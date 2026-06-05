"""R-VIS-TITLE-GAP · 正文顶到/重叠标题 (2026-05-31, P3).

R-VIS-TITLE-POSITION only checks the header's ABSOLUTE top (~61). Content that
grew/overflowed UP toward the title (cross-container: title in .header, content
in .stage) was unowned. This measures header-bottom → topmost content top.
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
ASSETS = HERE.parents[2] / "assets"
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402
VALIDATE = ASSETS / "validate.py"
DOC = HERE.parents[2] / "references" / "validator-rules.md"


def test_title_gap_wired():
    assert E.rule_in_engine("R-VIS-TITLE-GAP")
    assert "R-VIS-TITLE-GAP" in DOC.read_text(encoding="utf-8"), "R-VIS-TITLE-GAP not documented"


def _run(html):
    E.skip_if_no_engine()
    return E.findings_for("R-VIS-TITLE-GAP", html)


def _slide(stage_top):
    return ('<div class="slide" style="position:relative;width:1920px;height:1080px">'
            '<div class="header" style="position:absolute;top:61px;left:73px;height:53px">'
            '<h2 class="title-zh" style="font-size:44px;margin:0">标题在这里</h2></div>'
            f'<div class="stage" style="position:absolute;top:{stage_top}px;left:73px;right:73px;bottom:60px">'
            '<div class="card" style="border:1px solid #888;height:200px;font-size:24px">内容块</div>'
            '</div></div>')


def test_title_gap_fires_when_content_crowds_title():
    hits = _run(_slide(120))   # content top ~120, header bottom ~114 → gap ~6 < 24
    assert len(hits) >= 1, f"content 6px below title not flagged: {hits}"


def test_title_gap_quiet_with_normal_spacing():
    hits = _run(_slide(300))   # content top 300, gap ~186 → fine
    assert hits == [], f"false positive on normal title spacing: {hits}"


# --- name-free fallback (header-less raw slides) regression guards (2026-06-04) ---
def _raw_slide(inner, attrs=""):
    # No .header → exercises the name-free title-band fallback branch.
    return ('<div class="slide" data-layout="raw" data-slide-key="t" ' + attrs
            + ' style="position:relative;width:1920px;height:1080px">'
            + inner + '</div>')


_RAW_TITLE = '<div style="font-size:44px;margin:0">页面主标题</div>'
# A TALL content block hugging the title = real crowding (NOT a subtitle).
_RAW_CROWD = ('<div style="margin-top:6px;width:600px;height:200px;'
              'font-size:24px">正文区块顶到标题</div>')


def test_title_gap_quiet_with_raw_title_subtitle():
    # FALSE-POSITIVE GUARD: a bespoke header-less raw slide whose title is
    # immediately followed by its OWN subtitle (smaller font, single line, ~8px
    # below) must NOT fire — the subtitle is folded into the title band, not
    # treated as content crowding the title. (P4/P5/P7/P8 recurring false hits.)
    inner = (_RAW_TITLE
             + '<div style="font-size:20px;margin-top:8px">这是紧邻标题的副标题一行</div>'
             + '<div style="margin-top:220px;width:600px;height:200px;'
               'font-size:24px">正文内容区块</div>')
    hits = _run(_raw_slide(inner))
    assert hits == [], f"false positive: folded title+subtitle band fired: {hits}"


def test_title_gap_still_fires_on_raw_crowd_without_subtitle():
    # OVER-SUPPRESSION GUARD: a tall block hugging the title (no subtitle) is real
    # crowding and must still fire after the subtitle-folding fix.
    hits = _run(_raw_slide(_RAW_TITLE + _RAW_CROWD))
    assert len(hits) >= 1, f"real raw crowd (no subtitle) should still fire: {hits}"


def test_title_gap_opt_out_silences():
    # The data-allow-title-gap escape hatch silences the rule even on real crowding.
    hits = _run(_raw_slide(_RAW_TITLE + _RAW_CROWD, attrs="data-allow-title-gap"))
    assert hits == [], f"data-allow-title-gap should silence the rule: {hits}"


def test_title_gap_quiet_on_decorative_label_with_graphic():
    # SLIDE-4 CLASS: header-less raw slide whose topmost >=24px text is a DECORATIVE
    # label (an evo-arrow annotation, --fs-sub=28px) immediately followed by its
    # sibling <svg> graphic ~8px below. The label is not a page title and the graphic
    # is not body crowding it → must NOT fire. (The real page title is rendered as
    # chrome, outside the stage.) Crowding content must be TEXT, not a sibling graphic.
    inner = (
        '<div style="display:flex;flex-direction:column;gap:8px">'
        '<span style="font-size:28px">AI 在工作流中的位置不断前移</span>'
        '<svg viewBox="0 0 1180 24" style="width:600px;height:22px">'
        '<line x1="8" y1="12" x2="1150" y2="12" stroke="#3C7FFF" stroke-width="4"/></svg>'
        '</div>'
        '<div style="margin-top:60px;width:600px;height:200px;font-size:24px">真正的内容区块</div>'
    )
    hits = _run(_raw_slide(inner))
    assert hits == [], f"decorative label+graphic must not fire title-gap: {hits}"


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
