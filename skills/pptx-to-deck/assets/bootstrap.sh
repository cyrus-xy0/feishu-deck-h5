#!/usr/bin/env bash
# Create and verify the isolated Python runtime used by pptx-to-deck.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL="$(cd "$HERE/.." && pwd)"
VENV="${FS_DECK_PPTX_VENV:-$SKILL/.venv}"
BOOTSTRAP_PYTHON="${FS_DECK_PPTX_BOOTSTRAP_PYTHON:-python3}"

if [ ! -x "$VENV/bin/python3" ] && [ ! -x "$VENV/bin/python" ]; then
  echo "==> creating pptx-to-deck venv: $VENV"
  "$BOOTSTRAP_PYTHON" -m venv "$VENV"
fi

PY="$VENV/bin/python3"
[ -x "$PY" ] || PY="$VENV/bin/python"

if ! "$PY" -c 'import pptx, lxml' >/dev/null 2>&1; then
  echo "==> installing pptx-to-deck dependencies..."
  "$PY" -m pip install -r "$SKILL/requirements.txt"
fi

"$PY" -c 'import pptx, lxml'
echo "PPTX RUNTIME OK · $PY"
