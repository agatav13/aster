#!/usr/bin/env bash
set -o errexit

uv sync --python 3.13
uv run manage.py collectstatic --noinput
uv run manage.py migrate

if [ -n "$DJANGO_SUPERUSER_EMAIL" ]; then
  uv run manage.py createsuperuser --noinput || true
fi
