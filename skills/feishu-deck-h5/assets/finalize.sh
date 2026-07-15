#!/usr/bin/env bash
# feishu-deck-h5  ·  finalize a per-run output in one shot.
#
# Replaces the manual "remember to call copy-assets, then validate, then
# maybe package-deliverable" sequence with a single orchestrated command.
# Idempotent — safe to re-run after edits.
#
# Usage:
#     bash assets/finalize.sh <output-dir> [mode] [--strict] [--name <slug>] [--deck-id <deck-id>] [--no-optimize-images]
#         mode:           local (default) | remote | library
#         --strict        promote validator warnings to errors (final delivery)
#         --no-optimize-images
#                         skip the F-341 raster downscale pass (keep hi-res images
#                         as-is, e.g. for zoomable detail). Default: downscale
#                         any image whose longest edge exceeds 1920 (the canvas)
#                         so decks open fast, especially on mobile.
#         --name <slug>   name the remote editable zip (remote mode only)
#                         convention: lark-<customer>-<presentation-date>
#                         e.g. --name lark-boyu-starbucks-2026-05-08
#         --deck-id       required in library mode; stable material-library id
#
#     local   = copy-assets + validate (same-workspace checkpoint)
#     remote  = local steps + package-deliverable.sh (zip kit, zip name from --name)
#     library = copy-assets --shared=link + validate
#               + resource-only check + package-ingest.sh (dereference reachable
#                 shared files into deck.zip) + deck.zip resource check
#
# For single-file inline delivery (base64-inlined CSS/JS/images into one
# .html file for email/IM attachment), inline THE USER'S RUN with
# `python3 deck-json/render-deck.py <deck.json> <output-dir> --inline` (or
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
OPTIMIZE_IMAGES=1   # F-341: downscale oversized rasters for fast (mobile) load

shift || true
while [ $# -gt 0 ]; do
    case "$1" in
        local|remote|library) MODE="$1"; shift ;;
        --no-optimize-images) OPTIMIZE_IMAGES=0; shift ;;
        inline)
            echo "✗ 'inline' mode is no longer a finalize.sh subcommand." >&2
            echo "  For single-file inline delivery of THIS run, run:" >&2
            echo "    python3 deck-json/render-deck.py <deck.json> <output-dir> --inline" >&2
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

if [ "$MODE" = "local" ] && [ -n "$NAME" ]; then
    echo "✗ local mode does not accept --name; it does not create a transport artifact" >&2
    echo "  use remote --name for an editable zip, or render-deck.py --inline for one HTML" >&2
    exit 1
fi

# Validate --name against the convention if provided
if [ -n "$NAME" ]; then
    if ! [[ "$NAME" =~ ^lark-[a-z0-9-]+-[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        echo "✗ --name must follow lark-<customer>-<YYYY-MM-DD> (got: $NAME)" >&2
        echo "  example: --name lark-boyu-starbucks-2026-05-08" >&2
        exit 1
    fi
fi

# F-343: accept a slug (or partial run name) in place of the full output path.
# resolve-run.sh maps `everbright` → runs/*everbright*/output (newest), so
# delivery never needs a hand-typed path or a broad `find`. An existing path
# passes straight through. resolve-run prints disambiguation/errors to stderr.
_FZ_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -n "$OUT_DIR" ] && [ ! -d "$OUT_DIR" ]; then
    if RESOLVED="$(bash "$_FZ_DIR/resolve-run.sh" "$OUT_DIR")"; then
        echo "  · resolved '$OUT_DIR' → $RESOLVED"
        OUT_DIR="$RESOLVED"
    fi
fi

if [ -z "$OUT_DIR" ] || [ ! -d "$OUT_DIR" ]; then
    echo "usage: bash $(basename "$0") <output-dir|slug> [local|remote|library] [--strict] [--name <slug>] [--deck-id <deck-id>]" >&2
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
# delivery-1: remote must SELF-CONTAIN — real-copy only the shared files this deck
# references because package-deliverable.sh consumes the output tree directly.
# Library mode keeps the local shared link: package-ingest.sh dereferences only
# the verified reachable closure into deck.zip, so the run stays compact without
# leaking the whole shared pool.
COPY_ARGS=("$OUT_DIR")
if [ "$MODE" = "remote" ]; then
    COPY_ARGS+=("--shared=copy")
fi
if [ "$MODE" = "remote" ]; then
    echo "  · copy-assets --shared=copy …"
else
    echo "  · copy-assets --shared=link …"
fi
if ! run_step "copy-assets" python3 "$SCRIPT_DIR/copy-assets.py" "${COPY_ARGS[@]}"; then
    echo "FAIL_DOMAIN=delivery DO_NOT_EDIT_DECK=1" >&2
    exit 2
fi

# ---------- 1a · materialize remote images ----------
# Library/remote packages must not depend on temporary signed image URLs. Local
# preview may succeed while a p-mira/TOS URL later expires to 403 on the material
# library. Download http(s) image refs into output/assets/remote/ before
# validation, optimization, and zipping; fail here if the remote image is already
# inaccessible.
if [ "$MODE" = "library" ] || [ "$MODE" = "remote" ]; then
    echo "  · materialize-remote-images …"
    if ! run_step "materialize-remote-images" python3 "$SCRIPT_DIR/materialize-remote-images.py" "$OUT_DIR"; then
        echo "FAIL_DOMAIN=delivery DO_NOT_EDIT_DECK=1" >&2
        exit 5
    fi
fi

# ---------- 1b · optimize images (downscale oversized rasters) ----------
# F-341: imported/photo decks routinely carry 4K (3840×2160) full-page
# backgrounds + multi-MB PNGs for a 1920×1080 canvas — pure download + decode
# waste that makes decks slow to open, worst on mobile (4K JPEG decode is ~4×
# the CPU/memory of 1080p). Downscale the OUTPUT copies to the canvas longest
# edge. Downscale-ONLY here (no PNG→JPEG transcode) so filenames/refs are
# unchanged and the manifest copy-assets just wrote stays accurate; the
# standalone tool also transcodes for in-place decks. Non-fatal: a missing
# Pillow/sips just leaves images as-is. Opt out with --no-optimize-images for
# decks that intentionally ship hi-res (zoomable detail).
if [ "$OPTIMIZE_IMAGES" = "1" ]; then
    echo "  · optimize-images (downscale ≤1920) …"
    if ! run_step "optimize-images" python3 "$SCRIPT_DIR/optimize-images.py" "$OUT_DIR" --no-transcode --quiet; then
        echo "  ⚠️ optimize-images failed — continuing with un-optimized images" >&2
    fi
fi

# ---------- 2 · validate ----------
# Library ingest is resource-only. Its blocking checks are the resource gate
# below plus package-ingest.sh and the slide-library candidate gate. Keep the
# page-quality validator for local/remote delivery, where it is still part of
# the presentation handoff contract.
if [ "$MODE" = "library" ]; then
    echo "  · skip page-quality validator (library resource-only) …"
else
    VALIDATE_STRICT="$STRICT"
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
        echo "FAIL_DOMAIN=page DO_NOT_EDIT_DECK=0" >&2
        exit 4
    fi
fi

if [ "$MODE" = "library" ]; then
    echo "  · check-only --resource-only (HTML) …"
    if ! run_step "check-only HTML resource gate" python3 "$SCRIPT_DIR/check-only.py" "$HTML" --resource-only; then
        echo "FAIL_DOMAIN=page DO_NOT_EDIT_DECK=0" >&2
        exit 6
    fi
fi

# ---------- 3 · mode-specific packaging ----------
case "$MODE" in
    local)
        echo ""
        echo "✓ ready (local) — same-workspace checkpoint:"
        echo "    $HTML"
        echo "FINALIZE_RESULT status=pass shape=local artifact=$HTML stop=true"
        ;;
    remote)
        echo "  · package-deliverable …"
        ZIP_ARGS=("$OUT_DIR")
        if [ -n "$NAME" ]; then
            ZIP_ARGS+=("--name" "$NAME")
        fi
        if ! run_step "package-deliverable" bash "$SCRIPT_DIR/package-deliverable.sh" "${ZIP_ARGS[@]}"; then
            echo "FAIL_DOMAIN=delivery DO_NOT_EDIT_DECK=1" >&2
            exit 5
        fi
        ZIP_NAME="${NAME:-deck-editable}"
        ZIP="$OUT_DIR/${ZIP_NAME}.zip"
        echo ""
        echo "✓ ready (remote) — attach this zip to your delivery:"
        echo "    $ZIP"
        echo "FINALIZE_RESULT status=pass shape=remote artifact=$ZIP stop=true"
        ;;
    library)
        echo "  · package-ingest …"
        if ! run_step "package-ingest" bash "$SCRIPT_DIR/package-ingest.sh" "$OUT_DIR" --deck-id "$DECK_ID"; then
            echo "FAIL_DOMAIN=delivery DO_NOT_EDIT_DECK=1" >&2
            exit 5
        fi
        ZIP="$OUT_DIR/deck.zip"
        echo "  · check-only --resource-only (deck.zip) …"
        if ! run_step "check-only ZIP resource gate" python3 "$SCRIPT_DIR/check-only.py" "$ZIP" --resource-only; then
            echo "FAIL_DOMAIN=delivery DO_NOT_EDIT_DECK=1" >&2
            exit 6
        fi
        echo ""
        echo "✓ ready (library) — upload this zip to feishu-slide-library:"
        echo "    $ZIP"
        echo "FINALIZE_RESULT status=pass shape=library artifact=$ZIP stop=true"
        ;;
esac
