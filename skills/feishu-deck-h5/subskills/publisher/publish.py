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
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
SELF_CHECK = Path(__file__).resolve().parent / "self_check.py"
RUNS = REPO / "runs"
MAGIC_PAGE_ASSETS = REPO / "assets/magic-page-assets.py"
MAGIC_PAGE_PREFLIGHT = REPO / "assets/magic-page-preflight.py"
INLINE_ASSETS = REPO / "assets/inline-assets.py"
DEFAULT_MAGIC_PAGE_PUBLISHER = REPO / "assets/magic-page-publish.js"
DEFAULT_MAGIC_ASSET_UPLOADER = REPO / "assets/magic-upload.js"
DEFAULT_MAGIC_BASE_URL = "https://magic.solutionsuite.cn"
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


def subprocess_record(
    cmd: list[str],
    *,
    cwd: Path,
    log_path: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = DEFAULT_SUBPROCESS_TIMEOUT,
) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, text=True, capture_output=True, env=env, timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\nTIMEOUT after {timeout}s: {' '.join(cmd)}"
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
        return {
            "cmd": cmd,
            "ok": False,
            "returncode": 124,
            "stdout": stdout.strip(),
            "stderr": stderr.strip(),
            "json": None,
        }
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
    return {
        "cmd": cmd,
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
        "json": parsed,
    }


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


def publish_magic_page(
    *,
    html_path: Path,
    output_dir: Path,
    title: str,
    task_id: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    base_url = (args.magic_base_url or os.environ.get("MAGIC_BASE_URL") or DEFAULT_MAGIC_BASE_URL).rstrip("/")
    if args.dry_run or args.magic_page_dry_run:
        token = "dryrun-" + hashlib.sha1(f"{task_id}:{title}:{html_path}".encode("utf-8")).hexdigest()[:16]
        payload = {
            "target": "magic-page",
            "enabled": True,
            "ok": True,
            "dry_run": True,
            "app_url": f"{base_url}/dryrun/{token}",
            "app_id": token,
            "base_url": base_url,
            "html": repo_rel(html_path),
            "reason": "dry-run",
        }
        write_publish_reports(output_dir, payload)
        return payload

    if not magic_token_available():
        payload = magic_failure(missing_magic_token_message(), html_path, base_url, None)
        write_publish_reports(output_dir, payload)
        return payload

    working_html = html_path
    if not args.skip_magic_asset_prepare:
        uploader = args.magic_asset_uploader or optional_path(os.environ.get("FEISHU_DECK_H5_MAGIC_ASSET_UPLOADER", "")) or DEFAULT_MAGIC_ASSET_UPLOADER

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
                html_path, base_url, preflight,
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
            payload = magic_failure("inline-assets failed", prepared, base_url, inline)
            write_publish_reports(output_dir, payload)
            return payload
        packaged = output_dir / "magic-page-ready.html"
        package_cmd = [
            sys.executable,
            str(MAGIC_PAGE_ASSETS),
            str(prepared),
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
        ]
        # delivery-9 / P1#4: keep the framework runtime + per-slide CSS INLINE by
        # default. Externalizing them turns feishu-deck.js into a hash-named hosted
        # script that the publish-bytes runtime-presence check no longer recognizes
        # ("runtime missing" false negative — it cost a manual round-trip on every
        # publish). Code is <0.5 MB, so keeping it inline never threatens the body
        # limit; only heavy media is externalized. Opt out with
        # --externalize-inline-code if a deck genuinely needs it.
        if not args.externalize_inline_code:
            package_cmd.append("--keep-inline-code")
        package = subprocess_record(
            package_cmd,
            cwd=REPO,
            log_path=output_dir / "publisher-magic-assets.log",
        )
        if not package["ok"]:
            payload = magic_failure("magic-page-assets failed", html_path, base_url, package)
            write_publish_reports(output_dir, payload)
            return payload
        working_html = packaged

    integrity = audit_publish_integrity(working_html, output_dir)
    if not integrity["ok"]:
        payload = magic_failure(
            "publish artifact integrity check failed: " + integrity["reason"],
            working_html,
            base_url,
            None,
        )
        payload["integrity"] = integrity
        write_publish_reports(output_dir, payload)
        return payload

    script = args.magic_page_script or optional_path(os.environ.get("FEISHU_DECK_H5_MAGIC_PAGE_PUBLISHER", "")) or DEFAULT_MAGIC_PAGE_PUBLISHER
    if not script.exists():
        payload = magic_failure(f"Magic Page publisher not found: {script}", working_html, base_url, None)
        write_publish_reports(output_dir, payload)
        return payload
    cmd = ["node", str(script), "publish", str(working_html), "--title", title, "--base-url", base_url]
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
        "reason": "" if ok else (proc["stderr"] or proc["stdout"] or "publish failed"),
    }
    write_publish_reports(output_dir, payload)
    return payload


def magic_failure(reason: str, html_path: Path, base_url: str, proc: dict[str, Any] | None) -> dict[str, Any]:
    detail = ""
    if proc:
        detail = proc.get("stderr") or proc.get("stdout") or ""
    return {
        "target": "magic-page",
        "enabled": True,
        "ok": False,
        "dry_run": False,
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

    ap.add_argument("--magic-page-script", type=Path)
    ap.add_argument("--magic-asset-uploader", type=Path)
    ap.add_argument("--magic-base-url", default="")
    ap.add_argument("--magic-page-dry-run", action="store_true")
    ap.add_argument("--magic-page-open-source", action="store_true")
    ap.add_argument("--skip-magic-asset-prepare", action="store_true")
    # delivery-8: oversized-resource pre-flight (run before the upload API).
    ap.add_argument("--no-compress-oversized", action="store_true",
                    help="do NOT auto-compress oversized videos; instead fail the publish with a "
                         "report listing every oversized resource + the exact fix command")
    ap.add_argument("--magic-max-resource-bytes", type=int, default=64 * 1024 * 1024,
                    help="per-resource size limit enforced by the pre-flight (default 64 MiB, Magic Page's limit)")
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
    ap.add_argument("--self-check-threshold", type=float, default=0.06,
                    help="per-slide diff ratio that red-cards a page in the post-publish self-check (default 0.06)")

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.task_id and not args.html:
        raise SystemExit("publisher: --html or --task-id is required")

    task_id = args.task_id or f"publisher/{slugify(Path(args.html).stem if args.html else 'html')}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    _task_dir: Path | None = None
    output_dir: Path
    if args.task_id:
        _task_dir, output_dir = task_dirs(args.task_id)
    else:
        output_dir = RUNS / task_id / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

    html_path = resolve_html(args, output_dir)

    title = args.title or (read_json(output_dir / "deck.json").get("title") if (output_dir / "deck.json").exists() else "") or (html_path.stem if html_path else task_id)

    if not html_path:
        publication = {"ok": True, "dry_run": True, "reason": "no HTML artifact; compatibility dry-run only"}
    else:
        publication = publish_magic_page(html_path=html_path, output_dir=output_dir, title=title, task_id=task_id, args=args)

    self_check = post_publish_self_check(
        html_path=html_path,
        publication=publication,
        output_dir=output_dir,
        args=args,
    )

    manifest = {
        "task_id": task_id,
        "source": repo_rel(html_path) if html_path else "",
        "dry_run": args.dry_run,
        "publication": publication,
        "self_check": self_check,
        "skipped": [{"type": "library_ingest", "reason": "publisher only publishes to Magic Page; use subskills/importer/ingest.py for library ingest"}],
    }
    manifest_path = output_dir / "publish-manifest.json"
    write_json(manifest_path, manifest)
    print(json.dumps({"manifest": str(manifest_path), **manifest}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if (bool(publication.get("ok")) and bool(self_check.get("ok"))) else 1


if __name__ == "__main__":
    raise SystemExit(main())
