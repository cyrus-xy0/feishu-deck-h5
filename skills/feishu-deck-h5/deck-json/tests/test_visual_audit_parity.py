"""F-13: cross-language parity between Python validate.py and the JS
visual-audit.js for the genuinely-SHARED vocab. Static — parses the JS source,
no Chromium/Playwright needed (the visual audits don't run here anyway).

Covers SAME-concept pairs only. The HERO sets are intentionally DIFFERENT
(Python HERO_TITLE_LAYOUTS = hero-TITLE/header layouts, excludes big-stat;
JS HERO_LAYOUTS = hero-ZONE layouts, includes big-stat) and are deliberately
NOT asserted equal — see the cross-referencing comments on both definitions.
"""
import re
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
import validate as V  # noqa: E402

JS = (ASSETS / "visual-audit.js").read_text(encoding="utf-8")


def test_js_tier_matches_python_ladder():
    """The JS R-VIS-TIER ladder must equal the Python R20 ladder (both = the
    CSS --fs-* tokens). Catches drift if the ladder is re-tuned in CSS but the
    JS hardcoded TIER isn't updated."""
    m = re.search(r'const TIER = new Set\(\[([\d,\s]+)\]\)', JS)
    assert m, "could not find `const TIER = new Set([...])` in visual-audit.js"
    js_tier = {int(x) for x in re.findall(r'\d+', m.group(1))}
    assert js_tier == set(V.TYPE_LADDER_PX) == {16, 24, 28, 48}, \
        f"JS TIER {js_tier} != Python TYPE_LADDER_PX {set(V.TYPE_LADDER_PX)}"


def test_mock_containers_single_sourced():
    """The tier-mock and body-floor-mock container sets must stay identical —
    enforced by aliasing (MOCK_CONTAINERS = TIER_MOCK), not a parallel copy
    that can drift (it drifted on pd-card before F-13)."""
    assert re.search(r'MOCK_CONTAINERS\s*=\s*TIER_MOCK\b', JS), \
        "MOCK_CONTAINERS should alias TIER_MOCK (single source), not duplicate it"
    tm = re.search(r'TIER_MOCK = \[(.*?)\]', JS, re.S)
    assert tm, "TIER_MOCK array not found"
    members = set(re.findall(r"'([^']+)'", tm.group(1)))
    assert 'pd-card' in members  # the member that had drifted


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
