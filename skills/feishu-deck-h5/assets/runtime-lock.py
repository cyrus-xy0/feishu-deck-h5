#!/usr/bin/env python3
"""Build or verify the immutable Feishu Deck runtime lock."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Mapping


SCRIPT_PATH = Path(__file__).resolve()
DEFAULT_SKILL_ROOT = SCRIPT_PATH.parents[1]
RUNTIME_MANIFEST = Path("runtime/runtime-files.json")
RUNTIME_PROVENANCE = Path("runtime/runtime-provenance.json")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(value: str) -> bool:
    path = Path(value)
    return bool(
        value
        and "\\" not in value
        and "\0" not in value
        and not re.match(r"^[A-Za-z]:", value)
        and not path.is_absolute()
        and value == path.as_posix()
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def read_runtime_manifest(skill_root: Path) -> list[dict[str, str]]:
    path = skill_root / RUNTIME_MANIFEST
    try:
        raw = _read_regular_worktree_file(
            skill_root,
            RUNTIME_MANIFEST.as_posix(),
            "runtime manifest",
        )
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid runtime file manifest: {path}: {exc}") from exc
    return _parse_runtime_manifest(payload, path)


def _parse_runtime_manifest(
    payload: object,
    path: Path,
) -> list[dict[str, str]]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"invalid runtime file manifest schema: {path}")
    schema_version = payload.get("schema_version")
    if (
        type(schema_version) is not int
        or schema_version != 1
        or not isinstance(payload.get("files"), list)
    ):
        raise ValueError(f"invalid runtime file manifest schema: {path}")

    files: list[dict[str, str]] = []
    seen_sources: set[str] = set()
    seen_targets: set[str] = set()
    for item in payload["files"]:
        if not isinstance(item, Mapping):
            raise ValueError(f"invalid runtime file entry: {item!r}")
        source_value = item.get("source_path")
        package_value = item.get("package_path")
        if not isinstance(source_value, str) or not isinstance(package_value, str):
            raise ValueError(f"invalid runtime file entry: {item!r}")
        source_path = source_value
        package_path = package_value
        if (
            not _safe_relative_path(source_path)
            or not _safe_relative_path(package_path)
        ):
            raise ValueError(f"unsafe runtime file entry: {item!r}")
        if source_path in seen_sources or package_path in seen_targets:
            raise ValueError(f"duplicate runtime file entry: {item!r}")
        seen_sources.add(source_path)
        seen_targets.add(package_path)
        files.append({"source_path": source_path, "package_path": package_path})
    if not files:
        raise ValueError("runtime file manifest must not be empty")
    return sorted(files, key=lambda item: item["source_path"])


def _git_repository_root(skill_root: Path) -> Path | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(skill_root), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return Path(value).resolve() if value else None


def resolve_deck_h5_commit(
    skill_root: Path,
    files: list[dict[str, str]],
    explicit: str = "",
) -> str:
    value = (
        explicit.strip().lower()
        or os.environ.get("FEISHU_DECK_H5_COMMIT", "").strip().lower()
    )
    if not value:
        completed = subprocess.run(
            [
                "git",
                "-C",
                str(skill_root),
                "log",
                "-1",
                "--format=%H",
                "HEAD",
                "--",
                RUNTIME_MANIFEST.as_posix(),
                *(item["source_path"] for item in files),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode == 0:
            value = completed.stdout.strip().lower()
    if not COMMIT_RE.fullmatch(value):
        raise ValueError(
            "deck_h5_commit is unavailable; run from a Git checkout or set "
            "FEISHU_DECK_H5_COMMIT to the trusted 40-character commit"
        )
    return value


def verify_runtime_sources_at_commit(
    skill_root: Path,
    files: list[dict[str, str]],
    commit: str,
) -> dict[str, bytes]:
    repo_root = _git_repository_root(skill_root)
    if repo_root is None:
        raise ValueError(
            "cannot verify runtime provenance outside a Git checkout; set up a "
            "trusted checkout before building a library package"
        )
    try:
        skill_relative = skill_root.relative_to(repo_root)
    except ValueError as exc:
        raise ValueError(f"skill root escapes repository: {skill_root}") from exc

    object_type = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "-t", commit],
        check=False,
        capture_output=True,
        text=True,
    )
    if object_type.returncode != 0 or object_type.stdout.strip() != "commit":
        raise ValueError(f"trusted Git object is not a commit: {commit}")

    manifest_relative = (skill_relative / RUNTIME_MANIFEST).as_posix()
    manifest_blob = _read_commit_blob(
        repo_root,
        commit,
        manifest_relative,
        "runtime manifest",
    )
    manifest_working = _read_regular_worktree_file(
        repo_root,
        manifest_relative,
        "runtime manifest",
    )
    if manifest_blob != manifest_working:
        raise ValueError(
            f"runtime manifest differs from trusted commit {commit}: "
            f"{manifest_relative}; commit the runtime before packaging"
        )
    try:
        trusted_payload = json.loads(manifest_blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"invalid runtime file manifest in trusted commit {commit}: {exc}"
        ) from exc
    trusted_files = _parse_runtime_manifest(
        trusted_payload,
        Path(manifest_relative),
    )
    if files != trusted_files:
        raise ValueError("runtime manifest changed while verifying provenance")

    trusted_sources: dict[str, bytes] = {}
    for item in trusted_files:
        source_path = item["source_path"]
        repo_relative = (skill_relative / source_path).as_posix()
        blob = _read_commit_blob(
            repo_root,
            commit,
            repo_relative,
            "runtime source",
        )
        working = _read_regular_worktree_file(
            repo_root,
            repo_relative,
            "runtime source",
        )
        if blob != working:
            raise ValueError(
                f"runtime source differs from trusted commit {commit}: "
                f"{repo_relative}; commit the runtime before packaging"
            )
        trusted_sources[source_path] = blob
    return trusted_sources


def _read_regular_worktree_file(
    repo_root: Path,
    repo_relative: str,
    label: str,
) -> bytes:
    path = repo_root
    for part in Path(repo_relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError(
                f"{label} working tree path contains a symlink: {repo_relative}"
            )
    if not path.is_file():
        raise ValueError(f"{label} is missing from working tree: {repo_relative}")
    return path.read_bytes()


def _read_commit_blob(
    repo_root: Path,
    commit: str,
    repo_relative: str,
    label: str,
) -> bytes:
    entry = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "ls-tree",
            "--full-tree",
            "-z",
            commit,
            "--",
            repo_relative,
        ],
        check=False,
        capture_output=True,
    )
    records = [record for record in entry.stdout.split(b"\0") if record]
    if entry.returncode != 0 or len(records) != 1:
        raise ValueError(
            f"{label} is absent from trusted commit {commit}: {repo_relative}"
        )
    try:
        metadata, raw_path = records[0].split(b"\t", 1)
        mode, object_type, object_id = metadata.split(b" ", 2)
        tree_path = raw_path.decode("utf-8")
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(
            f"invalid {label} tree entry in trusted commit {commit}: {repo_relative}"
        ) from exc
    if (
        tree_path != repo_relative
        or mode not in {b"100644", b"100755"}
        or object_type != b"blob"
    ):
        raise ValueError(
            f"{label} is not a regular Git blob in trusted commit {commit}: "
            f"{repo_relative}"
        )
    blob = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "blob", object_id.decode("ascii")],
        check=False,
        capture_output=True,
    )
    if blob.returncode != 0:
        raise ValueError(
            f"cannot read {label} from trusted commit {commit}: {repo_relative}"
        )
    return blob.stdout


def _sidecar_commit_owns_runtime_path(
    skill_root: Path,
    commit: object,
) -> bool:
    if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
        return False
    repo_root = _git_repository_root(skill_root)
    if repo_root is None:
        return False
    try:
        skill_relative = skill_root.relative_to(repo_root)
    except ValueError:
        return False
    object_type = subprocess.run(
        ["git", "-C", str(repo_root), "cat-file", "-t", commit],
        check=False,
        capture_output=True,
        text=True,
    )
    if object_type.returncode != 0 or object_type.stdout.strip() != "commit":
        return False
    try:
        _read_commit_blob(
            repo_root,
            commit,
            (skill_relative / RUNTIME_MANIFEST).as_posix(),
            "runtime manifest",
        )
    except ValueError:
        return False
    return True


def _manifest_framework_paths(path: Path) -> set[str]:
    active = False
    result: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not raw.startswith((" ", "\t")):
            active = stripped == "framework:"
            continue
        if active and stripped.startswith("- "):
            value = stripped[2:].strip().strip("\"'")
            if value:
                result.add(value)
    return result


def verify_output_runtime(
    output_dir: Path,
    files: list[dict[str, str]],
    trusted_sources: Mapping[str, bytes],
) -> list[str]:
    manifest = output_dir / "assets-manifest.yaml"
    if not manifest.is_file():
        raise ValueError(f"missing assets-manifest.yaml: {manifest}")
    framework_paths = _manifest_framework_paths(manifest)
    by_package = {item["package_path"]: item for item in files}
    unknown_executable = sorted(
        path
        for path in framework_paths
        if Path(path).suffix.lower() in {".css", ".js", ".mjs", ".cjs", ".wasm"}
        and path not in by_package
    )
    if unknown_executable:
        raise ValueError(
            "uncontrolled executable framework file(s): "
            + ", ".join(unknown_executable)
        )
    active_files: list[str] = []
    for package_path in sorted(framework_paths & by_package.keys()):
        item = by_package[package_path]
        packaged = (output_dir / package_path).resolve()
        try:
            packaged.relative_to(output_dir)
        except ValueError as exc:
            raise ValueError(f"runtime package path escapes output: {package_path}") from exc
        if not packaged.is_file():
            raise ValueError(f"active runtime file is missing from output: {package_path}")
        if packaged.read_bytes() != trusted_sources[item["source_path"]]:
            raise ValueError(
                f"packaged runtime differs from trusted skill source: {package_path}"
            )
        active_files.append(package_path)
    return active_files


def content_id(files: list[Mapping[str, object]]) -> str:
    identities = [
        {
            "source_path": str(item["source_path"]),
            "package_path": str(item["package_path"]),
            "sha256": str(item["sha256"]),
        }
        for item in sorted(files, key=lambda value: str(value["package_path"]))
    ]
    canonical = json.dumps(
        {"schema_version": 1, "files": identities},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256-" + hashlib.sha256(canonical).hexdigest()


def _runtime_file_entries(
    files: list[dict[str, str]],
    trusted_sources: Mapping[str, bytes],
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for item in files:
        source = trusted_sources[item["source_path"]]
        entries.append(
            {
                "source_path": item["source_path"],
                "package_path": item["package_path"],
                "sha256": hashlib.sha256(source).hexdigest(),
                "size": len(source),
            }
        )
    return entries


def read_runtime_provenance(skill_root: Path) -> dict[str, object]:
    path = skill_root / RUNTIME_PROVENANCE
    try:
        raw = _read_regular_worktree_file(
            skill_root,
            RUNTIME_PROVENANCE.as_posix(),
            "runtime provenance",
        )
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid runtime provenance: {path}: {exc}") from exc
    expected_keys = {
        "schema_version",
        "deck_h5_commit",
        "manifest",
        "snapshot_id",
        "files",
    }
    if (
        not isinstance(payload, dict)
        or set(payload) != expected_keys
        or type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != 1
    ):
        raise ValueError(f"invalid runtime provenance schema: {path}")
    return payload


def build_runtime_provenance(
    skill_root: Path,
    *,
    deck_h5_commit: str = "",
) -> dict[str, object]:
    skill_root = skill_root.expanduser().resolve()
    files = read_runtime_manifest(skill_root)
    commit = resolve_deck_h5_commit(skill_root, files, deck_h5_commit)
    trusted_sources = verify_runtime_sources_at_commit(skill_root, files, commit)
    file_entries = _runtime_file_entries(files, trusted_sources)
    manifest_bytes = _read_regular_worktree_file(
        skill_root,
        RUNTIME_MANIFEST.as_posix(),
        "runtime manifest",
    )
    return {
        "schema_version": 1,
        "deck_h5_commit": commit,
        "manifest": {
            "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "size": len(manifest_bytes),
        },
        "snapshot_id": content_id(file_entries),
        "files": file_entries,
    }


def write_runtime_provenance(
    path: Path,
    payload: Mapping[str, object],
) -> None:
    write_runtime_lock(path, payload)


def verify_runtime_sources_from_provenance(
    skill_root: Path,
    files: list[dict[str, str]],
    explicit_commit: str = "",
) -> tuple[str, dict[str, bytes]]:
    # This sidecar proves distribution self-consistency only. The emitted
    # commit/snapshot still has to be admitted from official main by the
    # Slide Library consumer; the package never becomes a trust root.
    provenance = read_runtime_provenance(skill_root)
    sidecar_commit = provenance["deck_h5_commit"]
    if not isinstance(sidecar_commit, str) or not COMMIT_RE.fullmatch(
        sidecar_commit
    ):
        raise ValueError("invalid packaged runtime provenance commit")
    requested_commit = (
        explicit_commit.strip().lower()
        or os.environ.get("FEISHU_DECK_H5_COMMIT", "").strip().lower()
    )
    if requested_commit and not COMMIT_RE.fullmatch(requested_commit):
        raise ValueError(
            "deck_h5_commit must be a trusted 40-character commit"
        )
    if requested_commit and requested_commit != sidecar_commit:
        raise ValueError(
            "requested deck_h5_commit differs from packaged runtime provenance"
        )

    manifest_bytes = _read_regular_worktree_file(
        skill_root,
        RUNTIME_MANIFEST.as_posix(),
        "runtime manifest",
    )
    actual_manifest = {
        "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "size": len(manifest_bytes),
    }
    if provenance["manifest"] != actual_manifest:
        raise ValueError(
            "runtime manifest differs from packaged runtime provenance"
        )

    provenance_files = provenance["files"]
    trusted_sources: dict[str, bytes] = {}
    for item in files:
        source_path = item["source_path"]
        trusted_sources[source_path] = _read_regular_worktree_file(
            skill_root,
            source_path,
            "runtime source",
        )
    actual_entries = _runtime_file_entries(files, trusted_sources)
    if actual_entries != provenance_files:
        raise ValueError(
            "runtime source differs from packaged runtime provenance"
        )
    if provenance["snapshot_id"] != content_id(actual_entries):
        raise ValueError(
            "runtime provenance snapshot checksum mismatch"
        )
    return sidecar_commit, trusted_sources


def build_runtime_lock(
    skill_root: Path,
    *,
    deck_h5_commit: str = "",
    output_dir: Path | None = None,
) -> dict[str, object]:
    skill_root = skill_root.expanduser().resolve()
    files = read_runtime_manifest(skill_root)
    sidecar_path = skill_root / RUNTIME_PROVENANCE
    sidecar_present = sidecar_path.exists() or sidecar_path.is_symlink()
    sidecar = read_runtime_provenance(skill_root) if sidecar_present else None
    strict_git = not sidecar_present or _sidecar_commit_owns_runtime_path(
        skill_root,
        sidecar["deck_h5_commit"] if sidecar is not None else "",
    )
    if strict_git:
        requested_commit = (
            deck_h5_commit
            or os.environ.get("FEISHU_DECK_H5_COMMIT", "")
            or str(sidecar["deck_h5_commit"] if sidecar is not None else "")
        )
        commit = resolve_deck_h5_commit(skill_root, files, requested_commit)
        trusted_sources = verify_runtime_sources_at_commit(
            skill_root,
            files,
            commit,
        )
    else:
        commit, trusted_sources = verify_runtime_sources_from_provenance(
            skill_root,
            files,
            deck_h5_commit,
        )
    file_entries = _runtime_file_entries(files, trusted_sources)

    active_files = (
        verify_output_runtime(
            output_dir.expanduser().resolve(),
            files,
            trusted_sources,
        )
        if output_dir is not None
        else [item["package_path"] for item in files]
    )
    active_set = set(active_files)
    active_entries = [
        item for item in file_entries if str(item["package_path"]) in active_set
    ]
    return {
        "schema_version": 1,
        "runtime_id": content_id(active_entries),
        "snapshot_id": content_id(file_entries),
        "deck_h5_commit": commit,
        "files": active_entries,
    }


def write_runtime_lock(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", type=Path, default=DEFAULT_SKILL_ROOT)
    parser.add_argument("--deck-h5-commit", default="")
    parser.add_argument("--output-dir", type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--provenance-output", type=Path)
    action.add_argument("--check", type=Path)
    action.add_argument("--print-commit", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.provenance_output:
            provenance = build_runtime_provenance(
                args.skill_root,
                deck_h5_commit=args.deck_h5_commit,
            )
            write_runtime_provenance(args.provenance_output, provenance)
            print(f"snapshot_id={provenance['snapshot_id']}")
            return 0
        payload = build_runtime_lock(
            args.skill_root,
            deck_h5_commit=args.deck_h5_commit,
            output_dir=args.output_dir,
        )
        if args.print_commit:
            print(payload["deck_h5_commit"])
            return 0
        if args.output:
            write_runtime_lock(args.output, payload)
            print(f"runtime_id={payload['runtime_id']}")
            return 0
        expected = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        actual = args.check.read_text(encoding="utf-8")
        if actual != expected:
            print(f"ERROR: runtime lock drift: {args.check}", file=sys.stderr)
            return 1
        print(f"runtime lock verified: {payload['runtime_id']}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
