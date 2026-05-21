"""Smoke-test deck-cli.py operations on a copy of sample-deck.json:
- set: scalar change persists
- set: invalid schema → rolls back via .bak
- reorder: position changes
- clone: new slide added with unique key

Doesn't try to exhaustively cover all 14 subcommands — just the high-value
contract: backup → write → validate → rollback works.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
CLI = DECK_JSON / "deck-cli.py"
SAMPLE = DECK_JSON / "examples" / "sample-deck.json"


class DeckCliSmokeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="deck-cli-test-")
        self.deck = Path(self.tmp) / "deck.json"
        shutil.copy(SAMPLE, self.deck)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args) -> tuple[int, str, str]:
        proc = subprocess.run(
            [sys.executable, str(CLI), str(self.deck), "--yes", *args],
            capture_output=True, text=True,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def _load(self) -> dict:
        return json.loads(self.deck.read_text(encoding="utf-8"))

    def test_set_scalar_persists(self):
        rc, out, err = self._run("set", "slides.0.data.title", "NEW TITLE")
        self.assertEqual(rc, 0, f"set failed: {err}")
        self.assertEqual(self._load()["slides"][0]["data"]["title"], "NEW TITLE")

    def test_set_invalid_enum_rolls_back(self):
        # accent enum doesn't include "cyan" (R49 encoded in schema) — set
        # should fail + rollback to .bak
        before = self._load()["slides"][0]
        rc, out, err = self._run("set-accent", before["key"], "cyan")
        self.assertNotEqual(rc, 0, "set-accent cyan should fail (R49)")
        after = self._load()["slides"][0]
        self.assertEqual(after.get("accent"), before.get("accent"),
                         "rollback should have preserved original accent")

    def test_reorder_changes_position(self):
        before = [s["key"] for s in self._load()["slides"]]
        rc, out, err = self._run("reorder", "1", "3")  # 1-indexed
        self.assertEqual(rc, 0, f"reorder failed: {err}")
        after = [s["key"] for s in self._load()["slides"]]
        self.assertEqual(after[2], before[0], "slide 1 should now be at position 3")

    def test_clone_creates_new_key(self):
        src = self._load()["slides"][2]["key"]
        rc, out, err = self._run("clone", src, f"{src}-copy")
        self.assertEqual(rc, 0, f"clone failed: {err}")
        keys = [s["key"] for s in self._load()["slides"]]
        self.assertIn(f"{src}-copy", keys)
        # original still present
        self.assertIn(src, keys)


if __name__ == "__main__":
    unittest.main()
