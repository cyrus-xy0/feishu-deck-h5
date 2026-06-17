"""F-341 unit guards for assets/optimize-images.py — the deck image-optimization
pass that shrinks oversized rasters (4K backgrounds, multi-MB PNG photos) for
fast mobile loading.

Properties under test:
  • downscale: any raster whose longest edge > max-edge is shrunk to fit;
  • idempotent: a second run is a no-op (dimension-gated);
  • opaque PNG ≥ min-bytes → transcoded to JPEG, .png removed, every reference
    (index.html / deck.json) rewritten to the .jpg path;
  • a PNG with REAL transparency is NEVER transcoded (only downscaled);
  • PNGs below the size threshold and already-right-sized images are left alone;
  • --dry-run touches nothing;
  • percent-encoded (Chinese) reference paths are rewritten too.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

import pytest

# optimize-images.py treats Pillow as optional (degrades to sips / no-op without
# it), and CI installs only pytest/pyyaml/jsonschema/beautifulsoup4 — so these
# Pillow-dependent tests must SKIP, not error at collection, when PIL is absent.
Image = pytest.importorskip("PIL.Image")

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parents[1]
SCRIPT = SKILL_ROOT / "assets" / "optimize-images.py"


def _noise_img(mode, size):
    """A high-entropy image so PNG can't compress it to nothing (keeps test
    files comfortably above the transcode size threshold)."""
    w, h = size
    n = len(mode)
    return Image.frombytes(mode, size, os.urandom(w * h * n))


def _run(deck_dir, *extra):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(deck_dir), *extra],
        capture_output=True, text=True)


class OptimizeImagesTest(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())

    def _dims(self, p):
        with Image.open(p) as im:
            return im.size

    # ── downscale ────────────────────────────────────────────────────────────
    def test_downscale_oversized_jpeg_and_idempotent(self):
        bg = self.d / "bg" / "page-001.jpg"
        bg.parent.mkdir(parents=True)
        _noise_img("RGB", (3840, 2160)).save(bg, "JPEG", quality=92)
        (self.d / "index.html").write_text('<img src="bg/page-001.jpg">', encoding="utf-8")
        before = bg.stat().st_size

        r = _run(self.d, "--max-edge", "1920")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(max(self._dims(bg)), 1920)          # longest edge capped
        self.assertEqual(self._dims(bg), (1920, 1080))       # aspect preserved (16:9)
        self.assertLess(bg.stat().st_size, before)           # smaller on disk

        # idempotent: second run does not shrink further / re-encode
        size_after_first = bg.stat().st_size
        r2 = _run(self.d, "--max-edge", "1920")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertEqual(bg.stat().st_size, size_after_first)
        self.assertIn("0 downscaled", r2.stdout)

    def test_already_small_image_skipped(self):
        img = self.d / "input" / "small.jpg"
        img.parent.mkdir(parents=True)
        _noise_img("RGB", (800, 600)).save(img, "JPEG", quality=90)
        (self.d / "index.html").write_text('<img src="input/small.jpg">', encoding="utf-8")
        before = img.read_bytes()
        r = _run(self.d, "--max-edge", "1920", "--no-transcode")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(img.read_bytes(), before)           # byte-identical (untouched)

    # ── transcode opaque PNG → JPEG + ref rewrite ─────────────────────────────
    def test_opaque_png_transcoded_and_refs_rewritten(self):
        png = self.d / "input" / "photo.png"
        png.parent.mkdir(parents=True)
        _noise_img("RGB", (700, 700)).save(png, "PNG")        # opaque, high-entropy → big
        png_bytes = png.stat().st_size
        self.assertGreater(png_bytes, 150_000)
        (self.d / "index.html").write_text(
            '<img class="el" src="input/photo.png">', encoding="utf-8")
        (self.d / "deck.json").write_text(
            '{"slides":[{"elements":[{"type":"image","src":"input/photo.png"}]}]}',
            encoding="utf-8")

        r = _run(self.d, "--transcode-min-bytes", "150000")
        self.assertEqual(r.returncode, 0, r.stderr)
        jpg = self.d / "input" / "photo.jpg"
        self.assertTrue(jpg.exists())
        self.assertFalse(png.exists())                        # original removed
        # JPEG smaller than the source PNG (on real photos this is 10–15×; on the
        # incompressible random-noise test fixture the margin is naturally smaller)
        self.assertLess(jpg.stat().st_size, png_bytes)
        # references rewritten in BOTH html and deck.json (re-render stays valid)
        self.assertIn("input/photo.jpg", (self.d / "index.html").read_text())
        self.assertNotIn("input/photo.png", (self.d / "index.html").read_text())
        self.assertIn("input/photo.jpg", (self.d / "deck.json").read_text())
        self.assertNotIn("input/photo.png", (self.d / "deck.json").read_text())

    def test_transparent_png_not_transcoded(self):
        png = self.d / "input" / "logo.png"
        png.parent.mkdir(parents=True)
        im = _noise_img("RGBA", (700, 700))
        # force a genuinely transparent region so alpha-min < 255
        im.putalpha(Image.new("L", im.size, 0))
        im.save(png, "PNG")
        self.assertGreater(png.stat().st_size, 150_000)
        (self.d / "index.html").write_text('<img src="input/logo.png">', encoding="utf-8")

        r = _run(self.d, "--transcode-min-bytes", "150000")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(png.exists())                         # still a PNG
        self.assertFalse((self.d / "input" / "logo.jpg").exists())
        self.assertIn("input/logo.png", (self.d / "index.html").read_text())

    def test_small_opaque_png_below_threshold_kept(self):
        png = self.d / "input" / "icon.png"
        png.parent.mkdir(parents=True)
        Image.new("RGB", (64, 64), (10, 20, 30)).save(png, "PNG")  # tiny, opaque
        (self.d / "index.html").write_text('<img src="input/icon.png">', encoding="utf-8")
        r = _run(self.d, "--transcode-min-bytes", "150000")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(png.exists())
        self.assertFalse((self.d / "input" / "icon.jpg").exists())

    # ── dry-run ───────────────────────────────────────────────────────────────
    def test_dry_run_touches_nothing(self):
        bg = self.d / "bg" / "page-001.jpg"
        bg.parent.mkdir(parents=True)
        _noise_img("RGB", (3840, 2160)).save(bg, "JPEG", quality=92)
        (self.d / "index.html").write_text('<img src="bg/page-001.jpg">', encoding="utf-8")
        before = bg.read_bytes()
        r = _run(self.d, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(bg.read_bytes(), before)             # unchanged
        self.assertIn("would optimize", r.stdout)

    # ── percent-encoded (Chinese) refs ────────────────────────────────────────
    def test_percent_encoded_ref_rewritten_on_transcode(self):
        name = "封面.png"
        png = self.d / "input" / name
        png.parent.mkdir(parents=True)
        _noise_img("RGB", (700, 700)).save(png, "PNG")
        # HTML refers to the asset percent-encoded (as a browser/renderer emits)
        encoded = "input/" + quote(name)
        (self.d / "index.html").write_text(f'<img src="{encoded}">', encoding="utf-8")

        r = _run(self.d, "--transcode-min-bytes", "150000")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.d / "input" / "封面.jpg").exists())
        html = (self.d / "index.html").read_text()
        self.assertIn("input/" + quote("封面.jpg"), html)
        self.assertNotIn(quote(name), html)

    # ── shared pool is never touched ──────────────────────────────────────────
    def test_shared_symlink_dir_skipped(self):
        # a real (non-symlink) dir literally named "shared" is still skipped by
        # name, mirroring the pooled assets/shared the symlink points at.
        shared = self.d / "assets" / "shared"
        shared.mkdir(parents=True)
        big = shared / "pooled.jpg"
        _noise_img("RGB", (3840, 2160)).save(big, "JPEG", quality=92)
        (self.d / "index.html").write_text('<img src="assets/shared/pooled.jpg">', encoding="utf-8")
        before = big.read_bytes()
        r = _run(self.d)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(big.read_bytes(), before)            # pooled file untouched


if __name__ == "__main__":
    unittest.main()
