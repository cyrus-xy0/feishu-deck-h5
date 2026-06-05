"""Hidden-page (隐藏页, PPT-style "hide slide") coverage — closes M8/L8.

The hidden-page feature (deck.json `hidden: true` → `data-hidden` on .slide →
feishu-deck.js skips it in linear present-mode nav and the pager counts visible
slides only) shipped with no committed tests. This locks the pieces this cluster
owns end-to-end:

  · deck-cli hide / unhide round-trips the `hidden` field with a backup, and is
    idempotent (re-hiding an already-hidden slide reports no change).
  · render-deck.py emits `data-hidden` on a hidden slide's .slide AND drops the
    slide from the visible page count (slide-index.json `hidden:true`, while the
    slide still occupies a frame_index so #N stays reachable).
  · locate-slide.py is hidden-aware: it counts the on-screen pager (visible-only)
    correctly while frame_index keeps counting all slides — the SAME skip logic
    feishu-deck.js' visibleOrdinal/visibleCount implements (which can't be unit-
    tested from Python, so this is the cross-checking proxy assertion).
"""
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
CLI = DECK_JSON / "deck-cli.py"
RENDER = DECK_JSON / "render-deck.py"
LOCATE = DECK_JSON / "locate-slide.py"


def _tiny_deck() -> dict:
    """Three raw slides; slide 2 is the one we hide. Each has enough markup to
    render + strict-validate."""
    def raw(key, title):
        return {
            "key": key, "layout": "raw", "screen_label": f"{title}",
            "data": {"html": '<div class="stage" style="position:absolute;'
                             'inset:96px;display:flex;align-items:center;'
                             'justify-content:center;">'
                             f'<h1 style="font-size:96px;color:#fff;margin:0;">'
                             f'{title}</h1></div>'},
        }
    return {
        "version": "1.0",
        "deck": {"title": "hidden-page test", "author": "t", "date": "2026-06"},
        "slides": [raw("alpha", "一"), raw("beta", "二"), raw("gamma", "三")],
    }


class DeckCliHideUnhideTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hidden-page-cli-"))
        self.deck = self.tmp / "deck.json"
        self.deck.write_text(json.dumps(_tiny_deck(), ensure_ascii=False),
                             encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(CLI), str(self.deck), "--yes", *args],
            capture_output=True, text=True)

    def _load(self):
        return json.loads(self.deck.read_text(encoding="utf-8"))

    def _baks(self, command):
        return list(self.tmp.glob(f"deck.json.bak-pre-{command}-*"))

    def test_hide_sets_flag_and_writes_backup(self):
        proc = self._run("hide", "beta")
        self.assertEqual(proc.returncode, 0, f"hide failed: {proc.stderr}")
        slides = {s["key"]: s for s in self._load()["slides"]}
        self.assertTrue(slides["beta"].get("hidden") is True,
                        "hide must set hidden:true on the target slide")
        self.assertNotIn("hidden", slides["alpha"],
                         "hide must not touch other slides")
        self.assertTrue(self._baks("hide"),
                        "hide must write a .bak-pre-hide-* backup")

    def test_unhide_clears_flag_no_residue(self):
        self.assertEqual(self._run("hide", "beta").returncode, 0)
        proc = self._run("unhide", "beta")
        self.assertEqual(proc.returncode, 0, f"unhide failed: {proc.stderr}")
        slides = {s["key"]: s for s in self._load()["slides"]}
        # cleared, not left as hidden:false (no residue)
        self.assertNotIn("hidden", slides["beta"],
                         "unhide must remove the hidden key (no hidden:false residue)")

    def test_hide_is_idempotent(self):
        self.assertEqual(self._run("hide", "beta").returncode, 0)
        after_first = self._load()["slides"]
        proc = self._run("hide", "beta")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("no change", proc.stdout.lower(),
                      "re-hiding an already-hidden slide should report no change")
        # data unchanged by the idempotent second hide
        self.assertEqual(self._load()["slides"], after_first)


class RenderHiddenSlideTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hidden-page-render-"))
        self.deck = self.tmp / "deck.json"
        d = _tiny_deck()
        d["slides"][1]["hidden"] = True          # hide "beta"
        self.deck.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_render_emits_data_hidden_and_excludes_from_visible_count(self):
        r = subprocess.run(
            [sys.executable, str(RENDER), str(self.deck), str(self.tmp) + "/"],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0,
                         f"render failed:\n{r.stdout}\n{r.stderr}")
        html = (self.tmp / "index.html").read_text(encoding="utf-8")
        # the hidden slide's .slide carries data-hidden …
        beta_tag = re.search(
            r'<div class="slide(?:\s[^"]*)?"[^>]*data-slide-key="beta"[^>]*>', html)
        self.assertIsNotNone(beta_tag, "beta slide tag not found in render")
        self.assertIn("data-hidden", beta_tag.group(0),
                      "hidden slide must render data-hidden on its .slide")
        # slide-index.json: hidden flag set on beta, and the visible count = 2.
        idx = json.loads((self.tmp / "slide-index.json").read_text(encoding="utf-8"))
        by_key = {s["key"]: s for s in idx["slides"]}
        self.assertTrue(by_key["beta"].get("hidden") is True,
                        "slide-index.json must flag the hidden slide")
        self.assertNotIn("hidden", by_key["alpha"],
                         "slide-index.json must not flag visible slides")
        visible = [s for s in idx["slides"] if not s.get("hidden")]
        self.assertEqual(len(visible), 2,
                         "exactly 2 of 3 slides are visible (hidden excluded)")
        # frame_index still counts ALL slides → hidden slide stays #N-reachable.
        self.assertEqual(by_key["beta"]["frame_index"], 2,
                         "hidden slide keeps its frame_index (#N reachable)")
        self.assertEqual(by_key["gamma"]["frame_index"], 3,
                         "frame_index counts hidden slides (does not renumber)")


class LocateSlideVisibleOrdinalTest(unittest.TestCase):
    """Unit-level proxy for feishu-deck.js visibleCount/visibleOrdinal skip logic
    (JS can't be unit-tested from here): locate-slide annotates the SAME
    visible-only pager ordinal while frame_index keeps counting all slides."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hidden-page-locate-"))
        self.deck = self.tmp / "deck.json"
        d = _tiny_deck()
        d["slides"][1]["hidden"] = True          # hide the MIDDLE slide
        self.deck.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _locate(self, query, *flags):
        return subprocess.run(
            [sys.executable, str(LOCATE), str(self.deck), query, *flags],
            capture_output=True, text=True)

    def test_visible_ordinal_skips_hidden_in_json(self):
        # alpha visible #1 → screen 1; beta hidden → screen None; gamma visible
        # #3 (frame_index 3) → screen 2 (visible-only count).
        r = self._locate("1,2,3", "--json")
        self.assertEqual(r.returncode, 0, f"locate failed: {r.stderr}")
        rows = {e["key"]: e for e in json.loads(r.stdout)}
        self.assertEqual(rows["alpha"]["frame_index"], 1)
        self.assertEqual(rows["alpha"]["visible_ordinal"], 1)
        self.assertTrue(rows["beta"].get("hidden") is True)
        self.assertIsNone(rows["beta"]["visible_ordinal"],
                          "hidden slide has no own pager slot (visible_ordinal None)")
        self.assertEqual(rows["gamma"]["frame_index"], 3,
                         "frame_index counts the hidden slide")
        self.assertEqual(rows["gamma"]["visible_ordinal"], 2,
                         "visible pager skips the hidden slide → gamma is screen 2")

    def test_human_output_marks_hidden_and_prints_note(self):
        r = self._locate("2")        # the hidden slide, human output
        self.assertEqual(r.returncode, 0, f"locate failed: {r.stderr}")
        self.assertIn("[hidden]", r.stdout, "hidden slide must be annotated [hidden]")
        self.assertIn("screen=—", r.stdout, "hidden slide shows no pager position")
        self.assertIn("visible-only", r.stdout,
                      "deck with a hidden slide must print the pager note")


def _load_render():
    spec = importlib.util.spec_from_file_location(
        "render_deck_hidden", DECK_JSON / "render-deck.py")
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(DECK_JSON))
    spec.loader.exec_module(m)
    return m


def test_build_data_attrs_data_hidden_unit():
    """Fast unit check (no subprocess) mirroring the render path."""
    m = _load_render()
    assert "data-hidden" in m._build_data_attrs({"key": "x", "hidden": True})
    assert "data-hidden" not in m._build_data_attrs({"key": "x", "hidden": False})
    assert "data-hidden" not in m._build_data_attrs({"key": "x"})


if __name__ == "__main__":
    unittest.main()
