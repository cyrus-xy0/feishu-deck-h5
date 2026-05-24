#!/usr/bin/env bash
# feishu-deck-h5 · preflight check
# Verifies a local mount is present and writable before any skill action.
#
# Usage: bash assets/preflight.sh
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
# in that case. Instead we rsync the whole skill (minus runs/, .git/) into
# $PWD/.feishu-deck-h5-workspace (override via FS_DECK_WORKSPACE env var),
# and tell the agent to cd there. All relative paths inside the skill (CSS
# link, template lookups, render.py) keep working unchanged.
#
# This script is the LAST LINE of the skill's preflight. It's a hard gate;
# any non-zero exit means the agent must STOP and refuse to proceed.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

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

# ---- Check 3: required asset files present in source? ----
# Done BEFORE the writable check so an empty/incomplete RO mount fails fast
# (rather than bootstrapping a broken mirror).
REQUIRED=(
  "assets/feishu-deck.css"
  "assets/feishu-deck.js"
  "assets/validate.py"
  "assets/visual-audit.js"
  "assets/lark-logo.png"
  "assets/lark-cover-bg.jpg"
  "_body.partial.html"
  "build.sh"
  "SKILL.md"
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
  if ! command -v rsync >/dev/null 2>&1; then
    echo "PREFLIGHT FAIL · exit 2 · rsync required to bootstrap RO mount"
    echo
    echo "  Skill root: $SKILL_ROOT (RO)"
    echo "  rsync isn't installed — can't mirror the skill to a writable area."
    echo "  Install rsync, or mount the skill RW."
    exit 2
  fi
  mkdir -p "$WORKSPACE"
  rsync -a --delete \
    --exclude='runs/' \
    --exclude='.git/' \
    --exclude='__pycache__' \
    --exclude='.DS_Store' \
    "$SKILL_ROOT/" "$WORKSPACE/"
  # rsync -a preserves source perms — including the very RO bits we're trying
  # to escape. Restore owner write/exec on the mirror so the workspace can
  # actually accept runs/<ts>/ creation, edits, and validate-pass writes.
  chmod -R u+w "$WORKSPACE"
  echo "PREFLIGHT BOOTSTRAPPED"
  echo "  source (RO)    : $SKILL_ROOT"
  echo "  workspace (RW) : $WORKSPACE"
  echo "  ephemeral      : no"
  echo "  files          : ${#REQUIRED[@]}/${#REQUIRED[@]} present (mirrored)"
  echo
  echo "  ACTION REQUIRED — agent MUST cd into the workspace before running"
  echo "  any further skill commands (new-run.sh, render.py, build.sh, etc.):"
  echo
  echo "    cd \"$WORKSPACE\""
  echo
  echo "  All paths in SKILL.md become relative to the workspace once you cd."
  echo "  The runs/<ts>/output/ artifact will land in the workspace, where"
  echo "  the user (or harness) can pick it up for delivery."
  exit 0
fi

# ---- Check 5: warn if another clone of the same repo lives elsewhere on disk ----
# This catches the "Claude Code mounted a session-storage copy, not the user's
# main GitHub clone" footgun: deck output lands in a folder the user can't
# easily find / commit / push from. Soft-warn (don't fail), and surface the
# competing paths so the agent can ask the user which one to use.
if command -v git >/dev/null 2>&1 && [ -d "$SKILL_ROOT/.git" ]; then
  CURRENT_REMOTE=$(git -C "$SKILL_ROOT" remote get-url origin 2>/dev/null || echo "")
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
    SKILL_ROOT_ID="$(fs_id "$SKILL_ROOT")"
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

# ---- Check 6: visual-audit.js syntax (gate before Playwright runs) ----
# 2026-05-24 · audit JS was extracted from validate.py r"""...""" string.
# Catch syntax errors at preflight time, not 30s later inside Chromium.
# `node --check` is a parse-only check (no execution), takes ~50ms.
# Skip silently if node isn't installed — the audit still works via
# Playwright (which has its own JS engine), the gate is just a nice-to-have.
if command -v node >/dev/null 2>&1; then
  if ! node --check "$SKILL_ROOT/assets/visual-audit.js" >/dev/null 2>&1; then
    echo "PREFLIGHT FAIL · exit 4 · visual-audit.js has JS syntax errors"
    echo
    echo "  Run for details:"
    echo "    node --check $SKILL_ROOT/assets/visual-audit.js"
    echo
    exit 4
  fi
fi

# ---- All checks passed ----
echo "PREFLIGHT OK"
echo "  skill root: $SKILL_ROOT"
echo "  writable  : yes"
echo "  ephemeral : no"
echo "  files     : ${#REQUIRED[@]}/${#REQUIRED[@]} present"
exit 0
