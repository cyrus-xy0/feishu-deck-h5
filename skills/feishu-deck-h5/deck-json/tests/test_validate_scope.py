"""F-336 · validate-deck.py --scope report filter.

A scoped check-only review must surface findings on the locked page(s) + any
deck-level finding (no slides[i] anchor), and DROP pre-existing off-scope
findings — while all rules still RUN whole-deck (a cross-slide problem like a
duplicate key is still caught, just attributed to its own slide path).

Subprocess-level test (mirrors how render-deck / check-only invoke the CLI).
"""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
VALIDATE_DECK = HERE.parent / "validate-deck.py"


def _deck():
    # slide html < minLength(10) → a deterministic per-slide error on EVERY page;
    # a duplicate key → a cross-slide R-KEY anchored to the 2nd occurrence (page 2);
    # an unknown top-level property → a deck-level error (slide=None).
    return {
        "version": "1.0",
        "title": "t",                       # unknown property → deck-level error
        "deck": {"title": "T"},
        "slides": [
            {"key": "a", "layout": "raw", "data": {"html": "<p>1</p>"}},
            {"key": "a", "layout": "raw", "data": {"html": "<p>2</p>"}},
            {"key": "b", "layout": "raw", "data": {"html": "<p>3</p>"}},
        ],
    }


class ValidateDeckScopeTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.deck = Path(self._td.name) / "deck.json"
        self.deck.write_text(json.dumps(_deck()), encoding="utf-8")

    def tearDown(self):
        self._td.cleanup()

    def _json(self, *extra):
        r = subprocess.run(
            [sys.executable, str(VALIDATE_DECK), str(self.deck), "--json", *extra],
            capture_output=True, text=True)
        return json.loads(r.stdout)

    def test_full_report_has_all_findings(self):
        d = self._json()
        slides = sorted(e["slide"] for e in d["errors"] if e["slide"] is not None)
        self.assertEqual(slides, [0, 1, 1, 2])           # per-slide + R-KEY on idx1
        self.assertTrue(any(e["slide"] is None for e in d["errors"]))  # deck-level

    def test_scope_page1_drops_offscope_keeps_decklevel(self):
        d = self._json("--scope", "1")
        # page 1 = slide idx 0; keep its minLength + the deck-level finding only
        slides = [e["slide"] for e in d["errors"]]
        self.assertIn(0, slides)
        self.assertIn(None, slides)                      # deck-level always kept
        self.assertNotIn(1, slides)                      # off-scope dropped
        self.assertNotIn(2, slides)

    def test_scope_page2_keeps_its_findings_including_cross_slide_rkey(self):
        d = self._json("--scope", "2")
        slides = [e["slide"] for e in d["errors"]]
        self.assertEqual(slides.count(1), 2)             # minLength + R-KEY on idx1
        self.assertIn(None, slides)                      # deck-level kept
        self.assertNotIn(0, slides)
        self.assertNotIn(2, slides)

    def test_scope_by_key(self):
        d = self._json("--scope", "b")                   # key 'b' = page 3 = idx 2
        slides = [e["slide"] for e in d["errors"]]
        self.assertIn(2, slides)
        self.assertNotIn(0, slides)
        self.assertNotIn(1, slides)

    def test_bad_scope_token_is_a_hard_error(self):
        r = subprocess.run(
            [sys.executable, str(VALIDATE_DECK), str(self.deck), "--scope", "99"],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--scope", r.stderr)


if __name__ == "__main__":
    unittest.main()
