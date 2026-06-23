#!/usr/bin/env python3
"""
feishu-deck-h5 · Claude Code PreToolUse(Bash) guard — deny ad-hoc deck.json extraction

WHAT THIS IS
  A Claude-Code PreToolUse hook (matcher: Bash) that DENIES the anti-pattern of
  reading a feishu-deck deck.json with an ad-hoc `json.load(...)` / `jq` instead of
  the sanctioned deck-cli.py path. The deny reason points the model at the surgical
  recipe (deck-cli.py get-page / set / set --from-file). Ad-hoc extraction is
  brittle (it guesses the schema shape) and was a measured contributor to the
  re-archaeology slowdown the end-to-end latency audit flagged.

WHAT IT DENIES — deck.json must be the OPERAND of the json.load / jq, not merely
co-present in the command:
  - python:  json.load(open("…/deck.json"))  ·  json.loads(Path("…/deck.json").read_text())
  - jq:      jq '…' …/deck.json  ·  jq … < …/deck.json  ·  cat …/deck.json | jq
  It does NOT deny a compound command that mentions a deck.json path elsewhere while
  json.load/jq operates on a DIFFERENT file (e.g. a pairs.json) — the matcher
  requires the deck.json to be the operand. (This is the tightening over the first
  version, which blocked on mere co-occurrence and produced a real false positive.)

ALWAYS ALLOWED
  The sanctioned deck tools (deck-cli / render-deck / deck-map / locate-slide /
  import-html-slide / extract-text-pairs / lift-to-new-deck / lift-translate-page),
  even when their command names deck.json and pipes their JSON output to jq.

DESIGN RULE: never break the session on an internal error — any parse failure →
allow (a PreToolUse hook allows by emitting nothing / exit 0).

INSTALL (Claude Code only)
  1. Copy this file to a stable location, e.g.
     ~/.claude/hooks/feishu-deck-deny-extract.py, and chmod +x.
  2. Register in ~/.claude/settings.json under hooks.PreToolUse with matcher "Bash":
       {"hooks": {"PreToolUse": [
         {"matcher": "Bash", "hooks": [{"type": "command",
           "command": "python3 /ABSOLUTE/PATH/feishu-deck-deny-extract.py"}]}]}}
  To run a genuine cross-page batch analysis deck-cli cannot cover, temporarily
  disable this hook in settings.json.
"""
import sys, json, re


def allow():
    sys.exit(0)  # no output on PreToolUse == allow


try:
    data = json.load(sys.stdin)
except Exception:
    allow()

cmd = ((data.get("tool_input") or {}).get("command")) or ""
if "deck.json" not in cmd:
    allow()

# Never block the sanctioned deck tools (their command line legitimately names
# deck.json, and may pipe their JSON output to jq — that's fine).
if re.search(r"(deck-cli|render-deck|deck-map|locate-slide|import-html-slide"
             r"|extract-text-pairs|lift-to-new-deck|lift-translate-page)\.py", cmd):
    allow()

# Deny only when deck.json is the OPERAND of an ad-hoc json.load / jq — not merely
# co-present in a compound command whose json.load/jq targets another file. This is
# strictly NARROWER than co-occurrence, so it can only reduce false positives.
DENY = (
    r"json\.loads?\s*\([^)]*deck\.json"      # json.load(open("…deck.json")) / json.loads(Path("…deck.json")…)
    r"|\bjq\b[^|]*deck\.json"                 # jq … deck.json   (incl. jq … < deck.json)
    r"|deck\.json[^|]*\|[^|]*\bjq\b"          # cat deck.json | … | jq
)
if re.search(DENY, cmd):
    reason = (
        "已拦截:别用临时 json.load / jq 直接扒 deck.json(反模式,也是上次变慢的根因之一)。"
        "改用 deck-cli.py 的外科配方——"
        "读某页内容: deck-json/deck-cli.py <deck.json> get-page <key|#N> --html|--css；"
        "改一个值: ... set slides.<N-1>.<点路径> <值>；"
        "换整段 css/html 又要保住 lifted/title: ... set slides.<N-1>.custom_css --from-file f.css。"
        "详见 references/raw-page-quickstart.md「改单值」节。"
        "(若确属 deck-cli 无法覆盖的跨页批量分析,临时去 ~/.claude/settings.json 关掉本 hook 再跑。)"
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)

allow()
