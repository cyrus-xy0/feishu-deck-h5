"""CLI contract for capture-frames interaction-state verification."""
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
CAPTURE = HERE.parents[1] / "assets" / "capture-frames.py"


def test_help_exposes_interaction_capture_flags():
    result = subprocess.run([sys.executable, str(CAPTURE), "-h"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "--click-selector" in result.stdout
    assert "--close-selector" in result.stdout
    assert "--click-wait-ms" in result.stdout


def test_close_selector_requires_click_selector(tmp_path):
    html = tmp_path / "index.html"
    html.write_text("<!doctype html>", encoding="utf-8")
    result = subprocess.run([
        sys.executable, str(CAPTURE), str(html), "one",
        "--close-selector", ".close",
    ], capture_output=True, text=True)
    assert result.returncode == 2
    assert "requires --click-selector" in result.stderr


def test_click_and_close_capture_interaction_states(tmp_path):
    html = tmp_path / "index.html"
    html.write_text("""<!doctype html>
      <html data-deck-width="1920" data-deck-height="1080"><head><style>
        html,body{margin:0;width:100%;height:100%}
        .slide{position:relative;width:1920px;height:1080px;overflow:hidden}
        .modal{display:none;position:absolute;inset:100px;background:#fff}
        #qr:checked ~ .modal{display:block}
      </style></head><body>
        <div class="slide-frame is-current"><div class="slide" data-slide-key="one">
          <input id="qr" type="checkbox" hidden>
          <label class="trigger" for="qr" role="button">open</label>
          <div class="modal"><label class="close" for="qr" role="button">close</label></div>
        </div></div>
      </body></html>""", encoding="utf-8")
    result = subprocess.run([
        sys.executable, str(CAPTURE), str(html), "one",
        "--mid-ms", "0", "--settle-ms", "0", "--click-wait-ms", "0",
        "--out-dir", str(tmp_path),
        "--click-selector", ".trigger", "--close-selector", ".close",
    ], capture_output=True, text=True)
    unavailable_browser = (
        result.returncode == 2
        and ("browser unavailable" in result.stderr
             or "playwright install chromium" in result.stderr)
    )
    if unavailable_browser:
        pytest.skip("Playwright Chromium is not installed")
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "one_clicked.png").exists()
    assert (tmp_path / "one_closed.png").exists()
    assert '"error": null' in result.stdout
