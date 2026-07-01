import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IFRAME_FAAS = ROOT / "assets" / "magic-iframe-faas.py"
MAGIC_PAGE_ASSETS = ROOT / "assets" / "magic-page-assets.py"


FAKE_UPLOADER_JS = """
const args = process.argv.slice(2);
const key = args[args.indexOf("--key") + 1] || "missing-key";
process.stdout.write("https://tos.example.test/" + key);
"""


class MagicIframeFaasTest(unittest.TestCase):
    def test_local_iframe_html_is_rewritten_to_faas_proxy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="magic-iframe-faas-") as td:
            tmp = Path(td)
            uploader = tmp / "fake-upload.js"
            uploader.write_text(FAKE_UPLOADER_JS, encoding="utf-8")
            (tmp / "pic.png").write_bytes(b"\x89PNG\r\n")
            (tmp / "demo.html").write_text(
                '<!doctype html><html><body><img src="pic.png">'
                "<script>const u = new URL(location.href);</script></body></html>",
                encoding="utf-8",
            )
            main = tmp / "index.html"
            main.write_text('<iframe src="demo.html"></iframe>', encoding="utf-8")
            out = tmp / "out.html"
            report = tmp / "report.json"

            subprocess.run(
                [
                    sys.executable,
                    str(IFRAME_FAAS),
                    str(main),
                    "--out",
                    str(out),
                    "--uploader",
                    str(uploader),
                    "--base-url",
                    "https://magic.example.test",
                    "--key-prefix",
                    "deck/test",
                    "--asset-base-dir",
                    str(tmp),
                    "--report",
                    str(report),
                    "--dry-run",
                    "--upload-workers",
                    "1",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )

            html = out.read_text(encoding="utf-8")
            self.assertIn("https://magic.example.test/api/faas/", html)
            self.assertIn("?p=demo", html)
            self.assertNotIn('src="demo.html"', html)
            payload = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(payload["rewritten"], 1)
            self.assertTrue(payload["faas"]["dry_run"])
            self.assertIn("https://tos.example.test/deck/test/iframe-html/", payload["iframes"][0]["tos_url"])

    def test_magic_page_assets_does_not_upload_local_iframe_html_to_tos(self) -> None:
        with tempfile.TemporaryDirectory(prefix="magic-assets-iframe-") as td:
            tmp = Path(td)
            uploader = tmp / "fake-upload.js"
            uploader.write_text(FAKE_UPLOADER_JS, encoding="utf-8")
            (tmp / "demo.html").write_text("<p>demo</p>", encoding="utf-8")
            (tmp / "hero.png").write_bytes(b"\x89PNG\r\n")
            main = tmp / "index.html"
            main.write_text(
                '<iframe src="demo.html"></iframe><img src="hero.png">',
                encoding="utf-8",
            )
            out = tmp / "ready.html"

            subprocess.run(
                [
                    sys.executable,
                    str(MAGIC_PAGE_ASSETS),
                    str(main),
                    "--out",
                    str(out),
                    "--uploader",
                    str(uploader),
                    "--base-url",
                    "https://magic.example.test",
                    "--key-prefix",
                    "deck/test",
                    "--asset-base-dir",
                    str(tmp),
                    "--keep-inline-code",
                    "--upload-workers",
                    "1",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )

            html = out.read_text(encoding="utf-8")
            self.assertIn('src="demo.html"', html)
            self.assertIn("https://tos.example.test/deck/test/hero.png", html)
            self.assertNotIn("https://tos.example.test/deck/test/demo.html", html)

    def test_magic_page_assets_does_not_rewrite_js_url_constructor(self) -> None:
        with tempfile.TemporaryDirectory(prefix="magic-assets-js-url-") as td:
            tmp = Path(td)
            uploader = tmp / "fake-upload.js"
            uploader.write_text(FAKE_UPLOADER_JS, encoding="utf-8")
            (tmp / "hero.png").write_bytes(b"\x89PNG\r\n")
            main = tmp / "index.html"
            main.write_text(
                '<script>const asset = new URL("hero.png", location.href);</script>'
                '<style>.hero{background:url("hero.png")}</style>',
                encoding="utf-8",
            )
            out = tmp / "ready.html"

            subprocess.run(
                [
                    sys.executable,
                    str(MAGIC_PAGE_ASSETS),
                    str(main),
                    "--out",
                    str(out),
                    "--uploader",
                    str(uploader),
                    "--base-url",
                    "https://magic.example.test",
                    "--key-prefix",
                    "deck/test",
                    "--asset-base-dir",
                    str(tmp),
                    "--keep-inline-code",
                    "--upload-workers",
                    "1",
                ],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )

            html = out.read_text(encoding="utf-8")
            self.assertIn('new URL("hero.png", location.href)', html)
            self.assertIn("background:url('https://tos.example.test/deck/test/hero.png')", html)


if __name__ == "__main__":
    unittest.main()
