#!/usr/bin/env python3
"""Conservatively deduplicate run-level ``assets/shared`` directories.

Only these two locations are considered beneath each immediate run directory:

* ``runs/<run>/assets/shared``
* ``runs/<run>/output/assets/shared``

A real directory is eligible only when every file has a same-relative-path,
byte-identical counterpart in the canonical skill pool. Eligible directories
are reported by default; ``--apply`` atomically swaps them for a *relative*
symlink. Conflicts, missing canonical files, foreign symlinks and special files
are left untouched. No other run artifact is inspected or deleted.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
DEFAULT_CANONICAL = SKILL_ROOT / "assets" / "shared"
DEFAULT_RUNS = SKILL_ROOT.parent.parent / "runs"


@dataclass(frozen=True)
class Inspection:
    state: str
    logical_bytes: int = 0
    files: int = 0
    reason: str = ""


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _same_filesystem_entry(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return left.resolve() == right.resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_shared_dir(path: Path, canonical: Path) -> Inspection:
    """Classify one candidate without mutating it."""
    canonical = canonical.resolve()
    if path.is_symlink():
        try:
            if _same_filesystem_entry(path, canonical):
                return Inspection("already")
            target = os.readlink(path)
        except OSError as exc:
            target = f"unreadable ({exc})"
        return Inspection("skip", reason=f"foreign symlink -> {target}")
    if not _lexists(path):
        return Inspection("missing")
    if not path.is_dir():
        return Inspection("skip", reason="candidate is not a directory")

    logical_bytes = 0
    files = 0
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        root = Path(dirpath)
        for name in sorted(dirnames):
            child = root / name
            if child.is_symlink():
                rel = child.relative_to(path).as_posix()
                expected = canonical / child.relative_to(path)
                if not expected.is_dir() or not _same_filesystem_entry(child, expected):
                    return Inspection("skip", reason=f"foreign nested symlink: {rel}")
                logical_bytes += child.lstat().st_size
                files += 1
        for name in sorted(filenames):
            source = root / name
            rel = source.relative_to(path)
            expected = canonical / rel
            if source.is_symlink():
                if not expected.is_file() or not _same_filesystem_entry(source, expected):
                    return Inspection(
                        "skip", reason=f"foreign file symlink: {rel.as_posix()}")
                logical_bytes += source.lstat().st_size
                files += 1
                continue
            if not source.is_file():
                return Inspection(
                    "skip", reason=f"non-regular file: {rel.as_posix()}")
            if expected.is_symlink() or not expected.is_file():
                return Inspection(
                    "skip", reason=f"not in canonical pool: {rel.as_posix()}")
            source_size = source.stat().st_size
            if source_size != expected.stat().st_size or _sha256(source) != _sha256(expected):
                return Inspection(
                    "skip", reason=f"content mismatch: {rel.as_posix()}")
            logical_bytes += source_size
            files += 1

    if files == 0:
        return Inspection("skip", reason="empty shared directory")
    return Inspection("eligible", logical_bytes=logical_bytes, files=files)


def _candidate_paths(runs: Path) -> list[Path]:
    candidates: list[Path] = []
    if not runs.is_dir():
        return candidates
    for run in sorted(runs.iterdir(), key=lambda item: item.name):
        if not run.is_dir() or run.is_symlink():
            continue
        candidates.extend((run / "assets" / "shared", run / "output" / "assets" / "shared"))
    return [candidate for candidate in candidates if _lexists(candidate)]


def _atomic_replace_with_relative_link(
        path: Path, canonical: Path, expected: Inspection) -> None:
    """Swap an eligible directory for a relative link, with safe rollback."""
    token = uuid.uuid4().hex
    pending = path.parent / f".{path.name}.compact-{token}.link"
    backup = path.parent / f".{path.name}.compact-{token}.backup"
    relative_target = os.path.relpath(canonical.resolve(), start=path.parent.resolve())
    pending.symlink_to(relative_target, target_is_directory=True)
    moved = False
    installed = False
    try:
        os.replace(path, backup)
        moved = True
        # Revalidate the exact directory snapshot that will be deleted. A file
        # changed between the dry inspection and rename must never be discarded.
        current = inspect_shared_dir(backup, canonical)
        if (current.state != "eligible" or current.files != expected.files or
                current.logical_bytes != expected.logical_bytes):
            raise RuntimeError(
                f"candidate changed during compaction: {current.reason or current.state}")
        os.replace(pending, path)
        installed = True
        shutil.rmtree(backup)
    except BaseException:
        # Before link installation, restore the untouched directory. If cleanup
        # itself failed after installation, keep the working canonical link and
        # any remaining backup rather than restoring a possibly partial tree.
        if not installed and moved and _lexists(backup) and not _lexists(path):
            os.replace(backup, path)
            moved = False
        raise
    finally:
        if _lexists(pending):
            pending.unlink()


def _human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{value} B"  # pragma: no cover


def run(runs: Path, canonical: Path, *, apply: bool) -> int:
    if not canonical.is_dir():
        print(f"compact-runs: canonical shared pool not found: {canonical}", file=sys.stderr)
        return 2
    if not runs.is_dir():
        print(f"compact-runs: runs directory not found: {runs}", file=sys.stderr)
        return 2

    counts = {"eligible": 0, "linked": 0, "already": 0, "skipped": 0, "errors": 0}
    reclaimable = 0
    reclaimed = 0
    for candidate in _candidate_paths(runs):
        inspection = inspect_shared_dir(candidate, canonical)
        shown = candidate.relative_to(runs).as_posix()
        if inspection.state == "already":
            counts["already"] += 1
            print(f"ALREADY    {shown} (canonical symlink)")
        elif inspection.state == "skip":
            counts["skipped"] += 1
            print(f"SKIP       {shown} ({inspection.reason})")
        elif inspection.state == "eligible":
            counts["eligible"] += 1
            reclaimable += inspection.logical_bytes
            if not apply:
                print(
                    f"WOULD LINK {shown} ({inspection.files} files, "
                    f"{_human_bytes(inspection.logical_bytes)} reclaimable)")
                continue
            try:
                _atomic_replace_with_relative_link(candidate, canonical, inspection)
            except Exception as exc:
                counts["errors"] += 1
                print(f"ERROR      {shown} ({exc})", file=sys.stderr)
                continue
            counts["linked"] += 1
            reclaimed += inspection.logical_bytes
            print(
                f"LINKED      {shown} ({inspection.files} files, "
                f"{_human_bytes(inspection.logical_bytes)} reclaimed)")

    mode = "apply" if apply else "dry-run"
    print(
        f"Summary [{mode}]: eligible={counts['eligible']} linked={counts['linked']} "
        f"already={counts['already']} skipped={counts['skipped']} "
        f"errors={counts['errors']} "
        f"{'reclaimed' if apply else 'reclaimable'}="
        f"{_human_bytes(reclaimed if apply else reclaimable)}")
    return 1 if counts["errors"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "runs", nargs="?", type=Path, default=DEFAULT_RUNS,
        help=f"runs directory (default: {DEFAULT_RUNS})")
    parser.add_argument(
        "--canonical", type=Path, default=DEFAULT_CANONICAL,
        help=f"canonical shared pool (default: {DEFAULT_CANONICAL})")
    parser.add_argument(
        "--apply", action="store_true",
        help="perform eligible replacements (default is dry-run)")
    args = parser.parse_args(argv)
    return run(args.runs.resolve(), args.canonical.resolve(), apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
