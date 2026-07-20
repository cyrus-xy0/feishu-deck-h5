"""R-LOCAL-ASSET-REF: local decks may not cold-load static assets remotely.

Pure source-byte tests: the rule must execute without Chromium, before a remote
stylesheet/script/image can delay the browser-based audit itself.
"""

import importlib.util
import pathlib


ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
SPEC = importlib.util.spec_from_file_location(
    "run_audits_local_asset_refs", ASSETS / "run-audits.py")
RA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RA)

VD_SPEC = importlib.util.spec_from_file_location(
    "validate_deck_local_asset_refs", ASSETS.parent / "deck-json" / "validate-deck.py")
VD = importlib.util.module_from_spec(VD_SPEC)
VD_SPEC.loader.exec_module(VD)


def _findings(html, base_dir):
    return RA.audit_local_asset_refs_bytes(html, base_dir)


def test_remote_and_machine_absolute_static_assets_are_hard_errors(tmp_path):
    html = """<!doctype html><html><head>
      <link rel="stylesheet" href="https://cdn.example.com/deck.css">
      <script src="file:///Users/me/runtime.js"></script>
      </head><body>
      <img src="https://img.example.com/a.png">
      <video poster="/Users/me/poster.jpg"></video>
      <source srcset="//cdn.example.com/a.webp 1x, assets/a@2x.webp 2x">
      <div style="background:url('C:\\deck\\hero.png')"></div>
      <img src="lark://asset/hero">
      </body></html>"""
    findings = _findings(html, tmp_path)
    refs = {f["reference"] for f in findings}
    assert "https://cdn.example.com/deck.css" in refs
    assert "file:///Users/me/runtime.js" in refs
    assert "https://img.example.com/a.png" in refs
    assert "/Users/me/poster.jpg" in refs
    assert "//cdn.example.com/a.webp" in refs
    assert "C:\\deck\\hero.png" in refs
    assert "lark://asset/hero" in refs
    assert all(f["rule"] == "R-LOCAL-ASSET-REF" for f in findings)
    assert all(f["severity"] == "error" for f in findings)


def test_inline_and_linked_css_absolute_urls_fire(tmp_path):
    css_dir = tmp_path / "assets"
    css_dir.mkdir()
    (css_dir / "deck.css").write_text(
        "@import url('nested.css'); .x{background:url(https://img.example.com/x.png)}",
        encoding="utf-8",
    )
    (css_dir / "nested.css").write_text(
        ".y{background:url('/Users/me/y.png')}", encoding="utf-8")
    html = """<html><head><link rel="stylesheet" href="assets/deck.css">
      <style>.z{background:url('https://img.example.com/z.png')}</style>
      </head><body></body></html>"""
    refs = {f["reference"] for f in _findings(html, tmp_path)}
    assert refs == {
        "https://img.example.com/x.png",
        "/Users/me/y.png",
        "https://img.example.com/z.png",
    }


def test_relative_embedded_and_navigation_links_are_allowed(tmp_path):
    html = """<html><head><link rel="stylesheet" href="assets/deck.css"></head>
      <body><a href="https://example.com/report">source</a>
      <img src="assets/a.png"><img src="data:image/png;base64,AAAA">
      <svg><use href="#icon"></use></svg>
      <div style="background:url('../shared/bg.jpg')"></div>
      </body></html>"""
    assert _findings(html, tmp_path) == []


def test_remote_iframe_keeps_dedicated_policy_but_file_iframe_fails(tmp_path):
    html = """<html><body>
      <iframe src="https://demo.example.com/live"></iframe>
      <iframe src="file:///Users/me/demo.html"></iframe>
      </body></html>"""
    findings = _findings(html, tmp_path)
    assert [f["reference"] for f in findings] == ["file:///Users/me/demo.html"]


def test_rule_is_wired_into_both_path_runner_findings(tmp_path):
    html = """<!doctype html><html><body><div class="deck"></div>
      <img src="https://img.example.com/a.png">
      <script src="assets/feishu-deck.js"></script></body></html>"""
    codes = {f["rule"] for f in RA.runner_source_byte_findings(html, tmp_path)}
    assert "R-LOCAL-ASSET-REF" in codes


def test_deckjson_generation_gate_blocks_before_render(tmp_path):
    deck = {
        "deck": {"title": "x", "language": "zh-only"},
        "slides": [{
            "key": "s1",
            "layout": "raw",
            "data": {
                "html": '<a href="https://example.com/source">source</a>',
                "elements": [{"type": "image", "src": "https://img.example.com/a.png"}],
            },
            "custom_css": ".hero{background:url('/Users/me/hero.png')}",
        }],
    }
    result = VD.Result()
    VD.check_business_rules(deck, result, strict=False, deck_dir=tmp_path)
    messages = "\n".join(message for _, message in result.errors)
    assert messages.count("R-LOCAL-ASSET-REF") == 2
    assert "https://img.example.com/a.png" in messages
    assert "/Users/me/hero.png" in messages
    assert "https://example.com/source" not in messages


def test_deckjson_generation_gate_keeps_remote_iframe_policy(tmp_path):
    deck = {
        "deck": {"title": "x", "language": "zh-only"},
        "slides": [{
            "key": "s1",
            "layout": "iframe-embed",
            "data": {
                "src": "https://demo.example.com/live",
                "html": '<iframe src="https://demo.example.com/live"></iframe>',
            },
        }],
    }
    result = VD.Result()
    VD.check_business_rules(deck, result, strict=False, deck_dir=tmp_path)
    assert not any("R-LOCAL-ASSET-REF" in message
                   for _, message in result.errors)
