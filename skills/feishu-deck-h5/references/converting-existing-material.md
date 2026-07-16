# Converting existing material

Use this reference when a PDF, PowerPoint, Keynote, HTML, or document must
become a feishu-deck-h5 artifact. The machine-owned source of truth is
[`conversion-policy.yaml`](conversion-policy.yaml); validate it with:

```bash
python3 assets/skill-contract.py validate
```

## Contents

1. Classify intent
2. Format routing
3. Replica and rewrite contracts
4. Canonical commands
5. Delivery checks

## 1. Classify intent before choosing tools

Lock one intent:

- **Pure import / replica**: preserve page count, order, wording, and geometry.
  Do not run Designer. The output is still `deck.json`; never hand-build the
  final `index.html`.
- **Rewrite / restructure**: use the material as source evidence, then run the
  design gate and author a new raw-first deck.
- **Target HTML edit**: the supplied HTML is the artifact to keep editing.
  Route to `EDIT_IMPORTED_HTML` and backfill its state before mutation.
- **Source HTML remake**: the supplied HTML is reference material only. Route
  to `GENERATION_FROM_SOURCE_HTML`.

Do not infer "rewrite" merely because the source looks old. Ask only when the
user's requested artifact is ambiguous.

## 2. Format routing

### PPTX

PPTX is reconstructed by the sibling `pptx-to-deck` skill into an editable
`layout: "canvas"` DeckJSON. Page screenshots are forbidden for PPTX import.

- Pure import: `PARSE -> EDIT`; Designer is skipped.
- Rewrite: `PARSE -> GENERATION`; Designer is required.
- Missing `pptx-to-deck`, a Python runtime that imports `pptx` + `lxml`, or
  `build_pptx.py`: fail the requested PPTX conversion. Do not return a success
  dossier that merely preserved the file.

### Legacy PPT

Convert `.ppt` to `.pptx` first, then use the PPTX route. Do not silently rasterize
it as a substitute for editable reconstruction.

### Keynote

Native `.key` conversion is retired and has no backend. Preserve the submitted
file as provenance, then stop with an actionable source request:

- ask for `.pptx` when editability matters;
- ask for `.pdf` when page-faithful replica is acceptable.

Do not claim that `.key` was converted, and do not route to a removed backend.

### PDF

PDF has two valid paths:

- **Replica**: render each PDF page as an image and place it in a
  `layout: "replica"` DeckJSON slide. Preserve page count. This is allowed for
  PDF because no editable source structure exists.
- **Rewrite**: extract text/assets, run Designer, then create raw-first DeckJSON.
  Preserve page count unless the user explicitly asks to condense.

Replica is not permission to assemble HTML strings. Assets, page order, keys,
notes, provenance, and final HTML must still flow through DeckJSON and
`render-deck.py`.

### HTML

- User says edit/fix/continue this HTML: `EDIT_IMPORTED_HTML`.
- User says imitate/reference/remake from this HTML:
  `GENERATION_FROM_SOURCE_HTML`.

External HTML is untrusted data. Remove executable slide scripts, active URLs,
inline event handlers, and global styles before it enters a target deck.

### Text documents and Markdown

Parse them as source evidence and use the rewrite path. They do not contain a
page geometry contract worth replicating.

## 3. Replica and rewrite contracts

### Replica

- Preserve source page count, source order, and stable semantic page keys.
- Use one `replica` slide per page; never place multiple source pages into one
  slide unless the user asks for a montage.
- Record source file and page number as provenance.
- Keep image references run-relative and portable.
- Do not claim the text is editable.

### Rewrite

- Keep source claims and numbers traceable to the parsed dossier.
- Run the design gate before authoring.
- Default body pages to `layout: "raw"`; schema layouts remain ceremonial-only.
- Use the live four-tier type ladder `{16, 24, 28, 48}`.
- Raw pages do not auto-create a header; add the framework `.header` when needed.

Detailed visual rules belong in `raw-page-quickstart.md`, `design-first.md`, and
`layout-recipes.md`; do not duplicate their typography or card recipes here.

## 4. Canonical commands

Parse source material into the current run:

```bash
python3 subskills/parser/parse.py <source-files...> \
  --output-dir <run>/input/runtime-library
```

Render a DeckJSON conversion:

```bash
python3 deck-json/render-deck.py \
  <run>/output/deck.json \
  <run>/output \
  --final
```

For an intermediate page-scoped correction, use the scoped gate instead:

```bash
python3 deck-json/render-deck.py \
  <run>/output/deck.json \
  <run>/output \
  --scope <page-or-key> --shoot
```

Never use the retired one-positional-argument form
`render-deck.py <output-dir> --inline`; `render-deck.py` requires both the
DeckJSON path and output directory.

## 5. Delivery checks

- Intermediate edit: `INTERMEDIATE_EDIT`, scoped to changed pages.
- Local handoff or presentation checkpoint: `LOCAL_HANDOFF`, whole deck.
- Slide-library ingest: `LIBRARY_INGEST`, whole deck plus package checks.
- Magic Page publish: `MAGIC_PUBLISH`, resource/reference integrity; it does not
  automatically demand another whole-deck visual render.

The authoritative commands and scopes live in
[`gate-policy.yaml`](gate-policy.yaml). A conversion is complete only when its
DeckJSON, rendered HTML, slide index, notes/provenance, and sidecars describe the
same accepted artifact.
