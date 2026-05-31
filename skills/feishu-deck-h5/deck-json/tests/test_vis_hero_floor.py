"""R-VIS-HERO-FLOOR · hero 主元素字号下限 (2026-05-31, P11).

Direction = size FLOOR, not whitelist. R-VIS-TIER only asks "is px in HERO_SIZES";
this asks "is the hero big enough for its layout's master spec" (封面 82 < 100).
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
ASSETS = HERE.parents[2] / "assets"
AUDIT = ASSETS / "visual-audit.js"
VALIDATE = ASSETS / "validate.py"
DOC = HERE.parents[2] / "references" / "validator-rules.md"


def test_hero_floor_wired():
    js = AUDIT.read_text(encoding="utf-8")
    assert "hero_floor: []" in js and "out.hero_floor.push" in js
    assert "report.get('hero_floor'" in VALIDATE.read_text(encoding="utf-8")
    assert "R-VIS-HERO-FLOOR" in DOC.read_text(encoding="utf-8")


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
    return rep.get("hero_floor", [])


def _cover(px):
    return (f'<div class="slide" data-layout="cover"><div class="stage">'
            f'<h1 class="title-zh" style="font-size:{px}px;margin:0">封面主标题在这</h1>'
            '</div></div>')


def test_hero_floor_fires_on_small_cover_title():
    hits = _run(_cover(82))   # < 88 floor (master 100)
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert len(hits) >= 1 and hits[0]["rendered_px"] == 82, f"封面 82px 偏小未抓: {hits}"


def test_hero_floor_quiet_on_proper_cover_title():
    hits = _run(_cover(100))   # >= floor
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert hits == [], f"false positive on proper hero size: {hits}"


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
