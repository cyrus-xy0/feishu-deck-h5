#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
PORT="${1:-8765}"
echo "==> http://localhost:$PORT/index.html"
python3 -m http.server "$PORT"
