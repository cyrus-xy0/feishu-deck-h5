"""UNIFY-VALIDATE-ARCH step 4b · repurposed.

Originally this asserted cross-LANGUAGE parity between Python validate.py and the
JS visual-audit.js for the genuinely-SHARED vocab (TIER ladder, mock-container
set). After step 4 there is a SINGLE rule source — the unified engine
`assets/audits.js` — so that Python↔JS parity no longer exists to test.

What still matters and is checked here: the engine's hardcoded R-VIS-TIER ladder
(`VIS_TIER`) must equal the CSS `--fs-*` type tokens (the Python `TYPE_LADDER_PX`,
which is still derived from the tokens in _validate_common) — catching drift if
the ladder is re-tuned in CSS but the engine's hardcoded set isn't. And the
mock-container set (`VIS_TIER_MOCK`) is single-sourced inside the engine (the
member that once drifted, `pd-card`, is present). Static — no Chromium needed.
"""
import re
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
import validate as V  # noqa: E402  (TYPE_LADDER_PX survives in _validate_common)

JS = (ASSETS / "audits.js").read_text(encoding="utf-8")


def test_engine_tier_matches_css_token_ladder():
    """The engine R-VIS-TIER ladder (VIS_TIER) must equal the CSS --fs-* token
    ladder (Python TYPE_LADDER_PX). Catches drift if the ladder is re-tuned in
    CSS but the engine's hardcoded VIS_TIER isn't updated."""
    m = re.search(r'const VIS_TIER = new Set\(\[([\d,\s]+)\]\)', JS)
    assert m, "could not find `const VIS_TIER = new Set([...])` in audits.js"
    js_tier = {int(x) for x in re.findall(r'\d+', m.group(1))}
    assert js_tier == set(V.TYPE_LADDER_PX) == {16, 24, 28, 48}, \
        f"engine VIS_TIER {js_tier} != Python TYPE_LADDER_PX {set(V.TYPE_LADDER_PX)}"


def test_mock_containers_single_sourced():
    """The mock-container set is single-sourced inside the engine (VIS_TIER_MOCK,
    shared by the tier-mock and body-floor-mock exemptions). The member that once
    drifted (pd-card) must be present."""
    tm = re.search(r'VIS_TIER_MOCK = \[(.*?)\]', JS, re.S)
    assert tm, "VIS_TIER_MOCK array not found in audits.js"
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
