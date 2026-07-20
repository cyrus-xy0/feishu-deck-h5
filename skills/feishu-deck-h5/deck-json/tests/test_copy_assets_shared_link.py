import importlib.util
import os
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[2]


def load_copy_assets():
    module_path = SKILL_ROOT / "assets" / "copy-assets.py"
    spec = importlib.util.spec_from_file_location("copy_assets_shared_link", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_skill(tmp_path: Path) -> tuple[Path, Path]:
    skill_root = tmp_path / "repo" / "skills" / "feishu-deck-h5"
    canonical = skill_root / "assets" / "shared"
    canonical.mkdir(parents=True)
    (canonical / "logos").mkdir()
    (canonical / "logos" / "demo.png").write_bytes(b"canonical-logo")
    return skill_root, canonical


def test_shared_copy_is_atomically_replaced_with_relative_link(tmp_path: Path):
    copy_assets = load_copy_assets()
    skill_root, canonical = make_skill(tmp_path)
    local_assets = tmp_path / "repo" / "runs" / "demo" / "output" / "assets"
    local_shared = local_assets / "shared"
    (local_shared / "logos").mkdir(parents=True)
    (local_shared / "logos" / "demo.png").write_bytes(b"canonical-logo")

    result = copy_assets.ensure_shared_symlink(local_assets, skill_root)

    assert result == local_shared
    assert local_shared.is_symlink()
    assert not os.path.isabs(os.readlink(local_shared))
    assert local_shared.resolve() == canonical.resolve()
    assert not list(local_assets.glob(".shared.backup-*"))
    assert not list(local_assets.glob(".shared.link-*"))

    # Idempotence: a second pass preserves the same valid link.
    original_target = os.readlink(local_shared)
    copy_assets.ensure_shared_symlink(local_assets, skill_root)
    assert os.readlink(local_shared) == original_target


def test_divergent_shared_file_fails_closed_and_is_preserved(tmp_path: Path):
    copy_assets = load_copy_assets()
    skill_root, _canonical = make_skill(tmp_path)
    local_assets = tmp_path / "repo" / "runs" / "demo" / "output" / "assets"
    local_shared = local_assets / "shared"
    (local_shared / "logos").mkdir(parents=True)
    divergent = local_shared / "logos" / "demo.png"
    divergent.write_bytes(b"deck-specific-logo")

    with pytest.raises(SystemExit, match="files differ from the canonical shared pool"):
        copy_assets.ensure_shared_symlink(local_assets, skill_root)

    assert local_shared.is_dir()
    assert not local_shared.is_symlink()
    assert divergent.read_bytes() == b"deck-specific-logo"


def test_unknown_shared_file_fails_closed(tmp_path: Path):
    copy_assets = load_copy_assets()
    skill_root, _canonical = make_skill(tmp_path)
    local_assets = tmp_path / "repo" / "runs" / "demo" / "output" / "assets"
    local_shared = local_assets / "shared"
    local_shared.mkdir(parents=True)
    unknown = local_shared / "deck-only.png"
    unknown.write_bytes(b"not-in-canonical-pool")

    with pytest.raises(SystemExit, match="deck-only.png"):
        copy_assets.ensure_shared_symlink(local_assets, skill_root)

    assert unknown.is_file()


def test_same_size_different_runtime_bytes_are_not_treated_as_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    copy_assets = load_copy_assets()
    monkeypatch.delattr(copy_assets.hashlib, "file_digest", raising=False)
    current = tmp_path / "current.js"
    source = tmp_path / "source.js"
    current.write_bytes(b"runtime-a")
    source.write_bytes(b"runtime-b")

    assert current.stat().st_size == source.stat().st_size
    assert copy_assets._same_file_content(current, source) is False
