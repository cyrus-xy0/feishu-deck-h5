"""R-SELF-CONTAINED (LIFT-ARCHITECTURE L5) must-fire / must-not-fire guards.

The rule flags per-slide CSS that lives in a head/deck-level <style> (the
page-anim leak — vanishes on republish, left behind on lift) but must NOT flag
the renderer's co-located `<style data-fs-custom-css>` inside .slide, nor the
inlined framework stylesheet. It is a NON-escalating advisory (warn_soft).
"""
import pathlib
import sys

ASSETS = pathlib.Path(__file__).resolve().parents[1] / "assets"
sys.path.insert(0, str(ASSETS))

import _validate_common as C  # noqa: E402
import _validate_audits as A  # noqa: E402


def _run(html):
    iss = C.Issues()
    A.audit_self_contained(html, iss)
    codes = [c for c, _ in iss.soft_warnings]
    hard = [c for c, _ in iss.errors] + [c for c, _ in iss.warnings]
    return codes, hard


HEAD = '<!doctype html><html><head>{style}</head><body><div class="deck">{body}</div></body></html>'
FRAME = '<div class="slide-frame"><div class="slide" data-layout="raw" data-slide-key="{k}">{inner}</div></div>'


def test_head_style_referencing_slide_key_fires():
    html = HEAD.format(
        style='<style id="fs-deck-page-anim">.slide[data-slide-key="hero"] .x{opacity:1}</style>',
        body=FRAME.format(k="hero", inner="<h1>hi</h1>"))
    soft, hard = _run(html)
    assert "R-SELF-CONTAINED" in soft
    assert hard == []   # advisory only — never an error/warning


def test_head_style_referencing_data_page_fires():
    html = HEAD.format(
        style='<style>[data-page="03"] .y{transform:none}</style>',
        body=FRAME.format(k="hero", inner="<h1>hi</h1>"))
    soft, _ = _run(html)
    assert "R-SELF-CONTAINED" in soft


def test_co_located_custom_css_inside_slide_does_not_fire():
    # the renderer's GOOD pattern: <style data-fs-custom-css> as a child of .slide
    inner = ('<style data-slide-key="hero" data-fs-custom-css>'
             '.slide[data-slide-key="hero"] .x{opacity:1}</style>'
             '<div class="wordmark">飞书</div><h1>hi</h1>')
    html = HEAD.format(style='', body=FRAME.format(k="hero", inner=inner))
    soft, _ = _run(html)
    assert "R-SELF-CONTAINED" not in soft


def test_framework_inlined_block_does_not_fire():
    # inline_linked marks framework CSS data-source="framework"; it is generic
    # and exempt even if it somehow mentions a key-like token.
    html = HEAD.format(
        style='<style data-source="framework">.slide[data-slide-key="x"]{color:red}</style>',
        body=FRAME.format(k="x", inner="<h1>hi</h1>"))
    soft, _ = _run(html)
    assert "R-SELF-CONTAINED" not in soft


def test_head_style_without_perslide_selector_does_not_fire():
    # a generic head <style> with no [data-slide-key]/[data-page] is fine
    html = HEAD.format(
        style='<style>.deck{background:#000}</style>',
        body=FRAME.format(k="hero", inner="<h1>hi</h1>"))
    soft, _ = _run(html)
    assert "R-SELF-CONTAINED" not in soft


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
