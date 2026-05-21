"""Every example deck.json passes validate-deck.py."""
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
VALIDATE = DECK_JSON / "validate-deck.py"
EXAMPLES = DECK_JSON / "examples"


class ValidateExamplesTest(unittest.TestCase):
    def _run(self, deck_path: Path) -> tuple[int, str]:
        proc = subprocess.run(
            [sys.executable, str(VALIDATE), str(deck_path)],
            capture_output=True, text=True,
        )
        return proc.returncode, proc.stdout + proc.stderr

    def test_sample_deck_validates(self):
        rc, log = self._run(EXAMPLES / "sample-deck.json")
        self.assertEqual(rc, 0, f"sample-deck.json failed validate-deck:\n{log}")

    def test_migrated_decks_validate(self):
        migrated = EXAMPLES / "migrated-from-toml"
        if not migrated.is_dir():
            self.skipTest("migrated-from-toml/ not present")
        problems = []
        for path in sorted(migrated.glob("*.json")):
            rc, log = self._run(path)
            if rc != 0:
                problems.append(f"  {path.name}: rc={rc}\n{log[:600]}")
        self.assertFalse(problems, "Migrated decks failed:\n" + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
