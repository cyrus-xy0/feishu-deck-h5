"""Rule-coverage contract (UNIFY-VALIDATE-ARCH §coverage, 2026-06-05).

audits.js is ONE shared rules array applied to every slide layout-agnostically.
Coverage is therefore a per-rule property, not an engine property: a rule is
`universal` (name-free, fires on raw + schema) unless it deliberately narrows.

This test makes "covers raw+schema by default" machine-enforced:
  1. every rule in RULES must be declared in RULE_META (no silent rules);
  2. a rule that narrows to coverage schema-only / raw-only / stub MUST carry an
     `optout` justification (a reviewable line) — narrowing pays a visible tax;
  3. RULE_META must not name a rule that no longer exists.

It parses audits.js as text (the file is a browser-injected IIFE, not importable),
so it stays fast and dependency-free.
"""
import re
from pathlib import Path

AUDITS = Path(__file__).resolve().parents[2] / "assets" / "audits.js"
NARROW = {"schema-only", "raw-only", "stub"}


def _load():
    src = AUDITS.read_text(encoding="utf-8")
    # RULES ids: only `id: '...'` entries, which live inside rule objects.
    # NOTE the id char class must include `/` so composite ids like 'L1/L2/L4'
    # are parsed — otherwise the rule silently escapes the coverage contract.
    rules_region = src[src.index("const RULES = ["):]
    rule_ids = re.findall(r"\bid:\s*'([A-Z0-9][\w/-]+)'", rules_region)
    # RULE_META entries: `'<id>': { coverage: '<cov>', ... (optout: '...')? }`
    meta = {}
    for m in re.finditer(
        r"^\s*'([A-Z0-9][\w/-]+)':\s*\{\s*coverage:\s*'([\w-]+)'(.*)$", src, re.M
    ):
        rid, cov, rest = m.group(1), m.group(2), m.group(3)
        meta[rid] = {"coverage": cov, "optout": "optout:" in rest}
    return rule_ids, meta


def test_every_rule_is_declared_in_rule_meta():
    rule_ids, meta = _load()
    assert rule_ids, "no rules parsed — RULES array layout changed?"
    missing = [r for r in rule_ids if r not in meta]
    assert not missing, (
        "rules with no RULE_META coverage declaration (default to 'universal' "
        f"or justify narrowing): {missing}"
    )


def test_narrowed_rules_carry_an_optout_justification():
    rule_ids, meta = _load()
    unjustified = [
        r for r in rule_ids
        if meta.get(r, {}).get("coverage") in NARROW and not meta[r]["optout"]
    ]
    assert not unjustified, (
        "rules narrowed to schema-only/raw-only/stub without an `optout` "
        f"justification (covering raw+schema is the default; narrowing must be "
        f"justified): {unjustified}"
    )


def test_rule_meta_has_no_orphan_entries():
    rule_ids, meta = _load()
    orphans = [r for r in meta if r not in rule_ids]
    assert not orphans, f"RULE_META entries with no matching rule in RULES: {orphans}"


def test_coverage_values_are_valid():
    _, meta = _load()
    valid = {"universal", "schema-only", "raw-only", "partial", "stub"}
    bad = {r: m["coverage"] for r, m in meta.items() if m["coverage"] not in valid}
    assert not bad, f"invalid coverage values: {bad}"


# Dynamic `rule:` emissions in audits.js that are KNOWN-SAFE because they echo an
# already-registered code (so check-only's literal-only scan can't miss a NEW
# code through them). Each is the code's own id / a previously-emitted rule id:
#   · rule: rule.id  — the run() catch block (a rule THREW; reports its own id)
#   · rule: rid      — the PER_RULE_CAP collapse marker (rid = a dropped rule's id)
_KNOWN_DYNAMIC_RULE_EMITS = {"rule.id", "rid"}


def test_no_unregistered_dynamic_rule_emit():
    """contract-3 · check-only.py's enumerate_validate_rules() scans audits.js for
    `rule: '<literal>'` ONLY, so a finding emitted via a NON-literal `rule:` (a
    variable / expression) would escape the coverage registry. Today that's
    latent — the only dynamic emits re-use an already-registered code. This test
    pins that invariant: any NEW non-literal `rule:` whose expression isn't in the
    known-safe allowlist must be reviewed (either make it a literal so the scan
    sees it, or confirm it only ever echoes a registered code and allowlist it)."""
    src = AUDITS.read_text(encoding="utf-8")
    # `rule:` followed by something that is NOT a quoted string literal.
    dynamic = re.findall(r"\brule:\s*(?!['\"])([A-Za-z_][\w.]*)", src)
    unexpected = sorted(set(dynamic) - _KNOWN_DYNAMIC_RULE_EMITS)
    assert not unexpected, (
        "audits.js emits findings via non-literal `rule:` expressions that "
        f"check-only's literal scan can't register: {unexpected}. Make the code a "
        "string literal, or — if it only ever echoes an already-registered rule "
        "id — add it to _KNOWN_DYNAMIC_RULE_EMITS with a justification.")
