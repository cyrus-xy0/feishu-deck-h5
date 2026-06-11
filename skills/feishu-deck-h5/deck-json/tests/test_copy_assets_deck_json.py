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
        copied_css_text = copied_css.read_text(encoding="utf-8")
        self.assertNotIn("../", copied_css_text)
        self.assertIn('url("lark-content-bg.jpg")', copied_css_text)
        self.assertTrue((self.output / "assets" / "deck-json" / "templates" / "lark-content-bg.jpg").is_file())
        manifest = (self.output / "assets-manifest.yaml").read_text(encoding="utf-8")
        self.assertIn("  - assets/deck-json/templates/extra-layouts.css", manifest)
        self.assertIn("  - assets/deck-json/templates/lark-content-bg.jpg", manifest)
        self.assertNotIn("assets/assets/lark-content-bg.jpg", manifest)
        for line in manifest.splitlines():
            if line.startswith("  - "):
                self.assertTrue((self.output / line[4:]).is_file(), line)

    def test_inside_skill_deck_json_template_assets_are_bundled(self):
        skill_root = SKILL_ROOT
        tmp_run = skill_root / "runs" / "copy-assets-test-inside-skill" / "output"
        if tmp_run.exists():
            shutil.rmtree(tmp_run.parent, ignore_errors=True)
        tmp_run.mkdir(parents=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_run.parent, ignore_errors=True))
        index = tmp_run / "index.html"
        index.write_text(
            "<!doctype html><html><head>"
            '<link rel="stylesheet" href="../../../deck-json/templates/extra-layouts.css">'
            "</head><body></body></html>",
            encoding="utf-8",
        )

        proc = subprocess.run(
            [sys.executable, str(COPY_ASSETS), str(tmp_run), "--shared=copy"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        rewritten = index.read_text(encoding="utf-8")
        self.assertNotIn("../", rewritten)
        self.assertIn("assets/deck-json/templates/extra-layouts.css", rewritten)
        copied_css = tmp_run / "assets" / "deck-json" / "templates" / "extra-layouts.css"
        self.assertTrue(copied_css.is_file())
        self.assertNotIn("../", copied_css.read_text(encoding="utf-8"))
        self.assertTrue((tmp_run / "assets" / "deck-json" / "templates" / "lark-content-bg.jpg").is_file())
        manifest = (tmp_run / "assets-manifest.yaml").read_text(encoding="utf-8")
        self.assertIn("  - assets/deck-json/templates/extra-layouts.css", manifest)


if __name__ == "__main__":
    unittest.main()
