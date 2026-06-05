# Design Proposal — `translator` subskill (deck localization/translation)

> Status: **PROPOSAL for review**. Nothing in SKILL.md, subskills/, or deck-json/
> has been changed by this document. It specifies an 8th subskill, `translator`,
> that turns "把这份 deck 翻译成英文/他语" into a first-class, pipeline-native
> capability — built as a **thin orchestration + translation-discipline layer
> over existing tools**, never a parallel HTML system.
>
> Origin: a Starbucks×Lark deck was hand-translated by splitting `index.html`
> into chunks (slow: workers did 20–77 sequential Edits each) and it MISSED 5
> embedded `<iframe>` HTML files. Root cause = the deck.json pipeline (and its
> purpose-built `apply-text-pairs.py`, audit F-44) was bypassed. This subskill
> makes the official route the only route.

---

## 1. Goal / non-goals

**Goal.** Given a rendered feishu-deck-h5 deck (with or without `deck.json`) and a
target language, produce a fully localized deck through the source-of-truth
pipeline, with structure/CSS/SVG/`data-text-id` guaranteed untouched, plus the
translation-specific concerns that same-language editing never hits.

**Non-goals.**
- Re-designing or re-laying-out slides (that's designer/editor).
- Translating text **baked into raster images** (product screenshots, photos,
  PPTX-export PNGs) — out of reach without new art; the subskill *reports* these.
- Producing a real `.pptx`.

**Why a subskill (not a standalone Claude agent, not just an editor footnote).**
- It is tightly coupled to pipeline tools (`sync-index-to-deck`, `apply-text-pairs`,
  `render-deck`, `validate-deck`) that live in this skill; a detached agent loses them.
- "翻译成英文" is a primary user intent, deserving an explicit router mode — not
  buried in editor's same-language TEXT-SWAP.
- It carries discipline editor's text-swap does not: cross-language glossary,
  **overflow-after-translation** (target text is longer → clipping), external
  iframe coverage, baked-image reporting, language-tag + brand-asset swap.
- It stays **thin**: change-of-copy, render, and validate are all *delegated* to
  existing editor/renderer/validator tooling. No reimplementation.

---

## 2. Where it sits (proposed controller integration — NOT yet applied)

**Subskill Map — add one row:**

| Need | Subskill |
| --- | --- |
| Translate / localize an existing deck (or page range) into another language: backfill→extract→translate-pairs→apply→render→validate, plus embedded-iframe and brand-asset localization | `subskills/translator/SKILL.md` |

**Mandatory Router — add `translate` to the mode list** (line 1 of the router):
`parse / design / render / validate / simulate / edit / publish / full pipeline /
generation-from-source-html / edit-imported-html / **translate**`.

**Canonical Workflow — add under "For an existing deck":** a `translate` entry that
routes to Translator, which itself calls Editor's apply-text-pairs + Renderer +
Validator. Translator may only run after the deck is in deck.json form (auto-backfill
if missing). Publisher still only after explicit confirmation.

**Relationship to editor.** Translator REUSES `deck-json/apply-text-pairs.py`
(editor's TEXT-SWAP engine) and `render-deck.py`. It does not duplicate them. If a
user says "reskin copy to new customer" (same language) → editor TEXT-SWAP. If
"translate to <lang>" → translator (which is text-swap + cross-language discipline).

---

## 3. Canonical workflow

Router lock: `mode=translate | scope=deck | page-range | target=index.html (+deck.json) + --lang=<code>`.

```
1. SOURCE-OF-TRUTH FIRST
   - deck.json present?  → use it.
   - missing (legacy/merged render)?  → sync-index-to-deck.py  (auto-backfill to
     deck.json; legacy HTML becomes `raw` slides with inner data.html — lossless,
     never force-structured; per DECKJSON-UNIFIED-INTERMEDIATE-SPEC §4/§5).

2. EXTRACT TRANSLATABLE UNITS                         [NEW tool, §4]
   extract-text-pairs.py deck.json --lang <l>  >  pairs.skeleton.json
   → per slide: {key, replacements:[{find:"<verbatim CJK run>", replace:""}]}
     deduped, longest-first. `find` strings are copied VERBATIM from data.html
     (and from translatable attrs / CSS content:) so apply-text-pairs matches
     them exactly — eliminating the <br>/whitespace "unmatched" problem.

3. TRANSLATE  (controller fans out parallel workers, by slide-group)
   - Each worker is given: its slides' full data.html (for CONTEXT) + the list of
     `find` strings, the GLOSSARY (§5.1), and the condense-for-fit rule.
   - Worker fills `replace` for each `find` and returns the pairs only.
     Workers DO NOT write files → single writer = controller. (Fixes the old
     slow per-string-Edit model: each worker now emits structured pairs once.)

4. APPLY  (REUSE editor tool — deterministic, structure-safe)
   apply-text-pairs.py deck.json pairs.json
   → only swaps strings inside data.html; structure / CSS / SVG / data-text-id
     100% untouched; reports unmatched (handle leftovers, §6).

5. RENDER  (REUSE)
   render-deck.py deck.json  → index.html   (renderer guarantees structure)

6. EXTERNAL IFRAMES  (deck.json does NOT cover these — the thing the hand-run missed)
   - detect local <iframe src="*.htm(l)"> in the rendered deck.
   - for each: create  <name>.<lang>.html  copy, translate it (worker; HTML text +
     visible JS string literals), re-point the deck's iframe src to the copy.
   - keeps the source-language deck intact (copy-and-repoint, not in-place).

7. BRAND / ASSET LOCALIZATION  (deterministic)
   - brand wordmark var (--fs-asset-logo / -mono) + direct lark-logo refs → the
     target-language asset (e.g. assets/lark-en-logo.png) if present.
   - <html lang>, fs-language meta → target code.
   - baked-in-image Chinese (product screenshots/photos/PPTX PNGs): REPORT the
     slide list; cannot fix without new art.

8. QA GATES  (REUSE validator + translation-specific, §7)
   validate-deck.py  +  translation QA: (a) residual visible CJK in target deck &
   iframe copies, (b) overflow-after-translation render pass (baseline-diff: report
   only clipping/spill the target introduced that the source did not have).
   Fix regressions with targeted text-only pairs/edits; re-render; re-check.
```

Output: localized `index.html` + `deck.json` (now maintainable & re-translatable) +
`*.<lang>.html` iframe copies + a localization report (unmatched pairs, baked-image
slides, overflow fixes).

---

## 4. New artifacts (small, additive)

### 4.1 `deck-json/extract-text-pairs.py`  (the one genuine gap)
The pipeline can APPLY pairs (`apply-text-pairs.py`) but nothing GENERATES the
`find` side from a deck. Hand-authoring `find` strings is exactly what causes
apply-text-pairs' "unmatched" failures (<br>/emoji/whitespace normalization). This
tool generates them verbatim.

- **Input:** `deck.json` [`--slides key,key`] [`--lang`] [`--attrs alt,title,aria-label,data-screen-label,placeholder`].
- **Per slide** (`data.html` for raw/backfilled; text fields for any schema slide):
  extract every CJK-bearing **text run** at text-node granularity (do not span
  across child tags), plus CJK in the listed attributes and in CSS `content:`
  strings. Dedup within slide; sort **longest-first** (so apply-text-pairs can't
  do partial-substring damage).
- **Output:** `[{key, replacements:[{find, replace:""}]}]` — the apply-text-pairs
  input format, with `replace` empty for workers to fill.
- **`--report`:** per-slide CJK-run counts + total (for fan-out balancing).
- Exit non-zero if a slide has CJK the extractor could not isolate (so nothing is
  silently skipped).

### 4.2 `subskills/translator/SKILL.md`
The capability doc: router lock, the §3 workflow, the worker model (§6), the
glossary discipline (§5.1), the QA gates (§7), and the "REUSE, don't reimplement"
hard rule. Mirrors the size/shape of editor/SKILL.md. Lists which `deck-json/*`
tools it calls.

### 4.3 Translation QA  — extend `validate-deck.py` with `--lang <code>`  (or `references/translation-qa.md`)
- residual visible CJK in target deck + iframe copies (text nodes / translatable
  attrs / CSS content: only — ignore comments / asset paths / font names).
- overflow-after-translation: render source + target at 1920×1080, report slides
  where the target has clipping/spill the source did not (baseline diff). This is a
  translation-only failure mode (target longer than CJK); fold the salvaged scanner
  from the retired `deck-translate.py` here.

### 4.4 Default glossary  — `subskills/translator/glossary.default.json`
飞书→Lark (never "Feishu"), 星巴克→Starbucks, 豆包→Doubao, 字节跳动→ByteDance,
企业微信→WeCom, 小红书→RED, 拿铁→Latte, 绿围裙→Green Apron, 数字员工→digital
employee, 口味雷达/TasteRadar→TasteRadar, AI 协调员→AI Coordinator, … Overridable
per run; workers MUST apply it for consistency.

---

## 5. Reuse map (thin shell — what it calls vs. what's new)

| Step | Mechanism | New or reuse |
| --- | --- | --- |
| backfill legacy HTML → deck.json | `sync-index-to-deck.py` | **reuse** |
| generate translatable `find` pairs | `extract-text-pairs.py` | **NEW (§4.1)** |
| fan-out translation | controller multi-agent dispatch + worker prompt | reuse pattern, new prompt |
| apply translated pairs | `apply-text-pairs.py` (editor TEXT-SWAP engine) | **reuse** |
| re-render | `render-deck.py` | **reuse** |
| iframe copies + repoint | small documented step (+detector) | **NEW (small)** |
| brand logo / lang tag swap | deterministic regex on rendered html | **NEW (small/script)** |
| structure/visual/lang validation | `validate-deck.py` (+ `--lang`) | reuse (+ small ext) |
| overflow-after-translation | playwright baseline-diff (salvaged) | **NEW (small)** |

### 5.1 Worker model
- Workers translate, they do NOT touch files (single-writer = controller; avoids the
  concurrent-edit hazard and the old per-string-Edit slowness).
- Input per worker: slide-group `data.html` (context) + `find` list + glossary +
  condense rule. Output: filled `{find, replace}` pairs (validated by a schema).
- Balance fan-out by extract `--report` weight (raw/dense slides cost more).

---

## 6. Edge handling & failure modes
- **apply-text-pairs reports unmatched** → almost always a `find` that wasn't
  verbatim; because extract-text-pairs produces verbatim `find`s this should be ~0.
  Any leftover: surface to user, fix by hand.
- **Same CJK string, different meaning across slides** → pairs are per-slide-key, so
  context is preserved; no global collision.
- **CJK used as a logic key in raw-slide JS** → extractor flags strings inside
  `<script>`; workers translate only display literals (documented).
- **Raw slides after backfill** = inner HTML; translation is HTML-text swap (same as
  any raw slide) — uniform, no special path.
- **External iframes / baked images** → §3 steps 6 & 7; images are reported, not fixed.

---

## 7. QA gates (must pass before handoff)
1. `validate-deck.py` clean (structure/visual/delivery).
2. residual-CJK scan: zero visible Chinese in target deck + iframe copies (comments/
   paths/fonts excepted).
3. overflow-after-translation: zero NEW clipping/spill vs source (design-overflow
   that already existed in the source is not a regression).
4. apply-text-pairs unmatched count = 0 (or each leftover explained).
5. baked-image-Chinese report attached (known limitation, not a gate failure).

---

## 8. Retire / salvage
- **Retire** `~/bin/deck-translate.py` + `~/.claude/workflows/translate-deck.js`
  (parallel HTML system that reinvented apply-text-pairs + deck.json round-trip).
- **Salvage** its two genuinely-useful, pipeline-missing bits into the subskill:
  (a) embedded-iframe auto-discovery, (b) overflow-after-translation scanner.

---

## 9. Open questions for the maintainer
1. Glossary home & precedence: ship `glossary.default.json` in the subskill +
   allow a per-deck `runs/<deck>/glossary.json` override? (proposed: yes)
2. `validate-deck.py --lang` extension vs a separate `translation-qa` script —
   which keeps the validator's altitude cleanest?
3. iframe handling confirmed as **copy-and-repoint** (keeps the source-language
   deck intact)? (proposed: yes)
4. Should `extract-text-pairs.py` also emit schema-field pairs, or is raw-slide
   `data.html` coverage enough given backfill makes everything raw? (proposed:
   cover both; cheap.)
5. Multi-target: keep `index.<lang>.html` side-by-side per language, or one deck per
   output folder? (affects publisher.)
6. Does translation belong to its own run folder convention
   (`runs/<deck>-<lang>/`) for the making-of log?

---

## 10. Validation plan (after build)
Re-do the Starbucks×Lark deck end-to-end through the new path:
`sync-index-to-deck` → `extract-text-pairs` → (reuse the already-produced EN copy as
filled pairs, no re-translation) → `apply-text-pairs` → `render-deck` →
`validate-deck --lang en` + overflow pass + iframe coverage. Confirms backfill is
clean on a schema+raw mixed deck and the deck gains a maintainable `deck.json`.
Compare the rendered output against the current hand-made `index.en.html`.

---

## 11. Proposed file layout
```
subskills/translator/
  SKILL.md                  # the capability (router, workflow, worker model, QA)
  glossary.default.json     # default term map (Lark, Starbucks, …)
deck-json/
  extract-text-pairs.py     # NEW — generate verbatim find-side pairs from deck.json
  (apply-text-pairs.py)     # reused as-is
  (sync-index-to-deck.py)   # reused as-is
  (render-deck.py)          # reused as-is
  (validate-deck.py)        # + optional --lang residual-CJK / overflow mode
references/
  translation.md            # optional: deep reference (glossary discipline, iframe
                            #   coverage, overflow-after-translation, baked images)
SKILL.md (controller)       # +1 router mode, +1 subskill-map row, +1 workflow note
```

---

## 12. VALIDATION FINDING (2026-06-04) — round-trip is LOSSY on heavily-merged decks → TWO-BRANCH architecture

Ran the proposed step-1 (backfill→render) on the real Starbucks×Lark deck (a merged
"合并版 61 页" with **527k chars of bespoke head `<style>` CSS**, 1368 per-slide rules):

| stage | CSS chars reproduced |
| --- | --- |
| original head bespoke CSS | 527,221 |
| `sync-index-to-deck` backfill only | 164k (31%) — head CSS NOT captured; deck.json slides get only `html` (no `custom_css`) |
| + `migrate-head-css-to-custom-css` | 360k (68%); custom_css populated on 23/61 slides |

`migrate` **self-reports** leaving 8 `@media`/`@supports` blocks + non-`[data-slide-key]`
(shared-class) rules un-migrated. render-deck from deck.json does NOT carry those →
**~32% of this deck's bespoke CSS has no per-slide home → the deck.json round-trip
is lossy for this deck.** Backfill/render is content-faithful (61 slides, body CJK
13841≈13792 preserved) but **CSS-lossy** for merged-legacy decks.

### Implication
- For **pipeline-native decks** (clean deck.json, per-slide CSS already in
  `custom_css`): translation IS trivial — edit deck.json text → render. The user's
  premise holds; `apply-text-pairs.py` is the right tool.
- For **merged/legacy decks like this one**: full deck.json round-trip degrades
  visuals. Translating the **rendered HTML in place** (CSS untouched) is actually
  the *higher-fidelity* choice — which is what the original hand-run did; its only
  real sin was bypassing the structure-safe **pairs** mechanism, not operating on
  index.html.

### Revised architecture — translator picks a branch via a PARITY GATE
```
0. backfill (sync-index-to-deck) + migrate-head-css → deck.json
1. PARITY GATE: render-deck → screenshot/structural diff vs the source render.
   ├─ PASS (clean round-trip)  → BRANCH A (deck.json):
   │     extract-text-pairs deck.json → translate → apply-text-pairs → render
   └─ FAIL (lossy backfill, e.g. heavy merged CSS) → BRANCH B (in-place):
         extract-text-pairs --from-html index.html → translate →
         apply-text-pairs --html index.html  (deterministic verbatim str-replace,
         structure/CSS untouched, NO re-render) 
2. external iframes + brand logo + QA — identical in both branches.
```
Both branches use the SAME structure-safe primitives (extract verbatim finds →
fill → deterministic string-swap). Branch A swaps inside deck.json `data.html` then
re-renders (source-of-truth). Branch B swaps inside index.html directly (no
round-trip) for decks that can't losslessly round-trip.

### Tooling deltas this implies
- `extract-text-pairs.py` gains `--from-html <index.html>` (extract verbatim finds
  straight from rendered HTML, for Branch B). [already structured to add this]
- `apply-text-pairs.py` gains an `--html <index.html>` mode (apply pairs to a
  rendered HTML file, not just deck.json `data.html`) — small addition, same swap
  logic. OR a thin sibling `apply-text-pairs-html.py`.
- Parity gate = a small `roundtrip-parity.py` (render backfilled deck.json, diff CSS
  char count + per-slide-key selector count + a few screenshots vs source render;
  PASS threshold configurable).

### For the Starbucks deck specifically
It is a **Branch-B** deck (lossy backfill). The already-delivered `index.en.html`
(in-place translation, all CSS preserved) is the CORRECT artifact for it; re-doing
it through Branch A (deck.json) would *lose* bespoke CSS. Recommendation: do NOT
re-run it through Branch A; keep the in-place output, and use it as the canonical
**Branch-B regression fixture** for the translator subskill.
