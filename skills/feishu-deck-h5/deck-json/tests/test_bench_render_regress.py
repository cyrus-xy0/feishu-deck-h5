"""Unit tests for bench-render.py --fail-on-regress core (the perf-CI gate).

Covers only the side-effect-free `_regressions()` function so the gate logic is
verified WITHOUT launching Chromium (the timing harness itself needs a browser;
the regression decision does not). stdlib only."""
import importlib.util, pathlib

HERE = pathlib.Path(__file__).resolve().parents[2]  # skills/feishu-deck-h5/
_spec = importlib.util.spec_from_file_location(
    "bench_render", HERE / "assets" / "bench-render.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


def _seg(ms):
    return {"median_ms": ms}


def test_flags_real_regression_above_pct():
    seg = {"render_advisory": _seg(6000.0)}
    base = {"render_advisory": _seg(4600.0)}          # +30.4%
    regs = bench._regressions(seg, base, pct=20.0, noise_floor=50.0)
    assert [r["name"] for r in regs] == ["render_advisory"]
    assert abs(regs[0]["delta_pct"] - 30.4) < 0.2


def test_noise_floor_ignores_tiny_segments():
    # +300% but the baseline median is below the noise floor → must be ignored,
    # otherwise a 10ms→40ms jitter on deck_cli_set would flap the CI gate.
    seg = {"deck_cli_set": _seg(40.0)}
    base = {"deck_cli_set": _seg(10.0)}
    assert bench._regressions(seg, base, pct=20.0, noise_floor=50.0) == []
    # raise the floor enough and a genuinely-large segment still counts
    seg2 = {"validate_visual_json": _seg(6300.0)}
    base2 = {"validate_visual_json": _seg(4200.0)}     # +50%
    assert [r["name"] for r in bench._regressions(seg2, base2, 20.0, 50.0)] \
        == ["validate_visual_json"]


def test_improvement_is_not_a_regression():
    seg = {"validate_visual_json": _seg(3000.0)}
    base = {"validate_visual_json": _seg(4200.0)}      # faster
    assert bench._regressions(seg, base, 20.0, 50.0) == []


def test_pct_boundary_is_strict():
    # exactly at the threshold is NOT a regression (delta_pct > pct is strict).
    seg = {"render_advisory": _seg(1200.0)}
    base = {"render_advisory": _seg(1000.0)}           # +20.0% exactly
    assert bench._regressions(seg, base, 20.0, 50.0) == []
    seg2 = {"render_advisory": _seg(1200.1)}           # a hair over
    assert len(bench._regressions(seg2, base, 20.0, 50.0)) == 1


def test_missing_in_either_run_is_skipped():
    seg = {"only_now": _seg(9000.0)}
    base = {"only_base": _seg(100.0)}
    assert bench._regressions(seg, base, 20.0, 50.0) == []
    # a segment present but with no median (skipped/None) does not crash
    assert bench._regressions({"x": None}, {"x": _seg(100.0)}, 20.0, 50.0) == []
    assert bench._regressions({"x": _seg(None)}, {"x": _seg(100.0)}, 20.0, 50.0) == []


def test_empty_and_none_inputs_safe():
    assert bench._regressions({}, {}, 20.0, 50.0) == []
    assert bench._regressions(None, None, 20.0, 50.0) == []
    assert bench._regressions({"a": _seg(100.0)}, None, 20.0, 50.0) == []
