# troubleshooting — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:渲染坏了但 validator 没指出时:症状→修

## Failure modes & fixes

| Symptom                                | Likely cause                                         | Fix |
|----------------------------------------|------------------------------------------------------|---|
| Slide displays at top-left, tiny       | Forgot to wrap `.slide` in `.slide-frame`            | Add the wrapper. |
| Indicator + toggle don't appear        | Missing `<script src="assets/feishu-deck.js">`       | Add it (or inline). |
| Mobile shows huge whitespace           | Viewport meta tag missing                            | Add `<meta name="viewport" ...>`. |
| Title overflows past edge              | Content too long for 1920 px canvas                  | Cut content. Don't shrink type below 24 px. |
| Card heights misaligned                | Card content imbalanced                              | Add a 1-line `<br>` to short titles. Cards are min-height:400. |
| Stats column rule on first column      | Default CSS leaks                                    | First column has `border-left:0` already — check overrides. |
| Two accents on one slide               | Forgot to set `data-accent` on slide level           | Set `data-accent="teal"` on the `.slide` element only. |
| Quote glow too strong                  | Custom background overrides `--fs-grad-glow-blue`    | Don't override `.slide[data-layout="quote"]` background. |
| `lift-slides.py` dies `FileNotFoundError` writing DEST (doubled `skills/feishu-deck-h5/runs/...`) | RELATIVE dst resolved against the symlinked skill root, not where `new-run.sh` made the run | Pass the ABSOLUTE run path `new-run.sh` printed for src, DEST `deck.json`, and OUTPUT_DIR. (Tool now fails fast with this hint before parsing the source.) |
| Lifted slide: many `R-VIS-DEAD-RULE` errors, layout collapsed to vertical | `--shake` recovered the source's per-key head CSS, which included shared-stylesheet cruft targeting elements absent on this slide | Confirm it's source cruft (grep source for key+selector), then prune only rules whose leaf selector matches no body element; keep the framework layout block. |
| Render says `PASS / errors 0` yet a card's text visibly spills past its box / over the bottom strap (esp. `raw` + `lifted` slides) | Default gate is `--no-visual` (static only); Playwright geometry audits ran as a NON-BLOCKING advisory (F-253). The card box had grown via `min-height` / legacy `align-self:stretch` so `scrollHeight≈clientHeight` (no *card*-level overflow) while the box itself overflowed its `.grid` and the **centered** content overlapped the sibling strap. `R-OVERLAP` only compares same-container direct children, so a cross-container spill is invisible to it. | **Fixed 2026-06-06**: `render-deck.py` now PROMOTES the HARD geometry errors (`R-VIS-CARD-OVERFLOW` / `R-OVERLAP` / `R-OVERFLOW` / `R-VIS-BAND-COLLIDE`) out of the advisory into a BLOCKING gate on full `/runs/` renders (override `DECK_ALLOW_GEOM_OVERFLOW=1`). When you scope-render / `--quick` / override, **measure the right thing**: container `el.scrollHeight > clientHeight` AND last content child `.bottom` vs the next sibling's `.top` — NOT just the card's bounding box (which `min-height` can inflate to hide the spill). |

---

