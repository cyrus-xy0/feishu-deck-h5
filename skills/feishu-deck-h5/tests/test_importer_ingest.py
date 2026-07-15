import argparse
import importlib.util
import json
from pathlib import Path


def load_importer():
    module_path = Path(__file__).resolve().parents[1] / "subskills/importer/ingest.py"
    spec = importlib.util.spec_from_file_location("importer_ingest", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_confirm_dry_run_does_not_report_viewer_sync_ok():
    importer = load_importer()
    args = argparse.Namespace(auto_merge=False, wait_viewer=False)
    context = importer.library_viewer_sync_context(
        {
            "ok": True,
            "dry_run": False,
            "deck_id": "demo",
            "pr": {
                "dry_run": True,
                "viewer_url": "https://example.invalid/viewer/",
            },
        },
        args,
    )

    assert context["ok"] is False
    assert context["dry_run"] is True
    assert "not published" in context["reason"]


def test_real_confirm_can_report_viewer_sync_ok():
    importer = load_importer()
    args = argparse.Namespace(auto_merge=False, wait_viewer=False)
    context = importer.library_viewer_sync_context(
        {
            "ok": True,
            "dry_run": False,
            "deck_id": "demo",
            "pr": {
                "dry_run": False,
                "viewer_url": "https://example.invalid/viewer/",
            },
        },
        args,
    )

    assert context["ok"] is True
    assert context["dry_run"] is False
    assert context["reason"] == ""


def successful_step(json_payload=None):
    return {
        "cmd": [],
        "ok": True,
        "returncode": 0,
        "stdout": json.dumps(json_payload) if json_payload is not None else "ok",
        "stderr": "",
        "json": json_payload,
    }


def test_prepare_canonical_run_builds_fresh_zip_with_shared_link(tmp_path, monkeypatch):
    importer = load_importer()
    runs = tmp_path / "runs"
    output = runs / "demo" / "output"
    output.mkdir(parents=True)
    html = output / "index.html"
    html.write_text("<html></html>", encoding="utf-8")
    (output / "assets-manifest.yaml").write_text(
        "shared: []\nframework: []\ndeck-local: []\n",
        encoding="utf-8",
    )
    calls = []

    monkeypatch.setattr(importer, "RUNS", runs)

    def fake_subprocess(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "bash":
            (output / "deck.zip").write_bytes(b"zip")
        return successful_step()

    monkeypatch.setattr(importer, "subprocess_record", fake_subprocess)
    prepared = importer.prepare_ingest_artifact(
        html_path=html,
        deck_id="demo",
        report_output_dir=output,
    )

    assert prepared["ok"] is True
    assert Path(prepared["artifact_path"]) == output / "deck.zip"
    assert calls[0][-1] == "--shared=link"
    assert calls[1][-2:] == ["--deck-id", "demo"]


def test_importer_quality_gate_is_resource_only(tmp_path, monkeypatch):
    importer = load_importer()
    output = tmp_path / "output"
    output.mkdir()
    html = output / "index.html"
    html.write_text("<html></html>", encoding="utf-8")
    calls = []

    def fake_subprocess(cmd, **kwargs):
        calls.append(cmd)
        return successful_step()

    monkeypatch.setattr(importer, "subprocess_record", fake_subprocess)
    args = argparse.Namespace(allow_unaudited=False)
    result = importer.ensure_quality_gate(html, output, args)

    assert result["ok"] is True
    assert "--resource-only" in calls[0]
    assert "--gate" not in calls[0]


def test_prepare_isolated_html_keeps_html_and_does_not_write(tmp_path, monkeypatch):
    importer = load_importer()
    html = tmp_path / "standalone.html"
    html.write_text("<html></html>", encoding="utf-8")

    def unexpected_subprocess(*args, **kwargs):
        raise AssertionError("isolated HTML must not run package preparation")

    monkeypatch.setattr(importer, "subprocess_record", unexpected_subprocess)
    prepared = importer.prepare_ingest_artifact(
        html_path=html,
        deck_id="standalone",
        report_output_dir=tmp_path,
    )

    assert prepared["ok"] is True
    assert Path(prepared["artifact_path"]) == html
    assert prepared["steps"] == []


def test_ingest_dry_run_does_not_prepare_or_execute(tmp_path, monkeypatch):
    importer = load_importer()
    html = tmp_path / "index.html"
    html.write_text("<html></html>", encoding="utf-8")
    args = argparse.Namespace(
        deck_id="demo",
        job_id="",
        slide_library_root=tmp_path / "library",
        slide_library_skill_dir=tmp_path / "skill",
        staging_root=None,
        dry_run=True,
    )

    def unexpected_prepare(**kwargs):
        raise AssertionError("dry-run must not mutate the run or build a package")

    monkeypatch.setattr(importer, "prepare_ingest_artifact", unexpected_prepare)
    result = importer.ingest_with_slide_library(
        html_path=html,
        output_dir=tmp_path,
        title="Demo",
        task_id="demo",
        args=args,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["steps"] == []


def test_real_run_ingest_passes_fresh_zip_to_ingest_package(tmp_path, monkeypatch):
    importer = load_importer()
    runs = tmp_path / "runs"
    output = runs / "demo" / "output"
    output.mkdir(parents=True)
    html = output / "index.html"
    html.write_text("<html></html>", encoding="utf-8")
    (output / "assets-manifest.yaml").write_text(
        "shared: []\nframework: []\ndeck-local: []\n",
        encoding="utf-8",
    )
    library = tmp_path / "library"
    skill = library / "skills" / "feishu-slide-library"
    assets = skill / "assets"
    assets.mkdir(parents=True)
    for name in ("bootstrap-library.py", "ingest-package.py", "confirm-ingest.py"):
        (assets / name).write_text("", encoding="utf-8")
    staging = tmp_path / "staging"
    ingest_commands = []

    monkeypatch.setattr(importer, "RUNS", runs)

    def fake_subprocess(cmd, **kwargs):
        if cmd[0] == "bash":
            (output / "deck.zip").write_bytes(b"zip")
        if len(cmd) > 1 and Path(cmd[1]).name == "ingest-package.py":
            ingest_commands.append(cmd)
            candidate = staging / "candidate"
            source = candidate / "decks" / "demo" / "source.html"
            source.parent.mkdir(parents=True)
            source.write_text("<html></html>", encoding="utf-8")
            result_path = staging / "ingest_result.json"
            payload = {
                "ready_for_confirm": True,
                "candidate_root": str(candidate),
                "ingest_result_path": str(result_path),
            }
            result_path.write_text(json.dumps(payload), encoding="utf-8")
            return successful_step(payload)
        return successful_step()

    monkeypatch.setattr(importer, "subprocess_record", fake_subprocess)
    args = argparse.Namespace(
        deck_id="demo",
        job_id="",
        slide_library_root=library,
        slide_library_skill_dir=skill,
        staging_root=staging,
        dry_run=False,
        slide_library_branch="main",
        slide_library_offline=True,
        submitted_by="tester",
        contributor="",
        submitted_by_id="",
        no_confirm_ingest=True,
        confirm_dry_run=False,
        auto_merge=False,
        wait_viewer=False,
    )

    result = importer.ingest_with_slide_library(
        html_path=html,
        output_dir=output,
        title="Demo",
        task_id="demo",
        args=args,
    )

    assert result["ok"] is True
    assert result["artifact_path"] == str(output / "deck.zip")
    assert ingest_commands[0][2] == str(output / "deck.zip")
    assert "--resource-checks-only" in ingest_commands[0]
    assert "--no-deck-h5-gate" in ingest_commands[0]


def write_candidate_fixture(tmp_path, *, source_html, package_bytes=b"shared"):
    candidate_root = tmp_path / "staging" / "candidate"
    source = candidate_root / "decks" / "demo" / "source.html"
    source.parent.mkdir(parents=True)
    source.write_text(source_html, encoding="utf-8")
    package_root = tmp_path / "package"
    shared = package_root / "assets" / "shared" / "logos" / "demo.png"
    shared.parent.mkdir(parents=True)
    shared.write_bytes(package_bytes)
    manifest = package_root / "assets-manifest.yaml"
    manifest.write_text(
        "shared:\n"
        "  - assets/shared/logos/demo.png\n"
        "framework:\n"
        "  - assets/feishu-deck.css\n"
        "deck-local: []\n",
        encoding="utf-8",
    )
    ingest_result = tmp_path / "staging" / "ingest_result.json"
    ingest_result.write_text(
        json.dumps({"candidate_root": str(candidate_root)}),
        encoding="utf-8",
    )
    return candidate_root, manifest, ingest_result


def test_verify_candidate_assets_accepts_central_shared_handoff(tmp_path):
    importer = load_importer()
    candidate_root, manifest, ingest_result = write_candidate_fixture(
        tmp_path,
        source_html=(
            '<link rel="stylesheet" href="../../assets/framework/feishu-deck.css">'
            '<img src="../../assets/shared/logos/demo.png">'
        ),
    )
    pool_file = candidate_root / "assets" / "shared" / "logos" / "demo.png"
    pool_file.parent.mkdir(parents=True)
    pool_file.write_bytes(b"shared")

    verified = importer.verify_candidate_assets(
        ingest_result_path=ingest_result,
        deck_id="demo",
        library_root=tmp_path / "library",
        asset_manifest_path=manifest,
    )

    assert verified["ok"] is True
    assert verified["stderr"] == ""


def test_verify_candidate_assets_scans_nested_runtime_files(tmp_path):
    importer = load_importer()
    candidate_root, manifest, ingest_result = write_candidate_fixture(
        tmp_path,
        source_html="<html></html>",
    )
    nested = candidate_root / "decks" / "demo" / "assets" / "prototype" / "view.html"
    nested.parent.mkdir(parents=True)
    nested.write_text(
        '<link rel="stylesheet" href="../../../../assets/framework/feishu-deck.css">'
        '<img src="../../../../assets/shared/logos/demo.png">',
        encoding="utf-8",
    )
    pool_file = tmp_path / "library" / "assets" / "shared" / "logos" / "demo.png"
    pool_file.parent.mkdir(parents=True)
    pool_file.write_bytes(b"shared")
    provenance = candidate_root / "decks" / "demo" / "source_package" / "stale.html"
    provenance.parent.mkdir(parents=True)
    provenance.write_text('<img src="assets/shared/logos/demo.png">', encoding="utf-8")

    verified = importer.verify_candidate_assets(
        ingest_result_path=ingest_result,
        deck_id="demo",
        library_root=tmp_path / "library",
        asset_manifest_path=manifest,
    )

    assert verified["ok"] is True
    assert verified["stderr"] == ""


def test_verify_candidate_assets_rejects_deck_local_or_unrewritten_shared(tmp_path):
    importer = load_importer()
    candidate_root, manifest, ingest_result = write_candidate_fixture(
        tmp_path,
        source_html=(
            '<link rel="stylesheet" href="./assets/feishu-deck.css">'
            '<img src="assets/shared/logos/demo.png">'
        ),
    )
    forbidden = candidate_root / "decks" / "demo" / "assets" / "shared"
    forbidden.mkdir(parents=True)
    (forbidden / "demo.png").write_bytes(b"shared")
    library_file = tmp_path / "library" / "assets" / "shared" / "logos" / "demo.png"
    library_file.parent.mkdir(parents=True)
    library_file.write_bytes(b"different")

    verified = importer.verify_candidate_assets(
        ingest_result_path=ingest_result,
        deck_id="demo",
        library_root=tmp_path / "library",
        asset_manifest_path=manifest,
    )

    assert verified["ok"] is False
    assert "forbidden deck-local shared pool" in verified["stderr"]
    assert "was not rewritten" in verified["stderr"]
    assert "hash differs" in verified["stderr"]
    assert "legacy local framework references" in verified["stderr"]
