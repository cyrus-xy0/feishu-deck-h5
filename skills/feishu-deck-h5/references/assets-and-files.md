# assets-and-files — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:品牌资产/产品icon/persona/phone-mock + 文件树

## Files in this skill

```
feishu-deck-h5/
├── SKILL.md                    ← you are here
├── DESIGN.md                   ← 9-section design system spec (awesome-design-md format)
├── assets/                     ← TWO layers: framework (top) + shared content pool (shared/)
│   ├── feishu-deck.css         ← all design tokens + 13 slide layouts (single source of truth)
│   ├── feishu-deck.js          ← scale-to-fit + present/scroll modes + keyboard nav
│   ├── edit-mode/              ← client-side WYSIWYG editor (auto-injected by shell templates, default-on since 2026-05-21)
│   │   ├── deck-edit-mode.css  ← edit-mode chrome (toolbar, drag affordances)
│   │   └── deck-edit-mode.js   ← contenteditable text leaves + drag-reorder + Cmd/Ctrl+S save
│   ├── validate.py             ← programmatic self-check (HARD GATE before delivery)
│   ├── copy-assets.py          ← per-run portability + emits assets-manifest.yaml
│   ├── new-run.sh              ← create runs/<timestamp>/{input,output}/ workspace
│   ├── preflight.sh            ← mandatory local-mount check
│   ├── lark-logo.png           ← color logo (petals + 飞书) for cover/end. From master image3.png
│   ├── lark-logo-mono-white.png← mono-white variant for content/section pages
│   ├── lark-cover-bg.jpg       ← flower-on-dark master background. From master image2.jpg
│   ├── lark-section-bg.jpg     ← cool blue glow on right (chapter pages). From master image4.jpg
│   ├── lark-content-bg.jpg     ← subtle dark gradient (content pages). From master image1.jpg
│   ├── lark-slogan.png         ← "先进团队 先用飞书" slogan PNG. From master image6.png
│   └── shared/                 ← library-grade reusable pool (cross-deck, dedupe-able)
│       ├── clientlogo/         ← 客户/投资机构 brand PNGs (251+ files, growing)
│       ├── digital_employee_avatars_50/ ← 50-portrait generic AI agent library
│       ├── mydigitalemployee/  ← user's named personas (睿睿/参参/探探/呆呆/图图/…)
│       ├── third-party-logos/  ← zoom/slack/salesforce/钉钉/… (sales-ops tools, NOT bytedance)
│       ├── feishu-products/    ← 飞书标识_* (AI/aily/aPaaS/多维表格/… brand kit)
│       └── bytedance-products/ ← 字节系产品 logo (doubao/trae/…) — 飞书之外的字节家产品
├── templates/
│   ├── _shell.html             ← the empty single-file deck skeleton (head + 1 sample slide)
│   └── slide-recipes.html      ← every layout shown in one reference deck (copy the markup you need)
├── examples/
│   └── sample-deck.html        ← a polished 12-slide demo deck (for reference + visual check)
└── preview-dark.html           ← token swatches + type scale + component gallery
```

### Assets layout — two layers (framework + shared pool)

`assets/` has two layers, separated by purpose:

- **Framework** (top-level of `assets/`): `feishu-deck.css`, `feishu-deck.js`,
  and the lark master brand kit (`lark-logo*`, `lark-*-bg.*`, `lark-slogan.png`).
  Every deck depends on these — they ship with every deliverable, never deduped.
- **Shared content pool** (`assets/shared/`): cross-deck reusable PNGs —
  client logos, digital-employee portraits, third-party tool logos, feishu
  sub-product brand kit. Many decks share the same files; downstream tools
  (the slide library) dedupe these against their own `assets/shared/` copy.

**`copy-assets.py` emits `output/assets-manifest.yaml`** at hand-off time,
classifying every referenced file as `shared` / `framework` / `deck-local`.
The slide library reads this manifest on ingest:

- `shared` → don't copy into the deck folder; rewrite the path to the library's
  shared pool (saves ~50–500 KB per deck).
- `framework` → leave alone; deck stays self-contained.
- `deck-local` → copy into `decks/<id>/assets/` (deck-unique covers, photos).

**Back-compat**: pre-reorg references like `assets/clientlogo/foo.png` (no
`shared/` prefix) still work — `copy-assets.py` auto-redirects to
`assets/shared/clientlogo/foo.png`. New authoring should use the canonical
`shared/` paths everywhere.

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

### 飞书 product-line icons (2026-05-06) — `assets/shared/feishu-products/飞书标识_*.png`

Beyond the master 6 brand assets above, the skill also ships the
**飞书产品线 official 标识** PNGs covering all product modules. Use these
when a slide references a specific 飞书 product (aily / 多维表格 / 妙搭 /
…) — DON'T draw a stylized clone, DON'T hand-write SVG approximations,
DON'T fetch from the web. The licensed PNGs are right here.

**Naming convention**: `飞书标识_{产品}_{变体}.png`

| 产品 (中文) | Reference path (Color variant by default) | Use for |
|---|---|---|
| AI (飞书 AI 通用) | `assets/shared/feishu-products/飞书标识_AI_Color.png`             | 飞书 AI 入口 / AI 主题页(P04 中卡 hero) |
| aily          | `assets/shared/feishu-products/飞书标识_aily_Color.png`            | aily 智能体相关 |
| aPaaS         | `assets/shared/feishu-products/飞书标识_aPaaS_Color.png`           | 业务搭建 / 低代码相关 |
| 妙搭          | `assets/shared/feishu-products/飞书标识_妙搭_Color.png`            | 妙搭轻量系统 |
| 知识问答      | `assets/shared/feishu-products/飞书标识_知识问答_Color.png`        | 飞书知识问答 / Wiki AI |
| 飞书会议      | `assets/shared/feishu-products/飞书标识_飞书会议_Color.png`        | AI 会议 / 视频会议页 |
| 飞书多维表格  | `assets/shared/feishu-products/飞书标识_飞书多维表格_Color.png`    | Base / 业务一张表 |
| 飞书人事      | `assets/shared/feishu-products/飞书标识_飞书人事_Color.png`        | HR 模块 |
| 飞书招聘      | `assets/shared/feishu-products/飞书标识_飞书招聘_Color.png`        | 招聘模块 |
| 飞书绩效      | `assets/shared/feishu-products/飞书标识_飞书绩效_Color.png`        | 绩效模块 |
| 飞书项目      | `assets/shared/feishu-products/飞书标识_飞书项目_Color.png`        | 项目管理模块 |
| 飞书People    | `assets/shared/feishu-products/飞书标识_飞书People_Color.png`      | HR 套件总称 |
| 集成平台      | `assets/shared/feishu-products/飞书标识_集成平台_Color.png`        | 集成 / 中台 |

**3 variants per product** — pick by background tone:

- `_Color.png` (default) · 全彩,深色背景上用(我们 deck 默认就是深色,所以
  绝大部分场景用这个)
- `_White.png` · 单色白,在已有强色块/品牌色背景上用,避免色彩打架
- `_Black.png` · 单色黑,白色背景 deck 用(本 skill 默认深色 deck,基本用不到)

**How to embed (UI1-friendly)**:

```html
<!-- Use background-image on a div (NOT <img>) so UI1 validator stays
     quiet and the PNG can be controlled via CSS sizing -->
<div class="card-logo" role="img" aria-label="飞书 aily"
     style="background-image: url('../../../skills/feishu-deck-h5/assets/shared/feishu-products/飞书标识_aily_Color.png')"></div>
```

```css
.card-logo {
  width: 56px; height: 56px;             /* 方形 icon 默认尺寸 */
  background-position: center;
  background-size: contain;
  background-repeat: no-repeat;
}
/* Hero card: 用 lark-logo.png (含 wordmark) 而不是产品 icon */
.card.is-hero .card-logo {
  width: 180px; height: 57px;            /* lark-logo 是宽比例 (582:183 ≈ 3.18:1) */
  background-image: url('../../../skills/feishu-deck-h5/assets/lark-logo.png');
}
```

**Authoring discipline**:

1. 任何 slide 提到具体 飞书 产品 → **优先从 `assets/shared/feishu-products/` 找现成 PNG**,不要自己画 SVG / 用 emoji / 用文字代替
2. 找不到对应产品的 icon → 用 `lark-logo.png` (飞书品牌总标志,含 wordmark) 兜底,**不要自己设计**
3. 多个产品并列出现 (如 P04 三入口卡) → 中卡用 `lark-logo.png` (品牌总标志) 突出,边卡用产品 icon 区分
4. 编辑器路径相对值跟你的文件位置变 — 一般 `runs/<ts>/output/` 下用 `../../../skills/feishu-deck-h5/assets/...`,`single-pages/` 子目录加多一层

**Why this is mandatory**: 飞书的 brand guidelines 要求产品标识必须用 official
PNG,不允许重绘。手写 SVG 模仿就是商标违规;用 emoji 替代失专业感;
fetch 远程图既慢又怕版权链接失效。`assets/shared/feishu-products/` 里 45 张就是定稿版本,直接拿来用。

### Client / portfolio brand logos (mandatory) — `assets/shared/clientlogo/`

When a slide shows a **client brand**, **portfolio company**, **PE/VC firm**,
or any "we serve / 这些客户都在用" matrix, the logo PNG MUST come from
`assets/shared/clientlogo/<filename>.{png|jpg|jpeg}`. **Do NOT** put per-client
logos in `assets/` root — that folder is reserved for framework
(feishu-deck CSS/JS) + lark master brand (logo / cover bg / slogan) only.

**Filename matching rule**:

1. **First** look for the client's Chinese name as filename: `霸王茶姬.png`,
   `茶百道.png`, `益禾堂.png`, `源码资本.png`, `中金公司.png`.
2. **Fall back** to canonical English short name / abbreviation: `IDG资本.png`,
   `KKR.png`, `PAG.png`, `CPE源峰.png`, `Mistine_1.png`, `moodytiger.png`.
3. Multiple variants for the same brand → suffix `_N` (`太平鸟_1.png`,
   `新希望_2.png`) or `_paired` for the smaller variant used in 2-up
   paired cells (`CPE源峰_paired.png`).

**Lookup workflow** (every time you author a slide that references client logos):

```bash
ls /Users/<user>/.claude/skills/feishu-deck-h5/assets/shared/clientlogo/ | grep -i "<name>"
```

If the brand exists → use that file. If it doesn't → ask the user to drop
it into `assets/shared/clientlogo/` first; do NOT save it to the run's
`input/` folder, do NOT save it to `assets/` root, do NOT generate a
text fallback PNG without telling the user.

**HTML embed pattern**:

```html
<!-- Bg-image on div for UI1-friendliness -->
<div class="logo-card" role="img" aria-label="霸王茶姬">
  <div class="logo" style="background-image: url('../../../../skills/feishu-deck-h5/assets/shared/clientlogo/霸王茶姬.png')"></div>
</div>

<!-- Or <img> when explicit dimensions / max-width matter -->
<img src="../../../../skills/feishu-deck-h5/assets/shared/clientlogo/中金公司.png" alt="中金公司">
```

(Path depth: `runs/<ts>/output/single-pages/p<NN>.html` → 4 levels up to
repo root, then `skills/feishu-deck-h5/assets/shared/clientlogo/`.)

**Why this is mandatory**: the user maintains `assets/shared/clientlogo/` as a
versioned, growing library shared across all decks. Old per-deck `input/`
copies go stale; `assets/` root pollution makes the brand asset surface
unmaintainable. Single source of truth = `assets/shared/clientlogo/`.

### Digital employee portraits (mandatory) — TWO source folders

**Decision rule (apply in order):**

1. **Named, specific persona** (睿睿 / 参参 / 探探 / 呆呆 / 图图 the 5 内部
   AI 助手, or any task-specific persona like 门店 FFDI 营运助手 / 销售知识
   助手) → portrait MUST come from `assets/shared/mydigitalemployee/<name>.png`.

2. **Anonymous / generic AI agent slot** (e.g. P33 row "门店巡检" of
   品牌X — the row needs a digital-employee face but no specific named
   persona is assigned) → portrait MUST come from
   `assets/shared/digital_employee_avatars_50/NN_<traits>.png` (50-portrait
   generic library, diverse demographics, named by index +
   ethnic/style traits like `01_east_asian_woman_white_shirt.png`).
   Use them in numerical order or pick by visual fit; do not duplicate
   on the same slide.

**Where portraits do NOT belong**:

- ❌ `assets/shared/clientlogo/` — that's customer brand logos, not agents.
- ❌ `assets/` root — reserved for framework (feishu-deck CSS/JS) +
  lark master brand (logo / cover bg / slogan) only.
- ❌ `runs/<ts>/input/` — input is per-run, ephemeral; portraits are
  cross-deck shared assets.
- ❌ Generated CSS gradient placeholder (gray circle) when the slide
  REALLY needs a face — pick a generic from `digital_employee_avatars_50/`
  instead.

**Folder structure**:

```
assets/shared/
├── mydigitalemployee/              — user's OWN named personas
│   ├── 睿睿.png                     — AI 汇报复盘助手
│   ├── 参参.png                     — AI 故事线参谋
│   ├── 探探.png                     — AI 客户调研助手
│   ├── 呆呆.png                     — AI Demo 素材助手
│   ├── 图图.png                     — AI PPT 插画助手
│   ├── 门店FFDI营运助手.png
│   ├── 采购选品小助手.png
│   ├── 销售知识助手.png
│   └── … (extend as new named personas appear)
└── digital_employee_avatars_50/    — 50-portrait generic library
    ├── 01_east_asian_woman_white_shirt.png
    ├── 03_southeast_asian_man_hoodie.png
    ├── 05_african_man_beard_polo.png
    └── … (45+ diverse portraits, gaps in numbering OK)
```

Native circular crop (transparent PNG, 160–230 px square typical), so a
plain `background-image` + `border-radius: 50%` renders cleanly.

**HTML embed pattern**:

```html
<!-- Named persona (睿睿/参参/etc.) — use mydigitalemployee/ -->
<div class="avatar"
     style="background-image: url('../assets/shared/mydigitalemployee/睿睿.png');
            background-position: center; background-size: cover; border-radius: 50%;"
     role="img" aria-label="睿睿"></div>

<!-- Anonymous slot — use digital_employee_avatars_50/ -->
<div class="avatar"
     style="background-image: url('../assets/shared/digital_employee_avatars_50/01_east_asian_woman_white_shirt.png');
            background-position: center; background-size: cover; border-radius: 50%;"
     role="img" aria-label=""></div>
```

**Lookup workflow** (every time a slide references a persona):

```bash
# Step 1: try named persona first
ls ~/.claude/skills/feishu-deck-h5/assets/shared/mydigitalemployee/ | grep -i "<name>"

# Step 2: if no named match, fall back to generic library
ls ~/.claude/skills/feishu-deck-h5/assets/shared/digital_employee_avatars_50/ | head
```

If named persona exists → use `mydigitalemployee/`. If the slide just
needs a generic AI-agent face (no specific name) → use
`digital_employee_avatars_50/`. **Do NOT** generate a gradient
placeholder, **do NOT** crop from input/, **do NOT** save to
`assets/` root.

**Why this is mandatory**: the user maintains both folders as
versioned, growing libraries shared across decks (P25 / P26 / P27 /
P29 / P33 / P41 reference these portraits). The historical mistake of
saving the same avatar in three places (input/, assets/ root,
clientlogo/) led to drift and broken refs. **Single source of truth**:
named → `mydigitalemployee/`, generic → `digital_employee_avatars_50/`.

### Interactive demo / phone mockup spec (mandatory) — when a slide animates a chat / app

Some slides need a **live H5 demo** in place of a screenshot or GIF
(e.g. P20 海底捞大明白 chat,product-launch reels,onboarding flows).
Native CSS animations beat GIFs for these reasons: fully crisp at any
projector size,can be paused / toggled,inherit deck typography, and
the deck file stays self-contained without large binary blobs.

**Anatomy of a phone-mockup demo:**

```
.phone (the device shell)
├── ::before (notch / dynamic island — solid #11141c rounded rect, top center)
├── .ph-status (battery / signal / clock — flex 0 0 50px)
├── .ph-bar (app nav: back ‹ + badge + title + more — flex 0 0 52px)
├── .ph-tabs (in-app tab strip if applicable)
├── .ph-divider (e.g. 新话题 thin separator)
├── .ph-chat (flex: 1 — scrollable / animated content area)
│   └── .ph-chat-inner (the actual messages; can `transform: translateY()` to scroll)
├── .ph-foot-ribbon (e.g. 新话题 button)
├── .ph-input (the text field row)
└── .ph-tools (the emoji / @ / mic / image / Aa / + tool row)
```

**Phone shell — bezel via ring shadows, NEVER `box-shadow` with offset:**

R12 forbids real drop shadows. Build the bezel as concentric rings
(`box-shadow: 0 0 0 Npx <color>`),which the validator allows:

```css
.phone {
  width: 380px; height: 780px;
  background: #f6f6f6;
  border-radius: 46px;
  box-shadow: 0 0 0 10px #11141c,         /* 内圈黑 bezel */
              0 0 0 11px #2c3142,         /* 外圈一圈 1px 高光 */
              inset 0 0 0 1px rgba(0,0,0,0.04);  /* 屏内 hairline */
  overflow: hidden;
  display: flex; flex-direction: column;
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC",
               var(--fs-font-cjk);
}
```

NEVER use `box-shadow: 0 20px 56px ...` for "depth" — it's a real drop
shadow and R12 fails it. Outer rings only.

**Match the platform — iOS-flavor or 飞书-flavor or 企微-flavor:**

If the user gives you a reference screenshot (e.g. they drop a
`参考飞书交互样式.png` in `input/`), **read it pixel-by-pixel** and
match:

- Status bar font weight / color
- Notch/island shape and dimensions
- Nav bar back arrow style (chevron `‹` not arrow `←`)
- Tab strip underline color/width (e.g. 飞书 = blue `#3370FF`,3px,
  centered under active label)
- Bubble corner radii (asymmetric: `4px 14px 14px 14px` for "from
  this side")
- Bubble fill (bot = `#fff` border `rgba(0,0,0,0.04)`,user-side
  飞书 = `#DCEDFF`)
- Avatar gradient direction (135deg)
- Robot tag color (`#FFE7B0` bg + `#B87600` text in 飞书)
- Tool bar icon stroke width (1.8 in 飞书)

When in doubt, pick the user's reference over your imagination.

**Animation timing — looping demo, 12–14s typical:**

```
0.3s  · welcome / opening message
1.4s  · user msg 1
2.6s  · user msg 2
3.8s  · typing dots in
5.0s  · typing dots out + bot reply 1 in
6.0s  · input field starts typing user q3
8.4s  · field clears, user q3 message appears in chat
9.4s  · typing dots 2 in
10.8s · typing dots 2 out + bot reply 2 in
12.0s · pause / hold final state
14.0s · loop (animation re-fires)
```

`.ph-chat-inner` should `transform: translateY()` upward in the second
half of the loop so the early messages naturally scroll out of view —
matches how a real chat behaves when 5+ messages exceed the visible
area.

**Animation patterns to keep:**

```css
@keyframes msg-in  { from { opacity: 0; transform: translateY(8px);} to { opacity: 1; transform: translateY(0);} }
@keyframes msg-out { to { opacity: 0; height: 0; padding: 0; margin: 0;} }      /* for typing dots退场 */
@keyframes dot-pulse { 0%,60%,100% { opacity:.3; transform: translateY(0);} 30% { opacity:1; transform: translateY(-3px);} }
@keyframes type-in   { to { max-width: 86%; } }                   /* steps(N, end) for terminal-style */
@keyframes caret-blink { to { opacity: 0; } }                     /* steps(2) for hard blink */
```

Stagger via individual `animation-delay` on each `.msg.mN` selector
rather than `nth-child` — gives you absolute control and survives
DOM reordering.

**Typography floors apply identically inside the phone:**

- Bubble body text: ≥ 14 px (chrome floor — phone screens are visually
  smaller, so 14 px in mockup ≈ 22 px on the slide it lives in)
- Bubble lead / title (e.g. "你好,我是 \<bot name\>"): ≥ 16 px
- Status bar / tabs / nav bar: ≥ 14 px
- DON'T fall below 14 px even though the mockup looks like a real
  phone — the validator counts these as slide content,not chrome,
  so R06 still applies.

**No emoji, no real shadows, all icons via SVG:**

```html
<!-- Status bar wifi/battery: SVG, never 📶 🔋 (R05 fail) -->
<svg viewBox="0 0 16 12" width="16" height="12" fill="currentColor">...</svg>

<!-- Tool icons (emoji 😀 / @ / mic / image / Aa / +): SVG -->
<span class="tool"><svg viewBox="0 0 24 24">...</svg></span>
```

**Pause-on-hover (optional but recommended):**

```css
.phone:hover .ph-chat-inner,
.phone:hover .msg { animation-play-state: paused; }
```

Lets a presenter hover on the demo to freeze the animation mid-flow
during Q&A.

**When to use a phone demo vs a static screenshot:**

| Use phone demo | Use static screenshot |
|---|---|
| Showing a flow / conversation / progressive UI | Showing a single screen state |
| Highlighting an interaction beat (typing, sending, switching skill) | Listing app features statically |
| Replacing a low-res GIF | Showing exact production pixel art |
| Reference image is high-fidelity & faithful copy is feasible | Reference is too dense to recreate (full dashboards / tables) |

If the source is a 3-second video or a 10-frame GIF, a CSS demo
almost always wins. If the source is a 2000×1200 dashboard packed
with data, just use the screenshot — `<img>` it with `max-width: native`.

---

