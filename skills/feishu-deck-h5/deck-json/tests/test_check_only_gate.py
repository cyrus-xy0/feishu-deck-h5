"""F-18 tests: the ingest gate must not silently drop a rule whose code was
renamed in validate.py but left stale in business-rules.yaml. The drift guard
warns (never blocks) and stays silent on clean code (all yaml codes covered).

Also a light guard that the shared V.inline_linked (F-14) is importable.
"""
import contextlib
import importlib.util
import io
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
import validate as V  # noqa: E402

# check-only.py has a hyphen → load via importlib
_spec = importlib.util.spec_from_file_location("check_only", ASSETS / "check-only.py")
CO = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CO)


def test_enumerate_covers_all_yaml_codes():
    """On clean code the yaml gate codes must all be emitted by validate.py —
    otherwise the gate is silently dropping a mandatory rule today."""
    emitted = CO.enumerate_validate_rules()
    assert emitted, "expected to extract some rule codes from validate.py"
    yaml_codes = set(CO.load_business_rules().keys())
    orphaned = yaml_codes - emitted
    assert orphaned == set(), f"yaml codes not emitted by validate.py: {orphaned}"


def test_drift_warns_on_orphan_code():
    """A yaml code absent from validate.py emissions → explicit stderr warning."""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        CO.warn_on_gate_rule_drift({"R06", "R-PHANTOM-XYZ"}, {"R06", "R02"})
    err = buf.getvalue()
    assert "R-PHANTOM-XYZ" in err
    assert "R06" not in err  # covered code must not be reported


def test_drift_silent_when_subset():
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        CO.warn_on_gate_rule_drift({"R06", "R02"}, {"R06", "R02", "R10"})
    assert buf.getvalue() == ""


def test_drift_silent_when_validate_unreadable():
    """If validate.py couldn't be scanned (empty emitted set), skip quietly —
    never block the gate on a read failure."""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        CO.warn_on_gate_rule_drift({"R06"}, set())
    assert buf.getvalue() == ""


def test_inline_linked_is_shared():
    """F-14: the helper lives in validate.py and check-only references it."""
    assert callable(getattr(V, "inline_linked", None))


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
