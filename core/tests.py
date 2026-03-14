from django.test import TestCase
from django.urls import reverse


class CoreViewTests(TestCase):
    def test_home_page_renders(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Zaloguj się")
        self.assertContains(response, "Zarejestruj się")

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("dashboard"))
        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('dashboard')}",
        )

