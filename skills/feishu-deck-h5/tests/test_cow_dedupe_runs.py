"""Safety and idempotency tests for assets/cow-dedupe-runs.py."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
TOOL = SKILL_ROOT / "assets" / "cow-dedupe-runs.py"


def _load_tool_module():
    name = "_cow_dedupe_runs_test_module"
    spec = importlib.util.spec_from_file_location(name, TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _portable_test_rename_exclusive(cow, source: Path, destination: Path) -> None:
    """Move a test file without overwriting an existing destination.

    The production tool deliberately uses Darwin ``renamex_np(RENAME_EXCL)``.
    Transaction tests already inject a byte-copy clone in place of APFS
    ``clonefile``; on non-Darwin CI they need an equivalent test seam for the
    second platform-specific primitive too.  A hard-link followed by unlink
    gives these same-directory regular-file tests an atomic no-overwrite
    destination create without weakening the production implementation.
    """
    try:
        os.link(source, destination, follow_symlinks=False)
    except FileExistsError as exc:
        raise cow.RaceDetected(
            f"exclusive rename destination appeared: {destination}") from exc
    source.unlink()


@pytest.fixture
def cow():
    module = _load_tool_module()
    if sys.platform != "darwin":
        module._rename_exclusive = (
            lambda source, destination: _portable_test_rename_exclusive(
                module, source, destination)
        )
    return module


def _copy_clone(source: Path, destination: Path) -> None:
    shutil.copyfile(source, destination)


def _allow_metadata(_path: Path, _snapshot) -> None:
    return None


def _duplicate_pair(root: Path, payload: bytes = b"same" * 4096):
    root = root.resolve()
    source = root / "a.png"
    target = root / "b.png"
    source.write_bytes(payload)
    target.write_bytes(payload)
    return root, source, target, payload


def _apply(cow, root: Path, *, clone_impl=_copy_clone, metadata_check=_allow_metadata):
    messages: list[str] = []
    summary = cow.dedupe_runs(
        root,
        apply=True,
        clone_impl=clone_impl,
        metadata_check=metadata_check,
        emit=messages.append,
    )
    return summary, messages


def test_default_dry_run_makes_no_changes(tmp_path, cow):
    root, source, target, _ = _duplicate_pair(tmp_path)
    source_inode = source.stat().st_ino
    target_inode = target.stat().st_ino
    called = False

    def forbidden_clone(_source, _destination):
        nonlocal called
        called = True
        raise AssertionError("dry-run must not clone")

    messages: list[str] = []
    summary = cow.dedupe_runs(
        root,
        clone_impl=forbidden_clone,
        metadata_check=_allow_metadata,
        emit=messages.append,
    )

    assert summary.would_clone == 1
    assert summary.cloned == 0
    assert not called
    assert source.stat().st_ino == source_inode
    assert target.stat().st_ino == target_inode
    assert not (root / cow.MANIFEST_NAME).exists()
    assert any(message.startswith("WOULD CLONE") for message in messages)


def test_run_assets_scope_only_discovers_immediate_run_asset_trees(
        tmp_path, cow):
    root = tmp_path.resolve()
    payload = b"scoped duplicate" * 4096
    run = root / "run-a"
    direct_assets = run / "assets"
    output_assets = run / "output" / "assets"
    direct_assets.mkdir(parents=True)
    output_assets.mkdir(parents=True)
    (direct_assets / "a.png").write_bytes(payload)
    (output_assets / "nested" / "b.png").parent.mkdir()
    (output_assets / "nested" / "b.png").write_bytes(payload)

    outside_paths = [
        root / "root.png",
        run / "input" / "assets" / "input.png",
        run / "nested" / "assets" / "nested.png",
        run / "output" / "other" / "assets" / "other.png",
    ]
    for path in outside_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    outside = root.parent / f"{root.name}-outside-assets"
    outside.mkdir()
    (outside / "linked.png").write_bytes(payload)
    (direct_assets / "linked").symlink_to(outside, target_is_directory=True)
    linked_run = root / "run-linked"
    linked_run.mkdir()
    (linked_run / "assets").symlink_to(outside, target_is_directory=True)

    summary = cow.dedupe_runs(
        root,
        scope=cow.SCOPE_RUN_ASSETS,
        metadata_check=_allow_metadata,
        emit=lambda _message: None,
    )

    assert summary.candidates == 2
    assert summary.would_clone == 1


def test_run_assets_scope_preserves_manifest_entries_outside_scope(
        tmp_path, cow):
    root, _source, _target, payload = _duplicate_pair(tmp_path)
    all_scope, _ = _apply(cow, root)
    assert all_scope.cloned == 1
    manifest_path = root / cow.MANIFEST_NAME
    outside_entry = json.loads(manifest_path.read_text())["entries"]["b.png"]

    assets = root / "run-a" / "assets"
    assets.mkdir(parents=True)
    (assets / "a.png").write_bytes(payload)
    (assets / "b.png").write_bytes(payload)
    scoped = cow.dedupe_runs(
        root,
        apply=True,
        scope=cow.SCOPE_RUN_ASSETS,
        clone_impl=_copy_clone,
        metadata_check=_allow_metadata,
        emit=lambda _message: None,
    )
    entries = json.loads(manifest_path.read_text())["entries"]

    assert scoped.cloned == 1
    assert entries["b.png"] == outside_entry
    assert "run-a/assets/b.png" in entries


@pytest.mark.parametrize("missing", ["target", "source"])
def test_scoped_apply_drops_out_of_scope_entry_with_missing_endpoint(
        tmp_path, cow, missing):
    root, source, target, _ = _duplicate_pair(tmp_path)
    all_scope, _ = _apply(cow, root)
    assert all_scope.cloned == 1
    manifest_path = root / cow.MANIFEST_NAME
    assert "b.png" in json.loads(manifest_path.read_text())["entries"]

    {"target": target, "source": source}[missing].unlink()
    scoped = cow.dedupe_runs(
        root,
        apply=True,
        scope=cow.SCOPE_RUN_ASSETS,
        clone_impl=_copy_clone,
        metadata_check=_allow_metadata,
        emit=lambda _message: None,
    )
    entries = json.loads(manifest_path.read_text())["entries"]

    assert scoped.errors == 0
    assert "b.png" not in entries


def test_scoped_apply_drops_traversal_and_symlink_manifest_targets(
        tmp_path, cow):
    root, _source, _target, _ = _duplicate_pair(tmp_path)
    all_scope, _ = _apply(cow, root)
    assert all_scope.cloned == 1
    manifest_path = root / cow.MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text())
    template = manifest["entries"]["b.png"]

    outside = root.parent / f"{root.name}-outside.png"
    outside.write_bytes(b"outside")
    (root / "linked.png").symlink_to(outside)
    manifest["entries"][f"../{outside.name}"] = dict(template)
    manifest["entries"]["linked.png"] = dict(template)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    cow.dedupe_runs(
        root,
        apply=True,
        scope=cow.SCOPE_RUN_ASSETS,
        clone_impl=_copy_clone,
        metadata_check=_allow_metadata,
        emit=lambda _message: None,
    )
    entries = json.loads(manifest_path.read_text())["entries"]

    assert "b.png" in entries
    assert f"../{outside.name}" not in entries
    assert "linked.png" not in entries


def test_default_scope_remains_equivalent_to_explicit_all(tmp_path, cow):
    root, _source, _target, _ = _duplicate_pair(tmp_path)

    default = cow.dedupe_runs(
        root,
        metadata_check=_allow_metadata,
        emit=lambda _message: None,
    )
    explicit = cow.dedupe_runs(
        root,
        scope=cow.SCOPE_ALL,
        metadata_check=_allow_metadata,
        emit=lambda _message: None,
    )
    run_assets = cow.dedupe_runs(
        root,
        scope=cow.SCOPE_RUN_ASSETS,
        metadata_check=_allow_metadata,
        emit=lambda _message: None,
    )

    assert default == explicit
    assert default.would_clone == 1
    assert run_assets.candidates == 0
    assert run_assets.would_clone == 0


def test_apply_preserves_target_metadata_and_files_remain_independent(tmp_path, cow):
    root, source, target, payload = _duplicate_pair(tmp_path)
    old_inode = target.stat().st_ino
    timestamp = 1_700_000_000_123_456_789
    os.chmod(target, 0o640)
    os.utime(target, ns=(timestamp, timestamp))

    summary, _ = _apply(cow, root)
    installed = target.stat()

    assert summary.cloned == 1
    assert installed.st_ino not in {old_inode, source.stat().st_ino}
    assert installed.st_mode & 0o777 == 0o640
    assert installed.st_atime_ns == timestamp
    assert installed.st_mtime_ns == timestamp
    assert target.read_bytes() == payload

    target.write_bytes(b"target changed independently")
    assert source.read_bytes() == payload


def test_second_apply_is_manifest_verified_and_byte_stable(tmp_path, cow):
    root, _source, target, _ = _duplicate_pair(tmp_path)
    first, _ = _apply(cow, root)
    manifest = root / cow.MANIFEST_NAME
    manifest_bytes = manifest.read_bytes()
    target_inode = target.stat().st_ino

    second, messages = _apply(cow, root)

    assert first.cloned == 1
    assert second.already == 1
    assert second.cloned == 0
    assert second.logical_reclaimable_upper_bytes == 0
    assert target.stat().st_ino == target_inode
    assert manifest.read_bytes() == manifest_bytes
    assert any(message.startswith("ALREADY") for message in messages)


def test_extension_filter_preserves_out_of_scope_manifest_entries(tmp_path, cow):
    root, _source, _target, _ = _duplicate_pair(tmp_path)
    first, _ = _apply(cow, root)
    assert first.cloned == 1
    manifest = root / cow.MANIFEST_NAME
    before = manifest.read_bytes()

    zip_only = cow.dedupe_runs(
        root,
        apply=True,
        extensions=frozenset({".zip"}),
        clone_impl=_copy_clone,
        metadata_check=_allow_metadata,
        emit=lambda _message: None,
    )
    assert zip_only.cloned == 0
    assert manifest.read_bytes() == before

    default_again, _ = _apply(cow, root)
    assert default_again.already == 1
    assert default_again.cloned == 0


def test_filter_preserves_entry_when_live_source_is_out_of_scope(tmp_path, cow):
    root = tmp_path.resolve()
    payload = b"cross-extension" * 4096
    (root / "a.png").write_bytes(payload)
    (root / "b.zip").write_bytes(payload)
    first, _ = _apply(cow, root)
    assert first.cloned == 1
    manifest_path = root / cow.MANIFEST_NAME
    before = manifest_path.read_bytes()
    manifest = json.loads(before)
    assert manifest["entries"]["b.zip"]["source"]["path"] == "a.png"

    zip_only = cow.dedupe_runs(
        root,
        apply=True,
        extensions=frozenset({".zip"}),
        clone_impl=_copy_clone,
        metadata_check=_allow_metadata,
        emit=lambda _message: None,
    )
    assert zip_only.cloned == 0
    assert manifest_path.read_bytes() == before

    default_again, _ = _apply(cow, root)
    assert default_again.already == 1


def test_new_earlier_duplicate_keeps_live_manifest_source_anchor(tmp_path, cow):
    root, source, target, payload = _duplicate_pair(tmp_path)
    first, _ = _apply(cow, root)
    assert first.cloned == 1
    source_inode = source.stat().st_ino
    target_inode = target.stat().st_ino
    earlier = root / "0.png"
    earlier.write_bytes(payload)

    second, _ = _apply(cow, root)
    manifest = json.loads((root / cow.MANIFEST_NAME).read_text())

    assert second.cloned == 1
    assert second.already == 1
    assert source.stat().st_ino == source_inode
    assert target.stat().st_ino == target_inode
    assert manifest["entries"]["0.png"]["source"]["path"] == "a.png"
    assert manifest["entries"]["b.png"]["source"]["path"] == "a.png"

    third, _ = _apply(cow, root)
    assert third.already == 2
    assert third.cloned == 0


def test_clone_failure_leaves_original_inode_and_content(tmp_path, cow):
    root, _source, target, payload = _duplicate_pair(tmp_path)
    original_inode = target.stat().st_ino

    def fail_clone(_source, _destination):
        raise cow.CloneUnavailable("simulated clone failure")

    summary, _ = _apply(cow, root, clone_impl=fail_clone)

    assert summary.errors == 1
    assert summary.cloned == 0
    assert target.stat().st_ino == original_inode
    assert target.read_bytes() == payload
    assert not list(root.glob(".*.cow-*.tmp"))


def test_race_before_backup_is_detected_without_overwrite(
        tmp_path, cow, monkeypatch):
    root, _source, target, _ = _duplicate_pair(tmp_path)
    real_rename = cow._rename_exclusive
    raced = False
    external_inode = None

    def race_then_rename(source, destination):
        nonlocal raced, external_inode
        if source == target and str(destination).endswith(".backup") and not raced:
            raced = True
            replacement = root / ".external-replacement"
            replacement.write_bytes(b"external writer won")
            os.replace(replacement, target)
            external_inode = target.stat().st_ino
        return real_rename(source, destination)

    monkeypatch.setattr(cow, "_rename_exclusive", race_then_rename)
    summary, _ = _apply(cow, root)

    assert summary.errors == 1
    assert summary.cloned == 0
    assert raced
    assert target.stat().st_ino == external_inode
    assert target.read_bytes() == b"external writer won"
    assert not list(root.glob(".*.cow-*.backup"))


def test_installed_validation_failure_restores_original(tmp_path, cow):
    root, _source, target, payload = _duplicate_pair(tmp_path)
    original_inode = target.stat().st_ino

    def reject_installed(path, snapshot):
        if path == target and snapshot.inode != original_inode:
            raise cow.UnsafeMetadata("simulated installed-path failure")

    summary, _ = _apply(cow, root, metadata_check=reject_installed)

    assert summary.errors == 1
    assert summary.cloned == 0
    assert target.stat().st_ino == original_inode
    assert target.read_bytes() == payload
    assert not list(root.glob(".*.cow-*.backup"))


def test_rollback_preserves_in_place_external_write_on_installed_inode(
        tmp_path, cow):
    root, _source, target, payload = _duplicate_pair(tmp_path)
    original_inode = target.stat().st_ino
    external_payload = b"E" * len(payload)
    mutated = False

    def mutate_installed_then_reject(path, snapshot):
        nonlocal mutated
        if path == target and snapshot.inode != original_inode and not mutated:
            mutated = True
            path.write_bytes(external_payload)
            raise cow.UnsafeMetadata("external write during installed validation")

    summary, _ = _apply(cow, root, metadata_check=mutate_installed_then_reject)

    assert summary.errors == 1
    assert summary.cloned == 0
    assert mutated
    # The externally modified installed inode is restored at the public path;
    # the pre-tool original remains recoverable at the transaction backup.
    assert target.read_bytes() == external_payload
    backups = list(root.glob(".*.cow-*.backup"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == payload


def test_manifest_rejects_target_rewrite_even_if_mtime_is_restored(tmp_path, cow):
    root, _source, target, payload = _duplicate_pair(tmp_path)
    first, _ = _apply(cow, root)
    assert first.cloned == 1
    manifest = json.loads((root / cow.MANIFEST_NAME).read_text())
    stored_ctime = manifest["entries"]["b.png"]["ctime_ns"]
    saved_mtime = target.stat().st_mtime_ns

    with target.open("r+b") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.utime(target, ns=(target.stat().st_atime_ns, saved_mtime))
    assert target.stat().st_ctime_ns != stored_ctime

    second, _ = _apply(cow, root)
    assert second.already == 0
    assert second.cloned == 1


def test_manifest_rejects_replaced_source_inode(tmp_path, cow):
    root, source, _target, payload = _duplicate_pair(tmp_path)
    first, _ = _apply(cow, root)
    assert first.cloned == 1
    old_inode = source.stat().st_ino
    source_stat = source.stat()
    replacement = root / ".replacement-source"
    replacement.write_bytes(payload)
    os.chmod(replacement, source_stat.st_mode & 0o777)
    os.utime(
        replacement,
        ns=(source_stat.st_atime_ns, source_stat.st_mtime_ns),
    )
    os.replace(replacement, source)
    assert source.stat().st_ino != old_inode

    second, _ = _apply(cow, root)
    assert second.already == 0
    assert second.cloned == 1


def test_symlink_files_and_directories_are_never_followed(tmp_path, cow):
    root = tmp_path.resolve()
    source = root / "a.png"
    source.write_bytes(b"same")
    (root / "b.png").symlink_to(source)
    outside = root.parent / f"{root.name}-outside"
    outside.mkdir()
    (outside / "c.png").write_bytes(b"same")
    (root / "linked-dir").symlink_to(outside, target_is_directory=True)

    summary = cow.dedupe_runs(
        root,
        metadata_check=_allow_metadata,
        emit=lambda _message: None,
    )

    assert summary.would_clone == 0
    assert (root / "b.png").is_symlink()
    assert summary.reasons["symlink-or-nonregular"] == 1


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS metadata APIs")
def test_production_metadata_check_skips_xattr_acl_and_hardlinks(tmp_path, cow):
    root = tmp_path.resolve()
    xattr_file = root / "xattr.png"
    xattr_file.write_bytes(b"x")
    subprocess.run(
        ["/usr/bin/xattr", "-w", "com.openai.cowtest", "value", str(xattr_file)],
        check=True,
    )
    assert "com.openai.cowtest" in cow._list_xattrs(xattr_file)
    with pytest.raises(cow.UnsafeMetadata, match="xattrs present"):
        cow._production_metadata_check(xattr_file, cow.Snapshot.read(xattr_file))

    acl_file = root / "acl.png"
    acl_file.write_bytes(b"a")
    subprocess.run(
        ["/bin/chmod", "+a", "everyone deny delete", str(acl_file)],
        check=True,
    )
    try:
        assert cow._has_extended_acl(acl_file)
        with pytest.raises(cow.UnsafeMetadata, match="extended ACL"):
            cow._production_metadata_check(acl_file, cow.Snapshot.read(acl_file))
    finally:
        subprocess.run(["/bin/chmod", "-N", str(acl_file)], check=True)

    hardlink_source = root / "hardlink-source.png"
    hardlink_source.write_bytes(b"h")
    hardlink = root / "hardlink.png"
    os.link(hardlink_source, hardlink)
    with pytest.raises(cow.UnsafeMetadata, match="hardlinked"):
        cow._production_metadata_check(
            hardlink_source, cow.Snapshot.read(hardlink_source))


@pytest.mark.skipif(sys.platform != "darwin", reason="APFS clonefile test")
def test_native_clonefile_creates_independent_inode(tmp_path, cow):
    root = tmp_path.resolve()
    source = root / "source.png"
    clone = root / "clone.png"
    payload = b"native clone" * 8192
    source.write_bytes(payload)

    try:
        cow._clonefile_cow(source, clone)
    except cow.CloneUnavailable as exc:
        pytest.skip(str(exc))

    assert clone.read_bytes() == payload
    assert clone.stat().st_ino != source.stat().st_ino
    clone.write_bytes(b"changed")
    assert source.read_bytes() == payload


def test_clonefile_uses_no_follow_flags_and_original_path(tmp_path, cow, monkeypatch):
    calls = []

    class FakeCall:
        argtypes = None
        restype = None

        def __call__(self, source, destination, flags):
            calls.append((source, destination, flags))
            return 0

    class FakeLibc:
        clonefile = FakeCall()

    source = tmp_path / "source.png"
    destination = tmp_path / "destination.png"
    source.write_bytes(b"x")
    # Exercise the Darwin adapter contract against a fake libc on every CI OS.
    monkeypatch.setattr(cow.sys, "platform", "darwin")
    monkeypatch.setattr(cow, "_LIBC", FakeLibc())
    cow._clonefile_cow(source, destination)

    assert calls[0][0] == os.fsencode(source)
    assert calls[0][1] == os.fsencode(destination)
    assert calls[0][2] == (
        cow.CLONE_NOFOLLOW | cow.CLONE_NOFOLLOW_ANY | cow.CLONE_ACL
    )
