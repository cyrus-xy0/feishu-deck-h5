"""Tests for the F-267 repair-lifted.py orchestrator AND the F-281b lift-slides
write-after-validate + rollback contract.

repair-lifted.py is a THIN shell-out wrapper: it decides WHICH of the existing
lifted-repair tools apply (by file existence + a head-CSS precondition scan) and
runs them in a fixed order, dry-run-FIRST. These tests drive the real CLI and
assert:

  · --help parses (the orchestrator is invokable)
  · dry-run is the DEFAULT and changes NOTHING (no deck.json mtime change, no
    .bak turds) while printing the proven step order
  · the migrate-head-css step is gated on actual head/deck-level per-slide CSS
    (included when present, skipped when absent)
  · --apply runs the full pipeline and leaves a strict-VALID deck.json + a
    rendered index.html

F-281b (lift-slides write-after-validate + rollback) is co-tested here because
it is the safety net the repair pipeline relies on (a lift that produces an
invalid deck.json must NOT land on disk):

  · happy path: a clean lift now re-validates (prints the post-lift PASS line)
  · failure path: a lift whose RESULT fails `validate-deck --strict` is rolled
    back byte-for-byte (the pre-lift deck.json is restored) and exits non-zero
"""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
REPAIR = DECK_JSON / "repair-lifted.py"
RENDER = DECK_JSON / "render-deck.py"
VALIDATE = DECK_JSON / "validate-deck.py"
LIFT = DECK_JSON.parent / "assets" / "lift-slides.py"


def _raw_slide(key, label, html):
    return {"key": key, "layout": "raw", "screen_label": label,
            "data": {"html": html}}


_STAGE = ('<div class="stage" style="position:absolute;inset:96px;'
          'display:flex;align-items:center">'
          '<h1 style="font-size:96px;color:#fff;margin:0">{t}</h1></div>')


def _write_deck(path, title, slides):
    path.write_text(json.dumps(
        {"version": "1.0", "deck": {"title": title, "author": "a", "date": "2026-06"},
         "slides": slides}, ensure_ascii=False), encoding="utf-8")


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


class RepairLiftedHelpTest(unittest.TestCase):
    def test_help_parses(self):
        r = _run([sys.executable, str(REPAIR), "--help"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("repair-lifted", r.stdout)
        self.assertIn("--apply", r.stdout)
        self.assertIn("--dry-run", r.stdout)


class RepairLiftedDryRunTest(unittest.TestCase):
    """Default = dry-run: prints the proven step order, writes nothing."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="repair-dry-")
        d = Path(cls.tmp)
        cls.deck = d / "deck.json"
        # A lifted-style deck: one normal slide + one lifted-marked raw slide.
        _write_deck(cls.deck, "Dry", [
            _raw_slide("a", "01 A", _STAGE.format(t="A")),
            {**_raw_slide("b", "02 B", _STAGE.format(t="B")),
             "lifted": "src#b"},
        ])
        cls.sha_before = _sha(cls.deck)
        cls.r = _run([sys.executable, str(REPAIR), str(d)])

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_dry_run_succeeds(self):
        self.assertEqual(self.r.returncode, 0,
                         f"{self.r.stdout}\n{self.r.stderr}")

    def test_dry_run_label_shown(self):
        self.assertIn("DRY-RUN", self.r.stdout)
        self.assertIn("NOTHING was changed", self.r.stdout)

    def test_dry_run_writes_nothing(self):
        self.assertEqual(_sha(self.deck), self.sha_before,
                         "dry-run modified deck.json (must be a pure preview)")
        baks = list(Path(self.tmp).glob("deck.json.bak*"))
        self.assertEqual(baks, [],
                         f"dry-run left backup turds: {baks}")

    def test_step_order_is_heal_clean_reconcile(self):
        # No index.html present, deck.json present → migrate/backfill skipped,
        # the three CSS repairs run in this exact order.
        out = self.r.stdout
        i_heal = out.find("heal-lifted")
        i_clean = out.find("clean-lifted-css")
        i_recon = out.find("reconcile-lifted")
        self.assertTrue(0 <= i_heal < i_clean < i_recon,
                        f"steps out of order:\n{out}")

    def test_backfill_skipped_when_deckjson_present(self):
        self.assertIn("backfill        SKIP", self.r.stdout)


class RepairLiftedMigrateGateTest(unittest.TestCase):
    """The migrate-head-css step is gated on actual head/deck-level per-slide
    CSS in index.html — included when present, skipped when absent."""

    def _mk(self, head_css):
        tmp = Path(tempfile.mkdtemp(prefix="repair-gate-"))
        idx = tmp / "index.html"
        idx.write_text(
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">\n'
            + head_css +
            '</head><body><div class="deck">\n'
            '<div class="slide-frame" data-page="1">\n'
            '<div class="slide" data-layout="raw" data-slide-key="p1" '
            'data-screen-label="01 P1">\n'
            '<div class="wordmark">飞书</div>\n'
            '<div class="stage" style="position:absolute;inset:96px">'
            '<h1 style="font-size:96px;margin:0">P1</h1></div>\n'
            '</div></div>\n</div></body></html>\n', encoding="utf-8")
        _write_deck(tmp / "deck.json", "M",
                    [_raw_slide("p1", "01 P1",
                                '<div class="stage" style="position:absolute;'
                                'inset:96px"><h1 style="font-size:96px;margin:0">'
                                'P1</h1></div>')])
        return tmp

    def test_migrate_included_when_head_perslide_css_present(self):
        tmp = self._mk('<style>[data-slide-key="p1"] .stage h1 '
                       '{ color: gold; }</style>\n')
        try:
            r = _run([sys.executable, str(REPAIR), str(tmp)])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("migrate-head-css", r.stdout)
            # migrate must precede the three CSS repairs in the plan
            self.assertLess(r.stdout.find("migrate-head-css"),
                            r.stdout.find("heal-lifted"),
                            "migrate-head-css should run before heal-lifted")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_migrate_skipped_when_no_head_perslide_css(self):
        # A head <style> with NO per-slide selector (generic shell CSS) → skip.
        tmp = self._mk('<style>.deck { background: #000; }</style>\n')
        try:
            r = _run([sys.executable, str(REPAIR), str(tmp)])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("migrate-head    SKIP", r.stdout)
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class RepairLiftedApplyTest(unittest.TestCase):
    """--apply runs the full pipeline; result renders + strict-validates."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="repair-apply-")
        d = Path(cls.tmp)
        cls.deck = d / "deck.json"
        _write_deck(cls.deck, "Apply", [
            _raw_slide("a", "01 A", _STAGE.format(t="A")),
            {**_raw_slide("b", "02 B",
                          '<div class="stage" style="position:absolute;inset:96px">'
                          '<h2 style="font-size:64px;color:#fff;margin:0">B</h2></div>'),
             "lifted": "src#b"},
        ])
        cls.r = _run([sys.executable, str(REPAIR), str(d), "--apply"])

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_apply_succeeds(self):
        self.assertEqual(self.r.returncode, 0,
                         f"{self.r.stdout}\n{self.r.stderr}")
        self.assertIn("pipeline complete", self.r.stdout)

    def test_apply_renders_index_html(self):
        self.assertTrue((Path(self.tmp) / "index.html").is_file(),
                        "--apply did not render index.html")

    def test_result_strict_valid(self):
        v = _run([sys.executable, str(VALIDATE), str(self.deck), "--strict"])
        self.assertEqual(v.returncode, 0,
                         f"repaired deck.json failed strict validation:\n{v.stdout}")

    def test_apply_ran_render_step(self):
        # the render + validate steps appear in the executed plan
        self.assertIn("render", self.r.stdout)
        self.assertIn("validate --strict", self.r.stdout)


class RepairLiftedBackfillTest(unittest.TestCase):
    """HTML-only deck (no deck.json): --apply backfills, then repairs + renders.

    Each test gets a FRESH HTML-only dir (the --apply test creates a deck.json,
    which would otherwise contaminate the dry-run test's "no deck.json" premise).
    """

    def _html_only_dir(self):
        """Render a seed deck FROM A SEPARATE dir into a fresh output dir, so the
        output dir ends up with index.html (+ slide-index.json) and NO deck.json
        — a genuine legacy HTML-only deck for backfill to engage on."""
        root = Path(tempfile.mkdtemp(prefix="repair-backfill-"))
        seed = root / "seed.json"
        _write_deck(seed, "Legacy", [
            _raw_slide("p1", "01 P1", _STAGE.format(t="P1")),
            _raw_slide("p2", "02 P2", _STAGE.format(t="P2")),
        ])
        out = root / "out"
        out.mkdir()
        r0 = _run([sys.executable, str(RENDER), str(seed), str(out) + "/"])
        self.assertEqual(r0.returncode, 0,
                         f"seed render failed:\n{r0.stdout}\n{r0.stderr}")
        self.assertTrue((out / "index.html").is_file())
        self.assertFalse((out / "deck.json").exists(),
                         "render leaked a deck.json into the output dir — the "
                         "HTML-only premise no longer holds")
        return root, out

    def test_dry_run_plans_backfill_when_no_deckjson(self):
        root, out = self._html_only_dir()
        try:
            r = _run([sys.executable, str(REPAIR), str(out)])
            self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
            self.assertIn("backfill", r.stdout)
            # the CSS repairs are deferred in dry-run because deck.json doesn't
            # exist yet (backfill only previewed it) — announced, not a crash.
            self.assertIn("heal/clean/reconcile  SKIP", r.stdout)
            self.assertFalse((out / "deck.json").exists(),
                             "dry-run created deck.json (must preview only)")
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)

    def test_apply_backfills_then_validates(self):
        root, out = self._html_only_dir()
        try:
            deck = out / "deck.json"
            r = _run([sys.executable, str(REPAIR), str(out), "--apply"])
            self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
            self.assertTrue(deck.is_file(), "--apply did not backfill deck.json")
            v = _run([sys.executable, str(VALIDATE), str(deck), "--strict"])
            self.assertEqual(v.returncode, 0,
                             f"backfilled+repaired deck failed strict validation:\n{v.stdout}")
        finally:
            import shutil
            shutil.rmtree(root, ignore_errors=True)


class LiftWriteValidateRollbackTest(unittest.TestCase):
    """F-281b: lift-slides write-after-validate + rollback (老 F-124/F-75)."""

    def _src(self, tmp):
        src = tmp / "src"
        (src / "input").mkdir(parents=True)
        (src / "index.html").write_text(
            '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '</head><body><div class="deck">\n'
            '<div class="slide-frame" data-page="1">\n'
            '<div class="slide" data-layout="raw" data-slide-key="good" '
            'data-screen-label="01 G">\n'
            '<div class="stage" style="position:absolute;inset:96px">'
            '<h1 style="font-size:96px;margin:0">Good</h1></div>\n'
            '</div></div>\n</div></body></html>\n', encoding="utf-8")
        return src

    def test_happy_lift_revalidates(self):
        tmp = Path(tempfile.mkdtemp(prefix="lift-ok-"))
        try:
            src = self._src(tmp)
            dst = tmp / "dst"
            dst.mkdir()
            deck = dst / "deck.json"
            _write_deck(deck, "D", [_raw_slide("x", "01 X", _STAGE.format(t="X"))])
            r = _run([sys.executable, str(LIFT), str(src / "index.html"),
                      "--key", "good", str(deck)])
            self.assertEqual(r.returncode, 0,
                             f"clean lift should succeed:\n{r.stdout}\n{r.stderr}")
            self.assertIn("post-lift validation passed", r.stdout,
                          "lift no longer re-validates after write (F-281b "
                          "regressed)")
            keys = [s["key"] for s in json.loads(deck.read_text())["slides"]]
            self.assertEqual(keys, ["x", "good"])
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_failing_lift_rolls_back_byte_for_byte(self):
        # Lift a VALID slide into a deck.json that ALREADY holds a duplicate key.
        # The append itself is fine, but `validate-deck --strict` then flags the
        # PRE-EXISTING R-KEY dup → the whole write must roll back to the exact
        # pre-lift bytes (the dup deck is restored untouched), exit non-zero.
        tmp = Path(tempfile.mkdtemp(prefix="lift-rb-"))
        try:
            src = self._src(tmp)
            dst = tmp / "dst"
            dst.mkdir()
            deck = dst / "deck.json"
            _write_deck(deck, "D", [
                _raw_slide("dup", "01 A", _STAGE.format(t="A")),
                _raw_slide("dup", "02 B", _STAGE.format(t="B")),
            ])
            sha_before = _sha(deck)
            n_before = len(json.loads(deck.read_text())["slides"])
            r = _run([sys.executable, str(LIFT), str(src / "index.html"),
                      "--key", "good", str(deck)])
            self.assertNotEqual(r.returncode, 0,
                                "a lift whose RESULT is invalid must exit non-zero "
                                "(F-281b regressed)")
            self.assertIn("rolling back", r.stderr,
                          "rollback message missing on validation failure")
            # byte-for-byte restore: the dup deck.json is exactly as it was.
            self.assertEqual(_sha(deck), sha_before,
                             "deck.json was NOT rolled back to its pre-lift state "
                             "(F-281b regressed) — invalid lift landed on disk")
            self.assertEqual(len(json.loads(deck.read_text())["slides"]), n_before,
                             "the appended slide survived the rollback")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_lift_into_new_deckjson_validates(self):
        # Lifting into a NON-existent dst deck.json seeds a fresh deck and must
        # leave a strict-VALID file (the write-after-validate path also covers the
        # new-file case: _prev is None, so on failure the file would be REMOVED —
        # the restore side of that branch is exercised by the rollback test).
        tmp = Path(tempfile.mkdtemp(prefix="lift-new-"))
        try:
            src = self._src(tmp)
            dst = tmp / "dst"
            dst.mkdir()
            deck = dst / "deck.json"   # does NOT exist yet
            self.assertFalse(deck.exists())
            r = _run([sys.executable, str(LIFT), str(src / "index.html"),
                      "--key", "good", str(deck)])
            self.assertEqual(r.returncode, 0, f"{r.stdout}\n{r.stderr}")
            self.assertTrue(deck.is_file(),
                            "a clean lift into a new deck.json should leave a file")
            v = _run([sys.executable, str(VALIDATE), str(deck), "--strict"])
            self.assertEqual(v.returncode, 0,
                             f"freshly-lifted new deck.json must be valid:\n{v.stdout}")
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
