"""backfill — create a deck.json FROM SCRATCH out of an HTML-only legacy deck.

DECKJSON-UNIFIED-INTERMEDIATE-SPEC §5: a LEGACY deck that is HTML-only (no
deck.json) must, when operated on, get its deck.json `中间层` backfilled by
reverse-engineering the REAL rendered DOM (lossless, NO screenshots). Source =
HTML → reverse from the actual code, more precise than any image.

These tests drive the REAL pipeline:
  - render-deck.py (the schema + validate gate; a passing render = valid)
  - sync-index-to-deck.py backfill (imported as a module + via the CLI)

The acceptance contract (spec §5 / §9):
  - self-rendered feishu deck (data-slide-key) → EXACT raw slides, lifted-marked
  - foreign HTML (no data-slide-key) → best-effort, never crashes
  - round-trips: after backfill, sync-index-to-deck on the same index.html is a
    no-op (zero drift)
"""
import importlib.util
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
RENDER = ROOT / "render-deck.py"
SYNC = ROOT / "sync-index-to-deck.py"


def _load_sync_module():
    spec = importlib.util.spec_from_file_location("sync_index_to_deck", SYNC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_sync = _load_sync_module()


def _dom_keys(html: str):
    return re.findall(
        r'<div class="slide(?:\s[^"]*)?"[^>]*data-slide-key="([^"]+)"', html)


def _legacy_raw_deck():
    """A realistic legacy RAW deck (self-contained inline CSS + one custom_css).
    This is the actual backfill target — raw HTML whose visual is fully carried
    in the slide itself, so schema→raw conversion is lossless."""
    return {
        "version": "1.0",
        "deck": {"title": "Legacy raw deck (backfill target)"},
        "slides": [
            {"key": "intro", "layout": "raw", "screen_label": "01 开场",
             "custom_css": ".hero{letter-spacing:.04em}",
             "data": {"html": '<div class="stage" style="position:absolute;'
                              'inset:96px;display:flex;flex-direction:column;'
                              'justify-content:center;"><h1 class="hero" '
                              'style="font-size:96px;color:#fff;margin:0;">遗留'
                              ' HTML 演示</h1><p style="font-size:32px;color:'
                              'rgba(255,255,255,.7);margin:24px 0 0;">没有 '
                              'deck.json，只有 index.html</p></div>'}},
            {"key": "detail", "layout": "raw", "screen_label": "02 细节",
             "data": {"html": '<div class="stage" style="position:absolute;'
                              'inset:96px;"><h2 style="font-size:48px;color:'
                              '#fff;margin:0;">第二页</h2><p style="font-size:'
                              '28px;color:rgba(255,255,255,.8);margin:32px 0 0;'
                              'line-height:1.6;">这一页样式全内联，反推无损。'
                              '</p></div>'}},
            {"key": "finale", "layout": "raw", "screen_label": "03 收尾",
             "data": {"html": '<div class="stage" style="position:absolute;'
                              'inset:96px;display:flex;align-items:center;'
                              'justify-content:center;"><h2 style="font-size:'
                              '64px;color:#fff;margin:0;">谢谢</h2></div>'}},
        ],
    }


def _render(djson_path, out_dir, extra=()):
    r = subprocess.run(
        [sys.executable, str(RENDER), str(djson_path), str(out_dir) + "/", *extra],
        capture_output=True, text=True)
    return r


# ---------------------------------------------------------------------------
# unit-level (module import) — backfill_deck()
# ---------------------------------------------------------------------------

def test_backfill_native_exact_keys_and_lifted():
    html = (
        '<html><head><title>My Deck</title></head><body>'
        '<div class="slide" data-layout="raw" data-screen-label="01 A" '
        'data-slide-key="alpha"><div class="wordmark">飞书</div>'
        '<h2>Alpha</h2></div>'
        '<div class="slide" data-layout="raw" data-screen-label="02 B" '
        'data-slide-key="beta"><div class="wordmark">飞书</div>'
        '<p>Beta body</p></div>'
        '</body></html>')
    deck, warnings = _sync.backfill_deck(html, "mydeck")
    assert deck["version"] == "1.0"
    assert deck["deck"]["title"] == "My Deck"
    assert [s["key"] for s in deck["slides"]] == ["alpha", "beta"]
    for s in deck["slides"]:
        assert s["layout"] == "raw"
        assert s["lifted"].startswith("backfill:mydeck#")
        # wordmark stripped from carried inner
        assert "wordmark" not in s["data"]["html"]
    assert deck["slides"][0]["screen_label"] == "01 A"
    assert "Alpha" in deck["slides"][0]["data"]["html"]
    assert warnings == []  # native = clean


def test_backfill_captures_custom_css_scoped():
    # the rendered shape of a slide's leading data-fs-custom-css block: backfill
    # must capture it into custom_css and keep it OUT of data.html
    html = (
        '<html><body>'
        '<div class="slide" data-slide-key="x">'
        '<style data-slide-key="x" data-fs-custom-css>\n'
        '.slide[data-slide-key="x"] .hero {letter-spacing:.04em}\n'
        '        </style>\n        <div class="wordmark">飞书</div>'
        '<h1 class="hero">Hi</h1></div>'
        '</body></html>')
    deck, _ = _sync.backfill_deck(html, "d")
    s = deck["slides"][0]
    assert "letter-spacing" in s.get("custom_css", "")
    # css block must NOT leak into data.html (else re-render doubles it)
    assert "data-fs-custom-css" not in s["data"]["html"]
    assert "letter-spacing" not in s["data"]["html"]


def test_backfill_foreign_slide_divs_generate_keys():
    html = (
        '<html><head><title>Foreign</title></head><body>'
        '<div class="slide" id="opening"><h1>Welcome</h1></div>'
        '<div class="slide" data-name="Agenda"><h2>Agenda</h2></div>'
        '<div class="slide"><h3>Nested title</h3></div>'
        '</body></html>')
    deck, warnings = _sync.backfill_deck(html, "f")
    keys = [s["key"] for s in deck["slides"]]
    assert keys == ["opening", "agenda", "nested-title"]
    assert all(re.fullmatch(r"[a-z][a-z0-9-]*", k) for k in keys)
    assert all(s["layout"] == "raw" for s in deck["slides"])
    assert any("FOREIGN" in w for w in warnings)


def test_backfill_foreign_sections():
    html = (
        '<html><head><title>S</title></head><body>'
        '<section id="s-one"><h2>One</h2></section>'
        '<section><p>two</p></section>'
        '</body></html>')
    deck, _ = _sync.backfill_deck(html, "s")
    keys = [s["key"] for s in deck["slides"]]
    assert keys[0] == "s-one"
    assert keys[1] == "slide-2"  # no id → positional fallback


def test_backfill_foreign_unrecognized_single_slide():
    html = ('<html><head><title>Blob</title></head><body>'
            '<main><p>a wall of content with no slide structure</p></main>'
            '</body></html>')
    deck, warnings = _sync.backfill_deck(html, "b")
    assert len(deck["slides"]) == 1
    assert re.fullmatch(r"[a-z][a-z0-9-]*", deck["slides"][0]["key"])
    assert any("unrecognizable" in w for w in warnings)


def test_backfill_dedupes_collided_slide_keys():
    html = (
        '<html><body>'
        '<div class="slide" data-slide-key="dup"><h2>A</h2></div>'
        '<div class="slide" data-slide-key="dup"><h2>B</h2></div>'
        '</body></html>')
    deck, warnings = _sync.backfill_deck(html, "d")
    keys = [s["key"] for s in deck["slides"]]
    assert len(set(keys)) == 2  # uniqueness enforced
    assert any("duplicate" in w for w in warnings)


def test_backfill_never_crashes_on_empty_body():
    deck, warnings = _sync.backfill_deck("<html><body></body></html>", "e")
    # one last-resort slide of an empty body would be empty → dropped → 0 slides
    assert isinstance(deck["slides"], list)
    assert any("reconstructed" in w or "unrecognizable" in w for w in warnings)


# ---------------------------------------------------------------------------
# end-to-end through the REAL pipeline (render → backfill → re-render → sync)
# ---------------------------------------------------------------------------

def test_e2e_render_backfill_rerender_equivalence_and_zero_drift(tmp_path):
    """Spec §5 acceptance: render a legacy raw deck → move deck.json aside →
    backfill from index.html → re-render → equivalent (same count + keys) AND
    re-render PASSES the gate AND sync-index-to-deck is zero-drift."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "deck.json").write_text(
        json.dumps(_legacy_raw_deck(), ensure_ascii=False), encoding="utf-8")
    r0 = _render(src / "deck.json", src)
    assert r0.returncode == 0, f"baseline render failed:\n{r0.stdout}\n{r0.stderr}"
    orig_html = (src / "index.html").read_text(encoding="utf-8")
    orig_keys = _dom_keys(orig_html)
    assert orig_keys == ["intro", "detail", "finale"]

    # move deck.json aside, then BACKFILL via the CLI (auto-engages: absent target)
    (src / "deck.json").rename(src / "deck.json.orig")
    bf = subprocess.run(
        [sys.executable, str(SYNC), str(src / "index.html"), str(src / "deck.json")],
        capture_output=True, text=True)
    assert bf.returncode == 0, f"backfill failed:\n{bf.stdout}\n{bf.stderr}"
    assert (src / "deck.json").exists()

    backfilled = json.loads((src / "deck.json").read_text(encoding="utf-8"))
    assert [s["key"] for s in backfilled["slides"]] == orig_keys
    assert all(s["layout"] == "raw" for s in backfilled["slides"])
    assert all(s["lifted"].startswith("backfill:") for s in backfilled["slides"])
    # custom_css from the intro slide was captured
    intro = next(s for s in backfilled["slides"] if s["key"] == "intro")
    assert "letter-spacing" in intro.get("custom_css", "")

    # re-render the backfilled deck.json — must PASS and reproduce keys/count
    out2 = tmp_path / "out2"
    out2.mkdir()
    (out2 / "deck.json").write_text(
        json.dumps(backfilled, ensure_ascii=False), encoding="utf-8")
    r2 = _render(out2 / "deck.json", out2)
    assert r2.returncode == 0, f"re-render of backfilled deck failed:\n{r2.stdout}\n{r2.stderr}"
    re_keys = _dom_keys((out2 / "index.html").read_text(encoding="utf-8"))
    assert re_keys == orig_keys, "slide keys changed across backfill→re-render"

    # ZERO-DRIFT: sync the original index.html against the backfilled deck.json
    drift = subprocess.run(
        [sys.executable, str(SYNC), str(src / "index.html"),
         str(src / "deck.json"), "--dry-run"],
        capture_output=True, text=True)
    assert drift.returncode == 0
    assert "no drift detected" in drift.stdout, \
        f"backfill did not round-trip (drift):\n{drift.stdout}"

    # and zero-drift on the freshly re-rendered index.html too
    drift2 = subprocess.run(
        [sys.executable, str(SYNC), str(out2 / "index.html"),
         str(out2 / "deck.json"), "--dry-run"],
        capture_output=True, text=True)
    assert "no drift detected" in drift2.stdout, drift2.stdout


def test_e2e_explicit_backfill_flag_with_existing_deck(tmp_path):
    """--backfill explicitly creates from index.html even when a deck.json
    already exists (backs it up first)."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "deck.json").write_text(
        json.dumps(_legacy_raw_deck(), ensure_ascii=False), encoding="utf-8")
    assert _render(src / "deck.json", src).returncode == 0

    bf = subprocess.run(
        [sys.executable, str(SYNC), str(src / "index.html"),
         str(src / "deck.json"), "--backfill"],
        capture_output=True, text=True)
    assert bf.returncode == 0, bf.stderr
    # a pre-backfill backup was made
    assert any(p.name.startswith("deck.json.bak-pre-backfill-")
               for p in src.iterdir())
    rebuilt = json.loads((src / "deck.json").read_text(encoding="utf-8"))
    assert all(s["lifted"].startswith("backfill:") for s in rebuilt["slides"])


def test_backfill_duplicate_slide_key_keeps_distinct_bodies(tmp_path):
    """sync-3: when index.html has duplicate data-slide-key values, each
    duplicate-keyed slide must backfill its OWN body/label/custom_css — NOT a
    copy of the first slide's content. (The old by-key re.search path returned
    slide[0]'s content for every duplicate, silently losing the rest.)"""
    html = (
        "<html><head><title>Dup test</title></head><body><div class=\"deck\">\n"
        '<div class="slide" data-slide-key="dup" data-screen-label="First">'
        '<div class="wordmark">WM</div><p>FIRST BODY</p></div>\n'
        '<div class="slide" data-slide-key="dup" data-screen-label="Second">'
        '<div class="wordmark">WM</div><p>SECOND BODY DISTINCT</p></div>\n'
        "</div></body></html>"
    )
    deck, warnings = _sync.backfill_deck(html, "duptest")
    assert len(deck["slides"]) == 2
    s0, s1 = deck["slides"]
    # distinct bodies (the bug folded slide[1] into slide[0]'s body)
    assert "FIRST BODY" in s0["data"]["html"]
    assert "SECOND BODY DISTINCT" in s1["data"]["html"], \
        "duplicate-keyed slide lost its own body (sync-3 regression)"
    assert "FIRST BODY" not in s1["data"]["html"]
    # distinct labels, and the collided key was renamed (not bodies)
    assert s0.get("screen_label") == "First"
    assert s1.get("screen_label") == "Second"
    assert s0["key"] == "dup" and s1["key"] != "dup"
    assert any("renamed" in w for w in warnings)
