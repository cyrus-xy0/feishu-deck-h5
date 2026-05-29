# narrative-patterns — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:按字母取叙事 pattern A-N + helper 配方

## Narrative patterns (DESIGN.md §9 — A through K)

Beyond the 13 base layouts, the design system carries 11 named *narrative
patterns* for specific rhetorical moves common in 飞书 internal pitches.
The CSS ships classes for the high-frequency ones. Markup recipes:

### A. 3 + 1 hero pattern — "三类需求 → 统一过滤器"
Three parallel cards on top, one full-width "hero" card below. SVG dotted
arrows from each top-card foot converge to the hero. Use this when "decision
converges from multiple inputs" (clearer than 4-up).

### B. Verdict pill matrix — `data-verdict="go|conditional|nogo"`
For "接 / 部分接 / 不接" judgments. The card border color, top 5 px head bar,
and right-corner badge all derive from `data-verdict`:
```html
<div class="verdict-card" data-verdict="go">
  <span class="badge">GO · 接</span>
  <h3 class="ctitle">立即接入</h3>
  <p class="cbody">理由 …</p>
</div>
```
Color rules: `go=teal`, `conditional=purple`, `nogo=orange`.

### C. North-Star chip — every focus-area page must carry one
Sits directly under the page header. Dashed teal border, ★ icon prefix:
```html
<span class="north-star">北极星指标 · 关键决策时长 &lt; 60 秒</span>
```

### D. Boundary band — `不做` / `做` contrast
Two cards side-by-side. Left = orange dashed, body has line-through. Right =
teal solid, body uses `<span class="hl">关键词</span>` for accent4 emphasis:
```html
<div class="boundary-band">
  <div class="boundary-no">
    <span class="pill">不做</span>
    <p class="body">为单点客户定制非通用功能</p>
  </div>
  <div class="boundary-yes">
    <span class="pill">做</span>
    <p class="body">投入到 <span class="hl">5+ 客户共有的</span> 通用能力</p>
  </div>
</div>
```

### E. Fork visualization — 1 input → N branches
Don't use a 1/2/3 sequence diagram. Structure: input card → engine badge with
ACCENT4 pulse → Y-fork SVG → N branch cards in a row. Hand-write the SVG
for now; a helper is on the roadmap.

### F. Evolution chip — `现阶段 → 未来`
Compact two-row block, `white-space: nowrap` per row, dashed border:
```html
<div class="evolution-chip">
  <span class="stage-tag">CURRENT</span><span class="stage-body">中心化协同 + 部门工作流</span>
  <span class="stage-tag">FUTURE</span><span class="stage-body is-future">联邦化协同 + 跨域 AI 工作流</span>
</div>
```

### G. Two-track structure — one role, parallel tracks
Two stacked sub-blocks per role. Each sub-block: 3 px left color bar + short
label pill + body. Use for "PM 既负责 X 也负责 Y" duality.

### H. Iron 4-corners (铁四角) — 2×2 grid + center node
Four cards in a 2×2, an absolutely-positioned circle in the middle, four SVG
guide lines from center to each card's inner edge. Each card carries: pill +
serial numeral top-right + lead + body + key-deliverable chips + hand-off
indicator. Use for "四个不可分割的协同角色".

### H+. Two-hand architecture (心脏图) — `two-hand-arch`
Use when the value proposition is "we do exactly TWO things, on a shared
base, for a single decision-maker". 4-tier vertical structure: top
decision-maker crown → SVG curved-dashed lines (blue + teal) → two hands
(left blue tinted, right teal tinted) each with 3 numbered items → bottom
base (the underlying tech stack). Brand palette only — NEVER imitate
v2-style blue+orange split; use blue+teal which matches the feishu master.

```html
<div class="two-hand-arch">
  <div class="arch-top">
    <svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
    品牌总部 · CEO / 销售 VP / 渠道总监
  </div>
  <div class="arch-lines">
    <svg viewBox="0 0 800 60" preserveAspectRatio="none">
      <defs>
        <linearGradient id="archL" x1="0%" x2="100%"><stop offset="0" stop-color="#3C7FFF"/><stop offset="1" stop-color="#3C7FFF" stop-opacity=".3"/></linearGradient>
        <linearGradient id="archR" x1="0%" x2="100%"><stop offset="0" stop-color="#33D6C0" stop-opacity=".3"/><stop offset="1" stop-color="#33D6C0"/></linearGradient>
      </defs>
      <path d="M400,0 Q400,30 200,60" stroke="url(#archL)" stroke-width="2" fill="none" stroke-dasharray="6 6"/>
      <path d="M400,0 Q400,30 600,60" stroke="url(#archR)" stroke-width="2" fill="none" stroke-dasharray="6 6"/>
    </svg>
  </div>
  <div class="arch-hands">
    <div class="arch-hand left">
      <div class="arch-hand-title"><h3>左手 · X</h3><span class="em">EN MOTTO</span></div>
      <div class="sub">一句解释左手做什么</div>
      <div class="arch-items">
        <div class="arch-item"><span class="n">1</span>第一项 — 一句话效果</div>
        <div class="arch-item"><span class="n">2</span>第二项</div>
        <div class="arch-item"><span class="n">3</span>第三项</div>
      </div>
    </div>
    <div class="arch-hand right">
      <div class="arch-hand-title"><h3>右手 · Y</h3><span class="em">EN MOTTO</span></div>
      <div class="sub">一句解释右手做什么</div>
      <div class="arch-items">
        <div class="arch-item"><span class="n">4</span>第一项</div>
        <div class="arch-item"><span class="n">5</span>第二项</div>
        <div class="arch-item"><span class="n">6</span>第三项</div>
      </div>
    </div>
  </div>
  <div class="arch-base">底座 · 飞书 IM · 文档 · 多维表格 · 审批 · 知识库 — <b>天然一体</b></div>
</div>
```

### I. 6-step pipeline timeline
Top horizontal rail (gradient line + 6 dots, last dot teal). Below: 6 columns
with step number, EN, ZH, 3 bullets each. Final column gets accent4 stroke +
shadow. Use for end-to-end multi-stage flows that need labels.

### J. Three-color principle band — `principle-band`
```html
<div class="principle-band">
  <span class="principle" data-color="teal">专项优先</span>
  <span class="principle" data-color="blue">相邻扩展</span>
  <span class="principle" data-color="purple">战略例外</span>
</div>
```
Each principle prefixed by a glowing dot in its own color.

### K. 1+1 vs 1+1+N boundary tags — tenant/mode choice
Two side-by-side tags. Current mode highlighted; alternative mode rendered
with `text-decoration: line-through`. Use for "我们当前做 1+1; 不做 1+1+N".

### L. North-Star Map — `north-star-map`
N-up survey of parallel projects / initiatives in a single slide. Each card
distills one project to its essentials: **idx → 项目名 → 北极星指标 →
核心售卖 → 3 个 sub-capability tag chip**. Use this on the "deck-level
overview" slide right after the agenda / section divider — it gives the
viewer a single-frame mental model before each project gets its own deep-dive.

Markup:
```html
<div class="north-star-map" style="--cols:5">
  <div class="ns-card is-blue is-hero">     <!-- .is-hero highlights the lead card -->
    <span class="idx">01</span>
    <h4>门店管理</h4>
    <span class="star-label">北极星指标</span>
    <span class="star">门店坪效</span>
    <span class="core-label">核心售卖</span>
    <span class="core">千店千面个性化</span>
    <div class="tags">
      <span class="tag-chip">人 · 排班</span>
      <span class="tag-chip">货 · 菜单</span>
      <span class="tag-chip">场 · 陈列</span>
    </div>
  </div>
  <div class="ns-card is-violet">
    <span class="idx">02</span>
    <h4>内容营销</h4>
    <span class="star-label">北极星指标</span>
    <span class="star">广告投放 ROI</span>
    <span class="core-label">核心售卖</span>
    <span class="core">素材全生命周期</span>
    <div class="tags">
      <span class="tag-chip">内容洞察</span>
      <span class="tag-chip">内容生成</span>
      <span class="tag-chip">IP 探针</span>
    </div>
  </div>
  <!-- repeat for ns-card.is-teal / .is-purple / .is-orange -->
</div>
```

Tonal variants (`.is-blue / .is-violet / .is-teal / .is-purple / .is-orange`)
recolor the idx numeral and tag chip text. Keep them in deck order so the eye
can scan left-to-right by accent. Set `--cols` (default 5) to adjust grid
density: 4-up for shorter narrative arcs, 6-up only when content stays terse.
**Why this beats a comparison table**: a table forces the eye to read across;
the map lets each card breathe and treats every project as a peer. For "5
专项" or "4 战场" content this is the strongest single-slide overview shape.

### M. Adjacency-scenes grid — `scene-grid`
3×2 = 6 cards (or `--cols` adjusted) showing how a single principle / product
applies across **N adjacent industry domains**, with a quantified **economic
lever** per scene. Each card carries:
- a top accent bar (3 px, per-card color)
- an icon tile + scene name (one row)
- a divider
- 个性化对象 / 适用对象 label
- a one-line description of WHAT is personalized
- a `.sc-lever` callout with a **bold `<em>` for the impact number**
  (e.g. `经济杠杆 · <em>报损率 ↓1pp = 头部一年增利 1-2 亿</em>`)

Markup:
```html
<div class="scene-grid" style="--cols:3">
  <div class="scene-card is-blue">
    <div class="sc-top">
      <span class="sc-icon"><svg viewBox="0 0 24 24" stroke="currentColor"
        stroke-width="1.6" fill="none" stroke-linecap="round"
        stroke-linejoin="round"><path d="M3 7h18l-2 12H5L3 7Z"/>
        <path d="M8 7V5a4 4 0 0 1 8 0v2"/></svg></span>
      <span class="sc-name">生鲜超市</span>
    </div>
    <hr>
    <span class="sc-label">个性化对象</span>
    <span class="sc-obj">千店千策订货 · 加工 · 临期 · 调价</span>
    <span class="sc-lever">经济杠杆 · <em>报损率 ↓1pp = 头部一年增利 1-2 亿</em></span>
  </div>
  <div class="scene-card is-violet">
    <div class="sc-top">
      <span class="sc-icon"><svg viewBox="0 0 24 24" stroke="currentColor"
        stroke-width="1.6" fill="none" stroke-linecap="round"
        stroke-linejoin="round"><rect x="3" y="6" width="18" height="14" rx="2"/>
        <path d="M7 6V4h10v2"/><path d="M3 11h18"/></svg></span>
      <span class="sc-name">便利店选品</span>
    </div>
    <hr>
    <span class="sc-label">个性化对象</span>
    <span class="sc-obj">千店千策的 SKU 组合</span>
    <span class="sc-lever">经济杠杆 · <em>单店日销提升 5%+</em></span>
  </div>
  <!-- 4 more scene-cards … -->
</div>
```

The lever is the rhetorical hook — without a real, quantified impact number
this layout collapses into a generic "list of use cases". If you can't fill
in a credible `<em>` value for a scene, drop it from the grid; six soft
scenes are weaker than three hard ones. Per-card tonal variants
(`.is-blue / .is-violet / .is-teal / .is-purple / .is-orange`) recolor the
accent bar, icon, and label; keep adjacent cards in different tones so the
viewer can pre-attentively count the panels.

### N. 5-up Overview with Hero Numerals — `overview-grid` (2026-05-16)

Use this for **"this month / quarter / week, 5 things to push forward"**
overview pages. Each card carries a large decorative numeral (88 px Hero
exception) + a bold Title-tier topic name + one-line description body.
The hero numeral signals "5 parallel directions" pre-attentively; the
topic name takes the focal weight.

This pattern was evolved during the 2026-05-16 南区周会 session through
~10 iterations of size / weight / treatment tuning. The final values:

| Element | Size | Weight | Color | Notes |
|---|---|---|---|---|
| Page title (top, page-wide) | 48 Title | 700 | #fff | Standard |
| Card numeral 01–05 | **88 Hero** | 500 medium | 55% semi-transparent brand color | `/* allow:typescale */` |
| Card topic name | **48 Title** | 700 | #fff | Bold dominates within card |
| Card description | 24 Body | 500 medium | #fff @ 92% | Margin-top auto pushes to bottom |

5 cards in a horizontal `grid-template-columns: repeat(5, 1fr)`, gap 24px,
each card `min-height: 320px` to give numeral + title + body proper
breathing room.

Markup:
```html
<div class="slide" data-layout="content-3up" data-screen-label="01 五个推进方向"
     data-slide-key="weekly-overview">
  <div class="wordmark"></div>
  <div class="header">
    <h2 class="title-zh">本周南区周会 · 五个推进方向</h2>
  </div>
  <div class="stage">
    <div class="grid overview-grid">
      <div class="card overview-card is-c1">
        <span class="ov-num">01</span>
        <span class="ov-name">商机管理</span>
        <span class="ov-desc">Q2/Q3 大扫除 · 周末截止</span>
      </div>
      <!-- 4 more cards: is-c2 / is-c3 / is-c4 / is-c5 -->
    </div>
  </div>
</div>
```

Per-card tonal variants `.is-c1` (blue) / `.is-c2` (violet) / `.is-c3`
(teal) / `.is-c4` (orange) / `.is-c5` (neutral white) recolor the
border + numeral. Keep the SAME color → SAME topic across the deck (if
slide 1 says 商机管理 = blue, then slide 2 which is a deep-dive on 商机
should also lead with blue).

**Why this pattern needed naming**: a 5-up overview is structurally
different from a 3-up content layout (Pattern A) or a generic list. The
hero numeral makes each card READ as a "chapter" rather than a "cell".
Without the hero treatment, "5 things" devolves into "5 small cards",
and the page reads as "a list" not "an overview".

**Don't use this for**:
- 3 or 4 cards (too few — the hero numeral overpowers; use Pattern A
  content-3up or content-2col instead)
- 6+ cards (too many — hero numerals visually fight; collapse to
  smaller scale or split across two slides)
- Cards with > 2 lines of body (cards become tall and the hero numeral
  loses dominance; use Pattern A with regular sizes instead)

---


## Helper-snippet recipes

Where the design system has a reusable HTML+CSS combo, treat it as a "helper".
The CSS already ships the styles; the markup is what you copy. These are the
named helpers; expand each to the recipe block above when generating a deck:

| Helper                           | Use for                              | CSS class              |
|----------------------------------|--------------------------------------|------------------------|
| `north_star_chip(metric)`        | Pin every focus area to its KPI      | `.north-star`          |
| `verdict_card(go/cond/nogo, …)`  | Decision-judgment cards              | `.verdict-card[data-verdict=…]` |
| `boundary_band(no_text, yes_text)`| 不做 / 做 contrast                   | `.boundary-band`       |
| `evolution_chip(now, future)`    | 现阶段 → 未来                        | `.evolution-chip`      |
| `principle_band(items)`          | Three-color strategy principles      | `.principle-band`      |
| `phone_frame_iframe(src)`        | Mobile prototype embed               | `.phone-frame`         |
| `desktop_iframe(src)`            | Desktop prototype embed + hint       | `.desktop-frame`       |
| `aurora_background()`            | Add `data-decor="aurora"` on `.slide`| `[data-decor~="aurora"]` |
| `fullscreen_button()`            | Already shipped in `.deck-ui`        | `.deck-controls .ctl.fs` (auto) |
| `north_star_map(N, cards)`       | Pattern L · N-up project survey, idx + title + 北极星 + 核心售卖 + 3 chips | `.north-star-map / .ns-card` |
| `scene_grid(cards)`              | Pattern M · 3×2 industry-adjacency grid with quantified economic lever per scene | `.scene-grid / .scene-card` |

Roadmap helpers (no CSS yet — write the markup by hand and follow the spec):
fork visualization, iron-4-corners, 6-step pipeline timeline, two-track
structure, 1+1 vs 1+1+N boundary tags.

---

