#!/usr/bin/env bash
# Backward-compatible wrapper for the conservative run compactor.
#
# Historical behavior applied by default; keep that CLI contract for callers
# that already invoke this script. New automation should call compact-runs.py
# directly, whose default is a dry run and whose --apply flag is explicit.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPACTOR="$SCRIPT_DIR/compact-runs.py"
[[ -f "$COMPACTOR" ]] || {
  echo "compact-runs.py not found at $COMPACTOR" >&2
  exit 1
}

REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
[[ -n "$REPO_ROOT" ]] || REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
RUNS="$REPO_ROOT/runs"

case "${1:-}" in
  --dry-run)
    exec python3 "$COMPACTOR" "$RUNS"
    ;;
  "")
    exec python3 "$COMPACTOR" "$RUNS" --apply
    ;;
  *)
    echo "usage: bash $(basename "$0") [--dry-run]" >&2
    exit 2
    ;;
esac
