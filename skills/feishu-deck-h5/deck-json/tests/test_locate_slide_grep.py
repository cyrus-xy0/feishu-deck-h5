"""Tests for locate-slide.py --grep (F-301) — excerpting inside slide bodies.

A raw slide's data.html can run to 100s of KB; finding one element must not
require printing the whole thing. --grep searches the selected slides'
data.html + custom_css and prints source + offset + ±context per hit.

Also smoke-tests the plain locator (no prior coverage existed).
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCATE = HERE.parent / "locate-slide.py"


def _deck(td):
    big_html = ('<div class="header"><h2 class="title-zh">Map</h2></div>'
                '<div class="stage">' + ('<p class="filler">x</p>' * 2000) +
                '<span class="eng-name">Innovation</span></div>')
    deck = {"version": "1.0",
            "deck": {"title": "t", "author": "a", "date": "2026-06"},
            "slides": [
                {"key": "alpha", "layout": "raw", "screen_label": "01 Alpha",
                 "data": {"html": '<div class="tag">TIER ONE</div>'},
                 "custom_css": ".slide[data-slide-key=\"alpha\"] .tag{color:#fff}"},
                {"key": "four-engines", "layout": "raw", "screen_label": "02 Map",
                 "data": {"html": big_html},
                 "custom_css": ".eng-name{font-size:28px}"},
            ]}
    p = Path(td) / "deck.json"
    p.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
    return p


def _run(*args):
    return subprocess.run([sys.executable, str(LOCATE), *map(str, args)],
                          capture_output=True, text=True)


class LocateGrep(unittest.TestCase):
    def test_grep_one_slide_html_and_css(self):
        with tempfile.TemporaryDirectory() as td:
            deck = _deck(td)
            r = _run(deck, "four-engines", "--grep", "eng-name", "--context", "30")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("key=four-engines", r.stdout)
            self.assertIn("[html @", r.stdout)
            self.assertIn("[custom_css @", r.stdout)
            # the excerpt is short context, not the whole 30KB+ body
            self.assertLess(len(r.stdout), 2000)

    def test_grep_all_slides(self):
        with tempfile.TemporaryDirectory() as td:
            r = _run(_deck(td), "all", "--grep", "TIER")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("key=alpha", r.stdout)
            self.assertNotIn("four-engines", r.stdout)

    def test_grep_no_hit_exits_4(self):
        with tempfile.TemporaryDirectory() as td:
            r = _run(_deck(td), "all", "--grep", "NOPE-NOT-THERE")
            self.assertEqual(r.returncode, 4)
            self.assertIn("0 hits", r.stderr)

    def test_grep_invalid_regex_degrades_to_literal(self):
        with tempfile.TemporaryDirectory() as td:
            big = _deck(td)
            # "[html" style pattern: '(' alone is an invalid regex → literal
            r = _run(big, "alpha", "--grep", "TIER (")
            self.assertEqual(r.returncode, 4)  # literal "TIER (" not present
            r2 = _run(big, "alpha", "--grep", "TIER ONE")
            self.assertEqual(r2.returncode, 0)

    def test_grep_selects_by_frame_index(self):
        with tempfile.TemporaryDirectory() as td:
            r = _run(_deck(td), "2", "--grep", "Innovation")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Innovation", r.stdout)

    def test_plain_locate_still_works(self):
        with tempfile.TemporaryDirectory() as td:
            r = _run(_deck(td), "four-engines")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("#2", r.stdout)
            self.assertIn("layout=raw", r.stdout)


if __name__ == "__main__":
    unittest.main()
