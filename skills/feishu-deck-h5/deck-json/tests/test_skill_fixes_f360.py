"""Regression tests for the F-360..F-363 tooling fixes:

F-360  deck-map: count `.slide-frame` like the DOM (modifier classes / attr order)
F-362  deck-cli inspect-text: follow iframe src into the prototype, list font-sizes
F-363  deck-cli prune_backups: cap `.bak-pre-*` accumulation
(F-361 — render-deck `--shoot --slide` focus — is an integration behaviour
verified by the render gate, not unit-tested here.)
"""

import importlib.util
import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


HERE = Path(__file__).resolve().parent
DECKJSON = HERE.parents[1] / "deck-json"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


deck_map = _load("deck_map_mod", DECKJSON / "deck-map.py")
deck_cli = _load("deck_cli_mod", DECKJSON / "deck-cli.py")


class DeckMapFrameCountTest(unittest.TestCase):
    """F-360: frames with a modifier class or non-first class attr must still
    count — matching querySelectorAll('.slide-frame') / the browser's #N."""

    def test_modifier_classes_and_attr_order_all_count(self):
        html = (
            '<div class="slide-frame"><div class="slide" data-slide-key="a">'
            '<h2 class="title-zh">A</h2></div></div>'
            # modifier class (the is-current frame)
            '<div class="slide-frame is-current"><div class="slide" '
            'data-slide-key="b"><h2 class="title-zh">B</h2></div></div>'
            # extra class + a big inline style (the fs-bleed-host frame)
            '<div class="slide-frame fs-bleed-host" style="--x: url(&quot;p&quot;)">'
            '<div class="slide" data-slide-key="c"><h2 class="title-zh">C</h2>'
            '</div></div>'
        )
        rows = deck_map.map_html(html)
        self.assertEqual([r["index"] for r in rows], [1, 2, 3])
        self.assertEqual([r["key"] for r in rows], ["a", "b", "c"])


class PruneBackupsTest(unittest.TestCase):
    """F-363: keep only the newest N backups."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="prune-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_keeps_newest_n(self):
        dj = self.tmp / "deck.json"
        dj.write_text("{}")
        for i in range(20):
            f = self.tmp / f"deck.json.bak-pre-set-2026{i:04d}"
            f.write_text("x")
            os.utime(f, (1000 + i, 1000 + i))
        removed = deck_cli.prune_backups(dj, keep=15)
        left = sorted(self.tmp.glob("deck.json.bak-pre-*"))
        self.assertEqual(removed, 5)
        self.assertEqual(len(left), 15)
        # the 15 newest (mtimes 1005..1019) survive
        self.assertEqual(sorted(int(p.name[-4:]) for p in left), list(range(5, 20)))

    def test_under_limit_is_noop(self):
        dj = self.tmp / "deck.json"
        dj.write_text("{}")
        for i in range(3):
            (self.tmp / f"deck.json.bak-pre-x-{i}").write_text("x")
        self.assertEqual(deck_cli.prune_backups(dj, keep=15), 0)
        self.assertEqual(len(list(self.tmp.glob("deck.json.bak-pre-*"))), 3)


class InspectTextTest(unittest.TestCase):
    """F-362: inspect-text follows iframe src into the prototype file and lists
    its font-sizes."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="inspect-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_helpers(self):
        fm = deck_cli._fontsize_map(
            '.a{font-size:13px}.b{font:600 48px/1.2 sans}.c{color:red}')
        self.assertIn((".a", "13px"), fm)
        self.assertIn((".b", "48px"), fm)
        self.assertEqual(deck_cli._visible_text("<p>hi <b>there</b></p>"), "hi there")

    def test_follows_iframe_into_prototype(self):
        # prototype file two levels deep, referenced by the page's iframe
        proto_dir = self.tmp / "prototypes" / "demo"
        proto_dir.mkdir(parents=True)
        (proto_dir / "index.html").write_text(
            '<style>.win-bar .wt{font-size:17.5px}.bubble{font-size:14px}</style>'
            '<div class="bubble">hello from the demo</div>', encoding="utf-8")
        deck = {"slides": [{
            "key": "demo-page", "layout": "raw",
            "custom_css": '.title-zh{font:600 48px sans}',
            "data": {"html":
                '<h2 class="title-zh">T</h2>'
                '<iframe src="prototypes/demo/index.html"></iframe>'},
        }]}

        class A:  # stand-in for argparse Namespace
            ref = "demo-page"
            deck = (self.tmp / "deck.json")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = deck_cli.cmd_inspect_text(deck, A)
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("prototypes/demo/index.html", out)
        self.assertIn("17.5px", out)          # prototype font-size surfaced
        self.assertIn("hello from the demo", out)  # prototype text surfaced
        self.assertIn("48px", out)            # page font-size surfaced


if __name__ == "__main__":
    unittest.main()
