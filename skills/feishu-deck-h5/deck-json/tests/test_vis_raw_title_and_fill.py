"""R-VIS-RAW-TITLE-POS + R-VIS-FILL — raw-page blind-spot rules (2026-06-04).

These two close the gaps that let the 世界坚果协会 deck's first pass through
clean: raw pages bypass the framework `.header`, so R-VIS-TITLE-POSITION had no
header to measure (titles could sit anywhere), and `justify-content:center` hid
sparse content symmetrically so balance/canvas-center saw nothing. Both are
deterministic geometric checks (no LLM, no agents), raw-only, with a
data-allow-imbalance opt-out.
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402


def _slide(layout, inner, attrs=""):
    return (f'<div class="slide" data-layout="{layout}" data-slide-key="t" {attrs} '
            'style="position:relative;width:1920px;height:1080px">' + inner + '</div>')


def _stage(stage_top, body):
    return (f'<div class="raw-stage rs" style="position:absolute;top:{stage_top}px;'
            'left:80px;right:80px;bottom:80px;display:flex;flex-direction:column;'
            'gap:20px;justify-content:flex-start">' + body + '</div>')


_TITLE = '<h2 style="font-size:42px;margin:0">页面标题在这里写一行</h2>'
# A tall framed card that fills the stage (border = framed; text top-aligned inside).
_FILL_BODY = ('<div style="border:1px solid #888;height:840px;font-size:24px">'
              '卡片内容,文字贴顶但卡片撑满高度</div>')


def _run(rule, html):
    E.skip_if_no_engine()
    return E.findings_for(rule, html)


# ---- R-VIS-RAW-TITLE-POS ----
def test_raw_title_wired():
    assert E.rule_in_engine("R-VIS-RAW-TITLE-POS")


def test_raw_title_fires_when_title_too_low():
    # stage starts at 240 → de-facto title renders ~240px, far below the 61 baseline.
    hits = _run("R-VIS-RAW-TITLE-POS", _slide("raw", _stage(240, _TITLE + _FILL_BODY)))
    assert len(hits) >= 1, f"low raw title not flagged: {hits}"


def test_raw_title_quiet_at_baseline():
    # stage at 56 → title ~56px, within the baseline band.
    hits = _run("R-VIS-RAW-TITLE-POS", _slide("raw", _stage(56, _TITLE + _FILL_BODY)))
    assert hits == [], f"baseline raw title false-positived: {hits}"


def test_raw_title_skips_schema_layout():
    # schema layouts have framework headers → R-VIS-TITLE-POSITION owns them, not this.
    hits = _run("R-VIS-RAW-TITLE-POS", _slide("content", _stage(240, _TITLE)))
    assert hits == [], f"should skip non-raw layout: {hits}"


def test_raw_title_optout_silences():
    hits = _run("R-VIS-RAW-TITLE-POS",
                _slide("raw", _stage(240, _TITLE + _FILL_BODY), attrs="data-allow-imbalance"))
    assert hits == [], f"data-allow-imbalance should silence: {hits}"


# ---- R-VIS-FILL ----
def test_fill_wired():
    assert E.rule_in_engine("R-VIS-FILL")


def test_fill_fires_on_sparse_raw_page():
    # title + one short line at the top, the rest of the stage is void → low fill.
    body = _TITLE + '<p style="font-size:24px;margin:0">只有一行小内容,下面全是空。</p>'
    hits = _run("R-VIS-FILL", _slide("raw", _stage(56, body)))
    assert len(hits) >= 1, f"sparse raw page not flagged as empty: {hits}"


def test_fill_quiet_when_framed_card_fills():
    # a full-height framed card fills the stage → not empty (even if its text tops).
    hits = _run("R-VIS-FILL", _slide("raw", _stage(56, _TITLE + _FILL_BODY)))
    assert hits == [], f"full framed card false-positived as empty: {hits}"


def test_fill_skips_schema_layout():
    body = _TITLE + '<p style="font-size:24px;margin:0">只有一行。</p>'
    hits = _run("R-VIS-FILL", _slide("content", _stage(56, body)))
    assert hits == [], f"should skip non-raw layout: {hits}"


def test_fill_optout_silences():
    body = _TITLE + '<p style="font-size:24px;margin:0">只有一行。</p>'
    hits = _run("R-VIS-FILL", _slide("raw", _stage(56, body), attrs="data-allow-imbalance"))
    assert hits == [], f"data-allow-imbalance should silence: {hits}"


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


# ---- R-VIS-RAW-TITLE-STACK (two-layer title on bespoke raw — R56 blind-spot) ----
_STACK_TITLE = ('<h2 style="font-size:48px;margin:0;color:#fff">'
                '<span style="display:block;font-size:16px;color:#3C7FFF">变化 01 · NEW REFLEX</span>'
                '这是手写的双层标题占一行</h2>')
_FLAT_TITLE = ('<h2 style="font-size:48px;margin:0;color:#fff">'
               '<span style="font-size:48px;color:#888">变化 02 · </span>这是单行标题没有叠层</h2>')


def test_raw_title_stack_wired():
    assert E.rule_in_engine("R-VIS-RAW-TITLE-STACK")


def test_raw_title_stack_fires_on_folded_kicker():
    # 48px title with a 16px block kicker folded inside → the exact two-layer bug
    # R56 silently skips on bespoke raw.
    hits = _run("R-VIS-RAW-TITLE-STACK", _slide("raw", _stage(56, _STACK_TITLE + _FILL_BODY)))
    assert len(hits) >= 1, f"folded two-layer title not flagged: {hits}"


def test_raw_title_stack_quiet_on_single_line():
    # same-size prefix span (变化 02 · at 48px) = single-line title → no fire.
    hits = _run("R-VIS-RAW-TITLE-STACK", _slide("raw", _stage(56, _FLAT_TITLE + _FILL_BODY)))
    assert hits == [], f"single-line title false-positived: {hits}"


def test_raw_title_stack_skips_schema_layout():
    hits = _run("R-VIS-RAW-TITLE-STACK", _slide("content", _stage(56, _STACK_TITLE)))
    assert hits == [], f"should skip non-raw layout: {hits}"


def test_raw_title_stack_opt_out():
    hits = _run("R-VIS-RAW-TITLE-STACK",
                _slide("raw", _stage(56, _STACK_TITLE + _FILL_BODY), attrs='data-allow-title-stack'))
    assert hits == [], f"data-allow-title-stack should suppress: {hits}"
