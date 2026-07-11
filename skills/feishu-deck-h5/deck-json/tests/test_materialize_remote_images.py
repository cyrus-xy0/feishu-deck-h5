from __future__ import annotations

from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parents[1]
SCRIPT = SKILL_ROOT / "assets" / "materialize-remote-images.py"
RENDER = SKILL_ROOT / "deck-json" / "render-deck.py"


def _load():
    name = "materialize_remote_images_reliability"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class _Fetched:
    url: str
    content_type: str
    payload: bytes


def _install_fetcher(monkeypatch, module, *, fail_on: str = ""):
    calls: list[str] = []

    def fetch(url, **_kwargs):
        calls.append(url)
        if fail_on and fail_on in url:
            raise RuntimeError("synthetic mid-download failure")
        return _Fetched(url=url, content_type="image/png", payload=("PNG:" + url).encode())

    monkeypatch.setattr(module, "download_public_resource", fetch)
    return calls


def _relative(source: Path, output: Path, root_relative: str) -> str:
    return Path(os.path.relpath(output / root_relative, source.parent)).as_posix()


def test_nested_html_and_css_refs_are_relative_to_each_source_file(tmp_path: Path, monkeypatch):
    module = _load()
    calls = _install_fetcher(monkeypatch, module)
    output = tmp_path / "output"
    css = output / "assets" / "theme" / "main.css"
    iframe = output / "prototypes" / "demo" / "index.html"
    css.parent.mkdir(parents=True)
    iframe.parent.mkdir(parents=True)
    output.mkdir(exist_ok=True)
    url = "https://cdn.example.test/media/hero.png?sig=abc"
    index = output / "index.html"
    index.write_text(f'<img src="{url}">', encoding="utf-8")
    css.write_text(f'.hero{{background-image:url("{url}")}}', encoding="utf-8")
    iframe.write_text(f'<img src="{url}">', encoding="utf-8")
    (output / "assets-manifest.yaml").write_text(
        "framework: []\nshared: []\ndeck-local: []\n", encoding="utf-8")

    downloads = module.materialize(output)

    assert calls == [url]
    assert len(downloads) == 1
    root_ref = downloads[0].relative_path
    assert root_ref in index.read_text(encoding="utf-8")
    assert _relative(css, output, root_ref) in css.read_text(encoding="utf-8")
    assert _relative(iframe, output, root_ref) in iframe.read_text(encoding="utf-8")
    assert downloads[0].path.is_file()
    assert root_ref in (output / "assets-manifest.yaml").read_text(encoding="utf-8")


def test_deckjson_is_recursively_rewritten_to_preserve_rerender_parity(tmp_path: Path, monkeypatch):
    module = _load()
    _install_fetcher(monkeypatch, module)
    output = tmp_path / "output"
    output.mkdir()
    url = "https://cdn.example.test/media/hero.png?a=1&b=2"
    escaped = url.replace("&", "&amp;")
    protocol_relative = "//" + url[len("https://"):]
    (output / "index.html").write_text(f'<img src="{escaped}">', encoding="utf-8")
    deck = {
        "version": "1.0",
        "deck": {
            "title": "remote", "author": "a", "date": "2026.07.10",
            "presentation_date": "2026-07-10", "customer_slug": "remote",
            "language": "zh-only", "mode": "rewrite",
        },
        "slides": [{
            "key": "hero",
            "layout": "raw",
            "screen_label": "01 Remote",
            "data": {
                "html": f'<img src="{url}">',
                "nested": [url, {"protocol_relative": protocol_relative}],
            },
            "custom_css": f'.hero{{background:url("{escaped}")}}',
        }],
    }
    (output / "deck.json").write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")

    downloads = module.materialize(output)
    root_ref = downloads[0].relative_path
    rewritten = json.loads((output / "deck.json").read_text(encoding="utf-8"))
    blob = json.dumps(rewritten, ensure_ascii=False)
    assert url not in blob
    assert escaped not in blob
    assert protocol_relative not in blob
    assert blob.count(root_ref) >= 4

    # A renderer reads DeckJSON again; the reconstructed page must stay local.
    slide = rewritten["slides"][0]
    simulated_rerender = slide["data"]["html"] + slide["custom_css"]
    assert root_ref in simulated_rerender
    assert "https://cdn.example.test" not in simulated_rerender

    proc = subprocess.run(
        [
            sys.executable, str(RENDER), str(output / "deck.json"), str(output),
            "--skip-validate-json", "--skip-validate-html", "--skip-fit-check",
            "--skip-copy-assets", "--force",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    rerendered_html = (output / "index.html").read_text(encoding="utf-8")
    assert root_ref in rerendered_html
    assert "https://cdn.example.test" not in rerendered_html
    assert (output / root_ref).is_file()


def test_mid_download_failure_leaves_all_delivery_sources_unchanged(tmp_path: Path, monkeypatch):
    module = _load()
    output = tmp_path / "output"
    output.mkdir()
    first = "https://cdn.example.test/media/first.png"
    second = "https://cdn.example.test/media/second.png"
    index = output / "index.html"
    css = output / "theme.css"
    deck_path = output / "deck.json"
    manifest = output / "assets-manifest.yaml"
    index.write_text(f'<img src="{first}"><img src="{second}">', encoding="utf-8")
    css.write_text(f'.x{{background:url("{first}")}}', encoding="utf-8")
    deck_path.write_text(json.dumps({"slides": [{"data": {"html": first}}]}), encoding="utf-8")
    manifest.write_text("framework: []\nshared: []\ndeck-local: []\n", encoding="utf-8")
    snapshots = {path: path.read_bytes() for path in (index, css, deck_path, manifest)}
    calls = _install_fetcher(monkeypatch, module, fail_on="second.png")

    with pytest.raises(RuntimeError, match="synthetic mid-download failure"):
        module.materialize(output)

    assert calls == [first, second]
    assert all(path.read_bytes() == before for path, before in snapshots.items())
    assert not (output / "assets" / "remote").exists()
    assert not list(tmp_path.glob(".materialize-remote-*"))


def test_commit_failure_rolls_back_assets_and_prior_text_replacements(tmp_path: Path, monkeypatch):
    module = _load()
    output = tmp_path / "output"
    output.mkdir()
    url = "https://cdn.example.test/media/hero.png"
    index = output / "index.html"
    deck_path = output / "deck.json"
    manifest = output / "assets-manifest.yaml"
    index.write_text(f'<img src="{url}">', encoding="utf-8")
    deck_path.write_text(json.dumps({"slides": [{"data": {"html": url}}]}), encoding="utf-8")
    manifest.write_text("framework: []\nshared: []\ndeck-local: []\n", encoding="utf-8")
    snapshots = {path: path.read_bytes() for path in (index, deck_path, manifest)}
    _install_fetcher(monkeypatch, module)
    real_replace = module.os.replace
    failed = False

    def flaky_replace(source, destination):
        nonlocal failed
        if Path(destination) == deck_path and not failed:
            failed = True
            raise OSError("synthetic commit failure")
        return real_replace(source, destination)

    monkeypatch.setattr(module.os, "replace", flaky_replace)
    with pytest.raises(RuntimeError, match="commit failed and was rolled back"):
        module.materialize(output)

    assert failed
    assert all(path.read_bytes() == before for path, before in snapshots.items())
    assert not (output / "assets" / "remote").exists()
