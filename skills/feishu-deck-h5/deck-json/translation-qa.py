#!/usr/bin/env python3
"""translation-qa.py — translation/localization-specific QA for the translator
subskill. Three independent gates (the validator handles generic structure/visual;
this handles the failure modes unique to translating a deck):

  residual-cjk <file...>     Pure-text (no browser): report CJK still left in
                             VISIBLE positions (text nodes / translatable attrs /
                             CSS content:) — a translation miss. Ignores comments,
                             asset paths, font-family names, CSS class selectors.

  parity <src.html> <roundtrip.html>
                             Decide BRANCH A vs B for a legacy deck: compare a
                             backfilled-deck render against the source render
                             (CSS-char ratio, per-slide-key selector ratio, slide
                             count). PASS → the deck round-trips cleanly, use the
                             deck.json branch (A). FAIL → backfill is lossy (heavy
                             merged/head CSS), translate in place on index.html (B).

  overflow <src.html> <tgt.html>
                             Render both at 1920x1080 and report NEW overflow
                             (clipping/spill) the translation introduced that the
                             source did not have (target text is longer than CJK).

Exit: 0 pass / 1 findings / 2 usage. parity also prints BRANCH=A|B on the last line.
"""
import sys, os, re, json, argparse

# real CJK ideographs — the HARD gate (an untranslated word).
IDEO = re.compile(r'[㐀-䶿一-鿿豈-﫿]')
# typography RESIDUE (soft note): fullwidth ASCII/signs (／ ＋ （） ％ ：), CJK
# punctuation & ideographic space (。、「」《》　 U+3000-303F).
FW = re.compile(r'[！-｠￠-￦　-〿]')
CJK = IDEO  # parity/overflow only care about ideographs


# ---------------------------------------------------------------- residual-cjk
def _mask_nonvisible(l: str) -> str:
    """Blank out the BODIES of non-visible tokens on a line (keeping length / the
    rest of the line) so residual-cjk scans only user-visible text. Replaces:
      · href/src/data-* URL attribute VALUES (incl. file:// asset paths)
      · url(...) CSS bodies
      · font-family declarations
      · a trailing `// ...` line-comment segment (and full `//`-only lines)
    H5: this is per-TOKEN masking, NOT a whole-line skip — visible Chinese sharing
    a line with a https:// link or inline font-family is still caught."""
    s = l
    # attribute values that hold non-visible refs (src, href, and data-*-src/url/href)
    s = re.sub(r'\b(?:src|href|srcset|data-[\w-]*(?:src|url|href|path))\s*=\s*'
               r'(["\'])(.*?)\1', r'\1\1', s, flags=re.I)
    # CSS url(...) bodies
    s = re.sub(r'url\(\s*(["\']?)(.*?)\1\s*\)', r'url()', s, flags=re.I)
    # font-family declaration value (up to ; or } or end of line)
    s = re.sub(r'font-family\s*:[^;}\n]*', 'font-family:', s, flags=re.I)
    # trailing `// ...` line comment (require whitespace or line-start before //,
    # so `https://` is NOT treated as a comment — its value was already masked above
    # when it sat in an attribute; a bare https:// in visible text stays scanned)
    s = re.sub(r'(^|\s)//.*$', r'\1', s)
    return s


def cmd_residual(args):
    bad = 0
    # blank out block-comment BODIES (multi-line /* */ and <!-- -->) while keeping
    # newlines, so line numbers stay accurate and interior comment lines (a common
    # false-positive: Chinese CSS comments) don't trip the scan.
    blank = lambda m: re.sub(r'[^\n]', ' ', m.group(0))
    for path in args.files:
        if not os.path.isfile(path):
            print(f"  (skip, not found: {path})"); continue
        text = open(path, encoding="utf-8").read()
        text = re.sub(r'<!--.*?-->', blank, text, flags=re.S)
        text = re.sub(r'/\*.*?\*/', blank, text, flags=re.S)
        # Blank <script>...</script> BODIES (keep newlines for line numbers): CJK
        # inside a <script> is non-translatable by design — extract-text-pairs'
        # RunExtractor skips script content, and the renderer embeds Chinese speaker
        # notes verbatim in <script type="application/json" id="fs-deck-notes">. Those
        # are never swapped by the text-pairs pipeline, so flagging them as HARD
        # untranslated Chinese here is an unactionable false positive (misc-3).
        text = re.sub(r'(<script\b[^>]*>)(.*?)(</script>)',
                      lambda m: m.group(1) + re.sub(r'[^\n]', ' ', m.group(2)) + m.group(3),
                      text, flags=re.S | re.I)
        suspects, fw = [], []
        for i, l in enumerate(text.split("\n"), 1):
            has_ideo, has_fw = IDEO.search(l), FW.search(l)
            if not (has_ideo or has_fw):
                continue
            # H5: do NOT skip the whole line when a non-visible token is present —
            # a line can carry BOTH a https:// link / inline font-family AND visible
            # untranslated Chinese. Blank out only the non-visible token BODIES, then
            # re-scan what remains. (Old code did `continue` and reported such lines
            # CLEAN, hiding real misses.)
            scan = _mask_nonvisible(l)
            if re.search(r'[.#][\w-]*[㐀-䶿一-鿿]', scan):     # css selector token .k-角色
                scan = re.sub(r'[.#][\w-]*[㐀-䶿一-鿿][\w㐀-䶿一-鿿-]*', ' ', scan)
            if re.search(r'class="[^"]*[㐀-䶿一-鿿]', scan):    # load-bearing CJK class hook
                scan = re.sub(r'class="[^"]*"', ' ', scan)
            has_ideo, has_fw = IDEO.search(scan), FW.search(scan)
            if not (has_ideo or has_fw):
                continue
            if has_ideo:
                suspects.append((i, l.strip()[:90]))
            elif has_fw:
                fw.append((i, l.strip()[:90]))
        if suspects:
            bad += len(suspects)
            print(f"⚠️  {path}: {len(suspects)} line(s) with untranslated Chinese (HARD):")
            for ln, txt in suspects[:15]:
                print(f"     {ln}: {txt}")
        else:
            print(f"✅ {path}: no untranslated Chinese")
        if fw:
            note = "FAIL" if args.strict_fullwidth else "note"
            if args.strict_fullwidth:
                bad += len(fw)
            print(f"   ({note}) {len(fw)} line(s) with fullwidth punctuation residue (／ ＋ （） %…) — ASCII-ize for polish")
            for ln, txt in fw[:8]:
                print(f"     {ln}: {txt}")
    print(f"\n{'CLEAN ✅' if bad == 0 else f'{bad} hard finding(s) — inspect'}")
    return 1 if bad else 0


# ---------------------------------------------------------------------- parity
def _css_stats(html):
    styles = re.findall(r'<style[^>]*>(.*?)</style>', html, re.S)
    css = sum(len(s) for s in styles)
    sel = len(re.findall(r'\.slide\[data-slide-key=', html))
    frames = len(re.findall(r'class="slide-frame"', html))
    return css, sel, frames


def cmd_parity(args):
    src = open(args.source, encoding="utf-8").read()
    rt = open(args.roundtrip, encoding="utf-8").read()
    c0, s0, f0 = _css_stats(src)
    c1, s1, f1 = _css_stats(rt)
    css_ratio = (c1 / c0) if c0 else 1.0
    thr = args.css_threshold
    # M6: when the SOURCE has zero per-slide selectors (s0==0) the selector
    # criterion is DISABLED — do NOT silently default sel_ratio=1.0 (that always
    # passed it, collapsing the A/B decision onto css_ratio+frames without saying
    # so). Drop the selector criterion EXPLICITLY and warn.
    if s0:
        sel_ratio = s1 / s0
        sel_ok = sel_ratio >= thr
        sel_disabled = False
    else:
        sel_ratio = None
        sel_ok = True            # cannot evaluate → don't block, but be loud
        sel_disabled = True
    # A frameless render proves NOTHING — an empty/failed roundtrip (f1==0) or a
    # frameless source (f0==0) would otherwise sail through (f0==f1, and css_ratio
    # defaults to 1.0 when c0==0), falsely reporting BRANCH A "round-trips cleanly".
    # Require at least one frame on BOTH sides before a PASS can be granted.
    frames_real = f0 > 0 and f1 > 0
    ok = css_ratio >= thr and sel_ok and f0 == f1 and frames_real
    print(f"source   : css={c0} chars | slide-key selectors={s0} | frames={f0}")
    print(f"roundtrip: css={c1} chars | slide-key selectors={s1} | frames={f1}")
    if not frames_real:
        print("⚠️  empty/frameless render (source frames={} roundtrip frames={}) — "
              "cannot certify a clean round-trip; forcing BRANCH B.".format(f0, f1))
    if sel_disabled:
        print("⚠️  per-slide selectors NOT found in source (s0=0) — selector criterion "
              "DISABLED; deciding on css_ratio + frames only (broaden the selector "
              "regex if your decks use a different per-slide hook).")
        print(f"ratios   : css={css_ratio:.2f} selectors=n/a (threshold {thr}) | frames match={f0==f1}")
    else:
        print(f"ratios   : css={css_ratio:.2f} selectors={sel_ratio:.2f} (threshold {thr}) | frames match={f0==f1}")
    branch = "A" if ok else "B"
    if ok:
        print("PASS ✅ — deck.json round-trips cleanly. Use BRANCH A (deck.json).")
    else:
        print("FAIL ❌ — backfill is LOSSY (bespoke/head CSS not captured). Use BRANCH B")
        print("         (translate in place on index.html; do NOT re-render from deck.json).")
    print(f"BRANCH={branch}")
    return 0 if ok else 1


# -------------------------------------------------------------------- overflow
MEASURE = r"""
() => {
  const fr=document.querySelector('.slide-frame.is-current'); if(!fr)return{key:null,hits:[]};
  const sl=fr.querySelector('.slide'); const key=sl?(sl.dataset.slideKey||sl.id||'?'):'?';
  const sr=sl.getBoundingClientRect(); const hits=[]; const t=el=>(el.textContent||'').trim().replace(/\s+/g,' ').slice(0,46);
  sl.querySelectorAll('*').forEach(el=>{const cs=getComputedStyle(el); if(cs.display==='none'||cs.visibility==='hidden')return;
    const r=el.getBoundingClientRect(); if(!r.width||!r.height)return;
    if(el.scrollWidth>el.clientWidth+2&&(cs.textOverflow==='ellipsis'||cs.whiteSpace==='nowrap')&&t(el))hits.push('hclip|'+(el.className||el.tagName)+'|'+t(el));
    else if(el.scrollHeight>el.clientHeight+3&&(cs.overflowY==='hidden'||cs.overflow==='hidden')&&t(el))hits.push('vclip|'+(el.className||el.tagName)+'|'+t(el));
    const ob=r.bottom-sr.bottom,or=r.right-sr.right; if((ob>3||or>3)&&t(el)&&cs.position!=='fixed'&&cs.overflow!=='hidden'&&el.children.length<=2)hits.push('spill|'+(el.className||el.tagName)+'|'+t(el));
  }); return {key,hits};
}"""

def _scan(pw, path):
    url = "file://" + os.path.abspath(path)
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1920, "height": 1080})
    pg.goto(url, wait_until="domcontentloaded"); pg.wait_for_timeout(1200)
    keys = pg.evaluate("()=>Array.from(document.querySelectorAll('.slide-frame .slide')).map(s=>s.dataset.slideKey||s.id).filter(Boolean)")
    out = {}
    for k in keys:
        pg.evaluate(f"()=>{{location.hash='#{k}';}}"); pg.wait_for_timeout(400)
        r = pg.evaluate(MEASURE)
        if r["hits"]:
            out[k] = set(r["hits"])
    b.close()
    return out


def cmd_overflow(args):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed — `pip install playwright && playwright install chromium`", file=sys.stderr)
        return 2
    with sync_playwright() as pw:
        print("scanning source…");  base = _scan(pw, args.source)
        print("scanning target…");  tgt = _scan(pw, args.target)
    regr = {k: (h - base.get(k, set())) for k, h in tgt.items() if (h - base.get(k, set()))}
    if not regr:
        print("\n✅ no overflow REGRESSIONS (target introduced none beyond source design-overflow)")
        return 0
    print(f"\n⚠️  {len(regr)} slide(s) with NEW overflow from translation:")
    for k, hits in regr.items():
        print(f"### {k}")
        for h in list(hits)[:6]:
            print("   ", h)
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("residual-cjk"); p.add_argument("files", nargs="+")
    p.add_argument("--strict-fullwidth", action="store_true", help="also FAIL on fullwidth-punctuation residue")
    p.set_defaults(fn=cmd_residual)
    p = sub.add_parser("parity"); p.add_argument("source"); p.add_argument("roundtrip")
    p.add_argument("--css-threshold", type=float, default=0.90); p.set_defaults(fn=cmd_parity)
    p = sub.add_parser("overflow"); p.add_argument("source"); p.add_argument("target"); p.set_defaults(fn=cmd_overflow)
    a = ap.parse_args()
    sys.exit(a.fn(a))


if __name__ == "__main__":
    main()
