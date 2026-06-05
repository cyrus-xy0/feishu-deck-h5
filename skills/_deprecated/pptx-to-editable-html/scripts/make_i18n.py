#!/usr/bin/env python3
"""make_i18n.py — build the translation map that build.py --i18n consumes.

The map is { sourceText: {"h": <zh-Hant>, "e": <English>, "j": <Japanese>} } where
each key is a UNIQUE source paragraph from the deck. build.py tags every matching
.ln with a data-i index and bakes window.__I18N, so the in-deck language switch
(原版 / 繁體 / English / 日本語) works even inside sandboxed iframes — no browser-translate.

Pipeline this fits into:
    extract.py            -> texts.json
    make_manifest.py      -> manifest.json
    make_i18n.py SOURCE   -> i18n.json   (this script: fills h via OpenCC, e/j via FaaS)
    build.py ... --i18n i18n.json -> deck.html with the language switch

SOURCE may be EITHER:
  • a manifest.json (has top-level "slides": [{"texts":[{"paras":[{"text":...}]}]}]), or
  • a texts.json   (extract.py output: { "<slide-no>": [ {"paras":[{"text":...}]} ] }).
In both cases we walk slides -> texts -> paras exactly like build.py and collect every
non-empty paragraph, then DEDUPE by exact text (so repeated lines translate once).

Filling each language field:
  h (zh-Hant) : OpenCC config s2tw if the `opencc` module is importable; else '' + a warning.
  e/j (+more) : POST batches to a translation FaaS (--faas-url) of shape
                  { texts:[...], source:"zh-CN", target:"en" } -> { ok, translations:[...] };
                else left '' for manual fill. See scripts/faas_translate.js.
  --merge     : load an existing i18n.json first and PRESERVE its already-filled, non-empty
                values (only blanks get (re)filled) — lets you hand-correct then re-run.

Usage:
  python3 make_i18n.py manifest.json --out i18n.json
  python3 make_i18n.py texts.json    --out i18n.json --faas-url https://magic.../api/faas/<id>
  python3 make_i18n.py manifest.json --out i18n.json --langs h,e        # zh-Hant + English only
  python3 make_i18n.py manifest.json --out i18n.json --merge i18n.json  # refill blanks, keep edits

Dependencies:
  opencc-python-reimplemented   (optional; only needed to auto-fill h / zh-Hant)
  the FaaS (scripts/faas_translate.js, deployed) is optional; only needed for e/j.
"""
import argparse
import json
import sys
import urllib.request

# Per-language config: field key -> (OpenCC config or None, FaaS target language code).
# h is done locally via OpenCC; e/j (and any extra) go through the FaaS.
LANG_CFG = {
    'h': {'opencc': 's2tw', 'target': None},      # Traditional Chinese (Taiwan variant)
    'e': {'opencc': None,   'target': 'en'},      # English
    'j': {'opencc': None,   'target': 'ja'},      # Japanese
}
SOURCE_LANG = 'zh-CN'   # deck source language; mapped server-side by faas_translate.js
BATCH = 40              # texts per FaaS request


def extract_unique(source_path):
    """Walk a manifest.json OR a texts.json and return the ordered unique source texts."""
    data = json.load(open(source_path, encoding='utf-8'))
    if isinstance(data, dict) and 'slides' in data:
        # manifest.json
        slide_iter = (s.get('texts', []) for s in data['slides'])
    elif isinstance(data, dict):
        # texts.json: { "<slide-no>": [frames...] }, keyed by 1-based slide number.
        slide_iter = (data[k] for k in sorted(data.keys(), key=lambda x: int(x)))
    else:
        sys.exit(f'ERROR: {source_path} is neither a manifest (has "slides") nor a texts.json map')

    uniq, seen = [], set()
    for texts in slide_iter:
        for frame in (texts or []):
            for para in (frame.get('paras') or []):
                txt = (para.get('text') or '')
                if not txt.strip():
                    continue
                if txt not in seen:
                    seen.add(txt)
                    uniq.append(txt)
    return uniq


def fill_opencc(texts, config):
    """Convert each text via OpenCC. Returns (results, ok). If opencc is missing,
    returns ('' for every text, False) so the caller can warn and leave blanks."""
    try:
        import opencc
    except ImportError:
        return ['' for _ in texts], False
    cc = opencc.OpenCC(config)
    return [cc.convert(t) for t in texts], True


def fill_faas(texts, faas_url, target):
    """Translate texts via the FaaS in batches. On ANY error for a batch, that batch's
    texts come back as '' (manual fill). Mirrors faas_translate.js's graceful fallback."""
    out = []
    for i in range(0, len(texts), BATCH):
        chunk = texts[i:i + BATCH]
        payload = json.dumps({'texts': chunk, 'source': SOURCE_LANG, 'target': target}).encode('utf-8')
        req = urllib.request.Request(
            faas_url, data=payload,
            # text/plain keeps it a CORS "simple request" if ever called from a browser;
            # the FaaS parses the raw body either way.
            headers={'Content-Type': 'text/plain;charset=utf-8'}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                resp = json.loads(r.read().decode('utf-8'))
            tr = resp.get('translations') or []
            # If the FaaS echoed source unchanged (ok:false) treat as not-translated -> blank.
            if resp.get('ok') and len(tr) == len(chunk):
                out.extend(tr)
            else:
                out.extend('' for _ in chunk)
                sys.stderr.write(f'  WARN: FaaS batch {i // BATCH} not ok ({resp.get("error")}); left blank\n')
        except Exception as e:
            out.extend('' for _ in chunk)
            sys.stderr.write(f'  WARN: FaaS batch {i // BATCH} failed ({e}); left blank\n')
    return out


def main():
    ap = argparse.ArgumentParser(description='Build the build.py --i18n translation map.')
    ap.add_argument('source', help='manifest.json OR texts.json')
    ap.add_argument('--out', default='i18n.json', help='output map (default i18n.json)')
    ap.add_argument('--faas-url', default=None,
                    help='deployed scripts/faas_translate.js URL; fills e/j. Omit -> leave blank.')
    ap.add_argument('--langs', default='h,e,j',
                    help='comma-separated language fields to fill (default h,e,j)')
    ap.add_argument('--merge', default=None,
                    help='existing i18n.json; preserve its already-filled (non-empty) values')
    a = ap.parse_args()

    langs = [x.strip() for x in a.langs.split(',') if x.strip()]
    unknown = [l for l in langs if l not in LANG_CFG]
    if unknown:
        sys.exit(f'ERROR: unknown lang field(s) {unknown}; known: {list(LANG_CFG)}')

    uniq = extract_unique(a.source)
    print(f'unique source texts: {len(uniq)}')

    prior = {}
    if a.merge:
        try:
            prior = json.load(open(a.merge, encoding='utf-8'))
            print(f'merge: loaded {len(prior)} prior entries from {a.merge}')
        except FileNotFoundError:
            print(f'merge: {a.merge} not found, starting fresh')

    # Seed the map: every field present, '' by default, carry over non-empty prior values.
    result = {}
    for t in uniq:
        rec = {l: '' for l in langs}
        for l, v in (prior.get(t) or {}).items():
            if l in rec and v:
                rec[l] = v
        result[t] = rec

    # For each language, only fill the entries that are still blank (respects --merge).
    for l in langs:
        todo = [t for t in uniq if not result[t][l]]
        if not todo:
            print(f'[{l}] all {len(uniq)} already filled (merge); skipping')
            continue
        cfg = LANG_CFG[l]
        if cfg['opencc']:
            vals, ok = fill_opencc(todo, cfg['opencc'])
            if not ok:
                sys.stderr.write(
                    f'  WARN: [{l}] opencc not installed (pip install opencc-python-reimplemented); '
                    f'left {len(todo)} blank\n')
            else:
                print(f'[{l}] OpenCC({cfg["opencc"]}) filled {len(todo)}')
        elif a.faas_url:
            print(f'[{l}] FaaS translating {len(todo)} text(s) -> {cfg["target"]} ...')
            vals = fill_faas(todo, a.faas_url, cfg['target'])
            print(f'[{l}] FaaS filled {sum(1 for v in vals if v)}/{len(todo)}')
        else:
            vals = ['' for _ in todo]
            print(f'[{l}] no --faas-url; left {len(todo)} blank for manual fill')
        for t, v in zip(todo, vals):
            if v:
                result[t][l] = v

    json.dump(result, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    cov = {l: sum(1 for r in result.values() if r.get(l)) for l in langs}
    print(f'{a.out}: {len(result)} entries  coverage ' +
          '  '.join(f'{l}={cov[l]}/{len(result)}' for l in langs))


if __name__ == '__main__':
    main()
