#!/usr/bin/env bash
# feishu-deck-h5  ·  package the per-run output into a self-contained zip.
#
# Bundles index.html + assets/ + optional deck.json sidecar + a user-facing
# README into `deck-editable.zip`. The recipient unzips, double-clicks
# index.html, presses **E** to enter the built-in visual editor (default-on,
# zero deps), clicks any text to edit it, and saves with Cmd/Ctrl+S — no
# Claude Code / OpenClaw / pip install required, works offline in any browser.
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
SKIP_PORTABLE_CHECK=""
while [ $# -gt 0 ]; do
  case "$1" in
    --name) NAME="${2:?--name requires a value}"; shift 2 ;;
    --skip-portable-check) SKIP_PORTABLE_CHECK="1"; shift ;;
    *) echo "unknown arg: $1"; exit 1 ;;
  esac
done

# delivery-4: --name becomes a path component of ZIP_PATH ($OUT_DIR/$NAME.zip).
# Reject any traversal/separator so the zip can never be written outside OUT_DIR.
case "$NAME" in
  *..* | */* | "")
    echo "ERROR: --name must be a bare basename (no '/' or '..'): $NAME"
    exit 1
    ;;
esac

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

# Portability preflight (F-343): a blind `zip output/` ships broken paths if the
# output was never self-contained (skill-relative refs, symlink shared/). This
# gate makes the low-level packager safe even when entered without finalize.sh.
# Skip with --skip-portable-check only when you know the destination follows
# symlinks / keeps the skill folder adjacent.
if [ -z "$SKIP_PORTABLE_CHECK" ]; then
  if ! python3 "$SKILL_DIR/assets/verify-portable.py" "$OUT_DIR"; then
    echo "" >&2
    echo "✗ refusing to package a non-portable output (see above)." >&2
    echo "  self-contain first:  python3 assets/copy-assets.py \"$OUT_DIR\" --shared=copy" >&2
    echo "  or one-shot:         bash assets/finalize.sh \"$OUT_DIR\" remote" >&2
    echo "  (override with --skip-portable-check if you really mean it)" >&2
    exit 2
  fi
fi

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

echo "feishu-deck-h5 · package-deliverable"
echo "  source HTML  : $HTML_FILE"
echo "  bundle name  : ${NAME}.zip"

# Build a clean staging dir so the zip's internal layout is predictable
STAGE=$(mktemp -d -t feishu-deck-pkg.XXXXXX)
trap 'rm -rf "$STAGE"' EXIT

cp "$HTML_FILE"  "$STAGE/index.html"
cp "$SKILL_DIR/templates/README-deliverable.txt" "$STAGE/README.txt"

ZIP_ITEMS=(
  index.html
  README.txt
)

add_optional_file() {
  local rel="$1"
  if [ -f "$OUT_DIR/$rel" ]; then
    mkdir -p "$STAGE/$(dirname "$rel")"
    cp "$OUT_DIR/$rel" "$STAGE/$rel"
    ZIP_ITEMS+=("$rel")
  fi
}

add_optional_dir() {
  local rel="$1"
  if [ -d "$OUT_DIR/$rel" ]; then
    mkdir -p "$STAGE/$(dirname "$rel")"
    cp -R "$OUT_DIR/$rel" "$STAGE/$rel"
    ZIP_ITEMS+=("$rel")
  fi
}

# delivery-1: a link-mode output keeps assets/shared as a symlink to the canonical
# 30 MB skill pool. `cp -R` preserves it and `zip -r` later DEREFERENCES it, leaking
# every other customer's logo into the deliverable. Refuse rather than ship the pool;
# the caller must self-contain referenced files first (copy-assets.py --shared=copy,
# which finalize.sh remote mode now does automatically).
if [ -L "$OUT_DIR/assets/shared" ]; then
  echo "ERROR: $OUT_DIR/assets/shared is a symlink to the shared pool."
  echo "       Packaging would deref it and leak the WHOLE pool into the zip."
  echo "       Self-contain first:  python3 $(dirname "$0")/copy-assets.py \"$OUT_DIR\" --shared=copy"
  exit 2
fi

if [ -d "$OUT_DIR/assets" ]; then
  cp -R "$OUT_DIR/assets" "$STAGE/assets"
  ZIP_ITEMS+=(assets)
fi

add_optional_file "assets-manifest.yaml"
add_optional_file "deck.json"
add_optional_file "slide-index.json"
add_optional_file "making-of.html"
add_optional_dir "input"
add_optional_dir "prototypes"
add_optional_dir "deck-log"

for sidecar in "$OUT_DIR"/*.xml; do
  [ -e "$sidecar" ] || continue
  add_optional_file "$(basename "$sidecar")"
done

ZIP_PATH="$OUT_DIR/${NAME}.zip"
rm -f "$ZIP_PATH"

# -X strips extra timestamps. Keep paths relative to STAGE so assets/ remains
# next to index.html, matching the linked HTML references.
# delivery-1: never ship system metadata (.DS_Store / __MACOSX / AppleDouble ._*)
# into the customer-facing deliverable.
( cd "$STAGE" && zip -q -X -r "$ZIP_PATH" "${ZIP_ITEMS[@]}" \
    -x '*.DS_Store' -x '__MACOSX/*' -x '*/._*' -x '._*' )

if [ ! -f "$ZIP_PATH" ]; then
  echo "ERROR: zip step failed"
  exit 2
fi

SIZE_KB=$(( $(stat -f%z "$ZIP_PATH" 2>/dev/null || stat -c%s "$ZIP_PATH") / 1024 ))
echo "  wrote        : $ZIP_PATH  (${SIZE_KB} KB)"
echo
echo "Hand this zip to the user (Feishu attachment, email, OpenClaw return)."
echo "They unzip, open index.html, press E to edit text in-browser, Cmd/Ctrl+S"
echo "to save. README.txt explains all of this."
