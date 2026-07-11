"""Deck-level dynamic canvas: schema, renderer, runtime and tool discovery."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


DECK_JSON = Path(__file__).resolve().parents[1]
SKILL_ROOT = DECK_JSON.parent
RENDER = DECK_JSON / "render-deck.py"
SCHEMA = DECK_JSON / "deck-schema.json"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RD = _load("_dynamic_canvas_render", RENDER)
VD = _load("_dynamic_canvas_validate", DECK_JSON / "validate-deck.py")
RUN_AUDITS = _load("_dynamic_canvas_audits", SKILL_ROOT / "assets" / "run-audits.py")
SHOOT = _load("_dynamic_canvas_shoot", DECK_JSON / "shoot.py")


def _deck(canvas=None):
    meta = {"title": "Dynamic canvas"}
    if canvas is not None:
        meta["canvas"] = canvas
    return {
        "version": "1.0",
        "deck": meta,
        "slides": [{
            "key": "page-one",
            "layout": "raw",
            "screen_label": "01 page",
            "data": {"html": '<div style="position:absolute;inset:0">canvas</div>'},
        }],
    }


def _render(tmp_path: Path, canvas=None, body=None) -> Path:
    deck = tmp_path / "deck.json"
    payload = _deck(canvas)
    if body is not None:
        payload["slides"][0]["data"]["html"] = body
    deck.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    env = dict(os.environ, DECK_LOG_NO_AUTOSNAP="1", DECK_NO_AUTO_SCOPE="1")
    proc = subprocess.run(
        [sys.executable, str(RENDER), str(deck), str(out) + "/",
         "--skip-validate-json", "--skip-validate-html", "--skip-copy-assets"],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return out / "index.html"


def test_schema_canvas_optional_and_strict():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = VD.SchemaValidator(schema)

    def errors(instance):
        result = VD.Result()
        validator.validate(instance, result)
        return result.errors

    assert errors(_deck()) == []  # legacy: canvas omitted
    assert errors(_deck({
        "width": 1920,
        "height": 360,
        "source_width_emu": 12192000,
        "source_height_emu": 2286000,
        "aspect_ratio": "16:3",
    })) == []
    assert errors(_deck({"width": 1920}))
    assert errors(_deck({"width": 1920, "height": 0}))
    assert errors(_deck({"width": 1920, "height": 360,
                         "aspect_ratio": "wide"}))


def test_renderer_stamps_root_dimensions_and_css_vars(tmp_path):
    html = _render(tmp_path, {"width": 1600, "height": 300,
                              "aspect_ratio": "16:3"}).read_text(encoding="utf-8")
    assert 'data-deck-width="1600"' in html
    assert 'data-deck-height="300"' in html
    assert "--fs-deck-width:1600px" in html
    assert "--fs-deck-height:300px" in html
    assert "--fs-deck-aspect:1600 / 300" in html


def test_renderer_legacy_default_keeps_root_markup_compatible(tmp_path):
    html = _render(tmp_path).read_text(encoding="utf-8")
    assert 'data-deck-width=' not in html
    assert 'data-deck-height=' not in html
    assert RD._deck_canvas(_deck()) == (1920, 1080)


def test_canvas_layout_inherits_deck_coordinate_plane():
    slide = {
        "key": "canvas-page",
        "layout": "canvas",
        "data": {"elements": [{
            "id": "box", "type": "shape",
            "x": 800, "y": 150, "w": 800, "h": 150,
            "fill": "#123456",
        }]},
    }
    html = RD.render_slide(slide, 0, "assets", deck_canvas=(1600, 300))
    assert "left:50.0cqw" in html
    assert "top:50.0cqh" in html
    assert "width:50.0cqw" in html
    assert "height:50.0cqh" in html


def test_screenshot_and_audit_helpers_discover_portable_canvas(tmp_path):
    html = tmp_path / "index.html"
    html.write_text(
        '<div class="deck" data-deck-width="1920" data-deck-height="360"></div>',
        encoding="utf-8",
    )
    raw = html.read_text(encoding="utf-8")
    assert RUN_AUDITS._canvas_dimensions(raw, tmp_path) == (1920, 360)
    assert SHOOT._read_canvas(html) == (1920, 360)
    legacy = tmp_path / "legacy.html"
    legacy.write_text('<div class="deck"></div>', encoding="utf-8")
    assert SHOOT._read_canvas(legacy) == (1920, 1080)


def test_runtime_scales_custom_canvas_to_viewport(tmp_path):
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright not installed")
    html = _render(tmp_path, {"width": 1600, "height": 300,
                              "aspect_ratio": "16:3"})
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 800, "height": 600})
            page.goto(html.as_uri() + "?mode=present", wait_until="domcontentloaded")
            page.wait_for_function("() => document.querySelector('.deck[data-js-ready]')")
            dims = page.evaluate("""() => {
              const s = document.querySelector('.slide');
              const r = s.getBoundingClientRect();
              const cs = getComputedStyle(s);
              return { cssWidth: cs.width, cssHeight: cs.height,
                       renderedWidth: r.width, renderedHeight: r.height };
            }""")
            browser.close()
    except Exception as exc:
        pytest.skip(f"chromium unavailable: {exc}")
    assert dims["cssWidth"] == "1600px"
    assert dims["cssHeight"] == "300px"
    assert dims["renderedWidth"] == pytest.approx(800, abs=1)
    assert dims["renderedHeight"] == pytest.approx(150, abs=1)


def test_visual_audit_uses_custom_canvas_boundary(tmp_path):
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            browser.close()
    except Exception as exc:
        pytest.skip(f"chromium unavailable: {exc}")
    html = _render(
        tmp_path,
        {"width": 1600, "height": 300, "aspect_ratio": "16:3"},
        '<div style="position:relative;left:1550px;width:100px;height:40px;'
        'font-size:24px;white-space:nowrap">overflow probe</div>',
    )
    result = RUN_AUDITS.run_unified_engine(html, scope=[1], settle_ms=50)
    overflow = [f for f in result["findings"] if f.get("rule") == "R-OVERFLOW"]
    assert result["canvas"] == {"width": 1600, "height": 300}
    assert overflow, "content crossing x=1600 must be measured against the custom canvas"
    assert overflow[0]["deltaW"] == pytest.approx(50, abs=2)
