# Run artifacts — PROMPTS.md

> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:写每轮 PROMPTS.md
>
> 注:旧的 FEEDBACK.md 自我改进回路已退役,改由 MAKING-OF LOG(`deck-log`,
> 见 SKILL.md「MAKING-OF LOG」)承接 —— log 既记每轮输入/回复/截图/校验,
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
- See SKILL.md "MAKING-OF LOG" for the per-run making-of record (`deck-log`),
  which is the primary self-improvement / diagnose loop now.
