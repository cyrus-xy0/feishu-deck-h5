# prototype-embed — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:嵌入已有 HTML/原型/别的 slide(别默认 iframe)

## Prototype / standalone-page embed modes (mandatory) — pick BEFORE you write any code

When the user gives you existing HTML(**通常是本地路径**)and asks to "把它加进来 /
搬过来 / 拼进来 / 做成一页",**先按「源是什么」分流** —— 这一步分错就是 30 分钟
doom-loop("乱了""字小了""重叠了")。这是历史重灾区:旧版把"搬过来/原封不动"
默认导去 iframe,而用户要的常常是**原生拼接**。

| 源是什么 | 用哪种 | 为什么 |
|---|---|---|
| **一份 feishu-deck-h5 写的 slide**(或 slide 形态静态 HTML),要它**原样当一张 slide** | **Native slide lift**(原生拼接 · **非 iframe**) | 源与新 deck 共享 `feishu-deck.css`,直接 splice 就对齐,iframe 反而多此一举 |
| **外来的、自带 layout/缩放/chrome 的独立 demo / 原型 / H5**,要它当**"活的"嵌进来** | **iframe · Mode A / B** | 它有自己的世界,iframe 边界才能避免 CSS/JS 互相打架 |
| 一段简单内容(文档/截图/卡片列表),想用框架原语**重画** | **Mode C · re-author** | 想要 texts.md / brand token / 4-tier 接管 |

> **判不准就一句话问**:"这页你要它当**原生 slide 原样拼进来**,还是当**活的 demo 嵌进来(iframe)**?" —— **别默认 iframe**(历史上这里一直默认错)。

下面先讲 **Native slide lift**,再讲 iframe 的 Mode A / B / C:

| # | iframe Mode | When(源都是**外来独立页**) | Layout in deck.json | Deck chrome |
|---|---|---|---|---|
| **A** | **Full-bleed** · 外来 demo 占满整页 | 独立 H5/原型,自带 title+logo+layout,要当"活的" | `raw` (with `_orig_layout: "image-text"`) | **HIDDEN** |
| **B** | **Framed** · deck 给标题栏+wordmark,demo 填下方 | "嵌入到当前页面" / "做一页 demo,标题是 X" | `iframe-embed` (schema-native) | **VISIBLE** |
| **C** | **Native re-author** · 用框架原语重画(非 verbatim) | 简单内容,想要 texts.md/brand token/4-tier | `raw` / schema `content/2col` 等 | VISIBLE per layout |

### Native slide lift (原生拼接 · 非 iframe · 从本地路径搬现成 feishu slide)

**触发**:用户给一个**本地路径**(一份 feishu-deck-h5 deck 的 `index.html`,或 slide
形态的 HTML)+ "把第 N 页 / 这几页 / 这个 slide **搬过来 / 原样拼进来 / 加进来**"。
这是用户的常用工作流——**他发路径,你就基于路径把对应 slide 原样加进当前 deck,
不反问"拿来干嘛"**。典型场景:"我以前写了 50 页,这次从里面挑 3 页讲,拼起来,
一点都不能动。"

**为什么不用 iframe**:源 slide 本来就是 feishu-deck-h5 写的,和新 deck 共享同一套
`feishu-deck.css` + present-mode JS。直接把它的 `.slide-frame` splice 进来就**逐像素
对齐**——不需要 iframe 隔离、不需要 scope CSS、不需要重画。iframe 在这里是**错的工具**
(那是给"外来自带壳的 demo"的,见 Mode A)。这是它和 Mode A 的根本区别。

**手工流程**(没有也不需要一键工具,手工拼):

1. 打开源路径 `index.html`,按 `data-slide-key` / `data-screen-label` / 第几个
   `.slide-frame` 定位目标 slide。
2. 整块剪出 `<div class="slide-frame"> … </div>`(到配对的 `</div>`)**verbatim**。
   **别用正则吃 DOM** —— 手工读 + 整块复制(见 EDITING DISCIPLINE E2 / R-DOM)。
3. **带上它依赖的 per-page 样式**:源 `<head>` 里 scope 到这张的
   `<style>[data-page="NN"] …</style>` / `[data-slide-key="KEY"] …` 块,一起搬。
4. **拷它引用的资源**:`background-image:url(...)` / `<img src>` / iframe `src` 指向的
   `input/*`、`assets/shared/*`、`prototypes/*`,复制进新 deck 并保持相对路径解析。
5. splice 进新 deck 的 `.deck` 容器,顺序随你排。
6. **de-collision(只动管线,不动设计)**:
   - `data-page` 撞车(两张都用 `03` 但 scoped CSS 不同)→ 把搬进来这张的 `data-page`
     连同它的 `[data-page="03"]` 选择器一起改成唯一值。
   - `data-slide-key` 撞 → 改唯一 key。
   - **`data-text-id` 一律剥掉**(`re.sub(r'\s+data-text-id="[^"]*"', '', inner)`)
     —— 那是源 deck 的**定位编号**(如 `slide-05.c1.desc`),带过来会让新 deck 的
     texts.md 漂移、触发 **T03 error**。它是隐形属性,剥掉不改任何可见内容。
   - 资源重名(都叫 `input/scene.png` 但不同图)→ 改文件名 + 同步引用。
   - **以上全是编号 / 文件名层面,不改你看到的任何内容 / 设计。**
7. **内容逐字不动;标 `lifted`,但别哑掉校验**(2026-05-27 改,取代旧的"校验可跳"):
   给搬进来的页加 lift 标记 —— deck.json 里 `"lifted": "<源 deck>#<N>"`(纯拼接手写
   `index.html` 时直接在 `.slide` 上加 `data-lifted="<源>"`)。**校验照常跑(含
   `--visual`)**,validator 自动按 lift 分级:
   - **字号 / 配色违规(R06 / R-VIS-BODY-FLOOR / R-VIS-TIER / R-WHITE-TEXT)→ 降为
     warning**:旧页就是当年的字号,提示你"要不要 bump",**不阻塞,人来选修不修**。
   - **几何 / 溢出(R-OVERFLOW / R-VIS-CARD-OVERFLOW,含没设 `overflow:hidden` 的
     可见溢出)→ 仍是 error,必修**:真溢出跟 verbatim 与否无关。
   - **不要再 `--skip-validate-html`** —— 它会把溢出这种真故障一起哑掉(星巴克 P3 就这么
     漏了 61px 卡内溢出,直到用户肉眼发现)。

> **raw layout 自动继承母版定位(2026-05-28)**:
> `data-layout="raw"` 起,**`.header` 和 `.stage` 自动继承母版定位**
> (`feishu-deck.css` 把 `raw` 加进 unified rules):
> - `.header { position:absolute; top:61; left:73; right:320; }`
> - `.stage { position:absolute; top:200; bottom:200; left:96; right:96; flex column center; gap:24; }`
> - `.slide-frame` 在 present-mode 用 `lark-content-bg.jpg` 填 letterbox(早在 2026-05-08 已是这样)
>
> 这意味着 lift 时**通常不需要手补这些定位**,直接搬,框架默认值自动撑住。
> **特例**:
> - 源 slide 自己有 `.stage / .header` 的 inline CSS(custom top/bottom/gap 等)→ slide-key 选择器更具体,会覆盖框架默认。源 inline 通常只 override `top/bottom/gap`,依赖框架 cascade 给 `position:absolute + left:96 + right:96` —— 现在框架统一规则补上了,**源 inline 半自含也能工作**。
> - 源 slide 要全幅(no padding)→ inline `<style>` 写 `.slide { padding: 0 !important }` 或 redeclare `.stage` with `!important`,绝对优先级赢框架默认。
> - 历史 lift(2026-05-28 之前用 per-slide `.header / .stage` 注入手补的)现在那些注入是冗余的,可以删,但留着也无害(同值不冲突)。
>
> **抽取实战坑(2026-05-27 · 复杂 slide 必看)**:
> - **inner 用 frame 边界切,别 div 计数**:`<div`/`</div>` 平衡计数在大 / 嵌套深的
>   slide 上会数错、把后面几张 frame 一起吞进来(→ R-DOM 嵌套 + R-KEY 重复)。
>   稳妥:取「本 `slide-frame` 起点 → 下一个 `slide-frame` 起点」之间,再剥掉外层
>   frame + slide 两个 `</div>`。抽完**自检**:inner 里不应再有 `slide-frame` / 别的
>   `data-slide-key`,且 `<div`==`</div>`。
> - **CSS 可能写在 slide 自己的 inline `<style>` 里**(不在 head)。这时**直接 rescope
>   inner 本身**(含它的 inline style),别再单独抽一份(会重复 + 漏 rescope)。
> - **要单独抽 head CSS 时,只在 `<style>…</style>` 内部跑规则正则**,别 regex 整个文件
>   —— 否则会跨过 `</style>` 把 body 的 HTML(slide-frame 标记)当"选择器"吞进来。
> - **rescope 前先剥 CSS 注释 + 用容忍空白的正则**(2026-05-27 血泪):源选择器里
>   可能夹注释,如 `[data-page="35"] /* 注释 */ .slide .cards-row {…}`。直接字符串
>   `.replace('[data-page="35"] .slide ', …)` 匹配不到(中间隔着注释),只把
>   `[data-page="35"]` 换成 anchor → 留下**多余的 `.slide`** → `.slide[key] .slide
>   .cards-row`(双 .slide)匹配不到任何元素 → 该规则(常是 2 列网格)失效、布局崩,
>   而且**校验反而 0 error**(规则没生效 = 没字号违规)。先 `re.sub(r'/\*.*?\*/','',css)`
>   剥注释,再 `re.sub(r'\[data-page="NN"\]\s+\.slide\b', anchor, css)`(容忍空白)。
> - **整页 CSS 整块抓**:CTG 用 `/* === page NN === */` 注释分隔每页 CSS,按这个
>   边界整块抓,比"挑 `[data-page]` + 基础规则"更全(挑的会漏复杂页的规则)。
> - **rescope 锚点看源怎么 scope**:`[data-page="NN"] .slide`(注意 data-page 在
>   `.slide-frame` 上)/ `.slide.slide-xxx` class / `.slide .x` 通用 —— 全部换成
>   `.slide[data-slide-key="<key>"]`。
> - lift 页的 **R06 / R-VIS-BODY-FLOOR / R-VIS-TIER / R-VIS-LABEL-FLOOR / R-WHITE-TEXT**
>   会因 `lifted` 自动降 warning;**几何/overflow 仍 error**。

**两种装配方式**:
- **纯拼接**(只搬现成页、不混新页)→ **直接手工组装 `index.html`**(标准 shell +
  搬来的 slide-frames),最"一点不动";给每张 lift 的 `.slide` 加 `data-lifted="<源>"`,
  然后 `check-only.sh <index.html> --visual` 拿到同样的"字号 warning / 溢出 error"分级。
- **混装**(搬来的页 + 新设计的页同处一 deck)→ 每张搬来的 slide 作为
  `layout: "raw"` + `"lifted": "<源>#<N>"` 放进 deck.json(`.slide` 的 inner 塞进
  `data.html`),新页走 schema,一起 `render-deck.py … --visual`(**不加 --skip**)。

**和 DESIGN PHASE 的关系**:lift 进来的页在设计方案表里标「**源自 `<path>` 第 N 页 ·
原样未改**」,DESIGN PHASE 对它们**不做角色判断 / 不补内容 / 不写六维** —— 它们已是
成品。设计只作用于新加的框架页(封面/章节/结尾)和整体顺序。

### Mode A · Full-bleed slide (verbatim port · iframe)

This is for a **foreign, self-contained** prototype / H5 / demo: it has its own
`<title>`, internal logo, internal scale-to-fit JS, its own background. Deck framework
chrome would **collide** with it, so give it the entire `1920×1080` canvas via an
**iframe** and tell the deck to add nothing. **A feishu-deck slide from another deck
does NOT belong here** —— 那走上面的 **Native slide lift**(原样 splice,不套 iframe)。

```json
{
  "key": "<prototype-slug>",
  "layout": "raw",
  "_orig_layout": "image-text",
  "screen_label": "NN <topic>",
  "data": {
    "html": "<style>.slide[data-slide-key='<prototype-slug>'] { position: absolute; inset: 0; background: #080C18; overflow: hidden; }\n.slide[data-slide-key='<prototype-slug>'] iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; display: block; transform: scale(1.018); transform-origin: center center; }\n.slide[data-slide-key='<prototype-slug>'] .wordmark { display: none; }\n.slide[data-slide-key='<prototype-slug>'] .header { display: none; }</style><div class=\"wordmark\"></div><iframe src=\"prototypes/<prototype-slug>/index.html\" title=\"<demo title>\" loading=\"lazy\"></iframe>"
  }
}
```

Then `cp -r <source-deck>/prototypes/<slug> runs/<ts>/output/prototypes/` and you're done.

**`transform: scale(1.018)` is intentional** — standalone prototypes commonly compute
`min(window.innerWidth/W, window.innerHeight/H)` and cap at one axis, leaving 15px black
gutters. The 1.018 scale-up nudges the prototype past the gutters to fill 1920 cleanly.
Adjust per-prototype if needed.

### Mode B · Framed embed (iframe-embed schema)

This is the "**give me a demo slide titled X**" case. Deck contributes the chapter
title + 飞书 logo, prototype lives in the body area:

```json
{
  "key": "<demo-slug>",
  "layout": "iframe-embed",
  "screen_label": "NN <topic>",
  "data": {
    "title": "<deck-level chapter title>",
    "src": "prototypes/<demo-slug>/index.html",
    "iframe_title": "<a11y label>",
    "hint": "<optional bottom-right caption>"
  }
}
```

### Mode C · Native HTML re-author

Reserved for when the source is simple enough to redraw using framework primitives
(`.card`, `.kpi-strip`, `.data-panel`, `.ui-*`, etc.) AND you want `texts.md` editing,
brand tokens, 4-tier typography to apply. See "Re-render UI mocks as HTML, not
screenshots" earlier in this file. **Do NOT use this mode for a complex
standalone prototype** — its internal CSS (`:root` vars, absolute positioning,
custom scale JS) will fight the framework's stage / header / wordmark. See
anti-pattern below.

### Anti-pattern (this is the doom loop) · don't try to inline a complex prototype

Symptom: you start by copy-pasting prototype `<style>` + `<body>` into a raw slide's
`data.html`, then spend an hour:

- scoping every `:root { --x }` to `.slide[data-slide-key="..."] { --x }`
- prefixing every selector to avoid leaking
- rewriting the prototype's `window.innerWidth/W` scale logic to use slide dims
- adding `/* allow:typescale */` to every minified rule body to silence R06
- realizing the prototype's `position: absolute` children fight `.stage` / `.header`
- being told it "全乱了" and asked "有这么麻烦么"

**Yes, it's that hard, and it's the wrong tool.** When you catch yourself doing any
of the above on a standalone prototype HTML, stop and switch to **Mode A** (or B if
the deck needs a title overlay). The iframe boundary is what makes "verbatim port"
actually verbatim — without it, you're rebuilding the prototype inside the slide's
DOM tree and fighting every collision by hand.

### Decision recipe (90% of cases)

| 用户给的 + 说的 | 用哪种 |
|---|---|
| **本地路径 + feishu slide** · "把(第N页/这几页/这个 slide)搬过来 / 复制这页 / 原样拼进来 / 加进来 / 一点不动" | **Native lift**(splice · 非 iframe) |
| **外来独立 demo/原型** · "原封不动嵌这个 demo / 直接插入这个原型 / 把这个交互页放进来" | **A**(iframe 全幅) |
| "做一页 demo · 标题是 X" / "嵌入到当前页面" / "加个 demo,deck 给标题" | **B**(iframe framed) |
| "把这个文档/PDF/截图 重新用 native 组件画" / "用 .card / .kpi-strip 重做" | **C**(re-author) |
| 只给 URL/HTML 没说要干嘛 | **问**:"当**原生 slide 拼**(Native lift)还是当**活 demo 嵌**(iframe)?" — 别猜、**别默认 iframe** |

> 区分关键不在"搬/插入/原封不动"这些词(两类都这么说),而在**源是什么**:
> 一份 **feishu slide** → Native lift;一个**自带壳的独立 demo/原型** → iframe。

---


## Embedding prototypes (iframe rules)

Decks regularly embed live UI prototypes. There's a checklist for this — every
item below has bitten us before:

1. **Always copy the prototype HTML to the deck's outputs/ folder before
   embedding.** Never use `file:///Users/.../Downloads/...` or any user-local
   absolute path. When the deck is shared, the recipient won't have that file.
   Copy → reference with a relative path (`./prototypes/foo.html`).

2. **Strip "原型 / Demo" labels at the source, not via CSS.** `grep` and
   `replace` the `<div class="…demo-label…">…</div>` out of the prototype's
   HTML. CSS hiding leaves layout artifacts and screen-reader noise. Source
   stripping is 100× cleaner.

3. **Mobile prototype → wrap in `.phone-frame`** (CSS class shipped with the
   skill):
   ```html
   <div class="phone-frame">
     <div class="phone-screen">
       <iframe src="./prototypes/mobile.html" loading="lazy"></iframe>
     </div>
   </div>
   ```
   The notch (`::before`) and home indicator (`::after`) are decorative and
   already have `pointer-events: none` — without that the user reports "buttons
   don't respond".

4. **Desktop prototype → `.desktop-frame`** (no phone shell):
   ```html
   <div class="desktop-frame">
     <iframe src="./prototypes/desktop.html" loading="lazy"></iframe>
     <div class="iframe-hint">原型可点击 · Click anywhere</div>
   </div>
   ```
   The hint pill fades out after 7 s (already in CSS) and has `pointer-events:
   none` so it doesn't block clicks.

5. **iframe content too big? Scale it.**
   ```css
   .my-iframe { zoom: 0.88; }
   /* OR with width/height compensation */
   .my-iframe {
     transform: scale(0.88);
     width: calc(100% / 0.88); height: calc(100% / 0.88);
   }
   ```

6. **iframe tabs wrapping** is usually a font-size issue. Edit the
   prototype's source: `font-size: 11px`, `white-space: nowrap`,
   `flex-shrink: 0` on tab labels. If the prototype is bundled as base64 +
   gzip, decode → edit → re-gzip → re-encode (the `python -c` one-liner with
   `base64 + gzip + JSON` is the standard move).

7. **EVERY decorative overlay above an iframe needs `pointer-events: none`.**
   That includes hint pills, phone notches, home indicators, brand watermarks,
   timestamp chrome. Without it the prototype receives clicks but nothing
   happens — and the user thinks the prototype is broken.

8. **JSX / React prototypes MUST be pre-compiled — never Babel-runtime on
   `file://`.** A prototype whose `index.html` uses
   `<script type="text/babel" src="app.jsx">` + a CDN `@babel/standalone`
   renders **completely BLANK when the deck is opened via `file://`** (the
   normal way the user views a deck). Two reasons, either fatal:
   - Babel-standalone fetches each `.jsx` via XHR; on `file://` the browser
     blocks that as a cross-origin request (origin is `null`) → the JSX
     never transpiles → empty `#root`.
   - The CDN `<script src="https://unpkg.com/...">` needs live internet; an
     offline presentation gets nothing.

   **Symptom**: the slide shows the title + the iframe's bordered frame, but
   the frame is empty/black. The screenshot looks like a hollow box. Check
   the prototype's `index.html` for `type="text/babel"` and `unpkg.com`/CDN
   `src`s — that combination is the tell.

   **Fix (make it self-contained + file://-safe + offline)**:
   1. Pre-transpile every `.jsx` → plain `.js`. Babel-standalone runs fine in
      Node: `global.Babel = require('./babel.min.js');
      Babel.transform(src, { presets: ['react'] }).code`. Also transpile any
      inline `<script type="text/babel">` boot block.
   2. Vendor `react` + `react-dom` locally (`vendor/*.production.min.js`,
      ~140 KB total) instead of unpkg.
   3. Rewrite `index.html` so every script is a plain local
      `<script src="vendor/react.min.js">` / `<script src="compiled/app.js">`
      — no `type="text/babel"`, no CDN, no runtime Babel (drop the ~3 MB
      `babel.min.js` from the runtime entirely).
   4. Keep the `.jsx` as source; regenerate `compiled/*.js` whenever you edit
      one (and remember the rendered text now comes from `compiled/*.js`, so
      a copy change means: edit `.jsx` → recompile → the `.js` updates).

   Regular `<script src="x.js">` (and `data.js`, plain CSS `<link>`) load fine
   on `file://` — only Babel's XHR fetch of `.jsx` is blocked. So the cure is
   to remove JSX-at-runtime, not to inline cleverly. (Surfaced 2026-05-25 on
   the kangshifu `dealer-five-maps` five-maps demo — it shipped Babel-runtime
   and was blank on `file://`.)

---

