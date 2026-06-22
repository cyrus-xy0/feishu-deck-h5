#!/usr/bin/env python3
"""check-asset-weight.py — F-366: delivery asset-bloat gate.

Catches the "deck published at 300MB with no video" failure mode by auditing
what a RENDERED deck actually weighs + references. Advisory by default
(warnings, exit 0); `--strict` makes OVERSIZED/HEAVY/EMBED findings exit 11 so a
delivery pipeline can hard-block. Pure stdlib (os/re) — no browser, fast.

Findings (each with the concrete fix the qilu 300MB post-mortem taught us):
  OVERSIZED  a referenced image/media file over SINGLE_MAX — raw uncompressed art
             in a 1920-canvas deck; compress to <=1920px / convert photo PNG->JPG.
  EMBED      a page <iframe>s a whole LOCAL sub-deck whose folder is over EMBED_MAX
             — the "58MB source deck embedded just to show one slide" trap;
             staticize that page to a screenshot for delivery.
  ORPHAN     a large file sitting in the deck's asset dirs that NOTHING references
             — leftover video / font / export; delete it.
  HEAVY      the whole deliverable folder is over DECK_MAX (sum of the above).
"""
from __future__ import annotations
import os, re, sys

SINGLE_MAX = 2 * 1024 * 1024      # 2 MB — a 1920px image/photo almost never needs more
EMBED_MAX  = 5 * 1024 * 1024      # 5 MB — an iframe whose local folder exceeds this is a heavy embed
ORPHAN_MAX = 1 * 1024 * 1024      # 1 MB — flag only chunky orphans
DECK_MAX   = 120 * 1024 * 1024    # 120 MB — a delivered deck folder over this is unreasonable

_MEDIA_EXT = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.avif', '.bmp', '.tiff',
              '.mp4', '.webm', '.mov', '.m4v', '.svg')
# folders that hold deliverable assets (for orphan scan)
_ASSET_DIRS = ('assets', 'input', 'logos', 'media', 'static', 'prototypes')
# files that are NOT part of the delivered weight (dev/meta) — excluded from HEAVY + ORPHAN
_NONDELIVERY = re.compile(r'(\.bak[-.]|\.bak$|\.tmp$|\.orig$|/\.[^/]*\.tmp|'
                          r'\.md$|last-render\.log$|-findings\.json$|deck\.json$|'
                          r'\.slide-hashes\.json$|assets-manifest\.yaml$|'
                          r'outline\.json$|slide-index\.json$)')


def _human(n: int) -> str:
    return f'{n/1048576:.1f}MB' if n >= 1048576 else f'{n/1024:.0f}KB'


def _local_refs(html: str) -> set[str]:
    """Every local (non-http/data) src/href/url() target in the HTML, hash/query stripped."""
    out = set()
    for m in re.finditer(r'(?:src|href)="([^"#?:][^"]*?)"', html):
        out.add(m.group(1).split('#')[0].split('?')[0])
    for m in re.finditer(r'url\((["\']?)([^)"\']+)\1\)', html):
        out.add(m.group(2).split('#')[0].split('?')[0])
    return {r for r in out if r and not r.startswith(('http', 'data:', 'mailto', 'javascript', '//'))}


def _iframe_srcs(html: str) -> list[str]:
    return [m.group(1).split('#')[0].split('?')[0]
            for m in re.finditer(r'<iframe\b[^>]*\bsrc="([^"#?:][^"]*?)"', html)]


def _dir_size(d: str) -> int:
    t = 0
    for r, _, fs in os.walk(d):
        for f in fs:
            try: t += os.path.getsize(os.path.join(r, f))
            except OSError: pass
    return t


def _size(p: str) -> int:
    try: return os.path.getsize(p)
    except OSError: return 0


def audit(deck_dir: str,
          single_max=SINGLE_MAX, embed_max=EMBED_MAX,
          orphan_max=ORPHAN_MAX, deck_max=DECK_MAX) -> dict:
    """Return {oversized, embeds, orphans, deck_bytes, heavy} for a rendered deck dir."""
    deck_dir = os.path.abspath(deck_dir)
    idx = os.path.join(deck_dir, 'index.html')
    html = open(idx, encoding='utf-8').read() if os.path.exists(idx) else ''
    refs = _local_refs(html)
    ref_files = set()
    for r in refs:
        rp = os.path.normpath(os.path.join(deck_dir, r))
        if os.path.isfile(rp):
            ref_files.add(rp)

    # OVERSIZED — referenced media over the single-file ceiling
    oversized = []
    for rp in ref_files:
        if rp.lower().endswith(_MEDIA_EXT):
            s = _size(rp)
            if s > single_max:
                oversized.append((os.path.relpath(rp, deck_dir), s))
    oversized.sort(key=lambda x: -x[1])

    # EMBED — iframe to a local .html whose folder is heavy
    embeds = []
    for src in _iframe_srcs(html):
        if not src.lower().endswith(('.html', '.htm')):
            continue
        fp = os.path.normpath(os.path.join(deck_dir, src))
        d = os.path.dirname(fp)
        if os.path.isdir(d):
            ds = _dir_size(d)
            if ds > embed_max:
                embeds.append((src, ds))
    embeds.sort(key=lambda x: -x[1])

    # ORPHAN — chunky files in asset dirs that nothing references (by basename)
    orphans = []
    for sub in _ASSET_DIRS:
        base = os.path.join(deck_dir, sub)
        if not os.path.isdir(base):
            continue
        for r, _, fs in os.walk(base):
            for f in fs:
                fp = os.path.join(r, f)
                rel = os.path.relpath(fp, deck_dir)
                if _NONDELIVERY.search('/' + rel):
                    continue
                if f in html:                 # basename referenced anywhere → not orphan
                    continue
                s = _size(fp)
                if s > orphan_max:
                    orphans.append((rel, s))
    orphans.sort(key=lambda x: -x[1])

    # HEAVY — total delivered folder weight (excludes dev/meta cruft)
    deck_bytes = 0
    for r, _, fs in os.walk(deck_dir):
        for f in fs:
            fp = os.path.join(r, f)
            if _NONDELIVERY.search('/' + os.path.relpath(fp, deck_dir)):
                continue
            deck_bytes += _size(fp)

    return {'oversized': oversized, 'embeds': embeds, 'orphans': orphans,
            'deck_bytes': deck_bytes, 'heavy': deck_bytes > deck_max,
            'deck_max': deck_max}


def format_report(f: dict, compact=False) -> str:
    """Human advisory lines. compact=True → one-line digest for render-deck."""
    L = []
    ov, em, orf = f['oversized'], f['embeds'], f['orphans']
    if compact:
        bits = []
        if f['heavy']: bits.append(f"deck {_human(f['deck_bytes'])}>上限{_human(f['deck_max'])}")
        if ov:  bits.append(f"{len(ov)} 超大图(最大 {_human(ov[0][1])})")
        if em:  bits.append(f"{len(em)} 页嵌整源deck(最大 {_human(em[0][1])})")
        if orf: bits.append(f"{len(orf)} 孤儿大文件")
        if not bits:
            return ''
        return ("⚠ 资产臃肿 [asset-weight]: " + " · ".join(bits) +
                " — 跑 deck-json/check-asset-weight.py <out> 看明细+修法")
    if f['heavy']:
        L.append(f"⚠ HEAVY  交付文件夹 {_human(f['deck_bytes'])} > 上限 {_human(f['deck_max'])}")
    for rel, s in ov[:12]:
        hint = ("压缩视频(降码率 / 分辨率)" if rel.lower().endswith((".mp4", ".webm", ".mov", ".m4v"))
                else "压到 ≤1920px / 照片转 JPG")
        L.append(f"  OVERSIZED  {_human(s):>8}  {rel}  → {hint}")
    for src, ds in em:
        L.append(f"  EMBED      {_human(ds):>8}  iframe→{src}  → 该页静态化(截图替 iframe)")
    for rel, s in orf[:12]:
        L.append(f"  ORPHAN     {_human(s):>8}  {rel}  → 无人引用,删")
    if not L:
        return "✓ asset weight OK"
    return '\n'.join(L)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="F-366 deck asset-bloat gate")
    ap.add_argument('target', help='rendered deck dir (holding index.html) or the index.html')
    ap.add_argument('--strict', action='store_true',
                    help='exit 11 if OVERSIZED/EMBED/HEAVY findings exist (hard gate)')
    a = ap.parse_args(argv)
    d = a.target
    if d.endswith('.html'):
        d = os.path.dirname(os.path.abspath(d))
    f = audit(d)
    print(format_report(f))
    print(f"\n交付文件夹合计(去 dev/meta): {_human(f['deck_bytes'])}")
    if a.strict and (f['heavy'] or f['oversized'] or f['embeds']):
        return 11
    return 0


if __name__ == '__main__':
    sys.exit(main())
