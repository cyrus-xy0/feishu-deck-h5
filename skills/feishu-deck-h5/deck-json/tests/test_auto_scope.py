"""F-310 · auto-scope sidecar schema-2 additions (framework hash, _disabled
skip, default-on entrance contract).

The W3 basics (--iter engages on a changed page, sidecar written on success)
live in test_iteration_loop.py::test_iter_auto_scope_and_text_echo — this file
only covers what F-310 ADDED to the same single system:

  • _sidecar_state enumerates ACTIVE slides only (`_disabled` skipped) so list
    position i ↔ frame_index i+1 — schema 1 mis-numbered any deck with a
    _disabled slide.
  • _auto_scope_pages treats a framework/templates byte change as full-render
    (schema-1 sidecars lack the field → one-time full, then upgrade).
  • the DEFAULT-ON entrance in main() caps at AUTO_SCOPE_MAX_PAGES; the helper
    itself never caps (--iter takes any count).

Pure-helper tests — no rendering, no Playwright.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
RENDER_DECK = HERE.parent / "render-deck.py"

_spec = importlib.util.spec_from_file_location("render_deck_mod", RENDER_DECK)
rd = importlib.util.module_from_spec(_spec)
sys.modules["render_deck_mod"] = rd
_spec.loader.exec_module(rd)


def _deck(n=6, **meta):
    return {
        "version": "1.0",
        "title": "t",
        **meta,
        "slides": [
            {"key": f"p{i}", "layout": "raw", "data": {"html": f"<p>{i}</p>"}}
            for i in range(1, n + 1)
        ],
    }


def _sidecar_for(deck, tmp: Path) -> Path:
    sp = tmp / rd._SIDECAR_NAME
    sp.write_text(json.dumps(rd._sidecar_state(deck), ensure_ascii=False),
                  encoding="utf-8")
    return sp


class SidecarStateTest(unittest.TestCase):
    def test_disabled_slides_are_skipped_and_numbering_follows_frames(self):
        deck = _deck(4)
        deck["slides"][1]["_disabled"] = True   # p2 off → frames: p1, p3, p4
        st = rd._sidecar_state(deck)
        self.assertEqual([k for k, _ in st["slides"]], ["p1", "p3", "p4"])
        self.assertEqual(st["schema"], rd._SIDECAR_SCHEMA)
        self.assertIn("framework", st)

    def test_framework_hash_is_stable_within_a_run(self):
        self.assertEqual(rd._framework_hash(), rd._framework_hash())


class AutoScopePagesTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_changed_page_detected_with_frame_numbering(self):
        deck = _deck(4)
        deck["slides"][1]["_disabled"] = True   # frames: p1, p3, p4
        sp = _sidecar_for(deck, self.tmp)
        deck2 = copy.deepcopy(deck)
        deck2["slides"][2]["data"]["html"] = "<p>edited</p>"   # p3 = frame 2
        pages, reason = rd._auto_scope_pages(deck2, sp)
        self.assertEqual(pages, [2], reason)

    def test_framework_mismatch_forces_full(self):
        deck = _deck(3)
        sp = _sidecar_for(deck, self.tmp)
        st = json.loads(sp.read_text(encoding="utf-8"))
        st["framework"] = "0" * 40
        sp.write_text(json.dumps(st), encoding="utf-8")
        pages, reason = rd._auto_scope_pages(deck, sp)
        self.assertIsNone(pages)
        self.assertIn("framework", reason)

    def test_schema1_sidecar_without_framework_field_forces_full_once(self):
        deck = _deck(3)
        sp = _sidecar_for(deck, self.tmp)
        st = json.loads(sp.read_text(encoding="utf-8"))
        del st["framework"]                      # what a pre-F-310 sidecar looks like
        st["schema"] = 1
        sp.write_text(json.dumps(st), encoding="utf-8")
        pages, _ = rd._auto_scope_pages(deck, sp)
        self.assertIsNone(pages)

    def test_disabled_toggle_is_structural(self):
        deck = _deck(3)
        sp = _sidecar_for(deck, self.tmp)
        deck2 = copy.deepcopy(deck)
        deck2["slides"][0]["_disabled"] = True   # key list shrinks → structural
        pages, reason = rd._auto_scope_pages(deck2, sp)
        self.assertIsNone(pages)
        self.assertIn("added/removed/reordered", reason)

    def test_helper_never_caps_cap_is_the_default_entrances_job(self):
        deck = _deck(rd.AUTO_SCOPE_MAX_PAGES + 3)
        sp = _sidecar_for(deck, self.tmp)
        deck2 = copy.deepcopy(deck)
        for s in deck2["slides"]:
            s["data"]["html"] = "<p>x</p>"
        pages, _ = rd._auto_scope_pages(deck2, sp)
        self.assertEqual(len(pages), rd.AUTO_SCOPE_MAX_PAGES + 3)


if __name__ == "__main__":
    unittest.main()
