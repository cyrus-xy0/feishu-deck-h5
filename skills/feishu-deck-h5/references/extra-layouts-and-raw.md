# extra-layouts-and-raw — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:加新 layout 的 parity 契约 / 手写 raw 稠密版式

## Phase 1.c extras — parity contract + regression smoke test (mandatory)

There are TWO tiers of layouts in this skill:

- **Original 10–13 layouts** — `cover / agenda / section / content-3up /
  content-2col / quote / stats(row,hero) / big-stat / image-text / table /
  flow(timeline,process) / end`. CSS in `assets/feishu-deck.css`. Fully
  parity'd with master spec (header position, content-bg, R48 centering,
  etc.). Battle-tested via sample-deck.json + phase-1a/1b demos.

- **Phase 1.c extras** (added after the original set) — `content-before-after /
  content-blocks / content-matrix / content-story-case / flow-tree /
  flow-swim / stats-waterfall / arch-stack / logo-wall / replica`. CSS in
  `deck-json/templates/extra-layouts.css`. Most use brand-new `data-layout`
  values (`matrix-2x2`, `issue-tree`, `flow-swim`, `waterfall`, `arch-stack`,
  `logo-wall`, `content-before-after`); a few reuse original `data-layout`
  values (`content-blocks → content-2col`, `content-story-case → content-2col`,
  `replica → image-text`).

### Why this section exists

Audit 2026-05-21 found that ALL 7 new-`data-layout` extras shipped without:

- `.header` positioning (titles dropped into flow → stuck top-left of slide)
- Slide background image (looked unbranded vs originals' dark ambient bg)
- Default centering (no R48 equivalent)
- Multiple hero-context label floor violations (16 px chrome on axis names /
  industry tags / row headers that are actually content — should be ≥ 24)

The gap existed for ~3 weeks unnoticed because **zero examples used any of
the 7 new layouts**. sample-deck + phase-1a/1b demos all stopped at the
original 13. Without an example exercising the extras, validator-pass said
nothing about visual correctness.

### The contract (mandatory when adding a new layout)

**Three steps. Skip any one and the layout WILL ship with bugs:**

1. **CSS rules in `extra-layouts.css`**. Add `.slide[data-layout="X"]`
   selectors to the unified `.header`, present-mode bg, and scroll-mode
   bg lists at the **top of file** (the "Framework parity" block).
   Then write the layout-specific rules.

2. **Add a slide to `deck-json/examples/phase-1c-extras.json`** exercising
   the new layout with realistic content (≥ minimum schema fields,
   meaningful labels not just "lorem ipsum"). This is the regression deck.

3. **Render the regression deck + eyeball every slide**:
   ```bash
   python3 skills/feishu-deck-h5/deck-json/render-deck.py \
     skills/feishu-deck-h5/deck-json/examples/phase-1c-extras.json \
     skills/feishu-deck-h5/deck-json/examples/phase-1c-extras-out/
   ```
   Open `phase-1c-extras-out/index.html` and visually verify:
   - Title sits at master coords (top:61, left:73), not at slide top
   - Background is dark ambient gradient, not flat black
   - Content fills stage, no large empty regions stranded at top/bottom
   - Labels next to hero-anchor content are ≥ 24 px (Body tier), not 16 px
   - Horizontal/vertical alignment looks deliberate (no off-by-N misalignment)

### Other gotchas surfaced 2026-05-21

- **CSS var URL resolution across files**: `var(--fs-asset-content-bg)`
  is defined in feishu-deck.css with `url("lark-content-bg.jpg")`. When
  used inside a `background:` declaration in extra-layouts.css (different
  file), the URL may NOT resolve correctly in some browser engines (spec
  says relative to declaration site, but practice varies). Workaround:
  use direct relative URLs in extra-layouts.css —
  `background: #000 url("../../assets/lark-content-bg.jpg") center/cover no-repeat;`
  — instead of `var(--fs-asset-content-bg)`.

- **Waterfall label area must be padding-reserved, not flex-stacked**:
  if `.label` and `.sublabel` sit in `.bar`'s flex flow, bars with vs
  without sublabel get DIFFERENT label-area heights, so col bottoms
  misalign across bars ("柱子不在一个平面"). Pattern that works:
  - `.bar { padding-bottom: 96px; justify-content: end; }` — reserves
    fixed area at bottom for label, pushes col flush against it
  - `.label / .sublabel { position: absolute; bottom: <fixed>; }` —
    anchor labels to bar bottom inside the padding zone, decoupled
    from flex flow
  - X-axis line `.chart::after { bottom: 96px; }` — same offset as
    `.bar { padding-bottom }`, so axis aligns to col bottoms
  - `.chart` MUST NOT also set its own `padding-bottom` — the bar's
    padding-bottom is the only reservation; chart adding more
    double-counts and the axis floats below col bottoms.

- **Issue-tree connector lines**: the renderer NEVER injects the SVG
  the schema description promises. CSS pseudo-elements draw lines
  instead: `.connector::before` (vertical trunk, `top:25% bottom:25%`),
  `.connector::after` (root→trunk horizontal stub), `.branch::before`
  (trunk→b1 stub), plus matching trio on `.b1-conn` and `.leaf::before`
  for branch→leaves fork. Works for 2-branch / 2-leaf shapes; 3+ needs
  either renderer-side measurement OR a smarter CSS calc.

- **Replica mode is intentionally chrome-less**: no title, no stage
  content, no wordmark — just a full-bleed page image. If the example
  page_image is a small logo PNG instead of a real PDF page, the slide
  looks "empty" (small image floating). Use a placeholder that
  self-documents — see `replica-placeholder.svg` in examples/.

### 2026-05-21 fix batch (history)

If you see one of these patterns on a Phase 1.c layout, it's likely
fixed already — search extra-layouts.css comments for `2026-05-21`:

| Layout | What was wrong | Where it lived |
|---|---|---|
| All 7 extras | `.header` no positioning | feishu-deck.css unified rule hardcoded 8 names |
| All 7 extras | Background unset in present-mode | Same — slide-frame `:has()` list hardcoded |
| matrix-2x2 | axis names / labels / quadrant titles at 16 chrome | Should be 24-28 (Body / Sub tiers) |
| story-case | industry-tag at 16 chrome | Content categorization, → 24 Body |
| story-case | `.story-arc .lbl` (痛点/冲突/etc.) at 16 | Content row header, → 24 Body (widen column 88→120) |
| logo-wall | ind-name at 16 chrome | Industry label is content, → 24 (widen column 200→280) |
| waterfall | col bottoms misaligned across bars | Mixed-sublabel-presence; absolute-position label/sublabel |
| waterfall | X-axis floated above/below col bottom | Chart had double `padding-bottom` |
| waterfall | footnote rendered at slide top | No `.slide[data-layout="waterfall"] .footnote` positioning rule |
| issue-tree | Connector lines absent | Schema said renderer injects SVG; renderer didn't. CSS pseudo-element workaround |
| flow-swim | Lane names had thin colored border + dark bg | User asked for full-color tinted fill (gradient brand→0.75) |
| replica | "完全看不见内容" smoke test | Placeholder was tiny logo PNG; replaced with self-documenting SVG mock |

### 2026-05-22 fix batch — raw-layout stage geometry + silent text clip

Three related framework gaps surfaced together while building a dense 3-up
narrative slide (`taste-shifts-3pains`). Codify them so the next author
doesn't re-discover.

**Gap 1 — `.stage` default is 680 tall, NOT slide-full (1080)**:

Framework's `.slide .stage` for content layouts is sized to leave room for
header + footer chrome. Internal measurement: stage clientHeight = 680.
This means any `.stage > .grid { position: absolute; top:X; bottom:Y }`
positioning is **relative to a 680 px stage**, not the 1080 px slide.

For raw layouts (`layout: "raw"` + `_orig_layout: "content-*"`) that want
near-full-slide layouts (header overlay + big content + bottom band),
you MUST explicitly override stage to fill the slide:

```css
.slide[data-slide-key='X'] .stage {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  padding: 0;
}
```

Otherwise your grid coordinates measure off the wrong reference, and
"top:140 bottom:170" gives a 370 px grid instead of the expected 770 px.
You won't see this from static CSS — render and measure `clientHeight`.

**Gap 2 — `R-VIS-CARD-OVERFLOW` audit (added 2026-05-22)**:

Cards with `overflow: hidden` that have `scrollHeight > clientHeight` are
**silently clipping content**. Static validator sees nothing wrong (the
card itself fits in canvas; R-OVERFLOW is slide-level only). User sees
text mysteriously cut off.

Added `R-VIS-CARD-OVERFLOW` to `validate.py` visual audit JS — walks every
`.stage *` element, checks `getComputedStyle().overflow{,Y} === 'hidden'`
+ `scrollHeight > clientHeight + 4 px tolerance`. Reports selector +
overflow delta. Fires on the deck rendered with Playwright.

Run via `python3 render-deck.py deck.json out/ --visual` (the flag is new
too — see Gap 3) or `bash check-only.sh out/index.html --visual`.

Fix when triggered: shorten body copy, drop a row, shrink padding/gap,
or **drop `overflow: hidden`** so the issue is at least VISIBLE rather
than silently swallowed.

**Gap 3 — `render-deck.py --visual` flag (added 2026-05-22)**:

Previously `render-deck.py` always ran static validator with `--no-visual`
hardcoded. To get visual audits you had to manually chain
`check-only.sh --visual` after each render — easy to forget, and the
silent-clip bugs accumulated.

Now `render-deck.py deck.json out/ --visual` runs static + visual in
one shot (~2 s overhead for typical 5-10 slide decks). For dense decks
authored with raw layouts especially, **always render with `--visual`
on the last iteration** before delivery.

**Authoring pattern — flex column with `justify-content: center` is the default**:

The cleanest raw-layout pattern for "header + content + bottom band"
when content is shorter than available stage height:

```css
.stage {
  position: absolute; top: 130px; left: 48px; right: 48px; bottom: 32px;
  display: flex; flex-direction: column;
  gap: 28px;                    /* spacing between flow blocks */
  justify-content: center;      /* DEFAULT — center the group vertically */
}
.stage > .grid { position: static; display: grid; ... }
.stage > .anchor-band { position: static; ... }
```

Children flow naturally. Cards size to content. Anchor sits right
below grid with `gap: 28` spacing. **`justify-content: center` is the
right default** — the whole content group (grid + anchor) centers
vertically in the stage, with equal breathing room above and below.

**Why `flex-start` is wrong as default**: with `flex-start`, content
hugs top of stage and leaves a big empty band at slide bottom —
visually "stranded" / "top-heavy". The same R48 default-centering
problem that hit fixed-shape layouts (content-3up / content-2col /
agenda / stats / big-stat / quote) applies to flex columns too.

Use `flex-start` ONLY when you have a TALL stage container holding
a sparse top-anchored layout (e.g. one big hero + small footer
intentionally hugging top). For 99% of "header + body + anchor"
cases, `center` is correct.

No absolute-positioning math, no "why is there a 136 px gap"
mystery. flex column with center auto-handles spacing AND placement.

---

