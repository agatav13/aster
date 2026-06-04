#!/usr/bin/env bash
# Stop hook: block end-of-turn if a docs-encoded surface changed without a
# matching README.md / docs/ / mkdocs.yml update. Aster's docs hard-code
# implementation detail (ERDs from models, URL tables, management-command
# lists, deployment), so those surfaces drift silently otherwise.
# Compares the working tree against upstream (or origin/main / main as
# fallback), so committed-but-not-pushed changes are counted too. Opt out
# with SKIP_DOCS_CHECK=1.

set -uo pipefail

if [[ "${SKIP_DOCS_CHECK:-0}" == "1" ]]; then
  exit 0
fi

repo_root=$(git rev-parse --show-toplevel 2>/dev/null) || exit 0
cd "$repo_root"

base=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)
if [[ -z "${base:-}" ]]; then
  if git rev-parse --verify origin/main >/dev/null 2>&1; then
    base="origin/main"
  elif git rev-parse --verify main >/dev/null 2>&1; then
    base="main"
  else
    exit 0
  fi
fi

changed=$( {
  git diff --name-only "$base" -- 2>/dev/null
  git ls-files --others --exclude-standard 2>/dev/null
} | sort -u | grep -v '^$' || true )

[[ -z "$changed" ]] && exit 0

# A docs-encoded surface changed: models (ERDs), migrations (schema),
# urls (URL tables), management commands (command lists), settings /
# render.yaml / build.sh (deployment), pyproject.toml / uv.lock (deps).
docs_relevant=0
while IFS= read -r f; do
  case "$f" in
    */models.py|*/migrations/*.py|*/urls.py|*/management/commands/*.py|\
    config/settings.py|render.yaml|build.sh|pyproject.toml|uv.lock)
      docs_relevant=1
      break
      ;;
  esac
done <<< "$changed"

[[ "$docs_relevant" == "0" ]] && exit 0

# Satisfied by any edit to the docs surface itself.
if grep -qE '^(README\.md|mkdocs\.yml|docs/)' <<< "$changed"; then
  exit 0
fi

cat <<'JSON'
{"decision": "block", "reason": "A docs-encoded surface changed on this branch (vs upstream/origin/main) without a corresponding docs update: a models.py, migration, urls.py, management command, config/settings.py, render.yaml, build.sh, pyproject.toml, or uv.lock changed, but README.md, docs/, and mkdocs.yml are untouched. Aster's docs hard-code ERDs, URL tables, management-command lists, and deployment detail, so these drift silently. Reconcile the docs — invoke the docs-sync skill (/docs-sync) or edit README.md / docs/ directly — then stop. To bypass for this turn, run with SKIP_DOCS_CHECK=1."}
JSON
