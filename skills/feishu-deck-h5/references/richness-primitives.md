# richness-primitives — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:手写 richness primitive 的逐字配方

## Richness primitives (v1.3) — promoted from the deck_v3 reference

The skill ships a second tier of helpers that exist specifically to STOP the
agent from delivering an austere "skeleton" deck. They were promoted from the
hand-built `deck_v3_feishu` reference build — the highest-fidelity feishu
deck the team had shipped at the time. **Use them by default**, not "if you
have time". A slide that cites a number without `.kpi-strip`, a closing without
`.cta-box`, or a transform without `.ui-wave + .report-item` is a slide that
under-delivers on what the skill is capable of.

### MANDATORY: wrap body + helpers in `<div class="stage">`

`.grid` / `.flow` / `.nodes` / `.toc` / `.table-wrap` are **absolutely
positioned** by their layout rules. So if you place a `.pullquote` /
`.cta-box` / `.kpi-strip` / `.lede` as a *direct sibling* of the body
container under `.slide`, the helper falls into normal flow at the TOP
of the slide canvas — overlapping the header. Visually broken.

The fix is to wrap the body container AND its helpers in `<div class="stage">`:

```html
<div class="slide" data-layout="content-2col" data-decor="blue-glow">
  <div class="wordmark">飞书</div>
  <div class="header"><h2 class="title-zh">…</h2></div>
  <div class="stage">                       <!-- ← MANDATORY when using helpers -->
    <p class="lede">…</p>                   <!-- optional intro -->
    <div class="grid">…body cards…</div>    <!-- body, now flows naturally -->
    <p class="pullquote">…</p>              <!-- helper, flows below body -->
    <div class="cta-box">…</div>            <!-- helper, flows below pullquote -->
  </div>
</div>
```

`.stage` becomes the absolutely-positioned body zone (top:220, bottom:110,
left/right:96), and inner `.grid` / `.flow` / `.nodes` / `.toc` /
`.table-wrap` override their default absolute positioning to flow inside
the stage's flex column. Helpers stack naturally below the body.

Layouts that support `.stage` wrapper: `content-2col`, `content-3up`,
`process`, `timeline`, `table`, `agenda`, `stats`. (Cover / end / image-text /
big-stat have their own `.stage` semantics — see their layout recipes.)

For `timeline`: when wrapped in `.stage`, the `.axis` line stays as a direct
child of `.slide` (outside `.stage`) and auto-aligns to slide center.

If a slide has NO helpers (just body), you can omit `.stage`
without harm. Pre-1.3.2 decks (no `.stage` wrapper anywhere) still render
correctly via the legacy absolute positioning.

### When converting an external HTML deck (the failure mode this prevents)

Every primitive below maps to a v3-pattern the agent CAN'T just drop. If the
source deck has:

| Source has | You MUST use |
|---|---|
| Italic blockquote sealing the argument | `.pullquote` (default teal · `.is-orange / .is-blue / .is-violet`) |
| Customer testimonial cards with quotation glyphs | `.voice-card` (with `::before "「"`) |
| "Next step" CTA strip with a button | `.cta-box` + `.cta-btn` (`.is-teal` for promise framing) |
| Row of small KPI/metric mini-cards | `.kpi-strip` (set `--strip-cols`; tone via `.is-teal/.is-blue/.is-orange`) |
| ROI calculator / interactive sliders | `.calc` + `.calc-row` + `.calc-result` |
| Dashboard ROI rows / system list | `.ui-row` (`.val.up/.dn` for trend tone) |
| Alert banner with title + body | `.ui-alert` (orange-tone, fixed) |
| KPI tile with label + big number + delta | `.ui-kpi` (`.is-teal` for highlight variant) |
| Audio waveform (recording / call) | `.ui-wave` with 10 `<i>` bars (animated) |
| Tagged finding/insight rows (做得好 / 漏关键 / 建议) | `.report-item` (`.is-warn` orange · `.is-info` blue) |

> **Do NOT add `<div class="grid-bg"></div>` by default.** The class still
> ships for legacy decks, but the 飞书 master content layouts already use
> `lark-content-bg.jpg` (a subtle dark ambient gradient) as their background
> via `--fs-asset-content-bg`. Adding a dot-grid on top creates double-noise
> texture that makes the page feel busy and OFF-master. Only opt in to
> `.grid-bg` if a slide explicitly needs an additional engineered/technical
> backdrop (rare; e.g. a custom whitepaper layout). Default = clean.

**Drop a primitive → you've stripped meaning the source author put there.**
This is the lesson from v1 of the v3 conversion: validator-passing ≠ visually
faithful. Compliance and richness are both required.

### Card hover & tile gradient — already on by default

Every `.card` now:
- On hover: brighter background + 1 px blue glow ring (via `box-shadow:
  0 0 0 1px`) + accent border. **No `transform: translateY(...)`** — the
  transformed hit-area moves away from the cursor and creates a hover-flicker
  loop. Color + ring affords interactivity without moving the box.
- Has a **gradient blue→violet** `.tile` instead of a flat tinted square.
- Shows `.num` at 36 px / 700 (was inheriting smaller defaults).
- Shows `.cfoot` with dashed top border + accent arrow on the right.

If you write `<div class="card"><div class="head"><div class="tile">…</div>
<div class="num">01</div></div>…</div>`, you GET the v3 visual treatment for
free. There is no `.is-rich` modifier — richness is the default.

### Process step chevron — already on by default

Every `.step` inside a `[data-layout="process"] .flow` auto-renders a blue
chevron between cards. Last step and `data-variant="vertical"` auto-hide
the chevron. No markup change.

### Markup recipes (canonical)

```html
<!-- pullquote — caps a body grid with a thesis statement -->
<p class="pullquote">不是让你再投一个大系统,而是先请几个不要工位的同事。</p>
<p class="pullquote is-orange">不安抚,直接给解法。</p>

<!-- voice-card — testimonial inside a content-3up grid -->
<div class="voice-card">
  <p class="q">以前每天 8 点打开微信群看 200 条问题,现在群里是空的。精英销售终于能把时间放在打单。</p>
  <p class="who">某饮料品牌 · 华东大区销售经理</p>
</div>

<!-- cta-box — strong call-to-action tail strip -->
<div class="cta-box">
  <div class="l">
    <h3>下一步 · 免费 90 分钟诊断工作坊</h3>
    <p>解决方案架构师上门或线上,共同识别值得优先做的 1 个场景。</p>
  </div>
  <button class="cta-btn">启动诊断 →</button>
</div>

<!-- kpi-strip — 3-up metric row beneath body -->
<div class="kpi-strip">
  <div class="kpi"><div class="v is-teal">T+2 天</div><div class="l">费效比出数周期</div></div>
  <div class="kpi"><div class="v is-teal">全量</div><div class="l">异常自动筛(原抽查 5%)</div></div>
  <div class="kpi"><div class="v is-teal">3–5%</div><div class="l">预估可收回营销浪费</div></div>
</div>

<!-- calc — interactive ROI widget. needs ~12 lines of inline JS to wire up -->
<div class="calc">
  <div class="calc-row">
    <label>业务员人数</label>
    <input type="range" id="r1" min="100" max="5000" step="100" value="1000">
    <span class="v" id="v1">1,000 人</span>
  </div>
  <!-- ...more rows... -->
  <div class="calc-result">
    <div class="lbl">预计年化释放销售时间价值</div>
    <div class="amount" id="roi">6,300 万</div>
  </div>
  <p class="calc-hint">* 承诺的不是这个数字本身,而是每个变量的真实测量。</p>
</div>

<!-- ui-row + ui-alert + ui-kpi inside a ui-window -->
<div class="ui-window">
  <div class="ui-titlebar"><span class="ui-traffic-lights"><i></i></span><span>活动费效比 · 04-28</span></div>
  <div class="ui-body">
    <div class="ui-row"><span class="lbl">华东 · 大润发周末堆头</span><span class="val up">ROI 3.2x</span></div>
    <div class="ui-row"><span class="lbl">华北 · 餐饮渠道返点</span><span class="val dn">ROI 0.6x</span></div>
    <div class="ui-alert">
      <div class="t">异常自动标红</div>
      <h5>华北 · 12 家门店</h5>
      <p>照片疑似同时段同角度,销量环比未提升。已抄送大区经理。</p>
    </div>
    <div class="ui-kpi is-teal">
      <div class="t">本周自动核销</div>
      <div class="v">1,284</div>
      <div class="d">↑ 47% vs 人工 · 省 40 h/月</div>
    </div>
  </div>
</div>

<!-- ui-wave + report-item — audio→insights transform widget -->
<div class="ui-window">
  <div class="ui-titlebar"><span>INPUT · 一线拜访录音</span></div>
  <div class="ui-body">
    <div class="ui-wave"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
    <div>业务员小李 · 04-28 · 14:32 · 23 分钟</div>
  </div>
</div>
<div class="ui-window">
  <div class="ui-titlebar"><span>OUTPUT · 销冠视角复盘 · 5 分钟</span></div>
  <div class="ui-body">
    <div class="report-item"><span class="tag">做得好</span><div><b>主动倾听</b>,捕获备货过多的真实困境。</div></div>
    <div class="report-item is-warn"><span class="tag">漏关键</span><div>未识别<b>"再看看"</b>背后的退货风险信号。</div></div>
    <div class="report-item is-info"><span class="tag">销冠建议</span><div>立即提<b>调换新品 + 返点补贴</b>组合方案。</div></div>
  </div>
</div>

<!-- titled-panel — a heading that LABELS a set (steps / criteria / metrics)
     must be BOUND to its members inside ONE container. Otherwise the heading
     floats as an orphaned (N+1)th element above a row of equal-weight bordered
     cards, and the group stops reading as "one thing" (real failure mode, pg-27
     of a康师傅 deck). Fix: one tinted/bordered panel; header gets a divider;
     members become INTERNAL divider-rows — drop the per-card borders so they
     read as rows-under-a-title, not N independent peers. Scope the CSS to the
     slide-key (these are raw-slide class names, shown generic here). -->
<div class="titled-panel">
  <div class="tp-head">
    <h3 class="tp-title">专家督导的<span class="hl">「三步算账」</span></h3>
    <span class="tp-tag">10 MIN</span>
  </div>
  <div class="tp-rows">
    <div class="tp-row"><span class="n">01</span><div><p class="t">看线上单量</p><p class="d">打开美团,直接看竞品当日单量。</p></div></div>
    <div class="tp-row"><span class="n">02</span><div><p class="t">问外卖小哥</p><p class="d">买瓶水,问"今天送了多少单"——拿到内单号。</p></div></div>
    <div class="tp-row"><span class="n">03</span><div><p class="t">倒推算账</p><p class="d">内单号还原真实单量 × 客单价 = 竞品营业额。</p></div></div>
  </div>
</div>
<style>
/* the panel binds title + rows into one unit; pair it 等高 with the sibling
   visual (image / chart) via the row's align-items:stretch */
.SLIDEKEY .titled-panel{display:flex;flex-direction:column;border-radius:18px;
  border:1px solid rgba(51,214,192,.32);
  background:linear-gradient(135deg,rgba(51,214,192,.08),rgba(51,214,192,.02));
  padding:20px 26px}
.SLIDEKEY .tp-head{display:flex;align-items:baseline;gap:14px;
  padding-bottom:16px;border-bottom:1px solid rgba(51,214,192,.28)}
.SLIDEKEY .tp-rows{display:flex;flex-direction:column;flex:1;justify-content:space-between}
.SLIDEKEY .tp-row{display:grid;grid-template-columns:50px 1fr;column-gap:16px;
  align-items:start;padding:18px 0;border-top:1px solid rgba(255,255,255,.10)}
.SLIDEKEY .tp-row:first-child{border-top:none}
</style>

<!-- grid-bg — DO NOT add by default. The 飞书 master content background
     (lark-content-bg.jpg via --fs-asset-content-bg) already provides the
     ambient gradient. .grid-bg on top creates double-noise. Only opt in
     for engineered/technical layouts that need an explicit grid backdrop. -->
```

---

## Titled-panel — bind a label to its members (grouping / altitude)

When a heading **names a set** (steps, criteria, KPIs, do/don't), the heading and
the items must read as **one unit**. The recurring failure mode: a bare heading
sits above a row of **individually-bordered sibling cards** — each card has equal
visual weight, so they read as N independent peers and the heading floats as an
orphaned (N+1)th element. The "labeled group" never coheres.

**Fix (canonical above — `titled-panel`):** put the heading *and* the members in
**one** tinted/bordered panel; give the header a bottom divider; demote the
members to **internal divider-rows** (drop the per-card borders). Pair the panel
等高 with its sibling visual (image / chart) via the row's `align-items: stretch`
so the two blocks read as a balanced pair, not a tall panel beside a short image.

This is a **Gestalt / altitude judgment the validator does not gate** — like
title-position, hollow-centre and focal-point, it is an aesthetic call no rule
reliably catches. So it lives as a pattern + a self-check, not a hard闸.

**Self-check (fold into the render-time visual pass, before "done"):** for every
section heading on the page, ask — does it visually **own** its items (shared
container / tight proximity / shared left edge), or does it **float** above a row
of equal-weight cards? If the latter → wrap them in a `titled-panel`.

