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
# Python deps (python-pptx, lxml): FS_DECK_PPTX_PYTHON wins, then an explicit
# FS_DECK_PPTX_VENV, then the skill-local .venv, then `python3` on PATH.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"          # assets/
SKILL="$(cd "$HERE/.." && pwd)"                              # skills/pptx-to-deck
PY="${FS_DECK_PPTX_PYTHON:-python3}"
if [[ -z "${FS_DECK_PPTX_PYTHON:-}" ]]; then
    CANDIDATES=(
        "$SKILL/.venv/bin/python3"
        "$SKILL/.venv/bin/python"
        "$HERE/.venv/bin/python"
    )
    if [[ -n "${FS_DECK_PPTX_VENV:-}" ]]; then
        CANDIDATES=(
            "$FS_DECK_PPTX_VENV/bin/python3"
            "$FS_DECK_PPTX_VENV/bin/python"
            "${CANDIDATES[@]}"
        )
    fi
    for cand in "${CANDIDATES[@]}"; do
        [[ -x "$cand" ]] && { PY="$cand"; break; }
    done
fi
exec "$PY" "$HERE/build_pptx.py" "$@"
