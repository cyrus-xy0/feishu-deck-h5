# design-first — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:拿到文案要先出设计方案 + 组件类表(Q0-Q4/六维/squint)

## DESIGN-FIRST POLICY (mandatory) — 给文案就先出设计方案,别直接动手

> **本节是 `DESIGN PHASE` Step 2 的细节**(per-page 设计预检 + Q0–Q4 + 六维 +
> Decision rule)。编排、默认值、确认门规则在 `DESIGN PHASE` 那一节;这里讲
> "每页具体怎么想"。**raw-first 立场(见 `DECK GENERATION POLICY`):默认每页
> `layout: "raw"`,只有命中「纯标准形状白名单」才回退 schema。** 确认门:raw 页
> 过确认(批量一次性过),回退 schema 的白名单页宣告即走。

When the user hands you **a text brief** (一串提示词 / 文案 / Q&A 大纲 /
sections 描述 / 主题列表),**do NOT immediately create files**. First
produce a per-page design plan in chat (DESIGN PHASE Step 1–3), THEN —
若有 beyond-default 页则等确认、否则宣告即走 — generate.

### 设计前预检 · 5 个问题(MANDATORY · 每张新 slide / per-page polish)

**触发条件**:任何即将生成 HTML 的新单页 + 任何用户给文案让你重做的页。

**强制规则**:**必须在 chat 里 EXPLICIT 写出 Q0-Q4 答案 + A 档 6 维 spec
+ design intent statement,再调用任何 Write / Edit 工具**。「在脑子里
跑过了」不算。用户看不见你脑子里的思考。

**当 prompt 信息不足以填完 Q0-Q4 时,你 MUST STOP**:用问句形式
把空缺字段返还给用户,等用户回答再开工。**不要自己脑补答案**,因为
脑补的会跟用户真实意图错位(slide 9 冰红茶就这么发生的)。

#### 反模式 — 看到立刻拍醒

| 用户 prompt | ❌ 错误响应 | ✓ 正确响应 |
|---|---|---|
| 「做一页 AI 重写消费品增长」(8 字标题) | 立刻 `Write` deck.json 加 slide | 先在 chat 输出: "这页的**角色**是?(现象/方法论/结论/对比/证据) **唯一要记住的具体一句话**是?**A 档元素**应该是什么?气质上是冷调科技还是暖调编辑?" 等用户回答再 generate |
| 「加一页关于客户案例」(8 字) | 直接套 `content/story-case` schema | 先问: "这是单页 one-pager、单客户多页故事,还是多客户矩阵? 是否明确要痛冲解价值 4 段? 有客户原话还是只有数据?" |
| 「再做一页」(纯指令) | 沿着上一页 layout 复制 | 先问: "这页角色?跟前一页(方法论)什么关系?接续 / 转折 / 收束?" |

#### 触发判定

**判定 "prompt 信息足够"** —— 满足以下**至少 3 个**:

- ✓ 用户写明了**页面角色**关键词(现象/方法论/结论/对比/证据 之一,
  或同义词如"展示/讲解/收束/对比/数据支撑")
- ✓ 用户写明了**这页要记住的具体内容**(slogan/数字/案例名/产品名等
  具体的东西,不是抽象概念)
- ✓ 用户列出了**至少 2-3 个具体元素**(列表项 / 卡片 / 数字 / 图标 等)
- ✓ 用户暗示了**视觉气质**(科技/编辑/怀旧/工业/极简 等关键词)
- ✓ 用户给了**参考样式**(URL / 截图 / 类比 "做成 BCG 报告风")

**只满足 ≤ 2 项 = 信息不足 = 必须问问题再动手**。

漏跑这 5 题的真实代价(2026-05-22 复盘 · slide 9 冰红茶 5 剧本墙):
prompt 明写「现象呈现页 · 不下结论 · 话术是视觉焦点字号最大 · 引号视觉化」
—— 我跳过预检,直接套了"通用 3 卡 + 锚定 banner"(=方法论页骨架),
slogan 做成 28(Sub tier) 跟场景名同档不是"最大",引号 48 不是"视觉化"。
prompt 字面 4 条要求,**1 条都没真做到**。根因:没跑 Q0-Q4 就动手。

**这个反模式的根因不是用户 prompt 太短,是我自己跳过预检**。即使
prompt 给得很详细(slide 9 那个 prompt 信息绝对足够),不在 chat 里
explicit 跑 Q0-Q4,我还是会用熟悉的模板套上去。**强制 explicit chat
输出是唯一防线**。

#### Q0. 这页是什么角色?

5 选 1:

| 角色 | 视觉处理 | 反模式 |
|---|---|---|
| **现象呈现页** — 信号墙 / 剧本墙 / 案例矩阵 | 等权并列,不下结论 | 加锚定 banner / 加收束金句 / 强行 3up |
| **方法论页** — 步骤 / 框架 / 原则 | 顺序+依赖,流程感 | 等权并列没顺序 / 没收束 |
| **结论页** — 一句话收束 | 单 hero 句,记忆锚点 | 信息密度高,稀释结论 |
| **对比页** — 痛 vs 解 / 旧 vs 新 | 2 列 + 中线 + 视觉重量差 | 3 列均权 / 没视觉对位 |
| **证据页** — 数据 / 案例 / 引文 | 数字为主 + attribution | 抽象论述 / 无具体数据源 |

**错读角色 = layout 全错**。现象页做成方法论页 = 锚定 banner 抢了剧本墙
的戏 = 整页变 PPT 三段论。

#### Q1. 这页最该被记住的唯一一件事是什么?

**只准选 1 个**,不准选 2 个并列。写出来必须是 1 句具体话:

> "我希望观众离开这页时记住 [X]"

X 必须是**具体内容**(slogan / 数字 / 案例名),**不是抽象概念**:
- ✓ "撸串没冰红茶等于火锅没毛肚" — 具体话术
- ✓ "2 小时完成 335 人调研" — 具体数字
- ✗ "3 个痛点" — 抽象,记不住
- ✗ "AI 重构消费品逻辑" — 抽象口号

错读 Q1 = "每个东西都同等重要" = 全均匀 = 没重点 = 灰泥。

#### Q2. 把所有元素分 A/B/C/D 四档 + 强制 6 维 specification

| 档 | 角色 | 数量 |
|---|---|---|
| **A** | 必赢 · 视觉最大 | **唯一** |
| **B** | 辅助焦点 | 2-3 个 |
| **C** | 解释信息 | 视情况 |
| **D** | 注脚 | 视情况 |

**A 一定就是 Q1 答案的载体**。

**仅写「A 档 = slogan」是不够的** —— 这是断点。Q2 之前我写到这里就停,
然后让 4-tier ladder 自动决定字号 → slogan 跟其他元素同档 → A 档没赢。

**Q2 必须为每档输出 6 维 specification,不允许跳过任何一维**:

```
A 档 [元素名]
├─ 字号 ____  (具体 px;允许 off-ladder + /* allow:typescale */)
├─ 容器层级 ____  (1 级页 / 2 级卡 / 3 级浅 zone / 独立 box)
├─ 装饰 ____  (装饰字符 / 大圆角 / 阴影 / 边框 / 渐变 / 无)
├─ 对齐 ____  (左 / 中 / 右)
├─ 字距 ____  (具体 em 值,默认 normal;tight tracking ≤ -0.04em)
└─ 字重 ____  (400 / 500 / 600 / 700 / 800 / 900)

B 档 [...] (同上 6 维)
C 档 [...] (同上 6 维)
D 档 [...] (同上 6 维)
```

**Q2 收尾 · density budget(page-level,每页一行,验"装得下"):**

A/B/C/D 档分完后,再写一行 page-level 量盘子。6 维 spec 是"每个元素长什么样"
的细节,density budget 是"这页总共装得下吗"的总量检查。两步都过了 Q3 黑白
框架才有意义,否则黑白框架本身就是塞满的草稿,后续被迫靠"压字号 / 缩 gap"救火。

```
density budget(本页):
├─ 核心信息块: X 个    (A + B 档加起来)
├─ 支撑信息:   Y 个    (C 档)+ 下沉策略(底部窄带 / 注脚 / 下一页 / 直接砍)
└─ layout 容量: Z 个    (layout 的"自然容量":content-3up=3 卡 · stats=4 KPI ·
                         scene-grid=6 · logo-wall=12+ 必分组 · agenda=4-8 ·
                         arch-stack=2-5 层 · north-star-map=5 · table=4-6 行 ·
                         flow timeline=4-6 节点)

判定:X + Y <= Z?
  ✓ 是  → 继续 Q3 黑白框架
  ✗ 否  → 不回头压字号,**回 Q1 砍内容**:必上的留下,可下沉的下沉到 C/D 档,
          可删的删。允许把 Y 降到 0(支撑全下沉)再判一次。仍超 → layout 选小了
          或这页本来该拆成 2 页。
```

**反模式**:Q2 装下了 5 张大卡放进 `content-3up`(Z=3),不回 Q1 砍,而是在 Q3 把
卡 padding 压一半 + 字号从 48 → 28 + 卡片紧贴 —— 出图必然"挤"。Q2 量盘子就是
为了挡这种事。

**为什么 6 维强制**:

vocab 库(知道哪些 move 可用)需要 5-10 个不同主题的设计积累,**1 个
样本写不出来**(写出来就是 lock 死在那一种气质)。但**思考维度可以
现在固定**:任何 element 处理,**至少这 6 件事都要想过**。

不规定值,**强制必须填**。第一次跑可能填得很烂(没经验),但 explicit
写出来,用户能 review,迭代后能积累成真 vocab。

**反模式 — Q2 断点的具体形态**:

- ❌ "A 档 = slogan" + 5 维全空 → ladder 自动填 28 → 没赢
- ❌ "A 档 = slogan,字号 44" + 容器/装饰/对齐/字距/字重 全空 → 字大了但视觉无重量
- ❌ "B 档 = 场景名,字号 28" + 其余全空 → 跟 A 档 28 同档,A 档没赢
- ❌ 6 维填了但**没跟 Q4 内容气质对齐** → 上了冷调装饰跟主题不搭

**正例 — slide 9 重做版应该这样写**:

```
A 档 = slogon (5 句话术)
├─ 字号:44 (off-ladder · prompt 要求字号最大 · documented intent)
├─ 容器:3 级浅 zone (页 → 卡 → 浅 zone) · 圆角 18
├─ 装饰:80 serif 双引号(左上+右下绝对定位 · 品牌色 0.45 透)
├─ 对齐:中央
├─ 字距:-0.015em (tight tracking 增 editorial 感)
└─ 字重:900

B 档 = 场景名 + 头像 + 图标
├─ 场景名 28 · 2 级卡内 · 顶部 tiny-caps eyebrow "剧本 01" · 左对齐 · -0.01em · 700
├─ 头像 64 · 圆角 14 · 位置:卡顶右 · 品牌色 0.45 透 border · normal · -
└─ 图标 40 · 圆角 14 · 位置:卡顶左 · 1px 白透 border · - · -

C 档 = 人群标签 / 产品规格
├─ 字号 16 · 容器 spec 用圆角 pill 边框, demo 文本无容器
├─ tiny-caps eyebrow 上方("人群标签" / "产品规格")· 0.20em tracking
├─ 字重 500 · normal tracking · 左对齐

D 档 = 内容载体
├─ 字号 16 · 卡底 · 上方虚线 hairline 分隔
├─ 颜色 #fff 透 55% · italic · 左对齐 · normal · 500
```

每行 explicit · 总共 5-6 行 spec · 看完就知道每个元素长什么样。

#### Q3. 我现在准备做黑白框架,还是直接上风格?

**正确顺序**:
1. 黑白框架 — 只看大小 / 位置 / 比例 / 是否成立(无色 / 无品牌色 / 无渐变)
2. 风格 — 上色 / 字体 / 边框 / 阴影 / 渐变

**直接上风格的后果**:`feishu skill 默认 = 深色 + 品牌冷调 + 4-tier ladder`
变成隐形 KPI,prompt 意图被压在底层。我会先做风格再硬塞内容进去 ——
反向工程。

**眯眼测试(必跑)**:把黑白框架缩小到 1/3,眯眼看:
- 重点还成立吗?
- 5 列是不是均权(而不是某列突然轻 / 重)?
- 标题 / 卡片 / A 档元素之间形成节奏了吗?

眯眼看不出层次 = 框架没成立 = 上色也救不了。

#### Q4. 内容自己长出来的气质,跟 feishu skill 默认冲突吗?

| 内容气质 | 自然长出的 palette | feishu skill 默认 | 冲突? |
|---|---|---|---|
| 高科技 / AI 协同 / 数据指标 | 深蓝 / 青色 / 几何 | 深蓝 + 品牌冷调 | ✓ 一致 |
| 客户故事 / 案例 / 编辑感 | 米白 / 纸感 / 编辑灰 | 深蓝 | ✗ 冲突 |
| 食饮 / 怀旧 / 烟火气 | 茶色 / 琥珀 / 砖红 / 纸张 | 深蓝 + brand color | ✗ 强冲突 |
| 节庆 / 文化 / 传统 | 中国红 / 墨黑 / 金 | 深蓝 | ✗ 冲突 |

**冲突时怎么办**:
- feishu skill 标准是**约束底线**(不准 cyan / 不准 drop shadow /
  R10 brand hex / R12 / R13 / R56 等)
- skill 默认的**配色 / 字体 / 渐变模式**是"出厂建议",不是强制起点
- 内容气质优先 —— 即使 break ladder 或做 documented palette
  exception,也比出图跟内容气质不搭好
- 设计方案 chat 里 explicit 标:"⚠️ 这页内容气质要 [X],
  跟 skill 默认 [Y] 冲突;打算 [打破 ladder / 用自定义 palette /
  接受 R-VIS-TIER 报告 / 加 documented exception]"

#### 通过 5 问的标志:写出 1 句 design intent statement

跑完这 5 题应该能写出:

> "这页是 [现象呈现页],唯一重点是 [5 句话术,让观众自己得出结论],
>  A 档元素是 [slogan,44 hero + 80 装饰引号],
>  气质上要 [editorial 杂志感],
>  跟 skill 默认 [深蓝 + cool palette + 4-tier ladder 上限 48] 冲突,
>  处理:[slogan 字号 off-ladder 到 44,引号 off-ladder 到 80,
>  接受 R-VIS-TIER 报告作 documented intent;但保 skill 必守的
>  R10 / R12 / R13 等约束底线]"

**写不出这句话 = Q0-Q4 没答清 = 不要动手。**

#### 实操:把 5 问写进 design pass table

老版 design pass table 只列 layout 选型,加 1 列 "design intent" 写出 Q0-Q4
关键判断:

| # | 页 | 角色(Q0) | 唯一重点(Q1) | A 档元素(Q2) | 气质冲突?(Q4) | Layout |
|---|---|---|---|---|---|---|
| P0 | 冰红茶 5 剧本墙 | 现象页 | 5 句 slogan | slogan 44 + 引号 80 | ✗ 冲突 → 接受 R-VIS-TIER 作 documented intent | raw + content-3up base |

用户看到 "现象页 + 5 句 slogan 是 A 档"就立刻明白方案对不对,比看 layout
名更准。

### Validator 报告响应纪律 · opt-out attribute 不是 silence button

跑 `--visual` 之后 validator 会喊 R-VIS-BODY-FLOOR / R-VIS-TIER /
R-WHITE-TEXT 等。**每条警告都给 3 个选项**,典型形态:

> ✗ R-VIS-BODY-FLOOR · 16px 字太小
> · **Bump to 24 (preferred)**
> · OR rename to chrome class (.eyebrow / .footnote / .source / ...)
> · OR set `data-allow-body-floor` for documented exception

**默认必须选 Bump**。opt-out 是少数路径,仅在元素**真是 by-design 小字**
(axis-label / legend / status-chip / chrome metadata) 时用,**不是**
"warn 太多了批量哑掉"的方便键。

#### 三大 opt-out 的合法 vs 滥用场景

| Opt-out | 合法场景 | 滥用反模式 |
|---|---|---|
| `data-allow-body-floor` | Axis tick label / sparkline 数值 / status pill (在线/离线) / unit suffix | 整张卡片所有 li / desc 批量挂 → 静默承认字太小 |
| `/* allow:typescale */` | Cover hero title / section chapter-num / big-stat 数字 / 一次性装饰字符(80+ serif quote) | 每个 28-44 px 标题都挂 → 让 ladder 失效 |
| `/* allow:white-opacity */` | Subtle backdrop / decorative dim text / 真 chrome metadata | 整页 body 内容都用半透白 → 整页"褪色"感 |

#### 反模式识别:统计学触发器

**单张 slide 同一种 opt-out 出现 ≥ 5 次 = 几乎一定是 silence 反模式**,
不是 documented intent。Documented exception 应该是 1-3 处,精确定位
到真正的 by-design 元素。批量挂 = 在用 opt-out 做 mass-mute。

2026-05-22 复盘实例(slide 10 content-pipeline):

- validator 喊 10+ 条 16px R-VIS-BODY-FLOOR(li / track-body / proc-sub /
  proc-output / r-name / hi-desc 等)
- **我选了批量加 `data-allow-body-floor="diagram"`**,silence 12 个元素
- 用户视觉看:"方框里字普遍偏小,显得方框很空"
- **validator 全做对了 — 是我用 opt-out 哑了正确的警告**
- 修法:撤掉错加的 opt-out,真 body 内容 bump 16 → 24,只保留真 chrome
  (流 01 / 4R Strategy eyebrow / R1-R4 tag / 轨道 A/B badge / infra tag)

#### 实操规则

在 chat 里加 opt-out 之前,必须能回答:

> "这个元素 [name] 我打算挂 [opt-out 名]。它是 documented [chrome /
> by-design small / legend / axis / 装饰字符],因为 [具体设计理由,
> 不是'字号方便']。"

写不出 "因为"，就 bump 字号 / 选其他 fix,不要挂 opt-out。

#### 长期 framework 改进(TODO)

`R-VIS-OPT-OUT-ABUSE` 新审计 — 当单张 slide 上同种 opt-out attribute
出现次数 > 阈值(建议 5)时报 warn,强迫作者写 design justification
或减少 opt-out 数量。这是把"opt-out 必须是 documented intent"从
软约定升级为硬检查的下一步。

### Component utility classes (mandatory · framework 自带,不要自己复刻)

写 raw layout / 自定义 slide 时,**写一行 CSS 之前先查 framework 有没有
现成 component class**。Ad-hoc 重写不仅是冗余代码,而是**反 framework
化** —— skill 的标准化收益被消耗掉,validator 也会漏掉 lint。

| Pattern | 用 framework class | 不要 ad-hoc 写 |
|---|---|---|
| 列表项前面带 bullet | `<ul class="feature-list">` + `<li>...</li>` | ❌ `li::before { content:""; width:8px; height:1.5px; background:rgba(...) }` 自画横线 |
| icon + 大字标 + 小字描述 横排 tile | `<div class="fs-claim-row is-teal"><span class="fs-claim-row__icon">✓</span><div class="fs-claim-row__text"><span class="fs-claim-row__label">...</span><span class="fs-claim-row__desc">...</span></div></div>` | ❌ `<div class="hi"><span class="icon">...</span><span class="text"><span class="label">...</span><span class="desc">...</span></span></div>` 自起类名 |
| 强调短语 inline | `<span class="hl">关键词</span>`(框架 var --fs-cyan + 文本-黄/teal) | ❌ `<span style="color:#xxx">...</span>` |
| 数字 hero | `big-stat` schema layout · 或 `<div class="hero-num">42</div>` | ❌ 写自己的 `font-size:120px` raw |
| KPI 行 4 列 | `stats/row` schema layout | ❌ 4-col flex 自己写 |
| 客户 logo wall | `logo-wall` schema layout | ❌ 自己 grid logos |
| 引用文 + 引号装饰 | `quote` schema layout | ❌ 自己写 `<span class="quote-glyph">"</span>` |

每个 utility class 都已包含:
- 4-tier ladder 字号(`.fs-claim-row__label` 24 / `__desc` 20 already on ladder)
- R10 brand palette tokens (`--fs-blue/teal/violet/purple/orange`)
- R-WHITE-TEXT-safe color choices (solid hex 不靠 opacity 调灰)
- R-VIS-LABEL-FLOOR-safe sizing
- Master 行高 / letter-spacing / 字重

**当你发现 framework 没有现成 component**(罕见):
1. 不要 inline 写 ad-hoc — 写到 framework `feishu-deck.css` 里作为新
   utility class
2. 命名 `.fs-<pattern>` 表明它是 framework 提供
3. 加注释 + 用法 example 写在 utility 定义上方
4. 更新这张表 + 改 SKILL.md 这一节
5. 触发条件:同样 pattern 在 2 个以上 deck 出现 → 该上 framework

**反模式信号**:看到自己写的 CSS 里有
- `.highlight` / `.callout` / `.kpi-tile` / `.hi` / `.fact-row` 等 ad-hoc
  类名 → 几乎一定是该用 framework component 没用
- `<ul>` 没 `class="feature-list"` → 几乎一定该加
- `<span style="color:#XXX">` 真品牌色 inline → 该用 `.hl` 类

### Why design-first

`feishu-deck-h5` 有 14 个 schema layouts + raw 逃生口。layout 选错的代价高:

- 强行套标准 layout → 主问题被塞进 `.header .title-zh` 被 `white-space: nowrap`
  单行截断 / 内容溢出 1080 / 留白尴尬
- 默认全自定义 → 失去 schema 的 R20 / R06 / R-WHITE-TEXT 等防护,Path B 易踩坑
- 用户 review 时 layout 选错要改一整页 = 改 CSS + DOM,比设计阶段 3 分钟
  对齐贵 10 倍

围炉夜话 Q&A 是个正面例子:design pass 阶段就识别"主问题需多行 + 原声列表"
不在 schema 内,直接走自定义 `.qa-page`,避开 `.header h2.title-zh` 单行陷阱。
反例是博裕&星巴克的第一次跑:silent 把 54 页压成 17 页,因为没设计阶段对齐
"页数保持 1:1"。

### When this applies (默认 ON)

- 用户给 text brief / 主题列表 / Q&A 文案 / outline 描述
- 用户说"做一份 deck about X" / "把这些做成 deck" / "围绕 X 主题做一个分享材料"
- 用户描述了内容但没说视觉结构

### When to skip (直接走生成流程)

- 用户明说 "直接出 / 不用问设计 / 别问了就生成"
- 用户给 PDF / PPT 让 Replica / Rewrite / per-page polish — 那些路径有自己的
  conversion rules,设计在那里发生
- One-pager case (4-beat 痛/冲/解/价值 是固定结构)
- 用户在前文已经明确给出了 layout 选择
- 用户在迭代已有 deck 的某一页(per-page polish 模式)

### Design pass output — markdown table in chat

| # | 页 / 主题 | 角色 | path(默认 raw,回退才标) | 为什么 |
|---|---|---|---|---|
| P0 | 封面 | 结论 | 回退 `cover` | 纯标准形状:标题 + 发起人 + 日期 |
| P1 | 客户三个核心痛点 | 现象 | 回退 `content/3up` | 纯并列 3 卡,无关系 / 动画 → 标准形状 |
| P2 | 客户原话 | 证据 | 回退 `quote` | 单句引语,纯标准形状 |
| P3 | 那一个大论点 | 结论 | **`raw`** · 双手架构 | 全 deck 高光,有空间结构 → 主场 raw;词汇库选 two-hand-arch |
| P4 | 数据→信息→知识 | 方法论 | **`raw`** · 三层叙事 | 有递进 / 叙事实质,非纯并列 → raw |

每行必须给:
- **角色**: Q0 五选一(现象 / 方法论 / 结论 / 对比 / 证据)
- **path**: 默认 **`raw`** + **从词汇库选定的 pattern 名**(scan `narrative patterns A–N` +
  `component utility classes`,优先复用现成 pattern,别从零硬写);命中白名单才写「回退 <schema>」
- **为什么**: 1 句话依据 —— raw 页说"有什么 bespoke 实质 / 选了哪个 pattern";回退页说"它是哪个纯标准形状"

> **raw 页(= 大多数)在表下方各补一句话 design intent statement**(见"通过 5 问的标志"),
> 并把 Q0–Q4 + 六维写进 DESIGN-PLAN.md;回退 schema 的白名单页不需要。

### Decision rule — 白名单回退判定(raw-first)

**默认 = `layout: "raw"`。** F-305 «raw unless ceremonial» 之后,schema 回退**只剩仪式页**
(封面 / 分章 / 目录 / 金句 / 封底)与机制页(`replica` / `canvas` / `iframe-embed`)——
**正文内容一律 raw**(由模型自由排版,更丰富、各页更不同)。逐页判:这页是不是**仪式页**?
- **是 → 回退对应仪式 schema**(下表);
- **否(任何正文页)→ `layout: "raw"`**(主场)。

> ⚠️ **正文 schema 版式已冻结(F-305)**:`content` / `stats` / `flow` / `chart` / `table` /
> `arch-stack` / `image-text` / `logo-wall`(含全部 variant)**仍为存量 deck 渲染,但新页别再用**
> —— 用了会被 `R-LAYOUT-DEPRECATED`(warn_soft,advisory)提醒。从前"确定性几何 schema 更省
> 更稳"的理由,已让位给"模型自排更丰富、各页更不同":彻底 raw-first。一张纯标准卡片页,
> 现在也由模型 raw 自排(不再回退 content)。

| 内容形态 | 命中则回退 | 它为何是"仪式页" |
|---|---|---|
| 单标题 + 发起人 + 日期 | `cover` | Master 封面 |
| 3-8 章节项的目录 | `agenda` | Pill stack |
| 大章节号 + 章节标题 | `section` | Chapter divider |
| 1 句客户原话 + attribution | `quote` | 单句证言 |
| 结尾 slogan / 联系方式 | `end` | Master 封底 |
| Designer-polished PDF 页保真 | `replica` | 整页贴图(机制页,非设计版式) |
| **以上都不匹配 = 任何正文内容** | → `layout: "raw"`(默认主场) | 见下 |

### raw 的典型实质(它是默认,不再"仅限")

> ⚠️ raw-first 翻向后,`layout: raw` 是**默认主场**,不再"仅限"特定场景。下面几类是
> raw 最典型的实质理由(写进"为什么"列很顺手),但凡命中一类 = 留 raw:

1. **schema-shape 结构性不匹配** — e.g. Q&A 页(大问题多行 + 原声列表);标准
   `content-2col` 强制主问题进 `.header .title-zh` 被单行截断
2. **schema 里没有但又是 recurring narrative-pattern** — two-hand-arch /
   Iron 4-corners / 6-step pipeline — schema 没原生 DSL,但 CSS 已经有,
   走 `raw` 块复用 CSS
3. **用户明确给了 schema 无法表达的结构** — "6-beat case" / 竖版手机端 /
   "case 没有冲突,只有 3 个发现"

### Anti-patterns — 这些该回退 schema / 不是 layout 问题,别拿 raw 硬扛

- ❌ "想标题 18 px 不要 24" — R20 drift,不是设计实质;raw 页也得用 `var(--fs-*)` 四档
- ✅ "纯并列 4 卡(图标+标题+正文)" — **F-305 后:用 `layout:"raw"` 自排**(正文 schema 已冻结,旧的「回退 content/blocks」口径作废);用框架卡片 token / pattern 写,别再选 content schema
- ❌ "拿不准这页算不算纯标准形状" — raw-first 下**默认 raw 就对**(回退 schema 才要确证);别为了"省"硬塞进不贴合的 schema
- ❌ "想给每页换不同 accent 颜色" — `data-accent` 属性,不是 layout 改

### Design pass 收尾 — 确认门(raw-first)

设计方案 table 输出后:**raw 页 = beyond-default,需确认设计意图;回退 schema 的白名单页宣告即走**。

- **批量 deck**:把 raw 页的 spec(Q0–Q4 + 六维 + 选定 pattern)摆出,**一次性过整张方案**
  (逐页停会烦死人),end with:
  > 这几张 raw 页我按上面的设计来,确认?命中白名单回退 schema 的页(P_x / P_y)我直接出。
- **全是回退 schema 的纯标准 deck**(罕见,如纯内部 OKR 复盘)→ 宣告即走:
  > 方案如上(全是标准形状,回退 schema),我开工了;有要改的随时说。
- 逐页增量喂时,每张 raw 页设计完单独过一下确认再落。

无论哪种,**真正开始写文件前不要 pre-emptively 跑 PREFLIGHT**;按
`DESIGN PHASE` 的顺序:确认/宣告 → PREFLIGHT → new-run → **落 `DESIGN-PLAN.md`**
→ 生成。

方案一旦 lock,生成时直接照走,**不需要再问一遍**。生成后发现某页 layout
设计错了,先跟用户对齐切换(走 SLIDE DELETION POLICY 的双确认 + 备份规则),
不要静悄悄改设计;偏离 DESIGN-PLAN.md 也先回来改 plan。

---
