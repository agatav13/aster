# Aster — Movie Recommendation App

[![CI](https://github.com/agatav13/aster/actions/workflows/test.yml/badge.svg)](https://github.com/agatav13/aster/actions/workflows/test.yml)
[![E2E](https://github.com/agatav13/aster/actions/workflows/e2e.yml/badge.svg)](https://github.com/agatav13/aster/actions/workflows/e2e.yml)
[![Security](https://github.com/agatav13/aster/actions/workflows/security.yml/badge.svg)](https://github.com/agatav13/aster/actions/workflows/security.yml)
[![Docs](https://github.com/agatav13/aster/actions/workflows/docs.yml/badge.svg)](https://agatav13.github.io/aster/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A Django-based web application for browsing, rating, and tracking movies, with data sourced from TMDB.

🌐 **Live app:** <https://aster-1lf7.onrender.com/>

📖 **Documentation:** <https://agatav13.github.io/aster/>

## Tech Stack

- **Backend:** Django 5.2.13, Gunicorn, Python 3.13
- **Database:** SQLite (development), PostgreSQL (production)
- **External APIs:** TMDB v3 (catalog), Brevo / Gmail SMTP (email)
- **Static files:** WhiteNoise
- **Deployment:** Render.com
- **Package manager:** uv
- **Testing:** pytest, pytest-django, pytest-playwright, locust, bandit, pip-audit, pa11y
- **Docs:** MkDocs Material → GitHub Pages

## Documentation

The full project documentation lives at <https://agatav13.github.io/aster/> and covers:

- Functional and non-functional requirements
- UX/UI: sitemap, user journeys, wireframes (lo-fi + hi-fi)
- Architecture: system diagrams, ERD, API integrations, tech stack rationale
- Implementation: key modules, design patterns, deployment guide
- Testing: strategy and reproducible reports for unit/E2E/perf/security/a11y
- Maintenance: admin and user guides, changelog

The docs source lives in `docs/` (markdown). Build locally with `uv run mkdocs serve`.

## Quick Start

1. Clone and create `.env`:

```bash
DJANGO_SECRET_KEY=dev-secret-change-me
TMDB_API_KEY=your-tmdb-v3-key
```

2. Install dependencies:

```bash
uv sync --group dev
```

3. Run database migrations:

```bash
uv run manage.py migrate
```

4. Start the development server:

```bash
uv run manage.py runserver
```

5. Open <http://127.0.0.1:8000/>.

For full deployment instructions, env vars, and Render configuration, see
[docs → Deployment](https://agatav13.github.io/aster/implementation/deployment/).

## Useful Commands

```bash
# Run unit + integration tests with coverage
uv run pytest --cov

# Run E2E tests (requires Chromium)
uv run playwright install chromium
DJANGO_ALLOW_ASYNC_UNSAFE=true uv run pytest tests/e2e -m e2e

# Security checks
uv run bandit -r accounts core movies config -ll
uv run pip-audit
uv run manage.py check --deploy

# Build docs locally
uv run --group docs mkdocs serve
```

## Attribution

This product uses the TMDB API but is not endorsed or certified by TMDB.
Movie metadata and artwork are provided by [The Movie Database (TMDB)](https://www.themoviedb.org/).

## License

[MIT](LICENSE) © Agata Omasta
