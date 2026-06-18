"""R-VIS-CARD-OVERFLOW · scroll-viewport + intentional-clip opt-out (F-322).

Lifting Full Knowledge's doc-mockup pages into the strict mingming deck surfaced
two false positives:

  1. A `overflow-y: auto | scroll` element is a SCROLL VIEWPORT — its overflowing
     content is user-scrollable (contained behind a scrollbar), neither clipped-
     and-lost nor visibly spilling. The old `clips` test only matched
     `hidden | clip`, so an auto/scroll box fell through to the (a') visible-spill
     branch and got flagged as "content spills N px past the border" (知识安全页
     `fs-doc-scroll` 1180>732). F-322 skips self-scrolling elements.

  2. A new per-element opt-out `data-allow-clip` (on the element or any ancestor)
     marks INTENTIONAL truncation — e.g. a doc-preview frame that shows only the
     top of a longer document on purpose. Same family as
     data-allow-imbalance / -overlap / -flex-slack.

These two must NOT disable the rule for genuine clipped-and-lost content.

Layer 1 (static) always runs. Layer 2 (Playwright) skips if Chromium absent.
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402


def test_f322_wired_in_engine():
    js = E.audits_js_text()
    assert E.rule_in_engine("R-VIS-CARD-OVERFLOW")
    assert "data-allow-clip" in js, "F-322 data-allow-clip opt-out missing from audits.js"
    assert ("overflowY === 'auto'" in js or "overflowY === \"auto\"" in js), \
        "F-322 auto/scroll self-viewport skip missing from audits.js"


def _findings(html):
    E.skip_if_no_engine()
    return E.findings_for("R-VIS-CARD-OVERFLOW", html)


# overflow-y:auto box, content (400) taller than box (200) → SCROLLS (contained).
_SCROLL = ('<div class="slide"><div class="stage">'
           '<div class="card" style="height:200px;width:320px;border:1px solid #888;'
           'overflow-y:auto">'
           '<div style="height:400px">长内容靠滚动条容纳,不是缺陷,不该报。</div>'
           '</div></div></div>')
# overflow:hidden box marked data-allow-clip → intentional truncation, skip.
_ALLOWCLIP = ('<div class="slide"><div class="stage">'
              '<div class="card" data-allow-clip style="height:200px;width:320px;'
              'border:1px solid #888;overflow:hidden">'
              '<div style="height:400px">文档预览,故意只露顶部,有意截断,不该报。</div>'
              '</div></div></div>')
# overflow:hidden box, content taller, NO scroll, NO allow-clip → REAL content loss.
_CLIPPED = ('<div class="slide"><div class="stage">'
            '<div class="card" style="height:200px;width:320px;border:1px solid #888;'
            'overflow:hidden">'
            '<div style="height:400px">这段内容被永久裁掉看不到,是真缺陷,必须报。</div>'
            '</div></div></div>')


def test_scroll_viewport_not_flagged():
    f = _findings(_SCROLL)
    if f is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert f == [], f"overflow-y:auto scroll viewport falsely flagged: {f}"


def test_allow_clip_not_flagged():
    f = _findings(_ALLOWCLIP)
    if f is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert f == [], f"data-allow-clip intentional truncation falsely flagged: {f}"


def test_real_clip_still_flagged():
    f = _findings(_CLIPPED)
    if f is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert len(f) >= 1, f"genuine clipped-and-lost content NOT flagged (F-322 over-reached): {f}"
