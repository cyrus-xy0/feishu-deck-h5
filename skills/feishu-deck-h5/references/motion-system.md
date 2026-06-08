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
(若将来真要 JS 动画,必须先给 schema + render-deck.py + framework JS 加 `custom_js` + slide-change
事件这一整套——那是独立的大改,不在本规范内。)

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
   **playwright 抓动画过程帧**(导航到该页后在几个时刻截图):落定帧证明没破版,中间帧证明动起来了。
   "静态看着对"不算完成(见 [[feedback_visual_review_before_done]]、[[feedback_measure_dont_eyeball_tighten_loop]])。

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

**受限(需要 JS,本系统不做)**:
- **焦点引导(口播同步版)**:高亮"讲到哪亮到哪"要 within-slide step 控制,本框架 present 模式只翻页、无元素级 fragment。
  **自动循环版**(高亮按固定节奏在要点间滑动)是纯 CSS,可做(多档 `translateY` keyframe)。
- 数字 K 的"任意缓动 + 可暂停 / 可 seek"同理需 JS。

> SVG 类(F / I)最有用的图表页,往往正是 §2 护栏 #7 排除的"自带动画复杂页"——
> 这两个效果**不能批量铺**,要逐页对着该页现有动画小心叠(协调时序、别覆盖)。

## 5. 调性缩放

- **沉稳商务**(保险 / 金融 / 严肃 B2B):慢(0.5–1.2s)、`ease-out`、无 bounce、辉光克制。
- **科技酷炫**:扫光更亮、辉光更强、错落更紧。
- 永远别给严肃 B2B 用弹跳 / 过冲。按品牌选,不固化进任何模板。

## 6. 演进

这是**活调色板,不是冻结规格**。每份 deck 从护栏出发**现场设计**;真正反复用、验证过的效果
再补进第 4 节让它长大。若某个 pattern 在很多 deck 上稳定下来,**那时**才考虑提升成 schema token
(`slide.motion: "<effect>"`,由 render-deck.py 从内置库展开成 scoped custom_css)——**等它挣到了再固化,别预先写死**。

---

参考实战:run `20260528-192338-zhongan-ai-org`(众安 × 飞书)——封面 A / 5 章节页 B /
12 金句大字页 C + E,排除复杂&自带动画&iframe 页,逐页 playwright 验证、render PASS。
关联记忆 [[feedback_pageanim_not_in_deckjson_schema]](动效持久化 = custom_css 的根因与触发配方)、
[[feedback_deck_no_global_animation]]、[[feedback_no_rebalance_whole_container_local_edit]]。
