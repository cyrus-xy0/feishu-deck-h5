#!/usr/bin/env bash
# bak-and-log.sh — thin wrapper around bak-and-log.py. Bash dispatch only,
# real logic lives in the Python script (cleaner cross-platform handling
# of multi-line markdown, retention pruning, and timestamp collisions).
#
# Usage:
#   bash bak-and-log.sh <file> <short-tag> "<description>"
#
# See bak-and-log.py header for full semantics + design rationale.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)" || { echo "ERROR: cannot resolve script dir" >&2; exit 1; }
exec python3 "$HERE/bak-and-log.py" "$@"
