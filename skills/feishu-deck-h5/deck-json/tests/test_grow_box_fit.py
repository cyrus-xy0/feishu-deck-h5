"""grow-box-fit.py — the CSS-rewrite matcher (2026-05-31).

This tool had several real bugs during development (inline comments inside
selectors, ' vs " quote mismatch, a \\s-in-replacement crash, catastrophic
regex backtracking). The rewrite is now a linear <style>-scoped tokenizer.
These tests pin the load-bearing behaviour so it can't silently regress.

Pure Python — no Chromium.
"""
import sys
import importlib.util
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
_spec = importlib.util.spec_from_file_location("growboxfit", ASSETS / "grow-box-fit.py")
gbf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gbf)


def _apply(html, changes):
    out, n = gbf._apply_changes(html, changes)
    return out, n


def test_basic_font_size_bump():
    html = '<style>[data-page="04"] .feat { font-size: 18px; }</style>'
    out, n = _apply(html, [('[data-page="04"] .feat', 18, 24)])
    assert n == 1 and "24px" in out and "18px" not in out


def test_font_shorthand_bump():
    html = '<style>.a { font: 500 18px/1.55 var(--x); }</style>'
    out, n = _apply(html, [('.a', 18, 24)])
    assert "24px/1.55" in out, out


def test_inline_comment_in_selector():
    # CSSOM strips the comment; source keeps it. Matcher must tolerate it.
    html = '<style>[data-page="04"] /* 注释 */ .card-tag { font: 600 18px/1 var(--x); }</style>'
    out, n = _apply(html, [('[data-page="04"] .card-tag', 18, 24)])
    assert n == 1 and "24px" in out, out


def test_quote_style_mismatch():
    # CSSOM normalises to "; source may use '. Must match interchangeably.
    html = "<style>.slide[data-slide-key='feiling'] .lbl { font:500 16px/1.3 var(--x); }</style>"
    out, n = _apply(html, [('.slide[data-slide-key="feiling"] .lbl', 16, 24)])
    assert n == 1 and "24px" in out, out


def test_word_boundary_guards_against_118():
    # bumping 18→24 must NOT touch 118px elsewhere in the same block.
    html = '<style>.a { font-size: 18px; width: 118px; }</style>'
    out, n = _apply(html, [('.a', 18, 24)])
    assert "font-size: 24px" in out and "118px" in out, out


def test_only_rewrites_inside_style_not_script():
    # braces / numbers in <script> JS must be untouched.
    html = ('<style>.a { font-size: 18px; }</style>'
            '<script>const a={x:18}; if(a){b=18}</script>')
    out, n = _apply(html, [('.a', 18, 24)])
    assert "const a={x:18}; if(a){b=18}" in out, "script JS was corrupted"
    assert "font-size: 24px" in out


def test_nonmatching_selector_no_change():
    html = '<style>.a { font-size: 18px; }</style>'
    out, n = _apply(html, [('.b', 18, 24)])
    assert n == 0 and "18px" in out


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
