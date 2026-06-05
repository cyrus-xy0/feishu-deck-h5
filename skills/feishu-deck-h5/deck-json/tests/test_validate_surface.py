"""F-10 safety net: validate.py's public surface (the names check-only,
render-deck, and the test suite reference as V.X — the engine adapter
(run_unified_audits / engine_findings_to_issues), the Issues class,
extract_slides, inline_linked, filter_issues_to_slide, the kernel constants /
regex helpers re-exported from _validate_common) MUST stay stable. If a refactor
drops or renames a public symbol, this fails loudly.

UNIFY-VALIDATE-ARCH step 4b: the snapshot was DELIBERATELY regenerated when the
old audit registry (the audit_* functions, STATIC_AUDITS / run_static_audits /
run_visual_audits / _visual_audit_js, the check_* layout predicates, the perf
constants) was retired — those rules now live in the unified engine and are no
longer part of validate.py's surface. The snapshot in _validate_surface.json is
the contract; regenerate it deliberately only when intentionally changing the
public surface.
"""
import json
import sys
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parents[2] / "assets"
sys.path.insert(0, str(ASSETS))
import validate as V  # noqa: E402

SNAPSHOT = set(json.loads(
    (pathlib.Path(__file__).resolve().parent / "_validate_surface.json").read_text(encoding="utf-8")))


def test_public_surface_preserved():
    current = {n for n in dir(V) if not n.startswith('__')}
    missing = sorted(SNAPSHOT - current)
    assert not missing, f"validate.py lost public symbols across the split: {missing}"


if __name__ == "__main__":
    test_public_surface_preserved()
    print("ok")
