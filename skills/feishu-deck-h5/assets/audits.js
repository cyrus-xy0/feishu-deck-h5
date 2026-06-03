// audits.js — 统一校验引擎 · 单规则源 (UNIFY-VALIDATE-ARCH-2026-06-03, 步骤 2)
// ---------------------------------------------------------------------------
// 设计:所有规则都是"对渲染后 DOM 求值的函数"。每条规则 =
//   { id, severity, evaluate(slide, ctx) -> findings[] }
// 注入到 headless 浏览器里渲染好的 deck,返回一份扁平 findings 列表(每条自带
// rule/severity/slide_idx/message),不再分 static/visual 两套注册表、两种语言。
// 调速靠 scope(只算改动的几帧 vs 全 deck),由 runner(run-audits.py)传入。
//
// 步骤 2 只迁一条做验证闭环:R-VIS-CANVAS-CENTER —— 几何从 visual-audit.js 的
// `canvas_center` producer 逐字移植,finding 文案从 validate.py 的消费段并进来,
// 规则逻辑 + 文案首次合到一处(以前几何在 JS、文案在 Python)。后续步骤逐条迁入
// 此文件,改规则永远只动这一个文件。
//
// 注入约定(与 visual-audit.js 一致):runner 先设 window.__AUDIT_SCOPE__(1-based
// 帧号数组,空/缺 = 全 deck),再 page.evaluate(本文件源码),IIFE 返回结果对象:
//   { engine, version, rules:[ruleId...], scope, findings:[{rule,severity,slide_idx,
//     message, ...payload}] }
(function () {
  'use strict';

  // hero-ZONE 集(与 visual-audit.js 同义):这些版式整体是构图页,豁免居中类几何。
  const HERO_LAYOUTS = new Set([
    'cover', 'section', 'big-stat', 'end', 'quote', 'image-text',
  ]);

  // 短选择器(tag.cls.cls),用于 finding 定位。处理 SVG className.baseVal。
  const shortSel = (el) => {
    const tag = el.tagName.toLowerCase();
    const raw = el.className;
    const clsStr = (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || '')).toString();
    const cls = clsStr.split(/\s+/).filter(Boolean);
    return cls.length ? `${tag}.${cls.join('.')}` : tag;
  };

  // 元素是否有自己的直接文本(不只是子元素)。
  const hasOwnText = (el) => {
    for (const n of el.childNodes) {
      if (n.nodeType === 3 && n.textContent.trim()) return true;
    }
    return false;
  };

  // 元素自己 + 任一祖先(至 slide 边界)的全部 class 列表(用于 chrome-class /
  // hero 类豁免:与 _validate_audits.py 里"selector 命中某 chrome class"等价 ——
  // 渲染后没有 selector,改成沿元素的 class 链查同义类)。
  const classChain = (el, slide) => {
    const out = [];
    for (let p = el; p && p !== slide.parentElement; p = p.parentElement) {
      const raw = p.className;
      const s = (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || '')).toString();
      for (const c of s.split(/\s+/)) if (c) out.push(c);
      if (p === slide) break;
    }
    return out;
  };

  // 把 getComputedStyle().boxShadow 的规范串拆成逐层(顶层逗号分层;rgba()/hsl()
  // 内的逗号不分)。与 _validate_audits.py audit_no_drop_shadows 的手写 depth 拆分等价。
  const splitShadowLayers = (value) => {
    const layers = [];
    let depth = 0, buf = '';
    for (const ch of value) {
      if (ch === '(') { depth += 1; buf += ch; }
      else if (ch === ')') { depth = Math.max(0, depth - 1); buf += ch; }
      else if (ch === ',' && depth === 0) { layers.push(buf.trim()); buf = ''; }
      else buf += ch;
    }
    if (buf.trim()) layers.push(buf.trim());
    return layers;
  };

  // R12 单层判定。computed 规范串色在前(`rgba(...) Xpx Ypx Blurpx Spreadpx [inset]`)。
  //   inset → 内阴影,豁免(对应 _BOX_SHADOW_INSET_RE)。
  //   offset-x/y/blur 三者皆 0 → glow-ring,豁免(对应 ^0 0 0,spread 允许非零)。
  //   否则 = 有偏移/模糊的真投影。
  const shadowLayerIsDrop = (layer) => {
    if (!layer) return false;
    if (/\binset\b/.test(layer)) return false;            // 内阴影层 OK
    // 去掉颜色前缀(rgb/rgba/hsl/hsla/颜色名/#hex),留下 px 数列。
    const nums = (layer.match(/-?\d*\.?\d+px/g) || []).map((s) => parseFloat(s));
    if (nums.length < 3) return false;                    // 解析不出 → 不误报
    const [ox, oy, blur] = nums;
    if (ox === 0 && oy === 0 && blur === 0) return false;  // 0 0 0 ... glow-ring 层
    return true;                                          // 有偏移/模糊 → 真投影
  };

  // R-ESC-HTML:被转义后渲染成可见文本的 HTML 标签集(与 _validate_audits.py
  // _ESC_TAGS 同表)。渲染后 DOM 里 `&lt;span class=` 已解码成可见文本 `<span class=`,
  // 所以这里用字面 < > 而非 &lt; &gt;。
  const ESC_TAGS = 'span|b|i|em|strong|div|p|br|h[1-6]|ul|ol|li|a|svg|img|small|sup|sub|mark|code';
  const ESCAPED_TAG_RE = new RegExp(
    '<\\/?(?:' + ESC_TAGS + ')\\s*\\/?>'            // (A) <br> </span> <b> <br/>
    + '|<(?:' + ESC_TAGS + ')\\s+[a-zA-Z][\\w-]*\\s*=', // (B) <span class= / <a href=
    'i');

  // R-WHITE-TEXT:chrome 类(meta 文本,豁免)。与 _validate_audits.py 的 chrome_class_re 同集。
  const WHITE_CHROME_CLASSES = new Set([
    'eyebrow', 'footnote', 'pageno', 'caption', 'source', 'source-footer',
    'deck-pageno', 'nav-hint', 'mode-toggle', 'deck-ui', 'deck-controls',
    'deck-progress', 'attrib', 'sc-cap', 'axis-cap',
  ]);

  // 这个 styleSheet 是否"框架/外部"源?R-WHITE-TEXT 原版 `include_framework=False`
  // 只查作者 CSS —— 框架 master-spec 规则自带 allow:white-opacity 审查、豁免。等价判定:
  //   ① ownerNode data-source="framework"  ② href 命中 feishu-deck(-patterns).css
  //   ③ cssRules 读取抛错(file:// 下外链被 CORS 挡)→ 当框架/外部处理(不查)。
  const sheetIsFramework = (ss) => {
    if (!ss) return true;
    const n = ss.ownerNode;
    if (n && n.getAttribute && n.getAttribute('data-source') === 'framework') return true;
    if (ss.href && /feishu-deck(-patterns)?\.css/.test(ss.href)) return true;
    try { void ss.cssRules; } catch (e) { return true; }
    return false;
  };

  // R-WHITE-TEXT chrome class 选择器判定(对应 _validate_audits.py chrome_class_re)——
  // 作用在 selector 文本上(原版同样在 selector 上判 chrome 类)。
  const WHITE_CHROME_SEL_RE = new RegExp(
    '\\.(?:' + [...WHITE_CHROME_CLASSES].join('|') + ')(?![\\w-])');
  // 低透明纯白的 color: 声明(CSS 源文本判定,对应 soft_white_re)。
  const SOFT_WHITE_DECL_RE =
    /(?:^|[^-\w])color:\s*rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*(?:0?\.\d+|0)\s*\)/i;
  const FS_PX_RE = /font-size:\s*(\d+)px/;

  // 收集"作者 CSS"里命中 R-WHITE-TEXT 的规则(选择器 → 该规则触发)。整 deck 算一次,
  // 缓存在 window 上(driver 按 slide 调规则,但 CSSOM 是 deck 级)。每条规则做与原版
  // 完全一致的规则级判定:selector 含 .slide/.card/.col、非 chrome 类、无 allow:white-opacity、
  // 规则自身 font-size>14、声明里有低透明纯白 color。返回 [{selectorText, decl}]。
  const collectAuthorSoftWhiteRules = () => {
    if (typeof window !== 'undefined' && window.__WT_AUTHOR_RULES__) {
      return window.__WT_AUTHOR_RULES__;
    }
    const out = [];
    const sheets = (typeof document !== 'undefined' && document.styleSheets) || [];
    for (const ss of sheets) {
      if (sheetIsFramework(ss)) continue;          // 只查作者 CSS
      let rules;
      try { rules = ss.cssRules; } catch (e) { continue; }
      const walk = (ruleList) => {
        for (const r of ruleList) {
          // @media 等:原版把 @media 嵌套规则按 1920×1080 视口决定是否审计;这里 CSSOM
          // 下 .slide 是固定画布,统一钻进去(与原版"会激活的 @media 解包后审计"一致方向)。
          if (r.cssRules && (r.type === 4 || r.type === 12)) { walk(r.cssRules); continue; }
          if (r.type !== 1 || !r.style) continue;  // 只看 style rule
          const selector = r.selectorText || '';
          if (selector.indexOf('.slide') < 0 && selector.indexOf('.card') < 0
              && selector.indexOf('.col') < 0) continue;
          if (WHITE_CHROME_SEL_RE.test(selector)) continue;   // chrome 类豁免
          const cssText = r.style.cssText || '';
          // allow:white-opacity opt-out —— cssText 不含注释,改用 data-* 属性 opt-out
          //（见下面 evaluate 的 data-allow-white-opacity 链),此处对应原版注释 marker 已无法读取。
          const fsM = FS_PX_RE.exec(cssText);
          if (fsM && parseInt(fsM[1], 10) <= 14) continue;    // 规则自身 chrome floor 豁免
          if (!SOFT_WHITE_DECL_RE.test(cssText)) continue;
          out.push({ selectorText: selector, decl: (r.style.color || '') });
        }
      };
      walk(rules);
    }
    if (typeof window !== 'undefined') window.__WT_AUTHOR_RULES__ = out;
    return out;
  };

  // ==========================================================================
  //  规则注册表 —— 唯一规则源。新增规则 = 往这里加一个 (slide, ctx) => findings。
  // ==========================================================================
  const RULES = [
    {
      // R-VIS-CANVAS-CENTER · 内容并集相对"画布"垂直居中 (2026-05-31)
      // 画布 = [主标题 .header 底边 → 屏幕底 1080];内容并集(排除 .header / 绝对定位 /
      // 隐藏 / 过小 / 被裁)的垂直中心 content_mid 应 ≈ 画布中心 (hb+1080)/2。
      //   offset = canvas_mid - content_mid   (>0 偏上, <0 偏下)
      //   is_full = 内容比可用带还高 → 居中必溢出画布 → 顶对齐是对的,豁免。
      // |offset| > 40 判失衡(warn,留白判断主观,可 data-allow-imbalance opt-out)。
      // 几何全部先减 slide 顶、再 / scale 还原成设计 px,与 1080 同系。
      id: 'R-VIS-CANVAS-CENTER',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, scale, isHeroLayout } = ctx;
        if (isHeroLayout || slide.hasAttribute('data-allow-imbalance')) return [];

        const _ccSr = slide.getBoundingClientRect();
        const _ccSlideTop = _ccSr.top;
        const ccHeader = slide.querySelector(':scope > .header');
        const ccHeaderRendered = !!ccHeader && ccHeader.getClientRects().length > 0;
        const _ccHb = ccHeaderRendered
          ? (ccHeader.getBoundingClientRect().bottom - _ccSlideTop) / scale
          : 0;

        let ccTop = Infinity, ccBot = -Infinity, ccAny = false;
        slide.querySelectorAll('*').forEach((el) => {
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return;
          if (ccHeader && (el === ccHeader || ccHeader.contains(el))) return;
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return;
          if (cs.position === 'absolute' || cs.position === 'fixed') return;
          const tag = el.tagName;
          const isMedia = tag === 'IMG' || tag === 'SVG' || tag === 'svg'
            || tag === 'CANVAS' || tag === 'VIDEO';
          const isLeaf = el.children.length === 0;
          if (!hasOwnText(el) && !isMedia && !isLeaf) return;
          const r = el.getBoundingClientRect();
          if (r.width < 6 || r.height < 6) return;
          // 被 overflow:hidden 祖先裁掉的内容不算可见 —— 与每个非可见溢出祖先求交,
          // 完全被裁则丢弃(否则手机 mock 超出框的聊天/输入条会把并集拉低)。
          let vt = r.top, vb = r.bottom;
          for (let p = el.parentElement; p && p !== slide; p = p.parentElement) {
            if (getComputedStyle(p).overflowY !== 'visible') {
              const pr = p.getBoundingClientRect();
              if (pr.top > vt) vt = pr.top;
              if (pr.bottom < vb) vb = pr.bottom;
            }
          }
          if (vb - vt < 6) return;
          const t = (vt - _ccSlideTop) / scale;
          const b = (vb - _ccSlideTop) / scale;
          if (t < ccTop) ccTop = t;
          if (b > ccBot) ccBot = b;
          ccAny = true;
        });
        if (!ccAny) return [];

        const contentMid = (ccTop + ccBot) / 2;
        const canvasMid = (_ccHb + 1080) / 2;
        const offset = canvasMid - contentMid;        // >0 偏上, <0 偏下
        const contentH = ccBot - ccTop;
        const bandH = 1080 - _ccHb;
        // is_full = 内容并集确实高过可用带 → 无法不溢出地居中 → 顶对齐/溢出是对的,豁免。
        const isFull = bandH <= 8 || contentH > (bandH - 8);

        const content_mid = Math.round(contentMid);
        const canvas_mid = Math.round(canvasMid);
        const off = Math.round(offset);

        if (isFull) return [];
        if (Math.abs(off) <= 40) return [];

        const container_sel = shortSel(slide);
        const dir = off > 0 ? '偏上' : '偏下';
        return [{
          rule: 'R-VIS-CANVAS-CENTER',
          severity: 'warn',
          slide_idx,
          container_sel,
          offset: off,
          content_mid,
          canvas_mid,
          is_full: false,
          top: Math.round(ccTop),
          bot: Math.round(ccBot),
          hb: Math.round(_ccHb),
          message:
            `slide ${slide_idx} · \`${container_sel}\` 内容整体未在[标题底→屏幕底]` +
            `画布垂直居中:${dir} ${Math.abs(off)}px(内容中心 ${content_mid}px / ` +
            `画布中心 ${canvas_mid}px) —— 内容在 .stage 内部看似均衡,但 .stage 相对` +
            `画布整体偏移,所以全页看着上空/下空。Fix: 让 content 的 .grid \`flex:1\` ` +
            `撑满 stage + \`align-content:center\`(稀疏自动居中、满铺自动顶对齐铺满);` +
            `确属设计意图用 \`data-allow-imbalance\` opt-out。`,
        }];
      },
    },

    {
      // R-ESC-HTML · 被转义的 HTML 标签当可见文本漏出来 (步骤 3 第一批迁自
      // _validate_audits.py audit_escaped_html)。原版扫 slide 源 HTML 里的 `&lt;span`;
      // 渲染后 DOM 已把转义实体解码成可见文本 `<span` —— 等价、更准(只看真正渲染成
      // 文本的那份,raw 页 / `{{{ raw }}}` 输出真标签不会出现在 textContent 里)。
      id: 'R-ESC-HTML',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        // 只看可见文本:textContent 自动排除属性,但会含 <style>/<script> 文本 ——
        // 克隆后剥掉它们,免得 CSS 选择器 / JS 串里的 `<span ...>` 误报(对应原版剥
        // <style>/<script>)。
        const clone = slide.cloneNode(true);
        clone.querySelectorAll('style, script').forEach((n) => n.remove());
        const text = clone.textContent || '';
        const m = ESCAPED_TAG_RE.exec(text);
        if (!m) return [];
        const sample = m[0];
        return [{
          rule: 'R-ESC-HTML',
          severity: 'error',
          slide_idx,
          sample,
          message:
            `slide ${slide_idx}: 文本里出现被转义的 HTML 标签(如 \`${sample}…\`)。` +
            '裸 HTML 进了 schema 的转义文本字段(content/3up 等的 lede / body / ' +
            'title 走 `{{ field }}`,会被 _esc_br 转义),所以原样显示成"乱码"。' +
            '修法:把这页改成 `layout: raw` 自己控 markup(行内高亮 / svg 都放这),' +
            '或去掉标签改用该字段支持的强调方式;换行用 \\n(渲染器会转 <br>),' +
            '不要写字面 <br>。raw 页 / `{{{ raw }}}` 字段输出的是真标签、不会变 ' +
            '&lt;,因此不会被本规则误报。',
        }];
      },
    },

    {
      // R12 · slide 内容不许真投影 (步骤 3 第一批迁自 _validate_audits.py
      // audit_no_drop_shadows)。原版扫 `.slide…{ box-shadow }` CSS 规则;渲染后改成
      // 遍历 .slide 下元素(含 ::before/::after)的 computed box-shadow,逐层判定:
      // inset / glow-ring(0 0 0)豁免,有偏移/模糊 = 真投影。
      // 原 CSS 注释 opt-out `/* allow:drop-shadow */` 在 computed 里看不到(注释不进
      // 样式),改为:① UI-mock 窗体类(.ui-window/.phone-frame/.desktop-frame 等)豁免
      // ② `data-allow-drop-shadow` 属性 opt-out(就近祖先链)。
      id: 'R12',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const UI_MOCK = ['ui-window', 'phone-frame', 'desktop-frame', 'browser-frame', 'app-frame'];
        const findings = [];
        const flaggedSel = new Set();   // 同一 selector(短选择器)一页只报一次,降噪
        const all = [slide, ...slide.querySelectorAll('*')];
        for (const el of all) {
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') continue;
          const chain = classChain(el, slide);
          if (chain.some((c) => UI_MOCK.includes(c))) continue;          // UI-mock 窗体豁免
          let optOut = false;
          for (let p = el; p && p !== slide.parentElement; p = p.parentElement) {
            if (p.hasAttribute && p.hasAttribute('data-allow-drop-shadow')) { optOut = true; break; }
          }
          if (optOut) continue;
          for (const pseudo of [null, '::before', '::after']) {
            const cs = getComputedStyle(el, pseudo);
            // ::before/::after 没 content 不渲染 → 跳过(避免幽灵伪元素的默认 shadow)。
            if (pseudo) {
              const c = cs.content;
              if (!c || c === 'none' || c === 'normal') continue;
            }
            const bs = cs.boxShadow;
            if (!bs || bs === 'none') continue;
            for (const layer of splitShadowLayers(bs)) {
              if (shadowLayerIsDrop(layer)) {
                const sel = shortSel(el) + (pseudo || '');
                if (flaggedSel.has(sel)) break;
                flaggedSel.add(sel);
                findings.push({
                  rule: 'R12',
                  severity: 'warn',
                  slide_idx,
                  container_sel: sel,
                  message:
                    `slide ${slide_idx}: real drop shadow on \`${sel}\` — ` +
                    `\`box-shadow: ${layer}\` (use hairline + contrast instead, OR ` +
                    'opt out with data-allow-drop-shadow if this is a UI-mock window ' +
                    'chrome that legitimately needs depth shadow)',
                });
                break;   // one finding per rule/element is enough
              }
            }
          }
        }
        return findings;
      },
    },

    {
      // R49 · 青(#24C3FF)只能做行内高亮,绝不当 slide accent (步骤 3 第一批迁自
      // _validate_audits.py audit_no_cyan_accent)。原版扫 slide markup 里的
      // `data-accent="cyan"`;渲染后等价 querySelectorAll('[data-accent="cyan"]')。
      id: 'R49',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const hit = slide.matches('[data-accent="cyan"]')
          || slide.querySelector('[data-accent="cyan"]');
        if (!hit) return [];
        return [{
          rule: 'R49',
          severity: 'error',
          slide_idx,
          message:
            `slide ${slide_idx}: data-accent="cyan" — cyan #24C3FF is reserved for ` +
            'inline word highlight (.accent-text / .hl), never as the slide ' +
            'accent. Use blue / teal / purple / violet / orange instead.',
        }];
      },
    },

    {
      // R-BULLET-DASH · 自搓 dash 形 li::before bullet(应改用 .feature-list)。(步骤 3
      // 第一批迁自 _validate_audits.py audit_bullet_dash)。原版扫作者 CSS 里
      // `li::before { width:Npx; height:Mpx }` 且 w>=4 && h<=3 && w>=3h;渲染后改成读
      // 每个 li 的 ::before computed width/height,同阈值判定。(框架 .feature-list 的
      // 圆点 8×8 不命中。)
      id: 'R-BULLET-DASH',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const findings = [];
        const flaggedSel = new Set();
        slide.querySelectorAll('li').forEach((li) => {
          const cs = getComputedStyle(li, '::before');
          const content = cs.content;
          if (!content || content === 'none') return;   // 无 ::before 渲染
          const w = parseFloat(cs.width);
          const h = parseFloat(cs.height);
          if (!isFinite(w) || !isFinite(h)) return;
          if (w >= 4 && h <= 3 && w >= 3 * h) {
            const sel = shortSel(li) + '::before';
            if (flaggedSel.has(sel)) return;
            flaggedSel.add(sel);
            findings.push({
              rule: 'R-BULLET-DASH',
              severity: 'warn',
              slide_idx,
              container_sel: sel,
              message:
                `slide ${slide_idx}: ad-hoc dash bullet on \`${sel}\` ` +
                `(${w}×${h}px). Framework supplies \`.feature-list\` with branded ` +
                'colored dot bullets (8×8 round + halo). Use ' +
                '`<ul class="feature-list">` instead — see SKILL.md "Component ' +
                'utility classes" section. For multi-color cards, override ' +
                '`.is-<color> li::before { background: var(--fs-<color>) }` per accent.',
            });
          }
        });
        return findings;
      },
    },

    {
      // R-WHITE-TEXT · 暗底正文必须纯白(低透明白投影后发灰)。(步骤 3 第一批迁自
      // _validate_audits.py audit_white_text)。原版只查【作者 CSS】(include_framework=False)
      // 里 selector 含 .slide/.card/.col、非 chrome 类、规则自身 font-size>14、无
      // `/* allow:white-opacity */`、声明含 `color:rgba(255,255,255,<1)` 的规则。
      // 移植:用 CSSOM 取作者源规则(框架 link / data-source=framework 排除),规则级判定
      // 与原版逐字一致;再用 live DOM `querySelectorAll(selector)` 把命中规则归到具体 slide
      // (这样 [data-page=NN] / 继承都按渲染结果解析 —— 渲染基底、更准)。
      // CSS 注释 opt-out 在 CSSOM cssText 里读不到 → 改用 `data-allow-white-opacity` 属性
      // opt-out(就近祖先链),命中即跳过该元素。
      id: 'R-WHITE-TEXT',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const authorRules = collectAuthorSoftWhiteRules();
        if (!authorRules.length) return [];
        const findings = [];
        const flaggedSel = new Set();
        for (const ar of authorRules) {
          let matched;
          try { matched = slide.querySelectorAll(ar.selectorText); }
          catch (e) { continue; }                 // 选择器在本环境无法解析 → 跳过
          // 也可能 selector 命中 slide 自身(如 `.slide[...]`)。
          const candidates = [];
          if (slide.matches && (() => { try { return slide.matches(ar.selectorText); } catch (e) { return false; } })()) {
            candidates.push(slide);
          }
          for (const m of matched) candidates.push(m);
          if (!candidates.length) continue;
          // 整规则对本 slide 命中即报一次(原版每条 CSS 规则一条 finding)。挑首个未被
          // data-allow-white-opacity opt-out 的元素作为定位锚。
          let anchor = null;
          for (const el of candidates) {
            let optOut = false;
            for (let p = el; p && p !== slide.parentElement; p = p.parentElement) {
              if (p.hasAttribute && p.hasAttribute('data-allow-white-opacity')) { optOut = true; break; }
            }
            if (!optOut) { anchor = el; break; }
          }
          if (!anchor) continue;
          const sel = ar.selectorText;
          if (flaggedSel.has(sel)) continue;
          flaggedSel.add(sel);
          const cs = getComputedStyle(anchor);
          findings.push({
            rule: 'R-WHITE-TEXT',
            severity: 'warn',
            slide_idx,
            container_sel: sel,
            color: cs.color,
            message:
              `slide ${slide_idx}: soft-white text on \`${sel}\` — \`${cs.color}\`. ` +
              'Content text on dark slides must be `#fff` or `rgba(255,255,255,1)`. ' +
              'Low-opacity white reads as gray when projected. Use other levers ' +
              'for hierarchy (font-weight, font-size, background tone, border dim). ' +
              'Opt out with data-allow-white-opacity if this is a deliberate ' +
              'chrome exception.',
          });
        }
        return findings;
      },
    },
  ];

  // ==========================================================================
  //  driver —— 遍历 slide(可按 scope 过滤),逐条跑规则,汇总 findings。
  // ==========================================================================
  function run(scope) {
    const scopeSet = (Array.isArray(scope) && scope.length)
      ? new Set(scope.map(Number)) : null;
    const slides = document.querySelectorAll('.slide');
    const findings = [];
    slides.forEach((slide, idx) => {
      const slide_idx = idx + 1;
      if (scopeSet && !scopeSet.has(slide_idx)) return;
      const layout = slide.getAttribute('data-layout') || '';
      const ctx = {
        slide_idx,
        label: slide.getAttribute('data-screen-label') || `slide-${slide_idx}`,
        layout,
        isHeroLayout: HERO_LAYOUTS.has(layout),
        scale: parseFloat(getComputedStyle(slide).getPropertyValue('--fs-scale')) || 1,
        shortSel,
        hasOwnText,
        HERO_LAYOUTS,
      };
      for (const rule of RULES) {
        try {
          const fs = rule.evaluate(slide, ctx) || [];
          for (const f of fs) findings.push(f);
        } catch (e) {
          findings.push({
            rule: rule.id, severity: 'error', slide_idx,
            message: `audit '${rule.id}' threw on slide ${slide_idx}: ${e && e.message}`,
          });
        }
      }
    });
    return {
      engine: 'audits.js',
      version: 1,
      rules: RULES.map((r) => r.id),
      scope: scopeSet ? [...scopeSet] : null,
      slides_total: slides.length,
      findings,
    };
  }

  return run((typeof window !== 'undefined' && window.__AUDIT_SCOPE__) || null);
})();
