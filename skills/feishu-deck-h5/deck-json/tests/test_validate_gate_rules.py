"""Must-fire / must-not-fire unit tests for the ingest-gate-MANDATORY validator
rules in assets/validate.py that had NO dedicated automated coverage.

business-rules.yaml lists 21 MANDATORY ingest-gate rule codes. Seven of them
(R-DOM, R-WHITE-TEXT, R02, R06, R10, R12, R20) are already covered in
test_validate_static_rules.py / test_validate_r_lang.py and are NOT repeated
here. This module targets the remaining 14:

    L1, L2, L4, R-HIERARCHY, R-KEY, R-OVERFLOW, R05, R13,
    R47, R48, R49, R56, T01, T02

Each code was located by grepping its literal in assets/validate.py and reading
the emitting audit function to learn its real signature, the exact firing
condition, the scoped selector, and any opt-out token. Fixtures below were
verified against the code, NOT guessed.

TRIAGE (static-callable vs visual/Playwright-only):

  STATIC (13 codes — tested here, in-process call on an HTML/CSS string):
    L1            audit_layout_integrity(html, iss)   -> check_logo_default
    L2            audit_layout_integrity(html, iss)   -> check_balance
    L4            audit_layout_integrity(html, iss)   -> check_attrs_density
    R-HIERARCHY   audit_hierarchy(html, iss)          warn
    R-KEY         audit_slide_keys(slides, iss)       err/warn
    R05           audit_copy_rules(html, iss)         err
    R13           audit_titles_one_line(slides, iss)  err
    R47           audit_variant_discipline(html, iss) warn
    R48           audit_default_centering(html, iss)  err
    R49           audit_no_cyan_accent(slides, iss)   err
    R56           audit_header_minimal(slides, iss)   warn

  VISUAL / Playwright-only (1 code — NOT statically testable, listed not tested):
    R-OVERFLOW  · emitted ONLY from run_visual_audits() at validate.py:2527,
                  from `report = page.evaluate(_visual_audit_js())` after a
                  headless-Chromium `page.goto(...)` measures each slide's
                  scrollHeight/scrollWidth in `data-mode="present"`. There is no
                  Python audit_* that takes a string and emits R-OVERFLOW — the
                  overflow geometry only exists once the deck is laid out in a
                  real browser viewport. A static fixture cannot trigger it
                  without a Playwright harness, which is out of scope for these
                  static unit tests (and would be flaky / require chromium).

Notes verified from code:
  * L1/L2/L4 all surface through the single in-process entry point
    audit_layout_integrity(html, iss); the L* helpers are pure predicates.
  * L2 (check_balance) SKIPS a layout absent from the html; R48
    (check_default_centering) does NOT — it yields EVERY centerable layout
    lacking a centering rule, so an R48 must-not-fire must center all six
    centerable layouts (content-3up/content-2col/agenda/stats/big-stat/quote).
  * R13 & R56 skip HERO_TITLE_LAYOUTS = {cover, image-text, end, section,
    quote}; fixtures use `stats` so the audit actually runs.
  * R-HIERARCHY / R47 scan AUTHOR CSS only (include_framework=False), so
    fixtures use a plain <style> (no data-source="framework").
"""
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import validate as V  # noqa: E402,F401
import engine_helpers as E  # noqa: E402

# UNIFY-VALIDATE-ARCH step 4b: these gate rules now live ONLY in the unified
# engine (audits.js, rendered DOM). The old `audit_*` source-scan calls are
# replaced by an engine run filtered to the rule code. Aliases keep the call
# sites readable; the `L1/L2/L4` rule emits each of L1/L2/L4 separately, so each
# test passes its specific code. Requires Chromium (skips if unavailable).
L1, L2, L4 = "L1", "L2", "L4"
R_HIERARCHY, R_KEY, R05, R13 = "R-HIERARCHY", "R-KEY", "R05", "R13"
R47, R48, R49, R56 = "R47", "R48", "R49", "R56"


def _doc(head_style: str = "", body: str = "") -> str:
    """Minimal full HTML doc with one <style> block + a <body>."""
    return (
        "<html><head><style>" + head_style + "</style></head>"
        "<body>" + body + "</body></html>"
    )


def _slide(layout: str, body: str = "", *, key: str = "k") -> str:
    return (
        f'<div class="slide-frame"><div class="slide" '
        f'data-layout="{layout}" data-screen-label="x" data-slide-key="{key}">'
        f"{body}</div></div>"
    )


def _err_codes(rule, html_or_slides):
    E.skip_if_no_engine()
    return E.err_codes(rule, html_or_slides)


def _all_codes(rule, html_or_slides):
    """errors + warnings + soft_warnings codes (some rules warn, some err)."""
    E.skip_if_no_engine()
    return E.all_codes(rule, html_or_slides)


# ==========================================================================
# L1  audit_layout_integrity -> check_logo_default
#   fires when `.slide .wordmark { background: ... }` does NOT reference
#   var(--fs-asset-logo) (the colored default). is-mono / asset-logo-mono
#   must be opt-in.
# ==========================================================================

def test_l1_missing_colored_logo_default_fires():
    # No `.slide .wordmark { background: var(--fs-asset-logo) }` rule at all
    # -> check_logo_default returns False -> L1.
    html = _doc(".slide .desc { font-size: 24px; }")
    assert "L1" in _err_codes(L1, html)


def test_l1_mono_default_fires():
    # The default wordmark points at the MONO asset -> not the colored default.
    html = _doc(".slide .wordmark { background: var(--fs-asset-logo-mono); }")
    assert "L1" in _err_codes(L1, html)


def test_l1_colored_logo_default_no_fire():
    # Default references var(--fs-asset-logo) (colored) -> compliant.
    html = _doc(".slide .wordmark { background: var(--fs-asset-logo); }")
    assert "L1" not in _err_codes(L1, html)


# ==========================================================================
# L2  audit_layout_integrity -> check_balance
#   for short-content layouts USED in the deck, the body container
#   (.stage/.grid/.flow/.nodes) must declare align-content/justify-content:
#   center OR flex: 1. Layouts not present in the html are skipped.
# ==========================================================================

def test_l2_uncentered_short_layout_fires():
    # content-2col is used (markup) but its .grid has no centering / flex:1.
    html = (
        "<html><head><style>"
        '.slide[data-layout="content-2col"] .grid { gap: 24px; }'
        "</style></head><body>"
        + _slide("content-2col", '<div class="grid"></div>')
        + "</body></html>"
    )
    assert "L2" in _err_codes(L2, html)


def test_l2_centered_layout_no_fire():
    # Same layout, .grid declares align-content: center -> balanced.
    html = (
        "<html><head><style>"
        '.slide[data-layout="content-2col"] .grid '
        "{ align-content: center; }"
        "</style></head><body>"
        + _slide("content-2col", '<div class="grid"></div>')
        + "</body></html>"
    )
    assert "L2" not in _err_codes(L2, html)


def test_l2_layout_absent_no_fire():
    # No short-content layout string appears ANYWHERE in the html (the guard
    # `if f'data-layout="{layout}"' not in html` matches the whole document,
    # including <style> selectors) -> every short-content rule is N/A.
    html = (
        "<html><head><style>.slide .desc { font-size: 24px; }</style></head>"
        "<body>" + _slide("cover") + "</body></html>"
    )
    assert "L2" not in _err_codes(L2, html)


# ==========================================================================
# L4  audit_layout_integrity -> check_attrs_density
#   process .output .attrs must be grid-template-columns: 1fr (single col).
#   No such rule at all -> N/A (compliant).
# ==========================================================================

def test_l4_two_col_attrs_fires():
    html = _doc(
        '.slide[data-layout="process"] .output .attrs '
        "{ grid-template-columns: 1fr 1fr; }"
    )
    assert "L4" in _err_codes(L4, html)


def test_l4_single_col_attrs_no_fire():
    html = _doc(
        '.slide[data-layout="process"] .output .attrs '
        "{ grid-template-columns: 1fr; }"
    )
    assert "L4" not in _err_codes(L4, html)


def test_l4_no_output_panel_no_fire():
    # No process .output .attrs rule -> rule does not apply.
    html = _doc(".slide .desc { font-size: 24px; }")
    assert "L4" not in _err_codes(L4, html)


# ==========================================================================
# R-HIERARCHY  audit_hierarchy(html, iss)  [warn]
#   author CSS only; a META_CLASS_RE selector (owner/attrib/source/
#   timestamp/status/kicker/eyebrow/...) at font-size > FLOOR_BODY_PX (24).
# ==========================================================================

def test_hierarchy_oversized_meta_fires():
    # .source is a meta class; 28px > 24px body floor -> inverted hierarchy.
    html = _doc(".slide .source { font-size: 28px; }")
    assert "R-HIERARCHY" in _all_codes(R_HIERARCHY, html)


def test_hierarchy_meta_within_body_no_fire():
    # Same meta class at 16px (<= 24) -> correct hierarchy.
    html = _doc(".slide .source { font-size: 16px; }")
    assert "R-HIERARCHY" not in _all_codes(R_HIERARCHY, html)


def test_hierarchy_column_label_exempt_no_fire():
    # .side-pill matches COLUMN_LABEL_RE -> it is a content label, not meta.
    html = _doc(".slide .side-pill { font-size: 28px; }")
    assert "R-HIERARCHY" not in _all_codes(R_HIERARCHY, html)


def test_hierarchy_allow_meta_larger_exemption_no_fire():
    # /* allow:meta-larger */ opts the rule out (rare hero-owner case).
    html = _doc(".slide .owner { font-size: 28px; /* allow:meta-larger */ }")
    assert "R-HIERARCHY" not in _all_codes(R_HIERARCHY, html)


# ==========================================================================
# R-KEY  audit_slide_keys(slides, iss)  [err / warn]
#   every .slide must carry a unique, kebab-case, semantic data-slide-key.
# ==========================================================================

def test_rkey_missing_fires():
    # Slide-frame with a .slide but NO data-slide-key attribute.
    frame = ('<div class="slide-frame"><div class="slide" '
             'data-layout="stats" data-screen-label="x">body</div></div>')
    assert "R-KEY" in _err_codes(R_KEY, [frame])


def test_rkey_invalid_slug_fires():
    # Uppercase + underscore -> not kebab-case.
    slides = [_slide("stats", key="ARR_History")]
    assert "R-KEY" in _err_codes(R_KEY, slides)


def test_rkey_duplicate_slug_fires():
    # Two slides share the same key -> not deck-internal unique.
    slides = [_slide("stats", key="arr-history"),
              _slide("stats", key="arr-history")]
    assert "R-KEY" in _err_codes(R_KEY, slides)


def test_rkey_positional_slug_warns():
    # `slide-06` is positional -> warn (surfaced under all-codes), not silent.
    slides = [_slide("stats", key="slide-06")]
    assert "R-KEY" in _all_codes(R_KEY, slides)


def test_rkey_valid_semantic_keys_no_fire():
    # Distinct semantic kebab-case slugs -> clean (no err, no warn).
    slides = [_slide("stats", key="arr-history"),
              _slide("stats", key="case-meiyijia")]
    assert "R-KEY" not in _all_codes(R_KEY, slides)


# ==========================================================================
# R05  audit_copy_rules(html, iss)  [err]
#   no emoji / '!' / '…'(or ...) / '???' anywhere in slide body text.
#   <script>/<style>/<svg> are stripped before scanning.
# ==========================================================================

def test_r05_exclamation_fires():
    html = "<html><body><div class='slide'><p>太棒了!</p></div></body></html>"
    assert "R05" in _err_codes(R05, html)


def test_r05_ellipsis_fires():
    html = "<html><body><div class='slide'><p>未完待续...</p></div></body></html>"
    assert "R05" in _err_codes(R05, html)


def test_r05_emoji_fires():
    html = "<html><body><div class='slide'><p>发布啦\U0001F680</p></div></body></html>"
    assert "R05" in _err_codes(R05, html)


def test_r05_clean_copy_no_fire():
    html = "<html><body><div class='slide'><p>完整的一句话。</p></div></body></html>"
    assert "R05" not in _err_codes(R05, html)


def test_r05_svg_title_stripped_no_fire():
    # An exclamation lives inside <svg><title> (a11y text), not slide copy
    # -> stripped before scanning -> no fire.
    html = ("<html><body><div class='slide'>"
            "<svg><title>alert!</title></svg>正文内容。"
            "</div></body></html>")
    assert "R05" not in _err_codes(R05, html)


# ==========================================================================
# R13  audit_titles_one_line(slides, iss)  [err]
#   <br> inside a header <h2 class="title"/"title-zh"> on a NON-hero layout.
# ==========================================================================

def test_r13_br_in_title_fires():
    # `stats` is not a hero layout -> a <br> in the title is forbidden.
    slides = [_slide("stats", '<h2 class="title-zh">飞书企<br>业 AI</h2>')]
    assert "R13" in _err_codes(R13, slides)


def test_r13_single_line_title_no_fire():
    slides = [_slide("stats", '<h2 class="title-zh">飞书企业 AI</h2>')]
    assert "R13" not in _err_codes(R13, slides)


def test_r13_hero_layout_br_allowed_no_fire():
    # cover is a HERO layout -> multi-line hero titles (with <br>) are allowed.
    slides = [_slide("cover", '<h2 class="title-zh">飞书企<br>业 AI</h2>')]
    assert "R13" not in _err_codes(R13, slides)


# ==========================================================================
# R47  audit_variant_discipline(html, iss)  [warn]
#   author CSS; a [data-variant=...] rule that touches structure
#   (display:flex/grid, flex-direction, grid-template-*) but does NOT
#   redeclare BOTH align-items/place-items AND justify-content/place-content.
# ==========================================================================

def test_r47_structural_variant_missing_alignment_fires():
    html = _doc(
        '.slide[data-variant="wide"] .grid '
        "{ grid-template-columns: 1fr 1fr; }"
    )
    assert "R47" in _all_codes(R47, html)


def test_r47_structural_variant_with_alignment_no_fire():
    # Redeclares both align-items AND justify-content -> disciplined.
    html = _doc(
        '.slide[data-variant="wide"] .grid '
        "{ display: grid; grid-template-columns: 1fr 1fr; "
        "align-items: center; justify-content: center; }"
    )
    assert "R47" not in _all_codes(R47, html)


def test_r47_cosmetic_variant_no_fire():
    # Variant only changes color/padding -> no structural change -> exempt.
    html = _doc('.slide[data-variant="warm"] .card '
                "{ color: #fff; padding: 24px; }")
    assert "R47" not in _all_codes(R47, html)


def test_r47_pseudo_element_variant_no_fire():
    # ::before-targeting variant is decorative -> exempt even if structural.
    html = _doc('.slide[data-variant="x"] .arrow::before '
                "{ display: flex; }")
    assert "R47" not in _all_codes(R47, html)


# ==========================================================================
# R48  audit_default_centering(html, iss)  [err]
#   each centerable fixed-shape layout (content-3up / content-2col / agenda
#   / stats / big-stat / quote) must have a container centering rule SOMEWHERE
#   in the deck CSS. check_default_centering yields EVERY centerable layout
#   lacking one (regardless of whether it is used), so a must-not-fire fixture
#   must center all six.
# ==========================================================================

_CENTERABLE = ("content-3up", "content-2col", "agenda",
               "stats", "big-stat", "quote")


def _center_all_but(skip: str) -> str:
    rules = []
    for lay in _CENTERABLE:
        if lay == skip:
            continue
        rules.append(
            f'.slide[data-layout="{lay}"] .stage {{ justify-content: center; }}')
    return "".join(rules)


def test_r48_missing_centering_fires():
    # All centerable layouts centered EXCEPT `stats` -> R48 fires for stats.
    html = _doc(_center_all_but("stats"))
    assert "R48" in _err_codes(R48, html)


def test_r48_all_centered_no_fire():
    # Every centerable layout has a centering rule -> clean.
    rules = "".join(
        f'.slide[data-layout="{lay}"] .stage {{ align-content: center; }}'
        for lay in _CENTERABLE
    )
    html = _doc(rules)
    assert "R48" not in _err_codes(R48, html)


# ==========================================================================
# R49  audit_no_cyan_accent(slides, iss)  [err]
#   data-accent="cyan" on a slide is forbidden (cyan is inline-highlight only).
# ==========================================================================

def test_r49_cyan_accent_fires():
    frame = ('<div class="slide-frame"><div class="slide" '
             'data-layout="stats" data-screen-label="x" data-slide-key="k" '
             'data-accent="cyan">body</div></div>')
    assert "R49" in _err_codes(R49, [frame])


def test_r49_brand_accent_no_fire():
    frame = ('<div class="slide-frame"><div class="slide" '
             'data-layout="stats" data-screen-label="x" data-slide-key="k" '
             'data-accent="blue">body</div></div>')
    assert "R49" not in _err_codes(R49, [frame])


def test_r49_cyan_inline_highlight_no_fire():
    # cyan as an inline word highlight (.accent-text / .hl) — no data-accent.
    slides = [_slide("stats", '<span class="accent-text">关键词</span>')]
    assert "R49" not in _err_codes(R49, slides)


# ==========================================================================
# R56  audit_header_minimal(slides, iss)  [warn]
#   a content-page .header that still contains an .eyebrow (non-hero layout).
# ==========================================================================

def test_r56_eyebrow_in_header_fires():
    body = ('<div class="header"><div class="eyebrow">PRODUCT · X</div>'
            '<h2 class="title-zh">标题</h2></div>')
    slides = [_slide("stats", body)]
    assert "R56" in _all_codes(R56, slides)


def test_r56_title_only_header_no_fire():
    body = '<div class="header"><h2 class="title-zh">标题</h2></div>'
    slides = [_slide("stats", body)]
    assert "R56" not in _all_codes(R56, slides)


def test_r56_hero_layout_skipped_no_fire():
    # cover is a hero layout -> R56 does not police its header.
    body = ('<div class="header"><div class="eyebrow">PRODUCT · X</div>'
            '<h2 class="title-zh">标题</h2></div>')
    slides = [_slide("cover", body)]
    assert "R56" not in _all_codes(R56, slides)


if __name__ == "__main__":
    # Allow running without pytest: python3 test_validate_gate_rules.py
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
