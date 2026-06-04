from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from community.models import Follow
from community.services import (
    build_feed_groups,
    date_bucket,
    followee_ids_for,
    relative_when,
)
from movies.models import Comment, Movie, Rating, UserMovieStatus

User = get_user_model()


def _make_active_user(email: str, display_name: str = "") -> "User":
    return User.objects.create_user(
        email=email,
        password="StrongPass123!",
        is_active=True,
        is_email_verified=True,
        display_name=display_name,
    )


def _make_movie(tmdb_id: int, title: str = "Film") -> Movie:
    return Movie.objects.create(tmdb_id=tmdb_id, title=title, overview="")


class PublicEmailLeakageTests(TestCase):
    """Public-facing views must never render a user's email address.

    Without a display name the UI must fall back to an opaque "Użytkownik {pk}"
    label — never to the email local-part.
    """

    PRIVATE_EMAIL = "private.person@example.com"

    def _make_viewer(self):
        return User.objects.create_user(
            email="viewer@example.com",
            password="StrongPass123!",
            is_active=True,
            is_email_verified=True,
            display_name="Viewer",
        )

    def _make_target(self, *, display_name: str = "") -> "User":
        return User.objects.create_user(
            email=self.PRIVATE_EMAIL,
            password="StrongPass123!",
            is_active=True,
            is_email_verified=True,
            display_name=display_name,
        )

    def test_community_profile_uses_fallback_when_display_name_missing(self):
        viewer = self._make_viewer()
        target = self._make_target(display_name="")
        self.client.force_login(viewer)

        response = self.client.get(
            reverse("community:profile", kwargs={"user_id": target.pk})
        )
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.PRIVATE_EMAIL, content)
        self.assertNotIn("private.person", content)
        self.assertIn(f"Użytkownik {target.pk}", content)

    def test_community_profile_uses_display_name_when_available(self):
        viewer = self._make_viewer()
        target = self._make_target(display_name="filmlover")
        self.client.force_login(viewer)

        response = self.client.get(
            reverse("community:profile", kwargs={"user_id": target.pk})
        )
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.PRIVATE_EMAIL, content)
        self.assertIn("filmlover", content)

    def test_people_list_does_not_leak_target_email(self):
        viewer = self._make_viewer()
        self._make_target(display_name="")
        self.client.force_login(viewer)

        response = self.client.get(reverse("community:people"))
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.PRIVATE_EMAIL, content)
        self.assertNotIn("private.person", content)

    def test_movie_comments_do_not_leak_email(self):
        viewer = self._make_viewer()
        target = self._make_target(display_name="")
        movie = Movie.objects.create(
            tmdb_id=98765,
            title="Leak Test Movie",
            overview="",
        )
        Comment.objects.create(
            movie=movie,
            user=target,
            content="To jest komentarz",
        )

        self.client.force_login(viewer)
        response = self.client.get(
            reverse("movies:detail", kwargs={"tmdb_id": movie.tmdb_id})
        )
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.PRIVATE_EMAIL, content)
        self.assertNotIn("private.person", content)
        self.assertIn(f"Użytkownik {target.pk}", content)


class PublicNamePropertyTests(TestCase):
    def test_returns_display_name_when_set(self):
        user = User.objects.create_user(
            email="hasname@example.com",
            password="StrongPass123!",
            display_name="Kinoman",
        )
        self.assertEqual(user.public_name, "Kinoman")

    def test_falls_back_to_user_id_without_email(self):
        user = User.objects.create_user(
            email="noname@example.com",
            password="StrongPass123!",
            display_name="",
        )
        self.assertEqual(user.public_name, f"Użytkownik {user.pk}")
        self.assertNotIn("@", user.public_name)
        self.assertNotIn("noname", user.public_name)


class FollowToggleViewTests(TestCase):
    def setUp(self) -> None:
        self.me = _make_active_user("me@example.com", "Me")
        self.other = _make_active_user("other@example.com", "Other")
        self.url = reverse("community:follow_toggle", kwargs={"user_id": self.other.pk})

    def test_get_not_allowed(self) -> None:
        self.client.force_login(self.me)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_anonymous_post_redirects_to_login(self) -> None:
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)
        self.assertFalse(Follow.objects.exists())

    def test_first_post_creates_follow(self) -> None:
        self.client.force_login(self.me)
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Follow.objects.filter(follower=self.me, followee=self.other).exists()
        )

    def test_second_post_toggles_off_idempotently(self) -> None:
        self.client.force_login(self.me)
        self.client.post(self.url)
        self.client.post(self.url)
        self.assertFalse(
            Follow.objects.filter(follower=self.me, followee=self.other).exists()
        )

    def test_cannot_follow_self(self) -> None:
        self.client.force_login(self.me)
        url = reverse("community:follow_toggle", kwargs={"user_id": self.me.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Follow.objects.filter(follower=self.me).exists())

    def test_404_for_inactive_target(self) -> None:
        inactive = User.objects.create_user(
            email="ghost@example.com", password="StrongPass123!", is_active=False
        )
        self.client.force_login(self.me)
        url = reverse("community:follow_toggle", kwargs={"user_id": inactive.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_respects_next_redirect(self) -> None:
        self.client.force_login(self.me)
        profile_url = reverse("community:profile", kwargs={"user_id": self.other.pk})
        response = self.client.post(self.url, {"next": profile_url})
        self.assertRedirects(response, profile_url)

    def test_rejects_offsite_next_redirect(self) -> None:
        self.client.force_login(self.me)
        people_url = reverse("community:people")
        for hostile in ("https://evil.example/phish", "//evil.example/phish"):
            with self.subTest(next=hostile):
                response = self.client.post(self.url, {"next": hostile})
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, people_url)


class FolloweeIdsTests(TestCase):
    def test_returns_only_users_i_follow_directionally(self) -> None:
        me = _make_active_user("me@example.com")
        followee = _make_active_user("followee@example.com")
        follower_of_me = _make_active_user("fan@example.com")
        Follow.objects.create(follower=me, followee=followee)
        # Someone following me must NOT appear among my followees.
        Follow.objects.create(follower=follower_of_me, followee=me)

        self.assertEqual(followee_ids_for(me), [followee.pk])


class BuildFeedGroupsTests(TestCase):
    def setUp(self) -> None:
        self.me = _make_active_user("me@example.com", "Me")
        self.friend = _make_active_user("friend@example.com", "Friend")
        self.stranger = _make_active_user("stranger@example.com", "Stranger")
        self.movie = _make_movie(1, "Inception")
        self.movie2 = _make_movie(2, "Heat")
        Follow.objects.create(follower=self.me, followee=self.friend)

    @staticmethod
    def _set_rating_time(rating: Rating, when) -> None:
        Rating.objects.filter(pk=rating.pk).update(created_at=when)

    @staticmethod
    def _items(groups) -> list:
        return [item for group in groups for item in group.items]

    def test_empty_when_following_nobody(self) -> None:
        loner = _make_active_user("loner@example.com")
        self.assertEqual(build_feed_groups(loner), [])

    def test_includes_followee_rating(self) -> None:
        Rating.objects.create(user=self.friend, movie=self.movie, score=Decimal("4.5"))
        items = self._items(build_feed_groups(self.me))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].user_id, self.friend.pk)
        self.assertEqual(items[0].score, Decimal("4.5"))
        self.assertFalse(items[0].watched)

    def test_excludes_non_followee_activity(self) -> None:
        Rating.objects.create(
            user=self.stranger, movie=self.movie, score=Decimal("5.0")
        )
        self.assertEqual(build_feed_groups(self.me), [])

    def test_dedupes_rating_and_watch_of_same_movie(self) -> None:
        Rating.objects.create(user=self.friend, movie=self.movie, score=Decimal("4.0"))
        UserMovieStatus.objects.create(
            user=self.friend, movie=self.movie, status=UserMovieStatus.WATCHED
        )
        items = self._items(build_feed_groups(self.me))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].score, Decimal("4.0"))
        self.assertTrue(items[0].watched)

    def test_watchlist_status_does_not_appear(self) -> None:
        UserMovieStatus.objects.create(
            user=self.friend, movie=self.movie, status=UserMovieStatus.WATCHLIST
        )
        self.assertEqual(build_feed_groups(self.me), [])

    def test_newest_first_ordering(self) -> None:
        now = timezone.now()
        older = Rating.objects.create(
            user=self.friend, movie=self.movie, score=Decimal("3.0")
        )
        newer = Rating.objects.create(
            user=self.friend, movie=self.movie2, score=Decimal("4.0")
        )
        self._set_rating_time(older, now - timedelta(hours=5))
        self._set_rating_time(newer, now - timedelta(hours=1))

        items = self._items(build_feed_groups(self.me))
        self.assertEqual([i.movie.pk for i in items], [self.movie2.pk, self.movie.pk])

    def test_groups_under_date_buckets(self) -> None:
        now = timezone.now()
        today = Rating.objects.create(
            user=self.friend, movie=self.movie, score=Decimal("3.0")
        )
        yesterday = Rating.objects.create(
            user=self.friend, movie=self.movie2, score=Decimal("4.0")
        )
        self._set_rating_time(today, now)
        self._set_rating_time(yesterday, now - timedelta(days=1))

        groups = build_feed_groups(self.me)
        labels = [g.label for g in groups]
        self.assertEqual(labels[0], "Dzisiaj")
        self.assertIn("Wczoraj", labels)

    def test_limit_caps_total_items(self) -> None:
        for i in range(5):
            Rating.objects.create(
                user=self.friend, movie=_make_movie(100 + i), score=Decimal("3.0")
            )
        items = self._items(build_feed_groups(self.me, limit=2))
        self.assertEqual(len(items), 2)


class DateBucketTests(TestCase):
    def test_today(self) -> None:
        self.assertEqual(date_bucket(timezone.now()), "Dzisiaj")

    def test_yesterday(self) -> None:
        self.assertEqual(date_bucket(timezone.now() - timedelta(days=1)), "Wczoraj")

    def test_within_week(self) -> None:
        self.assertEqual(date_bucket(timezone.now() - timedelta(days=3)), "3 dni temu")

    def test_one_week_ago(self) -> None:
        self.assertEqual(
            date_bucket(timezone.now() - timedelta(days=8)), "Tydzień temu"
        )


class RelativeWhenTests(TestCase):
    def test_minutes(self) -> None:
        self.assertEqual(
            relative_when(timezone.now() - timedelta(minutes=5)), "5 min temu"
        )

    def test_hours(self) -> None:
        self.assertEqual(
            relative_when(timezone.now() - timedelta(hours=3)), "3 godz. temu"
        )

    def test_yesterday(self) -> None:
        self.assertEqual(relative_when(timezone.now() - timedelta(days=1)), "wczoraj")

    def test_days(self) -> None:
        self.assertEqual(
            relative_when(timezone.now() - timedelta(days=3)), "3 dni temu"
        )

    def test_weeks(self) -> None:
        self.assertEqual(
            relative_when(timezone.now() - timedelta(days=14)), "2 tyg. temu"
        )
