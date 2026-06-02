"""Regression guards for `assets/lift-slides.py --shake` (the foreign-deck lift).

Three bug classes hit while lifting qingdao `feishu-product-leadership` into the
zhongan deck on 2026-06-01 — each silently produced a broken slide that still
"looked carried" in the lift report. These tests lift a synthetic source deck
that reproduces all three structural triggers and assert the invariants:

  BUG1 · dropped </div>  — extract_one()'s old "2nd </div>-line from the end"
         heuristic mis-counted when the .slide-frame close sat on its own line
         below the .slide close (lift passes frame_end = next-frame-start − 1 =
         the frame-close line), dropping the slide's last container close
         (e.g. `.stage`) → +1 div imbalance → R-DOM frame nesting on lift.
         GUARD: the lifted slide's DOM (styles/comments stripped) is div-balanced.

  BUG2 · F-40 selector anchor — source head rules scoped `[data-page="N"] .slide
         .x` were token-swapped to `[data-slide-key="K"] .slide .x`, which needs
         a `.slide` NESTED under the keyed node (none exists) → matches 0 elements
         → the slide's bespoke layout collapses. Correct form fuses the key onto
         `.slide`: `.slide[data-slide-key="K"] .x`.
         GUARD: recovered selectors are fused; no `[data-slide-key=K] .slide`
         never-match form survives.

  BUG3 · F-76 asset copy — the auto-copy scanned only CSS `url(input/…)`, so
         `<img src="input/…">` assets silently failed to carry (broken images)
         while the report still claimed them "carried".
         GUARD: an `<img src="input/…">` asset lands in the dest input/ dir.

The fixture puts the lifted frame FIRST (so its frame_end = the next frame's
start − 1 = its own frame-close line — the exact BUG1 trigger) and gives each
closing </div> its own line.
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIFT = HERE.parent.parent / "assets" / "lift-slides.py"

# Source fixture. hero is frame #1 (followed by `tail`) so its frame_end resolves
# to the frame-close line — the BUG1 off-by-one trigger. The head rules are
# [data-page]-scoped (BUG2). The matrix cell holds an <img src="input/…"> (BUG3).
SRC_HTML = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
[data-page="2"] /* inline comment between token and .slide */ .slide .matrix { display: grid; grid-template-columns: 1fr 1fr; }
[data-page="2"] .slide .cell { padding: 8px; }
@keyframes fadeIn { from { opacity: 0 } to { opacity: 1 } }
</style>
</head><body><div class="deck">
<div class="slide-frame" data-page="2">
<div class="slide" data-layout="content-2col" data-slide-key="hero" data-screen-label="02 Hero" data-accent="blue">
<div class="header"><h2 class="title-zh">Hero</h2></div>
<div class="stage">
<div class="matrix"><div class="cell"><img src="input/icon.svg" alt=""></div></div>
</div>
</div>
</div>
<div class="slide-frame" data-page="1">
<div class="slide" data-layout="cover" data-slide-key="tail" data-screen-label="01">
<div class="stage"><h1>tail</h1></div>
</div>
</div>
</div></body></html>
"""

DST_DECK = ('{"version":"1.0","deck":{"title":"t","author":"a","date":"2026-06"},'
            '"slides":[{"key":"c","layout":"cover","accent":"blue",'
            '"data":{"title":"t","author":"a","date":"2026-06"}}]}')


def _div_balance(html: str) -> int:
    """DOM <div> open/close balance using the validator's method: strip
    comments/scripts/styles, then count via the stdlib parser."""
    body = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    body = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.S)
    body = re.sub(r"<style[^>]*>.*?</style>", "", body, flags=re.S)

    class P(HTMLParser):
        opens = closes = 0

        def handle_starttag(self, tag, attrs):
            if tag == "div":
                self.opens += 1

        def handle_endtag(self, tag):
            if tag == "div":
                self.closes += 1

    p = P()
    p.feed(body)
    p.close()
    return p.opens - p.closes


class LiftSlidesShakeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lift-slides-test-")
        tmp = Path(cls.tmp)
        src_dir = tmp / "src"
        (src_dir / "input").mkdir(parents=True)
        (src_dir / "index.html").write_text(SRC_HTML, encoding="utf-8")
        (src_dir / "input" / "icon.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8")
        cls.dst_dir = tmp / "dst"
        cls.dst_dir.mkdir()
        cls.dst_deck = cls.dst_dir / "deck.json"
        cls.dst_deck.write_text(DST_DECK, encoding="utf-8")

        cls.proc = subprocess.run(
            [sys.executable, str(LIFT), str(src_dir / "index.html"),
             "--key", "hero", str(cls.dst_deck), "--shake"],
            capture_output=True, text=True,
        )

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _hero(self) -> str:
        deck = json.loads(self.dst_deck.read_text(encoding="utf-8"))
        hero = [s for s in deck["slides"] if s.get("key") == "hero"]
        self.assertEqual(len(hero), 1,
                         f"lift did not append exactly one hero slide.\n"
                         f"stdout:\n{self.proc.stdout}\nstderr:\n{self.proc.stderr}")
        return hero[0]["data"]["html"]

    def test_lift_succeeded(self):
        self.assertEqual(self.proc.returncode, 0,
                         f"lift exited {self.proc.returncode}\n{self.proc.stderr}")

    def test_bug1_lifted_slide_div_balanced(self):
        # The dropped-</div> bug left the slide's .stage container unclosed (+1).
        self.assertEqual(_div_balance(self._hero()), 0,
                         "lifted slide DOM is not div-balanced — extract_one "
                         "dropped a closing </div> (BUG1 regressed).")

    def test_bug2_data_page_selectors_fused_not_orphaned(self):
        css = self._hero()
        css = css[:css.rfind("</style>") + len("</style>")]
        # Correct: key fused onto .slide. Never-match: key then a descendant .slide.
        self.assertRegex(
            css, r'\.slide\[data-slide-key="hero"\]\s+\.matrix',
            "recovered [data-page] rule was not fused onto .slide "
            "(BUG2/F-40 regressed) — bespoke layout would collapse.")
        self.assertNotRegex(
            css, r'\[data-slide-key="hero"\]\s+\.slide\s+\.matrix',
            "recovered selector kept the never-match `[data-slide-key] .slide` "
            "form (BUG2/F-40 regressed).")
        # comment-between-token-and-.slide must not leave a phantom descendant
        self.assertNotIn("/* inline comment", css,
                         "selector CSS comment was not stripped before fusion.")

    def test_bug3_img_src_assets_carried(self):
        # <img src="input/…"> (not url()) must be copied to the dest input/ dir.
        self._hero()  # ensure lift ran
        copied = self.dst_dir / "input" / "icon.svg"
        self.assertTrue(copied.is_file(),
                        "<img src='input/icon.svg'> was not carried to the dest "
                        "input/ dir (BUG3/F-76 regressed).")


# Source fixture for the base64-bloat guard: a head per-slide rule inlines a
# >75 KB image as `data:…;base64,…`, referenced TWICE (two rules, same blob) —
# the exact shape `--shake` recovers verbatim. Carried as-is the slide balloons
# to MB-scale → every later render/validate re-parses it → the lift FEELS slow.
SRC_HTML_B64 = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
[data-page="2"] .slide .bg-a {{ background-image: url(data:image/png;base64,{blob}); }}
[data-page="2"] .slide .bg-b {{ background-image: url(data:image/png;base64,{blob}); }}
</style>
</head><body><div class="deck">
<div class="slide-frame" data-page="2">
<div class="slide" data-layout="content-2col" data-slide-key="hero" data-screen-label="02 Hero" data-accent="blue">
<div class="header"><h2 class="title-zh">Hero</h2></div>
<div class="stage"><div class="bg-a"></div><div class="bg-b"></div></div>
</div>
</div>
<div class="slide-frame" data-page="1">
<div class="slide" data-layout="cover" data-slide-key="tail" data-screen-label="01">
<div class="stage"><h1>tail</h1></div>
</div>
</div>
</div></body></html>
"""


class LiftSlidesBase64Test(unittest.TestCase):
    """BUG4 · base64 bloat — `--shake` recovered source-head per-slide CSS
    verbatim, carrying MB-scale inline `data:…;base64,…` images (often the same
    blob 2×+). The slide ballooned to 10-20 MB → every render/validate re-parsed
    it → the lift felt slow. GUARD: oversized blobs are moved to a deduped
    `input/` file and the inline data URI no longer survives in the slide.
    (Pillow-independent: the test blob isn't a real image, so the optional
    downscale branch no-ops and the RAW bytes are externalized — exactly the
    fallback path we want covered.)"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lift-slides-b64-test-")
        tmp = Path(cls.tmp)
        src_dir = tmp / "src"
        (src_dir / "input").mkdir(parents=True)
        # ~80 KB of bytes → ~107 K base64 chars, over B64_EXTERNALIZE_MIN_CHARS.
        import base64 as _b64
        blob = _b64.b64encode(b"\x89PNG\r\n" + bytes(80_000)).decode("ascii")
        (src_dir / "index.html").write_text(
            SRC_HTML_B64.format(blob=blob), encoding="utf-8")
        cls.dst_dir = tmp / "dst"
        cls.dst_dir.mkdir()
        cls.dst_deck = cls.dst_dir / "deck.json"
        cls.dst_deck.write_text(DST_DECK, encoding="utf-8")
        cls.proc = subprocess.run(
            [sys.executable, str(LIFT), str(src_dir / "index.html"),
             "--key", "hero", str(cls.dst_deck), "--shake"],
            capture_output=True, text=True,
        )

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _hero_html(self):
        self.assertEqual(self.proc.returncode, 0,
                         f"lift exited {self.proc.returncode}\n{self.proc.stderr}")
        deck = json.loads(self.dst_deck.read_text(encoding="utf-8"))
        hero = [s for s in deck["slides"] if s.get("key") == "hero"]
        self.assertEqual(len(hero), 1, "lift did not append exactly one hero slide")
        return hero[0]["data"]["html"]

    def test_oversized_base64_removed_from_slide(self):
        self.assertNotIn("base64,", self._hero_html(),
                         "oversized inline base64 still embedded in the lifted "
                         "slide (BUG4 regressed) — render/validate will choke.")

    def test_externalized_to_single_deduped_file(self):
        html = self._hero_html()
        files = list((self.dst_dir / "input").glob("lift-hero-*"))
        self.assertEqual(len(files), 1,
                         f"expected exactly ONE externalized file (dedup of 2 "
                         f"identical refs), got {files}")
        # both refs rewritten to that one path
        self.assertEqual(html.count(f"input/{files[0].name}"), 2,
                         "both duplicate base64 refs should point at the one file")

    def test_small_base64_stays_inline(self):
        # A sub-threshold blob must NOT be externalized (self-contained is fine
        # at small sizes). Lift a fresh source with a tiny data URI.
        tmp = Path(tempfile.mkdtemp(prefix="lift-b64-small-"))
        try:
            import base64 as _b64
            small = _b64.b64encode(b"tiny").decode("ascii")
            src = tmp / "src"
            (src / "input").mkdir(parents=True)
            (src / "index.html").write_text(
                SRC_HTML_B64.format(blob=small), encoding="utf-8")
            dst = tmp / "dst"; dst.mkdir()
            deck = dst / "deck.json"; deck.write_text(DST_DECK, encoding="utf-8")
            subprocess.run(
                [sys.executable, str(LIFT), str(src / "index.html"),
                 "--key", "hero", str(deck), "--shake"],
                capture_output=True, text=True, check=True)
            html = json.loads(deck.read_text())["slides"][-1]["data"]["html"]
            self.assertIn("base64,", html,
                          "small inline base64 was needlessly externalized")
            self.assertFalse(list((dst / "input").glob("lift-hero-*")),
                             "small blob should not have produced an input/ file")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
