# deck-generation-policy — feishu-deck-h5 reference
> 从 legacy monolith 补回 · 何时读:Renderer 生成 `deck.json`/`index.html`,Editor 改现有 deck,或 Designer 需要判断 Path A/B/raw。

## DeckJSON Raw-First Policy

Default to **Path A: DeckJSON-first**. Within Path A, the current design stance is
**raw-first**: per page, default to `layout: "raw"` in `deck.json`; fall back to a
schema layout only when the page is a pure standard shape. The author writes
structured DeckJSON and `deck-json/render-deck.py` produces HTML, framework
chrome, present mode, page numbers, typography ladder, and validation hooks.

Raw-first is not Path B. `layout: "raw"` is a first-class DeckJSON layout and
still uses render/validate/delivery gates. Whole-page handwritten `index.html`
remains the rare escape hatch.

Why this is mandatory:

- **Stability**: most HTML/CSS drift is eliminated because authors describe what
  the slide is, not how each pixel is positioned.
- **Editability**: text and page edits use `deck-cli.py`, then rerender.
- **Versionability**: JSON diffs are readable; giant HTML diffs are not.
- **Liftability**: slides keep stable keys, assets, `custom_css`, and schema data.

Minimal flow:

```bash
# after router + design + preflight + run creation
python3 skills/feishu-deck-h5/deck-json/deck-cli.py \
  runs/<ts>/output/deck.json new-deck \
  --title "<title>" --author "<author>" --date "<YYYY.MM.DD>"

# import/set pages through the guarded CLI; do not open deck.json in an editor
python3 skills/feishu-deck-h5/deck-json/deck-cli.py \
  runs/<ts>/output/deck.json set-page <key> \
  --html <slide.html> --css <slide.css>

python3 skills/feishu-deck-h5/deck-json/render-deck.py \
  runs/<ts>/output/deck.json \
  runs/<ts>/output/

bash skills/feishu-deck-h5/assets/finalize.sh runs/<ts>/output/ local
```

Use `deck-json/examples/phase-1a-demo.json` as the smallest schema example and
`deck-json/deck-schema.json` as the contract.

## Authoring Paths

### Option A · Atomic CLI Ops

This is the only general write path for both initial population and scoped edits.
It carries the file lock, optimistic guard, backup, schema validation, and rollback:

```bash
python3 skills/feishu-deck-h5/deck-json/deck-cli.py runs/<ts>/output/deck.json set slides.3.data.title "新标题"
python3 skills/feishu-deck-h5/deck-json/deck-cli.py runs/<ts>/output/deck.json clone source-key new-key
python3 skills/feishu-deck-h5/deck-json/deck-cli.py runs/<ts>/output/deck.json reorder 5 2
python3 skills/feishu-deck-h5/deck-json/deck-cli.py runs/<ts>/output/deck.json set-variant kpi-4up hero
```

For deck-native lift:

```bash
python3 skills/feishu-deck-h5/deck-json/deck-cli.py DST/deck.json paste --from SRC/deck.json --key <key>
```

### Option B · Browser Edit Mode

Rendered decks load `assets/edit-mode/deck-edit-mode.css` and
`assets/edit-mode/deck-edit-mode.js`. Press `E` to edit text in the browser,
`Esc` to exit, and `Cmd/Ctrl+S` to save.

This edits `index.html`, so it creates post-render drift. To preserve the change,
port it back to `deck.json` manually or use `sync-index-to-deck.py` knowing that
the slide may become `layout: raw`.

## Layout Choice

Default each page to `layout: "raw"` unless it is a CEREMONIAL page. Per F-305
«raw unless ceremonial», schema is kept ONLY for the ceremonial set — cover,
agenda, section, quote, end — plus the mechanism layouts `raw`, `replica`,
`canvas`, `iframe-embed`. The body-content schema layouts (content / stats / flow
/ chart / table / arch-stack / image-text / logo-wall, all variants) are **FROZEN**:
they still render for legacy decks, but NEW pages must be `layout: "raw"` (the
model lays them out freely — richer & more distinct). `R-LAYOUT-DEPRECATED`
(warn_soft · advisory, never blocks) flags a new page that uses a frozen layout.

Pick by content substance, not aesthetics. A page stays **`raw` (the default)**
unless it is a ceremonial page (above). (Do not use vague tests like "has
alignment / hierarchy" to decide — every page has those.)

**Single source for the fall-back allowlist.** The canonical "when may a page fall
back to a schema layout" table lives in `references/design-first.md` →
*Decision rule — 白名单回退判定*. Use that one table; do not keep a second copy
here (the two drifting apart is what made the same page type land on raw in one
run and schema in the next). Post-F-305 that table lists ONLY the ceremonial five
(cover / agenda / section / quote / end) + `replica` (mechanism). **Anything not
matching a row in that table → `layout: "raw"`.**

Use schema-first only when the user explicitly asks for "schema-first", "安全模式",
"多用标准 layout", or `DESIGN-PLAN.md` declares `stance: schema-first`.

## Shell And DOM Contract

The canonical DOM order is:

```html
<div class="deck">
  <div class="slide-frame">
    <div class="slide" data-slide-key="..." data-layout="...">
      ...
    </div>
  </div>
</div>
```

`.slide-frame` must be a direct child of `.deck`, and each frame must contain
exactly one `.slide`. Runtime navigation and validator R-DOM depend on this.

For per-run decks at `<repo>/runs/<ts>/output/index.html`, framework asset paths
normally climb back to `../../../skills/feishu-deck-h5/assets/...`; delivery mode
may inline or copy assets.

## Writing And Numbering Rules

These are authoring rules, not only render rules:

1. **Cite numbers inline.** Put the source/citation near the number itself, using
   a trailing caption, a short line under the statement, or text in the sentence.
   Do not rely on retired footer chrome.
2. **Eyebrow numbering uses chapter/subpage form** such as `01`, `02`, `04-A`,
   `04-B`. When one focus expands across multiple pages, use subletters.
3. **ZH/EN separator** for bilingual text is ` · ` with spaces on both sides.
   Avoid slash, parentheses, and dash separators.
4. **Single teal emphasis per page.** If two phrases compete for accent emphasis,
   choose one or make both neutral.
5. **Do not force quote/end slides.** Deck length follows the narrative arc; use
   `end` only when there is a real close.

## Iconography

Use Lucide-style inline SVG for generic icons: 24px viewBox, `stroke:
currentColor`, `stroke-width: 2`, round linecap/join, no fill. Never use emoji or
Unicode glyphs as icons. Official Feishu product icons and client logos must come
from the asset pools in `assets-and-files.md`.

## Content Header Rule

Content-page headers default to **title-only**:

```html
<div class="header">
  <h2 class="title-zh">...</h2>
</div>
```

No eyebrow above the title, no inner wrapper, and no inline page number. Hero
layouts such as cover/image-text/end own their own title patterns and are the
exception. Validator R56 enforces the no-eyebrow rule, but authors should
construct it correctly.

### When you need a title subtitle — one canonical form only

A content/raw page may carry **one** subtitle line under the title. There is
exactly **one** way to write it: a `<p class="page-sub">` directly after the
`<h2>`, **inside `.header`**:

```html
<div class="header">
  <h2 class="title-zh">飞书与企微,已经不是同一类产品</h2>
  <p class="page-sub">下一代协同 vs 上一代 IM</p>
</div>
```

The framework (`.slide .header .page-sub`, see `feishu-deck.css`) gives it **one
uniform position**: title + 36px, `--fs-sub` (28px), #fff. Because every page
uses the same class, every subtitle lands at the same baseline and size.

**Do NOT improvise the subtitle.** Inside `.header`, forbidden alternatives:

- `.lede` — that class is for the **section** layout's master subtitle, and for a
  **body lead-in paragraph** (see below). It is not a header-subtitle class.
- `.subtitle` — cover-only.
- a bare `<div>` or an inline-styled `<p style="font-size:22px;…">`.

Each of these positions/sizes the subtitle differently per page, so a deck ends
up with subtitles at different tops and font-sizes ("副标位置都不一样").
Validator **R-VIS-SUBTITLE-CANON** (name-free, WARN) flags any text-bearing
element after the title inside `.header` whose class isn't `page-sub`.

**Body lead-in vs. title subtitle — keep them apart.** A *body* lead-in
paragraph (the `.lede` that introduces the content area) belongs **inside
`.stage`**, NOT in `.header`. R-VIS-SUBTITLE-CANON only scans `.header`, so a
`.lede` in `.stage` is correctly left alone — that is exactly where it goes:

```html
<div class="header"><h2 class="title-zh">…</h2></div>
<div class="stage">
  <p class="lede">A one-line lead-in that introduces the body below.</p>
  …
</div>
```

### This applies to `layout: "raw"` pages too — use the framework header, not a bespoke one

A raw content page MUST author its title with **this exact framework structure**
(`<div class="header"><h2 class="title-zh">…</h2></div>`), NOT a hand-invented
`.r-head` / `.r-title` / `.raw-stage` header. The framework already positions
`.slide[data-layout="raw"] .header` at the master baseline (top:61, see
`feishu-deck.css`), so you get correct placement for free and — critically — the
whole **header-guard family engages**. Those guards key off `.header` / `.title-zh`
and **silently skip any raw page that uses custom header classes**:

| Guard | What it enforces | Selector it needs |
|---|---|---|
| **R56** | no eyebrow in the header (the eyebrow above the title is suppressed) | `.header .eyebrow` |
| **R-VIS-SUBTITLE-CANON** | the **title subtitle** is the canonical `<p class="page-sub">` after the `<h2>` inside `.header` — not an improvised `.lede` / `.subtitle` / bare `<div>` / inline-styled `<p>` (name-free, so it also covers raw) | `.header` (scans elements after the title) |
| **R-VIS-TITLE-POSITION** | title sits at the master baseline (~top:61) | `:scope > .header > h2.title-zh` |
| **R-EMPTY-HEADER-ZONE** | header band isn't left visually empty | `:scope > .header` |
| **R-VIS-TITLE-GAP** | body doesn't crowd/overlap the title | `.header` + `.stage` |

Two name-free raw fallbacks now back-stop bespoke headers — between them they cover
both failure axes, so a custom-classed raw header no longer escapes unaudited:

| Raw fallback (name-free) | What it catches | Opt-out |
|---|---|---|
| **R-VIS-RAW-TITLE-POS** | the de-facto title (tallest ≥32px text block) pushed *down* off the master baseline | — |
| **R-VIS-RAW-TITLE-STACK** | a **two-layer title** — the de-facto title folds in a smaller eyebrow/kicker (own-text leaf ≤24px and ≤0.55× the title size); the R56 blind-spot on bespoke raw, since R56 keys on `.header .eyebrow` | `data-allow-title-stack` |

R-VIS-RAW-TITLE-POS alone used to miss the "飞书 不合规的双层标题" pattern (invent
`.r-head` + a kicker line — folding the kicker keeps the measured element-top at the
baseline, so the geometry check passed). **R-VIS-RAW-TITLE-STACK (2026-06-05) closed
that gap**: it detects the folded eyebrow/kicker by size ratio without needing any
framework class name, and warns. Fold the marker into the single title line (or use
the framework `.header > .title-zh`); only suppress with `data-allow-title-stack`
when the second line is genuinely a deliberate sub-track, not a smuggled eyebrow.

**Rules for raw content pages:**

- Title is a **single line**: `<h2 class="title-zh">…</h2>` inside `.header`.
  Section numbers (`变化 03 · …`) go **inline in that one line**, never as a second
  stacked line above it.
- Do not invent `.r-head` / `.r-title`. Reuse `.header` / `.title-zh` so the guards
  above actually run. Restyle emphasis spans as `.header .hl` / `.header .q`, etc.
- A validator firing (e.g. R-VIS-RAW-TITLE-POS) is a **design signal, not a red
  light to silence**: fix the structural cause (remove the extra layer / use the
  framework header), do not relocate the box or add an opt-out just to pass.

### Other schema-keyed checks that raw can bypass

Several card/column checks early-return unless the page uses framework class names.
If a raw page hand-rolls its own card/column classes, these **skip silently** —
reuse the framework names (or accept they won't audit your bespoke boxes):

| Check | Needs class | Effect on raw with custom names |
|---|---|---|
| R-VIS-CARD-OVERFLOW / R-VIS-CARD-MIN-HEIGHT-SPARSE | `.card` | card overflow / min-height not audited |
| R-VIS-LABEL-FLOOR (card-label floor) | `.card` / `.col` | in-card label size floor not enforced |
| R-VIS-PEER-SIZE / R-VIS-ALIGN (card pass) | `.card` / `.col` | peer-size & alignment checks skip |

Universal checks (font-tier R-VIS-TIER, body-floor, overflow/overlap geometry,
canvas-center, CSS-var, language R-LANG, focal, dead-rule, DOM order) are
name-free and **do** run on raw — those you cannot dodge by renaming.

## Text Color & Contrast

Base ink is pure `#fff` on the dark canvas. **Content text must stay bright** —
use `var(--fs-text)` (or `#fff`). Build hierarchy from **font-weight, font-size,
background tone, and accent color — never from text opacity.** Low-opacity white
reads as washed-out grey when projected.

- Body / list / description / summary / card copy → `var(--fs-text)`.
- Secondary lines → still `var(--fs-text)`, differentiated by weight/size, not by
  dimming.
- The dim tokens `--fs-text-72 / -65 / -40` are for **chrome only** (footnote,
  source, axis tick, eyebrow, page number, placeholder). `--fs-text-40` in
  particular is the dimmest chrome tier — never put sentence-like content on it.
- **Never write a literal `rgba(255,255,255,<1)` for text color.** Use the tokens.
  A raw soft-white literal trips **R-WHITE-TEXT**; if you genuinely need a soft
  chrome exception, add `data-allow-white-opacity` on the element.

Two validators enforce this, and they are complementary — do not rely on only one:

| Rule | Mechanism | Catches |
|---|---|---|
| **R-WHITE-TEXT** | scans **author CSS source** for literal `rgba(255,255,255,<1)` text | hand-written soft-white literals |
| **R-VIS-DIM-TEXT** | reads **computed DOM** color (token/inherit resolved); flags ≥8-char near-grey body text with effective brightness < 0.5 | soft-white delivered via `var(--fs-text-40)` etc. — the gap R-WHITE-TEXT can't see through. Brand-accent (blue/orange/violet) text is exempt (saturated, intentional). Opt out a deliberate dim note with `data-allow-dim-text`. |

The failure mode this prevents: a deck that pipes content through `--fs-text-40`
passes the CSS-source scan (it sees a token, not a literal) yet projects as
illegible grey. Author bright, dim only true chrome.

## Performance Budget

Keep decks lean. Validator `audit_perf` enforces P50-P55:

- **P50**: base64 in `<style>` <= 100KB by default; 250KB hard error.
  Single-file inline output must declare `<meta name="fs-deck-mode"
  content="inline">`.
- **P51**: `backdrop-filter: blur(N)` <= 10px.
- **P52**: at most one `ResizeObserver`, document-level with rAF batching.
- **P53**: many event listeners require `AbortController` and cleanup.
- **P54**: `.slide-frame { contain: layout paint size }`.
- **P55**: `.slide-frame .slide { will-change: transform }` plus GPU promotion.

Linked/default decks should have no base64 payload in CSS. Inline decks are an
explicit delivery mode, not the working default.

## `layout: raw`

Use `layout: raw` as the first-class default for bespoke/relational/narrative
pages. It is still inside the DeckJSON pipeline.

Rules:

- Put per-slide CSS in `slide.custom_css`, not in `<head>` or page-level style
  blocks. Renderer scopes/co-locates it to the slide so lift/clone/paste keeps it.
- Prefer framework variables and tokens. Raw slides should use
  `var(--fs-title)`, `var(--fs-sub)`, `var(--fs-body)`, and `var(--fs-foot)` instead
  of arbitrary font-size pixels.
- Prefer `fs-` component classes and narrative patterns before inventing ad-hoc
  classes. Raw must be a composition of framework primitives, not loose CSS.
- Do not use raw to dodge type-scale or readability rules. If content does not
  fit, cut/split content or redesign the page instead of shrinking below the
  ladder.
- Raw work requires the design gate: Q0-Q4 + six-dimensional spec.
- A plain N-card parallel list is ALSO raw now (F-305): author it with framework
  card tokens / patterns — do NOT fall back to a content schema. The old reverse
  nudge (`R-RAW-LOOKS-SCHEMA`, "raw card-list → content/blocks") was RETIRED on
  2026-06-12; its successor `R-LAYOUT-DEPRECATED` nudges the OPPOSITE way (frozen
  body schema → raw).

## Path B · Whole-Page Handwritten HTML

This is the escape hatch, not the normal path. Use it only when:

- the page/deck is a one-off design experiment that cannot fit any schema or raw
  slide cleanly;
- the user explicitly needs standalone HTML outside the DeckJSON pipeline;
- the pattern is being prototyped before possibly becoming a schema extension.

Anti-patterns:

- "I want this title 18px instead of 24" → content/layout issue, not Path B.
- "I'm not sure which layout matches" → read schema/examples and choose; do not
  hand-roll.
- "Need a richer hero" → use `layout: raw` first.

If a Path B pattern recurs in multiple decks, propose a schema/layout extension.

## Troubleshooting Render Failures

- Schema error: run or inspect `deck-json/validate-deck.py`, read the field path,
  and fix `deck.json`.
- Render completes but HTML looks stale: check renderer stdout, `index.html` mtime,
  and expected slide key/content.
- Assets missing after moving/sharing: run delivery/finalize; do not hand back
  linked HTML without portable assets.
- Raw/custom CSS does not travel on lift: migrate head-level per-slide CSS into
  `slide.custom_css` with `migrate-head-css-to-custom-css.py`.
