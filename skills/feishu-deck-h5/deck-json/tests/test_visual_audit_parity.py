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


def _rule_body(rule_id):
    """Return the source text of one engine rule's block (from `id: '<rule_id>'`
    up to the start of the NEXT `id: '...'`). Lets the single-source assertion
    inspect what mock-container identifier a given rule actually references."""
    start = re.search(r"id:\s*'" + re.escape(rule_id) + r"'", JS)
    assert start, f"rule {rule_id!r} not found in audits.js"
    nxt = re.search(r"\n\s+id:\s*'", JS[start.end():])
    end = start.end() + nxt.start() if nxt else len(JS)
    return JS[start.start():end]


def test_mock_containers_single_sourced():
    """RESTORED single-source aliasing assertion (N4).

    The OLD cross-language parity test asserted `MOCK_CONTAINERS == TIER_MOCK` —
    that the body-floor-mock list and the tier-mock list were the SAME set, so a
    second, parallel mock-container list could not silently drift from the first.
    The naive replacement only checked `pd-card` membership, which does NOT catch
    a parallel list being introduced.

    Post-unification there must be exactly ONE mock-container array
    (`VIS_TIER_MOCK`), and BOTH the tier-mock exemption (R-VIS-TIER) and the
    body-floor-mock exemption (R-VIS-BODY-FLOOR) must RESOLVE TO THAT SAME single
    source — i.e. each rule references the identifier `VIS_TIER_MOCK`, not its own
    inline `['ui-window', …]` literal. That is the modern form of the old
    `MOCK_CONTAINERS == TIER_MOCK` guarantee."""
    # 1) Exactly ONE mock-container array definition (no parallel list).
    decls = re.findall(r'const\s+VIS_TIER_MOCK\s*=\s*\[', JS)
    assert len(decls) == 1, \
        f"expected exactly one VIS_TIER_MOCK definition, found {len(decls)}"

    # 2) Both exemptions resolve to that ONE source (reference the identifier).
    tier_body = _rule_body('R-VIS-TIER')
    body_floor_body = _rule_body('R-VIS-BODY-FLOOR')
    assert 'VIS_TIER_MOCK' in tier_body, \
        "R-VIS-TIER must reference the shared VIS_TIER_MOCK (tier-mock exemption)"
    assert 'VIS_TIER_MOCK' in body_floor_body, \
        "R-VIS-BODY-FLOOR must reference the shared VIS_TIER_MOCK (body-floor-mock)"

    # 3) Neither rule re-declares a parallel inline mock list (the drift the old
    #    MOCK_CONTAINERS == TIER_MOCK check guarded against). A new
    #    `const SOMETHING_MOCK = [ ... ]` inside either rule body is the smell.
    for name, b in (('R-VIS-TIER', tier_body),
                    ('R-VIS-BODY-FLOOR', body_floor_body)):
        assert not re.search(r'const\s+\w*MOCK\w*\s*=\s*\[', b), \
            f"{name} declares its own inline mock list — must reuse VIS_TIER_MOCK"

    # 4) The member that once drifted (pd-card) is present in the single source.
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
