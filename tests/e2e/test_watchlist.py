"""E2E journey 3: add to watchlist → mark as watched.

Covers user-journey 3 from docs/ux/user-journeys.md.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from movies.models import Movie, UserMovieStatus


@pytest.mark.django_db(transaction=True)
def test_watchlist_then_watched(
    page: Page, live_server, login_user, movie: Movie
) -> None:
    user = login_user()
    base = live_server.url

    page.goto(f"{base}/movies/{movie.tmdb_id}/")

    page.get_by_role("button", name=re.compile(r"Obejrzyj później", re.I)).click()
    page.wait_for_url(re.compile(rf"/movies/{movie.tmdb_id}/"))
    expect(
        page.get_by_role("button", name=re.compile(r"Na liście „do obejrzenia”", re.I))
    ).to_be_visible()

    status = UserMovieStatus.objects.get(user=user, movie=movie)
    assert status.status == UserMovieStatus.WATCHLIST

    page.get_by_role("button", name=re.compile(r"Dodaj do obejrzanych", re.I)).click()
    page.wait_for_url(re.compile(rf"/movies/{movie.tmdb_id}/"))
    watched_btn = page.get_by_role("button", name=re.compile(r"Obejrzane", re.I))
    expect(watched_btn.first).to_be_visible()
    expect(watched_btn.first).to_have_attribute("aria-pressed", "true")

    status.refresh_from_db()
    assert status.status == UserMovieStatus.WATCHED
