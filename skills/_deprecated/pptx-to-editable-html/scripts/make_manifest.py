#!/usr/bin/env python3
"""make_manifest.py — assemble the build.py manifest from texts.json + image
locations (+ optional media). No deck-specific hardcoding: image hosts and file
patterns are CLI args.

  python3 make_manifest.py texts.json --out manifest.json \
      --img-base https://host/deck \
      --bg-pattern  'bg/page-{n:03d}.png' \
      --notext-pattern 'notext/page-{n:03d}.jpg' \
      --title '我的演示' \
      --font-base https://host/deck/font --font-reg reg.woff2 --font-bold bold.woff2 \
      [--media media.json] [--skip 58,60]

  • {n} in patterns is the 1-based slide number.
  • --media media.json: {"3":[{url,left,top,width,height,gif,clip,round,muted}], ...}
    (positions px on 1920×1080). Build overlays these as <video> (gif→autoplay
    loop, else click-to-play). See extract_media.py to generate it.
  • --skip drops pages (1-based) entirely from the deck.
"""
import argparse
import json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('texts')
    ap.add_argument('--out', default='manifest.json')
    ap.add_argument('--img-base', required=True)
    ap.add_argument('--bg-pattern', required=True, help='with-text image path, {n} = slide no.')
    ap.add_argument('--notext-pattern', required=True, help='no-text image path, {n} = slide no.')
    ap.add_argument('--title', default='Deck')
    ap.add_argument('--font-base', default=None)
    ap.add_argument('--font-reg', default=None)
    ap.add_argument('--font-bold', default=None)
    ap.add_argument('--media', default=None)
    ap.add_argument('--skip', default='', help='comma-separated 1-based pages to drop')
    ap.add_argument('--faas', default=None,
                    help='FaaS storage URL for shared, cross-device persistence (edits/order/hidden). '
                         'Deploy scripts/faas_store.js first; see references/backend-persistence.md')
    ap.add_argument('--dim', default='',
                    help="hero/pull-quote 压暗 pages: 'PAGE:BOXIDX[,PAGE:BOXIDX...]' (1-based PAGE = "
                         "texts.json key; BOXIDX 0-based into that page's texts). Marks the slide "
                         "dimothers and the named box(es) over, so the 金句 stays bright while the "
                         "rest of the page's text dims (see build.py .dim-others / .tb-over).")
    a = ap.parse_args()

    texts = json.load(open(a.texts, encoding='utf-8'))
    media = json.load(open(a.media, encoding='utf-8')) if a.media else {}
    skip = {int(x) for x in a.skip.split(',') if x.strip()}
    base = a.img_base.rstrip('/')

    dim = {}  # 1-based page -> {box indices to mark .over}
    for tok in a.dim.split(','):
        tok = tok.strip()
        if not tok:
            continue
        pg, _, bi = tok.partition(':')
        dim.setdefault(int(pg), set()).add(int(bi) if bi.strip() else 0)

    def fmt(pat, n):
        return pat.replace('{n:03d}', f'{n:03d}').replace('{n}', str(n))

    nums = sorted((int(k) for k in texts.keys()))
    slides = []
    for n in nums:
        if n in skip:
            continue
        sl = {
            'bg': f'{base}/{fmt(a.bg_pattern, n)}',
            'bgNotext': f'{base}/{fmt(a.notext_pattern, n)}',
            'texts': texts[str(n)],
            'media': media.get(str(n), []),
        }
        if n in dim:
            sl['dimothers'] = True
            for bi in dim[n]:
                if 0 <= bi < len(sl['texts']):
                    sl['texts'][bi]['over'] = True
        slides.append(sl)

    manifest = {'title': a.title, 'slides': slides}
    if a.faas:
        manifest['faas'] = a.faas
    if a.font_base and (a.font_reg or a.font_bold):
        manifest['fontBase'] = a.font_base.rstrip('/')
        manifest['fonts'] = {}
        if a.font_reg:
            manifest['fonts']['regular'] = a.font_reg
        if a.font_bold:
            manifest['fonts']['bold'] = a.font_bold

    json.dump(manifest, open(a.out, 'w'), ensure_ascii=False, indent=2)
    print(f'{a.out}: {len(slides)} slides (skipped {sorted(skip)})')


if __name__ == '__main__':
    main()
