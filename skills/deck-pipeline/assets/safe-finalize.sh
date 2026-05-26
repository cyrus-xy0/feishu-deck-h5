#!/usr/bin/env bash
set -euo pipefail

OUT_DIR="${1:-}"
MODE="${2:-local}"
STRICT=""
NAME=""

shift || true
shift || true
while [ $# -gt 0 ]; do
  case "$1" in
    --strict) STRICT="--strict"; shift ;;
    --name) NAME="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$OUT_DIR" ] || [ ! -d "$OUT_DIR" ]; then
  echo "usage: bash safe-finalize.sh <output-dir> [local|remote|inline] [--strict] [--name <slug>]" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UPSTREAM_DIR="$(cd "$SCRIPT_DIR/../../feishu-deck-h5/assets" && pwd)"
HTML="$OUT_DIR/index.html"

if [ ! -f "$HTML" ]; then
  echo "✗ no index.html in $OUT_DIR" >&2
  exit 1
fi

python3 "$SCRIPT_DIR/historical-run-guard.py" "$OUT_DIR"
python3 "$SCRIPT_DIR/safe-copy-assets.py" "$OUT_DIR"

TEXTS="$OUT_DIR/texts.md"
if [ ! -f "$TEXTS" ]; then
  python3 "$UPSTREAM_DIR/extract-texts.py" "$HTML" --out "$TEXTS" || true
fi

python3 "$SCRIPT_DIR/safe-validate.py" "$HTML" $STRICT

NAMED_HTML=""
if [ -n "$NAME" ]; then
  NAMED_HTML="$OUT_DIR/$NAME.html"
  cp "$HTML" "$NAMED_HTML"
fi

case "$MODE" in
  local)
    if [ -n "$NAMED_HTML" ]; then
      echo "$NAMED_HTML"
    else
      echo "$HTML"
    fi
    ;;
  remote)
    ZIP_ARGS=("$OUT_DIR")
    if [ -n "$NAME" ]; then
      ZIP_ARGS+=("--name" "$NAME")
    fi
    bash "$UPSTREAM_DIR/package-deliverable.sh" "${ZIP_ARGS[@]}"
    ;;
  inline)
    INLINE_OUT="$OUT_DIR/${NAME:-deck}-inline.html"
    python3 "$SCRIPT_DIR/inline-assets.py" "$HTML" --out "$INLINE_OUT"
    echo "$INLINE_OUT"
    ;;
  *)
    echo "unknown mode: $MODE" >&2
    exit 1
    ;;
esac
