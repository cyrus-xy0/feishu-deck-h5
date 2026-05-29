# run-artifacts — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:写每轮 FEEDBACK.md / PROMPTS.md

## RUN-FEEDBACK CAPTURE (mandatory) — auto-generated `FEEDBACK.md` per run

Every successful run MUST produce a `FEEDBACK.md` file in
`runs/<ts>/output/` alongside `index.html` and `texts.md`. This is the
manual feedback loop that drives skill maintenance: the agent
auto-records the **judgment calls and workarounds it actually made
during this run**, the user spot-checks them, and when they accumulate
≥3 things worth raising, sends the file to the skill maintainer for
integration into the next skill version.

### Why "auto-generated, not template"

A blank "tell us what's broken" form gets blank answers. What works is
showing the user **the specific decisions the agent made on their
content** — layout choices, sizing tweaks, validator workarounds, copy
shortenings, master deviations — and asking them to confirm or push
back per-decision. The user reads through the list, sees one item that
feels wrong, makes a note, moves on. No reconstruction effort needed.

### What goes into `FEEDBACK.md` (REQUIRED sections)

The agent fills the file based on **what actually happened in this
run** — not from a fixed template. Every run is different; the file
content reflects this run's specific decisions. Required sections:

1. **Header** — run timestamp + one-line description of what was built
   (layout, slide count, source material).

2. **关键决策 (auto-detected from this run)** — every non-trivial choice
   the agent made on the user's content. Each item gets:
   - what was decided (1-2 sentences)
   - why (the constraint or content shape that drove it)
   - a `你的看法:` line with checkboxes covering the realistic
     pushback shapes for that decision (`[ ] 对 / [ ] 应改成 X / [ ] 备注`)

   Examples of decisions that belong here:
   - layout pick (e.g. "用了 `.story-case` 因为 …")
   - column ratios / sizing tweaks (e.g. "图片列从 1fr 1fr 改到 1fr 1.3fr")
   - copy shortenings (e.g. "标题从 22 字压到 17 字以单行容纳")
   - validator workarounds (e.g. "把 '#001' 改成 'STORY 001' 因为 R10 误判 hex")
   - master deviations (e.g. "封面加了 subtitle 偏离 master,因为 …")
   - asset choices (e.g. "用 background-image 而非 `<img>` 满足 UI1")

3. **本次没解决的小毛病** (if any) — warnings the agent noticed but
   didn't fix (e.g. "validator 对 `.scene-cap` 做 backdrop-filter 警告
   但在阈值内,没改").

4. **你的额外建议** — empty bullets for the user to add anything not
   already auto-detected.

5. **末尾提示** — exactly:
   > 累计 ≥3 条值得反馈的(打钩 / 备注 / 自填),把这个文件发给 skill 维护者整合到下一版.

### What does NOT go into `FEEDBACK.md`

- Generic / boilerplate self-checklist questions ("layout 对吗? 字号对吗?")
  — useless without context. Only ask about decisions that were
  actually made.
- The validator's PASS report (already shipped in delivery message).
- The slide count or token usage (irrelevant to maintainer).
- Praise of the skill ("looks great!"). The file is for upgrade
  signal only.

### Don't hardcode contact info

`FEEDBACK.md` says "send to skill maintainer" — NOT a specific email,
handle, or IM address. Different installs of this skill have different
maintainers; the recipient identity is implicit per repo convention
(GitHub `CONTRIBUTING.md`, `git log`, the install team's group chat).
Hardcoding a personal address would couple the skill to one person.

### How the agent surfaces it at end of run

After validator passes and files are written, the agent's delivery
message (Mode 1 — Claude Code on local) MUST include:

> · `runs/<ts>/output/FEEDBACK.md` — 这次 build 的关键决策清单,
>   见到不对的地方打钩或备注;累 ≥3 条发给维护者整合到下版.

For Mode 2 (zip / remote / Feishu bot), `FEEDBACK.md` ships INSIDE
`deck-editable.zip` so the recipient can fill it offline. The
`package-deliverable.sh` script already includes `*.md` files in the
zip; no extra work needed.

### Maintainer-side workflow (informational, not enforced)

When the maintainer receives a batch of `FEEDBACK.md` files (e.g. 5+
forwarded over a few weeks), the integration ritual is:
1. Read all files; cluster comments by decision class (sizing,
   validator, layout choice, …).
2. Promote any cluster ≥3 reports into a SKILL.md rule update,
   citing the sample FEEDBACK files in the commit message.
3. One-off comments without cluster support → log in
   `LESSONS.md` (or the equivalent), revisit at next batch.

This step is the maintainer's call, not the agent's — the agent's job
ends at producing high-quality `FEEDBACK.md` files. Keeping the
integration manual is the user's explicit control point over skill
evolution.

---


## RUN-PROMPTS LOG (Phase 1) — `PROMPTS.md` per run

Goal: mine user prompts across many decks to surface **skill-gap
signals** (audit rules / defaults / protocols the skill SHOULD have
caught but didn't) and **workflow patterns** the user can improve on.
Each `runs/<ts>/output/` ships a `PROMPTS.md` capturing every user
prompt that touched the deck, verbatim + lightly tagged.

Full format spec: **`assets/PROMPTS-format.md`** (canonical, all writers
must conform).

### Two writing paths

| Path | When | Who runs it |
|---|---|---|
| **Realtime append** | The agent (any agent supporting it) appends to PROMPTS.md after each user message, before generating any artifact | Agent itself, per the contract in `PROMPTS-format.md` "Realtime-append contract" |
| **Post-hoc extraction** | Backfill historical decks OR rebuild PROMPTS.md from an agent that didn't realtime-append | User runs `extract-from-<agent>.py` against the agent's transcript files |

Both paths produce **the same canonical format**, so downstream analysis
doesn't care which path was used. The two paths can coexist on one
deck (e.g., realtime entries plus a backfill from before realtime
support was added).

### Shipped adapters (Phase 1)

- **`assets/extract-from-claude-code.py`** — for Claude Code's
  per-session JSONL transcripts at `~/.claude/projects/<encoded-cwd>/
  <session-id>.jsonl`. Single-flag deck filter (`--filter-deck SLUG`),
  session-level scoping (any prompt in a transcript mentioning the
  slug → include all prompts from that transcript).
- (other agent adapters: TBD — Codex / Mira / Cursor / Aider need
  sample transcripts before adapters can be written; do NOT speculate-write
  blind adapters)

Use:
```bash
# one transcript
python3 skills/feishu-deck-h5/assets/extract-from-claude-code.py \
    ~/.claude/projects/-Users-bytedance/<session-id>.jsonl \
    --out runs/<ts>/output/PROMPTS.md

# many transcripts → one deck
python3 skills/feishu-deck-h5/assets/extract-from-claude-code.py \
    ~/.claude/projects/-Users-bytedance/*.jsonl \
    --filter-deck <slug> \
    --out runs/<ts>/output/PROMPTS.md \
    --title "<deck display name>"
```

### Realtime-append contract (when agent supports it)

When supported, the agent MUST after every user message:

1. Compute the run's PROMPTS.md path:
   `runs/<ts>/output/PROMPTS.md` (same directory as the deck artifact)
2. If file doesn't exist, create with title + standard header
3. Append a new entry with the timestamp + type guess + slide refs +
   `(agent: <id>)` tag + verbatim user text
4. DO NOT proceed to generate the artifact until the append is done

**Verbatim or nothing**: do NOT summarize, translate, "improve", or
LLM-remix the user's wording. The log's value is its truthiness. If
the user wrote "字小了，没啥没检查出来" that is exactly what goes in.

If the agent runtime cannot file-write (sandboxed harness), print
`PROMPT-LOG: <ts> | <type> | <verbatim text>` to stdout so the user
can hand-append to PROMPTS.md. Don't silently drop.

### Why this exists (the actual goal)

Most "bugs" in a finished deck started as a user complaint like "字小了"
or "标题位置不对" or "中间太空" — the user was the audit. PROMPTS.md
turns that audit into a queryable signal:

| Signal type | What you mine PROMPTS.md for | Yields |
|---|---|---|
| **Skill-gap** | Repeated `bug-report` complaints across decks (e.g. "字小" appears 47 times across 23 decks) | New audit / rule / default — promote into validator |
| **Protocol miss** | `bug-report` AND the prior agent response shows skipped pre-check (no Q0-Q4 design pass, no backup before delete, etc.) | Tighten existing rule into hard gate |
| **Workflow inefficiency** | ≥ 5 edits on the same slide-key within 24h | Per-user coaching note: batch edits, use deck.json bulk ops, etc. |

The `bug-report` class is by far the highest-value mine. Real
production rate (in maintainer's testing on a 43-slide deck): 50
bug-report prompts → at least 2 new audit rules + 1 hard-gate
elevation. That's a 1:25 ratio of skill upgrades to user complaints,
which is what makes the log worth keeping.

### What NOT to log

- Assistant responses (out of scope; log is the USER's voice)
- Tool outputs (out of scope)
- System-injected messages (`<command-name>`, `<system-reminder>`,
  `<local-command-caveat>` — adapters MUST strip these)
- Anything synthesized by an LLM in passing (e.g. an agent's
  "I think the user meant ..." paraphrase)

### Privacy boundary

- PROMPTS.md is per-run, lives next to the deck in `runs/<ts>/output/`
- Same lifecycle as the deck — `package-deliverable.sh` already
  includes `*.md` files, so PROMPTS.md ships with the deck unless
  excluded
- **No automatic cross-user aggregation**. If you want a multi-user
  analysis dataset, collect PROMPTS.md files MANUALLY into a separate
  repo / dir — the user explicitly chooses what they share

If a PROMPTS.md contains sensitive content (real customer names,
internal metrics), `package-deliverable.sh --exclude PROMPTS.md` (TBD)
or just `rm` before zipping. There's no automated PII scrubbing yet.

---

