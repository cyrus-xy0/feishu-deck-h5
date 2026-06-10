# validator-rules — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:validator 规则全表 R02..P55 含义 / 严重度

## Self-check — the validator IS the self-check

Run before every delivery:

```bash
bash assets/finalize.sh runs/<ts>/output local            # in-progress
bash assets/finalize.sh runs/<ts>/output local --strict   # final delivery
```

`finalize.sh` orchestrates `copy-assets` → `validate.py`
in order. Every validator error prints **what's wrong + how to fix** —
read it, fix it. Don't suppress.

The validator covers programmable rules (last refreshed 2026-05-18):

| Family | Rules | What it enforces |
|---|---|---|
| Structure | R02 / R07 / R-DOM | every `.slide` has `data-layout`, `data-screen-label`, `.wordmark`; balanced `<div>` open/close (`.slide-frame` direct under `.deck`, exactly one `.slide` per frame, no nested frames). **R07 (`.wordmark`) is EXEMPT for `data-layout="canvas"` slides and for imported decks (`<meta name="fs-deck-origin" content="imported">`)** — commit 941f781 removed the canvas template's wordmark, so canvas / PPTX-imported decks must not fail R07 on every slide (the R02 `data-layout` / `data-screen-label` checks stay unconditional) |
| Document integrity (hard gate) | R-DOC-INTEGRITY | `err` (F-85, 2026-06-03): the whole `index.html` must be a COMPLETE, runnable document — (1) `<div class="deck">` opened AND closed (no mid-deck truncation: a `+N` `<div>` open-vs-close surplus = the `.deck` close was lost), (2) present-mode runtime PRESENT — linked (`<script src="…feishu-deck.js">`) OR inlined (a `<script>` body toggling `is-current`, or the `function balanceSlide(slide)` fingerprint; covers `build.sh --inline` single-file decks and linked decks whose JS `main()`/check-only already inlined), (3) document ENDS with `</body>` and `</html>`. Closes the gap where R-DOM's body parse returns early on a truncated doc (no `</body>`) and reports CLEAN while the deck shows nothing in the browser (`is-current` never set → "显示不全"). Broader than R-AUTOBALANCE-PRESENT (which polices a STALE runtime lacking the current balanceSlide build) — R-DOC-INTEGRITY only fires when the runtime is ENTIRELY absent / the document is structurally broken. 豁免:非 deck(无 `.deck`)；HTML 片段模板可加 `<!-- allow:doc-integrity -->`. 修法:`render-deck.py` 重渲,绝不手拼 deck 外壳 |
| Baked live DOM (hard gate) | R-BAKED-DOM | `err`: the `index.html` is a serialized POST-JS DOM ("烤死的活 DOM") — a page saved AFTER `feishu-deck.js` already ran (浏览器另存 / edit-mode 保存态), not a `render-deck.py` output. Fingerprints (any one fires): `data-idx="…"` on `.slide-frame` (JS runtime index), a baked `class="deck-ui"` overlay (buildUI createElement+append), or `.deck` carrying runtime flags `data-js-ready`/`data-nav-armed`/`data-edit-paste-guard`. Publishing it double-inits the JS → a duplicate `.deck-ui` whose hardcoded `01 / 01` overlay is what the audience sees (页码定格在 1 但还能翻页 — handlers bind to the real frames, so it's easy to miss). Clean render output NEVER contains these. Runs on BOTH `--visual` and `--no-visual` (byte/source path). 修法:从 `deck.json` 用 `render-deck.py` 重渲再发布,别发烤死版（与 R-DOC-INTEGRITY 同属"绕过渲染器"防线） |
| Copy | R05 / R13 / R-BULLET-DASH / R-ESC-HTML | no emoji / `!` / `…`; no `<br>` in content-page titles (allowed on hero layouts: cover / image-text / end / section / quote); no ad-hoc `– ` dash bullets (use framework colored dots); **R-ESC-HTML**: raw HTML tags (`<span>`/`<br>` etc.) written into an escaped schema text field (content/3up `lede`/`body`/`title` 走 `_esc_br`) render as literal `&lt;span&gt;` 给客户看到代码("乱码") — validator scans rendered output for escaped-tag fingerprints (`&lt;br&gt;` / `&lt;/span&gt;` / `&lt;span class=`) and errs; `{{{ raw }}}` / `layout:raw` 真标签不误报; fix = 改 `layout:raw` 自控 markup 或换行用 `
` |
| Hex palette | R10 | hex values come from `--fs-*` tokens; SVG decor and inlined framework CSS are exempt. Scans BOTH inline `style=""` AND the slide's serialized markup (`<script>`/`<style>`/`<svg>`/`data:` URIs stripped, de-duped against inline) — parity with the old `audit_hex_palette` which scanned the whole slide body, not just inline style |
| Drop shadows | R12 | no real `box-shadow` offsets (rings + insets only). Opt-outs: framework UI-mock window classes (`.ui-window` / `.phone-frame` / `.desktop-frame` / `.browser-frame` / `.app-frame` / `.scene-frame`), the `data-allow-drop-shadow` attribute, OR a `/* allow:drop-shadow */` comment in the author `<style>` rule (same comment-marker convention as R20's `/* allow:typescale */` and R-WHITE-TEXT's `/* allow:white-opacity */` — restored to parity 2026-06-05) |
| Typography | R06 / R20 | body ≥ 24 px; chrome ≥ 16 px; per-page `font-size` on the 4-tier ladder `{16, 24, 28, 48}` — hero exceptions (cover 100, section 88/160, big-stat 132+, quote 88+) require `/* allow:typescale */` in the rule |
| White-text | R-WHITE-TEXT / **R-VIS-DIM-TEXT** | semantic body text on dark slides is `#fff` not low-opacity gray (which vanishes on projector); chrome opt-out via `/* allow:white-opacity */` (author `<style>` rules) or `data-allow-white-opacity` (DOM attr). **R-WHITE-TEXT** scans BOTH author `<style>` CSS rules AND inline `style="color:rgba(255,255,255,<1)"` attributes (the inline pass honors the `font-size<=14` chrome floor and `data-allow-white-opacity`; emits an `<inline>` finding) — parity with the old `audit_white_text`. **R-VIS-DIM-TEXT** (2026-06-05 · WARN · computed-DOM) is its name-free twin — it reads the *rendered* `getComputedStyle(el).color`, catching soft-white delivered via a framework token (`var(--fs-text-40)` etc.) that the source scan can't see through. Flags ≥8-char near-grey body text whose effective brightness `alpha × luminance < 0.5`; saturated brand-accent text / ALL-CAPS labels / bilingual `-en` sub-tracks / chrome classes exempt; `data-allow-dim-text` opt-out. |
| Hierarchy | R-HIERARCHY | inside a card, meta-info (owner / source / attribution) is structurally less important than body — its rendered fontSize must be ≤ body |
| CSS vars | R-CSSVAR | `var(--name)` references must resolve to a defined custom property (or have a fallback). Browser silently drops the surrounding declaration when a var is undefined — the worst case is `font:` shorthand where `font-size` falls back to 16 px regardless of the size you wrote |
| Redundant echo | R-ECHO | a summary leaf (class contains `legend / note / footnote / caption / summary / footer / lede / disclaimer / callout / subtitle / kicker / page-sub / tagline / recap`, or a plain `<p>`) shouldn't echo ≥ 3 sibling-leaf prefixes — that's a list restatement; drop the echo and keep only the new information. **Opt-out (NEW · added in the Python→audits.js migration, did NOT exist in the old engine):** mark the leaf — or any ancestor — with class `echo-intentional` to declare a DELIBERATE closing / recap line that names earlier items on purpose (rhetoric / CTA, not lazy redundancy) |
| Logo | L1 | `.wordmark` defaults to color; mono is `class="is-mono"` opt-in |
| Layout integrity | L1 / L2 / L4 | logo default, balanced stage with content centering, single-col `.process .attrs` (L3 is not currently shipped) |
| Variants | R47 | structural-changing variants redeclare alignment |
| Centering | R48 | fixed-shape layouts default-center vertically |
| Empty header zone | R-EMPTY-HEADER-ZONE | hiding framework `.header` requires `.stage top ≤32` (snap to edge) OR `top:61` (framework anchor) OR a visible top decoration; otherwise the gap reads as "missing bg" — see BF15 |
| Cyan | R49 | cyan is inline-highlight only, not slide accent |
| Header | R56 | content-page `.header` has only `<h2>` (no eyebrow); matching is class-list aware (`class="header is-tall"` works) |
| Decor | R38 | `data-decor` tokens are from ship list — validated on the `.slide` AND any descendant carrying `data-decor` (parity with old `audit_data_decor` which scanned the whole frame markup) |
| Runtime chrome | R29-R32 | present-mode bar/buttons + `requestFullscreen` wired |
| Centering pattern | R36 | `margin: -540px 0 0 -960px`, NOT grid `place-items` |
| UI mocks | UI1 | system UI is HTML primitives, not raster `<img>` |
| Language | R-LANG | `.title-en` / `.subtitle-en` / `.label-en` classes + chrome-class scan (any class ending in `-en / -eng / -english / -num / -index / -ord` AND eyebrow / kicker / pill / tag / chip / badge family) + sibling-pair detection (CJK leaf paired with Latin-only leaf inside the same parent) — only when `<meta name="fs-language" content="zh-only">` (or absent); meta-attribute order is irrelevant |
| Slide keys | R-KEY | every `.slide` has unique semantic `data-slide-key` (kebab-case); positional slugs warned |
| Performance | P50-P55 | base64 budget, blur cap, single ResizeObserver, AbortController, GPU layers |
| Visual (Playwright, default-on) | R-OVERFLOW / R-OVERLAP / **R-VIS-BAND-COLLIDE** / R-VIS-TIER / R-VIS-HIER / R-VIS-LABEL-FLOOR / R-VIS-BODY-FLOOR / R-VIS-ORPHAN / R-VIS-TITLE-POSITION / R-VIS-ABSPOS-DUAL-ANCHOR / R-VIS-OPT-OUT-ABUSE / R-VIS-CARD-MIN-HEIGHT-SPARSE / R-VIS-SLACK-FLEX / R-VISUAL / **R-VIS-CARD-OVERFLOW** / **R-VIS-BALANCE** / **R-FOCAL-CHECK** / **R-VIS-CROWD** / **R-VIS-PANEL-TOP** / **R-VIS-TITLE-GAP** / **R-VIS-DEAD-ANIM** / **R-VIS-DEAD-RULE** / **R-VIS-RAW-TITLE-POS** / **R-VIS-RAW-TITLE-STACK** / **R-VIS-FILL** | slide-level overflow > 1920×1080; sibling bbox intersection inside `.stage / .grid / .flow / .nodes / .toc / .stack / .table-wrap` (catches "column bleeds into legend"); computed `font-size` on 4-tier ladder; meta ≤ body in rendered DOM; hero-context cards forbid 16 px non-chrome labels; **inner element with `overflow:hidden` + `scrollHeight > clientHeight` (catches the SILENT TEXT CLIP bug where dense 3-up cards swallow content past their flex-1 boundary — added 2026-05-22)**; **视觉重心 / 留白均衡** (R-VIS-BALANCE · 2026-05-28 · WARN · top-heavy / bottom-heavy / dead-band / **side-empty(横向失衡·单侧空壳,2026-05-31 · P10:真实内容 text+media 叶子挤向一侧、另一侧 ≥22% 横向空,空框不计、右图算 media 不误报 → #36「右半空壳面板」)** detection inside the body container — catches "上空 / 下空 / 中空" feedback that floor rules miss; per-slide opt-out `data-allow-imbalance`); **视觉焦点** (R-FOCAL-CHECK · 2026-05-28 · WARN · ≥3 elements share the slide's max fontSize without a declared `.is-hero` / `data-focal` AND without a parallel-pattern ancestor (overview-grid / north-star-map / scene-grid / logo-wall / kpi-strip / arch-stack / pipeline / …) → focal ambiguous. Catches "信息平铺无重点": title 48 + 3 card titles 48 = eye doesn't know where to land. Skip hero layouts; per-slide opt-out `data-allow-no-focal`); **框内文字贴底** (R-VIS-CROWD · 2026-05-30 · WARN · framed 非媒体框内文字离框可见底边 <10px 且明显比顶部更挤(下偏≥16px)→ "文字离下面太近";松/下方大留白不触发,所以 KPI 列顶基线对齐等 stats 类几何天然豁免(校准实测:挤底 3/6px 触发、stats 16px 放行),无需版式名白名单;per-slide opt-out `data-allow-imbalance`); **正文顶到标题** (R-VIS-TITLE-GAP · 2026-05-31 · WARN(gap<12px 升 ERR) · `.header` 底 → `.stage` 最顶真实内容块的**相对**间距 <24px(design px)或为负(重叠)→ 正文撑高/溢出顶到标题;R-VIS-TITLE-POSITION 只看 `.header` 绝对 top(≈61,跳过 `display:none` 隐藏 header——如 agenda 默认无 `with-header` 变体;2026-05-31 修:隐藏 header 全零 bbox 曾误报 top:0)、同容器 R-OVERLAP 跨容器比不到,这条专补这个盲区;hero 版式(TITLE_SKIP_LAYOUTS)与"内容整体在标题上方"的 full-bleed 豁免;**2026-06-04 name-free 兜底加 subtitle-folding + opt-out**:header-less raw 页自带「标题+紧邻副标」是常态,旧逻辑把副标当「顶到标题的正文」误报(P4/5/7/8 复发);现按几何 name-free 把紧贴标题(<24px)、own-text、字号严格小于标题、≈单行高的块识别为副标并入「标题带」,gap 从带底量、副标排除出内容扫描——标题下方的高/大块仍算真·拥挤照报;另加 per-slide opt-out **`data-allow-title-gap`**(与 data-allow-imbalance 一族一致,bespoke 标题间距的最后兜底);死规矩:标题不动,压内容/下移正文); **同角色字号不一致** (R-VIS-PEER-SIZE · 2026-05-31 · WARN · 同一并列容器(grid/卡/PARALLEL)内、语义角色相同(body/desc/feat-body…,角色 token 字面相等才互比)的 sibling computed font-size 不一致(容差 1px)→ "有大有小";只报偏离多数派者;豁免 hero/SVG/mock/chrome/单元素组;opt-out `data-allow-peer-size`); **同组框间距/内距不等** (R-VIS-GUTTER · 2026-05-31 · WARN(lifted→soft) · flex/grid 容器内 ≥3 个 framed 非媒体组框,相邻 gutter 应相等 / 同 tag 组框内 padding 应一致;双闸 max>min*1.8 且差>10px;豁免 hero/`data-allow-imbalance`/媒体框/<40px chrome;P7 #3 卡片左右 28 但到下面 8 / #4 cell padding 不一); **hero 字号偏小** (R-VIS-HERO-FLOOR · 2026-05-31 · WARN(lifted→soft) · cover/section/big-stat/stats/quote 的 hero 主元素(标题/.num/.chapter-num/KPI 值)computed font-size < 该版式 master hero 下限 → 偏小;方向=尺寸下限而非 HERO_SIZES 白名单;豁免 mock/`data-allow-typescale`;P11 封面 82<100); **短标签字号下限** (R-VIS-SHORT-LABEL-FLOOR · 2026-05-31 · WARN(lifted→soft) · 1–7 字、非 chrome/mock/media 的可见文本(**含 SVG `<text>`/`<tspan>` 轴标**,其他渲染检查都跳过 SVG)computed <18px → 短轴标/分类标签投影看不清;补 R-VIS-BODY-FLOOR「≥8 字」门槛放过的缝;opt-out `data-allow-body-floor`;P1 图表轴标); **内容画布居中** (R-VIS-CANVAS-CENTER · 2026-05-31 · WARN · 内容并集(排 .header)的垂直中心 vs 画布中心((主标题底+1080)/2;无标题页用整页中心 540)偏移 >40px → 整页"上空/下空"。补 R-VIS-BALANCE 只看 .stage **内部**留白、看不出 .stage **整体相对画布**偏移的盲区(对称 stage 中心 540 ≠ 画布中心 597 → balance 静默、canvas-center 报);满铺型(内容高/可用带 >0.72)豁免顶对齐;几何 name-free;opt-out `data-allow-imbalance`); **绝对定位内容带压正文** (R-VIS-BAND-COLLIDE · 2026-05-31 · ERR · framed + 有文字的 `position:absolute` 内容带(takeaway / cta / principle-band 等挂在 `.slide` 上的「带」)与居中内容容器(`.stage/.grid/…`)内的正文叶子 bbox 相交 >2×4px → 运行时 `centerSlideInCanvas` 把 absolute 排除在内容并集外、把正文居中进带子下;补 R-OVERLAP「只查同容器兄弟、跳过 absolute」的盲区;cover/image-text/end/section 豁免;Fix=把带子放进 `.stage`(flex column)流内、作为整体居中,绝不缩字号/贴边); **面板内单内容贴顶** (R-VIS-PANEL-TOP · 2026-06-01 · WARN · R-VIS-CROWD 的反向孪生:framed 非媒体面板容器(.col-visual / lifted .product-pane/.copy-pane/.case-pane 等)装单个矮内容块,内容贴顶(顶距<24px)、下方大空(底空比顶空多>60px)、且内容高<容器高62% → 面板没把内容垂直居中、卡在框顶。根因=panel 容器缺 flex+justify-center;框架已给 content-2col .col-visual 单子默认居中(:not(:has(card+card)) 守 BF12),这条兜 lifted/raw 页自定义 panel;Fix=该面板 custom_css 补 display:flex;flex-direction:column;justify-content:center;opt-out data-allow-imbalance;pg29 feishu-ai-scene-tools 实战); **动画落地 / 死选择器** (R-VIS-DEAD-ANIM · 2026-06-01 · ERR · F-57 · 该页自己的 `<style>`/custom_css 里某条规则声明了 `animation`/`animation-name`,但其选择器在 present 模式下 `document.querySelectorAll()` 命中 0 个元素(no-match)或解析抛错(parse-error,伪类 :is()/:has() 写法非法)→ 动画永不触发,被驱动元素停在动画初态(常 opacity:0 / transform 偏移)→ 内容投影上永久隐身/永不进场上滚。堵 F-51 整类:lift/前缀注入用正则啃选择器,把合法的 `.slide-frame.is-current` 啃成非法的 `-frame.is-current`(`-frame` 是合法 CSS ident 故能解析、但无 `<-frame>` 元素 → 永不匹配),静态 CSS 分析逐条读都合法、看不出。**只查 slide 自身 `<style>`,不碰 head 框架样式表**(框架 `.slide-frame.is-current .slide>*` reveal 健康、零误报);检测前临时给所有 `.slide-frame` 强加 `.is-current` 再测(否则非当前页的运行时 scoped 选择器会假性零匹配),测完还原;死选择器即便强加 is-current 仍零匹配(无 `<-frame>` 元素)→ 不被掩盖;几何/DOM 判定,lift 页同报 err;Fix=修选择器到合法可命中形态或连 animation 一起删死规则); **死规则(非动画)** (R-VIS-DEAD-RULE · 2026-06-01 · ERR(lift→warn) · F-68 · DEAD-ANIM 的超集到非动画属性:该页 `<style>`/custom_css 里某条规则声明了重要视觉属性(`position:absolute|fixed` / `display:grid|flex` / `font(-size)`≥48px / `width|height`≥120px),但其选择器 present 模式 `querySelectorAll` 零匹配或解析抛错 → 规则死掉、元素静默退默认值(冰山 `.hero-pct` 100px 死退 16px、`.loop-row` grid 死退 block,而 16 是合规档→R20 全绿、无任何闸报警,正是本类盲区)。**判定唯一靠运行时零匹配,绝不看注释**(`.a /*c*/ .b` ≡ 合法 `.a .b`,注释=空白后代组合子,不误判);只查 slide 自身 `<style>` 不碰 head 框架;Fix=修选择器到合法可命中). ~2 s overhead. `--no-visual` skips; gracefully skips when playwright not installed. **R-VIS-RAW-TITLE-STACK** (2026-06-05 · WARN · name-free) — raw content page's de-facto title element folds in a smaller eyebrow/kicker (own-text leaf ≤24px and ≤0.55× the title size): a two-layer title that R56 (keyed on framework `.header .eyebrow`) silently skips on bespoke raw. Fold the marker into the single title line or use `.header > .title-zh`; opt out with `data-allow-title-stack`. |
| Lift integrity | R-VIS-LIFT-STYLE-LOST / **R-LIFT-CSS-BUDGET** | R-VIS-LIFT-STYLE-LOST — a slide lifted to `layout:raw` that lost its framework styling (near-empty inline `<style>` + framework-styled class names like `.stack` / `.attrib` / `blockquote`) — re-lift with `lift-slides.py` or set the schema layout directly. **R-LIFT-CSS-BUDGET** (2026-06-10 · F-281a · WARN, >64KB → ERR) — a CSS-bloat guard that fires ONLY on lifted slides (`data-lifted`): sums the UTF-8 bytes of every `<style>` in the slide subtree (the injected `custom_css` block + any markup-embedded `<style>`) and warns at >24KB, errors at >64KB. Lifting a raw page tends to drag in the SOURCE deck's whole stylesheet (mostly dead rules / `@keyframes` the page never matches) — run `clean-lifted-css.py` to strip the unused CSS, shrinking the deck.json and speeding render. name-free (keyed on the `data-lifted` provenance attribute); clean/authored decks (no lifted slides) self-exempt. |
| Self-containment (advisory) | R-SELF-CONTAINED | a head/deck-level `<style>` references a per-slide selector (`[data-slide-key=…]` / `[data-page=…]`) but sits OUTSIDE the slide — the page-anim leak that vanishes on republish + is left behind on lift. Move the rules into the slide's `custom_css` (renderer co-locates them inside `.slide`). `warn_soft` · advisory, never blocks (even under `--strict`) until the L7 head-CSS→custom_css codemod sweeps the back catalog, then promoted to `err`. Framework-inlined CSS + in-`.slide` blocks exempt |
| Auto-balance runtime (hard gate) | R-AUTOBALANCE-PRESENT | `err` · 根因硬闸 (2026-05-31): deck HTML 必须内联/链接当前 `feishu-deck.js` 的 auto-balance runtime(指纹 `function balanceSlide(slide)`),否则运行时这段 0 行没跑 → "文字贴底"等 box-crowd 加载时不会被自动修(本会话最致命的流程根因:青啤 raw deck 实测 0 行)。schema 渲染的 deck 天然内联当前 JS → 永不触发,只打 raw/legacy/手搓/旧版 deck。修法: `python3 assets/rebundle-import.py <deck.html> --inplace`。豁免:非 deck(无 `.deck`)/ deck 标 `data-no-autobalance`(作者显式关) |
| Richness (advisory) | R-VIS-NO-IMAGERY | ≥60% of content slides carry zero icon / image / illustration → deck reads visually flat (`warn_soft` · advisory, never blocks; sparse-by-design layouts exempt) |
| Raw-first backstop (advisory) | R-RAW-LOOKS-SCHEMA | the raw-first OVER-PROCESSING nudge: a `layout:"raw"` slide whose DOM is just a plain N-card parallel list (icon + title + body) with NO diagram-`<svg>`, NO `@keyframes` animation, NO arrow/connector → that is a standard shape; fall back to `content/3up` / `content/blocks` (strictly less bug surface, faster, consistent). Source-of-truth = sibling `deck.json` (keys whose `layout` is `"raw"`), NOT the rendered `data-layout` (a raw slide often masks itself with a schema-ish `data-layout` to borrow framework CSS); no deck.json (foreign / Path B / lifted standalone) → skip silently. High-precision: skips anything with animation / a non-icon diagram `<svg>` / a flow connector, so metaphor (iceberg), animated heroes, and comparison/flow pages stay untouched. `warn_soft` · advisory, never blocks (even under `--strict`) — if the page has bespoke / relational / narrative substance, keep raw & ignore. Replaces the rejected deck-level ratio cap R-TOO-MUCH-RAW (over-raw is a per-page question, not a global ratio: a 90%-raw deck where every page earns it is fine) |
| Cross-page consistency (advisory · deck-level) | R-DECK-TITLE-DRIFT / R-DECK-PALETTE-DRIFT / R-DECK-TYPESCALE-BUDGET | F-257 · the FIRST deck-level (page-to-page) audits — every other rule is single-page, so "风格逐页漂移" was invisible. All three are `warn` (consistency is advisory, never blocks), name-free (computed geometry/colors, no class whitelist), deck-level (evaluated once on the `isFirstInScope` anchor frame, scanning the whole deck), and carry an opt-out. **R-DECK-TITLE-DRIFT** (2026-06-10 · WARN) — collects every NON-hero content slide's framework header title (`.header .title-zh`, fallback `.header h2`) computed `top` + `font-size` (normalized to design px), takes the deck MODE of each, and flags a page whose title `top` deviates from the mode by >8px (matching R-VIS-TITLE-POSITION's tolerance) OR whose `font-size` ≠ the mode — the page-to-page drift that per-page R-VIS-TITLE-POSITION can't see. Skips hero / `display:none` headers; needs ≥2 measurable titles. Opt-out: `data-allow-title-drift` (slide or deck) / `/* allow:title-drift */`. **R-DECK-PALETTE-DRIFT** (2026-06-10 · WARN) — the "re-eyeballed the accent on every page" fingerprint R10 can't see (R10 strips `<style>`). Scans ALL CSS via `iterStyleBlocks(true)` (incl. framework + per-page `<style>` / custom_css) + inline `style=`, normalizes hex/rgb, keeps only real accents (chroma ≥60 AND max-channel ≥140 — excludes near-black/white/grey backgrounds & text), clusters them (same cluster ⇔ every channel within ≤8), and warns ONLY when a cluster holds ≥3 distinct hexes (≥3 near-duplicates = hand-tuned drift; calibrated so the framework's 6 distinct brand accents and clean decks — worst case a single 2-member mock pair — stay silent). Opt-out: `data-allow-palette` / `/* allow:palette */`. **R-DECK-TYPESCALE-BUDGET** (2026-06-10 · WARN) — deck-wide `allow:typescale` overuse (the exemption became the rule; northregion had 161). Counts `allow:typescale` occurrences across all CSS (the marker R20 honors) vs the non-hero content-page count; warns when occurrences > 1.0× content pages (clean decks measure 0.30–1.00/page → silent under strict `>`), reporting the count + per-page average — the exemption is meant for rare hero numbers, not a deck-wide escape from the 4-tier ladder. Opt-out: `data-allow-typescale-budget` / `/* allow:typescale-budget */`. All advisory · never block delivery. |
| Preflight | PREFLIGHT | local mount writable; not ephemeral |

**Coverage boundary — abspos decoration (R-OVERFLOW / R-VIS-CARD-OVERFLOW)**: both overflow rules DELIBERATELY exclude `position:absolute|fixed` elements (VISUAL-AUDIT-SETTLED-STATE-SPEC §2A). Those are decorative glow / drift / rail layers meant to bleed past the canvas / card and be clipped by `overflow:hidden`; counting them caused false ERRORs. The intentional tradeoff: genuinely absolutely-positioned *content* overflowing the canvas or its card is NOT caught by these two rules — catching abspos-content collisions is R-VIS-BAND-COLLIDE / R-OVERLAP's job, not these rules', so the exclusion is not relaxed.

**Severity model**: every audit emits `warn`, `err`, or `warn_soft` at its inherent severity. `--strict` globally promotes all regular `warn`s to errors at the end of `main()`. **Soft warnings** (`warn_soft`) — currently `R-VIS-NO-IMAGERY`, `R-SELF-CONTAINED`, and `R-RAW-LOOKS-SCHEMA` — are editorial advisories that NEVER escalate to errors under `--strict`. They render alongside regular warnings (under the same `WARNINGS` heading) but don't fail CI.

What the validator can't catch — needs human eyes before delivery:

- **Visual alignment** — title baseline ↔ logo center, agenda numerals ↔ titles
- **Atmospheric feel** — gloom/glow density vs content density (open at 1920×1080 and squint)
- **ZH-EN sizing balance** on bilingual decks (ZH must read bigger / sit above)
- **Narrative landing** — does each slide deliver its one point in 3 seconds?

Open at 1920×1080 (PC), 1280×720 (laptop), 380×680 (phone). If any breaks
visually, fix the slide; the validator only catches programmable rules.

---


## Self-check must be EXECUTED, not just listed

The validator is a hard gate, not a checklist for your reading pleasure.
Before declaring a deck "done":

1. **Run the validator programmatically.** Don't trust visual feel.

   ```bash
   python3 assets/validate.py path/to/your-deck.html
   # exit 0 = pass · exit 1 = fail · exit 2 = file not found
   ```

   `validate.py` is the orchestrator: it auto-resolves linked CSS/JS, then
   folds in the SINGLE rule engine via `run_unified_audits` — the DOM rules
   from `assets/audits.js` (run in headless Chromium when present) plus the
   byte / file-system rules from `assets/run-audits.py`. There is no second
   rule set. The schema contract is checked separately by
   `deck-json/validate-deck.py`. What it covers:

   - **Structure** (R02 / R07): every `.slide` has `data-layout`,
     `data-screen-label`, and `.wordmark`. (`.footer` was retired 2026-05;
     the present-mode pager handles page numbers — no per-slide chrome
     is required anymore. R07 is exempt for `canvas` / imported decks.)
   - **One-line titles** (R13): no `<br>` inside `.header h2` /
     `.header h2.title-zh` / `.header h2.title` on layouts other than
     `cover` / `image-text` / `end` / `section` / `quote`.
   - **Brand chrome** (R07 / L1): warns when `.wordmark.is-mono` is used —
     mono-white logo must be an explicit edge case, not the default.
   - **Banned punctuation** (R05): scans rendered text for emoji, `!`/`！`,
     ellipsis `…`/`...`, `???`/`？？？`.
   - **Font-size floors** (R06): body text ≥ 24 px (`--fs-body`); chrome
     (footnote / source / pill / tag / axis tick / page number) ≥ 16 px
     (`--fs-foot`). The script lists each violation with the offending
     selector and size.
   - **4-tier type ladder** (R20): every per-page `font-size` must land on
     the 4-tier ladder **`{16, 24, 28, 48}`** — `--fs-foot:16 / --fs-body:24
     / --fs-sub:28 / --fs-title:48`. The ladder is DERIVED at runtime from
     the `:root --fs-*` tokens in `assets/feishu-deck.css` (the single source
     of truth — `_validate_common.py`'s `_FS_TOKENS` loads them, `audits.js`'s
     `TYPE_LADDER_PX` / `VIS_TIER` mirror them), NOT hard-typed. Any
     off-ladder value (17/18/20/22/26/30/32/36/40/44/52/64/88/100/132/160 …)
     ERRORs with a "nearest rung" hint. Hero exceptions (cover 100, section
     88/160, big-stat 132+, quote 88+) opt out per-rule with
     `/* allow:typescale */` (raw pages may also need `data-allow-typescale`
     on the element). The framework stylesheet is exempt; the rule fires only
     on per-page improvisation — which is exactly where ad-hoc 20/32/40 sizing
     slips in. **Note: 24 and 48 are on-ladder (legal Body / Title tiers), not
     errors.**
   - **No drop shadows** (R12): scans `.slide` selectors for `box-shadow`
     declarations. Recognises glow rings (`0 0 0 Npx ...`) and `inset`
     shadows as allowed; flags any real drop shadow with non-zero offset.
     Opt out with `/* allow:drop-shadow */` or `data-allow-drop-shadow`.
   - **`data-decor` token validity** (R38): every token inside a slide's
     `data-decor` must come from the ship list (`violet-glow / blue-glow /
     mix-glow / teal-glow / orange-spark / aurora / grain / topo /
     flower-bg / section-bg / photo-bg`). Misspellings produce hard fail.
   - **Hex palette** (R10): warns when slide markup contains hex values
     outside the brand `--fs-*` palette. (SVG decoration + inlined framework
     CSS are excluded from this scan.)
   - **White / dim text** (R-WHITE-TEXT / R-VIS-DIM-TEXT): semantic body text
     on dark slides must be `#fff`, never low-opacity grey. Opt out true
     chrome with `/* allow:white-opacity */` / `data-allow-white-opacity`
     (source) or `data-allow-dim-text` (computed).
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
   - **Content header** (R56): a content-page `.header` carries only `<h2>` —
     no eyebrow, no stacked subtitle.
   - **UI mocks as HTML** (UI1): warns on any `<img>` in slide content that
     isn't a known brand asset or `data:` URI.
   - **Cyan as slide-accent** (R49): rejects `data-accent="cyan"` on
     `.slide` — cyan is inline-word-highlight only.
   - **Visual geometry** (R-OVERFLOW / R-OVERLAP / R-VIS-TIER / R-VIS-* …):
     overflow, sibling collisions, computed font-size on the 4-tier ladder,
     title-gap, balance, focal, dead rules — see the summary table above.
     These need Chromium; `--no-visual` skips them, and they self-skip when
     playwright isn't installed.

   Pass `--strict` to promote warnings (mono logos, off-palette hex) into
   errors. Default mode lets warnings pass for an in-progress deck; strict
   mode is the pre-delivery gate.

2. **Treat exit-1 as a delivery blocker.** If the validator reports any
   error, fix it. Don't paper over it by editing the engine. The check is
   conservative — every flag is a real 规范 violation, not noise.

3. **Run the validator after EVERY rebuild.** The normal path is
   `render-deck.py`, which calls the validator as a built-in gate. If you
   validate a standalone deck by hand, do it in the same shell command as
   the render so regression detection is automatic — a CSS edit that
   introduces a 20 px font in a per-page selector is caught immediately,
   not when a customer flags it on a printed handout.

4. **Some checks still require a human eye.** Title-baseline ↔ logo-center
   alignment, ZH > EN balance, atmospheric "feel", and glow-vs-content
   density — the validator can't judge these. Open the deck at 1920×1080,
   1280×720, and 380×680 and look. Then ship.

---

