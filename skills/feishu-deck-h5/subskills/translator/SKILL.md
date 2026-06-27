---
name: feishu-deck-h5-translator
description: |
  Subskill for the feishu-deck-h5 pipeline. Use to translate or localize an
  existing deck or page range into another language through the source-of-truth
  flow: backfill, parity branch decision, verbatim text pairs, apply, render or
  in-place update, embedded iframe coverage, brand/lang asset swaps, and
  translation QA.
---

# translator — feishu-deck-h5 subskill

Localize / translate an existing deck into another language through the
source-of-truth pipeline. **Thin orchestration over existing tools** — it reuses
`apply-text-pairs.py` (editor's structure-safe text-swap engine), `render-deck.py`,
and `validate-deck.py`; it never hand-edits final HTML or builds a parallel system.

Translation = same-language TEXT-SWAP (editor) + cross-language discipline:
glossary, **overflow-after-translation** (target text is longer than CJK → clipping),
external-iframe coverage, brand-asset/lang swap, baked-image reporting.

## Router lock
`mode=translate | scope=deck | page-range | target=index.html(+deck.json) | --lang=<code>`.
Default target language English; default glossary `subskills/translator/glossary.default.json`
(override with `runs/<deck>/glossary.json`).

## Hard gates
1. **Never let an LLM rewrite markup.** Translation changes STRINGS only. Apply via
   `apply-text-pairs.py` (deck.json) — structure / CSS / SVG / `data-text-id` stay 100%.
2. **Source-of-truth first.** Operate on `deck.json`. No deck.json → auto-backfill
   (`sync-index-to-deck.py`) before anything else.
3. **Branch decision is mandatory** (see below). Do not blindly re-render a deck
   whose backfill is lossy — you will drop bespoke CSS.
4. **Validate before handoff** — `validate-deck.py` + `translation-qa.py` (residual
   Chinese + overflow). Fix findings, re-check.
5. Embedded `<iframe>` HTML and baked-image Chinese are NOT in deck.json — handle
   them explicitly (steps below); never silently skip.

## Step 0 — backfill + BRANCH decision (parity gate)
```bash
DJ=deck-json
# 1. ensure deck.json (auto-backfill if absent); CSS-heavy legacy decks also migrate head CSS:
python3 $DJ/sync-index-to-deck.py <deck>/index.html <deck>/deck.json          # backfill if missing
python3 $DJ/migrate-head-css-to-custom-css.py <deck>/index.html <deck>/deck.json   # head per-slide CSS → custom_css
# 2. render the backfilled deck.json and parity-check vs the source render:
python3 $DJ/render-deck.py <deck>/deck.json /tmp/rt/ --skip-copy-assets --skip-validate-html --skip-fit-check
python3 $DJ/translation-qa.py parity <deck>/index.html /tmp/rt/index.html      # prints BRANCH=A|B
```
- **BRANCH A** (parity PASS): deck round-trips cleanly → translate deck.json, re-render. Ideal.
- **BRANCH B** (parity FAIL): backfill is lossy (heavy merged/head CSS with no
  per-slide home) → translate **in place on index.html** (CSS untouched, no
  re-render). Most pipeline-native decks are A; merged/legacy artifacts are B.

## BRANCH A — deck.json round-trip
```bash
python3 $DJ/extract-text-pairs.py <deck>/deck.json > pairs.skeleton.json   # verbatim FIND side
#   → fan out workers (see Worker model) to fill every "replace"
python3 $DJ/extract-text-pairs.py pairs.filled.json --check                # gate: no empty / no CJK left
python3 $DJ/apply-text-pairs.py <deck>/deck.json pairs.filled.json         # deterministic swap
python3 $DJ/render-deck.py <deck>/deck.json <deck>/                        # re-render index.html
```

## BRANCH A-CANVAS — PPTX-import decks (layout:"canvas")
A `.pptx` import (pptx-to-deck) is a canvas deck: text lives in
`data.elements[].runs[].text`, NOT `data.html`. The flow:

1. **(legacy only) PDF抽词把整行拆成碎片** — applied ONLY to old decks built by the
   retired LibreOffice-PDF **hybrid** pipeline, where one visual line was split into
   many single-glyph positioned elements. The current pure `build_pptx` reads runs
   directly from the PPTX and does **not** fragment, so **skip this step for any deck
   built now**. For a legacy fragmented canvas deck, first normalize:
   ```bash
   python3 $DJ/merge-canvas-lines.py <deck>/deck.json --review <deck>/merge-review.json
   ```
   Clusters same-style + same-row + x-adjacent fragments into one logical line on
   the leftmost host (widened), deletes the siblings. Idempotent; `--dry-run` to
   preview. Skim the review sidecar — heavily scrambled pages (text over video /
   negative-gap overlap) may merge imperfectly; flag those.
2. Then the normal A flow — `extract-text-pairs` already reads canvas run texts,
   and `apply-text-pairs` swaps them **whole-run, strip-matched** (canvas-aware):
   ```bash
   python3 $DJ/extract-text-pairs.py <deck>/deck.json > pairs.skeleton.json
   #   → fan out workers; give each its slides' PPTX ground-truth text as context so
   #     it can repair any still-fragmented find (see references/translation.md)
   python3 $DJ/extract-text-pairs.py pairs.filled.json --check
   python3 $DJ/apply-text-pairs.py <deck>/deck.json pairs.filled.json
   ```
   > **Per-run match limitation (known, by design).** A canvas find matches only
   > when it equals ONE run's stripped text. A phrase split across multiple
   > **format runs** within the same text element (e.g. PowerPoint bolds/colors a
   > sub-span, producing `["营收 ", "<去年", " 同比"]`) can NOT be matched by
   > `apply-text-pairs` — `merge-canvas-lines` only consolidates *same-style*
   > fragments, not format-split runs. `apply-text-pairs` emits an explicit
   > **"canvas find(s) matched NO run"** warning listing every such unmatched find;
   > hand-resolve those (edit `data.elements[].runs[].text` directly, splitting the
   > replacement across the same runs). This is intentional — we are NOT doing
   > cross-run fuzzy matching (it would risk mangling per-run styling).
3. **Re-render must keep the canvas front-end** (letterbox bg CSS + fitText
   overflow-fit + self-contained assets) — plain `render-deck.py` drops them.
   Use the canvas re-render wrapper (lives in pptx-to-deck, which owns those steps):
   ```bash
   python3 <pptx-to-deck>/assets/rerender-deck.py <deck>/deck.json <deck>/
   ```
   It re-renders + make_portable + post_process in one shot (the `input/` assets,
   and `bg/` if any, already exist). **fitText fits overflow** (English ⟶ longer
   than CJK) — measures real `scrollWidth`, condenses (scaleX) or shrinks.
- Always work on a `<deck>-<lang>/` COPY: A-flow re-render overwrites index.html
  in place, so copy the run dir first to keep the source-language deck intact.

## BRANCH B — in-place on rendered index.html (lossy-backfill decks)
Same primitives, but the FIND side is taken from the rendered HTML and the swap is
applied to a copy of index.html (no re-render, so all bespoke CSS survives):
- copy `index.html` → `index.<lang>.html`.
- extract verbatim FIND runs per slide from the HTML; fan out workers to fill replace.
- apply each slide's find/replace **scoped to that slide's `<div class="slide" data-slide-key>` block** (so a word in slide A is not swapped in slide B), longest-first.
- run `extract-text-pairs.py … --check` on the filled pairs first.
- (This is what the Starbucks×Lark deck used; keep it as the Branch-B regression fixture.)

## Shared (both branches)
- **External iframes** (deck.json never covers these): find local `<iframe src="*.htm(l)">`,
  copy each to `<name>.<lang>.html`, translate it (HTML text + visible JS string
  literals; leave JS logic), re-point the deck's iframe src to the copy. Copy-and-repoint
  keeps the source-language deck intact.
- **Brand / language**: `<html lang>` + fs-language meta → target code; brand wordmark
  var (`--fs-asset-logo` / `-mono`) + direct `lark-logo.png` refs → the target-language
  asset (`assets/lark-en-logo.png`) when present.
- **Baked-image Chinese** (product screenshots, photos, PPTX-export PNGs): cannot be
  fixed without new art — collect the slide list and REPORT it. Not a gate failure.

## Worker model (fan-out)
- The controller fans out parallel translation workers by slide-group (balance by
  `extract-text-pairs.py --report` weight). Workers TRANSLATE ONLY — they do not write
  deck files (single writer = controller), avoiding the slow per-string-Edit model.
- Each worker gets: its slides' `data.html`/HTML (for context), the `find` list, the
  GLOSSARY, and the condense-for-fit rule. It returns filled `{find, replace}` pairs.
- Apply all pairs centrally via `apply-text-pairs.py`; handle any "unmatched" report.

## QA gates (before handoff)
```bash
python3 assets/validate.py <deck>/index.html                                # HTML structure/visual/lang gate (add --visual for R-OVERFLOW: catches EN-over-CJK clipping)
python3 $DJ/translation-qa.py residual-cjk --strict-fullwidth <deck>/index.<lang>.html <iframe-copies…>
python3 $DJ/translation-qa.py overflow <deck>/index.html <deck>/index.<lang>.html      # 0 NEW overflow
```
`residual-cjk --strict-fullwidth` is the DEFAULT gate: it hard-fails on both
untranslated CJK **and** fullwidth-punctuation residue (／ ＋ （） 「」 　). The
glossary already tells workers to ASCII-ize these at translation time, but the gate
is belt-and-suspenders — fix any flagged residue ( ／→/  ＋→+  （）→()  「」→"  　→space )
with targeted text-only pairs, EXCEPT deliberate fullwidth (e.g. an empty （　　）
avatar frame): keep those and note them so a later run doesn't "re-fix" them. Then
re-run. (Drop `--strict-fullwidth` only if a target audience genuinely wants CJK
punctuation.)

## Tools (in `deck-json/`, except where noted)
`sync-index-to-deck.py` (backfill) · `migrate-head-css-to-custom-css.py` (head CSS →
custom_css) · `merge-canvas-lines.py` (NEW — cluster PDF-fragmented canvas runs into
logical lines; canvas decks only) · `extract-text-pairs.py` (verbatim FIND pairs +
`--check`; reads canvas runs too) · `apply-text-pairs.py` (structure-safe swap —
`data.html` AND canvas `elements[].runs[].text`) · `render-deck.py` (REUSE) ·
`<pptx-to-deck>/assets/rerender-deck.py` (NEW — hybrid canvas re-render = render +
make_portable + post_process) · `validate-deck.py` (REUSE) · `translation-qa.py`
(parity / residual-cjk / overflow).

## References
- `../../references/translation.md` (glossary discipline, branch thresholds, iframe
  discovery, overflow-after-translation, baked-image reporting, command recipes)
- `../../references/reskin.md` (sibling: same-language copy swap)
