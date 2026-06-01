#!/usr/bin/env bash
# feishu-deck-h5 · build script
# Default mode produces a LINKED deck (CSS/JS/assets external, ~100 KB HTML).
# `--inline` mode produces a single self-contained file (~360 KB) for email/IM.
#
# Usage:
#   bash build.sh                     # default = linked, fast first paint
#   bash build.sh --inline            # single file, base64 assets inline
#   bash build.sh --validate          # also runs the self-check
#
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
INLINE=0
VALIDATE=0
SKIP_PREFLIGHT=0
for arg in "$@"; do
  case "$arg" in
    --inline)         INLINE=1 ;;
    --validate)       VALIDATE=1 ;;
    --skip-preflight) SKIP_PREFLIGHT=1 ;;   # CI / dev only — never in user flow
    *) ;;
  esac
done

# ---- Preflight: refuse to build in ephemeral / read-only mode ----
if [ "$SKIP_PREFLIGHT" = "0" ]; then
  if ! bash "$ROOT/assets/preflight.sh" >&2; then
    echo
    echo "BUILD ABORTED — preflight failed. Mount a local folder and re-run."
    echo "(For CI / dev, you may pass --skip-preflight to bypass.)"
    exit 1
  fi
fi

OUT_LINK="$ROOT/examples/sample-deck.html"
OUT_INLINE="$ROOT/examples/sample-deck-inline.html"

# ---- Build the linked version (default delivery) ----
{
  cat <<'HEAD'
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="fs-language" content="zh-en">
<title>先进团队的工作方式 · 飞书 2026 客户提案</title>
<link rel="stylesheet" href="../assets/feishu-deck.css">
<link rel="preload" as="image" href="../assets/lark-cover-bg.jpg">
<link rel="preload" as="image" href="../assets/lark-logo.png">
</head>
<body>
HEAD
  cat "$ROOT/_body.partial.html"
  echo '<script src="../assets/feishu-deck.js"></script></body></html>'
} > "$OUT_LINK"

# Patch the linked CSS so --fs-asset-* point to ../assets relative to examples/
# (the CSS already has the right relative paths from assets/ — examples/ → ../assets/ works)

# ---- Build the inlined version (opt-in single-file) ----
if [ "$INLINE" = "1" ] || [ "$VALIDATE" = "1" ]; then
  ASSET_OVERRIDE=$(python3 -c "
import base64, os
ROOT = '$ROOT/assets'
assets = [('logo','lark-logo.png','image/png'),('logo-mono','lark-logo-mono-white.png','image/png'),
          ('cover-bg','lark-cover-bg.jpg','image/jpeg'),('section-bg','lark-section-bg.jpg','image/jpeg'),
          ('content-bg','lark-content-bg.jpg','image/jpeg'),('slogan','lark-slogan.png','image/png')]
out = ':root {\n'
for k,fname,mime in assets:
    with open(os.path.join(ROOT, fname),'rb') as f:
        b = base64.b64encode(f.read()).decode('ascii')
    out += f'  --fs-asset-{k}: url(\"data:{mime};base64,{b}\");\n'
out += '}'
print(out)
")

  {
    echo '<!doctype html>'
    echo '<html lang="zh-CN">'
    echo '<head>'
    echo '<meta charset="utf-8">'
    echo '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
    echo '<title>先进团队的工作方式 · 飞书 2026 客户提案 (inline)</title>'
    echo '<meta name="fs-deck-mode" content="inline">'
    echo '<meta name="fs-language" content="zh-en">'
    echo '<style data-source="framework">'
    cat "$ROOT/assets/feishu-deck.css"
    echo
    echo "/* === Inlined brand assets (single-file delivery mode) === */"
    echo "$ASSET_OVERRIDE"
    echo '</style>'
    echo '</head><body>'
    python3 - "$OUT_LINK" <<'PY'
import re
import sys
from pathlib import Path

html = Path(sys.argv[1]).read_text(encoding='utf-8')
match = re.search(
    r'<body>\s*(.*?)\s*<script\s+src="../assets/feishu-deck\.js"></script></body>',
    html,
    re.S,
)
if not match:
    raise SystemExit('ERROR: cannot extract annotated body from linked sample deck')
print(match.group(1))
PY
    echo '<script data-source="framework">'
    cat "$ROOT/assets/feishu-deck.js"
    echo '</script></body></html>'
  } > "$OUT_INLINE"
fi

# ---- Build slide-recipes.html (also linked) ----
{
  echo '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
  echo '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
  echo '<meta name="fs-language" content="zh-en">'
  echo '<title>Slide recipes · feishu-deck-h5</title>'
  echo '<link rel="stylesheet" href="../assets/feishu-deck.css">'
  echo '</head><body>'
  cat "$ROOT/_body.partial.html"
  echo '<script src="../assets/feishu-deck.js"></script></body></html>'
} > "$ROOT/templates/slide-recipes.html"

echo "BUILD OK"
echo "  $OUT_LINK : $(stat -c %s "$OUT_LINK" 2>/dev/null || stat -f %z "$OUT_LINK") bytes (linked)"
if [ -f "$OUT_INLINE" ]; then
  echo "  $OUT_INLINE : $(stat -c %s "$OUT_INLINE" 2>/dev/null || stat -f %z "$OUT_INLINE") bytes (inlined)"
fi

# ---- Optional validation ----
if [ "$VALIDATE" = "1" ]; then
  echo
  echo "=== validate (default mode) ==="
  python3 "$ROOT/assets/validate.py" "$OUT_INLINE"
  echo
  echo "=== validate (--strict) ==="
  python3 "$ROOT/assets/validate.py" "$OUT_INLINE" --strict
fi
