from __future__ import annotations

import os
import re
from collections.abc import Iterator
from decimal import Decimal

os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

import pytest  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.core import mail  # noqa: E402

from movies.models import Genre, Movie  # noqa: E402


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-apply the e2e marker to every test under tests/e2e/."""
    for item in items:
        if "tests/e2e/" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)


@pytest.fixture
def browser_context_args(browser_context_args: dict) -> dict:
    return {**browser_context_args, "locale": "pl-PL"}


@pytest.fixture
def genres(db) -> list[Genre]:
    names = ["Akcja", "Dramat", "Komedia", "Horror", "Thriller"]
    result: list[Genre] = []
    for name in names:
        genre = Genre.objects.filter(name=name).first()
        if genre is None:
            genre = Genre.objects.create(name=name)
        result.append(genre)
    return result


@pytest.fixture
def movie(db, genres: list[Genre]) -> Movie:
    m = Movie.objects.create(
        tmdb_id=999_001,
        title="Aster Test Movie",
        original_title="Aster Test Movie",
        overview="Film testowy używany w scenariuszach E2E.",
        poster_url="",
        backdrop_url="",
        original_language="pl",
        average_rating=Decimal("0.00"),
        ratings_count=0,
    )
    m.genres.set(genres[:2])
    return m


@pytest.fixture
def active_user(db, genres: list[Genre]):
    User = get_user_model()
    user = User.objects.create_user(
        email="e2e-user@example.com",
        password="ZaqWsx!23456",
        display_name="E2E User",
        is_active=True,
        is_email_verified=True,
    )
    user.favorite_genres.set(genres[:2])
    return user


@pytest.fixture
def login_user(page, live_server, active_user):
    """Helper that logs `active_user` in via the UI and returns the user."""

    def _login() -> object:
        page.goto(f"{live_server.url}/auth/login/")
        page.get_by_label("Adres e-mail").fill(active_user.email)
        page.get_by_label("Hasło").fill("ZaqWsx!23456")
        page.get_by_role("button", name=re.compile(r"Zaloguj", re.I)).click()
        page.wait_for_url(re.compile(r"/$|/movies"))
        return active_user

    return _login


@pytest.fixture
def clear_outbox() -> Iterator[None]:
    mail.outbox = []
    yield
    mail.outbox = []
