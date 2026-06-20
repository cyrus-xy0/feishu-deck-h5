"""F-354 · render-deck.py --shoot (one-pass verify).

`--scope N --shoot` should, after the render, run the visual gate on the scoped
page(s) + screenshot each — collapsing the agent's edit→check loop (render +
validate + shoot-page = 3 round-trips) into one command. Here we lock the wiring:
the needs-`--scope` guard, and that a scoped --shoot emits the per-page SHOOT
section. The chromium-dependent artifacts (PNG / live findings) degrade
gracefully and are covered by manual e2e — this stays fast + browser-free.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
RENDER = HERE.parent / "render-deck.py"


def _deck():
    return {
        "version": "1.0",
        "deck": {"title": "t", "author": "a", "date": "2026-06"},
        "slides": [
            {"key": "c", "layout": "cover", "accent": "blue",
             "data": {"title": "T", "author": "a", "date": "2026-06"}},
            {"key": "r", "layout": "raw",
             "data": {"html": "<div class=\"header\"><h2 class=\"title-zh\">R</h2></div>"
                              "<div class=\"stage\"><p class=\"body\" "
                              "style=\"font-size:24px;color:#fff\">body copy here</p></div>"}},
        ],
    }


class RenderShootTest(unittest.TestCase):
    def _run(self, *extra):
        self._td = tempfile.TemporaryDirectory()
        d = Path(self._td.name) / "deck.json"
        d.write_text(json.dumps(_deck(), ensure_ascii=False), encoding="utf-8")
        out = Path(self._td.name) / "out"
        out.mkdir()
        r = subprocess.run([sys.executable, str(RENDER), str(d), str(out), *extra],
                           capture_output=True, text=True)
        return r

    def test_shoot_without_scope_warns_and_is_noop(self):
        r = self._run("--shoot")
        blob = r.stdout + r.stderr
        self.assertIn("--shoot needs --scope", blob, blob[-800:])
        self.assertNotIn("SHOOT · page", blob)

    def test_shoot_scoped_emits_verify_section(self):
        r = self._run("--scope", "1", "--shoot")
        blob = r.stdout + r.stderr
        self.assertEqual(r.returncode, 0, blob[-800:])
        self.assertIn("SHOOT · page 1", blob)


if __name__ == "__main__":
    unittest.main()
