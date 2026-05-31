"""R-VIS-* raw-coverage regression tests (2026-05-31).

Does each newly-added visual rule fire on a ``layout:raw`` slide whose markup
uses ARBITRARY (non-framework) class names?  That is the worst case for a raw /
hand-built / imported deck: the slide is rendered and audited (``raw`` is NOT in
``HERO_LAYOUTS``), but a rule whose candidate selector keys on framework classes
(``.stage`` / ``.header`` / ``.grid`` / ``.card`` / ``CARD_KEYS`` …) finds zero
candidates and silently passes.

Methodology mirrors the sibling per-rule tests (``test_vis_gutter`` etc.): read
``assets/visual-audit.js``, run it in headless Chromium via ``set_content`` with a
minimal, geometry-self-contained fixture (all sizes inline — no framework CSS), and
inspect the report bucket.

Empirically verified raw coverage (workflow wgry1zvgg, real render + Chromium):

  COVERED — name-free geometry, fires on raw:
    R-VIS-GUTTER            (_isFramedBox geometry, any flex/grid container)
    R-VIS-SHORT-LABEL-FLOOR (computed fontSize<18 over '*, text, tspan')
    R-VIS-CROWD             (_isFramedBox + content-union geometry)

  RAW ESCAPES — schema-class / layout gated, marked xfail(strict) below:
    R-VIS-HERO-FLOOR    HERO_FLOORS keyed by layout NAME (no 'raw') + KPI_FLOOR
                        class-gated on .kpi-val/.kpi .v/.metric-value  (visual-audit.js:1428,1463-1464)
    R-VIS-PEER-SIZE     roleOf() needs BODY_KEYS/META_KEYS substring AND
                        parallelAnchor() needs PEER_PARALLEL/GRID_KEYS/CARD_KEYS/
                        CARD_SUFFIX ancestor                            (visual-audit.js:1292-1300)
    R-VIS-BALANCE       bodyContainer = :scope > .stage|.grid|.flow|.nodes|.toc|
                        .table-wrap|.stack, no fallback to the slide   (visual-audit.js:930-936)
    R-VIS-CARD-OVERFLOW candidate query slide.querySelectorAll('.stage *')   (visual-audit.js:248)
    R-VIS-TITLE-GAP     requires :scope > .header AND :scope > .stage   (visual-audit.js:387,407)

Each escape rule has TWO tests: a ``*_schema_control`` (plain assert) proving the
fixture geometry genuinely fires under the framework class — so a green xfail is not
hiding a weak fixture — and a ``*_raw_fires`` marked ``xfail(strict=True)``.  The
xfail asserts the CORRECT behavior (the rule SHOULD fire on raw); it xfails today and
flips to a FAILURE the moment the selector is made name-free — that is the signal to
delete the marker and keep the now-passing raw assertion.

See SKILL.md "raw = markup 不采用标准框架 class 骨架" and the LIFT/raw discussion.
"""
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve()
ASSETS = HERE.parents[2] / "assets"
AUDIT = ASSETS / "visual-audit.js"
VALIDATE = ASSETS / "validate.py"


# --------------------------------------------------------------------------- #
# harness                                                                      #
# --------------------------------------------------------------------------- #
def _run(html):
    """Run visual-audit.js against `html` in headless Chromium; return the report
    dict, or None if Playwright/Chromium is unavailable (caller skips)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    audit = AUDIT.read_text(encoding="utf-8")
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_context(viewport={"width": 1920, "height": 1080}).new_page()
            pg.set_content(html)
            pg.wait_for_timeout(150)
            rep = pg.evaluate("(" + audit + ")()")
            b.close()
    except Exception:
        return None
    return rep


def _bucket(html, name, kind=None):
    rep = _run(html)
    if rep is None:
        pytest.skip("Chromium/Playwright unavailable")
    rows = rep.get(name, [])
    if kind is not None:
        rows = [r for r in rows if r.get("kind") == kind]
    return rows


def _slide(layout, inner):
    return (
        '<div class="slide" data-layout="' + layout + '" data-slide-key="t">'
        + inner + "</div>"
    )


_BORDER = "border:1px solid #888"


# --------------------------------------------------------------------------- #
# wiring sanity (no browser needed)                                            #
# --------------------------------------------------------------------------- #
def test_buckets_declared_and_mapped():
    """Every bucket these tests inspect must be declared in visual-audit.js's
    `out = {...}` and consumed in validate.py — else a rename silently zeroes the
    rule and every raw/schema assertion here would skip-pass on an empty list."""
    js = AUDIT.read_text(encoding="utf-8")
    vy = VALIDATE.read_text(encoding="utf-8")
    for bucket in ("gutter", "short_label_floor", "crowd", "hero_floor",
                   "peer_size", "balance", "card_overflow", "title_gap"):
        assert bucket + ": []" in js, f"bucket {bucket} not declared in visual-audit.js"
        assert "report.get('" + bucket + "'" in vy, f"bucket {bucket} not mapped in validate.py"


# --------------------------------------------------------------------------- #
# COVERED — name-free, must fire on raw markup with arbitrary classes          #
# --------------------------------------------------------------------------- #
def test_gutter_raw_fires():
    box = f'<div class="zzbox" style="{_BORDER};width:200px;height:100px;'
    inner = (
        '<div class="zzrow" style="display:flex">'
        + box + 'margin-right:8px"></div>'
        + box + 'margin-right:60px"></div>'
        + box + '"></div>'
        + "</div>"
    )
    hits = _bucket(_slide("raw", inner), "gutter", kind="gutter")
    assert len(hits) >= 1, f"R-VIS-GUTTER should fire on raw uneven [8,60] gutters; got {hits}"


def test_short_label_raw_fires():
    inner = '<div class="zzlabel" style="font-size:14px">营收</div>'
    hits = _bucket(_slide("raw", inner), "short_label_floor")
    assert len(hits) >= 1, f"R-VIS-SHORT-LABEL-FLOOR should fire on raw 14px short label; got {hits}"


def test_crowd_raw_fires():
    # 220px framed box, text pushed to the bottom (padding-top 195) → text ~4px
    # from the visible bottom edge, ~196px from the top → distBottom<10 & distTop>distBottom+16.
    inner = (
        f'<div class="zzbox" style="{_BORDER};width:320px;height:220px;'
        'padding-top:195px;box-sizing:border-box">'
        '<span style="font-size:16px;line-height:20px">底部文字内容</span></div>'
    )
    hits = _bucket(_slide("raw", inner), "crowd")
    assert len(hits) >= 1, f"R-VIS-CROWD should fire on raw bottom-crowded framed box; got {hits}"


# --------------------------------------------------------------------------- #
# RAW ESCAPES — control proves geometry; raw xfail(strict) documents the gap   #
# --------------------------------------------------------------------------- #

# ---- R-VIS-HERO-FLOOR ----
def test_hero_floor_schema_control():
    inner = '<h1 class="title-zh" style="font-size:70px;margin:0">封面主标题</h1>'
    hits = _bucket(_slide("cover", inner), "hero_floor")
    assert len(hits) >= 1, f"control: hero floor must fire on cover h1@70px (<88); got {hits}"


@pytest.mark.xfail(strict=True, reason=(
    "R-VIS-HERO-FLOOR raw escape: HERO_FLOORS keyed by layout name (no 'raw') and "
    "KPI_FLOOR class-gated on .kpi-val/.kpi .v/.metric-value (visual-audit.js:1428,1463-1464). "
    "Fix: pick the largest visible font on a non-hero-excluded slide vs a per-layout-OR-default "
    "floor; then delete this marker."))
def test_hero_floor_raw_fires():
    inner = '<div class="zzheadline" style="font-size:70px">封面主标题</div>'
    hits = _bucket(_slide("raw", inner), "hero_floor")
    assert len(hits) >= 1, f"R-VIS-HERO-FLOOR should fire on raw 70px hero (<88); got {hits}"


# ---- R-VIS-PEER-SIZE ----
def _peer_inner(wrap_cls, item_cls):
    return (
        f'<div class="{wrap_cls}">'
        f'<div class="{item_cls}" style="font-size:30px">甲方</div>'
        f'<div class="{item_cls}" style="font-size:18px">乙方</div>'
        "</div>"
    )


def test_peer_size_schema_control():
    # verdict-grid ∈ PEER_PARALLEL, .desc ∈ BODY_KEYS → both peers share the anchor.
    hits = _bucket(_slide("content", _peer_inner("verdict-grid", "desc")), "peer_size")
    assert len(hits) >= 1, f"control: peer-size must fire on verdict-grid .desc 30/18px; got {hits}"


@pytest.mark.xfail(strict=True, reason=(
    "R-VIS-PEER-SIZE raw escape: roleOf() needs a BODY_KEYS/META_KEYS substring AND "
    "parallelAnchor() needs a PEER_PARALLEL/GRID_KEYS/CARD_KEYS / -card|-tile|-cell|-panel|-box "
    "ancestor (visual-audit.js:1292-1300); arbitrary zz* classes drop out. "
    "Fix: bucket by a name-free anchor (nearest flex/grid common parent) + geometric role; "
    "then delete this marker."))
def test_peer_size_raw_fires():
    hits = _bucket(_slide("raw", _peer_inner("zzgrid", "zztext")), "peer_size")
    assert len(hits) >= 1, f"R-VIS-PEER-SIZE should fire on raw 30/18px peers; got {hits}"


# ---- R-VIS-BALANCE (side-empty) ----
def _balance_inner(wrap_cls):
    return (
        f'<div class="{wrap_cls}" style="width:1000px;height:400px;position:relative">'
        '<div style="width:300px;height:200px;background:#345;color:#fff">左侧内容文字</div>'
        "</div>"
    )


def test_balance_side_empty_schema_control():
    hits = _bucket(_slide("content", _balance_inner("stage")), "balance", kind="side-empty")
    assert len(hits) >= 1, f"control: side-empty must fire on .stage with 700px empty right; got {hits}"


@pytest.mark.xfail(strict=True, reason=(
    "R-VIS-BALANCE raw escape: bodyContainer = :scope > .stage|.grid|.flow|.nodes|.toc|"
    ".table-wrap|.stack with NO fallback to the slide (visual-audit.js:930-936); arbitrary raw "
    "children → bodyContainer=null → whole balance block skipped. "
    "Fix: fall back to the slide itself / largest non-chrome direct child; then delete this marker."))
def test_balance_side_empty_raw_fires():
    hits = _bucket(_slide("raw", _balance_inner("zzstage")), "balance", kind="side-empty")
    assert len(hits) >= 1, f"R-VIS-BALANCE side-empty should fire on raw lopsided grid; got {hits}"


# ---- R-VIS-CARD-OVERFLOW ----
def _overflow_inner(wrap_cls):
    return (
        f'<div class="{wrap_cls}">'
        '<div class="zzcard" style="height:60px;overflow:hidden">'
        '<div style="height:200px">内容内容内容内容内容</div></div>'
        "</div>"
    )


def test_card_overflow_schema_control():
    hits = _bucket(_slide("content", _overflow_inner("stage")), "card_overflow")
    assert len(hits) >= 1, f"control: card-overflow must fire on clipped .stage card; got {hits}"


@pytest.mark.xfail(strict=True, reason=(
    "R-VIS-CARD-OVERFLOW raw escape: sole candidate query is slide.querySelectorAll('.stage *') "
    "(visual-audit.js:248); a raw slide with no .stage ancestor enqueues zero candidates. "
    "Fix: broaden to slide.querySelectorAll('*') (excluding .slide/.slide-frame); then delete marker."))
def test_card_overflow_raw_fires():
    hits = _bucket(_slide("raw", _overflow_inner("zzwrap")), "card_overflow")
    assert len(hits) >= 1, f"R-VIS-CARD-OVERFLOW should fire on raw clipped box; got {hits}"


# ---- R-VIS-TITLE-GAP ----
def _title_gap_inner(header_cls, stage_cls):
    return (
        f'<div class="{header_cls}"><h2 class="title-zh" style="font-size:28px;margin:0">页面标题</h2></div>'
        f'<div class="{stage_cls}"><div style="width:300px;height:120px">正文区块顶到标题</div></div>'
    )


def test_title_gap_schema_control():
    hits = _bucket(_slide("content", _title_gap_inner("header", "stage")), "title_gap")
    assert len(hits) >= 1, f"control: title-gap must fire on .header/.stage with ~0px gap; got {hits}"


@pytest.mark.xfail(strict=True, reason=(
    "R-VIS-TITLE-GAP raw escape: hard-gated on :scope > .header AND :scope > .stage "
    "(visual-audit.js:387,407); arbitrary raw markup has neither → block returns without measuring. "
    "Fix: derive title band = topmost title-tier text, content band = next block below; then delete marker."))
def test_title_gap_raw_fires():
    hits = _bucket(_slide("raw", _title_gap_inner("zzheader", "zzstage")), "title_gap")
    assert len(hits) >= 1, f"R-VIS-TITLE-GAP should fire on raw title/content crowd; got {hits}"
