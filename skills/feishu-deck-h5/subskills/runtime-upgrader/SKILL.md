---
name: runtime-upgrader
description: Upgrade one source-backed Feishu Deck to a fixed trusted runtime in a new candidate run.
---

# Runtime Upgrader

Use this subskill only for the explicit `RUNTIME_UPGRADE` mode.

## Contract

- Input is canonical `runs/<source>/output/deck.json` with a sibling
  `index.html`. HTML-only artifacts are not eligible.
- `current` means the committed `HEAD` of the current trusted checkout. It is
  resolved once to a full 40-character commit; the upgrader never pulls or
  fetches.
- The target commit owns `runtime/runtime-migrations.json`. Every applicable
  required migration is automatic. Performance migrations are not a user
  switch.
- The source run is read-only. Output is a fresh
  `runs/<timestamp>-<slug>-runtime-upgrade/` candidate.
- The target renderer runs from a clean detached worktree. Old controlled
  runtime files are removed before the whole deck is rebuilt.
- `READY` means the candidate passed render, visual, portability, runtime-lock,
  DeckJSON conservation, and structural gates. It is not published.
- This subskill never calls a publisher.

## Command

```bash
python3 subskills/runtime-upgrader/upgrade.py \
  --deck-json /absolute/path/to/runs/<source>/output/deck.json \
  --to current
```

Advanced, still local and pinned:

```bash
python3 subskills/runtime-upgrader/upgrade.py \
  --deck-json /absolute/path/to/output/deck.json \
  --target-commit <40-character-commit> \
  --output-run /absolute/path/to/runs/<new-candidate>
```

Use `--dry-run` for eligibility and migration planning without creating a
candidate. There is deliberately no `--in-place`, `--force`, `--publish`, or
performance-feature flag.
