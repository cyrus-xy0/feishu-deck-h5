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
  (f) R-VIS-BODY-FLOOR honors the STATIC chrome vocab (2026-06-11 alignment):
      .ui-* mockup primitives (element or ancestor) and static chrome tokens
      (.kicker etc.) are exempt in the VISUAL floor too; plain small body text
      still fires.
  (g) R-VIS-SHORT-LABEL-FLOOR: same vocab alignment (.ui-* self/ancestor exempt).
  (h) R-VIS-CROWD: absolutely-positioned corner labels are not "flow content
      jammed at the bottom" (flowOnly content union — kills the decor-thumbnail
      false positive), and data-allow-imbalance now works on the BOX itself
      (closest chain), not only on .slide. Real flow crowding still fires.

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


# ==========================================================================
# (f) 静态↔视觉 chrome 词表对齐(2026-06-11)— R-VIS-BODY-FLOOR
#     .ui-* mockup primitive(元素或祖先)与静态 chrome token(.kicker 等)
#     在视觉地板同样豁免;裸正文照常 fire。
# ==========================================================================

_LONG16 = '<span style="font-size:16px">这是一段超过八个字的正文文字内容</span>'


def test_body_floor_fires_on_plain_small_text():
    # CONTROL: 16px ≥8 字裸正文(无 chrome/mock 类)必须照常 fire。
    hits = _run("R-VIS-BODY-FLOOR", [_frame("content", f"<div>{_LONG16}</div>")])
    assert len(hits) >= 1, f"plain 16px body text must still fire: {hits}"


def test_body_floor_ui_mock_ancestor_exempt():
    # .ui-row 祖先 = rung-8 mockup primitive(静态 \.ui-[a-z][\w-]* 臂)→ 内部
    # 小字是 mock-internal,不报。修复前只认 VIS_TIER_MOCK 枚举的 10 个 ui-* 类。
    hits = _run("R-VIS-BODY-FLOOR",
                [_frame("content", f'<div class="ui-row">{_LONG16}</div>')])
    assert hits == [], f".ui-* ancestor must exempt body-floor: {hits}"


def test_body_floor_static_chrome_class_exempt():
    # .kicker 在静态 _CHROME_CLASS_RE 里,视觉层必须同样豁免(对齐前会误报)。
    body = ('<span class="kicker" style="font-size:16px">'
            '这是一段超过八个字的正文文字内容</span>')
    hits = _run("R-VIS-BODY-FLOOR", [_frame("content", body)])
    assert hits == [], f"static chrome class (.kicker) must exempt body-floor: {hits}"


# ==========================================================================
# (g) 同一词表对齐 — R-VIS-SHORT-LABEL-FLOOR(.ui-* 自身或祖先豁免)
# ==========================================================================

def test_short_label_floor_fires_on_plain_short_label():
    # CONTROL: 裸 16px 短标签照常 fire。
    hits = _run("R-VIS-SHORT-LABEL-FLOOR",
                [_frame("content", '<span style="font-size:16px">SG</span>')])
    assert len(hits) >= 1, f"plain 16px short label must still fire: {hits}"


def test_short_label_floor_ui_mock_exempt():
    # mock 表格行(.ui-row)里的 16px 单元格短标签 = mockup-internal,不报。
    body = '<div class="ui-row"><span style="font-size:16px">SG</span></div>'
    hits = _run("R-VIS-SHORT-LABEL-FLOOR", [_frame("content", body)])
    assert hits == [], f"short label inside .ui-* must be exempt: {hits}"


# ==========================================================================
# (h) R-VIS-CROWD 误报修复(2026-06-11)— flowOnly 内容范围 + 框级 opt-out
# ==========================================================================

def test_crowd_skips_absolute_corner_label_only_box():
    # decor 缩略图:唯一文本是绝对定位的右下角标(".pptx" 这类)→ 刻意摆放,
    # 不是流式内容被挤;flowOnly 后 contentUnion 为空 → 整盒跳过,不报。
    body = ('<div style="position:relative;width:600px;height:220px;'
            'background:#101826;border:1px solid #888">'
            '<span style="position:absolute;right:8px;bottom:6px;'
            'font-size:16px">.pptx</span></div>')
    hits = _run("R-VIS-CROWD", [_frame("content", body)])
    assert hits == [], f"absolute-corner-label-only box must not fire CROWD: {hits}"


def test_crowd_still_fires_on_flow_text_at_bottom():
    # CONTROL: 真·流式正文贴底(顶部大片空)必须照常 fire。
    body = ('<div style="width:600px;height:220px;background:#101826;'
            'display:flex;flex-direction:column;justify-content:flex-end">'
            '<p style="font-size:24px;margin:0">真实流式正文内容贴在框底</p></div>')
    hits = _run("R-VIS-CROWD", [_frame("content", body)])
    assert len(hits) >= 1, f"flow text jammed at bottom must still fire CROWD: {hits}"


def test_crowd_box_level_allow_imbalance_suppresses():
    # 修复前 data-allow-imbalance 只认 .slide 级 — 加在框上静默无效;现在框级
    # (closest 链)同样生效。
    body = ('<div data-allow-imbalance style="width:600px;height:220px;'
            'background:#101826;display:flex;flex-direction:column;'
            'justify-content:flex-end">'
            '<p style="font-size:24px;margin:0">真实流式正文内容贴在框底</p></div>')
    hits = _run("R-VIS-CROWD", [_frame("content", body)])
    assert hits == [], f"data-allow-imbalance on the BOX must suppress CROWD: {hits}"


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
