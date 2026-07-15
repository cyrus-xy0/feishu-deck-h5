import contextlib
import hashlib
import importlib.util
import io
import json
from unittest import mock
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "lift-swap.py"

SPEC = importlib.util.spec_from_file_location("lift_swap_under_test", TOOL)
assert SPEC and SPEC.loader
LIFT_SWAP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIFT_SWAP)

SRC_HTML = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<div class="deck">
<div class="slide-frame">
<div class="slide" data-layout="raw" data-slide-key="src-page" data-screen-label="01 Source">
<div class="header"><h2 class="title-zh">Source Lifted Title</h2></div>
<div class="stage"><h1>Source Lifted Body</h1></div>
</div>
</div>
<div class="slide-frame">
<div class="slide" data-layout="raw" data-slide-key="second-page" data-screen-label="02 Second">
<div class="header"><h2 class="title-zh">Second Source Title</h2></div>
<div class="stage"><h1>Second</h1></div>
</div>
</div>
</div>
</body></html>
"""


def _target_deck():
    return {
        "version": "1.0",
        "deck": {"title": "target", "author": "a", "date": "2026-06"},
        "slides": [
            {"key": "target-one", "layout": "raw", "screen_label": "01 Target",
             "data": {"html": '<div class="header"><h2 class="title-zh">Target One Title</h2></div>'
                              '<div class="stage"><h1>Old One</h1></div>'}},
            {"key": "target-two", "layout": "raw", "screen_label": "02 Target Two",
             "data": {"html": '<div class="header"><h2 class="title-zh">Target Two Title</h2></div>'
                              '<div class="stage"><h1>Old Two</h1></div>'}},
        ],
    }


class LiftSwapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="lift-swap-test-"))
        self.src = self.tmp / "src"
        self.dst = self.tmp / "dst"
        self.src.mkdir()
        self.dst.mkdir()
        (self.src / "index.html").write_text(SRC_HTML, encoding="utf-8")
        (self.dst / "deck.json").write_text(
            json.dumps(_target_deck(), ensure_ascii=False), encoding="utf-8")
        (self.dst / "index.html").write_text("<html>OLD INDEX</html>", encoding="utf-8")

        self.ok_renderer = self.tmp / "fake-render-ok.py"
        self.ok_renderer.write_text(textwrap.dedent("""
            import pathlib
            import sys
            deck = pathlib.Path(sys.argv[1])
            out = pathlib.Path(sys.argv[2])
            scope = sys.argv[sys.argv.index('--scope') + 1]
            out.mkdir(parents=True, exist_ok=True)
            (out / 'index.html').write_text('<html>RENDERED ' + deck.name + '</html>', encoding='utf-8')
            (out / ('.shoot-p' + scope + '.png')).write_bytes(b'PNG')
        """), encoding="utf-8")
        self.bad_renderer = self.tmp / "fake-render-fail.py"
        self.bad_renderer.write_text("import sys\nsys.exit(9)\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(TOOL), *args],
            capture_output=True, text=True,
        )

    def _deck(self):
        return json.loads((self.dst / "deck.json").read_text(encoding="utf-8"))

    def _named_refs(self, source="#1", target="#1"):
        return [
            "--source", str(self.src / "index.html") + source,
            "--target", str(self.dst / "index.html") + target,
        ]

    def _call_main(self, args, *, renderer=None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        patcher = (mock.patch.object(LIFT_SWAP, "RENDER_DECK", renderer)
                   if renderer is not None else contextlib.nullcontext())
        with patcher, contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = LIFT_SWAP.main(args)
        return rc, stdout.getvalue(), stderr.getvalue()

    def _plan_token(self, refs=None):
        refs = refs or self._named_refs()
        rc, out, err = self._call_main(refs)
        self.assertEqual(rc, 0, f"{out}\n{err}")
        line = next(line for line in out.splitlines() if "confirm token:" in line)
        return line.split("confirm token:", 1)[1].strip(), out

    def test_default_is_read_only_even_with_legacy_positionals(self):
        before = (self.dst / "deck.json").read_text(encoding="utf-8")
        proc = self._run(
            (self.src / "index.html").resolve().as_uri() + "#1",
            (self.dst / "index.html").resolve().as_uri() + "#1",
        )
        self.assertEqual(proc.returncode, 0, f"{proc.stdout}\n{proc.stderr}")
        self.assertIn("READ ONLY", proc.stdout)
        self.assertIn("plan-only: no files changed", proc.stdout)
        self.assertEqual((self.dst / "deck.json").read_text(encoding="utf-8"), before)

    def test_plan_prints_direction_titles_and_token(self):
        token, out = self._plan_token()
        self.assertRegex(token, r"^[0-9a-f]{16}$")
        self.assertIn("SOURCE [READ-ONLY]", out)
        self.assertIn("Source Lifted Title", out)
        self.assertIn("↓ replace target slot; preserve source layout", out)
        self.assertIn("TARGET [WRITABLE]", out)
        self.assertIn("Target One Title", out)

    def test_missing_endpoint_is_rejected(self):
        proc = self._run("--source", str(self.src / "index.html") + "#1")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("missing --target", proc.stderr)

    def test_positional_apply_can_never_write(self):
        before = (self.dst / "deck.json").read_text(encoding="utf-8")
        proc = self._run(
            str(self.src / "index.html") + "#1",
            str(self.dst / "index.html") + "#1",
            "--apply", "--confirm", "anything",
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("writes require named", proc.stderr)
        self.assertEqual((self.dst / "deck.json").read_text(encoding="utf-8"), before)

    def test_stale_or_missing_token_is_rejected_without_mutation(self):
        before = (self.dst / "deck.json").read_text(encoding="utf-8")
        rc, _out, err = self._call_main(
            self._named_refs() + ["--apply", "--confirm", "stale"])
        self.assertEqual(rc, 4)
        self.assertIn("token missing or stale", err)
        self.assertEqual((self.dst / "deck.json").read_text(encoding="utf-8"), before)

    def test_plan_token_expires_when_target_changes(self):
        refs = self._named_refs()
        token, _out = self._plan_token(refs)
        changed = _target_deck()
        changed["deck"]["title"] = "changed after plan"
        (self.dst / "deck.json").write_text(
            json.dumps(changed, ensure_ascii=False), encoding="utf-8")

        rc, _out, err = self._call_main(
            refs + ["--apply", "--confirm", token], renderer=self.ok_renderer)
        self.assertEqual(rc, 4)
        self.assertIn("token missing or stale", err)
        self.assertEqual(self._deck()["deck"]["title"], "changed after plan")

    def test_plan_token_binds_high_risk_options(self):
        refs = self._named_refs()
        token, _out = self._plan_token(refs)
        rc, _out, err = self._call_main(
            refs + ["--force", "--apply", "--confirm", token],
            renderer=self.ok_renderer)
        self.assertEqual(rc, 4)
        self.assertIn("token missing or stale", err)

    def test_same_deck_tree_requires_explicit_override(self):
        (self.src / "deck.json").write_text(
            json.dumps(_target_deck(), ensure_ascii=False), encoding="utf-8")
        proc = self._run(
            "--source", str(self.src / "index.html") + "#1",
            "--target", str(self.src / "deck.json") + "#1",
        )
        self.assertEqual(proc.returncode, 3)
        self.assertIn("same deck tree", proc.stderr)

    def test_apply_is_transactional_and_source_stays_byte_identical(self):
        refs = self._named_refs()
        token, _out = self._plan_token(refs)
        source_before = hashlib.sha256(
            (self.src / "index.html").read_bytes()).hexdigest()

        rc, out, err = self._call_main(
            refs + ["--apply", "--confirm", token], renderer=self.ok_renderer)
        self.assertEqual(rc, 0, f"{out}\n{err}")
        deck = self._deck()
        self.assertEqual([slide["key"] for slide in deck["slides"]],
                         ["target-one", "target-two"])
        self.assertIn("Source Lifted Body", deck["slides"][0]["data"]["html"])
        self.assertIn("Old Two", deck["slides"][1]["data"]["html"])
        self.assertTrue(deck["slides"][0].get("lifted"))
        self.assertEqual(hashlib.sha256(
            (self.src / "index.html").read_bytes()).hexdigest(), source_before)
        self.assertEqual((self.dst / ".shoot-p1.png").read_bytes(), b"PNG")
        self.assertIn("committed transactional lift-swap", out)

    def test_render_failure_leaves_official_target_unchanged(self):
        refs = self._named_refs()
        token, _out = self._plan_token(refs)
        deck_before = (self.dst / "deck.json").read_bytes()
        index_before = (self.dst / "index.html").read_bytes()

        rc, _out, err = self._call_main(
            refs + ["--apply", "--confirm", token], renderer=self.bad_renderer)
        self.assertEqual(rc, 7)
        self.assertIn("official target unchanged", err)
        self.assertEqual((self.dst / "deck.json").read_bytes(), deck_before)
        self.assertEqual((self.dst / "index.html").read_bytes(), index_before)
        self.assertFalse((self.dst / ".shoot-p1.png").exists())
        self.assertFalse(list(self.tmp.glob(".dst.lift-stage-*")))


if __name__ == "__main__":
    unittest.main()
