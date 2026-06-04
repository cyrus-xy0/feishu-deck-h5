"""R-VIS-HERO-FLOOR · hero 主元素字号下限 (2026-05-31, P11).

Direction = size FLOOR, not whitelist. R-VIS-TIER only asks "is px in HERO_SIZES";
this asks "is the hero big enough for its layout's master spec" (封面 82 < 100).
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
ASSETS = HERE.parents[2] / "assets"
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402
VALIDATE = ASSETS / "validate.py"
DOC = HERE.parents[2] / "references" / "validator-rules.md"


def test_hero_floor_wired():
    # UNIFY-VALIDATE step 4b: single rule source — emitted by the unified
    # engine (audits.js) + documented (was bucket-in-visual-audit.js +
    # validate.py report.get mapping, both retired).
    assert E.rule_in_engine("R-VIS-HERO-FLOOR")
    assert "R-VIS-HERO-FLOOR" in DOC.read_text(encoding="utf-8")


def _run(html):
    E.skip_if_no_engine()
    return E.findings_for("R-VIS-HERO-FLOOR", html)


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
