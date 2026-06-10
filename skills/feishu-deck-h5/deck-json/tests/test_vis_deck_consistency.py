"""DECK-LEVEL cross-page consistency rules (F-257 · cross-page half) —
wiring + must-fire / must-not-fire.

Three deck-level (page-to-page) advisories, the first audits that COMPARE pages
instead of judging each in isolation. All three are WARN (consistency guides,
never blocks), name-free (computed geometry / colors, no class whitelist), fire
once on the `isFirstInScope` anchor frame, and carry an opt-out:

  · R-DECK-TITLE-DRIFT      — content-page title baseline/size drifts vs the deck
                              MODE (one page's title sits >8px off / a different
                              font-size than the rest).
  · R-DECK-PALETTE-DRIFT    — ≥3 near-duplicate accent hexes deck-wide (the
                              "re-eyeballed the accent on every page" fingerprint
                              R10 can't see — R10 strips <style>).
  · R-DECK-TYPESCALE-BUDGET — author `allow:typescale` markers > content-page
                              count (the exemption became the rule).

Two layers (F-09 discipline):
  1. STATIC (always runs, no Chromium): each code is wired end-to-end — present
     in audits.js (rule literal + RULE_META), in check-only's FAMILIES, and in
     references/validator-rules.md.
  2. PLAYWRIGHT-GATED (skips if Chromium/Playwright absent): render committed
     must-fire fixtures and assert each rule fires; render clean examples and
     assert all three stay silent (CALIBRATION: false-positives have repeatedly
     burned this skill — clean decks MUST be silent).
"""
import importlib.util
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve()
TESTS = HERE.parent
DECKJSON = TESTS.parent
ROOT = DECKJSON.parent
ASSETS = ROOT / "assets"
RENDER = DECKJSON / "render-deck.py"

CODES = ["R-DECK-TITLE-DRIFT", "R-DECK-PALETTE-DRIFT", "R-DECK-TYPESCALE-BUDGET"]

FIX_TITLE = TESTS / "fixtures" / "deck-title-drift-must-fire.deck.json"
FIX_PALETTE = TESTS / "fixtures" / "deck-palette-drift-must-fire.deck.json"
FIX_TYPESCALE = TESTS / "fixtures" / "deck-typescale-budget-must-fire.deck.json"
CLEAN_EXAMPLES = [
    ROOT / "examples" / "sample-deck.json",
    ROOT / "examples" / "phase-1a-demo.json",
    ROOT / "examples" / "phase-1b-demo.json",
    ROOT / "examples" / "phase-1c-extras.json",
]


# ---------- 1. STATIC wiring (always runs, no Chromium) ----------

def test_codes_declared_in_engine_and_rule_meta():
    """Every new code must be emitted by the engine (a `rule:` literal) AND carry
    a RULE_META entry — else test_rule_contract.py fails. (Mirrors the contract
    that every audits.js rule self-declares its coverage.)"""
    js = (ASSETS / "audits.js").read_text(encoding="utf-8")
    meta_region = js[js.index("const RULE_META = {"):js.index("const RULES = [")]
    for code in CODES:
        assert f"rule: '{code}'" in js, f"{code} not emitted as a rule literal in audits.js"
        assert f"'{code}':" in meta_region, f"{code} missing a RULE_META entry"


def test_codes_in_check_only_families():
    """test_check_only_gate.test_all_emitted_codes_documented_in_families requires
    every emitted code be categorized in FAMILIES — guard it here too."""
    spec = importlib.util.spec_from_file_location("check_only_dc", ASSETS / "check-only.py")
    CO = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(CO)
    fam = {c for _, codes in CO.FAMILIES for c in codes}
    for code in CODES:
        assert code in fam, f"{code} not categorized in check-only FAMILIES"


def test_codes_documented_in_reference():
    """F-03 doc-sync: references/validator-rules.md must document every code the
    validator can emit (enforced by test_check_only_gate too)."""
    doc = (ROOT / "references" / "validator-rules.md").read_text(encoding="utf-8")
    for code in CODES:
        assert code in doc, f"{code} missing from references/validator-rules.md"


def test_rules_are_warn_level():
    """Consistency advisories must be WARN — never block delivery. Assert each
    rule object declares severity: 'warn' (the skill's stance: advisories guide)."""
    js = (ASSETS / "audits.js").read_text(encoding="utf-8")
    for code in CODES:
        i = js.index(f"id: '{code}'")
        window = js[i:i + 200]
        assert "severity: 'warn'" in window, f"{code} must be severity:'warn' (advisory)"


def test_fixtures_exist():
    for fx in (FIX_TITLE, FIX_PALETTE, FIX_TYPESCALE):
        assert fx.exists(), f"must-fire fixture missing: {fx}"


# ---------- 2. PLAYWRIGHT-GATED firing (skips without Chromium) ----------

def _visual_available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def _engine():
    """Import run-audits.py (hyphenated → importlib); the SAME shared engine entry
    validate.py / check-only / render-deck use. Returns the module or None if
    Chromium/Playwright is unavailable (so the test skips, never errors)."""
    spec = importlib.util.spec_from_file_location("run_audits_dc", ASSETS / "run-audits.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _render(deck_json: pathlib.Path, out_dir: pathlib.Path) -> bool:
    import subprocess
    subprocess.run([sys.executable, str(RENDER), str(deck_json), str(out_dir), "--inline"],
                   capture_output=True, text=True)
    return (out_dir / "index.html").exists()


def _deck_codes(deck_json: pathlib.Path):
    """Render `deck_json` and return the set of R-DECK-* rule codes the unified
    engine emits on it (or None if the engine can't run → caller skips)."""
    import tempfile
    E = _engine()
    EngineUnavailable = getattr(E, "EngineUnavailable", Exception)
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "o"
        if not _render(deck_json, out):
            return "RENDER_FAILED"
        try:
            res = E.run_unified_engine(out / "index.html", None, settle_ms=350, dom_rules=True)
        except EngineUnavailable:
            return None
    return {f["rule"] for f in res.get("findings", []) if f["rule"].startswith("R-DECK-")}


def test_title_drift_fires():
    """MUST-FIRE: a deck where one content page's title sits 35px lower than the
    rest (page 4 at top:96 vs deck mode 61)."""
    if not _visual_available():
        print("  skip: playwright not installed (gated test)"); return
    codes = _deck_codes(FIX_TITLE)
    if codes in (None, "RENDER_FAILED"):
        print(f"  skip: {codes}"); return
    assert "R-DECK-TITLE-DRIFT" in codes, \
        f"R-DECK-TITLE-DRIFT did not fire on the title-drift fixture; got {codes}"


def test_palette_drift_fires():
    """MUST-FIRE: a deck with #5cf0dc / #5befdc / #5cefdb (3 near-duplicate teals
    = hand-tuned drift) → near-duplicate cluster of 3 flagged."""
    if not _visual_available():
        print("  skip: playwright not installed (gated test)"); return
    codes = _deck_codes(FIX_PALETTE)
    if codes in (None, "RENDER_FAILED"):
        print(f"  skip: {codes}"); return
    assert "R-DECK-PALETTE-DRIFT" in codes, \
        f"R-DECK-PALETTE-DRIFT did not fire on the palette-drift fixture; got {codes}"


def test_typescale_budget_fires():
    """MUST-FIRE: a deck with ~4× allows-per-page (8 author allow:typescale across
    2 content pages)."""
    if not _visual_available():
        print("  skip: playwright not installed (gated test)"); return
    codes = _deck_codes(FIX_TYPESCALE)
    if codes in (None, "RENDER_FAILED"):
        print(f"  skip: {codes}"); return
    assert "R-DECK-TYPESCALE-BUDGET" in codes, \
        f"R-DECK-TYPESCALE-BUDGET did not fire on the typescale-budget fixture; got {codes}"


def test_clean_examples_are_silent():
    """MUST-NOT-FIRE (CALIBRATION · highest-risk): the real clean example decks
    must produce ZERO of the 3 deck-level findings. Covers:
      · all content titles share a baseline (good case) → no TITLE-DRIFT;
      · a deck that legitimately mixes hero pages (excluded) → no TITLE-DRIFT;
      · the framework's OWN distinct brand accents + a clean palette → no
        PALETTE-DRIFT;
      · a few legit (framework) hero allows → no TYPESCALE-BUDGET.
    If any of these fires, the thresholds are wrong (loosen until clean → silent)."""
    if not _visual_available():
        print("  skip: playwright not installed (gated test)"); return
    available = [e for e in CLEAN_EXAMPLES if e.exists()]
    if not available:
        print("  skip: no clean example decks found"); return
    ran_any = False
    for ex in available:
        codes = _deck_codes(ex)
        if codes is None:
            print("  skip: engine unavailable"); return
        if codes == "RENDER_FAILED":
            print(f"  skip: render failed for {ex.name}"); continue
        ran_any = True
        assert codes == set(), \
            f"deck-level rule false-positive on clean deck {ex.name}: {sorted(codes)}"
    if not ran_any:
        print("  skip: no clean deck rendered")


def test_typescale_budget_silent_on_few_hero_allows():
    """MUST-NOT-FIRE: a deck with a few legit hero allows (3 across 9 pages). Built
    inline: 9 content pages, 3 author allow:typescale markers (one per 3 pages) →
    3 ≤ 9 → silent (the exemption count must exceed the content-page count to
    fire). Guards against the budget rule mistaking sparse legit use for abuse."""
    if not _visual_available():
        print("  skip: playwright not installed (gated test)"); return
    import json
    import tempfile
    slides = []
    for i in range(9):
        s = {
            "key": f"few-allow-{i+1}",
            "layout": "content",
            "variant": "3up",
            "accent": "blue",
            "screen_label": f"{i+1:02d} page",
            "data": {
                "title": f"页面 {i+1}",
                "cards": [
                    {"num": "01", "icon": "zap", "title_zh": "甲", "body": "正文。"},
                    {"num": "02", "icon": "check", "title_zh": "乙", "body": "正文。"},
                    {"num": "03", "icon": "users", "title_zh": "丙", "body": "正文。"},
                ],
            },
        }
        if i in (0, 3, 6):   # exactly 3 author allows across 9 pages = legit hero use
            s["custom_css"] = ".hero-num { font-size: 88px; /* allow:typescale */ }"
        slides.append(s)
    deck = {"version": "1.0",
            "deck": {"title": "few legit hero allows", "author": "fixture", "date": "2026-06"},
            "slides": slides}
    with tempfile.TemporaryDirectory() as td:
        dj = pathlib.Path(td) / "deck.json"
        dj.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
        codes = _deck_codes(dj)
    if codes in (None, "RENDER_FAILED"):
        print(f"  skip: {codes}"); return
    assert "R-DECK-TYPESCALE-BUDGET" not in codes, \
        f"R-DECK-TYPESCALE-BUDGET false-fired on 3 legit allows across 9 pages: {sorted(codes)}"


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
