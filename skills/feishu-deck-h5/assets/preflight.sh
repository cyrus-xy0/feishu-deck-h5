#!/usr/bin/env bash
# feishu-deck-h5 · preflight check
# Verifies a local mount is present and writable before any skill action.
#
# Usage: bash assets/preflight.sh [--profile core|generate|edit|runtime-upgrade|pptx|publish|miaoda-publish|import|template] [--json]
#
# Exit codes:
#   0  OK — running from a writable mount OR successfully bootstrapped a
#      writable mirror of a read-only skill mount. Distinguish between the
#      two via stdout (see "stdout markers" below).
#   1  no mount detected / required skill files missing in source
#   2  read-only AND no writable area available for bootstrap
#   3  ephemeral session output only (/sessions/*/mnt/outputs/) — not allowed
#
# stdout markers (always on the first line of the success/fail message):
#   PREFLIGHT OK              skill root is writable, run skill from $SKILL_ROOT
#   PREFLIGHT BOOTSTRAPPED    skill root was RO; mirrored to a writable
#                             workspace — agent MUST cd into the printed
#                             workspace path before any further skill commands
#   PREFLIGHT FAIL · exit N   gated, do not proceed
#
# Why bootstrap exists: harnesses like Mira mount the skill read-only into
# /opt or similar. We can't write runs/<ts>/{input,output}/ next to assets/
# in that case. Instead we mirror the skill (minus runs/, caches, and *.bak)
# into $PWD/.feishu-deck-h5-workspace (override via FS_DECK_WORKSPACE env var),
# and tell the agent to cd there. All relative paths inside the skill (CSS link,
# template lookups, render.py) keep working.
#
# The mirror uses the fastest tool available and falls back to python3, which
# the skill already hard-requires to render — so it never hard-depends on
# rsync (minimal cloud images frequently lack it; that used to be a hard
# exit-2 death for any RO-mounted skill).
#
# This script is the LAST LINE of the skill's preflight. It's a hard gate;
# any non-zero exit means the agent must STOP and refuse to proceed.

set -e

PROFILE="generate"
JSON_OUTPUT=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --profile)
      [ "$#" -ge 2 ] || { echo "PREFLIGHT FAIL · exit 64 · --profile needs a value"; exit 64; }
      PROFILE="$2"; shift
      ;;
    --json) JSON_OUTPUT=1 ;;
    -h|--help)
      echo "usage: preflight.sh [--profile core|generate|edit|runtime-upgrade|pptx|publish|miaoda-publish|import|template] [--json]"
      exit 0
      ;;
    *) echo "PREFLIGHT FAIL · exit 64 · unknown option: $1"; exit 64 ;;
  esac
  shift
done
case "$PROFILE" in
  core|generate|edit|runtime-upgrade|pptx|publish|miaoda-publish|import|template) ;;
  *) echo "PREFLIGHT FAIL · exit 64 · unknown profile: $PROFILE"; exit 64 ;;
esac

PREFLIGHT_RESULT="failed"
if [ "$JSON_OUTPUT" -eq 1 ]; then
  trap '_rc=$?; if [ "$_rc" -eq 0 ]; then _ok=true; else _ok=false; fi; printf "{\"ok\":%s,\"profile\":\"%s\",\"result\":\"%s\",\"exit_code\":%s}\n" "$_ok" "$PROFILE" "$PREFLIGHT_RESULT" "$_rc"' EXIT
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---- Check 0: Python >= 3.10 (skill sources use PEP 604 `X | None` typing) ----
# The deck-json tools (render-deck.py, deck-cli.py, import-html-slide.py, …) use
# `X | None` type syntax, which raises TypeError at import time on Python 3.9.
# macOS ships /usr/bin/python3 = 3.9, so gate loudly here rather than let a core
# command crash cryptically later.
if command -v python3 >/dev/null 2>&1; then
  if ! python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)' 2>/dev/null; then
    PYVER="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo unknown)"
    echo "PREFLIGHT FAIL · exit 4 · python3 too old ($PYVER; need >= 3.10)"
    echo
    echo "  This skill's tools use \`X | None\` type syntax (PEP 604), which needs"
    echo "  Python 3.10+. Your default python3 is $PYVER (macOS ships 3.9)."
    echo
    echo "  Fix — install a newer Python and make sure \`python3\` resolves to it:"
    echo "    brew install python@3.11        # macOS"
    echo "    # then reopen your shell, or put it earlier on PATH"
    echo "  Verify: python3 --version  →  should print 3.10 or newer"
    exit 4
  fi
else
  echo "PREFLIGHT FAIL · exit 4 · python3 not found"
  echo
  echo "  This skill requires Python 3.10+ (render/validate/edit are all python3)."
  echo "  Install it (e.g. \`brew install python@3.11\`) and retry."
  exit 4
fi

# ---- Check 1: are we in ephemeral session output only? ----
case "$SKILL_ROOT" in
  */mnt/outputs|*/mnt/outputs/*)
    echo "PREFLIGHT FAIL · exit 3 · ephemeral session output detected"
    echo
    echo "  The skill is running from $SKILL_ROOT, which is an ephemeral"
    echo "  Cowork session output directory. Files here are wiped between"
    echo "  conversations and not visible in the user's editor or browser."
    echo
    echo "  REQUIRED: ask the user to mount their local working directory"
    echo "  via mcp__cowork__request_cowork_directory, then re-run from"
    echo "  inside that mounted folder."
    exit 3
    ;;
esac

# ---- Check 2: are we actually in any kind of mount? ----
# A non-Cowork user (running locally from a clone) will be at e.g.
# /Users/.../Projects/feishu-deck-h5 — that's a real mount.
# A Cowork user will be at /sessions/<id>/mnt/<folder-name>/feishu-deck-h5
# Both are valid; only /mnt/outputs/ is rejected.
if [[ -z "$SKILL_ROOT" ]]; then
  echo "PREFLIGHT FAIL · exit 1 · no skill root detected"
  exit 1
fi

# ---- Check 3: bootstrap contract present in source? ----
# Full capability files are machine-owned by dependency-policy.yaml and checked
# by check-profile.py below. These three files are the minimum needed to mirror
# and perform that authoritative profile check from the writable copy.
REQUIRED=(
  "SKILL.md"
  "assets/check-profile.py"
  "references/dependency-policy.yaml"
)
MISSING=()
for f in "${REQUIRED[@]}"; do
  if [[ ! -f "$SKILL_ROOT/$f" ]]; then
    MISSING+=("$f")
  fi
done
if [[ ${#MISSING[@]} -gt 0 ]]; then
  echo "PREFLIGHT FAIL · exit 1 · missing required skill files"
  echo
  echo "  Mount root: $SKILL_ROOT"
  echo "  Missing files:"
  for f in "${MISSING[@]}"; do echo "    - $f"; done
  echo
  echo "  Likely cause: the user mounted an empty folder. Either git-clone"
  echo "  the feishu-deck-h5 repo into the mount, or copy from"
  echo "  ~/.claude/skills/feishu-deck-h5/ if installed via plugin."
  exit 1
fi

# ---- Check 4: skill root writable, OR bootstrap a writable mirror ----
PROBE="$SKILL_ROOT/.feishu-deck-h5-preflight-$$"
if ! ( touch "$PROBE" 2>/dev/null && rm -f "$PROBE" 2>/dev/null ); then
  # ---- RO mount → bootstrap a writable workspace ----
  WORKSPACE="${FS_DECK_WORKSPACE:-$PWD/.feishu-deck-h5-workspace}"
  WORKSPACE_PARENT="$(dirname "$WORKSPACE")"
  WORKSPACE_PROBE="$WORKSPACE_PARENT/.feishu-deck-h5-bootstrap-probe-$$"
  if ! ( mkdir -p "$WORKSPACE_PARENT" 2>/dev/null && \
         touch "$WORKSPACE_PROBE" 2>/dev/null && \
         rm -f "$WORKSPACE_PROBE" 2>/dev/null ); then
    echo "PREFLIGHT FAIL · exit 2 · skill root read-only AND no writable bootstrap area"
    echo
    echo "  Skill root         : $SKILL_ROOT (RO)"
    echo "  Tried workspace at : $WORKSPACE (parent not writable)"
    echo
    echo "  Set FS_DECK_WORKSPACE=<writable-dir> and re-run, or mount the"
    echo "  skill RW so writes can land next to assets/."
    exit 2
  fi
  mkdir -p "$WORKSPACE"
  # Mirror the skill into the writable workspace. Try the fastest tool first,
  # fall back to python3 (guaranteed present — the skill can't render without
  # it). This removes the old hard dependency on rsync. Excludes keep the
  # mirror lean: runs/ (user outputs, preserved if already there), VCS/cache
  # cruft, editor noise, and *.bak snapshots — none are needed to RENDER a deck.
  # The active pptx-to-deck sibling is mirrored separately for pptx/template
  # profiles so readonly suite packages keep their dependency topology.
  MIRROR_OK=0
  MIRROR_TOOL=""
  if command -v rsync >/dev/null 2>&1; then
    if rsync -a --delete \
        --exclude='runs/' \
        --exclude='.git/' \
        --exclude='__pycache__' \
        --exclude='.pytest_cache' \
        --exclude='.DS_Store' \
        --exclude='*.bak*' \
        "$SKILL_ROOT/" "$WORKSPACE/" 2>/dev/null; then
      MIRROR_OK=1; MIRROR_TOOL="rsync"
    fi
  fi
  if [ "$MIRROR_OK" -eq 0 ] && command -v python3 >/dev/null 2>&1; then
    if SRC="$SKILL_ROOT" DST="$WORKSPACE" python3 - <<'PY'
import os, shutil, sys
src, dst = os.environ["SRC"], os.environ["DST"]
NAMES = {".git", "__pycache__", ".pytest_cache", ".DS_Store", "runs"}
def ignore(dirpath, names):
    skip = {n for n in names if n in NAMES or ".bak" in n}
    return skip
try:
    shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True, symlinks=True)
except Exception as e:
    print(f"python-mirror-failed: {e}", file=sys.stderr); sys.exit(1)
PY
    then
      MIRROR_OK=1; MIRROR_TOOL="python3"
    fi
  fi
  if [ "$MIRROR_OK" -eq 0 ]; then
    echo "PREFLIGHT FAIL · exit 2 · could not mirror RO skill to a writable area"
    echo
    echo "  Skill root: $SKILL_ROOT (RO)"
    echo "  Tried rsync and python3 — neither is available (or both failed)."
    echo "  Install python3 (or rsync), or mount the skill RW."
    exit 2
  fi

  PPTX_WORKSPACE=""
  PPTX_MIRROR_TOOL=""
  case "$PROFILE" in
    pptx|template)
      PPTX_SOURCE="$(cd "$SKILL_ROOT/../pptx-to-deck" 2>/dev/null && pwd || true)"
      if [ -n "$PPTX_SOURCE" ] && [ -f "$PPTX_SOURCE/SKILL.md" ]; then
        PPTX_WORKSPACE="$WORKSPACE_PARENT/pptx-to-deck"
        if [ -e "$PPTX_WORKSPACE" ] && [ ! -f "$PPTX_WORKSPACE/SKILL.md" ]; then
          echo "PREFLIGHT FAIL · exit 2 · sibling workspace path already contains unrelated data"
          echo "  Refusing to overwrite: $PPTX_WORKSPACE"
          echo "  Set FS_DECK_WORKSPACE so its parent can safely contain pptx-to-deck."
          exit 2
        fi
        mkdir -p "$PPTX_WORKSPACE"
        if command -v rsync >/dev/null 2>&1 && \
           rsync -a \
             --exclude='.venv/' --exclude='venv/' --exclude='__pycache__' \
             --exclude='.pytest_cache' --exclude='.DS_Store' --exclude='*.bak*' \
             --exclude='example/**/assets/' --exclude='example/**/sweep/' \
             "$PPTX_SOURCE/" "$PPTX_WORKSPACE/" 2>/dev/null; then
          PPTX_MIRROR_TOOL="rsync"
        elif SRC="$PPTX_SOURCE" DST="$PPTX_WORKSPACE" python3 - <<'PY'
import os, shutil, sys
src, dst = os.environ["SRC"], os.environ["DST"]
NAMES = {".venv", "venv", "__pycache__", ".pytest_cache", ".DS_Store"}
def ignore(dirpath, names):
    rel = os.path.relpath(dirpath, src)
    skip = {n for n in names if n in NAMES or ".bak" in n}
    if rel.startswith("example"):
        skip.update({n for n in names if n in {"assets", "sweep"}})
    return skip
try:
    shutil.copytree(src, dst, ignore=ignore, dirs_exist_ok=True, symlinks=True)
except Exception as exc:
    print(f"pptx-sibling-mirror-failed: {exc}", file=sys.stderr); sys.exit(1)
PY
        then
          PPTX_MIRROR_TOOL="python3"
        else
          echo "PREFLIGHT FAIL · exit 2 · could not mirror pptx-to-deck sibling"
          exit 2
        fi
      fi
      ;;
  esac
  # The mirror may inherit the source's RO perm bits (rsync -a preserves them;
  # copytree copies file modes too). Restore owner write/exec so the workspace
  # can accept runs/<ts>/ creation, edits, and validate-pass writes.
  chmod -R u+w "$WORKSPACE" ${PPTX_WORKSPACE:+"$PPTX_WORKSPACE"} 2>/dev/null || true
  echo "PREFLIGHT BOOTSTRAPPED"
  echo "  source (RO)    : $SKILL_ROOT"
  echo "  workspace (RW) : $WORKSPACE"
  echo "  mirrored via   : $MIRROR_TOOL"
  if [ -n "$PPTX_WORKSPACE" ]; then
    echo "  pptx sibling   : $PPTX_WORKSPACE (via $PPTX_MIRROR_TOOL)"
  fi
  echo "  ephemeral      : no"
  echo "  bootstrap      : ${#REQUIRED[@]}/${#REQUIRED[@]} files present (mirrored)"
  echo
  echo "  ACTION REQUIRED — agent MUST cd into the workspace before running"
  echo "  any further skill commands (new-run.sh, render.py, build.sh, etc.):"
  echo
  echo "    cd \"$WORKSPACE\""
  if [ -n "$PPTX_WORKSPACE" ]; then
    echo "    bash \"$PPTX_WORKSPACE/assets/bootstrap.sh\""
  fi
  echo
  echo "  All paths in SKILL.md become relative to the workspace once you cd."
  echo "  The runs/<ts>/output/ artifact will land in the workspace, where"
  echo "  the user (or harness) can pick it up for delivery."
  PREFLIGHT_RESULT="bootstrapped"
  exit 0
fi

# ---- Check 5: warn if another clone of the same repo lives elsewhere on disk ----
# This catches the "Claude Code mounted a session-storage copy, not the user's
# main GitHub clone" footgun: deck output lands in a folder the user can't
# easily find / commit / push from. Soft-warn (don't fail), and surface the
# competing paths so the agent can ask the user which one to use.
REPO_ROOT=""
if command -v git >/dev/null 2>&1; then
  REPO_ROOT="$(git -C "$SKILL_ROOT" rev-parse --show-toplevel 2>/dev/null || true)"
fi
if [ -n "$REPO_ROOT" ]; then
  CURRENT_REMOTE=$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || echo "")
  if [ -n "$CURRENT_REMOTE" ]; then
    # Identify directories by (device, inode) instead of path string, so the
    # comparison survives macOS APFS/HFS case-insensitivity (~/Documents/Github
    # vs ~/Documents/GitHub) and symlinks. `pwd -P` doesn't normalize case on
    # macOS, but inode IDs do.
    fs_id() {
      stat -f '%d:%i' "$1" 2>/dev/null \
        || stat -c '%d:%i' "$1" 2>/dev/null \
        || echo "$1"   # last-ditch fallback if neither stat flavor works
    }

    # ---- Cache layer ----
    # The cross-clone scan is `find -maxdepth 4` × 11 candidate roots,
    # which costs ~2-5s on Documents-heavy home dirs (slow disks worse).
    # Cache the result in `.feishu-deck-h5-preflight-cache` next to the
    # skill root, keyed on skill-root inode + git origin URL. Refresh
    # every 24h so newly-added clones eventually get noticed. Force a
    # fresh scan by deleting the file or setting FS_DECK_NOCACHE=1.
    PREFLIGHT_CACHE="${SKILL_ROOT}/.feishu-deck-h5-preflight-cache"
    PREFLIGHT_CACHE_MAX_AGE=86400
    SKILL_ROOT_ID="$(fs_id "$REPO_ROOT")"
    CACHE_KEY="${SKILL_ROOT_ID}|${CURRENT_REMOTE}"
    OTHER_CLONES=""
    USED_CACHE=0
    if [ -z "${FS_DECK_NOCACHE:-}" ] && [ -f "$PREFLIGHT_CACHE" ]; then
      cache_first_line="$(head -1 "$PREFLIGHT_CACHE" 2>/dev/null || echo "")"
      cache_mtime=$(stat -f %m "$PREFLIGHT_CACHE" 2>/dev/null \
                    || stat -c %Y "$PREFLIGHT_CACHE" 2>/dev/null || echo 0)
      cache_age=$(( $(date +%s) - cache_mtime ))
      if [ "$cache_first_line" = "$CACHE_KEY" ] \
         && [ "$cache_age" -lt "$PREFLIGHT_CACHE_MAX_AGE" ]; then
        USED_CACHE=1
        OTHER_CLONES="$(tail -n +2 "$PREFLIGHT_CACHE")"
      fi
    fi

    if [ "$USED_CACHE" = "0" ]; then
      # Search the most common dev locations on macOS / Linux. Bounded
      # depth keeps it from exploring the whole tree.
      SEARCH_ROOTS=(
        "$HOME/Documents/Github" "$HOME/Documents/GitHub"
        "$HOME/Documents"        "$HOME/Projects"
        "$HOME/GitHub"           "$HOME/Github"
        "$HOME/code"             "$HOME/Code"
        "$HOME/dev"              "$HOME/Dev"
        "$HOME/src"
      )
      SEEN_IDS=":"
      for root in "${SEARCH_ROOTS[@]}"; do
        [ -d "$root" ] || continue
        while IFS= read -r git_dir; do
          clone_dir="$(dirname "$git_dir")"
          clone_id="$(fs_id "$clone_dir")"
          # skip ourselves
          [ "$clone_id" = "$SKILL_ROOT_ID" ] && continue
          # dedupe — same physical dir reached via different SEARCH_ROOTS
          case "$SEEN_IDS" in *":$clone_id:"*) continue ;; esac
          SEEN_IDS="$SEEN_IDS$clone_id:"
          # check it's the same remote
          clone_remote=$(git -C "$clone_dir" remote get-url origin 2>/dev/null || echo "")
          if [ "$clone_remote" = "$CURRENT_REMOTE" ]; then
            OTHER_CLONES+="    - $clone_dir"$'\n'
          fi
        done < <(find "$root" -maxdepth 4 -type d -name '.git' 2>/dev/null)
      done
      # Write cache for next time (even if no other clones found —
      # cache the "no clones" answer too, so subsequent invocations
      # don't re-scan a clean home dir).
      printf '%s\n%s' "$CACHE_KEY" "$OTHER_CLONES" > "$PREFLIGHT_CACHE" 2>/dev/null || true
    fi

    if [ -n "$OTHER_CLONES" ]; then
      echo
      echo "WARNING · another clone of this repo lives on disk:"
      printf "%s" "$OTHER_CLONES"
      echo "  Current skill root  : $SKILL_ROOT"
      echo
      echo "  This means: outputs created here (runs/<ts>/, generated decks)"
      echo "  WILL NOT appear in the other clone(s). If the user usually"
      echo "  edits / commits from one of those, abort and re-run the skill"
      echo "  from inside that clone instead. Shared GitHub remote ≠ shared"
      echo "  filesystem — they're independent working directories."
      echo
      echo "  Agent: surface this to the user before creating the run folder."
      if [ "$USED_CACHE" = "1" ]; then
        echo "  (cached result, refreshes every 24h; set FS_DECK_NOCACHE=1 to force)"
      fi
    fi
  fi
fi

# ---- Check 6: audits.js syntax (gate before Playwright runs) ----
# UNIFY-VALIDATE-ARCH step 4: the SINGLE rule source is assets/audits.js (the
# old visual-audit.js was retired). Catch syntax errors at preflight time, not
# 30s later inside Chromium. `node --check` is a parse-only check (no execution),
# takes ~50ms. Skip silently if node isn't installed — the engine still parses
# via Playwright (its own JS engine), the gate is just a nice-to-have.
if command -v node >/dev/null 2>&1; then
  if ! node --check "$SKILL_ROOT/assets/audits.js" >/dev/null 2>&1; then
    echo "PREFLIGHT FAIL · exit 4 · audits.js has JS syntax errors"
    echo
    echo "  Run for details:"
    echo "    node --check $SKILL_ROOT/assets/audits.js"
    echo
    exit 4
  fi
fi

# ---- Check 7: profile capabilities (machine-owned dependency policy) ----
if ! python3 "$SKILL_ROOT/assets/check-profile.py" --profile "$PROFILE"; then
  echo "PREFLIGHT FAIL · exit 5 · capability profile '$PROFILE' is unavailable"
  exit 5
fi

# ---- Check 8: visual-audit capability probe (F-255) — informative for core/import ----
# The delivery quality gate (geometry / visual / distribution) runs the
# Playwright/Chromium engine. On a real (runs/) delivery render that engine is
# now REQUIRED — render-deck BLOCKS if it can't run (escape: DECK_ALLOW_NO_VISUAL=1).
# Surface that capability ONCE here so the agent knows up front whether the gate
# will be live or degraded. Informational only — NEVER changes preflight's exit
# code (a missing engine is a degraded-gate state, not a preflight failure). We
# probe the cheap `import playwright` (a real Chromium launch is ~1s — too slow
# for preflight); render-deck's own engine-down detection is the authoritative
# runtime check that actually blocks.
if python3 -c "import playwright" >/dev/null 2>&1; then
  echo "CAPABILITY visual-audit: ON"
else
  echo "CAPABILITY visual-audit: OFF — install: pip install playwright && python -m playwright install chromium (gates degrade to static-only; runs/ delivery will BLOCK unless DECK_ALLOW_NO_VISUAL=1)"
fi

# ---- Check 9: CJK preferred-font probe (F-283 step 1) — non-fatal ----
# The framework's CJK face (方正兰亭黑 Pro GB18030) is a LOCALLY-LICENSED font
# with NO @font-face / NO bundling, so visual-audit geometry (overflow / balance
# / title-position) is measured against whatever CJK face THIS host actually has.
# On a host missing the master font, Chromium falls back (Noto / PingFang / tofu)
# and the same deck measures DIFFERENTLY → a silent "passes here, fails there".
# Surface which CJK face this host would paint with so that source is VISIBLE.
# Informational only — NEVER changes preflight's exit code, NEVER swaps the font
# (full @font-face packaging is F-283 B, TBD). The font name list comes from
# assets/feishu-deck.css's --fs-font-cjk (read-only) so it stays in sync with
# the framework cascade.
if command -v fc-list >/dev/null 2>&1; then
  _cjk_names() {
    # Extract the --fs-font-cjk value (may span several lines) from the CSS,
    # split on commas, strip quotes/whitespace. CSS is the single source of truth.
    awk '/--fs-font-cjk:/{f=1} f{printf "%s ", $0; if(/;/){exit}}' \
        "$SKILL_ROOT/assets/feishu-deck.css" 2>/dev/null \
      | sed 's/.*--fs-font-cjk:[[:space:]]*//; s/;.*//' \
      | tr ',' '\n' \
      | sed 's/^[[:space:]]*//; s/[[:space:]]*$//; s/^"//; s/"$//' \
      | grep -v '^$'
  }
  _fam_installed() {
    # exact (case-insensitive) match of a CSS family name against installed
    # fc-list families. -a guards BSD grep treating CJK output as binary.
    fc-list --format='%{family}\n' 2>/dev/null | tr ',' '\n' \
      | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' \
      | grep -aqixF "$1"
  }
  _CJK_PREFERRED_PRESENT=0
  _CJK_FIRST_AVAIL=""
  while IFS= read -r _name; do
    [ -z "$_name" ] && continue
    # generics never count as the "actual face"
    case "$_name" in system-ui|sans-serif|serif|monospace) continue ;; esac
    if _fam_installed "$_name"; then
      [ -z "$_CJK_FIRST_AVAIL" ] && _CJK_FIRST_AVAIL="$_name"
      # all 方正兰亭黑 / FZLanTingHei* names are aliases of the licensed master
      case "$_name" in 方正兰亭黑*|FZLanTingHei*) _CJK_PREFERRED_PRESENT=1 ;; esac
    fi
  done < <(_cjk_names)
  if [ "$_CJK_PREFERRED_PRESENT" -eq 1 ]; then
    echo "CAPABILITY cjk-font: 方正兰亭黑 present"
  elif [ -n "$_CJK_FIRST_AVAIL" ]; then
    echo "CAPABILITY cjk-font: MISSING → 回落 $_CJK_FIRST_AVAIL (视觉几何与作者机器会有偏差; full packaging = F-283 B)"
  else
    echo "CAPABILITY cjk-font: MISSING → 无 CJK 回落字体, Chromium 将渲染 tofu (视觉几何与截图均失真; install fonts-noto-cjk)"
  fi
else
  echo "CAPABILITY cjk-font: UNKNOWN — fc-list (fontconfig) not installed; cannot verify CJK face (视觉几何依赖字体, 跨机器对比 verdict 前先核对字体)"
fi

# ---- All checks passed ----
echo "PREFLIGHT OK"
echo "  profile   : $PROFILE"
echo "  skill root: $SKILL_ROOT"
echo "  writable  : yes"
echo "  ephemeral : no"
echo "  bootstrap : ${#REQUIRED[@]}/${#REQUIRED[@]} files present"
PREFLIGHT_RESULT="ok"
exit 0
