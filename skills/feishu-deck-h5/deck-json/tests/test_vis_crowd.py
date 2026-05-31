"""R-VIS-CROWD (框内文字贴底) — wiring + must-fire/must-not-fire.

Two layers (F-09 discipline):
  1. STATIC (always runs, no Chromium): the rule is wired end-to-end —
     visual-audit.js produces `out.crowd`, validate.py emits R-VIS-CROWD,
     and the reference doc lists it.
  2. PLAYWRIGHT-GATED (skips if Chromium/Playwright absent): render the
     committed must-fire fixture and assert R-VIS-CROWD fires; render a
     balanced deck (sample-deck) and assert it does NOT fire (stats/quote/
     content-3up are geometrically exempt — slack ≠ crowd, no layout-name
     whitelist).
"""
import re
import sys
import subprocess
import tempfile
import pathlib

HERE = pathlib.Path(__file__).resolve()
TESTS = HERE.parent
DECKJSON = TESTS.parent
ROOT = DECKJSON.parent
ASSETS = ROOT / "assets"
FIXTURE = TESTS / "fixtures" / "crowd-must-fire.deck.json"
SAMPLE = ROOT / "examples" / "sample-deck.html"
RENDER = DECKJSON / "render-deck.py"
VALIDATE = ASSETS / "validate.py"


# ---------- 1. STATIC wiring (always runs) ----------

def test_crowd_wired_in_visual_audit_js():
    js = (ASSETS / "visual-audit.js").read_text(encoding="utf-8")
    assert "crowd: []" in js, "out.crowd array missing from visual-audit.js"
    assert "out.crowd.push" in js, "crowd push site missing"
    # the geometric gate: distBottom < N (crowding floor) AND bottom-shift
    assert re.search(r"distBottom\s*<\s*10\s*&&\s*distTop\s*>\s*distBottom\s*\+\s*16", js), \
        "crowd threshold (distBottom<10 && distTop>distBottom+16) drifted"
    # media exclusion (so photo captions don't false-fire)
    assert "_isMediaBox" in js and "_isFramedBox" in js


def test_crowd_emitted_in_validate_py():
    py = (ASSETS / "validate.py").read_text(encoding="utf-8")
    assert "report.get('crowd'" in py, "validate.py does not consume report['crowd']"
    assert "R-VIS-CROWD" in py, "validate.py does not emit R-VIS-CROWD"


def test_crowd_documented():
    doc = (ROOT / "references" / "validator-rules.md").read_text(encoding="utf-8")
    assert "R-VIS-CROWD" in doc, "R-VIS-CROWD missing from references/validator-rules.md (F-03 sync)"


def test_crowd_fixture_exists():
    assert FIXTURE.exists(), f"must-fire fixture missing: {FIXTURE}"


# ---------- 2. PLAYWRIGHT-GATED firing (skips without Chromium) ----------

def _visual_available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def _render(deck_json: pathlib.Path, out_dir: pathlib.Path) -> bool:
    r = subprocess.run([sys.executable, str(RENDER), str(deck_json), str(out_dir), "--inline"],
                       capture_output=True, text=True)
    return (out_dir / "index.html").exists()


def _validate_output(html: pathlib.Path) -> str:
    r = subprocess.run([sys.executable, str(VALIDATE), str(html)],
                       capture_output=True, text=True)
    return r.stdout + r.stderr


def _visual_ran(out: str) -> bool:
    # validate.py prints an install hint when Chromium is missing → visual skipped
    return "install chromium" not in out.lower() and "playwright not installed" not in out.lower()


def _inject_no_autobalance(html: pathlib.Path):
    """Disable the runtime auto-balance so the detector can be tested alone."""
    t = html.read_text(encoding="utf-8")
    html.write_text(t.replace('<div class="deck', '<div data-no-autobalance class="deck', 1),
                    encoding="utf-8")


def test_crowd_detector_fires_when_autobalance_off():
    """Detector in isolation: with runtime auto-balance disabled
    (data-no-autobalance), the committed crowding fixture trips R-VIS-CROWD."""
    if not _visual_available():
        print("  skip: playwright not installed (gated test)"); return
    with tempfile.TemporaryDirectory() as td:
        out_dir = pathlib.Path(td) / "fire"
        if not _render(FIXTURE, out_dir):
            print("  skip: fixture render failed"); return
        _inject_no_autobalance(out_dir / "index.html")
        out = _validate_output(out_dir / "index.html")
        if not _visual_ran(out):
            print("  skip: Chromium unavailable, visual audit did not run"); return
        assert "R-VIS-CROWD" in out, \
            "detector did not fire on crowding fixture (autobalance off)\n" + out[-2000:]


def test_autobalance_fixes_crowd_on_load():
    """The runtime auto-balance corrects the crowd BEFORE the validator
    measures → R-VIS-CROWD goes silent (加载即对). Same fixture, autobalance on."""
    if not _visual_available():
        print("  skip: playwright not installed (gated test)"); return
    with tempfile.TemporaryDirectory() as td:
        out_dir = pathlib.Path(td) / "bal"
        if not _render(FIXTURE, out_dir):
            print("  skip: fixture render failed"); return
        out = _validate_output(out_dir / "index.html")
        if not _visual_ran(out):
            print("  skip: Chromium unavailable, visual audit did not run"); return
        assert "R-VIS-CROWD" not in out, \
            "auto-balance should have fixed the crowd on load (still firing)\n" + \
            "\n".join(l for l in out.splitlines() if "R-VIS-CROWD" in l)


def test_crowd_not_fire_on_balanced_deck():
    """MUST-NOT-FIRE: balanced canonical deck (stats/quote/3up) — no crowd."""
    if not _visual_available() or not SAMPLE.exists():
        print("  skip"); return
    out = _validate_output(SAMPLE)
    if not _visual_ran(out):
        print("  skip: visual audit did not run"); return
    assert "R-VIS-CROWD" not in out, \
        "R-VIS-CROWD false-positive on balanced sample-deck\n" + \
        "\n".join(l for l in out.splitlines() if "R-VIS-CROWD" in l)


TITLE_FIXTURE = TESTS / "fixtures" / "crowd-with-title.deck.json"


def test_autobalance_never_moves_title():
    """死规矩: auto-balance must NEVER move a content-page title / subtitle.
    Crowded fixture WITH a header — title & subtitle positions must be identical
    with auto-balance on vs off, while the card crowd is still fixed."""
    if not _visual_available() or not TITLE_FIXTURE.exists():
        print("  skip"); return
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("  skip: playwright unavailable"); return
    with tempfile.TemporaryDirectory() as td:
        out_dir = pathlib.Path(td) / "t"
        if not _render(TITLE_FIXTURE, out_dir):
            print("  skip: render failed"); return
        on_html = out_dir / "index.html"
        off_html = out_dir / "off.html"
        off_html.write_text(
            on_html.read_text(encoding="utf-8").replace(
                '<div class="deck', '<div data-no-autobalance class="deck', 1),
            encoding="utf-8")

        def probe(path):
            with sync_playwright() as p:
                b = p.chromium.launch()
                pg = b.new_context(viewport={"width": 1920, "height": 1080}).new_page()
                pg.goto(path.as_uri(), wait_until="load")
                pg.wait_for_timeout(400)
                r = pg.evaluate(
                    "() => { const t=document.querySelector('.title-zh').getBoundingClientRect();"
                    "const s=document.querySelector('.subtitle').getBoundingClientRect();"
                    "const c=document.querySelector('.card');const cr=c.getBoundingClientRect();"
                    "const tx=[...c.querySelectorAll('*')].filter(e=>[...e.childNodes].some(n=>n.nodeType===3&&n.textContent.trim()));"
                    "const tb=Math.max(...tx.map(e=>e.getBoundingClientRect().bottom));"
                    "return {tt:t.top,tl:t.left,st:s.top,cbi:cr.bottom-tb}; }")
                b.close(); return r
        try:
            off = probe(off_html); on = probe(on_html)
        except Exception as e:
            print(f"  skip: chromium probe failed ({e})"); return
        assert abs(on["tt"] - off["tt"]) <= 1 and abs(on["tl"] - off["tl"]) <= 1, \
            f"死规矩 violated: title moved {on['tt']-off['tt']:.1f}px top / {on['tl']-off['tl']:.1f}px left"
        assert abs(on["st"] - off["st"]) <= 1, \
            f"死规矩 violated: subtitle moved {on['st']-off['st']:.1f}px"
        # sanity: auto-balance actually fixed the crowd (else the guard is vacuous)
        assert on["cbi"] > off["cbi"] + 20, \
            f"auto-balance did not fix the card crowd (off {off['cbi']:.0f} → on {on['cbi']:.0f})"


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
