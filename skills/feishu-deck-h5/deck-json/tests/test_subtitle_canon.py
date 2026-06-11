"""F-294 · R-VIS-SUBTITLE-CANON lock-in.

The title subtitle has ONE canonical form: a `<p class="page-sub">` directly
after the `<h2>` INSIDE `.header` (framework `.slide .header .page-sub` =
title +36px, --fs-sub 28px, #fff, one uniform position). Improvised subtitles
(`.lede` / `.subtitle` / bare `<div>` / inline-styled `<p>`) drift in position
and size per page ("副标位置都不一样"). R-VIS-SUBTITLE-CANON (name-free, WARN)
flags any text-bearing element AFTER the title inside `.header` whose class is
not `page-sub`.

Critical boundary: the rule scans `.header` ONLY. A body lead-in `.lede` inside
`.stage` is NOT a title subtitle and must NEVER be flagged.

Evaluated against the rendered DOM via the shared unified engine (same
run_unified_engine validate.py / render-deck use); requires Chromium, skips
gracefully if unavailable.
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402

RULE = "R-VIS-SUBTITLE-CANON"


def _frame(layout, body, *, attrs="", key="k"):
    return (
        f'<div class="slide-frame"><div class="slide" data-layout="{layout}" '
        f'data-screen-label="x" data-slide-key="{key}" {attrs}>{body}</div></div>'
    )


def _run(html_or_slides):
    E.skip_if_no_engine()
    return E.findings_for(RULE, html_or_slides)


# ----------------------------------------------------------------------------
# wiring: the rule is actually emitted by the single engine source
# ----------------------------------------------------------------------------

def test_rule_is_declared_in_engine():
    assert E.rule_in_engine(RULE), f"{RULE} not declared in audits.js"


# ==========================================================================
# MUST FIRE — improvised header subtitle
# ==========================================================================

def test_fires_on_div_lede_in_header():
    # `.header` with a non-canonical <div class="lede"> after the title.
    body = (
        '<div class="header">'
        '<h2 class="title-zh">Individual gains</h2>'
        '<div class="lede">When everyone gets faster, the bottleneck moves.</div>'
        '</div>'
    )
    hits = _run([_frame("raw", body)])
    assert len(hits) >= 1, f"div.lede header subtitle must fire {RULE}: {hits}"
    # message must point authors to the canonical form
    assert "page-sub" in hits[0]["message"], hits[0]["message"]


def test_fires_on_inline_styled_p_in_header():
    # The blueprint case: an inline-styled <p> (not .page-sub) after the title.
    body = (
        '<div class="header">'
        '<h2 class="title-zh">Bytedance blueprint</h2>'
        '<p class="lede" style="font-size:22px;margin-top:10px;">Dual engines</p>'
        '</div>'
    )
    hits = _run([_frame("raw", body)])
    assert len(hits) >= 1, f"inline-styled header subtitle must fire {RULE}: {hits}"


def test_fires_on_bare_div_subtitle_in_header():
    # An unclassed bare <div> carrying subtitle text after the title.
    body = (
        '<div class="header">'
        '<h2 class="title-zh">Some title</h2>'
        '<div>A subtitle line with no class at all.</div>'
        '</div>'
    )
    hits = _run([_frame("content", body)])
    assert len(hits) >= 1, f"bare-div header subtitle must fire {RULE}: {hits}"


def test_fires_on_subtitle_class_in_header():
    # `.subtitle` is cover-only; using it in a content/raw .header is non-canonical.
    body = (
        '<div class="header">'
        '<h2 class="title-zh">Some title</h2>'
        '<p class="subtitle">A misplaced cover subtitle.</p>'
        '</div>'
    )
    hits = _run([_frame("content", body)])
    assert len(hits) >= 1, f".subtitle in content header must fire {RULE}: {hits}"


# ==========================================================================
# MUST NOT FIRE
# ==========================================================================

def test_no_fire_on_canonical_page_sub():
    # The canonical form — <p class="page-sub"> after the title inside .header.
    body = (
        '<div class="header">'
        '<h2 class="title-zh">飞书与企微,已经不是同一类产品</h2>'
        '<p class="page-sub">下一代协同 vs 上一代 IM</p>'
        '</div>'
    )
    hits = _run([_frame("raw", body)])
    assert hits == [], f"canonical .page-sub must NOT fire {RULE}: {hits}"


def test_no_fire_on_title_only_header():
    body = '<div class="header"><h2 class="title-zh">Just a title</h2></div>'
    hits = _run([_frame("content", body)])
    assert hits == [], f"title-only header must NOT fire {RULE}: {hits}"


def test_no_fire_on_body_lede_in_stage():
    # THE protected case: a body lead-in .lede lives inside .stage, not .header.
    # The rule is scoped to .header → this must stay silent.
    body = (
        '<div class="header"><h2 class="title-zh">Digital employees</h2></div>'
        '<div class="stage">'
        '<p class="lede">Digital employees are the real units of productivity.</p>'
        '<div class="ds-row">body content</div>'
        '</div>'
    )
    hits = _run([_frame("raw", body)])
    assert hits == [], f"body .lede in .stage must NOT fire {RULE}: {hits}"


def test_no_fire_on_lede_bar_in_stage():
    # The other protected variant: .lede-bar inside .stage.
    body = (
        '<div class="header"><h2 class="title-zh">Not a 1:1 copy</h2></div>'
        '<div class="stage">'
        '<p class="lede-bar">A digital employee is not a clone.</p>'
        '</div>'
    )
    hits = _run([_frame("raw", body)])
    assert hits == [], f".lede-bar in .stage must NOT fire {RULE}: {hits}"


def test_no_fire_on_eyebrow_in_header():
    # An eyebrow is R56's domain (it sits ABOVE the title). To avoid a
    # double-report, this rule skips eyebrow-classed elements even when they
    # follow the title.
    body = (
        '<div class="header">'
        '<h2 class="title-zh">Some title</h2>'
        '<span class="eyebrow">SECTION TAG</span>'
        '</div>'
    )
    hits = _run([_frame("content", body)])
    assert hits == [], f"eyebrow (R56 domain) must NOT fire {RULE}: {hits}"


def test_no_fire_on_hero_layout():
    # Hero layouts (cover/section/image-text/end/quote) own their title patterns.
    body = (
        '<div class="header">'
        '<h2 class="title-zh">Section title</h2>'
        '<p class="lede">A section subtitle that hero layouts allow.</p>'
        '</div>'
    )
    hits = _run([_frame("section", body)])
    assert hits == [], f"hero layout must be skipped by {RULE}: {hits}"


def test_no_fire_on_empty_logo_div_after_title():
    # A non-text element after the title (e.g. an empty wordmark/logo div) is not
    # a subtitle → must not fire (rule only targets text-bearing elements).
    body = (
        '<div class="header">'
        '<h2 class="title-zh">Some title</h2>'
        '<div class="wordmark"></div>'
        '</div>'
    )
    hits = _run([_frame("content", body)])
    assert hits == [], f"empty logo div must NOT fire {RULE}: {hits}"
