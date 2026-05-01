#!/usr/bin/env bash
# feishu-deck-h5 · per-run workspace creator
#
# Creates a fresh runs/<YYYYMMDD-HHMMSS>/{input,output} folder pair so the
# user's source materials and the agent's generated deck stay separated.
# Prints the absolute path of the new run folder on stdout (last line) so
# the calling agent can capture it.
#
# Usage:
#   bash assets/new-run.sh                # creates runs/<ts>/{input,output}
#   bash assets/new-run.sh my-pitch       # creates runs/<ts>-my-pitch/{input,output}
#
# Exit codes:
#   0  OK — folder created
#   1  could not create folder (permission / no mount / etc.)
#
# This script is mandated by SKILL.md "WORKSPACE LAYOUT" — every skill
# invocation creates one new run folder and writes the deck under output/.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Where to root the runs/ folder.
#
# Preference order:
#   1. Repo root (resolved via `git rev-parse --show-toplevel`) — when the
#      skill lives inside a git checkout, runs/ goes at the repo top so
#      users see  <repo>/runs/<ts>/  instead of having to dive through
#      <repo>/skills/<skill-name>/runs/<ts>/. Saves two levels in the
#      typical single-skill repo and matches user expectation that
#      generated artifacts live next to README, not inside skill source.
#   2. Skill root — fallback when the skill isn't inside a git tree
#      (rare; ad-hoc copies, untracked installs).
if REPO_ROOT="$(git -C "$SKILL_ROOT" rev-parse --show-toplevel 2>/dev/null)"; then
  RUNS_BASE="$REPO_ROOT"
else
  RUNS_BASE="$SKILL_ROOT"
fi

SLUG="${1:-}"
TS="$(date +%Y%m%d-%H%M%S)"

if [[ -n "$SLUG" ]]; then
  # Sanitize slug: keep [a-zA-Z0-9._-], replace others with '-', collapse repeats.
  SLUG="$(printf '%s' "$SLUG" | tr -c 'a-zA-Z0-9._-' '-' | tr -s '-' | sed 's/^-//; s/-$//')"
  RUN_NAME="${TS}-${SLUG}"
else
  RUN_NAME="$TS"
fi

RUN_DIR="$RUNS_BASE/runs/$RUN_NAME"

# In the unlikely case of a same-second collision, append -2, -3, ...
if [[ -e "$RUN_DIR" ]]; then
  N=2
  while [[ -e "${RUN_DIR}-${N}" ]]; do N=$((N+1)); done
  RUN_DIR="${RUN_DIR}-${N}"
fi

if ! mkdir -p "$RUN_DIR/input" "$RUN_DIR/output"; then
  echo "NEW-RUN FAIL · could not create $RUN_DIR" >&2
  exit 1
fi

# Drop one-click apply launchers into output/ so the local user gets the
# same edit-loop UX as the bundled deliverable zip: edit texts.md → double
# click apply.command (macOS) / apply.bat (Windows) → refresh index.html.
# Without these, Mode 1 users have to type a multi-arg python command from
# the repo root, which is the friction this addresses.
for src in \
  "$SKILL_ROOT/assets/apply-texts.py" \
  "$SKILL_ROOT/templates/apply.command" \
  "$SKILL_ROOT/templates/apply.bat"
do
  if [[ -f "$src" ]]; then
    cp "$src" "$RUN_DIR/output/" || echo "warning: could not copy $src" >&2
  else
    echo "warning: launcher source missing: $src" >&2
  fi
done
chmod +x "$RUN_DIR/output/apply.command" 2>/dev/null || true

REL_DIR="${RUN_DIR#$RUNS_BASE/}"

echo "NEW RUN OK"
echo "  run name : $RUN_NAME"
echo "  input    : $REL_DIR/input/    ← user drops source files here"
echo "  output   : $REL_DIR/output/   ← agent writes the deck here"
echo "  launcher : $REL_DIR/output/apply.command (mac) / apply.bat (win)"
echo "             ↑ edit texts.md → double-click → index.html updates"
echo "  abs path : $RUN_DIR"
echo "$RUN_DIR"
exit 0
