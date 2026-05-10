# Changelog

All notable changes to **Aster** are documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Editorial logged-out landing page** at `/` for anonymous visitors — replaces the redirect-to-login with a discovery-first landing: Fraunces serif hero ("Oglądaj. *Oceniaj*. Polecaj.") flanked by a hand-pinned five-poster fan of the top-rated titles, three numbered editorial features (`№ 01` / `№ 02` / `№ 03`), and two rails ("Najwyżej oceniane", "Co teraz oglądają"). Driven by `templates/core/landing.html` + the `.aster-*` block in `static/css/app.css`. The navbar gains anonymous **Start** and **Filmy** tabs so first-time visitors can move between the landing and the full browse without typing the URL.
- **Watched-count stat on movie detail** — the `.movie-detail-ledger` now includes an "Obejrzeli" entry counting `UserMovieStatus` rows with `status=WATCHED` for the movie, alongside the existing average-rating and your-rating cells.
- **Mirrored library / watchlist tabs on public community profiles** at `/community/u/<user_id>/` — same `Biblioteka` / `Do obejrzenia` tabbed layout as your own profile, including the `Wszystkie` / `Ocenione` / `Bez oceny` sub-filter and rating-aware sort. Read-only: no rating or status edit controls, just navigation to movie detail.
- **Community follow graph**: new `community.Follow` model (with `uq_follow_pair` unique constraint and `ck_follow_not_self` check), idempotent `POST /community/people/<user_id>/follow/` toggle, and a public read-only profile page at `/community/u/<user_id>/` showing the target's library, average rating, top genres, and top decade.
- **Friends-activity feed** rendered on the dashboard `/` and the `/community/` page via `community.services.build_feed_groups` — merges followees' `Rating` and `WATCHED` `UserMovieStatus` rows, deduplicates by `(user, movie)`, sorts newest-first, and groups under relative date headings ("Dzisiaj", "Wczoraj", "3 dni temu", …).
- **Community-top-rated rail** is now always rendered on the home dashboard beneath the watchlist rail (no longer gated on prior interaction).
- **Shared Redis cache**: `config/settings.py` switches `CACHES["default"]` to `RedisCache` when `REDIS_URL` is set, so the TMDB-response, recommendation, and personalized-shelf caches survive across Gunicorn workers and deploys. `LocMemCache` remains the dev fallback, `DummyCache` is used in tests. New env var documented in `render.yaml` and the deployment guide.
- **TMDB response cache** in `movies/tmdb.py`: every GET is keyed by `sha256(url+params)` and stored for `TMDB_RESPONSE_CACHE_TTL` seconds (default `900`).
- **htmx-driven actions on the movie detail page**: `update_movie_status`, `update_movie_rating`, `create_movie_comment`, and `delete_movie_comment` now recognise the `HX-Request` header and return the `templates/movies/_actions.html` / `_user_rating_cell.html` / `_comments_section.html` fragments instead of issuing a 302 redirect. The plain-form path is preserved as a JS-disabled fallback.
- **GZip middleware** (`django.middleware.gzip.GZipMiddleware`) added to the dynamic-response pipeline; WhiteNoise continues to serve static assets pre-compressed.
- **"Show watched" toggle** on `/movies/` plus a shelf empty-state hint shown when every entry has been filtered out by the watched filter.
- **"Bo obejrzałeś" recommendations rail** on `/movies/` (shelves mode), seeded from the user's most recently watched movie via TMDB recommendations. Walks back to the next-most-recent watch when the seed is already used by the rated-recommendations rail, so the page never renders two near-identical "Podobne do «X»" rails from the same title.
- **Hide watched titles** from the `/movies/` listing and every shelf for authenticated users. New helpers `watched_tmdb_ids` and `exclude_watched` in `movies/services.py`; computed once per request and applied to both the grid and rails. WATCHLIST entries are not affected — only WATCHED hides.

### Changed

- **Home dashboard (`/`)**: the TMDB-personalized recommendations block has been replaced with the friends-activity feed (`build_feed_groups`) — removes a TMDB round-trip from every dashboard load. Rail order leads with discovery: `community-top-rated rail → watchlist rail → friends-activity feed`.
- **Editorial typography extended across the app** — the Fraunces serif + JetBrains Mono language established on the landing page now applies to `/movies/` (mono uppercase eyebrows, italic-serif rail titles with hairline rules, search-source rendered as a `[ TMDB ]` mono tag with italic Fraunces caption, poster cards on Fraunces titles + mono uppercase year) and to the movie detail page (Fraunces display title and overview body, italic Fraunces original title, mono labels on the eyebrow / director / ledger rows, mono uppercase breadcrumb). Bootstrap-style `bi-fire` / `bi-heart` shelf icons removed in favour of the eyebrow + italic-serif title pattern.
- **Movie detail backdrop overlap** — the body grid now pulls up `140 px` into the bottom of the backdrop band so the poster overlaps the gradient fade (à la the classic editorial film page); the gradient was tightened (`transparent 25% → bg-primary 75%`) so text remains legible on the overlap.
- **`COMMUNITY_MIN_RATINGS`** raised from `1` to `2` — a single 5-star vote can no longer crown an obscure title on the "Najwyżej oceniane w Aster" rail.
- **`TMDB_REQUEST_TIMEOUT`** default lowered from `10` s to `3` s — TMDB sits on the critical render path and falling back to the local DB / empty rail is preferable to blocking the response.
- **Personalized recommendation rails are cached** per user under `PERSONALIZED_SHELF_CACHE_TTL` (15 min); credit backfill now uses row-level locking so concurrent detail-page renders cannot race the same `MovieCredit` insert.
- **Search results show watched titles by default** — the watched-hiding filter only applies to the catalogue grid and the shelves, not to the `?q=` search response.
- **Editorial flash toasts** replace the wide Bootstrap `.alert-*` strip for Django messages. Top-right corner stack, theme-tinted accent rule per tag (info / success / warning / error), auto-dismisses after ~4.5 s, manually dismissable, respects `prefers-reduced-motion`.
- **Editorial form fields** applied globally — bare Django widget inputs (and `.form-control` / `.form-select`) now share a hairline-border + accent-focus style, with autofill neutralized to the parchment palette. Bespoke pickers (`.movies-genre-select`, `.library-sort`) intentionally untouched.
- **`/movies/` filter row** reworked to a CSS grid with explicit tablet (≤ 820 px) and phone (≤ 520 px) breakpoints — submit no longer drops to a stranded second row, and fields stack full-width on phones.
- **Footer "Zgłoś problem"** GitHub-issue link is hidden for anonymous users so it only appears for members who can act on it.

### Fixed

- **Health check** (`/health/`) no longer executes `SELECT 1` against the database, so external uptime pings stop holding the managed Postgres compute awake.
- **Rating modal flash on htmx save**: stopped out-of-band swapping the rating dialog during a save in `movies/views.py`, so the modal no longer flickers or reopens after a successful rating.
- **Profile library scope and sort** (`accounts.ProfileView`): the *Biblioteka* tab is now strictly limited to movies with `UserMovieStatus.status=WATCHED` (previously also included `WATCHLIST` rows). The "ocena" sort now compares on `Rating.score` and falls back to the most recent of `Rating.updated_at` / `UserMovieStatus.updated_at`, so re-rating a movie pushes it to the top of the list as expected.

### Removed

- **`/community/lists/`** placeholder page (mock-data preview shipped in 0.1.0) is gone, together with the `community/_tabs.html` partial. Curated community lists move back to the roadmap; the new follow-driven `/community/u/<user_id>/` profile takes its place in the navigation.

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
