from __future__ import annotations

from django.core.paginator import Paginator
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.generic import DetailView, ListView

from .models import Genre, Movie
from .services import fetch_and_cache_movie
from .tmdb import TmdbApiError, TmdbConfigError


MOVIES_PER_PAGE = 12


class MovieListView(ListView):
    model = Movie
    template_name = "movies/list.html"
    context_object_name = "movies"
    paginate_by = MOVIES_PER_PAGE

    def _favorites_active(self) -> bool:
        return (
            self.request.GET.get("favorites") == "1"
            and self.request.user.is_authenticated
        )

    def get_queryset(self):
        queryset = Movie.objects.all().prefetch_related("genres")

        query = self.request.GET.get("q", "").strip()
        if query:
            queryset = queryset.filter(title__icontains=query)

        genre_id = self.request.GET.get("genre")
        if genre_id:
            queryset = queryset.filter(genres__id=genre_id)

        if self._favorites_active():
            favorite_ids = list(
                self.request.user.favorite_genres.values_list("id", flat=True)
            )
            if favorite_ids:
                queryset = queryset.filter(genres__id__in=favorite_ids)

        return queryset.distinct()

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["query"] = self.request.GET.get("q", "")
        context["selected_genre"] = self.request.GET.get("genre", "")
        context["favorites_active"] = self._favorites_active()
        context["genres"] = Genre.objects.order_by("name")
        if self.request.user.is_authenticated:
            context["has_favorite_genres"] = (
                self.request.user.favorite_genres.exists()
            )
        else:
            context["has_favorite_genres"] = False
        return context


def movie_detail(request: HttpRequest, tmdb_id: int) -> HttpResponse:
    """Lazy-cache pattern: serve from DB, fall back to TMDB on first hit."""
    try:
        movie = fetch_and_cache_movie(tmdb_id)
    except TmdbConfigError as exc:
        # No API key configured AND movie isn't in the local cache → 404 with hint.
        raise Http404(
            "This movie isn't cached locally yet and TMDB is not configured."
        ) from exc
    except TmdbApiError as exc:
        raise Http404(f"Could not fetch movie from TMDB: {exc}") from exc

    return render(
        request,
        "movies/detail.html",
        {"movie": movie, "genres": movie.genres.all()},
    )
