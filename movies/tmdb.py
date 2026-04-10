"""Thin TMDB v3 API client used by sync commands and the lazy-cache view.

Sync (httpx.Client) on purpose: Django views and management commands here are
sync, and a single per-request HTTP call is fine without async overhead. Can
be swapped to AsyncClient later when views go async.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated, Any

import httpx
from django.conf import settings
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


class TmdbMovieDetail(BaseModel):
    """Shape returned by /movie/{id}."""

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
        self.image_base_url = (image_base_url or settings.TMDB_IMAGE_BASE_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.TMDB_REQUEST_TIMEOUT
        self.language = language if language is not None else settings.TMDB_LANGUAGE

        if not self.api_key:
            raise TmdbConfigError(
                "TMDB_API_KEY is not configured. Set it in your environment "
                "before calling the TMDB client."
            )

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        merged_params: dict[str, Any] = {"api_key": self.api_key, "language": self.language}
        if params:
            merged_params.update(params)
        # Log only the public params — never the api_key.
        safe_params = {k: v for k, v in merged_params.items() if k != "api_key"}
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
                path, response.status_code, response.text[:500],
            )
            raise TmdbApiError(
                f"TMDB request to {path} failed with status {response.status_code}"
            )
        return response.json()

    def list_genres(self) -> list[TmdbGenre]:
        payload = self._get("/genre/movie/list")
        return TmdbGenresResponse.model_validate(payload).genres

    def discover_popular(self, page: int = 1) -> TmdbDiscoverResponse:
        payload = self._get(
            "/discover/movie",
            params={"sort_by": "popularity.desc", "page": page, "include_adult": "false"},
        )
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
        payload = self._get(f"/movie/{tmdb_id}")
        return TmdbMovieDetail.model_validate(payload)

    def image_url(self, path: str | None) -> str:
        if not path:
            return ""
        return f"{self.image_base_url}{path}"
