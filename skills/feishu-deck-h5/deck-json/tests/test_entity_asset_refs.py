"""F-333 unit guards: every asset-path scanner that feeds a destructive (prune /
delete) or lossy (copy / inline / upload) consumer must extract the CLEAN path
from an inline-style background whose quotes are HTML-entity-encoded
(`url(&quot;input/x.png&quot;)` / `&#34;` / `&apos;` / `&#39;`).

Before F-333 these scanners over-captured the trailing `&quot;` (so the real file
was treated as unreferenced and pruned) or failed to match at all (so the asset
was never copied/inlined). See docs/F-333-ENTITY-URL-ASSET-PRUNE-2026-06-16.md.
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SKILL_ROOT = HERE.parents[1]


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, SKILL_ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ENT = 'url(&quot;input/x.png&quot;)'


class CopyAssetsRegexEntityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ca = _load("assets/copy-assets.py", "_ca_f333")

    def test_rx_input_stops_at_entity(self):
        self.assertEqual(self.ca.RX_INPUT.search(ENT).group(2), "x.png")

    def test_rx_local_input_stops_at_entity(self):
        self.assertEqual(self.ca.RX_LOCAL_INPUT.search(ENT).group(2), "x.png")

    def test_rx_skill_stops_at_entity(self):
        m = self.ca.RX_SKILL.search(
            'url(&quot;../../../skills/feishu-deck-h5/assets/clientlogo/x.png&quot;)')
        self.assertEqual(m.group(3), "clientlogo/x.png")

    def test_numeric_and_apos_entities(self):
        self.assertEqual(self.ca.RX_INPUT.search('url(&#34;input/y.png&#34;)').group(2), "y.png")
        self.assertEqual(self.ca.RX_INPUT.search("url(&#39;input/z.png&#39;)").group(2), "z.png")

    def test_literal_and_bare_forms_unaffected(self):
        # regression: previously-working quote forms still capture the clean path
        self.assertEqual(self.ca.RX_INPUT.search('url("input/k.png")').group(2), "k.png")
        self.assertEqual(self.ca.RX_INPUT.search("url(input/k.png)").group(2), "k.png")
        self.assertEqual(self.ca.RX_INPUT.search("url('input/k.png')").group(2), "k.png")

    def test_literal_ampersand_filename_not_truncated(self):
        # ADVERSARIAL regression: the entity boundary must NOT cut a literal '&' (or
        # ';') inside a real filename — else the file is mis-tracked and pruned. Only
        # a '&' that begins a quote-entity terminates the capture.
        self.assertEqual(self.ca.RX_INPUT.search('url("input/Q&A.png")').group(2), "Q&A.png")
        self.assertEqual(self.ca.RX_INPUT.search('url(&quot;input/Q&A.png&quot;)').group(2), "Q&A.png")
        self.assertEqual(self.ca.RX_INPUT.search('url("input/a;b.png")').group(2), "a;b.png")
        self.assertEqual(self.ca.RX_LOCAL_INPUT.search('url("input/R&D.png")').group(2), "R&D.png")
        self.assertEqual(
            self.ca.RX_SKILL.search(
                'url("../../../skills/feishu-deck-h5/assets/AT&T.png")').group(3), "AT&T.png")


class RenderDeckScanEntityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rd = _load("deck-json/render-deck.py", "_rd_f333")

    def test_scan_slide_assets_strips_entity_quotes(self):
        got = self.rd._scan_slide_assets(
            '<div style="background:url(&quot;input/a.png&quot;)"></div> <img src="input/b.png">')
        self.assertEqual(got, ["input/a.png", "input/b.png"])

    def test_scan_slide_assets_keeps_literal_ampersand(self):
        # ADVERSARIAL regression: a literal '&' in a filename is part of the manifest
        # path (else a lift of this slide 404s its image).
        got = self.rd._scan_slide_assets(
            '<div style="background:url(&quot;input/a.png&quot;)"></div> <img src="input/R&D.png">')
        self.assertEqual(got, ["input/R&D.png", "input/a.png"])

    def test_resolve_bg_inlines_entity_encoded_ref(self):
        d = Path(tempfile.mkdtemp())
        (d / "input").mkdir()
        (d / "input" / "x.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 40)
        out = d / "index.html"
        out.write_text("x", encoding="utf-8")
        # entity-encoded ref resolves to a data: URI (not left external / missing)
        self.assertTrue(self.rd._resolve_bg(out, "&quot;input/x.png&quot;").startswith("'data:"))
        # regression: a clean ref still inlines
        self.assertTrue(self.rd._resolve_bg(out, "input/x.png").startswith("'data:"))

    def test_resolve_bg_leaves_external_and_fragment_untouched(self):
        # ADVERSARIAL regression (issue 5): the gated unescape must NOT decode
        # entities inside an external/data ref, and fragments stay bare (F-270).
        d = Path(tempfile.mkdtemp())
        out = d / "index.html"
        out.write_text("x", encoding="utf-8")
        self.assertIn("&amp;", self.rd._resolve_bg(out, "data:image/svg+xml,<svg>x=1&amp;y</svg>"))
        self.assertIn("&quot;", self.rd._resolve_bg(out, 'data:image/svg+xml,<text a="&quot;b&quot;"/>'))
        self.assertIn("&amp;copy;", self.rd._resolve_bg(out, "https://x.com/a.png?x=1&amp;copy;y"))
        self.assertEqual(self.rd._resolve_bg(out, "#noise"), "#noise")


class StripRefEntityTest(unittest.TestCase):
    def test_inline_assets_strip_ref(self):
        ia = _load("assets/inline-assets.py", "_ia_f333")
        self.assertEqual(ia.strip_ref("&quot;input/x.png&quot;"), "input/x.png")
        self.assertEqual(ia.strip_ref("input/x.png"), "input/x.png")          # clean
        self.assertEqual(ia.strip_ref("input/x.png?v=2#frag"), "input/x.png")  # query/frag still stripped
        # ADVERSARIAL (issue 3): a genuine CSS filename carrying some OTHER named
        # entity is NOT decoded (gate only fires on a quote-entity wrapper).
        self.assertEqual(ia.strip_ref("input/a&copy;b.png"), "input/a&copy;b.png")

    def test_magic_page_strip_ref(self):
        mp = _load("assets/magic-page-assets.py", "_mp_f333")
        self.assertEqual(mp.strip_ref("&#34;input/x.png&#34;"), "input/x.png")
        self.assertEqual(mp.strip_ref("input/x.png"), "input/x.png")
        self.assertEqual(mp.strip_ref("input/a&copy;b.png"), "input/a&copy;b.png")


class LiftImportUrlPatternEntityTest(unittest.TestCase):
    """The lift/import url() pattern must tolerate an entity-quote OPENER (the
    &quot; sits between url( and the path, not just after it) and still capture the
    clean inner ref — which must remain a literal substring of the original so the
    downstream inner.replace(token, ...) rewrite round-trips."""

    def _pat(self, mod_rel, name):
        return _load(mod_rel, name)._ASSET_REF_PATTERNS[4]

    def test_lift_url_pattern(self):
        pat = self._pat("assets/lift-slides.py", "_ls_f333")
        self.assertEqual(pat.search('url(&quot;../input/x.png&quot;)').group(1), "../input/x.png")
        self.assertEqual(pat.search('url(&#34;../input/q.png&#34;)').group(1), "../input/q.png")
        self.assertEqual(pat.search('url("../input/r.png")').group(1), "../input/r.png")
        self.assertEqual(pat.search('url(../input/s.png)').group(1), "../input/s.png")
        self.assertEqual(pat.search("url('input/t.png')").group(1), "input/t.png")
        # ADVERSARIAL (issue 2/4): a literal '&' in the filename is captured, not dropped
        self.assertEqual(pat.search('url(input/x&y.png)').group(1), "input/x&y.png")
        self.assertEqual(pat.search('url(&quot;../input/Q&A.png&quot;)').group(1), "../input/Q&A.png")

    def test_import_url_pattern(self):
        pat = self._pat("deck-json/import-html-slide.py", "_ih_f333")
        self.assertEqual(pat.search('url(&quot;input/x.png&quot;)').group(1), "input/x.png")
        self.assertEqual(pat.search('url("input/r.png")').group(1), "input/r.png")
        self.assertEqual(pat.search('url(input/s.png)').group(1), "input/s.png")
        self.assertEqual(pat.search('url(input/x&y.png)').group(1), "input/x&y.png")

    def test_lift_captured_ref_round_trips(self):
        ls = _load("assets/lift-slides.py", "_ls2_f333")
        original = 'url(&quot;../input/x.png&quot;)'
        cap = ls._ASSET_REF_PATTERNS[4].search(original).group(1)
        self.assertTrue(ls._REL_INPUT_RE.match(cap))     # classifies as rel-input
        self.assertIn(cap, original)                     # literal substring → replace works


if __name__ == "__main__":
    unittest.main()
