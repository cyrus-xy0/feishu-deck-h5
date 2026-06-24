"""P0#2 · publish-bytes dependency scan must not false-positive on JS.

The Magic Page publish-bytes gate rejects any unhosted runtime dependency. Its
url()/@import scan historically ran over the WHOLE document including <script>
bodies, so JS that merely *mentions* url(), URL(), location.href or
createObjectURL was flagged as an "unhosted resource" — costing a manual
round-trip on every publish. These tests pin: JS mentions are ignored, real CSS
url() / resource attributes are still caught, and residual inline data: payloads
of any heavy media type are detected.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PUBLISH = REPO / "subskills/publisher/publish.py"


def _load_publish():
    spec = importlib.util.spec_from_file_location("publisher_publish", PUBLISH)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


P = _load_publish()


def _scan(html: str) -> list[str]:
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "x.html"
        f.write_text(html, encoding="utf-8")
        return P.remaining_unhosted_dependencies(f)


def _residual(html: str) -> list[str]:
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "x.html"
        f.write_text(html, encoding="utf-8")
        return P.residual_data_payloads(f)


class DependencyScanTest(unittest.TestCase):
    def test_js_url_mentions_are_not_flagged(self) -> None:
        html = """
        <script>
          const a = `url(${x})`;
          const u = new URL(location.href);
          const b = URL.createObjectURL(blob);
          el.style.background = "url(" + name + ")";
          if (s.indexOf('url(') >= 0) {}
        </script>
        """
        self.assertEqual(_scan(html), [])

    def test_css_comment_url_not_flagged(self) -> None:
        html = '<style>/* see url(legacy/old.png) for history */ .a{color:red}</style>'
        self.assertEqual(_scan(html), [])

    def test_html_comment_ref_not_flagged(self) -> None:
        html = '<!-- <img src="draft/old.png"> --><div>ok</div>'
        self.assertEqual(_scan(html), [])

    def test_real_css_url_is_flagged(self) -> None:
        html = '<style>.hero{background:url("assets/bg.png")}</style>'
        self.assertIn("assets/bg.png", _scan(html))

    def test_real_unhosted_resource_attrs_flagged(self) -> None:
        html = (
            '<link rel="stylesheet" href="local.css">'
            '<img src="local.png">'
            '<script src="local.js"></script>'
        )
        flagged = _scan(html)
        self.assertIn("local.css", flagged)
        self.assertIn("local.png", flagged)
        self.assertIn("local.js", flagged)

    def test_hosted_refs_not_flagged(self) -> None:
        html = (
            '<img src="https://tos.example.test/a.png">'
            '<style>.b{background:url("https://tos.example.test/b.png")}</style>'
            '<script src="//cdn.example.test/c.js"></script>'
        )
        self.assertEqual(_scan(html), [])

    def test_data_uri_in_attr_not_treated_as_unhosted_path(self) -> None:
        # a data: ref is its own residual concern (residual_data_payloads), and is
        # NOT a relative/local path → must not appear in the unhosted-deps list.
        html = '<img src="data:image/png;base64,AAAA">'
        self.assertEqual(_scan(html), [])


class ResidualDataTest(unittest.TestCase):
    def test_detects_each_heavy_media_kind(self) -> None:
        self.assertTrue(_residual('<img src="data:image/png;base64,AAAA">'))
        self.assertTrue(_residual('<video src="data:video/mp4;base64,AAAA"></video>'))
        self.assertTrue(_residual('<audio src="data:audio/mpeg;base64,AAAA"></audio>'))
        self.assertTrue(_residual('<style>@font-face{src:url(data:font/woff2;base64,AAAA)}</style>'))

    def test_no_false_positive_when_all_hosted(self) -> None:
        html = '<img src="https://tos.example.test/a.png"><video src="https://tos.example.test/v.mp4"></video>'
        self.assertEqual(_residual(html), [])


if __name__ == "__main__":
    unittest.main()
