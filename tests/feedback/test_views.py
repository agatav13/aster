from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from feedback import views as feedback_views
from feedback.models import BugReport


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(
        email="reporter@example.com",
        password="ZaqWsx!23456",
        display_name="Reporter",
        is_active=True,
        is_email_verified=True,
    )


@pytest.fixture
def auth_client(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def github_ok(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake(title: str, body: str):
        calls.append((title, body))
        return "https://github.com/example/repo/issues/42", 42

    monkeypatch.setattr(feedback_views, "create_github_issue", fake)
    return calls


@pytest.fixture
def github_fail(monkeypatch):
    def fake(title: str, body: str):
        return None

    monkeypatch.setattr(feedback_views, "create_github_issue", fake)


def _post(client: Client, **overrides) -> object:
    payload = {
        "title": "Coś nie działa",
        "description": "Po kliknięciu przycisku nic się nie dzieje.",
        "page_url": "https://example.com/page",
        "website": "",
    }
    payload.update(overrides)
    return client.post(reverse("feedback:submit"), payload)


def test_anonymous_redirected_to_login(db, client):
    response = _post(client)
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]
    assert BugReport.objects.count() == 0


def test_valid_submission_creates_report_and_github_issue(auth_client, user, github_ok):
    response = _post(auth_client)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["github_url"] == "https://github.com/example/repo/issues/42"

    report = BugReport.objects.get()
    assert report.user == user
    assert report.title == "Coś nie działa"
    assert report.page_url == "https://example.com/page"
    assert report.github_issue_url == "https://github.com/example/repo/issues/42"
    assert report.github_issue_number == 42
    assert len(github_ok) == 1
    title, body = github_ok[0]
    assert title == "Coś nie działa"
    assert "reporter@example.com" in body
    assert "https://example.com/page" in body


def test_github_failure_still_persists_report(auth_client, github_fail):
    response = _post(auth_client)
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["github_url"] is None

    report = BugReport.objects.get()
    assert report.github_issue_url == ""
    assert report.github_issue_number is None


def test_honeypot_rejects_submission(auth_client, github_ok):
    response = _post(auth_client, website="http://spam.example.com")
    assert response.status_code == 400
    data = response.json()
    assert data["ok"] is False
    assert "website" in data["errors"]
    assert BugReport.objects.count() == 0
    assert github_ok == []


def test_missing_title_returns_field_error(auth_client, github_ok):
    response = _post(auth_client, title="")
    assert response.status_code == 400
    data = response.json()
    assert data["ok"] is False
    assert "title" in data["errors"]
    assert BugReport.objects.count() == 0
    assert github_ok == []


def test_get_method_not_allowed(auth_client):
    response = auth_client.get(reverse("feedback:submit"))
    assert response.status_code == 405
