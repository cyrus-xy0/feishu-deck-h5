"""Cross-deck paste keeps asset identity by content, never by mtime."""

import json
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
CLI = HERE.parent / "deck-cli.py"


def _load_cli_module():
    spec = importlib.util.spec_from_file_location("_deck_cli_asset_identity", CLI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _deck(title: str, slides: list[dict]) -> dict:
    return {
        "version": "1.0",
        "deck": {"title": title, "author": "test", "date": "2026-07-10"},
        "slides": slides,
    }


def _source_slide() -> dict:
    return {
        "key": "incoming",
        "layout": "raw",
        "custom_css": (
            ".hero{background-image:url('assets/shared/pool/logo.png')}"
        ),
        "data": {
            "html": (
                '<img src="input/logo.png">'
                '<iframe src="prototypes/demo/index.html"></iframe>'
                '<img src="media/local.png">'
            ),
        },
    }


def _run_paste(dst: Path, src: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), str(dst / "deck.json"), "--yes", "paste",
         "--from", str(src / "deck.json"), "--key", "incoming"],
        capture_output=True,
        text=True,
    )


def _prepare_source(root: Path, payload_prefix: bytes = b"SRC") -> None:
    _write(root / "input" / "logo.png", payload_prefix + b"-input")
    _write(root / "assets" / "shared" / "pool" / "logo.png",
           payload_prefix + b"-shared")
    _write(root / "media" / "local.png", payload_prefix + b"-local")
    _write(root / "prototypes" / "demo" / "index.html",
           payload_prefix + b"-prototype-html")
    _write(root / "prototypes" / "demo" / "app.js",
           payload_prefix + b"-prototype-js")
    (root / "deck.json").write_text(
        json.dumps(_deck("source", [_source_slide()]), ensure_ascii=False),
        encoding="utf-8",
    )


def test_different_same_path_assets_are_hash_isolated_and_only_pasted_slide_rewritten(
        tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _prepare_source(src)

    _write(dst / "input" / "logo.png", b"DEST-input")
    _write(dst / "assets" / "shared" / "pool" / "logo.png", b"DEST-shared")
    _write(dst / "media" / "local.png", b"DEST-local")
    _write(dst / "prototypes" / "demo" / "index.html", b"DEST-prototype-html")
    _write(dst / "prototypes" / "demo" / "app.js", b"DEST-prototype-js")
    keep = {
        "key": "keep",
        "layout": "raw",
        "custom_css": ".x{background:url('assets/shared/pool/logo.png')}",
        "data": {"html": (
            '<img src="input/logo.png"><iframe '
            'src="prototypes/demo/index.html"></iframe>'
            '<img src="media/local.png">')},
    }
    (dst / "deck.json").write_text(
        json.dumps(_deck("destination", [keep]), ensure_ascii=False),
        encoding="utf-8",
    )

    # Make every source newer than the destination. Old mtime-based behavior
    # overwrote the destination files in this exact situation.
    newer = 2_000_000_000
    for path in src.rglob("*"):
        if path.is_file():
            os.utime(path, (newer, newer))

    proc = _run_paste(dst, src)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    landed = json.loads((dst / "deck.json").read_text(encoding="utf-8"))
    assert landed["slides"][0] == keep, "existing destination slide was rewritten"
    pasted = next(s for s in landed["slides"] if s["key"] == "incoming")
    blob = pasted["custom_css"] + json.dumps(pasted["data"], ensure_ascii=False)

    input_ref = re.search(r"input/logo-[0-9a-f]{12}\.png", blob).group(0)
    shared_ref = re.search(
        r"assets/shared/pool/logo-[0-9a-f]{12}\.png", blob).group(0)
    local_ref = re.search(r"media/local-[0-9a-f]{12}\.png", blob).group(0)
    prototype_root = re.search(r"prototypes/demo-[0-9a-f]{12}", blob).group(0)

    assert (dst / "input" / "logo.png").read_bytes() == b"DEST-input"
    assert (dst / "assets" / "shared" / "pool" / "logo.png").read_bytes() == b"DEST-shared"
    assert (dst / "media" / "local.png").read_bytes() == b"DEST-local"
    assert (dst / "prototypes" / "demo" / "index.html").read_bytes() == b"DEST-prototype-html"

    assert (dst / input_ref).read_bytes() == b"SRC-input"
    assert (dst / shared_ref).read_bytes() == b"SRC-shared"
    assert (dst / local_ref).read_bytes() == b"SRC-local"
    assert (dst / prototype_root / "index.html").read_bytes() == b"SRC-prototype-html"
    assert (dst / prototype_root / "app.js").read_bytes() == b"SRC-prototype-js"

    # Repeating the paste reuses the deterministic hash destinations.
    proc2 = _run_paste(dst, src)
    assert proc2.returncode == 0, proc2.stdout + proc2.stderr
    assert len(list((dst / "input").glob("logo-*.png"))) == 1
    assert len(list((dst / "prototypes").glob("demo-*"))) == 1


def test_same_content_dedupes_at_original_paths_despite_mtime_difference(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    _prepare_source(src, payload_prefix=b"SAME")
    for rel in (
        "input/logo.png",
        "assets/shared/pool/logo.png",
        "media/local.png",
        "prototypes/demo/index.html",
        "prototypes/demo/app.js",
    ):
        _write(dst / rel, (src / rel).read_bytes())
        os.utime(dst / rel, (1, 1))

    (dst / "deck.json").write_text(
        json.dumps(_deck("destination", [{
            "key": "keep", "layout": "raw", "data": {"html": "<div>keep</div>"},
        }]), ensure_ascii=False),
        encoding="utf-8",
    )

    proc = _run_paste(dst, src)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    pasted = json.loads((dst / "deck.json").read_text(encoding="utf-8"))["slides"][-1]
    blob = pasted["custom_css"] + json.dumps(pasted["data"], ensure_ascii=False)
    assert "input/logo.png" in blob
    assert "assets/shared/pool/logo.png" in blob
    assert "prototypes/demo/index.html" in blob
    assert "media/local.png" in blob
    assert not list((dst / "input").glob("logo-*.png"))
    assert not list((dst / "assets" / "shared" / "pool").glob("logo-*.png"))
    assert not list((dst / "prototypes").glob("demo-*"))
    assert not list((dst / "media").glob("local-*.png"))


def test_asset_reference_rewrite_walks_nested_slide_data_without_touching_other_slide():
    cli = _load_cli_module()
    pasted = {
        "custom_css": ".x{background:url('input/logo.png')}",
        "data": {
            "nested": ["input/logo.png", {"deep": "media/local.png"}],
        },
    }
    untouched = json.loads(json.dumps(pasted))
    cli._rewrite_slide_asset_refs(
        pasted,
        {"input/logo.png": "input/logo-deadbeef0000.png",
         "media/local.png": "media/local-cafebabe0000.png"},
        {},
    )
    assert pasted["data"]["nested"][0] == "input/logo-deadbeef0000.png"
    assert pasted["data"]["nested"][1]["deep"] == "media/local-cafebabe0000.png"
    assert untouched["data"]["nested"][0] == "input/logo.png"
