from __future__ import annotations

import httpx
import pytest

from feedback import github


def test_returns_none_when_token_missing(settings):
    settings.GITHUB_TOKEN = ""
    settings.GITHUB_REPO = "owner/repo"
    assert github.create_github_issue("t", "b") is None


def test_returns_none_when_repo_missing(settings):
    settings.GITHUB_TOKEN = "x"
    settings.GITHUB_REPO = ""
    assert github.create_github_issue("t", "b") is None


class _Response:
    def __init__(self, status_code: int, json_data: dict):
        self.status_code = status_code
        self._json_data = json_data
        self.text = str(json_data)

    def json(self) -> dict:
        return self._json_data


class _Client:
    def __init__(self, response: _Response | Exception):
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, headers, json):
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def test_success_returns_url_and_number(settings, monkeypatch):
    settings.GITHUB_TOKEN = "tok"
    settings.GITHUB_REPO = "owner/repo"
    resp = _Response(201, {"html_url": "https://github.com/o/r/issues/7", "number": 7})
    monkeypatch.setattr(github.httpx, "Client", lambda timeout: _Client(resp))
    result = github.create_github_issue("t", "b")
    assert result == ("https://github.com/o/r/issues/7", 7)


def test_non_201_returns_none(settings, monkeypatch):
    settings.GITHUB_TOKEN = "tok"
    settings.GITHUB_REPO = "owner/repo"
    resp = _Response(500, {"message": "boom"})
    monkeypatch.setattr(github.httpx, "Client", lambda timeout: _Client(resp))
    assert github.create_github_issue("t", "b") is None


def test_network_error_returns_none(settings, monkeypatch):
    settings.GITHUB_TOKEN = "tok"
    settings.GITHUB_REPO = "owner/repo"
    monkeypatch.setattr(
        github.httpx,
        "Client",
        lambda timeout: _Client(httpx.ConnectError("nope")),
    )
    assert github.create_github_issue("t", "b") is None


@pytest.mark.parametrize("data", [{}, {"html_url": "x"}, {"number": 1}])
def test_malformed_response_returns_none(settings, monkeypatch, data):
    settings.GITHUB_TOKEN = "tok"
    settings.GITHUB_REPO = "owner/repo"
    monkeypatch.setattr(
        github.httpx, "Client", lambda timeout: _Client(_Response(201, data))
    )
    assert github.create_github_issue("t", "b") is None
