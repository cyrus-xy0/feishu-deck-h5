# validator-rules — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:validator 规则全表 R02..P55 含义 / 严重度

## Self-check — the validator IS the self-check

Run before every delivery:

```bash
bash assets/finalize.sh runs/<ts>/output local            # in-progress
bash assets/finalize.sh runs/<ts>/output local --strict   # final delivery
```

`finalize.sh` orchestrates `copy-assets` → `extract-texts` → `validate.py`
in order. Every validator error prints **what's wrong + how to fix** —
read it, fix it. Don't suppress.

The validator covers programmable rules (last refreshed 2026-05-18):

| Family | Rules | What it enforces |
|---|---|---|
| Structure | R02 / R07 / R-DOM | every `.slide` has `data-layout`, `data-screen-label`, `.wordmark`; balanced `<div>` open/close (`.slide-frame` direct under `.deck`, exactly one `.slide` per frame, no nested frames) |
| Copy | R05 / R13 / R-BULLET-DASH | no emoji / `!` / `…`; no `<br>` in content-page titles (allowed on hero layouts: cover / image-text / end / section / quote); no ad-hoc `– ` dash bullets (use framework colored dots) |
| Hex palette | R10 | hex values come from `--fs-*` tokens; SVG decor and inlined framework CSS are exempt |
| Drop shadows | R12 | no real `box-shadow` offsets (rings + insets only) |
| Typography | R06 / R20 | body ≥ 24 px; chrome ≥ 16 px; per-page `font-size` on the 4-tier ladder `{16, 24, 28, 48}` — hero exceptions (cover 100, section 88/160, big-stat 132+, quote 88+) require `/* allow:typescale */` in the rule |
| White-text | R-WHITE-TEXT | semantic body text on dark slides is `#fff` not low-opacity gray (which vanishes on projector); chrome opt-out via `/* allow:white-opacity */` |
| Hierarchy | R-HIERARCHY | inside a card, meta-info (owner / source / attribution) is structurally less important than body — its rendered fontSize must be ≤ body |
| CSS vars | R-CSSVAR | `var(--name)` references must resolve to a defined custom property (or have a fallback). Browser silently drops the surrounding declaration when a var is undefined — the worst case is `font:` shorthand where `font-size` falls back to 16 px regardless of the size you wrote |
| Redundant echo | R-ECHO | a summary leaf (class contains `legend / note / footnote / caption / summary / footer / lede / disclaimer / callout / subtitle / kicker / page-sub / tagline / recap`, or a plain `<p>`) shouldn't echo ≥ 3 sibling-leaf prefixes — that's a list restatement; drop the echo and keep only the new information |
| Logo | L1 | `.wordmark` defaults to color; mono is `class="is-mono"` opt-in |
| Layout integrity | L1 / L2 / L4 | logo default, balanced stage with content centering, single-col `.process .attrs` (L3 is not currently shipped) |
| Variants | R47 | structural-changing variants redeclare alignment |
| Centering | R48 | fixed-shape layouts default-center vertically |
| Empty header zone | R-EMPTY-HEADER-ZONE | hiding framework `.header` requires `.stage top ≤32` (snap to edge) OR `top:61` (framework anchor) OR a visible top decoration; otherwise the gap reads as "missing bg" — see BF15 |
| Cyan | R49 | cyan is inline-highlight only, not slide accent |
| Header | R56 | content-page `.header` has only `<h2>` (no eyebrow); matching is class-list aware (`class="header is-tall"` works) |
| Decor | R38 | `data-decor` tokens are from ship list |
| Runtime chrome | R29-R32 | present-mode bar/buttons + `requestFullscreen` wired |
| Centering pattern | R36 | `margin: -540px 0 0 -960px`, NOT grid `place-items` |
| UI mocks | UI1 | system UI is HTML primitives, not raster `<img>` |
| Language | R-LANG | `.title-en` / `.subtitle-en` / `.label-en` classes + chrome-class scan (any class ending in `-en / -eng / -english / -num / -index / -ord` AND eyebrow / kicker / pill / tag / chip / badge family) + sibling-pair detection (CJK leaf paired with Latin-only leaf inside the same parent) — only when `<meta name="fs-language" content="zh-only">` (or absent); meta-attribute order is irrelevant |
| Slide keys | R-KEY | every `.slide` has unique semantic `data-slide-key` (kebab-case); positional slugs warned |
| Text-id sidecar | T00 / T01 / T02 / T03 | data-text-id present (T00); valid `slide-NN.field` shape (T01); unique (T02); paired `texts.md` in sync (T03) |
| Performance | P50-P55 | base64 budget, blur cap, single ResizeObserver, AbortController, GPU layers |
| Visual (Playwright, default-on) | R-OVERFLOW / R-OVERLAP / R-VIS-TIER / R-VIS-HIER / R-VIS-ALIGN / R-VIS-LABEL-FLOOR / R-VIS-BODY-FLOOR / R-VIS-ORPHAN / R-VIS-TITLE-POSITION / R-VIS-ABSPOS-DUAL-ANCHOR / R-VIS-OPT-OUT-ABUSE / R-VIS-CARD-MIN-HEIGHT-SPARSE / R-VIS-SLACK-FLEX / R-VISUAL / **R-VIS-CARD-OVERFLOW** / **R-VIS-BALANCE** / **R-FOCAL-CHECK** / **R-VIS-CROWD** / **R-VIS-TITLE-GAP** | slide-level overflow > 1920×1080; sibling bbox intersection inside `.stage / .grid / .flow / .nodes / .toc / .stack / .table-wrap` (catches "column bleeds into legend"); computed `font-size` on 4-tier ladder; meta ≤ body in rendered DOM; grid-children equal height; hero-context cards forbid 16 px non-chrome labels; **inner element with `overflow:hidden` + `scrollHeight > clientHeight` (catches the SILENT TEXT CLIP bug where dense 3-up cards swallow content past their flex-1 boundary — added 2026-05-22)**; **视觉重心 / 留白均衡** (R-VIS-BALANCE · 2026-05-28 · WARN · top-heavy / bottom-heavy / dead-band / **side-empty(横向失衡·单侧空壳,2026-05-31 · P10:真实内容 text+media 叶子挤向一侧、另一侧 ≥22% 横向空,空框不计、右图算 media 不误报 → #36「右半空壳面板」)** detection inside the body container — catches "上空 / 下空 / 中空" feedback that floor rules miss; per-slide opt-out `data-allow-imbalance`); **视觉焦点** (R-FOCAL-CHECK · 2026-05-28 · WARN · ≥3 elements share the slide's max fontSize without a declared `.is-hero` / `data-focal` AND without a parallel-pattern ancestor (overview-grid / north-star-map / scene-grid / logo-wall / kpi-strip / arch-stack / pipeline / …) → focal ambiguous. Catches "信息平铺无重点": title 48 + 3 card titles 48 = eye doesn't know where to land. Skip hero layouts; per-slide opt-out `data-allow-no-focal`); **框内文字贴底** (R-VIS-CROWD · 2026-05-30 · WARN · framed 非媒体框内文字离框可见底边 <10px 且明显比顶部更挤(下偏≥16px)→ "文字离下面太近";松/下方大留白不触发,所以 KPI 列顶基线对齐等 stats 类几何天然豁免(校准实测:挤底 3/6px 触发、stats 16px 放行),无需版式名白名单;per-slide opt-out `data-allow-imbalance`); **正文顶到标题** (R-VIS-TITLE-GAP · 2026-05-31 · ERR · `.header` 底 → `.stage` 最顶真实内容块的**相对**间距 <24px(design px)或为负(重叠)→ 正文撑高/溢出顶到标题;R-VIS-TITLE-POSITION 只看 `.header` 绝对 top(≈61,跳过 `display:none` 隐藏 header——如 agenda 默认无 `with-header` 变体;2026-05-31 修:隐藏 header 全零 bbox 曾误报 top:0)、同容器 R-OVERLAP 跨容器比不到,这条专补这个盲区;hero 版式(TITLE_SKIP_LAYOUTS)与"内容整体在标题上方"的 full-bleed 豁免;死规矩:标题不动,压内容/下移正文); **同角色字号不一致** (R-VIS-PEER-SIZE · 2026-05-31 · WARN · 同一并列容器(grid/卡/PARALLEL)内、语义角色相同(body/desc/feat-body…,角色 token 字面相等才互比)的 sibling computed font-size 不一致(容差 1px)→ "有大有小";只报偏离多数派者;豁免 hero/SVG/mock/chrome/单元素组;opt-out `data-allow-peer-size`); **同组框间距/内距不等** (R-VIS-GUTTER · 2026-05-31 · WARN(lifted→soft) · flex/grid 容器内 ≥3 个 framed 非媒体组框,相邻 gutter 应相等 / 同 tag 组框内 padding 应一致;双闸 max>min*1.8 且差>10px;豁免 hero/`data-allow-imbalance`/媒体框/<40px chrome;P7 #3 卡片左右 28 但到下面 8 / #4 cell padding 不一); **hero 字号偏小** (R-VIS-HERO-FLOOR · 2026-05-31 · WARN(lifted→soft) · cover/section/big-stat/stats/quote 的 hero 主元素(标题/.num/.chapter-num/KPI 值)computed font-size < 该版式 master hero 下限 → 偏小;方向=尺寸下限而非 HERO_SIZES 白名单;豁免 mock/`data-allow-typescale`;P11 封面 82<100); **短标签字号下限** (R-VIS-SHORT-LABEL-FLOOR · 2026-05-31 · WARN(lifted→soft) · 1–7 字、非 chrome/mock/media 的可见文本(**含 SVG `<text>`/`<tspan>` 轴标**,其他渲染检查都跳过 SVG)computed <18px → 短轴标/分类标签投影看不清;补 R-VIS-BODY-FLOOR「≥8 字」门槛放过的缝;opt-out `data-allow-body-floor`;P1 图表轴标). ~2 s overhead. `--no-visual` skips; gracefully skips when playwright not installed |
| Lift integrity | R-VIS-LIFT-STYLE-LOST | a slide lifted to `layout:raw` that lost its framework styling (near-empty inline `<style>` + framework-styled class names like `.stack` / `.attrib` / `blockquote`) — re-lift with `lift-slides.py` or set the schema layout directly |
| Self-containment (advisory) | R-SELF-CONTAINED | a head/deck-level `<style>` references a per-slide selector (`[data-slide-key=…]` / `[data-page=…]`) but sits OUTSIDE the slide — the page-anim leak that vanishes on republish + is left behind on lift. Move the rules into the slide's `custom_css` (renderer co-locates them inside `.slide`). `warn_soft` · advisory, never blocks (even under `--strict`) until the L7 head-CSS→custom_css codemod sweeps the back catalog, then promoted to `err`. Framework-inlined CSS + in-`.slide` blocks exempt |
| Auto-balance runtime (hard gate) | R-AUTOBALANCE-PRESENT | `err` · 根因硬闸 (2026-05-31): deck HTML 必须内联/链接当前 `feishu-deck.js` 的 auto-balance runtime(指纹 `function balanceSlide(slide)`),否则运行时这段 0 行没跑 → "文字贴底"等 box-crowd 加载时不会被自动修(本会话最致命的流程根因:青啤 raw deck 实测 0 行)。schema 渲染的 deck 天然内联当前 JS → 永不触发,只打 raw/legacy/手搓/旧版 deck。修法: `python3 assets/rebundle-import.py <deck.html> --inplace`。豁免:非 deck(无 `.deck`)/ deck 标 `data-no-autobalance`(作者显式关) |
| Richness (advisory) | R-VIS-NO-IMAGERY | ≥60% of content slides carry zero icon / image / illustration → deck reads visually flat (`warn_soft` · advisory, never blocks; sparse-by-design layouts exempt) |
| Run-feedback | R-FEEDBACK | every run produces a `FEEDBACK.md` capturing decisions made for maintainer follow-up |
| Preflight | PREFLIGHT | local mount writable; not ephemeral |

**Severity model**: every audit emits `warn`, `err`, or `warn_soft` at its inherent severity. `--strict` globally promotes all regular `warn`s to errors at the end of `main()`. **Soft warnings** (`warn_soft`) — currently `R-FEEDBACK`, `R-VIS-ALIGN`, `R-VIS-NO-IMAGERY`, and `R-SELF-CONTAINED` — are editorial advisories that NEVER escalate to errors under `--strict`. They render alongside regular warnings (under the same `WARNINGS` heading) but don't fail CI.

What the validator can't catch — needs human eyes before delivery:

- **Visual alignment** — title baseline ↔ logo center, agenda numerals ↔ titles
- **Atmospheric feel** — gloom/glow density vs content density (open at 1920×1080 and squint)
- **ZH-EN sizing balance** on bilingual decks (ZH must read bigger / sit above)
- **Narrative landing** — does each slide deliver its one point in 3 seconds?

Open at 1920×1080 (PC), 1280×720 (laptop), 380×680 (phone). If any breaks
visually, fix the slide; the validator only catches programmable rules.

---


## Self-check must be EXECUTED, not just listed

The validator audits at the bottom of this file are a hard gate, not a
checklist for your reading pleasure. Before declaring a deck "done":

1. **Run a font-size audit programmatically.** Don't trust visual feel.

   ```bash
   python3 assets/validate.py path/to/your-deck.html
   # exit 0 = pass · exit 1 = fail · exit 2 = file not found
   ```

   The shipped `assets/validate.py` script statically audits the assembled
   HTML against every check that doesn't require a real browser:

   - **Structure** (R02 / R07): every `.slide` has `data-layout`,
     `data-screen-label`, and `.wordmark`. (`.footer` was retired 2026-05;
     the present-mode pager handles page numbers — no per-slide chrome
     is required anymore.)
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
   - **Modular type-scale ladder** (R20): every `font-size` in per-page
     `<style>` (selector contains `[data-page="NN"]`) must be in the allowed
     set `{10, 11, 12, 13, 14, 18, 22, 28, 38, 44, 52, 56, 64, 88, 100, 132, 160}`.
     Off-ladder values (16/17/19/20/24/26/30/32/36/40/48/72/96 …) ERROR with
     a "nearest rung" hint. Genuine master-spec exceptions opt out via
     `/* allow:typescale */` inside the rule. The framework stylesheet is
     exempt; this rule fires only on per-page improvisation, which is exactly
     where ad-hoc 24/32/96 sizing slips in.
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

