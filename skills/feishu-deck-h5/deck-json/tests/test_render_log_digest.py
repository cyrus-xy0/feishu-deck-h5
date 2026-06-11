"""W2 (iteration-loop) · last-render.log + render digest.

Contract:
  1. Every render writes its FULL combined output (stdout + stderr — the gate
     sections print to stderr) to <output_dir>/last-render.log, overwritten
     per run, so a BLOCKED render never needs a re-run just to re-read ❌.
  2. After main() returns, a compact digest is printed to the REAL stdout:
     verdict + one line per unique error finding + the log path.
  3. Digest survives the caller discarding stderr (2>/dev/null equivalent).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
RENDER = DECK_JSON / "render-deck.py"
DEMO = DECK_JSON / "examples" / "phase-1a-demo.json"


def _render(deck_path: Path, out_dir: Path, env_extra=None):
    import os
    env = dict(os.environ)
    env["DECK_LOG_NO_AUTOSNAP"] = "1"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(RENDER), str(deck_path), str(out_dir) + "/"],
        capture_output=True, text=True, env=env,
    )


def test_pass_render_writes_log_and_digest(tmp_path):
    out = tmp_path / "out"
    r = _render(DEMO, out)
    assert r.returncode == 0, r.stdout + r.stderr
    log = out / "last-render.log"
    assert log.exists(), "last-render.log must be written on every render"
    assert "──── render digest ────" in r.stdout
    assert "✔ PASS" in r.stdout
    assert "0 error(s)" in r.stdout
    # digest also appended into the log itself
    assert "render digest" in log.read_text(encoding="utf-8")


def test_blocked_render_digest_extracts_errors_even_without_stderr(tmp_path):
    # runs/<ts>/output path → real delivery render → visual gate active
    out = tmp_path / "runs" / "20260611-000000-w2digest" / "output"
    out.mkdir(parents=True)
    d = json.loads(DEMO.read_text(encoding="utf-8"))
    d["slides"] = [d["slides"][0], {
        "key": "badvis", "layout": "raw", "screen_label": "02 BadVis",
        "data": {"html":
            '<div class="header"><h2 class="title-zh">Visual gate test</h2></div>'
            '<div class="stage"><p style="font-size:20px">This body copy is twenty '
            'pixels which is below the floor and not on the ladder at all.</p></div>'},
    }]
    deck = out / "deck.json"
    deck.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    r = _render(deck, out)
    assert r.returncode == 4, "visual-gate block must exit 4"
    # stdout digest alone (stderr ignored!) names the rule + slide
    assert "✗ BLOCKED" in r.stdout
    assert "[R-VIS-" in r.stdout, "digest must list the blocking findings"
    # full detail is in the log: gate sections (printed to stderr) captured too
    log_text = (out / "last-render.log").read_text(encoding="utf-8")
    assert "❌ BLOCKING" in log_text
    assert "GATE-COVERAGE" in log_text


def test_log_overwritten_per_run(tmp_path):
    out = tmp_path / "out"
    r1 = _render(DEMO, out)
    assert r1.returncode == 0
    size1 = (out / "last-render.log").stat().st_size
    r2 = _render(DEMO, out)
    assert r2.returncode == 0
    size2 = (out / "last-render.log").stat().st_size
    # overwrite, not append: second run's log is same order of magnitude
    assert size2 < size1 * 2
