"""F-255 / F-256 · delivery quality gate is a PATH/FLAG/ENV INVARIANT.

The visual/geometry gate used to silently turn OFF whenever any of these missed:
output not under runs/, a --scope/--quick flag, Playwright absent, or the
advisory JSON failed to parse — any miss → render silently PASSed. These tests
pin the new invariants without depending on the full visual suite:

  • a normal /tmp render is UNAFFECTED (still exits 0; gate stays advisory-only)
  • render always emits ONE machine-readable GATE-COVERAGE line, accurate to what
    actually ran, so "did not run" is distinguishable from "ran clean"
  • --quick keeps the static-only fast path but LOUDLY warns the hard gate skipped
  • (Playwright present) a real (runs/) render with error-level visual defects
    BLOCKS (return 4), and DECK_ALLOW_VIS_ERRORS=1 lets it through
  • (Playwright present) a real (runs/) render whose engine is forced down BLOCKS,
    and DECK_ALLOW_NO_VISUAL=1 lets it through

Playwright-requiring tests skip cleanly when Chromium can't launch (portable).
"""
import json
import os
import subprocess
import sys
import tempfile
import pathlib

import pytest

DECK_JSON = pathlib.Path(__file__).resolve().parents[1]
RENDER = DECK_JSON / "render-deck.py"
EXAMPLE = DECK_JSON / "examples" / "sample-deck.json"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _have_playwright() -> bool:
    """True iff Playwright is importable AND a Chromium instance launches —
    the same engine the delivery gate needs. Used to gate (skip) the BLOCK
    tests so the suite stays portable on a no-Chromium CI box."""
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
    """Invoke render-deck.py as a subprocess (the established test pattern).
    Always passes --skip-copy-assets so the temp output dir need not be a real
    repo runs/<ts>/output/ layout for the COPY step (the GATE under test runs
    before copy-assets regardless)."""
    cmd = [sys.executable, str(RENDER), str(deck_path), str(out_dir) + "/",
           "--skip-copy-assets", *extra]
    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    return subprocess.run(cmd, capture_output=True, text=True, env=run_env)


def _gate_coverage_line(stderr: str):
    for ln in stderr.splitlines():
        if ln.startswith("GATE-COVERAGE "):
            return ln
    return None


# A raw deck whose only error-level visual finding is R-VIS-BODY-FLOOR (real
# 16px sentence-like body text below the 24px floor). Deliberately NOT an
# overlap/overflow, so it trips the BROAD _vis_block (DECK_ALLOW_VIS_ERRORS)
# WITHOUT also tripping the narrower _HARD_GEOM/_geom_block (which has its own
# DECK_ALLOW_GEOM_OVERFLOW escape) — keeps the escape-hatch assertion clean.
_FLOOR_DECK = {
    "version": "1.0",
    "deck": {
        "title": "Floor gate fixture", "author": "t", "date": "2026.06.10",
        "presentation_date": "2026-06-10", "customer_slug": "wa-gate-fixture",
        "language": "zh-only", "mode": "rewrite",
    },
    "slides": [{
        "key": "floor", "layout": "raw", "screen_label": "01 Floor",
        "data": {"html": (
            '<div class="stage"><div style="font-size:16px;color:#fff;'
            'line-height:1.6;max-width:900px">这是一段被故意设成十六像素的正文'
            '内容必须升到二十四像素才达到投影可读底线这是真实句子级文本不是装饰'
            '也不是页码或来源标签所以会触发可读性底线硬闸</div></div>')},
    }],
}


def _write_floor_deck(td) -> pathlib.Path:
    p = pathlib.Path(td) / "floor-deck.json"
    p.write_text(json.dumps(_FLOOR_DECK, ensure_ascii=False), encoding="utf-8")
    return p


def _runs_output(td) -> pathlib.Path:
    """A runs/<ts>/output/ path under a temp root — the real-delivery layout the
    gate keys on (copy-assets.find_run_root accepts it)."""
    out = pathlib.Path(td) / "runs" / "20260610-000000" / "output"
    out.mkdir(parents=True, exist_ok=True)
    return out


# --------------------------------------------------------------------------
# 1. regression: a normal /tmp render is unaffected (exit 0 + GATE-COVERAGE)
# --------------------------------------------------------------------------
def test_tmp_render_unaffected_exits_zero_with_coverage():
    with tempfile.TemporaryDirectory() as td:
        r = _render(EXAMPLE, td)
        assert r.returncode == 0, f"normal /tmp render must still pass:\n{r.stdout}\n{r.stderr}"
        line = _gate_coverage_line(r.stderr)
        assert line is not None, f"GATE-COVERAGE line missing:\n{r.stderr}"
        # /tmp is NOT a runs/ path → the gate stays advisory-only (does not run).
        assert "static=ran" in line
        assert "not-runs/" in line, f"expected advisory-only skip reason in:\n{line}"


# --------------------------------------------------------------------------
# 2. GATE-COVERAGE line format invariant
# --------------------------------------------------------------------------
def test_gate_coverage_line_format():
    with tempfile.TemporaryDirectory() as td:
        r = _render(EXAMPLE, td)
        line = _gate_coverage_line(r.stderr)
        assert line is not None, f"no GATE-COVERAGE line:\n{r.stderr}"
        for field in ("static=", "visual=", "geometry=", "distribution=", "scope="):
            assert field in line, f"GATE-COVERAGE missing `{field}`:\n{line}"


# --------------------------------------------------------------------------
# 3. --quick keeps static-only but LOUDLY warns the hard gate skipped
# --------------------------------------------------------------------------
def test_quick_render_loud_skip_warning_and_exit_zero():
    with tempfile.TemporaryDirectory() as td:
        r = _render(EXAMPLE, td, "--quick")
        assert r.returncode == 0, f"--quick must not block:\n{r.stdout}\n{r.stderr}"
        assert "几何/视觉硬闸未跑" in r.stderr, \
            f"--quick must LOUDLY warn the hard gate skipped:\n{r.stderr}"
        line = _gate_coverage_line(r.stderr)
        assert line is not None
        assert "visual=skipped(--quick)" in line, f"coverage must record --quick skip:\n{line}"


# --------------------------------------------------------------------------
# 4. real (runs/) render with error-level visual defects BLOCKS; escape passes
# --------------------------------------------------------------------------
@pytest.mark.skipif(not HAVE_PW, reason="Playwright/Chromium unavailable")
def test_runs_render_blocks_on_error_level_visual_defect():
    with tempfile.TemporaryDirectory() as td:
        deck = _write_floor_deck(td)
        out = _runs_output(td)
        r = _render(deck, out)
        assert r.returncode == 4, \
            f"runs/ render with an error-level R-VIS defect must BLOCK (return 4):\n{r.stdout}\n{r.stderr}"
        assert "BLOCKING" in r.stderr
        line = _gate_coverage_line(r.stderr)
        assert line and "visual=ran" in line, f"gate should have RUN on a runs/ path:\n{line}"


@pytest.mark.skipif(not HAVE_PW, reason="Playwright/Chromium unavailable")
def test_runs_render_vis_errors_escape_hatch_lets_through():
    with tempfile.TemporaryDirectory() as td:
        deck = _write_floor_deck(td)
        out = _runs_output(td)
        r = _render(deck, out, env={"DECK_ALLOW_VIS_ERRORS": "1"})
        assert r.returncode == 0, \
            f"DECK_ALLOW_VIS_ERRORS=1 must let a known-visual-error deck through:\n{r.stdout}\n{r.stderr}"


# --------------------------------------------------------------------------
# 5. F-255 core: engine-down on a runs/ render is a LOUD BLOCK, not silent pass
#    (force the engine down with a bogus Playwright browsers path)
# --------------------------------------------------------------------------
@pytest.mark.skipif(not HAVE_PW, reason="Playwright/Chromium unavailable")
def test_runs_render_blocks_when_engine_down():
    with tempfile.TemporaryDirectory() as td:
        out = _runs_output(td)
        # A non-existent browsers path makes Chromium unlaunchable → validate.py
        # degrades to the R-VISUAL soft warning (engine-down signal), exit 0.
        env = {"PLAYWRIGHT_BROWSERS_PATH": str(pathlib.Path(td) / "no-such-browsers")}
        r = _render(EXAMPLE, out, env=env)
        assert r.returncode == 4, \
            f"engine-down on a runs/ render must BLOCK (UNVERIFIED quality), not pass:\n{r.stdout}\n{r.stderr}"
        assert "could not run" in r.stderr, f"expected loud engine-down notice:\n{r.stderr}"
        line = _gate_coverage_line(r.stderr)
        assert line and "FAILED(no-playwright)" in line, \
            f"coverage must record the engine FAILED:\n{line}"


@pytest.mark.skipif(not HAVE_PW, reason="Playwright/Chromium unavailable")
def test_runs_render_no_visual_escape_hatch_lets_through():
    with tempfile.TemporaryDirectory() as td:
        out = _runs_output(td)
        env = {
            "PLAYWRIGHT_BROWSERS_PATH": str(pathlib.Path(td) / "no-such-browsers"),
            "DECK_ALLOW_NO_VISUAL": "1",
        }
        r = _render(EXAMPLE, out, env=env)
        assert r.returncode == 0, \
            f"DECK_ALLOW_NO_VISUAL=1 must let an engine-down runs/ render through:\n{r.stdout}\n{r.stderr}"


# --------------------------------------------------------------------------
# 6. engine-down on a NON-runs/ path stays SOFT (advisory), never blocks
# --------------------------------------------------------------------------
@pytest.mark.skipif(not HAVE_PW, reason="Playwright/Chromium unavailable")
def test_tmp_render_engine_down_stays_soft():
    with tempfile.TemporaryDirectory() as td:
        env = {"PLAYWRIGHT_BROWSERS_PATH": str(pathlib.Path(td) / "no-such-browsers")}
        r = _render(EXAMPLE, td, env=env)
        assert r.returncode == 0, \
            f"engine-down on a /tmp (non-runs/) render must stay soft:\n{r.stdout}\n{r.stderr}"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
