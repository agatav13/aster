from __future__ import annotations

from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from .mock import build_feed, build_lists, build_people


class _CommunityBaseView(LoginRequiredMixin, TemplateView):
    """Shared context: active sub-tab key used by the tab bar."""

    active_tab: str = "feed"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["active_tab"] = self.active_tab
        return ctx


class FeedView(_CommunityBaseView):
    template_name = "community/feed.html"
    active_tab = "feed"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["feed_items"] = build_feed(user_id=self.request.user.pk)
        return ctx


class PeopleView(_CommunityBaseView):
    template_name = "community/people.html"
    active_tab = "people"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        groups = build_people(user_id=self.request.user.pk)
        ctx["friends"] = groups["friends"]
        ctx["suggestions"] = groups["suggestions"]
        return ctx


class ListsView(_CommunityBaseView):
    template_name = "community/lists.html"
    active_tab = "lists"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        ctx = super().get_context_data(**kwargs)
        ctx["curated_lists"] = build_lists(user_id=self.request.user.pk)
        return ctx
