# feishu-deck-h5 · 业务规则审阅文档

本文是为**人工技能评审**准备的业务视角索引——把技能里所有强制规则、设计约束、行为边界汇总到一处，方便快速判断"技能在做什么、不做什么、为什么这么定"。

完整源在 `skills/feishu-deck-h5/SKILL.md`（3800+ 行）和 `DESIGN.md`（9-section 设计系统）；本文不替代它们，只做业务摘要。

---

## 1. 技能定位

**一句话**：把"飞书母版 2025（深色通用）.thmx"翻译成 HTML deck —— **不是 .pptx，是用 HTML 完整模仿 PPT 视觉**。

| 适用 | 不适用 |
|---|---|
| 需要 HTML 单文件汇报材料 | 需要 .pptx → 走 pptx 技能 |
| 视觉与飞书企业级 pitch 一致 | 想要白底 / Apple 风 / 非飞书风 |
| 同一份 deck 既做 PC 16:9 全屏，又能移动端竖滑浏览 | — |
| 内部 alignment / 客户提案 / 季度汇报 / AI 大讲堂 | — |

---

## 2. 输入 / 输出

### 输入（任一组合）
- 文本简报 / 内容大纲（必需）
- 现有 PDF / HTML / PPT export（转换场景）
- 一页纸案例的结构化 `input.toml`
- 案例配图（`scene.png`，可选）

### 输出（落到 `runs/<ts>/output/`）
```
runs/20260505-180000/output/
├── index.html          ← deck（默认 linked ~24KB，--inline 单文件 ~360KB）
├── texts.md            ← 文本编辑 sidecar（每个 text leaf 都有 data-text-id）
├── FEEDBACK.md         ← 这次 build 的关键决策清单（人机闭环）
└── deck-editable.zip   ← Mode 2/3 远程交付时附加产出
```

---

## 3. 强制门槛（refuse-to-work gates）

技能在以下情况**必须拒绝执行**——这是审阅的核心，决定了技能"什么时候不工作"。

### A. 必须挂载本地目录（preflight）

临时 session 输出（`/sessions/.../mnt/outputs/`）会话结束就消失。技能存在的所有理由（持久 / 团队协作 / git commit / 浏览器打开）都失效。所以技能强制：用户先挂本地可写目录，否则 `assets/preflight.sh` 退出非零，**所有后续步骤都不跑**。

例外：harness（如 Mira）只读挂载技能 → 自动 rsync 镜像到 `$PWD/.feishu-deck-h5-workspace/`，但仍要落到能持久的位置。

边缘：用户机器上**两份 clone**（譬如本地一份 + Claude Code session 挂载一份）→ 技能会主动告警询问"这次产出落在哪一份"，不许默默选一份。

### B. 必须建 per-run 工作目录

preflight 通过后，第一件事是 `bash assets/new-run.sh` 创建 `runs/<timestamp>/{input,output}/`，把这次素材和产出跟其他 run 隔离。**所有写入必须落在 `runs/<ts>/output/` 下**——不能写 `~/Downloads/`、`/tmp/`、桌面，除非用户显式说"放下载目录"。

### C. 必须主动回传产出（对话模式）

对话 / chat 模式下，**每次产出（首次生成 + 每次修改）都必须**在回复结尾贴上 `runs/<ts>/output/` 下新文件的路径。"已修复"自己一句话不带路径是 bug——用户没东西可点开看。

CLI / 后台模式不需要回显。

### D. 不能编 STORY id / 数据来源 / 访谈出处 ⚠️ 重点审阅

案例 slide 的模板里有 `brand: "飞书企业 AI · 客户案例 · STORY 015"` 和 `source: "数据来源 · XX 客户访谈"` 这种字段——但这些是**示范**，不是**填写指令**。

**规则**：
- 用户没给 story id → brand 就只写 `"飞书企业 AI · 客户案例"`，**不要补 STORY 0NN**
- 用户没给数据来源 → `source` 留空，对应 `.case-caption / .source-footer` 整段不渲染
- **不允许**写 `"客户访谈" / "内部口径" / "实践访谈" / "调研口径"` 这类托词——这些会被读者当作事实声明，造假被发现破信任
- 引语下的 `<div class="attrib">` 和 stats 下的 `Source · ...` 同规则

不确定就问，"一次问比假数据上客户面前划算"。这条规则是已发生过的事故倒推出来的硬规则。

### E. 默认中文，不双语

用户用中文写 prompt → slide 文本**单语中文**。**绝不**在每行中文下面叠英文翻译（"即时同步 / Instant sync" 这种）。

仅当用户显式说"做一份双语 deck" / "面向英文客户" / "ZH+EN bilingual" 时才开启双语。

例外保留原文（不翻译）：品牌名（Lark, Base, Wiki, Meetings）、产品代号、单位（px, %）、固定术语（KPI, ROI, OKR, agent, demo）。

---

## 4. 三种交付模式

| 模式 | 场景 | 产出 | 用户需要 |
|---|---|---|---|
| **Mode 1 · Local** | 默认，Claude Code 本机 | `runs/<ts>/output/index.html` | 浏览器双击即可 |
| **Mode 2 · Remote zip** | OpenClaw / 沙箱 / Feishu bot | `deck-editable.zip` | 本机 `python3`（Mac 自带，Win 一次性安装），双击 `apply.command` / `apply.bat` 即可改文字 |
| **Mode 3 · View-only** | "客户/老板看一眼就行"，不需编辑 | `--inline` 单文件 HTML，无 texts.md / 无脚本 | 浏览器打开 |

**默认 Mode 2（带 edit kit）**，除非用户显式说 "final 版不再改" 或 "只给客户看"。

---

## 5. 设计约束（design floor，硬规则）

| 项 | 规则 | 自检编号 |
|---|---|---|
| 画布 | 每张 slide 1920×1080，运行时 scale | 必填 `data-screen-label`（#2） |
| 主题 | 深色 cinematic 背景。**禁止**白底 / cream / Apple 风 | brand floor |
| 调色 | 仅 `--fs-*` 设计令牌，不允许自定义 hex | R10 / #10 |
| Accent | 每页**仅一个** brand accent（蓝/橙/紫/teal）。Cyan **仅作行内文字高亮**，不能整页 accent | R49 / #49 |
| Logo | 彩色 logo 默认每页（封面/封底左上，内容页右上）。Mono 是 opt-in 边缘 case | L1 / #7, #42 |
| 标题 | 内容页 H2 **单行**，`<br>` 禁止。Hero 双行只在 cover / image-text / end | R02 / #13 |
| 字号下限 | 正文 ≥22px on canvas，chrome ≥14px | #6 |
| 中英标点 | CJK 全角，EN ASCII，**不能混** | #11 |
| 内容页 header | 仅一个 `<h2>`，没 eyebrow / 副标题 / inline page-no（2026-05 之后页码统一由 pager UI 显示） | R56 / #56 |
| 字符 | 不允许 emoji / `!` / `…` / `???` | #5 |

---

## 6. 13 个 layouts（不能发明第 14 个）

| layout | 用途 | 飞书母版对应 |
|---|---|---|
| `cover` | 封面（花朵背景 + 左半文字） | slideLayout1 |
| `agenda` | 议程 | — |
| `section` | 章节扉页（大序号） | slideLayout3 |
| `content-3up` | 三卡并列 | — |
| `content-2col` | 文字 + 视觉双栏 | — |
| `quote` | 金句 | — |
| `stats` | 4 项 KPI | — |
| `big-stat` | 单大数字 | — |
| `image-text` | 全屏图 + 文字 | — |
| `table` | 对比表格 | — |
| `timeline` | 横向时间轴 | — |
| `process` | 步骤流程 | — |
| `end` | 封底带 slogan | slideLayout8 |

外加 11 个叙事模式（A–M）和 27 个 `.ui-*` UI 原语，详见 SKILL.md。

**转 PDF/PPT 进来时**：每页源材料必须映射到这 13 个之一，不能创新一个 14。

---

## 7. 一页纸案例（强约束 ⚠️ 重点审阅）

技能里**最强的硬规则之一**。

### 触发条件
用户说"一页纸案例 / one-pager case / 做成一页 / 压成一页"，或递一行案例库的数据 + "做成 deck / 试试效果 / 把这一行做出来"。

### 强约束
- **跳过封面页**——一页纸案例不该有 cover（封面 + 内容 = 浪费一页）。配图直接在内容 slide 的右栏作为 hero 视觉。
- **结构必须是 4-beat**：痛点（蓝）→ 冲突（橙）→ 解法（teal）→ 价值（紫）。这套色彩语言是固定的。
- **图文比例**：左文右图 1 : 1.3，magazine-spread 风格，配图 v2 高度等于文字列高度（v0 太小、v1 太大，2026-05-03 frozen）。
- **多案例 bundle 不在此约束内**——3+ 个案例的 deck 走标准 cover + agenda + section + content 流程。

### 两条渲染路径

| 路径 | 命令 | 何时用 | 成本 |
|---|---|---|---|
| **A · Template** | `python3 assets/render.py one-pager input.toml output/` | 案例 fits 4-beat schema 干净（80% 场景） | 0 token，0.5s，验证保证通过 |
| **B · LLM authoring** | agent 手写 HTML/CSS | 案例不 fit 模板，或有更好的视觉处理 | ~30-60s，~70K tokens |

### Path A 的两个安全网（自动跑）

1. **Schema-fit refusal（exit 4）**：每个 beat 扫占位词（TBD/占位/未填等）+ 长度下限 + 内容重复，不通过就拒绝渲染——逼 agent 切 Path B 或回去重抽 TOML，不让"模板填半成品"出门
2. **Accent boundary review**：渲染后高亮显示每个 accent 词，让 agent 1 秒目测"高亮的词是该突出的吗？"——抓 LLM 把高亮放错位置的常见 bug

### Path B 的"品牌底线"

可以破 layout shape，但**不能破**：
- 深色背景（`lark-content-bg.jpg` 或品牌 decor token）
- `--fs-*` 调色板，没有 off-palette
- 飞书 wordmark 在位
- 1920×1080 画布
- 默认中文不双语
- validator 所有规则（L1-L4, R02-R56, P50-P55, UI1, T01-T03）必须 strict pass

Path B **不是**"加个性化字体颜色"的口子，是"故事真不 fit 模板"的口子。

---

## 8. 文本编辑回路（texts.md sidecar）

**问题**：deck 是 1500+ 行 HTML，用户找一句改字像大海捞针。

**方案**：
- 每个 text leaf 都打 `data-text-id="slide-NN.field"`
- 同时输出 `texts.md`（结构 `## slide-NN ...\n- field: 文字`）
- 用户在 texts.md 里改文字，跑 `python3 assets/apply-texts.py output/index.html output/texts.md` patch 回 HTML
- CSS / 布局 / SVG / 装饰 **字节级保留**，先备份 `.bak`

**强约束**：
- 每个 text leaf **必须**有 `data-text-id`，slide 顺序 NN 跨重生稳定
- 必须输出 `texts.md`，没有就是技能 bug
- 占位符（`{{var}}`）+ inline `<br>` **不打** ID（避免冲突）
- 装饰 / SVG / 图标 **不打** ID

---

## 9. 反馈闭环（FEEDBACK.md）

每次成功 build **必须**产出 `FEEDBACK.md`——**不是空白模板**，是 agent 自动记录这次 run 真实做出的判断 / 取舍 / 妥协。

### 必填 4 类内容
1. **Header**：run 时间戳 + 一句话说做了什么
2. **关键决策（自动检测）**：每个非平凡选择都列一条，含「做了什么 / 为什么 / `你的看法:` 复选框」
   - 例："标题从 22 字压到 17 字以单行容纳"
   - 例："图片列从 1fr 1fr 改到 1fr 1.3fr"
   - 例："把 '#001' 改成 'STORY 001' 因为 R10 误判 hex"
3. **本次没解决的小毛病**（如果有）：validator 警告但 agent 没改的
4. **你的额外建议**：留几个空 bullet 给用户填

### 末尾固定语
> 累计 ≥3 条值得反馈的（打钩 / 备注 / 自填），把这个文件发给 skill 维护者整合到下一版.

### 禁止
- ❌ 通用 checklist（"layout 对吗 / 字号对吗"）—— 没上下文等于没问
- ❌ 重复 validator 的 PASS 报告
- ❌ "看起来很棒"这种夸奖
- ❌ 硬编码维护者邮箱（不同 install 不同维护者）

---

## 10. 自检 59 项（validate.py 自动跑 ~12 项）

完整列表在 SKILL.md "Self-check" 章节。分类摘要：

| 分类 | 编号区间 | 关键项 |
|---|---|---|
| Brand & content | 1-12 | 每页一个 accent / no emoji / 字号下限 / 调色板锁定 |
| Title & header alignment | 13-15 | H2 单行 / 与 logo 同基线 |
| Layout-specific sizes | 16-20 | agenda 字号一致 / 卡片标题 ≤14 字 |
| Copy & narrative | 21-24 | accent 使用约束 |
| Layout overflow & runtime | 25-28 | min-height: 0 / nowrap 默认 |
| Present-mode chrome | 29-32 | 顶部进度条 / 底部 pager / 全屏行为 |
| Fullscreen scale & chrome | 33-36 | 不裁切 / 首帧正确 / 闲置淡出 |
| Atmospheric preservation | 37-39 | data-decor 不丢 / 无副作用 |
| **Hard gate** | **40-41** | **`validate.py` exit 0 + `--strict` exit 0** |
| Layout integrity L1-L4 | 42-45 | 默认彩色 logo / 不允许顶部空白 / margin-top:auto bug 防御 |
| UI mocks | 46 | 系统 UI 必须 HTML 重建，不能贴 PNG |
| Variant discipline | 47 | 重声明所有结构属性 |
| Default centering | 48 | 固定形状 layout 默认垂直居中 |
| Cyan-as-slide-accent forbidden | 49 | data-accent="cyan" 整页禁止 |
| Performance budget | 50-55 | 见下表 |
| Content-page header minimalism | 56 | 内容页 header 仅一个 H2 |
| Conversion compliance | 57-58 | 转换时映射到 13 个 layout / 剥离源专属噪声 |
| Local-mount preflight | 59 | preflight.sh exit 0 |

---

## 11. 性能预算（P50-P55，硬规则）

| 项 | 规则 |
|---|---|
| **P50** | base64 内嵌到 `<style>` 默认 ≤100KB（硬上限 250KB）。inlined 模式必须声明 `<meta name="fs-deck-mode" content="inline">` 跳过此检查 |
| **P51** | `backdrop-filter` blur 半径 ≤10px（GPU 成本随半径增长） |
| **P52** | `new ResizeObserver()` 仅 1 个实例（多了警告） |
| **P53** | `addEventListener` 数 ≥8 必须用 `AbortController` 管理生命周期 |
| **P54** | `.slide-frame` 必须声明 `contain: layout paint size`（局部重绘） |
| **P55** | `.slide-frame .slide` 必须声明 `will-change: transform` + `translateZ(0)`（GPU 层） |

---

## 12. 已知限制 / 已退役机制

- **`.source-footer` / `.footer` / inline page-no 已 2026-05 退役**：旧 deck 可能还有，新生成的不该再加。页码统一由 present-mode pager UI 显示。
- **`<img>` 在 slide 内容里禁用**：UI 截图必须用 `.ui-*` 原语 HTML 重建（满足 UI1）。真实照片走 `data-decor="photo-bg"` + CSS 变量。
- **brand assets `lark-*.png/jpg` 不在 MIT 协议内**：仓库公开化前必须移除或替换。
- **Cyan #24C3FF 不能做整页 accent**：仅作行内字高亮（`.accent-text` / `.hl`）。

---

## 13. 评审建议清单

审阅时建议重点关注：

### A. 强制门槛是否合理
- [ ] preflight 拒绝执行的边界——是否有客户场景被错杀？
- [ ] "必须建 per-run 工作目录"——单次 quick fix 也要建吗？开销值得吗？
- [ ] hand-back 规则——技能在不该回显路径的场景是否会乱回显？

### B. "不编 STORY/数据来源" 这条
- [ ] 团队过去有过"模板字段当占位填"的事故吗？这条规则是补救已发生的错？
- [ ] `brand` / `source` 字段在 input.toml 里被标为 OPTIONAL 是否够明显？
- [ ] agent 在不确定时是否真的会 ask（不是默默填）？
- [ ] `client-shareable` 默认值 vs `internal` 的边界是否清楚？

### C. 中文优先
- [ ] 团队的客户/上游有英文场景吗？双语开关够好用吗？
- [ ] 是否会被"留原文术语"规则误伤（比如 KPI/ROI 列表是否会过度膨胀）？

### D. 一页纸案例的 4-beat
- [ ] 痛点/冲突/解法/价值 这套结构能覆盖你团队 80% 的案例吗？
- [ ] Path A → Path B 的退避是否有遗漏？
- [ ] Path B 的"品牌底线"是否真的够硬？被破过吗？
- [ ] Schema-fit refusal 的占位词清单（TBD/TODO/占位等）够全吗？

### E. 整体态度
- [ ] 技能拒绝行为（refuse to work）是否过度——容易让用户觉得"调用麻烦"？
- [ ] SKILL.md 3800+ 行，agent 真的能记全吗？哪些规则最容易被遗忘？
- [ ] FEEDBACK.md 设计能产生有用的迭代信号吗？还是会变成另一份没人看的产物？
- [ ] 13 layout 的硬限制，是否在某些场景下太死板？有没有该加 14 的真实需求？
- [ ] 性能预算 P50-P55 是否真的有用户能感知的差异？还是过度工程？

---

## 完整规范引用

- `skills/feishu-deck-h5/SKILL.md` —— 3800+ 行，技能实操细则
- `DESIGN.md` —— 9-section 设计系统（颜色/字体/组件/布局/响应/品牌等）
- `skills/feishu-deck-h5/assets/validate.py` —— 20 个 audit/check 函数
- `skills/feishu-deck-h5/templates/` —— 4 个 Layer 1 模板（one-pager / quote / big-stat / multi-case-bundle）
- `skills/feishu-deck-h5/examples/` —— 完整可运行样例
