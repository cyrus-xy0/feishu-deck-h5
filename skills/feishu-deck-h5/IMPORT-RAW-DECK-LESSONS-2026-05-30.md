# 教训:别"事后修"外来 raw deck —— 字号/排版 一次做对 backlog

> 2026-05-30 · 来源:把一份手搓 82% raw 的青啤 deck「事后修到过 validator」的失败复盘。
> 维护者(用户)逐张挑出 ~14 个问题,**无一例外**全是同一个根:**对一份按自己字号体系设计的 raw deck 做"把字号 snap 到 4 档"的盲变换**。
> 用途:把这次的根因炼成**技能层工单**(像 AUDIT 那样),变成真框架改动。

## 0 · 执行结论(必须先认)

**对一份手搓 raw deck 做"事后字号 snap"是类别错误,不是"修"。** 这份 raw deck 的字号本身是一套**有意的层级设计**(重点大、支撑小、chrome 更小)。"把所有字号对齐到我们的 {16,24,28,48} 档"把它**两头拍平**:

- **重点/hero 被压小** → 焦点/层级消失(封面标题 82→48、金句、"任务派发员/信息汇总员/风险雷达员"、"管理者/数字分身/知识管理重塑"、4 步标签 全变小,"没有重点")。
- **支撑正文被撑大** → 级联溢出(slide 3/4/5/16 卡文字超框、撞标题/logo、单字一行孤字)。
- **chrome 被放大** → 翻页器/全屏提示/wordmark 变大(本就不是内容)。

**净效果:这版"修复"比原版差。** 它用十几个真·设计缺陷,换了一堆**根本不伤阅读的字号档 warning**。→ **青啤用回原版 `index.html`;`lark-qingdao-beer-FIXED-2026-05-30.html` 作废。**

## 1 · 元原则(技能要固化的判断)

> **我们的字号/版式规则 = 我们 schema 的排版语言,不是套在每份 deck 上的通用约束。**

外来 raw / 导入 deck 只有两条干净路,**没有"snap 到档"这条中间路**:

- **(A) 保留原设计 + 把字号修对** —— validator **照报**字号问题(小正文 / 错 hero **不豁免**,谁设计的小字都看不清);修法不是降 advisory、更不是盲 snap px,而是 **enlarge 小正文到下限 24 + 框自动长高(grow-box,改大自动拉高)/ hero 走 layout 尺寸**,框架重 bundle 修 crowd。
- **(B) 重生成走 schema** —— 字号按**角色**分配(重点→hero、正文→24、chrome→框架),内容与字号**一起设计、天生适配** = 真·一次做对。

技能要把这个 fork **显式化**(导入时就问/判:keep-as-imported vs regenerate),**绝不假装一个变换能把 A 变成合规**。

## 2 · 工单(L1–L6)

#### [L1] 字号是语义/角色的,绝不按 px 盲 snap
- 现象:封面 82→48、各 hero/强调标题被当 off-tier 砍小;同时 18/22 正文被抬到 24 → 撑爆。
- 根因:盲 snap 按"当前 px"扫,**分不出"合法大重点" vs "该改小杂项"**(都按 off-tier 处理),也分不出"为适配小框而选的小字"。
- 技能层修法(🔄 **2026-05-30 修正**):~~① 外来 raw/导入 deck 的 R06/R20 一律降为 advisory~~ —— **这条实现了又撤回**。降 advisory = 把"小正文 / 错 hero"这些**真问题藏起来**(用户当场指出 slide 3 字小、封面字小都"应该拦住");小字投影看不清、hero 尺寸不对,**谁设计的都是问题,validator 一律照报**。真正的教训是 ② **永不提供"snap 字号 px 完事不管框"的工具/动作** —— 字号"修"靠 **enlarge 小正文到下限 24 + 框自动长高(grow-box)** / **hero 走 layout 尺寸**,不是降严重度、也不是盲 snap。
- 状态:[x] L1 降级已**撤回**(imported 字号照报,167 测试绿);grow-box / hero-layout-size 修法见 L4 / L2(进行中)。

#### [L2] 重点/hero 字号是 layout 定义的,要突出
- 现象:金句、章节、5-up 角色名、4 步标签等强调字被压到 48 → "没有重点"。
- 根因:hero whitelist 只认 schema 已知 hero 版式;raw 的自定义强调元素不在内 → 被 flag → 被砍。
- 技能层修法:cover/section/big-stat/quote + 任何**强调/标题角色**都不被任何"对齐字号档"逻辑触碰;raw 导入时强调元素要么保留、要么按角色映射到 hero 档(走 B 重生成)。
- 状态:[ ] 待做。

#### [L3] chrome 不是内容(检查只查 deck 内容)
- 现象:翻页器、翻页/全屏提示、`iframe-hint`、`fs-*`、wordmark 的小字被 snap 放大。
- 根因:① 变换不分 content/chrome;② validator `CHROME_WHITELIST`(visual-audit.js ~101)有 pageno/wordmark 等,但**漏了 present-mode 翻页器/全屏提示**。
- 技能层修法:① 补全 `CHROME_WHITELIST` / `PAGE_CHROME_ANCESTORS`,纳入 present-mode UI(pager / present-hint / mode-toggle / fs-mobile-* / deck-controls);② 任何 auto-fit/变换**选择器级硬排除** chrome。
- 状态:[ ] 待做。

#### [L4] 溢出:分类型对症,卡溢出从严
- 现象:① slide 3 卡文字超框 42px **没进 error**(被我过松的分级藏成 warn);② 修法只会"压字",不会"拉高框";③ 单字一行(企业微信/拉通靠·跨部门电话会)。
- 根因:严重度分级错用了对象 —— 把"卡内容溢出/裁切"也按 px 分档(24-60→warn)。但**文字溢出卡框=可见缺陷**,不是"无害画布留白"。
- 技能层修法:① **卡溢出/裁切从严**(>16px 即 err);**只有画布边缘 slack 才宽容**(R-OVERFLOW 保留分级)——**已修(validate.py),163 测试绿**。② auto-fit triage 按类型:**框→拉高(canvas 有空间优先)** > 标题→换行 > 正文→压字 > 条目多→删条目。③ 孤字:调措辞 / **去标点(去掉 `·` 等)让末行不止单字** + 框架 `text-wrap:balance`。
- 状态:[x] 分级从严已修;[ ] grow-box / 孤字技法待做。

#### [L5] 居中/分布是框架的活,raw 重 bundle 即可
- 现象:slide 12 内容没居中、飘上去。
- 根因:raw deck 用旧 inlined JS,没有 runtime auto-balance;schema 框架默认居中它也没走。
- 技能层修法:**把外来 raw deck 重新 bundle 当前框架 JS**(含已建的 auto-balance pass)→ 加载即自动居中/均衡(且不碰字号)。这是 raw 导入的"低破坏增益"。
- 状态:[ ] 待做(auto-balance 已存在,缺"导入时重 bundle"这一步)。

#### [L6] 把 import 的 fork 显式化(总)
- 现象:我默认"能 snap 修",结果补一个冒三个。
- 技能层修法:导入/拿到外来 HTML deck 时,技能**先判 + 显式问**:这是要 **(A) 保留原设计(只做安全增益:重 bundle JS / 真伤阅读的溢出对症 / 不碰字号)**,还是 **(B) 走 schema 重生成**。**默认禁止"字号 snap 去过规则"。**
- 状态:[ ] 待做(写进 SKILL.md import/reskin 决策)。

## 3 · 这次真正做对、留下的
- **validate.py:R-OVERFLOW / R-VIS-CARD-OVERFLOW 严重度分级**(画布边 slack 宽容、卡溢出/裁切从严)—— 独立有价值,留。
- 早前:content-3up + 5 版式 correct-by-construction sweep、`R-VIS-CROWD`、runtime auto-balance —— 都留。
- **作废**:对青啤的字号 snap(L1–L3 的坑)+ 那版 `*-FIXED-*.html`。

## 4 · 下一步候选
- 执行 L3(补 CHROME_WHITELIST)+ L1(把 `lifted` 降级扩到整份导入 raw)—— 两个最小、最直接堵住"再发生"。
- L5:给"导入 raw → 重 bundle 当前 JS"做一条命令。
- L6:把 import fork 写进 SKILL.md(reskin/converting 决策表)。
- 青啤若真要:走 B 重生成(Sonnet schema 那版思路)。
