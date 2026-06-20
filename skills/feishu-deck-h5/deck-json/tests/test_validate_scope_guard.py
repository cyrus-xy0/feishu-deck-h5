"""F-352 · validate.py scoped-edit guardrail.

A full-deck `validate.py <index.html>` run right after a page-SCOPED render is
REFUSED (the recurring "改一页却校验/渲染很多页" trap) — it would surface
pre-existing out-of-scope debt unrelated to the confined edit. The guard reads
the sibling last-render.log GATE-COVERAGE line (`scope=<digits>` = page-scoped;
`scope=full` / `--quick` = not). Escape hatches: --slide / --scope-frames (the
confined-edit path) or --full (the delivery / render-pipeline path, which is what
render-deck.py's own internal gate passes).

Subprocess-level (mirrors how render-deck / a human invoke the CLI).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
VALIDATE = HERE.parent.parent / "assets" / "validate.py"
SAMPLE = HERE / "__snapshots__" / "sample-deck.index.html"

SCOPED_LOG = (
    "feishu-deck-h5 render\n"
    "GATE-COVERAGE static=ran visual=skipped geometry=skipped "
    "distribution=skipped scope=6\n"
)
AUTO_SCOPED_LOG = (
    "GATE-COVERAGE static=ran visual=ran geometry=ran "
    "distribution=skipped scope=auto:3,4\n"
)
FULL_LOG = (
    "GATE-COVERAGE static=ran visual=ran geometry=ran "
    "distribution=ran scope=full\n"
)


class ValidateScopeGuardTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)
        self.html = self.dir / "index.html"
        shutil.copy(SAMPLE, self.html)

    def tearDown(self):
        self._td.cleanup()

    def _log(self, content):
        (self.dir / "last-render.log").write_text(content, encoding="utf-8")

    def _run(self, *extra):
        # --no-visual keeps it browser-free; the guard runs BEFORE audits so it
        # is unaffected by --no-visual either way.
        return subprocess.run(
            [sys.executable, str(VALIDATE), str(self.html), "--no-visual", *extra],
            capture_output=True, text=True)

    # --- the trap: full run right after a scoped render ---------------------
    def test_full_run_after_page_scoped_render_is_refused(self):
        self._log(SCOPED_LOG)
        r = self._run()
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("REFUSED", r.stderr)

    def test_full_run_after_auto_scoped_render_is_refused(self):
        self._log(AUTO_SCOPED_LOG)
        r = self._run()
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("REFUSED", r.stderr)

    # --- escape hatches -----------------------------------------------------
    def test_full_flag_overrides_guard(self):
        self._log(SCOPED_LOG)
        r = self._run("--full")
        self.assertNotIn("REFUSED", r.stderr)
        self.assertNotEqual(r.returncode, 2)   # 0/1 from audits, never the guard's 2

    def test_slide_filter_bypasses_guard(self):
        self._log(SCOPED_LOG)
        r = self._run("--slide", "1")
        self.assertNotIn("REFUSED", r.stderr)

    def test_scope_frames_bypasses_guard(self):
        self._log(SCOPED_LOG)
        r = self._run("--scope-frames", "1")
        self.assertNotIn("REFUSED", r.stderr)

    # --- non-triggers -------------------------------------------------------
    def test_full_render_log_does_not_trip_guard(self):
        self._log(FULL_LOG)
        r = self._run()
        self.assertNotIn("REFUSED", r.stderr)

    def test_no_render_log_does_not_trip_guard(self):
        # no last-render.log at all (e.g. html rendered elsewhere) → allow
        r = self._run()
        self.assertNotIn("REFUSED", r.stderr)


if __name__ == "__main__":
    unittest.main()
