import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "lift-swap.py"

SRC_HTML = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<div class="deck">
<div class="slide-frame">
<div class="slide" data-layout="raw" data-slide-key="src-page" data-screen-label="01 Source">
<div class="stage"><h1>Source Lifted Body</h1></div>
</div>
</div>
<div class="slide-frame">
<div class="slide" data-layout="raw" data-slide-key="second-page" data-screen-label="02 Second">
<div class="stage"><h1>Second</h1></div>
</div>
</div>
</div>
</body></html>
"""


def _target_deck():
    return {
        "version": "1.0",
        "deck": {"title": "target", "author": "a", "date": "2026-06"},
        "slides": [
            {"key": "target-one", "layout": "raw", "screen_label": "01 Target",
             "data": {"html": '<div class="stage"><h1>Old One</h1></div>'}},
            {"key": "target-two", "layout": "raw", "screen_label": "02 Target Two",
             "data": {"html": '<div class="stage"><h1>Old Two</h1></div>'}},
        ],
    }


class LiftSwapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lift-swap-test-"))
        self.src = self.tmp / "src"
        self.dst = self.tmp / "dst"
        self.src.mkdir()
        self.dst.mkdir()
        (self.src / "index.html").write_text(SRC_HTML, encoding="utf-8")
        (self.dst / "deck.json").write_text(
            json.dumps(_target_deck(), ensure_ascii=False), encoding="utf-8")
        # The wrapper accepts target index.html refs and resolves sibling deck.json.
        (self.dst / "index.html").write_text("<html></html>", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, source_ref: str, target_ref: str, *extra):
        return subprocess.run(
            [sys.executable, str(TOOL), source_ref, target_ref, *extra],
            capture_output=True, text=True,
        )

    def _deck(self):
        return json.loads((self.dst / "deck.json").read_text(encoding="utf-8"))

    def test_file_url_hash_swap_preserves_target_key_order_and_count(self):
        proc = self._run(
            (self.src / "index.html").resolve().as_uri() + "#1",
            (self.dst / "index.html").resolve().as_uri() + "#1",
        )
        self.assertEqual(proc.returncode, 0, f"{proc.stdout}\n{proc.stderr}")
        deck = self._deck()
        self.assertEqual([s["key"] for s in deck["slides"]],
                         ["target-one", "target-two"])
        self.assertEqual(deck["slides"][0]["screen_label"], "01 Target")
        self.assertIn("Source Lifted Body", deck["slides"][0]["data"]["html"])
        self.assertIn("Old Two", deck["slides"][1]["data"]["html"])

    def test_source_key_and_target_key_fragments_work(self):
        proc = self._run(
            str(self.src / "index.html") + "#second-page",
            str(self.dst / "deck.json") + "#target-two",
        )
        self.assertEqual(proc.returncode, 0, f"{proc.stdout}\n{proc.stderr}")
        deck = self._deck()
        self.assertEqual([s["key"] for s in deck["slides"]],
                         ["target-one", "target-two"])
        self.assertIn("Second", deck["slides"][1]["data"]["html"])
        self.assertIn("Old One", deck["slides"][0]["data"]["html"])

    def test_bad_target_page_refuses_without_mutating_deck(self):
        before = (self.dst / "deck.json").read_text(encoding="utf-8")
        proc = self._run(
            str(self.src / "index.html") + "#1",
            str(self.dst / "index.html") + "#99",
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("out of range", proc.stderr)
        after = (self.dst / "deck.json").read_text(encoding="utf-8")
        self.assertEqual(after, before)

    def test_dry_run_does_not_mutate_deck(self):
        before = (self.dst / "deck.json").read_text(encoding="utf-8")
        proc = self._run(
            str(self.src / "index.html") + "#1",
            str(self.dst / "index.html") + "#1",
            "--dry-run",
        )
        self.assertEqual(proc.returncode, 0, f"{proc.stdout}\n{proc.stderr}")
        self.assertIn("dry-run", proc.stdout)
        after = (self.dst / "deck.json").read_text(encoding="utf-8")
        self.assertEqual(after, before)
