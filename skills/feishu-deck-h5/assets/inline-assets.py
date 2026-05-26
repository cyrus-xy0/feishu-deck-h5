#!/usr/bin/env python3
"""
feishu-deck-h5  ·  inline-assets

Reads a linked HTML deck, inlines all external CSS, JS, and image assets
as base64 data URIs or embedded content, producing a single self-contained
HTML file that works offline anywhere.

Usage:
    python3 inline-assets.py <input.html> --out <output.html>

Exit codes:
    0  ok
    1  bad arguments / missing input
    2  inlining failed
"""

from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

MIME_MAP = {
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.webp': 'image/webp',
    '.ico': 'image/x-icon',
}


def find_input_dir(html_path: Path) -> Path:
    return html_path.parent


def resolve_asset(html_path: Path, ref: str) -> Path | None:
    base = find_input_dir(html_path)
    candidate = (base / ref).resolve()
    if candidate.is_file():
        return candidate
    return None


def inline_css_links(html: str, html_path: Path) -> tuple[str, int]:
    count = 0

    def replace_link(m):
        nonlocal count
        href = m.group(1)
        asset = resolve_asset(html_path, href)
        if asset is None:
            return m.group(0)
        css = asset.read_text(encoding='utf-8')
        count += 1
        return f'<style>\n{css}\n</style>'

    out = re.sub(
        r'<link\s+[^>]*rel=["\']stylesheet["\'][^>]*href=["\']([^"\']+)["\'][^>]*/?>',
        replace_link, html, flags=re.S,
    )
    return out, count


def inline_js_scripts(html: str, html_path: Path) -> tuple[str, int]:
    count = 0

    def replace_script(m):
        nonlocal count
        src = m.group(1)
        asset = resolve_asset(html_path, src)
        if asset is None:
            return m.group(0)
        js = asset.read_text(encoding='utf-8')
        count += 1
        return f'<script>\n{js}\n</script>'

    out = re.sub(
        r'<script\s+[^>]*src=["\']([^"\']+)["\'][^>]*>\s*</script>',
        replace_script, html, flags=re.S,
    )
    return out, count


def inline_css_images(html: str, html_path: Path) -> tuple[str, int]:
    count = 0
    url_re = re.compile(r'url\(["\']?([^)"\'\?]+(?:\?[^)"\'\?]+)?)["\']?\)')

    def replace_url(m):
        nonlocal count
        ref = m.group(1).split('?')[0]
        asset = resolve_asset(html_path, ref)
        if asset is None:
            return m.group(0)
        suffix = asset.suffix.lower()
        mime = MIME_MAP.get(suffix)
        if mime is None:
            return m.group(0)
        data = base64.b64encode(asset.read_bytes()).decode('ascii')
        count += 1
        return f'url("data:{mime};base64,{data}")'

    style_re = re.compile(r'<style[^>]*>(.*?)</style>', re.S)

    def replace_in_style(m):
        css = m.group(1)
        new_css = url_re.sub(replace_url, css)
        return f'<style>{new_css}</style>'

    out = style_re.sub(replace_in_style, html)
    return out, count


def inline_img_tags(html: str, html_path: Path) -> tuple[str, int]:
    count = 0

    def replace_img(m):
        nonlocal count
        src = m.group(1)
        asset = resolve_asset(html_path, src)
        if asset is None:
            return m.group(0)
        suffix = asset.suffix.lower()
        mime = MIME_MAP.get(suffix)
        if mime is None:
            return m.group(0)
        data = base64.b64encode(asset.read_bytes()).decode('ascii')
        count += 1
        return m.group(0).replace(src, f'data:{mime};base64,{data}')

    out = re.sub(
        r'<img\s+[^>]*src=["\']([^"\']+)["\']',
        replace_img, html,
    )
    return out, count


def main() -> int:
    args = sys.argv[1:]
    html_in = None
    html_out = None

    i = 0
    while i < len(args):
        if args[i] == '--out' and i + 1 < len(args):
            html_out = args[i + 1]
            i += 2
        elif args[i] in ('-h', '--help'):
            print(__doc__)
            return 0
        elif html_in is None:
            html_in = args[i]
            i += 1
        else:
            i += 1

    if not html_in:
        print(__doc__)
        return 1

    src = Path(html_in).resolve()
    if not src.is_file():
        print(f'ERROR: input not found: {src}', file=sys.stderr)
        return 1

    if not html_out:
        stem = src.stem
        html_out = str(src.with_name(f'{stem}-inline.html'))

    dst = Path(html_out).resolve()
    html = src.read_text(encoding='utf-8')

    html, n_css = inline_css_links(html, src)
    html, n_js = inline_js_scripts(html, src)
    html, n_css_img = inline_css_images(html, src)
    html, n_img = inline_img_tags(html, src)

    html = html.replace(
        '</head>',
        '<meta name="fs-deck-mode" content="inline">\n</head>',
    )

    dst.write_text(html, encoding='utf-8')
    size_kb = dst.stat().st_size / 1024
    print(f'inline-assets  ·  {src.name} → {dst.name}')
    print(f'  CSS files inlined  : {n_css}')
    print(f'  JS files inlined   : {n_js}')
    print(f'  CSS images inlined : {n_css_img}')
    print(f'  <img> inlined      : {n_img}')
    print(f'  output size        : {size_kb:.0f} KB')
    return 0


if __name__ == '__main__':
    sys.exit(main())
