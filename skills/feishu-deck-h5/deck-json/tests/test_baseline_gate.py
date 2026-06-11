"""Tests for the F-302 baseline-aware visual gate (new-vs-pre-existing diff).

A page that shipped via an accept-risk render (DECK_ALLOW_VIS_ERRORS=1) carries
findings that are NOT a later edit's fault. render-deck persists the shipped
findings as fingerprints in output/validate-findings.json; a `--scope` re-render
then blocks ONLY on findings absent from that baseline:

  1. ship with DECK_ALLOW_VIS_ERRORS=1   → baseline file written (fingerprints)
  2. text edit + scoped re-render        → all findings pre-existing → NOT blocked
  3. same render with --strict-baseline  → blocked (old hard behavior)

Runs REAL renders under a throwaway runs/<ts>/output/ dir (the gate is
path-gated to the canonical runs layout), so it needs Playwright; skipped
cleanly when the engine is unavailable. ~3 renders ≈ tens of seconds — slow
but it exercises the actual gate path end-to-end.
"""
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
RENDER = DECK_JSON / "render-deck.py"
SKILL_ROOT = DECK_JSON.parent          # skills/feishu-deck-h5
REPO_ROOT = SKILL_ROOT.parent.parent   # repo root (runs/ lives here)


def _chromium_ok():
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:
        return False
    return True


_DECK = {
    "version": "1.0",
    "deck": {"title": "baseline gate test", "author": "t", "date": "2026-06"},
    "slides": [{
        "key": "victim", "layout": "raw", "screen_label": "01 Victim",
        "data": {"html":
            '<div class="header"><h2 class="title-zh">Baseline Gate Test Page'
            '</h2></div>'
            '<div class="stage" style="position:absolute;top:220px;left:73px;'
            'right:73px;bottom:120px;display:flex;flex-direction:column;'
            'gap:24px;">'
            '<p style="font-size:24px;color:#fff;margin:0">A healthy body line '
            'at the proper floor size for projector reading.</p>'
            '<p class="smalltext" style="font-size:18px;color:#fff;margin:0">'
            'This sentence is deliberately below the body floor so the visual '
            'gate fires an error.</p></div>'}}],
}


@unittest.skipUnless(_chromium_ok(), "playwright/chromium unavailable")
class BaselineGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_dir = REPO_ROOT / "runs" / "00000000-000000-baseline-gate-test"
        cls.out = cls.run_dir / "output"
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.deck_path = cls.out / "deck.json"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.run_dir, ignore_errors=True)

    def _write_deck(self, mutate=None):
        deck = json.loads(json.dumps(_DECK))
        if mutate:
            mutate(deck)
        self.deck_path.write_text(json.dumps(deck, ensure_ascii=False),
                                  encoding="utf-8")

    def _render(self, *extra, env_extra=None):
        env = dict(os.environ, DECK_LOG_NO_AUTOSNAP="1")
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable, str(RENDER), str(self.deck_path),
             str(self.out) + "/", "--scope", "1", *extra],
            capture_output=True, text=True, env=env)

    def test_full_lifecycle(self):
        baseline = self.out / "validate-findings.json"

        # 0. no baseline → scoped render with errors BLOCKS (old behavior)
        self._write_deck()
        r0 = self._render()
        self.assertEqual(r0.returncode, 4, r0.stderr[-800:])
        self.assertIn("BLOCKING", r0.stderr)
        self.assertFalse(baseline.exists())   # blocked render writes no baseline

        # 1. accept-risk ship → baseline written with the victim's fingerprints
        r1 = self._render(env_extra={"DECK_ALLOW_VIS_ERRORS": "1"})
        self.assertEqual(r1.returncode, 0, r1.stderr[-800:])
        self.assertTrue(baseline.exists())
        fps = json.loads(baseline.read_text(encoding="utf-8"))["fingerprints"]
        self.assertTrue(any(fp[0] == "R-VIS-BODY-FLOOR" and fp[1] == "victim"
                            for fp in fps), fps)

        # 2. text edit (error untouched) → pre-existing demotion, ships w/o env
        self._write_deck(lambda d: d["slides"][0]["data"].__setitem__(
            "html", d["slides"][0]["data"]["html"].replace(
                "A healthy body line", "An EDITED healthy body line")))
        r2 = self._render()
        self.assertEqual(r2.returncode, 0, r2.stderr[-800:])
        self.assertIn("PRE-EXISTING", r2.stderr)
        self.assertIn("baseline(", r2.stderr)          # GATE-COVERAGE marker

        # 3. --strict-baseline → blocked again despite the baseline
        r3 = self._render("--strict-baseline")
        self.assertEqual(r3.returncode, 4, r3.stderr[-800:])
        self.assertIn("BLOCKING", r3.stderr)


if __name__ == "__main__":
    unittest.main()
