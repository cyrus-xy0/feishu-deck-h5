"""iteration-loop W1/W3/W4/W5/W8 — set-page, pre-write lint, auto-scope, echo, add-asset.

Replay-set anchors (docs/PLAN-ITERATION-LOOP-2026-06-11.md §7): the lint cases
mirror the real first-render gate failures of the FWD-deck session
(77px/21px typescale, .kicker 16px, inset:0 dual-anchor, P50 base64-in-style).
"""
import base64
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK_JSON = HERE.parent
CLI = DECK_JSON / "deck-cli.py"
RENDER = DECK_JSON / "render-deck.py"
DEMO = DECK_JSON / "examples" / "phase-1a-demo.json"

sys.path.insert(0, str(DECK_JSON))
from _lint_fragment import lint_fragment  # noqa: E402


# ---------------------------------------------------------------- helpers ----
def _mk_deck(tmp_path: Path) -> Path:
    d = json.loads(DEMO.read_text(encoding="utf-8"))
    d["slides"].append({
        "key": "rawpage", "layout": "raw", "screen_label": "07 Raw",
        "data": {"html": '<div class="header"><h2 class="title-zh">Old</h2>'
                         '</div><div class="stage"><p class="body">old</p></div>'}})
    p = tmp_path / "deck.json"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return p


def _cli(deck: Path, *argv):
    return subprocess.run(
        [sys.executable, str(CLI), str(deck), "--no-backup", *argv],
        capture_output=True, text=True)


def _render(deck: Path, out: Path, *flags):
    import os
    env = dict(os.environ); env["DECK_LOG_NO_AUTOSNAP"] = "1"
    return subprocess.run(
        [sys.executable, str(RENDER), str(deck), str(out) + "/", *flags],
        capture_output=True, text=True, env=env)


# ------------------------------------------------------------- W4 · lint ----
def test_lint_catches_fwd_session_failures():
    css = """
    .x .h1{ font-size:77px; }
    .x .sub{ font-size:21px; }
    .x .strip{ position:absolute; top:838px; bottom:44px; }
    .x .full{ position:absolute; inset:0; }
    """
    codes = [f["code"] for f in lint_fragment(css=css) if f["sev"] == "err"]
    assert codes.count("L-TYPESCALE") == 2
    # F-323: only `.strip` (top+bottom, no full box) is the cascade footgun;
    # `.full{ inset:0 }` is a deliberate fill (the runtime's own fix) → exempt.
    assert codes.count("L-DUAL-ANCHOR") == 1


def test_lint_dual_anchor_only_flags_half_anchor():
    # F-323: align L-DUAL-ANCHOR with runtime R-VIS-ABSPOS-DUAL-ANCHOR — flag only
    # top+bottom WITHOUT a full box; deliberate boxes / pseudo overlays are exempt.
    def codes(css, html=""):
        return [f["code"] for f in lint_fragment(html=html, css=css) if f["sev"] == "err"]
    # genuine footgun (top+bottom, no left/right, no inset) → flag
    assert "L-DUAL-ANCHOR" in codes(".x .a{position:absolute;top:8px;bottom:8px}")
    # inset shorthand (the runtime's own recommended fix) → exempt
    assert "L-DUAL-ANCHOR" not in codes(".x .b{position:absolute;inset:0}")
    # all four edges declared = deliberate box → exempt
    assert "L-DUAL-ANCHOR" not in codes(
        ".x .c{position:absolute;top:8px;bottom:8px;left:8px;right:8px}")
    # pseudo-element overlay (runtime never evaluates ::before) → exempt
    assert "L-DUAL-ANCHOR" not in codes(".x .d::before{position:absolute;top:0;bottom:0}")


def test_lint_respects_ladder_hero_and_optouts():
    ok = ".x .num{font-size:72px} .x .b{font-size:24px} .x .f{font-size:16px}"
    assert [f for f in lint_fragment(css=ok) if f["sev"] == "err"] == []
    # opt-outs silence their classes
    css = ".x .h{font-size:77px} .x .o{position:absolute;inset:0}"
    html = '<div data-allow-typescale data-allow-dual-anchor></div>'
    assert [f for f in lint_fragment(html=html, css=css) if f["sev"] == "err"] == []


def test_lint_p50_base64_in_style():
    blob = base64.b64encode(b"x" * 300 * 1024).decode()
    css = f'.x{{background:url("data:image/png;base64,{blob}")}}'
    codes = [f["code"] for f in lint_fragment(css=css) if f["sev"] == "err"]
    assert "L-P50-INLINE" in codes


def test_lint_lifted_downgrades_typescale_and_dual_anchor():
    # F-355: a LIFTED slide's verbatim source styling demotes L-TYPESCALE /
    # L-DUAL-ANCHOR err→warn (so the page no longer needs a wholesale --skip-lint),
    # while AUTHORED pages keep err. L-P50-INLINE (base64 bloat) stays err regardless.
    css = ".x .h{font-size:77px} .x .a{position:absolute;top:8px;bottom:8px}"
    blob = base64.b64encode(b"x" * 300 * 1024).decode()
    p50 = f'.y{{background:url("data:image/png;base64,{blob}")}}'

    auth = lint_fragment(css=css + p50, lifted=False)
    lift = lint_fragment(css=css + p50, lifted=True)
    auth_err = {f["code"] for f in auth if f["sev"] == "err"}
    lift_err = {f["code"] for f in lift if f["sev"] == "err"}
    lift_warn = {f["code"] for f in lift if f["sev"] == "warn"}

    assert {"L-TYPESCALE", "L-DUAL-ANCHOR", "L-P50-INLINE"} <= auth_err
    assert "L-TYPESCALE" not in lift_err and "L-DUAL-ANCHOR" not in lift_err
    assert {"L-TYPESCALE", "L-DUAL-ANCHOR"} <= lift_warn
    assert "L-P50-INLINE" in lift_err  # base64 bloat never demotes


# --------------------------------------------------------- W1 · set-page ----
def test_set_page_writes_html_css_lifted(tmp_path):
    deck = _mk_deck(tmp_path)
    h = tmp_path / "f.html"
    h.write_text('<div class="header"><h2 class="title-zh">New</h2></div>'
                 '<div class="stage"><p class="body">new body</p></div>',
                 encoding="utf-8")
    c = tmp_path / "f.css"
    c.write_text('.slide[data-slide-key="rawpage"] .body{font-size:24px;}',
                 encoding="utf-8")
    r = _cli(deck, "set-page", "rawpage", "--html", str(h), "--css", str(c),
             "--lifted", "--title", "T")
    assert r.returncode == 0, r.stdout + r.stderr
    s = json.loads(deck.read_text(encoding="utf-8"))["slides"][-1]
    assert "New" in s["data"]["html"]
    assert s["custom_css"].startswith(".slide[")
    assert s["lifted"] is True and s["data"]["title"] == "T"


def test_set_page_refuses_bad_fragment_then_skip_lint(tmp_path):
    deck = _mk_deck(tmp_path)
    bad = tmp_path / "bad.css"
    bad.write_text(".x{font-size:21px}", encoding="utf-8")
    r = _cli(deck, "set-page", "rawpage", "--css", str(bad))
    assert r.returncode == 5
    assert "L-TYPESCALE" in r.stdout + r.stderr
    s = json.loads(deck.read_text(encoding="utf-8"))["slides"][-1]
    assert "custom_css" not in s, "refused write must not touch the deck"
    r2 = _cli(deck, "set-page", "rawpage", "--css", str(bad), "--skip-lint")
    assert r2.returncode == 0


def _mk_deck_with_embedded_style(tmp_path: Path, css_body: str) -> Path:
    """rawpage whose data.html carries an embedded <style> (the override trap)."""
    deck = _mk_deck(tmp_path)
    d = json.loads(deck.read_text(encoding="utf-8"))
    d["slides"][-1]["data"]["html"] = (
        f"<style>{css_body}</style>"
        '<div class="header"><h2 class="title-zh">T</h2></div>'
        '<div class="stage"><p class="body">body copy here</p></div>')
    deck.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return deck


def test_consolidate_css_folds_embedded_style_idempotent(tmp_path):
    # F-347: embedded <style> → custom_css (single home; kills the override trap)
    rule = '.slide[data-slide-key="rawpage"] .body{font-size:24px}'
    deck = _mk_deck_with_embedded_style(tmp_path, rule)

    # dry-run reports but writes nothing
    r0 = _cli(deck, "consolidate-css", "--key", "rawpage", "--dry-run")
    assert r0.returncode == 0 and "would fold" in r0.stdout
    assert "<style" in json.loads(deck.read_text(encoding="utf-8"))[
        "slides"][-1]["data"]["html"], "dry-run must not mutate"

    # real run folds into custom_css and strips the <style> from data.html
    r1 = _cli(deck, "consolidate-css", "--key", "rawpage")
    assert r1.returncode == 0, r1.stdout + r1.stderr
    s = json.loads(deck.read_text(encoding="utf-8"))["slides"][-1]
    assert "<style" not in s["data"]["html"]
    assert "font-size:24px" in (s.get("custom_css") or "")

    # idempotent: nothing left to fold
    r2 = _cli(deck, "consolidate-css", "--key", "rawpage")
    assert r2.returncode == 0 and "nothing to do" in r2.stdout


def test_set_page_warns_on_embedded_style_override(tmp_path):
    # F-347: writing custom_css to a page that still has embedded <style> warns
    deck = _mk_deck_with_embedded_style(tmp_path, ".x{color:#fff}")
    c = tmp_path / "f.css"
    c.write_text('.slide[data-slide-key="rawpage"] .body{font-size:24px}',
                 encoding="utf-8")
    r = _cli(deck, "set-page", "rawpage", "--css", str(c))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "embedded <style>" in r.stderr and "consolidate-css" in r.stderr


def test_set_from_file_raw_string(tmp_path):
    deck = _mk_deck(tmp_path)
    f = tmp_path / "v.css"
    f.write_text('.slide .body{color:#fff}', encoding="utf-8")
    r = _cli(deck, "set", "slides.6.custom_css", "--from-file", str(f))
    assert r.returncode == 0, r.stdout + r.stderr
    s = json.loads(deck.read_text(encoding="utf-8"))["slides"][6]
    assert s["custom_css"] == '.slide .body{color:#fff}'


def test_rollback_restores_even_with_no_backup(tmp_path):
    deck = _mk_deck(tmp_path)
    before = deck.read_text(encoding="utf-8")
    r = _cli(deck, "set", "slides.0.layout", "not-a-layout")
    assert r.returncode == 3
    assert deck.read_text(encoding="utf-8") == before, \
        "--no-backup schema-fail must restore the pre-write content"


# ----------------------------------------------- W3/W5 · auto-scope + echo ----
def test_iter_auto_scope_and_text_echo(tmp_path):
    deck = _mk_deck(tmp_path)
    out = tmp_path / "out"
    r0 = _render(deck, out, "--iter")
    assert r0.returncode == 0
    assert "no sidecar" in r0.stdout
    assert (out / ".slide-hashes.json").exists()

    # edit the raw page only → next --iter must scope to page 7 + echo its text
    d = json.loads(deck.read_text(encoding="utf-8"))
    d["slides"][-1]["data"]["html"] = d["slides"][-1]["data"]["html"].replace(
        "old", "ECHO-MARKER")
    deck.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    r1 = _render(deck, out, "--iter")
    assert r1.returncode == 0
    assert "auto-scope → pages 7" in r1.stdout
    assert "text echo" in r1.stdout and "ECHO-MARKER" in r1.stdout

    # no change → full (cheap) again
    r2 = _render(deck, out, "--iter")
    assert "no slide changed" in r2.stdout

    # F-334: a structural INSERT scopes to the genuinely-new page instead of
    # forcing a full pass (was: assert "added/removed/reordered" → full). Each
    # page renders independently of position, so the shifted tail need not
    # re-gate — only the new page does.
    d["slides"].append({"key": "p8-new", "layout": "raw",
                        "data": {"html": "<p>brand new page</p>"}})
    deck.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    r3 = _render(deck, out, "--iter")
    assert "auto-scope → pages 8" in r3.stdout, r3.stdout

    # a deletion that leaves the rest untouched → nothing new to re-gate
    d["slides"].pop()
    deck.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    r4 = _render(deck, out, "--iter")
    assert "no slide changed" in r4.stdout, r4.stdout

    # --final overrides --iter
    r5 = _render(deck, out, "--iter", "--final")
    assert r5.returncode == 0 and "--iter:" not in r5.stdout


# ------------------------------------------------------------ W8 · asset ----
def test_add_asset_places_and_compresses(tmp_path):
    try:
        from PIL import Image
    except ImportError:
        import pytest
        pytest.skip("PIL not available")
    deck = _mk_deck(tmp_path)
    src = tmp_path / "big.png"
    Image.new("RGB", (2400, 1200), (200, 30, 30)).save(src)
    r = _cli(deck, "add-asset", str(src), "--max-width", "1200")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "reference it as:  input/big.jpg" in r.stdout
    placed = tmp_path / "input" / "big.jpg"
    assert placed.exists()
    with Image.open(placed) as im:
        assert im.width == 1200
