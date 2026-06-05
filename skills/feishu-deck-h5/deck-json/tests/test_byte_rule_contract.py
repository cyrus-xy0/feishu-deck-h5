"""Byte-rule coverage contract — the BYTE half of the unified rule surface
(UNIFY-VALIDATE-ARCH §coverage, PR3).

The DOM half is RULE_META in audits.js (enforced by test_rule_contract.py).
This file is its mirror for the runner-level source-byte rules: every rule code
the byte functions in run-audits.py emit must be declared in BYTE_RULE_META with
signal 'bytes'. Together the two contracts make EVERY rule — computed-DOM-in-
browser OR source-byte-in-runner — carry an explicit coverage declaration, so
"covers raw + schema by default" is machine-enforced across both physical
engines, not just the DOM one.

Pure text parse (no import side effects), so it stays fast and dependency-free.
"""
import re
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[2] / "assets" / "run-audits.py"


def _src():
    return RUNNER.read_text(encoding="utf-8")


def _emitted_byte_codes(src):
    """Rule codes the runner's byte functions actually emit — same idioms the
    check-only.py rule enumerator scans (`"rule": "X"`, the `DOC = "X"` alias,
    and `warn("Pxx")`)."""
    codes = set()
    codes |= set(re.findall(r'"rule":\s*"([A-Za-z0-9][\w-]*)"', src))
    codes |= set(re.findall(r'\bDOC\s*=\s*"([A-Za-z0-9][\w-]*)"', src))
    codes |= set(re.findall(r'\bwarn\(\s*"([A-Za-z0-9][\w-]*)"', src))
    return codes


def _declared(src):
    """BYTE_RULE_META entries — keyed name → declared signal. The
    `coverage`+`signal` shape is unique to BYTE_RULE_META in this file."""
    return dict(re.findall(
        r'"([A-Za-z0-9][\w-]*)":\s*\{\s*"coverage":\s*"[\w-]+",\s*"signal":\s*"([\w-]+)"',
        src))


def test_every_emitted_byte_rule_is_declared():
    src = _src()
    declared = _declared(src)
    assert declared, "BYTE_RULE_META not found / not parsed in run-audits.py"
    emitted = _emitted_byte_codes(src)
    missing = sorted(emitted - set(declared))
    assert not missing, (
        "byte rules emitted by the runner but not declared in BYTE_RULE_META "
        f"(declare coverage + signal): {missing}"
    )


def test_byte_rules_all_declare_signal_bytes():
    declared = _declared(_src())
    bad = {k: v for k, v in declared.items() if v != "bytes"}
    assert not bad, f"BYTE_RULE_META entries must declare signal 'bytes': {bad}"


def test_no_orphan_byte_meta_entries():
    src = _src()
    emitted = _emitted_byte_codes(src)
    orphans = sorted(set(_declared(src)) - emitted)
    assert not orphans, (
        f"BYTE_RULE_META declares rules the runner never emits: {orphans}"
    )
