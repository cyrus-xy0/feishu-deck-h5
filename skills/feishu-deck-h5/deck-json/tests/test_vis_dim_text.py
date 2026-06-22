"""R-VIS-DIM-TEXT — gradient-clipped text must not be mistaken for washed-out grey.

R-VIS-DIM-TEXT flags ≥8-char body text whose effective brightness on a dark canvas is
`alpha × luminance < 0.5`, read off `getComputedStyle(el).color`. The cinematic
gradient-accent idiom paints the glyphs from a `background` gradient and sets
`color:transparent` + `-webkit-background-clip:text`, so `color` carries no ink —
reading brightness off it yields a meaningless ~0% and a false "发灰看不清" warning.
The rule must skip any element whose visible ink comes from a `background-clip:text`
gradient. Regression guard for the cinematic-accent false-positive class.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402

RULE = "R-VIS-DIM-TEXT"
_TXT = "瓶颈早已移进了接缝之间根本够不到它们"


def _slide(inner):
    return ('<div class="slide" data-layout="content" data-slide-key="k" '
            'style="position:relative;width:1920px;height:1080px">'
            f'{inner}</div>')


def _run(html):
    E.skip_if_no_engine()
    return E.findings_for(RULE, html)


def test_wired():
    assert E.rule_in_engine(RULE)


def test_fires_on_soft_white_body():
    # rgba(255,255,255,.4) body on a dark canvas ≈ eff 0.4 < 0.5 → FIRE. Sanity guard:
    # the gradient-clip exemption below must not silence the whole rule.
    hits = _run(_slide(f'<p style="color:rgba(255,255,255,.4);font-size:24px">{_TXT}</p>'))
    assert len(hits) >= 1, f"soft-white 0.4 body not flagged: {hits}"


def test_silent_on_gradient_clipped_text():
    # Cinematic gradient-accent idiom: the glyphs are painted by the background gradient,
    # `color:transparent` is BY DESIGN. Reading brightness off `color` (→ 0%) is a false
    # positive — the rule must be SILENT. (Without the background-clip:text guard this
    # text reads as 0% effective brightness and fires.)
    grad = ('<p style="font-size:28px;font-weight:700;'
            'background:linear-gradient(92deg,#36D6FF,#4D7CFE);'
            '-webkit-background-clip:text;background-clip:text;color:transparent">'
            f'{_TXT}</p>')
    hits = _run(_slide(grad))
    assert hits == [], f"gradient-clipped accent text false-positived: {hits}"


def test_optout_silences():
    hits = _run(_slide(f'<p data-allow-dim-text '
                       f'style="color:rgba(255,255,255,.4);font-size:24px">{_TXT}</p>'))
    assert hits == [], f"data-allow-dim-text should silence: {hits}"


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
