# deck-json/tests · regression tests

Minimal test suite added in P3 (post local-multi-agent review). Catches the
drift bugs the reviewers found:

- `test_validate_examples.py` — every example deck.json validates clean
- `test_render_deck_golden.py` — example decks render to a stable golden snapshot
- `test_deck_cli_smoke.py` — CLI subcommands round-trip safely (backup +
  rollback on schema fail)
- plus the broader `test_validate_*` / `test_vis_*` / `test_lift_slides` /
  `test_css_utils` / `test_check_only_gate` suites

(Historical note: `test_render_examples.py` and `test_editor_schema_parity.py`
were removed alongside the `data-text-id` editor sidecar — don't reference them.)

## Running

```bash
cd skills/feishu-deck-h5/deck-json/
python3 -m unittest discover tests/ -v
```

Or single file:

```bash
python3 -m unittest tests.test_editor_schema_parity -v
```

## Adding tests

stdlib only — no pytest, no fixtures, no plugins. If you need a fixture,
create it inline in setUp() and clean up in tearDown().
