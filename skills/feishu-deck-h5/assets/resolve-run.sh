#!/usr/bin/env bash
# feishu-deck-h5  ·  resolve a run-output dir from a slug / partial name.
#
# Prints the absolute path to `runs/<...>/output` for the NEWEST run whose
# folder name contains <slug>. Delivery commands take a slug instead of a
# hand-typed `runs/<timestamp>-<slug>/output` path — this kills the broad
# filesystem `find` that an agent would otherwise run to locate the deck.
#
# Usage:
#     bash assets/resolve-run.sh <slug-or-partial>
#     DIR=$(bash assets/resolve-run.sh everbright) && echo "$DIR"
#
# Resolution order:
#   - If the arg is already an existing directory (a run dir or its output/),
#     it is echoed back as-is (so finalize.sh can pass slug OR path through).
#       · `<run>/output` exists  -> `<run>/output`
#       · `<run>` (has output/)  -> `<run>/output`
#       · any other existing dir -> the dir itself
#   - Otherwise treat the arg as a slug: search `./runs` (CWD) first, then the
#     skill repo root's `runs/` (where runs/ actually lives — it is gitignored
#     and absent inside worktrees). A run matches if its directory name
#     CONTAINS <slug>, case-insensitive, and has an `output/` child.
#   - 0 matches  -> exit 3 (not found), list searched roots on stderr.
#   - >1 matches -> pick the NEWEST by mtime, note the runner-up(s) on stderr.
#
# Exit codes: 0 ok / 2 bad args / 3 no match

set -euo pipefail

SLUG="${1:-}"
if [ -z "$SLUG" ]; then
    echo "usage: bash $(basename "$0") <slug-or-run-path>" >&2
    exit 2
fi

# ---- passthrough: arg is already a path on disk -------------------------
if [ -d "$SLUG" ]; then
    if [ -d "$SLUG/output" ]; then
        ( cd "$SLUG/output" && pwd )
    else
        ( cd "$SLUG" && pwd )
    fi
    exit 0
fi

# ---- slug resolution ----------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# assets -> feishu-deck-h5 -> skills -> <repo-root>  (runs/ lives at repo root)
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Candidate runs roots, de-duplicated, in priority order: CWD first.
declare -a ROOTS=()
add_root() { local r="$1"; [ -d "$r" ] || return 0; for e in "${ROOTS[@]:-}"; do [ "$e" = "$r" ] && return 0; done; ROOTS+=("$r"); }
add_root "$(pwd)/runs"
add_root "$REPO_ROOT/runs"

shopt -s nocaseglob nullglob

declare -a MATCHES=()
for root in "${ROOTS[@]:-}"; do
    for d in "$root"/*"$SLUG"*/; do
        [ -d "${d}output" ] || continue
        MATCHES+=("${d%/}")
    done
done

shopt -u nocaseglob nullglob

if [ "${#MATCHES[@]}" -eq 0 ]; then
    echo "✗ no run matches slug '$SLUG'." >&2
    echo "  searched: ${ROOTS[*]:-<none>}" >&2
    echo "  (a match is runs/*${SLUG}*/ containing an output/ folder)" >&2
    exit 3
fi

# Run folders are named runs/<YYYYMMDD-HHMMSS>-<slug>/, so a DESCENDING sort by
# basename is chronological — newest first. This is deterministic, unlike
# filesystem mtime (which edits/`touch` perturb and which ties at 1s resolution).
declare -a ORDERED=()
while IFS= read -r p; do
    [ -n "$p" ] && ORDERED+=("$p")
done < <(
    for m in "${MATCHES[@]}"; do printf '%s\t%s\n' "$(basename "$m")" "$m"; done \
        | sort -r | cut -f2-
)
NEWEST="${ORDERED[0]}"

if [ "${#ORDERED[@]}" -gt 1 ]; then
    echo "ℹ️  ${#ORDERED[@]} runs match '$SLUG' — picking newest:" >&2
    for p in "${ORDERED[@]}"; do
        mark="  "; [ "$p" = "$NEWEST" ] && mark="→ "
        echo "${mark}${p}" >&2
    done
fi

( cd "$NEWEST/output" && pwd )
