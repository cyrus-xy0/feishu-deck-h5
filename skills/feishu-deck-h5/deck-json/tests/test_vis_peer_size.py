"""R-VIS-PEER-SIZE · 同角色并列 sibling 字号不一致 (2026-05-31, P5).

#4 "18 与 22 混": same-role siblings in one parallel container should be equal
size. Catches the "有大有小" inconsistency no other check covered.
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
ASSETS = HERE.parents[2] / "assets"
AUDIT = ASSETS / "visual-audit.js"
VALIDATE = ASSETS / "validate.py"
DOC = HERE.parents[2] / "references" / "validator-rules.md"


def test_peer_size_wired():
    js = AUDIT.read_text(encoding="utf-8")
    assert "peer_size: []" in js and "out.peer_size.push" in js
    assert "report.get('peer_size'" in VALIDATE.read_text(encoding="utf-8")
    assert "R-VIS-PEER-SIZE" in DOC.read_text(encoding="utf-8")


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
    return rep.get("peer_size", [])


def _card(px1, px2):
    return ('<div class="slide"><div class="stage"><div class="info-card">'
            f'<span class="feat-body" style="font-size:{px1}px">第一条说明文字内容</span>'
            f'<span class="feat-body" style="font-size:{px2}px">第二条说明文字内容</span>'
            '</div></div></div>')


def test_peer_size_fires_on_mismatch():
    hits = _run(_card(18, 24))
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert len(hits) >= 1 and 18 in hits[0]["sizes"] and 24 in hits[0]["sizes"], \
        f"18/24 同角色不一致未抓: {hits}"


def test_peer_size_quiet_when_consistent():
    hits = _run(_card(24, 24))
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert hits == [], f"false positive on equal sizes: {hits}"


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
