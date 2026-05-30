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

Static — no Chromium needed.
"""
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
from _validate_common import Issues          # noqa: E402
from _validate_audits import (               # noqa: E402
    audit_font_sizes, audit_type_ladder, _deck_imported,
)

# off-floor body (18px) + off-tier (82px) in slide content; plus chrome fonts
_CONTENT = ('<style>'
            '[data-page="01"] .slide .card .cbody { font-size: 18px; } '
            '[data-page="01"] .slide .x { font-size: 82px; } '
            '.pager { font-size: 12px; } .nav-hint { font-size: 11px; } '
            '.mode-toggle { font-size: 13px; } .fs-mobile-pageno { font-size: 12px; }'
            '</style><body><div class="slide"></div></body>')
_META = '<meta name="fs-deck-origin" content="imported">'


def _run(html):
    i = Issues()
    audit_font_sizes(html, i)
    audit_type_ladder(html, i)
    err = [c for c, _ in i.errors]
    warn = [c for c, _ in i.warnings]
    return err, warn


def test_deck_imported_detection():
    assert _deck_imported(_META + _CONTENT) is True
    assert _deck_imported(_CONTENT) is False


def test_normal_deck_font_violations_are_errors():
    err, warn = _run(_CONTENT)
    assert "R06" in err and "R20" in err, f"expected R06/R20 errors, got {err}"


def test_imported_deck_font_violations_still_error():
    """L1 REVERTED: being imported does NOT exempt fonts. Small body (R06) and
    off-size hero (R20) STILL error — being a foreign deck is not a license for
    unreadable text. The fix is enlarge+grow-box / hero-layout-size, not a
    severity downgrade."""
    err, warn = _run(_META + _CONTENT)
    assert "R06" in err, f"imported deck small-body must still ERROR (got err={err})"
    assert "R20" in err, f"imported deck off-size hero must still ERROR (got err={err})"


def test_present_mode_chrome_excluded_from_r06():
    """L3: pager / hint / mode-toggle / mobile nav fonts are framework chrome,
    never flagged as content font-floor violations — even though they sit below
    the chrome floor (11-13px). Holds regardless of imported origin."""
    for html in (_CONTENT, _META + _CONTENT):
        i = Issues()
        audit_font_sizes(html, i)
        chrome_hits = [m for c, m in i.errors + i.warnings
                       if c == "R06" and ("pager" in m or "nav-hint" in m
                                          or "mode-toggle" in m or "fs-mobile" in m)]
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
