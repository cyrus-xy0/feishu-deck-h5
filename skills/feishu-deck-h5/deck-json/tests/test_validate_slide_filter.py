"""F-254 · validate.py --slide single-slide diagnostic filter.

Edits to a single page produce a deck-wide render (no per-slide mode), so a
one-page edit's findings get buried under pre-existing findings on OTHER slides.
`--slide <key|ordinal>` keeps only the findings for that one slide and exits on
them alone. These tests pin the filter logic (fast, no Playwright, no deck).
"""
import sys
import pathlib
import importlib.util

HERE = pathlib.Path(__file__).resolve()
VALIDATE = HERE.parents[2] / "assets" / "validate.py"


def _load():
    # validate.py does `from _validate_common import *` — its dir must be importable
    # (a standalone `python3 test.py` run has no conftest to set sys.path).
    assets = str(VALIDATE.parent)
    if assets not in sys.path:
        sys.path.insert(0, assets)
    spec = importlib.util.spec_from_file_location("validate_f254", VALIDATE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Iss:
    def __init__(self, e, w, s):
        self.errors = list(e)
        self.warnings = list(w)
        self.soft_warnings = list(s)


_SLIDES = [
    '<div class="slide-frame"><div class="slide" data-slide-key="aaa">1</div></div>',
    '<div class="slide-frame"><div class="slide" data-slide-key="bbb">2</div></div>',
    '<div class="slide-frame"><div class="slide" data-slide-key="ccc">3</div></div>',
]


def _mk():
    return _Iss(
        # slide aaa (=#1) referenced two ways: by selector AND by "slide 1" ordinal
        [('R20',    'font-size 30px on `.slide[data-slide-key="aaa"] .x` off-tier'),
         ('R-ORD1', 'slide 1 · a first-slide finding referenced by ordinal only'),
         ('UI1',    'slide 3: <img> as body')],
        [('R06',    'font-size 14px on `.slide[data-slide-key="bbb"] .y` floor')],
        # genuinely deck-wide (no slide / no key) → must drop for ANY single slide
        [('R-NOIMG', 'deck reads flat — no imagery anywhere')],
    )


def test_wiring():
    src = VALIDATE.read_text(encoding="utf-8")
    assert "--slide" in src
    assert "def filter_issues_to_slide" in src


def test_filter_by_key_keeps_selector_and_ordinal():
    # "aaa" IS slide #1 → keep its selector finding AND any "slide 1" finding;
    # drop other slides' findings AND the deck-wide note.
    v = _load(); iss = _mk()
    note = v.filter_issues_to_slide("aaa", _SLIDES, iss)
    assert {c for c, _ in iss.errors} == {"R20", "R-ORD1"}
    assert iss.warnings == []          # bbb dropped
    assert iss.soft_warnings == []     # deck-wide note dropped
    assert "aaa" in note and "filtered" in note


def test_ordinal_1_equals_key_aaa():
    v = _load(); iss = _mk()
    v.filter_issues_to_slide("1", _SLIDES, iss)   # ordinal 1 resolves to key aaa
    assert {c for c, _ in iss.errors} == {"R20", "R-ORD1"}


def test_filter_by_ordinal_3_matches_slide_N_msg():
    v = _load(); iss = _mk()
    v.filter_issues_to_slide("3", _SLIDES, iss)   # slide 3 = ccc; UI1 says "slide 3"
    assert {c for c, _ in iss.errors} == {"UI1"}


def test_filter_by_hash_ordinal_2():
    v = _load(); iss = _mk()
    v.filter_issues_to_slide("#2", _SLIDES, iss)  # "#2" -> ordinal 2 -> key bbb
    assert {c for c, _ in iss.warnings} == {"R06"}
    assert iss.errors == []


def test_unknown_key_notes_and_empties():
    v = _load(); iss = _mk()
    note = v.filter_issues_to_slide("nope-xyz", _SLIDES, iss)
    assert "not found" in note
    assert iss.errors == [] and iss.warnings == [] and iss.soft_warnings == []


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
