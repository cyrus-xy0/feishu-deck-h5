# operational-notes — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:拷 shell / 嵌入 / 相对路径 edge

## Operational notes (gotchas)

- **`templates/_shell.html` uses `../assets/feishu-deck.css`.** It assumes the
  shell stays one directory deep relative to `assets/`. If you `cp` it to a
  new working directory, fix the relative paths to point at the actual
  `assets/` location, or run `bash build.sh` from the skill root which
  handles the rewrite automatically.
- **`data-decor="flower-bg"` and `"photo-bg"` use `!important` to override
  layout backgrounds.** They REPLACE the layout's default background image —
  intentional, so you can carry the cover atmosphere onto a content page.
  The auto-darkening protection gradient is added on non-cover/non-end
  layouts only (cover and end have their own contrast strategies).
- **CSS rule `.deck[data-mode="scroll"] ~ .deck-ui` relies on `.deck-ui`
  being a later sibling of `.deck`.** `feishu-deck.js` always appends the
  UI to `document.body` so this holds, but if you wrap `.deck` in a parent
  container or insert nodes between `.deck` and `.deck-ui`, the sibling
  selector breaks. The JS belt-and-suspenders `display: none` keeps it
  working in practice — but if you embed the deck inside a custom shell,
  prefer toggling `body.is-scroll` instead.

---

