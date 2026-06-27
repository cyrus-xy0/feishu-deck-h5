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


def test_lint_mockup_silences_typescale():
    # F-358: a data-mockup root (a simulated UI) silences L-TYPESCALE for the
    # fragment, so phone / product-UI mockups don't need data-allow-typescale
    # sprinkled on every off-ladder leaf.
    css = ".x .lbl{font-size:14px} .x .num{font-size:19px}"
    assert "L-TYPESCALE" in [f["code"] for f in lint_fragment(css=css)
                             if f["sev"] == "err"]
    html = '<div class="phone" data-mockup></div>'
    assert "L-TYPESCALE" not in [
        f["code"] for f in lint_fragment(html=html, css=css) if f["sev"] == "err"]


def test_lint_reserved_raw_class_blocks_authored_stage():
    html = '<div class="header"><h2 class="title-zh">T</h2></div><div class="stage"></div>'
    css = '.slide[data-slide-key="k"] .stage{top:258px}'

    auth = lint_fragment(html=html, css=css, lifted=False)
    lift = lint_fragment(html=html, css=css, lifted=True)
    opt = lint_fragment(
        html=html + '<div data-allow-reserved-class></div>',
        css=css,
        lifted=False,
    )

    assert "L-RAW-RESERVED-CLASS" in {f["code"] for f in auth if f["sev"] == "err"}
    assert "L-RAW-RESERVED-CLASS" not in {f["code"] for f in lift if f["sev"] == "err"}
    assert "L-RAW-RESERVED-CLASS" in {f["code"] for f in lift if f["sev"] == "warn"}
    assert "L-RAW-RESERVED-CLASS" not in {f["code"] for f in opt}


def test_lint_allows_prefixed_raw_stage_hooks():
    html = '<div class="ai-leaps-stage"></div>'
    css = '.slide[data-slide-key="k"] .ai-leaps-stage{top:258px}'
    assert "L-RAW-RESERVED-CLASS" not in {f["code"] for f in lint_fragment(html=html, css=css)}


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


# ------------------------------------------------ F-368 · gate-fail sidecar ----
def _playwright_ok():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except Exception:
        return False


def _floor_page(key, label):
    # 16px real CJK sentence in a non-'body' class → passes the static ladder
    # (16 is on the {16,24,28,48} tier) but fails the runtime R-VIS-BODY-FLOOR
    # readability audit → a visual-only error that routes through _vis_block.
    return {"key": key, "layout": "raw", "screen_label": label,
            "data": {"html": '<div class="header"><h2 class="title-zh">Floor</h2>'
                             '</div><div class="stage"><div class="readout">这是一'
                             '段足够长的真正正文内容用于触发可读性地板审计它既不是'
                             '标签也不是页眉</div></div>'},
            "custom_css": f'.slide[data-slide-key="{key}"] .readout{{font-size:16px}}'}


def _raw_page(key, label, text):
    return {"key": key, "layout": "raw", "screen_label": label,
            "data": {"html": f'<div class="header"><h2 class="title-zh">{text}</h2>'
                             f'</div><div class="stage"><p class="body">正文内容'
                             f' {text} 这里写得足够长以正常渲染</p></div>'}}


def test_gate_fail_render_persists_sidecar_and_next_edit_auto_scopes(tmp_path):
    # F-368 · a deck that FAILS the visual gate (rc=4 — the normal work-in-progress
    # state) must STILL persist the auto-scope sidecar, with the erroring page
    # poisoned. Before F-368 the sidecar was written only past every gate return,
    # so such decks never got one → every render was a full whole-deck pass.
    import pytest
    if not _playwright_ok():
        pytest.skip("Playwright/Chromium unavailable — visual gate cannot run")

    # bootstrap a valid deck, then append 2 clean pages + 1 floor offender.
    deck = tmp_path / "deck.json"
    boot = subprocess.run([sys.executable, str(CLI), str(deck), "new-deck",
                           "--title", "F368", "--author", "A", "--date", "2026-06-23"],
                          capture_output=True, text=True)
    assert boot.returncode == 0, boot.stdout + boot.stderr
    d = json.loads(deck.read_text(encoding="utf-8"))
    d["slides"].append(_raw_page("cleanx", "97 Clean", "Alpha"))
    d["slides"].append(_floor_page("floorpg", "98 Floor"))
    deck.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    # runs/<ts>/output/ so the real delivery visual gate fires (not a smoke test).
    out = tmp_path / "runs" / "20260101-f368" / "output"
    out.mkdir(parents=True)

    r1 = _render(deck, out)
    assert r1.returncode == 4, "the floor page must block the visual gate\n" + r1.stderr
    sidecar = out / ".slide-hashes.json"
    assert sidecar.exists(), "F-368: a gate-fail render must still persist the sidecar"
    cells = dict(json.loads(sidecar.read_text(encoding="utf-8"))["slides"])
    assert cells["floorpg"] == "!unresolved-error", "the offender must be poisoned"
    assert cells["cleanx"] != "!unresolved-error", "a clean page keeps its real hash"

    # edit the CLEAN page → the next render must AUTO-SCOPE (not a full pass) and
    # the still-erroring floor page must stay in scope (keeps re-auditing).
    d = json.loads(deck.read_text(encoding="utf-8"))
    for s in d["slides"]:
        if s["key"] == "cleanx":
            s["data"]["html"] = s["data"]["html"].replace("Alpha", "Alpha-EDIT")
    deck.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")

    r2 = _render(deck, out)
    assert "scope=auto:" in r2.stderr, "auto-scope must engage now there is a sidecar\n" + r2.stderr
    assert "AUTO-SCOPE: off" not in r2.stderr, "must not fall back to a full render"


def test_no_change_rerender_skips_visual_reaudit(tmp_path):
    # F-369 · a re-render byte-identical to the last CLEAN render skips the
    # expensive 6b/6c browser passes (the cheap static gate still runs). Safe
    # because F-368 poisons any erroring page → an empty diff PROVES clean.
    import pytest
    if not _playwright_ok():
        pytest.skip("Playwright/Chromium unavailable — visual gate cannot run")

    deck = tmp_path / "deck.json"
    boot = subprocess.run([sys.executable, str(CLI), str(deck), "new-deck",
                           "--title", "F369", "--author", "A", "--date", "2026-06-23"],
                          capture_output=True, text=True)
    assert boot.returncode == 0, boot.stdout + boot.stderr
    d = json.loads(deck.read_text(encoding="utf-8"))
    d["slides"].append(_raw_page("cleanx", "97 Clean", "Alpha"))
    deck.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "runs" / "20260101-f369" / "output"
    out.mkdir(parents=True)

    r1 = _render(deck, out)                       # first render → full audit
    assert r1.returncode == 0, r1.stdout + r1.stderr
    assert "visual=ran" in r1.stderr

    r2 = _render(deck, out)                       # no change → skip 6b/6c
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "skipping visual/geometry re-audit" in r2.stderr
    assert "visual=skipped(unchanged" in r2.stderr

    r3 = _render(deck, out, "--final")            # --final forces the full pass
    assert "visual=ran" in r3.stderr and "skipped(unchanged" not in r3.stderr

    # introduce a blocking error → the next render must NOT skip (F-368 poisons
    # the offender → dirty → re-audited → caught): the skip can't hide a defect.
    d = json.loads(deck.read_text(encoding="utf-8"))
    d["slides"].append(_floor_page("badpg", "98 Floor"))
    deck.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    r4 = _render(deck, out)
    assert r4.returncode == 4, "the new floor page must be audited + blocked\n" + r4.stderr
    assert "skipping visual/geometry re-audit" not in r4.stderr

    # a no-change re-render while the error is OPEN still must not skip.
    r5 = _render(deck, out)
    assert r5.returncode == 4, "open error must keep re-auditing\n" + r5.stderr
    assert "skipping visual/geometry re-audit" not in r5.stderr


def test_f290_merged_distribution_matches_standalone(tmp_path):
    # F-290 · validate.py --with-distribution folds the layout-distribution audit
    # into the visual browser pass; its signals MUST equal standalone
    # check-distribution.py (parity), else render-deck would gate on different
    # geometry after dropping the 2nd Chromium launch.
    import pytest
    if not _playwright_ok():
        pytest.skip("Playwright/Chromium unavailable — visual gate cannot run")
    assets = DECK_JSON.parent / "assets"
    deck = tmp_path / "deck.json"
    boot = subprocess.run([sys.executable, str(CLI), str(deck), "new-deck",
                           "--title", "F290", "--author", "A", "--date", "2026-06-23"],
                          capture_output=True, text=True)
    assert boot.returncode == 0, boot.stdout + boot.stderr
    d = json.loads(deck.read_text(encoding="utf-8"))
    d["slides"].append(_raw_page("a", "97 A", "Alpha"))
    d["slides"].append(_raw_page("b", "98 B", "Beta"))
    deck.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "runs" / "20260101-f290" / "output"
    out.mkdir(parents=True)
    r = _render(deck, out)
    assert r.returncode in (0, 4), r.stdout + r.stderr
    html = str(out / "index.html")

    merged = subprocess.run(
        [sys.executable, str(assets / "validate.py"), html,
         "--visual", "--json", "--with-distribution", "--full"],
        capture_output=True, text=True)
    standalone = subprocess.run(
        [sys.executable, str(assets / "check-distribution.py"), html, "--json"],
        capture_output=True, text=True)
    md = json.loads(merged.stdout).get("distribution")
    sd = json.loads(standalone.stdout)
    assert md is not None, "validate --with-distribution must emit a 'distribution' key"

    def sigs(arr):
        return {s["idx"]: sorted(x[0] for x in s.get("signals", [])) for s in arr}
    assert sigs(md) == sigs(sd), "merged distribution signals must match standalone"


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
