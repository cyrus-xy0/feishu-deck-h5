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
import json
import mimetypes
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_resources import download_public_resource


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


def remote_asset_path(url: str, digest: str, suffix: str) -> str:
    parsed = urlparse(url)
    host = safe_segment(parsed.netloc) or "remote"
    stem = safe_segment(Path(unquote(parsed.path or "")).stem) or "image"
    return f"assets/remote/{host}/{stem}-{digest[:16]}{suffix}"


def download_image(url: str, *, output_dir: Path, cache: dict[str, DownloadedImage]) -> DownloadedImage:
    if url in cache:
        return cache[url]
    try:
        downloaded = download_public_resource(
            url,
            max_bytes=MAX_REMOTE_IMAGE_BYTES,
            timeout=NETWORK_TIMEOUT_SECONDS,
            user_agent="feishu-deck-h5-packager/1.0",
            allowed_type_prefixes=("image/",),
        )
    except RuntimeError as exc:
        raise RuntimeError(f"remote image download failed: {exc} {url}") from exc
    payload = downloaded.payload
    size = len(payload)
    content_type = downloaded.content_type
    digest_hex = hashlib.sha256(payload).hexdigest()
    rel = remote_asset_path(url, digest_hex, suffix_from_url_or_type(downloaded.url, content_type))
    target = output_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.stat().st_size != size:
        target.write_bytes(payload)
    item = DownloadedImage(url=url, relative_path=rel, path=target, content_type=content_type, size=size)
    cache[url] = item
    return item


def reference_from(source_path: Path, output_dir: Path, downloaded: DownloadedImage) -> str:
    """Return a browser ref relative to the file that contains the reference."""
    final_asset = output_dir.resolve() / downloaded.relative_path
    return Path(os.path.relpath(final_asset, source_path.resolve().parent)).as_posix()


def rewrite_srcset(
    value: str,
    *,
    output_dir: Path,
    cache: dict[str, DownloadedImage],
    source_path: Path | None = None,
    download_dir: Path | None = None,
) -> tuple[str, list[DownloadedImage]]:
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
            downloaded = download_image(
                normalize_http_ref(ref), output_dir=download_dir or output_dir, cache=cache)
            bits[0] = reference_from(
                source_path or (output_dir / "index.html"), output_dir, downloaded)
            downloads.append(downloaded)
            changed = True
        pieces.append(" ".join(bits))
    return (", ".join(pieces) if changed else value), downloads


def rewrite_html_text(
    text: str,
    *,
    output_dir: Path,
    cache: dict[str, DownloadedImage],
    source_path: Path | None = None,
    download_dir: Path | None = None,
) -> tuple[str, list[DownloadedImage]]:
    downloads: list[DownloadedImage] = []
    source = source_path or (output_dir / "index.html")

    def replace_css_url(match: re.Match[str]) -> str:
        raw = next((group for group in match.groups() if group is not None), "").strip()
        if not raw or not is_http_ref(raw) or not looks_like_css_image_url(raw):
            return match.group(0)
        downloaded = download_image(
            normalize_http_ref(raw), output_dir=download_dir or output_dir, cache=cache)
        downloads.append(downloaded)
        return match.group(0).replace(raw, reference_from(source, output_dir, downloaded))

    def replace_attr(match: re.Match[str]) -> str:
        raw = match.group(5 if match.re is IMAGE_ATTR_RE else 4)
        if not raw or not is_http_ref(raw):
            return match.group(0)
        downloaded = download_image(
            normalize_http_ref(raw), output_dir=download_dir or output_dir, cache=cache)
        downloads.append(downloaded)
        return match.group(0).replace(raw, reference_from(source, output_dir, downloaded))

    def replace_srcset(match: re.Match[str]) -> str:
        value = match.group(4)
        rewritten, new_downloads = rewrite_srcset(
            value,
            output_dir=output_dir,
            cache=cache,
            source_path=source,
            download_dir=download_dir,
        )
        downloads.extend(new_downloads)
        return match.group(0).replace(value, rewritten)

    new_text = URL_RE.sub(replace_css_url, text)
    new_text = IMAGE_ATTR_RE.sub(replace_attr, new_text)
    new_text = POSTER_ATTR_RE.sub(replace_attr, new_text)
    new_text = SRCSET_ATTR_RE.sub(replace_srcset, new_text)
    return new_text, downloads


def rewrite_css_text(
    text: str,
    *,
    output_dir: Path,
    cache: dict[str, DownloadedImage],
    source_path: Path | None = None,
    download_dir: Path | None = None,
) -> tuple[str, list[DownloadedImage]]:
    downloads: list[DownloadedImage] = []
    source = source_path or (output_dir / "index.css")

    def replace_css_url(match: re.Match[str]) -> str:
        raw = next((group for group in match.groups() if group is not None), "").strip()
        if not raw or not is_http_ref(raw) or not looks_like_css_image_url(raw):
            return match.group(0)
        downloaded = download_image(
            normalize_http_ref(raw), output_dir=download_dir or output_dir, cache=cache)
        downloads.append(downloaded)
        return match.group(0).replace(raw, reference_from(source, output_dir, downloaded))

    return URL_RE.sub(replace_css_url, text), downloads


def updated_assets_manifest_text(text: str, downloads: list[DownloadedImage]) -> str:
    """Return manifest text with root-relative downloaded asset entries."""
    if not downloads:
        return text
    existing = set(re.findall(r"^\s*-\s+(.+?)\s*$", text, flags=re.M))
    additions = [item.relative_path for item in downloads if item.relative_path not in existing]
    if not additions:
        return text
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
    return text


def update_assets_manifest(output_dir: Path, downloads: list[DownloadedImage]) -> None:
    """Compatibility wrapper; materialize() uses the transactional pure helper."""
    manifest = output_dir / "assets-manifest.yaml"
    if not downloads or not manifest.is_file():
        return
    original = manifest.read_text(encoding="utf-8")
    rewritten = updated_assets_manifest_text(original, downloads)
    if rewritten != original:
        manifest.write_text(rewritten, encoding="utf-8")


def _deck_aliases(url: str) -> tuple[str, ...]:
    aliases = [url, html.escape(url, quote=False)]
    if url.startswith("https://"):
        protocol_relative = "//" + url[len("https://"):]
        aliases.extend((protocol_relative, html.escape(protocol_relative, quote=False)))
    return tuple(dict.fromkeys(aliases))


def rewrite_deck_value(value, replacements: dict[str, str]) -> tuple[object, int]:
    """Recursively rewrite successfully materialized URLs in DeckJSON values."""
    if isinstance(value, str):
        rewritten = value
        count = 0
        aliases = sorted(
            ((alias, local_ref)
             for url, local_ref in replacements.items()
             for alias in _deck_aliases(url)),
            key=lambda item: len(item[0]),
            reverse=True,
        )
        for alias, local_ref in aliases:
            occurrences = rewritten.count(alias)
            if occurrences:
                rewritten = rewritten.replace(alias, local_ref)
                count += occurrences
        return rewritten, count
    if isinstance(value, list):
        out = []
        count = 0
        for item in value:
            new_item, changed = rewrite_deck_value(item, replacements)
            out.append(new_item)
            count += changed
        return out, count
    if isinstance(value, dict):
        out = {}
        count = 0
        for key, item in value.items():
            new_item, changed = rewrite_deck_value(item, replacements)
            out[key] = new_item
            count += changed
        return out, count
    return value, 0


def _commit_transaction(
    output_dir: Path,
    stage_dir: Path,
    text_updates: dict[Path, str],
    downloads: list[DownloadedImage],
) -> None:
    """Commit staged assets first, then text; roll back on any commit error."""
    plans: list[tuple[Path, Path]] = []
    for item in downloads:
        plans.append((item.path, output_dir / item.relative_path))

    text_stage = stage_dir / "text"
    for index, (destination, text) in enumerate(text_updates.items()):
        staged = text_stage / f"{index:04d}.txt"
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(text, encoding="utf-8")
        if destination.exists():
            shutil.copymode(destination, staged, follow_symlinks=False)
        plans.append((staged, destination))

    backup_dir = stage_dir / "backup"
    applied: list[tuple[Path, Path | None]] = []
    created_dirs: set[Path] = set()
    try:
        for index, (staged, destination) in enumerate(plans):
            try:
                destination.resolve().relative_to(output_dir)
            except ValueError as exc:
                raise RuntimeError(
                    f"materialize destination escapes output directory: {destination}"
                ) from exc
            parent = destination.parent
            while parent != output_dir and not parent.exists():
                created_dirs.add(parent)
                parent = parent.parent
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.is_symlink():
                raise RuntimeError(f"refusing to replace symlink during materialize: {destination}")
            backup: Path | None = None
            if destination.exists():
                backup = backup_dir / f"{index:04d}.bak"
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup)
            os.replace(staged, destination)
            applied.append((destination, backup))
    except Exception as exc:
        for destination, backup in reversed(applied):
            try:
                if backup is None:
                    destination.unlink(missing_ok=True)
                else:
                    os.replace(backup, destination)
            except OSError:
                pass
        for directory in sorted(created_dirs, key=lambda path: len(path.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise RuntimeError(f"materialize commit failed and was rolled back: {exc}") from exc


def materialize(output_dir: Path) -> list[DownloadedImage]:
    output_dir = output_dir.resolve()
    files = sorted(
        path for path in output_dir.rglob("*")
        if path.is_file() and not path.is_symlink()
        and path.suffix.lower() in {".html", ".htm", ".css"}
    )
    with tempfile.TemporaryDirectory(prefix=".materialize-remote-", dir=output_dir.parent) as tmp:
        stage_dir = Path(tmp)
        download_dir = stage_dir / "download"
        cache: dict[str, DownloadedImage] = {}
        text_updates: dict[Path, str] = {}

        # No destination file is touched while downloads are in progress.
        for path in files:
            original = path.read_text(encoding="utf-8", errors="replace")
            if path.suffix.lower() == ".css":
                rewritten, _found = rewrite_css_text(
                    original,
                    output_dir=output_dir,
                    cache=cache,
                    source_path=path,
                    download_dir=download_dir,
                )
            else:
                rewritten, _found = rewrite_html_text(
                    original,
                    output_dir=output_dir,
                    cache=cache,
                    source_path=path,
                    download_dir=download_dir,
                )
            if rewritten != original:
                text_updates[path] = rewritten

        unique = list({item.relative_path: item for item in cache.values()}.values())
        replacements = {url: item.relative_path for url, item in cache.items()}

        deck_path = output_dir / "deck.json"
        if replacements and deck_path.is_file():
            if deck_path.is_symlink():
                raise RuntimeError(f"refusing to rewrite symlinked deck.json: {deck_path}")
            original_deck_text = deck_path.read_text(encoding="utf-8")
            try:
                deck = json.loads(original_deck_text)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"cannot update invalid deck.json: {exc}") from exc
            rewritten_deck, changed = rewrite_deck_value(deck, replacements)
            if changed:
                text_updates[deck_path] = json.dumps(
                    rewritten_deck, ensure_ascii=False, indent=2) + "\n"

        manifest = output_dir / "assets-manifest.yaml"
        if unique and manifest.is_file():
            if manifest.is_symlink():
                raise RuntimeError(f"refusing to rewrite symlinked manifest: {manifest}")
            original_manifest = manifest.read_text(encoding="utf-8")
            rewritten_manifest = updated_assets_manifest_text(original_manifest, unique)
            if rewritten_manifest != original_manifest:
                text_updates[manifest] = rewritten_manifest

        _commit_transaction(output_dir, stage_dir, text_updates, unique)
        return [
            DownloadedImage(
                url=item.url,
                relative_path=item.relative_path,
                path=output_dir / item.relative_path,
                content_type=item.content_type,
                size=item.size,
            )
            for item in unique
        ]


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
