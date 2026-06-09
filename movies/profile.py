"""Shared per-user library statistics for the profile pages.

Both `accounts.ProfileView` (own profile) and `community.UserProfileView`
(read-only public profile) render the same hero ledger, taste stats and
library grid. The query/merge/aggregate logic lives here so the two views
only keep their page-specific context (tabs, initials, follow state).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.contrib.auth.models import AbstractBaseUser
from django.db.models import Avg

from .models import Movie, Rating, UserMovieStatus


@dataclass
class ProfileStats:
    watched_movies: list[Movie]
    watchlist_movies: list[Movie]
    rated_movies: list[dict[str, Any]]
    library_entries: list[dict[str, Any]]
    library_count: int
    library_rated_count: int
    library_unrated_count: int
    avg_rating: Decimal | None
    top_genres: list[str]
    top_decade: str | None
    watched_count: int
    watchlist_count: int
    rated_count: int


def build_profile_stats(user: AbstractBaseUser) -> ProfileStats:
    watched_rows = list(
        UserMovieStatus.objects.filter(user=user, status=UserMovieStatus.WATCHED)
        .select_related("movie")
        .order_by("-updated_at")
    )
    watchlist_rows = (
        UserMovieStatus.objects.filter(user=user, status=UserMovieStatus.WATCHLIST)
        .select_related("movie")
        .order_by("-updated_at")
    )
    rated_qs = (
        Rating.objects.filter(user=user).select_related("movie").order_by("-updated_at")
    )
    rated_rows = list(rated_qs)

    watched_movies = [row.movie for row in watched_rows]
    watchlist_movies = [row.movie for row in watchlist_rows]
    rated_movies = [{"movie": row.movie, "score": row.score} for row in rated_rows]

    # "Library" = strictly watched movies, with the user's rating attached
    # when one exists. A rating without an explicit watched mark stays out
    # of this list (the watchlist tab covers planned-to-watch separately).
    # updated_ts uses the latest of (watched, rated) so the grid still
    # surfaces recent activity even when the rating arrived after the
    # watched mark.
    ratings_by_movie: dict[int, tuple[Decimal, float]] = {
        row.movie.pk: (row.score, row.updated_at.timestamp()) for row in rated_rows
    }
    library_entries: list[dict[str, Any]] = []
    for row in watched_rows:
        score_ts = ratings_by_movie.get(row.movie.pk)
        score = score_ts[0] if score_ts else None
        updated_ts = row.updated_at.timestamp()
        if score_ts:
            updated_ts = max(updated_ts, score_ts[1])
        library_entries.append(
            {
                "movie": row.movie,
                "score": score,
                "updated_ts": updated_ts,
                "score_int": int(score) if score is not None else 0,
                "has_rating": score is not None,
            }
        )
    library_entries.sort(key=lambda e: e["updated_ts"], reverse=True)
    library_count = len(library_entries)
    library_rated_count = sum(1 for e in library_entries if e["has_rating"])

    avg_rating: Decimal | None = None
    if rated_rows:
        avg = rated_qs.aggregate(avg=Avg("score"))["avg"]
        if avg is not None:
            avg_rating = Decimal(str(avg)).quantize(Decimal("0.01"))

    top_genres: list[str] = []
    top_decade: str | None = None
    movie_ids = {m.pk for m in watched_movies} | {row.movie.pk for row in rated_rows}
    if movie_ids:
        movies_qs = Movie.objects.filter(pk__in=movie_ids).prefetch_related("genres")
        genre_counter: Counter[str] = Counter()
        decade_counter: Counter[str] = Counter()
        for m in movies_qs:
            for g in m.genres.all():
                genre_counter[g.name] += 1
            if m.release_date is not None:
                decade = (m.release_date.year // 10) * 10
                decade_counter[f"{decade}s"] += 1
        top_genres = [name for name, _ in genre_counter.most_common(3)]
        if decade_counter:
            top_decade = decade_counter.most_common(1)[0][0]

    return ProfileStats(
        watched_movies=watched_movies,
        watchlist_movies=watchlist_movies,
        rated_movies=rated_movies,
        library_entries=library_entries,
        library_count=library_count,
        library_rated_count=library_rated_count,
        library_unrated_count=library_count - library_rated_count,
        avg_rating=avg_rating,
        top_genres=top_genres,
        top_decade=top_decade,
        watched_count=len(watched_movies),
        watchlist_count=len(watchlist_movies),
        rated_count=len(rated_rows),
    )
