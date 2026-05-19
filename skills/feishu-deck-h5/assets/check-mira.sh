#!/usr/bin/env bash
# feishu-deck-h5 · Mira (and any agent-harness) self-check
#
# What this is for:
#   Verify an agent runner (Mira / Codex / Claude Code / etc) has the
#   environment + filesystem permissions + tooling this skill needs.
#   Pure sanity check — no LLM calls, no token cost, ~5 s to run.
#
# Usage:
#   bash skills/feishu-deck-h5/assets/check-mira.sh
#
# Exit codes:
#   0 — all 7 checks passed (or only optional checks warned)
#   1 — at least one MANDATORY check failed; the harness can't run this skill
#       reliably until the failure is fixed
#
# What it does NOT check:
#   - LLM context-length handling     (harness-specific, can't test from shell)
#   - LLM tool-calling correctness    (needs a real agent invocation)
#   - End-to-end deck generation      (covered by examples/* + render.py;
#                                      this script only dry-runs the validator)
#   - Network reachability for Lark APIs (depends on user auth + corp network)

# Don't use `set -e` — we want every check to run independently so the user
# sees the full diagnostic in one go.
set +e
set -o pipefail

# ---- Paths ----------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$SKILL_ROOT/.." 2>/dev/null && pwd || echo "$SKILL_ROOT")"
# If skills/<name>/ layout, climb one more level to repo root
if [ -d "$REPO_ROOT/skills" ] && [ -d "$REPO_ROOT/skills/feishu-deck-h5" ]; then
  : # already at repo root
elif [ -d "$REPO_ROOT/../skills/feishu-deck-h5" ]; then
  REPO_ROOT="$(cd "$REPO_ROOT/.." && pwd)"
fi

# ---- TTY-aware colors -----------------------------------------------------
if [ -t 1 ] && command -v tput >/dev/null 2>&1; then
  C_OK=$(tput setaf 2)      # green
  C_FAIL=$(tput setaf 1)    # red
  C_WARN=$(tput setaf 3)    # yellow
  C_DIM=$(tput dim)
  C_BOLD=$(tput bold)
  C_RESET=$(tput sgr0)
else
  C_OK=""; C_FAIL=""; C_WARN=""; C_DIM=""; C_BOLD=""; C_RESET=""
fi

# ---- State ----------------------------------------------------------------
TOTAL_GROUPS=7
PASSED_GROUPS=0
FAIL_COUNT=0
WARN_COUNT=0
CURRENT_GROUP_FAILED=0

mark_ok()   { printf '  %sOK%s   %s\n'   "$C_OK"   "$C_RESET" "$1"; }
mark_fail() { printf '  %sFAIL%s %s\n'   "$C_FAIL" "$C_RESET" "$1"; FAIL_COUNT=$((FAIL_COUNT+1)); CURRENT_GROUP_FAILED=1; }
mark_warn() { printf '  %sWARN%s %s\n'   "$C_WARN" "$C_RESET" "$1"; WARN_COUNT=$((WARN_COUNT+1)); }
mark_skip() { printf '  %sSKIP%s %s\n'   "$C_DIM"  "$C_RESET" "$1"; }

group_start() {
  CURRENT_GROUP_FAILED=0
  printf '\n%s[%d/%d] %s%s\n' "$C_BOLD" "$1" "$TOTAL_GROUPS" "$2" "$C_RESET"
}
group_end() {
  if [ "$CURRENT_GROUP_FAILED" -eq 0 ]; then
    PASSED_GROUPS=$((PASSED_GROUPS+1))
  fi
}

# ---- Header ---------------------------------------------------------------
printf '%s=== feishu-deck-h5 · harness self-check ===%s\n' "$C_BOLD" "$C_RESET"
printf '  skill root : %s\n' "$SKILL_ROOT"
printf '  repo root  : %s\n' "$REPO_ROOT"
printf '  date       : %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')"
printf '  shell      : %s\n' "$BASH_VERSION"
printf '  uname      : %s\n' "$(uname -srm)"

# ─────────────────────────────────────────────────────────────────────────
# Check 1 · SKILL.md frontmatter (description ≤ 1024 for Codex/Mira)
# ─────────────────────────────────────────────────────────────────────────
group_start 1 "SKILL.md frontmatter"
SKILL_MD="$SKILL_ROOT/SKILL.md"
if [ ! -f "$SKILL_MD" ]; then
  mark_fail "SKILL.md not found at $SKILL_MD"
else
  fm_out=$(SKILL_MD_PATH="$SKILL_MD" python3 - <<'PY'
import os, re, pathlib, sys
try:
    import yaml
except ImportError:
    print("PYYAML_MISSING"); sys.exit(0)
text = pathlib.Path(os.environ["SKILL_MD_PATH"]).read_text(encoding="utf-8")
m = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
if not m:
    print("NO_FRONTMATTER"); sys.exit(0)
fm = yaml.safe_load(m.group(1))
print(f"NAME={fm.get('name','')}")
print(f"DESC_LEN={len(fm.get('description',''))}")
PY
  )
  if echo "$fm_out" | grep -q PYYAML_MISSING; then
    mark_warn "PyYAML not installed — skipping deep parse (pip install pyyaml to enable)"
  elif echo "$fm_out" | grep -q NO_FRONTMATTER; then
    mark_fail "SKILL.md has no YAML frontmatter"
  else
    name=$(echo "$fm_out" | grep '^NAME=' | cut -d= -f2)
    desc_len=$(echo "$fm_out" | grep '^DESC_LEN=' | cut -d= -f2)
    if [ "$name" != "feishu-deck-h5" ]; then
      mark_fail "frontmatter name='$name' (expected 'feishu-deck-h5')"
    else
      mark_ok "name = $name"
    fi
    if [ -z "$desc_len" ] || [ "$desc_len" -gt 1024 ]; then
      mark_fail "description $desc_len chars > 1024 (Codex/Mira limit)"
    elif [ "$desc_len" -lt 100 ]; then
      mark_warn "description only $desc_len chars — may be too terse for harnesses' triggering"
    else
      mark_ok "description $desc_len chars (limit 1024, headroom $((1024 - desc_len)))"
    fi
  fi
fi
group_end

# ─────────────────────────────────────────────────────────────────────────
# Check 2 · Preflight (skill mount writable OR bootstrappable)
# ─────────────────────────────────────────────────────────────────────────
group_start 2 "Preflight mount"
PREFLIGHT_OUT=$(bash "$SKILL_ROOT/assets/preflight.sh" 2>&1)
PREFLIGHT_EXIT=$?
if [ "$PREFLIGHT_EXIT" -eq 0 ] && echo "$PREFLIGHT_OUT" | grep -q 'PREFLIGHT OK'; then
  mark_ok "skill root writable (PREFLIGHT OK)"
elif [ "$PREFLIGHT_EXIT" -eq 0 ] && echo "$PREFLIGHT_OUT" | grep -q 'PREFLIGHT BOOTSTRAPPED'; then
  ws=$(echo "$PREFLIGHT_OUT" | grep -oE 'workspace.*: [^ ]+' | head -1 | awk -F': ' '{print $NF}')
  mark_ok "skill root RO, bootstrapped to writable workspace ($ws)"
else
  mark_fail "preflight failed (exit $PREFLIGHT_EXIT)"
  echo "$PREFLIGHT_OUT" | sed 's/^/      | /' | head -10
fi
group_end

# ─────────────────────────────────────────────────────────────────────────
# Check 3 · Runtime deps (python3, git, gh, pip3, optionally playwright)
# ─────────────────────────────────────────────────────────────────────────
group_start 3 "Runtime deps"
if command -v python3 >/dev/null 2>&1; then
  pv=$(python3 --version 2>&1)
  mark_ok "python3 ............ $pv"
else
  mark_fail "python3 ............ not found (required for validate.py / render.py)"
fi

if command -v git >/dev/null 2>&1; then
  gv=$(git --version 2>&1 | head -1)
  mark_ok "git ................ $gv"
else
  mark_fail "git ................ not found (skill repo workflows need git)"
fi

if command -v gh >/dev/null 2>&1; then
  ghv=$(gh --version 2>&1 | head -1)
  if gh auth status >/dev/null 2>&1; then
    mark_ok "gh + auth .......... $ghv (logged in)"
  else
    mark_warn "gh ................. $ghv (not logged in — needed for PR / publish flows)"
  fi
else
  mark_skip "gh ................. not installed (optional; only needed if you push from agent)"
fi

if python3 -c "import yaml" 2>/dev/null; then
  mark_ok "pyyaml ............. installed"
else
  mark_warn "pyyaml ............. missing (pip install pyyaml — needed for check-only.py + this script's deep frontmatter parse)"
fi

if python3 -c "import playwright" 2>/dev/null; then
  mark_ok "playwright ......... installed (visual validator R-VIS-* enabled)"
else
  mark_skip "playwright ......... not installed (optional; visual audits R-OVERFLOW / R-VIS-TIER / R-VIS-HIER will skip)"
fi
group_end

# ─────────────────────────────────────────────────────────────────────────
# Check 4 · runs/ writable (sanity test_run, then cleanup)
# ─────────────────────────────────────────────────────────────────────────
group_start 4 "runs/ writable"
TEST_SLUG="harness-self-check-$$"
NEW_RUN_OUT=$(bash "$SKILL_ROOT/assets/new-run.sh" "$TEST_SLUG" 2>&1)
NEW_RUN_EXIT=$?
if [ "$NEW_RUN_EXIT" -ne 0 ]; then
  mark_fail "new-run.sh failed (exit $NEW_RUN_EXIT)"
  echo "$NEW_RUN_OUT" | sed 's/^/      | /' | head -10
else
  # Extract the absolute run path (last line of new-run.sh stdout)
  RUN_PATH=$(echo "$NEW_RUN_OUT" | tail -1)
  if [ -d "$RUN_PATH/input" ] && [ -d "$RUN_PATH/output" ]; then
    mark_ok "new-run.sh created  $(basename "$RUN_PATH")/"
    # Write a small probe file in output/
    probe="$RUN_PATH/output/probe.txt"
    echo "harness-self-check probe" > "$probe" 2>/dev/null
    if [ -f "$probe" ]; then
      mark_ok "output/ writable + readable"
    else
      mark_fail "output/ NOT writable (filesystem permission issue)"
    fi
    # Cleanup
    rm -rf "$RUN_PATH" 2>/dev/null
    if [ ! -d "$RUN_PATH" ]; then
      mark_ok "cleanup successful"
    else
      mark_warn "cleanup left files at $RUN_PATH (rm permission issue?)"
    fi
  else
    mark_fail "new-run.sh did not create input/ + output/ subdirs"
  fi
fi
group_end

# ─────────────────────────────────────────────────────────────────────────
# Check 5 · Framework assets present + readable
# ─────────────────────────────────────────────────────────────────────────
group_start 5 "Framework assets"
ASSETS=(
  "assets/feishu-deck.css"
  "assets/feishu-deck.js"
  "assets/validate.py"
  "assets/preflight.sh"
  "assets/new-run.sh"
  "assets/finalize.sh"
  "assets/lark-logo.png"
  "assets/lark-cover-bg.jpg"
  "assets/lark-slogan.png"
  "templates/_shell.html"
  "templates/slide-recipes.html"
)
for rel in "${ASSETS[@]}"; do
  full="$SKILL_ROOT/$rel"
  if [ -r "$full" ]; then
    size=$(wc -c < "$full" 2>/dev/null | tr -d ' ')
    if [ -n "$size" ] && [ "$size" -gt 0 ]; then
      hsize=$(numfmt --to=iec "$size" 2>/dev/null || echo "${size} B")
      mark_ok "$rel ($hsize)"
    else
      mark_warn "$rel exists but is empty"
    fi
  else
    mark_fail "$rel MISSING or unreadable"
  fi
done
group_end

# ─────────────────────────────────────────────────────────────────────────
# Check 6 · Validator dry-run on examples/sample-deck.html
# ─────────────────────────────────────────────────────────────────────────
group_start 6 "Validator dry-run"
SAMPLE="$SKILL_ROOT/examples/sample-deck.html"
if [ ! -f "$SAMPLE" ]; then
  mark_warn "examples/sample-deck.html not present (skip — generate with bash build.sh)"
else
  VAL_OUT=$(python3 "$SKILL_ROOT/assets/validate.py" "$SAMPLE" --no-visual 2>&1)
  VAL_EXIT=$?
  # Check the harness can run the validator — NOT whether sample-deck.html passes.
  # A python ImportError / FileNotFoundError / syntax error = harness can't run skill.
  # Validator finding deck errors = pre-existing, not a harness issue.
  if echo "$VAL_OUT" | grep -qE 'slides:\s+[0-9]+'; then
    errors=$(echo "$VAL_OUT" | grep -oE 'errors:\s+[0-9]+' | grep -oE '[0-9]+' | head -1)
    warns=$(echo "$VAL_OUT" | grep -oE 'warnings:\s+[0-9]+'  | grep -oE '[0-9]+' | head -1)
    mark_ok "validate.py runs and produces structured output ($errors errors, $warns warnings on sample)"
    if [ "${errors:-0}" -gt 0 ]; then
      mark_warn "sample deck has $errors validator errors — pre-existing in this repo, not a harness problem"
    fi
  elif echo "$VAL_OUT" | grep -qiE 'ModuleNotFoundError|ImportError|SyntaxError|FileNotFoundError'; then
    mark_fail "validate.py crashed (Python error — missing dep or broken install)"
    echo "$VAL_OUT" | tail -10 | sed 's/^/      | /'
  else
    mark_fail "validate.py produced no structured output (unexpected)"
    echo "$VAL_OUT" | tail -10 | sed 's/^/      | /'
  fi
fi
group_end

# ─────────────────────────────────────────────────────────────────────────
# Check 7 · Git ops (status, rev-parse, optional gh remote check)
# ─────────────────────────────────────────────────────────────────────────
group_start 7 "Git"
if ! command -v git >/dev/null 2>&1; then
  mark_skip "git not installed (covered in check 3)"
else
  if (cd "$REPO_ROOT" && git rev-parse --git-dir >/dev/null 2>&1); then
    if (cd "$REPO_ROOT" && git status --short >/dev/null 2>&1); then
      mark_ok "git status works"
    else
      mark_fail "git status failed"
    fi
    head_sha=$(cd "$REPO_ROOT" && git rev-parse --short HEAD 2>/dev/null)
    if [ -n "$head_sha" ]; then
      mark_ok "git HEAD = $head_sha"
    else
      mark_warn "git rev-parse HEAD failed (no commits?)"
    fi
    remote=$(cd "$REPO_ROOT" && git remote get-url origin 2>/dev/null)
    if [ -n "$remote" ]; then
      mark_ok "origin = $remote"
    else
      mark_warn "no origin remote configured"
    fi
  else
    mark_skip "$REPO_ROOT is not a git repo (skill not cloned via git)"
  fi
fi
group_end

# ─────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────
printf '\n──────────────────────────────────\n'
if [ "$FAIL_COUNT" -eq 0 ]; then
  printf '%s✓ %d/%d groups OK%s · %d warnings · this harness can run feishu-deck-h5\n' \
    "$C_OK" "$PASSED_GROUPS" "$TOTAL_GROUPS" "$C_RESET" "$WARN_COUNT"
  if [ "$WARN_COUNT" -gt 0 ]; then
    printf '%s  (warnings above are non-blocking — review them if features feel missing)%s\n' "$C_DIM" "$C_RESET"
  fi
  exit 0
else
  printf '%s✗ %d/%d groups OK%s · %d failures · %d warnings\n' \
    "$C_FAIL" "$PASSED_GROUPS" "$TOTAL_GROUPS" "$C_RESET" "$FAIL_COUNT" "$WARN_COUNT"
  printf '\nWhat to send to the skill maintainer:\n'
  printf '  · full stdout of this script\n'
  printf '  · harness name + version (e.g. "Mira v0.4.2", "Codex 0.18")\n'
  printf '  · OS / shell (already in header above)\n'
  exit 1
fi
