"""F-285 · publisher post-publish self-check.

Covers the standalone self-check that re-opens the final published URL as the
audience would and red-cards on the three last-mile delivery failures that have
no other validator:

  * a broken / 404'd asset on the remote (the dimension validate.py never sees —
    it checks local bytes, not what the receiving server serves);
  * a font that silently fell back on the remote where the local render used a
    real loaded face;
  * a per-slide visual difference past threshold between local and remote.

The browser-driven capture (`capture_side`) is exercised by an OPTIONAL
end-to-end test that spins up a local http server as a stand-in 'remote' and
skips cleanly when Playwright/Pillow are unavailable. Everything else — font
fallback heuristics, failed-request classification, the perceptual-hash / pixel
diff, and the verdict assembly in `compare_captures` — is pure logic and runs
without a browser.
"""
from __future__ import annotations

import functools
import importlib.util
import shutil
import socketserver
import threading
import http.server
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SELF_CHECK = ROOT / "subskills/publisher/self_check.py"
PUBLISH = ROOT / "subskills/publisher/publish.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


SC = _load("publisher_self_check_under_test", SELF_CHECK)


def _have_pillow() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except Exception:
        return False


def _have_playwright() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


HAVE_PIL = _have_pillow()
HAVE_PW = _have_playwright()


# --------------------------------------------------------------- font fallback
def test_font_fallback_remote_collapsed_to_generic():
    # local used a real face, remote resolved to a generic -> fallback
    assert SC.font_fell_back("Inter, sans-serif", "sans-serif, system-ui") is True


def test_font_fallback_remote_substituted_lastresort_cjk():
    # local intended a deck CJK face, remote substituted a system CJK face
    assert SC.font_fell_back("'PingFang TC', 'Source Han'", "Microsoft YaHei, sans-serif") is True


def test_font_fallback_same_face_is_not_fallback():
    assert SC.font_fell_back("Inter, sans-serif", "Inter, Arial") is False


def test_font_fallback_local_already_generic_is_not_fallback():
    # nothing to fall back FROM if local itself was generic
    assert SC.font_fell_back("sans-serif", "Arial, sans-serif") is False


def test_font_fallback_empty_inputs_safe():
    assert SC.font_fell_back("", "Arial") is False
    assert SC.font_fell_back("Inter", "") is False


# ----------------------------------------------------- failed-request triage
def test_asset_failure_classifies_real_assets():
    assert SC._is_asset_failure({"resource_type": "image", "failure": "net::ERR"}) is True
    assert SC._is_asset_failure({"resource_type": "font", "failure": "net::ERR"}) is True
    assert SC._is_asset_failure({"resource_type": "stylesheet", "failure": "net::ERR"}) is True


def test_asset_failure_status_based_always_real():
    # a 404 on any type (even an odd resource_type) is real
    assert SC._is_asset_failure({"resource_type": "other", "failure": "HTTP 404", "status": 404}) is True


def test_asset_failure_ignores_aborted_beacon_noise():
    # a non-asset type with no HTTP status is treated as ignorable noise
    assert SC._is_asset_failure({"resource_type": "other", "failure": "net::ERR_ABORTED"}) is False


def test_asset_failure_ignores_magic_shell_probes():
    assert SC._is_asset_failure({
        "url": "https://magic.solutionsuite.cn/api/me",
        "resource_type": "fetch",
        "failure": "HTTP 401",
        "status": 401,
    }) is False
    assert SC._is_asset_failure({
        "url": "https://magic.solutionsuite.cn/app/.image-slots.state.json",
        "resource_type": "fetch",
        "failure": "HTTP 403",
        "status": 403,
    }) is False


def test_classify_transient_document_abort_reprobe_ok_is_ignored(monkeypatch):
    monkeypatch.setattr(SC, "_reprobe_url_ok", lambda url: True)
    broken, ignored = SC._classify_failed_requests([{
        "url": "https://magic.solutionsuite.cn/html-box/demo",
        "resource_type": "document",
        "failure": "net::ERR_ABORTED",
    }])
    assert broken == []
    assert ignored and ignored[0]["ignored_reason"] == "transient-browser-failure-reprobe-ok"


def test_classify_transient_script_reprobe_failed_stays_broken(monkeypatch):
    monkeypatch.setattr(SC, "_reprobe_url_ok", lambda url: False)
    broken, ignored = SC._classify_failed_requests([{
        "url": "https://cdn.example.test/app.js",
        "resource_type": "script",
        "failure": "net::ERR_FAILED",
    }])
    assert ignored == []
    assert broken and broken[0]["url"] == "https://cdn.example.test/app.js"


# --------------------------------------------------------- image diff (algorithm)
def test_image_diff_byte_fallback_identical(tmp_path, monkeypatch):
    monkeypatch.setattr(SC, "have_pillow", lambda: False)
    a = tmp_path / "a.png"; b = tmp_path / "b.png"
    a.write_bytes(b"same-bytes"); b.write_bytes(b"same-bytes")
    ratio, method = SC.image_diff(a, b)
    assert ratio == 0.0 and method == "byte"


def test_image_diff_byte_fallback_differ(tmp_path, monkeypatch):
    monkeypatch.setattr(SC, "have_pillow", lambda: False)
    a = tmp_path / "a.png"; b = tmp_path / "b.png"
    a.write_bytes(b"one"); b.write_bytes(b"two-different")
    ratio, method = SC.image_diff(a, b)
    assert ratio == 1.0 and method == "byte"


@pytest.mark.skipif(not HAVE_PIL, reason="Pillow unavailable")
def test_image_diff_identical_image_zero(tmp_path):
    from PIL import Image
    a = tmp_path / "a.png"; b = tmp_path / "b.png"
    Image.new("RGB", (64, 36), (10, 20, 200)).save(a)
    Image.new("RGB", (64, 36), (10, 20, 200)).save(b)
    ratio, method = SC.image_diff(a, b)
    assert ratio == 0.0 and method == "phash+pixel"


@pytest.mark.skipif(not HAVE_PIL, reason="Pillow unavailable")
def test_image_diff_very_different_image_nonzero(tmp_path):
    from PIL import Image
    a = tmp_path / "a.png"; b = tmp_path / "b.png"
    Image.new("RGB", (64, 36), (10, 20, 200)).save(a)        # solid blue
    half = Image.new("RGB", (64, 36), (10, 20, 200)); px = half.load()
    for x in range(32, 64):
        for y in range(36):
            px[x, y] = (240, 0, 0)                            # right half red
    half.save(b)
    ratio, method = SC.image_diff(a, b)
    assert ratio > 0.0 and method == "phash+pixel"


# ------------------------------------------------- compare_captures (verdict)
def _png(tmp_path, name, color):
    """Write a tiny solid PNG and return its path (Pillow-gated helper)."""
    from PIL import Image
    p = tmp_path / name
    Image.new("RGB", (32, 18), color).save(p)
    return str(p)


@pytest.mark.skipif(not HAVE_PIL, reason="Pillow unavailable")
def test_compare_clean_is_ok(tmp_path):
    local = {"slides": [{"key": "cover", "idx": 1, "face": "Inter, sans-serif",
                         "png": _png(tmp_path, "lc.png", (0, 0, 0))}]}
    remote = {"slides": [{"key": "cover", "idx": 1, "face": "Inter, sans-serif",
                          "png": _png(tmp_path, "rc.png", (0, 0, 0))}],
              "failed_requests": []}
    v = SC.compare_captures(local, remote, threshold=0.06, diff_dir=None)
    assert v["ok"] is True
    assert v["broken_requests"] == [] and v["font_fallbacks"] == [] and v["visual_changed"] == []
    assert v["visual_unchanged"] == 1


def test_compare_broken_link_red_cards(tmp_path):
    # no images needed: just a 404'd asset on the remote
    local = {"slides": [{"key": "cover", "idx": 1, "face": "Inter", "png": ""}]}
    remote = {"slides": [{"key": "cover", "idx": 1, "face": "Inter", "png": ""}],
              "failed_requests": [
                  {"url": "https://x.invalid/a.png", "resource_type": "image",
                   "failure": "net::ERR_NAME_NOT_RESOLVED"},
                  {"url": "https://x.invalid/a.png", "resource_type": "image",
                   "failure": "net::ERR_NAME_NOT_RESOLVED"},  # dup -> deduped
              ]}
    v = SC.compare_captures(local, remote, threshold=0.06, diff_dir=None)
    assert v["ok"] is False
    assert len(v["broken_requests"]) == 1            # de-duplicated by url
    assert any("断链" in r or "404" in r for r in v["reasons"])


def test_compare_font_fallback_red_cards(tmp_path):
    local = {"slides": [{"key": "cover", "idx": 1, "face": "Inter, sans-serif", "png": ""}]}
    remote = {"slides": [{"key": "cover", "idx": 1, "face": "Arial, sans-serif", "png": ""}],
              "failed_requests": []}
    v = SC.compare_captures(local, remote, threshold=0.06, diff_dir=None)
    assert v["ok"] is False
    assert v["font_fallbacks"] and v["font_fallbacks"][0]["key"] == "cover"


@pytest.mark.skipif(not HAVE_PIL, reason="Pillow unavailable")
def test_compare_visual_drift_red_cards(tmp_path):
    local = {"slides": [{"key": "body", "idx": 2, "face": "Inter",
                         "png": _png(tmp_path, "lb.png", (0, 0, 0))}]}      # black
    remote = {"slides": [{"key": "body", "idx": 2, "face": "Inter",
                          "png": _png(tmp_path, "rb.png", (255, 255, 255))}],  # white
              "failed_requests": []}
    v = SC.compare_captures(local, remote, threshold=0.06, diff_dir=None)
    assert v["ok"] is False
    assert v["visual_changed"] and v["visual_changed"][0]["key"] == "body"


def test_compare_missing_pair_reported_not_crashed(tmp_path):
    local = {"slides": [{"key": "only-local", "idx": 1, "face": "Inter", "png": ""}]}
    remote = {"slides": [{"key": "only-remote", "idx": 1, "face": "Inter", "png": ""}],
              "failed_requests": []}
    v = SC.compare_captures(local, remote, threshold=0.06, diff_dir=None)
    keys = {m["key"] for m in v["missing"]}
    assert "only-local" in keys and "only-remote" in keys


# --------------------------------------------------------------- input resolve
def test_resolve_local_dir_to_index(tmp_path):
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    assert SC.resolve_local_html(tmp_path).name == "index.html"


def test_resolve_local_missing_index_errors(tmp_path):
    with pytest.raises(SystemExit):
        SC.resolve_local_html(tmp_path)


def test_normalize_remote_passes_http_through():
    assert SC.normalize_remote("https://magic.solutionsuite.cn/html-box/abc") == \
        "https://magic.solutionsuite.cn/html-box/abc"


def test_normalize_remote_local_path_becomes_file_uri(tmp_path):
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    uri = SC.normalize_remote(str(tmp_path))
    assert uri.startswith("file://") and uri.endswith("/index.html")


def test_normalize_remote_empty_errors():
    with pytest.raises(SystemExit):
        SC.normalize_remote("")


# --------------------------------------------------- browser-unavailable degrade
def test_run_self_check_degrades_when_no_browser(tmp_path, monkeypatch):
    # force capture to report 'no browser' -> skipped, ok True (never blocks),
    # report still written, no crash.
    (tmp_path / "index.html").write_text("<html><body></body></html>", encoding="utf-8")
    monkeypatch.setattr(SC, "capture_side",
                        lambda *a, **k: {"ok": False, "reason": "playwright not installed",
                                         "slides": [], "failed_requests": []})
    out = tmp_path / "out"
    payload = SC.run_self_check(local=tmp_path, remote=str(tmp_path), out_dir=out, pages=2)
    assert payload["skipped"] is True and payload["ok"] is False
    assert (out / "publish-self-check.json").exists()
    assert (out / "PUBLISH_SELF_CHECK.md").exists()


# ------------------------------------------------------- OPTIONAL end-to-end
@pytest.mark.skipif(not (HAVE_PW and HAVE_PIL), reason="needs Playwright + Pillow + rendered deck")
def test_end_to_end_local_vs_local_copy_and_404(tmp_path):
    """Render a real inline deck, serve a copy over local http as the 'remote',
    and assert: an identical copy is ok; a copy with a 404'd <img> red-cards."""
    import subprocess
    import sys

    sample = ROOT / "deck-json/examples/sample-deck.json"
    render = ROOT / "deck-json/render-deck.py"
    if not sample.exists() or not render.exists():
        pytest.skip("sample deck / renderer not present")
    local_dir = tmp_path / "local"
    proc = subprocess.run(
        [sys.executable, str(render), str(sample), str(local_dir), "--inline", "--skip-fit-check"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0 or not (local_dir / "index.html").exists():
        pytest.skip(f"inline render unavailable: {proc.stderr[-400:]}")

    html = (local_dir / "index.html").read_text(encoding="utf-8")

    def _serve(directory):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
        httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd, httpd.server_address[1]

    # clean remote
    clean = tmp_path / "remote_clean"; clean.mkdir()
    shutil.copy(local_dir / "index.html", clean / "index.html")
    httpd, port = _serve(clean)
    try:
        p1 = SC.run_self_check(local=local_dir, remote=f"http://127.0.0.1:{port}/index.html",
                               out_dir=tmp_path / "o1", pages=2, threshold=0.06)
    finally:
        httpd.shutdown()
    assert p1["skipped"] is False
    assert p1["ok"] is True, p1["verdict"]

    # 404 remote
    broken = tmp_path / "remote_404"; broken.mkdir()
    (broken / "index.html").write_text(
        html.replace("</body>",
                     '<img src="https://nonexistent.invalid.example/x.png" '
                     'style="position:absolute;left:-9px;top:-9px;width:1px;height:1px">\n</body>', 1),
        encoding="utf-8")
    httpd, port = _serve(broken)
    try:
        p2 = SC.run_self_check(local=local_dir, remote=f"http://127.0.0.1:{port}/index.html",
                               out_dir=tmp_path / "o2", pages=2, threshold=0.06)
    finally:
        httpd.shutdown()
    assert p2["skipped"] is False
    assert p2["ok"] is False
    assert p2["verdict"]["broken_requests"]
