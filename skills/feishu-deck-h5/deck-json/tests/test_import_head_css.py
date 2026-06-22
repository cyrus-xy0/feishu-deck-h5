"""F-371 unit guards: import-html-slide recovers a lifted page's CSS when the
SOURCE kept it in index.html's head/consolidated <style> (scoped the legacy way
by [data-page="N"], or by [data-slide-key]) instead of co-located in custom_css.

Before F-371 such a page imported as bare HTML — extract_slide_frames pulls only
the .slide-frame, and _consolidate_slide_css folds only a <style> EMBEDDED in
that frame, so head-scoped CSS was silently dropped → the page rendered unstyled
and overflowed the canvas. (Retrospective: 2026-06-22 ai-into-org lift, where
two pages lifted from a legacy 60-page deck overflowed +696/+666px because their
CSS lived in the source head keyed by data-page, never in custom_css.)
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parents[1]
DECK_JSON_DIR = SKILL_ROOT / "deck-json"


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, SKILL_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# A source index.html whose page CSS lives ONLY in a head <style>, scoped the
# legacy way by [data-page="03"] — including a [data-layout]-qualified .stage rule
# (the exact shape that overflowed in the retrospective) and an @keyframes the
# page references. The frame's .slide carries data-layout="content-2col" so the
# importer records it as _orig_layout and render re-emits data-layout for it.
SRC_INDEX = """<!doctype html><html><head>
<style data-source="framework">.slide{position:absolute}</style>
<style>
.slide[data-page="03"] .foo { color: #ff0000; font-size: 24px; }
.slide[data-page="03"][data-layout="content-2col"] .stage { display: grid; gap: 40px; }
@keyframes fooanim { from { opacity: 0 } to { opacity: 1 } }
.slide[data-page="03"] .bar { animation: fooanim .6s both; }
</style>
</head><body>
<div class="slide-frame" data-page="03">
  <div class="slide" data-layout="content-2col" data-slide-key="mypage">
    <div class="wordmark">飞书</div>
    <div class="stage"><div class="foo">hello</div><div class="bar">x</div></div>
  </div>
</div>
</body></html>"""


class HarvestHeadCssTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ih = _load("deck-json/import-html-slide.py", "_ih_f370")

    def test_harvest_returns_page_scoped_rules_by_orig_key(self):
        chunks = self.ih._harvest_head_css(SRC_INDEX)
        self.assertIn("mypage", chunks)            # mapped via data-page -> slide-key
        css = chunks["mypage"]
        self.assertIn(".foo", css)
        self.assertIn("#ff0000", css)

    def test_harvest_carries_data_layout_qualified_rule(self):
        # the [data-layout]-qualified .stage rule (the one whose loss overflowed the
        # retrospective page) must be harvested verbatim — it re-engages on the raw
        # wrapper because render re-emits data-layout from _orig_layout.
        css = self.ih._harvest_head_css(SRC_INDEX)["mypage"]
        self.assertIn('[data-layout="content-2col"]', css)
        self.assertIn(".stage", css)

    def test_harvest_pulls_referenced_keyframes(self):
        css = self.ih._harvest_head_css(SRC_INDEX)["mypage"]
        self.assertIn("@keyframes fooanim", css)

    def test_harvest_skips_framework_block(self):
        css = self.ih._harvest_head_css(SRC_INDEX)["mypage"]
        self.assertNotIn("position:absolute", css.replace(" ", ""))

    def test_harvest_empty_on_garbage(self):
        self.assertEqual(self.ih._harvest_head_css("<not even html"), {})


class InjectHeadCssTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ih = _load("deck-json/import-html-slide.py", "_ih2_f370")

    def _fresh_deck(self) -> Path:
        d = Path(tempfile.mkdtemp())
        deck = d / "deck.json"
        r = subprocess.run(
            [sys.executable, str(DECK_JSON_DIR / "deck-cli.py"), str(deck),
             "new-deck", "--title", "T", "--author", "A", "--date", "2026-01-01"],
            capture_output=True, text=True)
        assert deck.exists(), f"new-deck failed: {r.stderr}"
        return deck

    def _frag(self):
        return self.ih.extract_slide_frames(SRC_INDEX)[0]

    def test_injects_harvested_css_into_custom_css(self):
        deck = self._fresh_deck()
        css = self.ih._harvest_head_css(SRC_INDEX)["mypage"]
        self.ih.insert_into_json(
            deck, [self._frag()], 0, lifted=True, allow_unsynced=True, force=True,
            consolidate_css=True, head_css_list=[css])
        slides = json.loads(deck.read_text(encoding="utf-8"))["slides"]
        new = next(s for s in slides if (s.get("key") or "").startswith("mypage"))
        cc = new.get("custom_css", "") or ""
        self.assertIn(".foo", cc)                          # head CSS recovered
        self.assertIn("#ff0000", cc)
        self.assertIn('[data-layout="content-2col"]', cc)  # layout-qualified rule kept
        self.assertEqual(new.get("_orig_layout"), "content-2col")  # so data-layout re-emits

    def test_no_consolidate_css_skips_injection(self):
        # --no-consolidate-css (consolidate_css=False) opts out of head recovery too.
        deck = self._fresh_deck()
        css = self.ih._harvest_head_css(SRC_INDEX)["mypage"]
        self.ih.insert_into_json(
            deck, [self._frag()], 0, lifted=True, allow_unsynced=True, force=True,
            consolidate_css=False, head_css_list=[css])
        slides = json.loads(deck.read_text(encoding="utf-8"))["slides"]
        new = next(s for s in slides if (s.get("key") or "").startswith("mypage"))
        self.assertNotIn(".foo", new.get("custom_css", "") or "")

    def test_absent_head_css_leaves_custom_css_unset(self):
        # a frag with no harvested head CSS (None entry) must not crash or fabricate.
        deck = self._fresh_deck()
        self.ih.insert_into_json(
            deck, [self._frag()], 0, lifted=True, allow_unsynced=True, force=True,
            consolidate_css=True, head_css_list=[None])
        slides = json.loads(deck.read_text(encoding="utf-8"))["slides"]
        new = next(s for s in slides if (s.get("key") or "").startswith("mypage"))
        self.assertNotIn(".foo", new.get("custom_css", "") or "")


if __name__ == "__main__":
    unittest.main()
