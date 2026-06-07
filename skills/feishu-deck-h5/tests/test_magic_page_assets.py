from __future__ import annotations

import base64
import importlib.util
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

    def test_no_image_inline_stages_local_images_for_tos_upload(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node not available")

        with tempfile.TemporaryDirectory(prefix="magic-publisher-assets-") as td:
            tmp_path = Path(td)
            src_dir = tmp_path / "source"
            out_dir = tmp_path / "prepared"
            src_dir.mkdir()
            out_dir.mkdir()
            uploader = tmp_path / "upload-asset.js"
            uploader.write_text(
                """
const file = process.argv[2];
const keyIndex = process.argv.indexOf("--key");
const key = keyIndex >= 0 ? process.argv[keyIndex + 1] : file;
console.log("https://tos.example.test/" + key.replace(/[^A-Za-z0-9._/-]+/g, "-"));
""".strip(),
                encoding="utf-8",
            )

            (src_dir / "assets").mkdir()
            (src_dir / "assets" / "local.png").write_bytes(base64.b64decode("iVBORw0KGgo="))
            (src_dir / "app.css").write_text(
                ".hero{background:url('assets/local.png')}",
                encoding="utf-8",
            )
            html = src_dir / "index.html"
            prepared = out_dir / "magic-page-inline.html"
            ready = out_dir / "magic-page-ready.html"
            html.write_text(
                """
<html><head>
<link rel="stylesheet" href="app.css">
</head><body><img src="assets/local.png"></body></html>
""".strip(),
                encoding="utf-8",
            )

            subprocess.run(
                [sys.executable, str(INLINE_ASSETS), str(html), "--out", str(prepared), "--no-image-inline"],
                check=True,
                text=True,
                capture_output=True,
            )
            staged_html = prepared.read_text(encoding="utf-8")
            self.assertNotIn("data:image", staged_html)
            self.assertIn((src_dir / "assets" / "local.png").as_posix(), staged_html)

            subprocess.run(
                [
                    sys.executable,
                    str(MAGIC_PAGE_ASSETS),
                    str(prepared),
                    "--out",
                    str(ready),
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
            published_html = ready.read_text(encoding="utf-8")
            self.assertNotIn("data:image", published_html)
            self.assertNotIn((src_dir / "assets" / "local.png").as_posix(), published_html)
            self.assertIn("https://tos.example.test/deck/test/local.png", published_html)

    def test_magic_page_rehosts_external_and_non_image_resources(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node not available")

        with tempfile.TemporaryDirectory(prefix="magic-publisher-complete-") as td:
            tmp_path = Path(td)
            spec = importlib.util.spec_from_file_location("magic_page_assets", MAGIC_PAGE_ASSETS)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            magic_page_assets = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(magic_page_assets)
            remote_png = tmp_path / "remote.png"
            remote_png.write_bytes(base64.b64decode("iVBORw0KGgo="))
            base_url = "https://cdn.example.test"

            def fake_download_external_ref(ref, *, temp_dir, cache):
                cache[ref] = remote_png
                return remote_png

            magic_page_assets.download_external_ref = fake_download_external_ref

            src_dir = tmp_path / "source"
            src_dir.mkdir()
            (src_dir / "font.woff2").write_bytes(b"font-data")
            (src_dir / "poster.jpg").write_bytes(b"poster-data")
            uploader = tmp_path / "upload-asset.js"
            uploader.write_text(
                """
const file = process.argv[2];
const keyIndex = process.argv.indexOf("--key");
const key = keyIndex >= 0 ? process.argv[keyIndex + 1] : file;
console.log("https://tos.example.test/" + key.replace(/[^A-Za-z0-9._/-]+/g, "-"));
""".strip(),
                encoding="utf-8",
            )
            html = src_dir / "index.html"
            out = tmp_path / "ready.html"
            html.write_text(
                f"""
<html><head>
<style>
@font-face {{ font-family: Deck; src: url("font.woff2"); }}
.remote {{ background: url("{base_url}/remote.png"); }}
</style>
</head><body>
<img srcset="{base_url}/remote.png 1x, {base_url}/remote.png 2x">
<video poster="poster.jpg"></video>
</body></html>
""".strip(),
                encoding="utf-8",
            )

            rewritten, local_uploaded, data_uploaded, external_uploaded = magic_page_assets.rewrite_refs(
                html.read_text(encoding="utf-8"),
                html,
                uploader=uploader,
                base_url="https://magic.example.test",
                key_prefix="deck/test",
            )
            out.write_text(rewritten, encoding="utf-8")

            published_html = out.read_text(encoding="utf-8")
            self.assertEqual(local_uploaded, 2)
            self.assertEqual(data_uploaded, 0)
            self.assertEqual(external_uploaded, 1)
            self.assertNotIn(base_url, published_html)
            self.assertNotIn('url("font.woff2")', published_html)
            self.assertNotIn('poster="poster.jpg"', published_html)
            self.assertIn("https://tos.example.test/deck/test/font.woff2", published_html)
            self.assertIn("https://tos.example.test/deck/test/poster.jpg", published_html)
            self.assertIn("https://tos.example.test/deck/test/external/", published_html)


if __name__ == "__main__":
    unittest.main()
