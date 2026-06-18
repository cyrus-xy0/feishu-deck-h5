"""R-VIS-ABS-OVERLAP — 二期 (2026-06-15): media-box-over-text + large-overlap→error.

Background: a Pixar story page shipped with the image column (.art, an <img> in
an absolute box) overlapping the text column (.rail) by 76px. The original rule
*did* warn (.art carried a caption so it counted as a text block) but the render
still printed "PASS · 0 errors", so the warn was missed. Two gaps closed:

  1. MEDIA BLIND SPOT — a caption-LESS image column (textContent < 4) was filtered
     out by the "must carry text" candidate gate, so an image-over-text collision
     was invisible. Now absolute media boxes are paired against the text blocks.
  2. SILENT WARN — a large, clearly-visible text-occluding overlap should BLOCK,
     not pass as a non-blocking warn. Escalated to `error` at >=40px on BOTH axes,
     BUT only for STATIC blocks: transformed (slide-in / collapsed-overlay) blocks
     are exempted because the audit measures phantom overlaps on them in a non-
     present context (renwu .rw-detail-layer translateX: 14px gap in present, the
     audit reported 45px) — those stay `warn` so they never false-positive-block.

STATIC wiring only (no Chromium) — guards the rule logic against regression.
The must-fire / must-not behaviour was verified empirically against the live deck
(static .rail/.art 76px → BLOCK; renwu translateX panel → warn; fixed gutter → PASS).
"""
import re
import pathlib

HERE = pathlib.Path(__file__).resolve()
ROOT = HERE.parent.parent.parent                      # skills/feishu-deck-h5/
ASSETS = ROOT / "assets"
DOC = ROOT / "references" / "validator-rules.md"


def _rule_body():
    js = (ASSETS / "audits.js").read_text(encoding="utf-8")
    i = js.index("id: 'R-VIS-ABS-OVERLAP'")
    j = js.index("id: 'R-VIS-BAND-COLLIDE'", i)        # next rule in the list
    return js[i:j]


def test_media_occluder_branch_present():
    body = _rule_body()
    assert "visIsMediaBox(el)" in body, \
        "media-box occluder branch missing from R-VIS-ABS-OVERLAP (the .art-over-.rail blind spot)"
    assert "图片/媒体块" in body, "media-overlap finding message missing"
    # media occluders must be the caption-LESS ones (text boxes go through the text loop)
    assert "textContent || '').trim().length >= 4) continue" in body, \
        "media branch must skip text-bearing boxes (those are handled by the text loop)"


def test_large_static_overlap_escalates_to_error():
    body = _rule_body()
    # >=40px on BOTH axes is the escalation threshold (in design px)
    assert body.count("/ scale >= 40 && o.iy / scale >= 40") == 2, \
        "≥40px both-axis warn→error threshold must gate BOTH branches"
    # ...but only for STATIC (identity-transform) blocks — the phantom guard
    assert "_identityTf" in body, "transform-phantom guard for error escalation missing"
    assert body.count("_identityTf(") >= 4, \
        "escalation must check BOTH elements' transform in BOTH branches (text + media)"


def test_doc_lists_rule():
    doc = DOC.read_text(encoding="utf-8")
    assert "R-VIS-ABS-OVERLAP" in doc, "R-VIS-ABS-OVERLAP must stay documented in validator-rules.md"
