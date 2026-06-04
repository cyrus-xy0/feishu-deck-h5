"""R-VIS-BALANCE · side-empty 横向失衡 / 单侧空壳 (2026-05-31, P10).

R-VIS-BALANCE dead-band was vertical-only; horizontal 3-up exempt. #36「右半是个
空壳面板」横向失衡无人认领。side-empty: real content (text+media leaves, empty
frame doesn't count) hugs one side, the other ≥22% empty. A real right-image
fills the right (media counted) → no false positive.
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
ASSETS = HERE.parents[2] / "assets"
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402


def test_side_empty_wired():
    # UNIFY-VALIDATE step 4b: single rule source — R-VIS-BALANCE side-empty is
    # produced by the unified engine (audits.js).
    assert E.rule_in_engine("R-VIS-BALANCE")
    assert "side-empty" in E.audits_js_text(), "side-empty kind missing from audits.js"


def _run(html):
    E.skip_if_no_engine()
    return E.findings_for("R-VIS-BALANCE", html, kind="side-empty")


def _stage(right_inner):
    return ('<div class="slide"><div class="stage" style="display:flex;width:1600px;height:600px">'
            '<div class="left" style="width:600px;height:500px"><p>左边一堆文字内容在这里占着位置不少</p></div>'
            '<div class="spacer" style="width:440px"></div>'
            f'{right_inner}</div></div>')


def test_side_empty_fires_on_empty_right_panel():
    # right is an empty framed panel (no text/media) → right half dead
    hits = _run(_stage('<div class="panel" style="width:560px;height:500px;border:1px solid #888"></div>'))
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert len(hits) >= 1 and hits[0]["right_slack"] > hits[0]["left_slack"], f"右半空壳未抓: {hits}"


def test_side_empty_quiet_when_right_has_image():
    # right is a real image (media) → fills the right → no imbalance
    hits = _run(_stage('<img src="x.png" style="width:560px;height:500px">'))
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert hits == [], f"右侧有图却误报: {hits}"


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
