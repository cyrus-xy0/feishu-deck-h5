#!/usr/bin/env python3
"""shoot-page.py — F-304: deterministic ad-hoc screenshot of ONE deck page.

Why this exists (the failure it kills)
--------------------------------------
A deck containing a LIVE external iframe (an embedded larkoffice doc, a web
dashboard) makes every hand-rolled Playwright shot hang:

  · `goto(wait_until='load')` times out — the embed long-polls / streams and
    never reaches 'load';
  · even after `domcontentloaded`, `page.screenshot()` stalls on
    "waiting for fonts to load…" because the live frame keeps loading webfonts.

One live iframe on ONE page degrades screenshots of EVERY page of the deck
(all frames share the DOM). Each ad-hoc attempt burned ~30-60s in timeouts.

The fix is also a philosophy fit: the visual pipeline wants SETTLED-STATE
pixels, and live external content is never settled. So this tool route-ABORTS
every http(s) request by default — local file:// assets load normally, the
live embed renders as an empty panel — making shots instant and deterministic.

This is the sanctioned way to take a quick look at one page between renders.
(The full-fidelity path remains `render-deck.py --scope N`, whose deck-log
auto-snapshot handles live iframes itself.) Never hand-roll a
`wait_until='load'` Playwright shot against a deck that may embed live URLs.

Usage
-----
    python3 assets/shoot-page.py <index.html> <page> [--out PATH]
        [--allow-external] [--wait MS] [--scale {1,2}]

    page               1-based page number (= URL #N = frame_index)
    --out PATH         output PNG (default /tmp/shoot-p<N>.png)
    --allow-external   let http(s) through — for shooting the live embed
                       itself; expect slow + non-deterministic pixels
    --wait MS          settle wait after navigation (default 1800)
    --scale {1,2}      device pixel ratio (2 = retina-sharp, default 1)

Exit: 0 shot written · 2 bad input · 3 navigation/screenshot failed.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("index_html", type=Path)
    ap.add_argument("page", help="1-based page number (or '#N')")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--allow-external", action="store_true",
                    help="do NOT block http(s) — slow, non-deterministic")
    ap.add_argument("--wait", type=int, default=1800,
                    help="settle wait in ms after navigation (default 1800)")
    ap.add_argument("--scale", type=int, choices=(1, 2), default=1)
    args = ap.parse_args(argv)

    html = args.index_html.resolve()
    if not html.exists():
        print(f"shoot-page: {html} not found", file=sys.stderr)
        return 2
    m = re.search(r"\d+", str(args.page))
    if not m:
        print(f"shoot-page: bad page {args.page!r}", file=sys.stderr)
        return 2
    n = int(m.group(0))
    out = args.out or Path(f"/tmp/shoot-p{n}.png")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("shoot-page: playwright not installed "
              "(pip install playwright && python -m playwright install chromium)",
              file=sys.stderr)
        return 3

    t0 = time.time()
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            # delivery-8: close the browser in finally so a navigation/screenshot
            # failure never leaks the Chromium process.
            try:
                pg = b.new_page(viewport={"width": 1920, "height": 1080},
                                device_scale_factor=args.scale)
                if not args.allow_external:
                    # The whole point: live embeds never settle; kill the network.
                    pg.route(re.compile(r"^https?://"), lambda r: r.abort())
                pg.goto(f"file://{html}#{n}", wait_until="domcontentloaded",
                        timeout=15000)
                pg.wait_for_timeout(args.wait)
                pg.screenshot(path=str(out), timeout=10000)
            finally:
                b.close()
    except Exception as e:
        print(f"shoot-page: failed — {type(e).__name__}: {str(e)[:200]}",
              file=sys.stderr)
        return 3
    print(f"✓ {out}  (page {n}, {time.time() - t0:.1f}s"
          f"{', external ALLOWED' if args.allow_external else ', external blocked'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
