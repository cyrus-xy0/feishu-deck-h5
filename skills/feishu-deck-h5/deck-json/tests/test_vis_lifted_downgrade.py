"""F-325 · lifted-downgrade for geometry rules (2026-06-14).

R-VIS-CARD-OVERFLOW / R-VIS-ABSPOS-DUAL-ANCHOR / R-VIS-TITLE-POSITION fire as
`error` on an authored slide but demote to `warn` on a slide carrying
`data-lifted` provenance — the source author's geometry is faithfully reproduced
and is the human's call, not a fresh defect. Same family as R-VIS-TIER /
R-VIS-BODY-FLOOR. data-allow-* opt-outs still suppress entirely (covered by the
other vis tests); here we lock the error↔warn flip keyed purely on data-lifted.
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402


# ── static wiring guard (runs without a browser) ──────────────────────────────
def test_lifted_downgrade_wired_in_engine():
    js = E.audits_js_text()
    for r in ("R-VIS-CARD-OVERFLOW", "R-VIS-ABSPOS-DUAL-ANCHOR",
              "R-VIS-TITLE-POSITION"):
        assert E.rule_in_engine(r), f"{r} missing from engine"
    # all three carry the F-325 lifted-downgrade marker (CARD-OVERFLOW's old
    # PRESERVE-EXACTLY dead branch is re-animated — the gutter rule keeps its own,
    # so don't assert on the phrase globally).
    assert js.count("F-325 lifted-downgrade") >= 3, \
        "F-325 lifted-downgrade marker missing on one of the three rules"


def _wrap(inner, *, lifted, layout="raw"):
    lift = ' data-lifted="src#k"' if lifted else ""
    return (f'<div class="slide" data-layout="{layout}"{lift} '
            'style="position:relative;width:1920px;height:1080px;'
            'background:#0b1020">'
            f'{inner}</div>')


def _flip(rule, inner):
    """Return (authored_findings, lifted_findings) for `rule`."""
    E.skip_if_no_engine()
    auth = E.findings_for(rule, _wrap(inner, lifted=False))
    lift = E.findings_for(rule, _wrap(inner, lifted=True))
    return auth, lift


# ── R-VIS-TITLE-POSITION ──────────────────────────────────────────────────────
_TITLE_INNER = (
    '<div class="header" style="position:absolute;top:240px;left:73px;right:73px">'
    '<h2 class="title-zh" style="font-size:44px;margin:0;color:#fff">标题在这里</h2>'
    '</div>'
    '<div class="stage" style="position:absolute;top:320px;left:73px;right:73px;'
    'bottom:60px"><div class="card" style="height:200px;font-size:24px;color:#fff">'
    '内容块</div></div>')


def test_title_position_error_when_authored_warn_when_lifted():
    auth, lift = _flip("R-VIS-TITLE-POSITION", _TITLE_INNER)
    assert any(f["severity"] == "error" for f in auth), \
        f"authored drifted header should be ERROR: {auth}"
    assert lift and all(f["severity"] == "warn" for f in lift), \
        f"lifted drifted header should downgrade to WARN: {lift}"
    assert any("LIFTED slide" in f["message"] for f in lift), \
        "lifted finding should carry the downgrade note"


# ── R-VIS-CARD-OVERFLOW (non-recoverable vertical clip) ───────────────────────
_CLIP_INNER = (
    '<div class="stage" style="position:absolute;inset:80px 73px 60px">'
    '<div class="card" style="height:120px;overflow:hidden;border:1px solid #345;'
    'font-size:24px;color:#fff;line-height:40px">'
    '一行一行一行一行<br>二行二行二行二行<br>三行三行三行三行<br>'
    '四行四行四行四行<br>五行五行五行五行<br>六行六行六行六行</div></div>')


def test_card_overflow_error_when_authored_warn_when_lifted():
    auth, lift = _flip("R-VIS-CARD-OVERFLOW", _CLIP_INNER)
    assert any(f["severity"] == "error" for f in auth), \
        f"authored non-recoverable clip should be ERROR: {auth}"
    assert lift and all(f["severity"] == "warn" for f in lift), \
        f"lifted clip should downgrade to WARN: {lift}"


# ── R-VIS-ABSPOS-DUAL-ANCHOR ──────────────────────────────────────────────────
_DUAL_INNER = (
    '<div class="stage" style="position:absolute;inset:80px 73px 60px">'
    '<div class="watermark" style="position:absolute;top:0;bottom:0;left:0;'
    'width:300px;font-size:24px;color:#456">W</div></div>')


def test_dual_anchor_error_when_authored_warn_when_lifted():
    auth, lift = _flip("R-VIS-ABSPOS-DUAL-ANCHOR", _DUAL_INNER)
    assert any(f["severity"] == "error" for f in auth), \
        f"authored dual-anchor should be ERROR: {auth}"
    assert lift and all(f["severity"] == "warn" for f in lift), \
        f"lifted dual-anchor should downgrade to WARN: {lift}"
