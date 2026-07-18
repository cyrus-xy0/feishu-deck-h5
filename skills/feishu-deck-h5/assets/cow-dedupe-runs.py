#!/usr/bin/env python3
"""Deduplicate byte-identical run files with APFS COW clones.

PNG and ZIP are the default extensions. ``--extensions`` may widen the set,
and ``--scope run-assets`` limits discovery to each immediate run's
``assets/`` and ``output/assets/`` trees.

The command is deliberately conservative:

* dry-run by default; ``--apply`` is required for writes;
* scans regular files only and never follows symlinks;
* groups by size before SHA-256;
* keeps every pathname and creates an independent inode via macOS
  ``clonefile(2)`` (no best-effort copy fallback);
* atomically replaces a target only after source/target identity and hashes are
  revalidated;
* skips hardlinks, ownership/device mismatches, flags, ACLs, and xattrs rather
  than risking a metadata change;
* records verified clone targets in a small manifest under the runs root so a
  second invocation reports ``already`` instead of pretending to save the same
  bytes again.

Birth time and ctime necessarily change when an inode is replaced. Target mode,
uid/gid, atime, and mtime are preserved; files carrying metadata that cannot be
reliably recreated are skipped.
"""

from __future__ import annotations

import argparse
import contextlib
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import stat
import sys
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
DEFAULT_RUNS = SKILL_ROOT.parent.parent / "runs"
DEFAULT_EXTENSIONS = frozenset({".png", ".zip"})
SCOPE_ALL = "all"
SCOPE_RUN_ASSETS = "run-assets"
DEFAULT_SCOPE = SCOPE_ALL
SCOPES = frozenset({SCOPE_ALL, SCOPE_RUN_ASSETS})
MANIFEST_NAME = ".feishu-deck-cow-dedupe.json"
LOCK_NAME = ".feishu-deck-cow-dedupe.lock"
MANIFEST_VERSION = 1

# /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/include/sys/clonefile.h
CLONE_NOFOLLOW = 0x0001
CLONE_ACL = 0x0004
CLONE_NOFOLLOW_ANY = 0x0008
XATTR_NOFOLLOW = 0x0001
RENAME_EXCL = 0x00000004


class DedupeError(RuntimeError):
    """Base class for a fail-closed operation."""


class RaceDetected(DedupeError):
    """A file changed between planning and atomic replacement."""


class UnsafeMetadata(DedupeError):
    """Target metadata cannot be reproduced safely."""


class CloneUnavailable(DedupeError):
    """The filesystem cannot provide a guaranteed COW clone."""


class ManifestError(DedupeError):
    """The state manifest is malformed or unsafe."""


@dataclass(frozen=True)
class Snapshot:
    dev: int
    inode: int
    size: int
    atime_ns: int
    mtime_ns: int
    ctime_ns: int
    mode: int
    uid: int
    gid: int
    flags: int
    nlink: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> "Snapshot":
        return cls(
            dev=value.st_dev,
            inode=value.st_ino,
            size=value.st_size,
            atime_ns=value.st_atime_ns,
            mtime_ns=value.st_mtime_ns,
            ctime_ns=value.st_ctime_ns,
            mode=stat.S_IMODE(value.st_mode),
            uid=value.st_uid,
            gid=value.st_gid,
            flags=getattr(value, "st_flags", 0),
            nlink=value.st_nlink,
        )

    @classmethod
    def read(cls, path: Path) -> "Snapshot":
        value = path.lstat()
        if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode):
            raise UnsafeMetadata("not a regular non-symlink file")
        return cls.from_stat(value)

    def guard(self) -> tuple[int, ...]:
        """Fields that must not change while hashing/cloning.

        atime is excluded because the read itself may update it. The original
        target atime is still restored onto the replacement inode.
        """
        return (
            self.dev, self.inode, self.size, self.mtime_ns, self.ctime_ns,
            self.mode, self.uid, self.gid, self.flags, self.nlink,
        )

    def renamed_guard(self) -> tuple[int, ...]:
        """Stable fields across a same-directory rename.

        Darwin updates ctime on rename, and reads may update atime. Both are
        intentionally omitted only for the post-rename backup validation.
        """
        return (
            self.dev, self.inode, self.size, self.mtime_ns, self.mode,
            self.uid, self.gid, self.flags, self.nlink,
        )


@dataclass
class Item:
    path: Path
    rel: str
    snapshot: Snapshot
    digest: str = ""


@dataclass
class Summary:
    candidates: int = 0
    hashed: int = 0
    would_clone: int = 0
    already: int = 0
    cloned: int = 0
    skipped: int = 0
    errors: int = 0
    duplicate_logical_bytes: int = 0
    logical_reclaimable_upper_bytes: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    def bump_reason(self, reason: str) -> None:
        self.reasons[reason] = self.reasons.get(reason, 0) + 1


CloneImpl = Callable[[Path, Path], None]
MetadataCheck = Callable[[Path, Snapshot], None]
Emit = Callable[[str], None]


def _lexists(path: Path) -> bool:
    return os.path.lexists(path)


def _human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{int(size)} B" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024
    return f"{value} B"  # pragma: no cover


def _assert_snapshot(path: Path, expected: Snapshot, label: str) -> Snapshot:
    current = Snapshot.read(path)
    if current.guard() != expected.guard():
        raise RaceDetected(f"{label} stat changed: {path}")
    return current


def _stable_sha256(path: Path, expected: Snapshot | None = None) -> tuple[str, Snapshot]:
    """Hash one regular file while binding the read fd to the path inode."""
    before = Snapshot.read(path)
    if expected is not None and before.guard() != expected.guard():
        raise RaceDetected(f"stat changed before hash: {path}")

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    noatime = getattr(os, "O_NOATIME", 0)
    try:
        fd = os.open(path, flags | noatime)
    except OSError as exc:
        # Linux exposes O_NOATIME, but may reject it when the caller does not
        # own the inode or the filesystem does not support it. Production runs
        # on macOS, where the flag is absent; keep the portable test seam and
        # read-only audit usable on other Unix filesystems.
        unsupported = {
            errno.EPERM,
            errno.EINVAL,
            getattr(errno, "ENOTSUP", errno.EINVAL),
            getattr(errno, "EOPNOTSUPP", errno.EINVAL),
        }
        if not noatime or exc.errno not in unsupported:
            raise
        fd = os.open(path, flags)
    try:
        fd_before = Snapshot.from_stat(os.fstat(fd))
        if fd_before.guard() != before.guard():
            raise RaceDetected(f"path/inode changed while opening: {path}")
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 4 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        fd_after = Snapshot.from_stat(os.fstat(fd))
    finally:
        os.close(fd)

    after = Snapshot.read(path)
    if fd_before.guard() != fd_after.guard() or fd_after.guard() != after.guard():
        raise RaceDetected(f"file changed while hashing: {path}")
    return digest.hexdigest(), after


_LIBC: ctypes.CDLL | None = None


def _libc() -> ctypes.CDLL:
    global _LIBC
    if _LIBC is None:
        _LIBC = ctypes.CDLL(None, use_errno=True)
    return _LIBC


def _has_extended_acl(path: Path) -> bool:
    """Return whether a macOS file has at least one extended ACL entry."""
    if sys.platform != "darwin":
        raise UnsafeMetadata("ACL inspection requires macOS")
    libc = _libc()
    try:
        get_file = libc.acl_get_file
        get_entry = libc.acl_get_entry
        free_acl = libc.acl_free
    except AttributeError as exc:  # pragma: no cover - old/non-Darwin libc
        raise UnsafeMetadata("macOS ACL API unavailable") from exc
    get_file.argtypes = [ctypes.c_char_p, ctypes.c_int]
    get_file.restype = ctypes.c_void_p
    get_entry.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
    get_entry.restype = ctypes.c_int
    free_acl.argtypes = [ctypes.c_void_p]
    free_acl.restype = ctypes.c_int

    ctypes.set_errno(0)
    acl = get_file(os.fsencode(path), 0x00000100)  # ACL_TYPE_EXTENDED
    if not acl:
        error = ctypes.get_errno()
        # Darwin reports ENOENT when a regular file has no extended ACL.
        if error == errno.ENOENT:
            return False
        raise UnsafeMetadata(f"cannot inspect ACL (errno={error})")
    try:
        entry = ctypes.c_void_p()
        rc = get_entry(acl, 0, ctypes.byref(entry))  # ACL_FIRST_ENTRY
        if rc == 0:
            return True
        if rc == 1:
            return False
        error = ctypes.get_errno()
        raise UnsafeMetadata(f"cannot enumerate ACL (errno={error})")
    finally:
        free_acl(acl)


def _list_xattrs(path: Path) -> tuple[str, ...]:
    """List macOS xattr names without relying on optional Python wrappers."""
    if sys.platform != "darwin":
        raise UnsafeMetadata("xattr inspection requires macOS")
    libc = _libc()
    try:
        listxattr = libc.listxattr
    except AttributeError as exc:  # pragma: no cover - old/non-Darwin libc
        raise UnsafeMetadata("macOS xattr API unavailable") from exc
    listxattr.argtypes = [
        ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int,
    ]
    listxattr.restype = ctypes.c_ssize_t

    encoded = os.fsencode(path)
    ctypes.set_errno(0)
    required = listxattr(encoded, None, 0, XATTR_NOFOLLOW)
    if required < 0:
        error = ctypes.get_errno()
        raise UnsafeMetadata(
            f"cannot inspect xattrs: {os.strerror(error)} (errno={error})")
    if required == 0:
        return ()

    buffer = ctypes.create_string_buffer(required)
    ctypes.set_errno(0)
    written = listxattr(encoded, buffer, required, XATTR_NOFOLLOW)
    if written < 0:
        error = ctypes.get_errno()
        raise UnsafeMetadata(
            f"cannot inspect xattrs: {os.strerror(error)} (errno={error})")
    raw_names = bytes(buffer.raw[:written])
    return tuple(os.fsdecode(name) for name in raw_names.split(b"\0") if name)


def _production_metadata_check(path: Path, snapshot: Snapshot) -> None:
    """Fail closed for metadata clonefile/copystat cannot safely normalize."""
    current = _assert_snapshot(path, snapshot, "metadata")
    if current.nlink != 1:
        raise UnsafeMetadata("hardlinked file")
    if current.flags:
        raise UnsafeMetadata(f"file flags present: 0x{current.flags:x}")
    xattrs = _list_xattrs(path)
    if xattrs:
        raise UnsafeMetadata(f"xattrs present: {','.join(sorted(xattrs))}")
    if _has_extended_acl(path):
        raise UnsafeMetadata("extended ACL present")


def _clonefile_cow(source: Path, destination: Path) -> None:
    """Create a guaranteed COW clone; never fall back to a byte copy."""
    if sys.platform != "darwin":
        raise CloneUnavailable("clonefile(2) requires macOS")
    if _lexists(destination):
        raise CloneUnavailable(f"clone destination already exists: {destination}")
    libc = _libc()
    try:
        clonefile = libc.clonefile
    except AttributeError as exc:
        raise CloneUnavailable("clonefile(2) is unavailable") from exc
    clonefile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
    clonefile.restype = ctypes.c_int
    ctypes.set_errno(0)
    rc = clonefile(
        os.fsencode(source), os.fsencode(destination),
        CLONE_NOFOLLOW | CLONE_ACL | CLONE_NOFOLLOW_ANY,
    )
    if rc != 0:
        error = ctypes.get_errno()
        message = os.strerror(error) if error else "unknown clonefile error"
        raise CloneUnavailable(f"clonefile failed: {message} (errno={error})")


def _rename_exclusive(source: Path, destination: Path) -> None:
    """Atomically rename without ever overwriting an unexpected pathname."""
    if sys.platform != "darwin":
        raise DedupeError("exclusive rename requires macOS")
    libc = _libc()
    try:
        renamex_np = libc.renamex_np
    except AttributeError as exc:  # pragma: no cover - old/non-Darwin libc
        raise DedupeError("renamex_np(2) is unavailable") from exc
    renamex_np.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    renamex_np.restype = ctypes.c_int
    ctypes.set_errno(0)
    rc = renamex_np(os.fsencode(source), os.fsencode(destination), RENAME_EXCL)
    if rc != 0:
        error = ctypes.get_errno()
        message = os.strerror(error) if error else "unknown rename error"
        if error == errno.EEXIST:
            raise RaceDetected(
                f"exclusive rename destination appeared: {destination}")
        raise DedupeError(
            f"exclusive rename failed: {message} (errno={error})")


def _atomic_clone_target(
        source: Item,
        target: Item,
        digest: str,
        clone_impl: CloneImpl,
        metadata_check: MetadataCheck) -> Snapshot:
    """Install a clone transactionally, retaining the original for rollback."""
    if source.snapshot.dev != target.snapshot.dev:
        raise CloneUnavailable("source and target are on different devices")
    if (source.snapshot.uid, source.snapshot.gid) != (
            target.snapshot.uid, target.snapshot.gid):
        raise UnsafeMetadata("source/target uid or gid differs")

    metadata_check(source.path, source.snapshot)
    metadata_check(target.path, target.snapshot)
    source_hash, source_now = _stable_sha256(source.path, source.snapshot)
    target_hash, target_now = _stable_sha256(target.path, target.snapshot)
    if source_hash != digest or target_hash != digest:
        raise RaceDetected("source/target hash changed before clone")

    token = uuid.uuid4().hex
    temp = target.path.parent / f".{target.path.name}.cow-{token}.tmp"
    backup = target.path.parent / f".{target.path.name}.cow-{token}.backup"
    failed = target.path.parent / f".{target.path.name}.cow-{token}.failed"
    if any(_lexists(path) for path in (temp, backup, failed)):
        raise DedupeError("temporary transaction path already exists")
    backup_moved = False
    installed_at_path = False
    installed_inode: int | None = None
    try:
        clone_impl(source.path, temp)
        temp_snapshot = Snapshot.read(temp)
        if temp_snapshot.dev != target.snapshot.dev:
            raise CloneUnavailable("clone landed on a different device")
        if temp_snapshot.inode in {source.snapshot.inode, target.snapshot.inode}:
            raise CloneUnavailable("clone did not create an independent inode")
        if temp_snapshot.size != target.snapshot.size:
            raise CloneUnavailable("clone size differs from target")

        temp_hash, temp_snapshot = _stable_sha256(temp, temp_snapshot)
        if temp_hash != digest:
            raise CloneUnavailable("clone content hash mismatch")

        # clonefile inherits source metadata. We only admit files without ACL,
        # xattrs, or flags, then explicitly restore target mode and timestamps.
        os.chmod(temp, target.snapshot.mode, follow_symlinks=False)
        os.utime(
            temp,
            ns=(target.snapshot.atime_ns, target.snapshot.mtime_ns),
            follow_symlinks=False,
        )
        temp_snapshot = Snapshot.read(temp)
        metadata_check(temp, temp_snapshot)
        if (temp_snapshot.uid, temp_snapshot.gid) != (
                target.snapshot.uid, target.snapshot.gid):
            raise UnsafeMetadata("clone uid/gid differs from target")
        if temp_snapshot.mode != target.snapshot.mode:
            raise UnsafeMetadata("clone mode differs from target")
        if temp_snapshot.mtime_ns != target.snapshot.mtime_ns:
            raise UnsafeMetadata("clone mtime differs from target")
        if temp_snapshot.atime_ns != target.snapshot.atime_ns:
            raise UnsafeMetadata("clone atime differs from target")

        # Re-hash both original paths immediately before replacement. The
        # target guard includes inode, device, size, mtime, ctime, ownership,
        # mode, flags, and link count.
        metadata_check(source.path, source_now)
        metadata_check(target.path, target_now)
        source_final_hash, source_final = _stable_sha256(source.path, source_now)
        target_final_hash, target_final = _stable_sha256(target.path, target_now)
        if source_final_hash != digest or target_final_hash != digest:
            raise RaceDetected("source/target hash changed before replace")
        _assert_snapshot(source.path, source_final, "source final")
        _assert_snapshot(target.path, target_final, "target final")

        # Move the original inode aside first. This closes the overwrite race:
        # the exact inode moved is revalidated, and the clone is installed with
        # RENAME_EXCL so a newly appeared path can never be overwritten.
        installed_inode = temp_snapshot.inode
        _rename_exclusive(target.path, backup)
        backup_moved = True
        backup_snapshot = Snapshot.read(backup)
        if backup_snapshot.renamed_guard() != target_final.renamed_guard():
            raise RaceDetected("target identity changed before backup rename")
        metadata_check(backup, backup_snapshot)
        backup_hash, backup_snapshot = _stable_sha256(backup, backup_snapshot)
        if (backup_hash != digest or
                backup_snapshot.renamed_guard() != target_final.renamed_guard()):
            raise RaceDetected("renamed target no longer matches the plan")

        _rename_exclusive(temp, target.path)
        installed_at_path = True
        installed = Snapshot.read(target.path)
        metadata_check(target.path, installed)
        if (installed.inode != installed_inode or
                installed.inode == source.snapshot.inode):
            raise DedupeError("atomic replacement inode verification failed")
        if installed.size != target.snapshot.size:
            raise DedupeError("installed clone size verification failed")
        if (installed.mode, installed.uid, installed.gid, installed.flags,
                installed.mtime_ns, installed.atime_ns) != (
                target.snapshot.mode, target.snapshot.uid, target.snapshot.gid,
                target.snapshot.flags, target.snapshot.mtime_ns,
                target.snapshot.atime_ns):
            raise DedupeError("installed clone metadata verification failed")

        # Only destroy the original after every installed-path check passes.
        backup.unlink()
        backup_moved = False
        return installed
    except BaseException as operation_error:
        rollback_error: Exception | None = None
        rollback_note: str | None = None
        if backup_moved:
            try:
                if installed_at_path:
                    # Move the current target aside, then verify it really is
                    # our installed clone before restoring the original. If an
                    # external writer won the path, put its file back and keep
                    # our original safely at ``backup``.
                    _rename_exclusive(target.path, failed)
                    displaced = Snapshot.read(failed)
                    displaced_is_clone = (
                        displaced.inode == installed_inode
                        and displaced.renamed_guard()
                        == temp_snapshot.renamed_guard()
                    )
                    if displaced_is_clone:
                        try:
                            metadata_check(failed, displaced)
                            displaced_hash, displaced = _stable_sha256(
                                failed, displaced)
                            displaced_is_clone = (
                                displaced_hash == digest
                                and displaced.renamed_guard()
                                == temp_snapshot.renamed_guard()
                            )
                        except (DedupeError, OSError):
                            displaced_is_clone = False
                    if not displaced_is_clone:
                        if not _lexists(target.path):
                            _rename_exclusive(failed, target.path)
                        raise RaceDetected(
                            "installed inode changed during rollback; its data "
                            f"was preserved and original retained at {backup}")
                    _rename_exclusive(backup, target.path)
                    backup_moved = False
                    installed_at_path = False
                    # Never unlink the displaced inode during error recovery:
                    # another process may still hold it open and write after
                    # our hash. The hidden path makes every byte recoverable.
                    rollback_note = (
                        f"original restored; displaced inode retained at {failed}")
                else:
                    if _lexists(target.path):
                        raise RaceDetected(
                            "target path appeared during rollback; original "
                            f"retained at {backup}")
                    _rename_exclusive(backup, target.path)
                    backup_moved = False
            except Exception as exc:  # preserve both files on rollback trouble
                rollback_error = exc
        if rollback_error is not None:
            raise DedupeError(
                f"operation failed ({operation_error}); rollback incomplete "
                f"({rollback_error})") from operation_error
        if rollback_note is not None:
            raise DedupeError(
                f"operation failed ({operation_error}); {rollback_note}") \
                from operation_error
        raise
    finally:
        if _lexists(temp):
            try:
                temp.unlink()
            except OSError:
                pass


def _manifest_path(root: Path) -> Path:
    return root / MANIFEST_NAME


def _load_manifest(root: Path) -> dict:
    path = _manifest_path(root)
    if path.is_symlink():
        raise ManifestError(f"manifest must not be a symlink: {path}")
    if not path.exists():
        return {"schema_version": MANIFEST_VERSION, "entries": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError(f"cannot read manifest: {exc}") from exc
    if payload.get("schema_version") != MANIFEST_VERSION:
        raise ManifestError("unsupported manifest schema")
    if not isinstance(payload.get("entries"), dict):
        raise ManifestError("manifest entries must be an object")
    return payload


def _entry_identity_valid(
        entry: object, item: Item, items_by_rel: dict[str, Item]) -> bool:
    if not isinstance(entry, dict):
        return False
    target_expected = {
        "dev": item.snapshot.dev,
        "inode": item.snapshot.inode,
        "size": item.snapshot.size,
        "mtime_ns": item.snapshot.mtime_ns,
        "ctime_ns": item.snapshot.ctime_ns,
        "mode": item.snapshot.mode,
        "uid": item.snapshot.uid,
        "gid": item.snapshot.gid,
        "flags": item.snapshot.flags,
        "nlink": item.snapshot.nlink,
    }
    if not all(entry.get(key) == value for key, value in target_expected.items()):
        return False
    source_state = entry.get("source")
    if not isinstance(source_state, dict):
        return False
    source_rel = source_state.get("path")
    source = items_by_rel.get(source_rel) if isinstance(source_rel, str) else None
    if source is None or source.rel == item.rel:
        return False
    source_expected = {
        "dev": source.snapshot.dev,
        "inode": source.snapshot.inode,
        "size": source.snapshot.size,
        "mtime_ns": source.snapshot.mtime_ns,
        "ctime_ns": source.snapshot.ctime_ns,
        "mode": source.snapshot.mode,
        "uid": source.snapshot.uid,
        "gid": source.snapshot.gid,
        "flags": source.snapshot.flags,
        "nlink": source.snapshot.nlink,
    }
    return all(
        source_state.get(key) == value
        for key, value in source_expected.items()
    )


def _entry_valid(
        entry: object, item: Item, items_by_rel: dict[str, Item]) -> bool:
    if not _entry_identity_valid(entry, item, items_by_rel):
        return False
    assert isinstance(entry, dict)  # narrowed by _entry_identity_valid
    source_state = entry["source"]
    source = items_by_rel[source_state["path"]]
    return (
        entry.get("sha256") == item.digest
        and source_state.get("sha256") == source.digest
        and source.digest == item.digest
    )


def _manifest_entry(item: Item, source: Item) -> dict:
    return {
        "dev": item.snapshot.dev,
        "inode": item.snapshot.inode,
        "size": item.snapshot.size,
        "mtime_ns": item.snapshot.mtime_ns,
        "ctime_ns": item.snapshot.ctime_ns,
        "sha256": item.digest,
        "mode": item.snapshot.mode,
        "uid": item.snapshot.uid,
        "gid": item.snapshot.gid,
        "flags": item.snapshot.flags,
        "nlink": item.snapshot.nlink,
        "source": {
            "path": source.rel,
            "dev": source.snapshot.dev,
            "inode": source.snapshot.inode,
            "size": source.snapshot.size,
            "mtime_ns": source.snapshot.mtime_ns,
            "ctime_ns": source.snapshot.ctime_ns,
            "sha256": source.digest,
            "mode": source.snapshot.mode,
            "uid": source.snapshot.uid,
            "gid": source.snapshot.gid,
            "flags": source.snapshot.flags,
            "nlink": source.snapshot.nlink,
        },
        "cloned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _write_manifest(root: Path, entries: dict) -> None:
    path = _manifest_path(root)
    temp = root / f".{MANIFEST_NAME}.{uuid.uuid4().hex}.tmp"
    payload = {
        "schema_version": MANIFEST_VERSION,
        "tool": Path(__file__).name,
        "root_dev": root.stat().st_dev,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "entries": dict(sorted(entries.items())),
    }
    try:
        with temp.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    finally:
        if _lexists(temp):
            temp.unlink()


@contextlib.contextmanager
def _apply_lock(root: Path) -> Iterator[None]:
    lock_path = root / LOCK_NAME
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN):
                raise DedupeError("another COW dedupe apply is running") from exc
            raise
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _real_directory(path: Path) -> bool:
    """Return whether ``path`` is a directory without traversing a symlink."""
    try:
        value = path.lstat()
    except OSError:
        return False
    return stat.S_ISDIR(value.st_mode)


def _discovery_roots(root: Path, scope: str) -> tuple[Path, ...]:
    if scope == SCOPE_ALL:
        return (root,)
    if scope != SCOPE_RUN_ASSETS:
        raise DedupeError(f"unsupported scope: {scope}")

    roots: list[Path] = []
    for run in sorted(root.iterdir(), key=lambda path: path.name):
        if not _real_directory(run):
            continue
        direct_assets = run / "assets"
        if _real_directory(direct_assets):
            roots.append(direct_assets)

        output = run / "output"
        if not _real_directory(output):
            continue
        output_assets = output / "assets"
        if _real_directory(output_assets):
            roots.append(output_assets)
    return tuple(roots)


def _rel_in_scope(rel: str, scope: str) -> bool:
    """Return whether a manifest-relative POSIX path belongs to ``scope``."""
    if scope == SCOPE_ALL:
        return True
    if scope != SCOPE_RUN_ASSETS:
        raise DedupeError(f"unsupported scope: {scope}")

    path = PurePosixPath(rel)
    parts = path.parts
    if (path.is_absolute() or not parts
            or any(part in {".", ".."} for part in parts)):
        return False
    return (
        len(parts) >= 3 and parts[1] == "assets"
    ) or (
        len(parts) >= 4
        and parts[1] == "output"
        and parts[2] == "assets"
    )


def _safe_manifest_regular_file(root: Path, rel: object) -> bool:
    """Verify a root-relative manifest path without following any symlink."""
    if not isinstance(rel, str) or not rel:
        return False
    parts = rel.split("/")
    if (PurePosixPath(rel).is_absolute()
            or any(part in {"", ".", ".."} for part in parts)):
        return False

    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory is None:  # pragma: no cover - Unix tool
        return False
    directory_flags = os.O_RDONLY | nofollow | directory
    directory_fd: int | None = None
    try:
        directory_fd = os.open(root, directory_flags)
        for part in parts[:-1]:
            value = os.stat(
                part, dir_fd=directory_fd, follow_symlinks=False)
            if not stat.S_ISDIR(value.st_mode):
                return False
            next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        value = os.stat(
            parts[-1], dir_fd=directory_fd, follow_symlinks=False)
        return stat.S_ISREG(value.st_mode)
    except (OSError, ValueError):
        return False
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def _discover(
        root: Path,
        extensions: frozenset[str],
        summary: Summary,
        *,
        scope: str = DEFAULT_SCOPE) -> list[Item]:
    items: list[Item] = []
    for discovery_root in _discovery_roots(root, scope):
        for dirpath, dirnames, filenames in os.walk(
                discovery_root, followlinks=False):
            parent = Path(dirpath)
            # os.walk does not descend with followlinks=False, but removing links
            # explicitly makes that safety boundary obvious and platform-independent.
            dirnames[:] = [
                name for name in dirnames
                if not (parent / name).is_symlink()
            ]
            for name in filenames:
                path = parent / name
                if path.suffix.lower() not in extensions:
                    continue
                summary.candidates += 1
                try:
                    value = path.lstat()
                except OSError:
                    summary.errors += 1
                    summary.bump_reason("lstat-error")
                    continue
                if stat.S_ISLNK(value.st_mode) or not stat.S_ISREG(value.st_mode):
                    summary.skipped += 1
                    summary.bump_reason("symlink-or-nonregular")
                    continue
                items.append(Item(
                    path,
                    path.relative_to(root).as_posix(),
                    Snapshot.from_stat(value),
                ))
    return items


def _dedupe_locked(
        root: Path,
        *,
        apply: bool,
        extensions: frozenset[str],
        scope: str,
        clone_impl: CloneImpl,
        metadata_check: MetadataCheck,
        emit: Emit) -> Summary:
    summary = Summary()
    manifest = _load_manifest(root)
    entries = dict(manifest.get("entries", {}))
    manifest_changed = False
    # Applying any scope also garbage-collects globally broken relationships.
    # A live out-of-scope entry remains untouched, but missing, malformed,
    # traversal-based, or symlink-backed target/source paths cannot remain as
    # trusted clone state.
    if apply:
        for rel in list(entries):
            entry = entries.get(rel)
            source_state = (
                entry.get("source") if isinstance(entry, dict) else None)
            source_rel = (
                source_state.get("path")
                if isinstance(source_state, dict) else None
            )
            if (_safe_manifest_regular_file(root, rel)
                    and _safe_manifest_regular_file(root, source_rel)):
                continue
            entries.pop(rel, None)
            manifest_changed = True
    items = _discover(root, extensions, summary, scope=scope)
    items_by_rel = {item.rel: item for item in items}
    # Drop stale state only inside this invocation's extension and discovery
    # scopes. Filtered-out targets or sources are preserved conservatively so
    # a scoped audit cannot erase state owned by another scope.
    for rel in list(entries):
        if Path(rel).suffix.lower() not in extensions:
            continue
        if not _rel_in_scope(rel, scope):
            continue
        item = items_by_rel.get(rel)
        entry = entries.get(rel)
        source_state = entry.get("source") if isinstance(entry, dict) else None
        source_rel = (
            source_state.get("path") if isinstance(source_state, dict) else None
        )
        if (isinstance(source_rel, str)
                and Path(source_rel).suffix.lower() not in extensions):
            continue
        if (isinstance(source_rel, str)
                and not _rel_in_scope(source_rel, scope)):
            continue
        if (item is None
                or not _entry_identity_valid(entry, item, items_by_rel)):
            entries.pop(rel, None)
            manifest_changed = True
    by_size: dict[int, list[Item]] = defaultdict(list)
    for item in items:
        by_size[item.snapshot.size].append(item)

    by_content: dict[tuple[int, str], list[Item]] = defaultdict(list)
    for size, group in by_size.items():
        if len(group) < 2:
            summary.skipped += len(group)
            summary.bump_reason("unique-size")
            continue
        for item in group:
            try:
                item.digest, item.snapshot = _stable_sha256(item.path, item.snapshot)
            except (DedupeError, OSError) as exc:
                summary.errors += 1
                summary.bump_reason("hash-race-or-error")
                emit(f"ERROR      {item.rel} ({exc})")
                continue
            summary.hashed += 1
            by_content[(size, item.digest)].append(item)

    for (size, digest), group in sorted(
            by_content.items(), key=lambda pair: (pair[0][0], pair[0][1])):
        if len(group) < 2:
            summary.skipped += len(group)
            summary.bump_reason("unique-content")
            continue
        summary.duplicate_logical_bytes += size * (len(group) - 1)

        safe: list[Item] = []
        for item in sorted(group, key=lambda value: value.rel):
            try:
                metadata_check(item.path, item.snapshot)
            except (DedupeError, OSError) as exc:
                summary.skipped += 1
                summary.bump_reason("unsafe-metadata")
                emit(f"SKIP       {item.rel} ({exc})")
                continue
            safe.append(item)

        compatible: dict[tuple[int, int, int], list[Item]] = defaultdict(list)
        for item in safe:
            compatible[(item.snapshot.dev, item.snapshot.uid, item.snapshot.gid)].append(item)

        for subgroup in compatible.values():
            subgroup.sort(key=lambda value: value.rel)
            if len(subgroup) < 2:
                summary.skipped += 1
                summary.bump_reason("no-compatible-source")
                emit(f"SKIP       {subgroup[0].rel} (no same-device/same-owner source)")
                continue

            valid_state = {
                item.rel: _entry_valid(entries.get(item.rel), item, items_by_rel)
                for item in subgroup
            }
            subgroup_by_rel = {item.rel: item for item in subgroup}
            anchor_counts: dict[str, int] = defaultdict(int)
            for item in subgroup:
                if not valid_state[item.rel]:
                    continue
                entry = entries[item.rel]
                anchor_rel = entry["source"]["path"]
                if anchor_rel in subgroup_by_rel:
                    anchor_counts[anchor_rel] += 1
            if anchor_counts:
                # Preserve the live source currently referenced by the most
                # verified entries. This prevents adding an earlier pathname
                # from invalidating ALREADY relationships mid-run.
                anchor_rel = min(
                    anchor_counts,
                    key=lambda rel: (-anchor_counts[rel], rel),
                )
                source = subgroup_by_rel[anchor_rel]
            else:
                unrecorded = [
                    item for item in subgroup if not valid_state[item.rel]
                ]
                source = unrecorded[0] if unrecorded else subgroup[0]

            # A source is the retained anchor, never an ALREADY target. Remove
            # any historical target entry it might carry.
            if source.rel in entries:
                entries.pop(source.rel, None)
                manifest_changed = True

            for target in subgroup:
                if target is source:
                    continue
                target_entry = entries.get(target.rel)
                valid_for_source = (
                    valid_state[target.rel]
                    and isinstance(target_entry, dict)
                    and target_entry.get("source", {}).get("path") == source.rel
                )
                if valid_for_source:
                    summary.already += 1
                    emit(f"ALREADY    {target.rel} ({_human_bytes(size)})")
                    continue
                if target.rel in entries:
                    entries.pop(target.rel, None)
                    manifest_changed = True

                summary.logical_reclaimable_upper_bytes += size
                if not apply:
                    summary.would_clone += 1
                    emit(
                        f"WOULD CLONE {target.rel} <- {source.rel} "
                        f"({_human_bytes(size)})")
                    continue
                try:
                    installed = _atomic_clone_target(
                        source, target, digest, clone_impl, metadata_check)
                except (DedupeError, OSError) as exc:
                    summary.errors += 1
                    summary.bump_reason("clone-failed")
                    emit(f"ERROR      {target.rel} ({exc})")
                    continue
                target.snapshot = installed
                target.digest = digest
                entries[target.rel] = _manifest_entry(target, source)
                manifest_changed = True
                summary.cloned += 1
                emit(f"CLONED      {target.rel} <- {source.rel} ({_human_bytes(size)})")

    if apply and manifest_changed:
        try:
            _write_manifest(root, entries)
        except (OSError, ManifestError) as exc:
            summary.errors += 1
            summary.bump_reason("manifest-write-error")
            emit(f"ERROR      {MANIFEST_NAME} ({exc})")
    return summary


def dedupe_runs(
        root: Path,
        *,
        apply: bool = False,
        extensions: frozenset[str] = DEFAULT_EXTENSIONS,
        scope: str = DEFAULT_SCOPE,
        clone_impl: CloneImpl | None = None,
        metadata_check: MetadataCheck | None = None,
        emit: Emit = print) -> Summary:
    root = root.resolve()
    if not root.is_dir():
        raise DedupeError(f"runs directory not found: {root}")
    normalized = frozenset(
        extension.lower() if extension.startswith(".") else f".{extension.lower()}"
        for extension in extensions
    )
    if not normalized:
        raise DedupeError("at least one extension is required")
    if scope not in SCOPES:
        raise DedupeError(f"unsupported scope: {scope}")
    clone_impl = clone_impl or _clonefile_cow
    metadata_check = metadata_check or _production_metadata_check
    if apply:
        with _apply_lock(root):
            return _dedupe_locked(
                root, apply=True, extensions=normalized, scope=scope,
                clone_impl=clone_impl, metadata_check=metadata_check, emit=emit)
    return _dedupe_locked(
        root, apply=False, extensions=normalized, scope=scope,
        clone_impl=clone_impl, metadata_check=metadata_check, emit=emit)


def _print_summary(summary: Summary, *, apply: bool) -> None:
    mode = "apply" if apply else "dry-run"
    print(
        f"Summary [{mode}]: would_clone={summary.would_clone} "
        f"already={summary.already} cloned={summary.cloned} "
        f"skipped={summary.skipped} errors={summary.errors} "
        f"logical_reclaimable_upper="
        f"{_human_bytes(summary.logical_reclaimable_upper_bytes)} "
        f"duplicate_logical={_human_bytes(summary.duplicate_logical_bytes)}")
    print(
        f"Details: candidates={summary.candidates} hashed={summary.hashed} "
        f"reasons={json.dumps(summary.reasons, ensure_ascii=False, sort_keys=True)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "runs", nargs="?", type=Path, default=DEFAULT_RUNS,
        help=f"runs root (default: {DEFAULT_RUNS})")
    parser.add_argument(
        "--apply", action="store_true",
        help="atomically install verified COW clones (default is dry-run)")
    parser.add_argument(
        "--extensions", default="png,zip",
        help="comma-separated extensions (default: png,zip)")
    parser.add_argument(
        "--scope", choices=sorted(SCOPES), default=DEFAULT_SCOPE,
        help=(
            "discovery scope: all files, or only immediate-run assets and "
            "output/assets trees (default: all)"
        ))
    args = parser.parse_args(argv)
    extensions = frozenset(
        value.strip() for value in args.extensions.split(",") if value.strip())
    if sys.platform != "darwin":
        print("cow-dedupe-runs: macOS/APFS clonefile support is required", file=sys.stderr)
        return 2
    try:
        summary = dedupe_runs(
            args.runs, apply=args.apply, extensions=extensions,
            scope=args.scope)
    except (DedupeError, OSError) as exc:
        print(f"cow-dedupe-runs: {exc}", file=sys.stderr)
        return 2
    _print_summary(summary, apply=args.apply)
    return 1 if summary.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
