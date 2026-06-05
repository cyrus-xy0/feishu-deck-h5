# deck.json 唯一中间层 —— PPTX / 老 HTML 统一设计 (SPEC-2026-06-03, 锁定版)

> 状态:**设计 spec 定稿(两轮原型实证 + 啃不动比例实测,待实现)**。
> 实测:11 份真实 deck / 224 页,结构性不可重建(live chart/SmartArt/OLE)= **0%** → 留空页极少。
> 原则:**一个中间层 = deck.json;PPTX 走结构化 JSON(无 HTML 坨、无图);老 HTML 走 raw(原码无损);一套编辑 = edit→sync→deck.json。**
> 取代早先含 page-replica/图 fallback 的版本(用户决定:**完全不要截图**)。

---

## 0. 已实证的地基(真工具 + 一次性原型)

- **raw round-trip**(真 render-deck.py + 真 sync-index-to-deck.py,/tmp):data.html 含定位内容,编辑文字+几何 → sync 回 deck.json **无损,二次 sync 零漂移**。
- **结构化 JSON round-trip**(一次性原型 /tmp/struct-proto):`elements[]` → 派生 HTML → 编辑 → 按 `data-el-id` 回写 JSON。**8/8 通过**:单run文字✓、几何(cqw→px)✓、多run保格式改字✓、删框✓、加框✓、重排✓、二次零漂移✓;**唯一有损 = 多run框被编辑抹平时 per-run 格式退单段(预期、可接受)**。

→ 两种回写都验过。**PPTX 用结构化、老 HTML 用 raw,都能无损 round-trip。**

---

## 1. 锁定原则

1. **deck.json = 唯一中间层 / 源真相**;index.html 纯派生(不存)。
2. **PPTX → 结构化 JSON**:新增 `canvas` layout,`data.elements[]` 描述定位元素(文字框 runs / 图 / 形状),**不存 HTML 坨**。AI 改这份干净 JSON 最顺。
3. **完全不要截图**。啃不动的页(原生图表/SmartArt/复杂矢量)→ **留空占位 + 报告页号** → 用户自己重做那几页。PPT 里**本来就是图片**的内容(照片/logo)仍作 `<img>`(那是原始内容,非截图)。
4. **老 HTML → `raw`**:保留真实 inner HTML(原码无损,反推最精准),不结构化(任意 HTML 强行结构化是有损猜测)。
5. **编辑统一**:edit index.html → `sync-index-to-deck.py` → deck.json → 重渲一致。manifest/localStorage 退役。

---

## 2. PPTX → 结构化 JSON(主路,唯一路;无图)

- `pptx-to-html`(改造为 parser 后端)读 .pptx OOXML,逐元素产出 **`canvas` slide 的 `elements[]`**:
  - 文字框 → `{type:text, x,y,w,h, runs:[{text,bold,color,size,...}], anchor, insets}`
  - 图片(原始嵌入)→ `{type:image, x,y,w,h, src}`(`src` 指 `input/` 资产)
  - 形状/渐变/线/表 → `{type:shape|line|table, ...}`(几何 + 样式字段)
- **几何统一 px-on-1920×1080**,渲染期转 cqw/cqh(容器查询自适应)。
- **啃不动判定**:原生 chart 对象 / SmartArt / 复杂 freeform / OLE → 不硬撑:产一个**占位 slide**(`{layout:canvas, data:{placeholder:true, source_page:N, reason:"chart/smartart"}}`,渲染成"本页待重做 · 源第 N 页")+ 汇总报告 `unreconstructed:[N,...]`。用户照报告自己重设计那几页。
- 诉求 = 尽可能还原、非完全一致、结构达标即可、AI 可在 elements 上重设计。

## 3. `canvas` layout schema(新增)

```jsonc
{ "layout": "canvas",
  "data": {
    "canvas_w": 1920, "canvas_h": 1080,
    "elements": [
      { "id": "t1", "type": "text", "x": .., "y": .., "w": .., "h": ..,
        "anchor": "top|middle|bottom", "insets": [l,r,t,b],
        "runs": [ { "text": "..", "bold": false, "color": "#..", "size": .. } ] },
      { "id": "img1", "type": "image", "x":.., "y":.., "w":.., "h":.., "src": "input/p1.jpg" },
      { "id": "s1", "type": "shape", "x":.., "y":.., "w":.., "h":.., "fill": "#..", "radius": .. }
    ],
    "placeholder": false, "source_page": 1
  } }
```
- 几何 px;render 转 cqw/cqh。每个 element 有稳定 `id`(回写锚点)。
- `custom_css` 仍走既有 slide-level 字段(scoped、co-located、sync 自动剥),不进 elements。

## 4. Round-trip(按 id,已验证)

- **render**:`elements[]` → 定位 `<div class="el" data-el-id>` / `<img data-el-id>`;文字 runs → `<span>`。
- **sync**:读每个 `[data-el-id]` → 文字(runs by span,无 span 则降单段)、几何(cqw→px)回写对应 element;HTML 缺的 id=删、多的 id=增;DOM 顺序=重排。
- **无损**:文字 / 几何 / 增删框 / 重排;二次零漂移。
- **有损边界(文档化)**:多-run 框被编辑抹平内联格式 → 该框退单段;啃不动页本就占位无内容。

## 5. 老 HTML → backfill deck.json(`raw`,code 反推,不截图)

- **自家老 HTML**(有 `data-slide-key`/`.slide`):抽每页 `.slide` inner → `raw` data.html,页 CSS → custom_css。**秒级**。
- **纯外来老 HTML**:按页/section 切 → 各自 inner 进 `raw`;识别得出标准形状可升 schema layout,否则留 raw。慢些、不确定,单独标注。
- **触发**:操作无-deck.json 老 deck 前**自动 backfill**,**一步转成 deck.json、转完即用,不维护双态过渡**(用户定:省得管中间态)。外来 HTML 这类谨慎处理。

## 6. 编辑契约(统一)
所有 slide(canvas / raw / schema)同一套:deck.json 渲 → 浏览器 E 编辑 → `sync-index-to-deck.py` 回写 deck.json → 重渲一致。无私有持久化。

## 7. 逐组件改动

| 组件 | 改动 | 量 |
|---|---|---|
| `deck-schema.json` | 新增 `canvas` layout + `data.elements[]` $def + 占位字段 | S |
| `templates/canvas.fragment.html` + render-deck `_enrich_canvas` | elements[]→定位 HTML(px→cqw/cqh)、占位页渲染 | M |
| `sync-index-to-deck.py` | 加 `canvas` 的按-id 回写(本原型逻辑产品化);加「**从零建 deck.json**」(老 HTML backfill) | M |
| `pptx-to-html/build_pptx.py` | 改为产 `canvas.elements[]`(非 HTML 坨、非图);啃不动→占位+报告;**删 raster 兜底**(--raster/--full-raster 退役) | M-L |
| `subskills/parser` | .pptx 单入口:调 build_pptx;无图;handoff 前 validate;`unreconstructed` 报告回传 | M |
| `validate-deck.py` | `canvas` 校验(元素几何/id 唯一/资产存在);占位页规则 | S |
| copy-assets / deck-cli paste / lift-slides | 扫 `elements[].src` 图资产、撞名拷贝改名 | S |
| `pptx-to-editable-html`(图那套) | **整条退役**(用户不要图);引擎里能复用的(OOXML 抽取)并进 build_pptx | S |
| 文档 | parser/SKILL.md + 主 SKILL.md:PPTX=结构化无图、啃不动留空报告、老 HTML backfill | M |

## 8. 增量迁移(每步可 ship + 可回退)
- **A 地基**(✅ 两原型已证):落 `sync` 按-id 回写 + 老 HTML「从零建」最小实现。
- **B canvas 渲染+校验**:schema + 模板 + render + validate;手写一份 canvas deck 能渲能编辑能 sync 回。
- **C PPTX→canvas**:build_pptx 产 elements[];真 .pptx 端到端;啃不动→占位+报页号;质量抽查。
- **D 老 HTML backfill**:自家/外来反推 + 操作前自动 backfill(一步到位)。
- **E 收口**:删图那套(pptx-editable 退役)、资产/lift 补齐、文档、校验闸。

## 9. 验收闸
- round-trip 字节一致(文字+几何+增删框+重排);二次 sync 零漂移。
- 多run抹平=唯一允许的有损,其它不许丢。
- 资产:`elements[].src` 图被 copy-assets/lift 搬到、撞名改名、0 个 404。
- 啃不动页:正确占位 + `unreconstructed` 报告列出页号。
- 保真抽查:结构化页 playwright 量真实 px,"尽可能还原"达标。
- 零回归:现有版式 + 236 测试全过。
- 老 HTML:无-deck.json 老 deck 操作前能一步建出可渲染可再编辑的 deck.json。

## 10. 已锁定决策(2026-06-03 用户拍板"按建议执行")
1. **占位页 = 纯文字**:"第 N 页待重做 · 源第 N 页",不带缩略图(最简单)。
2. **啃不动比例 = 已实测**:11 份真实 deck / **224 页,live chart/SmartArt/OLE = 0%**(图表/图形多为贴图 PICTURE→`<img>`,能渲)。→ "留空+报告"的页预计极少。注意:此指标只测"结构性不可重建";"能重建但版式稍走样"属可接受的"稍变"区,需真渲+视觉比对评估(留到里程碑 C 抽查)。
3. **老 HTML backfill = 无感自动**:操作无-deck.json 老 deck 时自动 backfill,不问。
4. **先一律 `canvas`**:标准形状暂不升 schema layout,后续需要再升(可换肤)。
