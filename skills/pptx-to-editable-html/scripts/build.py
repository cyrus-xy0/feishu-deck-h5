#!/usr/bin/env python3
"""build.py — dual-background editable HTML generator (manifest-driven).

Architecture (learned from the reference deck, refined over many rounds):
  • VIEW mode shows the ORIGINAL with-text image (bg) → 100% fidelity (fonts,
    alignment — it's the real render). The structured text layer is hidden.
  • EDIT mode (press E) swaps to the no-text image (bgNotext) + reveals editable
    text boxes at the ORIGINAL font size (so creators judge real line fit).
  • A box you edit gets .dirty and stays visible in view mode; its background is
    the same-region crop of the no-text image, masking the baked text beneath it
    (no ghosting/重影).
  • Sidebar 目录: thumbnails with click-jump, multi-select (Cmd/Ctrl/Shift) +
    group drag-reorder, and per-page hide (eye). Order/hidden/edits persist to
    localStorage and bake into the exported HTML (window.__INIT).

Everything (image hosts, fonts, media, title) comes from a manifest JSON — no
deck-specific hardcoding. Coordinates in the manifest are px on a 1920×1080
design canvas; this script converts them to cqw/cqh so the deck scales purely
in CSS (container queries) with no JS scaling.

Usage:
  python3 build.py manifest.json --out index.html
Manifest schema: see references/manifest-schema.md
"""
import argparse
import html as H
import json
import sys

W, H_ = 1920.0, 1080.0
ALIGN = {'CENTER': 'center', 'RIGHT': 'right', 'JUSTIFY': 'justify', 'LEFT': 'left'}
ANCHOR = {'MIDDLE (3)': 'center', 'BOTTOM (4)': 'flex-end', 'TOP (1)': 'flex-start',
          'MIDDLE': 'center', 'BOTTOM': 'flex-end', 'TOP': 'flex-start'}

# in-deck i18n (set in main when --i18n given): _I18N maps source text -> {h,e,j};
# _I18N_OUT accumulates per-line translations in render order, baked as window.__I18N.
_I18N = None
_I18N_OUT = []


def cqw(px): return f'{px / W * 100:.3f}cqw'
def cqh(px): return f'{px / H_ * 100:.3f}cqh'


def _insets(s):
    ins = s.get('insets')
    if ins and len(ins) == 4:
        return max(ins[0], 6), max(ins[1], 6), max(ins[2], 2), max(ins[3], 2)
    return 10, 10, 4, 4


def _gap(p, sz):
    return p.get('spc_before') or round(sz * 0.22, 1)


def render_tb(s, sidx, tidx):
    paras = s.get('paras')
    if not paras or not any(p.get('text', '').strip() for p in paras):
        return ''
    anchor = ANCHOR.get(s.get('anchor') or '', 'flex-start')
    nn = [p.get('align') for p in paras if p.get('align') and p.get('text', '').strip()]
    dom = max(set(nn), key=nn.count) if nn else None
    il, ir, it, ib = _insets(s)
    bgpos = f"background-position:-{cqw(s['left'])} -{cqh(s['top'])}"
    outer = (f"left:{cqw(s['left'])};top:{cqh(s['top'])};width:{cqw(s['width'])};height:{cqh(s['height'])};"
             f"padding:{cqh(it)} {cqw(ir)} {cqh(ib)} {cqw(il)};justify-content:{anchor};{bgpos}")
    lns = ''
    last = 16
    first = True
    for p in paras:
        t = p.get('text', '')
        base = p.get('size') or last
        last = p.get('size') or last
        gap = '' if first else f"margin-top:{cqh(_gap(p, base))};"
        first = False
        if not t.strip():
            lns += f'<div class="ln" style="height:{cqh(base*0.5)}"></div>'
            continue
        al = ALIGN.get(p.get('align') or '', None) or ALIGN.get(dom or '', None) or 'left'
        st = f"font-size:calc({cqw(base)} * var(--fit,1) * var(--gfit,1));text-align:{al};{gap}"
        if p.get('color'):
            st += f"color:{p['color']};"
        if p.get('bold'):
            st += "font-weight:700;"
        di = ''
        if _I18N is not None:
            rec = _I18N.get(t)
            if rec:
                di = f' data-i="{len(_I18N_OUT)}"'
                _I18N_OUT.append(rec)
        lns += f'<div class="ln"{di} style="{st}">{H.escape(t)}</div>'
    ov = ' tb-over' if s.get('over') else ''
    _mx = max((p.get('size') or 0) for p in paras)
    ti = ' tb-title' if (s.get('top', 999) < 110 and _mx >= 44) else ''
    return f'<div class="tb{ov}{ti}" data-id="{sidx}:{tidx}" style="{outer}"><div class="bh" title="拖动移动文本框">✥</div><div class="tbin">{lns}</div><div class="brh" title="拖动改变文本框大小"></div></div>'


def render_media(m):
    style = (f"left:{cqw(m['left'])};top:{cqh(m['top'])};width:{cqw(m['width'])};height:{cqh(m['height'])}")
    if m.get('round'):
        style += ';border-radius:1.1cqw;overflow:hidden'
    if m.get('clip'):
        style += f";clip-path:{m['clip']}"
    url = m['url']
    if m.get('gif'):   # no audio → behaves like the original GIF: autoplay loop
        return (f'<video class="media-overlay" src="{url}" style="{style}" '
                f'autoplay muted loop playsinline preload="auto" data-keep-muted></video>')
    mute = ' muted data-keep-muted' if m.get('muted') else ''
    return (f'<video class="media-overlay" src="{url}#t=0.1" style="{style}" '
            f'controls loop playsinline preload="metadata"{mute}></video>')


def render_slide(s, i):
    media = ''.join(render_media(m) for m in s.get('media', []))
    tbs = ''.join(render_tb(t, i, j) for j, t in enumerate(s.get('texts', [])))
    nt = s.get('bgNotext', s['bg'])
    dm = ' dim-others' if s.get('dimothers') else ''
    return (f'<section class="slide{dm}" data-n="{i}" style="--nt:url(\'{nt}\')">'
            f'<img class="bg" data-src="{s["bg"]}" alt="">'
            f'<img class="bg-notext" data-src="{nt}" alt="">'
            f'<div class="medialayer">{media}</div>'
            f'<div class="textlayer">{tbs}</div></section>')


def render_thumbs(slides):
    out = ''
    for i, s in enumerate(slides):
        out += (f'<div class="thumb" data-i="{i}" draggable="true"><img src="{s["bg"]}" loading="lazy" alt="">'
                f'<span class="tno">{i+1}</span>'
                f'<button class="eye" title="隐藏/显示此页"><span class="e-on">{EYE}</span><span class="e-off">{EYEOFF}</span></button>'
                f'<span class="grip" title="拖动调整顺序">⠿</span></div>')
    return out


EYE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z"/><circle cx="12" cy="12" r="3"/></svg>'
EYEOFF = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10 10 0 0 1 12 19c-7 0-11-7-11-7a18 18 0 0 1 5-5.94M9.9 4.24A9 9 0 0 1 12 4c7 0 11 7 11 7a18 18 0 0 1-2.16 3.19"/><line x1="2" y1="2" x2="22" y2="22"/></svg>'


def font_css(font_base, fonts):
    if not (font_base and fonts):
        return ''
    fam = "'DeckFont','PingFang SC','PingFang TC','Microsoft YaHei','Heiti TC',sans-serif"
    out = ''
    if fonts.get('regular'):
        out += (f"@font-face{{font-family:'DeckFont';src:url('{font_base}/{fonts['regular']}') "
                f"format('woff2');font-weight:400 500;font-display:swap}}")
    if fonts.get('bold'):
        out += (f"@font-face{{font-family:'DeckFont';src:url('{font_base}/{fonts['bold']}') "
                f"format('woff2');font-weight:600 900;font-display:swap}}")
    out += f"html,body{{font-family:{fam}}}.ln{{font-family:{fam}}}"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('manifest')
    ap.add_argument('--out', default='index.html')
    ap.add_argument('--title', default=None)
    ap.add_argument('--faas', default=None, help='FaaS storage URL for shared, cross-device persistence (see references/backend-persistence.md)')
    ap.add_argument('--xl-default', action='store_true', help='load in 翻译模式 (visible text) so Chrome offers Translate at load')
    ap.add_argument('--native-text', action='store_true',
                    help='Default to NATIVE-TEXT view: show the no-text background + the real HTML '
                         'text layer (not the with-text image), so the browser built-in translate '
                         '(right-click → 翻译) can translate the deck into any language. Trades the '
                         'pixel-perfect original render for browser-translatable real text.')
    ap.add_argument('--i18n', default=None,
                    help='translations JSON {sourceText:{h,e,j}} -> adds an in-deck language switch '
                         '(yuanban/zh-Hant/English/Japanese); works inside iframes, no browser-translate needed')
    a = ap.parse_args()
    global _I18N, _I18N_OUT
    if a.i18n:
        _I18N = json.load(open(a.i18n, encoding='utf-8'))
        _I18N_OUT = []
    m = json.load(open(a.manifest, encoding='utf-8'))
    slides = m['slides']
    title = a.title or m.get('title', 'Deck')
    fcss = font_css(m.get('fontBase'), m.get('fonts'))
    faas = a.faas or m.get('faas')
    body = ''.join(render_slide(s, i) for i, s in enumerate(slides))
    thumbs = render_thumbs(slides)
    body_class = 'xl' if a.xl_default else ('native' if a.native_text else '')
    html = (PAGE
            .replace('__TITLE__', H.escape(title))
            .replace('__FONTCSS__', fcss)
            .replace('__BODYCLASS__', body_class)
            .replace('__NATIVE__', 'true' if a.native_text else 'false')
            .replace('__I18N__', json.dumps(_I18N_OUT, ensure_ascii=False).replace('</', '<\\/'))
            .replace('__SLIDES__', body)
            .replace('__THUMBS__', thumbs)
            .replace('__NPAGES__', str(len(slides)))
            .replace('__FAAS__', json.dumps(faas)))
    open(a.out, 'w', encoding='utf-8').write(html)
    print(f'wrote {a.out} ({len(html)} bytes, {len(slides)} slides)')


PAGE = r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>__TITLE__</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;background:#000;overflow:hidden;font-family:'PingFang SC','PingFang TC','Microsoft YaHei','Heiti TC',sans-serif}
__FONTCSS__
#stage{position:fixed;inset:0;width:100vw;height:100vh;display:grid;place-items:center}
#deck{position:relative;width:min(100vw,calc(100vh*16/9));height:min(100vh,calc(100vw*9/16));background:#000;container-type:size}
.slide{position:absolute;inset:0;display:none;background:#000}
.slide.cur{display:block}
.bg,.bg-notext{position:absolute;inset:0;width:100%;height:100%;object-fit:fill;user-select:none;-webkit-user-drag:none}
.bg-notext{display:none}
body.edit .bg{display:none}body.edit .bg-notext{display:block}
/* native-text view: show no-text bg + real HTML text layer (translatable by the
   browser's built-in translate). Trades pixel-perfect original render for real text. */
/* DEFAULT: with-text image (pixel-perfect 图2，蓝标题/字体/零色差) + REAL text overlaid
   TRANSPARENT & selectable (复制 / 豆包划词). 点底栏「🌐译文」(body.xl) 才切到可见文字
   给浏览器整页翻译——平时永远是原图，保真。 */
body:not(.edit):not(.xl) .tb:not(.dirty):not(.tb-title){background:none}
body:not(.edit):not(.xl) .tb:not(.dirty):not(.tb-title) .ln,body:not(.edit):not(.xl) .tb:not(.dirty):not(.tb-title) .ln *{color:transparent!important;-webkit-text-fill-color:transparent}
body.xl .bg{display:none}body.xl .bg-notext{display:block}
body.xl .tb{background:none}
/* 金句压暗底（如58页）：可见态下，除 .tb-over 外整页文字调暗，金句保持高亮 */
body.xl .slide.dim-others .tb:not(.tb-over),body.edit .slide.dim-others .tb:not(.tb-over){opacity:.4}
.medialayer{position:absolute;inset:0}
.media-overlay{position:absolute;object-fit:cover;z-index:2}
video.media-overlay{background:#000}
.textlayer{position:absolute;inset:0;z-index:3;pointer-events:none}
body.edit .textlayer{pointer-events:auto}
.tb{position:absolute;display:flex;flex-direction:column;overflow:visible;visibility:visible;
  user-select:text;-webkit-user-select:text;pointer-events:auto;cursor:text;
  background-image:var(--nt);background-repeat:no-repeat;background-size:100cqw 100cqh;background-origin:border-box}
.tbin{width:100%}
.ln{line-height:1.25;white-space:pre-wrap;word-break:break-word;color:#fff;font-weight:500}
.tb.dirty{visibility:visible}
body.edit .tb{visibility:visible;outline:1px dashed rgba(120,180,255,.55);cursor:text;border-radius:2px}
body.edit .tb:hover{outline:1px solid rgba(120,180,255,.95)}
body.edit .tb:focus{outline:2px solid #3a86ff;z-index:99}
.bh{display:none}
body.edit .bh{display:flex;position:absolute;left:-1px;top:-1px;width:20px;height:20px;align-items:center;justify-content:center;background:#3a86ff;color:#fff;font-size:12px;line-height:1;cursor:move;border-radius:3px;z-index:101;user-select:none;-webkit-user-drag:none}
.brh{display:none}
body.edit .brh{display:block;position:absolute;right:-1px;bottom:-1px;width:14px;height:14px;background:#3a86ff;cursor:nwse-resize;border-radius:3px 0 2px 0;z-index:101}
body.edit .tb.box-sel{outline:2px solid #ffb703!important;z-index:100}
body.edit.selact .tb:not(.box-sel) .tbin{opacity:.18;transition:opacity .12s}
#boxtool{position:absolute;z-index:130;display:none;gap:5px}
#boxtool.show{display:flex}
#boxtool button{border:0;border-radius:6px;padding:5px 11px;font-size:13px;cursor:pointer;background:rgba(12,18,32,.96);color:#fff;box-shadow:0 4px 16px rgba(0,0,0,.5)}
#boxtool button:hover{background:#3a86ff}
#bar{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:60;display:flex;flex-wrap:nowrap;gap:8px;align-items:center;
  background:rgba(12,18,32,.82);backdrop-filter:blur(10px);padding:7px 12px;border-radius:999px;box-shadow:0 8px 30px rgba(0,0,0,.45)}
/* 纯净投屏模式：URL 带 #proj / #bare / #clean / #kiosk 时隐藏底部工具栏（含页码栏），投屏只剩正文 */
body.bare #bar{display:none!important}
#bar button{border:0;border-radius:999px;padding:8px 14px;font-size:14px;cursor:pointer;background:rgba(255,255,255,.12);color:#fff;white-space:nowrap}
#bar button:hover{background:rgba(255,255,255,.22)}#bar button.on{background:#3a86ff}
#bar select{border:0;border-radius:999px;padding:8px 12px;font-size:14px;cursor:pointer;background:rgba(255,255,255,.12);color:#fff}#bar select option{color:#111;background:#fff}
#gfont{display:none;align-items:center;gap:5px;color:#cfe0ff;font-size:13px}body.xl:not(.edit) #gfont{display:inline-flex}#gfont .gfl{opacity:.8}
#langsel{display:none}body.xl:not(.edit) #langsel.has-i18n{display:inline-block}
#pagebox{display:inline-flex;align-items:center;gap:7px;white-space:nowrap;color:rgba(255,255,255,.72);font-size:14px;line-height:1;padding:0 4px}
#pagebox .psep{opacity:.45}#pagebox b{font-weight:600;color:rgba(255,255,255,.85)}
#pageinp{width:44px;height:30px;text-align:center;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.22);color:#fff;border-radius:7px;font-size:14px;line-height:1;outline:none;flex:0 0 auto}
#pageinp:focus{background:rgba(58,134,255,.32);border-color:#3a86ff}
#scrim{position:fixed;inset:0;z-index:70;background:rgba(0,0,0,.35);display:none}#scrim.show{display:block}
#toast{position:fixed;left:50%;bottom:70px;transform:translateX(-50%);z-index:90;background:rgba(20,28,44,.95);color:#fff;padding:9px 16px;border-radius:999px;font-size:13px;opacity:0;transition:opacity .2s;pointer-events:none;max-width:80vw}
#toast.show{opacity:1}
#sidebar{position:fixed;top:0;left:0;height:100vh;width:232px;z-index:80;background:rgba(10,14,22,.97);backdrop-filter:blur(12px);box-shadow:6px 0 30px rgba(0,0,0,.4);transform:translateX(-100%);transition:transform .25s ease;overflow-y:auto;padding:14px 12px}
#sidebar.open{transform:none}
#sidebar h4{color:#cfe0ff;font-size:13px;letter-spacing:.1em;margin-bottom:6px;font-weight:600}
#sidebar .hint{color:rgba(255,255,255,.4);font-size:11px;margin:0 0 10px}
.thumb{position:relative;border-radius:6px;overflow:hidden;cursor:pointer;border:2px solid transparent;margin-bottom:8px;aspect-ratio:16/9;background:#000;transition:box-shadow .12s}
.thumb img{width:100%;height:100%;object-fit:cover;display:block;pointer-events:none}
.thumb.active{border-color:#3a86ff}
.thumb.sel{outline:2px solid #ffb703;outline-offset:1px}.thumb.sel .tno{background:#ffb703;color:#1a1a1a;font-weight:700}
.thumb.drag{opacity:.4}.thumb.over{box-shadow:0 -3px 0 0 #3a86ff}
.thumb.hidden img{opacity:.28;filter:grayscale(1)}.thumb.hidden .e-on{display:none}.thumb.hidden .e-off{display:inline-flex}.thumb.hidden .tno{background:rgba(120,40,40,.85)}
.thumb .tno{position:absolute;left:5px;top:3px;background:rgba(0,0,0,.6);color:#fff;font-size:11px;padding:1px 6px;border-radius:8px}
.thumb .eye{position:absolute;right:4px;top:3px;width:24px;height:24px;padding:3px;border:0;border-radius:6px;background:rgba(0,0,0,.55);color:#cfe0ff;cursor:pointer;display:flex;align-items:center;justify-content:center}
.thumb .eye svg{width:100%;height:100%}.thumb .eye .e-off{display:none}.thumb .eye:hover{background:rgba(58,134,255,.8);color:#fff}
.thumb .grip{position:absolute;right:4px;bottom:4px;color:rgba(255,255,255,.45);font-size:12px;cursor:grab;line-height:1}
</style></head>
<body class="__BODYCLASS__">
<script>window.__FAAS=__FAAS__;window.__NATIVE=__NATIVE__;window.__I18N=__I18N__;</script>
<div id="scrim"></div>
<div id="sidebar"><h4>▦ 目录 · 共 __NPAGES__ 页</h4><div class="hint">拖动调整顺序 · ⌘/Ctrl 或 Shift 点击多选后整组拖动 · 点眼睛隐藏</div><div id="thumbs">__THUMBS__</div></div>
<div id="stage"><div id="deck">__SLIDES__</div><div id="boxtool" translate="no"><button data-a="left">左</button><button data-a="center">中</button><button data-a="right">右</button><button data-f="0.9">A-</button><button data-f="1.1">A+</button></div></div>
<div id="toast"></div>
<div id="bar" translate="no">
 <button id="toc" title="目录/跳转">▦ 目录</button>
 <button id="xlbtn" title="【翻译模式】文字可见、可用浏览器「翻译此页」翻成各语言；【高保真】原图最清晰，但浏览器翻译对它无效。点击切换。">🌐 翻译模式（可翻译）</button>
 <select id="langsel" title="内置翻译：用 --i18n 烤进的译文离线切换，沙箱 iframe（如妙笔）里也能用，无需浏览器翻译"><option value="o">语言 · 原版</option><option value="h">繁體</option><option value="e">English</option><option value="j">日本語</option></select>
 <button id="prev">‹</button>
 <span id="pagebox"><input id="pageinp" type="text" inputmode="numeric" value="1"><span class="psep">/</span><b id="pagetot">__NPAGES__</b></span>
 <button id="next">›</button>
 <button id="editbtn" title="按 E 切换">✎ 编辑 (E)</button>
 <span id="gfont" title="整体字号（全局）"><button id="gfdn">A-</button><button id="gfup">A+</button></span>
</div>
<script>
(function(){
 var slides=[].slice.call(document.querySelectorAll('.slide'));
 var tbs=[].slice.call(document.querySelectorAll('.tb'));
 var thumbsWrap=document.getElementById('thumbs');
 var thumbs=[].slice.call(document.querySelectorAll('.thumb'));
 var N=slides.length,ci=0,editing=false;
 var KEY='deck-edits-v1',HKEY='deck-hidden-v1',OKEY='deck-order-v1';
 var FAAS=window.__FAAS||null;
 var orig={};tbs.forEach(function(tb){orig[tb.dataset.id]=tb.querySelector('.tbin').innerHTML;});
 var INIT=window.__INIT||null;
 var hidden={},order=[],positions={},aligns={},manualFit={},sizes={},globalScale=1;
 function normalizeOrder(){var seen={},c=[];order.forEach(function(x){if(x>=0&&x<N&&!seen[x]){seen[x]=1;c.push(x);}});for(var k=0;k<N;k++)if(!seen[k])c.push(k);order=c;}
 var $=function(id){return document.getElementById(id);};
 // 纯净投屏：URL hash 含 proj/bare/clean/kiosk → 隐藏底部工具栏(含页码栏)，投屏只剩正文
 function _bare(){document.body.classList.toggle('bare',/proj|bare|clean|kiosk/i.test(location.hash||''));}
 addEventListener('hashchange',_bare);_bare();
 function toast(s){var t=$('toast');t.textContent=s;t.classList.add('show');clearTimeout(window.__tt);window.__tt=setTimeout(function(){t.classList.remove('show');},2000);}
 function visOrder(){return order.filter(function(i){return !hidden[i];});}
 function loadSlideImgs(sl,full){if(!sl)return;var xl=document.body.classList.contains('xl');sl.querySelectorAll('img[data-src]').forEach(function(im){var nt=im.className.indexOf('bg-notext')>=0;if(full||(xl?nt:!nt)){im.src=im.getAttribute('data-src');im.removeAttribute('data-src');}});}
 function show(idx){if(idx==null)return;if(hidden[idx]){var vo=visOrder();if(!vo.length)return;idx=vo[0];}
   slides[ci].classList.remove('cur');ci=idx;slides[ci].classList.add('cur');
   var vo=visOrder(),pos=vo.indexOf(ci);[pos-2,pos-1,pos,pos+1,pos+2].forEach(function(pp){if(pp>=0&&pp<vo.length)loadSlideImgs(slides[vo[pp]],pp===pos);});$('pageinp').value=(pos+1);$('pagetot').textContent=vo.length;
   thumbs.forEach(function(t){t.classList.toggle('active',+t.dataset.i===ci);});
   slides.forEach(function(sl,k){sl.querySelectorAll('video').forEach(function(v){
     if(k===ci){try{v.currentTime=0;if(v.hasAttribute('autoplay'))v.play();}catch(e){}}else{try{v.pause();}catch(e){}}});});if(window.__deckFit)requestAnimationFrame(window.__deckFit);}
 function go(d){var vo=visOrder(),pos=vo.indexOf(ci);pos=Math.max(0,Math.min(vo.length-1,pos+d));show(vo[pos]);}
 function layoutThumbs(){order.forEach(function(i){thumbsWrap.appendChild(thumbs[i]);});
   var vo=visOrder();thumbs.forEach(function(t){var i=+t.dataset.i,p=vo.indexOf(i);
     t.querySelector('.tno').textContent=p>=0?(p+1):'–';t.classList.toggle('hidden',!!hidden[i]);});}
 function applyEdits(ed){tbs.forEach(function(tb){var v=ed&&ed[tb.dataset.id];if(v!=null&&v!==orig[tb.dataset.id]){tb.querySelector('.tbin').innerHTML=v;tb.classList.add('dirty');}});}
 function applyState(st){st=st||{};if(st.hidden)hidden=st.hidden;if(st.order&&st.order.length)order=st.order;if(st.positions)positions=st.positions;if(st.aligns)aligns=st.aligns;if(st.sizes)sizes=st.sizes;if(st.fontscale)manualFit=st.fontscale;if(st.gscale)globalScale=st.gscale;normalizeOrder();applyEdits(st.edits||{});applyBoxState();applyGlobalFont();layoutThumbs();show(visOrder()[0]);}
 function collectEdits(){var ed={};document.querySelectorAll('.tb.dirty').forEach(function(tb){ed[tb.dataset.id]=tb.querySelector('.tbin').innerHTML;});return ed;}
 function persistAll(silent){if(FAAS){fetch(FAAS,{method:'POST',headers:{'Content-Type':'text/plain'},body:JSON.stringify({edits:collectEdits(),order:order,hidden:hidden,positions:positions,aligns:aligns,sizes:sizes,fontscale:manualFit,gscale:globalScale})}).then(function(r){return r.json();}).then(function(j){if(!silent)toast(j&&j.ok?'已保存（所有人可见最新版）':'保存失败');}).catch(function(){if(!silent)toast('保存失败：检查网络/FaaS');});}else{try{localStorage.setItem(KEY,JSON.stringify(collectEdits()));localStorage.setItem(HKEY,JSON.stringify(hidden));localStorage.setItem(OKEY,JSON.stringify(order));}catch(e){}if(!silent)toast('已保存到本浏览器');}}
 var _sv;function autosave(){clearTimeout(_sv);_sv=setTimeout(function(){persistAll(true);},1500);}
 if(FAAS){fetch(FAAS).then(function(r){return r.json();}).then(function(j){applyState(j&&j.data?j.data:{});}).catch(function(){applyState({});});}
 else{var st={hidden:{},order:[],edits:{}};try{st.hidden=INIT?INIT.hidden:JSON.parse(localStorage.getItem(HKEY)||'{}')}catch(e){}try{st.order=INIT?INIT.order:JSON.parse(localStorage.getItem(OKEY)||'[]')}catch(e){}try{st.edits=INIT?{}:JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){}applyState(st);}
 $('prev').onclick=function(){go(-1)};$('next').onclick=function(){go(1)};
 function jumpTo(n){var vo=visOrder();n=parseInt(n,10);if(isNaN(n)||n<1)n=1;if(n>vo.length)n=vo.length;show(vo[n-1]);}
 $('pageinp').addEventListener('change',function(){jumpTo(this.value);});
 $('pageinp').addEventListener('keydown',function(e){if(e.key==='Enter'){jumpTo(this.value);this.blur();}e.stopPropagation();});
 $('pageinp').addEventListener('focus',function(){this.select();});
 function sb(o){$('sidebar').classList.toggle('open',o);$('scrim').classList.toggle('show',o);}
 $('toc').onclick=function(){sb(!$('sidebar').classList.contains('open'))};$('scrim').onclick=function(){sb(false)};
 var dragSrc=null,sel={},lastIdx=null;
 function markSel(){thumbs.forEach(function(x){x.classList.toggle('sel',!!sel[+x.dataset.i]);});}
 function clearSel(){sel={};markSel();}
 function rangeSel(a,b){var pa=order.indexOf(a),pb=order.indexOf(b);if(pa<0||pb<0)return;if(pa>pb){var t=pa;pa=pb;pb=t;}sel={};for(var k=pa;k<=pb;k++)sel[order[k]]=true;markSel();}
 thumbs.forEach(function(t){
   t.onclick=function(e){var i=+t.dataset.i;
     if(e.metaKey||e.ctrlKey){if(sel[i])delete sel[i];else sel[i]=true;lastIdx=i;markSel();e.stopPropagation();return;}
     if(e.shiftKey&&lastIdx!=null){rangeSel(lastIdx,i);e.stopPropagation();return;}
     clearSel();lastIdx=i;show(i);sb(false);};
   t.querySelector('.eye').onclick=function(ev){ev.stopPropagation();var k=+t.dataset.i;
     if(hidden[k])delete hidden[k];else hidden[k]=true;persistAll(true);layoutThumbs();
     if(hidden[k]&&k===ci)go(1);else show(ci);toast(hidden[k]?'已隐藏该页':'已恢复显示');};
   t.addEventListener('dragstart',function(e){var i=+t.dataset.i;if(!sel[i])clearSel();dragSrc=t;t.classList.add('drag');e.dataTransfer.effectAllowed='move';});
   t.addEventListener('dragend',function(){t.classList.remove('drag');thumbs.forEach(function(x){x.classList.remove('over');});});
   t.addEventListener('dragover',function(e){e.preventDefault();if(t!==dragSrc)t.classList.add('over');});
   t.addEventListener('dragleave',function(){t.classList.remove('over');});
   t.addEventListener('drop',function(e){e.preventDefault();t.classList.remove('over');if(!dragSrc)return;var to=+t.dataset.i;
     var grp=Object.keys(sel).length>=2?order.filter(function(x){return sel[x];}):[+dragSrc.dataset.i];
     if(grp.indexOf(to)>=0)return;order=order.filter(function(x){return grp.indexOf(x)<0;});
     order.splice.apply(order,[order.indexOf(to),0].concat(grp));persistAll(true);
     clearSel();layoutThumbs();show(ci);toast('已调整顺序（'+grp.length+' 页）');});
 });
 function setEdit(on){editing=on;document.body.classList.toggle('edit',on);$('editbtn').classList.toggle('on',on);
   $('editbtn').textContent=on?'✓ 完成 (E)':'✎ 编辑 (E)';
   tbs.forEach(function(tb){var inner=tb.querySelector('.tbin');if(on){inner.setAttribute('contenteditable','true');inner.spellcheck=false;}else inner.removeAttribute('contenteditable');});
   if(!on){clearBoxSel();persistAll(true);}toast(on?'编辑：点文字改 · 点左上✥选框（可连点多选）· 拖✥移动 · 左/中/右对齐、A±字号对所选生效 · 退出自动保存':'已退出编辑（已自动保存）');}
 $('editbtn').onclick=function(){setEdit(!editing)};
 document.addEventListener('input',function(e){var tb=e.target.closest&&e.target.closest('.tb');if(tb){tb.classList.toggle('dirty',tb.querySelector('.tbin').innerHTML!==orig[tb.dataset.id]);if(FAAS)autosave();}});
 // ---- box editing: ✥ handle = select + drag-move; toolbar = align ----
 var selBoxes=[],boxtool=$('boxtool');
 function placeTool(){var tb=selBoxes[selBoxes.length-1];if(!boxtool||!tb){if(boxtool)boxtool.classList.remove('show');return;}var r=tb.getBoundingClientRect(),sr=$('stage').getBoundingClientRect();boxtool.style.left=Math.max(2,r.left-sr.left)+'px';boxtool.style.top=Math.max(2,r.top-sr.top-34)+'px';boxtool.classList.add('show');}
 function clearBoxSel(){selBoxes.forEach(function(t){t.classList.remove('box-sel');});selBoxes=[];if(boxtool)boxtool.classList.remove('show');document.body.classList.remove('selact');}
 function selectBox(tb,add){if(add){var i=selBoxes.indexOf(tb);if(i>=0){selBoxes.splice(i,1);tb.classList.remove('box-sel');}else{selBoxes.push(tb);tb.classList.add('box-sel');}}else{selBoxes.forEach(function(t){if(t!==tb)t.classList.remove('box-sel');});selBoxes=[tb];tb.classList.add('box-sel');}placeTool();document.body.classList.toggle('selact',selBoxes.length>0);}
 function applyBoxState(){tbs.forEach(function(tb){var id=tb.dataset.id;var p=positions[id];if(p&&p.l&&p.t){tb.style.left=p.l;tb.style.top=p.t;tb.style.backgroundPosition='-'+p.l+' -'+p.t;}var sz=sizes[id];if(sz){if(sz.w)tb.style.width=sz.w;if(sz.h)tb.style.height=sz.h;}var a=aligns[id];if(a)tb.querySelectorAll('.ln').forEach(function(l){l.style.textAlign=a;});if(manualFit[id]!=null)tb.style.setProperty('--fit',manualFit[id]);});}
 tbs.forEach(function(tb){var bh=tb.querySelector('.bh');
   if(bh)bh.addEventListener('mousedown',function(e){if(!editing)return;e.preventDefault();e.stopPropagation();
     var dr=$('deck').getBoundingClientRect(),sx=e.clientX,sy=e.clientY,moved=false,grp=null;
     function mm(ev){if(!moved){if(Math.abs(ev.clientX-sx)<3&&Math.abs(ev.clientY-sy)<3)return;moved=true;if(selBoxes.indexOf(tb)<0)selectBox(tb,false);grp=selBoxes.map(function(t){return {t:t,l:parseFloat(t.style.left)||0,tp:parseFloat(t.style.top)||0};});}
       var dx=(ev.clientX-sx)/dr.width*100,dy=(ev.clientY-sy)/dr.height*100;grp.forEach(function(o){var nl=Math.max(0,Math.min(98,o.l+dx)),nt=Math.max(0,Math.min(98,o.tp+dy));o.t.style.left=nl.toFixed(3)+'cqw';o.t.style.top=nt.toFixed(3)+'cqh';o.t.style.backgroundPosition='-'+o.t.style.left+' -'+o.t.style.top;});placeTool();}
     function mu(){document.removeEventListener('mousemove',mm);document.removeEventListener('mouseup',mu);if(moved){grp.forEach(function(o){positions[o.t.dataset.id]={l:o.t.style.left,t:o.t.style.top};});persistAll(true);}else{selectBox(tb,true);}}
     document.addEventListener('mousemove',mm);document.addEventListener('mouseup',mu);});
   var brh=tb.querySelector('.brh');
   if(brh)brh.addEventListener('mousedown',function(e){if(!editing)return;e.preventDefault();e.stopPropagation();if(selBoxes.indexOf(tb)<0)selectBox(tb,false);
     var dr=$('deck').getBoundingClientRect(),sx=e.clientX,sy=e.clientY,sw=parseFloat(tb.style.width)||tb.getBoundingClientRect().width/dr.width*100,sh=parseFloat(tb.style.height)||tb.getBoundingClientRect().height/dr.height*100,moved=false;
     function mm(ev){moved=true;var nw=Math.max(4,sw+(ev.clientX-sx)/dr.width*100),nh=Math.max(2,sh+(ev.clientY-sy)/dr.height*100);tb.style.width=nw.toFixed(3)+'cqw';tb.style.height=nh.toFixed(3)+'cqh';placeTool();}
     function mu(){document.removeEventListener('mousemove',mm);document.removeEventListener('mouseup',mu);if(moved){sizes[tb.dataset.id]={w:tb.style.width,h:tb.style.height};if(window.__deckFit)window.__deckFit();persistAll(true);}}
     document.addEventListener('mousemove',mm);document.addEventListener('mouseup',mu);});});
 if(boxtool)[].slice.call(boxtool.querySelectorAll('button')).forEach(function(b){b.addEventListener('mousedown',function(e){e.preventDefault();e.stopPropagation();if(!selBoxes.length)return;
   if(b.hasAttribute('data-a')){var a=b.getAttribute('data-a');selBoxes.forEach(function(cb){cb.querySelectorAll('.ln').forEach(function(l){l.style.textAlign=a;});aligns[cb.dataset.id]=a;});}
   else if(b.hasAttribute('data-f')){var f=parseFloat(b.getAttribute('data-f'));selBoxes.forEach(function(cb){var id=cb.dataset.id,c=parseFloat(manualFit[id]||getComputedStyle(cb).getPropertyValue('--fit'))||1,nf=Math.max(0.3,Math.min(2.5,c*f));manualFit[id]=nf.toFixed(3);cb.style.setProperty('--fit',manualFit[id]);});}
   persistAll(true);});});
 document.addEventListener('mousedown',function(e){if(editing&&selBoxes.length&&boxtool&&!boxtool.contains(e.target)&&!e.target.closest('.bh')&&!e.target.closest('.brh')&&selBoxes.indexOf(e.target.closest('.tb'))<0)clearBoxSel();},true);
 function applyGlobalFont(){var d=document.getElementById('deck');if(d)d.style.setProperty('--gfit',globalScale);}
 if($('gfdn'))$('gfdn').onclick=function(){globalScale=Math.max(0.3,+(globalScale*0.92).toFixed(3));applyGlobalFont();persistAll(true);toast('页面字号 '+Math.round(globalScale*100)+'%');};
 if($('gfup'))$('gfup').onclick=function(){globalScale=Math.min(3,+(globalScale*1.08).toFixed(3));applyGlobalFont();persistAll(true);toast('页面字号 '+Math.round(globalScale*100)+'%');};
 if($('xlbtn'))$('xlbtn').onclick=function(){var on=document.body.classList.toggle('xl');$('xlbtn').textContent=on?'🌐 翻译模式（可翻译）':'🖼 高保真（不可翻译）';$('xlbtn').classList.toggle('on',on);var cur=document.querySelector('.slide.cur');if(cur)loadSlideImgs(cur,true);toast(on?'已进入翻译模式：文字可见，可用浏览器「翻译此页」翻成各语言':'已进入高保真（原图最清晰）——此模式不能用浏览器翻译，需翻译请切回「翻译模式」');};
 document.addEventListener('keydown',function(e){
   if(e.target.isContentEditable){if(e.key==='Escape')e.target.blur();return;}
   if(e.key==='e'||e.key==='E'){e.preventDefault();setEdit(!editing);}
   else if(e.key==='f'||e.key==='F'){e.preventDefault();var de=document.documentElement;if(document.fullscreenElement){(document.exitFullscreen||function(){}).call(document);}else{(de.requestFullscreen||de.webkitRequestFullscreen||function(){}).call(de);}}
   else if(e.key==='ArrowRight'||e.key==='PageDown'||e.key===' ')go(1);
   else if(e.key==='ArrowLeft'||e.key==='PageUp')go(-1);
   else if(e.key==='Home'){var v=visOrder();if(v.length)show(v[0]);}
   else if(e.key==='End'){var v=visOrder();if(v.length)show(v[v.length-1]);}
   else if(e.key==='Escape'){if(editing)setEdit(false);sb(false);}});
 // needed shrink scale for one box at current --fit
 function need(tb){var inner=tb.querySelector('.tbin');if(!inner||!tb.clientHeight)return 1;
  var cs=getComputedStyle(tb),aH=tb.clientHeight-parseFloat(cs.paddingTop)-parseFloat(cs.paddingBottom),aW=tb.clientWidth-parseFloat(cs.paddingLeft)-parseFloat(cs.paddingRight);
  if(inner.scrollHeight<=aH+1&&inner.scrollWidth<=aW+1)return 1;
  var s=Math.min(aH/(inner.scrollHeight||1),aW/(inner.scrollWidth||1))*0.97;return s<0.65?0.65:s;}
 // GROUPED autofit: same-size boxes on a slide shrink by the SAME factor (keeps 同级字号一致)
 window.__deckFit=function(){
  var cur=document.querySelector('.slide.cur');if(!cur)return;
  var tbz=[].slice.call(cur.querySelectorAll('.tb'));
  tbz.forEach(function(tb){var id=tb.dataset.id;tb.style.setProperty('--fit',manualFit[id]!=null?manualFit[id]:'1');});
  requestAnimationFrame(function(){requestAnimationFrame(function(){
   tbz.forEach(function(tb){var id=tb.dataset.id;if(manualFit[id]!=null||tb.classList.contains('tb-title'))return;var f=need(tb);tb.style.setProperty('--fit',f<0.999?f.toFixed(3):'1');});
  });});
 };
 // auto-detect Chrome whole-page translation -> reveal visible text; revert when off
 var root=document.documentElement,tid;
 function check(){var on=/translated-(ltr|rtl)/.test(root.className)||!!document.querySelector('#deck font');
  if(document.body.classList.contains('translated')!==on)document.body.classList.toggle('translated',on);
  }
 function sched(){clearTimeout(tid);tid=setTimeout(check,150);}
 new MutationObserver(sched).observe(root,{attributes:true,attributeFilter:['class','lang']});
 var dk=document.getElementById('deck');if(dk)new MutationObserver(sched).observe(dk,{childList:true,subtree:true});
 addEventListener('resize',function(){clearTimeout(window.__fitT);window.__fitT=setTimeout(function(){if(window.__deckFit)window.__deckFit();},200);});
 // ---- in-deck language switch (内置翻译)：用 build --i18n 烤进的 window.__I18N 按 data-i 换 .ln 文字；
 // 离线、沙箱 iframe（妙笔 html-box）里也能用，与浏览器整页翻译互补。只在翻译态(xl)可见且文字可见时有意义。----
 var I18N=window.__I18N||[];
 var i18nLns=[].slice.call(document.querySelectorAll('.ln[data-i]'));
 i18nLns.forEach(function(l){l.setAttribute('data-o',l.innerHTML);});
 if(I18N.length&&$('langsel')){$('langsel').classList.add('has-i18n');
   $('langsel').onchange=function(){var c=this.value;i18nLns.forEach(function(l){var r=I18N[+l.getAttribute('data-i')]||{};if(c==='o'||!r[c])l.innerHTML=l.getAttribute('data-o');else l.textContent=r[c];});
     // 内置优先：选了内置语言 -> 给 deck 打 translate=no，挡掉浏览器二次翻译；切回「原版」-> 放开，
     // 允许顶层环境(妙搭/本地)用浏览器翻译长尾小语种。妙笔沙箱 iframe 里浏览器翻译本就无效，只剩内置。
     var dk=$('deck');if(c==='o')dk.removeAttribute('translate');else dk.setAttribute('translate','no');
     if(window.__deckFit)window.__deckFit();};}
 check();
})();
</script>
</body></html>'''


if __name__ == '__main__':
    main()
