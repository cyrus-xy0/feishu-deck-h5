---
name: pptx-to-html
description: |
  SUB-SKILL of feishu-deck-h5 (lives at feishu-deck-h5/pptx-to-html/, NOT an
  independently-registered skill). It is the .pptx import path into the deck
  system — invoked from feishu-deck-h5 when the user hands over a PowerPoint.

  Convert an existing PowerPoint (.pptx) presentation into a deck.json + HTML
  deck rendered by the parent feishu-deck-h5 skill — natively, with no
  PowerPoint app, no Keynote, no AppleScript. Walks every slide with
  python-pptx and reconstructs each as absolutely-positioned HTML on a
  1920×1080 canvas: text stays editable HTML, images become <img>, tables
  become <table>, shapes/gradients/lines are reproduced in CSS/SVG.

  Triggers: "把 PPT/PPTX 转成 HTML", "import pptx", ".pptx 转 deck",
  "把这份 PowerPoint 还原成网页/H5", or when the user hands over a .pptx path.

  This is the PowerPoint analogue of rollingai-decks' keynote-to-html, but
  because .pptx is open OOXML, extraction is exact (EMU geometry) and
  cross-platform — it does NOT shell out to any GUI app.

  Per-slide algorithm:
    1. python-pptx walks every shape (recursing groups through their
       chOff/chExt transform) → emits absolutely-positioned HTML.
    2. Text frames → real <div>/<span> with per-run font/size/color/weight,
       paragraph alignment, vertical anchor, bullets, soft line breaks <a:br>.
    3. Theme colors resolved from the master's <a:clrScheme>.
    4. Each slide is emitted as a `layout: "raw"` entry in deck.json.
    5. feishu-deck-h5's render-deck.py wraps it in present-mode chrome.

  Lossy / acceptable failures (do NOT block on these):
    · autofit "shrink-to-fit" text is not simulated (authored size used).
    · charts / SmartArt / picture-fill backgrounds need `--raster` (LibreOffice).
    · radial gradients, freeform custom geometry, image srcRect crop: approximated.
---

# pptx-to-html

## When to invoke

Trigger when the user has a `.pptx` and wants an HTML version that:
  - Looks faithful to the original PowerPoint rendering
  - Has editable text (HTML elements, not pixels)
  - Carries feishu-deck-h5's present-mode chrome (←/→ nav, F fullscreen,
    progress bar, mobile scroll mode)

Do NOT use for: `.key` (use keynote-to-html), or a from-scratch redesign
(use feishu-deck-h5 directly with a hand-authored deck.json).

## Preflight

1. Verify the `.pptx` exists. If only a name was given, `mdfind "<name>.pptx"`.
2. Python deps: `python-pptx`, `Pillow`, `PyMuPDF`. A venv at this sub-skill's
   root is used if present:
   ```bash
   python3 -m venv skills/feishu-deck-h5/pptx-to-html/.venv
   skills/feishu-deck-h5/pptx-to-html/.venv/bin/pip install python-pptx Pillow PyMuPDF
   ```
   (Or install on the system python; run.sh falls back to `python3`.)
3. The renderer is the **parent feishu-deck-h5** skill (auto-located as the
   grandparent dir of build_pptx.py, else `~/.claude/skills/feishu-deck-h5`).
   Override with `--renderer DIR`.
4. Raster fallback (`--raster` / `--full-raster`) additionally needs
   **LibreOffice** (`soffice`); without it those flags no-op with a warning.

## Invocation

**Output convention:** generated decks go to the MAIN feishu-deck-h5 skill's
**outer** `runs/` (`skills/feishu-deck-h5/runs/<deck-name>/`) — alongside every
other deck the main skill produces, NOT inside this sub-skill. (`runs/` is
gitignored repo-wide: regenerable, never committed.)

```bash
bash skills/feishu-deck-h5/pptx-to-html/assets/run.sh \
  <in.pptx>  skills/feishu-deck-h5/runs/<deck-name> \
  [--limit N]        # only first N slides
  [--raster]         # per-element raster fallback for charts/SmartArt/picture-fill
  [--full-raster]    # every slide = one full-bleed rasterized PNG (pixel-perfect)
  [--inline]         # single-file delivery (base64-inline) — avoid for image-heavy decks
  [--renderer DIR]   # feishu-deck-h5 skill root (default: parent skill, auto-located)
  [--title TEXT]
```

Preview: `bash skills/feishu-deck-h5/runs/<deck-name>/serve.sh` → localhost:8765

## Example / test fixture

`example/营销人的AI副驾/` is the kept reference deck — the real 60-page PowerPoint
this sub-skill was hardened against (every fix in FIXLOG was verified here). It is
NOT a runtime output; it stays in the sub-skill as the regression/demo fixture.
Committed lightweight (deck.json + montage_*.png + RESTORATION-REPORT.md +
index.html); the heavy regenerable `assets/` are gitignored.

## QA sweep

Screenshot every slide and build contact-sheet montages to scan for drift:

```bash
bash skills/feishu-deck-h5/pptx-to-html/assets/sweep.sh <out-dir> [N]   # writes <out-dir>/montage_*.png
```

Montage thumbnails downscale dark/detailed slides toward black — confirm any
"black" suspect against its full-res `<out-dir>/sweep/sNN.png` before treating
it as a defect.

## Pipeline files

| File | Role |
|---|---|
| `assets/build_pptx.py` | python-pptx → positioned HTML → deck.json → invoke renderer |
| `assets/run.sh` | bash entry point (venv-aware) |
| `assets/sweep.sh` | full-deck screenshot QA + montage |
| `assets/montage.py` | contact-sheet builder |

## Known limitations & the fix log

`FIXLOG.md` records every defect a real deck has exposed, its root cause, and
the **generalized** fix folded into `build_pptx.py` — the goal is that the next
PPT works first-try. When a new defect surfaces, fix it generically and append
to FIXLOG (don't hard-code per-deck workarounds). See `README.md` for the full
element-support table and the current lossy list.

**Hard-won gotcha (FIXLOG F3):** any value interpolated into an inline
`style="…"` attribute must use SINGLE quotes for font names — a nested double
quote truncates the attribute and silently drops every declaration after it
(color/weight), making light text render as the inherited dark default.
