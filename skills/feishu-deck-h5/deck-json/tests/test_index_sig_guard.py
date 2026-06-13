"""F-315 · clobber-guard tests.

Locks the fix for the silent data-loss bug: a colleague edits a rendered deck in
the browser edit-mode (`e` + ⌘S — writes index.html ONLY), then an AI edits other
pages and a re-render regenerates index.html from the untouched deck.json, wiping
the colleague's edits.

Covered:
  • _index_sig.verify: ok / edited / unstamped
  • _index_sig.guard_should_refuse: refuses on un-synced edit, passes once
    deck.json is newer (a sync folded the edits in)
  • render-deck.py stamps a sig and REFUSES (exit 8) to overwrite an edited
    index.html; --force overrides
  • deck-cli.py write commands REFUSE (exit 6) when the sibling index.html is
    edited; --force overrides
  • the normal set-page→render loop is NOT tripped (no false positive)
"""
import os
import re
import subprocess
import sys
import time
import pathlib

import pytest

DECKJSON = pathlib.Path(__file__).resolve().parents[1]
RENDER = DECKJSON / "render-deck.py"
DECKCLI = DECKJSON / "deck-cli.py"
SAMPLE = DECKJSON / "examples" / "sample-deck.json"

sys.path.insert(0, str(DECKJSON))
import _index_sig as sig  # noqa: E402


def _run(*argv):
    return subprocess.run([sys.executable, *map(str, argv)],
                          capture_output=True, text=True)


def _render(deck, outdir, *extra):
    r = _run(RENDER, deck, str(outdir) + "/", "--iter", *extra)
    return r


@pytest.fixture
def rendered(tmp_path):
    """A freshly rendered sample deck: deck.json + a sig-stamped index.html."""
    deck = tmp_path / "deck.json"
    deck.write_text(SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    r = _render(deck, tmp_path)
    assert r.returncode == 0, f"render failed:\n{r.stdout}\n{r.stderr}"
    index = tmp_path / "index.html"
    assert index.is_file()
    return tmp_path, deck, index


def _simulate_browser_edit(index: pathlib.Path):
    """Mimic an edit-mode ⌘S save: change the text of a real slide text field
    (a data-text-id element — exactly what edit-mode makes contenteditable), keep
    every meta (incl. the now-stale fs-render-sig), and bump mtime to 'after the
    render'. Targeting a slide field (not <head>/chrome) means the edit is both
    sig-breaking AND recoverable by sync-index-to-deck.py."""
    html = index.read_text(encoding="utf-8")
    m = re.search(r'(data-text-id="[^"]+"[^>]*>)([^<]{3,})(</)', html)
    assert m, "no data-text-id slide field to edit in sample render"
    html = html[:m.start(2)] + "COLLEAGUE-EDIT-XYZ" + html[m.end(2):]
    index.write_text(html, encoding="utf-8")
    # The write sets mtime to 'now', which is after the render (render aligned
    # index.html's mtime to deck.json's) → index.html is naturally newer than
    # deck.json, the un-synced-edit direction the guard refuses on.


# ---------------------------------------------------------------- unit: sig ---
def test_sig_stamped_and_verifies_ok(rendered):
    _, _, index = rendered
    assert sig.extract_sig(index.read_text(encoding="utf-8")) is not None
    assert sig.verify(index) == "ok"


def test_edit_breaks_sig(rendered):
    _, _, index = rendered
    _simulate_browser_edit(index)
    assert sig.verify(index) == "edited"


def test_unstamped_html(tmp_path):
    p = tmp_path / "x.html"
    p.write_text("<html><head></head><body>no stamp</body></html>", encoding="utf-8")
    assert sig.verify(p) == "unstamped"


def test_sig_stable_across_renders(tmp_path):
    """Same deck.json + same-depth output dir → same sig (deck_id / asset-path
    prefix normalized out). (Cross-DEPTH stability is not required — the guard
    self-verifies a file against its own embedded sig, never across renders.)"""
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    (a / "deck.json").write_text(SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    (b / "deck.json").write_text(SAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    assert _render(a / "deck.json", a).returncode == 0
    assert _render(b / "deck.json", b).returncode == 0
    s1 = sig.extract_sig((a / "index.html").read_text(encoding="utf-8"))
    s2 = sig.extract_sig((b / "index.html").read_text(encoding="utf-8"))
    assert s1 == s2


# -------------------------------------------------------------- unit: guard ---
def test_guard_passes_clean(rendered):
    _, deck, index = rendered
    assert sig.guard_should_refuse(deck, index) is None


def test_guard_refuses_edited(rendered):
    _, deck, index = rendered
    _simulate_browser_edit(index)
    assert sig.guard_should_refuse(deck, index) is not None


def test_guard_passes_when_deck_newer(rendered):
    """After a sync folds the edits into deck.json, deck.json is newer → a
    re-render is the safe direction and the guard must NOT refuse."""
    _, deck, index = rendered
    _simulate_browser_edit(index)
    future = time.time() + 100
    os.utime(deck, (future, future))   # deck.json now newer than index.html
    assert sig.guard_should_refuse(deck, index) is None


def test_guard_passes_when_no_index(tmp_path):
    deck = tmp_path / "deck.json"
    deck.write_text("{}", encoding="utf-8")
    assert sig.guard_should_refuse(deck, tmp_path / "index.html") is None


# --------------------------------------------------------- integration: cli ---
def test_deckcli_refuses_edited(rendered):
    _, deck, index = rendered
    _simulate_browser_edit(index)
    r = _run(DECKCLI, deck, "set-notes", "cover", "x")
    assert r.returncode == 6, f"expected refuse(6), got {r.returncode}\n{r.stderr}"
    assert "REFUSING" in r.stderr


def test_deckcli_force_overrides(rendered):
    _, deck, index = rendered
    _simulate_browser_edit(index)
    # deck-cli's --force is a global flag (before the deck positional).
    r = _run(DECKCLI, "--force", deck, "set-notes", "cover", "x")
    assert r.returncode == 0, f"--force should proceed, got {r.returncode}\n{r.stderr}"


def test_deckcli_clean_proceeds(rendered):
    """No false positive: a write command on a clean, freshly-rendered deck runs."""
    _, deck, index = rendered
    r = _run(DECKCLI, deck, "set-notes", "cover", "hello")
    assert r.returncode == 0, f"clean write should proceed, got {r.returncode}\n{r.stderr}"


# ------------------------------------------------------ integration: render ---
def test_render_refuses_edited(rendered):
    outdir, deck, index = rendered
    _simulate_browser_edit(index)
    r = _render(deck, outdir)
    assert r.returncode == 8, f"expected render refuse(8), got {r.returncode}\n{r.stderr}"
    assert "REFUSING" in r.stderr
    assert "COLLEAGUE-EDIT-XYZ" in index.read_text(encoding="utf-8"), \
        "refused render must NOT have overwritten the edited index.html"


def test_render_force_overrides(rendered):
    outdir, deck, index = rendered
    _simulate_browser_edit(index)
    r = _render(deck, outdir, "--force")
    assert r.returncode == 0, f"--force render should proceed, got {r.returncode}\n{r.stderr}"
    assert "COLLEAGUE-EDIT-XYZ" not in index.read_text(encoding="utf-8"), \
        "--force render should have regenerated index.html (discarding the edit)"


def test_canonical_loop_not_tripped(rendered):
    """set-notes → render → set-notes → render, all clean, must never refuse."""
    outdir, deck, _ = rendered
    assert _run(DECKCLI, deck, "set-notes", "cover", "n1").returncode == 0
    assert _render(deck, outdir).returncode == 0
    assert _run(DECKCLI, deck, "set-notes", "agenda", "n2").returncode == 0
    assert _render(deck, outdir).returncode == 0


_RAW_DECK = (
    '{"version":"1.0","deck":{"title":"raw recovery"},"slides":[{"key":"s1",'
    '"layout":"raw","data":{"html":"<h1 data-text-id=\\"s1.t\\">原始标题</h1>'
    '<p data-text-id=\\"s1.b\\">body text</p>"}}]}'
)


def test_sync_then_render_recovers(tmp_path):
    """The intended recovery flow on a RAW deck (clean round-trip, no --force):
    edit index.html → sync folds it into deck.json → render proceeds (deck.json is
    now newer) and the edit survives the regenerated index.html. This is the path
    the guard's refusal message points the user to."""
    deck = tmp_path / "deck.json"
    deck.write_text(_RAW_DECK, encoding="utf-8")
    assert _render(deck, tmp_path).returncode == 0
    index = tmp_path / "index.html"

    _simulate_browser_edit(index)                 # edits s1.t inside the raw slide
    assert sig.verify(index) == "edited"

    sync = DECKJSON / "sync-index-to-deck.py"
    s = _run(sync, index, deck, "--index-is-newer")
    assert s.returncode == 0, f"sync failed:\n{s.stdout}\n{s.stderr}"
    assert "COLLEAGUE-EDIT-XYZ" in deck.read_text(encoding="utf-8"), \
        "sync should have folded the raw-slide edit into deck.json"
    # In reality the sync runs well after the colleague's edit, so deck.json is
    # clearly the newer file. The test compresses time to <2s, so make the
    # deck.json-is-newer relationship explicit (the guard's release condition).
    _future = time.time() + 100
    os.utime(deck, (_future, _future))

    r = _render(deck, tmp_path)
    assert r.returncode == 0, f"render after sync should proceed (deck.json newer):\n{r.stderr}"
    assert "COLLEAGUE-EDIT-XYZ" in index.read_text(encoding="utf-8")
    assert sig.verify(index) == "ok"   # regenerated index.html is clean again


# ----------------------------------------------- Option A: auto-sync-if-lossless ---
@pytest.fixture
def rendered_raw(tmp_path):
    """A rendered RAW deck — its slide edits reverse-sync LOSSLESSLY, so Option A
    auto-syncs them instead of refusing."""
    deck = tmp_path / "deck.json"
    deck.write_text(_RAW_DECK, encoding="utf-8")
    assert _render(deck, tmp_path).returncode == 0
    return tmp_path, deck, tmp_path / "index.html"


def test_resolve_autosync_on_lossless_raw(rendered_raw):
    _, deck, index = rendered_raw
    _simulate_browser_edit(index)
    action, _ = sig.resolve_clobber(deck, index)
    assert action == "autosync", "a lossless raw-slide edit should be auto-syncable"


def test_resolve_refuse_on_schema(rendered):
    """A schema-slide edit isn't foldable by sync → resolve must refuse (not autosync)."""
    _, deck, index = rendered
    _simulate_browser_edit(index)   # sample deck = schema layouts
    action, reason = sig.resolve_clobber(deck, index)
    assert action == "refuse" and reason


def test_render_autosync_lossless_raw(rendered_raw):
    """Option A headline: edit a raw slide in the browser, then just RENDER — no
    manual sync. render auto-folds the edit into deck.json first, then regenerates
    index.html, so the edit survives and ends up in the source."""
    outdir, deck, index = rendered_raw
    _simulate_browser_edit(index)
    r = _render(deck, outdir)
    assert r.returncode == 0, f"render should auto-sync + proceed, got {r.returncode}\n{r.stderr}"
    assert "COLLEAGUE-EDIT-XYZ" in deck.read_text(encoding="utf-8"), \
        "render auto-sync should have folded the edit into deck.json"
    assert "COLLEAGUE-EDIT-XYZ" in index.read_text(encoding="utf-8")
    assert sig.verify(index) == "ok"


def test_deckcli_autosync_lossless_raw(rendered_raw):
    """deck-cli on a raw deck with un-synced lossless edits: auto-syncs the edit
    into deck.json, then applies the command on top — both survive."""
    _, deck, index = rendered_raw
    _simulate_browser_edit(index)
    r = _run(DECKCLI, deck, "set-notes", "s1", "a-note")
    assert r.returncode == 0, f"deck-cli should auto-sync + proceed, got {r.returncode}\n{r.stderr}"
    body = deck.read_text(encoding="utf-8")
    assert "COLLEAGUE-EDIT-XYZ" in body, "auto-sync should have folded the edit in"
    assert "a-note" in body, "the set-notes command should also have applied"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
