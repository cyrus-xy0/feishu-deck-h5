"""Raw DeckJSON asset discovery for locate-slide.py verbose/JSON output."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCATE = HERE.parent / "locate-slide.py"


def _run(*args):
    return subprocess.run([sys.executable, str(LOCATE), *map(str, args)],
                          capture_output=True, text=True)


def test_raw_deckjson_assets_include_html_css_and_srcset():
    with tempfile.TemporaryDirectory() as td:
        deck = Path(td) / "deck.json"
        deck.write_text(json.dumps({
            "deck": {"title": "assets"},
            "slides": [{
                "key": "raw-assets",
                "layout": "raw",
                "data": {"html": """
                    <img src="input/qr.png">
                    <img data-src='input/lazy.webp'>
                    <video poster="input/poster.jpg"></video>
                    <source srcset="input/a.png 1x, input/b.png 2x">
                    <img src="https://example.com/remote.png">
                    <img src="data:image/png;base64,AAAA">
                    <a href="#anchor">jump</a>
                """},
                "custom_css": """
                    .x{background:url('assets/bg.jpg')}
                    .y{mask-image:url(../outside.svg)}
                """,
            }],
        }), encoding="utf-8")
        result = _run(deck, "#1", "--json")
        assert result.returncode == 0, result.stderr
        row = json.loads(result.stdout)[0]
        assert row["assets"] == [
            "assets/bg.jpg",
            "input/a.png",
            "input/b.png",
            "input/lazy.webp",
            "input/poster.jpg",
            "input/qr.png",
        ]


def test_rendered_html_fallback_uses_same_asset_parser():
    with tempfile.TemporaryDirectory() as td:
        html = Path(td) / "index.html"
        html.write_text("""
            <div class="slide-frame"><div class="slide" data-slide-key="one"
              data-layout="raw" data-screen-label="01 One">
              <img src='input/one.png'>
              <video poster="input/poster.jpg"></video>
              <div style="background:url(assets/bg.jpg)"></div>
            </div></div>
        """, encoding="utf-8")
        result = _run(html, "#1", "--json")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)[0]["assets"] == [
            "assets/bg.jpg", "input/one.png", "input/poster.jpg"]
