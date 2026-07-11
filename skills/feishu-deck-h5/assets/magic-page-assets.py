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
import json
import mimetypes
import re
import selectors
import shlex
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import unquote, unquote_to_bytes, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_resources import download_public_resource, resolve_local_file


RESOURCE_ATTRS = {"src", "href", "poster"}
NON_DEPENDENCY_SCHEMES = {"", "about", "blob", "javascript", "mailto", "tel"}
NETWORK_TIMEOUT_SECONDS = 20
DEFAULT_UPLOAD_WORKERS = 6
MAX_UPLOAD_WORKERS = 16
BATCH_UPLOAD_TIMEOUT_SECONDS = 600
BATCH_PROTOCOL = "magic-upload-batch/v1"
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
    "application/ecmascript": ".js",
    "application/x-javascript": ".js",
    "text/javascript": ".js",
    "text/ecmascript": ".js",
    "text/css": ".css",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "audio/mpeg": ".mp3",
}
EXTERNAL_RESOURCE_TYPES = set(MIME_SUFFIXES) | {
    "application/octet-stream",
    "application/wasm",
    "application/vnd.ms-fontobject",
}
LOCAL_RESOURCE_SUFFIXES = {
    ".apng", ".avif", ".bmp", ".gif", ".ico", ".jpg", ".jpeg", ".png", ".svg", ".webp",
    ".css", ".js", ".mjs", ".wasm", ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp4", ".webm", ".mov", ".m4v", ".mp3", ".wav", ".ogg",
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
ANY_SCRIPT_BLOCK_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.I | re.S)
CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


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
    # at runtime.
    if tag == "iframe" and is_http_ref(ref):
        return False
    # Local HTML iframes are pages, not static resources. Uploading them directly
    # to TOS can return attachment-style delivery headers and blank embedded
    # demos. The publisher rewrites these through magic-iframe-faas.py before this
    # script runs; if one reaches here, leave it untouched so the integrity gate
    # catches it instead of silently producing a broken TOS iframe.
    if tag == "iframe":
        path = ref.split("#", 1)[0].split("?", 1)[0].strip().lower()
        if path.endswith((".html", ".htm")):
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


def trusted_asset_roots(html_path: Path, base_dir: Path) -> tuple[Path, ...]:
    roots = [base_dir.resolve(), SKILL_ROOT / "assets", SKILL_ROOT / "deck-json" / "templates"]
    if base_dir.name == "output":
        roots.append(base_dir.parent)
    return tuple(dict.fromkeys(root.resolve() for root in roots))


def resolve_asset(html_path: Path, ref: str, *, base_dir: Path | None = None) -> Path | None:
    if is_external_ref(ref) or ref.strip().startswith("data:"):
        return None
    raw = strip_ref(ref)
    if not raw:
        return None
    base = (base_dir or html_path.parent).resolve()
    return resolve_local_file(
        base,
        raw,
        allowed_roots=trusted_asset_roots(html_path, base),
        allowed_suffixes=LOCAL_RESOURCE_SUFFIXES,
    )


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
    """Explicit legacy single-file uploader path.

    Normal packaging uses upload_batch() once. This function remains only for
    callers that opt into --legacy-uploader for an older custom script.
    """
    cmd = ["node", str(uploader), str(asset), "--key", key, "--base-url", base_url, "-q"]
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        timeout=BATCH_UPLOAD_TIMEOUT_SECONDS,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "unknown upload failure"
        raise RuntimeError(f"upload failed for {asset}: {detail}")
    url = proc.stdout.strip()
    if not url.startswith(("http://", "https://")):
        raise RuntimeError(f"uploader returned a non-URL for {asset}: {url!r}")
    return url


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_base_url(base_url: str) -> str:
    raw = str(base_url or "https://magic.solutionsuite.cn").strip().rstrip("/")
    if not raw:
        return "https://magic.solutionsuite.cn"
    return raw if re.match(r"^https?://", raw, re.I) else "https://" + raw


def _upload_spec(asset: Path, *, key: str, base_url: str) -> dict[str, str]:
    resolved = asset.resolve()
    sha256 = _file_sha256(resolved)
    normalized_base = _normalized_base_url(base_url)
    cache_key = hashlib.sha256(
        f"{normalized_base}\0{key}\0{sha256}".encode("utf-8")
    ).hexdigest()
    content_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    return {
        "id": cache_key,
        "file": str(resolved),
        "key": key,
        "content_type": content_type,
        "sha256": sha256,
        "cache_key": cache_key,
    }


def _validate_batch_payload(
    payload: object,
    specs: list[dict[str, str]],
    *,
    returncode: int,
    stderr: str,
    expected_request_id: str | None = None,
) -> dict[str, str]:
    if not isinstance(payload, dict) or payload.get("protocol") != BATCH_PROTOCOL:
        detail = stderr.strip() or "uploader returned no valid batch JSON"
        raise RuntimeError(
            "batch uploader protocol error: " + detail
            + "; custom legacy uploaders require explicit --legacy-uploader"
        )
    rows = payload.get("items")
    if not isinstance(rows, list):
        raise RuntimeError("batch uploader protocol error: items must be a JSON array")
    expected = {spec["id"]: spec for spec in specs}
    seen: dict[str, dict] = {}
    errors: list[str] = []
    urls: dict[str, str] = {}
    if expected_request_id is not None and str(payload.get("request_id") or "") != expected_request_id:
        errors.append("batch response request_id mismatch")
    if payload.get("error"):
        errors.append(str(payload.get("error")))
    for row in rows:
        if not isinstance(row, dict):
            errors.append("non-object result row")
            continue
        item_id = str(row.get("id") or "")
        spec = expected.get(item_id)
        if spec is None:
            errors.append(f"unexpected result id {item_id!r}")
            continue
        if item_id in seen:
            errors.append(f"duplicate result id {item_id}")
            continue
        seen[item_id] = row
        for field in ("key", "sha256", "cache_key"):
            if str(row.get(field) or "") != spec[field]:
                errors.append(f"{spec['key']}: result {field} mismatch")
        if not row.get("ok"):
            errors.append(f"{spec['key']}: {row.get('error') or 'upload failed'}")
            continue
        url = str(row.get("url") or "")
        if not url.startswith(("http://", "https://")):
            errors.append(f"{spec['key']}: uploader returned non-URL {url!r}")
            continue
        urls[item_id] = url
    missing = [spec["key"] for item_id, spec in expected.items() if item_id not in seen]
    if missing:
        errors.append("missing result rows: " + ", ".join(missing[:8]))
    if returncode != 0 and not errors:
        errors.append(stderr.strip() or f"batch uploader exited {returncode}")
    if errors:
        raise RuntimeError("batch upload failed: " + "; ".join(errors[:12]))
    return urls


def upload_batch(
    specs: list[dict[str, str]],
    *,
    uploader: Path,
    base_url: str,
    workers: int,
    temp_dir: Path,
    legacy_uploader: bool = False,
) -> dict[str, str]:
    """Upload unique staged specs and return cache_key/id -> public URL.

    Native mode invokes exactly one Node process with a content-addressed JSON
    manifest. Legacy fallback is deliberately opt-in and bounded; unsupported
    custom uploaders never trigger a silent N-process fallback.
    """
    unique: dict[str, dict[str, str]] = {}
    for spec in specs:
        prior = unique.get(spec["cache_key"])
        if prior and prior != spec:
            raise RuntimeError(f"upload cache-key collision for {spec['key']}")
        unique[spec["cache_key"]] = spec
    ordered = list(unique.values())
    if not ordered:
        return {}
    bounded_workers = max(1, min(MAX_UPLOAD_WORKERS, int(workers or 1)))
    if legacy_uploader:
        def _one(spec: dict[str, str]) -> tuple[str, str]:
            if _file_sha256(Path(spec["file"])) != spec["sha256"]:
                raise RuntimeError(f"staged content changed before legacy upload: {spec['key']}")
            return spec["id"], upload_file(
                Path(spec["file"]),
                uploader=uploader,
                base_url=base_url,
                key=spec["key"],
            )

        urls: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=bounded_workers) as pool:
            futures = [pool.submit(_one, spec) for spec in ordered]
            for future in as_completed(futures):
                item_id, url = future.result()
                urls[item_id] = url
        return urls

    manifest = temp_dir / "magic-upload-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "protocol": BATCH_PROTOCOL,
                "base_url": _normalized_base_url(base_url),
                "items": ordered,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [
            "node",
            str(uploader),
            "--batch-manifest",
            str(manifest),
            "--base-url",
            base_url,
            "--workers",
            str(bounded_workers),
        ],
        text=True,
        capture_output=True,
        timeout=BATCH_UPLOAD_TIMEOUT_SECONDS,
    )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = None
    return _validate_batch_payload(
        payload,
        ordered,
        returncode=proc.returncode,
        stderr=proc.stderr,
    )


class BatchUploadSession:
    """One native Node uploader process serving one or more bounded batches."""

    def __init__(
        self,
        *,
        uploader: Path,
        base_url: str,
        workers: int,
        temp_dir: Path,
        legacy_uploader: bool = False,
    ) -> None:
        self.uploader = uploader
        self.base_url = _normalized_base_url(base_url)
        self.workers = max(1, min(MAX_UPLOAD_WORKERS, int(workers or 1)))
        self.temp_dir = temp_dir
        self.legacy_uploader = legacy_uploader
        self._proc = None
        self._stderr_file = None
        self._request_no = 0

    def __enter__(self):
        return self

    def _start(self) -> None:
        if self._proc is not None or self.legacy_uploader:
            return
        stderr_path = self.temp_dir / "magic-upload-session.stderr.log"
        self._stderr_file = stderr_path.open("w+", encoding="utf-8")
        self._proc = subprocess.Popen(
            [
                "node",
                str(self.uploader),
                "--batch-ndjson",
                "--base-url",
                self.base_url,
                "--workers",
                str(self.workers),
            ],
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self._stderr_file,
            bufsize=1,
        )

    def _stderr(self) -> str:
        if self._stderr_file is None:
            return ""
        self._stderr_file.flush()
        self._stderr_file.seek(0)
        return self._stderr_file.read()

    def upload(self, specs: list[dict[str, str]], *, temp_dir: Path) -> dict[str, str]:
        if self.legacy_uploader:
            return upload_batch(
                specs,
                uploader=self.uploader,
                base_url=self.base_url,
                workers=self.workers,
                temp_dir=temp_dir,
                legacy_uploader=True,
            )
        unique: dict[str, dict[str, str]] = {}
        for spec in specs:
            prior = unique.get(spec["cache_key"])
            if prior and prior != spec:
                raise RuntimeError(f"upload cache-key collision for {spec['key']}")
            unique[spec["cache_key"]] = spec
        ordered = list(unique.values())
        if not ordered:
            return {}
        self._start()
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise RuntimeError("batch uploader session is not running")
        self._request_no += 1
        request_id = f"batch-{self._request_no}"
        request = {
            "protocol": BATCH_PROTOCOL,
            "request_id": request_id,
            "base_url": self.base_url,
            "items": ordered,
        }
        try:
            self._proc.stdin.write(json.dumps(request, ensure_ascii=False, separators=(",", ":")) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise RuntimeError("batch uploader session closed before request: " + self._stderr()) from exc

        selector = selectors.DefaultSelector()
        try:
            selector.register(self._proc.stdout, selectors.EVENT_READ)
            if not selector.select(BATCH_UPLOAD_TIMEOUT_SECONDS):
                self._proc.kill()
                raise RuntimeError(
                    f"batch uploader timed out after {BATCH_UPLOAD_TIMEOUT_SECONDS}s"
                )
            line = self._proc.stdout.readline()
        finally:
            selector.close()
        if not line:
            code = self._proc.poll()
            raise RuntimeError(
                f"batch uploader session ended unexpectedly (exit {code}): {self._stderr()}"
            )
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "batch uploader returned invalid NDJSON: " + line[:300]
                + "; custom legacy uploaders require explicit --legacy-uploader"
            ) from exc
        return _validate_batch_payload(
            payload,
            ordered,
            returncode=0,
            stderr=self._stderr(),
            expected_request_id=request_id,
        )

    def __exit__(self, exc_type, exc, tb):
        exit_code = 0
        stderr = ""
        if self._proc is not None:
            try:
                if self._proc.stdin is not None:
                    try:
                        self._proc.stdin.close()
                    except BrokenPipeError:
                        pass
                exit_code = self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                exit_code = self._proc.wait(timeout=5)
            finally:
                if self._proc.stdout is not None:
                    self._proc.stdout.close()
            stderr = self._stderr()
        if self._stderr_file is not None:
            self._stderr_file.close()
        if exc_type is None and exit_code != 0:
            raise RuntimeError(
                f"batch uploader session exited {exit_code}: {stderr.strip()}"
            )
        return False


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
            raise RuntimeError(f"invalid base64 data URI: {exc}") from exc
    return mime, unquote_to_bytes(payload)


def _data_upload_kind(mime: str) -> tuple[str, str]:
    lowered = mime.lower()
    if lowered == "text/css":
        return "css", "css"
    if lowered in {
        "application/javascript", "application/ecmascript",
        "application/x-javascript", "text/javascript", "text/ecmascript",
    }:
        return "js", "js"
    return "data", "data-uri"


def stage_ref_uncached(
    ref: str,
    *,
    html_path: Path,
    base_dir: Path,
    base_url: str,
    key_prefix: str,
    temp_dir: Path,
) -> tuple[dict[str, str] | None, str]:
    """Resolve/download one already-collected reference, but do not upload it.

    All local containment and remote SSRF/MIME/size checks happen here before a
    manifest is ever passed to Node.
    """
    parsed = data_uri_payload(ref)
    if parsed is not None:
        mime, payload = parsed
        suffix = MIME_SUFFIXES.get(mime) or mimetypes.guess_extension(mime) or ".bin"
        digest = hashlib.sha256(payload).hexdigest()
        kind, folder = _data_upload_kind(mime)
        tmp = temp_dir / f"{folder}-{digest[:16]}{suffix}"
        if not tmp.exists():
            tmp.write_bytes(payload)
        key = "/".join(
            part
            for part in (
                safe_key_part(key_prefix),
                f"{folder}/{digest[:16]}{suffix}",
            )
            if part
        )
        return _upload_spec(tmp, key=key, base_url=base_url), kind
    if is_http_ref(ref):
        url = normalize_http_ref(ref)
        downloaded = download_external_ref(url, temp_dir=temp_dir, cache={})
        key = "/".join(
            part
            for part in (
                safe_key_part(key_prefix),
                f"external/{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}{downloaded.suffix}",
            )
            if part
        )
        return _upload_spec(downloaded, key=key, base_url=base_url), "external"
    asset = resolve_asset(html_path, ref, base_dir=base_dir)
    if asset is None:
        return None, ""
    resolved = asset.resolve()
    return (
        _upload_spec(
            resolved,
            key=key_for(resolved, base_dir.resolve(), key_prefix),
            base_url=base_url,
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
    downloaded = download_public_resource(
        url,
        max_bytes=MAX_EXTERNAL_BYTES,
        timeout=NETWORK_TIMEOUT_SECONDS,
        user_agent="feishu-deck-h5-publisher/1.0",
        allowed_types=EXTERNAL_RESOURCE_TYPES,
        allowed_type_prefixes=("image/", "font/", "audio/", "video/"),
    )
    payload = downloaded.payload
    content_type = downloaded.content_type
    digest = hashlib.sha256(payload).hexdigest()[:16]
    suffix = suffix_from_url(downloaded.url, content_type)
    url_digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
    target = temp_dir / f"external-{url_digest}-{digest}{suffix}"
    target.write_bytes(payload)
    cache[url] = target
    return target


def collect_resource_refs(html: str) -> list[str]:
    refs: list[str] = []
    css_scan = CSS_COMMENT_RE.sub(" ", ANY_SCRIPT_BLOCK_RE.sub(" ", html))
    for regex in (URL_RE, IMPORT_RE):
        for match in regex.finditer(css_scan):
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


def sub_outside_script_blocks(
    regex: re.Pattern[str],
    repl,
    html: str,
) -> str:
    pieces: list[str] = []
    last = 0
    for match in ANY_SCRIPT_BLOCK_RE.finditer(html):
        pieces.append(regex.sub(repl, html[last:match.start()]))
        pieces.append(match.group(0))
        last = match.end()
    pieces.append(regex.sub(repl, html[last:]))
    return "".join(pieces)


def _rewrite_refs_batched(
    html: str,
    html_path: Path,
    *,
    uploader: Path,
    base_url: str,
    key_prefix: str,
    asset_base_dir: Path | None = None,
    upload_workers: int = DEFAULT_UPLOAD_WORKERS,
    legacy_uploader: bool = False,
    upload_session: BatchUploadSession | None = None,
) -> tuple[str, dict[str, int]]:
    base_dir = (asset_base_dir or html_path.parent).resolve()

    with tempfile.TemporaryDirectory(prefix="magic-page-assets-") as tmp_name:
        temp_dir = Path(tmp_name)
        url_map: dict[str, str] = {}
        counts = {"local": 0, "data": 0, "external": 0, "css": 0, "js": 0}

        uploadable = [
            ref for ref in collect_resource_refs(html)
            if ref.strip().startswith("data:") or is_http_ref(ref) or resolve_asset(html_path, ref, base_dir=base_dir)
        ]
        workers = max(1, min(MAX_UPLOAD_WORKERS, int(upload_workers or 1)))
        staged_by_ref: dict[str, tuple[dict[str, str] | None, str]] = {}
        if workers == 1:
            for ref in uploadable:
                staged_by_ref[ref] = stage_ref_uncached(
                    ref,
                    html_path=html_path,
                    base_dir=base_dir,
                    base_url=base_url,
                    key_prefix=key_prefix,
                    temp_dir=temp_dir,
                )
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                future_to_ref = {
                    pool.submit(
                        stage_ref_uncached,
                        ref,
                        html_path=html_path,
                        base_dir=base_dir,
                        base_url=base_url,
                        key_prefix=key_prefix,
                        temp_dir=temp_dir,
                    ): ref
                    for ref in uploadable
                }
                for future in as_completed(future_to_ref):
                    ref = future_to_ref[future]
                    staged_by_ref[ref] = future.result()

        specs: list[dict[str, str]] = []
        ref_to_id: dict[str, str] = {}
        # Iterate in source order even when staging ran concurrently so the
        # manifest and diagnostics are deterministic.
        for ref in uploadable:
            spec, kind = staged_by_ref.get(ref, (None, ""))
            if spec is None:
                continue
            specs.append(spec)
            ref_to_id[ref] = spec["id"]
            counts[kind] += 1
        if upload_session is not None:
            uploaded = upload_session.upload(specs, temp_dir=temp_dir)
        else:
            uploaded = upload_batch(
                specs,
                uploader=uploader,
                base_url=base_url,
                workers=workers,
                temp_dir=temp_dir,
                legacy_uploader=legacy_uploader,
            )
        for ref, item_id in ref_to_id.items():
            url_map[ref] = uploaded[item_id]

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

        html = sub_outside_script_blocks(URL_RE, replace_url, html)
        html = sub_outside_script_blocks(IMPORT_RE, replace_import, html)
        html = RESOURCE_ATTR_RE.sub(replace_resource_attr, html)
        html = SRCSET_ATTR_RE.sub(replace_srcset, html)

    return html, counts


def rewrite_refs(
    html: str,
    html_path: Path,
    *,
    uploader: Path,
    base_url: str,
    key_prefix: str,
    asset_base_dir: Path | None = None,
    upload_workers: int = DEFAULT_UPLOAD_WORKERS,
    legacy_uploader: bool = False,
) -> tuple[str, int, int, int]:
    """Compatibility wrapper for callers that only rewrite resource refs."""
    rewritten, counts = _rewrite_refs_batched(
        html,
        html_path,
        uploader=uploader,
        base_url=base_url,
        key_prefix=key_prefix,
        asset_base_dir=asset_base_dir,
        upload_workers=upload_workers,
        legacy_uploader=legacy_uploader,
    )
    return rewritten, counts["local"], counts["data"], counts["external"]


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


def externalize_inline_blocks_batched(
    html: str,
    *,
    uploader: Path,
    base_url: str,
    key_prefix: str,
    upload_workers: int = DEFAULT_UPLOAD_WORKERS,
    legacy_uploader: bool = False,
    upload_session: BatchUploadSession | None = None,
) -> tuple[str, int, int]:
    """Externalize already-resource-rewritten CSS/JS in one bounded batch."""
    css_count = 0
    js_count = 0
    with tempfile.TemporaryDirectory(prefix="magic-page-code-") as tmp_name:
        temp_dir = Path(tmp_name)
        specs_by_token: dict[tuple[str, str], dict[str, str]] = {}

        def register(folder: str, suffix: str, text: str) -> str:
            payload = text.encode("utf-8")
            digest = hashlib.sha256(payload).hexdigest()
            token = (folder, digest)
            if token not in specs_by_token:
                staged = temp_dir / f"{folder}-{digest[:16]}{suffix}"
                staged.write_bytes(payload)
                key = "/".join(
                    part
                    for part in (
                        safe_key_part(key_prefix),
                        f"{folder}/{digest[:16]}{suffix}",
                    )
                    if part
                )
                specs_by_token[token] = _upload_spec(
                    staged,
                    key=key,
                    base_url=base_url,
                )
            return specs_by_token[token]["id"]

        for match in STYLE_BLOCK_RE.finditer(html):
            _attrs, css = match.groups()
            if css.strip():
                register("css", ".css", css)
                css_count += 1
        for match in SCRIPT_BLOCK_RE.finditer(html):
            attrs, js = match.groups()
            if js.strip() and script_type_allows_externalize(attrs):
                register("js", ".js", js)
                js_count += 1

        specs = list(specs_by_token.values())
        if upload_session is not None:
            uploaded = upload_session.upload(specs, temp_dir=temp_dir)
        else:
            uploaded = upload_batch(
                specs,
                uploader=uploader,
                base_url=base_url,
                workers=upload_workers,
                temp_dir=temp_dir,
                legacy_uploader=legacy_uploader,
            )

        def replace_style(match: re.Match[str]) -> str:
            _attrs, css = match.groups()
            if not css.strip():
                return match.group(0)
            digest = hashlib.sha256(css.encode("utf-8")).hexdigest()
            item_id = specs_by_token[("css", digest)]["id"]
            return (
                '<link rel="stylesheet" href="'
                + html_lib.escape(uploaded[item_id], quote=True)
                + '">'
            )

        def replace_script(match: re.Match[str]) -> str:
            attrs, js = match.groups()
            if not js.strip() or not script_type_allows_externalize(attrs):
                return match.group(0)
            digest = hashlib.sha256(js.encode("utf-8")).hexdigest()
            item_id = specs_by_token[("js", digest)]["id"]
            clean_attrs = attrs.rstrip()
            url = html_lib.escape(uploaded[item_id], quote=True)
            if clean_attrs:
                return f'<script{clean_attrs} src="{url}"></script>'
            return f'<script src="{url}"></script>'

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
    parser.add_argument(
        "--legacy-uploader",
        action="store_true",
        help=(
            "explicitly allow an older custom uploader without the JSON batch "
            "protocol (spawns one bounded process per unique asset)"
        ),
    )
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
        css_uploaded = 0
        js_uploaded = 0
        with tempfile.TemporaryDirectory(prefix="magic-upload-session-") as session_tmp:
            with BatchUploadSession(
                uploader=uploader,
                base_url=args.base_url,
                workers=args.upload_workers,
                temp_dir=Path(session_tmp),
                legacy_uploader=args.legacy_uploader,
            ) as upload_session:
                # Resources first, so CSS that contains local/data/remote url()
                # is rewritten before its final bytes are hashed and uploaded.
                rewritten, counts = _rewrite_refs_batched(
                    html,
                    src,
                    uploader=uploader,
                    base_url=args.base_url,
                    key_prefix=args.key_prefix,
                    asset_base_dir=Path(args.asset_base_dir).expanduser().resolve() if args.asset_base_dir else None,
                    upload_workers=args.upload_workers,
                    legacy_uploader=args.legacy_uploader,
                    upload_session=upload_session,
                )
                if not args.keep_inline_code:
                    rewritten, css_uploaded, js_uploaded = externalize_inline_blocks_batched(
                        rewritten,
                        uploader=uploader,
                        base_url=args.base_url,
                        key_prefix=args.key_prefix,
                        upload_workers=args.upload_workers,
                        legacy_uploader=args.legacy_uploader,
                        upload_session=upload_session,
                    )
        local_uploaded = counts["local"]
        data_uploaded = counts["data"]
        external_uploaded = counts["external"]
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
    print(f"  uploader mode: {'legacy-explicit' if args.legacy_uploader else 'batch-ndjson'}")
    print(f"  key prefix   : {shlex.quote(args.key_prefix)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
