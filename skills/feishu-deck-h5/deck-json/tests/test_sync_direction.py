"""sync-index-to-deck — direction guard + coverage-blackhole fixes (F-273).

`sync-index-to-deck.py` ports post-render edits from index.html back into
deck.json. Three randomness sources made delivery unstable ("edited but it
reverted", "reported green but didn't sync"):

  1. DIRECTION GUARD — the tool assumed index.html is always the newer side.
     If you edit deck.json and forget to re-render, a full sync silently feeds
     the STALE index.html back over those edits. Now: when deck.json is newer
     than index.html (beyond a small tolerance) a full sync refuses to write,
     prints a hard warning, and downgrades to dry-run. --index-is-newer
     overrides. The normal render→sync direction (index.html newer) is
     UNAFFECTED.

  2. COVERAGE BLACKHOLES — a default full sync reported "no drift" while
     dropping (a) custom_css block edits, (b) hidden flag + speaker notes
     (previously reachable only via their own flags). Now all are in the
     default path.

  3. TEMPLATE slides — a template (cover/quote/...) slide with browser edits
     used to be a SILENT skip. Now it is a loud WARNING.

These tests drive the REAL pipeline (render-deck.py renders; sync runs via the
CLI and as an imported module), mirroring tests/test_backfill.py.
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


def _load_sync_module():
    spec = importlib.util.spec_from_file_location("sync_index_to_deck", SYNC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_sync = _load_sync_module()


def _render(djson_path, out_dir, extra=()):
    return subprocess.run(
        [sys.executable, str(RENDER), str(djson_path), str(out_dir) + "/", *extra],
        capture_output=True, text=True)


def _sync_cli(index_html, deck_json, *args):
    return subprocess.run(
        [sys.executable, str(SYNC), str(index_html), str(deck_json), *args],
        capture_output=True, text=True)


def _raw_deck():
    """A small raw deck with one custom_css slide (the real round-trip target)."""
    return {
        "version": "1.0",
        "deck": {"title": "Sync-direction test deck"},
        "slides": [
            {"key": "intro", "layout": "raw",
             "custom_css": ".hero{letter-spacing:.04em}",
             "data": {"html": '<div class="stage" style="position:absolute;'
                              'inset:96px;display:flex;flex-direction:column;'
                              'justify-content:center;"><h1 class="hero" '
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
    """Bump index.html mtime so it is clearly newer than deck.json (the NORMAL
    post-render-edit direction) — isolates non-direction tests from the guard."""
    now = time.time()
    os.utime(src / "deck.json", (now - 5, now - 5))
    os.utime(src / "index.html", (now, now))


# ---------------------------------------------------------------------------
# 1) DIRECTION GUARD
# ---------------------------------------------------------------------------

def test_direction_guard_blocks_when_deckjson_is_newer(tmp_path):
    """deck.json newer than index.html (edited-but-not-rendered) → a default
    full sync refuses to write, warns, and downgrades to dry-run."""
    src = _render_raw_deck(tmp_path)
    # introduce REAL drift in index.html so there would be something to write
    html = (src / "index.html").read_text(encoding="utf-8").replace("开场", "开场 X")
    (src / "index.html").write_text(html, encoding="utf-8")
    before = (src / "deck.json").read_text(encoding="utf-8")

    # make deck.json ~10s NEWER than index.html → wrong direction
    now = time.time()
    os.utime(src / "index.html", (now - 10, now - 10))
    os.utime(src / "deck.json", (now, now))

    r = _sync_cli(src / "index.html", src / "deck.json")
    assert r.returncode == 0, r.stderr            # safety downgrade, not an error
    assert "DIRECTION GUARD" in r.stderr
    assert "re-render" in r.stderr.lower()
    assert "--index-is-newer" in r.stderr
    # NOT written: deck.json is byte-identical, the stale edit was NOT fed back
    assert (src / "deck.json").read_text(encoding="utf-8") == before
    assert "开场 X" not in (src / "deck.json").read_text(encoding="utf-8")


def test_direction_guard_override_writes(tmp_path):
    """--index-is-newer overrides the guard and reverse-feeds anyway."""
    src = _render_raw_deck(tmp_path)
    html = (src / "index.html").read_text(encoding="utf-8").replace("开场", "开场 X")
    (src / "index.html").write_text(html, encoding="utf-8")
    now = time.time()
    os.utime(src / "index.html", (now - 10, now - 10))
    os.utime(src / "deck.json", (now, now))

    r = _sync_cli(src / "index.html", src / "deck.json", "--index-is-newer")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "DIRECTION GUARD" not in r.stderr
    deck = json.loads((src / "deck.json").read_text(encoding="utf-8"))
    intro = next(s for s in deck["slides"] if s["key"] == "intro")
    assert "开场 X" in intro["data"]["html"]


def test_force_direction_is_an_alias(tmp_path):
    """--force-direction is accepted as an alias of --index-is-newer."""
    src = _render_raw_deck(tmp_path)
    html = (src / "index.html").read_text(encoding="utf-8").replace("开场", "开场 Y")
    (src / "index.html").write_text(html, encoding="utf-8")
    now = time.time()
    os.utime(src / "index.html", (now - 10, now - 10))
    os.utime(src / "deck.json", (now, now))
    r = _sync_cli(src / "index.html", src / "deck.json", "--force-direction")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    deck = json.loads((src / "deck.json").read_text(encoding="utf-8"))
    intro = next(s for s in deck["slides"] if s["key"] == "intro")
    assert "开场 Y" in intro["data"]["html"]


def test_normal_direction_is_unaffected_backward_compat(tmp_path):
    """The render→sync flow (index.html newer) never trips the guard and writes
    as before. This is the backward-compatibility contract."""
    src = _render_raw_deck(tmp_path)
    html = (src / "index.html").read_text(encoding="utf-8").replace("开场", "开场 Z")
    (src / "index.html").write_text(html, encoding="utf-8")
    _make_index_newer(src)  # index.html newer = normal post-render-edit direction

    r = _sync_cli(src / "index.html", src / "deck.json")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "DIRECTION GUARD" not in r.stderr
    assert "wrote" in r.stdout
    deck = json.loads((src / "deck.json").read_text(encoding="utf-8"))
    intro = next(s for s in deck["slides"] if s["key"] == "intro")
    assert "开场 Z" in intro["data"]["html"]


def test_wrong_direction_helper_tolerance():
    """_wrong_direction trips only when deck.json is newer beyond the tolerance;
    equal / index-newer / within-slack all return None (fail-safe)."""
    fn = _sync._wrong_direction
    tol = _sync._DIRECTION_TOLERANCE_S

    class _P:
        def __init__(self, mt):
            self._mt = mt

        def stat(self):
            class _S:
                pass
            s = _S()
            s.st_mtime = self._mt
            return s

    # deck.json newer by 10s → wrong direction (returns the delta)
    assert fn(_P(110.0), _P(100.0)) == 10.0
    # index.html newer → fine
    assert fn(_P(100.0), _P(110.0)) is None
    # within tolerance → fine (normal render writes both back-to-back)
    assert fn(_P(100.0 + tol / 2), _P(100.0)) is None
    # exactly equal → fine
    assert fn(_P(100.0), _P(100.0)) is None


# ---------------------------------------------------------------------------
# 2a) custom_css coverage blackhole
# ---------------------------------------------------------------------------

def test_custom_css_drift_detected_and_written_back(tmp_path):
    """Editing the <style data-fs-custom-css> block in index.html is now real
    drift (was silently dropped + reported "no drift")."""
    src = _render_raw_deck(tmp_path)
    html = (src / "index.html").read_text(encoding="utf-8")
    assert "letter-spacing:.04em" in html
    html = html.replace("letter-spacing:.04em", "letter-spacing:.12em")
    (src / "index.html").write_text(html, encoding="utf-8")
    _make_index_newer(src)

    # dry-run: the custom_css drift is reported (NOT a false green)
    dry = _sync_cli(src / "index.html", src / "deck.json", "--dry-run")
    assert dry.returncode == 0, dry.stderr
    assert "custom_css" in dry.stdout
    assert "no drift detected" not in dry.stdout

    # write: the field is updated
    w = _sync_cli(src / "index.html", src / "deck.json")
    assert w.returncode == 0, w.stderr
    deck = json.loads((src / "deck.json").read_text(encoding="utf-8"))
    intro = next(s for s in deck["slides"] if s["key"] == "intro")
    assert "letter-spacing:.12em" in intro["custom_css"]


def test_custom_css_no_false_positive_round_trips(tmp_path):
    """A freshly rendered deck reports ZERO custom_css drift, and after a
    write-back a re-run is a no-op (the stored scoped form round-trips)."""
    src = _render_raw_deck(tmp_path)
    _make_index_newer(src)
    r = _sync_cli(src / "index.html", src / "deck.json", "--dry-run")
    assert "no drift detected" in r.stdout, r.stdout
    assert "custom_css" not in r.stdout  # the unedited block is not flagged

    # edit + write, then a second dry-run must be clean
    html = (src / "index.html").read_text(encoding="utf-8").replace(
        "letter-spacing:.04em", "letter-spacing:.20em")
    (src / "index.html").write_text(html, encoding="utf-8")
    _make_index_newer(src)
    assert _sync_cli(src / "index.html", src / "deck.json").returncode == 0
    _make_index_newer(src)
    again = _sync_cli(src / "index.html", src / "deck.json", "--dry-run")
    assert "no drift detected" in again.stdout, again.stdout


# ---------------------------------------------------------------------------
# 2b) hidden / notes coverage blackhole (default full sync)
# ---------------------------------------------------------------------------

def test_default_full_sync_reconciles_hidden_and_notes(tmp_path):
    """hidden + notes used to need --hidden-only / --notes-only; the default
    full sync now reconciles them (lossless idempotent)."""
    src = _render_raw_deck(tmp_path)
    html = (src / "index.html").read_text(encoding="utf-8")
    # toggle slide 'two' hidden via data-hidden on its open tag
    html = re.sub(r'(<div class="slide[^"]*"[^>]*data-slide-key="two")',
                  r'\1 data-hidden', html, count=1)
    # set a speaker note on 'intro' via the #fs-deck-notes island
    m = re.search(r'(<script type="application/json" id="fs-deck-notes">)(.*?)(</script>)',
                  html, re.S)
    note_obj = {"intro": "开场口播稿"}
    if m:
        existing = m.group(2).strip()
        cur = json.loads(existing.replace('<\\/', '</')) if existing else {}
        cur.update(note_obj)
        html = html[:m.start(2)] + json.dumps(cur, ensure_ascii=False) + html[m.end(2):]
    else:
        html = html.replace(
            "</body>",
            '<script type="application/json" id="fs-deck-notes">'
            + json.dumps(note_obj, ensure_ascii=False) + '</script></body>')
    (src / "index.html").write_text(html, encoding="utf-8")
    _make_index_newer(src)

    r = _sync_cli(src / "index.html", src / "deck.json")
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "[hidden]" in r.stdout and "[notes]" in r.stdout
    deck = json.loads((src / "deck.json").read_text(encoding="utf-8"))
    two = next(s for s in deck["slides"] if s["key"] == "two")
    intro = next(s for s in deck["slides"] if s["key"] == "intro")
    assert two.get("hidden") is True, "hidden not synced in DEFAULT path"
    assert intro.get("notes") == "开场口播稿", "notes not synced in DEFAULT path"


# ---------------------------------------------------------------------------
# 2c) template slide drift → loud WARNING (not silent)
# ---------------------------------------------------------------------------

def _cover_deck():
    return {
        "version": "1.0",
        "deck": {"title": "Cover-drift test deck"},
        "slides": [
            {"key": "cover", "layout": "cover", "screen_label": "01 Cover",
             "data": {"title": "原标题", "author": "作者", "date": "2026"}},
            {"key": "two", "layout": "raw",
             "data": {"html": '<div class="stage" style="position:absolute;'
                              'inset:96px;"><h2 style="font-size:48px;color:'
                              '#fff;margin:0;">第二页</h2></div>'}},
        ],
    }


def test_template_slide_drift_is_a_loud_warning(tmp_path):
    """A cover (template) slide edited in the browser is no longer a silent
    skip — sync prints a WARNING that the edits will be lost, and does NOT
    silently convert the slide to raw."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "deck.json").write_text(
        json.dumps(_cover_deck(), ensure_ascii=False), encoding="utf-8")
    assert _render(src / "deck.json", src).returncode == 0

    html = (src / "index.html").read_text(encoding="utf-8")
    assert "原标题" in html
    html = html.replace("原标题", "改过的标题")
    (src / "index.html").write_text(html, encoding="utf-8")
    _make_index_newer(src)

    r = _sync_cli(src / "index.html", src / "deck.json", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "WARNING" in r.stdout and "TEMPLATE" in r.stdout
    assert "cover" in r.stdout and "LOSSY" in r.stdout
    # and the slide stayed a cover (no silent raw conversion)
    deck = json.loads((src / "deck.json").read_text(encoding="utf-8"))
    assert deck["slides"][0]["layout"] == "cover"
