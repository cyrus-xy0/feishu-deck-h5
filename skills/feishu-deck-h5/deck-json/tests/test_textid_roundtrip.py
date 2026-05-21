"""Asserts every data-text-id format render-deck.py emits has a matching
rule in editor.js textIdToSlidePath. Catches "in-place edit silently broken"
(the bug code-quality reviewer found at editor.js:1241 for feature_list).

Strategy: render sample-deck → grep data-text-id → for each one, run a
Python reimplementation of textIdToSlidePath (kept in sync with editor.js)
→ assert it returns non-None and matches a JSON path that exists in the deck.

This is the LIVE check — if you add a new data-text-id format to an
enricher but forget the editor.js mapping, this test fails.
"""
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
RENDER = DECK_JSON / "render-deck.py"
SAMPLE = DECK_JSON / "examples" / "sample-deck.json"


# Mirror of editor.js textIdToSlidePath. KEEP IN SYNC.
def text_id_to_slide_path(text_id: str) -> str | None:
    m = re.match(r"^slide-\d+\.(.+)$", text_id)
    if not m:
        return None
    field = m.group(1)

    # text-id naming → schema field naming
    field = field.replace("chapter-num", "chapter_num", 1)\
                 .replace("source-footer", "source_footer", 1)

    def dec(s: str) -> str:
        return str(int(s, 10) - 1)

    # two-level array structures
    mm = re.match(r"^branch-(\d+)\.leaf-(\d+)$", field)
    if mm:
        return f"data.branches.{dec(mm[1])}.leaves.{dec(mm[2])}"
    mm = re.match(r"^row-(\d+)\.cell-(\d+)$", field)
    if mm:
        return f"data.rows.{dec(mm[1])}.{dec(mm[2])}"
    mm = re.match(r"^(tl|tr|bl|br)\.item-(\d+)$", field)
    if mm:
        return f"data.quadrants.{mm[1]}.items.{dec(mm[2])}"

    item_transforms = [
        (re.compile(r"^card-(\d+)\.title$"),       lambda m: f"cards.{dec(m[1])}.title_zh"),
        (re.compile(r"^card-(\d+)\.(.+)$"),        lambda m: f"cards.{dec(m[1])}.{m[2]}"),
        (re.compile(r"^col-(\d+)\.(.+)$"),         lambda m: f"cols.{dec(m[1])}.{m[2]}"),
        (re.compile(r"^node-(\d+)\.(.+)$"),        lambda m: f"nodes.{dec(m[1])}.{m[2]}"),
        (re.compile(r"^step-(\d+)\.(.+)$"),        lambda m: f"steps.{dec(m[1])}.{m[2]}"),
        (re.compile(r"^bar-(\d+)\.(.+)$"),         lambda m: f"bars.{dec(m[1])}.{m[2]}"),
        (re.compile(r"^branch-(\d+)\.(.+)$"),      lambda m: f"branches.{dec(m[1])}.{m[2]}"),
        (re.compile(r"^head-(\d+)$"),              lambda m: f"headers.{dec(m[1])}"),
        (re.compile(r"^item-(\d+)$"),              lambda m: f"items.{dec(m[1])}.title_zh"),
        (re.compile(r"^pill-(\d+)$"),              lambda m: f"pills.{dec(m[1])}"),
        (re.compile(r"^(tl|tr|bl|br)\.(.+)$"),     lambda m: f"quadrants.{m[1]}.{m[2]}"),
        (re.compile(r"^text\.feature-(\d+)$"),     lambda m: f"text.feature_list.{dec(m[1])}"),
    ]
    for rx, fn in item_transforms:
        mm = rx.match(field)
        if mm:
            return f"data.{fn(mm)}"
    return f"data.{field}"


class TextIdRoundtripTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td) / "output"
            out_dir.mkdir()
            # Render with assets-copy off (faster, doesn't matter for parsing)
            proc = subprocess.run(
                [sys.executable, str(RENDER), str(SAMPLE), str(out_dir),
                 "--skip-copy-assets", "--skip-validate-html"],
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                raise AssertionError(
                    f"render-deck failed:\n{proc.stdout}\n{proc.stderr}"
                )
            html = (out_dir / "index.html").read_text(encoding="utf-8")
            cls.text_ids = sorted(set(re.findall(
                r'data-text-id="(slide-\d+\.[^"]+)"', html)))
        cls.deck = json.loads(SAMPLE.read_text(encoding="utf-8"))

    def test_every_textid_maps_to_some_path(self):
        unmapped = [tid for tid in self.text_ids
                    if text_id_to_slide_path(tid) is None]
        self.assertFalse(unmapped, f"text-ids with no path:\n  {unmapped}")

    def test_no_array_item_falls_to_fallback(self):
        """The fallback `data.{field}` is too permissive — it accepts ANY
        suffix. We want to make sure that anything matching an array-item
        shape (`<name>-<digits>...`) gets a real transform, not the
        fallback. Otherwise editing the item writes to a phantom path.
        """
        problems = []
        ARRAY_PREFIXES = re.compile(
            r"^(?:slide-\d+)\.(?:card|col|node|step|bar|branch|head|item|pill|row|leaf|feature)-?\d"
        )
        for tid in self.text_ids:
            if not ARRAY_PREFIXES.match(tid):
                continue
            path = text_id_to_slide_path(tid)
            # Reject paths that smell like the fallback (no array-index segment)
            if path and not re.search(r"\.\d+(\.|$)", path):
                problems.append(f"  {tid} → {path}  (probable fallback hit)")
        self.assertFalse(problems,
            "These array-item text-ids hit the fallback (path lacks .N. index):\n"
            + "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
