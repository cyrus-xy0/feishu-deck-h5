from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
PPTX_ROOT = REPO / "skills" / "pptx-to-deck"
INSTALL = REPO / "install.sh"


def run_install(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "INSTALL_DIR": str(REPO),
            "CLAUDE_DIR": str(tmp_path / "harness"),
            "PREFLIGHT_PROFILE": "core",
        }
    )
    return subprocess.run(
        ["bash", str(INSTALL), "--link-only", *args],
        cwd=REPO,
        env=env,
        text=True,
        capture_output=True,
    )


def test_correct_symlink_is_idempotent(tmp_path: Path) -> None:
    main_link = tmp_path / "harness" / "skills" / "feishu-deck-h5"
    pptx_link = tmp_path / "harness" / "skills" / "pptx-to-deck"
    main_link.parent.mkdir(parents=True)
    main_link.symlink_to(ROOT)
    pptx_link.symlink_to(PPTX_ROOT)
    before = {link.name: os.lstat(link).st_ino for link in (main_link, pptx_link)}
    proc = run_install(tmp_path)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    for link, target in ((main_link, ROOT), (pptx_link, PPTX_ROOT)):
        assert link.is_symlink()
        assert link.resolve() == target.resolve()
        assert os.lstat(link).st_ino == before[link.name]


def test_fresh_install_links_only_active_skills(tmp_path: Path) -> None:
    proc = run_install(tmp_path)
    assert proc.returncode == 0, proc.stderr or proc.stdout
    skills = tmp_path / "harness" / "skills"
    assert (skills / "feishu-deck-h5").resolve() == ROOT.resolve()
    assert (skills / "pptx-to-deck").resolve() == PPTX_ROOT.resolve()
    assert not (skills / "keynote-to-html").exists()


def test_real_directory_is_refused_and_preserved(tmp_path: Path) -> None:
    link = tmp_path / "harness" / "skills" / "feishu-deck-h5"
    link.mkdir(parents=True)
    marker = link / "local-work.txt"
    marker.write_text("keep", encoding="utf-8")
    proc = run_install(tmp_path)
    assert proc.returncode == 3
    assert marker.read_text(encoding="utf-8") == "keep"
    assert not link.is_symlink()


def test_different_symlink_is_refused_and_preserved(tmp_path: Path) -> None:
    other = tmp_path / "other-skill"
    other.mkdir()
    link = tmp_path / "harness" / "skills" / "feishu-deck-h5"
    link.parent.mkdir(parents=True)
    link.symlink_to(other)
    proc = run_install(tmp_path)
    assert proc.returncode == 3
    assert link.is_symlink()
    assert link.resolve() == other.resolve()


def test_pptx_conflict_refuses_before_creating_main_link(tmp_path: Path) -> None:
    other = tmp_path / "other-skill"
    other.mkdir()
    skills = tmp_path / "harness" / "skills"
    skills.mkdir(parents=True)
    pptx_link = skills / "pptx-to-deck"
    pptx_link.symlink_to(other)
    proc = run_install(tmp_path)
    assert proc.returncode == 3
    assert not (skills / "feishu-deck-h5").exists()
    assert pptx_link.resolve() == other.resolve()


def test_force_requires_backup_and_preserves_old_directory(tmp_path: Path) -> None:
    link = tmp_path / "harness" / "skills" / "feishu-deck-h5"
    link.mkdir(parents=True)
    (link / "local-work.txt").write_text("keep", encoding="utf-8")
    refused = run_install(tmp_path, "--force")
    assert refused.returncode == 64
    proc = run_install(tmp_path, "--force", "--backup")
    assert proc.returncode == 0, proc.stderr or proc.stdout
    backups = list(link.parent.glob("feishu-deck-h5.backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "local-work.txt").read_text(encoding="utf-8") == "keep"
    assert link.is_symlink() and link.resolve() == ROOT.resolve()
