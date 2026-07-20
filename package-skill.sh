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
RUNTIME_PROVENANCE="runtime/runtime-provenance.json"

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
  --exclude="$RUNTIME_PROVENANCE" \
  "$SKILL_SRC/" "$TMP/$SKILL_NAME/"

# Emit machine-owned provenance from the trusted Git checkout into the staged
# no-Git skill. runtime-lock.py re-verifies the manifest and every runtime blob.
python3 "$SKILL_SRC/assets/runtime-lock.py" \
  --skill-root "$SKILL_SRC" \
  --provenance-output "$TMP/$SKILL_NAME/$RUNTIME_PROVENANCE"
python3 "$TMP/$SKILL_NAME/assets/runtime-lock.py" \
  --skill-root "$TMP/$SKILL_NAME" \
  --print-commit >/dev/null

# Drop a short install README at the zip root.
BUILT_AT="$(date '+%Y-%m-%d %H:%M:%S %Z')"
cat > "$TMP/INSTALL-FROM-ZIP.md" <<EOF
# feishu-deck-h5 · install from zip

**Version:** \`$VERSION\`
**Built:** $BUILT_AT

## Install (one command)

Unzip, then run the bundled installer. It auto-detects your agent's skills
directory, copies the skill in, and runs preflight:

\`\`\`bash
unzip $ZIP_NAME
bash $SKILL_NAME/install-from-zip.sh
\`\`\`

If auto-detect can't find your skills dir (or you run multiple agents), point
it explicitly — same skill works for every harness:

\`\`\`bash
SKILLS_DIR="\$HOME/.claude/skills" bash $SKILL_NAME/install-from-zip.sh   # Claude Code
SKILLS_DIR="\$HOME/.codex/skills"  bash $SKILL_NAME/install-from-zip.sh   # Codex
SKILLS_DIR="<harness-root>/skills" bash $SKILL_NAME/install-from-zip.sh   # other agents
\`\`\`

## Manual alternative

Move the inner \`$SKILL_NAME/\` directory into your harness's skills folder:

| Harness         | Target path                                |
| --------------- | ------------------------------------------ |
| Claude Code     | \`~/.claude/skills/$SKILL_NAME/\`         |
| Codex           | \`~/.codex/skills/$SKILL_NAME/\`          |
| OpenClaw        | \`~/.openclaw/skills/$SKILL_NAME/\`       |
| Other           | \`<harness-root>/skills/$SKILL_NAME/\`     |

Then verify:

\`\`\`bash
bash <skills-dir>/$SKILL_NAME/assets/preflight.sh
\`\`\`

## Requirements

- **Python 3.10+** (macOS ships 3.9 — install a newer one, e.g.
  \`brew install python@3.11\`, and make sure \`python3\` resolves to it).
  Preflight enforces this and prints exact fix steps if it's too old.
- A modern browser for visual audits (optional; static gates still run).
- No \`pip install\` / \`npm install\` needed — the skill is self-contained.

## Notes

- This is a **snapshot** at version \`$VERSION\`. To update, ask the
  maintainer for a fresh zip and re-run \`install-from-zip.sh\` (it replaces
  the old copy in place).
- \`runs/\` (per-invocation outputs) is excluded from this zip and created
  on first use.
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
