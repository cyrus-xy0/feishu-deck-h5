from __future__ import annotations

import contextlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


SKILL_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = SKILL_ROOT / "subskills" / "runtime-upgrader" / "upgrade.py"
SPEC = importlib.util.spec_from_file_location("runtime_upgrader", MODULE_PATH)
assert SPEC and SPEC.loader
UPGRADER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPGRADER)
COMMIT = "a" * 40


def raw_slide(key: str) -> dict[str, object]:
    return {
        "key": key,
        "layout": "raw",
        "screen_label": key,
        "data": {"html": f'<div class="stage"><h2>{key}</h2></div>'},
    }


def make_source(tmp_path: Path, *, slides: int = 3) -> tuple[Path, Path, Path]:
    repository = tmp_path / "repo"
    output = repository / "runs" / "source" / "output"
    output.mkdir(parents=True)
    deck = {
        "version": "1.0",
        "deck": {"title": "Source"},
        "slides": [raw_slide(f"p{index}") for index in range(1, slides + 1)],
    }
    deck_json = output / "deck.json"
    deck_json.write_text(json.dumps(deck), encoding="utf-8")
    (output / "index.html").write_text("<!doctype html><html></html>", encoding="utf-8")
    (output / "deck.zip").write_bytes(b"old delivery")
    assets = output / "assets"
    assets.mkdir()
    (assets / "feishu-deck.css").write_text("old css", encoding="utf-8")
    (assets / "feishu-deck.js").write_text("old js", encoding="utf-8")
    return repository, output.parent, deck_json


def make_target(tmp_path: Path) -> tuple[Path, Path]:
    checkout = tmp_path / "target"
    skill = checkout / "skills" / "feishu-deck-h5"
    for relative in UPGRADER.REQUIRED_TARGET_PATHS:
        target = skill / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# tool\n", encoding="utf-8")
    (skill / "runtime" / "runtime-migrations.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "migrations": [
                    {
                        "id": "lazy-frames-v1",
                        "required": True,
                        "operation": "deck-json-set",
                        "path": "deck.lazy_frames",
                        "value": True,
                        "when": {"min_active_slides": 2},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (skill / "runtime" / "runtime-files.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "required_package_paths": [
                    "assets/feishu-deck.css",
                    "assets/feishu-deck.js",
                ],
                "files": [
                    {
                        "source_path": "assets/feishu-deck.css",
                        "package_path": "assets/feishu-deck.css",
                    },
                    {
                        "source_path": "assets/feishu-deck.js",
                        "package_path": "assets/feishu-deck.js",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return checkout, skill


def install_fake_target(
    monkeypatch: pytest.MonkeyPatch,
    checkout: Path,
) -> None:
    @contextlib.contextmanager
    def fake_worktree(_repository: Path, commit: str):
        assert commit == COMMIT
        yield checkout

    monkeypatch.setattr(UPGRADER, "target_worktree", fake_worktree)
    monkeypatch.setattr(
        UPGRADER,
        "resolve_target_commit",
        lambda _repository, _explicit: COMMIT,
    )
    monkeypatch.setattr(UPGRADER, "check_source_drift", lambda *_args: None)


def fake_pipeline_command(
    args: list[str],
    *,
    cwd: Path | None = None,
    allowed: tuple[int, ...] = (0,),
) -> subprocess.CompletedProcess[str]:
    del cwd, allowed
    joined = " ".join(args)
    if "deck-cli.py" in joined and " set " in f" {joined} ":
        deck_path = Path(args[args.index("--no-backup") + 1])
        payload = json.loads(deck_path.read_text(encoding="utf-8"))
        payload["deck"]["lazy_frames"] = True
        deck_path.write_text(json.dumps(payload), encoding="utf-8")
    elif "render-deck.py" in joined:
        assert "--final" in args
        assert "--visual" in args
        assert args[args.index("--shared") + 1] == "copy"
        deck_path = Path(args[2])
        output = Path(args[3])
        deck = json.loads(deck_path.read_text(encoding="utf-8"))
        count = UPGRADER.active_slide_count(deck)
        eager = (
            '<div class="slide-frame"><div class="slide" '
            'data-slide-key="p1"></div></div>'
        )
        templates = "".join(
            f'<div class="slide-frame" data-fs-lazy-frame="" '
            f'data-slide-key="p{index}" data-layout="raw" '
            f'data-screen-label="p{index}"><template data-fs-lazy-slide>'
            f'<div class="slide" data-slide-key="p{index}"></div>'
            f"</template></div>"
            for index in range(2, count + 1)
        )
        (output / "index.html").write_text(
            f'<div class="deck" data-lazy-frames="">{eager}{templates}</div>',
            encoding="utf-8",
        )
        assets = output / "assets"
        assets.mkdir(exist_ok=True)
        (assets / "feishu-deck.css").write_text("new css", encoding="utf-8")
        (assets / "feishu-deck.js").write_text("new js", encoding="utf-8")
        (output / "assets-manifest.yaml").write_text(
            "framework:\n"
            "  - assets/feishu-deck.css\n"
            "  - assets/feishu-deck.js\n",
            encoding="utf-8",
        )
    elif "runtime-lock.py" in joined and "--output" in args:
        output_path = Path(args[args.index("--output") + 1])
        output_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "runtime_id": "sha256-" + "1" * 64,
                    "snapshot_id": "sha256-" + "2" * 64,
                    "deck_h5_commit": COMMIT,
                    "files": [
                        {"package_path": "assets/feishu-deck.css"},
                        {"package_path": "assets/feishu-deck.js"},
                    ],
                }
            ),
            encoding="utf-8",
        )
    return subprocess.CompletedProcess(args, 0, "", "")


def test_parser_has_one_runtime_mode_and_no_performance_or_publish_switch() -> None:
    parser = UPGRADER.build_parser()
    args = parser.parse_args(["--deck-json", "/tmp/deck.json"])
    assert args.to == "current"
    for forbidden in ("--enable-lazy-frames", "--publish", "--force", "--in-place"):
        with pytest.raises(SystemExit):
            parser.parse_args(["--deck-json", "/tmp/deck.json", forbidden])


def test_runtime_registry_automatically_plans_lazy_frames() -> None:
    migrations = UPGRADER.load_migrations(SKILL_ROOT)
    plan = UPGRADER.plan_migrations(
        {
            "deck": {"title": "test"},
            "slides": [raw_slide("one"), raw_slide("two")],
        },
        migrations,
    )
    assert plan == [
        {
            "id": "lazy-frames-v1",
            "path": "deck.lazy_frames",
            "required": True,
            "status": "pending",
        }
    ]


def test_upgrade_builds_ready_candidate_and_preserves_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, source_run, deck_json = make_source(tmp_path)
    checkout, _skill = make_target(tmp_path)
    install_fake_target(monkeypatch, checkout)
    monkeypatch.setattr(UPGRADER, "run_command", fake_pipeline_command)
    before = UPGRADER.tree_digest(source_run)
    candidate = repository / "runs" / "candidate-runtime-upgrade"

    result = UPGRADER.upgrade(
        deck_json,
        output_run=candidate,
        repository=repository,
    )

    assert result["status"] == "READY"
    assert result["ready_to_publish"] is True
    assert result["published"] is False
    assert result["performance"]["status"] == "unproven"
    assert result["migrations"][0]["status"] == "applied"
    upgraded = json.loads(
        (candidate / "output" / "deck.json").read_text(encoding="utf-8")
    )
    assert upgraded["deck"]["lazy_frames"] is True
    assert not (candidate / "output" / "deck.zip").exists()
    assert (candidate / "output" / "assets" / "feishu-deck.js").read_text() == "new js"
    assert json.loads((candidate / "RUNTIME-UPGRADE.json").read_text())[
        "status"
    ] == "READY"
    assert UPGRADER.tree_digest(source_run) == before


def test_stage_removes_shared_symlink_for_fresh_materialization(
    tmp_path: Path,
) -> None:
    repository, _source_run, deck_json = make_source(tmp_path)
    source_output = deck_json.parent
    canonical = tmp_path / "shared-pool"
    canonical.mkdir()
    shared = source_output / "assets" / "shared"
    shared.symlink_to(canonical, target_is_directory=True)
    candidate = repository / "runs" / "candidate"

    output = UPGRADER.stage_candidate(
        source_output,
        candidate,
        ["assets/feishu-deck.css", "assets/feishu-deck.js"],
    )

    assert not (output / "assets" / "shared").exists()
    assert not (output / "assets" / "shared").is_symlink()


def test_stage_refuses_runtime_path_below_symlink_parent(tmp_path: Path) -> None:
    repository, _source_run, deck_json = make_source(tmp_path)
    source_output = deck_json.parent
    external = tmp_path / "external-assets"
    external.mkdir()
    (external / "feishu-deck.js").write_text("external", encoding="utf-8")
    (source_output / "assets" / "feishu-deck.css").unlink()
    (source_output / "assets" / "feishu-deck.js").unlink()
    (source_output / "assets").rmdir()
    (source_output / "assets").symlink_to(external, target_is_directory=True)
    candidate = repository / "runs" / "candidate"

    with pytest.raises(UPGRADER.UpgradeError) as caught:
        UPGRADER.stage_candidate(
            source_output,
            candidate,
            ["assets/feishu-deck.js"],
        )

    assert caught.value.code == "RUP-ASSET-001"
    assert (external / "feishu-deck.js").read_text() == "external"


def test_dry_run_plans_without_creating_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, source_run, deck_json = make_source(tmp_path)
    checkout, _skill = make_target(tmp_path)
    install_fake_target(monkeypatch, checkout)
    monkeypatch.setattr(UPGRADER, "run_command", fake_pipeline_command)
    before = UPGRADER.tree_digest(source_run)

    result = UPGRADER.upgrade(deck_json, dry_run=True, repository=repository)

    assert result["status"] == "DRY_RUN"
    assert result["migrations"][0]["status"] == "pending"
    assert list((repository / "runs").iterdir()) == [source_run]
    assert UPGRADER.tree_digest(source_run) == before


def test_existing_candidate_is_refused_without_touching_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, source_run, deck_json = make_source(tmp_path)
    checkout, _skill = make_target(tmp_path)
    install_fake_target(monkeypatch, checkout)
    monkeypatch.setattr(UPGRADER, "run_command", fake_pipeline_command)
    candidate = repository / "runs" / "existing"
    candidate.mkdir()
    before = UPGRADER.tree_digest(source_run)

    with pytest.raises(UPGRADER.UpgradeError, match="candidate already exists"):
        UPGRADER.upgrade(
            deck_json,
            output_run=candidate,
            repository=repository,
        )

    assert UPGRADER.tree_digest(source_run) == before


def test_html_only_or_missing_sibling_is_blocked(tmp_path: Path) -> None:
    repository, _source_run, deck_json = make_source(tmp_path)
    (deck_json.parent / "index.html").unlink()
    with pytest.raises(UPGRADER.UpgradeError) as caught:
        UPGRADER.validate_source(deck_json, repository)
    assert caught.value.code == "RUP-SRC-002"


def test_drift_blocks_before_candidate_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, _source_run, deck_json = make_source(tmp_path)
    checkout, _skill = make_target(tmp_path)
    install_fake_target(monkeypatch, checkout)

    def drift(*_args: object) -> None:
        raise UPGRADER.UpgradeError("RUP-SRC-003", "unsynced")

    monkeypatch.setattr(UPGRADER, "check_source_drift", drift)
    with pytest.raises(UPGRADER.UpgradeError) as caught:
        UPGRADER.upgrade(deck_json, repository=repository)
    assert caught.value.code == "RUP-SRC-003"
    assert len(list((repository / "runs").iterdir())) == 1


def test_source_tools_receive_read_only_copies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deck = tmp_path / "source-deck.json"
    index = tmp_path / "source-index.html"
    deck.write_text(
        json.dumps({"deck": {"title": "t"}, "slides": [raw_slide("one")]}),
        encoding="utf-8",
    )
    index.write_text("<!doctype html>", encoding="utf-8")
    observed: list[Path] = []

    def observe(_skill: Path, index_copy: Path, deck_copy: Path) -> None:
        assert index_copy != index
        assert deck_copy != deck
        assert index_copy.is_file() and deck_copy.is_file()
        observed.extend([index_copy, deck_copy])

    monkeypatch.setattr(UPGRADER, "check_source_drift", observe)
    monkeypatch.setattr(UPGRADER, "run_command", fake_pipeline_command)
    UPGRADER.check_source_safely(tmp_path, index, deck)

    assert observed
    assert deck.read_text(encoding="utf-8").startswith("{")
    assert index.read_text(encoding="utf-8") == "<!doctype html>"


def test_target_without_toolchain_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, _source_run, deck_json = make_source(tmp_path)
    checkout = tmp_path / "empty-target"
    checkout.mkdir()
    install_fake_target(monkeypatch, checkout)
    with pytest.raises(UPGRADER.UpgradeError) as caught:
        UPGRADER.upgrade(deck_json, repository=repository)
    assert caught.value.code == "RUP-TGT-002"


def test_unregistered_deckjson_change_is_rejected() -> None:
    source = {
        "deck": {"title": "Original"},
        "slides": [raw_slide("one"), raw_slide("two")],
    }
    candidate = json.loads(json.dumps(source))
    candidate["deck"]["title"] = "Changed"
    migrations = UPGRADER.load_migrations(SKILL_ROOT)
    with pytest.raises(UPGRADER.UpgradeError) as caught:
        UPGRADER.validate_deck_conservation(source, candidate, migrations, [])
    assert caught.value.code == "RUP-MIG-002"


def test_pipeline_failure_writes_failed_not_ready_and_preserves_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, source_run, deck_json = make_source(tmp_path)
    checkout, _skill = make_target(tmp_path)
    install_fake_target(monkeypatch, checkout)
    candidate = repository / "runs" / "failed-runtime-upgrade"
    before = UPGRADER.tree_digest(source_run)

    def fail_render(
        args: list[str],
        *,
        cwd: Path | None = None,
        allowed: tuple[int, ...] = (0,),
    ) -> subprocess.CompletedProcess[str]:
        if any("render-deck.py" in item for item in args):
            raise UPGRADER.UpgradeError("RUP-BLD-001", "render failed")
        return fake_pipeline_command(args, cwd=cwd, allowed=allowed)

    monkeypatch.setattr(UPGRADER, "run_command", fail_render)
    with pytest.raises(UPGRADER.UpgradeError) as caught:
        UPGRADER.upgrade(
            deck_json,
            output_run=candidate,
            repository=repository,
        )

    assert caught.value.code == "RUP-BLD-001"
    report = json.loads((candidate / "RUNTIME-UPGRADE.json").read_text())
    assert report["status"] == "FAILED"
    assert report["ready_to_publish"] is False
    assert "READY" not in (candidate / "RUNTIME-UPGRADE.md").read_text()
    assert UPGRADER.tree_digest(source_run) == before


def test_late_source_drift_overwrites_ready_receipt_with_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, source_run, deck_json = make_source(tmp_path)
    checkout, _skill = make_target(tmp_path)
    install_fake_target(monkeypatch, checkout)
    monkeypatch.setattr(UPGRADER, "run_command", fake_pipeline_command)
    candidate = repository / "runs" / "late-drift-runtime-upgrade"
    stable = UPGRADER.tree_digest(source_run)
    calls = 0

    def changing_digest(_root: Path) -> str:
        nonlocal calls
        calls += 1
        return stable if calls <= 2 else "f" * 64

    monkeypatch.setattr(UPGRADER, "tree_digest", changing_digest)
    with pytest.raises(UPGRADER.UpgradeError) as caught:
        UPGRADER.upgrade(
            deck_json,
            output_run=candidate,
            repository=repository,
        )

    assert caught.value.code == "RUP-SRC-004"
    report = json.loads((candidate / "RUNTIME-UPGRADE.json").read_text())
    assert report["status"] == "FAILED"
    assert report["ready_to_publish"] is False
    assert report["source_invariant"] == "failed"
