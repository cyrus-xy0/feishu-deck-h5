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

    def test_visible_asset_path_text_does_not_pollute_manifest(self):
        asset = self.output / "assets" / "custom" / "probe.svg"
        asset.parent.mkdir(parents=True)
        asset.write_text("<svg xmlns=\"http://www.w3.org/2000/svg\" />\n", encoding="utf-8")
        index = self.output / "index.html"
        index.write_text(
            "<!doctype html><html><head>"
            "<style>.probe{background:url('assets/custom/probe.svg')}</style>"
            "</head><body>"
            "<p>可见说明文本: assets/missing-from-text.svg</p>"
            "<div>CSS 背景图: assets/custom/probe.svg</div>"
            "<div class=\"probe\"></div>"
            "</body></html>",
            encoding="utf-8",
        )

        proc = subprocess.run(
            [sys.executable, str(COPY_ASSETS), str(self.output), "--shared=copy"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        manifest = (self.output / "assets-manifest.yaml").read_text(encoding="utf-8")
        self.assertIn("  - assets/custom/probe.svg", manifest)
        self.assertNotIn("missing-from-text", manifest)
        self.assertNotIn("</", manifest)


    def _run_prune_case(self, bg_attr: str, kept: str):
        """Build output/ with input/<kept> referenced ONLY via `bg_attr` and an
        unreferenced input/orphan.png, run copy-assets, return (manifest, paths).
        The orphan is a live control: it MUST be pruned, proving x's survival is
        meaningful (not just 'prune disabled')."""
        (self.output / "input").mkdir(parents=True, exist_ok=True)
        (self.output / "input" / kept).write_bytes(b"PNGDATA-keep")
        (self.output / "input" / "orphan.png").write_bytes(b"PNGDATA-orphan")
        (self.output / "index.html").write_text(
            "<!doctype html><html><head></head><body>"
            f'<div class="slide" data-slide-key="end" style="{bg_attr}"></div>'
            "</body></html>",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [sys.executable, str(COPY_ASSETS), str(self.output), "--shared=copy"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        manifest = (self.output / "assets-manifest.yaml").read_text(encoding="utf-8")
        return manifest

    def test_entity_encoded_input_bg_survives_prune(self):
        # F-333: a raw/canvas page whose bg is an inline style="" attribute with
        # HTML-entity-encoded double quotes — url(&quot;input/x.png&quot;) — must NOT
        # have its real input/x.png deleted by the self-contained prune. This is the
        # exact "图不见了" report (northregion-ai-lecture p47 end page).
        manifest = self._run_prune_case(
            'background-image:url(&quot;input/x.png&quot;)', "x.png")
        self.assertTrue((self.output / "input" / "x.png").is_file(),
                        "entity-referenced input/x.png was pruned (F-333 regression)")
        self.assertFalse((self.output / "input" / "orphan.png").is_file(),
                         "control: unreferenced orphan.png should have been pruned")
        self.assertIn("  - input/x.png", manifest)
        self.assertNotIn("quot", manifest)          # no &quot;-tailed bogus path
        self.assertNotIn("input/x.png&", manifest)

    def test_numeric_entity_input_bg_survives_prune(self):
        # &#34; (numeric double-quote entity) begins with '&' just like &quot;, so the
        # entity-specific stop is entity-form-agnostic.
        manifest = self._run_prune_case(
            'background-image:url(&#34;input/y.png&#34;)', "y.png")
        self.assertTrue((self.output / "input" / "y.png").is_file(),
                        "&#34;-referenced input/y.png was pruned (F-333 regression)")
        self.assertIn("  - input/y.png", manifest)
        self.assertNotIn("#34", manifest)

    def test_literal_ampersand_filename_survives_prune(self):
        # F-333 ADVERSARIAL regression: a filename with a LITERAL '&' (Q&A.png,
        # R&D.png — real business-deck names) must NOT be truncated by the entity
        # boundary and then deleted by the prune. The fix stops capture ONLY at an
        # actual quote-entity (&quot; etc.), never at a bare '&'. A naive `[^...&]`
        # char-class would re-introduce the very "图不见了" deletion this ticket kills.
        manifest = self._run_prune_case(
            'background-image:url(&quot;input/Q&A.png&quot;)', "Q&A.png")
        self.assertTrue((self.output / "input" / "Q&A.png").is_file(),
                        "literal-& filename input/Q&A.png was pruned (F-333 adversarial regression)")
        self.assertFalse((self.output / "input" / "orphan.png").is_file())
        self.assertIn("  - input/Q&A.png", manifest)


if __name__ == "__main__":
    unittest.main()
