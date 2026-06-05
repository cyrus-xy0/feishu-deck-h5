# Run artifacts — PROMPTS.md

> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:写每轮 PROMPTS.md
>
> 注:旧的 FEEDBACK.md 自我改进回路已退役,改由 MAKING-OF LOG(`deck-log`)
> 承接 —— log 既记每轮输入/回复/截图/校验,
> 又能 `deck-log diagnose` 出框架 bug 候选工单,完整覆盖原 FEEDBACK 的用途。

## PROMPTS.md — capture the user's actual asks

`PROMPTS.md` records the user's verbatim prompts for this run (the design
brief, edit requests, corrections), so the maintainer can see what real
users asked for and how the skill interpreted it.

The maintainer (you, between sessions) periodically reviews a batch of
`PROMPTS.md` files to find recurring friction and fold it into the skill.

### PROMPTS.md format

```markdown
# Prompts · <run-slug>

## Turn 1
> <verbatim user prompt>

**Interpreted as:** <what you did>

## Turn 2
...
```

## Cross-references

- `PROMPTS.md` is written per run; the maintainer batches them.
- See "MAKING-OF LOG" below for the per-run making-of record (`deck-log`), which
  is the primary self-improvement / diagnose loop now.

## MAKING-OF LOG — default-on per run

The making-of log records how a deck was produced so teammates can reconstruct the
process and maintainers can diagnose skill/framework defects. Store it under
`runs/<deck>/log/`, never under `output/`.

Tool: `log-tool/deck-log.py` (schema/details in `log-tool/README.md`). It is
default-on for generation-class deck work unless explicitly disabled with
`deck-log off`.

`assets/new-run.sh` now auto-initializes the making-of log when it creates a run
directory. It prints `deck-log : making-of log started` on success. `deck-log
init` is idempotent and preserves the original `start_ts`, so repeated init will
not lose early turns, but it is normally unnecessary.

Fixed actions:

1. **Start** is automatic after workspace creation:

   ```bash
   bash skills/feishu-deck-h5/assets/new-run.sh <slug>
   ```

   This creates `log/`, records the transcript path if discoverable, and sets the
   active deck. Do not manually run `deck-log init` unless `new-run.sh` prints
   `deck-log : auto-init skipped`, or the detected transcript is wrong. In the
   latter case, rerun:

   ```bash
   python3 skills/feishu-deck-h5/log-tool/deck-log.py init <run-dir> --transcript <path>
   ```

   The conversation transcript already contains each turn's user input and
   assistant response; do not duplicate it manually unless needed.

2. **Snapshot each meaningful version**:

   ```bash
   python3 skills/feishu-deck-h5/log-tool/deck-log.py snapshot <run-dir> --label "<what changed>"
   ```

   This freezes a copy, captures page screenshots, and runs distribution checks
   when available.

3. **Record problems and fixes** when the user flags a slide or the agent finds a
   defect:

   ```bash
   python3 skills/feishu-deck-h5/log-tool/deck-log.py event <run-dir> --type problem --slide N --msg "<problem>" --said "<user words>"
   python3 skills/feishu-deck-h5/log-tool/deck-log.py event <run-dir> --type fix --slide N --resolves "<problem>"
   ```

4. **Optional summaries** for important turns:

   ```bash
   python3 skills/feishu-deck-h5/log-tool/deck-log.py event <run-dir> --type summary --json '{"n":1,"msg":"..."}'
   ```

5. **Close out**:

   ```bash
   python3 skills/feishu-deck-h5/log-tool/deck-log.py render <run-dir>
   ```

   This writes `log/making-of.html`; include its path when useful.

6. **Diagnose framework/skill bugs** when asked:

   ```bash
   python3 skills/feishu-deck-h5/log-tool/deck-log.py diagnose <run-dir>
   ```

   Use the digest to produce candidate `AUDIT-*.md` findings in the existing
   F-NN format.
