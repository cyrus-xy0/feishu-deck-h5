#!/usr/bin/env python3
"""shoot.py — present-mode screenshots of specific deck pages.  (ticket C / F-321)

The fast path for "render these pages and let me LOOK at them" — the exact thing
an agent otherwise hand-rolls a one-off Playwright script for on EVERY visual
iteration, tripping over the same gotchas each time:

  · `networkidle` never settles on a page with an embedded live demo (iframe) →
    the goto times out.  (We use `domcontentloaded` + a bounded `load` wait.)
  · jumping to a frame by toggling `is-current` fights the framework's own
    current-index state and lands on the wrong / a half-faded frame.  (We drive
    the framework's OWN keyboard nav so currentIdx + pager + is-current + the
    entrance reveal all stay consistent — then wait for the reveal to settle.)
  · a letterbox-seam check needs a viewport whose ratio differs from the deck +
    a FULL-viewport shot, not the design-canvas clip. (`--aspect` handles it.)

    shoot.py <index.html | run-dir> [--pages 19,20|cover,zengzhang]
             [--out DIR] [--aspect 16:10]

--pages : comma list of 1-based frame indices AND/OR slide keys. Default: all.
--out   : dir for the PNGs. Default: <dir-of-index>/_shoots.
--aspect: viewport aspect ratio (W:H or W/H).
          omitted → deck canvas, clipped to the design box (no letterbox).
          anything else (e.g. 16:10) → design-width×round(width·H/W) viewport, FULL-viewport
          shot so the present-mode letterbox bands are visible — the lens for
          verifying the F-318 letterbox seam at fullscreen aspect ratios.

Exit: 0 if every requested page was shot; 2 on bad input / engine missing; 3 if
some requested pages were not found.
"""
import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_DESIGN_W, DEFAULT_DESIGN_H = 1920, 1080

# (idx 1-based, key) for every .slide-frame, in render order.
_META_JS = r"""
() => [...document.querySelectorAll('.slide-frame')].map((f, i) => {
  const s = f.querySelector('.slide');
  return { idx: i + 1,
           key: (s && (s.getAttribute('data-slide-key') || s.id)) || ('slide-' + (i + 1)) };
})
"""

# DOM index (0-based) of the framework's current frame. -1 if none yet.
_CUR_JS = r"""
() => [...document.querySelectorAll('.slide-frame')].findIndex(f => f.classList.contains('is-current'))
"""


def _parse_aspect(s: str):
    """'16:10' / '16/10' / '1.6' → (w_ratio, h_ratio). None on parse fail."""
    s = s.strip().replace("/", ":")
    try:
        if ":" in s:
            w, h = s.split(":", 1)
            return float(w), float(h)
        return float(s), 1.0
    except Exception:
        return None


def _resolve_index(target: str) -> Path | None:
    p = Path(target).expanduser()
    if p.is_dir():
        cand = p / "index.html"
        return cand if cand.is_file() else None
    return p if p.is_file() else None


def _read_canvas(index: Path) -> tuple[int, int]:
    """Read portable root attributes first, then sibling deck.json, then legacy."""
    try:
        raw = index.read_text(encoding="utf-8", errors="replace")
    except OSError:
        raw = ""
    mw = re.search(r"\bdata-deck-width\s*=\s*['\"]([0-9]+)['\"]", raw, re.I)
    mh = re.search(r"\bdata-deck-height\s*=\s*['\"]([0-9]+)['\"]", raw, re.I)
    if mw and mh and int(mw.group(1)) > 0 and int(mh.group(1)) > 0:
        return int(mw.group(1)), int(mh.group(1))
    sidecar = index.parent / "deck.json"
    try:
        canvas = (json.loads(sidecar.read_text(encoding="utf-8")).get("deck") or {}).get("canvas") or {}
        width, height = int(canvas.get("width")), int(canvas.get("height"))
        if width > 0 and height > 0:
            return width, height
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return DEFAULT_DESIGN_W, DEFAULT_DESIGN_H


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Present-mode screenshots of specific deck pages (ticket C).")
    ap.add_argument("target", help="index.html path OR a run/output dir holding index.html")
    ap.add_argument("--pages", default=None,
                    help="comma list of 1-based frame indices and/or slide keys "
                         "(e.g. '19,20' or 'cover,zengzhang'). Default: all pages.")
    ap.add_argument("--out", default=None,
                    help="output dir for PNGs (default: <index-dir>/_shoots).")
    ap.add_argument("--aspect", default=None,
                    help="viewport aspect W:H. Omit for the deck's design clip; "
                         "a different ratio (16:10, 21:9) captures letterboxing.")
    ap.add_argument("--allow-external", action="store_true",
                    help="let http(s) through (for shooting a live external embed). "
                         "Default BLOCKS external requests so remote webfonts fail "
                         "fast and the screenshot doesn't stall on document.fonts.ready.")
    args = ap.parse_args(argv)

    index = _resolve_index(args.target)
    if index is None:
        print(f"✗ no index.html at {args.target!r} (give the file or its run/output dir)",
              file=sys.stderr)
        return 2

    design_w, design_h = _read_canvas(index)
    ratio = _parse_aspect(args.aspect) if args.aspect else (design_w, design_h)
    if ratio is None:
        print(f"✗ bad --aspect {args.aspect!r} (use W:H, e.g. 16:10)", file=sys.stderr)
        return 2
    w_r, h_r = ratio
    vp_h = round(design_w * h_r / w_r)
    design_mode = abs(vp_h - design_h) <= 1
    if design_mode:
        vp_h = design_h

    out_dir = Path(args.out).expanduser() if args.out else index.parent / "_shoots"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("✗ playwright not installed. `pip install playwright && "
              "python -m playwright install chromium`", file=sys.stderr)
        return 2

    written, missing = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": design_w, "height": vp_h},
                                  device_scale_factor=1)
        page = ctx.new_page()
        # Block external http(s) by default: a live embed / remote webfont never
        # settles, and page.screenshot() then stalls ~30s on "waiting for fonts to
        # load…" before timing out (the exact trap shoot-page.py already avoids).
        # Aborting external requests makes document.fonts.ready resolve immediately;
        # local file:// assets still load. --allow-external opts back in for the
        # rare case of shooting the live external embed itself.
        if not args.allow_external:
            page.route(re.compile(r"^https?://"), lambda r: r.abort())
        # ?mode=present → the framework inits straight into present mode (its own
        # currentIdx/pager/is-current state is internally consistent from the
        # start — the basis for driving it by keyboard below).
        page.goto(index.resolve().as_uri() + "?mode=present",
                  wait_until="domcontentloaded", timeout=60_000)
        # Bounded settle: an embedded live demo keeps 'load' pending ~30s — cap it
        # (same pixels), then await fonts so CJK doesn't shoot in a fallback face,
        # then wait for the framework to finish init (data-js-ready on .deck).
        for fn in (lambda: page.wait_for_load_state("load", timeout=4_000),
                   lambda: page.evaluate("() => Promise.race([(document.fonts && "
                        "document.fonts.ready) || Promise.resolve(), "
                        "new Promise(r => setTimeout(r, 2000))])"),
                   lambda: page.wait_for_function(
                        "() => document.querySelector('.deck[data-js-ready]')", timeout=5_000)):
            try:
                fn()
            except Exception:
                pass
        page.wait_for_timeout(300)

        # Restart-on-enter (feishu-deck.js restartFrameMotion) replays a slide's
        # CSS animations and reloads its embedded iframes every time we navigate to
        # it. A screenshot wants the SETTLED end state (see the 650ms wait below),
        # not a mid-replay frame — and we don't want every ArrowRight step reloading
        # the iframes it passes. Opt all frames out for the shoot only; the live
        # deck is unaffected. (Honoured via closest('[data-no-restart]').)
        page.evaluate("() => document.querySelectorAll('.slide-frame')"
                      ".forEach(f => f.setAttribute('data-no-restart',''))")

        meta = page.evaluate(_META_JS)
        by_idx = {m["idx"]: m for m in meta}
        by_key = {m["key"]: m for m in meta}

        # Resolve --pages → target frames, sorted ASCENDING (we walk forward with
        # ArrowRight, so order of capture is by frame position regardless of how
        # the user listed them).
        if args.pages:
            want, seen = [], set()
            for tok in (t.strip() for t in args.pages.split(",") if t.strip()):
                m = by_idx.get(int(tok)) if tok.isdigit() else by_key.get(tok)
                if m is None:
                    missing.append(tok)
                elif m["idx"] not in seen:
                    seen.add(m["idx"])
                    want.append(m)
        else:
            want = list(meta)
        want.sort(key=lambda m: m["idx"])

        # Drive the framework's own keyboard nav. ArrowRight advances by VISIBLE
        # frame, so reading is-current after each press naturally steps over hidden
        # frames; we stop when current reaches the target's DOM index.
        page.evaluate("() => document.body && document.body.focus()")
        for m in want:
            target0 = m["idx"] - 1
            guard = 0
            while page.evaluate(_CUR_JS) < target0 and guard < len(meta) + 3:
                page.keyboard.press("ArrowRight")
                page.wait_for_timeout(110)
                guard += 1
            # delivery-5: if nav couldn't LAND on the target (a hidden/conditional
            # frame ArrowRight steps over, or the guard exhausted), do NOT shoot the
            # current (wrong) frame and mislabel it p{target}-{key}.png. Treat it as
            # not-found so the operator's visual self-review isn't misled.
            if page.evaluate(_CUR_JS) != target0:
                print(f"⚠ could not reach page {m['idx']} ({m['key']}) — "
                      f"skipped (frame hidden/unreachable)", file=sys.stderr)
                missing.append(str(m["idx"]))
                continue
            # Let the cross-fade + the staggered entrance reveal (~0.28s + stagger)
            # fully settle so the shot is the end state, not a mid-animation frame.
            page.wait_for_timeout(650)
            fn = out_dir / f"p{m['idx']:02d}-{m['key']}.png"
            if design_mode:
                page.screenshot(path=str(fn), timeout=15_000,
                                clip={"x": 0, "y": 0,
                                      "width": design_w, "height": design_h})
            else:
                page.screenshot(path=str(fn), timeout=15_000)   # full viewport → letterbox visible
            written.append((m, fn))
        browser.close()

    mode = (f"design {design_w}×{design_h}" if design_mode
            else f"letterbox {design_w}×{vp_h} (deck {design_w}×{design_h})")
    for m, fn in written:
        print(f"  p{m['idx']:>2} {m['key']:<22} → {fn}")
    print(f"📸 {len(written)} shot(s) · {mode} · {out_dir}", file=sys.stderr)
    if missing:
        print(f"⚠ not found (skipped): {', '.join(missing)}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
