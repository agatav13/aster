from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from movies.models import Movie, UserMovieStatus
from movies.services import get_recommendations_for_user

WATCHLIST_RAIL_LIMIT = 8
RECOMMENDATION_GRID_LIMIT = 24


class HomeView(View):
    """Editorial landing page for signed-in users.

    Anonymous → login. Signed-in visitors see a discovery-oriented start
    page: personal recommendations and their watchlist rail. The personal
    activity tabs (watched / rated / watchlist) live on the profile page
    so Start doesn't duplicate them.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        if not request.user.is_authenticated:
            return redirect("accounts:login")

        user = request.user

        watchlist_rail = list(
            Movie.objects.filter(
                user_statuses__user=user,
                user_statuses__status=UserMovieStatus.WATCHLIST,
            ).order_by("-user_statuses__updated_at")[:WATCHLIST_RAIL_LIMIT]
        )

        recommendations = get_recommendations_for_user(
            user, limit=RECOMMENDATION_GRID_LIMIT
        )

        return render(
            request,
            "core/dashboard.html",
            {
                "watchlist_rail": watchlist_rail,
                "recommendations": recommendations,
            },
        )
