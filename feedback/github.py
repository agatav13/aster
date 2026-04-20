import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


def create_github_issue(title: str, body: str) -> tuple[str, int] | None:
    token = settings.GITHUB_TOKEN
    repo = settings.GITHUB_REPO
    if not token or not repo:
        logger.info("GitHub token or repo not configured; skipping issue creation")
        return None

    url = f"https://api.github.com/repos/{repo}/issues"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.post(
                url, headers=headers, json={"title": title, "body": body}
            )
    except httpx.HTTPError:
        logger.exception("GitHub issue creation failed (network error)")
        return None

    if response.status_code != 201:
        logger.error(
            "GitHub issue creation returned %s: %s",
            response.status_code,
            response.text[:500],
        )
        return None

    data = response.json()
    html_url = data.get("html_url", "")
    number = data.get("number")
    if not html_url or number is None:
        logger.error("GitHub response missing html_url/number: %s", data)
        return None
    return html_url, int(number)
