#!/usr/bin/env python3
"""run-regression.py — execute the regression fixture suite.

Reads regression-fixtures.yaml, runs validate.py --visual on each unique
deck, parses output for the expected audit + slide, asserts must_fire /
must_not_fire per fixture, prints pass/fail, exits with the failure count.

Use case:
  1. After ANY audit rule edit in validate.py — re-run to verify the rule
     still catches the historical user-complaint cases AND doesn't
     regress on previously-fixed cases.
  2. Periodic CI / pre-push check.

Why this script (vs pytest):
  - Stdlib + PyYAML only; no test framework dependency
  - Cache-aware: runs validate.py at most ONCE per deck (fixtures often
    share the same source deck — pytest would re-run per-test)
  - Per-fixture deterministic output (deck + audit + slide + verdict)
    that's diffable for "what changed since last run"

Usage:
  python3 skills/feishu-deck-h5/tests/run-regression.py
  python3 skills/feishu-deck-h5/tests/run-regression.py --fixtures custom.yaml
  python3 skills/feishu-deck-h5/tests/run-regression.py --verbose
"""

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:
    print('FATAL: PyYAML required. `pip install pyyaml`', file=sys.stderr)
    sys.exit(2)


# Repo root = three levels up from this file (tests/ → assets/.. → skill → skills/ → repo).
# Actually: tests/ is at <repo>/skills/feishu-deck-h5/tests/. Two ups: skill, skills.
SKILL_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_ROOT.parent.parent
VALIDATOR = SKILL_ROOT / 'assets' / 'validate.py'
DEFAULT_FIXTURES = SKILL_ROOT / 'tests' / 'regression-fixtures.yaml'


def load_fixtures(path: Path) -> list:
    with path.open() as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict) or 'fixtures' not in data:
        raise SystemExit(f'FATAL: {path} missing top-level `fixtures:` key.')
    return data['fixtures']


def run_validator(deck: Path) -> dict:
    """Run validate.py --visual --json on the deck; return parsed JSON payload.

    Timeout 420s — handles 50-slide decks comfortably.

    Uses --json since 2026-05-24 (previously regex-parsed human-readable
    stdout, which silently broke whenever the output format was tweaked).
    """
    if not deck.exists():
        raise FileNotFoundError(f'deck not found: {deck}')
    proc = subprocess.run(
        ['python3', str(VALIDATOR), str(deck), '--visual', '--json'],
        capture_output=True, text=True, timeout=420,
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        # Surface the first non-JSON line — usually a Python traceback
        first_line = next((l for l in proc.stdout.split('\n') if l.strip()), '')
        raise SystemExit(
            f'FATAL: validator --json did not return JSON for {deck}\n'
            f'  first stdout line: {first_line[:120]}\n'
            f'  stderr (tail):     {proc.stderr[-300:].strip()}\n'
            f'  parse error:       {e}'
        )


def parse_audit_hits(payload: dict) -> dict:
    """Return { (rule_code, slide_idx): [issue_dict, ...] } from JSON payload.

    Each issue_dict has keys: code, severity, msg, slide, selector_hint.
    Errors and warnings are merged — the fixture's audit-code lookup
    doesn't care about severity (an audit that fires as 'warn' still
    proves coverage).
    """
    hits = defaultdict(list)
    for item in payload.get('errors', []) + payload.get('warnings', []):
        code = item.get('code')
        slide = item.get('slide')
        if code is None or slide is None:
            continue
        hits[(code, int(slide))].append(item)
    return hits


def evaluate_fixture(fixture: dict, hits: dict) -> tuple:
    """Return (passed: bool, reason: str)."""
    rule = fixture['audit']
    slide = int(fixture['slide'])
    typ = fixture['type']
    hint = fixture.get('selector_hint', '')

    matches = hits.get((rule, slide), [])
    if hint:
        # Match against selector_hint OR raw message (some audits put
        # the discriminating substring in msg body, not the backtick token)
        matches = [
            m for m in matches
            if (m.get('selector_hint') and hint in m['selector_hint'])
            or hint in m.get('msg', '')
        ]

    def _sample(m):
        body = m.get('msg', '')[:120]
        return f'[{m.get("code")}] {body}' + ('...' if len(m.get('msg', '')) > 120 else '')

    if typ == 'must_fire':
        if matches:
            return True, f'{len(matches)} hit(s); sample: {_sample(matches[0])}'
        return False, (
            f'expected {rule} to fire on slide {slide}'
            + (f' with selector containing `{hint}`' if hint else '')
            + ' — got 0 matching hits'
        )
    if typ == 'must_not_fire':
        if not matches:
            return True, f'no {rule} hits on slide {slide} (as expected)'
        return False, (
            f'expected {rule} to NOT fire on slide {slide}'
            + (f' with selector containing `{hint}`' if hint else '')
            + f' — got {len(matches)} hit(s); sample: {_sample(matches[0])}'
        )
    return False, f'unknown fixture type `{typ}` (must_fire | must_not_fire)'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--fixtures', '-f', type=Path, default=DEFAULT_FIXTURES,
                    help='path to fixtures yaml (default: tests/regression-fixtures.yaml)')
    ap.add_argument('--verbose', '-v', action='store_true',
                    help='print sample audit line on every fixture (not just failures)')
    args = ap.parse_args()

    fixtures = load_fixtures(args.fixtures)
    print(f'Loaded {len(fixtures)} fixtures from {args.fixtures.relative_to(REPO_ROOT)}')
    print()

    # Group fixtures by deck to avoid re-running validate.py per fixture.
    by_deck = defaultdict(list)
    for fx in fixtures:
        by_deck[fx['deck']].append(fx)

    pass_count = 0
    fail_count = 0
    for deck_rel, deck_fixtures in by_deck.items():
        deck_path = REPO_ROOT / deck_rel
        print(f'== {deck_rel}  ({len(deck_fixtures)} fixtures) ==')
        try:
            payload = run_validator(deck_path)
        except FileNotFoundError as e:
            print(f'  ✗ DECK MISSING — {e}')
            fail_count += len(deck_fixtures)
            continue
        except subprocess.TimeoutExpired:
            print('  ✗ VALIDATOR TIMEOUT (>420s) — visual audit likely stuck')
            fail_count += len(deck_fixtures)
            continue
        hits = parse_audit_hits(payload)
        for fx in deck_fixtures:
            ok, reason = evaluate_fixture(fx, hits)
            mark = '✓' if ok else '✗'
            print(f'  {mark} [{fx["audit"]}] {fx["id"]}')
            if not ok or args.verbose:
                print(f'      → {reason}')
            if ok:
                pass_count += 1
            else:
                fail_count += 1
        print()

    print(f'TOTAL: {pass_count} pass · {fail_count} fail')
    sys.exit(fail_count)


if __name__ == '__main__':
    main()
