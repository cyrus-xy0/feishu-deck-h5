#!/usr/bin/env bash
# feishu-deck-h5  ·  package the per-run output into a self-contained zip.
#
# Bundles index.html + assets/ + texts.md + the apply-texts engine +
# macOS/Windows launchers + source/metadata sidecars into `deck-editable.zip`.
# The recipient just unzips, edits texts.md, and double-clicks
# apply.command/apply.bat — no Claude Code / OpenClaw / pip install required
# (only python3, which ships on macOS by default and is a one-time install on
# Windows).
#
# Usage:
#     bash assets/package-deliverable.sh runs/<timestamp>/output
#     bash assets/package-deliverable.sh runs/<timestamp>/output --name my-deck
#
# Produces:
#     runs/<timestamp>/output/deck-editable.zip
#
# Exit codes: 0 ok / 1 input missing / 2 packaging error

set -euo pipefail

OUT_DIR="${1:-}"
shift || true

NAME="deck-editable"
while [ $# -gt 0 ]; do
  case "$1" in
    --name) NAME="$2"; shift 2 ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac
done

if [ -z "$OUT_DIR" ]; then
  echo "Usage: bash assets/package-deliverable.sh <output-dir> [--name <basename>]"
  exit 1
fi

if [ ! -d "$OUT_DIR" ]; then
  echo "ERROR: output dir not found: $OUT_DIR"
  exit 1
fi

# Resolve absolute paths
OUT_DIR="$(cd "$OUT_DIR" && pwd)"
SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Locate the deck HTML inside OUT_DIR. Prefer index.html; otherwise pick the
# only .html file present. Fail if ambiguous.
HTML_FILE=""
if [ -f "$OUT_DIR/index.html" ]; then
  HTML_FILE="$OUT_DIR/index.html"
else
  HTML_COUNT=$(find "$OUT_DIR" -maxdepth 1 -name '*.html' | wc -l | tr -d ' ')
  if [ "$HTML_COUNT" = "1" ]; then
    HTML_FILE=$(find "$OUT_DIR" -maxdepth 1 -name '*.html' | head -1)
  else
    echo "ERROR: cannot locate the deck HTML in $OUT_DIR"
    echo "       expected index.html or exactly one *.html (found $HTML_COUNT)"
    exit 1
  fi
fi

# texts.md required: prefer paired basename, fallback to texts.md
HTML_BASE="$(basename "$HTML_FILE" .html)"
TEXTS_FILE=""
if [ -f "$OUT_DIR/${HTML_BASE}.texts.md" ]; then
  TEXTS_FILE="$OUT_DIR/${HTML_BASE}.texts.md"
elif [ -f "$OUT_DIR/texts.md" ]; then
  TEXTS_FILE="$OUT_DIR/texts.md"
else
  echo "ERROR: paired texts.md not found in $OUT_DIR"
  echo "       expected ${HTML_BASE}.texts.md or texts.md"
  echo "       (run extract-texts.py to generate one)"
  exit 1
fi

echo "feishu-deck-h5 · package-deliverable"
echo "  source HTML  : $HTML_FILE"
echo "  source texts : $TEXTS_FILE"
echo "  bundle name  : ${NAME}.zip"

# Build a clean staging dir so the zip's internal layout is predictable
STAGE=$(mktemp -d -t feishu-deck-pkg.XXXXXX)
trap 'rm -rf "$STAGE"' EXIT

cp "$HTML_FILE"  "$STAGE/index.html"
cp "$TEXTS_FILE" "$STAGE/texts.md"
cp "$SKILL_DIR/assets/apply-texts.py"        "$STAGE/apply-texts.py"
cp "$SKILL_DIR/assets/texts_common.py"       "$STAGE/texts_common.py"
cp "$SKILL_DIR/templates/apply.command"      "$STAGE/apply.command"
cp "$SKILL_DIR/templates/apply.bat"          "$STAGE/apply.bat"
cp "$SKILL_DIR/templates/README-deliverable.txt" "$STAGE/README.txt"

# Copy portable runtime assets. `copy-assets.py --shared=link` may leave
# output/assets/shared as a symlink to the canonical shared pool during local
# iteration; dereference it here so the zip is truly self-contained.
if [ -d "$OUT_DIR/assets" ]; then
  cp -R -L "$OUT_DIR/assets" "$STAGE/assets"
fi

# Include source and handoff metadata when present. These files make the zip
# useful as an editable source package, not just a text patch kit.
OPTIONAL_FILES=()
for f in deck.json FEEDBACK.md assets-manifest.yaml pitch-rehearsal.json PITCH_REHEARSAL.md; do
  if [ -f "$OUT_DIR/$f" ]; then
    cp "$OUT_DIR/$f" "$STAGE/$f"
    OPTIONAL_FILES+=("$f")
  fi
done

# launchers must be executable on extract; zip preserves the +x bit
chmod +x "$STAGE/apply.command"

ZIP_PATH="$OUT_DIR/${NAME}.zip"
rm -f "$ZIP_PATH"

# -X strips extra timestamps. Keep top-level files flat, but preserve assets/
# because linked HTML expects `assets/...` paths.
ZIP_ITEMS=(index.html texts.md apply-texts.py texts_common.py apply.command apply.bat README.txt)
if [ -d "$STAGE/assets" ]; then
  ZIP_ITEMS+=(assets)
fi
if [ "${#OPTIONAL_FILES[@]}" -gt 0 ]; then
  ZIP_ITEMS+=("${OPTIONAL_FILES[@]}")
fi
( cd "$STAGE" && zip -q -X -r "$ZIP_PATH" "${ZIP_ITEMS[@]}" )

if [ ! -f "$ZIP_PATH" ]; then
  echo "ERROR: zip step failed"
  exit 2
fi

SIZE_KB=$(( $(stat -f%z "$ZIP_PATH" 2>/dev/null || stat -c%s "$ZIP_PATH") / 1024 ))
echo "  wrote        : $ZIP_PATH  (${SIZE_KB} KB)"
echo
echo "Hand this zip to the user (Feishu attachment, email, OpenClaw return)."
echo "On macOS first-run, ask them to right-click → Open on apply.command"
echo "to clear Gatekeeper. README.txt explains all of this."
