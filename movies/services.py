"""Glue between the TMDB API client and Django ORM models."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterator

from django.contrib.auth.models import AbstractBaseUser
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, Q, QuerySet
from django.utils import timezone

from .models import Comment, Genre, Movie, MovieCredit, Person, Rating, UserMovieStatus
from .tmdb import (
    TmdbApiError,
    TmdbClient,
    TmdbConfigError,
    TmdbCredits,
    TmdbDiscoverResponse,
    TmdbMovieDetail,
    TmdbMovieSummary,
)

logger = logging.getLogger(__name__)

PERSONALIZED_SHELF_CACHE_TTL = 15 * 60

# TMDB caps `page` at 500 server-side; exceed it and the API returns 422.
# Kept as a hard upper bound for the inner pagination loop so we never issue
# a guaranteed-bad request, but the UI cap below is deliberately much lower.
TMDB_API_MAX_PAGE = 500
# Local cap on how deep the grid will let users paginate. TMDB's popularity
# and trending rankings get noisy well before page 500, and browsing that
# deep is vanishingly rare. 30 UI pages × 2 TMDB pages × 18 trimmed rows =
# ~1080 distinct movies, which is more than enough for a catalogue view.
MAX_UI_PAGES = 30
# Canonical UI page size, deliberately a multiple of 6 so a 6-column movie
# grid never ends with an orphan partial row. Used for both the local
# paginator and the TMDB-backed listings (which trim down to this count).
DEFAULT_PAGE_SIZE = 36
# Each TMDB /search/movie response is 20 rows. We stitch this many underlying
# TMDB pages together per UI page (40 raw rows) and trim down to
# DEFAULT_PAGE_SIZE so the visible grid stays clean.
TMDB_SEARCH_PAGES_PER_REQUEST = 2


# Canonical Polish names for the standard TMDB movie genres, keyed by their
# stable TMDB id. Used as a safety net so a polluted DB (e.g. one that was
# synced when language was still en-US) can be normalized to Polish without
# trusting whatever TMDB returns at sync time.
TMDB_GENRE_PL_NAMES: dict[int, str] = {
    28: "Akcja",  # Action
    12: "Przygodowy",  # Adventure
    16: "Animacja",  # Animation
    35: "Komedia",  # Comedy
    80: "Kryminał",  # Crime
    99: "Dokumentalny",  # Documentary
    18: "Dramat",  # Drama
    10751: "Familijny",  # Family
    14: "Fantasy",  # Fantasy
    36: "Historyczny",  # History
    27: "Horror",  # Horror
    10402: "Muzyka",  # Music
    9648: "Tajemnica",  # Mystery
    10749: "Romans",  # Romance
    878: "Science Fiction",  # Science Fiction
    10770: "Film telewizyjny",  # TV Movie
    53: "Thriller",  # Thriller
    10752: "Wojenny",  # War
    37: "Western",  # Western
}

# English → Polish mapping for stragglers that exist in the DB without a
# tmdb_id (e.g. rows manually created or from a botched first sync). Used by
# normalize_genres to fold them into the canonical Polish row.
GENRE_EN_TO_PL: dict[str, str] = {
    "Action": "Akcja",
    "Adventure": "Przygodowy",
    "Animation": "Animacja",
    "Comedy": "Komedia",
    "Crime": "Kryminał",
    "Documentary": "Dokumentalny",
    "Drama": "Dramat",
    "Family": "Familijny",
    "Fantasy": "Fantasy",
    "History": "Historyczny",
    "Horror": "Horror",
    "Music": "Muzyka",
    "Mystery": "Tajemnica",
    "Romance": "Romans",
    "Science Fiction": "Science Fiction",
    "Sci-Fi": "Science Fiction",
    "TV Movie": "Film telewizyjny",
    "Thriller": "Thriller",
    "War": "Wojenny",
    "Western": "Western",
}


@transaction.atomic
def _merge_genre(source: Genre, target: Genre) -> None:
    """Move every reference from `source` to `target`, then delete `source`.

    Transactional and bulk: M2M `add(*qs)` issues a single INSERT per side and
    `source.delete()` cascades the old through-rows. Safe to call from any
    context (does not rely on a caller-provided transaction).
    """
    source_pk = source.pk
    source_name = source.name
    user_count = source.users.count()
    movie_count = source.movies.count()
    target.users.add(*source.users.all())
    target.movies.add(*source.movies.all())
    source.delete()
    logger.info(
        "Merged genre id=%s name=%r into id=%s name=%r "
        "(moved %d user favorite(s), %d movie link(s))",
        source_pk,
        source_name,
        target.pk,
        target.name,
        user_count,
        movie_count,
    )


@transaction.atomic
def upsert_genre(tmdb_id: int, name: str) -> Genre:
    """Merge a TMDB genre into the local Genre table.

    Resolution order:
      1. Match by tmdb_id (already linked).
         a. If the name still matches, return as-is.
         b. If the name differs and is free, rename in place.
         c. If the new name collides with another row, merge the two
            (transferring user favorites and movie links) and keep the row
            that already has the canonical name.
      2. Match by case-insensitive name against an unlinked seeded row and
         attach tmdb_id to it.
      3. Create a brand new row.
    """
    by_id = Genre.objects.filter(tmdb_id=tmdb_id).first()
    if by_id is not None:
        if by_id.name == name:
            return by_id
        collision = Genre.objects.filter(name__iexact=name).exclude(pk=by_id.pk).first()
        if collision is None:
            logger.debug(
                "Renaming genre tmdb_id=%s from %r to %r", tmdb_id, by_id.name, name
            )
            by_id.name = name
            by_id.save(update_fields=["name"])
            return by_id
        # Two rows describe the same genre — fold by_id into collision and
        # promote collision as the canonical row for this tmdb_id.
        logger.info(
            "Genre name collision for tmdb_id=%s (%r); merging into existing row id=%s",
            tmdb_id,
            name,
            collision.pk,
        )
        _merge_genre(source=by_id, target=collision)
        collision.tmdb_id = tmdb_id
        collision.name = name
        collision.save(update_fields=["tmdb_id", "name"])
        return collision

    by_name = Genre.objects.filter(name__iexact=name, tmdb_id__isnull=True).first()
    if by_name is not None:
        logger.debug(
            "Attaching tmdb_id=%s to seeded genre id=%s (%r)",
            tmdb_id,
            by_name.pk,
            by_name.name,
        )
        by_name.tmdb_id = tmdb_id
        by_name.name = name  # normalize case to TMDB's
        by_name.save(update_fields=["tmdb_id", "name"])
        return by_name

    logger.debug("Creating new genre tmdb_id=%s name=%r", tmdb_id, name)
    return Genre.objects.create(tmdb_id=tmdb_id, name=name)


def sync_all_genres(client: TmdbClient) -> int:
    """Pull the TMDB genre dictionary and upsert each row.

    The TMDB-returned name is overridden by `TMDB_GENRE_PL_NAMES` whenever the
    id is known, so the local DB always ends up with the canonical Polish name
    even if TMDB returns an English fallback for some rows.
    """
    genres = client.list_genres()
    for tmdb_genre in genres:
        canonical = TMDB_GENRE_PL_NAMES.get(tmdb_genre.id, tmdb_genre.name)
        upsert_genre(tmdb_genre.id, canonical)
    return len(genres)


@transaction.atomic
def normalize_all_genres() -> dict[str, int]:
    """One-shot cleanup that consolidates a polluted Genre table.

    Two passes:
      1. For every entry in TMDB_GENRE_PL_NAMES, call upsert_genre with the
         Polish name. Re-uses the merge logic in upsert_genre to fold any
         English duplicate that already holds the tmdb_id into the Polish row.
      2. Walk every English-named row that still has no tmdb_id and look it up
         in GENRE_EN_TO_PL. If a Polish target row exists, merge into it; if
         not, just rename in place.

    Safe to run repeatedly. Returns a small report dict so the management
    command can print counts.
    """
    report = {"upserted": 0, "merged_orphans": 0, "renamed_orphans": 0}

    for tmdb_id, polish_name in TMDB_GENRE_PL_NAMES.items():
        upsert_genre(tmdb_id, polish_name)
        report["upserted"] += 1

    for english_name, polish_name in GENRE_EN_TO_PL.items():
        if english_name == polish_name:
            continue
        orphan = Genre.objects.filter(
            name__iexact=english_name, tmdb_id__isnull=True
        ).first()
        if orphan is None:
            continue
        target = (
            Genre.objects.filter(name__iexact=polish_name).exclude(pk=orphan.pk).first()
        )
        if target is not None:
            _merge_genre(source=orphan, target=target)
            report["merged_orphans"] += 1
        else:
            orphan.name = polish_name
            orphan.save(update_fields=["name"])
            report["renamed_orphans"] += 1

    return report


def _build_movie_defaults(
    payload: TmdbMovieSummary | TmdbMovieDetail, client: TmdbClient
) -> dict[str, Any]:
    runtime = getattr(payload, "runtime", None)
    return {
        "title": payload.title,
        "original_title": payload.original_title or "",
        "overview": payload.overview or "",
        "release_date": payload.release_date,
        "runtime_minutes": runtime,
        "poster_url": client.image_url(payload.poster_path),
        "backdrop_url": client.image_url(payload.backdrop_path),
        "original_language": payload.original_language or "",
        "popularity": (
            Decimal(str(payload.popularity)) if payload.popularity is not None else None
        ),
        "tmdb_synced_at": timezone.now(),
    }


def upsert_movie_summary(payload: TmdbMovieSummary, client: TmdbClient) -> Movie:
    movie, _ = Movie.objects.update_or_create(
        tmdb_id=payload.id,
        defaults=_build_movie_defaults(payload, client),
    )
    if payload.genre_ids:
        genres = list(Genre.objects.filter(tmdb_id__in=payload.genre_ids))
        movie.genres.set(genres)
    return movie


def upsert_movie_detail(payload: TmdbMovieDetail, client: TmdbClient) -> Movie:
    movie, _ = Movie.objects.update_or_create(
        tmdb_id=payload.id,
        defaults=_build_movie_defaults(payload, client),
    )
    if payload.genres:
        for tmdb_genre in payload.genres:
            upsert_genre(tmdb_genre.id, tmdb_genre.name)
        genres = list(Genre.objects.filter(tmdb_id__in=[g.id for g in payload.genres]))
        movie.genres.set(genres)
    if payload.credits:
        sync_movie_credits(movie, payload.credits, client)
    return movie


# Maximum number of cast members to store per movie.
MAX_CAST_PER_MOVIE = 10


@transaction.atomic
def sync_movie_credits(movie: Movie, credits: TmdbCredits, client: TmdbClient) -> None:
    """Persist directors and top-billed cast from a TMDB credits payload."""
    # Serialize concurrent backfills for the same movie. The dashboard can now
    # trigger multiple TMDB candidate fetches in parallel requests, and two
    # workers may try to "replace credits" on the same row at once.
    movie = Movie.objects.select_for_update().get(pk=movie.pk)
    directors = [c for c in credits.crew if c.job == "Director"]
    cast = sorted(credits.cast, key=lambda c: c.order)[:MAX_CAST_PER_MOVIE]

    bulk: list[MovieCredit] = []
    seen_credits: set[tuple[int, str]] = set()
    for member in directors:
        person, _ = Person.objects.update_or_create(
            tmdb_id=member.id,
            defaults={
                "name": member.name,
                "profile_url": client.image_url(member.profile_path),
            },
        )
        credit_key = (person.id, MovieCredit.DIRECTOR)
        if credit_key in seen_credits:
            continue
        seen_credits.add(credit_key)
        bulk.append(
            MovieCredit(
                movie=movie,
                person=person,
                credit_type=MovieCredit.DIRECTOR,
                order=0,
            )
        )

    for member in cast:
        person, _ = Person.objects.update_or_create(
            tmdb_id=member.id,
            defaults={
                "name": member.name,
                "profile_url": client.image_url(member.profile_path),
            },
        )
        credit_key = (person.id, MovieCredit.CAST)
        if credit_key in seen_credits:
            continue
        seen_credits.add(credit_key)
        bulk.append(
            MovieCredit(
                movie=movie,
                person=person,
                credit_type=MovieCredit.CAST,
                character=member.character or "",
                order=member.order,
            )
        )

    # Replace existing credits for this movie.
    MovieCredit.objects.filter(movie=movie).delete()
    # `ignore_conflicts=True` is a second line of defense against concurrent
    # inserts from another worker that raced us to the same unique tuple.
    MovieCredit.objects.bulk_create(bulk, ignore_conflicts=True)


def fetch_and_cache_movie(tmdb_id: int, client: TmdbClient | None = None) -> Movie:
    """Look up a movie locally; if missing, fetch from TMDB and persist.

    Also backfills credits for movies that were cached before the credits
    feature was added (no MovieCredit rows yet).
    """
    existing = Movie.objects.filter(tmdb_id=tmdb_id).first()
    if existing is not None:
        if existing.credits.exists():
            logger.debug("Movie cache hit tmdb_id=%s", tmdb_id)
            return existing
        # Cached before credits feature — backfill from TMDB.
        logger.info("Backfilling credits for tmdb_id=%s", tmdb_id)
        try:
            client = client or TmdbClient()
            detail = client.get_movie(tmdb_id)
            if detail.credits:
                sync_movie_credits(existing, detail.credits, client)
        except (TmdbConfigError, TmdbApiError) as exc:
            logger.warning("Credit backfill failed for tmdb_id=%s: %s", tmdb_id, exc)
        return existing
    logger.info("Movie cache miss tmdb_id=%s, fetching from TMDB", tmdb_id)
    client = client or TmdbClient()
    detail = client.get_movie(tmdb_id)
    movie = upsert_movie_detail(detail, client)
    logger.info("Cached TMDB movie tmdb_id=%s title=%r", tmdb_id, movie.title)
    return movie


# ── Listing adapters ─────────────────────────────────────────────────────────
# The list view needs to render rows from two sources (the local cache and
# live TMDB search results) without the template caring which one. The two
# tiny dataclasses below normalize both into a single shape and provide the
# same pagination attributes Django's Page object exposes.


@dataclass
class MovieListItem:
    """View-model row used by templates/movies/list.html."""

    tmdb_id: int
    title: str
    poster_url: str = ""
    release_date: date | None = None
    popularity: float | None = None

    @classmethod
    def from_local(cls, movie: Movie) -> "MovieListItem":
        return cls(
            tmdb_id=movie.tmdb_id,
            title=movie.title,
            poster_url=movie.poster_url,
            release_date=movie.release_date,
            popularity=float(movie.popularity)
            if movie.popularity is not None
            else None,
        )

    @classmethod
    def from_tmdb(
        cls, summary: TmdbMovieSummary, client: TmdbClient
    ) -> "MovieListItem":
        return cls(
            tmdb_id=summary.id,
            title=summary.title,
            poster_url=client.image_url(summary.poster_path),
            release_date=summary.release_date,
            popularity=summary.popularity,
        )


@dataclass
class MovieListPage:
    """Minimal page object compatible with the list template.

    Mirrors the subset of django.core.paginator.Page that the template uses
    so we can hand-build a page from a TMDB response without instantiating a
    Paginator.
    """

    object_list: list[MovieListItem]
    number: int
    num_pages: int

    def __iter__(self) -> Iterator[MovieListItem]:
        return iter(self.object_list)

    @property
    def has_previous(self) -> bool:
        return self.number > 1

    @property
    def has_next(self) -> bool:
        return self.number < self.num_pages

    @property
    def previous_page_number(self) -> int:
        return self.number - 1

    @property
    def next_page_number(self) -> int:
        return self.number + 1


def watched_tmdb_ids(user: AbstractBaseUser) -> set[int]:
    """tmdb_ids the user has marked as watched. Empty set for anon users."""
    if not getattr(user, "is_authenticated", False):
        return set()
    return set(
        UserMovieStatus.objects.filter(
            user=user, status=UserMovieStatus.WATCHED
        ).values_list("movie__tmdb_id", flat=True)
    )


def exclude_watched(
    items: Iterator[MovieListItem] | list[MovieListItem],
    watched_ids: set[int],
) -> list[MovieListItem]:
    """Drop items the user has already watched. Pass-through when set is empty."""
    if not watched_ids:
        return list(items)
    return [it for it in items if it.tmdb_id not in watched_ids]


def _coerce_genre_id(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        logger.debug("Ignoring non-integer genre filter: %r", raw)
        return None


def browse_local_movies(
    *,
    query: str = "",
    genre_id_raw: str | None = None,
    page: int = 1,
    per_page: int = DEFAULT_PAGE_SIZE,
) -> MovieListPage:
    """Paginate the locally cached Movie table with optional filters.

    Used both for plain browse mode and as a fallback when TMDB search is
    unavailable. The query is matched against `title` with icontains to
    preserve the previous local-search behaviour.
    """
    queryset: QuerySet[Movie] = Movie.objects.all().prefetch_related("genres")

    if query:
        queryset = queryset.filter(title__icontains=query)

    genre_id = _coerce_genre_id(genre_id_raw)
    if genre_id is not None:
        queryset = queryset.filter(genres__id=genre_id)

    queryset = queryset.distinct()

    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(page)

    return MovieListPage(
        object_list=[MovieListItem.from_local(m) for m in page_obj.object_list],
        number=page_obj.number,
        num_pages=paginator.num_pages,
    )


def _resolve_tmdb_genre_id(genre_id_raw: str | None) -> int | None:
    """Map a local Genre PK to the corresponding TMDB genre id.

    Returns None when no filter is applied or when the local row has no
    TMDB linkage (e.g. a custom genre that was never synced).
    """
    genre_id = _coerce_genre_id(genre_id_raw)
    if genre_id is None:
        return None
    local_genre = Genre.objects.filter(pk=genre_id).first()
    if local_genre is None or local_genre.tmdb_id is None:
        return None
    return local_genre.tmdb_id


def discover_tmdb_movies(
    *,
    genre_id_raw: str | None = None,
    page: int = 1,
    client: TmdbClient | None = None,
    pages_per_ui: int = TMDB_SEARCH_PAGES_PER_REQUEST,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> MovieListPage:
    """Browse movies live from TMDB.

    Two data sources depending on what filters apply:

    * Unfiltered browse hits `/trending/movie/week`, so the base rail
      reshuffles weekly instead of showing the same popularity-ranked top-40
      on every visit.
    * When a genre filter is picked, we switch to `/discover/movie` with
      `with_genres` so the filtering happens server-side. TMDB's trending
      endpoint does not accept `with_genres`, so this split keeps filtering
      exact without resorting to client-side post-filtering.

    Same pagination scheme as search: stitch `pages_per_ui` underlying TMDB
    pages together so the user sees ~40 results per UI page.
    """
    client = client or TmdbClient()

    safe_ui_page = max(1, min(page, MAX_UI_PAGES))

    selected_tmdb_id = _resolve_tmdb_genre_id(genre_id_raw)
    with_genres = str(selected_tmdb_id) if selected_tmdb_id is not None else None
    use_trending = with_genres is None

    items: list[MovieListItem] = []
    tmdb_total_pages = 1

    for offset in range(pages_per_ui):
        tmdb_page = (safe_ui_page - 1) * pages_per_ui + 1 + offset
        if tmdb_page > TMDB_API_MAX_PAGE:
            break

        if use_trending:
            response = client.list_trending(time_window="week", page=tmdb_page)
        else:
            response = client.discover_popular(page=tmdb_page, with_genres=with_genres)

        if offset == 0:
            tmdb_total_pages = response.total_pages

        for summary in response.results:
            items.append(MovieListItem.from_tmdb(summary, client))

        if tmdb_page >= response.total_pages:
            break

    ui_total_pages = max(
        1,
        min(
            MAX_UI_PAGES,
            (tmdb_total_pages + pages_per_ui - 1) // pages_per_ui,
        ),
    )

    return MovieListPage(
        object_list=items[:page_size],
        number=safe_ui_page,
        num_pages=ui_total_pages,
    )


# ── Shelves: curated rails for the home & browse surfaces ────────────────────
# Each helper returns a flat list[MovieListItem] (capped at `limit`) so the
# template can iterate without worrying about pagination. All three swallow
# config / API errors and return an empty list — shelves are decorative and
# must never break the page.


SHELF_LIMIT = 18


def _tmdb_shelf(
    fetch,
    *,
    limit: int = SHELF_LIMIT,
    label: str = "shelf",
) -> list[MovieListItem]:
    """Shared error-swallowing wrapper for a single TMDB shelf fetch."""
    try:
        client = TmdbClient()
        response = fetch(client)
    except TmdbConfigError:
        logger.debug("TMDB shelf %s skipped: TMDB_API_KEY not configured", label)
        return []
    except TmdbApiError as exc:
        logger.warning("TMDB shelf %s failed: %s", label, exc)
        return []
    items: list[MovieListItem] = []
    for summary in response.results:
        if not _is_released(summary.release_date):
            continue
        items.append(MovieListItem.from_tmdb(summary, client))
        if len(items) >= limit:
            break
    return items


def fetch_trending_shelf(*, limit: int = SHELF_LIMIT) -> list[MovieListItem]:
    return _tmdb_shelf(
        lambda c: c.list_trending(time_window="week"),
        limit=limit,
        label="trending",
    )


def fetch_top_rated_shelf(*, limit: int = SHELF_LIMIT) -> list[MovieListItem]:
    return _tmdb_shelf(
        lambda c: c.list_top_rated(),
        limit=limit,
        label="top_rated",
    )


def fetch_genre_shelf(
    *, tmdb_genre_id: int, limit: int = SHELF_LIMIT
) -> list[MovieListItem]:
    return _tmdb_shelf(
        lambda c: c.discover_popular(page=1, with_genres=str(tmdb_genre_id)),
        limit=limit,
        label=f"genre:{tmdb_genre_id}",
    )


# ── Curated "identity" shelves ───────────────────────────────────────────────
# These rails pull from signals unique to Aster (community ratings, a user's
# own history, an editorial pick) rather than generic TMDB feeds. Every helper
# returns an empty list on any failure so the shelves section stays
# decoration-only and can't break the page.


# Minimum number of Aster users who must have rated a movie before it's
# eligible for the "Najwyżej oceniane w Aster" shelf. A single enthusiastic
# user shouldn't be able to crown an obscure title with one 5-star vote, so
# we require at least two independent ratings before a film can appear.
COMMUNITY_MIN_RATINGS = 2


def fetch_community_top_rated_shelf(
    *, limit: int = SHELF_LIMIT, min_ratings: int = COMMUNITY_MIN_RATINGS
) -> list[MovieListItem]:
    """Local top-rated rail driven by Aster's own Rating rows.

    Uses the cached `average_rating` / `ratings_count` aggregates on Movie —
    no TMDB call. Eligibility requires at least `min_ratings` distinct
    ratings so one enthusiastic user can't put a random film at the top.
    """
    movies = (
        Movie.objects.filter(ratings_count__gte=min_ratings)
        .filter(_released_movie_q())
        .order_by("-average_rating", "-ratings_count", "-popularity")[:limit]
    )
    return [MovieListItem.from_local(m) for m in movies]


def _interacted_movie_ids(user: AbstractBaseUser) -> set[int]:
    """Ids of every movie the user already rated, watchlisted, or watched.

    Used to filter personalised shelves so TMDB never recommends something
    the user has already engaged with. Shared by the "seeded
    recommendations" and "continue exploring" shelves.
    """
    ids: set[int] = set()
    ids.update(Rating.objects.filter(user=user).values_list("movie_id", flat=True))
    ids.update(
        UserMovieStatus.objects.filter(user=user).values_list("movie_id", flat=True)
    )
    return ids


def _interacted_tmdb_ids(user: AbstractBaseUser) -> set[int]:
    """Same as _interacted_movie_ids but keyed by tmdb_id instead of PK."""
    local_ids = _interacted_movie_ids(user)
    if not local_ids:
        return set()
    return set(Movie.objects.filter(id__in=local_ids).values_list("tmdb_id", flat=True))


def _personal_shelf_version_key(user_id: int) -> str:
    return f"user-shelf-version:{user_id}"


def _personal_shelf_version(user_id: int) -> int:
    version = cache.get(_personal_shelf_version_key(user_id))
    return int(version) if version is not None else 1


def _personal_shelf_cache_key(
    name: str, user_id: int, *, limit: int, extra: str = ""
) -> str:
    version = _personal_shelf_version(user_id)
    suffix = f":{extra}" if extra else ""
    return f"user-shelf:v{version}:user:{user_id}:{name}:limit:{limit}{suffix}"


def bust_personalized_shelves_cache(user: AbstractBaseUser) -> None:
    """Rotate the cache namespace for per-user browse shelves."""
    if user is None or not getattr(user, "pk", None):
        return
    version_key = _personal_shelf_version_key(user.pk)
    current = _personal_shelf_version(user.pk)
    cache.set(version_key, current + 1, None)


def _pick_recommendation_seed(user: AbstractBaseUser) -> Rating | None:
    """Pick the rating that will seed "Bo oceniłeś wysoko" recommendations.

    Prefers the user's highest score; among equal-scored ratings, the most
    recently updated one wins so the shelf refreshes as the user rates more
    films. Returns None when the user has no ratings at all.
    """
    return (
        Rating.objects.filter(user=user)
        .select_related("movie")
        .order_by("-score", "-updated_at")
        .first()
    )


def fetch_seeded_recommendations_shelf(
    user: AbstractBaseUser, *, limit: int = SHELF_LIMIT
) -> tuple[Movie | None, list[MovieListItem]]:
    """TMDB recommendations seeded from the user's favourite rated movie.

    Returns `(seed_movie, items)`. `seed_movie` is None when the user has no
    ratings; `items` is empty when TMDB is unavailable or the seed has no
    recommendations. The caller uses the seed to label the rail
    ("Bo oceniłeś wysoko „Seven”").
    """
    cache_key = _personal_shelf_cache_key("seeded", user.pk, limit=limit)
    cached = cache.get(cache_key)
    if cached is not None:
        seed_movie_id = cached["seed_movie_id"]
        seed_movie = (
            Movie.objects.filter(pk=seed_movie_id).first() if seed_movie_id else None
        )
        return seed_movie, cached["items"]

    seed_rating = _pick_recommendation_seed(user)
    if seed_rating is None:
        cache.set(
            cache_key,
            {"seed_movie_id": None, "items": []},
            PERSONALIZED_SHELF_CACHE_TTL,
        )
        return None, []
    seed_movie = seed_rating.movie
    excluded = _interacted_tmdb_ids(user)

    try:
        client = TmdbClient()
        response = client.get_movie_recommendations(seed_movie.tmdb_id)
    except TmdbConfigError:
        logger.debug(
            "Seeded recommendations skipped: TMDB_API_KEY not configured",
        )
        return seed_movie, []
    except TmdbApiError as exc:
        logger.warning(
            "TMDB recommendations failed for tmdb_id=%s: %s",
            seed_movie.tmdb_id,
            exc,
        )
        return seed_movie, []

    items: list[MovieListItem] = []
    for summary in response.results:
        if summary.id in excluded:
            continue
        if not _is_released(summary.release_date):
            continue
        items.append(MovieListItem.from_tmdb(summary, client))
        if len(items) >= limit:
            break
    cache.set(
        cache_key,
        {"seed_movie_id": seed_movie.pk, "items": items},
        PERSONALIZED_SHELF_CACHE_TTL,
    )
    return seed_movie, items


def _pick_watched_seed(
    user: AbstractBaseUser, *, exclude_movie_ids: set[int] | None = None
) -> Movie | None:
    """Most-recently watched movie for the user, optionally skipping any
    already used as a seed elsewhere on the page (e.g. the rated shelf).

    Returns None when the user has no watched entries — or when every one
    is in `exclude_movie_ids`. Walks rows newest-first so caller can keep
    asking for the next-best seed if needed.
    """
    qs = (
        UserMovieStatus.objects.filter(user=user, status=UserMovieStatus.WATCHED)
        .select_related("movie")
        .order_by("-updated_at")
    )
    if exclude_movie_ids:
        qs = qs.exclude(movie_id__in=exclude_movie_ids)
    row = qs.first()
    return row.movie if row else None


def fetch_recently_watched_recommendations_shelf(
    user: AbstractBaseUser,
    *,
    limit: int = SHELF_LIMIT,
    exclude_seed_movie_ids: set[int] | None = None,
) -> tuple[Movie | None, list[MovieListItem]]:
    """TMDB recommendations seeded from the user's most recently watched movie.

    Mirrors `fetch_seeded_recommendations_shelf` but draws its signal from
    watch history, so the rail still works for users who mark films watched
    without rating them. Returns `(seed_movie, items)`.

    `exclude_seed_movie_ids` lets the caller skip seeds already used by
    another rail (typically the rated-recommendations seed) so we don't
    render two near-identical rails seeded from the same title.
    """
    excluded_seed_ids = sorted(exclude_seed_movie_ids or set())
    cache_key = _personal_shelf_cache_key(
        "watched",
        user.pk,
        limit=limit,
        extra=",".join(str(movie_id) for movie_id in excluded_seed_ids),
    )
    cached = cache.get(cache_key)
    if cached is not None:
        seed_movie_id = cached["seed_movie_id"]
        seed_movie = (
            Movie.objects.filter(pk=seed_movie_id).first() if seed_movie_id else None
        )
        return seed_movie, cached["items"]

    seed_movie = _pick_watched_seed(user, exclude_movie_ids=exclude_seed_movie_ids)
    if seed_movie is None:
        cache.set(
            cache_key,
            {"seed_movie_id": None, "items": []},
            PERSONALIZED_SHELF_CACHE_TTL,
        )
        return None, []

    excluded = _interacted_tmdb_ids(user)

    try:
        client = TmdbClient()
        response = client.get_movie_recommendations(seed_movie.tmdb_id)
    except TmdbConfigError:
        logger.debug("Watched recommendations skipped: TMDB_API_KEY not configured")
        return seed_movie, []
    except TmdbApiError as exc:
        logger.warning(
            "TMDB recommendations failed for tmdb_id=%s: %s",
            seed_movie.tmdb_id,
            exc,
        )
        return seed_movie, []

    items: list[MovieListItem] = []
    for summary in response.results:
        if summary.id in excluded:
            continue
        if not _is_released(summary.release_date):
            continue
        items.append(MovieListItem.from_tmdb(summary, client))
        if len(items) >= limit:
            break
    cache.set(
        cache_key,
        {"seed_movie_id": seed_movie.pk, "items": items},
        PERSONALIZED_SHELF_CACHE_TTL,
    )
    return seed_movie, items


def _pick_exploration_person(user: AbstractBaseUser) -> Person | None:
    """Pick the director/actor most represented in the user's liked ratings.

    Directors are preferred over actors for equal counts (strong auteur
    signal). Returns None when there are no liked ratings or no credits
    cached for them yet.
    """
    liked_movie_ids = list(
        Rating.objects.filter(user=user, score__gte=LIKED_RATING_THRESHOLD).values_list(
            "movie_id", flat=True
        )
    )
    if not liked_movie_ids:
        return None

    counts = (
        MovieCredit.objects.filter(movie_id__in=liked_movie_ids)
        .filter(
            Q(credit_type=MovieCredit.DIRECTOR)
            | Q(credit_type=MovieCredit.CAST, order__lt=TOP_BILLED_CAST_LIMIT)
        )
        .values("person_id", "credit_type")
        .annotate(count=Count("id"))
    )
    # Sort directors first, then by count desc — so a director tied with an
    # actor on count still wins.
    ranked = sorted(
        counts,
        key=lambda r: (
            r["credit_type"] != MovieCredit.DIRECTOR,
            -r["count"],
        ),
    )
    for row in ranked:
        person = Person.objects.filter(pk=row["person_id"]).first()
        if person is not None and person.tmdb_id:
            return person
    return None


def fetch_continue_exploring_shelf(
    user: AbstractBaseUser, *, limit: int = SHELF_LIMIT
) -> tuple[Person | None, list[MovieListItem]]:
    """Filmography rail for the person the user has rated most often.

    Returns `(person, items)`. When no signal is available or TMDB is
    unreachable, returns `(None, [])` / `(person, [])` so the caller can
    drop the shelf silently.
    """
    cache_key = _personal_shelf_cache_key("explore", user.pk, limit=limit)
    cached = cache.get(cache_key)
    if cached is not None:
        person_id = cached["person_id"]
        person = Person.objects.filter(pk=person_id).first() if person_id else None
        return person, cached["items"]

    person = _pick_exploration_person(user)
    if person is None or person.tmdb_id is None:
        cache.set(
            cache_key,
            {"person_id": None, "items": []},
            PERSONALIZED_SHELF_CACHE_TTL,
        )
        return None, []

    excluded = _interacted_tmdb_ids(user)

    try:
        client = TmdbClient()
        response = client.get_person_movie_credits(person.tmdb_id)
    except TmdbConfigError:
        logger.debug("Continue-exploring skipped: TMDB_API_KEY not configured")
        return person, []
    except TmdbApiError as exc:
        logger.warning(
            "TMDB person credits failed for tmdb_id=%s: %s", person.tmdb_id, exc
        )
        return person, []

    items: list[MovieListItem] = []
    for summary in response.results:
        if summary.id in excluded:
            continue
        if not _is_released(summary.release_date):
            continue
        if not summary.poster_path:
            # Skip filmography entries with no artwork — the shelf is visual.
            continue
        items.append(MovieListItem.from_tmdb(summary, client))
        if len(items) >= limit:
            break
    cache.set(
        cache_key,
        {"person_id": person.pk, "items": items},
        PERSONALIZED_SHELF_CACHE_TTL,
    )
    return person, items


# TMDB's ISO-639-1 code for Polish. Isolated as a constant so the intent is
# obvious at the call site.
POLISH_LANGUAGE_CODE = "pl"
# Vote-count floor for the Polish cinema rail: excludes obscure shorts and
# festival one-offs that have a handful of votes and inflated averages.
POLISH_CINEMA_MIN_VOTES = 50


def fetch_polish_cinema_shelf(*, limit: int = SHELF_LIMIT) -> list[MovieListItem]:
    """Editorial rail: highest-rated Polish-language films on TMDB."""
    return _tmdb_shelf(
        lambda c: c.discover_popular(
            page=1,
            with_original_language=POLISH_LANGUAGE_CODE,
            vote_count_gte=POLISH_CINEMA_MIN_VOTES,
            sort_by="vote_average.desc",
        ),
        limit=limit,
        label="polish_cinema",
    )


def search_tmdb_movies(
    *,
    query: str,
    genre_id_raw: str | None = None,
    page: int = 1,
    client: TmdbClient | None = None,
    pages_per_ui: int = TMDB_SEARCH_PAGES_PER_REQUEST,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> MovieListPage:
    """Search TMDB live and adapt the response to the list template.

    A single UI page maps to `pages_per_ui` underlying TMDB pages so the user
    sees ~40 raw results at a time instead of TMDB's default 20; the result
    is then trimmed to `page_size` so the rendered grid stays a clean
    multiple of the column count. When `genre_id_raw` is supplied, the local
    Genre row is resolved to its TMDB id and the returned summaries are
    post-filtered client-side; TMDB's /search/movie endpoint does not accept
    `with_genres`, so this is the cleanest way to combine free-text search
    with a genre constraint.
    """
    client = client or TmdbClient()

    safe_ui_page = max(1, min(page, MAX_UI_PAGES))

    tmdb_genre_id = _resolve_tmdb_genre_id(genre_id_raw)

    items: list[MovieListItem] = []
    tmdb_total_pages = 1

    for offset in range(pages_per_ui):
        tmdb_page = (safe_ui_page - 1) * pages_per_ui + 1 + offset
        if tmdb_page > TMDB_API_MAX_PAGE:
            break

        response = client.search_movies(query=query, page=tmdb_page)

        if offset == 0:
            tmdb_total_pages = response.total_pages

        for summary in response.results:
            if tmdb_genre_id is not None and tmdb_genre_id not in summary.genre_ids:
                continue
            items.append(MovieListItem.from_tmdb(summary, client))

        # No more underlying pages available — stop early so we don't waste
        # an HTTP call on a guaranteed-empty response.
        if tmdb_page >= response.total_pages:
            break

    ui_total_pages = max(
        1,
        min(
            MAX_UI_PAGES,
            (tmdb_total_pages + pages_per_ui - 1) // pages_per_ui,
        ),
    )

    return MovieListPage(
        object_list=items[:page_size],
        number=safe_ui_page,
        num_pages=ui_total_pages,
    )


# ── User activity: watchlist / watched / rating ──────────────────────────────
# These helpers encapsulate the write-side logic for the three "my movies"
# features. They keep the cached aggregates on Movie (average_rating,
# ratings_count) in sync so the detail and list views can render without
# recomputing on every request.


@transaction.atomic
def set_movie_status(*, user, movie: Movie, status: str) -> UserMovieStatus:
    """Create or flip a user↔movie status.

    Accepted `status` values are the class constants on UserMovieStatus.
    Raises ValueError on anything else so the view layer doesn't have to.
    """
    if status not in {UserMovieStatus.WATCHLIST, UserMovieStatus.WATCHED}:
        raise ValueError(f"Invalid status: {status!r}")
    obj, _ = UserMovieStatus.objects.update_or_create(
        user=user, movie=movie, defaults={"status": status}
    )
    bust_recommendations_cache(user)
    logger.info(
        "User id=%s set status=%s on movie tmdb_id=%s",
        user.pk,
        status,
        movie.tmdb_id,
    )
    return obj


@transaction.atomic
def remove_movie_status(*, user, movie: Movie) -> bool:
    """Delete any status row for (user, movie). Returns True if one existed."""
    deleted, _ = UserMovieStatus.objects.filter(user=user, movie=movie).delete()
    if deleted:
        bust_recommendations_cache(user)
        logger.info(
            "User id=%s cleared status on movie tmdb_id=%s",
            user.pk,
            movie.tmdb_id,
        )
    return bool(deleted)


def _refresh_movie_rating_aggregates(movie: Movie) -> None:
    """Recompute average_rating and ratings_count from the ratings table.

    Called from inside the transaction that mutates a Rating row, so the
    cached aggregates on Movie stay consistent with the source of truth.
    The two-decimal quantization matches the DecimalField definition.
    """
    stats = Rating.objects.filter(movie=movie).aggregate(
        avg=Avg("score"), total=Count("id")
    )
    total = stats["total"] or 0
    avg = stats["avg"]
    if total == 0 or avg is None:
        movie.average_rating = Decimal("0.00")
    else:
        movie.average_rating = Decimal(str(avg)).quantize(Decimal("0.01"))
    movie.ratings_count = total
    movie.save(update_fields=["average_rating", "ratings_count", "updated_at"])


@transaction.atomic
def upsert_rating(*, user, movie: Movie, score: Decimal | float | int) -> Rating:
    """Create or update a user's rating and refresh the movie aggregates.

    Accepts int, float, or Decimal scores in 0.5 increments between 0.5 and
    5.0. Rating a movie implies the user has watched it, so we also ensure
    the user↔movie status row exists with `status=WATCHED`. This promotes a
    prior `watchlist` row to `watched` via update_or_create, and is a no-op
    when the row is already watched.
    """
    score_dec = Decimal(str(score))
    if not (Rating.MIN_SCORE <= score_dec <= Rating.MAX_SCORE):
        raise ValueError(
            f"Score must be between {Rating.MIN_SCORE} and {Rating.MAX_SCORE}"
        )
    if score_dec % Rating.SCORE_STEP != 0:
        raise ValueError("Score must be in 0.5 increments")
    rating, created = Rating.objects.update_or_create(
        user=user, movie=movie, defaults={"score": score_dec}
    )
    _refresh_movie_rating_aggregates(movie)
    UserMovieStatus.objects.update_or_create(
        user=user,
        movie=movie,
        defaults={"status": UserMovieStatus.WATCHED},
    )
    bust_recommendations_cache(user)
    logger.info(
        "User id=%s %s rating=%s for movie tmdb_id=%s (status auto-set to watched)",
        user.pk,
        "created" if created else "updated",
        score_dec,
        movie.tmdb_id,
    )
    return rating


@transaction.atomic
def remove_rating(*, user, movie: Movie) -> bool:
    """Delete a user's rating (if present) and refresh movie aggregates."""
    deleted, _ = Rating.objects.filter(user=user, movie=movie).delete()
    if deleted:
        _refresh_movie_rating_aggregates(movie)
        bust_recommendations_cache(user)
        logger.info(
            "User id=%s removed rating on movie tmdb_id=%s",
            user.pk,
            movie.tmdb_id,
        )
    return bool(deleted)


# ── Comments ────────────────────────────────────────────────────────────────
# Thin wrappers so the view layer doesn't touch the ORM directly. Keeping
# the moderation fields (status, toxicity_score, moderated_at) here means the
# phase-2 moderation panel can plug into these helpers without rewriting the
# create/delete path.


def visible_comments_for(movie: Movie) -> QuerySet[Comment]:
    """All user-facing comments for a movie, newest first."""
    return Comment.objects.filter(movie=movie, status=Comment.VISIBLE).select_related(
        "user"
    )


@transaction.atomic
def create_comment(*, user, movie: Movie, content: str) -> Comment:
    """Persist a new comment after trimming whitespace.

    Length-capping is enforced by the model field, but we trim here so the
    form can't submit a comment that is only whitespace.
    """
    trimmed = (content or "").strip()
    if not trimmed:
        raise ValueError("Comment content must not be empty.")
    if len(trimmed) > Comment.MAX_LENGTH:
        raise ValueError(
            f"Comment content must not exceed {Comment.MAX_LENGTH} characters."
        )
    comment = Comment.objects.create(
        user=user,
        movie=movie,
        content=trimmed,
        status=Comment.VISIBLE,
    )
    logger.info(
        "User id=%s added comment id=%s on movie tmdb_id=%s",
        user.pk,
        comment.pk,
        movie.tmdb_id,
    )
    return comment


@transaction.atomic
def delete_own_comment(*, user, comment: Comment) -> bool:
    """Hard-delete a comment if it belongs to the given user.

    Returns True when a row was removed. Ownership check lives here so the
    view layer doesn't have to repeat the permission logic.
    """
    if comment.user_id != user.pk:
        return False
    comment_id = comment.pk
    movie_tmdb_id = comment.movie.tmdb_id
    comment.delete()
    logger.info(
        "User id=%s deleted own comment id=%s on movie tmdb_id=%s",
        user.pk,
        comment_id,
        movie_tmdb_id,
    )
    return True


# ── Recommendations ────────────────────────────────────────────────────────
# Content-based recommendations using three signal types extracted from
# movies the user rated highly, explicit favorite genres, and watched-only
# history (weaker than an explicit rating):
#   1. Genre overlap
#   2. Director match
#   3. Actor match
# The weighted sum is the primary sort key, with TMDB popularity as tiebreaker.

# Minimum rating score for a movie to count as "liked" and contribute its
# genres / credits to the recommendation pool.
LIKED_RATING_THRESHOLD = 4
# Ratings at or below this threshold become negative recommendation signals.
DISLIKED_RATING_THRESHOLD = Decimal("2.5")
# Default cap on how many recommendations to return.
DEFAULT_RECOMMENDATION_LIMIT = 12

# Scoring weights for each signal type. The liked/favorite weights preserve
# the previous 1:3:2 ratio, rescaled so watched-only signals can contribute
# at half strength without needing fractional DB expressions.
WEIGHT_LIKED_GENRE = 2
WEIGHT_LIKED_DIRECTOR = 6
WEIGHT_LIKED_ACTOR = 4
WEIGHT_WATCHED_GENRE = 1
WEIGHT_WATCHED_DIRECTOR = 3
WEIGHT_WATCHED_ACTOR = 2
WEIGHT_DISLIKED_GENRE = 2
WEIGHT_DISLIKED_DIRECTOR = 6
WEIGHT_DISLIKED_ACTOR = 4

# Only the first few billed cast members count as a recommendation signal.
TOP_BILLED_CAST_LIMIT = 3

# TMDB candidate expansion for the dashboard recommender. The external pool is
# intentionally bounded so the dashboard does not explode into dozens of HTTP
# calls when a user has a deep history.
TMDB_RECOMMENDATION_SEED_LIMIT = 3
TMDB_WATCHED_SEED_LIMIT = 2
TMDB_GENRE_DISCOVERY_LIMIT = 2
TMDB_CANDIDATE_POOL_LIMIT = 36


@dataclass
class RecommendationSignals:
    explicit_genre_ids: set[int]
    watched_genre_ids: set[int]
    liked_director_ids: set[int]
    watched_director_ids: set[int]
    liked_actor_ids: set[int]
    watched_actor_ids: set[int]
    disliked_genre_ids: set[int]
    disliked_director_ids: set[int]
    disliked_actor_ids: set[int]
    interacted_movie_ids: set[int]
    interacted_tmdb_ids: set[int]
    seed_movie_tmdb_ids: list[int]
    watched_seed_tmdb_ids: list[int]
    discovery_genre_tmdb_ids: list[int]

    def has_positive_signals(self) -> bool:
        return bool(
            self.explicit_genre_ids
            or self.watched_genre_ids
            or self.liked_director_ids
            or self.watched_director_ids
            or self.liked_actor_ids
            or self.watched_actor_ids
        )


def _released_movie_q() -> Q:
    today = timezone.localdate()
    return Q(release_date__isnull=True) | Q(release_date__lte=today)


def _is_released(release_date: date | None) -> bool:
    return release_date is None or release_date <= timezone.localdate()


def _genre_ids_for(movie_ids: set[int]) -> set[int]:
    if not movie_ids:
        return set()
    return set(
        Genre.objects.filter(movies__id__in=movie_ids).values_list("id", flat=True)
    )


def _person_ids_for(
    movie_ids: set[int],
    *,
    credit_type: str,
    top_billed_only: bool = False,
) -> set[int]:
    if not movie_ids:
        return set()
    qs = MovieCredit.objects.filter(
        movie_id__in=movie_ids,
        credit_type=credit_type,
    )
    if credit_type == MovieCredit.CAST and top_billed_only:
        qs = qs.filter(order__lt=TOP_BILLED_CAST_LIMIT)
    return set(qs.values_list("person_id", flat=True))


def _build_recommendation_signals(user: AbstractBaseUser) -> RecommendationSignals:
    ratings_qs = Rating.objects.filter(user=user).select_related("movie")
    liked_ratings = ratings_qs.filter(score__gte=LIKED_RATING_THRESHOLD)
    disliked_ratings = ratings_qs.filter(score__lte=DISLIKED_RATING_THRESHOLD)

    liked_movie_ids: set[int] = set(liked_ratings.values_list("movie_id", flat=True))
    disliked_movie_ids: set[int] = set(
        disliked_ratings.values_list("movie_id", flat=True)
    )
    rated_movie_ids: set[int] = set(ratings_qs.values_list("movie_id", flat=True))

    status_qs = UserMovieStatus.objects.filter(user=user)
    watched_movie_ids: set[int] = set(
        status_qs.filter(status=UserMovieStatus.WATCHED).values_list(
            "movie_id", flat=True
        )
    )
    watched_only_movie_ids = watched_movie_ids - rated_movie_ids

    favorite_genre_ids = set(user.favorite_genres.values_list("id", flat=True))
    favorite_tmdb_genres = list(
        user.favorite_genres.filter(tmdb_id__isnull=False).values("tmdb_id")
    )

    explicit_genre_ids = _genre_ids_for(liked_movie_ids) | favorite_genre_ids
    watched_genre_ids = _genre_ids_for(watched_only_movie_ids)

    discovery_genre_tmdb_ids = [row["tmdb_id"] for row in favorite_tmdb_genres][
        :TMDB_GENRE_DISCOVERY_LIMIT
    ]
    if (
        len(discovery_genre_tmdb_ids) < TMDB_GENRE_DISCOVERY_LIMIT
        and explicit_genre_ids
    ):
        extra_tmdb_ids = list(
            Genre.objects.filter(id__in=explicit_genre_ids, tmdb_id__isnull=False)
            .exclude(tmdb_id__in=discovery_genre_tmdb_ids)
            .values_list("tmdb_id", flat=True)[:TMDB_GENRE_DISCOVERY_LIMIT]
        )
        for tmdb_id in extra_tmdb_ids:
            if len(discovery_genre_tmdb_ids) >= TMDB_GENRE_DISCOVERY_LIMIT:
                break
            discovery_genre_tmdb_ids.append(tmdb_id)

    liked_director_ids = _person_ids_for(
        liked_movie_ids,
        credit_type=MovieCredit.DIRECTOR,
    )
    watched_director_ids = _person_ids_for(
        watched_only_movie_ids,
        credit_type=MovieCredit.DIRECTOR,
    )
    liked_actor_ids = _person_ids_for(
        liked_movie_ids,
        credit_type=MovieCredit.CAST,
        top_billed_only=True,
    )
    watched_actor_ids = _person_ids_for(
        watched_only_movie_ids,
        credit_type=MovieCredit.CAST,
        top_billed_only=True,
    )

    disliked_genre_ids = _genre_ids_for(disliked_movie_ids)
    disliked_director_ids = _person_ids_for(
        disliked_movie_ids,
        credit_type=MovieCredit.DIRECTOR,
    )
    disliked_actor_ids = _person_ids_for(
        disliked_movie_ids,
        credit_type=MovieCredit.CAST,
        top_billed_only=True,
    )

    interacted_movie_ids = rated_movie_ids | set(
        status_qs.values_list("movie_id", flat=True)
    )
    interacted_tmdb_ids = set(
        Movie.objects.filter(id__in=interacted_movie_ids).values_list(
            "tmdb_id", flat=True
        )
    )

    seed_movie_tmdb_ids = list(
        liked_ratings.order_by("-score", "-updated_at").values_list(
            "movie__tmdb_id", flat=True
        )[:TMDB_RECOMMENDATION_SEED_LIMIT]
    )
    watched_seed_tmdb_ids = list(
        status_qs.filter(status=UserMovieStatus.WATCHED)
        .exclude(movie_id__in=rated_movie_ids)
        .order_by("-updated_at")
        .values_list("movie__tmdb_id", flat=True)[:TMDB_WATCHED_SEED_LIMIT]
    )

    return RecommendationSignals(
        explicit_genre_ids=explicit_genre_ids,
        watched_genre_ids=watched_genre_ids,
        liked_director_ids=liked_director_ids,
        watched_director_ids=watched_director_ids,
        liked_actor_ids=liked_actor_ids,
        watched_actor_ids=watched_actor_ids,
        disliked_genre_ids=disliked_genre_ids,
        disliked_director_ids=disliked_director_ids,
        disliked_actor_ids=disliked_actor_ids,
        interacted_movie_ids=interacted_movie_ids,
        interacted_tmdb_ids=interacted_tmdb_ids,
        seed_movie_tmdb_ids=seed_movie_tmdb_ids,
        watched_seed_tmdb_ids=watched_seed_tmdb_ids,
        discovery_genre_tmdb_ids=discovery_genre_tmdb_ids,
    )


def _recommendation_match_q(signals: RecommendationSignals) -> Q:
    parts: list[Q] = []
    if signals.explicit_genre_ids:
        parts.append(Q(genres__id__in=signals.explicit_genre_ids))
    if signals.watched_genre_ids:
        parts.append(Q(genres__id__in=signals.watched_genre_ids))
    if signals.liked_director_ids:
        parts.append(
            Q(
                credits__person_id__in=signals.liked_director_ids,
                credits__credit_type=MovieCredit.DIRECTOR,
            )
        )
    if signals.watched_director_ids:
        parts.append(
            Q(
                credits__person_id__in=signals.watched_director_ids,
                credits__credit_type=MovieCredit.DIRECTOR,
            )
        )
    if signals.liked_actor_ids:
        parts.append(
            Q(
                credits__person_id__in=signals.liked_actor_ids,
                credits__credit_type=MovieCredit.CAST,
                credits__order__lt=TOP_BILLED_CAST_LIMIT,
            )
        )
    if signals.watched_actor_ids:
        parts.append(
            Q(
                credits__person_id__in=signals.watched_actor_ids,
                credits__credit_type=MovieCredit.CAST,
                credits__order__lt=TOP_BILLED_CAST_LIMIT,
            )
        )

    match_q = Q(pk__in=[])
    for part in parts:
        match_q |= part
    return match_q


def _fetch_tmdb_recommendation_candidates(
    signals: RecommendationSignals,
) -> list[Movie]:
    try:
        client = TmdbClient()
    except TmdbConfigError:
        return []

    candidate_tmdb_ids: list[int] = []
    seen_tmdb_ids: set[int] = set()

    def add_from_response(response: TmdbDiscoverResponse) -> bool:
        for summary in response.results:
            if len(candidate_tmdb_ids) >= TMDB_CANDIDATE_POOL_LIMIT:
                return True
            if summary.id in seen_tmdb_ids or summary.id in signals.interacted_tmdb_ids:
                continue
            if not _is_released(summary.release_date):
                continue
            seen_tmdb_ids.add(summary.id)
            candidate_tmdb_ids.append(summary.id)
        return len(candidate_tmdb_ids) >= TMDB_CANDIDATE_POOL_LIMIT

    try:
        for tmdb_id in signals.seed_movie_tmdb_ids:
            if add_from_response(client.get_movie_recommendations(tmdb_id)):
                break
        if len(candidate_tmdb_ids) < TMDB_CANDIDATE_POOL_LIMIT:
            for tmdb_id in signals.watched_seed_tmdb_ids:
                if add_from_response(client.get_movie_recommendations(tmdb_id)):
                    break
        if len(candidate_tmdb_ids) < TMDB_CANDIDATE_POOL_LIMIT:
            for genre_tmdb_id in signals.discovery_genre_tmdb_ids:
                if add_from_response(
                    client.discover_popular(page=1, with_genres=str(genre_tmdb_id))
                ):
                    break
    except TmdbApiError as exc:
        logger.warning("TMDB recommendation candidate expansion failed: %s", exc)

    movies: list[Movie] = []
    for tmdb_id in candidate_tmdb_ids[:TMDB_CANDIDATE_POOL_LIMIT]:
        try:
            movie = fetch_and_cache_movie(tmdb_id, client=client)
        except TmdbApiError as exc:
            logger.warning(
                "TMDB candidate detail fetch failed for tmdb_id=%s: %s", tmdb_id, exc
            )
            continue
        if movie.id in signals.interacted_movie_ids:
            continue
        if not _is_released(movie.release_date):
            continue
        movies.append(movie)
    return movies


def _score_recommendation_candidate(
    movie: Movie,
    signals: RecommendationSignals,
) -> int:
    genre_ids = {genre.id for genre in movie.genres.all()}
    director_ids: set[int] = set()
    actor_ids: set[int] = set()
    for credit in movie.credits.all():
        if credit.credit_type == MovieCredit.DIRECTOR:
            director_ids.add(credit.person_id)
        elif (
            credit.credit_type == MovieCredit.CAST
            and credit.order < TOP_BILLED_CAST_LIMIT
        ):
            actor_ids.add(credit.person_id)

    positive_score = (
        len(genre_ids & signals.explicit_genre_ids) * WEIGHT_LIKED_GENRE
        + len(genre_ids & signals.watched_genre_ids) * WEIGHT_WATCHED_GENRE
        + len(director_ids & signals.liked_director_ids) * WEIGHT_LIKED_DIRECTOR
        + len(director_ids & signals.watched_director_ids) * WEIGHT_WATCHED_DIRECTOR
        + len(actor_ids & signals.liked_actor_ids) * WEIGHT_LIKED_ACTOR
        + len(actor_ids & signals.watched_actor_ids) * WEIGHT_WATCHED_ACTOR
    )
    negative_score = (
        len(genre_ids & signals.disliked_genre_ids) * WEIGHT_DISLIKED_GENRE
        + len(director_ids & signals.disliked_director_ids) * WEIGHT_DISLIKED_DIRECTOR
        + len(actor_ids & signals.disliked_actor_ids) * WEIGHT_DISLIKED_ACTOR
    )
    return positive_score - negative_score


RECOMMENDATIONS_CACHE_TTL = 30 * 60
RECOMMENDATIONS_CACHE_VERSION = 1


def _recommendations_cache_key(user_id: int) -> str:
    return f"recs:v{RECOMMENDATIONS_CACHE_VERSION}:user:{user_id}"


def bust_recommendations_cache(user: AbstractBaseUser) -> None:
    """Invalidate the cached recommendation IDs for a user.

    Called from the rating/status mutation helpers so a freshly rated or
    watchlisted movie shows up in the next dashboard load instead of waiting
    for the TTL.
    """
    if user is None or not getattr(user, "pk", None):
        return
    cache.delete(_recommendations_cache_key(user.pk))
    bust_personalized_shelves_cache(user)


def _compute_recommendation_movie_ids(user: AbstractBaseUser) -> list[int]:
    signals = _build_recommendation_signals(user)
    if not signals.has_positive_signals():
        return []

    local_candidate_ids = set(
        Movie.objects.filter(_recommendation_match_q(signals))
        .exclude(id__in=signals.interacted_movie_ids)
        .filter(_released_movie_q())
        .values_list("id", flat=True)
    )
    local_candidate_ids.update(
        movie.id for movie in _fetch_tmdb_recommendation_candidates(signals)
    )
    if not local_candidate_ids:
        return []

    candidates = (
        Movie.objects.filter(id__in=local_candidate_ids)
        .exclude(id__in=signals.interacted_movie_ids)
        .filter(_released_movie_q())
        .prefetch_related("genres", "credits")
    )

    scored: list[tuple[Movie, int]] = []
    for movie in candidates:
        score = _score_recommendation_candidate(movie, signals)
        if score <= 0:
            continue
        scored.append((movie, score))

    scored.sort(
        key=lambda item: (
            -item[1],
            -(item[0].popularity or Decimal("0")),
            item[0].title,
        )
    )
    return [movie.id for movie, _score in scored]


def get_recommendations_for_user(
    user: AbstractBaseUser,
    *,
    limit: int = DEFAULT_RECOMMENDATION_LIMIT,
) -> list[Movie]:
    """Return content-based movie recommendations for an authenticated user.

    Three signal types are combined:
      1. Genre overlap — genres from highly-rated movies, favourites, and
         watched-only history.
      2. Director match — directors of highly-rated or watched-only movies.
      3. Actor match — top-billed actors from highly-rated or watched-only
         movies.

    Movies the user has already interacted with (rated, watchlisted, or
    watched) are excluded. Candidates are scored by a weighted sum of the
    three signals, with watched-only signals counting less than explicit
    preferences. Low ratings add negative signals that can suppress or remove
    otherwise plausible matches. Candidate supply is hybrid: local matches are
    augmented by TMDB recommendation/discovery fetches, cached locally, then
    reranked with the same content score.

    Results are memoised in Django's cache for ~30 minutes keyed on user id;
    `bust_recommendations_cache` clears the entry when the user mutates a
    rating or status. Limit only slices the final list, so different limits
    share the same cache entry.

    Returns an empty list when there are no signals or no candidates.
    """
    cache_key = _recommendations_cache_key(user.pk)
    movie_ids = cache.get(cache_key)
    if movie_ids is None:
        movie_ids = _compute_recommendation_movie_ids(user)
        cache.set(cache_key, movie_ids, RECOMMENDATIONS_CACHE_TTL)

    if not movie_ids:
        return []

    sliced_ids = movie_ids[:limit]
    movies_by_id = {m.id: m for m in Movie.objects.filter(id__in=sliced_ids)}
    return [movies_by_id[mid] for mid in sliced_ids if mid in movies_by_id]


def fetch_personal_recommendations_shelf(
    user: AbstractBaseUser, *, limit: int = SHELF_LIMIT
) -> list[MovieListItem]:
    """Shelf-shaped wrapper around `get_recommendations_for_user`.

    Same content-scoring engine, just returned as `MovieListItem`s so it
    can sit alongside the TMDB-driven rails on /movies/. Returns an empty
    list when the user has no signals (which makes the caller drop the
    shelf entirely instead of rendering an empty rail).
    """
    movies = get_recommendations_for_user(user, limit=limit)
    return [MovieListItem.from_local(movie) for movie in movies]
