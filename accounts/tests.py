from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import Genre, User


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    APP_BASE_URL="http://testserver",
)
class AuthFlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.action = Genre.objects.get(name="Akcja")
        cls.drama = Genre.objects.get(name="Dramat")

    def test_registration_creates_inactive_user_and_sends_email(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "email": "user@example.com",
                "display_name": "Agata",
                "favorite_genres": [self.action.pk, self.drama.pk],
                "password1": "BezpieczneHaslo123!",
                "password2": "BezpieczneHaslo123!",
            },
        )

        self.assertRedirects(response, reverse("accounts:activation_sent"))
        user = User.objects.get(email="user@example.com")
        self.assertFalse(user.is_active)
        self.assertEqual(user.display_name, "Agata")
        self.assertQuerySetEqual(
            user.favorite_genres.order_by("name"),
            Genre.objects.filter(pk__in=[self.action.pk, self.drama.pk]).order_by("name"),
            transform=lambda genre: genre,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/auth/activate/", mail.outbox[0].body)

    def test_registration_renders_genres_as_tiles(self):
        response = self.client.get(reverse("accounts:register"))

        self.assertContains(response, 'class="genre-grid"')
        self.assertContains(response, 'class="genre-choice"')

    def test_registration_requires_at_least_one_genre(self):
        response = self.client.post(
            reverse("accounts:register"),
            {
                "email": "genreless@example.com",
                "display_name": "Bez gatunku",
                "password1": "BezpieczneHaslo123!",
                "password2": "BezpieczneHaslo123!",
            },
        )

        self.assertContains(response, "Wybierz przynajmniej jeden ulubiony gatunek.")
        self.assertFalse(User.objects.filter(email="genreless@example.com").exists())

    def test_display_name_is_not_login_identifier(self):
        user = User.objects.create_user(
            email="auth@example.com",
            password="MocneHaslo123!",
            display_name="kinoholik",
            is_active=True,
            is_email_verified=True,
        )

        response = self.client.post(
            reverse("accounts:login"),
            {"email": user.display_name, "password": "MocneHaslo123!"},
        )

        self.assertContains(response, "Wprowadź poprawny adres email.")

    def test_activation_marks_user_as_verified(self):
        user = User.objects.create_user(
            email="inactive@example.com",
            password="MocneHaslo123!",
            is_active=False,
            is_email_verified=False,
        )
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        response = self.client.get(
            reverse("accounts:activate", kwargs={"uidb64": uid, "token": token})
        )

        user.refresh_from_db()
        self.assertContains(response, "Konto zostało aktywowane")
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_email_verified)

    def test_inactive_user_cannot_login(self):
        User.objects.create_user(
            email="inactive@example.com",
            password="MocneHaslo123!",
            is_active=False,
            is_email_verified=False,
        )

        response = self.client.post(
            reverse("accounts:login"),
            {"email": "inactive@example.com", "password": "MocneHaslo123!"},
        )

        self.assertContains(response, "Konto nie jest jeszcze aktywne")

    def test_active_user_can_login(self):
        user = User.objects.create_user(
            email="active@example.com",
            password="MocneHaslo123!",
            is_active=True,
            is_email_verified=True,
        )

        response = self.client.post(
            reverse("accounts:login"),
            {"email": user.email, "password": "MocneHaslo123!"},
        )

        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_password_reset_sends_email(self):
        User.objects.create_user(
            email="reset@example.com",
            password="MocneHaslo123!",
            is_active=True,
            is_email_verified=True,
        )

        response = self.client.post(
            reverse("accounts:password_reset"),
            {"email": "reset@example.com"},
        )

        self.assertRedirects(response, reverse("accounts:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/auth/reset/", mail.outbox[0].body)

    def test_password_reset_confirm_changes_password(self):
        user = User.objects.create_user(
            email="confirm@example.com",
            password="StareHaslo123!",
            is_active=True,
            is_email_verified=True,
        )
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)

        initial_response = self.client.get(
            reverse(
                "accounts:password_reset_confirm",
                kwargs={"uidb64": uid, "token": token},
            )
        )
        reset_form_url = initial_response.headers["Location"]

        response = self.client.post(
            reset_form_url,
            {
                "new_password1": "NoweHaslo123!",
                "new_password2": "NoweHaslo123!",
            },
        )

        self.assertRedirects(response, reverse("accounts:password_reset_complete"))
        login_response = self.client.post(
            reverse("accounts:login"),
            {"email": user.email, "password": "NoweHaslo123!"},
        )
        self.assertRedirects(login_response, reverse("dashboard"))
