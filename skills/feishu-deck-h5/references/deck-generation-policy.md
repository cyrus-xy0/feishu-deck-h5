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
- **Editability**: text edits use `deck-cli.py set` or JSON edits, then rerender.
- **Versionability**: JSON diffs are readable; giant HTML diffs are not.
- **Liftability**: slides keep stable keys, assets, `custom_css`, and schema data.

Minimal flow:

```bash
# after router + design + preflight + run creation
$EDITOR runs/<ts>/output/deck.json

python3 skills/feishu-deck-h5/deck-json/render-deck.py \
  runs/<ts>/output/deck.json \
  runs/<ts>/output/

bash skills/feishu-deck-h5/assets/finalize.sh runs/<ts>/output/ local
```

Use `deck-json/examples/phase-1a-demo.json` as the smallest schema example and
`deck-json/deck-schema.json` as the contract.

## Authoring Paths

### Option A · Direct JSON Edit

Best for batch generation and structural rewrites. Edit `deck.json` directly,
render, then validate. Keep slide keys semantic and stable.

### Option B · Atomic CLI Ops

Best for scoped edits:

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

### Option C · Browser Edit Mode

Rendered decks load `assets/edit-mode/deck-edit-mode.css` and
`assets/edit-mode/deck-edit-mode.js`. Press `E` to edit text in the browser,
`Esc` to exit, and `Cmd/Ctrl+S` to save.

This edits `index.html`, so it creates post-render drift. To preserve the change,
port it back to `deck.json` manually or use `sync-index-to-deck.py` knowing that
the slide may become `layout: raw`.

## Layout Choice

Default each page to `layout: "raw"` unless it hits the pure standard-shape
allowlist below. The common schema set includes cover, agenda, section, content
variants, quote, stats, big-stat, image-text, table, timeline, process, end, plus
extra DeckJSON layouts such as `raw`, `replica`, and `iframe-embed`.

Pick by content substance, not aesthetics. If the page has alignment, hierarchy,
relationship, metaphor, spatial storytelling, animation substance, or narrative
composition, keep it raw. If it is just a standard shape, schema is faster, safer,
and more editable.

Pure standard-shape allowlist:

| Shape | Schema |
|---|---|
| Cover: title + owner + date | `cover` |
| Closing: slogan + contact info | `end` |
| Single quote + attribution | `quote` |
| Plain agenda with 3-8 items | `agenda` |
| Single row of 3-4 KPI numbers, no diagram | `stats/row` |
| Plain parallel cards: icon + title + body, no diagram/connector/animation | `content/3up` or `content/blocks` |
| Plain text comparison matrix | `table` |
| Faithful PDF/page image | `replica` |

Deterministic geometry schemas such as chart, table, logo-wall, flow, and
arch-stack may also be used when the page is mainly data/structure and does not
need bespoke story composition. Otherwise, raw is the default.

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

Content-page headers are title-only:

```html
<div class="header">
  <h2 class="title-zh">...</h2>
</div>
```

No eyebrow above, no subtitle below, no inner wrapper, and no inline page number.
Hero layouts such as cover/image-text/end own their own title patterns and are the
exception. Validator R56 enforces this, but authors should construct it correctly.

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
- If a raw page is just a plain N-card parallel list with no bespoke substance,
  fall back to `content/3up` / `content/blocks`; validator
  `R-RAW-LOOKS-SCHEMA` warns on this over-processing case.

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
