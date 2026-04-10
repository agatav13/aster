"""Glue between the TMDB API client and Django ORM models."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import Genre, Movie
from .tmdb import TmdbClient, TmdbMovieDetail, TmdbMovieSummary


# Canonical Polish names for the standard TMDB movie genres, keyed by their
# stable TMDB id. Used as a safety net so a polluted DB (e.g. one that was
# synced when language was still en-US) can be normalized to Polish without
# trusting whatever TMDB returns at sync time.
TMDB_GENRE_PL_NAMES: dict[int, str] = {
    28: "Akcja",            # Action
    12: "Przygodowy",       # Adventure
    16: "Animacja",         # Animation
    35: "Komedia",          # Comedy
    80: "Kryminał",         # Crime
    99: "Dokumentalny",     # Documentary
    18: "Dramat",           # Drama
    10751: "Familijny",     # Family
    14: "Fantasy",          # Fantasy
    36: "Historyczny",      # History
    27: "Horror",           # Horror
    10402: "Muzyka",        # Music
    9648: "Tajemnica",      # Mystery
    10749: "Romans",        # Romance
    878: "Science Fiction", # Science Fiction
    10770: "Film telewizyjny",  # TV Movie
    53: "Thriller",         # Thriller
    10752: "Wojenny",       # War
    37: "Western",          # Western
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


def _merge_genre(source: Genre, target: Genre) -> None:
    """Move every reference from `source` to `target`, then delete `source`."""
    for user in source.users.all():
        user.favorite_genres.add(target)
        user.favorite_genres.remove(source)
    for movie in source.movies.all():
        movie.genres.add(target)
        movie.genres.remove(source)
    source.delete()


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
        collision = (
            Genre.objects.filter(name__iexact=name).exclude(pk=by_id.pk).first()
        )
        if collision is None:
            by_id.name = name
            by_id.save(update_fields=["name"])
            return by_id
        # Two rows describe the same genre — fold by_id into collision and
        # promote collision as the canonical row for this tmdb_id.
        _merge_genre(source=by_id, target=collision)
        collision.tmdb_id = tmdb_id
        collision.name = name
        collision.save(update_fields=["tmdb_id", "name"])
        return collision

    by_name = Genre.objects.filter(name__iexact=name, tmdb_id__isnull=True).first()
    if by_name is not None:
        by_name.tmdb_id = tmdb_id
        by_name.name = name  # normalize case to TMDB's
        by_name.save(update_fields=["tmdb_id", "name"])
        return by_name

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
            Genre.objects.filter(name__iexact=polish_name)
            .exclude(pk=orphan.pk)
            .first()
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
) -> dict[str, object]:
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
        genres = list(
            Genre.objects.filter(tmdb_id__in=[g.id for g in payload.genres])
        )
        movie.genres.set(genres)
    return movie


def fetch_and_cache_movie(tmdb_id: int, client: TmdbClient | None = None) -> Movie:
    """Look up a movie locally; if missing, fetch from TMDB and persist."""
    existing = Movie.objects.filter(tmdb_id=tmdb_id).first()
    if existing is not None:
        return existing
    client = client or TmdbClient()
    detail = client.get_movie(tmdb_id)
    return upsert_movie_detail(detail, client)
