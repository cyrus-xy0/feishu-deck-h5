# deck-pipeline

> **飞书 HTML Deck 全流程治理技能** — 编排 feishu-deck-h5 及相关技能，从用户输入到 HTML 交付物的一条龙流水线。

## 技能定位

本技能是一个**流程编排器（orchestrator）**，不自己生成 HTML，而是：
1. 将 feishu-deck-h5 的散装脚本和决策点串联成有序流水线
2. 在关键决策点强制人工确认
3. 预留扩展点，未来可插入 PDF 解析、图片处理等外部技能

**解决的核心问题**：feishu-deck-h5 的 SKILL.md 有 ~4900 行，agent 需要多轮对话才能理解全貌、容易遗漏步骤、在决策点不主动确认。本技能把流程固化成 stage → task 的结构化流水线。

---

## 输出目录规范

所有输出文件**必须**放到项目根目录下的 `deck-design/deck-pipeline/` 目录中：

```
<project-root>/
└── deck-design/
    └── deck-pipeline/
        ├── runs/                     ← 每次运行的产出（按时间戳隔离）
        │   └── <YYYYMMDD-HHMMSS>/
        │       ├── input/            ← 输入材料
        │       ├── output/           ← 输出产物
        │       │   ├── index.html    ← 主 deck
        │       │   ├── texts.md      ← 文本编辑 sidecar
        │       │   ├── FEEDBACK.md   ← 反馈记录
        │       │   └── assets/       ← 自包含资产
        │       └── RUN-META.yaml     ← 运行元信息
        └── _shared/                  ← 跨 run 共享中间产物
```

**禁止**写入 `deck-design/deck-pipeline/` 以外的位置。

---

## 全流程总览

```
Stage 0: 环境就绪    →  预检 + 工作区创建
Stage 1: 输入解析    →  内容采集 + 模式选择（🛑 人工确认）
Stage 2: 内容生成    →  Deck 生成 + 资产匹配 + 文本标注
Stage 3: 质量保障    →  校验 + 修复循环
Stage 4: 交付封装    →  自包含输出 + 打包 + 交付（🛑 人工确认）
```

---

## Stage 0 · 环境就绪

目标：确保技能可运行，创建隔离的工作区。

| Task ID | 原子 Task | 调用目标 | 解决的问题 | 失败策略 |
|---|---|---|---|---|
| T0.1 | 运行 preflight 检查 | `feishu-deck-h5/assets/preflight.sh` | 验证本地挂载 + 写权限 + 必需文件 | exit ≠ 0 → 告知用户挂载本地目录，终止流程 |
| T0.2 | 创建 per-run 工作区 | `feishu-deck-h5/assets/new-run.sh [slug]` | 隔离每次运行的 input/output | 失败 → 检查权限，终止流程 |
| T0.3 | 记录 run 元信息 | 写入 `output/RUN-META.yaml` | 记录本次 run 的时间戳、输入类型、模式选择 | — |

**前置依赖**：无
**人工确认**：无（自动执行）
**产出**：`deck-design/deck-pipeline/runs/<ts>/{input,output}/` + `RUN-META.yaml`

---

## Stage 1 · 输入解析

目标：理解用户要做什么，选择正确的生成模式。

| Task ID | 原子 Task | 调用目标 | 解决的问题 | 失败策略 |
|---|---|---|---|---|
| T1.1 | 采集用户输入 | 读取用户消息 / `input/` 目录文件 | 明确内容来源（简报 / PDF / PPT / TOML） | 无输入 → 提示用户提供 |
| T1.2 | 判断输入类型 | agent 逻辑判断 | 区分：文本简报 / 设计稿 PDF / 结构化 TOML / 已有 HTML | — |
| T1.3 | 选择生成模式 | agent 逻辑 + 🛑 人工确认 | 三选一：①DeckJSON Render（deck.json→render-deck.py）/ ②Replica（PDF 页面转图片）/ ③Rewrite（LLM 原生重画） | — |
| T1.4 | 评估内容密度 | agent 逻辑 + 🛑 人工确认 | 检测信息是否过薄，是否需要补内容 | 薄 → 停下来问用户 |
| T1.5 | 确定语言模式 | agent 逻辑 + 🛑 人工确认 | zh-only（默认）或 zh-en（双语 opt-in） | — |

**前置依赖**：Stage 0 完成
**🛑 人工确认点**：
- T1.3：确认生成模式（Replica 保留原设计 vs Rewrite 原生重画）
- T1.4：信息薄时确认是否补内容、补什么
- T1.5：确认语言模式

**确认话术模板**：
```
📋 模式确认
· 生成模式：{Replica/Rewrite/DeckJSON Render}
· 内容密度：{充足/偏薄 — 建议补充：①… ②… ③…}
· 语言模式：{zh-only/zh-en}
请确认或调整：
```

---

## Stage 2 · 内容生成

目标：生成符合飞书规范的 HTML deck。

**🔴 前置条件**：执行本 Stage 前，agent **必须**已阅读 `DESIGN.md` 全文（§1-§9）和 `feishu-deck.css` 中的 `.wordmark` / 各 `data-layout` 规则。详见「设计规范合规」章节。

| Task ID | 原子 Task | 调用目标 | 解决的问题 | 失败策略 |
|---|---|---|---|---|
| T2.0 | **设计规范预检** | 读取 DESIGN.md + feishu-deck.css | 确认 agent 理解飞书 Deck 设计约束 | — |
| T2.1 | DeckJSON Render 路径 | `feishu-deck-h5/deck-json/render-deck.py deck.json output/` | 用新版 DeckJSON 管线确定性渲染标准 layout 与模板化 deck | schema / validate 拒绝 → 切 LLM 手写 |
| T2.2 | LLM 手写路径 | agent 按 SKILL.md + DESIGN.md 规范手写 HTML | render-deck.py 不覆盖的 layout 或 schema-fit 失败 | — |
| T2.3 | Replica 路径 | 外部工具（pdf2image/imagemagick）+ HTML 壳 | 保留设计师原稿的视觉保真度 | 外部工具不可用 → 提示安装或切 Rewrite |
| T2.4 | **品牌资产复制** | 从 `feishu-deck-h5/assets/` 复制到 `output/assets/` | Logo / CSS / JS / 背景图等全部到位 | 缺失 → 不交付 |
| T2.5 | 标注 data-text-id | agent 在生成时同步标注 | 建立 texts.md 编辑回路 | — |
| T2.6 | 标注 data-slide-key | agent 在生成时同步标注 | 满足 validator R-KEY + slide-library 入库 | — |
| T2.7 | **合规自检** | 运行 §5 合规检查清单 | 验证颜色/字体/Logo/chrome 全部合规 | 不通过 → 修复后重跑 |
| T2.8 | 生成 texts.md | `feishu-deck-h5/assets/extract-texts.py` | 输出文本编辑 sidecar | — |

**前置依赖**：Stage 1 完成 + 模式已确认 + DESIGN.md 已阅读
**人工确认**：无（按已确认的模式自动执行）
**产出**：`deck-design/deck-pipeline/runs/<ts>/output/index.html` + `texts.md` + 完整 `assets/` 目录

---

## Stage 3 · 质量保障

目标：确保 deck 通过所有规范检查。

| Task ID | 原子 Task | 调用目标 | 解决的问题 | 失败策略 |
|---|---|---|---|---|
| T3.1 | 运行 validator | `feishu-deck-h5/assets/validate.py index.html` | 检查 27+ 条规范 | errors ≠ 0 → 进入修复循环 |
| T3.2 | 修复 validator errors | agent 根据 "how to fix" 提示修复 | 自动修复可程序化解决的问题 | 修复后重跑 T3.1，最多 3 轮 |
| T3.3 | 运行 strict validator | `feishu-deck-h5/assets/validate.py index.html --strict` | 交付前硬门槛 | warnings → 评估是否可接受 |
| T3.4 | **真实浏览器渲染验证** | Chrome/Safari headless screenshot 或 computed style 脚本 | 验证最终浏览器画面，而不是只验证源码字符串 | 不通过 → 进入 CSS 级联排查 |
| T3.5 | 人工 review | 🛑 人工确认 | validator 无法检查的视觉/内容问题 | — |

**前置依赖**：Stage 2 完成
**🛑 人工确认点**：
- T3.5：用户在浏览器中打开 deck，确认视觉效果

**修复循环**：T3.1 → T3.2 → T3.1（最多 3 轮），3 轮后仍有 error → 告知用户具体问题，请求指导

### 真实浏览器渲染验证硬门禁

> **铁律**：涉及视觉结果的修改，不能只用源码字符串、文件时间戳、validator 或 inline 成功日志证明。必须用浏览器真实渲染结果证明。

#### 必须触发的场景

满足任一条件即触发 T3.4：
- 新生成 HTML 首页/内容页/封底页
- 应用 M mode / S mode / 删除元素导出的 `deck-edits-*.json`
- 修改 `transform`、`animation`、`opacity`、`display`、`font-size`、`width/height`、`top/left/right/bottom`、`margin`、`grid/flex`
- 用户反馈“文件没有变化”“还是老样子”“位置不对”“和截图不一致”

#### 最低验证标准

```
□ 用最终交付 HTML 路径打开真实浏览器，而不是只打开 linked index.html
□ 用 Chrome headless 或 Safari 截图生成 render-check-*.png
□ 对关键元素读取 computed style 或截图人工核对
□ 若修改 transform，必须确认 computed transform 不是母版 reveal 动画的 translate3d 覆盖值
□ 若修改 display/opacity，必须确认元素在截图中真实显隐
□ 若修改字体/尺寸，必须确认截图中文字大小或元素框真实变化
□ 验证截图文件路径必须回传或记录在交付说明中
```

#### 标准命令模板

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless --disable-gpu --hide-scrollbars \
  --window-size=1024,576 \
  --screenshot=output/render-check-<name>.png \
  file:///ABSOLUTE/PATH/TO/output/lark-<name>.html
```

无 Chrome 时可用 Safari/系统浏览器打开，但仍必须通过截图或 computed style 取得运行时证据。

#### CSS 级联排查顺序

出现“源码已变但视觉没变”时，必须按以下顺序排查，禁止先归因于缓存：
1. 目标元素 inline style 是否写入正确值
2. `getComputedStyle(target).transform/fontSize/display/opacity` 是否等于预期
3. 母版规则是否覆盖目标元素，重点检查 `.slide-frame.is-current .slide > *`、reveal animation、layout 规则和 `!important`
4. 若 inline transform 被母版覆盖，必须使用稳定豁免方案：给元素加 `data-fixed-transform="true"`，并在自定义 CSS 中添加更高优先级规则，显式写入最终 `transform`、`transform-origin`、`animation: none !important`
5. 重新 inline 生成最终 HTML，再用最终 HTML 路径重新截图验证

---

## Stage 4 · 交付封装

目标：产出可离开技能目录的交付物。

| Task ID | 原子 Task | 调用目标 | 解决的问题 | 失败策略 |
|---|---|---|---|---|
| T4.1 | **资产完整性检查** | 验证 `output/assets/` 包含全部必需文件 | 确保离线可用、Logo 显示正常 | 缺失 → 从 `feishu-deck-h5/assets/` 补齐 |
| **T4.1b** | **完整备份（修改前必做）** | 运行「备份与内嵌完整性」§1 标准备份脚本 | 防止改坏后无法回退；确保所有引用文件一起备份 | 备份失败 → 不继续修改 |
| T4.2 | **iframe srcdoc 转换 + 自包含输出** | 先运行 §2 自动转换脚本处理 iframe，再执行 `inline-assets.py index.html` | CSS/JS/图片内嵌 + iframe 内容内嵌为单文件 HTML | 失败 → 手动诊断 |
| T4.2b | **交付物完整性验证** | 按「备份与内嵌完整性」§3 检查清单逐项验证 | 确保双击即可打开、无裂图、iframe 可见 | 不通过 → 修复后重跑 |
| T4.2c | **最终交付 HTML 渲染验证** | 对 inline 交付物执行 T3.4 截图/computed style 验证 | 确保最终交付文件真实视觉正确，而不是只验证 linked 源文件 | 不通过 → 回到 T3.4 CSS 级联排查 |
| T4.3 | 生成 FEEDBACK.md | agent 自动记录本次 run 的关键决策 | 人机闭环反馈 | — |
| T4.4 | 选择交付形态 | 🛑 人工确认 | 三选一：A:inline HTML / B:zip edit kit / C:hosted URL | — |
| T4.5 | 执行交付封装 | `feishu-deck-h5/assets/finalize.sh output/ [mode] [--strict] [--name ...]` | 一条命令完成 copy-assets + extract-texts + validate + 打包 | 失败 → 按退出码诊断 |
| T4.6 | 交付物命名 | `--name lark-<customer>-<YYYY-MM-DD>` | 符合命名规范 | — |
| T4.7 | 回传交付物 | 按模式回传路径/zip/URL | 确保用户收到可打开的文件 | — |

**前置依赖**：Stage 3 通过
**🛑 人工确认点**：
- T4.3：确认交付形态（默认 inline，如需编辑选 zip）

**确认话术模板**：
```
📦 交付确认
· 交付形态：{inline 单文件 / zip 编辑包 / URL}
· 文件名：lark-<customer>-<date>.html
· 文件大小：~xxx KB
请确认：
```

---

## 扩展点（未来技能接入）

| 扩展点 | 对应 Stage | 接入方式 | 候选技能 |
|---|---|---|---|
| PDF 解析 | Stage 1 → T1.2 | 替换 agent 逻辑判断为技能调用 | pdf-extract skill |
| 图片处理 | Stage 2 → T2.4 | 替换 agent 资产匹配为技能调用 | image-process skill |
| 多格式输出 | Stage 4 → T4.3 | 增加 .pptx / .pdf 输出路径 | pptx-export skill |
| 批量生成 | Stage 2 → T2.1 | 循环调用 render-deck.py | batch-render skill |

---

## 设计规范合规（Design Compliance）

> **硬性要求**：所有 HTML 产出物必须严格遵循 `feishu-deck-h5/DESIGN.md` 定义的设计规范。
> 这是 deck-pipeline 的**第 0 条铁律**，在 Stage 2 内容生成和 Stage 5 修改流程中均强制执行。

### 1. 必读规范文件

生成或修改 HTML 前，agent **必须**先读取以下文件：

| 文件 | 路径 | 用途 |
|------|------|------|
| **DESIGN.md** | `feishu-deck-h5/DESIGN.md` | 飞书 Deck 完整设计规范（颜色/字体/布局/组件/Do's & Don'ts） |
| **feishu-deck.css** | `feishu-deck-h5/assets/feishu-deck.css` | 飞书样式表（含 `.wordmark` / `.slide[data-layout=...]` 等全部组件样式） |
| **feishu-deck.js** | `feishu-deck-h5/assets/feishu-deck.js` | 飞书运行时 JS（缩放/翻页/chrome 渲染） |

### 2. 品牌资产清单（必须复制到 output/assets/）

每次创建新 run 或执行 T4.1 自包含输出时，以下资产**必须**从 `feishu-deck-h5/assets/` 复制到 `output/assets/`：

```
feishu-deck-h5/assets/
├── feishu-deck.css          ← 样式表（必须）
├── feishu-deck.js            ← 运行时 JS（必须）
├── lark-logo.png             ← 飞书彩色 Logo（必须 — .wordmark 默认引用）
├── lark-logo-mono-white.png  ← 飞书白色单色 Logo（必须 — 暗色背景页用）
├── lark-content-bg.jpg       ← content 页背景纹理（content-2col / content-3up 等）
├── lark-cover-bg.jpg         ← 封面背景图
├── lark-section-bg.jpg       ← 章节(section)页背景图
├── lark-slogan.png           ← 封底 slogan 图
├── lark-en-logo.png          ← 英文版 Logo
└── lark-logo-mono-white.png  ← 白色单色 Logo
└── shared/                   ← 客户 logo 库、产品图标等
    ├── clientlogo/
    ├── bytedance-products/
    └── digital_employee_avatars_50/
```

**关键规则**：
- `lark-logo.png` 和 `lark-logo-mono-white.png` 是 `.wordmark` 组件的图片源，**缺失会导致 Logo 不显示**
- CSS 中通过 `--fs-asset-logo: url("lark-logo.png")` 变量引用，inline-assets.py 会自动内嵌为 base64

### 3. 设计规范核心约束速查表

#### 颜色（只用 CSS 变量，禁止裸写 hex）

```css
/* 背景 */
--fs-bg-0     /* #000000 默认 */
--fs-bg-1     /* #04060F 深色替代 */
--fs-bg-2     /* #0A1230 冷深度 */
--fs-bg-3     /* #1B1F3A 冷深度 */

/* 品牌强调色（每页只用一个） */
--fs-blue     /* #3C7FFF 默认主色 */
--fs-teal     /* #33D6C0 数据/KPI */
--fs-purple   /* #5C3FFB 差异化 */
--fs-violet   /* #9F6FF1 差异化 */
--fs-orange   /* #FE7F00 高注意力 */

/* 文字 */
--fs-text      /* #FFFFFF 标题 */
--fs-text-72   /* rgba(255,255,255,.72) 正文 */
--fs-text-65   /* rgba(255,255,255,.65) 卡片 */
--fs-text-48   /* rgba(255,255,255,.48) EN副标题 */
--fs-text-40   /* rgba(255,255,255,.40) 页脚 */
```

#### 字体层级（1920px 画布）

| 角色 | 大小/粗细 | 行高 | 字间距 |
|------|----------|------|--------|
| 封面标题 | 100/700 | 1.18 | -0.005em |
| 章节标题 | 88/700 | 1.18 | -0.005em |
| 页面 H2 | 52/600 | 1.10 | -0.005em |
| Lede 导语 | 32-36/500 | 1.40 | 0 |
| 正文 | 28/500 | 1.50 | 0 |
| 卡片正文 | 20/500 | 1.60 | 0 |
| **底线** | **≥14px** | | **正文≥24px, CJK≥20px** |

#### 布局（12 种标准 layout）

| Layout | 用途 | 容器类 |
|--------|------|--------|
| `cover` | 封面 | `.stage` |
| `section` | 章节分隔 | 直接子元素 |
| `agenda` | 目录 | `.toc` |
| `content-3up` | 三卡片 | `.grid` |
| `content-2col` | 左文右图 | `.grid` |
| `stats` | 四格数据 | `.grid` |
| `big-stat` | 单大数字 | `.stage` |
| `quote` | 金句 | `.stack` |
| `image-text` | 全屏图+字 | `.stage` |
| `table` | 表格 | `.table-wrap` |
| `timeline` | 时间轴 | `.nodes` |
| `process` | 流程步骤 | `.flow` |
| `end` | 封底 | 直接子元素 |

#### Chrome（每页必备）

| 元素 | 规则 |
|------|------|
| **飞书 Logo** | `<div class="wordmark">飞书</div>` — 彩色花瓣+文字，160×50px 右上角；封面/封底用 235×74px 左上角。**禁止纯文字替代** |
| **data-screen-label** | 每个 slide 必须 `<div class="slide" data-layout="xxx" data-screen-label="NN Title">` |
| **data-slide-key** | 每个 slide 必须 `data-slide-key="unique-key"` 用于定位 |
| **data-accent** | 每个 slide 必须 `data-accent="blue|teal|purple|violet|orange"` |
| **data-decor** | 可选装饰 `data-decor="blue-glow|violet-glow|aurora|none"` |

### 4. 绝对禁止项（来自 DESIGN.md §7 Do's and Don'ts）

| ❌ 禁止 | ✅ 正确做法 |
|---------|-----------|
| emoji 作为图标或内联 | 使用 inline SVG（Lucide 风格，24px viewBox） |
| `!` `…` `???` 在幻灯片文案中 | 删掉，让数字和事实说话 |
| 一页用两个品牌 accent | 只用一个（图表系列等兄弟元素除外） |
| 拉伸/重新着色飞书 Logo | 使用原始 `lark-logo.png`，不修改 |
| 对幻灯片内容加 drop-shadow | 用对比度和 hairline border 替代 |
| Latin 标题用 Title Case | 用 Sentence case |
| 正文 < 24px 来塞内容 | 删减内容，不要缩小字号 |
| CJK 和 ASCII 标点混用 | CJK 用全角 `「」。，` EN 用 ASCII `,.` |
| unicode 字符 →✓ ✗ 当图标 | 写真正的 SVG |
| stock photo 人物/等距插画 | 用数据可视化/UI mock/抽象图形 |

### 5. 合规检查清单（Stage 2 生成后 & Stage 5 修改后必跑）

```
□ 所有颜色值使用 --fs-* CSS 变量（grep '#[0-9a-fA-F]{3,8}' 排查裸写 hex）
□ 每页只有一个 data-accent（cyan 只用于行内关键词高亮）
□ .wordmark 存在且引用的是 lark-logo.png（非纯文字）
□ 所有 slide 有 data-layout + data-slide-key + data-screen-label + data-accent
□ 正文字号 ≥ 24px，CJK ≥ 20px，chrome ≥ 16px
□ 无 emoji、无 !…???、无 drop-shadow、无混合标点
□ output/assets/ 包含 lark-logo.png + lark-logo-mono-white.png
□ 引用的 assets/ 下的文件都存在（无 404）
□ ZH 在上 EN 在下（双语场景）
□ 飞书 Logo 未被拉伸/重新着色/重绘
```

### 6. 自定义布局时的特殊规定

当用户需求无法匹配 12 种标准 layout 时（如本次同仁堂双栏时间轴页面），允许手写自定义 HTML，但**必须满足**：

1. **画布固定 1920×1080**，`.slide-frame` 和 `.slide` 尺寸不可变
2. **引入 feishu-deck.css** 并继承其变量体系（`--fs-*`）
3. **保留 `.wordmark`** 组件并正确引用 Logo 图片
4. **颜色只从 `--fs-*` token 取值**，新增的自定义变量以 `--tr-` 前缀命名
5. **字体使用 `var(--fs-font-cjk)` / `var(--fs-font-latin)`**
6. **暗色背景**（`#000` 或 `--fs-bg-*`），不用亮色底
7. **无 drop-shadow / backdrop-blur**
8. **自定义组件的 class 名** 以 `tr-` 前缀避免与飞书基础样式冲突

---

## 强制规则

1. **Stage 0 失败 = 全流程终止**：preflight 不通过，后续所有步骤都不执行
2. **🛑 确认点不可跳过**：Stage 1 的模式选择、Stage 3 的视觉 review、Stage 4 的交付形态，必须用户明确确认
3. **修复循环上限 3 轮**：Stage 3 的 validator 修复最多 3 轮，超过则请求人工指导
4. **交付物必须自包含**：Stage 4 产出的文件必须能在技能目录外独立打开
5. **禁止编造数据**：STORY id / 数据来源 / 访谈出处，用户没给就不写
6. **每次产出必须回传路径**：交互模式下，每次生成/修改都必须在回复中指向 `deck-design/deck-pipeline/runs/<ts>/output/` 下的文件
7. **输出目录规范**：所有文件必须写入 `deck-design/deck-pipeline/`，禁止写入项目根目录其他位置
8. **🔴 设计规范合规是铁律**：所有 HTML 产出必须遵循 `DESIGN.md` + `feishu-deck.css` 的完整设计规范。Logo 图片必须复制到位。自定义布局需遵守 §6 特殊规定。违规 = 不交付。
9. **🔴 Debug 标注模式 + 网格标尺 + 交互式移动 + 交互式尺寸调整必须内置**：所有生成的 HTML 必须同时包含 Debug 标注模式（D 键）、网格标尺覆盖层（R 键）、交互式移动模式（M 键）和交互式尺寸调整模式（S 键），这是标准能力而非可选功能。详见「Debug 标注模式」「网格标尺覆盖层」「交互式移动模式」和「交互式尺寸调整模式」章节。
10. **🔴 备份必须完整 + iframe 必须内嵌**：备份时必须扫描并包含所有被引用的外部文件（iframe src、img src、CSS url() 等），禁止只拷贝 index.html + index-inline.html。HTML 中的 iframe 必须使用 `srcdoc` 替代 `src`，确保 inline 文件双击即可完全打开。详见「备份与内嵌完整性」章节。
11. **🔴 真实渲染验证是交付硬门槛**：任何新生成、修改样式、应用 `deck-edits-*.json`、重新 inline 的 HTML，必须用最终交付 HTML 路径完成浏览器截图或 computed style 验证。未通过 T3.4/T4.2c 不得宣称“已修复/已完成”。

---

## Debug 标注模式（标准内置能力）

> **硬性要求**：每次生成的 HTML 产出物**必须**包含 Debug 标注模式代码。这是截图驱动修改的基础设施，不是可选功能。

### 功能说明

在浏览器中按 **D 键** 切换 Debug 标注模式：
- 每个可编辑文字元素显示**蓝色标签**（`data-text-id`）
- 每个图片元素显示**橙色标签**（`data-text-id`）
- 每个 slide 左上角显示**渐变标签**（slide-key + layout + accent）
- 右上角显示 **"DEBUG MODE — 按 D 退出"** 橙色脉冲徽章
- URL 加 `#debug` 可自动开启（如 `index.html#debug`）

### 必须注入的代码

以下代码**必须**在每次生成 HTML 时注入到 `<style>` 和 `<body>` 中：

#### CSS（注入到 `</style>` 前）

```css
.debug-mode [data-text-id] {
  outline: 2px solid var(--fs-blue) !important;
  outline-offset: 4px;
}
.debug-mode img[data-text-id] {
  outline: 3px solid var(--fs-orange) !important;
  outline-offset: 4px;
}
.debug-label {
  position: absolute; z-index: 999999; pointer-events: none;
  font-family: var(--fs-font-mono, 'SF Mono', 'Menlo', 'Consolas', monospace);
  font-weight: 700; white-space: nowrap; line-height: 1.4;
  letter-spacing: 0.5px; box-shadow: 0 2px 12px rgba(0,0,0,0.6);
  padding: 4px 10px; border-radius: 5px; font-size: 13px;
}
.debug-label.text-label {
  background: var(--fs-blue); color: #fff; top: -28px; left: 0;
}
.debug-label.img-label {
  background: var(--fs-orange); color: #fff; top: -28px; left: 0; font-size: 12px;
}
.debug-label.slide-label {
  background: linear-gradient(135deg, var(--fs-teal), var(--fs-blue));
  color: #fff; font-size: 14px; padding: 5px 14px;
  border-radius: 0 0 6px 6px; top: 10px; left: 10px;
}
.debug-badge {
  position: fixed; top: 16px; right: 16px;
  background: linear-gradient(135deg, #FF6B35, var(--fs-orange));
  color: #fff; padding: 8px 18px; border-radius: 8px;
  font-size: 14px; font-weight: 700; z-index: 9999999;
  display: none; pointer-events: none;
  font-family: var(--fs-font-mono, 'SF Mono', 'Menlo', 'Consolas', monospace);
  box-shadow: 0 4px 20px rgba(255,107,53,0.6);
  letter-spacing: 1px;
  animation: debug-pulse 2s ease-in-out infinite;
}
@keyframes debug-pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.05); opacity: 0.85; }
}
.debug-mode .debug-badge { display: block; }
```

#### HTML（注入到 `<body>` 开头）

```html
<div class="debug-badge">DEBUG MODE — 按 D 退出</div>
```

#### JS（注入到 `<div class="deck">` 前）

```javascript
<script>
(function(){
  var debugActive = false;
  var labels = [];
  function createLabel(text, className, parent) {
    var span = document.createElement('span');
    span.className = 'debug-label ' + className;
    span.textContent = text;
    parent.style.position = 'relative';
    parent.appendChild(span);
    return span;
  }
  function injectLabels() {
    labels.forEach(function(l){ if(l.parentNode) l.parentNode.removeChild(l); });
    labels = [];
    if (!debugActive) return;
    document.querySelectorAll('.slide[data-slide-key]').forEach(function(slide){
      var key = slide.getAttribute('data-slide-key') || '';
      var layout = slide.getAttribute('data-layout') || '';
      var accent = slide.getAttribute('data-accent') || '';
      var label = createLabel(key + ' | ' + layout + ' | accent=' + accent, 'slide-label', slide);
      labels.push(label);
    });
    document.querySelectorAll('[data-text-id]').forEach(function(el){
      if (el.tagName === 'IMG') {
        var label = createLabel(el.getAttribute('data-text-id'), 'img-label', el);
        labels.push(label);
      } else {
        var label = createLabel(el.getAttribute('data-text-id'), 'text-label', el);
        labels.push(label);
      }
    });
  }
  function toggle() {
    debugActive = !debugActive;
    document.body.classList.toggle('debug-mode', debugActive);
    document.querySelector('.debug-badge').style.display = debugActive ? 'block' : 'none';
    injectLabels();
  }
  document.addEventListener('keydown', function(e){
    if((e.key==='d'||e.key==='D') && !['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName)){
      toggle();
    }
  });
  if (location.hash === '#debug') { setTimeout(toggle, 500); }
})();
</script>
```

### 技术要点

1. **使用 DOM 注入而非 CSS `::after`**：因为 `.slide` / `.stage` 容器有 `overflow: hidden`，CSS 伪元素会被裁剪不可见。必须用 `document.createElement('span')` 创建真实 DOM 节点。
2. **颜色使用 `var(--fs-*)` 变量**：标签颜色遵循飞书设计规范，不裸写 hex。
3. **`#debug` hash 自动开启**：方便分享带标注的预览链接。
4. **与 `data-text-id` / `data-slide-key` 绑定**：依赖 Stage 2 T2.5/T2.6 的标注工作。

---

## 网格标尺覆盖层（标准内置能力）

> **硬性要求**：与 Debug 标注模式并列，所有生成的 HTML 必须同时包含网格标尺功能。这是用户精确沟通定位的基础设施。

### 功能说明

在浏览器中按 **R 键**切换网格标尺模式：
- 显示 **1920×1080 坐标网格**（每 100px 一格，每 500px 主刻度加粗）
- **顶部 X 轴标尺** + **左侧 Y 轴标尺**（像素刻度）
- 鼠标移动时显示**橙色十字准星 + 实时坐标标签**
- URL 加 `#ruler` 可自动开启（如 `index.html#ruler`）
- 可与 **Debug 模式（D 键）同时使用**

### 用户沟通定位的标准话术

用户按 R 开启标尺后，可以这样描述位置：

#### 🔴 锚点约定（必须遵守）

**默认锚点 = TL（Top-Left / 左上角）**。即 `x` 和 `y` 指的是元素的**左上角坐标**。

Ruler 模式下鼠标悬停任何元素时：
- 元素显示**橙色虚线边框**
- **左上角**出现红色圆点（锚点标记）
- 右侧显示标签：`x,y | 宽×高 | TL`

| 锚点类型 | 后缀 | 含义 | CSS 实现 |
|---------|------|------|---------|
| **TL**（默认） | 无后缀或写 `TL` | 左上角定位 | `left: x; top: y;` |
| TC | `TC` | 顶部居中 | `left: calc(x - width/2); top: y;` 或 `left:50%; transform:translateX(-50%); top:y;` |
| TR | `TR` | 右上角 | `right: (1920-x); top: y;` |
| ML | `ML` | 左侧垂直居中 | `left: x; top: calc(y - height/2);` |
| CC | `CC` | 正中心 | `left: calc(x - width/2); top: calc(y - height/2);` |
| MR | `MR` | 右侧垂直居中 | `right: (1920-x); top: calc(y - height/2);` |
| BL | `BL` | 左下角 | `left: x; bottom: (1080-y);` |
| BC | `BC` | 底部居中 | `left: calc(x - width/2); bottom: (1080-y);` |
| BR | `BR` | 右下角 | `right: (1920-x); bottom: (1080-y);` |

> **约定**：用户不指定锚点时，Agent 默认按 **TL（左上角）** 执行。用户可显式指定如 "移到 x=500 y=300 CC" 表示以中心点对齐。

#### 标准指令格式

| 指令类型 | 示例 | Agent 执行 |
|---------|------|-----------|
| 绝对坐标（TL默认） | "标题移到 x=120 y=80" | `position:absolute; left:120px; top:80px` |
| 绝对坐标（指定锚点） | "KPI卡片中心对齐 x=960 y=400 CC" | `position:absolute; left:calc(960px - width/2); top:calc(400px - height/2)` |
| 相对偏移 | "时间轴下移 30px" | `margin-top:30px` 或 `top += 30` |
| 对齐参照 | "结论条左边缘与标题左边缘对齐" | 两者 `left` 取相同值 |
| 尺寸调整 | "右侧区域宽度增加 200px" | `grid-template-columns` 调整 |
| 间距控制 | "两栏间距从 56px 改为 80px" | `gap: 80px` |

### 必须注入的代码

同 Debug 标注模式，Ruler 模式的 CSS + HTML badge + JS 与 Debug 模式**并列注入**在同一位置。详见「Debug 标注模式」章节中的完整代码模板（已包含 Ruler 逻辑 + 悬停尺寸检测）。

### 技术要点

1. **坐标换算**：鼠标屏幕坐标 → 画布坐标 = `(e.clientX - rect.left) * (rect.width / 1920)`
2. **悬停元素检测**：`document.elementFromPoint()` + 向上遍历找到有实际尺寸的父元素，跳过 SPAN/BR/I/EM/STRONG/B 等内联元素
3. **性能优化**：只在 `rulerActive=true` 时监听 mousemove
4. **DOM 构建**：标尺刻度通过 JS 动态生成（0-1920 / 0-1080 每 100px），避免 HTML 臃肿
5. **z-index 层级**：网格(999998) < 十字准星(999999) < 徽章(9999999)
6. **锚点可视化**：红圆点标记左上角(TL)，橙色虚线边框标注元素边界，标签显示 `x,y | w×h | TL`

---

## 交互式移动模式（Move Mode — M 键）

> **解决的核心问题**：之前用户需要读 Ruler 坐标 → 口头告诉我 → 我设 CSS → 偏了 → 再调，多轮对话才能对齐。现在用户直接在页面上点两下 = 完成。

### 交互流程

```
按 M 键进入 Move Mode
  ↓
┌──────────────────────────────────────────────┐
│ 顶部绿色徽章: "🎯 MOVE MODE — 按 M 退出"     │
│ 底部提示: "📍 第 1 步：点击要移动的元素"       │
└──────────────────────────────────────────────┘
  ↓ 用户点击目标元素
┌──────────────────────────────────────────────┐
│ 元素被绿色高亮 + 脉冲发光动画                  │
│ 底部提示: "📍 第 2 步：点击目标位置"            │
└──────────────────────────────────────────────┘
  ↓ 用户点击目标位置
┌──────────────────────────────────────────────┐
│ 绿色虚线箭头: 起点 → 终点                     │
│ 十字准星标记目标位置                           │
│ 弹出确认面板:                                 │
│   · 源元素 class / data-text-id              │
│   · 当前位置 (TL) → 目标位置 (TL)             │
│   · 将执行的 CSS 代码                         │
│   · [✓ 执行移动] [✕ 取消]                    │
└──────────────────────────────────────────────┘
  ↓ 用户点击 "✓ 执行移动"
┌──────────────────────────────────────────────┐
│ 元素按视觉位移移动到目标位置                    │
│ Move Mode 明确退出，不自动二次 toggle          │
│ 如需继续移动，用户再次按 M                      │
└──────────────────────────────────────────────┘
```

### 技术实现要点

1. **触发键**：`M` 键（不区分大小写），排除 INPUT/TEXTAREA/SELECT
2. **坐标系统**：以浏览器真实 `clientX/clientY` 和 `getBoundingClientRect()` 为唯一事实来源；展示坐标可换算为 `.slide` 设计坐标（1920×1080），但移动执行不得直接使用设计坐标写 `left/top`
3. **元素选择**：`document.elementFromPoint()` 精确捕获，自动向上冒泡到有尺寸的父元素（跳过 SPAN/BR/I/EM/STRONG/B/SVG）
4. **样式应用**：Move Mode 禁止用 `position/left/top` 直接重定位。必须使用浏览器真实渲染坐标计算视觉位移：`dx = targetClientX - sourceRect.left`、`dy = targetClientY - sourceRect.top`，再除以 slide 缩放比例生成 `transform: translate(tx, ty)`，最后用 `element.style.setProperty('transform', value, 'important')` 应用。
5. **事件拦截顺序**（⚠️ 关键）：
   ```javascript
   // ❌ 错误：preventDefault 在 UI 检查之前 → 按钮点击被吞
   e.preventDefault(); e.stopPropagation();
   if (t.closest('.move-confirm-panel')) return;

   // ✅ 正确：先检查是否点击了 UI 元素，再拦截
   if (t.closest('.move-confirm-panel')) return;
   e.preventDefault(); e.stopPropagation();
   ```
6. **UI 元素白名单**：`.move-confirm-panel` / `.move-badge` / `.move-step-hint` / `.inspect-panel` / `.debug-badge` / `.ruler-badge` 的点击不拦截

### 标准命令格式

| 操作 | 命令示例 | 说明 |
|------|---------|------|
| 移动元素到指定坐标 | `将结论条移到 x=97 y=502` | 仍支持文字指令，但推荐用 M 键交互 |
| 交互式移动 | 按 M 键 → 点元素 → 点目标 | **推荐方式**，零偏移 |

### 最终算法模板（必须使用）

```javascript
var moveTargetClientX = 0;
var moveTargetClientY = 0;

function toSlideCoords(clientX, clientY) {
  var sr = getSlideRect();
  return {
    x: Math.round((clientX - sr.left) / (sr.width / 1920)),
    y: Math.round((clientY - sr.top) / (sr.height / 1080))
  };
}

// 第二次点击目标位置时保存浏览器真实坐标
moveTargetClientX = e.clientX;
moveTargetClientY = e.clientY;

// 执行前生成视觉位移，而不是 left/top
var slide = moveSourceEl.closest('.slide') || document.querySelector('.slide');
var sRect = slide.getBoundingClientRect();
var scaleX = sRect.width / 1920;
var scaleY = sRect.height / 1080;
var dx = moveTargetClientX - moveSourceRect.left;
var dy = moveTargetClientY - moveSourceRect.top;
var tx = Math.round(dx / scaleX);
var ty = Math.round(dy / scaleY);
var baseTransform = srcStyle.transform && srcStyle.transform !== 'none' ? srcStyle.transform : '';
var cssText = 'transform: translate(' + tx + 'px, ' + ty + 'px)' +
  (baseTransform ? ' ' + baseTransform : '') + ';';

// 应用时逐属性设置，避免 cssText += 失效
moveSourceEl.style.setProperty('transform', cssText.replace(/^transform:\s*|\s*;$/g, ''), 'important');
```

### Move Mode 自检清单

生成或修改 Move Mode 后，必须检查：

```
□ M 键绑定存在：key==='m'||e.key==='M'
□ 第二次点击保存 client 坐标：moveTargetClientX = e.clientX / moveTargetClientY = e.clientY
□ toSlideCoords 使用除法反推设计坐标：/ (sr.width / 1920)，不是乘法
□ 移动使用视觉差值：moveTargetClientX - moveSourceRect.left
□ translate 按 slide scale 反推：tx = dx / scaleX，ty = dy / scaleY
□ 最终 CSS 使用 transform: translate(...)
□ 应用样式使用 setProperty(..., 'important')
□ 禁止出现 position:relative;left: 或 position:absolute;left:+目标坐标 的移动算法
□ 点击确认面板按钮不被吞：preventDefault/stopPropagation 必须在 UI 白名单检查之后
□ 执行完成后不自动二次 toggleMove；如需继续移动，由用户再次按 M
```

### 血的教训（2026-05-16）

**Bug #1**：`executeMove` 使用 `style.cssText += css` 不生效
- **根因**：`cssText` 的 `+=` 在浏览器中行为不一致，且无法覆盖 CSS class 样式
- **修复**：改为 `style.setProperty(prop, val, 'important')` 逐属性设置

**Bug #2**：点击「执行移动」按钮无反应
- **根因**：`handleMoveClick` 中 `e.preventDefault()` + `e.stopPropagation()` 在 UI 元素检查**之前**执行，导致确认面板按钮的 click 事件被吞掉
- **修复**：将 `preventDefault`/`stopPropagation` 移到 UI 元素白名单检查**之后**

**Bug #3**：元素朝相反方向移动
- **根因**：当元素的 `position` 为 `relative` 或 `static` 时，代码错误地生成了 `position:relative;left:Δx;top:Δy`。但 relative 的 `left/top` 是**相对于文档流原始位置的偏移量**，不是绝对坐标。`left:+Npx` 会让元素向右走，而不是向左。
- **第一次修复失败**：统一改成 `position:absolute;left:X;top:Y` 仍然不可靠，因为 deck 的 `.slide` 会 `transform: scale(...)`，且元素的 absolute 参照物（offsetParent）不一定是 `.slide`。
- **最终修复**：Move Mode 改为 **transform 视觉位移算法**：使用 `getBoundingClientRect()` 取得元素当前真实屏幕位置，用点击目标 `clientX/clientY` 计算视觉差值，再按 slide scale 反推成 `translate(tx,ty)`。这样不依赖 `relative/absolute/static`，也不依赖 offsetParent。

---

## 交互式尺寸调整模式（Size Mode — S 键）

> **解决的核心问题**：用户需要精准表达“把这个标题放大一点”“把这张图横向拉宽”“把这组卡片整体放大”等尺寸调整。禁止靠口头描述反复试；必须让用户在页面上直接选择元素并拖拽到目标大小。

### 交互流程

```
按 S 键进入 Size Mode
  ↓
┌──────────────────────────────────────────────┐
│ 顶部紫色徽章: "SIZE MODE — 按 S 退出"         │
│ 底部提示: "第 1 步：点击要调整大小的元素"       │
└──────────────────────────────────────────────┘
  ↓ 用户点击元素
┌──────────────────────────────────────────────┐
│ 元素出现尺寸控制框                            │
│ 8 个拖拽手柄：四角 + 四边                      │
│ 实时标签显示：w×h / font-size / scale          │
└──────────────────────────────────────────────┘
  ↓ 用户拖拽手柄或使用键盘微调
┌──────────────────────────────────────────────┐
│ 实时预览目标大小                              │
│ 松手后弹出确认面板                            │
│   · 元素 class / data-text-id                 │
│   · 原始尺寸 → 目标尺寸                       │
│   · 调整模式：Font / Box / Scale              │
│   · 将执行的 CSS                              │
│   · [✓ 执行调整] [✕ 取消]                    │
└──────────────────────────────────────────────┘
```

### 三种调整模式

| 模式 | 适用元素 | 应用 CSS | 说明 |
|------|----------|----------|------|
| **Font Size** | h1/h2/p/li/span/em/strong 等文本 | `font-size` + 可选 `line-height` | 用于标题、正文、列表、数字 |
| **Box Size** | img/iframe/video/canvas/.screenshot-frame | `width` / `height` / `object-fit` | 用于图片、仪表盘、截图区域 |
| **Transform Scale** | card/chart/kpi/group 等复杂容器 | `transform: scale(...)` | 用于整体放大复杂块，不拆内部布局 |

### 模式自动判断

```javascript
function inferSizeMode(el) {
  var tag = el.tagName;
  if (['H1','H2','H3','P','LI','SPAN','EM','STRONG','B'].includes(tag)) return 'font';
  if (['IMG','IFRAME','VIDEO','CANVAS'].includes(tag)) return 'box';
  if (el.className && /screenshot|iframe|visual|image|media/.test(String(el.className))) return 'box';
  return 'scale';
}
```

### 算法原则

1. **真实渲染尺寸是唯一事实来源**：使用 `getBoundingClientRect()` 读取当前视觉宽高，不能只读 CSS `width/height`。
2. **拖拽使用 client 坐标**：记录 pointerdown 的 `clientX/clientY` 和 `startRect`，pointermove 时计算真实视觉 delta。
3. **按 slide scale 反推设计尺寸**：`designDeltaX = clientDeltaX / scaleX`，`designDeltaY = clientDeltaY / scaleY`。
4. **文本优先改 font-size**：不要用 `transform: scale` 放大文字，避免字体模糊和行高错乱。
5. **图片/iframe 优先改 box size**：默认固定左上角 TL，拖右下角改变宽高；支持 `object-fit: cover/contain`。
6. **复杂容器使用 transform scale**：组合组件内部布局复杂时，不改子元素，整体 `scale()`。
7. **不要自动写死根布局**：Size Mode 的修改应尽量落在选中元素的 inline style 上，不改 `.slide`、`.grid`、`.deck` 等全局布局。

### 锚点规则

| 锚点 | 行为 | 默认场景 |
|------|------|----------|
| `TL` | 左上角固定，向右下调整 | 默认 |
| `CC` | 中心固定，向四周缩放 | 图片居中放大 |
| `TR/BL/BR` | 对角固定 | 精修边缘贴合 |

v1 默认只要求 `TL`；确认面板中可显示当前锚点。实现其它锚点时，必须明确视觉结果，不得隐式改变元素位置。

### 键盘微调

| 键 | 行为 |
|----|------|
| `←/→` | 调整宽度或 font-size |
| `↑/↓` | 调整高度或 line-height |
| `Shift` + 方向键 | 10px / 10% 大步调整 |
| `Alt` + 方向键 | 1px / 1% 精细调整 |

### Size Mode 自检清单

生成或修改 Size Mode 后，必须检查：

```
□ S 键绑定存在：key==='s'||e.key==='S'
□ 点击元素后有尺寸控制框和 8 个手柄
□ 文本元素默认 Font Size 模式，不使用 transform scale 放大文字
□ 图片/iframe 默认 Box Size 模式，调整 width/height
□ 复杂容器默认 Transform Scale 模式
□ pointermove 使用 clientX/clientY 与 getBoundingClientRect 计算 delta
□ 设计尺寸变化按 slide scale 反推：delta / scale
□ 确认面板显示原始尺寸、目标尺寸、调整模式、将执行 CSS
□ 执行前可取消，取消后恢复原始样式
□ 执行后不自动二次 toggle；如需继续调整，由用户再次按 S
```

---

## 备份与内嵌完整性（Backup & Embed Integrity）

> **硬性要求**：每次修改 HTML 前、每次生成 inline 交付物后、每次用户要求备份时，**必须**执行完整备份。备份不全是致命错误——会导致用户拿到无法打开的文件。

### 血的教训（2026-05-16 同仁堂项目）

**事故经过**：
1. 用户要求备份当前版本
2. Agent 只拷贝了 `index.html` 和 `index-inline.html` 到 `backup-<ts>/`
3. `trial_week_dashboard.html`（被 iframe src 引用的外部页面）**未包含在备份中**
4. 用户直接双击打开 `backup-<ts>/index-inline.html` → iframe 显示空白 + "文件可能已被移除/重命名"
5. 根因有两层：① 备份不完整 ② `inline-assets.py` 不处理 iframe 引用

**修复方案**：
- 补全备份目录
- 将 `<iframe src="...">` 改为 `<iframe srcdoc="...">`，把外部 HTML 内容内嵌进 iframe 标签

### 1. 标准备份脚本

**每次执行以下任一操作前，必须先运行备份**：

```bash
# 标准完整备份脚本（必须使用此格式，禁止 ad-hoc cp）
TS=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="output/backup-${TS}"
mkdir -p "$BACKUP_DIR"

# Step 1: 备份核心文件
cp output/index.html "$BACKUP_DIR/"
cp output/index-inline.html "$BACKUP_DIR/" 2>/dev/null

# Step 2: 扫描并备份所有被引用的外部文件
#   - iframe src 引用的 HTML（注意：srcdoc 已转换的不会匹配）
#   - <img> / CSS url() / JS src 引用的本地文件
#   使用 grep -E 兼容 macOS/Linux（不用 grep -P）
grep -oE 'src=["\x27]([^"\x27]+\.(html?|css|js|png|jpg|svg|gif|woff2?))["\x27]' output/index.html | \
  sed 's/src=["\x27]//;s/["\x27]$//' | sort -u | \
  while read ref; do
    if [ -f "output/$ref" ]; then
      cp "output/$ref" "$BACKUP_DIR/"
      echo "  ✅ $ref"
    fi
  done

# Step 3: 备份 assets 目录（如存在）
if [ -d "output/assets" ]; then
  cp -r output/assets "$BACKUP_DIR/assets"
fi

echo "✅ 完整备份 → $BACKUP_DIR"
ls -lh "$BACKUP_DIR/"
```

**触发备份的场景**（满足任一即触发）：

| 场景 | 说明 |
|------|------|
| 用户明确要求「备份当前版本」 | 立即执行 |
| 即将进行结构性 DOM 修改 | 修改前先备份 |
| 即将运行 inline-assets.py | 生成新 inline 前先备份 |
| 连续修改超过 3 轮 | 自动创建检查点备份 |

### 2. iframe 内嵌规范（srcdoc 替代 src）

#### 问题

HTML 中如果使用了 `<iframe src="dashboard.html">`：
- **linked 模式**（通过 HTTP server 打开）：✅ 正常加载
- **inline 模式**（双击 file:// 直接打开）：❌ 找不到相对路径文件
- **备份恢复**：如果 dashboard.html 未一起备份 → ❌ 空白

`inline-assets.py` **不会处理** iframe 的 src 属性引用。

#### 解决方案

**所有 iframe 必须使用 `srcdoc` 属性替代 `src`**：

```html
<!-- ❌ 错误：依赖外部文件 -->
<iframe src="trial_week_dashboard.html" loading="lazy"></iframe>

<!-- ✅ 正确：内容完全内嵌 -->
<iframe srcdoc="&lt;section class=&quot;trial-dashboard&quot;&gt;
  ...完整的 dashboard HTML 内容...
&lt;/section&gt;" loading="lazy" sandbox="allow-scripts allow-same-origin"></iframe>
```

#### 自动转换方法

在运行 `inline-assets.py` **之前**，先扫描并转换所有 iframe：

```bash
# 自动将所有 <iframe src="xxx.html"> 转为 srcdoc 内嵌
python3 -c "
import os, html as h

output_dir = 'output'
source_file = os.path.join(output_dir, 'index.html')

with open(source_file, 'r', encoding='utf-8') as f:
    content = f.read()

import re
iframes = re.findall(r'<iframe\s+src=[\"\']([^\"\']+)[\"\']', content)
changed = False
for src in iframes:
    if not src.startswith('http') and not src.startswith('data:'):
        ref_path = os.path.join(output_dir, src)
        if os.path.exists(ref_path):
            with open(ref_path, 'r', encoding='utf-8') as rf:
                embed = rf.read()
            escaped = embed.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('\"','&quot;')
            old_tag = f'<iframe src=\"{src}\"'
            new_tag = f'<iframe srcdoc=\"{escaped}\" sandbox=\"allow-scripts allow-same-origin\"'
            content = content.replace(old_tag, new_tag)
            changed = True
            print(f'  ✅ {src} → srcdoc 内嵌 ({len(embed)} bytes)')

if changed:
    with open(source_file, 'w', encoding='utf-8') as f:
        f.write(content)
    print('✅ index.html 已更新：所有本地 iframe 已转为 srcdoc')
else:
    print('ℹ️ 无需转换的 iframe')
"
```

#### sandbox 安全策略

使用 srcdoc 时必须添加 `sandbox` 属性：

| 值 | 含义 |
|---|------|
| `allow-scripts` | 允许执行 JS（ECharts 渲染需要） |
| `allow-same-origin` | 允许访问父页面的 cookie/storage（跨域通信需要） |
| 不加 `allow-popups` | 阻止弹窗 |
| 不加 `allow-forms` | 阻止表单提交 |

### 3. 自包含交付物完整性检查清单

生成 `index-inline.html` 后，**必须**验证以下项：

```
□ 双击 index-inline.html 可以直接打开（无需 server）
□ 所有图片正常显示（非裂图）
□ 所有 CSS 样式生效（字体/颜色/布局正确）
□ 所有 iframe 内容可见（非空白/非报错）
□ .wordmark Logo 正常显示（彩色花瓣+文字）
□ Debug 模式（D 键）可切换
□ Ruler 模式（R 键）可切换
□ Inspect 模式（I 键）可切换（如有注入）
□ Move Mode（M 键）可切换，点击元素→点击目标→执行移动方向正确
□ Size Mode（S 键）可切换，点击元素→拖拽手柄→确认调整可执行
□ 文件大小合理（通常 100KB ~ 500KB；超过 1MB 检查是否有大图未压缩）
```

### 4. 失效场景速查

| 场景 | 症状 | 原因 | 修复 |
|------|------|------|------|
| iframe 显示空白 | 「该文件可能已被移除/重命名」 | 外部 HTML 未随主文件分发 | 用 srcdoc 内嵌 |
| iframe 显示空白 | 无报错但内容为空 | srcdoc 内容为空或转义错误 | 检查转义逻辑 |
| 图片显示裂图 | 小图标/占位符 | 图片未被 inline-assets.py 内联 | 手动 base64 或确认 assets 存在 |
| Logo 不显示 | 只看到文字「飞书」 | lark-logo.png 未复制到 assets/ | 执行 T2.4 资产复制 |
| ECharts 图表不渲染 | 卡片有数据但无图表 | CDN 被阻止（离线环境） | 下载 echarts.min.js 并内嵌为 base64 |

---

## 修改流程（Stage 5）

当用户要求修改已交付的 deck 时，**必须**按以下流程执行，禁止直接编辑 inline HTML。

### 文件地址约定

每次修改完成后，以下 2 个位置会同步更新：

| 文件 | 路径 | 说明 |
|---|---|---|
| **linked 源文件** | `deck-design/deck-pipeline/runs/<run>/output/index.html` | 所有修改的目标，19KB，需 assets/ 目录 |
| **inline 交付物** | `deck-design/deck-pipeline/runs/<run>/output/lark-<name>-<date>.html` | 自动生成，~1MB，可直接打开 |

当前 run 目录：`deck-design/deck-pipeline/runs/20260516-171140-xiaofei-luindou/output/`

**修改只改 linked 源文件**，inline 交付物由 Step 5-7 自动同步。禁止向项目根目录写副本。

### 核心原则

0. **🔴 修改前必须完整备份**（运行「备份与内嵌完整性」§1 脚本），禁止无备份直接修改
1. **永远修改 linked 版（index.html）**，不修改 inline 版
2. **用 deck-edit.py 精准定位**，不手动搜索替换
3. **修改后自动重新生成 inline 版**（先跑 iframe srcdoc 转换再跑 inline-assets.py），确保交付物同步
4. **每次修改前先 --dry-run 确认**，修改后 --list 验证
5. **修改完成后自动打开浏览器预览**，无需用户主动要求
6. **视觉修改必须真实渲染验证**：涉及 `transform`、尺寸、显隐、动画、布局、字体、元素删除或 `deck-edits-*.json` 补丁时，必须用最终 inline HTML 路径截图或读取 computed style 后再交付

### 修改交互模式

用户说"把第 X 页的 Y 改成 Z"时，agent 的执行步骤：

```
Step 1: 定位字段
    python3 deck-edit.py index.html --list | grep "slide-XX"

Step 2: 预览修改（dry-run）
    python3 deck-edit.py index.html --set slide-XX.field "新值" --dry-run

Step 3: 确认后执行
    python3 deck-edit.py index.html --set slide-XX.field "新值"

Step 4: 同步 texts.md
    python3 extract-texts.py index.html --out texts.md

Step 5: iframe srcdoc 转换 + 重新生成 inline 版
    # 先转换所有本地 iframe src 为 srcdoc（见「备份与内嵌完整性」§2）
    python3 -c "..."  (iframe 转换脚本)
    python3 inline-assets.py index.html --out lark-<name>-<date>.html

Step 6: 交付物完整性验证（按 §3 检查清单逐项确认）

Step 7: 对最终 inline HTML 执行真实浏览器渲染验证
    # 生成 render-check-*.png，必要时读取关键元素 computed style
    # 若源码已变但视觉未变，按 T3.4 CSS 级联排查顺序处理
    open lark-<name>-<date>.html
Step 8: 自动打开浏览器预览（无需用户要求）
    open lark-<name>-<date>.html


### 支持的修改类型

| 修改类型 | 工具 | 示例 |
|---|---|---|
| 改某个字段的文字 | `deck-edit.py --set` | `--set slide-04.title "新标题"` |
| 全局替换某个词 | `deck-edit.py --replace` | `--replace "飞书AI录音豆" "飞书妙记"` |
| 批量修改多个字段 | `deck-edit.py --batch` | `--batch edits.json` |
| 删除某个元素 | 直接编辑 HTML | 删除对应的 `<div class="slide-frame">` 块 |
| 换图片 | 替换文件 + 更新 src | 替换 `input/` 下的图片文件 |
| 改布局/样式 | 直接编辑 HTML | 修改 data-layout / data-accent 属性 |

### 批量编辑 JSON 格式

```json
[
  {"id": "slide-04.title", "value": "新标题"},
  {"id": "slide-08.card1-body", "value": "新内容"},
  {"find": "飞书AI录音豆", "replace": "飞书妙记"}
]
```

### 修改确认话术

```
🔧 修改确认
· 修改类型：{单字段/全局替换/批量}
· 影响范围：{slide-XX.field / N 处匹配}
· 修改内容：
  - 旧值：{old}
  + 新值：{new}
请确认：
```

### 结构性修改（图片/布局/排版/增删页）

结构性修改使用 `deck-manage.py`，支持以下操作：

| 修改类型 | 命令 | 示例 |
|---|---|---|
| 查看概览 | `--info` | `deck-manage.py index.html --info` |
| 查看单页 | `--slide N --info` | `deck-manage.py index.html --slide 4 --info` |
| 换图片 | `--replace-img` | `--replace-img input/old.jpeg input/new.jpeg` |
| 改 accent 颜色 | `--slide N --accent` | `--slide 4 --accent teal` |
| 改 decor 装饰 | `--slide N --decor` | `--slide 4 --decor aurora` |
| 改 layout 布局 | `--slide N --layout` | `--slide 4 --layout content-2col` |
| 插入新页 | `--add-slide` | `--add-slide 5 section --key "section-new" --accent teal` |
| 删除页 | `--remove-slide` | `--remove-slide 5` |
| 复制页 | `--duplicate-slide` | `--duplicate-slide 4` |
| 移动页 | `--move-slide` | `--move-slide 10 5` |
| 批量操作 | `--apply` | `--apply edits.yaml` |

### 结构性修改交互流程

用户说"把第4页的颜色改成绿色"或"在第5页后面加一页"时：

```
Step 1: 查看当前状态
    deck-manage.py index.html --info

Step 2: 预览修改（dry-run）
    deck-manage.py index.html --slide 4 --accent teal --dry-run

Step 3: 🛑 确认修改
    🔧 修改确认
    · 修改类型：accent 颜色
    · 影响范围：Slide 04 (pain-points)
    · 修改内容：blue → teal
    请确认：

Step 4: 执行修改
    deck-manage.py index.html --slide 4 --accent teal

Step 5: iframe srcdoc 转换 + 重新生成 inline 版
    # 先转换所有本地 iframe src 为 srcdoc
    python3 -c "..."  (iframe 转换脚本)
    inline-assets.py index.html --out lark-<name>-<date>.html

Step 6: 交付物完整性验证（按 §3 检查清单逐项确认）

Step 7: 对最终 inline HTML 执行真实浏览器渲染验证
    # 生成 render-check-*.png，必要时读取关键元素 computed style
    # 若源码已变但视觉未变，按 T3.4 CSS 级联排查顺序处理

Step 8: 自动打开浏览器预览（无需用户要求）
    open lark-<name>-<date>.html
```

### 可用 accent 颜色

| accent | 效果 |
|---|---|
| `blue` | 飞书主色蓝（默认） |
| `teal` | 青绿色，适合数据/技术 |
| `purple` | 紫色，适合场景/案例 |
| `green` | 绿色，适合增长/成功 |

### 可用 decor 装饰

| decor | 效果 |
|---|---|
| `none` | 无装饰（section 页默认） |
| `blue-glow` | 蓝色光晕 |
| `teal-glow` | 青绿光晕 |
| `violet-glow` | 紫色光晕 |
| `aurora` | 极光渐变 |

### 可用 layout 布局（新增页模板）

| layout | 说明 | 包含字段 |
|---|---|---|
| `section` | 章节分隔页 | title, lede |
| `content-3up` | 三卡片 | title, card1/2/3-title, card1/2/3-body |
| `content-2col` | 左文右图 | title, lede, screenshot |
| `stats` | 四格数据 | title, stat1/2/3/4-label |
| `image-text` | 左文右图 | title, lede, photo |
| `process` | 四步流程 | title, step1/2/3/4-title, step1/2/3/4-body |
| `quote` | 引用 | quote, cite |

### 批量操作 YAML 格式

```yaml
operations:
  - action: set-accent
    slide: 4
    value: teal
  - action: set-decor
    slide: 4
    value: teal-glow
  - action: replace-img
    old: input/old.jpeg
    new: input/new.jpeg
  - action: add-slide
    position: 5
    layout: section
    key: section-new
    accent: purple
  - action: move-slide
    from: 10
    to: 5
  - action: remove-slide
    slide: 15
```

### 结构性修改确认话术

```
🔧 结构修改确认
· 修改类型：{accent/decor/layout/图片/增删页/移动}
· 影响范围：Slide {N} ({key})
· 修改前：{旧值}
· 修改后：{新值}
· 是否需要重新生成 inline 版：是
请确认：
```

### 截图驱动修改模式

用户可以直接发送截图 + 修改指令，agent 通过视觉识别定位目标元素并精准修改。

#### 交互流程

```
用户发送截图 + "把这个标题改成XXX"
    ↓
Step 1: 视觉识别 — 从截图中识别 slide 编号和目标元素
    · 匹配文字内容 → 定位 slide 编号
    · 匹配布局/颜色 → 确认 layout/accent
    · 匹配位置 → 定位 data-text-id
    ↓
Step 2: 精准定位 — 用 deck-edit.py --list 确认字段
    ↓
Step 3: 🛑 确认修改（同文字/结构修改流程）
    ↓
Step 4-7: 执行修改 → 重新生成 inline → 自动打开浏览器 → 同步
```

#### Debug 标注模式（辅助截图定位）

在浏览器中按 **D 键** 切换 Debug 标注模式：
- 每个可编辑文字元素显示蓝色标签（data-text-id）
- 每个图片元素显示橙色标签
- 每个 slide 左上角显示绿色标签（slide-key + layout + accent）
- 右上角显示 "DEBUG MODE" 徽章

**推荐操作**：用户先按 D 开启标注模式 → 截图 → 发送截图 + 指令 → agent 直接读取标签精准定位

#### 截图指令示例

| 用户发送 | agent 识别 | 执行命令 |
|---|---|---|
| 截图 + "标题改成XXX" | 读取蓝色标签 `slide-04.title` | `deck-edit.py --set slide-04.title "XXX"` |
| 截图 + "颜色改成绿色" | 读取绿色标签 `key=pain-points, accent=blue` | `deck-manage.py --slide 4 --accent teal` |
| 截图 + "换张图" | 读取橙色标签 `slide-06.screenshot` | `deck-manage.py --replace-img old new` |
| 截图 + "删掉这页" | 读取绿色标签确认 slide 编号 | `deck-manage.py --remove-slide N` |
| 截图 + "这页太挤了" | 读取绿色标签 `layout=content-3up` | `deck-manage.py --slide N --layout content-2col` |

#### slide-map.md（机器可读的 slide 索引）

每次生成 deck 后自动生成 `slide-map.md`，包含每页的 key/layout/accent/text_ids/images。
当截图无法精确识别时，agent 可结合 slide-map.md 进行匹配。

---

## Files in this skill

```
deck-pipeline/
├── SKILL.md              ← 本文件
└── assets/
    └── pipeline.yaml     ← 流水线定义（机器可读）
```
