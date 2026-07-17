"""F-344 / F-345 · letterbox seam auto-fix (markBleedPanels + frame decor mirror).

A lifted/raw page often carries a full-slide background PANEL of its own
(.qilu-page / .source-frame-wrap / .ppt-stage / .slide65-redo …). On a non-16:9
viewport the 16:9 deck letterboxes, and the panel — confined to the slide — seams
against the un-decorated letterbox bands. Two seam classes are healed here:

  * F-344 — the panel re-paints the framework content-bg (at the 16:9 slide crop)
    or a flat dark solid OVER the now-transparent .slide (F-318). The .slide-frame
    already paints that SAME content-bg across the WHOLE frame, so the panel's
    slide-confined copy seams at the boundary. Fix: drop the panel's redundant
    backdrop (.fs-bleed-panel) so the frame's single layer shows through.

  * F-345 — the panel carries CUSTOM full-bleed DECORATION the frame lacks: radial
    glows in its background + a darkening ::before vignette. These stop at the slide
    edge, so the letterbox stays un-decorated → a luma seam (exactly what the
    declarative data-decor mirror fixes for framework decor TOKENS). Fix:
    feishu-deck.js::markBleedPanels MIRRORS the decoration onto the viewport-filling
    .slide-frame BACKGROUND (--fs-bleed-deco-* over the frame's captured backdrop, so
    it stays behind the slide content — the vignette must not dim cards/text) and
    zeroes the panel's own copy (.fs-bleed-panel drops its backdrop;
    .fs-bleed-promoted drops its ::before). content-bg layers are matched by BASENAME
    so the panel's own-assets-dir copy is recognised as the frame's image and dropped.

Two layers of test:
  * fingerprint (no browser) — the fix is BUNDLED in the framework assets and wired
    into BOTH lazy paths (same philosophy as R-AUTOBALANCE-PRESENT);
  * runtime (Chromium + PIL) — the actual DOM effect AND the user-visible outcome:
    the decoration is promoted to the frame, the panel + its ::before are zeroed, and
    the slide↔letterbox boundary has NO luma step. Skips gracefully when
    Playwright/Chromium/PIL are unavailable.
"""
import pathlib
import re
import shutil
import sys
import tempfile

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
EXTRA_LAYOUTS = pathlib.Path(__file__).resolve().parents[1] / "templates" / "extra-layouts.css"
JS = (ASSETS / "feishu-deck.js").read_text(encoding="utf-8")
CSS = (ASSETS / "feishu-deck.css").read_text(encoding="utf-8")
EXTRA_CSS = EXTRA_LAYOUTS.read_text(encoding="utf-8")
_FW_CSS = (ASSETS / "feishu-deck.css").as_uri()
_FW_JS = (ASSETS / "feishu-deck.js").as_uri()


# ---------------------------------------------------------------- fingerprint --
def test_js_carries_markbleedpanels():
    assert "function markBleedPanels(slide)" in JS, "markBleedPanels not bundled in feishu-deck.js"


def test_js_wires_both_lazy_paths():
    # init full-deck pass + is-current MutationObserver retry — same two hooks
    # maybeBalance rides, so content-visibility-skipped frames are still covered.
    assert JS.count("markBleedPanels(s)") >= 2, "markBleedPanels must run on init pass AND is-current retry"


def test_css_carries_present_gated_panel_rule():
    assert "--fs-bleed-grads" in CSS, "panel backdrop-drop var missing in feishu-deck.css"
    assert re.search(r'\.deck\[data-mode="present"\][^{]*\.fs-bleed-panel', CSS), \
        ".fs-bleed-panel neutraliser must be present-mode gated"


def test_css_carries_present_gated_frame_mirror_rule():
    # F-345 — the frame-host decoration mirror + the ::before vignette zero.
    assert "--fs-bleed-deco-image" in CSS, "frame decor-mirror var missing in feishu-deck.css"
    assert re.search(r'\.deck\[data-mode="present"\][^{]*\.fs-bleed-host', CSS), \
        ".fs-bleed-host frame mirror must be present-mode gated"
    assert re.search(r'\.fs-bleed-promoted[^{]*::before', CSS), \
        ".fs-bleed-promoted::before vignette-zero rule missing"


def test_present_mode_preserves_full_page_replica_backgrounds():
    assert '.slide-frame:has(> .slide.page-replica)' in CSS
    assert '.slide-frame > .slide:not(.page-replica)' in CSS
    assert re.search(
        r"\.slide\.page-replica::before,\s*"
        r"\.slide\.page-replica::after\s*\{[^}]*"
        r"content:\s*none\s*!important;[^}]*"
        r"display:\s*none\s*!important;",
        EXTRA_CSS,
        re.S,
    )


def test_js_carries_f345_promote_logic():
    assert "fs-bleed-host" in JS and "fs-bleed-promoted" in JS, "F-345 frame-promote tags missing in JS"
    assert "isFrameBg" in JS, "content-bg basename matcher (isFrameBg) missing in JS"
    assert "'::before'" in JS, "::before vignette capture missing in JS"
    assert "--fs-bleed-deco-image" in JS, "JS must populate the frame decor-mirror var"


# ------------------------------------------------------------------- runtime --
# A decorated lifted panel == the real .qilu-page shape: a full-slide wrapper whose
# background is [two radial glows + content-bg] plus a darkening ::before vignette.
# The panel references content-bg by a RELATIVE url (resolves to the temp dir, a
# DIFFERENT path than the frame's framework var) to exercise the basename match.
def _deco_fixture():
    return """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="%(css)s">
<style>
.slide[data-slide-key="t"] .panel { position:absolute; inset:0; padding:120px 80px 60px;
  background-image: radial-gradient(900px 620px at 88%% 8%%, rgba(60,127,255,0.30), transparent 62%%),
                    radial-gradient(760px 520px at 6%% 98%%, rgba(92,63,251,0.20), transparent 64%%),
                    url("lark-content-bg.jpg");
  background-size: auto, auto, cover; background-position: center, center, center;
  background-repeat: no-repeat; background-color: #050a17; }
.slide[data-slide-key="t"] .panel::before { content:""; position:absolute; inset:0;
  pointer-events:none; z-index:0;
  background: linear-gradient(180deg, rgba(0,0,0,0.04), rgba(0,0,0,0.50)); }
.slide[data-slide-key="t"] .card { position:relative; z-index:1; width:300px; height:160px;
  background:#101826; border-radius:18px; }
</style></head><body>
<div class="deck"><div class="slide-frame is-current">
<div class="slide" data-layout="raw" data-slide-key="t">
  <div class="panel"><div class="card">x</div></div>
</div></div></div>
<script src="%(js)s"></script></body></html>""" % {"css": _FW_CSS, "js": _FW_JS}


# A plain content-bg panel (no glows, no ::before) → F-344 path only, NOT promoted.
def _plain_fixture():
    return """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="%(css)s">
<style>
.slide[data-slide-key="t"] .panel { position:absolute; inset:0;
  background: #050a17 url("lark-content-bg.jpg") center/cover no-repeat; }
</style></head><body>
<div class="deck"><div class="slide-frame is-current">
<div class="slide" data-layout="raw" data-slide-key="t"><div class="panel"></div></div>
</div></div></div>
<script src="%(js)s"></script></body></html>""" % {"css": _FW_CSS, "js": _FW_JS}


_PROBE = """() => {
  const frame = document.querySelector('.slide-frame');
  const panel = document.querySelector('.panel');
  const card  = document.querySelector('.card');
  const pcs = getComputedStyle(panel);
  return {
    frameHost:      frame.classList.contains('fs-bleed-host'),
    panelBleedPanel:panel.classList.contains('fs-bleed-panel'),
    panelPromoted:  panel.classList.contains('fs-bleed-promoted'),
    cardTagged:     card ? card.classList.contains('fs-bleed-panel') : false,
    panelBgColor:   pcs.backgroundColor,
    panelBgImage:   pcs.backgroundImage,
    panelBeforeBg:  getComputedStyle(panel, '::before').backgroundImage,
    frameBgImage:   getComputedStyle(frame).backgroundImage,
  };
}"""


def _run(fixture, mode, shot=False):
    """Render the fixture in `mode`; return (probe dict, screenshot path|None) or skip."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        import pytest
        pytest.skip(f"playwright unavailable: {e}")
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        (d / "index.html").write_text(fixture, encoding="utf-8")
        # content-bg into the temp dir → panel's relative url resolves HERE, a
        # different path than the frame's framework-var copy (basename-match test).
        src = ASSETS / "lark-content-bg.jpg"
        if src.exists():
            shutil.copyfile(src, d / "lark-content-bg.jpg")
        out = None
        try:
            with sync_playwright() as p:
                try:
                    b = p.chromium.launch()
                except Exception as e:  # noqa: BLE001
                    import pytest
                    pytest.skip(f"chromium unavailable: {e}")
                pg = b.new_page(viewport={"width": 1440, "height": 900})  # 16:10 → 45px letterbox
                pg.goto(f"{(d / 'index.html').as_uri()}?mode={mode}", wait_until="domcontentloaded")
                pg.wait_for_timeout(800)  # let the rAF init pass run markBleedPanels
                data = pg.evaluate(_PROBE)
                if shot:
                    keep = pathlib.Path(tempfile.gettempdir()) / "fs_f345_shot.png"
                    pg.screenshot(path=str(keep))
                    out = str(keep)
                b.close()
                return data, out
        except Exception as e:  # noqa: BLE001
            import pytest
            pytest.skip(f"engine run failed: {e}")


def test_present_promotes_decoration_to_frame():
    d, _ = _run(_deco_fixture(), "present")
    assert d["frameHost"], "frame must be tagged .fs-bleed-host (decoration promoted)"
    assert d["panelPromoted"], "decorated panel must be tagged .fs-bleed-promoted"
    assert d["panelBleedPanel"], "decorated panel must also be tagged .fs-bleed-panel"
    assert "gradient" in d["frameBgImage"], "promoted glows/vignette must appear on the frame"
    assert "lark-content-bg" in d["frameBgImage"], "frame must still carry its content-bg backdrop under the decor"
    assert d["panelBgImage"] == "none", \
        f"panel's own content-bg + glows must be dropped (now on frame), got {d['panelBgImage'][:60]}"
    assert d["panelBeforeBg"] == "none", "panel's ::before vignette must be zeroed (now on frame)"


def test_present_boundary_has_no_seam():
    try:
        from PIL import Image
    except Exception as e:  # noqa: BLE001
        import pytest
        pytest.skip(f"PIL unavailable: {e}")
    _, shot = _run(_deco_fixture(), "present", shot=True)
    if not shot:
        import pytest
        pytest.skip("no screenshot produced")
    im = Image.open(shot).convert("RGB")
    x = im.size[0] // 2
    # bottom boundary at y≈855 (worst case — 50% darkening). With the vignette promoted
    # to the frame the decoration is continuous, so px just inside the slide and just
    # inside the letterbox must match (no step). Without F-345 the slide side is
    # visibly darker → a clear step.
    above = im.getpixel((x, 851))   # slide side
    below = im.getpixel((x, 859))   # letterbox side
    step = max(abs(above[i] - below[i]) for i in range(3))
    assert step <= 4, f"slide↔letterbox boundary still has a luma step ({above} vs {below}, Δ={step})"


def test_plain_content_bg_panel_uses_f344_not_promote():
    d, _ = _run(_plain_fixture(), "present")
    assert d["panelBleedPanel"], "plain content-bg panel must be F-344 tagged .fs-bleed-panel"
    assert not d["frameHost"], "a panel with NO custom decoration must not promote (nothing to mirror)"
    assert d["panelBgImage"] == "none", "plain panel's redundant content-bg must be dropped"


def test_small_card_is_not_touched():
    d, _ = _run(_deco_fixture(), "present")
    assert not d["cardTagged"], "a <95%-coverage card must NOT be neutralised"


def test_scroll_mode_leaves_panel_intact():
    d, _ = _run(_deco_fixture(), "scroll")
    # JS may still tag by geometry, but every CSS effect is present-mode only: scroll
    # has no letterbox, so the panel keeps its own decorated backdrop and the frame is
    # not re-painted.
    assert not d["frameHost"] or "gradient" in d["panelBgImage"], \
        "scroll mode must leave the panel's own decoration intact (present-gated effects only)"
    assert d["panelBgImage"] != "none", \
        f"scroll mode must keep the panel's background, got {d['panelBgImage']}"


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
