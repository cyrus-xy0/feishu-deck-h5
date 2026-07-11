---
name: feishu-deck-h5-renderer
description: |
  Subskill for the feishu-deck-h5 pipeline. Use after designer output exists:
  consume outline.json, local input assets, cloud asset records, style rules, and
  DeckJSON schema to produce deck.json and render the HTML deck. This subskill
  does not decide pitch strategy and does not publish.
---

# feishu-deck-h5-renderer

## Responsibility

Input:

- `runs/<...>/output/outline.json`
- local assets under `runs/<...>/input/runtime-library/assets/`
- source files under `runs/<...>/input/`
- the explicitly selected, version-pinned
  `runs/<...>/input/runtime-library/template-pack/template-pack.json` when the
  outline declares Template Pack bindings
- scoped cloud asset records from the Feishu Base asset library
- framework assets under `skills/feishu-deck-h5/assets/`

Output:

- `runs/<...>/output/deck.json`
- `runs/<...>/output/index.html`
- copied/shared assets needed for local preview and handoff
- copied pack-relative Template Pack assets when a pack is selected

Inline freshness rule: when this subskill is not running as a separate
multi-agent worker, reread the current upstream files before rendering. Do not
rely on cached chat summaries or earlier reads of `outline.json`,
`DESIGN-PLAN.md`, local assets, cloud asset records, or schema/reference files.

## Rendering Flow

1. Read `outline.json` and `DESIGN-PLAN.md`; do not silently change the design
   plan. If content/layout must change, update the plan first. If slides declare
   `template_role`, also read the exact selected Template Pack version and
   `references/template-system.md`. Verify that every `template_layout_id`
   resolves from the pack's coverage; never infer a replacement layout.
2. Use DeckJSON-first for all deck output. Fill `deck.json` using
   `deck-json/deck-schema.json`; raw slides and schema slides both live in this
   file. Use `deck-json/examples/phase-1a-demo.json` as the minimal structured
   example when starting from scratch.
3. Follow the design plan's raw-first stance: `layout: "raw"` is the default;
   schema layouts are only for ceremonial / mechanism shapes explicitly approved
   by the design policy. Keep raw CSS in
   `slide.custom_css`; do not put per-slide CSS in `<head>`. For the fixed raw
   contract you should NOT re-derive each run (the untemplated legacy canvas is
   1920×1080, the
   {16,24,28,48} ladder + `/* allow:typescale */`, raw does not auto-create a
   `.header` so author the framework header yourself when a content title is
   needed, scope every rule to `.slide[data-slide-key="K"]`, the
   `is-current` + reduced-motion motion one-liner, SVG `<text>` floor → use HTML
   labels), read `references/raw-page-quickstart.md`. Author the focal/hero
   element bold the first time — do not escalate timid→bold across render cycles.
   A selected Template Pack does not create a new DeckJSON layout: it binds
   `cover/raw/section/quote/agenda/end` over existing layouts and maps legacy
   body layouts to `raw`. Its `canvas.design_width/design_height`, slot
   typography, safe areas, and fixed layers replace the corresponding default
   shell for bound slides; do not force that pack back to 16:9 or the framework
   type ladder.
   - **底色归 `.slide-frame`,不在 `.slide` 写整页背景(mandatory)。** 普通
     raw / content 单页的底色由框架 master 机制铺:`.slide-frame` 按 layout 分发
     `#000 var(--fs-asset-content-bg) center/cover`(= `lark-content-bg.jpg`,飞书
     母版暗调渐变;见 `assets/feishu-deck.css` L170–200),`.slide` 必须保持透明让
     它透上来。生成时 **不要** 在 `custom_css` 给 `.slide`(或整页根容器)写
     `background` —— 不写自定义渐变、不把 `var(--fs-asset-content-bg)` 焊到
     `.slide`、不默认铺 grid 纹理;任何一种都会盖掉 master 背景,视觉上就是
     「底色不对」。也 **不默认加灰底大面板**(半透明灰黑 panel 与暗底相乘 → 显脏
     显闷);分区用边框 / 细分隔 / 留白。唯一例外:raw 页有意模拟 cover / end /
     replica,才在该页按需覆盖背景并说明原因。
   - **Template Pack exception:** when a bound role supplies an approved fixed
     background/VI layer, that pack layer is the master. Do not inject the
     default Feishu background or wordmark over it, and do not move, recolor,
     resize, cover, or re-align locked elements.
4. Look up assets locally first. If missing and cloud assets are needed, query the
   configured Feishu Base via `lark-base`; download or reference only assets needed
   for locked slides.
5. Render:

```bash
python3 skills/feishu-deck-h5/deck-json/render-deck.py \
  runs/<ts>/output/deck.json \
  runs/<ts>/output/
```

   While iterating on individual pages, add `--iter` (auto-scopes audits to the
   changed pages via the `.slide-hashes.json` sidecar, skips the autosnapshot,
   prints a text echo of changed slides). Before any handoff, render once with
   `--final` (full audits + autosnapshot). At this boundary the Template Pack
   runtime must load the version pinned by the deck: final accepts only
   `status: "approved"`. A draft may bind only in an explicitly requested
   preview and never in final handoff. Every render writes its complete
   output to `<output_dir>/last-render.log` and ends with an errors-only
   digest — on a BLOCK, read the log instead of re-running.

   For fast iteration on one raw page, `deck-json/preview-slide.py <deck.json>
   --key <slide_key>` drops that single slide into the framework shell, screenshots
   it 1:1 at the resolved design canvas (1920×1080 only when no custom canvas is
   declared) AND runs the per-slide gate (audits.js: geometry / typescale /
   overflow / drop-shadow / soft-white / focal) — all in ~2s, no deck.json write, no
   autosnapshot. So you catch layout-rule violations in the SAME pass instead of a
   12s `render-deck` round-trip. ALWAYS pass `--key` (drift-proof: page numbers shift
   the moment a concurrent edit inserts a slide). The gate is single-slide + static,
   so it SUPPRESSES framework / present-mode / whole-deck rules (wordmark, present
   chrome, every-layout centering, CSS-var source scan, deck-wide drift) — those run
   only at the real render; preview shows NATIVE severity (no baseline demotion).
   `--no-gate` = screenshot only. Loop: iterate with preview `--key`, then commit +
   run the FULL gate once via `render-deck.py --scope <key> --final`. Caveat: JS
   motion / iframe-embed content / fitText do NOT run here — an iframe demo page
   (e.g. a feishu-prototype) still needs the real render.

6. Confirm the render actually updated `index.html` by checking renderer output,
   mtime, or expected slide key/content.
   If schema validation fails before render, inspect with
   `deck-json/validate-deck.py` or the validator error path and fix `deck.json`.
7. Before handoff, run asset copy/finalize workflow from the delivery reference.
8. Use `content` + `variant: "story-case"` only when the user or
   `outline.json` explicitly calls for a one-pager / four-beat case. Load the
   one-pager reference before authoring that shape; generic customer cases stay
   on the normal raw-first/schema-fit path.

## DeckJSON Rules

- `deck.json` remains the source of truth.
- Every slide needs a stable `key`.
- When a Template Pack is selected, pin its exact template ID/version and local
  pack snapshot. Selecting or approving a pack never changes the framework
  default for other decks.
- Resolve template coverage before authoring output. The only roles are
  `cover/raw/section/quote/agenda/end`, with statuses
  `native/derived/alias/unsupported`. Missing/unsupported is a hard error for a
  required strict role. Report it and stop; never mix in the default Feishu
  shell for only that page. Aliases and derivations must already be approved.
- Consume Template Pack layouts through `deck-json/template-pack.py` so alias
  cycles, state, asset containment, and per-slide bindings share one runtime
  contract. Pack assets must remain local and pack-relative; reject traversal,
  absolute, remote/data URI, or symlink-escape paths.
- Preserve template slots and fixed layers exactly. Do not automatically change
  font family, font size, weight, color, line height, alignment, geometry,
  z-order, Logo alignment, or fixed VI. Resolve overflow by shortening copy,
  selecting another approved layout, splitting the slide, then asking for
  confirmation—not by shrinking text.
- Chinese-only is default; set language metadata only when designer requested it.
- Use framework tokens and schema fields instead of hand-tuned CSS wherever
  possible.
- For raw slides, use the four semantic type variables:
  `var(--fs-title)`, `var(--fs-sub)`, `var(--fs-body)`, `var(--fs-foot)`.
- For raw slides, prefer `fs-` component classes and narrative patterns from the
  references before inventing ad-hoc CSS. If the page is a plain card list,
  still author it as `layout: "raw"` using framework card/list tokens; do not
  fall back to frozen body schemas such as `content/3up` or `content/blocks` for
  new pages.
- For a raw **content page title**, use the framework header verbatim —
  `<div class="header"><h2 class="title-zh">…</h2></div>`, title-only, single line
  (section number inline). Do NOT invent `.r-head` / `.r-title`: the header guards
  (R56 no-eyebrow, R-VIS-TITLE-POSITION, R-EMPTY-HEADER-ZONE, R-VIS-TITLE-GAP) only
  fire on `.header`/`.title-zh` and silently skip a custom raw header. See
  `references/deck-generation-policy.md` → "Content Header Rule" for the full gap
  list of schema-only checks raw can bypass.
- **Title subtitle = `.page-sub` (one canonical form).** If a content/raw page
  needs a subtitle line under the title, write it as `<p class="page-sub">`
  directly after the `<h2>` **inside `.header`** — the framework gives it one
  uniform position (title +36px, `--fs-sub` 28px, #fff). Do NOT improvise it with
  `.lede` / `.subtitle` / a bare `<div>` / inline `style="font-size:…"` (each
  drifts position + size per page → "副标位置都不一样"). A *body* lead-in
  paragraph is a different thing: that `.lede` goes inside `.stage`, not `.header`.
  Enforced by R-VIS-SUBTITLE-CANON (name-free, scans `.header` only).
- Do not use emoji or hand-drawn approximations for official Feishu product icons.
  Use the official asset pool described in `assets-and-files.md`.
- **Budget heights before you place absolutely-positioned raw panels — and PIN
  `line-height`.** On the default 1920×1080 canvas the framework header eats
  ~61→~200px, so
  body content lives in ~220–1010px. When you give a `.qc-panel`-style box a fixed
  `height`, the content inside it must fit *that* box. The #1 way the math goes
  wrong: **CJK `line-height: normal` ≈ 2.0×** — a 24px pill / tag / kicker renders
  ~58px tall, not ~34px, so a 4-row card silently doubles past its box. ALWAYS set
  an explicit `line-height` on every text element (≈1.1 for single-line
  chips/pills/labels, ≈1.2 for body), or your height estimate is off by ~2×. And a
  box with `justify-content:center` / `flex-end` does NOT hide overflow — content
  taller than the box spills out **both** the top and bottom borders (the title row
  pokes *above* the panel). Keep content ≤ box inner height. The render gate's
  `R-VIS-CARD-OVERFLOW` (F-317) now catches both-edge spills, but compute up front
  so you land it in one pass instead of iterating against the gate.

## References To Load As Needed

- `../../deck-json/deck-schema.json`
- `../../deck-json/README.md`
- `../../deck-json/DECK-CLI-README.md`
- `../../deck-json/validate-deck.py`
- `../../deck-json/examples/phase-1a-demo.json`
- `../../references/deck-generation-policy.md`
- `../../references/design-first.md`
- `../../references/assets-and-files.md`
- `../../references/layout-recipes.md`
- `../../references/extra-layouts-and-raw.md`
- `../../references/one-pager-case.md`
- `../../references/prototype-embed.md`
- `../../references/delivery.md`
- `../../references/round-trip-integrity.md`
- `../../references/operational-notes.md`
- `../../references/troubleshooting.md`
- `../../references/template-system.md`

After rendering, route to validator. Do not publish from renderer.
