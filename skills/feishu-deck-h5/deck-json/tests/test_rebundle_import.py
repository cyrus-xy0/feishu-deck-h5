"""rebundle-import.py — re-bundle a raw deck with the current framework runtime.

The SAFE path for an imported/raw deck: stamp the imported origin marker + swap
in the current feishu-deck.js (so the runtime auto-balance is actually present —
the root cause R-AUTOBALANCE-PRESENT now gates). Tests the linked-mode swap +
the meta stamp + non-destructive default output.
"""
import sys
import subprocess
import tempfile
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOL = ROOT / "assets" / "rebundle-import.py"
CUR_JS = ROOT / "assets" / "feishu-deck.js"


def _has_chromium_independent():
    return TOOL.exists() and CUR_JS.exists()


def test_linked_swap_and_stamp_inplace():
    if not _has_chromium_independent():
        import pytest; pytest.skip("tool/runtime missing")
    with tempfile.TemporaryDirectory() as d:
        dd = pathlib.Path(d)
        (dd / "assets").mkdir()
        # OLD runtime (no auto-balance) + a LINKED <script src>
        (dd / "assets" / "feishu-deck.js").write_text("/* old runtime, no balanceSlide */\n")
        deck = dd / "index.html"
        deck.write_text(
            '<html><head></head><body><div class="deck">'
            '<div class="slide-frame"><div class="slide"></div></div></div>'
            '<script src="assets/feishu-deck.js"></script></body></html>')

        r = subprocess.run([sys.executable, str(TOOL), str(deck), "--inplace"],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, f"tool failed: {r.stderr}\n{r.stdout}"

        html = deck.read_text()
        # imported origin stamped
        assert 'fs-deck-origin' in html and 'imported' in html, "imported meta not stamped"
        # the deck's linked JS now carries the current runtime's balanceSlide fingerprint
        swapped = (dd / "assets" / "feishu-deck.js").read_text()
        assert "function balanceSlide(slide)" in swapped, "current runtime not swapped in"


def test_default_is_non_destructive():
    if not _has_chromium_independent():
        import pytest; pytest.skip("tool/runtime missing")
    with tempfile.TemporaryDirectory() as d:
        dd = pathlib.Path(d)
        (dd / "assets").mkdir()
        (dd / "assets" / "feishu-deck.js").write_text("/* old */\n")
        deck = dd / "index.html"
        original = ('<html><head></head><body><div class="deck">'
                    '<div class="slide-frame"><div class="slide"></div></div></div>'
                    '<script src="assets/feishu-deck.js"></script></body></html>')
        deck.write_text(original)
        r = subprocess.run([sys.executable, str(TOOL), str(deck)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        # original untouched; a *-rebundled.html written instead
        assert deck.read_text() == original, "default run must NOT touch the original"
        assert (dd / "index-rebundled.html").exists(), "expected non-destructive -rebundled.html"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  ok  {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL  {fn.__name__}"); traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
