#!/usr/bin/env python3
"""
Explode a self-contained deck HTML back into a linked-assets directory.

Inverse of inline-assets.py. Extracts every `data:` image URI (in CSS `url()`,
inline `style=`, `<img src>`, custom properties — any context) into a single
file under `<out>/assets/`, **deduplicated by content hash**, and rewrites every
reference to a relative path. Identical bytes used in N places (incl. the same
screenshot used as both a CSS background AND an <img>) collapse to ONE file.

Why: a self-contained single file is right for "download / portability", but for
HOSTING (飞书妙搭 / Miaoda, any static host) it is the wrong shape — a 7.5 MB
file is uploaded + built whole on every publish, base64 inflates bytes ~33 %, and
cross-context image duplicates cannot be deduped inside one static file. A
directory keeps index.html tiny, stores each image once, and lets the browser
cache them.

Usage:
    explode-assets.py deck.html --out ./dist        # -> ./dist/index.html + ./dist/assets/
    explode-assets.py deck.html --out ./dist --min-bytes 1024
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
import sys
from pathlib import Path
from urllib.parse import unquote_to_bytes

# data: URI token — terminates at the first quote, paren or whitespace. Safe for
# base64 (alphabet has none of those) and for url-encoded payloads (literal
# quotes/parens always close the surrounding url()/attr).
DATA_URI_RE = re.compile(r"data:[^\"')\s]+")

EXT_MAP = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
}


def decode_data_uri(uri: str) -> tuple[bytes, str] | None:
    """Return (raw_bytes, mime) for a data: URI, or None if unparseable."""
    if not uri.startswith("data:"):
        return None
    header, _, payload = uri[5:].partition(",")
    if not _:
        return None
    is_b64 = header.endswith(";base64")
    mime = header[:-7] if is_b64 else header.split(";", 1)[0]
    try:
        if is_b64:
            raw = base64.b64decode(payload)
        else:
            raw = unquote_to_bytes(payload)
    except Exception:
        return None
    return raw, (mime or "application/octet-stream")


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Explode a self-contained deck into index.html + assets/.")
    p.add_argument("html", help="Input self-contained HTML file")
    p.add_argument("--out", required=True, help="Output directory (gets index.html + assets/)")
    p.add_argument("--assets-dir", default="assets", help="Asset subfolder name (default: assets)")
    p.add_argument("--min-bytes", type=int, default=512,
                   help="Leave data URIs smaller than this inline (avoid many tiny files); default 512")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    src = Path(args.html).resolve()
    if not src.is_file():
        print(f"ERROR: input not found: {src}", file=sys.stderr)
        return 1

    out_dir = Path(args.out).resolve()
    assets_dir = out_dir / args.assets_dir
    html = src.read_text(encoding="utf-8")
    in_bytes = len(html.encode("utf-8"))

    # Unique data URIs, longest first so a shorter URI that is a prefix of a
    # longer one never partially-replaces it.
    uris = sorted(set(DATA_URI_RE.findall(html)), key=len, reverse=True)

    hash_to_name: dict[str, str] = {}   # content hash -> filename (dedup)
    uri_to_path: dict[str, str] = {}    # full uri -> relative ref
    written = 0
    skipped_small = 0
    occurrences = 0

    for uri in uris:
        dec = decode_data_uri(uri)
        if dec is None:
            continue
        raw, mime = dec
        if len(raw) < args.min_bytes:
            skipped_small += 1
            continue
        digest = hashlib.sha256(raw).hexdigest()[:12]
        name = hash_to_name.get(digest)
        if name is None:
            ext = EXT_MAP.get(mime, ".bin")
            name = f"{digest}{ext}"
            hash_to_name[digest] = name
            assets_dir.mkdir(parents=True, exist_ok=True)
            (assets_dir / name).write_bytes(raw)
            written += 1
        uri_to_path[uri] = f"{args.assets_dir}/{name}"

    for uri, ref in uri_to_path.items():
        n = html.count(uri)
        occurrences += n
        html = html.replace(uri, ref)

    # mark mode as linked (was 'inline')
    html = html.replace('<meta name="fs-deck-mode" content="inline">',
                        '<meta name="fs-deck-mode" content="linked">')

    out_dir.mkdir(parents=True, exist_ok=True)
    index = out_dir / "index.html"
    index.write_text(html, encoding="utf-8")

    html_kb = index.stat().st_size / 1024
    assets_bytes = sum(f.stat().st_size for f in assets_dir.glob("*")) if assets_dir.exists() else 0
    print(f"explode-assets  ·  {src.name} -> {out_dir}/")
    print(f"  unique images written : {written}  (in {args.assets_dir}/)")
    print(f"  references rewritten   : {occurrences}  ({len(uri_to_path)} distinct URIs)")
    print(f"  tiny URIs left inline  : {skipped_small}  (< {args.min_bytes} B)")
    print(f"  index.html             : {html_kb:.0f} KB   (was {in_bytes/1024:.0f} KB self-contained)")
    print(f"  assets total           : {assets_bytes/1024/1024:.2f} MB")
    print(f"  directory total        : {(index.stat().st_size + assets_bytes)/1024/1024:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
