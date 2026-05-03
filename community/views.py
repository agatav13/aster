from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Exists, OuterRef
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from movies.models import Movie, Rating, UserMovieStatus

from .models import Follow
from .services import build_feed_groups, handle_for, name_for

User = get_user_model()


class _CommunityBaseView(LoginRequiredMixin, TemplateView):
    active_tab: str = "feed"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["active_tab"] = self.active_tab
        return ctx


class FeedView(_CommunityBaseView):
    template_name = "community/feed.html"
    active_tab = "feed"
    LIMIT = 60

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["feed_groups"] = build_feed_groups(self.request.user, limit=self.LIMIT)
        return ctx


class PeopleView(_CommunityBaseView):
    template_name = "community/people.html"
    active_tab = "people"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        me = self.request.user
        is_following = Follow.objects.filter(follower=me, followee=OuterRef("pk"))
        users = (
            User.objects.exclude(pk=me.pk)
            .filter(is_active=True)
            .annotate(is_following=Exists(is_following))
            .order_by("-is_following", "display_name", "email")
        )

        friends: list[Any] = []
        suggestions: list[Any] = []
        for u in users:
            card = {
                "id": u.pk,
                "name": name_for(u),
                "handle": handle_for(u),
                "is_following": u.is_following,
            }
            (friends if u.is_following else suggestions).append(card)

        ctx["friends"] = friends
        ctx["suggestions"] = suggestions
        return ctx


class UserProfileView(LoginRequiredMixin, TemplateView):
    """Read-only public profile of another user."""

    template_name = "community/profile.html"

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        user_id = kwargs["user_id"]
        if request.user.is_authenticated and request.user.pk == user_id:
            return redirect("accounts:profile")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        target = get_object_or_404(User, pk=kwargs["user_id"], is_active=True)

        watched_rows = (
            UserMovieStatus.objects.filter(user=target, status=UserMovieStatus.WATCHED)
            .select_related("movie")
            .order_by("-updated_at")
        )
        watchlist_rows = (
            UserMovieStatus.objects.filter(
                user=target, status=UserMovieStatus.WATCHLIST
            )
            .select_related("movie")
            .order_by("-updated_at")
        )
        rated_rows = (
            Rating.objects.filter(user=target)
            .select_related("movie")
            .order_by("-updated_at")
        )

        watched_movies = [r.movie for r in watched_rows]
        watchlist_movies = [r.movie for r in watchlist_rows]
        rated_count = rated_rows.count()

        avg_rating: Decimal | None = None
        if rated_count:
            total = sum((r.score for r in rated_rows), Decimal("0"))
            avg_rating = (total / rated_count).quantize(Decimal("0.01"))

        top_genres: list[str] = []
        top_decade: str | None = None
        movie_ids = {m.pk for m in watched_movies} | {r.movie.pk for r in rated_rows}
        if movie_ids:
            movies_qs = Movie.objects.filter(pk__in=movie_ids).prefetch_related(
                "genres"
            )
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

        ratings_by_movie = {
            r.movie.pk: (r.score, r.updated_at.timestamp()) for r in rated_rows
        }
        library_entries = []
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
                    "has_rating": score is not None,
                }
            )
        library_entries.sort(key=lambda e: e["updated_ts"], reverse=True)
        library_count = len(library_entries)
        library_rated_count = sum(1 for e in library_entries if e["has_rating"])
        library_unrated_count = library_count - library_rated_count

        raw_tab = self.request.GET.get("tab")
        active_library_tab = "watchlist" if raw_tab == "watchlist" else "library"

        is_following = Follow.objects.filter(
            follower=self.request.user, followee=target
        ).exists()
        followers_count = Follow.objects.filter(followee=target).count()
        following_count = Follow.objects.filter(follower=target).count()

        ctx.update(
            {
                "target": target,
                "profile_display_name": name_for(target),
                "profile_handle": handle_for(target),
                "profile_joined": target.date_joined,
                "watched_count": len(watched_movies),
                "watchlist_count": len(watchlist_movies),
                "watchlist_movies": watchlist_movies,
                "rated_count": rated_count,
                "avg_rating": avg_rating,
                "top_genres": top_genres,
                "top_decade": top_decade,
                "library_entries": library_entries,
                "library_count": library_count,
                "library_rated_count": library_rated_count,
                "library_unrated_count": library_unrated_count,
                "active_library_tab": active_library_tab,
                "is_following": is_following,
                "followers_count": followers_count,
                "following_count": following_count,
            }
        )
        return ctx


@require_POST
def follow_toggle(request: HttpRequest, user_id: int) -> HttpResponse:
    if not request.user.is_authenticated:
        return redirect("accounts:login")
    if request.user.pk == user_id:
        return HttpResponseBadRequest("Nie można obserwować samego siebie.")

    target = get_object_or_404(User, pk=user_id, is_active=True)
    qs = Follow.objects.filter(follower=request.user, followee=target)
    if qs.exists():
        qs.delete()
    else:
        Follow.objects.create(follower=request.user, followee=target)

    next_url = request.POST.get("next") or "community:people"
    if next_url.startswith("/"):
        return redirect(next_url)
    return redirect(next_url)
