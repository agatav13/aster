"""Tests for the four movies management commands.

The commands are the documented production seeding path; these tests fake the
TMDB client at the command-module boundary and exercise arg parsing, output,
and error handling with the real service layer underneath.
"""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from movies.models import Genre, Movie
from movies.tmdb import (
    TmdbCastMember,
    TmdbConfigError,
    TmdbCredits,
    TmdbCrewMember,
    TmdbDiscoverResponse,
    TmdbGenre,
    TmdbMovieDetail,
    TmdbMovieSummary,
)


def _image_url(path: str | None) -> str:
    return f"https://image.tmdb.org/t/p/w500{path}" if path else ""


@pytest.mark.django_db
@patch("movies.management.commands.sync_tmdb_genres.TmdbClient")
def test_sync_tmdb_genres_upserts_canonical_names(mock_client_class):
    mock_client = mock_client_class.return_value
    # 28 is in TMDB_GENRE_PL_NAMES, so the English name must be overridden.
    mock_client.list_genres.return_value = [TmdbGenre(id=28, name="Action")]

    out = StringIO()
    call_command("sync_tmdb_genres", stdout=out)

    assert "Synced 1 genres" in out.getvalue()
    assert Genre.objects.filter(tmdb_id=28, name="Akcja").exists()


@pytest.mark.django_db
@patch("movies.management.commands.sync_tmdb_genres.TmdbClient")
def test_sync_tmdb_genres_fails_cleanly_without_api_key(mock_client_class):
    mock_client_class.side_effect = TmdbConfigError("TMDB_API_KEY is not configured.")

    with pytest.raises(CommandError, match="TMDB_API_KEY"):
        call_command("sync_tmdb_genres")


@pytest.mark.django_db
@patch("movies.management.commands.sync_tmdb_popular.TmdbClient")
def test_sync_tmdb_popular_ingests_requested_pages(mock_client_class):
    mock_client = mock_client_class.return_value
    mock_client.image_url.side_effect = _image_url
    mock_client.discover_popular.return_value = TmdbDiscoverResponse(
        page=1,
        total_pages=1,
        total_results=1,
        results=[TmdbMovieSummary(id=42, title="Seeded")],
    )
    mock_client.get_movie.return_value = TmdbMovieDetail(
        id=42, title="Seeded", genres=[TmdbGenre(id=18, name="Dramat")]
    )

    out = StringIO()
    call_command("sync_tmdb_popular", "--pages", "1", "--sleep", "0", stdout=out)

    assert "Upserted 1 movies" in out.getvalue()
    assert Movie.objects.filter(tmdb_id=42, title="Seeded").exists()
    mock_client.discover_popular.assert_called_once_with(page=1)


@pytest.mark.django_db
@patch("movies.management.commands.backfill_credits.TmdbClient")
def test_backfill_credits_fills_movies_without_credits(mock_client_class):
    movie = Movie.objects.create(tmdb_id=77, title="Bez obsady")
    mock_client = mock_client_class.return_value
    mock_client.image_url.side_effect = _image_url
    mock_client.get_movie.return_value = TmdbMovieDetail(
        id=77,
        title="Bez obsady",
        credits=TmdbCredits(
            cast=[TmdbCastMember(id=1, name="Aktorka", character="Rola", order=0)],
            crew=[TmdbCrewMember(id=2, name="Reżyser", job="Director")],
        ),
    )

    out = StringIO()
    call_command("backfill_credits", "--sleep", "0", stdout=out)

    assert "Backfilled 1 movies, 0 failed" in out.getvalue()
    assert movie.credits.count() == 2


@pytest.mark.django_db
@patch("movies.management.commands.backfill_credits.TmdbClient")
def test_backfill_credits_noop_when_everything_has_credits(mock_client_class):
    out = StringIO()
    call_command("backfill_credits", stdout=out)

    assert "already have credits" in out.getvalue()
    mock_client_class.return_value.get_movie.assert_not_called()


@pytest.mark.django_db
def test_normalize_genres_reports_consolidation():
    Genre.objects.create(tmdb_id=28, name="Action")  # English orphan to fold

    out = StringIO()
    call_command("normalize_genres", stdout=out)

    assert "canonical genres" in out.getvalue()
    assert Genre.objects.filter(tmdb_id=28, name="Akcja").exists()
