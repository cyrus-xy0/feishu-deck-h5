---
name: feishu-deck-h5
description: |
  总控 skill for Feishu / Lark-style HTML decks. Use when the user asks for
  飞书风格 PPT, Lark deck, 汇报材料, 客户提案, h5 deck, 16:9 网页演示, HTML deck
  generation/editing/validation/publishing, or material parsing for this deck
  pipeline. This controller does not do worker implementation itself: it routes
  workflow steps to subskills under subskills/. Default output is a dark,
  cinematic 1920x1080 HTML deck with validated local delivery and optional
  Feishu publishing / Base ingestion. Generation is DeckJSON/render-deck first:
  run design before render, default slides to raw-first unless they are pure
  standard schema shapes, and always validate before handoff. Do not use for
  producing a real `.pptx`; route that to an appropriate PowerPoint/keynote
  workflow if available.
---

# feishu-deck-h5

This is the **controller**. It owns workflow, scope control, and dispatch. It does
not author slides, render HTML, validate visuals, publish, or parse source
materials directly.

## Mandatory Router

Before doing anything, lock three things:

1. **Mode**: parse / design / render / validate / simulate / edit / publish /
   full pipeline / generation-from-source-html / edit-imported-html.
2. **Scope**: one slide, named slides, whole deck, or one run folder. Default to the
   smallest scope the user asked for.
3. **Target**: run directory, `outline.json`, `deck.json`, `index.html`, slide key,
   uploaded file set, or publish destination.

For a single-slide small edit, state the lock and proceed. If scope expands beyond
what the user named, stop and ask.

## Controller Hard Gates

These gates apply before dispatching to any subskill:

1. **Deck output must go through DeckJSON and `render-deck.py`.** Do not hand-write
   or patch a final `index.html` for generation. Full HTML fallback is rare; if
   accepted, state the fallback reason and still run validator before handoff.
2. **Generation must run design first.** Do not jump directly from brief/materials
   to `deck.json`. Designer output (`DESIGN-PLAN.md` + `outline.json`) is the
   contract the renderer follows.
3. **Default stance is raw-first inside Path A.** Renderer should make slides
   `layout: "raw"` by default, using framework tokens/components/patterns. Fall
   back to schema layouts only for pure standard shapes covered by
   `references/deck-generation-policy.md`.
4. **Validate before delivery or publish.** Any rendered or edited HTML must pass
   the validator path appropriate to the locked scope before local handoff,
   simulator use, or publisher confirmation.

## Scope Discipline

- If the user says "add one slide", "add a section", "add chapter N", or names a
  specific page, treat the request as that single requested artifact. For a
  chapter request, add the chapter divider first; ask only for the future chapter
  page count or title if needed.
- Do not respond to a one-slide request with a multi-page design menu or expanded
  deck roadmap. If a broader plan seems useful, mention it after completing the
  requested page-level action.
- For page references, `page N`, URL `#N`, and frame index N are canonical. Old
  `screen_label` numeric prefixes are labels, not source-of-truth page numbers.

## Multi-Agent Dispatch

Before reading or executing a subskill, verify whether the current harness
supports spawning subagents:

1. Check whether a subagent/spawn tool is already available in the active tool
   list.
2. If tool discovery is available, search for `spawn subagent multi-agent`.
3. Treat the environment as multi-agent capable only when a concrete spawn tool
   is callable. Do not assume support from prose, model name, or prior runs.
4. Announce the result once per task: either `multi-agent: available` or
   `multi-agent: unavailable, running inline`.

When multi-agent support is available, each routed subskill step defaults to a
fresh worker subagent. The controller remains responsible for the router lock,
scope boundaries, sequencing, conflict avoidance, final integration, and user
communication. The worker owns the actual subskill execution.

For every spawned worker:

- Pass the exact subskill path it must read, the locked mode/scope/target, the
  run directory, and the expected artifacts.
- Give it a disjoint responsibility. Do not let two workers write the same file
  or slide range concurrently.
- Tell it that other workers may be active and that it must not revert unrelated
  edits.
- Require a concise final report listing files changed, commands run, validation
  status, and blockers.
- If the step writes files, require the worker to re-read the latest on-disk
  file immediately before editing.

Use parallel workers only for independent steps, such as parsing separate source
bundles, reviewing different slide ranges, or running validation while the main
thread prepares a non-overlapping handoff. Keep dependent chains sequential:
Parser output gates Designer, Designer output gates Renderer, Renderer output
gates Validator. Simulator may run only after Validator/local delivery, and
Publisher only runs after explicit user confirmation.

Run a step inline instead of spawning when any of these are true:

- The environment lacks a callable spawn mechanism.
- The user asked to avoid delegation or wants a single-threaded run.
- The task is a known small edit with no useful parallelism, especially a
  single-slide or <=10-step mechanical change.
- The next action is immediately blocked on the result and delegating would only
  add coordination latency.

When a routed step runs inline, treat prior chat context as non-authoritative.
Before executing that subskill, reread the current on-disk upstream artifacts it
depends on, such as `source-dossier.json`, `outline.json`, `DESIGN-PLAN.md`,
`deck.json`, `index.html`, validator reports, or publish manifests. Do not rely
on cached summaries, earlier reads, or remembered file contents.

If a spawned worker fails, times out, or reports uncertainty, the controller must
either retry with a narrower prompt or take over inline. Never leave the user
with only a worker transcript; integrate the result into the controller's final
answer.

## Subskill Map

Read exactly the subskill needed for the next step:

| Need                                                                                                                                          | Subskill                       |
| --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| Turn user requirements + local/cloud knowledge into scenario, `design_plan`, and `outline.json`                                               | `subskills/designer/SKILL.md`  |
| Turn `outline.json` into `deck.json`, render `index.html`, package assets                                                                     | `subskills/renderer/SKILL.md`  |
| Check finished or in-progress deck for text, visual, structural, language, and delivery compliance                                            | `subskills/validator/SKILL.md` |
| Operate existing artifacts: edit existing decks, reskin foreign HTML, lift/swap slides, convert/import existing material, round-trip recovery | `subskills/editor/SKILL.md`    |
| Publish confirmed HTML to Feishu hosting and write publish metadata back to Base                                                              | `subskills/publisher/SKILL.md` |
| Parse uploaded materials into local `input/runtime-library/source-dossier.json` and normalize assets into `input/runtime-library/assets/`. A `.pptx` is converted (build_pptx) into a structured `canvas` deck.json — code reconstruction, no screenshots; hard pages → placeholder + reported | `subskills/parser/SKILL.md`    |
| Rehearse how a validated deck may land with target customer or stakeholder roles                                                              | `subskills/simulator/SKILL.md` |

## Canonical Workflow

For an uploaded HTML file, first classify its role:

- **Source HTML**: the user says to reference, imitate, learn from, remake, or use
  the HTML as material. Treat it as input only. Run Parser to create
  `source-dossier.json`, then Designer, Renderer, and Validator to produce a new
  `index.html`.
- **Target HTML**: the user says to edit, modify, adjust, optimize, fix, replace
  copy/style/layout, or continue from the uploaded HTML. Treat the HTML as the
  current deck state, not just a source material. First import/analyze it into
  the pipeline's existing-state artifacts, then route the change to Editor.

For target HTML, bootstrap the existing state before editing:

1. Copy the submitted file to `runs/<...>/input/source.html` and
   `runs/<...>/output/index.html`.
2. Analyze the current HTML into `input/runtime-library/source-dossier.json`.
3. Generate lightweight current-state `DESIGN-PLAN.md`, `outline.json`, and
   `deck.json` that describe what already exists. Mark these artifacts as
   `imported_existing_state` / `source_role: target-html`.
4. If the HTML is already a feishu-deck-h5 or recognizable slide deck, preserve
   slide order and `data-slide-key` values. If it is ordinary or complex HTML,
   wrap pages/sections as raw DeckJSON slides rather than redesigning them.
5. Run Editor against that imported state, rerender when `deck.json` changed, and
   run Validator before handoff.

For a new deck:

1. **Parser** if the user uploaded files or raw materials. Spawn a Parser worker
   when multi-agent dispatch is available. A `.pptx` import goes Parser →
   build_pptx → a structured, editable `canvas` deck.json (no screenshots);
   un-reconstructable pages (live chart / SmartArt / OLE) are placeholdered and
   reported for the user to redo — so this can hand straight to Renderer/Editor
   without a Designer pass when the deck is just being imported.
2. **Designer** to produce scenario, `design_plan`, and `outline.json`. Spawn a
   Designer worker when multi-agent dispatch is available.
3. **Renderer** to produce `deck.json`, render HTML, and prepare handoff files.
   Spawn a Renderer worker when multi-agent dispatch is available.
4. **Validator** before any HTML handoff. Whether the HTML came from Renderer or
   a later Editor pass, run Validator and fix non-zero findings before local
   delivery or publish confirmation. Spawn a Validator worker when multi-agent
   dispatch is available.
5. **Simulator** only if the user asks for pitch rehearsal, customer reaction
   simulation, stakeholder objections, or improvement advice after local HTML
   delivery. Spawn a Simulator worker when multi-agent dispatch is available.
6. **Publisher** only after the user confirms the HTML can be published. Spawn a
   Publisher worker when multi-agent dispatch is available.

For an existing deck:

1. Use **Validator** for check-only review. Spawn a Validator worker when
   multi-agent dispatch is available.
2. Use **Editor** for edits, reskin, lift/swap, import/conversion, or round-trip
   recovery. Spawn an Editor worker when multi-agent dispatch is available unless
   the task is a known small edit.
3. Use **Renderer** only when a changed `deck.json` or `outline.json` must be
   re-rendered. Spawn a Renderer worker when multi-agent dispatch is available.
4. Run **Validator** before any HTML handoff after Editor or Renderer changes,
   and fix non-zero findings before local delivery or publish confirmation.
5. Use **Simulator** only after the deck has passed Validator and the local HTML
   artifact has been delivered, when the user asks for rehearsal or improvement
   advice.
6. Use **Publisher** only after explicit publish confirmation. Spawn a Publisher
   worker when multi-agent dispatch is available.

## Shared Contracts

- `deck.json` is the single intermediate layer and source of truth; `index.html`
  is derived. A PPTX import becomes a structured `canvas` deck.json (no
  screenshots); a legacy HTML-only deck (no deck.json) is backfilled to deck.json
  from its real DOM before it is operated on. Editing is uniform across canvas /
  raw / schema slides: render → edit → sync back to `deck.json` → re-render.
- Work happens inside `runs/<timestamp>-<slug>/`. After preflight and before any
  new generation, create a run with `assets/new-run.sh <slug>` and announce the
  absolute run path. Use a short ASCII slug derived from the topic/customer; do
  not use a bare timestamp unless there is no usable topic.
- Inputs live in `runs/<...>/input/`; parser output lives in
  `input/runtime-library/`, with `source-dossier.json`, `assets/`,
  `source-library/raw/`, and `source-library/fetched/`.
- Designer writes `runs/<...>/output/outline.json` and `DESIGN-PLAN.md`.
- Renderer writes `runs/<...>/output/deck.json` and `index.html`.
- Validator reports must be scoped to the locked pages/run unless the user asked
  for whole-deck review.
- Simulator writes `runs/<...>/output/pitch-rehearsal.json` and
  `PITCH_REHEARSAL.md`; it does not publish, ingest, or automatically modify the
  deck.
- Publisher must not publish until the user has confirmed the exact HTML artifact.
- Every `.slide` must have a stable semantic `data-slide-key`. Schema rendering
  adds it automatically; hand-authored/lifted HTML must preserve or add it before
  delivery.
- Chinese-only is the default language unless the user explicitly asks for
  bilingual or external English-facing output.
- For each generation run, record the user's asks in `PROMPTS.md`; for production
  deck work, keep the making-of log under `runs/<deck>/log/` via
  `log-tool/deck-log.py` when practical.
- Do not hand back a single linked HTML file as final delivery. Run the delivery
  workflow so framework assets/shared assets are portable or the output is truly
  self-contained.
- `screen_label` numbers may drift after lift/insert/reorder. The canonical page
  identity is `page N = frame_index N = slides[N-1]`; use
  `deck-json/locate-slide.py` for source/target lookup and
  `render-deck.py --renumber` on target DeckJSON when labels need to match true
  frame order.

## Cloud Knowledge / Asset Base

Use this Feishu Base as the shared cloud knowledge and asset library when designer,
renderer, parser, or publisher need cloud context:

`https://bytedance.larkoffice.com/base/DBtybdvHYaovVwsWLatcipJBnrg?table=tblRIgS1rgDpUPW0&view=vewaY9hqu7`

When operating the Base, load the `lark-base` skill and use `lark-cli base +...`
commands with `--as user`. Extract:

- `base_token`: `DBtybdvHYaovVwsWLatcipJBnrg`
- `table_id`: `tblRIgS1rgDpUPW0`
- `view_id`: `vewaY9hqu7`

Do not pull entire Base contents into chat context. Query only the records needed
for the current scenario, asset lookup, or publish record.

## Preflight

Before any generation/render/edit that writes files, ensure the repository or skill
workspace is writable:

```bash
bash skills/feishu-deck-h5/assets/preflight.sh
```

If the script prints `PREFLIGHT BOOTSTRAPPED`, switch to the printed writable
workspace before continuing. If preflight fails because no persistent local folder
is mounted, stop and ask the user to mount/select a writable project folder.

## References

Workers should load only the reference files they need:

- `references/request-router.md`
- `references/deck-generation-policy.md`
- `references/design-phase.md`
- `references/design-first.md`
- `references/content-density.md`
- `references/assets-and-files.md`
- `references/layout-recipes.md`
- `references/narrative-patterns.md`
- `references/richness-primitives.md`
- `references/one-pager-case.md`
- `references/check-only.md`
- `references/validator-rules.md`
- `references/delivery.md`
- `references/editing-discipline.md`
- `references/round-trip-integrity.md`
- `references/reskin.md`
- `references/converting-existing-material.md`
- `references/prototype-embed.md`
- `references/slide-deletion.md`
- `references/operational-notes.md`
- `references/run-artifacts.md`
- `references/troubleshooting.md`
