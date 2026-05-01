from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from community.services import build_feed_groups
from movies.models import Movie, UserMovieStatus
from movies.services import fetch_community_top_rated_shelf

WATCHLIST_RAIL_LIMIT = 8
FEED_GROUPS_LIMIT = 24


class HomeView(View):
    """Editorial landing page for signed-in users.

    Anonymous → login. Signed-in visitors see a community-first start page:
    a friends-activity feed up top, the watchlist rail beneath it, and a
    community-top-rated rail as the empty-state filler when the user
    follows nobody (or nobody they follow has logged anything yet). Personal
    recommendations live on /movies/ now — moving them off this page cuts
    a TMDB round-trip from every dashboard load.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        if not request.user.is_authenticated:
            return redirect("accounts:login")

        user = request.user

        feed_groups = build_feed_groups(user, limit=FEED_GROUPS_LIMIT)

        watchlist_rail = list(
            Movie.objects.filter(
                user_statuses__user=user,
                user_statuses__status=UserMovieStatus.WATCHLIST,
            ).order_by("-user_statuses__updated_at")[:WATCHLIST_RAIL_LIMIT]
        )

        # Only build the fallback when we'd otherwise leave the page mostly
        # empty — fetch_community_top_rated_shelf is local + cached, so the
        # cost is trivial, but skipping it keeps the dashboard tight when
        # the friends feed already filled the screen.
        community_shelf = fetch_community_top_rated_shelf() if not feed_groups else []

        return render(
            request,
            "core/dashboard.html",
            {
                "feed_groups": feed_groups,
                "watchlist_rail": watchlist_rail,
                "community_shelf": community_shelf,
            },
        )
