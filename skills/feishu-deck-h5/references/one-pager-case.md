# one-pager-case — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:一页纸客户案例 story-case(skip cover / 禁造 STORY id)

## ONE-PAGER CASE POLICY (mandatory) — 一页纸案例 layout

This is the **canonical layout only when a customer case is explicitly
meant to be rendered as one slide** (一页纸案例 / one-pager case study).
When that explicit trigger applies, use the `.story-case` recipe documented
below — don't improvise a different layout, don't add a cover, don't expand it
into multiple slides unless the user explicitly asks for that.

### NEVER fabricate STORY ids, source attributions, or interview citations

Case slides have a strong gravitational pull toward "looking like a
finished case-library entry" — a STORY 0NN suffix, a "数据来源 · XX
客户访谈" caption, a "本院实践访谈" footer. When the user hands you
raw material that doesn't carry these, the agent fills them in by
default, because the schema and recipe markup show them as fields.

**Don't.** Rule:

- If the user did NOT give you a story id, the brand line is
  `"飞书企业 AI · 客户案例"` — period. Do NOT append `STORY 015` /
  `STORY 0NN` / a fabricated number. The 0NN in template comments is
  a placeholder showing where the user-provided id WOULD go, not an
  instruction to make one up.
- If the user did NOT give you a source citation, OMIT the source
  line entirely (drop `.case-caption` / `.source-footer` from the
  markup; omit the `source` field from the slide's `data`). Do NOT write
  "客户访谈" / "内部口径" / "实践访谈" / "调研口径" as a placeholder
   — these read as factual claims and break trust if the customer
  reads the deck.
- The same rule applies to attribution lines under quotes
  (`<div class="attrib">`) and any `Source · ...` line under stats.
  Either the user gave you a real source, or the line doesn't ship.

When in doubt, ask: "do you have a story id / source citation for
this, or should I leave those off?" — one ping is cheaper than the
trust hit of a fake STORY 015 reaching a customer.

This rule overrides the example schemas. Treat schema fields like
`brand` and `source` that show specimen STORY/source values as
**form**, not **content**: the field exists; you fill it ONLY with
what the user actually provided.

### How to render — `content` layout + `variant: story-case` (Path A DeckJSON)

The one-pager case is a **DeckJSON layout**, not a separate engine. Author
it as a `content` slide with `variant: "story-case"` in `deck.json`, then
`render-deck.py` produces `index.html` (see DECK GENERATION
POLICY for the Path A flow). The 4-beat 痛点/冲突/解法/价值 + hook + scene
shape maps 1:1 to the `data_content_story_case` schema (field reference
below). render-deck.py runs the schema-fit refusal + accent review
automatically (see "Safety nets" below).

> Historical note: pre-2026-05-26 this layout had its own TOML engine
> (`render.py one-pager`). That engine + its `examples/one-pager-luckin/`
> TOML were retired; the layout, the policy in this section, and the two
> safety nets all live in the DeckJSON path now. Old `.toml` cases convert
> 1:1 to a `content/story-case` slide.

#### When story-case doesn't fit — use a different layout (not a different engine)

The 4-beat arc is intentionally narrow. When the case's natural shape
isn't 4-beat, pick the layout that fits instead of forcing it:

1. **User asks for something story-case can't express** — "加一段客户原话",
   "做成 timeline", "用大数字突出 ROI", "把 4 个 beat 改成 6 个观察",
   "case 没有冲突,只有 3 个发现". Switch layout rather than mutilate content.
2. **The story's natural shape** is a one-sentence testimonial → `quote`;
   a hero metric + prose → `stats` variant `hero`; a chronological roadmap
   → `flow` variant `timeline`; 3 parallel observations → `content` variant
   `3up`.
3. **A genuinely one-off visual shape** that no layout + variant covers →
   `layout: "raw"` for that single slide (keep the rest of the deck on
   schema layouts). If the shape recurs across ≥ 2 decks, propose a schema
   extension (deck-json/MIGRATION-REPORT.md Phase 0.2), not a pile of raw
   slides.

Don't switch layout just for per-case flair (different fonts, off-palette
colors, custom logo) — that's drift, not fit. The brand floor below applies
to every layout you land on.

#### Brand floor (mandatory, applies to every layout)

Whatever layout the case lands on, you can vary the *shape* but NOT these
brand basics. The validator enforces most of them:

- Dark cinematic background — `lark-content-bg.jpg` via the master
  decor system, OR a brand-aligned `data-decor` token (no white /
  cream / "Apple style" backgrounds).
- Color palette from `--fs-*` tokens only — no off-palette hex (R10),
  no cyan as slide accent (R49).
- 飞书 wordmark present per L1 (color logo top-right on content,
  mono opt-in only on chapter dividers).
- 16:9 design canvas (1920×1080) — `data-screen-label` on every slide.
- ZH-only by default (no EN translation tracks under every CN line).
- All other validator rules (L1-L4, R02-R56, P50-P55, UI1)
  must still PASS strict. Deviation is a layout choice, not a license
  to skip integrity checks.

If a genuinely new case shape recurs across ≥ 2 decks, propose a schema
extension (a new `content` variant or a new layout) per
deck-json/MIGRATION-REPORT.md Phase 0.2 — that's how the layout catalog
grows, without one-off raw slides accumulating.

#### When the user rejects a story-case output

If the problem is *visual or structural* and it'd recur on the next case,
fix the **template** (`deck-json/templates/content-story-case.fragment.html`)
or its CSS in `assets/feishu-deck-patterns.css`, then re-render — don't
hand-patch the single output's `index.html` (the next render overwrites it,
and the next case hits the same bug).

If the problem is *copy / wording / strategic emphasis*, edit the slide's
`data` in `deck.json` (e.g. `deck-cli set`) and re-render. The template is
fine; the content was wrong.

If the problem is *"this case shouldn't have been story-case at all"*,
switch the slide's layout/variant (see "When story-case doesn't fit"
above) and proactively expand the trigger-detection rules so similar cases
route correctly next time.

### Safety nets — schema-fit refusal + accent review (in render-deck.py)

`render-deck.py` runs two automatic checks for every `content/story-case`
slide (ported 2026-05-26 from the retired render.py). They catch the
predictable failure modes: thin/placeholder beats, and a mis-framed accent.

**1 · Schema-fit refusal (exit 4).** After schema-validate, before render,
every story-case beat is scanned for:

- Placeholder content: `TBD / TODO / TBC / XXX / N/A / 待补 / 占位 /
  稍后补充 / 未填 / None`, ellipsis-only, question-mark-only strings.
- Length floor: meaty beats (`arc.pain / arc.conflict / arc.solution`)
  ≥ 10 chars; `*.accent` ≥ 2 chars; `*.lead / *.tail` ≥ 1 char (connective).
- Duplicate content across beats (laziness signal).

If any beat fails, render REFUSES (exit 4) and lists the offenders. Correct
response:

- Fill the beat in `deck.json` with real content.
- **Switch layout** — the failure often means "this story doesn't have a
  clean 4-beat arc"; use quote / stats-hero / content-3up instead.
- `--skip-fit-check` to bypass, ONLY for a specific reason (intentionally
  terse copy the user confirmed). Not a way to silence the warning.

**2 · Accent review (post-render print).** After a successful render,
render-deck.py prints each accent-bearing field with the highlight marked
(ANSI teal in a TTY, `[brackets]` otherwise):

```
ACCENT 复核 (1 秒目测,被高亮的词是该突出的吗?)
  luckin-case ·  hook  ·  新店垃圾桶距出餐窄 1 米,按 SOP 必须 [砸墙返工] —— …
  luckin-case · value  ·  飞书把这种隐形经验萃取到 [企业 AI 知识库],…
```

Eyeball it. If the bracketed word isn't the emotional pivot (e.g. `1 米`
instead of `砸墙返工`), fix `arc.value.accent` / `hook.accent` in `deck.json`
and re-render.

### Field reference — `data_content_story_case` (deck.json)

Full schema: `deck-json/deck-schema.json` → `$defs/data_content_story_case`
(`required: title, industry, hook, arc, scene`). The `data` block of a
story-case slide:

```jsonc
{ "key": "case-<slug>", "layout": "content", "variant": "story-case",
  "accent": "blue", "decor": "blue-glow",
  "screen_label": "01 客户案例 — 标题",
  "data": {
    "title":    "客户/项目 · 案例标题",           // single line, no <br> (R13)
    "industry": "行业 · 场景 · 客户案例",          // short pill tag
    // OPTIONAL story-id / source — ONLY if the user gave one. NEVER fabricate.
    "hook":  { "lead": "…before…", "accent": "强调动词", "tail": "…after…" },
    "arc": {
      "pain":     "…",                              // blue   · ≥10 chars
      "conflict": "…",                              // orange · ≥10 chars
      "solution": "…",                              // teal   · ≥10 chars
      "value":  { "lead": "…", "accent": "…", "tail": "…" }   // violet
    },
    "scene": { "image": "input/scene.png",          // path relative to deck.json
               "caption": "现场 · 一句话场景说明",
               "alt": "无障碍描述,完整场景内容" }
  } }
```

Render with the standard Path A flow:
`python3 deck-json/render-deck.py runs/<ts>/output/deck.json runs/<ts>/output/`.
Outputs `index.html`; the scene image is copied in. A non-zero
exit on a story-case slide is usually the schema-fit refusal (exit 4) — read
the offenders, not a template bug.

### Trigger detection — when to use this layout

Apply the one-pager case layout ONLY when at least one explicit trigger is true:

- The user explicitly says **"一页纸案例" / "one-pager case" / "做成一页"
  / "single-page case study" / "压成一页" / "one-page version"**.
- The user explicitly asks for the 4-beat customer-story shape:
  `痛点 / 冲突 / 解法 / 价值` plus hook and scene, or names
  `story-case` / `content/story-case`.
- The current `outline.json` or existing `deck.json` already specifies
  `schema:content/story-case`, `layout: "content"` + `variant: "story-case"`,
  or a `.slide.story-case` page that is being edited in place.

Generic customer-case asks are NOT a trigger by themselves. A single row from a
customer-story table, "做这个客户案例", "把这一行做出来", "render this case", or a
case brief with fields such as 题目 / 行业痛点 / 钩子 / 故事背景 / 核心情节 /
核心价值 should go through the normal design-first, raw-first decision process.
If scope or shape is ambiguous, ask one short question rather than defaulting to
one-pager.

The CSS class `.story-case` (added on the `.slide` element) is the
canonical marker for this layout. Any slide with `class="story-case"`
on `.slide` MUST follow the rules in this section.

### Skip the cover page

When the trigger above applies, **SKIP the `cover` layout entirely**
and open the deck with the one-pager content slide.

### Why this is mandatory

- A single-case deck has no deck-level title that needs a hero cover.
  The case IS the content — a separate cover page wastes a slide and
  forces the reader through a click of pure ceremony before they reach
  the value.
- The case illustration belongs **inside** the content slide as the
  visual (right column / hero image), not isolated on a cover. Putting
  it on a cover divorces the image from the narrative.
- Internal sharers / WeCom forwards / IM previews show only the first
  slide. If that slide is a generic cover, the recipient sees nothing
  about the actual story. If it's the content slide, they see the hook,
  the title, and the visual all at once.

### The one-pager structure (mandatory shape)

`data-layout="content-2col"` with `class="story-case"` on the `.slide`,
arranged as:

- **Header**: the case title (one line, no `<br>`, no eyebrow per R56).
- **Left column** (`.col-text`):
  - `.industry-tag` — small accent chip naming the industry / scenario
  - `.story-hook` — the one-line hook (use a `.accent` span on the
    pivot keyword to highlight in teal)
  - `.story-arc` — 4-row labeled narrative beats:
    `痛点` (blue) → `冲突` (orange) → `解法` (teal) → `价值` (violet)
- **Right column** (`.col-visual`): the case illustration as a hero
  frame (see "Image is the visual hero" below for sizing rules — image
  goes in via `background-image`, NEVER an `<img>` tag, to satisfy UI1).
- ~~**`.source-footer`** (data citation line below the body)~~ **Retired 2026-05** alongside `.footer`. Data citations now live inline in the slide body (as a `.caption`, in a corner `.eyebrow`, or just trailing text). Hide-only CSS keeps any leftover DOM invisible.
- ~~**Chrome footer**: brand line + page number.~~ **Retired 2026-05.** The fullscreen present-mode pager (bottom-center prev/next/page-no bar) now shows the page number; the corner `.wordmark` carries the brand. The renderer no longer emits `<div class="footer">` / `<span class="pageno">`. Validator R07 no longer requires it. Don't add it to new slides.

The 4-beat 痛点/冲突/解法/价值 arc IS the rhetorical structure of a
one-pager case. Don't replace it with generic bullets; the labeled
beats are what carry the narrative through one slide.

### When the case doesn't fit the 4-beat shape

Substitute layouts ONLY when the case content forces it:
- `content-3up` — case naturally splits into 3 parallel beats (e.g.
  "三个发现" without a clear conflict→solution narrative)
- `quote` — case IS a one-sentence customer testimonial (no narrative
  arc, just the voice)
- `image-text` — case is more about the scene than the analysis (e.g.
  "看这家门店一周的状态变化")

NEVER use `cover` / `agenda` / `section` / `end` for a one-pager case.
And NEVER expand a one-pager into multiple slides without the user
explicitly asking — the whole point is that it fits on ONE page.

### Multi-case bundles are different

A deck that bundles **3+ cases** (a "客户案例集" / "story library" /
"quarterly customer review") DOES get the standard treatment:
- `cover` slide with the deck title
- `agenda` listing the cases
- `section` divider per case (optional)
- One or more content slides per case

The "skip the cover" rule is specifically for explicit one-pager case decks.
If unsure, ask whether this is a one-page case, a multi-slide single-case story,
or a case bundle — the answer determines whether the cover stays.

### Cover handling outside explicit one-pagers

For explicit one-pagers, the default remains no cover. Outside explicit
one-pagers, use the normal deck/story scope decision; do not apply this
reference's no-cover default just because the material is a single case.

Use or keep a cover when the user says one of:
- "我要一个封面页" / "give it a cover" / "加一张封面"
- "做成正式提案" (formal proposal explicitly needs a hero cover)
- The single case is going to a board / external customer (formal
  context, cover earns its keep)

### Image sizing — magazine-spread top-aligned (v2, frozen 2026-05-03)

The case illustration is the slide's emotional anchor on the right.
History of the rule (relevant context for future maintainers):

- **v0 (broken)**: `aspect-ratio: 16/9` thumbnail → ~460 px tall image
  with 300 px of empty space below. User feedback: "图太小了".
- **v1 (overshot)**: `min-height: 680 px` hero filling ~88 % of the
  770 px stage zone → image taller than text content, awkward visual
  imbalance. User feedback: "右边的图还是有点大,能不能和左边文字
  的标题对齐".
- **v2 (current)**: image height = LEFT text column's natural height,
  both columns top-aligned, row vertically centered in stage. Reads
  like a magazine spread; image is still ~57 % of the grid width
  (clearly hero by area), but its proportions match the text it
  illustrates.

**Mandatory sizing rules (v2)**:

1. **Column ratio still favors the image.** `1fr 1.3fr` (text 43 %,
   image 57 %). Image is hero by *area*, not by *being taller*.

2. **Top-align both columns; image height equals text height.**
   `grid-template-rows: auto` on `.grid` makes the row natural-sized;
   `align-items: stretch` makes the visual column match the text
   column's height. **Do NOT** set `min-height: 680 px` (the v1 bug)
   or `justify-content: center` on `.col-text` (also v1).

3. **Image is cropped via `background-size: cover`** to fit the
   text-determined height. The 16:9 illustration sitting in a
   ~440 × 950 frame loses ~50 px from top and bottom — fine as long
   as the illustration's main subject is centered (most are).
   Side crop is also fine for the same reason.

4. **Use `background-image`, NOT `<img>`** (UI1 validator treats
   `<img>` in slide content as a possible UI screenshot). Mark the
   frame `role="img" aria-label="..."` for a11y. Per-instance image
   URL goes in inline `style="background-image: url(...)"`, NOT in
   the shared CSS — bundles need per-case `scene-NN.png` filenames.

5. **Caption goes INSIDE the frame as an overlay** (bottom-left
   absolute pill, rgba dark + backdrop blur). Reads like a
   documentary still. Don't stack `frame + caption-below` — it
   shrinks the frame.

6. **`min-height: 360 px` floor** on the frame catches degenerate
   cases where the left text column is unusually short (e.g. a
   one-pager with 2-line beats). Below that, the image stops
   shrinking and the row gets a touch of extra height. Tune this if
   real cases hit it; default is fine for the typical 4-beat shape.

### Reference markup — copy this for a single-case content slide

```html
<div class="slide story-case" data-layout="content-2col" data-accent="blue"
     data-decor="blue-glow" data-screen-label="01 客户案例 — 标题">
  <div class="wordmark"></div>
  <div class="header">
    <h2 class="title-zh" data-text-id="slide-01.title">客户/项目 · 案例标题(单行)</h2>
  </div>
  <div class="stage">
    <div class="grid">
      <div class="col-text">
        <span class="industry-tag">行业 · 场景 · 客户案例</span>
        <p class="story-hook">钩子(一句话定调,核心动词用 .accent 标 teal)。</p>
        <div class="story-arc">
          <div class="row"><span class="lbl">痛点</span><p>…</p></div>
          <div class="row"><span class="lbl is-orange">冲突</span><p>…</p></div>
          <div class="row"><span class="lbl is-teal">解法</span><p>…</p></div>
          <div class="row"><span class="lbl is-violet">价值</span><p>…</p></div>
        </div>
      </div>
      <div class="col-visual">
        <div class="scene-frame" role="img" aria-label="…现场描述…">
          <span class="scene-cap">现场 · 一句话场景说明</span>
        </div>
      </div>
    </div>
  </div>
</div>
```

The story-case v2 CSS lives in `assets/feishu-deck-patterns.css` —
render-deck.py's `content-story-case.fragment.html` links it, so a
v2 → v3 refactor only touches one file. **DON'T inline these rules** in a
`<style>` block on a normal story-case slide.

If you hand-author a one-off story-case as a `layout: "raw"` slide (the
rare case where you need bespoke markup), copy this block verbatim into
that slide's `<style>`:

```css
.slide.story-case[data-layout="content-2col"] .grid {
  display: grid;
  grid-template-columns: 1fr 1.3fr;
  grid-template-rows: auto;             /* row sizes to content (v2) */
  column-gap: 56px;
  align-content: center;                /* center the row in the 770px stage */
  align-items: stretch;                 /* both cols share row height */
}
.slide.story-case .col-text {
  display: flex; flex-direction: column;
  gap: 28px; min-width: 0;
  /* no justify-content: center — content top-aligns inside col (v2) */
}
.slide.story-case .col-visual {
  display: flex; align-items: stretch; min-width: 0; min-height: 0;
}
.slide.story-case .scene-frame {
  position: relative;
  flex: 1; width: 100%;
  min-height: 360px;                    /* floor for degenerate cases (v2) */
  border-radius: 20px;
  border: 1px solid rgba(255,255,255,0.12);
  background-color: rgba(8,12,24,0.45);
  background-repeat: no-repeat;
  /* per-instance: inline style="background-image: url('./scene.png');
                                background-position: center;
                                background-size: cover;" */
  box-shadow: 0 24px 64px -24px rgba(0,0,0,0.65),
              0 0 0 1px rgba(60,127,255,0.16);
}
.slide.story-case .scene-frame .scene-cap {
  position: absolute; left: 18px; bottom: 18px;
  padding: 8px 14px;
  background: rgba(8,12,24,0.72);
  backdrop-filter: blur(8px);
  border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.10);
  font: 500 16px/1.3 var(--fs-font-cjk);
  color: rgba(255,255,255,0.85);
  letter-spacing: 0.04em;
}
```

### Quick check before delivering

Open the slide and ask: *do the left column's first text element
(industry tag) and the right column's image top-edge sit on the same
horizontal line?* If yes, v2 is rendering correctly. If the image
extends above OR below the text content, the row is using `1fr`
instead of `auto` (regression to v1 behavior — fix it).

---
