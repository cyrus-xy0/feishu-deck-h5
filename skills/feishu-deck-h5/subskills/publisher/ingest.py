#!/usr/bin/env python3
"""Publish a confirmed feishu-deck-h5 HTML artifact and ingest it.

The publisher skill owns the last mile after the user has confirmed a rendered
HTML deck:

- publish the confirmed HTML to Feishu/Miaobi Magic Page;
- hand the same artifact to FuQiang/feishu-slide-library's integrated ingest
  flow: bootstrap-library.py -> ingest-package.py -> confirm-ingest.py.

The feishu-slide-library scripts remain the source of truth for library ingest.
This wrapper only coordinates inputs, reports, and the feishu-deck-h5 manifest.
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
DEFAULT_SLIDE_LIBRARY_ROOT = REPO / "tmp/feishu-slide-library"
SLIDE_LIBRARY_REPO = "https://github.com/FuQiang/feishu-slide-library.git"
DEFAULT_PUBLISH_TARGET = "magic-page"

sys.path.insert(0, str(REPO / "server"))
import slide_library  # noqa: E402


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


def selected_slide_keys(deck: dict[str, Any], requested: list[str]) -> list[str]:
    if requested:
        return requested
    keys = []
    for slide in deck.get("slides", []):
        if not isinstance(slide, dict):
            continue
        if slide.get("layout") in {"cover", "end", "raw", "replica"}:
            continue
        key = slide.get("key")
        if key:
            keys.append(str(key))
    return keys


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


def parse_lark_cli_error(proc: dict[str, Any]) -> str:
    for stream in (proc.get("stdout", ""), proc.get("stderr", "")):
        if not stream:
            continue
        try:
            payload = json.loads(stream)
        except json.JSONDecodeError:
            continue
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            return str(error.get("hint") or error.get("message") or stream)
    return str(proc.get("stderr") or proc.get("stdout") or "")


def parse_miaoda_publish_stdout(stdout: str) -> dict[str, str]:
    payload = json.loads(stdout or "{}")
    data = payload.get("data") if isinstance(payload, dict) else None
    app = data.get("app") if isinstance(data, dict) else None
    return {
        "url": str((data or {}).get("url") or ""),
        "app_id": str((app or {}).get("app_id") or ""),
        "name": str((app or {}).get("name") or ""),
    }


def prepare_miaoda_publish_dir(
    *,
    html_path: Path,
    output_dir: Path,
    args: argparse.Namespace,
) -> tuple[Path, dict[str, Any]]:
    publish_dir = (args.miaoda_publish_dir or output_dir / "miaoda-publish").expanduser().resolve()
    publish_dir.mkdir(parents=True, exist_ok=True)
    target_html = publish_dir / "index.html"
    mode = "inline-single-file"
    prep: dict[str, Any] = {
        "mode": mode,
        "path": repo_rel(publish_dir),
        "source_html": repo_rel(html_path),
        "index_html": repo_rel(target_html),
        "inline": True,
    }
    if args.miaoda_linked:
        mode = "linked-directory"
        prep.update({"mode": mode, "inline": False})
        target_html.write_text(html_path.read_text(encoding="utf-8"), encoding="utf-8")
        # Keep this mode deliberately minimal. It is useful for custom apps that
        # need external files, but deck delivery defaults to inline because
        # Miaoda/Miaobi hosts have historically served only the entry HTML in
        # some contexts.
        return publish_dir, prep
    inline_step = subprocess_record(
        [sys.executable, str(INLINE_ASSETS), str(html_path), "--out", str(target_html)],
        cwd=REPO,
        log_path=output_dir / "publisher-miaoda-inline-assets.log",
    )
    prep["inline_step"] = summarize_step(inline_step)
    if not inline_step["ok"]:
        raise RuntimeError(inline_step["stderr"] or inline_step["stdout"] or "inline-assets failed")
    prep["size_bytes"] = target_html.stat().st_size
    return publish_dir, prep


def publish_miaoda(
    *,
    html_path: Path,
    output_dir: Path,
    title: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    if args.dry_run or args.miaoda_dry_run:
        dry_app_id = args.miaoda_app_id or "app_dryrun"
        payload = {
            "target": "miaoda",
            "enabled": True,
            "ok": True,
            "dry_run": True,
            "app_url": f"https://miaoda.feishu.cn/app/{dry_app_id}",
            "app_id": dry_app_id,
            "html": repo_rel(html_path),
            "publish_dir": "",
            "mode": "dry-run",
            "reason": "dry-run",
        }
        write_publish_reports(output_dir, payload)
        return payload

    try:
        publish_dir, prep = prepare_miaoda_publish_dir(html_path=html_path, output_dir=output_dir, args=args)
    except Exception as exc:
        payload = {
            "target": "miaoda",
            "enabled": True,
            "ok": False,
            "dry_run": False,
            "app_url": "",
            "app_id": args.miaoda_app_id or "",
            "html": repo_rel(html_path),
            "publish_dir": "",
            "mode": "prepare-failed",
            "reason": f"prepare Miaoda publish payload failed: {exc}",
        }
        write_publish_reports(output_dir, payload)
        return payload

    app_id = args.miaoda_app_id.strip() if args.miaoda_app_id else ""
    create_step: dict[str, Any] | None = None
    if not app_id:
        app_name = args.miaoda_name or title or html_path.stem
        create_step = subprocess_record(
            ["lark-cli", "apps", "+create", "--name", app_name, "--app-type", "HTML"],
            cwd=REPO,
            log_path=output_dir / "publisher-miaoda-create.log",
        )
        if not create_step["ok"]:
            payload = {
                "target": "miaoda",
                "enabled": True,
                "ok": False,
                "dry_run": False,
                "app_url": "",
                "app_id": "",
                "html": repo_rel(html_path),
                "publish_dir": repo_rel(publish_dir),
                "mode": prep.get("mode"),
                "reason": "apps +create failed: " + parse_lark_cli_error(create_step),
                "steps": [{"name": "apps +create", **summarize_step(create_step)}],
            }
            write_publish_reports(output_dir, payload)
            return payload
        parsed_create = parse_miaoda_publish_stdout(create_step["stdout"])
        app_id = parsed_create["app_id"]
    publish_step = subprocess_record(
        ["lark-cli", "apps", "+html-publish", "--app-id", app_id, "--path", repo_rel(publish_dir)],
        cwd=REPO,
        log_path=output_dir / "publisher-miaoda-html-publish.log",
    )
    parsed_publish: dict[str, str] = {}
    if publish_step["ok"]:
        parsed_publish = parse_miaoda_publish_stdout(publish_step["stdout"])
    app_url = parsed_publish.get("url", "")
    steps = []
    if create_step:
        steps.append({"name": "apps +create", **summarize_step(create_step)})
    steps.append({"name": "apps +html-publish", **summarize_step(publish_step)})
    payload = {
        "target": "miaoda",
        "enabled": True,
        "ok": bool(publish_step["ok"] and app_url),
        "dry_run": False,
        "app_url": app_url,
        "app_id": app_id,
        "html": repo_rel(html_path),
        "publish_dir": repo_rel(publish_dir),
        "mode": prep.get("mode"),
        "prepared": prep,
        "steps": steps,
        "reason": "" if publish_step["ok"] and app_url else ("apps +html-publish failed: " + parse_lark_cli_error(publish_step)),
    }
    write_publish_reports(output_dir, payload)
    return payload


def contains_data_image(html_path: Path) -> bool:
    try:
        html = html_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return bool(re.search(r"data:image/[A-Za-z0-9.+-]+", html, re.I))


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

    working_html = html_path
    if not args.skip_magic_asset_prepare:
        uploader = args.magic_asset_uploader or optional_path(os.environ.get("FEISHU_DECK_H5_MAGIC_ASSET_UPLOADER", "")) or DEFAULT_MAGIC_ASSET_UPLOADER
        prepared = output_dir / "magic-page-inline.html"
        inline = subprocess_record(
            [sys.executable, str(INLINE_ASSETS), str(html_path), "--out", str(prepared)],
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
    if payload.get("target") == "miaoda":
        write_json(output_dir / "miaoda-publish.json", payload)
        report_name = "MIAODA_PUBLISH.md"
        title = "Feishu/Miaobi Miaoda Publish"
    else:
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


def slide_library_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    root = args.slide_library_root or optional_path(os.environ.get("FEISHU_SLIDE_LIBRARY_ROOT", "")) or DEFAULT_SLIDE_LIBRARY_ROOT
    root = root.expanduser().resolve()
    skill_dir = args.slide_library_skill_dir or root / "skills/feishu-slide-library"
    skill_dir = skill_dir.expanduser().resolve()
    return root, skill_dir


def ingest_with_slide_library(
    *,
    html_path: Path,
    output_dir: Path,
    title: str,
    task_id: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    deck_id = args.deck_id or slugify(title or task_id, "deck")
    job_id = args.job_id or slugify(task_id.replace("/", "-"), deck_id)
    library_root, skill_dir = slide_library_paths(args)
    staging_root = (args.staging_root or output_dir / "feishu-slide-library-ingest").expanduser().resolve()
    bootstrap = skill_dir / "assets/bootstrap-library.py"
    ingest_package = skill_dir / "assets/ingest-package.py"
    confirm_ingest = skill_dir / "assets/confirm-ingest.py"
    required = [bootstrap, ingest_package, confirm_ingest]
    result: dict[str, Any] = {
        "target": "feishu-slide-library",
        "repo": SLIDE_LIBRARY_REPO,
        "deck_id": deck_id,
        "job_id": job_id,
        "library_root": str(library_root),
        "skill_dir": str(skill_dir),
        "staging_root": str(staging_root),
        "ready_for_confirm": False,
        "confirmed": False,
        "ok": False,
        "dry_run": bool(args.dry_run),
        "steps": [],
        "ingest_result_path": "",
        "pr": {},
        "reason": "",
    }
    if args.dry_run:
        result.update(
            {
                "ok": True,
                "ready_for_confirm": True,
                "confirmed": False,
                "reason": "dry-run; external feishu-slide-library scripts not executed",
            }
        )
        return result
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        result["reason"] = "missing feishu-slide-library scripts: " + ", ".join(missing)
        return result
    bootstrap_cmd = [
        sys.executable,
        str(bootstrap),
        "--library-root",
        str(library_root),
        "--repo-url",
        SLIDE_LIBRARY_REPO,
        "--branch",
        args.slide_library_branch,
    ]
    if args.slide_library_offline:
        bootstrap_cmd.append("--offline")
    bootstrap_step = subprocess_record(bootstrap_cmd, cwd=REPO, log_path=output_dir / "publisher-slide-library-bootstrap.log")
    result["steps"].append({"name": "bootstrap-library", **summarize_step(bootstrap_step)})
    if not bootstrap_step["ok"]:
        result["reason"] = bootstrap_step["stderr"] or bootstrap_step["stdout"] or "bootstrap-library failed"
        return result

    ingest_cmd = [
        sys.executable,
        str(ingest_package),
        str(html_path),
        "--deck-id",
        deck_id,
        "--job-id",
        job_id,
        "--library-root",
        str(library_root),
        "--staging-root",
        str(staging_root),
        "--submitted-by",
        args.submitted_by or args.contributor or "gtm",
        "--overwrite",
    ]
    if args.submitted_by_id:
        ingest_cmd.extend(["--submitted-by-id", args.submitted_by_id])
    ingest_step = subprocess_record(ingest_cmd, cwd=REPO, log_path=output_dir / "publisher-slide-library-ingest.log")
    result["steps"].append({"name": "ingest-package", **summarize_step(ingest_step)})
    if not ingest_step["ok"]:
        result["reason"] = ingest_step["stderr"] or ingest_step["stdout"] or "ingest-package failed"
        return result
    ingest_payload = ingest_step["json"] if isinstance(ingest_step["json"], dict) else {}
    result["ready_for_confirm"] = bool(ingest_payload.get("ready_for_confirm"))
    result["ingest_result_path"] = str(ingest_payload.get("ingest_result_path") or "")
    result["assessment_path"] = str(ingest_payload.get("assessment_path") or "")
    result["review_candidates"] = str(ingest_payload.get("review_candidates") or "")
    result["ingest_report"] = str(ingest_payload.get("ingest_report") or "")
    if not result["ready_for_confirm"]:
        result["reason"] = "ingest-package produced ready_for_confirm=false"
        return result
    if args.no_confirm_ingest:
        result["ok"] = True
        result["reason"] = "ready_for_confirm; confirm-ingest skipped by --no-confirm-ingest"
        return result

    ingest_result_path = Path(result["ingest_result_path"])
    if not ingest_result_path.exists():
        result["reason"] = f"ingest_result.json not found: {ingest_result_path}"
        return result
    confirm_cmd = [
        sys.executable,
        str(confirm_ingest),
        str(ingest_result_path),
        "--library-root",
        str(library_root),
    ]
    if args.confirm_dry_run:
        confirm_cmd.append("--dry-run")
    if args.auto_merge:
        confirm_cmd.append("--auto-merge")
    if args.wait_viewer:
        confirm_cmd.append("--wait-viewer")
    confirm_step = subprocess_record(confirm_cmd, cwd=REPO, log_path=output_dir / "publisher-slide-library-confirm.log")
    result["steps"].append({"name": "confirm-ingest", **summarize_step(confirm_step)})
    result["confirmed"] = confirm_step["ok"]
    result["ok"] = confirm_step["ok"]
    result["pr"] = confirm_step["json"] if isinstance(confirm_step["json"], dict) else {}
    result["reason"] = "" if confirm_step["ok"] else (confirm_step["stderr"] or confirm_step["stdout"] or "confirm-ingest failed")
    return result


def summarize_step(step: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": step["ok"],
        "returncode": step["returncode"],
        "stderr": step["stderr"][:1200],
        "stdout": step["stdout"][:1200],
    }


def report_md(manifest: dict[str, Any]) -> str:
    publication = manifest.get("publication") or {}
    library_ingest = manifest.get("library_ingest") or {}
    lines = [
        "# Publisher Report",
        "",
        f"- task_id: `{manifest.get('task_id', '')}`",
        f"- source: `{manifest.get('source', '')}`",
        f"- dry_run: {manifest.get('dry_run', False)}",
        f"- publish_ok: {publication.get('ok')}",
        f"- publication_target: {publication.get('target') or ''}",
        f"- publication_url: {publication.get('app_url') or ''}",
        f"- library_ingest_ok: {library_ingest.get('ok')}",
        f"- library_deck_id: {library_ingest.get('deck_id') or ''}",
        "",
    ]
    if library_ingest.get("ingest_report"):
        lines.append(f"- ingest_report: `{library_ingest.get('ingest_report')}`")
    if library_ingest.get("review_candidates"):
        lines.append(f"- review_candidates: `{library_ingest.get('review_candidates')}`")
    if publication.get("reason"):
        lines.extend(["", "## Publish note", str(publication.get("reason"))])
    if library_ingest.get("reason"):
        lines.extend(["", "## Library ingest note", str(library_ingest.get("reason"))])
    if manifest.get("skipped"):
        lines.extend(["", "## Skipped"])
        for item in manifest["skipped"]:
            lines.append(f"- `{item.get('slide_key', item.get('type', 'item'))}` · {item.get('reason')}")
    lines.append("")
    return "\n".join(lines)


def register_ppt_library(args: argparse.Namespace) -> int:
    metadata = {
        "title": args.title,
        "summary": args.summary,
        "thumbnail": args.thumbnail,
        "industry": normalize_list(args.industry, ["待标注"]),
        "product": normalize_list(args.product, ["待标注"]),
        "customer_stage": normalize_list(args.customer_stage, ["待标注"]),
        "deck_type": normalize_list(args.deck_type, ["用户自选 PPT"]),
        "value_prop": normalize_list(args.value_prop, []),
        "tags": normalize_list(args.tag, ["ppt-upload", "needs-review"]),
        "source_level": args.source_level,
        "owner": args.owner,
        "reviewer": args.reviewer,
        "contributor": args.contributor or args.owner or "gtm",
        "contributed_at": args.contributed_at or now_iso(),
        "permission_status": args.permission_status,
    }
    result = slide_library.register_ppt_upload(args.ppt_library, metadata, pages=args.ppt_page)
    manifest: dict[str, Any] = {
        "source": result["source"],
        "slide_count": result["slide_count"],
        "local_candidates": result["registered"],
        "base_writes": [],
        "skipped": result.get("skipped", []),
    }
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--task-id")
    ap.add_argument("--html", type=Path, help="confirmed .html/.htm artifact to publish and ingest")
    ap.add_argument("--deck-id", default="", help="feishu-slide-library deck_id; defaults to a slug from title/task")
    ap.add_argument("--job-id", default="", help="feishu-slide-library job id; defaults to task/deck id")
    ap.add_argument("--title")
    ap.add_argument("--allow-unaudited", action="store_true", help="bypass deck-validator pass requirement for local/debug use")
    ap.add_argument("--dry-run", action="store_true", help="simulate publishing and feishu-slide-library ingest without external writes")

    ap.add_argument(
        "--publish-target",
        choices=["miaoda", "magic-page", "auto"],
        default=DEFAULT_PUBLISH_TARGET,
        help="cloud publish target. Default is magic-page: publish confirmed HTML to Miaobi HTML Box.",
    )

    ap.add_argument("--miaoda-app-id", default="", help="existing Miaoda app_id; omitted means create a new HTML app with current Feishu user")
    ap.add_argument("--miaoda-name", default="", help="Miaoda app name when creating a new app; defaults to --title")
    ap.add_argument("--miaoda-publish-dir", type=Path, help="staging dir for Miaoda publish payload")
    ap.add_argument("--miaoda-linked", action="store_true", help="publish linked HTML directory instead of default single-file inline HTML")
    ap.add_argument("--miaoda-dry-run", action="store_true", help="dry-run Miaoda branch only")

    ap.add_argument("--magic-page-script", type=Path)
    ap.add_argument("--magic-asset-uploader", type=Path)
    ap.add_argument("--magic-base-url", default="")
    ap.add_argument("--magic-page-dry-run", action="store_true")
    ap.add_argument("--magic-page-open-source", action="store_true")
    ap.add_argument("--skip-magic-asset-prepare", action="store_true")

    ap.add_argument("--slide-library-root", type=Path)
    ap.add_argument("--slide-library-skill-dir", type=Path)
    ap.add_argument("--slide-library-branch", default="main")
    ap.add_argument("--slide-library-offline", action="store_true")
    ap.add_argument("--publish-only", action="store_true", help="publish the confirmed HTML and skip feishu-slide-library ingestion")
    ap.add_argument("--staging-root", type=Path)
    ap.add_argument("--submitted-by", default="")
    ap.add_argument("--submitted-by-id", default="")
    ap.add_argument("--no-confirm-ingest", action="store_true", help="stop after ingest-package.py is ready_for_confirm")
    ap.add_argument("--confirm-dry-run", action="store_true", help="call confirm-ingest.py --dry-run")
    ap.add_argument("--auto-merge", action="store_true")
    ap.add_argument("--wait-viewer", action="store_true")

    ap.add_argument("--ppt-library", type=Path, help="register a user-selected PPT/PPTX into the local selectable library")
    ap.add_argument("--ppt-page", action="append", type=int, default=[])
    ap.add_argument("--slide-key", action="append", default=[], help="compatibility: emitted in dry-run slide_records")
    ap.add_argument("--industry", action="append", default=[])
    ap.add_argument("--product", action="append", default=[])
    ap.add_argument("--customer-stage", action="append", default=[])
    ap.add_argument("--deck-type", action="append", default=[])
    ap.add_argument("--value-prop", action="append", default=[])
    ap.add_argument("--tag", action="append", default=[])
    ap.add_argument("--source-level", default="internal-draft")
    ap.add_argument("--owner", default="gtm")
    ap.add_argument("--reviewer", default="")
    ap.add_argument("--contributor", default="")
    ap.add_argument("--contributed-at", default="")
    ap.add_argument("--summary", default="")
    ap.add_argument("--thumbnail", default="")
    ap.add_argument("--permission-status", default="needs_review")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.ppt_library:
        return register_ppt_library(args)
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
        raise SystemExit("publisher: deck-validator pass verdict is required before publishing and ingestion")

    html_path = resolve_html(args, output_dir)
    title = args.title or (read_json(output_dir / "deck.json").get("title") if (output_dir / "deck.json").exists() else "") or (html_path.stem if html_path else task_id)

    manifest: dict[str, Any] = {
        "task_id": task_id,
        "source": repo_rel(html_path) if html_path else str((output_dir / "deck.json").relative_to(REPO)) if (output_dir / "deck.json").exists() else "",
        "local_candidates": [],
        "knowledge_records": [],
        "asset_records": [],
        "slide_records": [],
        "base_writes": [],
        "skipped": [],
        "dry_run": args.dry_run,
        "local_write_enabled": False,
        "publication": {},
        "library_ingest": {},
        "validation": {
            "schema": "skills/feishu-deck-h5/schema/ingestion-manifest.schema.json",
            "validated": False,
        },
    }

    if (output_dir / "deck.json").exists():
        deck = read_json(output_dir / "deck.json")
        for slide_key in selected_slide_keys(deck, args.slide_key):
            manifest["slide_records"].append({
                "type": "slide",
                "mode": "dry-run" if args.dry_run else "local",
                "ok": True,
                "slide_key": slide_key,
                "path": "",
            })

    if html_path:
        if args.publish_target == "miaoda":
            publication = publish_miaoda(html_path=html_path, output_dir=output_dir, title=title, args=args)
        elif args.publish_target == "auto":
            publication = publish_magic_page(html_path=html_path, output_dir=output_dir, title=title, task_id=task_id, args=args)
            if not publication.get("ok"):
                fallback = publish_miaoda(html_path=html_path, output_dir=output_dir, title=title, args=args)
                fallback["fallback_from"] = publication
                publication = fallback
        else:
            publication = publish_magic_page(html_path=html_path, output_dir=output_dir, title=title, task_id=task_id, args=args)
        manifest["publication"] = publication
        if publication.get("ok"):
            if args.publish_only:
                manifest["library_ingest"] = {
                    "ok": True,
                    "skipped": True,
                    "target": "feishu-slide-library",
                    "reason": "publish-only; feishu-slide-library ingestion skipped",
                }
                manifest["skipped"].append({"type": "library_ingest", "reason": "publish-only"})
            else:
                manifest["library_ingest"] = ingest_with_slide_library(
                    html_path=html_path,
                    output_dir=output_dir,
                    title=title,
                    task_id=task_id,
                    args=args,
                )
        else:
            manifest["library_ingest"] = {"ok": False, "reason": "skipped because cloud publish failed"}
    else:
        manifest["publication"] = {"ok": True, "dry_run": True, "reason": "no HTML artifact; compatibility dry-run only"}
        manifest["library_ingest"] = {"ok": True, "dry_run": True, "reason": "no HTML artifact; compatibility dry-run only"}
        manifest["skipped"].append({"type": "publish", "reason": "confirmed HTML not provided"})

    manifest_path = output_dir / "ingestion-manifest.json"
    report_path = output_dir / "INGESTION_REPORT.md"
    write_json(manifest_path, manifest)
    report_path.write_text(report_md(manifest), encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), "report": str(report_path), **manifest}, ensure_ascii=False, indent=2, sort_keys=True))

    publish_ok = bool((manifest.get("publication") or {}).get("ok"))
    ingest_ok = bool((manifest.get("library_ingest") or {}).get("ok"))
    return 0 if publish_ok and ingest_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
