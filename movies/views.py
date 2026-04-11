from __future__ import annotations

import logging
from typing import Any

from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.generic import TemplateView

from .models import Genre
from .services import (
    MovieListPage,
    browse_local_movies,
    discover_tmdb_movies,
    fetch_and_cache_movie,
    search_tmdb_movies,
)
from .tmdb import TmdbApiError, TmdbConfigError

logger = logging.getLogger(__name__)


class MovieListView(TemplateView):
    template_name = "movies/list.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        request = self.request

        query = request.GET.get("q", "").strip()
        genre_id_raw = request.GET.get("genre", "").strip()
        has_favorite_genres = (
            request.user.is_authenticated
            and request.user.favorite_genres.exists()
        )
        favorites_active = self._resolve_favorites_active(
            request.GET.get("favorites"), has_favorite_genres
        )
        page = self._parse_page(request.GET.get("page"))

        page_obj, source, search_error = self._build_listing(
            query=query,
            genre_id_raw=genre_id_raw,
            favorites_active=favorites_active,
            page=page,
        )

        context.update(
            {
                "movies": page_obj.object_list,
                "page_obj": page_obj,
                "is_paginated": page_obj.num_pages > 1,
                "query": query,
                "selected_genre": genre_id_raw,
                "favorites_active": favorites_active,
                "genres": Genre.objects.order_by("name"),
                "search_mode": bool(query),
                "search_source": source,
                "search_error": search_error,
            }
        )
        return context

    @staticmethod
    def _resolve_favorites_active(
        raw_favorites: str | None, has_favorite_genres: bool
    ) -> bool:
        """Decide whether the favorites filter should be on for this request.

        Behaviour matrix:
          * No `favorites` param + user has favorites → on (auto-personalize
            so the catalog defaults to the user's preferred genres).
          * `favorites=0` → explicitly off, even if the user has favorites.
            This is the escape hatch the "Pokaż wszystkie" state uses.
          * `favorites=1` → on, if the user actually has favorites to filter by.
          * User has no favorite genres (or is anonymous) → always off; the
            filter would be a no-op anyway.
        """
        if not has_favorite_genres:
            return False
        if raw_favorites == "0":
            return False
        if raw_favorites == "1":
            return True
        return raw_favorites is None

    @staticmethod
    def _parse_page(raw: str | None) -> int:
        try:
            value = int(raw) if raw else 1
        except ValueError:
            return 1
        return max(1, value)

    def _build_listing(
        self,
        *,
        query: str,
        genre_id_raw: str,
        favorites_active: bool,
        page: int,
    ) -> tuple[MovieListPage, str, str | None]:
        """Pick the right data source for the current request.

        Both modes (free-text search via /search/movie, default browse via
        /discover/movie) hit TMDB live and fall back to the local DB on
        config or transport errors.

        Returns (page, source, error_message) where:
          - source is "tmdb" when the rows came from TMDB, "local" otherwise.
          - error_message is set when TMDB was tried but failed and we fell
            back to the local DB; the template renders it as a banner.
        """
        fallback_kwargs: dict[str, Any] = {
            "query": query,
            "genre_id_raw": genre_id_raw,
            "favorites_active": favorites_active,
            "user": self.request.user,
            "page": page,
        }

        if query:
            tmdb_call = lambda: search_tmdb_movies(  # noqa: E731
                query=query, genre_id_raw=genre_id_raw, page=page
            )
            log_label = f"search q={query!r}"
        else:
            tmdb_call = lambda: discover_tmdb_movies(  # noqa: E731
                genre_id_raw=genre_id_raw,
                favorites_active=favorites_active,
                user=self.request.user,
                page=page,
            )
            log_label = "browse"

        try:
            return tmdb_call(), "tmdb", None
        except TmdbConfigError:
            logger.info(
                "TMDB %s requested but TMDB_API_KEY is not configured; "
                "falling back to local",
                log_label,
            )
            return browse_local_movies(**fallback_kwargs), "local", None
        except TmdbApiError as exc:
            logger.warning("TMDB %s failed: %s", log_label, exc)
            return (
                browse_local_movies(**fallback_kwargs),
                "local",
                "Wyszukiwarka TMDB jest chwilowo niedostępna. "
                "Pokazujemy pasujące tytuły z lokalnej bazy.",
            )


def movie_detail(request: HttpRequest, tmdb_id: int) -> HttpResponse:
    """Lazy-cache pattern: serve from DB, fall back to TMDB on first hit."""
    try:
        movie = fetch_and_cache_movie(tmdb_id)
    except TmdbConfigError as exc:
        logger.warning(
            "Movie tmdb_id=%s not cached and TMDB_API_KEY is not configured", tmdb_id
        )
        raise Http404(
            "This movie isn't cached locally yet and TMDB is not configured."
        ) from exc
    except TmdbApiError as exc:
        logger.warning("TMDB fetch failed for tmdb_id=%s: %s", tmdb_id, exc)
        raise Http404("Could not fetch movie from TMDB.") from exc

    return render(
        request,
        "movies/detail.html",
        {"movie": movie, "genres": movie.genres.all()},
    )
