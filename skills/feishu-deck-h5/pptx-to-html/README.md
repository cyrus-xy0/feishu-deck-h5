# pptx-to-html

把现有 **PowerPoint (.pptx)** **尽可能还原**成一份**结构化的** feishu-deck-h5
`canvas` deck.json，渲染器用你本机的
**feishu-deck-h5**（`~/.claude/skills/feishu-deck-h5/deck-json/render-deck.py`）。

`.pptx` 是开放的 OOXML，`python-pptx` 直接读出每个元素的精确坐标(EMU)、文字 run
(字体/字号/颜色/粗斜体)、图片、分组，**跨平台**——不依赖 Keynote、AppleScript、
也**不依赖 LibreOffice / 不截图**。

每页输出成一个 `layout:"canvas"` slide：一串**定位 + 类型 + 带 id** 的元素
（`data.elements[]`），**不是 HTML 坨、不是截图**。文字保持干净 runs（可编辑），
图片是原始嵌入资产，形状带 appearance 字段。渲染器把 elements[] 转成定位 HTML，
`sync-index-to-deck.py` 再按 id 把编辑无损写回 elements[]。这是
DECKJSON-UNIFIED-INTERMEDIATE-SPEC（§2/§3）的 PPTX 侧。

```
.pptx ──python-pptx──► deck.json (layout:"canvas", elements[]) ──render-deck.py──► index.html
        (本工具 build_pptx.py)                                    (你的 feishu-deck-h5)
```

## 用法

```bash
bash run.sh <in.pptx> <out-dir> [选项]

  --inline          单文件交付（base64 内联全部 CSS/JS/图片）
  --limit N         只转前 N 页
  --no-render       只产 deck.json + 资产，跳过 HTML 渲染
  --renderer DIR    指定 feishu-deck-h5 skill 根目录（默认 ~/.claude/skills/feishu-deck-h5）
  --title TEXT      deck 标题
  --raster          ⚠ 已退役（no-op）：不再截图
  --full-raster     ⚠ 已退役（no-op）：不再整页栅格化
```

> **不要截图**：旧的整页 / 按元素栅格兜底已**退役**。嵌入的 PICTURE 仍作 image
> 元素（那是原始内容）；啃不动的页留占位 + 报告页号，用户自己重做那几页。

预览：`bash <out-dir>/serve.sh` → http://localhost:8765/index.html
（← → 翻页、F 全屏、底部进度条，都是 feishu-deck-h5 自带的演示态。）

## 元素映射（每个 → `{id, type, x, y, w, h, ...}`，px on 1920×1080）

| PPT 元素 | canvas element |
|---|---|
| TEXT_BOX / PLACEHOLDER（含文字） | `{type:"text", runs:[{text,bold,color,size}], anchor, insets}` —— **干净结构化、可编辑** |
| PICTURE | `{type:"image", src:"input/<file>"}`（blob 抽到 `input/`，真实可扫描路径） |
| MEDIA（视频） | 取海报图 → `{type:"image", src:..}`，无则海报占位 shape |
| AUTO_SHAPE | `{type:"shape", kind, fill\|gradient, border, radius, style}` |
| FREEFORM (custGeom) / LINE | `{type:"shape", svg:".."}` —— custGeom/line 解析成内联 SVG path（normalized 0..100 box，preserveAspectRatio:none） |
| 表格 | 拍平成定位的单元格 shape + 单元格 text（canvas 无 table 类型） |
| GROUP | **展开**：按组 chOff/chExt 变换把子元素绝对坐标算好，作**顶层元素**逐个发出（无 group 包裹） |
| 旋转 | shape 走 `style:"transform:rotate(..)"` 逃生口（text/image 保持干净） |
| 背景 | slide→layout→master 纯色链作一块铺满的 backing shape；母版/版式 `<p:bg>` 贴图作铺满 image |
| 主题色 | 解析母版 theme `<a:clrScheme>`，tx/bg/dk/lt/accent1-6/hlink 全映射真实 RGB（文字色 & 渐变停靠点都用） |

text / image **只带干净结构化字段**；只有 shape 用 appearance/svg/style。每个
element 都有稳定 `id`（`e{slide}_{n}`），是 sync 的回写锚点。

## 啃不动 → 占位 + 报告

整页含 **live chart（`has_chart`）/ SmartArt（diagram 命名空间）/ OLE 对象**
→ 该页发成 `{layout:"canvas", data:{placeholder:true, source_page:N, elements:[]}}`，
收集页号；结束打印 `unreconstructed slides: [N, ...]`（无则空表）。实测 11 份真实
deck / 224 页，结构性不可重建 = **0%**（图表多为贴图 PICTURE，能渲）。

## 还原质量（诚实说明：尽可能还原，非像素级）

- 渐变只支持线性（`<a:gradFill>` 停靠点 + 角度）；径向 / lumMod/shade/tint/alpha 微调不还原。
- roundRect 圆角按短边 ~16% 近似（PPT adj 未逐一解析）。
- FREEFORM custGeom 支持 move/line/cubic/quad/close；arc 等少见命令跳过。
- 图片裁剪 (a:srcRect) 未提取，整图贴入 bbox；autofit shrink 不模拟。
- 占位符字号继承：run 无显式字号时回退默认（python-pptx 不解析继承链）。
- 表格拍平成定位单元格，复杂合并/斜线表头不还原。

> 详细的「问题→修复」记录见 **FIXLOG.md**。

## 依赖

`./.venv` 里：`python-pptx`、`lxml`（已不需要 Pillow / PyMuPDF / LibreOffice）。
