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

UNIFY-VALIDATE-ARCH step 4b: these rules now live in the unified engine (rendered
DOM). The tests still assert the SEVERITY BUCKET each finding lands in for an
imported (data-lifted) slide vs an authored one — engine_helpers.buckets() maps
the engine severities (error/warn/warn_soft) onto the historical bucket names
(errors/warnings/soft_warnings) so the assertions are unchanged. Requires Chromium.
"""
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import engine_helpers as E  # noqa: E402


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


def _run(rule, slides):
    """One engine run over the slide fragments → bucket dict for `rule`."""
    E.skip_if_no_engine()
    return E.buckets(list(slides), rule=rule)


def _codes(buckets, bucket):
    return buckets[bucket]


# --- R05 banned punctuation (deck-wide; downgrades when ALL slides imported) -
def test_r05_ellipsis_errors_on_authored_deck():
    iss = _run("R05", [_slide("<p>未完待续…</p>")])
    assert "R05" in _codes(iss, "errors")
    assert "R05" not in _codes(iss, "soft_warnings")


def test_r05_ellipsis_downgrades_on_imported_deck():
    iss = _run("R05", [_slide("<p>未完待续…</p>", lifted=True)])
    assert "R05" not in _codes(iss, "errors"), "imported deck must NOT block on R05"
    assert "R05" in _codes(iss, "soft_warnings"), "R05 must be surfaced as soft warn"


# --- R10 off-palette hex (deck-wide; downgrades when ALL slides imported) ----
_OFF_HEX_BODY = '<div class="card" style="color:#c00000">红</div>'


def test_r10_hex_warns_on_authored_deck():
    iss = _run("R10", [_slide(_OFF_HEX_BODY)])
    # authored: regular warning (promoted to error under --strict)
    assert "R10" in _codes(iss, "warnings")
    assert "R10" not in _codes(iss, "soft_warnings")


def test_r10_hex_downgrades_on_imported_deck():
    iss = _run("R10", [_slide(_OFF_HEX_BODY, lifted=True)])
    assert "R10" not in _codes(iss, "errors")
    assert "R10" in _codes(iss, "soft_warnings"), "imported R10 must be soft (no --strict promote)"


# --- R-KEY positional slug (per-slide downgrade) ----------------------------
def test_rkey_positional_warns_on_authored_slide():
    iss = _run("R-KEY", [_slide(key="slide-001", lifted=False)])
    assert "R-KEY" in _codes(iss, "warnings")
    assert "R-KEY" not in _codes(iss, "soft_warnings")


def test_rkey_positional_downgrades_on_imported_slide():
    iss = _run("R-KEY", [_slide(key="slide-001", lifted=True)])
    assert "R-KEY" not in _codes(iss, "errors")
    assert "R-KEY" in _codes(iss, "soft_warnings"), "imported positional key must be soft"


# --- R-KEY DUPLICATE stays a full error even when imported (structural) ------
def test_rkey_duplicate_stays_error_even_when_imported():
    iss = _run("R-KEY", [
        _slide(key="dup", lifted=True),
        _slide(key="dup", lifted=True),
    ])
    # real collision breaks the round-trip / library locator → stays ERROR
    assert "R-KEY" in _codes(iss, "errors"), "duplicate key must stay error regardless of import"


# --- R-LANG Latin leaf paired with CJK sibling (per-slide downgrade) --------
_TRANS_PAIR = ('<div class="card"><span class="t">审批聚合</span>'
               '<span class="n">APPROVAL AGGREGATE</span></div>')


def test_rlang_pair_warns_on_authored_slide():
    iss = _run("R-LANG", [_slide(_TRANS_PAIR, lifted=False)])
    assert "R-LANG" in _codes(iss, "warnings")
    assert "R-LANG" not in _codes(iss, "soft_warnings")


def test_rlang_pair_downgrades_on_imported_slide():
    iss = _run("R-LANG", [_slide(_TRANS_PAIR, lifted=True)])
    assert "R-LANG" not in _codes(iss, "errors")
    assert "R-LANG" in _codes(iss, "soft_warnings"), "imported Latin-pair must be soft"


# --- end-to-end: a fully-imported canvas deck has 0 errors via the audits ----
_TARGET_RULES = {"R05", "R10", "R-KEY", "R-LANG"}


def test_imported_deck_no_blocking_errors_across_target_rules():
    """The four CONTENT-AUTHORING families on imported slides → 0 errors (soft
    warns ok). Scoped to the target rules (the original ran exactly these 4
    audit functions); a minimal fixture also trips unrelated STRUCTURAL rules
    (R48/R36/L1/R07/runtime/doc-integrity) which were never in this test's
    purview and are covered elsewhere."""
    E.skip_if_no_engine()
    slides = [
        _slide("<p>未完待续…</p>" + _OFF_HEX_BODY + _TRANS_PAIR,
               key="slide-001", lifted=True),
    ]
    errs = [f["rule"] for f in E.run(slides)
            if f.get("severity") == "error" and f.get("rule") in _TARGET_RULES]
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
