"""E2E journey 1: registration → email verification → login → dashboard.

Covers user-journey 1 from docs/ux/user-journeys.md.
"""

from __future__ import annotations

import re

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from playwright.sync_api import Page, expect


@pytest.mark.django_db(transaction=True)
def test_register_activate_login(page: Page, live_server, genres, clear_outbox) -> None:
    base = live_server.url
    email = "new-e2e@example.com"
    password = "BezpieczneHaslo!23"

    page.goto(f"{base}/auth/register/")
    page.get_by_label("Adres e-mail").fill(email)
    page.get_by_label(re.compile(r"Nick lub imię", re.I)).fill("Nowy Użytkownik")
    page.get_by_label("Hasło", exact=False).first.fill(password)
    page.get_by_label(re.compile(r"Potwierdzenie hasła|Powtórz hasło", re.I)).fill(
        password
    )
    page.locator(f"input[name='favorite_genres'][value='{genres[0].pk}']").check(
        force=True
    )
    page.get_by_role("button", name=re.compile(r"Utwórz konto", re.I)).click()

    expect(page).to_have_url(re.compile(r"/auth/activation-sent/"))

    assert len(mail.outbox) == 1, "Activation email should be sent"
    activation_path = _extract_activation_path(mail.outbox[0].body)
    assert activation_path, "Activation link missing in email body"

    page.goto(f"{base}{activation_path}")
    expect(page.get_by_text(re.compile(r"aktywowane|aktywne", re.I))).to_be_visible()

    User = get_user_model()
    user = User.objects.get(email=email)
    assert user.is_active is True
    assert user.is_email_verified is True

    page.goto(f"{base}/auth/login/")
    page.get_by_label("Adres e-mail").fill(email)
    page.get_by_label("Hasło").fill(password)
    page.get_by_role("button", name=re.compile(r"Zaloguj", re.I)).click()

    page.wait_for_url(re.compile(r"/$"))
    expect(page.get_by_text(re.compile(r"Zalogowano", re.I))).to_be_visible()


def _extract_activation_path(body: str) -> str | None:
    match = re.search(r"/auth/activate/[^/]+/[^/\s]+/?", body)
    return match.group(0) if match else None
