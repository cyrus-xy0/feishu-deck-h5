# Interactive QR zoom

Use this pattern when a QR code should stay small during the talk but expand to
a scan-friendly overlay on click. It is pure HTML/CSS, so it survives the
DeckJSON render path and Magic Page packaging without injecting slide scripts.

## Integration

1. Copy `references/snippets/qr-zoom.body.html` into the raw slide body and
   `references/snippets/qr-zoom.css` into that slide's `custom_css`.
2. Replace `REPLACE_QR_ID` with a deck-unique ID, `REPLACE_QR_ASSET` with a
   local relative asset, and `REPLACE_SLIDE_KEY` in the CSS with the real key.
3. Keep `.qr-zoom` as a direct child of the slide body. Reposition only
   `.qr-zoom__trigger`; do not overlap the header/title band.
4. Keep `role="button"` on trigger/backdrop/close labels. The deck runtime
   ignores navigation clicks originating from `[role="button"]`.
5. Keep `data-allow-overlap` on the full-canvas overlay wrapper. Do not use it
   to hide unrelated layout collisions.

The component uses an explicit BEM namespace and a unique checkbox ID. Avoid
generic selectors such as `.head > div`: they are easy to break when wrappers
change. Use only local assets; remote QR images make offline delivery fragile.

## Interaction verification

After the normal scoped render, capture both modal states:

```bash
python3 assets/capture-frames.py runs/<deck>/index.html <slide-key> \
  --click-selector '.qr-zoom__trigger' \
  --close-selector '.qr-zoom__close'
```

The command emits `*_clicked.png` and `*_closed.png` in addition to the normal
mid/settled frames, and fails when either selector cannot be clicked. For slow
entrance motion, set `--settle-ms` beyond the longest delay plus duration; the
tool does not guess page-specific animation timing.

Type remains on the `{16, 24, 28, 48}` ladder: 16 px for the compact action and
24 px for scan instructions. The modal image is intentionally large, but its QR
pixels must remain crisp (prefer a lossless PNG and avoid browser blur filters).
