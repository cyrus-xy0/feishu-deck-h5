# slide-deletion — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:net-delete 触发判定细节 + 备份命名

## SLIDE DELETION POLICY (mandatory) — explicit confirmation packet + backup before any net delete

Deleting a slide is **irreversible** without a backup. The deck is the user's
real work product — a 30-slide pitch reduced to 27 slides has lost 3 slides
of editorial decisions, content density, and visual rhythm that can't be
silently regenerated. Mistakes here are high-cost; the confirmation cost is
one IM line. The math always favors confirm-then-act.

### The rule

Before ANY operation that **net-removes** a slide from a deck:

1. **STOP.** Don't run the deletion yet.
2. **List what's being removed.** Show:
   - count of slides going away
   - each slide's `data-screen-label` (e.g. "07 工作台") + `data-slide-key`
     (e.g. `workbench-portal`) so the user can identify it without opening
     the file
   - 1-line "why" the agent is removing each one
3. **Send one explicit confirmation packet.** The packet combines the exact
   deletion list from step 2 with the backup decision, so the user resolves
   both branches in one reply. The default is to back up `index.html` and
   `deck.json` (when present) beside the originals with
   `.bak-pre-delete-<YYYYMMDD-HHMMSS>` naming and log the change. Suggested
   phrasing:

   > "将删除 3 页：#16 `...`、#21 `...`、#28 `...`。默认先配对备份
   > `index.html` + `deck.json` 到原目录并写入 CHANGES.md。回复‘确认’即按
   > 上述列表删除并采用默认备份；如不要备份或要换目录，请在同一条回复里说明。"

   Wait for the user to type "确认" / "yes delete" / "ok" / equivalent.
   **Implicit consent does NOT count** — if the user said "trim the deck"
   earlier, that is not approval to delete a surfaced list. A reply such as
   "确认删除，不备份" explicitly selects the no-backup branch; do not ask a
   second question.
4. **Only THEN proceed.** Run the default paired backup unless the confirmation
   selected another backup option, then apply the deletion.

This preserves the requested double-confirm safety without creating two extra
chat round trips: the user's original delete instruction is the first signal;
the surfaced confirmation packet is the second, explicit confirmation and also
settles the backup choice.

### What counts as a "net-removing operation"

| Operation | Triggers? | Notes |
|---|---|---|
| Removing a `.slide-frame` block from `index.html` via Edit | **Yes** | Even if "just one slide" |
| `rm` of the entire `output/` folder | **Yes** | Wholesale wipe |
| Re-rendering a `deck.json` with FEWER `content/story-case` (or any) slides than the current `index.html` has | **Yes** | Net delete via regen |
| Replacing N slides with M < N slides in one operation | **Yes** | Net-removed = N − M |
| Inserting slides (M > N) | No | Pure addition is reversible by deleting back |
| Reordering slides (same N, same content) | No | But announce the new order before applying — separate "non-destructive change confirmation" |
| Editing a slide's content (title / cards / CSS) | No | The slide still exists; content edits are routine |
| Replacing one slide with one different slide (1:1 swap) | **Yes** | The previous slide's content IS deleted; back it up |

When in doubt, treat the operation as a delete and ask. One IM ping is
cheap; rebuilding a slide from scratch is not.

### When the user has pre-authorized

If the user says EXACTLY "delete slide 7, no need to confirm" or "drop
slides 7-9 and back up to /tmp/foo, don't ask me again", the rule is
satisfied — they gave a specific instruction with both branches resolved.
Default-decline confirmations still require a list-then-act flow; the
"don't ask me again" only applies to THIS operation, not future
deletions in the same session.

### Why this rule is mandatory (and where it came from)

User feedback 2026-05-18: "如果需要删页的,一定要和我 2 次确认,然后给我
删除前备份选项". The agent was getting too comfortable executing slide-
removal operations without surfacing exactly what was being lost. Slide-
level deletion is in the same risk tier as `git push --force` or
`rm -rf` — destructive on shared, slow-to-reproduce work.

### Backup helper: `bak-and-log.sh` (recommended)

Use the shipped helper instead of hand-rolling `cp` + filename — it
backs up, logs the change to `CHANGES.md`, AND prunes old backups so
the output dir doesn't accumulate 50+ stale `.bak` files:

```bash
bash skills/feishu-deck-h5/assets/bak-and-log.sh \
    <file> <short-tag> "<one-line description>"
```

Example:

```bash
bash skills/feishu-deck-h5/assets/bak-and-log.sh \
    runs/<ts>/output/index.html delete-slide-7 \
    "Drop slide 7 (taste-shifts-3pains, redundant with slide 8)"
```

Effects:
- Creates `<file>.bak-pre-<tag>-<YYYYMMDD-HHMMSS>` (`.N` suffix if
  same-second collision)
- Prepends an entry to `<dir>/CHANGES.md` (creates if absent)
- Prunes `.bak-pre-<tag>-*` keeping only the **3 most recent** per
  (file, tag) pair — different tags get separate retention slots

Tags scope retention. Use one tag per edit class (`delete-slide-7`,
`iframe-fix`, `p20-rewrite`) so unrelated edits don't compete for the
3-slot quota.

For paired files (e.g. `index.html` + `deck.json`), run the helper TWICE
with the SAME tag and similar descriptions — both files get backed
up under the same retention slot, and both edits get one CHANGES.md
entry per call (consider consolidating description in the second
call: "(paired with index.html backup above)").

### Backup naming convention (legacy, prefer the helper above)

If you must hand-roll without the helper, follow the format the
helper produces so retention logic still recognises the files:

```
<file>.bak-pre-<short-tag>-<YYYYMMDD-HHMMSS>
```

Examples:
- `runs/.../output/index.html.bak-pre-delete-slide-7-20260518-160000`
- `runs/.../output/deck.json.bak-pre-delete-slide-7-20260518-160000`

Without the helper you don't get the CHANGES.md entry or pruning —
which is how the historical 53-bak pile-up happened. Use the helper.

---
