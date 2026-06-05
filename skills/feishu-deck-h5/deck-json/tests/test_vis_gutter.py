"""R-VIS-GUTTER · 同组相邻框间距不等 / 框内 padding 不一致 (2026-05-31, P7).

#3 卡片左右 28px 但到下面 strap 仅 8px;#4 同组 cell padding 不一。≥3 framed
组框的 gutter 应相等;双闸 max>min*1.8 且差>10px。
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
ASSETS = HERE.parents[2] / "assets"
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402
DOC = HERE.parents[2] / "references" / "validator-rules.md"


def test_gutter_wired():
    assert E.rule_in_engine("R-VIS-GUTTER")
    assert "R-VIS-GUTTER" in DOC.read_text(encoding="utf-8")


def _run(html):
    E.skip_if_no_engine()
    return E.findings_for("R-VIS-GUTTER", html, kind="gutter")


def _row(m1, m2):
    box = 'border:1px solid #888;width:200px;height:100px'
    return ('<div class="slide"><div class="stage"><div style="display:flex">'
            f'<div class="card" style="{box};margin-right:{m1}px"></div>'
            f'<div class="card" style="{box};margin-right:{m2}px"></div>'
            f'<div class="card" style="{box}"></div>'
            '</div></div></div>')


def test_gutter_fires_on_uneven_gaps():
    hits = _run(_row(10, 50))   # gutters [10,50] → 50>10*1.8 & diff 40>10
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert len(hits) >= 1, f"不等 gutter (10/50) 未抓: {hits}"


def test_gutter_quiet_on_even_gaps():
    hits = _run(_row(24, 24))   # gutters [24,24] → equal
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert hits == [], f"false positive on even gutters: {hits}"


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
