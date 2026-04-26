"""E2E journey 2: browse catalog → open detail → rate → comment.

Covers user-journey 2 from docs/ux/user-journeys.md.
"""

from __future__ import annotations

import re
from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from movies.models import Comment, Movie, Rating


@pytest.mark.django_db(transaction=True)
def test_browse_rate_comment(page: Page, live_server, login_user, movie: Movie) -> None:
    user = login_user()
    base = live_server.url

    page.goto(f"{base}/movies/")
    expect(
        page.get_by_role("heading", name=re.compile(r"Przeglądaj filmy", re.I))
    ).to_be_visible()

    page.goto(f"{base}/movies/{movie.tmdb_id}/")
    expect(
        page.get_by_role("heading", name=re.compile(re.escape(movie.title), re.I))
    ).to_be_visible()

    page.get_by_role("button", name=re.compile(r"Oceń film", re.I)).click()
    page.locator("#ratingModal").wait_for(state="visible")
    page.evaluate(
        "() => {"
        "  const r = document.getElementById('rs-40');"
        "  r.checked = true;"
        "  r.dispatchEvent(new Event('change', {bubbles: true}));"
        "}"
    )
    page.locator("#ratingModal").get_by_role(
        "button", name=re.compile(r"Zapisz", re.I)
    ).click()

    page.locator("#ratingModal").wait_for(state="hidden")
    page.locator(".modal-backdrop").wait_for(state="detached")

    rating = Rating.objects.get(user=user, movie=movie)
    assert rating.score == Decimal("4.0")

    movie.refresh_from_db()
    assert movie.ratings_count == 1
    assert movie.average_rating == Decimal("4.00")

    comment_text = "Bardzo dobry film, polecam każdemu."
    page.locator("#commentBody").fill(comment_text)
    page.get_by_role("button", name=re.compile(r"Wyślij", re.I)).click()

    expect(page.get_by_text(comment_text)).to_be_visible()

    assert Comment.objects.filter(user=user, movie=movie, content=comment_text).exists()
