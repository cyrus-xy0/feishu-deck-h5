"""Regression tests for the 2026-06 全技能 code-review fixes (AUDIT-2026-06-01).

Locks in the headline fixes so they can't silently regress:
  R1  render_template parks raw {{{ }}} content so a literal {{ x }} in a raw
      slide / enricher slot no longer crashes the render.
  R2  _inject_custom_css matches `.slide` allowing extra classes → custom_css
      no longer silently dropped on story-case / replica slides.
  R3  validate-deck only warns on an EXPLICIT cols mismatch → a 3-step flow
      with no `cols` renders (was rejected under --strict).
  gate-failure propagation: a schema-invalid deck fails the render (non-zero).
  schema additionalProperties:false: a typo'd slide-level field is rejected.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
RENDER = DECK_JSON / "render-deck.py"
VALIDATE_DECK = DECK_JSON / "validate-deck.py"
EXTRA_CSS = DECK_JSON / "templates" / "extra-layouts.css"


def _cover():
    return {"key": "cover", "layout": "cover", "accent": "blue",
            "data": {"title": "t", "author": "a", "date": "2026-06"}}


def _render(deck, outdir):
    p = Path(outdir) / "deck.json"
    p.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
    return subprocess.run([sys.executable, str(RENDER), str(p), str(outdir)],
                          capture_output=True, text=True)


def test_R1_raw_slide_with_literal_braces_renders(tmp_path):
    deck = {"version": "1.0", "deck": {"title": "t", "author": "a", "date": "2026-06"},
            "slides": [_cover(),
                       {"key": "demo", "layout": "raw", "data": {"html":
                        '<div class="slide" data-layout="raw" data-slide-key="demo">'
                        '<div class="stage"><p>Use {{ count }} widgets</p></div></div>'}}]}
    r = _render(deck, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    # the literal placeholder must survive verbatim, not be substituted/escaped away
    assert "{{ count }}" in (tmp_path / "index.html").read_text(encoding="utf-8")


def test_R2_custom_css_injected_on_multiclass_slide():
    spec = importlib.util.spec_from_file_location("rd_under_test", str(RENDER))
    rd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rd)
    for cls in ("slide", "slide story-case", "slide page-replica"):
        html = (f'<div class="slide-frame"><div class="{cls}" data-slide-key="k">'
                f'<div class="stage">x</div></div></div>')
        out = rd._inject_custom_css(html, "k", ".stage{color:red}")
        assert "data-fs-custom-css" in out, f"custom_css dropped for class={cls!r}"
    # slide-frame alone (no real .slide) must NOT get a block
    only_frame = '<div class="slide-frame"><div class="x">y</div></div>'
    assert "data-fs-custom-css" not in rd._inject_custom_css(only_frame, "k", ".a{top:0}")


def test_R3_flow_process_3_steps_no_cols_renders(tmp_path):
    deck = {"version": "1.0", "deck": {"title": "t", "author": "a", "date": "2026-06"},
            "slides": [_cover(),
                       {"key": "proc", "layout": "flow", "variant": "process", "accent": "blue",
                        "data": {"title": "三步", "steps": [{"title": "一", "body": "x"},
                                 {"title": "二", "body": "y"}, {"title": "三", "body": "z"}]}}]}
    r = _render(deck, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_gate_failure_propagates(tmp_path):
    # invalid key (uppercase/underscore) → schema gate must fail the whole render
    deck = {"version": "1.0", "deck": {"title": "t", "author": "a", "date": "2026-06"},
            "slides": [{"key": "BadKey_UPPER", "layout": "cover",
                        "data": {"title": "t", "author": "a", "date": "2026-06"}}]}
    r = _render(deck, tmp_path)
    assert r.returncode != 0, "schema-invalid deck must fail the render"


def test_schema_rejects_misspelled_slide_field(tmp_path):
    deck = {"version": "1.0", "deck": {"title": "t", "author": "a", "date": "2026-06"},
            "slides": [dict(_cover(), varient="3up")]}  # typo: varient
    p = tmp_path / "deck.json"
    p.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([sys.executable, str(VALIDATE_DECK), str(p)],
                       capture_output=True, text=True)
    assert r.returncode != 0 and "varient" in (r.stdout + r.stderr)


def test_new_extra_layouts_are_ingest_gate_friendly():
    css = EXTRA_CSS.read_text(encoding="utf-8")

    assert ".slide[data-layout=\"chart\"] .cbar .cval {\n  font: 700 28px/1 var(--fs-font-latin);" in css
    assert ".slide[data-layout=\"chart\"] .chart-bar {\n  flex: 0 0 auto; height: 520px;" in css
    assert ".slide[data-layout=\"content-before-after\"] .side .icon" in css
    assert "width: 32px; height: 32px;" in css
    assert "font: 700 var(--fs-body)/1 var(--fs-font-cjk);" in css
    assert ".slide[data-layout=\"iframe-embed\"] .iframe-hint" in css
    assert "font: 600 var(--fs-body)/1.2 var(--fs-font-cjk);" in css
    assert "font: 700 40px/1 var(--fs-font-latin)" not in css
