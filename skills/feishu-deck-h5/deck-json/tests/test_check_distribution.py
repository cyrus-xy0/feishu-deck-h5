"""check-distribution.py · signals_for() — name-free geometric distribution audit.

Playwright only collects per-slide measurements; signals_for() does the analysis
(L1 canvas offset/underfill, L2 group dead-band/cross-axis, L3 box). Pure Python,
so we test the thresholds directly with synthetic measurement objects.
"""
import sys
import importlib.util
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
_spec = importlib.util.spec_from_file_location("checkdist", ASSETS / "check-distribution.py")
cd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cd)


def _box(left, top, bottom, cy=None, ti=20, bi=20, sel="div.x", media=False):
    return {"left": left, "top": top, "bottom": bottom,
            "cy": cy if cy is not None else (top + bottom) / 2,
            "topInset": ti, "bottomInset": bi, "h": bottom - top, "sel": sel, "media": media}


def _s(**over):
    base = {
        "allowImbalance": False, "heroHint": False, "scale": 1,
        "container": {"h": 800, "topInset": 100, "bottomInset": 100,
                      "fillV": 0.8, "fillH": 0.8, "blockCount": 3},
        "gaps": [40, 40, 40],
        "boxes": [_box(0, 100, 200), _box(300, 100, 200)],
    }
    base.update(over)
    return base


def _codes(s):
    return {c for c, _, _ in cd.signals_for(s)}


def test_balanced_slide_emits_nothing():
    assert _codes(_s()) == set(), "balanced slide should produce no signals"


def test_allow_imbalance_override_silences_all():
    bad = _s(container={"h": 1000, "topInset": 30, "bottomInset": 250,
                        "fillV": 0.7, "fillH": 0.7, "blockCount": 3},
             allowImbalance=True)
    assert _codes(bad) == set(), "explicit data-allow-imbalance must silence (not a name whitelist)"


def test_l1_offset_top_heavy():
    s = _s(container={"h": 1000, "topInset": 30, "bottomInset": 250,
                      "fillV": 0.7, "fillH": 0.7, "blockCount": 3})
    assert "L1-OFFSET" in _codes(s), "asymmetric top/bottom inset (30 vs 250) not flagged"


def test_l1_underfill_v():
    s = _s(container={"h": 1000, "topInset": 100, "bottomInset": 100,
                      "fillV": 0.30, "fillH": 0.8, "blockCount": 3})
    assert "L1-UNDERFILL-V" in _codes(s), "≥2 blocks filling only 30% height not flagged"


def test_l2_deadband():
    s = _s(gaps=[40, 40, 400])     # one huge gap among small ones
    assert "L2-DEADBAND" in _codes(s), "dead-band (gap 400 vs median 40) not flagged"


def test_l2_crossaxis_misaligned_row():
    s = _s(boxes=[_box(0, 100, 300, cy=200), _box(400, 100, 300, cy=285)])  # cy 200 vs 285 (>64.8)
    assert "L2-CROSSAXIS" in _codes(s), "same-row boxes with 85px centerline mismatch not flagged"


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
