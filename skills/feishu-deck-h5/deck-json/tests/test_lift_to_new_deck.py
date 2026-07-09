"""Tests for lift-to-new-deck.py — lift a deck.json-native slide into a BRAND-NEW
deck in one command.

Contract under test (the failure modes that made the hand-rolled flow slow/wrong):
- a valid, lintable deck.json is scaffolded (no hand-built enum/field errors);
- the per-slide copy is delegated to deck-cli paste, so the embedded scoped CSS
  is rekeyed to the new key (F-255) — no orphan selectors onto the old key;
- `lifted` provenance is stamped;
- it refuses to clobber a dest that already holds a deck.json (that's paste's job).
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
TOOL = DECK_JSON / "lift-to-new-deck.py"

OLD_KEY = "src-day"
# Embedded, key-scoped CSS in data.html — the exact shape that broke the manual
# string-replace lift (selectors scoped to the slide key).
SRC_HTML = (
    f'<style>.slide[data-slide-key="{OLD_KEY}"] .x{{color:red}}'
    f'@keyframes k{{from{{opacity:0}}to{{opacity:1}}}}'
    f'.slide[data-slide-key="{OLD_KEY}"] .y{{animation:k 1s}}</style>'
    '<div class="x">hi</div><div class="y">yo</div>'
)


class LiftToNewDeckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lift-to-new-deck-"))
        self.src_dir = self.tmp / "src"
        self.src_dir.mkdir(parents=True)
        src_deck = {
            "version": "1.0",
            "deck": {"title": "source", "author": "a", "date": "2026-06"},
            "slides": [
                {"key": OLD_KEY, "layout": "raw", "accent": "blue",
                 "screen_label": "1 source day", "data": {"html": SRC_HTML}},
                {"key": "src-day-2", "layout": "raw", "accent": "teal",
                 "screen_label": "2 source day two",
                 "data": {"html": '<div class="x">two</div>'}},
            ],
        }
        (self.src_dir / "deck.json").write_text(
            json.dumps(src_deck, ensure_ascii=False), encoding="utf-8")
        self.src = self.src_dir / "deck.json"
        self.dest = self.tmp / "out"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(TOOL), str(self.src), *args],
            capture_output=True, text=True)

    def _lift_one(self, *extra) -> subprocess.CompletedProcess:
        return self._run("1", str(self.dest), "--title", "新 Deck",
                         "--new-key", "new-day", *extra)

    def test_creates_lintable_new_deck(self):
        proc = self._lift_one()
        self.assertEqual(proc.returncode, 0, f"lift failed: {proc.stderr}\n{proc.stdout}")
        deck_path = self.dest / "deck.json"
        self.assertTrue(deck_path.is_file(), "new deck.json not created")
        # The produced deck must pass schema lint (the whole point: no hand-rolled
        # invalid deck.json / bad enum).
        lint = subprocess.run([sys.executable, str(CLI), str(deck_path), "lint"],
                              capture_output=True, text=True)
        self.assertEqual(lint.returncode, 0, f"produced deck failed lint: {lint.stdout}\n{lint.stderr}")
        deck = json.loads(deck_path.read_text(encoding="utf-8"))
        self.assertEqual(deck["deck"]["title"], "新 Deck")
        self.assertEqual(len(deck["slides"]), 1)
        self.assertEqual(deck["slides"][0]["key"], "new-day")

    def test_embedded_css_rekeyed_to_new_key(self):
        proc = self._lift_one()
        self.assertEqual(proc.returncode, 0, f"lift failed: {proc.stderr}\n{proc.stdout}")
        slide = json.loads((self.dest / "deck.json").read_text(encoding="utf-8"))["slides"][0]
        css = slide.get("custom_css") or ""
        self.assertIn('data-slide-key="new-day"', css,
                      "embedded selectors were not rekeyed to the new key")
        self.assertNotIn(f'data-slide-key="{OLD_KEY}"', css,
                         "embedded selectors still orphan onto the old key → unstyled slide")
        self.assertNotIn("<style", slide["data"]["html"].lower(),
                         "pasted raw data.html should not retain embedded <style>")

    def test_lifted_provenance_stamped(self):
        self.assertEqual(self._lift_one().returncode, 0)
        slide = json.loads((self.dest / "deck.json").read_text(encoding="utf-8"))["slides"][0]
        self.assertIn("lifted", slide, "paste must stamp `lifted` provenance")
        self.assertIn(OLD_KEY, slide["lifted"])

    def test_refuses_existing_dest_deck(self):
        self.dest.mkdir(parents=True)
        (self.dest / "deck.json").write_text("{}", encoding="utf-8")
        proc = self._lift_one()
        self.assertNotEqual(proc.returncode, 0,
                            "must refuse to clobber a dest that already has a deck.json")
        self.assertIn("already has a deck.json", proc.stderr)

    def test_new_key_rejected_for_multipage(self):
        # --new-key only makes sense for a single lifted page.
        proc = self._run("1-2", str(self.dest), "--new-key", "x")
        self.assertNotEqual(proc.returncode, 0,
                            "--new-key with >1 page must be rejected")
        self.assertIn("only valid when lifting exactly one page", proc.stderr)

    def test_multipage_lift_keeps_source_keys(self):
        proc = self._run("1-2", str(self.dest), "--title", "多页")
        self.assertEqual(proc.returncode, 0, f"multi-page lift failed: {proc.stderr}\n{proc.stdout}")
        deck = json.loads((self.dest / "deck.json").read_text(encoding="utf-8"))
        self.assertEqual([s["key"] for s in deck["slides"]], [OLD_KEY, "src-day-2"])


DRIFT_KEY = "digital-employee-onboard"
# A DRIFTED source (postmortem 2026-06-22, everbright #7 → ai-into-org): the
# slide's per-slide CSS lives only in a HEAD <style> (legacy data-page scheme),
# and its deck.json custom_css is EMPTY. A naive lift/paste copies that empty
# field → styleless, image-less page, with data-accent/data-decor lost too.
DRIFT_INDEX_HTML = (
    "<html><head>\n"
    '<style data-source="framework">.slide{position:absolute}</style>\n'
    '<style>.slide[data-page="06"] .agent-grid{display:grid}'
    ".slide[data-page=\"06\"] .avatar{background-image:url('input/a.png')}</style>\n"
    "</head><body>\n"
    '<div class="slide-frame"><div class="slide" data-page="06" data-accent="blue" '
    f'data-decor="blue-glow" data-slide-key="{DRIFT_KEY}">\n'
    '<div class="agent-grid"><div class="avatar"></div></div>\n'
    "</div></div>\n</body></html>"
)


class LiftDriftGuardTest(unittest.TestCase):
    """Lifting a page whose styling is stranded in the source's rendered <head>
    (empty deck.json custom_css) must HALT with the repair-lifted remedy, not
    silently emit a styleless deck. Postmortem 2026-06-22 (everbright #7)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lift-drift-"))
        self.src_dir = self.tmp / "src"
        self.src_dir.mkdir(parents=True)
        src_deck = {
            "version": "1.0",
            "deck": {"title": "drifted source"},
            "slides": [
                {"key": DRIFT_KEY, "layout": "raw", "screen_label": "06 数字员工",
                 "custom_css": "",  # the smoking gun: CSS only lives in the head
                 "data": {"html": '<div class="agent-grid"><div class="avatar"></div></div>'}},
            ],
        }
        (self.src_dir / "deck.json").write_text(
            json.dumps(src_deck, ensure_ascii=False), encoding="utf-8")
        (self.src_dir / "index.html").write_text(DRIFT_INDEX_HTML, encoding="utf-8")
        self.dest = self.tmp / "out"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, src, *args):
        return subprocess.run(
            [sys.executable, str(TOOL), str(src), DRIFT_KEY, str(self.dest), *args],
            capture_output=True, text=True)

    def test_halts_on_drift_when_src_is_index_html(self):
        proc = self._run(self.src_dir / "index.html")
        self.assertEqual(proc.returncode, 1, f"expected drift halt:\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("repair-lifted", proc.stderr)
        self.assertIn(DRIFT_KEY, proc.stderr)
        self.assertFalse((self.dest / "deck.json").exists(),
                         "must NOT write a styleless deck when drift is detected")

    def test_halts_on_drift_when_src_is_deck_dir(self):
        proc = self._run(self.src_dir)  # sibling index.html is discovered
        self.assertEqual(proc.returncode, 1, f"expected drift halt:\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("repair-lifted", proc.stderr)

    def test_allow_drift_bypasses_guard(self):
        proc = self._run(self.src_dir / "index.html", "--allow-drift", "--title", "T")
        self.assertEqual(proc.returncode, 0, f"--allow-drift should proceed:\n{proc.stderr}\n{proc.stdout}")
        self.assertTrue((self.dest / "deck.json").exists())

    def test_no_false_alarm_when_custom_css_present(self):
        # Heal the source (CSS now in custom_css). The head still has stale rules,
        # but the empty-custom_css gate is no longer tripped → guard must stay silent.
        deck_path = self.src_dir / "deck.json"
        deck = json.loads(deck_path.read_text(encoding="utf-8"))
        deck["slides"][0]["custom_css"] = ".agent-grid{display:grid}"
        deck_path.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
        proc = self._run(self.src_dir / "index.html", "--title", "T")
        self.assertEqual(proc.returncode, 0, f"healthy deck must lift cleanly:\n{proc.stderr}\n{proc.stdout}")
        self.assertTrue((self.dest / "deck.json").exists())


if __name__ == "__main__":
    unittest.main()
