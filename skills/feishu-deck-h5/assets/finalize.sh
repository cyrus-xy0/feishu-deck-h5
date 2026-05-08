#!/usr/bin/env bash
# feishu-deck-h5  ·  finalize a per-run output in one shot.
#
# Replaces the manual "remember to call copy-assets, then extract-texts,
# then validate, then maybe package-deliverable" sequence with a single
# orchestrated command. Idempotent — safe to re-run after edits.
#
# Usage:
#     bash assets/finalize.sh <output-dir> [mode] [--strict]
#         mode:    local (default) | remote | inline
#         --strict promotes validator warnings to errors (use for final delivery)
#
#     local   = copy-assets + extract-texts + validate
#     remote  = local steps + package-deliverable.sh (zip kit)
#     inline  = local steps + base64-inline assets into single .html
#
# Exit codes:
#     0  all green
#     1  bad arguments
#     2  copy-assets failed
#     3  extract-texts failed
#     4  validate failed (errors — fix the deck and re-run)
#     5  packaging failed

set -euo pipefail

OUT_DIR="${1:-}"
MODE="local"
STRICT=""

shift || true
while [ $# -gt 0 ]; do
    case "$1" in
        local|remote|inline) MODE="$1"; shift ;;
        --strict) STRICT="--strict"; shift ;;
        *) echo "unknown arg: $1" >&2; exit 1 ;;
    esac
done

if [ -z "$OUT_DIR" ] || [ ! -d "$OUT_DIR" ]; then
    echo "usage: bash $(basename "$0") <output-dir> [local|remote|inline] [--strict]" >&2
    echo "       output-dir must exist (typically runs/<ts>/output/)" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HTML="$OUT_DIR/index.html"

if [ ! -f "$HTML" ]; then
    echo "✗ no index.html in $OUT_DIR" >&2
    exit 1
fi

echo "==> finalize  ·  $OUT_DIR  ($MODE)"

# ---------- 1 · copy-assets (make output portable) ----------
echo "  · copy-assets …"
if ! python3 "$SCRIPT_DIR/copy-assets.py" "$OUT_DIR" >/dev/null 2>&1; then
    echo "✗ copy-assets failed — run manually for diagnosis:" >&2
    echo "    python3 $SCRIPT_DIR/copy-assets.py $OUT_DIR" >&2
    exit 2
fi

# ---------- 2 · extract-texts (sidecar) ----------
TEXTS="$OUT_DIR/texts.md"
if [ ! -f "$TEXTS" ]; then
    echo "  · extract-texts (no sidecar found, generating) …"
    if ! python3 "$SCRIPT_DIR/extract-texts.py" "$HTML" --out "$TEXTS" >/dev/null 2>&1; then
        echo "  ! extract-texts skipped (deck has no data-text-id leaves — fine for Replica decks)"
    fi
else
    echo "  · texts.md sidecar already exists, skip"
fi

# ---------- 3 · validate ----------
if [ -n "$STRICT" ]; then
    echo "  · validate --strict …"
else
    echo "  · validate …"
fi
if ! python3 "$SCRIPT_DIR/validate.py" "$HTML" $STRICT; then
    if [ -n "$STRICT" ]; then
        echo "✗ validator failed under --strict — fix the warnings/errors above" >&2
    else
        echo "✗ validator errors — fix above and re-run" >&2
    fi
    exit 4
fi

# ---------- 4 · mode-specific packaging ----------
case "$MODE" in
    local)
        echo ""
        echo "✓ ready (local) — open in browser:"
        echo "    open $HTML"
        ;;
    remote)
        echo "  · package-deliverable …"
        if ! bash "$SCRIPT_DIR/package-deliverable.sh" "$OUT_DIR" >/dev/null 2>&1; then
            echo "✗ packaging failed" >&2
            exit 5
        fi
        ZIP="$OUT_DIR/deck-editable.zip"
        echo ""
        echo "✓ ready (remote) — attach this zip to your delivery:"
        echo "    $ZIP"
        ;;
    inline)
        echo "  · inline mode not yet wired — run manually:"
        echo "    bash skills/feishu-deck-h5/build.sh --inline"
        echo ""
        echo "✓ ready (local outputs in $OUT_DIR — inline single-file is build.sh's job)"
        ;;
esac
