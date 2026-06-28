#!/usr/bin/env python3
"""
Prepare deck HTML for Magic Page publishing without oversized inline payloads.

Magic Page receives one HTML document, but large image data URIs make that
document too heavy. This helper uploads local image references and
data:image/... payloads to the configured TOS uploader, then rewrites the
HTML to public URLs. It can also externalize inline CSS/JS blocks to TOS so the
HTML body sent to Magic Page stays below service limits.
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import unquote, unquote_to_bytes, urlparse
from urllib.request import Request, urlopen


RESOURCE_ATTRS = {"src", "href", "poster"}
NON_DEPENDENCY_SCHEMES = {"", "about", "blob", "javascript", "mailto", "tel"}
NETWORK_TIMEOUT_SECONDS = 20
DEFAULT_UPLOAD_WORKERS = 6
SKILL_ROOT = Path(__file__).resolve().parents[1]
# delivery-7: cap remote bodies so a hostile/huge URL can't exhaust memory.
MAX_EXTERNAL_BYTES = 64 * 1024 * 1024  # 64 MB
MIME_SUFFIXES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
    "font/woff": ".woff",
    "font/woff2": ".woff2",
    "application/font-woff": ".woff",
    "application/font-woff2": ".woff2",
    "application/javascript": ".js",
    "text/javascript": ".js",
    "text/css": ".css",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "audio/mpeg": ".mp3",
}
URL_RE = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)]*))\s*\)", re.I)
IMPORT_RE = re.compile(r"@import\s+(?:url\(\s*)?(?:\"([^\"]*)\"|'([^']*)'|([^;'\")\s]+))(?:\s*\))?", re.I)
RESOURCE_ATTR_RE = re.compile(r"(<(?P<tag>[A-Za-z][\w:-]*)\b[^>]*?\b(?P<attr>src|href|poster)\s*=\s*)([\"'])(.*?)\4", re.I | re.S)
SRCSET_ATTR_RE = re.compile(r"(<[A-Za-z][\w:-]*\b[^>]*?\bsrcset\s*=\s*)([\"'])(.*?)\2", re.I | re.S)
DATA_URI_RE = re.compile(r"^data:([^;,]+)(?:;([^,]*))?,(.*)$", re.I | re.S)
STYLE_BLOCK_RE = re.compile(r"<style\b([^>]*)>(.*?)</style>", re.I | re.S)
SCRIPT_BLOCK_RE = re.compile(r"<script\b((?:(?!\bsrc\s*=)[^>])*)>(.*?)</script>", re.I | re.S)
SCRIPT_TYPE_RE = re.compile(r"\btype\s*=\s*([\"'])(.*?)\1", re.I | re.S)
LINK_REL_RE = re.compile(r"\brel\s*=\s*([\"'])(.*?)\1", re.I | re.S)


def is_external_ref(ref: str) -> bool:
    raw = ref.strip()
    return (
        not raw
        or raw.startswith(("#", "blob:", "http://", "https://", "//"))
        or raw.lower().startswith(("javascript:", "mailto:", "tel:", "about:"))
    )


def is_http_ref(ref: str) -> bool:
    raw = ref.strip()
    return raw.startswith(("http://", "https://", "//"))


def normalize_http_ref(ref: str) -> str:
    raw = ref.strip()
    if raw.startswith("//"):
        return "https:" + raw
    return raw


def is_probable_resource_attr(tag: str, attr: str, ref: str) -> bool:
    if attr.lower() not in RESOURCE_ATTRS:
        return False
    tag = tag.lower()
    attr = attr.lower()
    # A REMOTE <iframe src> is a LIVE EMBED (e.g. a Feishu Docx / Base), not a
    # re-hostable file. Fetching it would chase the embed origin's login 302
    # and 404 the deck; leave external iframe srcs untouched so the embed loads
    # at runtime. (Local prototype iframes still re-host normally.)
    if tag == "iframe" and is_http_ref(ref):
        return False
    if attr in {"src", "poster"}:
        return True
    if attr == "href" and tag == "image":
        return True
    if tag != "link":
        return False
    rel_match = LINK_REL_RE.search(ref)
    # The caller passes only the ref for regex simplicity, so use permissive
    # handling for link hrefs: link tags are delivery resources in deck HTML.
    return True


def strip_ref(ref: str) -> str:
    # F-333: an inline-style url(&quot;input/x.png&quot;) reaches URL_RE whose bare
    # ([^)]*) branch captures the whole `&quot;input/x.png&quot;` (else the image is
    # never uploaded to TOS → 404 on the published Magic Page). ONLY when a
    # quote-entity wrapper is present do we unescape (→ `"input/x.png"`) and strip the
    # now-literal quotes; gated so a genuine CSS url() filename carrying some OTHER
    # named entity stays byte-identical. Covers URL_RE + IMPORT_RE + resource-attr at
    # one choke point; safe because emit re-quotes a fresh TOS url. (External refs are
    # filtered out before here.)
    s = ref.strip()
    if any(e in s for e in ("&quot;", "&#34;", "&apos;", "&#39;")):
        s = html_lib.unescape(s).strip("\"'")
    return unquote(s.split("#", 1)[0].split("?", 1)[0])


def resolve_asset(html_path: Path, ref: str, *, base_dir: Path | None = None) -> Path | None:
    if is_external_ref(ref) or ref.strip().startswith("data:"):
        return None
    raw = strip_ref(ref)
    if not raw:
        return None
    roots = [base_dir or html_path.parent]
    if SKILL_ROOT not in roots:
        roots.append(SKILL_ROOT)
    for root in roots:
        candidate = (root / raw).resolve()
        if candidate.is_file():
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


def upload_bytes(
    payload: bytes,
    *,
    suffix: str,
    uploader: Path,
    base_url: str,
    key_prefix: str,
    folder: str,
    temp_dir: Path,
    cache: dict[str, str],
) -> str:
    digest = hashlib.sha256(payload).hexdigest()[:16]
    cache_key = f"{folder}:{digest}:{suffix}"
    if cache_key in cache:
        return cache[cache_key]
    tmp = temp_dir / f"{folder}-{digest}{suffix}"
    tmp.write_bytes(payload)
    key = "/".join(part for part in (safe_key_part(key_prefix), f"{folder}/{digest}{suffix}") if part)
    url = upload_file(tmp, uploader=uploader, base_url=base_url, key=key)
    cache[cache_key] = url
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
    match = DATA_URI_RE.match(ref.strip())
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


def upload_ref_uncached(
    ref: str,
    *,
    html_path: Path,
    base_dir: Path,
    uploader: Path,
    base_url: str,
    key_prefix: str,
    temp_dir: Path,
) -> tuple[str | None, str]:
    parsed = data_uri_payload(ref)
    if parsed is not None:
        mime, payload = parsed
        suffix = MIME_SUFFIXES.get(mime) or mimetypes.guess_extension(mime) or ".img"
        digest = hashlib.sha256(payload).hexdigest()[:16]
        tmp = temp_dir / f"data-image-{digest}{suffix}"
        tmp.write_bytes(payload)
        key = "/".join(part for part in (safe_key_part(key_prefix), f"data-uri/{digest}{suffix}") if part)
        return upload_file(tmp, uploader=uploader, base_url=base_url, key=key), "data"
    if is_http_ref(ref):
        url = normalize_http_ref(ref)
        downloaded = download_external_ref(url, temp_dir=temp_dir, cache={})
        public = upload_file(
            downloaded,
            uploader=uploader,
            base_url=base_url,
            key="/".join(
                part
                for part in (
                    safe_key_part(key_prefix),
                    f"external/{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}{downloaded.suffix}",
                )
                if part
            ),
        )
        return public, "external"
    asset = resolve_asset(html_path, ref, base_dir=base_dir)
    if asset is None:
        return None, ""
    return (
        upload_file(
            asset.resolve(),
            uploader=uploader,
            base_url=base_url,
            key=key_for(asset.resolve(), base_dir.resolve(), key_prefix),
        ),
        "local",
    )


def suffix_from_url(url: str, content_type: str) -> str:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix:
        return suffix[:16]
    mime = content_type.split(";", 1)[0].strip().lower()
    return MIME_SUFFIXES.get(mime) or mimetypes.guess_extension(mime) or ".bin"


def download_external_ref(
    ref: str,
    *,
    temp_dir: Path,
    cache: dict[str, Path],
) -> Path:
    url = normalize_http_ref(ref)
    if url in cache:
        return cache[url]
    request = Request(url, headers={"User-Agent": "feishu-deck-h5-publisher/1.0"})
    with urlopen(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
        # delivery-7: refuse oversized bodies early (Content-Length when present),
        # and read at most MAX_EXTERNAL_BYTES + 1 so an unsized/streaming response
        # can't read the whole thing into memory.
        declared = response.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > MAX_EXTERNAL_BYTES:
            raise RuntimeError(
                f"external resource too large ({int(declared)} bytes > "
                f"{MAX_EXTERNAL_BYTES} cap): {url}")
        payload = response.read(MAX_EXTERNAL_BYTES + 1)
        content_type = response.headers.get("content-type", "application/octet-stream")
    if len(payload) > MAX_EXTERNAL_BYTES:
        raise RuntimeError(
            f"external resource exceeds {MAX_EXTERNAL_BYTES}-byte cap: {url}")
    if not payload:
        raise RuntimeError(f"external resource is empty: {url}")
    digest = hashlib.sha256(payload).hexdigest()[:16]
    suffix = suffix_from_url(url, content_type)
    target = temp_dir / f"external-{digest}{suffix}"
    target.write_bytes(payload)
    cache[url] = target
    return target


def collect_resource_refs(html: str) -> list[str]:
    refs: list[str] = []
    for regex in (URL_RE, IMPORT_RE):
        for match in regex.finditer(html):
            ref = next((group for group in match.groups() if group is not None), "").strip()
            if ref:
                refs.append(ref)
    for match in RESOURCE_ATTR_RE.finditer(html):
        tag = match.group("tag")
        attr = match.group("attr")
        src = match.group(5)
        if is_probable_resource_attr(tag, attr, src):
            refs.append(src)
    for match in SRCSET_ATTR_RE.finditer(html):
        for item in match.group(3).split(","):
            item = item.strip()
            if item:
                refs.append(item.split()[0])
    out: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def rewrite_refs(
    html: str,
    html_path: Path,
    *,
    uploader: Path,
    base_url: str,
    key_prefix: str,
    asset_base_dir: Path | None = None,
    upload_workers: int = DEFAULT_UPLOAD_WORKERS,
) -> tuple[str, int, int, int]:
    base_dir = (asset_base_dir or html_path.parent).resolve()

    with tempfile.TemporaryDirectory(prefix="magic-page-assets-") as tmp_name:
        temp_dir = Path(tmp_name)
        url_map: dict[str, str] = {}
        counts = {"local": 0, "data": 0, "external": 0}

        uploadable = [
            ref for ref in collect_resource_refs(html)
            if ref.strip().startswith("data:") or is_http_ref(ref) or resolve_asset(html_path, ref, base_dir=base_dir)
        ]
        workers = max(1, int(upload_workers or 1))
        if workers == 1:
            for ref in uploadable:
                url, kind = upload_ref_uncached(
                    ref,
                    html_path=html_path,
                    base_dir=base_dir,
                    uploader=uploader,
                    base_url=base_url,
                    key_prefix=key_prefix,
                    temp_dir=temp_dir,
                )
                if url:
                    url_map[ref] = url
                    counts[kind] += 1
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                future_to_ref = {
                    pool.submit(
                        upload_ref_uncached,
                        ref,
                        html_path=html_path,
                        base_dir=base_dir,
                        uploader=uploader,
                        base_url=base_url,
                        key_prefix=key_prefix,
                        temp_dir=temp_dir,
                    ): ref
                    for ref in uploadable
                }
                for future in as_completed(future_to_ref):
                    ref = future_to_ref[future]
                    url, kind = future.result()
                    if url:
                        url_map[ref] = url
                        counts[kind] += 1

        def public_url(ref: str) -> str | None:
            return url_map.get(ref)

        def replace_url(match: re.Match[str]) -> str:
            ref = next((group for group in match.groups() if group is not None), "").strip()
            url = public_url(ref)
            if url is None:
                return match.group(0)
            return f"url('{url}')"

        def replace_import(match: re.Match[str]) -> str:
            ref = next((group for group in match.groups() if group is not None), "").strip()
            url = public_url(ref)
            if url is None:
                return match.group(0)
            return f"@import url('{url}')"

        def replace_resource_attr(match: re.Match[str]) -> str:
            prefix = match.group(1)
            tag = match.group("tag")
            attr = match.group("attr")
            quote = match.group(4)
            src = match.group(5)
            # delivery-6: only rewrite attrs that are actually delivery resources.
            # Without this, an <a href="page2.html"> navigation link gets treated
            # as an upload target. is_probable_resource_attr keeps src/poster on
            # any tag, but limits href to <link>.
            if not is_probable_resource_attr(tag, attr, src):
                return match.group(0)
            url = public_url(src)
            if url is None:
                return match.group(0)
            return f"{prefix}{quote}{html_lib.escape(url, quote=True)}{quote}"

        def replace_srcset(match: re.Match[str]) -> str:
            prefix, quote, value = match.groups()
            items = []
            changed = False
            for item in value.split(","):
                item = item.strip()
                if not item:
                    continue
                parts = item.split()
                url = public_url(parts[0])
                if url:
                    parts[0] = url
                    changed = True
                items.append(" ".join(parts))
            if not changed:
                return match.group(0)
            return f"{prefix}{quote}{html_lib.escape(', '.join(items), quote=True)}{quote}"

        html = URL_RE.sub(replace_url, html)
        html = IMPORT_RE.sub(replace_import, html)
        html = RESOURCE_ATTR_RE.sub(replace_resource_attr, html)
        html = SRCSET_ATTR_RE.sub(replace_srcset, html)

    return html, counts["local"], counts["data"], counts["external"]


def script_type_allows_externalize(attrs: str) -> bool:
    match = SCRIPT_TYPE_RE.search(attrs)
    if not match:
        return True
    script_type = match.group(2).strip().lower()
    return script_type in {
        "",
        "text/javascript",
        "application/javascript",
        "module",
    }


def externalize_inline_blocks(
    html: str,
    *,
    uploader: Path,
    base_url: str,
    key_prefix: str,
) -> tuple[str, int, int]:
    cache: dict[str, str] = {}
    css_count = 0
    js_count = 0

    with tempfile.TemporaryDirectory(prefix="magic-page-code-") as tmp_name:
        temp_dir = Path(tmp_name)

        def replace_style(match: re.Match[str]) -> str:
            nonlocal css_count
            attrs, css = match.groups()
            if not css.strip():
                return match.group(0)
            url = upload_bytes(
                css.encode("utf-8"),
                suffix=".css",
                uploader=uploader,
                base_url=base_url,
                key_prefix=key_prefix,
                folder="css",
                temp_dir=temp_dir,
                cache=cache,
            )
            css_count += 1
            return f'<link rel="stylesheet" href="{html_lib.escape(url, quote=True)}">'

        def replace_script(match: re.Match[str]) -> str:
            nonlocal js_count
            attrs, js = match.groups()
            if not js.strip() or not script_type_allows_externalize(attrs):
                return match.group(0)
            url = upload_bytes(
                js.encode("utf-8"),
                suffix=".js",
                uploader=uploader,
                base_url=base_url,
                key_prefix=key_prefix,
                folder="js",
                temp_dir=temp_dir,
                cache=cache,
            )
            js_count += 1
            clean_attrs = attrs.rstrip()
            if clean_attrs:
                return f'<script{clean_attrs} src="{html_lib.escape(url, quote=True)}"></script>'
            return f'<script src="{html_lib.escape(url, quote=True)}"></script>'

        html = STYLE_BLOCK_RE.sub(replace_style, html)
        html = SCRIPT_BLOCK_RE.sub(replace_script, html)

    return html, css_count, js_count


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upload deck images to TOS and rewrite Magic Page HTML refs.")
    parser.add_argument("html", help="Input HTML file")
    parser.add_argument("--out", default="", help="Output HTML file; defaults to overwriting input")
    parser.add_argument("--uploader", required=True, help="Path to the TOS upload-asset.js script")
    parser.add_argument("--base-url", default="https://magic.solutionsuite.cn", help="Magic service base URL")
    parser.add_argument("--key-prefix", required=True, help="TOS key prefix for uploaded deck assets")
    parser.add_argument("--asset-base-dir", help="Directory used to resolve relative resources after HTML was copied/inlined")
    parser.add_argument("--keep-inline-code", action="store_true", help="do not externalize inline <style>/<script> blocks")
    parser.add_argument("--upload-workers", type=int, default=DEFAULT_UPLOAD_WORKERS, help="parallel asset upload workers")
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
        rewritten, local_uploaded, data_uploaded, external_uploaded = rewrite_refs(
            html,
            src,
            uploader=uploader,
            base_url=args.base_url,
            key_prefix=args.key_prefix,
            asset_base_dir=Path(args.asset_base_dir).expanduser().resolve() if args.asset_base_dir else None,
            upload_workers=args.upload_workers,
        )
        css_uploaded = 0
        js_uploaded = 0
        if not args.keep_inline_code:
            rewritten, css_uploaded, js_uploaded = externalize_inline_blocks(
                rewritten,
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
    print(f"  data payloads: {data_uploaded}")
    print(f"  external refs: {external_uploaded}")
    print(f"  css blocks   : {css_uploaded}")
    print(f"  js blocks    : {js_uploaded}")
    print(f"  key prefix   : {shlex.quote(args.key_prefix)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
