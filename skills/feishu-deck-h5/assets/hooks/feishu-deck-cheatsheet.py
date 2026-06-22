#!/usr/bin/env python3
"""
feishu-deck-h5 · Claude Code UserPromptSubmit cheat-sheet hook  (handed into the repo)

WHAT THIS IS
  A Claude-Code hook that fires when the user submits a prompt. If the prompt
  references a feishu-deck-h5 deck, it slices the highest-value fast-path sections
  out of references/raw-page-quickstart.md and injects them into context — so the
  固定常量 / 速度纪律 / 改单值 facts (and, on lift/translate intent, the 跨 deck
  拎一页 LIFT+SWAP recipe) are in front of the model WITHOUT it having to open the
  file, re-run --help on every deck-cli subcommand, or re-archaeologize deck.json
  shape each cold session. This collapses the per-session CLI/deck re-discovery
  that the end-to-end latency audit flagged as a top wall-clock + variance source.

WHY SLICE LIVE (not paste a copy)
  It reads the sections straight from the installed skill's quickstart, so it can
  never drift from the single source. raw-page-quickstart.md owns the wording; this
  hook only chooses which sections to surface for the current prompt.

DESIGN RULE: the hook must NEVER break the session. Any exception / parse failure
/ missing file / non-deck prompt → silently pass through (exit 0). It only ADDS
context; it never blocks a prompt.

  -----------------------------------------------------------------------------
  ⚠️ THIS HOOK IS CLAUDE-CODE-ONLY (UserPromptSubmit). Codex / cloud agents have
  no UserPromptSubmit mechanism, so it is a convenience accelerator, not the
  model-agnostic floor — the durable fast-path lives in the docs it slices
  (references/raw-page-quickstart.md) and in the tools it points at
  (deck-cli.py / lift-translate-page.py / render-deck.py --scope --shoot).
  -----------------------------------------------------------------------------

INSTALL (Claude Code only)
  1. Copy this file to a stable location, e.g. ~/.claude/hooks/feishu-deck-cheatsheet.py
  2. Register it in ~/.claude/settings.json under hooks.UserPromptSubmit:
       {"hooks": {"UserPromptSubmit": [
         {"hooks": [{"type": "command",
                     "command": "python3 /ABSOLUTE/PATH/feishu-deck-cheatsheet.py"}]}]}}
  3. It reads the quickstart from ~/.claude/skills/feishu-deck-h5/references/
     raw-page-quickstart.md (the standard skill install path); adjust QS below if
     your skill lives elsewhere.
"""
import os, sys, json, re


def out_nothing():
    sys.exit(0)


try:
    data = json.load(sys.stdin)
except Exception:
    out_nothing()

prompt = data.get("prompt") or data.get("user_prompt") or ""
# deck signal: a feishu-deck path / deck.json / a #N page ref on an index.html / a runs/*.html path
if not re.search(r"feishu-deck-h5|deck\.json|index\.html#\d|/runs/.+\.html", prompt):
    out_nothing()
# lift/translate intent → also slice the (already-authored) 跨 deck 拎一页 LIFT recipe,
# so the cross-deck-page chain is in front of the model without it re-archaeologizing.
lift_intent = bool(re.search(r"lift|拎一页|paste|翻译|translate|localize|英文|English",
                             prompt, re.I))

QS = os.path.expanduser(
    "~/.claude/skills/feishu-deck-h5/references/raw-page-quickstart.md")
try:
    lines = open(QS, encoding="utf-8").read().splitlines()
except Exception:
    out_nothing()

# Pull the high-value sections: facts + speed discipline + EDIT recipes always;
# the 跨 deck 拎一页 (LIFT+SWAP) recipe only on lift/translate intent.
a = b = c = d = False
picked = []
for ln in lines:
    if ln.startswith("## 固定常量"): a = True
    if ln.startswith("## raw 页"): a = False
    if ln.startswith("## 跨 deck 拎一页"): d = True
    if ln.startswith("## 速度纪律"):
        d = False
        c = True
    if ln.startswith("## 改单值"):
        c = False
        b = True
    if a or b or c or (d and lift_intent):
        picked.append(ln)

body = "\n".join(picked).strip()
if not body:
    out_nothing()

ctx = (
    "【feishu-deck 速记 · hook 自动注入】检测到你在改一个 feishu-deck 页。先用下面这些"
    "固定事实+配方,别再 json.load 手猜 deck.json 形状、别逐个 --help、别现场重新考古、"
    "别为改一页跑全 deck。全文见 raw-page-quickstart.md。\n\n" + body
)
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": ctx,
    }
}))
