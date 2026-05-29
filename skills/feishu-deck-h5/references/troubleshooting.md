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

---

