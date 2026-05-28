---
name: docs-sync
description: After a behavior, URL, model, template, management-command, deployment, or dependency change in Aster, propose coordinated edits to README.md and the MkDocs pages under docs/ so the documentation stays in sync with the code. Use this skill whenever the user says "update the docs", "docs sync", "do the docs match", "what docs need to change", or whenever they finish a change that touches app code, routing, models, or deployment. Aster's docs encode implementation detail (ERDs, URL tables, management-command lists, module layout), so drift is fast and silent — this skill makes the update a single coordinated pass instead of piecemeal edits spread across files.
allowed-tools: Read, Edit, Bash, Glob, Grep
---

# Docs Sync Skill

Keep `README.md` and `docs/` consistent with the code whenever Aster's behavior, URLs, models, templates, management commands, deployment pipeline, or dependencies change. Aster's docs are unusually code-coupled (Mermaid ERDs that list every model field; URL tables with form payloads; per-app module descriptions with class names) — those decay fast without discipline. One coordinated pass per PR is much cheaper than a pre-release audit that finds three-month-old drift.

## Language

Aster's documentation is split between English and Polish — **always match the language of the file you're editing**:

- **English:** `README.md`, `CHANGELOG.md` (but see below — not in scope here).
- **Polish:** everything under `docs/`. Tone is formal, technical, terse. Uses bolded Polish terms, `mermaid` diagrams with Polish labels, code blocks with Polish comments, and explains *why* decisions were made (e.g. `Świadoma decyzja: signals są niewidoczne i utrudniają testowanie`). Read neighboring paragraphs before writing — don't machine-translate from English drafts.

If you're unsure how to phrase a Polish technical sentence, find a similar sentence in the surrounding docs and mirror its structure. Ask the user rather than guess when the phrasing is load-bearing (e.g. a requirement, a security claim, a user-guide step).

**Register varies across `docs/`.** Not all Polish pages share one voice: `architecture/` and `implementation/` are densely technical (class names, decisions, mermaid), while `maintenance/user-guide.md` and `maintenance/admin-guide.md` are written for end users / operators in a plainer register. Read the neighboring paragraphs of the *specific* file you're editing to calibrate — don't carry the `modules.md` voice into `user-guide.md`.

## Scope of documentation

The documentation surface for Aster:

- `README.md` — project overview, tech stack, quick start, deployment notes (English).
- `docs/index.md` — site landing page.
- `docs/requirements/functional.md`, `docs/requirements/non-functional.md` — functional + non-functional requirements.
- `docs/ux/sitemap.md`, `docs/ux/user-journeys.md` — URL map + user flows.
- `docs/architecture/system.md` — high-level system diagram and layer split.
- `docs/architecture/database.md` — ERD (mermaid) + model/field listing.
- `docs/architecture/apis.md` — external URLs exposed, plus TMDB + email integrations.
- `docs/architecture/tech-stack.md` — framework + library + Python version.
- `docs/implementation/modules.md` — walk-through of key modules, patterns, and decisions.
- `docs/implementation/deployment.md` — Render deployment, `build.sh`, env vars.
- `docs/testing/strategy.md`, `docs/testing/reports.md` — test layers and reproducible reports.
- `docs/maintenance/admin-guide.md`, `docs/maintenance/user-guide.md` — operational/end-user guides.
- `docs/maintenance/changelog.md` — **conventions page only**; don't mirror entries here, it intentionally links to the root `CHANGELOG.md`.
- `mkdocs.yml` — site config + `nav:` tree. Touch only when a new page is added or a page is renamed.

**Out of scope:**
- `CHANGELOG.md` — handled by the `changelog` skill.
- `site/` — generated output, never hand-edit.
- `htmlcov/` — coverage report artifacts.

## Change → docs mapping

Walk the diff and decide which doc files each change touches. Use this mapping — it's Aster-specific and reflects where information actually lives today:

| Change in code                                                      | Likely docs to update                                                |
|--------------------------------------------------------------------|----------------------------------------------------------------------|
| Model added / field added / field renamed in `*/models.py`          | `docs/architecture/database.md` (ERD + field list), possibly `modules.md` if the model is central |
| New Django app or app added to `INSTALLED_APPS`                     | `docs/implementation/modules.md` (project tree), possibly `system.md`; if the app exposes URLs, also `docs/architecture/apis.md` and `docs/ux/sitemap.md` |
| URL added / renamed / removed in `*/urls.py`                        | `docs/architecture/apis.md` (endpoint tables), `docs/ux/sitemap.md`  |
| New / changed public helper in `*/services.py`                      | `docs/implementation/modules.md` (§4 Service layer documents these by name) |
| View class / function added or renamed                              | `docs/implementation/modules.md` if the view is referenced there by name |
| View *semantics* changed (same URL, different content/purpose — e.g. `HomeView` dashboard → editorial shelves) | `docs/implementation/modules.md` **and** `docs/maintenance/user-guide.md` + `docs/ux/sitemap.md` (what the page now does, not just that it exists) |
| New / changed template under `templates/`                           | `docs/maintenance/user-guide.md` or `admin-guide.md` if the screen is described there |
| Change to `movies/tmdb.py` (TMDB client)                            | `docs/architecture/apis.md` (TMDB integration section)               |
| Email backend / Brevo config change                                 | `docs/architecture/apis.md` (email integration)                      |
| New / changed management command in `*/management/commands/`        | `docs/maintenance/admin-guide.md` (operations), `docs/implementation/modules.md` if it's part of a documented flow |
| Change to `render.yaml`, `build.sh`, or deploy env vars             | `docs/implementation/deployment.md`                                  |
| `pyproject.toml` dependency or Python version change                | `docs/architecture/tech-stack.md`, `README.md` tech-stack list       |
| Change to test tooling, pytest config, coverage targets             | `docs/testing/strategy.md`, `docs/testing/reports.md` if numbers changed |
| New / removed functional requirement                                | `docs/requirements/functional.md`                                    |
| New / changed non-functional target (performance, a11y, security)   | `docs/requirements/non-functional.md`                                |
| New doc page                                                        | add to `mkdocs.yml` `nav:` in the right section (Polish label)       |

If a code change doesn't map to any row above, it probably doesn't need a docs edit. That's fine — say so in the summary.

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
   git diff --stat origin/main...HEAD
   git diff origin/main...HEAD -- '*.py' 'templates/**' 'static/**' 'pyproject.toml' 'render.yaml' 'build.sh'
   ```
2. **Working-tree-only** (modifications not yet committed):
   ```bash
   git status
   git diff HEAD -- '*.py' 'templates/**' 'static/**' 'config/**' 'pyproject.toml' 'render.yaml' 'build.sh'
   ```
3. **Untracked new files or whole new apps** — these appear in *no* diff. List and read them directly:
   ```bash
   git ls-files --others --exclude-standard
   ```
   For a new app like `community/`, read `models.py`, `views.py`, `urls.py`, `forms.py`, `services.py`, and the templates under `templates/<app>/` to understand the surface.

Read the full diff for anything in `accounts/`, `movies/`, `core/`, `community/`, `feedback/`, `config/`, or `templates/` — these are the directories most tightly coupled to the docs.

### 2. Read the current docs state

Before editing, read every doc file that appears in the mapping rows triggered by the diff. Don't guess contents — the existing phrasing and structure must be preserved. Pay particular attention to:

- The ERD block in `docs/architecture/database.md` (mermaid syntax, field ordering).
- The endpoint tables in `docs/architecture/apis.md` (column order: field / type / values / description).
- The project tree in `docs/implementation/modules.md` (list of apps).
- Cross-references — supported-format-style lists and identifier lists sometimes appear in multiple places; when they change, update **every** occurrence in the same pass. Missing one is the most common bug this skill prevents.

### 3. Build a change matrix

For each meaningful code change, enumerate: which doc files are affected, what specifically needs to change in each, and whether the change is additive (new section/bullet/row) or corrective (existing text is now wrong).

If the scope is large (>3 files or >10 total edits), present the matrix to the user **before editing** so they can approve in one message. For small scopes, proceed directly to editing.

### 4. Make the edits

Use `Edit` to apply each change. Preserve style:

- **Polish under `docs/`**: match the voice of the surrounding paragraphs. Keep Polish column headers in tables (`Pole`, `Typ`, `Wartości`, `Opis`). Keep Polish labels inside mermaid diagrams (`wystawia`, `komentowany`, `klasyfikacja`).
- **English in `README.md`**: keep the existing section order and the shields badge lines untouched unless the change is specifically about one of them.
- **Code examples**: runnable under `uv run` (e.g. `uv run manage.py sync_tmdb_popular --pages 5`, not `python manage.py ...`).
- **Cross-consistency**: if the supported-genre list, URL list, or management-command list appears in more than one doc, update them together.
- **Honesty**: if the diff introduces a half-finished feature (model fields prepared but admin UI not wired), reflect that honestly instead of pretending it's complete. House style is explicit about gaps (e.g. `Schemat gotowy, widok publiczny już teraz filtruje na status='visible'`).

### 5. Verify the docs still build

Run:

```bash
uv run mkdocs build --strict
```

`--strict` is what the `docs` GitHub Actions workflow uses. If it fails, fix the reported issue (broken internal link, page missing from `nav:`, malformed mermaid, unresolved reference) before reporting done.

If `mkdocs` isn't installed in the environment or the build is too slow for the current iteration, say so explicitly in the summary rather than skipping silently.

### 6. Summarize

Report:
- Files edited, with a one-line reason each.
- Anything deliberately **not** touched (e.g. `docs/testing/strategy.md` — no test-tooling changes in the diff) so the user can disagree.
- Whether `mkdocs build --strict` passed.
- Any judgment calls resolved (phrasing choices, where to place a new section), so the user can overrule.

## What not to do

- Don't edit `CHANGELOG.md` — that's the `changelog` skill.
- Don't stage or commit anything. Leave that to the user.
- Don't rewrite sections that aren't affected by the diff. This skill is surgical, not a general editorial pass.
- Don't machine-translate English drafts into Polish `docs/` pages — read the surrounding text and match its voice.
- Don't duplicate changelog-style history into `docs/maintenance/changelog.md`. That file describes conventions and links to the root file.
- Don't hand-edit anything under `site/` — it's generated by mkdocs.
- Don't invent features. If a feature is half-wired, say so.
- Don't add emojis or marketing language to match neighboring files' tone.
