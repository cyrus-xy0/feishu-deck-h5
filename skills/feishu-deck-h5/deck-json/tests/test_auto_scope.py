"""F-335 · structured auto-scope decision (visual / static-engine fingerprint
split, field-level deck-meta, content/visual decouple).

Supersedes the F-310/F-334 tests for the old `_auto_scope_pages` (which returned
(pages|None) and discarded the content scope on any framework or deck-meta bust).
The new `_auto_scope_decision` returns:

    {content_dirty, visual_full, engine_dirty, extra_visual, reason}

and the headline guarantee is the DECOUPLE: a framework / template / rule-engine
/ deck-meta change no longer empties content_dirty — it only sets visual_full
(or engine_dirty), so the static gate + making-of snapshot stay scoped to the
genuinely-changed pages while the visual pass covers all of them.

The W3 basics (--iter engages on a changed page, sidecar written on success)
live in test_iteration_loop.py. Pure-helper tests — no rendering, no Playwright.
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

    def test_sidecar_carries_the_split_fingerprints_and_meta(self):
        st = rd._sidecar_state(_deck(3))
        for field in ("visual_fp", "engine_fp", "meta_chrome", "meta_structural"):
            self.assertIn(field, st)
        # the old monolithic fields are gone
        self.assertNotIn("framework", st)
        self.assertNotIn("deck_meta", st)

    def test_fingerprints_are_stable_within_a_run(self):
        deck = _deck(3)
        self.assertEqual(rd._visual_fingerprint(deck), rd._visual_fingerprint(deck))
        self.assertEqual(rd._static_engine_fingerprint(),
                         rd._static_engine_fingerprint())


class LayoutAwareVisualFingerprintTest(unittest.TestCase):
    def test_raw_only_deck_includes_wrapper_excludes_schema_fragments(self):
        # A raw-first deck includes the always-rendered wrappers (_shell.html +
        # raw.fragment.html — editing the wordmark/wrapper MUST bust it) but NOT
        # an unused schema-layout fragment (editing flow.fragment.html must not
        # bust a deck with no flow slide).
        files = {p.name for p in rd._deck_template_files(_deck(3))}
        self.assertIn("_shell.html", files)
        if (rd.TEMPLATES_DIR / "raw.fragment.html").exists():
            self.assertIn("raw.fragment.html", files)
        flow = rd.TEMPLATES_DIR / "flow.fragment.html"
        if flow.exists():
            self.assertNotIn("flow.fragment.html", files)

    def test_deck_using_a_layout_includes_that_fragment(self):
        # If a fragment exists for a layout the deck uses, it must be in the set.
        layout = None
        for cand in ("content", "section", "cover", "quote"):
            if (rd.TEMPLATES_DIR / f"{cand}.fragment.html").exists():
                layout = cand
                break
        if layout is None:
            self.skipTest("no schema-layout fragment available in this build")
        deck = _deck(2)
        deck["slides"][0] = {"key": "k", "layout": layout, "data": {}}
        files = {p.name for p in rd._deck_template_files(deck)}
        self.assertIn(f"{layout}.fragment.html", files)


class AutoScopeDecisionTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _decide(self, deck, sp):
        return rd._auto_scope_decision(deck, sp)

    # ---- content diff ---------------------------------------------------------

    def test_changed_page_detected_with_frame_numbering(self):
        deck = _deck(4)
        deck["slides"][1]["_disabled"] = True   # frames: p1, p3, p4
        sp = _sidecar_for(deck, self.tmp)
        deck2 = copy.deepcopy(deck)
        deck2["slides"][2]["data"]["html"] = "<p>edited</p>"   # p3 = frame 2
        dec = self._decide(deck2, sp)
        self.assertEqual(dec["content_dirty"], [2], dec["reason"])
        self.assertFalse(dec["visual_full"])
        self.assertFalse(dec["engine_dirty"])

    # ---- THE DECOUPLE: framework change keeps content scoped ------------------

    def test_visual_fingerprint_change_keeps_content_scope_and_sets_visual_full(self):
        # The #1 fix: a framework/CSS change must NOT discard the content diff.
        deck = _deck(4)
        sp = _sidecar_for(deck, self.tmp)
        st = json.loads(sp.read_text(encoding="utf-8"))
        st["visual_fp"] = "0" * 40                       # simulate a CSS edit
        sp.write_text(json.dumps(st), encoding="utf-8")
        dec = self._decide(deck, sp)
        self.assertTrue(dec["visual_full"])
        self.assertEqual(dec["content_dirty"], [])       # NOT None — scope preserved
        self.assertIn("visual", dec["reason"])

    def test_framework_change_plus_content_edit_scopes_content_full_visual(self):
        deck = _deck(4)
        sp = _sidecar_for(deck, self.tmp)
        st = json.loads(sp.read_text(encoding="utf-8"))
        st["visual_fp"] = "0" * 40
        sp.write_text(json.dumps(st), encoding="utf-8")
        deck2 = copy.deepcopy(deck)
        deck2["slides"][2]["data"]["html"] = "<p>edited</p>"   # frame 3
        dec = self._decide(deck2, sp)
        self.assertEqual(dec["content_dirty"], [3])      # snapshot/static stay scoped
        self.assertTrue(dec["visual_full"])              # visual goes full

    # ---- static rule-engine change -------------------------------------------

    def test_engine_change_sets_engine_dirty_not_visual_full(self):
        deck = _deck(3)
        sp = _sidecar_for(deck, self.tmp)
        st = json.loads(sp.read_text(encoding="utf-8"))
        st["engine_fp"] = "0" * 40                       # simulate a validator edit
        sp.write_text(json.dumps(st), encoding="utf-8")
        dec = self._decide(deck, sp)
        self.assertTrue(dec["engine_dirty"])
        self.assertFalse(dec["visual_full"])             # rules ≠ appearance
        self.assertEqual(dec["content_dirty"], [])

    # ---- field-level deck-meta -----------------------------------------------

    def test_chrome_meta_change_rechecks_cover_not_full(self):
        deck = _deck(3)
        sp = _sidecar_for(deck, self.tmp)
        deck2 = copy.deepcopy(deck)
        deck2["title"] = "a new title"                   # chrome field
        dec = self._decide(deck2, sp)
        self.assertFalse(dec["visual_full"])
        self.assertEqual(dec["extra_visual"], [1])       # cover re-checked
        self.assertIn("chrome", dec["reason"])

    def test_structural_meta_change_forces_full_visual(self):
        deck = _deck(3, theme="light")
        sp = _sidecar_for(deck, self.tmp)
        deck2 = copy.deepcopy(deck)
        deck2["theme"] = "dark"                           # structural field
        dec = self._decide(deck2, sp)
        self.assertTrue(dec["visual_full"])
        self.assertIn("structural", dec["reason"])

    def test_deck_id_does_not_bust(self):
        # deck_id is render-minted; it must never trigger a structural bust.
        deck = _deck(3)
        sp = _sidecar_for(deck, self.tmp)
        deck2 = copy.deepcopy(deck)
        deck2["deck"] = {"deck_id": "dk-abc123"}
        dec = self._decide(deck2, sp)
        self.assertFalse(dec["visual_full"])
        self.assertEqual(dec["extra_visual"], [])
        self.assertEqual(dec["content_dirty"], [])

    # ---- incompatible / missing sidecar --------------------------------------

    def test_no_sidecar_is_full(self):
        dec = self._decide(_deck(3), self.tmp / "nope.json")
        self.assertIsNone(dec["content_dirty"])
        self.assertTrue(dec["visual_full"])

    def test_old_schema_sidecar_forces_full_once(self):
        deck = _deck(3)
        sp = _sidecar_for(deck, self.tmp)
        st = json.loads(sp.read_text(encoding="utf-8"))
        st["schema"] = 1                                 # pre-F-335 sidecar
        sp.write_text(json.dumps(st), encoding="utf-8")
        dec = self._decide(deck, sp)
        self.assertIsNone(dec["content_dirty"])
        self.assertTrue(dec["visual_full"])
        self.assertIn("schema", dec["reason"])

    # ---- F-334 structural-by-key (carried forward) ---------------------------

    def test_insert_scopes_to_the_new_page_only(self):
        deck = _deck(4)
        sp = _sidecar_for(deck, self.tmp)
        deck2 = copy.deepcopy(deck)
        deck2["slides"].insert(2, {"key": "pNEW", "layout": "raw",
                                   "data": {"html": "<p>new</p>"}})  # frame 3
        dec = self._decide(deck2, sp)
        self.assertEqual(dec["content_dirty"], [3], dec["reason"])

    def test_screen_label_change_alone_is_not_dirty(self):
        deck = _deck(3)
        sp = _sidecar_for(deck, self.tmp)
        deck2 = copy.deepcopy(deck)
        for i, s in enumerate(deck2["slides"]):
            s["screen_label"] = f"{i + 1:02d} renamed"
        dec = self._decide(deck2, sp)
        self.assertEqual(dec["content_dirty"], [])
        self.assertFalse(dec["visual_full"])

    def test_insert_plus_renumber_scopes_to_new_page_only(self):
        deck = _deck(4)
        sp = _sidecar_for(deck, self.tmp)
        deck2 = copy.deepcopy(deck)
        deck2["slides"].insert(1, {"key": "pNEW", "layout": "raw",
                                   "data": {"html": "<p>new</p>"}})  # frame 2
        for i, s in enumerate(deck2["slides"]):
            s["screen_label"] = f"{i + 1:02d} label"
        dec = self._decide(deck2, sp)
        self.assertEqual(dec["content_dirty"], [2], dec["reason"])

    def test_reorder_with_same_content_is_not_dirty(self):
        deck = _deck(3)
        sp = _sidecar_for(deck, self.tmp)
        deck2 = copy.deepcopy(deck)
        deck2["slides"].reverse()
        dec = self._decide(deck2, sp)
        self.assertEqual(dec["content_dirty"], [])

    def test_enabling_a_disabled_slide_scopes_to_it(self):
        deck = _deck(3)
        deck["slides"][1]["_disabled"] = True
        sp = _sidecar_for(deck, self.tmp)
        deck2 = copy.deepcopy(deck)
        del deck2["slides"][1]["_disabled"]               # frame 2
        dec = self._decide(deck2, sp)
        self.assertEqual(dec["content_dirty"], [2], dec["reason"])

    def test_helper_never_caps_cap_is_the_default_entrances_job(self):
        deck = _deck(rd.AUTO_SCOPE_MAX_PAGES + 3)
        sp = _sidecar_for(deck, self.tmp)
        deck2 = copy.deepcopy(deck)
        for s in deck2["slides"]:
            s["data"]["html"] = "<p>x</p>"
        dec = self._decide(deck2, sp)
        self.assertEqual(len(dec["content_dirty"]), rd.AUTO_SCOPE_MAX_PAGES + 3)


if __name__ == "__main__":
    unittest.main()
