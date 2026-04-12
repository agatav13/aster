from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from .models import Comment, Genre, MovieCredit, Rating, UserMovieStatus
from .services import (
    MovieListPage,
    browse_local_movies,
    create_comment,
    delete_own_comment,
    discover_tmdb_movies,
    fetch_and_cache_movie,
    remove_movie_status,
    remove_rating,
    search_tmdb_movies,
    set_movie_status,
    upsert_rating,
    visible_comments_for,
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

        The default listing always shows trending / all movies so that the
        catalog feels fresh. Favourite-genre filtering only activates when
        the user explicitly opts in via ``?favorites=1``.
        """
        if not has_favorite_genres:
            return False
        return raw_favorites == "1"

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

    user_status: str | None = None
    user_rating: int | None = None
    if request.user.is_authenticated:
        status_row = UserMovieStatus.objects.filter(
            user=request.user, movie=movie
        ).first()
        user_status = status_row.status if status_row else None
        rating_row = Rating.objects.filter(user=request.user, movie=movie).first()
        user_rating = rating_row.score if rating_row else None

    comments = list(visible_comments_for(movie))

    credits = movie.credits.select_related("person").order_by("credit_type", "order")
    directors = [c for c in credits if c.credit_type == MovieCredit.DIRECTOR]
    cast = [c for c in credits if c.credit_type == MovieCredit.CAST]

    return render(
        request,
        "movies/detail.html",
        {
            "movie": movie,
            "genres": movie.genres.all(),
            "directors": directors,
            "cast": cast,
            "user_status": user_status,
            "user_rating": user_rating,
            "status_watchlist": UserMovieStatus.WATCHLIST,
            "status_watched": UserMovieStatus.WATCHED,
            "comments": comments,
            "comments_count": len(comments),
            "comment_max_length": Comment.MAX_LENGTH,
        },
    )


def _resolve_movie_or_404(tmdb_id: int):
    """Shared helper for write-side views: fetch-and-cache or 404."""
    try:
        return fetch_and_cache_movie(tmdb_id)
    except TmdbConfigError as exc:
        raise Http404(
            "This movie isn't cached locally yet and TMDB is not configured."
        ) from exc
    except TmdbApiError as exc:
        raise Http404("Could not fetch movie from TMDB.") from exc


def _detail_redirect(tmdb_id: int) -> HttpResponse:
    return redirect(reverse("movies:detail", args=[tmdb_id]))


@login_required
@require_POST
def update_movie_status(request: HttpRequest, tmdb_id: int) -> HttpResponse:
    """Toggle/clear a watchlist or watched marker for the current user.

    The form posts an `action` field. Supported values:
      * "watchlist" / "watched" — upsert the corresponding status. If the
        user already has the same status, treat the second click as a
        "remove" toggle so the buttons work as on/off switches.
      * "clear" — unconditionally remove any status row.
    """
    movie = _resolve_movie_or_404(tmdb_id)
    action = request.POST.get("action", "").strip()

    if action == "clear":
        remove_movie_status(user=request.user, movie=movie)
        messages.info(request, f"„{movie.title}” usunięty z Twoich list.")
        return _detail_redirect(tmdb_id)

    if action not in {UserMovieStatus.WATCHLIST, UserMovieStatus.WATCHED}:
        messages.error(request, "Nieprawidłowa akcja.")
        return _detail_redirect(tmdb_id)

    existing = UserMovieStatus.objects.filter(
        user=request.user, movie=movie
    ).first()
    if existing is not None and existing.status == action:
        remove_movie_status(user=request.user, movie=movie)
        messages.info(request, f"„{movie.title}” usunięty z Twoich list.")
        return _detail_redirect(tmdb_id)

    promoted_from_watchlist = (
        existing is not None
        and existing.status == UserMovieStatus.WATCHLIST
        and action == UserMovieStatus.WATCHED
    )
    set_movie_status(user=request.user, movie=movie, status=action)
    if promoted_from_watchlist:
        messages.success(
            request,
            f"„{movie.title}” przeniesiony z „do obejrzenia” do „obejrzane”.",
        )
    else:
        label = (
            "do obejrzenia"
            if action == UserMovieStatus.WATCHLIST
            else "obejrzane"
        )
        messages.success(request, f"„{movie.title}” dodany do listy „{label}”.")
    return _detail_redirect(tmdb_id)


@login_required
@require_POST
def update_movie_rating(request: HttpRequest, tmdb_id: int) -> HttpResponse:
    """Save or delete the current user's rating for a movie."""
    movie = _resolve_movie_or_404(tmdb_id)
    action = request.POST.get("action", "save").strip()

    if action == "delete":
        if remove_rating(user=request.user, movie=movie):
            messages.info(request, f"Twoja ocena filmu „{movie.title}” została usunięta.")
        return _detail_redirect(tmdb_id)

    raw_score = request.POST.get("score", "").strip()
    try:
        score = Decimal(raw_score)
    except (ValueError, InvalidOperation):
        messages.error(request, "Wybierz ocenę od 0.5 do 5 gwiazdek.")
        return _detail_redirect(tmdb_id)

    # Detect "watchlist → watched" promotion before the rating upsert so we
    # can tell the user that their watchlist entry was moved, not just that
    # the rating was saved.
    was_on_watchlist = UserMovieStatus.objects.filter(
        user=request.user, movie=movie, status=UserMovieStatus.WATCHLIST
    ).exists()

    try:
        upsert_rating(user=request.user, movie=movie, score=score)
    except ValueError:
        messages.error(request, "Ocena musi mieścić się w zakresie 0.5–5.")
        return _detail_redirect(tmdb_id)

    display_score = score.normalize()
    messages.success(request, f"Zapisano ocenę {display_score}/5 dla „{movie.title}”.")
    if was_on_watchlist:
        messages.info(
            request,
            f"„{movie.title}” przeniesiony z „do obejrzenia” do „obejrzane”.",
        )
    return _detail_redirect(tmdb_id)


@login_required
@require_POST
def create_movie_comment(request: HttpRequest, tmdb_id: int) -> HttpResponse:
    """Create a new visible comment on the movie.

    Validation is intentionally shallow: the service layer trims/caps
    content and the view just surfaces the two error cases via messages so
    the rendered page can tell the user what went wrong.
    """
    movie = _resolve_movie_or_404(tmdb_id)
    content = request.POST.get("content", "")
    try:
        create_comment(user=request.user, movie=movie, content=content)
    except ValueError:
        if not content.strip():
            messages.error(request, "Komentarz nie może być pusty.")
        else:
            messages.error(
                request,
                f"Komentarz jest zbyt długi (maks. {Comment.MAX_LENGTH} znaków).",
            )
        return _detail_redirect(tmdb_id)

    messages.success(request, "Dodano komentarz.")
    return _detail_redirect(tmdb_id)


@login_required
@require_POST
def delete_movie_comment(
    request: HttpRequest, tmdb_id: int, comment_id: int
) -> HttpResponse:
    """Delete a comment the current user owns; 404 for anything else."""
    comment = get_object_or_404(
        Comment, pk=comment_id, movie__tmdb_id=tmdb_id
    )
    if not delete_own_comment(user=request.user, comment=comment):
        raise Http404("Nie można usunąć tego komentarza.")
    messages.info(request, "Komentarz usunięty.")
    return _detail_redirect(tmdb_id)
