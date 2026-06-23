"""F-293 · `--scope-frames` feeds a render SCOPE into the unified engine so a
single-page `--scope` render only AUDITS the changed frame(s) instead of all N
slides (华泰: 50 pages ~7s of per-slide audits → just the changed one).

Two layers are pinned here:

  1. CLI WIRING (fast, no browser, always runs) — `validate.py --scope-frames N`
     parses the 1-based comma list and threads it as the engine `scope` (NOT the
     `--slide` post-run report filter). `run_unified_audits` is monkeypatched to
     capture the scope it receives, so the parse path is exercised without
     Chromium.

  2. ENGINE BEHAVIOUR (requires Chromium, skips cleanly) — with a real scope:
       • a PER-SLIDE rule (R-VIS-BODY-FLOOR, name-free geometry) fires ONLY for
         the scoped frame; off-scope slides are SKIPPED (not just filtered after).
       • a DECK-LEVEL rule (R-VIS-NO-IMAGERY, anchored on isFirstInScope, scans
         the whole DOM) STILL emits — scope must NOT swallow deck-level rules.
     A baseline full-deck run shows the per-slide rule firing on BOTH violating
     frames, proving scope genuinely narrowed it.

This guards the F-256/F-292 gate contract too: scoping the engine changes only
WHICH per-slide frames are evaluated; the deck-level rules (and therefore the
gate findings they feed) are untouched. The render-gate BLOCK semantics are
pinned separately by test_render_gate.py.
"""
import importlib.util
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve()
VALIDATE = HERE.parents[2] / "assets" / "validate.py"

sys.path.insert(0, str(HERE.parent))          # tests/ dir → engine_helpers
import engine_helpers as EH                    # noqa: E402


# ---------------------------------------------------------------------------
#  helpers
# ---------------------------------------------------------------------------
def _load_validate():
    """Import assets/validate.py as a module. It does `from _validate_common
    import *`, so its dir must be on sys.path (no conftest path-setup when run
    standalone)."""
    assets = str(VALIDATE.parent)
    if assets not in sys.path:
        sys.path.insert(0, assets)
    spec = importlib.util.spec_from_file_location("validate_f293", VALIDATE)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run_main_capture_scope(monkeypatch, tmp_path, argv_extra):
    """Run validate.main() with a minimal real HTML file but a STUBBED engine
    call, capturing the `scope` kwarg `run_unified_audits` received. Returns
    (exit_code, captured_scope). Fast — no browser involved."""
    v = _load_validate()
    captured = {}

    def _fake_run_unified_audits(path, iss, *, dom_rules=True, scope=None,
                                 want_screenshots=False, with_distribution=False):
        captured["scope"] = scope
        captured["dom_rules"] = dom_rules
        # emit nothing → clean PASS, exit 0

    monkeypatch.setattr(v, "run_unified_audits", _fake_run_unified_audits)
    # probe_effective_cjk_font would launch Chromium on the --json path; stub it.
    monkeypatch.setattr(v, "probe_effective_cjk_font", lambda p: "stub")

    html = tmp_path / "index.html"
    html.write_text(
        '<!doctype html><html><body><div class="deck">'
        '<div class="slide-frame"><div class="slide" data-layout="content" '
        'data-slide-key="a" data-screen-label="a">x</div></div>'
        '<div class="slide-frame"><div class="slide" data-layout="content" '
        'data-slide-key="b" data-screen-label="b">y</div></div>'
        '</div></body></html>',
        encoding="utf-8")

    monkeypatch.setattr(sys, "argv",
                        ["validate.py", str(html), *argv_extra])
    code = v.main()
    return code, captured


# ---------------------------------------------------------------------------
#  1 · CLI wiring (no browser, always runs)
# ---------------------------------------------------------------------------
def test_source_declares_scope_frames_flag_and_threads_engine_scope():
    """--scope-frames exists, and is wired to the ENGINE scope param of
    run_unified_audits (not the --slide report filter)."""
    src = VALIDATE.read_text(encoding="utf-8")
    assert "--scope-frames" in src
    assert "scope=scope_frames" in src
    # __AUDIT_SCOPE__ is the mechanism it ultimately drives (documented in help).
    assert "__AUDIT_SCOPE__" in src


def test_scope_frames_single_parsed_to_engine(monkeypatch, tmp_path):
    code, cap = _run_main_capture_scope(
        monkeypatch, tmp_path, ["--no-visual", "--scope-frames", "2"])
    assert code == 0
    assert cap["scope"] == [2]


def test_scope_frames_multi_parsed_to_engine(monkeypatch, tmp_path):
    code, cap = _run_main_capture_scope(
        monkeypatch, tmp_path, ["--no-visual", "--scope-frames", "2,3"])
    assert code == 0
    assert cap["scope"] == [2, 3]


def test_no_scope_frames_means_full_deck(monkeypatch, tmp_path):
    """Absent flag → scope=None → engine audits the WHOLE deck (unchanged
    default behaviour)."""
    code, cap = _run_main_capture_scope(
        monkeypatch, tmp_path, ["--no-visual"])
    assert code == 0
    assert cap["scope"] is None


def test_scope_frames_tolerates_whitespace_and_empty_tokens(monkeypatch, tmp_path):
    code, cap = _run_main_capture_scope(
        monkeypatch, tmp_path, ["--no-visual", "--scope-frames", " 2 , 3 ,"])
    assert code == 0
    assert cap["scope"] == [2, 3]


def test_scope_frames_invalid_is_input_error(monkeypatch, tmp_path):
    """Non-integer tokens are a usage error (exit 2), never a silent full-deck
    fallback that would quietly re-audit all 50 pages."""
    code, cap = _run_main_capture_scope(
        monkeypatch, tmp_path, ["--no-visual", "--scope-frames", "two"])
    assert code == 2
    assert "scope" not in cap     # bailed before the engine call


def test_scope_frames_is_independent_of_slide_filter(monkeypatch, tmp_path):
    """--scope-frames (engine scope) and --slide (post-run report filter) are
    orthogonal: passing only --slide must NOT set an engine scope."""
    v = _load_validate()
    captured = {}
    monkeypatch.setattr(
        v, "run_unified_audits",
        lambda path, iss, *, dom_rules=True, scope=None, want_screenshots=False,
        with_distribution=False:
            captured.__setitem__("scope", scope))
    monkeypatch.setattr(v, "probe_effective_cjk_font", lambda p: "stub")
    html = tmp_path / "index.html"
    html.write_text(
        '<!doctype html><html><body><div class="deck"><div class="slide-frame">'
        '<div class="slide" data-layout="content" data-slide-key="a" '
        'data-screen-label="a">x</div></div></div></body></html>',
        encoding="utf-8")
    monkeypatch.setattr(sys, "argv",
                        ["validate.py", str(html), "--no-visual", "--slide", "1"])
    v.main()
    assert captured["scope"] is None   # --slide does NOT feed the engine scope


# ---------------------------------------------------------------------------
#  2 · engine behaviour (Chromium required — skips cleanly without it)
# ---------------------------------------------------------------------------
# A 3-content-page deck:
#   • ALL three are text-only (zero imagery) → R-VIS-NO-IMAGERY (deck-level,
#     warn_soft, anchored on isFirstInScope, scans every .slide) would fire
#     (3/3 flat ≥ 0.6 threshold).
#   • slides 1 AND 2 each carry a body-floor violation (an 18px sentence-like
#     <p>) → R-VIS-BODY-FLOOR (per-slide, error) fires on EACH of them in a full
#     run.
# Scoping to [2] must: keep the per-slide R-VIS-BODY-FLOOR for slide 2 only
# (slide 1's suppressed — its frame is never evaluated), yet STILL surface the
# deck-level R-VIS-NO-IMAGERY (it scans the whole DOM regardless of scope).
def _floor_p():
    # ≥8 chars of direct sentence text at <24px, outside chrome/mock → fires
    # R-VIS-BODY-FLOOR. Plain <p>, no imagery, so the slide also stays "flat".
    return ('<p style="font-size:18px">This sentence renders below the body '
            'floor on the projector.</p>')


def _content_slide(idx, *, floor=False):
    body = (_floor_p() if floor
            else '<p style="font-size:28px">Headline body copy at tier.</p>')
    return (
        f'<div class="slide-frame"><div class="slide" data-layout="content" '
        f'data-screen-label="s{idx}" data-slide-key="s{idx}">'
        f'<span class="wordmark">飞书</span>{body}</div></div>')


def _three_page_deck():
    return [_content_slide(1, floor=True),
            _content_slide(2, floor=True),
            _content_slide(3, floor=False)]


def _floor_slides(findings):
    """Set of slide_idx that R-VIS-BODY-FLOOR fired on."""
    return {f.get("slide_idx") for f in findings
            if f.get("rule") == "R-VIS-BODY-FLOOR"}


def _no_imagery(findings):
    return [f for f in findings if f.get("rule") == "R-VIS-NO-IMAGERY"]


def test_full_deck_per_slide_rule_fires_on_both_violating_frames():
    """Baseline (no scope): the per-slide body-floor rule fires on BOTH slide 1
    and slide 2 — so scoping below is a genuine narrowing, not a fixture quirk."""
    EH.skip_if_no_engine()
    findings = EH.run(_three_page_deck())
    assert _floor_slides(findings) == {1, 2}


def test_scope_narrows_per_slide_rule_to_the_changed_frame():
    """scope=[2]: R-VIS-BODY-FLOOR fires ONLY for slide 2. Slide 1 is SKIPPED by
    the engine (its frame is never evaluated) — the whole point of feeding the
    scope in rather than auditing all frames then filtering."""
    EH.skip_if_no_engine()
    findings = EH.run(_three_page_deck(), scope=[2])
    assert _floor_slides(findings) == {2}, (
        "off-scope slide 1 should NOT be evaluated under scope=[2]")


def test_deck_level_rule_still_emits_under_scope():
    """scope=[2]: a DECK-LEVEL rule (R-VIS-NO-IMAGERY) must STILL fire — scope
    suppresses per-slide evaluation, never the whole-DOM deck rules. It anchors
    on the first IN-SCOPE frame (slide 2) and still reports flatness it found
    across the WHOLE deck (mentions an off-scope frame, e.g. #1/#3)."""
    EH.skip_if_no_engine()
    findings = EH.run(_three_page_deck(), scope=[2])
    ni = _no_imagery(findings)
    assert ni, "deck-level R-VIS-NO-IMAGERY was swallowed by --scope"
    # anchored on the in-scope frame, not the (excluded) frame 1
    assert ni[0].get("slide_idx") == 2
    # it scanned the whole deck: the flat list cites a frame OTHER than the
    # scoped one (e.g. #1 or #3), proving it didn't stop at the scope.
    msg = ni[0].get("message", "")
    assert ("#1(" in msg or "#3(" in msg), (
        "deck-level rule should report flatness across the WHOLE deck, "
        f"not only the scoped frame; got: {msg}")


def test_scope_only_first_page_anchors_deck_rule_there():
    """scope=[1]: the deck-level rule anchors on frame 1 (now the first in
    scope) and the per-slide rule fires only on frame 1 — symmetric to the
    scope=[2] case, confirming the anchor follows the scope."""
    EH.skip_if_no_engine()
    findings = EH.run(_three_page_deck(), scope=[1])
    assert _floor_slides(findings) == {1}
    ni = _no_imagery(findings)
    assert ni and ni[0].get("slide_idx") == 1


if __name__ == "__main__":
    import traceback
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            # crude DI for the monkeypatch-based tests when run standalone
            import inspect
            if "monkeypatch" in inspect.signature(fn).parameters:
                print(f"  skip {fn.__name__} (needs pytest monkeypatch)")
                continue
            fn(); print(f"  ok  {fn.__name__}")
        except Exception:
            failed += 1; print(f"FAIL  {fn.__name__}"); traceback.print_exc()
    print(f"\n{len(fns) - failed} ran/passed (monkeypatch tests need pytest)")
    sys.exit(1 if failed else 0)
