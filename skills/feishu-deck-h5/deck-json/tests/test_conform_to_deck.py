"""Tests for conform-to-deck.py (F-300) — the family-drift detector.

The detector reads the consensus of the sibling raw content pages and reports,
for the page(s) under test, every dimension where it drifts from that consensus.
These tests assert both directions on a synthetic deck:

  · a CONFORMANT page (matches siblings: no own bg, framework .header title, no
    pre-title chrome, on-ladder fonts, bright body text) → clean, exit 0
  · a DRIFTED page (own page bg / bespoke title / topbar eyebrow / off-ladder
    fonts / muted-grey body) → D1-D4 hard drift, D5 advisory, --strict exits 1
  · consensus needs >= 2 siblings: a tiny deck reports "insufficient"
  · the unit-level signal extractors return the right booleans

The detector is READ-ONLY — these tests also assert it never writes a .bak or
mutates the input deck.json.
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
CONFORM = DECK_JSON / "conform-to-deck.py"

_spec = importlib.util.spec_from_file_location("conform_to_deck", CONFORM)
conform = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(conform)


# --- slide builders -----------------------------------------------------------
def _conformant_slide(key, label, title):
    """A page that follows the house style: framework .header title, .stage body,
    no own page-bg, on-ladder fonts, bright (white) body text."""
    html = (f'<div class="header"><h2 class="title-zh">{title}</h2></div>'
            f'<div class="stage"><p class="lede">{title} body copy here.</p></div>')
    css = (f'.slide[data-slide-key="{key}"] .lede{{font-size:24px;color:#fff}}'
           f'.slide[data-slide-key="{key}"] .title-zh{{font-size:48px;color:#fff}}')
    return {"key": key, "layout": "raw", "screen_label": label,
            "data": {"html": html}, "custom_css": css}


def _drifted_slide(key="bad", label="99 Bad"):
    """A page faithful to a FOREIGN source: own full-bleed bg, a topbar eyebrow,
    a bespoke title block (not .header), off-ladder fonts, muted-grey body text."""
    html = ('<div class="shift">'
            '<div class="topbar"><b>P1</b> THE SHIFT</div>'
            '<div class="headline"><h1>Human-to-Human to Human-to-Agent</h1></div>'
            '<div class="panels"><div class="panel">'
            '<div class="caption">The platform was a pipe.'
            '<span class="cn">a note</span></div></div></div>'
            '</div>')
    css = (f'.slide[data-slide-key="{key}"]{{background:#0A0E18;color:#F2F5FA}}'
           f'.slide[data-slide-key="{key}"] .headline h1{{font-size:64px}}'
           f'.slide[data-slide-key="{key}"] .caption{{font-size:17px;color:#C8CFDC}}'
           f'.slide[data-slide-key="{key}"] .cn{{font-size:13px;color:#5E6678}}')
    return {"key": key, "layout": "raw", "screen_label": label,
            "data": {"html": html}, "custom_css": css}


def _write_deck(path, slides):
    path.write_text(json.dumps(
        {"version": "1.0",
         "deck": {"title": "t", "author": "a", "date": "2026-06"},
         "slides": slides}, ensure_ascii=False), encoding="utf-8")


_FAMILY = [
    _conformant_slide("onboard", "04 Onboard", "Digital Employees Come Online"),
    _conformant_slide("review", "05 Review", "The Review Assistant"),
    _conformant_slide("not-1to1", "06 Not 1:1", "Not a 1:1 Copy of a Human"),
    _conformant_slide("map", "07 Map", "Four Engines on One OS"),
]


class ConformUnitSignals(unittest.TestCase):
    def test_page_bg_signal(self):
        self.assertTrue(conform.sets_own_page_bg(_drifted_slide())[0])
        self.assertFalse(conform.sets_own_page_bg(_FAMILY[0])[0])

    def test_title_in_header_signal(self):
        self.assertTrue(conform.title_in_header(_FAMILY[0]))
        self.assertFalse(conform.title_in_header(_drifted_slide()))

    def test_pretitle_chrome_signal(self):
        self.assertTrue(conform.has_pretitle_chrome(_drifted_slide())[0])
        self.assertFalse(conform.has_pretitle_chrome(_FAMILY[0])[0])

    def test_font_ladder_signal(self):
        self.assertGreater(conform.offladder_count(_drifted_slide()), 0)
        self.assertEqual(conform.offladder_count(_FAMILY[0]), 0)

    def test_transparent_rgba_bg_not_flagged(self):
        s = _conformant_slide("x", "08 X", "X")
        s["custom_css"] += '.slide[data-slide-key="x"]{background:rgba(0,0,0,0)}'
        self.assertFalse(conform.sets_own_page_bg(s)[0])


class ConformAssessment(unittest.TestCase):
    def test_drifted_page_flags_d1_d4_hard_d5_advisory(self):
        drifted = _drifted_slide()
        dims = {d.code: d for d in conform.assess_page(drifted, _FAMILY)}
        self.assertEqual(dims["D1"].verdict, "drift")
        self.assertEqual(dims["D2"].verdict, "drift")
        self.assertEqual(dims["D3"].verdict, "drift")
        self.assertEqual(dims["D4"].verdict, "drift")
        self.assertEqual(dims["D5"].verdict, "advisory")  # never hard-fails

    def test_conformant_page_clean(self):
        page = _conformant_slide("self", "09 Self", "A Conformant Page")
        dims = {d.code: d for d in conform.assess_page(page, _FAMILY)}
        for code in ("D1", "D2", "D3", "D4"):
            self.assertEqual(dims[code].verdict, "match", code)
        self.assertIn(dims["D5"].verdict, ("match", "n/a"))


class ConformCLI(unittest.TestCase):
    def _run(self, deck_path, *args):
        return subprocess.run(
            [sys.executable, str(CONFORM), str(deck_path), *args],
            capture_output=True, text=True)

    def test_strict_exit_on_drift_and_clean(self):
        with tempfile.TemporaryDirectory() as td:
            deck = Path(td) / "deck.json"
            _write_deck(deck, _FAMILY + [_drifted_slide()])
            before = deck.read_bytes()

            r = self._run(deck, "--page", "5", "--strict")
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("✗", r.stdout)

            # read-only: input unchanged, no .bak written
            self.assertEqual(deck.read_bytes(), before)
            self.assertEqual(list(Path(td).glob("*.bak*")), [])

            r2 = self._run(deck, "--page", "1", "--strict")  # a conformant sibling
            self.assertEqual(r2.returncode, 0, r2.stdout)

    def test_insufficient_family(self):
        with tempfile.TemporaryDirectory() as td:
            deck = Path(td) / "deck.json"
            _write_deck(deck, _FAMILY[:2])  # only 2 content pages
            r = self._run(deck)
            self.assertEqual(r.returncode, 0)
            self.assertIn("need >= 3 raw content pages", r.stdout)

    def test_apply_fixes_d1_d3_d4_leaves_d2(self):
        with tempfile.TemporaryDirectory() as td:
            deck = Path(td) / "deck.json"
            _write_deck(deck, _FAMILY + [_drifted_slide()])

            r = self._run(deck, "--page", "5", "--apply")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("stripped own page-bg", r.stdout)
            self.assertIn("removed pre-title chrome", r.stdout)
            self.assertIn("snapped", r.stdout)
            self.assertIn("validate-deck --strict: PASS", r.stdout)
            # a backup was left
            self.assertTrue(list(Path(td).glob("*.bak-pre-conform-*")))

            # re-detect: D1/D3/D4 now conform, D2 still drifts (DOM, not auto)
            r2 = self._run(deck, "--page", "5")
            out = r2.stdout
            self.assertRegex(out, r"✓ ① D1")
            self.assertRegex(out, r"✓ ③ D3")
            self.assertRegex(out, r"✓ ④ D4")
            self.assertRegex(out, r"✗ ② D2")

    def test_apply_noop_when_clean(self):
        with tempfile.TemporaryDirectory() as td:
            deck = Path(td) / "deck.json"
            _write_deck(deck, _FAMILY)
            before = deck.read_bytes()
            r = self._run(deck, "--page", "1", "--apply")
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn("nothing to auto-conform", r.stdout)
            self.assertEqual(deck.read_bytes(), before)      # untouched
            self.assertEqual(list(Path(td).glob("*.bak*")), [])


class ConformApplyUnit(unittest.TestCase):
    def test_apply_conforms_mutates_slide(self):
        slide = _drifted_slide()
        dims = {d.code: d for d in conform.assess_page(slide, _FAMILY)}
        actions = conform.apply_conforms(slide, dims)
        self.assertEqual(len(actions), 3)               # D1 + D3 + D4
        # bg gone, topbar gone, fonts snapped
        self.assertFalse(conform.sets_own_page_bg(slide)[0])
        self.assertFalse(conform.has_pretitle_chrome(slide)[0])
        self.assertEqual(conform.offladder_count(slide), 0)
        # title still bespoke (D2 not auto-applied)
        self.assertFalse(conform.title_in_header(slide))

    def test_apply_never_removes_title(self):
        # an eyebrow class wrapping the title must NOT delete the title
        slide = {"key": "k", "layout": "raw", "screen_label": "09 K",
                 "data": {"html": '<div class="eyebrow"><h2 class="title-zh">T</h2>'
                                   '</div><div class="stage"><p>body</p></div>'},
                 "custom_css": ""}
        gone = conform.fix_pretitle_chrome(slide)
        self.assertEqual(gone, [])
        self.assertIn("title-zh", slide["data"]["html"])


class ValidateDeckFamilyDrift(unittest.TestCase):
    """R-FAMILY-DRIFT must SURFACE but never BLOCK — render-deck calls
    validate-deck --strict and aborts on a hard error, so the rule is soft."""

    VALIDATE = DECK_JSON / "validate-deck.py"

    def _validate(self, deck_path, *args):
        return subprocess.run(
            [sys.executable, str(self.VALIDATE), str(deck_path), *args],
            capture_output=True, text=True)

    def test_drift_surfaces_as_nonblocking_advisory_even_in_strict(self):
        with tempfile.TemporaryDirectory() as td:
            deck = Path(td) / "deck.json"
            _write_deck(deck, _FAMILY + [_drifted_slide()])
            r = self._validate(deck, "--strict")
            self.assertEqual(r.returncode, 0, r.stdout)        # NOT promoted
            self.assertIn("PASS", r.stdout)
            self.assertIn("R-FAMILY-DRIFT", r.stdout)
            self.assertIn("advisory (non-blocking)", r.stdout)
            self.assertIn("D1 page-background", r.stdout)
            self.assertIn("D3 pre-title chrome", r.stdout)

    def test_conformant_deck_has_no_drift_advisory(self):
        with tempfile.TemporaryDirectory() as td:
            deck = Path(td) / "deck.json"
            _write_deck(deck, _FAMILY + [
                _conformant_slide("self", "08 Self", "A Conformant Page")])
            r = self._validate(deck, "--strict")
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertNotIn("R-FAMILY-DRIFT", r.stdout)

    def test_skipped_under_three_content_pages(self):
        with tempfile.TemporaryDirectory() as td:
            deck = Path(td) / "deck.json"
            _write_deck(deck, _FAMILY[:2] + [_drifted_slide()])  # 3 raw but...
            # only 2 conformant + 1 drifted = 3 content pages → consensus exists;
            # to assert the < 3 skip, use just 2 pages:
            _write_deck(deck, _FAMILY[:1] + [_drifted_slide()])
            r = self._validate(deck, "--strict")
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertNotIn("R-FAMILY-DRIFT", r.stdout)


if __name__ == "__main__":
    unittest.main()
