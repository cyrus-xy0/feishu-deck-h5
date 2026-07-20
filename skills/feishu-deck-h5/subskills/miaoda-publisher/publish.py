#!/usr/bin/env python3
"""Publish one deck per Miaoda HTML app and refresh a separate catalog app."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


SKILL_ROOT = Path(__file__).resolve().parents[2]
COPY_ASSETS = SKILL_ROOT / "assets" / "copy-assets.py"
VERIFY_PORTABLE = SKILL_ROOT / "assets" / "verify-portable.py"
SHOOT_PAGE = SKILL_ROOT / "assets" / "shoot-page.py"
HTML_LIMIT = 10 * 1024 * 1024
TOTAL_LIMIT = 200 * 1024 * 1024
ARCHIVE_LIMIT = 20 * 1024 * 1024
READONLY_POLICY_META = '<meta name="fs-deck-edit-policy" content="readonly">'
READONLY_GUARD_MARKER = "data-fs-miaoda-readonly-guard"
MIAODA_COVER_COMPAT_MARKER = "data-fs-miaoda-cover-compat"
MIAODA_COVER_FRAME_MARKER = "data-fs-miaoda-cover-frame"
MIAODA_COVER_COMPAT_STYLE = """  <style data-fs-miaoda-cover-compat>
  .deck[data-mode="present"] .slide-frame[data-fs-miaoda-cover-frame] {
    background: #000 url("__MIAODA_COVER_DATA_URI__") center/cover no-repeat !important;
  }
  .slide-frame[data-fs-miaoda-cover-frame] > .slide[data-layout="cover"] .wordmark {
    background-image: url("__MIAODA_LOGO_DATA_URI__") !important;
  }
  </style>"""
READONLY_GUARD = """  <script data-fs-miaoda-readonly-guard>
  (() => {
    window.addEventListener('keydown', (event) => {
      const target = event.target;
      const inField = target && (
        target.isContentEditable ||
        ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
      );
      if (
        inField || event.isComposing || event.keyCode === 229 ||
        (event.key || '').toLowerCase() !== 'e' ||
        event.metaKey || event.ctrlKey || event.altKey || event.shiftKey
      ) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      document.getElementById('fs-miaoda-readonly-toast')?.remove();
      const toast = document.createElement('div');
      toast.id = 'fs-miaoda-readonly-toast';
      toast.setAttribute('role', 'status');
      toast.textContent = '当前为妙搭线上只读版本。请修改本地源 Deck 后重新发布。';
      Object.assign(toast.style, {
        position: 'fixed',
        left: '50%',
        bottom: '28px',
        transform: 'translateX(-50%)',
        zIndex: '2147483647',
        padding: '10px 16px',
        borderRadius: '8px',
        background: 'rgba(28, 31, 35, .94)',
        color: '#fff',
        font: '14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
        boxShadow: '0 6px 20px rgba(0, 0, 0, .24)'
      });
      (document.body || document.documentElement).appendChild(toast);
      window.setTimeout(() => toast.remove(), 3600);
    }, true);
  })();
  </script>"""
STATIC_SUFFIXES = {
    ".avif", ".css", ".gif", ".htm", ".html", ".ico", ".jpeg", ".jpg",
    ".js", ".json", ".m4a", ".mjs", ".mov", ".mp3", ".mp4", ".ogg",
    ".otf", ".png", ".svg", ".ttf", ".wasm", ".wav", ".webm", ".webp",
    ".woff", ".woff2", ".xml",
}
RESOURCE_DIRS = ("assets", "input", "prototypes", "static", "logos")
APP_ID_RE = re.compile(r"^app_[A-Za-z0-9]+$")
INPUT_REF_RE = re.compile(
    r"""(?P<ref>(?:\.\./)*input/[^'"()<>\s?#]+)""",
    re.IGNORECASE,
)


class PublishError(RuntimeError):
    pass


def find_project_root() -> Path:
    for parent in (SKILL_ROOT, *SKILL_ROOT.parents):
        try:
            if (parent / "skills" / "feishu-deck-h5").resolve() == SKILL_ROOT:
                return parent
        except OSError:
            continue
    return SKILL_ROOT


PROJECT_ROOT = find_project_root()
RUNS = PROJECT_ROOT / "runs"
DEFAULT_CATALOG_ROOT = Path(
    os.environ.get(
        "FEISHU_DECK_H5_MIAODA_ROOT",
        str(RUNS / "miaoda-publisher"),
    )
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def read_json(path: Path, *, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.is_file():
        return {} if default is None else dict(default)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError(f"invalid JSON state file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PublishError(f"invalid JSON state file {path}: expected object")
    return payload


def slugify(value: str, fallback_seed: str) -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    if value:
        return value[:80].rstrip("-")
    digest = hashlib.sha256(fallback_seed.encode("utf-8")).hexdigest()[:10]
    return f"deck-{digest}"


def extract_title(source: Path) -> str:
    deck_json = source.parent / "deck.json"
    if deck_json.is_file():
        try:
            value = json.loads(deck_json.read_text(encoding="utf-8")).get("title")
        except (OSError, json.JSONDecodeError, AttributeError):
            value = ""
        if str(value or "").strip():
            return str(value).strip()
    text = source.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    if match:
        value = re.sub(r"\s+", " ", html.unescape(match.group(1))).strip()
        if value:
            return value
    return source.parent.name or source.stem


def resolve_source(args: argparse.Namespace) -> Path:
    if args.html:
        source = args.html.expanduser().resolve()
    else:
        run = (RUNS / args.task_id).resolve()
        candidates = (run / "output" / "index.html", run / "index.html")
        source = next((path for path in candidates if path.is_file()), candidates[0])
    if not source.is_file() or source.suffix.lower() not in {".html", ".htm"}:
        raise PublishError(f"confirmed HTML not found: {source}")
    return source


def source_run_root(source: Path) -> Path | None:
    parent = source.parent
    if parent.name == "output" and parent.parent.parent.name == "runs":
        return parent.parent
    if parent.parent.name == "runs":
        return parent
    return None


def copy_static_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        return
    for candidate in sorted(source.rglob("*")):
        relative = candidate.relative_to(source)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if candidate.is_symlink():
            # A run may keep assets/shared as a link to the canonical skill pool.
            # Do not traverse or copy that link here: copy-assets.py --shared=copy
            # materializes only the shared files referenced by the staged HTML.
            if candidate.is_dir():
                continue
            raise PublishError(f"refusing to publish symlinked resource: {candidate}")
        if not candidate.is_file() or candidate.suffix.lower() not in STATIC_SUFFIXES:
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, target)


def restore_missing_input_refs(output: Path, run_input: Path) -> None:
    if not run_input.is_dir():
        return
    output_root = output.resolve()
    for document in sorted(output.rglob("*.htm*")):
        text = document.read_text(encoding="utf-8", errors="ignore")
        for match in INPUT_REF_RE.finditer(text):
            ref = match.group("ref")
            marker = ref.lower().find("input/")
            relative = Path(ref[marker + len("input/"):])
            source = (run_input / relative).resolve()
            try:
                source.relative_to(run_input.resolve())
            except ValueError:
                continue
            destination = (document.parent / ref).resolve()
            try:
                destination.relative_to(output_root)
            except ValueError:
                continue
            if destination.exists() or not source.is_file():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def copy_referenced_sibling_dirs(source: Path, output: Path) -> None:
    text = source.read_text(encoding="utf-8", errors="ignore")
    for candidate in sorted(source.parent.iterdir()):
        if (
            not candidate.is_dir()
            or candidate.name.startswith(".")
            or candidate.name in RESOURCE_DIRS
            or f"{candidate.name}/" not in text
        ):
            continue
        copy_static_tree(candidate, output / candidate.name)


def run_checked(command: list[str], *, cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PublishError(f"command failed to start: {command[0]}: {exc}") from exc
    if result.returncode:
        reason = (result.stderr or result.stdout).strip()
        raise PublishError(reason or f"command failed with exit {result.returncode}")
    return result


def tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


def measure_site(site: Path) -> dict[str, Any]:
    files = sorted(path for path in site.rglob("*") if path.is_file())
    if not (site / "index.html").is_file():
        raise PublishError(f"site root is missing index.html: {site}")
    oversized_html = [
        {
            "path": path.relative_to(site).as_posix(),
            "bytes": path.stat().st_size,
        }
        for path in files
        if path.suffix.lower() in {".html", ".htm"} and path.stat().st_size > HTML_LIMIT
    ]
    total_bytes = sum(path.stat().st_size for path in files)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz") as archive_file:
        with tarfile.open(fileobj=archive_file, mode="w:gz") as archive:
            for path in files:
                archive.add(path, arcname=path.relative_to(site).as_posix(), recursive=False)
        archive_file.flush()
        archive_bytes = os.fstat(archive_file.fileno()).st_size
    report = {
        "file_count": len(files),
        "total_bytes": total_bytes,
        "archive_bytes": archive_bytes,
        "oversized_html": oversized_html,
        "limits": {
            "html_bytes": HTML_LIMIT,
            "total_bytes": TOTAL_LIMIT,
            "archive_bytes": ARCHIVE_LIMIT,
        },
    }
    failures: list[str] = []
    if oversized_html:
        failures.append(
            "HTML over 10 MB: "
            + ", ".join(f"{item['path']} ({item['bytes']} bytes)" for item in oversized_html)
        )
    if total_bytes > TOTAL_LIMIT:
        failures.append(f"uncompressed site is {total_bytes} bytes (limit {TOTAL_LIMIT})")
    if archive_bytes > ARCHIVE_LIMIT:
        failures.append(f"tar.gz is {archive_bytes} bytes (limit {ARCHIVE_LIMIT})")
    if failures:
        raise PublishError("Miaoda size gate failed: " + "; ".join(failures))
    return report


def apply_miaoda_readonly_policy(index_path: Path) -> None:
    text = index_path.read_text(encoding="utf-8")
    policy = re.search(
        r"""<meta\b[^>]*\bname\s*=\s*["']fs-deck-edit-policy["'][^>]*>""",
        text,
        re.IGNORECASE,
    )
    if policy and not re.search(
        r"""\bcontent\s*=\s*["']readonly["']""",
        policy.group(0),
        re.IGNORECASE,
    ):
        raise PublishError("source HTML declares a conflicting fs-deck-edit-policy")
    if policy and READONLY_GUARD_MARKER in text:
        return
    closing_head = re.search(r"</head\s*>", text, re.IGNORECASE)
    if not closing_head:
        raise PublishError("source HTML is missing </head>; cannot apply Miaoda readonly policy")
    additions = []
    if not policy:
        additions.append(f"  {READONLY_POLICY_META}")
    if READONLY_GUARD_MARKER not in text:
        additions.append(READONLY_GUARD)
    insertion = "\n".join(additions) + "\n"
    atomic_write(
        index_path,
        text[:closing_head.start()] + insertion + text[closing_head.start():],
    )


def apply_miaoda_cover_compatibility(index_path: Path) -> None:
    text = index_path.read_text(encoding="utf-8")
    if (
        MIAODA_COVER_COMPAT_MARKER in text
        and "data:image/jpeg;base64," in text
        and "data:image/png;base64," in text
    ):
        return
    text = re.sub(
        r"""\s*<style\b[^>]*\bdata-fs-miaoda-cover-compat\b[^>]*>.*?</style>""",
        "\n",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cover_frame = re.compile(
        r"""(?P<frame><div\b[^>]*\bclass\s*=\s*["'][^"']*\bslide-frame\b[^"']*["'][^>]*>)"""
        r"""(?P<gap>\s*)"""
        r"""(?=<div\b[^>]*\bclass\s*=\s*["'][^"']*\bslide\b[^"']*["'][^>]*"""
        r"""\bdata-layout\s*=\s*["']cover["'][^>]*>)""",
        re.IGNORECASE,
    )
    marked_cover_frame = re.search(
        r"""<div\b[^>]*\bdata-fs-miaoda-cover-frame\b[^>]*>""",
        text,
        re.IGNORECASE,
    )
    if marked_cover_frame:
        rewritten, count = text, 1
    else:
        rewritten, count = cover_frame.subn(
            lambda match: (
                match.group("frame")[:-1]
                + f" {MIAODA_COVER_FRAME_MARKER}>"
                + match.group("gap")
            ),
            text,
        )
    if count == 0:
        return
    cover_asset = index_path.parent / "assets" / "lark-cover-bg.jpg"
    logo_asset = index_path.parent / "assets" / "lark-logo.png"
    for asset in (cover_asset, logo_asset):
        if not asset.is_file():
            raise PublishError(
                f"Miaoda cover compatibility asset not found: "
                f"{asset.relative_to(index_path.parent)}"
            )
    cover_data_uri = (
        "data:image/jpeg;base64,"
        + base64.b64encode(cover_asset.read_bytes()).decode("ascii")
    )
    logo_data_uri = (
        "data:image/png;base64,"
        + base64.b64encode(logo_asset.read_bytes()).decode("ascii")
    )
    compatibility_style = (
        MIAODA_COVER_COMPAT_STYLE
        .replace("__MIAODA_COVER_DATA_URI__", cover_data_uri)
        .replace("__MIAODA_LOGO_DATA_URI__", logo_data_uri)
    )
    closing_head = re.search(r"</head\s*>", rewritten, re.IGNORECASE)
    if not closing_head:
        raise PublishError(
            "source HTML is missing </head>; cannot apply Miaoda cover compatibility"
        )
    atomic_write(
        index_path,
        rewritten[:closing_head.start()]
        + compatibility_style
        + "\n"
        + rewritten[closing_head.start():],
    )


def copy_catalog_brand_assets(catalog_site: Path) -> None:
    destination = catalog_site / "assets"
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("lark-cover-bg.jpg", "lark-logo.png"):
        source = SKILL_ROOT / "assets" / name
        if not source.is_file():
            raise PublishError(f"catalog brand asset not found: {name}")
        shutil.copy2(source, destination / name)


def capture_catalog_cover(deck_site: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.stem}.{uuid.uuid4().hex}{destination.suffix}"
    )
    try:
        run_checked(
            [
                sys.executable,
                str(SHOOT_PAGE),
                str(deck_site / "index.html"),
                "1",
                "--out",
                str(temporary),
                "--wait",
                "400",
                "--cap",
                "30",
                "--hide-ui",
                "--viewport",
                "960x540",
            ],
            cwd=PROJECT_ROOT,
            timeout=45,
        )
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise PublishError("cover capture completed without a non-empty image")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_site(source: Path, staging_root: Path, slug: str) -> tuple[Path, dict[str, Any]]:
    fake_run = staging_root / "runs" / slug
    output = fake_run / "output"
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output / "index.html")
    for name in RESOURCE_DIRS:
        copy_static_tree(source.parent / name, output / name)
    copy_referenced_sibling_dirs(source, output)
    run_root = source_run_root(source)
    if run_root is not None:
        copy_static_tree(run_root / "input", fake_run / "input")
        for name in ("assets", "prototypes", "static", "logos"):
            if not (output / name).exists():
                copy_static_tree(run_root / name, output / name)
    run_checked(
        [sys.executable, str(COPY_ASSETS), str(output), "--shared=copy"],
        cwd=PROJECT_ROOT,
    )
    apply_miaoda_readonly_policy(output / "index.html")
    apply_miaoda_cover_compatibility(output / "index.html")
    # Nested prototype pages can use ../../input/... which resolves to
    # output/input rather than the fake run's input directory. copy-assets
    # may not associate those nested references with the root deck, so restore
    # only the missing files that published HTML actually references.
    if run_root is not None:
        restore_missing_input_refs(output, run_root / "input")
    run_checked(
        [sys.executable, str(VERIFY_PORTABLE), str(output), "--quiet"],
        cwd=PROJECT_ROOT,
    )
    return output, measure_site(output)


def replace_tree(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = destination.with_name(f".{destination.name}.backup-{uuid.uuid4().hex}")
    if destination.exists():
        destination.rename(backup)
    try:
        source.rename(destination)
    except BaseException:
        if backup.exists():
            backup.rename(destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def parse_envelope(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    raw = result.stdout.strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PublishError(f"lark-cli returned invalid JSON: {raw[:300]}") from exc
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        error = payload.get("error") if isinstance(payload, dict) else {}
        if not isinstance(error, dict):
            error = {}
        reason = error.get("hint") or error.get("message") or "lark-cli returned ok != true"
        raise PublishError(str(reason))
    return payload


def cli_call(
    cli: str,
    args: list[str],
    *,
    cwd: Path,
    dry_run: bool = False,
    timeout: int = 300,
) -> dict[str, Any]:
    command = [cli, "apps", *args, "--as", "user", "--json"]
    if dry_run:
        command.append("--dry-run")
    env = os.environ.copy()
    env["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"] = "1"
    env["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"] = "1"
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PublishError(f"lark-cli failed to start: {exc}") from exc
    if result.returncode:
        raw = (result.stderr or result.stdout).strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            raise PublishError(raw or f"lark-cli exited {result.returncode}")
        error = payload.get("error") if isinstance(payload, dict) else {}
        if not isinstance(error, dict):
            error = {}
        raise PublishError(str(error.get("hint") or error.get("message") or raw))
    return parse_envelope(result)


def fake_app_id(kind: str, slug: str) -> str:
    digest = hashlib.sha256(f"{kind}:{slug}".encode("utf-8")).hexdigest()[:32]
    return f"app_{digest}"


def validate_app_id(value: str, label: str) -> str:
    if not APP_ID_RE.fullmatch(value):
        raise PublishError(f"{label} must be a Miaoda app_id beginning with app_: {value!r}")
    return value


def ensure_app(
    *,
    cli: str,
    cwd: Path,
    state_path: Path,
    override: str,
    name: str,
    description: str,
    dry_run: bool,
    fake_id: str,
) -> tuple[str, dict[str, Any], bool]:
    state = read_json(state_path)
    saved = str(state.get("app_id") or "")
    if override and saved and override != saved:
        raise PublishError(
            f"app_id mismatch for {state_path}: saved {saved}, requested {override}"
        )
    app_id = override or saved
    if app_id:
        validate_app_id(app_id, "app_id")
        if not dry_run:
            payload = cli_call(cli, ["+get", "--app-id", app_id], cwd=cwd)
            app = (payload.get("data") or {}).get("app") or {}
            if str(app.get("app_type") or "").lower() != "html":
                raise PublishError(f"Miaoda app {app_id} is not an html app")
        return app_id, state, False
    if dry_run:
        cli_call(
            cli,
            [
                "+create", "--name", name, "--app-type", "html",
                "--description", description,
            ],
            cwd=cwd,
            dry_run=True,
        )
        return fake_id, state, True
    payload = cli_call(
        cli,
        [
            "+create", "--name", name, "--app-type", "html",
            "--description", description,
        ],
        cwd=cwd,
    )
    app_id = str((((payload.get("data") or {}).get("app") or {}).get("app_id")) or "")
    validate_app_id(app_id, "created app_id")
    state.update(
        {
            "schema_version": 1,
            "app_id": app_id,
            "app_type": "html",
            "name": name,
            "created_at": state.get("created_at") or now_iso(),
        }
    )
    write_json(state_path, state)
    return app_id, state, True


def site_arg(site: Path, cwd: Path) -> str:
    try:
        relative = site.resolve().relative_to(cwd.resolve())
    except ValueError as exc:
        raise PublishError(f"publish site must be below catalog root: {site}") from exc
    return f"./{relative.as_posix()}"


def canonical_app_url(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme in {"http", "https"}
        and parts.hostname
        and parts.hostname.endswith(".feishuapp.com")
        and re.fullmatch(r"/app/app_[A-Za-z0-9]+", parts.path)
    ):
        parts = parts._replace(path=parts.path + "/")
    return urlunsplit(parts)


def first_slide_url(url: str) -> str:
    parts = urlsplit(canonical_app_url(url))
    return urlunsplit(parts._replace(fragment="1"))


def validate_html_dry_run(payload: dict[str, Any]) -> None:
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise PublishError("lark-cli html dry-run returned invalid data")
    if data.get("path_error"):
        raise PublishError(str(data["path_error"]))
    files = data.get("files") or []
    if not isinstance(files, list) or "index.html" not in files:
        raise PublishError("lark-cli html dry-run did not include root index.html")
    if not isinstance(data.get("file_count"), int) or data["file_count"] <= 0:
        raise PublishError("lark-cli html dry-run returned no files")


def release_url(cli: str, cwd: Path, app_id: str, release_id: str, timeout: int) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = cli_call(
            cli,
            ["+release-get", "--app-id", app_id, "--release-id", release_id],
            cwd=cwd,
            timeout=min(timeout, 300),
        )
        data = payload.get("data") or {}
        release = data.get("release") if isinstance(data, dict) else {}
        if not isinstance(release, dict):
            release = data if isinstance(data, dict) else {}
        status = str(release.get("status") or "").lower()
        if status == "finished":
            url = str(release.get("online_url") or "")
            if not url:
                raise PublishError(f"release {release_id} finished without online_url")
            return canonical_app_url(url)
        if status == "failed":
            raise PublishError(f"Miaoda release {release_id} failed: {release.get('error_logs') or 'no error log'}")
        time.sleep(2)
    raise PublishError(f"Miaoda release {release_id} did not finish within {timeout}s")


def publish_site(
    *,
    cli: str,
    cwd: Path,
    site: Path,
    app_id: str,
    dry_run: bool,
    release_timeout: int,
) -> str:
    payload = cli_call(
        cli,
        ["+html-publish", "--app-id", app_id, "--path", site_arg(site, cwd)],
        cwd=cwd,
        dry_run=dry_run,
        timeout=max(release_timeout, 300),
    )
    if dry_run:
        validate_html_dry_run(payload)
        return f"https://dryrun.invalid/{app_id}"
    data = payload.get("data") or {}
    url = str(data.get("url") or "") if isinstance(data, dict) else ""
    if url:
        return canonical_app_url(url)
    release_id = str(data.get("release_id") or "") if isinstance(data, dict) else ""
    if release_id:
        return release_url(cli, cwd, app_id, release_id, release_timeout)
    raise PublishError("lark-cli html publish returned neither data.url nor data.release_id")


def parse_targets(raw: str) -> list[dict[str, str]]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PublishError(f"invalid targets JSON: {exc}") from exc
    if not isinstance(value, list) or not value:
        raise PublishError("specific scope requires a non-empty targets JSON array")
    targets: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or item.get("type") not in {"user", "department", "chat"} or not item.get("id"):
            raise PublishError("each target must contain type=user|department|chat and id")
        targets.append({"type": str(item["type"]), "id": str(item["id"])})
    return targets


def apply_scope(
    *,
    cli: str,
    cwd: Path,
    app_id: str,
    scope: str,
    targets_json: str,
    require_login: bool | None,
    dry_run: bool,
) -> tuple[str, int]:
    if scope == "keep":
        if targets_json or require_login is not None:
            raise PublishError("scope=keep does not accept targets or require-login")
        return "unchanged", 0
    command = ["+access-scope-set", "--app-id", app_id, "--scope", scope]
    target_count = 0
    if scope == "specific":
        targets = parse_targets(targets_json)
        target_count = len(targets)
        if require_login is not None:
            raise PublishError("specific scope does not accept require-login")
        command += ["--targets", json.dumps(targets, ensure_ascii=False, separators=(",", ":"))]
    elif scope == "public":
        if targets_json:
            raise PublishError("public scope does not accept targets")
        if require_login is None:
            raise PublishError("public scope requires --require-login or --no-require-login")
        command.append(f"--require-login={'true' if require_login else 'false'}")
    elif scope == "tenant":
        if targets_json or require_login is not None:
            raise PublishError("tenant scope does not accept targets or require-login")
    cli_call(cli, command, cwd=cwd, dry_run=dry_run)
    return scope, target_count


def render_catalog(entries: list[dict[str, Any]], catalog_title: str) -> str:
    visible = sorted(
        (entry for entry in entries if entry.get("listed") is True and entry.get("published_url")),
        key=lambda entry: (str(entry.get("category") or ""), str(entry.get("title") or "")),
    )
    categories = sorted({str(entry.get("category") or "未分类") for entry in visible})
    cards = []
    for entry in visible:
        title = html.escape(str(entry.get("title") or entry.get("slug") or "Untitled"))
        description = html.escape(str(entry.get("description") or ""))
        category = html.escape(str(entry.get("category") or "未分类"))
        url = html.escape(first_slide_url(str(entry["published_url"])), quote=True)
        scope = html.escape(str(entry.get("access_scope") or "unknown"))
        cover = str(entry.get("cover_image") or "")
        cover_src = (
            html.escape(cover, quote=True)
            if re.fullmatch(r"covers/[a-z0-9-]+\.(?:png|jpe?g)", cover)
            else ""
        )
        cover_html = (
            f'<div class="cover"><img src="{cover_src}" alt="" loading="lazy"></div>'
            if cover_src
            else '<div class="cover" aria-hidden="true"></div>'
        )
        cards.append(
            f'<a class="card" href="{url}" target="_blank" rel="noopener" '
            f'data-category="{category}" data-search="{html.escape((title + " " + description).lower(), quote=True)}">'
            f'{cover_html}<div class="card-body">'
            f'<div class="meta"><span>{category}</span><span class="scope">{scope}</span></div>'
            f'<h2>{title}</h2><p>{description or "打开独立妙搭应用"}</p>'
            f'<div class="open">打开演示 →</div></div></a>'
        )
    options = "".join(f'<option value="{html.escape(value, quote=True)}">{html.escape(value)}</option>' for value in categories)
    safe_catalog_title = html.escape(catalog_title)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>{safe_catalog_title}</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;background:#f5f6f8;color:#1f2329;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}}
.hero{{position:relative;min-height:320px;padding:54px 24px;overflow:hidden;color:#fff;background:linear-gradient(90deg,rgba(3,6,14,.97) 0%,rgba(3,6,14,.88) 40%,rgba(3,6,14,.32) 72%,rgba(3,6,14,.08) 100%),url("assets/lark-cover-bg.jpg") center 43%/cover no-repeat}}
.hero .wrap{{position:relative;z-index:1}}.hero-logo{{display:block;width:132px;height:auto}}.wrap{{max-width:1120px;margin:auto}}
h1{{margin:28px 0 12px;font-size:42px}}.hero p{{margin:0;opacity:.82}}.tools{{display:flex;gap:12px;margin:28px 0 24px}}
input,select{{height:44px;border:1px solid #d0d3d8;border-radius:10px;background:#fff;padding:0 14px;font-size:15px}}input{{flex:1}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:24px;padding-bottom:64px}}
.card{{display:block;overflow:hidden;border:1px solid #e1e4e8;border-radius:18px;background:#fff;color:inherit;text-decoration:none;box-shadow:0 6px 18px rgba(31,35,41,.06);transition:.2s}}
.card:hover{{transform:translateY(-3px);border-color:#3370ff;box-shadow:0 14px 32px rgba(20,86,240,.16)}}.cover{{aspect-ratio:16/9;overflow:hidden;background:#080b12 url("assets/lark-cover-bg.jpg") center/cover no-repeat}}
.cover img{{display:block;width:100%;height:100%;object-fit:contain;transition:transform .25s ease}}.card:hover .cover img{{transform:scale(1.015)}}.card-body{{padding:20px 22px 22px}}
.meta{{display:flex;justify-content:space-between;color:#646a73;font-size:13px}}
.scope{{padding:2px 8px;border-radius:999px;background:#eef3ff;color:#1456f0}}h2{{margin:20px 0 10px;font-size:21px}}.card p{{margin:0;color:#646a73;line-height:1.6}}
.open{{margin-top:24px;color:#1456f0;font-weight:600}}.empty{{display:none;padding:40px;text-align:center;color:#8f959e}}
@media(max-width:640px){{.hero{{min-height:280px;padding:44px 20px;background-position:68% 43%}}.hero-logo{{width:116px}}h1{{font-size:32px}}.tools{{flex-direction:column}}.grid{{grid-template-columns:1fr;gap:18px}}}}
</style>
</head>
<body>
<header class="hero"><div class="wrap"><img class="hero-logo" src="assets/lark-logo.png" alt="飞书"><h1>{safe_catalog_title}</h1><p>{len(visible)} 个独立妙搭应用 · 每个 Deck 单独管理访问权限</p></div></header>
<main class="wrap">
<div class="tools"><input id="q" type="search" placeholder="搜索标题或说明"><select id="category"><option value="">全部分类</option>{options}</select></div>
<section id="grid" class="grid">{''.join(cards)}</section><div id="empty" class="empty">没有匹配的演示</div>
</main>
<script>
const q=document.querySelector('#q'),c=document.querySelector('#category'),cards=[...document.querySelectorAll('.card')],empty=document.querySelector('#empty');
function filter(){{const s=q.value.trim().toLowerCase(),cat=c.value;let n=0;cards.forEach(card=>{{const show=(!s||card.dataset.search.includes(s))&&(!cat||card.dataset.category===cat);card.style.display=show?'block':'none';if(show)n++}});empty.style.display=n?'none':'block'}}
q.addEventListener('input',filter);c.addEventListener('change',filter);
</script>
</body></html>
"""


def upsert_entry(catalog: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    entries = catalog.get("entries")
    if not isinstance(entries, list):
        entries = []
    by_slug = {
        str(item.get("slug")): item
        for item in entries
        if isinstance(item, dict) and item.get("slug")
    }
    by_slug[str(entry["slug"])] = entry
    return {
        "schema_version": 1,
        "updated_at": now_iso(),
        "entries": sorted(by_slug.values(), key=lambda item: str(item.get("slug") or "")),
    }


def write_receipt(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Miaoda publish",
        "",
        f"- status: `{payload.get('status')}`",
        f"- deck app: `{payload.get('deck_app_id')}`",
        f"- deck URL: {payload.get('deck_url')}",
        f"- catalog app: `{payload.get('catalog_app_id')}`",
        f"- catalog URL: {payload.get('catalog_url')}",
        f"- access scope: `{payload.get('access_scope')}`",
        f"- dry run: `{str(bool(payload.get('dry_run'))).lower()}`",
    ]
    atomic_write(path, "\n".join(lines) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--html", type=Path)
    source.add_argument("--task-id")
    parser.add_argument("--title")
    parser.add_argument("--slug")
    parser.add_argument("--category", default="未分类")
    parser.add_argument("--description", default="")
    parser.add_argument("--unlisted", action="store_true")
    parser.add_argument("--catalog-root", type=Path, default=DEFAULT_CATALOG_ROOT)
    parser.add_argument("--catalog-title", default="飞书方案演示集")
    parser.add_argument("--deck-app-id", default="")
    parser.add_argument("--catalog-app-id", default="")
    parser.add_argument("--scope", choices=("keep", "tenant", "public", "specific"), default="keep")
    parser.add_argument("--targets-json", default="")
    parser.add_argument("--require-login", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--catalog-scope", choices=("keep", "tenant", "public", "specific"), default="keep")
    parser.add_argument("--catalog-targets-json", default="")
    parser.add_argument("--catalog-require-login", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--lark-cli", default=os.environ.get("LARK_CLI", "lark-cli"))
    parser.add_argument("--release-timeout", type=int, default=300)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        source = resolve_source(args)
        title = str(args.title or extract_title(source)).strip()
        if not title:
            raise PublishError("--title cannot be empty")
        slug = slugify(str(args.slug or source.parent.name), str(source))
        catalog_root = args.catalog_root.expanduser().resolve()
        live_deck_state_path = catalog_root / "decks" / slug / "app.json"
        live_catalog_state_path = catalog_root / "catalog" / "app.json"
        work_root = (
            catalog_root / ".dry-run" / slug
            if args.dry_run
            else catalog_root
        )
        if args.dry_run and work_root.exists():
            shutil.rmtree(work_root)
        staging_root = work_root / ".staging" / uuid.uuid4().hex
        prepared, deck_size = prepare_site(source, staging_root, slug)
        deck_site = work_root / "decks" / slug / "site"
        replace_tree(prepared, deck_site)
        shutil.rmtree(staging_root, ignore_errors=True)

        deck_state_source = live_deck_state_path if args.dry_run else work_root / "decks" / slug / "app.json"
        deck_app_id, deck_state, deck_created = ensure_app(
            cli=args.lark_cli,
            cwd=work_root,
            state_path=deck_state_source,
            override=args.deck_app_id,
            name=title,
            description=args.description or f"Feishu Deck H5: {title}",
            dry_run=args.dry_run,
            fake_id=fake_app_id("deck", slug),
        )
        deck_url = publish_site(
            cli=args.lark_cli,
            cwd=work_root,
            site=deck_site,
            app_id=deck_app_id,
            dry_run=args.dry_run,
            release_timeout=args.release_timeout,
        )
        deck_state.update(
            {
                "schema_version": 1,
                "app_id": deck_app_id,
                "app_type": "html",
                "name": title,
                "slug": slug,
                "published_url": deck_url,
                "management_url": f"https://miaoda.feishu.cn/app/{deck_app_id}",
                "content_sha256": tree_sha256(deck_site),
                "published_at": now_iso(),
                "dry_run": bool(args.dry_run),
                "size": deck_size,
            }
        )
        deck_state_path = work_root / "decks" / slug / "app.json"
        write_json(deck_state_path, deck_state)
        access_scope, target_count = apply_scope(
            cli=args.lark_cli,
            cwd=work_root,
            app_id=deck_app_id,
            scope=args.scope,
            targets_json=args.targets_json,
            require_login=args.require_login,
            dry_run=args.dry_run,
        )
        if access_scope == "unchanged":
            access_scope = str(deck_state.get("access_scope") or ("creator" if deck_created else "unknown"))
            target_count = int(deck_state.get("access_target_count") or 0)
        deck_state.update(
            {
                "access_scope": access_scope,
                "access_target_count": target_count,
            }
        )
        write_json(deck_state_path, deck_state)

        live_catalog_path = catalog_root / "catalog" / "catalog.json"
        catalog = read_json(live_catalog_path, default={"schema_version": 1, "entries": []})
        previous_entry = next(
            (
                item
                for item in catalog.get("entries", [])
                if isinstance(item, dict) and item.get("slug") == slug
            ),
            {},
        )
        catalog_dir = work_root / "catalog"
        catalog_site = catalog_dir / "site"
        catalog_site.mkdir(parents=True, exist_ok=True)
        if args.dry_run:
            copy_static_tree(catalog_root / "catalog" / "site" / "covers", catalog_site / "covers")
        copy_catalog_brand_assets(catalog_site)
        cover_image = f"covers/{slug}.jpg"
        cover_path = catalog_site / cover_image
        cover_content_sha256 = str(previous_entry.get("cover_content_sha256") or "")
        if (
            not cover_path.is_file()
            or cover_content_sha256 != deck_state["content_sha256"]
        ):
            try:
                capture_catalog_cover(deck_site, cover_path)
                cover_content_sha256 = str(deck_state["content_sha256"])
            except PublishError as exc:
                shutil.copy2(catalog_site / "assets" / "lark-cover-bg.jpg", cover_path)
                cover_content_sha256 = ""
                print(
                    "miaoda-publisher: warning: cover capture failed; "
                    f"using flower background fallback: {exc}",
                    file=sys.stderr,
                )
        entry = {
            "slug": slug,
            "title": title,
            "description": args.description,
            "category": args.category,
            "published_url": deck_url,
            "access_scope": access_scope,
            "listed": not args.unlisted,
            "content_sha256": deck_state["content_sha256"],
            "cover_image": cover_image,
            "cover_content_sha256": cover_content_sha256,
            "updated_at": now_iso(),
        }
        catalog = upsert_entry(catalog, entry)
        write_json(catalog_dir / "catalog.json", catalog)
        atomic_write(
            catalog_site / "index.html",
            render_catalog(catalog["entries"], args.catalog_title),
        )
        catalog_size = measure_site(catalog_site)

        catalog_state_source = live_catalog_state_path if args.dry_run else catalog_dir / "app.json"
        catalog_app_id, catalog_state, catalog_created = ensure_app(
            cli=args.lark_cli,
            cwd=work_root,
            state_path=catalog_state_source,
            override=args.catalog_app_id,
            name=args.catalog_title,
            description="独立妙搭 Deck 应用导航页",
            dry_run=args.dry_run,
            fake_id=fake_app_id("catalog", args.catalog_title),
        )
        if catalog_app_id == deck_app_id:
            raise PublishError("catalog app_id must be different from every deck app_id")
        catalog_url = publish_site(
            cli=args.lark_cli,
            cwd=work_root,
            site=catalog_site,
            app_id=catalog_app_id,
            dry_run=args.dry_run,
            release_timeout=args.release_timeout,
        )
        catalog_state.update(
            {
                "schema_version": 1,
                "app_id": catalog_app_id,
                "app_type": "html",
                "name": args.catalog_title,
                "published_url": catalog_url,
                "management_url": f"https://miaoda.feishu.cn/app/{catalog_app_id}",
                "content_sha256": tree_sha256(catalog_site),
                "published_at": now_iso(),
                "dry_run": bool(args.dry_run),
                "size": catalog_size,
            }
        )
        write_json(catalog_dir / "app.json", catalog_state)
        catalog_scope, catalog_target_count = apply_scope(
            cli=args.lark_cli,
            cwd=work_root,
            app_id=catalog_app_id,
            scope=args.catalog_scope,
            targets_json=args.catalog_targets_json,
            require_login=args.catalog_require_login,
            dry_run=args.dry_run,
        )
        if catalog_scope == "unchanged":
            catalog_scope = str(
                catalog_state.get("access_scope")
                or ("creator" if catalog_created else "unknown")
            )
            catalog_target_count = int(catalog_state.get("access_target_count") or 0)
        catalog_state.update(
            {
                "access_scope": catalog_scope,
                "access_target_count": catalog_target_count,
            }
        )
        write_json(catalog_dir / "app.json", catalog_state)

        manifest = {
            "status": "dry-run" if args.dry_run else "published",
            "dry_run": bool(args.dry_run),
            "source": str(source),
            "catalog_root": str(work_root),
            "slug": slug,
            "title": title,
            "deck_app_id": deck_app_id,
            "deck_url": deck_url,
            "catalog_app_id": catalog_app_id,
            "catalog_url": catalog_url,
            "access_scope": access_scope,
            "catalog_access_scope": catalog_scope,
            "listed": not args.unlisted,
            "published_at": now_iso(),
        }
        write_json(work_root / "decks" / slug / "publish-manifest.json", manifest)
        write_receipt(work_root / "decks" / slug / "MIAODA_PUBLISH.md", manifest)
        print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except PublishError as exc:
        print(f"miaoda-publisher: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
