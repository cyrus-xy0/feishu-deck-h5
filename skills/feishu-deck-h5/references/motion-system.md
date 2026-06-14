# Motion System — 每页 CSS 动效(round-trip-safe)

给 deck 加"高级感"进场/强调动效的统一规范。**这是一份活的调色板,不是冻结的规格**:
每次结合页面与品牌**现场设计**,下面的效果库是起点不是终点,可重混、可调、可新增。
不变的只有"护栏(constraints)"和"方法(method)"——那两节必须守。

---

## 0. 何时用(opt-in)

- **默认不加**。框架已自带基础入场:`.slide-frame.is-current .slide > *` 走 `fs-reveal`
  错落淡入(`--child-i` 由 JS 设,gated `prefers-reduced-motion`)。这就是 baseline。
- 仅当用户明确要"高级感 / 动效 / animation"时,才加 bespoke 动效。bespoke 动效是
  **加法**,叠在 fs-reveal 之上,不是替换它。

## 1. 唯一铁律:动效活在 deck.json 里

动效 = **CSS,写进 `slide.custom_css`**。渲染器把它 scope 到 `.slide[data-slide-key=K]`
并 co-locate 成 `<style data-fs-custom-css>` 进该 slide(`render-deck.py` `_inject_custom_css`
→ `_css_utils.scope_selectors`)。它进 deck.json、随 render / fork / republish round-trip。

**绝不**:head `<style>`、`<script>`、任何 JS 动画库(GSAP / anime.js / WAAPI)。
deck.json **没有 JS 槽**,任何脚本只活在 index.html,**下一次重渲染静默丢失**——这正是用户最怕的。
WAAPI 尤其别用:它的卖点是 JS 运行时控制,静态 deck 用不上,CSS `@keyframes` 全覆盖且 round-trip。

**已落地的"框架级 JS"例外有两个,都是 deck 级 opt-in、默认关(不开 = 与纯 CSS 基线逐字节一致):**
1. **Magic Move(翻页变形)**:需要 `document.startViewTransition`(JS),但这段 JS 活在 **framework
   `feishu-deck.js` 的 `goTo()` 单点**,**作者只写纯 CSS**(`view-transition-name` 配对进 `custom_css`),
   照样 round-trip。详见 §7。
2. **GSAP 入场引擎**:`deck.motion_engine: "gsap"` → renderer 发 `data-motion="gsap"` + 本地化
   `assets/gsap/*` + 加载 framework 级 `assets/feishu-deck-motion.js`,用编排化逐页 timeline 替掉平铺
   `fs-reveal`。这段 JS 同样**活在 framework**(不是 deck 内容),所以 round-trip 安全;作者无需写任何 JS。详见 §8。
两者都是 **framework 持有 JS、deck 只声明开关**的形态。除此之外若还要 *per-slide* 的 JS 动画(bespoke 逐页脚本),
仍须先给 schema + render-deck.py + framework 加整套槽 + 解决 round-trip/validator/安全——别在 custom_css 里塞 `<script>`;
重交互(Flip/MorphSVG/Draggable 等)走 iframe 逃生舱(见 `references/prototype-embed.md`)。

**Motion tokens(可用非强制)**:框架 `:root` 已提供 `--fs-ease-out` / `--fs-ease-soft` /
`--fs-dur-enter` / `--fs-dur-quick` / `--fs-dur-ambient` / `--fs-stagger` / `--fs-stagger-tight`。
custom_css **可以**直接 `var(--fs-ease-out)`、`calc(var(--i,0) * var(--fs-stagger))` 引用,
让多份 deck 的动效语言天然一致、消灭 copy-paste 漂移。但它**不强制**——某页要自己的曲线/节奏照样自由写
(§6"别预先固化"的精神:tokens 是货架不是法令)。下面示例为可读仍写字面值,生产里优先引 token。

## 2. 护栏(不可破,破了就不安全 / 不一致 / 被冲掉)

1. **只进 `custom_css`**。
2. **触发用 is-current 直通写法**:选择器**自带 `[data-slide-key="K"]`** → `scope_selectors`
   原样直通(`_scope_one_selector` rule 1,不二次包裹);前面拼 `.slide-frame.is-current`
   → 翻到该页时祖先 class 出现、选择器开始匹配、动画从头重放(等价框架自带机制)。
   固定形:`.slide-frame.is-current .slide[data-slide-key="K"] <hook> { animation: … }`
3. **包 `@media (prefers-reduced-motion: no-preference)`**(无障碍降级,跟框架一致)。
4. **不动标题位 / 不重排容器**。位置是框架的活(fs-reveal 负责"上浮就位");动效只**加一个维度**
   (blur-in / clip-path 揭幕 / 呼吸 / Ken Burns / 错落),**落点 = 元素既有 CSS 位置**。
   位移尽量交给 fs-reveal,自己别再叠 translate,避免双重位移。
5. **不加全局动画**。全局会顶掉 fs-reveal 和各页自带 bespoke 动画。永远逐页 scope。
6. **`@keyframes` 名唯一**(keyframes 在输出里是全局的)。用前缀,如 `za*` 或 `<deck-slug>-*`,
   避免跨页 / 跟框架撞名。每页 block 自带它用到的 keyframes(自包含,可被 lift 带走)。
7. **排除这些页,别碰**:复杂 SVG / 图表 / 表格 / 多图页;**已自带动画**的页
   (`grep '@keyframes\|animation:'` 它的 data.html);`iframe-embed` / live demo 页。
   理由:会跟既有动画打架、或动到 live 内容。

## 3. 方法(layout-last + 逐页动态设计)

1. **先定稿**:布局 / 内容定稿、validator 过了,**再**加动效。动一个还在动的布局 = 白做
   (这就是 skill 的 "Layout Before Animation" 原则)。
2. **测绘**:逐页判 archetype + 找**真实挂载点**(你刚写的 HTML,或读 data.html 拿类名)。
   定哪些页加、哪些排除。结构差异大,**不能盲套一个模板**(同名 hook 在不同页可能不存在)。
3. **现场设计**:结合 deck 调性(沉稳 vs 科技)、页面角色、它的真实结构来设计。
   下面的词汇表是**起点调色板**——重混、改参、按需新增命名效果。**别照抄、别求一模一样。**
4. **应用 + 重渲染 + 视觉验证**:写进 custom_css → `render-deck.py` 重渲(自带 validator)→
   抓动画过程帧:落定帧证明没破版,中间帧证明动起来了。**用现成工具,别手写 playwright 脚本**:

   ```bash
   python3 assets/capture-frames.py <output>/index.html <key> [<key>...] \
       --settle-ms 4500   # > 页内最长 delay+duration
   ```

   一条命令产出每页 `<key>_mid.png` + `<key>_settled.png` 并自动跑 §3.5 落定断言
   (exit 0 = 过;多 key 共用一个浏览器会话)。抓完仍要**亲眼看**这两张图——断言只管
   "落定干净",动得好不好看是审美判断。"静态看着对"不算完成
   (见 [[feedback_visual_review_before_done]]、[[feedback_measure_dont_eyeball_tighten_loop]])。
5. **"卡半透明"落定断言(HTML PPT 最常见翻车点)**:动画播完后,该页所有入场元素必须真正落定,
   绝不能定格在半透明 / 偏移态(delay 算错、`both` 漏写、keyframe 终值不是 1 都会导致)。
   `capture-frames.py` 已把这条做成硬断言:settled 帧上检查该页每个 `.reveal` / 入场 hook
   (`--assert-class` 可换)computed `opacity === 1` 且无残留 `transform`,瞬态元素
   (`--transient-class`,默认 `fly`)必须已退场,且无元素溢出 `.slide` 边界。
   任一不满足 = exit 1 = 该页动效不合格,回去修终值 / `both` / delay,别交付。
   这条是 §3.4 抓帧的**硬判据**,不是"看一眼"。

## 4. 种子词汇表(可扩展,非封闭集)

| 代号 | 效果 | 典型用处 | 要点 |
| --- | --- | --- | --- |
| **A 聚焦显影** | `filter: blur(N)→0` (+opacity) | 标题 / hero | 最通用的"高级"signature |
| **B 章节仪式** | 序号 blur-in 缩定 → 标题 `clip-path:inset()` 由下揭幕 → 细线 `width:0→N` 生长 | 章节分隔页 | 全 deck 章节统一节奏才有仪式感;细线用 `position:absolute` 别挤标题 |
| **C 标题聚焦 + 内容错落** | 标题 blur-in + 卡片/行 `nth-child` 延时上浮 | 内容 / 网格页 | 卡片嵌在 stage 内不吃 fs-reveal,错落是额外揭示 |
| **D 数字落定** | `scale(.92)→1` + blur-in + 一次性辉光脉冲 | KPI / 大数字 | **真计数 0→N 需要 JS = 没有**,只做"落定强调"别承诺计数 |
| **E decor 氛围** | 设 `slide.decor` token(`aurora` / `*-glow` / `grain`,可叠加) | 深色页广泛 | 零动画风险、氛围性价比最高;不是 custom_css,是 slide 级字段 |

可新增(按页需要):扫光 / 流光(`background-clip:text` 动渐变)、mask wipe、下划线/边框描边、
卡片 sheen 掠过、hero 图 Ken Burns(`transform:scale` 缓推)…… **新效果随用随补进本表**
(写清 hook + 调性),让词汇表生长。

## 4b. 可复用基元:错落揭示 `.reveal` + `--i`

"一组元素依次揭示"(C 的内容错落、列表/卡片/行进场)统一用这一个基元,**别每页重写 nth-child**:

1. 给要揭示的元素加 class `reveal`,并在元素上写序号 `style="--i:0"` `--i:1` …
   (在 data.html / raw markup 里;顺序你定,不必跟 DOM 顺序一致)。
2. 该页 `custom_css` 放这段(`K` = slide-key;`.5s` 基偏移按需,想让它跟在标题后就留,想立即就删):

```css
.slide-frame.is-current .slide[data-slide-key="K"] .reveal { opacity: 0; }
.slide-frame.is-current .slide[data-slide-key="K"] .reveal {
  animation: zaUp .6s cubic-bezier(.16,1,.3,1) both;
  animation-delay: calc(.5s + var(--i,0) * 90ms);
}
@keyframes zaUp { from{opacity:0;transform:translateY(14px)} to{opacity:1;transform:none} }
```

要点 / 坑:
- 触发用 `.slide-frame.is-current`——框架当前页标记在**祖先 `.slide-frame`** 上,**没有 `.active`**;
  选择器自带 `[data-slide-key]` 走 scope 直通(护栏 #2)。
- **`both` 必加**:带 delay 时元素在轮到前保持 `opacity:0`,不会先闪一下。
- keyframe 用 `za*` 前缀(输出里 keyframes 全局,`up` 易撞名);`--i` 兜底 `var(--i,0)`。
- 把 `.reveal` 元素放进 `.stage` 等**容器(嵌套层)**,避开框架对 `.slide` 直接子已有的 `fs-reveal`,免双重动画(护栏 #4)。
- 不想动 markup → 退用 `:nth-child(n)` 设 delay,但同级结构一变易错位
  (本框架同级多同 tag,用 nth-child 别用 nth-of-type,见 [[feedback_css_nth_child_not_type]])。
- 节奏:`step 90ms / dur .6s / expo-out` 是沉稳档;科技档收到 `~60ms` 更紧。
- 实战见 run `20260528-192338` 的 `ai-manager-clone`(p9):3 个 benefit-chip 用 `class="… reveal" style="--i:0/1/2"` 错落。

## 4c. 扩展效果(纯 CSS,可与 A–E + .reveal 自由组合)

都不需要 JS、都进 `custom_css`、都 round-trip 安全。无限循环类只做"氛围"、必须 gated `prefers-reduced-motion`。

| 代号 | 效果 | 技法 | 落点 / 坑 |
| --- | --- | --- | --- |
| **F 路径绘制** | 线 / 对勾 / 连线"自己画出来" | SVG `stroke-dasharray:<路径长>` + 动 `stroke-dashoffset:<长>→0` | 需 SVG `<path>`(对勾/连线必须 SVG;下划线也可退用 width-grow)。确认/完成状态、流程连线 |
| **G 数据条生长** | 柱 / 进度条从 0 长到位,可错落 | `transform:scaleX(0→1)` + `transform-origin:left`(或 `width:0→N`),多条配 `.reveal/--i` | 数据页标配。**值是作者写死在 CSS 里的,不是真算**;比摆数字有说服力。scaleX 比 width 更 GPU 友好 |
| **H 文字擦入** | 标题像被布擦开 | `clip-path:inset()` 方向揭幕,或 `mask-image` 渐变扫过 | **B 章节标题已在用**(逐行);可扩 L→R 擦。金句 / 大标题专用,别滥用 |
| **I 连线流动** | 虚线缓慢流动="数据在跑" | SVG `stroke-dasharray` + `stroke-dashoffset` **无限** `linear` | 架构 / 流程图点睛。**要慢**;无限动画 gated reduced-motion |
| **J 悬浮微动** | 元素出现后缓慢上下浮 | `transform:translateY` **无限** `alternate` ease-in-out(±6–10px / 4–6s) | **只放装饰 / 背景元素,绝不放正文**(动的文字伤可读)。gated reduced-motion |
| **K 数字滚动** | 数字真从 0 滚到 N | ① `@property --n{syntax:'<integer>'}` 动画 + `counter()` 渲染(整数,无逗号/小数/单位);② 数字列"老虎机" `translateY`(任意格式,markup 重) | KPI / 数据页。**真逐帧任意缓动 + 暂停才需 JS**——那是老问题(无槽),不值得 |
| **L 起始态入场** | 元素从隐藏切出时直接过渡入场,**不写 keyframes** | `@starting-style` 声明"刚出现那一刻"的起始值 + 普通 `transition`:`@starting-style{opacity:0;transform:translateY(12px)}` 配 `transition:opacity/transform var(--fs-dur-enter) var(--fs-ease-out)` | 比 `@keyframes` 简洁,适合单元素一次性入场;翻页逻辑也简化。坑:仅当元素**新插入/从 `display:none` 切出**才触发;本框架翻页是 toggle `.is-current`(元素一直在 DOM、靠祖先类匹配重放动画),所以 §4b 的 `.reveal` keyframe 路线仍是错落入场的主力,`@starting-style` 主要给 Magic Move / 真新增节点的单点入场补位 |

**受限(需要 JS,本系统不做)**:
- **焦点引导(口播同步版)**:高亮"讲到哪亮到哪"要 within-slide step 控制,本框架 present 模式只翻页、无元素级 fragment。
  **自动循环版**(高亮按固定节奏在要点间滑动)是纯 CSS,可做(多档 `translateY` keyframe)。
- 数字 K 的"任意缓动 + 可暂停 / 可 seek"同理需 JS。

> SVG 类(F / I)最有用的图表页,往往正是 §2 护栏 #7 排除的"自带动画复杂页"——
> 这两个效果**不能批量铺**,要逐页对着该页现有动画小心叠(协调时序、别覆盖)。

## 5. 调性缩放

- **沉稳商务**(保险 / 金融 / 严肃 B2B):慢(0.5–1.2s)、`ease-out`、无 bounce、辉光克制。
- **科技酷炫**:扫光更亮、辉光更强、错落更紧(`var(--fs-stagger-tight)`)。
- 永远别给严肃 B2B 用弹跳 / 过冲。按品牌选,不固化进任何模板。
- **`linear()` 缓动(进阶)**:想要"几乎察觉不到的极轻物理感"(微弹簧)时,`linear()` 能定义任意曲线,
  表现力强过 `cubic-bezier`,例 `animation-timing-function: linear(0,.6 30%,1.02 60%,1)`。但**商业场合那条铁律不变:
  弹要弹得极轻**——过冲 ≤2%、只给科技调性、严肃 B2B 一律 `--fs-ease-out` 不过冲。

## 6. 演进

这是**活调色板,不是冻结规格**。每份 deck 从护栏出发**现场设计**;真正反复用、验证过的效果
再补进第 4 节让它长大。若某个 pattern 在很多 deck 上稳定下来,**那时**才考虑提升成 schema token
(`slide.motion: "<effect>"`,由 render-deck.py 从内置库展开成 scoped custom_css)——**等它挣到了再固化,别预先写死**。

## 7. Magic Move(翻页变形 / View Transitions)

Keynote「神奇移动」的 HTML 原生版:翻页时**同一个元素从上一页的位置/大小平滑变形到下一页的落点**,
而不是淡出再淡入。靠浏览器原生 View Transitions API,框架已接好,作者**只写纯 CSS**、round-trip 安全。

### 7.1 怎么开(deck 级 opt-in)

1. deck.json 顶层 `deck.magic_move: true` → render-deck.py 在 deck 根吐 `data-magic-move`。
2. `feishu-deck.js` 的 `goTo()` 检测到该 attr 后,把翻页那一刻的 DOM 切换包进
   `document.startViewTransition()`。**护栏全在框架里**:feature-detect(Firefox 无 → 瞬切降级)、
   仅 present 模式、首屏不触发(`wasArmed`)、`prefers-reduced-motion: reduce` 自动关。
3. 默认**关**。不开时翻页行为零变化(fs-reveal 基线照旧),所以对存量 deck 零风险。

### 7.2 怎么让某个元素"变形"(配对 `view-transition-name`)

给**前后两页的同一个元素**标**同一个** `view-transition-name`,浏览器自动补间。名字写进
**两页各自的 `slide.custom_css`**(纯 CSS,round-trip):

```css
/* 章节页的大序号 01 */
.slide-frame.is-current .slide[data-slide-key="sec-2"] .big-num { view-transition-name: chap2-num; }
/* 下一张内容页的页眉序号 —— 同名,于是 01 缩小飞到左上角变成页眉 */
.slide-frame.is-current .slide[data-slide-key="topic-2"] .page-num { view-transition-name: chap2-num; }
```

翻页时浏览器把这个元素当成"同一个",从章节页的巨大居中态**变形**到内容页的小页眉态。
一个动作就讲清"前后两页是同一个故事",这是淡入淡出做不到的叙事——也是 Magic Move 最值钱的用法。
默认 group 时序框架已给(`::view-transition-group(*)` = `--fs-dur-enter` + `--fs-ease-out`);
要单独调某个名字,在 custom_css 里写 `::view-transition-group(chap2-num){animation-duration:.5s}`。

### 7.3 护栏(Magic Move 专属,叠加 §2 通用护栏)

1. **名字全 deck 唯一**:`view-transition-name` 在一次过渡里**不能重复**,两个元素同名会报错并退化成瞬切。
   每对配一个唯一名(`<deck-slug>-<role>`),只在真正要变形的"那一对"上加,别全页乱标。
2. **只标"前后页都存在的同一逻辑元素"**:logo、章节序号、hero 图、关键 KPI 数字这类跨页延续物。
   一页有、另一页没有的元素标了也只是单边淡入淡出,不变形——不如不标。
3. **节制**:一次翻页变形元素 ≤2–3 个,否则满屏乱飞,廉价。其余元素走默认 fs-reveal 即可。
4. **演示机要 Chromium 系**(Chrome/Edge,Safari 18+ 部分支持);Firefox 优雅降级为瞬切——
   交付前确认客户演示环境,别承诺"哪都能动"。本框架已 feature-detect,不会报错,只是没动效。
5. **reduced-motion 自动关**(框架已 gate),无需你在 custom_css 再写一遍。
6. 仍守 §2:`view-transition-name` 进 custom_css、选择器自带 `[data-slide-key]` 走 scope 直通、不动布局落点。

### 7.4 验证

按 §3.4 抓帧 + §3.5 落定断言:导航过去后抓**翻页中间帧**(证明在变形)和**落定帧**(证明落到正确页眉位、
opacity===1 不卡半透明)。Firefox/降级环境单独抓一张确认"瞬切但不破版"。

## 8. GSAP 入场引擎(deck 级 opt-in,替换 fs-reveal)

平铺的 `fs-reveal`(0.28s 错峰淡入)够用但平。需要"高级感"整体动效时,可整 deck 切到 **GSAP 引擎**:
逐页编排化 timeline,**作者无需写任何 JS**,只在 deck.json 开一个开关。

### 8.1 怎么开
```jsonc
{ "deck": { "motion_engine": "gsap" } }     // 缺省 / "css" = 原 fs-reveal 基线
```
renderer 据此:① 在 `<div class="deck">` 发 `data-motion="gsap"`;② 注入本地化的
`assets/gsap/{gsap,CustomEase,SplitText}.min.js`(~88KB)+ framework 级 `assets/feishu-deck-motion.js`;
③ `--final` 时 copy-assets 把这些一并打进自包含产物。**不开这个开关的 deck 与纯 CSS 基线逐字节一致**(零注入、零行为变化)。

### 8.2 引擎做什么(按页型自动适配,通用选择器,无需逐页配)
- **标题**:正文页**逐词**升起(模糊→清晰,word-split 保持换行不改高度);封面 / 章节 / 收尾**逐字符** 3D 飞入;
  结构化标题(带 `.lead/.accent` 等子 span)自动改"逐段错峰"以免拆坏;渐变文字(`background-clip:text`)自动逐单元补回渐变。
- **内容块**:纵深错峰(下沉 + 微缩放 + 模糊渐入);嵌套卡片/列表第二波错峰。
- **SVG**:线条 draw-on(stroke-dashoffset 生长)。**数字**:`.metric/.num` 从 0 滚到目标(原文存 `data-fwd-num`,落定/打断都复原)。
- **环境微动**:`[class*=glow/orb/halo/...]` 装饰元素轻浮(落定后启动)。

### 8.3 安全设计(铁律,改引擎必守)
- **绝不全局预隐**。静止态 = framework 默认 = **可见**。只对"要动的那几个后代元素"**逐元素 inline** 关 fs-reveal +
  pin `opacity:1`,再用 `.from()` 让**终态恒为可见值**。→ GSAP 没加载/报错/某页没进场,顶多"无动画",**绝不丢内容**。
  (曾经用全局 CSS `animation:none` 杀 fs-reveal,把超高自缩放页的 `--fs-scale` 算崩、整页塌黑——已废弃,严禁回退。)
- **不碰全局测量**:不加 `.slide>*` 全局 override → 超高页 `--fs-scale` 不受影响。
- 每页 build 包 try/catch + clearProps 兜底;另有 watchdog 强制揭示任何残留隐藏的当前页。
- 监听 framework 的 `fs-slide-enter/leave`,与导航/缩放/Magic Move 共存(不替换运行时);首个 enter 在监听器挂载前触发,靠 `ensureCurrent` 重试补。

### 8.4 代价与边界(诚实记账)
- **+~88KB** vendored JS/每 deck;GSAP ticker 常驻 rAF(真浏览器无碍;**headless 虚拟时间会被它饿死**——
  `--virtual-time-budget` 截图对 GSAP deck 不可靠,present 模式多页 deck 可截、3 页 scroll 测试件会串味,属伪影非真 bug;真要逐帧验证用真实浏览器 or CDP 实时等待)。
- **validator 看不见 JS 动效**:CSSOM 的 `R-VIS-DEAD-ANIM`/`R-VIS-DEAD-RULE` 对 GSAP 恒零 finding。
  → 8.3 的"静止态恒可见"是唯一兜底:测不了动效质量,但保证不丢内容。
- **不覆盖** bespoke 逐页炫操作(Flip 放大 / MorphSVG 形变 / Draggable 物理)——那些走 iframe 逃生舱(`prototype-embed.md`)。
- 诊断:URL 加 `?nofx` 可临时关引擎(A/B 对照基线);`?mode=present` 强制 present 模式。

### 8.5 验证
present 模式多页 deck 走 §3.4/§3.5 抓帧落定断言(GSAP deck 在 present 下 headless 可正常落定截图,参 output-gsap 46 页基线);
关键是**逐页确认无内容丢失**(对照同 deck `?nofx` 或 `motion_engine:"css"` 渲染),GSAP 失败降级到"无动画即可见"。

---

参考实战:run `20260528-192338-zhongan-ai-org`(众安 × 飞书)——封面 A / 5 章节页 B /
12 金句大字页 C + E,排除复杂&自带动画&iframe 页,逐页 playwright 验证、render PASS。
关联记忆 [[feedback_pageanim_not_in_deckjson_schema]](动效持久化 = custom_css 的根因与触发配方)、
[[feedback_deck_no_global_animation]]、[[feedback_no_rebalance_whole_container_local_edit]]。
