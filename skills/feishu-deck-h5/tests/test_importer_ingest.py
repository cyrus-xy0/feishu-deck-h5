import argparse
import importlib.util
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
