# Aster — Movie Recommendation App

[![CI](https://github.com/agatav13/aster/actions/workflows/test.yml/badge.svg)](https://github.com/agatav13/aster/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Django-based web application for discovering, rating, and managing movies with personalized recommendations.

## Features

- **User authentication** — registration with email verification, login, password reset
- **Genre preferences** — select favorite genres during registration
- **User dashboard** — personalized view with account info and preferences
- **Movie catalog** — browse, search, and filter movies sourced from TMDB
- **Admin panel** — Django admin for managing users, genres, and movies

## Tech Stack

- **Backend:** Django 5.2, Gunicorn
- **Database:** SQLite (development), PostgreSQL (production)
- **Email:** Gmail SMTP / Brevo API (via django-anymail)
- **Static files:** WhiteNoise
- **Deployment:** Render.com
- **Package manager:** uv

## Requirements

- Python 3.13
- uv

## Getting Started

1. Clone the repository and create a `.env` file at the project root with at minimum:

```bash
DJANGO_SECRET_KEY=dev-secret-change-me
TMDB_API_KEY=your-tmdb-v3-key
```

2. Install dependencies:

```bash
uv sync --python 3.13
```

3. Run database migrations:

```bash
uv run manage.py migrate
```

4. Start the development server:

```bash
uv run manage.py runserver
```

5. Open http://127.0.0.1:8000/

## Configuration

Key environment variables:

| Variable | Description |
|---|---|
| `DJANGO_SECRET_KEY` | Django secret key |
| `DJANGO_DEBUG` | `True` for development, `False` for production |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated allowed hosts |
| `DJANGO_ADMIN_URL` | Admin URL path (defaults to `admin/`) |
| `DATABASE_URL` | PostgreSQL connection string (defaults to SQLite if unset) |
| `EMAIL_HOST_USER` | SMTP email address |
| `EMAIL_HOST_PASSWORD` | SMTP password / app password |
| `BREVO_API_KEY` | Brevo API key (alternative to SMTP) |
| `DEFAULT_FROM_EMAIL` | Sender address for outgoing emails |
| `APP_BASE_URL` | Base URL for activation links |
| `TMDB_API_KEY` | TMDB v3 API key (required to populate the movie catalog) |
| `TMDB_API_BASE_URL` | TMDB API base, defaults to `https://api.themoviedb.org/3` |
| `TMDB_IMAGE_BASE_URL` | Poster CDN base, defaults to `https://image.tmdb.org/t/p/w500` |

## Useful Commands

```bash
# Run tests
uv run pytest

# Create superuser
uv run manage.py createsuperuser

# Generate migrations after model changes
uv run manage.py makemigrations

# Collect static files for production
uv run manage.py collectstatic --noinput

# Sync the genre dictionary from TMDB (run once)
uv run manage.py sync_tmdb_genres

# Pull popular movies from TMDB (1 page = 20 movies)
uv run manage.py sync_tmdb_popular --pages 3
```

## Project Structure

```
config/          # Django settings, root URL config, WSGI/ASGI
accounts/        # Authentication app (models, views, forms, utils)
core/            # Home page and dashboard
movies/          # Movie catalog, ratings, comments, TMDB integration
templates/       # HTML templates (base, auth, email, partials)
static/          # CSS and static assets
docs/            # Project documentation and mockups
build.sh         # Render.com build script
render.yaml      # Render.com deployment config
```

## Deployment

The project deploys to Render.com. The `build.sh` script handles dependency installation, static file collection, and database migrations.

## Attribution

This product uses the TMDB API but is not endorsed or certified by TMDB. Movie metadata and artwork are provided by [The Movie Database (TMDB)](https://www.themoviedb.org/).

## License

[MIT](LICENSE) © Agata Omasta
