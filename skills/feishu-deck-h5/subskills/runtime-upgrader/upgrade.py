#!/usr/bin/env python3
"""Build a verified runtime-upgrade candidate without mutating or publishing."""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Iterator, Mapping


SCRIPT_PATH = Path(__file__).resolve()
SKILL_ROOT = SCRIPT_PATH.parents[2]
MIGRATION_REGISTRY = Path("runtime/runtime-migrations.json")
RUNTIME_MANIFEST = Path("runtime/runtime-files.json")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SAFE_MIGRATION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
REQUIRED_TARGET_PATHS = (
    "subskills/runtime-upgrader/upgrade.py",
    "runtime/runtime-migrations.json",
    "runtime/runtime-files.json",
    "assets/runtime-lock.py",
    "assets/verify-portable.py",
    "assets/copy-assets.py",
    "deck-json/deck-cli.py",
    "deck-json/deck-schema.json",
    "deck-json/render-deck.py",
    "deck-json/sync-index-to-deck.py",
)
STALE_OUTPUT_FILES = (
    "index.html",
    "assets-manifest.yaml",
    "runtime-lock.json",
    "deck.zip",
    "ingestion-manifest.json",
    ".asset-closure.json",
    ".slide-hashes.json",
    "slide-index.json",
    "validate-findings.json",
    "last-render.log",
)
STALE_OUTPUT_DIRS = ("feishu-slide-library-ingest",)
MISSING = object()


class UpgradeError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.state = "BLOCKED"
        self.candidate_run: Path | None = None


def run_command(
    args: list[str],
    *,
    cwd: Path | None = None,
    allowed: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in allowed:
        detail = (completed.stderr or completed.stdout).strip()
        raise UpgradeError(
            "RUP-CMD-001",
            f"command failed ({completed.returncode}): {' '.join(args)}"
            + (f": {detail}" if detail else ""),
        )
    return completed


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(root: Path) -> str:
    """Hash names, bytes, and symlink targets without following symlinks."""
    digest = hashlib.sha256()
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs.sort()
        files.sort()
        base = Path(current)
        entries = [(name, True) for name in dirs] + [(name, False) for name in files]
        for name, is_dir in entries:
            path = base / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                kind = b"L"
                payload = os.readlink(path).encode("utf-8", errors="surrogateescape")
            elif is_dir:
                kind = b"D"
                payload = b""
            else:
                kind = b"F"
                payload = path.read_bytes()
            digest.update(kind + b"\0" + relative.encode("utf-8") + b"\0")
            digest.update(hashlib.sha256(payload).digest())
    return digest.hexdigest()


def repo_root(start: Path) -> Path:
    completed = run_command(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"]
    )
    return Path(completed.stdout.strip()).resolve()


def resolve_target_commit(repository: Path, explicit: str) -> str:
    requested = explicit.strip().lower()
    if requested and not COMMIT_RE.fullmatch(requested):
        raise UpgradeError(
            "RUP-TGT-001",
            "--target-commit must be a full 40-character lowercase Git commit",
        )
    ref = requested or "HEAD"
    completed = run_command(
        ["git", "-C", str(repository), "rev-parse", f"{ref}^{{commit}}"]
    )
    commit = completed.stdout.strip().lower()
    if not COMMIT_RE.fullmatch(commit):
        raise UpgradeError("RUP-TGT-001", f"cannot resolve trusted commit: {ref}")
    return commit


@contextlib.contextmanager
def target_worktree(repository: Path, commit: str) -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="fs-runtime-upgrade-") as temp:
        checkout = Path(temp) / "checkout"
        run_command(
            [
                "git",
                "-C",
                str(repository),
                "worktree",
                "add",
                "--detach",
                "--quiet",
                str(checkout),
                commit,
            ]
        )
        try:
            yield checkout
        finally:
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "worktree",
                    "remove",
                    "--force",
                    str(checkout),
                ],
                check=False,
                capture_output=True,
                text=True,
            )


def validate_target_skill(skill_root: Path) -> None:
    missing = [path for path in REQUIRED_TARGET_PATHS if not (skill_root / path).is_file()]
    if missing:
        raise UpgradeError(
            "RUP-TGT-002",
            "target commit lacks runtime-upgrade toolchain: " + ", ".join(missing),
        )


def _safe_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = Path(value)
    return (
        not path.is_absolute()
        and value == path.as_posix()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def load_runtime_contract(skill_root: Path) -> tuple[list[str], list[str]]:
    try:
        payload = json.loads((skill_root / RUNTIME_MANIFEST).read_text(encoding="utf-8"))
        files = payload["files"]
        required = payload["required_package_paths"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise UpgradeError("RUP-TGT-003", f"invalid runtime manifest: {exc}") from exc
    result: list[str] = []
    for item in files:
        package_path = item.get("package_path") if isinstance(item, Mapping) else None
        if not _safe_relative_path(package_path):
            raise UpgradeError("RUP-TGT-003", "unsafe runtime package path")
        result.append(str(package_path))
    if not result or len(result) != len(set(result)):
        raise UpgradeError("RUP-TGT-003", "empty or duplicate runtime package paths")
    if (
        not isinstance(required, list)
        or not required
        or any(not _safe_relative_path(path) for path in required)
        or not set(required) <= set(result)
    ):
        raise UpgradeError("RUP-TGT-003", "invalid required runtime package paths")
    return sorted(result), sorted(set(required))


def load_runtime_package_paths(skill_root: Path) -> list[str]:
    return load_runtime_contract(skill_root)[0]


def load_migrations(skill_root: Path) -> list[dict[str, object]]:
    path = skill_root / MIGRATION_REGISTRY
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpgradeError("RUP-TGT-004", f"invalid migration registry: {exc}") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "migrations"}
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("migrations"), list)
    ):
        raise UpgradeError("RUP-TGT-004", "unsupported migration registry schema")
    migrations: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in payload["migrations"]:
        if not isinstance(raw, dict):
            raise UpgradeError("RUP-TGT-004", "migration entry must be an object")
        migration_id = raw.get("id")
        when = raw.get("when")
        if (
            set(raw) != {"id", "required", "operation", "path", "value", "when"}
            or not isinstance(migration_id, str)
            or not SAFE_MIGRATION_ID_RE.fullmatch(migration_id)
            or migration_id in seen
            or raw.get("required") is not True
            or raw.get("operation") != "deck-json-set"
            or not isinstance(raw.get("path"), str)
            or not str(raw["path"]).startswith("deck.")
            or not isinstance(when, dict)
            or set(when) != {"min_active_slides"}
            or not isinstance(when.get("min_active_slides"), int)
            or isinstance(when.get("min_active_slides"), bool)
            or int(when["min_active_slides"]) < 1
        ):
            raise UpgradeError("RUP-TGT-004", f"invalid required migration: {raw!r}")
        seen.add(migration_id)
        migrations.append(copy.deepcopy(raw))
    return migrations


def load_deck(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpgradeError("RUP-SRC-001", f"invalid DeckJSON: {path}: {exc}") from exc
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("deck"), dict)
        or not isinstance(payload.get("slides"), list)
    ):
        raise UpgradeError("RUP-SRC-001", f"invalid DeckJSON shape: {path}")
    return payload


def active_slide_count(deck: Mapping[str, object]) -> int:
    slides = deck.get("slides")
    assert isinstance(slides, list)
    return sum(
        1
        for slide in slides
        if isinstance(slide, Mapping) and not slide.get("_disabled")
    )


def get_path(payload: Mapping[str, object], dotted: str) -> object:
    current: object = payload
    for part in dotted.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return MISSING
        current = current[part]
    return current


def diff_paths(before: object, after: object, prefix: str = "") -> set[str]:
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        result: set[str] = set()
        for key in set(before) | set(after):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in before or key not in after:
                result.add(path)
            else:
                result |= diff_paths(before[key], after[key], path)
        return result
    if before != after:
        return {prefix}
    return set()


def plan_migrations(
    deck: Mapping[str, object],
    migrations: list[dict[str, object]],
) -> list[dict[str, object]]:
    count = active_slide_count(deck)
    planned: list[dict[str, object]] = []
    for migration in migrations:
        minimum = int(cast_mapping(migration["when"])["min_active_slides"])
        current = get_path(deck, str(migration["path"]))
        if count < minimum:
            status = "not_applicable"
        elif current == migration["value"]:
            status = "already_satisfied"
        else:
            status = "pending"
        planned.append(
            {
                "id": migration["id"],
                "path": migration["path"],
                "required": True,
                "status": status,
            }
        )
    return planned


def cast_mapping(value: object) -> Mapping[str, object]:
    assert isinstance(value, Mapping)
    return value


def apply_migrations(
    skill_root: Path,
    deck_path: Path,
    migrations: list[dict[str, object]],
) -> list[dict[str, object]]:
    deck = load_deck(deck_path)
    planned = plan_migrations(deck, migrations)
    by_id = {str(item["id"]): item for item in migrations}
    for item in planned:
        if item["status"] != "pending":
            continue
        migration = by_id[str(item["id"])]
        value = json.dumps(migration["value"], ensure_ascii=False)
        run_command(
            [
                sys.executable,
                str(skill_root / "deck-json/deck-cli.py"),
                "--no-backup",
                str(deck_path),
                "set",
                str(migration["path"]),
                value,
                "--json",
            ]
        )
        if get_path(load_deck(deck_path), str(migration["path"])) != migration["value"]:
            raise UpgradeError(
                "RUP-MIG-001",
                f"migration did not set {migration['path']}: {migration['id']}",
            )
        item["status"] = "applied"
    return planned


def validate_source(deck_json: Path, repository: Path) -> tuple[Path, Path]:
    deck_json = deck_json.expanduser().resolve()
    if not deck_json.is_file() or deck_json.name != "deck.json":
        raise UpgradeError("RUP-SRC-001", f"missing canonical deck.json: {deck_json}")
    source_output = deck_json.parent
    source_run = source_output.parent
    expected_runs = (repository / "runs").resolve()
    if source_output.name != "output" or source_run.parent.resolve() != expected_runs:
        raise UpgradeError(
            "RUP-SRC-001",
            "source must be canonical <repo>/runs/<run>/output/deck.json",
        )
    index_html = source_output / "index.html"
    if not index_html.is_file():
        raise UpgradeError(
            "RUP-SRC-002",
            f"source-backed upgrade requires sibling index.html: {index_html}",
        )
    load_deck(deck_json)
    return source_run, index_html


def check_source_drift(skill_root: Path, index_html: Path, deck_json: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(skill_root / "deck-json/sync-index-to-deck.py"),
            str(index_html),
            str(deck_json),
            "--check-drift",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode == 10:
        raise UpgradeError(
            "RUP-SRC-003",
            "source index.html contains edits not synchronized to deck.json",
        )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise UpgradeError("RUP-SRC-001", f"source drift check failed: {detail}")


def check_source_safely(
    skill_root: Path,
    index_html: Path,
    deck_json: Path,
) -> None:
    """Run target tools only against read-only copies of the source pair."""
    with tempfile.TemporaryDirectory(prefix="fs-runtime-source-check-") as temp:
        root = Path(temp)
        deck_copy = root / "deck.json"
        index_copy = root / "index.html"
        shutil.copy2(deck_json, deck_copy)
        shutil.copy2(index_html, index_copy)
        deck_copy.chmod(0o444)
        index_copy.chmod(0o444)
        check_source_drift(skill_root, index_copy, deck_copy)
        run_command(
            [
                sys.executable,
                str(skill_root / "deck-json/deck-cli.py"),
                str(deck_copy),
                "lint",
            ]
        )


def default_candidate_run(repository: Path, source_run: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", source_run.name).strip("-") or "deck"
    return repository / "runs" / f"{timestamp}-{slug}-runtime-upgrade"


def validate_candidate_path(
    candidate_run: Path,
    repository: Path,
    source_run: Path,
) -> Path:
    candidate_run = candidate_run.expanduser().resolve()
    if candidate_run.parent != (repository / "runs").resolve():
        raise UpgradeError(
            "RUP-OUT-001",
            "--output-run must be a new direct child of <repo>/runs",
        )
    if candidate_run == source_run or source_run in candidate_run.parents:
        raise UpgradeError("RUP-OUT-001", "candidate must not overlap the source run")
    if candidate_run.exists():
        raise UpgradeError("RUP-OUT-001", f"candidate already exists: {candidate_run}")
    return candidate_run


def ensure_no_symlink_parents(root: Path, path: Path) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise UpgradeError("RUP-ASSET-001", f"path escapes candidate: {path}") from exc
    current = root
    for part in relative.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise UpgradeError(
                "RUP-ASSET-001",
                f"candidate path has symlink parent: {current}",
            )


def remove_path(root: Path, path: Path) -> None:
    ensure_no_symlink_parents(root, path)
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def stage_candidate(
    source_output: Path,
    candidate_run: Path,
    runtime_package_paths: list[str],
) -> Path:
    candidate_run.parent.mkdir(parents=True, exist_ok=True)
    candidate_run.mkdir()
    input_dir = candidate_run / "input"
    input_dir.mkdir()
    shutil.copy2(source_output / "deck.json", input_dir / "source-deck.json")
    shutil.copy2(source_output / "index.html", input_dir / "source-index.html")
    candidate_output = candidate_run / "output"
    shutil.copytree(source_output, candidate_output, symlinks=True)
    for relative in STALE_OUTPUT_FILES:
        remove_path(candidate_output, candidate_output / relative)
    for relative in STALE_OUTPUT_DIRS:
        remove_path(candidate_output, candidate_output / relative)
    for relative in runtime_package_paths:
        remove_path(candidate_output, candidate_output / relative)
    shared = candidate_output / "assets/shared"
    ensure_no_symlink_parents(candidate_output, shared)
    if shared.is_symlink():
        shared.unlink()
    return candidate_output


def prepare_candidate_record(source_output: Path, candidate_run: Path) -> None:
    candidate_run.mkdir()
    input_dir = candidate_run / "input"
    input_dir.mkdir()
    shutil.copy2(source_output / "deck.json", input_dir / "source-deck.json")
    shutil.copy2(source_output / "index.html", input_dir / "source-index.html")


def validate_deck_conservation(
    source: Mapping[str, object],
    candidate: Mapping[str, object],
    migrations: list[dict[str, object]],
    results: list[dict[str, object]],
) -> list[str]:
    changed = sorted(diff_paths(source, candidate))
    by_id = {str(item["id"]): item for item in migrations}
    allowed = {
        str(by_id[str(result["id"])]["path"])
        for result in results
        if result["status"] == "applied"
    }
    unexpected = sorted(set(changed) - allowed)
    if unexpected:
        raise UpgradeError(
            "RUP-MIG-002",
            "DeckJSON changed outside registered migrations: " + ", ".join(unexpected),
        )
    for path in allowed:
        migration = next(item for item in migrations if item["path"] == path)
        if get_path(candidate, path) != migration["value"]:
            raise UpgradeError("RUP-MIG-002", f"migration value mismatch: {path}")
    return changed


def validate_lazy_structure(output: Path, deck: Mapping[str, object]) -> None:
    if get_path(deck, "deck.lazy_frames") is not True:
        return
    count = active_slide_count(deck)
    html = (output / "index.html").read_text(encoding="utf-8")
    if 'data-lazy-frames=""' not in html:
        raise UpgradeError("RUP-BLD-003", "lazy runtime marker is missing")
    expected = max(0, count - 1)
    if html.count("<template data-fs-lazy-slide>") != expected:
        raise UpgradeError("RUP-BLD-003", "lazy slide template count is invalid")
    templates = re.findall(
        r"<template data-fs-lazy-slide>(.*?)</template>",
        html,
        flags=re.S,
    )
    if any(
        len(re.findall(r'<div class="slide(?:\s[^"]*)?"[^>]*>', body)) != 1
        for body in templates
    ):
        raise UpgradeError("RUP-BLD-003", "lazy template payload is invalid")
    frame_tags = re.findall(
        r'<div class="slide-frame"[^>]*data-fs-lazy-frame=""[^>]*>',
        html,
    )
    if len(frame_tags) != expected or any(
        attribute not in tag
        for tag in frame_tags
        for attribute in ("data-slide-key=", "data-layout=", "data-screen-label=")
    ):
        raise UpgradeError("RUP-BLD-003", "lazy frame metadata count is invalid")
    first_template = html.find("<template data-fs-lazy-slide>")
    eager_region = html if first_template < 0 else html[:first_template]
    if count and (
        'class="slide-frame"' not in eager_region
        or re.search(r'<div class="slide(?:\s[^"]*)?"[^>]*>', eager_region) is None
    ):
        raise UpgradeError("RUP-BLD-003", "first slide is not eager")


def read_source_runtime(source_output: Path) -> dict[str, object]:
    lock = source_output / "runtime-lock.json"
    if not lock.is_file():
        return {"status": "unlocked"}
    try:
        payload = json.loads(lock.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"status": "unlocked", "reason": "invalid_runtime_lock"}
    return {
        "status": "reported_unverified",
        "runtime_id": payload.get("runtime_id"),
        "deck_h5_commit": payload.get("deck_h5_commit"),
    }


def validate_runtime_lock_payload(
    payload: object,
    commit: str,
    required_paths: list[str],
) -> None:
    if not isinstance(payload, Mapping):
        raise UpgradeError("RUP-BLD-002", "runtime lock is not an object")
    runtime_id = payload.get("runtime_id")
    snapshot_id = payload.get("snapshot_id")
    files = payload.get("files")
    if (
        payload.get("schema_version") != 1
        or payload.get("deck_h5_commit") != commit
        or not isinstance(runtime_id, str)
        or not re.fullmatch(r"sha256-[0-9a-f]{64}", runtime_id)
        or not isinstance(snapshot_id, str)
        or not re.fullmatch(r"sha256-[0-9a-f]{64}", snapshot_id)
        or not isinstance(files, list)
        or not files
    ):
        raise UpgradeError("RUP-BLD-002", "runtime lock receipt is invalid")
    active = {
        item.get("package_path")
        for item in files
        if isinstance(item, Mapping)
    }
    if not set(required_paths) <= active:
        raise UpgradeError(
            "RUP-BLD-002",
            "runtime lock omits required package paths",
        )


def write_report(candidate_run: Path, payload: Mapping[str, object]) -> None:
    json_path = candidate_run / "RUNTIME-UPGRADE.json"
    json_temp = candidate_run / ".RUNTIME-UPGRADE.json.tmp"
    json_temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    migrations = payload.get("migrations", [])
    lines = [
        "# Runtime Upgrade",
        "",
        f"- Status: `{payload.get('status')}`",
        f"- Target commit: `{cast_mapping(payload.get('target', {})).get('commit', '')}`",
        f"- Candidate: `{payload.get('candidate_run', '')}`",
        f"- Ready to publish: `{str(payload.get('ready_to_publish', False)).lower()}`",
        f"- Performance: `{cast_mapping(payload.get('performance', {})).get('status', 'unproven')}`",
        "",
        "## Migrations",
        "",
    ]
    if isinstance(migrations, list):
        lines.extend(
            f"- `{item.get('id')}`: `{item.get('status')}`"
            for item in migrations
            if isinstance(item, Mapping)
        )
    error = payload.get("error")
    if isinstance(error, Mapping):
        lines.extend(
            ["", "## Error", "", f"- `{error.get('code')}`: {error.get('message')}"]
        )
    markdown_path = candidate_run / "RUNTIME-UPGRADE.md"
    markdown_temp = candidate_run / ".RUNTIME-UPGRADE.md.tmp"
    markdown_temp.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    os.replace(json_temp, json_path)
    os.replace(markdown_temp, markdown_path)


def upgrade(
    deck_json: Path,
    *,
    target_commit: str = "",
    output_run: Path | None = None,
    dry_run: bool = False,
    repository: Path | None = None,
) -> dict[str, object]:
    repository = (repository or repo_root(SKILL_ROOT)).resolve()
    source_run, source_index = validate_source(deck_json, repository)
    deck_json = deck_json.expanduser().resolve()
    source_output = deck_json.parent
    source_hash_before = tree_digest(source_run)
    commit = resolve_target_commit(repository, target_commit)
    candidate_run: Path | None = None
    build_run: Path | None = None
    receipt: dict[str, object] = {}
    try:
        with target_worktree(repository, commit) as checkout:
            target_skill = checkout / "skills/feishu-deck-h5"
            validate_target_skill(target_skill)
            migrations = load_migrations(target_skill)
            runtime_paths, required_runtime_paths = load_runtime_contract(target_skill)
            check_source_safely(target_skill, source_index, deck_json)
            source_deck = load_deck(deck_json)
            planned = plan_migrations(source_deck, migrations)
            target = {
                "commit": commit,
                "migration_registry_sha256": sha256_file(
                    target_skill / MIGRATION_REGISTRY
                ),
            }
            if dry_run:
                receipt = {
                    "schema_version": 1,
                    "status": "DRY_RUN",
                    "source": {
                        "deck_json": str(deck_json),
                        "run": str(source_run),
                        "tree_sha256": source_hash_before,
                        "runtime": read_source_runtime(source_output),
                    },
                    "target": target,
                    "migrations": planned,
                    "ready_to_publish": False,
                    "performance": {"status": "unproven"},
                }
                return receipt

            candidate_run = validate_candidate_path(
                output_run or default_candidate_run(repository, source_run),
                repository,
                source_run,
            )
            prepare_candidate_record(source_output, candidate_run)
            build_run = checkout / "runs" / candidate_run.name
            build_output = stage_candidate(
                source_output,
                build_run,
                runtime_paths,
            )
            candidate_deck = build_output / "deck.json"
            migration_results = apply_migrations(
                target_skill,
                candidate_deck,
                migrations,
            )
            changed_paths = validate_deck_conservation(
                source_deck,
                load_deck(candidate_deck),
                migrations,
                migration_results,
            )
            run_command(
                [
                    sys.executable,
                    str(target_skill / "deck-json/render-deck.py"),
                    str(candidate_deck),
                    str(build_output),
                    "--final",
                    "--visual",
                    "--shared",
                    "copy",
                ]
            )
            run_command(
                [
                    sys.executable,
                    str(target_skill / "assets/verify-portable.py"),
                    str(build_output),
                    "--quiet",
                ]
            )
            runtime_lock = build_output / "runtime-lock.json"
            run_command(
                [
                    sys.executable,
                    str(target_skill / "assets/runtime-lock.py"),
                    "--skill-root",
                    str(target_skill),
                    "--deck-h5-commit",
                    commit,
                    "--output-dir",
                    str(build_output),
                    "--output",
                    str(runtime_lock),
                ]
            )
            run_command(
                [
                    sys.executable,
                    str(target_skill / "assets/runtime-lock.py"),
                    "--skill-root",
                    str(target_skill),
                    "--deck-h5-commit",
                    commit,
                    "--output-dir",
                    str(build_output),
                    "--check",
                    str(runtime_lock),
                ]
            )
            final_deck = load_deck(candidate_deck)
            validate_deck_conservation(
                source_deck,
                final_deck,
                migrations,
                migration_results,
            )
            validate_lazy_structure(build_output, final_deck)
            lock_payload = json.loads(runtime_lock.read_text(encoding="utf-8"))
            validate_runtime_lock_payload(
                lock_payload,
                commit,
                required_runtime_paths,
            )
            if tree_digest(source_run) != source_hash_before:
                raise UpgradeError("RUP-SRC-004", "source run changed during upgrade")
            shutil.copytree(
                build_run / "output",
                candidate_run / "output",
                symlinks=True,
            )
            candidate_output = candidate_run / "output"
            receipt = {
                "schema_version": 1,
                "status": "READY",
                "source": {
                    "deck_json": str(deck_json),
                    "run": str(source_run),
                    "tree_sha256": source_hash_before,
                    "runtime": read_source_runtime(source_output),
                },
                "target": {
                    **target,
                    "runtime_id": lock_payload["runtime_id"],
                    "snapshot_id": lock_payload["snapshot_id"],
                },
                "candidate_run": str(candidate_run),
                "candidate_output": str(candidate_output),
                "migrations": migration_results,
                "deck_json_changed_paths": changed_paths,
                "gates": {
                    "source_drift": "passed",
                    "render": "passed",
                    "visual": "passed",
                    "portable": "passed",
                    "runtime_lock": "passed",
                    "deck_json_conservation": "passed",
                    "lazy_structure": "passed",
                },
                "performance": {
                    "status": "unproven",
                    "reason": "no paired runtime benchmark was run",
                },
                "ready_to_publish": True,
                "published": False,
                "rollback_source": str(source_run),
            }
            write_report(candidate_run, receipt)
            if tree_digest(source_run) != source_hash_before:
                raise UpgradeError("RUP-SRC-004", "source run changed during upgrade")
            return receipt
    except Exception as exc:
        error = exc if isinstance(exc, UpgradeError) else UpgradeError("RUP-INT-001", str(exc))
        source_changed = tree_digest(source_run) != source_hash_before
        if source_changed and error.code != "RUP-SRC-004":
            error = UpgradeError(
                error.code,
                f"{error}; source run also changed during upgrade",
            )
        if candidate_run is not None and candidate_run.is_dir():
            error.state = "FAILED"
            error.candidate_run = candidate_run
            failed = {
                "schema_version": 1,
                "status": "FAILED",
                "source": {
                    "deck_json": str(deck_json),
                    "run": str(source_run),
                    "tree_sha256": source_hash_before,
                },
                "target": {"commit": commit},
                "candidate_run": str(candidate_run),
                "ready_to_publish": False,
                "published": False,
                "performance": {"status": "unproven"},
                "error": {"code": error.code, "message": str(error)},
                "source_invariant": "failed" if source_changed else "passed",
            }
            write_report(candidate_run, failed)
        raise error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck-json", required=True, type=Path)
    parser.add_argument("--to", choices=["current"], default="current")
    parser.add_argument("--target-commit", default="")
    parser.add_argument("--output-run", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = upgrade(
            args.deck_json,
            target_commit=args.target_commit,
            output_run=args.output_run,
            dry_run=args.dry_run,
        )
    except UpgradeError as exc:
        payload = {
            "status": exc.state,
            "ready_to_publish": False,
            "error": {"code": exc.code, "message": str(exc)},
        }
        if exc.candidate_run is not None:
            payload["candidate_run"] = str(exc.candidate_run)
        print(
            json.dumps(payload, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
