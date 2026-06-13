"""R-VIS-CARD-OVERFLOW · centered / both-edge visible spill (F-317).

The pre-F-317 visible-spill branch (a') gated on `scrollHeight - clientHeight > 8`
and measured ONLY the bottom child edge, in raw screen px. Two structural blind
spots fell out of that:

  1. A flex card with `justify-content:center` (or `flex-end`) whose children are
     taller than the box overflows the TOP border too. `scrollHeight` does NOT
     report content above the box, so `dh ≈ 0` and the card was never even
     examined — the #meeting-qc regression (标题行顶出面板上沿, validator green).
  2. At present-mode scale < 1 the bottom spill was under-reported because (a')
     never divided by `_scale` like the rest of the engine (line 56 等), so a real
     ~13px spill shrank below the 8px screen-px threshold and slipped through.

F-317 measures BOTH child edges in design px (`/_scale`) and sums them. These
fixtures lock in that a centered/top-edge spill is caught and that a card whose
children genuinely fit stays quiet (no false positive).

Layer 1 (static) always runs. Layer 2 (Playwright) skips if Chromium absent.
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402


def test_both_edge_branch_wired_in_engine():
    js = E.audits_js_text()
    assert E.rule_in_engine("R-VIS-CARD-OVERFLOW")
    assert "topSpill" in js and "botSpill" in js, \
        "F-317 both-edge spill measurement (topSpill/botSpill) missing from audits.js"


def _vv(html):
    """vertical-visible findings for the card, or None when no engine."""
    E.skip_if_no_engine()
    hits = E.findings_for("R-VIS-CARD-OVERFLOW", html)
    if hits is None:
        return None
    return [c for c in hits if c.get("direction") == "vertical-visible"]


# flex column, justify-content:center, children can't shrink (flex:none) and total
# (260) taller than the box (200) → content centred, overflows BOTH borders ~30px.
_CENTERED = ('<div class="slide" style="height:1080px"><div class="stage">'
             '<div class="card" style="height:200px;width:400px;border:2px solid #888;'
             'display:flex;flex-direction:column;justify-content:center;overflow:visible">'
             '<div style="height:140px;flex:none">A</div>'
             '<div style="height:120px;flex:none">B</div></div></div></div>')
# same shape, box tall enough (340) for its children (260) → no spill.
_FIT = ('<div class="slide" style="height:1080px"><div class="stage">'
        '<div class="card" style="height:340px;width:400px;border:2px solid #888;'
        'display:flex;flex-direction:column;justify-content:center;overflow:visible">'
        '<div style="height:140px;flex:none">A</div>'
        '<div style="height:120px;flex:none">B</div></div></div></div>')
# pure TOP spill: justify-content:flex-end pushes an over-tall child out the top
# border only (bottom flush). scrollHeight is blind to this → the case the old
# bottom-only / dh-gated branch could NEVER reach.
_TOP_ONLY = ('<div class="slide" style="height:1080px"><div class="stage">'
             '<div class="card" style="height:200px;width:400px;border:2px solid #888;'
             'display:flex;flex-direction:column;justify-content:flex-end;overflow:visible">'
             '<div style="height:320px;flex:none">A</div></div></div></div>')


def test_centered_both_edge_spill_fires():
    hits = _vv(_CENTERED)
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert len(hits) >= 1, f"centered card overflowing both borders not flagged: {hits}"


def test_top_only_spill_fires():
    hits = _vv(_TOP_ONLY)
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert len(hits) >= 1, f"top-edge-only spill (scrollHeight-invisible) not flagged: {hits}"


def test_centered_card_that_fits_is_quiet():
    hits = _vv(_FIT)
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert hits == [], f"false positive: card whose children fit flagged as spill: {hits}"
