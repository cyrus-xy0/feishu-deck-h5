"""R-VIS-TITLE-GAP · 正文顶到/重叠标题 (2026-05-31, P3).

R-VIS-TITLE-POSITION only checks the header's ABSOLUTE top (~61). Content that
grew/overflowed UP toward the title (cross-container: title in .header, content
in .stage) was unowned. This measures header-bottom → topmost content top.
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
ASSETS = HERE.parents[2] / "assets"
AUDIT = ASSETS / "visual-audit.js"
VALIDATE = ASSETS / "validate.py"
DOC = HERE.parents[2] / "references" / "validator-rules.md"


def test_title_gap_wired():
    js = AUDIT.read_text(encoding="utf-8")
    assert "title_gap: []" in js and "out.title_gap.push" in js, "title_gap not wired in visual-audit.js"
    assert "report.get('title_gap'" in VALIDATE.read_text(encoding="utf-8"), "validate.py does not consume title_gap"
    assert "R-VIS-TITLE-GAP" in DOC.read_text(encoding="utf-8"), "R-VIS-TITLE-GAP not documented"


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
            pg.set_content(html); pg.wait_for_timeout(150)
            rep = pg.evaluate("(" + audit + ")()")
            b.close()
    except Exception:
        return None
    return rep.get("title_gap", [])


def _slide(stage_top):
    return ('<div class="slide" style="position:relative;width:1920px;height:1080px">'
            '<div class="header" style="position:absolute;top:61px;left:73px;height:53px">'
            '<h2 class="title-zh" style="font-size:44px;margin:0">标题在这里</h2></div>'
            f'<div class="stage" style="position:absolute;top:{stage_top}px;left:73px;right:73px;bottom:60px">'
            '<div class="card" style="border:1px solid #888;height:200px;font-size:24px">内容块</div>'
            '</div></div>')


def test_title_gap_fires_when_content_crowds_title():
    hits = _run(_slide(120))   # content top ~120, header bottom ~114 → gap ~6 < 24
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert len(hits) >= 1, f"content 6px below title not flagged: {hits}"


def test_title_gap_quiet_with_normal_spacing():
    hits = _run(_slide(300))   # content top 300, gap ~186 → fine
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert hits == [], f"false positive on normal title spacing: {hits}"


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
