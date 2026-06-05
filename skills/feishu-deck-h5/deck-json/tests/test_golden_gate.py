"""C1b · golden-snapshot GATE for the unified engine's findings.

A tiny, deterministic fixture deck (tests/fixtures/golden-gate/deck.json — three
raw slides that deliberately trip a diverse, stable set of rules: an off-palette
hex R10, inline soft-white R-WHITE-TEXT, a bad data-decor R38, plus the geometry
rules that engage on the sparse raw stages — R-VIS-CANVAS-CENTER / R-VIS-FILL /
R-VIS-RAW-TITLE-POS / R-VIS-BALANCE) is RENDERED via render-deck.py, the unified
engine is run against the rendered index.html, and its findings are snapshotted
into a committed golden JSON.

The snapshot is the SHAPE of the findings, not the prose: for each rule code, the
per-severity counts and the sorted list of slide_idx it fired on. This is stable
across machines (no paths, no timing) yet sensitive to the things that matter —
a rule edit that changes WHICH slides a geometry rule fires on, or that
adds/drops a finding, surfaces as an explicit golden diff. That is exactly the
guard the resting-state geometry rules need (their measurement is the most
regression-prone surface).

Contract:
  · The golden MUST be generated with Chromium present (it captures the DOM /
    geometry rules). Regenerate with FS_UPDATE_SNAPSHOTS=1 and REVIEW the diff.
  · The test SKIPS gracefully when Chromium is unavailable (no false red on a
    browserless CI) — but it does NOT silently pass: a missing golden with no
    Chromium is a skip, never a green.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import pathlib
from collections import Counter

import pytest

HERE = pathlib.Path(__file__).resolve()
DECK_JSON = HERE.parents[1]
ASSETS = DECK_JSON.parents[0] / "assets"
RENDER = DECK_JSON / "render-deck.py"
FIXTURE = HERE.parent / "fixtures" / "golden-gate" / "deck.json"
GOLDEN = HERE.parent / "__snapshots__" / "golden-gate-findings.json"

sys.path.insert(0, str(HERE.parent))
import engine_helpers as E  # noqa: E402

# Load run-audits.py (hyphenated → importlib) — the single shared engine entry.
_spec = importlib.util.spec_from_file_location("run_audits_golden", ASSETS / "run-audits.py")
RA = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RA)


def _render(dest_dir) -> pathlib.Path:
    """Render the fixture deck.json → index.html in `dest_dir`."""
    r = subprocess.run(
        [sys.executable, str(RENDER), str(FIXTURE), str(dest_dir) + "/"],
        capture_output=True, text=True)
    assert r.returncode == 0, f"render failed:\n{r.stdout}\n{r.stderr}"
    out = pathlib.Path(dest_dir) / "index.html"
    assert out.is_file(), "render produced no index.html"
    return out


def _snapshot(findings) -> dict:
    """Normalize findings → a stable, machine-independent shape: per rule code,
    {counts: {severity: n}, slides: sorted([slide_idx, …])}. No paths, no
    messages (prose churns), but WHICH slides a rule fired on is captured (the
    geometry-rule resting-state signal we want to lock)."""
    by_rule = {}
    for f in findings:
        rule = f.get("rule", "?")
        by_rule.setdefault(rule, {"_sev": Counter(), "_slides": []})
        by_rule[rule]["_sev"][f.get("severity", "?")] += 1
        by_rule[rule]["_slides"].append(f.get("slide_idx", 0))
    out = {}
    for rule, agg in by_rule.items():
        out[rule] = {
            "counts": dict(sorted(agg["_sev"].items())),
            "slides": sorted(agg["_slides"]),
        }
    return dict(sorted(out.items()))


def _current_snapshot() -> dict:
    with tempfile.TemporaryDirectory() as td:
        idx = _render(td)
        result = RA.run_unified_engine(idx, None, dom_rules=True)
    return _snapshot(result.get("findings", []))


def test_engine_findings_match_golden():
    # Skip gracefully if Chromium can't run (probe via engine_helpers) — but the
    # golden itself MUST have been generated with Chromium present.
    try:
        E.skip_if_no_engine()
    except Exception:  # pragma: no cover — defensive
        pytest.skip("unified engine unavailable")

    current = _current_snapshot()

    if os.environ.get("FS_UPDATE_SNAPSHOTS") or not GOLDEN.is_file():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(
            json.dumps(current, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        if not os.environ.get("FS_UPDATE_SNAPSHOTS"):
            pytest.skip(f"[golden] bootstrapped {GOLDEN.name} — review & commit it")
        return

    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    if current != expected:
        import difflib
        diff = "\n".join(difflib.unified_diff(
            json.dumps(expected, ensure_ascii=False, indent=2).splitlines(),
            json.dumps(current, ensure_ascii=False, indent=2).splitlines(),
            fromfile="golden", tofile="current", lineterm="", n=2))
        raise AssertionError(
            "unified-engine findings changed vs the golden gate. If intentional "
            "(a deliberate rule edit), regenerate with FS_UPDATE_SNAPSHOTS=1 and "
            "REVIEW the diff — especially geometry-rule slide-set changes:\n"
            + diff[:6000])


def test_golden_covers_a_diverse_rule_set():
    """Guard the FIXTURE itself: it must keep exercising a broad spread of rules
    (content + geometry, error + warn) so the gate stays meaningful. If a future
    fixture edit narrows coverage, this fails loudly rather than silently shrink
    the gate."""
    if not GOLDEN.is_file():
        pytest.skip("golden not yet generated")
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    rules = set(golden)
    # Content/markup rules that must remain represented.
    assert {"R10", "R-WHITE-TEXT", "R38"} <= rules, \
        f"fixture lost content-rule coverage: {sorted(rules)}"
    # At least one geometry (R-VIS-*) rule must be present (resting-state guard).
    assert any(r.startswith("R-VIS-") for r in rules), \
        f"fixture lost geometry-rule coverage: {sorted(rules)}"
    # At least one error and one warn severity must appear across the snapshot.
    sevs = set()
    for agg in golden.values():
        sevs.update(agg["counts"])
    assert "error" in sevs and "warn" in sevs, \
        f"fixture must trip both error and warn severities: {sevs}"


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
