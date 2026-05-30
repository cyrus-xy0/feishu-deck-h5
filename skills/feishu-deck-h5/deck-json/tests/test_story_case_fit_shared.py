"""F-15: story-case fit primitives are single-sourced in _story_case_fit.py.
Guards against re-introducing the byte-identical PLACEHOLDER_PATTERNS copies
that previously lived in BOTH render-deck.py and validate-deck.py, and pins the
canonical min-length mapping.
"""
import importlib.util
import re
import sys
import pathlib

DECK_JSON = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DECK_JSON))

_spec = importlib.util.spec_from_file_location("_story_case_fit", DECK_JSON / "_story_case_fit.py")
SCF = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SCF)


def test_shared_module_exposes_primitives():
    assert len(SCF.PLACEHOLDER_PATTERNS) >= 4
    assert all(isinstance(p, str) for p in SCF.PLACEHOLDER_PATTERNS)
    assert SCF.STORY_CASE_FIT_CHECK  # non-empty path list
    assert callable(SCF.get_path)


def test_min_len_mapping_is_canonical():
    assert SCF._min_len_for("hook.accent") == SCF._MIN_LEN_ACCENT == 2
    assert SCF._min_len_for("arc.value.accent") == 2
    assert SCF._min_len_for("hook.lead") == SCF._MIN_LEN_CONNECTIVE == 1
    assert SCF._min_len_for("arc.value.tail") == 1
    assert SCF._min_len_for("arc.pain") == SCF._MIN_LEN_FULL == 10
    assert SCF._min_len_for("arc.solution") == 10


def test_get_path_walks_and_raises():
    d = {"a": {"b": {"c": 1}}}
    assert SCF.get_path(d, "a.b.c") == 1
    try:
        SCF.get_path(d, "a.x")
    except KeyError:
        pass
    else:
        raise AssertionError("expected KeyError for missing path")


def _defines_placeholder_patterns_locally(filename):
    src = (DECK_JSON / filename).read_text(encoding="utf-8")
    # a local assignment like `PLACEHOLDER_PATTERNS = (` (not an import line)
    return bool(re.search(r'^\s*_?PLACEHOLDER_PATTERNS\s*=\s*\(', src, re.M))


def test_render_deck_imports_not_defines():
    assert not _defines_placeholder_patterns_locally("render-deck.py"), \
        "render-deck.py should import PLACEHOLDER_PATTERNS from _story_case_fit, not redefine it"


def test_validate_deck_imports_not_defines():
    assert not _defines_placeholder_patterns_locally("validate-deck.py"), \
        "validate-deck.py should import PLACEHOLDER_PATTERNS from _story_case_fit, not redefine it"


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
