#!/usr/bin/env bash
# pptx-to-deck · run.sh — convert a .pptx into a feishu-deck-h5 HTML deck.
#
# Emits a structured `layout:"canvas"` deck.json (data.elements[]) — no
# screenshots. (--raster/--full-raster are retired no-ops.)
#
# Usage:
#   bash run.sh <in.pptx> <out-dir> [--limit N] [--no-render] [--inline]
#
# Renderer defaults to the sibling feishu-deck-h5 skill (../feishu-deck-h5),
# else ~/.claude/skills/feishu-deck-h5. Override with --renderer DIR.
#
# Python deps (python-pptx, lxml): a venv at the skill root
# (skills/pptx-to-deck/.venv) is used if present, else `python3` on PATH.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"          # assets/
SKILL="$(cd "$HERE/.." && pwd)"                              # skills/pptx-to-deck
PY="python3"
for cand in "$SKILL/.venv/bin/python" "$HERE/.venv/bin/python"; do
    [[ -x "$cand" ]] && { PY="$cand"; break; }
done
exec "$PY" "$HERE/build_pptx.py" "$@"
