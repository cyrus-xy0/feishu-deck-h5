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
        return hero[0]["data"]["html"] + "\n" + (hero[0].get("custom_css") or "")

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

    def test_lift_hygiene_moves_styles_out_of_data_html(self):
        deck = json.loads(self.dst_deck.read_text(encoding="utf-8"))
        hero = [s for s in deck["slides"] if s.get("key") == "hero"][0]
        self.assertNotIn("<style", hero["data"]["html"].lower(),
                         "lifted raw data.html must not keep embedded <style>; "
                         "that CSS is global in the target deck.")
        self.assertIn(".matrix", hero.get("custom_css") or "",
                      "recovered per-slide CSS should move into custom_css.")


SRC_HTML_POLLUTION = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"></head>
<body><div class="deck">
<div class="slide-frame" data-page="1">
<div class="slide" data-layout="raw" data-slide-key="polluted" data-screen-label="01 Dirty">
<style data-source="framework">
.slide { transform: scale(.8); }
.card, h1, .stage { position: absolute; left: 0; }
</style>
<div class="stage" onclick="evil()"><h1>Polluted</h1><div class="card">x</div>
<a href="javascript:evil()">unsafe</a><iframe srcdoc="&lt;script&gt;evil()&lt;/script&gt;"></iframe></div>
<script data-source="framework">window.evil = true</script>
</div>
</div>
</div></body></html>
"""


class LiftSlidesPollutionHygieneTest(unittest.TestCase):
    """A lifted page must not carry unscoped CSS or executable markup in data.html.

    This is the failure mode where source-deck CSS like `.slide`, `.card`, `h1`,
    or `.stage` enters the target deck as a raw inline <style> and cascades over
    unrelated pages.
    """

    def test_lifted_pollution_is_consolidated_and_stripped(self):
        with tempfile.TemporaryDirectory(prefix="lift-pollution-") as td:
            tmp = Path(td)
            src = tmp / "src"; src.mkdir()
            (src / "index.html").write_text(SRC_HTML_POLLUTION, encoding="utf-8")
            dst = tmp / "dst"; dst.mkdir()
            deck_path = dst / "deck.json"
            deck_path.write_text(DST_DECK, encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(LIFT), str(src / "index.html"),
                 "--key", "polluted", str(deck_path), "--shake"],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0,
                             f"pollution fixture lift failed:\n{proc.stdout}\n{proc.stderr}")
            deck = json.loads(deck_path.read_text(encoding="utf-8"))
            slide = [s for s in deck["slides"] if s.get("key") == "polluted"][0]
            body = slide["data"]["html"].lower()
            css = slide.get("custom_css") or ""
            self.assertNotIn("<style", body)
            self.assertNotIn("<script", body)
            self.assertNotIn("onclick=", body)
            self.assertNotIn("javascript:", body)
            self.assertNotIn("srcdoc=", body)
            self.assertIn(".card, h1, .stage", css)
            self.assertIn("css hygiene: moved 1 embedded <style>", proc.stdout)
            self.assertIn("script hygiene: stripped 1 <script> block(s), 1 inline handler(s)",
                          proc.stdout)


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
        return hero[0]["data"]["html"] + "\n" + (hero[0].get("custom_css") or "")

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
            slide = json.loads(deck.read_text())["slides"][-1]
            html = slide["data"]["html"] + "\n" + (slide.get("custom_css") or "")
            self.assertIn("base64,", html,
                          "small inline base64 was needlessly externalized")
            self.assertFalse(list((dst / "input").glob("lift-hero-*")),
                             "small blob should not have produced an input/ file")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


# BUG5 · multi-line .slide opening tag — heavily hand-edited decks wrap the
# .slide tag across lines (attrs on their own lines). extract_one() read attrs
# from ONLY the first line, so data-slide-key / data-screen-label (on later
# lines) were missed → key=None → --index shows "?", --key can't find the slide,
# src_key=None, and (worst) the slide_key never reached extract_head_slide_rules
# so the slide's own per-slide CSS was DROPPED → layout collapsed to block flow.
# It also leaked the wrapped attr lines into the body as VISIBLE TEXT.
# (merged-49pages back-1000stores / back-store-pipeline repro, 2026-06-02.)
SRC_HTML_MULTILINE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
[data-page="2"] .slide .matrix { display: grid; grid-template-columns: 1fr 1fr; }
</style>
</head><body><div class="deck">
<div class="slide-frame" data-idx="1">
<div class="slide" data-layout="content-2col" data-page="2"
            data-screen-label="02 Hero"
            data-slide-key="hero" data-accent="blue">
<div class="header"><h2 class="title-zh">Hero</h2></div>
<div class="stage">
<div class="matrix"><div class="cell">x</div></div>
</div>
</div>
</div>
<div class="slide-frame" data-idx="0">
<div class="slide" data-layout="cover" data-slide-key="tail" data-screen-label="01">
<div class="stage"><h1>tail</h1></div>
</div>
</div>
</div></body></html>
"""


class LiftSlidesMultilineTagTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lift-slides-multiline-test-")
        tmp = Path(cls.tmp)
        src_dir = tmp / "src"
        (src_dir / "input").mkdir(parents=True)
        (src_dir / "index.html").write_text(SRC_HTML_MULTILINE, encoding="utf-8")
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

    def _hero(self):
        deck = json.loads(self.dst_deck.read_text(encoding="utf-8"))
        hero = [s for s in deck["slides"] if s.get("key") == "hero"]
        self.assertEqual(len(hero), 1,
                         "--key hero did not resolve through the multi-line "
                         ".slide opening tag (BUG5 regressed).\n"
                         f"stdout:\n{self.proc.stdout}\nstderr:\n{self.proc.stderr}")
        return hero[0]

    def test_lift_succeeded_key_resolved(self):
        self.assertEqual(self.proc.returncode, 0,
                         f"lift exited {self.proc.returncode}\n{self.proc.stderr}")
        self._hero()  # asserts the key was read off the wrapped tag

    def test_no_attr_leak_into_body(self):
        html = self._hero()["data"]["html"]
        self.assertFalse(re.match(r'data-[a-z-]+=', html.lstrip()),
                         "wrapped opening-tag attr lines leaked into the slide "
                         "body as visible text (BUG5 regressed).")
        self.assertNotIn('data-screen-label="02 Hero"', html,
                         "data-screen-label= leaked into the body (BUG5 regressed).")

    def test_per_slide_css_recovered_no_collapse(self):
        slide = self._hero()
        html = slide["data"]["html"] + "\n" + (slide.get("custom_css") or "")
        self.assertRegex(
            html, r'\.slide\[data-slide-key="hero"\]\s+\.matrix',
            "the slide's own [data-page]-scoped grid rule was NOT recovered for "
            "the multi-line-tag slide (BUG5 → layout collapse regressed).")
        self.assertIn("display: grid", html,
                      "recovered per-slide rule lost its grid declaration.")


# BUG6 · lift asset/drift gaps (P1, 2026-06-02) — three classes that left a
# lifted page broken on a CURRENT-framework target:
#   (a) prototypes/<demo>.html DIRECT-FILE iframe body — the copy regex required
#       a trailing slash so only prototypes/<dir>/ subdirs copied; direct files
#       were dropped → blank iframe.
#   (b) a foreign deck's iframe body at a NON-STANDARD local path
#       (assets/custom/<demo>/x.html) — bucketed "other" and never copied.
#   (c) a RETIRED framework CSS var (var(--fs-accent4)) — undefined in the
#       current framework → declaration silently fails on render (R-CSSVAR).
SRC_HTML_P1 = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
[data-page="2"] .slide .lead b { color: var(--fs-accent4); }
</style>
</head><body><div class="deck">
<div class="slide-frame" data-page="2">
<div class="slide" data-layout="content-2col" data-slide-key="hero" data-screen-label="02 Hero" data-accent="blue">
<div class="stage">
<p class="lead"><b>x</b></p>
<iframe src="prototypes/demo.html"></iframe>
<iframe src="assets/custom/widget/widget.html"></iframe>
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


class LiftSlidesAssetAndDriftTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lift-slides-p1-test-")
        tmp = Path(cls.tmp)
        src_dir = tmp / "src"
        (src_dir / "input").mkdir(parents=True)
        (src_dir / "prototypes").mkdir()
        (src_dir / "prototypes" / "demo.html").write_text(
            "<!doctype html><body>demo</body>", encoding="utf-8")
        (src_dir / "assets" / "custom" / "widget").mkdir(parents=True)
        (src_dir / "assets" / "custom" / "widget" / "widget.html").write_text(
            "<!doctype html><body>widget</body>", encoding="utf-8")
        (src_dir / "assets" / "custom" / "widget" / "dep.js").write_text(
            "// sibling dep", encoding="utf-8")
        (src_dir / "index.html").write_text(SRC_HTML_P1, encoding="utf-8")
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
        return hero[0]["data"]["html"] + "\n" + (hero[0].get("custom_css") or "")

    def test_prototype_direct_file_copied(self):
        self._hero_html()
        self.assertTrue((self.dst_dir / "prototypes" / "demo.html").is_file(),
                        "prototypes/demo.html (direct-file iframe body) was not "
                        "copied (BUG6a regressed) → blank iframe.")

    def test_other_iframe_body_folder_copied(self):
        self._hero_html()
        self.assertTrue(
            (self.dst_dir / "assets" / "custom" / "widget" / "widget.html").is_file(),
            "non-standard iframe body assets/custom/widget/widget.html was not "
            "copied (BUG6b regressed) → blank iframe.")
        self.assertTrue(
            (self.dst_dir / "assets" / "custom" / "widget" / "dep.js").is_file(),
            "the iframe demo's sibling dep was not carried (folder copy regressed).")

    def test_retired_css_var_remapped(self):
        html = self._hero_html()
        self.assertNotIn("var(--fs-accent4)", html,
                         "retired var(--fs-accent4) was not remapped (BUG6c "
                         "regressed) → R-CSSVAR render-fail.")
        self.assertIn("var(--fs-teal)", html,
                      "var(--fs-accent4) should map to var(--fs-teal).")


# BUG7 · inline single-file lift gaps (P1, 2026-06-02, wudeli-final.html) —
#   (a) MULTI-CLASS .slide div — an iframe-embed/special page tagged
#       `class="slide embedded-management-page"` was missed by the exact-string
#       matcher → frame keyed "?" / unliftable. _SLIDE_OPEN_RE now allows extra
#       classes (but still excludes class="slide-frame").
#   (b) recovered head rule scoped `[data-slide-key=K][data-layout=X]` — the
#       lifted slide renders as data-layout="raw", so the [data-layout] filter
#       never matches → R-VIS-DEAD-RULE, layout silently lost. The [data-layout]
#       filter is now stripped from recovered head rules too (not just inner CSS).
SRC_HTML_MULTICLASS = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
.slide[data-slide-key="hero"][data-layout="content-2col"] .grid { display: grid; gap: 10px; }
</style>
</head><body><div class="deck">
<div class="slide-frame" data-page="2">
<div class="slide embedded-special-page" data-layout="content-2col" data-slide-key="hero" data-screen-label="02 Hero" data-accent="blue">
<div class="grid"><div class="cell">x</div></div>
</div>
</div>
<div class="slide-frame" data-page="1">
<div class="slide" data-layout="cover" data-slide-key="tail" data-screen-label="01">
<div class="stage"><h1>tail</h1></div>
</div>
</div>
</div></body></html>
"""


class LiftSlidesInlineMulticlassTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lift-slides-multiclass-test-")
        tmp = Path(cls.tmp)
        src_dir = tmp / "src"
        (src_dir / "input").mkdir(parents=True)
        (src_dir / "index.html").write_text(SRC_HTML_MULTICLASS, encoding="utf-8")
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

    def _hero(self):
        deck = json.loads(self.dst_deck.read_text(encoding="utf-8"))
        hero = [s for s in deck["slides"] if s.get("key") == "hero"]
        self.assertEqual(len(hero), 1,
                         "--key hero did not resolve through a MULTI-CLASS .slide "
                         "div `class=\"slide embedded-special-page\"` (BUG7a "
                         f"regressed).\nstdout:\n{self.proc.stdout}\nstderr:\n{self.proc.stderr}")
        return hero[0]["data"]["html"] + "\n" + (hero[0].get("custom_css") or "")

    def test_multiclass_slide_lifts(self):
        self.assertEqual(self.proc.returncode, 0,
                         f"lift exited {self.proc.returncode}\n{self.proc.stderr}")
        self._hero()

    def test_data_layout_filter_stripped_from_recovered_rules(self):
        html = self._hero()
        self.assertNotRegex(
            html, r'\[data-slide-key="hero"\]\[data-layout=',
            "recovered head rule kept its [data-layout] filter (BUG7b regressed) "
            "→ dead on the raw-lifted slide.")
        self.assertRegex(
            html, r'\.slide\[data-slide-key="hero"\]\s+\.grid',
            "recovered grid rule not present/fused after [data-layout] strip.")
        self.assertIn("display: grid", html,
                      "recovered rule lost its grid declaration.")


# BUG8 · base64-in-head-CSS perf + correctness (P1, 2026-06-02, wudeli inline) —
# inline single-file decks embed MB-scale images as url(data:…;base64,…) right in
# the head CSS (a 248MB block on wudeli). extract_head_slide_rules brace-parsed it
# verbatim → O(n²) in _match_brace (≈15s). Fix: stash data: URIs to short tokens
# before parsing, restore only in kept rules. GUARD the correctness of that
# stash/restore: a kept slide-key rule's data: URI survives intact, another
# slide's data: URI is not pulled, and no stash token leaks into the output.
SRC_HTML_BASE64HEAD = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
.slide[data-slide-key="hero"] .bg { background-image: url(data:image/png;base64,iVBORKEEPME12345); }
.slide[data-slide-key="other"] .junk { background-image: url(data:image/png;base64,SHOULDNOTLEAK999); }
</style>
</head><body><div class="deck">
<div class="slide-frame" data-page="2">
<div class="slide" data-layout="content-2col" data-slide-key="hero" data-screen-label="02 Hero" data-accent="blue">
<div class="bg">x</div>
</div>
</div>
<div class="slide-frame" data-page="1">
<div class="slide" data-layout="cover" data-slide-key="tail" data-screen-label="01">
<div class="stage"><h1>tail</h1></div>
</div>
</div>
</div></body></html>
"""


class LiftSlidesBase64HeadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lift-slides-b64head-test-")
        tmp = Path(cls.tmp)
        src_dir = tmp / "src"
        (src_dir / "input").mkdir(parents=True)
        (src_dir / "index.html").write_text(SRC_HTML_BASE64HEAD, encoding="utf-8")
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

    def _hero(self):
        self.assertEqual(self.proc.returncode, 0,
                         f"lift exited {self.proc.returncode}\n{self.proc.stderr}")
        deck = json.loads(self.dst_deck.read_text(encoding="utf-8"))
        hero = [s for s in deck["slides"] if s.get("key") == "hero"]
        self.assertEqual(len(hero), 1, "lift did not append exactly one hero slide")
        return hero[0]["data"]["html"] + "\n" + (hero[0].get("custom_css") or "")

    def test_kept_rule_base64_intact(self):
        html = self._hero()
        self.assertIn("data:image/png;base64,iVBORKEEPME12345", html,
                      "the kept slide-key rule's data: URI was corrupted by the "
                      "stash/restore (BUG8 regressed).")

    def test_other_slide_base64_not_pulled(self):
        html = self._hero()
        self.assertNotIn("SHOULDNOTLEAK999", html,
                         "a different slide's data: URI leaked into the lifted slide.")

    def test_no_stash_token_leaks(self):
        html = self._hero()
        self.assertNotIn("\x00DURI", html,
                         "a base64-stash placeholder token leaked into the output "
                         "(restore failed).")


class LiftSlidesDeCollideCssTest(unittest.TestCase):
    """F-255 · a de-collided lift key must follow into the slide's inlined CSS.

    Lifting `hero` into a target that ALREADY has a `hero` key renames the lifted
    key to `hero-2`. transform() inlined that slide's per-slide CSS under the
    ORIGINAL key (`.slide[data-slide-key="hero"] .matrix`), so the wrapper/entry
    got `hero-2` while its embedded selectors stayed on `hero` → matched nothing
    → garbled slide, dead @keyframes (the exact "lift came over garbled, animation
    gone" failure on the everbright deck, 2026-06-03). Guard BOTH lift sinks.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lift-decollide-test-")
        tmp = Path(cls.tmp)
        src_dir = tmp / "src"
        (src_dir / "input").mkdir(parents=True)
        (src_dir / "index.html").write_text(SRC_HTML, encoding="utf-8")
        (src_dir / "input" / "icon.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8")

        # --- sink A: deck.json --shake, into a deck that already owns key `hero`
        cls.dj_dir = tmp / "dst-json"
        cls.dj_dir.mkdir()
        cls.dj_deck = cls.dj_dir / "deck.json"
        cls.dj_deck.write_text(
            '{"version":"1.0","deck":{"title":"t","author":"a","date":"2026-06"},'
            '"slides":[{"key":"hero","layout":"cover","accent":"blue",'
            '"data":{"title":"t","author":"a","date":"2026-06"}}]}',
            encoding="utf-8")
        cls.proc_json = subprocess.run(
            [sys.executable, str(LIFT), str(src_dir / "index.html"),
             "--key", "hero", str(cls.dj_deck), "--shake"],
            capture_output=True, text=True,
        )

        # --- sink B: --to-html, into a legacy index.html that already owns `hero`
        cls.html_dir = tmp / "dst-html"
        (cls.html_dir / "input").mkdir(parents=True)
        cls.dst_html = cls.html_dir / "index.html"
        cls.dst_html.write_text(
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '</head><body><div class="deck">\n'
            '<div class="slide-frame">\n'
            '<div class="slide" data-layout="cover" data-slide-key="hero" '
            'data-screen-label="01 existing"><div class="stage"><h1>own hero</h1>'
            '</div></div>\n</div>\n'
            '</div></body></html>\n', encoding="utf-8")
        cls.proc_html = subprocess.run(
            [sys.executable, str(LIFT), str(src_dir / "index.html"),
             "--key", "hero", str(cls.dst_html), "--shake"],
            capture_output=True, text=True,
        )

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # ---- sink A: deck.json --shake ----
    def _lifted_json_html(self) -> str:
        self.assertEqual(self.proc_json.returncode, 0,
                         f"deck.json lift exited {self.proc_json.returncode}\n"
                         f"{self.proc_json.stderr}")
        deck = json.loads(self.dj_deck.read_text(encoding="utf-8"))
        lifted = [s for s in deck["slides"] if s.get("key") == "hero-2"]
        self.assertEqual(len(lifted), 1,
                         "lift did not de-collide the key to 'hero-2'.\n"
                         f"keys: {[s.get('key') for s in deck['slides']]}\n"
                         f"stdout:\n{self.proc_json.stdout}")
        return lifted[0]["data"]["html"] + "\n" + (lifted[0].get("custom_css") or "")

    def test_json_inlined_css_follows_decollided_key(self):
        css = self._lifted_json_html()
        self.assertRegex(
            css, r'\.slide\[data-slide-key="hero-2"\]\s+\.matrix',
            "inlined per-slide CSS did not follow the de-collided key to "
            "'hero-2' (F-255 regressed) — slide renders unstyled.")
        self.assertNotRegex(
            css, r'data-slide-key="hero"(?!-)',
            "a bare 'hero' selector survived in the de-collided slide's CSS "
            "(F-255 regressed) — it now matches the WRONG (original) page.")

    def test_json_original_hero_untouched(self):
        deck = json.loads(self.dj_deck.read_text(encoding="utf-8"))
        orig = [s for s in deck["slides"] if s.get("key") == "hero"]
        self.assertEqual(len(orig), 1, "the pre-existing 'hero' slide vanished.")
        self.assertEqual(orig[0]["layout"], "cover",
                         "the de-collision rewrote the WRONG slide.")

    # ---- sink B: --to-html ----
    def test_to_html_inlined_css_follows_decollided_key(self):
        self.assertEqual(self.proc_html.returncode, 0,
                         f"--to-html lift exited {self.proc_html.returncode}\n"
                         f"{self.proc_html.stderr}")
        html = self.dst_html.read_text(encoding="utf-8")
        # the spliced frame's wrapper got hero-2; its <style> must too.
        self.assertIn('data-slide-key="hero-2"', html,
                      "--to-html did not de-collide the wrapper key to 'hero-2'.")
        self.assertRegex(
            html, r'\.slide\[data-slide-key="hero-2"\]\s+\.matrix',
            "--to-html embedded CSS did not follow the de-collided key "
            "(F-255 regressed).")
        # exactly one bare `hero` slide remains (the target's own pre-existing
        # one); the lifted page's selectors are all rekeyed to hero-2.
        self.assertEqual(
            len(re.findall(r'data-slide-key="hero"(?!-)', html)), 1,
            "expected exactly one bare 'hero' (the target's own slide); the "
            "lifted page's CSS leaked bare-'hero' selectors (F-255 regressed).")


RENDER = HERE.parent / "render-deck.py"
VALIDATE = HERE.parent / "validate-deck.py"


class LiftFromLegacyHtmlOnlySourceIntoDeckJsonTest(unittest.TestCase):
    """SCENARIO 2 (cross-deck): lift ONE page FROM a LEGACY HTML-only deck (no
    deck.json) INTO a deck.json deck.

    Empirically verified behaviour (DECKJSON-UNIFIED-INTERMEDIATE-SPEC §5):
      · lift-slides.py reads the source's index.html DIRECTLY (frame-based DOM
        parsing) — the SOURCE never needs a deck.json, and lift does NOT backfill
        it. There is no backfill prerequisite for this direction at all.
      · The selected page becomes a `layout: "raw"` slide ADDED to the dest's
        deck.json (the dest's `中间层` gets the page appended), `lifted`-marked +
        carrying structured `lift_origin` provenance.
      · It carries faithfully (content + the source's per-slide CSS, consolidated
        into custom_css instead of left as global data.html <style>), re-renders,
        and strict-validates.

    This is the native cross-deck path: no manual backfill step is required (in
    contrast to Scenario 1's paste-into-legacy-dest, which DOES require a backfill
    prerequisite). Reported as: WORKS, no gap."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lift-from-legacy-src-")
        tmp = Path(cls.tmp)
        # SOURCE: a real 2-slide deck.json → render → index.html, then MOVE the
        # deck.json aside so the source is legacy HTML-only.
        cls.src_dir = tmp / "source"
        cls.src_dir.mkdir()
        src_deck = {
            "version": "1.0",
            "deck": {"title": "Legacy source deck", "author": "a", "date": "2026-06"},
            "slides": [
                {"key": "src-page-a", "layout": "raw", "screen_label": "01 A",
                 "data": {"html": '<div class="stage" style="position:absolute;'
                                  'inset:96px;display:flex;align-items:center;">'
                                  '<h1 style="font-size:96px;color:#fff;margin:0;">'
                                  'Source page A</h1></div>'}},
                {"key": "src-page-b", "layout": "raw", "screen_label": "02 B",
                 "custom_css": ".lifted-marker{letter-spacing:.05em}",
                 "data": {"html": '<div class="stage" style="position:absolute;'
                                  'inset:96px;"><h2 class="lifted-marker" '
                                  'style="font-size:64px;color:#fff;margin:0;">'
                                  'Source page B</h2><p style="font-size:28px;'
                                  'color:rgba(255,255,255,.8);margin:32px 0 0;">'
                                  '这一页要被 lift 进 deck.json dest</p></div>'}},
            ],
        }
        (cls.src_dir / "deck.json").write_text(
            json.dumps(src_deck, ensure_ascii=False), encoding="utf-8")
        r0 = subprocess.run(
            [sys.executable, str(RENDER), str(cls.src_dir / "deck.json"),
             str(cls.src_dir) + "/"], capture_output=True, text=True)
        assert r0.returncode == 0, f"source render failed:\n{r0.stdout}\n{r0.stderr}"
        # MOVE the source deck.json aside → source is now legacy HTML-only.
        (cls.src_dir / "deck.json").rename(cls.src_dir / "deck.json.aside")

        # DEST: a deck.json-native deck (one existing slide).
        cls.dst_dir = tmp / "dest"
        cls.dst_dir.mkdir()
        cls.dst_deck = cls.dst_dir / "deck.json"
        dst_deck = {
            "version": "1.0",
            "deck": {"title": "Dest deck.json deck", "author": "a", "date": "2026-06"},
            "slides": [
                {"key": "dest-existing", "layout": "raw",
                 "data": {"html": '<div class="stage" style="position:absolute;'
                                  'inset:96px;display:flex;align-items:center;">'
                                  '<h1 style="font-size:96px;color:#fff;margin:0;">'
                                  'Dest page one</h1></div>'}},
            ],
        }
        cls.dst_deck.write_text(json.dumps(dst_deck, ensure_ascii=False),
                                encoding="utf-8")

        # LIFT one page (src-page-b) from the HTML-only source into the dest deck.json.
        cls.proc = subprocess.run(
            [sys.executable, str(LIFT), str(cls.src_dir / "index.html"),
             "--key", "src-page-b", str(cls.dst_deck)],
            capture_output=True, text=True)

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _dest(self):
        return json.loads(self.dst_deck.read_text(encoding="utf-8"))

    def test_lift_from_no_deckjson_source_succeeded(self):
        # The source is HTML-only — lift reads its index.html directly, no
        # backfill of the source required.
        self.assertEqual(self.proc.returncode, 0,
                         f"lift from HTML-only source failed: exit "
                         f"{self.proc.returncode}\n{self.proc.stdout}\n{self.proc.stderr}")

    def test_page_added_as_raw_slide_to_dest_deckjson(self):
        deck = self._dest()
        keys = [s["key"] for s in deck["slides"]]
        self.assertEqual(keys, ["dest-existing", "src-page-b"],
                         "lifted page was not appended to the dest deck.json")
        lifted = next(s for s in deck["slides"] if s["key"] == "src-page-b")
        self.assertEqual(lifted["layout"], "raw",
                         "lifted page should land as a raw slide")
        self.assertTrue(lifted.get("lifted", "").startswith("source#"),
                        "lifted slide should carry `lifted` provenance")
        self.assertIn("lift_origin", lifted,
                      "lifted slide should carry structured lift_origin provenance")

    def test_lifted_content_and_custom_css_carried(self):
        lifted = next(s for s in self._dest()["slides"] if s["key"] == "src-page-b")
        html = lifted["data"]["html"]
        self.assertIn("Source page B", html, "lifted page content not carried")
        self.assertIn("这一页要被 lift", html, "lifted page body text not carried")
        # the source's per-slide custom_css travels, but now in the safe
        # custom_css home rather than a global inline <style> inside data.html.
        self.assertIn("lifted-marker", lifted.get("custom_css") or "",
                      "source per-slide custom_css was not carried with the page")
        self.assertNotIn("<style", html.lower(),
                         "lifted raw data.html should not retain embedded <style>")

    def test_dest_renders_and_validates_after_lift(self):
        r = subprocess.run(
            [sys.executable, str(RENDER), str(self.dst_deck), str(self.dst_dir) + "/"],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 0,
                         f"dest re-render after lift failed:\n{r.stdout}\n{r.stderr}")
        html = (self.dst_dir / "index.html").read_text(encoding="utf-8")
        # exactly one .slide WRAPPER for the lifted key (extra data-slide-key hits
        # are inside the carried scoped custom_css <style> block — not wrappers).
        wrappers = re.findall(
            r'<div class="slide(?:\s[^"]*)?"[^>]*data-slide-key="src-page-b"', html)
        self.assertEqual(len(wrappers), 1,
                         "lifted page should produce exactly one .slide wrapper")
        v = subprocess.run(
            [sys.executable, str(VALIDATE), str(self.dst_deck), "--strict"],
            capture_output=True, text=True)
        self.assertEqual(v.returncode, 0,
                         f"dest deck.json failed strict validation after lift:\n"
                         f"{v.stdout}\n{v.stderr}")


# F-332 · the framework drives present-mode fit-scale through the `.slide` root's
# `transform: scale(var(--fs-scale))`. `--shake` recovers a source page-entrance
# animation (`fs-page-enter`) onto the root; if its keyframes set `transform`
# (fill-mode `both` freezes the root at `scale(1)`), the fit-scale is overridden
# and the slide renders unscaled → overflows/clips at non-16:9 viewports. The lift
# must strip `transform` from root-applied keyframes (the fade survives) while
# leaving CHILD animations (here `spin` on `.spinner`) untouched.
SRC_HTML_ROOTANIM = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
@keyframes fs-page-enter { from { opacity:0; transform:translateY(24px) scale(.985);} to { opacity:1; transform:translateY(0) scale(1);} }
@keyframes spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }
.deck[data-mode="present"] .slide-frame.is-current .slide[data-slide-key="hero"] { animation: fs-page-enter .65s cubic-bezier(.2,.8,.2,1) both; }
.slide[data-slide-key="hero"] .spinner { animation: spin 2s linear infinite; }
</style>
</head><body><div class="deck">
<div class="slide-frame" data-page="2">
<div class="slide" data-layout="content-2col" data-slide-key="hero" data-screen-label="02 Hero" data-accent="blue">
<div class="header"><h2 class="title-zh">Hero</h2></div>
<div class="stage"><div class="spinner">x</div></div>
</div>
</div>
<div class="slide-frame" data-page="1">
<div class="slide" data-layout="cover" data-slide-key="tail" data-screen-label="01">
<div class="stage"><h1>tail</h1></div>
</div>
</div>
</div></body></html>
"""


def _kf_block(css: str, name: str) -> str:
    """Brace-matched `@keyframes <name> {...}` text, or '' if absent."""
    m = re.search(r'@(?:-webkit-|-moz-)?keyframes\s+' + re.escape(name) + r'\s*\{', css)
    if not m:
        return ""
    i, depth = m.end(), 1
    while i < len(css) and depth:
        if css[i] == '{':
            depth += 1
        elif css[i] == '}':
            depth -= 1
        i += 1
    return css[m.start():i]


class LiftRootAnimFitScaleTest(unittest.TestCase):
    """F-332: a page-entrance animation recovered onto the `.slide` root must not
    carry `transform` — it would clobber the present-mode fit-scale and the slide
    would render unscaled/overflowing at non-16:9 viewports."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lift-rootanim-test-")
        tmp = Path(cls.tmp)
        src_dir = tmp / "src"
        (src_dir / "input").mkdir(parents=True)
        (src_dir / "index.html").write_text(SRC_HTML_ROOTANIM, encoding="utf-8")
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
        return hero[0]["data"]["html"] + "\n" + (hero[0].get("custom_css") or "")

    def test_lift_succeeded(self):
        self.assertEqual(self.proc.returncode, 0,
                         f"lift exited {self.proc.returncode}\n{self.proc.stderr}")

    def test_root_animation_rule_recovered(self):
        # the page-enter animation must still land on the `.slide` root (we keep
        # the entrance, only neuter its transform) — else the test is a no-op.
        css = self._hero()
        self.assertRegex(
            css, r'\.slide\[data-slide-key="hero"\][^{}]*\{[^}]*animation[^}]*fs-page-enter',
            "page-enter animation was not recovered onto the .slide root "
            "(fixture/recovery changed) — test no longer exercises F-332.")

    def test_root_keyframe_transform_stripped(self):
        # the clobbering transform must be gone from the root-applied keyframe.
        kf = _kf_block(self._hero(), "fs-page-enter")
        self.assertTrue(kf, "fs-page-enter @keyframes was not pulled into the slide.")
        self.assertNotIn("transform", kf,
                          "fs-page-enter keyframe still carries `transform` — it "
                          "freezes the .slide root scale and overrides the "
                          "present-mode fit-scale (F-332 regressed).")

    def test_root_keyframe_fade_preserved(self):
        # opacity (the fade) must survive the transform strip — no over-stripping.
        kf = _kf_block(self._hero(), "fs-page-enter")
        self.assertIn("opacity", kf,
                      "transform strip also removed opacity — the fade entrance "
                      "was lost (over-stripping).")

    def test_child_animation_transform_preserved(self):
        # a CHILD animation (`spin` on `.spinner`) is not on the root → its
        # transform must be left intact (the strip must not over-reach).
        kf = _kf_block(self._hero(), "spin")
        self.assertTrue(kf, "spin @keyframes was not pulled into the slide.")
        self.assertIn("rotate", kf,
                      "child `.spinner` animation lost its transform — the strip "
                      "over-reached beyond .slide-root animations (F-332).")


# ── F-324: --scan pre-lift health report ─────────────────────────────────────
# `--scan` sweeps the whole source and flags frames whose content is runtime/JS-
# injected (so a deck.json lift lands them empty): iframe demos, image-slot
# placeholders, and frames the lifter can't parse. These guards assert it flags
# the dynamic classes and leaves a genuinely static page alone (no false
# positive on a page that fills its picture via <img src>).
SCAN_SRC = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"></head>
<body><div class="deck">
<div class="slide-frame" data-page="1">
<div class="slide" data-layout="content-2col" data-slide-key="clean-imgs" data-screen-label="01 Clean">
<div class="stage">
<div class="pic"><img src="input/photo.jpg" alt=""></div>
</div>
</div>
</div>
<div class="slide-frame" data-page="2">
<div class="slide" data-layout="iframe-embed" data-slide-key="iframe-demo" data-screen-label="02 Demo">
<div class="stage">
<iframe id="demo" src="about:blank" loading="lazy"></iframe>
</div>
</div>
</div>
<div class="slide-frame" data-page="3">
<div class="slide" data-layout="content-2col" data-slide-key="photo-slots" data-screen-label="03 Photos">
<div class="stage">
<div class="photo-cell p1" role="img" aria-label="a"></div>
<div class="photo-cell p2" role="img" aria-label="b"></div>
</div>
</div>
</div>
</div></body></html>
"""


class LiftSlidesScanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lift-scan-test-")
        src = Path(cls.tmp) / "index.html"
        src.write_text(SCAN_SRC, encoding="utf-8")
        cls.proc = subprocess.run(
            [sys.executable, str(LIFT), str(src), "--scan"],
            capture_output=True, text=True)
        cls.out = cls.proc.stdout

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_scan_exits_clean(self):
        self.assertEqual(self.proc.returncode, 0,
                         f"--scan exited {self.proc.returncode}\n{self.proc.stderr}")

    def test_scan_flags_iframe_embed(self):
        self.assertIn("[iframe-embed]", self.out)
        self.assertIn("iframe-demo", self.out)

    def test_scan_flags_empty_image_slots(self):
        self.assertIn("[empty-image-slots]", self.out)
        self.assertIn("photo-slots", self.out)
        self.assertIn("2 image-slot placeholder", self.out)

    def test_scan_does_not_flag_static_image_page(self):
        # a content page that fills its picture via <img src> is NOT a false
        # positive — its key must never appear in the flagged listing.
        self.assertNotIn("clean-imgs", self.out)
        self.assertIn("1 frame(s) lift cleanly", self.out)


# ── F-376 / F-377 / F-378 (lift-slides body-swap + asset/prune fixes) ────────

# Background image referenced ONLY by a [data-page] HEAD rule's url('input/…') —
# never in the slide markup. Step 5's asset scan ran BEFORE head-recovery injects
# this rule, so pre-F-376 the CSS came over but the file did NOT (broken bg; the
# user had to hand-copy it). Distinct from BUG3, which is an inline <img src>.
SRC_HTML_HEADBG = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
[data-page="2"] .slide .hero-bg { background-image: url('input/headbg.png'); background-size: cover; }
</style>
</head><body><div class="deck">
<div class="slide-frame" data-page="2">
<div class="slide" data-layout="content-2col" data-slide-key="hero" data-screen-label="02 Hero" data-accent="blue">
<div class="header"><h2 class="title-zh">Hero</h2></div>
<div class="stage"><div class="hero-bg"></div></div>
</div>
</div>
<div class="slide-frame" data-page="1">
<div class="slide" data-layout="cover" data-slide-key="tail" data-screen-label="01">
<div class="stage"><h1>tail</h1></div>
</div>
</div>
</div></body></html>
"""


class LiftSlidesHeadBgAssetTest(unittest.TestCase):
    """F-376 · an image referenced ONLY by a recovered [data-page] head rule
    (url('input/…')) must be CARRIED. Step 5's input-copy ran before head-recovery
    injected the rule, so the file was left behind (CSS landed, image 404'd).
    GUARD: the file lands in dest input/ and the recovered rule references it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lift-slides-headbg-test-")
        tmp = Path(cls.tmp)
        src_dir = tmp / "src"
        (src_dir / "input").mkdir(parents=True)
        (src_dir / "index.html").write_text(SRC_HTML_HEADBG, encoding="utf-8")
        (src_dir / "input" / "headbg.png").write_bytes(b"\x89PNG\r\n\x1a\n fake")
        cls.dst_dir = tmp / "dst"
        cls.dst_dir.mkdir()
        cls.dst_deck = cls.dst_dir / "deck.json"
        cls.dst_deck.write_text(DST_DECK, encoding="utf-8")
        cls.proc = subprocess.run(
            [sys.executable, str(LIFT), str(src_dir / "index.html"),
             "--key", "hero", str(cls.dst_deck), str(cls.dst_dir), "--shake"],
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
        return hero[0]["data"]["html"] + "\n" + (hero[0].get("custom_css") or "")

    def test_head_css_background_file_carried(self):
        html = self._hero_html()
        self.assertIn("input/headbg.png", html,
                      "recovered head-CSS background rule did not come over")
        carried = self.dst_dir / "input" / "headbg.png"
        self.assertTrue(carried.is_file(),
                        "head-CSS url('input/headbg.png') background was NOT carried "
                        "to dest input/ (F-376 regressed) — broken background on lift.")


class LiftSlidesPruneDeadTest(unittest.TestCase):
    """F-377 · --shake is over-inclusive: it inlines the slide's WHOLE
    [data-layout=content-2col] ruleset, but a bespoke-body slide (here a .matrix
    grid) uses none of content-2col's .col-text/.col-visual → those rescoped rules
    are DEAD (R-VIS-DEAD-RULE noise + dead inline weight). GUARD: rules whose every
    descendant class is absent from the markup are pruned, while a live framework
    rule (.header — the slide HAS one) and the slide's own recovered author rule
    (.matrix) are kept."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lift-slides-prune-test-")
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
             "--key", "hero", str(cls.dst_deck), str(cls.dst_dir), "--shake"],
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
        hero = [s for s in deck["slides"] if s.get("key") == "hero"][0]
        return hero["data"]["html"] + "\n" + (hero.get("custom_css") or "")

    def test_dead_framework_rules_pruned(self):
        html = self._hero_html()
        self.assertNotIn(".col-text", html,
                         "dead content-2col .col-text rule was not pruned (F-377).")
        self.assertNotIn(".col-visual", html,
                         "dead content-2col .col-visual rule was not pruned (F-377).")

    def test_live_framework_rule_kept(self):
        # the slide HAS a .header → its inlined framework rule must survive (proves
        # the inline happened AND the prune was not over-aggressive).
        self.assertIn("] .header", self._hero_html(),
                      "live framework .header rule was wrongly pruned (F-377).")

    def test_recovered_author_rule_kept(self):
        # prune touches only the AUTO-INLINED block, never recovered author CSS.
        self.assertRegex(self._hero_html(),
                         r'\.slide\[data-slide-key="hero"\]\s+\.matrix',
                         "recovered .matrix rule was wrongly pruned (F-377 hit the "
                         "wrong block).")


# Replace-in-place target: slot 2 carries a sentinel key/screen_label/title that
# `--replace --keep-title` MUST preserve while swapping in the source body.
DST_DECK_REPLACE = json.dumps({
    "version": "1.0",
    "deck": {"title": "t", "author": "a", "date": "2026-06"},
    "slides": [
        {"key": "c", "layout": "cover", "accent": "blue",
         "data": {"title": "t", "author": "a", "date": "2026-06"}},
        {"key": "tgt2", "layout": "raw", "screen_label": "99 KEEP",
         "data": {"html": '<div class="header">'
                          '<h2 class="title-zh">原始标题保留我</h2></div>'
                          '<div class="stage">old body</div>'}},
        {"key": "filler3", "layout": "raw", "screen_label": "98 FILL",
         "data": {"html": '<div class="header">'
                          '<h2 class="title-zh">第三页不动</h2></div>'
                          '<div class="stage">keep me</div>'}},
    ],
}, ensure_ascii=False)


class LiftSlidesReplaceTest(unittest.TestCase):
    """F-378 · `--replace N --keep-title` overwrites slot N's BODY with the lifted
    source frame while KEEPING the slot's key + screen_label + visible title.
    GUARD: identity + title preserved, body swapped, lifted CSS rescoped to the
    target key, sibling slots untouched, slide count steady."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="lift-slides-replace-test-")
        tmp = Path(cls.tmp)
        src_dir = tmp / "src"
        (src_dir / "input").mkdir(parents=True)
        (src_dir / "index.html").write_text(SRC_HTML, encoding="utf-8")
        (src_dir / "input" / "icon.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8")
        cls.dst_dir = tmp / "dst"
        cls.dst_dir.mkdir()
        cls.dst_deck = cls.dst_dir / "deck.json"
        cls.dst_deck.write_text(DST_DECK_REPLACE, encoding="utf-8")
        cls.proc = subprocess.run(
            [sys.executable, str(LIFT), str(src_dir / "index.html"),
             "--key", "hero", str(cls.dst_deck), str(cls.dst_dir),
             "--shake", "--replace", "2", "--keep-title"],
            capture_output=True, text=True,
        )
        cls.deck = json.loads(cls.dst_deck.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_lift_succeeded(self):
        self.assertEqual(self.proc.returncode, 0,
                         f"replace lift exited {self.proc.returncode}\n{self.proc.stderr}")

    def test_slide_count_unchanged(self):
        self.assertEqual(len(self.deck["slides"]), 3,
                         "--replace must overwrite in place, not append.")

    def test_target_identity_preserved(self):
        slot = self.deck["slides"][1]
        self.assertEqual(slot["key"], "tgt2", "target slot key not preserved.")
        self.assertEqual(slot["screen_label"], "99 KEEP",
                         "target slot screen_label not preserved.")

    def test_title_kept_body_swapped(self):
        html = self.deck["slides"][1]["data"]["html"]
        self.assertIn("原始标题保留我", html, "--keep-title dropped the target title.")
        self.assertNotIn(">Hero<", html,
                         "source frame title leaked in (keep-title failed).")
        self.assertIn("matrix", html, "source body was not swapped into the slot.")

    def test_css_rescoped_to_target_key(self):
        css = self.deck["slides"][1].get("custom_css") or ""
        self.assertIn('data-slide-key="tgt2"', css,
                      "lifted CSS not rescoped to the target slot key.")
        self.assertNotIn('data-slide-key="hero"', css,
                         "source key leaked into the replaced slot — its selectors "
                         "would match nothing under the tgt2 wrapper.")

    def test_sibling_slots_untouched(self):
        self.assertEqual(self.deck["slides"][0]["key"], "c")
        self.assertIn("第三页不动", self.deck["slides"][2]["data"]["html"],
                      "a sibling slot was clobbered by --replace.")


if __name__ == "__main__":
    unittest.main()
