# pptx-to-html

把现有 **PowerPoint (.pptx)** 1:1 还原成可编辑的 HTML deck，渲染器用你本机的
**feishu-deck-h5**（`~/.claude/skills/feishu-deck-h5/deck-json/render-deck.py`）。

这是 [rollingai-decks](https://github.com/liukai1576/rollingai-decks) 里
`keynote-to-html` 技能的 **PowerPoint 版**——但不依赖 Keynote、不依赖 AppleScript：
`.pptx` 是开放的 OOXML，`python-pptx` 直接读出每个元素的精确坐标(EMU)、文字 run
(字体/字号/颜色/粗斜体)、图片、表格、分组，**跨平台**。

```
.pptx ──python-pptx──► deck.json (layout:"raw") ──render-deck.py──► index.html
        (本工具 build_pptx.py)                      (你的 feishu-deck-h5)
```

## 用法

```bash
bash run.sh <in.pptx> <out-dir> [选项]

  --inline         单文件交付（base64 内联全部 CSS/JS/图片）
  --limit N         只转前 N 页
  --raster          图表/SmartArt/渐变填充等无法结构化的元素 → 栅格裁图兜底
  --full-raster     每页整页栅格化成一张图（像素级保真、不可编辑）
  --renderer DIR    指定 feishu-deck-h5 skill 根目录（默认 ~/.claude/skills/feishu-deck-h5）
  --title TEXT      deck 标题
```

栅格兜底需要本机装 **LibreOffice**（`soffice`）；没有时自动跳过并告警。

预览：`bash <out-dir>/serve.sh` → http://localhost:8765/index.html
（← → 翻页、F 全屏、底部进度条，都是 feishu-deck-h5 自带的演示态。）

## 支持的元素 (v0.2)

| 元素 | 处理 |
|---|---|
| 背景 | slide→layout→master 纯色填充链；默认 #FFF |
| 图片 | `<img>` 原位，object-fit:fill 贴合 PPT 拉伸语义 |
| 文本框/占位符 | 真 `<div>/<span>`，逐 run 字体/字号/颜色/粗斜体下划线、段落对齐、垂直锚点、项目符号、**段内软换行 `<a:br>`**、字段（页码/日期） |
| 主题色 | **解析母版 theme `<a:clrScheme>`，tx/bg/dk/lt/accent1-6/hlink 全映射成真实 RGB**（文字色 & 渐变停靠点都用） |
| 自选图形 | 纯色填充→背景 div；**渐变填充→CSS linear-gradient（解析 `<a:gradFill>` 停靠点+角度）**；描边、圆角/椭圆 |
| 表格 | `<table>` + 单元格文字/填充/边框（无填充单元格安全处理） |
| 线条/连接符 | **SVG `<line>`，按 flipH/flipV 还原方向（含对角线）、线色、线宽** |
| 媒体/视频 | 取首帧海报图；无则 ▶ 占位（静态 deck 不可播放） |
| 分组 | 递归展开，按组的 chOff/chExt 变换还原子元素绝对坐标 |
| 旋转 | CSS transform: rotate() |

字体名在内联 style 里**强制单引号**（双引号会截断 `style=""` 属性，丢失颜色/粗细 —— 见 FIXLOG F3）。

## 已知有损 / 兜底

- 图表 / SmartArt / OLE 对象：不做结构解析；用 `--raster`（需 LibreOffice）栅格裁图兜底。
- 图片 / 图案填充的形状：CSS 无法复现 → `--raster` 兜底。
- 径向渐变 / 渐变明暗微调（lumMod/shade/tint/alpha）：仅支持线性渐变。
- 自由形状 FREEFORM：有填充按 bbox 矩形近似（丢自定义几何）；无填充跳过。
- 主题色 master `clrMap` 自定义映射：用默认 tx1→dk1 假设。
- 占位符字号继承：python-pptx 不解析 layout/master 继承链，run 无显式字号时回退默认。
- 图片裁剪 (a:srcRect)：暂未提取，整图贴入 bbox。
- 文本自动缩放 (autofit shrink)：按 PPT 写死字号渲染，溢出则自然换行（不模拟缩小）。

> 详细的「问题→修复」记录见 **FIXLOG.md**——每暴露一个缺陷就通用化修掉，目标是下一份 PPT 一次做对。

## 依赖

`./.venv` 里：`python-pptx`、`Pillow`、`PyMuPDF`。栅格兜底另需 LibreOffice。
