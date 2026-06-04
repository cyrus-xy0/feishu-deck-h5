---
name: pptx-to-html
description: |
  SUB-SKILL of feishu-deck-h5 (lives at feishu-deck-h5/pptx-to-html/, NOT an
  independently-registered skill). It is the .pptx import path into the deck
  system — invoked from feishu-deck-h5 when the user hands over a PowerPoint.

  Convert an existing PowerPoint (.pptx) into a STRUCTURED feishu-deck-h5
  `canvas` deck.json (data.elements[]) — natively, with no PowerPoint app, no
  Keynote, no AppleScript, no LibreOffice, NO SCREENSHOTS. Walks every slide
  with python-pptx and emits each as a list of absolutely-positioned, typed,
  id'd elements: text stays clean editable runs, images are the original
  embedded assets, shapes/gradients/lines carry appearance/SVG fields. This is
  the PPTX side of DECKJSON-UNIFIED-INTERMEDIATE-SPEC (§2/§3): one intermediate
  layer = deck.json, one edit loop = edit→sync→deck.json.

  Triggers: "把 PPT/PPTX 转成 HTML", "import pptx", ".pptx 转 deck",
  "把这份 PowerPoint 还原成网页/H5", or when the user hands over a .pptx path.

  Because .pptx is open OOXML, extraction is exact (EMU geometry) and
  cross-platform — it does NOT shell out to any GUI app.

  Per-slide algorithm:
    1. python-pptx walks every shape (recursing+flattening groups through their
       chOff/chExt transform) → each shape → an element dict.
    2. TEXT_BOX/PLACEHOLDER → {type:text, runs, anchor, insets}; PICTURE →
       {type:image, src:"input/.."}; AUTO_SHAPE/FREEFORM/LINE → {type:shape,
       kind/fill/gradient/border/radius/svg/style}.
    3. Theme colors resolved from the master's <a:clrScheme>.
    4. Each slide is emitted as a `layout:"canvas"` entry in deck.json.
    5. render-deck.py → positioned HTML (data-el-id, cqw/cqh); sync-index-to
       -deck.py round-trips edits back into elements[] by id.

  Un-reconstructable (live chart / SmartArt / OLE) → that slide becomes a
  placeholder ({placeholder:true, source_page:N}) and N is reported
  (`unreconstructed slides: [..]`). NO screenshot fallback — --raster /
  --full-raster are retired no-ops.

  Lossy / acceptable (best-effort 还原, NOT pixel-perfect):
    · autofit "shrink-to-fit" text is not simulated (authored size used).
    · only linear gradients; radial / lumMod-shade-tint approximated.
    · freeform custGeom: move/line/cubic/quad/close (arc etc. skipped).
    · image srcRect crop, complex table merges: approximated.
---

# pptx-to-html

## When to invoke

Trigger when the user has a `.pptx` and wants a structured, editable deck that:
  - Reconstructs the original PowerPoint as best-effort (尽可能还原, not pixel-perfect)
  - Has editable text + typed/positioned elements (deck.json, NOT pixels)
  - Carries feishu-deck-h5's present-mode chrome (←/→ nav, F fullscreen,
    progress bar, mobile scroll mode)

Do NOT use for: `.key` (use keynote-to-html), or a from-scratch redesign
(use feishu-deck-h5 directly with a hand-authored deck.json).

## 两条管线：选哪条

| 管线 | 入口 | 背景装饰 | 文字 | 依赖 | 何时用 |
|---|---|---|---|---|---|
| **代码重建** | `build_pptx.py` | 代码重建（渐变/glow/自由曲线**近似**，复杂装饰会失真） | 全结构化可编辑 | python-pptx | 想要**完全可编辑**、不在意装饰像素级、或不能装 LibreOffice |
| **混合（高保真）** | `build_pptx_hybrid.py` | **LibreOffice 渲染 → 像素级保真**（装饰/照片/图表原样） | 前景文字结构化可编辑，叠在无字背景上 | + **LibreOffice** + PyMuPDF | 想要**装饰像素级保真 + 前景文字可编辑**（推荐默认） |

**为什么混合管线更保真**：纯代码重建对「装饰性元素」（渐变、glow、阴影、自由曲线、艺术字、被裁剪的图片）永远近似失真；混合管线把这层交给 LibreOffice 真实渲染成无字背景图（零失真），只把**前景文字**抽出来结构化叠加（可编辑、纯色、真实字体、按渲染后的真实行 bbox 钉位）。装饰不可编辑（本就不需要逐像素编辑），前景文字可编辑——两全。详见 `references/` 与 `final/ARCHITECTURE-ANALYSIS-3layer.md`（如有）。

混合管线一条命令（**自动**：剥字→LibreOffice渲背景→栅格→抽原图→抽文字位置/字体/颜色→组装→渲染→**自包含打包**→前端增强 letterbox/nowrap/scaleX/懒加载）。产物**默认即交付级自包含**：框架 CSS/JS（及其内部 `url()` 引的 lark logo）自动拷进 `<deck>/assets/` 并把引用改写成相对路径，`bg/`、`input/` 本就是 deck 本地目录——整夹拷走 / 打包 / 发给别人都不断，无需再单独跑交付/copy-assets 步骤。打包器路径无关（判据=引用解析后落在技能内且不在 deck 内→框架资源），输出到 `runs/` 内外都能自包含。

```bash
skills/feishu-deck-h5/pptx-to-html/.venv/bin/python3 \
  skills/feishu-deck-h5/pptx-to-html/assets/build_pptx_hybrid.py \
  <in.pptx>  skills/feishu-deck-h5/runs/<deck-name> \
  [--renderer DIR] [--title TEXT] [--soffice /path/to/soffice]
```

依赖（混合管线特有，缺则报错并提示）：
- **LibreOffice**：`brew install --cask libreoffice`（headless 渲染改写过的 pptx；PowerPoint 对 python-pptx 改写过的文件导出会**静默失败**，故必须用 LibreOffice）。
- **PyMuPDF**：`<venv>/bin/pip install pymupdf`。
- **字体坑（务必记住，已根治）**：叠加文字的字体**必须从源 PPTX 的 `<a:latin>/<a:ea>` typeface 提取**（`deck_fonts()`），**绝不能用 PyMuPDF 从 LibreOffice 渲染里 `get_text` 读出的字体名**——LibreOffice 会把缺失字体替换成 Hiragino / **LiberationSerif（衬线！）** / Arial 等，喂给浏览器渲得又杂又怪。原字体若装在系统（如本机 `~/Library/Fonts/方正兰亭黑`）则字宽/对齐准；没装回退 PingFang。

混合管线的**已知边界**：① 背景装饰不可编辑（设计取舍）② 艺术化的图形标签（金字塔上中英混排）等复杂样式页，结构化文字有小的对齐瑕疵 ③ 图片全交给 LibreOffice 背景（个别异常裁剪的图可能比 PowerPoint 略压缩）。

## Preflight

1. Verify the `.pptx` exists. If only a name was given, `mdfind "<name>.pptx"`.
2. Python deps: `python-pptx`, `lxml`. A venv at this sub-skill's root is used
   if present:
   ```bash
   python3 -m venv skills/feishu-deck-h5/pptx-to-html/.venv
   skills/feishu-deck-h5/pptx-to-html/.venv/bin/pip install python-pptx
   ```
   (Or install on the system python; run.sh falls back to `python3`.)
   No LibreOffice / Pillow / PyMuPDF needed — rasterization is retired.
3. The renderer is the **parent feishu-deck-h5** skill (auto-located as the
   grandparent dir of build_pptx.py, else `~/.claude/skills/feishu-deck-h5`).
   Override with `--renderer DIR`.

## Invocation

**Output convention:** generated decks go to the MAIN feishu-deck-h5 skill's
**outer** `runs/` (`skills/feishu-deck-h5/runs/<deck-name>/`) — alongside every
other deck the main skill produces, NOT inside this sub-skill. (`runs/` is
gitignored repo-wide: regenerable, never committed.)

```bash
bash skills/feishu-deck-h5/pptx-to-html/assets/run.sh \
  <in.pptx>  skills/feishu-deck-h5/runs/<deck-name> \
  [--limit N]        # only first N slides
  [--no-render]      # emit deck.json + input/ assets only, skip HTML render
  [--inline]         # single-file delivery (base64-inline) — avoid for image-heavy decks
  [--renderer DIR]   # feishu-deck-h5 skill root (default: parent skill, auto-located)
  [--title TEXT]
  [--raster]         # ⚠ RETIRED no-op (no screenshots)
  [--full-raster]    # ⚠ RETIRED no-op (no screenshots)
```

The build self-validates (DeckJSON schema gate runs before render) and prints
`unreconstructed slides: [..]` — any listed page is a placeholder the user must
redo by hand. Image assets are extracted to `<out-dir>/input/` and referenced
as `elements[].src = "input/<file>"` (real scannable paths for copy-assets/lift).

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
| `assets/build_pptx.py` | python-pptx → positioned HTML → deck.json → invoke renderer（代码重建管线） |
| `assets/build_pptx_hybrid.py` | **混合高保真管线**：LibreOffice 无字背景 + 结构化可编辑文字叠加（一条命令编排，需 LibreOffice + PyMuPDF） |
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
