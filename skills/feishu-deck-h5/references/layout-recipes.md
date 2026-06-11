# layout-recipes — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:手写/换皮 slide markup · variant 纪律 · 居中 · CSS 陷阱

## Layout recipes (canonical copy-paste markup)

Each recipe below is the exact markup the agent should drop into a `.slide-frame`.
The markup uses only tokens defined in `assets/feishu-deck.css`.

## Raw Grid Authoring Rules

When writing `layout: raw` grid pages, make grid tracks shrinkable from the first
draft:

- Use `repeat(N, minmax(0, 1fr))` for fixed rows and columns. CSS Grid's default
  `1fr` behaves like `minmax(auto, 1fr)`, so logos, square cells, or long images
  can force tracks wider/taller than the available frame and clip the row.
- Add `min-width: 0; min-height: 0; overflow: hidden` to grid children that hold
  logos, images, or long labels.
- For an absolutely positioned grid container with fixed `top`/`bottom`, a
  single-row grid still sizes to content unless told otherwise. Set
  `grid-template-rows: minmax(0, 1fr)` when the row should fill the container.

This avoids the common render-measure-fix loop where the last logo row disappears
or the page keeps an obvious bottom blank.

### 1. Cover (`data-layout="cover"`) — matches 飞书 母版 slideLayout1

The cover uses the master flower background (`lark-cover-bg.jpg`) with content positioned on the **left half** (the dark negative space). The color logo sits **top-left** at master coordinates. Title is **100 px / 700** (smaller than you'd expect — that's the master's spec). No eyebrow, no subtitle, no keyline bar, no footer chrome.

The cover is intentionally minimal: **title + initiator's personal name + date, nothing else.** No English subtitle. No team / company / department label. The flower image and the title carry the entire composition. (See "Step 2 · Cover page" above for the full rationale.)

```html
<div class="slide" data-layout="cover" data-screen-label="01 Cover">
  <div class="wordmark">飞书</div>
  <div class="stage">
    <h1 class="title title-zh" data-text-id="slide-01.title">先进团队的<br>工作方式</h1>
  </div>
  <div class="author">
    <span data-text-id="slide-01.author">杰森</span><br>
    <span data-text-id="slide-01.date">2026.04.30</span>
  </div>
</div>
```

Note: cover (and `image-text`, `end`) are HERO_TITLE_LAYOUTS — `<br>` is allowed
inside their titles. The validator (R13) skips `<br>` checking on these three.

Master pixel grid (1920×1080 design canvas):
- Logo top-left: `120, 113` size `235×74` (color logo with petals + 飞书 wordmark — `lark-logo.png`)
- Title: `124, 285`, max-width `884`, font 100/700
- Author block: `124, 720` (2026-05-06 · was 803), font 30/600 — two stacked spans, name on top, date below. Do NOT use `.role` muted prefix on the cover (the date alone is enough chrome).
- Right half: reserved for the flower image — DO NOT place text there.

### 2. Agenda (`data-layout="agenda"`) — vertical pill stack (v2, 2026-05-06)

The agenda layout was rebuilt 2026-05-06 from the v1 TOC-grid into a
**vertical pill stack** matching the 飞书 master 议程页 spec. Three
(or up to ~6) pills stack centered on the canvas. NO header by default —
the pills ARE the content. Each pill carries an italic blue numeral
(01/02/03 …) + a single white title line.

```html
<div class="slide" data-layout="agenda" data-accent="blue" data-screen-label="02 Agenda">
  <div class="wordmark"></div>
  <div class="toc">
    <div class="item"><div class="n">01</div><div class="title-zh" data-text-id="slide-02.item-01">飞书的定位和商业化进展</div></div>
    <div class="item"><div class="n">02</div><div class="title-zh" data-text-id="slide-02.item-02">飞书对博裕及星巴克价值</div></div>
    <div class="item"><div class="n">03</div><div class="title-zh" data-text-id="slide-02.item-03">飞书差异化优势</div></div>
  </div>
</div>
```

#### Recap variant — highlight one item (entering chapter)

When the deck has multiple chapters and you re-show the agenda before
each chapter (a recap page), dim the inactive items and highlight the
active one with `class="is-active"`. The active pill border becomes
teal and the numeral picks up the teal accent.

```html
<div class="item is-dim"><div class="n">01</div><div class="title-zh">飞书的定位和商业化进展</div></div>
<div class="item is-active"><div class="n">02</div><div class="title-zh">飞书对博裕及星巴克价值</div></div>
<div class="item is-dim"><div class="n">03</div><div class="title-zh">飞书差异化优势</div></div>
```

#### Header variant — opt-in `data-variant="with-header"`

If the deck genuinely needs a top header (rare — the pills usually
speak for themselves), opt in with `data-variant="with-header"` on
the `.slide` element. The header reappears at top:96 and the pill
stack shifts down to make room. Default = header hidden.

```html
<div class="slide" data-layout="agenda" data-variant="with-header" data-screen-label="02 Agenda">
  <div class="wordmark"></div>
  <div class="header"><h2 class="title-zh">本次汇报共三个部分</h2></div>
  <div class="toc"><!-- pills --></div>
</div>
```

#### Bilingual opt-in

For ZH+EN bilingual decks, add `<div class="title-en">` next to the
ZH line per item — the CSS renders it as a small EN sub-line below
each pill title. ZH-only is the default per LANGUAGE POLICY.

#### Why the rebuild

The v1 TOC-grid (2-column rows with hairline borders) read as a list,
not a focal divider. The 飞书 master 议程页 uses a single-frame pill
stack centered on a section gradient — visually closer to "here's what
this deck covers, in 3 acts" than "here's a long content list." User
feedback 2026-05-06 ("目录这个布局不好看,改成竖排,参考 PDF 第二页布局")
confirmed the pill style as the new default.

### 3. Section (`data-layout="section"`) — matches 飞书 母版 slideLayout3 一级章节页

Chapter divider. Big numeral with a period (`02.` not `02`), section title below, optional lede + product pills. Master positioning is **160 px** for the numeral (NOT 280) — anything larger gets clipped at the line-box top by `-webkit-background-clip:text`.

```html
<div class="slide" data-layout="section" data-screen-label="03 Section">
  <div class="wordmark">飞书</div>
  <div class="chapter-num">02.</div>
  <h2 class="title title-zh">先进团队的工作方式</h2>
  <p class="lede">即时同步 · 共识对齐 · 闭环交付</p>
  <div class="pills">
    <span class="pill">飞书消息</span>
    <span class="pill">飞书文档</span>
    <span class="pill">飞书多维表格</span>
    <span class="pill">飞书知识库</span>
    <span class="pill">飞书视频会议</span>
  </div>
</div>
```

Master pixel grid (1920×1080):
- Logo: top-right at `1677, 61` (mono-white)
- `.chapter-num`: `126, 271`, font **160/700** (master is 80 pt = 160 px on 1920 canvas)
- `.title`: `126, 447`, font **88/700**
- `.lede`: `126, 597`, font 36/500
- `.pills`: `126, bottom 96` row of ghost pills
- Background: `lark-section-bg.jpg` (cool blue glow on the right edge)

### 4. Content 3-up (`data-layout="content-3up"`)

```html
<div class="slide" data-layout="content-3up" data-accent="blue" data-screen-label="04 Content">
  <div class="wordmark">Lark</div>
  <div class="header">
    <h2 class="title-zh">先进团队的三大工作方式</h2>
  </div>
  <div class="grid">
    <div class="card">
      <div class="head">
        <div class="tile"><svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></div>
        <div class="num">01</div>
      </div>
      <h3 class="ctitle">即时同步<br>Instant sync</h3>
      <p class="cbody">30 万人组织,一封消息触达全员,3 秒内全部已读。</p>
      <div class="cfoot"><span>MESSENGER · DOCS</span><svg width="20" height="20" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg></div>
    </div>
    <div class="card">
      <div class="head">
        <div class="tile"><svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></div>
        <div class="num">02</div>
      </div>
      <h3 class="ctitle">共识对齐<br>Aligned consensus</h3>
      <p class="cbody">所有讨论沉淀进 Wiki,决策可追溯,新成员第一天就能看到全貌。</p>
      <div class="cfoot"><span>WIKI · BASE</span><svg width="20" height="20" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg></div>
    </div>
    <div class="card">
      <div class="head">
        <div class="tile"><svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg></div>
        <div class="num">03</div>
      </div>
      <h3 class="ctitle">闭环交付<br>Closed-loop delivery</h3>
      <p class="cbody">从需求到上线,流程在 Base 中自动流转,每一步都有责任人和时间戳。</p>
      <div class="cfoot"><span>BASE · MEETINGS</span><svg width="20" height="20" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg></div>
    </div>
  </div>
</div>
```

### 5. Content 2-col (`data-layout="content-2col"`)

```html
<div class="slide" data-layout="content-2col" data-accent="blue" data-screen-label="05 Content">
  <div class="wordmark">Lark</div>
  <div class="header">
    <h2 class="title-zh">让流程在表格里运转</h2>
  </div>
  <div class="grid">
    <div class="col-text">
      <p class="lede">Lark Base 把任务、工单、合同、人员、审批,统一到一个可视化的多维表格。</p>
      <ul class="feature-list">
        <li>看板、甘特、日历、卡片视图,一份数据多种视角。</li>
        <li>关联字段把分散的表打成网,数据不再孤立。</li>
        <li>触发器 + 自动化,把人手 工 操作变成系统行为。</li>
        <li>开放 API,与 ERP、CRM、自研系统双向同步。</li>
      </ul>
    </div>
    <div class="col-visual">
      <!-- 〔TODO drop in product UI screenshot or SVG mock here〕 -->
    </div>
  </div>
</div>
```

### 6. Quote (`data-layout="quote"`)

```html
<div class="slide" data-layout="quote" data-accent="blue" data-screen-label="06 Quote">
  <div class="wordmark">Lark</div>
  <div class="stack">
    <hr class="keyline">
    <blockquote>飞书让 30 万人 <span class="accent-text">像一个团队</span> 一样工作。</blockquote>
    <div class="attrib">某头部互联网公司 · CIO · 2024</div>
  </div>
</div>
```

### 7. Stats (`data-layout="stats"`, accent teal)

```html
<div class="slide" data-layout="stats" data-screen-label="07 Stats">
  <div class="wordmark">Lark</div>
  <div class="header">
    <h2 class="title-zh">飞书带来的可量化结果</h2>
  </div>
  <div class="grid">
    <div class="col">
      <div class="tile sm"><svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg></div>
      <span class="trend">↑ 触达</span>
      <div class="num">3<span class="unit">秒</span></div>
      <div class="label">30 万人组织全员消息送达时延</div>
      <div class="source">Source · 内部传输实测 2024 Q4</div>
    </div>
    <div class="col">
      <div class="tile sm"><svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></div>
      <span class="trend">↑ 已读</span>
      <div class="num">98<span class="unit">%</span></div>
      <div class="label">关键通知 30 分钟内已读率</div>
      <div class="source">Source · 12 家头部企业平均</div>
    </div>
    <div class="col">
      <div class="tile sm"><svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg></div>
      <span class="trend">↑ ROI</span>
      <div class="num">3.2<span class="unit">×</span></div>
      <div class="label">部署 12 个月后协同 ROI 中位数</div>
      <div class="source">Source · IDC 2024 商务白皮书</div>
    </div>
    <div class="col">
      <div class="tile sm"><svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg></div>
      <span class="trend">↓ 决策</span>
      <div class="num">&lt;60<span class="unit">秒</span></div>
      <div class="label">关键决策从发起到对齐时长</div>
      <div class="source">Source · 客户访谈 N=24</div>
    </div>
  </div>
  <p class="footnote">数据样本: 12 家中国头部企业,2024 Q3-Q4 实测,口径见附录 A.</p>
</div>
```

### 8. Big stat (`data-layout="big-stat"`)

```html
<div class="slide" data-layout="big-stat" data-accent="blue" data-screen-label="08 Big Stat">
  <div class="wordmark">Lark</div>
  <div class="stage">
    <div class="num">30<span class="unit">万人</span></div>
    <div class="copy">
      <div class="eyebrow">SCALE · 极限规模</div>
      <h2 style="margin-top:14px">单一组织,统一协同</h2>
      <p>飞书的消息、文档、视频会议在 30 万人量级下保持秒级响应,且不依赖私有部署。</p>
    </div>
  </div>
</div>
```

### 9. Image-text (`data-layout="image-text"`)

```html
<div class="slide" data-layout="image-text" data-accent="blue" data-screen-label="09 Image"
     style="background-image:url('〔your-photo.jpg〕');">
  <div class="wordmark">Lark</div>
  <div class="stage">
    <div class="eyebrow">CUSTOMER · 一线场景</div>
    <h2 class="title">现场决策,<br>从未离线</h2>
    <p class="lede">门店、产线、出差、远程,飞书让每一处节点都能即时被看到、被对齐。</p>
  </div>
</div>
```

### 10. Table (`data-layout="table"`)

```html
<div class="slide" data-layout="table" data-accent="blue" data-screen-label="10 Table">
  <div class="wordmark">Lark</div>
  <div class="header">
    <h2 class="title-zh">飞书与传统办公套件</h2>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>能力</th><th>飞书 Lark</th><th>传统套件 A</th><th>传统套件 B</th></tr>
      </thead>
      <tbody>
        <tr><td>消息 + 文档 + 表格 + 会议 一体化</td><td>原生集成</td><td>多产品拼接</td><td>多产品拼接</td></tr>
        <tr><td>多维表格 (Base) 自动化</td><td>核心能力</td><td>第三方插件</td><td>不支持</td></tr>
        <tr><td>30 万人级消息触达</td><td>3 秒内全员</td><td>未公开</td><td>未公开</td></tr>
        <tr><td>跨域中英双语支持</td><td>原生</td><td>需配置</td><td>需配置</td></tr>
        <tr><td>开放 API + Webhook</td><td>全量开放</td><td>受限</td><td>受限</td></tr>
      </tbody>
    </table>
  </div>
</div>
```

### 11. Timeline (`data-layout="timeline"`)

```html
<div class="slide" data-layout="timeline" data-accent="blue" data-screen-label="11 Timeline" style="--cols:4">
  <div class="wordmark">Lark</div>
  <div class="header">
    <h2 class="title-zh">12 周落地路径</h2>
  </div>
  <div class="nodes">
    <div class="node"><div class="when">W1-2</div><div class="what">需求蓝图</div><div class="desc">访谈 6 部门, 输出协同地图与目标 KPI。</div></div>
    <div class="node"><div class="when">W3-5</div><div class="what">关键流程上线</div><div class="desc">销售、HR、财务三条核心流在 Base 中先跑通。</div></div>
    <div class="node"><div class="when">W6-8</div><div class="what">全员推广</div><div class="desc">分层培训, 关键岗位 100% 接入, 数据搬迁完成。</div></div>
    <div class="node"><div class="when">W9-12</div><div class="what">数据复盘</div><div class="desc">复盘 KPI, 调整流程, 形成长期治理机制。</div></div>
  </div>
  <div class="axis"></div>
</div>
```

### 12. Process (`data-layout="process"`)

```html
<div class="slide" data-layout="process" data-accent="blue" data-screen-label="12 Process" style="--cols:4">
  <div class="wordmark">Lark</div>
  <div class="header">
    <h2 class="title-zh">需求到交付,四步成型</h2>
  </div>
  <div class="flow">
    <div class="step"><div class="stnum">01</div><h3>提出</h3><p>任意一线员工在 Messenger 发起,自动落入 Base 队列。</p></div>
    <div class="step"><div class="stnum">02</div><h3>对齐</h3><p>相关方在 Docs 留痕讨论,关键决策沉淀到 Wiki。</p></div>
    <div class="step"><div class="stnum">03</div><h3>交付</h3><p>负责人在 Base 中流转, 责任人 + 时间戳每一步可追溯。</p></div>
    <div class="step"><div class="stnum">04</div><h3>复盘</h3><p>会后 Meetings 自动生成纪要, 关键指标进入下个周期。</p></div>
  </div>
</div>
```

### 13. End / closing (`data-layout="end"`) — matches 飞书 母版 slideLayout8 封底带 slogan

The master closing is intentionally minimal: same flower background as the cover, the color logo top-left, and the brand slogan **"先进团队 先用飞书"** as a PNG (`lark-slogan.png`). NO title, NO CTA pills, NO contact grid. The slogan IS the message.

```html
<div class="slide" data-layout="end" data-screen-label="13 End">
  <div class="wordmark">飞书</div>
  <div class="slogan" role="img" aria-label="先进团队 先用飞书"></div>
  <!-- optional small contact line — not in the master, but allowed -->
  <div class="contact">contact@feishu.cn  ·  feishu.cn</div>
</div>
```

Master pixel grid:
- Logo top-left: `120, 121` size `235×74` (color)
- Slogan PNG: `102, 348` size `561×345` (loaded from `--fs-asset-slogan`)
- Optional `.contact` line: `124, bottom 80` (off-master but allowed)

If you genuinely need a CTA on the closing (e.g. for an internal pitch where someone asked for it), break with the master and use a pill row — but flag the deviation. Default = stay with the master.

---


## Layout default: content sizes itself, the stage centers it

Most decks have at least one slide where the content is genuinely shorter
than the canvas (e.g. a 3-card recommendation summary, a 3-stat KPI row, a
quote). The default layout should never leave content stranded at the top
of an empty canvas; it should center vertically and let the content take
its natural height.

This applies to **every container layout** that holds a fixed number of
content blocks: `content-3up`, `content-2col`, `agenda`, `process`,
`stats`, `big-stat`, `quote`.

> Note on container naming: the spec uses `.stage` as the canonical inner
> container. This skill's CSS uses historical aliases per layout —
> `.grid` (content-3up / content-2col / stats), `.toc` (agenda),
> `.flow` (process), `.nodes` (timeline), `.stack` (quote), `.stage`
> (big-stat). The validator (`check_default_centering`) accepts ALL of
> these as valid containers when checking for default centering.

Mechanical recipe:

```css
/* WRONG — grid grows to fill canvas, cards top-stack */
.slide[data-layout="content-3up"] .stage {
  display: flex; flex-direction: column;
}
.slide[data-layout="content-3up"] .grid {
  flex: 1;          /* claims all available height; cards stretch tall */
  align-items: stretch;
}

/* RIGHT — stage centers, grid sizes to content */
.slide[data-layout="content-3up"] .stage {
  display: flex; flex-direction: column;
  justify-content: center;  /* center group vertically */
  gap: 28px;                 /* spacing between grid and strap/footer */
}
.slide[data-layout="content-3up"] .grid {
  /* no flex: 1 — content-sized grid */
  align-items: stretch;      /* still equalizes cards to tallest one's content */
}
```

When the content IS dense enough to fill 80%+ of the canvas (e.g. content-3up
with strap + 3 features per card), `justify-content: center` resolves to a
top-aligned visual anyway because the content nearly fills available space.
So this default is **safe both for sparse and dense slides**.

### Counter-rule: when grid SHOULD grow

`pipeline` (Pattern I) explicitly wants the 6-step row to fill vertically so
the rail/dots/cards span the canvas — that layout uses `flex: 1` on `.steps`
deliberately. Don't strip that. The rule is: **only layouts with a fixed
content shape (3-up, 2-col, etc.) center; layouts with a stretched flow
(pipeline, timeline, process) fill.**

### When the grid shares the stage with a sibling block (strap / footer / lede)

This is the single most common way the "dead band" bug reappears, so it has a
framework guard (`BF-GRIDFILL-SIBLING`, 2026-06-05) — but author it right and
the guard never has to fire.

Since 2026-05-31 the framework gives a lone `content-3up` / `content-2col`
`.grid` `flex: 1` so it fills the [title-bottom → bottom] band (sparse →
`align-content:center` centers ≈596; dense → fills). **That fill is only
correct when the grid is the SOLE body block in `.stage`.** The moment the
stage also holds a sibling — a bottom anchor-band / strap, a lede line above
the cards, a disclaimer footer — `flex: 1` on the grid swallows every pixel of
vertical slack: the cards float dead-centre in an over-tall grid and the
sibling is shoved to the far edge, opening a large empty band between them.
Worse, the stage's own `justify-content: center` becomes a no-op (no slack left
to distribute), so "group the blocks + centre the group" never happens. This is
the **"为撑满屏幕把页脚顶到底"** anti-pattern — *filling the screen is not a
goal*; a centred group with balanced top/bottom whitespace is.

The framework now gates the fill to `:only-child`, so a grid WITH a sibling is
content-sized automatically and the stage groups + centres all blocks. You do
not need to do anything for the common case — just let the stage hold the grid
plus its strap/footer:

```html
<div class="stage">              <!-- justify-content:center, gap:28 -->
  <div class="grid">…3 cards…</div>   <!-- content-sized (NOT flex:1) -->
  <div class="anchor-band">…closing strap…</div>
</div>
```

Opt back into filling **only** for an intentional top→fill→bottom anchored
layout (e.g. a quote pinned top, a body that should stretch, a disclaimer
pinned bottom). Add the explicit `fs-fill` class to the block that should
stretch — consistent with `.fs-card-fill` / `.stage--tall`:

```html
<div class="stage">
  <p class="top-quote">…</p>
  <div class="grid fs-fill">…cards stretch to fill the middle…</div>
  <p class="disclaimer">…pinned to the floor…</p>
</div>
```

The validator already catches the un-opted-in case: **`R-VIS-SLACK-FLEX`**
flags a `flex:1` child that is over-tall (content < box) and prescribes exactly
this fix (drop `flex:1` → content-sized + parent `justify-content:center`, or
declare intent). If you see it, the answer is almost always "group + centre",
not "stretch".

### Mechanical audit (extends Rule L2)

```python
def check_default_centering(css):
    """Container-layouts that aren't pipeline/timeline/process should center
    vertically by default."""
    centerable = ('content-3up', 'content-2col', 'agenda', 'stats', 'big-stat', 'quote')
    for layout in centerable:
        m = re.search(rf'\.slide\[data-layout="{layout}"\] \.stage\s*\{{([^}}]*)\}}', css, re.DOTALL)
        if not m: continue
        stage = m.group(1)
        if 'justify-content' not in stage and 'align-content' not in stage:
            yield layout  # missing default centering
```

Block delivery if any layout in `centerable` lacks centering.

The shipped `assets/validate.py` implements this as `audit_default_centering`
(rule **R48**), with the practical extension that it accepts any of
`.stage / .grid / .toc / .flow / .nodes / .stack` as a valid container for
the layout (the spec-canonical name is `.stage`; the historical names are
the per-layout aliases this skill already uses). It also accepts
`align-items: center` and `place-content: center` as equivalent centering
declarations. Functionally identical to the spec, just looser about which
selector name carries the rule.

### Failure mode this catches

User adds a recommendations slide with 3 short cards. Cards stretch to
fill canvas, content stuck at top of each card, big empty bottom across
the slide. User asks "why is there so much empty space?" — agent has to
add centering after the fact. **The default layout should already center.**

### Raw slides + genuinely-sparse content — pick a shape that FILLS, don't stretch boxes

Everything above (group + centre, "*filling the screen is not a goal*",
`R-VIS-SLACK-FLEX`, `R-VIS-CARD-MIN-HEIGHT-SPARSE`) applies to `layout:"raw"`
too — and raw is the default, so it's where this bug actually ships. The schema
guards key off known containers (`content-3up` `.grid`, etc.); **bespoke raw
class names slip through them**, so own the discipline by hand. Two raw-specific
failure modes:

1. **Never hard-code `min-height` (or `flex:1`+stretch) on a bordered card to
   force it to the floor.** A box that has a border / background stretched past
   its content = visible hollow: content jammed at the top, footer/`代价` line
   jammed at the bottom, dead air in the middle. Cards are **content-height**,
   full stop.

2. **When content is genuinely too sparse to fill even when centred** (e.g. 4
   short cards + a one-row diagram cover only ~45 % of the canvas), neither
   `justify-content:center` nor `space-between` saves it — centring leaves one
   big middle gap; space-between leaves big *even* gaps; both read as "ran out
   of content". Do **not** stretch anything. **Re-shape the layout to one whose
   natural proportion fills 16:9:**
   - a **vertical** flow / timeline / process spine (top→bottom) instead of a
     single horizontal row — verticality fills height by nature and is the right
     shape for a long serial process;
   - **wide, stacked** rows (N cards stacked full-width, each short) instead of a
     tall horizontal card row — each row is content-tall, the stack fills the
     column;
   - move supporting items **beside a tall hero visual** (two columns: tall
     diagram left, stacked annotations right) so both columns fill height;
   - let the **hero visual grow and keep it borderless** — air *around* a
     borderless diagram on the canvas reads as breathing room; the *same* air
     *inside* a bordered box reads as broken.

   **Rule of thumb: whitespace belongs on the canvas / around borderless
   visuals — never inside a bordered box.** If you are tempted to stretch a card
   to fill, the layout *shape* is wrong; re-shape it instead of stretching.

   *Case (2026-06-06): a "新险种卡在审批长链" raw page — a one-row chain + a
   4-card horizontal row left ~half the slide empty; stretching the cards made
   540 px hollow cards (two rounds of "间距太大 / 框太高" feedback). Fix that
   landed: vertical approval flowchart (left column, fills height) + 4 wide
   stacked pain-point cards (right column); both columns fill, zero stretch, zero
   gap.*

---


## Vertical anchor: the title band bottom (subtitle-aware) — F-301

All vertical math on a content page anchors on the **title-band bottom**,
NOT on the main title's bottom and NOT on a hardcoded constant
(200 / 220 / 250 are all main-title-era folklore — copy-pasting them under a
subtitle is exactly how fwd-founder #8 shipped with a chart 14px under the
subtitle and 184px of dead floor).

Definition:

```
title-band bottom = real rendered bottom of the .header bbox
                  = main title bottom               (no subtitle)
                  = .page-sub bottom                (subtitle present)
content top      ≥ title-band bottom + 24px        (validator floor, R-VIS-TITLE-GAP)
content band     = [title-band bottom, 1080]        — center content on its mid
                    (R-VIS-CANVAS-CENTER measures exactly this)
```

Estimating the band bottom when authoring (design px, before render):

```
61 (header top)
+ title lines × 55      (48px / 1.15)
+ if .page-sub: 36 (canonical margin) + sub lines × 41   (28px / 1.45)
```

So: 1-line title ≈ 119 · 1-line title + 1-line sub ≈ 196 · + 2-line sub ≈ 236.
ALWAYS re-measure after render (playwright computed px) instead of trusting
the estimate — line counts wrap differently in Latin vs CJK.

Who handles this for you, and when you are on your own:

- **Schema / stage-based slides**: the framework measures the rendered header
  into `--fs-band-bottom` (feishu-deck.js `setBandAnchor`) and the unified
  `.stage` rule derives `top: calc(var(--fs-band-bottom, 112px) + 56px)` —
  the stage's flex center lands exactly on the band mid. You do nothing.
- **Raw full-bleed pages (absolute positioning, own wrapper)**: the framework
  cannot reach in. Compute every `top:` from the band-bottom formula above and
  center the composition in `[band bottom, 1080]`. The validator floor still
  covers you (R-VIS-TITLE-GAP third channel + R-VIS-CANVAS-CENTER both find
  nested `.land > .header` headers), but only at warn/err level — get the
  numbers right at authoring time.
- Keep the header inside the canonical pattern (`.header > h2.title-zh` +
  `p.page-sub`) even on bespoke raw pages — that is what the validator's
  nested-header detection keys on.

## Variant override discipline

When a `data-variant` re-skins an existing `data-layout`, the variant CSS does
NOT automatically reset properties from the base layout. CSS cascade only
overrides properties that the variant *explicitly declares*. So if the base
sets `flex-direction: column` and your variant only sets `display: flex`, the
column direction sticks.

**Rule:** when a variant changes the visual structure (row ↔ column,
grid ↔ flex, horizontal ↔ vertical), it MUST explicitly redeclare every
directional / structural property of the layout container — NOT rely on
shorthand or default behavior.

### Concrete recipe — variant flips a column container to row

```css
/* ---- Base layout: vertical stack ---- */
.slide[data-layout="content-2col"] .grid {
  display: flex;
  flex-direction: column;     /* base: vertical */
  align-items: stretch;
  justify-content: flex-start;
  flex-wrap: nowrap;
  gap: 24px;
}

/* ---- Variant: flip to horizontal row — WRONG ---- */
.slide[data-layout="content-2col"][data-variant="horizontal"] .grid {
  display: flex;              /* technically already flex; doesn't help */
  /* flex-direction missing → STILL column from base — bug */
  gap: 36px;
}

/* ---- Variant: flip to horizontal row — CORRECT ---- */
.slide[data-layout="content-2col"][data-variant="horizontal"] .grid {
  display: flex;              /* explicit, even if identical */
  flex-direction: row;        /* MUST redeclare — does not auto-reset */
  align-items: stretch;       /* MUST redeclare — even if value is identical */
  justify-content: flex-start;/* MUST redeclare */
  flex-wrap: nowrap;          /* MUST redeclare */
  gap: 36px;
}
```

### Concrete recipe — variant flips a grid to flex (or vice versa)

When changing layout *engine* (grid → flex, flex → grid), every property
specific to the OLD engine becomes a no-op but doesn't disappear. You must
explicitly null them with `unset` or replace them with the new engine's
equivalents.

```css
/* Base: 3-column grid */
.slide[data-layout="content-3up"] .grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  grid-template-rows: auto;
  align-items: stretch;
  align-content: center;
  gap: 36px;
}

/* Variant: become a horizontal flex row instead — CORRECT */
.slide[data-layout="content-3up"][data-variant="flex-row"] .grid {
  display: flex;                                     /* swap engine */
  grid-template-columns: unset;                      /* null grid-only props */
  grid-template-rows: unset;
  flex-direction: row;                               /* declare flex equivalents */
  align-items: stretch;
  justify-content: center;
  flex-wrap: nowrap;
  gap: 36px;
}
```

### Why "redeclare even if identical"

The cascade is property-level, not declaration-level. If the base has
`align-items: stretch` and the variant doesn't mention `align-items` at all,
the base value sticks — which is usually what you want. But the moment you
later refactor the BASE to `align-items: center`, every variant inherits
that change silently. The bug shows up months later when "just a small base
tweak" cascades into 12 broken variants. Redeclaring all structural props
in the variant makes each variant self-contained and audit-friendly.

### Properties considered "structural / directional"

Any of these properties on a layout container constitutes structure. If
the variant changes ANY of them, it must explicitly redeclare ALL of them:

- `display`
- `flex-direction`, `flex-wrap`, `flex-flow`
- `grid-template-columns`, `grid-template-rows`, `grid-template-areas`,
  `grid-auto-flow`, `grid-auto-columns`, `grid-auto-rows`
- `align-items`, `align-content`, `align-self`, `place-items`, `place-content`
- `justify-items`, `justify-content`, `justify-self`
- `gap`, `row-gap`, `column-gap`

Properties like `padding`, `background`, `color`, `border-radius` are
*cosmetic* — a variant changing only those doesn't need to redeclare
structural props.

### Validator behavior

`assets/validate.py` includes `audit_variant_discipline` (rule **R47**).
For every CSS rule whose selector contains `[data-variant=...]`, the
validator checks: if the block declares `display:` or `flex-direction:`
or any `grid-template-*`, it must ALSO declare `align-items` and
`justify-content` (or their `place-*` shorthands). Otherwise it warns
that this variant is touching structure without redeclaring all
directional props — exactly the scenario that produces "I flipped
direction but it didn't change" bugs.

Cosmetic-only variants (e.g. `data-variant="dense"` that only changes
`gap` and `padding`) pass the audit untouched — the rule only triggers
when structural change is detected.

### Going-forward expectation

When writing or editing a `data-variant` rule:

1. Decide: is this variant **cosmetic** (color, spacing, font) or
   **structural** (layout direction, engine, alignment)?
2. If structural → redeclare every directional property listed above.
3. Run `python3 assets/validate.py deck.html` — R47 will catch any
   structural variant that forgot to redeclare alignment.
4. If a variant is intentionally only changing one structural prop and
   keeping the others, redeclare them ANYWAY with the inherited value.
   Self-contained variants are easier to refactor later.

---


## Layout integrity rules — execute, don't assume

These are the failure modes that hit the LKK exchange deck on first try.
Adding them as **mandatory** layout audits, not "best practice" suggestions.

### Rule L1 — Logo defaults to COLOR on every slide

`.slide .wordmark` background MUST default to `var(--fs-asset-logo)` (the
tri-petal color logo). Mono is **opt-in** via `class="is-mono"`. The mono
variant is only correct on chapter dividers / section pages where the
glow background dominates and a colored logo would clash.

```css
/* default — color */
.slide .wordmark { background: var(--fs-asset-logo) right center/contain no-repeat; }
/* opt-in mono */
.slide .wordmark.is-mono { background-image: var(--fs-asset-logo-mono); }
```

The pre-Sept-2025 spec had this backwards (mono default, color opt-in via
`is-color`). That's deprecated. **If you generate a deck where every content
slide uses the mono logo, you've broken Rule L1.**

### Rule L2 — No content stranded at the top of a slide

If a slide's content uses less than 60% of the canvas height, you MUST
either (a) center the content vertically, or (b) make it expand to fill.
**Never** leave content packed at the top with empty bottom — this is the
single most-reported visual bug from internal sales.

Mechanical fix recipe per layout type:

| Layout         | When to apply                          | CSS to add                                   |
|----------------|----------------------------------------|----------------------------------------------|
| `content-2col` | Cards shorter than canvas              | `align-content: center` on `.stage`/`.grid`  |
| `process`      | Step row natural height < canvas       | `align-content: center` on `.stage`/`.flow`  |
| `content-3up`  | Card row natural height < canvas       | `align-content: center` on `.stage`/`.grid`  |
| `pipeline`     | Steps + highlights + infra leave space | `flex: 1` on `.steps`, let it grow           |
| `timeline`     | Nodes row shorter than container       | `align-content: center` on `.nodes`          |

> The CSS in this skill uses `.grid` / `.flow` / `.nodes` as the historical
> per-layout container names. `.stage` is the canonical generic name from
> the abstract规范. Both are valid; the audit accepts any of them.

If the content is already dense enough to genuinely fill 80%+ of the canvas,
neither center-mode nor grow-mode is needed. Otherwise pick one — DO NOT
ship a top-stacked slide.

### Rule L3 — `margin-top: auto` on a stretched card creates the empty-middle bug

If a card is `display: flex; flex-direction: column` and an inner element
has `margin-top: auto` (e.g. a pills row pushed to bottom), and the parent
grid stretches the card to fill the whole stage height, the visible result
is a card with content stuck at top, pills stuck at bottom, and **a giant
empty middle**.

Fix: combine Rule L2 (center the row vertically with `align-content: center`
on the grid container) with content-sized rows (`grid-template-rows: auto`)
so cards become exactly content-tall instead of canvas-tall. Pills'
`margin-top: auto` then becomes a no-op when content already fills the card.

The shipped CSS now defaults to this safer behavior:

```css
.slide .grid > .card,
.slide .flow > .step {
  align-self: stretch;   /* equal-height within row, cosmetic */
  margin: 0;              /* override the auto-margin default — grid handles vertical placement */
}
```

### Rule L4 — Output panel attribute lists: single column when narrow

The `process` layout's output panel is ~400 px wide. If you put a 4-item
attribute list in `grid-template-columns: 1fr 1fr` (2×2), each cell becomes
~180 px which truncates body-floor (22 px) text like "Communication style".
Use `grid-template-columns: 1fr` (single vertical stack) when the panel
is < 480 px wide. The output panel is naturally tall — vertical stacking
fits its proportion and lets body type stay at the 22 px floor.

The shipped CSS enforces this:

```css
.slide[data-layout="process"] .output .attrs {
  grid-template-columns: 1fr;   /* never 1fr 1fr */
}
```

### Mechanical audit (extends self-check items #6, #7, #19)

The `assets/validate.py` validator now includes these checks (the function
signatures match the规范 verbatim):

```python
def check_logo_default(html):
    """Rule L1: wordmark default must reference --fs-asset-logo (color)."""
    m = re.search(r'\.slide \.wordmark \{[^}]*background:\s*([^;]+);', html, re.DOTALL)
    return m and 'asset-logo)' in m.group(1) and 'asset-logo-mono' not in m.group(1)

def check_balance(html):
    """Rule L2: every layout's stage uses center or flex-grow when content is short."""
    layouts_with_short_content = ('content-2col', 'process', 'content-3up')
    for layout in layouts_with_short_content:
        m = re.search(rf'\.slide\[data-layout="{layout}"\] \.stage \{{[^}}]*\}}', html, re.DOTALL)
        if m and not ('center' in m.group(0) or 'flex: 1' in html):
            return False, layout
    return True, None

def check_attrs_density(html):
    """Rule L4: process output attrs should be 1-col when output panel is narrow."""
    m = re.search(r'\.slide\[data-layout="process"\] \.output \.attrs \{[^}]*\}', html, re.DOTALL)
    return m and 'grid-template-columns: 1fr;' in m.group(0)
```

Block delivery if any returns False.

### Going-forward expectation for the agent

When the agent finishes writing a deck, BEFORE sending the file to the user:

1. Run the font-size audit (existing — Rule #6).
2. Run `check_logo_default` (Rule L1).
3. Run `check_balance` for every layout used (Rule L2).
4. For every `content-3up`, `content-2col`, `process` slide, eyeball whether
   `.stage` either centers or fills. If neither, fix.
5. For every `process` slide with output attrs, confirm single-column.

**The user should never have to point out a top-stacked layout, an empty
middle, or a mono logo on content slides.** If they do, it's because the
agent skipped Rules L1–L4. Re-run before you reply.

---


## CSS layout pitfalls (defenses already in feishu-deck.css)

The `.slide` canvas is fixed 1080 × 1920 (or 720 × 1280 native — same ratio).
Four classic flex/grid mistakes blow that canvas out. The CSS includes defenses
for all of them, but be aware:

1. **flex-column + `flex:1` child + min-content content → overflow.** Every flex
   item must also have `min-height: 0` so it can actually shrink. The CSS
   applies this to `.stage`, `.grid`, `.flow`, `.col-text` by default.
2. **CSS Grid rows take max-content height.** Use `grid-template-rows: minmax(0, 1fr)`
   and apply `min-height: 0` to grid cells. The CSS already applies `min-width: 0;
   min-height: 0` to all direct grid children.
3. **`flex-wrap: wrap` on a `min-width: 0` parent = disaster.** Mixed-width
   children blow up scrollHeight. The CSS defaults `.pills` and `.cta-row` to
   `nowrap` with `overflow-x: hidden`. If you genuinely need wrapping pills,
   declare it explicitly.
4. **Card density: stretch vs auto-margin.** Default = `.card { margin: auto 0 }`,
   so cards take their content's natural height and center vertically in the
   grid cell. Only add `class="is-stretch"` when content density actually
   requires the card to fill — otherwise you get an ugly "card filled, content
   only at top" gap. The CSS already encodes this; trust the default.

If you write a custom layout, follow these patterns. If a slide overflows in
practice, run through this list before tweaking pixel values.

---

## Screenshot tile (`.shot-twin` / `.shot-col` / `.shot-pill` / `img.shot-img`)

For showing N FULL product screenshots side by side, each with a short pill
label. Codified 2026-06-05 from `meeting-recap-ai` + `ai-knows-you`. Lives in
**feishu-deck.css** (the always-loaded core). Distinct from story-case
`.scene-frame`, which CROPS a documentary still (`background-size: cover` +
overlay caption); a screenshot must be shown WHOLE.

```html
<div class="stage">
  <div class="shot-twin">
    <div class="shot-col">
      <span class="shot-pill">近 1 年的会议文档及会议发言</span>
      <img class="shot-img" src="input/会议发言.png" alt="近一年周会文档及发言">
    </div>
    <div class="shot-col is-violet">
      <span class="shot-pill">会议相关的待办及评论</span>
      <img class="shot-img" src="input/待办评论.png" alt="会议待办及评论">
    </div>
  </div>
</div>
```

- Use a **real `<img>`**, NOT a `background-size:contain` frame. A contain image
  floats inside a fixed-height frame, so shots of different aspect ratios sit at
  different offsets and the label↔image gap differs column-to-column (the trap on
  the source page: 14px vs 54px). The validator can't see it (it measures DOM
  rects, not the floated background extent), and the runtime `balanceColumns` fix
  only half-solves it (tightens the frame but then centres each unit → labels
  mis-align). An `<img>` sizes to its own aspect ratio with no letterbox slack.
- The tile gives **aligned labels + identical gaps** for free: `.shot-twin` is
  `align-items: start` (top-aligns columns → labels line up); the pill↔image gap
  is the flex `gap` (one constant, every aspect ratio); each image is exactly as
  tall as it needs to be (a wider/shorter shot simply ends higher). The whole
  group is content-height and the stage centres it.
- Pill colour variants on the column: `is-violet` / `is-teal` / `is-orange`.
  Columns: `--shot-cols` (default 2). Tall portraits: cap height with
  `--shot-max-h` (default 740px) if the stage is shorter than usual.
- Captions BELOW the image instead of above: author the pill AFTER the `<img>`
  and add `shot-twin--cap-below` on the twin (bottom-aligns so image bottoms +
  captions line up).

