import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parents[1]
PACKAGE_DELIVERABLE = SKILL_ROOT / "assets" / "package-deliverable.sh"


class PackageDeliverableTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="package-deliverable-"))
        self.output = self.tmp / "output"
        self.output.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_deck_json_and_assets_are_bundled(self):
        (self.output / "index.html").write_text(
            '<!doctype html><html><body><img src="assets/local.png"></body></html>',
            encoding="utf-8",
        )
        (self.output / "deck.json").write_text(
            json.dumps({"schema_version": "1.0", "slides": []}),
            encoding="utf-8",
        )
        (self.output / "assets-manifest.yaml").write_text(
            "deck_local:\n  - assets/local.png\n",
            encoding="utf-8",
        )
        assets = self.output / "assets"
        assets.mkdir()
        (assets / "local.png").write_bytes(b"fake-png")

        proc = subprocess.run(
            ["bash", str(PACKAGE_DELIVERABLE), str(self.output), "--name", "deckjson-package"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        zip_path = self.output / "deckjson-package.zip"
        self.assertTrue(zip_path.is_file())
        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())

        self.assertIn("index.html", names)
        self.assertIn("README.txt", names)
        self.assertIn("deck.json", names)
        self.assertIn("assets-manifest.yaml", names)
        self.assertIn("assets/local.png", names)
        # texts.md / apply-texts.py no longer bundled — editing is in-browser
        self.assertNotIn("texts.md", names)
        self.assertNotIn("apply-texts.py", names)


if __name__ == "__main__":
    unittest.main()
