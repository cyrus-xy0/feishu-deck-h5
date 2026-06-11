"""Tests for assets/shoot-page.py (F-304) — deterministic ad-hoc page shots.

The failure it guards against: a deck embedding a LIVE external iframe makes
naive Playwright shots hang (goto 'load' never settles; screenshot stalls on
"waiting for fonts"). shoot-page.py route-aborts http(s) by default, so the
shot must complete FAST even when the deck embeds an unreachable live URL.
"""
import subprocess
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHOOT = HERE.parent.parent / "assets" / "shoot-page.py"


def _chromium_ok():
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:
        return False
    return True


@unittest.skipUnless(_chromium_ok(), "playwright/chromium unavailable")
class ShootPage(unittest.TestCase):
    def test_blocks_live_iframe_and_completes_fast(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            html = Path(td) / "index.html"
            # 203.0.113.0/24 is TEST-NET-3: guaranteed unroutable — a naive
            # wait_until='load' shot would hang on this iframe.
            html.write_text(
                '<html><body style="background:#0B0F1A;color:#fff">'
                '<div class="slide-frame"><div class="slide">'
                '<h1 style="font-size:48px">Deterministic shot</h1>'
                '<iframe src="https://203.0.113.1/never-loads" '
                'style="width:800px;height:400px"></iframe>'
                '</div></div></body></html>', encoding="utf-8")
            out = Path(td) / "shot.png"
            t0 = time.time()
            r = subprocess.run(
                [sys.executable, str(SHOOT), str(html), "1",
                 "--out", str(out), "--wait", "600"],
                capture_output=True, text=True, timeout=60)
            elapsed = time.time() - t0
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(out.exists() and out.stat().st_size > 5000)
            # the whole point: no 30s load-timeout, no fonts stall
            self.assertLess(elapsed, 20, f"took {elapsed:.1f}s — blocking failed?")
            self.assertIn("external blocked", r.stdout)

    def test_bad_input_exits_2(self):
        r = subprocess.run(
            [sys.executable, str(SHOOT), "/nonexistent/index.html", "1"],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
