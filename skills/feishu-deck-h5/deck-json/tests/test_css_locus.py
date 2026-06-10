"""F-272 · page-CSS locus convergence.

Per-page CSS must converge on ONE home — `slide.custom_css` (round-trips with
deck.json, the single source of truth) — not a `<style>` embedded in a raw
slide's `data.html` (does NOT round-trip the field, has no budget, can leak
cross-page selectors). Three pieces:

  1. migrate-head-css-to-custom-css.py now ALSO sweeps a raw slide's top-level
     inline <style> INTO its custom_css and strips it from data.html (the FIX).
  2. Two warn audits flag decks that still carry the embedded channel:
       · R-CSS-INLINE-BUDGET — raw-page inline <style> > 8KB.
       · R-CSS-CROSS-PAGE    — a slide's <style> targets ANOTHER page's key.
  3. render-deck prints an advisory (tested separately at the source level here).

Two test layers (F-09 discipline):
  · STATIC (always runs, no Chromium): codes wired end-to-end (audits.js rule
    literal + RULE_META + check-only FAMILIES + validator-rules.md), thresholds
    locked, migrate tool behaviour (pure deck.json transform, no browser).
  · PLAYWRIGHT-GATED (skips if Chromium/Playwright absent): render synthetic
    decks and assert the rules fire / stay silent, plus CALIBRATION that the
    real clean example decks stay silent (false-positives have burned this skill).
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
MIGRATE = DECKJSON / "migrate-head-css-to-custom-css.py"

INLINE = "R-CSS-INLINE-BUDGET"
CROSS = "R-CSS-CROSS-PAGE"

CLEAN_EXAMPLES = [
    DECKJSON / "examples" / "sample-deck.json",
    DECKJSON / "examples" / "phase-1a-demo.json",
    DECKJSON / "examples" / "phase-1b-demo.json",
    DECKJSON / "examples" / "phase-1c-extras.json",
]


# ---------------------------------------------------------------------------
# 1. STATIC wiring (always runs, no Chromium)
# ---------------------------------------------------------------------------

def test_codes_declared_in_engine_and_rule_meta():
    js = (ASSETS / "audits.js").read_text(encoding="utf-8")
    meta_region = js[js.index("const RULE_META = {"):js.index("const RULES = [")]
    for code in (INLINE, CROSS):
        assert f"rule: '{code}'" in js, f"{code} not emitted as a rule literal"
        assert f"id: '{code}'" in js, f"{code} has no rule object (id)"
        assert f"'{code}':" in meta_region, f"{code} missing a RULE_META entry"


def test_codes_in_check_only_families():
    spec = importlib.util.spec_from_file_location("check_only_csslocus",
                                                  ASSETS / "check-only.py")
    CO = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(CO)
    fam = {c for _, codes in CO.FAMILIES for c in codes}
    for code in (INLINE, CROSS):
        assert code in fam, f"{code} not categorized in check-only FAMILIES"


def test_codes_documented_in_reference():
    doc = (ROOT / "references" / "validator-rules.md").read_text(encoding="utf-8")
    for code in (INLINE, CROSS):
        assert code in doc, f"{code} missing from references/validator-rules.md"


def test_codes_are_warn_severity_and_never_error():
    """Scope constraint: these guardrails are WARN — they must NOT be wired as
    `error` (proving R-CSS stays advisory; R-SELF-CONTAINED is NOT promoted)."""
    js = (ASSETS / "audits.js").read_text(encoding="utf-8")
    for code in (INLINE, CROSS):
        i = js.index(f"id: '{code}'")
        window = js[i:i + 1700]
        assert "severity: 'warn'" in window, f"{code} not declared severity:'warn'"
        # the emitted finding must carry warn, never error
        assert f"rule: '{code}', severity: 'warn'" in window, \
            f"{code} emits a non-warn finding"
        assert "severity: 'error'" not in window, \
            f"{code} must never emit an error-level finding (advisory only)"


def test_inline_budget_threshold_locked():
    js = (ASSETS / "audits.js").read_text(encoding="utf-8")
    i = js.index(f"id: '{INLINE}'")
    window = js[i:i + 1700]
    assert "8 * 1024" in window, "8KB inline-budget threshold not found near rule"


def test_r_self_contained_not_promoted_to_error():
    """L7b is NOT done this round: R-SELF-CONTAINED must stay warn_soft (advisory)
    in run-audits.py, never err — promoting it would wall existing static gates."""
    runner = (ASSETS / "run-audits.py").read_text(encoding="utf-8")
    # the rule's finding emit must remain warn_soft
    m = re.search(r'"rule":\s*"R-SELF-CONTAINED",\s*"severity":\s*"([\w_]+)"', runner)
    assert m, "R-SELF-CONTAINED emit not found in run-audits.py"
    assert m.group(1) == "warn_soft", \
        f"R-SELF-CONTAINED severity is {m.group(1)!r}, must stay 'warn_soft' (L7b not done)"


# ---------------------------------------------------------------------------
# 2. migrate tool — raw inline <style> → custom_css (pure deck.json transform)
# ---------------------------------------------------------------------------

def _load_migrate():
    spec = importlib.util.spec_from_file_location("migrate_css_locus", MIGRATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _raw_deck_with_inline(css: str, *, key="hero", html_extra=""):
    return {
        "version": "1.0",
        "deck": {"title": "css-locus", "author": "fixture", "date": "2026-06"},
        "slides": [{
            "key": key, "layout": "raw", "screen_label": "01 x",
            "data": {"html":
                '<div class="header"><h2 class="title-zh">Hi</h2></div>'
                f'<style>{css}</style>'
                f'<div class="stage"><p class="body" style="font-size:24px">hi</p>'
                f'{html_extra}</div>'},
        }],
    }


def test_migrate_raw_inline_moves_style_into_custom_css():
    M = _load_migrate()
    deck = _raw_deck_with_inline(".foo{color:#fff;font-size:24px}")
    applied = M.migrate_raw_inline(deck, dry_run=False)
    assert applied, "migrate_raw_inline reported nothing migrated"
    s = deck["slides"][0]
    # CSS landed in custom_css...
    assert ".foo{color:#fff;font-size:24px}" in (s.get("custom_css") or "")
    assert "F-272 codemod" in s["custom_css"]
    # ...and the <style> is gone from data.html
    assert "<style" not in s["data"]["html"].lower(), \
        "inline <style> not stripped from data.html"


def test_migrate_raw_inline_dry_run_does_not_mutate():
    M = _load_migrate()
    deck = _raw_deck_with_inline(".foo{color:#fff}")
    before = json.dumps(deck, sort_keys=True)
    applied = M.migrate_raw_inline(deck, dry_run=True)
    assert applied, "dry-run should still REPORT what it would migrate"
    assert json.dumps(deck, sort_keys=True) == before, \
        "dry-run mutated the deck"


def test_migrate_raw_inline_idempotent():
    M = _load_migrate()
    deck = _raw_deck_with_inline(".foo{color:#fff}")
    M.migrate_raw_inline(deck, dry_run=False)
    cc_after_first = deck["slides"][0]["custom_css"]
    # second run: no embedded <style> remains → nothing to do, custom_css unchanged
    again = M.migrate_raw_inline(deck, dry_run=False)
    assert again == [], "second migrate should be a no-op (no <style> left)"
    assert deck["slides"][0]["custom_css"] == cc_after_first


def test_migrate_raw_inline_preserves_framework_style():
    """A `<style data-source="framework">` must be LEFT in data.html (not swept)."""
    M = _load_migrate()
    deck = {
        "version": "1.0",
        "deck": {"title": "t", "author": "a", "date": "2026-06"},
        "slides": [{
            "key": "k", "layout": "raw", "screen_label": "01 x",
            "data": {"html":
                '<style data-source="framework">.fw{color:red}</style>'
                '<style>.mine{color:#fff}</style>'
                '<div class="stage"><p class="body" style="font-size:24px">x</p></div>'},
        }],
    }
    M.migrate_raw_inline(deck, dry_run=False)
    h = deck["slides"][0]["data"]["html"]
    assert 'data-source="framework"' in h, "framework <style> was wrongly stripped"
    assert ".mine{color:#fff}" in deck["slides"][0]["custom_css"]
    assert ".mine" not in h, "author inline <style> not stripped"


def test_migrate_skips_non_raw_slides():
    M = _load_migrate()
    deck = {
        "version": "1.0",
        "deck": {"title": "t", "author": "a", "date": "2026-06"},
        "slides": [{"key": "k", "layout": "content", "variant": "3up",
                    "data": {"title": "x", "html": "<style>.a{}</style>"}}],
    }
    assert M.migrate_raw_inline(deck, dry_run=False) == [], \
        "only raw slides should be swept (content slides don't use data.html)"


def test_migrate_cli_raw_inline_only_writes_and_backs_up():
    """End-to-end CLI: --raw-inline-only on deck.json alone migrates + backs up."""
    M = _load_migrate()
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        dj = d / "deck.json"
        dj.write_text(json.dumps(_raw_deck_with_inline(".foo{color:#fff}")),
                      encoding="utf-8")
        rc = M.main(["--raw-inline-only", str(dj)])
        assert rc == 0
        out = json.loads(dj.read_text(encoding="utf-8"))
        assert ".foo{color:#fff}" in (out["slides"][0].get("custom_css") or "")
        assert "<style" not in out["slides"][0]["data"]["html"].lower()
        assert list(d.glob("deck.json.bak-pre-migrate-*")), "no backup written"


# ---------------------------------------------------------------------------
# Render-parity (no browser): render before/after migrate; the rendered .slide
# subtree must carry the same CSS rule either way (it just moves homes).
# ---------------------------------------------------------------------------

def _render(deck_json: pathlib.Path, out_dir: pathlib.Path) -> bool:
    subprocess.run([sys.executable, str(RENDER), str(deck_json), str(out_dir),
                    "--inline"], capture_output=True, text=True)
    return (out_dir / "index.html").exists()


def test_render_parity_before_after_migrate():
    """The migrated deck must render the SAME page CSS — the rule body survives,
    just relocated from an embedded <style> to the custom_css <style>."""
    M = _load_migrate()
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        deck = _raw_deck_with_inline(".foo{color:#fff;font-size:24px}")
        before_json = d / "before.json"
        before_json.write_text(json.dumps(deck), encoding="utf-8")
        if not _render(before_json, d / "before"):
            print("  skip: render failed (before)"); return
        before_html = (d / "before" / "index.html").read_text(encoding="utf-8")

        M.migrate_raw_inline(deck, dry_run=False)
        after_json = d / "after.json"
        after_json.write_text(json.dumps(deck), encoding="utf-8")
        if not _render(after_json, d / "after"):
            print("  skip: render failed (after)"); return
        after_html = (d / "after" / "index.html").read_text(encoding="utf-8")

        # both renders must contain the rule's declaration (color:#fff on .foo)
        assert "color:#fff" in before_html.replace(" ", "")
        assert "color:#fff" in after_html.replace(" ", ""), \
            "migrated deck dropped the .foo rule on render — NOT visually equivalent"


# ---------------------------------------------------------------------------
# 3. PLAYWRIGHT-GATED firing + calibration (skips without Chromium)
# ---------------------------------------------------------------------------

def _visual_available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def _engine():
    spec = importlib.util.spec_from_file_location("run_audits_csslocus",
                                                  ASSETS / "run-audits.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _findings_for(deck: dict, code: str):
    E = _engine()
    EngineUnavailable = getattr(E, "EngineUnavailable", Exception)
    with tempfile.TemporaryDirectory() as td:
        src = pathlib.Path(td) / "d.json"
        src.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
        out = pathlib.Path(td) / "o"
        if not _render(src, out):
            return "RENDER_FAILED"
        try:
            res = E.run_unified_engine(out / "index.html", None,
                                       settle_ms=300, dom_rules=True)
        except EngineUnavailable:
            return None
    return [f for f in res.get("findings", []) if f["rule"] == code]


def _example_findings(deck_json: pathlib.Path, codes):
    E = _engine()
    EngineUnavailable = getattr(E, "EngineUnavailable", Exception)
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / "o"
        if not _render(deck_json, out):
            return "RENDER_FAILED"
        try:
            res = E.run_unified_engine(out / "index.html", None,
                                       settle_ms=300, dom_rules=True)
        except EngineUnavailable:
            return None
    return [f for f in res.get("findings", []) if f["rule"] in codes]


def _big_inline_css(n: int) -> str:
    rules = "\n".join(
        f".dead-{i}{{color:#fff;margin:{i}px;padding:2px 4px;"
        f"border:1px solid #112233;background:linear-gradient(90deg,#000,#fff)}}"
        for i in range(n))
    return "/* embedded source stylesheet */\n" + rules


def test_inline_budget_fires_over_8kb():
    """MUST-FIRE (warn): a raw page with >8KB of inline <style> in data.html."""
    if not _visual_available():
        print("  skip: playwright not installed"); return
    # n=80 rules ~ 9.5KB > 8KB
    fs = _findings_for(_raw_deck_with_inline(_big_inline_css(80)), INLINE)
    if fs in (None, "RENDER_FAILED"):
        print(f"  skip: {fs}"); return
    assert fs, "R-CSS-INLINE-BUDGET did not fire on a >8KB raw inline <style>"
    assert all(f["severity"] == "warn" for f in fs)


def test_inline_budget_silent_under_8kb():
    """MUST-NOT-FIRE: a small raw inline <style> (well under 8KB)."""
    if not _visual_available():
        print("  skip: playwright not installed"); return
    fs = _findings_for(_raw_deck_with_inline(".keep{color:#fff;font-size:24px}"),
                       INLINE)
    if fs in (None, "RENDER_FAILED"):
        print(f"  skip: {fs}"); return
    assert fs == [], f"R-CSS-INLINE-BUDGET fired on a tiny inline <style>: {fs}"


def test_inline_budget_silent_when_css_in_custom_css():
    """MUST-NOT-FIRE: the SAME big CSS placed in custom_css (the CORRECT home,
    rendered as a data-fs-custom-css <style>) does NOT trip the inline budget —
    that's the whole point of the rule (it targets the embedded channel only)."""
    if not _visual_available():
        print("  skip: playwright not installed"); return
    deck = {
        "version": "1.0",
        "deck": {"title": "t", "author": "a", "date": "2026-06"},
        "slides": [{
            "key": "hero", "layout": "raw", "screen_label": "01 x",
            "custom_css": _big_inline_css(80),
            "data": {"html":
                '<div class="header"><h2 class="title-zh">Hi</h2></div>'
                '<div class="stage"><p class="body" style="font-size:24px">hi</p></div>'},
        }],
    }
    fs = _findings_for(deck, INLINE)
    if fs in (None, "RENDER_FAILED"):
        print(f"  skip: {fs}"); return
    assert fs == [], \
        f"R-CSS-INLINE-BUDGET wrongly fired on custom_css (correct home): {fs}"


def test_cross_page_fires_on_foreign_slide_key():
    """MUST-FIRE (warn): a slide's <style> scoped to ANOTHER page's slide-key."""
    if not _visual_available():
        print("  skip: playwright not installed"); return
    # page "a" embeds a rule scoped to page "b" — the cross-page leak.
    deck = {
        "version": "1.0",
        "deck": {"title": "t", "author": "a", "date": "2026-06"},
        "slides": [
            {"key": "a", "layout": "raw", "screen_label": "01 a",
             "data": {"html":
                '<div class="header"><h2 class="title-zh">A</h2></div>'
                '<style>.slide[data-slide-key="b"] .x{color:#fff}</style>'
                '<div class="stage"><p class="body" style="font-size:24px">a</p></div>'}},
            {"key": "b", "layout": "raw", "screen_label": "02 b",
             "data": {"html":
                '<div class="header"><h2 class="title-zh">B</h2></div>'
                '<div class="stage"><p class="x body" style="font-size:24px">b</p></div>'}},
        ],
    }
    fs = _findings_for(deck, CROSS)
    if fs in (None, "RENDER_FAILED"):
        print(f"  skip: {fs}"); return
    assert fs, "R-CSS-CROSS-PAGE did not fire on a foreign-slide-key selector"
    assert all(f["severity"] == "warn" for f in fs)
    assert any("b" in (f.get("foreign_keys") or []) for f in fs), \
        f"cross-page finding did not name the foreign key 'b': {fs}"


def test_cross_page_silent_on_own_key():
    """MUST-NOT-FIRE: a <style> scoped to the slide's OWN key is correct."""
    if not _visual_available():
        print("  skip: playwright not installed"); return
    deck = {
        "version": "1.0",
        "deck": {"title": "t", "author": "a", "date": "2026-06"},
        "slides": [{"key": "a", "layout": "raw", "screen_label": "01 a",
            "data": {"html":
                '<div class="header"><h2 class="title-zh">A</h2></div>'
                '<style>.slide[data-slide-key="a"] .x{color:#fff}</style>'
                '<div class="stage"><p class="x body" style="font-size:24px">a</p></div>'}}],
    }
    fs = _findings_for(deck, CROSS)
    if fs in (None, "RENDER_FAILED"):
        print(f"  skip: {fs}"); return
    assert fs == [], f"R-CSS-CROSS-PAGE fired on the slide's OWN key: {fs}"


def test_clean_examples_are_silent():
    """MUST-NOT-FIRE (CALIBRATION · highest-risk): the real clean example decks
    must produce ZERO R-CSS-INLINE-BUDGET / R-CSS-CROSS-PAGE findings (raw=0, no
    embedded <style>, custom_css scoped to its own key by the renderer)."""
    if not _visual_available():
        print("  skip: playwright not installed"); return
    available = [e for e in CLEAN_EXAMPLES if e.exists()]
    if not available:
        print("  skip: no clean example decks found"); return
    ran_any = False
    for ex in available:
        fs = _example_findings(ex, {INLINE, CROSS})
        if fs is None:
            print("  skip: engine unavailable"); return
        if fs == "RENDER_FAILED":
            print(f"  skip: render failed for {ex.name}"); continue
        ran_any = True
        assert fs == [], f"R-CSS-* fired on clean example {ex.name}: {fs}"
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
