from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Comment, Genre, Movie, MovieCredit, Person, Rating, UserMovieStatus
from .services import (
    DEFAULT_PAGE_SIZE,
    TMDB_GENRE_PL_NAMES,
    create_comment,
    delete_own_comment,
    fetch_and_cache_movie,
    fetch_community_top_rated_shelf,
    fetch_continue_exploring_shelf,
    fetch_polish_cinema_shelf,
    fetch_recently_watched_recommendations_shelf,
    fetch_seeded_recommendations_shelf,
    normalize_all_genres,
    remove_movie_status,
    remove_rating,
    set_movie_status,
    sync_all_genres,
    sync_movie_credits,
    upsert_genre,
    upsert_rating,
    visible_comments_for,
)
from .tmdb import (
    TmdbApiError,
    TmdbCastMember,
    TmdbClient,
    TmdbConfigError,
    TmdbCredits,
    TmdbCrewMember,
    TmdbDiscoverResponse,
    TmdbGenre,
    TmdbMovieDetail,
    TmdbMovieSummary,
)


def make_movie(
    *,
    tmdb_id: int,
    title: str,
    popularity: float = 100.0,
    genres: list[Genre] | None = None,
) -> Movie:
    movie = Movie.objects.create(
        tmdb_id=tmdb_id,
        title=title,
        overview=f"Overview for {title}",
        release_date=date(2020, 1, 1),
        runtime_minutes=120,
        popularity=Decimal(str(popularity)),
        poster_url="https://image.tmdb.org/t/p/w500/example.jpg",
    )
    if genres:
        movie.genres.set(genres)
    return movie


@override_settings(TMDB_API_KEY="")
class MovieListViewTests(TestCase):
    """Local-only browse paths. TMDB key is forced empty so search() falls
    back to the local DB, which is what these assertions exercise."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.action = Genre.objects.get(name="Akcja")
        cls.drama = Genre.objects.get(name="Dramat")
        make_movie(tmdb_id=1, title="Inception", popularity=200, genres=[cls.action])
        make_movie(tmdb_id=2, title="The Godfather", popularity=180, genres=[cls.drama])
        make_movie(tmdb_id=3, title="Mad Max", popularity=150, genres=[cls.action])

    def test_list_renders_movies(self) -> None:
        response = self.client.get(reverse("movies:list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Inception")
        self.assertContains(response, "The Godfather")
        self.assertContains(response, "Mad Max")

    def test_search_filter_narrows_results(self) -> None:
        response = self.client.get(reverse("movies:list"), {"q": "godfather"})
        self.assertContains(response, "The Godfather")
        self.assertNotContains(response, "Inception")
        self.assertNotContains(response, "Mad Max")

    def test_genre_filter(self) -> None:
        response = self.client.get(reverse("movies:list"), {"genre": self.drama.id})
        self.assertContains(response, "The Godfather")
        self.assertNotContains(response, "Inception")

    def test_empty_state_when_no_movies_match(self) -> None:
        response = self.client.get(reverse("movies:list"), {"q": "nonexistent"})
        self.assertContains(response, "Brak filmów")

    def test_watched_movies_hidden_for_logged_in_user(self) -> None:
        """Authenticated users should not see titles they marked as watched
        in the grid. Anonymous users still see everything."""
        user = get_user_model().objects.create_user(
            email="viewer@example.com", password="hunter2!!"
        )
        watched = Movie.objects.get(tmdb_id=1)
        UserMovieStatus.objects.create(
            user=user, movie=watched, status=UserMovieStatus.WATCHED
        )

        # Anonymous user: still sees the watched title.
        response = self.client.get(reverse("movies:list"))
        self.assertContains(response, "Inception")

        # Logged-in user: watched title is hidden, others remain.
        self.client.force_login(user)
        response = self.client.get(reverse("movies:list"))
        self.assertNotContains(response, "Inception")
        self.assertContains(response, "The Godfather")
        self.assertContains(response, "Mad Max")

    def test_show_watched_toggle_unhides_watched_titles(self) -> None:
        """`?show_watched=1` opts out of the watched filter so the user can
        re-find titles they've already seen (e.g. to re-rate them)."""
        user = get_user_model().objects.create_user(
            email="reviewer@example.com", password="hunter2!!"
        )
        watched = Movie.objects.get(tmdb_id=1)
        UserMovieStatus.objects.create(
            user=user, movie=watched, status=UserMovieStatus.WATCHED
        )

        self.client.force_login(user)

        # Default: watched title is hidden.
        response = self.client.get(reverse("movies:list"))
        self.assertNotContains(response, "Inception")

        # show_watched=1: watched title returns.
        response = self.client.get(reverse("movies:list"), {"show_watched": "1"})
        self.assertContains(response, "Inception")
        self.assertContains(response, "The Godfather")

    def test_shelf_empty_state_surfaces_when_everything_is_watched(self) -> None:
        """When the watched filter strips a shelf to zero, the shelf is
        kept (not silently dropped) and renders an empty-state hint
        pointing at the `Pokaż obejrzane` toggle. Without this the user
        would see a rail just disappear with no explanation."""
        user = get_user_model().objects.create_user(
            email="completist@example.com", password="hunter2!!"
        )
        # Make tmdb_id=1 community-top-rated eligible (1 rating, COMMUNITY_MIN_RATINGS=1).
        movie = Movie.objects.get(tmdb_id=1)
        movie.average_rating = Decimal("4.50")
        movie.ratings_count = 1
        movie.save(update_fields=["average_rating", "ratings_count"])
        UserMovieStatus.objects.create(
            user=user, movie=movie, status=UserMovieStatus.WATCHED
        )

        self.client.force_login(user)

        # Default: the community shelf had 1 item, all watched → empty-state shows.
        response = self.client.get(reverse("movies:list"))
        self.assertContains(response, "shelf-empty")
        self.assertContains(response, "Wszystkie tytuły z tej listy")

        # show_watched=1: the watched title comes back, so no empty state.
        response = self.client.get(reverse("movies:list"), {"show_watched": "1"})
        self.assertNotContains(response, "shelf-empty")

    def test_watchlist_status_does_not_hide_movie(self) -> None:
        """Only WATCHED hides — WATCHLIST entries should still appear."""
        user = get_user_model().objects.create_user(
            email="planner@example.com", password="hunter2!!"
        )
        movie = Movie.objects.get(tmdb_id=2)
        UserMovieStatus.objects.create(
            user=user, movie=movie, status=UserMovieStatus.WATCHLIST
        )

        self.client.force_login(user)
        response = self.client.get(reverse("movies:list"))
        self.assertContains(response, "The Godfather")


class MovieDetailViewTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.movie = make_movie(tmdb_id=42, title="Cached Movie", popularity=50)

    def test_detail_renders_cached_movie(self) -> None:
        response = self.client.get(reverse("movies:detail", args=[42]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cached Movie")

    @override_settings(TMDB_API_KEY="")
    def test_detail_404_when_unknown_movie_and_no_api_key(self) -> None:
        response = self.client.get(reverse("movies:detail", args=[9999]))
        self.assertEqual(response.status_code, 404)

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_detail_lazy_fetches_from_tmdb(self, mock_client_class) -> None:
        mock_client = mock_client_class.return_value
        mock_client.get_movie.return_value = TmdbMovieDetail(
            id=555,
            title="Lazy Cached",
            overview="Pulled from TMDB on first hit.",
            release_date=date(2024, 6, 1),
            runtime=110,
            poster_path="/poster.jpg",
            popularity=88.5,
            genres=[TmdbGenre(id=28, name="Action")],
            credits=TmdbCredits(
                cast=[TmdbCastMember(id=1, name="Actor", order=0)],
                crew=[TmdbCrewMember(id=2, name="Director", job="Director")],
            ),
        )
        mock_client.image_url.side_effect = lambda path: (
            f"https://image.tmdb.org/t/p/w500{path}" if path else ""
        )

        response = self.client.get(reverse("movies:detail", args=[555]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lazy Cached")
        self.assertTrue(Movie.objects.filter(tmdb_id=555).exists())

        # Second hit should serve from DB and NOT call TMDB again.
        mock_client.get_movie.reset_mock()
        response2 = self.client.get(reverse("movies:detail", args=[555]))
        self.assertEqual(response2.status_code, 200)
        mock_client.get_movie.assert_not_called()


class TmdbClientConfigTests(TestCase):
    @override_settings(TMDB_API_KEY="")
    def test_client_raises_when_api_key_missing(self) -> None:
        with self.assertRaises(TmdbConfigError):
            fetch_and_cache_movie(tmdb_id=99999)

    @override_settings(
        TMDB_API_KEY="fake-key",
        TMDB_RESPONSE_CACHE_TTL=60,
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "tmdb-client-cache-tests",
            }
        },
    )
    @patch("movies.tmdb.httpx.get")
    def test_client_caches_successful_responses(self, mock_get) -> None:
        mock_response = mock_get.return_value
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "page": 1,
            "total_pages": 1,
            "total_results": 1,
            "results": [
                {
                    "id": 1,
                    "title": "Cached Remote",
                    "poster_path": "/poster.jpg",
                    "popularity": 12.0,
                }
            ],
        }

        client = TmdbClient()
        first = client.list_trending()
        second = client.list_trending()

        self.assertEqual(first.results[0].title, "Cached Remote")
        self.assertEqual(second.results[0].title, "Cached Remote")
        mock_get.assert_called_once()


class GenreRelocationTests(TestCase):
    """Smoke test that the move from accounts.Genre → movies.Genre stayed intact."""

    def test_existing_seeded_genres_are_present(self) -> None:
        # Genres seeded in accounts/0002 should still be readable via movies.Genre.
        self.assertTrue(Genre.objects.filter(name="Akcja").exists())
        self.assertTrue(Genre.objects.filter(name="Dramat").exists())

    def test_user_favorite_genres_relation_works(self) -> None:
        user = get_user_model().objects.create_user(
            email="genre-test@example.com",
            password="StrongPass123!",
        )
        action = Genre.objects.get(name="Akcja")
        user.favorite_genres.add(action)
        self.assertIn(action, user.favorite_genres.all())


class UpsertGenreTests(TestCase):
    def test_links_seeded_genre_by_name(self) -> None:
        seeded = Genre.objects.get(name="Akcja")
        self.assertIsNone(seeded.tmdb_id)

        result = upsert_genre(28, "Akcja")

        seeded.refresh_from_db()
        self.assertEqual(result.pk, seeded.pk)
        self.assertEqual(seeded.tmdb_id, 28)

    def test_updates_existing_tmdb_match_in_place(self) -> None:
        existing = Genre.objects.create(tmdb_id=99, name="OldName")
        result = upsert_genre(99, "NewName")
        existing.refresh_from_db()
        self.assertEqual(result.pk, existing.pk)
        self.assertEqual(existing.name, "NewName")

    def test_creates_new_when_no_match(self) -> None:
        before = Genre.objects.count()
        upsert_genre(12345, "Brand New Genre")
        self.assertEqual(Genre.objects.count(), before + 1)
        self.assertTrue(Genre.objects.filter(tmdb_id=12345).exists())

    def test_sci_fi_was_renamed_to_science_fiction(self) -> None:
        # Data migration movies/0002 must have run.
        self.assertFalse(Genre.objects.filter(name="Sci-Fi").exists())
        self.assertTrue(Genre.objects.filter(name="Science Fiction").exists())

    def test_sync_all_genres_overrides_with_polish_alias(self) -> None:
        """Even if TMDB returns English names (e.g. en-US fallback),
        sync_all_genres should produce Polish rows via the alias map."""

        class FakeClient:
            def list_genres(self):
                return [
                    TmdbGenre(id=28, name="Action"),
                    TmdbGenre(id=18, name="Drama"),
                    TmdbGenre(id=10751, name="Family"),
                ]

        sync_all_genres(FakeClient())  # type: ignore[arg-type]

        action = Genre.objects.get(tmdb_id=28)
        drama = Genre.objects.get(tmdb_id=18)
        family = Genre.objects.get(tmdb_id=10751)
        self.assertEqual(action.name, "Akcja")
        self.assertEqual(drama.name, "Dramat")
        self.assertEqual(family.name, "Familijny")
        # No English duplicates should remain.
        self.assertFalse(
            Genre.objects.filter(name__in=["Action", "Drama", "Family"]).exists()
        )

    def test_rename_collision_merges_into_existing_row(self) -> None:
        """Reproduces the en-US-then-pl-PL upgrade path: an English row
        with tmdb_id collides with a Polish seed when re-synced under pl-PL.
        upsert_genre should fold the duplicate into the seed and transfer
        any references."""
        seeded = Genre.objects.get(name="Akcja")
        self.assertIsNone(seeded.tmdb_id)

        english_dup = Genre.objects.create(tmdb_id=28, name="Action")

        # Attach references to BOTH rows so we can verify the merge moves them.
        user = get_user_model().objects.create_user(
            email="merge-fav@example.com", password="StrongPass123!"
        )
        user.favorite_genres.add(seeded)

        movie = Movie.objects.create(
            tmdb_id=777, title="Tagged Movie", popularity=Decimal("10")
        )
        movie.genres.add(english_dup)

        # Re-sync: TMDB returns Polish name with the same tmdb_id.
        result = upsert_genre(28, "Akcja")

        # The Polish seed survived; the English duplicate is gone.
        self.assertEqual(result.pk, seeded.pk)
        self.assertFalse(Genre.objects.filter(pk=english_dup.pk).exists())

        seeded.refresh_from_db()
        self.assertEqual(seeded.tmdb_id, 28)
        self.assertEqual(seeded.name, "Akcja")

        # The movie that was tagged with the English row now points at the seed.
        self.assertIn(seeded, movie.genres.all())
        # The user's favorite stayed valid.
        self.assertIn(seeded, user.favorite_genres.all())


class NormalizeGenresTests(TestCase):
    """End-to-end recovery: a polluted DB with mixed Polish + English rows
    should fold into a Polish-only state with FK references intact."""

    def _build_polluted_state(self) -> tuple[Genre, Genre, Movie]:
        # Seeded Polish row (no tmdb_id) — represents the original
        # accounts/0002 fixtures.
        polish_seed = Genre.objects.get(name="Akcja")
        self.assertIsNone(polish_seed.tmdb_id)

        # English duplicate row created by an earlier en-US sync, still
        # holding the tmdb_id and the movie reference.
        english_dup = Genre.objects.create(tmdb_id=28, name="Action")

        # Another English row that never even got a tmdb_id (e.g. created by
        # hand or by a half-failed sync). normalize should rename / merge it.
        Genre.objects.create(name="Drama", tmdb_id=None)

        # A movie that was synced under the broken state and ended up linked
        # to the English row instead of the Polish seed.
        movie = Movie.objects.create(
            tmdb_id=999, title="Polluted Movie", popularity=Decimal("5")
        )
        movie.genres.add(english_dup)

        return polish_seed, english_dup, movie

    def test_normalize_consolidates_polluted_database(self) -> None:
        polish_seed, english_dup, movie = self._build_polluted_state()

        report = normalize_all_genres()

        # The merge happened.
        self.assertGreaterEqual(report["upserted"], 19)
        self.assertFalse(Genre.objects.filter(pk=english_dup.pk).exists())

        polish_seed.refresh_from_db()
        self.assertEqual(polish_seed.tmdb_id, 28)
        self.assertEqual(polish_seed.name, "Akcja")

        # The orphan English "Drama" row was either merged into the Polish
        # "Dramat" row or renamed in place — either way it must not survive
        # as "Drama".
        self.assertFalse(Genre.objects.filter(name="Drama").exists())
        self.assertTrue(Genre.objects.filter(name="Dramat").exists())

        # Movies that were tagged with the English row now point at the
        # canonical Polish row instead.
        self.assertIn(polish_seed, movie.genres.all())

    def test_normalize_is_idempotent(self) -> None:
        normalize_all_genres()
        first_count = Genre.objects.count()
        normalize_all_genres()
        self.assertEqual(Genre.objects.count(), first_count)

    def test_every_canonical_polish_genre_is_present_after_normalize(self) -> None:
        normalize_all_genres()
        for tmdb_id, polish_name in TMDB_GENRE_PL_NAMES.items():
            row = Genre.objects.filter(tmdb_id=tmdb_id).first()
            self.assertIsNotNone(row, f"Missing genre for tmdb_id={tmdb_id}")
            self.assertEqual(row.name, polish_name)


class TmdbLiveSearchTests(TestCase):
    """The list view should hit TMDB /search/movie when ?q= is set."""

    @classmethod
    def setUpTestData(cls) -> None:
        # One local movie that does NOT match the TMDB query, to prove the
        # search results come from TMDB and not from a local title__icontains.
        make_movie(tmdb_id=1, title="Local Only", popularity=10)

    def _build_response(self, *titles: str) -> TmdbDiscoverResponse:
        return TmdbDiscoverResponse(
            page=1,
            total_pages=1,
            total_results=len(titles),
            results=[
                TmdbMovieSummary(
                    id=10_000 + idx,
                    title=title,
                    poster_path=f"/{title.lower().replace(' ', '_')}.jpg",
                    popularity=50.0,
                )
                for idx, title in enumerate(titles)
            ],
        )

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_search_uses_tmdb_when_configured(self, mock_client_class) -> None:
        mock_client = mock_client_class.return_value
        mock_client.search_movies.return_value = self._build_response(
            "Galactic Quest", "Galactic Empire"
        )
        mock_client.image_url.side_effect = lambda path: (
            f"https://image.tmdb.org/t/p/w500{path}" if path else ""
        )

        response = self.client.get(reverse("movies:list"), {"q": "galactic"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Galactic Quest")
        self.assertContains(response, "Galactic Empire")
        # The local row whose title doesn't match must NOT leak in.
        self.assertNotContains(response, "Local Only")
        self.assertContains(response, "Wyniki z TMDB")
        mock_client.search_movies.assert_called_once_with(query="galactic", page=1)

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_search_falls_back_to_local_on_tmdb_error(self, mock_client_class) -> None:
        mock_client = mock_client_class.return_value
        mock_client.search_movies.side_effect = TmdbApiError("boom")

        # The local DB has a title that matches the query — fallback should
        # find it via title__icontains.
        make_movie(tmdb_id=2, title="Local Galactic Hero", popularity=20)

        response = self.client.get(reverse("movies:list"), {"q": "galactic"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Local Galactic Hero")
        self.assertContains(response, "Wyszukiwarka TMDB jest chwilowo niedostępna")

    @override_settings(TMDB_API_KEY="")
    def test_search_without_tmdb_key_falls_back_silently(self) -> None:
        """No TMDB key configured → use local title search, no warning banner."""
        make_movie(tmdb_id=3, title="Local Galactic Captain", popularity=15)

        response = self.client.get(reverse("movies:list"), {"q": "galactic"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Local Galactic Captain")
        self.assertNotContains(response, "Wyniki z TMDB")
        self.assertContains(response, "Wyniki z lokalnej bazy")

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_search_empty_results_renders_empty_state(self, mock_client_class) -> None:
        mock_client = mock_client_class.return_value
        mock_client.search_movies.return_value = TmdbDiscoverResponse(
            page=1, total_pages=1, total_results=0, results=[]
        )
        mock_client.image_url.side_effect = lambda path: ""

        response = self.client.get(reverse("movies:list"), {"q": "zzznoresults"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Brak filmów do wyświetlenia")

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_search_handles_empty_release_date_string(self, mock_client_class) -> None:
        """Regression: TMDB returns release_date as "" for unreleased movies.
        Pydantic v2's date parser used to crash on this; OptionalDate should
        coerce it to None so the listing renders cleanly."""
        raw_payload = {
            "page": 1,
            "total_pages": 1,
            "total_results": 1,
            "results": [
                {
                    "id": 9001,
                    "title": "Little Women (Unreleased Edition)",
                    "release_date": "",  # the offending value from production
                    "poster_path": "/lw.jpg",
                    "popularity": 12.3,
                    "genre_ids": [],
                }
            ],
        }
        # Validate through the real Pydantic model so we exercise the
        # OptionalDate BeforeValidator end-to-end.
        mock_client = mock_client_class.return_value
        mock_client.search_movies.return_value = TmdbDiscoverResponse.model_validate(
            raw_payload
        )
        mock_client.image_url.side_effect = lambda path: (
            f"https://image.tmdb.org/t/p/w500{path}" if path else ""
        )

        response = self.client.get(reverse("movies:list"), {"q": "little women"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Little Women (Unreleased Edition)")

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_search_stitches_two_tmdb_pages_per_ui_page(
        self, mock_client_class
    ) -> None:
        """A single UI page should pull 2 underlying TMDB pages so users see
        ~40 results per click."""
        mock_client = mock_client_class.return_value
        page1 = TmdbDiscoverResponse(
            page=1,
            total_pages=4,
            total_results=80,
            results=[
                TmdbMovieSummary(id=1000 + i, title=f"P1-{i}", popularity=10.0)
                for i in range(20)
            ],
        )
        page2 = TmdbDiscoverResponse(
            page=2,
            total_pages=4,
            total_results=80,
            results=[
                TmdbMovieSummary(id=2000 + i, title=f"P2-{i}", popularity=10.0)
                for i in range(20)
            ],
        )
        mock_client.search_movies.side_effect = [page1, page2]
        mock_client.image_url.side_effect = lambda path: ""

        response = self.client.get(reverse("movies:list"), {"q": "stitched"})

        self.assertEqual(response.status_code, 200)
        # Both underlying TMDB pages must have been fetched.
        self.assertEqual(mock_client.search_movies.call_count, 2)
        mock_client.search_movies.assert_any_call(query="stitched", page=1)
        mock_client.search_movies.assert_any_call(query="stitched", page=2)
        # Sample one row from each underlying page to confirm both got merged.
        # 40 raw rows → trimmed to 36, so the last 4 of the second page are
        # dropped. P1-0 stays; P2-15 is the last surviving row from page 2.
        self.assertContains(response, "P1-0")
        self.assertContains(response, "P2-15")
        self.assertNotContains(response, "P2-16")
        self.assertNotContains(response, "P2-19")
        # 4 TMDB pages of total → 2 UI pages of 2 TMDB pages each.
        self.assertContains(response, "Strona 1 z 2")


class TmdbDiscoverBrowseTests(TestCase):
    """Default browse (no ?q=) should hit TMDB /discover/movie when configured
    so the catalog isn't capped by whatever happens to be cached locally."""

    @classmethod
    def setUpTestData(cls) -> None:
        # Local row with a non-matching title — proves the default listing
        # comes from TMDB, not from a local fallback that would also include it.
        make_movie(tmdb_id=1, title="Local Cached", popularity=10)
        cls.action = Genre.objects.get(name="Akcja")
        # Pretend the seeded Akcja row was synced so it has a tmdb_id.
        cls.action.tmdb_id = 28
        cls.action.save(update_fields=["tmdb_id"])

    def _build_response(
        self, *titles: str, total_pages: int = 1
    ) -> TmdbDiscoverResponse:
        return TmdbDiscoverResponse(
            page=1,
            total_pages=total_pages,
            total_results=len(titles),
            results=[
                TmdbMovieSummary(
                    id=20_000 + idx,
                    title=title,
                    poster_path=f"/{title.lower().replace(' ', '_')}.jpg",
                    popularity=99.0,
                )
                for idx, title in enumerate(titles)
            ],
        )

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_browse_shelves_populated_from_tmdb(self, mock_client_class) -> None:
        """Unfiltered browse renders the shelves page using live TMDB rails
        (trending, top-rated, now-playing, upcoming). Local cache rows that
        don't match any shelf must not leak in."""
        mock_client = mock_client_class.return_value
        mock_client.list_trending.return_value = self._build_response(
            "Trending One", "Trending Two"
        )
        mock_client.image_url.side_effect = lambda path: (
            f"https://image.tmdb.org/t/p/w500{path}" if path else ""
        )

        response = self.client.get(reverse("movies:list"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["shelves_mode"])
        self.assertContains(response, "Trending One")
        self.assertNotContains(response, "Local Cached")
        mock_client.list_trending.assert_called_with(time_window="week")
        # Catalogue page intentionally doesn't pull any of these any more:
        # TMDB top-rated / Polish cinema / now-playing / upcoming were all
        # retired from /movies/. Trending and community top-rated (local DB)
        # are the only remaining unauthenticated rails.
        mock_client.list_top_rated.assert_not_called()
        mock_client.list_now_playing.assert_not_called()
        mock_client.list_upcoming.assert_not_called()
        mock_client.discover_popular.assert_not_called()

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_browse_falls_back_to_local_on_tmdb_error(self, mock_client_class) -> None:
        """When every shelf fetch errors out, the view falls back to a
        plain local-cache grid instead of rendering an empty shelves page."""
        mock_client = mock_client_class.return_value
        mock_client.list_trending.side_effect = TmdbApiError("boom")
        mock_client.list_top_rated.side_effect = TmdbApiError("boom")
        mock_client.list_now_playing.side_effect = TmdbApiError("boom")
        mock_client.list_upcoming.side_effect = TmdbApiError("boom")

        response = self.client.get(reverse("movies:list"))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["shelves_mode"])
        self.assertContains(response, "Local Cached")

    @override_settings(TMDB_API_KEY="")
    def test_browse_without_tmdb_key_falls_back_silently(self) -> None:
        """Missing TMDB_API_KEY skips every shelf fetch and falls back to
        the local grid without a warning banner — a missing key is a
        configuration choice, not an outage."""
        response = self.client.get(reverse("movies:list"))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["shelves_mode"])
        self.assertContains(response, "Local Cached")
        # No warning banner — missing key is not an outage.
        self.assertNotContains(response, "Wyszukiwarka TMDB jest chwilowo niedostępna")

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_browse_passes_genre_filter_to_tmdb(self, mock_client_class) -> None:
        mock_client = mock_client_class.return_value
        mock_client.discover_popular.return_value = self._build_response("Action Pick")
        mock_client.image_url.side_effect = lambda path: ""

        response = self.client.get(
            reverse("movies:list"), {"genre": str(self.action.id)}
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Action Pick")
        mock_client.discover_popular.assert_called_once_with(page=1, with_genres="28")

    def test_default_page_size_is_a_multiple_of_six(self) -> None:
        """A 6-column movie grid should never end with a partial last row."""
        self.assertEqual(DEFAULT_PAGE_SIZE % 6, 0)

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_grid_trims_stitched_results_to_page_size(self, mock_client_class) -> None:
        """40 raw rows from two stitched TMDB pages should be trimmed down
        to exactly DEFAULT_PAGE_SIZE so the grid has a clean last row.

        Exercised via a search query, which triggers grid mode regardless of
        whether shelves would have been available."""
        mock_client = mock_client_class.return_value
        page1 = TmdbDiscoverResponse(
            page=1,
            total_pages=10,
            total_results=200,
            results=[
                TmdbMovieSummary(id=5000 + i, title=f"T-{i:02d}", popularity=10.0)
                for i in range(20)
            ],
        )
        page2 = TmdbDiscoverResponse(
            page=2,
            total_pages=10,
            total_results=200,
            results=[
                TmdbMovieSummary(id=6000 + i, title=f"T-{20 + i:02d}", popularity=10.0)
                for i in range(20)
            ],
        )
        mock_client.search_movies.side_effect = [page1, page2]
        mock_client.image_url.side_effect = lambda path: ""

        response = self.client.get(reverse("movies:list"), {"q": "anything"})

        self.assertEqual(response.status_code, 200)
        page_obj = response.context["page_obj"]
        self.assertEqual(len(page_obj.object_list), DEFAULT_PAGE_SIZE)

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_grid_stitches_two_tmdb_pages_per_ui_page(self, mock_client_class) -> None:
        mock_client = mock_client_class.return_value
        page1 = TmdbDiscoverResponse(
            page=1,
            total_pages=4,
            total_results=80,
            results=[
                TmdbMovieSummary(id=3000 + i, title=f"D1-{i}", popularity=10.0)
                for i in range(20)
            ],
        )
        page2 = TmdbDiscoverResponse(
            page=2,
            total_pages=4,
            total_results=80,
            results=[
                TmdbMovieSummary(id=4000 + i, title=f"D2-{i}", popularity=10.0)
                for i in range(20)
            ],
        )
        mock_client.search_movies.side_effect = [page1, page2]
        mock_client.image_url.side_effect = lambda path: ""

        response = self.client.get(reverse("movies:list"), {"q": "anything"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_client.search_movies.call_count, 2)
        mock_client.search_movies.assert_any_call(query="anything", page=1)
        mock_client.search_movies.assert_any_call(query="anything", page=2)
        # 40 raw rows → trimmed to 36, so the last 4 of the second page are
        # dropped. D1-0 stays; D2-15 is the last surviving row from page 2.
        self.assertContains(response, "D1-0")
        self.assertContains(response, "D2-15")
        self.assertNotContains(response, "D2-16")
        self.assertNotContains(response, "D2-19")
        # 4 TMDB pages → 2 UI pages of 2 TMDB pages each.
        self.assertContains(response, "Strona 1 z 2")

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_grid_caps_ui_pagination_to_max_ui_pages(self, mock_client_class) -> None:
        """Even when TMDB claims thousands of pages, the UI paginator must
        never offer more than MAX_UI_PAGES — we don't want the grid letting
        users click into noise-territory popularity rankings."""
        from movies.services import MAX_UI_PAGES, TMDB_SEARCH_PAGES_PER_REQUEST

        mock_client = mock_client_class.return_value
        mock_client.search_movies.return_value = TmdbDiscoverResponse(
            page=1,
            total_pages=5000,  # TMDB claims a huge corpus
            total_results=100000,
            results=[
                TmdbMovieSummary(id=7000 + i, title=f"Big-{i}", popularity=10.0)
                for i in range(20)
            ],
        )
        mock_client.image_url.side_effect = lambda path: ""

        response = self.client.get(reverse("movies:list"), {"q": "anything"})

        self.assertEqual(response.status_code, 200)
        page_obj = response.context["page_obj"]
        self.assertEqual(page_obj.num_pages, MAX_UI_PAGES)
        # Sanity: the cap is well below TMDB's own 500 ceiling.
        self.assertLess(MAX_UI_PAGES, 500 // TMDB_SEARCH_PAGES_PER_REQUEST)


class UserMovieStatusServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.User = get_user_model()
        cls.user = cls.User.objects.create_user(
            email="status-svc@example.com", password="StrongPass123!"
        )
        cls.movie = make_movie(tmdb_id=900, title="Status Flick")

    def test_set_status_creates_row(self) -> None:
        set_movie_status(
            user=self.user, movie=self.movie, status=UserMovieStatus.WATCHLIST
        )
        row = UserMovieStatus.objects.get(user=self.user, movie=self.movie)
        self.assertEqual(row.status, UserMovieStatus.WATCHLIST)

    def test_set_status_updates_existing_row(self) -> None:
        set_movie_status(
            user=self.user, movie=self.movie, status=UserMovieStatus.WATCHLIST
        )
        set_movie_status(
            user=self.user, movie=self.movie, status=UserMovieStatus.WATCHED
        )
        rows = UserMovieStatus.objects.filter(user=self.user, movie=self.movie)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().status, UserMovieStatus.WATCHED)

    def test_set_status_rejects_unknown_value(self) -> None:
        with self.assertRaises(ValueError):
            set_movie_status(user=self.user, movie=self.movie, status="bogus")

    def test_remove_status_returns_false_when_missing(self) -> None:
        self.assertFalse(remove_movie_status(user=self.user, movie=self.movie))

    def test_remove_status_deletes_row(self) -> None:
        set_movie_status(
            user=self.user, movie=self.movie, status=UserMovieStatus.WATCHED
        )
        self.assertTrue(remove_movie_status(user=self.user, movie=self.movie))
        self.assertFalse(
            UserMovieStatus.objects.filter(user=self.user, movie=self.movie).exists()
        )


class RatingServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.User = get_user_model()
        cls.user = cls.User.objects.create_user(
            email="rating-svc@example.com", password="StrongPass123!"
        )
        cls.other = cls.User.objects.create_user(
            email="other@example.com", password="StrongPass123!"
        )
        cls.movie = make_movie(tmdb_id=901, title="Rating Flick")

    def test_upsert_creates_and_updates_aggregates(self) -> None:
        upsert_rating(user=self.user, movie=self.movie, score=5)
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.ratings_count, 1)
        self.assertEqual(self.movie.average_rating, Decimal("5.00"))

        upsert_rating(user=self.other, movie=self.movie, score=3)
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.ratings_count, 2)
        self.assertEqual(self.movie.average_rating, Decimal("4.00"))

    def test_upsert_updates_existing_rating(self) -> None:
        upsert_rating(user=self.user, movie=self.movie, score=5)
        upsert_rating(user=self.user, movie=self.movie, score=2)

        self.assertEqual(Rating.objects.filter(user=self.user).count(), 1)
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.average_rating, Decimal("2.00"))
        self.assertEqual(self.movie.ratings_count, 1)

    def test_half_star_rating(self) -> None:
        upsert_rating(user=self.user, movie=self.movie, score=3.5)
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.ratings_count, 1)
        self.assertEqual(self.movie.average_rating, Decimal("3.50"))

    def test_half_star_average(self) -> None:
        upsert_rating(user=self.user, movie=self.movie, score=4)
        upsert_rating(user=self.other, movie=self.movie, score=3.5)
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.average_rating, Decimal("3.75"))

    def test_upsert_rejects_out_of_range(self) -> None:
        for bad in (0, 5.5, -1, 10):
            with self.assertRaises(ValueError):
                upsert_rating(user=self.user, movie=self.movie, score=bad)

    def test_upsert_rejects_non_half_step(self) -> None:
        for bad in (0.3, 1.2, 2.7, 4.9):
            with self.assertRaises(ValueError):
                upsert_rating(user=self.user, movie=self.movie, score=bad)

    def test_remove_rating_refreshes_aggregates(self) -> None:
        upsert_rating(user=self.user, movie=self.movie, score=5)
        upsert_rating(user=self.other, movie=self.movie, score=3)

        self.assertTrue(remove_rating(user=self.user, movie=self.movie))
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.ratings_count, 1)
        self.assertEqual(self.movie.average_rating, Decimal("3.00"))

    def test_remove_all_ratings_resets_aggregates_to_zero(self) -> None:
        upsert_rating(user=self.user, movie=self.movie, score=4)
        remove_rating(user=self.user, movie=self.movie)
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.ratings_count, 0)
        self.assertEqual(self.movie.average_rating, Decimal("0.00"))

    def test_rating_auto_marks_movie_as_watched(self) -> None:
        upsert_rating(user=self.user, movie=self.movie, score=4)
        status = UserMovieStatus.objects.get(user=self.user, movie=self.movie)
        self.assertEqual(status.status, UserMovieStatus.WATCHED)

    def test_rating_promotes_watchlist_to_watched(self) -> None:
        set_movie_status(
            user=self.user, movie=self.movie, status=UserMovieStatus.WATCHLIST
        )
        upsert_rating(user=self.user, movie=self.movie, score=3)
        rows = UserMovieStatus.objects.filter(user=self.user, movie=self.movie)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().status, UserMovieStatus.WATCHED)

    def test_rating_is_noop_on_status_when_already_watched(self) -> None:
        set_movie_status(
            user=self.user, movie=self.movie, status=UserMovieStatus.WATCHED
        )
        upsert_rating(user=self.user, movie=self.movie, score=5)
        rows = UserMovieStatus.objects.filter(user=self.user, movie=self.movie)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().status, UserMovieStatus.WATCHED)

    def test_removing_rating_leaves_watched_status_intact(self) -> None:
        """Removing a rating is not the same as "I didn't watch this" —
        the user just withdrew their score. The watched marker should stay."""
        upsert_rating(user=self.user, movie=self.movie, score=4)
        remove_rating(user=self.user, movie=self.movie)
        self.assertTrue(
            UserMovieStatus.objects.filter(
                user=self.user,
                movie=self.movie,
                status=UserMovieStatus.WATCHED,
            ).exists()
        )

    def test_invalid_score_does_not_create_status(self) -> None:
        with self.assertRaises(ValueError):
            upsert_rating(user=self.user, movie=self.movie, score=99)
        self.assertFalse(
            UserMovieStatus.objects.filter(user=self.user, movie=self.movie).exists()
        )


class MovieStatusViewTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.User = get_user_model()
        cls.user = cls.User.objects.create_user(
            email="status-view@example.com", password="StrongPass123!"
        )
        cls.movie = make_movie(tmdb_id=902, title="View Status")

    def setUp(self) -> None:
        self.client.force_login(self.user)

    def test_post_watchlist_creates_status(self) -> None:
        url = reverse("movies:update_status", args=[self.movie.tmdb_id])
        response = self.client.post(url, {"action": UserMovieStatus.WATCHLIST})
        self.assertRedirects(
            response, reverse("movies:detail", args=[self.movie.tmdb_id])
        )
        self.assertEqual(
            UserMovieStatus.objects.get(user=self.user, movie=self.movie).status,
            UserMovieStatus.WATCHLIST,
        )

    def test_repeated_click_acts_as_toggle_off(self) -> None:
        url = reverse("movies:update_status", args=[self.movie.tmdb_id])
        self.client.post(url, {"action": UserMovieStatus.WATCHED})
        self.client.post(url, {"action": UserMovieStatus.WATCHED})
        self.assertFalse(
            UserMovieStatus.objects.filter(user=self.user, movie=self.movie).exists()
        )

    def test_switching_status_replaces_row(self) -> None:
        url = reverse("movies:update_status", args=[self.movie.tmdb_id])
        self.client.post(url, {"action": UserMovieStatus.WATCHLIST})
        self.client.post(url, {"action": UserMovieStatus.WATCHED})
        row = UserMovieStatus.objects.get(user=self.user, movie=self.movie)
        self.assertEqual(row.status, UserMovieStatus.WATCHED)
        # There must never be a second row — the unique constraint on
        # (user, movie) is what implements "rated/watched removes from
        # watchlist" for free.
        self.assertEqual(
            UserMovieStatus.objects.filter(user=self.user, movie=self.movie).count(),
            1,
        )

    def test_clear_action_removes_row(self) -> None:
        url = reverse("movies:update_status", args=[self.movie.tmdb_id])
        self.client.post(url, {"action": UserMovieStatus.WATCHED})
        self.client.post(url, {"action": "clear"})
        self.assertFalse(
            UserMovieStatus.objects.filter(user=self.user, movie=self.movie).exists()
        )

    def test_anonymous_user_redirected_to_login(self) -> None:
        self.client.logout()
        url = reverse("movies:update_status", args=[self.movie.tmdb_id])
        response = self.client.post(url, {"action": UserMovieStatus.WATCHLIST})
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])


class MovieRatingViewTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.User = get_user_model()
        cls.user = cls.User.objects.create_user(
            email="rating-view@example.com", password="StrongPass123!"
        )
        cls.movie = make_movie(tmdb_id=903, title="View Rating")

    def setUp(self) -> None:
        self.client.force_login(self.user)

    def test_post_score_creates_rating_and_refreshes_average(self) -> None:
        url = reverse("movies:update_rating", args=[self.movie.tmdb_id])
        response = self.client.post(url, {"action": "save", "score": "4"})
        self.assertRedirects(
            response, reverse("movies:detail", args=[self.movie.tmdb_id])
        )
        rating = Rating.objects.get(user=self.user, movie=self.movie)
        self.assertEqual(rating.score, 4)
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.ratings_count, 1)
        self.assertEqual(self.movie.average_rating, Decimal("4.00"))

    def test_post_score_also_marks_movie_as_watched(self) -> None:
        """Rating a movie via the view implies watched — this is what lets
        the dashboard "Ocenione" and "Obejrzane" tabs stay consistent."""
        url = reverse("movies:update_rating", args=[self.movie.tmdb_id])
        self.client.post(url, {"action": "save", "score": "5"})
        status = UserMovieStatus.objects.get(user=self.user, movie=self.movie)
        self.assertEqual(status.status, UserMovieStatus.WATCHED)

    def test_post_score_updates_existing_rating(self) -> None:
        url = reverse("movies:update_rating", args=[self.movie.tmdb_id])
        self.client.post(url, {"action": "save", "score": "5"})
        self.client.post(url, {"action": "save", "score": "2"})
        self.assertEqual(Rating.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Rating.objects.get(user=self.user, movie=self.movie).score, 2)

    def test_delete_action_removes_rating(self) -> None:
        url = reverse("movies:update_rating", args=[self.movie.tmdb_id])
        self.client.post(url, {"action": "save", "score": "3"})
        self.client.post(url, {"action": "delete"})
        self.assertFalse(
            Rating.objects.filter(user=self.user, movie=self.movie).exists()
        )
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.ratings_count, 0)
        self.assertEqual(self.movie.average_rating, Decimal("0.00"))

    def test_invalid_score_does_not_create_rating(self) -> None:
        url = reverse("movies:update_rating", args=[self.movie.tmdb_id])
        self.client.post(url, {"action": "save", "score": "not-a-number"})
        self.assertFalse(Rating.objects.filter(user=self.user).exists())

    def test_half_star_score_via_view(self) -> None:
        url = reverse("movies:update_rating", args=[self.movie.tmdb_id])
        response = self.client.post(url, {"action": "save", "score": "3.5"})
        self.assertRedirects(
            response, reverse("movies:detail", args=[self.movie.tmdb_id])
        )
        rating = Rating.objects.get(user=self.user, movie=self.movie)
        self.assertEqual(rating.score, Decimal("3.5"))
        self.movie.refresh_from_db()
        self.assertEqual(self.movie.average_rating, Decimal("3.50"))

    def test_score_out_of_range_rejected(self) -> None:
        url = reverse("movies:update_rating", args=[self.movie.tmdb_id])
        self.client.post(url, {"action": "save", "score": "9"})
        self.assertFalse(Rating.objects.filter(user=self.user).exists())

    def test_anonymous_user_redirected_to_login(self) -> None:
        self.client.logout()
        url = reverse("movies:update_rating", args=[self.movie.tmdb_id])
        response = self.client.post(url, {"action": "save", "score": "4"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])


class MovieDetailContextTests(TestCase):
    """Detail view should expose the current user's status + rating so the
    template can toggle button styles without a second query."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.User = get_user_model()
        cls.user = cls.User.objects.create_user(
            email="detail-ctx@example.com", password="StrongPass123!"
        )
        cls.movie = make_movie(tmdb_id=904, title="Context Flick")

    def test_anonymous_context_has_no_user_activity(self) -> None:
        response = self.client.get(reverse("movies:detail", args=[self.movie.tmdb_id]))
        self.assertIsNone(response.context["user_status"])
        self.assertIsNone(response.context["user_rating"])

    def test_authenticated_context_reflects_existing_activity(self) -> None:
        set_movie_status(
            user=self.user, movie=self.movie, status=UserMovieStatus.WATCHED
        )
        upsert_rating(user=self.user, movie=self.movie, score=4)

        self.client.force_login(self.user)
        response = self.client.get(reverse("movies:detail", args=[self.movie.tmdb_id]))
        self.assertEqual(response.context["user_status"], UserMovieStatus.WATCHED)
        self.assertEqual(response.context["user_rating"], Decimal("4.0"))


class CommentServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.User = get_user_model()
        cls.user = cls.User.objects.create_user(
            email="comment-svc@example.com", password="StrongPass123!"
        )
        cls.other = cls.User.objects.create_user(
            email="other-svc@example.com", password="StrongPass123!"
        )
        cls.movie = make_movie(tmdb_id=1000, title="Comment Flick")

    def test_create_comment_persists_with_default_visible_status(self) -> None:
        comment = create_comment(
            user=self.user, movie=self.movie, content="Niezłe kino."
        )
        self.assertEqual(comment.status, Comment.VISIBLE)
        self.assertEqual(comment.content, "Niezłe kino.")
        self.assertEqual(comment.movie, self.movie)
        self.assertEqual(comment.user, self.user)

    def test_create_comment_trims_whitespace(self) -> None:
        comment = create_comment(
            user=self.user, movie=self.movie, content="  Świetne!   "
        )
        self.assertEqual(comment.content, "Świetne!")

    def test_create_comment_rejects_empty_content(self) -> None:
        for bad in ("", "   ", "\n\t  "):
            with self.assertRaises(ValueError):
                create_comment(user=self.user, movie=self.movie, content=bad)
        self.assertFalse(Comment.objects.exists())

    def test_create_comment_rejects_too_long_content(self) -> None:
        with self.assertRaises(ValueError):
            create_comment(
                user=self.user,
                movie=self.movie,
                content="x" * (Comment.MAX_LENGTH + 1),
            )

    def test_visible_comments_filters_out_non_visible(self) -> None:
        create_comment(user=self.user, movie=self.movie, content="ok-1")
        Comment.objects.create(
            user=self.user,
            movie=self.movie,
            content="hidden",
            status=Comment.HIDDEN,
        )
        Comment.objects.create(
            user=self.user,
            movie=self.movie,
            content="flagged",
            status=Comment.FLAGGED,
        )

        rows = list(visible_comments_for(self.movie))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].content, "ok-1")

    def test_delete_own_comment_succeeds(self) -> None:
        comment = create_comment(user=self.user, movie=self.movie, content="usuwalny")
        self.assertTrue(delete_own_comment(user=self.user, comment=comment))
        self.assertFalse(Comment.objects.filter(pk=comment.pk).exists())

    def test_delete_own_comment_refuses_other_users_row(self) -> None:
        comment = create_comment(user=self.other, movie=self.movie, content="cudzy")
        self.assertFalse(delete_own_comment(user=self.user, comment=comment))
        self.assertTrue(Comment.objects.filter(pk=comment.pk).exists())


class CommentViewTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.User = get_user_model()
        cls.user = cls.User.objects.create_user(
            email="comment-view@example.com", password="StrongPass123!"
        )
        cls.other = cls.User.objects.create_user(
            email="other-view@example.com", password="StrongPass123!"
        )
        cls.movie = make_movie(tmdb_id=1001, title="Comment View")

    def test_create_comment_requires_login(self) -> None:
        url = reverse("movies:create_comment", args=[self.movie.tmdb_id])
        response = self.client.post(url, {"content": "hej"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])
        self.assertFalse(Comment.objects.exists())

    def test_create_comment_persists_and_redirects_to_detail(self) -> None:
        self.client.force_login(self.user)
        url = reverse("movies:create_comment", args=[self.movie.tmdb_id])
        response = self.client.post(url, {"content": "Bardzo dobre!"})
        self.assertRedirects(
            response, reverse("movies:detail", args=[self.movie.tmdb_id])
        )
        comment = Comment.objects.get()
        self.assertEqual(comment.content, "Bardzo dobre!")
        self.assertEqual(comment.user, self.user)
        self.assertEqual(comment.status, Comment.VISIBLE)

    def test_empty_comment_does_not_persist(self) -> None:
        self.client.force_login(self.user)
        url = reverse("movies:create_comment", args=[self.movie.tmdb_id])
        self.client.post(url, {"content": "   "})
        self.assertFalse(Comment.objects.exists())

    def test_overlong_comment_does_not_persist(self) -> None:
        self.client.force_login(self.user)
        url = reverse("movies:create_comment", args=[self.movie.tmdb_id])
        self.client.post(url, {"content": "x" * (Comment.MAX_LENGTH + 1)})
        self.assertFalse(Comment.objects.exists())

    def test_delete_own_comment_removes_row(self) -> None:
        comment = create_comment(user=self.user, movie=self.movie, content="moje")
        self.client.force_login(self.user)
        url = reverse("movies:delete_comment", args=[self.movie.tmdb_id, comment.pk])
        response = self.client.post(url)
        self.assertRedirects(
            response, reverse("movies:detail", args=[self.movie.tmdb_id])
        )
        self.assertFalse(Comment.objects.filter(pk=comment.pk).exists())

    def test_cannot_delete_someone_elses_comment(self) -> None:
        comment = create_comment(user=self.other, movie=self.movie, content="cudze")
        self.client.force_login(self.user)
        url = reverse("movies:delete_comment", args=[self.movie.tmdb_id, comment.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Comment.objects.filter(pk=comment.pk).exists())

    def test_delete_returns_404_when_comment_belongs_to_other_movie(self) -> None:
        """URL scoping: /movies/<a>/comments/<id-on-movie-b>/delete/ must 404,
        otherwise a crafted URL could delete comments from any movie."""
        other_movie = make_movie(tmdb_id=1002, title="Other Movie")
        comment = create_comment(
            user=self.user, movie=other_movie, content="na innym filmie"
        )
        self.client.force_login(self.user)
        url = reverse("movies:delete_comment", args=[self.movie.tmdb_id, comment.pk])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Comment.objects.filter(pk=comment.pk).exists())


class MovieDetailCommentContextTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.User = get_user_model()
        cls.user = cls.User.objects.create_user(
            email="detail-comments@example.com", password="StrongPass123!"
        )
        cls.movie = make_movie(tmdb_id=1003, title="Comments Context")

    def test_detail_view_lists_visible_comments_newest_first(self) -> None:
        old = create_comment(user=self.user, movie=self.movie, content="stary")
        new = create_comment(user=self.user, movie=self.movie, content="nowy")

        response = self.client.get(reverse("movies:detail", args=[self.movie.tmdb_id]))
        self.assertEqual(response.status_code, 200)
        ctx_comments = list(response.context["comments"])
        self.assertEqual([c.pk for c in ctx_comments], [new.pk, old.pk])
        self.assertEqual(response.context["comments_count"], 2)

    def test_detail_view_hides_non_visible_comments(self) -> None:
        create_comment(user=self.user, movie=self.movie, content="widoczny")
        Comment.objects.create(
            user=self.user,
            movie=self.movie,
            content="ukryty",
            status=Comment.HIDDEN,
        )

        response = self.client.get(reverse("movies:detail", args=[self.movie.tmdb_id]))
        self.assertContains(response, "widoczny")
        self.assertNotContains(response, "ukryty")
        self.assertEqual(response.context["comments_count"], 1)


class CreditSyncTests(TestCase):
    """Tests for sync_movie_credits service function."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.movie = make_movie(tmdb_id=8001, title="Credit Sync Movie")

    @patch("movies.services.TmdbClient")
    def test_sync_creates_director_and_cast(self, mock_client_class) -> None:
        mock_client = mock_client_class.return_value
        mock_client.image_url.side_effect = lambda p: f"https://img{p}" if p else ""

        credits = TmdbCredits(
            cast=[
                TmdbCastMember(
                    id=100,
                    name="Actor One",
                    character="Hero",
                    order=0,
                    profile_path="/a1.jpg",
                ),
                TmdbCastMember(id=101, name="Actor Two", character="Villain", order=1),
            ],
            crew=[
                TmdbCrewMember(
                    id=200, name="Dir One", job="Director", profile_path="/d1.jpg"
                ),
                TmdbCrewMember(id=201, name="Producer One", job="Producer"),
            ],
        )

        sync_movie_credits(self.movie, credits, mock_client)

        self.assertEqual(Person.objects.filter(tmdb_id=100).count(), 1)
        self.assertEqual(Person.objects.filter(tmdb_id=200).count(), 1)
        # Producer should NOT be stored
        self.assertFalse(Person.objects.filter(tmdb_id=201).exists())

        directors = MovieCredit.objects.filter(
            movie=self.movie, credit_type=MovieCredit.DIRECTOR
        )
        self.assertEqual(directors.count(), 1)
        self.assertEqual(directors.first().person.name, "Dir One")

        cast = MovieCredit.objects.filter(
            movie=self.movie, credit_type=MovieCredit.CAST
        ).order_by("order")
        self.assertEqual(cast.count(), 2)
        self.assertEqual(cast[0].character, "Hero")
        self.assertEqual(cast[1].character, "Villain")

    @patch("movies.services.TmdbClient")
    def test_sync_replaces_existing_credits(self, mock_client_class) -> None:
        mock_client = mock_client_class.return_value
        mock_client.image_url.return_value = ""

        old_person = Person.objects.create(tmdb_id=999, name="Old Actor")
        MovieCredit.objects.create(
            movie=self.movie,
            person=old_person,
            credit_type=MovieCredit.CAST,
            order=0,
        )

        credits = TmdbCredits(
            cast=[TmdbCastMember(id=100, name="New Actor", order=0)],
            crew=[],
        )
        sync_movie_credits(self.movie, credits, mock_client)

        remaining = MovieCredit.objects.filter(movie=self.movie)
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.first().person.name, "New Actor")

    @patch("movies.services.TmdbClient")
    def test_sync_deduplicates_repeated_tmdb_credit_rows(
        self, mock_client_class
    ) -> None:
        mock_client = mock_client_class.return_value
        mock_client.image_url.return_value = ""

        credits = TmdbCredits(
            cast=[
                TmdbCastMember(id=100, name="Actor One", character="Hero", order=0),
                TmdbCastMember(id=100, name="Actor One", character="Hero", order=1),
            ],
            crew=[
                TmdbCrewMember(id=200, name="Dir One", job="Director"),
                TmdbCrewMember(id=200, name="Dir One", job="Director"),
            ],
        )

        sync_movie_credits(self.movie, credits, mock_client)

        self.assertEqual(
            MovieCredit.objects.filter(
                movie=self.movie,
                person__tmdb_id=200,
                credit_type=MovieCredit.DIRECTOR,
            ).count(),
            1,
        )
        self.assertEqual(
            MovieCredit.objects.filter(
                movie=self.movie,
                person__tmdb_id=100,
                credit_type=MovieCredit.CAST,
            ).count(),
            1,
        )


class MovieDetailCreditsContextTests(TestCase):
    """Tests that the movie detail view passes credits to the template."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.movie = make_movie(tmdb_id=8002, title="Detail Credits Movie")
        director = Person.objects.create(tmdb_id=300, name="Test Director")
        actor = Person.objects.create(tmdb_id=301, name="Test Actor")
        MovieCredit.objects.create(
            movie=cls.movie,
            person=director,
            credit_type=MovieCredit.DIRECTOR,
        )
        MovieCredit.objects.create(
            movie=cls.movie,
            person=actor,
            credit_type=MovieCredit.CAST,
            character="Main Role",
            order=0,
        )

    def test_detail_renders_director(self) -> None:
        response = self.client.get(reverse("movies:detail", args=[self.movie.tmdb_id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Director")

    def test_detail_renders_cast(self) -> None:
        response = self.client.get(reverse("movies:detail", args=[self.movie.tmdb_id]))
        self.assertContains(response, "Test Actor")
        self.assertContains(response, "Main Role")


class CuratedShelvesTests(TestCase):
    """Unit coverage for the four identity-building shelves added on top of
    the generic TMDB rails."""

    @classmethod
    def setUpTestData(cls) -> None:
        cls.User = get_user_model()
        cls.viewer = cls.User.objects.create_user(
            email="viewer@example.com", password="pw123456!"
        )
        cls.other = cls.User.objects.create_user(
            email="other@example.com", password="pw123456!"
        )

    def _rate(self, user, movie: Movie, score: str) -> None:
        Rating.objects.create(user=user, movie=movie, score=Decimal(score))

    def test_community_top_rated_respects_min_ratings(self) -> None:
        """With min_ratings=2, one-user-one-rating films are excluded; a
        film with 2+ ratings ranks by average, not by popularity. (The
        production default is currently 1 while the rating pool is small
        — see COMMUNITY_MIN_RATINGS — but the gate still works when the
        threshold is bumped back up.)"""
        # Popular-but-unrated row is created so we can assert popularity
        # alone isn't enough to surface it; the return value is unused.
        make_movie(tmdb_id=7001, title="Popular Unrated", popularity=900)
        single_rating = make_movie(tmdb_id=7002, title="Single Rating", popularity=50)
        community_fav = make_movie(tmdb_id=7003, title="Community Fav", popularity=10)

        # Single rating → excluded by min-ratings gate.
        self._rate(self.viewer, single_rating, "5.0")
        single_rating.average_rating = Decimal("5.00")
        single_rating.ratings_count = 1
        single_rating.save(update_fields=["average_rating", "ratings_count"])

        # Two ratings averaging 4.5 → eligible.
        self._rate(self.viewer, community_fav, "4.5")
        self._rate(self.other, community_fav, "4.5")
        community_fav.average_rating = Decimal("4.50")
        community_fav.ratings_count = 2
        community_fav.save(update_fields=["average_rating", "ratings_count"])

        items = fetch_community_top_rated_shelf(min_ratings=2)

        titles = [item.title for item in items]
        self.assertIn("Community Fav", titles)
        self.assertNotIn("Single Rating", titles)
        self.assertNotIn("Popular Unrated", titles)

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_seeded_recommendations_uses_highest_rated_and_excludes_seen(
        self, mock_client_class
    ) -> None:
        """Seed is the user's top rating; movies already on any of their
        lists are filtered out of the results."""
        seed = make_movie(tmdb_id=8101, title="Seed Movie", popularity=100)
        also_seen = make_movie(tmdb_id=8102, title="Already Watched", popularity=50)
        filler = make_movie(tmdb_id=8103, title="Filler Low", popularity=30)

        self._rate(self.viewer, seed, "5.0")
        self._rate(self.viewer, filler, "3.0")
        UserMovieStatus.objects.create(
            user=self.viewer, movie=also_seen, status=UserMovieStatus.WATCHED
        )

        mock_client = mock_client_class.return_value
        mock_client.get_movie_recommendations.return_value = TmdbDiscoverResponse(
            page=1,
            total_pages=1,
            total_results=2,
            results=[
                # This one is already watched → must be filtered out.
                TmdbMovieSummary(
                    id=also_seen.tmdb_id,
                    title="Already Watched",
                    popularity=10.0,
                ),
                TmdbMovieSummary(
                    id=9001,
                    title="Fresh Recommendation",
                    poster_path="/x.jpg",
                    popularity=10.0,
                ),
            ],
        )
        mock_client.image_url.side_effect = lambda path: ""

        seed_movie, items = fetch_seeded_recommendations_shelf(self.viewer)

        self.assertEqual(seed_movie, seed)
        mock_client.get_movie_recommendations.assert_called_once_with(seed.tmdb_id)
        titles = [item.title for item in items]
        self.assertIn("Fresh Recommendation", titles)
        self.assertNotIn("Already Watched", titles)

    @override_settings(
        TMDB_API_KEY="fake-key",
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "personal-shelf-cache-tests",
            }
        },
    )
    @patch("movies.services.TmdbClient")
    def test_seeded_recommendations_are_cached_per_user(
        self, mock_client_class
    ) -> None:
        seed = make_movie(tmdb_id=8110, title="Seed Movie", popularity=100)
        self._rate(self.viewer, seed, "5.0")

        mock_client = mock_client_class.return_value
        mock_client.get_movie_recommendations.return_value = TmdbDiscoverResponse(
            page=1,
            total_pages=1,
            total_results=1,
            results=[
                TmdbMovieSummary(
                    id=9015,
                    title="Cached Shelf Result",
                    poster_path="/x.jpg",
                    popularity=10.0,
                )
            ],
        )
        mock_client.image_url.side_effect = lambda path: ""

        first_seed, first_items = fetch_seeded_recommendations_shelf(self.viewer)
        second_seed, second_items = fetch_seeded_recommendations_shelf(self.viewer)

        self.assertEqual(first_seed, seed)
        self.assertEqual(second_seed, seed)
        self.assertEqual([item.title for item in first_items], ["Cached Shelf Result"])
        self.assertEqual([item.title for item in second_items], ["Cached Shelf Result"])
        mock_client.get_movie_recommendations.assert_called_once_with(seed.tmdb_id)

    def test_seeded_recommendations_returns_none_without_ratings(self) -> None:
        """No ratings → nothing to seed from."""
        seed_movie, items = fetch_seeded_recommendations_shelf(self.viewer)
        self.assertIsNone(seed_movie)
        self.assertEqual(items, [])

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_seeded_recommendations_filters_out_future_releases(
        self, mock_client_class
    ) -> None:
        seed = make_movie(tmdb_id=8104, title="Seed Movie", popularity=100)
        self._rate(self.viewer, seed, "5.0")

        mock_client = mock_client_class.return_value
        mock_client.get_movie_recommendations.return_value = TmdbDiscoverResponse(
            page=1,
            total_pages=1,
            total_results=2,
            results=[
                TmdbMovieSummary(
                    id=9008,
                    title="Future Recommendation",
                    poster_path="/x.jpg",
                    release_date=date(2027, 1, 1),
                    popularity=10.0,
                ),
                TmdbMovieSummary(
                    id=9009,
                    title="Released Recommendation",
                    poster_path="/x.jpg",
                    release_date=date(2026, 1, 1),
                    popularity=9.0,
                ),
            ],
        )
        mock_client.image_url.side_effect = lambda path: ""

        _, items = fetch_seeded_recommendations_shelf(self.viewer)

        self.assertEqual([item.title for item in items], ["Released Recommendation"])

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_watched_recommendations_seeds_from_most_recent_watch(
        self, mock_client_class
    ) -> None:
        """Most-recently watched movie is the seed; interacted titles are
        filtered out of the response."""
        older = make_movie(tmdb_id=8201, title="Older Watch", popularity=20)
        newer = make_movie(tmdb_id=8202, title="Newer Watch", popularity=30)
        already_seen = make_movie(tmdb_id=8203, title="Also Seen", popularity=10)

        UserMovieStatus.objects.create(
            user=self.viewer, movie=older, status=UserMovieStatus.WATCHED
        )
        UserMovieStatus.objects.create(
            user=self.viewer, movie=already_seen, status=UserMovieStatus.WATCHED
        )
        # Created last → updated_at is the most recent, so this is the seed.
        UserMovieStatus.objects.create(
            user=self.viewer, movie=newer, status=UserMovieStatus.WATCHED
        )

        mock_client = mock_client_class.return_value
        mock_client.get_movie_recommendations.return_value = TmdbDiscoverResponse(
            page=1,
            total_pages=1,
            total_results=2,
            results=[
                TmdbMovieSummary(
                    id=already_seen.tmdb_id,
                    title="Also Seen",
                    popularity=5.0,
                ),
                TmdbMovieSummary(
                    id=9201,
                    title="Fresh From Watch",
                    poster_path="/x.jpg",
                    popularity=5.0,
                ),
            ],
        )
        mock_client.image_url.side_effect = lambda path: ""

        seed_movie, items = fetch_recently_watched_recommendations_shelf(self.viewer)

        self.assertEqual(seed_movie, newer)
        mock_client.get_movie_recommendations.assert_called_once_with(newer.tmdb_id)
        titles = [item.title for item in items]
        self.assertIn("Fresh From Watch", titles)
        self.assertNotIn("Also Seen", titles)

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_watched_recommendations_skips_excluded_seed(
        self, mock_client_class
    ) -> None:
        """When the most-recent watch is already used as a seed elsewhere,
        the rail falls back to the next-most-recent watch."""
        primary = make_movie(tmdb_id=8301, title="Already Seeded", popularity=40)
        fallback = make_movie(tmdb_id=8302, title="Fallback Seed", popularity=30)

        UserMovieStatus.objects.create(
            user=self.viewer, movie=fallback, status=UserMovieStatus.WATCHED
        )
        UserMovieStatus.objects.create(
            user=self.viewer, movie=primary, status=UserMovieStatus.WATCHED
        )

        mock_client = mock_client_class.return_value
        mock_client.get_movie_recommendations.return_value = TmdbDiscoverResponse(
            page=1, total_pages=1, total_results=0, results=[]
        )
        mock_client.image_url.side_effect = lambda path: ""

        seed_movie, _ = fetch_recently_watched_recommendations_shelf(
            self.viewer, exclude_seed_movie_ids={primary.id}
        )

        self.assertEqual(seed_movie, fallback)
        mock_client.get_movie_recommendations.assert_called_once_with(fallback.tmdb_id)

    def test_watched_recommendations_returns_none_without_watched(self) -> None:
        """No watched entries → nothing to seed from."""
        seed_movie, items = fetch_recently_watched_recommendations_shelf(self.viewer)
        self.assertIsNone(seed_movie)
        self.assertEqual(items, [])

    def test_watchlist_only_does_not_seed_watched_recommendations(self) -> None:
        """A WATCHLIST entry must not be treated as watched."""
        movie = make_movie(tmdb_id=8401, title="Plan To Watch", popularity=10)
        UserMovieStatus.objects.create(
            user=self.viewer, movie=movie, status=UserMovieStatus.WATCHLIST
        )
        seed_movie, items = fetch_recently_watched_recommendations_shelf(self.viewer)
        self.assertIsNone(seed_movie)
        self.assertEqual(items, [])

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_continue_exploring_prefers_director_from_liked_ratings(
        self, mock_client_class
    ) -> None:
        """Director of a highly-rated movie wins even if an actor co-appears
        on the same film."""
        liked = make_movie(tmdb_id=8201, title="Liked Film", popularity=100)
        self._rate(self.viewer, liked, "4.5")

        director = Person.objects.create(tmdb_id=501, name="Chosen Director")
        actor = Person.objects.create(tmdb_id=502, name="Co-star")
        MovieCredit.objects.create(
            movie=liked, person=director, credit_type=MovieCredit.DIRECTOR
        )
        MovieCredit.objects.create(
            movie=liked, person=actor, credit_type=MovieCredit.CAST, order=0
        )

        mock_client = mock_client_class.return_value
        mock_client.get_person_movie_credits.return_value = TmdbDiscoverResponse(
            page=1,
            total_pages=1,
            total_results=1,
            results=[
                TmdbMovieSummary(
                    id=9201,
                    title="Other Work",
                    poster_path="/x.jpg",
                    popularity=10.0,
                ),
            ],
        )
        mock_client.image_url.side_effect = lambda path: ""

        person, items = fetch_continue_exploring_shelf(self.viewer)

        self.assertIsNotNone(person)
        assert person is not None  # for type checkers
        self.assertEqual(person.pk, director.pk)
        mock_client.get_person_movie_credits.assert_called_once_with(director.tmdb_id)
        self.assertEqual([item.title for item in items], ["Other Work"])

    def test_continue_exploring_returns_none_without_liked_ratings(self) -> None:
        """No high ratings → no person to explore."""
        low_rated = make_movie(tmdb_id=8301, title="Meh", popularity=10)
        self._rate(self.viewer, low_rated, "2.0")

        person, items = fetch_continue_exploring_shelf(self.viewer)
        self.assertIsNone(person)
        self.assertEqual(items, [])

    def test_continue_exploring_ignores_deep_cast_members(self) -> None:
        liked = make_movie(tmdb_id=8304, title="Crowded Cast", popularity=20)
        self._rate(self.viewer, liked, "4.5")

        buried_actor = Person.objects.create(tmdb_id=503, name="Buried Actor")
        MovieCredit.objects.create(
            movie=liked,
            person=buried_actor,
            credit_type=MovieCredit.CAST,
            order=8,
        )

        person, items = fetch_continue_exploring_shelf(self.viewer)
        self.assertIsNone(person)
        self.assertEqual(items, [])

    def test_community_top_rated_filters_future_releases(self) -> None:
        future = make_movie(tmdb_id=7004, title="Future Favorite", popularity=15)
        future.release_date = date(2027, 1, 1)
        future.average_rating = Decimal("5.00")
        future.ratings_count = 2
        future.save(update_fields=["release_date", "average_rating", "ratings_count"])

        released = make_movie(tmdb_id=7005, title="Released Favorite", popularity=14)
        released.average_rating = Decimal("4.50")
        released.ratings_count = 2
        released.save(update_fields=["average_rating", "ratings_count"])

        items = fetch_community_top_rated_shelf()

        titles = [item.title for item in items]
        self.assertIn("Released Favorite", titles)
        self.assertNotIn("Future Favorite", titles)

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_polish_cinema_calls_discover_with_pl_params(
        self, mock_client_class
    ) -> None:
        """The Polish cinema rail forwards language / vote-count / sort
        params straight to TMDB so it surfaces acclaimed local films."""
        mock_client = mock_client_class.return_value
        mock_client.discover_popular.return_value = TmdbDiscoverResponse(
            page=1,
            total_pages=1,
            total_results=1,
            results=[
                TmdbMovieSummary(
                    id=9301, title="Ida", poster_path="/ida.jpg", popularity=5.0
                ),
            ],
        )
        mock_client.image_url.side_effect = lambda path: ""

        items = fetch_polish_cinema_shelf()

        mock_client.discover_popular.assert_called_once_with(
            page=1,
            with_original_language="pl",
            vote_count_gte=50,
            sort_by="vote_average.desc",
        )
        self.assertEqual([item.title for item in items], ["Ida"])

    @override_settings(TMDB_API_KEY="")
    def test_polish_cinema_skips_silently_without_api_key(self) -> None:
        """Missing TMDB_API_KEY must not break the shelf — it should just
        return an empty list so the rail hides itself."""
        self.assertEqual(fetch_polish_cinema_shelf(), [])
