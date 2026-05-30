"""L1 + L3 (2026-05-30) — imported/foreign raw deck font handling.

L1: an imported deck (`<meta name="fs-deck-origin" content="imported">`) has the
    author's own typography. Our 4-tier ladder / floor rules (R06 / R20) are
    ADVISORY for it (warn), NOT errors — so we never "snap a foreign deck onto
    our ladder" (which flattens its hero/emphasis and breaks its fit).
    See IMPORT-RAW-DECK-LESSONS-2026-05-30.md.

L3: present-mode UI chrome (pager / fullscreen-hint / mode-toggle / mobile nav)
    is framework UI, NOT slide content — excluded from R06 (检查只查内容).

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


def test_imported_deck_font_violations_are_advisory():
    """L1: same violations, but the deck is imported → WARN, not ERROR."""
    err, warn = _run(_META + _CONTENT)
    assert "R06" not in err and "R20" not in err, \
        f"imported deck still has font ERRORS (should be warns): {err}"
    assert "R06" in warn and "R20" in warn, \
        f"imported deck should DOWNGRADE font violations to warn, got warns={warn}"


def test_present_mode_chrome_excluded_from_r06():
    """L3: pager / hint / mode-toggle / mobile nav fonts are framework chrome,
    never flagged as content font-floor violations."""
    err, warn = _run(_CONTENT)
    # The chrome rules use 11-13px (below the 16 chrome floor) but must NOT fire
    # R06 — they're excluded by selector. R06 here is only the 18px .cbody body.
    r06_msgs = [m for c, m in Issues().errors]  # placeholder; check via full run
    i = Issues()
    audit_font_sizes(_CONTENT, i)
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
