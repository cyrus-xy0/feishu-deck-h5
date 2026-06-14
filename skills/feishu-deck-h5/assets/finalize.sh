#!/usr/bin/env bash
# feishu-deck-h5  ·  finalize a per-run output in one shot.
#
# Replaces the manual "remember to call copy-assets, then validate, then
# maybe package-deliverable" sequence with a single orchestrated command.
# Idempotent — safe to re-run after edits.
#
# Usage:
#     bash assets/finalize.sh <output-dir> [mode] [--strict] [--name <slug>] [--deck-id <deck-id>]
#         mode:           local (default) | remote | library
#         --strict        promote validator warnings to errors (final delivery)
#         --name <slug>   emit a delivery-named copy alongside index.html
#                         convention: lark-<customer>-<presentation-date>
#                         e.g. --name lark-boyu-starbucks-2026-05-08
#         --deck-id       required in library mode; stable material-library id
#
#     local   = copy-assets + validate (+ named copy if --name)
#     remote  = local steps + package-deliverable.sh (zip kit, zip name from --name)
#     library = copy-assets --shared=copy + validate --strict
#               + check-only gate + package-ingest.sh + deck.zip gate
#
# For single-file inline delivery (base64-inlined CSS/JS/images into one
# .html file for email/IM attachment), inline THE USER'S RUN with
# `python3 deck-json/render-deck.py runs/<ts>/output --inline` (or
# `python3 assets/inline-assets.py runs/<ts>/output/index.html --out <file>`).
# Do NOT use `build.sh --inline` — that rebuilds the skill's bundled SAMPLE deck.
#
# Exit codes:
#     0  all green
#     1  bad arguments
#     2  copy-assets failed
#     4  validate failed (errors — fix the deck and re-run)
#     5  packaging failed
#     6  ingest gate failed

set -euo pipefail

OUT_DIR="${1:-}"
MODE="local"
STRICT=""
NAME=""
DECK_ID=""

shift || true
while [ $# -gt 0 ]; do
    case "$1" in
        local|remote|library) MODE="$1"; shift ;;
        inline)
            echo "✗ 'inline' mode is no longer a finalize.sh subcommand." >&2
            echo "  For single-file inline delivery of THIS run, run:" >&2
            echo "    python3 deck-json/render-deck.py ${OUT_DIR:-runs/<ts>/output} --inline" >&2
            echo "  (build.sh --inline rebuilds the bundled SAMPLE deck, not your run.)" >&2
            exit 1
            ;;
        --strict) STRICT="--strict"; shift ;;
        --name) NAME="${2:?--name requires a value}"; shift 2 ;;
        --deck-id) DECK_ID="${2:?--deck-id requires a value}"; shift 2 ;;
        *) echo "unknown arg: $1" >&2; exit 1 ;;
    esac
done

if [ "$MODE" = "library" ]; then
    if [ -n "$NAME" ]; then
        echo "✗ library mode does not accept --name; it always writes deck.zip" >&2
        exit 1
    fi
    if [ -z "$DECK_ID" ]; then
        echo "✗ library mode requires --deck-id <deck-id>" >&2
        exit 1
    fi
fi

# Validate --name against the convention if provided
if [ -n "$NAME" ]; then
    if ! [[ "$NAME" =~ ^lark-[a-z0-9-]+-[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        echo "✗ --name must follow lark-<customer>-<YYYY-MM-DD> (got: $NAME)" >&2
        echo "  example: --name lark-boyu-starbucks-2026-05-08" >&2
        exit 1
    fi
fi

if [ -z "$OUT_DIR" ] || [ ! -d "$OUT_DIR" ]; then
    echo "usage: bash $(basename "$0") <output-dir> [local|remote|library] [--strict] [--name <slug>] [--deck-id <deck-id>]" >&2
    echo "       output-dir must exist (typically runs/<ts>/output/)" >&2
    echo "       --name convention: lark-<customer>-<YYYY-MM-DD>" >&2
    echo "       library mode: bash $(basename "$0") <output-dir> library --deck-id <deck-id>" >&2
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
    local log rc
    log=$(mktemp -t feishu-finalize-step.XXXXXX)
    "$@" >"$log" 2>&1
    rc=$?                                     # capture BEFORE the `if`/`fi` resets $? to 0
    if [ "$rc" -eq 0 ]; then
        rm -f "$log"
        return 0
    fi
    echo "✗ $desc failed (exit $rc):" >&2
    sed 's/^/    /' "$log" >&2
    rm -f "$log"
    return 1
}

# ---------- 1 · copy-assets (make output portable) ----------
# delivery-1: remote (and library) must SELF-CONTAIN — real-copy only the shared
# files this deck references. The default --shared=link makes output/assets/shared
# a symlink to the whole 30 MB skill pool, which package-deliverable.sh's zip then
# DEREFERENCES, leaking every other customer's logo into the deliverable. Only the
# in-place `local` mode (kept next to the skill) may use the link.
COPY_ARGS=("$OUT_DIR")
if [ "$MODE" = "library" ] || [ "$MODE" = "remote" ]; then
    COPY_ARGS+=("--shared=copy")
fi
if [ "$MODE" = "library" ] || [ "$MODE" = "remote" ]; then
    echo "  · copy-assets --shared=copy …"
else
    echo "  · copy-assets …"
fi
if ! run_step "copy-assets" python3 "$SCRIPT_DIR/copy-assets.py" "${COPY_ARGS[@]}"; then
    exit 2
fi

# ---------- 2 · validate ----------
VALIDATE_STRICT="$STRICT"
if [ "$MODE" = "library" ]; then
    VALIDATE_STRICT="--strict"
fi
if [ -n "$VALIDATE_STRICT" ]; then
    echo "  · validate --strict …"
else
    echo "  · validate …"
fi
if ! python3 "$SCRIPT_DIR/validate.py" "$HTML" $VALIDATE_STRICT; then
    if [ -n "$VALIDATE_STRICT" ]; then
        echo "✗ validator failed under --strict — fix the warnings/errors above" >&2
    else
        echo "✗ validator errors — fix above and re-run" >&2
    fi
    exit 4
fi

# D-14: a default (non-strict) validate pass can still be REJECTED at
# slide-library ingest, because the ingest gate (`check-only.py --gate ingest`)
# forces strict (warn→error) + visual audit. Surface that stricter bar here so a
# "done" deck doesn't surprise-fail on hand-off. Only nag when not already strict.
if [ -z "$STRICT" ] && [ "$MODE" != "library" ]; then
    echo ""
    echo "  ℹ️  slide-library 入库门禁更严:strict(warn→error) + 视觉审计。"
    echo "      入库前想按同一档门槛预检,任选其一:"
    echo "        bash $(basename "$0") \"$OUT_DIR\" $MODE --strict"
    echo "        python3 \"$SCRIPT_DIR/check-only.py\" \"$HTML\" --gate ingest"
fi

if [ "$MODE" = "library" ]; then
    echo "  · check-only --gate ingest (HTML) …"
    if ! run_step "check-only HTML gate" python3 "$SCRIPT_DIR/check-only.py" "$HTML" --gate ingest; then
        exit 6
    fi
fi

# ---------- 3 · delivery-named copy (if --name provided) ----------
NAMED_HTML=""
if [ -n "$NAME" ]; then
    NAMED_HTML="$OUT_DIR/$NAME.html"
    cp "$HTML" "$NAMED_HTML"
    echo "  · copied → $NAME.html"
fi

# ---------- 4 · mode-specific packaging ----------
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
    library)
        echo "  · package-ingest …"
        if ! run_step "package-ingest" bash "$SCRIPT_DIR/package-ingest.sh" "$OUT_DIR" --deck-id "$DECK_ID"; then
            exit 5
        fi
        ZIP="$OUT_DIR/deck.zip"
        echo "  · check-only --gate ingest (deck.zip) …"
        if ! run_step "check-only ZIP gate" python3 "$SCRIPT_DIR/check-only.py" "$ZIP" --gate ingest; then
            exit 6
        fi
        echo ""
        echo "✓ ready (library) — upload this zip to feishu-slide-library:"
        echo "    $ZIP"
        ;;
esac
