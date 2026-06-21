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

- **`EDIT` fast-text (pure copy swap)**: when the request is ONLY changing words
  — a label, a sentence, a title's wording, zero DOM/layout implication — use
  **`deck-json/fast-text.py <deck-dir> "OLD" "NEW"`**: a sub-second dual-write
  that updates deck.json AND the rendered index.html in one deterministic swap
  (count==1 asserted on both sides; JSON-escape handled; refuses `<`/`>`), with
  NO render and NO validation. This is the sanctioned exception to
  "rerender after edits" — round-trip integrity holds because both
  representations changed by the same literal string. It exits 3 (deck.json
  updated, html refused) when the renderer entity-escaped the text — then sync
  with a `--quick` render. If NEW is much longer than OLD the tool warns about
  overflow; eyeball or do a `--scope` render when the page was already tight.

  ```text
  ✓ exit 3 = deck.json WAS written but index.html was refused
    (entity-escaped, or match count ≠ 1). The two representations now
    disagree — reconcile before doing anything else:
        render-deck.py <deck.json> <out>/ --quick
  ✗ treat exit 3 like exit 0 and render/deliver as-is (ships deck.json and
    index.html out of sync).
  ```

  Counter-intuitive: this exit code is NOT a 0/1 binary, and `exit 3` here
  (partial write, needs re-render) is a DIFFERENT meaning than `exit 3` in
  deck-cli (schema rollback) — see `references/deck-state-contract.md`.
- **`EDIT` (fragment edit) — the canonical loop (W1/W3, iteration-loop)**:

  ```
  1. Write the fragment files   input/<key>.body.html / input/<key>.css
  2. deck-cli.py <deck.json> set-page <key> --html f.html --css f.css [--lifted]
       ↳ runs the W4 static pre-write lint (off-ladder font-size, dual-anchor,
         P50 base64-in-style …) and REFUSES known gate failures before they
         reach deck.json; optimistic lock + auto-backup included.
  3. render-deck.py <deck.json> <out>/ --iter
       ↳ auto-scopes to the pages whose content changed (sidecar diff — no page
         numbers to compute), skips the autosnapshot, prints a text echo of the
         changed slides + an errors-only digest; full output in
         <out>/last-render.log.
  4. Verify cheap-first: text echo for copy · sNN.thumb.png for layout · full
     sNN.png only when the thumb is ambiguous.
  5. Before any handoff/publish: render-deck.py … --final  (full audits +
     autosnapshot; --iter renders intentionally defer whole-deck checks).
  ```

  **Anti-pattern**: ad-hoc python/heredoc scripts that write deck.json directly.
  They bypass the optimistic lock (concurrent-session clobbering), the auto
  backup, schema-fail rollback, and the pre-write lint — every one of which
  exists because a real session paid for its absence. `set-page` /
  `set --from-file` is the sanctioned write path for fragment payloads.

  **Un-synced browser edits — the clobber guard (F-315, Option A)**: if someone
  edited this deck in the browser edit-mode (`e` + ⌘S — writes `index.html` only,
  never `deck.json`), `deck-cli` / `render` / `import-html-slide` detect it (via the
  `fs-render-sig` stamp) before they touch `deck.json`/`index.html`, and act
  **auto-sync-if-lossless, else refuse**:
  - **raw-slide edits** (lossless) → silently **auto-synced** into `deck.json`
    first, then your command/render proceeds — no action needed, both edits survive.
  - **canvas / schema / baked / chrome edits** (lossy or unfoldable) → **refuse**
    (deck-cli exit 6, render exit 8): handle manually (`sync-index-to-deck.py`,
    re-apply in `deck.json`) or `--force` to DISCARD. Canvas (PPTX-import) decks
    hit this — prefer editing canvas content in `deck.json`, not the browser.

  ```text
  ✓ read the exit code first: deck-cli exit 6 / render exit 8 = REFUSED
    (canvas/schema/baked browser edit not yet in deck.json). Recover the
    手改 first, THEN retry:
        sync-index-to-deck.py <deck-dir>   # fold browser edits back into deck.json
    (or redo the edit in deck.json). raw-slide edits auto-sync — no action.
  ✗ see the refusal and reach for `--force` (silently DISCARDS the user's
    browser 手改).
  ```

  Counter-intuitive: these exit codes are NOT a 0/1 binary, and `exit 6`
  (deck-cli) means a different thing than `exit 3` — see
  `references/deck-state-contract.md`.
  See `references/round-trip-integrity.md` § "Automatic clobber guard".

- **`EDIT` (manual scope)**: when you DO know the page numbers, `--scope N`
  (1-based, e.g. `--scope 3,5`) gives the same scoped render without the
  sidecar diff — it refreshes only those pages in the making-of and skips the
  whole-deck readability advisory + geometry audit, cutting a 50-page re-render
  from ~2m12s to ~12s while still capturing the changed page's screenshot.
  Use `--quick` instead when you don't need the making-of updated this run (skips the
  snapshot entirely, ~12-18s). Full render (no flag) only for a new deck or a
  whole-deck change. See `references/editing-discipline.md` → "Re-render speed".
- **`EDIT` multi-page / clone-to-N** (restyle a divider series, or replicate one
  page's treatment to several pages): read `references/editing-discipline.md` E0
  "Multi-page" FIRST — inspect the model + all targets in ONE parallel batch
  (`deck-map --sections` for positions, `show <key>` for content), `set-page <key>`
  each, then verify them ALL in a single `--scope a,b,c --shoot`. Serializing the
  inspect/verify per page (and re-`--help`-ing settled flags) is the time-sink.
- **`EDIT` insert a NEW page you authored (html+css fragment)**: read
  `references/raw-page-quickstart.md` FIRST (fixed constants — canvas 1920×1080,
  {16,24,28,48} ladder, raw renders no header, motion scope one-liner, `allow`
  syntax — plus the insert/set-page/render recipe and the don't-re-derive speed
  discipline; `#N` from the URL already gives the index, insert range-checks it,
  so do NOT re-confirm the insertion point with repeated deck-map runs). Then use
  **`deck-json/import-html-slide.py`** (Mode A, target = deck.json) — it wraps the
  fragment as a raw slide, validates each candidate, inserts at a numeric index /
  `end` / after-key, and auto re-renders. `--yes` for non-interactive. Do NOT
  hand-roll a one-off "load deck.json → splice → dump" insert script per run —
  this wheel exists and already does backup + validate + re-render. After any
  insert/reorder, `render-deck.py --renumber` refreshes stale `screen_label`
  prefixes. For pages with bespoke entrance motion, verify with
  `assets/capture-frames.py <output>/index.html <key>` (mid+settled frames,
  settle assertions — see `references/motion-system.md` §3.4).
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
  swapped.
  - **Into a BRAND-NEW deck** ("开个新 deck 复用某页"): use
    `deck-json/lift-to-new-deck.py SRC PAGES DEST [--new-key K] [--render]`. It
    scaffolds a schema-valid deck.json then delegates each slide copy to
    `deck-cli.py paste`, so the embedded scoped CSS is rekeyed, assets copied,
    and `lifted` stamped — no hand-built deck.json (that path repeatedly failed
    on bad `deck.mode` enum / missing render args / forgotten CSS rekey).
  - **Into an EXISTING deck.json**: `deck-cli.py paste` for DeckJSON-native
    sources; `assets/lift-slides.py --shake` for foreign or older HTML sources.
  - Then swap copy with `deck-json/apply-text-pairs.py` (deterministic text
    replacement). Resolve source/target pages with `deck-json/locate-slide.py`;
    after lift/insert/reorder, run `render-deck.py --renumber` on the target
    DeckJSON when stale `screen_label` prefixes need to match true page/hash
    order (`lift-to-new-deck.py --render` already passes `--renumber`).
- **Scan the source FIRST: `assets/lift-slides.py SRC/index.html --scan`.** It
  sweeps the whole deck in one read and flags every frame a deck.json lift CANNOT
  carry — iframe demos (`iframe-embed` / `src=about:blank`, populated by the
  source's JS), image-slot placeholders (`photo-cell`/`poster-img`/`role=img`
  with no static image → photos land EMPTY), and frames the lifter can't parse.
  Plan these up front instead of discovering them page-by-page after the lift: an
  iframe page is re-homed via `deck-cli.py paste --from <src deck.json> --key
  <key>` (carries the prototype + keeps the `iframe-embed` schema), NOT lifted to
  raw; image-slot pages lift but need real images re-attached afterward.
- **Default to `--shake` when the source slide is a SCHEMA layout**
  (content-*/stats/flow/chart/table/arch-stack/image-text/logo-wall/section/
  iframe-embed). A deck.json lift converts the slide to `layout:raw`, and the
  framework `[data-layout=X]` CSS that styled it does NOT follow a raw slide, so
  without `--shake` the layout silently collapses. `--shake` inlines that
  framework CSS (and recovers source-head per-slide rules). Skip `--shake` ONLY
  for a source page already `layout:raw` AND self-contained (`--preview` →
  `self_contained:true`, `recommend_shake:false`). When unsure, shake: it is
  over-inclusive by design and the only cost is pruning dead-rule cruft (which
  renders harmlessly) vs. a collapsed layout. NOTE: `--preview`'s
  `recommend_shake` only inspects source-head coupling — it can read `false` for a
  schema page that still needs the framework-CSS inline (use `--against
  DST/index.html`, which adds the `target_lacks_layout_css` check), so prefer this
  schema-layout rule over a bare per-page `recommend_shake`.
- **Lift into HTML target without DeckJSON**: when the destination is a deck with no
  `deck.json`, do not hand-splice frames. Use the HTML destination mode:

  ```bash
  python3 assets/lift-slides.py SRC/index.html --preview --key <key> [--against DST/index.html]
  python3 assets/lift-slides.py SRC/index.html --key <key> DST/index.html [--pos N|end] [--shake]
  ```

  Add `--shake` per the schema-layout rule above (any schema layout needs it so
  its framework `[data-layout=X]` CSS survives lift-to-raw; a source page already
  `layout:raw` AND self-contained may skip it). `lift-slides.py --to-html`
  extracts the rendered frame, transforms assets/CSS with the same logic as
  DeckJSON lift, splices into `.deck`, backs up, and validates the inserted page.
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

  ```text
  ✓ default run = dry-run (plan only, writes nothing); read the plan, THEN:
        deck-json/repair-lifted.py <deck>            # preview
        deck-json/repair-lifted.py <deck> --apply    # run, after confirming
  ✗ go straight to `--apply` and mutate in place with no preview.
  ```

  Counter-intuitive: exit codes here are NOT a 0/1 binary — `--apply`
  transparently passes through whichever sub-tool's exit code (e.g. a
  schema rollback) failed; see `references/deck-state-contract.md`.
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
- **Never print a whole raw `data.html` to find one element** — raw pages run to
  100s of KB. Excerpt instead:
  `deck-json/locate-slide.py <deck> <page|key|all> --grep PATTERN [--context N]`
  searches the selected slides' `data.html` + `custom_css` and prints each hit
  with source + char offset + ±context. Then do the edit with an exact-string
  replace anchored on what the grep showed (assert match-count==1 first).

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
- `../../deck-json/_lint_fragment.py` — W4 static pre-write lint (also a CLI:
  `--html f --css f`); constants parsed from `assets/audits.js`, single source
- `../../deck-json/fast-text.py` — F-303 sub-second pure-copy edit: dual-write
  deck.json + index.html, no render/validation; hard guardrails (count==1 both
  sides, refuses DOM chars, JSON-corruption refused-and-restored).
- `../../deck-json/conform-to-deck.py` — F-300 family-drift detector + conformer
  for a page ADOPTED into an existing deck. Read-only drift table by default
  (D1 page-bg / D2 title placement / D3 pre-title chrome / D4 font ladder / D5
  body luminance, each vs the sibling-content-page consensus); `--apply` runs the
  three deterministic conforms (D1/D3/D4) with backup + optimistic-lock +
  validate-with-rollback. D2/D5 are report-only. Also runs read-only as a step in
  `repair-lifted.py`, and is the source-of-truth for the soft `R-FAMILY-DRIFT`
  advisory in `validate-deck.py`.
- `../../assets/grow-box-fit.py`
- `../../assets/shoot-page.py` — F-304 deterministic ad-hoc page screenshot:
  route-aborts external http(s) by default, so a deck embedding a LIVE iframe
  (larkoffice doc / web dashboard) still shoots in ~2s instead of hanging the
  30s `load` timeout / "waiting for fonts" stall. Use this (or render's
  deck-log auto-snapshot) for quick looks; never hand-roll a
  `wait_until='load'` Playwright shot against such decks. See
  prototype-embed.md F-304 for whether a live iframe belongs in the deck at all.
- `../../deck-json/import-html-slide.py` — insert authored html+css fragments as
  raw slides (per-fragment validate + position pick + auto re-render); the
  sanctioned path for "add one new page to an existing deck".
- `../../assets/capture-frames.py` — bespoke-motion pages: one command for
  mid+settled frame capture + §3.5 settle assertions (motion-system.md §3.4).
- `../../references/deck-state-contract.md` — single-source contract for deck.json
  / deck-cli state + errors + exit codes (per-tool, non-binary; `exit 3` differs
  between deck-cli and fast-text).
