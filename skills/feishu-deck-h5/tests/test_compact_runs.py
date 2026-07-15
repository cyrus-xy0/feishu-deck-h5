"""Focused contract tests for assets/compact-runs.py."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
TOOL = SKILL_ROOT / "assets" / "compact-runs.py"


def _load_tool_module():
    name = "_compact_runs_test_module"
    spec = importlib.util.spec_from_file_location(name, TOOL)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _invoke(runs: Path, canonical: Path, *, apply: bool = False) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(TOOL), str(runs), "--canonical", str(canonical)]
    if apply:
        cmd.append("--apply")
    return subprocess.run(cmd, capture_output=True, text=True)


def test_dry_run_then_apply_compacts_both_supported_locations_with_relative_links(tmp_path):
    canonical = tmp_path / "canonical"
    runs = tmp_path / "runs"
    _write(canonical / "pool" / "logo.png", b"same-logo")
    _write(canonical / "pool" / "avatar.png", b"same-avatar")
    source_shared = runs / "run-a" / "assets" / "shared"
    output_shared = runs / "run-b" / "output" / "assets" / "shared"
    _write(source_shared / "pool" / "logo.png", b"same-logo")
    _write(output_shared / "pool" / "avatar.png", b"same-avatar")

    dry = _invoke(runs, canonical)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert dry.stdout.count("WOULD LINK") == 2
    assert source_shared.is_dir() and not source_shared.is_symlink()
    assert output_shared.is_dir() and not output_shared.is_symlink()

    applied = _invoke(runs, canonical, apply=True)
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert applied.stdout.count("LINKED") == 2
    for shared in (source_shared, output_shared):
        assert shared.is_symlink()
        target = os.readlink(shared)
        assert not os.path.isabs(target), "run links must remain relocatable"
        assert shared.resolve() == canonical.resolve()


def test_conflict_or_missing_canonical_file_is_skipped_without_partial_changes(tmp_path):
    canonical = tmp_path / "canonical"
    runs = tmp_path / "runs"
    _write(canonical / "pool" / "logo.png", b"canonical")
    mismatch = runs / "mismatch" / "assets" / "shared"
    missing = runs / "missing" / "output" / "assets" / "shared"
    _write(mismatch / "pool" / "logo.png", b"different")
    _write(missing / "pool" / "unregistered.png", b"orphan")

    result = _invoke(runs, canonical, apply=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "content mismatch: pool/logo.png" in result.stdout
    assert "not in canonical pool: pool/unregistered.png" in result.stdout
    assert mismatch.is_dir() and not mismatch.is_symlink()
    assert missing.is_dir() and not missing.is_symlink()
    assert (mismatch / "pool" / "logo.png").read_bytes() == b"different"
    assert (missing / "pool" / "unregistered.png").read_bytes() == b"orphan"


def test_apply_is_idempotent_for_existing_canonical_relative_link(tmp_path):
    canonical = tmp_path / "canonical"
    runs = tmp_path / "runs"
    shared = runs / "run-a" / "assets" / "shared"
    _write(canonical / "pool" / "logo.png", b"same")
    _write(shared / "pool" / "logo.png", b"same")

    first = _invoke(runs, canonical, apply=True)
    assert first.returncode == 0, first.stdout + first.stderr
    first_target = os.readlink(shared)

    second = _invoke(runs, canonical, apply=True)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "ALREADY" in second.stdout
    assert "linked=0" in second.stdout
    assert os.readlink(shared) == first_target
    assert shared.resolve() == canonical.resolve()


def test_real_directory_with_canonical_file_link_remains_eligible(tmp_path):
    canonical = tmp_path / "canonical"
    runs = tmp_path / "runs"
    shared = runs / "run-a" / "assets" / "shared"
    _write(canonical / "pool" / "logo.png", b"same")
    _write(canonical / "pool" / "avatar.png", b"same-avatar")
    _write(shared / "pool" / "logo.png", b"same")
    linked_file = shared / "pool" / "avatar.png"
    linked_file.symlink_to(os.path.relpath(
        canonical / "pool" / "avatar.png", start=linked_file.parent))

    result = _invoke(runs, canonical, apply=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert shared.is_symlink()
    assert shared.resolve() == canonical.resolve()


def test_atomic_install_failure_restores_original_directory(tmp_path, monkeypatch):
    compact = _load_tool_module()
    canonical = tmp_path / "canonical"
    shared = tmp_path / "runs" / "run-a" / "assets" / "shared"
    _write(canonical / "pool" / "logo.png", b"same")
    _write(shared / "pool" / "logo.png", b"same")
    inspection = compact.inspect_shared_dir(shared, canonical)
    assert inspection.state == "eligible"

    real_replace = os.replace
    calls = 0

    def fail_link_install(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated link install failure")
        return real_replace(source, destination)

    monkeypatch.setattr(compact.os, "replace", fail_link_install)
    with pytest.raises(OSError, match="simulated link install failure"):
        compact._atomic_replace_with_relative_link(shared, canonical, inspection)

    assert shared.is_dir() and not shared.is_symlink()
    assert (shared / "pool" / "logo.png").read_bytes() == b"same"
    assert not list(shared.parent.glob(".shared.compact-*"))
