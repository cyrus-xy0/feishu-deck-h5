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
4. Look up assets locally first. If missing and cloud assets are needed, query the
   configured Feishu Base via `lark-base`; download or reference only assets needed
   for locked slides.
5. Render:

```bash
python3 skills/feishu-deck-h5/deck-json/render-deck.py \
  runs/<ts>/output/deck.json \
  runs/<ts>/output/
```

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
- Do not use emoji or hand-drawn approximations for official Feishu product icons.
  Use the official asset pool described in `assets-and-files.md`.

## References To Load As Needed

- `../../deck-json/deck-schema.json`
- `../../deck-json/README.md`
- `../../deck-json/DECK-CLI-README.md`
- `../../deck-json/validate-deck.py`
- `../../deck-json/examples/phase-1a-demo.json`
- `../../references/deck-generation-policy.md`
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
