"""Tests for deck-json/outline-lint.py — the designer outline.json self-check.

outline-lint is a SELF-CHECK, not a render gate: these tests pin that it
(1) accepts well-formed deterministic syntax variants, (2) flags a
missing top-level contract key, (3) enforces the six-dimension design_spec +
non-empty density_budget on `raw:` slides only, and (4) reports violations with
the slide key + 1-based locator (F-280 convention).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
REPO = DECK_JSON.parent
LINT = DECK_JSON / "outline-lint.py"
SCHEMA = REPO / "schema" / "outline.schema.json"


def _full_six_dim_spec() -> dict:
    return {
        "Q0": "现象页",
        "Q1": "记住一句话",
        "six_dim": "字号 44 · 容器 2 级卡 · 装饰 glow 圆点 · 对齐 居中 · 字距 -0.01em · 字重 700",
    }


def _valid_outline() -> dict:
    return {
        "scenario": {"goal": "g", "audience": "a", "decision": "d"},
        "design_plan": {"title": "t", "narrative_arc": "arc"},
        "slides": [
            {
                "key": "cover",
                "role": "cover",
                "layout_intent": "schema:cover",
                "single_focus": "封面",
                "density_budget": "核心1",
                "design_spec": {"notes": "深色 cover"},
            },
            {
                "key": "trend-threshold",
                "role": "insight",
                "layout_intent": "raw:trend-threshold",
                "single_focus": "2026 临界点",
                "density_budget": "核心块1 + 支撑1 ≤ 容量",
                "design_spec": _full_six_dim_spec(),
            },
        ],
    }


class OutlineLintCli(unittest.TestCase):
    def _run(self, outline: dict | None = None, path: Path | None = None) -> tuple[int, str]:
        if path is None:
            tmp = tempfile.NamedTemporaryFile(
                "w", suffix=".json", delete=False, encoding="utf-8")
            json.dump(outline, tmp, ensure_ascii=False)
            tmp.flush()
            tmp.close()
            path = Path(tmp.name)
            cleanup = True
        else:
            cleanup = False
        try:
            proc = subprocess.run(
                [sys.executable, str(LINT), str(path)],
                capture_output=True, text=True,
            )
            return proc.returncode, proc.stdout + proc.stderr
        finally:
            if cleanup:
                path.unlink(missing_ok=True)

    # --- happy path -------------------------------------------------------

    def test_valid_outline_passes(self):
        rc, log = self._run(_valid_outline())
        self.assertEqual(rc, 0, log)
        self.assertIn("OK", log)

    def test_six_dimension_syntax_variants_pass(self):
        # Pin both supported authoring forms without scanning mutable local runs/.
        # A unit test must not change result when a historical or in-progress run
        # is added beside the repository.
        explicit = _valid_outline()
        compact = _valid_outline()
        compact["slides"][1]["design_spec"] = {
            "Q0": "现象页",
            "visual": "44/700/居中/-0.01em · 2级卡 panel · glow border",
        }
        for syntax, outline in (("explicit-labels", explicit), ("compact-slash", compact)):
            with self.subTest(syntax=syntax):
                rc, log = self._run(outline)
                self.assertEqual(rc, 0, log)

    # --- shape errors -----------------------------------------------------

    def test_missing_top_level_key_fails(self):
        outline = _valid_outline()
        del outline["design_plan"]
        rc, log = self._run(outline)
        self.assertEqual(rc, 1, log)
        self.assertIn("design_plan", log)

    def test_missing_slide_required_key_fails(self):
        outline = _valid_outline()
        del outline["slides"][1]["single_focus"]
        rc, log = self._run(outline)
        self.assertEqual(rc, 1, log)
        self.assertIn("single_focus", log)

    # --- raw-slide design contract ---------------------------------------

    def test_raw_slide_missing_six_dim_fails_with_locator(self):
        outline = _valid_outline()
        # drop 字重 / 装饰 from the spec entirely
        outline["slides"][1]["design_spec"] = {
            "six_dim": "字号 44 · 容器 2 级卡 · 对齐 居中"
        }
        rc, log = self._run(outline)
        self.assertEqual(rc, 1, log)
        self.assertIn("trend-threshold", log)          # slide key present
        self.assertIn("第2项", log)                     # 1-based locator
        self.assertIn("六维", log)
        self.assertIn("字重", log)                       # the missing dim is named

    def test_raw_slide_empty_density_budget_fails(self):
        outline = _valid_outline()
        outline["slides"][1]["density_budget"] = ""
        rc, log = self._run(outline)
        self.assertEqual(rc, 1, log)
        self.assertIn("density_budget", log)
        self.assertIn("trend-threshold", log)

    def test_raw_slide_empty_design_spec_fails(self):
        outline = _valid_outline()
        outline["slides"][1]["design_spec"] = {}
        rc, log = self._run(outline)
        self.assertEqual(rc, 1, log)
        self.assertIn("design_spec", log)

    def test_schema_slide_exempt_from_six_dim(self):
        # A non-raw (schema:) slide with a thin design_spec must NOT trip the
        # six-dimension rule — that rule is raw-only.
        outline = _valid_outline()
        outline["slides"][0]["design_spec"] = {"notes": "x"}
        outline["slides"][0]["density_budget"] = ""  # also empty: still fine for schema slide
        rc, log = self._run(outline)
        self.assertEqual(rc, 0, log)


if __name__ == "__main__":
    unittest.main()
