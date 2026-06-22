"""paste — framework shared-pool fallback for `assets/shared/<pool>/<file>`.

A pasted slide that references a framework shared asset the SOURCE deck never
localized (linked-mode / hand-assembled source) must still land the file in the
target: paste falls back to the framework pool `<skill>/assets/shared/` instead
of flagging a real asset `missing` and rendering a broken image. The target deck
rarely pre-populates the pool. Postmortem 2026-06-22 (lifted digital-employee
avatars: refs lived in the head — drift — and even once recovered, a source
without a local copy would have left them missing without this fallback).
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
FRAMEWORK_SHARED = DECK_JSON.parent / "assets" / "shared"
# a stable, committed framework shared asset used as the fallback probe
PROBE_REF = "mydigitalemployee/睿睿.png"


class PasteSharedFallbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="paste-shared-fb-"))
        self.src = self.tmp / "src"
        self.dst = self.tmp / "dst"
        self.src.mkdir(parents=True)
        self.dst.mkdir(parents=True)
        # source slide references a framework shared asset in its custom_css, but
        # the source deck has NO local assets/shared/ copy of it (linked-mode src).
        src_deck = {
            "version": "1.0", "deck": {"title": "s"},
            "slides": [{"key": "p", "layout": "raw",
                        "custom_css": f".a{{background-image:url('assets/shared/{PROBE_REF}')}}",
                        "data": {"html": '<div class="a"></div>'}}],
        }
        (self.src / "deck.json").write_text(
            json.dumps(src_deck, ensure_ascii=False), encoding="utf-8")
        (self.dst / "deck.json").write_text(json.dumps(
            {"version": "1.0", "deck": {"title": "d"},
             "slides": [{"key": "keep", "layout": "raw", "data": {"html": "<div>k</div>"}}]},
            ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _paste(self):
        return subprocess.run(
            [sys.executable, str(CLI), str(self.dst / "deck.json"), "--yes",
             "paste", "--from", str(self.src / "deck.json"), "--key", "p", "2"],
            capture_output=True, text=True)

    @unittest.skipUnless((FRAMEWORK_SHARED / PROBE_REF).is_file(),
                         f"framework probe asset missing: {PROBE_REF}")
    def test_falls_back_to_framework_pool(self):
        proc = self._paste()
        self.assertEqual(proc.returncode, 0, f"paste failed:\n{proc.stderr}\n{proc.stdout}")
        landed = self.dst / "assets" / "shared" / PROBE_REF
        self.assertTrue(landed.is_file(),
                        "framework shared asset not copied via fallback → broken image in target")

    @unittest.skipUnless((FRAMEWORK_SHARED / PROBE_REF).is_file(),
                         f"framework probe asset missing: {PROBE_REF}")
    def test_source_local_copy_still_preferred(self):
        # When the source DID localize the asset, that copy is used (existing
        # behavior must be preserved — fallback only kicks in when src lacks it).
        local = self.src / "assets" / "shared" / PROBE_REF
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(b"SRCLOCALMARKER")
        proc = self._paste()
        self.assertEqual(proc.returncode, 0, f"paste failed:\n{proc.stderr}\n{proc.stdout}")
        landed = self.dst / "assets" / "shared" / PROBE_REF
        self.assertEqual(landed.read_bytes(), b"SRCLOCALMARKER",
                         "source-local shared copy must win over the framework pool")

    def test_truly_missing_shared_is_flagged_not_fatal(self):
        # A shared ref in NEITHER source nor framework pool must not crash paste;
        # it is reported missing, not copied, and paste still succeeds.
        deck = json.loads((self.src / "deck.json").read_text(encoding="utf-8"))
        deck["slides"][0]["custom_css"] = \
            ".a{background-image:url('assets/shared/zzz-nonexistent/none.png')}"
        (self.src / "deck.json").write_text(
            json.dumps(deck, ensure_ascii=False), encoding="utf-8")
        proc = self._paste()
        self.assertEqual(proc.returncode, 0,
                         f"paste must tolerate a truly-missing shared ref:\n{proc.stderr}")
        self.assertFalse(
            (self.dst / "assets" / "shared" / "zzz-nonexistent" / "none.png").exists())


if __name__ == "__main__":
    unittest.main()
