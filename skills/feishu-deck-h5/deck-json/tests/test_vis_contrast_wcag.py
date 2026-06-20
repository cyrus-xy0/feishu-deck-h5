"""R-VIS-CONTRAST-WCAG — text vs effective background below WCAG AA (F-351, 2026-06-20).

The complement to R-VIS-DIM-TEXT (which assumes a dark canvas and uses a brightness
heuristic). This rule resolves each ≥8-char body element's EFFECTIVE background by
walking ancestors for the first opaque solid `background-color`, and ONLY when that
backdrop is light-ish (relative luminance ≥ 0.35) computes the true gamma-correct
WCAG contrast ratio `(L1+.05)/(L2+.05)`, flagging body text below 4.5:1 (large/bold
text below 3:1). Conservative by design (floor rule — false-negative over
false-positive): gradient / image / translucent / unresolvable / DARK backgrounds are
all exempt (dark is DIM-TEXT's domain → ZERO double-report), as are hero layouts /
chrome / ALL-CAPS eyebrows / bilingual `-en` / mock-internal text. WARN · advisory ·
opt-out `data-allow-contrast`.

Catches the slop DIM-TEXT structurally can't see: light-grey body on a white card,
white text on a pale callout.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402

RULE = "R-VIS-CONTRAST-WCAG"
_TXT = "这是一段中文正文内容用于测试对比度阈值是否被正确判定"


def _card(bg, color, fs="20px", txt=_TXT, attrs=""):
    return ('<div class="slide" data-layout="content" data-slide-key="k" '
            'style="position:relative;width:1920px;height:1080px">'
            f'<div style="background:{bg};padding:40px">'
            f'<p {attrs} style="color:{color};font-size:{fs};margin:0">{txt}</p></div></div>')


def _run(html):
    E.skip_if_no_engine()
    return E.findings_for(RULE, html)


def test_wired():
    assert E.rule_in_engine(RULE)


def test_fires_on_low_contrast_body_on_light_card():
    # #999 grey body on #fff card ≈ 2.8:1 < 4.5 → FIRE.
    hits = _run(_card("#ffffff", "#999999"))
    assert len(hits) >= 1, f"low-contrast grey-on-white body not flagged: {hits}"


def test_silent_on_high_contrast_body():
    # #222 near-black on #fff ≈ 16:1 → SILENT.
    hits = _run(_card("#ffffff", "#222222"))
    assert hits == [], f"high-contrast dark-on-white false-positived: {hits}"


def test_silent_on_dark_background_dimtext_domain():
    # grey on #000: bg is dark (relLum < 0.35) → DIM-TEXT's domain → EXEMPT here
    # (the no-double-report guarantee — both rules must never fire on the same text).
    hits = _run(_card("#000000", "#777777"))
    assert hits == [], f"dark-bg text should be left to DIM-TEXT (no double-report): {hits}"


def test_silent_on_gradient_background():
    # gradient backdrop is unresolvable → conservative EXEMPT.
    hits = _run(_card("linear-gradient(#ffffff,#eeeeee)", "#999999"))
    assert hits == [], f"gradient-bg should be exempt (unresolvable effective bg): {hits}"


def test_silent_on_saturated_brand_text():
    # Feishu brand blue #3370ff (4.28:1) and brand green #16a34a (3.3:1) on a white
    # card are INTENTIONAL colored text, not washed-out grey — exempt (parity with
    # R-VIS-DIM-TEXT's maxc-minc>40 saturation gate). Adversarial-verify FP class.
    assert _run(_card("#ffffff", "#3370ff")) == [], "brand blue text false-positived"
    assert _run(_card("#ffffff", "#16a34a")) == [], "brand green text false-positived"


def test_silent_on_light_text_over_dark_scrim():
    # The readable "light caption over a dark scrim/overlay" pattern: a dark absolute
    # SIBLING covers the white card the ancestor-walk resolves, so a naive ratio reads
    # ~1.1:1 and would false-fire. Light composited text (relLum > 0.55) → conservative
    # SKIP (the real backdrop is layered, not the resolved light card).
    scrim = ('<div class="slide" data-layout="content" data-slide-key="sc" '
             'style="position:relative;width:1920px;height:1080px">'
             '<div style="position:relative;background:#ffffff;padding:60px">'
             '<div style="position:absolute;inset:0;background:#0d0d0d;z-index:0"></div>'
             f'<p style="position:relative;z-index:1;color:#f5f5f5;font-size:22px;margin:0">{_TXT}</p>'
             '</div></div>')
    hits = _run(scrim)
    assert hits == [], f"light-on-dark-scrim caption false-positived: {hits}"


def test_large_text_uses_3to1_threshold():
    # #858585 on #fff ≈ 3.7:1 (clear margin both sides): FAILS body (4.5) but PASSES
    # large (3.0). At 48px it is large → must be SILENT; at 20px body → must FIRE.
    big = _run(_card("#ffffff", "#858585", fs="48px", txt="大字标题对比度阈值测试内容"))
    assert big == [], f"large text wrongly held to the 4.5:1 body threshold: {big}"
    small = _run(_card("#ffffff", "#858585", fs="20px"))
    assert len(small) >= 1, f"body text not flagged at the 4.5:1 threshold: {small}"


def test_optout_silences():
    hits = _run(_card("#ffffff", "#999999", attrs="data-allow-contrast"))
    assert hits == [], f"data-allow-contrast should silence: {hits}"


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
