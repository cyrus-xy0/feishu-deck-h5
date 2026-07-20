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
        [--allow-external] [--hide-ui] [--wait MS] [--cap S] [--scale {1,2}]

    page               1-based page number (= URL #N = frame_index)
    --out PATH         output image; PNG/JPEG inferred from extension
                       (default /tmp/shoot-p<N>.png)
    --allow-external   let http(s) through — for shooting the live embed
                       itself; expect slow + non-deterministic pixels
    --hide-ui          hide deck navigation chrome for clean cover thumbnails
    --wait MS          floor settle wait after navigation (default 2500); an
                       adaptive animation-settle waits for fs-reveal to finish on
                       top, so entrance staggers aren't captured mid-flight.
                       Raise to ~5000 for pages with several heavy local iframes.
    --cap S            hard wall-clock cap for the whole shot (default 45s)
    --scale {1,2}      device pixel ratio (2 = retina-sharp, default 1)

Exit: 0 shot written · 2 bad input · 3 navigation/screenshot failed.
"""
from __future__ import annotations

import argparse
import re
import signal
import sys
import time
from pathlib import Path

# Adaptive settle: after the floor --wait, poll until no CSS animation is still
# `running` (fs-reveal entrance staggers), capped so a looping/infinite animation
# can't stall the shot. Floors below this gave false-empty pages (content captured
# mid-reveal); this waits exactly as long as the entrance needs, no longer.
_ANIM_SETTLE_CAP_MS = 4000


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("index_html", type=Path)
    ap.add_argument("page", help="1-based page number (or '#N')")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--allow-external", action="store_true",
                    help="do NOT block http(s) — slow, non-deterministic")
    ap.add_argument("--hide-ui", action="store_true",
                    help="hide deck navigation chrome for clean cover thumbnails")
    ap.add_argument("--wait", type=int, default=2500,
                    help="floor settle wait in ms after navigation (default 2500; "
                         "an adaptive animation-settle runs on top — raise to "
                         "~5000 for pages with several heavy local iframes)")
    ap.add_argument("--cap", type=int, default=45,
                    help="hard wall-clock cap in seconds for the whole shot "
                         "(default 45); guards against a page that never settles")
    ap.add_argument("--scale", type=int, choices=(1, 2), default=1)
    ap.add_argument("--viewport", default="1920x1080",
                    help="WxH viewport (default 1920x1080 = native 16:9). Use a "
                         "NON-16:9 size (e.g. 1600x1000) to EXPOSE top/bottom "
                         "letterbox bars — the 16:9 default hides them, so a "
                         "letterbox/'黑边' bug on a raw/iframe slide is invisible "
                         "at the default. Reproduce the user's window aspect here.")
    args = ap.parse_args(argv)
    try:
        _vw, _vh = (int(x) for x in args.viewport.lower().split("x"))
        assert _vw > 0 and _vh > 0
    except (ValueError, AssertionError):
        print(f"shoot-page: bad --viewport {args.viewport!r} (expected WxH, e.g. 1600x1000)",
              file=sys.stderr)
        return 2

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

    # Hard wall-clock cap: even with per-call goto/screenshot timeouts a page can
    # stall far longer (one shot hung ~430s). SIGALRM kills the whole shot; the
    # delivery-8 inner finally + context-manager exit still tear the browser down.
    _have_alarm = hasattr(signal, "SIGALRM") and args.cap > 0

    def _on_alarm(signum, frame):
        raise TimeoutError(f"shoot-page hard cap {args.cap}s exceeded")

    if _have_alarm:
        signal.signal(signal.SIGALRM, _on_alarm)
        signal.alarm(args.cap)

    t0 = time.time()
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            # delivery-8: close the browser in finally so a navigation/screenshot
            # failure never leaks the Chromium process.
            try:
                pg = b.new_page(viewport={"width": _vw, "height": _vh},
                                device_scale_factor=args.scale)
                if not args.allow_external:
                    # The whole point: live embeds never settle; kill the network.
                    pg.route(re.compile(r"^https?://"), lambda r: r.abort())
                pg.goto(f"file://{html}#{n}", wait_until="domcontentloaded",
                        timeout=15000)
                if args.hide_ui:
                    pg.add_style_tag(content=".deck-ui{display:none!important}")
                pg.wait_for_timeout(args.wait)
                # Adaptive entrance-settle: wait until no CSS animation is still
                # running so fs-reveal staggers aren't captured mid-flight.
                # Best-effort — a looping/infinite animation or no getAnimations()
                # just falls back to the floor --wait above.
                try:
                    pg.wait_for_function(
                        "() => { const a = document.getAnimations ? "
                        "document.getAnimations() : []; "
                        "return a.every(x => x.playState !== 'running'); }",
                        timeout=_ANIM_SETTLE_CAP_MS)
                except Exception:
                    pass
                pg.screenshot(path=str(out), timeout=10000)
            finally:
                b.close()
    except Exception as e:
        print(f"shoot-page: failed — {type(e).__name__}: {str(e)[:200]}",
              file=sys.stderr)
        return 3
    finally:
        if _have_alarm:
            signal.alarm(0)
    print(f"✓ {out}  (page {n}, {time.time() - t0:.1f}s"
          f"{', external ALLOWED' if args.allow_external else ', external blocked'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
