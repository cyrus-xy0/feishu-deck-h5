# CHANGES — feishu-deck-h5 历史/已固化的修复记录
> 从 SKILL.md 拆出(F-30)。这些防御的可执行部分已固化进 feishu-deck.css / validate.py;此处仅留叙事供追溯。

## R-ESC-HTML — 裸 HTML 进转义字段变"乱码" 硬闸(2026-05-31)

裸 `<span class="hl">` / `<br>` 写进 schema 转义文本字段(content/3up 等的
`lede` / `body` / `title` 走 `{{ field }}` → `_esc_br`)→ 渲染成 `&lt;span&gt;`
字面文本,客户看到一串代码("乱码")。validator 现扫渲染产物里**被转义的标签
指纹**(`&lt;br&gt;` / `&lt;/span&gt;` 等闭合形,或 `&lt;span class=` 等带属性
开标签),命中即 err 阻断。`{{{ raw }}}` 字段 / `layout:raw` 输出真标签(不会变
`&lt;`)不误报;math/prose 比较符("并发 < 16"、"0 < a < b")因要求标签名紧贴
`&lt;` 且呈真标签形态也不误报。修法:改 `layout:raw` 自控 markup,或换行用 `\n`。
实现 `assets/_validate_audits.py::audit_escaped_html`。

## Layer-1 patterns (RETIRED 2026-05-26) — quote / big-stat / multi-case-bundle

These were a separate TOML-driven engine (`assets/render.py`). **Retired** —
they were fully redundant with DeckJSON Path A layouts. The engine, its
templates, and its `examples/*-luckin/` TOML samples were removed; the
story-case schema-fit refusal + accent review were ported into
`render-deck.py` (see the ONE-PAGER section's "Safety nets").

Author what used to be a Layer-1 pattern as a normal deck.json layout:

| Old Layer-1 pattern | Now author as (deck.json) |
|---|---|
| `quote`             | `layout: "quote"` |
| `big-stat`          | `layout: "stats"`, `variant: "hero"` |
| `one-pager`         | `layout: "content"`, `variant: "story-case"` (see ONE-PAGER CASE POLICY above) |
| `multi-case-bundle` | a normal multi-slide deck: `cover` + `agenda` + one `content/story-case` per case + `end` |

Old `.toml` case files convert 1:1 to the shapes above. If you ever need to
render a legacy `.toml`, `render.py` is recoverable from git history.



## Production deck layout fixes (BF1-BF4 — v1.4, 2026-05-02)

These four bugs surfaced in the 数字员工指南 deck and now have permanent
defenses in `feishu-deck.css`. Each captures a specific user-visible failure;
the defense is automatic, but the AUTHORING rule still matters — knowing
why the defense exists keeps you from working around it.

### BF1 — short-numeral big-stat hugs the left edge

**Symptom**: Big-stat slide with a single-character `.num` value (e.g. `5`,
`3`) — the digit visually clings to the slide's left padding (96px from the
edge), looking orphaned. Multi-character values like `30万人` filled the
left grid cell and hid the issue.

**Defense (CSS)** — *v2, 2026-05-03, replaced v1's right-anchor approach*:
`.slide[data-layout="big-stat"] .num { justify-self: center; text-align:
center; }` — sits the numeral in the visual center of its left half-canvas
cell, so the digit reads as a balanced focal element regardless of value
length.

**v1 → v2 history**: v1 used `justify-self: end / text-align: right` to
anchor the number against the slide centerline next to the .copy block.
That hugged the number too close to the .copy text, creating a
visually-jammed-up feeling on the centerline. v2 centers in the cell
instead, with breathing room on both sides.

**Authoring rule**: prefer multi-character values that show the FULL
story — e.g. `30 → 5` instead of bare `5`. The transformation reads in
one glance AND the cell fills naturally. Single-character values are
allowed; the v2 centering keeps them looking deliberate. Don't
hand-tune position.

### BF2 — `.col-visual` double-frames a self-decorated child

**Symptom**: Putting a `.data-panel`, `.ui-window`, `.kpi-strip`,
`.scene-grid`, `.north-star-map`, `.calc`, or `.ui-kpi` directly inside
`.col-visual` produces a visible "browser-chrome" border WRAPPED AROUND the
inner panel — the `.col-visual` default frame (1px hairline + 16px radius +
faint top-down gradient) was meant for raw image / placeholder mocks only.

**Defense (CSS)**: `.col-visual:has(> .data-panel) { border: none;
background: none; padding: 0; border-radius: 0; }` — and the same for
each self-decorated component class. The wrapper frame disappears
automatically; the inner panel's own decoration takes over.

**Authoring rule**: prefer putting structured data containers
(`.data-panel`, etc.) directly inside `.col-visual` — the CSS will
silently strip the wrapper frame. Only keep `.col-visual`'s own frame
when the column carries a raw image, an inline SVG mock, a screenshot,
or a custom hand-built block that has no border of its own.

### BF3 — helpers compressed in stage middle, surrounded by empty space

**Symptom**: `.scene-grid` (especially 2×2 / 4-card layouts) or
`.north-star-map` placed inside a layout's `.stage` shows up as a small
block in the canvas vertical centre, with conspicuous empty space above
AND below. Default `align-self: center` + content-natural height collapse
the helper to ~70% of the available vertical room.

**Defense (CSS)** — *v2, 2026-05-02 PM, replaced v1's vertical-stretch approach*:
- All `.stage > .scene-grid` and `.stage > .north-star-map` get
  `align-self: stretch; width: 100%` so they span the stage horizontally.
- When the helper is the dominant body block (alone, or paired only with a
  trailing pullquote / lede — detected via
  `:only-child` and `:first-child:nth-last-child(-n+2)`), the CSS bumps
  per-card padding (scene-card 32×28, ns-card 28×22) AND grid gap
  (scene-grid 24px, north-star-map 18px). Cards stay content-sized; the
  visual mass spreads across the canvas via richer padding + gaps, not
  via stretching empty card interiors.

**v1 → v2 history**: the first version added `flex: 1; align-content:
stretch` on the grid to force cards to fill the stage vertically. That
overshot — ns-cards at --cols:5 stretched to ~750px tall while content
was only ~400px, leaving giant empty borders, and `.tags`
(`margin-top: auto`) ended up jammed against the bottom border, looking
like the border was "blocking" the text. Lesson: stretch FILLS space but
doesn't distribute content — bigger padding + bigger gaps achieve the
same "feels filled" without the empty-card-interior failure mode.

**Authoring rule**: when you want a 2×2 or 1×N helper to occupy the
canvas, just place it as the major body block of `.stage`. The defense
triggers automatically and bumps padding/gap. If you DON'T want the
extra padding (e.g. 3 short rows of dense cards where tight spacing is
the look), add a non-trivial sibling AFTER the helper (a `.kpi-strip`,
a `.cta-box`, etc.) so the :nth-last-child detector skips the bump.
The auto-bump only fires when there's no significant content following
the helper.

### BF4 — pullquote left-bar shifts text 32px right of grid

**Symptom**: A `.pullquote` placed below a body grid (`.grid`,
`.scene-grid`, `.north-star-map`) reads as "indented" — its text starts
32px to the right of the cards' left edge because the bar uses
`border-left: 4px` + `padding-left: 28px`. The visual misalignment
nags the reader even when they can't articulate why.

**Defense (CSS)**: `.stage > .pullquote { margin-left: -32px; }` pulls
the bar OUTSIDE the text column, so the text-left aligns with the grid's
left edge while the bar still reads as decoration to the left of the
content area.

**Authoring rule**: don't reach for inline `style="margin-left: ..."` to
fix pullquote alignment. The defense handles content-2col / content-3up /
agenda / process / stats / timeline / table stages uniformly. If a
pullquote sits OUTSIDE `.stage` (legacy decks pre-1.3.2 with no stage
wrapper), the rule doesn't fire — but you should be migrating those
decks to the stage pattern anyway.

### BF5 — macOS traffic-lights forbidden by default

**Symptom**: A `.ui-window` mock with `<span class="ui-traffic-lights">`
renders three colored dots (red / yellow / green) at the top-left of
the titlebar, mimicking a macOS app window. In a 飞书 enterprise pitch
the dots feel **too consumer / casual** — the slide stops reading as a
brand-aligned data panel and starts reading as "someone's screenshot."
Reported by users on multiple decks.

**Defense (CSS)**:
`.slide .ui-window:not([data-show-chrome]) .ui-traffic-lights { display:
none; }` — the dots disappear automatically. The `.ui-titlebar` without
dots still reads as a window-style header, which is sufficient chrome
when mocking a Lark Base spreadsheet, a chat panel, or a browser dashboard.

**Opt-in for genuine macOS-screenshot context**: add `data-show-chrome`
on the parent `.ui-window`. This is the documented escape hatch when
a slide genuinely needs the macOS aesthetic (e.g. an "app review" deck
that's literally about macOS apps). Default is HIDDEN.

**Authoring rule**: do NOT include `<span class="ui-traffic-lights">`
in new decks unless you've explicitly decided the slide needs the macOS
window aesthetic. Even if the recipe at the top of `templates/slide-recipes.html`
shows the dots, the brand expectation for 飞书 / 汇报 / 客户提案 contexts
is no traffic lights. The CSS will hide them anyway, but cleaner markup
makes it obvious this isn't a macOS screenshot.

### BF6 — `.ui-grid` clusters at one side of `.ui-window`

**Symptom**: A `.ui-grid` (Lark Base / spreadsheet mock) inside a
`.ui-window` inside `.col-visual` clusters at the LEFT edge of its
parent, leaving large empty space on the right. Reported as
"内容都在一头" (content all stuck on one side) on a sales-table slide
where columns were `style="grid-template-columns: 130px 90px 80px 70px"`
(370px total width) inside an 864px col-visual.

**Defense (CSS)**: `.slide .ui-grid { width: 100%; align-self: stretch; }`
— the grid container always fills its parent's available row width.
Authors using fixed-px columns will see the grid expand and the leftover
space distributed proportionally if their `grid-template-columns`
includes `fr` units.

**Authoring rule**: prefer `fr`-based proportions for `.ui-grid` — e.g.
`style="grid-template-columns: 1.5fr 1fr 1fr 0.8fr"` keeps the relative
column widths AND fills the parent uniformly. If you genuinely need a
narrow content-sized table (e.g. a left-aligned key-value box), override
inline with `style="width: max-content"` on the .ui-grid.

### BF7 — `content-2col` hero image: align top AND bottom (defended in framework CSS)

When `.col-visual` carries an inline `min-height` (e.g. a 16:9 reference
scene anchored to 600px) and `.col-text` holds a stack of 3-5 short
sections, the text column packs at the top with empty space below.

**The framework now auto-applies `justify-content: space-between`** on
`.col-text` whenever `.col-visual` has an inline `min-height` style
(see feishu-deck.css). First text child aligns with image top, last
aligns with image bottom. Just set the image's `min-height` inline —
no other CSS needed.

When NOT to use this — use the story-case v2 pattern instead (see
ONE-PAGER CASE POLICY image-sizing rules) when the layout is
`.story-case`, OR when the text column has dense paragraphs that
naturally exceed image height. For those cases, image shrinks to text,
not the reverse.

### BF8 — flex-stage shrinks chart, grid bars don't follow (defended in framework CSS)

When a chart with positioned X-axis line (`::after { bottom: <pad> }`)
sits in a flex-column `.stage` alongside other body blocks, flex shrinks
the chart but the inner Grid `.bars` stays content-sized → bars
overflow downward, dropping below the X-axis line.

**The framework already defends `.arr-chart` / `.store-chart` /
`.bar-chart` with `flex-shrink: 0`** (see feishu-deck.css). When you
invent a new chart class, follow the same pattern — either name it one
of those, or add `flex-shrink: 0` in your per-page `<style>`.

Mirror failure (bars too SHORT, floating ABOVE X-axis): see "Bar chart
· X-axis alignment & in-chart brand logos" earlier in this file. Same
symptom, opposite cause; both rules apply together.

### BF9 — grid-stretched cell + `margin-top: auto` child = dead-middle empty space

**Symptom**: A vertical-comparison layout puts ONE column inside a grid
row that's stretched to the row's height (default `align-items: stretch`).
An inner element uses `margin-top: auto` to anchor itself to the column
bottom (e.g. "业务后果" label pushed below the comparison). Result: the
column has its title at top, the auto-margined element at bottom, and a
**giant empty middle** — the column is 600 px tall but content is 200 px
top-aligned plus 80 px bottom-anchored.

This is the structural sibling of BF3 (north-star-map's "stretch
overshoot"): any grid-stretched container with one `margin-top: auto`
child gets the same failure pattern.

**Failure recipe (don't write this)**:

```css
/* Bug: column stretches to row height; auto-margin yanks pills to bottom
   even though there's no content between, leaving a huge gap. */
.vs-comparison {
  display: grid; grid-template-columns: 1fr 1fr 1fr;
  align-items: stretch;     /* ← column = row height */
}
.vs-comparison .col {
  display: flex; flex-direction: column;
}
.vs-comparison .col .consequence {
  margin-top: auto;          /* ← yanks to bottom; empty middle */
}
```

**Three valid fixes**:

1. **Replace `margin-top: auto` with `justify-content: space-between`
   on the parent column.** This explicitly distributes children with
   equal gaps; nothing "yanks" to the bottom, so the middle naturally
   reads as deliberate negative space, not as an empty gap.
   ```css
   .vs-comparison .col {
     display: flex; flex-direction: column;
     justify-content: space-between;
   }
   ```
   Best for 3-section columns (title / comparison body / outcome
   footer) — the visual rhythm is clean.

2. **Drop `align-items: stretch` on the grid; let columns size to
   content.** Use `align-items: start` (or default `normal`) so columns
   are content-tall. The `margin-top: auto` then becomes a no-op (no
   space to push into). Use this when columns are intentionally
   different heights and you don't want forced equalization.

3. **Add a visible spacer or divider between the title and the
   auto-margined element.** A `<hr class="vs-divider">` with margin
   `auto 0` or a flex spacer with explicit `flex: 1` and visible
   gradient turns the empty space into deliberate decoration.

**Rule of thumb**: `margin-top: auto` should be paired with content
that fills MOST of the column. If your column has 30% content and 70%
empty (visible to the eye), the design is wrong — pick fix 1 or 2.

This is now flagged in SKILL.md but NOT enforced by the validator —
detecting "visible empty middle" requires layout-aware metrics
(line counts × line-heights). The R-DOM / R20 / R-WHITE-TEXT rules
catch DOM and typography drift; this one is editorial.

### R57 — quote / 金句 pages: no trailing periods

**Symptom**: A `<blockquote>` ending with `。` (or `.`) reads as a
formal full-stop sentence in the headline frame — too declarative,
breaks the rhetorical "this hangs in the air" feel of a 金句 / 客户证言
page. Reported repeatedly across multiple decks.

**Authoring rule**: on `data-layout="quote"` slides:
- Drop the trailing `。` / `.` from the final span of the blockquote
  text (the `.tail` leaf in the mixed-content split).
- Mid-sentence `,` `、` `—` are fine — they structure the sentence;
  it's only the TRAILING terminator that should disappear.
- The `.attrib` line below the quote MAY keep a trailing period if it's
  a complete attribution sentence, but most look better without.
- This applies to inline `<span class="accent-text">` emphasis splits
  too — make sure the LAST span doesn't terminate with a period.

**Why no programmatic enforcement**: a deck may have a quote spanning
multiple sentences with internal `。` (legitimate). Detecting "trailing
period only" reliably requires a parsing pass we haven't bothered to
write. The authoring rule + manual check on every quote slide is enough.

---


## BF10–12 — Alignment defenses (2026-05-16)

Framework CSS now ships three alignment defaults that catch common
"why doesn't it line up" footguns. All three apply automatically; the
notes here are for context when authors hand-write similar layouts.

### BF10 — Mixed-size row uses `align-items: center`, not baseline

When a row has elements at very different font sizes (ratio > 1.5×,
e.g. a 48 px numeral followed by 24 px body), `align-items: baseline`
LOOKS misaligned — the baselines do align but the visual centers don't.
Center alignment puts the smaller element at the visual middle of the
bigger element's line-box.

Apply via `.mixed-row` utility class:
```html
<div class="mixed-row">
  <span class="num">01</span>
  <p class="text">不留意向沟通阶段的商机...</p>
</div>
```

Default: `display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 22px`.

### BF11 — Hero zone content centered, not flex-start

For big-stat (and similar 2-col-hero) layouts, the LEFT column's
content (hero number + caption + secondary stat) should be visually
centered within its half — not hugging the slide's left edge.

Framework default: `.slide[data-layout="big-stat"] .hero { align-items: center; text-align: center; }`. Don't override unless you intentionally
want left-flush (rare; for that, use `.slide[data-layout="content-2col"] .col-text` which is left-flush by design).

### BF12 — Multi-card column equal-height

When `.col-text` / `.col-visual` contain multiple stacked cards (2–3
typical), the cards should fill the column height equally — otherwise
left / right columns of a 2-col grid mis-align across the page.

Framework default: `.canonical-card / .news-card / .data-panel` get
`flex: 1` when they're direct children of `.col-text` / `.col-visual`.
Heights balance automatically; no per-deck override needed.

### BF13 — Present-mode first-frame fallback must gate on `[data-js-ready]` (2026-05-17)

**Symptom**: navigating between content pages in present mode, the cover
(slide 1) **flashes underneath** for a frame or two — most noticeable
on slower transitions or when screenshotting via headless Chromium.
The cover bleeds through as a faint background even on slide 13 / 22 /
whichever the user just navigated to.

**Root cause**: framework CSS provides a "pre-JS first-frame visible"
fallback so users don't see a black screen during the gap between
CSS-applied (all frames opacity:0) and JS-loaded (active frame gets
`.is-current`). The original rule was:

```css
/* WRONG — fallback stays alive forever */
.deck[data-mode="present"] .slide-frame:first-child {
  opacity: 1; pointer-events: auto;
}
```

The `:first-child` selector has equal specificity to `.is-current`, but
this rule was DECLARED LATER in the stylesheet, so it kept winning even
after JS marked another frame as `.is-current`. The first frame
remained `opacity: 1` underneath every subsequent slide.

**Defense (CSS + JS, mandatory pair)**:

```css
/* feishu-deck.css — gate the fallback so it deactivates after JS init */
.deck[data-mode="present"]:not([data-js-ready]) .slide-frame:first-child {
  opacity: 1; pointer-events: auto;
}
```

```js
/* feishu-deck.js — set [data-js-ready] AFTER initial goTo() */
if (!readHash()) goTo(deck, frames, 0, false);
deck.setAttribute('data-js-ready', '');
```

**How it works**:
- Before JS runs: deck has no `[data-js-ready]` → fallback active →
  first frame visible → no black screen during the ~50 ms init window.
- After JS runs: deck gains `[data-js-ready]` → fallback DEselects →
  only `.is-current` frame is opacity:1 → no bleed-through.

**Don't break this pair**:
- If you simplify CSS to "always show first frame", flash returns.
- If you simplify CSS to "never show first frame", initial black screen returns.
- If JS sets `[data-js-ready]` too early (before first `goTo`), brief black flash.
- If JS forgets to set `[data-js-ready]`, fallback never deactivates.

**Postmortem (2026-05-17)**: showcase eval surfaced the flash during
screenshot capture. Initial fix was a `page.add_style_tag` injection
inside `validate.py`'s screenshot loop — only fixed screenshots, not
the real browser experience. Root fix moved to framework: gate the
CSS fallback behind `:not([data-js-ready])`. Validator workaround
removed (commit after BF13 lands).

### BF14 — abs-positioned chrome override must reset the OTHER anchor (2026-05-23)

**Symptom**: a deck adds a local `<style>` override for a `position:
absolute` chrome element (hint pill, badge, chip, icon) and sets ONLY
ONE vertical anchor (`top: Xpx;` *or* `bottom: Ypx;`) without resetting
the other. A less-specific framework rule already declared the OTHER
anchor — both are now active. Browser computes height as
`parent.height - top - bottom`, regardless of content. The chrome
element silently stretches to ~80–95 % of the parent height.

**Postmortem (2026-05-23)**: AI-consumer-growth deck slide 6 (and 8,
30 — three iframe-embed slides). The deck's `<head> <style>` block
had an obsolete override (predating the framework's 2026-05-22
iframe-embed support):

```css
/* override (wrong — only declares top) */
.slide[data-layout="iframe-embed"] .iframe-wrap > .iframe-hint {
  position: absolute; top: 16px; right: 16px;
  display: inline-flex; padding: 8px 14px;
  /* no `bottom:` declared → inherited `bottom: 18px` still active */
}
```

Framework rule still applied for `bottom`:

```css
/* framework (extra-layouts.css) */
.slide[data-layout="iframe-embed"] .iframe-hint {
  position: absolute;
  bottom: 18px; right: 18px;
  display: inline-flex; padding: 10px 18px;
}
```

Result: hint pill rendered at **764 px tall** instead of ~32 px.
User-visible: "进入页面，报告可滚动查阅这个的高有问题，非常大".

**Two valid fixes**:

1. **Delete the obsolete override entirely** — if the framework
   already has the layout's rules covered (which is what we did
   here, since the override predated framework iframe-embed support).
2. **In the override, redeclare BOTH anchors** —
   `top: 16px; bottom: auto;` (or use `inset:` shorthand to set all
   four). This makes the override self-contained and immune to
   future framework rule changes.

```css
/* fixed pattern (if you must override) */
.slide[data-layout="iframe-embed"] .iframe-wrap > .iframe-hint {
  position: absolute;
  top: 16px;       bottom: auto;          /* MUST redeclare bottom */
  right: 16px;     left: auto;            /* and left, for symmetry */
  display: inline-flex; padding: 8px 14px;
}
```

**Defense (validator)**: `R-VIS-ABSPOS-DUAL-ANCHOR` in `validate.py`
visual audit catches this automatically. For every
`position: absolute` non-layout element in the deck, the audit:
1. measures rendered height (`h1`)
2. temporarily sets `style.bottom = 'auto'` and re-measures (`h2`)
3. restores the original `style.bottom`
4. flags if `h1 - h2 >= 30 px` AND `h1 >= 2 × h2` (height collapsed
   by ≥ 30 px AND ≥ 2× ratio when bottom was neutralized → CSS DID
   declare `bottom` AND it was driving the height)

Why mutation test: `getComputedStyle().bottom` returns the USED
value (always px) for any positioned element, NOT the declared
value. There is no static way to tell from JS whether `bottom`
was declared in CSS or computed by the layout engine. Mutating
inline `style.bottom = 'auto'` (max specificity) flips the resolver
into the "bottom unset" path and exposes whether CSS had it set.

**Excluded from the audit** (legitimate full-bleed by design):
- Class denylist: `.stage / .stack / .toc / .flow / .nodes / .grid /
  .table-wrap / .header / .footer / .col-text / .col-visual /
  .iframe-wrap / .desktop-frame / .phone-frame / .phone-screen /
  .arch-stack / .panel / .slide-frame / .deck / .two-hand-arch /
  .pipeline / .steps` — these are layout shells; vertical span is
  intentional.
- Element opt-out: `data-allow-dual-anchor` attribute — set this
  on a custom-class element that genuinely needs both top + bottom
  active (e.g. a true full-height side-rail or a fill-parent overlay
  drawing the entire canvas).

**Authoring rule**: when you write a `<style>` override for an
absolutely-positioned chrome element AND the same element is targeted
by framework CSS (any `.slide[data-layout=...] .chrome-class` rule),
either:
- Drop the override (let the framework take over), OR
- Redeclare all four anchors in the override (top + bottom + left +
  right, using explicit `auto` for the ones you don't want active),
  OR use `inset:` shorthand.

Half-redeclared overrides on positioned elements are the same class
of bug as R47 (variants that change `display` / `flex-direction`
without redeclaring `align-items` + `justify-content`). The fix
discipline is the same: **self-contained overrides, no partial
property declarations on positioning / layout properties**.

### BF15 — hiding framework `.header` requires content rebalance (2026-05-24)

**Symptom**: a slide hides `.header { display: none }` in per-page CSS to gain
vertical space, AND sets `.stage` with a custom `top` value in the "danger
zone" (typically `top: 40-60px`, neither close enough to slide edge to look
like a deliberate "snap to top" nor matching the framework anchor at
`top: 61px`). Result: an empty dark area at slide y=0..N appears as
「上面一条黑色 · 背景没有全」 — especially with diagonal-glow decor
(mix-glow's bright zones are at opposite corners, leaving the top edge
darker).

**Why this happens**: the framework's unified
`.slide[data-layout=...] .header` rule positions title at slide y=61 — a
deliberate visual anchor shared by every content slide. When you hide
`.header`, the slide loses that anchor; if your content doesn't replace
its visual function, the gap is perceived as missing background, not as
intentional whitespace.

**The rule**: when hiding framework `.header`, the slide MUST do ONE of:

| Choice | When to use | Effect |
|---|---|---|
| (a) Restore `.header` (drop `display:none`) | Default safe path — you usually can keep `.header` AND tighten the rest | Title sits at framework anchor y=61; visually consistent with sibling slides |
| (b) Snap `.stage { top: ≤32 }` | Hero / full-bleed feel — content extends near slide edge | Content sits at slide top edge; no perceived gap |
| (c) Align `.stage { top: 61px }` | Most common — sibling consistency | First child of stage sits at the same y as other slides' titles |
| (d) Add a visible top decoration as `.stage`'s first child (eyebrow / brand bar / decorative line) | Slide needs unique top treatment | Decoration occupies the would-be-gap |

**Anti-pattern**: `.header { display: none }` + `.stage { top: 40-60 }`
without a top decoration. Visual gap of 40-60 px reads as "missing bg".

**Validator enforcement**: `audit_empty_header_zone` (rule
**R-EMPTY-HEADER-ZONE**) fires `warn` when a per-page CSS block hides
`.header` AND sets `.stage top` to a value > 32 AND ≠ 61 — i.e. NOT
snapped-to-top AND NOT framework-anchored. The rule scans every `<style>`
block scoped to a `data-slide-key`.

**Postmortem (2026-05-24)**: slide `management-clone-flywheel` had
`.header { display: none }` + `.stage { top: 50px }` + `mix-glow` decor
(whose bright zones are at opposite corners, leaving the top edge dark).
User reported 「上面有一条黑色,背景没有全」. Took 3 round-trips:
50→16 "snap to top" overshot past framework anchor; 16→61 finally matched
sibling slides. After codifying as R-EMPTY-HEADER-ZONE, validator surfaces
the pattern up front so authors hit it once at lint time.

Validator finding 2026-05-24: 8 other slides in the kangshifu deck (and
~same in source) use the same pattern (mostly `top:50` + hidden header,
including `flow-grows-itself` which uses mix-glow same as 22). They may
have the same "black zone" perception that just hadn't been spotted yet.
Run validator → review → fix proactively before next demo.

### BF15.1 — diagonal-glow decor + letterbox = visible edge at slide top (2026-05-24)

**Symptom (follow-up to BF15)**: even after pulling `.stage` top to 61 to
match framework anchor, slide 22 in fullscreen on a non-16:9 monitor
**STILL** showed "上面有黑色的边" — a visible horizontal seam at the slide
top boundary.

**Why**: the decor `::before` pseudo-element (mix-glow / orange-spark / any
decor with a glow source near the top) is bounded by `.slide` dimensions.
The slide-frame's bg image (`lark-content-bg.jpg`) extends into the
letterbox area on non-16:9 viewports, but the decor tinting does NOT.
Result: a sharp luma jump where decor tinting begins at the slide top edge.

Pixel proof at 1920×1200 viewport, col 1700 (right side, mix-glow purple
zone):

```
y=58 (letterbox): RGB(47, 35, 74)  luma=43
y=60 (slide top): RGB(69, 50,106)  luma=62   ← 19 luma jump
```

The 19-luma jump is the visible edge.

**Fix pattern** (slide-specific, applied via per-page CSS using `:has()`):

```css
/* Move the decor from .slide ::before onto .slide-frame ::after so it
   covers the letterbox + slide uniformly. */
.slide-frame:has(> .slide[data-slide-key="K"])::after {
  content: '';
  position: absolute; inset: 0;
  background-image: /* same radial-gradient as the original decor */;
  pointer-events: none; z-index: 0;
}
/* Suppress the slide's own ::before — otherwise it stacks ON TOP of the
   frame::after inside the slide, doubling the tint and re-creating the
   edge at the slide boundary. */
.slide[data-slide-key="K"][data-decor~="mix-glow"]::before {
  background-image: none;
}
```

After applying: luma is uniform 40-44 across the y=60 boundary (no jump).
The decor reads as a single continuous gradient from viewport edge to
viewport edge.

**When this matters**: only on viewports where letterbox is visible
(non-16:9 monitor in fullscreen). On 16:9 monitor (slide fills viewport),
the slide top edge IS the viewport top edge → no letterbox → no edge.

**Affected decor list**: any decor whose `radial-gradient` has its bright
zone near the slide top edge (`y <= ~20%`):
- `mix-glow` (`at 92% 8%`) — explicitly seen on slide 22, 43
- `orange-spark` (`at 88% 18%`) — likely affected, untested

Not affected (glow at bottom or center): `violet-glow`, `teal-glow`,
`blue-glow`.

**Framework-level fix (deferred)**: the right long-term fix is to make
`data-decor` apply to `.slide-frame::after` directly (via the same `:has()`
selector pattern) rather than only `.slide::before`. That would make the
decor uniformly cover the viewport for every slide automatically. Out of
scope for this fix; tracked as a framework TODO. Until then, slides with
top-bright decors need the per-slide `:has()` override above.

---


## Slide media auto-restart + auto-sound on enter (framework behavior, 2026-05-24 · sound 2026-05-25)

**Problem**: present mode keeps EVERY `.slide-frame` in the DOM at once
(only `.is-current` toggles visibility). So a `<video autoplay loop>` on a
non-first slide **starts playing on page load while its slide is still
hidden**, and by the time the presenter navigates to it the clip is at
some arbitrary point mid-loop — never from the start. Same class of bug
hits CSS `@keyframes` animations (they run once on load and are finished
before you arrive). Reported on slide 11 of the kangshifu deck
(`<video ... autoplay muted loop>`); the same `<video autoplay>` pattern
exists in ≥ 5 decks and `@keyframes`/`animation:` in ≥ 10.

**Fix (in `feishu-deck.js`, automatic — no per-deck markup)**: a single
`MutationObserver` watches every frame's `class` attribute. It catches
EVERY navigation path (present-mode `goTo`, hash nav, prev/next buttons,
and the separate mobile-patch IIFE's direct `.is-current` toggles).

- **Enter** a frame → each `<video>` is reset to `currentTime = 0`, and
  if it carries the `autoplay` attribute it is `.play()`ed — **with sound
  unless it was authored `muted`** (`muted = false` only for un-muted
  videos). See the sound paragraph below.
- **Leave** a frame → its `<video>`s are `.pause()`d (stops hidden
  background looping AND any sound).
- On both transitions a `CustomEvent` is dispatched on the `.slide`:
  **`fs-slide-enter`** / **`fs-slide-leave`** (bubbling). CSS-keyframe
  decks that need to re-trigger an animation on revisit can listen for
  `fs-slide-enter` and toggle a class, OR — simpler, no JS — scope the
  animation to `.slide-frame.is-current .x { animation: … }` so re-adding
  `.is-current` re-applies (and thus restarts) the animation.

**Sound (2026-05-25 · conservative default)**: an autoplay video plays
**with sound** when its slide is entered **only if it was authored WITHOUT
a `muted` attribute**. The framework sets `muted = false` before `.play()`
for those. An authored `muted` attribute is **respected as "keep silent"**
(same as `data-keep-muted`) — so already-shipped decks written per the old
"`autoplay muted` to enable autoplay" guidance keep playing silently and
do NOT suddenly blare audio when they pick up the updated `feishu-deck.js`.

Browsers block unmuted autoplay until a user gesture — but in present mode
**slide navigation is itself a gesture**, so unmuting succeeds on every
navigated-to slide. The one pre-gesture case (deck opens directly on a
video slide, before the viewer clicks/keys anything) gracefully falls back
to muted; a one-shot `pointerdown`/`keydown`/`touchstart` listener
(`upgradeMediaSound`) then turns sound on at the first input **without
resetting the playhead** (so the enabling click doesn't restart the clip).
Leaving a slide pauses its videos, so no two slides' audio overlap.

**Opt out**:
- `data-no-restart` — don't reset/pause this video on slide enter/leave
  (keeps its position across visits — rare).
- `data-keep-muted` — keep this video **silent** even though it has no
  `muted` attribute. Mostly redundant now that authored `muted` is also
  honored, but useful as an explicit-intent marker on a clip you author
  without `muted` but still want silent.

**Authoring guidance**:
- Want a video that plays from the top WITH SOUND each time the slide is
  shown → give it `autoplay` **without `muted`** (add `loop` to repeat
  while on screen). The framework resets the playhead and unmutes it.
- Want a silent / decorative / ambient background loop → keep the `muted`
  attribute: `autoplay loop muted`. The framework leaves it alone.
- Want a CSS animation to replay on revisit → scope it to
  `.slide-frame.is-current` (preferred) or hook `fs-slide-enter`.

**Caveat — existing decks**: this fix lives in the skill's
`feishu-deck.js`. Decks that link to the skill copy get it on next load.
Decks that shipped their OWN `output/assets/feishu-deck.js` (copy-assets
snapshot) or are already published (e.g. `feishusolution/<deck>/assets/`)
keep their old copy until re-run through `copy-assets.py` / re-deployed.

---


## CJK 换行平衡 / 末行孤字防治 (2026-05-25)

**Problem**: CJK 文本换行后,末行只剩一两个字("市场传媒"→市场/传媒、
"渠道适配感知"→渠道适配感/知),或两行上长下短(第一行很长、第二行很短)。
投影上很碎、不像一个整体。用户明确不接受这种孤字/失衡。

**两层防护:预防(CSS) + 检测(validator),不是二选一。**

### 1 · 预防 — `text-wrap: balance`(框架已默认开一批)

`feishu-deck.css` 有一条 **skill-level baseline**(`/* text-wrap baseline */`),
给常见标题/卡名类(`.ctitle / .card-name / .role-name / .ns-card h4 /
.scene-card .sc-name / .feat-label / .bot-name / .arch-label / .dir-name`)
开了 `text-wrap: balance`。balance 让换行后各行字数尽量相等,把 5+1 重排成
3+3,孤字自然消失,**纯 CSS、零 JS、零成本**。

- 如果某页用的是 **deck 专有类**(渲染器/手写产生的 `.meta-value / .slogan /
  `.ctx / .ts-time` 之类),baseline 没覆盖到 → 在该 deck 的 `<style>` 里补一条
  `.deck .slide-frame .slide :is(.类A,.类B) { text-wrap: balance; }` 即可。
- **balance 的硬限制(必须知道)**:
  - 元素里有 `<br>` 强制换行 → **balance 整体失效**(Chromium 行为)。别在会
    换行的标签里用 `<br>` 拼副标题;要副标题就用 `display:block` 子元素。
  - 容器是**固定宽 / 被 flex 夹窄**且文本本身就超出可用宽 → balance 也救不了
    (它只能重排、不能变出空间)。

### 2 · 检测 — `R-VIS-ORPHAN`(`--visual`,WARN)

`visual-audit.js` + `validate.py` 新增 `R-VIS-ORPHAN`:present 模式下用 Range
量每个 CJK 叶子文本元素的行盒,命中两类:

- **orphan**:换 ≥2 行且末行 ≤ ~1.45 字宽(末行单字)。
- **imbalanced**:短标签/标题(CJK ≤ 14 字)换 2-3 行,且末行 < 最宽行的 38%。

**跳过**(避免误报):有 block 级子元素的(`.role` 这类故意拆行的副标)、SVG
`<text>`、mockup 容器内文字、`white-space: nowrap` 的。**只审 deck slide
本身——`<iframe>` 里的原型是独立文档,审计够不着**(原型要手改,见下)。
长正文 2 行末行天然短,不算缺陷,已被 CJK≤14 闸挡掉。

### 3 · 被 R-VIS-ORPHAN 点名后的修复阶梯

1. **该类没 balance** → 加 `text-wrap: balance`(报告里 `bal != 'balance'` 即此情形;
   若加了仍不生效,多半被更具体的选择器/另一条 `!important` 压住,提级覆盖)。
2. **已 balance 仍孤字 = 容器约束**(报告里 `bal == 'balance'`):
   - 首选**加宽容器**。例:`senior-tour-leader-day` 时间轴首列固定 `200px`,
     最长活动名 "下午拜访 · 收单回办公室" 18px 要 206px、内容区只有 178px →
     必溢出。把 `grid-template-columns: 200px 1fr 1fr` 改成 `236px 1fr 1fr`
     就全单行了。**别靠缩字号**:缩字号只是把溢出在各行间搬家(whack-a-mole,
     这行修好那行又冒),且常踩 R20/R-VIS-TIER 的 off-tier。
   - ≤4 字主标签放不下 → `white-space: nowrap` 逼单行 + 把尾词用 `display:block`
     拆成副标行(见原型例子)。
   - 实在无解再考虑改文案让上下两行字数接近(内容是甲方的,慎改)。

### 4 · 原型 `<iframe>` 里的标签(检测够不着,手动按同款规则)

原型是独立 HTML,R-VIS-ORPHAN 审不到,得手写时就避坑。典型:`sps-coord-pain`
原型的 `.hub-node`(固定 148px,内含 avatar + `.hub-label`)里 "市场传媒" 4 字
被 avatar 挤到换行。修法 = 同款阶梯:**缩小 avatar 腾宽 + 主标签 `white-space:
nowrap` 逼单行**(`.role`"企划"本就 `display:block` 落副标行),量出可用宽再定
字号(量 → 定 → 验,别拍脑袋)。

---

## R-VIS-BAND-COLLIDE — 绝对定位内容带压住正文(2026-05-31)

**症状(P05 vs-wecom 差异化对比页)**:把某页字号严格放大到 4 档后,底部那条
`<p class="takeaway">`(收口金句带,有文字有底色)开始**压住矩阵最后一行的正文**,
但所有校验全 PASS——用户肉眼看到重叠、问"这种检查不出来么"。

**根因(两个盲区叠加)**:
1. **运行时画布居中 `centerSlideInCanvas`(feishu-deck.js)在算"内容并集"时
   跳过所有 `position:absolute` 元素**(line ~188 `if cs.position==='absolute' return`)。
   takeaway 是 absolute → 不计入 → 居中算法把 `[标题底→1080]` 整带都当可用区,
   把矩阵在里面垂直居中,正好压进底部那条带子。字号一放大、矩阵变高,压得更狠。
   它还用**内联 `!important`** 写 top/bottom(line ~251),所以外部 CSS `!important`
   也压不过它。
2. **旧 `R-OVERLAP` 只查"同容器直接子兄弟"的 bbox 相交,且明确跳过 absolute 子元素**
   (visual-audit.js line ~780,注释"intentional overlays")。takeaway 是 `.slide`
   的 absolute 兄弟、跟矩阵不在同一容器 → 天生看不见。

**修复**:
- **正解(对症根因)**:把内容带放进 `.stage`(`flex-direction: column`)的**正常流**
  末尾 + `margin-top` 间隔——它一旦不是 absolute,就被 `_ccMeasure` 计入并集,
  矩阵+带子作为**一个整体**居中,永不重叠。SKILL.md 已固化此规则。
- **检测(闭掉"检查不出来")**:新增 `R-VIS-BAND-COLLIDE`(visual-audit.js
  `out.band_collide` + validate.py 消费,ERR)。判定:framed + 有文字(≥4 字)+
  非 chrome/media 的 `position:absolute` `.slide` 子元素(=内容带),与居中容器
  (`.stage/.grid/.flow/.nodes/.toc/.stack/.table-wrap`)内的**正文文字叶子** bbox
  相交 >2×4px → 报。cover/image-text/end/section 豁免(hero overlay 是设计)。
- **通用原则(写进 SKILL.md `.stage` 段)**:字号放大引发框↔框/框↔字重叠或间距
  过小时,**先参照同页其它间距把容器/框拉高(`.stage--tall`、抬 stage 上沿、
  `grid-template-rows: …1fr…`)、保持一致间距,再整体重新居中**;绝不缩字号、
  绝不让内容贴边或重叠。

**回归**:改动前重叠状态(backup)→ 现报 `slide 5 · p.takeaway 压住 vs-row-label-cons
(交叠 150×20px)`;修好后不报;`examples/sample-deck.html` / `showcase.html` 零误报。

**未做(待评估的 R-NN)**:让 `centerSlideInCanvas` 本身**为顶部/底部绝对带预留
占位**(从画布带里扣掉它们的高度再居中),从运行时根治、不依赖作者把带子放进流内。
运行时居中历史上反复翻车(见 BALANCE-CENTERING-GAP / R-11),改前须配
`check-distribution.py` 全量零回归验证。

---

## R-VIS-PANEL-TOP — 面板内单内容贴顶未居中(2026-06-01)

**症状(pg29 feishu-ai-scene-tools 实战)**:content-2col 类页里,右侧面板容器(本框架 `.col-visual`,或从外来 deck lift 进来的 `.product-pane`/`.copy-pane`/`.case-pane`)装着一个比栏矮的单内容块(产品图/单卡/mock),内容**贴在框顶、下方一大片空** —— 面板没把内容垂直居中。用户在另一对话手补 `display:flex;flex-direction:column;justify-content:center !important` 修好,要求固化进技能。

**根因**:框架对 `.stage`/`.grid` 这层有 L2 居中默认,但**面板容器这一层没有**。`.col-visual` 当时只有边框/背景/overflow,无内部对齐;`.col-text` 虽是 flex 列但缺 `justify-content`。单矮内容 → 贴顶。`.product-pane` 等是外来源 deck 自带类(本框架标准是 `.col-visual`),lift 进来后同样缺居中。

**修复(三层,2026-06-01)**:
- **框架默认(根治)**:`feishu-deck.css` 给 `.slide[data-layout="content-2col"] .col-visual` 加 scoped 默认 `display:flex;flex-direction:column;justify-content:center`,用 `:not(:has(> .card+.card))` / `:not(:has(> .data-panel+.data-panel))` 守住 **BF12 多卡等高填充** 不被破坏;BF7 hero 图(inline min-height 撑满列)无 slack 故无冲突;BF2 自装饰子单个居中无害。**零回归验证**:phase-1a-demo(含 content-2col `lark-base-tour`)改前后 index.html **逐字节零差异**(单内容已撑满列、justify 无 slack=不变),validate 行为不变(exit 与改前一致,exit=1 是既有 R-KEY 历史项、非本改引入)。
- **检测器(兜底)**:`visual-audit.js` 新增 `R-VIS-PANEL-TOP`(crowd 的反向孪生)——framed 非媒体面板,内容贴顶(顶距<24px)+ 底空比顶空多>60px + 内容高<容器高62% → 报面板内单内容贴顶。**must-fire/must-not-fire 实测**:贴顶 panelA 报、已居中 panelB 不报。warn 级(--strict 升 err),`data-allow-imbalance` 跳过。兜 lifted/raw 页里框架默认够不着的自定义 panel。
- **注册**:check-only.py FAMILIES(连带补上上一条漏注册的 R-VIS-BAND-COLLIDE)+ references/validator-rules.md 规则表。

**适用边界**:框架默认只管本框架的 `.col-visual`;lifted/raw 页的自定义 panel 仍需在该页 `custom_css` 补居中(检测器会提示),因为给外来类名(`.product-pane`)写框架默认是死代码。

