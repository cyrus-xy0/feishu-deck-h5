#!/usr/bin/env bash
# pptx-to-html · run.sh — convert a .pptx into a feishu-deck-h5 HTML deck.
#
# Usage:
#   bash run.sh <in.pptx> <out-dir> [--limit N] [--raster] [--full-raster] [--inline]
#
# Renderer defaults to the sibling feishu-deck-h5 skill (../feishu-deck-h5),
# else ~/.claude/skills/feishu-deck-h5. Override with --renderer DIR.
#
# Python deps (python-pptx, Pillow, PyMuPDF): a venv at the skill root
# (skills/pptx-to-html/.venv) is used if present, else `python3` on PATH.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"          # assets/
SKILL="$(cd "$HERE/.." && pwd)"                              # skills/pptx-to-html
PY="python3"
for cand in "$SKILL/.venv/bin/python" "$HERE/.venv/bin/python"; do
    [[ -x "$cand" ]] && { PY="$cand"; break; }
done
exec "$PY" "$HERE/build_pptx.py" "$@"
