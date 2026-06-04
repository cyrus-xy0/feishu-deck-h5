"""Imported/foreign raw deck font handling (2026-05-30, L1 REVERTED).

History: L1 originally made font rules ADVISORY for an imported deck
(`<meta name="fs-deck-origin" content="imported">`). That was WRONG — it hid
the very problems the user wants caught: small body text is unreadable no
matter who designed it, and an off-size hero is still wrong. So font-size
violations are NOT exempted for imported decks; the validator flags them and
the RIGHT fix is enlarge-to-floor + grow-box (small body) / hero at the
layout's defined size — never snap-and-overflow, never advisory-and-ignore.

L3 (still valid): present-mode UI chrome (pager / fullscreen-hint / mode-toggle
    / mobile nav) is framework UI, NOT slide content — excluded from R06.

UNIFY-VALIDATE-ARCH step 4b: R06 / R20 now live in the unified engine (rendered
DOM). The `_deck_imported` helper that the old _validate_audits.py exported is
gone; the behavioral invariant it backed (imported decks are NOT exempted from
the font floors — L1 reverted) is now asserted directly through the engine.
Requires Chromium.
"""
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import engine_helpers as E  # noqa: E402

# off-floor body (18px) + off-tier (82px) in slide content; plus chrome fonts
_CONTENT = ('<style>'
            '[data-page="01"] .slide .card .cbody { font-size: 18px; } '
            '[data-page="01"] .slide .x { font-size: 82px; } '
            '.pager { font-size: 12px; } .nav-hint { font-size: 11px; } '
            '.mode-toggle { font-size: 13px; } .fs-mobile-pageno { font-size: 12px; }'
            '</style><body><div class="slide"></div></body>')
_META = '<meta name="fs-deck-origin" content="imported">'


def _run(html):
    E.skip_if_no_engine()
    findings = E.run(html)
    err = [f["rule"] for f in findings if f.get("severity") == "error"]
    warn = [f["rule"] for f in findings if f.get("severity") == "warn"]
    return err, warn


def test_normal_deck_font_violations_are_errors():
    err, warn = _run(_CONTENT)
    assert "R06" in err and "R20" in err, f"expected R06/R20 errors, got {err}"


def test_imported_deck_font_violations_still_error():
    """L1 REVERTED: being imported does NOT exempt fonts. Small body (R06) and
    off-size hero (R20) STILL error — being a foreign deck is not a license for
    unreadable text. The fix is enlarge+grow-box / hero-layout-size, not a
    severity downgrade. (The engine reproduces the no-downgrade behavior the old
    _deck_imported gate enforced.)"""
    err, warn = _run(_META + _CONTENT)
    assert "R06" in err, f"imported deck small-body must still ERROR (got err={err})"
    assert "R20" in err, f"imported deck off-size hero must still ERROR (got err={err})"


def test_present_mode_chrome_excluded_from_r06():
    """L3: pager / hint / mode-toggle / mobile nav fonts are framework chrome,
    never flagged as content font-floor violations — even though they sit below
    the chrome floor (11-13px). Holds regardless of imported origin."""
    for html in (_CONTENT, _META + _CONTENT):
        E.skip_if_no_engine()
        chrome_hits = [f["message"] for f in E.run(html)
                       if f.get("rule") == "R06" and any(
                           tok in f.get("message", "")
                           for tok in ("pager", "nav-hint", "mode-toggle", "fs-mobile"))]
        assert not chrome_hits, f"present-mode chrome wrongly flagged by R06: {chrome_hits}"


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
