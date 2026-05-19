from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from movies.models import Comment, Movie

User = get_user_model()


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
