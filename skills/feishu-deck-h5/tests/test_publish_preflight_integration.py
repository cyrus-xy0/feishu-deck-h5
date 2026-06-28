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


if __name__ == "__main__":
    unittest.main()
