#!/usr/bin/env python3
"""
Prepare deck HTML for Magic Page publishing without data:image payloads.

Magic Page receives one HTML document, but large image data URIs make that
document too heavy. This helper uploads local image references and
data:image/... payloads to the configured TOS uploader, then rewrites the
HTML to public URLs. CSS/JS inlining is handled separately by inline-assets.py.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html as html_lib
import mimetypes
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, unquote_to_bytes


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico"}
MIME_SUFFIXES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
}
URL_RE = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)]*))\s*\)", re.I)
IMG_SRC_RE = re.compile(r"(<img\b[^>]*?\bsrc\s*=\s*)([\"'])(.*?)\2", re.I | re.S)
DATA_IMAGE_RE = re.compile(r"^data:(image/[A-Za-z0-9.+-]+)(?:;([^,]*))?,(.*)$", re.I | re.S)


def is_external_ref(ref: str) -> bool:
    raw = ref.strip()
    return (
        not raw
        or raw.startswith(("#", "blob:", "http://", "https://", "//"))
        or raw.lower().startswith("javascript:")
    )


def strip_ref(ref: str) -> str:
    return unquote(ref.strip().split("#", 1)[0].split("?", 1)[0])


def resolve_asset(html_path: Path, ref: str) -> Path | None:
    if is_external_ref(ref) or ref.strip().startswith("data:"):
        return None
    raw = strip_ref(ref)
    if not raw:
        return None
    candidate = (html_path.parent / raw).resolve()
    if candidate.is_file() and candidate.suffix.lower() in IMAGE_SUFFIXES:
        return candidate
    return None


def safe_key_part(value: str) -> str:
    value = value.replace("\\", "/").strip("/")
    return re.sub(r"[^A-Za-z0-9._/-]+", "-", value)


def key_for(asset: Path, base_dir: Path, key_prefix: str) -> str:
    try:
        rel = asset.relative_to(base_dir).as_posix()
    except ValueError:
        rel = asset.name
    return "/".join(part for part in (safe_key_part(key_prefix), safe_key_part(rel)) if part)


def upload_file(asset: Path, *, uploader: Path, base_url: str, key: str) -> str:
    cmd = ["node", str(uploader), str(asset), "--key", key, "--base-url", base_url, "-q"]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "unknown upload failure"
        raise RuntimeError(f"upload failed for {asset}: {detail}")
    url = proc.stdout.strip()
    if not url.startswith(("http://", "https://")):
        raise RuntimeError(f"uploader returned a non-URL for {asset}: {url!r}")
    return url


def upload_asset(
    asset: Path,
    *,
    base_dir: Path,
    uploader: Path,
    base_url: str,
    key_prefix: str,
    cache: dict[Path, str],
) -> str:
    resolved = asset.resolve()
    if resolved in cache:
        return cache[resolved]
    url = upload_file(
        resolved,
        uploader=uploader,
        base_url=base_url,
        key=key_for(resolved, base_dir.resolve(), key_prefix),
    )
    cache[resolved] = url
    return url


def data_uri_payload(ref: str) -> tuple[str, bytes] | None:
    match = DATA_IMAGE_RE.match(ref.strip())
    if not match:
        return None
    mime = match.group(1).lower()
    flags = (match.group(2) or "").lower()
    payload = match.group(3)
    if "base64" in {part.strip() for part in flags.split(";") if part.strip()}:
        compact = re.sub(r"\s+", "", payload)
        try:
            return mime, base64.b64decode(compact, validate=True)
        except Exception as exc:
            raise RuntimeError(f"invalid base64 image data URI: {exc}") from exc
    return mime, unquote_to_bytes(payload)


def upload_data_uri(
    ref: str,
    *,
    uploader: Path,
    base_url: str,
    key_prefix: str,
    cache: dict[str, str],
    temp_dir: Path,
) -> str | None:
    parsed = data_uri_payload(ref)
    if parsed is None:
        return None
    if ref in cache:
        return cache[ref]
    mime, payload = parsed
    suffix = MIME_SUFFIXES.get(mime) or mimetypes.guess_extension(mime) or ".img"
    digest = hashlib.sha256(payload).hexdigest()[:16]
    tmp = temp_dir / f"data-image-{digest}{suffix}"
    tmp.write_bytes(payload)
    key = "/".join(part for part in (safe_key_part(key_prefix), f"data-uri/{digest}{suffix}") if part)
    url = upload_file(tmp, uploader=uploader, base_url=base_url, key=key)
    cache[ref] = url
    return url


def rewrite_refs(html: str, html_path: Path, *, uploader: Path, base_url: str, key_prefix: str) -> tuple[str, int, int]:
    file_cache: dict[Path, str] = {}
    data_cache: dict[str, str] = {}
    base_dir = html_path.parent

    with tempfile.TemporaryDirectory(prefix="magic-page-assets-") as tmp_name:
        temp_dir = Path(tmp_name)

        def public_url(ref: str) -> str | None:
            data_url = upload_data_uri(
                ref,
                uploader=uploader,
                base_url=base_url,
                key_prefix=key_prefix,
                cache=data_cache,
                temp_dir=temp_dir,
            )
            if data_url:
                return data_url
            asset = resolve_asset(html_path, ref)
            if asset is None:
                return None
            return upload_asset(
                asset,
                base_dir=base_dir,
                uploader=uploader,
                base_url=base_url,
                key_prefix=key_prefix,
                cache=file_cache,
            )

        def replace_url(match: re.Match[str]) -> str:
            ref = next((group for group in match.groups() if group is not None), "").strip()
            url = public_url(ref)
            if url is None:
                return match.group(0)
            return f"url('{url}')"

        def replace_img(match: re.Match[str]) -> str:
            prefix, quote, src = match.groups()
            url = public_url(src)
            if url is None:
                return match.group(0)
            return f"{prefix}{quote}{html_lib.escape(url, quote=True)}{quote}"

        html = URL_RE.sub(replace_url, html)
        html = IMG_SRC_RE.sub(replace_img, html)

    return html, len(file_cache), len(data_cache)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload deck images to TOS and rewrite Magic Page HTML refs.")
    parser.add_argument("html", help="Input HTML file")
    parser.add_argument("--out", default="", help="Output HTML file; defaults to overwriting input")
    parser.add_argument("--uploader", required=True, help="Path to the TOS upload-asset.js script")
    parser.add_argument("--base-url", default="https://magic.solutionsuite.cn", help="Magic service base URL")
    parser.add_argument("--key-prefix", required=True, help="TOS key prefix for uploaded deck assets")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    src = Path(args.html).resolve()
    dst = Path(args.out).resolve() if args.out else src
    uploader = Path(args.uploader).expanduser().resolve()

    if not src.is_file():
        print(f"ERROR: input not found: {src}", file=sys.stderr)
        return 1
    if not uploader.is_file():
        print(f"ERROR: uploader not found: {uploader}", file=sys.stderr)
        return 1

    try:
        html = src.read_text(encoding="utf-8")
        rewritten, local_uploaded, data_uploaded = rewrite_refs(
            html,
            src,
            uploader=uploader,
            base_url=args.base_url,
            key_prefix=args.key_prefix,
        )
        dst.write_text(rewritten, encoding="utf-8")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print("magic-page-assets")
    print(f"  input        : {src}")
    print(f"  output       : {dst}")
    print(f"  local images : {local_uploaded}")
    print(f"  data images  : {data_uploaded}")
    print(f"  key prefix   : {shlex.quote(args.key_prefix)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
