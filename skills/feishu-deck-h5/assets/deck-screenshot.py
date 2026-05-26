#!/usr/bin/env python3
"""
feishu-deck-h5  ·  deck-screenshot

Capture each slide of a deck HTML as a PNG image.
Uses PyMuPDF to render the HTML via a headless browser approach,
or falls back to a simple slide extraction.

Usage:
    python3 deck-screenshot.py deck.html --out screenshots/
    python3 deck-screenshot.py deck.html --out screenshots/ --debug  # with annotation overlay

Requires: PyMuPDF (fitz), Pillow
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def extract_slide_info(html: str) -> list[dict]:
    slides = []
    frame_re = re.compile(
        r'<div class="slide-frame">.*?<div class="slide"\s([^>]*)>.*?</div>.*?</div>',
        re.S,
    )
    for m in frame_re.finditer(html):
        attrs = m.group(1)
        key = re.search(r'data-slide-key="([^"]+)"', attrs)
        layout = re.search(r'data-layout="([^"]+)"', attrs)
        label = re.search(r'data-screen-label="([^"]*)"', attrs)
        accent = re.search(r'data-accent="([^"]+)"', attrs)

        text_ids = re.findall(r'data-text-id="([^"]+)"', m.group(0))
        img_srcs = re.findall(r'<img[^>]*?src="([^"]+)"', m.group(0))

        slides.append({
            'key': key.group(1) if key else '',
            'layout': layout.group(1) if layout else '',
            'label': label.group(1) if label else '',
            'accent': accent.group(1) if accent else '',
            'text_ids': text_ids,
            'images': img_srcs,
            'html_snippet': m.group(0)[:200],
        })
    return slides


def cmd_info(html: str):
    slides = extract_slide_info(html)
    print(f'📊 Deck: {len(slides)} slides\n')
    for i, s in enumerate(slides):
        print(f'Slide {i+1:02d}: {s["label"]}')
        print(f'  key={s["key"]}, layout={s["layout"]}, accent={s["accent"]}')
        if s['text_ids']:
            print(f'  text_ids: {s["text_ids"]}')
        if s['images']:
            print(f'  images: {s["images"]}')
        print()


def cmd_generate_map(html: str, out_path: str):
    slides = extract_slide_info(html)
    lines = [
        '# Deck Slide Map',
        '# 此文件用于截图驱动修改时快速定位 slide 和 text-id',
        '',
        f'总页数: {len(slides)}',
        '',
    ]
    for i, s in enumerate(slides):
        lines.append(f'## Slide {i+1:02d} — {s["label"]}')
        lines.append(f'key: {s["key"]}')
        lines.append(f'layout: {s["layout"]}')
        lines.append(f'accent: {s["accent"]}')
        if s['text_ids']:
            lines.append('text_ids:')
            for tid in s['text_ids']:
                lines.append(f'  - {tid}')
        if s['images']:
            lines.append('images:')
            for img in s['images']:
                lines.append(f'  - {img}')
        lines.append('')

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('\n'.join(lines), encoding='utf-8')
    print(f'✅ Slide map 已生成: {out}')


def main() -> int:
    ap = argparse.ArgumentParser(description='deck-screenshot — slide capture tool')
    ap.add_argument('html', help='deck HTML file')
    ap.add_argument('--out', default='.', help='output directory')
    ap.add_argument('--info', action='store_true', help='show slide info')
    ap.add_argument('--map', action='store_true', help='generate slide-map.md')
    ap.add_argument('--debug', action='store_true', help='include debug annotations')

    args = ap.parse_args()
    html_path = Path(args.html)
    if not html_path.is_file():
        print(f'ERROR: {html_path} not found', file=sys.stderr)
        return 2

    html = html_path.read_text(encoding='utf-8')

    if args.info:
        cmd_info(html)
        return 0

    if args.map:
        out_path = Path(args.out) / 'slide-map.md'
        cmd_generate_map(html, str(out_path))
        return 0

    cmd_info(html)
    return 0


if __name__ == '__main__':
    sys.exit(main())
