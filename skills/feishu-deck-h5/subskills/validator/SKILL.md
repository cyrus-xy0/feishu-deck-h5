---
name: feishu-deck-h5-validator
description: |
  Subskill for checking and validating feishu-deck-h5 decks. Use for CHECK-ONLY
  review of existing HTML, post-render validation, compliance gates, text/language
  checks, visual audits, and delivery readiness. This subskill reports issues but
  does not redesign or publish.
---

# feishu-deck-h5-validator

## Responsibility

Validate:

- text and language policy
- structure and DOM integrity
- visual overflow, crowding, hierarchy, balance, and typography
- asset/link delivery readiness
- scoped slide changes when the controller locked a limited scope

Inline freshness rule: when this subskill is not running as a separate
multi-agent worker, reread the current upstream files before validating. Do not
rely on cached chat summaries or earlier reads of `index.html`, `deck.json`,
copied assets, validator rules, or business-rule text.

## Modes

### Check-only existing HTML

When the user gives a finished `.html` and asks for review:

```bash
bash skills/feishu-deck-h5/assets/check-only.sh <html>
```

Return the generated business-readable report. Do not recategorize findings by
internal rule family unless the user asks for engineer view.

### Post-render gate

For freshly rendered decks:

```bash
bash skills/feishu-deck-h5/assets/finalize.sh runs/<ts>/output/ local
```

If this fails, route the fix to renderer/editor depending on whether the issue is
in `deck.json` generation or an existing deck edit.

### Scoped edit validation

For a single-slide edit, validation may invoke whole-deck render because the tool
does that internally, but the report must inspect only the locked slide key(s).
Do not surface unrelated stored findings unless the user asked for whole-deck
review.

## Validation Principles

- Validator is a gate, not the designer. It should identify concrete issues and
  route fixes.
- `deck.json` is authoritative. If `index.html` has drift, route to editor's
  round-trip recovery.
- Distinguish blocking errors from advisory reminders.
- For visual issues, include slide number/key and the business impact.
- If validation reports a known symptom but the fix is unclear, load the
  troubleshooting reference before guessing.
- For framework/layout-default changes, `assets/check-distribution.py` is the
  mechanical distribution smoke test before treating a workaround as durable.

## References To Load As Needed

- `../../references/check-only.md`
- `../../references/validator-rules.md`
- `../../references/delivery.md`
- `../../references/round-trip-integrity.md`
- `../../references/operational-notes.md`
- `../../references/troubleshooting.md`
- `../../assets/business-rules.yaml`

Rules are implemented in `../../assets/validate.py` and
`../../assets/_validate_audits.py`; do not maintain a separate rule source.
