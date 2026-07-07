#!/usr/bin/env python3
"""Download remote image references into a deck output folder.

Library/remote delivery packages must be durable. A browser can render a
temporary signed http(s) background image today, then the material library loses
it tomorrow when the URL expires. This helper left-shifts that failure: remote
images are downloaded into output/assets/remote/ and HTML/CSS references are
rewritten before deck.zip is built.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import mimetypes
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen


NETWORK_TIMEOUT_SECONDS = 60
MAX_REMOTE_IMAGE_BYTES = 64 * 1024 * 1024
IMAGE_SUFFIXES = {".apng", ".avif", ".gif", ".jpg", ".jpeg", ".png", ".svg", ".webp"}
IMAGE_MIME_SUFFIXES = {
    "image/apng": ".apng",
    "image/avif": ".avif",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}
URL_RE = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)]*))\s*\)", re.I)
IMAGE_ATTR_RE = re.compile(
    r"(<(?P<tag>img|image)\b[^>]*?\b(?P<attr>src|href|xlink:href)\s*=\s*)([\"'])(.*?)\4",
    re.I | re.S,
)
POSTER_ATTR_RE = re.compile(r"(<(?P<tag>video)\b[^>]*?\bposter\s*=\s*)([\"'])(.*?)\3", re.I | re.S)
SRCSET_ATTR_RE = re.compile(r"(<(?P<tag>img|source)\b[^>]*?\bsrcset\s*=\s*)([\"'])(.*?)\3", re.I | re.S)


@dataclass(frozen=True)
class DownloadedImage:
    url: str
    relative_path: str
    path: Path
    content_type: str
    size: int


def is_http_ref(ref: str) -> bool:
    raw = ref.strip()
    return raw.startswith(("http://", "https://", "//"))


def normalize_http_ref(ref: str) -> str:
    raw = html.unescape(ref.strip().strip("\"'"))
    if raw.startswith("//"):
        return "https:" + raw
    return raw


def safe_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "")).strip(".-")[:96]


def suffix_from_url_or_type(url: str, content_type: str) -> str:
    path_suffix = Path(unquote(urlparse(url).path or "")).suffix.lower()
    if path_suffix in IMAGE_SUFFIXES:
        return ".jpg" if path_suffix == ".jpeg" else path_suffix
    mime = content_type.split(";", 1)[0].strip().lower()
    suffix = IMAGE_MIME_SUFFIXES.get(mime) or mimetypes.guess_extension(mime) or ".img"
    return ".jpg" if suffix in {".jpe", ".jpeg"} else suffix


def looks_like_css_image_url(ref: str) -> bool:
    url = normalize_http_ref(ref)
    suffix = Path(unquote(urlparse(url).path or "")).suffix.lower()
    return suffix in IMAGE_SUFFIXES


def response_content_type(response: object) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    getter = getattr(headers, "get_content_type", None)
    if callable(getter):
        return str(getter() or "")
    getter = getattr(headers, "get", None)
    if callable(getter):
        return str(getter("Content-Type", "") or "")
    return ""


def remote_asset_path(url: str, digest: str, suffix: str) -> str:
    parsed = urlparse(url)
    host = safe_segment(parsed.netloc) or "remote"
    stem = safe_segment(Path(unquote(parsed.path or "")).stem) or "image"
    return f"assets/remote/{host}/{stem}-{digest[:16]}{suffix}"


def download_image(url: str, *, output_dir: Path, cache: dict[str, DownloadedImage]) -> DownloadedImage:
    if url in cache:
        return cache[url]
    request = Request(url, headers={"User-Agent": "feishu-deck-h5-packager/1.0"})
    try:
        with urlopen(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
            status = int(getattr(response, "status", 200) or 200)
            if status >= 400:
                raise RuntimeError(f"HTTP {status}")
            content_type = response_content_type(response).split(";", 1)[0].strip().lower()
            if not content_type.startswith("image/"):
                raise RuntimeError(f"not an image ({content_type or 'unknown content-type'})")
            declared = response.headers.get("content-length") if getattr(response, "headers", None) else None
            if declared and declared.isdigit() and int(declared) > MAX_REMOTE_IMAGE_BYTES:
                raise RuntimeError(f"image too large ({declared} bytes)")
            digest = hashlib.sha256()
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_REMOTE_IMAGE_BYTES:
                    raise RuntimeError(f"image exceeds {MAX_REMOTE_IMAGE_BYTES} bytes")
                digest.update(chunk)
                chunks.append(chunk)
    except HTTPError as exc:
        raise RuntimeError(f"remote image download failed: HTTP {exc.code} {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"remote image download failed: {exc.reason} {url}") from exc
    except RuntimeError as exc:
        raise RuntimeError(f"remote image download failed: {exc} {url}") from exc
    if size <= 0:
        raise RuntimeError(f"remote image download failed: empty body {url}")
    digest_hex = digest.hexdigest()
    rel = remote_asset_path(url, digest_hex, suffix_from_url_or_type(url, content_type))
    target = output_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.stat().st_size != size:
        target.write_bytes(b"".join(chunks))
    item = DownloadedImage(url=url, relative_path=rel, path=target, content_type=content_type, size=size)
    cache[url] = item
    return item


def rewrite_srcset(value: str, *, output_dir: Path, cache: dict[str, DownloadedImage]) -> tuple[str, list[DownloadedImage]]:
    changed = False
    downloads: list[DownloadedImage] = []
    pieces: list[str] = []
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        bits = item.split()
        ref = bits[0]
        if is_http_ref(ref):
            downloaded = download_image(normalize_http_ref(ref), output_dir=output_dir, cache=cache)
            bits[0] = downloaded.relative_path
            downloads.append(downloaded)
            changed = True
        pieces.append(" ".join(bits))
    return (", ".join(pieces) if changed else value), downloads


def rewrite_html_text(text: str, *, output_dir: Path, cache: dict[str, DownloadedImage]) -> tuple[str, list[DownloadedImage]]:
    downloads: list[DownloadedImage] = []

    def replace_css_url(match: re.Match[str]) -> str:
        raw = next((group for group in match.groups() if group is not None), "").strip()
        if not raw or not is_http_ref(raw) or not looks_like_css_image_url(raw):
            return match.group(0)
        downloaded = download_image(normalize_http_ref(raw), output_dir=output_dir, cache=cache)
        downloads.append(downloaded)
        return match.group(0).replace(raw, downloaded.relative_path)

    def replace_attr(match: re.Match[str]) -> str:
        raw = match.group(5 if match.re is IMAGE_ATTR_RE else 4)
        if not raw or not is_http_ref(raw):
            return match.group(0)
        downloaded = download_image(normalize_http_ref(raw), output_dir=output_dir, cache=cache)
        downloads.append(downloaded)
        return match.group(0).replace(raw, downloaded.relative_path)

    def replace_srcset(match: re.Match[str]) -> str:
        value = match.group(4)
        rewritten, new_downloads = rewrite_srcset(value, output_dir=output_dir, cache=cache)
        downloads.extend(new_downloads)
        return match.group(0).replace(value, rewritten)

    new_text = URL_RE.sub(replace_css_url, text)
    new_text = IMAGE_ATTR_RE.sub(replace_attr, new_text)
    new_text = POSTER_ATTR_RE.sub(replace_attr, new_text)
    new_text = SRCSET_ATTR_RE.sub(replace_srcset, new_text)
    return new_text, downloads


def rewrite_css_text(text: str, *, output_dir: Path, cache: dict[str, DownloadedImage]) -> tuple[str, list[DownloadedImage]]:
    downloads: list[DownloadedImage] = []

    def replace_css_url(match: re.Match[str]) -> str:
        raw = next((group for group in match.groups() if group is not None), "").strip()
        if not raw or not is_http_ref(raw) or not looks_like_css_image_url(raw):
            return match.group(0)
        downloaded = download_image(normalize_http_ref(raw), output_dir=output_dir, cache=cache)
        downloads.append(downloaded)
        return match.group(0).replace(raw, downloaded.relative_path)

    return URL_RE.sub(replace_css_url, text), downloads


def update_assets_manifest(output_dir: Path, downloads: list[DownloadedImage]) -> None:
    if not downloads:
        return
    manifest = output_dir / "assets-manifest.yaml"
    if not manifest.is_file():
        return
    text = manifest.read_text(encoding="utf-8")
    existing = set(re.findall(r"^\s*-\s+(.+?)\s*$", text, flags=re.M))
    additions = [item.relative_path for item in downloads if item.relative_path not in existing]
    if not additions:
        return
    if re.search(r"^deck-local:\s*\[\]\s*$", text, flags=re.M):
        replacement = "deck-local:\n" + "\n".join(f"  - {path}" for path in sorted(additions))
        text = re.sub(r"^deck-local:\s*\[\]\s*$", replacement, text, flags=re.M)
    elif re.search(r"^deck-local:\s*$", text, flags=re.M):
        lines = text.splitlines()
        out: list[str] = []
        inserted = False
        in_deck_local = False
        for line in lines:
            if line == "deck-local:":
                in_deck_local = True
                out.append(line)
                continue
            if in_deck_local and re.match(r"^[A-Za-z][A-Za-z0-9_-]*:", line):
                out.extend(f"  - {path}" for path in sorted(additions))
                inserted = True
                in_deck_local = False
            out.append(line)
        if not inserted:
            out.extend(f"  - {path}" for path in sorted(additions))
        text = "\n".join(out) + "\n"
    else:
        text = text.rstrip() + "\n" + "deck-local:\n" + "\n".join(f"  - {path}" for path in sorted(additions)) + "\n"
    manifest.write_text(text, encoding="utf-8")


def materialize(output_dir: Path) -> list[DownloadedImage]:
    output_dir = output_dir.resolve()
    cache: dict[str, DownloadedImage] = {}
    downloads: list[DownloadedImage] = []
    files = sorted(
        path for path in output_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".html", ".htm", ".css"}
    )
    for path in files:
        original = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() == ".css":
            rewritten, found = rewrite_css_text(original, output_dir=output_dir, cache=cache)
        else:
            rewritten, found = rewrite_html_text(original, output_dir=output_dir, cache=cache)
        if rewritten != original:
            path.write_text(rewritten, encoding="utf-8")
        downloads.extend(found)
    unique = list({item.relative_path: item for item in downloads}.values())
    update_assets_manifest(output_dir, unique)
    return unique


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize remote http(s) image references into output/assets/remote.")
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args(argv)
    if not args.output_dir.is_dir():
        parser.error(f"output_dir not found: {args.output_dir}")
    try:
        downloads = materialize(args.output_dir)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if downloads:
        print(f"materialized {len(downloads)} remote image(s):")
        for item in downloads:
            print(f"  - {item.url} -> {item.relative_path}")
    else:
        print("materialized 0 remote image(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
