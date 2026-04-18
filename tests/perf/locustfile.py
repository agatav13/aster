"""Locust performance scenarios for Aster.

Three weighted user behaviors:
- AnonymousBrowser (70%): unauth visits to home/list/detail
- LoggedInBrowser (25%): authenticated browse + rate
- Searcher (5%): query search

Run against a local gunicorn matching production config:
    DJANGO_DEBUG=False uv run gunicorn config.wsgi --workers 1 --bind 127.0.0.1:8000

Then in another shell:
    uv run locust -f tests/perf/locustfile.py --host http://127.0.0.1:8000 \\
        --users 50 --spawn-rate 10 --run-time 5m --headless --html docs/assets/perf/report.html
"""

from __future__ import annotations

import random
import re

from locust import HttpUser, between, task

CSRF_RE = re.compile(r'name="csrfmiddlewaretoken"\s+value="([^"]+)"')

DEFAULT_TMDB_IDS: list[int] = [
    27205,
    155,
    157336,
    24428,
    100402,
    1726,
    49026,
    68721,
    99861,
    284054,
]


def _csrf_from(html: str) -> str | None:
    match = CSRF_RE.search(html)
    return match.group(1) if match else None


class AnonymousBrowser(HttpUser):
    weight = 70
    wait_time = between(1, 3)

    @task(5)
    def home(self) -> None:
        self.client.get("/", name="GET /")

    @task(8)
    def movie_list(self) -> None:
        self.client.get("/movies/", name="GET /movies/")

    @task(3)
    def movie_detail(self) -> None:
        tmdb_id = random.choice(DEFAULT_TMDB_IDS)
        self.client.get(f"/movies/{tmdb_id}/", name="GET /movies/<id>/")


class Searcher(HttpUser):
    weight = 5
    wait_time = between(2, 5)

    QUERIES = ["godfather", "batman", "matrix", "inception", "interstellar"]

    @task
    def search(self) -> None:
        q = random.choice(self.QUERIES)
        self.client.get(f"/movies/?q={q}", name="GET /movies/?q=<query>")


class LoggedInBrowser(HttpUser):
    """Requires a pre-seeded user (perf-user@example.com / PerfPass!23456).

    Create it with:
        uv run manage.py shell -c "from accounts.models import User; \\
            User.objects.create_user(email='perf-user@example.com', \\
            password='PerfPass!23456', is_active=True, is_email_verified=True)"
    """

    weight = 25
    wait_time = between(1, 4)

    def on_start(self) -> None:
        login_page = self.client.get("/auth/login/", name="GET /auth/login/").text
        token = _csrf_from(login_page)
        if not token:
            return
        self.client.post(
            "/auth/login/",
            data={
                "csrfmiddlewaretoken": token,
                "email": "perf-user@example.com",
                "password": "PerfPass!23456",
            },
            headers={"Referer": f"{self.host}/auth/login/"},
            name="POST /auth/login/",
        )

    @task(6)
    def movie_list(self) -> None:
        self.client.get("/movies/", name="GET /movies/")

    @task(2)
    def movie_detail(self) -> None:
        tmdb_id = random.choice(DEFAULT_TMDB_IDS)
        self.client.get(f"/movies/{tmdb_id}/", name="GET /movies/<id>/")

    @task(1)
    def profile(self) -> None:
        self.client.get("/auth/profile/", name="GET /auth/profile/")
