#!/usr/bin/env python3
"""Fast single-slide preview for feishu-deck-h5.

Reads ONE slide from a deck.json, drops it into the framework shell
(`.deck > .slide-frame.is-current > .slide`), forces 1920x1080 static
(no present-mode scaling / no JS), and screenshots it 1:1 — skipping the
whole render-deck pipeline (no deck.json write, no validation, no making-of).

Use it for fast VISUAL iteration (layout / text / wrapping / color); then run
`render-deck.py <deck.json> . --scope N` once at the end to commit + validate.
Caveat: JS-driven motion, iframe-embed content, and fitText won't run here —
those need the real render.

Usage:
  preview-slide.py <deck.json> <page>            # 1-based page number
  preview-slide.py <deck.json> --key <slide_key>
  preview-slide.py <deck.json> 21 --out /tmp/p21.png
"""
import sys, os, json, argparse, time, pathlib


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("deck", help="path to deck.json")
    ap.add_argument("page", nargs="?", type=int, help="1-based page number")
    ap.add_argument("--key", help="slide key instead of page number")
    ap.add_argument("--out", default=None, help="output PNG path")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--scale", type=int, default=1, help="device_scale_factor (2 for retina detail)")
    ap.add_argument("--wait", type=int, default=500, help="ms settle before shot")
    args = ap.parse_args()

    deck_path = os.path.abspath(args.deck)
    rundir = os.path.dirname(deck_path)
    d = json.load(open(deck_path, encoding="utf-8"))
    slides = d["slides"]
    if args.key:
        matches = [i for i, s in enumerate(slides) if s.get("key") == args.key]
        if not matches:
            sys.exit(f"preview-slide: key '{args.key}' not found")
        idx = matches[0]
    elif args.page:
        idx = args.page - 1
    else:
        sys.exit("preview-slide: give a <page> number or --key")
    if not (0 <= idx < len(slides)):
        sys.exit(f"preview-slide: page out of range (1..{len(slides)})")

    s = slides[idx]
    key = s.get("key", "")
    layout = s.get("layout", "raw")
    accent = s.get("accent", "")
    label = s.get("screen_label", "")
    html = (s.get("data") or {}).get("html", "")
    css = s.get("custom_css", "") or ""
    title_style = d.get("title_style") or "left-double"

    if not html and layout != "raw":
        print(f"[warn] page {idx+1} ({key}) is layout='{layout}' with no data.html — "
              f"schema layouts render from data fields via render-deck, not previewable here.",
              file=sys.stderr)

    attrs = f'data-layout="{layout}" data-slide-key="{key}"'
    if accent:
        attrs += f' data-accent="{accent}"'
    if label:
        attrs += f' data-screen-label="{label}"'

    harness = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<link rel="stylesheet" href="assets/feishu-deck.css">
<style>
  html,body{{margin:0;padding:0;background:#000;width:{args.width}px;height:{args.height}px;overflow:hidden}}
  .deck{{position:static!important;margin:0!important;padding:0!important;width:{args.width}px;height:{args.height}px;background:#000}}
  .slide-frame{{position:static!important;transform:none!important;opacity:1!important;left:0!important;top:0!important;
    margin:0!important;width:{args.width}px;height:{args.height}px;display:block!important;visibility:visible!important}}
  .slide-frame > .slide,.slide{{transform:none!important;width:1920px!important;height:1080px!important;
    position:relative!important;left:0!important;top:0!important}}
{css}
</style></head>
<body>
<div class="deck" data-title-style="{title_style}">
  <div class="slide-frame is-current">
    <div class="slide" {attrs}>
{html}
    </div>
  </div>
</div>
</body></html>"""

    prev = os.path.join(rundir, ".__preview_slide.html")
    with open(prev, "w", encoding="utf-8") as f:
        f.write(harness)

    out = args.out or os.path.join(rundir, f".__preview_p{idx+1}.png")
    t0 = time.time()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("preview-slide: python playwright not installed")
    url = pathlib.Path(prev).as_uri()
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        pg = b.new_page(viewport={"width": args.width, "height": args.height},
                        device_scale_factor=args.scale)
        pg.goto(url)
        pg.wait_for_timeout(args.wait)
        pg.screenshot(path=out)
        b.close()
    try:
        os.remove(prev)
    except OSError:
        pass
    print(f"preview p{idx+1} ({key}) -> {out}  [{time.time()-t0:.1f}s]")


if __name__ == "__main__":
    main()
