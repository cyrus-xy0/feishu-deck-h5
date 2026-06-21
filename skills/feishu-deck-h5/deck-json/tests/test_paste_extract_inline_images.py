"""`deck-cli paste` lifts LARGE inline base64 images out of deck.json into
asset files (`assets/lift-<key>-<hash>.<ext>`) and rewrites the references —
keeping the pasted deck small (the P50 base64-in-fragment anti-pattern) — while
leaving tiny inline data: URIs (icons) alone.

Unit-tests `_extract_inline_images` directly (imported from the hyphenated
deck-cli.py via importlib) so the assertion does not depend on a lint-passing
target deck.
"""

import base64
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
DECK_CLI = HERE.parents[1] / "deck-json" / "deck-cli.py"
_spec = importlib.util.spec_from_file_location("deck_cli_mod", DECK_CLI)
deck_cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(deck_cli)


class ExtractInlineImagesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="extract-img-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_large_extracted_small_left_inline(self):
        big_bytes = b"\xff\xd8\xff\xe0" + b"PHOTODATA" * 4000   # ~36KB → extract
        big = base64.b64encode(big_bytes).decode()
        small = base64.b64encode(b"<svg/>").decode()            # tiny → keep inline
        slide = {
            "key": "x", "layout": "raw",
            # same image (same mime) referenced in BOTH css and html → one file
            "custom_css": f'.f{{background:url(data:image/jpeg;base64,{big})}}',
            "data": {"html":
                f'<img src="data:image/jpeg;base64,{big}">'
                f'<i style="background:url(data:image/svg+xml;base64,{small})"></i>'},
        }

        written = deck_cli._extract_inline_images(slide, self.tmp, "mykey")

        # The big image appears in html AND css as the SAME data: URI → deduped to
        # one asset file; the tiny inline svg stays inline (below threshold).
        self.assertEqual(len(written), 1, written)
        rel = written[0]
        self.assertRegex(rel, r"^assets/lift-mykey-[0-9a-f]{8}\.jpg$")
        self.assertTrue((self.tmp / rel).is_file())
        # bytes written verbatim (lossless — no re-encode)
        self.assertEqual((self.tmp / rel).read_bytes(), big_bytes)

        html, css = slide["data"]["html"], slide["custom_css"]
        # large data: URI gone from BOTH fields, replaced by the asset path
        self.assertNotIn(f"base64,{big}", html)
        self.assertNotIn(f"base64,{big}", css)
        self.assertIn(rel, html)
        self.assertIn(rel, css)
        # tiny icon left inline
        self.assertIn(f"base64,{small}", html)

    def test_no_inline_images_is_noop(self):
        slide = {"key": "y", "layout": "raw",
                 "data": {"html": '<img src="input/photo.jpg">'}}
        written = deck_cli._extract_inline_images(slide, self.tmp, "k")
        self.assertEqual(written, [])
        self.assertEqual(slide["data"]["html"], '<img src="input/photo.jpg">')


if __name__ == "__main__":
    unittest.main()
