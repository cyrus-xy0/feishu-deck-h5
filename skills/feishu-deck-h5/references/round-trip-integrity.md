# round-trip-integrity — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:fork / 回灌 deck.json 的细节 + sync-index-to-deck.py

## ROUND-TRIP INTEGRITY (mandatory) — `deck.json` is the source of truth, never post-render-edit `index.html`

`deck.json` is the canonical spec for a deck's visual state. `index.html` is
a derived artifact — `render-deck.py` regenerates it whenever needed. Any
state that only lives in `index.html` (not in `deck.json`) is **silent drift**
and WILL be destroyed by the next render, fork, or downstream tool that
reads `deck.json`.

### The two halves of the rule

**Half A — Authoring side**: do not post-render-edit `index.html`. All visual
state (CSS, HTML structure, animations, scripts, dev-tools tweaks) MUST go
into `deck.json` — `data.html` for `layout: raw`, or the appropriate
template field for schema layouts. If you iterate quickly in the browser
or paste from dev-tools as an experiment, that is fine — but **port the
change back into `deck.json` before delivery, fork, or library ingest**.

**Half B — Fork / clone / download side**: when you derive a new deck from
an existing one (cp the run folder, clone a slide, install from the
slide-library), **copy BOTH `deck.json` AND `index.html`**, OR run a
parity check first and reconcile drift. If you copy only `deck.json`
because it looks like "the spec", you silently lose every post-render
edit the original author made.

### Why this matters for slide-library ingest

The `feishu-slide-library` skill stores the FULL rendered `source.html`
per deck (intentionally — its CSS, fonts, decoration are shared across
slides). So library ingest itself is safe: animations travel with the
slide because the library ingests `index.html`, not `deck.json`.

The risk is at the AUTHORING boundary BEFORE ingest: if your `index.html`
carries post-render edits that aren't in `deck.json`, and your ingest
pipeline does `finalize.sh` (which re-renders) before submitting, the
freshly rendered HTML will have lost the edits before the library ever
sees them. The library's `--gate ingest` runs `check-only.sh` against
the delivered HTML — it doesn't know about `deck.json`, so it can't
catch this drift on its own. **The deck author owns this check, before
delivery.**

### Detection + recovery

The skill ships `deck-json/sync-index-to-deck.py` for both detection
(dry-run) and recovery (actual sync).

```bash
# Detection — exit 0 with drift report; doesn't mutate
python3 skills/feishu-deck-h5/deck-json/sync-index-to-deck.py \
  <output>/index.html  <output>/deck.json  --dry-run

# Recovery — for each raw slide with drift, extract inner HTML from
# index.html and write back to deck.json data.html. Backs up first.
python3 skills/feishu-deck-h5/deck-json/sync-index-to-deck.py \
  <output>/index.html  <output>/deck.json

# Single slide
python3 ... --slide-key content-pipeline

# Convert template-layout slides (cover/quote/section/iframe-embed/etc) to
# raw to capture post-render edits — LOSSY (drops structured fields). Use
# only when you intentionally need raw to preserve edits.
python3 ... --force
```

**The tool normalizes**:
- Trailing/leading whitespace (some old builder scripts left it in deck.json)
- Asset-path rewrites from `copy-assets.py` (`../input/x` → `input/x`,
  `../../../skills/feishu-deck-h5/assets/x` → `assets/x`) — these are
  expected post-finalize, not drift

**The tool will NOT silently overwrite** non-raw slides (template-rendered:
`cover`, `quote`, `section`, `iframe-embed`, `agenda`, etc.) without
`--force`, because converting them to `raw` loses the structured `data`
fields. Use `--slide-key K --force` to convert one specific slide
when you really do mean to bake post-render edits in.

### Fork checklist (mandatory when deriving a new deck from an existing one)

1. **Copy both files**: `cp -r runs/<src>/output runs/<new>/output` (this
   takes BOTH `deck.json` and `index.html`)
2. **Verify parity**: `python3 .../sync-index-to-deck.py <new>/output/index.html <new>/output/deck.json --dry-run`
3. **If drift detected**: run without `--dry-run` to reconcile. Re-render
   to verify: `python3 .../render-deck.py <new>/output/deck.json <new>/output/`
4. Only THEN start editing the new deck.

If you copied only `deck.json` (skipping step 1's `index.html`), step 2
will report 0 drift but you've already lost the post-render edits from
the source. **You must fork by copying the WHOLE output folder, not
deck.json alone.**

### Postmortem (2026-05-24)

The `kangshifu-ai-lecture` deck was forked from `ai-consumer-growth` by
copying only `deck.json`. Source's `index.html` was ~40 KB larger than
what its own `deck.json` would re-render — those 40 KB were post-render-
edited animations:

- slide 9 `ice-tea-5scripts`: 5 keyframes (`it5-card-in`, `it5-icon-pop`,
  `it5-bar-grow`, `it5-fade-in`, `it5-fade-down`) — 10 animation hits
- slide 10 `content-pipeline`: 10 keyframes (`cp-pipe-flow`,
  `cp-fade-up/down/left/right`, `cp-proc-breathe`, `cp-dot-pulse`,
  `cp-reveal-ltr`, `cp-proc-in`, `cp-r-pop`) — 21 animation hits

The fork inherited animation-less `deck.json`; user noticed in
browser:「这页的动画怎么没有了」. Manual recovery: extract each `.slide`'s
inner HTML from source `index.html`, port back into `deck.json` `data.html`.
~150 lines of one-shot Python. `sync-index-to-deck.py` exists so this is
one CLI invocation next time.

### Single-slide lift (deck.json-native) — and why `custom_css` ends the postmortem above

Forking a WHOLE deck is the section above. Lifting ONE page into the current
deck is `deck-cli.py paste` (LIFT-ARCHITECTURE L3):

```bash
python3 .../deck-cli.py DST/deck.json paste --from SRC/deck.json --key <key> [POS]
```

It deep-copies the slide OBJECT (not DOM out of `index.html`), copies referenced
`input/`/`prototypes/` assets to target-relative paths, auto-de-collides the key,
strips source-bound `data-text-id`, and stamps `lifted` provenance. Because it
operates on `deck.json`, the agent never reads the source `index.html` or the
3491-line `feishu-deck.css`. For a FOREIGN deck with no `custom_css`, use
`assets/lift-slides.py --index` (list) / `--key K` (select) instead — it
tree-shakes framework CSS out of the rendered HTML inside the tool process.

**The doctrine that makes this safe — per-slide CSS lives in `slide.custom_css`,
never in a head/page `<style>`.** The renderer scopes `custom_css` to
`.slide[data-slide-key=KEY]` and emits it as a co-located `<style
data-fs-custom-css>` first-child of the slide, so it travels with the slide
object on paste/clone and round-trips through `sync-index-to-deck.py`
(which skips that block on extraction). The 2026-05-24 postmortem — animation
keyframes living in `index.html` but not `deck.json`, lost on fork — **cannot
recur for slides authored with `custom_css`**: the keyframes are part of the
slide object. Authoring rule: put `@keyframes`/`@media`/per-slide rules in
`custom_css`, write selectors WITHOUT a scope prefix (the renderer adds it).

---

