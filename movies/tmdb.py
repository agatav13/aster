"""Thin TMDB v3 API client used by sync commands and the lazy-cache view.

Sync (httpx.Client) on purpose: Django views and management commands here are
sync, and a single per-request HTTP call is fine without async overhead. Can
be swapped to AsyncClient later when views go async.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from typing import Annotated, Any

import httpx
from django.conf import settings
from django.core.cache import cache
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

logger = logging.getLogger(__name__)


def _empty_string_to_none(value: Any) -> Any:
    """Coerce TMDB's empty-string sentinel into None.

    TMDB returns `release_date: ""` for unreleased / unscheduled movies
    instead of omitting the field. Pydantic v2's date parser rejects an
    empty string, so we normalize it to None before validation.
    """
    if isinstance(value, str) and not value.strip():
        return None
    return value


# Reusable annotated type: any optional date field that may arrive as "".
OptionalDate = Annotated[date | None, BeforeValidator(_empty_string_to_none)]


class TmdbConfigError(RuntimeError):
    """Raised when TMDB_API_KEY is not configured."""


class TmdbApiError(RuntimeError):
    """Raised when the TMDB API returns a non-success response."""


class TmdbGenre(BaseModel):
    id: int
    name: str


class TmdbGenresResponse(BaseModel):
    genres: list[TmdbGenre]


class TmdbMovieSummary(BaseModel):
    """Shape returned by /discover/movie and /movie/popular."""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    title: str
    original_title: str = ""
    overview: str = ""
    release_date: OptionalDate = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    original_language: str = ""
    popularity: float | None = None
    genre_ids: list[int] = Field(default_factory=list)


class TmdbDiscoverResponse(BaseModel):
    page: int
    total_pages: int
    total_results: int
    results: list[TmdbMovieSummary]


class TmdbCastMember(BaseModel):
    """Single cast entry from /movie/{id}/credits."""

    id: int
    name: str
    character: str = ""
    order: int = 0
    profile_path: str | None = None


class TmdbCrewMember(BaseModel):
    """Single crew entry from /movie/{id}/credits."""

    id: int
    name: str
    job: str = ""
    profile_path: str | None = None


class TmdbCredits(BaseModel):
    cast: list[TmdbCastMember] = Field(default_factory=list)
    crew: list[TmdbCrewMember] = Field(default_factory=list)


class TmdbMovieDetail(BaseModel):
    """Shape returned by /movie/{id} (with optional append_to_response=credits)."""

    id: int
    title: str
    original_title: str = ""
    overview: str = ""
    release_date: OptionalDate = None
    runtime: int | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    original_language: str = ""
    popularity: float | None = None
    genres: list[TmdbGenre] = Field(default_factory=list)
    credits: TmdbCredits | None = None


class TmdbClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        image_base_url: str | None = None,
        timeout: float | None = None,
        language: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.TMDB_API_KEY
        self.base_url = (base_url or settings.TMDB_API_BASE_URL).rstrip("/")
        self.image_base_url = (image_base_url or settings.TMDB_IMAGE_BASE_URL).rstrip(
            "/"
        )
        self.timeout = timeout if timeout is not None else settings.TMDB_REQUEST_TIMEOUT
        self.language = language if language is not None else settings.TMDB_LANGUAGE

        if not self.api_key:
            raise TmdbConfigError(
                "TMDB_API_KEY is not configured. Set it in your environment "
                "before calling the TMDB client."
            )

    def _cache_key(self, path: str, params: dict[str, Any]) -> str:
        serialized = json.dumps(
            {
                "path": path,
                "language": self.language,
                "params": params,
            },
            sort_keys=True,
            default=str,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return f"tmdb:response:{digest}"

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        merged_params: dict[str, Any] = {
            "api_key": self.api_key,
            "language": self.language,
        }
        if params:
            merged_params.update(params)
        # Log only the public params — never the api_key.
        safe_params = {k: v for k, v in merged_params.items() if k != "api_key"}
        cache_key = self._cache_key(path, safe_params)
        cached_payload = cache.get(cache_key)
        if cached_payload is not None:
            logger.debug("TMDB cache hit %s params=%s", path, safe_params)
            return cached_payload
        logger.debug("TMDB GET %s params=%s", path, safe_params)
        try:
            response = httpx.get(url, params=merged_params, timeout=self.timeout)
        except httpx.HTTPError as exc:
            logger.warning("TMDB transport error on %s: %s", path, exc)
            raise TmdbApiError(f"TMDB request to {path} failed") from exc
        if response.status_code >= 400:
            # Log the body server-side for debugging, but keep the raised
            # message generic so it's safe to show to end users.
            logger.warning(
                "TMDB %s returned HTTP %s; body=%r",
                path,
                response.status_code,
                response.text[:500],
            )
            raise TmdbApiError(
                f"TMDB request to {path} failed with status {response.status_code}"
            )
        payload = response.json()
        cache.set(
            cache_key,
            payload,
            getattr(settings, "TMDB_RESPONSE_CACHE_TTL", 15 * 60),
        )
        return payload

    def list_genres(self) -> list[TmdbGenre]:
        payload = self._get("/genre/movie/list")
        return TmdbGenresResponse.model_validate(payload).genres

    def list_trending(
        self,
        time_window: str = "week",
        page: int = 1,
    ) -> TmdbDiscoverResponse:
        """Fetch TMDB's trending movies for the given time window.

        `time_window` is "day" or "week". The response shape is identical to
        `/discover/movie` so `TmdbDiscoverResponse` and `MovieListItem` can
        consume both endpoints uniformly. `/trending/*` does NOT accept
        `with_genres` — callers that need genre filtering must fall back to
        `discover_popular`.
        """
        if time_window not in ("day", "week"):
            raise ValueError(
                f"time_window must be 'day' or 'week', got {time_window!r}"
            )
        payload = self._get(f"/trending/movie/{time_window}", params={"page": page})
        return TmdbDiscoverResponse.model_validate(payload)

    def discover_popular(
        self,
        page: int = 1,
        with_genres: str | None = None,
        *,
        with_original_language: str | None = None,
        vote_count_gte: int | None = None,
        sort_by: str = "popularity.desc",
    ) -> TmdbDiscoverResponse:
        """Browse popular movies.

        `with_genres` is forwarded straight to TMDB's `/discover/movie`
        endpoint. Use a single id to filter by one genre, "id1,id2" for AND,
        or "id1|id2" for OR — see TMDB's discover docs. The remaining
        keyword-only filters (`with_original_language`, `vote_count_gte`,
        `sort_by`) power editorial shelves like "Polish cinema" without
        needing a separate method per use case.
        """
        params: dict[str, Any] = {
            "sort_by": sort_by,
            "page": page,
            "include_adult": "false",
        }
        if with_genres:
            params["with_genres"] = with_genres
        if with_original_language:
            params["with_original_language"] = with_original_language
        if vote_count_gte is not None:
            params["vote_count.gte"] = vote_count_gte
        payload = self._get("/discover/movie", params=params)
        return TmdbDiscoverResponse.model_validate(payload)

    def get_movie_recommendations(
        self, tmdb_id: int, page: int = 1
    ) -> TmdbDiscoverResponse:
        """Movies TMDB recommends as similar to the given one."""
        payload = self._get(
            f"/movie/{tmdb_id}/recommendations",
            params={"page": page},
        )
        return TmdbDiscoverResponse.model_validate(payload)

    def get_person_movie_credits(self, person_id: int) -> TmdbDiscoverResponse:
        """Filmography for a person (cast + crew), normalized to the shared
        TmdbMovieSummary shape so it can feed a shelf directly.

        TMDB returns cast and crew as separate arrays with a different per-row
        shape than /discover/movie. We project both to TmdbMovieSummary,
        de-duplicate by movie id (so a director-and-writer on the same film
        only appears once), and hand back a synthetic single-page response.
        """
        payload = self._get(f"/person/{person_id}/movie_credits")
        seen: dict[int, dict[str, Any]] = {}
        for row in list(payload.get("cast") or []) + list(payload.get("crew") or []):
            movie_id = row.get("id")
            if movie_id is None or movie_id in seen:
                continue
            seen[movie_id] = {
                "id": movie_id,
                "title": row.get("title") or "",
                "original_title": row.get("original_title") or "",
                "overview": row.get("overview") or "",
                "release_date": row.get("release_date") or None,
                "poster_path": row.get("poster_path"),
                "backdrop_path": row.get("backdrop_path"),
                "original_language": row.get("original_language") or "",
                "popularity": row.get("popularity"),
                "genre_ids": row.get("genre_ids") or [],
            }
        results = [TmdbMovieSummary.model_validate(row) for row in seen.values()]
        results.sort(key=lambda r: r.popularity or 0, reverse=True)
        return TmdbDiscoverResponse(
            page=1,
            total_pages=1,
            total_results=len(results),
            results=results,
        )

    def list_top_rated(self, page: int = 1) -> TmdbDiscoverResponse:
        """Top-rated movies across TMDB's all-time chart."""
        payload = self._get("/movie/top_rated", params={"page": page})
        return TmdbDiscoverResponse.model_validate(payload)

    def list_now_playing(self, page: int = 1) -> TmdbDiscoverResponse:
        """Movies currently playing in theatres.

        TMDB's `/movie/now_playing` is region-sensitive; we leave `region`
        unset so TMDB picks a sensible default from the configured language.
        """
        payload = self._get("/movie/now_playing", params={"page": page})
        return TmdbDiscoverResponse.model_validate(payload)

    def list_upcoming(self, page: int = 1) -> TmdbDiscoverResponse:
        """Upcoming theatrical releases in the next few weeks."""
        payload = self._get("/movie/upcoming", params={"page": page})
        return TmdbDiscoverResponse.model_validate(payload)

    def search_movies(self, query: str, page: int = 1) -> TmdbDiscoverResponse:
        """Free-text title search via TMDB /search/movie.

        Returns the same shape as discover_popular so the calling code can
        treat both endpoints uniformly. TMDB caps `page` at 500 server-side.
        """
        payload = self._get(
            "/search/movie",
            params={"query": query, "page": page, "include_adult": "false"},
        )
        return TmdbDiscoverResponse.model_validate(payload)

    def get_movie(self, tmdb_id: int) -> TmdbMovieDetail:
        payload = self._get(
            f"/movie/{tmdb_id}",
            params={"append_to_response": "credits"},
        )
        return TmdbMovieDetail.model_validate(payload)

    def image_url(self, path: str | None) -> str:
        if not path:
            return ""
        return f"{self.image_base_url}{path}"
