"""Focused transaction tests for lift-insert.py.

Every failure deliberately dirties the staged copy before raising.  The
official destination must remain content-identical, including assets,
prototypes, validation sidecars and screenshots.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest


HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "lift-insert.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("lift_insert_transaction", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


LIFT = _load_tool()


def _slide(key: str, text: str, *, notes: str | None = None,
           iframe: str | None = None) -> dict:
    if iframe is not None:
        slide = {
            "key": key,
            "layout": "iframe-embed",
            "screen_label": key,
            "data": {"src": iframe, "title": text},
        }
    else:
        slide = {
            "key": key,
            "layout": "raw",
            "screen_label": key,
            "data": {"html": f'<div class="stage">{text}</div>'},
        }
    if notes is not None:
        slide["notes"] = notes
    return slide


def _deck(title: str, slides: list[dict]) -> dict:
    return {
        "version": "1.0",
        "deck": {"title": title, "author": "tester", "date": "2026-07"},
        "slides": slides,
    }


def _write_deck_dir(path: Path, deck: dict, *, target_sentinels: bool = False) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "deck.json").write_text(
        json.dumps(deck, ensure_ascii=False, indent=2), encoding="utf-8")
    (path / "index.html").write_text(
        "<html><head><meta name='old-only' content='stale'></head>"
        "<body>OLD-FRAME-STRING-ONLY</body></html>", encoding="utf-8")
    if target_sentinels:
        (path / "slide-index.json").write_bytes(b"OLD-SLIDE-INDEX\n")
        (path / ".slide-hashes.json").write_bytes(b"OLD-HASHES\n")
        (path / "validate-findings.json").write_bytes(b"OLD-BASELINE\n")
        (path / ".shoot-p1.png").write_bytes(b"OLD-SHOT\x00")
        (path / "assets").mkdir()
        (path / "assets" / "keep.bin").write_bytes(b"OFFICIAL-ASSET\x00")
        (path / "prototypes").mkdir()
        (path / "prototypes" / "keep.html").write_bytes(b"OFFICIAL-PROTOTYPE\n")


@pytest.fixture
def workspace(tmp_path: Path):
    target = tmp_path / "runs" / "target" / "output"
    _write_deck_dir(
        target,
        _deck("target", [
            _slide("target-one", "one", notes="target note"),
            _slide("target-two", "two"),
        ]),
        target_sentinels=True,
    )
    source_a = tmp_path / "source-a"
    source_b = tmp_path / "source-b"
    _write_deck_dir(source_a, _deck("source-a", [
        _slide("insert-a", "insert A", notes="inserted note"),
    ]))
    _write_deck_dir(source_b, _deck("source-b", [
        _slide("insert-b", "insert B"),
    ]))
    return target, source_a, source_b


def _argv(target: Path, *source_dirs: Path, verify: bool = False) -> list[str]:
    args = ["--after", f"{target / 'index.html'}#1"]
    args += [f"{source / 'index.html'}#1" for source in source_dirs]
    if verify:
        args.append("--verify")
    return args


def _completed(cmd: list[str], rc: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(cmd, rc, stdout="", stderr="")


def _fake_paste(cmd: list[str], target: Path) -> Path:
    assert Path(cmd[1]) == LIFT.DECK_CLI
    staged_deck = Path(cmd[2])
    assert target not in staged_deck.parents
    assert ".lift-insert-stage-" in str(staged_deck)
    src = Path(cmd[cmd.index("--from") + 1])
    key = cmd[cmd.index("--key") + 1]
    position = int(cmd[-1])
    source_deck = json.loads(src.read_text(encoding="utf-8"))
    copied = next(slide for slide in source_deck["slides"] if slide["key"] == key)
    copied = json.loads(json.dumps(copied))
    destination = json.loads(staged_deck.read_text(encoding="utf-8"))
    destination["slides"].insert(position - 1, copied)
    staged_deck.write_text(
        json.dumps(destination, ensure_ascii=False, indent=2), encoding="utf-8")
    staged_asset = staged_deck.parent / "assets" / f"{key}.bin"
    staged_asset.parent.mkdir(parents=True, exist_ok=True)
    staged_asset.write_bytes(f"staged-{key}".encode())
    return staged_deck


def _assert_untouched(target: Path, before) -> None:
    assert LIFT._tree_fingerprint(target) == before
    stage_dirs = list(target.parent.parent.glob(".lift-insert-stage-*"))
    assert stage_dirs == [], f"leaked stage directories: {stage_dirs}"


def test_second_paste_failure_rolls_back_every_official_byte(
        workspace, monkeypatch: pytest.MonkeyPatch):
    target, source_a, source_b = workspace
    before = LIFT._tree_fingerprint(target)
    calls = 0

    def fake_run(cmd, **_kwargs):
        nonlocal calls
        if Path(cmd[1]) == LIFT.DECK_CLI:
            calls += 1
            if calls == 2:
                return _completed(cmd, 9)
            _fake_paste(cmd, target)
            return _completed(cmd)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(LIFT, "_run", fake_run)
    with pytest.raises(RuntimeError, match=r"paste failed \(9\)"):
        LIFT.main(_argv(target, source_a, source_b))
    assert calls == 2
    _assert_untouched(target, before)


def test_download_failure_discards_partial_prototype_and_paste(
        workspace, monkeypatch: pytest.MonkeyPatch):
    target, _source_a, _source_b = workspace
    remote = target.parent.parent.parent / "remote-source"
    _write_deck_dir(remote, _deck("remote", [
        _slide("remote-demo", "remote", iframe="https://public.example/demo.html"),
    ]))
    before = LIFT._tree_fingerprint(target)

    def fake_run(cmd, **_kwargs):
        if Path(cmd[1]) == LIFT.DECK_CLI:
            _fake_paste(cmd, target)
            return _completed(cmd)
        raise AssertionError(f"unexpected command: {cmd}")

    def fail_download(_src: str, dest: Path):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"PARTIAL-STAGED-DOWNLOAD")
        raise RuntimeError("download failed after partial write")

    monkeypatch.setattr(LIFT, "_run", fake_run)
    monkeypatch.setattr(LIFT, "_download_remote", fail_download)
    with pytest.raises(RuntimeError, match="download failed"):
        LIFT.main(_argv(target, remote))
    _assert_untouched(target, before)


def test_render_gate_failure_discards_rejected_bundle(
        workspace, monkeypatch: pytest.MonkeyPatch):
    target, source_a, _source_b = workspace
    before = LIFT._tree_fingerprint(target)

    def fake_run(cmd, **_kwargs):
        executable = Path(cmd[1])
        if executable == LIFT.DECK_CLI:
            _fake_paste(cmd, target)
            return _completed(cmd)
        if executable == LIFT.RENDER_DECK:
            stage = Path(cmd[3])
            (stage / "index.html").write_bytes(b"REJECTED-INDEX")
            (stage / "slide-index.json").write_bytes(b"REJECTED-SIDE-CAR")
            (stage / ".slide-hashes.json").write_bytes(b"REJECTED-HASHES")
            (stage / "validate-findings.json").write_bytes(b"REJECTED-BASELINE")
            (stage / ".shoot-p2.png").write_bytes(b"REJECTED-SHOT")
            raise RuntimeError("command failed (4): visual gate rejected")
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(LIFT, "_run", fake_run)
    with pytest.raises(RuntimeError, match="visual gate rejected"):
        LIFT.main(_argv(target, source_a, verify=True))
    _assert_untouched(target, before)


def test_directory_swap_failure_restores_official_tree(
        workspace, monkeypatch: pytest.MonkeyPatch):
    target, _source_a, _source_b = workspace
    before = LIFT._tree_fingerprint(target)
    stage = target.parent / "staged-output"
    stage.mkdir()
    (stage / "deck.json").write_bytes(b"NEW-BUT-NOT-COMMITTED")
    real_replace = LIFT.os.replace
    calls = 0

    def fail_second_replace(src, dst):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated staged-directory rename failure")
        return real_replace(src, dst)

    monkeypatch.setattr(LIFT.os, "replace", fail_second_replace)
    with pytest.raises(OSError, match="simulated staged-directory"):
        LIFT._commit_staged_directory(stage, target, before)
    assert calls == 3  # official→backup, stage→official(fail), backup→official
    assert LIFT._tree_fingerprint(target) == before
    assert stage.is_dir()


def _write_coherent_fake_render(cmd: list[str]) -> None:
    import _index_sig

    deck_path = Path(cmd[2])
    stage = Path(cmd[3])
    deck = json.loads(deck_path.read_text(encoding="utf-8"))
    active = [slide for slide in deck["slides"] if not slide.get("_disabled")]
    deck_hash = hashlib.sha256(deck_path.read_bytes()).hexdigest()[:12]
    frames = "\n".join(
        '<div class="slide-frame"><div class="slide" '
        f'data-slide-key="{slide["key"]}"></div></div>'
        for slide in active
    )
    notes = {slide["key"]: slide["notes"] for slide in active
             if isinstance(slide.get("notes"), str) and slide["notes"].strip()}
    notes_island = (
        '<script type="application/json" id="fs-deck-notes">'
        + json.dumps(notes, ensure_ascii=False).replace("</", "<\\/")
        + "</script>" if notes else "")
    html = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<meta name="fs-deck-generator" content="render-deck">'
        f'<meta name="fs-deck-hash" content="{deck_hash}"></head>'
        f'<body><div class="deck">{frames}</div>{notes_island}</body></html>'
    )
    (stage / "index.html").write_text(_index_sig.stamp_sig(html), encoding="utf-8")
    (stage / "slide-index.json").write_text(json.dumps({
        "version": "1.0",
        "deck": deck["deck"]["title"],
        "slides": [{"key": slide["key"], "frame_index": i + 1}
                   for i, slide in enumerate(active)],
    }), encoding="utf-8")
    (stage / ".slide-hashes.json").write_text(json.dumps({
        "schema": 4,
        "slides": [[slide["key"], f"hash-{i}"] for i, slide in enumerate(active)],
    }), encoding="utf-8")
    (stage / "validate-findings.json").write_text(json.dumps({
        "schema": 1,
        "note": "fresh-success-baseline",
        "fingerprints": [],
    }), encoding="utf-8")
    if "--shoot" in cmd:
        scope = cmd[cmd.index("--scope") + 1].split(",")
        by_key = {slide["key"]: i + 1 for i, slide in enumerate(active)}
        for key in scope:
            (stage / f".shoot-p{by_key[key]}.png").write_bytes(
                f"fresh-shot-{key}".encode())


def test_success_commits_one_coherent_source_of_truth_bundle(
        workspace, monkeypatch: pytest.MonkeyPatch):
    target, source_a, _source_b = workspace
    original_target = target
    rendered_stages: list[Path] = []

    def fake_run(cmd, **_kwargs):
        executable = Path(cmd[1])
        if executable == LIFT.DECK_CLI:
            _fake_paste(cmd, original_target)
            return _completed(cmd)
        if executable == LIFT.RENDER_DECK:
            stage = Path(cmd[3])
            assert stage != original_target
            assert "--shoot" in cmd
            # lift-insert must invalidate the old page-numbered screenshot before
            # producing the new bundle (the insertion shifts following frames).
            assert not (stage / ".shoot-p1.png").exists()
            _write_coherent_fake_render(cmd)
            (stage / "assets" / "rendered.bin").write_bytes(b"fresh-render-asset")
            rendered_stages.append(stage)
            return _completed(cmd)
        raise AssertionError(f"unexpected command: {cmd}")

    monkeypatch.setattr(LIFT, "_run", fake_run)
    assert LIFT.main(_argv(target, source_a, verify=True)) == 0
    assert len(rendered_stages) == 1

    deck = json.loads((target / "deck.json").read_text(encoding="utf-8"))
    keys = [slide["key"] for slide in deck["slides"]]
    assert keys == ["target-one", "insert-a", "target-two"]
    assert LIFT.verify_index_signature(target / "index.html") == "ok"
    html = (target / "index.html").read_text(encoding="utf-8")
    assert "OLD-FRAME-STRING-ONLY" not in html
    assert LIFT._frame_keys(html) == keys
    expected_hash = hashlib.sha256((target / "deck.json").read_bytes()).hexdigest()[:12]
    assert re.search(
        rf'name="fs-deck-hash" content="{expected_hash}"', html)
    assert LIFT._notes_from_index(html) == {
        "target-one": "target note",
        "insert-a": "inserted note",
    }

    slide_index = json.loads((target / "slide-index.json").read_text(encoding="utf-8"))
    assert [row["key"] for row in slide_index["slides"]] == keys
    assert [row["frame_index"] for row in slide_index["slides"]] == [1, 2, 3]
    hashes = json.loads((target / ".slide-hashes.json").read_text(encoding="utf-8"))
    assert [row[0] for row in hashes["slides"]] == keys
    baseline = json.loads((target / "validate-findings.json").read_text(encoding="utf-8"))
    assert baseline["note"] == "fresh-success-baseline"
    assert {path.name for path in target.glob(".shoot-p*.png")} == {".shoot-p2.png"}
    assert (target / ".shoot-p2.png").read_bytes() == b"fresh-shot-insert-a"
    assert (target / "assets" / "rendered.bin").read_bytes() == b"fresh-render-asset"
    assert list(target.parent.parent.glob(".lift-insert-stage-*")) == []
