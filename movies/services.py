"""Glue between the TMDB API client and Django ORM models."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Iterator

from django.contrib.auth.models import AbstractBaseUser
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
    TmdbMovieDetail,
    TmdbMovieSummary,
)

logger = logging.getLogger(__name__)

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


def sync_movie_credits(movie: Movie, credits: TmdbCredits, client: TmdbClient) -> None:
    """Persist directors and top-billed cast from a TMDB credits payload."""
    directors = [c for c in credits.crew if c.job == "Director"]
    cast = sorted(credits.cast, key=lambda c: c.order)[:MAX_CAST_PER_MOVIE]

    bulk: list[MovieCredit] = []
    for member in directors:
        person, _ = Person.objects.update_or_create(
            tmdb_id=member.id,
            defaults={
                "name": member.name,
                "profile_url": client.image_url(member.profile_path),
            },
        )
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
    MovieCredit.objects.bulk_create(bulk)


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
# movies the user rated highly plus their explicit favorite genres:
#   1. Genre overlap  (weight 1 per matching genre)
#   2. Director match (weight 3 — strong auteur signal)
#   3. Actor match    (weight 2 — familiar cast)
# The weighted sum is the primary sort key, with TMDB popularity as tiebreaker.

# Minimum rating score for a movie to count as "liked" and contribute its
# genres / credits to the recommendation pool.
LIKED_RATING_THRESHOLD = 4
# Default cap on how many recommendations to return.
DEFAULT_RECOMMENDATION_LIMIT = 12

# Scoring weights for each signal type.
WEIGHT_GENRE = 1
WEIGHT_DIRECTOR = 3
WEIGHT_ACTOR = 2


def get_recommendations_for_user(
    user: AbstractBaseUser,
    *,
    limit: int = DEFAULT_RECOMMENDATION_LIMIT,
) -> list[Movie]:
    """Return content-based movie recommendations for an authenticated user.

    Three signal types are combined:
      1. Genre overlap — genres from highly-rated movies + user's favourites.
      2. Director match — directors of highly-rated movies.
      3. Actor match — top-billed actors from highly-rated movies.

    Movies the user has already interacted with (rated, watchlisted, or
    watched) are excluded. Candidates are scored by a weighted sum of the
    three signals, then sorted by score descending and popularity as
    tiebreaker.

    Returns an empty list when there are no signals or no candidates.
    """
    liked_ratings = Rating.objects.filter(user=user, score__gte=LIKED_RATING_THRESHOLD)
    liked_movie_ids: set[int] = set(liked_ratings.values_list("movie_id", flat=True))

    # ── Genre signals ──────────────────────────────────────────────────
    liked_genre_ids: set[int] = set(
        Genre.objects.filter(movies__id__in=liked_movie_ids).values_list(
            "id", flat=True
        )
    )
    favorite_genre_ids: set[int] = set(
        user.favorite_genres.values_list("id", flat=True)
    )
    target_genre_ids = liked_genre_ids | favorite_genre_ids

    # ── Credit signals ─────────────────────────────────────────────────
    target_director_ids: set[int] = set(
        MovieCredit.objects.filter(
            movie_id__in=liked_movie_ids, credit_type=MovieCredit.DIRECTOR
        ).values_list("person_id", flat=True)
    )
    target_actor_ids: set[int] = set(
        MovieCredit.objects.filter(
            movie_id__in=liked_movie_ids, credit_type=MovieCredit.CAST
        ).values_list("person_id", flat=True)
    )

    has_signals = target_genre_ids or target_director_ids or target_actor_ids
    if not has_signals:
        return []

    # ── Exclude already-interacted movies ──────────────────────────────
    interacted_movie_ids: set[int] = set()
    interacted_movie_ids.update(
        Rating.objects.filter(user=user).values_list("movie_id", flat=True)
    )
    interacted_movie_ids.update(
        UserMovieStatus.objects.filter(user=user).values_list("movie_id", flat=True)
    )

    # ── Build candidate queryset with weighted scoring ─────────────────
    # Start with movies that match at least one signal.
    genre_q = Q(genres__id__in=target_genre_ids) if target_genre_ids else Q()
    director_q = (
        Q(
            credits__person_id__in=target_director_ids,
            credits__credit_type=MovieCredit.DIRECTOR,
        )
        if target_director_ids
        else Q()
    )
    actor_q = (
        Q(
            credits__person_id__in=target_actor_ids,
            credits__credit_type=MovieCredit.CAST,
        )
        if target_actor_ids
        else Q()
    )
    match_q = genre_q | director_q | actor_q

    genre_score = (
        Count("genres", filter=Q(genres__id__in=target_genre_ids), distinct=True)
        * WEIGHT_GENRE
        if target_genre_ids
        else 0
    )
    director_score = (
        Count(
            "credits",
            filter=Q(
                credits__person_id__in=target_director_ids,
                credits__credit_type=MovieCredit.DIRECTOR,
            ),
            distinct=True,
        )
        * WEIGHT_DIRECTOR
        if target_director_ids
        else 0
    )
    actor_score = (
        Count(
            "credits",
            filter=Q(
                credits__person_id__in=target_actor_ids,
                credits__credit_type=MovieCredit.CAST,
            ),
            distinct=True,
        )
        * WEIGHT_ACTOR
        if target_actor_ids
        else 0
    )

    candidates = (
        Movie.objects.filter(match_q)
        .exclude(id__in=interacted_movie_ids)
        .annotate(rec_score=genre_score + director_score + actor_score)
        .order_by("-rec_score", "-popularity")
        .distinct()[:limit]
    )

    return list(candidates)
