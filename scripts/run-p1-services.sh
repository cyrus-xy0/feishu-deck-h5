#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

GENERATOR_HOST="${GENERATOR_HOST:-127.0.0.1}"
GENERATOR_PORT="${GENERATOR_PORT:-8765}"
LOCAL_BASE_URL="http://${GENERATOR_HOST}:${GENERATOR_PORT}"
PUBLIC_BASE_URL="${GENERATOR_PUBLIC_BASE_URL:-$LOCAL_BASE_URL}"
LOG_DIR="${P1_LOG_DIR:-runs/p1-services}"

mkdir -p "$LOG_DIR"

echo "Starting generator on ${LOCAL_BASE_URL}"
python3 server/generator.py serve --host "$GENERATOR_HOST" --port "$GENERATOR_PORT" \
  >"${LOG_DIR}/generator.log" 2>"${LOG_DIR}/generator.err.log" &
GENERATOR_PID="$!"

cleanup() {
  if kill -0 "$GENERATOR_PID" >/dev/null 2>&1; then
    kill "$GENERATOR_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 30); do
  if curl -fsS "${LOCAL_BASE_URL}/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

curl -fsS "${LOCAL_BASE_URL}/health" >/dev/null
echo "Generator health OK"

echo "Running bot doctor for ${PUBLIC_BASE_URL}"
python3 server/feishu_bot.py doctor --base-url "$PUBLIC_BASE_URL" || true

echo "Starting Feishu bot event consumer"
GENERATOR_PUBLIC_BASE_URL="$PUBLIC_BASE_URL" python3 server/feishu_bot.py serve
