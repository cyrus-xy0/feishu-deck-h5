#!/usr/bin/env python3
"""Step 2b/3 (2026-05-30): 一键把外来/导入 raw deck 的字号「修对」—— 不是盲 snap。

两遍,都基于浏览器实测几何(不靠版式名、不缩任何字号):

  ① grow-box(改大自动拉高)· BODY
     每个 <24px 的正文框,量「提到 24 需多高 vs 框+画布有多少余量」:
       · GROW-OK → 把它的字号源规则改成 24(框靠 flow 自动长高,实测装得下);
       · NO-ROOM → 不动,只标出来让你压字数/删条目(永不缩字号)。

  ② hero / 封面 · 走 layout 的 hero 尺寸
     hero 版式(cover/section/big-stat/end/quote/image-text)上 off-ladder 且
     ≥48px 的大字 → 向上吸附到最近的 HERO 档(82→88…),never 缩小。

机制:在页面里找到每个目标元素「生效的字号 CSS 规则」(selectorText + 源 px),
回到源码里把那条规则的 font-size / font 简写里的那个 px 改掉。124 个静态
.slide + 1493 条 [data-page=] 规则都在 <style> 里,可直接重写。

默认 DRY-RUN(只打印计划,不写);--apply 才落盘(自带 .bak + 前后截图)。

Usage:
  python3 assets/grow-box-fit.py <deck.html>            # 体检:打印会改什么
  python3 assets/grow-box-fit.py <deck.html> --apply    # 落盘到 <deck>-fit.html(+备份+前后图)
  python3 assets/grow-box-fit.py <deck.html> --apply --inplace
"""
import sys
import re
import json
import time
import shutil
import argparse
import pathlib

ASSETS = pathlib.Path(__file__).resolve().parent

# In-browser collector: returns {bump, cut, hero}. Self-contained (mirrors the
# body_floor / hero-tier logic in visual-audit.js so the tool doesn't couple to
# its internals). px values are DESIGN px — the deck scales via transform, so
# getComputedStyle().fontSize returns the source literal, not the on-screen size.
_COLLECT_JS = r"""
() => {
  const FLOOR = 24;
  const HERO_SIZES = [30,36,38,40,44,52,56,64,72,88,92,96,100,132,160,240,312];
  const LADDER = [16,24,28,48];
  const HERO_LAYOUTS = new Set(['cover','section','big-stat','end','quote','image-text']);
  const CHROME = '.pager,.hint,.header,.footer,.fs-mobile,.fullscreen,.source,.pageno,.footnote,.attrib,.copyright,.wordmark,.contact,.cfoot,.demo-tag,.eyebrow,.kicker,.unit,.tag,.chip,.badge,.pill';
  const MOCK = /\b(mock|phone|screen|device|chat|im-|app-ui|pd-card)\b/i;

  const hasOwnText = el => {
    let t=''; for (const n of el.childNodes) if (n.nodeType===3) t+=n.textContent;
    return t.trim();
  };
  const isFramed = el => {
    const c=getComputedStyle(el);
    const hb=['Top','Right','Bottom','Left'].some(s=>parseFloat(c['border'+s+'Width']||0)>0 && !/transparent|rgba\(0, 0, 0, 0\)/.test(c['border'+s+'Color']));
    const bg=c.backgroundColor && !/transparent|rgba\(0, 0, 0, 0\)/.test(c.backgroundColor);
    const bi=c.backgroundImage && c.backgroundImage!=='none';
    return hb||bg||bi;
  };
  const isMedia = el => {
    const c=getComputedStyle(el);
    if (c.backgroundImage && c.backgroundImage!=='none' && !/gradient/i.test(c.backgroundImage)) return true;
    if (el.querySelector('img,iframe,canvas,video,picture')) return true;
    return MOCK.test((el.className||'').toString());
  };
  const contentUnion = root => {
    let top=Infinity, bottom=-Infinity, any=false;
    for (const el of root.querySelectorAll('*')) {
      if (!hasOwnText(el)) continue;
      const r=el.getBoundingClientRect(); if (r.height<1) continue;
      top=Math.min(top,r.top); bottom=Math.max(bottom,r.bottom); any=true;
    }
    return any ? {top,bottom} : null;
  };
  // the effective font rule for el: last-matching STYLE rule that sets size
  const fontRule = el => {
    let best=null;
    for (const sheet of document.styleSheets) {
      let rules; try { rules=sheet.cssRules; } catch(e){ continue; }
      if (!rules) continue;
      for (const rule of rules) {
        if (rule.type!==1) continue;
        let m=false; try { m=el.matches(rule.selectorText); } catch(e){ continue; }
        if (!m) continue;
        const ct=rule.cssText||'';
        if (/font-size\s*:\s*\d+px/.test(ct) || /font\s*:\s*[^;{}]*?\d+px/.test(ct))
          best={selectorText: rule.selectorText};   // last wins ≈ cascade
      }
    }
    return best;
  };

  const slides=[...document.querySelectorAll('.slide')];
  const out={bump:[], cut:[], hero:[]};
  const seen=new Set();

  slides.forEach((slide, i) => {
    const idx=i+1;
    const layout=slide.getAttribute('data-layout')||'';
    const isHero=HERO_LAYOUTS.has(layout);
    const scale=parseFloat(getComputedStyle(slide).getPropertyValue('--fs-scale'))||1;
    const sr=slide.getBoundingClientRect();

    for (const el of slide.querySelectorAll('*')) {
      if (el.tagName==='STYLE'||el.tagName==='SCRIPT'||el.ownerSVGElement) continue;
      const t=hasOwnText(el); if (t.length<6) continue;
      const px=Math.round(parseFloat(getComputedStyle(el).fontSize)||0);
      if (!px) continue;
      if (el.closest(CHROME)) continue;
      let inMock=false; for (let n=el;n&&n!==slide;n=n.parentElement) if (MOCK.test((n.className||'').toString())){inMock=true;break;}
      if (inMock) continue;

      // ② hero / 封面 — off-ladder 大字,向上吸附
      if (px>=48 && isHero && !LADDER.includes(px) && !HERO_SIZES.includes(px)) {
        const up=HERO_SIZES.filter(h=>h>=px).sort((a,b)=>a-b)[0];
        if (up && up!==px) {
          const fr=fontRule(el); if (!fr) continue;
          const k='H'+fr.selectorText+px; if (seen.has(k)) continue; seen.add(k);
          out.hero.push({slide:idx, sel:fr.selectorText, oldPx:px, newPx:up, preview:t.slice(0,22)});
        }
        continue;
      }

      // ① body grow-box — sub-floor content text
      if (px>=FLOOR) continue;
      if (t.length<8) continue;
      if (isHero) continue;                       // hero zone handled above
      const fr=fontRule(el); if (!fr) continue;
      // grow verdict
      const elH=el.getBoundingClientRect().height/scale;
      const grow=Math.round(elH*(FLOOR/px-1));
      let node=el.parentElement, box=null;
      while (node && node!==slide){ if (isFramed(node)&&!isMedia(node)){box=node;break;} node=node.parentElement; }
      const target=box||slide; const br=target.getBoundingClientRect();
      const cu=contentUnion(target);
      const innerSlack=cu?Math.max(0,(br.bottom-cu.bottom)/scale):0;
      const canvasBelow=box?Math.max(0,(sr.bottom-br.bottom)/scale):0;
      const room=Math.round(innerSlack+canvasBelow);
      const rec={slide:idx, sel:fr.selectorText, oldPx:px, newPx:FLOOR, grow, room, preview:t.slice(0,22)};
      const k='B'+fr.selectorText+px; if (seen.has(k)) continue; seen.add(k);
      (grow<=room ? out.bump : out.cut).push(rec);
    }
  });
  return out;
}
"""


def _rewrite_rule(html, selector, old_px, new_px):
    """In `html`, find the CSS block(s) for `selector` and bump the font px
    `old_px`→`new_px` inside font-size: / font: shorthand. Returns (html, n)."""
    sel_re = re.escape(selector)
    # selector may have flexible whitespace in source vs CSSOM-normalized form
    sel_re = sel_re.replace(r'\ ', r'\s+').replace(r'\>', r'\s*>\s*').replace(r'\,', r'\s*,\s*')
    block_re = re.compile(sel_re + r'\s*\{([^{}]*)\}')
    n = [0]

    def _block(m):
        body = m.group(1)
        # font-size: OLDpx
        body2 = re.sub(r'(font-size\s*:\s*)' + str(old_px) + r'px',
                       lambda mm: mm.group(1) + f'{new_px}px', body)
        # font: <...> OLDpx (the size token in shorthand, before optional /lh)
        body2 = re.sub(r'(font\s*:\s*[^;{}]*?)\b' + str(old_px) + r'px',
                       lambda mm: mm.group(1) + f'{new_px}px', body2)
        if body2 != body:
            n[0] += 1
        return m.group(0).replace(body, body2) if body2 != body else m.group(0)

    return block_re.sub(_block, html), n[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("deck")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run report)")
    ap.add_argument("--inplace", action="store_true", help="with --apply: edit in place (else <deck>-fit.html)")
    args = ap.parse_args()

    deck = pathlib.Path(args.deck).resolve()
    if not deck.exists():
        print(f"✗ not found: {deck}"); sys.exit(2)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("✗ needs playwright (pip install playwright && playwright install chromium)"); sys.exit(2)

    url = deck.as_uri()
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_context(viewport={"width": 1920, "height": 1080}).new_page()
        pg.goto(url, wait_until="domcontentloaded", timeout=60000)
        pg.wait_for_timeout(2000)
        plan = pg.evaluate(_COLLECT_JS)
        b.close()

    bump, cut, hero = plan["bump"], plan["cut"], plan["hero"]
    print(f"\n=== grow-box-fit 计划 · {deck.name} ===")
    print(f"① BODY grow-box:{len(bump)} 条规则可「改大自动拉高」(→24),"
          f"{len(cut)} 条 NO-ROOM(需压内容,不改字号)")
    print(f"② HERO/封面:{len(hero)} 条 off-ladder 大字向上吸附到 hero 档\n")
    for r in bump[:30]:
        print(f"  [BODY→24] s{r['slide']:>2} {r['oldPx']}px grow{r['grow']}/room{r['room']}  "
              f"{r['sel'][:54]}  '{r['preview']}'")
    if len(bump) > 30: print(f"  … +{len(bump)-30} more")
    for r in hero[:20]:
        print(f"  [HERO {r['oldPx']}→{r['newPx']}] s{r['slide']:>2}  {r['sel'][:54]}  '{r['preview']}'")
    for r in cut[:20]:
        print(f"  [NO-ROOM] s{r['slide']:>2} {r['oldPx']}px grow{r['grow']}>room{r['room']}  "
              f"{r['sel'][:48]}  '{r['preview']}' → 压字数/删条目")

    if not args.apply:
        print("\n(DRY-RUN — 没改任何东西。加 --apply 落盘,自带备份 + 前后截图。)")
        return

    # ---- apply ----
    html = deck.read_text(encoding="utf-8")
    changes = [(r["sel"], r["oldPx"], r["newPx"]) for r in bump] + \
              [(r["sel"], r["oldPx"], r["newPx"]) for r in hero]
    total = 0
    for sel, old, new in changes:
        html, n = _rewrite_rule(html, sel, old, new)
        total += n
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = deck.with_name(deck.stem + f".bak-pre-growfit-{ts}" + deck.suffix)
    shutil.copy2(deck, bak)
    out = deck if args.inplace else deck.with_name(deck.stem + "-fit" + deck.suffix)
    out.write_text(html, encoding="utf-8")
    print(f"\n✓ 改写 {total} 条规则的字号 · 备份 {bak.name} · 写出 {out.name}")
    print(f"  NO-ROOM 的 {len(cut)} 条未动(需你压内容)。字号一律没缩小。")

    # before/after of the first changed slide
    if changes:
        s1 = (bump or hero)[0]["slide"]
        for tag, f in (("before", deck), ("after", out)):
            pg2 = None
            with sync_playwright() as p:
                bb = p.chromium.launch(); pg2 = bb.new_context(viewport={"width": 1920, "height": 1080}).new_page()
                pg2.goto(f.as_uri(), wait_until="domcontentloaded", timeout=60000); pg2.wait_for_timeout(1500)
                pg2.evaluate(f'window.location.hash="#{s1}"'); pg2.wait_for_timeout(800)
                shot = f"/tmp/growfit-s{s1}-{tag}.png"; pg2.screenshot(path=shot); bb.close()
                print(f"  截图 {tag}: {shot}")


if __name__ == "__main__":
    main()
