"""Regression: `deck-cli paste` must not choke on a slide carrying a large
inline `data:` URI (base64 image).

History: a single ~370KB inline-base64 photo hung `paste` for ~3.5 min at 100%
CPU. Root cause was the media-ref scan in `_copy_slide_assets`: the unbounded
`[^\\s"'<>()\\\\?#]+\\.<ext>` pattern greedily ate the whole base64 run, then
backtracked character-by-character (O(n^2)) looking for a `.png`/`.jpg` that
never came. Fix: collapse `data:` URIs in `_slide_asset_text` before the scan
(they are never copyable assets) + bound the media-ref quantifier as a backstop.

This test pastes a slide whose data.html holds a ~400KB inline base64 run and
asserts the command RETURNS WELL UNDER a generous wall-clock bound. The bound is
30s — three orders of magnitude above the fixed path (sub-second) and far below
the >210s regression — so it is decisive without being flaky.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parents[1]
DECK_CLI = SKILL_ROOT / "deck-json" / "deck-cli.py"

# ~400KB of base64-alphabet chars (no '.', no delimiter) — the pathological run.
_BIG_B64 = ("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
            * 6400)  # 64 * 6400 = 409,600 chars


class PasteBase64NoChokeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="paste-b64-"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, name, deck):
        p = self.tmp / name
        p.write_text(json.dumps(deck), encoding="utf-8")
        return p

    def test_paste_with_large_inline_base64_does_not_hang(self):
        src = self._write("src.json", {
            "framework_version": "2025.1",
            "slides": [{
                "key": "bigimg",
                "layout": "raw",
                "data": {"html":
                    '<div class="bigimg"><img src="data:image/jpeg;base64,'
                    + _BIG_B64 + '" alt="big"></div>'},
            }],
        })
        target = self._write("target.json", {
            "framework_version": "2025.1",
            "slides": [{"key": "seed", "layout": "raw",
                        "data": {"html": "<div>seed</div>"}}],
        })

        try:
            proc = subprocess.run(
                [sys.executable, str(DECK_CLI), "--yes", str(target),
                 "paste", "--from", str(src), "--key", "bigimg"],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            self.fail("paste hung on a large inline base64 image "
                      "(the >210s catastrophic-backtracking regression is back)")

        # The asset-scan (the part that used to hang) must have run to completion.
        # We don't assert lint success — only that paste reached its copy stage
        # quickly. The combined stdout/stderr should mention the paste outcome.
        combined = proc.stdout + proc.stderr
        self.assertIn("bigimg", combined,
                      f"paste did not reach copy stage; output:\n{combined}")


if __name__ == "__main__":
    unittest.main()
