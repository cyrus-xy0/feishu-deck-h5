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

- **Small edit**: lock slide key/scope, edit `deck.json`, render, validate only
  locked slide(s).
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
  redesign. Use `assets/reskin.sh`.
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
- **Conversion/import**: read `converting-existing-material.md` and choose replica
  vs rewrite. Existing material defaults to 1:1 page count unless user says to
  compress/restructure.
- **Round-trip recovery**: run `sync-index-to-deck.py` before forking, library
  ingest, or delivery when `index.html` may contain post-render edits.
- **Copy/text edit**: edit `deck.json` and rerender; do not revive the retired
  `texts.md` sidecar flow or mutate rendered HTML unless doing explicit
  round-trip recovery.
- **Imported/raw deck repair**: if an imported deck has old head-level per-slide
  CSS, use `deck-json/migrate-head-css-to-custom-css.py`; if it has readable
  but too-small raw text, prefer `assets/grow-box-fit.py` after rebundling rather
  than blind font-size snapping.

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
- `../../deck-json/migrate-head-css-to-custom-css.py`
- `../../assets/grow-box-fit.py`
