"""F-334 · --renumber / structural-insert participates in auto-scope.

The reported regression: adding ONE page to a big deck and running
`render-deck.py --renumber` ran the FULL-deck gate, which then BLOCKED + rolled
back the freshly-rendered index.html because of PRE-EXISTING errors on unrelated
pages. Root cause cluster (all fixed here):

  1. an insert changed the slide-key list → `_auto_scope_pages` short-circuited
     to a full pass via an order-sensitive `pk != ck` guard;
  2. `--renumber` was on the auto-scope DISABLE list → scope_pages stayed empty
     → F-319's scope-aware demotion never engaged;
  3. screen_label was inside the per-slide content hash → a renumber marked
     every shifted page "dirty".

After the fix, `--renumber` (or a bare insert) scopes the gate to the
genuinely-new page; pre-existing out-of-scope errors are demoted (F-319/F-302),
the new page is NOT rolled back, and `--final` still forces the whole-deck gate.

The pure-helper diff logic is covered cheaply in test_auto_scope.py. This file
runs a REAL render under a throwaway runs/<ts>/output/ dir (the gate is
path-gated to that layout) with a pre-existing visual error, so it needs
Playwright; it skips cleanly when the engine is unavailable.
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
REPO_ROOT = DECK_JSON.parent.parent.parent   # repo root (runs/ lives here)


def _chromium_ok():
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:
        return False
    return True


def _victim_html():
    # An 18px body line trips R-VIS-BODY-FLOOR — a reliable PRE-EXISTING error
    # on the page we will NOT scope to.
    return (
        '<div class="header"><h2 class="title-zh">Pre-existing Error Page'
        '</h2></div>'
        '<div class="stage" style="position:absolute;top:220px;left:73px;'
        'right:73px;bottom:120px;display:flex;flex-direction:column;gap:24px;">'
        '<p style="font-size:24px;color:#fff;margin:0">A healthy body line at '
        'the proper floor size for projector reading.</p>'
        '<p style="font-size:18px;color:#fff;margin:0">This sentence is '
        'deliberately below the body floor so the visual gate fires.</p></div>')


def _clean_html():
    return (
        '<div class="header"><h2 class="title-zh">Freshly Inserted Clean Page'
        '</h2></div>'
        '<div class="stage" style="position:absolute;top:220px;left:73px;'
        'right:73px;bottom:120px;display:flex;flex-direction:column;gap:24px;">'
        '<p style="font-size:24px;color:#fff;margin:0">This inserted page is '
        'clean and sits comfortably above the body floor for reading.</p>'
        '</div>')


def _deck(slides):
    return {"version": "1.0",
            "deck": {"title": "renumber scope gate", "author": "t",
                     "date": "2026-06"},
            "slides": slides}


@unittest.skipUnless(_chromium_ok(), "playwright/chromium unavailable")
class RenumberScopeGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.run_dir = REPO_ROOT / "runs" / "00000000-000000-renumber-scope-gate"
        cls.out = cls.run_dir / "output"
        cls.out.mkdir(parents=True, exist_ok=True)
        cls.deck_path = cls.out / "deck.json"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.run_dir, ignore_errors=True)

    def _write(self, deck):
        self.deck_path.write_text(json.dumps(deck, ensure_ascii=False),
                                  encoding="utf-8")

    def _render(self, *extra):
        env = dict(os.environ, DECK_LOG_NO_AUTOSNAP="1")
        return subprocess.run(
            [sys.executable, str(RENDER), str(self.deck_path),
             str(self.out) + "/", *extra],
            capture_output=True, text=True, env=env)

    def test_insert_plus_renumber_scopes_and_does_not_rollback(self):
        index = self.out / "index.html"

        # 0. ship the 1-page deck that has a pre-existing visual error (accept
        #    risk) → success writes BOTH the .slide-hashes.json sidecar AND the
        #    validate-findings.json baseline.
        self._write(_deck([{"key": "victim", "layout": "raw",
                            "screen_label": "01 Victim",
                            "data": {"html": _victim_html()}}]))
        env_extra = dict(os.environ, DECK_LOG_NO_AUTOSNAP="1",
                         DECK_ALLOW_VIS_ERRORS="1")
        r0 = subprocess.run(
            [sys.executable, str(RENDER), str(self.deck_path),
             str(self.out) + "/"], capture_output=True, text=True,
            env=env_extra)
        self.assertEqual(r0.returncode, 0, r0.stderr[-800:])
        self.assertTrue((self.out / ".slide-hashes.json").exists())

        # 1. INSERT a clean page at the end AND run --renumber (no --scope).
        #    Before F-334 this forced a full gate that rolled back on the
        #    victim's pre-existing error. Now it auto-scopes to the new page.
        self._write(_deck([
            {"key": "victim", "layout": "raw", "screen_label": "01 Victim",
             "data": {"html": _victim_html()}},
            {"key": "fresh", "layout": "raw",
             "data": {"html": _clean_html()}}]))
        r1 = self._render("--renumber")

        self.assertEqual(r1.returncode, 0, "must NOT roll back the new page:\n"
                         + r1.stderr[-1500:])
        # auto-scoped to page 2, not a full pass
        self.assertIn("AUTO-SCOPE", r1.stderr, r1.stderr[-800:])
        self.assertIn("auto:2", r1.stderr, r1.stderr[-800:])
        # renumber actually ran
        self.assertIn("renumber", r1.stderr.lower(), r1.stderr[-800:])
        # the new page's content is present in the delivered index.html
        self.assertIn("Freshly Inserted Clean Page",
                      index.read_text(encoding="utf-8"))

    def test_final_still_forces_full_gate(self):
        # --final must remain the whole-deck checkpoint: the victim's error is
        # in scope on a full pass, so a --final render BLOCKS (rc 4).
        self._write(_deck([
            {"key": "victim", "layout": "raw", "screen_label": "01 Victim",
             "data": {"html": _victim_html()}},
            {"key": "fresh", "layout": "raw",
             "data": {"html": _clean_html()}}]))
        # prime a sidecar so we know --final, not "first render", is what forces
        # the full pass.
        env_extra = dict(os.environ, DECK_LOG_NO_AUTOSNAP="1",
                         DECK_ALLOW_VIS_ERRORS="1")
        subprocess.run([sys.executable, str(RENDER), str(self.deck_path),
                        str(self.out) + "/"], capture_output=True, text=True,
                       env=env_extra)
        r = self._render("--renumber", "--final")
        self.assertEqual(r.returncode, 4, "—final must run the full-deck gate "
                         "and block on the in-scope victim error:\n"
                         + r.stderr[-1200:])


if __name__ == "__main__":
    unittest.main()
