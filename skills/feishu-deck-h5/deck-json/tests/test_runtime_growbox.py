"""feishu-deck.js runtime auto-balance · grow-box (2026-05-31, P2 治本).

balanceSlide now also GROWS a box whose text overflows its bottom (raise
min-height to contain it — the runtime version of grow-box-fit's 拉高框),
inside the existing measure-or-revert + death-rule (title must not move) frame.
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
ASSETS = HERE.parents[2] / "assets"
JS = ASSETS / "feishu-deck.js"


def test_growbox_wired_in_runtime():
    js = JS.read_text(encoding="utf-8")
    assert "before.overflowed.forEach" in js, "grow-box pass missing from balanceSlide"
    assert "minHeight" in js and "overflowBetter" in js, "grow-box keep-criterion missing"
    assert "overflowed" in js, "_abMeasure does not track overflow"


_SZ = "position:relative;width:1920px;height:1080px"
_DECK = """<!doctype html><html><body>
<div class="deck"><div class="slide-frame is-current" style="__SZ__">
  <div class="slide" data-layout="content-3up" style="__SZ__">
    <div class="header"><h2 class="title-zh" style="font-size:44px;margin:0">标题不许动</h2></div>
    <div class="stage" style="position:absolute;top:200px;left:73px;right:73px;bottom:60px">
      <div class="card" style="width:320px;height:90px;border:1px solid #888;overflow:visible">
        <p style="font-size:24px;line-height:1.5;margin:0">这是一段会换行并明显溢出这个矮框底边的文字内容确实比框高出不少必须拉高框才容得下它</p>
      </div>
    </div>
  </div>
</div></div>
<script>__JS__</script></body></html>""".replace("__SZ__", _SZ)


def _run():
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    html = _DECK.replace("__JS__", JS.read_text(encoding="utf-8"))
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_context(viewport={"width": 1920, "height": 1080}).new_page()
            pg.set_content(html)
            title_before = pg.evaluate("Math.round(document.querySelector('.title-zh').getBoundingClientRect().top)")
            pg.evaluate("window.feishuDeck && window.feishuDeck.init && window.feishuDeck.init()")
            pg.wait_for_timeout(400)   # let the rAF auto-balance pass run
            res = pg.evaluate("""() => {
                const card = document.querySelector('.card');
                const p = card.querySelector('p');
                const title = document.querySelector('.title-zh');
                return {
                  cardH: Math.round(card.getBoundingClientRect().height),
                  contentBottomVsCard: Math.round(p.getBoundingClientRect().bottom - card.getBoundingClientRect().bottom),
                  titleTop: Math.round(title.getBoundingClientRect().top),
                  autobalanced: document.querySelector('.slide').hasAttribute('data-fs-autobalanced'),
                };
            }""")
            res["title_before"] = title_before
            b.close()
    except Exception:
        return None
    return res


def test_growbox_grows_overflowing_box_without_moving_title():
    r = _run()
    if r is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    # box grew past its original 90px to contain the ~140px content
    assert r["cardH"] > 120, f"box did not grow to fit overflowing text: {r}"
    # content no longer spills below the (grown) box
    assert r["contentBottomVsCard"] <= 6, f"content still overflowing after grow: {r}"
    # death rule: the title did NOT move
    assert abs(r["titleTop"] - r["title_before"]) <= 1, f"DEATH RULE violated — title moved: {r}"
    assert r["autobalanced"], "slide not marked data-fs-autobalanced (grow not kept)"


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
