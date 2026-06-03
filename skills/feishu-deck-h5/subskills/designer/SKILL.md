---
name: feishu-deck-h5-designer
description: |
  Subskill for the feishu-deck-h5 pipeline. Use after the controller routes a
  deck-generation request to design: turn user requirements plus local input/
  knowledge and Feishu Base knowledge into a scenario, design_plan, and
  outline.json. This subskill does not render HTML or validate final visuals.
---

# feishu-deck-h5-designer

## Responsibility

Input: user brief, parsed `input/runtime-library/source-dossier.json` if present,
local files under `runs/<...>/input/`, and scoped records from the Feishu Base
knowledge library.

Output:

- `runs/<...>/output/DESIGN-PLAN.md`
- `runs/<...>/output/outline.json`

Do not write `deck.json` or `index.html`; that belongs to renderer.

Inline freshness rule: when this subskill is not running as a separate
multi-agent worker, reread the current upstream files before designing. Do not
rely on cached chat summaries or earlier reads of `source-dossier.json`, local
`input/` files, Feishu Base query results, or user notes.

## Required Design Flow

1. Define `scenario`: pitch goal, audience, decision context, setting, language,
   risk level, and proof requirements.
2. Query local knowledge first: `input/`,
   `input/runtime-library/source-dossier.json`,
   `input/runtime-library/assets/`, and any user-provided notes.
3. Query the cloud Feishu Base only for relevant knowledge records. Use the
   controller's Base URL/token/table/view and the `lark-base` skill.
4. Produce a narrative arc and slide outline. Default to Chinese-only unless the
   user explicitly asks for bilingual or external English-facing pitch.
5. Apply the raw-first design stance: every slide defaults to `layout: "raw"`
   when it later becomes DeckJSON. In `outline.json`, express that as
   `layout_intent: "raw:<pattern-or-intent>"`. Fall back to schema only for pure
   standard shapes listed in `deck-generation-policy.md`. Give every raw slide
   Q0-Q4 plus a six-dimensional design spec before authoring.
6. For every slide, include a density budget: core block + supporting evidence <=
   layout capacity. If it will not fit, cut or split content instead of shrinking
   text below the ladder.
7. Never fabricate attributed facts: no specific company numbers, named quotes,
   source claims, or future-roadmap commitments unless provided by user/local/cloud
   source. General industry/product knowledge is allowed only when labeled as such.
8. If the brief is a one-pager customer case or a four-beat case story, read
   `one-pager-case.md` and default to a single `content/story-case` slide without
   a cover unless the user asks otherwise.
9. Write or update the run's `PROMPTS.md` alongside `DESIGN-PLAN.md` so the user's
   actual asks survive the design/render handoff.

## `outline.json` Contract

Write JSON with this shape:

```json
{
  "scenario": {
    "goal": "",
    "audience": "",
    "setting": "",
    "decision": "",
    "language": "zh-only",
    "source_summary": []
  },
  "design_plan": {
    "title": "",
    "narrative_arc": "",
    "visual_direction": "",
    "hero_pages": [],
    "risks": [],
    "open_questions": []
  },
  "slides": [
    {
      "key": "cover",
      "role": "cover",
      "layout_intent": "schema:cover",
      "is_hero": true,
      "single_focus": "",
      "content": {},
      "evidence": [],
      "assets_needed": [],
      "density_budget": "",
      "design_spec": {}
    }
  ]
}
```

Keys must be stable kebab-case semantic IDs, not positional names like
`slide-01`.

For `layout_intent`, use `raw:<pattern-or-intent>` by default. Use
`schema:<layout>` only when the slide is a pure standard shape and include the
reason in `density_budget` or `design_spec.notes`.

## References To Load As Needed

- `../../references/design-phase.md`
- `../../references/deck-generation-policy.md`
- `../../references/design-first.md`
- `../../references/content-density.md`
- `../../references/narrative-patterns.md`
- `../../references/richness-primitives.md`
- `../../references/one-pager-case.md`
- `../../references/run-artifacts.md`
- `../../references/assets-and-files.md`
- `../../deck-json/deck-schema.json`

If converting existing PDF/PPT/HTML/docs, also read
`../../references/converting-existing-material.md`.
