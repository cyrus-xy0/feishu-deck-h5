"""F-07: golden-snapshot test for render-deck.py output.

18+ enrichers hand-build HTML; only downstream validate.py incidentally caught
markup regressions. This locks the enricher HTML contract: render a stable
example deck, normalize the one machine-specific bit (the skill-root path
prefix in asset href/src — everything else is deterministic), and diff against
a committed snapshot. Any intentional enricher change shows up as an explicit
snapshot diff; regenerate with FS_UPDATE_SNAPSHOTS=1 and review.

Linked mode is used on purpose (not --inline): the snapshot then captures only
the generated MARKUP, so editing framework CSS/JS does NOT churn it.
"""
import os
import re
import subprocess
import sys
import tempfile
import pathlib

DECK_JSON = pathlib.Path(__file__).resolve().parents[1]
RENDER = DECK_JSON / "render-deck.py"
EXAMPLE = DECK_JSON / "examples" / "sample-deck.json"
SNAP_DIR = pathlib.Path(__file__).resolve().parent / "__snapshots__"
SNAP = SNAP_DIR / "sample-deck.index.html"


def _normalize(html: str) -> str:
    # Strip the machine-specific path that precedes the skill root in linked
    # asset refs → a stable token. Everything else (markup, data-text-ids,
    # deck.json-sourced dates) is deterministic.
    html = re.sub(r'((?:href|src)=")[^"]*?skills/feishu-deck-h5/',
                  r'\1SKILL/', html)
    return html


def _render_normalized() -> str:
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run([sys.executable, str(RENDER), str(EXAMPLE), td + "/"],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"render failed:\n{r.stdout}\n{r.stderr}"
        out = pathlib.Path(td) / "index.html"
        assert out.is_file(), "render produced no index.html"
        return _normalize(out.read_text(encoding="utf-8"))


def test_render_output_matches_golden_snapshot():
    current = _render_normalized()
    # normalization must leave no machine-specific absolute path behind
    assert "/Users/" not in current and "/private/tmp/" not in current, \
        "normalization missed a machine-specific path"

    if os.environ.get("FS_UPDATE_SNAPSHOTS") or not SNAP.is_file():
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        SNAP.write_text(current, encoding="utf-8")
        if not os.environ.get("FS_UPDATE_SNAPSHOTS"):
            print(f"[golden] bootstrapped snapshot at {SNAP} — review & commit it")
        return

    expected = SNAP.read_text(encoding="utf-8")
    if current != expected:
        # compact unified diff for the failure message
        import difflib
        diff = "\n".join(difflib.unified_diff(
            expected.splitlines(), current.splitlines(),
            fromfile="snapshot", tofile="current", lineterm="", n=2))
        raise AssertionError(
            "render-deck output changed vs golden snapshot. If intentional, "
            "regenerate with FS_UPDATE_SNAPSHOTS=1 and review the diff:\n"
            + diff[:4000])


if __name__ == "__main__":
    test_render_output_matches_golden_snapshot()
    print("ok")
