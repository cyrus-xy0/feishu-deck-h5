"""Opt-in large-deck progressive slide mounting.

Default decks keep their historical eager markup. ``deck.lazy_frames`` mirrors
the metadata needed before hydration onto each lightweight frame, keeps page 1
eager for the pre-JS fallback, and mounts the requested present-mode window on
demand. Scroll/edit modes still expand the complete deck.
"""

import importlib.util
import asyncio
import json
import subprocess
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
SKILL = DECK_JSON.parent
RENDER = DECK_JSON / "render-deck.py"
SCHEMA = DECK_JSON / "deck-schema.json"
JS = SKILL / "assets" / "feishu-deck.js"
CSS = SKILL / "assets" / "feishu-deck.css"


def _renderer_module():
    spec = importlib.util.spec_from_file_location("render_deck_lazy_test", str(RENDER))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _raw(key, label):
    return {
        "key": key,
        "layout": "raw",
        "screen_label": label,
        "data": {"html": f'<div class="stage"><h2>{label}</h2></div>'},
    }


def test_defer_slide_frame_keeps_one_inert_payload_and_metadata():
    rd = _renderer_module()
    source = (
        '    <div class="slide-frame">\n'
        '      <div class="slide" data-layout="raw" data-slide-key="hidden-page">\n'
        '        <div class="stage"><div>body</div></div>\n'
        '      </div>\n'
        '    </div>\n'
    )
    out = rd._defer_slide_frame(
        source,
        {"key": "hidden-page", "layout": "raw", "screen_label": "02 Hidden", "hidden": True},
    )

    assert out.count('data-fs-lazy-frame=""') == 1
    assert out.count("<template data-fs-lazy-slide>") == 1
    assert out.count('class="slide"') == 1
    assert 'data-slide-key="hidden-page"' in out
    assert 'data-screen-label="02 Hidden"' in out
    assert 'data-slide-hidden=""' in out
    assert out.index("<template data-fs-lazy-slide>") < out.index('class="slide"')


def test_renderer_emits_lazy_markup_only_when_opted_in(tmp_path):
    deck = {
        "version": "1.0",
        "deck": {"title": "lazy", "lazy_frames": True},
        "slides": [_raw("first", "01 First"), _raw("second", "02 Second")],
    }
    deck_path = tmp_path / "deck.json"
    deck_path.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(RENDER),
            str(deck_path),
            str(tmp_path),
            "--skip-copy-assets",
            "--skip-validate-html",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert '<div class="deck"' in html and 'data-lazy-frames=""' in html
    assert html.count("<template data-fs-lazy-slide>") == 1
    assert html.index('data-slide-key="first"') < html.index("<template data-fs-lazy-slide>")


def test_schema_accepts_boolean_and_rejects_non_boolean_lazy_frames():
    try:
        import jsonschema
    except Exception as exc:  # pragma: no cover - capability-dependent
        pytest.skip(f"jsonschema unavailable: {exc}")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    good = {"version": "1.0", "deck": {"title": "t", "lazy_frames": True},
            "slides": [_raw("first", "01 First")]}
    jsonschema.validate(good, schema)
    bad = json.loads(json.dumps(good))
    bad["deck"]["lazy_frames"] = "yes"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


@pytest.fixture()
def lazy_page(tmp_path):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - capability-dependent
        pytest.skip(f"playwright unavailable: {exc}")
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        pytest.skip("sync Playwright unavailable inside the suite's active asyncio loop")

    frames = []
    for i in range(1, 9):
        hidden = ' data-slide-hidden=""' if i == 2 else ""
        inner_hidden = " data-hidden" if i == 2 else ""
        slide = (
            f'<div class="slide" data-layout="raw" data-slide-key="k{i}"{inner_hidden}>'
            f'<div class="stage"><h1>page {i}</h1></div></div>'
        )
        if i == 1:
            frames.append(f'<div class="slide-frame" data-slide-key="k1">{slide}</div>')
        else:
            frames.append(
                f'<div class="slide-frame" data-fs-lazy-frame="" '
                f'data-slide-key="k{i}" data-layout="raw"{hidden}>'
                f'<template data-fs-lazy-slide>{slide}</template></div>'
            )
    html = tmp_path / "lazy.html"
    html.write_text(
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<link rel="stylesheet" href="{CSS.as_uri()}"></head><body>'
        f'<div class="deck" data-lazy-frames="">{"".join(frames)}</div>'
        f'<script src="{JS.as_uri()}"></script></body></html>',
        encoding="utf-8",
    )

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception as exc:  # pragma: no cover - capability-dependent
            pytest.skip(f"chromium unavailable: {exc}")
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        yield page, html
        browser.close()


def _open(page, html, suffix):
    page.goto(html.as_uri() + suffix)
    page.wait_for_selector(".deck[data-js-ready]")


def _current_key(page):
    return page.locator(".slide-frame.is-current > .slide").get_attribute("data-slide-key")


def test_present_mode_mounts_landing_window_then_progresses(lazy_page):
    page, html = lazy_page
    _open(page, html, "?mode=present#3")

    assert _current_key(page) == "k3"
    assert page.locator(".slide-frame > .slide").count() == 4  # eager #1 + #2/#3/#4
    assert page.locator('.slide-frame[data-slide-key="k8"] > template').count() == 1

    page.keyboard.press("ArrowRight")
    assert _current_key(page) == "k4"
    assert page.url.endswith("#4")
    assert page.locator('.slide-frame[data-slide-key="k5"] > .slide').count() == 1


def test_slug_hash_hidden_navigation_and_scroll_expansion(lazy_page):
    page, html = lazy_page
    _open(page, html, "?mode=present#k6")
    assert _current_key(page) == "k6"
    assert page.locator(".slide-frame > .slide").count() < 8

    _open(page, html, "?mode=present#1")
    page.keyboard.press("ArrowRight")
    assert _current_key(page) == "k3"  # k2 is hidden before hydration too

    _open(page, html, "?mode=scroll")
    assert page.locator(".slide-frame > .slide").count() == 8
