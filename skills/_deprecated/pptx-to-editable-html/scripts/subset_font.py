#!/usr/bin/env python3
"""subset_font.py — subset a (CJK) font to ONLY the glyphs used in the deck.

A full GB18030 CJK otf is ~12 MB; subset to a deck's ~1k chars it's ~200 KB —
small enough to embed as a web font so text matches the original typeface
instead of falling back to PingFang.

  python3 subset_font.py <font.otf> <texts.json> <out.woff2> [--extra "0123…"]

Requires: fonttools, brotli  (pip install fonttools brotli)
Run once per weight you need (e.g. Regular and Bold).
"""
import argparse
import json
import subprocess
import sys


def charset_from_texts(path):
    d = json.load(open(path, encoding='utf-8'))
    chars = set()
    for frames in d.values():
        for fr in frames:
            for p in fr.get('paras', []):
                chars.update(p.get('text', '') or '')
    chars.discard('\n')
    chars.discard('\x0b')
    return chars


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('font')
    ap.add_argument('texts')
    ap.add_argument('out')
    ap.add_argument('--extra', default='0123456789%+-—·，。：；、（）《》""' "'")
    a = ap.parse_args()
    chars = charset_from_texts(a.texts) | set(a.extra)
    text = ''.join(sorted(chars))
    tmp = a.out + '.chars.txt'
    open(tmp, 'w', encoding='utf-8').write(text)
    cmd = [sys.executable, '-m', 'fontTools.subset', a.font,
           f'--text-file={tmp}', '--flavor=woff2', f'--output-file={a.out}',
           '--layout-features=*', '--no-hinting']
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr[-500:], file=sys.stderr)
        sys.exit(1)
    import os
    print(f'{a.out}: {os.path.getsize(a.out)//1024} KB ({len(chars)} glyphs)')


if __name__ == '__main__':
    main()
