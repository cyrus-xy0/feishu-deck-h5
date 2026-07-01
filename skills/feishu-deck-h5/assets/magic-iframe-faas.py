#!/usr/bin/env python3
"""Rewrite local HTML iframes for Magic Page publishing.

TOS is a good place for media, fonts, JS, and processed HTML bytes, but TOS
HTML responses may carry attachment-like delivery headers. A deck iframe that
points directly at such a URL can render blank or download. Publishing each
child HTML as a nested Magic HTML Box also adds a second sandbox layer that can
break demos reading storage.

This helper prepares every local ``<iframe src="*.html">`` as:

  child HTML -> child assets hosted on TOS -> child HTML uploaded to TOS
  -> one Magic FaaS proxy returns that HTML as text/html
  -> parent iframe src becomes /api/faas/<record_id>?p=<slug>
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen


DEFAULT_MAGIC_BASE_URL = "https://magic.solutionsuite.cn"
TOKEN_FILES = (
    Path.home() / ".magic-token",
    Path.cwd() / ".magic-token",
    Path(__file__).resolve().parent / ".magic-token",
)
INLINE_ASSETS = Path(__file__).resolve().parent / "inline-assets.py"
MAGIC_PAGE_ASSETS = Path(__file__).resolve().parent / "magic-page-assets.py"
IFRAME_RE = re.compile(
    r"(<iframe\b[^>]*?\bsrc\s*=\s*)([\"'])(?P<src>.*?)(\2)(?P<tail>[^>]*>)",
    re.I | re.S,
)


def normalize_base_url(value: str) -> str:
    raw = (value or DEFAULT_MAGIC_BASE_URL).strip().rstrip("/")
    if not raw:
        return DEFAULT_MAGIC_BASE_URL
    return raw if re.match(r"^https?://", raw, re.I) else "https://" + raw


def safe_key_part(value: str) -> str:
    value = value.replace("\\", "/").strip("/")
    return re.sub(r"[^A-Za-z0-9._/-]+", "-", value)


def safe_slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-_").lower()
    return slug[:48] or fallback


def unique_page_slug(iframe_path: Path, index: int, used: set[str]) -> str:
    stem_slug = safe_slug(iframe_path.stem, f"iframe-{index:02d}")
    parent_slug = safe_slug(iframe_path.parent.name, "")
    candidates = [stem_slug]
    if parent_slug:
        candidates.append(safe_slug(f"{parent_slug}-{iframe_path.stem}", stem_slug))
    for candidate in candidates:
        if candidate not in used:
            used.add(candidate)
            return candidate
    counter = 2
    while True:
        candidate = safe_slug(f"{parent_slug or stem_slug}-{iframe_path.stem}-{counter}", f"iframe-{index:02d}-{counter}")
        if candidate not in used:
            used.add(candidate)
            return candidate
        counter += 1


def strip_ref(ref: str) -> str:
    raw = html_lib.unescape(ref.strip())
    return unquote(raw.split("#", 1)[0].split("?", 1)[0])


def is_remote_or_nonfile(ref: str) -> bool:
    raw = ref.strip().lower()
    if not raw or raw.startswith("#"):
        return True
    return bool(re.match(r"^(?:[a-z][a-z0-9+.-]*:|//)", raw))


def resolve_local_iframe(src: str, base_dir: Path) -> Optional[Path]:
    if is_remote_or_nonfile(src):
        return None
    raw = strip_ref(src)
    if not raw:
        return None
    suffix = Path(urlparse(raw).path).suffix.lower()
    if suffix not in {".html", ".htm"}:
        return None
    candidate = (base_dir / raw.lstrip("/")).resolve()
    return candidate if candidate.is_file() else None


def read_token() -> str:
    if os.environ.get("MAGIC_TOKEN", "").strip():
        return os.environ["MAGIC_TOKEN"].strip()
    for path in TOKEN_FILES:
        try:
            if path.exists():
                token = path.read_text(encoding="utf-8", errors="ignore").strip()
                if token:
                    return token
        except OSError:
            continue
    raise RuntimeError("Magic token missing. Set MAGIC_TOKEN or create ~/.magic-token.")


def subprocess_json_or_text(cmd: List[str], cwd: Path) -> Tuple[str, str]:
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "unknown error"
        raise RuntimeError(f"command failed: {' '.join(cmd)}\n{detail}")
    return proc.stdout.strip(), proc.stderr.strip()


def upload_file(asset: Path, *, uploader: Path, base_url: str, key: str, content_type: str = "") -> str:
    cmd = ["node", str(uploader), str(asset), "--key", key, "--base-url", base_url, "-q"]
    if content_type:
        cmd += ["--content-type", content_type]
    stdout, _stderr = subprocess_json_or_text(cmd, cwd=Path.cwd())
    url = stdout.splitlines()[-1].strip()
    if not url.startswith(("http://", "https://")):
        raise RuntimeError(f"uploader returned non-URL for {asset}: {url!r}")
    return url


def prepare_child_html(
    iframe_path: Path,
    *,
    index: int,
    work_dir: Path,
    uploader: Path,
    base_url: str,
    key_prefix: str,
    upload_workers: int,
) -> Path:
    child_dir = work_dir / "children"
    child_dir.mkdir(parents=True, exist_ok=True)
    stem = safe_slug(iframe_path.stem, f"iframe-{index:02d}")
    inlined = child_dir / f"{index:02d}-{stem}-inline.html"
    ready = child_dir / f"{index:02d}-{stem}-ready.html"
    subprocess_json_or_text(
        [
            sys.executable,
            str(INLINE_ASSETS),
            str(iframe_path),
            "--out",
            str(inlined),
            "--no-image-inline",
        ],
        cwd=Path.cwd(),
    )
    subprocess_json_or_text(
        [
            sys.executable,
            str(MAGIC_PAGE_ASSETS),
            str(inlined),
            "--out",
            str(ready),
            "--uploader",
            str(uploader),
            "--base-url",
            base_url,
            "--key-prefix",
            f"{key_prefix}/iframe-assets/{index:02d}-{stem}",
            "--asset-base-dir",
            str(iframe_path.parent),
            "--keep-inline-code",
            "--upload-workers",
            str(upload_workers),
        ],
        cwd=Path.cwd(),
    )
    return ready


def make_faas_code(pages: Dict[str, str]) -> str:
    return (
        "const PAGES = "
        + json.dumps(pages, ensure_ascii=False, indent=2)
        + """;

module.exports = async function (request, context) {
  try {
    const requestUrl = new URL(request.url);
    const page = requestUrl.searchParams.get("p") || "index";
    const upstream = PAGES[page];
    if (!upstream) {
      return new Response("Not found", {
        status: 404,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }
    const response = await fetch(upstream, { headers: { "Accept": "text/html,*/*" } });
    if (!response.ok) {
      return new Response("Upstream error: " + response.status, {
        status: 502,
        headers: { "Content-Type": "text/plain; charset=utf-8" },
      });
    }
    const body = await response.text();
    return new Response(body, {
      status: 200,
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "public, max-age=300",
      },
    });
  } catch (error) {
    return new Response(String(error && error.message || error), {
      status: 500,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  }
};
"""
    )


def publish_faas_api(*, code: str, name: str, record_id: str, base_url: str, dry_run: bool) -> Dict[str, Any]:
    if dry_run:
        digest = hashlib.sha1((name + code).encode("utf-8")).hexdigest()[:12]
        rec = record_id or f"dryiframe{digest}"
        return {
            "record_id": rec,
            "faas_url": f"{base_url}/api/faas/{rec}",
            "dry_run": True,
        }
    payload: Dict[str, Any] = {"code": code, "name": name}
    if record_id:
        payload["id"] = record_id
    request = Request(
        f"{base_url}/api/faas",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {read_token()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=60) as response:
        text = response.read().decode("utf-8", errors="replace")
    result = json.loads(text) if text else {}
    if result.get("code") != 0:
        raise RuntimeError(f"FaaS publish failed: {result.get('msg') or result}")
    data = result.get("data") or {}
    rec = str(data.get("record_id") or data.get("id") or record_id or "")
    if not rec:
        raise RuntimeError(f"FaaS publish returned no record id: {result}")
    faas_url = data.get("faas_url") or f"/api/faas/{rec}"
    if str(faas_url).startswith("http"):
        full_url = str(faas_url)
    else:
        full_url = base_url + "/" + str(faas_url).lstrip("/")
    return {"record_id": rec, "faas_url": full_url, "dry_run": False, "api_result": result}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html")
    parser.add_argument("--out", required=True)
    parser.add_argument("--uploader", required=True)
    parser.add_argument("--base-url", default=DEFAULT_MAGIC_BASE_URL)
    parser.add_argument("--key-prefix", required=True)
    parser.add_argument("--asset-base-dir")
    parser.add_argument("--report", required=True)
    parser.add_argument("--faas-name", default="feishu_deck_iframe_html_proxy")
    parser.add_argument("--faas-record-id", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--upload-workers", type=int, default=4)
    args = parser.parse_args(argv or sys.argv[1:])

    src = Path(args.html).resolve()
    dst = Path(args.out).resolve()
    uploader = Path(args.uploader).expanduser().resolve()
    base_dir = Path(args.asset_base_dir).expanduser().resolve() if args.asset_base_dir else src.parent
    report_path = Path(args.report).resolve()
    base_url = normalize_base_url(args.base_url)

    html = src.read_text(encoding="utf-8", errors="replace")
    matches: List[Tuple[re.Match[str], Path]] = []
    seen: Dict[Path, str] = {}
    for match in IFRAME_RE.finditer(html):
        iframe_path = resolve_local_iframe(match.group("src"), base_dir)
        if iframe_path:
            matches.append((match, iframe_path))
            seen.setdefault(iframe_path, "")

    if not matches:
        dst.write_text(html, encoding="utf-8")
        report = {"ok": True, "rewritten": 0, "iframes": [], "reason": "no local HTML iframe"}
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    work_dir = report_path.parent / "magic-iframe-faas-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        pages: Dict[str, str] = {}
        iframe_rows: List[Dict[str, Any]] = []
        path_to_faas_url: Dict[Path, str] = {}

        used_slugs: set[str] = set()
        for index, iframe_path in enumerate(seen.keys(), 1):
            slug = unique_page_slug(iframe_path, index, used_slugs)
            ready = prepare_child_html(
                iframe_path,
                index=index,
                work_dir=work_dir,
                uploader=uploader,
                base_url=base_url,
                key_prefix=args.key_prefix,
                upload_workers=args.upload_workers,
            )
            digest = hashlib.sha256(ready.read_bytes()).hexdigest()[:16]
            key = "/".join(
                part
                for part in (
                    safe_key_part(args.key_prefix),
                    f"iframe-html/{index:02d}-{slug}-{digest}.html",
                )
                if part
            )
            tos_url = upload_file(
                ready,
                uploader=uploader,
                base_url=base_url,
                key=key,
                content_type="text/html; charset=utf-8",
            )
            pages[slug] = tos_url
            iframe_rows.append(
                {
                    "slug": slug,
                    "source": str(iframe_path),
                    "prepared_html": str(ready),
                    "tos_url": tos_url,
                    "tos_key": key,
                    "bytes": ready.stat().st_size,
                }
            )
            seen[iframe_path] = slug

        faas_code = make_faas_code(pages)
        faas = publish_faas_api(
            code=faas_code,
            name=args.faas_name,
            record_id=args.faas_record_id,
            base_url=base_url,
            dry_run=args.dry_run,
        )
        for iframe_path, slug in seen.items():
            path_to_faas_url[iframe_path] = f"{faas['faas_url']}?p={slug}"

        pieces: List[str] = []
        last = 0
        rewritten = 0
        for match, iframe_path in matches:
            pieces.append(html[last:match.start()])
            url = html_lib.escape(path_to_faas_url[iframe_path], quote=True)
            pieces.append(f"{match.group(1)}{match.group(2)}{url}{match.group(2)}{match.group('tail')}")
            last = match.end()
            rewritten += 1
        pieces.append(html[last:])
        dst.write_text("".join(pieces), encoding="utf-8")

        report = {
            "ok": True,
            "rewritten": rewritten,
            "faas": faas,
            "iframes": iframe_rows,
            "output": str(dst),
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        report = {"ok": False, "reason": str(exc)}
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
