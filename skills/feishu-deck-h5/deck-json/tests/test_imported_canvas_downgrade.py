"""Imported / lifted canvas-slide downgrade tests.

A PPTX→canvas deck (build_pptx.py) is IMPORTED content: every slide is marked
`lifted` (provenance `pptx:<stem>#<N>`), the renderer emits `data-lifted`, and
the validator then DOWNGRADES this slide's CONTENT-AUTHORING violations
err→warn (warn_soft, so they survive even `--strict`):

    R05    banned punctuation (ellipsis / '!' / '???')   deck-wide, all-imported
    R10    off-palette hex                                deck-wide, all-imported
    R-KEY  positional slug (slide-NN)                     per-slide
    R-LANG Latin-only leaf paired with CJK sibling        per-slide

while STRUCTURAL / GEOMETRY rules stay full-severity error regardless of import:

    R-KEY  DUPLICATE / empty / invalid-kebab slug         (round-trip locator)

These tests import the audits directly (no render / no Playwright) and assert the
severity bucket each finding lands in for an imported slide vs an authored one.
"""
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
import validate as V  # noqa: E402


# --- fixture builders -------------------------------------------------------
def _slide(body: str = "", *, key: str = "k", lifted: bool = False,
           layout: str = "canvas") -> str:
    """One slide-frame chunk. lifted=True stamps data-lifted (import marker)."""
    lifted_attr = ' data-lifted="pptx:demo#1"' if lifted else ""
    return (
        f'<div class="slide-frame"><div class="slide" '
        f'data-layout="{layout}" data-screen-label="x" '
        f'data-slide-key="{key}"{lifted_attr}>{body}</div></div>'
    )


def _doc(slides: list[str]) -> str:
    return "<html><head></head><body>" + "".join(slides) + "</body></html>"


def _run(fn, *args):
    iss = V.Issues()
    fn(*args, iss)
    return iss


def _codes(iss, bucket):
    return [c for c, _ in getattr(iss, bucket)]


# --- R05 banned punctuation (deck-wide; downgrades when ALL slides imported) -
def test_r05_ellipsis_errors_on_authored_deck():
    html = _doc([_slide("<p>未完待续…</p>")])
    iss = _run(V.audit_copy_rules, html)
    assert "R05" in _codes(iss, "errors")
    assert "R05" not in _codes(iss, "soft_warnings")


def test_r05_ellipsis_downgrades_on_imported_deck():
    html = _doc([_slide("<p>未完待续…</p>", lifted=True)])
    iss = _run(V.audit_copy_rules, html)
    assert "R05" not in _codes(iss, "errors"), "imported deck must NOT block on R05"
    assert "R05" in _codes(iss, "soft_warnings"), "R05 must be surfaced as soft warn"


# --- R10 off-palette hex (deck-wide; downgrades when ALL slides imported) ----
_OFF_HEX_BODY = '<div class="card" style="color:#c00000">红</div>'


def test_r10_hex_warns_on_authored_deck():
    html = _doc([_slide(_OFF_HEX_BODY)])
    iss = _run(V.audit_hex_palette, html)
    # authored: regular warning (promoted to error under --strict)
    assert "R10" in _codes(iss, "warnings")
    assert "R10" not in _codes(iss, "soft_warnings")


def test_r10_hex_downgrades_on_imported_deck():
    html = _doc([_slide(_OFF_HEX_BODY, lifted=True)])
    iss = _run(V.audit_hex_palette, html)
    assert "R10" not in _codes(iss, "errors")
    assert "R10" in _codes(iss, "soft_warnings"), "imported R10 must be soft (no --strict promote)"


# --- R-KEY positional slug (per-slide downgrade) ----------------------------
def test_rkey_positional_warns_on_authored_slide():
    slides = [_slide(key="slide-001", lifted=False)]
    iss = _run(V.audit_slide_keys, slides)
    assert "R-KEY" in _codes(iss, "warnings")
    assert "R-KEY" not in _codes(iss, "soft_warnings")


def test_rkey_positional_downgrades_on_imported_slide():
    slides = [_slide(key="slide-001", lifted=True)]
    iss = _run(V.audit_slide_keys, slides)
    assert "R-KEY" not in _codes(iss, "errors")
    assert "R-KEY" in _codes(iss, "soft_warnings"), "imported positional key must be soft"


# --- R-KEY DUPLICATE stays a full error even when imported (structural) ------
def test_rkey_duplicate_stays_error_even_when_imported():
    slides = [
        _slide(key="dup", lifted=True),
        _slide(key="dup", lifted=True),
    ]
    iss = _run(V.audit_slide_keys, slides)
    # real collision breaks the round-trip / library locator → stays ERROR
    assert "R-KEY" in _codes(iss, "errors"), "duplicate key must stay error regardless of import"


# --- R-LANG Latin leaf paired with CJK sibling (per-slide downgrade) --------
_TRANS_PAIR = ('<div class="card"><span class="t">审批聚合</span>'
               '<span class="n">APPROVAL AGGREGATE</span></div>')


def test_rlang_pair_warns_on_authored_slide():
    slides = [_slide(_TRANS_PAIR, lifted=False)]
    html = _doc(slides)
    iss = _run(V.audit_language_policy, html, slides)
    assert "R-LANG" in _codes(iss, "warnings")
    assert "R-LANG" not in _codes(iss, "soft_warnings")


def test_rlang_pair_downgrades_on_imported_slide():
    slides = [_slide(_TRANS_PAIR, lifted=True)]
    html = _doc(slides)
    iss = _run(V.audit_language_policy, html, slides)
    assert "R-LANG" not in _codes(iss, "errors")
    assert "R-LANG" in _codes(iss, "soft_warnings"), "imported Latin-pair must be soft"


# --- end-to-end: a fully-imported canvas deck has 0 errors via the audits ----
def test_imported_deck_no_blocking_errors_across_target_rules():
    """All four target families on imported slides → 0 errors (soft warns ok)."""
    slides = [
        _slide("<p>未完待续…</p>" + _OFF_HEX_BODY + _TRANS_PAIR,
               key="slide-001", lifted=True),
    ]
    html = _doc(slides)
    errs = []
    for fn, args in (
        (V.audit_copy_rules, (html,)),
        (V.audit_hex_palette, (html,)),
        (V.audit_slide_keys, (slides,)),
        (V.audit_language_policy, (html, slides)),
    ):
        iss = _run(fn, *args)
        errs += iss.errors
    assert errs == [], f"imported canvas deck must have 0 blocking errors, got {errs}"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
