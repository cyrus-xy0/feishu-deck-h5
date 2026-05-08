# feishu-deck-h5 · 业务规则审阅文档

本文是为**人工技能评审**准备的业务视角索引——把技能里所有强制规则、设计约束、行为边界汇总到一处,方便快速判断"技能在做什么、不做什么、为什么这么定"。

完整源在 `skills/feishu-deck-h5/SKILL.md`(~4900 行)和 `DESIGN.md`(9-section 设计系统);本文不替代它们,只做业务摘要。

> **2026-05-08 重写**:覆盖到 commit `27252f9`。新增资产库 / 转换三模式 / R-LANG / R-KEY / finalize.sh 一条龙,SKILL.md 自检章节由 200 行压成 ~50 行,~280 行文档瘦身。

---

## 1. 技能定位

**一句话**:把"飞书母版 2025(深色通用).thmx"翻译成 HTML deck —— **不是 .pptx,是用 HTML 完整模仿 PPT 视觉**。

| 适用 | 不适用 |
|---|---|
| 需要 HTML 单文件汇报材料 | 需要 .pptx → 走 pptx 技能 |
| 视觉与飞书企业级 pitch 一致 | 想要白底 / Apple 风 / 非飞书风 |
| PC 16:9 全屏 + 移动端竖滑浏览同一份 deck | — |
| 内部 alignment / 客户提案 / 季度汇报 / AI 大讲堂 | — |
| 想把现有 PDF / PPT 1:1 翻成 HTML 重新分发 | — |

---

## 2. 输入 / 输出

### 输入(任一组合)
- 文本简报 / 内容大纲(必需)
- 现有 PDF / HTML / PPT export(转换场景,见第 8 节)
- 一页纸案例的结构化 `input.toml`
- 案例配图(`scene.png`,可选)
- 客户 / 资本机构 / 飞书产品图标 → 自动从内置资产库匹配(见第 10 节)

### 输出(落到 `runs/<ts>/output/`)
```
runs/20260508-180000/output/
├── index.html          ← deck(默认 linked ~24 KB,--inline 单文件 ~360 KB)
├── texts.md            ← 文本编辑 sidecar(每个 text leaf 都有 data-text-id)
├── FEEDBACK.md         ← 这次 build 的关键决策清单(人机闭环)
├── assets/             ← 自包含资源(logo / 头像 / 截图)
└── deck-editable.zip   ← Mode 2/3 远程交付时附加产出
```

---

## 3. 强制门槛(refuse-to-work gates)

技能在以下情况**必须拒绝执行**——这是审阅的核心,决定了技能"什么时候不工作"。

### A. 必须挂载本地目录(preflight)

临时 session 输出会话结束就消失,持续性 / 团队协作 / git commit / 浏览器打开全失效。技能强制:用户先挂本地可写目录,否则 `assets/preflight.sh` 退出非零,**所有后续步骤都不跑**。

边缘:用户机器上**两份 clone**(本地一份 + Claude Code session 挂载一份)→ 技能会主动告警询问"这次产出落在哪一份",不许默默选一份。

### B. 必须建 per-run 工作目录

preflight 通过后,第一件事是 `bash assets/new-run.sh` 创建 `runs/<timestamp>/{input,output}/`。**所有写入必须落在 `runs/<ts>/output/` 下**——不能写 `~/Downloads/`、`/tmp/`、桌面,除非用户显式说"放下载目录"。

### C. 必须主动回传产出(对话模式)

对话 / chat 模式下,**每次产出(首次生成 + 每次修改)都必须**在回复结尾贴上 `runs/<ts>/output/` 下新文件的路径。"已修复"自己一句话不带路径是 bug。CLI / 后台模式不需要回显。

### D. 不能编 STORY id / 数据来源 / 访谈出处 ⚠️ 重点审阅

案例 slide 的模板里有 `brand: "飞书企业 AI · 客户案例 · STORY 015"` 和 `source: "数据来源 · XX 客户访谈"` 这种字段——但这些是**示范**,不是**填写指令**。

规则:
- 用户没给 story id → brand 就只写 `"飞书企业 AI · 客户案例"`,**不要补 STORY 0NN**
- 用户没给数据来源 → `source` 留空,对应字幕段不渲染
- **不允许**写"客户访谈 / 内部口径 / 实践访谈 / 调研口径"等托词,会被读者当作事实声明,造假被发现破信任
- 引语下的 `<div class="attrib">` 和 stats 下的 `Source · ...` 同规则

不确定就问。"一次问比假数据上客户面前划算"。这条规则是已发生过的事故倒推出来的硬规则。

### E. 默认中文不双语(R-LANG validator 强制)

deck 在 `<head>` 必须声明语言模式:

```html
<meta name="fs-language" content="zh-only">   <!-- 默认 -->
<meta name="fs-language" content="zh-en">     <!-- 双语 opt-in -->
```

`zh-only` 模式下 validator 会报警 `.title-en / .subtitle-en / .label-en` 这些类的使用。仅当用户显式说"做一份双语 deck / 面向英文客户 / ZH+EN bilingual"时才切换。

例外保留原文(不翻译):品牌名(Lark, Base, Wiki, Meetings)、产品代号、单位(px, %)、固定术语(KPI, ROI, OKR, agent, demo)。

### F. 信息薄时必须先确认才能补内容 ⚠️ 重点审阅

飞书 deck 的 slide **设计就是信息密集型**——空旷加 3 行字看着像没准备好。但用户给的内容常常薄(三句话简报 / 一行案例库行 / 不带 KPI 的故事),agent 这时候有三种合规反应,优先级:

1. **改用稀疏型 layout**(`quote` / `big-stat` / `cover` / `end` / `image-text`)——这些天生就是少字版式,2 行就够
2. **停下来问用户要更多上下文**——薄到任何 layout 都撑不住时的默认动作
3. **用 agent 知识库的行业 / 产品 / 同类客户故事补**——**仅在用户明确确认后**

### 强制流程

如果选择了**需要密度**的 layout(`content-2col` / `content-3up` / `stats` / `table` / `timeline` / `process`)且检测到信息薄,agent **必须**:

1. 停在生成前
2. 告知:这个 layout 期望 X,你给的是 Y,直接出图会显得空
3. 提 2-3 个具体补充选项(行业基准 / 产品能力 / 同类客户故事 / 邻接 KPI),每个一句话
4. 等用户选:补哪一项 / 不补直接出 / 改 layout / 让我再补背景

只有用户**明确点头**才补。

### 补内容时的提示框

> "结合输入的信息,如果画一页专业的 PPT,请帮我设计对应的内容,要专业风格的。"

把用户输入当 SEED,按"高级决策者会真读的咨询/战略 deck"的密度去设计——具体数字、具体能力、具体案例、邻接客户名,而不是营销文案或创意写作。

### 边界(即便用户确认也不允许)

- 把具体数字归到具体公司(用户没给的)
- 把引语归到具名人(用户没提供的)
- "客户访谈 / 内部口径"这类来源标注(归 D 条)
- 未来产品 roadmap 声明

简言之:**augmentation 是公开的行业 / 产品知识 + tag 清楚来源,绝不是把虚构事实归到具体实体。**

这条规则和 D 是同一颗北极星:**deck 不能默默编出汇报人在客户面前 defend 不了的内容**。

### G. 每张 slide 必须有唯一语义 key(R-KEY validator 强制,新)

每个 `<div class="slide">` 必须带 `data-slide-key="<语义 slug>"`:

```html
<div class="slide" data-layout="big-stat"
     data-screen-label="08 ARR History"
     data-slide-key="arr-history">
```

规则:
- kebab-case,正则 `^[a-z0-9][a-z0-9-]*$`
- deck 内唯一(重复 → error)
- **语义** slug,不是位置编号:`arr-history` ✓ / `slide-08` ✗(警告)
- 跨 slide 重排稳定:从第 7 页移到第 3 页,key 不变

下游消费者:**`feishu-slide-library`** 把渲染好的 deck 拆成可复用素材库,locator 用这个 key 锚定。**没 key → 入库失败**。

---

## 4. 三种交付模式(finalize.sh 一条命令)

新增 `bash assets/finalize.sh <output-dir> [local|remote|inline] [--strict]`,把以前要分别跑的 4 条脚本(copy-assets / extract-texts / validate / package-deliverable)串成一条。

| 模式 | 场景 | 产出 | 用户需要 |
|---|---|---|---|
| **Mode 1 · Local** | 默认,Claude Code 本机 | `runs/<ts>/output/index.html` | 浏览器双击即可 |
| **Mode 2 · Remote zip** | OpenClaw / 沙箱 / Feishu bot | `deck-editable.zip` | 本机 `python3`(Mac 自带,Win 一次性安装),双击 `apply.command` / `apply.bat` 即可改文字 |
| **Mode 3 · View-only inline** | "客户/老板看一眼就行",不需编辑 | `--inline` 单文件 HTML,无 texts.md / 无脚本 | 浏览器打开 |

**默认 Mode 2(带 edit kit)**,除非用户显式说"final 版不再改"或"只给客户看"。

`--strict` 标志将 validator 警告升级为错误——交付前用,日常迭代不用。

---

## 5. 设计底线(design floor,硬规则)

| 项 | 规则 | 自检编号 |
|---|---|---|
| 画布 | 每张 slide 1920×1080,运行时 scale | R02 |
| 主题 | 深色 cinematic 背景。**禁止**白底 / cream / Apple 风 | brand floor |
| 调色 | 仅 `--fs-*` 设计令牌,不允许自定义 hex | R10 |
| Accent | 每页**仅一个** brand accent(蓝/橙/紫/teal)。Cyan **仅作行内文字高亮**,不能整页 accent | R49 |
| Logo | 彩色 logo 默认每页(封面/封底左上,内容页右上)。Mono 是 opt-in 边缘 case | L1 |
| 标题 | 内容页 H2 **单行**,`<br>` 禁止。Hero 双行只在 cover / image-text / end | R13 |
| 字号下限 | 正文 ≥ 22 px on canvas;chrome ≥ 14 px | R06 |
| **字号梯子** | per-page `<style>` 的 `font-size` 必须从 `{10, 11, 12, 13, 14, 18, 22, 28, 38, 44, 52, 56, 64, 88, 100, 132, 160}` 里选,off-ladder 报错 | R20 |
| **正文颜色** | 深色背景上的语义文字必须 `#fff` 或 ≥ 0.95 opacity 白,半透明灰白只用于真正的 chrome / 装饰 | (审稿规则,无 audit) |
| **嵌套框** | 任一垂直方向最多 2 层"卡片边框",禁止三层嵌套 | (审稿规则) |
| 中英标点 | CJK 全角,EN ASCII,**不能混** | (审稿) |
| 内容页 header | 仅一个 `<h2>`,没 eyebrow / 副标题 / inline page-no | R56 |
| 字符 | 不允许 emoji / `!` / `…` / `???` | R05 |
| 语言模式 | `<meta name="fs-language">` 强制 | R-LANG |
| Slide 唯一编号 | `data-slide-key` 强制 | R-KEY |

---

## 6. 13 个布局 + 13 个叙事模式

### 13 个 layouts(不能发明第 14 个)

| layout | 用途 | 飞书母版对应 |
|---|---|---|
| `cover` | 封面(花朵背景 + 左半文字) | slideLayout1 |
| `agenda` | 议程(2026-05-06 重做成竖排 pill stack) | — |
| `section` | 章节扉页(大序号) | slideLayout3 |
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

**封面/封底已 master-spec lock**:封面只 title + 发起人姓名 + 日期,**砍掉**英文副标题 / 团队名 / 会议性质;封底只 slogan,**砍掉** CTA pills / 联系方式表格。

### 13 个叙事模式(layout 之上的修辞结构)

A. 3+1 hero(三并列汇聚到一个 hero) · B. 判定卡(GO / 部分 GO / NO-GO) · C. 北极星 chip(每个 focus area 必带) · D. 不做 / 做 边界带 · E. 1→N 分叉 · F. 现阶段 → 未来 chip · G. 双轨结构(单角色双任务) · H. 铁四角(2×2 + 中心节点) · **H+ 两手架构(左手 X · 右手 Y · 共享底座,适合产品定位)** · I. 6 步流水线 timeline · J. 三色原则带 · K. 1+1 vs 1+1+N · **L. 北极星地图(N 个项目一页综述,每个带北极星指标 + 核心售卖 + 3 子能力)** · **M. 邻接场景(同一能力跨 N 行业,每个带量化经济杠杆)**

外加 27 个 `.ui-*` UI 原语(Lark Base 表格 / 飞书消息 / 浏览器 dashboard / 手机壳 / 仪表盘 etc.),全部用 HTML/CSS 重建,不贴截图。

### 一页纸案例 / 客户案例集 已 Path-A 化(0 token)

| Path A · 模板渲染 | Path B · LLM 手写 |
|---|---|
| `python3 assets/render.py one-pager input.toml output/` | agent 手写 HTML/CSS,在品牌底线内 |
| `quote` / `big-stat` / `multi-case-bundle` 同样有子命令 | 用于 4-beat schema 装不下的故事 |
| 0 token,~0.5 s,验证保证通过 | ~30-60 s,~70 K tokens |

Path A 自带两个安全网:**schema-fit refusal**(占位符 / 长度过短 / 内容重复 → 拒绝渲染,逼 agent 切 Path B 或回去重抽 TOML)+ **accent boundary review**(渲染后高亮显示 accent 词,1 秒目测"高亮的是该突出的词吗")。

---

## 7. 一页纸案例(强约束 ⚠️ 重点审阅)

技能里**最强的硬规则之一**。

### 触发条件
用户说"一页纸案例 / one-pager case / 做成一页 / 压成一页",或递一行案例库的数据 + "做成 deck / 试试效果 / 把这一行做出来"。

### 强约束
- **跳过封面页**——一页纸案例不该有 cover(封面 + 内容 = 浪费一页)。配图直接在内容 slide 的右栏作为 hero 视觉。
- **结构必须是 4-beat**:痛点(蓝)→ 冲突(橙)→ 解法(teal)→ 价值(紫)。这套色彩语言固定。
- **图文比例**:左文右图 1 : 1.3,magazine-spread 风格,配图 v2 高度等于文字列高度(v0 太小 / v1 太大 / v2 frozen 2026-05-03)。
- **多案例 bundle 不在此约束内**——3+ 个案例的 deck 走标准 cover + agenda + section + content 流程(已 render.py 化:`render.py multi-case-bundle bundle.toml output/`)。

### Path B 的"品牌底线"

可以破 layout shape,但**不能破**:深色背景 / `--fs-*` 调色板 / 飞书 wordmark 在位 / 1920×1080 画布 / ZH-only 默认 / validator 全部 strict pass。

Path B **不是**"加个性化字体颜色"的口子,是"故事真不 fit 模板"的口子。

---

## 8. PDF / PPT 转换的三种模式(2026-05-05 起明确)

| 模式 | 场景 | 产出 | 成本 |
|---|---|---|---|
| **Replica · 页面转图片**(默认) | 设计师精修过的 PDF / PPT,含 UI 截图 / 配图 | 每页 jpg + HTML 壳子(全屏 / 上下滑 / URL hash) | ~30 s,0 token,100% 信息保真 |
| **Rewrite · 原生重画**(opt-in) | 文本 / Markdown / Doc 导出,或低质量源,或用户明说"重画" | 完整 native HTML deck,带 data-text-id + texts.md 编辑回路 | ~30-60 K tokens |
| **逐页精修**(对话模式) | 用户逐页 review,每页给反馈,agent 改一页 | `runs/<ts>/output/single-pages/p-NN.html` 每轮一张 | per-page 增量 |

### 默认 = Replica(若源是设计师精修过的 PDF / PPT)

理由:
- 用户已经为设计付过钱,Rewrite 会**丢失** UI 截图 / 氛围照片 / 自定义视觉
- "样式变化很大,截图都没了"是 Rewrite 输出的最常见反馈
- Replica 0 token 0.5 s,客户实际想要的"体验升级"是壳子(全屏导航 / 移动端 / URL hash sync),Replica 都给

### 必须严格 1:1 页数(默认)

源材料 N 页 → 输出 N 张 slide。**不许默默压成更少页**(以前发生过 54 页 → 17 页的事故)。压缩 opt-in only:用户明说"精简 / 提炼 / 压成 N 页 / 做执行摘要"才允许。

### 逐页精修的标题逐字保真

per-page polish 模式下,源 PDF/PPT 标题必须**逐字**到 HTML——不丢字、不加字、不换标点(全角 ↔ 半角)、不丢括号注释。Agent 的修改 license 是**重做版式 / 排版 / 装饰**,不是改 COPY。这条规则 2026-05-06 升级为强约束,事故触发(标题字"资本"被压、"AI 原生组织"被加空格、"(企业豆包)"被丢)。

---

## 9. 文本编辑回路(texts.md sidecar)

**问题**:deck 是 1500+ 行 HTML,用户找一句改字像大海捞针。

**方案**:
- 每个 text leaf 都打 `data-text-id="slide-NN.field"`
- 同时输出 `texts.md`(结构 `## slide-NN ...\n- field: 文字`)
- 用户在 texts.md 里改文字,跑 `python3 assets/apply-texts.py output/index.html output/texts.md` patch 回 HTML
- CSS / 布局 / SVG / 装饰 **字节级保留**,先备份 `.bak`

**强约束**:
- 每个 text leaf **必须**有 `data-text-id`,slide 顺序 NN 跨重生稳定
- 必须输出 `texts.md`,没有就是技能 bug
- 占位符(`{{var}}`)+ inline `<br>` **不打** ID(避免冲突)
- 装饰 / SVG / 图标 **不打** ID

`finalize.sh` 自动调 `extract-texts.py` 生成 / 同步 sidecar,作者不再手动调。

---

## 10. 资产库(2026-05-07 大批入库)

**核心理念**:常用 logo / icon / 头像不再让 LLM 临时画或网上扒,统一从内置库匹配。

### 库结构

```
skills/feishu-deck-h5/assets/
├── clientlogo/                          ← 251 张客户 / PE / VC 标识(24 MB)
├── digital_employee_avatars_50/         ← 45 张通用 AI 助手肖像
├── mydigitalemployee/                   ← 5 个内部命名 persona
│   └── 睿睿 / 参参 / 探探 / 呆呆 / 图图
├── 飞书标识_<product>_<variant>.png    ← 13 个飞书产品 × 3 色变体 = 39 张
│   └── AI / aily / aPaaS / 妙搭 / 知识问答 / 飞书会议 / 多维表格 / 人事 /
│       招聘 / 绩效 / 项目 / People / 集成平台
├── {slack,zoom,salesforce,workday,servicenow}.png   ← 国际产品图标
└── lark-{logo,cover-bg,section-bg,content-bg,slogan}.{png,jpg}   ← 母版 6 件套
```

### 匹配规则

| 场景 | 优先级 |
|---|---|
| 客户名(中文) | 先 `clientlogo/<中文名>.png` → 然后英文短名 → 再叫用户补 |
| 飞书产品 | `飞书标识_<产品>_Color.png`(深色 deck 默认彩色) |
| AI 助手有命名(睿睿等) | `mydigitalemployee/<名字>.png` |
| 通用 AI 助手 | `digital_employee_avatars_50/NN_<traits>.png` |

### 强约束

- **不允许**自己 SVG 画飞书产品标识(商标违规风险)
- **不允许**`assets/` 根目录乱塞客户 logo,客户 logo 必须落 `clientlogo/`
- **不允许**用 emoji 替代 icon
- 找不到的 logo 用 `lark-logo.png` 兜底,不要自己设计

---

## 11. 反馈闭环(FEEDBACK.md)

每次成功 build **必须**产出 `FEEDBACK.md`——**不是空白模板**,是 agent 自动记录这次 run 真实做出的判断 / 取舍 / 妥协。

### 必填 4 类内容
1. **Header**:run 时间戳 + 一句话说做了什么
2. **关键决策(自动检测)**:每个非平凡选择都列一条,含「做了什么 / 为什么 / `你的看法:` 复选框」
3. **本次没解决的小毛病**:validator 警告但 agent 没改的
4. **你的额外建议**:留几个空 bullet 给用户填

### 末尾固定语
> 累计 ≥3 条值得反馈的(打钩 / 备注 / 自填),把这个文件发给 skill 维护者整合到下一版.

### 禁止
- ❌ 通用 checklist("layout 对吗 / 字号对吗")—— 没上下文等于没问
- ❌ 重复 validator 的 PASS 报告
- ❌ "看起来很棒"这种夸奖
- ❌ 硬编码维护者邮箱(不同 install 不同维护者)

---

## 12. 自检(validate.py · ~27 条规则)

2026-05-08 P3 重构后,SKILL.md "Self-check" 章节由 200 行压成 ~50 行——validator 报错本身已经"什么错 + 怎么改"地告诉 agent / 用户,不再需要 agent 通读 59 项 prose。

### 验证家族(每条都有"how to fix"提示)

| 家族 | 规则 | 内容 |
|---|---|---|
| 结构 | R02 / R07 | 每个 `.slide` 有 layout / screen-label / wordmark |
| 复制 | R05 / R13 | 无 emoji / `!` / `…`,内容页标题无 `<br>` |
| 调色板 | R10 | hex 来自 `--fs-*` |
| 阴影 | R12 | 无真 drop shadow(只允许环 / 内阴影) |
| 字号 | R06 / R20 | 正文 ≥ 22 px,chrome ≥ 14 px,per-page font-size 在梯子上 |
| Logo 默认 | L1 | 彩色默认,mono opt-in |
| 布局完整性 | L2 / L3 / L4 | stage 平衡,卡片内容自适应,process attrs 单列 |
| 变体规范 | R47 | 结构变化的 variant 重声明 align/justify |
| 默认居中 | R48 | 固定 shape layout 默认垂直居中 |
| Cyan | R49 | cyan 仅行内字高亮 |
| Header | R56 | 内容页 header 只一个 `<h2>` |
| Decor | R38 | data-decor 仅在 ship list 内 |
| 运行时 chrome | R29-R32 | 顶部进度条 / 底部 pager / 全屏 API 都已接入(2026-05-08 修复:audit 现在能读外链 JS,以前对 linked-script deck 误报) |
| 居中模式 | R36 | 用 `margin: -540px 0 0 -960px`,不用 grid place-items |
| UI mocks | UI1 | 系统 UI 必须 HTML 重建,不贴 PNG |
| 语言 | R-LANG | `.title-en` 类只在 `<meta name="fs-language" content="zh-en">` 时允许 |
| Text-id sidecar | T01 / T02 / T03 | id 唯一 / 形状合规 / 与 texts.md 同步 |
| 性能预算 | P50-P55 | 见第 13 节 |
| Slide 唯一 key | R-KEY | 每张 `.slide` 有唯一语义 `data-slide-key` |
| Preflight | PREFLIGHT | 本地挂载 + 写权限 |

### 人眼验证(validator 抓不到)

- 视觉对齐(标题基线 ↔ logo 中线、agenda 数字 ↔ 标题)
- 氛围密度(glow / grain 与内容密度匹配)
- ZH-EN 平衡(双语 deck 中 ZH 大于 EN)
- 叙事落地(每张 slide 3 秒能讲清自己的一点)

打开 1920×1080 / 1280×720 / 380×680 各看一遍,有视觉问题就修;validator 只抓可程序化的。

---

## 13. 性能预算(P50-P55,硬规则)

| 项 | 规则 |
|---|---|
| **P50** | base64 内嵌到 `<style>` 默认 ≤ 100 KB(硬上限 250 KB)。inlined 模式必须声明 `<meta name="fs-deck-mode" content="inline">` 跳过此检查 |
| **P51** | `backdrop-filter` blur 半径 ≤ 10 px(GPU 成本随半径增长) |
| **P52** | `new ResizeObserver()` 仅 1 个实例(多了警告) |
| **P53** | `addEventListener` 数 ≥ 8 必须用 `AbortController` 管理生命周期 |
| **P54** | `.slide-frame` 必须声明 `contain: layout paint size`(局部重绘) |
| **P55** | `.slide-frame .slide` 必须声明 `will-change: transform` + `translateZ(0)`(GPU 层) |

---

## 14. 框架自动防御(BF1-BF8)

不再要求 agent 在每个 deck 里手写防御 CSS。框架已自动:

| 失败模式 | 自动防御(在 feishu-deck.css) |
|---|---|
| BF1 单字大数字贴左缘 | `justify-self: center` 在 big-stat `.num` |
| BF2 col-visual 双框包自装饰组件 | `:has()` 选择器自动剥外框(对 .data-panel / .ui-window / .kpi-strip / .scene-grid / .north-star-map / .calc / .ui-kpi 都适用) |
| BF3 helper 在 stage 中段挤压 | 检测到 helper 是主体块时自动加 padding + gap |
| BF4 pullquote 左条让文字偏离网格 | `.stage > .pullquote { margin-left: -32px }` |
| BF5 macOS 红黄绿点 | 默认 `display: none`,`data-show-chrome` opt-in |
| BF6 ui-grid 挤靠左 | `.ui-grid { width: 100%; align-self: stretch }` |
| BF7 content-2col hero 图与文字底不齐 | `.col-text` 在检测到 hero 图时自动 `space-between` |
| BF8 图表被 flex stage 挤压,柱子掉到 X 轴下 | `.arr-chart / .store-chart / .bar-chart { flex-shrink: 0 }` |

新的图表类继承 BF8 防御,只需起一个上述类名,或在 per-page CSS 里自己写一行 `flex-shrink: 0`。

---

## 15. 已退役 / 已知限制

- **`.source-footer` / `.footer` / inline page-no 已 2026-05 退役**:旧 deck 可能还有,新生成的不该再加。页码统一由 present-mode pager UI 显示。
- **`<img>` 在 slide 内容里禁用**:UI 截图必须用 `.ui-*` 原语 HTML 重建(满足 UI1)。真实照片走 `data-decor="photo-bg"` + CSS 变量。
- **brand assets `lark-*.png/jpg` 不在 MIT 协议内**:仓库公开化前必须移除或替换。
- **Cyan #24C3FF 不能做整页 accent**:仅作行内字高亮(`.accent-text` / `.hl`)。
- **`copy-assets.py` 的 prune 正则 2026-05-08 修复**:之前对根级 `assets/...` 引用(无 `../` 前缀)误判为"无引用"导致整个 output/assets/ 被清空。现在零或多个 `../` 前缀都识别。
- **`audit_runtime_chrome` 之前只看 inline `<script>`**:对 `<script src="...">` 外链 deck 一律误报 R29-R32(9 条)。2026-05-08 P3 修好,自动读外链 JS 内容。
- **`extract-texts.py` 对 `<span class="X">…</span>` 嵌套结构有边角 bug**:个别 slide 的 text-id 没被 dump 进 texts.md(P51 9 个 photo span 是已知例子)。不影响出图,影响 T03 同步检查。

---

## 16. 评审建议清单

审阅时建议重点关注:

### A. 强制门槛是否合理
- [ ] preflight 拒绝执行的边界——是否有客户场景被错杀?
- [ ] "必须建 per-run 工作目录"——单次 quick fix 也要建吗?开销值得吗?
- [ ] hand-back 规则——技能在不该回显路径的场景是否会乱回显?
- [ ] R-KEY 在小型 deck 上是否过度——5 张 slide 也要全部带语义 slug 吗?

### B. "不编 STORY/数据来源" 这条
- [ ] 团队过去有过"模板字段当占位填"的事故吗?这条规则是补救已发生的错?
- [ ] `brand` / `source` 字段在 input.toml 里被标为 OPTIONAL 是否够明显?
- [ ] agent 在不确定时是否真的会 ask(不是默默填)?

### C. 中文优先
- [ ] 团队的客户/上游有英文场景吗?双语开关够好用吗?
- [ ] R-LANG validator 检测项是否覆盖够全?(目前只查 `.title-en` / `.subtitle-en` / `.label-en`)

### D. 一页纸案例的 4-beat
- [ ] 痛点/冲突/解法/价值 这套结构能覆盖你团队 80% 的案例吗?
- [ ] Path A → Path B 的退避是否有遗漏?
- [ ] Path B 的"品牌底线"是否真的够硬?被破过吗?
- [ ] Schema-fit refusal 的占位词清单(TBD/TODO/占位等)够全吗?

### E. PDF/PPT 转换三模式
- [ ] Replica 默认是否合理?有 deck 类型应该默认走 Rewrite 吗?
- [ ] 1:1 页数硬约束在压缩需求合理时是否会被错过?
- [ ] 逐页精修模式的"标题逐字保真"在用户主动压缩标题时是否够灵活?

### F. 资产库
- [ ] 251 客户 logo + 飞书产品标识 + 数字员工头像在公开仓库是否有版权 / 商业敏感问题?
- [ ] 库的命名规则(中文文件名 / kebab-case 国际名)是否足够稳定让 agent 准确匹配?

### G. 整体态度
- [ ] 技能拒绝行为(refuse to work)是否过度——容易让用户觉得"调用麻烦"?
- [ ] SKILL.md ~4900 行(已瘦身 280 行),agent 真的能记全吗?哪些规则最容易被遗忘?
- [ ] FEEDBACK.md 设计能产生有用的迭代信号吗?还是会变成另一份没人看的产物?
- [ ] 13 layout + 13 narrative pattern 的硬限制,是否在某些场景下太死板?

---

## 完整规范引用

- `skills/feishu-deck-h5/SKILL.md` —— ~4900 行,技能实操细则
- `DESIGN.md` —— 9-section 设计系统(颜色/字体/组件/布局/响应/品牌等)
- `skills/feishu-deck-h5/assets/validate.py` —— ~27 个 audit/check 函数
- `skills/feishu-deck-h5/assets/finalize.sh` —— 一条命令编排 copy-assets / extract-texts / validate / package
- `skills/feishu-deck-h5/templates/` —— 5 个 Layer 1 模板(_shell / one-pager / quote / big-stat / multi-case-bundle)
- `skills/feishu-deck-h5/examples/` —— 完整可运行样例
