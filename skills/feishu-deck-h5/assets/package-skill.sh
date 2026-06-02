#!/usr/bin/env bash
# feishu-deck-h5 · lean distribution packager
#
# What this is for:
#   Produce a SLIM, self-contained copy of the skill for installing onto a
#   cloud agent platform (Mira / Codex / internal harness). The working repo
#   is ~843 MB — but 689 MB of that is a single 60-page pptx EXAMPLE corpus
#   (6–11 MB images per slide) plus *.bak snapshots, __pycache__, and the
#   420 KB SKILL.md.bak. None of it is needed to RUN the skill. Shipping it
#   makes cloud install slow, flaky, and timeout-prone.
#
#   This script mirrors only the files the skill needs at runtime into a
#   staging dir and (by default) tars it up. Result is ~30–40 MB.
#
# Usage:
#   bash assets/package-skill.sh                 # → dist/feishu-deck-h5-<date>.tar.gz
#   bash assets/package-skill.sh /tmp/out        # custom output dir
#   bash assets/package-skill.sh --dir-only      # leave staged dir, skip tarball
#   bash assets/package-skill.sh --verify        # run check-mira.sh on the staged copy
#
# Exit codes:
#   0  OK — package produced (and verified, if --verify)
#   1  could not mirror / no python3 or rsync
#   2  --verify requested and the staged copy failed its self-check
#
# Mirror tool: tries rsync, falls back to python3 (guaranteed present — the
# skill can't render without it). Never hard-depends on rsync, matching
# preflight.sh's bootstrap.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

OUTDIR=""
DIR_ONLY=0
VERIFY=0
for arg in "$@"; do
  case "$arg" in
    --dir-only) DIR_ONLY=1 ;;
    --verify)   VERIFY=1 ;;
    -h|--help)
      sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    --*) echo "unknown flag: $arg" >&2; exit 1 ;;
    *)   OUTDIR="$arg" ;;
  esac
done
OUTDIR="${OUTDIR:-$SKILL_ROOT/dist}"

DATE="$(date +%Y%m%d)"
STAGE_NAME="feishu-deck-h5"
STAGE="$OUTDIR/$STAGE_NAME"

# du on an absolute path can report 0B under some sandboxes (macOS Seatbelt);
# `du -sh .` from inside the dir is reliable. Use a cd-relative helper.
dirsize() { ( cd "$1" 2>/dev/null && du -sh . 2>/dev/null | cut -f1 | tr -d ' ' ) || echo "?"; }

# ---- Exclude set — what NEVER ships in a distribution ----------------------
# (kept in sync with preflight.sh's bootstrap excludes, plus packaging-only
#  cruft: the packager's own dist/ output, the bootstrap workspace, and the
#  preflight scan cache.)
EXCLUDE_NAMES=(
  ".git" "__pycache__" ".pytest_cache" ".DS_Store" "runs" "dist"
  ".feishu-deck-h5-workspace" ".venv" "venv"
)
# rsync --exclude patterns (path/glob aware)
RSYNC_EXCLUDES=(
  --exclude='.git/'
  --exclude='__pycache__'
  --exclude='.pytest_cache'
  --exclude='.DS_Store'
  --exclude='runs/'
  --exclude='dist/'
  --exclude='.feishu-deck-h5-workspace/'
  --exclude='.feishu-deck-h5-preflight-cache'
  --exclude='*.bak*'
  --exclude='pptx-to-html/example/'
  --exclude='.venv/'
  --exclude='venv/'
  --exclude='*.pyc'
)

echo "=== feishu-deck-h5 · packaging a lean distribution ==="
echo "  source : $SKILL_ROOT"
echo "  staging: $STAGE"
SRC_SIZE="$(dirsize "$SKILL_ROOT")"
echo "  source size: $SRC_SIZE"
echo

rm -rf "$STAGE"
mkdir -p "$STAGE"

# ---- Mirror (rsync → python3 fallback) -------------------------------------
MIRROR_TOOL=""
if command -v rsync >/dev/null 2>&1; then
  if rsync -a "${RSYNC_EXCLUDES[@]}" "$SKILL_ROOT/" "$STAGE/" 2>/dev/null; then
    MIRROR_TOOL="rsync"
  fi
fi
if [ -z "$MIRROR_TOOL" ] && command -v python3 >/dev/null 2>&1; then
  if SRC="$SKILL_ROOT" DST="$STAGE" \
     EXCL="$(IFS=:; echo "${EXCLUDE_NAMES[*]}")" python3 - <<'PY'
import os, shutil, sys
src, dst = os.environ["SRC"], os.environ["DST"]
names = set(os.environ["EXCL"].split(":"))
def ignore(dirpath, entries):
    skip = {e for e in entries
            if e in names or ".bak" in e or e == ".feishu-deck-h5-preflight-cache"}
    if os.path.basename(dirpath) == "pptx-to-html" and "example" in entries:
        skip.add("example")
    return skip
try:
    shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True, symlinks=True)
except Exception as e:
    print(f"python-mirror-failed: {e}", file=sys.stderr); sys.exit(1)
PY
  then
    MIRROR_TOOL="python3"
  fi
fi
if [ -z "$MIRROR_TOOL" ]; then
  echo "FAIL · could not mirror skill (need rsync or python3)" >&2
  exit 1
fi
# Restore owner write/exec so the install target can run + accept runs/.
chmod -R u+w "$STAGE" 2>/dev/null || true

STAGE_SIZE="$(dirsize "$STAGE")"
FILE_COUNT="$(find "$STAGE" -type f | wc -l | tr -d ' ')"
echo "  mirrored via : $MIRROR_TOOL"
echo "  staged size  : $STAGE_SIZE  ($FILE_COUNT files)"

# ---- Optional self-check on the staged copy --------------------------------
if [ "$VERIFY" -eq 1 ]; then
  echo
  echo "--- verifying staged copy with check-mira.sh ---"
  if bash "$STAGE/assets/check-mira.sh" >/tmp/pkg-verify-$$.log 2>&1; then
    echo "  VERIFY OK — staged copy passes its harness self-check"
  else
    echo "  VERIFY FAIL — staged copy did not pass; full log:" >&2
    sed 's/^/    | /' /tmp/pkg-verify-$$.log >&2
    rm -f /tmp/pkg-verify-$$.log
    exit 2
  fi
  rm -f /tmp/pkg-verify-$$.log
  # check-mira / preflight write scratch INTO the staged copy during verify
  # (preflight cache + RO-mount workspace mirror). Strip it so the scratch
  # doesn't ship inside the distribution tarball. (#132)
  rm -rf "$STAGE/.feishu-deck-h5-preflight-cache" \
         "$STAGE/.feishu-deck-h5-workspace" 2>/dev/null || true
fi

# ---- Tarball ---------------------------------------------------------------
if [ "$DIR_ONLY" -eq 1 ]; then
  echo
  echo "✓ staged dir ready (no tarball, --dir-only): $STAGE"
  exit 0
fi

TARBALL="$OUTDIR/${STAGE_NAME}-${DATE}.tar.gz"
# Tar from OUTDIR so the archive root is a clean `feishu-deck-h5/` folder.
tar -czf "$TARBALL" -C "$OUTDIR" "$STAGE_NAME"
TAR_SIZE="$( ( cd "$OUTDIR" && du -sh "$(basename "$TARBALL")" 2>/dev/null | cut -f1 | tr -d ' ' ) || echo "?")"

echo
echo "✓ distribution package ready"
echo "  tarball : $TARBALL"
echo "  size    : $TAR_SIZE   (source was $SRC_SIZE)"
echo
echo "  Install on the target platform:"
echo "    tar -xzf $(basename "$TARBALL") -C <skills-dir>/"
echo "    bash <skills-dir>/feishu-deck-h5/assets/check-mira.sh   # verify env"
exit 0
