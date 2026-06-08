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
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
RUNS = REPO / "runs"
MAGIC_PAGE_ASSETS = REPO / "assets/magic-page-assets.py"
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
RESOURCE_ATTR_RE = re.compile(r"<(?P<tag>[A-Za-z][\w:-]*)\b[^>]*?\b(?P<attr>src|href|poster)\s*=\s*([\"'])(.*?)\3", re.I | re.S)
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


def audit_passed(output_dir: Path) -> bool:
    report = output_dir / "audit-report.json"
    if report.exists():
        try:
            payload = read_json(report)
        except Exception:
            payload = {}
        verdict = str(payload.get("verdict") or payload.get("feishu_deck_h5_verdict") or "").lower()
        status = str(payload.get("status") or "").lower()
        if verdict == "pass" or status == "pass":
            return True
    md = output_dir / "AUDIT_REPORT.md"
    if md.exists():
        first = md.read_text(encoding="utf-8", errors="ignore").splitlines()[:5]
        joined = " ".join(first).lower()
        return "feishu-deck-h5 verdict: pass" in joined or "verdict: pass" in joined
    return False


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


def subprocess_record(
    cmd: list[str],
    *,
    cwd: Path,
    log_path: Path | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, env=env)
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


def contains_data_image(html_path: Path) -> bool:
    try:
        html = html_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return bool(re.search(r"data:image/[A-Za-z0-9.+-]+", html, re.I))


def is_dependency_ref(ref: str) -> bool:
    raw = ref.strip()
    if not raw or raw.startswith("#"):
        return False
    lowered = raw.lower()
    return not lowered.startswith(("javascript:", "mailto:", "tel:", "about:", "blob:"))


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
    for regex in (URL_RE, IMPORT_RE):
        for match in regex.finditer(html):
            ref = next((group for group in match.groups() if group), "").strip()
            if is_unhosted_dependency(ref):
                refs.append(ref)
    for match in RESOURCE_ATTR_RE.finditer(html):
        tag = match.group("tag").lower()
        attr = match.group("attr").lower()
        ref = match.group(4).strip()
        if attr == "href" and tag != "link":
            continue
        if is_unhosted_dependency(ref):
            refs.append(ref)
    for match in SRCSET_ATTR_RE.finditer(html):
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
        prepared = output_dir / "magic-page-inline.html"
        inline = subprocess_record(
            [sys.executable, str(INLINE_ASSETS), str(html_path), "--out", str(prepared), "--no-image-inline"],
            cwd=REPO,
            log_path=output_dir / "publisher-magic-inline-assets.log",
        )
        if not inline["ok"]:
            payload = magic_failure("inline-assets failed", prepared, base_url, inline)
            write_publish_reports(output_dir, payload)
            return payload
        packaged = output_dir / "magic-page-ready.html"
        package = subprocess_record(
            [
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
            ],
            cwd=REPO,
            log_path=output_dir / "publisher-magic-assets.log",
        )
        if not package["ok"]:
            payload = magic_failure("magic-page-assets failed", html_path, base_url, package)
            write_publish_reports(output_dir, payload)
            return payload
        working_html = packaged

    if contains_data_image(working_html):
        payload = magic_failure(
            "Magic Page HTML still contains data:image payloads; upload images to TOS before publishing",
            working_html,
            base_url,
            None,
        )
        write_publish_reports(output_dir, payload)
        return payload
    unhosted = remaining_unhosted_dependencies(working_html)
    if unhosted:
        sample = ", ".join(unhosted[:8])
        more = f" (+{len(unhosted) - 8} more)" if len(unhosted) > 8 else ""
        payload = magic_failure(
            f"Magic Page HTML still contains unhosted runtime dependencies: {sample}{more}",
            working_html,
            base_url,
            None,
        )
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
    proc = subprocess_record(cmd, cwd=REPO, log_path=output_dir / "publisher-magic-page.log")
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
        f"- mode: {payload.get('mode') or ''}",
        f"- publish_dir: {payload.get('publish_dir') or ''}",
        f"- reason: {payload.get('reason') or ''}",
        "",
    ]
    (output_dir / report_name).write_text("\n".join(lines), encoding="utf-8")


def summarize_step(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": step["ok"],
        "returncode": step["returncode"],
        "stderr": step["stderr"][:1200],
        "stdout": step["stdout"][:1200],
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task-id")
    ap.add_argument("--html", type=Path, help="confirmed .html/.htm artifact to publish")
    ap.add_argument("--title")
    ap.add_argument("--allow-unaudited", action="store_true", help="bypass deck-validator pass requirement for local/debug use")
    ap.add_argument("--dry-run", action="store_true", help="simulate publishing without external writes")

    ap.add_argument("--magic-page-script", type=Path)
    ap.add_argument("--magic-asset-uploader", type=Path)
    ap.add_argument("--magic-base-url", default="")
    ap.add_argument("--magic-page-dry-run", action="store_true")
    ap.add_argument("--magic-page-open-source", action="store_true")
    ap.add_argument("--skip-magic-asset-prepare", action="store_true")

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

    if not args.allow_unaudited and output_dir.exists() and (output_dir / "deck.json").exists() and not audit_passed(output_dir):
        raise SystemExit("publisher: deck-validator pass verdict is required before publishing")

    html_path = resolve_html(args, output_dir)
    title = args.title or (read_json(output_dir / "deck.json").get("title") if (output_dir / "deck.json").exists() else "") or (html_path.stem if html_path else task_id)

    if not html_path:
        publication = {"ok": True, "dry_run": True, "reason": "no HTML artifact; compatibility dry-run only"}
    else:
        publication = publish_magic_page(html_path=html_path, output_dir=output_dir, title=title, task_id=task_id, args=args)

    manifest = {
        "task_id": task_id,
        "source": repo_rel(html_path) if html_path else "",
        "dry_run": args.dry_run,
        "publication": publication,
        "skipped": [{"type": "library_ingest", "reason": "publisher only publishes to Magic Page; use subskills/importer/ingest.py for library ingest"}],
    }
    manifest_path = output_dir / "publish-manifest.json"
    write_json(manifest_path, manifest)
    print(json.dumps({"manifest": str(manifest_path), **manifest}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if bool(publication.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
