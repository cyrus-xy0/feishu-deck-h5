"""Smoke-test deck-cli.py operations on a copy of sample-deck.json:
- set: scalar change persists
- set: invalid schema → rolls back via .bak
- reorder: position changes
- clone: new slide added with unique key

Doesn't try to exhaustively cover all 14 subcommands — just the high-value
contract: backup → write → validate → rollback works.
"""
import json
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
CLI = DECK_JSON / "deck-cli.py"
RENDER = DECK_JSON / "render-deck.py"
SYNC = DECK_JSON / "sync-index-to-deck.py"
VALIDATE = DECK_JSON / "validate-deck.py"
SAMPLE = DECK_JSON / "examples" / "sample-deck.json"


class DeckCliSmokeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="deck-cli-test-")
        self.deck = Path(self.tmp) / "deck.json"
        shutil.copy(SAMPLE, self.deck)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args) -> tuple[int, str, str]:
        proc = subprocess.run(
            [sys.executable, str(CLI), str(self.deck), "--yes", *args],
            capture_output=True, text=True,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def _load(self) -> dict:
        return json.loads(self.deck.read_text(encoding="utf-8"))

    def test_set_scalar_persists(self):
        rc, out, err = self._run("set", "slides.0.data.title", "NEW TITLE")
        self.assertEqual(rc, 0, f"set failed: {err}")
        self.assertEqual(self._load()["slides"][0]["data"]["title"], "NEW TITLE")

    def test_set_by_slide_key_lands_on_right_slide(self):
        # Address a slide by KEY, not array index. Must hit that exact slide
        # wherever it sits — no page#->index hand-conversion, so the off-by-one
        # that _disabled/hidden slides cause can't clobber the wrong page.
        slides = self._load()["slides"]
        key = slides[3]["key"]                       # a mid-deck slide
        rc, out, err = self._run("set", f"slides.{key}.data.title", "BY-KEY-OK")
        self.assertEqual(rc, 0, f"set by key failed: {err}")
        after = self._load()["slides"]
        self.assertEqual(after[3]["data"]["title"], "BY-KEY-OK")
        self.assertNotEqual(after[2].get("data", {}).get("title"), "BY-KEY-OK")
        self.assertNotEqual(after[4].get("data", {}).get("title"), "BY-KEY-OK")

    def test_set_by_unknown_key_errors_not_silent(self):
        rc, out, err = self._run("set", "slides.no-such-key.data.title", "X")
        self.assertNotEqual(rc, 0, "unknown slide key should error, not no-op")

    def test_get_by_slide_key_path(self):
        key = self._load()["slides"][2]["key"]
        self._run("set", "slides.2.data.title", "ROUNDTRIP")
        proc = subprocess.run(
            [sys.executable, str(CLI), str(self.deck),
             "get", f"slides.{key}.data.title"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("ROUNDTRIP", proc.stdout)

    def test_set_invalid_enum_rolls_back(self):
        # accent enum doesn't include "cyan" (R49 encoded in schema) — set
        # should fail + rollback to .bak
        before = self._load()["slides"][0]
        rc, out, err = self._run("set-accent", before["key"], "cyan")
        self.assertNotEqual(rc, 0, "set-accent cyan should fail (R49)")
        after = self._load()["slides"][0]
        self.assertEqual(after.get("accent"), before.get("accent"),
                         "rollback should have preserved original accent")

    def test_reorder_changes_position(self):
        before = [s["key"] for s in self._load()["slides"]]
        rc, out, err = self._run("reorder", "1", "3")  # 1-indexed
        self.assertEqual(rc, 0, f"reorder failed: {err}")
        after = [s["key"] for s in self._load()["slides"]]
        self.assertEqual(after[2], before[0], "slide 1 should now be at position 3")

    def test_clone_creates_new_key(self):
        src = self._load()["slides"][2]["key"]
        rc, out, err = self._run("clone", src, f"{src}-copy")
        self.assertEqual(rc, 0, f"clone failed: {err}")
        keys = [s["key"] for s in self._load()["slides"]]
        self.assertIn(f"{src}-copy", keys)
        # original still present
        self.assertIn(src, keys)

    def test_add_section_sets_chapter_title_and_label_in_one_write(self):
        rc, out, err = self._run(
            "add-section", "2", "chapter-01-ai-capability",
            "--chapter", "01", "--title", "AI 的能力如何了？",
            "--label", "03",
        )
        self.assertEqual(rc, 0, f"add-section failed: {err}\n{out}")
        section = self._load()["slides"][1]
        self.assertEqual(section["key"], "chapter-01-ai-capability")
        self.assertEqual(section["layout"], "section")
        self.assertEqual(section["screen_label"], "03")
        self.assertEqual(section["data"]["chapter_num"], "01.")
        self.assertEqual(section["data"]["title"], "AI 的能力如何了？")

    def test_mutation_lock_covers_load_to_write_transaction(self):
        spec = importlib.util.spec_from_file_location("deck_cli_mod", CLI)
        deck_cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(deck_cli)
        if deck_cli.fcntl is None:
            self.skipTest("fcntl unavailable; deck mutation lock is POSIX-only")

        with deck_cli.deck_mutation_lock(self.deck):
            proc = subprocess.Popen(
                [sys.executable, str(CLI), str(self.deck), "--yes",
                 "set", "deck.title", "SUBPROCESS-TITLE"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            time.sleep(0.25)
            self.assertIsNone(
                proc.poll(),
                "subprocess mutation should wait for the deck lock before loading")
            current = self._load()
            current["deck"]["author"] = "PARENT-WRITE-WHILE-LOCKED"
            self.deck.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")

        out, err = proc.communicate(timeout=10)
        self.assertEqual(proc.returncode, 0, f"locked mutation failed: {err}\n{out}")
        after = self._load()
        self.assertEqual(after["deck"]["title"], "SUBPROCESS-TITLE")
        self.assertEqual(after["deck"]["author"], "PARENT-WRITE-WHILE-LOCKED",
                         "subprocess must load after the lock is released, not "
                         "clobber a newer on-disk field with a stale pre-lock read")


class DeckCliPasteDriftTest(unittest.TestCase):
    """`paste` must (a) copy a prototypes/<demo>.html DIRECT-FILE iframe body
    (old regex only matched prototypes/<dir>/ subdirs → blank iframe) and
    (b) remap retired framework CSS vars (var(--fs-accent4)→var(--fs-teal)) so an
    old slide doesn't render-fail on R-CSSVAR after paste. (P1, 2026-06-02)"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="deck-cli-paste-test-"))
        self.src_dir = self.tmp / "src"
        (self.src_dir / "prototypes").mkdir(parents=True)
        (self.src_dir / "assets" / "shared").mkdir(parents=True)
        (self.src_dir / "prototypes" / "demo.html").write_text(
            "<!doctype html><body>demo</body>", encoding="utf-8")
        (self.src_dir / "assets" / "shared" / "logo.png").write_bytes(b"PNG")
        src_deck = {
            "version": "1.0",
            "deck": {"title": "s", "author": "a", "date": "2026-06"},
            "slides": [{
                "key": "src-raw", "layout": "raw", "accent": "blue",
                "custom_css": '.brand{background-image:url("assets/shared/logo.png")}',
                "data": {"html": '<div class="lead">'
                                 '<b style="color:var(--fs-accent4)">x</b></div>'
                                 '<iframe src="prototypes/demo.html"></iframe>'},
            }],
        }
        (self.src_dir / "deck.json").write_text(json.dumps(src_deck), encoding="utf-8")
        self.dst_dir = self.tmp / "dst"
        self.dst_dir.mkdir()
        self.dst = self.dst_dir / "deck.json"
        shutil.copy(SAMPLE, self.dst)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _paste(self):
        return subprocess.run(
            [sys.executable, str(CLI), str(self.dst), "--yes",
             "paste", "--from", str(self.src_dir / "deck.json"), "--key", "src-raw"],
            capture_output=True, text=True,
        )

    def test_prototype_direct_file_copied(self):
        proc = self._paste()
        self.assertEqual(proc.returncode, 0,
                         f"paste failed: {proc.stderr}\n{proc.stdout}")
        self.assertTrue((self.dst_dir / "prototypes" / "demo.html").is_file(),
                        "prototypes/demo.html direct-file iframe body was not "
                        "copied by paste (blank iframe).")

    def test_retired_var_remapped(self):
        proc = self._paste()
        self.assertEqual(proc.returncode, 0,
                         f"paste failed: {proc.stderr}\n{proc.stdout}")
        deck = json.loads(self.dst.read_text(encoding="utf-8"))
        pasted = [s for s in deck["slides"] if s.get("key") == "src-raw"][0]
        html = pasted["data"]["html"]
        self.assertNotIn("var(--fs-accent4)", html,
                         "paste did not remap retired var(--fs-accent4).")
        self.assertIn("var(--fs-teal)", html,
                      "var(--fs-accent4) should map to var(--fs-teal).")

    def test_shared_asset_copied(self):
        proc = self._paste()
        self.assertEqual(proc.returncode, 0,
                         f"paste failed: {proc.stderr}\n{proc.stdout}")
        self.assertTrue((self.dst_dir / "assets" / "shared" / "logo.png").is_file(),
                        "assets/shared refs in custom_css must be copied from "
                        "downloaded library packages before re-render/publish.")


class DeckCliPasteCanvasAssetTest(unittest.TestCase):
    """`paste` of a `canvas` slide must copy the images it references in
    `data.elements[].src` (a canvas slide has NO data.html — images live only in
    elements[].src). DECKJSON-UNIFIED-INTERMEDIATE-SPEC §7 / Milestone E."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="deck-cli-canvas-paste-"))
        # SOURCE deck: one canvas slide with two image elements under input/.
        self.src_dir = self.tmp / "src"
        (self.src_dir / "input").mkdir(parents=True)
        (self.src_dir / "input" / "img-001.jpg").write_bytes(b"\xff\xd8\xff\xd9JPEGDATA")
        (self.src_dir / "input" / "img-002.png").write_bytes(b"\x89PNG\r\n\x1a\nPNGDATA")
        src_deck = {
            "version": "1.0",
            "deck": {"title": "src", "author": "a", "date": "2026-06"},
            "slides": [{
                "key": "src-canvas", "layout": "canvas",
                "data": {
                    "canvas_w": 1920, "canvas_h": 1080, "source_page": 1,
                    "elements": [
                        {"id": "e1_0", "type": "image", "src": "input/img-001.jpg",
                         "x": 0, "y": 0, "w": 960, "h": 540},
                        {"id": "e1_1", "type": "image", "src": "input/img-002.png",
                         "x": 0, "y": 540, "w": 960, "h": 540},
                        {"id": "e1_2", "type": "text", "x": 100, "y": 100,
                         "w": 400, "h": 80, "runs": [{"text": "标题"}]},
                    ],
                },
            }],
        }
        (self.src_dir / "deck.json").write_text(json.dumps(src_deck), encoding="utf-8")
        self.dst_dir = self.tmp / "dst"
        self.dst_dir.mkdir()
        self.dst = self.dst_dir / "deck.json"
        shutil.copy(SAMPLE, self.dst)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_canvas_element_images_copied(self):
        proc = subprocess.run(
            [sys.executable, str(CLI), str(self.dst), "--yes",
             "paste", "--from", str(self.src_dir / "deck.json"), "--key", "src-canvas"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0,
                         f"canvas paste failed: {proc.stderr}\n{proc.stdout}")
        for fn in ("img-001.jpg", "img-002.png"):
            self.assertTrue((self.dst_dir / "input" / fn).is_file(),
                            f"canvas element image {fn} (data.elements[].src) was "
                            f"not copied on paste — broken image after paste.")
        # the canvas slide is now in the target with its layout intact
        deck = json.loads(self.dst.read_text(encoding="utf-8"))
        pasted = [s for s in deck["slides"] if s.get("key") == "src-canvas"]
        self.assertEqual(len(pasted), 1)
        self.assertEqual(pasted[0]["layout"], "canvas")


class CrossDeckPasteIntoLegacyHtmlTest(unittest.TestCase):
    """SCENARIO 1 (cross-deck): paste a deck.json-native slide INTO a LEGACY
    HTML-only deck (no deck.json).

    Empirically verified behaviour (DECKJSON-UNIFIED-INTERMEDIATE-SPEC §5):
      · `deck-cli paste` operates on a deck.json — it does NOT auto-backfill a
        legacy HTML-only dest. Pasting straight at the dest dir fails with exit 2
        ("deck not found") because there is no deck.json to load.
      · The working sequence is: backfill the dest's deck.json `中间层` from its
        index.html (sync-index-to-deck — auto-engages when the deck.json target
        is ABSENT, so the user need not pass --backfill) → deck-cli paste the
        source slide into the now-backfilled deck.json → re-render.
      · End-to-end result: dest deck.json = the original page(s) as `raw`
        (lifted-marked) + the pasted slide; it re-renders and strict-validates.

    GAP (reported, not fixed here): backfill is a MANUAL prerequisite step, not
    an auto-wire inside deck-cli paste. Acceptable for now (one extra command,
    and sync auto-engages on an absent deck.json), but a future deck-cli paste
    could detect a legacy HTML-only dest and backfill it first."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cross-paste-legacy-"))
        self.dest = self.tmp / "dest"
        self.dest.mkdir()
        self.src = self.tmp / "source"
        self.src.mkdir()
        # DEST: a real deck.json → render → index.html, then MOVE deck.json aside
        # so the dest is HTML-only (a legacy deck).
        dest_deck = {
            "version": "1.0",
            "deck": {"title": "Legacy dest deck"},
            "slides": [
                {"key": "page-one", "layout": "raw", "screen_label": "01 One",
                 "custom_css": ".hero{letter-spacing:.04em}",
                 "data": {"html": '<div class="stage" style="position:absolute;'
                                  'inset:96px;display:flex;align-items:center;">'
                                  '<h1 class="hero" style="font-size:96px;color:'
                                  '#fff;margin:0;">遗留 dest 第一页</h1></div>'}},
                {"key": "page-two", "layout": "raw", "screen_label": "02 Two",
                 "data": {"html": '<div class="stage" style="position:absolute;'
                                  'inset:96px;"><h2 style="font-size:48px;color:'
                                  '#fff;margin:0;">遗留 dest 第二页</h2></div>'}},
            ],
        }
        (self.dest / "deck.json").write_text(
            json.dumps(dest_deck, ensure_ascii=False), encoding="utf-8")
        r0 = subprocess.run(
            [sys.executable, str(RENDER), str(self.dest / "deck.json"),
             str(self.dest) + "/"], capture_output=True, text=True)
        assert r0.returncode == 0, f"dest baseline render failed:\n{r0.stdout}\n{r0.stderr}"
        # MOVE deck.json aside → dest is now legacy HTML-only.
        (self.dest / "deck.json").rename(self.dest / "deck.json.aside")

        # SOURCE: a separate deck.json with one slide to paste.
        src_deck = {
            "version": "1.0",
            "deck": {"title": "Source deck", "author": "a", "date": "2026-06"},
            "slides": [{
                "key": "src-slide", "layout": "raw", "accent": "blue",
                "data": {"html": '<div class="stage" style="position:absolute;'
                                 'inset:96px;display:flex;align-items:center;'
                                 'justify-content:center;"><h1 style="font-size:'
                                 '96px;color:#fff;margin:0;">从别的 deck 粘进来'
                                 '</h1></div>'}},
            ],
        }
        (self.src / "deck.json").write_text(
            json.dumps(src_deck, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_paste_into_legacy_html_only_dest_auto_backfills(self):
        # 无感自动 backfill (spec §10 decision 3): paste into a legacy HTML-only dest
        # (no deck.json, but a sibling index.html) AUTO-backfills the deck.json from
        # the rendered DOM first, then pastes — succeeds (exit 0), no manual step.
        proc = subprocess.run(
            [sys.executable, str(CLI), str(self.dest / "deck.json"), "--yes",
             "paste", "--from", str(self.src / "deck.json"), "--key", "src-slide"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0,
                         "paste into a legacy HTML-only dest should auto-backfill "
                         f"then succeed.\n{proc.stdout}\n{proc.stderr}")
        self.assertIn("auto-backfill", proc.stderr.lower())
        self.assertTrue((self.dest / "deck.json").is_file())
        deck = json.loads((self.dest / "deck.json").read_text(encoding="utf-8"))
        keys = [s["key"] for s in deck["slides"]]
        self.assertIn("src-slide", keys)  # the pasted slide
        self.assertTrue(any(str(s.get("lifted", "")).startswith("backfill:")
                            for s in deck["slides"]),
                        "original pages should be backfilled (lifted=backfill:...)")

    def test_backfill_then_paste_then_render_end_to_end(self):
        # STEP 1: backfill the legacy dest's deck.json from its index.html.
        # sync-index-to-deck AUTO-ENGAGES backfill because the deck.json target is
        # absent (no --backfill flag needed).
        bf = subprocess.run(
            [sys.executable, str(SYNC), str(self.dest / "index.html"),
             str(self.dest / "deck.json")], capture_output=True, text=True)
        self.assertEqual(bf.returncode, 0,
                         f"backfill failed:\n{bf.stdout}\n{bf.stderr}")
        self.assertTrue((self.dest / "deck.json").is_file())
        backfilled = json.loads((self.dest / "deck.json").read_text(encoding="utf-8"))
        # original pages carried as raw + lifted-marked
        self.assertEqual([s["key"] for s in backfilled["slides"]],
                         ["page-one", "page-two"])
        self.assertTrue(all(s["layout"] == "raw" for s in backfilled["slides"]))
        self.assertTrue(all(s["lifted"].startswith("backfill:")
                            for s in backfilled["slides"]))

        # STEP 2: paste the source slide into the now-backfilled dest deck.json.
        ps = subprocess.run(
            [sys.executable, str(CLI), str(self.dest / "deck.json"), "--yes",
             "paste", "--from", str(self.src / "deck.json"), "--key", "src-slide"],
            capture_output=True, text=True)
        self.assertEqual(ps.returncode, 0,
                         f"paste into backfilled dest failed:\n{ps.stdout}\n{ps.stderr}")

        # ASSERT: dest deck.json = original pages (raw) + the pasted slide.
        final = json.loads((self.dest / "deck.json").read_text(encoding="utf-8"))
        keys = [s["key"] for s in final["slides"]]
        self.assertEqual(keys, ["page-one", "page-two", "src-slide"],
                         "dest deck.json should be original pages + pasted slide")
        pasted = next(s for s in final["slides"] if s["key"] == "src-slide")
        self.assertEqual(pasted["layout"], "raw")
        self.assertIn("从别的 deck 粘进来", pasted["data"]["html"])

        # STEP 3: re-render → must pass and reproduce all three keys.
        r2 = subprocess.run(
            [sys.executable, str(RENDER), str(self.dest / "deck.json"),
             str(self.dest) + "/"], capture_output=True, text=True)
        self.assertEqual(r2.returncode, 0,
                         f"re-render of backfilled+pasted dest failed:\n{r2.stdout}\n{r2.stderr}")
        dom_keys = re.findall(
            r'<div class="slide(?:\s[^"]*)?"[^>]*data-slide-key="([^"]+)"',
            (self.dest / "index.html").read_text(encoding="utf-8"))
        self.assertEqual(dom_keys, ["page-one", "page-two", "src-slide"])

        # STEP 4: strict-validate the final deck.json.
        vr = subprocess.run(
            [sys.executable, str(VALIDATE), str(self.dest / "deck.json"), "--strict"],
            capture_output=True, text=True)
        self.assertEqual(vr.returncode, 0,
                         f"final deck.json failed strict validation:\n{vr.stdout}\n{vr.stderr}")


class DeckCliGetPageTest(unittest.TestCase):
    """`get-page` is the read-side replacement for ad-hoc 'json.load + guess the
    field names' extractors: address a slide by key OR 1-based index (#N), and
    --html/--css/--title dump the raw field, unescaped, for piping. F-357."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="deck-cli-getpage-")
        self.deck = Path(self.tmp) / "deck.json"
        shutil.copy(SAMPLE, self.deck)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args) -> tuple[int, str, str]:
        proc = subprocess.run(
            [sys.executable, str(CLI), str(self.deck), *args],
            capture_output=True, text=True,
        )
        return proc.returncode, proc.stdout, proc.stderr

    def _load(self) -> dict:
        return json.loads(self.deck.read_text(encoding="utf-8"))

    def test_key_index_and_hash_resolve_to_same_slide(self):
        key = self._load()["slides"][0]["key"]
        rc_k, out_k, _ = self._run("get-page", key)
        rc_i, out_i, _ = self._run("get-page", "1")
        rc_h, out_h, _ = self._run("get-page", "#1")
        self.assertEqual((rc_k, rc_i, rc_h), (0, 0, 0), "all three refs should resolve")
        head = lambda o: o.splitlines()[0]
        self.assertEqual(head(out_k), head(out_i), "key and index disagree")
        self.assertEqual(head(out_i), head(out_h), "index and #hash disagree")
        self.assertIn(f"key={key}", head(out_k))

    def test_bad_ref_exits_1(self):
        rc, out, err = self._run("get-page", "no-such-slide-xyz")
        self.assertEqual(rc, 1)
        self.assertIn("no slide matches", err)

    def test_html_flag_prints_raw_unescaped_field(self):
        # self-contained: a raw slide with multi-line html, so the test always
        # exercises the dump path (the sample deck has no raw slide).
        raw_html = '<div class="x">原始 <b>HTML</b>\n第二行</div>'
        deck = {
            "version": "1.0",
            "deck": {"title": "t", "author": "a", "date": "2026-06"},
            "slides": [{"key": "raw-one", "layout": "raw", "data": {"html": raw_html}}],
        }
        p = Path(self.tmp) / "raw.json"
        p.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(CLI), str(p), "get-page", "raw-one", "--html"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # raw field round-trips verbatim — a real newline, NOT the JSON-escaped
        # "\n" that `show` would print.
        self.assertEqual(proc.stdout.rstrip("\n"), raw_html)
        self.assertIn("\n第二行", proc.stdout)


class DeckCliNewDeckTest(unittest.TestCase):
    """`new-deck` scaffolds a fresh, schema-valid deck.json (deck meta + a cover
    slide) so a deck can be started without hand-writing JSON or reading the
    1200-line schema. Also normalises a literal <br> in the cover title to a
    newline — the cover title is an ESCAPED field, so a literal <br> would render
    escaped and trip R-ESC-HTML at render time. F-367."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="deck-cli-newdeck-"))
        # parent dir intentionally absent — new-deck must mkdir -p it
        self.deck = self.tmp / "out" / "deck.json"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _new(self, *args) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CLI), str(self.deck), "new-deck", *args],
            capture_output=True, text=True,
        )

    def test_scaffolds_valid_deck_with_cover(self):
        p = self._new("--title", "标题 X", "--author", "杰森", "--date", "2026.06.23")
        self.assertEqual(p.returncode, 0, f"new-deck failed: {p.stderr}\n{p.stdout}")
        self.assertTrue(self.deck.is_file(), "deck.json not created (parent auto-made?)")
        deck = json.loads(self.deck.read_text(encoding="utf-8"))
        self.assertEqual(deck["version"], "1.0")
        self.assertEqual(deck["deck"]["title"], "标题 X")
        self.assertEqual(len(deck["slides"]), 1)
        cover = deck["slides"][0]
        self.assertEqual(cover["layout"], "cover")
        self.assertEqual(cover["data"],
                         {"title": "标题 X", "author": "杰森", "date": "2026.06.23"})
        lint = subprocess.run([sys.executable, str(CLI), str(self.deck), "lint"],
                              capture_output=True, text=True)
        self.assertEqual(lint.returncode, 0,
                         f"scaffolded deck failed schema lint:\n{lint.stdout}")

    def test_cover_title_literal_br_normalised_to_newline(self):
        p = self._new("--title", "Deck", "--author", "A", "--date", "2026.06.23",
                      "--cover-title", "第一行<br>第二行")
        self.assertEqual(p.returncode, 0, p.stderr)
        title = json.loads(self.deck.read_text(encoding="utf-8"))["slides"][0]["data"]["title"]
        self.assertEqual(title, "第一行\n第二行",
                         "literal <br> in cover title should normalise to a newline "
                         "(escaped field → a literal <br> trips R-ESC-HTML).")
        self.assertNotIn("<br>", title)

    def test_refuses_to_overwrite_without_force(self):
        self.assertEqual(
            self._new("--title", "A", "--author", "B", "--date", "2026.06.23").returncode,
            0)
        again = self._new("--title", "C", "--author", "D", "--date", "2026.06.23")
        self.assertNotEqual(again.returncode, 0, "should refuse to overwrite existing deck")
        self.assertEqual(
            json.loads(self.deck.read_text(encoding="utf-8"))["deck"]["title"], "A",
            "refused overwrite must leave the original deck intact")

    def test_force_overwrites(self):
        self._new("--title", "A", "--author", "B", "--date", "2026.06.23")
        forced = subprocess.run(
            [sys.executable, str(CLI), "--force", str(self.deck), "new-deck",
             "--title", "C", "--author", "D", "--date", "2026.06.23"],
            capture_output=True, text=True)
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertEqual(
            json.loads(self.deck.read_text(encoding="utf-8"))["deck"]["title"], "C")


if __name__ == "__main__":
    unittest.main()
