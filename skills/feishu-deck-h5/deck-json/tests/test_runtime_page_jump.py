"""Browser coverage for the present-mode quick page-number jump controls.

The pager counts visible slides while ``goTo`` navigates physical frame indexes.
This test keeps a hidden slide in the middle so a visible page jump must perform
the same ordinal-to-frame translation as the real presenter UI.
"""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "assets" / "feishu-deck.js"
CSS = ROOT / "assets" / "feishu-deck.css"


def _current_key(page):
    return page.locator(".slide-frame.is-current .slide").get_attribute("data-slide-key")


@pytest.fixture()
def deck_page(tmp_path):
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # pragma: no cover - capability-dependent
        pytest.skip(f"playwright unavailable: {exc}")

    frames = "".join(
        f'''<div class="slide-frame"><div class="slide" data-layout="raw"
             data-slide-key="{key}"{hidden}><h1>{key}</h1></div></div>'''
        for key, hidden in (
            ("alpha", ""),
            ("beta-hidden", " data-hidden"),
            ("gamma", ""),
            ("delta", ""),
        )
    )
    html = tmp_path / "page-jump.html"
    html.write_text(
        f'''<!doctype html><html><head><meta charset="utf-8">
        <link rel="stylesheet" href="{CSS.as_uri()}">
        <style>html,body{{margin:0;width:100%;height:100%}}</style></head>
        <body><div class="deck">{frames}</div>
        <script src="{JS.as_uri()}"></script></body></html>''',
        encoding="utf-8",
    )

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception as exc:  # pragma: no cover - capability-dependent
            pytest.skip(f"chromium unavailable: {exc}")
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto(html.as_uri() + "?mode=present")
        page.wait_for_selector(".deck[data-js-ready]")
        yield page
        browser.close()


def test_bottom_pager_jumps_by_visible_ordinal(deck_page):
    page = deck_page
    pager = page.locator(".deck-ui .cur")

    assert pager.input_value() == "01"
    assert pager.get_attribute("role") is None
    assert pager.get_attribute("aria-valuenow") is None
    assert page.locator(".deck-ui .total").text_content() == "03"
    assert _current_key(page) == "alpha"

    # Visible page 2 is physical frame #3 because frame #2 is hidden.
    pager.fill("2")
    pager.press("Enter")
    assert _current_key(page) == "gamma"
    assert page.url.endswith("#3")
    assert pager.input_value() == "02"

    # Out-of-range values follow the retired pager and clamp to the last page.
    pager.fill("99")
    pager.press("Enter")
    assert _current_key(page) == "delta"
    assert page.url.endswith("#4")
    assert pager.input_value() == "03"

    # Invalid text restores the current page instead of navigating.
    pager.fill("not-a-page")
    pager.press("Enter")
    assert _current_key(page) == "delta"
    assert pager.input_value() == "03"

    pager.fill("-5")
    pager.press("Enter")
    assert _current_key(page) == "alpha"
    assert page.url.endswith("#1")
    assert pager.input_value() == "01"


def test_typing_and_presenter_page_jump_do_not_trigger_global_shortcuts(deck_page):
    page = deck_page
    pager = page.locator(".deck-ui .cur")

    pager.fill("2")
    pager.press("Enter")
    assert _current_key(page) == "gamma"

    # Arrow keys belong to the focused input; they must not turn the deck page.
    pager.click()
    pager.press("ArrowLeft")
    assert _current_key(page) == "gamma"
    pager.press("Escape")
    assert pager.input_value() == "02"

    page.keyboard.press("p")
    presenter = page.locator(".fs-presenter")
    presenter.wait_for(state="visible")
    pv_pager = presenter.locator(".pv-page-input")
    assert pv_pager.input_value() == "2"
    assert pv_pager.get_attribute("role") is None
    assert pv_pager.get_attribute("aria-valuenow") is None
    assert presenter.locator(".pv-total").text_content() == "3"

    pv_pager.fill("1")
    pv_pager.press("Enter")
    assert _current_key(page) == "alpha"
    assert page.url.endswith("#1")
    assert pv_pager.input_value() == "1"
    assert pager.input_value() == "01"

    # Escape cancels an in-progress number without closing presenter mode.
    pv_pager.fill("3")
    pv_pager.press("Escape")
    assert _current_key(page) == "alpha"
    assert pv_pager.input_value() == "1"
    assert presenter.is_visible()
