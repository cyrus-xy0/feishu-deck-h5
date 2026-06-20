"""R-DECK-EYEBROW-BUDGET — deck-wide eyebrow density budget (F-349, 2026-06-20).

The "uppercase micro-label above every header" AI tell, as a deck-level budget
(taste-skill's "max 1 eyebrow per 3 sections"). Counts NON-hero content pages
carrying an eyebrow/kicker (class-exact `eyebrow`/`kicker`/`overline` incl. the
framework `.header .eyebrow`, OR a name-free de-facto micro-label: visible
own-text ≤24 chars, ≤22px, uppercase, letter-spacing ≥0.5px, non-chrome) and
warns when that count exceeds ⌈contentPages / 3⌉. Hero layouts are excluded so
their legit eyebrows don't count. WARN · advisory · opt-out
`data-allow-eyebrow-budget`.

Grounds the deck's existing "content/story pages = clean single-line title"
convention at deck scale. Static wiring lives in test_vis_deck_consistency.py;
this file covers must-fire / calibration behaviour through the headless engine.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402

RULE = "R-DECK-EYEBROW-BUDGET"

_EYE = ('<div class="header"><div class="eyebrow">SOME LABEL</div>'
        '<h2 class="title-zh">标题在这里</h2></div>')
_NOEYE = '<div class="header"><h2 class="title-zh">标题在这里</h2></div>'
# de-facto hand-rolled eyebrow (no .eyebrow class): uppercase + tracked + small.
_RAW_EYE = ('<div style="text-transform:uppercase;letter-spacing:2px;font-size:14px">new reflex</div>'
            '<h2 style="font-size:42px">标题在这里写一行</h2>')
_RAW_PLAIN = '<h2 style="font-size:42px">纯标题没有小标签</h2>'


def _slide(layout, inner, key="k", attrs=""):
    return (f'<div class="slide" data-layout="{layout}" data-slide-key="{key}" {attrs} '
            f'style="position:relative;width:1920px;height:1080px">{inner}</div>')


def _deck(slides):
    return [_slide(*s) for s in slides]


def _run(html):
    E.skip_if_no_engine()
    return E.findings_for(RULE, html)


def test_wired():
    assert E.rule_in_engine(RULE)


def test_fires_when_most_content_pages_have_eyebrow():
    # 6 content pages, 5 with an eyebrow → budget ⌈6/3⌉=2, 5 > 2 → FIRE.
    slides = [("content", _EYE if i < 5 else _NOEYE, f"s{i}") for i in range(6)]
    hits = _run(_deck(slides))
    assert len(hits) >= 1, f"5/6 content pages with eyebrow not flagged: {hits}"


def test_unclassed_uppercase_labels_not_counted():
    # DELIBERATE conservative scope (adversarial-verify hardening): a per-page
    # uppercase+tracked micro-label that is NOT class-marked stays SILENT. A
    # style-only de-facto detector mis-counts KPI tags (GMV/ARR), bilingual EN
    # glosses (revenue), and status badges (LIVE) as eyebrows → false positives.
    # Floor rule: prefer the miss (raw hand-rolled eyebrow) over the false alarm.
    slides = [("raw", _RAW_EYE if i < 5 else _RAW_PLAIN, f"s{i}") for i in range(6)]
    hits = _run(_deck(slides))
    assert hits == [], f"unclassed uppercase labels must NOT be counted as eyebrows: {hits}"


def test_kpi_and_status_badges_not_false_counted():
    # The three adversarial FP shapes, all unclassed: small uppercase tracked
    # KPI metric tag / status badge recurring on every page must stay silent.
    kpi = [("content",
            '<div class="header"><h2 class="title-zh">复盘</h2></div>'
            '<div style="font-size:18px;letter-spacing:1px;text-transform:uppercase;color:#888">GMV</div>'
            '<div style="font-size:48px">¥2.4亿</div>', f"k{i}") for i in range(6)]
    hits = _run(_deck(kpi))
    assert hits == [], f"recurring KPI metric tags miscounted as eyebrows: {hits}"


def test_silent_within_budget():
    # 6 content pages, 1 eyebrow → 1 ≤ ⌈6/3⌉=2 → SILENT.
    slides = [("content", _EYE if i < 1 else _NOEYE, f"s{i}") for i in range(6)]
    hits = _run(_deck(slides))
    assert hits == [], f"1/6 eyebrow within budget false-positived: {hits}"


def test_hero_pages_excluded():
    # eyebrows on hero/section pages are legit and must NOT count (0 content pages).
    slides = [("section", _EYE, f"s{i}") for i in range(6)]
    hits = _run(_deck(slides))
    assert hits == [], f"hero-page eyebrows wrongly counted: {hits}"


def test_defacto_excludes_pageno_and_units():
    # uppercase tracked SHORT chrome that is NOT an eyebrow (pageno / unit) must not
    # be counted as an eyebrow even though it is small + uppercase + tracked.
    chrome = ('<div class="pageno" style="text-transform:uppercase;letter-spacing:2px;font-size:14px">PAGE 01</div>'
              '<div class="unit" style="text-transform:uppercase;letter-spacing:2px;font-size:14px">GMV YOY</div>'
              '<h2 style="font-size:42px">纯标题没有小标签</h2>')
    slides = [("raw", chrome, f"s{i}") for i in range(6)]
    hits = _run(_deck(slides))
    assert hits == [], f"non-eyebrow chrome (pageno/unit) miscounted as eyebrow: {hits}"


def test_optout_silences():
    slides = [("content", _EYE, f"s{i}",
               "data-allow-eyebrow-budget" if i == 0 else "") for i in range(6)]
    hits = _run([_slide(*s) for s in slides])
    assert hits == [], f"data-allow-eyebrow-budget should silence: {hits}"


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
