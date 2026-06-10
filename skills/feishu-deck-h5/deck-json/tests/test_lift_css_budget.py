"""R-LIFT-CSS-BUDGET (F-281a) — lifted-slide CSS-bloat guard.

When a raw page is LIFTED from another deck, its `custom_css` (rendered as a
`.slide`-scoped `<style>`) plus any markup-embedded `<style>` tends to drag in
the SOURCE deck's whole stylesheet — mostly dead rules / @keyframes the page
never matches. This rule sums the UTF-8 bytes of every `<style>` in a lifted
slide's subtree and warns at >24KB, errors at >64KB. It is name-free (keyed on
the `data-lifted` provenance attribute) and fires ONLY on lifted slides, so
clean/authored decks (no lifted slides, custom_css typically 0) self-exempt.

Two layers (F-09 discipline):
  1. STATIC (always runs, no Chromium): the code is wired end-to-end — emitted
     as a `rule:` literal in audits.js, declared in RULE_META, categorized in
     check-only's FAMILIES, and documented in references/validator-rules.md.
  2. PLAYWRIGHT-GATED (skips if Chromium/Playwright absent): render synthetic
     decks and assert the rule fires WARN >24KB / ERROR >64KB on a lifted slide,
     stays SILENT on a non-lifted slide carrying the same CSS, and stays SILENT
     on the real clean example decks (CALIBRATION — false-positives have
     repeatedly burned this skill; clean decks MUST be silent).
"""
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve()
TESTS = HERE.parent
DECKJSON = TESTS.parent
ROOT = DECKJSON.parent
ASSETS = ROOT / "assets"
RENDER = DECKJSON / "render-deck.py"

CODE = "R-LIFT-CSS-BUDGET"

# Real clean decks must NEVER trip this rule (calibration baseline). These have
# zero lifted slides and zero custom_css, so the rule self-exempts entirely.
CLEAN_EXAMPLES = [
    DECKJSON / "examples" / "sample-deck.json",
    DECKJSON / "examples" / "phase-1a-demo.json",
    DECKJSON / "examples" / "phase-1b-demo.json",
    DECKJSON / "examples" / "phase-1c-extras.json",
]


# ---------- 1. STATIC wiring (always runs, no Chromium) ----------

def test_code_declared_in_engine_and_rule_meta():
    """The code must be emitted by the engine (a `rule:` literal) AND carry a
    RULE_META entry — else test_rule_contract.py fails."""
    js = (ASSETS / "audits.js").read_text(encoding="utf-8")
    meta_region = js[js.index("const RULE_META = {"):js.index("const RULES = [")]
    assert f"rule: '{CODE}'" in js, f"{CODE} not emitted as a rule literal in audits.js"
    assert f"id: '{CODE}'" in js, f"{CODE} has no rule object (id) in audits.js"
    assert f"'{CODE}':" in meta_region, f"{CODE} missing a RULE_META entry"


def test_code_in_check_only_families():
    """test_check_only_gate.test_all_emitted_codes_documented_in_families requires
    every emitted code be categorized in FAMILIES — guard it here too."""
    spec = importlib.util.spec_from_file_location("check_only_lcb", ASSETS / "check-only.py")
    CO = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(CO)
    fam = {c for _, codes in CO.FAMILIES for c in codes}
    assert CODE in fam, f"{CODE} not categorized in check-only FAMILIES"


def test_code_documented_in_reference():
    """F-03 doc-sync: references/validator-rules.md must document every code the
    validator can emit (also enforced by test_check_only_gate)."""
    doc = (ROOT / "references" / "validator-rules.md").read_text(encoding="utf-8")
    assert CODE in doc, f"{CODE} missing from references/validator-rules.md"


def test_thresholds_present_in_source():
    """Lock the calibrated budget so a refactor can't silently move it: 24KB warn
    / 64KB error, expressed as 24*1024 / 64*1024 in audits.js."""
    js = (ASSETS / "audits.js").read_text(encoding="utf-8")
    i = js.index(f"id: '{CODE}'")
    window = js[i:i + 1400]
    assert "24 * 1024" in window, "24KB warn budget not found near the rule"
    assert "64 * 1024" in window, "64KB error budget not found near the rule"


def test_stub_R_VIS_ALIGN_removed():
    """F-282a: the unimplemented R-VIS-ALIGN stub was removed — it must no longer
    be a registered rule (no `id:`) nor a RULE_META object entry; a tombstone
    comment may remain. (A registered-but-silent rule is a 'rule list ≠ real
    coverage' gap the audit forbids.)"""
    js = (ASSETS / "audits.js").read_text(encoding="utf-8")
    assert "id: 'R-VIS-ALIGN'" not in js, "R-VIS-ALIGN rule object still present"
    # RULE_META entry would be a line like `'R-VIS-ALIGN': { coverage: ... }`
    assert not re.search(r"^\s*'R-VIS-ALIGN':\s*\{", js, re.M), \
        "R-VIS-ALIGN still has a RULE_META object entry (would be a contract orphan)"


# ---------- 2. PLAYWRIGHT-GATED firing (skips without Chromium) ----------

def _visual_available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def _engine():
    spec = importlib.util.spec_from_file_location("run_audits_lcb", ASSETS / "run-audits.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _render(deck_json: pathlib.Path, out_dir: pathlib.Path) -> bool:
    subprocess.run([sys.executable, str(RENDER), str(deck_json), str(out_dir), "--inline"],
                   capture_output=True, text=True)
    return (out_dir / "index.html").exists()


def _findings(deck: dict):
    """Render an in-memory deck dict and return the list of R-LIFT-CSS-BUDGET
    findings the unified engine emits (or a sentinel string / None to skip)."""
    E = _engine()
    EngineUnavailable = getattr(E, "EngineUnavailable", Exception)
    with tempfile.TemporaryDirectory() as td:
        src = pathlib.Path(td) / "d.json"
        src.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
        out = pathlib.Path(td) / "o"
        if not _render(src, out):
            return "RENDER_FAILED"
        try:
            res = E.run_unified_engine(out / "index.html", None, settle_ms=300, dom_rules=True)
        except EngineUnavailable:
            return None
    return [f for f in res.get("findings", []) if f["rule"] == CODE]


def _example_findings(deck_json: pathlib.Path):
    E = _engine()
    EngineUnavailable = getattr(E, "EngineUnavailable", Exception)
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "o"
        if not _render(deck_json, out):
            return "RENDER_FAILED"
        try:
            res = E.run_unified_engine(out / "index.html", None, settle_ms=300, dom_rules=True)
        except EngineUnavailable:
            return None
    return [f for f in res.get("findings", []) if f["rule"] == CODE]


def _big_css(n: int) -> str:
    # Each rule ~115 bytes → n=350 ≈ 40KB, n=800 ≈ 90KB. Realistic of a source
    # deck's dead rules dragged in by a lift.
    rules = "\n".join(
        f".dead-{i}{{color:#fff;margin:{i}px;padding:2px 4px;"
        f"border:1px solid #112233;background:linear-gradient(90deg,#000,#fff)}}"
        for i in range(n))
    return "/* lifted source stylesheet */\n" + rules


def _raw_slide(key: str, css: str, *, lifted: bool) -> dict:
    """A raw page whose markup embeds a big <style> (the way a lifted page drags
    in the source deck's CSS). `lifted=True` adds the `data-lifted` provenance."""
    s = {
        "key": key, "layout": "raw", "screen_label": "01 x",
        "data": {"html":
            '<div class="header"><h2 class="title-zh">Lifted</h2></div>'
            f'<style>{css}</style>'
            '<div class="stage"><p class="body" style="font-size:24px">hi</p></div>'},
    }
    if lifted:
        s["lifted"] = "source-deck#orig-key"
    return s


def _deck(slide: dict) -> dict:
    return {"version": "1.0",
            "deck": {"title": "lift-css-budget", "author": "fixture", "date": "2026-06"},
            "slides": [slide]}


def test_warn_fires_over_24kb_on_lifted_slide():
    """MUST-FIRE (warn): a lifted slide carrying ~40KB of CSS (>24KB, <64KB)."""
    if not _visual_available():
        print("  skip: playwright not installed (gated test)"); return
    fs = _findings(_deck(_raw_slide("a", _big_css(350), lifted=True)))
    if fs in (None, "RENDER_FAILED"):
        print(f"  skip: {fs}"); return
    assert fs, "R-LIFT-CSS-BUDGET did not fire on a ~40KB lifted slide"
    assert all(f["severity"] == "warn" for f in fs), \
        f"expected WARN at ~40KB (<64KB), got {[f['severity'] for f in fs]}"


def test_error_fires_over_64kb_on_lifted_slide():
    """MUST-FIRE (error): a lifted slide carrying ~90KB of CSS (>64KB)."""
    if not _visual_available():
        print("  skip: playwright not installed (gated test)"); return
    fs = _findings(_deck(_raw_slide("a", _big_css(800), lifted=True)))
    if fs in (None, "RENDER_FAILED"):
        print(f"  skip: {fs}"); return
    assert fs, "R-LIFT-CSS-BUDGET did not fire on a ~90KB lifted slide"
    assert any(f["severity"] == "error" for f in fs), \
        f"expected ERROR at ~90KB (>64KB), got {[f['severity'] for f in fs]}"


def test_silent_on_non_lifted_slide_with_same_css():
    """MUST-NOT-FIRE: the SAME ~90KB of CSS on a NON-lifted raw slide stays
    silent — the rule self-exempts on authored (non-lifted) pages."""
    if not _visual_available():
        print("  skip: playwright not installed (gated test)"); return
    fs = _findings(_deck(_raw_slide("a", _big_css(800), lifted=False)))
    if fs in (None, "RENDER_FAILED"):
        print(f"  skip: {fs}"); return
    assert fs == [], f"R-LIFT-CSS-BUDGET fired on a NON-lifted slide; got {fs}"


def test_silent_on_small_lifted_slide():
    """MUST-NOT-FIRE: a lifted slide with only a tiny bit of CSS (well under
    24KB) must stay silent — a normal, well-trimmed lifted page."""
    if not _visual_available():
        print("  skip: playwright not installed (gated test)"); return
    fs = _findings(_deck(_raw_slide("a", ".keep{color:#fff;font-size:24px}", lifted=True)))
    if fs in (None, "RENDER_FAILED"):
        print(f"  skip: {fs}"); return
    assert fs == [], f"R-LIFT-CSS-BUDGET fired on a small lifted slide; got {fs}"


def test_clean_examples_are_silent():
    """MUST-NOT-FIRE (CALIBRATION · highest-risk): the real clean example decks
    must produce ZERO R-LIFT-CSS-BUDGET findings (they have no lifted slides and
    no custom_css, so the rule self-exempts). If any fires, the rule is
    over-reaching — it must never touch an authored deck."""
    if not _visual_available():
        print("  skip: playwright not installed (gated test)"); return
    available = [e for e in CLEAN_EXAMPLES if e.exists()]
    if not available:
        print("  skip: no clean example decks found"); return
    ran_any = False
    for ex in available:
        fs = _example_findings(ex)
        if fs is None:
            print("  skip: engine unavailable"); return
        if fs == "RENDER_FAILED":
            print(f"  skip: render failed for {ex.name}"); continue
        ran_any = True
        assert fs == [], \
            f"R-LIFT-CSS-BUDGET fired on clean example {ex.name}: {fs}"
    assert ran_any, "no clean example actually ran (all render-failed/skipped)"


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
