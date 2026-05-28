---
name: changelog
description: Draft or update the `[Unreleased]` section of CHANGELOG.md for Aster based on the diff between `origin/main` and the current branch. Use this skill whenever the user says "update the changelog", "add a changelog entry", "what should go in the changelog", or whenever they are about to commit / open a PR and CHANGELOG.md hasn't been touched. Also trigger when behavior, public URLs, management commands, models, templates, documentation, or build/tooling changed — Aster's release workflow assumes `[Unreleased]` is an accurate running log of user-visible changes.
allowed-tools: Read, Edit, Bash, Glob, Grep
---

# Changelog Skill

Produce a correct, house-style entry in the `[Unreleased]` section of `CHANGELOG.md` for the work currently on the branch. The project follows Keep a Changelog 1.1.0 + SemVer. When release time comes, `[Unreleased]` gets promoted to a dated `## [x.y.z]` section — so keeping it accurate every PR avoids release-day archaeology.

## Why this exists

The CHANGELOG is Aster's single source of truth for user-visible history (the Polish `docs/maintenance/changelog.md` page just describes conventions and links here). Writing entries from the diff — while the work is fresh — is more accurate than reconstructing them later from commit messages, and it catches the classification errors ("this is really a `Changed`, not an `Added`") that are hard to notice in hindsight.

## Voice and format

Aster's CHANGELOG is in **English** (even though the app UI and `docs/` are in Polish). Study the existing file before writing — match its tone. Good entries look like:

- Past-tense, result-first verbs ("Added…", "Moved…", "Replaced…", "Switched…").
- Technical and specific — name the Django app, view, model, URL, management command, or setting.
- One bullet per logical change, not one bullet per commit. Squash related commits into a single entry.
- Grouped under `### Added`, `### Changed`, `### Fixed`, `### Removed`, `### Security`. Omit groups with no entries.
- No emojis, no marketing language, no vague verbs ("improved", "enhanced").

### Classification rules

Lean on Aster's conventional-commit prefixes as a starting hint, then verify against the actual diff:

| Prefix | Usually becomes | Notes |
|---|---|---|
| `feat:` | **Added** | New user-visible feature, new URL, new template, new management command |
| `fix:` | **Fixed** | Only list if the bug was in a released version. Fixes to code that never shipped are invisible and don't belong. |
| `refactor:`, `perf:` | **Changed** | Only if observable behavior, response shape, or performance characteristics changed. Pure internal refactors are skipped. |
| UI/styling rework (large CSS/template change, **same** URLs and context keys) | **Changed** | A visible layout/visual overhaul with no routing or data change. Example: `Reworked templates/core/dashboard.html into an editorial shelves layout; no URL or context-key changes.` |
| `chore(deps):` | **Changed** | Only if the bump is user-visible (major framework upgrade, security-relevant). Routine dependency bumps are usually skipped. |
| `docs:`, `test:`, `ci:`, `build:`, plain `chore:` | *skipped* | Not user-facing. |
| `!` suffix or `BREAKING CHANGE:` footer | flag at top with ⚠️ | Surface prominently so the release skill can decide on MAJOR bump. |

The prefix is a hint, not a rule. A commit titled `refactor:` that actually changes a URL pattern is a `Changed` entry; a `feat:` that adds an internal helper nobody sees gets dropped.

**Stubbed / mocked features.** If a feature ships user-visible URLs, templates, or nav but is backed by mock data or placeholder models (e.g. `community/` with `mock.py` and no models yet), list it now — the surface is real — and note the stub status in the bullet itself (`…backed by mock data until the schema lands`). This mirrors the honesty rule in the `docs-sync` skill.

## Steps

### 1. Gather the diff

Start by detecting the change-set shape — Aster is frequently edited directly on `main`, so the work is often uncommitted or in an untracked new app, where `git diff origin/main..HEAD` returns nothing:

```bash
.claude/scripts/diff-shape.sh
```

This prints which of the three modes applies and the right stat view. If the script isn't present, run the commands for your mode by hand:

1. **Feature branch with commits** (default):
   ```bash
   git fetch origin main --quiet 2>/dev/null || true
   git log --oneline origin/main..HEAD
   git diff --stat origin/main...HEAD
   ```
   If `origin/main` isn't available, fall back to local `main`.
2. **Working-tree-only** (modifications not yet committed):
   ```bash
   git status
   git diff --stat HEAD
   ```
3. **Untracked new files or whole new apps** — these appear in *no* diff. List and read them directly:
   ```bash
   git ls-files --others --exclude-standard
   ```
   For a new app like `community/`, read `models.py`, `views.py`, `urls.py`, `forms.py`, and the templates under `templates/<app>/` to understand the surface.

Use the stat to prioritize which files to actually read in full.

Almost always changelog-worthy when touched:
- `accounts/`, `movies/`, `core/`, `community/`, `feedback/` — app code (models, views, forms, urls, services, templates)
- `templates/**` — user-visible UI
- `static/**` — user-visible styles/scripts
- `config/urls.py`, `config/settings.py` — when the change affects runtime behavior
- `movies/management/commands/*.py` — management command surface
- `docs/**`, `README.md` — documented contracts
- `pyproject.toml` — user-visible dependency/Python-version changes
- `render.yaml`, `build.sh` — deployment behavior

Usually **not** changelog-worthy:
- `tests/`, `*/tests.py` — test-only changes
- `.github/`, `.claude/`, `.pre-commit-config.yaml`, `mkdocs.yml` (unless the site URL or nav contract visibly changes)
- Migrations that are purely mechanical (generated alongside a model change that IS listed — the model change is the entry, not the migration file)

### 2. Read the existing `[Unreleased]` section

Read `CHANGELOG.md` and note:
- What's already under `[Unreleased]` (to avoid duplicates and match phrasing).
- The `### Planned` subsection — don't touch it; the user maintains that list manually.
- The most recent dated section (e.g. `## [0.1.0]`) as a style reference.

### 3. Classify the changes

For each logical change in the diff, decide:
- Is it user-visible? If no, drop it.
- Which group does it belong to (see the classification table above)?
- Is it already covered by an existing `[Unreleased]` bullet? If yes, refine the wording rather than duplicate.
- Does it cross the MAJOR-bump threshold (breaking URL, removed endpoint, removed CLI flag, schema change requiring manual migration)? Flag it.

### 4. Write the entries

Draft bullets in the project's voice. Mention concrete Aster identifiers:

- Django apps (`accounts`, `movies`, `core`, `community`, `feedback`)
- View classes (`RegisterView`, `MovieListView`) and function views (`update_movie_rating`)
- URL paths (`/movies/<tmdb_id>/rating/`, `/auth/activate/`)
- Models and fields (`Movie.average_rating`, `UserMovieStatus`, `Comment.toxicity_score`)
- Management commands (`sync_tmdb_popular`, `normalize_genres`)
- Settings (`TMDB_LANGUAGE`, `PASSWORD_RESET_TIMEOUT`)
- Templates (`templates/movies/list.html`)

**Example style (match this level of specificity):**

- `Added a floating bug-report widget (templates/base.html) that forwards to GitHub Issues via a query-string prefill.`
- `Switched the movie list genre filter to a multi-select, persisted through the querystring, and updated templates/movies/list.html accordingly.`
- `Replaced per-signal rating aggregate updates with an explicit _refresh_movie_aggregates call in movies/services.py; aggregates now refresh inside the same transaction as the rating write.`
- `Fixed activation email links pointing at http://localhost in production by reading APP_BASE_URL from the environment.`

### 5. Update the file

Use `Edit` to insert or merge bullets into `[Unreleased]`. Keep groups in canonical order: `Added` → `Changed` → `Fixed` → `Removed` → `Security`. Preserve the `### Planned` subsection untouched.

Do **not**:
- Touch any dated `## [x.y.z]` section.
- Create a new version section or bump the version in `pyproject.toml` — that's the release workflow's job.
- Stage or commit — leave that to the user.

### 6. Summarize back

Print a short report:
- Bullets added / modified per group.
- What you explicitly **did not** include (test-only changes, internal refactors) so the user can disagree.
- Any judgment calls, with your choice and the alternative.
- Any ⚠️ breaking-change flags requiring release-time attention.

## What not to do

- Don't invent entries for changes you can't see in the diff. If the diff is empty or trivial, say so and stop.
- Don't mirror entries into `docs/maintenance/changelog.md` — that file intentionally points back here.
- Don't move or rewrite bullets from past released versions.
- Don't use emojis (except the ⚠️ breaking-change marker), marketing language, or vague verbs.
- Don't narrate refactors that left the observable surface identical — those aren't changelog material.
