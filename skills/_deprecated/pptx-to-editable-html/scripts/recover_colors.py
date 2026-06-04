#!/usr/bin/env python3
"""recover_colors.py — recover real text colors for translate/edit mode.

WHY: python-pptx usually cannot resolve theme/inherited text colors, so
extract.py emits color=null for many paragraphs. Those then render white and go
invisible on light backgrounds. This script recovers the true color WITHOUT the
PPT theme: for each text box it diffs the WITH-text background image (bg) against
the NO-text image (bgNotext); the pixels that changed are the text, and their
dominant color (sampled from the clean WITH-text image) is the real text color.
Only paragraphs that are currently null or white-ish are overridden — anything
extract.py resolved confidently is left alone.

Works on a manifest produced by make_manifest.py. bg / bgNotext may be http(s)
URLs (downloaded + cached to --workdir) OR local file paths (read in place).

Usage:
  python3 recover_colors.py manifest.json
  python3 recover_colors.py manifest.json --out manifest-colored.json \
      --workdir ./work/cr --diff-threshold 45 --canvas 1920x1080

Requires: Pillow (pip install Pillow).
"""
import argparse
import concurrent.futures
import json
import os
import urllib.request

from PIL import Image, ImageChops


def is_url(s):
    return isinstance(s, str) and (s.startswith('http://') or s.startswith('https://'))


def download(url, dest):
    """Cache a remote image to dest; skip if already present and non-trivial."""
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
    """Resolve a slide image (URL or local path) to a readable local file path.
    URLs are downloaded into the cache; local paths are returned as-is."""
    if is_url(src):
        ok = download(src, dest)
        return dest if ok is True else None
    return src if (src and os.path.exists(src)) else None


def whiteish(c):
    """True for None / white text — the only colors we are allowed to override."""
    if c is None:
        return True
    return str(c).upper().lstrip('#') in ('FFFFFF', 'FFF', 'WHITE')


def recover(Wi, Ni, box, W, H, diff_threshold):
    """Return the dominant text color (#RRGGBB) inside box, or None if unreliable.

    Diff the with-text crop against the no-text crop -> the changed pixels are the
    text glyphs. Mask them, bucket colors (//12) to merge anti-aliasing, then take
    the most common surviving color from the CLEAN with-text crop.
    """
    l, t = int(box['left']), int(box['top'])
    r, b = min(W, l + int(box['width'])), min(H, t + int(box['height']))
    l, t = max(0, l), max(0, t)
    if r - l < 4 or b - t < 4:
        return None
    wc = Wi.crop((l, t, r, b))
    nc = Ni.crop((l, t, r, b))
    wb = wc.point(lambda x: (x // 12) * 12)  # bucket to merge anti-aliased edges
    mask = (ImageChops.difference(wc, nc).convert('L')
            .point(lambda x: 255 if x > diff_threshold else 0).convert('1'))
    sent = (1, 2, 3)  # sentinel color for non-text pixels (won't collide w/ real text)
    masked = Image.composite(wb, Image.new('RGB', wb.size, sent), mask)
    cols = [(c, rgb) for c, rgb in (masked.getcolors(300000) or []) if rgb != sent]
    if not cols:
        return None
    cols.sort(reverse=True)
    if sum(c for c, _ in cols) < 30:  # too few text pixels -> dominant color unreliable
        return None
    return '#%02X%02X%02X' % cols[0][1]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('manifest', help='input manifest.json (from make_manifest.py)')
    ap.add_argument('--out', default=None,
                    help='output manifest path (default: input with -colored before .json)')
    ap.add_argument('--workdir', default='./work/cr', help='image cache dir')
    ap.add_argument('--diff-threshold', type=int, default=45,
                    help='per-pixel luminance diff to count as text (default 45)')
    ap.add_argument('--canvas', default='1920x1080', help='design canvas WxH (default 1920x1080)')
    a = ap.parse_args()

    W, H = (int(x) for x in a.canvas.lower().split('x'))
    out = a.out or (a.manifest[:-5] + '-colored.json' if a.manifest.endswith('.json')
                    else a.manifest + '-colored.json')
    os.makedirs(a.workdir, exist_ok=True)

    M = json.load(open(a.manifest, encoding='utf-8'))
    slides = M['slides']

    # Resolve every bg / bgNotext to a local file (download URLs in parallel).
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

    recovered = boxes = 0
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
        for tb in s.get('texts', []):
            ps = [p for p in tb.get('paras', [])
                  if (p.get('text') or '').strip() and whiteish(p.get('color'))]
            if not ps:
                continue
            col = recover(Wi, Ni, tb, W, H, a.diff_threshold)
            if not col:
                continue
            boxes += 1
            for p in ps:
                p['color'] = col
                recovered += 1

    json.dump(M, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'recovered colors: {recovered} paras across {boxes} boxes -> {out}')


if __name__ == '__main__':
    main()
