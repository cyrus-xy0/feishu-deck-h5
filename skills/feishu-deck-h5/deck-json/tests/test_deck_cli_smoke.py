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


class DeckCliPasteDriftTest(unittest.TestCase):
    """`paste` must (a) copy a prototypes/<demo>.html DIRECT-FILE iframe body
    (old regex only matched prototypes/<dir>/ subdirs → blank iframe) and
    (b) remap retired framework CSS vars (var(--fs-accent4)→var(--fs-teal)) so an
    old slide doesn't render-fail on R-CSSVAR after paste. (P1, 2026-06-02)"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="deck-cli-paste-test-"))
        self.src_dir = self.tmp / "src"
        (self.src_dir / "prototypes").mkdir(parents=True)
        (self.src_dir / "prototypes" / "demo.html").write_text(
            "<!doctype html><body>demo</body>", encoding="utf-8")
        src_deck = {
            "version": "1.0",
            "deck": {"title": "s", "author": "a", "date": "2026-06"},
            "slides": [{
                "key": "src-raw", "layout": "raw", "accent": "blue",
                "data": {"html": '<div class="lead">'
                                 '<b style="color:var(--fs-accent4)">x</b></div>'
                                 '<iframe src="prototypes/demo.html"></iframe>'},
            }],
        }
        (self.src_dir / "deck.json").write_text(json.dumps(src_deck), encoding="utf-8")
        self.dst_dir = self.tmp / "dst"
        self.dst_dir.mkdir()
        self.dst = self.dst_dir / "deck.json"
        shutil.copy(SAMPLE, self.dst)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _paste(self):
        return subprocess.run(
            [sys.executable, str(CLI), str(self.dst), "--yes",
             "paste", "--from", str(self.src_dir / "deck.json"), "--key", "src-raw"],
            capture_output=True, text=True,
        )

    def test_prototype_direct_file_copied(self):
        proc = self._paste()
        self.assertEqual(proc.returncode, 0,
                         f"paste failed: {proc.stderr}\n{proc.stdout}")
        self.assertTrue((self.dst_dir / "prototypes" / "demo.html").is_file(),
                        "prototypes/demo.html direct-file iframe body was not "
                        "copied by paste (blank iframe).")

    def test_retired_var_remapped(self):
        proc = self._paste()
        self.assertEqual(proc.returncode, 0,
                         f"paste failed: {proc.stderr}\n{proc.stdout}")
        deck = json.loads(self.dst.read_text(encoding="utf-8"))
        pasted = [s for s in deck["slides"] if s.get("key") == "src-raw"][0]
        html = pasted["data"]["html"]
        self.assertNotIn("var(--fs-accent4)", html,
                         "paste did not remap retired var(--fs-accent4).")
        self.assertIn("var(--fs-teal)", html,
                      "var(--fs-accent4) should map to var(--fs-teal).")


if __name__ == "__main__":
    unittest.main()
