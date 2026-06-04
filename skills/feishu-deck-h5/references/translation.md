# translation — feishu-deck-h5 reference

> When to read: routed to `subskills/translator/SKILL.md` (mode=translate). Deep
> detail behind that subskill: branch thresholds, command recipes, the failure
> modes unique to translating a deck. Design rationale: `docs/TRANSLATOR-SUBSKILL-DESIGN-2026-06-04.md`.

## Why translation ≠ generic edit
A deck is rendered from `deck.json` (source of truth) but ships as `index.html`. The
canonical, structure-safe way to change copy is `apply-text-pairs.py` (audit F-44),
which swaps STRINGS inside each slide's `data.html` and never lets an LLM touch
markup. Translation is that, plus four things same-language edits never hit:

1. **Glossary consistency** across the whole deck (飞书→Lark, never Feishu, etc.).
2. **Overflow-after-translation** — the target language is ~1.5–2× longer than CJK
   in a fixed 1920×1080 frame, so previously-fitting titles/cells now clip. This is
   a NEW failure mode; check it explicitly.
3. **External iframes** — many decks embed `<iframe src="*.html">` H5 prototypes
   whose content is the dominant visual but lives OUTSIDE deck.json entirely.
4. **Brand assets & baked-image text** — the corner wordmark is an image var; product
   screenshots/photos have Chinese baked into pixels.

## The branch decision (A vs B) — why it exists
Backfilling a legacy/merged deck to deck.json captures per-slide inner HTML as `raw`
but does NOT capture head `<style>` CSS. `migrate-head-css-to-custom-css.py` recovers
the per-`[data-slide-key]` rules into `custom_css`, but `@media`/`@supports` and
non-per-slide (shared-class) rules have no per-slide home. For a deck with heavy
bespoke/merged CSS, re-rendering from the backfilled deck.json therefore DROPS a
chunk of styling → visual breakage.

`translation-qa.py parity <src.html> <roundtrip.html>` quantifies this (CSS-char
ratio + per-slide-key selector ratio + frame count; default PASS threshold 0.90):
- **PASS → Branch A** (deck.json round-trip): translate deck.json, re-render. The fast,
  ideal path for pipeline-native decks.
- **FAIL → Branch B** (in-place): translate the rendered `index.html` directly via
  verbatim per-slide find/replace; do NOT re-render. Preserves 100% of bespoke CSS.

Measured example (Starbucks×Lark "合并版 61 页"): 527k chars bespoke CSS, backfill+
migrate recovered 68% → parity FAIL → Branch B. Its in-place `index.en.html` (all CSS
preserved) is the correct artifact and the Branch-B regression fixture.

## Command recipes
Branch A (parity PASS):
```bash
DJ=deck-json
python3 $DJ/extract-text-pairs.py <deck>/deck.json > pairs.json     # FIND verbatim, replace=""
# fan out workers to fill every "replace" (glossary + condense); then:
python3 $DJ/extract-text-pairs.py pairs.json --check                # gate: no empty / no CJK
python3 $DJ/apply-text-pairs.py <deck>/deck.json pairs.json         # deterministic swap (reports unmatched)
python3 $DJ/render-deck.py <deck>/deck.json <deck>/                 # re-render
```
Branch B (parity FAIL): copy `index.html`→`index.<lang>.html`; extract verbatim FIND
runs per slide from the HTML; fan out workers; apply each slide's find/replace
**scoped to its `<div class="slide" data-slide-key="K"> … </div>` block**, longest-first;
no re-render.

Both branches then run the Shared steps + QA.

## External iframes
```bash
grep -oE '<iframe[^>]*src="[^"]+\.html?"' <deck>/index.html        # discover local iframe files
```
For each local file: `cp f.html f.<lang>.html`; translate the copy (HTML text +
visible JS string literals — chat bubbles, chart/series labels, button text; leave
JS identifiers/keys/logic); then re-point the deck's `src="f.html"` → `src="f.<lang>.html"`.
A `translation-qa.py residual-cjk` pass must include every iframe copy.

## Brand & language (deterministic)
- `<html lang="zh-CN">` → `<html lang="<code>">`; `<meta name="fs-language" content="…">` → target.
- `--fs-asset-logo` / `--fs-asset-logo-mono` + any direct `url(...lark-logo.png)` →
  `assets/lark-en-logo.png` (white EN wordmark; present in this repo) when targeting EN.
- CSS `content:` strings with CJK render as visible pseudo-element text — translate them.

## Baked-image Chinese (report, don't fix)
Slides built from product screenshots / photos / PPTX-export PNGs carry Chinese in
pixels. List them in the localization report (e.g. by spotting `<iframe>`-less raster
`<img>`/`background-image` with Chinese filenames, then a screenshot eyeball). Fixing
requires re-exporting source art or new captures — out of translation scope.

## QA gates
- `validate-deck.py` — generic structure/visual/language/delivery.
- `translation-qa.py residual-cjk <files…>` — HARD-fails on untranslated CJK
  ideographs; lists fullwidth-punctuation residue (／ ＋ （） 「」 　) as a soft note
  (`--strict-fullwidth` to gate it too). Run on the deck AND every iframe copy.
- `translation-qa.py overflow <src.html> <tgt.html>` — renders both at 1920×1080 and
  reports only NEW clipping/spill the translation introduced (source design-overflow
  is not a regression). Fix with shorter copy (re-apply via pairs), not layout changes.
