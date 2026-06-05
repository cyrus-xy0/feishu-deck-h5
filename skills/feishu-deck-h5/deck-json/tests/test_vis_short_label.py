"""R-VIS-SHORT-LABEL-FLOOR · 1–7 字短标签 / SVG 轴标 < 18px (2026-05-31, P1).

R-VIS-BODY-FLOOR's ≥8-char gate skips short chart axis / category labels. This
补 the gap (incl. SVG <text>, which every other render check skips).
"""
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve()
ASSETS = HERE.parents[2] / "assets"
sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402
VALIDATE = ASSETS / "validate.py"
DOC = HERE.parents[2] / "references" / "validator-rules.md"


def test_short_label_wired():
    js = E.audits_js_text()
    assert E.rule_in_engine("R-VIS-SHORT-LABEL-FLOOR")
    assert "tspan" in js, "SVG text drilling missing from audits.js"
    assert "R-VIS-SHORT-LABEL-FLOOR" in DOC.read_text(encoding="utf-8")


def _run(html):
    E.skip_if_no_engine()
    return E.findings_for("R-VIS-SHORT-LABEL-FLOOR", html)


def _wrap(inner):
    return f'<div class="slide"><div class="stage">{inner}</div></div>'


def test_short_label_fires_on_small_category_label():
    hits = _run(_wrap('<div class="chart"><span class="cat" style="font-size:14px">营收</span></div>'))
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert any(h["text"] == "营收" for h in hits), f"14px 短标签未抓: {hits}"


def test_short_label_fires_on_svg_axis_text():
    svg = ('<svg width="300" height="100"><text x="10" y="50" '
           'style="font-size:14px" class="tick">2024</text></svg>')
    hits = _run(_wrap(svg))
    if hits is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert any(h.get("is_svg") and h["text"] == "2024" for h in hits), f"SVG 轴标未抓: {hits}"


def test_short_label_quiet_on_proper_size_and_chrome():
    # 18px (not < 18) AND a chrome .unit at 14px → both quiet
    h1 = _run(_wrap('<span class="cat" style="font-size:18px">营收</span>'))
    h2 = _run(_wrap('<span class="unit" style="font-size:14px">万</span>'))
    if h1 is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable")
    assert h1 == [], f"18px false positive: {h1}"
    assert h2 == [], f"chrome .unit false positive: {h2}"


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
