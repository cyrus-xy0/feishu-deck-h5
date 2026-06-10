"""F-269 / F-270 · atomic writes, gate-fail rollback, and complete --inline.

F-269
  • render-deck.py / deck-cli.py / lift-slides.py write index.html, slide-index
    .json and deck.json ATOMICALLY (temp file + os.replace) — a kill mid-write
    never leaves a torn file.
  • render-deck.py writes index.html BEFORE the delivery gate; on a gate fail
    (return 4) it must RESTORE the previously-good index.html instead of leaving
    the rejected one on disk. A successful (or gate-skipped) render drops the
    backup.

F-270
  • --inline base64-inlines <img src> / <source src> / <video src|poster> and
    BARE url() — not just quoted background-image url() (the old gap).
  • a LOCAL ref it can't inline (file missing) is WARNED about (was silent);
    --inline-strict makes that a non-zero exit.

The in-process rollback test drives the STATIC gate (rc != 0) by monkeypatching
the validate-html subprocess call, so it needs NO Playwright. A second,
Playwright-gated end-to-end test exercises the REAL visual gate path and skips
cleanly on a no-Chromium box.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import pathlib

import pytest

DECK_JSON = pathlib.Path(__file__).resolve().parents[1]
RENDER = DECK_JSON / "render-deck.py"
DECK_CLI = DECK_JSON / "deck-cli.py"
EXAMPLE = DECK_JSON / "examples" / "sample-deck.json"


# --------------------------------------------------------------------------
# module import helpers (hyphenated filenames → importlib)
# --------------------------------------------------------------------------
def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RD = _load("_rd_under_test", RENDER)
DC = _load("_dc_under_test", DECK_CLI)


def _have_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False
    try:
        p = sync_playwright().start()
        b = p.chromium.launch()
        b.close()
        p.stop()
        return True
    except Exception:
        return False


HAVE_PW = _have_playwright()


def _render(deck_path, out_dir, *extra, env=None):
    cmd = [sys.executable, str(RENDER), str(deck_path), str(out_dir) + "/",
           "--skip-copy-assets", *extra]
    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, env=run_env)


def _runs_output(td) -> pathlib.Path:
    out = pathlib.Path(td) / "runs" / "20260610-000000" / "output"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _simple_deck(title="T", body="这是一段足够长的正文内容用来填充页面文本区域"):
    return {
        "version": "1.0",
        "deck": {"title": title, "author": "a", "date": "2026.06.10",
                 "presentation_date": "2026-06-10", "customer_slug": "wa-x",
                 "language": "zh-only", "mode": "rewrite"},
        "slides": [{
            "key": "k", "layout": "raw", "screen_label": "01 X",
            "data": {"html": f'<div class="stage"><p style="color:#ddd;'
                             f'font-size:24px">{body}</p></div>'},
        }],
    }


# ==========================================================================
# F-269 · atomic_write_text mechanics (portable)
# ==========================================================================
def test_atomic_write_text_writes_and_is_clean():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "nested" / "f.txt"   # parent created on demand
        DC.atomic_write_text(p, "héllo 世界")
        assert p.read_text(encoding="utf-8") == "héllo 世界"
        # no leftover temp turds in the dir
        assert list(p.parent.glob(".*.tmp")) == []


def test_atomic_write_text_replaces_existing_no_torn_file():
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "f.txt"
        DC.atomic_write_text(p, "v1-old-content")
        DC.atomic_write_text(p, "v2-new-content")
        assert p.read_text() == "v2-new-content"
        assert list(p.parent.glob(".*.tmp")) == []


def test_atomic_write_text_failure_leaves_no_turd_and_keeps_old(monkeypatch):
    # Simulate a crash mid-write: os.replace blows up AFTER the temp file is
    # written. The original file must be untouched and no .tmp turd left.
    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / "f.txt"
        p.write_text("ORIGINAL")
        real_replace = os.replace

        def boom(src, dst):
            raise OSError("simulated crash before rename completes")

        monkeypatch.setattr(DC.os, "replace", boom)
        with pytest.raises(OSError):
            DC.atomic_write_text(p, "NEWDATA")
        monkeypatch.setattr(DC.os, "replace", real_replace)
        assert p.read_text() == "ORIGINAL"        # old file intact
        assert list(p.parent.glob(".*.tmp")) == []  # temp cleaned up


def test_render_module_shares_deck_cli_atomic_write():
    # render-deck must single-source the writer (imported from deck-cli), not
    # silently fall back to a divergent local copy in the normal case.
    assert RD.atomic_write_text.__module__ in ("_dc_under_test", "_deck_cli_atomic")


# ==========================================================================
# F-269 · render writes the sidecar files atomically, no .bak left on success
# ==========================================================================
def test_successful_render_outputs_and_no_bak_left():
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "out"
        out.mkdir()
        r = _render(EXAMPLE, out)
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        assert (out / "index.html").is_file()
        assert (out / "slide-index.json").is_file()
        json.loads((out / "slide-index.json").read_text())  # valid JSON
        # success path must clean up the pre-render backup + any temp turds
        assert not (out / "index.html.bak-pre-render").exists()
        assert list(out.glob(".*.tmp")) == []


# ==========================================================================
# F-269 · gate FAIL rolls back the previously-good index.html (portable —
# drives the STATIC gate via a monkeypatched validate-html subprocess call)
# ==========================================================================
def test_gate_fail_rolls_back_previous_index_html(monkeypatch, capsys, tmp_path):
    out = tmp_path / "out"
    out.mkdir()

    # 1. First render succeeds → a known-good index.html on disk.
    good = _simple_deck(title="GOOD-V1", body="第一版已通过校验的正文内容文字足够长")
    good_path = tmp_path / "good.json"
    good_path.write_text(json.dumps(good, ensure_ascii=False), encoding="utf-8")
    rc0 = RD.main([str(good_path), str(out) + "/", "--skip-copy-assets"])
    assert rc0 == 0
    v1 = (out / "index.html").read_text(encoding="utf-8")
    assert "GOOD-V1" in v1

    # 2. Second render of DIFFERENT content, but force the static HTML gate to
    #    fail. Monkeypatch render-deck's subprocess.run so ONLY the main
    #    validate-html call (validate.py without --json) returns rc=1; every
    #    other subprocess (json-schema validate, advisory, copy-assets) runs for
    #    real.
    real_run = subprocess.run
    VH = str(RD.VALIDATE_HTML)

    def fake_run(cmd, *a, **k):
        if isinstance(cmd, (list, tuple)) and VH in [str(c) for c in cmd] \
                and "--json" not in [str(c) for c in cmd]:
            return subprocess.CompletedProcess(cmd, 1, stdout="forced FAIL\n",
                                               stderr="")
        return real_run(cmd, *a, **k)

    monkeypatch.setattr(RD.subprocess, "run", fake_run)

    bad = _simple_deck(title="BAD-V2", body="第二版会被闸门拒绝的正文内容文字足够长")
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    rc1 = RD.main([str(bad_path), str(out) + "/", "--skip-copy-assets"])

    assert rc1 == 4, "a static-gate failure must return 4"
    # the BAD render must NOT have clobbered the previously-good file
    after = (out / "index.html").read_text(encoding="utf-8")
    assert after == v1, "index.html must be rolled back to the last good version"
    assert "GOOD-V1" in after and "BAD-V2" not in after
    err = capsys.readouterr().err
    assert "回滚" in err, f"expected a rollback notice on stderr:\n{err}"
    # backup consumed by the restore, no temp turds
    assert not (out / "index.html.bak-pre-render").exists()
    assert list(out.glob(".*.tmp")) == []


# ==========================================================================
# F-269 · the REAL visual gate path also rolls back (Playwright-gated)
# ==========================================================================
_FLOOR_DECK = {
    "version": "1.0",
    "deck": {"title": "Floor gate fixture", "author": "t", "date": "2026.06.10",
             "presentation_date": "2026-06-10", "customer_slug": "wa-floor",
             "language": "zh-only", "mode": "rewrite"},
    "slides": [{
        "key": "floor", "layout": "raw", "screen_label": "01 Floor",
        "data": {"html": (
            '<div class="stage"><div style="font-size:16px;color:#fff;'
            'line-height:1.6;max-width:900px">这是一段被故意设成十六像素的正文'
            '内容必须升到二十四像素才达到投影可读底线这是真实句子级文本不是装饰'
            '也不是页码或来源标签所以会触发可读性底线硬闸</div></div>')},
    }],
}


@pytest.mark.skipif(not HAVE_PW, reason="Playwright/Chromium unavailable")
def test_real_visual_gate_fail_rolls_back():
    with tempfile.TemporaryDirectory() as td:
        out = _runs_output(td)
        # 1. a good render under runs/ first
        good = pathlib.Path(td) / "good.json"
        good.write_text(json.dumps(_simple_deck(title="REAL-GOOD"),
                                   ensure_ascii=False), encoding="utf-8")
        r0 = _render(good, out)
        assert r0.returncode == 0, f"{r0.stdout}\n{r0.stderr}"
        v1 = (out / "index.html").read_text(encoding="utf-8")
        assert "REAL-GOOD" in v1
        # 2. floor deck trips the real visual gate (return 4)
        bad = pathlib.Path(td) / "floor.json"
        bad.write_text(json.dumps(_FLOOR_DECK, ensure_ascii=False),
                       encoding="utf-8")
        r1 = _render(bad, out)
        assert r1.returncode == 4, f"floor deck must BLOCK:\n{r1.stdout}\n{r1.stderr}"
        after = (out / "index.html").read_text(encoding="utf-8")
        assert after == v1, "real gate fail must roll back to the good index.html"
        assert "回滚" in r1.stderr


# ==========================================================================
# F-270 · --inline completeness
# ==========================================================================
def _inline_fixture_deck(td, out_dir, img_rel="input/x.png", make_img=True):
    """A raw deck that references a local <img src> + a quoted background-image
    url() + a BARE url() — the three things F-270 must inline. Asset refs in raw
    HTML pass through verbatim and --inline resolves them relative to the OUTPUT
    dir (where index.html lands), so the image is placed UNDER out_dir."""
    root = pathlib.Path(td)
    if make_img:
        img_abs = pathlib.Path(out_dir) / img_rel
        img_abs.parent.mkdir(parents=True, exist_ok=True)
        # a tiny PNG byte blob (content doesn't matter for base64)
        img_abs.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRfakefakefake")
    deck = {
        "version": "1.0",
        "deck": {"title": "Inline fixture", "author": "a", "date": "2026.06.10",
                 "presentation_date": "2026-06-10", "customer_slug": "wa-inl",
                 "language": "zh-only", "mode": "rewrite"},
        "slides": [{
            "key": "k", "layout": "raw", "screen_label": "01 X",
            "data": {"html": (
                '<div class="stage">'
                f'<img src="{img_rel}" alt="logo">'
                f'<div style="background-image:url(\'{img_rel}\')"></div>'
                f'<div style="background:url({img_rel})"></div>'
                '</div>')},
        }],
    }
    p = root / "deck.json"
    p.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
    return p


def test_inline_base64s_img_src_and_bare_url():
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "out"
        out.mkdir()
        deck = _inline_fixture_deck(td, out)
        r = _render(deck, out, "--inline")
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        html = (out / "index.html").read_text(encoding="utf-8")
        # <img src> inlined
        assert 'src="data:image/png;base64,' in html, "img src must be inlined"
        # bare url() inlined
        assert "url('data:image/png;base64," in html, "bare url() must be inlined"
        # the local png ref must be GONE (fully inlined, won't 404 after move)
        assert "input/x.png" not in html
        # single-file mode meta present
        assert '<meta name="fs-deck-mode" content="inline">' in html


def test_inline_quoted_bg_url_no_regression():
    # The pre-F-270 behaviour (quoted background-image url()) must still inline.
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "out"
        out.mkdir()
        deck = _inline_fixture_deck(td, out)
        r = _render(deck, out, "--inline")
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        html = (out / "index.html").read_text(encoding="utf-8")
        # the deck's quoted background-image url() must become a data: URI.
        assert "background-image:url('data:image/png;base64," in html


def test_inline_missing_local_ref_warns_but_succeeds():
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "out"
        out.mkdir()
        # reference a file that does NOT exist (don't create it)
        deck = _inline_fixture_deck(td, out, img_rel="input/does-not-exist.png",
                                    make_img=False)
        r = _render(deck, out, "--inline")
        assert r.returncode == 0, "missing local ref alone must NOT fail (only warn)"
        assert "未内联" in r.stderr, f"expected a missing-ref warning:\n{r.stderr}"
        assert "does-not-exist.png" in r.stderr


def test_inline_strict_fails_on_missing_local_ref():
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "out"
        out.mkdir()
        deck = _inline_fixture_deck(td, out, img_rel="input/does-not-exist.png",
                                    make_img=False)
        r = _render(deck, out, "--inline-strict")
        assert r.returncode != 0, "--inline-strict must FAIL when a local ref is missing"
        assert "未内联" in r.stderr


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            # crude standalone runner: skip fixtures needing pytest args
            import inspect
            params = inspect.signature(fn).parameters
            if params:
                print(f"skip  {fn.__name__} (needs pytest fixtures)")
                continue
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed - 1}/{len(fns)} ran")
    sys.exit(1 if failed else 0)
