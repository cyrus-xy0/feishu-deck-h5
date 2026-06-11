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
- scoped cloud asset records from the Feishu Base asset library
- framework assets under `skills/feishu-deck-h5/assets/`

Output:

- `runs/<...>/output/deck.json`
- `runs/<...>/output/index.html`
- copied/shared assets needed for local preview and handoff

Inline freshness rule: when this subskill is not running as a separate
multi-agent worker, reread the current upstream files before rendering. Do not
rely on cached chat summaries or earlier reads of `outline.json`,
`DESIGN-PLAN.md`, local assets, cloud asset records, or schema/reference files.

## Rendering Flow

1. Read `outline.json` and `DESIGN-PLAN.md`; do not silently change the design
   plan. If content/layout must change, update the plan first.
2. Use DeckJSON-first for all deck output. Fill `deck.json` using
   `deck-json/deck-schema.json`; raw slides and schema slides both live in this
   file. Use `deck-json/examples/phase-1a-demo.json` as the minimal structured
   example when starting from scratch.
3. Follow the design plan's raw-first stance: `layout: "raw"` is the default;
   schema layouts are only for approved pure standard shapes. Keep raw CSS in
   `slide.custom_css`; do not put per-slide CSS in `<head>`.
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
   `--final` (full audits + autosnapshot). Every render writes its complete
   output to `<output_dir>/last-render.log` and ends with an errors-only
   digest — on a BLOCK, read the log instead of re-running.

6. Confirm the render actually updated `index.html` by checking renderer output,
   mtime, or expected slide key/content.
   If schema validation fails before render, inspect with
   `deck-json/validate-deck.py` or the validator error path and fix `deck.json`.
7. Before handoff, run asset copy/finalize workflow from the delivery reference.
8. If rendering a one-pager case, use the `content` layout with
   `variant: "story-case"` and load the one-pager reference before hand-authoring
   alternatives.

## DeckJSON Rules

- `deck.json` remains the source of truth.
- Every slide needs a stable `key`.
- Chinese-only is default; set language metadata only when designer requested it.
- Use framework tokens and schema fields instead of hand-tuned CSS wherever
  possible.
- For raw slides, use the four semantic type variables:
  `var(--fs-title)`, `var(--fs-sub)`, `var(--fs-body)`, `var(--fs-foot)`.
- For raw slides, prefer `fs-` component classes and narrative patterns from the
  references before inventing ad-hoc CSS. If the raw page is only a plain card
  list, use `content/3up` or `content/blocks` instead.
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

After rendering, route to validator. Do not publish from renderer.
