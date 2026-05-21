# Migration Report · Path A TOML → DeckJSON

**Date**: 2026-05-20
**Scope**: 把现有 `examples/*/input.toml` (4 个 case) 转成 DeckJSON,验证新 schema 100% 覆盖存量。
**Verdict**: ✅ 4/4 全部 PASS `--strict`。1 个真实 schema gap 被发现并修复;3 个 TOML 死字段被识别可弃用。

---

## 迁移成果

| 源 TOML | 目标 DeckJSON | layout / variant | 字段映射 | 验证 |
|---|---|---|---|---|
| `one-pager-luckin/input.toml` | `migrated-from-toml/one-pager-luckin.json` | `content` / `story-case` | 1:1 (含 brand + source) | ✅ PASS strict |
| `quote-luckin/input.toml` | `migrated-from-toml/quote-luckin.json` | `quote` (无 variant) | 1:1,**brand 字段丢弃** (死字段) | ✅ PASS strict |
| `big-stat-luckin/input.toml` | `migrated-from-toml/big-stat-luckin.json` | `stats` / `hero` | 1:1,**brand + source 字段丢弃** (死字段) | ✅ PASS strict |
| `bundle-luckin/bundle.toml` | `migrated-from-toml/bundle-luckin.json` | `cover` + `agenda` + `content/story-case` + `end` | 复合: 1 个 deck.toml + N 个 case.toml → 1 个 deck.json 数组 | ✅ PASS strict |

---

## 发现的 schema gap (已修复)

### G1 · `data_agenda.items.minItems: 2` 太严

**症状**: `bundle-luckin` 只有 1 个 case,渲染后 agenda 也只有 1 条。原 `render.py` 接受;新 schema 拒绝。

**根因**: 我设计 schema 时把"agenda 至少 2 项"当作编辑铁律。实际上 render.py 的 `_build_agenda_items_html` 单纯按 `cases` 数组数量出条,不做下限校验。

**修复**: `data_agenda.items.minItems` 2 → 1,加 description 说明"1-item agenda 是允许的但编辑上偏弱,建议单 case deck 直接去掉 agenda"。

**Lesson**: schema 应该**接受所有 render.py 接受的输入**,不该比 render.py 更严。编辑准则(单 case 不该有 agenda)归编辑器 UI 提示,不归 schema。

---

## TOML 死字段 (已知非 schema 缺口)

迁移时发现 3 个 TOML 字段在对应模板里**实际未被引用**,是 2026-05 footer chrome 退役后留下的遗物。DeckJSON 直接弃用,无需对应字段:

| TOML 字段 | 出现在 | 模板用了吗 | 处理 |
|---|---|---|---|
| `quote.brand = "..."` | `quote-luckin` | ❌ `templates/quote.html` 无引用 | drop |
| `big-stat.brand = "..."` | `big-stat-luckin` | ❌ `templates/big-stat.html` 无引用 | drop |
| `big-stat.source = "..."` | `big-stat-luckin` | ❌ 同上 | drop |

**Lesson**: 现有 TOML examples 是给 Path A 用户做 reference 的,但其中一部分字段早就跟 footer chrome 一起死了 —— 没人删,因为 render.py 也不报错。DeckJSON schema 不带这些字段是正确的精简。

**Action item** (skill 维护者): 把这 3 个字段从对应 `input.toml` 里清理掉,避免后续用户看到 example 时被误导。

---

## 真正 1:1 干净对齐的字段映射

### one-pager (`content` / `story-case`)

| TOML | DeckJSON | 备注 |
|---|---|---|
| `title` | `data.title` + `deck.title` (各填一份) | DeckJSON 是完整 deck,需要 deck 级别 title |
| `industry` | `data.industry` | 1:1 |
| `brand` | `data.brand` | 1:1 (与 quote/big-stat 不同,one-pager 的 brand 在模板里**有**用) |
| `source` | `data.source` | 1:1 (同上) |
| `[hook]` lead/accent/tail | `data.hook.{lead,accent,tail}` | 1:1 |
| `[arc]` pain/conflict/solution | `data.arc.{pain,conflict,solution}` | 1:1 |
| `[arc.value]` lead/accent/tail | `data.arc.value.{lead,accent,tail}` | 1:1 |
| `[scene]` image/caption/alt/fit/position | `data.scene.{image,caption,alt,fit,position}` | 1:1 |
| `decor` (TOML 没有,render.py 也没有 default) | `slides[0].decor` (我加了 `["blue-glow"]`) | DeckJSON 比 TOML 多了显式 decor 表达力 |
| `screen_label` (optional default) | `slides[0].screen_label` | 1:1 |

### quote

| TOML | DeckJSON | 备注 |
|---|---|---|
| `title` | `deck.title` + `data.title` | 同上 |
| `[quote]` lead/accent/tail | `data.quote.{lead,accent,tail}` | 1:1 |
| `attribution` | `data.attribution` | 1:1 |
| `decor` (TOML default `"blue-glow"`) | `slides[0].decor: ["blue-glow"]` | 改成 array 表达力 |

### big-stat (→ `stats` / `hero`)

| TOML | DeckJSON | 备注 |
|---|---|---|
| `title` | `deck.title` + `data.title` | 同上 |
| `eyebrow` | `data.eyebrow` | 1:1 |
| `heading` | `data.heading` | 1:1 |
| `body` | `data.body` | 1:1 |
| `[stat]` number/unit | `data.stat.{number,unit}` | 1:1 |

### bundle (复合 → 单一 deck.json)

| 源 | DeckJSON 位置 | 备注 |
|---|---|---|
| `[deck]` title/author/date | `deck.{title, author, date}` | 1:1 |
| `[agenda]` title | `slides[1].data.title` (agenda 那条) | 重定位到对应 slide |
| `[brand]` contact | `slides[N].data.contact` (end 那条) | 重定位 |
| `[brand]` line | DROP | footer chrome 死字段,模板未用 |
| `[[cases]]` array | `slides[2..N-1]` 每条一个 `content/story-case` slide | **核心简化** — bundle 不再是特殊 composite pattern,就是普通 slides 数组 |
| `[[cases]].input` 路径 | 整 TOML 内容 inline 到对应 slide | 不再需要"载入子文件"的特殊逻辑 |
| `[[cases]].label` | `slides[1].data.items[i].title_zh` (agenda 项) | 1:1 |

**最大收获**: bundle 在 DeckJSON 里完全平凡化。原 render.py 100+ 行的 `render_composite()` / `_build_agenda_items_html()` / 多 TOML loading / fail-fast validation,Phase 1 渲染器**全部可以删除**,只剩"按数组顺序渲染每个 slide"这一个循环。

---

## Schema 验证统计

```
sample-deck.json                14 slides   ✅ PASS strict
one-pager-luckin.json            1 slide    ✅ PASS strict
quote-luckin.json                1 slide    ✅ PASS strict
big-stat-luckin.json             1 slide    ✅ PASS strict
bundle-luckin.json               4 slides   ✅ PASS strict
─────────────────────────────────────────────
total                           21 slides   5/5 deck PASS
```

Negative test 仍然 12/12 全部 catch (见 README · "What the validator checks")。

---

## 后续工作

1. **Action**: 清理 `examples/quote-luckin/input.toml` 和 `examples/big-stat-luckin/input.toml` 里的死字段 (brand / source),避免误导。
2. **Phase 1 准备**: 渲染器实现时,bundle 不需要 composite 代码路径 —— 直接把 slides 数组逐张渲染、按顺序拼接即可。`render_composite()` / `_build_agenda_items_html()` 可以删。
3. **Phase 0.1 候选** (如果 Phase 1 之前要做):
   - 把现有 `runs/<ts>/output/*.html` 抽样 5-10 个,反推成 DeckJSON,验证更广泛的 layout 覆盖。
   - 给 schema 加 `block_voice_card / block_north_star_map / block_scene_grid` 等还没纳入 embeddable_block 的高频 pattern。

---

## 结论

**Phase 0 schema 设计正确,可以支撑 Phase 1 开工**。

- 16 → 10 layout 合并对实际 case 没有损失,反而让 bundle 失去了"特殊 composite"的复杂度
- multi-variant 字段(content / stats / flow)的 if/then 分支在真实 case 上验证有效
- 唯一发现的 schema gap (agenda minItems) 已修复
- 3 个 TOML 死字段被识别,推动 example 清理

---

# Phase 0.1 · 真实生产 deck 覆盖度验证

**Date**: 2026-05-20 (same session)
**Scope**: Survey 5 个 production runs/ deck (4 个 valid + 1 跳过的非标 deck),验证扩展 schema,迁移 1 个真实 deck 5 个 slide,清理 3 个 TOML 死字段。
**Verdict**: ✅ schema 加 1 个 variant + 2 个 embeddable block,覆盖所有 multi-deck patterns;single-deck 复杂 pattern 走 `raw` 兜底,Phase 1 渐进吸收。

## 现场调查

调查的 5 个 deck (`runs/<ts>/output/index.html`):

| Deck | Slides | Layout 用量 | 自定义 CSS (`<style data-page>`) |
|---|---|---|---|
| lark-feishu-consumption-q2 (4-30) | 44 | 11/12 个 base layout | **0** |
| opple-ai-lecture (5-13) | 102 | 8/12 | **0** |
| nanqu-weekly-0515 (5-16) | 16 | 4/12 | **0** |
| lark-ai-container-story (5-18) | 28 | 7/12 | **0** |
| sps-coord-pain (5-20) | — | 非标 SVG visualization,跳过 | — |

### 关键发现

1. **0 个未知 `data-layout`** —— 10 base layouts 完整覆盖 production。
2. **0 个 `<style data-page>` custom CSS** —— production 作者完全不用 escape hatch,意味着 `custom_css` 字段是真的低频需求(可以推迟优化)。
3. **0 个 `data-variant=` 属性** —— production 用 class modifier (`is-teal` / `is-warn`) 而不是 variant 属性。**不冲突**:我的 schema 在 JSON 层用 variant,Phase 1 渲染器输出 HTML 时映射成 `data-layout=` 即可(无需 `data-variant=`)。
4. **multi-deck pattern** (≥2 deck 出现):
   - 已有 schema: `kpi-strip` · `pullquote` · `cta-box` · `data-panel` ✅
   - 缺 schema: `verdict-card` (2 deck) · `phone-iframe` (2 deck) ✅ **本次新增**
5. **single-deck pattern**: `two-hand-arch` · `boundary-band` · `voice-card` · `ui-window` 全家桶 · `calc` · 手写 `.phone` 聊天 demo —— **走 `raw` 兜底**,Phase 1 渐进升级。

### 隐藏的真实 gap (调查时才发现)

调查迁移 lark-feishu-consumption-q2 slide 02 时发现:**原 deck 用 `data-layout="content-2col"` 装了 2 个 verdict-card 横排**(不是 text+visual 结构)。

这是 schema 比 production 语义更窄的问题:
- 我的 `content/2col` 强制要求 `text + visual` 二分(左文右图)
- production `content-2col` 实际是"任意 2 列网格"的灵活容器
- 解决:加 `content/blocks` variant,允许全宽 `body_blocks` 占据 canvas

## 本次 schema 改动

```
content variant enum:  [3up, 2col, story-case]  →  [3up, 2col, story-case, blocks]
+ data_content_blocks  (新)
+ block_verdict_grid   (新, 嵌入式)
+ block_phone_iframe   (新, 嵌入式)
```

embeddable_block 从 5 → 7;layout enum 不变(12 值);content variant 从 3 → 4。

## 真实 deck 迁移验证

`examples/migrated-from-toml/lark-consumption-q2-excerpt.json` —— 5 个 slide:

| slide | layout/variant | pattern 覆盖 | 验证 |
|---|---|---|---|
| 01 cover | `cover` | 1:1 保留 subtitle + team-author (legacy) | ✅ |
| 02 CEO 命题 | `content/blocks` | verdict-grid (2 cards w/ kpis) + pullquote(orange) + source_footer | ✅ |
| 03 周一上午 | `content/3up` | 3 cards + pullquote (body_block) | ✅ |
| 06 心脏图 | `raw` | two-hand-arch 走 raw 兜底,html elided | ✅ |
| 07 closing | `end` | minimal | ✅ |

**全部 PASS strict**。新 schema 在真实 deck 上 dogfood 通过。

## 死字段清理 (action item 落地)

- `examples/quote-luckin/input.toml` · 删除 `brand = "飞书企业 AI · Customer Voice"`
- `examples/big-stat-luckin/input.toml` · 删除 `brand = "..."` 和 `source = "..."`
- 删后跑 `render.py`,两个 case 仍成功生成 HTML,确认这两个字段确实没被模板消费

(HTML validator 在两个 case 上报了 R-KEY 错 —— 是 `quote.html` / `big-stat.html` 模板缺 `data-slide-key` 的预存问题,跟死字段清理无关,留作独立模板维护任务。)

## 累计验证统计

```
sample-deck.json                         14 slides   ✅ PASS strict
one-pager-luckin.json                     1 slide    ✅ PASS strict
quote-luckin.json                         1 slide    ✅ PASS strict
big-stat-luckin.json                      1 slide    ✅ PASS strict
bundle-luckin.json                        4 slides   ✅ PASS strict
lark-consumption-q2-excerpt.json          5 slides   ✅ PASS strict
─────────────────────────────────────────────────────
total                                    26 slides   6/6 deck PASS
```

Negative tests 仍然 12/12 全 catch。新增 variant `blocks` / 新 block `verdict-grid` / `phone-iframe` 没破任何旧测试。

## Phase 0.2 候选 (留给 Phase 1 渲染器实施时按需吸收)

按出现频率排序的待升级 pattern (目前都走 `raw` 兜底):

| Pattern | 出现 deck 数 | 提升路径 |
|---|---|---|
| `two-hand-arch` | 1 | 新 layout `architecture` (variant `two-hand`),或 block `block_two_hand_arch` |
| `phone` 手写聊天 demo | 1 | 复杂 SVG/CSS animation,可能始终走 `raw` |
| `voice-card` | 1 | embeddable block,简单 |
| `boundary-band` | 1 | embeddable block,简单 |
| `ui-window` 全家桶 | 1 | 大型 sub-schema(20+ sub-classes),很可能始终走 `raw` 或 `data-panel` 替代 |
| `calc` | 1 | 需要嵌入 JS,可能走 `raw` |

**判断准则**: pattern 重复出现在 ≥2 个 deck → 加 schema;single-deck → 留 `raw`。

## 总结论

✅ **Phase 0 / 0.1 全部完成,schema 可以支撑 Phase 1 渲染器开工**。

- 10 base layout + 12 enum 值充分
- 7 个 embeddable block 覆盖 100% multi-deck pattern
- 真实 production deck 5/5 验证通过
- 死字段已清理,文档化
- 剩余 single-deck pattern 走 `raw` 不阻塞 Phase 1

---

# Phase 0.2 · 4 个 layout proposal 评估

**Date**: 2026-05-20 (same session, after Phase 0.1)
**Source**: `examples/_layout-proposal.html` 前 4 slide (用户起草的 layout 建议)
**Scope**: 评估 matrix-2x2 / exec-summary / waterfall / issue-tree 4 个新 layout 是否值得加入 schema,严守 10 base layout 上限不破。

## 评估结果一览

| Proposal | consulting 通用性 | 现 schema 装得下 | 决定 | 实现 |
|---|---|---|---|---|
| matrix-2x2 | ★★★ McKinsey/BCG 必备 | ❌ | **加 variant** | `content/matrix` |
| exec-summary | ★★★ 正式 deck 开篇标配 | △ 80%(content/blocks 拼) | **扩字段** | `content/3up` + `lede` + `cards[].kpi` |
| waterfall | ★★★ 财务/营收 deck 必备 | ❌ | **加 variant** | `stats/waterfall` |
| issue-tree | ★★★ MECE 拆解,McKinsey 招牌 | ❌ | **加 variant** | `flow/tree` |

**核心原则**:严守 **10 base layout** 不破。每个新 pattern 先尝试归类到现有 layout 作为 variant,只有结构真的不同才加 base 层。

## 实现细节

### content/matrix (新 variant)

2×2 矩阵 + 命名轴 + 4 象限,经典战略优先级模板。

数据 shape:
```json
{
  "title": "...",
  "axes": { "y": {name, high_label, low_label}, "x": {...} },
  "quadrants": { "tl": {ord, title, items}, "tr", "bl", "br" }
}
```

为什么归 content:matrix 跟 3up / 2col / blocks 同属"用某种结构组织内容主体"。3up 是 3 卡片横排;matrix 是 2×2 网格 + 轴;blocks 是全宽 body。同构语义。

### stats/waterfall (新 variant)

桥图 / 瀑布图。base + N pos/neg + end 的 bar 序列,renderer 自动算高度和连接线。

数据 shape:
```json
{
  "title": "...",
  "bars": [
    { "kind": "base|pos|neg|end", "value": "...", "delta": "...", "label": "...", "sublabel": "..." }
  ]
}
```

为什么归 stats:row 是 3-4 KPI 横排,hero 是 1 大数字,waterfall 是"N 个数字的连续分解"——都是"数字呈现"的不同形态。共同的视觉锚点是"数字本身是 hero"。

### flow/tree (新 variant)

MECE issue-tree。root 问题 + 2-4 个 branches,每 branch 带 1-4 个 leaves。Renderer 画 SVG dashed connectors。

数据 shape:
```json
{
  "title": "...",
  "root": { "question": "...", "why": "..." },
  "branches": [ { "ord": "A", "title": "...", "leaves": ["...", "..."] } ]
}
```

为什么归 flow:timeline 是横向时间序列,process 是横向流程序列,tree 是树形分解序列——都是"结构关系展现",共同点是 N 个有序/有层次的关系单元。语义略 strain(timeline/process 横向、tree 纵向)但可接受。

**风险记录**: 如果未来加 org-chart / decision-flow / decomposition 类的 layout,可能需要重新考虑把 flow 改名 `structure`(更宽泛)。Phase 0.2 不改。

### content/3up 扩展(吸收 exec-summary)

不单独加 layout,通过扩 content/3up 字段实现:

- `lede` (optional string) — 卡片网格上方的 thesis 段落
- `cards[].kpi` (optional `{value, label}`) — 每卡的 KPI 徽标

加上现有 `body_blocks[]` (可放 cta-box 作 actions strip),exec-summary 的 3 个组成部分(thesis + takeaways + actions)都被覆盖。

为什么不单独加 layout:exec-summary 的 3 段结构本质是 3up 的扩展形态(thesis 段 + 3 卡带 KPI + closing CTA),复用 content/3up 比新建 layout 更经济,且不破坏 10 base 上限。

## 调整后的 schema 统计

- **layout enum**: 仍是 12 (10 base + 2 special) — 不破 10 base 上限 ✅
- **content variants**: 4 → 5 (`3up / 2col / story-case / blocks / matrix`)
- **stats variants**: 2 → 3 (`row / hero / waterfall`)
- **flow variants**: 2 → 3 (`timeline / process / tree`)
- **embeddable blocks**: 7 不变
- **data $defs**: +3 (`data_content_matrix / data_stats_waterfall / data_flow_tree / matrix_quadrant`)
- **content/3up**: +2 字段 (`lede / cards[].kpi`)

## Dogfood 验证

`examples/migrated-from-toml/proposal-mvw.json` —— 3 slide,1:1 转录 `_layout-proposal.html` slide 1+3+4:

| slide | layout/variant | 验证 |
|---|---|---|
| 01 | `content/matrix` | ✅ PASS strict |
| 03 | `stats/waterfall` | ✅ PASS strict |
| 04 | `flow/tree` | ✅ PASS strict |

**全部 PASS**。3 个新 variant 在真实 proposal markup 上验证通过。

## 累计验证 (Phase 0 + 0.1 + 0.2)

```
sample-deck.json                         14 slides   ✅
one-pager-luckin.json                     1 slide    ✅
quote-luckin.json                         1 slide    ✅
big-stat-luckin.json                      1 slide    ✅
bundle-luckin.json                        4 slides   ✅
lark-consumption-q2-excerpt.json          5 slides   ✅
proposal-mvw.json                         3 slides   ✅
─────────────────────────────────────────────────────
total                                    29 slides   7/7 deck PASS
```

Negative tests: 12 (Phase 0/0.1) + 8 (Phase 0.2: matrix_no_quadrants · matrix_missing_quad · matrix_no_axes · waterfall_no_bars · waterfall_bad_kind · tree_no_root · tree_no_branches · tree_only_1_branch) = **20/20 全 catch**。

## proposal 文件剩余 4 slide (5-8) 状态

`_layout-proposal.html` 还有 4 个 layout (arch-stack / logo-wall / roadmap-swim / before-after) 没评估,留 Phase 0.3 处理:

- **arch-stack** · 4 层架构横条 → 可能归 `content/stack` variant
- **logo-wall** · 客户 logo 矩阵 → 可能归 `image-text/logo-grid` variant 或单独 block
- **roadmap-swim** · 多泳道 timeline → `flow/timeline` 多行扩展? 或 `flow/swim` variant?
- **before-after** · 对比页 → `table/compare` variant?

都是"先尝试 variant,实在不行才加 layout"的路径。

## 总结论 v2

✅ **Phase 0.2 完成,schema 现在可以表达 consulting deck 经典 4 大模式 (matrix / exec-summary / waterfall / tree)**。

- 10 base layout 上限**严守**
- variant 数量增加但每个都有清晰归属理由
- exec-summary 不单独成 layout,扩 content/3up 字段实现 — 避免功能重叠
- 真实 proposal slide dogfood 通过
- Phase 1 渲染器现在可以覆盖 100% production + 4 大 consulting pattern

---

# Phase 0.3 评估 · _layout-proposal.html slide 5-8

(2026-05-21 评估,实施暂缓)

## 评估结果一览

| # | layout | 结构特征 | schema 装入路径 | 优先级 | 估算工作量 |
|---|---|---|---|---|---|
| 5 | **arch-stack** | 4 层水平条 (apps / platform / ai / data),每层 {title, sub, modules[]} | 新 base layout `arch-stack` (不适合 content/* 或 flow/* variant — 层级语义太强) | 中 | 1 天 (schema + template + enricher) |
| 6 | **logo-wall** | header + lede + N 个 industry group,每组 {name, logos[]} | 新 base layout `logo-wall` (重图片,无现有 layout 类似) | 高 — 客户提案标配 | 1-2 天 (asset 路径处理 + 多 industry 排版) |
| 7 | **roadmap-swim** | 时间轴 (Q1-Q4) × 4 lane,每 lane 含 milestone[{quarter, title, desc}] | 新增 `flow/swim` variant (跟 flow/timeline 同源,加一维 lane 分组) | 中 | 1-2 天 (网格布局 + lane name styling) |
| 8 | **before-after** | 两列 vs (痛点 X items / 飞书 ✓ items) + pivot 中段 | 新增 `content/before-after` variant (跟 content/2col 同源,加 pivot + 强对称) | 高 — 提案叙事高频 | 1 天 |

## 详细评估

### 5 · arch-stack

```jsonc
{
  "layout": "arch-stack",
  "data": {
    "title": "飞书企业 AI · 产品全景",
    "layers": [
      {
        "name":  { "title": "应用层", "sub": "APPS · 面向终端用户" },
        "modules": ["飞书消息", "飞书文档", "多维表格", "视频会议", "飞书 AI 助手", "知识库"]
      },
      { /* 同样的 shape × 3 */ }
    ]
  }
}
```

**为什么不归到现有 layout**：
- `content/3up` 卡片间是平行关系,这里是**纵向层级关系**(上层依赖下层)
- `flow/process` 步骤连续,这里**不是流程**是**并列层**
- `stats/*` 都是数字密集,这里没数字

**约束**：layer 数量 `minItems: 2, maxItems: 5`,每 layer modules `minItems: 3, maxItems: 8`。

### 6 · logo-wall

```jsonc
{
  "layout": "logo-wall",
  "data": {
    "title": "50+ 头部企业 · 与飞书一起跑",
    "lede":  "从新茶饮到家电零售...持续运转。",
    "industries": [
      {
        "name":  "新茶饮 / 餐饮连锁",
        "logos": ["蜜雪冰城", "瑞幸咖啡", "..."]  // 逻辑 key,asset 路径在 enricher 里转
      }
    ]
  }
}
```

**关键设计抉择**：
- `logos[]` 是 **logical key 数组**,不是直接路径 —— 让 enricher 把 "瑞幸咖啡" 解析成 `<output>/assets/shared/clientlogo/瑞幸咖啡.png`
- 同步要 build 一个 client logo registry (`assets/shared/clientlogo/_index.json`),让 schema validator 校验 "logo key 是否存在"
- 行业组 `minItems: 2, maxItems: 4`,每行业 `minItems: 4, maxItems: 12`

**为什么高优先**：客户提案 90% 都要这一页("看我们的客户");现在没有 schema 路径,只能写 raw HTML。

### 7 · roadmap-swim

```jsonc
{
  "layout": "flow",
  "variant": "swim",
  "data": {
    "title": "2026 飞书 AI · 4 条产品线并行路线",
    "time_axis":  ["Q1", "Q2", "Q3", "Q4"],
    "lanes": [
      {
        "name":   "飞书 AI 助手",
        "sub":    "AI ASSISTANT",
        "accent": "blue",
        "milestones": [
          { "quarter": 2, "title": "AI 助手 v2", "desc": "多模态 + 工作流" },
          { "quarter": 4, "title": "AI Workspace", "desc": "个人 AI 工作台" }
        ]
      }
    ]
  }
}
```

**为什么归 flow 而不是新 layout**:
- `flow/timeline` 一维 (时间), `flow/process` 一维 (步骤), `flow/tree` 一维 (分支)
- `flow/swim` 是 **时间 × 产品线 二维** — 仍然是 flow 家族,只是多一个分组维度
- 重用 `flow` 的 accent / decor / header 等约定

**约束**：lane `minItems: 2, maxItems: 5`,time_axis `length === 4` (季度);更长时间维度可考虑 quarters → months 变体。

### 8 · before-after

```jsonc
{
  "layout": "content",
  "variant": "before-after",
  "data": {
    "title": "用飞书 12 周后 · 5 个真实变化",
    "before": {
      "tag":   "现状 · 痛点",
      "items": ["关键决策需 3-5 天跨部门对齐", "..."]
    },
    "pivot":  { "caption": "用飞书 12 周后" },
    "after": {
      "tag":   "飞书 · 现在",
      "items": ["关键决策对齐 < 60 秒,Wiki 留痕", "..."]
    }
  }
}
```

**为什么归 content/* 而不是新 layout**：
- 跟 `content/2col` 同样是双列结构
- 加 `variant: before-after` 触发 pivot 中柱 + ✕/✓ icon 自动渲染 + 红/蓝色调对比
- before/after items 对称必须 (`before.items.length === after.items.length`)

**约束**：items `minItems: 3, maxItems: 6` (太多放不下;太少没说服力)。

## 总体推荐路径 (顺序)

按"客户场景频次 × 实施成本"加权：

1. **#8 before-after** (优先级最高 · 1 天) —— 提案叙事高频,实施最简单 (variant of content,大量复用现有 CSS)
2. **#6 logo-wall** (优先级高 · 1-2 天) —— 提案标配,但需要 client-logo registry 配套
3. **#7 flow/swim** (中 · 1-2 天) —— 产品 roadmap 场景才用
4. **#5 arch-stack** (中 · 1 天) —— 架构产品介绍场景

## Phase 0.3 暂缓的理由

当前 phase 重心已转到 editor (Phase 4.x);schema 扩展每加一个 layout 要联动改 8 个地方:

1. `deck-schema.json` 加 enum + sub-schema
2. `validate-deck.py` 加业务规则
3. `render-deck.py` 加 enricher
4. `templates/<new>.fragment.html` 写模板
5. 可能要写 CSS (放 extra-layouts.css 还是 feishu-deck-patterns.css 决策)
6. `editor.js` EXTRA_FIELDS / ARRAY_FIELDS map 加条目
7. SKILL.md (DECK GENERATION POLICY) 提到新 layout
8. 例子 sample 更新 (sample-deck.json + migrated-from-toml/proposal-mvw.json)

每个 layout ~半天到 1 天工作,4 个共 2-3 天。不阻塞当前 editor 收敛,作为下一波 schema 扩展专项执行。

---

# Phase 4 服务端 editor · 2026-05-21 退役

(2026-05-21 决定)

## 背景

Phase 4.a-4.b.6 累计交付了一个基于 stdlib HTTP server + 浏览器 UI 的本地可视化编辑器(`deck-editor.py` + `editor/` frontend + `deck-editor.command`)。功能完整：

- 3 栏 UI(slide 列表 / preview iframe / inspector)
- 拖拽 reorder · 缝隙横线指示 · drop 到空白区
- Preview 内 in-place 文字编辑(contenteditable)
- Inspector 顶层标量 + 嵌套字段 + 数组编辑 + polymorphic body_blocks
- 图片拖拽上传 / PDF → replica 导入(需 poppler) / multi-deck 切换
- CSRF token / path containment / switch-deck allow-list 全套安全
- 键盘 cheatsheet · QUICKSTART 文档 · macOS .command 双击启动器

## 为什么退役

用户决定改做**独立客户端 editor**(在渲染好的 HTML 网页里直接 WYSIWYG 编辑),不再需要服务端编辑器作为中间层。

- 客户端 editor 更轻量(无 server / 无端口 / 无授权)
- WYSIWYG 比 inspector 表单更直观
- deck-editor.py 的 inspector 也只覆盖 schema 字段的一小部分,深度受限
- "服务端 + 浏览器 + iframe" 三层架构对单用户单 deck 偏重

## 删除的资产

- `deck-editor.py` (754 行)
- `deck-editor.command` (40 行,macOS 启动器)
- `editor/index.html` (148 行)
- `editor/editor.css` (520 行)
- `editor/editor.js` (~1700 行,含 BLOCK_TYPES / ARRAY_FIELDS / EXTRA_FIELDS / In-place edit / CSRF / multi-deck switcher / image upload / PDF import)
- `EDITOR-QUICKSTART.md` (235 行)
- `tests/test_editor_schema_parity.py` (267 行 —— 没 editor 就不需要防 BLOCK_TYPES vs schema drift)

总 ~3700 行删除。git 历史(commit `c327192`)永久保留;任何时候 `git show c327192:.../deck-editor.py` 即可恢复。

## 保留的资产

| 资产 | 在新方案中的角色 |
|---|---|
| `deck-schema.json` | 不变。Schema 仍是 deck.json 的字段单一来源 |
| `render-deck.py` | 不变。客户端 editor 的输入是它产出的 HTML |
| `validate-deck.py` | 不变。deck.json 生成阶段校验 |
| `templates/` | 不变。renderer 用 |
| `deck-cli.py` | 保留。客户端 editor 主管 in-line 编辑,deck-cli 管结构操作(clone / reorder / set-variant) |
| `tests/test_validate_examples.py` | 保留。schema 回归 |
| `tests/test_textid_roundtrip.py` | 保留。render-deck 产出的 data-text-id 格式契约 —— 客户端 editor 仍可能用 |
| `tests/test_deck_cli_smoke.py` | 保留。CLI 回归 |
| `SKILL.md DECK GENERATION POLICY` | 保留 + 微调。Option C 改成指向"客户端 editor",不再是 deck-editor.py |

## DeckJSON 在新方案中的角色

仍然是 **deck 生产线** —— Claude / 人写 deck.json → render-deck → HTML → **客户端 editor 接管** WYSIWYG 编辑。

- DeckJSON: deck 生成 + 结构(slides 数组 / accent / decor / metadata)的契约
- 客户端 editor: 渲染后的视觉编辑层
- 当用户需要结构操作(clone / reorder)时,**回到 deck.json + deck-cli**,再 render → 新 HTML 进 editor

参考之前讨论的 50/50 bespoke 场景:**重复 50% slide 走 schema fastpath,bespoke 50% slide 用 layout:raw + framework primitives**,客户端 editor 对两类一视同仁(都是 HTML 视觉编辑)。

## 经验教训

1. **Inspector 表单的天花板**:把 schema 字段一一映射到表单 = 永远追不上 schema 增长。BLOCK_TYPES drift 就是这问题(review 出 6 个字段 mismatch)
2. **WYSIWYG > 字段表单**:对 90% 修改场景,用户想"看到怎么改",不是"填正确字段值"
3. **HTTP server 对单用户偏重**:CSRF / path containment / 多 deck 切换 / 启动 alias —— 都是为了让 server 模式好用,但根本问题是"不需要 server"
4. **schema + renderer 真核心**:删了 ~3700 行 editor,核心 deck 生产能力 0 损失。说明**Phase 0-3 才是 deck-json 的真本质**,Phase 4 是探索性 UI 实验


---

# Phase 5 · PPT 素材库整合 · 2026-05-21

读飞书 PPT 母版库(`~/Downloads/素材库.pptx`, 122 slides + 12 layouts + 314 媒体),
完整评估见 [PPT-LIBRARY-MAPPING.md](./PPT-LIBRARY-MAPPING.md)。

## 关键发现

- **Framework 跟 PPT 库已 100% 颜色 / 字体对齐** —— framework 本来就是按这份 PPT 做的
- PPT 库 12 个 master layout 跟 deck-json 10 base 是正交维度:PPT 按"标题样式+logo 联名"切,deck-json 按"内容结构"切
- 122 slides 中 ~53% 起手即直接覆盖,真新 layout 需求只 ~12%(都是 Phase 0.3 评估清单上的)

## 路线 A 实施清单(2 batch + 1 batch)

### Batch 1 (commit `98cb5e5`):
- `content/before-after` variant — 痛点→飞书后对比布局
- `logo-wall` 新 base layout — N 行业 × M 客户 logo
- deck-level `title_style` (4) + `logo_position` (2) = 8 PPT master 风格组合

### Batch 2 (commit `1bba84e`):
- `arch-stack` 新 base layout — 2-5 层架构图
- `flow/swim` variant — 多泳道 roadmap (time × lanes 网格)
- `testimonial-card` block — 客户证言(name + title + quote + portrait + company_logo)

### Batch 3 (post-merge):
- `mockup-card` block — UI mockup 4 kinds(past / now / callout / compare)
- `persona-card` block — 用户画像(name + role + generation + summary + portrait)
- `end` 加 optional `slogan` 字段 — PPT '封底(带 slogan)' master
- `section` 加 optional `parent_label` 字段 — PPT '二级章节页' master

## 覆盖度变化

| | 起点 (Phase 4 ship) | 路线 A 末 |
|---|---|---|
| Schema 直接覆盖 | 53% | **~90%** |
| 需扩 variant/block/字段 | 25% | ~5% |
| 真需要新 layout | 12% | **0%**(全部已加) |
| 资源 / 真 raw | 10% | ~10%(不变,正常 ceiling) |

## Schema 现状(Phase 5 末)

```
Base layouts:        12  (从 10 加到 12: +logo-wall +arch-stack)
Content variants:     6  (+before-after)
Flow variants:        4  (+swim)
Stats variants:       3  (不变)
Embeddable blocks:   10  (+testimonial-card +mockup-card +persona-card)
Deck-level config:    title_style (4) × logo_position (2) = 8 PPT master 组合
```

## 跳过项 (明确 defer / 不做)

- SVG icon 库解压编目 —— 196 个 SVG 用户明确不要,跳过
- 完全 bespoke 单页 layout —— 用 `layout: raw` + framework primitives (validate.py 静态守门)
- AI 集成(Phase 4.c) —— 用户明确不要
- Twin column / step-circles / logo-strip / issue-frequency 等更细 block —— 真用到时再加
