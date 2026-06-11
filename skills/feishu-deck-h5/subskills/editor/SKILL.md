---
name: feishu-deck-h5-editor
description: |
  Operations subskill for feishu-deck-h5. Use for existing deck edits,
  single-slide changes, reskinning foreign HTML, lift/swap from another deck,
  importing/converting existing PDF/PPT/HTML/docs, slide deletion/reorder, and
  round-trip recovery.
---

# feishu-deck-h5-editor

## Responsibility

Handle existing artifacts:

- edit copy/layout of existing decks
- edit target HTML that has been imported as existing pipeline state
- reskin foreign HTML into Feishu chrome
- lift/swap slides from another deck while preserving source layout
- convert/import existing PDF/PPT/HTML/docs into the deck pipeline
- delete/insert/reorder slides with backup and confirmation
- recover drift between `index.html` and `deck.json`

Inline freshness rule: when this subskill is not running as a separate
multi-agent worker, reread the current upstream files before editing. Do not rely
on cached chat summaries or earlier reads of `deck.json`, `index.html`,
`slide-index.json`, source decks, text-replacement plans, or imported material.

## Mode Routing

Mode names follow the single **Authoritative Mode Enum** in
`../../references/request-router.md`. The Editor owns the EDIT family: `EDIT`
(generic small/substantive edit of an existing deck), `EDIT_IMPORTED_HTML`,
`RESKIN`, and `LIFT+SWAP`. All of these edit a deck that already exists — they do
NOT open a new run (a fresh run artifact is `GENERATION`, which routes to
Designer + Renderer instead).

- **`EDIT` (small edit)**: lock slide key/scope, edit `deck.json`, render, validate only
  locked slide(s). The locked scope is the boundary for the re-render too — pass it
  to `render-deck.py` so downstream steps don't re-process the whole deck. For an
  edit confined to specific pages, re-render with `--scope N` (1-based page numbers,
  e.g. `--scope 1` or `--scope 3,5`): it refreshes only those pages in the making-of
  and skips the whole-deck readability advisory + geometry audit, cutting a 50-page
  re-render from ~2m12s to ~12s while still capturing the changed page's screenshot.
  Use `--quick` instead when you don't need the making-of updated this run (skips the
  snapshot entirely, ~12-18s). Full render (no flag) only for a new deck or a
  whole-deck change. See `references/editing-discipline.md` → "Re-render speed".
- **EDIT_IMPORTED_HTML**: user wants to modify the uploaded/current HTML itself.
  Require existing-state artifacts first: `input/source.html`,
  `input/runtime-library/source-dossier.json`, `output/DESIGN-PLAN.md`,
  `output/outline.json`, `output/deck.json`, and `output/index.html`.
  Treat those artifacts as describing the already-completed current deck state.
  Prefer editing `deck.json` and rerendering. If the imported HTML cannot be
  faithfully represented as structured DeckJSON, keep it as raw slides and edit
  the smallest raw slide/body region needed. Directly mutate rendered HTML only
  for explicit round-trip recovery or when the controller has accepted a
  non-DeckJSON fallback.
- **RESKIN**: user wants Feishu chrome on an existing foreign HTML without content
  redesign. Use `assets/reskin.sh`. **First ask the F-300 second question** — is
  this a STANDALONE reskin, or is the page being ADOPTED into an existing deck?
  If adopted, the page must match its NEW SIBLINGS, not its source: after the
  reskin/rebuild lands in the deck, run the conform pass
  `deck-json/conform-to-deck.py <deck.json>` (read-only drift table first, then
  `--apply` for the deterministic D1/D3/D4 conforms; D2 title-move + D5 contrast
  stay manual). The sibling raw content pages ARE the house-style spec; this
  collapses the otherwise-serial "fix the bg / move the title / drop the eyebrow /
  fix the font size / un-grey the text" feedback rounds into one. The soft
  `R-FAMILY-DRIFT` advisory in `validate-deck.py` is the render-time backstop.
- **LIFT+SWAP**: user wants source deck layout preserved and only copy/client
  swapped. Use `deck-cli.py paste` for DeckJSON-native sources; use
  `assets/lift-slides.py --shake` for foreign or older HTML sources; use
  `deck-json/apply-text-pairs.py` for deterministic text replacement. Resolve
  source and target pages with `deck-json/locate-slide.py`; after lift/insert/
  reorder, run `render-deck.py --renumber` on the target DeckJSON when stale
  `screen_label` prefixes need to match true page/hash order.
- **Lift into HTML target without DeckJSON**: when the destination is a deck with no
  `deck.json`, do not hand-splice frames. Use the HTML destination mode:

  ```bash
  python3 assets/lift-slides.py SRC/index.html --preview --key <key> [--against DST/index.html]
  python3 assets/lift-slides.py SRC/index.html --key <key> DST/index.html [--pos N|end] [--shake]
  ```

  Add `--shake` only when preview recommends it, typically because the source
  slide depends on head-coupled CSS. `lift-slides.py --to-html` extracts the
  rendered frame, transforms assets/CSS with the same logic as DeckJSON lift,
  splices into `.deck`, backs up, and validates the inserted page.
- **Always pass ABSOLUTE paths to `lift-slides.py` and `render-deck.py`** (src,
  DEST `deck.json`, OUTPUT_DIR). The skill root is usually a symlink
  (`~/.claude/skills/feishu-deck-h5` → `.../Github/feishu-deck-h5/skills/
  feishu-deck-h5`), so a relative `runs/...` path resolves against the
  de-symlinked CWD into a non-existent `runs/` that does not match where
  `new-run.sh` created the run — wasting a full source parse before the write
  fails. Use the absolute run path `new-run.sh` prints.
- **`--shake` faithfully recovers the source's per-`[data-slide-key]` head CSS,
  including dead cruft.** If a source author pasted one shared kitchen-sink
  stylesheet onto every page, a lifted slide can carry dozens of rules whose
  target elements do not exist on it → `R-VIS-DEAD-RULE` errors. Verify the root
  cause is source cruft (grep the source for the key+selector — if present, it
  is the source's, not a shake mis-scope), then prune only the rules whose leaf
  selector references no element in that slide's body DOM. Keep the framework
  layout block and every rule that targets a live class/tag.
- **Conversion/import**: read `converting-existing-material.md` and choose replica
  vs rewrite. Existing material defaults to 1:1 page count unless user says to
  compress/restructure.
- **Round-trip recovery**: run `sync-index-to-deck.py` before forking, library
  ingest, or delivery when `index.html` may contain post-render edits. **Always
  `--dry-run` first and confirm the DRIFT DIRECTION** — drift can mean either
  genuine post-render `index.html` edits (sync them) or un-rendered `deck.json`
  edits (re-render instead, do NOT sync, or you overwrite them with stale HTML).
  The tool guards this: if `deck.json` is newer than `index.html` a full sync
  refuses to write, warns, and falls back to dry-run (`--index-is-newer`
  overrides). A default full sync covers raw HTML, canvas, slide order,
  `custom_css`, `hidden`, and speaker `notes` — so a green report from any
  earlier (raw-only) run is not a guarantee those fields were checked; re-run.
- **Copy/text edit**: edit `deck.json` and rerender; do not revive the retired
  `texts.md` sidecar flow or mutate rendered HTML unless doing explicit
  round-trip recovery.
- **Imported/raw deck repair**: for the common back-catalog defects of a
  lifted/imported deck, run the one-command pipeline **`deck-json/repair-lifted.py`**
  (see next section) instead of remembering the individual tools. If a deck has
  readable but too-small raw text, that is a separate fix — prefer
  `assets/grow-box-fit.py` after rebundling rather than blind font-size snapping
  (`repair-lifted.py` does NOT grow tiny text; it only snaps OFF-LADDER values).

### Lifted / imported deck repair pipeline (F-267)

- **One command for a garbled imported deck: `deck-json/repair-lifted.py <deck>`.**
  It is a thin orchestrator that decides which of the existing repair tools apply
  (by file existence + a head-CSS scan) and runs them in the proven order:
  `backfill` (sync-index-to-deck `--backfill`, only when there is no `deck.json`
  yet) → `migrate-head-css-to-custom-css` (only when `index.html` has head/deck-level
  per-slide CSS) → `heal-lifted` → `clean-lifted-css` → `reconcile-lifted` →
  render + `validate-deck --strict`. `<deck>` may be the deck dir, its
  `index.html`, or its `deck.json`.
- **dry-run-FIRST — it defaults to `--dry-run`.** It prints the plan and previews
  every step (writing nothing); add **`--apply`** to actually run. Always preview
  first: `heal-lifted`'s "provably-safe" premise was once falsified and rolled
  back (docs/archive), so never assume a blind direct run is safe.
- Each step keeps its own `deck.json.bak-pre-<cmd>-<ts>` + re-validate-with-rollback,
  and `lift-slides.py` now write-after-validates + rolls back too (F-281b), so a
  lift/repair that would produce an invalid `deck.json` never lands on disk.

### Batch lift & lift-done gates (F-62 / F-63)

- **F-62 — batch lift discipline.** Never "lift every page first, then fix in bulk".
  Lift in batches of **3–5 pages**; after each batch **immediately** reconcile font
  sizes onto the 4 tiers and run `validate.py` — a batch is NOT done while any ✗
  remains, and stacking the next batch with ✗ still open is wrong. **Do the font
  snap with `deck-json/reconcile-lifted.py <deck.json>` (or the whole repair pass
  `deck-json/repair-lifted.py <deck> --apply`), not by hand** — both snap `font:`
  shorthand + `font-size` to {16,24,28,48} deterministically and idempotently
  (`--dry-run`/dry-run-first to preview). Complex pages (phone mock / chat UI /
  KPI bars — F-40 known to collapse) get rendered + screenshot-checked **one page
  at a time**, not deferred. (A 24→46 bulk lift of 22 pages at once = 18✗ / 185
  findings dumped at the end — exactly this rule's absence.)
- **F-63 — lift done = 4 greens** (any non-green = lift not finished; do NOT say
  "done"):
  - [ ] **DOM balance** — `R-DOM` (`audit_dom_integrity`) no ✗; every `.slide-frame`
    is a direct child of `.deck` and contains exactly one `.slide`.
  - [ ] **Complex component pages screenshot-verified** — phone mock / chat UI / KPI
    bars (F-40) checked by image, not collapsed.
  - [ ] **Font sizes reconciled to the 4 tiers, validator off-ladder clean** — `R20`
    / `R06` / `R-VIS-TIER` clean, no off-ladder sizes.
  - [ ] **No silent cropping** — `R-VIS-CARD-OVERFLOW` / `R-OVERFLOW` no ✗.
  - Scope: the F-63 four-green check targets **foreign / hand-authored /
    possibly-broken** decks, NOT your own already-published pages.

## Hard Rules

- Never use regex/sed to mutate slide DOM structure.
- Never delete slides without explicit confirmation, list of removed slides, and
  backup offer.
- Do not broaden a small edit into a whole-deck audit.
- Do not treat target HTML edits as freeform rewrites. The uploaded HTML is the
  current state to preserve unless the user asks to redesign or regenerate.
- Treat `page N`, URL `#N`, and frame index N as the same canonical page. Do not
  use old `screen_label` numeric prefixes as source page numbers.
- If a file may have been changed by another session, reread immediately before
  editing and preserve unrelated changes.
- Keep `deck.json` as source of truth; rerender after edits.
- Ensure lifted/hand-authored slides retain stable semantic `data-slide-key`
  values before delivery or library ingestion.
- For raw slides, `data.html` is the inner content of `.slide`; it does not
  include `.slide` or `.slide-frame` wrappers. If you need a complete renderable
  frame, extract it from rendered `index.html`, not from `deck.json` `data.html`.

## References To Load As Needed

- `../../references/layout-recipes.md` — **read before editing the layout / fill /
  whitespace of a `layout:"raw"` slide.** Sparse content does NOT get fixed by
  stretching bordered cards (`min-height` / `flex:1`) to reach the floor — that
  makes hollow cards (content jammed top, dead air middle). Re-shape to a layout
  that fills 16:9 by nature (vertical flow, wide stacked rows, tall hero beside
  stacked annotations) and keep growing visuals borderless. See "Raw slides +
  genuinely-sparse content".
- `../../references/editing-discipline.md`
- `../../references/request-router.md`
- `../../references/deck-generation-policy.md`
- `../../references/slide-deletion.md`
- `../../references/reskin.md`
- `../../references/converting-existing-material.md`
- `../../references/prototype-embed.md`
- `../../references/round-trip-integrity.md`
- `../../references/operational-notes.md`
- `../../references/run-artifacts.md`
- `../../references/troubleshooting.md`
- `../../references/delivery.md`
- `../../LIFT-ARCHITECTURE-2026-05-30.md`
- `../../IMPORT-RAW-DECK-LESSONS-2026-05-30.md`
- `../../deck-json/repair-lifted.py` — one-command lifted/imported deck repair
  pipeline (F-267); dry-run-first, `--apply` to run. Routes backfill →
  migrate-head-css → heal → clean → reconcile → render+validate.
- `../../deck-json/migrate-head-css-to-custom-css.py`
- `../../deck-json/reconcile-lifted.py` — snap lifted-slide inline font sizes
  onto the {16,24,28,48} tier ladder (the F-62 reconcile step).
- `../../deck-json/conform-to-deck.py` — F-300 family-drift detector + conformer
  for a page ADOPTED into an existing deck. Read-only drift table by default
  (D1 page-bg / D2 title placement / D3 pre-title chrome / D4 font ladder / D5
  body luminance, each vs the sibling-content-page consensus); `--apply` runs the
  three deterministic conforms (D1/D3/D4) with backup + optimistic-lock +
  validate-with-rollback. D2/D5 are report-only. Also runs read-only as a step in
  `repair-lifted.py`, and is the source-of-truth for the soft `R-FAMILY-DRIFT`
  advisory in `validate-deck.py`.
- `../../assets/grow-box-fit.py`
