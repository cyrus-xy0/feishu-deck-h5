# Architecture: dual-background editable deck

## The core idea

Two images per slide:
- **`bg`** — the ORIGINAL render (with text). Shown in **view mode**.
- **`bgNotext`** — the same slide with all text removed. Shown in **edit mode**.

In **view mode** the viewer sees the *real* PowerPoint/Keynote render — perfect
fonts, kerning, alignment, custom shapes, gradients. Nothing we reconstruct can
beat the original render, so we just show it. The structured text layer sits on
top but its glyphs are `color:transparent` — **invisible yet still selectable**,
so a reader can drag-select → copy → paste into Google/DeepL/豆包 without ever
seeing reconstructed text. (Earlier versions used `visibility:hidden`; transparent
+ selectable is strictly better — same fidelity, but the text is real DOM you can
copy and a browser can translate.)

```
view (高保真): bg(with text) visible · text layer TRANSPARENT but selectable  → 100% fidelity
xl (翻译模式):  bgNotext      visible · text layer VISIBLE (real text)          → browser-translatable
edit (E):      bgNotext      visible · text layer visible + editable (original font size)
```

The three states are body classes: none (高保真), `xl` (翻译模式), `edit`. The
bottom-bar 🌐 toggles `xl`; `E` toggles `edit`. See `references/translation.md`
for why pixel-perfect transparent text and browser whole-page translate are
mutually exclusive (hence the toggle).

## Why it doesn't ghost (重影 audit)

When you edit a box it gets `.dirty` and becomes visible in *view* mode too, so
your change shows on top of the original image. Problem: the original `bg` still
has the old text baked in underneath.

Fix: every `.tb` box's CSS background is the **no-text image, sized to the whole
deck, positioned at `-left,-top`** — i.e. the exact same-region crop of `bgNotext`.
So a dirty box paints the clean (text-free) background of that region first, then
the new text on top — the baked text underneath is fully masked. No ghosting,
regardless of whether the new text is longer or shorter.

`dirty` is decided by `innerHTML !== original` — editing back to the original
clears it, so untouched/reverted boxes show the pristine `bg` again.

## Layout: container queries, no JS scaling

```css
#deck{ width:min(100vw,calc(100vh*16/9)); height:min(100vh,calc(100vw*9/16));
       container-type:size }
```
`#deck` is a pure-CSS 16:9 letterbox. Every element inside uses `cqw`/`cqh`
(1% of the deck's width/height), so the whole deck scales with the container —
correct in any iframe/viewport with zero JavaScript measurement (an earlier
`transform:scale` + fixed-1920 approach mis-measured inside sandboxed iframes
and drifted).

## Text fidelity in EDIT mode

- **Per-paragraph font size** — a frame with 标题24pt + 说明18pt renders each line
  at its own size (don't size the whole box by the first run).
- **Resolved alignment** — read `lstStyle/lvlNpPr/@algn`, not just
  `para.alignment`; many decks set 居中 at the list-style level.
- **Original font size by default** — keep the PPT size so creators judge real
  line fit. View mode is the original image anyway, so overflow only matters in
  edit/翻译 mode (see autofit below).
- **Per-frame insets** — from PPT `bodyPr` lIns/rIns/tIns/bIns.

## Hidden-behind-image text

A text frame fully covered by a later (higher z-order) picture was invisible in
the deck (the picture sat on top). `extract.py` detects this and **skips** it, so
we don't float hidden text onto the editable layer (which caused a stray "Zoom"
to overlap "Workday" before the fix).

## Media

`extract_media.py` probes each clip with ffprobe: **no audio → GIF-style**
(`autoplay muted loop`, behaves like the original animated GIF); **has audio →
real video** (`controls`, click-to-play, first frame via `#t=0.1` so it isn't a
black block). `.mov`→`.mp4` remux and `.gif`→`.mp4` convert so every overlay is a
uniform `<video>`.

## Box editing (edit mode)

Beyond editing text, edit mode lets you reshape boxes — useful when translated
text needs more room or a frame is mis-placed:
- **✥ handle** (top-left of each box): single-click to select, click again to
  multi-select, drag to move the whole selection. A box's CSS `background-position`
  moves with it so its no-text mask stays aligned.
- **◢ handle** (bottom-right): drag to resize the box.
- **Toolbar** (above the selection): 左/中/右 align, A-/A+ per-box font scale.
- **#gfont A-/A+** (bar, 翻译态): global font scale for the whole deck.

These write `positions` / `sizes` / `aligns` / `fontscale` / `gscale` into the
same persistence layer as edits.

## Autofit & lazy loading

- **Grouped autofit** (`window.__deckFit`): on each slide, boxes that overflow are
  shrunk via a `--fit` CSS var; same-size sibling boxes shrink by the **same**
  factor (keeps 同级字号一致), floor 0.65. Titles (`.tb-title`) and manually-scaled
  boxes are excluded. Runs on page show, resize, and when browser translation is
  detected. `--gfit` is the global multiplier; final size = `base * --fit * --gfit`.
- **Lazy bg loading**: `bg`/`bgNotext` carry `data-src`, not `src`; only the
  current ±2 slides' images are loaded (the right one per mode). Stops a 60-page
  deck from eagerly fetching ~100 MB and black-screening on first paint. Toggling
  翻译态 loads the current slide's no-text image on demand.

## Persistence & export

`order` (page order), `hidden` (per-page), text edits, and box geometry
(positions/sizes/aligns/fontscale/gscale) persist — to a FaaS backend if `--faas`
is set (shared, cross-device; required inside 妙笔's sandboxed iframe where
localStorage is blocked), else to localStorage. **Edits auto-save on edit-mode
exit** (this version has no manual save/export button). On load the deck still
reads `window.__INIT` (`order`+`hidden`) if present, so a hand-baked export opens
in the arranged state. See `references/backend-persistence.md`.
