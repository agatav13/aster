from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
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
    exclude_watched,
    fetch_and_cache_movie,
    fetch_community_top_rated_shelf,
    fetch_continue_exploring_shelf,
    fetch_genre_shelf,
    fetch_recently_watched_recommendations_shelf,
    fetch_seeded_recommendations_shelf,
    fetch_trending_shelf,
    remove_movie_status,
    remove_rating,
    search_tmdb_movies,
    set_movie_status,
    upsert_rating,
    visible_comments_for,
    watched_tmdb_ids,
)
from .tmdb import TmdbApiError, TmdbConfigError

logger = logging.getLogger(__name__)


class MovieListView(TemplateView):
    template_name = "movies/list.html"

    # Personal genre shelves are limited to this many so the page doesn't
    # become an infinite scroll of per-genre rails when the user has many
    # favourites.
    PERSONAL_GENRE_SHELVES = 2

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        request = self.request

        query = request.GET.get("q", "").strip()
        genre_id_raw = request.GET.get("genre", "").strip()
        page = self._parse_page(request.GET.get("page"))

        shelves_mode = not query and not genre_id_raw
        context["query"] = query
        context["selected_genre"] = genre_id_raw
        context["genres"] = Genre.objects.order_by("name")

        # Hide titles the user has already marked as watched. Computed once
        # per request and applied to both the grid and the shelves below.
        watched_ids = watched_tmdb_ids(request.user)

        if shelves_mode:
            shelves = self._build_shelves(request, watched_ids=watched_ids)
            if shelves:
                context["shelves_mode"] = True
                context["shelves"] = shelves
                # Grid defaults so the template doesn't need to branch for
                # these when shelves are showing.
                context["movies"] = []
                context["page_obj"] = None
                context["is_paginated"] = False
                context["search_mode"] = False
                context["search_source"] = None
                context["search_error"] = None
                return context
            # No shelves available (TMDB unavailable, key missing, etc.).
            # Fall through to the standard listing build so we still serve
            # a useful grid of whatever is in the local cache.

        context["shelves_mode"] = False
        context["shelves"] = []

        page_obj, source, search_error = self._build_listing(
            query=query,
            genre_id_raw=genre_id_raw,
            page=page,
        )

        page_obj.object_list = exclude_watched(page_obj.object_list, watched_ids)

        context.update(
            {
                "movies": page_obj.object_list,
                "page_obj": page_obj,
                "is_paginated": page_obj.num_pages > 1,
                "search_mode": bool(query),
                "search_source": source,
                "search_error": search_error,
            }
        )
        return context

    def _build_shelves(
        self, request: HttpRequest, *, watched_ids: set[int]
    ) -> list[dict[str, Any]]:
        """Build the shelves shown in default browse mode.

        Each shelf is a dict: {eyebrow, title, icon, items, filter_genre_id}.
        `filter_genre_id` is set for genre shelves so the "Zobacz wszystkie"
        link can deep-link into grid mode with the matching filter applied.

        Ordering is intentional: the trending rail anchors the page, then
        personal signals (seeded recommendations, continue exploring,
        favourite genres) take over so an authenticated user sees themselves
        in the feed before the generic editorial and TMDB rails.

        Each shelf's items are filtered against `watched_ids` so titles the
        user has already seen never appear in the rails. Empty shelves drop
        out at the bottom of this method.
        """
        shelves: list[dict[str, Any]] = [
            {
                "eyebrow": "W tym tygodniu",
                "title": "Popularne",
                "icon": "bi-fire",
                "items": fetch_trending_shelf(),
                "filter_genre_id": None,
            },
        ]

        user = request.user
        if user.is_authenticated:
            seed_movie, seeded_items = fetch_seeded_recommendations_shelf(user)
            if seeded_items:
                shelves.append(
                    {
                        "eyebrow": "Bo oceniłeś wysoko",
                        "title": f"Podobne do „{seed_movie.title}”",
                        "icon": "bi-stars",
                        "items": seeded_items,
                        "filter_genre_id": None,
                    }
                )

            # Skip the rated-shelf seed so the watched rail picks a
            # different title (avoids two near-identical "Podobne do X"
            # rails when the user rated their most recent watch).
            rated_seed_ids = {seed_movie.id} if seed_movie is not None else set()
            watched_seed, watched_items = fetch_recently_watched_recommendations_shelf(
                user, exclude_seed_movie_ids=rated_seed_ids
            )
            if watched_items:
                shelves.append(
                    {
                        "eyebrow": "Bo obejrzałeś",
                        "title": f"Podobne do „{watched_seed.title}”",
                        "icon": "bi-eye",
                        "items": watched_items,
                        "filter_genre_id": None,
                    }
                )

            explore_person, explore_items = fetch_continue_exploring_shelf(user)
            if explore_items:
                shelves.append(
                    {
                        "eyebrow": "Kontynuuj odkrywanie",
                        "title": explore_person.name,
                        "icon": "bi-person-video",
                        "items": explore_items,
                        "filter_genre_id": None,
                    }
                )

        shelves.append(
            {
                "eyebrow": "Głosami widzów Aster",
                "title": "Najwyżej oceniane w Aster",
                "icon": "bi-heart",
                "items": fetch_community_top_rated_shelf(),
                "filter_genre_id": None,
            }
        )

        if user.is_authenticated:
            favs = list(user.favorite_genres.all()[: self.PERSONAL_GENRE_SHELVES])
            for genre in favs:
                if genre.tmdb_id is None:
                    continue
                shelves.append(
                    {
                        "eyebrow": "W Twoim guście",
                        "title": genre.name,
                        "icon": "bi-collection",
                        "items": fetch_genre_shelf(tmdb_genre_id=genre.tmdb_id),
                        "filter_genre_id": genre.pk,
                    }
                )

        for shelf in shelves:
            shelf["items"] = exclude_watched(shelf["items"], watched_ids)

        # Drop shelves that came back empty — either because TMDB was
        # unavailable or because every item got filtered out as watched.
        return [s for s in shelves if s["items"]]

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

    # The cached TMDB URL points at the w500 size (configured globally for
    # grid posters); for the full-bleed detail backdrop we need the wider
    # w1280 asset so it doesn't pixelate on desktop.
    backdrop_hires_url = ""
    if movie.backdrop_url:
        backdrop_hires_url = movie.backdrop_url.replace("/w500/", "/w1280/")

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
            "backdrop_hires_url": backdrop_hires_url,
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


def _is_htmx(request: HttpRequest) -> bool:
    return request.headers.get("HX-Request") == "true"


def _user_movie_state(user, movie) -> tuple[str | None, int | None]:
    if not user.is_authenticated:
        return None, None
    status_row = UserMovieStatus.objects.filter(user=user, movie=movie).first()
    rating_row = Rating.objects.filter(user=user, movie=movie).first()
    return (
        status_row.status if status_row else None,
        rating_row.score if rating_row else None,
    )


def _detail_partial_context(request: HttpRequest, movie) -> dict[str, Any]:
    user_status, user_rating = _user_movie_state(request.user, movie)
    return {
        "movie": movie,
        "user_status": user_status,
        "user_rating": user_rating,
        "status_watched": UserMovieStatus.WATCHED,
        "status_watchlist": UserMovieStatus.WATCHLIST,
    }


def _htmx_response(*fragments: str) -> HttpResponse:
    return HttpResponse("\n".join(fragments))


def _htmx_actions_response(request: HttpRequest, movie) -> HttpResponse:
    """Swap the actions block + OOB-update the user-rating cell and rating modal."""
    ctx = _detail_partial_context(request, movie)
    return _htmx_response(
        render_to_string("movies/_actions.html", ctx, request=request),
        render_to_string(
            "movies/_user_rating_cell.html", {**ctx, "oob": True}, request=request
        ),
        render_to_string(
            "movies/_rating_modal.html", {**ctx, "oob": True}, request=request
        ),
    )


def _htmx_comments_response(request: HttpRequest, movie) -> HttpResponse:
    comments = list(visible_comments_for(movie))
    ctx = {
        "movie": movie,
        "comments": comments,
        "comments_count": len(comments),
        "comment_max_length": Comment.MAX_LENGTH,
    }
    return _htmx_response(
        render_to_string("movies/_comments_section.html", ctx, request=request),
    )


def _actions_response(request: HttpRequest, movie, tmdb_id: int) -> HttpResponse:
    if _is_htmx(request):
        return _htmx_actions_response(request, movie)
    return _detail_redirect(tmdb_id)


def _comments_response(request: HttpRequest, movie, tmdb_id: int) -> HttpResponse:
    if _is_htmx(request):
        return _htmx_comments_response(request, movie)
    return _detail_redirect(tmdb_id)


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
        return _actions_response(request, movie, tmdb_id)

    if action not in {UserMovieStatus.WATCHLIST, UserMovieStatus.WATCHED}:
        return _actions_response(request, movie, tmdb_id)

    existing = UserMovieStatus.objects.filter(user=request.user, movie=movie).first()
    if existing is not None and existing.status == action:
        remove_movie_status(user=request.user, movie=movie)
        return _actions_response(request, movie, tmdb_id)

    set_movie_status(user=request.user, movie=movie, status=action)
    return _actions_response(request, movie, tmdb_id)


@login_required
@require_POST
def update_movie_rating(request: HttpRequest, tmdb_id: int) -> HttpResponse:
    """Save or delete the current user's rating for a movie."""
    movie = _resolve_movie_or_404(tmdb_id)
    action = request.POST.get("action", "save").strip()

    if action == "delete":
        remove_rating(user=request.user, movie=movie)
        return _actions_response(request, movie, tmdb_id)

    raw_score = request.POST.get("score", "").strip()
    try:
        score = Decimal(raw_score)
    except (ValueError, InvalidOperation):
        return _actions_response(request, movie, tmdb_id)

    try:
        upsert_rating(user=request.user, movie=movie, score=score)
    except ValueError:
        pass
    return _actions_response(request, movie, tmdb_id)


@login_required
@require_POST
def create_movie_comment(request: HttpRequest, tmdb_id: int) -> HttpResponse:
    """Create a new visible comment on the movie. Empty/over-long content is
    silently dropped — the comments section just re-renders unchanged."""
    movie = _resolve_movie_or_404(tmdb_id)
    content = request.POST.get("content", "")
    try:
        create_comment(user=request.user, movie=movie, content=content)
    except ValueError:
        pass
    return _comments_response(request, movie, tmdb_id)


@login_required
@require_POST
def delete_movie_comment(
    request: HttpRequest, tmdb_id: int, comment_id: int
) -> HttpResponse:
    """Delete a comment the current user owns; 404 for anything else."""
    comment = get_object_or_404(Comment, pk=comment_id, movie__tmdb_id=tmdb_id)
    movie = comment.movie
    if not delete_own_comment(user=request.user, comment=comment):
        raise Http404("Nie można usunąć tego komentarza.")
    return _comments_response(request, movie, tmdb_id)
