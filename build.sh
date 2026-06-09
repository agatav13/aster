#!/usr/bin/env bash
set -o errexit

# --no-dev: production has no use for pytest/playwright/locust/ruff etc.
# --no-sync on the run commands so they don't re-install the dev group.
uv sync --no-dev --python 3.13
uv run --no-sync manage.py collectstatic --noinput
uv run --no-sync manage.py migrate
