"""delivery-8 · Magic Page publish size pre-flight.

Covers the up-front oversized-resource audit that turns the historical serial
fail/compress/re-publish loop into one report: oversized local/data: resources are
reported together (blocking), in-limit resources pass, and the ffmpeg transcode
command is downscale-only. The actual ffmpeg execution path is exercised only when
ffmpeg is installed; here we pin the pure command-construction + audit logic, which
needs no ffmpeg.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PREFLIGHT = REPO / "assets/magic-page-preflight.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("magic_page_preflight", PREFLIGHT)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


PF = _load_module()


def _run_cli(html: Path, *extra: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(PREFLIGHT), str(html), "--json", *extra],
        text=True, capture_output=True,
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
    return proc.returncode, payload


class PreflightAuditTest(unittest.TestCase):
    def test_oversized_local_video_blocks_with_remediation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            (t / "big.mp4").write_bytes(b"\0" * (70 * 1024 * 1024))
            (t / "ok.png").write_bytes(b"\0" * (1 * 1024 * 1024))
            html = t / "index.html"
            html.write_text('<video src="big.mp4" poster="ok.png"></video><img src="ok.png">', encoding="utf-8")
            rc, payload = _run_cli(html)
            self.assertEqual(rc, 1)
            self.assertFalse(payload["ok"])
            refs = [o["ref"] for o in payload["oversized"]]
            self.assertIn("big.mp4", refs)
            # the in-limit image/poster is NOT flagged
            self.assertNotIn("ok.png", refs)
            block = next(o for o in payload["oversized"] if o["ref"] == "big.mp4")
            self.assertTrue(block["is_video"])
            self.assertIn("ffmpeg", block["remediation"])

    def test_all_in_limit_passes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            (t / "small.mp4").write_bytes(b"\0" * (2 * 1024 * 1024))
            html = t / "index.html"
            html.write_text('<video src="small.mp4"></video>', encoding="utf-8")
            rc, payload = _run_cli(html)
            self.assertEqual(rc, 0)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["oversized"], [])

    def test_oversized_nonvideo_blocks_without_ffmpeg_command(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            (t / "huge.png").write_bytes(b"\0" * (70 * 1024 * 1024))
            html = t / "index.html"
            html.write_text('<img src="huge.png">', encoding="utf-8")
            rc, payload = _run_cli(html)
            self.assertEqual(rc, 1)
            block = next(o for o in payload["oversized"] if o["ref"] == "huge.png")
            self.assertFalse(block["is_video"])
            self.assertNotIn("ffmpeg", block["remediation"])

    def test_compress_without_ffmpeg_still_blocks(self) -> None:
        # On a machine without ffmpeg, --compress must not crash and must keep the
        # oversized video BLOCKING (never silently "pass" an un-fixed resource).
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            (t / "big.mp4").write_bytes(b"\0" * (70 * 1024 * 1024))
            html = t / "index.html"
            html.write_text('<video src="big.mp4"></video>', encoding="utf-8")
            rc, payload = _run_cli(html, "--compress", "--out", str(t / "out.html"))
            if payload.get("ffmpeg_available"):
                self.skipTest("ffmpeg present; this test pins the ffmpeg-absent path")
            self.assertEqual(rc, 1)
            self.assertFalse(payload["ok"])

    def test_data_uri_oversized_video_detected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            t = Path(td)
            big = base64.b64encode(b"\0" * (70 * 1024 * 1024)).decode("ascii")
            html = t / "index.html"
            html.write_text(f'<video src="data:video/mp4;base64,{big}"></video>', encoding="utf-8")
            rc, payload = _run_cli(html)
            self.assertEqual(rc, 1)
            self.assertTrue(any(o["kind"] == "data-uri" and o["is_video"] for o in payload["oversized"]))


class PreflightUnitTest(unittest.TestCase):
    def test_ffmpeg_cmd_downscale_only(self) -> None:
        src, dst = Path("/in.mp4"), Path("/out.mp4")
        # within 1080p → NO scale filter (never upscale)
        cmd_small = PF.build_ffmpeg_cmd(src, dst, width=1280, height=720)
        self.assertNotIn("-vf", cmd_small)
        # over 1080p → scale filter present
        cmd_big = PF.build_ffmpeg_cmd(src, dst, width=2880, height=2160)
        self.assertIn("-vf", cmd_big)
        self.assertIn("force_original_aspect_ratio=decrease", " ".join(cmd_big))
        # unknown dims → safe default keeps the scale filter
        cmd_unknown = PF.build_ffmpeg_cmd(src, dst, width=None, height=None)
        self.assertIn("-vf", cmd_unknown)
        # always drops audio + caps fps
        for c in (cmd_small, cmd_big):
            self.assertIn("-an", c)
            self.assertIn("30", c)

    def test_data_uri_size_and_mime(self) -> None:
        payload = b"hello-bytes"
        uri = "data:video/mp4;base64," + base64.b64encode(payload).decode("ascii")
        size, mime = PF.data_uri_size_and_mime(uri)
        self.assertEqual(size, len(payload))
        self.assertEqual(mime, "video/mp4")
        self.assertIsNone(PF.data_uri_size_and_mime("not-a-data-uri"))

    def test_is_video_ref(self) -> None:
        self.assertTrue(PF.is_video_ref("clip.mp4"))
        self.assertTrue(PF.is_video_ref("https://x.test/a.webm"))
        self.assertFalse(PF.is_video_ref("pic.png"))


if __name__ == "__main__":
    unittest.main()
