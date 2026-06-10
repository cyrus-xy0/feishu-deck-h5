"""F-285 (importer half) · the ingest quality gate must KEEP the cross-page
consistency rules.

`check-only.py --gate ingest` only blocks on rule codes present in
`business-rules.yaml` (its keep-filter: ``kept = [(c,m) for c,m in errors if c
in rules]``). The cross-page rules R-DECK-TITLE-DRIFT / R-DECK-PALETTE-DRIFT /
R-DECK-TYPESCALE-BUDGET (added to audits.js) would silently fall out of the gate
unless they also have business-rules.yaml entries. This guards that wiring so a
future edit can't quietly drop deck-level consistency from the ingest door.

It also confirms there is no F-18 drift (a yaml code the validator no longer
emits) introduced by those additions.
"""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK_ONLY = ROOT / "assets/check-only.py"

CROSS_PAGE = ("R-DECK-TITLE-DRIFT", "R-DECK-PALETTE-DRIFT", "R-DECK-TYPESCALE-BUDGET")


def _load_check_only():
    spec = importlib.util.spec_from_file_location("check_only_under_test", CHECK_ONLY)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_cross_page_rules_are_kept_by_ingest_gate():
    m = _load_check_only()
    rules = m.load_business_rules()       # the gate's keep-set
    for code in CROSS_PAGE:
        assert code in rules, (
            f"{code} is not in business-rules.yaml; the ingest gate "
            f"(check-only.py --gate ingest) would silently drop it"
        )


def test_cross_page_rules_are_emitted_by_validator():
    m = _load_check_only()
    emitted = m.enumerate_validate_rules()
    if not emitted:
        # validator source could not be scanned in this environment — skip rather
        # than assert on an empty set (mirrors warn_on_gate_rule_drift's guard).
        import pytest
        pytest.skip("validator rule codes could not be enumerated")
    for code in CROSS_PAGE:
        assert code in emitted, f"{code} is no longer emitted by the validator"


def test_no_orphaned_gate_rules_after_cross_page_addition():
    m = _load_check_only()
    emitted = m.enumerate_validate_rules()
    if not emitted:
        import pytest
        pytest.skip("validator rule codes could not be enumerated")
    rules = m.load_business_rules()
    orphaned = sorted(set(rules) - emitted)
    assert orphaned == [], (
        f"business-rules.yaml lists codes the validator no longer emits "
        f"(F-18 drift): {orphaned}"
    )
