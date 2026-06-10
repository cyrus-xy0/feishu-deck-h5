"""F-266 — Gate 1 model-agnostic enforcement (provenance stamp + R-PROVENANCE).

Hard Gate 1 ("must go through render-deck.py") used to be enforced ONLY by the
author's personal Claude-Code PostToolUse hook; Codex / cloud agents have none,
so a hand-written / hand-patched index.html (Path B) caused silent
deck.json↔index.html drift that nothing in the repo caught. This moves the
enforcement into the toolchain:

  · render-deck.py STAMPS every output's <head> with
      <meta name="fs-deck-generator" content="render-deck">
      <meta name="fs-deck-hash" content="<H>">   where H = sha256(deck.json file)[:12]
  · run-audits.py's R-PROVENANCE VERIFIES that stamp (byte/file-system check),
    but ONLY when index.html is under a runs/ path AND a sibling deck.json
    exists. Three tiers: no stamp → warn (legacy decks innocent; promoted to
    error under --strict/ingest); stamp present but hash ≠ sibling deck.json
    sha256[:12] → error (real drift).

These tests pin all of that with NO browser (byte path only) + one real render.
"""
import hashlib
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DECK_JSON = Path(__file__).resolve().parents[1]
RENDER = DECK_JSON / "render-deck.py"
EXAMPLE = DECK_JSON / "examples" / "sample-deck.json"
ASSETS = DECK_JSON.parent / "assets"

# run-audits.py has a hyphen → load by path.
_spec = importlib.util.spec_from_file_location("run_audits", ASSETS / "run-audits.py")
RA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RA)

# render-deck.py likewise (for deck_json_hash / _stamp_provenance single-source).
_rspec = importlib.util.spec_from_file_location("render_deck", RENDER)
RD = importlib.util.module_from_spec(_rspec)
_rspec.loader.exec_module(RD)


def _expected_hash(deck_path: Path) -> str:
    return hashlib.sha256(deck_path.read_bytes()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# render-deck STAMP side
# ---------------------------------------------------------------------------

def test_render_stamps_generator_and_hash():
    """A fresh render injects both provenance meta, and the hash = sha256 of the
    deck.json FILE CONTENT (first 12 hex chars)."""
    with tempfile.TemporaryDirectory() as td:
        r = subprocess.run([sys.executable, str(RENDER), str(EXAMPLE), td + "/"],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"render failed:\n{r.stdout}\n{r.stderr}"
        html = (Path(td) / "index.html").read_text(encoding="utf-8")
    assert '<meta name="fs-deck-generator" content="render-deck">' in html
    m = re.search(r'<meta name="fs-deck-hash" content="([^"]+)">', html)
    assert m, "fs-deck-hash meta missing"
    assert m.group(1) == _expected_hash(EXAMPLE), \
        "stamped hash must equal sha256(deck.json file)[:12]"


def test_stamp_is_based_on_deck_json_not_index_html():
    """The hash must track deck.json content, so a POST-render rewrite of
    index.html (the inline/copy/explode-assets class of edit) does NOT change H.
    Simulate that: stamp once, then mutate the HTML body — recomputing against
    the SAME deck.json yields the SAME hash, so R-PROVENANCE stays clean."""
    h = RD.deck_json_hash(EXAMPLE)
    base = '<!doctype html><html><head><meta charset="utf-8"></head><body><div class="deck"></div></body></html>'
    stamped = RD._stamp_provenance(base, h)
    # post-render rewrite: add a localized asset path (what copy-assets does)
    rewritten = stamped.replace('class="deck"', 'class="deck" data-x="1"')
    m = re.search(r'<meta name="fs-deck-hash" content="([^"]+)">', rewritten)
    assert m and m.group(1) == h, "rewriting index.html must not change the deck.json-based hash"


def test_stamp_is_idempotent():
    """Re-stamping already-stamped HTML replaces, never duplicates, the meta."""
    base = '<!doctype html><html><head><meta charset="utf-8"></head><body></body></html>'
    once = RD._stamp_provenance(base, "aaaaaaaaaaaa")
    twice = RD._stamp_provenance(once, "bbbbbbbbbbbb")
    assert twice.count('name="fs-deck-generator"') == 1
    assert twice.count('name="fs-deck-hash"') == 1
    assert 'content="bbbbbbbbbbbb"' in twice and 'content="aaaaaaaaaaaa"' not in twice


# ---------------------------------------------------------------------------
# R-PROVENANCE VERIFY side — helpers to stage a runs/<ts>/output/ layout
# ---------------------------------------------------------------------------

def _stage_runs_render(tmp: Path) -> Path:
    """Render the example into a runs/<ts>/output/ style dir WITH a sibling
    deck.json (the real delivery layout R-PROVENANCE polices). Returns the
    output dir holding index.html + deck.json."""
    out = tmp / "runs" / "20260610-000000" / "output"
    out.mkdir(parents=True)
    shutil.copy2(EXAMPLE, out / "deck.json")
    r = subprocess.run(
        [sys.executable, str(RENDER), str(out / "deck.json"), str(out) + "/",
         "--skip-validate-html"],   # we exercise R-PROVENANCE directly, no gate needed
        capture_output=True, text=True)
    assert r.returncode == 0, f"staged render failed:\n{r.stdout}\n{r.stderr}"
    assert (out / "index.html").is_file()
    return out


def _provenance_findings(out: Path):
    html = (out / "index.html").read_text(encoding="utf-8")
    return RA.audit_provenance_bytes(html, out)


def test_clean_render_under_runs_passes():
    """A real render under runs/ with a matching sibling deck.json → no finding."""
    with tempfile.TemporaryDirectory() as td:
        out = _stage_runs_render(Path(td))
        assert _provenance_findings(out) == [], \
            "a clean render-deck output must not trip R-PROVENANCE"


def test_hash_mismatch_after_editing_deck_json_is_error():
    """Edit deck.json WITHOUT re-rendering → stamped hash goes stale → error."""
    with tempfile.TemporaryDirectory() as td:
        out = _stage_runs_render(Path(td))
        dj = out / "deck.json"
        dj.write_text(dj.read_text(encoding="utf-8") + "\n", encoding="utf-8")  # 1-byte change
        fs = _provenance_findings(out)
        assert len(fs) == 1 and fs[0]["rule"] == "R-PROVENANCE"
        assert fs[0]["severity"] == "error", "hash mismatch must be an ERROR (real drift)"


def test_missing_stamp_is_warn_not_error():
    """Legacy / hand-written index.html with NO stamp → warn (innocent; promoted
    to error only under --strict/ingest by the consumer layer), NEVER a hard
    error on a daily render."""
    with tempfile.TemporaryDirectory() as td:
        out = _stage_runs_render(Path(td))
        html = (out / "index.html").read_text(encoding="utf-8")
        # strip BOTH provenance meta to simulate a pre-F-266 / hand-made deck
        html = re.sub(r'\s*<meta name="fs-deck-(?:generator|hash)" content="[^"]*">', "", html)
        (out / "index.html").write_text(html, encoding="utf-8")
        fs = _provenance_findings(out)
        assert len(fs) == 1 and fs[0]["rule"] == "R-PROVENANCE"
        assert fs[0]["severity"] == "warn", \
            "no-stamp must be WARN (legacy decks are innocent), not error"


# ---------------------------------------------------------------------------
# Exemptions (calibration): /tmp (not under runs/) and no-sibling-deck.json
# ---------------------------------------------------------------------------

def test_tmp_render_without_runs_is_exempt():
    """An index.html NOT under a runs/ path is exempt — even if unstamped (this
    is the /tmp smoke-test + examples-to-/tmp case)."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "scratch"
        out.mkdir()
        shutil.copy2(EXAMPLE, out / "deck.json")
        (out / "index.html").write_text(
            '<!doctype html><html><head><meta charset="utf-8"></head>'
            '<body><div class="deck"></div></body></html>', encoding="utf-8")
        assert _provenance_findings(out) == [], \
            "non-runs/ path must be exempt from R-PROVENANCE"


def test_runs_without_sibling_deck_json_is_exempt():
    """Under runs/ but NO sibling deck.json (standalone HTML / imported fragment
    that isn't deck.json-backed) → exempt."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "runs" / "20260610-000000" / "output"
        out.mkdir(parents=True)
        (out / "index.html").write_text(
            '<!doctype html><html><head><meta charset="utf-8"></head>'
            '<body><div class="deck"></div></body></html>', encoding="utf-8")
        assert not (out / "deck.json").exists()
        assert _provenance_findings(out) == [], \
            "no sibling deck.json must exempt R-PROVENANCE even under runs/"


# ---------------------------------------------------------------------------
# Wiring: R-PROVENANCE runs on BOTH paths + is declared in BYTE_RULE_META
# ---------------------------------------------------------------------------

def test_provenance_runs_in_both_paths_via_source_byte_findings():
    """R-PROVENANCE must be wired into runner_source_byte_findings (the set that
    runs on BOTH --visual and --no-visual), not the no-browser-only set."""
    with tempfile.TemporaryDirectory() as td:
        out = _stage_runs_render(Path(td))
        dj = out / "deck.json"
        dj.write_text(dj.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        html = (out / "index.html").read_text(encoding="utf-8")
        codes = {f["rule"] for f in RA.runner_source_byte_findings(html, out)}
        assert "R-PROVENANCE" in codes


def test_provenance_declared_in_byte_rule_meta():
    """The contract: every byte rule the runner emits is declared with
    signal 'bytes' in BYTE_RULE_META (mirrors test_byte_rule_contract)."""
    assert RA.BYTE_RULE_META.get("R-PROVENANCE", {}).get("signal") == "bytes"


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn(); print(f"  ok  {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL  {fn.__name__}"); traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
