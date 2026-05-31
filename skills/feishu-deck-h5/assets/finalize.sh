#!/usr/bin/env bash
# feishu-deck-h5  ·  finalize a per-run output in one shot.
#
# Replaces the manual "remember to call copy-assets, then extract-texts,
# then validate, then maybe package-deliverable" sequence with a single
# orchestrated command. Idempotent — safe to re-run after edits.
#
# Usage:
#     bash assets/finalize.sh <output-dir> [mode] [--strict] [--name <slug>]
#         mode:           local (default) | remote
#         --strict        promote validator warnings to errors (final delivery)
#         --name <slug>   emit a delivery-named copy alongside index.html
#                         convention: lark-<customer>-<presentation-date>
#                         e.g. --name lark-boyu-starbucks-2026-05-08
#
#     local   = copy-assets + extract-texts + validate (+ named copy if --name)
#     remote  = local steps + package-deliverable.sh (zip kit, zip name from --name)
#
# For single-file inline delivery (base64-inlined CSS/JS/images into one
# .html file for email/IM attachment), run `bash build.sh --inline` from
# the skill root — that's a separate pipeline, not orchestrated here.
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
NAME=""

shift || true
while [ $# -gt 0 ]; do
    case "$1" in
        local|remote) MODE="$1"; shift ;;
        inline)
            echo "✗ 'inline' mode is no longer a finalize.sh subcommand." >&2
            echo "  For single-file inline delivery, run from the skill root:" >&2
            echo "    bash build.sh --inline" >&2
            exit 1
            ;;
        --strict) STRICT="--strict"; shift ;;
        --name) NAME="$2"; shift 2 ;;
        *) echo "unknown arg: $1" >&2; exit 1 ;;
    esac
done

# Validate --name against the convention if provided
if [ -n "$NAME" ]; then
    if ! [[ "$NAME" =~ ^lark-[a-z0-9-]+-[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        echo "✗ --name must follow lark-<customer>-<YYYY-MM-DD> (got: $NAME)" >&2
        echo "  example: --name lark-boyu-starbucks-2026-05-08" >&2
        exit 1
    fi
fi

if [ -z "$OUT_DIR" ] || [ ! -d "$OUT_DIR" ]; then
    echo "usage: bash $(basename "$0") <output-dir> [local|remote] [--strict] [--name <slug>]" >&2
    echo "       output-dir must exist (typically runs/<ts>/output/)" >&2
    echo "       --name convention: lark-<customer>-<YYYY-MM-DD>" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HTML="$OUT_DIR/index.html"

if [ ! -f "$HTML" ]; then
    echo "✗ no index.html in $OUT_DIR" >&2
    exit 1
fi

echo "==> finalize  ·  $OUT_DIR  ($MODE)"

# Helper: run a sub-command, capture its stderr; on failure print the
# captured output so the user sees the real error instead of a useless
# "run manually for diagnosis" prompt.
run_step() {
    local desc="$1"; shift
    local log
    log=$(mktemp -t feishu-finalize-step.XXXXXX)
    if "$@" >"$log" 2>&1; then
        rm -f "$log"
        return 0
    fi
    echo "✗ $desc failed (exit $?):" >&2
    sed 's/^/    /' "$log" >&2
    rm -f "$log"
    return 1
}

# ---------- 1 · copy-assets (make output portable) ----------
echo "  · copy-assets …"
if ! run_step "copy-assets" python3 "$SCRIPT_DIR/copy-assets.py" "$OUT_DIR"; then
    exit 2
fi

# ---------- 2 · extract-texts (sidecar) ----------
TEXTS="$OUT_DIR/texts.md"
if [ ! -f "$TEXTS" ]; then
    echo "  · extract-texts (no sidecar found, generating) …"
    if ! run_step "extract-texts" python3 "$SCRIPT_DIR/extract-texts.py" "$HTML" --out "$TEXTS"; then
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

# ---------- 4 · delivery-named copy (if --name provided) ----------
NAMED_HTML=""
if [ -n "$NAME" ]; then
    NAMED_HTML="$OUT_DIR/$NAME.html"
    cp "$HTML" "$NAMED_HTML"
    echo "  · copied → $NAME.html"
fi

# ---------- 5 · mode-specific packaging ----------
case "$MODE" in
    local)
        echo ""
        if [ -n "$NAMED_HTML" ]; then
            echo "✓ ready (local) — deliver this file:"
            echo "    $NAMED_HTML"
            echo "  (working copy still at $HTML for further edits)"
        else
            echo "✓ ready (local) — open in browser:"
            echo "    open $HTML"
            echo ""
            echo "  TIP: when delivering, re-run with --name lark-<customer>-<YYYY-MM-DD>"
            echo "       to emit a properly-named copy (convention for site sync /"
            echo "       slide-library inbox / customer hand-off)."
        fi
        ;;
    remote)
        echo "  · package-deliverable …"
        ZIP_ARGS=("$OUT_DIR")
        if [ -n "$NAME" ]; then
            ZIP_ARGS+=("--name" "$NAME")
        fi
        if ! run_step "package-deliverable" bash "$SCRIPT_DIR/package-deliverable.sh" "${ZIP_ARGS[@]}"; then
            exit 5
        fi
        ZIP_NAME="${NAME:-deck-editable}"
        ZIP="$OUT_DIR/${ZIP_NAME}.zip"
        echo ""
        echo "✓ ready (remote) — attach this zip to your delivery:"
        echo "    $ZIP"
        if [ -z "$NAME" ]; then
            echo ""
            echo "  TIP: pass --name lark-<customer>-<YYYY-MM-DD> for a named zip"
            echo "       instead of the generic deck-editable.zip."
        fi
        ;;
esac
