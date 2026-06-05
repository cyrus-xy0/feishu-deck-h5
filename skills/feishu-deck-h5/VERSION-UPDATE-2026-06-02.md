# feishu-deck-h5 Version Update — 2026-06-02

## Summary

This update turns `feishu-deck-h5` from a single large controller skill into a
controller plus focused subskills for parsing, design, rendering, editing,
validation, simulation, and publishing. The pipeline is now more explicit about
scope locking, DeckJSON as source of truth, raw-first slide design, validation
before handoff, and optional cloud publishing / library ingestion.

## Highlights

- Added subskills for designer, renderer, validator, editor, parser, simulator,
  and publisher workflows.
- Added parser contracts for source dossiers, local HTML asset materialization,
  Lark media preview handling, target-HTML bootstrap, and image-page decisions.
- Added publisher support for Magic Page / Miaoda-style HTML publishing,
  dry-run reports, and slide-library ingestion manifests.
- Added pitch simulator contracts and scenario-aware rehearsal output.
- Added `locate-slide.py`, `render-deck.py --renumber`, and stronger slide
  addressing rules: page number = frame index = URL hash.
- Strengthened raw-first policy, controller hard gates, scope discipline, and
  validator advisory coverage such as `R-RAW-LOOKS-SCHEMA`.
- Improved lift/import handling, including source-head CSS recovery, asset
  copying, base64 externalization, key collision handling, and HTML-target lift.
- Improved package and delivery scripts so DeckJSON sidecars, slide indexes,
  assets, and lean skill distributions are handled more reliably.

## Test And Review Notes

- Converted top-level tests to stdlib `unittest` so the documented test runner
  discovers them without requiring pytest.
- Verified:
  - `python3 -m unittest discover -s tests -p 'test*.py' -v`
  - `python3 -m unittest discover tests -v` in `deck-json`
  - `python3 -m unittest discover subskills/parser/tests -v`
  - `python3 -m unittest discover subskills/simulator/tests -v`
  - `git diff --check`

## Compatibility Notes

- The branch still intentionally does not merge or rebase `origin/main`; the
  relevant upstream fixes were reviewed and absorbed into the local subskill
  architecture instead.
- Visual strict validation still depends on Playwright being installed in the
  execution environment; static/programmatic validation remains available with
  `--no-visual`.
