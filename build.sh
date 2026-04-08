#!/usr/bin/env bash
set -o errexit

uv sync --python 3.13
uv run manage.py collectstatic --noinput
uv run manage.py migrate
