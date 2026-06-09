from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Exists, OuterRef
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from movies.profile import build_profile_stats

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
            .order_by("-is_following", "display_name", "pk")
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
        # LoginRequiredMixin guarantees an authenticated user here.
        if request.user.pk == kwargs["user_id"]:
            return redirect("accounts:profile")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        target = get_object_or_404(User, pk=kwargs["user_id"], is_active=True)
        stats = build_profile_stats(target)

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
                "watched_count": stats.watched_count,
                "watchlist_count": stats.watchlist_count,
                "watchlist_movies": stats.watchlist_movies,
                "rated_count": stats.rated_count,
                "avg_rating": stats.avg_rating,
                "top_genres": stats.top_genres,
                "top_decade": stats.top_decade,
                "library_entries": stats.library_entries,
                "library_count": stats.library_count,
                "library_rated_count": stats.library_rated_count,
                "library_unrated_count": stats.library_unrated_count,
                "active_library_tab": active_library_tab,
                "is_following": is_following,
                "followers_count": followers_count,
                "following_count": following_count,
            }
        )
        return ctx


@login_required
@require_POST
def follow_toggle(request: HttpRequest, user_id: int) -> HttpResponse:
    if request.user.pk == user_id:
        return HttpResponseBadRequest("Nie można obserwować samego siebie.")

    target = get_object_or_404(User, pk=user_id, is_active=True)
    # get_or_create instead of exists()+create(): two concurrent POSTs
    # (double-click) would otherwise both create and the loser would 500 on
    # the uq_follow_pair constraint.
    _, created = Follow.objects.get_or_create(follower=request.user, followee=target)
    if not created:
        Follow.objects.filter(follower=request.user, followee=target).delete()

    next_url = request.POST.get("next") or ""
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect("community:people")
