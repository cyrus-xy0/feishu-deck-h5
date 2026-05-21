# PPT 素材库映射评估 · 2026-05-21

> **实施状态 (2026-05-21 末):** 路线 A 全部完成 + batch 2 完成 + batch 3 完成。
> 覆盖度从 53% → **~90%**。剩 ~10% 是真 raw / 资源 / 单页定制。
> 已实施清单见 MIGRATION-REPORT.md.

**输入**: `~/Downloads/素材库.pptx` — 飞书 Pitch Deck 母版资源库
**输入规模**: 122 slides + 12 layout 母版 + 314 媒体文件(196 SVG / 85 PNG / 等)
**输出**: 跟 deck-json 现有 schema 的契合度地图,以及"做哪些工作 ROI 最高"建议

---

## 重大发现:design system 已经对齐

| 维度 | 状态 |
|---|---|
| **颜色 6 个 accent** | ✅ **完全一致**(blue/teal/violet/purple/orange 一字不差) |
| **CJK 字体** | ✅ **完全一致**(framework 把方正兰亭黑 Pro_GB18030 作首选) |
| **字号阶梯** | ⚠️ framework 收敛到 4 tier (16/24/28/48),PPT 用 14+ 种 — framework 比 PPT 严格 |
| **cyan accent2 (#24C3FF)** | ⚠️ PPT 有,framework R49 拒(用 violet 替) |
| **Latin 字体** | ⚠️ framework=Inter,PPT=FZLanTingHeiPro_GB18030 Light(可调) |

**结论:你 framework 当前就是按这份 PPT 库做的。Theme.css 不用单独写 —— 它已经 baked-in 在 feishu-deck.css 里**。

---

## 122 slides 的真实分布

```
slide   1     · 母版总览
slide   2-14  · 【基础元素】icons / mockups / 圆角投影 / logo 占位          (13 slides)
slide  15-36  · 【典型通用】目录 / 金句 / 封底 / 焦虑话术 / 介绍模板            (22 slides)
slide  37-55  · 【设计组件】表格 / 卡片 / 流程 / 结构图                    (19 slides)
slide  56-64  · 【问题调研】挑战 / 高频问题 / 数据表                      (9 slides)
slide  65-78  · 【竞品对比】对比表 / Before-After / 问题 1/2/3            (14 slides)
slide  79-84  · 【客户案例】一页纸 / 企业介绍                            (6 slides)
slide  85-91  · 【客户证言】姓名 + 职位 + 金句                          (7 slides)
slide  92-98  · 【产品界面展示】UI mockup + 流程图                      (7 slides)
slide  99-103 · 【AI 场景】打单场景 / 现状痛点                         (5 slides)
slide 104-122 · 【服务体系】服务介绍 / 数据 / 品牌墙 / 占比统计              (19 slides)
```

## PPT 12 个 layout 母版 vs deck-json 现有 layout

| PPT layout 母版 | deck-json layout / variant | 状态 |
|---|---|---|
| 封面 | `cover` | ✅ 完全对应 |
| 一级章节页-1 | `section` | ✅ 对应 |
| 二级章节页 | `section` + variant `subsection` | ⚠️ **schema 缺二级 variant** |
| 金句页 | `quote` | ✅ 对应 |
| 内容页-飞书联名在前 | `content/*` + `logo_position: front` | ⚠️ **logo 位置作 deck-level 字段需加** |
| 内容页-飞书联名在后 | `content/*` + `logo_position: back` | ⚠️ 同上 |
| 封底(带 slogan) | `end` + variant `with-slogan` | ⚠️ end 现在无 variant |
| 封底(可编辑结束语) | `end` | ✅ 默认 |
| 内容页-标题单行居中 | `content/*` + `title_style: center-single` | ⚠️ **title 样式作字段需加** |
| 内容页-标题双行居中 | ↑ + `center-double` | ⚠️ 同上 |
| 内容页-标题双行居左 | ↑ + `left-double` | ⚠️ 同上 |
| 内容页-标题在左 | ↑ + `left` | ⚠️ 同上 |

**核心 mismatch**: PPT 按"标题样式"(4 种)+"logo 联名位置"(2 种)细分 = 8 个 layout master,但 deck-json 按"内容结构"(3up/2col/story-case/blocks/matrix)细分。

→ **不冲突,正交维度**。建议作 deck-level 配置:
```jsonc
{
  "deck": {
    "title_style": "left-double",       // 4 选 1
    "logo_position": "front"            // front / back
  }
}
```

由 framework CSS 用 `:root[data-title-style="left-double"]` 切换。无需改 layout enum。

---

## 122 slides 详细覆盖度(汇总)

| 覆盖度 | slides 数 | 占比 |
|---|---|---|
| ✅ **直接覆盖** (schema 现有 layout 直接用) | ~65 | 53% |
| ⚠️ **部分覆盖** (schema 用但需扩 variant / block / 字段) | ~30 | 25% |
| 🆕 **需新增** (schema 当前装不下,真的要加 layout / block) | ~15 | 12% |
| 📚 **资源 / 不映射** (icon 库 / 字体 / 示范页,不是 layout) | ~5 | 4% |
| 🚫 **走 raw**(高度定制,不进 schema) | ~7 | 6% |

## ✅ 直接覆盖(~65 slides)

| PPT slides | 对应 deck-json | 备注 |
|---|---|---|
| 12 (封面) | `cover` | |
| 13-14 (封底) | `end` | 14 加 variant `with-slogan` |
| 17 (目录) | `agenda` | |
| 18-21, 86-91 (金句) | `quote` | 86-91 加 attribution + portrait → 用 portrait block? |
| 2/15/37/56/65/79/85/92/99/104 (section 分隔) | `section` | |
| 61, 66-67 (表格) | `table` | |
| 75, 116 (大数字) | `stats/hero` | |
| 119-122 (占比 / 品牌墙数据) | `stats/row` / `stats/hero` | 加 logo 配饰 |
| 7/25/26 (挑战 / 三栏) | `content/3up` | |
| 27-28/95 (左文右图) | `content/2col` | |
| 39-50 (大部分设计组件) | `content/blocks` | body_blocks 拼装 |
| 80 (客户案例一页纸) | `content/story-case` | |
| 100-103 (AI 工作流) | `flow/process` 4 步 | |

## ⚠️ 部分覆盖(~30 slides) — 需扩字段 / variant / block

| PPT slides | 现有 | 缺什么 |
|---|---|---|
| 二级章节页 (slideLayout3) | `section` | 加 variant `subsection` + `parent_label` 字段 |
| 6 (UI Mockup 4 模式) | — | 加 4 个 mockup block: 过去 / 现在 / 突出 / 对比卡片 |
| 31-32 (主标题 + 多内容文案) | `content/blocks` | data-panel block + 备注字段 |
| 34 (企业介绍 + 5000+ logo + 内容) | — | 新 layout `customer-intro`? 或 content/2col + logo grid block |
| 35 (人物介绍 70 后 / 姓名 / 职位) | — | 新 block `persona-card`? |
| 36 (logo + 内容文案 多行) | — | 新 block `logo-strip` |
| 38-50 中部分(卡片矩阵) | `content/blocks` | 现有 verdict-grid / kpi-strip 大致够 |
| 51 (5 个点击文案) | — | content/blocks 加 `step-circles` block |
| 57-58 (挑战文案大字) | `content/3up` | 加 variant `challenges`(对应粗大 + ✕图标) |
| 59-60 (高频问题 / 普通问题) | — | 加 `issue-frequency` block? |
| 62 (管理 / 提效 / 降本) | `stats/row` | 加 `kpi-tagged` 加文字 tag |
| 71-73 (Before/After) | — | **Phase 0.3 评估过 — 加 variant `content/before-after`** |
| 78 (问题 1/2/3) | `content/3up` | variant `numbered-problems` |
| 84 (企业介绍 multi-image) | — | content/2col + image-grid block? |
| 105-107 (服务体系细节) | `content/blocks` | 多 block 拼,目前应该够 |
| 110 (4 阶段路线图) | `flow/timeline` | variant `lane-grouped` (=roadmap-swim) — **Phase 0.3 评估过** |
| 113 (走进 100 家企业) | `stats/hero` | 加 logo 装饰 strip |

## 🆕 需新增(~15 slides) — schema 真装不下

| PPT slides | 推荐 |
|---|---|
| 3, 4, 118 (产品 ICON 资源 / 功能 ICON 资源 / icon 大表) | 不进 schema —— **作 framework 内置 icon 库**(/assets/shared/icons/)。slide 119-122 等 deck 引用 |
| 5 (高亮字体示范) | 不进 schema —— framework 文档/示范页 |
| 6 (Mockup 4 模式) | 4 个新 block: `mockup-past` / `mockup-now` / `mockup-callout` / `mockup-compare` |
| 8 (圆角投影示范) | 不进 schema —— framework 内置规范文档 |
| 9 (UI 框 大/小 展示) | 加 `ui-frame` block (大 / 小 size 变体) |
| 11 (联名 logo 位置) | 不进 schema —— deck-level 字段 `logo_position` |
| 22-24 (10 大陷阱专题) | 新 layout `enumerated-list`?或 content/blocks + numbered cards |
| 89-90 (证言 with 人物头像 + 公司 logo) | 新 block `testimonial-card`(姓名 + 职位 + 引言 + 头像) |
| 93-94, 98 (UI 界面 + 流程图 + 文案) | 新 block `ui-with-flow`(扩展 phone-iframe 概念) |
| 121-122 (品牌墙 with stat overlay) | 新 layout `logo-wall` — **Phase 0.3 评估过** |

## 📚 资源类(~5 slides) — 不是 layout

| 内容 | 处理 |
|---|---|
| Icon 库(slide 3-4, 118) | 195 个 SVG 已在 `ppt/media/`,可解压到 `skills/feishu-deck-h5/assets/shared/icons/` 编目 |
| 字体示范(slide 16) | 进 framework 文档,不进 schema |
| 客户 LOGO 占位(slide 10) | 编目到 `assets/shared/clientlogo/`(已有结构) |
| 联名 LOGO(slide 11) | 同上 |

## 🚫 走 raw(~7 slides) — 高度定制 / 一次性

| PPT slides | 为何走 raw |
|---|---|
| 复杂 service 体系树(部分 107-112) | 树形 + 多层 + 节点 / 边都自定义 |
| 117 (滚动品牌带) | 动态效果,schema 表达不出 |
| 部分 deeply customized 视觉 | 设计师为某 deck 专做 |

---

## 工作量估算(把 ⚠️ 和 🆕 都做了)

### Tier 1 · 主题级别(已完成 0%,无需做)
所有 token 已对齐,**0 工作量**。

### Tier 2 · Schema 扩展(中等)

| 项 | 估时 | 优先级 |
|---|---|---|
| Deck-level `title_style` (4 选 1) + framework CSS 切换 | 半天 | 高 (PPT 8 个母版的根本差异) |
| Deck-level `logo_position` (front/back) + CSS 切换 | 半天 | 高 |
| `section` 加 variant `subsection` | 1 小时 | 中 |
| `end` 加 variant `with-slogan` | 1 小时 | 中 |
| `content/3up` 加 variant `challenges` (痛点 + ✕) | 半天 | 中 |
| `content/3up` 加 variant `numbered-problems` (问题 1/2/3) | 半天 | 中 |
| `content/before-after` 新 variant (Phase 0.3) | 1 天 | 中 |
| `flow/swim` 新 variant (Phase 0.3 roadmap) | 1-2 天 | 中 |
| `logo-wall` 新 base layout (Phase 0.3) | 1-2 天 | 高 |
| `mockup-*` 4 新 block | 2-3 天 | 中 |
| `testimonial-card` 新 block | 半天 | 中 |
| `persona-card` 新 block | 半天 | 低 |
| `step-circles` `logo-strip` `issue-frequency` 等 block | 各半天 | 低 |
| **小计** | **~8-12 天** | |

### Tier 3 · 资源管理(独立 track)

| 项 | 估时 |
|---|---|
| 把 196 个 SVG 解压 + 命名编目到 `assets/shared/icons/` + 写一个 README | 1-2 天 |
| 把 PNG / JPG client logo 解压 + 编目 | 半天 |
| **小计** | **~2 天** |

### 全总 ~10-14 天工作量

如果都干完:Schema 能装下原 PPT 库 **~95% slides**(剩 5% 走 raw)。

---

## 推荐路径

按"立刻有用 / 杠杆最大"排:

### 路线 A · "最小改动,最大覆盖" (~3-4 天)

按使用频率,只做 ROI 高的:

1. ✅ `logo-wall` 新 layout (客户案例 deck 几乎必有) — **1-2 天**
2. ✅ `content/before-after` (痛点 → 解决方案对比,提案 deck 几乎必有) — **1 天**
3. ✅ Deck-level `title_style` + `logo_position` (改 1 个 deck 全切风格) — **1 天**
4. ✅ 解压 SVG icon 库到 `assets/shared/icons/` — **1 天**

**完成后**: ~80% PPT slides 能进 schema。

### 路线 B · 全覆盖 (~10-14 天)

A + 剩余 ⚠️ 和 🆕 项。

### 路线 C · 不动 schema,只做素材 (~2 天)

只整理 196 SVG icon 库 + client logo,layout 完全不动。Deck 设计师手 work,但拿到完整 icon 资源用。

---

## 我的判断

你的核心需求是"**装下大量定制化 layout**"。给出 3 个真实数字让你决策:

- **PPT 库 53% slides 用现有 schema 能直接装** —— 这部分零工作量
- **25% slides 需要扩 schema** —— ~5-7 天工作把这部分装下
- **12% 真的需要新 layout** —— ~5-7 天(主要是 Phase 0.3 那 4 个 + mockup 系列)
- **剩 10% 资源 / raw** —— 不动 schema

**这跟 "50% 定制化" 的紧张感不一致 —— PPT 库 ~78% 实际能进 schema,只 12% 是真新 layout。"定制化"听起来吓人,实际多数是 variant 级别的微调。**

如果你之前担心的 50% 是想说"50% slides 跟基础 layout 风格不同,但本质结构能对应",那:**schema 完全 hold 住**。

如果是"50% slides 结构都没法预测",那:数据不支持。PPT 库摆在那 122 个 = 公司过去所有 deck 的精华,12% 真新 layout 是天花板。

---

## 我建议执行的下一步

**路线 A**(3-4 天)杠杆最高:

| 第 1-2 天 | 加 `logo-wall` + `content/before-after` 两个 layout/variant |
| 第 3 天 | 加 deck-level `title_style` + `logo_position` |
| 第 4 天 | 解压 SVG → `assets/shared/icons/` + 索引 README |

完成后:
- 80%+ PPT slides 可用 schema 表达
- design 一致性靠 validate.py 静态规则维持
- 剩 20% 是 raw 个性化(用 validate.py 兜底)

要不要走?如要走,从哪个开始?
