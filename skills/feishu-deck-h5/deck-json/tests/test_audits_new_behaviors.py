"""Lock-in fixtures for the audits.js behaviors changed in the 2026-06 engine
batch (UNIFY-VALIDATE-ARCH follow-up). Each test pins ONE behavior so a future
rule edit that regresses it is caught.

Behaviors locked here (all evaluated against the RENDERED DOM via the unified
engine — engine_helpers runs the SAME run_unified_engine that validate.py /
render-deck use; requires Chromium, skips gracefully if unavailable):

  (a) R07 is EXEMPT for canvas slides (data-layout="canvas") that ship no
      .wordmark — 941f781 dropped the canvas template's wordmark, so without the
      carve-out every PPTX-import/canvas deck fires R07 on every frame. A NORMAL
      slide (data-layout="content") with no .wordmark still fires.
  (b) inline style="color:rgba(255,255,255,.7)" fires R-WHITE-TEXT (the inline
      second-pass that was lost in migration), and data-allow-white-opacity on
      the element (or an ancestor) suppresses it.
  (c) /* allow:drop-shadow */ inside a slide's <style> rule block suppresses R12
      (the CSS-comment opt-out restored to parity with the data-attribute form).
  (d) data-decor on a DESCENDANT (not just the .slide root) is validated by R38
      (parity restore: a typo'd token on a stage/decor child used to slip).
  (e) R-VIS-TITLE-GAP still fires on REAL body crowding below a FOLDED subtitle
      (the M2 fix: the subtitle is folded into the title band, but a tall body
      block hugging the subtitle band bottom is still real crowding).

These exercise the engine through the public engine_helpers surface; the exact
HTML/CSS shapes were read from the live rules, not assumed.
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402


def _frame(layout, body, *, attrs="", key="k"):
    """One slide-frame chunk with the required structural attributes."""
    return (
        f'<div class="slide-frame"><div class="slide" data-layout="{layout}" '
        f'data-screen-label="x" data-slide-key="{key}" {attrs}>{body}</div></div>'
    )


def _run(rule, html_or_slides):
    E.skip_if_no_engine()
    return E.findings_for(rule, html_or_slides)


# ==========================================================================
# (a) R07 canvas exemption — canvas without .wordmark is OK, content is not
# ==========================================================================

def test_r07_canvas_slide_without_wordmark_no_fire():
    # data-layout="canvas" + no .wordmark → exempt (941f781 dropped the canvas
    # template wordmark). Must NOT fire R07.
    hits = _run("R07", [_frame("canvas", "<p>纯净画布内容</p>")])
    assert hits == [], f"canvas slide without wordmark must NOT fire R07: {hits}"


def test_r07_normal_slide_without_wordmark_still_fires():
    # The SAME body on a normal content layout (no canvas exemption) → R07 fires.
    hits = _run("R07", [_frame("content", "<p>纯净内容</p>")])
    assert len(hits) >= 1, f"content slide without wordmark must still fire R07: {hits}"


# ==========================================================================
# (b) R-WHITE-TEXT inline soft-white + data-allow-white-opacity suppression
# ==========================================================================

def test_white_text_inline_soft_white_fires():
    # inline style="color:rgba(255,255,255,.7)" on body-sized text → R-WHITE-TEXT.
    body = ('<div class="wordmark"></div>'
            '<div style="font-size:24px;color:rgba(255,255,255,.7)">正文文字</div>')
    hits = _run("R-WHITE-TEXT", [_frame("content", body)])
    assert len(hits) >= 1, f"inline soft-white must fire R-WHITE-TEXT: {hits}"


def test_white_text_inline_data_allow_suppresses():
    # data-allow-white-opacity on the element itself opts the inline soft-white out.
    body = ('<div class="wordmark"></div>'
            '<div data-allow-white-opacity '
            'style="font-size:24px;color:rgba(255,255,255,.7)">正文文字</div>')
    hits = _run("R-WHITE-TEXT", [_frame("content", body)])
    assert hits == [], f"data-allow-white-opacity must suppress inline soft-white: {hits}"


def test_white_text_inline_data_allow_on_ancestor_suppresses():
    # The opt-out is honored on an ANCESTOR (the rule walks the parent chain).
    body = ('<div class="wordmark"></div>'
            '<div data-allow-white-opacity>'
            '<div style="font-size:24px;color:rgba(255,255,255,.7)">正文文字</div></div>')
    hits = _run("R-WHITE-TEXT", [_frame("content", body)])
    assert hits == [], f"ancestor data-allow-white-opacity must suppress: {hits}"


# ==========================================================================
# (c) R12 /* allow:drop-shadow */ CSS-comment opt-out
# ==========================================================================

def _drop_shadow_frame(rule_block):
    return (
        '<div class="slide-frame"><div class="slide" data-layout="content" '
        'data-screen-label="x" data-slide-key="k">'
        '<div class="wordmark"></div>'
        '<style>' + rule_block + '</style>'
        '<div class="uiwin">x</div>'
        '</div></div>'
    )


def test_r12_allow_drop_shadow_comment_suppresses():
    # /* allow:drop-shadow */ inside the slide's <style> rule block opts R12 out.
    html = _drop_shadow_frame(
        '.slide .uiwin { box-shadow: 0 8px 24px rgba(0,0,0,0.4); '
        '/* allow:drop-shadow */ }')
    hits = _run("R12", html)
    assert hits == [], f"/* allow:drop-shadow */ must suppress R12: {hits}"


def test_r12_real_drop_shadow_without_comment_fires():
    # Same rule WITHOUT the comment → real drop shadow → R12 fires.
    html = _drop_shadow_frame(
        '.slide .uiwin { box-shadow: 0 8px 24px rgba(0,0,0,0.4); }')
    hits = _run("R12", html)
    assert len(hits) >= 1, f"real drop shadow (no opt-out) must fire R12: {hits}"


# ==========================================================================
# (d) R38 data-decor on a DESCENDANT is validated
# ==========================================================================

def test_r38_descendant_data_decor_validated():
    # A bad data-decor token on a stage/decor CHILD (not the .slide root) must be
    # caught — parity restore (was only reading the .slide root attribute).
    body = '<div class="wordmark"></div><div data-decor="bogus-token">装饰</div>'
    hits = _run("R38", [_frame("content", body)])
    assert len(hits) >= 1, f"bad data-decor on a descendant must fire R38: {hits}"
    assert any(f.get("token") == "bogus-token" for f in hits), \
        f"R38 finding must carry the offending token: {hits}"


def test_r38_descendant_valid_token_no_fire():
    # A SHIP-LIST token on a descendant must NOT fire (guards over-firing).
    body = '<div class="wordmark"></div><div data-decor="aurora">装饰</div>'
    hits = _run("R38", [_frame("content", body)])
    assert hits == [], f"valid ship-list data-decor must not fire R38: {hits}"


# ==========================================================================
# (e) R-VIS-TITLE-GAP fires on real crowding BELOW a folded subtitle (M2 fix)
# ==========================================================================

def _raw_slide(inner, attrs=""):
    return ('<div class="slide" data-layout="raw" data-slide-key="t" ' + attrs
            + ' style="position:relative;width:1920px;height:1080px">'
            + inner + '</div>')


_RAW_TITLE = '<div style="font-size:44px;margin:0">页面主标题</div>'
_FOLDED_SUBTITLE = '<div style="font-size:20px;margin-top:8px">紧邻标题的副标题一行</div>'


def test_title_gap_fires_on_body_crowding_below_folded_subtitle():
    # M2: the subtitle (smaller font, ~8px below the title) is FOLDED into the
    # title band — but a tall body block hugging the subtitle band bottom (~6px
    # below it) is REAL crowding and must still fire (the floor is measured from
    # the subtitle band bottom, not the title).
    inner = (_RAW_TITLE + _FOLDED_SUBTITLE
             + '<div style="margin-top:6px;width:600px;height:200px;'
               'font-size:24px">正文区块顶到副标题带</div>')
    hits = _run("R-VIS-TITLE-GAP", _raw_slide(inner))
    assert len(hits) >= 1, \
        f"real body crowding below a folded subtitle must still fire: {hits}"


def test_title_gap_quiet_when_only_folded_subtitle():
    # CONTROL: title + folded subtitle with the body well clear → no fire (the
    # subtitle alone is not crowding). Guards against the M2 fix over-firing.
    inner = (_RAW_TITLE + _FOLDED_SUBTITLE
             + '<div style="margin-top:220px;width:600px;height:200px;'
               'font-size:24px">正文内容区块,离副标题很远</div>')
    hits = _run("R-VIS-TITLE-GAP", _raw_slide(inner))
    assert hits == [], f"folded subtitle alone must not fire title-gap: {hits}"


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
