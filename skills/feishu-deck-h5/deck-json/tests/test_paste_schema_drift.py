"""F-373 unit guard: `deck-cli paste` warns when a source page is RENDERED as a
schema layout (data-layout=content-2col / 3up / stats / …) while its deck.json
says `layout: raw`. The framework `[data-layout=X]` CSS (e.g. `.grid{display:grid}`)
does NOT follow a raw paste, so the layout silently collapses / overflows on
render — the 2026-06-22 ai-into-org feiling-product retrospective (+508px).

Complements F-371 (which catches CSS dropped from the source <head>); this catches
CSS dropped WITH the data-layout. Pages already `--shake`-inlined carry an
`AUTO-INLINED from framework` marker and are skipped (self-contained). Advisory
only — paste still succeeds.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON_DIR = HERE.parents[0]                       # deck-json/
DECK_CLI = DECK_JSON_DIR / "deck-cli.py"

RAW_SLIDE_HTML = (
    '<div class="slide" data-layout="raw" data-slide-key="mypage">'
    '<div class="wordmark">飞书</div>'
    '<div class="header"><h2 class="title-zh">测试页面标题在这里</h2></div>'
    '<div class="stage"><div class="grid">'
    '<div class="col-text">这是左栏的一段正文内容用于测试布局是否塌陷</div>'
    '<div class="col-visual">这是右栏的视觉占位内容用于测试</div>'
    '</div></div></div>'
)


def _src_deck(tmp: Path, *, html: str = RAW_SLIDE_HTML, custom_css: str = "") -> Path:
    """A source deck whose 'mypage' slide is layout:raw in deck.json."""
    deck = {"meta": {"title": "Src", "author": "A", "date": "2026-01-01"},
            "slides": [{"key": "mypage", "layout": "raw", "screen_label": "01",
                        "data": {"html": html}, "custom_css": custom_css}]}
    p = tmp / "deck.json"
    p.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
    return p


def _src_index(tmp: Path, data_layout: str) -> None:
    """The sibling index.html that RENDERS 'mypage' with the given data-layout."""
    html = ('<!doctype html><html><body><div class="slide-frame">'
            '<div class="slide" data-layout="' + data_layout + '" '
            'data-slide-key="mypage">x</div></div></body></html>')
    (tmp / "index.html").write_text(html, encoding="utf-8")


def _fresh_dst(tmp: Path) -> Path:
    deck = tmp / "dst.json"
    subprocess.run([sys.executable, str(DECK_CLI), str(deck), "new-deck",
                    "--title", "T", "--author", "A", "--date", "2026-01-01"],
                   capture_output=True, text=True, check=True)
    return deck


def _paste(dst: Path, src: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(DECK_CLI), "--yes", str(dst), "paste",
         "--from", str(src), "--key", "mypage"],
        capture_output=True, text=True)


class PasteSchemaDriftGuard(unittest.TestCase):
    def test_warns_when_render_is_schema_and_not_inlined(self):
        tmp = Path(tempfile.mkdtemp())
        src = _src_deck(tmp)
        _src_index(tmp, "content-2col")
        r = _paste(_fresh_dst(tmp), src)
        self.assertEqual(r.returncode, 0, r.stderr)        # advisory — still succeeds
        self.assertIn("raw-ified-schema drift", r.stderr)
        self.assertIn("content-2col", r.stderr)
        self.assertIn("--shake", r.stderr)

    def test_silent_when_render_is_raw(self):
        tmp = Path(tempfile.mkdtemp())
        src = _src_deck(tmp)
        _src_index(tmp, "raw")
        r = _paste(_fresh_dst(tmp), src)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("raw-ified-schema drift", r.stderr)

    def test_silent_when_shake_inlined(self):
        tmp = Path(tempfile.mkdtemp())
        # render IS schema, but the slide carries the --shake marker → self-contained
        html = "<style>/* AUTO-INLINED from framework rules */</style>" + RAW_SLIDE_HTML
        src = _src_deck(tmp, html=html)
        _src_index(tmp, "content-3up")
        r = _paste(_fresh_dst(tmp), src)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("raw-ified-schema drift", r.stderr)

    def test_silent_when_no_source_index(self):
        tmp = Path(tempfile.mkdtemp())
        src = _src_deck(tmp)                                # no index.html written
        r = _paste(_fresh_dst(tmp), src)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("raw-ified-schema drift", r.stderr)


if __name__ == "__main__":
    unittest.main()
