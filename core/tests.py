from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


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
