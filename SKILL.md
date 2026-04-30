---
name: feishu-deck-h5
description: |
  Use this skill whenever the user asks for a Feishu/Lark-style slide deck rendered as a single
  HTML file (NOT a real .pptx). Triggers: "飞书风格 PPT", "Lark deck", "汇报材料", "客户提案",
  "h5 deck", "presentation html", "16:9 网页演示", "用 html 模仿 ppt", "深色商务汇报",
  or whenever the user attaches the 飞书 .thmx master and asks for an HTML version. The skill
  produces a dark, cinematic, bilingual (ZH primary / EN secondary) deck at 1920×1080 design
  canvas with auto-responsive scale-to-fit, plus a built-in mobile vertical browse mode in the
  same file. Outputs look indistinguishable from a hand-built Lark sales deck. Do NOT use this
  skill when the user actually wants a real PowerPoint (.pptx) file — that's the pptx skill.
---

# feishu-deck-h5

> **🛑 STOP — read this preflight before doing anything else.**

## PREFLIGHT (mandatory, blocks all work) — local mount required

This skill is **ONLY valid in local-mount mode**. If the user has not
mounted a writable local folder, the skill MUST refuse to proceed and
must NOT write anything to ephemeral session storage.

### Why this is mandatory

Decks generated in temporary session storage (`/sessions/.../mnt/outputs/`)
are **wiped between conversations**. Without a local mount:

- The user loses the deck the moment the conversation ends.
- Brand assets (`lark-*.png/jpg`) can't be reused across decks.
- Multiple people on the same team can't collaborate or version-control.
- The user can't `git commit` what they generated.
- The generated HTML can't be opened in the user's own browser via
  `file://` because the session is sandboxed.

The skill is designed for persistent, team-shareable, version-controlled
decks. Running without a mount defeats every reason this skill exists.

### Required preflight steps (run IN ORDER)

**Step P-1.** Check `<env>` in your system context for the line
`User selected a folder: yes/no`.
- If `yes` → continue to Step P-2.
- If `no` → go to Step P-3 (request mount).

**Step P-2.** Verify the mount is writable by running:

```bash
bash assets/preflight.sh
```

The script exits 0 on success. Exit codes 1 / 2 / 3 mean: no mount /
read-only / running from ephemeral output. Any non-zero exit blocks
all subsequent work.

**Step P-3.** Call `mcp__cowork__request_cowork_directory` and ask the
user to select their project folder. Phrase the request like:

> "I need to mount your local working directory before generating a
> deck — outputs need to persist beyond this session and be available
> in your editor / browser. Please select the folder where you want
> the deck files to live (e.g. `~/Projects/2026-customer-deck/`)."

**Step P-4.** If the user declines or the mount call fails or P-2 still
fails after P-3, STOP and reply with this exact message:

> "feishu-deck-h5 requires a local mounted folder so generated decks
> persist beyond this conversation, can be opened in your browser, and
> can be version-controlled. I can't proceed without one. Please select
> a working directory and ask me again, or use a different tool that
> doesn't require local persistence."

**Do NOT** generate any HTML in `/sessions/*/mnt/outputs/`. **Do NOT**
hand-wave with "I'll generate it temporarily". **Do NOT** offer to
inline everything into a single message. The skill is gated; honor the
gate.

### What "local mount" looks like in practice

| State | Filesystem indicator | Action |
|---|---|---|
| User cloned the repo + mounted | `~/Projects/feishu-deck-h5/` mounted; SKILL.md visible | OK, proceed |
| User mounted a parent project folder | `~/Projects/q1-pitch/` mounted; cloned skill in subfolder OR via plugin install | OK, proceed |
| User mounted a fresh empty folder | Mounted but no skill files yet | Copy skill files into the mount first (`git clone` or copy from `~/.claude/skills/`), then proceed |
| User has not mounted anything | `User selected a folder: no` in env | Request mount, refuse if declined |
| Working in `/sessions/*/mnt/outputs/` only | `preflight.sh` returns exit 3 | Treat as no-mount, refuse |

The skill treats "ephemeral outputs only" the same as "no mount" — both
are non-persistent and equally broken for this skill's purpose.

---

## WORKSPACE LAYOUT (mandatory) — per-run `runs/<timestamp>/` folder

After PREFLIGHT passes, but **before generating any HTML**, the agent
MUST create a fresh per-run workspace and announce it to the user.
This is a non-negotiable convention so that:

- multiple deck attempts in the same project don't overwrite each other
- the user's source materials and the agent's outputs stay separated
- every run is timestamped and easy to find / archive / git-commit later

### Required structure

```
runs/
└── YYYYMMDD-HHMMSS/        ← one folder per skill invocation, timestamp to the second
    ├── input/              ← USER drops source files here (PDFs, images, briefs, refs, .thmx, etc.)
    └── output/             ← AGENT writes the deck HTML, validate reports, intermediate artifacts here
```

### Required steps (run IN ORDER, after PREFLIGHT)

**Step W-1.** Create the run folder:

```bash
bash assets/new-run.sh
```

The script prints the absolute path of the new run folder and exits 0.
Capture the printed path; it is the working folder for everything below.

**Step W-2.** Announce the path to the user **in the same response**.
Use roughly this phrasing (translate to the user's language):

> "已为本次任务创建工作目录：
> `runs/<timestamp>/`
> · 请把素材（图片、PDF、参考稿、文案等）放到 `input/`
> · 我会把生成的 HTML deck 和验证报告写到 `output/`
> 准备好后告诉我即可继续。"

**Step W-3.** Wait for the user to drop files into `input/` (or to
confirm there are no source files — text-only briefs are fine, the
folder still exists for the deck to land in `output/`).

**Step W-4.** All subsequent file writes for this invocation MUST go
under `runs/<timestamp>/output/`. Never write the deck to
`examples/`, the repo root, or any other location. `examples/` is
reserved for the maintainers' reference sample.

### When NOT to create a new run folder

- The user explicitly says "edit the existing deck at `runs/.../output/X.html`"
  — in that case, reuse that run folder, don't create a new one.
- You are running `build.sh` to regenerate `examples/sample-deck.html`
  as a maintainer of this skill (not as an end-user delivery). `build.sh`
  is intentionally hardcoded to `examples/` and is out of scope for this
  rule.

---

Generate a dark, cinematic Lark / 飞书 brand-aligned **HTML deck** at 1920×1080 in a single
self-contained file that:

- looks identical on PC at 16:9 fullscreen,
- gracefully reflows to a vertical browse on mobile,
- never invents tokens — pulls every color, font size, gradient, radius, and spacing
  from `assets/feishu-deck.css`,
- ships with a built-in present mode (←/→/space, click-to-go), a scroll mode (mobile),
  a mode toggle, page indicator, and URL hash sync.

This skill is the **canonical interpretation** of the 飞书母版 2025 (深色通用) PowerPoint
master, expressed as design tokens and layout recipes.

---

## When to use this skill

Use it when the user wants:
- a slide deck delivered as an HTML file (not a `.pptx`)
- something that *looks like* a Lark / 飞书 / ByteDance enterprise pitch
- a dark, bilingual ZH+EN sales / quarterly / customer-pitch presentation
- both PC fullscreen and mobile-viewable in one artifact

If the user explicitly asks for `.pptx`, route to the **pptx** skill instead.

If the user asks for a generic non-Feishu deck (e.g. white background, Apple style),
this skill is the wrong choice — its design tokens are brand-locked.

---

## Files in this skill

```
feishu-deck-h5/
├── SKILL.md                    ← you are here
├── DESIGN.md                   ← 9-section design system spec (awesome-design-md format)
├── assets/
│   ├── feishu-deck.css         ← all design tokens + 13 slide layouts (single source of truth)
│   ├── feishu-deck.js          ← scale-to-fit + present/scroll modes + keyboard nav
│   ├── lark-logo.png           ← color logo (petals + 飞书) for cover/end. From master image3.png
│   ├── lark-logo-mono-white.png← mono-white variant for content/section pages
│   ├── lark-cover-bg.jpg       ← flower-on-dark master background. From master image2.jpg
│   ├── lark-section-bg.jpg     ← cool blue glow on right (chapter pages). From master image4.jpg
│   ├── lark-content-bg.jpg     ← subtle dark gradient (content pages). From master image1.jpg
│   └── lark-slogan.png         ← "先进团队 先用飞书" slogan PNG. From master image6.png
├── templates/
│   ├── _shell.html             ← the empty single-file deck skeleton (head + 1 sample slide)
│   └── slide-recipes.html      ← every layout shown in one reference deck (copy the markup you need)
├── examples/
│   └── sample-deck.html        ← a polished 12-slide demo deck (for reference + visual check)
└── preview-dark.html           ← token swatches + type scale + component gallery
```

### Brand assets — must travel with every deck

Every deck depends on these six image files, which were lifted directly from the
official **飞书 母版 2025（深色通用）** PowerPoint master. They live in `assets/` and are
referenced via CSS variables (`--fs-asset-logo` etc.). For single-file delivery, base64-
inline them into a `:root { --fs-asset-… }` override block — see how
`examples/sample-deck.html` does it.

| Variable                | Default file                  | Source (from .thmx)         | Used by             |
|-------------------------|-------------------------------|-----------------------------|---------------------|
| `--fs-asset-logo`       | `lark-logo.png`               | `theme/media/image3.png`    | cover, end (top-left, color) |
| `--fs-asset-logo-mono`  | `lark-logo-mono-white.png`    | recolored from image3.png   | section + every content page (top-right, mono) |
| `--fs-asset-cover-bg`   | `lark-cover-bg.jpg`           | `theme/media/image2.jpg`    | cover, end backgrounds |
| `--fs-asset-section-bg` | `lark-section-bg.jpg`         | `theme/media/image4.jpg`    | section divider |
| `--fs-asset-content-bg` | `lark-content-bg.jpg`         | `theme/media/image1.jpg`    | content / agenda / stats / table / etc |
| `--fs-asset-slogan`     | `lark-slogan.png`             | `theme/media/image6.png`    | end / 封底带 slogan |

---

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

| Element | Spec |
|---|---|
| Background | `lark-cover-bg.jpg` (the master flower image — NOT a solid color, NOT a gradient invented on the fly) |
| Logo | top-LEFT at (120, 113), size 235×74, **COLORED** tri-petal `--fs-asset-logo` |
| Title | left-half only (max-width 884px), 100/700, can be 1-2 lines (hero allowed `<br>`) |
| Subtitle | 40/600 white below title |
| Author block | bottom-left at top:803, with `.role` muted prefix + main text |
| Footer chrome | NONE (cover doesn't have a footer row) |
| Eyebrow | NONE |

```html
<div class="slide" data-layout="cover" data-screen-label="01 Cover">
  <div class="wordmark">飞书</div>
  <div class="stage">
    <h1 class="title title-zh">〔Source title — can wrap with &lt;br&gt;〕</h1>
    <p class="subtitle">〔Source EN subtitle, or translated〕</p>
  </div>
  <div class="author">
    <span class="role">〔议题类型 · 日期〕</span>〔团队 / 公司〕
  </div>
</div>
```

### Step 3 · Every content page — title-only header + colored top-right logo

```html
<div class="slide" data-layout="content-3up" data-screen-label="04 Content">
  <div class="wordmark">飞书</div>           ← top-RIGHT, COLORED, 160×50 (auto from CSS)
  <div class="header">
    <h2 class="title-zh">〔Source title — single line, no &lt;br&gt;〕</h2>
  </div>
  <!-- body content (.grid / .flow / .nodes / .table-wrap / etc.) -->
  <div class="footer"><span>〔brand line · client name〕</span><span class="pageno">04</span></div>
</div>
```

What you MUST drop from the source:
- Eyebrow / kicker text above the title (R56)
- Subtitle / lead text below the title
- Inline page numbers in the header (footer only)
- Source page numbers in any other position
- Decorative breadcrumbs / "you are here" indicators
- Watermarks
- `<br>` inside the title — shorten the title instead (R13)
- Emoji, `!`, `…`, `???` — strip without asking (R05)

What you MUST preserve:
- Atmospheric backgrounds via `data-decor` (e.g. violet-glow on Digital
  Workforce / AI pages — see "Preserve atmospheric / decorative
  backgrounds when re-rendering")
- System UI / app screenshots → recreate as HTML using `.ui-*` primitives,
  NOT as raster images (UI1)
- Photographic backgrounds → use `data-decor="photo-bg"` with `style="--photo: url(...)"`

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
bash build.sh --inline
python3 assets/validate.py examples/sample-deck.html --strict
python3 assets/validate.py examples/sample-deck-inline.html --strict
```

All four must exit 0. If any check fails (R49 cyan-as-accent, L1 mono
logo, R13 br-in-title, R56 eyebrow-in-header, P50 base64 budget),
**fix the markup, don't suppress the check**.

### Common conversion mistakes (forbidden)

| Mistake | Why it's wrong | What to do instead |
|---|---|---|
| Use `data-layout="cover"` for an internal "agenda" or "section" page | Cover layout has the flower background and left-half text positioning that doesn't suit an agenda | Use `agenda` or `section` |
| Use mono-white logo on content pages | Mono is opt-in for over-imagery edge cases only (L1) | Use the default colored logo |
| Multi-line `<h2>` on content pages with `<br>` | Forbidden by R13 | Shorten the title; if it really needs two lines, the source title is too long for a deck |
| Add eyebrow above content page title | Forbidden by R56 | Drop the eyebrow; if context is essential, put it in the footer brand line |
| Re-use source page numbers verbatim in the title area | Page no. lives in the footer only | Add `<span class="pageno">07</span>` inside the footer |
| Inline raster screenshots of 飞书 UI as `<img>` | Forbidden by UI1 | Recreate using `.ui-window / .ui-grid / .ui-list / .ui-msg` etc. |
| Use cyan as a slide accent | Forbidden by R49 (cyan = inline highlight only) | Pick blue / teal / purple / violet / orange instead |

---

## Operational notes (gotchas)

- **`templates/_shell.html` uses `../assets/feishu-deck.css`.** It assumes the
  shell stays one directory deep relative to `assets/`. If you `cp` it to a
  new working directory, fix the relative paths to point at the actual
  `assets/` location, or run `bash build.sh` from the skill root which
  handles the rewrite automatically.
- **`data-decor="flower-bg"` and `"photo-bg"` use `!important` to override
  layout backgrounds.** They REPLACE the layout's default background image —
  intentional, so you can carry the cover atmosphere onto a content page.
  The auto-darkening protection gradient is added on non-cover/non-end
  layouts only (cover and end have their own contrast strategies).
- **CSS rule `.deck[data-mode="scroll"] ~ .deck-ui` relies on `.deck-ui`
  being a later sibling of `.deck`.** `feishu-deck.js` always appends the
  UI to `document.body` so this holds, but if you wrap `.deck` in a parent
  container or insert nodes between `.deck` and `.deck-ui`, the sibling
  selector breaks. The JS belt-and-suspenders `display: none` keeps it
  working in practice — but if you embed the deck inside a custom shell,
  prefer toggling `body.is-scroll` instead.

---

## Quick start (recommended workflow)

1. **Read DESIGN.md** end-to-end. Token names matter — the LLM that generates the deck
   must reference `--fs-*` variables, not hex values.
2. **Open `examples/sample-deck.html` in a browser** to confirm the rendering pipeline
   works on the user's machine. This is the visual ground truth.
3. **Open `templates/_shell.html`**. Copy it to the user's working directory, rename
   to whatever the project is (e.g. `2026-Q1-customer-deck.html`).
4. **Author the slide order**. Sketch the deck arc first, then for each slide:
   - pick a layout from the table below
   - copy the corresponding markup block from `templates/slide-recipes.html`
   - drop it into the shell, fill the placeholders, set `data-screen-label`,
     and increment the footer page number.
5. **Run the self-check** (final section of this file).
6. **Deliver as one HTML file**. Inline the CSS + JS for portability if the user
   wants a single attachment (see "Single-file inlined output" below).

---

## Available layouts

Pick by content, not by aesthetic. Each layout corresponds to a `data-layout` attribute
on `.slide`. Full markup lives in `templates/slide-recipes.html`.

| Layout            | Use when                                     | Accent default |
|-------------------|----------------------------------------------|---|
| `cover`           | First slide. Title + EN subtitle + brand + date. | blue |
| `agenda`          | TOC. 4–8 numbered items in 2 columns.        | blue |
| `section`         | Chapter divider. Giant `01` numeral + ZH title + EN lede + product pills. | blue |
| `content-3up`     | Three parallel pillars / capabilities / pillars. | blue |
| `content-2col`    | One narrative + supporting visual / mock / list. | blue |
| `quote`           | Single customer / executive quote, centered.  | blue |
| `stats`           | 4-up KPI row with big numbers as evidence.   | **teal** |
| `big-stat`        | One hero number (e.g. `30万`) + paragraph.    | blue |
| `image-text`      | Single full-bleed photo with type bottom-left. | blue |
| `table`           | Comparison or matrix. Up to 6 rows × 5 cols. | blue |
| `timeline`        | Chronological 4–6 milestones along an axis.  | blue |
| `process`         | 3–6 sequential steps with right-pointing arrows. | blue |
| `end`             | Closing — title + CTA pills + contact grid.  | blue |

**Mix rule.** A 12-slide deck typically uses 7–9 distinct layouts. Repeat `content-3up`
for parallel concepts; otherwise alternate to keep rhythm.

---

## The shell (single-file deck skeleton)

`templates/_shell.html` provides the canonical structure. Inline gist:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>〔Deck title〕 · Lark Suite</title>
  <link rel="stylesheet" href="assets/feishu-deck.css">
  <!-- Or inline the css for single-file delivery: see "Single-file inlined output" -->
</head>
<body>
  <div class="deck">
    <div class="slide-frame">
      <div class="slide" data-layout="cover" data-screen-label="01 Cover">
        ... cover markup ...
      </div>
    </div>
    <!-- more <div class="slide-frame"> entries -->
  </div>
  <script src="assets/feishu-deck.js"></script>
</body>
</html>
```

Do not change the DOM order: `.deck > .slide-frame > .slide`. The runtime relies on it.

---

## Layout recipes (canonical copy-paste markup)

Each recipe below is the exact markup the agent should drop into a `.slide-frame`.
The markup uses only tokens defined in `assets/feishu-deck.css`.

### 1. Cover (`data-layout="cover"`) — matches 飞书 母版 slideLayout1

The cover uses the master flower background (`lark-cover-bg.jpg`) with content positioned on the **left half** (the dark negative space). The color logo sits **top-left** at master coordinates. Title is **100 px / 700** (smaller than you'd expect — that's the master's spec). No eyebrow, no keyline bar, no footer chrome on the cover.

```html
<div class="slide" data-layout="cover" data-screen-label="01 Cover">
  <div class="wordmark">飞书</div>
  <div class="stage">
    <h1 class="title title-zh">先进团队的<br>工作方式</h1>
    <p class="subtitle">The way advanced teams work</p>
  </div>
  <div class="author">
    <span class="role">客户提案 · 2026.04</span>飞书企业服务团队
  </div>
</div>
```

Note: cover (and `image-text`, `end`) are HERO_TITLE_LAYOUTS — `<br>` is allowed
inside their titles. The validator (R13) skips `<br>` checking on these three.

Master pixel grid (1920×1080 design canvas):
- Logo top-left: `120, 113` size `235×74` (color logo with petals + 飞书 wordmark — `lark-logo.png`)
- Title: `124, 285`, max-width `884`, font 100/700
- Subtitle: directly below title, font 40/600 white
- Author block: `124, 803`, font 30/600 with optional `.role` muted prefix
- Right half: reserved for the flower image — DO NOT place text there.

### 2. Agenda (`data-layout="agenda"`)

```html
<div class="slide" data-layout="agenda" data-accent="blue" data-screen-label="02 Agenda">
  <div class="wordmark">Lark</div>
  <div class="header">
    <div class="eyebrow">AGENDA · 议程</div>
    <h2 class="title-zh" style="margin-top:18px">本次汇报<br>共六个部分</h2>
    <p class="en">Six chapters · approximately 35 minutes</p>
  </div>
  <div class="toc">
    <div class="item"><div class="n">01</div><div><div class="title-zh">背景与挑战</div><div class="title-en">Context and challenges</div></div></div>
    <div class="item"><div class="n">02</div><div><div class="title-zh">先进团队的工作方式</div><div class="title-en">How advanced teams work</div></div></div>
    <div class="item"><div class="n">03</div><div><div class="title-zh">飞书平台能力</div><div class="title-en">Lark platform capabilities</div></div></div>
    <div class="item"><div class="n">04</div><div><div class="title-zh">客户实证</div><div class="title-en">Customer evidence</div></div></div>
    <div class="item"><div class="n">05</div><div><div class="title-zh">部署与服务</div><div class="title-en">Rollout and service</div></div></div>
    <div class="item"><div class="n">06</div><div><div class="title-zh">下一步</div><div class="title-en">Next steps</div></div></div>
  </div>
  <div class="footer"><span>Lark Suite · 2026 客户提案</span><span class="pageno">02</span></div>
</div>
```

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
  <div class="footer"><span>飞书 · 2026 客户提案</span><span class="pageno">03</span></div>
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
    <div>
      <div class="eyebrow">CAPABILITIES · 三大能力</div>
      <h2 class="title-zh" style="margin-top:14px">先进团队的<br>三大工作方式</h2>
    </div>
    <div class="pageno">04 / 12</div>
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
  <div class="footer"><span>Lark Suite · 2026 客户提案</span><span class="pageno">04</span></div>
</div>
```

### 5. Content 2-col (`data-layout="content-2col"`)

```html
<div class="slide" data-layout="content-2col" data-accent="blue" data-screen-label="05 Content">
  <div class="wordmark">Lark</div>
  <div class="header">
    <div>
      <div class="eyebrow">PRODUCT · LARK BASE</div>
      <h2 class="title-zh" style="margin-top:14px">让流程在表格里运转</h2>
    </div>
    <div class="pageno">05 / 12</div>
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
  <div class="footer"><span>Lark Suite · 2026 客户提案</span><span class="pageno">05</span></div>
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
  <div class="footer"><span>Lark Suite · Customer Voice</span><span class="pageno">06</span></div>
</div>
```

### 7. Stats (`data-layout="stats"`, accent teal)

```html
<div class="slide" data-layout="stats" data-screen-label="07 Stats">
  <div class="wordmark">Lark</div>
  <div class="header">
    <div>
      <div class="eyebrow">BUSINESS IMPACT · 实测数据</div>
      <h2 class="title-zh" style="margin-top:14px">飞书带来的可量化结果</h2>
    </div>
    <div class="pageno">07 / 12</div>
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
  <div class="footer"><span>Lark Suite · 2026 客户提案</span><span class="pageno">07</span></div>
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
  <div class="footer"><span>Lark Suite · 2026 客户提案</span><span class="pageno">08</span></div>
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
  <div class="footer"><span>Lark Suite · 2026 客户提案</span><span class="pageno">09</span></div>
</div>
```

### 10. Table (`data-layout="table"`)

```html
<div class="slide" data-layout="table" data-accent="blue" data-screen-label="10 Table">
  <div class="wordmark">Lark</div>
  <div class="header">
    <div>
      <div class="eyebrow">COMPARISON · 平台对比</div>
      <h2 class="title-zh" style="margin-top:14px">飞书与传统办公套件</h2>
    </div>
    <div class="pageno">10 / 12</div>
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
  <div class="footer"><span>Lark Suite · 2026 客户提案</span><span class="pageno">10</span></div>
</div>
```

### 11. Timeline (`data-layout="timeline"`)

```html
<div class="slide" data-layout="timeline" data-accent="blue" data-screen-label="11 Timeline" style="--cols:4">
  <div class="wordmark">Lark</div>
  <div class="header">
    <div>
      <div class="eyebrow">ROADMAP · 部署节奏</div>
      <h2 class="title-zh" style="margin-top:14px">12 周落地路径</h2>
    </div>
    <div class="pageno">11 / 12</div>
  </div>
  <div class="nodes">
    <div class="node"><div class="when">W1-2</div><div class="what">需求蓝图</div><div class="desc">访谈 6 部门, 输出协同地图与目标 KPI。</div></div>
    <div class="node"><div class="when">W3-5</div><div class="what">关键流程上线</div><div class="desc">销售、HR、财务三条核心流在 Base 中先跑通。</div></div>
    <div class="node"><div class="when">W6-8</div><div class="what">全员推广</div><div class="desc">分层培训, 关键岗位 100% 接入, 数据搬迁完成。</div></div>
    <div class="node"><div class="when">W9-12</div><div class="what">数据复盘</div><div class="desc">复盘 KPI, 调整流程, 形成长期治理机制。</div></div>
  </div>
  <div class="axis"></div>
  <div class="footer"><span>Lark Suite · 2026 客户提案</span><span class="pageno">11</span></div>
</div>
```

### 12. Process (`data-layout="process"`)

```html
<div class="slide" data-layout="process" data-accent="blue" data-screen-label="12 Process" style="--cols:4">
  <div class="wordmark">Lark</div>
  <div class="header">
    <div>
      <div class="eyebrow">SERVICE · 协同闭环</div>
      <h2 class="title-zh" style="margin-top:14px">需求到交付,四步成型</h2>
    </div>
    <div class="pageno">12 / 12</div>
  </div>
  <div class="flow">
    <div class="step"><div class="stnum">01</div><h3>提出</h3><p>任意一线员工在 Messenger 发起,自动落入 Base 队列。</p></div>
    <div class="step"><div class="stnum">02</div><h3>对齐</h3><p>相关方在 Docs 留痕讨论,关键决策沉淀到 Wiki。</p></div>
    <div class="step"><div class="stnum">03</div><h3>交付</h3><p>负责人在 Base 中流转, 责任人 + 时间戳每一步可追溯。</p></div>
    <div class="step"><div class="stnum">04</div><h3>复盘</h3><p>会后 Meetings 自动生成纪要, 关键指标进入下个周期。</p></div>
  </div>
  <div class="footer"><span>Lark Suite · 2026 客户提案</span><span class="pageno">12</span></div>
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

## Iconography

- Use **Lucide-style inline SVG**, 24 px viewBox, `stroke: currentColor`, `stroke-width: 2`,
  `stroke-linecap: round`, `stroke-linejoin: round`, `fill: none`. Inherit color via the
  parent (`.tile` colors children to `--fs-accent` automatically).
- For production, recommend the user swap to **ByteDance IconPark** for licensing parity.
- **Never** use emoji or unicode glyphs (`✓ ✗ → 🚀`) as icons. Always real SVG.

A small library of go-to icons is included in the recipes above. When the LLM needs
a new icon, it should hand-write the SVG path rather than reference a remote URL.

---

## Single-file inlined output (recommended for delivery)

For a portable artifact, the agent should produce ONE `.html` file with CSS + JS inlined:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>...</title>
  <style>/* paste contents of assets/feishu-deck.css */</style>
</head>
<body>
  <div class="deck">
    <!-- slide-frame entries -->
  </div>
  <script>/* paste contents of assets/feishu-deck.js */</script>
</body>
</html>
```

The `examples/sample-deck.html` file is built this way and is the reference output.

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

---

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

### UI primitives shipped in the CSS

The `feishu-deck.css` ships a set of `.ui-*` primitive classes that compose
into any 飞书-style app mock. All are dark-themed, brand-aware, and built
from the existing tokens. None of them require additional assets.

| Primitive             | Renders                                          |
|-----------------------|--------------------------------------------------|
| `.ui-window`          | Generic dark app panel + 16 px radius + soft shadow |
| `.ui-titlebar`        | Top bar inside `.ui-window`                       |
| `.ui-traffic-lights`  | macOS-style red/yellow/green dots                |
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

## Self-check must be EXECUTED, not just listed

The 39-item self-check at the bottom of this file is a hard gate, not a
checklist for your reading pleasure. Before declaring a deck "done":

1. **Run a font-size audit programmatically.** Don't trust visual feel.

   ```bash
   python3 assets/validate.py path/to/your-deck.html
   # exit 0 = pass · exit 1 = fail · exit 2 = file not found
   ```

   The shipped `assets/validate.py` script statically audits the assembled
   HTML against every check that doesn't require a real browser:

   - **Structure** (R02 / R07): every `.slide` has `data-layout`,
     `data-screen-label`, `.wordmark`, and (non-cover/end) a `.footer`.
   - **One-line titles** (R13): no `<br>` inside `.header h2` /
     `.header h2.title-zh` / `.header h2.title` on layouts other than
     `cover` / `image-text` / `end`.
   - **Brand chrome** (R07): warns when `.wordmark.is-mono` is used —
     mono-white logo must be an explicit edge case, not the default.
   - **Banned punctuation** (R05): scans rendered text for emoji, `!`/`！`,
     ellipsis `…`/`...`, `???`/`？？？`.
   - **Font-size floor** (R06): every `font-size` declaration on a selector
     that targets slide content (NOT `.deck-ui`) must be ≥ 14 px. The script
     lists each violation with the offending selector and size.
   - **No drop shadows** (R12): scans `.slide` selectors for `box-shadow`
     declarations. Recognises glow rings (`0 0 0 Npx ...`) and `inset`
     shadows as allowed; flags any real drop shadow with non-zero offset.
   - **`data-decor` token validity** (R38): every token inside a slide's
     `data-decor` must come from the ship list (`violet-glow / blue-glow /
     mix-glow / teal-glow / orange-spark / aurora / grain / topo /
     flower-bg / section-bg / photo-bg`). Misspellings produce hard fail.
   - **Hex palette** (R10): warns when slide markup contains hex values
     outside the brand palette. (SVG decoration is excluded from this scan.)
   - **Runtime chrome** (R29-R32): verifies `.deck-progress`, `.deck-controls`,
     prev/next/fs buttons, `requestFullscreen`, `fullscreenchange`, the
     keyline-gradient progress bar, and `.is-idle` auto-fade are all wired.
   - **Centering pattern** (R36): asserts present-mode uses
     `margin: -540px 0 0 -960px` (absolute centering) and NOT `display: grid`
     on `.slide-frame`.
   - **Layout integrity** (L1 / L2 / L4): logo defaults to color, every
     short-content stage has `align-content: center` (or grow), `process`
     output panel attrs are single column.
   - **Default centering** (R48): every fixed-shape layout has centering on
     its inner container.
   - **Variant discipline** (R47): variants that change structural
     properties also redeclare `align-items` + `justify-content`.
   - **UI mocks as HTML** (UI1): warns on any `<img>` in slide content that
     isn't a known brand asset or `data:` URI.
   - **Cyan as slide-accent** (R49): rejects `data-accent="cyan"` on
     `.slide` — cyan is inline-word-highlight only.

   Pass `--strict` to promote warnings (mono logos, off-palette hex) into
   errors. Default mode lets warnings pass for an in-progress deck; strict
   mode is the pre-delivery gate.

2. **Treat exit-1 as a delivery blocker.** If the script reports any error,
   fix it. Don't paper over it by editing the validator. The check is
   conservative — every flag is a real规范 violation, not noise.

3. **Run the script after EVERY rebuild.** Each time you regenerate
   `examples/sample-deck.html` (or any deck), pipe through the validator
   in the same shell command:

   ```bash
   bash build.sh && python3 assets/validate.py examples/sample-deck.html || exit 1
   ```

   This makes regression detection automatic — a CSS edit that introduces
   a 12 px font in a `.slide *` selector will be caught immediately, not
   when a customer flags it on a printed handout.

4. **Items 14, 15, 20, 21 still require a human eye.** Visual alignment of
   the title baseline with the logo center, ZH > EN balance, atmospheric
   "feel", and density of glow vs content density — the validator can't
   judge these. Open the deck at 1920×1080, 1280×720, and 380×680 and
   look. Then ship.

The current `examples/sample-deck.html` passes `validate.py` with exit 0
in both default and `--strict` mode — that's the bar.

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

---

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

---

## Copy / numbering 规范

These are content rules — they affect what to *write*, not how to render it.

1. **Source footer on every content page.** Use `class="source-footer"` near
   the bottom-left: `数据来源：xxx · 内部口径`. Without this, the deck reads
   like marketing copy; with it, it reads like a board memo.
2. **Eyebrow numbering uses `01 / 02 / 03 / 04-A / 04-B / 04-C / …`** to
   express chapter+sub-page hierarchy. When a focus area expands across
   multiple pages, sub-letters are mandatory.
3. **CN ↔ EN separator:** ZH text + space + `·` + space + EN text.
   No em-dashes, no slashes, no parens.
4. **Single ACCENT4 (teal) emphasis per page.** The keyword-jump rule applies
   to *every* page, not just quote/金句. If two phrases compete for emphasis,
   pick one or step back to a neutral color.
5. **Match deck length to actual narrative arc.** A short pitch can stop on
   the last content slide — don't force a quote slide and a closing slogan if
   the story doesn't earn them. Use `end` only when there's a real "end".

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
| `source_footer(text)`            | Every content page footer line       | `.source-footer`       |
| `aurora_background()`            | Add `data-decor="aurora"` on `.slide`| `[data-decor~="aurora"]` |
| `fullscreen_button()`            | Already shipped in `.deck-ui`        | `.deck-controls .ctl.fs` (auto) |

Roadmap helpers (no CSS yet — write the markup by hand and follow the spec):
fork visualization, iron-4-corners, 6-step pipeline timeline, two-track
structure, 1+1 vs 1+1+N boundary tags.

---

## Performance budget (hard rules — enforced by `audit_perf`)

A 13-slide deck should be lean. The skill ships with a perf budget enforced
by `validate.py audit_perf`. Each rule has a CSS or JS fix; none of them
require an external dependency.

| ID  | Budget | Hard cap | Fix |
|-----|--------|----------|-----|
| P50 | base64 in `<style>` ≤ 100 KB (default delivery) | 250 KB error | Use `bash build.sh` (linked); single-file mode requires `<meta name="fs-deck-mode" content="inline">` |
| P51 | `backdrop-filter: blur(N)` ≤ 10 px | warn always | Drop blur radius or replace with opaque rgba |
| P52 | `new ResizeObserver()` count ≤ 1 | warn at 2+ | One document-level RO with rAF batching, iterate frames in callback |
| P53 | `addEventListener` count ≥ 8 must use `AbortController` | warn always | Wrap init in `new AbortController()` + pass `{ signal }` to every listener; expose `destroy()` |
| P54 | `.slide-frame` declares `contain: ...` | warn if missing | `.slide-frame { contain: layout paint size }` — local repaints |
| P55 | `.slide-frame .slide` declares `will-change: transform` | warn if missing | `.slide-frame .slide { will-change: transform }` + `transform: ... translateZ(0)` |

### Two delivery modes

| Mode | When | Output | base64 | Validator |
|---|---|---|---|---|
| **Linked (default)** | Internal use, hosted, repo deck | `examples/sample-deck.html` ≈ 24 KB + external `assets/*` | 0 KB | passes P50 |
| **Inlined (opt-in)**  | Email attachment, IM, "send-me-the-html" | `examples/sample-deck-inline.html` ≈ 360 KB | 250 KB | skips P50 (signaled by `<meta name="fs-deck-mode" content="inline">`) |

`bash build.sh` produces the linked version; `bash build.sh --inline` produces both.
The inlined HTML must include the `fs-deck-mode=inline` meta tag — `build.sh` adds it
automatically. Hand-built single-file decks must add it manually or get flagged P50.

---

## Content-page header — title only, no eyebrow, no sub-line

Per the 2026-04 reference deck (see attached screenshot in commit history),
the content-page header is intentionally minimal:

```html
<div class="header">
  <h2 class="title-zh">懂我的AI,可以代我做方案评审</h2>
</div>
```

That's it. **No eyebrow above. No subtitle below. No inner wrapper div.
No inline page number** (the page number lives in the footer).

The reasoning: a content slide already carries a card grid / table /
process flow / etc. as its main body. Stacking an eyebrow + title +
sub-line at the top creates visual hierarchy noise that competes with
the actual content for attention. The screenshot demonstrates exactly
this: a single white sans-serif title at top-left, the colored 飞书
logo at top-right on the same baseline, and the content below.

The CSS enforces this defensively:

```css
.slide .header .eyebrow { display: none; }
```

Even if someone copies the old eyebrow-included markup, the eyebrow
won't render. The `.eyebrow` class is still usable elsewhere (inside
cards, section dividers, stats columns, etc.) — it's only suppressed
when it sits inside a content-page `.header`.

The Hero layouts (`cover` / `image-text` / `end`) use their own `.stage`
container, not `.header`, so they're unaffected and keep their existing
title patterns.

---

## Self-check (run all 59 items before delivering)

Before saving the deck, walk this list. **Failing any item is a hard reject.**

```
Brand & content
[ ]  1. Each slide is wrapped in <div class="slide-frame"><div class="slide" ...>.
[ ]  2. Every .slide has data-layout AND data-screen-label set.
[ ]  3. Every .slide has exactly ONE accent (cyan = inline highlight only).
[ ]  4. ZH copy is bigger than EN copy and sits ABOVE it.
[ ]  5. No emoji. No '!', '…', '???'.
[ ]  6. Body text ≥ 22 px on canvas; chrome ≥ 14 px.
[ ]  7. Wordmark present on EVERY slide (cover/end top-left, others top-right) —
        always the COLORED logo unless class="is-mono" is explicitly set.
[ ]  8. Page numbers are zero-padded ('01') in the footer of non-cover/non-end slides.
[ ]  9. All icons are inline SVG with stroke:currentColor.
[ ] 10. All hex values come from --fs-* tokens.
[ ] 11. CJK punctuation full-width, EN punctuation ASCII, never mixed.
[ ] 12. No drop shadows on slide content (only on .slide-frame in scroll mode).

Title & header alignment
[ ] 13. Page-header H2 is ONE LINE. No <br> in .header h2 / .header .title-zh.
        Shorten the title; do NOT shrink the font. Hero 2-line titles only on
        cover and image-text layouts.
[ ] 14. Page-header H2 vertically aligned with the top-right logo (top: 61).
        Eyebrow (when used) goes BELOW the title.
[ ] 15. Title-only pages (cover, agenda, big-stat) have NO eyebrow above the
        title, so the title sits exactly on the logo line.

Layout-specific sizes
[ ] 16. Agenda numbers and item titles share the SAME font size (both 44 px).
[ ] 17. Stats .trend ≥ 20 px CJK 600 (NOT 14 px Latin uppercase).
[ ] 18. Stats .label ≥ 24 px CJK.
[ ] 19. Table <th> ≥ 24 px CJK 600 white (NOT 16 px Latin uppercase).
[ ] 20. Card titles fit on ≤ 14 CJK chars at default font size (no clash with
        right-corner numerals / verdict badges).

Copy & narrative
[ ] 21. Every content page that cites a number carries a .source-footer line
        ("数据来源：xxx · 内部口径"). Without it, the deck reads as marketing.
[ ] 22. Eyebrow numbering uses 01 / 02 / 03 / 04-A / 04-B / … sub-letters when
        a focus area expands across multiple pages.
[ ] 23. CN-EN separator inside titles/eyebrows is space + · + space.
[ ] 24. At most ONE accent4 (teal) emphasis per page — even on plain content.

Layout overflow & runtime
[ ] 25. No flex item lacks min-height: 0 inside .stage / .grid / .flow.
        No grid uses 1fr without minmax(0, 1fr) on its rows.
[ ] 26. Pill/CTA rows default to nowrap. Wrapping pill rows must declare it
        explicitly (and risk vertical overflow).
[ ] 27. iframe-embedded prototypes live in outputs/ with relative paths; every
        decorative overlay above an iframe has pointer-events: none.
[ ] 28. The deck opens correctly at viewport widths 1920, 1280, and 380.
        Page indicator + mode toggle + fullscreen button visible. Keyboard
        ←→ navigates; F toggles fullscreen.

Present-mode chrome (rendered automatically by feishu-deck.js — verify it shows)
[ ] 29. Top progress bar (3 px, --fs-grad-keyline) visible across the top of
        the viewport in present mode. Width = (cur+1)/total × 100%. Animated.
[ ] 30. Bottom-center pill bar shows: [prev] [01 / 12] [next] | [fullscreen].
        Glassmorphic background. Prev/next disabled at endpoints.
[ ] 31. Clicking 演示模式 ALSO requests browser fullscreen (one gesture).
        Clicking 退出演示 exits both. Esc exits fullscreen but stays in
        present mode (deliberate).
[ ] 32. Top progress bar + bottom control pill are HIDDEN in scroll mode.
        Esc, F-key, and ←/→ keyboard navigation work whether fullscreen or not.

Fullscreen scale & chrome
[ ] 33. Entering fullscreen does NOT clip slide content. Slide letterboxes
        (preserves 16:9) on non-16:9 displays. On true 16:9 displays, slide
        fills viewport exactly with scale = 1.
[ ] 34. After fullscreen transition the scale is correct on the FIRST frame
        (no flash of wrong size). Runtime double-rAFs + 120ms timeout for
        viewport settle.
[ ] 35. Chrome (top progress bar, mode toggle, bottom controls) auto-fades
        after 2.5s of no input in present mode and restores on any input.
        Hovering chrome cancels the fade.
[ ] 36. Slide centering uses absolute + negative margin pattern, NOT grid
        place-items, so transform/overflow clipping is deterministic.

Atmospheric / decorative preservation
[ ] 37. When re-rendering an existing slide into a standard layout, the source
        slide's distinctive atmospheric content (radial glows, full-bleed
        photos, brand gradients, aurora, film grain, illustrative motifs) is
        preserved via a data-decor attribute. NEVER silently dropped.
[ ] 38. data-decor tokens come from the ship list (violet-glow / blue-glow /
        mix-glow / teal-glow / orange-spark / aurora / grain / topo /
        flower-bg / section-bg / photo-bg). Multiple tokens stack via space
        separation. If the source decor doesn't match any token exactly, use
        the closest one and note the approximation.
[ ] 39. Decor never disturbs layout or hit-testing — it's a ::before/::after
        pseudo-element at z-index: 0 with pointer-events: none. Slide
        content stays at z-index: 1.

Hard gate · run programmatically
[ ] 40. `python3 assets/validate.py path/to/your-deck.html` exits 0.
        This script EXECUTES checks 02 / 05 / 06 / 07 / 10 / 12 / 13 /
        29-32 / 36 / 38 statically. Don't ship a deck where the validator
        is red — fix the underlying issue.
[ ] 41. `python3 assets/validate.py path/to/your-deck.html --strict`
        also exits 0 before final delivery (warnings → errors).

Layout integrity (L1-L4 — LKK exchange deck failure modes)
[ ] 42. L1 — .slide .wordmark default references var(--fs-asset-logo) (color).
        Mono opt-in via class="is-mono" only on chapter dividers / over-imagery
        edge cases. Validator: check_logo_default().
[ ] 43. L2 — every body-content stage on content-2col / content-3up / process /
        timeline / pipeline either has align-content: center OR flex: 1 declared.
        Never ship a top-stacked slide. Validator: check_balance().
[ ] 44. L3 — cards inside grids are content-tall, not stretched to canvas.
        margin-top: auto on inner pills must NOT create an empty middle.
        Validator: indirectly via L2 (centering eliminates the bug).
[ ] 45. L4 — .slide[data-layout="process"] .output .attrs is grid-template-columns:
        1fr (single column). Validator: check_attrs_density().

UI mocks
[ ] 46. UI1 — every system UI element (app windows, sidebars, chat threads,
        spreadsheets, dashboards, modal dialogs) is recreated in HTML using
        the .ui-* primitives, NOT embedded as a raster screenshot.
        Validator: audit_ui_mocks_are_html — warns on any <img> in slide
        content that isn't a known brand asset or data: URI. Real photographs
        go through data-decor="photo-bg" with style="--photo: url(...)".

Variant discipline
[ ] 47. R47 — every CSS rule whose selector contains [data-variant=...] AND
        declares any structural property (display, flex-direction, flex-wrap,
        grid-template-*) MUST also redeclare both align-items (or place-items)
        AND justify-content (or place-content). Cosmetic-only variants
        (color/padding/font/gap) are exempt. Validator: audit_variant_discipline.

Default centering for fixed-shape layouts
[ ] 48. R48 — every container layout that holds a fixed number of content
        blocks (content-3up, content-2col, agenda, stats, big-stat, quote)
        default-centers vertically via justify-content / align-content /
        align-items / place-content : center on its inner container
        (.stage / .grid / .toc / .flow / .nodes / .stack). pipeline /
        timeline / process are documented exceptions that fill instead.
        Validator: audit_default_centering / check_default_centering.

Cyan-as-slide-accent forbidden
[ ] 49. R49 — cyan (#24C3FF) is INLINE-WORD-HIGHLIGHT only via .accent-text
        / .hl. Slides with data-accent="cyan" are rejected. The CSS no
        longer ships a `[data-accent="cyan"]` rule; if a slide tries to
        opt in, the variable doesn't resolve. Validator:
        audit_no_cyan_accent.

Performance budget
[ ] 50. P50 — base64 in <style> ≤ 100 KB on the default linked deck
        (≤ 250 KB hard cap). Inlined-mode decks must declare
        `<meta name="fs-deck-mode" content="inline">` to skip this check.
        Validator: audit_perf.
[ ] 51. P51 — backdrop-filter blur radius ≤ 10 px (GPU cost scales with
        radius; opaque rgba is preferable in most cases).
[ ] 52. P52 — at most ONE `new ResizeObserver(...)` instance in the runtime.
        One document-level RO with rAF batching is the规范.
[ ] 53. P53 — runtime uses `AbortController` (or `removeEventListener`) for
        every `addEventListener` so SPA hosts can `destroy()` cleanly.
[ ] 54. P54 — `.slide-frame { contain: layout paint size }` is set so slide
        changes are local repaints, not full-document.
[ ] 55. P55 — `.slide-frame .slide { will-change: transform }` (with a
        `translateZ(0)` in the transform value) gives the slide a GPU
        layer, avoiding CPU rasterization on every transition.

Content-page header minimalism
[ ] 56. R56 — content-page `.header` contains ONLY a single `<h2>` title.
        No `.eyebrow`, no inline page-no, no inner wrapper div. The
        page number lives in the footer. CSS defends this with
        `.slide .header .eyebrow { display: none }` — but the markup
        should be clean too. Validator: audit_header_minimal.

Conversion compliance (when re-rendering external material)
[ ] 57. C1 — when converting external material (PDF / HTML / PPT export),
        every source page is mapped to ONE of the 13 layouts using the
        identification table in the "Converting existing material" section.
        Cover pages use `data-layout="cover"` (NOT a content layout).
        End pages use `data-layout="end"` (NOT a content layout with a
        manually-built thank-you grid). No 14th invented layout.
[ ] 58. C2 — during conversion, source-only artifacts are STRIPPED before
        rendering: source page numbers (use the footer pageno only),
        watermarks, decorative breadcrumbs, kicker text above titles,
        emoji / `!` / `…` / `???`, and `<br>` inside content-page titles.
        Atmospheric content (radial glows, photographic backgrounds, brand
        gradients) is PRESERVED via `data-decor` (see "Preserve
        atmospheric / decorative backgrounds"). System UI screenshots
        are RECREATED in HTML via `.ui-*` primitives, not embedded as
        raster (UI1).

Local-mount preflight
[ ] 59. PREFLIGHT — `bash assets/preflight.sh` exits 0. The skill is NOT
        running from `/sessions/*/mnt/outputs/` (ephemeral). The skill
        root is writable. All required asset files are present. If
        any of these fails, refuse to generate any HTML and tell the
        user to mount a local folder.
```

If any item fails, fix the slide. Don't ship a deck that fails item 5 — emoji on a
飞书 sales slide is the single fastest way to break trust with the audience.

---

## Failure modes & fixes

| Symptom                                | Likely cause                                         | Fix |
|----------------------------------------|------------------------------------------------------|---|
| Slide displays at top-left, tiny       | Forgot to wrap `.slide` in `.slide-frame`            | Add the wrapper. |
| Indicator + toggle don't appear        | Missing `<script src="assets/feishu-deck.js">`       | Add it (or inline). |
| Mobile shows huge whitespace           | Viewport meta tag missing                            | Add `<meta name="viewport" ...>`. |
| Title overflows past edge              | Content too long for 1920 px canvas                  | Cut content. Don't shrink type below 24 px. |
| Card heights misaligned                | Card content imbalanced                              | Add a 1-line `<br>` to short titles. Cards are min-height:400. |
| Stats column rule on first column      | Default CSS leaks                                    | First column has `border-left:0` already — check overrides. |
| Two accents on one slide               | Forgot to set `data-accent` on slide level           | Set `data-accent="teal"` on the `.slide` element only. |
| Quote glow too strong                  | Custom background overrides `--fs-grad-glow-blue`    | Don't override `.slide[data-layout="quote"]` background. |

---

## Caveats to relay to the user when delivering

> "This is an HTML approximation of the 飞书 母版 2025 (深色通用) PowerPoint master.
>
> 1. **Fonts** — Production uses 方正兰亭黑Pro (licensed). Web stack falls back to
>    Noto Sans SC / PingFang SC. To match the master pixel-for-pixel, install the
>    licensed face on the rendering machine.
> 2. **Logo** — The wordmark in this output is typographic ('Lark · 飞书'). For the
>    real tri-petal mark, drop in `lark-logo-mono-white.png` and `lark-logo-color.png`
>    via the `<div class=\"wordmark\">` slot.
> 3. **Icons** — Hand-drawn Lucide-style. For brand parity, swap to ByteDance IconPark.
> 4. **Customer logos / photos** — All product UI mocks and customer faces are
>    flagged with 〔TODO〕 and must be replaced before external use."

---

## Examples

- `examples/sample-deck.html` — 12-slide demo using all 13 layouts (single file, inlined).
- `preview-dark.html` — token swatches and component gallery for visual self-test.
- `templates/slide-recipes.html` — every layout in one reference deck (open and copy).
