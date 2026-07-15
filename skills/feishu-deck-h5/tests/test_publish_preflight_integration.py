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
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PUBLISH = REPO / "subskills/publisher/publish.py"

UPLOADER_JS = r'''
const fs=require("fs");const readline=require("readline");
const args=process.argv.slice(2);
const mi=args.indexOf("--batch-manifest");
const clean=(k)=>String(k).replace(/[^A-Za-z0-9._/-]+/g,"-");
const respond=(m)=>{
  const items=m.items.map((item)=>({...item,ok:true,url:"https://tos.example.test/"+clean(item.key)}));
  return {protocol:"magic-upload-batch/v1",request_id:m.request_id||"",ok:true,base_url:m.base_url,items};};
async function main(){
if(args.includes("--batch-ndjson")){
  const rl=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
  for await(const line of rl){if(line.trim())process.stdout.write(JSON.stringify(respond(JSON.parse(line)))+"\n");}
}else if(mi>=0){
  const m=JSON.parse(fs.readFileSync(args[mi+1],"utf8"));process.stdout.write(JSON.stringify(respond(m)));
}else{
  const p=process.argv[2];const i=process.argv.indexOf("--key");const k=i>=0?process.argv[i+1]:p;
  console.log("https://tos.example.test/"+clean(k));
}
}
main().catch((e)=>{console.error(e.message);process.exit(1);});
'''.strip()
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
PUBLISHER_UPDATE_JS = (
    'const args=process.argv.slice(2);'
    'const i=args.indexOf("--remote-id");'
    'const id=i>=0?args[i+1]:"";'
    'if(id!=="stable123"){console.error("missing remote id: "+id);process.exit(17);}'
    'console.log(JSON.stringify({app_url:"https://magic.example.test/html-box/"+id,'
    'app_id:id,remote_id:id}));'
)


class PublishPreflightIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node not available")

    def test_publish_snapshot_freezes_local_asset_bytes_and_page_hashes(self) -> None:
        spec = importlib.util.spec_from_file_location("publisher_snapshot_test", PUBLISH)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        publisher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(publisher)
        with tempfile.TemporaryDirectory(prefix="publish-snapshot-") as td:
            tmp = Path(td)
            source = tmp / "source"
            output = tmp / "output"
            source.mkdir()
            output.mkdir()
            logo = source / "logo.png"
            logo.write_bytes(b"first-logo")
            html = source / "index.html"
            html.write_text(
                '<div class="slide-frame"><div class="slide" data-slide-key="cover"><img src="logo.png"></div></div>',
                encoding="utf-8",
            )
            snapshot_html, manifest = publisher.freeze_publish_snapshot(
                package_source=html,
                asset_base_dir=source,
                source_html=html,
                output_dir=output,
            )
            frozen_ref = manifest["assets"][0]["snapshot_ref"]
            frozen_asset = snapshot_html.parent / frozen_ref
            self.assertEqual(frozen_asset.read_bytes(), b"first-logo")
            self.assertEqual(manifest["pages"][0]["key"], "cover")

            logo.write_bytes(b"second-logo")
            self.assertEqual(frozen_asset.read_bytes(), b"first-logo")
            snapshot_two, manifest_two = publisher.freeze_publish_snapshot(
                package_source=html,
                asset_base_dir=source,
                source_html=html,
                output_dir=output,
            )
            self.assertNotEqual(snapshot_two.parent, snapshot_html.parent)
            self.assertNotEqual(manifest_two["snapshot_id"], manifest["snapshot_id"])

    def test_incremental_self_check_selection_prioritizes_changed_pages_and_bookends(self) -> None:
        spec = importlib.util.spec_from_file_location("publisher_selection_test", PUBLISH)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        publisher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(publisher)
        prior = [
            {"index": index, "key": f"s{index}", "sha256": f"old-{index}"}
            for index in range(1, 7)
        ]
        current = [dict(row) for row in prior]
        current[2] = {"index": 3, "key": "s3", "sha256": "new-3"}
        selected = publisher.select_incremental_self_check_pages(
            current,
            prior,
            leading_pages=3,
            max_pages=5,
        )
        self.assertEqual(selected, [1, 2, 3, 4, 6])

    def test_html_publish_workspace_is_stable_per_source_path(self) -> None:
        spec = importlib.util.spec_from_file_location("publisher_task_id_test", PUBLISH)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        publisher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(publisher)
        first = publisher.stable_publisher_task_id(Path("/tmp/a/index.html"))
        repeated = publisher.stable_publisher_task_id(Path("/tmp/a/index.html"))
        other = publisher.stable_publisher_task_id(Path("/tmp/b/index.html"))
        self.assertEqual(first, repeated)
        self.assertNotEqual(first, other)

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
                task_id = manifest["task_id"]                       # stable publisher/<slug>-<path-hash>
                run_dir = REPO / "runs" / task_id
                out_dir = REPO / "runs" / task_id / "output"

                self.assertTrue(manifest["snapshot"]["snapshot_id"])
                self.assertTrue((out_dir / "publish-snapshot.json").exists())
                self.assertTrue(manifest["timing"]["within_budget"])
                self.assertTrue((out_dir / "publish-timing.json").exists())
                self.assertTrue((out_dir / "PUBLISH_TIMING.md").exists())

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
                run_dir = REPO / "runs" / manifest["task_id"]
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
                run_dir = REPO / "runs" / manifest["task_id"]
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

    def test_republish_reuses_prior_magic_app_id_for_stable_link(self) -> None:
        task_id = "publisher-stable-link-test"
        run_dir = REPO / "runs" / task_id
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)
        try:
            with tempfile.TemporaryDirectory(prefix="pub-stable-") as td:
                t = Path(td)
                uploader = t / "up.js"
                uploader.write_text(UPLOADER_JS, encoding="utf-8")
                publisher = t / "pub-update.js"
                publisher.write_text(PUBLISHER_UPDATE_JS, encoding="utf-8")

                out_dir = run_dir / "output"
                out_dir.mkdir(parents=True)
                (out_dir / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)
                (out_dir / "index.html").write_text(
                    '<html><body><div class="slide" data-slide-key="s1">'
                    '<img src="logo.png"><p>republish</p>'
                    '</div></body></html>',
                    encoding="utf-8",
                )
                (out_dir / "magic-page-publish.json").write_text(
                    json.dumps({
                        "ok": True,
                        "app_id": "stable123",
                        "app_url": "https://magic.example.test/html-box/stable123",
                    }),
                    encoding="utf-8",
                )

                env = dict(os.environ, MAGIC_TOKEN="dummy-token-for-test")
                proc = subprocess.run(
                    [sys.executable, str(PUBLISH),
                     "--task-id", task_id, "--title", "Stable Link",
                     "--skip-self-check",
                     "--magic-base-url", "https://magic.example.test",
                     "--magic-asset-uploader", str(uploader),
                     "--magic-page-script", str(publisher)],
                    text=True, capture_output=True, env=env,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
                manifest = json.loads(proc.stdout)
                pub = manifest["publication"]
                self.assertTrue(pub["ok"], pub.get("reason"))
                self.assertEqual(pub["app_id"], "stable123")
                self.assertEqual(pub["app_url"], "https://magic.example.test/html-box/stable123")
                self.assertEqual(pub["reused_app_id"], "stable123")
        finally:
            if run_dir.exists():
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
                run_dir = REPO / "runs" / manifest["task_id"]
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
                uploader.write_text(
                    r'''
const fs=require("fs");const readline=require("readline");const args=process.argv.slice(2);
const mi=args.indexOf("--batch-manifest");
const clean=(k)=>String(k).replace(/[^A-Za-z0-9._/-]+/g,"-");
const respond=(m)=>{
  fs.appendFileSync(process.env.MOCK_UPLOAD_LOG,"REQUEST\n"+m.items.map(i=>i.key).join("\n")+"\n");
  const items=m.items.map(i=>({...i,ok:true,url:"https://tos.example.test/"+clean(i.key)}));
  return {protocol:"magic-upload-batch/v1",request_id:m.request_id||"",ok:true,base_url:m.base_url,items};};
async function main(){
if(args.includes("--batch-ndjson")){
  fs.appendFileSync(process.env.MOCK_UPLOAD_LOG,"BATCH_PROCESS\n");
  const rl=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
  for await(const line of rl){if(line.trim())process.stdout.write(JSON.stringify(respond(JSON.parse(line)))+"\n");}
}else if(mi>=0){
  const m=JSON.parse(fs.readFileSync(args[mi+1],"utf8"));process.stdout.write(JSON.stringify(respond(m)));
}else{
  const p=process.argv[2];const i=args.indexOf("--key");const k=i>=0?args[i+1]:p;
  fs.appendFileSync(process.env.MOCK_UPLOAD_LOG,"SINGLE_PROCESS\n"+k+"\n");
  console.log("https://tos.example.test/"+clean(k));
}
}
main().catch((e)=>{console.error(e.message);process.exit(1);});
'''.strip(),
                    encoding="utf-8",
                )
                publisher = t / "pub-limit.js"
                publisher.write_text(PUBLISHER_LIMIT_JS, encoding="utf-8")
                upload_log = t / "uploads.log"
                (t / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0" * 64)

                html = t / "index.html"
                html.write_text(
                    "<html><head><style>"
                    + (".huge{color:#123456;}" * 160)
                    + "</style></head><body>"
                    '<div class="slide" data-slide-key="s1">size gate'
                    '<img src="logo.png"></div>'
                    "</body></html>",
                    encoding="utf-8",
                )

                env = dict(
                    os.environ,
                    MAGIC_TOKEN="dummy-token-for-test",
                    MOCK_MAGIC_MAX_CHARS="1000",
                    MOCK_UPLOAD_LOG=str(upload_log),
                )
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
                run_dir = REPO / "runs" / manifest["task_id"]
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

                # Prediction uses only the local deterministic uploader. The
                # selected externalized mode performs one real package/upload
                # pass, so shared assets are never uploaded twice.
                uploaded_keys = upload_log.read_text(encoding="utf-8").splitlines()
                image_uploads = [
                    key for key in uploaded_keys
                    if "/assets/" in key and key.endswith(".png")
                ]
                self.assertEqual(len(image_uploads), 1, uploaded_keys)
                self.assertEqual(uploaded_keys.count("BATCH_PROCESS"), 1, uploaded_keys)
        finally:
            if run_dir and run_dir.exists():
                shutil.rmtree(run_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
