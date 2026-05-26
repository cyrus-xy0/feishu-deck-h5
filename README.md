# feishu-deck-h5

> **飞书风格的客户提案 deck，但是 HTML 不是 PPT。**
> 浏览器全屏放映、单文件发 IM、文本编辑器改字、视觉与飞书母版完全对齐。

🔗 看样品 → [`examples/sample-deck.html`](examples/sample-deck.html)
（双击在浏览器打开，左右键翻页）

---

## 这是什么

把飞书母版 2025（深色通用）的 PowerPoint 视觉**完整搬到 HTML**，生成的就是一份
`.html` 文件，但它表现得跟 PPT 一样：

- **浏览器全屏 = 16:9 演示模式** — 左右键翻页、底部进度条、闲置自动隐藏控件
- **手机能看** — 自动切换成纵向滚动浏览，发链接给客户立刻能预览
- **单文件可直接转发** — 飞书 / 邮件 / IM 任何途径，对方双击就开，不用装 Office
- **文字用记事本改** — 配套 `texts.md` 文本侧文件，改文字不动布局
- **视觉跟飞书品牌完全对齐** — 15 个 DeckJSON layout enum（13 个常规 + 2 个 special）沿用飞书母版坐标，色值/字号/留白由 renderer 和 validator 约束

更完整的产品方向见 [`PRODUCT.md`](PRODUCT.md):本项目正在从单个 H5 生成
skill，演进为“场景规划 → 知识库 → 素材库 → DeckJSON → H5 渲染 → Pitch 预演
→ 反馈入库”的产品闭环。

---

## 产品化能力

- **outline planner** — `skills/deck-outline-planner/` 先判断行业痛点、受众、
  证据缺口、素材计划和页级 layout candidate,避免只做视觉 demo。
- **知识库** — 飞书 Base `知识库` 是 source of truth; `knowledge/` / `.base-cache/`
  只作为本地副本。
- **素材索引** — 飞书 Base `素材库` 统一索引 logo、图片、video、icon、demo 等素材;
  `assets/shared/asset-index.generated.json` 由 Base 导出,本地 agent 和飞书 bot 共用
  `scripts/base_library.py` 这一套访问入口。
- **H5 渲染** — `skills/feishu-deck-h5/` 消费 outline,优先用 DeckJSON-first
  生成可编辑、可校验、可入库的 HTML deck。
- **服务端 wrapper** — `server/generator.py` 固化 `Brief -> Outline -> DeckJSON -> HTML`
  链路,生成任务目录、运行 renderer / validator,并输出预览、编辑和下载链接字段。
- **Pitch 预演** — `skills/pitch-rehearsal-simulator/` 在 HTML deck 之后模拟
  决策者、推动者、使用者、技术和财务角色逐页反应,输出异议地图和改稿队列。

---

## 为什么不直接用 PowerPoint

| | PowerPoint .pptx | feishu-deck-h5 .html |
|---|---|---|
| 文件大小 | 几十 MB 起步 | 24-360 KB |
| 需要 Office license | 是 | 否（任何浏览器都能开） |
| 飞书/IM 转发 | 经常变形 | 单文件，对方双击即看 |
| AI 直接生成 | 很难做出像样的 | 天然适合（HTML 是 LLM 母语） |
| 视觉一致性 | 靠人盯 | 55 项规范程序化自动校验 |
| 版本管理 / 协作 | git 看不了 diff | 标准 git diff，PR review 友好 |

不是替代 PPT 所有场景——客户硬要 .pptx 还是给 .pptx。但售前/内训/产品提案
这些**多人迭代 + 多渠道分发**的场景，HTML 几乎是完胜。

---

## 支持哪些 layout

15 个 DeckJSON layout enum（13 个常规 + 2 个 special），覆盖一份典型客户提案
从封面到封底的所有页型。`content` / `stats` / `flow` 是多 variant layout，
因此实际可用版式约 20 个：

| Layout | 适合什么内容 |
|---|---|
| **cover** | 封面 — 飞书母版花朵背景，标题在左、配图在右 |
| **agenda** | 议程 — 3-6 项垂直 pill 堆叠，开场目录 |
| **section** | 章节分隔 — 巨型序号 + 章节标题 + 产品 pill |
| **content** | 三卡并列、左文右图、一页纸案例、矩阵、前后对比、全宽 blocks |
| **stats** | KPI 行、单个英雄数字、桥图 |
| **quote** | 客户证言 / 金句 — 居中大字 + 来源 |
| **image-text** | 全屏照片 + 左下角文字 — 客户现场 / 门店 / 工厂 |
| **table** | 对比表 — 飞书 vs 传统套件这种比较矩阵 |
| **flow** | 时间轴、流程步骤、MECE 树、多泳道 roadmap |
| **logo-wall** | 行业 / 客户 logo 矩阵 |
| **arch-stack** | 应用、平台、AI、数据底座等分层架构图 |
| **iframe-embed** | 嵌入 live demo、原型、报表或外部 HTML |
| **end** | 封底 — 飞书品牌花朵背景 + "先进团队 先用飞书" slogan |
| **replica / raw** | special: PDF 页图复刻 / 单页 HTML escape hatch |

**加成**：

- **11 个叙事模式** — 北极星指标 chip、verdict 判定矩阵、"做 / 不做" boundary band、
  现阶段 → 未来 evolution chip、北极星地图、行业邻接场景 grid 等，覆盖飞书内部
  常用的"几种主张并列"、"判断接 / 部分接 / 不接"等结构化论证。
- **27 个 UI 原语** — `.ui-window` / `.ui-grid` / `.ui-msg` / `.ui-tabs` / `.ui-kpi` 等，
  让产品截图用 HTML 重建而非贴 PNG，缩放永远清晰、字体永远跟 deck 一致。
- **飞书产品官方 logo** — aily / 多维表格 / 妙搭 / 飞书会议 / 飞书人事 / 集成平台
  等全套产品标识，无需自己画 SVG。

完整 layout 规格 + 11 个叙事模式 + UI 原语清单见 [SKILL.md](skills/feishu-deck-h5/SKILL.md)。

---

## 看更多例子

- [`examples/sample-deck.html`](examples/sample-deck.html) — HTML 示例 deck
- [`preview-dark.html`](preview-dark.html) — 设计令牌（颜色 / 字号 / 渐变）+ 组件 gallery
- [`templates/slide-recipes.html`](templates/slide-recipes.html) — 每种 layout 的 reference 实现

---

## 怎么开始用

**让 Claude 帮你装 + 帮你做**，一句话：

> "帮我安装 feishu-deck-h5 skill：https://github.com/FuQiang/feishu-deck-h5，
> 装完帮我做一份关于〔你的主题〕的 deck"

Claude 会读 [INSTALL.md](INSTALL.md) 走标准安装流程（plugin marketplace 或 install.sh），
然后按 [SKILL.md](skills/feishu-deck-h5/SKILL.md) 的规范生成 deck。

如果你只有一段业务场景 brief,推荐先让 agent 使用 `deck-outline-planner`
产出 outline,确认后再交给 `feishu-deck-h5` 渲染。

如果已经生成了 HTML deck,可以继续让 agent 使用 `pitch-rehearsal-simulator`
预演“拿这套片子去讲会发生什么”,产出 `pitch-rehearsal.json` 和
`PITCH_REHEARSAL.md`,再把修改队列回写到 outline / deck.json。

---

## 想看怎么搭出来的

| 内容 | 文档 |
|---|---|
| 安装路径（marketplace / install.sh / 手动 clone） | [INSTALL.md](INSTALL.md) |
| 15 layout enum + 11 叙事模式 + 27 UI 原语 + 55 自检项 | [SKILL.md](skills/feishu-deck-h5/SKILL.md) |
| 9-section 完整设计系统 | [DESIGN.md](DESIGN.md) |

---

## License

MIT — 见 [LICENSE](LICENSE)。

`assets/lark-*.png/jpg` 是 ByteDance / 飞书的官方品牌资产，版权归飞书设计团队，
不在本仓库 MIT 许可范围内，第三方使用前请遵守飞书品牌规范。
