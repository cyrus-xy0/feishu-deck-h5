"""F-283 step 1 · CJK font-fingerprint (DIAGNOSTIC, not a rule).

The framework's CJK face (方正兰亭黑 Pro GB18030) is a LOCALLY-LICENSED font with
NO @font-face / NO bundling. Every visual-audit geometry number (overflow /
balance / title-position) is therefore measured against THIS host's glyph
metrics — so the same deck verdict can silently differ across machines that have
a different CJK face. Step 1 makes the actually-rendered face VISIBLE; it changes
no gate and emits no finding. These tests lock the diagnostic CONTRACT:

  1. validate.py --json ALWAYS carries an `effective_cjk_font` field (both the
     visual and the --no-visual paths), so a cross-machine verdict is always
     self-stamped with the face geometry was measured against.
  2. The --no-visual path reports the honest no-engine sentinel WITHOUT launching
     Chromium (cheap, deterministic).
  3. probe_effective_cjk_font NEVER raises and, when an engine is available,
     returns a family that is actually a member of the framework CJK cascade
     (--fs-font-cjk in feishu-deck.css) — i.e. a real face the browser would
     paint, not garbage.
  4. preflight.sh / check-mira.sh surface a CJK-font CAPABILITY line and stay
     non-fatal (the probe never changes their exit code).

Engine-dependent assertions skip (not fail) when Chromium is unavailable, the
same graceful-degrade contract as the sibling visual tests.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parents[1]
ASSETS = SKILL_ROOT / "assets"
sys.path.insert(0, str(ASSETS))
sys.path.insert(0, str(HERE))

import validate as V  # noqa: E402

SAMPLE_DECK = SKILL_ROOT / "examples" / "sample-deck.html"
CSS = ASSETS / "feishu-deck.css"
PREFLIGHT = ASSETS / "preflight.sh"
CHECK_MIRA = ASSETS / "check-mira.sh"


# --------------------------------------------------------------------------- #
#  helpers
# --------------------------------------------------------------------------- #
def _has_engine() -> bool:
    """True when Playwright + a launchable Chromium are present."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(headless=True)
            b.close()
        return True
    except Exception:
        return False


def _cjk_stack_names() -> list[str]:
    """The CJK family names declared in feishu-deck.css's --fs-font-cjk, in
    cascade order, quotes/whitespace stripped. The SAME single source of truth
    the probe and the shell capability checks read."""
    text = CSS.read_text(encoding="utf-8")
    m = re.search(r"--fs-font-cjk:\s*(.+?);", text, re.DOTALL)
    assert m, "could not find --fs-font-cjk in feishu-deck.css"
    return [n.strip().strip('"').strip()
            for n in m.group(1).split(",") if n.strip()]


def _run_validate_json(*flags: str) -> dict:
    """Run validate.py on the sample deck and return the parsed --json payload."""
    out = subprocess.run(
        [sys.executable, str(ASSETS / "validate.py"), str(SAMPLE_DECK),
         "--json", *flags],
        capture_output=True, text=True, timeout=240)
    # --json prints the blob to stdout; non-zero exit just means the deck had
    # findings (we only care about the payload shape here).
    return json.loads(out.stdout)


# --------------------------------------------------------------------------- #
#  surface / contract
# --------------------------------------------------------------------------- #
def test_probe_symbol_is_public():
    """The probe + its sentinel are part of validate.py's surface so downstream
    tools (render-deck / cross-machine diffing) can call them."""
    assert hasattr(V, "probe_effective_cjk_font")
    assert hasattr(V, "_CJK_FONT_UNKNOWN")
    assert isinstance(V._CJK_FONT_UNKNOWN, str) and V._CJK_FONT_UNKNOWN


def test_probe_never_raises_and_returns_str_or_none():
    """A probe failure must never break validation — it is metadata, not a gate.
    Whatever the environment, the call returns a str (a family or the sentinel)
    or None, but does NOT propagate an exception."""
    if not SAMPLE_DECK.is_file():
        import pytest
        pytest.skip("examples/sample-deck.html not built (bash build.sh)")
    result = V.probe_effective_cjk_font(SAMPLE_DECK)
    assert result is None or isinstance(result, str)


def test_probe_missing_playwright_returns_sentinel(monkeypatch):
    """When Playwright cannot be imported, the probe degrades to the no-engine
    sentinel string rather than crashing or returning a misleading family."""
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
        else __builtins__.__import__

    def _blocked(name, *a, **k):
        if name == "playwright" or name.startswith("playwright."):
            raise ImportError("blocked for test")
        return real_import(name, *a, **k)

    monkeypatch.setitem(
        sys.modules, "playwright", None)  # force the import inside to miss
    # Also block re-import via the import machinery.
    import builtins
    monkeypatch.setattr(builtins, "__import__", _blocked)
    result = V.probe_effective_cjk_font(SAMPLE_DECK if SAMPLE_DECK.is_file()
                                        else CSS)
    assert result == V._CJK_FONT_UNKNOWN


# --------------------------------------------------------------------------- #
#  --json payload field (the cross-machine fingerprint)
# --------------------------------------------------------------------------- #
def test_json_payload_always_has_effective_cjk_font_no_visual():
    """--no-visual is cheap + deterministic: it must still emit the field (so the
    contract holds on CI-without-Chromium) and report the no-engine sentinel
    (honest: nothing was measured), WITHOUT launching a browser."""
    if not SAMPLE_DECK.is_file():
        import pytest
        pytest.skip("examples/sample-deck.html not built (bash build.sh)")
    payload = _run_validate_json("--no-visual")
    assert "effective_cjk_font" in payload, \
        "json payload must carry effective_cjk_font even on --no-visual"
    assert payload["effective_cjk_font"] == V._CJK_FONT_UNKNOWN


def test_json_payload_visual_reports_a_real_cascade_member():
    """On the visual path the field must be a family the browser actually paints
    — i.e. a member of the framework CJK cascade (or the no-engine sentinel if
    Chromium flaked). Never garbage, never absent."""
    if not SAMPLE_DECK.is_file():
        import pytest
        pytest.skip("examples/sample-deck.html not built (bash build.sh)")
    if not _has_engine():
        import pytest
        pytest.skip("Chromium engine unavailable")
    payload = _run_validate_json("--visual")
    assert "effective_cjk_font" in payload
    eff = payload["effective_cjk_font"]
    assert eff and isinstance(eff, str)
    if eff == V._CJK_FONT_UNKNOWN:
        return  # engine flaked mid-run — acceptable, still a valid sentinel
    stack = _cjk_stack_names()
    assert eff in stack, (
        f"effective_cjk_font {eff!r} is not a member of the --fs-font-cjk "
        f"cascade {stack!r} — the probe returned something off-cascade")


# --------------------------------------------------------------------------- #
#  shell capability lines (preflight + check-mira)
# --------------------------------------------------------------------------- #
def test_preflight_emits_cjk_font_capability_and_stays_zero():
    """preflight.sh must print a `CAPABILITY cjk-font:` line and NOT change its
    exit code because of the font probe (it is diagnostic, non-fatal)."""
    proc = subprocess.run(["bash", str(PREFLIGHT)],
                          capture_output=True, text=True, timeout=120)
    assert "CAPABILITY cjk-font:" in proc.stdout, \
        f"preflight.sh did not emit the cjk-font capability line:\n{proc.stdout}"
    # On a normal local clone preflight exits 0 (writable mount). The font probe
    # must never be the reason it isn't.
    assert proc.returncode == 0, \
        f"preflight exited {proc.returncode} (font probe must stay non-fatal)\n{proc.stdout}"


def test_check_mira_emits_preferred_cjk_line():
    """check-mira.sh's container-readiness check must surface the PREFERRED CJK
    face specifically (not just 'any CJK font'), so a host that has Noto but not
    the master font is flagged as a geometry-divergence risk."""
    proc = subprocess.run(["bash", str(CHECK_MIRA)],
                          capture_output=True, text=True, timeout=120)
    assert "preferred CJK face" in proc.stdout, \
        f"check-mira.sh did not emit the preferred-CJK line:\n{proc.stdout[-2000:]}"


def test_shell_probe_reads_font_names_from_css():
    """Both shell probes must read the CJK names from the CSS (single source of
    truth), so the capability stays in sync with --fs-font-cjk. Guard against a
    future refactor hard-coding the list in the shell instead."""
    for script in (PREFLIGHT, CHECK_MIRA):
        body = script.read_text(encoding="utf-8")
        assert "--fs-font-cjk" in body, \
            f"{script.name} should derive CJK names from feishu-deck.css's " \
            "--fs-font-cjk, not hard-code them"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            # crude monkeypatch shim for __main__ runs (pytest provides the real one)
            if "monkeypatch" in fn.__code__.co_varnames:
                print(f"SKIP  {fn.__name__} (needs pytest monkeypatch)")
                continue
            fn()
            print(f"  ok  {fn.__name__}")
        except Exception as e:  # noqa: BLE001
            if e.__class__.__name__ == "Skipped":
                print(f"SKIP  {fn.__name__}: {e}")
                continue
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed} passed/skipped, {failed} failed")
    sys.exit(1 if failed else 0)
