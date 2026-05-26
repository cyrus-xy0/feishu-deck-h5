import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parents[1]
COPY_ASSETS = SKILL_ROOT / "assets" / "copy-assets.py"


class CopyAssetsDeckJsonTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="copy-assets-deck-json-"))
        self.run_root = self.tmp / "runs" / "case"
        self.output = self.run_root / "output"
        self.output.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_deck_json_template_assets_are_bundled(self):
        html = (
            "<!doctype html><html><head>"
            '<link rel="stylesheet" href="../../../skills/feishu-deck-h5/deck-json/templates/extra-layouts.css">'
            "</head><body></body></html>"
        )
        index = self.output / "index.html"
        index.write_text(html, encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, str(COPY_ASSETS), str(self.output), "--shared=copy"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        rewritten = index.read_text(encoding="utf-8")
        self.assertNotIn("skills/feishu-deck-h5", rewritten)
        self.assertIn("assets/deck-json/templates/extra-layouts.css", rewritten)
        copied_css = self.output / "assets" / "deck-json" / "templates" / "extra-layouts.css"
        self.assertTrue(copied_css.is_file())
        self.assertIn('url("../../lark-content-bg.jpg")', copied_css.read_text(encoding="utf-8"))
        self.assertTrue((self.output / "assets" / "lark-content-bg.jpg").is_file())
        manifest = (self.output / "assets-manifest.yaml").read_text(encoding="utf-8")
        self.assertIn("  - assets/deck-json/templates/extra-layouts.css", manifest)
        self.assertIn("  - assets/lark-content-bg.jpg", manifest)
        self.assertNotIn("assets/assets/lark-content-bg.jpg", manifest)
        for line in manifest.splitlines():
            if line.startswith("  - "):
                self.assertTrue((self.output / line[4:]).is_file(), line)


if __name__ == "__main__":
    unittest.main()
