"""Tests for fast-text.py (F-303) — the sub-second pure-copy edit mode.

Dual-writes deck.json + index.html with count==1 asserts on both sides, no
render, no validation. Guardrails are hard: DOM chars refused, ambiguous
anchors refused, JSON-corrupting replacements refused-and-restored.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAST = HERE.parent / "fast-text.py"


def _mk(td, html_text="The quick brown fox jumps."):
    deck = {"version": "1.0",
            "deck": {"title": "t", "author": "a", "date": "2026-06"},
            "slides": [{"key": "k1", "layout": "raw", "screen_label": "01 K",
                        "data": {"html": f'<p class="x">{html_text}</p>'}}]}
    dj = Path(td) / "deck.json"
    dj.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
    ih = Path(td) / "index.html"
    ih.write_text(f'<html><body><div class="slide"><p class="x">{html_text}'
                  f'</p></div></body></html>', encoding="utf-8")
    return dj, ih


def _run(deck, old, new):
    return subprocess.run([sys.executable, str(FAST), str(deck), old, new],
                          capture_output=True, text=True)


class FastText(unittest.TestCase):
    def test_dual_write_happy_path(self):
        with tempfile.TemporaryDirectory() as td:
            dj, ih = _mk(td)
            r = _run(td, "quick brown fox", "slow purple fox")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("slow purple fox", dj.read_text(encoding="utf-8"))
            self.assertIn("slow purple fox", ih.read_text(encoding="utf-8"))
            json.loads(dj.read_text(encoding="utf-8"))   # still valid JSON

    def test_refuses_dom_chars(self):
        with tempfile.TemporaryDirectory() as td:
            dj, ih = _mk(td)
            before = dj.read_bytes()
            r = _run(td, '<p class="x">The', "y")
            self.assertEqual(r.returncode, 2)
            self.assertIn("DOM edit", r.stderr)
            self.assertEqual(dj.read_bytes(), before)    # untouched

    def test_refuses_ambiguous_anchor(self):
        with tempfile.TemporaryDirectory() as td:
            dj, ih = _mk(td, "fox and fox again")
            before = dj.read_bytes()
            r = _run(td, "fox", "wolf")
            self.assertEqual(r.returncode, 2)
            self.assertIn("2×", r.stderr.replace("2x", "2×"))
            self.assertEqual(dj.read_bytes(), before)

    def test_quote_bearing_text_json_escaped(self):
        with tempfile.TemporaryDirectory() as td:
            dj, ih = _mk(td, 'He said "hello" loudly.')
            # index.html holds the raw quotes; deck.json holds \" — the tool
            # must handle both encodings of the SAME logical string.
            r = _run(td, 'said "hello" loudly', 'said "goodbye" loudly')
            self.assertEqual(r.returncode, 0, r.stderr)
            data = json.loads(dj.read_text(encoding="utf-8"))
            self.assertIn('said "goodbye" loudly',
                          data["slides"][0]["data"]["html"])
            self.assertIn('said "goodbye" loudly', ih.read_text(encoding="utf-8"))

    def test_html_mismatch_exits_3_deck_still_updated(self):
        with tempfile.TemporaryDirectory() as td:
            dj, ih = _mk(td)
            # html diverged from deck.json (e.g. an entity-escaped or duplicated
            # rendering) → OLD matches 2× there, so the html side must refuse
            ih.write_text('<p class="x">The quick brown fox jumps. The quick '
                          'brown fox jumps.</p>', encoding="utf-8")
            r = _run(td, "quick brown fox jumps.", "quick brown fox leaps.")
            self.assertEqual(r.returncode, 3, r.stderr)
            self.assertIn("--quick", r.stderr)           # tells how to sync
            self.assertIn("leaps", dj.read_text(encoding="utf-8"))

    def test_overflow_warning_on_much_longer_text(self):
        with tempfile.TemporaryDirectory() as td:
            _mk(td)
            r = _run(td, "The quick brown fox jumps.",
                     "The quick brown fox jumps over the extremely lazy dog "
                     "while reciting poetry.")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("⚠", r.stderr)
            self.assertIn("chars longer", r.stderr)


if __name__ == "__main__":
    unittest.main()
