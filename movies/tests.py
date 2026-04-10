from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Genre, Movie
from .services import (
    TMDB_GENRE_PL_NAMES,
    fetch_and_cache_movie,
    normalize_all_genres,
    sync_all_genres,
    upsert_genre,
)
from .tmdb import (
    TmdbApiError,
    TmdbConfigError,
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
        self.assertFalse(Genre.objects.filter(name__in=["Action", "Drama", "Family"]).exists())

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


class FavoritesFilterTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.action = Genre.objects.get(name="Akcja")
        cls.drama = Genre.objects.get(name="Dramat")
        cls.horror = Genre.objects.get(name="Horror")
        cls.action_movie = make_movie(
            tmdb_id=101, title="Action Hero", popularity=300, genres=[cls.action]
        )
        cls.drama_movie = make_movie(
            tmdb_id=102, title="Dramatic Tale", popularity=290, genres=[cls.drama]
        )
        cls.horror_movie = make_movie(
            tmdb_id=103, title="Spooky Night", popularity=280, genres=[cls.horror]
        )

    def _login_user_with_favorites(self, *favorites: Genre):
        user = get_user_model().objects.create_user(
            email="fav-test@example.com",
            password="StrongPass123!",
            is_active=True,
            is_email_verified=True,
        )
        if favorites:
            user.favorite_genres.set(favorites)
        self.client.force_login(user)
        return user

    def test_favorites_filter_returns_only_matching_movies(self) -> None:
        self._login_user_with_favorites(self.action, self.drama)

        response = self.client.get(reverse("movies:list"), {"favorites": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Action Hero")
        self.assertContains(response, "Dramatic Tale")
        self.assertNotContains(response, "Spooky Night")

    def test_favorites_filter_ignored_when_anonymous(self) -> None:
        response = self.client.get(reverse("movies:list"), {"favorites": "1"})
        self.assertEqual(response.status_code, 200)
        # Anonymous users see all movies.
        self.assertContains(response, "Action Hero")
        self.assertContains(response, "Spooky Night")

    def test_favorites_filter_with_no_favorites_shows_all(self) -> None:
        self._login_user_with_favorites()  # no favorites
        response = self.client.get(reverse("movies:list"), {"favorites": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Action Hero")
        self.assertContains(response, "Spooky Night")

    def test_favorites_button_visible_when_user_has_favorites(self) -> None:
        self._login_user_with_favorites(self.action)
        response = self.client.get(reverse("movies:list"))
        self.assertContains(response, "Moje ulubione")

    def test_favorites_button_hidden_when_no_favorites(self) -> None:
        self._login_user_with_favorites()
        response = self.client.get(reverse("movies:list"))
        self.assertNotContains(response, "Moje ulubione")


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
        self.assertContains(response, "Wyniki na żywo z TMDB")
        mock_client.search_movies.assert_called_once_with(
            query="galactic", page=1
        )

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_search_falls_back_to_local_on_tmdb_error(
        self, mock_client_class
    ) -> None:
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
        self.assertNotContains(response, "Wyniki na żywo z TMDB")
        self.assertContains(response, "Wyniki z lokalnej bazy")

    @override_settings(TMDB_API_KEY="fake-key")
    @patch("movies.services.TmdbClient")
    def test_search_empty_results_renders_empty_state(
        self, mock_client_class
    ) -> None:
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
    def test_search_handles_empty_release_date_string(
        self, mock_client_class
    ) -> None:
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
        mock_client.search_movies.return_value = (
            TmdbDiscoverResponse.model_validate(raw_payload)
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
        self.assertContains(response, "P1-0")
        self.assertContains(response, "P2-19")
        # 4 TMDB pages of total → 2 UI pages of 2 TMDB pages each.
        self.assertContains(response, "Strona 1 z 2")
