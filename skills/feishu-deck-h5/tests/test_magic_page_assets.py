from __future__ import annotations

import base64
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAGIC_PAGE_ASSETS = ROOT / "assets" / "magic-page-assets.py"
INLINE_ASSETS = ROOT / "assets" / "inline-assets.py"
MAGIC_UPLOAD = ROOT / "assets" / "magic-upload.js"

BATCH_UPLOADER_JS = r'''
const fs=require("fs");const readline=require("readline");const args=process.argv.slice(2);
const mi=args.indexOf("--batch-manifest");
const failNeedle=process.env.BATCH_FAIL_KEY||"";
const respond=(m)=>{const items=m.items.map((item)=>failNeedle&&item.key.includes(failNeedle)
    ?({...item,ok:false,error:"synthetic partial failure"})
    :({...item,ok:true,url:"https://tos.example.test/"+item.key}));
  if(process.env.BATCH_CAPTURE_CSS){for(const item of m.items){if(item.key.includes("/css/"))
    fs.writeFileSync(process.env.BATCH_CAPTURE_CSS,fs.readFileSync(item.file));}}
  const ok=items.every((item)=>item.ok);
  return {protocol:"magic-upload-batch/v1",request_id:m.request_id||"",ok,base_url:m.base_url,items};};
async function main(){
  if(args.includes("--batch-ndjson")){
    if(process.env.BATCH_PROCESS_LOG)fs.appendFileSync(process.env.BATCH_PROCESS_LOG,"PROCESS\n");
    const rl=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
    for await(const line of rl){if(!line.trim())continue;const m=JSON.parse(line);
      if(process.env.BATCH_PROCESS_LOG)fs.appendFileSync(process.env.BATCH_PROCESS_LOG,"REQUEST:"+m.items.length+"\n");
      process.stdout.write(JSON.stringify(respond(m))+"\n");}
    return;
  }
  if(mi<0)throw new Error("batch required");
  const m=JSON.parse(fs.readFileSync(args[mi+1],"utf8"));const out=respond(m);
  process.stdout.write(JSON.stringify(out));process.exitCode=out.ok?0:1;
}
main().catch((e)=>{console.error(e.message);process.exit(9);});
'''.strip()


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
                    "--legacy-uploader",
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

    def test_inline_assets_removes_local_image_preload_when_images_are_inlined(self) -> None:
        with tempfile.TemporaryDirectory(prefix="inline-assets-preload-") as td:
            tmp_path = Path(td)
            (tmp_path / "assets").mkdir()
            (tmp_path / "assets" / "hero.png").write_bytes(base64.b64decode("iVBORw0KGgo="))
            html = tmp_path / "index.html"
            out = tmp_path / "out.html"
            html.write_text(
                """
<html><head>
<link rel="preload" as="image" href="assets/hero.png">
<style>.hero{background:url("assets/hero.png")}</style>
</head><body><div class="hero"></div></body></html>
""".strip(),
                encoding="utf-8",
            )

            subprocess.run(
                [sys.executable, str(INLINE_ASSETS), str(html), "--out", str(out)],
                check=True,
                text=True,
                capture_output=True,
            )

            published_html = out.read_text(encoding="utf-8")
            self.assertNotIn('href="assets/hero.png"', published_html)
            self.assertNotIn("url(\"assets/hero.png\")", published_html)
            self.assertIn("data:image/png;base64", published_html)

    def test_inline_assets_no_image_inline_keeps_safe_relative_staging_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="inline-assets-preload-linked-") as td:
            tmp_path = Path(td)
            (tmp_path / "assets").mkdir()
            (tmp_path / "assets" / "hero.png").write_bytes(base64.b64decode("iVBORw0KGgo="))
            html = tmp_path / "index.html"
            out = tmp_path / "out.html"
            html.write_text(
                """
<html><head>
<link rel="preload" as="image" href="assets/hero.png">
<style>.hero{background:url("assets/hero.png")}</style>
</head><body><div class="hero"></div></body></html>
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
            self.assertIn('href="assets/hero.png"', published_html)
            self.assertIn("url('assets/hero.png')", published_html)
            self.assertNotIn((tmp_path / "assets" / "hero.png").as_posix(), published_html)
            self.assertNotIn("data:image", published_html)

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
            self.assertIn("assets/local.png", staged_html)
            self.assertNotIn((src_dir / "assets" / "local.png").as_posix(), staged_html)

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
                    "--asset-base-dir",
                    str(src_dir),
                    "--legacy-uploader",
                ],
                check=True,
                text=True,
                capture_output=True,
            )
            published_html = ready.read_text(encoding="utf-8")
            self.assertNotIn("data:image", published_html)
            self.assertNotIn((src_dir / "assets" / "local.png").as_posix(), published_html)
            self.assertIn("https://tos.example.test/deck/test/assets/local.png", published_html)

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
                legacy_uploader=True,
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

    def test_keep_inline_code_still_externalizes_data_uri_in_inline_css(self) -> None:
        # delivery-9 regression: the publisher now passes --keep-inline-code by
        # default so the framework runtime stays recognizable. That MUST NOT leave
        # the framework's inline `url("data:image/svg+xml;utf8,<svg…>")` grain
        # textures inline — rewrite_refs runs regardless of --keep-inline-code, so
        # every data: payload is still hosted. If this regresses, the broadened
        # residual_data_payloads check would red-card EVERY publish.
        if not shutil.which("node"):
            self.skipTest("node not available")
        with tempfile.TemporaryDirectory(prefix="magic-keepinline-") as td:
            tmp_path = Path(td)
            uploader = tmp_path / "upload-asset.js"
            uploader.write_text(
                'const p=process.argv[2];const i=process.argv.indexOf("--key");'
                'const k=i>=0?process.argv[i+1]:p;'
                'console.log("https://tos.example.test/"+k.replace(/[^A-Za-z0-9._/-]+/g,"-"));',
                encoding="utf-8",
            )
            svg = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' "
                   "width='200' height='200'><rect filter='url(%23n)'/></svg>")
            html = tmp_path / "index.html"
            out = tmp_path / "ready.html"
            html.write_text(
                f'<html><head><style>.g{{background-image:url("{svg}")}}</style></head>'
                f'<body><script>window.__deck=1;const u="url("+x+")";</script>'
                f'<div class="g"></div></body></html>',
                encoding="utf-8",
            )
            subprocess.run(
                [sys.executable, str(MAGIC_PAGE_ASSETS), str(html), "--out", str(out),
                 "--uploader", str(uploader), "--base-url", "https://magic.example.test",
                 "--key-prefix", "deck/test", "--keep-inline-code", "--legacy-uploader"],
                check=True, text=True, capture_output=True,
            )
            published = out.read_text(encoding="utf-8")
            self.assertNotIn("data:image", published)                  # data: hosted
            self.assertIn("https://tos.example.test/deck/test/data-uri/", published)
            self.assertIn("window.__deck=1", published)                # runtime kept inline

    def test_batch_uploader_uses_one_node_process_for_20_and_100_assets(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node not available")
        for asset_count in (20, 100):
            with self.subTest(asset_count=asset_count), tempfile.TemporaryDirectory(
                prefix=f"magic-batch-{asset_count}-"
            ) as td:
                tmp_path = Path(td)
                assets = tmp_path / "assets"
                assets.mkdir()
                refs = []
                for idx in range(asset_count):
                    name = f"i{idx:03d}.png"
                    (assets / name).write_bytes(b"png" + idx.to_bytes(2, "big"))
                    refs.append(f'<img src="assets/{name}">')
                html = tmp_path / "index.html"
                out = tmp_path / "ready.html"
                html.write_text(
                    "<html><head><style>.x{color:red}</style></head><body>"
                    + "".join(refs)
                    + "<script>window.batchReady=true;</script></body></html>",
                    encoding="utf-8",
                )
                uploader = tmp_path / "batch-uploader.js"
                uploader.write_text(BATCH_UPLOADER_JS, encoding="utf-8")
                process_log = tmp_path / "process.log"
                env = dict(os.environ, BATCH_PROCESS_LOG=str(process_log))
                proc = subprocess.run(
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
                        "--upload-workers",
                        "8",
                    ],
                    text=True,
                    capture_output=True,
                    env=env,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
                # local assets + one CSS block + one JS block share one manifest.
                self.assertEqual(
                    process_log.read_text(encoding="utf-8").splitlines(),
                    ["PROCESS", f"REQUEST:{asset_count}", "REQUEST:2"],
                )
                published = out.read_text(encoding="utf-8")
                self.assertEqual(published.count("https://tos.example.test/"), asset_count + 2)
                self.assertNotIn("data:", published)

    def test_batch_partial_failure_is_atomic_and_reports_item_error(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node not available")
        with tempfile.TemporaryDirectory(prefix="magic-batch-partial-") as td:
            tmp_path = Path(td)
            for name in ("ok-a.png", "fail.png", "ok-b.png"):
                (tmp_path / name).write_bytes(name.encode("utf-8"))
            html = tmp_path / "index.html"
            out = tmp_path / "ready.html"
            html.write_text(
                '<html><body><img src="ok-a.png"><img src="fail.png">'
                '<img src="ok-b.png"></body></html>',
                encoding="utf-8",
            )
            uploader = tmp_path / "batch-uploader.js"
            uploader.write_text(BATCH_UPLOADER_JS, encoding="utf-8")
            process_log = tmp_path / "process.log"
            env = dict(
                os.environ,
                BATCH_PROCESS_LOG=str(process_log),
                BATCH_FAIL_KEY="fail.png",
            )
            proc = subprocess.run(
                [
                    sys.executable, str(MAGIC_PAGE_ASSETS), str(html),
                    "--out", str(out), "--uploader", str(uploader),
                    "--base-url", "https://magic.example.test",
                    "--key-prefix", "deck/test",
                ],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("synthetic partial failure", proc.stderr)
            self.assertEqual(
                process_log.read_text(encoding="utf-8").splitlines(),
                ["PROCESS", "REQUEST:3"],
            )
            self.assertFalse(out.exists(), "partial upload must not write partially rewritten HTML")

    def test_batch_externalized_css_uses_rewritten_hosted_resource_url(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node not available")
        with tempfile.TemporaryDirectory(prefix="magic-batch-css-order-") as td:
            tmp_path = Path(td)
            (tmp_path / "hero.png").write_bytes(b"hero")
            html = tmp_path / "index.html"
            out = tmp_path / "ready.html"
            html.write_text(
                '<html><head><style>.hero{background:url("hero.png")}</style></head>'
                '<body><div class="hero"></div></body></html>',
                encoding="utf-8",
            )
            uploader = tmp_path / "batch-uploader.js"
            uploader.write_text(BATCH_UPLOADER_JS, encoding="utf-8")
            captured_css = tmp_path / "captured.css"
            process_log = tmp_path / "process.log"
            env = dict(
                os.environ,
                BATCH_CAPTURE_CSS=str(captured_css),
                BATCH_PROCESS_LOG=str(process_log),
            )
            proc = subprocess.run(
                [
                    sys.executable, str(MAGIC_PAGE_ASSETS), str(html),
                    "--out", str(out), "--uploader", str(uploader),
                    "--base-url", "https://magic.example.test",
                    "--key-prefix", "deck/test",
                ],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            css = captured_css.read_text(encoding="utf-8")
            self.assertIn("https://tos.example.test/deck/test/hero.png", css)
            self.assertNotIn('url("hero.png")', css)
            self.assertEqual(
                process_log.read_text(encoding="utf-8").splitlines(),
                ["PROCESS", "REQUEST:1", "REQUEST:1"],
            )

    def test_custom_single_file_uploader_needs_explicit_legacy_flag(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node not available")
        with tempfile.TemporaryDirectory(prefix="magic-batch-legacy-") as td:
            tmp_path = Path(td)
            (tmp_path / "a.png").write_bytes(b"a")
            html = tmp_path / "index.html"
            html.write_text('<html><body><img src="a.png"></body></html>', encoding="utf-8")
            uploader = tmp_path / "legacy.js"
            uploader.write_text(
                'console.log("https://tos.example.test/legacy.png");',
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    sys.executable, str(MAGIC_PAGE_ASSETS), str(html),
                    "--out", str(tmp_path / "out.html"), "--uploader", str(uploader),
                    "--base-url", "https://magic.example.test",
                    "--key-prefix", "deck/test",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 2)
            self.assertIn("explicit --legacy-uploader", proc.stderr)

    def test_upload_cache_key_changes_with_content_and_base_url(self) -> None:
        spec = importlib.util.spec_from_file_location("magic_page_assets_cache", MAGIC_PAGE_ASSETS)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix="magic-cache-key-") as td:
            asset = Path(td) / "a.png"
            asset.write_bytes(b"one")
            first = module._upload_spec(asset, key="deck/a.png", base_url="https://magic-a.test")
            other_base = module._upload_spec(asset, key="deck/a.png", base_url="https://magic-b.test")
            asset.write_bytes(b"two")
            other_content = module._upload_spec(asset, key="deck/a.png", base_url="https://magic-a.test")
            self.assertNotEqual(first["cache_key"], other_base["cache_key"])
            self.assertNotEqual(first["cache_key"], other_content["cache_key"])

    def test_native_magic_uploader_batch_reports_per_item_validation_error(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node not available")
        with tempfile.TemporaryDirectory(prefix="magic-upload-native-") as td:
            tmp_path = Path(td)
            asset = tmp_path / "a.png"
            asset.write_bytes(b"a")
            manifest = tmp_path / "manifest.json"
            manifest.write_text(
                json.dumps({
                    "protocol": "magic-upload-batch/v1",
                    "base_url": "https://magic.example.test",
                    "items": [{
                        "id": "0" * 64,
                        "file": str(asset),
                        "key": "deck/a.png",
                        "content_type": "image/png",
                        "sha256": "not-a-sha",
                        "cache_key": "0" * 64,
                    }],
                }),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    "node", str(MAGIC_UPLOAD), "--batch-manifest", str(manifest),
                    "--base-url", "https://magic.example.test", "--workers", "4",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 1, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["protocol"], "magic-upload-batch/v1")
            self.assertFalse(payload["items"][0]["ok"])
            self.assertIn("invalid sha256", payload["items"][0]["error"])

    def test_native_magic_uploader_ndjson_serves_two_requests_in_one_process(self) -> None:
        if not shutil.which("node"):
            self.skipTest("node not available")
        with tempfile.TemporaryDirectory(prefix="magic-upload-ndjson-") as td:
            asset = Path(td) / "a.png"
            asset.write_bytes(b"a")
            proc = subprocess.Popen(
                [
                    "node", str(MAGIC_UPLOAD), "--batch-ndjson",
                    "--base-url", "https://magic.example.test", "--workers", "2",
                ],
                text=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=1,
            )
            self.assertIsNotNone(proc.stdin)
            self.assertIsNotNone(proc.stdout)
            for request_id in ("first", "second"):
                request = {
                    "protocol": "magic-upload-batch/v1",
                    "request_id": request_id,
                    "base_url": "https://magic.example.test",
                    "items": [{
                        "id": "0" * 64,
                        "file": str(asset),
                        "key": f"deck/{request_id}.png",
                        "content_type": "image/png",
                        "sha256": "invalid",
                        "cache_key": "0" * 64,
                    }],
                }
                proc.stdin.write(json.dumps(request) + "\n")
                proc.stdin.flush()
                response = json.loads(proc.stdout.readline())
                self.assertEqual(response["request_id"], request_id)
                self.assertFalse(response["items"][0]["ok"])
            proc.stdin.close()
            self.assertEqual(proc.wait(timeout=10), 0, proc.stderr.read())


if __name__ == "__main__":
    unittest.main()
