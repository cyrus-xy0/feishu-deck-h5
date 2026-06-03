# manifest.json schema (input to build.py)

All coordinates are **px on a 1920×1080 design canvas**; build.py converts them
to `cqw`/`cqh` so the deck scales purely in CSS (container queries).

```jsonc
{
  "title": "我的演示",
  "fontBase": "https://host/deck/font",      // optional; omit for system-font fallback
  "fonts": { "regular": "reg.woff2", "bold": "bold.woff2" },  // optional
  "slides": [
    {
      "bg":       "https://host/deck/bg/page-001.jpg",      // WITH text — shown in view mode
      "bgNotext": "https://host/deck/notext/page-001.jpg",  // NO text — shown in edit + 翻译(xl) mode + as dirty-mask
      "dimothers": false,    // optional; true = 金句压暗: dim every text box on this slide EXCEPT the .over one(s)
      "texts": [
        {
          "left": 124, "top": 376, "width": 934, "height": 356,
          "insets": [l, r, t, b],          // px padding inside the box (from PPT bodyPr)
          "anchor": "MIDDLE",              // vertical: TOP|MIDDLE|BOTTOM (PPT vertical_anchor)
          "over": false,                   // optional; on a dimothers slide, this box stays bright (the 金句)
          "paras": [
            { "text": "标题", "size": 96, "color": "#6EAAFF",
              "bold": true, "align": "CENTER", "spc_before": null },
            { "text": "副标题", "size": 36, "color": null, "bold": false,
              "align": "CENTER", "spc_before": 12 }
          ]
        }
      ],
      "media": [
        { "url": "https://host/deck/media/v1.mp4",
          "left": 1295, "top": 440, "width": 549, "height": 411,
          "gif": false,        // true = autoplay muted loop (no audio); false = click-to-play video
          "clip": null,        // optional CSS clip-path to carve out overlapping foreground
          "round": false,      // optional rounded corners
          "muted": false }     // for non-first video on a slide, mute to avoid audio overlap
      ]
    }
  ]
}
```

- `texts` comes straight from `extract.py` (texts.json[slide]).
- `bg`/`bgNotext` are assembled by `make_manifest.py` from `--img-base` + patterns.
  Point the patterns at hi-res JPEGs (re-rasterized at width 2880/3840) to fix
  blurry photos — see `references/image-quality.md`. `bgNotext` must stay the same
  pixel size as `bg` so the dirty-mask crop lines up.
- `media` is optional; from `extract_media.py` after uploading + url-rewrite.
- A text frame with `size:null` falls back to the previous paragraph's size; use
  `extract.py --fill-sizes` to fill master-inherited title sizes. `color:null`
  renders white → invisible on light backgrounds; recover it with
  `scripts/recover_colors.py` (see `references/image-quality.md`).
- `dimothers` (slide) + `over` (box) drive 金句压暗; set them with
  `make_manifest.py --dim 'PAGE:BOXIDX'` or by hand.
- A separate **i18n map** (`{sourceText:{h,e,j}}`, NOT part of this manifest) is
  passed to `build.py --i18n` for the in-deck language switch; generate it with
  `scripts/make_i18n.py`. See `references/translation.md`.
