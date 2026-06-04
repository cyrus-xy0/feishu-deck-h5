"""R-VIS-PEER-SIZE · 同角色并列 sibling 字号不一致 (2026-05-31, P5).

#4 "18 与 22 混": same-role siblings in one parallel container should be equal
size. Catches the "有大有小" inconsistency no other check covered.
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
ASSETS = HERE.parents[2] / "assets"
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402
VALIDATE = ASSETS / "validate.py"
DOC = HERE.parents[2] / "references" / "validator-rules.md"


def test_peer_size_wired():
    assert E.rule_in_engine("R-VIS-PEER-SIZE")
    assert "R-VIS-PEER-SIZE" in DOC.read_text(encoding="utf-8")


def _run(html):
    E.skip_if_no_engine()
    return E.findings_for("R-VIS-PEER-SIZE", html)


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
