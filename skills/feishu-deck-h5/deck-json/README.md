# DeckJSON · 单一数据模型 + 渲染器 + CLI + 可视化编辑器

**Purpose**: one structured data model for every feishu-deck-h5 deck.
Decouples *deck content* from *HTML/CSS rendering* so that:

1. The LLM produces JSON instead of free-form HTML → 输出空间收敛到 schema 内,生成稳定性飞跃.
2. A visual editor edits the same JSON the LLM produces → 编辑器和 AI 共用一套数据模型.
3. Renderer is a pure function → 同样的 JSON 永远渲染同样的 HTML(确定性).

---

## Entry points · 第一次进来看哪个

| 想做什么 | 文档 |
|---|---|
| **写一份新 deck** (作为 Claude / 作为人) | `../SKILL.md` § **DECK GENERATION POLICY** |
| **可视化编辑 deck** (浏览器) | [`EDITOR-QUICKSTART.md`](./EDITOR-QUICKSTART.md) |
| **脚本批量改 deck** (CLI) | [`DECK-CLI-README.md`](./DECK-CLI-README.md) |
| **理解 schema 设计 / 历史 / 取舍** | [`MIGRATION-REPORT.md`](./MIGRATION-REPORT.md) |
| **字段 ground truth** | [`deck-schema.json`](./deck-schema.json) |

---

## 工具一览

```
deck-json/
├── README.md             ← 你正在看
├── EDITOR-QUICKSTART.md  ← 非技术同事友好的编辑器使用
├── DECK-CLI-README.md    ← 14 个原子命令的 reference
├── MIGRATION-REPORT.md   ← Phase 0-3 设计取舍、Phase 0.3 评估
│
├── deck-schema.json      ← JSON Schema Draft 2020-12 · 单一字段源
├── validate-deck.py      ← stdlib 校验器(schema + 业务规则)
├── render-deck.py        ← 渲染器(triple-gate: schema → render → validate.py)
├── deck-cli.py           ← 14 个原子操作命令
├── deck-editor.py        ← 可视化编辑器 HTTP server
├── deck-editor.command   ← macOS 双击启动器
│
├── editor/               ← 编辑器前端 (index.html + editor.css + editor.js)
├── templates/            ← 渲染器使用的 24 个 layout/block 片段模板
├── examples/             ← sample-deck.json (14 slides 覆盖每个 layout)
│                          + migrated-from-toml/ (历史 deck 迁移产物)
└── tests/                ← 回归测试
```

---

## Quick start

```bash
# 1. 用 sample-deck.json 起手
cp examples/sample-deck.json runs/<ts>/output/deck.json

# 2. 渲染(triple-gate · schema → render → validate.py)
python3 render-deck.py runs/<ts>/output/deck.json runs/<ts>/output/

# 3. 起编辑器调内容
python3 deck-editor.py runs/<ts>/output/deck.json
# 浏览器自动打开,3 栏 UI: slide list / preview / inspector
# 双击 preview 文字直接改 · 拖动 slide 重排
```

或者用 alias 一键:

```bash
echo "alias edit-deck='python3 ~/Documents/GitHub/feishu-deck-h5/skills/feishu-deck-h5/deck-json/deck-editor.py'" >> ~/.zshrc
source ~/.zshrc
edit-deck    # 自动找最近的 deck.json
```

---

## Schema 一览

### 10 base layouts + 2 specials

| Layout | Variants | 用于 |
|---|---|---|
| `cover` | — | 标题页 |
| `agenda` | — | 目录 / TOC pills |
| `section` | — | 章节分隔 + 大编号 |
| `content` | `3up` / `2col` / `story-case` / `blocks` / `matrix` | 3 卡片 / 左文右图 / 一页纸案例 / 全宽 body / 2×2 矩阵 |
| `stats` | `row` / `hero` / `waterfall` | 3-4 KPI 列 / 1 个 hero 数字 / 桥图 |
| `quote` | — | 客户/专家引言单页 |
| `image-text` | — | 全屏图片 + 浮层文字 |
| `table` | — | 对比表格 |
| `flow` | `timeline` / `process` / `tree` | 时间轴 / 步骤 / MECE 拆解树 |
| `end` | — | 结束页 |
| **specials** | | |
| `replica` | — | 全屏 PDF 页图 |
| `raw` | — | 单页 HTML 自由发挥(escape hatch) |

= **10 base + 2 specials = 12 layout enum values**。多 variant 层叠出 **18 个实际可用版式**。

**10-base 不变量是有意的** — 加新 pattern 优先考虑做 existing layout 的 variant,只有结构性完全不同才加新 base。见 MIGRATION-REPORT.md Phase 0.2 的 4-proposal 评估过程。

### 7 个 embeddable blocks

可嵌入到 `content/3up.body_blocks[]` / `content/2col.text.body_blocks[]` / `content/blocks.body_blocks[]`:

| block type | 用于 | 必填字段 |
|---|---|---|
| `pullquote` | 强调引言 (橙/蓝/紫 tone) | text |
| `cta-box` | 行动召唤 strip | heading |
| `kpi-strip` | 2-4 数字 mini-cards | kpis[] |
| `data-panel` | 非 app 结构化数据 | title, rows[] |
| `verdict-grid` | 判断卡 (go/conditional/nogo) | cards[] |
| `phone-iframe` | 手机预览(嵌 iframe) | iframe_src |
| `principle-band` | 三色策略原则 | principles[] |

字段精确定义见 [`deck-schema.json`](./deck-schema.json) `$defs/block_*`。Inspector 的 `BLOCK_TYPES` 镜像 schema,**测试** (`tests/test_editor_schema_parity.py`) 强制对齐。

---

## 共享 slide 属性

| 字段 | 类型 | 说明 |
|---|---|---|
| `key` | kebab-case string, **unique** | 语义 locator (`data-slide-key`),slide-library ingest 必需 |
| `layout` | enum (12 个值) | 主鉴别字段 |
| `variant` | string (content/stats/flow **必须**) | 子鉴别字段,单 variant layout 上忽略 |
| `screen_label` | string (optional) | 上下页 UI 显示文字。默认从 title 派生 |
| `accent` | enum: blue/teal/violet/purple/orange | **无 cyan** (规则 R49 编码在 schema) |
| `decor` | string[] (token) | violet-glow / blue-glow / mix-glow / teal-glow / orange-spark / aurora / grain / topo / flower-bg / section-bg / photo-bg |
| `language_override` | enum | 单 slide override `deck.language` |
| `notes` | string | 作者备注(不渲染) |

---

## What the validator checks

1. **JSON Schema** (deck-schema.json) — types / enums / required / additionalProperties:false / allOf 触发的 variant 约束
2. **业务规则** (validate-deck.py 内置):
   - 唯一 slide key
   - kebab-case slide key
   - accent ≠ cyan (R49)
   - decor token whitelist
   - 长 title 警告
   - texts.md 兼容性 hint

3. **HTML validator** (assets/validate.py) — 渲染产物再过一道,~40 条规则 (R02 / R06 / R20 / L1-L4 / BF1-BF12 / 等)

triple-gate 序: 任何一道 fail → 整体失败 → backup 恢复。

---

## 现况 · Phase status

| Phase | 内容 | 状态 |
|---|---|---|
| **0** | 10 base layouts + 7 blocks + schema + validator + sample-deck | ✅ shipped |
| **0.1** | embeddable block 5→7 (加 `verdict-grid`, `phone-iframe`) | ✅ shipped |
| **0.2** | proposal-mvw.json 4 个 consulting 模式 (matrix/exec-summary/waterfall/tree) → variant 扩展通过 | ✅ shipped |
| **0.3** | 评估剩 4 proposal (arch-stack / logo-wall / roadmap-swim / before-after) | 📝 评估完毕(见 MIGRATION-REPORT.md),实施暂缓 |
| **1** | 渲染器 (render-deck.py · 1230 行 · 18 enricher · 7 block partial) | ✅ shipped |
| **2** | SKILL.md DECK GENERATION POLICY · Claude 默认走 Path A (DeckJSON-first) | ✅ shipped |
| **3** | 14 个原子 CLI 操作 (deck-cli.py) | ✅ shipped |
| **4.a** | Editor 基础: 3 栏 UI + 拖拽 + import + inspector 顶层字段 | ✅ shipped |
| **4.b.1** | Preview in-place 文字编辑 | ✅ shipped |
| **4.b.2** | Inspector 数组编辑(cards/cols/nodes/bars/...) | ✅ shipped |
| **4.b.3** | 图片拖拽上传 | ✅ shipped |
| **4.b.4** | body_blocks polymorphic 编辑 | ✅ shipped |
| **4.b.5** | PDF → replica 导入 (需 `brew install poppler`) | ✅ shipped |
| **4.b.6** | 嵌套字段(story-case / matrix / tree.leaves) | ✅ shipped |
| **4.c** | AI 集成(写整页 / 重设计 / 图→deck / review) | 🟡 排队 |

---

## 维护者备注

- `deck-schema.json` 是字段唯一真理。**新增 layout = 先改 schema,再改 validator / renderer / editor map**。
- 编辑器的 `BLOCK_TYPES` / `EXTRA_FIELDS` / `ARRAY_FIELDS` 是 schema 的镜像,**必须**通过 `tests/test_editor_schema_parity.py` 测试。
- validator 实现 JSON Schema Draft 2020-12 子集。如果需要新 keyword (`dependentRequired` / `format` / 跨文件 `$ref` 等),要在 `validate-deck.py` 加。
- 加新 layout 时同步加 negative test 到 `tests/`,证明 schema 真的拒了 bad input。
