"""F-02: the 4-tier font ladder is single-sourced from feishu-deck.css :root
--fs-* tokens. validate.py DERIVES FLOOR_BODY_PX / FLOOR_CHROME_PX /
TYPE_LADDER_PX from them instead of re-typing 16/24/28/48. These tests fail if
the CSS tokens drift from the validator's canonical fallback, or if the
derivation breaks — that's what makes the single source enforceable.
"""
import re
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
import validate as V  # noqa: E402

CANON = {'--fs-foot': 16, '--fs-body': 24, '--fs-sub': 28, '--fs-title': 48}


def _css_tokens():
    text = (ASSETS / "feishu-deck.css").read_text(encoding="utf-8")
    return {f'--fs-{n}': int(px)
            for n, px in re.findall(r'--fs-(title|sub|body|foot)\s*:\s*(\d+)px', text)}


def test_css_defines_all_four_tokens():
    assert _css_tokens() == CANON


def test_validator_derives_from_css_not_fallback():
    # the values the validator actually uses == what's in the CSS (parse worked)
    assert V._FS_TOKENS == _css_tokens()


def test_ladder_and_floors_match_tokens():
    assert V.TYPE_LADDER_PX == set(CANON.values()) == {16, 24, 28, 48}
    assert V.FLOOR_BODY_PX == CANON['--fs-body'] == 24
    assert V.FLOOR_CHROME_PX == CANON['--fs-foot'] == 16


def test_fallback_matches_css():
    # the in-code fallback must equal the CSS, so a CSS-read failure can't
    # silently change the enforced ladder (and editing a CSS tier without
    # updating the fallback fails this test → keeps them single-sourced)
    assert V._FS_TOKEN_FALLBACK == _css_tokens()


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
