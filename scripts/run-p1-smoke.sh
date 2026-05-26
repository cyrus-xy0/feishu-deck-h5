#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BASE_URL="${GENERATOR_PUBLIC_BASE_URL:-http://127.0.0.1:8765}"

python3 -m py_compile server/generator.py server/feishu_bot.py server/slide_library.py
python3 server/slide_library.py validate
python3 evals/run-generator-contract.py
python3 evals/run-feishu-bot-contract.py

if curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then
  curl -fsS "${BASE_URL}/library/slides?query=%E9%A3%9E%E4%B9%A6&limit=3" >/dev/null
  echo "Live generator health and library API OK: ${BASE_URL}"
else
  echo "No live generator detected at ${BASE_URL}; offline contracts passed."
fi
