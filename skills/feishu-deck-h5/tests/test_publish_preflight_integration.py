"""delivery-8/9 · end-to-end publish wiring through the new pre-flight.

Drives publish.py on the real (non-dry) Magic Page path with mocked node
uploader + publisher on the default path without the old PyYAML/visual gate,
proving that a normal small deck still publishes through the new wiring:
  - the resource-size pre-flight actually runs (writes MAGIC_PAGE_PREFLIGHT.md),
  - the publish integrity report runs (writes PUBLISH_INTEGRITY_REPORT.md),
  - --keep-inline-code is passed by default (runtime stays inline in the artifact),
  - the old check-only quality reports are not produced,
  - the publish succeeds and returns the mocked app_url.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PUBLISH = REPO / "subskills/publisher/publish.py"

UPLOADER_JS = (
    'const p=process.argv[2];const i=process.argv.indexOf("--key");'
    'const k=i>=0?process.argv[i+1]:p;'
    'console.log("https://tos.example.test/"+k.replace(/[^A-Za-z0-9._/-]+/g,"-"));'
)
# mock Magic Page publisher: echo a JSON app_url, ignore the upload.
PUBLISHER_JS = (
    'console.log(JSON.stringify({app_url:"https://magic.example.test/html-box/test123",'
    'app_id:"test123"}));'
)
PUBLISHER_LIMIT_JS = (
    'const fs=require("fs");'
    'const file=process.argv[2]==="publish"?process.argv[3]:process.argv[2];'
    'const max=Number(process.env.MOCK_MAGIC_MAX_CHARS||"900000");'
    'const chars=fs.readFileSync(file,"utf8").length;'
    'if(chars>max){console.error("mock 413: "+chars+" > "+max);process.exit(13);}'
    'console.log(JSON.stringify({app_url:"https://magic.example.test/html-box/limited",'
    'app_id:"limited",chars}));'
)


class PublishPreflightIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_normal_deck_publishes_through_preflight_keeping_runtime_inline(self) -> None:
        run_dir: Path | None = None
        try:
            with tempfile.TemporaryDirectory(prefix="pub-int-") as td:
                t = Path(td)
                uploader = t / "up.js"
                uploader.write_text(UPLOADER_JS, encoding="utf-8")
                publisher = t / "pub.js"
                publisher.write_text(PUBLISHER_JS, encoding="utf-8")

                # tiny self-contained deck: inline runtime <script>, one local image,
                # no remote refs, nothing oversized → pre-flight passes clean.
                (t / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
                html = t / "index.html"
                html.write_text(
                    '<html><head><style>.h{color:#000}</style></head><body>'
                    '<script>window.__feishuDeck=1;</script>'
                    '<div class="slide" data-slide-key="s1"><img src="logo.png"></div>'
                    '</body></html>',
                    encoding="utf-8",
                )

                env = dict(os.environ, MAGIC_TOKEN="dummy-token-for-test")
                proc = subprocess.run(
                    [sys.executable, str(PUBLISH),
                     "--html", str(html), "--title", "Integration",
                     "--skip-self-check",
                     "--magic-asset-uploader", str(uploader),
                     "--magic-page-script", str(publisher)],
                    text=True, capture_output=True, env=env,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
                manifest = json.loads(proc.stdout)
                pub = manifest["publication"]
                self.assertTrue(pub["ok"], pub.get("reason"))
                self.assertEqual(pub["app_url"], "https://magic.example.test/html-box/test123")

                # locate the exact run output dir from the manifest's task_id
                task_id = manifest["task_id"]                       # e.g. publisher/<slug>-<ts>
                run_dir = REPO / "runs" / task_id.split("/")[0]
                out_dir = REPO / "runs" / task_id / "output"

                self.assertTrue((out_dir / "MAGIC_PAGE_PREFLIGHT.md").exists(),
                                "pre-flight report MAGIC_PAGE_PREFLIGHT.md was not written")
                self.assertTrue((out_dir / "PUBLISH_INTEGRITY_REPORT.md").exists(),
                                "publish integrity report PUBLISH_INTEGRITY_REPORT.md was not written")
                self.assertFalse((out_dir / "PUBLISH_QUALITY_REPORT-prepublish.md").exists(),
                                 "old check-only prepublish gate should not run")
                self.assertFalse((out_dir / "PUBLISH_QUALITY_REPORT-finalbytes.md").exists(),
                                 "old check-only finalbytes gate should not run")
                packaged = (out_dir / "magic-page-ready.html").read_text(encoding="utf-8")
                # --keep-inline-code default: runtime stays inline (not a hashed .js)
                self.assertIn("window.__feishuDeck=1", packaged)
                # local image was hosted to TOS, no local path residue
                self.assertIn("https://tos.example.test/", packaged)
                self.assertNotIn('src="logo.png"', packaged)
        finally:
            if run_dir and run_dir.exists():
                shutil.rmtree(run_dir, ignore_errors=True)

    def test_dry_run_executes_publish_preparation_without_token_or_remote_writes(self) -> None:
        run_dir: Path | None = None
        try:
            with tempfile.TemporaryDirectory(prefix="pub-dry-") as td:
                t = Path(td)
                (t / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
                html = t / "index.html"
                html.write_text(
                    '<html><head><style>.h{color:#000}</style></head><body>'
                    '<script>window.__feishuDeck=1;</script>'
                    '<div class="slide" data-slide-key="s1"><img src="logo.png"></div>'
                    '</body></html>',
                    encoding="utf-8",
                )

                env = dict(os.environ)
                env.pop("MAGIC_TOKEN", None)
                proc = subprocess.run(
                    [sys.executable, str(PUBLISH),
                     "--html", str(html), "--title", "Dry Run",
                     "--dry-run", "--skip-self-check"],
                    text=True, capture_output=True, env=env,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
                manifest = json.loads(proc.stdout)
                run_dir = REPO / "runs" / manifest["task_id"].split("/")[0]
                out_dir = REPO / "runs" / manifest["task_id"] / "output"
                pub = manifest["publication"]

                self.assertTrue(pub["ok"], pub.get("reason"))
                self.assertTrue(pub["dry_run"])
                self.assertEqual(pub["reason"], "dry-run after publish preparation and integrity checks")
                self.assertTrue((out_dir / "MAGIC_PAGE_PREFLIGHT.md").exists())
                self.assertTrue((out_dir / "PUBLISH_SIZE_REPORT.md").exists())
                self.assertTrue((out_dir / "PUBLISH_INTEGRITY_REPORT.md").exists())
                ready = (out_dir / "magic-page-ready.html").read_text(encoding="utf-8")
                self.assertIn("https://dryrun.local/feishu-deck-h5/", ready)
                self.assertNotIn('src="logo.png"', ready)
                self.assertFalse((out_dir / "publisher-magic-page.log").exists(),
                                 "dry-run must not call the final Magic Page publish API")
        finally:
            if run_dir and run_dir.exists():
                shutil.rmtree(run_dir, ignore_errors=True)

    def test_dry_run_fails_when_publish_integrity_gate_finds_local_iframe(self) -> None:
        run_dir: Path | None = None
        try:
            with tempfile.TemporaryDirectory(prefix="pub-dry-bad-") as td:
                t = Path(td)
                (t / "demo.html").write_text("<html><body>demo</body></html>", encoding="utf-8")
                html = t / "index.html"
                html.write_text(
                    '<html><body><div class="slide" data-slide-key="s1">'
                    '<iframe src="demo.html"></iframe>'
                    '</div></body></html>',
                    encoding="utf-8",
                )

                env = dict(os.environ)
                env.pop("MAGIC_TOKEN", None)
                proc = subprocess.run(
                    [sys.executable, str(PUBLISH),
                     "--html", str(html), "--title", "Dry Run Bad",
                     "--dry-run", "--skip-self-check", "--skip-magic-iframe-faas"],
                    text=True, capture_output=True, env=env,
                )
                self.assertEqual(proc.returncode, 1, proc.stderr or proc.stdout)
                manifest = json.loads(proc.stdout)
                run_dir = REPO / "runs" / manifest["task_id"].split("/")[0]
                out_dir = REPO / "runs" / manifest["task_id"] / "output"
                pub = manifest["publication"]

                self.assertFalse(pub["ok"])
                self.assertTrue(pub["dry_run"])
                self.assertIn("publish artifact integrity check failed", pub["reason"])
                report = (out_dir / "PUBLISH_INTEGRITY_REPORT.md").read_text(encoding="utf-8")
                self.assertIn("demo.html", report)
        finally:
            if run_dir and run_dir.exists():
                shutil.rmtree(run_dir, ignore_errors=True)

    def test_local_iframe_html_is_proxied_before_publish(self) -> None:
        run_dir: Path | None = None
        try:
            with tempfile.TemporaryDirectory(prefix="pub-iframe-") as td:
                t = Path(td)
                uploader = t / "up.js"
                uploader.write_text(UPLOADER_JS, encoding="utf-8")
                publisher = t / "pub.js"
                publisher.write_text(PUBLISHER_JS, encoding="utf-8")

                (t / "demo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
                (t / "demo.html").write_text(
                    '<html><body><img src="demo.png">'
                    "<script>const current = new URL(location.href);</script>"
                    "</body></html>",
                    encoding="utf-8",
                )
                html = t / "index.html"
                html.write_text(
                    '<html><body><div class="slide" data-slide-key="s1">'
                    '<iframe src="demo.html"></iframe>'
                    "</div></body></html>",
                    encoding="utf-8",
                )

                env = dict(os.environ, MAGIC_TOKEN="dummy-token-for-test")
                proc = subprocess.run(
                    [sys.executable, str(PUBLISH),
                     "--html", str(html), "--title", "Iframe Integration",
                     "--skip-self-check",
                     "--magic-base-url", "https://magic.example.test",
                     "--magic-asset-uploader", str(uploader),
                     "--magic-page-script", str(publisher),
                     "--magic-iframe-faas-dry-run"],
                    text=True, capture_output=True, env=env,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
                manifest = json.loads(proc.stdout)
                run_dir = REPO / "runs" / manifest["task_id"].split("/")[0]
                out_dir = REPO / "runs" / manifest["task_id"] / "output"

                ready = (out_dir / "magic-page-ready.html").read_text(encoding="utf-8")
                self.assertIn("https://magic.example.test/api/faas/", ready)
                self.assertIn("?p=demo", ready)
                self.assertNotIn('src="demo.html"', ready)
                iframe_report = json.loads((out_dir / "magic-iframe-faas.json").read_text(encoding="utf-8"))
                self.assertEqual(iframe_report["rewritten"], 1)
                self.assertIn("https://tos.example.test/feishu-deck-h5/", iframe_report["iframes"][0]["tos_url"])
                child_html = Path(iframe_report["iframes"][0]["prepared_html"]).read_text(encoding="utf-8")
                self.assertIn("https://tos.example.test/feishu-deck-h5/", child_html)
                self.assertIn("new URL(location.href)", child_html)
        finally:
            if run_dir and run_dir.exists():
                shutil.rmtree(run_dir, ignore_errors=True)

    def test_oversized_magic_html_auto_externalizes_inline_code_before_api(self) -> None:
        run_dir: Path | None = None
        try:
            with tempfile.TemporaryDirectory(prefix="pub-size-") as td:
                t = Path(td)
                uploader = t / "up.js"
                uploader.write_text(UPLOADER_JS, encoding="utf-8")
                publisher = t / "pub-limit.js"
                publisher.write_text(PUBLISHER_LIMIT_JS, encoding="utf-8")

                html = t / "index.html"
                html.write_text(
                    "<html><head><style>"
                    + (".huge{color:#123456;}" * 160)
                    + "</style></head><body>"
                    '<div class="slide" data-slide-key="s1">size gate</div>'
                    "</body></html>",
                    encoding="utf-8",
                )

                env = dict(os.environ, MAGIC_TOKEN="dummy-token-for-test", MOCK_MAGIC_MAX_CHARS="1000")
                proc = subprocess.run(
                    [sys.executable, str(PUBLISH),
                     "--html", str(html), "--title", "Size Integration",
                     "--skip-self-check",
                     "--magic-max-html-chars", "1000",
                     "--magic-asset-uploader", str(uploader),
                     "--magic-page-script", str(publisher)],
                    text=True, capture_output=True, env=env,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
                manifest = json.loads(proc.stdout)
                run_dir = REPO / "runs" / manifest["task_id"].split("/")[0]
                out_dir = REPO / "runs" / manifest["task_id"] / "output"

                pub = manifest["publication"]
                self.assertTrue(pub["ok"], pub.get("reason"))
                self.assertEqual(pub["app_url"], "https://magic.example.test/html-box/limited")
                ready = (out_dir / "magic-page-ready.html").read_text(encoding="utf-8")
                self.assertLessEqual(len(ready), 1000)
                self.assertIn('<link rel="stylesheet"', ready)
                self.assertNotIn(".huge{color:#123456;}" * 20, ready)

                size_report = (out_dir / "PUBLISH_SIZE_REPORT.md").read_text(encoding="utf-8")
                self.assertIn("auto_externalized_inline_code: True", size_report)
                self.assertIn("mode: `keep-inline-code`", size_report)
                self.assertIn("mode: `externalize-inline-code`", size_report)
        finally:
            if run_dir and run_dir.exists():
                shutil.rmtree(run_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
