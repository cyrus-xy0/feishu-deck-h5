# deck-json/tests · regression tests

Minimal test suite added in P3 (post local-multi-agent review). Catches the
drift bugs the reviewers found:

- `test_validate_examples.py` — every example deck.json validates clean
- `test_render_examples.py` — every example renders + every emitted
  data-text-id reverse-maps via editor.js textIdToSlidePath
- `test_editor_schema_parity.py` — editor.js BLOCK_TYPES / EXTRA_FIELDS /
  ARRAY_FIELDS field names + enums match deck-schema.json $defs
- `test_deck_cli_smoke.py` — CLI subcommands round-trip safely (backup +
  rollback on schema fail)

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
