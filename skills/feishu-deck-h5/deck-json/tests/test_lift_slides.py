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
        html = self._hero()["data"]["html"]
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
        return hero[0]["data"]["html"]

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
        return hero[0]["data"]["html"]

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
        return hero[0]["data"]["html"]

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


if __name__ == "__main__":
    unittest.main()
