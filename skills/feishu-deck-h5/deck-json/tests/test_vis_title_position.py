"""R-VIS-TITLE-POSITION · header top drift (added 2026-05-22).

Regression guard for the 2026-05-31 false-positive fix: the framework hides the
header in some layouts (e.g. agenda without the `with-header` variant sets
`.header { display:none }`). A display:none element reports an all-zero bbox →
top:0, which used to false-fail the expected-61 check and made the bundled
examples/sample-deck.html FAIL once check-only's visual audits defaulted on.

The audit now skips non-rendered headers (getClientRects().length === 0).
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
ASSETS = HERE.parents[2] / "assets"
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402


def test_title_position_guard_wired():
    """Static guard: the display:none skip must stay in the engine source."""
    js = E.audits_js_text()
    assert E.rule_in_engine("R-VIS-TITLE-POSITION")
    assert "headerRendered" in js, "headerRendered guard missing from audits.js"
    assert "getClientRects().length > 0" in js, \
        "display:none test (getClientRects) missing from audits.js"


def _run(html):
    E.skip_if_no_engine()
    return E.findings_for("R-VIS-TITLE-POSITION", html)


def _slide(header_style):
    return ('<div class="slide" data-layout="content-2col" '
            'style="position:relative;width:1920px;height:1080px">'
            f'<div class="header" style="{header_style}">'
            '<h2 class="title-zh" style="font-size:44px;margin:0">标题在这里</h2></div>'
            '<div class="stage" style="position:absolute;top:200px;left:73px;'
            'right:73px;bottom:60px">'
            '<div class="card" style="height:200px;font-size:24px">内容块</div>'
            '</div></div>')


def test_hidden_header_not_flagged():
    """display:none header → all-zero bbox → must NOT be flagged (the bug)."""
    hits = _run(_slide("display:none"))
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert hits == [], f"display:none header wrongly flagged: {hits}"


def test_visible_misplaced_header_flagged():
    """Control: a VISIBLE header far from top:61 must still be flagged — proves
    the display:none guard didn't over-suppress real drift."""
    hits = _run(_slide("position:absolute;top:0px;left:73px;height:53px"))
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert any(h["actual_top"] <= 8 for h in hits), \
        f"visible header at top:0 not flagged: {hits}"


def test_correct_header_quiet():
    """Control: a header at the master top:61 must stay quiet."""
    hits = _run(_slide("position:absolute;top:61px;left:73px;height:53px"))
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert hits == [], f"correctly-placed header flagged: {hits}"


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
