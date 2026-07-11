"""Scoped `render --shoot` uses one visual browser lifecycle for audit + PNGs."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
SKILL = DECK_JSON.parent
RENDER = DECK_JSON / "render-deck.py"
RUN_AUDITS = SKILL / "assets" / "run-audits.py"
RUNTIME = SKILL / "assets" / "feishu-deck.js"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RD = _load("_render_scoped_shoot", RENDER)
RA = _load("_run_audits_scoped_shoot", RUN_AUDITS)


def _deck(count=4):
    return {
        "version": "1.0",
        "deck": {"title": "Scoped shoot", "author": "test", "date": "2026-07-10",
                 "language": "zh-only", "mode": "rewrite"},
        "slides": [
            {"key": f"page-{i}", "layout": "raw", "screen_label": f"{i:02d}",
             "data": {"html": f"<div class='stage'><p>page {i} content</p></div>"}}
            for i in range(1, count + 1)
        ],
    }


@pytest.mark.parametrize("pages", [[1], [1, 2, 3, 4]], ids=["scope-1", "scope-4"])
def test_renderer_launches_one_visual_validator_for_scope_shoot(
        monkeypatch, tmp_path, pages):
    deck_path = tmp_path / "deck.json"
    deck_path.write_text(json.dumps(_deck(), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "runs" / "20260710-scoped-shoot" / "output"
    out.mkdir(parents=True)
    calls = []

    def fake_run(cmd, *args, **kwargs):
        command = [str(x) for x in cmd]
        calls.append((command, kwargs))
        if str(RD.VALIDATE_HTML) in command and "--visual" in command:
            env = kwargs.get("env") or {}
            requested = env.get(RD.AUDIT_SHOOT_PAGES_ENV, "")
            for token in requested.split(","):
                if token:
                    (out / f".shoot-p{int(token)}.png").write_bytes(b"PNG")
            payload = {"ok": True, "errors": [], "warnings": [],
                       "soft_warnings": [], "distribution": None}
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")
        if str(RD.VALIDATE_HTML) in command:
            return subprocess.CompletedProcess(cmd, 0, stdout="PASS\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(RD.subprocess, "run", fake_run)
    rc = RD.main([
        str(deck_path), str(out) + "/", "--scope", ",".join(map(str, pages)),
        "--shoot", "--skip-validate-json", "--skip-copy-assets", "--force",
    ])
    assert rc == 0

    validate_calls = [c for c, _ in calls if str(RD.VALIDATE_HTML) in c]
    visual_calls = [(c, k) for c, k in calls
                    if str(RD.VALIDATE_HTML) in c and "--visual" in c]
    assert len(validate_calls) == 2, "one static gate + one visual gate, independent of page count"
    assert len(visual_calls) == 1, "--shoot must not launch a second visual validator"
    command, kwargs = visual_calls[0]
    assert command[command.index("--scope-frames") + 1] == ",".join(map(str, pages))
    assert kwargs["env"][RD.AUDIT_SHOOT_PAGES_ENV] == ",".join(map(str, pages))
    assert all("shoot-page.py" not in " ".join(c) for c, _ in calls)
    assert all((out / f".shoot-p{n}.png").read_bytes() == b"PNG" for n in pages)


def test_failed_scoped_gate_rolls_back_previous_screenshot(monkeypatch, tmp_path):
    deck_path = tmp_path / "deck.json"
    deck_path.write_text(json.dumps(_deck(count=1), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "runs" / "20260710-scoped-shoot-fail" / "output"
    out.mkdir(parents=True)
    shot = out / ".shoot-p1.png"
    shot.write_bytes(b"OLD-ACCEPTED-SHOT")

    def fake_run(cmd, *args, **kwargs):
        command = [str(x) for x in cmd]
        if str(RD.VALIDATE_HTML) in command and "--visual" in command:
            shot.write_bytes(b"NEW-REJECTED-SHOT")
            payload = {"ok": False, "errors": [{
                "code": "R-VIS-BODY-FLOOR", "severity": "error",
                "msg": "slide 1: forced visual failure", "slide": 1,
                "selector_hint": ".body",
            }], "warnings": [], "soft_warnings": []}
            return subprocess.CompletedProcess(cmd, 1, stdout=json.dumps(payload), stderr="")
        if str(RD.VALIDATE_HTML) in command:
            return subprocess.CompletedProcess(cmd, 0, stdout="PASS\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(RD.subprocess, "run", fake_run)
    rc = RD.main([
        str(deck_path), str(out) + "/", "--scope", "1", "--shoot",
        "--skip-validate-json", "--skip-copy-assets", "--force",
    ])
    assert rc == 4
    assert shot.read_bytes() == b"OLD-ACCEPTED-SHOT"
    assert not (out / "index.html").exists(), "fresh failed HTML must roll back too"


class _FakeLocator:
    def __init__(self, total):
        self.total = total

    def count(self):
        return self.total


class _FakePage:
    def __init__(self, total):
        self.total = total
        self.shots = []
        self.navigations = []

    def locator(self, selector):
        assert selector == ".slide-frame"
        return _FakeLocator(self.total)

    def evaluate(self, script, arg=None):
        if arg is not None:
            self.navigations.append(arg)

    def wait_for_function(self, *args, **kwargs):
        return None

    def wait_for_timeout(self, ms):
        return None

    def screenshot(self, *, path, timeout):
        Path(path).write_bytes(b"PNG")
        self.shots.append(Path(path))


@pytest.mark.parametrize("pages", [[1], [1, 2, 3, 4]], ids=["scope-1", "scope-4"])
def test_one_settled_page_captures_all_requested_screenshots(tmp_path, pages):
    html = tmp_path / "index.html"
    html.write_text("<html></html>", encoding="utf-8")
    page = _FakePage(total=4)
    result = RA._capture_scoped_screenshots(page, html, pages)
    assert len(page.shots) == len(pages)
    assert [r["page"] for r in result] == pages
    assert all(r["ok"] for r in result)
    assert page.navigations == pages


def test_audit_freezes_findings_before_screenshots_and_has_one_browser_context():
    source = RUN_AUDITS.read_text(encoding="utf-8")
    engine = source[source.index("def run_unified_engine"):]
    assert engine.count("pw.chromium.launch") == 1
    assert engine.count("browser.new_context") == 1
    assert engine.index("result = page.evaluate(audits_src)") < engine.index(
        "_capture_scoped_screenshots(")
    helper = source[source.index("def _capture_scoped_screenshots"):source.index(
        "def run_unified_engine")]
    assert "chromium.launch" not in helper and "new_context" not in helper


def test_runtime_consumes_preinit_scope_for_expensive_initial_loops():
    source = RUNTIME.read_text(encoding="utf-8")
    init = source[source.index("function init()"):source.index("// ---- Boot ----")]
    assert "Array.isArray(window.__AUDIT_SCOPE__)" in init
    assert "auditScope.has(i + 1)" in init, "audit scope must remain 1-based"
    assert "auditInitFrames.forEach((f) => { const s = f.querySelector('.slide'); maybeBalance(s)" in init
    assert "auditInitFrames.forEach((f) => { try { setBandAnchor" in init
    # Observers/navigation still cover every frame; scoping is startup-only.
    assert "frames.forEach((f) => mediaObserver.observe" in init
