#!/usr/bin/env python3
"""
feishu-deck-h5  ·  programmatic self-check

Runs the SKILL.md self-check items that can be enforced by static analysis.
This is a HARD GATE: a deck is not "done" until this script exits 0.

Usage:
    python3 assets/validate.py path/to/deck.html [--strict]

    --strict  also fails on warnings (mono-logo usage, large unknown hex
              values inside slide markup, etc.)

Exit codes:
    0   all checks pass
    1   one or more violations
    2   internal error (cannot parse file)
"""

from __future__ import annotations
import functools, re, sys, argparse
from collections import Counter
from pathlib import Path

# ===========================================================================
#  VALIDATOR MAP — the 32 static audits by family (F-10 navigability index).
#  Find a rule fast: rule code → audit function → `grep "def <name>"`. The audit
#  SET is data-driven via the STATIC_AUDITS registry (just above main()); this
#  map is the human index into the monolith. Visual/Playwright rules (R-OVERFLOW,
#  R-VIS-TIER/BODY-FLOOR/BALANCE…) live in run_visual_audits + visual-audit.js.
#
#  STRUCTURE / DOM
#    audit_structure             R02,R07          frame/deck nesting, required blocks
#    audit_dom_integrity         R-DOM            balanced divs, 1 .slide per frame
#    audit_slide_keys            R-KEY            unique kebab data-slide-key
#  TYPOGRAPHY / COPY
#    audit_titles_one_line       R13              title one line (hero layouts exempt)
#    audit_copy_rules            R05              punctuation / placeholder hygiene
#    audit_font_sizes            R06              body 24 / chrome 16 floors
#    audit_type_ladder           R20              per-page sizes on {16,24,28,48}
#    audit_white_text            R-WHITE-TEXT     low-opacity white on dark
#    audit_hierarchy             R-HIERARCHY      meta not larger than body
#    audit_header_minimal        R56              eyebrow on a non-hero header
#    audit_bullet_dash           R-BULLET-DASH    ad-hoc dash bullets
#    audit_list_echo             R-ECHO           summary leaf echoes sibling prefixes
#  BRAND / PALETTE / CHROME
#    audit_brand_chrome          R07              wordmark / logo chrome
#    audit_hex_palette           R10              hex outside brand palette
#    audit_no_drop_shadows       R12              drop shadows (glow/inset exempt)
#    audit_data_decor            R38              decor data-attr usage
#    audit_no_cyan_accent        R49              cyan reserved for inline highlight
#    audit_runtime_chrome        R29-32           present-mode runtime chrome present
#  LANGUAGE
#    audit_language_policy       R-LANG           zh-only; no EN translation tracks
#    audit_translation_track_pairs R-LANG         sibling-pair detector (called above)
#  LAYOUT
#    audit_centering_pattern     R36              default-centering markup
#    audit_default_centering     R48              centerable layouts declare centering
#    audit_layout_integrity      L1,L2,L4         logo / balance / attr-density
#    audit_variant_discipline    R47              variant CSS alignment
#    audit_empty_header_zone     R-EMPTY-HEADER-ZONE   empty header band
#    audit_lift_style_lost       R-VIS-LIFT-STYLE-LOST lifted raw slide lost framework CSS
#  CSS / TECHNICAL
#    audit_undefined_css_vars    R-CSSVAR         var(--x) with no def/fallback
#  UI-MOCK · texts.md · RICHNESS · PERF · DELIVERY
#    audit_ui_mocks_are_html     UI1              mock UIs are HTML, not images
#    audit_text_ids              T00-T03          data-text-id format + texts.md sync
#    audit_visual_richness       R-VIS-NO-IMAGERY deck reads flat (advisory)
#    audit_perf                  P50-P55          inline-size / asset budgets
#    audit_feedback_md           R-FEEDBACK       FEEDBACK.md present at hand-off
# ===========================================================================

# ---------------------------------------------------------------------------
#  F-10 module split · re-export the full public surface
# ---------------------------------------------------------------------------
# validate.py stays the single import target (`import validate as V`) and the
# script entry. The kernel + audits live in sibling modules; re-export every
# public name (and every underscore-prefixed kernel symbol star-import skips)
# so the historical 91-name surface is preserved.
from _validate_common import *
from _validate_common import (
    _FS_TOKEN_FALLBACK, _load_fs_tokens, _FS_TOKENS,
    _SLIDE_FRAME_OPEN_RE,
    _STYLE_BLOCK_RE, _iter_style_blocks,
    _RULE_WITH_COMMENTS_RE,
    _DECK_VW, _DECK_VH, _MQ_FEATURE_RE, _media_query_matches,
    _strip_nested_at_rules,
    _BOX_SHADOW_GLOW_RING_RE, _BOX_SHADOW_INSET_RE,
    _BODY_CLASS_RE, _CHROME_CLASS_RE,
    _CJK_RE, _HTML_LEAF_TAGS, _HTML_VOID_TAGS, _HTML_SKIP_CONTAINERS,
    _walk_text_leaves,
    _CHART_SCAFFOLD_CLASSES, _is_chart_scaffold_class,
    _LAYOUT_ONLY_PARENT_TAGS,
)
# STATIC_AUDITS (below) references the audit functions, so the audits must be
# imported BEFORE that registry is built.
from _validate_audits import *
from _validate_audits import (
    _lifted_slide_keys, _parse_texts_md_ids, _SPARSE_BY_DESIGN,
)

# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------

def run_visual_audits(html_path: Path, iss: Issues, *,
                       want_screenshots: bool = False):
    """Single Playwright session that runs all `--visual` audits.

    Replaces standalone audit_visual_overflow. One Chromium launch covers:

      R-OVERFLOW       · per-slide scrollHeight > 1080 or scrollWidth > 1920
      R-VIS-TIER       · every text element's computed fontSize is on the
                         4-tier ladder {16, 24, 28, 48} or a documented hero
                         exception (88, 100, 132, 160) on hero-class selectors
      R-VIS-HIER       · within each card / panel, meta-class fontSize ≤
                         body-class fontSize (renderer-confirmed, not just
                         static CSS — catches inheritance / overrides)
      R-VIS-ALIGN      · grid containers (.overview-grid / .todo-grid / etc.)
                         have all direct children at roughly the same
                         bounding-box height (within 4 px tolerance)
      R-VIS-BODY-FLOOR · 2026-05-19 · text elements with ≥ 8 chars of direct
                         text rendered at < 24 px while NOT inside a mockup
                         container or chrome class. Catches the gap where
                         ambiguous short class names (.rt / .d / .ind-tag)
                         pass both R20 (16 is on ladder) and R06 (class-
                         heuristic). Renderer-aware: looks at actual
                         content length + container. Opt out per element
                         with `data-allow-body-floor`.
      R-VIS-ORPHAN     · 2026-05-25 · CJK leaf text that wraps to ≥2 lines
                         with a lonely ~1-char last line (orphan) OR a short
                         2-3 line label whose last line is < 38% of the
                         widest (上长下短 imbalance). `text-wrap: balance` in
                         feishu-deck.css prevents most; this WARNs on the
                         residue (fixed-width / flex-clamped containers where
                         balance can't help). Skips block-child sub-labels
                         (.role), SVG text, mockup-internal, nowrap. Note:
                         only audits deck slides — text inside prototype
                         <iframe>s is a separate document and not reached.

    Optionally archives PNG screenshots when want_screenshots=True.

    Speed: ~5 seconds for a 30-slide deck (vs ~40 s for per-slide
    screenshot). One Chromium launch, all assertions evaluate inside
    page.evaluate() so the round-trip cost stays minimal.

    Setup once:
        pip install playwright && python -m playwright install chromium
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        # Visual audits are default-on but gracefully degrade. Print a single
        # stderr hint (not a warning so it doesn't pollute the issue list /
        # break CI parsing) and continue with static-only output. Re-enable
        # by `pip install playwright && python -m playwright install chromium`,
        # or suppress this notice via `--no-visual`.
        print('  (visual audits skipped — playwright not installed; '
              'install with `pip install playwright && python -m playwright '
              'install chromium` to enable R-OVERFLOW / R-VIS-* checks)',
              file=sys.stderr)
        return

    url = html_path.resolve().as_uri()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080})
            page = context.new_page()
            # 2026-05-24 · was `wait_until='networkidle' timeout=10_000`.
            # Large decks (50+ slides with images/iframes) blew past 10s
            # because `networkidle` waits for ALL pending requests to settle.
            # The visual audit JS runs purely against the DOM and computed
            # styles — it doesn't need network-quiet, just DOM-ready. Switch
            # to `load` event (faster, fires when initial resources load),
            # bump timeout to 60s as belt-and-braces for big-deck image
            # decoding. Validated on ctg (53 slides) which previously
            # silently failed → 0 R-VIS-* hits.
            page.goto(url, wait_until='load', timeout=60_000)
            # Switch into present mode so each slide gets the full
            # 1920×1080 canvas (scroll mode would false-positive).
            page.evaluate("""
                () => {
                    const deck = document.querySelector('.deck');
                    if (deck) deck.setAttribute('data-mode', 'present');
                }
            """)
            page.wait_for_timeout(200)  # let layout settle

            # ----- One JS evaluation gathers EVERYTHING -----
            # Returns a structured report; Python then formats findings.
            report = page.evaluate(_visual_audit_js())

            # ----- Optional: archive screenshots -----
            shots_dir = None
            if want_screenshots:
                shots_dir = html_path.parent / (html_path.stem + '-previews')
                shots_dir.mkdir(parents=True, exist_ok=True)
                # Wait for deck JS to wire the .is-current class onto the
                # active slide-frame. After init, framework adds
                # `[data-js-ready]` to the deck and the CSS `:first-child`
                # fallback automatically de-activates (BF13), so we no
                # longer need to inject an override stylesheet here.
                try:
                    page.wait_for_function(
                        "() => document.querySelector('.deck[data-js-ready] .slide-frame.is-current') !== null",
                        timeout=3000)
                except Exception:
                    pass  # fall through; bleed may occur if JS never runs
                # Re-iterate slides, hashchange-navigate, screenshot each.
                slide_count = page.evaluate(
                    "() => document.querySelectorAll('.slide').length")
                for i in range(1, slide_count + 1):
                    page.evaluate(f"window.location.hash = '#{i}'")
                    # Wait for is-current to land on the expected frame
                    # (deck JS uses 1-based hash matching data-page).
                    try:
                        page.wait_for_function(
                            f"() => document.querySelector('.slide-frame[data-page=\"{i}\"]')?.classList.contains('is-current')",
                            timeout=1500)
                    except Exception:
                        pass
                    page.wait_for_timeout(350)  # CSS opacity transition is .25s; allow fade to finish
                    fname = f's{i:02d}.png'
                    page.screenshot(path=str(shots_dir / fname),
                                    full_page=False)

            browser.close()
    except Exception as e:
        iss.warn('R-VISUAL',
            f'visual checks could not run ({type(e).__name__}: {e}). '
            'Try `python -m playwright install chromium` if you have not '
            'yet, or open the deck in a browser manually to verify.')
        return

    # ----- Format findings from the JS report -----
    for entry in report.get('overflow', [])[:20]:
        bits = []
        delta_h = entry['h'] - 1080
        delta_w = entry['w'] - 1920
        if delta_h > 0: bits.append(f'height +{delta_h} px')
        if delta_w > 0: bits.append(f'width +{delta_w} px')
        iss.err('R-OVERFLOW',
            f'slide {entry["idx"]} ({entry["label"]}): content overflows '
            f'canvas — {", ".join(bits)}. Reduce content density, drop '
            'cards/rows, increase column count, or shorten body copy.')

    for entry in report.get('tier', [])[:20]:
        _lev = iss.warn if entry.get('lifted') else iss.err
        _note = (' — LIFTED slide (verbatim from another deck); downgraded '
                 'to WARNING, you choose whether to fix.' if entry.get('lifted') else '')
        _lev('R-VIS-TIER',
            f'slide {entry["slide_idx"]} · `{entry["selector"]}` renders '
            f'at {entry["computed_px"]}px (off the 4-tier ladder '
            '{16, 24, 28, 48} + hero whitelist). Snap to nearest tier, OR '
            'add `/* allow:typescale */` if this is a documented hero '
            f'exception (cover hero / section chapter-num / big-stat / etc.).{_note}')

    for entry in report.get('hier', [])[:20]:
        iss.err('R-VIS-HIER',
            f'slide {entry["slide_idx"]} · meta `{entry["meta_sel"]}` at '
            f'{entry["meta_px"]}px is BIGGER than body `{entry["body_sel"]}` '
            f'at {entry["body_px"]}px in the same card '
            f'(`{entry["card_sel"]}`). Visual hierarchy reads inverted — '
            'shrink meta to ≤ body, or rename to a column-pill class if '
            'this element is actually a column title (not meta).')

    for entry in report.get('align', [])[:20]:
        # Soft: 4 px tolerance is genuinely fuzzy (sub-pixel rounding on
        # Chromium fractional scale can produce 5 px deltas on perfectly
        # aligned grids). Editorial — flagged but never promoted to error.
        iss.warn_soft('R-VIS-ALIGN',
            f'slide {entry["slide_idx"]} · grid `{entry["grid_sel"]}` has '
            f'{entry["count"]} direct children with heights '
            f'{entry["heights"]} — max diff {entry["delta"]} px '
            f'(> 4 px tolerance). For canonical-card / overview-card '
            'grids the cards should be equal-height; check `flex: 1` is '
            'applied or `align-items: stretch` is set on the container.')

    for entry in report.get('title_position', [])[:20]:
        iss.err('R-VIS-TITLE-POSITION',
            f'slide {entry["slide_idx"]} (layout `{entry["layout"]}`) · '
            f'`.header` rendered at top:{entry["actual_top"]}px, expected '
            f'~{entry["expected_top"]}px (master spec). Likely cause: the '
            f'layout is missing from the framework header-positioning '
            'whitelist in `feishu-deck.css` / `extra-layouts.css`. Add '
            f'`.slide[data-layout="{entry["layout"]}"] .header` to the '
            'unified positioning rule (`position:absolute; top:61px; '
            'left:73px; right:320px`) so title aligns with the master '
            'spec across all layouts.')

    for entry in report.get('opt_out_abuse', [])[:20]:
        ex_str = (f' (e.g. {", ".join(entry["examples"])})'
                  if entry.get('examples') else '')
        iss.warn('R-VIS-OPT-OUT-ABUSE',
            f'slide {entry["slide_idx"]} has {entry["count"]} occurrences of '
            f'`{entry["type"]}` (threshold: {entry["threshold"]}){ex_str}. '
            'opt-out attribute / comment is documented exception, NOT '
            'silence button. Batch-muting validator warnings hides real '
            'issues (text too small / chrome class abuse / palette drift). '
            'Fix: revisit each opt-out — if it is true by-design chrome / '
            'axis label / decorative element, KEEP it AND write a one-line '
            'justification comment; if it is regular body content, REMOVE '
            'the opt-out and bump to 24 (or use brand color, etc). '
            'Documented exception is 1-3 per slide, not 6+.')

    for entry in report.get('card_overflow', [])[:20]:
        direction = entry.get('direction', 'vertical')
        if direction == 'horizontal':
            iss.err('R-VIS-CARD-OVERFLOW',
                f'slide {entry["slide_idx"]} · `{entry["selector"]}` is a '
                f'flex/grid container with nowrap children — total children '
                f'width ({entry["content_h"]} px) exceeds container width '
                f'({entry["card_h"]} px) by {entry["overflow_px"]} px. '
                'Children are bleeding past the right edge (visible overflow) '
                'or being silently clipped. Fix: shorten child text, move one '
                'child to a separate line (display:block sibling), set '
                '`flex-wrap: wrap`, or widen the container.')
        elif direction == 'vertical-visible':
            iss.err('R-VIS-CARD-OVERFLOW',
                f'slide {entry["slide_idx"]} · `{entry["selector"]}` content '
                f'({entry["content_h"]} px) is {entry["overflow_px"]} px taller '
                f'than its box ({entry["card_h"]} px) and overflow is NOT hidden '
                '— text is spilling visibly out the bottom past the border / '
                'background. The slide still fits the 1920×1080 canvas, so '
                'R-OVERFLOW misses it; the clip-only check missed it too because '
                'overflow is visible. Fix: shorten body copy, drop a row / item, '
                'tighten padding / gap, or give the box more height. (Geometry — '
                'stays ERROR even on lifted slides; a visible spill is a real defect.)')
        else:
            iss.err('R-VIS-CARD-OVERFLOW',
                f'slide {entry["slide_idx"]} · `{entry["selector"]}` has '
                f'`overflow:hidden` but content ({entry["content_h"]} px) is '
                f'{entry["overflow_px"]} px taller than the container '
                f'({entry["card_h"]} px) — text is being clipped silently. '
                'Fix: shorten body copy, drop a row/item, shrink padding/gap, '
                'increase card height (more stage space), OR drop overflow:hidden '
                'so the issue is at least visible.')

    for entry in report.get('overlap', [])[:20]:
        iss.err('R-OVERLAP',
            f'slide {entry["slide_idx"]} · siblings inside `{entry["container_sel"]}` '
            f'physically overlap: `{entry["a_sel"]}` and `{entry["b_sel"]}` '
            f'intersect by {entry["overlap_x"]}×{entry["overlap_y"]} px. '
            'One sibling overflowed its allocated row/column and crashed '
            'into another. Fix: tighten content (smaller padding/gap, fewer '
            'items), expand the container (use `.stage.stage--tall` for 750 px '
            'vs default 680 px height), or add `min-height: 0; overflow: hidden` '
            'on the overflowing element so excess content is clipped instead of '
            'bleeding into siblings.')

    for entry in report.get('label_floor', [])[:20]:
        _lev = iss.warn if entry.get('lifted') else iss.err
        _lev('R-VIS-LABEL-FLOOR',
            (('LIFTED slide (verbatim) — downgraded to WARNING, you choose whether to bump. ')
             if entry.get('lifted') else '') +
            f'slide {entry["slide_idx"]} · card `{entry["card_sel"]}` '
            f'contains content-tier text (≥28px) but label '
            f'`{entry["label_sel"]}` is {entry["label_px"]}px — '
            'content-card labels MUST be ≥ 24 (Body tier). 16/18 chrome '
            'is reserved for true page metadata (.source / .pageno / '
            '.footnote / .attrib / etc., reached via .header / .footer '
            'ancestor). See SKILL.md "Hero-context label floor". '
            'Promote to 24 + differentiate via font-weight or brand '
            'color, not by shrinking the size.')

    for entry in report.get('body_floor', [])[:20]:
        _lev = iss.warn if entry.get('lifted') else iss.err
        _lev('R-VIS-BODY-FLOOR',
            (('LIFTED slide (verbatim from another deck) — downgraded to '
              'WARNING, you choose whether to bump. ') if entry.get('lifted') else '') +
            f'slide {entry["slide_idx"]} · `{entry["selector"]}` renders at '
            f'{entry["rendered_px"]}px but its direct text is '
            f'{entry["char_count"]} chars ("{entry["preview"]}"). '
            'Body content (≥ 8 chars of sentence-like text outside mockup '
            'containers and chrome classes) must be ≥ 24 px on projector. '
            'Bump to 24 (preferred), OR rename to a chrome class '
            '(.eyebrow / .footnote / .source / .pill / .tag / .chip / '
            '.badge / .pageno / .demo-tag) if it really is chrome, OR set '
            '`data-allow-body-floor` on the element for a documented '
            'exception (e.g. legend annotation by design).')

    for entry in report.get('abspos_dual_anchor', [])[:20]:
        iss.err('R-VIS-ABSPOS-DUAL-ANCHOR',
            f'slide {entry["slide_idx"]} · `{entry["selector"]}` is '
            f'`position: absolute` with BOTH `top: {entry["top"]}` AND '
            f'`bottom: {entry["bottom"]}` declared — height stretched to '
            f'{entry["actual_h"]} px; content-sized would be {entry["content_h"]} px. '
            'Classic cascade footgun: an override added `top:` without '
            'declaring `bottom: auto`, so an inherited `bottom:` from a '
            'less-specific rule is still active and the element fills the '
            'parent vertically. Fix: in the override block, add '
            '`bottom: auto` (or `top: auto`) to neutralize the inherited '
            'anchor; OR use `inset:` shorthand to redeclare all four; OR '
            'set `data-allow-dual-anchor` on the element if it is a real '
            'fill-parent overlay (rare for slide content).')

    for entry in report.get('orphan', [])[:25]:
        kind = '末行孤字 orphan' if entry['kind'] == 'orphan' else '上长下短 imbalanced'
        no_bal = '' if entry.get('balance') == 'balance' else \
            ' (该元素当前没有 text-wrap:balance)'
        iss.warn('R-VIS-ORPHAN',
            f'slide {entry["slide_idx"]} · `{entry["selector"]}` CJK 换行不平衡 '
            f'— {kind}: {entry["lines"]} 行 {entry["line_px"]}px,末行仅 '
            f'{entry["last_px"]}px (最宽行 {entry["max_px"]}px / 字号 '
            f'{entry["font_px"]}px) ("{entry["preview"]}"). 文字换行后末行只剩一两个字 '
            '或上面长下面短,投影上很碎。Fix 优先级: (1) 给元素加 '
            '`text-wrap: balance`(框架对常见标题/卡名类已默认开 — 若这里没生效,'
            '多半被更具体的选择器/另一条 !important 压住了,提级覆盖即可);'
            '(2) 容器固定宽 / 被 flex 夹窄,balance 也救不了 → 加宽容器,或 4 字以内'
            '主标签用 `white-space: nowrap` 逼单行,或把尾词(「企划」「部」等)用 '
            '`display:block` 拆成副标行;(3) 改文案让上下两行字数接近。' + no_bal)

    # ---- R-VIS-BALANCE · 视觉重心 / 留白均衡 ----
    # 三种 sub-kind: top-heavy / bottom-heavy / dead-band。Warn 级别
    # (不是 err) — 留白判断有主观成分,作者可能故意留;但默认要让作者
    # 知道这页"上空 / 下空 / 中空",大量"看着空"的反馈都在这里。
    for entry in report.get('balance', [])[:25]:
        kind = entry['kind']
        if kind == 'top-heavy':
            iss.warn('R-VIS-BALANCE',
                f'slide {entry["slide_idx"]} · `{entry["container_sel"]}` '
                f'上重下空(top-heavy): 顶部留白 {entry["top_gap"]}px,'
                f'底部留白 {entry["bottom_gap"]}px (容器高 {entry["body_height"]}px) '
                '— 内容堆在顶部,下半页大块空白。Fix: (1) 容器加 '
                '`justify-content: center`(框架对 fixed-shape layout 已默认开 R48,'
                '但 raw / flex column 默认 flex-start,需手动加);(2) 删 `flex: 1` 让'
                '内容随高度伸展的情况,改成 content-sized + center;(3) 内容确实太少 → '
                '加 supporting 元素(KPI / pullquote / case ref)填重心。Per-slide '
                'opt-out: 在 .slide 加 `data-allow-imbalance` 标记为故意。')
        elif kind == 'bottom-heavy':
            iss.warn('R-VIS-BALANCE',
                f'slide {entry["slide_idx"]} · `{entry["container_sel"]}` '
                f'下重上空(bottom-heavy): 顶部留白 {entry["top_gap"]}px,'
                f'底部留白 {entry["bottom_gap"]}px (容器高 {entry["body_height"]}px) '
                '— 内容沉底,上半页大块空白。Fix: 容器 `justify-content: center` '
                '或 `align-content: center`;或检查是否有 `margin-top: auto` 把'
                '内容硬推到底部(BF9 反模式)。')
        else:  # dead-band
            iss.warn('R-VIS-BALANCE',
                f'slide {entry["slide_idx"]} · `{entry["container_sel"]}` '
                f'中间留白 {entry["gap_px"]}px(dead-band)— `{entry["between_a"]}` '
                f'和 `{entry["between_b"]}` 之间有一条 >140px 的空带,'
                '页面被切成两半。Fix: (1) 容器去掉 `flex: 1` / `justify-content: '
                'space-between`(BF9 反模式经常制造这种空白);(2) 缩小 gap;(3) '
                '在中间加一行 supporting 元素(pullquote / KPI / divider);(4) '
                '确实是设计意图(留白让 hero 呼吸)→ 加 `data-allow-imbalance`。')

    # ---- R-VIS-SLACK-FLEX · flex:1 子容器撑出内部空白 ----
    # R-VIS-BALANCE 看的是 body container 顶级 children 之间的 sibling gap;
    # 这条补的是另一类:`flex:1` 子容器抢光剩余空间后,内部 justify-content
    # 把空白分到子容器顶/底,导致最后一个 grandchild 离子容器边距远 →
    # sibling 看上去"远"。典型踩坑:`.arch3 { flex:1; justify-content: center }`
    # 内部撑出 200px slack。Warn 级(留白判断主观,作者可能有意)。
    for entry in report.get('slack_flex', [])[:20]:
        ts, bs = entry['top_slack'], entry['bottom_slack']
        if ts >= 80 and bs >= 80:
            kind = f'容器内部居中撑空(top {ts}px / bottom {bs}px)'
        elif ts >= 80:
            kind = f'容器内部上方撑空 {ts}px'
        else:
            kind = f'容器内部下方撑空 {bs}px(最后一个子元素到容器底距离过大)'
        iss.warn('R-VIS-SLACK-FLEX',
            f'slide {entry["slide_idx"]} · `{entry["child_sel"]}` '
            f'(flex-grow {entry["flex_grow"]}, 高 {entry["child_height"]}px, '
            f'内容 {entry["content_height"]}px, justify-content: '
            f'{entry["justify"]}) — {kind}。父 `{entry["container_sel"]}`。'
            '原因:`flex:1` 把剩余空间给了该子容器,但内部内容比拿到的空间小,'
            '`justify-content` 把空白分到容器内部,视觉上跟相邻 sibling 间距'
            '异常大。Fix 选一个: (1) 去掉子容器的 `flex: 1`(改成 content-sized '
            '+ 父容器 `justify-content: center` 居中整组内容,这是最常见的修法);'
            '(2) 把子容器 `justify-content` 改成 `flex-start` / `flex-end` 让'
            '内容靠一端;(3) 内容确实太少 → 加 supporting 元素填重心;(4) '
            '确实是设计意图(故意让 hero 元素被推到某一端)→ 在子容器或父容器加 '
            '`data-allow-flex-slack` 跳过审计。')

    # ---- R-VIS-CARD-MIN-HEIGHT-SPARSE · min-height 撑空 + 没 space-between ----
    # 作者用 `min-height` 撑 card 视觉体量,但 default `justify-content: flex-start`
    # 让内容堆顶,卡底大量空白 — 视觉上"卡片看着空"。正解:加 `class="fs-card-fill"`
    # (= space-between),N child 均布。Warn 级(留白判断主观,作者可能故意)。
    # 触发 2026-05-29 P15 调试:这 pattern 应该是 default 提醒,不靠作者记得。
    for entry in report.get('card_min_height_sparse', [])[:15]:
        iss.warn('R-VIS-CARD-MIN-HEIGHT-SPARSE',
            f'slide {entry["slide_idx"]} · `{entry["selector"]}` '
            f'(min-height {entry["min_height"]}px, 实际 {entry["client_h"]}px, '
            f'内容延展 {entry["content_extent"]}px (first→last bbox), '
            f'可用 {entry["usable_h"]}px (减 padding), 真 slack {entry["slack"]}px, '
            f'{entry["kid_count"]} children, justify-content: {entry["justify"]}) '
            f'— 作者设了 min-height 撑卡片体量,但内容堆顶,卡底大量空白。'
            'Fix: (1) 给该元素加 `class="fs-card-fill"`(框架 utility · 内部 '
            '`justify-content: space-between !important` · {N children 跨高度均布}'
            ');(2) 或缩小 min-height 到自然内容高度附近(slack < 30px · 让 '
            'flex-start 看不出来);(3) 确实是设计意图(顶部 hero + 底部留白)→ '
            '给元素加 `data-allow-min-height-sparse` 跳过审计。'
            '完整 pattern 见 `feishu-deck.css` 的 `.fs-card-fill` 注释。')

    # ---- R-FOCAL-CHECK · 视觉焦点是否清晰 ----
    # 唯一被诊断的失败模式:≥3 个元素共享最大字号 AND 无任何元素声明 hero。
    # 通常说明作者把 title + N 个 card title 全做到 48,眼睛没有第一落点。
    for entry in report.get('focal', [])[:20]:
        iss.warn('R-FOCAL-CHECK',
            f'slide {entry["slide_idx"]} (layout `{entry["layout"]}`) · '
            f'{entry["tied_count"]} 个元素共享最大字号 {entry["top_size_px"]}px '
            f'(e.g. {", ".join("`"+s+"`" for s in entry["examples"][:3])}…)'
            f'{"…" if entry["tied_count"] > 3 else ""},视觉焦点模糊 — '
            '观众第一眼不知道该看哪个。Fix 选一个: (1) 把 N-1 个降一级'
            '(48→28 或 28→24,按 Card density 规则:≤4 卡 = 48,5-6 卡 = 28,'
            '≥7 卡 = 28);(2) 给真正的 hero 元素加 `class="is-hero"` 或 '
            '`data-focal`(明示该元素是焦点,审计放行);(3) 用 brand color / '
            'border / 不同 padding 把 hero 元素从平行结构里抽出来;(4) 这页确实'
            '是 overview / 平权矩阵(N 项等大就是设计本身)→ 在 .slide 加 '
            '`data-allow-no-focal` 跳过审计。')

    # (screenshot archival happens inside the Playwright block above; no
    # post-step needed. The previous `if 'shots_dir' in dir(): pass` was
    # dead: `dir()` inside a function returns local names, not what one
    # might assume, and the branch had `pass` anyway. Removed 2026-05-18.)


# ---- JS payload that runs INSIDE the headless browser ----
# Returns: {overflow: [...], tier: [...], hier: [...], align: [...]}
# Loaded from disk so we get JS syntax highlight, `node --check`
# in preflight.sh, and line-mapped stack traces. Extracted
# 2026-05-24 (was a 626-line r"""...""" string embedded here).
#
# Loaded LAZILY (on first visual-audit run), not at import time, so that
# importing this module for static-only checks never touches the file.
# check-only.py does `import validate` and must keep working even if
# visual-audit.js is absent; a read failure here degrades to the existing
# R-VISUAL warning inside run_visual_audits() rather than crashing import.
_VISUAL_AUDIT_JS_CACHE = None


def _visual_audit_js():
    global _VISUAL_AUDIT_JS_CACHE
    if _VISUAL_AUDIT_JS_CACHE is None:
        _VISUAL_AUDIT_JS_CACHE = (
            Path(__file__).resolve().parent / 'visual-audit.js'
        ).read_text()
    return _VISUAL_AUDIT_JS_CACHE


def inline_linked(html_text, base_dir):
    """Inline <link rel=stylesheet> / <script src> into the HTML so audits can
    see framework CSS/JS content. External (http/https/data:) refs and missing
    files are left untouched. Shared by main() here and check-only.py — was
    copy-pasted in both, unified per F-14."""
    def repl_link(m):
        href = m.group(1)
        if href.startswith(('http:', 'https:', 'data:')): return m.group(0)
        target = (base_dir / href).resolve()
        if not target.is_file(): return m.group(0)
        return ('<style data-source="framework">'
                + target.read_text(encoding='utf-8')
                + '</style>')
    html_text = re.sub(
        r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>',
        repl_link, html_text)
    def repl_script(m):
        src = m.group(1)
        if src.startswith(('http:', 'https:', 'data:')): return m.group(0)
        target = (base_dir / src).resolve()
        if not target.is_file(): return m.group(0)
        return ('<script data-source="framework">'
                + target.read_text(encoding='utf-8')
                + '</script>')
    html_text = re.sub(
        r'<script[^>]*src="([^"]+)"[^>]*>\s*</script>',
        repl_script, html_text)
    return html_text


# F-10/F-08 · single registry of static audits, iterated by BOTH main() here
# and check-only.py — so the two entry points can never run different audit
# sets (check-only historically skipped 6 audits silently). Each entry is
# (audit_fn, arg-order); the runner passes the named context values
# positionally. Order matches the historical main() sequence (audits are
# independent — each only reads html/slides/path and appends to iss — so order
# is cosmetic). Adding/removing an audit = one registry line, both entries.
STATIC_AUDITS = [
    (audit_dom_integrity,      ('html', 'iss')),
    (audit_lift_style_lost,    ('html', 'iss')),
    (audit_structure,          ('slides', 'iss')),
    (audit_titles_one_line,    ('slides', 'iss')),
    (audit_brand_chrome,       ('slides', 'iss')),
    (audit_copy_rules,         ('html', 'iss')),
    (audit_font_sizes,         ('html', 'iss')),
    (audit_type_ladder,        ('html', 'iss')),
    (audit_undefined_css_vars, ('html', 'iss')),
    (audit_white_text,         ('html', 'iss')),
    (audit_no_drop_shadows,    ('html', 'iss')),
    (audit_data_decor,         ('slides', 'iss')),
    (audit_hex_palette,        ('html', 'iss')),
    (audit_bullet_dash,        ('html', 'iss')),
    (audit_runtime_chrome,     ('html', 'iss', 'path')),
    (audit_centering_pattern,  ('html', 'iss')),
    (audit_layout_integrity,   ('html', 'iss')),
    (audit_default_centering,  ('html', 'iss')),
    (audit_empty_header_zone,  ('html', 'iss')),
    (audit_hierarchy,          ('html', 'iss')),
    (audit_variant_discipline, ('html', 'iss')),
    (audit_ui_mocks_are_html,  ('slides', 'iss')),
    (audit_no_cyan_accent,     ('slides', 'iss')),
    (audit_header_minimal,     ('slides', 'iss')),
    (audit_slide_keys,         ('slides', 'iss')),
    (audit_language_policy,    ('html', 'slides', 'iss')),
    (audit_list_echo,          ('slides', 'iss')),
    (audit_visual_richness,    ('slides', 'iss')),
    (audit_perf,               ('html', 'iss')),
    (audit_text_ids,           ('html', 'path', 'iss')),
    (audit_feedback_md,        ('path', 'iss')),
]


def run_static_audits(audits, *, html, slides, path, iss):
    """Run a registry of (audit_fn, arg-order) entries against one context."""
    ctx = {'html': html, 'slides': slides, 'path': path, 'iss': iss}
    for fn, sig in audits:
        fn(*(ctx[a] for a in sig))


def main():
    p = argparse.ArgumentParser(description='feishu-deck-h5 self-check')
    p.add_argument('html', help='Path to the assembled deck HTML file')
    p.add_argument('--strict', action='store_true',
                   help='Promote warnings to errors')
    p.add_argument('--visual', action=argparse.BooleanOptionalAction,
                   default=True,
                   help='Run the Playwright-based renderer-side audits: '
                        'R-OVERFLOW (canvas overflow — catches the P05-style '
                        '"column bleeds into legend" bug that static CSS '
                        'analysis cannot), R-VIS-TIER (computed fontSize on '
                        '4-tier ladder), R-VIS-HIER (meta ≤ body in each '
                        'card), R-VIS-ALIGN (grid children equal height). '
                        'DEFAULT: on (~1-5s extra per deck). Use --no-visual '
                        'to skip (e.g. CI without Chromium). Gracefully '
                        'skips when playwright is not installed.')
    p.add_argument('--screenshots', action='store_true',
                   help='In addition to --visual checks, archive PNG '
                        'screenshots of each slide to '
                        '<deck-stem>-previews/sNN.png. Useful for visual '
                        'baseline / human review; not needed for CI.')
    p.add_argument('--json', action='store_true',
                   help='Emit a stable JSON blob to stdout instead of the '
                        'human-readable report. Format: '
                        '{"deck": <path>, "slides": <N>, "errors": [...], '
                        '"warnings": [...]} where each issue is '
                        '{"code", "msg", "slide" (parsed if present), '
                        '"severity"}. Use this when downstream tools '
                        '(run-regression.py, analyze-prompts.py) consume '
                        'validator output — parsing the human report via '
                        'regex is brittle to format tweaks.')
    args = p.parse_args()
    if args.screenshots and not args.visual:
        args.visual = True   # --screenshots implies --visual

    path = Path(args.html)
    if not path.is_file():
        print(f'ERROR: file not found: {path}', file=sys.stderr)
        return 2

    html = path.read_text(encoding='utf-8')

    # Resolve linked stylesheets and scripts so audits can see their content
    # (the linked-mode deck doesn't inline CSS/JS — without this, runtime-chrome
    # and centering-pattern audits would false-fail).
    #
    # Inlined `<style>` and `<script>` blocks carry `data-source="framework"`
    # so author-CSS audits (R-WHITE-TEXT, R47, future rules) can scope
    # themselves to author markup and skip framework rules they shouldn't
    # police. Audits that DO want to see framework (R29-R32 runtime chrome,
    # R36 centering pattern, R10 hex palette) can ignore the attribute.
    html = inline_linked(html, path.parent)  # module-level helper (F-14)

    slides = extract_slides(html)

    iss = Issues()
    # All audits emit warn/err at their inherent severity. The global
    # `--strict` flag promotes ALL warnings to errors after the audits
    # complete (see end of main()) — per-audit `strict` branches were
    # redundant and removed 2026-05-18. Audits run from the shared
    # STATIC_AUDITS registry so check-only.py runs the identical set (F-10/F-08).
    run_static_audits(STATIC_AUDITS, html=html, slides=slides, path=path, iss=iss)

    if args.visual:
        run_visual_audits(path, iss, want_screenshots=args.screenshots)

    if args.strict:
        # Promote regular warnings to errors. SOFT warnings (R-FEEDBACK,
        # R-VIS-ALIGN, etc.) stay as warnings — they are editorial
        # advisories that should never fail CI.
        iss.errors.extend(iss.warnings)
        iss.warnings = []

    # Soft warnings render alongside regular warnings, no separate header.
    all_warnings = iss.warnings + iss.soft_warnings

    if args.json:
        # Stable machine-readable output. Downstream tools (run-regression,
        # analyze-prompts) read this instead of regex-parsing the human
        # narrative. Slide ordinal parsed from msg when present ("slide N ·")
        # — same convention every audit emit follows. selector_hint is best-
        # effort: backtick-quoted token inside the msg (most audits include).
        _SLIDE_IN_MSG = re.compile(r'slide\s+(\d+)\b')
        _BACKTICK_IN_MSG = re.compile(r'`([^`]+)`')
        def _entry(code, msg, severity):
            s = _SLIDE_IN_MSG.search(msg)
            sel = _BACKTICK_IN_MSG.search(msg)
            return {
                'code': code,
                'severity': severity,
                'msg': msg,
                'slide': int(s.group(1)) if s else None,
                'selector_hint': sel.group(1) if sel else None,
            }
        payload = {
            'deck': str(path),
            'slides': len(slides),
            'errors': [_entry(c, m, 'error') for c, m in iss.errors],
            'warnings': (
                [_entry(c, m, 'warning') for c, m in iss.warnings]
                + [_entry(c, m, 'warning_soft') for c, m in iss.soft_warnings]
            ),
            'pass': not iss.errors,
        }
        import json as _json
        print(_json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if not iss.errors else 1

    print(f'feishu-deck-h5 validator  ·  {path.name}')
    print(f'  slides: {len(slides)}')
    print(f'  errors:   {len(iss.errors)}')
    print(f'  warnings: {len(all_warnings)}')

    if iss.errors:
        print('\nERRORS')
        for code, msg in iss.errors:
            print(f'  ✗ [{code}] {msg}')
    if all_warnings:
        print('\nWARNINGS')
        for code, msg in all_warnings:
            print(f'  ! [{code}] {msg}')

    if iss.errors:
        print('\nFAIL — fix the errors above before delivering.')
        return 1
    print('\nPASS — all programmatic checks satisfied.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
