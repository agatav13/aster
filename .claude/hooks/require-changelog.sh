#!/usr/bin/env bash
# Stop hook: block end-of-turn if app code changed without a CHANGELOG.md entry.
# Compares the working tree against upstream (or origin/main / main as fallback),
# so committed-but-not-pushed changes are counted too. Opt out with
# SKIP_CHANGELOG_CHECK=1.

set -uo pipefail

if [[ "${SKIP_CHANGELOG_CHECK:-0}" == "1" ]]; then
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

app_changed=0
while IFS= read -r f; do
  case "$f" in
    accounts/*|movies/*|core/*|community/*|feedback/*|config/*|templates/*)
      app_changed=1
      break
      ;;
  esac
done <<< "$changed"

[[ "$app_changed" == "0" ]] && exit 0

if grep -qx 'CHANGELOG.md' <<< "$changed"; then
  exit 0
fi

cat <<'JSON'
{"decision": "block", "reason": "App code under accounts/, movies/, core/, community/, feedback/, config/, or templates/ changed on this branch (vs upstream/origin/main) without a corresponding CHANGELOG.md update. Add an entry to the [Unreleased] section — invoke the changelog skill (/changelog) or edit CHANGELOG.md directly — then stop. To bypass for this turn, run with SKIP_CHANGELOG_CHECK=1."}
JSON
