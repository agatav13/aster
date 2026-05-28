---
name: release
description: Prepare and execute a release for Aster. Runs tests and lint, suggests a semver version bump based on the `[Unreleased]` entries in CHANGELOG.md, promotes them to a dated section, bumps `pyproject.toml`, creates the release commit and annotated tag, and optionally pushes + cuts a GitHub release with notes. Always asks before pushing or publishing. Use this skill whenever the user says "cut a release", "publish a release", "bump the version", "tag a new version", or is otherwise ready to tag and publish. Also trigger when the user says the `[Unreleased]` section of CHANGELOG.md is ready to go out, or after a stabilization sweep when they're preparing to hand off a build.
allowed-tools: Read, Edit, Bash, Glob, Grep
---

# Release Skill

Prepare and execute a release for the **Aster** project (Django app, top-level apps in `accounts/ community/ config/ core/ feedback/ movies/`, no `src/` layout).

Aster's CHANGELOG follows Keep a Changelog 1.1.0 and the project adheres to SemVer. The `[Unreleased]` section is kept accurate per-PR by the `changelog` skill — this skill is the **promote-and-publish** step.

## Steps

Execute these steps **in order**. Stop and report if any step fails. Never push or publish without explicit user confirmation.

### 1. Pre-flight checks

Run, in this order, and confirm they pass:

```bash
uv run pytest
uv run ruff check
uv run ruff format --check
```

- **Do not proceed if any of the three fail.** Report the failures and stop. The unit/integration suite must be green; ruff lint and format are CI gates.
- Run `git status --short`. If the working tree is dirty with anything other than the files this skill is about to touch (`CHANGELOG.md`, `pyproject.toml`), **warn the user** with the list and ask whether to continue, stash, or abort.
- Confirm the current branch is `main` (or whatever release branch the user names). If on a feature branch, ask the user — they may want to merge first.

### 2. Determine the new version

- Read the current version from `pyproject.toml` (`[project] version`).
- Read the `[Unreleased]` section of `CHANGELOG.md` to understand what changed.
- Suggest a semver bump:
  - **Patch** (`0.x.Y`): bug fixes only (`### Fixed` entries dominate), small docs/test/tooling tweaks, no behavior changes for end users.
  - **Minor** (`0.X.0`): new features or new endpoints/models/management commands (`### Added` entries), additive `### Changed` entries that don't break existing flows.
  - **Major** (`X.0.0`): breaking changes — removed URLs, removed models, renamed required env vars, schema migrations that require manual data work, or anything under `### Removed` that downstream code depends on.

  Aster is pre-1.0 (`0.x.y`), so the convention "breaking changes within 0.x can bump minor instead of major" is acceptable — flag it explicitly to the user and let them decide.
- **Ask the user to confirm** the suggested version before proceeding. They may override.

### 3. Update CHANGELOG.md

- Move every entry from `[Unreleased]` into a new section header: `## [<version>] - <YYYY-MM-DD>` (use the current date in the local timezone).
- Leave the `[Unreleased]` header in place with empty `### Added`, `### Changed`, `### Fixed`, `### Removed`, `### Security` subsections **omitted** — the next entry will recreate the groups it needs.
- Preserve the existing voice exactly: past-tense English, technical and specific (named apps/views/models/URLs/management commands), one bullet per logical change. No emojis, no marketing verbs.
- If there are footer link references at the bottom of the file (`[Unreleased]: …compare/v…HEAD`, `[x.y.z]: …compare/…`), update them: the existing `[Unreleased]` link gets its base bumped to the new tag, and a new `[<version>]: …` link is added.

### 4. Bump version in pyproject.toml

- Update the `version = "..."` field in `[project]` to the new version. **Only this line changes** — do not touch dependencies, ruff config, or anything else.
- Run `uv lock` afterwards so `uv.lock`'s top-level `aster` package version is in sync. Stage `uv.lock` alongside the other files.
- **README badge:** Aster's README currently has no release badge — `License: MIT`, `CI`, `E2E`, `Security`, `Docs` only. If a future PR adds a `release-v<version>-blue` shields badge, update its URL segment here; otherwise skip this sub-step.

### 5. Create the release commit and tag

- Stage exactly these files: `CHANGELOG.md`, `pyproject.toml`, `uv.lock`. Use `git add <path>` per file — never `git add -A`.
- Commit with message: `release: v<version>` (matches Aster's conventional-commit prefixes — `release:` is treated as a `chore:`-class prefix for this purpose; do not invent a new prefix).
- Create an annotated tag: `git tag -a v<version> -m "Release v<version>"`.
- Run `git log --oneline -1` and `git tag --points-at HEAD` and report both to the user.

### 6. Push and publish GitHub release

- **Ask the user** whether to push and publish now. If they decline, skip to step 7.
- If they confirm:
  - Push commit and tag: `git push origin <release-branch> --follow-tags` (use `--follow-tags`, not `--tags`, so only the annotated release tag is pushed, not unrelated local tags).
  - Build the release notes body from the entries you moved out of `[Unreleased]` in step 3 (the new `## [<version>]` section minus the header line). Preserve the `### Added` / `### Changed` / etc. structure.
  - Confirm `gh` is available: `command -v gh`. If missing, fall back to printing the release-notes body and the manual `gh release create` command for the user to run.
  - Cut the release: `gh release create v<version> --title "v<version>" --notes "<body>"`. Pass the body via `--notes-file` (write to a temp file) if it contains shell-special characters.
  - Report the URL of the created release.
- If they decline, print the exact commands they need to run later:

  ```bash
  git push origin <release-branch> --follow-tags
  gh release create v<version> --title "v<version>" --notes-file <path>
  ```

### 7. Summary

Print:

- Previous version → new version.
- Number of changelog entries promoted (count of bullets under the new `## [<version>]` section).
- Commit hash and tag name.
- Whether the GitHub release was created (with its URL) or a reminder to push + publish manually.
- Any pre-flight warnings the user accepted (dirty working tree, non-main branch) so they're recorded in the conversation.

## What this skill does not do

- **Does not edit `[Unreleased]` content.** That's the `changelog` skill's job. If `[Unreleased]` is empty or stale, stop and tell the user to run the changelog skill first.
- **Does not bump dependencies.** A release is a snapshot, not a refresh. Dependency bumps belong in their own commits.
- **Does not deploy to Render.** Render auto-deploys on `main` push; this skill stops at GitHub. If a deployment is needed and Render is paused, surface that in the summary so the user can resume manually.
- **Does not skip hooks** (`--no-verify`) or sign with anything other than the user's configured signing key. If pre-commit fails, fix the underlying issue.
