"""F-344 · letterbox seam auto-fix (markBleedPanels / .fs-bleed-panel).

A lifted/raw page often carries a full-slide opaque background PANEL of its own
(.qilu-page / .source-frame-wrap / .ppt-stage …) that re-paints the framework
content-bg (at the 16:9 slide crop) or a flat dark solid OVER the now-transparent
.slide (F-318). In present mode the .slide-frame paints the SAME content-bg across
the WHOLE frame incl. the letterbox, so the panel's slide-confined copy seams at
the slide↔letterbox boundary on any non-16:9 viewport ("黑边").

feishu-deck.js::markBleedPanels geometry-detects those panels (≥95% slide
coverage + content-bg-or-dark-solid backdrop) and tags them .fs-bleed-panel,
stashing any decorative gradient glows in --fs-bleed-grads; feishu-deck.css drops
their opaque backdrop in present mode so the frame's single content-bg layer shows
through seamlessly.

Two layers of test:
  * fingerprint (no browser) — the fix is BUNDLED in the framework assets and
    wired into BOTH lazy paths (same "ensure the runtime ships" philosophy as
    R-AUTOBALANCE-PRESENT);
  * runtime (Chromium) — the actual DOM effect: present neutralises the panel
    (keeps glows, drops content-bg), scroll leaves it, and a small card is never
    touched. Skips gracefully when Playwright/Chromium is unavailable.
"""
import pathlib
import re
import sys
import tempfile

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
JS = (ASSETS / "feishu-deck.js").read_text(encoding="utf-8")
CSS = (ASSETS / "feishu-deck.css").read_text(encoding="utf-8")


# ---------------------------------------------------------------- fingerprint --
def test_js_carries_markbleedpanels():
    assert "function markBleedPanels(slide)" in JS, "markBleedPanels not bundled in feishu-deck.js"


def test_js_wires_both_lazy_paths():
    # init full-deck pass + is-current MutationObserver retry — same two hooks
    # maybeBalance rides, so content-visibility-skipped frames are still covered.
    assert JS.count("markBleedPanels(s)") >= 2, "markBleedPanels must run on init pass AND is-current retry"


def test_css_carries_present_gated_bleed_rule():
    assert "--fs-bleed-grads" in CSS, "gradient-preserve var missing in feishu-deck.css"
    assert re.search(r'\.deck\[data-mode="present"\][^{]*\.fs-bleed-panel', CSS), \
        ".fs-bleed-panel neutraliser must be present-mode gated"


# ------------------------------------------------------------------- runtime --
_CONTENT_BG = (ASSETS / "lark-content-bg.jpg").as_uri()
_FW_CSS = (ASSETS / "feishu-deck.css").as_uri()
_FW_JS = (ASSETS / "feishu-deck.js").as_uri()

_FIXTURE = f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="{_FW_CSS}">
<style>
.slide[data-slide-key="t"] .panel {{ position:absolute; inset:0;
  background-color:#050a17;
  background-image: radial-gradient(circle at 18% 16%, rgba(60,127,255,.30), transparent 60%), url("{_CONTENT_BG}");
  background-size: auto, cover; background-position: center, center; background-repeat:no-repeat; }}
.slide[data-slide-key="t"] .card {{ position:absolute; left:40px; top:40px; width:320px; height:180px; background:#101826; }}
</style></head><body>
<div class="deck"><div class="slide-frame is-current">
<div class="slide" data-layout="raw" data-slide-key="t"><div class="panel"><div class="card">x</div></div></div>
</div></div>
<script src="{_FW_JS}"></script></body></html>"""

_PROBE = """() => {
  const panel = document.querySelector('.panel');
  const card  = document.querySelector('.card');
  const cs = getComputedStyle(panel);
  return {
    panelTagged: panel.classList.contains('fs-bleed-panel'),
    cardTagged:  card.classList.contains('fs-bleed-panel'),
    panelBgColor: cs.backgroundColor,
    panelBgImage: cs.backgroundImage,
  };
}"""


def _read(mode):
    """Render the fixture, load it in `mode`, return the probe dict (or skip)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        import pytest
        pytest.skip(f"playwright unavailable: {e}")
    with tempfile.TemporaryDirectory() as td:
        idx = pathlib.Path(td) / "index.html"
        idx.write_text(_FIXTURE, encoding="utf-8")
        try:
            with sync_playwright() as p:
                try:
                    b = p.chromium.launch()
                except Exception as e:  # noqa: BLE001
                    import pytest
                    pytest.skip(f"chromium unavailable: {e}")
                pg = b.new_page(viewport={"width": 1440, "height": 900})  # 16:10 → letterbox
                pg.goto(f"{idx.as_uri()}?mode={mode}", wait_until="domcontentloaded")
                pg.wait_for_timeout(700)  # let the rAF init pass run markBleedPanels
                data = pg.evaluate(_PROBE)
                b.close()
                return data
        except Exception as e:  # noqa: BLE001
            import pytest
            pytest.skip(f"engine run failed: {e}")


def test_present_neutralises_panel_keeps_glow():
    d = _read("present")
    assert d["panelTagged"], "full-slide opaque panel should be tagged .fs-bleed-panel"
    assert d["panelBgColor"] in ("rgba(0, 0, 0, 0)", "transparent"), \
        f"panel backdrop should be transparent in present, got {d['panelBgColor']}"
    assert "gradient" in d["panelBgImage"], "decorative glow gradient must be preserved"
    assert "lark-content-bg" not in d["panelBgImage"], "redundant content-bg layer must be dropped"


def test_small_card_is_not_touched():
    d = _read("present")
    assert not d["cardTagged"], "a <95%-coverage card must NOT be neutralised"


def test_scroll_mode_leaves_panel_opaque():
    d = _read("scroll")
    # JS may still tag by geometry, but the CSS effect is present-mode only:
    # scroll keeps the panel's own opaque backdrop (no letterbox there).
    assert d["panelBgColor"] not in ("rgba(0, 0, 0, 0)", "transparent"), \
        f"scroll mode must keep the panel's opaque bg, got {d['panelBgColor']}"


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
