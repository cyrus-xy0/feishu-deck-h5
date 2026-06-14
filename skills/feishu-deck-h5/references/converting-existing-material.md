# converting-existing-material — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:把 PDF/PPT/HTML/docs 转成合规 deck(1:1 页数 / Replica vs Rewrite)

## Converting existing material (PDF / HTML / PPT export / docs) into a compliant deck

When the user hands you ANY existing material — a PDF report, an old HTML
deck, an exported PPT screenshot set, a markdown brief, a Google Slides
share — and asks for a "feishu-deck-h5 version", **follow this workflow
exactly**. Skipping any step produces the failure modes the user has
specifically called out before:

- mono-white logo on every page (should be color)
- content slides made with `data-layout="cover"` (wrong; cover has flower bg)
- end page with title + CTA + 4-col contact grid (master spec is slogan only)
- multi-layer header on content pages with eyebrow + title + subtitle
- `<br>` inside content-page titles
- pre-existing watermarks / page numbers carried over
- **silently compressing N source pages into ~M pages** (the "I'll distill 54 → 17 because it's tighter" failure)

### Step -1 · Classify uploaded HTML role before conversion

For HTML specifically, classify the file before applying the conversion rules:

- **Source HTML**: the user says to reference, imitate, remake, recreate, learn
  from, or use the HTML as material. This is a conversion/generation input. Run
  Parser, then Designer, Renderer, and Validator. The output is a new deck.
- **Target HTML**: the user says to modify, adjust, optimize, fix, replace copy,
  tune style/layout, or continue from the current HTML. This is not a normal
  source conversion. Import/analyze it into current-state artifacts first:
  `source-dossier.json`, `DESIGN-PLAN.md`, `outline.json`, `deck.json`, and
  `index.html`; mark them as `imported_existing_state`; then route to Editor.

Only Source HTML enters the Replica vs Rewrite decision below. Target HTML edits
must preserve the submitted file's current state unless the user explicitly asks
to regenerate or redesign.

### Step 0 · Preserve the page count — DO NOT compress by default

When the user hands you a source deck (PDF / PPT / HTML) and asks for a
"feishu-deck-h5 version" (or any phrasing that means "convert this"),
the **default contract is 1:1 page mapping**:

- N source pages → N HTML slides
- Original section dividers, agenda recap pages, "thank you" closings
  ALL stay as their own slides
- Per-slide content can be UPGRADED (raster UI → `.ui-window` HTML mock,
  flat list → `.scene-grid` / `.north-star-map` / `.kpi-strip`,
  cropped chart → typographic data viz), but information items don't
  drop off
- The deck's narrative pacing (a 3-part agenda revealed gradually,
  the same idea spread over 3 build-up slides) is the user's prior
  editorial choice — preserve it

**Why this is non-negotiable** (rule elevated 2026-05-05 after a 54-page
博裕&星巴克 deck was silently compressed to 17 slides on first attempt;
user reaction: "不要压缩,这种让你基于PDF生成html,要保持页数不变,等于
就是每页仿制和体验升级"):

- The user already did editorial selection on the source. A page
  exists because they decided it earned its slot.
- Section dividers and agenda-recap slides ARE pacing — pulling
  them strips presentation rhythm.
- A single-case page that gets its own slide says "this case
  matters"; lumping 6 cases into one matrix says "these are
  interchangeable." Different message.
- Internal sales decks routinely get presented page-by-page; if
  the agent "distills" the deck, the speaker has lost their map.

**When compression IS appropriate** (opt-in only):
- User explicitly says "精简" / "提炼" / "压成 N 页" / "做执行摘要" /
  "summarize this in N slides".
- User specifies a target page count different from the source.
- User asks for a "one-pager" / "single-page summary" of a multi-page
  source.

In all other cases — convert page-for-page. If the source has 54
pages, the output has 54 slides.

**How to apply (mechanical)**:
1. Inventory source: count pages (`mdls -name kMDItemNumberOfPages`,
   `pdfinfo`, manual scroll). Write down the count.
2. Use `data-screen-label` numbering that matches the source page
   numbers ("01 Cover" through "54 End" for a 54-page source) so
   any reviewer can cross-reference the validator output to the
   original PDF.
3. Per-page upgrade is the goal — not per-deck redesign. Match the
   source's information items, then re-render in feishu-deck-h5
   style.
4. If a source page is genuinely empty (just a logo/transition),
   render it as a transition slide rather than dropping it.

### Step 0.5 · Pick the conversion mode — Replica vs Rewrite

Before deciding HOW to render each page, decide WHICH MODE the
overall conversion uses. There are two:

#### Replica mode (page-as-image · DEFAULT for designed source decks)

Each PDF page is rendered as a high-res JPG and placed in the slide
as a full-bleed `background-image`. feishu-deck-h5 only contributes
the wrapping shell — fullscreen present mode, mobile vertical
browse, keyboard nav, page indicator, URL hash sync. The source's
typography, screenshots, illustrations, color choices are preserved
**byte-for-byte**.

```bash
# Render all pages to JPG (1920px wide, q85 ~= 200-450 KB each)
mkdir -p runs/<ts>/output/pages
pdftoppm -png -scale-to-x 1920 -scale-to-y -1 input.pdf runs/<ts>/output/pages/p
for f in runs/<ts>/output/pages/p-*.png; do
  sips -s format jpeg -s formatOptions 85 "$f" --out "${f%.png}.jpg" >/dev/null
done
rm runs/<ts>/output/pages/p-*.png
```

Slide markup template:

```html
<div class="slide-frame">
  <div class="slide page-replica" data-layout="image-text"
       data-screen-label="01 Cover"
       style="background-image: url('./pages/p-01.jpg')">
    <div class="wordmark"></div>      <!-- DOM present (R07), hidden via CSS -->
  </div>
</div>
```

Required CSS (one block, applies to every slide):

```css
.slide.page-replica {
  background-color: #000 !important;
  background-position: center center !important;
  background-size: contain !important;
  background-repeat: no-repeat !important;
}
/* Source page already carries 飞书 logo — hide our shell wordmark
   so the brand mark doesn't double up. R07 is satisfied because the
   .wordmark DOM element is still present. */
.slide.page-replica .wordmark { display: none; }
```

Validator behaviour:
- All rules (R02 / R07 / R48 / etc.) pass on stub conditions.
- Replica decks have no editable text leaves — if the user wants copy
  changes, they re-export the source PDF.

#### Rewrite mode (LLM re-authors each page · OPT-IN)

Each page is hand-authored in feishu-deck-h5 native HTML — every
`.ui-window` mock is rebuilt from `.ui-*` primitives, every logo
matrix becomes a `.logo-cell` text grid, every brand palette item
maps to `--fs-*` tokens.

This is the mode the rest of SKILL.md (Steps 1–5, layout recipes,
narrative patterns) describes. It's the right call when:

- The user explicitly says "用飞书原生组件重画 / native HTML /
  redesign / 改造排版 / 不要截图".
- The source is text / markdown / docs / docs export — there are no
  meaningful screenshots to preserve.
- The source is low-resolution / poorly designed / off-brand and
  needs a real redesign.
- The source is a customer-story table row / case-library row — that
  routes to one-pager / Path A / Path B per the existing rules.

#### Default = Replica when source is a designed PDF/PPT

If the user gives you a presentable PDF or PPT (designer-touched
master, brand-aligned, has actual screenshots and product mocks)
and says "convert to feishu-deck-h5 HTML" — DEFAULT TO REPLICA.

Why:
- The user already paid for the design. Rewriting it loses that
  investment AND tends to lose UI screenshots, atmospheric photos,
  and bespoke visualizations that the LLM can't faithfully recreate
  in a single pass.
- "样式变化很大 · 截图都没了" is the most common reaction to a
  Rewrite output when Replica was the right answer.
- Replica is fast (~30 seconds for `pdftoppm` + `sips` + 60 lines
  of HTML), zero token cost, 100% information fidelity.
- The "experience upgrade" the user actually wanted is the SHELL —
  fullscreen present mode, ←/→ nav, mobile reflow, URL hash sync.
  Replica delivers all of that without touching content.

Lesson elevated 2026-05-05 from the 54-page 博裕&星巴克 deck:
first attempt was Rewrite (compressed to 17 slides) — rejected.
Second attempt was Rewrite (1:1 page count) — rejected with "整体
不太行,这种如何尽量模仿之前的内容,很多截图都没有了,样式变化
很大". Third attempt was Replica — accepted.

#### How to decide in 5 seconds

| Source signal | Mode |
|---|---|
| Designer-polished PDF/PPT, has UI screenshots, brand-aligned | **Replica** (default) |
| Markdown / docs / Google Doc / text export | Rewrite |
| Low-res screenshots / off-brand source / "redesign this" | Rewrite |
| Customer story table row, "做这个客户案例" | one-pager (Path A/B) |
| User says "用 native 组件 / 重画 / 升级排版" | Rewrite |
| User says "保持原样 / 模仿原版 / 别动样式" | Replica |

If ambiguous, **ask the user once** before deciding — the rebuild
cost between modes is high, but the question cost is one IM line.

#### Per-page polish mode (4th mode · iterative)

Distinct from Replica / Rewrite / one-pager: this is the iterative
mode where the user reviews each slide individually and gives
focused feedback ("第 N 页改成 X / 字小一点 / 列宽窄一点"), and the
agent ships a **single-slide HTML** per round under
`runs/<ts>/output/single-pages/p-NN.html`. Trigger phrases:

- "一页一页来" / "每页精修" / "一张张做"
- User reviews a slide in isolation and gives detailed visual feedback
- User drops per-page assets ("这一页的 logo / 截图我放在 input/")

In this mode, **the source PDF/PPT title is verbatim** — every
character, every punctuation mark, every parenthetical note must
reach the HTML unchanged. The agent's licence is to redo BUILD
(layout / typography / decoration), not COPY.

##### Title verbatim — strict rule

In per-page polish mode the slide's `<h2 class="title-zh">` (or
`<h1 class="title">` for hero layouts) MUST mirror the source
title byte-for-byte:

- **Don't drop characters** — "飞书对博裕资本及星巴克价值" can't
  be compressed to "飞书对博裕及星巴克价值". The 资本 stays.
- **Don't add characters** — "AI原生组织" (no space between AI
  and CJK) stays exactly that. Don't insert " AI " spaces by
  reflex.
- **Don't swap punctuation** — full-width "：" (chinese colon)
  / "；" (semicolon) / "（）" (parens) stay full-width. Don't
  replace with "·" or ":" by reflex.
- **Keep parenthetical notes** — "字节跳动的全方位AI布局：飞书
  （企业豆包）定位企业级AI入口" — the "（企业豆包）" annotation
  carries a positioning claim ("飞书 = 企业版豆包"); dropping
  it loses information.
- **Subtitles / agenda items / chapter ledes / pill labels are
  also verbatim**. The "title preservation" rule extends to all
  short headings — anything user might re-read aloud.

The ONLY editable text in per-page polish mode is the body copy:
story-hook, feature descriptions, paragraph bodies. Those the agent
may re-organize / compress / expand to fit the new layout. Headings
are off-limits.

##### When the rule is suspended

Only when the user explicitly says one of:
- "标题改成 X" / "把标题压缩"
- "这个标题太长,帮我精简" / "起一个新标题"
- The user is co-authoring the title in dialogue ("我觉得标题改
  「飞书 × 博裕」更直接")

If the source has an obvious typo (e.g. duplicated character),
**flag it to the user** and ask whether to fix; don't fix silently.

##### Self-check before shipping each polish round

Before declaring a single-page p-NN.html done, verify:

```
(1) <h2> innerText === source-page-N title (visual byte-compare)
(2) Punctuation classes match (full-width vs ASCII)
(3) Parenthetical notes / 数字注释 preserved
(4) Subtitles / pill labels / agenda items also verbatim
```

This rule was elevated 2026-05-06 from the 博裕&星巴克 polish
session: P01 "AI原生组织" got "AI 原生组织" (added space), P02
"飞书对博裕资本及星巴克价值" lost 资本, P04 dropped 「（企业豆
包）」. User feedback: "之前PDF的标题默认是不变的,一个字都
不要改". Verbatim-title is the per-page polish mode contract.

### Step 1 · Inventory the source

For every source page, write down:

| Source page | Role identifier | Likely target layout |
|---|---|---|
| Cover / 主标题 / title slide / first big-image page | hero, lots of negative space | `cover` |
| Table of contents / 目录 / agenda / outline | numbered list of sections | `agenda` |
| Section divider / chapter intro / 章节页 / 大序号 | giant numeral + chapter title | `section` |
| 3 parallel concepts / 三大能力 / capabilities triplet | 3 cards in a row | `content-3up` |
| Body text + chart / one narrative + supporting visual | left text, right image/mock | `content-2col` |
| Customer quote / 金句 / executive thesis | single sentence centered | `quote` |
| 4 KPIs in a row / metrics dashboard | numbers + units + labels | `stats` |
| Single hero number with paragraph | one big number, side prose | `big-stat` |
| Full-bleed photo + text | photograph + bottom-left caption | `image-text` |
| Comparison matrix / feature table | rows × columns of text | `table` |
| Roadmap / chronological milestones | linear timeline with stages | `timeline` |
| 3-6 sequential workflow steps | process flow with arrows | `process` |
| Closing / 谢谢 / 封底 / "thank you" | final visual signature | `end` |

If a source page doesn't fit any of these 13, it's almost always a
content page in disguise — most likely `content-3up` or `content-2col`.
Do NOT invent a 14th layout.

### Step 2 · Cover page (`data-layout="cover"`) — MUST follow master spec

The cover is intentionally minimal: **title + initiator name + date,
nothing else**. NO English subtitle, NO team/company line, NO meeting
type label. The cover earns its weight through composition, not text
volume — the right-half flower image carries the atmosphere.

| Element | Spec |
|---|---|
| Background | `lark-cover-bg.jpg` (the master flower image — NOT a solid color, NOT a gradient invented on the fly) |
| Logo | top-LEFT at (120, 113), size 235×74, **COLORED** tri-petal `--fs-asset-logo` |
| Title | left-half only (max-width 884px), 100/700, can be 1-2 lines (hero allowed `<br>`) |
| Subtitle | **NONE** (no EN translation, no marketing tagline — drop it; if you really need a sentence, put it on slide 02) |
| Author block | left-side at top:720 (2026-05-06 · was 803, moved up to sit ~215px below a 2-line title so name+date read as part of the title block, not a separate stack). Two stacked spans separated by `<br>`: line 1 = the **initiator's personal name** (the meeting host / deck owner / report author — NOT a team / department / role title); line 2 = the date (`YYYY.MM.DD`). |
| Footer chrome | NONE (retired 2026-05; pager UI shows page number) |
| Eyebrow | NONE |

```html
<div class="slide" data-layout="cover" data-screen-label="01 Cover">
  <div class="wordmark">飞书</div>
  <div class="stage">
    <h1 class="title title-zh" data-text-id="slide-01.title">〔主标题 — can wrap with &lt;br&gt;〕</h1>
  </div>
  <div class="author">
    <span data-text-id="slide-01.author">〔发起人名字〕</span><br>
    <span data-text-id="slide-01.date">〔YYYY.MM.DD〕</span>
  </div>
</div>
```

**Why the minimalism is non-negotiable** (this rule was elevated from
user feedback after a 2026-Q2 deck):

- An EN subtitle on every cover reads like marketing copy — clients
  who only need an internal summary find it noisy.
- A team line ("飞书企业服务团队") is generic; an actual person's name
  ("杰森" / "FuQiang") tells the reader who to push back to.
- The cover is a hero composition; the less text it carries, the more
  the title and the flower image can breathe.

If the user explicitly asks for an English subtitle on a particular
deck (e.g. for a bilingual external pitch), allow it — but the
default authoring behavior is "no subtitle" unless asked.

### Step 3 · Every content page — title-only header + colored top-right logo

```html
<div class="slide" data-layout="content-3up" data-screen-label="04 Content">
  <div class="wordmark">飞书</div>           ← top-RIGHT, COLORED, 160×50 (auto from CSS)
  <div class="header">
    <h2 class="title-zh">〔Source title — single line, no &lt;br&gt;〕</h2>
  </div>
  <!-- body content (.grid / .flow / .nodes / .table-wrap / etc.) -->
</div>
```

What you MUST drop from the source:
- Eyebrow / kicker text above the title (R56)
- Subtitle / lead text below the title
- Inline page numbers anywhere — page numbers are entirely retired from per-slide DOM (the present-mode pager handles them)
- Source page numbers in any other position
- Decorative breadcrumbs / "you are here" indicators
- Watermarks
- Explicit `<br>` inside content-page title (R13). If the source title is long, drop the `<br>` and let it wrap naturally — DO NOT shorten or truncate; the title is content, preserve verbatim
- Emoji, `!`, `…`, `???` — strip without asking (R05)

What you MUST preserve:
- Atmospheric backgrounds via `data-decor` (e.g. violet-glow on Digital
  Workforce / AI pages — see "Preserve atmospheric / decorative
  backgrounds when re-rendering")
- System UI / app screenshots → recreate as HTML using `.ui-*` primitives,
  NOT as raster images (UI1)
- Photographic backgrounds → use `data-decor="photo-bg"` with `style="--photo: url(...)"`

#### Typography — 4-tier strict for content pages (mandatory, 2026-05-16)

**The math**: PPT 16:9 canvas is 13.33" × 7.5". 1pt = 1/72". Web canvas
1920×1080 ⇒ 1920 ÷ 13.33 ≈ 144 dpi ⇒ **1pt ≈ 2px**. Standard
consulting-deck PPT sizes map cleanly:

| Tier | PPT (pt) | Web (px) | Role |
|---|---|---|---|
| Title | 18–24 | **48** | Action Title — the headline conclusion on a content slide |
| Sub | 14 | **28** | Subtitle / column-title / lede (optional tier) |
| Body | 10–12 | **24** | Paragraphs, list items, table cells, captions |
| Foot | 8 | **16** | Footnote, eyebrow, pill, tag, attrib, source, page metadata |

**Hard rule**: every CONTENT slide uses **only these four sizes**. The
hierarchy ratio (48 / 24 = 2.0×, 24 / 16 = 1.5×) is what makes the
deck read crisply from 5 m back.

##### What's a "content page" vs a "hero exception"

| Type | Tier system | Examples |
|---|---|---|
| **Content** (80% of slides) | 4-tier strict | content-3up · content-2col · stats · table · timeline · process · agenda body · scene-grid · north-star-map · the body of EVERY content slide |
| **Hero exception** (≤20%) | Master-spec values, OUT of 4-tier | cover hero title (100) · section chapter-num (160) · section H2 (88) · big-stat number (132+) · quote blockquote (88) · end slogan PNG |

Hero exceptions appear ONLY in their respective layouts and ONLY for
the explicit hero element. Everything ELSE on those slides (cover
author, section lede, big-stat caption, etc.) still uses the 4-tier.

##### CSS variables for 4-tier (framework provides them)

```css
:root {
  --fs-title: 48px;   /* Action Title */
  --fs-sub:   28px;   /* Subtitle (optional) */
  --fs-body:  24px;   /* Body copy */
  --fs-foot:  16px;   /* Footnote / chrome */
}
```

Author CSS in per-page `<style>` blocks should prefer the variables
over hardcoded px:

```css
[data-page="03"] .slide .card-title { font: 700 var(--fs-title) / 1.2 var(--fs-font-cjk); }
[data-page="03"] .slide .card-body  { font: 500 var(--fs-body)  / 1.5 var(--fs-font-cjk); }
```

Plain `font-size: 48px` is fine too — the validator accepts both forms.

##### Enforced by validator R06 + R20

- **R06 chrome floor**: any content-page selector that doesn't match a
  body class (chrome / pill / tag / foot / eyebrow / attrib / source /
  pageno / `.ui-*` mockup / etc.) must be ≥ 16 px. Below 16 → error.
- **R06 body floor**: any selector matching body classes (`.cbody` /
  `.body` / `.desc` / `.sub` / `.lede` / `.paragraph` / `.caption` /
  `.feat-body` / `.dir-desc` / `.sc-obj` / `.sc-lever` / `.arch-item` /
  `.arch-base` / `.principle` / `.voice-card` / `.cta-box` / `.who` /
  `.col-text` / `.page-sub` / `.subtitle` / `.ts-tasks` / etc.) must be
  ≥ 24 px. Below 24 → error.
- **R20 type-tier ladder**: every `font-size` in a `[data-page="NN"]`
  scoped CSS rule must be exactly one of `{16, 24, 28, 48}`. Anything
  else fails as `R20 off-tier`. Framework CSS (feishu-deck.css) is
  exempt — its hero rules (88/100/132/160) come from master spec.

##### Opt-outs (sparingly, document why)

- `/* allow:typescale */` — full exemption from R06 + R20. Use for:
  1. Hero exceptions in per-page CSS (cover 100, section 88/160,
     big-stat 132+, quote 88+ when authored per-page).
  2. Mockup-internal text inside `.ui-window` / `.ui-doc` simulations
     (10–13 px to look "small inside a real-size app").
- `/* allow:body-floor */` — exempt this specific rule from R06's
  body floor only. Extremely rare.
- `/* allow:white-opacity */` — exempt from R-WHITE-TEXT (unrelated
  but lives in the same opt-out family).

##### Common drift to recognize and fix

The 4-tier is so simple that drift is obvious. If you find yourself
typing any of these px values in per-page CSS, you're off-tier:

```
DRIFT          → SNAP TO
  14, 18, 20   → 16 (chrome / pill / tag) or 24 (body)
  22           → 24 (body floor, was OLD value, bumped 2026-05-16)
  26, 30, 32   → 28 (sub)
  36, 38, 40   → 48 (title)
  44, 52, 56   → 48 (title)
```

**Why this strict regime**:
- Hierarchy reads instantly when there are 4 size values, not 8 or 12.
  48 / 24 / 28 / 16 gives 2× / 1.16× / 1.5× ratios — the eye picks
  up "this is a title, that is a body" pre-attentively. Sub-tier
  drift (5 sizes between 28 and 18) blurs the boundaries.
- Pre-2026-05-16 the skill ran an 8-rung ladder (10/14/18/22/28/38/44/
  52/56/64/88/100/132/160). Every deck had 8–12 distinct sizes. Users
  consistently flagged "层次不够突出" and "字还是小". The 4-tier collapses
  that range into the 4 spec values.

##### Postmortems (kept for context — pre-2026-05-16 sizing)

- **P32**: 5+ iterations because elements were sized 16 / 22 / 24
  ad-hoc. The eye read 22 / 24 / 28 as "three slightly different
  sub-titles" rather than one consistent rhythm. Under 4-tier
  this can't happen — only 24 exists in the body range.
- **20260505 P03/P06**: timeline events at 17 / 18 / 15 (below body
  floor AND off-ladder); market-card text at 24 / 16 / 16. The 4-tier
  ladder makes the "snap" choice trivial: 24 for body content, 16
  for chrome.

#### Goldilocks zones — decorative elements have only TWO safe sizes (2026-05-16)

Decorative elements (large numerals, display markers, eyebrow indices
like "01 / 05") that AREN'T semantic content must sit in one of two
safe size zones, NEVER in the middle.

For a slide with Title at 48 px:

| Element size | Zone | Outcome |
|---|---|---|
| ≥ 86 px (1.8× Title) | **Hero zone** | "I'm decoration, not text" — reads as visual marker |
| 24–48 px (0.5–1.0×) | **Muddled middle** ⚠️ | Eye can't tell — looks like a wannabe-title that's too small |
| ≤ 19 px (0.4× Title) | **Chrome zone** | "I'm an index / aux info" — reads as eyebrow / footnote |

**Don't sit in 50–80% of the title size.** A decorative numeral at
24, 28, 32, 38, 40 next to a 48 title looks "stuck" — neither
clearly Hero nor clearly Chrome.

**Concrete rule for decorative numerals**:
- Big-numeral-overview cards (like Pattern N, 5-up overview): use
  ≥ 88 px (Hero exception, requires `/* allow:typescale */`).
- Eyebrow-style "N of 5" markers: use **16 (Foot)** as the framework
  `.content-tag` or the new `.column-pill` would in their default.

**Postmortem (20260516 南区周会 slide 1)**: hero numerals iterated
88 → 64 → 16 → 28 → 24 → 88 over 6 rounds. Every middle value
"looked stuck"; user kept saying either "too small" (24) or "too
big" (88) depending on which way they were leaving from. The
Goldilocks rule formalizes this: don't even TRY the middle.

#### Content-context label floor — labels in content cards NEVER get 16 chrome (2026-05-17, broadened 2026-05-23)

When a card / panel contains **any content-tier text (≥ 28 px Sub
tier or above)**, every **content label** in the same card must be
**≥ 24 (Body tier)**. The 16 (Foot / chrome) tier is reserved for
page-level metadata ONLY (reached via `.header` / `.footer` /
`.source-footer` / `.pageno` / `.wordmark` ancestor).

**Broadened 2026-05-23**: originally the rule required a 48 px hero
anchor inside the card. Empirically (PROMPTS.md corpus: 85 "字小"
complaints across 8 decks), users complained equally about chrome
labels in cards that had only a 28-44 Sub-tier anchor (e.g.
`story-case .industry-tag`, `logo-wall .ind-name`,
`script-card .card-num`). Lowered anchor threshold from 48 → 28
(any content-tier text in the card triggers the floor).

| Element role | Tier | Examples |
|---|---|---|
| Hero anchor | 48+ | Hero numeral, big-stat number, display title |
| Sub anchor | 28-44 | Story-hook, card title, scene name, action title |
| Content label (introduces a value) | **24 Body MIN** | "北极星" / "核心售卖" / "交付" / "触达" / "已读" / "个性化对象" / "痛点 / 冲突 / 解法" / "时间维度" / "剧本 01" |
| Page-level chrome | 16 Foot | `.pageno` / `.source` / `.footnote` / `.copyright` / `.attrib` (REQUIRES `.header` / `.footer` ancestor — chrome class inside content card still flags) |

**Why this rule exists** (showcase eval 2026-05-17):

When a card looks like `[88 hero][48 title][24 body][16 label]`,
the 16 label DISAPPEARS — the reader's eye locks onto 88+48+24 as
the content rhythm and treats 16 as noise (or skips it entirely).
On 1920×1080 projectors at 4-5m viewing distance, 16 px CJK is
~3 mm tall — below the threshold for casual scanning.

The fix is NOT to bump 16 → 18 / 20 (still off-tier AND still too
small). The fix is to **promote the label to 24 Body** so it joins
the readable rhythm. If the visual hierarchy worry is "now the
label is the same size as the value below it", use **font-weight
700** or **brand color** to differentiate — those are free hierarchy
levers that don't require shrinking the font.

**Concrete examples from showcase iteration**:

- ❌ `.ns-card .star-label` at 16 (gray) next to `.star` at 24 (white):
  the field name "北极星" reads as throwaway; reader doesn't know
  what "门店坪效" IS. FIX → `.star-label` 24 brand-bold, `.star` 24
  white-regular. Same size, hierarchy via weight + color.
- ❌ `.stats .trend` at 16 chrome ("触达") above the 88 hero number:
  the eyebrow vanishes; viewers see "3 秒" but can't tell it's
  about reach time vs ROI vs decision time. FIX → `.trend` 24
  brand-bold.
- ❌ `.scene-card .sc-label` at 16 chrome ("个性化对象") above the
  24 body value: same disappearing-label problem. FIX → 24.
- ❌ `.evolution-chip .stage-tag` at 16 ("现阶段" / "未来"): readers
  can't anchor the two-row evolution. FIX → 24 brand-bold.

**Decision tree before sizing any label**:
1. Is this label IN a card that has a hero anchor (≥48 element)?
   → YES: minimum 24 (Body). Use weight + color for differentiation.
   → NO: 16 (Foot) is OK if it's true page chrome.
2. Is this label INTRODUCING content the reader needs to understand?
   → YES: 24 minimum. Without the label, the value is orphan.
   → NO (purely decorative numbering, page footer, source line): 16.

**Postmortem (20260517 showcase eval)**: 7 of the user's 10
complaints in slides 6/9/14/16/17/22/24 reduced to this single
rule. Until codified, every per-page CSS that used 16 for a
content-label produced "字小了" feedback even though the slide
passed the 4-tier ladder and body-floor checks.

#### Card density — title-size depends on cards-per-page (2026-05-16)

When you author N parallel cards on a slide, the per-card title size
must scale DOWN as N grows. A 48px Title on 4 cards reads decisively;
the same 48px on 8 cards crowds the canvas and the cards lose visual
breathing room.

| Cards per slide | Card title tier | Why |
|---|---|---|
| ≤ 4 cards | **48 (Title)** | Plenty of horizontal room per card; 48 is decisive |
| 5–6 cards | 28–48 (author judges) | Depends on card aspect ratio. Wide cards still fit 48; narrow drops to 28 |
| ≥ 7 cards | **28 (Sub)** | 48 titles make the page feel "full"; 28 is the right rhythm for dense grids |

When in doubt with 5–6 cards: shrink to 28, OR shrink the card count
by consolidating related items. Don't keep 48 and add cards.

**Postmortem (20260516 南区周会 slide 8)**: 8 todos rendered with 48
titles in a 4×2 grid → cards visually fought each other, user flagged
"太满 / 拥挤". Dropping titles to 28 (Sub) fixed it without losing
content.

#### Nested grids must replicate the parent's column ratio (mandatory)

When a region (e.g. `bottom-cta`, a strip of CTA pills) sits *underneath*
a 2-column main grid and is supposed to align with those columns, its
internal `grid-template-columns` MUST replicate the parent's ratio AND
gap, not default to `1fr 1fr; gap: 24px`.

```css
/* parent stage */
.stage {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.05fr);
  column-gap: 36px;
}

/* ✅ CORRECT — child grid copies parent's ratio + gap */
.bottom-cta {
  grid-column: 1 / -1;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.05fr);
  column-gap: 36px;
}

/* ❌ WRONG — child re-invents 1fr 1fr; split line ≠ parent's */
.bottom-cta {
  grid-column: 1 / -1;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}
```

Why: the user's design rule is "right-side elements (lede, report-mock,
right-CTA) all share the same left edge — the 96 px-derived right
column line". With unequal column ratios (1fr vs 1.05fr) the split line
is at ~52 % of stage width, not 50 %. A nested 1fr/1fr CTA strip places
its split at 50 %, leaving the right pill ~14 px misaligned vs the
report-mock's left edge.

The same rule applies to ANY nested grid that visually overlaps the
parent's columns: footer toolbars, KPI strips spanning two columns,
gallery rows under a 2-col content area. If the child doesn't need to
align (e.g. bottom-cta is intentionally a 3-equal-pill strip), this
rule doesn't apply — but say so explicitly with a comment.

**Postmortem**: P32 right CTA pill kept misaligning by ~14 px under
the report-mock. Root cause: parent stage was 1fr/1.05fr but
bottom-cta was 1fr/1fr. Fixed by replicating the ratio.

#### Color contrast floor — body text on dark slides MUST be white (mandatory)

The brand background is dark (~ #080C18). Pure white `#fff` reads
crisp; gray text vanishes when projected. **All semantic body text
(card titles, sub-headings, descriptions, large numerals, captions,
list items) on dark slides MUST be `#fff` or `rgba(255,255,255,0.95)+`
— not the lower-opacity gray tokens.** Specifically, **stop using
these for body text:**

- ❌ `var(--fs-text-72)` / `rgba(255,255,255,0.72)`
- ❌ `var(--fs-text-78)` / `rgba(255,255,255,0.78)`
- ❌ `var(--fs-text-65)` / `rgba(255,255,255,0.65)`
- ❌ `rgba(255,255,255,0.55)` (large numerals shouldn't fade either)

Use them ONLY for:
- True chrome / metadata (page no., footnote disclaimer, axis labels — not body)
- Decorative atmosphere (subtle outlines, dim background hints)
- Disabled/inactive states (mute pills, secondary tabs)

**Rule of thumb:** if the text is *information the audience must
read* — title, sub-head, description, big number, caption under
a screenshot, key data label — it goes to `#fff`. If it's *decoration
or chrome* — fade is OK, but never apply fade to anything carrying
meaning.

This applies regardless of font size and is independent of the
typography floor above. (A 22 px gray description is still
unreadable on a projector. The fix is white, not bigger.)

#### No nested frames — max ONE visible card boundary per content unit (mandatory)

When authoring per-page CSS, **do not stack three layers of bordered
boxes inside each other**. A "frame" is any element with both
`border` (or `box-shadow` ring) AND a fill color/`background`.
Triple-nesting reads as "boxes in boxes" and is the #1 reason
single-page polish slides feel cluttered.

**Counted as 1 frame each:**

- An outer `canvas` / `panel` wrapper card (border + fill).
- A `step-card` / `feat-card` / `dir-card` (border + fill).
- A `mini-ui` mock or a `chart-frame` (border + fill).
- A `factor-chip` / `tag` (border + fill counts as a frame too,
  but small chips are usually OK if their parent is a flat row,
  not another card).

**The cap is 2 visible frame layers max** for any vertical pixel of
the slide. Three or more is forbidden:

```
✗ stage → canvas-frame → step-card → mini-ui     (3 frames — fail)
✗ outer-card → inner-item → icon-bg-tile          (3 frames — fail)
```

**How to fix when you find yourself nesting:**

- **Drop the outer wrapper.** If `canvas-frame` only exists to draw a
  border around step-cards, delete it and put the step-cards directly
  on the slide background.
- **Replace the inner with a hairline.** If you need to subdivide a
  card, use a 1px section divider or a section colored bar (e.g.
  `border-top: 2px solid var(--fs-violet)`) instead of a fully
  bordered sub-card.
- **Section-color the parent, kill the child border.** E.g. the parent
  card's left edge is a 4px violet bar, and the inner content sits
  flat with just text + spacing — no inner card.
- **Use background tone, not borders.** A slightly-lighter rectangular
  block inside a card (no border) signals grouping without adding a
  frame.

Chips, pills, and tag rows that themselves have borders are allowed
inside a card (1 card + N chips = still counted as 2 frame layers
total, since the chips don't nest into a third level).

#### Sibling frames — merge into one card when they're a single content unit (mandatory)

The "no nested frames" rule above covers VERTICAL nesting. This rule
covers a different failure mode: **two stacked sibling frames that
together represent one content unit**. Common case:

```
┌─────────────────────────┐   ← floating pill (frame 1)
│  传统模式: 业务提需求     │
└─────────────────────────┘
┌─────────────────────────┐   ← bullet card (frame 2)
│  · IT 团队: ...          │
│  · 业务团队: ...         │
└─────────────────────────┘
```

Even though they're not nested, the "mode card" is conceptually ONE
unit (header label + supporting body), and rendering it as **two
independent bordered boxes stacked vertically** reads as visually
fragmented. Default to merging into a single frame:

```
┌─────────────────────────┐   ← single frame
│ 传统模式: 业务提需求       │   ← header section (color-block top)
├─────────────────────────┤
│ · IT 团队: ...           │   ← body section
│ · 业务团队: ...          │
└─────────────────────────┘
```

**Decision rule** — before splitting into 2 sibling frames, ask:

> "Does this header label make sense WITHOUT its supporting body?"

If the answer is "no" (e.g., "传统模式" is meaningless without the
bullets explaining what it means), merge them. Use a `1px solid` divider
or a `border-bottom` on the header section instead of two separate
borders. The header gets a stronger fill (gradient / accent) to
visually differentiate it within the merged card.

**Common merge patterns:**

```css
/* parent: single frame */
.mode-card {
  border: 1.5px solid <accent>;
  border-radius: 18px;
  overflow: hidden;     /* clip header gradient at radius */
  background: <body-bg>;
}
/* header section: differentiated bg, NO independent border */
.mode-card .head {
  padding: 16px 26px;
  background: <accent-fill>;
  border-bottom: 1px solid <hairline>;
  text-align: center;
}
/* body section: shares parent border, just padding */
.mode-card .body {
  padding: 22px 28px;
}
```

**When 2 sibling frames ARE OK** — when the two are independent
content units (e.g., a "metric card" and a "trend card" stacked, where
each can stand alone), they SHOULD have their own frames. The rule is
about merging frames for ONE conceptual unit, not about banning
vertical card stacks in general.

**Postmortem**: P35 v2 had a floating mode-head pill + a separately
bordered mode-list card per side. Header pill made no sense without
the bullets it labeled — they were one unit. Merging into a single
mode-card with header-section + body-section eliminated 2 of the
4 visible frames on the page (one per side) and the page felt
visibly more substantial / less cluttered, with no information loss.

#### Reserved class names — do NOT redefine in per-page `<style>` (mandatory)

`feishu-deck.css` ships several **global utility classes** scoped at
`.slide .<name>`. Authoring a per-page `<style>` block that defines a
selector with the same class name causes hard-to-debug visual
collisions — the global rule wins on specificity for properties you
didn't override, so your custom container gets force-shrunk /
force-positioned in ways that look broken without an obvious cause.

**Reserved class names (search `feishu-deck.css` before reusing any
short common name; this list grows over time):**

| Class | Built-in behaviour |
|---|---|
| `.tile` | **64×64 icon tile** with `display: grid; place-items: center` (background tinted by `--fs-accent`). If you author `.tile { display: grid; grid-template-columns: 160px 1fr; padding: 12px 18px; ... }`, the 64×64 width/height wins, your padding is clipped, and inner CJK text wraps to one char per line. |
| `.pill` | Generic pill chrome with padding + border-radius. |
| `.eyebrow` | Uppercase Latin tracked label. |
| `.keyline` | 96×3 keyline accent bar. |
| `.title-zh` / `.title-en` / `.title` | Bilingual title typography. |
| `.wordmark` | Top-right 飞书 logo container. |
| `.stage` / `.header` / `.footer` | Slide structural shells. |
| `.deck` / `.slide` / `.slide-frame` | Top-level deck shell. |
| `.deck-progress` / `.deck-controls` | Present-mode chrome. |

**Convention for custom containers**: prefix per-page classes with a
2–4 char scope tag matching the slide topic, e.g. `.kpi-tile` (not
`.tile`), `.case-card` (not `.card`), `.qa-pill` (not `.pill`),
`.report-toc` (already scoped under `.report-mock`).

**Symptom catalog** to recognize collisions early:
- Custom container collapses to 64×64 → you used `.tile`.
- Padding ignored / borders missing → check `.pill` / `.eyebrow`
  collision.
- Text wraps to one CJK character per line inside what should be a
  wide row → almost always `.tile` collision (the 64px width forces
  the column to be 1-CJK-glyph wide).

**Postmortem**: P29 量化成效 KPI strip broke this rule three iterations
in a row — the local `.tile { display:grid; grid-template-columns:160px 1fr; }`
got overruled by the global `.slide .tile { width:64px; height:64px; }`,
producing 3 empty 64×64 boxes with vertically-stacked CJK labels
spilling out to the right. Renaming to `.kpi-tile` fixed it
immediately. If you see a layout that "looks like the rule didn't
apply", grep `feishu-deck.css` for your class name FIRST.

#### Bar chart · X-axis alignment & in-chart brand logos (mandatory)

When a slide has a bar chart with brand logos under each bar (e.g. P07
万店时代 timeline, P29 quality-check store list), three rules apply:

**1. X-axis baseline must touch bar bottoms · zero gap**

The chart's X-axis line (`::after` pseudo) and the bar `<div class="fill">`
bottom must sit at the *same Y pixel*. The standard pattern:

```css
.store-chart {
  position: relative;
  display: flex; flex-direction: column;          /* MANDATORY · see note below */
  padding: 24px 60px <LABEL_AREA_HEIGHT>px 80px;  /* leave bottom space for logo+brand+date */
  min-height: 540px;
}
/* X-axis line — sits exactly at the top of the label area = bar bottoms */
.store-chart::after {
  content: ''; position: absolute;
  left: 60px; right: 32px;
  bottom: <LABEL_AREA_HEIGHT>px;       /* MUST equal padding-bottom */
  height: 1px;
  background: linear-gradient(90deg, rgba(60,127,255,0.55), rgba(60,127,255,0.10));
}
.store-bars {
  display: grid; grid-template-columns: repeat(N, 1fr);
  align-items: end;                     /* bars sit on container bottom */
  padding: 0 24px 0 16px;               /* padding-bottom: 0 — bars touch baseline */
  flex: 1;                              /* MANDATORY · fills chart content area top-to-bottom */
  min-height: 0;                        /* allow flex to override default content sizing */
}
.store-bar .fill {
  /* heights via .h-XXXX classes; no margin-bottom — flush to bars-container bottom */
}
```

**The `flex: column` + `flex: 1` pair is mandatory, not decorative.**
Without it, `.store-bars`'s natural height = max bar height (e.g. 260 px).
The chart `min-height: 540px` minus `padding-top + padding-bottom`
(174 px) leaves **366 px content area** — but `.store-bars` only fills
260 px of that, so it floats 106 px above the chart's content-area
bottom. Meanwhile `::after { bottom: <LABEL_AREA> }` is anchored to
the chart's content-area bottom. Result: **X-axis line sits 100+ px
below the bars** and the chart looks broken. Forcing `.store-bars`
to `flex: 1` makes it span the full chart content area so its
`align-items: end` baseline lines up exactly with `::after`.

**Forbidden**: any `padding-bottom > 0` on `.store-bars`, or any
`bottom != LABEL_AREA_HEIGHT` on `.store-chart::after`, or omitting
the chart `flex: column` / bars `flex: 1` pair. All of these produce
a visible gap between the X-axis line and the bars and instantly look
amateur.

**2. Brand logo placement: BELOW the X-axis line, not on top of bars**

Logos go in `.label-wrap` absolutely positioned `top: calc(100% + 14px)`
relative to `.store-bar`. Since `.store-bar`'s bottom = bars-container
bottom = X-axis line, this puts the logo card 14 px below the X-axis.

The label area should contain (in vertical order): **logo · brand name
· optional `hq-tag` · date**. Bar count `<span class="count">` goes
ABOVE the bar (not in the label-wrap).

**3. Brand logos MUST preserve aspect ratio · NO circular frames for
non-square logos**

The frequent failure mode: developers default to a 56×56 round avatar
frame with `background-size: 80% 80%` or `cover`, which **stretches**
horizontal logos (`美宜佳`, `沪上阿姨`) into a vertical box. Don't.

**Standard pattern**:

```css
.store-bar .logo {
  width: 96px; height: 44px;            /* rectangular card, ~2.2:1 ratio */
  border-radius: 6px;
  background-color: #fff;
  background-position: center;
  background-size: contain;             /* mandatory — preserves aspect ratio */
  background-repeat: no-repeat;
  padding: 4px;
  border: 1px solid rgba(255,255,255,0.20);
}
.store-bar.is-hero .logo { border: 2px solid var(--fs-blue); }
```

`background-size: contain` is **mandatory** for any logo container with
mixed-aspect-ratio logos (any chart with both wide and square brands).
Use circles ONLY when every logo in the set is verifiably square (logo
files in `clientlogo/` cropped 1:1) — otherwise rectangles.

**Hero callout**: don't use a glow `box-shadow: 0 0 16px ...` on hero
logo — that's a R12 real drop shadow. Use a colored `border` or a
`0 0 0 2px ring` shadow.

### Step 4 · End page (`data-layout="end"`) — MUST follow master spec

The 飞书 master closing is intentionally minimal: flower background +
colored logo top-left + slogan PNG. **No title. No CTA. No contact
grid.** Optional contact line allowed.

| Element | Spec |
|---|---|
| Background | `lark-cover-bg.jpg` (same as cover) |
| Logo | top-LEFT at (120, 121), COLORED, 235×74 |
| Slogan | `lark-slogan.png` ("先进团队 先用飞书") at (102, 348), 561×345 |
| Contact line | optional, bottom-left at top:80 |
| Title / CTA / contact grid | NONE (off-master, do not add) |
| Footer | NONE |

```html
<div class="slide" data-layout="end" data-screen-label="13 End">
  <div class="wordmark">飞书</div>
  <div class="slogan" role="img" aria-label="先进团队 先用飞书"></div>
  <!-- optional, off-master -->
  <div class="contact">contact@feishu.cn  ·  feishu.cn</div>
</div>
```

If the source has CTA pills / contact grids and you really need to keep
them, break with the master and document the deviation in the deck's
opening comment. Default = stay with the master.

### Step 5 · Run the validator BEFORE responding

```bash
# Validate THE USER'S converted run (not the bundled sample). build.sh --inline
# rebuilds examples/sample-deck*, so never use it to inline/validate a real deck.
python3 assets/validate.py runs/<ts>/output/index.html --strict
python3 deck-json/render-deck.py runs/<ts>/output --inline   # inlines index.html of THIS run in place
python3 assets/validate.py runs/<ts>/output/index.html --strict
```

All four must exit 0. If any check fails (R49 cyan-as-accent, L1 mono
logo, R13 br-in-title, R56 eyebrow-in-header, P50 base64 budget),
**fix the markup, don't suppress the check**.

### Common conversion mistakes (forbidden)

| Mistake | Why it's wrong | What to do instead |
|---|---|---|
| Use `data-layout="cover"` for an internal "agenda" or "section" page | Cover layout has the flower background and left-half text positioning that doesn't suit an agenda | Use `agenda` or `section` |
| Use mono-white logo on content pages | Mono is opt-in for over-imagery edge cases only (L1) | Use the default colored logo |
| Explicit `<br>` inside content-page `<h2>` | Forbidden by R13 | Drop the `<br>`. If the title is long, let it wrap naturally to 2 lines via CSS word-break — DO NOT shorten, truncate, or add ellipsis. The title is content; preserve it verbatim. Browser handles CJK word-break automatically. |
| Add eyebrow above content page title | Forbidden by R56 | Drop the eyebrow; if context is essential, work it into the title or move it to the slide body |
| Re-use source page numbers verbatim in the title area | Footer/pageno retired 2026-05 — page numbers come from the pager UI in present mode | Drop the inline page no.; if you need an editorial label like "07 / 12", do it as a hand-placed `.eyebrow` or `.callout` once per deck, not standardized chrome |
| Inline raster screenshots of 飞书 UI as `<img>` | Forbidden by UI1 | Recreate using `.ui-window / .ui-grid / .ui-list / .ui-msg` etc. |
| Use cyan as a slide accent | Forbidden by R49 (cyan = inline highlight only) | Pick blue / teal / purple / violet / orange instead |
| Free-style `font-size` like 16 / 17 / 19 / 20 / 24 / 26 / 30 / 32 / 36 / 40 / 48 / 72 / 96 in per-page CSS | Forbidden by R20 modular type-scale | Pick from {14, 18, 22, 28, 38, 44, 52, 56, 64, 88, 100, 132, 160}. Body content ≥ 22. If master truly says exactly 96 px, add `/* allow:typescale */` in the rule and document why |

---

