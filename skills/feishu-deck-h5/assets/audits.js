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

  // --------------------------------------------------------------------------
  //  步骤 3 第二批共享常量/工具(R-CSSVAR / R10 / R-KEY / R-LANG / R07 / R13 / R38)
  // --------------------------------------------------------------------------

  // class 字符串(含 SVG className.baseVal)→ 规整空格串。
  const classStr = (el) => {
    if (!el) return '';
    const raw = el.className;
    return (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || '')).toString();
  };

  // ── lift / import provenance(对应 _validate_audits.py 的 _slide_is_lifted /
  //    _deck_all_imported / _deck_imported)。渲染后:slide 自身或祖先带 data-lifted
  //    = lifted;<meta name=fs-deck-origin content=imported> 或 全 .slide 都 lifted
  //    = whole-deck imported。
  const slideIsLifted = (slide) => !!(slide && slide.hasAttribute
    && slide.hasAttribute('data-lifted'));

  const deckOriginImported = () => {
    if (typeof document === 'undefined') return false;
    const m = document.querySelector('meta[name="fs-deck-origin"]');
    return !!(m && (m.getAttribute('content') || '').trim().toLowerCase() === 'imported');
  };

  const deckAllImported = () => {
    if (typeof window !== 'undefined' && window.__DECK_ALL_IMPORTED__ !== undefined) {
      return window.__DECK_ALL_IMPORTED__;
    }
    let v;
    if (deckOriginImported()) {
      v = true;
    } else {
      const slides = (typeof document !== 'undefined' && document.querySelectorAll('.slide')) || [];
      v = slides.length > 0 && [...slides].every((s) => slideIsLifted(s));
    }
    if (typeof window !== 'undefined') window.__DECK_ALL_IMPORTED__ = v;
    return v;
  };

  // ── deck 语言模式(对应 audit_language_policy 的 <meta name=fs-language> 解析)。
  const deckLanguageMode = () => {
    if (typeof window !== 'undefined' && window.__DECK_LANG_MODE__) {
      return window.__DECK_LANG_MODE__;
    }
    let mode = 'zh-only';
    if (typeof document !== 'undefined') {
      const m = document.querySelector('meta[name="fs-language"]');
      if (m) {
        const c = (m.getAttribute('content') || '').trim().toLowerCase();
        if (c) mode = c;
      }
    }
    if (typeof window !== 'undefined') window.__DECK_LANG_MODE__ = mode;
    return mode;
  };

  // ── R10 调色板(对应 _validate_common.py ALLOWED_HEX,小写、无 #)。
  const ALLOWED_HEX = new Set([
    'fff', 'ffffff', '000', '000000',
    '3c7fff', '24c3ff', '33d6c0', '5c3ffb', '9f6ff1', 'fe7f00',
    '080c18', '0f1a4a', '060b22', '1a2256', '050817', '04060f', '0a1230', '1b1f3a',
  ]);

  // ── R38 data-decor ship list(对应 _validate_common.py ALLOWED_DECOR)。
  const ALLOWED_DECOR = new Set([
    'violet-glow', 'blue-glow', 'mix-glow', 'teal-glow', 'orange-spark',
    'aurora', 'grain', 'topo', 'flower-bg', 'section-bg', 'photo-bg',
  ]);

  // ── R13 hero-title 版式(对应 _validate_common.py HERO_TITLE_LAYOUTS —— 注意
  //    这与本文件顶部 HERO_LAYOUTS(visual)不同集,big-stat 不在内,见 F-13 注释)。
  const HERO_TITLE_LAYOUTS = new Set(['cover', 'image-text', 'end', 'section', 'quote']);

  // ── R-KEY slug 规则(对应 audit_slide_keys 的三个正则)。
  const KEY_VALID_SLUG_RE = /^[a-z][a-z0-9-]*$/;
  const KEY_POSITIONAL_RE = /^(slide|page|section|frame)-?\d+$/;

  // ── R-LANG 共享:CJK 探测 / 品牌白名单 / 技术码 / chrome-label / 纯拉丁 UC /
  //    布局型父标签 / 图表脚手架类(全部对应 audit_language_policy +
  //    audit_translation_track_pairs + _validate_common 里的同名常量)。
  const CJK_RE = /[一-鿿㐀-䶿豈-﫿]/;
  const LATIN_BRAND_WHITELIST = new Set([
    'AI', 'API', 'HTML', 'CSS', 'JS', 'CLI', 'SDK', 'UI', 'UX',
    'PDF', 'PNG', 'JPG', 'SVG', 'CTA', 'KPI', 'OKR', 'ROI', 'SOP',
    'CXO', 'CEO', 'CTO', 'CFO', 'COO', 'CMO', 'CIO', 'VP', 'BD', 'KA',
    'PR', 'HR', 'IT', 'BG', 'BU',
    'SaaS', 'PaaS', 'IaaS', 'B2B', 'B2C', 'O2O', 'MVP',
    'LBP', 'IDC', 'AWS', 'GCP', 'OEM', 'ODM', 'NPS', 'GMV',
    'Q1', 'Q2', 'Q3', 'Q4', 'H1', 'H2',
    'Lark', 'Feishu', 'Codex', 'Mira', 'Flow', 'Base', 'Wiki',
    'OpenAI', 'Anthropic', 'Claude', 'GPT', 'LLM',
    'ERP', 'CRM', 'WMS', 'PMS', 'MES', 'SCM', 'BI', 'OA', 'POS',
  ]);
  const TECHNICAL_CODE_RE = /^[A-Z]{1,4}\d{1,4}[A-Z]?$/;
  const LATIN_UC_RE = /^[A-Z0-9 ·\-/_&]{2,40}$/;
  // chrome 类名集(对应 chrome_class_text_re 里枚举 + \w+-suffix 族)。判定见 langClassIsChromeLabel。
  const LANG_CHROME_EXACT = new Set([
    'eyebrow', 'kicker', 'pill', 'tag', 'chip', 'badge',
    'nc-tag', 'db-tag', 'dl-eyebrow', 'mode-tag', 'side-pill', 'focus-pill', 'td-owner',
  ]);
  const LANG_CHROME_SUFFIX = ['-tag', '-pill', '-eyebrow', '-chip', '-badge',
    '-en', '-eng', '-english', '-num', '-index', '-ord'];
  const LANG_CHROME_TAGS = new Set(['SPAN', 'P', 'DIV', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6']);
  const LAYOUT_ONLY_PARENT_TAGS = new Set([
    'TR', 'TABLE', 'THEAD', 'TBODY', 'TFOOT',
    'UL', 'OL', 'DL', 'FIGURE', 'SELECT', 'FIELDSET',
  ]);
  const CHART_SCAFFOLD_CLASSES = new Set([
    'x-axis', 'y-axis', 'axis', 'sublabel', 'legend', 'scale', 'tick', 'gridline',
  ]);
  const isChartScaffoldClass = (cls) => !!cls
    && cls.split(/\s+/).some((t) => CHART_SCAFFOLD_CLASSES.has(t));
  // 元素 class 是否命中 chrome-label 类(对应 chrome_class_text_re 的 class 部分)。
  const langClassIsChromeLabel = (el) => {
    if (!LANG_CHROME_TAGS.has(el.tagName)) return false;
    const tokens = classStr(el).split(/\s+/).filter(Boolean);
    return tokens.some((c) =>
      LANG_CHROME_EXACT.has(c) || LANG_CHROME_SUFFIX.some((suf) => c.endsWith(suf)));
  };
  // 该串是否"应翻译的纯拉丁标签"(对应 _is_offending_latin)。
  const langIsOffendingLatin = (text) => {
    const t = (text || '').trim();
    if (!LATIN_UC_RE.test(t)) return false;
    const tokens = t.split(/[\s·\-/_&]+/).filter((x) => x && !/^\d+$/.test(x));
    if (!tokens.length) return false;
    return !tokens.every((x) => LATIN_BRAND_WHITELIST.has(x) || TECHNICAL_CODE_RE.test(x));
  };
  // 元素的"直接文本"(只数直接 text 子节点,排除子元素文本;对应 _walk_text_leaves 的
  // 叶子定义:有直接文本、无元素子节点)。
  const directText = (el) => {
    let s = '';
    for (const n of el.childNodes) {
      if (n.nodeType === 3) s += n.textContent;
    }
    return s.trim();
  };
  const isElementLeaf = (el) => {
    // 叶子 = 无元素子节点(允许文本/void)。<br> 等 void 也算元素子节点会破坏判定 ——
    // 但 _walk_text_leaves 忽略 void 标签,所以这里也排除 void 子元素。
    const VOID = new Set(['BR', 'HR', 'IMG', 'INPUT', 'META', 'LINK', 'SOURCE',
      'AREA', 'BASE', 'COL', 'EMBED', 'PARAM', 'TRACK', 'WBR']);
    for (const c of el.children) {
      if (!VOID.has(c.tagName)) return false;
    }
    return true;
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

    {
      // R-CSSVAR · var(--undefined) 引用(浏览器静默丢整条声明,font: 缩写最危险)。
      // (步骤 3 第二批迁自 _validate_audits.py audit_undefined_css_vars)。
      // 原版从【所有 CSS 源(作者 + inline_linked 进来的框架)】文本里收 `--name:` 定义
      // 与 `var(--name[, fallback])` 引用,无 fallback 且未定义 → 报错。
      // 移植关键:**不能用 CSSOM** —— 浏览器会把含未定义 var() 的整条声明丢掉(正是本规则
      // 要抓的),CSSOM 里就读不到了;且 file:// 下外链样式表 cssRules 被 CORS 挡。改读
      // <style> 块的 textContent(原始源字节、不被解析擦除);框架变量定义由 runner 把外链
      // CSS 注入成 <style data-source="framework"> 提供(见 run-audits.py _inline_framework_css)。
      // deck 级规则:整 deck 算一次,挂在第一帧上报(用 window 缓存防重复)。
      id: 'R-CSSVAR',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__CSSVAR_DONE__) return [];
        // deck 级:整 deck 算一次,挂在本次 scope 的第一帧上(scope 排除首帧也照常报)。
        if (!ctx.isFirstInScope) return [];
        if (typeof window !== 'undefined') window.__CSSVAR_DONE__ = true;

        // 收集所有 <style> 块的源文本(含 runner 注入的框架块)。
        const styles = (typeof document !== 'undefined' && document.querySelectorAll('style')) || [];
        let combined = '';
        for (const s of styles) combined += '\n' + (s.textContent || '');
        if (!combined.trim()) return [];

        // 去 CSS 注释 + 字符串字面量(免得引号里的 `--foo:` / `var()` 误判)。
        let clean = combined.replace(/\/\*[\s\S]*?\*\//g, '');
        clean = clean.replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'/g, '""');

        // 定义:`--name:`。
        const defined = new Set();
        let dm;
        const defRe = /--([a-zA-Z][\w-]*)\s*:/g;
        while ((dm = defRe.exec(clean))) defined.add(dm[1]);

        // 引用:`var(--name[, fallback])`;有 fallback 即豁免。
        const refRe = /var\(\s*--([a-zA-Z][\w-]*)\s*(?:,((?:[^()]|\([^()]*\))*))?\)/g;
        const undefinedCounts = {};
        let rm;
        while ((rm = refRe.exec(clean))) {
          const name = rm[1];
          const fallback = (rm[2] || '').trim();
          if (defined.has(name) || fallback) continue;
          undefinedCounts[name] = (undefinedCounts[name] || 0) + 1;
        }
        const names = Object.keys(undefinedCounts);
        if (!names.length) return [];

        const suggest = (name) => {
          const lo = name.toLowerCase();
          for (const d of defined) if (d.toLowerCase() === lo) return ` Did you mean \`--${d}\`?`;
          for (const d of defined) {
            let common = 0;
            const n = Math.min(name.length, d.length);
            for (let k = 0; k < n; k++) { if (name[k] === d[k]) common++; else break; }
            if (common >= 4 && Math.abs(d.length - name.length) <= 5) return ` Did you mean \`--${d}\`?`;
          }
          return '';
        };

        const findings = [];
        for (const name of names.sort()) {
          const count = undefinedCounts[name];
          findings.push({
            rule: 'R-CSSVAR',
            severity: 'error',
            slide_idx,
            var_name: name,
            count,
            message:
              `\`var(--${name})\` referenced ${count}× but never defined in any ` +
              'CSS source linked from this deck. Browser silently fails the ' +
              'surrounding declaration — common consequence: `font:` shorthand ' +
              'parse fails → font-size falls back to browser default 16px.' +
              suggest(name),
          });
        }
        return findings;
      },
    },

    {
      // R10 · slide markup 里的 hex 必须来自 --fs-* 调色板。(步骤 3 第二批迁自
      // _validate_audits.py audit_hex_palette)。原版扫 <body> 文本(剥 script/style/svg/
      // data: URI),正则抓 `#hex`,不在 ALLOWED_HEX 即报。always warn;--strict 全局升 err。
      // IMPORTED deck(全 lifted / origin=imported)→ 颜色逐字搬运,降 warn_soft(不升 err)。
      // 移植:渲染后等价 = 扫每个元素的 inline `style` 属性里的 hex(原版抓的就是 markup 里
      // 写死的 hex,渲染后这些 hex 落在 style 属性 / 不会变);跳过 svg / style / script 子树。
      // deck 级聚合(原版按整 body 统计,无法归到某帧),整 deck 算一次挂第一帧。
      id: 'R10',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__R10_DONE__) return [];
        if (!ctx.isFirstInScope) return [];   // deck 级:整 deck 算一次,挂本次 scope 首帧
        if (typeof window !== 'undefined') window.__R10_DONE__ = true;
        const slides = (typeof document !== 'undefined' && document.querySelectorAll('.slide')) || [];

        const HEX_RE = /#([0-9A-Fa-f]{3,6})\b/g;
        const counts = {};
        // 遍历所有 slide 里元素的 inline style(markup 写死的 hex 都在这);svg 内部 / style /
        // script 跳过(原版 strip svg/style/script)。保险起见对 style 值剥掉 data: 段
        // (base64 里的 #xxx 假阳)。
        for (const sl of slides) {
          const walker = [sl, ...sl.querySelectorAll('*')];
          for (const el of walker) {
            const tag = el.tagName;
            if (tag === 'STYLE' || tag === 'SCRIPT') continue;
            if (tag === 'SVG' || tag === 'svg') continue;
            // svg 内部元素:跳过(祖先含 svg)。
            let inSvg = false;
            for (let p = el.parentElement; p && p !== sl.parentElement; p = p.parentElement) {
              const pt = p.tagName;
              if (pt === 'SVG' || pt === 'svg') { inSvg = true; break; }
            }
            if (inSvg) continue;
            const styleAttr = el.getAttribute && el.getAttribute('style');
            if (!styleAttr) continue;
            const v = styleAttr.replace(/data:[^"'\s)]+/g, '');
            let m;
            HEX_RE.lastIndex = 0;
            while ((m = HEX_RE.exec(v))) {
              const h = m[1].toLowerCase();
              if (ALLOWED_HEX.has(h)) continue;
              counts[h] = (counts[h] || 0) + 1;
            }
          }
        }
        const extras = Object.keys(counts);
        if (!extras.length) return [];
        const msg = extras.sort().map((h) => `#${h}×${counts[h]}`).join(', ');
        const imported = deckAllImported();
        if (imported) {
          return [{
            rule: 'R10',
            severity: 'warn_soft',
            slide_idx,
            message: `hex values outside palette in slide markup: ${msg}` +
              ' — IMPORTED deck (verbatim-carried colors); soft advisory.',
          }];
        }
        return [{
          rule: 'R10',
          severity: 'warn',
          slide_idx,
          message: `hex values outside palette in slide markup: ${msg}`,
        }];
      },
    },

    {
      // R-KEY · 每个 .slide 都要有唯一、语义化的 data-slide-key。(步骤 3 第二批迁自
      // _validate_audits.py audit_slide_keys)。规则:必填 / kebab-case
      // (^[a-z][a-z0-9-]*$)/ deck 内唯一 / 位置型(slide-NN…)只 warn。
      // 位置型在 lifted 页(data-lifted)降 warn_soft(源排序的忠实搬运);重复 key 即便
      // lifted 也保 err(撞 key 破坏 round-trip / library 定位)。
      // deck 级规则(要跨帧查重),整 deck 算一次挂第一帧。
      id: 'R-KEY',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__RKEY_DONE__) return [];
        if (!ctx.isFirstInScope) return [];   // deck 级查重:整 deck 算一次,挂本次 scope 首帧
        if (typeof window !== 'undefined') window.__RKEY_DONE__ = true;
        const slides = (typeof document !== 'undefined' && document.querySelectorAll('.slide')) || [];

        const findings = [];
        const seen = {};       // slug -> first 1-based slide index
        const missing = [];
        slides.forEach((sl, idx) => {
          const i = idx + 1;
          const lifted = slideIsLifted(sl);
          const hasAttr = sl.hasAttribute('data-slide-key');
          if (!hasAttr) { missing.push(i); return; }
          const slug = sl.getAttribute('data-slide-key') || '';
          if (!slug) {
            findings.push({
              rule: 'R-KEY', severity: 'error', slide_idx: i,
              message: `slide ${i}: data-slide-key is empty. ` +
                'Set a semantic kebab-case slug (e.g. "arr-history", "cover", ' +
                '"case-meiyijia"). Required by feishu-slide-library locator.',
            });
            return;
          }
          if (!KEY_VALID_SLUG_RE.test(slug)) {
            findings.push({
              rule: 'R-KEY', severity: 'error', slide_idx: i,
              message: `slide ${i}: data-slide-key="${slug}" is not valid kebab-case. ` +
                'Use lowercase letters, digits, and `-` only; must start with ' +
                'an alphanumeric. Example: "arr-history" not "ARR_History".',
            });
            return;
          }
          if (KEY_POSITIONAL_RE.test(slug)) {
            if (lifted) {
              findings.push({
                rule: 'R-KEY', severity: 'warn_soft', slide_idx: i,
                message: `slide ${i}: data-slide-key="${slug}" is positional — ` +
                  'IMPORTED/lifted slide (key carried from source ordering); ' +
                  'soft advisory, rename to a semantic slug if you keep it.',
              });
            } else {
              findings.push({
                rule: 'R-KEY', severity: 'warn', slide_idx: i,
                message: `slide ${i}: data-slide-key="${slug}" is positional — it ` +
                  'breaks when slides reorder. Use a semantic slug naming ' +
                  'what the slide is ABOUT (e.g. "arr-history" instead of ' +
                  '"slide-06").',
              });
            }
          }
          if (Object.prototype.hasOwnProperty.call(seen, slug)) {
            findings.push({
              rule: 'R-KEY', severity: 'error', slide_idx: i,
              message: `slide ${i}: data-slide-key="${slug}" already used by ` +
                `slide ${seen[slug]}. Slugs must be deck-internal unique. ` +
                'Pick a different semantic slug or add a suffix ' +
                `(e.g. "${slug}-v2").`,
            });
          } else {
            seen[slug] = i;
          }
        });
        if (missing.length) {
          const head = missing.slice(0, 5).join(', ');
          findings.push({
            rule: 'R-KEY', severity: 'error', slide_idx: missing[0],
            message: `${missing.length} slide(s) missing data-slide-key ` +
              `(slide indices: ${head}${missing.length > 5 ? ', …' : ''}). ` +
              'Every .slide must carry a semantic kebab-case slug so the ' +
              'feishu-slide-library skill can index it. Add ' +
              '`data-slide-key="<slug>"` next to data-screen-label.',
          });
        }
        return findings;
      },
    },

    {
      // R07 · logo 默认彩色,除非显式 is-mono opt-in。(步骤 3 第二批迁自
      // _validate_audits.py audit_brand_chrome)。原版扫 `class="wordmark is-mono"` /
      // `class="is-mono wordmark"`;渲染后等价 = .wordmark.is-mono(class 顺序无关,更准)。
      // 注:audit_structure 里的 R07「缺 .wordmark」未在本批迁移范围内(留后续批次)。
      id: 'R07',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const hit = (slide.matches && slide.matches('.wordmark.is-mono'))
          || slide.querySelector('.wordmark.is-mono');
        if (!hit) return [];
        return [{
          rule: 'R07',
          severity: 'warn',
          slide_idx,
          message: `slide ${slide_idx}: mono-white logo used — verify this is an over-imagery edge case`,
        }];
      },
    },

    {
      // R13 · 非 hero 版式的 page-header 标题必须单行(无 <br>)。(步骤 3 第二批迁自
      // _validate_audits.py audit_titles_one_line)。原版扫 `<h1|h2 class*="title"|"title-zh">`
      // 内含 `<br>` 的;hero-title 版式(cover/image-text/end/section/quote)豁免。
      // 移植:querySelectorAll('h1,h2') 里 class 含 title / title-zh、且含真实 <br> 子节点。
      // (schema title 字段的字面 <br> 会被 _esc_br 转义成可见文本 → 由 R-ESC-HTML 抓;R13 抓的
      // 是 raw 页 / 真标签输出里真正渲染成换行的 <br> 元素。)
      id: 'R13',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx, layout } = ctx;
        if (HERO_TITLE_LAYOUTS.has(layout)) return [];   // hero 版式允许多行标题
        const findings = [];
        slide.querySelectorAll('h1, h2').forEach((h) => {
          const tokens = classStr(h).split(/\s+/).filter(Boolean);
          const isTitle = tokens.includes('title') || tokens.includes('title-zh');
          if (!isTitle) return;
          if (h.querySelector('br')) {
            findings.push({
              rule: 'R13',
              severity: 'error',
              slide_idx,
              message: `slide ${slide_idx} (${layout || '?'}): <br> inside header title — ` +
                'titles must be one line on non-hero layouts',
            });
          }
        });
        return findings;
      },
    },

    {
      // R38 · data-decor token 必须来自 ship list。(步骤 3 第二批迁自
      // _validate_audits.py audit_data_decor)。原版读 slide 的 data-decor 属性、空格拆分,
      // 任一 token 不在 ALLOWED_DECOR 即报 err。渲染后等价 = 读 .slide[data-decor]。
      id: 'R38',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const decor = slide.getAttribute('data-decor');
        if (!decor) return [];
        const findings = [];
        // 与 Python `sorted(ALLOWED_DECOR)` 的 repr 完全一致(单引号、', ' 分隔、[] 包裹)。
        const allowedRepr = '[' + [...ALLOWED_DECOR].sort().map((t) => `'${t}'`).join(', ') + ']';
        for (const token of decor.split(/\s+/).filter(Boolean)) {
          if (!ALLOWED_DECOR.has(token)) {
            findings.push({
              rule: 'R38',
              severity: 'error',
              slide_idx,
              token,
              message: `slide ${slide_idx}: unknown data-decor token '${token}' — ` +
                `must be one of ${allowedRepr}`,
            });
          }
        }
        return findings;
      },
    },

    {
      // R-LANG · zh-only 默认语言政策(禁 EN 翻译轨)。(步骤 3 第二批迁自
      // _validate_audits.py audit_language_policy + audit_translation_track_pairs)。
      // 三段判定,全部在每帧 DOM 上做:
      //   (1) 双语 class:.title-en / .subtitle-en / .label-en(框架专为双语模式备)出现 = 漂移。
      //   (2) chrome-label 拉丁:eyebrow/kicker/pill/tag/...-en/...-num 等小文本叶里的纯拉丁 UC 串
      //       (品牌白名单 / 技术码豁免)。
      //   (3) sibling-pair 翻译轨:某语义容器(非 table/ul/figure 等布局型父)直接子叶里同时有
      //       CJK 叶和"应翻译拉丁"叶 = 翻译轨;图表脚手架(axis/legend/scale…)豁免。
      // 模式:<meta name=fs-language>;zh-en 整条豁免;未知值发 warn 并按 zh-only 处理。
      // lifted 页(data-lifted)的 R-LANG 命中降 warn_soft(源文本忠实搬运,不升 err)。
      id: 'R-LANG',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const mode = deckLanguageMode();
        if (mode === 'zh-en') return [];   // 显式双语,整规则 no-op
        const findings = [];
        const lifted = slideIsLifted(slide);
        const sev = lifted ? 'warn_soft' : 'warn';
        const emit = (message, extra) => findings.push(Object.assign(
          { rule: 'R-LANG', severity: sev, slide_idx, message }, extra || {}));

        // 未知 mode:只在第一帧发一次告知(原版每次跑 audit 发一次 → deck 级,这里挂 scope 首帧)。
        if (mode !== 'zh-only') {
          if (ctx.isFirstInScope && !(typeof window !== 'undefined' && window.__RLANG_MODE_WARNED__)) {
            if (typeof window !== 'undefined') window.__RLANG_MODE_WARNED__ = true;
            findings.push({
              rule: 'R-LANG', severity: 'warn', slide_idx,
              message: `<meta name="fs-language" content="${mode}"> — unknown value. ` +
                'Use "zh-only" (default, monolingual ZH) or "zh-en" (bilingual). ' +
                'Treating as zh-only.',
            });
          }
        }

        // (1) 双语 class —— 一帧报一次(原版 break)。
        const bilingual = slide.querySelector('.title-en, .subtitle-en, .label-en');
        if (bilingual) {
          const tok = classStr(bilingual).split(/\s+/)
            .find((c) => c === 'title-en' || c === 'subtitle-en' || c === 'label-en') || 'title-en';
          emit(`slide ${slide_idx}: bilingual class \`${tok}…\` rendered in ` +
            'zh-only mode — drop the EN translation track, or ' +
            'opt into bilingual via `<meta name="fs-language" ' +
            'content="zh-en">` in <head>.');
        }

        // (2) chrome-label 拉丁标签。元素 class 命中 chrome 族、且为文本叶(无元素子节点)、
        //     直接文本是"应翻译拉丁串"。
        slide.querySelectorAll('span, p, div, h1, h2, h3, h4, h5, h6').forEach((el) => {
          if (!langClassIsChromeLabel(el)) return;
          if (!isElementLeaf(el)) return;
          const text = directText(el);
          if (!langIsOffendingLatin(text)) return;
          emit(`slide ${slide_idx}: chrome label \`${text}\` looks like a Latin label ` +
            'in a zh-only deck. If it\'s genuinely a brand / product / ' +
            'acronym, add it to LATIN_BRAND_WHITELIST in validate.py; ' +
            'otherwise translate to CJK (e.g. "MODE 01" → "方式 01", ' +
            '"DEADLINE" → "截止时间", "PREDIT"-style typos → fix).');
        });

        // (3) sibling-pair 翻译轨。收集本帧所有"文本叶"(有直接文本、无元素子节点、在叶标签集),
        //     按直接父元素分组;父非布局型 / 非脚手架,且直接子叶里同时含 CJK 叶 + 应翻译拉丁叶 → 报。
        const LEAF_TAGS = new Set(['SPAN', 'P', 'DIV', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6',
          'LI', 'A', 'B', 'EM', 'STRONG', 'I', 'U', 'SMALL', 'MARK',
          'BLOCKQUOTE', 'DT', 'DD', 'FIGCAPTION', 'CAPTION', 'TH', 'TD']);
        const byParent = new Map();
        const allEls = slide.querySelectorAll('*');
        for (const el of allEls) {
          const tag = el.tagName;
          if (tag === 'STYLE' || tag === 'SCRIPT' || tag === 'SVG' || tag === 'svg') continue;
          // svg 子树跳过。
          let inSvg = false;
          for (let p = el.parentElement; p && p !== slide.parentElement; p = p.parentElement) {
            const pt = p.tagName; if (pt === 'SVG' || pt === 'svg') { inSvg = true; break; }
          }
          if (inSvg) continue;
          if (!LEAF_TAGS.has(tag)) continue;
          if (!isElementLeaf(el)) continue;        // 必须是叶(无元素子节点)
          const text = directText(el);
          if (!text) continue;
          const parent = el.parentElement;
          if (!parent) continue;
          if (!byParent.has(parent)) byParent.set(parent, []);
          byParent.get(parent).push({ el, text, cls: classStr(el), tag: tag.toLowerCase() });
        }
        const seenPairs = new Set();
        for (const [parent, sibs] of byParent) {
          if (sibs.length < 2) continue;
          if (LAYOUT_ONLY_PARENT_TAGS.has(parent.tagName)) continue;
          const parentClass = classStr(parent);
          if (isChartScaffoldClass(parentClass)) continue;
          const cjkLvs = sibs.filter((s) => CJK_RE.test(s.text));
          let latLvs = sibs.filter((s) => langIsOffendingLatin(s.text));
          latLvs = latLvs.filter((s) => !isChartScaffoldClass(s.cls));
          if (!(cjkLvs.length && latLvs.length)) continue;
          const parentRef = parentClass
            ? `class="${parentClass.slice(0, 60)}"`
            : `<${parent.tagName.toLowerCase()}>`;
          for (const l of latLvs) {
            const key = l.cls + ' ' + l.text;
            if (seenPairs.has(key)) continue;
            seenPairs.add(key);
            emit(`slide ${slide_idx}: \`<${l.tag} class="${l.cls.slice(0, 60)}">` +
              `${l.text.slice(0, 60)}\` — Latin-only leaf paired with CJK ` +
              `sibling inside \`<… ${parentRef}>\` looks like an EN ` +
              'translation track. Drop the Latin leaf, translate to ' +
              'CJK, opt into bilingual via `<meta name="fs-language" ' +
              'content="zh-en">`, or add the term to ' +
              'LATIN_BRAND_WHITELIST in validate.py if it is ' +
              'genuinely a brand / acronym.');
          }
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
    // deck 级规则(R-CSSVAR / R10 / R-KEY,跨帧/整 deck 求值,只报一次)需要一个稳定的
    // "唯一锚帧",哪怕 scope 把第一帧排除了也得有个帧来承载结果 —— 取本次实际处理(scope 内)
    // 的第一帧。这些规则内部仍对【整 deck】求值(查重/调色板/var),只是输出挂在 firstInScope 上。
    let firstInScopeIdx = -1;
    slides.forEach((slide, idx) => {
      const i = idx + 1;
      if (firstInScopeIdx === -1 && (!scopeSet || scopeSet.has(i))) firstInScopeIdx = i;
    });
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
        isFirstInScope: slide_idx === firstInScopeIdx,
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
