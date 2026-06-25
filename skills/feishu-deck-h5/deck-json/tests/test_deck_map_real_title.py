"""deck-map.py · shows the REAL .title-zh, not stale data.title (2026-06-25).

After a retarget/edit, a slide's `data.title` metadata routinely keeps the OLD
heading while `data.html` already carries the NEW `.title-zh`. deck-map must show
the html heading so pages are identifiable straight from the map — otherwise you
have to render-just-to-find-out-which-page-is-which (a real time sink). Regression
for the inverted-priority bug where data.title was trusted first.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve()
DECK_MAP = HERE.parents[1] / "deck-map.py"


def _run_map(deck: dict) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as f:
        json.dump(deck, f)
        path = f.name
    out = subprocess.run([sys.executable, str(DECK_MAP), path],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout


class DeckMapRealTitle(unittest.TestCase):
    def test_html_title_overrides_stale_metadata(self):
        deck = {"meta": {"title": "T"}, "slides": [{
            "key": "k1", "layout": "raw",
            "data": {
                "title": "STALE OLD HEADING",
                "html": '<div class="header">'
                        '<h2 class="title-zh">REAL NEW HEADING</h2></div>',
            },
        }]}
        out = _run_map(deck)
        self.assertIn("REAL NEW HEADING", out)
        self.assertNotIn("STALE OLD HEADING", out)

    def test_falls_back_to_metadata_when_html_has_no_heading(self):
        deck = {"meta": {"title": "T"}, "slides": [{
            "key": "k1", "layout": "raw",
            "data": {"title": "ONLY METADATA",
                     "html": '<div class="stage">body, no heading</div>'},
        }]}
        out = _run_map(deck)
        self.assertIn("ONLY METADATA", out)


if __name__ == "__main__":
    unittest.main()
