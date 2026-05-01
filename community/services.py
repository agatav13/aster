"""Reusable helpers for community-driven feeds.

Both `community.FeedView` and `core.HomeView` render an activity stream of
people the current user follows. The query/merge/group logic lives here so
the home page can swap its TMDB recommendations rail for friends activity
without duplicating code.
"""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser
from django.utils import timezone

from movies.models import Rating, UserMovieStatus

from .mock import FeedGroup, FeedItem
from .models import Follow


def name_for(user) -> str:
    return user.display_name or user.email.split("@")[0]


def handle_for(user) -> str:
    return f"@{user.email.split('@')[0]}"


def relative_when(dt) -> str:
    minutes = max(0, int((timezone.now() - dt).total_seconds() // 60))
    if minutes < 60:
        return f"{minutes} min temu"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} godz. temu"
    days = hours // 24
    if days == 1:
        return "wczoraj"
    if days < 7:
        return f"{days} dni temu"
    return f"{days // 7} tyg. temu"


def date_bucket(dt) -> str:
    today = timezone.localdate()
    d = timezone.localtime(dt).date()
    delta = (today - d).days
    if delta <= 0:
        return "Dzisiaj"
    if delta == 1:
        return "Wczoraj"
    if delta < 7:
        return f"{delta} dni temu"
    weeks = delta // 7
    return "Tydzień temu" if weeks == 1 else f"{weeks} tyg. temu"


def followee_ids_for(user: AbstractBaseUser) -> list[int]:
    return list(
        Follow.objects.filter(follower=user).values_list("followee_id", flat=True)
    )


def build_feed_groups(user: AbstractBaseUser, *, limit: int = 60) -> list[FeedGroup]:
    """Recent friends-activity grouped by relative date bucket.

    Pulls each followee's recent ratings and watched-marks, dedupes by
    (user, movie) so the same row isn't shown twice when someone rated and
    marked watched in one go, then sorts newest-first and groups under
    "Dzisiaj" / "Wczoraj" / "3 dni temu" headings.

    Returns an empty list when the user follows nobody. Hits the supporting
    indexes added in movies migration 0009 — without them the order_by
    falls back to a sort over all rows for the followee set.
    """
    followee_ids = followee_ids_for(user)
    if not followee_ids:
        return []

    fetch = limit * 2

    ratings = (
        Rating.objects.filter(user_id__in=followee_ids)
        .select_related("user", "movie")
        .order_by("-created_at")[:fetch]
    )
    watches = (
        UserMovieStatus.objects.filter(
            user_id__in=followee_ids, status=UserMovieStatus.WATCHED
        )
        .select_related("user", "movie")
        .order_by("-updated_at")[:fetch]
    )

    merged: dict[tuple[int, int], FeedItem] = {}

    def upsert(user_obj, movie, ts, *, score=None, watched=False) -> None:
        key = (user_obj.pk, movie.pk)
        existing = merged.get(key)
        if existing is None:
            merged[key] = FeedItem(
                user_id=user_obj.pk,
                user_name=name_for(user_obj),
                movie=movie,
                score=score,
                watched=watched,
                when_label=relative_when(ts),
                timestamp=ts,
            )
            return
        if score is not None:
            existing.score = score
        if watched:
            existing.watched = True
        if ts > existing.timestamp:
            existing.timestamp = ts
            existing.when_label = relative_when(ts)

    for r in ratings:
        upsert(r.user, r.movie, r.created_at, score=r.score)
    for w in watches:
        upsert(w.user, w.movie, w.updated_at, watched=True)

    items = sorted(merged.values(), key=lambda i: i.timestamp, reverse=True)[:limit]

    groups: dict[str, list[FeedItem]] = {}
    for item in items:
        label = date_bucket(item.timestamp)
        groups.setdefault(label, []).append(item)

    return [FeedGroup(label=lbl, items=its) for lbl, its in groups.items()]
