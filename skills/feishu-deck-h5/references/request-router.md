# request-router — feishu-deck-h5 reference
> 从 legacy monolith 补回 · 何时读:任何任务开始前锁定模式/范围/目标,尤其是单页编辑、lift/swap、reskin、检查模式。

## REQUEST ROUTER — mandatory

Before touching files or running tools, lock:

1. **Mode**: pick exactly one from the **Authoritative Mode Enum** below.
2. **Scope**: single slide, named slides, whole deck, or one run folder. Default
   to the smallest scope the user named. More work requires user authorization.
3. **Target**: run dir, `deck.json`, `index.html`, slide key, slide number, source
   file set, or publish destination.

### Authoritative Mode Enum (single source of truth)

This table is the ONE canonical Mode vocabulary for the whole skill. The root
`SKILL.md` Mandatory Router and every subskill reference this list — do not keep a
second, differently-spelled mode list anywhere. Names are UPPERCASE_SNAKE (with
`CHECK-ONLY` / `LIFT+SWAP` kept as the established spellings). Every mode maps to
the subskill that owns its work.

| Mode | When it applies | Routes to (subskill) |
| --- | --- | --- |
| `CHECK-ONLY` | Check / review / validate an existing `.html` or deck; no content generation or edit requested. | Validator (`subskills/validator/SKILL.md`) |
| `GENERATION` | A NEW deck, OR converting external PDF / PPT / doc material into a deck, OR any change that produces a fresh run artifact. Design-first. | Designer + Renderer (`subskills/designer/SKILL.md` → `subskills/renderer/SKILL.md`) |
| `GENERATION_FROM_SOURCE_HTML` | An uploaded HTML is reference / inspiration / "照着这个重新做" — source material, not the artifact to preserve. | Parser → Designer + Renderer (`subskills/parser/SKILL.md` → designer → renderer) |
| `EDIT_IMPORTED_HTML` | An uploaded HTML IS the target state; user wants to modify / continue / fix it in place. | Editor (`subskills/editor/SKILL.md`) |
| `EDIT` | Edit copy / layout of an existing deck inside its own run (deck.json / index.html already exist). | Editor (`subskills/editor/SKILL.md`) |
| `RESKIN` | Foreign / non-Feishu HTML → "换皮" / 套飞书模板 / Feishu 化, same visual design preserved. | Editor (`subskills/editor/SKILL.md`) |
| `LIFT+SWAP` | Reuse another deck's pages / layout while swapping copy, client, or wording. | Editor (`subskills/editor/SKILL.md`) |
| `TRANSLATE` | Translate / localize an existing deck (or page range) into another language. | Translator (`subskills/translator/SKILL.md`) |
| `PARSE` | Parse uploaded source materials into `source-dossier.json` + normalized assets. (A `.pptx` is reconstructed into an editable `canvas` deck.json.) | Parser (`subskills/parser/SKILL.md`) |
| `IMPORT` | Quality-gate then ingest a confirmed finished HTML into `FuQiang/feishu-slide-library` (入库 / 提交 / 上传 / submit / archive). | Importer (`subskills/importer/SKILL.md`) |
| `SIMULATE` | Rehearse how a validated deck lands with a target customer / stakeholder. | Simulator (`subskills/simulator/SKILL.md`) |
| `PUBLISH` | Publish a confirmed HTML to Magic Page / 妙笔 / MagicBook / html-box hosting. | Publisher (`subskills/publisher/SKILL.md`) |

`EDIT`, `RESKIN`, `LIFT+SWAP`, and `EDIT_IMPORTED_HTML` are the **EDIT family** (all
route to Editor). `GENERATION` and `GENERATION_FROM_SOURCE_HTML` are the
**GENERATION family** (both run the design gate before render). The decidable line
between EDIT-family and GENERATION-family is in **Edit vs Generation boundary**
below.

The per-mode trigger + action detail for the historically documented modes
(`CHECK-ONLY`, `GENERATION_FROM_SOURCE_HTML`, `EDIT_IMPORTED_HTML`, `RESKIN`,
`LIFT+SWAP`, `GENERATION`) is in **Mode Selection Semantics** further down. A full
pipeline (Parser → Designer → Renderer → Validator → …) is just `GENERATION` (or
`GENERATION_FROM_SOURCE_HTML`) run end to end — it is not a separate mode.

For slide-specific requests, resolve both ordinal and stable key. URL `#N` means
slide index `N`; title/key references should be resolved through `slide-index.json`
or `deck.json` `slides[].key`. Prefer semantic `data-slide-key` over positional
names.

Canonical page numbering:

- `page N = frame_index N = slides[N-1]`. A user link `#N` and a spoken "第 N 页"
  mean the same frame index. Do not reinterpret old `screen_label` prefixes such
  as `50 飞书生态` as page numbers; those labels can drift after lift/insert/reorder.
- Resolve pages with:

```bash
python3 skills/feishu-deck-h5/deck-json/locate-slide.py <deck-dir|slide-index.json|deck.json|index.html> <query>
```

`query` may be `46`, `#46`, an `index.html#46` URL, a range `46-48`, a list
`46,2`, a slide key, or a title/label substring. Prefer `slide-index.json`, then
`deck.json`, then `index.html`; for legacy/foreign source decks, parsing
`index.html` DOM order gives the true `#N`.

Run `render-deck.py --renumber` only on the target DeckJSON deck after lift,
insert, or reorder when `screen_label` prefixes need to match frame order. It is
not needed for old source decks that have no `deck.json`.

## Confirmation Policy

- **Single-slide small edits**: state the lock once, then do it. Example:
  "理解 = 只改第 7 页 · key=case-meiyijia 的标题". No extra confirmation needed.
- **Scope >1 slide** or **any discovered need to touch unlisted slides**: stop,
  list the affected slides, and ask before proceeding.
- User says "直接出 / 别问": this skips the confirmation moment, not the router,
  scope lock, design thinking, or safety gates.
- **"加一页 / 加个章节" means make that one page first.** A chapter request means
  add the chapter divider page the user named, then continue page by page. Do not
  offer a multi-page design menu that nudges scope wider. If scale matters, ask a
  plain question such as "这章你计划一共几页?" Only propose splitting when the
  current page truly cannot fit.

## Scope Bounds All Work

The locked scope constrains the whole job, not only file edits. Render, screenshot,
validate, compare, audit, delivery packaging, and reporting must stay inside the
requested slide(s)/run unless the user expands scope.

- Do not run whole-deck visual audits for a single-slide text edit.
- Do not screenshot or compare pages outside the requested scope to "prove" they
  are fine.
- Existing published/self-generated pages are trusted stock unless the user asks
  to audit them. For lift/swap from trusted pages, one render plus one scoped visual
  spot-check is enough.
- Do not invent extra deliverables such as inline HTML or zip packages unless the
  user requested that delivery shape.
- When the user DOES ask to **打包 / package / bundle / 交付 / 发我** an existing
  run, that is a delivery hand-back action, not a new Mode — do not broad-`find`
  the run or hand-roll a portability check. Resolve the run by slug and run one
  command: `bash assets/finalize.sh <slug> remote` (default editable zip; see the
  「打包 / package — fast path」 table in `references/delivery.md` for shapes A/B/D).

This rule intentionally overrides exhaustive-verification instincts when the user
asked for a small, bounded operation.

## Scope Gate vs Design Gate

Scope confirmation and design confirmation are independent:

- **Scope gate** decides how many pages may be touched. A single page can proceed
  without asking "may I edit this one page?"
- **Design gate** decides whether the proposed design is beyond the default schema.
  Any hero page, bespoke/raw page, or heavy content augmentation still needs Q0-Q4
  plus the six-dimensional design spec before authoring, even if it is only one
  slide.

The two gates are **orthogonal** — either, both, or neither may fire. Decide each
column independently; do not collapse "many pages" into "needs design" or "creative
page" into "needs scope confirmation":

| Near-identical prompt | scope trigger? (>1 page) | design trigger? (beyond default) | What to do |
| --- | --- | --- | --- |
| "第 7 页标题 28 改 32" | no (single page) | no (pure size tweak) | both quiet → just do it |
| "第 7 页改成双手架构 hero" | no (single page) | yes (bespoke/raw hero) | design gate only → run Q0-Q4 + spec first, then author the one page |
| "全 deck 把『美宜佳』替换成『天福』" | yes (whole deck) | no (pure copy swap) | scope gate only → confirm the range, then `deck-json/apply-text-pairs.py` (fast-text); no design confirmation |
| "把全 deck 每页都改成双手架构 hero" | yes (many pages) | yes (bespoke on each) | both fire → confirm scope AND run design gate |

So scope size and design depth are read on separate axes: a large pure-copy swap
needs scope confirmation but never trips the design gate, and a single bespoke hero
trips the design gate without needing a scope question.

## Edit vs Generation boundary (decidable)

EDIT-family and GENERATION-family used to give opposite answers for "substantive
deck edits". The single decidable line is the **artifact target**, not how large
or creative the change feels:

- **Editing a deck that already exists inside its own run** — `deck.json` /
  `index.html` are already on disk under `runs/<...>/output/` — is the **EDIT
  family** (`EDIT` / `EDIT_IMPORTED_HTML` / `RESKIN` / `LIFT+SWAP`). Route to
  Editor. **Do not open a new run** for editing an existing run's deck (see
  `references/operational-notes.md`). A beyond-default *design* on one of those
  pages still passes the design gate (Scope Gate vs Design Gate above), but it is
  still an edit of the existing artifact, not a new GENERATION run.
- **Producing a fresh run artifact** — a brand-new deck, or converting external
  PDF / PPT / doc material into a new deck — is the **GENERATION family**
  (`GENERATION` / `GENERATION_FROM_SOURCE_HTML`). It runs `new-run.sh` and the
  design-first pipeline.

So: "改既有 run 目录里的 deck = EDIT 系(Editor,不开新 run);产出一份新 run 工件
= GENERATION(走 design)". There is no third "substantive edit → GENERATION"
path; substantive edits to an existing deck stay in the EDIT family.

Minimal pairs — each row differs from its neighbor by one phrase that flips the
**artifact target**, not by how big or creative the change is:

| Near-identical prompt | Family / mode | Because (artifact target) |
| --- | --- | --- |
| "把既有 run 的第 7 页整页重做成 hero" | EDIT family (`EDIT`) | edits an artifact already on disk in its run; bespoke design passes the design gate but **no new run is opened** |
| 同样要求,但还没有 run / deck.json,从 PDF 起做一份新 deck | GENERATION family (`GENERATION`) | produces a fresh run artifact from external material → `new-run.sh` + design-first |
| "换文字 lift 别人的页进我的 run" | EDIT family (`LIFT+SWAP`) | pastes into an existing run's deck and swaps copy; the target is the existing artifact, not a new run |
| "照着这个 HTML 重新做一份" | GENERATION family (`GENERATION_FROM_SOURCE_HTML`) | the HTML is source/inspiration; output is a brand-new run artifact the Renderer owns |

The flips above are all driven by whether a new run artifact is produced —
"整页重做" / "hero" / "重新做" by themselves do **not** push an in-run edit into
GENERATION.

## Import vs re-create: when conversions pass the Designer

A conversion of existing material (PDF / PPT / `.pptx` / foreign HTML) splits on
intent, and this is the single口径 the root `SKILL.md` and this router share:

- **Pure import (1:1 restore)** — faithfully reproduce the source deck's pages,
  no redesign. **免 Designer**: the parser output (e.g. a `.pptx` reconstructed
  into an editable `canvas` deck.json) hands straight to Renderer / Editor. This
  is `PARSE` feeding an `EDIT`-style finish, not `GENERATION`.
- **Import-then-create / rewrite / restructure** — reuse the material as input but
  produce a re-authored deck. **Must pass the design gate** (`GENERATION` /
  `GENERATION_FROM_SOURCE_HTML`): Designer runs first.

In short: **纯导入(1:1 还原)免 Designer;导入后再创作 / 重写必须过 design gate.**
Replica-vs-Rewrite detail lives in `references/converting-existing-material.md`.

## Mode Selection Semantics

### CHECK-ONLY

Trigger: user asks to check/review/validate an existing `.html`/deck without asking
to generate or modify content.

Action: route directly to Validator. Skip preflight, `new-run.sh`, copy-assets,
design, render, and publish. Return the business-readable report generated by
`check-only.sh`; do not reclassify by internal rule families unless requested.

### GENERATION_FROM_SOURCE_HTML

Trigger: user uploads or points to an HTML file and says it is for reference,
inspiration, imitation, remake, recreation, style learning, source material, or
"照着这个重新做". The submitted HTML is not the target artifact to preserve.

Action: route as a new deck generation with HTML as source material:

1. Parser analyzes the HTML into `input/runtime-library/source-dossier.json`,
   including structure, copy, assets, screenshots, and layout/style signals.
2. Designer creates fresh scenario, `DESIGN-PLAN.md`, and `outline.json`.
3. Renderer creates a new `deck.json` and `index.html`.
4. Validator gates the new HTML before delivery.

The source HTML may inform content and visual direction, but Renderer owns the
new output. Do not promise pixel preservation unless the user explicitly asks for
replica conversion.

### EDIT_IMPORTED_HTML

Trigger: user uploads or points to an HTML file and asks to modify, continue,
optimize, fix, replace text, adjust style/layout, or otherwise work "on this
HTML". The submitted HTML is the current target state.

Action: import the current HTML as an already-rendered deck state before editing:

1. Snapshot the original HTML under `input/source.html` and copy the working
   artifact to `output/index.html`.
2. Analyze it into `source-dossier.json`, then create lightweight
   `DESIGN-PLAN.md`, `outline.json`, and `deck.json` that represent the existing
   state. Mark the artifacts with `source_role: target-html` or
   `imported_existing_state`.
3. If the HTML already has `.slide` / `data-slide-key`, preserve them. If it is
   ordinary HTML, wrap the page or major sections as raw DeckJSON slides instead
   of redesigning.
4. Route the requested change to Editor. Editor should prefer editing
   `deck.json` and rerendering; direct HTML mutation is reserved for explicit
   round-trip recovery or non-DeckJSON targets.
5. Run Validator before handoff, scoped to the locked slide(s) when possible.

This mode treats `current HTML = already completed upstream state`; it must not
fall back to a freeform one-off HTML patch unless importing fails and the user
accepts that fallback.

### RESKIN

Trigger: user gives foreign/non-Feishu HTML and asks to "换皮", "套飞书模板",
"Feishu 化", "reskin", or "改成飞书风格" while preserving the same visual design.

Action: route to Editor RESKIN. Apply Feishu chrome mechanically via
`assets/reskin.sh`. Skip redesign and design-phase judgment. If a non-mechanical
trade-off appears, ask first.

### LIFT+SWAP

Trigger: user gives another deck/existing deck and asks to reuse pages/layout while
changing copy, client, or wording.

Action: default toward preserving the source layout. If ambiguous, ask once:
"保留原版式 lift+换文字,还是用 schema 重新设计?" Tool by case:

- **Lift page(s) into a BRAND-NEW deck** ("开个新 deck 复用某页"): use
  `deck-json/lift-to-new-deck.py SRC PAGES DEST [--new-key K] [--render]`. It
  scaffolds a schema-valid deck.json and delegates each slide copy to
  `deck-cli.py paste` (embedded scoped CSS rekeyed, assets copied, `lifted`
  stamped). Do NOT hand-build the deck.json — that path repeatedly failed on bad
  `deck.mode` enum / missing render args / forgotten CSS rekey.
- **Add a page to an EXISTING deck.json**: `deck-cli.py <dest> paste --from SRC
  --key K [--new-key NK]` (DeckJSON-native sources).
- **Legacy / foreign HTML source** (no deck.json): `assets/lift-slides.py --shake`.
- **Deterministic copy swap** after the lift: `deck-json/apply-text-pairs.py`.

This is distinct from converting external PDF/PPT material, which uses Replica vs
Rewrite rules in `converting-existing-material.md`.

### GENERATION

Mode for producing a **fresh run artifact**: a new deck, or a re-authored deck
built from PDF / PPT / doc material (import-then-create — pure 1:1 import is
`PARSE` + Editor, see **Import vs re-create** above). Run design first with the
raw-first policy: per page, default to `layout: "raw"` inside DeckJSON and fall
back to schema only for pure standard shapes. Then preflight/new-run, DeckJSON
render, validation, and delivery.

Substantive edits to an **existing** deck are NOT GENERATION — they stay in the
EDIT family and route to Editor without a new run (see **Edit vs Generation
boundary** above). The dividing line is whether you are creating a new run
artifact or modifying one that already exists, not how large the change is.

### EDIT

Edit copy / layout of an existing deck inside its own run directory; `deck.json` /
`index.html` already exist. Route to Editor (`subskills/editor/SKILL.md`); do not
open a new run. A beyond-default design on an edited page still passes the design
gate, but the work is an edit of the existing artifact. `RESKIN`, `LIFT+SWAP`, and
`EDIT_IMPORTED_HTML` are the specialized EDIT-family modes documented above.

### TRANSLATE / PARSE / IMPORT / SIMULATE / PUBLISH

These map 1:1 to their owning subskills (Translator / Parser / Importer /
Simulator / Publisher) per the **Authoritative Mode Enum**. Their detailed
workflows live in those subskills and in the root `SKILL.md` Canonical Workflow;
this router only fixes the vocabulary and the routing target.
