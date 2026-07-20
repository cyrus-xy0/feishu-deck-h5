"""Unit tests for the static validator rules in assets/validate.py that were
previously untested (no dedicated test_*.py exercised them in isolation).

Covers must-fire / must-not-fire pairs (plus exemption / opt-out must-not-fire
variants) for these 8 audits:

    audit_font_sizes        -> R06         (body floor 24px / chrome floor 16px)
    audit_type_ladder       -> R20         (off-ladder per-page font-size)
    audit_undefined_css_vars-> R-CSSVAR    (var(--x) undefined, no fallback)
    audit_no_drop_shadows   -> R12         (real drop shadow on .slide rules)
    audit_hex_palette       -> R10         (hex outside brand palette in markup)
    audit_white_text        -> R-WHITE-TEXT(low-opacity white on dark slides)
    audit_list_echo         -> R-ECHO      (summary leaf echoes 3+ sibling prefixes)
    audit_dom_integrity     -> R-DOM       (slide-frame / .slide / div-balance)

UNIFY-VALIDATE-ARCH step 4b: the rules now live ONLY in the unified engine
(assets/audits.js, evaluated against the rendered DOM). These fixtures used to
call the old Python `audit_*` functions on source strings; they now run the SAME
rule through the engine via tests/engine_helpers.py — `err_codes("R06", html)` /
`all_codes(...)` render the fragment headlessly and return that rule's findings.
Requires Chromium (skips gracefully if unavailable). Fixtures are inline (no
dependency on examples/ / runs/ / absolute paths). Thresholds and HTML/CSS shapes
below were read directly from the engine rules, NOT assumed:
  * R06   reads FLOOR_BODY_PX=24, FLOOR_CHROME_PX=16; only audits selectors
          containing .slide/.card/.col/.toc/.cell/thead/tbody inside <style>.
  * R20   audits rules whose selector contains `[data-page=` OR
          `[data-slide-key=` (F-52: lifted/co-located per-page CSS keys off
          data-slide-key); ladder = {16,24,28,48}; honours /* allow:typescale */;
          lifted slides (data-lifted on the .slide) downgrade err->warn.
  * R12   ONLY audits rules whose selector STARTS with `.slide`; glow-ring
          `0 0 0 Npx`, `inset`, and /* allow:drop-shadow */ are exempt.
  * R10   strips <script>/<style>/<svg>/data: from <body> before hex scan;
          ALLOWED_HEX is the brand palette set.
  * R-WHITE-TEXT scans AUTHOR CSS only (skips data-source="framework"),
          selector must contain .slide/.card/.col, exempts chrome classes,
          rules with font-size<=14, and /* allow:white-opacity */.
  * R-ECHO needs >=4 leaves per slide; target leaf must be a <p> or carry a
          summary-intent class, be >=12 chars with >=4 CJK chars, and contain
          3+ distinct 2-4 char CJK prefixes of OTHER leaves; skips
          agenda/section/cover/end layouts.
  * R-DOM needs <html><body>; checks slide-frame-direct-child-of-.deck,
          exactly 1 .slide per frame, balanced <div>; opt-out
          <!-- allow:dom-integrity -->.
"""
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import validate as V  # noqa: E402,F401  (kept for V.Issues / extract_slides parity)
import engine_helpers as E  # noqa: E402

# Rule-code aliases — the migration kept every call site readable by aliasing the
# OLD audit-function names to the rule code the engine emits (so the per-test
# intent comments still line up). One engine run per call, filtered to the rule.
R06, R20, R_CSSVAR, R12, R10 = "R06", "R20", "R-CSSVAR", "R12", "R10"
R_WHITE_TEXT, R_ECHO, R_DOM = "R-WHITE-TEXT", "R-ECHO", "R-DOM"


def _doc(head_style: str = "", body: str = "") -> str:
    """Minimal full HTML doc with one <style> block + a <body>."""
    return (
        "<html><head><style>" + head_style + "</style></head>"
        "<body>" + body + "</body></html>"
    )


def _err_codes(rule, html_or_slides):
    E.skip_if_no_engine()
    return E.err_codes(rule, html_or_slides)


def _all_codes(rule, html_or_slides):
    """errors + warnings + soft_warnings codes (some rules warn, some err)."""
    E.skip_if_no_engine()
    return E.all_codes(rule, html_or_slides)


def _slide(layout: str, body: str = "") -> str:
    return (
        f'<div class="slide-frame"><div class="slide" '
        f'data-layout="{layout}" data-screen-label="x" data-slide-key="k">'
        f"{body}</div></div>"
    )


# ==========================================================================
# R06  audit_font_sizes
# ==========================================================================

def test_r06_body_floor_fires():
    # .desc is a BODY class -> 24px floor; 18px < 24 -> error. Selector
    # carries `.slide` so the audit scans it.
    html = _doc(".slide .desc { font-size: 18px; }")
    assert "R06" in _err_codes(R06, html)


def test_r06_chrome_floor_fires():
    # .eyebrow is a CHROME class -> 16px floor; 12px < 16 -> error.
    html = _doc(".slide .eyebrow { font-size: 12px; }")
    assert "R06" in _err_codes(R06, html)


def test_r06_compliant_no_fire():
    # body class at exactly the 24px floor + chrome at 16px -> clean.
    html = _doc(".slide .desc { font-size: 24px; } "
                ".slide .eyebrow { font-size: 16px; }")
    assert "R06" not in _err_codes(R06, html)


def test_r06_allow_body_floor_exemption_no_fire():
    # /* allow:body-floor */ in the rule opts the body class out of 24px.
    html = _doc(".slide .desc { font-size: 18px; /* allow:body-floor */ }")
    assert "R06" not in _err_codes(R06, html)


def test_r06_allow_typescale_exemption_no_fire():
    # /* allow:typescale */ fully exempts the rule (rung-8 mockup-internal).
    html = _doc(".slide .desc { font-size: 11px; /* allow:typescale */ }")
    assert "R06" not in _err_codes(R06, html)


# ==========================================================================
# R20  audit_type_ladder
# ==========================================================================

def test_r20_off_ladder_fires():
    # 30px is off the {16,24,28,48} ladder, on a per-page rule -> error.
    html = _doc('[data-page="3"] .cbody { font-size: 30px; }')
    assert "R20" in _err_codes(R20, html)


def test_r20_on_ladder_no_fire():
    # All sizes on-ladder -> clean.
    html = _doc('[data-page="3"] .cbody { font-size: 24px; } '
                '[data-page="3"] h2 { font-size: 48px; }')
    assert "R20" not in _err_codes(R20, html)


def test_r20_slide_key_off_ladder_fires():
    # F-52: a per-page rule keyed off [data-slide-key=...] (lifted / co-located
    # CSS scheme) with an off-ladder size MUST report R20. Previously the gate
    # only recognised [data-page=...], so slide-key pages slipped through as a
    # dead gate. The .slide is NOT marked data-lifted -> stays a hard error.
    html = _doc('[data-slide-key="abc"] .cbody { font-size: 30px; }')
    assert "R20" in _err_codes(R20, html)


def test_r20_lifted_slide_key_off_ladder_downgrades_to_warn():
    # F-52: when the slide IS lifted (a `<div class="slide" data-lifted
    # data-slide-key="abc">` exists), the off-ladder R20 downgrades err->warn so
    # a 36-page lift doesn't drown the gate. It must still SURFACE (in warnings),
    # just not block as an error.
    html = (
        '<html><head><style>'
        '[data-slide-key="abc"] .cbody { font-size: 30px; }'
        '</style></head><body>'
        '<div class="slide-frame">'
        '<div class="slide" data-lifted data-slide-key="abc">x</div>'
        '</div></body></html>'
    )
    assert "R20" not in _err_codes(R20, html)
    assert "R20" in _all_codes(R20, html)


def test_r20_non_per_page_rule_ignored():
    # Off-ladder size but NEITHER [data-page=...] NOR [data-slide-key=...] in the
    # selector -> R20 ignores it (the global framework stylesheet owns hero
    # values).
    html = _doc(".slide .cbody { font-size: 30px; }")
    assert "R20" not in _err_codes(R20, html)


def test_r20_allow_typescale_exemption_no_fire():
    # /* allow:typescale */ opts a per-page hero value off the ladder.
    html = _doc('[data-page="1"] .hero-num { font-size: 132px; '
                '/* allow:typescale */ }')
    assert "R20" not in _err_codes(R20, html)


# ==========================================================================
# R-CSSVAR  audit_undefined_css_vars
# ==========================================================================

def test_cssvar_undefined_fires():
    # --fs-font-en is never defined and there's no fallback -> error.
    html = _doc(".slide h1 { font: 700 88px/0.9 var(--fs-font-en); }")
    assert "R-CSSVAR" in _err_codes(R_CSSVAR, html)


def test_cssvar_defined_no_fire():
    # The referenced var is defined in the same CSS source -> clean.
    html = _doc(":root { --fs-blue: #3c7fff; } "
                ".slide h1 { color: var(--fs-blue); }")
    assert "R-CSSVAR" not in _err_codes(R_CSSVAR, html)


def test_cssvar_fallback_no_fire():
    # Undefined name BUT an explicit fallback -> fallback is the safety net.
    html = _doc(".slide h1 { color: var(--missing, #fff); }")
    assert "R-CSSVAR" not in _err_codes(R_CSSVAR, html)


# ==========================================================================
# R12  audit_no_drop_shadows
# ==========================================================================

# NOTE (step 4b · MORE-CORRECT divergence): the engine R12 reads the COMPUTED
# box-shadow on the rendered element (getComputedStyle), not the CSS source text.
# So each fixture must include an actual element matching the selector — the rule
# now judges what really paints (catches shadows applied via cascade/override the
# old source-scan missed). Same shape for R-WHITE-TEXT below.
def test_r12_drop_shadow_fires():
    # Non-zero offset/blur on a .slide rule -> real drop shadow -> warn.
    html = _doc(".slide .card { box-shadow: 0 8px 24px rgba(0,0,0,0.4); }",
                _slide("content", '<div class="card">x</div>'))
    assert "R12" in _all_codes(R12, html)


def test_r12_glow_ring_no_fire():
    # `0 0 0 6px ...` is a glow ring (zero offset/blur), not a drop shadow.
    html = _doc(".slide .card { box-shadow: 0 0 0 6px rgba(60,127,255,0.3); }",
                _slide("content", '<div class="card">x</div>'))
    assert "R12" not in _all_codes(R12, html)


def test_r12_inset_no_fire():
    # inset shadows are decorative inner highlights -> allowed.
    html = _doc(".slide .card { box-shadow: inset 0 2px 8px rgba(0,0,0,0.3); }",
                _slide("content", '<div class="card">x</div>'))
    assert "R12" not in _all_codes(R12, html)


def test_r12_allow_drop_shadow_exemption_no_fire():
    # /* allow:drop-shadow */ opts the rule out (UI-mock window chrome).
    html = _doc(".slide .ui-window { box-shadow: 0 8px 24px rgba(0,0,0,0.4); "
                "/* allow:drop-shadow */ }",
                _slide("content", '<div class="ui-window">x</div>'))
    assert "R12" not in _all_codes(R12, html)


# ==========================================================================
# R10  audit_hex_palette
# ==========================================================================

def test_r10_off_palette_hex_fires():
    # #abcdef is not in the brand palette and lives in slide markup -> warn.
    html = "<html><body>" + _slide(
        "stats", '<span style="color:#abcdef">x</span>') + "</body></html>"
    assert "R10" in _all_codes(R10, html)


def test_r10_palette_hex_no_fire():
    # #3c7fff and #080C18 are brand tokens -> clean.
    html = "<html><body>" + _slide(
        "stats", '<span style="color:#3c7fff;background:#080C18">x</span>') + "</body></html>"
    assert "R10" not in _all_codes(R10, html)


def test_r10_hex_inside_svg_no_fire():
    # Hex inside <svg> is stripped before scanning -> off-palette SVG hex OK.
    html = ("<html><body>" + _slide(
        "stats", '<svg><path fill="#abcdef"/></svg>') + "</body></html>")
    assert "R10" not in _all_codes(R10, html)


# ==========================================================================
# R-WHITE-TEXT  audit_white_text
# ==========================================================================

# NOTE (step 4b · MORE-CORRECT divergence): the engine R-WHITE-TEXT matches the
# author rule against the RENDERED element (slide.querySelectorAll(selector) +
# getComputedStyle), so each fixture carries a real `.cbody` element. Also the
# per-rule opt-out moved from a `/* allow:white-opacity */` CSS comment (invisible
# to CSSOM after parsing) to a `data-allow-white-opacity` ATTRIBUTE on the element
# — the comment form silently stopped working under the DOM engine, the attribute
# is the live mechanism (see the rule's data-allow-white-opacity ancestor walk).
def test_white_text_low_opacity_fires():
    # rgba(255,255,255,0.6) color on a .slide content rule -> warn.
    html = _doc(".slide .cbody { font-size: 24px; "
                "color: rgba(255,255,255,0.6); }",
                _slide("content", '<div class="cbody">正文文字</div>'))
    assert "R-WHITE-TEXT" in _all_codes(R_WHITE_TEXT, html)


def test_white_text_pure_white_no_fire():
    # Pure #fff content text -> clean.
    html = _doc(".slide .cbody { font-size: 24px; color: #fff; }",
                _slide("content", '<div class="cbody">正文文字</div>'))
    assert "R-WHITE-TEXT" not in _all_codes(R_WHITE_TEXT, html)


def test_white_text_chrome_class_no_fire():
    # .footnote is a chrome class -> exempt from the soft-white check.
    html = _doc(".slide .footnote { font-size: 24px; "
                "color: rgba(255,255,255,0.6); }",
                _slide("content", '<div class="footnote">脚注</div>'))
    assert "R-WHITE-TEXT" not in _all_codes(R_WHITE_TEXT, html)


def test_white_text_allow_opacity_exemption_no_fire():
    # data-allow-white-opacity on the element opts the rule out (was a
    # /* allow:white-opacity */ comment under the old source-scan engine).
    html = _doc(".slide .cbody { font-size: 24px; "
                "color: rgba(255,255,255,0.6); }",
                _slide("content",
                       '<div class="cbody" data-allow-white-opacity>正文</div>'))
    assert "R-WHITE-TEXT" not in _all_codes(R_WHITE_TEXT, html)


def test_white_text_framework_css_skipped():
    # Audit polices AUTHOR CSS only; a framework block is skipped.
    html = ('<html><head><style data-source="framework">'
            '.slide .cbody { font-size: 24px; color: rgba(255,255,255,0.6); }'
            '</style></head><body>'
            + _slide("content", '<div class="cbody">正文文字</div>')
            + '</body></html>')
    assert "R-WHITE-TEXT" not in _all_codes(R_WHITE_TEXT, html)


# ==========================================================================
# R-ECHO  audit_list_echo
# ==========================================================================

def test_echo_summary_fires():
    # 5 column titles + a <p> footer that re-lists 4 of them (>=3 distinct
    # 2-4 char CJK prefixes) -> R-ECHO warn. Layout is content (not skipped).
    body = (
        '<div class="col"><span>研发提效</span></div>'
        '<div class="col"><span>生产保质</span></div>'
        '<div class="col"><span>营销升级</span></div>'
        '<div class="col"><span>供应链强化</span></div>'
        '<div class="col"><span>高效工作</span></div>'
        '<p class="footnote">已落地四十二场景,覆盖研发、生产、营销、供应链关键域</p>'
    )
    slides = [_slide("content-5up", body)]
    assert "R-ECHO" in _all_codes(R_ECHO, slides)


_ECHO_FIRING_BODY = (
    '<div class="col"><span>研发提效</span></div>'
    '<div class="col"><span>生产保质</span></div>'
    '<div class="col"><span>营销升级</span></div>'
    '<div class="col"><span>供应链强化</span></div>'
    '<div class="col"><span>高效工作</span></div>'
)


def test_echo_intentional_optout_on_target_skips():
    # Same echoing footer as test_echo_summary_fires, but the leaf carries class
    # `echo-intentional` → the deliberate-recap opt-out skips it (a closing line
    # that names earlier items on PURPOSE is rhetoric, not lazy redundancy).
    # (2026-06-04: contract was documented in the rule comment but never wired up.)
    body = _ECHO_FIRING_BODY + (
        '<p class="footnote echo-intentional">已落地四十二场景,覆盖研发、生产、营销、供应链关键域</p>'
    )
    slides = [_slide("content-5up", body)]
    assert "R-ECHO" not in _all_codes(R_ECHO, slides)


def test_echo_intentional_optout_on_ancestor_skips():
    # The opt-out is also honored on an ANCESTOR (the documented "parent 链含"
    # form): wrapping the recap in an echo-intentional container skips it.
    body = _ECHO_FIRING_BODY + (
        '<div class="echo-intentional">'
        '<p class="footnote">已落地四十二场景,覆盖研发、生产、营销、供应链关键域</p></div>'
    )
    slides = [_slide("content-5up", body)]
    assert "R-ECHO" not in _all_codes(R_ECHO, slides)


def test_echo_no_summary_no_fire():
    # Footer text shares no sibling prefixes -> no echo.
    body = (
        '<div class="col"><span>研发提效</span></div>'
        '<div class="col"><span>生产保质</span></div>'
        '<div class="col"><span>营销升级</span></div>'
        '<div class="col"><span>供应链强化</span></div>'
        '<p class="footnote">今年累计交付一千二百个独立可复用的能力单元</p>'
    )
    slides = [_slide("content-5up", body)]
    assert "R-ECHO" not in _all_codes(R_ECHO, slides)


def test_echo_agenda_layout_skipped():
    # Same echoing footer, but on an agenda layout where echo is by design.
    body = (
        '<div class="col"><span>研发提效</span></div>'
        '<div class="col"><span>生产保质</span></div>'
        '<div class="col"><span>营销升级</span></div>'
        '<div class="col"><span>供应链强化</span></div>'
        '<div class="col"><span>高效工作</span></div>'
        '<p class="footnote">已落地四十二场景,覆盖研发、生产、营销、供应链关键域</p>'
    )
    slides = [_slide("agenda", body)]
    assert "R-ECHO" not in _all_codes(R_ECHO, slides)


# ==========================================================================
# R-DOM  audit_dom_integrity
# ==========================================================================

def test_dom_clean_no_fire():
    html = ('<html><body><div class="deck">'
            '<div class="slide-frame"><div class="slide">a</div></div>'
            '<div class="slide-frame"><div class="slide">b</div></div>'
            '</div></body></html>')
    assert "R-DOM" not in _err_codes(R_DOM, html)


def test_dom_orphan_frame_fires():
    # slide-frame not a direct child of .deck (wrapped in a plain div).
    html = ('<html><body><div class="deck">'
            '<div class="wrap">'
            '<div class="slide-frame"><div class="slide">a</div></div>'
            '</div></div></body></html>')
    assert "R-DOM" in _err_codes(R_DOM, html)


def test_dom_two_slides_in_frame_fires():
    # A frame containing two .slide direct children (expected exactly 1).
    html = ('<html><body><div class="deck">'
            '<div class="slide-frame">'
            '<div class="slide">a</div><div class="slide">b</div>'
            '</div></div></body></html>')
    assert "R-DOM" in _err_codes(R_DOM, html)


def test_dom_one_lazy_template_payload_is_valid():
    html = ('<html><body><div class="deck" data-lazy-frames>'
            '<div class="slide-frame" data-fs-lazy-frame>'
            '<template data-fs-lazy-slide><div class="slide">a</div></template>'
            '</div></div></body></html>')
    assert "R-DOM" not in _err_codes(R_DOM, html)


def test_dom_unbalanced_divs_fires():
    # A missing </div> (deck never closed) -> div open/close imbalance.
    # MORE-CORRECT divergence (step 4b): the div open/close-BALANCE invariant was
    # the one R-DOM check that needs RAW source bytes (the browser auto-closes
    # tags, so the rendered DOM is always balanced). Per UNIFY-VALIDATE-ARCH it is
    # attributed to the runner byte-level rule R-DOC-INTEGRITY, NOT R-DOM (whose
    # two DOM-structure invariants — orphan/nested frame, >1 .slide per frame —
    # stay in the engine). So a truncated deck now fires R-DOC-INTEGRITY.
    html = ('<html><body><div class="deck">'
            '<div class="slide-frame"><div class="slide">a</div></div>'
            '</body></html>')
    assert "R-DOC-INTEGRITY" in _err_codes("R-DOC-INTEGRITY", html)
    assert "R-DOM" not in _err_codes(R_DOM, html)


def test_dom_allow_optout_no_fire():
    # <!-- allow:dom-integrity --> suppresses the whole audit even when the
    # markup is structurally broken (orphan frame + imbalance).
    html = ('<html><body><!-- allow:dom-integrity -->'
            '<div class="deck"><div class="wrap">'
            '<div class="slide-frame"><div class="slide">a</div></div>'
            '</body></html>')
    assert "R-DOM" not in _err_codes(R_DOM, html)


# ==========================================================================
# F-358  mockup sandbox  (a data-mockup / role="img" subtree is a PICTURE of a
#         product UI, not page content -> its internals are exempt from R20
#         typescale, R-WHITE-TEXT, and R12 drop-shadow)
# ==========================================================================

def test_r20_mockup_sandbox_no_fire():
    # Off-ladder per-page font fires normally...
    fires = _doc('[data-slide-key="k"] .lbl { font-size: 14px; }',
                 _slide("content", '<div class="lbl">x</div>'))
    assert "R20" in _all_codes(R20, fires)
    # ...but is exempt when the selector targets only data-mockup internals.
    exempt = _doc('[data-slide-key="k"] .lbl { font-size: 14px; }',
                  _slide("content",
                         '<div class="phone" data-mockup>'
                         '<div class="lbl">x</div></div>'))
    assert "R20" not in _all_codes(R20, exempt)


def test_r12_mockup_sandbox_no_fire():
    # A real drop shadow inside a data-mockup subtree is simulated UI chrome.
    html = _doc(".slide .btn { box-shadow: 0 8px 24px rgba(0,0,0,0.4); }",
                _slide("content",
                       '<div class="phone" data-mockup>'
                       '<div class="btn">x</div></div>'))
    assert "R12" not in _all_codes(R12, html)


def test_white_text_mockup_data_attr_no_fire():
    # Soft-white inside a data-mockup subtree is simulated-UI grey text -> exempt.
    html = _doc(".slide .cbody { font-size: 24px; color: rgba(255,255,255,0.6); }",
                _slide("content",
                       '<div class="phone" data-mockup>'
                       '<div class="cbody">正文</div></div>'))
    assert "R-WHITE-TEXT" not in _all_codes(R_WHITE_TEXT, html)


def test_white_text_role_img_mockup_no_fire():
    # A role="img" subtree is a graphic (a picture of a UI) -> its grey text exempt.
    html = _doc(".slide .cbody { font-size: 24px; color: rgba(255,255,255,0.6); }",
                _slide("content",
                       '<div class="phone" role="img">'
                       '<div class="cbody">正文</div></div>'))
    assert "R-WHITE-TEXT" not in _all_codes(R_WHITE_TEXT, html)


if __name__ == "__main__":
    # Allow running without pytest: python3 test_validate_static_rules.py
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
