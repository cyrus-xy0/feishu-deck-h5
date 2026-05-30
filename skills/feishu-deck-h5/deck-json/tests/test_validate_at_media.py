"""F-11: @media-aware CSS resolution. A violation inside an @media that WOULD be
active at the deck's fixed 1920×1080 viewport is now audited (it was hidden when
all @-rules were blindly stripped); a violation inside a responsive override
that never renders (max-width < 1920, print) stays hidden — no false positives
on legitimate responsive CSS. Static, no Chromium.
"""
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
import validate as V  # noqa: E402


def _codes(html, fn):
    iss = V.Issues()
    fn(html, iss)
    return [c for c, _ in iss.errors + iss.warnings]


def _body(inner):
    return f'<html><head></head><body>{inner}</body></html>'


# ---- media-query matcher (unit) ----
def test_mq_screen_all_empty_active():
    assert V._media_query_matches('screen')
    assert V._media_query_matches('all')
    assert V._media_query_matches('')


def test_mq_print_inactive():
    assert not V._media_query_matches('print')
    assert not V._media_query_matches('only print')


def test_mq_responsive_maxwidth_inactive():
    assert not V._media_query_matches('(max-width: 768px)')
    assert not V._media_query_matches('screen and (max-width: 1200px)')


def test_mq_widths_covering_1920_active():
    assert V._media_query_matches('(min-width: 1200px)')
    assert V._media_query_matches('(max-width: 1920px)')
    assert V._media_query_matches('(min-width: 1920px)')


def test_mq_comma_is_or():
    # one branch matches (screen) → active, even though the other (print) doesn't
    assert V._media_query_matches('print, screen')


# ---- integration: R06 floor inside @media ----
def test_r06_fires_inside_active_media():
    html = _body('<style>@media screen { .slide .body { font-size: 18px } }</style>')
    assert 'R06' in _codes(html, V.audit_font_sizes)


def test_r06_not_fired_inside_responsive_media():
    html = _body('<style>@media (max-width: 768px) { .slide .body { font-size: 18px } }</style>')
    assert 'R06' not in _codes(html, V.audit_font_sizes)


def test_top_level_violation_still_fires():
    # control: the same violation outside any @media still fires (no regression)
    html = _body('<style>.slide .body { font-size: 18px }</style>')
    assert 'R06' in _codes(html, V.audit_font_sizes)


def test_keyframes_still_dropped():
    # @keyframes has no auditable selector rules; its % steps must not be scanned
    css = V._strip_nested_at_rules('@keyframes spin{0%{opacity:0}100%{opacity:1}} .y{color:red}')
    assert '0%' not in css and '.y{color:red}' in css


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
