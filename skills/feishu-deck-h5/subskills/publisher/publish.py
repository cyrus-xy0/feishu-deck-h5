#!/usr/bin/env python3
"""Publish a confirmed feishu-deck-h5 HTML artifact.

The publisher skill owns the last mile after the user has confirmed a rendered
HTML deck. It publishes the confirmed HTML to Feishu/Miaobi Magic Page.

Library ingestion is intentionally out of scope. Use subskills/importer/ingest.py
to push a finished HTML artifact into FuQiang/feishu-slide-library.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
SELF_CHECK = Path(__file__).resolve().parent / "self_check.py"
RUNS = REPO / "runs"
MAGIC_PAGE_ASSETS = REPO / "assets/magic-page-assets.py"
MAGIC_PAGE_PREFLIGHT = REPO / "assets/magic-page-preflight.py"
MAGIC_IFRAME_FAAS = REPO / "assets/magic-iframe-faas.py"
MAGIC_ASSET_FAAS = REPO / "assets/magic-asset-faas.py"
INLINE_ASSETS = REPO / "assets/inline-assets.py"
DEFAULT_MAGIC_PAGE_PUBLISHER = REPO / "assets/magic-page-publish.js"
DEFAULT_MAGIC_ASSET_UPLOADER = REPO / "assets/magic-upload.js"
DEFAULT_MAGIC_ASSET_CACHE = RUNS / "publisher" / ".magic-asset-cache-v1.json"
DEFAULT_MAGIC_BASE_URL = "https://magic.solutionsuite.cn"
DEFAULT_MAGIC_MAX_HTML_CHARS = 900_000
DEFAULT_PUBLISH_TIME_BUDGET_SECONDS = 600
MAGIC_TOKEN_FILES = (
    Path.home() / ".magic-token",
    REPO / ".magic-token",
    REPO / "assets/.magic-token",
)
URL_RE = re.compile(r"url\(\s*(?:\"([^\"]*)\"|'([^']*)'|([^)]*))\s*\)", re.I)
IMPORT_RE = re.compile(r"@import\s+(?:url\(\s*)?(?:\"([^\"]*)\"|'([^']*)'|([^;'\")\s]+))(?:\s*\))?", re.I)
# NB: `(?<![\w-])` (not a bare `\b`) so a hyphenated attr name like data-src /
# data-href / data-poster is NOT misdetected as the real src/href/poster — a
# `\b` matches the boundary between '-' and 'src', falsely capturing data-* attrs.
RESOURCE_ATTR_RE = re.compile(r"<(?P<tag>[A-Za-z][\w:-]*)\b[^>]*?(?<![\w-])(?P<attr>src|href|poster)\s*=\s*([\"'])(.*?)\3", re.I | re.S)
SRCSET_ATTR_RE = re.compile(r"\bsrcset\s*=\s*([\"'])(.*?)\1", re.I | re.S)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def repo_rel(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO).as_posix()
    except ValueError:
        return resolved.as_posix()


def slugify(value: str, fallback: str = "deck") -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    return slug or fallback


def stable_publisher_task_id(html_path: Path) -> str:
    """Stable per-source workspace so retries can reuse cache/FaaS/app state."""
    resolved = html_path.expanduser().resolve()
    path_id = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
    return f"publisher/{slugify(resolved.stem, 'html')}-{path_id}"


def optional_path(value: str) -> Path | None:
    raw = str(value or "").strip()
    return Path(raw) if raw else None


def magic_token_available() -> bool:
    if os.environ.get("MAGIC_TOKEN", "").strip():
        return True
    for path in MAGIC_TOKEN_FILES:
        try:
            if path.exists() and path.read_text(encoding="utf-8", errors="ignore").strip():
                return True
        except OSError:
            continue
    return False


def missing_magic_token_message() -> str:
    return (
        "Magic token missing. Ask the user to provide a Magic token, then set it "
        "as MAGIC_TOKEN for this run or save it to ~/.magic-token before publishing."
    )


def normalize_list(values: list[str] | None, default: list[str]) -> list[str]:
    out: list[str] = []
    for value in values or []:
        for part in str(value).replace("，", ",").replace("、", ",").split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out or default


def task_dirs(task_id: str) -> tuple[Path, Path]:
    task_dir = RUNS / task_id
    output_dir = task_dir / "output"
    if not output_dir.exists():
        raise SystemExit(f"publisher: output directory not found for task {task_id}")
    return task_dir, output_dir


def resolve_html(args: argparse.Namespace, output_dir: Path | None) -> Path | None:
    if args.html:
        html_path = args.html.expanduser().resolve()
    elif output_dir and (output_dir / "index.html").exists():
        html_path = (output_dir / "index.html").resolve()
    else:
        return None
    if not html_path.exists() or not html_path.is_file():
        raise SystemExit(f"publisher: confirmed HTML not found: {html_path}")
    if html_path.suffix.lower() not in {".html", ".htm"}:
        raise SystemExit(f"publisher: expected .html/.htm artifact, got {html_path}")
    return html_path


# Default wall-clock bound for child steps. The network-bound `node
# magic-page-publish.js` upload gets a generous timeout so a stalled connection
# cannot hang the whole publish with no bound (subskill-5).
DEFAULT_SUBPROCESS_TIMEOUT = 300
NETWORK_SUBPROCESS_TIMEOUT = 600
STAGE_EVENTS: list[dict[str, Any]] = []
PUBLISH_DEADLINE: float | None = None


def subprocess_record(
    cmd: list[str],
    *,
    cwd: Path,
    log_path: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = DEFAULT_SUBPROCESS_TIMEOUT,
) -> dict[str, Any]:
    started = time.monotonic()
    effective_timeout = timeout
    if PUBLISH_DEADLINE is not None:
        remaining = PUBLISH_DEADLINE - started
        if remaining <= 0:
            result = {
                "cmd": cmd,
                "ok": False,
                "returncode": 124,
                "stdout": "",
                "stderr": "publish time budget exhausted before stage start",
                "json": None,
                "duration_seconds": 0.0,
            }
            STAGE_EVENTS.append({
                "stage": Path(cmd[1]).name if len(cmd) > 1 else Path(cmd[0]).name,
                "ok": False,
                "duration_seconds": 0.0,
                "reason": "time-budget-exhausted",
            })
            return result
        remaining_seconds = max(1, int(remaining))
        effective_timeout = remaining_seconds if timeout is None else min(timeout, remaining_seconds)
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, text=True, capture_output=True, env=env, timeout=effective_timeout
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\nTIMEOUT after {effective_timeout}s: {' '.join(cmd)}"
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="ignore")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="ignore")
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(
                "$ " + " ".join(cmd) + "\n\nSTDOUT\n" + stdout + "\nSTDERR\n" + stderr,
                encoding="utf-8",
            )
        result = {
            "cmd": cmd,
            "ok": False,
            "returncode": 124,
            "stdout": stdout.strip(),
            "stderr": stderr.strip(),
            "json": None,
            "duration_seconds": round(time.monotonic() - started, 3),
        }
        STAGE_EVENTS.append({
            "stage": Path(cmd[1]).name if len(cmd) > 1 else Path(cmd[0]).name,
            "ok": False,
            "duration_seconds": result["duration_seconds"],
        })
        return result
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "$ " + " ".join(cmd) + "\n\nSTDOUT\n" + proc.stdout + "\nSTDERR\n" + proc.stderr,
            encoding="utf-8",
        )
    parsed: Any = None
    if proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
        except json.JSONDecodeError:
            parsed = None
    result = {
        "cmd": cmd,
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "json": parsed,
        "duration_seconds": round(time.monotonic() - started, 3),
    }
    STAGE_EVENTS.append({
        "stage": Path(cmd[1]).name if len(cmd) > 1 else Path(cmd[0]).name,
        "ok": result["ok"],
        "duration_seconds": result["duration_seconds"],
    })
    return result


def parse_magic_stdout(stdout: str) -> dict[str, Any]:
    try:
        payload = json.loads(stdout)
        app_url = str(payload.get("app_url") or payload.get("url") or "")
        app_id = str(payload.get("app_id") or payload.get("id") or "")
        urls = payload.get("urls") if isinstance(payload.get("urls"), list) else []
        return {"app_url": app_url, "app_id": app_id, "urls": urls}
    except json.JSONDecodeError:
        pass
    result: dict[str, Any] = {"app_url": "", "app_id": "", "urls": {}}
    urls: dict[str, str] = {}
    label_to_key = {
        "Independent Page": "html_box",
        "Dashboard Plugin": "dashboard",
        "Feishu Sidebar": "panel",
        "Feishu Tab": "tab",
    }
    for line in stdout.splitlines():
        if ":" not in line:
            continue
        label, value = line.split(":", 1)
        label = label.strip()
        value = value.strip()
        if not value:
            continue
        if label == "App ID":
            result["app_id"] = value
        elif label in label_to_key:
            key = label_to_key[label]
            urls[key] = value
            if label == "Independent Page":
                result["app_url"] = value
    if result["app_url"] or result["app_id"]:
        result["urls"] = urls
        return result
    urls = re.findall(r"https?://\S+", stdout)
    app_url = urls[0] if urls else ""
    return {"app_url": app_url, "app_id": "", "urls": urls}


# Any data: payload left inline after asset prep is a bug: asset prep is supposed
# to upload every data: resource to TOS (the contract is "no data: in the published
# bytes"). A residual one both bloats the request body past Magic Page's limit and
# defeats CDN delivery. (Was image-only; broadened to ANY data: kind after a
# published deck repeatedly stalled on a `data:video` the old image-only check let
# through.) The mime is surfaced in the failure message.
RESIDUAL_DATA_RE = re.compile(r"data:([A-Za-z0-9.+-]+/[A-Za-z0-9.+-]*)", re.I)
# Regions whose contents must NOT feed the CSS url()/@import dependency scan:
# <script> blocks (JS strings/comments like url(), URL(), location.href,
# createObjectURL were false-flagged as unhosted resources) and CSS comments. HTML
# comments are stripped for BOTH the url() scan and the attribute scan (a
# commented-out <img>/<link> does not load). Real <script src="..."> /
# <link href="..."> deps survive the attribute scan because only the url() scan
# strips <script> blocks; the attribute scan runs on comment-stripped-but-otherwise
# intact html.
_SCRIPT_BLOCK_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.I | re.S)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def residual_data_payloads(html_path: Path) -> list[str]:
    try:
        html = html_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    kinds: list[str] = []
    seen: set[str] = set()
    for m in RESIDUAL_DATA_RE.finditer(html):
        kind = m.group(0).split(",", 1)[0][:40].lower()
        if kind not in seen:
            seen.add(kind)
            kinds.append(kind)
    return kinds


def _strip_html_comments(html: str) -> str:
    """Blank out HTML comments — a commented-out <img>/<link>/<script> never loads,
    so it must not be flagged as an unhosted dependency. Used as the base for BOTH
    the attribute scan and the url() scan."""
    return _HTML_COMMENT_RE.sub(" ", html)


def _strip_script_and_css_comments(html: str) -> str:
    """On top of comment-stripping, blank out <script> blocks and CSS comments so
    the url()/@import scan only sees real stylesheet references — not JS that merely
    mentions url(), URL(), location.href, createObjectURL, etc."""
    return _CSS_COMMENT_RE.sub(" ", _SCRIPT_BLOCK_RE.sub(" ", html))


def is_dependency_ref(ref: str) -> bool:
    raw = ref.strip()
    if not raw or raw.startswith("#"):
        return False
    lowered = raw.lower()
    # data: is self-contained (no external fetch), so it is NOT an "unhosted
    # dependency" — its inline-payload problem is owned by residual_data_payloads,
    # which reports it with an accurate message. Excluding it here keeps the two
    # checks non-overlapping (a data: ref was previously double-flagged as a
    # missing runtime dependency).
    return not lowered.startswith(("javascript:", "mailto:", "tel:", "about:", "blob:", "data:"))


def is_unhosted_dependency(ref: str) -> bool:
    raw = ref.strip()
    if not is_dependency_ref(raw):
        return False
    lowered = raw.lower()
    if lowered.startswith(("http://", "https://", "//")):
        return False
    return True


def remaining_unhosted_dependencies(html_path: Path) -> list[str]:
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    refs: list[str] = []
    attr_scan = _strip_html_comments(html)            # keeps <script src>/<link href>
    css_scan = _strip_script_and_css_comments(attr_scan)  # also drops JS + CSS comments
    for regex in (URL_RE, IMPORT_RE):
        for match in regex.finditer(css_scan):
            ref = next((group for group in match.groups() if group), "").strip()
            if is_unhosted_dependency(ref):
                refs.append(ref)
    for match in RESOURCE_ATTR_RE.finditer(attr_scan):
        tag = match.group("tag").lower()
        attr = match.group("attr").lower()
        ref = match.group(4).strip()
        if attr == "href" and tag not in {"link", "image"}:
            continue
        if is_unhosted_dependency(ref):
            refs.append(ref)
    for match in SRCSET_ATTR_RE.finditer(attr_scan):
        for item in match.group(2).split(","):
            ref = item.strip().split()[0] if item.strip() else ""
            if is_unhosted_dependency(ref):
                refs.append(ref)
    out: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out


def audit_publish_integrity(html_path: Path, output_dir: Path) -> dict[str, Any]:
    """Lightweight publish gate: only block references that cannot survive Magic Page.

    This intentionally does not run deck-validator/check-only visual or design
    rules. The publish path follows the slide-library resource-only stance:
    fail on unresolved runtime dependencies and residual inline payloads, then
    rely on post-publish self-check for the final hosted URL.
    """
    residual = residual_data_payloads(html_path)
    unhosted = remaining_unhosted_dependencies(html_path)
    reasons: list[str] = []
    if residual:
        reasons.append(
            "inline data: payloads remain after asset preparation: " + ", ".join(residual)
        )
    if unhosted:
        sample = ", ".join(unhosted[:8])
        more = f" (+{len(unhosted) - 8} more)" if len(unhosted) > 8 else ""
        reasons.append(f"unhosted runtime dependencies remain: {sample}{more}")
    ok = not reasons
    report_path = output_dir / "PUBLISH_INTEGRITY_REPORT.md"
    lines = [
        "# Publish Integrity Report",
        "",
        f"- ok: {ok}",
        f"- html: {repo_rel(html_path)}",
        f"- residual_data_payloads: {len(residual)}",
        f"- unhosted_dependencies: {len(unhosted)}",
        "",
    ]
    if residual:
        lines.extend(["## Residual data payloads", ""])
        lines.extend(f"- `{item}`" for item in residual)
        lines.append("")
    if unhosted:
        lines.extend(["## Unhosted dependencies", ""])
        lines.extend(f"- `{item}`" for item in unhosted)
        lines.append("")
    if not residual and not unhosted:
        lines.append("No unresolved local/data runtime references found in the publish-bound HTML.")
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {
        "ok": ok,
        "html": repo_rel(html_path),
        "report": repo_rel(report_path),
        "residual_data_payloads": residual,
        "unhosted_dependencies": unhosted,
        "reason": "; ".join(reasons),
    }


def html_char_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="ignore"))


def write_publish_size_report(output_dir: Path, payload: dict[str, Any]) -> None:
    report_path = output_dir / "PUBLISH_SIZE_REPORT.md"
    lines = [
        "# Publish Size Report",
        "",
        f"- ok: {payload.get('ok')}",
        f"- max_html_chars: {payload.get('max_html_chars')}",
        f"- final_html: {payload.get('final_html')}",
        f"- final_chars: {payload.get('final_chars')}",
        f"- auto_externalized_inline_code: {payload.get('auto_externalized_inline_code')}",
        "",
        "## Attempts",
        "",
    ]
    for attempt in payload.get("attempts") or []:
        lines.extend(
            [
                f"- mode: `{attempt.get('mode')}`",
                f"  html: `{attempt.get('html')}`",
                f"  chars: {attempt.get('chars')}",
                f"  ok: {attempt.get('ok')}",
            ]
        )
    if payload.get("reason"):
        lines.extend(["", f"reason: {payload.get('reason')}"])
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _clean_magic_app_id(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return raw.removeprefix("rec")


def _publication_from_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    publication = payload.get("publication")
    return publication if isinstance(publication, dict) else payload


def resolve_existing_magic_app_id(output_dir: Path, args: argparse.Namespace) -> str:
    explicit = _clean_magic_app_id(args.magic_page_app_id or os.environ.get("MAGIC_PAGE_APP_ID", ""))
    if explicit:
        return explicit
    for name in ("magic-page-publish.json", "cloud-publish.json", "publish-manifest.json"):
        path = output_dir / name
        if not path.exists():
            continue
        try:
            payload = _publication_from_manifest(read_json(path))
        except Exception:
            continue
        app_id = _clean_magic_app_id(payload.get("app_id") or payload.get("id"))
        if app_id:
            return app_id
        app_url = str(payload.get("app_url") or payload.get("url") or "")
        match = re.search(r"/html-box/([^/?#]+)", app_url)
        if match:
            return _clean_magic_app_id(match.group(1))
    return ""


def make_magic_assets_cmd(
    *,
    package_source: Path,
    packaged: Path,
    uploader: Path,
    base_url: str,
    task_id: str,
    source_html: Path,
    upload_workers: int,
    keep_inline_code: bool,
    legacy_uploader: bool = False,
    cache_manifest: Path | None = None,
) -> list[str]:
    cmd = [
        sys.executable,
        str(MAGIC_PAGE_ASSETS),
        str(package_source),
        "--out",
        str(packaged),
        "--uploader",
        str(uploader),
        "--base-url",
        base_url,
        "--key-prefix",
        f"feishu-deck-h5/{task_id}",
        "--asset-base-dir",
        str(source_html.parent),
        "--upload-workers",
        str(upload_workers),
    ]
    if keep_inline_code:
        cmd.append("--keep-inline-code")
    if legacy_uploader:
        cmd.append("--legacy-uploader")
    if cache_manifest:
        cmd += ["--cache-manifest", str(cache_manifest)]
    return cmd


def dry_run_asset_uploader(output_dir: Path) -> Path:
    """Return a local uploader shim that maps upload keys to deterministic URLs."""
    uploader = output_dir / "dry-run-magic-upload.js"
    uploader.write_text(
        r"""
const fs = require("fs");
const crypto = require("crypto");
const readline = require("readline");
const args = process.argv.slice(2);
const manifestIndex = args.indexOf("--batch-manifest");
const ndjson = args.includes("--batch-ndjson");
const baseIndex = args.indexOf("--base-url");
const baseRaw = String(baseIndex >= 0 ? args[baseIndex + 1] : "https://magic.solutionsuite.cn")
  .trim().replace(/\/+$/, "");
const base = /^https?:\/\//i.test(baseRaw) ? baseRaw : "https://" + baseRaw;
const cleanKey = (raw) => String(raw || "asset")
  .replace(/[^A-Za-z0-9._/-]+/g, "-").replace(/^\/+/, "");

function responseFor(request) {
  const items = request.items.map((item) => {
    const payload = fs.readFileSync(item.file);
    const sha256 = crypto.createHash("sha256").update(payload).digest("hex");
    const cacheKey = crypto.createHash("sha256")
      .update(base + "\0" + item.key + "\0" + sha256).digest("hex");
    if (sha256 !== item.sha256 || cacheKey !== item.cache_key || item.id !== cacheKey) {
      return {...item, ok: false, error: "dry-run manifest integrity mismatch"};
    }
    return {...item, ok: true, url: "https://dryrun.local/" + cleanKey(item.key)};
  });
  return {
    protocol: "magic-upload-batch/v1",
    request_id: request.request_id || "",
    ok: items.every((item) => item.ok),
    base_url: base,
    items
  };
}

async function main() {
  if (ndjson) {
    const rl = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
    for await (const line of rl) {
      if (!line.trim()) continue;
      process.stdout.write(JSON.stringify(responseFor(JSON.parse(line))) + "\n");
    }
    return;
  }
  if (manifestIndex >= 0) {
    const response = responseFor(JSON.parse(fs.readFileSync(args[manifestIndex + 1], "utf8")));
    process.stdout.write(JSON.stringify(response));
    process.exitCode = response.ok ? 0 : 1;
    return;
  }
  const keyIndex = args.indexOf("--key");
  const rawKey = keyIndex >= 0 ? args[keyIndex + 1] : (args[0] || "asset");
  process.stdout.write("https://dryrun.local/" + cleanKey(rawKey));
}
main().catch((error) => { console.error(error.message); process.exit(1); });
""".strip()
        + "\n",
        encoding="utf-8",
    )
    return uploader


def _run_magic_assets(
    *,
    package_source: Path,
    packaged: Path,
    uploader: Path,
    base_url: str,
    task_id: str,
    source_html: Path,
    upload_workers: int,
    keep_inline_code: bool,
    output_dir: Path,
    log_name: str,
    legacy_uploader: bool = False,
    cache_manifest: Path | None = None,
) -> dict[str, Any]:
    """Run one Magic asset-packaging pass.

    Keeping this at one choke point makes the performance contract testable:
    prediction passes use the deterministic dry-run uploader, then a live
    publish invokes the real uploader exactly once in the selected mode.
    """
    return subprocess_record(
        make_magic_assets_cmd(
            package_source=package_source,
            packaged=packaged,
            uploader=uploader,
            base_url=base_url,
            task_id=task_id,
            source_html=source_html,
            upload_workers=upload_workers,
            keep_inline_code=keep_inline_code,
            legacy_uploader=legacy_uploader,
            cache_manifest=cache_manifest,
        ),
        cwd=REPO,
        log_path=output_dir / log_name,
    )


def _load_magic_page_assets_module():
    spec = importlib.util.spec_from_file_location("publisher_magic_page_assets", MAGIC_PAGE_ASSETS)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load Magic asset helper: {MAGIC_PAGE_ASSETS}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_page_hashes(html: str) -> list[dict[str, Any]]:
    """Return stable page hashes for incremental post-publish verification."""
    marker = '<div class="slide-frame">'
    parts = html.split(marker)[1:]
    pages: list[dict[str, Any]] = []
    for index, part in enumerate(parts, 1):
        key_match = re.search(r'\bdata-slide-key=["\']([^"\']+)', part)
        key = key_match.group(1) if key_match else f"page-{index}"
        pages.append({
            "index": index,
            "key": key,
            "sha256": hashlib.sha256(part.encode("utf-8")).hexdigest(),
        })
    return pages


def select_incremental_self_check_pages(
    current_pages: list[dict[str, Any]],
    prior_pages: list[dict[str, Any]],
    *,
    leading_pages: int,
    max_pages: int,
) -> list[int]:
    """Select cover/last plus changed pages and their immediate neighbours."""
    count = len(current_pages)
    if count <= 0:
        return []
    if not prior_pages:
        return list(range(1, min(count, max(1, leading_pages)) + 1))

    prior_by_key = {str(row.get("key")): row for row in prior_pages}
    current_by_key = {str(row.get("key")): row for row in current_pages}
    changed: set[int] = set()
    for row in current_pages:
        prior = prior_by_key.get(str(row.get("key")))
        if not prior or prior.get("sha256") != row.get("sha256"):
            changed.add(int(row["index"]))
    for key, prior in prior_by_key.items():
        if key not in current_by_key:
            old_index = int(prior.get("index") or 1)
            changed.add(max(1, min(count, old_index)))

    selected: set[int] = {1, count}
    if not changed:
        return sorted(selected)
    for index in sorted(changed):
        selected.update({max(1, index - 1), index, min(count, index + 1)})
    ordered = sorted(selected)
    limit = max(2, int(max_pages or 5))
    if len(ordered) <= limit:
        return ordered
    # Preserve the bookends, then spend the remaining budget on changed pages
    # before their neighbours.
    priority = [1, count]
    priority.extend(index for index in sorted(changed) if index not in priority)
    priority.extend(index for index in ordered if index not in priority)
    return sorted(dict.fromkeys(priority[:limit]))


def freeze_publish_snapshot(
    *,
    package_source: Path,
    asset_base_dir: Path,
    source_html: Path,
    output_dir: Path,
) -> tuple[Path, dict[str, Any]]:
    """Copy the exact publish-bound HTML and local resource closure.

    The snapshot is immutable and content-addressed. Later edits to the live run
    cannot silently change bytes halfway through upload or force the publisher
    to chase a moving target.
    """
    module = _load_magic_page_assets_module()
    html = package_source.read_text(encoding="utf-8", errors="replace")
    rows: list[dict[str, Any]] = []
    replacements: dict[str, str] = {}
    for ref in module.collect_resource_refs(html):
        try:
            asset = module.resolve_asset(package_source, ref, base_dir=asset_base_dir)
        except Exception:
            asset = None
        if asset is None:
            continue
        resolved = asset.resolve()
        sha256 = _sha256_file(resolved)
        suffix = resolved.suffix.lower()[:16] or ".bin"
        snapshot_ref = f"assets/{sha256[:24]}{suffix}"
        replacements[ref] = snapshot_ref
        rows.append({
            "ref": ref,
            "source": str(resolved),
            "snapshot_ref": snapshot_ref,
            "sha256": sha256,
            "bytes": resolved.stat().st_size,
        })

    identity = hashlib.sha256(html.encode("utf-8"))
    for row in sorted(rows, key=lambda item: (item["ref"], item["sha256"])):
        identity.update(b"\0")
        identity.update(row["ref"].encode("utf-8"))
        identity.update(b"\0")
        identity.update(row["sha256"].encode("ascii"))
    snapshot_id = identity.hexdigest()[:20]
    snapshot_dir = output_dir / "publish-snapshots" / snapshot_id
    assets_dir = snapshot_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    for row in rows:
        target = snapshot_dir / row["snapshot_ref"]
        if not target.exists() or _sha256_file(target) != row["sha256"]:
            shutil.copy2(Path(row["source"]), target)

    frozen_html = html
    # Longest refs first avoids a short path replacing a prefix of another ref.
    for ref, snapshot_ref in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        frozen_html = frozen_html.replace(ref, snapshot_ref)
    snapshot_html = snapshot_dir / "index.html"
    snapshot_html.write_text(frozen_html, encoding="utf-8")
    manifest = {
        "version": 1,
        "snapshot_id": snapshot_id,
        "created_at": now_iso(),
        "source_html": str(source_html.resolve()),
        "package_source": str(package_source.resolve()),
        "snapshot_html": str(snapshot_html.resolve()),
        "html_sha256": hashlib.sha256(frozen_html.encode("utf-8")).hexdigest(),
        "assets": rows,
        "pages": extract_page_hashes(frozen_html),
    }
    write_json(snapshot_dir / "publish-snapshot.json", manifest)
    write_json(output_dir / "publish-snapshot.json", manifest)
    return snapshot_html, manifest


def publish_magic_page(
    *,
    html_path: Path,
    output_dir: Path,
    title: str,
    task_id: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    base_url = (args.magic_base_url or os.environ.get("MAGIC_BASE_URL") or DEFAULT_MAGIC_BASE_URL).rstrip("/")
    dry_run = bool(args.dry_run or args.magic_page_dry_run)

    if not dry_run and not magic_token_available():
        payload = magic_failure(missing_magic_token_message(), html_path, base_url, None)
        write_publish_reports(output_dir, payload)
        return payload

    working_html = html_path
    if not args.skip_magic_asset_prepare:
        uploader = (
            dry_run_asset_uploader(output_dir)
            if dry_run
            else args.magic_asset_uploader
            or optional_path(os.environ.get("FEISHU_DECK_H5_MAGIC_ASSET_UPLOADER", ""))
            or DEFAULT_MAGIC_ASSET_UPLOADER
        )

        # delivery-8: size pre-flight BEFORE upload. Magic Page hard-rejects any
        # single resource over the per-resource limit, and historically that was
        # discovered one resource at a time at the upload API — turning a single
        # publish into a serial fail/compress/re-validate/re-publish loop. Run the
        # audit once, up front: every oversized resource is reported together, and
        # (unless --no-compress-oversized) oversized videos are auto-compressed to
        # a publish-safe profile here so they never reach the API oversized.
        source_html = html_path
        preflighted = output_dir / "magic-page-preflight.html"
        pf_cmd = [
            sys.executable, str(MAGIC_PAGE_PREFLIGHT), str(html_path),
            "--report", str(output_dir / "MAGIC_PAGE_PREFLIGHT.md"),
            "--max-bytes", str(args.magic_max_resource_bytes),
            "--check-remote", "--json",
        ]
        if not args.no_compress_oversized:
            pf_cmd += ["--compress", "--out", str(preflighted)]
        preflight = subprocess_record(pf_cmd, cwd=REPO, log_path=output_dir / "publisher-magic-preflight.log")
        if not preflight["ok"]:
            blocking = ((preflight.get("json") or {}).get("oversized")) or []
            sample = "; ".join(f"{o.get('ref')} ({o.get('bytes', 0) // (1024*1024)}MB)" for o in blocking[:4])
            payload = magic_failure(
                "oversized resources block Magic Page publish (over per-resource limit). "
                "See MAGIC_PAGE_PREFLIGHT.md and compress/host them, then re-publish"
                + (f": {sample}" if sample else ""),
                html_path, base_url, preflight, dry_run=dry_run,
            )
            write_publish_reports(output_dir, payload)
            return payload
        if not args.no_compress_oversized and ((preflight.get("json") or {}).get("compressed")) and preflighted.exists():
            source_html = preflighted  # compressed-video refs replaced the oversized originals

        prepared = output_dir / "magic-page-inline.html"
        inline = subprocess_record(
            [sys.executable, str(INLINE_ASSETS), str(source_html), "--out", str(prepared), "--no-image-inline"],
            cwd=REPO,
            log_path=output_dir / "publisher-magic-inline-assets.log",
        )
        if not inline["ok"]:
            payload = magic_failure("inline-assets failed", prepared, base_url, inline, dry_run=dry_run)
            write_publish_reports(output_dir, payload)
            return payload
        package_source = prepared
        if not args.skip_magic_iframe_faas:
            iframe_ready = output_dir / "magic-page-iframes.html"
            iframe_report = output_dir / "magic-iframe-faas.json"
            faas_record_id = args.magic_iframe_faas_record_id
            if not faas_record_id and iframe_report.exists():
                try:
                    faas_record_id = str((read_json(iframe_report).get("faas") or {}).get("record_id") or "")
                except Exception:
                    faas_record_id = ""
            faas_name = "feishu_deck_h5_" + slugify(task_id.replace("/", "-"), "deck")[:40] + "_iframes"
            iframe_cmd = [
                sys.executable,
                str(MAGIC_IFRAME_FAAS),
                str(prepared),
                "--out",
                str(iframe_ready),
                "--uploader",
                str(uploader),
                "--base-url",
                base_url,
                "--key-prefix",
                f"feishu-deck-h5/{task_id}",
                "--asset-base-dir",
                str(source_html.parent),
                "--report",
                str(iframe_report),
                "--faas-name",
                faas_name,
                "--upload-workers",
                str(args.magic_upload_workers),
            ]
            if faas_record_id:
                iframe_cmd += ["--faas-record-id", faas_record_id]
            if args.legacy_magic_asset_uploader:
                iframe_cmd.append("--legacy-uploader")
            if dry_run or args.magic_iframe_faas_dry_run:
                iframe_cmd.append("--dry-run")
            iframe = subprocess_record(
                iframe_cmd,
                cwd=REPO,
                log_path=output_dir / "publisher-magic-iframe-faas.log",
                timeout=NETWORK_SUBPROCESS_TIMEOUT,
            )
            if not iframe["ok"]:
                payload = magic_failure(
                    "magic iframe FaaS preparation failed",
                    prepared,
                    base_url,
                    iframe,
                    dry_run=dry_run,
                )
                write_publish_reports(output_dir, payload)
                return payload
            if iframe_ready.exists():
                package_source = iframe_ready
        try:
            package_source, _snapshot = freeze_publish_snapshot(
                package_source=package_source,
                asset_base_dir=source_html.parent,
                source_html=html_path,
                output_dir=output_dir,
            )
            # Every later packaging pass resolves only against immutable bytes.
            source_html = package_source
        except Exception as exc:
            payload = magic_failure(
                f"publish snapshot freeze failed: {exc}",
                package_source,
                base_url,
                None,
                dry_run=dry_run,
            )
            write_publish_reports(output_dir, payload)
            return payload
        packaged = output_dir / "magic-page-ready.html"
        # delivery-9 / P1#4: keep the framework runtime + per-slide CSS INLINE by
        # default. Externalizing them turns feishu-deck.js into a hash-named hosted
        # script that the publish-bytes runtime-presence check no longer recognizes
        # ("runtime missing" false negative — it cost a manual round-trip on every
        # publish). The old implementation uploaded the keep-inline artifact,
        # measured it, then uploaded every shared asset AGAIN when the HTML was
        # too large and code had to be externalized. Instead, package first with a
        # deterministic local URL shim (zero remote writes), select the mode from
        # that exact artifact, then perform at most ONE real upload pass.
        requested_keep_inline = not args.externalize_inline_code
        max_html_chars = int(args.magic_max_html_chars or DEFAULT_MAGIC_MAX_HTML_CHARS)
        attempts: list[dict[str, Any]] = []

        preview_uploader = dry_run_asset_uploader(output_dir)
        preview_inline = output_dir / "magic-page-ready.keep-inline-preview.html"
        preview_keep_inline = requested_keep_inline
        preview = _run_magic_assets(
            package_source=package_source,
            packaged=preview_inline,
            uploader=preview_uploader,
            base_url=base_url,
            task_id=task_id,
            source_html=source_html,
            upload_workers=args.magic_upload_workers,
            keep_inline_code=preview_keep_inline,
            output_dir=output_dir,
            log_name="publisher-magic-assets-preview.log",
            legacy_uploader=False,
            cache_manifest=None,
        )
        if not preview["ok"]:
            payload = magic_failure(
                "magic-page-assets prediction failed",
                html_path,
                base_url,
                preview,
                dry_run=dry_run,
            )
            write_publish_reports(output_dir, payload)
            return payload

        preview_chars = html_char_count(preview_inline)
        attempts.append(
            {
                "mode": "keep-inline-code" if preview_keep_inline else "externalize-inline-code",
                "phase": "prediction",
                "html": repo_rel(preview_inline),
                "chars": preview_chars,
                "ok": preview_chars <= max_html_chars,
            }
        )
        auto_externalized = False
        selected_keep_inline = preview_keep_inline
        selected_preview = preview_inline
        if preview_keep_inline and preview_chars > max_html_chars:
            preview_externalized = output_dir / "magic-page-ready.externalized-preview.html"
            externalized = _run_magic_assets(
                package_source=package_source,
                packaged=preview_externalized,
                uploader=preview_uploader,
                base_url=base_url,
                task_id=task_id,
                source_html=source_html,
                upload_workers=args.magic_upload_workers,
                keep_inline_code=False,
                output_dir=output_dir,
                log_name="publisher-magic-assets-externalized-preview.log",
                legacy_uploader=False,
                cache_manifest=None,
            )
            if not externalized["ok"]:
                payload = magic_failure(
                    "magic-page-assets prediction failed while auto-externalizing inline code",
                    html_path,
                    base_url,
                    externalized,
                    dry_run=dry_run,
                )
                write_publish_reports(output_dir, payload)
                return payload
            auto_externalized = True
            selected_keep_inline = False
            selected_preview = preview_externalized
            externalized_chars = html_char_count(preview_externalized)
            attempts.append(
                {
                    "mode": "externalize-inline-code",
                    "phase": "prediction",
                    "html": repo_rel(preview_externalized),
                    "chars": externalized_chars,
                    "ok": externalized_chars <= max_html_chars,
                }
            )

        selected_preview_chars = html_char_count(selected_preview)
        if selected_preview_chars > max_html_chars:
            # Even the selected mode cannot fit. Preserve the predicted artifact
            # and report, but do not make a knowingly-useless remote upload.
            shutil.copy2(selected_preview, packaged)
            attempts.append(
                {
                    "mode": "keep-inline-code" if selected_keep_inline else "externalize-inline-code",
                    "phase": "final-prediction",
                    "html": repo_rel(packaged),
                    "chars": selected_preview_chars,
                    "ok": False,
                }
            )
            reason = (
                f"Magic Page HTML body is {selected_preview_chars} chars, over the "
                f"{max_html_chars} char limit"
            )
            size_payload = {
                "ok": False,
                "max_html_chars": max_html_chars,
                "final_html": repo_rel(packaged),
                "final_chars": selected_preview_chars,
                "auto_externalized_inline_code": auto_externalized,
                "attempts": attempts,
                "reason": reason,
            }
            write_publish_size_report(output_dir, size_payload)
            payload = magic_failure(
                "publish artifact size check failed before Magic Page asset upload: " + reason,
                packaged,
                base_url,
                None,
                dry_run=dry_run,
            )
            payload["size"] = size_payload
            write_publish_reports(output_dir, payload)
            return payload

        # Dry-run preparation is itself the selected deterministic package; live
        # publishing now performs exactly one uploader-backed package pass.
        if dry_run:
            shutil.copy2(selected_preview, packaged)
            package = preview
        else:
            package = _run_magic_assets(
                package_source=package_source,
                packaged=packaged,
                uploader=uploader,
                base_url=base_url,
                task_id=task_id,
                source_html=source_html,
                upload_workers=args.magic_upload_workers,
                keep_inline_code=selected_keep_inline,
                output_dir=output_dir,
                log_name="publisher-magic-assets.log",
                legacy_uploader=bool(args.legacy_magic_asset_uploader),
                cache_manifest=(
                    args.magic_asset_cache
                    if not args.no_magic_asset_cache
                    and uploader.resolve() == DEFAULT_MAGIC_ASSET_UPLOADER.resolve()
                    else None
                ),
            )
            if not package["ok"]:
                payload = magic_failure(
                    "magic-page-assets failed",
                    html_path,
                    base_url,
                    package,
                    dry_run=dry_run,
                )
                write_publish_reports(output_dir, payload)
                return payload

        final_chars = html_char_count(packaged)
        attempts.append(
            {
                "mode": "keep-inline-code" if selected_keep_inline else "externalize-inline-code",
                "phase": "final",
                "html": repo_rel(packaged),
                "chars": final_chars,
                "ok": final_chars <= max_html_chars,
            }
        )
        size_payload = {
            "ok": final_chars <= max_html_chars,
            "max_html_chars": max_html_chars,
            "final_html": repo_rel(packaged),
            "final_chars": final_chars,
            "auto_externalized_inline_code": auto_externalized,
            "attempts": attempts,
            "reason": "" if final_chars <= max_html_chars else (
                f"Magic Page HTML body is {final_chars} chars, over the {max_html_chars} char limit"
            ),
        }
        write_publish_size_report(output_dir, size_payload)
        if not size_payload["ok"]:
            payload = magic_failure(
                "publish artifact size check failed before Magic Page API call: " + size_payload["reason"],
                packaged,
                base_url,
                None,
                dry_run=dry_run,
            )
            payload["size"] = size_payload
            write_publish_reports(output_dir, payload)
            return payload
        working_html = packaged
        if not args.skip_magic_asset_faas:
            asset_report = output_dir / "magic-asset-faas.json"
            asset_faas_record_id = args.magic_asset_faas_record_id
            if not asset_faas_record_id and asset_report.exists():
                try:
                    prior_asset_report = read_json(asset_report)
                    prior_shards = prior_asset_report.get("faas_shards") or []
                    if prior_shards:
                        asset_faas_record_id = ",".join(
                            str(row.get("record_id") or "") for row in prior_shards if row.get("record_id")
                        )
                    else:
                        asset_faas_record_id = str((prior_asset_report.get("faas") or {}).get("record_id") or "")
                except Exception:
                    asset_faas_record_id = ""
            asset_faas_name = "feishu_deck_h5_" + slugify(task_id.replace("/", "-"), "deck")[:40] + "_assets"
            asset_cmd = [
                sys.executable,
                str(MAGIC_ASSET_FAAS),
                str(packaged),
                "--out",
                str(packaged),
                "--report",
                str(asset_report),
                "--base-url",
                base_url,
                "--faas-name",
                asset_faas_name,
            ]
            if asset_faas_record_id:
                asset_cmd += ["--faas-record-id", asset_faas_record_id]
            if dry_run or args.magic_asset_faas_dry_run:
                asset_cmd.append("--dry-run")
            asset_proxy = subprocess_record(
                asset_cmd,
                cwd=REPO,
                log_path=output_dir / "publisher-magic-asset-faas.log",
                timeout=NETWORK_SUBPROCESS_TIMEOUT,
            )
            if not asset_proxy["ok"]:
                payload = magic_failure(
                    "Magic TOS asset FaaS preparation failed",
                    packaged,
                    base_url,
                    asset_proxy,
                    dry_run=dry_run,
                )
                write_publish_reports(output_dir, payload)
                return payload
            if packaged.exists():
                working_html = packaged

    if args.skip_magic_asset_prepare:
        try:
            working_html, _snapshot = freeze_publish_snapshot(
                package_source=html_path,
                asset_base_dir=html_path.parent,
                source_html=html_path,
                output_dir=output_dir,
            )
        except Exception as exc:
            payload = magic_failure(
                f"publish snapshot freeze failed: {exc}",
                html_path,
                base_url,
                None,
                dry_run=dry_run,
            )
            write_publish_reports(output_dir, payload)
            return payload

    integrity = audit_publish_integrity(working_html, output_dir)
    if not integrity["ok"]:
        payload = magic_failure(
            "publish artifact integrity check failed: " + integrity["reason"],
            working_html,
            base_url,
            None,
            dry_run=dry_run,
        )
        payload["integrity"] = integrity
        write_publish_reports(output_dir, payload)
        return payload

    if dry_run:
        token = "dryrun-" + hashlib.sha1(f"{task_id}:{title}:{working_html}".encode("utf-8")).hexdigest()[:16]
        payload = {
            "target": "magic-page",
            "enabled": True,
            "ok": True,
            "dry_run": True,
            "app_url": f"{base_url}/dryrun/{token}",
            "app_id": token,
            "base_url": base_url,
            "urls": [],
            "html": repo_rel(working_html),
            "reason": "dry-run after publish preparation and integrity checks",
        }
        write_publish_reports(output_dir, payload)
        return payload

    script = args.magic_page_script or optional_path(os.environ.get("FEISHU_DECK_H5_MAGIC_PAGE_PUBLISHER", "")) or DEFAULT_MAGIC_PAGE_PUBLISHER
    if not script.exists():
        payload = magic_failure(f"Magic Page publisher not found: {script}", working_html, base_url, None)
        write_publish_reports(output_dir, payload)
        return payload
    existing_app_id = resolve_existing_magic_app_id(output_dir, args)
    cmd = ["node", str(script), "publish", str(working_html), "--title", title, "--base-url", base_url]
    if existing_app_id:
        cmd += ["--remote-id", existing_app_id]
    if args.magic_page_open_source:
        cmd.append("--open-source")
    proc = subprocess_record(cmd, cwd=REPO, log_path=output_dir / "publisher-magic-page.log", timeout=NETWORK_SUBPROCESS_TIMEOUT)
    parsed = parse_magic_stdout(proc["stdout"])
    ok = proc["ok"] and bool(parsed["app_url"])
    payload = {
        "target": "magic-page",
        "enabled": True,
        "ok": ok,
        "dry_run": False,
        "app_url": parsed["app_url"],
        "app_id": parsed["app_id"],
        "base_url": base_url,
        "urls": parsed["urls"],
        "html": repo_rel(working_html),
        "reused_app_id": existing_app_id,
        "reason": "" if ok else (proc["stderr"] or proc["stdout"] or "publish failed"),
    }
    write_publish_reports(output_dir, payload)
    return payload


def magic_failure(
    reason: str,
    html_path: Path,
    base_url: str,
    proc: dict[str, Any] | None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    detail = ""
    if proc:
        detail = proc.get("stderr") or proc.get("stdout") or ""
    return {
        "target": "magic-page",
        "enabled": True,
        "ok": False,
        "dry_run": dry_run,
        "app_url": "",
        "app_id": "",
        "base_url": base_url,
        "html": repo_rel(html_path),
        "reason": f"{reason}: {detail}".strip(": "),
    }


def write_publish_reports(output_dir: Path, payload: dict[str, Any]) -> None:
    write_json(output_dir / "cloud-publish.json", payload)
    write_json(output_dir / "magic-page-publish.json", payload)
    report_name = "MAGIC_PAGE_PUBLISH.md"
    title = "Feishu/Miaobi Magic Page Publish"
    lines = [
        f"# {title}",
        "",
        f"- target: {payload.get('target') or ''}",
        f"- ok: {payload.get('ok')}",
        f"- dry_run: {payload.get('dry_run')}",
        f"- app_url: {payload.get('app_url') or ''}",
        f"- app_id: {payload.get('app_id') or ''}",
        f"- reason: {payload.get('reason') or ''}",
        "",
    ]
    (output_dir / report_name).write_text("\n".join(lines), encoding="utf-8")


def write_timing_report(output_dir: Path, timing: dict[str, Any]) -> None:
    lines = [
        "# Publish Timing",
        "",
        f"- total_seconds: {timing.get('total_seconds')}",
        f"- budget_seconds: {timing.get('budget_seconds')}",
        f"- within_budget: {timing.get('within_budget')}",
        "",
        "## Stages",
        "",
    ]
    for row in timing.get("stages") or []:
        lines.append(
            f"- `{row.get('stage')}` · {row.get('duration_seconds')}s · "
            + ("ok" if row.get("ok") else "failed")
        )
    if not timing.get("within_budget"):
        lines.extend([
            "",
            "Publisher exceeded its delivery SLO. Stop retrying this artifact in the",
            "PUBLISH lane and route the named slow/failed stage to PUBLISH_RECOVERY.",
        ])
    (output_dir / "PUBLISH_TIMING.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _load_self_check():
    """Load subskills/publisher/self_check.py by path (sibling module)."""
    spec = importlib.util.spec_from_file_location("publisher_self_check", SELF_CHECK)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def post_publish_self_check(
    *,
    html_path: Path,
    publication: dict[str, Any],
    output_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    """F-285 last-mile verification: re-open the *final published URL* as the
    audience would and confirm the bytes survived publishing — no 404'd assets,
    no silent font fallback, no per-page visual drift vs the local render.

    Skipped (not failed) when: the user opted out (--skip-self-check), the
    publish was a dry-run / produced no app_url, or there is no local HTML to
    compare against. A red card here flips the publish to non-zero by default
    (the whole point — do not call a broken delivery 'published'); pass
    --self-check-soft to downgrade a red card to a warning."""
    if args.skip_self_check:
        return {"enabled": False, "ok": True, "reason": "self-check skipped by --skip-self-check"}
    if not html_path:
        return {"enabled": False, "ok": True, "reason": "no local HTML to compare; self-check skipped"}
    app_url = str(publication.get("app_url") or "")
    if publication.get("dry_run") or not publication.get("ok") or not app_url:
        return {"enabled": False, "ok": True,
                "reason": "no live published URL (dry-run / publish failed); self-check skipped"}

    mod = _load_self_check()
    try:
        payload = mod.run_self_check(
            local=html_path,
            remote=app_url,
            out_dir=output_dir,
            pages=args.self_check_pages,
            threshold=args.self_check_threshold,
            page_indices=getattr(args, "_self_check_page_indices", None),
        )
    except SystemExit as exc:
        return {"enabled": True, "ok": True if args.self_check_soft else False,
                "reason": f"self-check could not start: {exc}"}
    payload["enabled"] = True
    if payload.get("skipped"):
        # browser unavailable: report, never block (real publish stays green)
        payload["ok"] = True
        return payload
    if not payload.get("ok") and args.self_check_soft:
        payload["soft"] = True
        payload["ok"] = True
    return payload


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task-id")
    ap.add_argument("--html", type=Path, help="confirmed .html/.htm artifact to publish")
    ap.add_argument("--title")
    ap.add_argument(
        "--allow-unaudited",
        action="store_true",
        help="deprecated no-op; publisher now runs resource-integrity checks instead of deck-validator",
    )
    ap.add_argument("--dry-run", action="store_true", help="simulate publishing without external writes")
    ap.add_argument(
        "--publish-time-budget",
        type=int,
        default=DEFAULT_PUBLISH_TIME_BUDGET_SECONDS,
        help="maximum wall-clock seconds available to publisher child stages (default 600)",
    )

    ap.add_argument("--magic-page-script", type=Path)
    ap.add_argument("--magic-asset-uploader", type=Path)
    ap.add_argument(
        "--legacy-magic-asset-uploader",
        action="store_true",
        help=(
            "explicitly allow a custom uploader that lacks the JSON batch "
            "protocol; uses bounded one-process-per-asset fallback"
        ),
    )
    ap.add_argument("--magic-base-url", default="")
    ap.add_argument("--magic-page-app-id", default="",
                    help="existing Magic Page html-box id to update; otherwise publisher reuses prior run publish metadata")
    ap.add_argument("--magic-page-dry-run", action="store_true")
    ap.add_argument("--magic-page-open-source", action="store_true")
    ap.add_argument("--skip-magic-asset-prepare", action="store_true")
    ap.add_argument("--skip-magic-iframe-faas", action="store_true",
                    help="do not rewrite local HTML iframes through a Magic FaaS text/html proxy")
    ap.add_argument("--magic-iframe-faas-record-id", default="",
                    help="existing Magic FaaS record id to update for local iframe HTML proxying")
    ap.add_argument("--magic-iframe-faas-dry-run", action="store_true",
                    help="rewrite local iframe HTML through a deterministic fake FaaS URL for tests")
    ap.add_argument("--skip-magic-asset-faas", action="store_true",
                    help="do not proxy Magic TOS assets that are served with attachment disposition")
    ap.add_argument("--magic-asset-faas-record-id", default="",
                    help="comma-separated existing Magic FaaS record ids to update for binary asset proxying")
    ap.add_argument("--magic-asset-faas-dry-run", action="store_true",
                    help="rewrite Magic TOS assets through a deterministic fake FaaS URL for tests")
    ap.add_argument("--magic-upload-workers", type=int, default=6,
                    help="parallel upload workers for Magic Page asset and iframe preparation")
    ap.add_argument(
        "--magic-asset-cache",
        type=Path,
        default=DEFAULT_MAGIC_ASSET_CACHE,
        help="persistent content-addressed upload cache shared across publisher runs",
    )
    ap.add_argument("--no-magic-asset-cache", action="store_true",
                    help="disable persistent Magic asset URL reuse for this invocation")
    # delivery-8: oversized-resource pre-flight (run before the upload API).
    ap.add_argument("--no-compress-oversized", action="store_true",
                    help="do NOT auto-compress oversized videos; instead fail the publish with a "
                         "report listing every oversized resource + the exact fix command")
    ap.add_argument("--magic-max-resource-bytes", type=int, default=64 * 1024 * 1024,
                    help="per-resource size limit enforced by the pre-flight (default 64 MiB, Magic Page's limit)")
    ap.add_argument("--magic-max-html-chars", type=int, default=DEFAULT_MAGIC_MAX_HTML_CHARS,
                    help="Magic Page HTML body character limit; publisher auto-externalizes inline code before calling the API when exceeded")
    # delivery-9 / P1#4: framework runtime + CSS stay inline by default so the
    # publish-bytes runtime check still recognizes the player. Opt out only if a
    # deck genuinely needs its code externalized.
    ap.add_argument("--externalize-inline-code", action="store_true",
                    help="externalize inline <style>/<script> to TOS (default: keep inline so the "
                         "runtime stays recognizable to the publish-bytes check)")

    # F-285 post-publish self-check (verify the final URL the audience opens).
    ap.add_argument("--skip-self-check", action="store_true",
                    help="do not re-open the published URL to verify delivery (404 / font / visual)")
    ap.add_argument("--self-check-soft", action="store_true",
                    help="a self-check red card warns instead of failing the publish")
    ap.add_argument("--self-check-pages", type=int, default=3,
                    help="how many leading slides the post-publish self-check verifies (default 3)")
    ap.add_argument(
        "--self-check-page",
        dest="self_check_page_indices",
        action="append",
        type=int,
        default=[],
        help="1-based page to verify; repeat to override automatic incremental selection",
    )
    ap.add_argument("--self-check-max-pages", type=int, default=5,
                    help="maximum automatic incremental screenshots after a prior successful publish (default 5)")
    ap.add_argument("--self-check-threshold", type=float, default=0.06,
                    help="per-slide diff ratio that red-cards a page in the post-publish self-check (default 0.06)")

    return ap


def main(argv: list[str] | None = None) -> int:
    global PUBLISH_DEADLINE
    STAGE_EVENTS.clear()
    invocation_started = time.monotonic()
    args = build_parser().parse_args(argv)
    args.magic_asset_cache = args.magic_asset_cache.expanduser().resolve()
    budget_seconds = max(30, int(args.publish_time_budget or DEFAULT_PUBLISH_TIME_BUDGET_SECONDS))
    PUBLISH_DEADLINE = invocation_started + budget_seconds
    if not args.task_id and not args.html:
        raise SystemExit("publisher: --html or --task-id is required")

    task_id = args.task_id or stable_publisher_task_id(Path(args.html))
    _task_dir: Path | None = None
    output_dir: Path
    if args.task_id:
        _task_dir, output_dir = task_dirs(args.task_id)
    else:
        output_dir = RUNS / task_id / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

    html_path = resolve_html(args, output_dir)
    prior_manifest: dict[str, Any] = {}
    prior_manifest_path = output_dir / "publish-manifest.json"
    if prior_manifest_path.is_file():
        try:
            candidate = read_json(prior_manifest_path)
            if (candidate.get("publication") or {}).get("ok") and (candidate.get("self_check") or {}).get("ok"):
                prior_manifest = candidate
        except (OSError, json.JSONDecodeError, TypeError):
            prior_manifest = {}

    title = args.title or (read_json(output_dir / "deck.json").get("title") if (output_dir / "deck.json").exists() else "") or (html_path.stem if html_path else task_id)

    if not html_path:
        publication = {"ok": True, "dry_run": True, "reason": "no HTML artifact; compatibility dry-run only"}
    else:
        publication = publish_magic_page(html_path=html_path, output_dir=output_dir, title=title, task_id=task_id, args=args)

    snapshot: dict[str, Any] = {}
    snapshot_path = output_dir / "publish-snapshot.json"
    if snapshot_path.is_file():
        try:
            snapshot = read_json(snapshot_path)
        except (OSError, json.JSONDecodeError, TypeError):
            snapshot = {}
    if args.self_check_page_indices:
        args._self_check_page_indices = sorted({index for index in args.self_check_page_indices if index > 0})
    else:
        args._self_check_page_indices = select_incremental_self_check_pages(
            snapshot.get("pages") or [],
            (prior_manifest.get("snapshot") or {}).get("pages") or [],
            leading_pages=args.self_check_pages,
            max_pages=args.self_check_max_pages,
        ) or None

    self_check_started = time.monotonic()
    self_check = post_publish_self_check(
        html_path=html_path,
        publication=publication,
        output_dir=output_dir,
        args=args,
    )
    STAGE_EVENTS.append({
        "stage": "post-publish-self-check",
        "ok": bool(self_check.get("ok")),
        "duration_seconds": round(time.monotonic() - self_check_started, 3),
    })

    total_seconds = round(time.monotonic() - invocation_started, 3)
    timing = {
        "total_seconds": total_seconds,
        "budget_seconds": budget_seconds,
        "within_budget": total_seconds <= budget_seconds,
        "stages": list(STAGE_EVENTS),
    }
    write_json(output_dir / "publish-timing.json", timing)
    write_timing_report(output_dir, timing)
    snapshot_summary = {
        "version": snapshot.get("version"),
        "snapshot_id": snapshot.get("snapshot_id"),
        "html_sha256": snapshot.get("html_sha256"),
        "asset_count": len(snapshot.get("assets") or []),
        "pages": snapshot.get("pages") or [],
        "manifest": repo_rel(snapshot_path) if snapshot else "",
    }

    manifest = {
        "task_id": task_id,
        "source": repo_rel(html_path) if html_path else "",
        "dry_run": args.dry_run,
        "publication": publication,
        "self_check": self_check,
        "snapshot": snapshot_summary,
        "timing": timing,
        "skipped": [{"type": "library_ingest", "reason": "publisher only publishes to Magic Page; use subskills/importer/ingest.py for library ingest"}],
    }
    manifest_path = output_dir / "publish-manifest.json"
    write_json(manifest_path, manifest)
    print(json.dumps({"manifest": str(manifest_path), **manifest}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if (bool(publication.get("ok")) and bool(self_check.get("ok"))) else 1


if __name__ == "__main__":
    raise SystemExit(main())
