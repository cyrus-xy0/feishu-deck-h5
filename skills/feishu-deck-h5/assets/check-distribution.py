#!/usr/bin/env python3
"""
check-distribution.py — name-free, geometric layout-distribution audit.

Measures how content is *distributed* in a rendered deck at THREE nesting
levels, and flags the failures the validator currently misses. Nothing here
keys on a layout NAME or a per-layout whitelist — every signal is a geometric
ratio or a relative comparison, so it works identically on schema layouts and
hand-written `layout:raw` slides.

The only escape is the framework's existing author override
`data-allow-imbalance` on a `.slide` (an explicit "this one is intentional"
marker — NOT a name whitelist).

Three levels (the "distribution is fractal" model):
  L1 · canvas   — is the slide's content block centered / does it use the canvas
                  (位置偏移 · 画布利用率低)
  L2 · group    — are sibling blocks evenly distributed, are side-by-side peers
                  on a shared baseline (块间死带 · 左高右低)
  L3 · box      — inside each framed box, are the top/bottom insets balanced; do
                  peer boxes in a row share a bottom inset
                  (卡内文字贴底 · 整排卡下边距参差)

Usage:
  python3 assets/check-distribution.py <deck.html> [--slide N] [--json] [--quiet-pass]

A centered 金句 page PASSES here not because it is whitelisted, but because its
insets are symmetric — the same rule that fails a bottom-crowded card.
"""
import sys, json, argparse
from pathlib import Path

# ---- The measurement runs in the browser; Python only thresholds + formats. ----
MEASURE_JS = r"""
() => {
  const clsOf = (el) => {
    const c = el.className;
    if (c == null) return '';
    return (typeof c === 'object' && 'baseVal' in c) ? c.baseVal : String(c);
  };
  const DECOR = (el) => {
    if (el.tagName === 'SVG' || el.tagName === 'svg') return true;
    if (['SCRIPT','STYLE','NOSCRIPT'].includes(el.tagName)) return true;
    return /\b(wordmark|pageno|grid-bg|bg-layer|aurora|glow|decor|keyline|watermark)\b/i.test(clsOf(el));
  };
  const hasOwnText = (el) =>
    [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length);
  // union bbox of visible TEXT-bearing leaves under root (decoration excluded)
  const contentUnion = (root) => {
    let t=Infinity,b=-Infinity,l=Infinity,r=-Infinity,any=false;
    const all = root.querySelectorAll('*');
    for (const el of all) {
      if (DECOR(el)) continue;
      if (!hasOwnText(el)) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) continue;
      const rc = el.getBoundingClientRect();
      if (rc.width < 2 || rc.height < 2) continue;
      any = true;
      t=Math.min(t,rc.top); b=Math.max(b,rc.bottom); l=Math.min(l,rc.left); r=Math.max(r,rc.right);
    }
    return any ? {top:t,bottom:b,left:l,right:r} : null;
  };
  // inner content-box (padding excluded) of an element
  const innerBox = (el) => {
    const rc = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return {
      top: rc.top + parseFloat(cs.paddingTop || 0),
      bottom: rc.bottom - parseFloat(cs.paddingBottom || 0),
      left: rc.left + parseFloat(cs.paddingLeft || 0),
      right: rc.right - parseFloat(cs.paddingRight || 0),
      h: rc.height, w: rc.width,
    };
  };
  const isFramedBox = (el) => {
    const cs = getComputedStyle(el);
    const hasBorder = ['Top','Right','Bottom','Left'].some(s =>
      parseFloat(cs['border'+s+'Width']||0) > 0 &&
      !/transparent|rgba\(0, 0, 0, 0\)/.test(cs['border'+s+'Color']));
    const bg = cs.backgroundColor;
    const hasBg = bg && !/transparent|rgba\(0, 0, 0, 0\)/.test(bg);
    const hasBgImg = cs.backgroundImage && cs.backgroundImage !== 'none';
    return (hasBorder || hasBg || hasBgImg);
  };
  // Media tiles (photo/mock/iframe) carry a caption that is INTENTIONALLY
  // bottom/edge-placed — measuring its "text inset" is a false positive.
  // Excluded from the box-level inset checks (still counted as a block).
  const isMedia = (el) => {
    const cs = getComputedStyle(el);
    if (cs.backgroundImage && cs.backgroundImage !== 'none' && !/gradient/i.test(cs.backgroundImage)) return true;
    if (el.querySelector('img,iframe,canvas,video,picture')) return true;
    return /\b(photo|image|img|visual|mock|thumb|avatar|portrait|media|phone|screen)\b/i.test(clsOf(el));
  };

  const BODY_SEL = ':scope > .stage, :scope > .grid, :scope > .flow, :scope > .nodes, ' +
                   ':scope > .toc, :scope > .stack, :scope > .table-wrap';
  const HERO_HINT = /\b(cover|section|big-stat|quote|image-text|end)\b/;

  const out = [];
  const slides = document.querySelectorAll('.slide');
  let idx = 0;
  for (const slide of slides) {
    idx++;
    const label = slide.getAttribute('data-screen-label') || slide.getAttribute('data-slide-key') || ('#'+idx);
    const layoutAttr = slide.getAttribute('data-layout') || '';
    const scale = parseFloat(getComputedStyle(slide).getPropertyValue('--fs-scale')) || 1;
    const allowImbalance = slide.hasAttribute('data-allow-imbalance');

    // resolve body container: prefer .stage, then a known container; drill
    // through single-child wrappers so we measure the real content container.
    let body = slide.querySelector(BODY_SEL);
    if (body) {
      let guard = 0;
      while (body && body.children.length === 1 && guard++ < 4) {
        const only = body.children[0];
        if (/\b(grid|flow|nodes|toc|stack|table-wrap|stage)\b/.test(clsOf(only))) body = only;
        else break;
      }
    }
    const container = body || slide;
    const cbox = innerBox(container);
    const content = contentUnion(container);

    // direct content children = "blocks" for the group level
    const blocks = [...container.children]
      .filter(el => !DECOR(el))
      .map(el => ({ el, rc: el.getBoundingClientRect() }))
      .filter(o => o.rc.width > 8 && o.rc.height > 8)
      .sort((a,b) => a.rc.top - b.rc.top);

    // framed boxes (cards/panels) anywhere under the container
    const boxEls = [...container.querySelectorAll('*')]
      .filter(el => !DECOR(el) && el !== container && isFramedBox(el) &&
                    el.getBoundingClientRect().height > 40 &&
                    el.getBoundingClientRect().width > 40 &&
                    contentUnion(el));
    // keep only "outermost" framed boxes (drop framed children of framed boxes)
    const boxes = boxEls.filter(el => !boxEls.some(other => other !== el && other.contains(el)));

    const boxData = boxes.map(el => {
      const ib = innerBox(el);
      const cu = contentUnion(el);
      return {
        sel: (el.tagName.toLowerCase() + '.' + (clsOf(el).trim().split(/\s+/)[0] || '')),
        media: isMedia(el),
        topInset: (cu.top - ib.top) / scale,
        bottomInset: (ib.bottom - cu.bottom) / scale,
        leftInset: (cu.left - ib.left) / scale,
        rightInset: (ib.right - cu.right) / scale,
        h: ib.h / scale,
        cx: (el.getBoundingClientRect().left + el.getBoundingClientRect().right) / 2,
        cy: (el.getBoundingClientRect().top + el.getBoundingClientRect().bottom) / 2,
        top: el.getBoundingClientRect().top,
        bottom: el.getBoundingClientRect().bottom,
        left: el.getBoundingClientRect().left,
        right: el.getBoundingClientRect().right,
      };
    });

    // group gaps (vertical, between stacked blocks)
    const gaps = [];
    for (let i = 1; i < blocks.length; i++) {
      const prev = blocks[i-1].rc, cur = blocks[i].rc;
      // only count as a stacked gap if they don't horizontally sit side-by-side
      const sideBySide = !(cur.left >= prev.right - 4 || cur.right <= prev.left + 4) ? false : true;
      if (sideBySide) continue;
      const overlapX = Math.min(prev.right, cur.right) - Math.max(prev.left, cur.left);
      if (overlapX <= 8) continue; // truly side-by-side, skip
      gaps.push((cur.top - prev.bottom) / scale);
    }

    out.push({
      idx, label, layoutAttr, scale, allowImbalance,
      heroHint: HERO_HINT.test(layoutAttr),
      container: {
        h: cbox.h / scale, w: cbox.w / scale,
        topInset: content ? (content.top - cbox.top) / scale : null,
        bottomInset: content ? (cbox.bottom - content.bottom) / scale : null,
        leftInset: content ? (content.left - cbox.left) / scale : null,
        rightInset: content ? (cbox.right - content.right) / scale : null,
        fillV: (content && cbox.h) ? (content.bottom - content.top) / cbox.h : null,
        fillH: (content && cbox.w) ? (content.right - content.left) / cbox.w : null,
        blockCount: blocks.length,
      },
      gaps,
      boxes: boxData,
    });
  }
  return out;
};
"""

def pct(x):
    return f"{x*100:.0f}%" if x is not None else "—"

def px(x):
    return f"{x:.0f}px" if x is not None else "—"

def signals_for(s):
    """Apply name-free geometric thresholds. Returns list of (code, sev, msg)."""
    if s["allowImbalance"]:
        return []  # explicit author override (not a name whitelist)
    out = []
    c = s["container"]
    H = c["h"] or 1

    # ---------- L1 · CANVAS ----------
    ti, bi = c["topInset"], c["bottomInset"]
    if ti is not None and bi is not None:
        slack = ti + bi
        # OFFSET: meaningful slack AND strongly asymmetric top vs bottom
        if slack > 0.12 * H and abs(ti - bi) > 0.5 * slack and abs(ti - bi) > 80:
            where = "偏上(下方留白多)" if bi > ti else "偏下(上方留白多)"
            out.append(("L1-OFFSET", "warn",
                f"内容{where} · 上内距{px(ti)} vs 下内距{px(bi)}(应大致相等)"))
    # UNDERFILL: structural-gated (≥2 parallel blocks) — single focal block (金句) exempt by STRUCTURE, not name
    if c["fillV"] is not None and c["blockCount"] >= 2 and not s["heroHint"]:
        if c["fillV"] < 0.45:
            out.append(("L1-UNDERFILL-V", "warn",
                f"纵向利用率低 · 内容只占画布高 {pct(c['fillV'])}(≥2 个并列块却缩成一小条)"))
    if c["fillH"] is not None and c["blockCount"] <= 1 and not s["heroHint"]:
        if c["fillH"] < 0.5:
            out.append(("L1-UNDERFILL-H", "warn",
                f"横向利用率低 · 内容只占画布宽 {pct(c['fillH'])}(单列窄条飘在中间 → 加宽/两栏/配伴随块)"))

    # ---------- L2 · GROUP ----------
    gaps = sorted(s["gaps"])
    if len(gaps) >= 2:
        # LOWER median (typical gap, excluding the outlier max). The old
        # `gaps[len//2]` picked the UPPER-middle, so for exactly 2 gaps it
        # equalled the max → `mx > 1.9*med` was `mx > 1.9*mx` → the dead-band
        # check could never fire on a 2-gap group.
        med = gaps[(len(gaps) - 1) // 2]
        mx = gaps[-1]
        edge = min([v for v in [ti, bi] if v is not None] or [9999])
        if med > 0 and mx > 1.9 * med and mx > 1.4 * edge and mx > 120:
            out.append(("L2-DEADBAND", "warn",
                f"块间死带 · 最大间距{px(mx)} ≫ 常规间距{px(med)}(底下与上面离太远 → 收成一组/等距/封顶)"))

    # cross-axis: peer boxes sharing a row but with misaligned vertical centers
    rows = []
    bs = sorted(s["boxes"], key=lambda b: b["left"])
    for b in bs:
        placed = False
        for row in rows:
            # same row if vertical ranges overlap > 50%
            ov = min(b["bottom"], row["bottom"]) - max(b["top"], row["top"])
            if ov > 0.5 * min(b["bottom"]-b["top"], row["bottom"]-row["top"]):
                row["items"].append(b)
                row["top"] = min(row["top"], b["top"]); row["bottom"] = max(row["bottom"], b["bottom"])
                placed = True; break
        if not placed:
            rows.append({"items":[b], "top":b["top"], "bottom":b["bottom"]})
    for row in rows:
        if len(row["items"]) >= 2:
            cys = [it["cy"] for it in row["items"]]
            spread = (max(cys) - min(cys)) / (s["scale"] or 1)
            if spread > 0.06 * 1080 and spread > 40:
                out.append(("L2-CROSSAXIS", "warn",
                    f"左高右低 · 同排 {len(row['items'])} 个框竖直中线相差{px(spread)}(并排同级块应共享一条中线 → align-items:center)"))

    # ---------- L3 · BOX ----------
    for b in s["boxes"]:
        ti2, bi2 = b["topInset"], b["bottomInset"]
        if b.get("media") or ti2 is None or bi2 is None or b["h"] < 60:
            continue
        lo, hi = min(ti2, bi2), max(ti2, bi2)
        if hi > 0 and lo < 0.45 * hi and (hi - lo) > 18:
            side = "贴底(下内距小)" if bi2 < ti2 else "贴顶(上内距小)"
            out.append(("L3-BOXINSET", "warn",
                f"框内文字{side} · {b['sel']} 上内距{px(ti2)}/下内距{px(bi2)}(框内应上下均衡)"))
    # peer boxes: bottom-inset raggedness across a row (the qingdao 3-up case)
    for row in rows:
        items = [it for it in row["items"] if it["h"] >= 60 and not it.get("media")]
        if len(items) >= 2:
            bins = [it["bottomInset"] for it in items]
            if min(bins) >= 0 and max(bins) > 2.2 * max(min(bins), 1) and (max(bins)-min(bins)) > 24:
                out.append(("L3-BOXROW", "warn",
                    f"整排框下内距参差 · {len(items)} 个并排框下内距 {', '.join(px(x) for x in bins)}"
                    f"(最满的那张贴底、其余富余 → 卡内容居中或给最小下内距)"))
    return out

# ---- The corrector — MEASUREMENT-GATED. It re-walks the deck, and on each
# element it ONLY corrects the ones that measure imbalanced (same thresholds
# as the audit), skipping `data-allow-imbalance`. A blunt global stylesheet
# fixes the target but perturbs bespoke raw pages (net wash); gating touches
# only what's wrong → improvement without collateral. This is the exact shape
# of the production auto-balance pass that belongs in feishu-deck.js (after
# scale-to-fit). No layout name appears anywhere.
GATED_FIX_JS = r"""
() => {
  const clsOf = (el) => { const c=el.className; if(c==null) return ''; return (typeof c==='object'&&'baseVal' in c)?c.baseVal:String(c); };
  const DECOR = (el) => { if(/^(SVG|svg|SCRIPT|STYLE|NOSCRIPT)$/.test(el.tagName)) return true; return /\b(wordmark|pageno|grid-bg|bg-layer|aurora|glow|decor|keyline|watermark)\b/i.test(clsOf(el)); };
  const hasOwnText = (el) => [...el.childNodes].some(n=>n.nodeType===3&&n.textContent.trim().length);
  const contentUnion = (root) => { let t=Infinity,b=-Infinity,l=Infinity,r=-Infinity,any=false; for(const el of root.querySelectorAll('*')){ if(DECOR(el)||!hasOwnText(el)) continue; const cs=getComputedStyle(el); if(cs.visibility==='hidden'||cs.display==='none'||+cs.opacity===0) continue; const rc=el.getBoundingClientRect(); if(rc.width<2||rc.height<2) continue; any=true; t=Math.min(t,rc.top);b=Math.max(b,rc.bottom);l=Math.min(l,rc.left);r=Math.max(r,rc.right);} return any?{top:t,bottom:b,left:l,right:r}:null; };
  const innerBox = (el) => { const rc=el.getBoundingClientRect(),cs=getComputedStyle(el); return {top:rc.top+parseFloat(cs.paddingTop||0),bottom:rc.bottom-parseFloat(cs.paddingBottom||0),left:rc.left+parseFloat(cs.paddingLeft||0),right:rc.right-parseFloat(cs.paddingRight||0),h:rc.height,w:rc.width}; };
  const isFramedBox = (el) => { const cs=getComputedStyle(el); const hb=['Top','Right','Bottom','Left'].some(s=>parseFloat(cs['border'+s+'Width']||0)>0&&!/transparent|rgba\(0, 0, 0, 0\)/.test(cs['border'+s+'Color'])); const bg=cs.backgroundColor; const hbg=bg&&!/transparent|rgba\(0, 0, 0, 0\)/.test(bg); const hbi=cs.backgroundImage&&cs.backgroundImage!=='none'; return hb||hbg||hbi; };
  const isMedia = (el) => { const cs=getComputedStyle(el); if(cs.backgroundImage&&cs.backgroundImage!=='none'&&!/gradient/i.test(cs.backgroundImage)) return true; if(el.querySelector('img,iframe,canvas,video,picture')) return true; return /\b(photo|image|img|visual|mock|thumb|avatar|portrait|media|phone|screen)\b/i.test(clsOf(el)); };
  const BODY_SEL = ':scope > .stage, :scope > .grid, :scope > .flow, :scope > .nodes, :scope > .toc, :scope > .stack, :scope > .table-wrap';

  let applied = 0;
  for (const slide of document.querySelectorAll('.slide')) {
    if (slide.hasAttribute('data-allow-imbalance')) continue;
    const scale = parseFloat(getComputedStyle(slide).getPropertyValue('--fs-scale'))||1;
    let body = slide.querySelector(BODY_SEL);
    if (body) { let g=0; while(body&&body.children.length===1&&g++<4){ const only=body.children[0]; if(/\b(grid|flow|nodes|toc|stack|table-wrap|stage)\b/.test(clsOf(only))) body=only; else break; } }
    const container = body || slide;

    // L3 · framed non-media text boxes that measure asymmetric → un-stretch
    // their row (content-size + shared midline) + center content inside.
    const boxEls = [...container.querySelectorAll('*')].filter(el=>!DECOR(el)&&el!==container&&isFramedBox(el)&&!isMedia(el)&&el.getBoundingClientRect().height>60&&contentUnion(el));
    const boxes = boxEls.filter(el=>!boxEls.some(o=>o!==el&&o.contains(el)));
    const flagged = boxes.filter(el=>{ const ib=innerBox(el),cu=contentUnion(el); const ti=(cu.top-ib.top)/scale,bi=(ib.bottom-cu.bottom)/scale,lo=Math.min(ti,bi),hi=Math.max(ti,bi); return hi>0&&lo<0.45*hi&&(hi-lo)>18; });
    const parents = new Set(flagged.map(b=>b.parentElement).filter(Boolean));
    parents.forEach(p=>{ for(const ch of p.children){ if(ch.nodeType===1) ch.style.alignSelf='center'; } applied++; });
    flagged.forEach(b=>{ b.style.display='flex'; b.style.flexDirection='column'; b.style.justifyContent='center'; applied++; });

    // L1 · group offset → center the body container only if it measures off.
    const cbox=innerBox(container), content=contentUnion(container);
    if (content) {
      const ti=(content.top-cbox.top)/scale, bi=(cbox.bottom-content.bottom)/scale;
      const H=(cbox.h/scale)||1, slack=ti+bi;
      if (slack>0.12*H && Math.abs(ti-bi)>0.5*slack && Math.abs(ti-bi)>80) {
        container.style.placeContent='center'; container.style.alignContent='center'; applied++;
      }
    }
  }
  return applied;
};
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("deck", help="path to rendered index.html")
    ap.add_argument("--slide", type=int, default=None, help="focus a single slide (1-based)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet-pass", action="store_true", help="hide slides with no findings")
    ap.add_argument("--fix", action="store_true",
                    help="apply the name-free auto-balance CSS and show before→after")
    ap.add_argument("--css", default=None,
                    help="inject a candidate CSS file (test a framework default) and show before→after")
    args = ap.parse_args()

    path = Path(args.deck).resolve()
    if not path.exists():
        print(f"✗ not found: {path}"); sys.exit(2)
    url = path.as_uri()

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width":1920,"height":1080})
        page = ctx.new_page()
        page.goto(url, wait_until="load", timeout=60_000)
        page.evaluate("() => { const d=document.querySelector('.deck'); if(d) d.setAttribute('data-mode','present'); }")
        page.wait_for_timeout(250)
        data = page.evaluate(MEASURE_JS)
        data_after = None
        if args.fix:
            applied = page.evaluate(GATED_FIX_JS)
            page.wait_for_timeout(300)
            data_after = page.evaluate(MEASURE_JS)
            print(f"[gated auto-balance] 仅修正测出失衡的元素 · 应用 {applied} 处")
        elif args.css:
            css = Path(args.css).read_text(encoding="utf-8")
            page.add_style_tag(content=css)
            page.wait_for_timeout(300)
            data_after = page.evaluate(MEASURE_JS)
            print(f"[candidate CSS] 注入 {args.css} 后重测")
        browser.close()

    show_after = bool(args.fix or args.css)

    if args.slide is not None:  # slides are 0-indexed; `--slide 0` is valid, not "no filter"
        data = [s for s in data if s["idx"] == args.slide]
        if data_after:
            data_after = [s for s in data_after if s["idx"] == args.slide]

    if show_after:
        after_by_idx = {s["idx"]: s for s in (data_after or [])}
        b_tot = a_tot = b_slides = a_slides = 0
        for s in data:
            bs = signals_for(s); a = after_by_idx.get(s["idx"])
            as_ = signals_for(a) if a else []
            b_tot += len(bs); a_tot += len(as_)
            b_slides += 1 if bs else 0; a_slides += 1 if as_ else 0
            if (bs or as_) and (not args.quiet_pass or bs):
                print(f"\n\033[1m#{s['idx']:>2} [{s['label']}] {s['layoutAttr']}\033[0m")
                print(f"   before: {len(bs)} finding(s)" + (f" — {'; '.join(c for c,_,_ in bs)}" if bs else ""))
                if a:
                    cb = s['container']; ca = a['container']
                    print(f"     container insets T/B {px(cb['topInset'])}/{px(cb['bottomInset'])} → "
                          f"{px(ca['topInset'])}/{px(ca['bottomInset'])} · fillV {pct(cb['fillV'])}→{pct(ca['fillV'])}")
                    for i,(bx) in enumerate(s['boxes']):
                        ax = a['boxes'][i] if i < len(a['boxes']) else None
                        if ax and not bx.get('media'):
                            print(f"     box {bx['sel']:<16} T/B {px(bx['topInset'])}/{px(bx['bottomInset'])} → "
                                  f"{px(ax['topInset'])}/{px(ax['bottomInset'])}")
                print(f"   after:  {len(as_)} finding(s)" + (f" — {'; '.join(c for c,_,_ in as_)}" if as_ else " ✓ balanced"))
        print(f"\n— before: {b_slides} slides / {b_tot} findings  →  after: {a_slides} slides / {a_tot} findings —")
        return

    if args.json:
        enriched = [{**s, "signals": signals_for(s)} for s in data]
        print(json.dumps(enriched, ensure_ascii=False, indent=2)); return

    total_hits = 0; flagged = 0
    for s in data:
        sig = signals_for(s)
        if not sig and args.quiet_pass:
            continue
        head = f"#{s['idx']:>2} [{s['label']}] layout={s['layoutAttr'] or '?'} blocks={s['container']['blockCount']} boxes={len(s['boxes'])}"
        if sig:
            flagged += 1; total_hits += len(sig)
            print(f"\n\033[1m{head}\033[0m")
            c = s["container"]
            print(f"     container fillV={pct(c['fillV'])} fillH={pct(c['fillH'])} "
                  f"insets T/B={px(c['topInset'])}/{px(c['bottomInset'])} L/R={px(c['leftInset'])}/{px(c['rightInset'])}")
            for code, sev, msg in sig:
                print(f"     ⚠ {code:<14} {msg}")
        elif not args.quiet_pass:
            print(f"  ✓ {head}")
    print(f"\n— {flagged} slide(s) flagged · {total_hits} finding(s) —")

if __name__ == "__main__":
    main()
