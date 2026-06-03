from __future__ import annotations

import base64
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAGIC_PAGE_ASSETS = ROOT / "assets" / "magic-page-assets.py"
INLINE_ASSETS = ROOT / "assets" / "inline-assets.py"


class MagicPageAssetsTest(unittest.TestCase):
    def test_magic_page_uploads_local_and_base64_images(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node not available")

        with tempfile.TemporaryDirectory(prefix="magic-page-assets-") as td:
            tmp_path = Path(td)
            uploader = tmp_path / "upload-asset.js"
            uploader.write_text(
                """
const path = process.argv[2];
const keyIndex = process.argv.indexOf("--key");
const key = keyIndex >= 0 ? process.argv[keyIndex + 1] : path;
console.log("https://tos.example.test/" + key.replace(/[^A-Za-z0-9._/-]+/g, "-"));
""".strip(),
                encoding="utf-8",
            )

            (tmp_path / "assets").mkdir()
            (tmp_path / "assets" / "local.png").write_bytes(base64.b64decode("iVBORw0KGgo="))
            data_uri = "data:image/png;base64," + base64.b64encode(b"inline-image").decode("ascii")
            html = tmp_path / "index.html"
            out = tmp_path / "magic.html"
            html.write_text(
                f"""
<html><head>
<style>.hero {{ background-image: url("assets/local.png"); }}</style>
</head><body>
<img src="assets/local.png">
<img src="{data_uri}">
</body></html>
""".strip(),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(MAGIC_PAGE_ASSETS),
                    str(html),
                    "--out",
                    str(out),
                    "--uploader",
                    str(uploader),
                    "--base-url",
                    "https://magic.example.test",
                    "--key-prefix",
                    "deck/test",
                ],
                check=True,
                text=True,
                capture_output=True,
            )

            published_html = out.read_text(encoding="utf-8")
            self.assertNotIn("data:image", published_html)
            self.assertIn("https://tos.example.test/deck/test/assets/local.png", published_html)
            self.assertIn("https://tos.example.test/deck/test/data-uri/", published_html)


    def test_inline_assets_no_image_inline_keeps_uploaded_image_urls(self) -> None:
        with tempfile.TemporaryDirectory(prefix="inline-assets-") as td:
            tmp_path = Path(td)
            (tmp_path / "app.css").write_text(
                ".hero{background:url('https://tos.example.test/hero.png')}",
                encoding="utf-8",
            )
            (tmp_path / "app.js").write_text("window.deckReady = true;", encoding="utf-8")
            html = tmp_path / "index.html"
            out = tmp_path / "out.html"
            html.write_text(
                """
<html><head>
<link rel="stylesheet" href="app.css">
<script src="app.js"></script>
</head><body><img src="https://tos.example.test/pic.png"></body></html>
""".strip(),
                encoding="utf-8",
            )

            subprocess.run(
                [sys.executable, str(INLINE_ASSETS), str(html), "--out", str(out), "--no-image-inline"],
                check=True,
                text=True,
                capture_output=True,
            )

            published_html = out.read_text(encoding="utf-8")
            self.assertNotIn("data:image", published_html)
            self.assertIn("https://tos.example.test/hero.png", published_html)
            self.assertIn("https://tos.example.test/pic.png", published_html)
            self.assertIn("window.deckReady = true", published_html)


if __name__ == "__main__":
    unittest.main()
