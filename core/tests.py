from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from movies.models import Movie, Rating, UserMovieStatus


class HomeViewTests(TestCase):
    def test_anonymous_visitor_is_redirected_to_login(self):
        response = self.client.get(reverse("home"))
        self.assertRedirects(response, reverse("accounts:login"))

    def test_authenticated_user_sees_dashboard_inline(self):
        user = get_user_model().objects.create_user(
            email="home-test@example.com",
            password="StrongPass123!",
            is_active=True,
            is_email_verified=True,
            display_name="Ada",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        # Dashboard content is rendered in place at /, no redirect.
        self.assertContains(response, "Witaj, Ada")
        self.assertContains(response, "Moja aktywność")

    def test_no_separate_dashboard_url(self):
        with self.assertRaises(Exception):
            reverse("dashboard")


class DashboardActivityTests(TestCase):
    """The dashboard surfaces each user's three activity lists derived from
    UserMovieStatus (watched, watchlist) and Rating (rated). Empty state only
    appears per-tab when that tab has no rows."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.User = get_user_model()
        cls.user = cls.User.objects.create_user(
            email="dash@example.com",
            password="StrongPass123!",
            is_active=True,
            is_email_verified=True,
        )
        cls.watched_movie = Movie.objects.create(
            tmdb_id=5001,
            title="Watched Flick",
            release_date=date(2020, 1, 1),
            popularity=Decimal("10.00"),
        )
        cls.watchlist_movie = Movie.objects.create(
            tmdb_id=5002,
            title="Later Flick",
            release_date=date(2021, 1, 1),
            popularity=Decimal("10.00"),
        )
        cls.rated_movie = Movie.objects.create(
            tmdb_id=5003,
            title="Scored Flick",
            release_date=date(2022, 1, 1),
            popularity=Decimal("10.00"),
        )

    def setUp(self) -> None:
        self.client.force_login(self.user)

    def test_empty_user_sees_empty_state_per_tab(self) -> None:
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Brak obejrzanych filmów")
        self.assertContains(response, "Brak ocenionych filmów")
        self.assertContains(response, "Pusta lista do obejrzenia")

    def test_watched_movie_shows_up_in_watched_tab(self) -> None:
        UserMovieStatus.objects.create(
            user=self.user,
            movie=self.watched_movie,
            status=UserMovieStatus.WATCHED,
        )

        response = self.client.get(reverse("home"))

        self.assertContains(response, "Watched Flick")
        self.assertEqual(response.context["watched_count"], 1)
        self.assertIn(self.watched_movie, response.context["watched_movies"])

    def test_watchlist_movie_shows_up_in_watchlist_tab(self) -> None:
        UserMovieStatus.objects.create(
            user=self.user,
            movie=self.watchlist_movie,
            status=UserMovieStatus.WATCHLIST,
        )

        response = self.client.get(reverse("home"))

        self.assertContains(response, "Later Flick")
        self.assertEqual(response.context["watchlist_count"], 1)
        self.assertIn(self.watchlist_movie, response.context["watchlist_movies"])

    def test_rated_tab_shows_rated_movies_with_score(self) -> None:
        Rating.objects.create(
            user=self.user, movie=self.rated_movie, score=4
        )

        response = self.client.get(reverse("home"))

        self.assertContains(response, "Scored Flick")
        self.assertContains(response, "4/5")
        self.assertEqual(response.context["rated_count"], 1)
        # Rated context is list of {movie, score} dicts.
        first = response.context["rated_movies"][0]
        self.assertEqual(first["movie"], self.rated_movie)
        self.assertEqual(first["score"], 4)

    def test_other_users_activity_does_not_leak(self) -> None:
        other = self.User.objects.create_user(
            email="other@example.com", password="StrongPass123!"
        )
        UserMovieStatus.objects.create(
            user=other,
            movie=self.watched_movie,
            status=UserMovieStatus.WATCHED,
        )

        response = self.client.get(reverse("home"))

        self.assertEqual(response.context["watched_count"], 0)
        self.assertNotContains(response, "Watched Flick")

    def test_rating_a_watchlisted_movie_moves_it_off_watchlist(self) -> None:
        """End-to-end: movie on watchlist → rate it via POST → dashboard
        now lists it under "Obejrzane" and the watchlist tab is empty.
        Guards against the unique (user, movie) constraint being replaced
        with a second row someday."""
        movie = self.watchlist_movie
        UserMovieStatus.objects.create(
            user=self.user, movie=movie, status=UserMovieStatus.WATCHLIST
        )

        before = self.client.get(reverse("home"))
        self.assertEqual(before.context["watchlist_count"], 1)
        self.assertEqual(before.context["watched_count"], 0)

        self.client.post(
            reverse("movies:update_rating", args=[movie.tmdb_id]),
            {"action": "save", "score": "4"},
        )

        after = self.client.get(reverse("home"))
        self.assertEqual(after.context["watchlist_count"], 0)
        self.assertEqual(after.context["watched_count"], 1)
        self.assertEqual(after.context["rated_count"], 1)
        self.assertIn(movie, after.context["watched_movies"])
        self.assertNotIn(movie, after.context["watchlist_movies"])

    def test_marking_watchlisted_movie_as_watched_moves_it_off_watchlist(
        self,
    ) -> None:
        movie = self.watchlist_movie
        UserMovieStatus.objects.create(
            user=self.user, movie=movie, status=UserMovieStatus.WATCHLIST
        )

        self.client.post(
            reverse("movies:update_status", args=[movie.tmdb_id]),
            {"action": UserMovieStatus.WATCHED},
        )

        response = self.client.get(reverse("home"))
        self.assertEqual(response.context["watchlist_count"], 0)
        self.assertEqual(response.context["watched_count"], 1)
        self.assertIn(movie, response.context["watched_movies"])
        self.assertNotIn(movie, response.context["watchlist_movies"])
        # Exactly one row per (user, movie) — the unique constraint keeps
        # the status table from holding both states simultaneously.
        self.assertEqual(
            UserMovieStatus.objects.filter(user=self.user, movie=movie).count(),
            1,
        )
