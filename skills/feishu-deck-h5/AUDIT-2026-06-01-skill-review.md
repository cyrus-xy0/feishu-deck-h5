# AUDIT · feishu-deck-h5 全技能 code review — 2026-06-01

> 全技能源码审计(非单 deck)。多 agent workflow(28 子系统深审 + 6 跨文件契约追踪)→ 对抗式三态验证 → 三镜头查漏 → 4 个空结果单元重跑 → 人工复现头号 bug。
> 候选 184 →(去重)**173 工单 F-77..F-249**:🔴 高 23 · 🟡 中 56 · ⚪ 低 94。
> 工具产物:workflow `wf_112af030-c7f`(task `wkc59ueqr`)。

## 修复进度(2026-06-02 · 分批 commit,不 push · 25 批)
**全部三类(高/中/低)都走了一遍。** 测试:`231 passed, 0 failed`(原 226 + 5 个新回归测试)。每批 `py_compile`/`node --check` + 复现/集成测试。`[需视觉抽查]` 标记的 JS/CSS 运行时改动须在浏览器里抽查。

### ✅ 已修复(按域)
- **模板引擎族**:R1(花括号崩)/R2(custom_css 丢)+ `scope_selectors` `[data-page]` 融合 + `_css_utils` `_match_brace`(string/comment-aware)+ 5 处 exact-`class="slide"` 正则
- **validate-deck**:R3(cols 误拒)+ R-KEY↔schema 对齐 + data 类型守卫 + pattern `fullmatch`(尾换行洞)
- **资产扫描族**:lift `<img src>`(#9)/key 去重(#8)/appended==0;deck-cli paste 裸图(#6);copy-assets 仓内 run 本地化(#18)+ 路径穿越守卫
- **校验器正确性**:DEAD-ANIM(#14)/R12 多层/空头区误报/raw-looks(卡片·viewBox·箭头)/R13·undefined-var·font-size 精度/iframe vouch/inline_linked 顺序/视觉报告 try 容错/死代码/yaml 重复键
- **check-only** D/E 关切(#78)· **bak-and-log** 删除守卫(#77)· **import-html** key slug + 渲染失败传播(#10/#11)+ slides 守卫
- **edit-mode**:结构/XSS/保存失败/快捷键(#80/#81/#83/#724)+ 拖拽回灌侧栏(#246)+ data-mode(#305)+ drag key(#228)+ undo 恢复 scale/侧栏(#82 实际故障)
- **render**:`--inline` 丢框架图(#3)+ script defer · **migrate** `@keyframes`(#13)+ 幂等 · **CSS** 双箭头(#84)
- **feishu-deck.js**:`centerSlideInCanvas` 纳入绝对定位内容带(R-VIS-BAND-COLLIDE,最窄改法)+ 移动端 hash 同步(#914)+ maybeBalance abort 守卫 + #0 hash 归一
- **deck-cli**:锁/备份碰撞/clone 位置/lint/set-variant 补字段(#309)· **reskin** font-family/box-shadow/bg-neutralize/cyan
- **杂项**:sync-index 回灌拖拽重排 · schema `additionalProperties`+lift_origin · Playwright 故障不阻断 · text-swap 备份不覆盖 · check-distribution 死带/Infinity/--slide 0/配对 · reconcile-reflow `_probe` 对齐 · log-tool transcript/sev · reconcile/clean-lifted 正则 · rebundle 路径守卫 · shell(finalize/new-run/build/migrate-shared/reskin.sh/package-skill)· README/extract/story-case

### ⚠️ 改了→回滚(亲测会坏)
- `_validate_common` 伪造 framework 标记(nonce):实现后挂 2 个测试(夹具手搓 `data-source="framework"`),破坏既有约定;洞本质是作者藏自己的 CSS=自伤。已干净回滚。

### 🚫 查证后确认不改(改了更糟 / moot / 根本限制 · 附理由)
- `R-ESC-HTML` 短标签:正则本就要求 `&lt;`+标签名间无空格,数学比较不匹配,误报近乎零;建议的「要求属性」会漏 `<b>word</b>` 真 bug。
- preflight `pipefail`:实测无 `|head/tail/grep -q` 早关管道,pipefail 空操作;`-u` 进硬闸门会因可选未设变量假失败阻断全技能。
- 视频进场重播:本有 `data-no-restart` opt-out。
- `#869` 移动监听:`wire()` 有幂等守卫(只接一次),静态 deck 无 teardown 调用方,加 AbortController=无消费者死机器。
- schema 单版式禁 variant:多版式 variant enum **已存在**;禁单版式 stray variant 会拒存量 deck(renderer 本就忽略)。
- migrate 重复 `_page_to_key`:两份**非**字节相同(`_FRAME_OPEN` vs 内联正则),合并=行为变更风险、无 bug。
- lift 锁序:孤儿资产文件无害;事务化拷贝过重。
- deck-cli 锁 mtime 精度:粗 mtime 文件系统根本限制,content-hash/size 改动过广。
- `feishu-deck.css` eyebrow 死块/overflow 泄漏/标题截断:纯 CSS 视觉、有回归风险、低价值。
- `_renumber_text_ids`:`data-text-id` 系统已废弃、惰性无害。

## 测试基线
- 审计当时(`raw-first-stance` @ `1a14115`):`221 passed, 1 FAILED`(`R-RAW-LOOKS-SCHEMA` 未写进 `references/validator-rules.md`)。
- 现 `main`(并行 session 合并 raw-first + 3 个新提交后):**`226 passed, 0 failed`**。
  - 🟢 红测试已被并行 session 提交 `7bce431` 修掉(validator-rules.md 文档补齐)。
  - 🟢 `8eb0782` 已修 lift-slides `--shake` 的 3 个 bug 类(`extract_one` 漏 `</div>`、F-40 锚点等)——与本审计的 lift 工单**不同**,需各自核对。

## 人工已复现(最高置信 · 工单 ID 见下表,按文件名排序故非 F-77/78/79)
- **R1 · `render-deck.py render_template`**:raw 先替换、safe 再重扫整串 → raw 页/enricher 注入内容里出现字面双花括号占位 → SystemExit 渲染崩。复现 exit=1(main 仍复现)。
- **R2 · `render-deck.py _inject_custom_css`**:正则把 class 钉死 "slide",`story-case`/`replica` 的 `class="slide story-case"` / `"slide page-replica"` 不匹配 → custom_css 静默丢失。模板已确认。
- **R3 · `validate-deck.py`**:cols 默认 4 + render `--strict` 升 err → 3/5/6 步 flow 无显式 `cols` 渲染被拒。复现 FAIL。

## 根因族(一次修一批)
1. **模板引擎族** — `.slide` 按 class 全等匹配 + raw→safe 双趟重扫 + `scope_selectors` 只换 token 不融合。命中 render-deck、`_css_utils.scope_selectors`、sync-index、migrate、import、`_validate_audits._lifted_slide_keys`、所有 enricher `*_html` 槽、flow-tree 模板。修引擎一处:`.slide` 改按 `data-slide-key` 定位;raw 注入哨兵保护避开 safe 重扫;`scope_selectors` 对 `[data-page=N] .slide` 融合。
2. **资产扫描族** — 各处自写、只认 `url()`。命中 lift step4(`<img src>`)、deck-cli paste(裸图字段)、copy-assets(仓内 run 的 `../../../assets/`)。抽共享扫描器覆盖 `<img/source/video/iframe src>`、`url()`、`<link/script href>` + 裸图字段。
3. **`--strict` 把信息性 warn 升成渲染拦截** — cols 默认 4。validate-deck 只在显式不符时 warn。
4. **失败被吞 / 坏状态报成功** — import re-render 吞错 exit 0、render 先写 index.html 再过 HTML 闸、多写者无写后复校。三道闸"render 必须失败"契约要传播非零 + 回滚。
5. **交付/便携丢 Lark 视觉** — `--inline` 不内联框架 `--fs-asset-* url()`、copy-assets 仓内 run 不本地化 → zip/搬运后丢背景+logo。
6. **可视化编辑器 round-trip 完整性**(每份交付 deck 默认带) — 容器 contenteditable 毁结构、富文本粘贴 XSS、undo/save 作用域不一、保存失败静默。
7. **乐观锁不一致 / 写者绕过** — render `--renumber`、lift、apply-text-pairs 写 deck.json 缺锁或缺写后复校;三处 mtime 精度+`--force`+删除竞态不一致。
8. **备份守卫会删最新备份** — `bak-and-log` 按 `st_mtime` 排序,但 `copy2` 保留源 mtime → 删页前最后防线可能删掉最新备份。

---

## 🔴 高危工单(F-77..)
| ID | 文件:行 | 摘要 | 修法 | 状态 |
|---|---|---|---|---|
| F-77 | `assets/bak-and-log.py:114` | prune sorts by st_mtime but copy2 preserves SOURCE mtime -> backups share mtime -> can delete NEWEST backup | (see re-run agent report) | ☐ |
| F-78 | `assets/check-only.py:87-91, 477-491` | Gate report's CONCERN_ORDER only has buckets A/B/C, but business-rules.yaml now assigns concerns D (放映功能不全) and E (文件偏大可能卡顿). Any D/E error is misrouted to the 'yaml 未覆盖' | Extend CONCERN_ORDER to include 'D · 放映功能不全' and 'E · 文件偏大可能卡顿' (matching the yaml exactly), or derive the bucket list dynamically from the distinct concern values presen | ☐ |
| F-79 | `assets/copy-assets.py:51-70, 316-387` | copy-assets never localizes framework refs when the run dir lives INSIDE the skill (skills/feishu-deck-h5/runs/<ts>/output/) — RX_SKILL only matches the literal `skills/f | Drop the literal-skill-name assumption. Either (a) make render-deck always emit the canonical `…/skills/feishu-deck-h5/assets/…` form (don't let os.path.relpath collapse  | ☐ |
| F-80 | `assets/edit-mode/deck-edit-mode.js:30` | getTextLeaves makes parent-of-textnode editable incl containers w/ child elements -> editing/paste destroys child structure on save | (see re-run agent report) | ☐ |
| F-81 | `assets/edit-mode/deck-edit-mode.js:91` | rich-HTML paste into contenteditable persisted verbatim on save -> stored XSS in delivered deck | (see re-run agent report) | ☐ |
| F-82 | `assets/edit-mode/deck-edit-mode.js:261` | undoStack snapshots deck.innerHTML but save serializes documentElement -> undo/save divergence + lost inline scale/state | (see re-run agent report) | ☐ |
| F-83 | `assets/edit-mode/deck-edit-mode.js:526` | FS write throw after picker success -> silent download fallback w/ false 'unsupported' msg, possibly truncated file | (see re-run agent report) | ☐ |
| F-84 | `assets/feishu-deck.css:1132-1137, 3315-3327` | Two competing ::after arrow definitions on process steps MERGE on every non-last step, producing a garbled glyph instead of one clean arrow. | Delete the stale rule at lines 1132-1137 (and its vertical-variant hide at 2326-2328 which only existed to suppress that old chevron). Keep only the 3315 clip-path arrow  | ☐ |
| F-85 | `assets/feishu-deck.js:188` | centerSlideInCanvas content-union skips position:absolute -> abs content bands overlap title (R-VIS-BAND-COLLIDE root) | (see re-run agent report) | ☐ |
| F-86 | `assets/lift-slides.py:448-456` | Framework asset path-rewrite (step 4) only rewrites CSS `url(...)`, never `<img src>` — the exact F-76 gap that step 5 fixed for input/ but was NOT applied to framework r | Rewrite framework/shared refs by scanning with _ASSET_REF_PATTERNS (same approach as the F-76 input/ fix at step 5), or run an attribute-aware rewrite for `src=`/`href=`  | ☐ |
| F-87 | `assets/lift-slides.py:618-643` | lift appends slides with the source data-slide-key verbatim and NEVER de-collides against the destination deck (or against other frames lifted in the same run); a collidi | Before appending, gather `existing = {s.get('key') for s in deck['slides']}` and de-collide each lifted key with the same `while f'{requested}-{i}' in existing: i+=1` loo | ☐ |
| F-88 | `assets/visual-audit.js:1987` | R-VIS-DEAD-ANIM splits a rule's selectorText on raw ',', so commas inside :is()/:not()/:has()/[attr="a,b"] shatter a valid selector into illegal fragments → false 'parse- | Reuse the same depth-aware splitter the DEAD-RULE pass already has. Either hoist _splitSelectorList to the top-level helper scope and call it from _checkSel, or replace t | ☐ |
| F-89 | `deck-json/deck-cli.py:485-512` | paste's _copy_slide_assets only copies input/ and prototypes/ refs; bare/relative image paths (scene.png, page-01.jpg, ./scene.png, assets/..) used by image-text / replic | Scan ALL local asset refs, not just input/ + prototypes/. Reuse the same patterns render-deck/lift-slides use: lift-slides.py:243 _ASSET_REF_PATTERNS (<img src>, url(), < | ☐ |
| F-90 | `deck-json/import-html-slide.py:1-13, 444-490` | Import never captures the foreign slide's CSS (head <style> / [data-page=NN] rules) into custom_css, so Mode-A imported raw slides render unstyled — directly contradictin | Parse the source file's <style> blocks, collect rules whose selectors match this slide-frame's [data-page=N]/[data-slide-key]/.slide scope, rewrite them scope-free, and s | ☐ |
| F-91 | `deck-json/import-html-slide.py:455-457` | Foreign data-slide-key is copied verbatim into the deck.json `key` field without normalizing to the schema slug pattern, producing an unrenderable deck.json. | Slugify raw_key before use: lower-case, replace [^a-z0-9-]+ with '-', strip leading non-alpha, fall back to 'imported-<ts>' if empty. Apply the same in the Mode-B path. | ☐ |
| F-92 | `deck-json/import-html-slide.py:630-637 (re_render at 493-504)` | A failed re-render is swallowed: import mutates deck.json, re_render prints the error and returns, then main prints 'done' and returns exit 0 — leaving a broken deck.json | Have re_render return proc.returncode (or raise); in main, if Mode A re-render fails, restore the .bak (or at least propagate a non-zero exit and print a loud failure), s | ☐ |
| F-93 | `deck-json/migrate-head-css-to-custom-css.py:24-27,254` | Migrate codemod stores head page-anim rules VERBATIM into custom_css and relies on scope_selectors to fix `[data-page=N]`, but its docstring promise is false for the FRAM | Either fix scope_selectors (finding above) so the verbatim verbatim-store is actually safe, or have collect() apply the same fusion rewrite that extract_head_slide_rules  | ☐ |
| F-94 | `deck-json/migrate-head-css-to-custom-css.py:185-210` | @keyframes living in a head <style> block that has no per-slide selector are never collected, so animations referenced by migrated rules lose their keyframe definition. | Collect @keyframes from ALL non-framework head blocks (a first pass that harvests keyframes regardless of whether the block carries a per-slide selector), then attach the | ☐ |
| F-95 | `deck-json/render-deck.py:184-209` | render_template runs the safe {{ }} pass over the ENTIRE template AFTER raw {{{ }}} substitution, so raw-injected author HTML (raw slide data.html) that contains a litera | Don't re-scan raw-substituted content. Either (a) do the safe pass FIRST then the raw pass, or (b) substitute raw fields with a placeholder sentinel, run the safe pass, t | ☐ |
| F-96 | `deck-json/render-deck.py:1610-1615` | _inject_custom_css regex `<div class="slide"[^>]*>` only matches slides whose class attribute is EXACTLY "slide"; the story-case and replica templates use `class="slide s | Loosen the anchor to allow extra classes: `r'(<div class="slide(?:\s[^"]*)?"[^>]*>)'` (matches `class="slide"` and `class="slide story-case"` but still not `slide-frame`) | ☐ |
| F-97 | `deck-json/render-deck.py:1896-1914` | --inline does NOT inline the framework CSS's own background images. feishu-deck.css references lark-cover-bg.jpg/lark-logo.png/etc. via `--fs-asset-*: url("...")` custom  | After inlining stylesheets, run a generic `url(...)` rewrite over the whole document (not just `background-image:`), resolving each ref relative to its ORIGINAL styleshee | ☐ |
| F-98 | `deck-json/templates/content-3up.fragment.html:8,10,12` | All enricher-built raw {{{ *_html }}} slots (cards_html / lede_html / body_blocks_html, and equally quadrants_html, bars_html, footnote_html, branches_html, scene_html, c | Fix at the engine: make _esc_br also escape braces (e.g. replace '{' '}' with entity refs or zero-width-safe sentinels) for text destined for raw slots, OR perform raw+sa | ☐ |
| F-99 | `deck-json/validate-deck.py:262-274` | flow/timeline & flow/process cols-mismatch warning fires on the schema DEFAULT (4) when author omits the optional `cols` field, and render-deck always runs validate-deck  | Only warn when `cols` is EXPLICITLY present and mismatched: `if 'cols' in data and data['cols'] != len(...)`. Do not synthesize the default 4 and then compare it against  | ☐ |

## 🟡 中危工单
| ID | 文件:行 | 摘要 | 状态 |
|---|---|---|---|
| F-100 | `assets/_validate_audits.py:110-122` | _lifted_slide_keys regex `<div class="slide"[^>]*>` only matches slides whose class is EXACTLY "slide"; lifted story-case (`class="slide story-case"`) and replica (`class="slide page-re | ☐ |
| F-101 | `assets/_validate_audits.py:491` | audit_no_drop_shadows judges multi-layer box-shadow by FIRST layer only -> R12 bypass via glow-ring/inset prefix | ☐ |
| F-102 | `assets/_validate_audits.py:1428` | audit_empty_header_zone hide_pat matches a CHILD/SIBLING of .header -> false R-EMPTY-HEADER-ZONE | ☐ |
| F-103 | `assets/_validate_common.py:157-176` | _iter_style_blocks trusts a string-substring `data-source="framework"` to decide framework-vs-author CSS; a layout:"raw" slide can FORGE that marker in its verbatim data.html and bypass | ☐ |
| F-104 | `assets/bak-and-log.py:56` | same-second collision .N suffix ordering lost in mtime sort | ☐ |
| F-105 | `assets/bak-and-log.py:84` | prepend_changes_md inserts after first ambiguous '---\n\n' -> can splice into a prior entry | ☐ |
| F-106 | `assets/bak-and-log.sh:10` | only set -e (no -uo pipefail); cd in $() failure not propagated -> empty HERE | ☐ |
| F-107 | `assets/check-distribution.py:228-235` | L2-DEADBAND median miscompute: for exactly 2 gaps the 'median' equals the max, so the dead-band check can never fire — silently missing the canonical 3-block deadband case. | ☐ |
| F-108 | `assets/copy-assets.py:24-27, 585-589` | Docstring/console claim 'zip / Finder-compress / IM-upload follow the symlink and embed real files' is false for macOS Finder Compress (ditto): it preserves output/assets/shared as a sy | ☐ |
| F-109 | `assets/copy-assets.py:68-70` | RX_LOCAL_ASSET (and RX_SKILL/RX_INPUT/RX_LOCAL_INPUT) lack a left boundary before `assets/`/`input/`; a path like `myassets/foo.png` matches the `assets/foo.png` substring and can be co | ☐ |
| F-110 | `assets/copy-assets.py:235-249` | replace_skill computes target/origin from regex `rest` with no .resolve()+is_relative_to(out_dir) guard — `assets/../../../...` escapes output/ on both read and write | ☐ |
| F-111 | `assets/copy-assets.py:255-279` | replace_input has no is_relative_to(out_dir) guard — an `input/../../..` ref escapes the run, reads an arbitrary file and writes it OUTSIDE output/ | ☐ |
| F-112 | `assets/edit-mode/deck-edit-mode.js:246` | frame drag-reorder doesn't rebuildSidebar/renumber; keyless slide -> canvas/sidebar order desync | ☐ |
| F-113 | `assets/edit-mode/deck-edit-mode.js:305` | buildSavedHTML data-mode restoration gated on lifecycle var prevDeckMode -> bakes wrong mode when save() called outside edit mode | ☐ |
| F-114 | `assets/edit-mode/deck-edit-mode.js:724` | Cmd-S keys off lowercase 's' (CapsLock 'S' misses); no isComposing guard; nav swallow on read-only viewers | ☐ |
| F-115 | `assets/feishu-deck.css:3579-3582` | The 2026-05-30 sweep sets process steps to `align-self: center`, making cards content-height (unequal), which mis-aligns the between-card arrows that are pinned to each step's own `top: | ☐ |
| F-116 | `assets/feishu-deck.js:522` | maybeBalance/centerSlideInCanvas deferred rAF/Promise/setTimeout run after abort() -> cross-lifecycle layout mutation | ☐ |
| F-117 | `assets/feishu-deck.js:692` | syncFrameMedia resets currentTime=0 + replays autoplay video with sound on EVERY slide entry | ☐ |
| F-118 | `assets/feishu-deck.js:869` | mobile-patch IIFE adds 4+ listeners with no {signal}/destroy -> leak + violates P53 | ☐ |
| F-119 | `assets/feishu-deck.js:914` | mobile setMode/go bypass goTo -> hash + progress + updateUI desync on mobile nav | ☐ |
| F-120 | `assets/lift-slides.py:452-454` | The `assets/lark-*` framework rewrite uses a hardcoded 6-filename list, but `_classify_asset_ref` classifies ANY `assets/lark-*` as "framework" via regex. lark-* files not in the list ( | ☐ |
| F-121 | `assets/lift-slides.py:591-605` | When EVERY requested frame is out of range or fails extraction (appended==0), lift still rewrites deck.json and main() returns exit 0 — a caller/workflow sees success with nothing lifte | ☐ |
| F-122 | `assets/lift-slides.py:606-621, 706-716` | Asset copies (input/, prototypes/) happen DURING the per-frame loop, BEFORE the optimistic-lock check; on lock failure the code sys.exit(4) leaving orphaned files in the destination dir | ☐ |
| F-123 | `assets/lift-slides.py:626-651` | lift-slides appends the lifted slide with the source key VERBATIM (no de-collision), diverging from deck-cli paste which auto-suffixes; on a key collision the recovered head-CSS (scoped | ☐ |
| F-124 | `assets/lift-slides.py:706-718` | lift-slides writes the destination deck.json (line 715) with NO post-write schema revalidation — it never invokes validate-deck.py — unlike deck-cli.write_deck_with_validation (validate | ☐ |
| F-125 | `assets/rebundle-import.py:60-67` | Linked-runtime swap writes to `deck.parent / rel` with no containment check, so a relative src like '../../../skills/feishu-deck-h5/assets/feishu-deck.js' (the shell template's own form | ☐ |
| F-126 | `assets/reskin.py:99-132` | Cyan-redirect short-circuit (distance<60 to cyan -> --fs-blue) runs BEFORE the nearest-brand-color search, so a legitimate brand teal that happens to sit closer to cyan than 60 is wrong | ☐ |
| F-127 | `assets/reskin.py:1130-1132` | drop_foreign_chrome_rules background-neutralize uses bare substring `any(s in sel ...)` with subs ['.slide','body'], over-matching .card-body / .body-text / .message-body / tbody / .sli | ☐ |
| F-128 | `assets/reskin.py:1326-1336` | source_font_family capture regex `font-family\s*:\s*([^;]+);` requires a trailing ';' and over-runs the closing '}' when font-family is the last declaration in body{} — corrupts the emi | ☐ |
| F-129 | `assets/reskin.sh:106-109` | Preflight is run with all output discarded and only its exit code checked, so a PREFLIGHT BOOTSTRAPPED result (RO mount mirrored to a workspace) is silently treated as plain success — r | ☐ |
| F-130 | `assets/validate.py:225-230` | When the user explicitly requests visual audits (render-deck --visual → validate.py without --no-visual), a Playwright launch/navigation failure downgrades to a regular WARNING (iss.war | ☐ |
| F-131 | `assets/validate.py:226-230` | A Playwright runtime failure emits a promotable iss.warn('R-VISUAL'), so under --strict / --gate ingest an environment glitch (flaky Chromium launch, page timeout) becomes a hard blocki | ☐ |
| F-132 | `assets/visual-audit.js:1916-1921` | R-VIS-SHORT-LABEL-FLOOR exempts a small label if ANY ancestor satisfies _isMediaBox, which matches any container holding a descendant <img> — so all sub-18px text in any image-bearing c | ☐ |
| F-133 | `deck-json/_css_utils.py:34-85, 142-212` | Both `iter_css_rules` and `_scope_block` are brace-counters that ignore CSS string literals, so a `{` or `}` inside a quoted value (e.g. `content:"}"`) corrupts parsing. | ☐ |
| F-134 | `deck-json/_css_utils.py:130-139` | scope_selectors lacks the FRAME-level `[data-page=N] .slide` fusion that lift-slides.extract_head_slide_rules has, so the SAME legacy page-anim rule scopes correctly via --shake but lan | ☐ |
| F-135 | `deck-json/apply-text-pairs.py:105-114` | Replacements are applied sequentially to the running string, so cascading find/replace pairs double-substitute and miss-counting is order-dependent (non-deterministic w.r.t. pair order) | ☐ |
| F-136 | `deck-json/apply-text-pairs.py:147-148` | Backup filename is a FIXED name with no timestamp (.json.bak-pre-textswap), so a second text-swap run overwrites the only backup of the pre-swap state, and the backup is captured by RE- | ☐ |
| F-137 | `deck-json/clean-lifted-css.py:101-103` | _INJECTED_FRAME_PREFIX lookahead `(?:to/from/\d+(?:\.\d+)?%)\b` puts `\b` AFTER the `%`; since `%` is a non-word char and a normal keyframe selector is followed by space/`{` (also non-w | ☐ |
| F-138 | `deck-json/deck-cli.py:309-347` | set-variant drops now-incompatible data fields then immediately writes with --strict validation, so any variant switch that leaves required fields of the NEW variant unfilled is fully r | ☐ |
| F-139 | `deck-json/deck-cli.py:433-434` | cmd_clone never validates the POSITION argument (every other structural op does), so out-of-range / 0 / negative positions are silently mishandled instead of rejected | ☐ |
| F-140 | `deck-json/deck-cli.py:493-500` | paste asset copy de-collides the slide KEY but never de-collides asset FILENAMES, and the mtime guard reports a copy as done even when it silently keeps a different existing dest file | ☐ |
| F-141 | `deck-json/deck-schema.json:76-176` | The slide schema places no constraint on `variant` for single-variant layouts (cover/agenda/section/quote/image-text/table/end/replica/raw/iframe-embed/logo-wall/arch-stack); a spurious | ☐ |
| F-142 | `deck-json/migrate-head-css-to-custom-css.py:79-88,165-172` | The [data-page="N"] -> slide-key mapping is dead for any deck re-rendered by the current renderer, which never emits data-page on .slide; such rules become unattributable orphans contra | ☐ |
| F-143 | `deck-json/reconcile-lifted.py:210` | `_FONT_SHORTHAND_RE` (`\bfont:`) false-matches CSS custom properties and vendor-ish hyphenated tokens, so reconcile silently rewrites the px value of a `--*-font:` variable. | ☐ |
| F-144 | `deck-json/render-deck.py:1428-1432` | _enrich_flow_swim collapses milestones into a dict keyed by quarter (`milestones_by_q[q] = (mi, ms)`); two milestones in the same lane sharing the same quarter index silently overwrite  | ☐ |
| F-145 | `deck-json/render-deck.py:1733-1747` | render-deck --renumber writes deck.json back to disk with NO optimistic-lock (mtime) check — the only deck.json writer in the toolchain that bypasses the F-48/F-53 concurrency guard tha | ☐ |
| F-146 | `deck-json/render-deck.py:1810-1854` | render-deck overwrites output/index.html unconditionally at line 1811 BEFORE the HTML validate gate (line 1838); a render that then fails the gate has already clobbered the previously-g | ☐ |
| F-147 | `deck-json/render-deck.py:1900-1903` | _inline_script regex `<script\s+src="([^"]+)"></script>` cannot match the shell's deferred edit-mode script `<script src="..." defer></script>`, so deck-edit-mode.js is left as a dangli | ☐ |
| F-148 | `deck-json/sync-index-to-deck.py:80-90` | extract_slide_inner depth-counts <div>/</div> over raw slide HTML without masking <style>/<script>/comment regions, so a raw slide whose data.html contains a literal '</div>' or '<div'  | ☐ |
| F-149 | `deck-json/sync-index-to-deck.py:135-174` | sync-index-to-deck reconciles by data-slide-key in deck.json order and NEVER reorders deck.json — so edit-mode drag-reorder (which only writes index.html) is silently discarded on the n | ☐ |
| F-150 | `deck-json/templates/flow-tree.fragment.html:9` | root.question is the only direct deck.json data field among these fragments rendered RAW ({{{ }}}); all sibling fields (branch title, leaves, matrix titles, 3up body, story-case beats)  | ☐ |
| F-151 | `deck-json/tests/test_chart_enricher.py:34-35` | No test verifies gate-FAILURE propagation: every render-deck test asserts returncode==0, so the triple-gate invariant 'a gate failure must fail the render with non-zero exit and write n | ☐ |
| F-152 | `deck-json/validate-deck.py:249-309` | check_business_rules runs unconditionally even when schema validation already recorded type errors, and assumes well-typed values; non-list table rows / non-dict agenda items / non-stri | ☐ |
| F-153 | `log-tool/deck-log.py:224-228` | `_relevant_transcripts` empty-fallback returns the globally most-recently-modified .jsonl across ALL projects with NO deck-token filter, so render/diagnose can ingest an unrelated sessi | ☐ |
| F-154 | `log-tool/deck-log.py:440-450` | `snapshot --slide N` re-screenshots into the latest version dir but the journal version event may point that slide's png at an OLDER (reused) dir, so the refresh is silently dropped fro | ☐ |
| F-155 | `tests/regression-fixtures.yaml:37, 53, 69, 83, 99, 116, 135` | Every regression-fixture deck points at git-ignored `runs/2026...` output that does not exist on a fresh clone or CI, so the entire historical-bug regression suite fails 100% (or is nev | ☐ |

## ⚪ 低危工单
| ID | 文件:行 | 摘要 | 状态 |
|---|---|---|---|
| F-156 | `assets/_validate_audits.py:65-72` | audit_titles_one_line (R13) over-matches hyphenated compound classes like `hero-title` / `title-en` because `\btitle\b` matches the `title` token inside them. | ☐ |
| F-157 | `assets/_validate_audits.py:106` | audit_copy_rules has a duplicated identical condition: `'???' in text or '???' in text` — the second ASCII `???` check is dead code. | ☐ |
| F-158 | `assets/_validate_audits.py:185-189` | audit_font_sizes (R06) selector gate uses bare substring matches (`.col`, `.cell`) that also match unrelated classes like `.color-box`, potentially producing false R06 errors on non-con | ☐ |
| F-159 | `assets/_validate_audits.py:258` | audit_font_sizes inline-style path calls _lev('') so a lifted slide's inline sub-floor font-size is never downgraded to a warning, contradicting the documented 'LIFTED → WARN' policy. | ☐ |
| F-160 | `assets/_validate_audits.py:384` | audit_undefined_css_vars treats `--name:` appearing inside a CSS string/content value as a real custom-property definition, masking genuinely-undefined var() references. | ☐ |
| F-161 | `assets/_validate_audits.py:1589` | audit_ui_mocks_are_html iframe branch uses iss.warn not _lev -> vouched iframe promoted under --strict | ☐ |
| F-162 | `assets/_validate_audits.py:2024` | audit_raw_looks_schema icon detect requires exact viewBox tuple -> under-fires on 32/48 icons | ☐ |
| F-163 | `assets/_validate_audits.py:2037` | audit_raw_looks_schema treats any arrow glyph in body copy as flow signal -> under-fires | ☐ |
| F-164 | `assets/_validate_audits.py:2159` | audit_escaped_html branch A false-positives on single-letter escaped tags <p>/<b>/<i> -> hard R-ESC-HTML err | ☐ |
| F-165 | `assets/bak-and-log.py:63` | 99-collision cap fails with NO backup taken right before destructive op | ☐ |
| F-166 | `assets/bak-and-log.py:101-118` | prune_old_baks sorts backups by st_mtime, but each backup is a shutil.copy2 of the source (copy2 preserves the SOURCE's mtime), so all backups of an unchanged source share an identical  | ☐ |
| F-167 | `assets/bak-and-log.py:143` | prune has no error handling; concurrent unlink -> uncaught traceback after backup succeeded | ☐ |
| F-168 | `assets/bak-and-log.py:155` | dir_label uses CWD-relative path -> unstable header label | ☐ |
| F-169 | `assets/business-rules.yaml:32-39 and 234-240` | Duplicate mapping key 'R-OVERFLOW' defined twice; PyYAML safe_load silently keeps the second (shorter, 1-step fix) and discards the first (richer 3-step fix). check-rule-coverage cannot | ☐ |
| F-170 | `assets/check-distribution.py:49-62` | contentUnion excludes only the SVG/svg ROOT as decoration but still iterates SVG descendants, so decorative SVG <text> (chart axes, watermark text) inflates the measured content union. | ☐ |
| F-171 | `assets/check-distribution.py:182-183` | --json can emit the invalid JSON token `Infinity`/`NaN` when a measured container has zero width or height. | ☐ |
| F-172 | `assets/check-distribution.py:371` | `if args.slide:` is a falsy-zero guard; `--slide 0` is treated as 'no filter' and prints all slides instead of an empty/invalid selection. | ☐ |
| F-173 | `assets/check-distribution.py:391-395` | before→after box table pairs boxes by positional index, which mismatches when --fix/--css changes which elements qualify as framed boxes or their ordering. | ☐ |
| F-174 | `assets/check-only.py:20-24, 95, 454, 467` | Pervasive stale '21 条必修规则' claim. The gate keep-set is `c in rules` = ALL business-rules.yaml entries (67), not 21. The PASS message hardcodes '21 条必修规则全部满足' regardless of actual covera | ☐ |
| F-175 | `assets/check-only.py:243, 311-312` | Per-page report harvests labels via a global `data-screen-label` regex over the whole HTML and indexes labels[i-1] by slide number. A raw-page data.html that embeds a stray data-screen- | ☐ |
| F-176 | `assets/check-only.py:379-385, 372` | build_default_report (--by-rule engineer view) reads only iss.errors and iss.warnings, never iss.soft_warnings. All warn_soft advisories are completely invisible in the exact mode meant | ☐ |
| F-177 | `assets/check-only.py:601-602, 635-639` | --strict help text claims it is '与 --gate 互斥' (mutually exclusive with --gate) but nothing enforces it; passing both is silently accepted and --gate wins. | ☐ |
| F-178 | `assets/check-rule-coverage.py:27-48` | Drift detection compares rule-code STRING PRESENCE in source (enumerate_validate_rules regex-scans for emit-site literals) against FAMILIES/yaml — it never checks that the emitting audi | ☐ |
| F-179 | `assets/copy-assets.py:47-53, 316-352` | extra-layouts.css ref is dropped entirely in the inside-skill layout: `../../../deck-json/templates/extra-layouts.css` matches NEITHER RX_SKILL (no `skills/feishu-deck-h5/` segment) NOR | ☐ |
| F-180 | `assets/copy-assets.py:54-56, 71-73` | RX_INPUT and RX_LOCAL_INPUT have no left boundary, so any token ending in `input/` (e.g. user-input/, reinput/) or an external URL containing `/input/` is captured as an input asset ref | ☐ |
| F-181 | `assets/copy-assets.py:239` | Size-equality is used as the 'already copied / up-to-date' check (`target.stat().st_size != origin.stat().st_size`); a same-byte-length content change is never refreshed on re-run | ☐ |
| F-182 | `assets/copy-assets.py:288-308` | Deck-local assets dropped at output/ root (referenced as `./hero.png`) are left at the root, classified `framework`, and excluded from package-deliverable.sh's zip — 404 in the editable | ☐ |
| F-183 | `assets/copy-assets.py:459-505` | CSS url() asset chaser only runs on .css files, so runtime asset references inside copied .js (or extensionless url targets) are never followed; `url(font)` (no dot, no slash) is also s | ☐ |
| F-184 | `assets/edit-mode/deck-edit-mode.js:119` | IntersectionObserver tracks stale detached frames after undo/drag until manual refresh | ☐ |
| F-185 | `assets/edit-mode/deck-edit-mode.js:228` | onDragStart reads `dragSrc.dataset.slideKey` but dragSrc is the .slide-frame, and data-slide-key is emitted on the inner .slide, not the frame — so the dataTransfer payload is always th | ☐ |
| F-186 | `assets/feishu-deck.css:1440-1448, 1515` | `.slide .header .eyebrow` is fully styled and `display:block`-ed at 1444 then unconditionally `display:none`-d at the same specificity later (1515); the eyebrow can never appear in a he | ☐ |
| F-187 | `assets/feishu-deck.css:1449-1463` | Header titles use `white-space: nowrap` + `overflow: hidden; text-overflow: ellipsis`, so an over-long author title is silently truncated to an ellipsis with no warning. | ☐ |
| F-188 | `assets/feishu-deck.css:1769-1772` | `overflow-x: hidden` from the generic `.slide .pills` overflow defense leaks onto section-layout pills (which intentionally wrap), clipping wrapped pill rows on the horizontal axis is h | ☐ |
| F-189 | `assets/feishu-deck.js:376` | mobile tap-to-enlarge wiring only at load -> absent when viewport narrowed from desktop | ☐ |
| F-190 | `assets/feishu-deck.js:491` | #0 resolves to slide 1 and out-of-range numeric hash clamps but keeps stale hash | ☐ |
| F-191 | `assets/finalize.sh:48` | `--name) NAME="$2"` (and the same in package-deliverable.sh line 27) dereferences $2 under `set -u`; if `--name` is passed as the final argument with no value, the user gets a raw `"$2" | ☐ |
| F-192 | `assets/finalize.sh:82-94` | run_step prints the WRONG exit code — `$?` after the `if "$@"` test is always 0, so the diagnostic always says "(exit 0)" | ☐ |
| F-193 | `assets/finalize.sh:102-115` | finalize.sh's validate gate is non-strict by default and only validates the HTML — it never re-checks the deck.json schema and won't catch a regression that is warn-only (would fail ren | ☐ |
| F-194 | `assets/grow-box-fit.py:130-141` | The grow verdict estimates height growth linearly (elH*(FLOOR/px-1)) and only measures slack below the element, so width-constrained text that REWRAPS to more lines when enlarged to 24p | ☐ |
| F-195 | `assets/grow-box-fit.py:153-162 (_normalize_sel), 175-201 (_apply_changes)` | Selector normalization unifies quotes but not attribute-value quoting state, so a CSSOM-quoted selectorText ([data-page="04"]) won't match a source selector written unquoted ([data-page | ☐ |
| F-196 | `assets/migrate-shared-to-symlink.sh:23` | REPO_ROOT is hardcoded as `$SCRIPT_DIR/../../..` (assumes X/skills/feishu-deck-h5/assets/ depth), but new-run.sh roots runs/ at the git toplevel (or SKILL_ROOT when non-git). The two di | ☐ |
| F-197 | `assets/migrate-shared-to-symlink.sh:45` | `size_kb=$(du -sk "$shared" / awk ...)` runs under `set -euo pipefail`; if the shared dir vanishes between the `[[ -d ]]` check and du (TOCTOU with a concurrent run-cleanup) or du hits  | ☐ |
| F-198 | `assets/new-run.sh:67` | `REL_DIR="${RUN_DIR#$RUNS_BASE/}"` uses RUNS_BASE unquoted in the pattern position of `#`, so it is interpreted as a glob pattern; a repo path containing glob metacharacters mis-strips, | ☐ |
| F-199 | `assets/package-deliverable.sh:78-81` | package-deliverable only stages index.html / README / assets/ / manifest / deck.json — it does NOT include deck-local `./` files that copy-assets symlinks into output root (line 305), s | ☐ |
| F-200 | `assets/package-skill.sh:132-143` | --verify runs check-mira.sh against the freshly-staged copy AFTER mirroring; check-mira/preflight write scratch files (the .feishu-deck-h5-preflight-cache from the two-clone scan, plus  | ☐ |
| F-201 | `assets/preflight.sh:37` | preflight.sh uses bare `set -e` (no `pipefail`, no `-u`). The two-clone scan and cache block rely on many pipelines (`head`, `tail`, `stat`, `find / while read`) whose failures are inte | ☐ |
| F-202 | `assets/reskin.py:427-431` | strip_drop_shadows regex `box-shadow\s*:\s*([^;]+);` requires a trailing ';' so a box-shadow that is the last declaration in its block (no ';') is never stripped — R12 drop-shadow leaks | ☐ |
| F-203 | `assets/reskin.py:571-572` | scope_selectors keeps any selector starting with ':root' unscoped — but a foreign `:root{}` block frequently carries non-custom-property declarations (font-size, background, color, etc. | ☐ |
| F-204 | `assets/reskin.py:663-676` | detect_title requires `len(text) >= 4`, which discards short CJK titles (2-3 chars) — common in this Chinese-only framework — falling back to <title> or 'Untitled'. | ☐ |
| F-205 | `assets/reskin.py:1396-1398, 994-1010, 1242-1248` | Large blocks are dead under the current contract: preflight_canvas raises CanvasMismatchError for every source that isn't exactly 1920x1080, so canvas is always (1920,1080) downstream — | ☐ |
| F-206 | `assets/reskin.sh:178-223` | The post-render overflow-check Python heredoc runs under `set -e` (re-enabled at line 165) and is not guarded; a Playwright goto failure (e.g. OUT_DIR path with spaces/`#`/`%` breaking  | ☐ |
| F-207 | `assets/validate.py:238-757` | The visual-report formatting loops use direct dict indexing (entry['h'], entry['offset'], entry['slide_idx'], ...) OUTSIDE the try/except that only wraps the Playwright session — a malf | ☐ |
| F-208 | `assets/validate.py:804-806` | inline_linked's <link> regex requires rel="stylesheet" to appear BEFORE href=; valid HTML with href before rel never matches, so framework CSS is silently not inlined (degrades check-on | ☐ |
| F-209 | `assets/visual-audit.js:116-123` | firstAncestor helper is defined but never called anywhere in the file (dead code). | ☐ |
| F-210 | `assets/visual-audit.js:158-163` | _isFramedBox treats a fully-transparent NON-black border (alpha 0 but non-zero RGB) as a visible border, so it can classify an unframed element as 'framed'. | ☐ |
| F-211 | `assets/visual-audit.js:585-588` | R-VIS-TITLE-POSITION compares headerTop (raw getBoundingClientRect delta, i.e. SCALED px) against the design-px constant 61 without dividing by --fs-scale; correct only because the audi | ☐ |
| F-212 | `assets/visual-audit.js:1841-1844` | R-VIS-CANVAS-CENTER folds empty, childless, text-free, non-media leaves (flow spacers / decorative line divs) into the content-union bbox, skewing the measured vertical center. | ☐ |
| F-213 | `build.sh:63-76` | The inline-asset Python is generated by shell-interpolating `$ROOT` into a single-quoted Python string literal (`ROOT = '$ROOT/assets'`); a skill root path containing a single quote or  | ☐ |
| F-214 | `deck-json/_css_utils.py:132` | The `[data-page=` gate requires the `=`, so a bare presence selector `[data-page]` falls through to the descendant branch and produces a doubly-broken selector with a phantom `.slide` A | ☐ |
| F-215 | `deck-json/_story_case_fit.py:33` | The trailing-ellipsis placeholder pattern `\.\.\.{2,}` requires 4+ literal dots, so a real 3-dot '...' is not matched by that alternative (only the all-dots ^...$ alt catches dot-only s | ☐ |
| F-216 | `deck-json/apply-text-pairs.py:133-152` | apply-text-pairs writes the deck back with NO post-write schema revalidation and no rollback-on-invalid, unlike deck-cli's write_deck_with_validation triple-gate; a find/replace that br | ☐ |
| F-217 | `deck-json/deck-cli.py:129-131, 156-158` | backup_path uses a second-precision timestamp (%Y%m%d-%H%M%S) with no collision suffix, so two writes of the SAME command within one second produce identical .bak-pre-<cmd>-<ts> paths;  | ☐ |
| F-218 | `deck-json/deck-cli.py:145` | Lock check is short-circuited by `and deck_path.exists()`: if a concurrent process DELETES deck.json between read and write, the check is skipped and deck-cli recreates the file, silent | ☐ |
| F-219 | `deck-json/deck-cli.py:147` | All three writers gate the optimistic lock on `abs(cur_mtime - expected_mtime) > 1e-6`, an epsilon far finer than the mtime resolution on FAT/exFAT (2s), many SMB/NFS mounts and some Do | ☐ |
| F-220 | `deck-json/deck-cli.py:498` | asset-copy freshness check uses st_mtime > comparison; clock-skewed or coarse-mtime filesystems (1s granularity, network FS) can leave a stale dest asset in place while reporting it cop | ☐ |
| F-221 | `deck-json/deck-cli.py:564-567, 145-147` | cmd_paste copies source assets into the destination dir (line 567) before cmd_paste returns; the optimistic-lock refusal and the schema-fail rollback in write_deck_with_validation both  | ☐ |
| F-222 | `deck-json/deck-cli.py:571-574` | cmd_paste position uses the falsy-zero guard `pos = args.position if args.position else n+1`, so `paste ... 0` is silently coerced to 'append at end' and then passes the `1 <= pos <= n+ | ☐ |
| F-223 | `deck-json/deck-cli.py:714-715` | lint subcommand declares `--strict` with action=store_true AND default=True, so the flag is a permanent no-op — lint is always strict and there is no way to run a non-strict lint | ☐ |
| F-224 | `deck-json/import-html-slide.py:429-441` | _renumber_text_ids computes the slide ordinal from the raw slides[] index (position+offset+1), but render-deck re-numbers data-text-id using the index among ACTIVE slides (after _disabl | ☐ |
| F-225 | `deck-json/import-html-slide.py:446, 618-619` | Mode A reads deck.json and indexes deck["slides"] without guarding the key, so a deck.json missing the slides array crashes with a bare KeyError/traceback instead of a clean message. | ☐ |
| F-226 | `deck-json/migrate-head-css-to-custom-css.py:242-254` | Running the codemod twice without re-rendering in between appends the same migrated CSS again, duplicating rules in custom_css; idempotency holds only after a re-render removes the head | ☐ |
| F-227 | `deck-json/reconcile-reflow.py:187-195` | `_probe` err-classification for card-overflow diverges from validate.py: it treats any `vertical*` record with `recoverable is False` as err regardless of px, but validate.py only does  | ☐ |
| F-228 | `deck-json/render-deck.py:234-248` | _build_data_attrs routes attribute values (accent/decor/title_style/logo_position/lifted) through _esc_br, which converts \n -> <br>. A newline in any of these emits a literal `<br>` su | ☐ |
| F-229 | `deck-json/render-deck.py:881-886` | image-text bg_style injects user-controlled image.src into a raw `style="{{{ bg_style }}}"` attribute. _esc_br escapes the HTML-attr delimiter (" -> &quot;) so attribute breakout is blo | ☐ |
| F-230 | `deck-json/render-deck.py:1451-1454` | replica.fragment.html omits the `{{{ data_attrs }}}` slot that every other layout emits, so a replica slide's accent/decor/title_style/logo_position AND the `lifted` marker are dropped  | ☐ |
| F-231 | `deck-json/render-deck.py:1668-1673` | With --skip-validate-json, a structurally-malformed deck (missing 'slides' or deck.deck.title) raises an unhandled KeyError instead of a clean exit, after the JSON-load error handling s | ☐ |
| F-232 | `deck-json/render-deck.py:1742-1747` | The --renumber branch writes the mutated deck.json back to disk with NO optimistic-lock (expected_mtime) check and no post-write revalidation/rollback, unlike every other deck.json writ | ☐ |
| F-233 | `deck-json/render-deck.py:1764-1853` | HTML validate gate (step 6) runs BEFORE the HTML is mutated by inline_html / copy-assets (step 7); the delivered index.html is never re-validated, so a passing gate can leave a 'done'-l | ☐ |
| F-234 | `deck-json/sync-index-to-deck.py:72,1611-analog` | extract_slide_inner only matches `<div class="slide"` (exact closing quote), so replica slides rendered as `class="slide page-replica"` are never found and are reported as missing rathe | ☐ |
| F-235 | `deck-json/sync-index-to-deck.py:91-98` | sync-index-to-deck strips and DISCARDS the per-slide data-fs-custom-css block from index.html and never writes it back to slide.custom_css, so post-render edits to a slide's CSS are sil | ☐ |
| F-236 | `deck-json/templates/extra-layouts.css:205-211,246-249` | Duplicate selector '.slide[data-layout="waterfall"] .bar .label' (and .sublabel) defined twice; the second block silently overrides the first block's carefully-commented margin-top:0 wi | ☐ |
| F-237 | `deck-json/tests/README.md:5-12` | README advertises test_render_examples.py and test_editor_schema_parity.py — both files are deleted; the data-text-id reverse-map (editor.js textIdToSlidePath) contract and 'every examp | ☐ |
| F-238 | `deck-json/tests/test_copy_assets_deck_json.py:24-53` | Asset-404 detection is untested: copy-assets tests only assert the happy path (asset exists, gets copied). No test feeds a deck referencing a MISSING asset to assert copy-assets reports | ☐ |
| F-239 | `deck-json/tests/test_deck_cli_smoke.py:24-72` | No test exercises deck-cli's optimistic concurrency lock (F-48) — the core 'refuse write if deck.json changed since read, unless --force' contract has zero coverage. | ☐ |
| F-240 | `deck-json/tests/test_lift_slides.py:55, 70-72, 99-118` | The lift test fixture is built so the source key ('hero') never collides with the destination deck key ('c'), so the documented key-collision bug (lift appends source key verbatim with  | ☐ |
| F-241 | `deck-json/tests/test_render_deck_golden.py:53-58` | Golden-snapshot test auto-bootstraps and PASSES when the snapshot file is absent, so it can never fail on a fresh/missing snapshot — a first-run enricher regression is silently adopted  | ☐ |
| F-242 | `deck-json/validate-deck.py:128-130` | Pattern check uses re.search instead of re.fullmatch, so a slide `key` ending in a newline (or any string whose first line matches) passes the kebab `^[a-z][a-z0-9-]*$` gate and then re | ☐ |
| F-243 | `deck-json/validate-deck.py:276-309` | check_business_rules re-implements the story-case fit-check inline instead of calling the shared check_story_case_fit primitive, re-introducing exactly the drift F-15 single-sourcing wa | ☐ |
| F-244 | `deck-json/validate-deck.py:896 (assets/_validate_audits.py) vs deck-schema.json:82` | The valid-key regex diverges between the JSON gate and the HTML gate: schema/validate-deck require `^[a-z][a-z0-9-]*$` (must start with a letter) but audit_slide_keys accepts `^[a-z0-9] | ☐ |
| F-245 | `extract-from-claude-code.py:222-226` | iter_user_prompts only accepts string `content` and drops every user message whose content is a list-of-blocks, but real user-authored prompts (text block + attachment/image, interrupt  | ☐ |
| F-246 | `log-tool/deck-log.py:268-272` | `extract_turns` start_ts filter only applies when the transcript row HAS a timestamp; rows missing `timestamp` bypass the filter and leak pre-init content into the log | ☐ |
| F-247 | `log-tool/deck-log.py:443-448` | `snapshot --slide N` for a non-existent page returns an empty (not None) shots list, so the user sees "0 张" with no explanation and the page-missing warning is easy to miss | ☐ |
| F-248 | `log-tool/deck-log.py:473` | Off-by-one in severity extraction: `sev = f[1] if len(f) > 2 else ""` should be `len(f) > 1`; a 2-element finding silently loses its severity | ☐ |
| F-249 | `log-tool/deck-log.py:559-562` | Turns are globally re-numbered every render based on the current set of discovered transcripts, so a `summary` event's `n` (and the displayed 回合 number) can attach to the wrong turn onc | ☐ |
| F-250 | `assets/lift-slides.py:493-514 (transform)` | `--shake` inlines framework background rules using `var(--fs-asset-content-bg)` into the slide's data.html. A `url()` carried in a custom property resolves relative to the **document**, not the feishu-deck.css that defines it → `output/lark-content-bg.jpg` 404 → background silently goes black. Schema decks are unaffected (rule stays in the external CSS). Hit live: qingdao #38 lift lost its blue-glow ambient bg; validator PASSes, only caught by eye. **Fix:** `_deref_asset_vars()` rewrites inlined `var(--fs-asset-X)` → `url("assets/<file>")` (the path copy-assets lands brand assets at for linked-local delivery). Covers content/cover/section-bg + logo + slogan. | ✅ |
| F-251 | `assets/lift-slides.py:591-593 (lift)` | Lifting into a NON-existent target deck.json scaffolds `deck:{}` with no `deck.title`, so the FIRST render of a freshly-lifted new deck always fails schema validation (`deck.title required`). The "lift a page into a brand-new deck" flow always stumbles. **Fix:** seed `deck.title` from the source deck `<title>` (fallback = source folder name → "未命名 deck"). | ✅ |
| F-252 | `assets/lift-slides.py:transform/lift loop` | Lifting a foreign page that uses `<img>` for content photos/avatars fails UI1 on every `<img>` at render time (source bypassed the gate; through it = a wall). **Fix (partial):** lift-time **warning** lists the content `<img>` count + the bg-div fix, surfacing it at lift not render. Auto-conversion left as future opt-in (`--photos-as-bg`) — naive img→bg-div collapses imgs whose parent relies on intrinsic size, so it's not safe to apply unconditionally. | ◑ |

---
> **F-250..F-252(2026-06-02)** — 单页 lift→新 deck 实操中发现,见 [[#lift-new-deck-fidelity]] 下方进度节。分支 `fix-lift-new-deck-fidelity`(未合并 main)。与 `8eb0782` 的 `--shake` 三类修复正交。

---
> 修复在 `main` 上分批改 + 分批 commit(不 push),每批改前重读文件(并发 session 安全)、改后跑测试。WONTFIX/by-design 项在对应 commit message 注明理由。

---

## <a name="lift-new-deck-fidelity"></a>F-250..F-252 修复进度(2026-06-02 · 分支 `fix-lift-new-deck-fidelity`,未合并/未 push)

**触发**:用户「把外来青啤 deck `index-fix.html#38`(`ice-tea-5scripts`)lift 成一份**新** deck 的首页」。实操踩出 3 个"lift 到**新建**目标"路径专属缺口 —— 既有 lift 工单(F-40/F-44/F-45/F-75/F-76)都假设粘进**已有** deck,这条全新路径没人走过。三处全在 `assets/lift-slides.py`,与并行大审计(F-77..F-249)及 `8eb0782` 的 `--shake` 三类修复**正交**。

**根因(已逐层坐实于最新 main)**
- **F-250(🔴 静默背景丢失)** — `--shake` 把框架 `.slide{background:#000 var(--fs-asset-content-bg) …}` 内联进该页的 `data.html`。CSS 自定义属性里的 `url()` 由浏览器按**使用它的文档**解析,而非**定义它的 feishu-deck.css**(后者在 `assets/`)→ 解析成 `output/lark-content-bg.jpg`(缺 `assets/`)→ 404 → 背景静默变黑。**纯 schema deck 不受影响**(该规则留在外部 CSS,相对 CSS 解析正确)。实测:青啤 #38 丢了 blue-glow 氛围底;`validate.py` PASS,只能靠眼睛抓(像素对比 top 边 src=(12,17,47) vs lift=(0,0,0))。
- **F-251** — lift 进不存在的目标 → 脚手架 `deck:{}` 无 `title` → 首次 `render-deck.py` 必报 `$.deck required property 'title' missing`。
- **F-252(◑ 部分)** — 外来页用 `<img>` 当头像/照片 → render 时每张挂 UI1(源 deck 当年绕过了闸门)。

**修复(`assets/lift-slides.py` 单文件)**
- F-250:新增 `_deref_asset_vars()` + `_asset_var_filemap()`(从 feishu-deck.css `:root` 解析 `--fs-asset-* → 文件名`),在 `transform()` 末尾把内联的 `var(--fs-asset-X)` 解引用成 `url("assets/<file>")` —— copy-assets 为 linked-local 交付把品牌资产整套落在 `output/assets/`,故该路径正确。覆盖 content/cover/section-bg + logo + slogan。**caveat**:只对 linked-local 交付(默认+交付形态)正确;纯 skill-relative 渲染(无 copy-assets)下原 `var` 本来也 404,故是严格改进非退化。
- F-251:`_source_title()` 用源 deck `<title>` 播种 `deck.title`(回退 = 源文件夹名 → "未命名 deck")。仅新建目标时,既有 deck 不动。
- F-252:lift 时打印警告列出会触发 UI1 的内容 `<img>` 数量 + bg-div 修法,把发现点从 render 提前到 lift。**未做自动转换**:naive `<img>`→bg-div 会让"靠 img 内在尺寸撑开父容器"的页塌掉,不能无条件套;留 `--photos-as-bg` opt-in 为后续。

**验证**
- 改后全新 lift:F-251 title 自动播种 ✓;F-250 `var` 残留 0 / `url("assets/lark-content-bg.jpg")` ×2 ✓;F-252 lift 时即警告 ✓。
- 端到端(lift → render → copy-assets,linked-local 交付形态):content-bg **不再 404**,errors 0。
- 回归:`deck-json/tests/` 非 Playwright 全套 **177 passed**、`tests/run-regression.py`(视觉 fixtures)**7 pass·0 fail**、`test_self_contained` **5 passed**、lift 单测 **4 passed**。(全套 `pytest -q` 在本机挂在特定 `test_vis_*` Playwright 测试 + `dist/` 重复收集上 —— 环境问题,与本改动无关。)

**未决 / 交给用户**
- F-252 的 `--photos-as-bg` 安全自动转换(检测"父容器有显式尺寸 + img object-fit:cover"才转)。
- 是否把 F-250 推广成更稳的 render 期修法(render-deck 在 `<head>` 注入文档相对正确的 `:root{--fs-asset-*}` 覆盖,可同时救 skill-relative 模式 + 任何 inline 用 var 的 custom_css)—— 改共享 render 路径,回归面更大,留作选项。
- 是否合并本分支到 main / 是否推送。

---

## 单页 redesign 实操发现(2026-06-02 · 众安 deck #30 → 泰康保险 AI 先锋案例)

**触发**:用户把 #30(`feishu-ai-scene-tools`)按给定文案重做成泰康 4 案例矩阵(raw 页)。全程跑通,暴露两个**校验/迭代**层缺口(与代码审计 F-77..F-252 正交,非 lift 路径);先记待办,后续按 ID 清。

| ID | 文件 | 摘要 | 修法 | 状态 |
|---|---|---|---|---|
| F-253 | `assets/_validate_audits.py`(R06 ~185-258)+ `assets/visual-audit.js` | 真正的正文**内容**渲染在 16px(chrome foot 档)时 R06/R20 都查不出 → 静默"字偏小"。R06 BODY-floor 只认名字像正文的选择器(body/description/caption/list/cell/arch-*);raw 页自定义内容类(`.tk-sec`/卡内 `em` 等)不在表里 → 不当正文 → 16px==foot floor 放行;R20 同理(16px 是合法 Foot 档)。实测本会话 #30 v1:卡副标 + 次要指标行 16px,validator **0 finding**,用户当场指"字偏小"。系"合法档位下的内容语义盲区"(与 F-158 裸子串 / F-159 lifted 不降级同族、不同角度)。 | 加 computed-size 审计(visual-audit.js,量真实 px):叶子 <24px 且非已知 chrome 类/角色且含句子级文本(≥~6 CJK / 多词)→ warn「内容低于 24px 正文下限」。或让 R06 body 启发式不再只靠类名(回退:`.stage` 内 + 非 chrome 类 + 有实质文本 = 正文)。 | ✅ |
| F-254 | `deck-json/render-deck.py` · `assets/validate.py` | 无**单页**渲染/校验模式:改一页必须整份 render+validate。本会话改 1 页 → 71 err + 142 warn,**无一条**在被改页上 → 单页信号被全 deck 存量噪音淹没(只能靠 grep 自己 key,见纪律 F-68)。 | render-deck 加 `--only <key>`(或 validate 加 `--slide <key>`):只渲染/校验目标页 + 只打印该页 finding,加速单页迭代;默认仍整份(三道闸"整份校验"契约不破,`--only` 仅诊断/迭代用)。 | ✅ |

**副记(文档建议,非工单)**:raw 卡内 stat hero 大数字用 `font-size:64px;/* allow:typescale */` 实测可压住 R20 off-tier。`references/` 目前只列 cover/section/big-stat/quote 为合法 typescale 例外,建议补「raw 页卡内 KPI 大数字」一项,免得后人不敢用、退回偏小的 48。

> 过程慢的**执行层**教训(非技能 bug:误把"validator 干净"当"视觉干净"、看降采样缩略图不量真实 px、shell 抽风时反复 grep 而非写文件用 Read、对结构化 PDF 过度铺 workflow 而非"读目录→定位→读目标页")已入个人工作记忆,不在此技能审计追。

---

### F-253 / F-254 修复进度(2026-06-02 · 工作树未 commit / 未 push)

**F-254 ✅ — `validate.py --slide <key|N>` 单页诊断过滤**(`assets/validate.py`:新增 `filter_issues_to_slide` + `--slide` 参数)。按 data-slide-key 或 1-based 序号(`30` / `#30`)只保留该页 finding、exit 只看该页;不改跑哪些审计,仅改报告/退出口径,**非交付闸**。key↔序号互通(`aaa`=`#1`,"slide N" 文案也归该页)。实测真 deck:`--slide system-integration-thesis` → 只报该页 **3 条 R20**(而非全 deck 71),`--slide feishu-ai-scene-tools` → 0 finding / PASS。测试 `tests/test_validate_slide_filter.py`(5 例)。render-deck `--only` 透传留作可选(`validate --slide` 已覆盖核心诉求)。

**F-253 ✅ — 关键更正 + 真正修法**:动手才发现 **content-floor 审计早已存在 = `R-VIS-BODY-FLOOR`**(`visual-audit.js:853`,2026-05-19 加)——它**正是**抓"模糊命名类的 <24px 正文"(注释明写抓 `.rt/.d/.ind-tag` 这类过 R20+R06 的缝),我的 `.tk-sec`/`.tk-sub` 16px **会**被它抓到。**没触发的真因**:`render-deck` 默认强加 `--no-visual` → 所有视觉可读性审计**休眠**(而 `validate.py` 自己默认 visual=ON)。所以修法**不是**新写审计(会重复),而是让既有审计在默认渲染路径可达:**render-deck 现对 runs/ 下的真实 deck 把视觉审计作为「非阻断 readability advisory」自动跑**(打到 stderr,不影响 exit code),且**无论静态闸过不过都跑**(字偏小 与他页静态错可共存——正是 #30 的情形)。`/tmp` 路径跳过(测试不被拖入 Playwright)、无 Playwright 时静默 no-op。**实地验证**:runs/ 下放一页 16px 正文、`render-deck`(无 --visual)→ 静态闸 exit 0,advisory 仍打出 `[R-VIS-BODY-FLOOR] … renders at 16px … must be ≥ 24 px`。测试 `tests/test_readability_advisory.py`。
- **决策记录**:把 render-deck `--visual` 默认翻成全局 ON 被否——会让每次渲染(含 golden / 全测试套)强依赖 Playwright;「只对 runs/ 出 advisory」是测试安全的折中。
- **残留**:无 Playwright 的环境仍漏字偏小(advisory no-op;静态 R06 看不到渲染文本,不强加噪音静态规则,维持现状)。副记的 typescale 文档补充未落 `references/`(可选)。

**回归**:静态校验类 **96 passed**、新增 **8 例**(F-254×5 + F-253×2 + 接线)、render-deck golden/chart/review-fixes **10 passed**。改动文件:`assets/validate.py`、`deck-json/render-deck.py` + 两个新测试。**仅工作树,未 commit / 未 push**。
