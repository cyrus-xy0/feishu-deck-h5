#!/usr/bin/env bash
# package-skill.sh — build a portable feishu-deck-h5.zip
#
# Produces feishu-deck-h5-<YYYYMMDD>-<shortsha>.zip in the repo root.
# Recipient unzips → moves the inner feishu-deck-h5/ folder into their
# harness's skills directory (~/.claude/skills/, ~/.openclaw/skills/, …).
#
# Version naming:  date stamp + git short SHA (auto, fully traceable).
# Dirty trees are flagged with `-dirty` so you don't ship un-committed work
# without realizing it.
#
# Usage:
#   bash package-skill.sh                # from repo root
#
# Output:
#   feishu-deck-h5-<version>.zip   in the repo root.

set -euo pipefail

SKILL_NAME="feishu-deck-h5"
SKILL_SRC="skills/$SKILL_NAME"

if [ ! -d "$SKILL_SRC" ]; then
  echo "package-skill: must run from repo root (no $SKILL_SRC/ found)" >&2
  exit 1
fi

DATE_STAMP="$(date +%Y%m%d)"
SHORT_SHA="$(git rev-parse --short HEAD 2>/dev/null || echo nogit)"
DIRTY_FLAG=""
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  DIRTY_FLAG="-dirty"
fi
VERSION="${DATE_STAMP}-${SHORT_SHA}${DIRTY_FLAG}"
ZIP_NAME="${SKILL_NAME}-${VERSION}.zip"

# Stage in a tmp dir so we can write the install README at the zip root
# cleanly, without polluting the repo.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Copy the skill folder, excluding generated/local noise.
rsync -a \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='*.pyo' \
  --exclude='.DS_Store' \
  --exclude='.pytest_cache' \
  --exclude='*.bak' \
  --exclude='*.orig' \
  --exclude='runs/' \
  "$SKILL_SRC/" "$TMP/$SKILL_NAME/"

# Drop a short install README at the zip root.
BUILT_AT="$(date '+%Y-%m-%d %H:%M:%S %Z')"
cat > "$TMP/INSTALL-FROM-ZIP.md" <<EOF
# feishu-deck-h5 · install from zip

**Version:** \`$VERSION\`
**Built:** $BUILT_AT

## Install

Unzip this archive, then move the inner \`$SKILL_NAME/\` directory into
your harness's skills folder:

| Harness         | Target path                                |
| --------------- | ------------------------------------------ |
| Claude Code     | \`~/.claude/skills/$SKILL_NAME/\`         |
| OpenClaw        | \`~/.openclaw/skills/$SKILL_NAME/\`       |
| Other           | \`<harness-root>/skills/$SKILL_NAME/\`     |

Quick way (Claude Code on macOS / Linux):

\`\`\`bash
unzip $ZIP_NAME
mkdir -p ~/.claude/skills
mv $SKILL_NAME ~/.claude/skills/
\`\`\`

## Verify

\`\`\`bash
bash ~/.claude/skills/$SKILL_NAME/assets/preflight.sh
\`\`\`

Expect \`PREFLIGHT OK\`. Done — invoke the skill from any chat that has
a writable mounted folder.

## Notes

- This is a **snapshot** at version \`$VERSION\`. To update, ask the
  maintainer for a fresh zip, or use the git-based install in the
  project's \`INSTALL.md\` (requires GitHub access).
- \`runs/\` (per-invocation outputs) is intentionally excluded from this
  zip. It will be created at \`~/.claude/skills/$SKILL_NAME/runs/\` (or
  at the repo root when checked out via git) on first use.
- The skill is fully self-contained — no \`pip install\` or
  \`npm install\` required. Stock Python 3.11+ and a modern browser
  are enough.
EOF

# Build the zip
(cd "$TMP" && zip -rq "$ZIP_NAME" .)
mv "$TMP/$ZIP_NAME" .

# Report
SIZE_HUMAN="$(du -h "$ZIP_NAME" | cut -f1)"
FILE_COUNT="$(unzip -l "$ZIP_NAME" | tail -1 | awk '{print $2}')"
echo "OK → $ZIP_NAME"
echo "    size:    $SIZE_HUMAN"
echo "    files:   $FILE_COUNT"
echo "    version: $VERSION"
echo
echo "Send to recipient. They unzip, move $SKILL_NAME/ into their"
echo "harness's skills dir, run preflight.sh, done."
