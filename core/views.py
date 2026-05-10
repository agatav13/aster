from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views import View

from community.services import build_feed_groups
from movies.models import Movie, UserMovieStatus
from movies.services import (
    fetch_community_top_rated_shelf,
    fetch_trending_shelf,
)

WATCHLIST_RAIL_LIMIT = 8
FEED_GROUPS_LIMIT = 24


class HomeView(View):
    """Dual-mode entry page.

    Anonymous visitors get a discovery-first landing: a hero with
    login/register CTAs, a search box that submits to /movies/, and the
    community-top-rated and trending rails so they can start browsing
    immediately without manually navigating to /movies/. Signed-in users
    see the dashboard: top-rated rail, their watchlist, and the
    friends-activity feed.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        if not request.user.is_authenticated:
            return render(
                request,
                "core/landing.html",
                {
                    "top_rated": fetch_community_top_rated_shelf(),
                    "trending": fetch_trending_shelf(),
                },
            )

        user = request.user

        feed_groups = build_feed_groups(user, limit=FEED_GROUPS_LIMIT)

        watchlist_rail = list(
            Movie.objects.filter(
                user_statuses__user=user,
                user_statuses__status=UserMovieStatus.WATCHLIST,
            ).order_by("-user_statuses__updated_at")[:WATCHLIST_RAIL_LIMIT]
        )

        community_shelf = fetch_community_top_rated_shelf()

        return render(
            request,
            "core/dashboard.html",
            {
                "feed_groups": feed_groups,
                "watchlist_rail": watchlist_rail,
                "community_shelf": community_shelf,
            },
        )
