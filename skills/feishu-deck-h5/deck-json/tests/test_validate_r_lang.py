"""R-LANG (audit_language_policy) tests — focused on the F-12 false-positive
fix: chart axis poles / legend keys / scale caps / data-coded sublabels sit
beside CJK by design and must NOT be flagged as EN translation tracks, while
genuine translation pairs (and the -en class / chrome-label paths) still fire.

Fast: imports validate.py directly, calls the public audit_language_policy
entry (which wires the real _is_offending_latin), no render / no Playwright.
Note: the sibling-pair detector only flags ALL-CAPS Latin (is_offending_latin
requires latin_uc_re), so must-fire fixtures use uppercase Latin.
"""
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
import validate as V  # noqa: E402


def _codes(slides):
    """Run R-LANG over the given slide fragments (zh-only mode, no meta)."""
    html = "<html><head></head><body>" + "".join(slides) + "</body></html>"
    iss = V.Issues()
    V.audit_language_policy(html, slides, iss)
    return [c for c, _ in iss.warnings]


def _slide(layout, body):
    return (f'<div class="slide" data-layout="{layout}" '
            f'data-slide-key="k">{body}</div>')


# ---- must-fire: real translation tracks still caught ----------------
def test_sibling_pair_uppercase_latin_fires():
    # CJK + all-caps Latin sibling inside a semantic .card → translation track
    slides = [_slide("content-3up",
        '<div class="card"><div class="t">审批聚合</div>'
        '<div class="n">APPROVAL AGGREGATE</div></div>')]
    assert "R-LANG" in _codes(slides)


def test_en_class_still_fires():
    # the .title-en class path is independent of the sibling-pair fix
    slides = [_slide("cover",
        '<h1 class="title">标题</h1><h1 class="title-en">TITLE</h1>')]
    assert "R-LANG" in _codes(slides)


def test_chrome_label_still_fires():
    # the chrome-label scan (eyebrow/kicker/...) is independent too
    slides = [_slide("content-3up", '<span class="eyebrow">DEADLINE</span>'
                                     '<div class="b">说明文字</div>')]
    assert "R-LANG" in _codes(slides)


# ---- must-not-fire: F-12 scaffolding / data-label skips -------------
def test_skip_y_axis_poles():
    slides = [_slide("matrix-2x2",
        '<div class="y-axis"><span class="label">HIGH</span>'
        '<span class="name">业务影响</span></div>')]
    assert "R-LANG" not in _codes(slides)


def test_skip_x_axis_poles():
    slides = [_slide("matrix-2x2",
        '<div class="x-axis"><span class="label">LOW</span>'
        '<span class="name">实施难度</span></div>')]
    assert "R-LANG" not in _codes(slides)


def test_skip_legend_keys():
    slides = [_slide("stats",
        '<div class="legend"><span class="key">HIGH</span>'
        '<span class="key">中等</span></div>')]
    assert "R-LANG" not in _codes(slides)


def test_skip_sublabel_quarter_baseline():
    # leaf class "sublabel" AND date-coded text — both filters cover it
    slides = [_slide("stats",
        '<div class="bar is-base"><div class="sublabel">2025 Q4 BASELINE</div>'
        '<div class="data">基准值</div></div>')]
    assert "R-LANG" not in _codes(slides)


def test_skip_sublabel_actual():
    slides = [_slide("stats",
        '<div class="bar is-end"><div class="sublabel">2026 Q1 ACTUAL</div>'
        '<div class="data">实际值</div></div>')]
    assert "R-LANG" not in _codes(slides)


def test_skip_ancestor_axis_wrapper():
    # parent class carries an axis token even when nested
    slides = [_slide("matrix-2x2",
        '<div class="y-axis-cap"><span class="label">VERY HIGH</span>'
        '<span class="name">非常重要</span></div>')]
    assert "R-LANG" not in _codes(slides)


# ---- integration: the bundled example must be R-LANG-clean ----------
def test_bundled_layout_proposal_has_no_r_lang():
    example = ASSETS.parent / "examples" / "_layout-proposal.html"
    if not example.is_file():
        return  # example not present in this checkout — skip
    html = example.read_text(encoding="utf-8")
    slides = V.extract_slides(html)
    iss = V.Issues()
    V.audit_language_policy(html, slides, iss)
    rlang = [m for c, m in iss.warnings if c == "R-LANG"]
    assert rlang == [], f"unexpected R-LANG on bundled example: {rlang}"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
