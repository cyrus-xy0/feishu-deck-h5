#!/usr/bin/env bash
# migrate-shared-to-symlink.sh
#
# Convert runs/*/output/assets/shared from copied directories into symlinks
# pointing at the canonical skill assets/shared/. Reclaims per-run disk space.
#
# Idempotent: runs that are already on a symlink (or have no shared/) are
# skipped. The conversion is performed by re-invoking copy-assets.py in its
# default --shared=link mode, so the HTML refs and manifest are kept in sync.
#
# Usage:
#   bash skills/feishu-deck-h5/assets/migrate-shared-to-symlink.sh [--dry-run]

set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COPY_ASSETS="$SCRIPT_DIR/copy-assets.py"
[[ -f "$COPY_ASSETS" ]] || { echo "copy-assets.py not found at $COPY_ASSETS" >&2; exit 1; }

# Match new-run.sh: runs/ lives at the git toplevel; fall back to the fixed
# 3-up only for a non-git tree (the hardcoded depth broke when the skill was
# mounted / symlinked at a different depth).
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"
[[ -n "$REPO_ROOT" ]] || REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
RUNS="$REPO_ROOT/runs"
[[ -d "$RUNS" ]] || { echo "no runs/ at $RUNS — nothing to migrate"; exit 0; }

converted=0
skipped_symlink=0
skipped_missing=0
total_freed_kb=0

for shared in "$RUNS"/*/output/assets/shared; do
    [[ -e "$shared" ]] || continue
    output_dir="${shared%/assets/shared}"

    if [[ -L "$shared" ]]; then
        skipped_symlink=$((skipped_symlink + 1))
        continue
    fi
    if [[ ! -d "$shared" ]]; then
        skipped_missing=$((skipped_missing + 1))
        continue
    fi

    size_kb=$(du -sk "$shared" 2>/dev/null | awk '{print $1}'); [[ -n "$size_kb" ]] || size_kb=0
    echo "→ $output_dir (was ${size_kb} KB)"
    if [[ $DRY_RUN -eq 1 ]]; then
        echo "    (dry-run: would invoke copy-assets.py --shared=link)"
    else
        python3 "$COPY_ASSETS" "$output_dir" --shared=link >/dev/null
    fi
    converted=$((converted + 1))
    total_freed_kb=$((total_freed_kb + size_kb))
done

echo
if [[ $DRY_RUN -eq 1 ]]; then
    echo "Dry-run: $converted run(s) would be converted · ~$((total_freed_kb / 1024)) MB would be freed"
    echo "          $skipped_symlink already symlinked · $skipped_missing no shared/ dir"
else
    echo "Done. $converted run(s) converted · ~$((total_freed_kb / 1024)) MB freed"
    echo "      $skipped_symlink already symlinked · $skipped_missing no shared/ dir"
fi
