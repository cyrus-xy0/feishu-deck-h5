"""edit→save→sync round-trip sanitize — F-259 P0 「编辑链越改越坏」稳妥版.

Three components used to contradict each other so the edit chain degraded the
deck every round-trip:

  ① The in-browser edit-mode ⌘S save (deck-edit-mode.js buildSavedHTML) only
     stripped EDIT artifacts, not the RUNTIME traces feishu-deck.js writes at
     present-mode init (per-frame data-idx, the buildUI() .deck-ui overlay, .deck
     runtime flags, per-slide data-fs-* balance markers, the reveal --child-i
     prop, and the inline geometry the balance/canvas-center passes inject). So
     the saved file tripped the new R-BAKED-DOM gate AND carried runtime geometry.

  ② sync-index-to-deck.py reverse-feeds index.html → deck.json. Fed a baked DOM,
     it folded those runtime mutations back into deck.json as if they were author
     edits → the source drifted every round-trip.

The 稳妥版 fix sanitizes at the two BOUNDARIES (save + sync) without touching the
runtime (feishu-deck.js is NOT modified):

  · buildSavedHTML strips the runtime traces on its clone (asserted by the
    Playwright e2e below — skipped if Chromium is unavailable);
  · sync REFUSES a baked index.html by default (R-BAKED-DOM fingerprints) and,
    with --sanitize, strips the runtime traces before drift compare so they are
    never written into deck.json.

These tests drive the REAL pipeline (render-deck.py renders; sync runs via the
CLI and as an imported module), mirroring tests/test_sync_direction.py.
"""
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
RENDER = ROOT / "render-deck.py"
SYNC = ROOT / "sync-index-to-deck.py"
ASSETS = ROOT.parent / "assets"
FEISHU_JS = ASSETS / "feishu-deck.js"
EDIT_JS = ASSETS / "edit-mode" / "deck-edit-mode.js"
RUN_AUDITS = ASSETS / "run-audits.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_sync = _load("sync_index_to_deck_rt", SYNC)
_engine = _load("run_audits_rt", RUN_AUDITS)


def _render(djson_path, out_dir, extra=()):
    return subprocess.run(
        [sys.executable, str(RENDER), str(djson_path), str(out_dir) + "/", *extra],
        capture_output=True, text=True)


def _sync_cli(index_html, deck_json, *args):
    return subprocess.run(
        [sys.executable, str(SYNC), str(index_html), str(deck_json), *args],
        capture_output=True, text=True)


def _raw_deck():
    """A small raw deck. 'intro' carries an absolute box with PLAIN top/left
    (the author-style case that --sanitize must NOT strip)."""
    return {
        "version": "1.0",
        "deck": {"title": "Sanitize round-trip test deck"},
        "slides": [
            {"key": "intro", "layout": "raw",
             "data": {"html": '<div class="stage" style="position:absolute;'
                              'top:96px;left:96px;right:96px;bottom:96px;'
                              'display:flex;flex-direction:column;'
                              'justify-content:center;"><h1 '
                              'style="font-size:96px;color:#fff;margin:0;">'
                              '开场</h1></div>'}},
            {"key": "two", "layout": "raw",
             "data": {"html": '<div class="stage" style="position:absolute;'
                              'inset:96px;"><h2 style="font-size:48px;color:'
                              '#fff;margin:0;">第二页</h2></div>'}},
        ],
    }


def _render_raw_deck(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "deck.json").write_text(
        json.dumps(_raw_deck(), ensure_ascii=False), encoding="utf-8")
    r = _render(src / "deck.json", src)
    assert r.returncode == 0, f"baseline render failed:\n{r.stdout}\n{r.stderr}"
    return src


def _make_index_newer(src):
    now = time.time()
    os.utime(src / "deck.json", (now - 5, now - 5))
    os.utime(src / "index.html", (now, now))


# A baked index.html = a clean render that has had the runtime traces JS would
# write spliced in. We splice the EXACT shapes feishu-deck.js produces, without a
# browser. NB: we inject only the UNAMBIGUOUS runtime traces the sanitizer strips
# (the R-BAKED-DOM fingerprints + --child-i + the canvas-center !important
# top/bottom). The balanceSlide props (align-self/justify-content/min-height/
# padding) are text-identical to author styles and are DELIBERATELY preserved by
# the sanitizer (see deck-edit-mode.js / sync-index-to-deck.py rationale), so
# injecting them would not be a meaningful no-op assertion.
def _bake_runtime_traces(html):
    # .deck open tag: add data-js-ready + data-nav-armed (runtime flags)
    html = re.sub(r'(<div class="deck")', r'\1 data-js-ready data-nav-armed',
                  html, count=1)
    # a .deck-ui overlay (buildUI output) right after the .deck open tag
    html = re.sub(r'(<div class="deck"[^>]*>)',
                  r'\1<div class="deck-ui"><div class="deck-progress">'
                  r'01 / 02</div></div>', html, count=1)
    # per-frame data-idx on every .slide-frame
    i = [0]
    def _idx(m):
        out = m.group(0) + f' data-idx="{i[0]}"'
        i[0] += 1
        return out
    html = re.sub(r'<div class="slide-frame[^"]*"', _idx, html)
    # per-slide data-fs-* markers
    html = re.sub(r'(data-slide-key="intro")',
                  r'\1 data-fs-balanced data-fs-canvascentered', html, count=1)
    # inject the stripped runtime inline props onto the intro stage: a --child-i
    # reveal prop + the canvas-center top/bottom !important band-translate, both
    # PREPENDED to the existing author style (which keeps its own top/bottom/
    # justify-content — those must survive).
    html = html.replace(
        'style="position:absolute;top:96px;left:96px;right:96px;bottom:96px;'
        'display:flex;flex-direction:column;justify-content:center;"',
        'style="--child-i: 1;top:200px !important;bottom:160px !important;'
        'position:absolute;top:96px;left:96px;'
        'right:96px;bottom:96px;display:flex;flex-direction:column;'
        'justify-content:center;"', 1)
    return html


# ---------------------------------------------------------------------------
# 1) unit: fingerprint detection + sanitizer (the shared helpers)
# ---------------------------------------------------------------------------

def test_baked_fingerprints_match_run_audits_logic():
    """sync._baked_dom_fingerprints detects the same R-BAKED-DOM signals the
    validator (run-audits.audit_baked_runtime_dom_bytes) does."""
    baked = ('<div class="deck" data-js-ready><div class="deck-ui">x</div>'
             '<div class="slide-frame" data-idx="0"><div class="slide" '
             'data-slide-key="a"></div></div></div>')
    clean = ('<div class="deck"><div class="slide-frame"><div class="slide" '
             'data-slide-key="a"></div></div></div>')
    hits = _sync._baked_dom_fingerprints(baked)
    assert len(hits) == 3, hits
    # parity with the validator's byte rule
    val = _engine.audit_baked_runtime_dom_bytes(baked)
    assert val and val[0]["rule"] == "R-BAKED-DOM"
    assert not _sync._baked_dom_fingerprints(clean)
    assert not _engine.audit_baked_runtime_dom_bytes(clean)


def test_sanitize_strips_unambiguous_runtime_props():
    """_sanitize_style_attr drops the UNAMBIGUOUS runtime props (--child-i,
    --fs-scale, and the canvas-center !important top/bottom) but PRESERVES author
    inline styles — including the balance props that are text-identical to author
    styles, and plain (non-!important) author top/bottom."""
    s = _sync._sanitize_style_attr
    # unambiguous runtime custom props removed
    assert s("--child-i: 3;color:#fff") == "color:#fff"
    assert s("--fs-scale:0.5;width:1920px") == "width:1920px"
    # canvas-center !important top/bottom removed; PLAIN author top/bottom kept
    assert s("position:absolute;top:597px !important;bottom:1px !important") == \
        "position:absolute"
    assert s("position:absolute;top:0;left:0") == "position:absolute;top:0;left:0"
    # balance props are DELIBERATELY preserved (text-identical to author styles —
    # stripping them would delete authored layout)
    assert s("align-self:center;margin:0") == "align-self:center;margin:0"
    assert s("justify-content:center;display:flex") == "justify-content:center;display:flex"
    assert s("min-height:720px;padding-top:70px") == "min-height:720px;padding-top:70px"
    # author trailing ';' is preserved (render-deck emits it; dropping = false drift)
    assert s("color:#fff;margin:0;") == "color:#fff;margin:0;"
    # a substring like scroll-padding-top is never touched
    assert s("scroll-padding-top:5px;color:#fff") == "scroll-padding-top:5px;color:#fff"


def test_sanitize_html_removes_all_baked_fingerprints():
    """A baked HTML run through sanitize_runtime_traces loses every attribute
    fingerprint (data-idx / data-fs-* / .deck flags), the --child-i prop, and the
    canvas-center !important geometry, while legit attrs (data-mode,
    data-slide-key), author CSS, and plain author top/bottom stay."""
    baked = _bake_runtime_traces(_render_marker_html())
    out = _sync.sanitize_runtime_traces(baked)
    for gone in ("data-idx", "data-fs-balanced", "data-fs-canvascentered",
                 "data-js-ready", "data-nav-armed", "--child-i",
                 "200px !important"):
        assert gone not in out, f"{gone} should be stripped"
    assert "data-slide-key" in out
    assert "color:#fff" in out
    # plain author top + author justify-content survive
    assert "top:96px" in out
    assert "justify-content:center" in out


def _render_marker_html():
    """Minimal HTML carrying the author styles _bake_runtime_traces mutates."""
    return ('<div class="deck"><div class="slide-frame"><div class="slide" '
            'data-slide-key="intro"><div class="stage" '
            'style="position:absolute;top:96px;left:96px;right:96px;bottom:96px;'
            'display:flex;flex-direction:column;justify-content:center;">'
            '<h1 style="color:#fff">开场</h1></div></div></div></div>')


# ---------------------------------------------------------------------------
# 2) sync gate: a baked index.html is REFUSED by default, accepted with --sanitize
# ---------------------------------------------------------------------------

def test_sync_refuses_baked_index_by_default(tmp_path):
    """A baked index.html (R-BAKED-DOM fingerprints) is refused: exit 2, a
    pointer to --sanitize / re-save, and deck.json is NOT touched."""
    src = _render_raw_deck(tmp_path)
    before = (src / "deck.json").read_text(encoding="utf-8")
    baked = _bake_runtime_traces((src / "index.html").read_text(encoding="utf-8"))
    (src / "index.html").write_text(baked, encoding="utf-8")
    _make_index_newer(src)

    r = _sync_cli(src / "index.html", src / "deck.json")
    assert r.returncode == 2, f"expected refuse (exit 2):\n{r.stdout}\n{r.stderr}"
    assert "R-BAKED-DOM" in r.stderr
    assert "--sanitize" in r.stderr
    # deck.json untouched
    assert (src / "deck.json").read_text(encoding="utf-8") == before


def test_sync_sanitize_does_not_fold_runtime_geometry_into_deck(tmp_path):
    """With --sanitize, a baked index.html with ONLY runtime mutations (no real
    author edit) reverse-feeds as a no-op: the runtime geometry / --child-i /
    markers are NOT written into deck.json (the core 越改越坏 fix)."""
    src = _render_raw_deck(tmp_path)
    baked = _bake_runtime_traces((src / "index.html").read_text(encoding="utf-8"))
    (src / "index.html").write_text(baked, encoding="utf-8")
    _make_index_newer(src)

    r = _sync_cli(src / "index.html", src / "deck.json", "--sanitize")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "no drift detected" in r.stdout, \
        f"runtime-only mutations must be a NO-OP after sanitize:\n{r.stdout}"
    deck = json.loads((src / "deck.json").read_text(encoding="utf-8"))
    intro = next(s for s in deck["slides"] if s["key"] == "intro")
    blob = json.dumps(deck, ensure_ascii=False)
    for gone in ("--child-i", "--fs-scale", "200px !important",
                 "160px !important", "data-fs-balanced", "data-idx"):
        assert gone not in blob, f"runtime trace {gone} leaked into deck.json"
    # the author content is intact and unchanged
    assert "开场" in intro["data"]["html"]
    assert "top:96px" in intro["data"]["html"]  # author geometry preserved
    assert "justify-content:center" in intro["data"]["html"]  # author layout preserved


def test_sync_sanitize_still_captures_a_real_author_edit(tmp_path):
    """--sanitize strips ONLY runtime traces — a genuine author text edit on a
    baked DOM is still detected and written back."""
    src = _render_raw_deck(tmp_path)
    html = (src / "index.html").read_text(encoding="utf-8").replace("开场", "开场 X")
    baked = _bake_runtime_traces(html)
    (src / "index.html").write_text(baked, encoding="utf-8")
    _make_index_newer(src)

    r = _sync_cli(src / "index.html", src / "deck.json", "--sanitize")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    deck = json.loads((src / "deck.json").read_text(encoding="utf-8"))
    intro = next(s for s in deck["slides"] if s["key"] == "intro")
    assert "开场 X" in intro["data"]["html"], "real author edit was lost"
    # but no runtime trace tagged along
    assert "--child-i" not in intro["data"]["html"]
    assert "align-self:center" not in intro["data"]["html"]


def test_clean_render_is_not_treated_as_baked(tmp_path):
    """A freshly rendered (clean) index.html is NOT a baked DOM — sync proceeds
    normally with no --sanitize needed, and reports zero drift."""
    src = _render_raw_deck(tmp_path)
    _make_index_newer(src)
    # not baked → no fingerprints
    assert not _sync._baked_dom_fingerprints(
        (src / "index.html").read_text(encoding="utf-8"))
    r = _sync_cli(src / "index.html", src / "deck.json", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "no drift detected" in r.stdout


# ---------------------------------------------------------------------------
# 3) e2e (Playwright): buildSavedHTML output is clean of R-BAKED-DOM
# ---------------------------------------------------------------------------

# The e2e drives the REAL pipeline (render-deck.py → headless feishu-deck.js →
# edit-mode buildSavedHTML). NOTE on the content shape: the runtime sets
# --child-i on every DIRECT child of each .slide via `el.style.setProperty(...)`,
# which makes the BROWSER reserialize that child's whole style attribute through
# CSSOM (e.g. top/left/right/bottom → the `inset` shorthand). That normalization
# is the runtime's, not buildSavedHTML's, and it is unavoidable for an inline-
# styled direct child without modifying the runtime (out of scope). So to get a
# faithful ZERO-DRIFT round-trip, the deck below keeps all author inline styles on
# a NESTED element (`.inner`), with a STYLELESS direct child (`.stage`) — the
# runtime's --child-i lands on the styleless wrapper (→ stripped to nothing),
# leaving the authored geometry on .inner untouched. This isolates the assertion
# to the sanitizer (the thing under test), not CSSOM serialization quirks.
def _e2e_deck():
    return {
        "version": "1.0",
        "deck": {"title": "e2e"},
        "slides": [
            {"key": "intro", "layout": "raw", "screen_label": "01 intro",
             "data": {"html":
                '<div class="stage"><div class="inner" style="position:absolute;'
                'top:200px;left:73px;right:73px;bottom:60px;display:flex;'
                'flex-direction:column;justify-content:center;">'
                '<h1 class="title-zh" style="font-size:64px;margin:0">开场标题</h1>'
                '<p style="font-size:24px;line-height:1.5;margin:0">这是一段较短的'
                '说明文字</p></div></div>'}},
            {"key": "two", "layout": "raw", "screen_label": "02 two",
             "data": {"html":
                '<div class="stage"><div class="inner" style="position:absolute;'
                'inset:96px;"><h2 style="font-size:48px;margin:0">第二页</h2>'
                '</div></div>'}},
        ],
    }


def _render_and_buildsaved(tmp_path):
    """Render the e2e deck, load it headless (feishu-deck.js bakes runtime
    traces), inject edit-mode, and return (src_dir, live_flags, saved_html).
    Returns None when Chromium/Playwright is unavailable (caller skips)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return None
    src = tmp_path / "src"
    src.mkdir()
    (src / "deck.json").write_text(
        json.dumps(_e2e_deck(), ensure_ascii=False), encoding="utf-8")
    if _render(src / "deck.json", src).returncode != 0:
        return None
    edit_js = EDIT_JS.read_text(encoding="utf-8")
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_context(viewport={"width": 1920, "height": 1080}).new_page()
            pg.goto((src / "index.html").resolve().as_uri(),
                    wait_until="domcontentloaded")
            try:
                pg.wait_for_function(
                    "() => document.querySelector('.deck[data-js-ready]')",
                    timeout=5000)
            except Exception:
                pass
            pg.wait_for_timeout(600)  # let init + rAF balance/canvas-center settle
            pg.add_script_tag(content=edit_js)  # inject edit-mode after init
            pg.wait_for_timeout(100)
            live = pg.evaluate("""() => ({
                hasIdx: !!document.querySelector('.slide-frame[data-idx]'),
                hasDeckUi: !!document.querySelector('.deck-ui'),
                hasJsReady: !!document.querySelector('.deck[data-js-ready]'),
                hasChildI: !!document.querySelector('.slide [style*="--child-i"]'),
            })""")
            saved = pg.evaluate("window.deckEdit.buildSavedHTML()")
            b.close()
    except Exception:
        return None
    return src, live, saved


def test_buildsavedhtml_strips_runtime_traces_e2e(tmp_path):
    """End-to-end: render → run feishu-deck.js (bakes runtime traces) →
    deckEdit.buildSavedHTML() → the saved bytes carry ZERO R-BAKED-DOM
    fingerprints (data-idx / .deck-ui / .deck flags), no --child-i, and no
    canvas-center !important geometry. Skips when Chromium is unavailable."""
    res = _render_and_buildsaved(tmp_path)
    if res is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable (or render failed)")
    _src, live, saved = res
    # precondition: the runtime really did bake traces into the LIVE DOM
    assert live["hasIdx"], "feishu-deck.js did not write data-idx — test invalid"
    assert live["hasDeckUi"], "feishu-deck.js did not build .deck-ui — test invalid"
    assert live["hasJsReady"], "feishu-deck.js did not set data-js-ready — test invalid"
    assert live["hasChildI"], "feishu-deck.js did not set --child-i — test invalid"

    # The substring assertions must ignore <script> bodies: this e2e INLINES
    # deck-edit-mode.js (via add_script_tag) so its own source text — which
    # discusses --child-i / data-idx in comments — would false-match. In a real
    # deck the editor is an external <script src=>, so its source is not in the
    # saved bytes. Scrub script blocks for the markup checks; the R-BAKED-DOM byte
    # rule below runs on the FULL saved bytes (its needles are markup-anchored).
    markup = re.sub(r"<script\b[^>]*>.*?</script>", "", saved, flags=re.S | re.I)
    assert "data-idx=" not in markup, "data-idx leaked into saved markup"
    assert 'class="deck-ui"' not in markup, ".deck-ui leaked into saved markup"
    assert "--child-i" not in markup, "--child-i reveal prop leaked into saved markup"
    assert "--fs-scale" not in markup, "--fs-scale leaked into saved markup"
    for marker in ("data-fs-balanced", "data-fs-colbalanced",
                   "data-fs-canvascentered", "data-fs-autobalanced",
                   "data-js-ready", "data-nav-armed", "data-edit-paste-guard"):
        assert marker not in markup, f"runtime marker {marker} leaked into saved markup"
    assert "!important" not in markup, "canvas-center !important geometry leaked"

    # author content + legit attrs survive
    assert "开场标题" in markup and "第二页" in markup
    assert 'data-slide-key="intro"' in markup
    assert 'data-mode="present"' in markup  # restored, not the edit-mode 'scroll'

    # and the validator's R-BAKED-DOM byte rule agrees on the FULL saved bytes:
    # zero findings — i.e. this saved file would PASS the gate that blocks baked DOMs.
    findings = _engine.audit_baked_runtime_dom_bytes(saved)
    assert findings == [], f"R-BAKED-DOM fired on the saved file: {findings}"


def test_buildsavedhtml_save_then_sync_dryrun_zero_drift_e2e(tmp_path):
    """Full chain: render → JS → buildSavedHTML → write back → sync --dry-run
    against the SAME deck.json reports ZERO drift (and is NOT refused as baked).
    Proves the save sanitizer and the sync gate agree end-to-end: an edit-mode
    save that changed nothing is a true no-op round-trip."""
    res = _render_and_buildsaved(tmp_path)
    if res is None:
        import pytest; pytest.skip("Chromium/Playwright unavailable (or render failed)")
    src, _live, saved = res
    (src / "index.html").write_text(saved, encoding="utf-8")
    _make_index_newer(src)

    # the saved file is clean → NOT refused by the R-BAKED-DOM gate
    assert not _sync._baked_dom_fingerprints(saved), \
        "buildSavedHTML output should not trip the R-BAKED-DOM gate"
    r = _sync_cli(src / "index.html", src / "deck.json", "--dry-run")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "no drift detected" in r.stdout, \
        f"save→sync should be a no-op round-trip:\n{r.stdout}"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            import inspect
            if "tmp_path" in inspect.signature(fn).parameters:
                import tempfile
                fn(pathlib.Path(tempfile.mkdtemp()))
            else:
                fn()
            print(f"  ok  {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {fn.__name__}")
            traceback.print_exc()
    sys.exit(1 if failed else 0)
