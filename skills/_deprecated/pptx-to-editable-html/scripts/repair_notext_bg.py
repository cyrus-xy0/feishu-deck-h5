#!/usr/bin/env python3
"""repair_notext_bg.py — rebuild no-text backgrounds that lost NON-text graphics.

WHY: the text-stripped render (bgNotext) is supposed to drop only the text, but
some renderers also drop non-text graphics that happened to live in the same
shape tree — tables, embedded UI screenshots, icons. In translate/edit mode the
deck shows bgNotext, so on those pages the graphics are simply MISSING.

DETECTION (per slide): diff the WITH-text bg against the NO-text bgNotext, then
blacken/exclude every text-box rectangle and every media rectangle. Whatever
still differs is, by definition, a non-text graphic that the no-text render
dropped. If that out-of-box changed area (pixels with diff > --diff-threshold)
exceeds --area-threshold of the page, the page is FLAGGED.

REPAIR (flagged pages only): start from the WITH-text image as the base (so the
dropped graphics come back), then paste the clean NO-text crop ONLY over each
text-box rectangle (so the baked text inside those boxes stays removed/clean).
Result: out-of-box graphics restored, in-box text still gone.

PAGE-NUMBER vs SLIDE-INDEX DRIFT: when pages were dropped during build (e.g.
make_manifest --skip), the slide's position in the manifest is NOT its original
page number. The hi-res image filenames are named by the ORIGINAL page number,
so we map outputs by the page number embedded in the bg filename
(regex page-NNN / slide-NNN), never by the slide index. Repaired files are
written as page-{n:03d}.png using that recovered number, so a later upload step
lines them up with the right slide.

This script only WRITES repaired PNGs and PRINTS the flagged list — uploading and
rewriting manifest bgNotext URLs is a separate step.

Usage:
  python3 repair_notext_bg.py manifest.json
  python3 repair_notext_bg.py manifest.json --out-dir ./work/repair/out \
      --workdir ./work/repair --area-threshold 0.008 --diff-threshold 40 \
      --canvas 1920x1080

Requires: Pillow (pip install Pillow).
"""
import argparse
import concurrent.futures
import json
import os
import re
import urllib.request

from PIL import Image, ImageChops, ImageDraw

PAGENO_RE = re.compile(r'(?:page|slide)-0*(\d+)')


def is_url(s):
    return isinstance(s, str) and (s.startswith('http://') or s.startswith('https://'))


def download(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 1500:
        return True
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, 'wb') as f:
            f.write(r.read())
        return True
    except Exception as e:
        return 'ERR ' + str(e)[:80]


def local_path(src, dest):
    if is_url(src):
        ok = download(src, dest)
        return dest if ok is True else None
    return src if (src and os.path.exists(src)) else None


def page_number(s, fallback):
    """Recover the ORIGINAL page number from the bg filename, not the slide index.
    Falls back to the 1-based manifest position only if no number is embedded."""
    m = PAGENO_RE.search(s.get('bg', '') or '')
    return int(m.group(1)) if m else fallback


def rects(box, W, H):
    """Clamp a manifest box (left/top/width/height px) to a canvas rectangle."""
    l = max(0, int(box.get('left', 0)))
    t = max(0, int(box.get('top', 0)))
    r = min(W, l + int(box.get('width', 0)))
    b = min(H, t + int(box.get('height', 0)))
    return (l, t, r, b) if (r > l and b > t) else None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('manifest', help='manifest.json (from make_manifest.py)')
    ap.add_argument('--workdir', default='./work/repair', help='image cache dir')
    ap.add_argument('--out-dir', default=None, help='repaired PNG output dir (default <workdir>/out)')
    ap.add_argument('--area-threshold', type=float, default=0.008,
                    help='out-of-box changed-area fraction that flags a page (default 0.008)')
    ap.add_argument('--diff-threshold', type=int, default=40,
                    help='per-pixel luminance diff to count as changed (default 40)')
    ap.add_argument('--canvas', default='1920x1080', help='design canvas WxH (default 1920x1080)')
    a = ap.parse_args()

    W, H = (int(x) for x in a.canvas.lower().split('x'))
    out_dir = a.out_dir or os.path.join(a.workdir, 'out')
    os.makedirs(a.workdir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    page_area = W * H

    M = json.load(open(a.manifest, encoding='utf-8'))
    slides = M['slides']

    # Resolve / cache all images (download URLs in parallel).
    tasks = []
    for i, s in enumerate(slides):
        if is_url(s.get('bg')):
            tasks.append((s['bg'], os.path.join(a.workdir, f'w_{i:03d}.img')))
        if is_url(s.get('bgNotext')):
            tasks.append((s['bgNotext'], os.path.join(a.workdir, f'n_{i:03d}.img')))
    if tasks:
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
            res = list(ex.map(lambda t: download(*t), tasks))
        errs = [r for r in res if str(r).startswith('ERR')]
        print(f'downloaded {len(tasks) - len(errs)}/{len(tasks)}; errors: {errs[:3]}')

    flagged = []
    for i, s in enumerate(slides):
        wp = local_path(s.get('bg'), os.path.join(a.workdir, f'w_{i:03d}.img'))
        np_ = local_path(s.get('bgNotext'), os.path.join(a.workdir, f'n_{i:03d}.img'))
        if not (wp and np_ and os.path.exists(wp) and os.path.exists(np_)):
            continue
        Wi = Image.open(wp).convert('RGB')
        Ni = Image.open(np_).convert('RGB')
        if Wi.size != (W, H):
            Wi = Wi.resize((W, H))
        if Ni.size != (W, H):
            Ni = Ni.resize((W, H))

        text_boxes = [r for r in (rects(tb, W, H) for tb in s.get('texts', [])) if r]
        media_boxes = [r for r in (rects(mb, W, H) for mb in s.get('media', [])) if r]

        # Changed-pixel mask, then blacken every text rect + media rect so only
        # OUT-OF-BOX changes (dropped graphics) survive.
        diff = ImageChops.difference(Wi, Ni).convert('L').point(
            lambda x: 255 if x > a.diff_threshold else 0)
        dr = ImageDraw.Draw(diff)
        for (l, t, r, b) in text_boxes + media_boxes:
            dr.rectangle([l, t, r - 1, b - 1], fill=0)
        changed = sum(diff.point(lambda x: 1 if x else 0).getdata())
        frac = changed / page_area

        n = page_number(s, i + 1)
        if frac <= a.area_threshold:
            continue
        flagged.append(n)

        # Rebuild: with-text base (graphics return) + clean no-text crop pasted
        # over each text rect (text stays removed).
        rebuilt = Wi.copy()
        for (l, t, r, b) in text_boxes:
            rebuilt.paste(Ni.crop((l, t, r, b)), (l, t))
        rebuilt.save(os.path.join(out_dir, f'page-{n:03d}.png'))

    print(f'flagged {len(flagged)} pages (out-of-box change > {a.area_threshold:.3%}): '
          f'{sorted(flagged)}')
    print(f'repaired PNGs -> {out_dir} (named page-NNN.png by original page number)')


if __name__ == '__main__':
    main()
