#!/usr/bin/env bash
# feishu-deck-h5 · one-command install from an unpacked zip
#
# This script lives INSIDE the skill folder. After you unzip the delivered
# archive, run it from anywhere and it will copy the skill into your agent
# harness's skills directory and run preflight.
#
# It is harness-agnostic: it auto-detects common skills dirs, and you can
# always override the destination explicitly.
#
# Usage:
#   bash feishu-deck-h5/install-from-zip.sh                 # auto-detect
#   SKILLS_DIR="$HOME/.claude/skills" bash .../install-from-zip.sh
#   SKILLS_DIR="$HOME/.codex/skills"  bash .../install-from-zip.sh
#
# Env:
#   SKILLS_DIR   destination skills directory (skips auto-detect if set)
#
# No GitHub access, no pip, no npm. Needs Python 3.10+ (preflight enforces it).

set -euo pipefail

SKILL_NAME="feishu-deck-h5"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$SRC_DIR/SKILL.md" ]; then
  echo "ERROR: this script must sit inside the unpacked $SKILL_NAME/ folder" >&2
  echo "       (expected $SRC_DIR/SKILL.md)" >&2
  exit 1
fi

# ---- pick a destination skills dir ----
pick_dest() {
  if [ -n "${SKILLS_DIR:-}" ]; then
    echo "$SKILLS_DIR"
    return
  fi
  # Prefer an already-existing harness skills dir (most specific first).
  for d in \
    "$HOME/.claude/skills" \
    "$HOME/.codex/skills" \
    "$HOME/.openclaw/skills" \
    "$HOME/.agents/skills"; do
    if [ -d "$d" ]; then
      echo "$d"
      return
    fi
  done
  return 1
}

if ! DEST="$(pick_dest)"; then
  cat >&2 <<EOF
Could not auto-detect a skills directory.

Set SKILLS_DIR to your harness's skills folder and re-run, e.g.:

  SKILLS_DIR="\$HOME/.claude/skills"  bash "$SRC_DIR/install-from-zip.sh"   # Claude Code
  SKILLS_DIR="\$HOME/.codex/skills"   bash "$SRC_DIR/install-from-zip.sh"   # Codex
  SKILLS_DIR="<harness-root>/skills"  bash "$SRC_DIR/install-from-zip.sh"   # other agents
EOF
  exit 1
fi

DEST_SKILL="$DEST/$SKILL_NAME"
echo "==> installing $SKILL_NAME"
echo "    from: $SRC_DIR"
echo "    into: $DEST_SKILL"

mkdir -p "$DEST"

# If destination exists (real dir or symlink), replace it cleanly.
if [ -L "$DEST_SKILL" ] || [ -e "$DEST_SKILL" ]; then
  echo "==> removing existing $DEST_SKILL"
  rm -rf "$DEST_SKILL"
fi

# Copy (never symlink — the zip is a snapshot the user may delete).
if command -v rsync >/dev/null 2>&1; then
  rsync -a --exclude='runs/' --exclude='__pycache__' --exclude='*.pyc' \
    "$SRC_DIR/" "$DEST_SKILL/"
else
  cp -R "$SRC_DIR" "$DEST_SKILL"
  rm -rf "$DEST_SKILL/runs"
fi
echo "==> copied."

# ---- verify ----
echo
echo "==> running preflight..."
if bash "$DEST_SKILL/assets/preflight.sh"; then
  echo
  echo "==> DONE. Restart your agent session to pick up the skill."
else
  rc=$?
  echo
  echo "WARN — preflight exited $rc. The skill is copied at $DEST_SKILL but"
  echo "your environment needs attention (see the message above)."
  exit "$rc"
fi
