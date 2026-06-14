"""Scope-aware static gate · the in-scope-error-still-blocks guarantee (diff-1/diff-2).

The render static gate (validate.py --no-visual, render-deck.py step 6) must roll
back index.html and return 4 whenever a static error is present ON A PAGE THE EDIT
TOUCHED — including the per-slide CONTENT rule R05 (banned emoji / '!' / '…' /
'???'), whose messages carry NO "slide N" anchor.

This is the regression lock for the diff-1 hole: any future scope-aware static
DEMOTION (forcing rc→0 for "off-scope" errors) must NOT silently demote an R05
error that the in-scope edit actually introduced. R05 messages are body-wide and
anchor-free, so a naive "slide==None → deck-level → demote" partition would let a
freshly-introduced emoji ship clean. These tests assert the opposite: an in-scope
R05 error BLOCKS (rc 4) and the previously-good index.html is restored.

Pure static gate — R05 is a byte rule, so no Playwright/Chromium is needed and the
test is fast (two small raw-page renders).
"""
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
RENDER = DECK_JSON / "render-deck.py"


def _clean_deck():
    return {
        "version": "1.0",
        "deck": {"title": "scope static gate test", "author": "t",
                 "date": "2026-06"},
        "slides": [
            {"key": "p1", "layout": "raw", "screen_label": "01 First",
             "data": {"html":
                 '<div class="header"><h2 class="title-zh">First Page</h2></div>'
                 '<div class="stage"><p class="body" style="font-size:24px">'
                 'A clean body line on the first page.</p></div>'}},
            {"key": "p2", "layout": "raw", "screen_label": "02 Second",
             "data": {"html":
                 '<div class="header"><h2 class="title-zh">Second Page</h2></div>'
                 '<div class="stage"><p class="body" style="font-size:24px">'
                 'A clean body line on the second page.</p></div>'}},
        ],
    }


def _emoji_html(label):
    return (f'<div class="header"><h2 class="title-zh">{label}</h2></div>'
            f'<div class="stage"><p class="body" style="font-size:24px">'
            f'A line that now carries a banned emoji \U0001f680 here.</p></div>')


def _render(deck_path, out_dir, *flags):
    env = dict(os.environ)
    env["DECK_LOG_NO_AUTOSNAP"] = "1"
    return subprocess.run(
        [sys.executable, str(RENDER), str(deck_path), str(out_dir) + "/", *flags],
        capture_output=True, text=True, env=env)


class ScopeStaticGate(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.out = self.tmp / "out"
        self.out.mkdir(parents=True, exist_ok=True)
        self.deck_path = self.tmp / "deck.json"
        self.index = self.out / "index.html"

    def tearDown(self):
        self._td.cleanup()

    def _write_deck(self, deck):
        self.deck_path.write_text(json.dumps(deck, ensure_ascii=False),
                                  encoding="utf-8")

    def _seed_good_index(self):
        """First render the clean deck so a previously-good index.html exists for
        the rollback assertion."""
        self._write_deck(_clean_deck())
        r = _render(self.deck_path, self.out)
        self.assertEqual(r.returncode, 0,
                         "clean deck should pass the static gate\n" + r.stderr)
        return self.index.read_text(encoding="utf-8")

    def test_in_scope_r05_emoji_blocks_and_rolls_back(self):
        good = self._seed_good_index()
        # Introduce an R05 emoji on the IN-SCOPE page (p2 = frame 2) and re-render
        # scoped to that page only.
        deck = _clean_deck()
        deck["slides"][1]["data"]["html"] = _emoji_html("Second Page")
        self._write_deck(deck)
        r = _render(self.deck_path, self.out, "--scope", "2")
        self.assertEqual(r.returncode, 4,
                         "an in-scope R05 emoji must BLOCK (rc 4), never be "
                         "demoted as deck-level\n" + r.stdout + r.stderr)
        self.assertIn("R05", r.stdout + r.stderr)
        # F-269 rollback: the previously-good index.html must be restored, so a
        # gate-rejected render never lands on disk.
        self.assertEqual(self.index.read_text(encoding="utf-8"), good,
                         "rejected scoped render must roll index.html back to the "
                         "previously-good version")

    def test_in_scope_r05_emoji_blocks_on_full_render_too(self):
        good = self._seed_good_index()
        deck = _clean_deck()
        deck["slides"][1]["data"]["html"] = _emoji_html("Second Page")
        self._write_deck(deck)
        r = _render(self.deck_path, self.out)   # full (unscoped) render
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn("R05", r.stdout + r.stderr)
        self.assertEqual(self.index.read_text(encoding="utf-8"), good)


if __name__ == "__main__":
    unittest.main()
