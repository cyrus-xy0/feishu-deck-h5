# reskin — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:RESKIN 换皮 / 重渲 UI mock / 保留氛围背景

## RESKIN MODE — foreign HTML → feishu chrome (mechanical, one-shot)

The user has an existing single-page HTML (built elsewhere — claude artifact,
hand-coded, output of a non-feishu deck tool, PDF-converted, etc.) and wants
it "feishu-styled" without redesigning the content. This is a **mechanical
chrome rewrite**, NOT a content-design pass.

> **The clarifying question** that disambiguates 90% of these requests:
> "你要换 chrome(标题位置 / 字体 / 字号 / 配色 / logo / 背景) 还是重画内容 /
> 换 layout?" — RESKIN does the first; GENERATION mode (or Pattern H+ etc.)
> does the second.

### Entry — one command

```bash
bash skills/feishu-deck-h5/assets/reskin.sh <input.html> \
    [--slug SLUG] [--strict] [--visual]
```

- `<input.html>` — path to foreign HTML (absolute or relative)
- `--slug SLUG` — slide-key slug (kebab-case). Defaults to filename stem.
- `--strict` — promote validator warnings to errors (final-pass review)
- `--visual` — also run Playwright visual audits (off by default; reskin
  output often hits R-VIS-OVERFLOW / R-VIS-LABEL-FLOOR on dense foreign
  content, needs human iteration)

Output: `runs/<ts>-reskin-<slug>/output/index.html` + `deck.json` +
`FEEDBACK.md`. Single-file inline delivery: `--inline` on render-deck.py,
or `build.sh --inline` after.

### PRECONDITION — source canvas MUST be 1920×1080 (CHECK BEFORE INVOKING)

Reskin **refuses** to process foreign HTML at any canvas size other than
1920×1080. The check runs as the FIRST step in `reskin.py` (before any
CSS / DOM rewrites), so misfit input fails fast with a clear message —
no wasted render + screenshot cycle. **Exit code 3** with actionable
error; no output produced.

**Why this is a hard precondition** (lesson from a 2026-05-28 reskin
session that burned 30 minutes discovering the issue late):

- Foreign HTML's CSS px values (paddings, ring sizes, column widths) and
  JS coords (`buildRing` cx/cy/R, animation positions, etc.) are designed
  for the source canvas. They're MUTUALLY consistent at that size only.
- Scaling CSS px without also scaling JS-positioned elements gives
  **broken layout** (nodes positioned in old-coord-space inside new-size
  container).
- `transform: scale()` preserves proportions but **stretches 3-column
  layouts** so center-column labels overlap into siblings.
- Letterboxing source at native size in 1920×1080 leaves content small
  and unfilled.
- The ONLY actually-correct option is for source to BE 1920×1080 native.
  Conveniently, that's also feishu standard.

**Agent workflow when receiving foreign HTML**:

1. **BEFORE invoking reskin**: grep the source HTML for canvas-size CSS
   (`.slide { width: Npx; height: Mpx }` or similar).
2. If `Npx ≠ 1920` OR `Mpx ≠ 1080`, **tell the user immediately**, BEFORE
   running reskin:
   > "Your source HTML is `<W>×<H>`. Reskin needs `1920×1080` native to
   > produce a faithful result (CSS px + JS coords must be designed for
   > the same canvas). Want me to ask the original author to redo at
   > 1920×1080, or are you OK with reskin refusing this run?"
3. Default = ask user to resize source first. **DON'T** invoke reskin on
   a mismatched canvas just because the user asked — the engine will
   refuse and the user has wasted a turn.

**Tip for claude artifacts**: most claude-generated single-page HTMLs
default to 1280×720 (the assistant's training-era default). When the
user hands you one, the first turn before reskin is usually a chat round
with the artifact author asking to redo at 1920×1080, then reskin runs
clean.

### What reskin ALWAYS does (mechanical transforms)

| # | Action | Source |
|---|---|---|
| 1 | Wrap source body in framework shell `.deck > .slide-frame > .slide[data-layout="raw"]` (renderer's `raw.fragment.html` auto-adds these; we emit deck.json with one `layout: "raw"` slide) | SKILL.md "DECK GENERATION POLICY" raw escape hatch |
| 2 | Strip foreign logo blocks (any element with class containing `logo` / `brand` / `mark` AND containing `<svg>` or the text 飞书/Lark). Framework's `.wordmark` auto-injects the real colored `lark-logo.png` top-right | SKILL.md L1 |
| 3 | Apply `lark-content-bg.jpg` background to slide anchor (base64-inlined into per-page CSS — `var(--fs-asset-content-bg)` doesn't work in inline `<style>` because CSS custom property url() is text-substituted then resolved against the HTML document, not the framework CSS) | SKILL.md content-bg, lesson from this convo iter 2 |
| 4 | Palette rewrite: fuzzy-match every `#hex` and `rgba()` literal to nearest `--fs-*` token (distance ≤ 80 RGB). **Skip grayscale-ish** (max channel diff < 60 — e.g. `#9AA6C2` muted text stays as-is, doesn't false-match to `--fs-violet`). Cyan-ish (distance < 60 to `#24C3FF`) → `--fs-blue` per R49 | SKILL.md R10 / R49 + lesson iter 10 |
| 5 | `strip_scale_script` — surgical excise of `function fit() { ... }` + its call + `addEventListener('resize', fit)` from inline scripts. **NOT** delete-whole-script (would kill `buildRing` / animation init / other content-bearing code that often lives in the same `<script>` block) | lesson iter 7 |
| 6 | `prune_empty_wrappers` — drop UNCLASSED empty divs (residue from extracted title/subtitle/logo). Skip empties WITH class/id/style — they're CSS-decorated drawings like `<div class="circle"></div>` (border-radius dashed circle), not residue | lesson iter 6 |
| 7 | Scope every rewritten rule to `.slide[data-slide-key="reskin-<slug>"]`. **Special cases** in scope step: `.slide` → anchor (NOT `<anchor> .slide` — would target a nested .slide that doesn't exist); `.slide foo` → `<anchor> foo`; `html` / `body` → DROP (foreign global rules conflict with framework chrome); `*` (universal reset) → DROP (would hit `.wordmark` and framework chrome inside slide) | scoping defense |
| 8 | When mapping source `.slide` → anchor, STRIP `border` / `border-radius` / `box-shadow` declarations from the rule body. Source defines these for "slide card in standalone viewport" (1px ring + drop shadow); inside framework's full-canvas wrap they become visible thin lines at slide top/bottom edges | lesson iter 9 |
| 9 | Strip R12 violations: `box-shadow:` values with non-zero offset and not `inset` are dropped. Glow rings (`0 0 Npx ...`) and inset shadows survive | SKILL.md R12 |

### Two operating modes depending on source canvas

**Mode 1 · `extract_to_header = True`** *(non-1920×1080 source — currently
unreachable, see PRECONDITION above. Documented here in case the
precondition is ever relaxed.)*: extract foreign title → `.header >
h2.title-zh` at `top:62`; foreign body inner content → `<div class="stage">`
at `top:220` with flex-column auto-layout. Framework font cascades into
content via `.slide { font-family: var(--fs-font-cjk) }`. Font-size snap +
label-floor bump runs.

**Mode 2 · `extract_to_header = False`** *(1920×1080 native source —
the only path reachable today)*: source already has its own title + chrome
designed for the full canvas. Adding framework `.header` chrome on top
displaces source content downward → overflow. Native mode:

- **NO framework `.header` / `.stage` chrome wrap** — source title +
  layout stay at their native coordinates
- **Capture source's body font-family stack** (usually `"PingFang SC", ...`
  defined on `html, body`) before scope drops those rules; re-assert it
  on `.slide[data-slide-key=X]` so framework's `.slide { font-family:
  var(--fs-font-cjk) }` cascade doesn't change line-heights → ~70px
  cumulative downward shift would push tagline below 1080
- **Font-size snap + label-floor bump default ON** (per user choice B,
  2026-05-28): projector readability per R06/R20 wins over source's
  pixel-perfect layout. Side effect: source content designed for sub-floor
  text inflates and may overflow 1080 — caught by post-render overflow check.
- **`--keep-source-typography` flag** (option A escape): skip snap +
  label-floor, emit `/* allow:typescale */ /* allow:body-floor */`
  comments on every font-size rule so validator accepts sub-spec sizes.
  Use when source's design density genuinely requires its own typography.

### Post-render overflow check (Playwright, last step of reskin.sh)

After validate.py passes, headless-Chromium loads `index.html` at
1920×1080 and enumerates every LEAF element whose `getBoundingClientRect().
bottom > 1080`. Reports each with class / text / overflow px:

```
! content overflow past 1080 boundary (snapped fonts inflated heights):
  · span.b   +40px  "组织知识"
  · span.p   +40px  "集团决策"
  Source content density too high for feishu spec font floors.
  To fix: have source author reduce content by ~40px vertical,
  OR re-run reskin with --keep-source-typography (deviates from spec).
```

The check is non-fatal (warns, doesn't exit) — user needs to either:
- Have source author trim content density (recommended)
- Re-run with `--keep-source-typography` (escape hatch)
- Manually edit `runs/<ts>/output/deck.json`'s per-page CSS to override

### bs4 script-tag quirk (note for maintainers)

When `strip_scale_script` excises fit() and calls `s.string = new_txt` on
the script tag, bs4's `get_text()` returns empty afterwards (script tags
treat content as CDATA, not text-nodes — `.string` setter writes content
correctly but `.get_text()` reads incorrectly). The surviving-scripts
collection uses `str(s)` and inspects the rendered HTML inner; do NOT use
`.get_text()` to check whether a script has content post-modification.

### What reskin REFUSES to do (hard rule, no flag overrides)

- **Restructure the foreign layout's semantic hierarchy** — the source's
  dual-flywheel stays a dual-flywheel; we don't swap it for Pattern H+
  Two-hand-arch even if that "fits better"
- **Swap one narrative pattern for another**
- **Drop content** that's part of the source's information density (we
  preserve every card, every label, every row)
- **Add content** not present in the source (no LLM augmentation — the
  user's content density is preserved)
- **Anything requiring reading the source's intent** rather than its markup

If the user actually wants those things, they should ask for GENERATION
mode with explicit redesign instructions. Reskin is a paint job, not a
remodel.

### Pipeline (what reskin.sh does internally)

```
input.html
   ↓ PREFLIGHT (writable mount check)
   ↓ new-run.sh reskin-<slug> → runs/<ts>-reskin-<slug>/{input,output}/
   ↓ cp input.html → input/
   ↓ FEEDBACK.md stub (so render-time validate doesn't warn R-FEEDBACK)
   ↓ reskin.py canvas preflight (1920×1080 required; else exit 3)
   ↓ reskin.py transforms (above 9 mandatory + Mode 1/2 split)
deck.json {layout: "raw", data: {html: "<style>...</style>" + body content}}
   ↓ render-deck.py (auto wraps .deck > .slide-frame > .slide + .wordmark)
runs/<ts>/output/index.html
   ↓ copy-assets.py (bundle framework CSS/JS into output/)
   ↓ validate.py (--no-visual by default; --visual opt-in)
   ↓ Playwright overflow check (every leaf element vs y=1080 boundary)
   ↓ ✓ PASS → hand back path to user
   ↓ ! warn if any element overflows: list class/text/overflow-px,
     suggest source content trim OR --keep-source-typography re-run
```

### Tuning (non-engineer)

`assets/reskin-rules.yaml` carries every threshold + hint list. Edit and
re-run; no code change needed. Knobs:

| Section | What you change |
|---|---|
| `palette` | Add brand colors; nudge RGB if a new feishu accent ships |
| `palette_match_threshold` | Looser (default 80) = more aggressive swap to `--fs-*`; tighter = preserve more original colors. Grayscale-ish (max channel diff < 60) is hardcoded-skip — change in `_is_grayscale_ish` if needed |
| `font_size_snap_table` | If you want a 5th tier (e.g. 88 hero) → add row. The 4-tier default matches SKILL.md R20 |
| `content_label_floor.card_class_hints` | Add class substrings that mark "containers worth applying the floor rule to" |
| `foreign_chrome.logo_signals` | Brand-text patterns + class hints that identify logo blocks worth stripping |
| `foreign_chrome.title_candidates` | Tag+class hints reskin uses to find page title (Mode 1 only; Mode 2 leaves title in source) |
| `header_chrome.*` | Master coords for Mode 1's `.header` + `.stage` placement (Mode 2 ignores all of these) |
| `auto_layout.flex_grow_class_substring` | Mode 1 only: class substrings whose div should grow to fill stage height |

CLI flags:

| Flag | Effect |
|---|---|
| `--slug SLUG` | Slide-key slug (kebab-case). Defaults to input filename stem. |
| `--strict` | Promote validator warnings to errors. Use for final-pass review. |
| `--visual` | Also run Playwright visual audits during validate.py (R-VIS-* family). Off by default — reskin output often hits R-VIS-OVERFLOW on dense foreign content; overflow check (last step) catches this separately with more actionable diagnostics. |
| `--no-visual` | Force visual audits off (default). |
| `--keep-source-typography` | Mode 2 escape: skip font-size snap + label-floor bump. Source's hierarchy preserved; validator R06/R20 satisfied via auto-emitted `/* allow:typescale */ /* allow:body-floor */` comments. Use when source's design density requires sub-floor text and you accept the spec deviation. |

### When reskin output still needs human iteration

Reskin is V1 — it handles the mechanical 80%. The remaining ~20% needs eyes:

- **Overflow on dense foreign content** — 1280×720 sources scaled 1.5×
  sometimes exceed framework `.stage` (which expects content sized for
  1920×1080 native). Fix: trim source content, OR enlarge `.stage` via
  per-page CSS override
- **Label-floor missed a class** — `card_class_hints` doesn't cover every
  foreign class name (e.g. `.unique-thing`). Either add the hint to
  `reskin-rules.yaml` or manually bump that class's font-size in the
  rendered output
- **CJK orphan wrap** — `R-VIS-ORPHAN` warns when a short label wraps to
  a 1-2 char last line. Fix: widen the container, add `text-wrap: balance`,
  or shorten the label
- **Foreign pattern has no framework analog** — e.g. flywheel / cycle /
  loop diagrams aren't in the catalog (Pattern A–N). Reskin preserves the
  source's bespoke geometry, which is correct, but the slide loses the
  "this would be cleaner as a framework block" upgrade. To formalize a
  recurring pattern, use `contribute-catalog` skill to PR a new block

### META-RULE — ask before any non-mechanical trade-off

This is the most important lesson from the 2026-05-28 conversation. The
agent silently picked trade-offs at multiple points and burned hours
discovering each was wrong only after the user pushed back. The rule:

> **Anything that isn't a deterministic mechanical transform — STOP and
> ask the user before doing it.** Present the trade-off explicitly, list
> the options, wait for choice. Don't decide for them.

Concrete trigger patterns:

| Trade-off | Wrong (silent) → | Right (ask) |
|---|---|---|
| Source canvas ≠ 1920×1080 | "Letterbox it" / "scale-wrap" | "Source is `<W>×<H>`. Reskin requires 1920×1080. Want to ask source author to resize, OR refuse this run?" |
| Source has own title at native coords | "Extract to framework `.header`" | "Source's title sits at its own native coords. Extracting to framework `.header` will displace content downward. Keep source layout, or use framework chrome?" |
| Source uses sub-floor fonts (17-23 px) | "Snap to 24 — spec wins" | "Source uses sub-floor body text (e.g. 17/19/23 px). Snapping to spec (R06) inflates heights → overflow. Three options: keep source (sub-spec), snap (overflow), or refuse (have source redesign)." |
| Source font-family doesn't match framework | Silent swap to `var(--fs-font-cjk)` | "Framework's primary font (方正兰亭黑) has wider CJK metrics than source's PingFang → ~70px cumulative downward shift. Keep source font-family, or swap?" |
| Foreign HTML has 8 minor R12 violations | "Drop them all silently" | (this one IS mechanical — R12 is a hard framework rule, no judgment needed; drop silently is OK) |
| Overflow detected after render | Silent margin-trim heuristic | "Tagline overflows 40px. Options: ask source to trim content / try `--keep-source-typography` / let me auto-shrink margins (specify which)" |

**How to apply when uncertain**: if you find yourself writing a comment
like "for source X we'll do Y as a workaround" — that's a trade-off,
ask first. If you're snapping `X → Y` purely because spec says Y is the
floor — that's mechanical, do it silently.

### Why this exists (lesson from a 10+ round conversation, 2026-05-28)

User had a foreign HTML built elsewhere, asked to "use feishu template".
Across 10+ rounds the agent burned ~3 hours on:

1. **Iter 1-3**: misunderstood "用模板" as either "换皮" (just colors) or
   "重画 pattern" (use Two-hand-arch). Right answer: chrome + shell, no
   pattern. **Lesson** → MODE SELECTION table now lists trigger phrases.
2. **Iter 4-5**: silently picked "letterbox 1280×720" then "scale-wrap"
   then "scale-canvas" — all bad. **Lesson** → PRECONDITION fails fast
   at 1920×1080 mismatch (exit 3 with actionable error).
3. **Iter 6**: framework `.header` chrome displaced source content
   downward → 1920×1080 native source overflowed. **Lesson** → Mode 2
   `extract_to_header=False` skips framework header wrap.
4. **Iter 7-8**: font-family swap caused ~70px cumulative shift; font-size
   snap inflated heights to overflow. **Lesson** → Mode 2 captures source
   font + native mode does spec snap with overflow check.
5. **Iter 9**: thin borders top/bottom of slide. **Lesson** → strip
   border/box-shadow from source `.slide` (standalone-only chrome).
6. **Iter 10**: gray muted text mapped to `--fs-violet`. **Lesson** →
   palette skip grayscale-ish (`max(R,G,B) - min(R,G,B) < 60`).
7. **Meta**: at every iteration the agent made silent trade-offs the
   user later rejected. **Lesson** → META-RULE above. Always ask.

**Root cause of the original problem**: "用模板" has 3 layers (chrome /
shell / pattern). The user wanted chrome + shell, NOT pattern. RESKIN
MODE makes this the default. The follow-on bugs were all silent
trade-off decisions cascading.

---


## Re-render UI mocks as HTML, not screenshots

When adapting source content into HTML — especially when "translating" or
"re-rendering" an existing deck, slide, or marketing screenshot — **system
UI, app screens, chat threads, dashboards, spreadsheets, browser windows,
and modal dialogs MUST be recreated in HTML/CSS, not embedded as raster
images.**

### Why

| Aspect | Raster screenshot | HTML mock |
|---|---|---|
| Fullscreen scaling | Pixelates above 1× | Crisp at any res |
| Typography | Whatever the screenshot has | Brand font (`var(--fs-font-cjk)`) |
| Color harmony | Off-brand by definition | Uses `--fs-blue` etc. |
| File size | 200–800 KB JPG/PNG | 1–4 KB inline HTML |
| Inspectable | Black box | DOM, accessible |
| Licensing | Real product UI = NDA risk | Stylized recreation, safe |
| "Looks more real" | Looks pasted-in | Looks native to the deck |

### What still belongs as a raster image

- Real photographs (customer scenes, hardware shots, factory floors) →
  use `data-decor="photo-bg"` with `style="--photo: url(...)"`.
- Brand assets (the 飞书 tri-petal logo, the slogan PNG) — already inlined.
- Illustrative artwork that's genuinely artistic (the master flower image).

If it's a UI element — re-render. If it's a photograph or art — inline.

### `.data-panel` vs `.ui-window` — pick the right container

Two ways to frame structured data on a slide. They look superficially
similar, but the visual associations are very different and the rule
for picking is strict:

| Container | When to use | Visual signal |
|---|---|---|
| **`.data-panel`** (default) | You're showing structured data — status rows, KPI summaries, value-translation tables, agent step lists, "下一步" callouts. The data isn't part of any app's UI; you just need a brand-aligned framing. | Side accent bar (4 px blue / teal / violet) + clean header + gradient keyline. NO traffic lights. NO window chrome. |
| **`.ui-window` + `.ui-traffic-lights`** | You're actually mocking a macOS desktop app (real screenshot replacement). The traffic lights tell the viewer "this is a software window." | Three colored dots (red/yellow/green) + titlebar + window-style framing. |

**Default to `.data-panel`.** Reach for `.ui-window` only when the
content WOULD HAVE BEEN a screenshot of a real app — chat thread,
browser dashboard, spreadsheet panel, modal dialog. If the same
content could legitimately appear as a "report module" without app
chrome, it's a `.data-panel`.

`.data-panel` markup pattern:

```html
<div class="data-panel">                  <!-- or .data-panel.is-teal / .is-violet -->
  <h4>客户类型 · 共创进入条件</h4>
  <hr>
  <div class="row">
    <span class="lbl">先进型 · 流程已成熟</span>
    <span class="val">学过来 → 教别人</span>     <!-- default: teal -->
  </div>
  <div class="row">
    <span class="lbl">中间型 · R&amp;D VP 接洽</span>
    <span class="val warn">权限不够 → 暂缓</span>  <!-- .warn = orange -->
  </div>
  <div class="ui-alert">                   <!-- .ui-alert reuses fine inside .data-panel -->
    <div class="t">下一步</div>
    <h5>古茗 / 瑞幸先进流程调研</h5>
    <p>凯轩节后跟进。</p>
  </div>
</div>
```

Tonal variants (`.is-teal` / `.is-violet`) recolor the side accent bar
and the row arrows for differentiation when multiple panels coexist on
a slide (e.g. content-2col with two side-by-side panels).

### UI primitives shipped in the CSS

The `feishu-deck.css` ships a set of `.ui-*` primitive classes that compose
into any 飞书-style app mock. All are dark-themed, brand-aware, and built
from the existing tokens. None of them require additional assets.

| Primitive             | Renders                                          |
|-----------------------|--------------------------------------------------|
| **`.data-panel`**     | **Default** brand-aligned container for structured data — side accent + keyline, no window chrome. Tonal variants `.is-teal` / `.is-violet`. **Use this for non-app data;** `.ui-window` only for actual macOS app UI mocks. |
| `.ui-window`          | Generic dark app panel + 16 px radius + soft shadow — for app UI mocks |
| `.ui-titlebar`        | Top bar inside `.ui-window`                       |
| `.ui-traffic-lights`  | macOS-style red/yellow/green dots — only inside real app mocks |
| `.ui-browser`         | `.ui-window` variant w/ a URL pill in titlebar   |
| `.ui-urlbar`          | Pill-shaped URL display                          |
| `.ui-body`            | Flex container holding `.ui-sidebar` + `.ui-main`|
| `.ui-sidebar`         | 260 px left vertical navigation                   |
| `.ui-main`            | Right-side content column                         |
| `.ui-toolbar`         | Horizontal toolbar with tabs / buttons            |
| `.ui-tab-bar` / `.ui-tab` | Tabs (`.is-active` for selected)              |
| `.ui-list` / `.ui-list-item` | Chat list / contact list / file list rows  |
| `.ui-list-item .ui-line .name / .preview` | Two-line list row text       |
| `.ui-list-item .ui-meta` | Right-side timestamp / count                  |
| `.ui-avatar`          | Round avatar with initial (`data-tone="teal\|purple\|orange"`) |
| `.ui-msg`             | Chat bubble (`.is-self` blue right / `.is-other` ghost left) |
| `.ui-msg-stack`       | Vertical stack of `.ui-msg`                       |
| `.ui-input`           | Form text input                                   |
| `.ui-btn`             | Button (`.is-primary` / `.is-secondary` / `.is-ghost`) |
| `.ui-grid` / `.ui-cell` | Spreadsheet / 多维表格 cells (`.is-header` for thead) |
| `.ui-cell .ui-pill`   | Inline tag inside a cell (`data-tone=...`)        |
| `.ui-status-dot`      | 8 px status dot (`.is-online / .is-busy / .is-offline`) |
| `.ui-badge`           | Numeric notification badge (`.is-mute` for grey)  |
| `.ui-progress`        | 4 px progress bar; set `style="--ui-progress: 76%"`|

### Example: recreating a 飞书 messenger window

```html
<div class="col-visual">
  <div class="ui-window">
    <div class="ui-titlebar">
      <span class="ui-traffic-lights"><i></i></span>
      <span>飞书 · 销售战区</span>
    </div>
    <div class="ui-body">
      <aside class="ui-sidebar">
        <div class="ui-section">置顶会话</div>
        <div class="ui-list">
          <div class="ui-list-item is-selected">
            <span class="ui-avatar" data-tone="teal">A</span>
            <span class="ui-line">
              <span class="name">A 公司 · 战区群</span>
              <span class="preview">王总：方案已确认,周一开评审会</span>
            </span>
            <span class="ui-meta">2 分钟前</span>
          </div>
          <div class="ui-list-item">
            <span class="ui-avatar" data-tone="purple">B</span>
            <span class="ui-line">
              <span class="name">B 银行 · 商务对接</span>
              <span class="preview">合同条款已发您查收</span>
            </span>
            <span class="ui-meta">12:48</span>
          </div>
        </div>
      </aside>
      <main class="ui-main">
        <div class="ui-toolbar">
          <div class="ui-tab-bar">
            <span class="ui-tab is-active">消息</span>
            <span class="ui-tab">文件</span>
            <span class="ui-tab">日程</span>
          </div>
        </div>
        <div class="ui-msg-stack">
          <div class="ui-msg is-other">王总,本季度推进的方案版本已经在 Wiki。</div>
          <div class="ui-msg is-self">收到。我看完后下午给你反馈。</div>
          <div class="ui-msg is-other">好的,有问题随时@我。</div>
        </div>
      </main>
    </div>
  </div>
</div>
```

### Example: recreating a Lark Base 多维表格

```html
<div class="ui-window">
  <div class="ui-titlebar">
    <span class="ui-traffic-lights"><i></i></span>
    <span>销售跟单 · 飞书多维表格</span>
  </div>
  <div class="ui-grid" style="grid-template-columns: 200px 120px 100px 140px">
    <div class="ui-cell is-header">客户</div>
    <div class="ui-cell is-header">阶段</div>
    <div class="ui-cell is-header">金额</div>
    <div class="ui-cell is-header">负责人</div>

    <div class="ui-cell">A 公司</div>
    <div class="ui-cell"><span class="ui-pill" data-tone="teal">已签约</span></div>
    <div class="ui-cell">¥ 3.2M</div>
    <div class="ui-cell">王雪</div>

    <div class="ui-cell">B 银行</div>
    <div class="ui-cell"><span class="ui-pill" data-tone="blue">谈判中</span></div>
    <div class="ui-cell">¥ 4.6M</div>
    <div class="ui-cell">张伟</div>

    <div class="ui-cell">C 集团</div>
    <div class="ui-cell"><span class="ui-pill" data-tone="purple">商机</span></div>
    <div class="ui-cell">¥ 2.4M</div>
    <div class="ui-cell">李娜</div>
  </div>
</div>
```

### Example: recreating a browser-based dashboard

```html
<div class="ui-window ui-browser">
  <div class="ui-titlebar">
    <span class="ui-traffic-lights"><i></i></span>
    <span class="ui-urlbar">larksuite.com / dashboard / 战区周报</span>
  </div>
  <div class="ui-main" style="padding: 32px">
    <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap: 18px">
      <div class="card"><h3 class="ctitle">已读率</h3><div class="num">98%</div></div>
      <div class="card"><h3 class="ctitle">触达时延</h3><div class="num">3 秒</div></div>
      <div class="card"><h3 class="ctitle">ROI</h3><div class="num">3.2×</div></div>
    </div>
  </div>
</div>
```

### Validator behavior

`assets/validate.py` includes `audit_ui_mocks_are_html` (rule **UI1**).
It scans every slide for `<img src="…">` tags. The validator allows:
- `data:` URIs (inlined assets)
- The known brand asset filenames (`lark-logo`, `lark-slogan`,
  `lark-cover-bg`, etc.)

Anything else triggers a **warning** suggesting the `<img>` is a UI
screenshot that should be re-rendered using the `.ui-*` primitives.
In `--strict` mode this becomes an **error**. Pure photographs go through
`data-decor="photo-bg"` with `style="--photo: url(…)"`, not via raw `<img>`.

### Going-forward expectation for the agent

When asked to "translate this slide / deck / page into HTML":
1. Identify which visual elements are SYSTEM UI vs. real photographs.
2. For each UI element, pick the closest `.ui-*` primitive composition.
3. Recreate the UI in HTML/CSS using brand tokens — fonts, colors, radii.
4. Only reach for raster `<img>` when the source is a genuine photograph
   or a piece of artwork.
5. If unsure ("is this a UI screenshot or a marketing illustration?"),
   ask. The default answer is "treat it as UI and re-render".

A deck where every UI element is HTML feels native. A deck with pasted
screenshots feels like a draft.

---


## Preserve atmospheric / decorative backgrounds when re-rendering

When re-rendering an existing slide into a standard layout, **never silently drop
the slide's distinctive background imagery, decorative gradients, or atmospheric
overlays**. Those visuals carry tone information that the layout structure alone
cannot express — stripping them makes the redesign feel sterile and the user
notices immediately.

### What counts as "atmospheric"
- Radial decorative glows (e.g. the violet magnolia glow lower-right on
  Digital Workforce slides)
- Full-bleed photographic backgrounds beyond the cover (e.g. customer scene
  photos on `image-text` layouts)
- Brand gradients other than the default `--fs-grad-hero`
- Aurora / particle / film-grain overlays
- Hand-drawn illustrative motifs

### How to preserve them — `data-decor` attribute

Decoration is **orthogonal to layout**. A slide can carry any combination of
layout + variant + decor. Mark the decoration with a `data-decor` attribute
on the `.slide` element:

```html
<!-- Preserve the violet magnolia glow when re-rendering Digital Workforce
     into the standard 3-up content layout — layout is unchanged, atmosphere stays -->
<div class="slide"
     data-layout="content-3up"
     data-decor="violet-glow"
     data-screen-label="07 数字员工">
  ...
</div>

<!-- Stack multiple decors with space separation: cinematic mix + grain -->
<div class="slide"
     data-layout="quote"
     data-decor="mix-glow grain"
     data-screen-label="06 Quote">
  ...
</div>

<!-- Custom photographic background for an image-text style customer page -->
<div class="slide"
     data-layout="image-text"
     data-decor="photo-bg"
     style="--photo: url('./photos/store-floor.jpg')"
     data-screen-label="09 Customer">
  ...
</div>
```

### Available decor tokens (CSS already ships these)

| Token          | Renders                                      | Use for |
|----------------|----------------------------------------------|---|
| `violet-glow`  | Lower-right violet bloom (#9F6FF1 + #5C3FFB) | Digital Workforce / 数字员工 / AI signature |
| `blue-glow`    | Centered blue radial (#3C7FFF)               | Quote / hero / single-focus emphasis |
| `mix-glow`     | Purple top-right + blue bottom-left          | Closing / cinematic transitions |
| `teal-glow`    | Bottom-left teal bloom (#33D6C0)             | Data / KPI / impact pages |
| `orange-spark` | Top-right warm flare (#FE7F00)               | Alert / 例外 / risk callout |
| `aurora`       | Three-color ambient (blue + violet + teal)   | Generic ambient atmosphere |
| `grain`        | Subtle film grain (CSS noise, no asset)      | Cinematic finish — pairs with any glow |
| `topo`         | Faint topographic line motif                 | Process / engineering / pipeline pages |
| `flower-bg`    | Full-bleed master flower (`--fs-asset-cover-bg`) | Carries the cover atmosphere into a content page |
| `section-bg`   | Master section gradient (`--fs-asset-section-bg`) | Color-rich chapter pages outside `section` layout |
| `photo-bg`     | Custom URL via `style="--photo: url(...)"`   | Any photographic full-bleed beyond the master assets |

### Architecture rules
1. **Decor is a `::before` (and grain a `::after`) pseudo-element.** It sits
   under all slide content (`z-index: 0`) with `pointer-events: none`. It
   never disturbs layout or hit-testing.
2. **Decor is always opt-in.** Default slides have no `data-decor` and render
   exactly as they used to. Adding decor never changes the layout.
3. **Decor stacks via space-separated tokens.** `data-decor="violet-glow grain"`
   composes the violet bloom and the grain overlay.
4. **`flower-bg` and `photo-bg` automatically add a darkening protection
   gradient** when applied to a non-cover layout, so text remains legible
   over imagery. Cover and end layouts already carry their own contrast
   strategy and skip the auto-overlay.
5. **When re-rendering an existing deck**, audit each source slide for
   atmospheric content and translate it to the matching token. If no token
   matches the source decor exactly, use the closest one and note the
   approximation — never silently drop it.

---

