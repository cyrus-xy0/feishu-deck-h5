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

REL_DIR="${RUN_DIR#"$RUNS_BASE"/}"

echo "NEW RUN OK"
echo "  run name : $RUN_NAME"
echo "  input    : $REL_DIR/input/    ← user drops source files here"
echo "  output   : $REL_DIR/output/   ← agent writes the deck here"
echo "  abs path : $RUN_DIR"

# --- making-of log: auto-start (default-OFF since 2026-06-21; opt-in via `deck-log on` → ~/.claude/deck-log.on) ---
# When enabled, bolted into new-run.sh so the log can NEVER be silently skipped — deck-log
# has no hook, so relying on the agent to remember `deck-log init` is exactly the no-hook
# miss mode the skill warns about. This is the single chokepoint for new workspaces.
# Default-off (2026-06-21): making-of auto-snapshot costs render time, so it is now opt-in.
# `deck-log on` re-enables auto-init here AND auto-snapshot in render-deck.py; without it,
# record a single deck with `deck-log init <deck>` + manual `deck-log snapshot`.
# Guards: failure must never break workspace creation, and the final stdout line MUST
# stay "$RUN_DIR" (the caller captures the last line as the run path), so all deck-log
# chatter is muted and the status note is printed in the human block above it.
if [[ ! -f "$HOME/.claude/deck-log.on" ]] || [[ -f "$HOME/.claude/deck-log.off" ]]; then
  echo "  deck-log : making-of OFF by default (saves render time) — \`deck-log on\` to enable, or \`deck-log init $REL_DIR\` for this deck only"
elif [[ -f "$SKILL_ROOT/log-tool/deck-log.py" ]] \
  && python3 "$SKILL_ROOT/log-tool/deck-log.py" init "$RUN_DIR" --title "${SLUG:-$RUN_NAME}" >/dev/null 2>&1; then
  echo "  deck-log : making-of log started → $REL_DIR/log/  (snapshot/event as you iterate)"
else
  echo "  deck-log : auto-init skipped — run: python3 $SKILL_ROOT/log-tool/deck-log.py init $RUN_DIR"
fi

echo "$RUN_DIR"
exit 0
