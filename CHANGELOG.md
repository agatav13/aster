# Changelog

All notable changes to **Aster** are documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **"Bo obejrzałeś" recommendations rail** on `/movies/` (shelves mode), seeded from the user's most recently watched movie via TMDB recommendations. Walks back to the next-most-recent watch when the seed is already used by the rated-recommendations rail, so the page never renders two near-identical "Podobne do «X»" rails from the same title.
- **Hide watched titles** from the `/movies/` listing and every shelf for authenticated users. New helpers `watched_tmdb_ids` and `exclude_watched` in `movies/services.py`; computed once per request and applied to both the grid and rails. WATCHLIST entries are not affected — only WATCHED hides.

### Changed

- **Editorial flash toasts** replace the wide Bootstrap `.alert-*` strip for Django messages. Top-right corner stack, theme-tinted accent rule per tag (info / success / warning / error), auto-dismisses after ~4.5 s, manually dismissable, respects `prefers-reduced-motion`.
- **Editorial form fields** applied globally — bare Django widget inputs (and `.form-control` / `.form-select`) now share a hairline-border + accent-focus style, with autofill neutralized to the parchment palette. Bespoke pickers (`.movies-genre-select`, `.library-sort`) intentionally untouched.
- **`/movies/` filter row** reworked to a CSS grid with explicit tablet (≤ 820 px) and phone (≤ 520 px) breakpoints — submit no longer drops to a stranded second row, and fields stack full-width on phones.
- **Footer "Zgłoś problem"** GitHub-issue link is hidden for anonymous users so it only appears for members who can act on it.

### Planned

- Personalized recommendations based on `favorite_genres`, ratings, and watch history.
- Automated comment moderation (toxicity score, moderator actions in admin panel).
- Rate limiting on `/auth/login/` and `/auth/register/`.
- Manual accessibility audit + screen-reader testing.
- E2E tests for password reset and admin flows.

## [0.1.0] — 2026-04-18

First public release of the documentation and the supporting test suites.

### Added

- **User accounts**: registration with email verification, login/logout, password reset, profile editing (display name, favorite genres).
- **Movie catalog** sourced from TMDB (popular, search by title, genre filter, "favorites only" filter).
- **Movie detail page** with overview, poster, genres, cast and director credits.
- **Half-star ratings** (0.5–5.0) with cached aggregates on the `Movie` row.
- **Comments** (post, delete own) with model fields prepared for moderation (`toxicity_score`, `flagged`/`hidden` statuses).
- **Watchlist / Watched lists** modelled as a single `UserMovieStatus` row that flips state.
- **Django admin panel** for users, genres, movies, comments.
- **Management commands**: `sync_tmdb_genres`, `sync_tmdb_popular`, `backfill_credits`, `normalize_genres`.
- **Tests**:
    - 135 unit/integration tests (pytest, pytest-django) with ~83% line coverage.
    - 3 E2E tests (Playwright) covering the three main user journeys.
    - locust performance script (`tests/perf/locustfile.py`).
- **Security automation**: bandit, pip-audit, `manage.py check --deploy` running on every PR (`.github/workflows/security.yml`).
- **Accessibility audit** with pa11y (WCAG2AA) on four key pages — zero issues.
- **CI/CD**: four GitHub Actions workflows (`test`, `e2e`, `security`, `docs`).
- **Documentation site** (this site) — MkDocs Material, hosted on GitHub Pages.

### Changed

- Bump Django from 5.2.12 → 5.2.13 to remediate 5 CVEs surfaced by `pip-audit`.
- Production hardening in `config/settings.py` activated when `DEBUG=False`: `SECURE_SSL_REDIRECT`, HSTS (1 year, include subdomains, preload), secure cookies, `X_FRAME_OPTIONS=DENY`, `SECURE_REFERRER_POLICY=same-origin`, `SECURE_CONTENT_TYPE_NOSNIFF`.

[Unreleased]: https://github.com/agatav13/aster/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/agatav13/aster/releases/tag/v0.1.0
