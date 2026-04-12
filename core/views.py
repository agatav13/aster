from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from movies.models import Rating, UserMovieStatus
from movies.services import get_recommendations_for_user


class HomeView(View):
    """Single index route.

    Anonymous visitors are redirected to the login screen. Authenticated
    users get the dashboard rendered in place at `/` — there is no separate
    `/dashboard/` URL anymore, so `/` is the canonical entry point for
    logged-in users.
    """

    def get(self, request: HttpRequest) -> HttpResponse:
        if not request.user.is_authenticated:
            return redirect("accounts:login")

        user = request.user

        # Each tab is sourced differently per docs/database-design.md §Panel
        # użytkownika: "obejrzane" / "do obejrzenia" come from
        # user_movie_statuses filtered by status, while "ocenione" is derived
        # from ratings (no extra table needed).
        watched_rows = (
            UserMovieStatus.objects
            .filter(user=user, status=UserMovieStatus.WATCHED)
            .select_related("movie")
            .order_by("-updated_at")
        )
        watchlist_rows = (
            UserMovieStatus.objects
            .filter(user=user, status=UserMovieStatus.WATCHLIST)
            .select_related("movie")
            .order_by("-updated_at")
        )
        rated_rows = (
            Rating.objects
            .filter(user=user)
            .select_related("movie")
            .order_by("-updated_at")
        )

        watched_movies = [row.movie for row in watched_rows]
        watchlist_movies = [row.movie for row in watchlist_rows]
        # Templates need the score alongside the movie, so we annotate a
        # lightweight list of tuples; the template unpacks as {movie, score}.
        rated_movies = [
            {"movie": row.movie, "score": row.score} for row in rated_rows
        ]

        recommendations = get_recommendations_for_user(user)

        return render(
            request,
            "core/dashboard.html",
            {
                "watched_movies": watched_movies,
                "watchlist_movies": watchlist_movies,
                "rated_movies": rated_movies,
                "watched_count": len(watched_movies),
                "watchlist_count": len(watchlist_movies),
                "rated_count": len(rated_movies),
                "recommendations": recommendations,
            },
        )
