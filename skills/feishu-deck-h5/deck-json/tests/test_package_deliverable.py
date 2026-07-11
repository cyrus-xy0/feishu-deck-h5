import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread


HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parents[1]
PACKAGE_DELIVERABLE = SKILL_ROOT / "assets" / "package-deliverable.sh"
PACKAGE_INGEST = SKILL_ROOT / "assets" / "package-ingest.sh"


class _RemoteImageHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/remote.jpg"):
            payload = b"remote-image-bytes"
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path.startswith("/broken.jpg"):
            payload = b"forbidden"
            self.send_response(403)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, _format, *args):
        return


@contextmanager
def remote_image_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RemoteImageHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


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
        (self.output / ".slide-hashes.json").write_text(
            json.dumps({"cover": "hash"}),
            encoding="utf-8",
        )
        (self.output / "assets-manifest.yaml").write_text(
            "deck_local:\n  - assets/local.png\n",
            encoding="utf-8",
        )
        (self.output / "slide-index.json").write_text(
            json.dumps({"slides": [{"key": "cover", "assets": ["prototypes/demo/index.html"]}]}),
            encoding="utf-8",
        )
        (self.output / "making-of.html").write_text(
            "<!doctype html><html><body>making of</body></html>",
            encoding="utf-8",
        )
        (self.output / "deck.xml").write_text("<deck />\n", encoding="utf-8")
        assets = self.output / "assets"
        assets.mkdir()
        (assets / "local.png").write_bytes(b"fake-png")
        prototypes = self.output / "prototypes" / "demo"
        prototypes.mkdir(parents=True)
        (prototypes / "index.html").write_text(
            "<!doctype html><html><body>prototype</body></html>",
            encoding="utf-8",
        )
        inputs = self.output / "input"
        inputs.mkdir()
        (inputs / "photo.png").write_bytes(b"fake-photo")
        deck_log = self.output / "deck-log"
        deck_log.mkdir()
        (deck_log / "events.jsonl").write_text("{}\n", encoding="utf-8")

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
        self.assertIn("slide-index.json", names)
        self.assertIn("making-of.html", names)
        self.assertIn("deck.xml", names)
        self.assertIn("assets/local.png", names)
        self.assertIn("prototypes/demo/index.html", names)
        self.assertIn("input/photo.png", names)
        self.assertIn("deck-log/events.jsonl", names)
        # texts.md / apply-texts.py no longer bundled — editing is in-browser
        self.assertNotIn("texts.md", names)
        self.assertNotIn("apply-texts.py", names)

    def test_package_ingest_writes_top_level_deck_zip(self):
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
            ["bash", str(PACKAGE_INGEST), str(self.output), "--deck-id", "lark-demo-2026-06-11"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        zip_path = self.output / "deck.zip"
        self.assertTrue(zip_path.is_file())
        manifest = json.loads((self.output / "ingestion-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["deck_id"], "lark-demo-2026-06-11")
        self.assertEqual(manifest["primary_html"], "index.html")
        self.assertIn("README.md", manifest["soft_missing"])
        self.assertEqual(manifest["asset_closure"]["status"], "verified")
        self.assertGreaterEqual(manifest["asset_closure"]["reachable_file_count"], 2)
        self.assertEqual(len(manifest["asset_closure"]["digest_sha256"]), 64)

        with zipfile.ZipFile(zip_path) as zf:
            names = set(zf.namelist())

        self.assertIn("index.html", names)
        self.assertIn("deck.json", names)
        self.assertIn("assets-manifest.yaml", names)
        self.assertIn("ingestion-manifest.json", names)
        self.assertIn("README.md", names)
        self.assertIn("assets/local.png", names)
        self.assertNotIn(".slide-hashes.json", names)
        self.assertFalse(any(name.startswith("output/") for name in names))
        self.assertFalse(any("\\" in name for name in names))

    def test_package_ingest_promotes_redirect_shell_index(self):
        (self.output / "index.html").write_text(
            """<!doctype html>
<html><head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="0; url=deck.html">
</head><body><a href="deck.html">open</a></body></html>
""",
            encoding="utf-8",
        )
        (self.output / "deck.html").write_text(
            '<!doctype html><html><body><div class="slide" data-slide-key="cover">'
            '<img src="assets/local.png"></div></body></html>',
            encoding="utf-8",
        )
        (self.output / "deck.json").write_text(
            json.dumps({"schema_version": "1.0", "slides": [{"key": "cover"}]}),
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
            ["bash", str(PACKAGE_INGEST), str(self.output), "--deck-id", "lark-wide-2026-06-30"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("redirect shell", proc.stderr)
        with zipfile.ZipFile(self.output / "deck.zip") as zf:
            names = set(zf.namelist())
            packaged_index = zf.read("index.html").decode("utf-8")

        self.assertIn("index.html", names)
        self.assertNotIn("deck.html", names)
        self.assertIn('data-slide-key="cover"', packaged_index)
        self.assertNotIn("http-equiv=\"refresh\"", packaged_index)

    def test_package_ingest_rejects_loopback_background_image(self):
        with remote_image_server() as base_url:
            remote_url = f"{base_url}/remote.jpg?sign=abc&expires=123"
            (self.output / "index.html").write_text(
                '<!doctype html><html><body><div class="slide" data-slide-key="cover" '
                f'style="background-image:url(\'{remote_url.replace("&", "&amp;")}\')">Cover</div></body></html>',
                encoding="utf-8",
            )
            (self.output / "deck.json").write_text(
                json.dumps({"schema_version": "1.0", "slides": [{"key": "cover"}]}),
                encoding="utf-8",
            )
            (self.output / "assets-manifest.yaml").write_text(
                "framework: []\nshared: []\ndeck-local: []\n",
                encoding="utf-8",
            )
            (self.output / "assets").mkdir()

            proc = subprocess.run(
                ["bash", str(PACKAGE_INGEST), str(self.output), "--deck-id", "lark-remote-bg-2026-07-08"],
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("non-public destination IP", proc.stderr)
        self.assertFalse((self.output / "deck.zip").exists())

    def test_package_ingest_fails_when_remote_background_image_is_forbidden(self):
        with remote_image_server() as base_url:
            remote_url = f"{base_url}/broken.jpg"
            (self.output / "index.html").write_text(
                '<!doctype html><html><body><div class="slide" data-slide-key="cover" '
                f'style="background-image:url(\'{remote_url}\')">Cover</div></body></html>',
                encoding="utf-8",
            )
            (self.output / "deck.json").write_text(
                json.dumps({"schema_version": "1.0", "slides": [{"key": "cover"}]}),
                encoding="utf-8",
            )
            (self.output / "assets-manifest.yaml").write_text(
                "framework: []\nshared: []\ndeck-local: []\n",
                encoding="utf-8",
            )
            (self.output / "assets").mkdir()

            proc = subprocess.run(
                ["bash", str(PACKAGE_INGEST), str(self.output), "--deck-id", "lark-remote-bg-2026-07-08"],
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("non-public destination IP", proc.stderr)
        self.assertFalse((self.output / "deck.zip").exists())

    def test_package_ingest_rejects_missing_nested_script(self):
        (self.output / "index.html").write_text(
            '<!doctype html><html><body><iframe src="assets/prototypes/demo/index.html"></iframe></body></html>',
            encoding="utf-8",
        )
        (self.output / "deck.json").write_text(
            json.dumps({"schema_version": "1.0", "slides": []}),
            encoding="utf-8",
        )
        (self.output / "assets-manifest.yaml").write_text(
            "deck-local:\n  - assets/prototypes/demo/index.html\n",
            encoding="utf-8",
        )
        child = self.output / "assets" / "prototypes" / "demo" / "index.html"
        child.parent.mkdir(parents=True)
        child.write_text('<script type="module" src="app.js"></script>', encoding="utf-8")

        proc = subprocess.run(
            ["bash", str(PACKAGE_INGEST), str(self.output), "--deck-id", "lark-nested-missing-2026-07-10"],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("LOCAL_REF_MISSING", proc.stderr)
        self.assertIn("assets/prototypes/demo/index.html -> app.js", proc.stderr)
        self.assertFalse((self.output / "deck.zip").exists())

    def test_package_ingest_rejects_zero_byte_asset(self):
        (self.output / "index.html").write_text(
            '<!doctype html><html><body><img src="assets/empty.png"></body></html>',
            encoding="utf-8",
        )
        (self.output / "deck.json").write_text(
            json.dumps({"schema_version": "1.0", "slides": []}),
            encoding="utf-8",
        )
        (self.output / "assets-manifest.yaml").write_text(
            "deck-local:\n  - assets/empty.png\n",
            encoding="utf-8",
        )
        assets = self.output / "assets"
        assets.mkdir()
        (assets / "empty.png").write_bytes(b"")

        proc = subprocess.run(
            ["bash", str(PACKAGE_INGEST), str(self.output), "--deck-id", "lark-empty-asset-2026-07-10"],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("LOCAL_ASSET_EMPTY", proc.stderr)
        self.assertFalse((self.output / "deck.zip").exists())

    def test_package_ingest_rejects_unsafe_redirect_shell(self):
        (self.output / "index.html").write_text(
            '<!doctype html><meta http-equiv="refresh" content="0; url=../deck.html">',
            encoding="utf-8",
        )
        (self.output / "deck.json").write_text(
            json.dumps({"schema_version": "1.0", "slides": []}),
            encoding="utf-8",
        )
        (self.output / "assets-manifest.yaml").write_text("assets: []\n", encoding="utf-8")
        (self.output / "assets").mkdir()

        proc = subprocess.run(
            ["bash", str(PACKAGE_INGEST), str(self.output), "--deck-id", "lark-wide-2026-06-30"],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("LOCAL_REF_ESCAPE index.html -> ../deck.html", proc.stderr)

    def test_package_ingest_rejects_name(self):
        proc = subprocess.run(
            [
                "bash",
                str(PACKAGE_INGEST),
                str(self.output),
                "--deck-id",
                "lark-demo-2026-06-11",
                "--name",
                "lark-demo-2026-06-11",
            ],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("does not accept --name", proc.stderr)


if __name__ == "__main__":
    unittest.main()
