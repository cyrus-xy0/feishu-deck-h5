"""Snapshot regression gate: the set of VISUAL-rule findings on the example decks
must not drift.

This catches the failure mode that synthetic unit fixtures structurally miss — a
validator SELECTOR change that introduces FALSE POSITIVES (or silently drops
coverage) on real, fully-rendered decks. It is the gate that would have caught the
2026-05-31 raw-fix regression in CI: every synthetic fixture passed, yet the example
decks grew 8 (PEER-SIZE) + 2 (CARD-OVERFLOW) brand-new findings from a tag/`*`
fallback. A per-rule fixture can't see that, because it only renders the one shape it
was written for.

How it works
------------
Corpus (broad layout coverage, all checked in):
  * examples/sample-deck.html              — the 14-layout reference (self-contained)
  * deck-json/examples/phase-1c-extras.json — matrix / before-after / tree / swim /
                                              waterfall / logo-wall / arch-stack

Signature = (deck, slide_index, rule_id) for every VISUAL-family finding. No pixel
values and no selectors, so the snapshot is stable across content-neutral re-renders
and Chromium minor jitter, but sensitive to a rule firing on a NEW slide or vanishing
from one — exactly the regression signal we want.

The baseline (baselines/example_decks_visual.txt) captures the ACCEPTED CURRENT state,
not an ideal — its job is "don't ADD or DROP findings without a human reviewing it",
not "have zero findings". Any drift fails the test and prints the exact delta.

Updating the baseline (after an INTENTIONAL validator change)
------------------------------------------------------------
    python3 deck-json/tests/test_examples_visual_baseline.py --update
Review the diff (git diff on the baseline file) before committing — a growing baseline
means new findings; a shrinking one means dropped coverage. Either way, a human signs off.
"""
import pathlib
import re
import subprocess
import sys
import tempfile

# pytest is imported LAZILY inside the test fn (not at module top) so this file imports
# cleanly under the CI's `unittest` discovery, where pytest is not installed. Matches the
# sibling test_vis_*.py convention.

HERE = pathlib.Path(__file__).resolve()
SKILL = HERE.parents[2]
ASSETS = SKILL / "assets"
EXAMPLES = SKILL / "examples"
DECK_EXAMPLES = SKILL / "deck-json" / "examples"
BASELINE = HERE.parent / "baselines" / "example_decks_visual.txt"

# Rules emitted by the visual (Chromium) pass — the family a selector change can move.
VISUAL_RULE = re.compile(
    r"\[(R-VIS-[A-Z-]+|R-OVERFLOW|R-OVERLAP|R-FOCAL-CHECK|R-VISUAL)\]\s+slide\s+(\d+)"
)
_SKIP_MARK = re.compile(r"visual audit.*skip|skip.*visual audit|playwright not installed", re.I)


def _chromium_ok():
    try:
        import playwright.sync_api  # noqa: F401
    except Exception:
        return False
    return True


def _validate(html_path):
    r = subprocess.run(
        [sys.executable, str(ASSETS / "validate.py"), str(html_path)],
        capture_output=True, text=True,
    )
    return r.stdout + r.stderr


def _sigs(deck_label, text):
    return {f"{deck_label}\t{m.group(2)}\t{m.group(1)}" for m in VISUAL_RULE.finditer(text)}


def _collect():
    """Render + validate the corpus. Returns (sigs:set, skipped:bool).
    skipped=True means the visual pass could not run (chromium missing) → caller skips."""
    sigs = set()

    smp = EXAMPLES / "sample-deck.html"
    if smp.exists():
        out = _validate(smp)
        if _SKIP_MARK.search(out):
            return sigs, True
        sigs |= _sigs("sample-deck", out)

    p1c = DECK_EXAMPLES / "phase-1c-extras.json"
    if p1c.exists():
        with tempfile.TemporaryDirectory() as td:
            out_dir = pathlib.Path(td) / "out"
            subprocess.run(
                [sys.executable, str(SKILL / "deck-json" / "render-deck.py"), str(p1c), str(out_dir) + "/"],
                capture_output=True, text=True,
            )
            idx = out_dir / "index.html"
            if idx.exists():
                subprocess.run(
                    [sys.executable, str(ASSETS / "copy-assets.py"), str(out_dir)],
                    capture_output=True, text=True,
                )
                out = _validate(idx)
                if _SKIP_MARK.search(out):
                    return sigs, True
                sigs |= _sigs("phase-1c", out)

    return sigs, False


def _read_baseline():
    if not BASELINE.exists():
        return None
    return {l.rstrip("\n") for l in BASELINE.read_text(encoding="utf-8").splitlines() if l.strip()}


def _write_baseline(sigs):
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text("\n".join(sorted(sigs)) + "\n", encoding="utf-8")


def test_visual_findings_match_baseline():
    import pytest
    if not _chromium_ok():
        pytest.skip("Chromium/Playwright unavailable")
    baseline = _read_baseline()
    if baseline is None:
        pytest.skip(f"no baseline yet — generate with: python3 {HERE} --update")
    current, skipped = _collect()
    if skipped:
        pytest.skip("visual audit skipped (chromium missing in validate.py subprocess)")

    new = current - baseline
    missing = baseline - current
    if not new and not missing:
        return

    parts = []
    if new:
        parts.append(
            "NEW visual findings on example decks — a selector change likely introduced "
            "FALSE POSITIVES (the failure synthetic fixtures cannot see):\n  "
            + "\n  ".join(sorted(new))
        )
    if missing:
        parts.append(
            "MISSING visual findings — coverage silently dropped vs the baseline:\n  "
            + "\n  ".join(sorted(missing))
        )
    parts.append(
        "If this drift is INTENTIONAL, review it and regenerate the baseline:\n"
        f"  python3 {HERE} --update"
    )
    pytest.fail("\n\n".join(parts))


if __name__ == "__main__":
    if "--update" in sys.argv:
        if not _chromium_ok():
            print("Chromium/Playwright unavailable — cannot generate baseline")
            sys.exit(2)
        sigs, skipped = _collect()
        if skipped:
            print("visual audit skipped (chromium missing) — cannot generate baseline")
            sys.exit(2)
        _write_baseline(sigs)
        print(f"wrote {len(sigs)} signatures to {BASELINE.relative_to(SKILL)}")
    else:
        print(f"usage: python3 {HERE.name} --update")
