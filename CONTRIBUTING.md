# Contributing

## Dev workflow

```bash
# 1. Edit CSS / JS / templates / docs
vim assets/feishu-deck.css       # design tokens, layouts, decor, ui-*
vim assets/feishu-deck.js        # runtime
vim assets/validate.py           # validator
vim _body.partial.html           # the demo deck used by build.sh
vim SKILL.md                     # the agent-facing playbook
vim DESIGN.md                    # 9-section design system spec

# 2. Rebuild
bash build.sh --inline           # produces both linked + inlined examples

# 3. Validate (must exit 0 on both modes before committing)
python3 assets/validate.py examples/sample-deck.html
python3 assets/validate.py examples/sample-deck.html --strict
python3 assets/validate.py examples/sample-deck-inline.html
python3 assets/validate.py examples/sample-deck-inline.html --strict
```

If any of the four runs fails, fix the underlying issue. Don't suppress
the validator — every check exists because of a real bug from a previous
deliverable.

---

## Adding a new layout

1. Decide the layout's name (e.g. `data-layout="kpi-pyramid"`).
2. Add CSS rule block in `feishu-deck.css` under the matching layout
   section. Use one of the canonical inner-container names
   (`.stage` preferred, or `.grid / .flow / .nodes / .stack` per
   convention).
3. Add a recipe to `templates/slide-recipes.html` and `_body.partial.html`.
4. If the layout is "fixed shape" (content has natural height shorter
   than canvas), add it to `check_default_centering`'s `centerable`
   tuple AND ensure your CSS includes `align-content: center` /
   `place-content: center` on the container.
5. Add a recipe block to `SKILL.md` "Available layouts" + the layouts
   table.
6. Run `bash build.sh --inline && python3 assets/validate.py
   examples/sample-deck.html --strict`. Fix anything that fails.

---

## Adding a new `data-decor` token

1. Add a CSS rule `.slide[data-decor~="<name>"]::before { ... }` in the
   "ATMOSPHERIC DECORATION" section of `feishu-deck.css`.
2. Add the token to the `ALLOWED_DECOR` set in `assets/validate.py`.
3. Document it in SKILL.md's "Available decor tokens" table.
4. Validate.

---

## Adding a new `data-variant`

1. Add a CSS rule `.slide[data-layout="X"][data-variant="Y"] .grid {
   ... }`.
2. **Redeclare every structural property** — `display`, `flex-direction`,
   `align-items`, `justify-content`, `flex-wrap`, `grid-template-*`.
   The variant discipline rule (R47) catches missing redeclarations,
   but it's better to do it right the first time.
3. Document any new variant in SKILL.md.
4. Validate.

---

## Adding a new validator check

1. Write `def audit_<thing>(slides_or_html, iss, *):` in
   `assets/validate.py`.
2. Wire into `main()` between the existing audit calls.
3. Pick a rule code: `R##` for规范, `L#` for layout integrity, `P##` for
   perf, `UI#` for UI mock rules. Don't reuse codes.
4. Add a corresponding self-check item in `SKILL.md` numbered list.
5. Add a self-test (inject a violation, confirm the audit fires) — see
   the existing self-tests in `validate.py` REPL examples.
6. Validate the existing samples still pass.

---

## CI

`.github/workflows/validate.yml` runs `bash build.sh --inline` then
validates both `examples/sample-deck.html` and
`examples/sample-deck-inline.html` in default and `--strict` modes.

A green CI is required for merge. PRs that drop a规范 are auto-rejected.

---

## Brand asset hygiene

The `assets/lark-*.png` and `assets/lark-*.jpg` files are extracted from
the official 飞书 PowerPoint master and are property of ByteDance / 飞书
Technologies. They are NOT covered by this repo's MIT license.

- This repo is **private** for that reason. Do not flip it to public
  without first removing the brand assets and updating `.gitignore` to
  exclude them.
- If you need to share generated decks publicly, regenerate them from
  the inlined version (`sample-deck-inline.html`) which has the assets
  baked into base64 — recipients don't need access to the raw files.

---

## Style

- Code comments in English (English is the lingua franca; translate to
  ZH in user-facing strings only).
- Documentation in 中英 mix is fine — match the existing tone.
- Emoji in code comments → no.
- "TODO:" comments → only with a date and your initials, e.g.
  `// TODO: 2026-04 fq · refactor when …`.
