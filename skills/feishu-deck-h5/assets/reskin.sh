#!/usr/bin/env bash
# feishu-deck-h5 · reskin mode (foreign HTML → feishu-skinned single-page deck)
#
# 用法:
#   bash assets/reskin.sh <input.html> [--slug SLUG] [--strict] [--no-visual]
#
# 流程:
#   1. PREFLIGHT (sanity check writable mount)
#   2. new-run.sh reskin-<slug>  → runs/<ts>-reskin-<slug>/{input,output}/
#   3. cp <input.html> → input/
#   4. reskin.py    → output/deck.json (layout:"raw" + per-page CSS)
#   5. render-deck.py     → output/index.html (auto wraps .deck/.slide-frame/.slide/.wordmark)
#   6. copy-assets.py     → bundle framework CSS/JS + brand assets
#   7. validate.py        → R10/R12/R20/R-WHITE-TEXT/etc. catch leftover issues
#
# 默认:
#   - 不开 --visual (raw layouts 经常 R-VIS-* warn, 需要人评估)
#   - 不开 --strict (foreign HTML 几乎不可能首跑全绿; warns 给用户作为修复指引)
#
# Exit codes:
#   0  reskin succeeded, output ready
#   1  bad args / input file missing
#   2  preflight failed (no writable mount)
#   3  reskin.py failed — including canvas-size mismatch (source ≠ 1920×1080).
#      Canvas check runs BEFORE any rewrites so we fail fast — saves a
#      render + screenshot cycle that ends in "the output looks small /
#      overlaps / has misplaced JS nodes". Fix: resize source to 1920×1080
#      native, OR use GENERATION mode for a full redesign.
#   4  render-deck.py failed
#   5  validate.py failed (errors — not warnings)

set -euo pipefail

# ──────────────────────────────────────────────────────── args

INPUT=""
SLUG=""
STRICT=""
# Visual audit default OFF: reskin is a mechanical chrome rewrite, NOT
# a content-design pass. Visual issues (overflow, label-floor on dense
# foreign content) are EXPECTED first-pass artifacts that need human
# iteration. Opt in with --visual for final-pass review.
VISUAL_FLAG="--no-visual"

KEEP_SOURCE_TYPO=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --slug)       SLUG="$2"; shift 2 ;;
    --strict)     STRICT="--strict"; shift ;;
    --visual)     VISUAL_FLAG="--visual"; shift ;;
    --no-visual)  VISUAL_FLAG="--no-visual"; shift ;;
    --keep-source-typography)  KEEP_SOURCE_TYPO="1"; shift ;;
    -h|--help)
      cat <<EOF
Usage: bash assets/reskin.sh <input.html> [--slug SLUG] [--strict] [--visual]

Args:
  <input.html>   Foreign HTML to reskin
  --slug SLUG    Slide-key slug (kebab-case). Defaults to input filename stem.
  --strict       Promote validator warnings to errors (final delivery)
  --visual       Also run Playwright visual audits (slow; many false positives on raw layouts)
EOF
      exit 0
      ;;
    *)
      if [[ -z "$INPUT" ]]; then
        INPUT="$1"
      else
        echo "✗ unexpected arg: $1" >&2
        exit 1
      fi
      shift
      ;;
  esac
done

if [[ -z "$INPUT" ]]; then
  echo "✗ missing <input.html>. Try --help." >&2
  exit 1
fi

if [[ ! -f "$INPUT" ]]; then
  echo "✗ input file not found: $INPUT" >&2
  exit 1
fi

# Absolute path of input (so cd later doesn't break it)
INPUT_ABS="$(cd "$(dirname "$INPUT")" && pwd)/$(basename "$INPUT")"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Derive slug from input filename if not provided
if [[ -z "$SLUG" ]]; then
  basename_noext="$(basename "$INPUT" .html)"
  basename_noext="${basename_noext%.htm}"
  # kebab-case, ascii-only, max 30 chars
  SLUG="$(echo "$basename_noext" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g' | cut -c1-30)"
  [[ -z "$SLUG" ]] && SLUG="reskin"
fi

echo "==> reskin: input=$INPUT_ABS slug=$SLUG"

# ──────────────────────────────────────────────────────── 1. PREFLIGHT

if ! bash "$SCRIPT_DIR/preflight.sh" >/dev/null 2>&1; then
  echo "✗ preflight failed — run 'bash assets/preflight.sh' for details" >&2
  exit 2
fi

# ──────────────────────────────────────────────────────── 2. new-run

# new-run.sh prints the run folder absolute path on its last stdout line.
RUN_DIR="$(bash "$SCRIPT_DIR/new-run.sh" "reskin-$SLUG" | tail -1)"
if [[ ! -d "$RUN_DIR" ]]; then
  echo "✗ new-run.sh did not produce a usable directory: $RUN_DIR" >&2
  exit 2
fi

OUT_DIR="$RUN_DIR/output"
IN_DIR="$RUN_DIR/input"

echo "==> run: $RUN_DIR"

# ──────────────────────────────────────────────────────── 3. cp input

cp "$INPUT_ABS" "$IN_DIR/"
INPUT_IN_RUN="$IN_DIR/$(basename "$INPUT_ABS")"

# ──────────────────────────────────────────────────────── 4. reskin.py

DECK_JSON="$OUT_DIR/deck.json"
echo "==> reskin.py → $DECK_JSON"
RESKIN_FLAGS=""
[[ -n "$KEEP_SOURCE_TYPO" ]] && RESKIN_FLAGS="--keep-source-typography"
if ! python3 "$SCRIPT_DIR/reskin.py" "$INPUT_IN_RUN" "$DECK_JSON" --slug "$SLUG" $RESKIN_FLAGS; then
  echo "✗ reskin.py failed" >&2
  exit 3
fi

# ──────────────────────────────────────────────────────── 5. render-deck.py

echo "==> render-deck.py → $OUT_DIR/index.html"
# render-deck.py only accepts --visual (no --no-visual; off is the default).
RENDER_VISUAL=""
[[ "$VISUAL_FLAG" == "--visual" ]] && RENDER_VISUAL="--visual"
if ! python3 "$SKILL_ROOT/deck-json/render-deck.py" "$DECK_JSON" "$OUT_DIR/" $RENDER_VISUAL; then
  echo "✗ render-deck.py failed (deck.json may have schema issues — inspect $DECK_JSON)" >&2
  exit 4
fi

# ──────────────────────────────────────────────────────── 6. copy-assets

echo "==> copy-assets.py (bundle framework CSS/JS into output/)"
python3 "$SCRIPT_DIR/copy-assets.py" "$OUT_DIR/" >/dev/null || {
  echo "! copy-assets warnings (non-fatal); inspect manually if needed" >&2
}

# ──────────────────────────────────────────────────────── 7. validate

echo "==> validate.py $STRICT $VISUAL_FLAG"
set +e
python3 "$SCRIPT_DIR/validate.py" "$OUT_DIR/index.html" $STRICT $VISUAL_FLAG
VALIDATE_EXIT=$?
set -e

if [[ $VALIDATE_EXIT -ne 0 && -n "$STRICT" ]]; then
  echo "✗ validator failed (strict mode). Fix the deck or re-run without --strict." >&2
  exit 5
fi

# ──────────────────────────────────────────────────────── 8. overflow check
# After snap pushes fonts to spec, source content designed for sub-floor
# sizes can spill past the 1080 boundary. Render in headless Chromium and
# enumerate any LEAF text past y=1080 — give the user actionable diagnostics
# (which element + how many px overflow) so they know what to fix in source.
echo "==> overflow check (post-render content vs 1080 boundary)"
python3 - <<'PYEOF' "$OUT_DIR/index.html"
import sys
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("  ! playwright not installed — skip overflow check", file=sys.stderr)
    sys.exit(0)
url = f"file://{sys.argv[1]}"
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    page.goto(url)
    page.wait_for_timeout(1500)
    items = page.evaluate("""() => {
        const slide = document.querySelector('.slide');
        if (!slide) return [];
        const out = [];
        slide.querySelectorAll('*').forEach(e => {
            if (e.children.length > 0) return;        // leaf-only
            const r = e.getBoundingClientRect();
            if (r.bottom > 1080.5) {
                out.push({
                    cls: (e.className || '').toString().substring(0, 32),
                    tag: e.tagName.toLowerCase(),
                    text: (e.textContent || '').trim().substring(0, 40),
                    bottom: Math.round(r.bottom),
                    overflow: Math.round(r.bottom - 1080),
                });
            }
        });
        return out;
    }""")
    browser.close()
if items:
    print(f"  ! content overflow past 1080 boundary (snapped fonts inflated heights):", file=sys.stderr)
    for it in items[:15]:
        print(f"    · {it['tag']}.{it['cls']:30} +{it['overflow']:3}px  \"{it['text']}\"",
              file=sys.stderr)
    if len(items) > 15:
        print(f"    · ... and {len(items)-15} more", file=sys.stderr)
    print(f"  Source content density too high for feishu spec font floors.", file=sys.stderr)
    print(f"  To fix: have source author reduce content by ~{max(it['overflow'] for it in items)}px vertical,", file=sys.stderr)
    print(f"  OR re-run reskin with --keep-source-typography (deviates from spec).", file=sys.stderr)
else:
    print(f"  ✓ no content overflow")
PYEOF

# ──────────────────────────────────────────────────────── done

cat <<EOF

──────── ✓ reskin done ────────
output:       $OUT_DIR/index.html
deck.json:    $DECK_JSON
input copy:   $INPUT_IN_RUN

Next:
  - open $OUT_DIR/index.html in a browser
  - edit deck.json (or texts.md if you want) and re-run render-deck.py
  - for single-file delivery, run: bash $SKILL_ROOT/build.sh  (or inline via render-deck.py --inline)
EOF
