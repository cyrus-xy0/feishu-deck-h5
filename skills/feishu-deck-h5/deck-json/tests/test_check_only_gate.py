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


def test_enumerate_captures_lev_indirection():
    """Codes emitted via the lev/_lev aliases (not iss.err/warn directly) must
    still be captured — else they'd be mis-flagged as gate drift if ever gated."""
    emitted = CO.enumerate_validate_rules()
    # R-VIS-TIER is emitted only via _lev(...) in validate.py
    assert "R-VIS-TIER" in emitted


def test_inline_linked_is_shared():
    """F-14: single source — helper lives on validate.py, check-only keeps no
    copy and references the shared one, and it actually inlines a local link."""
    import tempfile
    assert callable(getattr(V, "inline_linked", None))
    assert not hasattr(CO, "_inline_linked")  # no leftover copy
    src = (ASSETS / "check-only.py").read_text(encoding="utf-8")
    assert "V.inline_linked(" in src  # call site uses the shared helper
    # behavioral round-trip: local <link> inlined, external left untouched
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        (d / "x.css").write_text("body{color:#fff}", encoding="utf-8")
        html = ('<link rel="stylesheet" href="x.css">'
                '<link rel="stylesheet" href="https://e.com/y.css">')
        out = V.inline_linked(html, d)
        assert '<style data-source="framework">body{color:#fff}</style>' in out
        assert 'href="https://e.com/y.css"' in out


def test_check_only_runs_full_audit_registry():
    """F-08: check-only runs the SAME static audit set as validate.py — both
    iterate V.STATIC_AUDITS, so they can't diverge (check-only used to silently
    skip 6 audits)."""
    assert len(V.STATIC_AUDITS) >= 31
    fns = {fn.__name__ for fn, _ in V.STATIC_AUDITS}
    for name in ('audit_lift_style_lost', 'audit_undefined_css_vars',
                 'audit_bullet_dash', 'audit_empty_header_zone',
                 'audit_list_echo', 'audit_visual_richness'):
        assert name in fns  # the 6 that check-only historically skipped
    src = (ASSETS / "check-only.py").read_text(encoding="utf-8")
    assert "run_static_audits(V.STATIC_AUDITS" in src  # dispatches via registry


def test_families_cover_newly_surfaced_codes():
    """The previously-skipped audits' codes must be categorized in FAMILIES so
    check-only's review groups them instead of dumping to '未分类'."""
    fam_codes = {c for _, codes in CO.FAMILIES for c in codes}
    for code in ('R-ECHO', 'R-BULLET-DASH', 'R-CSSVAR',
                 'R-EMPTY-HEADER-ZONE', 'R-VIS-LIFT-STYLE-LOST'):
        assert code in fam_codes, f"{code} not categorized in FAMILIES"


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
