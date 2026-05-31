"""R-VIS-CARD-OVERFLOW · text-leaf spill upgrade (2026-05-31, P2/P8).

The pre-existing visible-spill branch (a') only caught CONTAINERS (children>0).
A pure TEXT LEAF (text, no element children) whose text wraps an extra line and
pokes past its framed cell slipped through unflagged (#4 「自然语言搭建业务应用」).
The upgrade measures the leaf's own line boxes via Range.getClientRects().

Layer 1 (static) always runs. Layer 2 (Playwright) skips if Chromium absent.
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
ASSETS = HERE.parents[2] / "assets"
AUDIT = ASSETS / "visual-audit.js"


def test_leaf_spill_wired_in_visual_audit_js():
    js = AUDIT.read_text(encoding="utf-8")
    assert "leaf-text-spill" in js, "leaf-text-spill direction missing"
    assert "getClientRects()" in js, "Range line-box measurement missing"
    assert "children.length === 0" in js, "text-leaf guard (no element children) missing"


def _run(html):
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
    return [c for c in rep.get("card_overflow", []) if c.get("direction") == "leaf-text-spill"]


# a framed cell (border) too short for its text leaf → leaf wraps + spills past border
_SPILL = ('<div class="slide"><div class="stage">'
          '<div class="card" style="border:1px solid #888;height:40px;width:200px;'
          'overflow:visible;font-size:24px;line-height:1.4">'
          '这是一段会换行并溢出这个矮框底边的纯文本叶子内容确实很长</div>'
          '</div></div>')
# same cell, but tall enough → no spill
_FIT = ('<div class="slide"><div class="stage">'
        '<div class="card" style="border:1px solid #888;height:200px;width:200px;'
        'overflow:visible;font-size:24px;line-height:1.4">'
        '这是一段会换行并溢出这个矮框底边的纯文本叶子内容确实很长</div>'
        '</div></div>')


def test_leaf_spill_fires_on_overflowing_text_leaf():
    hits = _run(_SPILL)
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert len(hits) >= 1, f"text leaf spilling its framed cell not flagged: {hits}"


def test_leaf_spill_quiet_when_text_fits():
    hits = _run(_FIT)
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert hits == [], f"false positive: text that fits flagged as spill: {hits}"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  ok  {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL  {fn.__name__}"); traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
