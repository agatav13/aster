#!/usr/bin/env bash
# Detect the "shape" of the current change set and emit the right diff for the
# changelog / docs-sync / release skills. Solves the recurring gap where
# `git diff origin/main..HEAD` is empty because work is uncommitted or lives in
# an untracked new app (Aster is frequently edited directly on `main`).
#
# Three cases are handled:
#   1. Feature branch with commits   -> diff vs origin/main (or main)
#   2. Working-tree-only (uncommitted modifications)
#   3. Untracked new files / whole new apps (invisible to any git diff)
#
# Usage: .claude/scripts/diff-shape.sh [pathspec ...]
# With no pathspec, sensible Aster defaults are used for the stat/diff views.

set -uo pipefail

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || { echo "Not a git repository."; exit 0; }
cd "$repo_root" || exit 1

git fetch origin main --quiet 2>/dev/null || true

base=""
if git rev-parse --verify --quiet origin/main >/dev/null; then
  base="origin/main"
elif git rev-parse --verify --quiet main >/dev/null; then
  base="main"
fi

default_paths=('*.py' 'templates/**' 'static/**' 'config/**' 'pyproject.toml' 'render.yaml' 'build.sh' 'docs/**' 'README.md')
if [[ "$#" -gt 0 ]]; then
  paths=("$@")
else
  paths=("${default_paths[@]}")
fi

branch_files=""
if [[ -n "$base" ]]; then
  branch_files=$(git diff --name-only "$base"...HEAD 2>/dev/null)
fi
worktree_files=$(git diff --name-only HEAD 2>/dev/null)
untracked=$(git ls-files --others --exclude-standard 2>/dev/null)

echo "# Change-set shape"
echo

if [[ -n "$branch_files" ]]; then
  echo "## Mode 1: feature branch with commits (vs $base)"
  echo
  git --no-pager diff --stat "$base"...HEAD -- "${paths[@]}"
elif [[ -n "$worktree_files" || -n "$untracked" ]]; then
  echo "## Mode 2: working tree (uncommitted modifications)"
  echo "(no commits on this branch vs ${base:-main}; reading the working tree)"
  echo
  git --no-pager diff --stat HEAD -- "${paths[@]}"
else
  echo "No tracked changes detected vs ${base:-HEAD}."
fi

if [[ -n "$untracked" ]]; then
  echo
  echo "## Mode 3: untracked files (NOT in any diff — read these directly)"
  echo "$untracked"
  echo
  echo "For a new app dir (e.g. community/), read models.py, views.py, urls.py,"
  echo "forms.py, services.py, and templates/<app>/ to understand the surface."
fi
