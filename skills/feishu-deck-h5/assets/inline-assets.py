#!/usr/bin/env python3
"""
Inline linked deck CSS/JS, optionally leaving image references as URLs.

Default mode creates a self-contained HTML file with image data URIs. For Magic
Page publishing, pass --no-image-inline after magic-page-assets.py has uploaded
images to TOS; this keeps the HTML small and prevents base64 image payloads.
"""

from __future__ import annotations

import argparse
import base64
import html as html_lib
import re
import sys
from pathlib import Path
from urllib.parse import unquote


MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}
ATTR_RE = re.compile(r"([:\w-]+)\s*=\s*([\"'])(.*?)\2", re.S)
URL_RE = re.compile(r"url\(\s*([\"']?)([^)\"']+)\1\s*\)")


def is_external_ref(ref: str) -> bool:
    ref = ref.strip()
    return (
        not ref
        or ref.startswith(("#", "data:", "blob:", "http://", "https://", "//"))
        or ref.lower().startswith("javascript:")
    )


def strip_ref(ref: str) -> str:
    return unquote(ref.strip().split("#", 1)[0].split("?", 1)[0])


def resolve_asset(base_path: Path, ref: str) -> Path | None:
    if is_external_ref(ref):
        return None
    raw = strip_ref(ref)
    if not raw:
        return None
    candidate = (base_path.parent / raw).resolve()
    if candidate.is_file():
        return candidate
    return None


def data_uri(asset: Path) -> str | None:
    mime = MIME_MAP.get(asset.suffix.lower())
    if mime is None:
        return None
    data = base64.b64encode(asset.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def attr_value(tag: str, name: str) -> str | None:
    for attr, _quote, value in ATTR_RE.findall(tag):
        if attr.lower() == name.lower():
            return value
    return None


def attr_escape(value: str) -> str:
    return html_lib.escape(value, quote=True)


def inline_css_urls(css: str, css_path: Path, *, inline_images: bool) -> tuple[str, int]:
    if not inline_images:
        return css, 0
    count = 0

    def replace_url(match: re.Match[str]) -> str:
        nonlocal count
        ref = match.group(2)
        asset = resolve_asset(css_path, ref)
        if asset is None:
            return match.group(0)
        uri = data_uri(asset)
        if uri is None:
            return match.group(0)
        count += 1
        return f"url('{uri}')"

    return URL_RE.sub(replace_url, css), count


def inline_css_links(html: str, html_path: Path, *, inline_images: bool) -> tuple[str, int, int]:
    count = 0
    image_count = 0

    def replace_link(match: re.Match[str]) -> str:
        nonlocal count, image_count
        tag = match.group(0)
        rel = (attr_value(tag, "rel") or "").lower()
        href = attr_value(tag, "href")
        if "stylesheet" not in rel or not href:
            return tag
        asset = resolve_asset(html_path, href)
        if asset is None:
            return tag
        css = asset.read_text(encoding="utf-8")
        css, n_images = inline_css_urls(css, asset, inline_images=inline_images)
        count += 1
        image_count += n_images
        return (
            f'<style data-source="framework" data-inlined-from="{attr_escape(href)}">\n'
            f"{css}\n"
            "</style>"
        )

    return re.sub(r"<link\b[^>]*?>", replace_link, html, flags=re.S | re.I), count, image_count


def inline_js_scripts(html: str, html_path: Path) -> tuple[str, int]:
    count = 0

    def replace_script(match: re.Match[str]) -> str:
        nonlocal count
        tag = match.group(1)
        src = attr_value(tag, "src")
        if not src:
            return match.group(0)
        asset = resolve_asset(html_path, src)
        if asset is None:
            return match.group(0)
        js = asset.read_text(encoding="utf-8")
        count += 1
        return (
            f'<script data-source="framework" data-inlined-from="{attr_escape(src)}">\n'
            f"{js}\n"
            "</script>"
        )

    out = re.sub(
        r"(<script\b[^>]*src=[\"'][^\"']+[\"'][^>]*>)\s*</script>",
        replace_script,
        html,
        flags=re.S | re.I,
    )
    return out, count


def inline_css_images(html: str, html_path: Path, *, inline_images: bool) -> tuple[str, int]:
    count = 0
    style_re = re.compile(r"(<style\b[^>]*>)(.*?)</style>", re.S | re.I)

    def replace_in_style(match: re.Match[str]) -> str:
        nonlocal count
        css, n_images = inline_css_urls(match.group(2), html_path, inline_images=inline_images)
        count += n_images
        return f"{match.group(1)}{css}</style>"

    return style_re.sub(replace_in_style, html), count


def inline_img_tags(html: str, html_path: Path, *, inline_images: bool) -> tuple[str, int]:
    if not inline_images:
        return html, 0
    count = 0

    def replace_img(match: re.Match[str]) -> str:
        nonlocal count
        src = match.group(1)
        asset = resolve_asset(html_path, src)
        if asset is None:
            return match.group(0)
        uri = data_uri(asset)
        if uri is None:
            return match.group(0)
        count += 1
        return match.group(0).replace(src, uri)

    return re.sub(r"<img\s+[^>]*src=[\"']([^\"']+)[\"']", replace_img, html, flags=re.S | re.I), count


def inline_html_style_urls(html: str, html_path: Path, *, inline_images: bool) -> tuple[str, int]:
    if not inline_images:
        return html, 0
    count = 0

    def replace_url(match: re.Match[str]) -> str:
        nonlocal count
        ref = match.group(2)
        asset = resolve_asset(html_path, ref)
        if asset is None:
            return match.group(0)
        uri = data_uri(asset)
        if uri is None:
            return match.group(0)
        count += 1
        return f"url('{uri}')"

    return URL_RE.sub(replace_url, html), count


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inline linked CSS/JS/assets into a deck HTML file.")
    parser.add_argument("html", help="Input HTML file")
    parser.add_argument("--out", default="", help="Output HTML file; defaults to <stem>-inline.html")
    parser.add_argument("--no-image-inline", action="store_true", help="do not convert images to base64 data URIs")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    src = Path(args.html).resolve()
    if not src.is_file():
        print(f"ERROR: input not found: {src}", file=sys.stderr)
        return 1

    dst = Path(args.out).resolve() if args.out else src.with_name(f"{src.stem}-inline.html")
    inline_images = not args.no_image_inline
    html = src.read_text(encoding="utf-8")

    html, n_css, n_link_css_img = inline_css_links(html, src, inline_images=inline_images)
    html, n_js = inline_js_scripts(html, src)
    html, n_css_img = inline_css_images(html, src, inline_images=inline_images)
    html, n_img = inline_img_tags(html, src, inline_images=inline_images)
    html, n_style_img = inline_html_style_urls(html, src, inline_images=inline_images)

    if inline_images and '<meta name="fs-deck-mode"' not in html:
        html = html.replace("</head>", '<meta name="fs-deck-mode" content="inline">\n</head>', 1)

    dst.write_text(html, encoding="utf-8")
    size_kb = dst.stat().st_size / 1024
    print(f"inline-assets  ·  {src.name} -> {dst.name}")
    print(f"  CSS files inlined  : {n_css}")
    print(f"  JS files inlined   : {n_js}")
    print(f"  CSS images inlined : {n_css_img + n_link_css_img}")
    print(f"  <img> inlined      : {n_img}")
    print(f"  style url() inlined: {n_style_img}")
    print(f"  image mode         : {'linked' if args.no_image_inline else 'base64'}")
    print(f"  output size        : {size_kb:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
