from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from movies.models import Genre

from .models import User


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
            Genre.objects.filter(pk__in=[self.action.pk, self.drama.pk]).order_by(
                "name"
            ),
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

        self.assertRedirects(response, reverse("home"))
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

    def test_edit_favorite_genres_requires_login(self):
        response = self.client.get(reverse("accounts:edit_favorite_genres"))
        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('accounts:edit_favorite_genres')}",
        )

    def test_edit_favorite_genres_renders_for_logged_in_user(self):
        user = User.objects.create_user(
            email="editor@example.com",
            password="MocneHaslo123!",
            is_active=True,
            is_email_verified=True,
        )
        user.favorite_genres.set([self.action])
        self.client.force_login(user)

        response = self.client.get(reverse("accounts:edit_favorite_genres"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Edytuj ulubione gatunki")
        self.assertContains(response, 'class="genre-grid"')

    def test_edit_favorite_genres_updates_selection(self):
        user = User.objects.create_user(
            email="updater@example.com",
            password="MocneHaslo123!",
            is_active=True,
            is_email_verified=True,
        )
        user.favorite_genres.set([self.action])
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:edit_favorite_genres"),
            {"favorite_genres": [self.drama.pk]},
        )

        self.assertRedirects(response, reverse("home"))
        user.refresh_from_db()
        self.assertEqual(
            list(user.favorite_genres.values_list("pk", flat=True)),
            [self.drama.pk],
        )

    def test_edit_favorite_genres_requires_at_least_one(self):
        user = User.objects.create_user(
            email="empty@example.com",
            password="MocneHaslo123!",
            is_active=True,
            is_email_verified=True,
        )
        user.favorite_genres.set([self.action])
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:edit_favorite_genres"),
            {"favorite_genres": []},
        )

        self.assertContains(response, "Wybierz przynajmniej jeden ulubiony gatunek.")
        user.refresh_from_db()
        self.assertEqual(list(user.favorite_genres.all()), [self.action])

    def test_edit_display_name_requires_login(self):
        response = self.client.get(reverse("accounts:edit_display_name"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.headers["Location"])

    def test_edit_display_name_form_is_prefilled_for_logged_in_user(self):
        user = User.objects.create_user(
            email="display-prefill@example.com",
            password="StrongPass123!",
            is_active=True,
            is_email_verified=True,
            display_name="Stara Nazwa",
        )
        self.client.force_login(user)

        response = self.client.get(reverse("accounts:edit_display_name"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Stara Nazwa")

    def test_edit_display_name_updates_user_and_redirects_to_profile(self):
        user = User.objects.create_user(
            email="display-update@example.com",
            password="StrongPass123!",
            is_active=True,
            is_email_verified=True,
            display_name="Pierwsza Wersja",
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:edit_display_name"),
            {"display_name": "Nowa Nazwa"},
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertEqual(user.display_name, "Nowa Nazwa")

    def test_edit_display_name_strips_whitespace(self):
        user = User.objects.create_user(
            email="display-strip@example.com",
            password="StrongPass123!",
            is_active=True,
            is_email_verified=True,
        )
        self.client.force_login(user)

        self.client.post(
            reverse("accounts:edit_display_name"),
            {"display_name": "   Z Białymi Znakami   "},
        )

        user.refresh_from_db()
        self.assertEqual(user.display_name, "Z Białymi Znakami")

    def test_edit_display_name_allows_blank_to_clear(self):
        user = User.objects.create_user(
            email="display-clear@example.com",
            password="StrongPass123!",
            is_active=True,
            is_email_verified=True,
            display_name="Do Wyczyszczenia",
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:edit_display_name"),
            {"display_name": ""},
        )

        self.assertRedirects(response, reverse("accounts:profile"))
        user.refresh_from_db()
        self.assertEqual(user.display_name, "")

    def test_profile_page_links_to_display_name_edit(self):
        user = User.objects.create_user(
            email="profile-edit-link@example.com",
            password="StrongPass123!",
            is_active=True,
            is_email_verified=True,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("accounts:profile"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("accounts:edit_display_name"))

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
        self.assertRedirects(login_response, reverse("home"))
