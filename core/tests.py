from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from movies.models import Genre, Movie, MovieCredit, Person, Rating, UserMovieStatus
from movies.services import get_recommendations_for_user, upsert_rating
from movies.tmdb import (
    TmdbCredits,
    TmdbCrewMember,
    TmdbDiscoverResponse,
    TmdbGenre,
    TmdbMovieDetail,
    TmdbMovieSummary,
)


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
        self.assertContains(response, "Rekomendacje dla Ciebie")

    def test_no_separate_dashboard_url(self):
        with self.assertRaises(Exception):
            reverse("dashboard")


class ProfileActivityTests(TestCase):
    """The profile page surfaces each user's three activity lists derived
    from UserMovieStatus (watched, watchlist) and Rating (rated). Empty
    state only appears per-tab when that tab has no rows.

    (These assertions previously lived on the dashboard; the activity tabs
    were moved to /auth/profile/ so Start can be a discovery surface.)"""

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
        response = self.client.get(reverse("accounts:profile"))
        self.assertContains(response, "Brak obejrzanych filmów")
        self.assertContains(response, "Brak ocenionych filmów")
        self.assertContains(response, "Pusta lista do obejrzenia")

    def test_watched_movie_shows_up_in_watched_tab(self) -> None:
        UserMovieStatus.objects.create(
            user=self.user,
            movie=self.watched_movie,
            status=UserMovieStatus.WATCHED,
        )

        response = self.client.get(reverse("accounts:profile"))

        self.assertContains(response, "Watched Flick")
        self.assertEqual(response.context["watched_count"], 1)
        self.assertIn(self.watched_movie, response.context["watched_movies"])

    def test_watchlist_movie_shows_up_in_watchlist_tab(self) -> None:
        UserMovieStatus.objects.create(
            user=self.user,
            movie=self.watchlist_movie,
            status=UserMovieStatus.WATCHLIST,
        )

        response = self.client.get(reverse("accounts:profile"))

        self.assertContains(response, "Later Flick")
        self.assertEqual(response.context["watchlist_count"], 1)
        self.assertIn(self.watchlist_movie, response.context["watchlist_movies"])

    def test_rated_tab_shows_rated_movies_with_score(self) -> None:
        Rating.objects.create(user=self.user, movie=self.rated_movie, score=4)

        response = self.client.get(reverse("accounts:profile"))

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

        response = self.client.get(reverse("accounts:profile"))

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

        before = self.client.get(reverse("accounts:profile"))
        self.assertEqual(before.context["watchlist_count"], 1)
        self.assertEqual(before.context["watched_count"], 0)

        self.client.post(
            reverse("movies:update_rating", args=[movie.tmdb_id]),
            {"action": "save", "score": "4"},
        )

        after = self.client.get(reverse("accounts:profile"))
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

        response = self.client.get(reverse("accounts:profile"))
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


class RecommendationTests(TestCase):
    """Tests for the content-based recommendation engine."""

    @classmethod
    def setUpTestData(cls) -> None:
        User = get_user_model()
        cls.user = User.objects.create_user(
            email="reco@example.com",
            password="StrongPass123!",
            is_active=True,
            is_email_verified=True,
        )

        # Genres may already exist from seed migrations — fetch or create.
        cls.genre_action, _ = Genre.objects.get_or_create(name="Akcja")
        cls.genre_comedy, _ = Genre.objects.get_or_create(name="Komedia")
        cls.genre_horror, _ = Genre.objects.get_or_create(name="Horror")

        cls.liked_movie = Movie.objects.create(
            tmdb_id=9001,
            title="Liked Movie",
            popularity=Decimal("50.00"),
        )
        cls.liked_movie.genres.set([cls.genre_action, cls.genre_comedy])

        cls.candidate_action = Movie.objects.create(
            tmdb_id=9002,
            title="Action Candidate",
            popularity=Decimal("80.00"),
        )
        cls.candidate_action.genres.set([cls.genre_action])

        cls.candidate_comedy = Movie.objects.create(
            tmdb_id=9003,
            title="Comedy Candidate",
            popularity=Decimal("60.00"),
        )
        cls.candidate_comedy.genres.set([cls.genre_comedy])

        cls.candidate_both = Movie.objects.create(
            tmdb_id=9004,
            title="Both Genres Candidate",
            popularity=Decimal("40.00"),
        )
        cls.candidate_both.genres.set([cls.genre_action, cls.genre_comedy])

        cls.unrelated_movie = Movie.objects.create(
            tmdb_id=9005,
            title="Horror Only",
            popularity=Decimal("90.00"),
        )
        cls.unrelated_movie.genres.set([cls.genre_horror])

        # People for credit-based recommendation tests.
        cls.director_a = Person.objects.create(tmdb_id=7001, name="Director A")
        cls.actor_a = Person.objects.create(tmdb_id=7002, name="Actor A")

        MovieCredit.objects.create(
            movie=cls.liked_movie,
            person=cls.director_a,
            credit_type=MovieCredit.DIRECTOR,
        )
        MovieCredit.objects.create(
            movie=cls.liked_movie,
            person=cls.actor_a,
            credit_type=MovieCredit.CAST,
            character="Hero",
            order=0,
        )

        # A candidate sharing the same director (but no genre overlap).
        cls.candidate_same_director = Movie.objects.create(
            tmdb_id=9006,
            title="Same Director Film",
            popularity=Decimal("30.00"),
        )
        cls.candidate_same_director.genres.set([cls.genre_horror])
        MovieCredit.objects.create(
            movie=cls.candidate_same_director,
            person=cls.director_a,
            credit_type=MovieCredit.DIRECTOR,
        )

        # A candidate sharing the same actor (but no genre overlap).
        cls.candidate_same_actor = Movie.objects.create(
            tmdb_id=9007,
            title="Same Actor Film",
            popularity=Decimal("25.00"),
        )
        cls.candidate_same_actor.genres.set([cls.genre_horror])
        MovieCredit.objects.create(
            movie=cls.candidate_same_actor,
            person=cls.actor_a,
            credit_type=MovieCredit.CAST,
            character="Sidekick",
            order=0,
        )

    def test_no_signals_returns_empty(self) -> None:
        result = get_recommendations_for_user(self.user)
        self.assertEqual(result, [])

    def test_favorite_genres_produce_recommendations(self) -> None:
        self.user.favorite_genres.set([self.genre_action])
        result = get_recommendations_for_user(self.user)

        tmdb_ids = [m.tmdb_id for m in result]
        self.assertIn(9002, tmdb_ids)  # action candidate
        self.assertIn(9004, tmdb_ids)  # both genres (has action)
        self.assertIn(9001, tmdb_ids)  # liked_movie (has action, not rated)
        self.assertNotIn(9005, tmdb_ids)  # horror only

        self.user.favorite_genres.clear()

    def test_liked_ratings_produce_recommendations(self) -> None:
        Rating.objects.create(user=self.user, movie=self.liked_movie, score=5)

        result = get_recommendations_for_user(self.user)

        tmdb_ids = [m.tmdb_id for m in result]
        # liked_movie itself is excluded (user has rated it)
        self.assertNotIn(9001, tmdb_ids)
        # Candidates matching action or comedy genres appear
        self.assertIn(9002, tmdb_ids)
        self.assertIn(9003, tmdb_ids)
        self.assertIn(9004, tmdb_ids)
        # Horror-only is excluded (no genre overlap)
        self.assertNotIn(9005, tmdb_ids)

        Rating.objects.filter(user=self.user).delete()

    def test_low_ratings_do_not_contribute_genres(self) -> None:
        Rating.objects.create(user=self.user, movie=self.liked_movie, score=2)

        result = get_recommendations_for_user(self.user)
        self.assertEqual(result, [])

        Rating.objects.filter(user=self.user).delete()

    def test_watched_history_produces_recommendations_without_ratings(self) -> None:
        UserMovieStatus.objects.create(
            user=self.user,
            movie=self.liked_movie,
            status=UserMovieStatus.WATCHED,
        )

        result = get_recommendations_for_user(self.user)

        tmdb_ids = [m.tmdb_id for m in result]
        self.assertNotIn(9001, tmdb_ids)
        self.assertIn(9002, tmdb_ids)
        self.assertIn(9003, tmdb_ids)
        self.assertIn(9004, tmdb_ids)

        UserMovieStatus.objects.filter(user=self.user).delete()

    def test_low_rating_via_service_does_not_become_positive_watch_signal(self) -> None:
        upsert_rating(user=self.user, movie=self.liked_movie, score=2)

        result = get_recommendations_for_user(self.user)
        self.assertEqual(result, [])

        Rating.objects.filter(user=self.user).delete()
        UserMovieStatus.objects.filter(user=self.user).delete()

    def test_disliked_signals_remove_otherwise_matching_candidate(self) -> None:
        director_b = Person.objects.create(tmdb_id=7003, name="Director B")
        disliked = Movie.objects.create(
            tmdb_id=9010,
            title="Disliked Horror",
            popularity=Decimal("20.00"),
        )
        disliked.genres.set([self.genre_horror])
        MovieCredit.objects.create(
            movie=disliked,
            person=director_b,
            credit_type=MovieCredit.DIRECTOR,
        )

        penalized = Movie.objects.create(
            tmdb_id=9011,
            title="Comedy With Bad Signal",
            popularity=Decimal("95.00"),
        )
        penalized.genres.set([self.genre_comedy, self.genre_horror])
        MovieCredit.objects.create(
            movie=penalized,
            person=director_b,
            credit_type=MovieCredit.DIRECTOR,
        )

        Rating.objects.create(user=self.user, movie=self.liked_movie, score=5)
        upsert_rating(user=self.user, movie=disliked, score=2)

        result = get_recommendations_for_user(self.user)
        tmdb_ids = [m.tmdb_id for m in result]
        self.assertIn(9003, tmdb_ids)
        self.assertNotIn(9011, tmdb_ids)

        Rating.objects.filter(user=self.user).delete()
        UserMovieStatus.objects.filter(user=self.user).delete()

    def test_watched_and_watchlisted_movies_are_excluded(self) -> None:
        self.user.favorite_genres.set([self.genre_action])
        UserMovieStatus.objects.create(
            user=self.user,
            movie=self.candidate_action,
            status=UserMovieStatus.WATCHED,
        )
        UserMovieStatus.objects.create(
            user=self.user,
            movie=self.candidate_both,
            status=UserMovieStatus.WATCHLIST,
        )

        result = get_recommendations_for_user(self.user)
        tmdb_ids = [m.tmdb_id for m in result]
        self.assertNotIn(9002, tmdb_ids)  # watched
        self.assertNotIn(9004, tmdb_ids)  # watchlisted

        UserMovieStatus.objects.filter(user=self.user).delete()
        self.user.favorite_genres.clear()

    def test_genre_overlap_ranks_higher_than_popularity(self) -> None:
        self.user.favorite_genres.set([self.genre_action, self.genre_comedy])

        result = get_recommendations_for_user(self.user)
        # candidate_both (2 genre overlaps, pop=40) should rank above
        # candidate_action (1 overlap, pop=80)
        tmdb_ids = [m.tmdb_id for m in result]
        both_idx = tmdb_ids.index(9004)
        action_idx = tmdb_ids.index(9002)
        self.assertLess(both_idx, action_idx)

        self.user.favorite_genres.clear()

    def test_director_signal_produces_recommendations(self) -> None:
        Rating.objects.create(user=self.user, movie=self.liked_movie, score=5)

        result = get_recommendations_for_user(self.user)
        tmdb_ids = [m.tmdb_id for m in result]
        # Same-director candidate appears even though its genres don't overlap
        # with the liked movie's action/comedy.
        self.assertIn(9006, tmdb_ids)

        Rating.objects.filter(user=self.user).delete()

    def test_actor_signal_produces_recommendations(self) -> None:
        Rating.objects.create(user=self.user, movie=self.liked_movie, score=5)

        result = get_recommendations_for_user(self.user)
        tmdb_ids = [m.tmdb_id for m in result]
        self.assertIn(9007, tmdb_ids)

        Rating.objects.filter(user=self.user).delete()

    def test_director_match_outranks_single_genre_overlap(self) -> None:
        """A director match should rank above a single explicit-genre match."""
        Rating.objects.create(user=self.user, movie=self.liked_movie, score=5)

        result = get_recommendations_for_user(self.user)
        tmdb_ids = [m.tmdb_id for m in result]
        # same-director film vs single-genre candidate
        director_idx = tmdb_ids.index(9006)
        # candidate_action has one explicit genre overlap
        action_idx = tmdb_ids.index(9002)
        self.assertLess(director_idx, action_idx)

        Rating.objects.filter(user=self.user).delete()

    def test_only_top_billed_actors_contribute_actor_signal(self) -> None:
        actor_b = Person.objects.create(tmdb_id=7004, name="Buried Cast Member")
        mystery, _ = Genre.objects.get_or_create(name="Tajemnica")

        liked = Movie.objects.create(
            tmdb_id=9012,
            title="High Rated Ensemble",
            popularity=Decimal("30.00"),
        )
        liked.genres.set([self.genre_horror])
        MovieCredit.objects.create(
            movie=liked,
            person=actor_b,
            credit_type=MovieCredit.CAST,
            order=7,
        )

        candidate = Movie.objects.create(
            tmdb_id=9013,
            title="Only Same Deep Cast",
            popularity=Decimal("99.00"),
        )
        candidate.genres.set([mystery])
        MovieCredit.objects.create(
            movie=candidate,
            person=actor_b,
            credit_type=MovieCredit.CAST,
            order=0,
        )

        Rating.objects.create(user=self.user, movie=liked, score=5)

        result = get_recommendations_for_user(self.user)
        tmdb_ids = [m.tmdb_id for m in result]
        self.assertNotIn(9013, tmdb_ids)

        Rating.objects.filter(user=self.user).delete()

    def test_limit_caps_results(self) -> None:
        self.user.favorite_genres.set([self.genre_action])
        result = get_recommendations_for_user(self.user, limit=1)
        self.assertEqual(len(result), 1)

        self.user.favorite_genres.clear()

    def test_recommendations_in_dashboard_context(self) -> None:
        self.client.force_login(self.user)
        Rating.objects.create(user=self.user, movie=self.liked_movie, score=5)

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        recommendations = response.context["recommendations"]
        self.assertTrue(len(recommendations) > 0)
        # The liked movie itself must not appear
        rec_ids = [m.tmdb_id for m in recommendations]
        self.assertNotIn(9001, rec_ids)

        Rating.objects.filter(user=self.user).delete()

    def test_unreleased_local_movie_is_not_recommended(self) -> None:
        self.user.favorite_genres.set([self.genre_action])
        future_movie = Movie.objects.create(
            tmdb_id=9014,
            title="Future Action",
            release_date=date(2027, 1, 1),
            popularity=Decimal("999.00"),
        )
        future_movie.genres.set([self.genre_action])

        result = get_recommendations_for_user(self.user)
        self.assertNotIn(9014, [m.tmdb_id for m in result])

        self.user.favorite_genres.clear()

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_tmdb_candidates_are_cached_and_reranked(self, mock_client_class) -> None:
        Rating.objects.create(user=self.user, movie=self.liked_movie, score=5)

        mock_client = mock_client_class.return_value
        mock_client.get_movie_recommendations.return_value = TmdbDiscoverResponse(
            page=1,
            total_pages=1,
            total_results=1,
            results=[
                TmdbMovieSummary(
                    id=9901,
                    title="Remote Match",
                    poster_path="/x.jpg",
                    release_date=date(2026, 1, 1),
                    popularity=70.0,
                )
            ],
        )
        mock_client.get_movie.return_value = TmdbMovieDetail(
            id=9901,
            title="Remote Match",
            poster_path="/x.jpg",
            release_date=date(2026, 1, 1),
            popularity=70.0,
            genres=[TmdbGenre(id=28, name="Akcja")],
            credits=TmdbCredits(
                crew=[
                    TmdbCrewMember(
                        id=self.director_a.tmdb_id, name="Director A", job="Director"
                    )
                ]
            ),
        )
        mock_client.image_url.side_effect = lambda path: ""

        result = get_recommendations_for_user(self.user)

        tmdb_ids = [m.tmdb_id for m in result]
        self.assertIn(9901, tmdb_ids)
        self.assertTrue(Movie.objects.filter(tmdb_id=9901).exists())

        Rating.objects.filter(user=self.user).delete()

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_tmdb_future_movie_is_not_recommended(self, mock_client_class) -> None:
        Rating.objects.create(user=self.user, movie=self.liked_movie, score=5)

        mock_client = mock_client_class.return_value
        mock_client.get_movie_recommendations.return_value = TmdbDiscoverResponse(
            page=1,
            total_pages=1,
            total_results=1,
            results=[
                TmdbMovieSummary(
                    id=9902,
                    title="Future Remote Match",
                    poster_path="/x.jpg",
                    release_date=date(2027, 1, 1),
                    popularity=70.0,
                )
            ],
        )
        mock_client.image_url.side_effect = lambda path: ""

        result = get_recommendations_for_user(self.user)

        self.assertNotIn(9902, [m.tmdb_id for m in result])
        mock_client.get_movie.assert_not_called()

        Rating.objects.filter(user=self.user).delete()

    def test_empty_recommendations_show_placeholder(self) -> None:
        self.client.force_login(self.user)
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["recommendations"]), 0)
        self.assertContains(response, "algorytm zacznie")
