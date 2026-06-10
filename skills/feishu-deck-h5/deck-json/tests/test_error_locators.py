"""F-280b · unified error-locator coordinate system.

Every user-facing surface (deck-cli list / URL #N / frame_index) is 1-based and
carries the slide key. The validator alone used to report a bare 0-based
`slides[i]`, and render-deck let a non-SystemExit render crash escape as a bare
traceback with NO page context. These tests pin the unified locator:

  - validate-deck.py annotates `$.slides[i]` paths (schema AND business-rule
    errors) with `(key='…', 第N项)` while keeping the 0-based JSON-path body.
  - render-deck.py wraps a per-slide render crash in a SystemExit carrying the
    1-based page index, key, layout, and variant (and points at --debug for the
    full traceback); --debug re-raises the original exception instead.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
VALIDATE = DECK_JSON / "validate-deck.py"
RENDER = DECK_JSON / "render-deck.py"


def _write_deck(deck: dict) -> Path:
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(deck, tmp, ensure_ascii=False)
    tmp.flush()
    tmp.close()
    return Path(tmp.name)


class ValidateLocatorTest(unittest.TestCase):
    def _run_validate(self, deck: dict, *extra) -> tuple[int, str]:
        path = _write_deck(deck)
        try:
            proc = subprocess.run(
                [sys.executable, str(VALIDATE), str(path), *extra],
                capture_output=True, text=True,
            )
            return proc.returncode, proc.stdout + proc.stderr
        finally:
            path.unlink(missing_ok=True)

    def test_schema_error_carries_key_and_1based(self):
        # slide[1] (key='broken') has a bad accent value → schema enum error.
        deck = {
            "deck": {"title": "T", "language": "zh-only"},
            "slides": [
                {"key": "cover", "layout": "cover",
                 "data": {"title": "Hi"}},
                {"key": "broken", "layout": "cover", "accent": "not-a-color",
                 "data": {"title": "Yo"}},
            ],
        }
        rc, log = self._run_validate(deck)
        self.assertEqual(rc, 1, f"expected validation failure:\n{log}")
        # JSON-path body stays 0-based for tools…
        self.assertIn("$.slides[1]", log, log)
        # …with a human annotation carrying the key + 1-based position.
        self.assertIn("key='broken'", log, log)
        self.assertIn("第2项", log, log)

    def test_business_rule_error_carries_key_and_1based(self):
        # Duplicate keys → R-KEY business-rule error on slides[1].
        deck = {
            "deck": {"title": "T", "language": "zh-only"},
            "slides": [
                {"key": "dup", "layout": "cover", "data": {"title": "A"}},
                {"key": "dup", "layout": "cover", "data": {"title": "B"}},
            ],
        }
        rc, log = self._run_validate(deck)
        self.assertEqual(rc, 1, f"expected validation failure:\n{log}")
        self.assertIn("R-KEY", log, log)
        # The duplicate is reported at slides[1] (the second occurrence).
        self.assertRegex(
            log,
            r"\$\.slides\[1\]\s*\(key='dup', 第2项\)",
            f"R-KEY error missing unified locator:\n{log}",
        )

    def test_annotation_injected_once_per_path(self):
        # A nested path (slides[0].data.rows[0]) must annotate the slides[0] head
        # exactly once — never twice on the same line, and the tail after it
        # stays a literal JSON path (`.data.rows[0]`, no second annotation).
        deck = {
            "deck": {"title": "T", "language": "zh-only"},
            "slides": [
                {"key": "tbl", "layout": "table",
                 "data": {"title": "x", "headers": ["a", "b"],
                          "rows": [["only-one"]]}},
            ],
        }
        rc, log = self._run_validate(deck)
        self.assertEqual(rc, 1, f"expected validation failure:\n{log}")
        row_lines = [ln for ln in log.splitlines() if ".data.rows[0]" in ln]
        self.assertTrue(row_lines, f"no rows[0] error line:\n{log}")
        for ln in row_lines:
            # one annotation on this line, and the row tail stays a raw path
            self.assertEqual(ln.count("第1项"), 1, ln)
            self.assertIn("$.slides[0] (key='tbl', 第1项).data.rows[0]", ln)


class RenderLocatorTest(unittest.TestCase):
    # Slide 1 is a renderable `raw` slide (its template needs only data.html);
    # slide 2 has NO `layout`, so render_slide raises KeyError('layout') — a
    # non-SystemExit exception. We skip schema validation + fit-check so the
    # render loop is reached and the new catch-all handler fires on slide 2
    # (proving the 1-based index is 2, not 0/1).
    BAD_DECK = {
        "deck": {"title": "T", "language": "zh-only"},
        "slides": [
            {"key": "ok", "layout": "raw", "data": {"html": "<h1>hi</h1>"}},
            {"key": "boom", "variant": "x", "data": {"title": "Bye"}},
        ],
    }

    def _run_render(self, *extra) -> tuple[int, str]:
        path = _write_deck(self.BAD_DECK)
        out = tempfile.mkdtemp()
        try:
            proc = subprocess.run(
                [sys.executable, str(RENDER), str(path), out,
                 "--skip-validate-json", "--skip-validate-html",
                 "--skip-fit-check", "--skip-copy-assets", *extra],
                capture_output=True, text=True,
            )
            return proc.returncode, proc.stdout + proc.stderr
        finally:
            path.unlink(missing_ok=True)

    def test_render_crash_wrapped_with_1based_locator(self):
        rc, log = self._run_render()
        self.assertNotEqual(rc, 0, f"expected render to fail:\n{log}")
        # 1-based page index (the bad slide is the 2nd) + key + layout + variant.
        self.assertIn("slide[2]", log, log)
        self.assertIn("key='boom'", log, log)
        self.assertIn("variant='x'", log, log)
        # Exception type surfaced, plus the --debug hint.
        self.assertIn("KeyError", log, log)
        self.assertIn("--debug", log, log)
        # NOT a bare traceback (the whole point of the wrap).
        self.assertNotIn('Traceback (most recent call last)', log, log)

    def test_debug_flag_reraises_original_traceback(self):
        rc, log = self._run_render("--debug")
        self.assertNotEqual(rc, 0, f"expected render to fail:\n{log}")
        # --debug re-raises → the original traceback is visible.
        self.assertIn("Traceback (most recent call last)", log, log)
        self.assertIn("KeyError", log, log)


if __name__ == "__main__":
    unittest.main()
