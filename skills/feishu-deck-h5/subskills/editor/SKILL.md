---
name: feishu-deck-h5-editor
description: |
  Operations subskill for feishu-deck-h5. Use for existing deck edits,
  single-slide changes, imported HTML recovery, reskin, lift/swap, conversion
  finish, slide insertion/deletion/reorder, and round-trip repair.
---

# feishu-deck-h5 editor

Own the EDIT family from `../../references/workflow.yaml`: `EDIT`,
`EDIT_IMPORTED_HTML`, `RESKIN`, and `LIFT+SWAP`. These modes modify an existing
artifact; they do not create a fresh run.

Before editing, reread the current `deck.json`, `index.html`, slide index, source
deck, and replacement plan. Preserve unrelated work from other sessions.

## Canonical write contract

`deck.json` is source of truth. General writes go through `deck-cli.py` or an
explicit sanctioned wrapper. Direct JSON editor/heredoc/ad-hoc rewrites are
forbidden because they bypass locking, optimistic concurrency, backup, schema
validation, and rollback. Read `../../references/deck-state-contract.md` before
interpreting non-zero tool exits.

Never use regex/sed to mutate slide DOM. Raw `data.html` contains only the inner
slide content, not `.slide` or `.slide-frame` wrappers.

## Choose the lightest safe path

### Pure text replacement

When wording changes without DOM/layout implications:

```bash
python3 deck-json/fast-text.py <deck-dir> "OLD" "NEW"
```

The tool dual-writes DeckJSON and HTML. Exit 3 means DeckJSON changed but HTML did
not; immediately reconcile with a quick render. It is not the same as deck-cli
exit 3.

### Pure existing-image replacement

When exactly one existing `<img>` source changes and crop/layout stay fixed:

```bash
python3 deck-json/fast-image.py <deck> <slide-key> <image> \
  --old-src <fragment> --name <stable-name>
```

If aspect ratio, crop, container, or CSS changes, use the fragment loop instead.

### Fragment/layout edit

1. Resolve page/key with `locate-slide.py`.
2. Read only the target page with `deck-cli.py get-page` or
   `locate-slide.py --grep`.
3. Write body/CSS fragment files under the run input directory.
4. Commit through `deck-cli.py set-page`.
5. Iterate with `preview-slide.py --key` when useful.
6. Run one real `render-deck.py <deck.json> <output> --scope <key> --shoot` gate.

```bash
python3 deck-json/deck-cli.py <deck.json> set-page <key> \
  --html <body.html> --css <page.css>
python3 deck-json/preview-slide.py <deck.json> --key <key>
python3 deck-json/render-deck.py <deck.json> <output> --scope <key> --shoot
```

Use one bounded fix-render only for a blocking or visible target-page regression.
Do not chase unrelated whole-deck warnings during a scoped edit.

### Insert a newly-authored page

Read `../../references/raw-page-quickstart.md`, then use:

```bash
python3 deck-json/import-html-slide.py <deck.json> \
  --html <body.html> --css <page.css> --key <key> --at <position> --yes
```

Do not hand-splice slides into DeckJSON or rendered HTML. Raw pages use the live
`{16, 24, 28, 48}` ladder and do not auto-create a header.

### Multi-page edit

Inspect all named targets together, write them one at a time through the guarded
CLI, then verify once with a combined scope. Do not serialize a browser launch
per page.

## Round-trip and clobber protection

Browser edit mode changes HTML first. Raw edits may auto-sync; canvas/schema/
baked edits can be lossy and must be reconciled before rendering.

- deck-cli exit 6 or render exit 8 means the write was refused.
- Run `sync-index-to-deck.py --dry-run`, confirm drift direction, then sync or
  rerender as appropriate.
- `--force` intentionally discards unreconciled browser state; never use it as
  the first response to a refusal.

For a broadly damaged lifted/imported deck, preview then apply the orchestrator:

```bash
python3 deck-json/repair-lifted.py <deck>
python3 deck-json/repair-lifted.py <deck> --apply
```

## Imported HTML and reskin

### `EDIT_IMPORTED_HTML`

Require existing-state artifacts: source snapshot, dossier, design plan,
outline, DeckJSON, and current HTML. Preserve detected page order and stable
keys. Prefer structured DeckJSON; otherwise wrap major sections as raw slides.
Direct HTML mutation is only for explicit recovery or an accepted non-DeckJSON
fallback.

### `RESKIN`

Use `assets/reskin.sh` for mechanical Feishu chrome. Decide whether the output is
standalone or being adopted into an existing deck. Adopted pages must conform to
their new siblings; inspect with `conform-to-deck.py` before applying its safe
deterministic fixes. Do not redesign content during a reskin.

## Lift and swap

Resolve source and target against their current DOM/DeckJSON order. Never infer
`#N` from old labels or chat memory. Pass absolute paths. Lock and display both
resolved endpoints before writing:

```text
SOURCE [READ-ONLY] deck-a/index.html#6 · 《source title》
                      ↓ replace; preserve source layout
TARGET [WRITABLE]  deck-b/index.html#3 · 《target title》
```

If one endpoint is missing, the same URL is repeated for a cross-deck request,
or the direction is ambiguous, stop. Do not reinterpret "复用现在 #3 页" as a
target locator without an exact target artifact. A repair after lift preserves
the lifted visual/prototype by default; fixing loading, assets, or runtime does
not authorize a redesign.

### Replace one existing slot

```bash
# 1) mandatory read-only plan (default); review titles + arrow
python3 deck-json/lift-swap.py \
  --source SRC#index --target DST#index

# 2) copy the exact token printed by step 1
python3 deck-json/lift-swap.py \
  --source SRC#index --target DST#index \
  --apply --confirm <PLAN_TOKEN>
```

`--apply` always performs the lift, scoped render, visual gate, and screenshot in
a staged destination and commits atomically only after they pass. The source
control files must remain byte-identical; the target key/order/page count must
remain unchanged. Legacy positional `SRC DST` is plan-only and can never write.
Same-deck source/target trees are rejected unless `--allow-same-deck` is explicit.
Do not delete+paste or renumber for a same-slot replacement.

### Insert DeckJSON-native pages after an anchor

```bash
python3 deck-json/lift-insert.py \
  --after DST#index SRC#index [SRC#index ...] --verify
```

`lift-insert` must stage the full operation and atomically commit DeckJSON, HTML,
slide index, notes/signature, and sidecars. Failure must leave the destination
bundle unchanged.

### Other lift shapes

- One DeckJSON page into an existing deck: `deck-cli.py paste`.
- Into a new deck: `lift-to-new-deck.py`.
- Foreign/legacy HTML: scan first with `lift-slides.py --scan`; use `--shake` for
  schema layouts and only skip it for self-contained raw pages.
- HTML-only destination: use `lift-slides.py` HTML destination mode, never a
  manual frame splice.

After lift, swap deterministic copy with `apply-text-pairs.py`. Lift hygiene is
mandatory: slide scripts, inline handlers, active URLs, and author `<style>` in
raw HTML do not survive; scoped CSS lives in `custom_css`.

## Conversion finish

Read `../../references/conversion-policy.yaml` and
`../../references/converting-existing-material.md`.

- PPTX pure import arrives as editable canvas DeckJSON from `pptx-to-deck`.
- Keynote delegates to `keynote-to-html`.
- PDF replica uses DeckJSON `replica`; rewrite runs Designer.
- Preserve page count unless the user explicitly requests condensation.

## Deletion, reorder, and identity

- Deletion requires explicit confirmation and backup; use the guarded CLI.
- `page N = URL #N = frame index N`; stable keys are preferred.
- Renumber stale `screen_label` prefixes only at an explicit cleanup checkpoint.
- Every lifted/hand-authored page keeps a stable semantic key; namespace generic
  keys across decks.

## Gate and handoff

- Intermediate work: `INTERMEDIATE_EDIT`, scoped to changed pages.
- Local handoff, presentation checkpoint, or library ingest: whole-deck gate.
- Magic Page publish: Publisher resource/reference integrity gate; do not add a
  redundant whole-deck visual pass by default.

Close substantial edits with the number of guarded writes/renders, the verified
scope, screenshot/report paths, and any intentionally retained baseline warning.

## Load on demand

- State/errors: `../../references/deck-state-contract.md`
- Raw authoring: `../../references/raw-page-quickstart.md`,
  `../../references/layout-recipes.md`
- Edit speed/multi-page: `../../references/editing-discipline.md`
- Lift/recovery: `../../references/round-trip-integrity.md`
- Reskin: `../../references/reskin.md`
- Conversion: `../../references/converting-existing-material.md`
- Deletion: `../../references/slide-deletion.md`
- Prototype/iframe: `../../references/prototype-embed.md`
- Delivery: `../../references/gate-policy.yaml`, `../../references/delivery.md`

Use tool `--help` for flags. Do not load every reference for a routine edit.
