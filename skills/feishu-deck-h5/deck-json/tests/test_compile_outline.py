"""Regression test for outline.json -> DeckJSON compilation."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
REPO = DECK_JSON.parents[2]
COMPILE = DECK_JSON / "compile-outline.py"
VALIDATE = DECK_JSON / "validate-deck.py"
OUTLINE = REPO / "skills" / "deck-outline-planner" / "examples" / "retail-agent-outline.json"


class CompileOutlineTest(unittest.TestCase):
    def test_retail_outline_compiles_to_valid_deckjson(self):
        with tempfile.TemporaryDirectory(prefix="compile-outline-test-") as td:
            out = Path(td) / "deck.json"
            report = Path(td) / "compile-report.json"
            feedback = Path(td) / "FEEDBACK.md"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(COMPILE),
                    str(OUTLINE),
                    str(out),
                    "--report",
                    str(report),
                    "--feedback",
                    str(feedback),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

            deck = json.loads(out.read_text(encoding="utf-8"))
            source = json.loads(OUTLINE.read_text(encoding="utf-8"))
            expected_keys = [slide["key"] for slide in source["outline"]["slides"]]
            actual_keys = [slide["key"] for slide in deck["slides"]]
            self.assertEqual(actual_keys, expected_keys)

            gap = next(slide for slide in deck["slides"] if slide["key"] == "execution-gap")
            self.assertEqual(gap["layout"], "content")
            self.assertEqual(gap["variant"], "before-after")
            self.assertEqual(len(gap["data"]["before"]["items"]), len(gap["data"]["after"]["items"]))

            validate = subprocess.run(
                [sys.executable, str(VALIDATE), str(out)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(validate.returncode, 0, validate.stdout + validate.stderr)

            compiled_report = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(compiled_report["summary"]["slides"], len(expected_keys))
            self.assertIn("unsupported_claims", compiled_report["claim_discipline"])
            self.assertIn("execution-gap", feedback.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
