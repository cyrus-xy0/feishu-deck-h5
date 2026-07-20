#!/usr/bin/env python3
"""Quality-gate and ingest a confirmed feishu-deck-h5 HTML artifact.

The importer skill owns library submission after the user has finished and
confirmed an HTML deck and explicitly asked to 入库/提交/上传:

- run or reuse the ingest quality gate before any library write;
- hand the confirmed HTML to FuQiang/feishu-slide-library's PR-based ingest flow:
  package-ingest.sh -> bootstrap-library.py -> ingest-package.py ->
  verify candidate assets -> confirm-ingest.py;
- record PR/confirm and Cloudflare-hosted viewer sync context for controller
  handoff.

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


SKILL_ROOT = Path(__file__).resolve().parents[2]


def find_project_root(skill_root: Path) -> Path:
    """Return the checkout root when running from a source checkout."""
    resolved_skill = skill_root.resolve()
    for parent in (resolved_skill, *resolved_skill.parents):
        try:
            if (
                (parent / "skills" / "feishu-deck-h5").resolve() == resolved_skill
                and (parent / "runs").is_dir()
            ):
                return parent
        except OSError:
            continue
    return resolved_skill


REPO = find_project_root(SKILL_ROOT)
RUNS = REPO / "runs"
if REPO == SKILL_ROOT:
    DEFAULT_SLIDE_LIBRARY_ROOT = SKILL_ROOT.parents[1] / "tmp/feishu-slide-library"
    LEGACY_SLIDE_LIBRARY_ROOT = SKILL_ROOT / "tmp/feishu-slide-library"
else:
    DEFAULT_SLIDE_LIBRARY_ROOT = REPO / "tmp/feishu-slide-library"
    LEGACY_SLIDE_LIBRARY_ROOT = SKILL_ROOT / "tmp/feishu-slide-library"
SLIDE_LIBRARY_REPO = "https://github.com/FuQiang/feishu-slide-library.git"
CHECK_ONLY = SKILL_ROOT / "assets/check-only.py"
COPY_ASSETS = SKILL_ROOT / "assets/copy-assets.py"
PACKAGE_INGEST = SKILL_ROOT / "assets/package-ingest.sh"
UNREWRITTEN_FRAMEWORK_REFS = (
    'href="assets/feishu-deck.css"',
    "href='assets/feishu-deck.css'",
    'src="assets/feishu-deck.js"',
    "src='assets/feishu-deck.js'",
    'href="assets/deck-json/templates/extra-layouts.css"',
    "href='assets/deck-json/templates/extra-layouts.css'",
    'href="assets/edit-mode/',
    "href='assets/edit-mode/",
    'src="assets/edit-mode/',
    "src='assets/edit-mode/",
)
UNREWRITTEN_FRAMEWORK_PATTERN = re.compile(
    r'''(?:href|src)\s*=\s*["'](?:\./)?assets/(?:feishu-deck\.(?:css|js)|deck-json/templates/extra-layouts\.css|edit-mode/)''',
    re.IGNORECASE,
)

sys.path.insert(0, str(SKILL_ROOT / "server"))
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


def ensure_quality_gate(html_path: Path, output_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    """Run the resource-only gate before slide-library writes.

    Library ingest is intentionally not coupled to the full visual/business
    review gate.  The package and candidate paths below still enforce resource
    closure, while ``check-only --gate ingest`` remains available as an
    explicit strict review command.
    """
    report_path = output_dir / "IMPORT_QUALITY_REPORT.md"
    if args.allow_unaudited:
        return {
            "ok": True,
            "reused": False,
            "bypassed": True,
            "report": "",
            "reason": "--allow-unaudited set; local resource precheck bypassed for debug use; downstream package/resource checks still apply",
        }
    cmd = [
        sys.executable,
        str(CHECK_ONLY),
        str(html_path),
        "--resource-only",
        "--report",
        str(report_path),
    ]
    step = subprocess_record(cmd, cwd=REPO, log_path=output_dir / "importer-quality-gate.log")
    return {
        "ok": step["ok"],
        "reused": False,
        "bypassed": False,
        "report": repo_rel(report_path),
        "step": summarize_step(step),
        "reason": "" if step["ok"] else (step["stderr"] or step["stdout"] or "ingest quality gate failed"),
    }


def task_dirs(task_id: str) -> tuple[Path, Path]:
    task_dir = RUNS / task_id
    output_dir = task_dir / "output"
    if not output_dir.exists():
        raise SystemExit(f"importer: output directory not found for task {task_id}")
    return task_dir, output_dir


def resolve_html(args: argparse.Namespace, output_dir: Path | None) -> Path | None:
    if args.html:
        html_path = args.html.expanduser().resolve()
    elif output_dir and (output_dir / "index.html").exists():
        html_path = (output_dir / "index.html").resolve()
    else:
        return None
    if not html_path.exists() or not html_path.is_file():
        raise SystemExit(f"importer: confirmed HTML not found: {html_path}")
    if html_path.suffix.lower() not in {".html", ".htm"}:
        raise SystemExit(f"importer: expected .html/.htm artifact, got {html_path}")
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


# Default wall-clock bound for child steps. Network-bound steps (bootstrap's git
# clone, confirm-ingest's PR push) get a generous timeout so a stalled connection
# cannot hang the whole run with no bound (subskill-5).
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


def has_slide_library_scripts(root: Path) -> bool:
    skill_dir = root / "skills/feishu-slide-library"
    required = (
        skill_dir / "assets/bootstrap-library.py",
        skill_dir / "assets/ingest-package.py",
        skill_dir / "assets/confirm-ingest.py",
    )
    return all(path.exists() for path in required)


def resolve_slide_library_root(args: argparse.Namespace) -> Path:
    explicit = args.slide_library_root or optional_path(os.environ.get("FEISHU_SLIDE_LIBRARY_ROOT", ""))
    if explicit:
        return explicit.expanduser().resolve()
    for candidate in (DEFAULT_SLIDE_LIBRARY_ROOT, LEGACY_SLIDE_LIBRARY_ROOT):
        resolved = candidate.expanduser().resolve()
        if has_slide_library_scripts(resolved):
            return resolved
    return DEFAULT_SLIDE_LIBRARY_ROOT.expanduser().resolve()


def slide_library_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    root = resolve_slide_library_root(args)
    skill_dir = args.slide_library_skill_dir or root / "skills/feishu-slide-library"
    skill_dir = skill_dir.expanduser().resolve()
    return root, skill_dir


def child_env(library_root: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    python_bin = str(Path(sys.executable).resolve().parent)
    current_path = env.get("PATH", "")
    env["PATH"] = python_bin + (os.pathsep + current_path if current_path else "")
    env.setdefault("FEISHU_DECK_H5_SKILL_DIR", str(SKILL_ROOT))
    if library_root:
        env.setdefault("FEISHU_SLIDE_LIBRARY_ROOT", str(library_root))
    return env


def runtime_preflight(output_dir: Path, library_root: Path) -> dict[str, Any]:
    step = subprocess_record(
        [sys.executable, "-c", "import yaml"],
        cwd=REPO,
        log_path=output_dir / "importer-runtime-preflight.log",
        env=child_env(library_root),
    )
    return {"name": "runtime-preflight", **summarize_step(step)}


def has_unrewritten_framework_refs(source_html: Path) -> bool:
    try:
        html = source_html.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return any(ref in html for ref in UNREWRITTEN_FRAMEWORK_REFS) or bool(
        UNREWRITTEN_FRAMEWORK_PATTERN.search(html)
    )


def canonical_run_output(html_path: Path) -> Path | None:
    """Return the canonical runs/<id>/output directory for its index.html."""
    resolved = html_path.resolve()
    if resolved.name != "index.html" or resolved.parent.name != "output":
        return None
    try:
        resolved.parent.relative_to(RUNS.resolve())
    except ValueError:
        return None
    return resolved.parent


def prepare_ingest_artifact(
    *,
    html_path: Path,
    deck_id: str,
    report_output_dir: Path,
) -> dict[str, Any]:
    """Build a fresh ZIP for a canonical run; keep isolated HTML compatible.

    The run output keeps shared assets as one canonical symlink. package-ingest
    materializes only the reachable shared bytes into deck.zip, so the upload is
    portable without expanding the authoring directory again.
    """
    run_output = canonical_run_output(html_path)
    if run_output is None:
        return {
            "ok": True,
            "artifact_path": str(html_path),
            "asset_manifest_path": "",
            "steps": [],
            "reason": "isolated HTML; package preparation not applicable",
        }

    copy_step = subprocess_record(
        [sys.executable, str(COPY_ASSETS), str(run_output), "--shared=link"],
        cwd=REPO,
        log_path=report_output_dir / "importer-prepare-copy-assets.log",
    )
    steps = [{"name": "copy-assets-shared-link", **summarize_step(copy_step)}]
    if not copy_step["ok"]:
        return {
            "ok": False,
            "artifact_path": "",
            "asset_manifest_path": "",
            "steps": steps,
            "reason": copy_step["stderr"] or copy_step["stdout"] or "copy-assets failed",
        }

    package_step = subprocess_record(
        ["bash", str(PACKAGE_INGEST), str(run_output), "--deck-id", deck_id],
        cwd=REPO,
        log_path=report_output_dir / "importer-prepare-package-ingest.log",
    )
    steps.append({"name": "package-ingest", **summarize_step(package_step)})
    deck_zip = run_output / "deck.zip"
    if not package_step["ok"] or not deck_zip.is_file():
        reason = package_step["stderr"] or package_step["stdout"] or "package-ingest failed"
        if package_step["ok"] and not deck_zip.is_file():
            reason = f"package-ingest did not produce {deck_zip}"
        return {
            "ok": False,
            "artifact_path": "",
            "asset_manifest_path": "",
            "steps": steps,
            "reason": reason,
        }
    return {
        "ok": True,
        "artifact_path": str(deck_zip),
        "asset_manifest_path": str(run_output / "assets-manifest.yaml"),
        "steps": steps,
        "reason": "fresh self-contained deck.zip prepared from canonical run output",
    }


def read_asset_manifest(path: Path | None) -> dict[str, list[str]]:
    if path is None:
        return {"shared": [], "framework": [], "deck-local": []}
    if not path.is_file():
        raise ValueError(f"assets-manifest.yaml is missing: {path}")
    try:
        import yaml
    except ImportError as exc:
        raise ValueError(f"cannot read assets-manifest.yaml without PyYAML: {exc}") from exc
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"invalid assets-manifest.yaml: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid assets-manifest.yaml: expected a mapping")
    result: dict[str, list[str]] = {}
    for category in ("shared", "framework", "deck-local"):
        raw = payload.get(category) or []
        if not isinstance(raw, list):
            raise ValueError(f"invalid assets-manifest.yaml: {category} must be a list")
        normalized: list[str] = []
        for item in raw:
            if isinstance(item, str):
                value = item.strip()
            elif isinstance(item, dict):
                value = str(item.get("path") or "").strip()
            else:
                raise ValueError(
                    f"invalid assets-manifest.yaml: {category} entries require a path"
                )
            while value.startswith("./"):
                value = value[2:]
            if value:
                normalized.append(value)
        result[category] = normalized
    return result


def sha256_file(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _safe_manifest_asset(entry: str, prefix: str) -> Path | None:
    relative = Path(entry)
    if (
        not entry.startswith(prefix)
        or "\\" in entry
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        return None
    return relative


def resolve_candidate_root(ingest_result_path: Path, payload: dict[str, Any]) -> Path | None:
    raw = str(payload.get("candidate_root") or "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = ingest_result_path.resolve().parent / candidate
    return candidate.resolve()


ACTIVE_CANDIDATE_TEXT_SUFFIXES = {".html", ".htm", ".css", ".js", ".mjs", ".svg"}


def active_candidate_text_files(deck_dir: Path) -> list[tuple[Path, str]]:
    """Read runtime-bearing candidate files, excluding provenance snapshots."""
    files: list[tuple[Path, str]] = []
    for path in sorted(deck_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in ACTIVE_CANDIDATE_TEXT_SUFFIXES:
            continue
        relative = path.relative_to(deck_dir)
        if "source_package" in relative.parts:
            continue
        files.append((path, path.read_text(encoding="utf-8", errors="ignore")))
    return files


def candidate_pool_reference(path: Path, pool_file: Path) -> str:
    return os.path.relpath(pool_file, path.parent).replace(os.sep, "/")


def verify_candidate_assets(
    *,
    ingest_result_path: Path,
    deck_id: str,
    library_root: Path,
    asset_manifest_path: Path | None,
) -> dict[str, Any]:
    """Verify the transactional candidate without mutating the live library."""
    issues: list[str] = []
    try:
        ingest_payload = read_json(ingest_result_path)
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(f"cannot read ingest_result.json: {exc}")
        ingest_payload = {}
    candidate_root = resolve_candidate_root(ingest_result_path, ingest_payload)
    if candidate_root is None or not candidate_root.is_dir():
        issues.append(f"candidate_root is missing or unreadable: {candidate_root or ''}")
        return {
            "name": "verify-candidate-assets",
            "ok": False,
            "returncode": 1,
            "stdout": "",
            "stderr": "; ".join(issues),
        }

    deck_dir = candidate_root / "decks" / deck_id
    source_html = deck_dir / "source.html"
    if not source_html.is_file():
        issues.append(f"candidate source.html is missing: {source_html}")
    active_texts = active_candidate_text_files(deck_dir) if deck_dir.is_dir() else []

    deck_shared = deck_dir / "assets" / "shared"
    if deck_shared.exists() or deck_shared.is_symlink():
        issues.append(f"candidate contains forbidden deck-local shared pool: {deck_shared}")

    try:
        manifest = read_asset_manifest(asset_manifest_path)
    except ValueError as exc:
        manifest = {"shared": [], "framework": [], "deck-local": []}
        issues.append(str(exc))

    manifest_root = asset_manifest_path.parent if asset_manifest_path else None
    for entry in manifest["shared"]:
        relative = _safe_manifest_asset(entry, "assets/shared/")
        if relative is None:
            issues.append(f"unsafe or misclassified shared manifest entry: {entry}")
            continue
        pool_target = candidate_root / relative
        matched_reference = False
        for active_path, active_text in active_texts:
            expected_ref = candidate_pool_reference(active_path, pool_target)
            if relative.as_posix() not in active_text and expected_ref not in active_text:
                continue
            matched_reference = True
            if expected_ref not in active_text:
                issues.append(
                    f"shared reference in {active_path.relative_to(deck_dir)} was not rewritten to {expected_ref}"
                )
            elif relative.as_posix() in active_text.replace(expected_ref, ""):
                issues.append(
                    f"legacy deck-local shared reference remains in {active_path.relative_to(deck_dir)}: {relative.as_posix()}"
                )
        if not matched_reference:
            issues.append(f"manifest shared asset has no active candidate reference: {relative.as_posix()}")
        candidate_pool_file = candidate_root / relative
        live_pool_file = library_root / relative
        pool_file = candidate_pool_file if candidate_pool_file.is_file() else live_pool_file
        if not pool_file.is_file():
            issues.append(f"shared pool file is missing from candidate and library: {relative.as_posix()}")
            continue
        package_file = manifest_root / relative if manifest_root else None
        if package_file and package_file.is_file():
            try:
                hash_matches = sha256_file(package_file) == sha256_file(pool_file)
            except OSError as exc:
                issues.append(f"cannot hash shared asset {relative.as_posix()}: {exc}")
            else:
                if not hash_matches:
                    issues.append(f"shared pool hash differs from packaged asset: {relative.as_posix()}")

    for entry in manifest["framework"]:
        relative = _safe_manifest_asset(entry, "assets/")
        if relative is None:
            issues.append(f"unsafe framework manifest entry: {entry}")
            continue
        old_ref = relative.as_posix()
        framework_target = candidate_root / "assets" / "framework" / relative.name
        for active_path, active_text in active_texts:
            expected_ref = candidate_pool_reference(active_path, framework_target)
            if old_ref not in active_text and expected_ref not in active_text:
                continue
            if expected_ref not in active_text:
                issues.append(
                    f"framework reference in {active_path.relative_to(deck_dir)} was not rewritten to {expected_ref}"
                )
            elif old_ref in active_text.replace(expected_ref, ""):
                issues.append(
                    f"legacy framework reference remains in {active_path.relative_to(deck_dir)}: {old_ref}"
                )

    for active_path, _active_text in active_texts:
        if has_unrewritten_framework_refs(active_path):
            issues.append(
                f"active candidate file still contains legacy local framework references: {active_path.relative_to(deck_dir)}"
            )

    return {
        "name": "verify-candidate-assets",
        "ok": not issues,
        "returncode": 0 if not issues else 1,
        "stdout": "candidate source and shared-pool handoff verified" if not issues else "",
        "stderr": "; ".join(issues),
    }


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
    preflight = runtime_preflight(output_dir, library_root)
    result["steps"].append(preflight)
    if not preflight["ok"]:
        result["reason"] = preflight["stderr"] or preflight["stdout"] or "runtime preflight failed"
        return result

    prepared = prepare_ingest_artifact(
        html_path=html_path,
        deck_id=deck_id,
        report_output_dir=output_dir,
    )
    result["steps"].extend(prepared["steps"])
    if not prepared["ok"]:
        result["reason"] = prepared["reason"] or "failed to prepare ingest artifact"
        return result
    artifact_path = Path(prepared["artifact_path"])
    asset_manifest_path = optional_path(prepared.get("asset_manifest_path", ""))
    result["artifact_path"] = str(artifact_path)

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
    env = child_env(library_root)
    bootstrap_step = subprocess_record(bootstrap_cmd, cwd=REPO, log_path=output_dir / "importer-slide-library-bootstrap.log", env=env, timeout=NETWORK_SUBPROCESS_TIMEOUT)
    result["steps"].append({"name": "bootstrap-library", **summarize_step(bootstrap_step)})
    if not bootstrap_step["ok"]:
        result["reason"] = bootstrap_step["stderr"] or bootstrap_step["stdout"] or "bootstrap-library failed"
        return result

    ingest_cmd = [
        sys.executable,
        str(ingest_package),
        str(artifact_path),
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
        "--resource-checks-only",
        "--no-deck-h5-gate",
    ]
    if args.submitted_by_id:
        ingest_cmd.extend(["--submitted-by-id", args.submitted_by_id])
    ingest_step = subprocess_record(ingest_cmd, cwd=REPO, log_path=output_dir / "importer-slide-library-ingest.log", env=env)
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

    ingest_result_path = Path(result["ingest_result_path"])
    if not ingest_result_path.is_absolute():
        ingest_result_path = (REPO / ingest_result_path).resolve()
    if not ingest_result_path.exists():
        result["reason"] = f"ingest_result.json not found: {ingest_result_path}"
        return result
    candidate_step = verify_candidate_assets(
        ingest_result_path=ingest_result_path,
        deck_id=deck_id,
        library_root=library_root,
        asset_manifest_path=asset_manifest_path,
    )
    result["steps"].append(candidate_step)
    if not candidate_step["ok"]:
        result["reason"] = candidate_step["stderr"] or candidate_step["stdout"] or "candidate asset verification failed"
        return result
    if args.no_confirm_ingest:
        result["ok"] = True
        result["reason"] = "ready_for_confirm; confirm-ingest skipped by --no-confirm-ingest"
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
    confirm_step = subprocess_record(confirm_cmd, cwd=REPO, log_path=output_dir / "importer-slide-library-confirm.log", env=env, timeout=NETWORK_SUBPROCESS_TIMEOUT)
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
    viewer_sync = manifest.get("viewer_sync") or {}
    library_ingest = manifest.get("library_ingest") or {}
    quality_gate = manifest.get("quality_gate") or {}
    lines = [
        "# Importer Report",
        "",
        f"- task_id: `{manifest.get('task_id', '')}`",
        f"- source: `{manifest.get('source', '')}`",
        f"- dry_run: {manifest.get('dry_run', False)}",
        f"- quality_gate_ok: {quality_gate.get('ok')}",
        f"- quality_report: `{quality_gate.get('report') or ''}`",
        f"- viewer_sync_ok: {viewer_sync.get('ok')}",
        f"- viewer_sync_target: {viewer_sync.get('target') or ''}",
        f"- viewer_sync_url: {viewer_sync.get('app_url') or ''}",
        f"- library_ingest_ok: {library_ingest.get('ok')}",
        f"- library_deck_id: {library_ingest.get('deck_id') or ''}",
        "",
    ]
    if library_ingest.get("ingest_report"):
        lines.append(f"- ingest_report: `{library_ingest.get('ingest_report')}`")
    if library_ingest.get("review_candidates"):
        lines.append(f"- review_candidates: `{library_ingest.get('review_candidates')}`")
    if viewer_sync.get("reason"):
        lines.extend(["", "## Viewer sync note", str(viewer_sync.get("reason"))])
    if library_ingest.get("reason"):
        lines.extend(["", "## Library ingest note", str(library_ingest.get("reason"))])
    if manifest.get("skipped"):
        lines.extend(["", "## Skipped"])
        for item in manifest["skipped"]:
            lines.append(f"- `{item.get('slide_key', item.get('type', 'item'))}` · {item.get('reason')}")
    lines.append("")
    return "\n".join(lines)


def library_viewer_sync_context(library_ingest: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    pr = library_ingest.get("pr") if isinstance(library_ingest.get("pr"), dict) else {}
    pr_dry_run = bool(pr.get("dry_run"))
    ok = bool(library_ingest.get("ok")) and not pr_dry_run
    viewer_url = (
        pr.get("viewer_url")
        or pr.get("cloudflare_url")
        or pr.get("published_url")
        or pr.get("url")
        or ""
    )
    reason = library_ingest.get("reason") or ""
    if pr_dry_run:
        reason = "confirm-ingest ran with --dry-run; viewer sync was not published"
    elif not library_ingest.get("ok"):
        reason = reason or "library ingest failed before viewer sync"
    return {
        "target": "cloudflare-slide-library",
        "enabled": True,
        "ok": ok,
        "dry_run": bool(library_ingest.get("dry_run")) or pr_dry_run,
        "app_url": viewer_url,
        "repo": SLIDE_LIBRARY_REPO,
        "deck_id": library_ingest.get("deck_id") or "",
        "pr": pr,
        "auto_merge_requested": bool(args.auto_merge),
        "wait_viewer_requested": bool(args.wait_viewer),
        "reason": reason,
    }


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
    ap.add_argument("--html", type=Path, help="confirmed .html/.htm artifact to ingest into feishu-slide-library")
    ap.add_argument("--deck-id", default="", help="feishu-slide-library deck_id; defaults to a slug from title/task")
    ap.add_argument("--job-id", default="", help="feishu-slide-library job id; defaults to task/deck id")
    ap.add_argument("--title")
    ap.add_argument("--allow-unaudited", action="store_true", help="bypass the local resource precheck for debug use; downstream package/resource checks still apply")
    ap.add_argument("--dry-run", action="store_true", help="simulate feishu-slide-library ingest without external writes")

    ap.add_argument("--slide-library-root", type=Path)
    ap.add_argument("--slide-library-skill-dir", type=Path)
    ap.add_argument("--slide-library-branch", default="main")
    ap.add_argument("--slide-library-offline", action="store_true")
    ap.add_argument("--staging-root", type=Path)
    ap.add_argument("--submitted-by", default="")
    ap.add_argument("--submitted-by-id", default="")
    ap.add_argument("--no-confirm-ingest", action="store_true", help="stop after ingest-package.py is ready_for_confirm")
    ap.add_argument("--confirm-dry-run", action="store_true", help="call confirm-ingest.py --dry-run")
    ap.add_argument("--auto-merge", action="store_true")
    ap.add_argument("--wait-viewer", action="store_true")

    ap.add_argument("--ppt-library", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--ppt-page", action="append", type=int, default=[], help=argparse.SUPPRESS)
    ap.add_argument("--slide-key", action="append", default=[], help=argparse.SUPPRESS)
    ap.add_argument("--industry", action="append", default=[], help=argparse.SUPPRESS)
    ap.add_argument("--product", action="append", default=[], help=argparse.SUPPRESS)
    ap.add_argument("--customer-stage", action="append", default=[], help=argparse.SUPPRESS)
    ap.add_argument("--deck-type", action="append", default=[], help=argparse.SUPPRESS)
    ap.add_argument("--value-prop", action="append", default=[], help=argparse.SUPPRESS)
    ap.add_argument("--tag", action="append", default=[], help=argparse.SUPPRESS)
    ap.add_argument("--source-level", default="internal-draft", help=argparse.SUPPRESS)
    ap.add_argument("--owner", default="gtm", help=argparse.SUPPRESS)
    ap.add_argument("--reviewer", default="", help=argparse.SUPPRESS)
    ap.add_argument("--contributor", default="", help=argparse.SUPPRESS)
    ap.add_argument("--contributed-at", default="", help=argparse.SUPPRESS)
    ap.add_argument("--summary", default="", help=argparse.SUPPRESS)
    ap.add_argument("--thumbnail", default="", help=argparse.SUPPRESS)
    ap.add_argument("--permission-status", default="needs_review", help=argparse.SUPPRESS)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.ppt_library:
        raise SystemExit("importer: --ppt-library is no longer supported; importer only ingests finished HTML")
    if not args.task_id and not args.html:
        raise SystemExit("importer: --html or --task-id is required")

    task_id = args.task_id or f"importer/{slugify(Path(args.html).stem if args.html else 'html')}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    _task_dir: Path | None = None
    output_dir: Path
    if args.task_id:
        _task_dir, output_dir = task_dirs(args.task_id)
    else:
        output_dir = RUNS / task_id / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

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
        "viewer_sync": {},
        "library_ingest": {},
        "quality_gate": {},
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
        manifest["quality_gate"] = ensure_quality_gate(html_path, output_dir, args)
        if not (manifest["quality_gate"] or {}).get("ok"):
            manifest["library_ingest"] = {"ok": False, "reason": "quality gate failed; slide-library ingest not attempted"}
            manifest["viewer_sync"] = {"target": "cloudflare-slide-library", "enabled": True, "ok": False, "reason": "quality gate failed"}
            manifest["skipped"].append({"type": "library_ingest", "reason": "quality gate failed"})
            manifest["skipped"].append({"type": "viewer_sync", "reason": "quality gate failed"})
        else:
            manifest["library_ingest"] = ingest_with_slide_library(
                html_path=html_path,
                output_dir=output_dir,
                title=title,
                task_id=task_id,
                args=args,
            )
            manifest["viewer_sync"] = library_viewer_sync_context(manifest["library_ingest"], args)
    else:
        manifest["library_ingest"] = {"ok": True, "dry_run": True, "reason": "no HTML artifact; compatibility dry-run only"}
        manifest["skipped"].append({"type": "library_ingest", "reason": "confirmed HTML not provided"})

    manifest_path = output_dir / "ingestion-manifest.json"
    report_path = output_dir / "INGESTION_REPORT.md"
    write_json(manifest_path, manifest)
    report_path.write_text(report_md(manifest), encoding="utf-8")
    print(json.dumps({"manifest": str(manifest_path), "report": str(report_path), **manifest}, ensure_ascii=False, indent=2, sort_keys=True))

    ingest_ok = bool((manifest.get("library_ingest") or {}).get("ok"))
    return 0 if ingest_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
