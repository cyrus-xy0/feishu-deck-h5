from __future__ import annotations

import hashlib
import importlib.util
import json
import posixpath
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "assets" / "runtime-lock.py"
SPEC = importlib.util.spec_from_file_location("runtime_lock", MODULE_PATH)
assert SPEC and SPEC.loader
RUNTIME_LOCK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME_LOCK)


def _create_runtime_repo(
    tmp_path: Path,
) -> tuple[Path, Path, Path, str]:
    repo = tmp_path / "repo"
    skill = repo / "skill"
    (skill / "runtime").mkdir(parents=True)
    (skill / "assets").mkdir()
    runtime = skill / "assets" / "runtime.js"
    runtime.write_bytes(b"runtime-v1")
    (skill / "assets" / "alternate.js").write_bytes(b"runtime-v2")
    (skill / "runtime" / "runtime-files.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "files": [
                    {
                        "source_path": "assets/runtime.js",
                        "package_path": "assets/runtime.js",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Runtime Test",
            "-c",
            "user.email=runtime-test@example.com",
            "commit",
            "-qm",
            "runtime fixture",
        ],
        check=True,
    )
    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo, skill, runtime, commit


def _create_staged_runtime_skill(
    tmp_path: Path,
) -> tuple[Path, Path, Path, dict[str, object]]:
    _, skill, _, _ = _create_runtime_repo(tmp_path)
    staged = tmp_path / "staged-skill"
    shutil.copytree(skill, staged)
    sidecar = staged / RUNTIME_LOCK.RUNTIME_PROVENANCE
    provenance = RUNTIME_LOCK.build_runtime_provenance(skill)
    RUNTIME_LOCK.write_runtime_provenance(sidecar, provenance)
    return skill, staged, staged / "assets" / "runtime.js", provenance


@pytest.mark.parametrize(
    "source_path,package_path",
    [
        ("../assets/runtime.js", "assets/runtime.js"),
        ("assets/runtime.js", "/assets/runtime.js"),
        ("assets\\runtime.js", "assets/runtime.js"),
        ("assets/runtime.js", "C:/runtime.js"),
        ("assets//runtime.js", "assets/runtime.js"),
        (1, "assets/runtime.js"),
    ],
)
def test_runtime_manifest_rejects_unsafe_or_non_string_paths(
    tmp_path: Path,
    source_path: object,
    package_path: object,
) -> None:
    skill = tmp_path / "skill"
    (skill / "runtime").mkdir(parents=True)
    (skill / "runtime" / "runtime-files.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "files": [
                    {
                        "source_path": source_path,
                        "package_path": package_path,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        RUNTIME_LOCK.read_runtime_manifest(skill)


def test_runtime_manifest_covers_local_css_dependencies() -> None:
    files = RUNTIME_LOCK.read_runtime_manifest(SKILL_ROOT)
    sources = {item["source_path"] for item in files}
    for item in files:
        source_path = item["source_path"]
        if not source_path.endswith(".css"):
            continue
        css = (SKILL_ROOT / source_path).read_text(encoding="utf-8")
        for match in re.finditer(r"url\(\s*['\"]?([^'\"\)]+)", css):
            reference = match.group(1).strip()
            if (
                not reference
                or reference.startswith(("data:", "http:", "https:", "#", "%"))
                or reference == "..."
            ):
                continue
            dependency = posixpath.normpath(
                posixpath.join(posixpath.dirname(source_path), reference)
            )
            assert dependency in sources, (
                f"{source_path} references runtime dependency {dependency}, "
                "but runtime/runtime-files.json does not include it"
            )


def test_runtime_sync_dispatch_watches_the_full_runtime_manifest() -> None:
    workflow = (
        SKILL_ROOT.parents[1]
        / ".github"
        / "workflows"
        / "dispatch-slide-library-runtime-sync.yml"
    ).read_text(encoding="utf-8")
    for item in RUNTIME_LOCK.read_runtime_manifest(SKILL_ROOT):
        expected = f"- skills/feishu-deck-h5/{item['source_path']}"
        assert expected in workflow
    assert "- skills/feishu-deck-h5/runtime/runtime-files.json" in workflow
    assert "fetch-depth: 0" in workflow
    assert "assets/runtime-lock.py" in workflow
    assert "--print-commit" in workflow
    assert "git rev-parse HEAD" not in workflow
    assert '"deck_h5_ref": os.environ["SOURCE_COMMIT"]' in workflow
    assert '"source_sha": os.environ["SOURCE_COMMIT"]' in workflow
    assert "if: env.SLIDE_LIBRARY_SYNC_TOKEN != ''" in workflow
    assert "if: env.SLIDE_LIBRARY_SYNC_TOKEN == ''" in workflow
    assert "::error::Missing SLIDE_LIBRARY_SYNC_TOKEN" not in workflow


def test_runtime_manifest_must_match_the_trusted_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    skill = repo / "skill"
    (skill / "runtime").mkdir(parents=True)
    (skill / "assets").mkdir()
    runtime = skill / "assets" / "runtime.js"
    runtime.write_text("runtime-v1", encoding="utf-8")
    manifest = skill / "runtime" / "runtime-files.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "files": [
                    {
                        "source_path": "assets/runtime.js",
                        "package_path": "assets/runtime.js",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Runtime Test",
            "-c",
            "user.email=runtime-test@example.com",
            "commit",
            "-qm",
            "runtime fixture",
        ],
        check=True,
    )
    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            '"package_path": "assets/runtime.js"',
            '"package_path": "assets/renamed-runtime.js"',
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="runtime manifest differs from trusted commit"):
        RUNTIME_LOCK.build_runtime_lock(skill, deck_h5_commit=commit)


def test_runtime_lock_rejects_tree_object_as_commit(tmp_path: Path) -> None:
    repo, skill, _, _ = _create_runtime_repo(tmp_path)
    tree = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    with pytest.raises(ValueError, match="Git object is not a commit"):
        RUNTIME_LOCK.build_runtime_lock(skill, deck_h5_commit=tree)


def test_default_provenance_ignores_unrelated_later_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("FEISHU_DECK_H5_COMMIT", raising=False)
    repo, skill, _, runtime_commit = _create_runtime_repo(tmp_path)
    before = RUNTIME_LOCK.build_runtime_lock(skill)
    (repo / "unrelated.txt").write_text("not runtime\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "unrelated.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Runtime Test",
            "-c",
            "user.email=runtime-test@example.com",
            "commit",
            "-qm",
            "unrelated change",
        ],
        check=True,
    )
    assert subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() != runtime_commit

    lock = RUNTIME_LOCK.build_runtime_lock(skill)

    assert lock["deck_h5_commit"] == runtime_commit
    assert lock["snapshot_id"] == before["snapshot_id"]
    assert (
        RUNTIME_LOCK.main(
            ["--skill-root", str(skill), "--print-commit"]
        )
        == 0
    )
    assert capsys.readouterr().out.strip() == runtime_commit


def test_runtime_lock_rejects_dirty_runtime_symlink(tmp_path: Path) -> None:
    _, skill, runtime, commit = _create_runtime_repo(tmp_path)
    runtime.unlink()
    runtime.symlink_to("alternate.js")

    with pytest.raises(ValueError, match="working tree path contains a symlink"):
        RUNTIME_LOCK.build_runtime_lock(skill, deck_h5_commit=commit)


def test_runtime_lock_rejects_committed_runtime_symlink(tmp_path: Path) -> None:
    repo, skill, runtime, _ = _create_runtime_repo(tmp_path)
    runtime.unlink()
    runtime.symlink_to("alternate.js")
    subprocess.run(["git", "-C", str(repo), "add", "skill/assets/runtime.js"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Runtime Test",
            "-c",
            "user.email=runtime-test@example.com",
            "commit",
            "-qm",
            "symlink runtime",
        ],
        check=True,
    )
    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    with pytest.raises(ValueError, match="not a regular Git blob"):
        RUNTIME_LOCK.build_runtime_lock(skill, deck_h5_commit=commit)


def test_staged_no_git_skill_uses_packaged_runtime_provenance(
    tmp_path: Path,
) -> None:
    skill, staged, _, provenance = _create_staged_runtime_skill(tmp_path)

    assert RUNTIME_LOCK._git_repository_root(staged) is None
    assert RUNTIME_LOCK.build_runtime_lock(staged) == RUNTIME_LOCK.build_runtime_lock(
        skill
    )
    assert RUNTIME_LOCK.build_runtime_lock(staged)["snapshot_id"] == provenance[
        "snapshot_id"
    ]
    with pytest.raises(
        ValueError,
        match="requested deck_h5_commit differs from packaged runtime provenance",
    ):
        RUNTIME_LOCK.build_runtime_lock(
            staged,
            deck_h5_commit="f" * 40,
        )


def test_untracked_staged_skill_inside_another_git_worktree_uses_sidecar(
    tmp_path: Path,
) -> None:
    repo, skill, _, _ = _create_runtime_repo(tmp_path)
    staged = repo / "dist" / "feishu-deck-h5"
    shutil.copytree(skill, staged)
    RUNTIME_LOCK.write_runtime_provenance(
        staged / RUNTIME_LOCK.RUNTIME_PROVENANCE,
        RUNTIME_LOCK.build_runtime_provenance(skill),
    )

    assert RUNTIME_LOCK._git_repository_root(staged) == repo.resolve()
    assert RUNTIME_LOCK.build_runtime_lock(staged) == RUNTIME_LOCK.build_runtime_lock(
        skill
    )


def test_tracked_vendor_checkout_preserves_official_sidecar_provenance(
    tmp_path: Path,
) -> None:
    _, skill, _, official_commit = _create_runtime_repo(tmp_path)
    vendor = tmp_path / "vendor"
    staged = vendor / "skills" / "feishu-deck-h5"
    shutil.copytree(skill, staged)
    RUNTIME_LOCK.write_runtime_provenance(
        staged / RUNTIME_LOCK.RUNTIME_PROVENANCE,
        RUNTIME_LOCK.build_runtime_provenance(skill),
    )
    subprocess.run(["git", "init", "-q", str(vendor)], check=True)
    subprocess.run(["git", "-C", str(vendor), "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(vendor),
            "-c",
            "user.name=Runtime Vendor",
            "-c",
            "user.email=runtime-vendor@example.com",
            "commit",
            "-qm",
            "vendor packaged skill",
        ],
        check=True,
    )
    vendor_commit = subprocess.run(
        ["git", "-C", str(vendor), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert vendor_commit != official_commit
    assert RUNTIME_LOCK.build_runtime_lock(staged)["deck_h5_commit"] == official_commit


def test_source_checkout_with_sidecar_still_rejects_dirty_runtime(
    tmp_path: Path,
) -> None:
    _, skill, runtime, _ = _create_runtime_repo(tmp_path)
    RUNTIME_LOCK.write_runtime_provenance(
        skill / RUNTIME_LOCK.RUNTIME_PROVENANCE,
        RUNTIME_LOCK.build_runtime_provenance(skill),
    )
    runtime.write_bytes(b"runtime-tampered")

    with pytest.raises(
        ValueError,
        match="runtime source differs from trusted commit",
    ):
        RUNTIME_LOCK.build_runtime_lock(skill)
    with pytest.raises(
        ValueError,
        match="runtime source differs from trusted commit",
    ):
        RUNTIME_LOCK.build_runtime_provenance(skill)


@pytest.mark.parametrize("tamper_target", ["runtime", "manifest", "sidecar"])
def test_staged_no_git_skill_rejects_runtime_provenance_tampering(
    tmp_path: Path,
    tamper_target: str,
) -> None:
    _, staged, runtime, _ = _create_staged_runtime_skill(tmp_path)
    if tamper_target == "runtime":
        runtime.write_bytes(b"runtime-tampered")
        expected = "runtime source differs from packaged runtime provenance"
    elif tamper_target == "manifest":
        manifest = staged / RUNTIME_LOCK.RUNTIME_MANIFEST
        manifest.write_bytes(manifest.read_bytes() + b"\n")
        expected = "runtime manifest differs from packaged runtime provenance"
    else:
        sidecar = staged / RUNTIME_LOCK.RUNTIME_PROVENANCE
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        payload["snapshot_id"] = "sha256-" + ("0" * 64)
        sidecar.write_text(json.dumps(payload), encoding="utf-8")
        expected = "runtime provenance snapshot checksum mismatch"

    with pytest.raises(ValueError, match=expected):
        RUNTIME_LOCK.build_runtime_lock(staged)


@pytest.mark.parametrize("failure_mode", ["missing", "symlink"])
def test_staged_no_git_skill_rejects_non_regular_runtime_files(
    tmp_path: Path,
    failure_mode: str,
) -> None:
    _, staged, runtime, _ = _create_staged_runtime_skill(tmp_path)
    runtime.unlink()
    if failure_mode == "symlink":
        runtime.symlink_to("alternate.js")
        expected = "runtime source working tree path contains a symlink"
    else:
        expected = "runtime source is missing from working tree"

    with pytest.raises(ValueError, match=expected):
        RUNTIME_LOCK.build_runtime_lock(staged)


@pytest.mark.parametrize(
    "relative_path,label",
    [
        (RUNTIME_LOCK.RUNTIME_MANIFEST, "runtime manifest"),
        (RUNTIME_LOCK.RUNTIME_PROVENANCE, "runtime provenance"),
    ],
)
@pytest.mark.parametrize("failure_mode", ["missing", "symlink"])
def test_staged_no_git_skill_rejects_non_regular_metadata_files(
    tmp_path: Path,
    relative_path: Path,
    label: str,
    failure_mode: str,
) -> None:
    _, staged, _, _ = _create_staged_runtime_skill(tmp_path)
    path = staged / relative_path
    if failure_mode == "symlink":
        target = path.with_name(path.name + ".regular")
        path.rename(target)
        path.symlink_to(target.name)
        expected = f"{label} working tree path contains a symlink"
    else:
        path.unlink()
        expected = (
            "deck_h5_commit is unavailable"
            if relative_path == RUNTIME_LOCK.RUNTIME_PROVENANCE
            else f"{label} is missing from working tree"
        )

    with pytest.raises(ValueError, match=expected):
        RUNTIME_LOCK.build_runtime_lock(staged)


def test_runtime_lock_uses_verified_commit_bytes_after_source_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, skill, runtime, commit = _create_runtime_repo(tmp_path)
    output = tmp_path / "output"
    packaged = output / "assets" / "runtime.js"
    packaged.parent.mkdir(parents=True)
    packaged.write_bytes(b"runtime-v1")
    (output / "assets-manifest.yaml").write_text(
        "framework:\n  - assets/runtime.js\n",
        encoding="utf-8",
    )
    original_verify = RUNTIME_LOCK.verify_runtime_sources_at_commit

    def verify_then_change_source(
        skill_root: Path,
        files: list[dict[str, str]],
        trusted_commit: str,
    ) -> dict[str, bytes]:
        trusted = original_verify(skill_root, files, trusted_commit)
        runtime.write_bytes(b"runtime-v2")
        return trusted

    monkeypatch.setattr(
        RUNTIME_LOCK,
        "verify_runtime_sources_at_commit",
        verify_then_change_source,
    )

    lock = RUNTIME_LOCK.build_runtime_lock(
        skill,
        deck_h5_commit=commit,
        output_dir=output,
    )

    assert lock["files"] == [
        {
            "source_path": "assets/runtime.js",
            "package_path": "assets/runtime.js",
            "sha256": hashlib.sha256(b"runtime-v1").hexdigest(),
            "size": len(b"runtime-v1"),
        }
    ]


def test_runtime_id_changes_only_when_controlled_runtime_changes(tmp_path: Path) -> None:
    skill = tmp_path / "skill"
    (skill / "runtime").mkdir(parents=True)
    (skill / "assets").mkdir()
    (skill / "docs").mkdir()
    (skill / "runtime" / "runtime-files.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "files": [
                    {
                        "source_path": "assets/runtime.js",
                        "package_path": "assets/runtime.js",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    runtime = skill / "assets" / "runtime.js"
    runtime.write_text("runtime-v1", encoding="utf-8")
    files = RUNTIME_LOCK.read_runtime_manifest(skill)
    assert files == [
        {"source_path": "assets/runtime.js", "package_path": "assets/runtime.js"}
    ]
    first_id = RUNTIME_LOCK.sha256_file(runtime)
    (skill / "docs" / "notes.md").write_text("non-runtime change", encoding="utf-8")
    assert RUNTIME_LOCK.sha256_file(runtime) == first_id
    runtime.write_text("runtime-v2", encoding="utf-8")
    assert RUNTIME_LOCK.sha256_file(runtime) != first_id


def test_runtime_provenance_is_not_part_of_the_runtime_snapshot(
    tmp_path: Path,
) -> None:
    _, skill, _, _ = _create_runtime_repo(tmp_path)
    first = RUNTIME_LOCK.build_runtime_provenance(skill)
    sidecar = skill / RUNTIME_LOCK.RUNTIME_PROVENANCE
    RUNTIME_LOCK.write_runtime_provenance(sidecar, first)
    sidecar.write_bytes(sidecar.read_bytes() + b"\n")

    second = RUNTIME_LOCK.build_runtime_provenance(skill)

    assert second["snapshot_id"] == first["snapshot_id"]
    assert second["files"] == first["files"]


def test_distribution_packagers_emit_the_same_runtime_provenance_sidecar() -> None:
    repository = SKILL_ROOT.parents[1]
    for script in (
        repository / "package-skill.sh",
        SKILL_ROOT / "assets" / "package-skill.sh",
    ):
        text = script.read_text(encoding="utf-8")
        assert "assets/runtime-lock.py" in text
        assert "--provenance-output" in text
        assert "--print-commit" in text
        assert "runtime/runtime-provenance.json" in text


def test_runtime_lock_is_deterministic_and_uses_full_hashes() -> None:
    first = RUNTIME_LOCK.build_runtime_lock(SKILL_ROOT)
    second = RUNTIME_LOCK.build_runtime_lock(SKILL_ROOT)
    assert first == second
    assert first["runtime_id"].startswith("sha256-")
    assert len(first["runtime_id"]) == len("sha256-") + 64
    assert first["snapshot_id"].startswith("sha256-")
    assert all(len(item["sha256"]) == 64 for item in first["files"])


def test_runtime_lock_uses_only_output_runtime_subset(tmp_path: Path) -> None:
    output = tmp_path / "output"
    target = output / "assets" / "feishu-deck.css"
    target.parent.mkdir(parents=True)
    shutil.copy2(SKILL_ROOT / "assets" / "feishu-deck.css", target)
    (output / "assets-manifest.yaml").write_text(
        "framework:\n  - assets/feishu-deck.css\n",
        encoding="utf-8",
    )

    lock = RUNTIME_LOCK.build_runtime_lock(SKILL_ROOT, output_dir=output)

    assert [item["package_path"] for item in lock["files"]] == [
        "assets/feishu-deck.css"
    ]
    assert lock["runtime_id"] != lock["snapshot_id"]


def test_copy_assets_preserves_controlled_extra_layout_runtime_bytes(
    tmp_path: Path,
) -> None:
    output = tmp_path / "runs" / "runtime-copy" / "output"
    output.mkdir(parents=True)
    (output / "index.html").write_text(
        "<!doctype html><html><head>"
        '<link rel="stylesheet" href="../../../skills/feishu-deck-h5/'
        'deck-json/templates/extra-layouts.css">'
        "</head><body></body></html>",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [
            sys.executable,
            str(SKILL_ROOT / "assets" / "copy-assets.py"),
            str(output),
            "--shared=copy",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    packaged = output / "assets" / "deck-json" / "templates" / "extra-layouts.css"
    assert packaged.read_bytes() == (
        SKILL_ROOT / "deck-json" / "templates" / "extra-layouts.css"
    ).read_bytes()
    lock = RUNTIME_LOCK.build_runtime_lock(SKILL_ROOT, output_dir=output)
    assert "assets/deck-json/templates/extra-layouts.css" in {
        item["package_path"] for item in lock["files"]
    }


def test_runtime_lock_rejects_same_size_stale_output_runtime(tmp_path: Path) -> None:
    output = tmp_path / "output"
    target = output / "assets" / "feishu-deck.css"
    target.parent.mkdir(parents=True)
    source = (SKILL_ROOT / "assets" / "feishu-deck.css").read_bytes()
    target.write_bytes(bytes([source[0] ^ 1]) + source[1:])
    (output / "assets-manifest.yaml").write_text(
        "framework:\n  - assets/feishu-deck.css\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="packaged runtime differs from trusted skill source",
    ):
        RUNTIME_LOCK.build_runtime_lock(SKILL_ROOT, output_dir=output)


def test_runtime_lock_rejects_uncontrolled_executable_framework_file(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    target = output / "assets" / "custom-runtime.js"
    target.parent.mkdir(parents=True)
    target.write_text("window.customRuntime = true;", encoding="utf-8")
    (output / "assets-manifest.yaml").write_text(
        "framework:\n  - assets/custom-runtime.js\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="uncontrolled executable framework"):
        RUNTIME_LOCK.build_runtime_lock(SKILL_ROOT, output_dir=output)
