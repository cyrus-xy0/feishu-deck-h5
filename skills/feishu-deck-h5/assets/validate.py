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
#  VALIDATOR MAP — the static audits by family (F-10 navigability index).
#  Find a rule fast: rule code → audit function → `grep "def <name>"`. The audit
#  SET is data-driven via the STATIC_AUDITS registry (just above main()); this
#  map is the human index into the monolith. Visual/Playwright rules (R-OVERFLOW,
#  R-VIS-TIER/BODY-FLOOR/BALANCE…) live in run_visual_audits + visual-audit.js.
#
#  STRUCTURE / DOM
#    audit_structure             R02,R07          frame/deck nesting, required blocks
#    audit_dom_integrity         R-DOM            balanced divs, 1 .slide per frame
#    audit_doc_integrity         R-DOC-INTEGRITY  whole-doc complete: .deck closed,
#                                                 runtime present, ends </body></html>
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
#  UI-MOCK · RICHNESS · PERF · DELIVERY
#    audit_ui_mocks_are_html     UI1              mock UIs are HTML, not images
#    audit_visual_richness       R-VIS-NO-IMAGERY deck reads flat (advisory)
#    audit_perf                  P50-P55          inline-size / asset budgets
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
    _lifted_slide_keys, _SPARSE_BY_DESIGN, _deck_imported,
)

# ---------------------------------------------------------------------------
#  UNIFY-VALIDATE-ARCH (2026-06-03/04) · single rule source = the unified engine
# ---------------------------------------------------------------------------
# validate.py no longer runs its own audit registries. ALL rule findings are
# sourced from the unified engine (`assets/audits.js`, evaluated against the
# RENDERED DOM by `run-audits.py`'s shared `run_unified_engine`) + a handful of
# source-byte / file-system checks that live in the runner (R-DOC-INTEGRITY /
# R-SELF-CONTAINED / perf — things a browser can't see faithfully). One rule
# source, one language; the old STATIC_AUDITS / _validate_audits.py /
# visual-audit.js dual registries are retired (step 4).
#
# validate.py's job is now purely the CLI / OUTPUT-CONTRACT adapter: parse flags,
# call the engine, map its findings into the historical {code, severity, msg,
# slide, selector_hint} shape (errors / warnings split, --strict promotion,
# --json, --slide, exit codes) that render-deck / delivery / the write-hook /
# the test suite depend on.
#
# DEPENDENCY: the engine is DOM/browser-based → validate.py now needs playwright
# for its DEFAULT (full) path. `--no-visual` runs ONLY the no-browser byte/source
# rules (see main()); it is documented as a partial check, never a silent green.
import importlib.util as _importlib_util

_RUN_AUDITS_PATH = Path(__file__).resolve().parent / 'run-audits.py'
_ENGINE = None  # lazily-loaded module handle (run-audits.py has a hyphen)


def _engine():
    """Lazily import run-audits.py (hyphenated → importlib). Cached. Returns the
    module exposing run_unified_engine + EngineUnavailable. Lazy so that merely
    importing validate (e.g. check-only's source scan, the surface test) never
    forces the engine module to load."""
    global _ENGINE
    if _ENGINE is None:
        spec = _importlib_util.spec_from_file_location(
            'run_audits', _RUN_AUDITS_PATH)
        mod = _importlib_util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _ENGINE = mod
    return _ENGINE


# Map the engine's severity vocabulary → the Issues buckets. The engine emits
# 'error' / 'warn' / 'warn_soft' (1:1 with iss.err / iss.warn / iss.warn_soft).
_SEV_TO_BUCKET = {
    'error': 'err',
    'warn': 'warn',
    'warn_soft': 'warn_soft',
}


def engine_findings_to_issues(findings, iss):
    """Pour unified-engine findings (each {rule, severity, slide_idx, message,
    ...}) into the Issues buckets, preserving the (code, msg) tuple shape every
    downstream consumer expects. Unknown severities default to a warning (never
    silently dropped)."""
    for f in findings:
        code = f.get('rule', '?')
        msg = f.get('message', '')
        bucket = _SEV_TO_BUCKET.get(f.get('severity'), 'warn')
        getattr(iss, bucket)(code, msg)


def run_unified_audits(path, iss, *, dom_rules=True, scope=None,
                       want_screenshots=False):
    """Run the unified engine against the rendered deck and fold its findings
    into `iss`. This REPLACES the old run_static_audits + run_visual_audits.

    dom_rules=True  → full engine: render in headless Chromium + audits.js
                      (geometry / DOM-text / structure rules) PLUS runner
                      byte/source rules. Requires playwright.
    dom_rules=False → `--no-visual`: NO browser; only the runner byte/source
                      rules (R-DOC-INTEGRITY / R-SELF-CONTAINED / perf). The
                      DOM/geometry rules do NOT run — documented partial check.

    Mirrors the old run_visual_audits failure semantics: an INABILITY to render
    (playwright missing / Chromium launch flake / nav timeout) is an environment
    glitch, NOT a deck defect, so it degrades to a single soft advisory rather
    than blocking a good deck under --strict. A real rule VIOLATION found by the
    engine still errs/warns normally."""
    eng = _engine()
    try:
        result = eng.run_unified_engine(
            path, scope, dom_rules=dom_rules)
    except eng.EngineUnavailable as e:
        if not dom_rules:
            # byte-only path should never raise for env reasons (no browser),
            # but be defensive — surface as a soft advisory, never block.
            iss.warn_soft('R-VISUAL',
                f'byte/source checks could not run ({type(e).__name__}: {e}).')
            return
        # Full path needs a browser. Missing playwright / Chromium flake →
        # degrade to static-only-ish: still run the byte/source rules (no
        # browser) so R-DOC-INTEGRITY etc. are never skipped, then advise.
        try:
            result = eng.run_unified_engine(path, scope, dom_rules=False)
            engine_findings_to_issues(result.get('findings', []), iss)
        except Exception:
            pass
        iss.warn_soft('R-VISUAL',
            f'visual/DOM checks could not run ({type(e).__name__}: {e}). '
            'Install with `pip install playwright && python -m playwright '
            'install chromium`, or open the deck in a browser to verify. '
            'Byte/source rules (R-DOC-INTEGRITY / R-SELF-CONTAINED / perf) '
            'still ran.')
        return
    engine_findings_to_issues(result.get('findings', []), iss)
    if want_screenshots and dom_rules:
        _archive_screenshots(path)


def _archive_screenshots(html_path):
    """Optional PNG archival of each slide (preserves the legacy --screenshots
    flag). Independent of rule sourcing — a separate lightweight Chromium pass.
    Degrades silently if playwright is unavailable (the engine path already
    advised)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return
    shots_dir = html_path.parent / (html_path.stem + '-previews')
    try:
        shots_dir.mkdir(parents=True, exist_ok=True)
        url = html_path.resolve().as_uri()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_context(
                viewport={'width': 1920, 'height': 1080}).new_page()
            page.goto(url, wait_until='load', timeout=60_000)
            try:
                page.wait_for_function(
                    "() => document.querySelector('.deck[data-js-ready] "
                    ".slide-frame.is-current') !== null", timeout=3000)
            except Exception:
                pass
            slide_count = page.evaluate(
                "() => document.querySelectorAll('.slide').length")
            for i in range(1, slide_count + 1):
                page.evaluate(f"window.location.hash = '#{i}'")
                page.wait_for_timeout(350)
                page.screenshot(path=str(shots_dir / f's{i:02d}.png'),
                                full_page=False)
            browser.close()
    except Exception:
        pass  # archival is best-effort; never break validation


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
        # INABILITY to run the visual checks (flaky Chromium launch / nav
        # timeout / missing browser) is an environment glitch, NOT a deck
        # defect — emit warn_soft so it NEVER escalates to a blocking error
        # under --strict / --gate ingest (which would reject a perfectly good
        # deck on a CI hiccup). An actual visual VIOLATION found below still
        # warns/errs normally.
        iss.warn_soft('R-VISUAL',
            f'visual checks could not run ({type(e).__name__}: {e}). '
            'Try `python -m playwright install chromium` if you have not '
            'yet, or open the deck in a browser manually to verify.')
        return

    # ----- Format findings from the JS report -----
    # NOTE (2026-05-30, L1 reverted): font-size violations are NOT exempted for
    # imported/foreign decks. Small body text is unreadable regardless of who
    # designed it, and an off-size hero is still wrong — the validator flags
    # both; the RIGHT fix is enlarge-to-floor + grow-box (small body) / hero at
    # the layout's defined size, never snap-and-overflow nor advisory-and-ignore.
    for entry in report.get('overflow', [])[:20]:
        bits = []
        delta_h = entry['h'] - 1080
        delta_w = entry['w'] - 1920
        if delta_h > 0: bits.append(f'height +{delta_h} px')
        if delta_w > 0: bits.append(f'width +{delta_w} px')
        # Severity tiering (2026-05-30): not all canvas overflow hurts reading.
        # <24px (≈half a line, space is fine) = benign advisory; 24-60px = warn;
        # >60px = content genuinely clipped/lost → error. Only the harmful tier
        # blocks delivery.
        _ov = max(delta_h, delta_w)
        _lev = iss.err if _ov > 60 else iss.warn if _ov >= 24 else iss.warn_soft
        _sev = ('严重 · 内容被切，必修' if _ov > 60
                else '临界 · 约 1-2 行' if _ov >= 24
                else '可忽略 · 半行内，空间够，不阻断')
        _lev('R-OVERFLOW',
            f'slide {entry["idx"]} ({entry["label"]}): content overflows '
            f'canvas — {", ".join(bits)}（{_sev}）. 对症修：标题溢出→换行/加宽容器，'
            '正文→压字数，条目过多→删条目/减列。')

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

    for entry in report.get('title_gap', [])[:20]:
        # < 12px (or negative) = colliding/crowding the title → err;
        # 12-24px = tight breathing room → warn (advisory).
        _lev = iss.err if entry["gap_px"] < 12 else iss.warn
        _lev('R-VIS-TITLE-GAP',
            f'slide {entry["slide_idx"]} (layout `{entry["layout"]}`) · content '
            f'sits only {entry["gap_px"]}px below the title (< 24px / overlapping). '
            'The body grew or overflowed UP toward `.header` — it is crowding / '
            'colliding with the title. Fix: shorten or shrink the content so it '
            'fits, OR move the content block DOWN (adjust the stage top / vertical '
            'centering). 死规矩:标题/副标题位置不动,压内容或下移正文,绝不动标题。')

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
        # Severity tiering: visible spill <24px is benign; clipped content (lost)
        # escalates sooner. >60px (or >24px clipped) = error; else warn / advisory.
        _px = entry.get('overflow_px', 0)
        # Content spilling OUT of / clipped BY a styled box is a VISIBLE defect
        # (text sitting outside its card) — harmful even at small px, unlike
        # benign canvas-EDGE slack (R-OVERFLOW). The earlier 24-60px=warn tiering
        # wrongly hid real card spills (e.g. a 42px hero-card spill). Only a tiny
        # <16px (descender / rounding) is advisory here.
        _lev = iss.err if _px > 16 else iss.warn
        if direction == 'horizontal':
            _lev('R-VIS-CARD-OVERFLOW',
                f'slide {entry["slide_idx"]} · `{entry["selector"]}` is a '
                f'flex/grid container with nowrap children — total children '
                f'width ({entry["content_h"]} px) exceeds container width '
                f'({entry["card_h"]} px) by {entry["overflow_px"]} px. '
                'Children are bleeding past the right edge (visible overflow) '
                'or being silently clipped. Fix: shorten child text, move one '
                'child to a separate line (display:block sibling), set '
                '`flex-wrap: wrap`, or widen the container.')
        elif direction == 'vertical-visible':
            _lev('R-VIS-CARD-OVERFLOW',
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
            # F-58 · 区分两种 overflow:hidden 裁切的危害程度:
            #   (b) 永久不可见(non-recoverable):该盒 user 不可滚、祖先也没有真正的
            #       user 滚动视口 → 被裁内容彻底丢、客户永远看不到 → 顶格 ERR(无视 px
            #       阈值,即便溢出几 px 也是真内容丢失)。pg40/41 手机 mock 属此类。
            #   (a) 可滚出(recoverable):某祖先是真正的 user 滚动视口
            #       (overflow-y:auto|scroll 且有可滚高度)→ 内容能滚出来,危害低 →
            #       维持原 px 分级(小溢出降 warn)。
            #   注意:绝不用"el.scrollTop=N 能不能动"判 recoverable —— overflow:hidden 也
            #   能编程式滚,会判反。producer 按 computed overflow-y 走祖先链判定。
            _recoverable = entry.get('recoverable', False)
            if not _recoverable:
                _clev = iss.warn if entry.get('lifted') else iss.err
                _clev('R-VIS-CARD-OVERFLOW',
                    (('LIFTED slide(逐字搬运)— 降为 WARNING,你决定是否修。 ')
                     if entry.get('lifted') else '') +
                    f'slide {entry["slide_idx"]} · `{entry["selector"]}` has '
                    f'`overflow:hidden` but content ({entry["content_h"]} px) is '
                    f'{entry["overflow_px"]} px taller than the container '
                    f'({entry["card_h"]} px), AND there is NO user-scrollable '
                    'viewport (该盒 overflow-y 是 hidden/clip,user 不可滚;祖先也没有 '
                    'overflow-y:auto|scroll 的真实滚动视口)→ 被裁内容永久不可见 '
                    '(non-recoverable clip),客户永远看不到这部分,内容彻底丢。'
                    'Fix: shorten body copy, drop a row/item, shrink padding/gap, '
                    'increase card height (more stage space), OR drop overflow:hidden '
                    'so the issue is at least visible. (内容丢失是硬伤 — 即便溢出很小'
                    '也顶格 ERROR;lifted 页降 warn 由你定夺。)')
            else:
                _clev = iss.err if _px > 16 else iss.warn
                _clev('R-VIS-CARD-OVERFLOW',
                    f'slide {entry["slide_idx"]} · `{entry["selector"]}` has '
                    f'`overflow:hidden` but content ({entry["content_h"]} px) is '
                    f'{entry["overflow_px"]} px taller than the container '
                    f'({entry["card_h"]} px) — text is being clipped, but the box '
                    'HAS a usable scroll mechanism (内容能滚出来,危害低)。'
                    'Fix: shorten body copy, drop a row/item, shrink padding/gap, '
                    'increase card height (more stage space), OR drop overflow:hidden '
                    'so the clipped content is visible without scrolling.')

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

    for entry in report.get('band_collide', [])[:20]:
        iss.err('R-VIS-BAND-COLLIDE',
            f'slide {entry["slide_idx"]} · 绝对定位内容带 `{entry["band_sel"]}` 压住正文 '
            f'`{entry["content_sel"]}`(交叠 {entry["overlap_x"]}×{entry["overlap_y"]}px)。'
            '底部/顶部内容带(takeaway / cta / principle-band 等有文字有底色的"带")若用 '
            'position:absolute 挂在 .slide 上,运行时画布居中(centerSlideInCanvas)会把 '
            'absolute 元素排除在内容并集外 → 把正文居中进带子下面、视觉重叠(旧 R-OVERLAP '
            '只查同容器兄弟,查不出这种)。Fix:把内容带作为 `.stage`(flex column)最后一个 '
            '流式子元素 + `margin-top` 间隔,让正文+带子作为整体被居中;或把 .stage 调高 / 内容下沉。'
            '绝不靠缩字号或让内容贴边。')

    # ---- R-VIS-DEAD-ANIM · 声明了 animation 但选择器运行时零匹配 (F-57 · 堵 F-51 整类) ----
    # 该页自己的 <style>/custom_css 里某条规则声明了 animation,但其选择器在 present
    # 模式下 document.querySelectorAll() 命中 0 个元素(no-match)或直接解析抛错
    # (parse-error)→ 这条动画永不触发,被它驱动的元素停在动画初态(常是 opacity:0)
    # → 内容永久隐身/永不上滚。最常见成因:lift / 前缀注入用正则啃选择器,把合法的
    # `.slide-frame.is-current` 啃成非法的 `-frame.is-current`(`-frame` 是合法 CSS
    # ident 故能解析,但没有 `<-frame>` 元素 → 永不匹配)。静态 CSS 分析看不出(每条
    # 规则单独读都合法),只有运行时 querySelectorAll 才暴露。err 级(内容隐身是硬伤)。
    for entry in report.get('dead_anim', [])[:20]:
        _why = ('选择器解析失败(伪类 :is()/:has() 等写法非法)'
                if entry.get('reason') == 'parse-error'
                else '选择器运行时零匹配(很可能被前缀注入/lift 啃坏,'
                     '如合法的 `.slide-frame.is-current` 被啃成非法的 `-frame.is-current`)')
        iss.err('R-VIS-DEAD-ANIM',
            f'slide {entry["slide_idx"]} · 该页 CSS 里 `{entry["selector"]}` 声明了 '
            f'animation,但{_why} —— 这条动画永不触发,被它驱动的元素停在动画初态'
            '(通常是 opacity:0 / transform 偏移),内容在投影上永久隐身或永不进场/上滚。'
            'Fix: 把选择器修正到合法、运行时真能命中的形态(常见即把 `-frame.is-current` '
            '还原成 `.slide-frame.is-current`,或把损坏的伪类写对);若该规则本就该删,'
            '连 animation 声明一起删,别留死规则。(几何/DOM 判定,lift 页同样报 err —— '
            '动画静默失效就是真缺陷。)')

    # ---- R-VIS-DEAD-RULE · 声明了重要视觉属性但选择器运行时零匹配 (F-68 · F-57 超集) ----
    # F-57 (dead_anim) 只覆盖 animation。但同一类"规则声明在源里、运行时选择器死掉、
    # 元素静默退回浏览器默认值"的盲区还有非动画属性:冰山 `.hero-pct` 从 100px 死成
    # 16px(16 是合规档,R20/R-VIS-TIER 全绿、无任何闸报警)、`.loop-row` 从 grid 死成
    # block(排版塌掉、无报警)。这条把 dead-selector 判定扩到 position:absolute|fixed /
    # display:grid|flex / font-size≥48px / width|height≥120px 这些一旦失效就视觉塌陷的
    # 重要属性。判定逻辑同 dead_anim:运行时 querySelectorAll 零匹配或解析抛错才算死,
    # 绝不靠"选择器里有没有注释"(`.a /*c*/ .b{}` ≡ 合法的 `.a .b{}`,注释=空白后代组合
    # 子,照常应用,不一定死)。与主区 dead_anim 消费块口径一致:恒 err 不降级(规则静默
    # 失效是硬伤,lift 页同样报 err)。
    _DEAD_RULE_PROP_NOTE = {
        'position':  ('退回 static → 定位元素跑位 / 叠层错乱', 'position:absolute|fixed'),
        'display':   ('退回 block → grid/flex 排版整体塌掉(行/列变竖排)', 'display:grid|flex'),
        'font-size': ('退回浏览器默认 ~16px → hero/大字号文字缩成小字,且 16 是合规档、'
                      '字号闸(R20 / R-VIS-TIER)全绿不会报', '大字号'),
        'width':     ('退回 auto → 尺寸塌缩 / 布局错位', '具体宽度'),
        'height':    ('退回 auto → 尺寸塌缩 / 布局错位', '具体高度'),
    }
    for entry in report.get('dead_rule', [])[:20]:
        _why = ('选择器解析失败(伪类 :is()/:has() 等写法非法)'
                if entry.get('reason') == 'parse-error'
                else '选择器运行时零匹配(很可能被前缀注入/lift 啃坏,'
                     '如合法的 `.slide-frame.is-current` 被啃成非法的 `-frame.is-current`)')
        _effect, _label = _DEAD_RULE_PROP_NOTE.get(
            entry.get('prop'), ('元素退回浏览器默认值', entry.get('prop', '?')))
        iss.err('R-VIS-DEAD-RULE',
            f'slide {entry["slide_idx"]} · 该页 CSS 里 `{entry["selector"]}` 声明了 '
            f'`{entry["prop"]}: {entry.get("value", "")}`({_label}),但{_why} —— '
            f'这条规则永不生效,被它本该驱动的元素静默{_effect}。源里逐条读都合法、'
            '字号/排版闸全绿,只有运行时 querySelectorAll 才暴露。'
            'Fix: 把选择器修正到合法、运行时真能命中的形态(常见即把 `-frame.is-current` '
            '还原成 `.slide-frame.is-current`,或把损坏的伪类写对);若该规则本就该删,'
            '连声明一起删,别留死规则。(几何/DOM 判定,lift 页同样报 err —— '
            '规则静默失效就是真缺陷。)')

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
        # grow-box verdict (改大自动拉高): if the box has room, enlarging to the
        # floor + growing the box is the fix; if not, content must be cut.
        _cg = entry.get('can_grow')
        if _cg is True:
            _fix = (f' 修法→ 提到 24 + 框自动长高(改大自动拉高):需约 '
                    f'{entry.get("grow_needed_px","?")}px,框/画布余 '
                    f'{entry.get("room_px","?")}px,装得下。永不缩字号。')
        elif _cg is False:
            _fix = (f' 修法→ 提到 24 后空间不够(需 {entry.get("grow_needed_px","?")}px,'
                    f'仅余 {entry.get("room_px","?")}px):压字数/删条目,而非缩字号。')
        else:
            _fix = ' 修法→ 提到 24(优先),内容超框则拉高框 / 压字数,永不缩字号。'
        _lev('R-VIS-BODY-FLOOR',
            (('LIFTED slide (verbatim from another deck) — downgraded to '
              'WARNING, you choose whether to bump. ') if entry.get('lifted') else '') +
            f'slide {entry["slide_idx"]} · `{entry["selector"]}` renders at '
            f'{entry["rendered_px"]}px but its direct text is '
            f'{entry["char_count"]} chars ("{entry["preview"]}"). '
            'Body content (≥ 8 chars of sentence-like text outside mockup '
            'containers and chrome classes) must be ≥ 24 px on projector.' +
            _fix +
            ' (Or rename to a chrome class .eyebrow/.footnote/.source/.pill/'
            '.tag/.chip/.badge/.pageno/.demo-tag if it really is chrome, OR set '
            '`data-allow-body-floor` for a documented exception.)')

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
        elif kind == 'dead-band':
            iss.warn('R-VIS-BALANCE',
                f'slide {entry["slide_idx"]} · `{entry["container_sel"]}` '
                f'中间留白 {entry["gap_px"]}px(dead-band)— `{entry["between_a"]}` '
                f'和 `{entry["between_b"]}` 之间有一条 >140px 的空带,'
                '页面被切成两半。Fix: (1) 容器去掉 `flex: 1` / `justify-content: '
                'space-between`(BF9 反模式经常制造这种空白);(2) 缩小 gap;(3) '
                '在中间加一行 supporting 元素(pullquote / KPI / divider);(4) '
                '确实是设计意图(留白让 hero 呼吸)→ 加 `data-allow-imbalance`。')
        elif kind == 'side-empty':
            _side = '右侧' if entry['right_slack'] > entry['left_slack'] else '左侧'
            iss.warn('R-VIS-BALANCE',
                f'slide {entry["slide_idx"]} · `{entry["container_sel"]}` '
                f'横向失衡 / 单侧空壳(side-empty): 左空 {entry["left_slack"]}px / '
                f'右空 {entry["right_slack"]}px(容器宽 {entry["body_width"]}px)— '
                f'真实内容(文字/图)挤向一边,{_side}一大块空(空框不算内容)。'
                '常见 #36「右半是个空壳面板」/ 内容偏左。Fix: (1) 给空的一侧填真内容 '
                '(图示 / 截图重建 / 要点);(2) 缩窄空面板、让内容两栏铺满;(3) 单列'
                '窄条飘着 → 加宽或配伴随块。真有图但被判空说明图是 media→已计入不会误报;'
                '故意留白 → `data-allow-imbalance`。')

    # ---- R-VIS-CANVAS-CENTER · 内容整体在"画布"里垂直居中 (2026-05-31) ----
    # R-VIS-BALANCE 只看"内容在 body 容器(.stage)内部"的上下留白是否均衡 —— 但
    # 当 .stage 本身相对画布偏上时(如对称定位 top:200/bottom:200,中心 540,而画布
    # 中心 ~597),内容在 .stage 内部均衡却整体偏上,balance 检测不出 → 漏报。这条补
    # 这个洞:画布 = [主标题.header 底边 → 屏幕底 1080];内容并集(排除 .header)的垂直
    # 中心 content_mid 应 ≈ 画布中心 canvas_mid = (hb + 1080)/2。offset = canvas_mid
    # - content_mid(正=偏上,负=偏下)。is_full(内容比可用带还高、居中必然溢出画布)豁免
    # ——这种顶对齐/溢出是对的。注意 is_full ≠"填满 72%":那种"两框带 gap 占 83% 但整体偏上"
    # 的页放得下、应该居中,旧 0.72 阈值会误豁免(见 visual-audit.js 注释)。几何 name-free。
    # Warn 级(留白判断主观,可 opt-out)。运行时 feishu-deck.js 已就地居中=本规则通常静默。
    for entry in report.get('canvas_center', [])[:20]:
        if entry.get('is_full'):
            continue
        offset = entry['offset']
        if abs(offset) <= 40:
            continue
        _dir = '偏上' if offset > 0 else '偏下'
        iss.warn('R-VIS-CANVAS-CENTER',
            f'slide {entry["slide_idx"]} · `{entry["container_sel"]}` '
            f'内容整体未在[标题底→屏幕底]画布垂直居中:{_dir} {abs(offset)}px'
            f'(内容中心 {entry["content_mid"]}px / 画布中心 {entry["canvas_mid"]}px)'
            ' —— 内容在 .stage 内部看似均衡,但 .stage 相对画布整体偏移,所以全页'
            '看着上空/下空。这跟 R-VIS-BALANCE 互补:balance 看内容在容器内部的上下'
            '留白,这条看内容并集中心 vs 画布([主标题底边→1080])中心。'
            'Fix: 内容并集应在 [标题底→屏幕底] 画布里垂直居中;根因常是 .stage 用对称'
            '定位(top/bottom 相等)使中心固定 540,而画布中心因标题占顶被推到 ~597 → '
            '整体偏上。正解在 framework:让 content 的 .grid `flex:1` 撑满 stage + '
            '`align-content:center`(稀疏自动居中、满铺自动顶对齐铺满);或确属设计意图 '
            '→ 在 .slide 加 `data-allow-imbalance` 跳过。')

    # ---- R-VIS-CROWD · 框内文字挤到底边 (2026-05-30) ----
    # 框内文字离卡片可见底边过近且明显下偏 = "文字离下面太近"(qingdao 3up 等高卡
    # 实测离底 5px / 顶部 34px)。几何 name-free,不按版式名:松(下方大留白,如
    # KPI 列顶基线对齐)下内距大、不触发,stats 类天然豁免。warn 级(--strict 升 err)。
    for entry in report.get('crowd', [])[:20]:
        iss.warn('R-VIS-CROWD',
            f'slide {entry["idx"]} · `{entry["sel"]}` 框内文字贴底 —— 内容离框可见底边'
            f'只剩 {entry["bottom_px"]}px,顶部却留 {entry["top_px"]}px,文字被挤到框底。'
            'Fix: 让卡片按内容尺寸 + 垂直居中(参考 content-3up `align-self: center; '
            'justify-content: center`),或给框一个最小下内距 / 减少该框内容;'
            '若等高框内文字贴底是刻意设计 → 在 `.slide` 加 `data-allow-imbalance`。')

    # R-VIS-PANEL-TOP · 框内单内容贴顶、下方大片空(crowd 的反向孪生,2026-06-01 pg29)。
    # 一个 framed 面板容器(.col-visual / lifted .product-pane/.copy-pane/.case-pane)装着
    # 一个比容器矮一大截的单内容块,内容贴顶、下方留大空 = 面板没把内容垂直居中。
    # 框架已给 content-2col 的 .col-visual 单子加 flex 居中默认;这条兜 lifted/raw 页里
    # 自定义 panel 容器仍贴顶的情况。warn 级(--strict 升 err),data-allow-imbalance 跳过。
    for entry in report.get('panel_top', [])[:20]:
        iss.warn('R-VIS-PANEL-TOP',
            f'slide {entry["idx"]} · `{entry["sel"]}` 面板内单内容贴顶 —— 内容高 '
            f'{entry["content_h"]}px 只占框 {entry["box_h"]}px 的一部分,顶距 '
            f'{entry["top_px"]}px、底部却空了 {entry["bottom_px"]}px,内容卡在框顶。'
            'Fix: 给该面板容器(panel/pane/col-visual 类)加 `display:flex; '
            'flex-direction:column; justify-content:center`,让单内容在框内垂直居中'
            '(框架已对 content-2col `.col-visual` 单子默认居中;lifted/raw 页的自定义 '
            'panel 需在该页 `custom_css` 补这条);若刻意顶对齐 → `.slide` 加 '
            '`data-allow-imbalance`。')

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

    for entry in report.get('peer_size', [])[:20]:
        _off = ", ".join(f'`{o["sel"]}`={o["px"]}px' for o in entry.get('offenders', [])[:3])
        iss.warn('R-VIS-PEER-SIZE',
            f'slide {entry["slide_idx"]} · `{entry["container_sel"]}` 内同角色 '
            f'`{entry["role"]}` 字号不一致:多数 {entry["majority_px"]}px,'
            f'但 {_off} 偏离(本组出现 {sorted(entry["sizes"])} 多种尺寸)。'
            '同一并列容器里同角色的 sibling 应等大 —— "有大有小"靠这条抓。'
            'Fix:把偏离者统一到多数派字号(按角色给一档);若确为有意不同 → '
            '元素或祖先加 `data-allow-peer-size`。')

    for entry in report.get('gutter', [])[:20]:
        # 间距判断有主观成分 → warn;lifted 页(逐字搬运)降 warn_soft。
        _lev = iss.warn_soft if entry.get('lifted') else iss.warn
        _pre = ('LIFTED slide(逐字搬运)— 降为软提示。 ' if entry.get('lifted') else '')
        if entry['kind'] == 'gutter':
            _lev('R-VIS-GUTTER', _pre +
                f'slide {entry["slide_idx"]} · `{entry["container_sel"]}` 同组相邻框'
                f'({entry["axis"]})间距不等:{entry["gutters"]}px(min {entry["min_px"]} / '
                f'max {entry["max_px"]})。同组框 gutter 应相等才齐整(P7 #3:卡片左右 '
                '28px 但到下面只 8px)。Fix:把 gap 统一;故意不均 → .slide 加 '
                '`data-allow-imbalance`。')
        else:
            _lev('R-VIS-GUTTER', _pre +
                f'slide {entry["slide_idx"]} · `{entry["container_sel"]}` 同 tag '
                f'`{entry["cell_tag"]}` 组框的内 padding 不一致:{entry["pads"]}px'
                f'(min {entry["min_px"]} / max {entry["max_px"]})。同类 cell 内容到'
                '边框的距离应一致才好看(P7 #4)。Fix:统一 padding / 让内容等距居中。')

    for entry in report.get('hero_floor', [])[:20]:
        _lev = iss.warn_soft if entry.get('lifted') else iss.warn
        _lev('R-VIS-HERO-FLOOR',
            f'slide {entry["slide_idx"]} (layout `{entry["layout"]}`) · '
            f'{entry["role"]} `{entry["selector"]}` 渲染 {entry["rendered_px"]}px,'
            f'低于该版式 hero 下限 {entry["floor_px"]}px(master 规格约 '
            f'{entry["spec_px"]}px)→ 偏小、不够大气(P11 封面 82<100)。方向是'
            '"够不够大"不是"在不在白名单":hero 主元素该走 layout 规定尺寸。'
            'Fix:放大到 master 规格;若刻意做小变体 → 加 `data-allow-typescale`。')

    for entry in report.get('short_label_floor', [])[:20]:
        _lev = iss.warn_soft if entry.get('lifted') else iss.warn
        _svg = ' (SVG 轴标)' if entry.get('is_svg') else ''
        _lev('R-VIS-SHORT-LABEL-FLOOR',
            f'slide {entry["slide_idx"]} · `{entry["selector"]}`{_svg} 短标签 '
            f'"{entry["text"]}"({entry["char_count"]} 字)渲染 {entry["rendered_px"]}px '
            '< 18px,投影看不清。R-VIS-BODY-FLOOR 的「≥8 字」门槛放过了这种短轴标/'
            '分类标签,这条专补(含 SVG 轴标)。Fix:放大到 ≥18(图表轴标)/24(正文);'
            '若确为单位/装饰 → 元素加 `data-allow-body-floor`。')

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
        # visual-audit.js holds CJK bytes; a bare .read_text() decodes with the
        # locale default, which under C/POSIX (the default in minimal Linux
        # containers / CI) is ASCII and raises UnicodeDecodeError — crashing the
        # DEFAULT validate path. Pin UTF-8 so it's locale-independent.
        _VISUAL_AUDIT_JS_CACHE = (
            Path(__file__).resolve().parent / 'visual-audit.js'
        ).read_text(encoding='utf-8')
    return _VISUAL_AUDIT_JS_CACHE


def inline_linked(html_text, base_dir):
    """Inline <link rel=stylesheet> / <script src> into the HTML so audits can
    see framework CSS/JS content. External (http/https/data:) refs and missing
    files are left untouched. Shared by main() here and check-only.py — was
    copy-pasted in both, unified per F-14."""
    def repl_link(m):
        tag = m.group(0)
        # Order-independent: match ANY <link> tag, inline only if it's a local
        # stylesheet. The old `rel="stylesheet" … href=` regex missed
        # `<link href="…" rel="stylesheet">`, so that framework CSS was
        # invisible to the audits (they then under-reported).
        if 'rel="stylesheet"' not in tag:
            return tag
        hm = re.search(r'href="([^"]+)"', tag)
        if not hm:
            return tag
        href = hm.group(1)
        if href.startswith(('http:', 'https:', 'data:')): return tag
        target = (base_dir / href).resolve()
        if not target.is_file(): return tag
        return ('<style data-source="framework">'
                + target.read_text(encoding='utf-8')
                + '</style>')
    html_text = re.sub(r'<link\b[^>]*>', repl_link, html_text)
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
    (audit_doc_integrity,      ('html', 'iss')),
    (audit_escaped_html,       ('slides', 'iss')),
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
    (audit_ui_mocks_are_html,  ('html', 'iss')),
    (audit_no_cyan_accent,     ('slides', 'iss')),
    (audit_header_minimal,     ('slides', 'iss')),
    (audit_slide_keys,         ('slides', 'iss')),
    (audit_language_policy,    ('html', 'slides', 'iss')),
    (audit_list_echo,          ('slides', 'iss')),
    (audit_visual_richness,    ('slides', 'iss')),
    (audit_raw_looks_schema,   ('slides', 'iss', 'path')),
    (audit_self_contained,     ('html', 'iss')),
    (audit_autobalance_present, ('html', 'iss')),
    (audit_perf,               ('html', 'iss')),
]


def run_static_audits(audits, *, html, slides, path, iss):
    """Run a registry of (audit_fn, arg-order) entries against one context."""
    ctx = {'html': html, 'slides': slides, 'path': path, 'iss': iss}
    for fn, sig in audits:
        fn(*(ctx[a] for a in sig))


def filter_issues_to_slide(slide_arg, slides, iss):
    """F-254 · diagnostic single-slide filter.

    Mutate `iss` in place, keeping only findings that pertain to ONE slide so a
    one-page edit isn't buried in deck-wide pre-existing noise. `slide_arg` is a
    data-slide-key ("cover") or a 1-based ordinal ("30" / "#30"). A finding
    matches when its message contains `data-slide-key="<key>"` OR `slide <N>`
    (the two conventions every audit emits). Returns a short human note.
    """
    idx_to_key = {}
    for i, s in enumerate(slides, 1):
        m = re.search(r'data-slide-key="([^"]+)"', s)
        if m:
            idx_to_key[i] = m.group(1)
    key_to_idx = {v: k for k, v in idx_to_key.items()}

    arg = slide_arg.strip().lstrip('#')
    if arg.isdigit():
        ordinal = int(arg)
        key = idx_to_key.get(ordinal)
    else:
        key = arg
        ordinal = key_to_idx.get(key)

    known = (key in key_to_idx) or (ordinal in idx_to_key)

    def _match(msg):
        if key and f'data-slide-key="{key}"' in msg:
            return True
        if ordinal and re.search(rf'\bslide {ordinal}\b', msg):
            return True
        return False

    iss.errors        = [e for e in iss.errors        if _match(e[1])]
    iss.warnings      = [w for w in iss.warnings      if _match(w[1])]
    iss.soft_warnings = [w for w in iss.soft_warnings if _match(w[1])]

    label = (f'#{ordinal} {key}' if (ordinal and key)
             else f'#{ordinal}' if ordinal else (key or arg))
    if not known:
        return (f'⚠ slide "{slide_arg}" not found among {len(slides)} slides — '
                'matched by substring anyway (0 findings likely means a typo).')
    return f'filtered to slide {label}'


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
                        'card). '
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
    p.add_argument('--slide', metavar='KEY_OR_N', default=None,
                   help='Diagnostic single-slide filter (F-254): keep only '
                        'findings for ONE slide — by data-slide-key (e.g. '
                        '"cover") or 1-based ordinal (e.g. "30" / "#30"). Exit '
                        'code reflects ONLY that slide. Use when editing a single '
                        'page so its findings are not buried in deck-wide '
                        'pre-existing noise. Does NOT change which audits run — '
                        'only what is reported/exited on; NOT a delivery gate.')
    args = p.parse_args()
    if args.screenshots and not args.visual:
        args.visual = True   # --screenshots implies --visual

    path = Path(args.html)
    if not path.is_file():
        print(f'ERROR: file not found: {path}', file=sys.stderr)
        return 2

    html = path.read_text(encoding='utf-8')
    # `slides` is still needed for the human header count (`slides: N`) and the
    # --slide diagnostic filter. extract_slides reads the raw frame markup; the
    # engine does its OWN framework inlining / rendering, so we no longer need
    # inline_linked here on the rule path (kept as a public helper for
    # check-only / tests via F-14).
    slides = extract_slides(html)

    iss = Issues()
    # UNIFY-VALIDATE-ARCH: ALL rule findings come from the single unified engine
    # (audits.js on the rendered DOM + runner byte/source rules). No more
    # STATIC_AUDITS / visual-audit.js dual registries. `--strict` still promotes
    # warnings → errors after the run (see end of main()).
    #   · DEFAULT (`--visual`): full engine — geometry / DOM-text / structure +
    #     byte/source rules. Needs playwright; degrades to byte/source-only +
    #     advisory if Chromium is unavailable (never blocks a good deck on a CI
    #     hiccup; never a silent green either).
    #   · `--no-visual`: byte/source rules ONLY (no browser). A documented
    #     PARTIAL check — the DOM/geometry rules (R-VIS-*, R06/R20/R10/R-DOM/…)
    #     do not run. Use only where Chromium is unavailable.
    try:
        run_unified_audits(path, iss, dom_rules=args.visual,
                           want_screenshots=args.screenshots)
    except Exception as e:
        # The engine adapter should self-degrade; a leak here must still never
        # crash the whole validate — emit a soft advisory and continue so any
        # findings already folded in survive.
        iss.warn_soft('R-VISUAL',
            f'unified engine failed ({type(e).__name__}: {e}) — '
            'findings may be incomplete.')

    slide_filter_note = None
    if args.slide is not None:
        slide_filter_note = filter_issues_to_slide(args.slide, slides, iss)

    if args.strict:
        # Promote regular warnings to errors. SOFT warnings (R-VIS-NO-IMAGERY,
        # R-SELF-CONTAINED, etc.) stay as warnings — they are editorial
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
    if slide_filter_note:
        print(f'  ⟂ {slide_filter_note} · F-254 single-slide diagnostic (NOT a delivery gate)')
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
