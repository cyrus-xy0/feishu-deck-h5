# editing-discipline — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:删/插/重排/自定义 layout 编辑(E1-E5 细节)

## EDITING DISCIPLINE (mandatory) — high-cost bugs to avoid

These four failure modes recurred in the 2026-05-14 CTG run and burned
30+ minutes of debug time each. Read this section BEFORE doing any
delete-slide / insert-slide / reorder-slide / custom-layout work.

## Adding content to a `raw` / `lifted` card — measure geometry, not the box

When you ADD a visual element or extra text to a hand-authored `raw` slide
(new band / rail / extra feature row), a `min-height` or the legacy
`.slide .grid .card { align-self: stretch }` can inflate the card box so it
LOOKS like it fits — the box grows, `scrollHeight ≈ clientHeight`, and a quick
`card.getBoundingClientRect()` vs the strap shows a healthy gap — while the box
itself overflows its `.grid` and the **centered** content silently overlaps the
sibling strap. Measure the right things before declaring done:

- container `el.scrollHeight > el.clientHeight` (does content overflow its box?),
- the `.grid` (or stage child) the card lives in — same check,
- the **last content child** `.bottom` vs the **next sibling**'s `.top` (real
  collision), NOT just the card's bounding box.

`render-deck.py` now BLOCKS on the hard geometry rules
(`R-VIS-CARD-OVERFLOW` / `R-OVERLAP` / `R-OVERFLOW` / `R-VIS-BAND-COLLIDE`) for
full `/runs/` renders, but a scoped / `--quick` / `DECK_ALLOW_GEOM_OVERFLOW=1`
render skips that gate — so on those paths this manual check is on you. See
`references/troubleshooting.md` ("Render says PASS yet a card's text spills").

## Editing Copy

The correct path for copy changes is `deck.json` → rerender. Do not post-render
edit `index.html` unless intentionally doing browser edit mode followed by
round-trip recovery.

Examples:

```bash
python3 skills/feishu-deck-h5/deck-json/deck-cli.py runs/<ts>/output/deck.json set slides.3.data.title "新标题"
python3 skills/feishu-deck-h5/deck-json/deck-cli.py runs/<ts>/output/deck.json set slides.3.data.cards.0.body "新正文"
python3 skills/feishu-deck-h5/deck-json/render-deck.py runs/<ts>/output/deck.json runs/<ts>/output/ --quick
```

### Re-render speed: scope the render to the page(s) you edited

A full `render-deck.py` does THREE whole-deck Playwright loads — the F-253
readability advisory, the making-of auto-snapshot screenshots, and (inside the
snapshot) the geometry audit — plus the fit-check. Those whole-deck passes exist
for GENERATION; re-running them after a one-page edit re-audits 49 pages you never
touched.

**The locked edit scope is the boundary. Pass it to the renderer.** Two flags:

- **`--scope N`** (preferred for a confined edit — `--scope 1`, `--scope 3,5`):
  re-render, then refresh ONLY pages N in the making-of (`deck-log snapshot
  --slide N`). The changed page's screenshot still lands in the log; the
  whole-deck advisory + geometry audit + re-shoot of unchanged pages are skipped.
  Implies `--skip-fit-check`. **~2m12s → ~12s.**
- **`--quick`** (text-only, and you don't need the making-of updated this run):
  skips the snapshot ENTIRELY. Same speed as `--scope` now, but the edit won't
  show in the making-of until the next real snapshot. **~2m12s → ~12-18s.**

| render | time | making-of updated? | what runs |
| --- | --- | --- | --- |
| default (full) | ~30-60s | yes (whole deck) | fit-check + advisory + audit + full snapshot |
| `--scope N` | **~12s** | yes (page N only) | static validator + 1-page snapshot |
| `--quick` | ~12-18s | no | static validator only |

Default to `--scope N` for scope-locked edits — it now matches `--quick` on speed
while ALSO keeping the changed-page screenshot. Use the full render (no flag) only
for a new deck or a change that spans the whole deck.

> **Why `--scope N` is ~12s and not ~60s (2026-06-06):** the headless-browser
> entry points used to `goto(wait_until='load')`, which stalls ~31s on this deck
> because the embedded live demo never fires `load`. All five screenshot/audit
> drivers (`deck-log.py`, `check-distribution.py`, `validate.py`, `run-audits.py`,
> `reconcile-reflow.py`) now use `domcontentloaded` + a *bounded* 4s best-effort
> `load` wait + `fonts.ready` + a `.deck[data-js-ready]` framework-ready gate.
> Fast decks still get true-load fidelity in ~1s; a hung sub-resource caps at ~4s
> instead of ~31s. Verified pixel-equivalent to the old `load` captures (incl. the
> demo page) — the `data-js-ready` gate is what prevents a blank/un-revealed
> capture. If you add a new Playwright driver, copy this settle block; do NOT
> reintroduce a bare `wait_until='load'`.

The old `texts.md` / `apply-texts.py` sidecar flow is retired. Residual
`data-text-id` attributes in old decks are harmless, but do not author new flows
around them.

### Browser edit mode (downstream reviewers)

The rendered deck ships with a built-in client-side visual editor
(`assets/edit-mode/deck-edit-mode.{css,js}`, default-on). For downstream
reviewers who only need copy tweaks and don't have the CLI:

- Press **E** in the browser to enter edit mode, click any text to edit it
  in place, press **Esc** to exit, and **Cmd/Ctrl+S** to save.
- This edits the rendered **`index.html`**, NOT `deck.json` — so it is exactly
  the post-render drift the ROUND-TRIP INTEGRITY rule warns about. The change
  lives only in `index.html` and will be destroyed by the next re-render, fork,
  or downstream tool that reads `deck.json`.

### Drift recovery — port browser edits back to deck.json

If you (or a reviewer) made edits in browser edit mode, port them back into
`deck.json` before delivery / fork / library ingest so re-render stays
byte-identical:

```bash
python3 skills/feishu-deck-h5/deck-json/sync-index-to-deck.py \
  runs/<ts>/output/index.html runs/<ts>/output/deck.json --dry-run
# review the diff, then drop --dry-run to write it back
python3 skills/feishu-deck-h5/deck-json/sync-index-to-deck.py \
  runs/<ts>/output/index.html runs/<ts>/output/deck.json
```

`sync-index-to-deck.py` matches each `.slide` by `data-slide-key`, overwrites the
matching slide's `data.html`, and (with `--force`) can downgrade template slides
to `layout: raw` — lossy on structured fields, so prefer editing `deck.json`
directly when you can. See `round-trip-integrity.md` for the full two-halves rule
and fork/clone parity checks.

### Stable `data-slide-key` is mandatory — no key, no locator, no slice

Every `.slide` must have a stable semantic `data-slide-key`: unique within the
deck, kebab-case, NOT positional (`slide-01` / `page-7`), and stable across
reorder. Hand-authored / lifted HTML must add or preserve it before delivery or
library ingest.

The hazard chain: **无 key → 无 locator → 切片不可索引**. Without a stable key,
`sync-index-to-deck.py` cannot find the matching slide (no locator), so
browser edits cannot be ported back; and the slide-library cannot index the
slice for reuse. A positional key looks stable until the first reorder, then
silently points at the wrong slide.

### E1. Identifier sync on delete/insert — what's mandatory vs conditional

A slide can carry up to three numeric identifiers, at different DOM levels:

| Identifier | Lives on | Status | Used for |
|---|---|---|---|
| `data-screen-label="NN Title"` | `.slide` element | **mandatory** | present-mode pager UI label; validator R02 requires it |
| `data-page="NN"` | `.slide-frame` wrapper | **conditional — only when the slide has per-page scoped CSS** | per-page `[data-page="07"] .card { ... }` overrides authored in the deck's inline `<style>` |

`data-screen-label` is always required (validator enforces). `data-page`
is **purely a CSS-scoping handle** the author opts into when they need
per-page overrides — most Path A (template-rendered) slides don't have
it at all (Opple deck: 0/51 frames carry `data-page`; CTG deck: 36/53
have it because that deck has heavy per-page custom CSS).

**Renumber ritual on delete / insert / reorder** — only update the
identifiers that EXIST on the affected slides:

1. Decide the new ordinal map (e.g. inserting at position 7 → all
   positions ≥ 7 shift +1).
2. **Always** — update `data-screen-label="NN Title"` on every affected
   `.slide`.
3. **Only if `data-page="NN"` is on the affected `.slide-frame`** —
   renumber it too, AND grep for `[data-page="OLDNN"]` selectors in the
   deck's `<style>` blocks and renumber those to match. Skipping this
   leaves per-page CSS attached to the wrong frame (this is the bug
   that gave "第三页样式不对" in the 2026-05-14 CTG run; the slide had
   `data-page="03"` plus a `[data-page="03"] .card { … }` rule, and the
   renumber missed the frame attribute, so the rule fired on the wrong
   page after the delete).
4. Run `python3 assets/validate.py runs/<ts>/output/index.html` —
   R-DOM catches missing `</div>`, R20 catches per-page CSS that's off
   the type-scale ladder.

**The deck on disk is your source of truth** for which identifiers
each slide carries — there is no "every slide MUST have data-page"
rule; it's purely conditional on whether per-page CSS exists.

If you find this ritual error-prone, prefer rewriting the slide list
end-to-end (regenerate with fresh ordinals 01..NN) rather than splicing
in place. The validator's R-DOM rule catches the most catastrophic case
(slide-frame nesting from regex-eaten `</div>`); the identifier sync
is editorial — only you can do it right.

### E2. Don't use sed / regex / text substitution to edit slide-frames

Three separate bugs in the CTG run came from using Python regex to splice
HTML for slide insertion / deletion / column-content rotation:

- `(<div class="slide-frame"...)` matched mid-frame instead of frame-start
  because the regex didn't anchor to the `<div ` token boundary. Result:
  insertion landed inside an existing slide-frame, nesting 7 subsequent
  frames inside it. Present mode hid them all (they never became "current").
- `</[a-zA-Z]+>` was the close-tag pattern used in a column-content
  rotation. It correctly closes `</span>` and `</p>` but does NOT match
  `</h3>` (HTML allows digits in tag names; `[a-zA-Z]+` excludes them).
  Result: regex consumed past the h3 and ate the entire next column's
  markup until it found a `</span>` further down.
- Plain text replacement of "第一段" → "新内容" stripped a closing `</div>`
  that lived inside the matched span.

**Rule**: do not use regex / sed / plain text replacement to manipulate
slide DOM structure. For editorial text changes edit `deck.json` (schema
field or a `layout: raw` slide's `data.html`) and re-render — or use
`deck-cli set slides.N.data.<field> "…"`. For structural changes
(insert / delete / move slide), do it by reading the file, identifying
the slide blocks manually, and writing back the full sequence (or, for
Path A decks, mutate `deck.json` and re-render).

**Safety net**: after every structural change, run validator R-DOM
(`audit_dom_integrity` in `validate.py`). It catches the catastrophic
nesting case automatically — every `.slide-frame` must be a direct
child of `.deck`, every frame must hold exactly one `.slide`, and
`<div>` opens must balance closes inside `<body>`. A structural API
helper (`assets/dom-ops.py`) may be added later if the rule proves
insufficient on its own; until then, R-DOM IS the structural defense.

### E3. Custom-layout selectors have lower specificity than framework defaults

Every framework `.slide[data-layout="..."] .grid { ... }` rule has
specificity `(0,2,0)` — one class + one attribute = 2 classes equivalent.
A naively-written custom layout `.slide-vs-wecom .grid { ... }` has
specificity `(0,2,0)` too — same level — but loses the cascade to the
framework because the framework rule was DECLARED LATER.

**Failure mode**: author writes `<div class="slide slide-vs-wecom"
data-layout="content-3up">` and defines `.slide-vs-wecom .grid {
display: flex; gap: 64px }`. Framework rule
`.slide[data-layout="content-3up"] .grid { display: grid;
grid-template-columns: 1fr 1fr 1fr; ... }` wins. The flex layout
silently doesn't apply. Content overflows 1080.

**Three ways to authoring around it**, in order of preference:

1. **Bump specificity by combining classes**: write
   `.slide.slide-vs-wecom .grid { ... }` (specificity `(0,3,0)`) — wins
   over the framework's `(0,2,0)` cleanly.
2. **Use `!important` on the directional / structural properties** —
   `display: flex !important; flex-direction: row !important;` — works
   but pollutes; reserve for layout direction, NOT for cosmetic values.
3. **Use absolute positioning** for the children of your custom layout
   instead of flex/grid. Specificity matters less when each child has
   its own `position: absolute; top: ...; left: ...`.

Watch out for the related trap: don't name your custom class with a
reserved framework class name (`.tile`, `.pill`, `.card`, `.eyebrow`,
`.keyline`, `.title-zh`, `.wordmark`, `.stage`, `.header`, `.footer`,
`.deck`, `.slide`, `.slide-frame`). See "Reserved class names" section
for the full list — collisions cause force-shrink and other surprise
behavior beyond just specificity.

### E4. Pre-delivery R06 / R20 enforcement is NOT optional

The validator already enforces:
- **R06** — body text ≥ 22 px on slide content; chrome ≥ 14 px.
- **R20** — every `font-size` in per-page `<style>` blocks must come from
  the modular type-scale ladder `{10, 11, 12, 13, 14, 18, 22, 28, 38,
  44, 52, 56, 64, 88, 100, 132, 160}`.
- **R-WHITE-TEXT** — content text on dark slides must be `#fff`, never
  `rgba(255,255,255,X<1)`. Low-opacity white reads as gray when
  projected.

These rules existed before the CTG run, but they were violated **at
least 4 times** in that run because the agent wrote inline `<style>` and
shipped without re-validating. Users had to flag the under-floor fonts
every single time.

**Workflow rule for the agent**:

After every Edit that touches CSS inside a `<style>` block of the deck —
especially per-page `<style data-page="NN">` blocks — IMMEDIATELY run:

```bash
python3 assets/validate.py runs/<ts>/output/index.html
```

Don't wait until "final delivery". Don't trust visual eyeballing for
font-size rules — what looks fine on a desktop preview vanishes on a
projector. R06 / R20 / R-WHITE-TEXT exist exactly because human
judgment fails on these consistently.

Treat each violation as a delivery blocker. If you write 16 px because
you think it fits, the rule still rejects — fix to 14 (chrome) or 18
(pill) or 22 (body), not 16.

### E5. Delete an element → rebalance the rest in the same pass (mandatory)

When the user says "删 X" / "去掉 Y" / "Z 不要了",**the task is two
operations, not one**: (1) remove the element, AND (2) rebalance the
surrounding layout so the deleted slot doesn't leave a visible hole.
Validator PASS ≠ visually balanced. Shipping a "successfully deleted"
deck with a giant blank in the middle is failure, even if every R-rule
passes.

**Why this is mandatory** (user feedback 2026-05-22 · slide 15 after
deleting the closing block + the flow-row + the subtitle):

> "这么改完中间太空了,这个你不觉得难看么?为什么要这样设计,之后别这样了"

The agent had treated "delete the closing 3-line block" as a textual
removal and shipped without checking that the remaining `.ttl-block +
.preface + .dept-grid` now top-aligned with a half-screen blank below.
The `dept-grid { flex: 1 }` did fill the space, but each card's interior
content (5 short children + `margin-top: auto` on `.card-stuck`) only
filled ~60% of the now-taller card → ugly empty middles in every card.

Three deletion symptoms that ALWAYS need rebalancing:

| Symptom of recent deletion | Rebalance action |
|---|---|
| `.stage` flex-column lost a child → top-aligned remainder with bottom blank | Add `justify-content: center` (or `space-between`) on `.stage` so the remaining group sits visually centered, not stuck-top. Reference: R48 default centering. |
| Grid row was occupied by deleted element → leftover row stretch grew the rest | Either shrink `grid-template-rows` to match the new row count, OR drop `flex: 1` on the grid so it sizes to content + center it in `.stage`. Reference: BF3 stretch overshoot. |
| Card had N fields with `margin-top: auto` on one (pushing it to bottom); now N-1 fields | Drop `margin-top: auto`, change card to `justify-content: space-between`. The auto-margin trick assumes a specific child count; deleting breaks the assumption. Reference: BF9. |
| Subtitle deleted, title now alone at top | Either bump title font (36→48), or increase `margin-top` on the title so it sits in the visual upper-third instead of pinned to the top edge. |
| Removed 1-2 cards from a `repeat(N, 1fr)` grid | Drop N by 1 (`repeat(N-1, 1fr)`), don't leave the grid with one stretched orphan cell. |

**Mechanical checklist** (run mentally after every Edit that removes
DOM content):

1. Squint at the slide at 1/3 zoom — is there a visible blank band
   (top, middle, or bottom)?
2. If yes, identify which container houses the blank (stage / grid /
   card).
3. Apply the matching fix from the table above.
4. Re-render. Re-squint. If still blank, repeat.

**Anti-pattern**: delete → render → "完成了 · PASS" → ship. This is the
exact failure mode the user called out. Even if the validator is green,
**you owe a visual rebalance pass**.

**Trigger scope (mandatory — broader than "after delete")**: the squint
check + rebalance flow above must run whenever you touch a slide for
ANY of these reasons:

- You **deleted** DOM content (the original trigger).
- You **edited / fixed / restyled** a slide the user pointed at
  ("这页有问题", "改一下 #NN", "看看 slide NN").
- You **inherited** a slide from another flow / earlier in the session
  / another deck and the user is now asking you to look at it.
- You're about to **deliver / hand off** the deck or any specific page.

Common failure pattern (2026-05-22 · slide 17 NPD-4-stage): a slide
ships with `.acts { flex: 1 }` containing only 3 short act rows →
container stretches, content top-aligns, bottom half empty. The slide
was authored by another flow, not by my edit, so E5's "after delete"
trigger never fired. The user catches "中间还是空着好多内容,刚加的
规则怎么没实现" — they're right. The rule is about **the visual end
state**, not just about who edited last. **If you're looking at a
slide for any reason, you own the squint check**.

The 30-second squint pass is cheap. Shipping a holed-out slide and
being told "你不觉得难看么" is expensive.

**Watch for the inverse trap too**: if the user ADDS content, check
whether the now-fuller layout has the OPPOSITE problem (overflow,
R-VIS-CARD-OVERFLOW, cards too tall to fit). Add and delete are symmetric
— both shift the layout, both need a rebalance check.

---

### E6. Local single-element nudge → do NOT rebalance the whole container (mandatory)

E5's mirror image. When the user asks to move/space **one named
element** ("这条收口句离卡片太远,移近点" / "把这个标签往上挪一点"),
**never achieve it by changing the container's alignment** (e.g. flipping
`.stage` from `justify-content: space-between` to `center`). That
silently relocates every *other* anchor in the same container — **above
all, the title.**

**Why this is mandatory** (user feedback 2026-05-31 · zhongan deck,
flywheel page): to "move the closing line nearer the cards" the agent
changed `.stage` to `center`, which pushed the title **down 62px**. The
user caught it on sight: a single-element request had quietly moved an
element they never named.

**The hard rule — `R-VIS-TITLE-GAP`'s creed:「标题不动,压内容/下移正文」.**
The title (and every anchor the user did NOT name) keeps its **exact
original position**.

**The validator will NOT save you on `raw` pages.** `R-VIS-TITLE-POSITION`
only watches `.header`'s absolute `top` (≈61) and **skips
`display:none` headers**. A `layout: raw` page typically does
`.header { display:none }` + a bespoke `.ttl-block` standing in as the
title → the validator never recognizes it as a title, so a moved title
goes **unreported**. On raw pages this rule is yours to enforce by hand.

**How to apply:**

1. Change **only that element's own** `margin` (or wrap the "lower
   group" into a sub-group and center/space *that*) — never re-center
   the whole `.stage`.
2. Before editing a raw-page layout, ask: *will this move the title?*
   If yes, pick a different mechanism.
3. After the edit, **measure `titleTop` with Playwright and confirm it
   did not change.** Static validation can't prove this on raw pages.

Cross-ref: E5 (when you SHOULD rebalance — after a delete) is the
complement; E6 is the boundary that stops over-rebalancing on a local
nudge.

---

