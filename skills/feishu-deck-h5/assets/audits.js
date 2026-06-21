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

  // F-301 · 找本页的「页头标题带」容器。直接子 `.header` 优先(框架 canonical);
  // 没有时接受【嵌一层】的 .header —— bespoke 满幅 raw 页常把 header 包进全幅
  // wrapper(.land > .header,fwd-founder #8),`:scope > .header` 一律摸空导致
  // TITLE-GAP / CANVAS-CENTER 整条通道静默。嵌套候选要过严闸,防止把内容区的
  // mock-UI「header」(手机/窗口 chrome)认成页头:
  //   ① 不在 .stage 内(schema 正文里的都是内容);② 必须含框架标题元素
  //   (.title-zh/.title-en/h1/h2 —— bespoke 页也沿用这个约定);③ 顶部带内
  //   (top ≤ 200 design px);④ 宽 ≥ 40% 画布(mock chrome 是窄条)。
  const findSlideHeader = (slide) => {
    const direct = slide.querySelector(':scope > .header');
    if (direct) return direct;
    const sr = slide.getBoundingClientRect();
    if (sr.height < 30) return null;
    const scale = sr.height / 1080;
    for (const el of slide.querySelectorAll('.header')) {
      if (el.closest('.stage')) continue;
      if (!el.querySelector('.title-zh, .title-en, h1, h2')) continue;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      if ((r.top - sr.top) / scale > 200) continue;
      if (r.width < sr.width * 0.4) continue;
      return el;
    }
    return null;
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

  // F-358 mockup sandbox: a simulated-UI mockup subtree (a `.phone`/UI mock marked
  // `data-mockup`, or any `role="img"` graphic) is a PICTURE of a product UI, not
  // page content — so its internals are exempt from the page-content chrome rules
  // (R20 / typescale, R-WHITE-TEXT, R12 drop-shadow). One marker on the root replaces
  // sprinkling data-allow-typescale + data-allow-white-opacity + data-allow-drop-shadow.
  const inMockupRoot = (el, stop) => {
    for (let p = el; p && p !== stop; p = p.parentElement) {
      if (p.nodeType === 1 &&
          (p.hasAttribute('data-mockup') || p.getAttribute('role') === 'img')) return true;
    }
    return false;
  };

  // DEAD-ANIM / DEAD-RULE host stripper. A rule targeting a pseudo-element
  // (::before/::after/…) or a dynamic state (:hover/:focus/…) NEVER matches
  // querySelectorAll (pseudo-elements aren't selectable; states aren't active at
  // audit time) → the raw selector looks "dead" even when the host element is
  // present and healthy (false dead-anim/dead-rule on glow/ring/line ::after
  // decorations — the same ::after class R12 avoids by reading pseudo styles via
  // getComputedStyle(el,'::after')). Strip those tails to the structural HOST;
  // a rule is only truly dead when even the host matches zero.
  const _PSEUDO_EL_RE = /::?(?:before|after|first-line|first-letter|marker|placeholder|selection|backdrop|cue|cue-region|file-selector-button|target-text|spelling-error|grammar-error)\b(?:\([^)]*\))?/gi;
  const _DYN_PSEUDO_RE = /:(?:hover|focus|focus-within|focus-visible|active|target|checked|visited|link|enabled|disabled|indeterminate|default|placeholder-shown|autofill|user-invalid|user-valid|current|past|future)\b(?:\([^)]*\))?/gi;
  const hostSelForDeadCheck = (sel) =>
    (sel || '').replace(_PSEUDO_EL_RE, '').replace(_DYN_PSEUDO_RE, '').trim();

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
    if (ss.href && /(?:feishu-deck(?:-patterns)?|deck-edit-mode|extra-layouts)\.css/.test(ss.href)) return true;
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
      // /* allow:white-opacity */ 注释豁免 —— CSSOM 的 cssText 丢注释,改读 owning
      // <style> 的【原始文本】(保留注释,与 R06 同套路):收集 declaration 块里带 marker
      // 的选择器 → 规则级豁免。恢复迁移前作者一直在用的注释 opt-out(否则存量 deck 静默报警)。
      const _rawExempt = new Set();
      const _rawCss = (ss.ownerNode && ss.ownerNode.textContent) || '';
      if (_rawCss.indexOf('allow:white-opacity') >= 0) {
        const _blockRe = /([^{}]+)\{([^{}]*)\}/g;
        let _m;
        while ((_m = _blockRe.exec(_rawCss))) {
          if (_m[2].indexOf('allow:white-opacity') < 0) continue;
          for (const s of _m[1].split(',')) {
            const n = s.replace(/\s+/g, ' ').trim();
            if (n) _rawExempt.add(n);
          }
        }
      }
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
          if (_rawExempt.size && _rawExempt.has(selector.replace(/\s+/g, ' ').trim())) continue;  // /* allow:white-opacity */ 注释豁免(读原始文本恢复)
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

  // --------------------------------------------------------------------------
  //  步骤 3 第三批共享常量/工具(R06 / R20 / R-HIERARCHY / R05 / R56 / R-ECHO)
  // --------------------------------------------------------------------------

  // ── 4-tier 字号台阶 + 两道地板(对应 _validate_common.py 的 _FS_TOKENS 派生量)。
  //    台阶/地板从【框架 CSS :root --fs-* 真值】读,而非硬编 16/24/28/48 —— 与 Python
  //    _load_fs_tokens 同源。读不到则退回 fallback(与 _FS_TOKEN_FALLBACK 同值)。
  //    runner 注入了 <style data-source=framework> 的框架 CSS,这里能从中读到 :root 定义。
  const _FS_TOKEN_FALLBACK = { '--fs-foot': 16, '--fs-body': 24, '--fs-sub': 28, '--fs-title': 48 };
  const loadFsTokens = () => {
    if (typeof window !== 'undefined' && window.__FS_TOKENS__) return window.__FS_TOKENS__;
    let tokens = Object.assign({}, _FS_TOKEN_FALLBACK);
    const styles = (typeof document !== 'undefined' && document.querySelectorAll('style')) || [];
    let combined = '';
    for (const s of styles) combined += '\n' + (s.textContent || '');
    const found = {};
    let m;
    const re = /--fs-(title|sub|body|foot)\s*:\s*(\d+)px/g;
    while ((m = re.exec(combined))) found['--fs-' + m[1]] = parseInt(m[2], 10);
    // require all four; else fall back(防未来重命名)。
    if (['--fs-title', '--fs-sub', '--fs-body', '--fs-foot'].every((k) => k in found)) {
      tokens = found;
    }
    if (typeof window !== 'undefined') window.__FS_TOKENS__ = tokens;
    return tokens;
  };
  const FS_TOKENS = loadFsTokens();
  const FLOOR_BODY_PX = FS_TOKENS['--fs-body'];     // 内容正文地板(rung 3)
  const FLOOR_CHROME_PX = FS_TOKENS['--fs-foot'];   // 角标/脚注/pill/tag 地板(rung 4)
  const TYPE_LADDER_PX = new Set(Object.values(FS_TOKENS));  // 4-tier strict {16,24,28,48}

  // ── R06 body-class / chrome-class 选择器判定(逐字对应 _validate_common.py 的
  //    _BODY_CLASS_RE / _CHROME_CLASS_RE)。作用在 selector 文本上(与 Python 同)。
  const BODY_CLASS_RE = new RegExp(
    '\\.(?:'
    + 'cbody|body|desc|sub|lede|paragraph|para|caption|cap|note|'
    + 'feat-body|brand-desc|dir-desc|dir-sub|sc-obj|sc-lever|'
    + 'arch-item|arch-base|arch-hand-title|story-hook|story-arc|'
    + 'principle|voice-card|voice-q|cta-box|the-who|content-body|'
    + 'who|name|preview-text|hook|takeaway|callout-body|'
    + 'sec ?ul|sec ?ol|item-body|row-body|cell-body|col-body|col-text|'
    + 'page-sub|subtitle(?!-en)|lead|timeline-desc'
    + ')\\b'
    + '|\\b(?:ts-tasks|ts-time)\\b');
  const CHROME_CLASS_RE = new RegExp(
    '\\.(?:'
    + 'eyebrow|footnote|pageno|deck-pageno|attrib|source(?:-footer)?|'
    + 'pill|chip|tag(?:-chip)?|badge|label-small|chrome|kicker|overline|'
    + 'meta|trend|axis(?:-cap)?|hint|tip|legend|nav-hint|mode-toggle|'
    + 'phase-pill|status|status-dot|fmt|fix|disclaim|fineprint|'
    + 'sc-cap|cfoot|stnum|chapter-num|stat-unit|kpi-unit|unit|'
    + 'iframe-hint|count|'
    + 'n'
    + ')\\b|'
    + '\\.ui-[a-z][\\w-]*');

  // ── R-HIERARCHY meta-class / column-label 选择器判定(逐字对应 audit_hierarchy 的
  //    META_CLASS_RE / COLUMN_LABEL_RE,用 `(?![-_\w])` 而非 \b)。
  const META_CLASS_RE = new RegExp(
    '\\.(?:'
    + 'owner|attrib|source(?:-footer)?|who|byline|author-meta|'
    + 'timestamp|date|status|kicker|'
    + 'td-owner|nc-author|case-attrib|quote-attrib|voice-who|'
    + 'eyebrow'
    + ')(?![-_\\w])');
  const COLUMN_LABEL_RE = new RegExp(
    '\\.(?:column-pill|side-pill|focus-pill|'
    + 'agenda-label|story-label|case-label)(?![-_\\w])');

  // ── @media 解析(对应 _media_query_matches,固定 1920×1080 画布)。
  const _DECK_VW = 1920, _DECK_VH = 1080;
  const MQ_FEATURE_RE = /\(\s*(min|max)-(width|height)\s*:\s*(\d+)\s*px\s*\)/;
  const mediaQueryMatches = (query) => {
    const q = (query || '').trim().toLowerCase();
    if (!q) return true;
    for (const branch of q.split(',')) {     // 逗号 = OR
      const b = branch.trim();
      if (!b) return true;
      let active = true;
      for (const part of b.split(/\band\b/)) {  // and = AND
        const p = part.trim();
        if (!p || p === 'all' || p === 'screen' || p === 'only screen' || p === 'only all') continue;
        if (p === 'print' || p === 'speech' || p.indexOf('only print') === 0) { active = false; break; }
        if (p.indexOf('not ') === 0) { active = (p.indexOf('print') >= 0 || p.indexOf('speech') >= 0); break; }
        const mm = MQ_FEATURE_RE.exec(p);
        if (mm) {
          const kind = mm[1], dim = mm[2], val = parseInt(mm[3], 10);
          const cur = dim === 'width' ? _DECK_VW : _DECK_VH;
          if ((kind === 'min' && cur < val) || (kind === 'max' && cur > val)) { active = false; break; }
        }
      }
      if (active) return true;
    }
    return false;
  };

  // ── @-rule 解析(对应 _strip_nested_at_rules):active @media 展开、其余 @-rule 丢弃。
  //    平衡花括号、递归处理嵌套 @media。
  const stripNestedAtRules = (css) => {
    const out = [];
    const n = css.length;
    let i = 0;
    for (;;) {
      const at = css.indexOf('@', i);
      if (at === -1) { out.push(css.slice(i)); break; }
      out.push(css.slice(i, at));
      const brace = css.indexOf('{', at);
      if (brace === -1) { out.push(css.slice(at)); break; }
      const prelude = css.slice(at, brace);
      let depth = 0, j = brace;
      for (; j < n; j++) {
        const c = css[j];
        if (c === '{') depth++;
        else if (c === '}') { depth--; if (depth === 0) break; }
      }
      const body = css.slice(brace + 1, j);
      const mk = /@([a-zA-Z-]+)\s*([\s\S]*)/.exec(prelude);
      const kind = mk ? mk[1].toLowerCase() : '';
      const cond = mk ? mk[2] : '';
      if (kind === 'media' && mediaQueryMatches(cond)) {
        out.push(stripNestedAtRules(body));    // 展开 + 递归
      }
      // else: 丢弃(inactive @media / @keyframes / @font-face / @supports / @page …)
      i = j + 1;
    }
    return out.join('');
  };

  // ── 遍历所有 <style> 块的 (rawCss, isFramework)(对应 _iter_style_blocks)。
  //    框架块 = runner 注入的 <style data-source="framework">。
  //    顺序保真:Python `inline_linked` 把框架 `<link>`(惯例为 <head> 首个样式表,层叠上
  //    必在作者覆盖之前)就地替换成 <style data-source=framework>,故框架块在源序里最前;
  //    runner 却把框架块 append 到 <head> 末尾 → DOM querySelectorAll 序里框架靠后。R06 混扫
  //    框架+作者并 [:10] 截断,顺序影响"取哪 10 条"。这里把框架块提到最前以与 Python 源序对齐
  //    (作者块之间仍保 DOM 序 = 源序)。R20(gate 排框架)/R-HIERARCHY(不含框架)不受影响。
  const iterStyleBlocks = (includeFramework) => {
    const fw = [];
    const author = [];
    const styles = (typeof document !== 'undefined' && document.querySelectorAll('style')) || [];
    for (const s of styles) {
      const isFw = s.getAttribute && s.getAttribute('data-source') === 'framework';
      if (isFw && !includeFramework) continue;
      (isFw ? fw : author).push({ css: s.textContent || '', isFramework: isFw });
    }
    return fw.concat(author);
  };

  // ── 注释容忍的 `selector { body }` 拆分(对应 _RULE_WITH_COMMENTS_RE)。
  //    返回 [{selector, body}](body 仍含注释,供 allow:* marker 判定)。先经 stripNestedAtRules。
  const RULE_WITH_COMMENTS_RE = /([^{}]+?)\{((?:\/\*[\s\S]*?\*\/|[^{}])*)\}/g;
  const iterCssRules = (rawCss) => {
    const css = stripNestedAtRules(rawCss);
    const out = [];
    let m;
    RULE_WITH_COMMENTS_RE.lastIndex = 0;
    while ((m = RULE_WITH_COMMENTS_RE.exec(css))) {
      out.push({ selector: m[1], body: m[2] });
    }
    return out;
  };

  // ── 从一个规则 body 抓所有 font-size px(对应 Python 的两条 finditer:
  //    `font-size: Npx` + `font: ... Npx` 缩写)。body 须先剥注释。
  const stripCssComments = (s) => (s || '').replace(/\/\*[\s\S]*?\*\//g, '');
  const collectFontSizes = (block) => {
    const sizes = [];
    let m;
    const re1 = /font-size:\s*(\d+)px/g;
    while ((m = re1.exec(block))) sizes.push(parseInt(m[1], 10));
    const re2 = /\bfont:\s*[^;{}]*?(\d+)px/g;
    while ((m = re2.exec(block))) sizes.push(parseInt(m[1], 10));
    return sizes;
  };

  // ── allow:* marker 解析。CSSOM cssText 不含注释 → 无法读 `/* allow:typescale */`
  //    等 opt-out;但渲染后 <style> textContent 原样保留注释(实测 56× typescale 在 rendered
  //    deck 里可读)。R06/R20/R-HIERARCHY 直接在规则 body 文本里 indexOf('allow:...') 判 opt-out
  //    (与 Python 同 —— marker 与 selector / 字号同处一份源,自洽,无需 CSSOM 反查归一化)。

  // ── 渲染后 DOM 上的文本叶遍历(对应 _walk_text_leaves)。返回叶 {tag, cls, text,
  //    parents:[class…closest-last], parentClass, parentEl, parentTag, el}。
  //    叶 = 有非空直接文本、无元素子节点(void 除外)、tag ∈ LEAF_TAGS;skip svg/style/script 子树。
  const LEAF_TAGS_ECHO = new Set(['SPAN', 'P', 'DIV', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6',
    'LI', 'A', 'B', 'EM', 'STRONG', 'I', 'U', 'SMALL', 'MARK',
    'BLOCKQUOTE', 'DT', 'DD', 'FIGCAPTION', 'CAPTION', 'TH', 'TD']);
  const walkTextLeaves = (root) => {
    const leaves = [];
    // 递归走,维护 parents(class 链, closest-last)。
    const walk = (el, parents) => {
      const tag = el.tagName;
      if (tag === 'STYLE' || tag === 'SCRIPT' || tag === 'SVG' || tag === 'svg') return;
      const childEls = [];
      for (const c of el.children) {
        const ct = c.tagName;
        if (ct === 'STYLE' || ct === 'SCRIPT' || ct === 'SVG' || ct === 'svg') continue;
        childEls.push(c);
      }
      const txt = directText(el);
      if (txt && isElementLeaf(el) && LEAF_TAGS_ECHO.has(tag)) {
        const parentEl = el.parentElement;
        leaves.push({
          tag: tag.toLowerCase(),
          cls: classStr(el),
          text: txt,
          parents: parents.slice(),
          parentClass: parents.length ? parents[parents.length - 1] : '',
          parentEl,
          parentTag: parentEl ? parentEl.tagName.toLowerCase() : '',
          el,
        });
      }
      const nextParents = parents.concat([classStr(el)]);
      for (const c of childEls) walk(c, nextParents);
    };
    for (const c of root.children) walk(c, [classStr(root)]);
    return leaves;
  };

  // --------------------------------------------------------------------------
  //  步骤 3 第四批共享常量/工具
  //  (R36 / R48 / R-EMPTY-HEADER-ZONE / R47 / R29-32 / R-VIS-NO-IMAGERY)
  // --------------------------------------------------------------------------

  // ── 收集整 deck 的"全部 CSS 源文本"(含框架,DOM 序;框架块由 runner 注入)。
  //    R36 / R48 等 deck 级 CSS 文本规则用它(原版扫整份 HTML 的 <style> / inline_linked
  //    进来的框架表)。注:与 R06/R20 的 iterStyleBlocks 同源,这里直接拼接整文本。
  const allStyleText = () => {
    let combined = '';
    for (const { css } of iterStyleBlocks(true)) combined += '\n' + css;
    return combined;
  };

  // ── R48 check_default_centering(逐字对应 _validate_audits.py check_default_centering)。
  //    centerable 版式的容器(stage/grid/toc/flow/nodes/stack 任一)须含某条 *-center 居中声明;
  //    任一别名命中即该版式 OK;全 deck CSS 聚合后判定(原版 audit_default_centering 聚合所有
  //    <style> 块、剥注释、_strip_nested_at_rules 后整体跑 check)。返回违规版式名数组。
  const R48_CENTERABLE = ['content-3up', 'content-2col', 'agenda', 'stats', 'big-stat', 'quote'];
  const R48_CONTAINER_ALIASES = ['stage', 'grid', 'toc', 'flow', 'nodes', 'stack'];
  const checkDefaultCentering = (css) => {
    const missing = [];
    for (const layout of R48_CENTERABLE) {
      let ok = false;
      for (const alias of R48_CONTAINER_ALIASES) {
        // 逐字镜像 Python 正则:.slide[data-layout="L"]\s+.alias\s*\{([^}]*)\}
        const re = new RegExp(
          '\\.slide\\[data-layout="' + layout + '"\\]\\s+\\.' + alias + '\\s*\\{([^}]*)\\}',
          'g');
        let m;
        while ((m = re.exec(css))) {
          const block = m[1];
          if (block.indexOf('justify-content: center') >= 0
            || block.indexOf('align-content: center') >= 0
            || block.indexOf('place-content: center') >= 0
            || block.indexOf('align-items: center') >= 0) { ok = true; break; }
        }
        if (ok) break;
      }
      if (!ok) missing.push(layout);
    }
    return missing;
  };

  // ── L1/L2/L4 layout-integrity（LKK exchange-deck 四大失败模式之三，ingest-gate
  //    MANDATORY，business-rules.yaml）。逐字镜像 _validate_audits.py 的
  //    check_logo_default / check_balance / check_attrs_density —— 三者都是对
  //    【整 deck 源 HTML（含框架 CSS + 渲染后 markup）】的正则文本扫描，与渲染计算
  //    无关，故在 audits.js 里对 deckOuterHTML()（runner 已注入框架 <style>，等价于
  //    Python inline_linked 后的 html）做同套正则即逐字对齐。三规则共用同一 deck-level
  //    锚帧（audit_layout_integrity 在 Python 里是单 audit emit L1/L2/L4 三 code）。

  // L1：wordmark 默认必须引用 --fs-asset-logo（彩色）；mono 须 opt-in。
  //   Python：re.search(r'\.slide \.wordmark\s*\{[^}]*background:\s*([^;]+);', html, DOTALL)
  //   找不到该规则 → False（报）；找到 → decl 须含 'asset-logo)' 且不含 'asset-logo-mono'。
  const L1_WORDMARK_RE = /\.slide \.wordmark\s*\{[^}]*background:\s*([^;]+);/s;
  const checkLogoDefault = (html) => {
    const m = L1_WORDMARK_RE.exec(html);
    if (!m) return false;
    const decl = m[1];
    return decl.indexOf('asset-logo)') >= 0 && decl.indexOf('asset-logo-mono') < 0;
  };

  // L2：易短内容版式的 body 容器须显式垂直居中（align/justify-content: center）或
  //   flex: 1。容器别名 stage/grid/flow/nodes 任一命中即该版式 OK。版式若未在 deck 中
  //   使用（`data-layout="L"` 整 html 串里都没有）→ 跳过。逐字镜像 check_balance：
  //   返回 [ok, brokenLayout]。timeline 故意排除（见 Python 注释，轴线/节点固定 y）。
  const L2_SHORT_LAYOUTS = ['content-2col', 'process', 'content-3up', 'pipeline'];
  const L2_ALIASES = ['stage', 'grid', 'flow', 'nodes'];
  const checkBalance = (html) => {
    for (const layout of L2_SHORT_LAYOUTS) {
      let ok = false;
      for (const alias of L2_ALIASES) {
        // 逐字镜像 Python 正则：.slide[data-layout="L"]\s+.alias\s*\{([^}]*)\}
        const re = new RegExp(
          '\\.slide\\[data-layout="' + layout + '"\\]\\s+\\.' + alias + '\\s*\\{([^}]*)\\}',
          'gs');
        let m;
        while ((m = re.exec(html))) {
          const block = m[1];
          if (block.indexOf('align-content: center') >= 0
            || block.indexOf('justify-content: center') >= 0
            || block.indexOf('flex: 1') >= 0) { ok = true; break; }
        }
        if (ok) break;
      }
      // 该版式没在 deck 用到 → 跳过。
      if (html.indexOf('data-layout="' + layout + '"') < 0) continue;
      if (!ok) return [false, layout];
    }
    return [true, null];
  };

  // L4：process .output .attrs 须 grid-template-columns: 1fr（窄 output 面板单列）。
  //   逐字镜像 check_attrs_density：无该 .output .attrs 规则 → True（N/A，不报）。
  const L4_ATTRS_RE = /\.slide\[data-layout="process"\]\s+\.output\s+\.attrs\s*\{[^}]*\}/s;
  const checkAttrsDensity = (html) => {
    const m = L4_ATTRS_RE.exec(html);
    if (!m) return true;   // deck 无 output 面板 → 规则 N/A
    return m[0].indexOf('grid-template-columns: 1fr;') >= 0;
  };

  // ── R47 variant-discipline 触发集(逐字对应 audit_variant_discipline)。
  const R47_LAYOUT_DISPLAY = new Set(['flex', 'grid', 'block', 'inline-block',
    'inline-flex', 'inline-grid', 'inline', 'table', 'table-row', 'table-cell']);
  const R47_STRUCTURAL_TRIGGERS = [
    'flex-direction:', 'flex-wrap:', 'flex-flow:',
    'grid-template-columns:', 'grid-template-rows:', 'grid-template-areas:',
    'grid-auto-flow:', 'grid-auto-columns:', 'grid-auto-rows:'];
  const R47_ALIGN_PROPS = ['align-items:', 'place-items:'];
  const R47_JUSTIFY_PROPS = ['justify-content:', 'place-content:'];

  // ── R-VIS-NO-IMAGERY sparse-by-design 版式集(对应 _SPARSE_BY_DESIGN =
  //    HERO_TITLE_LAYOUTS | {agenda, table, replica, iframe-embed, raw})。
  const SPARSE_BY_DESIGN = new Set([...HERO_TITLE_LAYOUTS,
    'agenda', 'table', 'replica', 'iframe-embed', 'raw']);

  // --------------------------------------------------------------------------
  //  步骤 3 第五批共享常量/工具
  //  (UI1 / R-VIS-LIFT-STYLE-LOST / R-AUTOBALANCE-PRESENT / audit_structure: R02/R07)
  //  注:R-RAW-LOOKS-SCHEMA 已于 2026-06-12 退役(F-305 «raw unless ceremonial»,
  //  与新增的反向规则 R-LAYOUT-DEPRECATED 立场冲突),其 helper(isIconViewBox /
  //  RLS_FLOW_SIGNALS / rawKeysFromDeckJson)随之删除;deck.json 真源查询改用
  //  下方通用的 layoutByKeyFromDeckJson。
  // --------------------------------------------------------------------------

  // ── UI1(audit_ui_mocks_are_html)brand / raster / ui-hint 判定(逐字对应
  //    _validate_audits.py 的 _UI1_BRAND / _UI1_UI_HINTS / _UI1_RASTER / _ui1_brand)。
  const UI1_BRAND = ['lark-logo', 'lark-slogan', 'lark-cover', 'lark-section',
    'lark-content', 'wordmark'];
  const UI1_UI_HINTS = new RegExp(
    '(screen|screenshot|\\bui\\b|dashboard|console|panel|chat|window|mock|'
    + 'prototype|figma|wireframe|interface)', 'i');
  const UI1_RASTER = /\.(png|jpe?g|webp|gif|bmp)(\?|#|$)/i;
  const ui1Brand = (s) => UI1_BRAND.some((h) => (s || '').indexOf(h) >= 0);

  // ── 整 deck 的源 HTML(documentElement.outerHTML)—— 渲染后的文档序列化。
  //    UI1 background-image 子串扫(原版扫 frame 源)、autobalance / 结构类需要"源样子",
  //    渲染后用序列化 DOM 当源。slide 级用 slide.outerHTML。
  const slideOuterHTML = (slide) => (slide && slide.outerHTML) || '';

  // ── deck 整文档源(含 head/script);autobalance 指纹、deck-origin 判定用。
  const deckOuterHTML = () => (typeof document !== 'undefined' && document.documentElement
    && document.documentElement.outerHTML) || '';

  // ── 所有 <script> 源文本拼接(runner 已把外链框架 JS 注入成 <script
  //    data-source=framework type=text/plain>;含页内 inline)。R-AUTOBALANCE-PRESENT
  //    / R-DOC 类的 JS 指纹检查用 —— 与 Python 在 inline_linked 之后扫整 HTML 等价。
  const allScriptText = () => {
    let s = '';
    const scripts = (typeof document !== 'undefined' && document.querySelectorAll('script')) || [];
    for (const el of scripts) s += ' ' + (el.textContent || '');
    return s;
  };

  // ── R-AUTOBALANCE-PRESENT 指纹(逐字对应 _AUTOBALANCE_SIG)。
  const AUTOBALANCE_SIG = 'function balanceSlide(slide)';

  // ── F-305 «raw unless ceremonial» — 正文 schema 版式【冻结清单】。schema 只保留
  //    【仪式页】(cover/section/agenda/quote/end)+【机制页】(raw/canvas/iframe-embed/
  //    replica);下面这 8 个【正文 schema 版式】(含其全部 variant:content-3up/2col/...
  //    stats-row/hero/... flow-process/timeline/... 等)已冻结 —— 仍为存量 deck 渲染,但
  //    新页应走 layout:"raw"(模型自由排版,更丰富、各页更不同)。判据用 deck.json 的
  //    【真 authored layout】(下方 layoutByKeyFromDeckJson),不用渲染后 data-layout ——
  //    raw 页常借 data-layout="content-3up" 蹭框架 CSS,那是 raw 主场、绝不算 deprecated。
  const DEPRECATED_BODY_LAYOUTS = new Set([
    'content', 'stats', 'flow', 'chart', 'table',
    'arch-stack', 'image-text', 'logo-wall',
  ]);

  // ── deck.json 的 key → 真 authored layout 映射(R-LAYOUT-DEPRECATED 的 SOURCE-OF-TRUTH)。
  //    deck.json 里 layout 与 variant 是分开字段,这里只取 base layout 即可判冻结。runner 经
  //    window.__DECK_JSON__ 注入(若存在);缺(foreign / Path B / lifted standalone)→ null,
  //    该规则安静跳过(advisory 永不误报)。memoize 到 window.__DECK_LAYOUT_BY_KEY__。
  const layoutByKeyFromDeckJson = () => {
    if (typeof window !== 'undefined' && window.__DECK_LAYOUT_BY_KEY__ !== undefined) {
      return window.__DECK_LAYOUT_BY_KEY__;
    }
    let out = null;
    const dj = (typeof window !== 'undefined' && window.__DECK_JSON__) || null;
    if (dj && Array.isArray(dj.slides)) {
      out = new Map();
      for (const s of dj.slides) {
        if (s && s.key) out.set(s.key, (s.layout || '').trim());
      }
    }
    if (typeof window !== 'undefined') window.__DECK_LAYOUT_BY_KEY__ = out;
    return out;
  };

  // ── audit_structure (R02/R07) 之 .wordmark 判定:渲染后 slide 子树是否含 .wordmark
  //    (逐字对应 `'class="wordmark' not in fr` —— 渲染后 querySelector 等价、更准:class
  //    顺序无关)。data-layout / data-screen-label 直接读属性。
  const slideHasWordmark = (slide) => !!(slide && (
    (slide.matches && slide.matches('.wordmark')) || slide.querySelector('.wordmark')));

  // ── R-VIS-LIFT-STYLE-LOST 重版式签名(逐字对应 HEAVY_SIGNATURES)。在 slide 源 HTML
  //    子串上判(与原版同 —— class 字面/标签字面),保留原版精确度。
  const LIFT_HEAVY_SIGNATURES = {
    quote: ['<blockquote', '<div class="attrib"', '<div class="stack"'],
    cover: ['<div class="author"'],
    section: ['<div class="chapter-num"', '<div class="pills"'],
    'big-stat': ['<div class="num"', '<div class="copy"'],
    end: ['<div class="slogan"'],
  };

  // ── R-DOM(audit_dom_integrity)class-token + 祖先判定(渲染基底)。
  //    `name in class_str.split()` 的 DOM 等价 = classList.contains(name)。
  const elHasClass = (el, name) => !!(el && el.classList && el.classList.contains(name));
  // 任一祖先(到 documentElement)是否也带 class name(R-DOM "嵌在另一 frame 内"判定)。
  const ancestorHasClass = (el, name) => {
    for (let p = el && el.parentElement; p; p = p.parentElement) {
      if (elHasClass(p, name)) return true;
    }
    return false;
  };

  // --------------------------------------------------------------------------
  //  步骤 3 第六批共享常量/工具 —— VISUAL 规则(R-OVERFLOW / R-VIS-CARD-OVERFLOW /
  //  R-VIS-TIER / R-VIS-HIER / R-VIS-BODY-FLOOR / R-VIS-ORPHAN)迁自 visual-audit.js。
  //  词表常量逐字搬 visual-audit.js 顶部("audit's hardcoded vocabulary");几何/测量
  //  helper(hasAnyClass / _isFramedBox / _isMediaBox / _contentUnion / _growBox)逐字
  //  搬 visual-audit.js 同名函数。finding 的 id/severity/文案/opt-out/lifted 降级则来自
  //  validate.py run_visual_audits 的消费段(见各规则注释)。
  // --------------------------------------------------------------------------

  // 4-tier 字号台阶(visual 用硬编 {16,24,28,48} — 与 R20/R06 的 TYPE_LADDER_PX 同集,
  // 但这里保留 visual-audit.js 原样硬编 Set 以零漂移逐字移植)。
  const VIS_TIER = new Set([16, 24, 28, 48]);
  // Hero exceptions — element/ancestor class 命中即允许 hero size(逐字搬 HERO_CLASSES)。
  const VIS_HERO_CLASSES = [
    'hero-num', 'ov-num', 'chapter-num', 'bigstat-num',
    'cover-title', 'cover-h1', 'big-num', 'num', 'unit',
    'slogan', 'idx',
    'hero', 'kpi-val', 'metric-value', 'kpi-strip',
    'closing-strip',
  ];
  const VIS_HERO_SIZES = new Set([
    30, 36, 38, 40, 44,
    52, 56, 64, 72, 88, 92, 96, 100, 132, 160,
    240, 312,
  ]);
  // Meta class hints(逐字搬 META_KEYS)。
  const VIS_META_KEYS = [
    'owner', 'attrib', 'source', 'who', 'byline', 'author-meta',
    'timestamp', 'date', 'status', 'kicker', 'eyebrow',
    'td-owner', 'quote-attrib', 'voice-who', 'case-attrib',
  ];
  // Body class hints(逐字搬 BODY_KEYS)。
  const VIS_BODY_KEYS = [
    'body', 'desc', 'paragraph', 'para', 'caption',
    'cc-body', 'card-body', 'td-body', 'nc-body', 'ov-desc',
    'dir-desc', 'mode-body', 'rule-text', 'arch-base', 'feat-body',
  ];
  // Card / panel container hints(逐字搬 CARD_KEYS)。
  const VIS_CARD_KEYS = [
    'canonical-card', 'todo-card', 'news-card', 'overview-card',
    'mode-card', 'dir-card', 'scene-card', 'ns-card', 'verdict-card',
    'voice-card', 'cta-box', 'data-panel', 'arch-hand',
    'story-case', 'pain-card', 'script-card', 'card-num',
    'ind-row', 'logo-cell',
  ];
  const VIS_CARD_SUFFIXES = ['-card', '-tile', '-cell', '-panel', '-box'];
  // 真页面级 chrome 类(逐字搬 CHROME_WHITELIST)。原 R-VIS-LABEL-FLOOR/HIER 留待;
  // 步骤 3 第九批 R-VIS-BAND-COLLIDE 用它把页面级 chrome 排除出"内容带"候选 → 引入。
  const VIS_CHROME_WHITELIST = [
    'source', 'pageno', 'footnote', 'attrib', 'copyright',
    'wordmark', 'contact', 'cfoot', 'demo-tag',
    'unit',
  ];
  // Grid 容器类(逐字搬 GRID_KEYS)。原 R-VIS-ALIGN(equal-height grid)未迁;步骤 3
  // 第九批 R-VIS-PEER-SIZE 的 parallelAnchor 用它(连同 CARD_KEYS / CARD_SUFFIXES)→ 引入。
  const VIS_GRID_KEYS = [
    'overview-grid', 'todo-grid', 'scene-grid', 'north-star-map',
    'dir-grid',
  ];
  // Mock 容器类(逐字搬 TIER_MOCK — R-VIS-TIER 的 mock-internal 豁免;R-VIS-BODY-FLOOR /
  // R-VIS-ORPHAN 共用同一集,visual-audit.js 注释 "Shared with R-VIS-BODY-FLOOR")。
  const VIS_TIER_MOCK = [
    'ui-window', 'ui-screen', 'ui-chat', 'ui-body', 'ui-toolbar',
    'ui-sidebar', 'ui-grid', 'ui-cell', 'ui-list-item', 'ui-msg',
    'phone', 'phone-screen', 'p22-ph', 'p17-phone', 'fs-phone',
    'chat-body', 'chat-header', 'p22-chat', 'p22-noti', 'p22-know',
    'p22-task', 'ph-bar', 'ph-status', 'ph-chat', 'msg-ai', 'msg-user',
    'dash', 'mini-ui', 'browser-mock', 'p17-xhs', 'p17-dy', 'p17-flow-card',
    'page-replica', 'report-toc', 'report-mock', 'doc-mock',
    'doc-preview', 'wiki-mock', 'feishu-doc', 'lark-doc-mock',
    'pd-card',
    'doc-grid', 'doc-stage', 'doc-card',
  ];
  // R-VIS-BODY-FLOOR 的 chrome-class 豁免集(逐字搬 CONTENT_CHROME_CLASSES)。
  const VIS_CONTENT_CHROME_CLASSES = [
    'pageno', 'footnote', 'source', 'attrib', 'copyright', 'wordmark',
    'contact', 'eyebrow', 'pill', 'tag', 'chip', 'badge', 'demo-tag',
    'demo-label', 'caption-meta', 'cite',
  ];

  // ── 静态↔视觉 chrome 词表对齐(2026-06-11)─────────────────────────────────
  // 此前是两套词表:静态检查(R06/R20,_validate_common.py 的 _CHROME_CLASS_RE)
  // 豁免 .kicker/.legend/.meta/…/.ui-* 全命名空间;视觉地板(R-VIS-BODY-FLOOR /
  // R-VIS-SHORT-LABEL-FLOOR)只认上面 16 个子串 → 作者按静态词表写的 chrome
  // (.ui-row 表格 mock、.kicker 等)静态全绿、视觉层却被误报,被迫逐个 data-allow。
  // 这里把静态词表整套搬进视觉层(只放宽、不收紧:旧子串集原样保留在前)。
  // ⚠️ 匹配语义:token 全等(class 拆分后逐个比对),不能用 visHasAnyClass 的子串
  // includes —— 'n'/'fix'/'tip' 这类短 token 用子串会把 'note'/'prefix' 全误豁免。
  // 同步约定:改 _validate_common._CHROME_CLASS_RE 必须同步这里;两边集合相等由
  // test_visual_audit_parity.py::test_chrome_vocab_aligned_with_static 锁定。
  const VIS_STATIC_CHROME_TOKENS = new Set([
    'eyebrow', 'footnote', 'pageno', 'deck-pageno', 'attrib', 'source',
    'source-footer', 'pill', 'chip', 'tag', 'tag-chip', 'badge', 'label-small',
    'chrome', 'kicker', 'overline', 'meta', 'trend', 'axis', 'axis-cap',
    'hint', 'tip', 'legend', 'nav-hint', 'mode-toggle', 'phase-pill',
    'status', 'status-dot', 'fmt', 'fix', 'disclaim', 'fineprint',
    'sc-cap', 'cfoot', 'stnum', 'chapter-num', 'stat-unit', 'kpi-unit',
    'unit', 'iframe-hint', 'count', 'n',
  ]);
  const visClassTokens = (el) => {
    const raw = el.className;
    return (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || ''))
      .toString().toLowerCase().split(/\s+/).filter(Boolean);
  };
  // 元素自身 class 命中静态 chrome 词表(token 全等)。
  const visIsStaticChrome = (el) =>
    visClassTokens(el).some((c) => VIS_STATIC_CHROME_TOKENS.has(c));
  // .ui-* 前缀 = SKILL.md rung-8 mockup primitive(静态侧 `\.ui-[a-z][\w-]*`):
  // 元素或祖先命中都算 mockup-internal(调用处配合祖先 walk 使用)。
  const visIsUiMock = (el) =>
    visClassTokens(el).some((c) => /^ui-[a-z][\w-]*$/.test(c));

  // class 子串包含判定(逐字搬 visual-audit.js hasAnyClass —— 小写化、子串 includes,
  // 与 audits.js 既有的 classList.contains 不同语义:这是 visual 的"宽松子串"匹配)。
  const visHasAnyClass = (el, keys) => {
    const raw = el.className;
    const cls = (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || '')).toString().toLowerCase();
    return keys.some((k) => cls.includes(k));
  };
  // -card / -tile / -cell / -panel / -box 后缀卡片判定(逐字搬 hasCardSuffix)。
  const visHasCardSuffix = (el) => {
    const raw = el.className;
    const cls = (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || '')).toString().toLowerCase();
    return VIS_CARD_SUFFIXES.some((suf) => cls.split(/\s+/).some((c) => c.endsWith(suf)));
  };
  // 可见 text-bearing 叶的并集 bbox(逐字搬 _contentUnion)。
  // opts.flowOnly(2026-06-11,CROWD/PANEL-TOP 误报修复):跳过 position:absolute/
  // fixed 的文本元素 —— 绝对定位的角标(mock 缩略图右下 ".pptx"、水印、徽标)是刻意
  // 摆放,不是"流式内容被挤到框底";把它们算进内容范围会让 decor 缩略图在 CROWD 上
  // 必报(其唯一文本=贴底角标 → distBottom<10 恒成立)。默认 false = 原语义,
  // 其余消费者(visGrowBox / R-VIS-BAND 系)行为零变。
  const visContentUnion = (root, opts) => {
    const flowOnly = !!(opts && opts.flowOnly);
    let t = Infinity, b = -Infinity, any = false;
    for (const el of root.querySelectorAll('*')) {
      if (el.tagName === 'SVG' || el.tagName === 'svg'
          || el.tagName === 'SCRIPT' || el.tagName === 'STYLE') continue;
      if (!hasOwnText(el)) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) continue;
      if (flowOnly && (cs.position === 'absolute' || cs.position === 'fixed')) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) continue;
      any = true; t = Math.min(t, r.top); b = Math.max(b, r.bottom);
    }
    return any ? { top: t, bottom: b } : null;
  };
  // 有可见"框"(border / bg-color / bg-image)的盒(逐字搬 _isFramedBox)。
  const visIsFramedBox = (el) => {
    const cs = getComputedStyle(el);
    const hb = ['Top', 'Right', 'Bottom', 'Left'].some((s) =>
      parseFloat(cs['border' + s + 'Width'] || 0) > 0
      && !/transparent|rgba\(0, 0, 0, 0\)/.test(cs['border' + s + 'Color']));
    const bg = cs.backgroundColor;
    const hbg = bg && !/transparent|rgba\(0, 0, 0, 0\)/.test(bg);
    const hbi = cs.backgroundImage && cs.backgroundImage !== 'none';
    return hb || hbg || hbi;
  };
  // 媒体框(逐字搬 _isMediaBox)。
  const visIsMediaBox = (el) => {
    const cs = getComputedStyle(el);
    if (cs.backgroundImage && cs.backgroundImage !== 'none' && !/gradient/i.test(cs.backgroundImage)) return true;
    if (el.querySelector('img,iframe,canvas,video,picture')) return true;
    const raw = el.className;
    const c = (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || '')).toString();
    return /\b(photo|image|img|visual|mock|thumb|avatar|portrait|media|phone|screen)\b/i.test(c);
  };
  // grow-box verdict(逐字搬 _growBox)——R-VIS-BODY-FLOOR 的"改大自动拉高"判断。
  const visGrowBox = (el, slide, scale) => {
    const FLOOR = 24;
    const px = parseFloat(getComputedStyle(el).fontSize) || FLOOR;
    if (px >= FLOOR) return null;
    const elH = el.getBoundingClientRect().height / scale;
    const growNeeded = Math.round(elH * (FLOOR / px - 1));
    let node = el.parentElement, framed = null;
    while (node && node !== slide) {
      if (visIsFramedBox(node) && !visIsMediaBox(node)) { framed = node; break; }
      node = node.parentElement;
    }
    const target = framed || slide;
    const br = target.getBoundingClientRect();
    const cu = visContentUnion(target);
    const innerSlack = cu ? Math.max(0, (br.bottom - cu.bottom) / scale) : 0;
    const sr = slide.getBoundingClientRect();
    const canvasBelow = framed ? Math.max(0, (sr.bottom - br.bottom) / scale) : 0;
    const room = Math.round(innerSlack + canvasBelow);
    return { grow_needed_px: growNeeded, room_px: room,
      can_grow: growNeeded <= room, in_box: !!framed };
  };

  // ==========================================================================
  //  规则注册表 —— 唯一规则源。新增规则 = 往这里加一个 (slide, ctx) => findings。
  // ==========================================================================
  // ==========================================================================
  //  RULE_META · 覆盖契约登记表 (UNIFY-VALIDATE-ARCH §coverage, 2026-06-05)
  //  每条规则声明: coverage(universal|schema-only|raw-only|partial|stub) + signal
  //  (dom|css-source|text|bytes)。assertRuleContract() 强制:① RULES 每条都在此登记;
  //  ② coverage:'schema-only'|'raw-only'|'stub' 必须带 optout 辩护(为何不是 universal /
  //  raw 兜底计划)。新规则【默认 universal】(name-free,raw+schema 同覆盖);收窄要在此交
  //  可审查的税。测试 deck-json/tests/test_rule_contract.py 在 CI 阻断未登记/未辩护的规则。
  const RULE_META = {
    'R-VIS-CANVAS-CENTER': { coverage: 'universal', signal: 'dom' },
    'R-VIS-FILL': { coverage: 'raw-only', signal: 'dom', optout: 'layout!=="raw" early-return — name-free fill check, raw by design' },
    'R-ESC-HTML': { coverage: 'universal', signal: 'text' },
    'R12': { coverage: 'universal', signal: 'dom' },
    'R49': { coverage: 'universal', signal: 'dom' },
    'R-BULLET-DASH': { coverage: 'universal', signal: 'dom' },
    'R-WHITE-TEXT': { coverage: 'schema-only', signal: 'css-source', optout: 'css-source scan requires selector .slide/.card/.col; computed-DOM twin = R-VIS-DIM-TEXT' },
    'R-CSSVAR': { coverage: 'partial', signal: 'css-source', optout: 'deck-level css-source scan; name-free but single-shot' },
    'R10': { coverage: 'universal', signal: 'css-source' },
    'R-KEY': { coverage: 'universal', signal: 'dom' },
    'R07': { coverage: 'schema-only', signal: 'dom', optout: 'targets framework .wordmark.is-mono (auto-injected); only meaningful when .wordmark reused' },
    'R13': { coverage: 'universal', signal: 'dom' },
    'R38': { coverage: 'universal', signal: 'dom' },
    'R-LANG': { coverage: 'universal', signal: 'text' },
    'R06': { coverage: 'universal', signal: 'css-source' },
    'R20': { coverage: 'universal', signal: 'css-source' },
    'R-HIERARCHY': { coverage: 'schema-only', signal: 'css-source', optout: 'META_CLASS_RE hard gate (.owner/.kicker/.eyebrow); kicker vs caption indistinguishable by geometry — intrinsically name-bound' },
    'R05': { coverage: 'universal', signal: 'text' },
    'R56': { coverage: 'universal', signal: 'dom' },
    'R-VIS-SUBTITLE-CANON': { coverage: 'universal', signal: 'dom' },
    'R-ECHO': { coverage: 'universal', signal: 'text' },
    'R36': { coverage: 'partial', signal: 'css-source', optout: 'margin check name-free / grid check keyed on framework [data-mode=present]' },
    'R48': { coverage: 'schema-only', signal: 'css-source', optout: 'CSS regex keyed on [data-layout="<6 centerable>"]; raw via [data-role=stage] TODO (PR2)' },
    'R-EMPTY-HEADER-ZONE': { coverage: 'schema-only', signal: 'dom', optout: 'keyed on .header literal; raw via [data-role=header] + geometry TODO (PR2)' },
    'R47': { coverage: 'partial', signal: 'css-source', optout: 'css-source variant-discipline scan keyed on [data-variant]' },
    'R29-32': { coverage: 'universal', signal: 'css-source' },
    'R-VIS-NO-IMAGERY': { coverage: 'universal', signal: 'dom' },
    'R02-R07-STRUCTURE': { coverage: 'universal', signal: 'dom' },
    // composite rule (emits L1 / L2 / L4) — deck-level CSS-source scan over
    // deckOuterHTML(); evaluated once on the first in-scope frame. The emitted
    // codes L1/L2/L4 are registered in the other surfaces (FAMILIES / yaml /
    // validator-rules.md); this declares the rule's own id for the coverage contract.
    'L1/L2/L4': { coverage: 'universal', signal: 'css-source' },
    'R-VIS-LIFT-STYLE-LOST': { coverage: 'raw-only', signal: 'dom', optout: 'lifted raw slide style-preservation, raw by design' },
    'R-AUTOBALANCE-PRESENT': { coverage: 'universal', signal: 'dom' },
    'R-LAYOUT-DEPRECATED': { coverage: 'schema-only', signal: 'dom', optout: 'fires only on the FROZEN schema body layouts (F-305 «raw unless ceremonial»); raw is the preferred path and is never flagged — the narrowing IS the rule intent, not a coverage gap. Reads true authored layout from window.__DECK_JSON__ (not data-layout, which a raw page may borrow)' },
    'R-OVERFLOW': { coverage: 'universal', signal: 'dom' },
    'R-VIS-CARD-OVERFLOW': { coverage: 'universal', signal: 'dom' },
    'R-VIS-TIER': { coverage: 'partial', signal: 'dom', optout: 'card path keyed on .col/.num then name-free fallback' },
    'R-VIS-HIER': { coverage: 'partial', signal: 'dom', optout: 'card hierarchy keyed on .card' },
    'R-VIS-BODY-FLOOR': { coverage: 'universal', signal: 'dom' },
    'R-VIS-DIM-TEXT': { coverage: 'universal', signal: 'dom' },
    'R-VIS-ORPHAN': { coverage: 'universal', signal: 'dom' },
    'R-VIS-TITLE-POSITION': { coverage: 'schema-only', signal: 'dom', optout: 'keyed on :scope>.header>.title-zh; raw title position covered by R-VIS-RAW-TITLE-POS twin' },
    'R-VIS-RAW-TITLE-STACK': { coverage: 'raw-only', signal: 'dom', optout: 'layout!=="raw" early-return — name-free two-layer-title detector (R56 raw blind-spot), raw by design' },
    'R-VIS-RAW-TITLE-POS': { coverage: 'raw-only', signal: 'dom', optout: 'layout!=="raw" — the geometric raw twin of R-VIS-TITLE-POSITION' },
    'R-VIS-TITLE-GAP': { coverage: 'universal', signal: 'dom' },
    'R-VIS-CROWD': { coverage: 'universal', signal: 'dom' },
    'R-VIS-PANEL-TOP': { coverage: 'universal', signal: 'dom' },
    'R-VIS-BALANCE': { coverage: 'universal', signal: 'dom' },
    'R-VIS-GUTTER': { coverage: 'universal', signal: 'dom' },
    'R-OVERLAP': { coverage: 'universal', signal: 'dom' },
    'R-VIS-ABS-OVERLAP': { coverage: 'universal', signal: 'dom', optout: 'F-313 — two independently position:absolute text-blocks whose boxes overlap (R-OVERLAP skips absolute; R-VIS-BAND-COLLIDE needs a framework host). data-allow-overlap opts out.' },
    'R-VIS-BAND-COLLIDE': { coverage: 'schema-only', signal: 'dom', optout: 'host set = framework .stage/.grid/.flow...; raw via [data-role=flow|content-band] TODO (PR2)' },
    'R-VIS-ABSPOS-DUAL-ANCHOR': { coverage: 'universal', signal: 'dom' },
    'R-VIS-SLACK-FLEX': { coverage: 'universal', signal: 'dom' },
    'R-FOCAL-CHECK': { coverage: 'universal', signal: 'dom' },
    'R-VIS-PEER-SIZE': { coverage: 'universal', signal: 'dom' },
    // R-VIS-ALIGN: removed 2026-06-10 — was an unimplemented stub; alignment audit deferred.
    'R-LIFT-CSS-BUDGET': { coverage: 'universal', signal: 'dom', optout: 'fires ONLY on lifted slides (data-lifted provenance); clean/authored decks self-exempt — not a coverage narrowing but a scope inherent to the rule' },
    'R-CSS-INLINE-BUDGET': { coverage: 'universal', signal: 'dom' },
    'R-CSS-CROSS-PAGE': { coverage: 'universal', signal: 'dom' },
    'R-VIS-LABEL-FLOOR': { coverage: 'partial', signal: 'dom', optout: 'card label floor keyed on .card/-card/-tile/-cell/-panel/-box' },
    'R-VIS-OPT-OUT-ABUSE': { coverage: 'universal', signal: 'dom' },
    'R-VIS-CARD-MIN-HEIGHT-SPARSE': { coverage: 'universal', signal: 'dom' },
    'R-VIS-HERO-FLOOR': { coverage: 'schema-only', signal: 'dom', optout: 'HERO_FLOORS[layout] dict excludes raw; cheap name-free geometric twin TODO (PR2)' },
    'R-VIS-SHORT-LABEL-FLOOR': { coverage: 'universal', signal: 'dom' },
    'R-VIS-SVG-TEXT-FLOOR': { coverage: 'universal', signal: 'dom' },
    'R-VIS-DEAD-ANIM': { coverage: 'universal', signal: 'css-source' },
    'R-VIS-DEAD-RULE': { coverage: 'universal', signal: 'css-source' },
    'R-DOM': { coverage: 'universal', signal: 'dom' },
    // 注入面最低防线 (F-287) — 非框架来源的可执行内容(<script> / on* 事件)。universal:
    // raw 页可任意 markup、schema 页一律无脚本 → 两类都该查。严重度按来源分级(lifted/imported
    // 页 = error,普通生成页 = warn);框架自注入脚本(data-source=framework / framework src /
    // 非可执行 type)豁免,且只扫 .slide 子树(body 级框架脚本天然在外)。
    'R-FOREIGN-SCRIPT': { coverage: 'universal', signal: 'dom', optout: 'severity is provenance-graded (lifted/imported→error, authored→warn) not a coverage narrowing; raw + schema both scanned; data-allow-foreign-script per-slide escape for an intentionally-scripted bespoke raw page' },
    // 离线可用性最低防线 (2026-06-11) — 远程 iframe 让 load 事件在离线/headless 下挂死,
    // 现场无网/未登录时 live demo 静默失效。name-free,raw + schema 同覆盖。
    'R-IFRAME-REMOTE': { coverage: 'universal', signal: 'dom' },
    // 内嵌看板 iframe 的不透明深色内底 = 边缘黑边 (2026-06-21) — 解码 data: 载荷查内层
    // html/body/.stage-host/.slide 的 background。name-free,raw + schema 同覆盖。
    'R-EMBED-OPAQUE-BG': { coverage: 'universal', signal: 'dom' },
    'UI1': { coverage: 'universal', signal: 'dom' },
    // 跨页一致性 (DECK-LEVEL · F-257) — deck 级求值,name-free,均 universal(raw+schema
    // 都跑;opt-out 是显式逃生口,不是 coverage 收窄)。
    'R-DECK-TITLE-DRIFT': { coverage: 'universal', signal: 'dom' },
    'R-DECK-PALETTE-DRIFT': { coverage: 'universal', signal: 'css-source' },
    'R-DECK-TYPESCALE-BUDGET': { coverage: 'universal', signal: 'css-source' },
    // 跨页一致性续 (DECK-LEVEL · F-349 eyebrow 预算 / F-350 圆角体系) + 对比度地板
    // (F-351 WCAG)。均 name-free、universal(raw+schema 都跑);opt-out 是逃生口非收窄。
    'R-DECK-EYEBROW-BUDGET': { coverage: 'universal', signal: 'dom' },
    'R-DECK-RADIUS-DRIFT': { coverage: 'universal', signal: 'css-source' },
    'R-VIS-CONTRAST-WCAG': { coverage: 'universal', signal: 'dom' },
  };

  // Contract assertion — pure data check, never throws at engine load (a bad entry
  // must fail CI, not break every deck's validation). Returns a list of violations.
  function assertRuleContract(ruleIds, meta) {
    const v = [];
    for (const id of ruleIds) {
      const m = meta[id];
      if (!m) { v.push(`${id}: no RULE_META entry (declare coverage)`); continue; }
      if ((m.coverage === 'schema-only' || m.coverage === 'raw-only' || m.coverage === 'stub') && !m.optout) {
        v.push(`${id}: coverage='${m.coverage}' requires an optout justification`);
      }
    }
    for (const id of Object.keys(meta)) {
      if (!ruleIds.includes(id)) v.push(`${id}: RULE_META entry has no matching rule in RULES`);
    }
    return v;
  }

  const RULES = [
    {
      // R-VIS-CANVAS-CENTER · 内容并集相对"画布"垂直居中 (2026-05-31)
      // 画布 = [标题带 .header 底边 → 屏幕底 1080];内容并集(排除 .header / 绝对定位 /
      // 隐藏 / 过小 / 被裁)的垂直中心 content_mid 应 ≈ 画布中心 (hb+1080)/2。
      //   offset = canvas_mid - content_mid   (>0 偏上, <0 偏下)
      //   is_full = 内容比可用带还高 → 居中必溢出画布 → 顶对齐是对的,豁免。
      // |offset| > 40 判失衡(warn,留白判断主观,可 data-allow-imbalance opt-out)。
      // 几何全部先减 slide 顶、再 / scale 还原成设计 px,与 1080 同系。
      // F-301 (2026-06-11):锚点语义明确为「标题带底边」—— header bbox 天然含
      // .page-sub 副标,所以带底=副标底(有副标)/主标底(无副标),与框架运行时
      // setBandAnchor / canvas-center 同口径;header 改用 findSlideHeader 探测,
      // 兼容 .land>.header 嵌一层的 bespoke 满幅 raw 页(旧 `:scope>.header` 摸空
      // → hb=0 → 错用全画布中心 540 评带下内容,raw twin TODO(PR2) 由此关闭,
      // coverage 升 universal)。
      id: 'R-VIS-CANVAS-CENTER',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, scale, isHeroLayout } = ctx;
        if (isHeroLayout || slide.hasAttribute('data-allow-imbalance')) return [];

        const _ccSr = slide.getBoundingClientRect();
        const _ccSlideTop = _ccSr.top;
        const ccHeader = findSlideHeader(slide);
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
      // R-VIS-FILL · 内容没填满可用画布 = "空洞" (2026-06-04).
      // R-VIS-CANVAS-CENTER 查"内容并集有没有居中",但对【居中的稀疏内容】无能为力:
      // justify-content:center 把空白对称地藏在上下,balance / canvas-center 都看着均衡 →
      // 放行(正是世界坚果协会 deck 第一版"过了校验却空洞"的盲区)。这条补盲:复用同一套
      // 内容并集(text+media 叶、非 absolute、可见、overflow 裁剪),量 contentH / 可用带高;
      // < 阈值 → 内容太稀、撑不满版面。可用带 = [.header 底(无则 0)→ 1080]。hero / section
      // 等极简版式由 isHeroLayout 豁免,data-allow-imbalance 显式豁免。warn(留白阈值主观)。
      id: 'R-VIS-FILL',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, layout, scale, isHeroLayout } = ctx;
        // 只查 raw 页:schema 版式(content/stats/flow/…)由框架版式约束填充+居中,且
        // 既有 R-VIS-BALANCE / CANVAS-CENTER 已覆盖,本规则不二次猜测(否则误报正常 schema 页)。
        if (layout !== 'raw') return [];
        if (isHeroLayout || slide.hasAttribute('data-allow-imbalance')) return [];
        const sr = slide.getBoundingClientRect();
        const slideTop = sr.top;
        const hdr = slide.querySelector(':scope > .header');
        const hdrRendered = !!hdr && hdr.getClientRects().length > 0;
        const hb = hdrRendered ? (hdr.getBoundingClientRect().bottom - slideTop) / scale : 0;
        // 只量内容台(.raw-stage / .stage)里的东西 —— 框架 chrome(wordmark / pageno)在台
        // 外、贴屏幕边,若混进并集会把内容撑到满高、把"空洞"伪装成"填满"。台内再排页脚。
        const stageEl = slide.querySelector('.raw-stage')
          || slide.querySelector(':scope > .stage') || slide;
        let top = Infinity, bot = -Infinity, any = false;
        stageEl.querySelectorAll('*').forEach((el) => {
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return;
          if (hdr && (el === hdr || hdr.contains(el))) return;
          // 台内的页脚 / 页码 / 水印 / 品牌标也排掉(footnote 贴底,最坑)。
          if (visHasAnyClass(el, ['foot', 'pageno', 'wordmark', 'logo', 'brand', 'watermark', 'copyright'])) return;
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return;
          if (cs.position === 'absolute' || cs.position === 'fixed') return;
          const tag = el.tagName;
          const isMedia = tag === 'IMG' || tag === 'SVG' || tag === 'svg'
            || tag === 'CANVAS' || tag === 'VIDEO';
          const isLeaf = el.children.length === 0;
          // 带框的卡/盒(border/bg)也算"填了":卡片撑满高度即占了版面;卡内文字贴顶是
          // 卡内对齐问题(R-VIS-CROWD/PANEL-TOP 管),不该让满高卡被本规则判成空洞。
          const isFramed = visIsFramedBox(el) && !visIsMediaBox(el);
          if (!hasOwnText(el) && !isMedia && !isLeaf && !isFramed) return;
          const r = el.getBoundingClientRect();
          if (r.width < 6 || r.height < 6) return;
          // overflow 裁剪(同 canvas-center):被非可见溢出祖先裁掉的部分不计。
          let vt = r.top, vb = r.bottom;
          for (let p = el.parentElement; p && p !== slide; p = p.parentElement) {
            if (getComputedStyle(p).overflowY !== 'visible') {
              const pr = p.getBoundingClientRect();
              if (pr.top > vt) vt = pr.top;
              if (pr.bottom < vb) vb = pr.bottom;
            }
          }
          if (vb - vt < 6) return;
          const t = (vt - slideTop) / scale, b = (vb - slideTop) / scale;
          if (t < top) top = t;
          if (b > bot) bot = b;
          any = true;
        });
        if (!any) return [];
        const contentH = bot - top;
        const bandH = 1080 - hb;
        if (bandH <= 8) return [];
        const fill = contentH / bandH;
        const THRESHOLD = 0.52;
        if (fill >= THRESHOLD) return [];
        return [{
          rule: 'R-VIS-FILL', severity: 'warn', slide_idx,
          fill_pct: Math.round(fill * 100), content_h: Math.round(contentH),
          band_h: Math.round(bandH), container_sel: shortSel(slide),
          message:
            `slide ${slide_idx} · 内容只填满可用画布的 ${Math.round(fill * 100)}% `
            + `(内容高 ${Math.round(contentH)}px / 可用带 ${Math.round(bandH)}px,阈值 `
            + `${Math.round(THRESHOLD * 100)}%) —— 页面偏空("空洞")。居中`
            + '(justify-content:center)只会把空白对称藏在上下,balance/canvas-center 看着'
            + '均衡所以漏报,这条专补。Fix: 放大主视觉 / 加支撑结构(轴 / 图例 / 数据点 / '
            + '卡片)把版面填实,或收紧留白;确属极简设计意图用 `data-allow-imbalance`。',
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
      // 原 CSS 注释 opt-out `/* allow:drop-shadow */`:① 框架里有 sanctioned depth shadow
      // 的元素类(每个在框架 CSS 里都带 `/* allow:drop-shadow */`:ui-window/phone-frame/
      // desktop-frame/browser-frame/app-frame 是 UI-mock 窗体,scene-frame 是 story-case
      // 纪实影像框 feishu-deck-patterns.css)豁免 ② `data-allow-drop-shadow` 属性 opt-out
      // (就近祖先链) ③ **R12 parity restore**:作者 `<style>` 规则块里写 `/* allow:drop-shadow */`
      // 的注释 opt-out。computed 里看不到注释,但 R20 已有的「读 <style> textContent + 注释容忍
      // 拆规则」机制(iterStyleBlocks/iterCssRules)能拿到含注释的规则源 —— 复用它收集所有带
      // marker 的选择器,元素 .matches() 命中任一即豁免。与 R20 的 /* allow:typescale */ /
      // R-WHITE-TEXT 的 /* allow:white-opacity */ 同一约定(迁移时被砍掉,只剩 data-* 属性,
      // 与 R20 不一致 → 这里恢复)。
      id: 'R12',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const UI_MOCK = ['ui-window', 'phone-frame', 'desktop-frame', 'browser-frame', 'app-frame', 'scene-frame'];
        const findings = [];
        const flaggedSel = new Set();   // 同一 selector(短选择器)一页只报一次,降噪
        // /* allow:drop-shadow */ 注释 opt-out:从作者 <style> 收集所有 marker 规则的选择器
        // (R20 同套 textContent 扫描 + 注释容忍拆规则)。deck 级算一次,缓存到 window。
        let dsExemptSelectors;
        if (typeof window !== 'undefined' && window.__R12_DS_EXEMPT__) {
          dsExemptSelectors = window.__R12_DS_EXEMPT__;
        } else {
          dsExemptSelectors = [];
          for (const { css } of iterStyleBlocks(false)) {     // 作者 CSS,排除框架
            for (const { selector, body } of iterCssRules(css)) {
              if (body.indexOf('allow:drop-shadow') < 0) continue;
              for (const s of selector.split(',')) {
                const n = s.trim();
                if (n) dsExemptSelectors.push(n);
              }
            }
          }
          if (typeof window !== 'undefined') window.__R12_DS_EXEMPT__ = dsExemptSelectors;
        }
        const dsCommentExempt = (el) => {
          for (const sel of dsExemptSelectors) {
            try { if (el.matches && el.matches(sel)) return true; }
            catch (e) { /* 选择器本环境无法解析 → 跳过 */ }
          }
          return false;
        };
        const all = [slide, ...slide.querySelectorAll('*')];
        for (const el of all) {
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') continue;
          const chain = classChain(el, slide);
          if (chain.some((c) => UI_MOCK.includes(c))) continue;          // UI-mock 窗体豁免
          if (inMockupRoot(el, slide.parentElement)) continue;           // F-358 mockup 沙箱
          if (dsCommentExempt(el)) continue;                             // /* allow:drop-shadow */ 注释豁免
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
        const findings = [];
        const flaggedSel = new Set();
        // NB: do NOT early-return when authorRules is empty — the inline style=""
        // second pass below must still run (a deck may carry inline soft-white with
        // no offending author CSS rule at all). The CSS-rule loop simply no-ops.
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
            if (inMockupRoot(el, slide.parentElement)) continue;   // F-358 mockup 沙箱
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
        // inline style="" 第二遍(parity:原版 audit_white_text 在扫作者 CSS 规则之外
        // 还扫 markup 里 `style="...color:rgba(255,255,255,<1)"` 的 inline 声明 —— 迁移时
        // 漏掉,inline soft-white 静默漏报)。镜像 R06 的 inline 分支:遍历 slide 全体元素读
        // el.getAttribute('style'),命中低透纯白即报。沿用同套 opt-out:
        //   · data-allow-white-opacity(就近祖先链)豁免;
        //   · inline 自带 font-size<=14 → chrome floor 豁免(与规则级 FS_PX_RE<=14 一致)。
        // 用 "<inline>" 当 container_sel 锚定(原版 inline 命中无 selector 上下文)。
        for (const el of [slide, ...slide.querySelectorAll('*')]) {
          const tag = el.tagName;
          if (tag === 'STYLE' || tag === 'SCRIPT') continue;
          const styleAttr = el.getAttribute && el.getAttribute('style');
          if (!styleAttr) continue;
          if (!SOFT_WHITE_DECL_RE.test(styleAttr)) continue;
          const fsM = FS_PX_RE.exec(styleAttr);
          if (fsM && parseInt(fsM[1], 10) <= 14) continue;   // inline chrome floor 豁免
          if (inMockupRoot(el, slide.parentElement)) continue;   // F-358 mockup 沙箱
          let optOut = false;
          for (let p = el; p && p !== slide.parentElement; p = p.parentElement) {
            if (p.hasAttribute && p.hasAttribute('data-allow-white-opacity')) { optOut = true; break; }
          }
          if (optOut) continue;
          const cs = getComputedStyle(el);
          findings.push({
            rule: 'R-WHITE-TEXT',
            severity: 'warn',
            slide_idx,
            container_sel: '<inline>',
            color: cs.color,
            message:
              `slide ${slide_idx}: soft-white text on \`<inline>\` (${shortSel(el)}) — \`${cs.color}\`. ` +
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
        const tally = (str) => {
          if (!str) return;
          const v = str.replace(/data:[^"'\s)]+/g, '');
          let m;
          HEX_RE.lastIndex = 0;
          while ((m = HEX_RE.exec(v))) {
            const h = m[1].toLowerCase();
            if (ALLOWED_HEX.has(h)) continue;
            counts[h] = (counts[h] || 0) + 1;
          }
        };
        // 遍历所有 slide 里元素的 inline style(markup 写死的 hex 都在这);svg 内部 / style /
        // script 跳过(原版 strip svg/style/script)。保险起见对 style 值剥掉 data: 段
        // (base64 里的 #xxx 假阳)。
        const inlineSeen = new Set();   // (slide, el) 已计过 inline → 序列化扫描时去重
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
            inlineSeen.add(el);
            tally(styleAttr);
          }
          // parity restore:原版 audit_hex_palette 扫【整个 <body> markup】(剥
          // script/style/svg/data:),不只是 inline style —— 文本节点 / 属性里写死的
          // #hex(如 `<text fill="#c00">` 之外的内容、`data-color="#abc"`、纯文本提到色号)
          // 迁移时漏掉,只剩 inline style 一路 → 大量 off-palette hex 静默漏报。
          // 这里对 slide 的 serialized outerHTML 同款 strip(<script>/<style>/<svg>/data:)后
          // 再扫,与上面的 inline 扫描 DE-DUPE:已在 inline 计过的元素其 style 属性会随
          // outerHTML 再次出现,故先把这些元素的 style 值从序列化串里挖掉,避免双计。
          let markup = slideOuterHTML(sl);
          markup = markup
            .replace(/<script[\s\S]*?<\/script>/gi, '')
            .replace(/<style[\s\S]*?<\/style>/gi, '')
            .replace(/<svg[\s\S]*?<\/svg>/gi, '');
          // 把已 inline 计过的 style="…" 整段移除(去重,防双报)。
          for (const el of inlineSeen) {
            const sa = el.getAttribute && el.getAttribute('style');
            if (!sa) continue;
            // 移除该确切 style 值出现处(简单字面替换,够用)。
            markup = markup.split(sa).join('');
          }
          tally(markup);
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
      // _validate_audits.py audit_data_decor)。原版 `audit_data_decor` 用
      // `slide_attr(fr, 'decor')` 在【整帧 markup】里找 data-decor(不限于 .slide 根元素),
      // 渲染后等价 = .slide 自身 + 后代 querySelectorAll('[data-decor]') 全验
      // (parity restore:之前只读 slide.getAttribute('data-decor') → 挂在 stage / 装饰子
      // 元素上的 data-decor 拼错时静默漏报)。任一 token 不在 ALLOWED_DECOR 即报 err。
      id: 'R38',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const findings = [];
        // 与 Python `sorted(ALLOWED_DECOR)` 的 repr 完全一致(单引号、', ' 分隔、[] 包裹)。
        const allowedRepr = '[' + [...ALLOWED_DECOR].sort().map((t) => `'${t}'`).join(', ') + ']';
        const seen = new Set();   // 同一 token 一帧只报一次,降噪
        for (const el of [slide, ...slide.querySelectorAll('[data-decor]')]) {
          const decor = el.getAttribute && el.getAttribute('data-decor');
          if (!decor) continue;
          for (const token of decor.split(/\s+/).filter(Boolean)) {
            if (ALLOWED_DECOR.has(token)) continue;
            if (seen.has(token)) continue;
            seen.add(token);
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
            'acronym, add it to LATIN_BRAND_WHITELIST in audits.js; ' +
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
              'LATIN_BRAND_WHITELIST in audits.js if it is ' +
              'genuinely a brand / acronym.');
          }
        }

        return findings;
      },
    },

    {
      // R06 · slide 内容字号下限(chrome 14 / body 22)。(步骤 3 第三批迁自
      // _validate_audits.py audit_font_sizes)。原版扫【所有 <style> 块(含框架)】的 CSS
      // 规则文本,按 selector 分 chrome / body floor,声明字号 < floor 即报;另扫 inline style 的
      // font-size(仅 chrome floor)。两道地板 honor `/* allow:typescale */`(整豁免)与
      // `/* allow:body-floor */`(仅免 body 地板)。lifted 页(selector 命中 lifted slide-key)err→warn。
      //
      // 移植方式(与原版【规则文本】扫描逐字对齐 —— 见本批迁移说明):本规则对【渲染后 DOM 里
      // 的 <style> 节点 textContent】做与 Python 同套正则扫描(selector + 声明字号 + allow 注释
      // marker 全在一处、自洽),而非"CSSOM 规则 → 匹配元素 computed"。原因:
      //   ① CSSOM cssText 不含注释 → 读不到 allow:* marker;按 selectorText 反查原文又会因
      //      CSSOM 归一化空白/属性引号而错配(实测漏报)。
      //   ② "声明 100px、var() 失败实渲 16px"的冰山由 R-CSSVAR(已迁)直接抓未定义 var,R06 不必重做。
      //   ③ 原版即"未被任何元素使用的 CSS 规则也照报"——CSSOM+querySelectorAll 会因 0 匹配漏掉
      //      这些规则(实测 .fs-claim-row__label / .arch-top 等成片漏);扫规则文本则与原版一致。
      // 渲染后 <style> textContent 原样保留注释(实测 allow:typescale 56× 可读),故 marker 直读。
      // deck 级(原版扫整份 HTML),整 deck 算一次挂第一帧。
      id: 'R06',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__R06_DONE__) return [];
        if (!ctx.isFirstInScope) return [];
        if (typeof window !== 'undefined') window.__R06_DONE__ = true;

        // R06 的内容 gate:selector 命中 slide 内容类(token 边界与原版一致)。
        const passesContentGate = (selector) => {
          if (selector.indexOf('.deck-ui') >= 0 || selector.indexOf('.deck-controls') >= 0
            || selector.indexOf('.deck-progress') >= 0 || selector.indexOf('.mode-toggle') >= 0
            || selector.indexOf('.nav-hint') >= 0 || selector.indexOf('.pager') >= 0
            || selector.indexOf('.hint') >= 0 || selector.indexOf('.fs-mobile') >= 0
            || selector.indexOf('.fullscreen') >= 0 || selector.indexOf('@') >= 0) return false;
          if (selector.indexOf('.slide') < 0 && selector.indexOf('.card') < 0
            && !/\.col(?![\w-])/.test(selector) && selector.indexOf('.toc') < 0
            && !/\.cell(?![\w-])/.test(selector) && selector.indexOf('thead') < 0
            && selector.indexOf('tbody') < 0) return false;
          return true;
        };

        // lifted slide-keys(对应 _lifted_slide_keys):data-lifted 帧的 data-slide-key。
        const liftedKeys = new Set();
        const allSlides = (typeof document !== 'undefined' && document.querySelectorAll('.slide')) || [];
        for (const sl of allSlides) {
          if (slideIsLifted(sl)) {
            const k = sl.getAttribute('data-slide-key');
            if (k) liftedKeys.add(k);
          }
        }
        const selectorIsLifted = (selector) =>
          [...liftedKeys].some((k) => selector.indexOf(`data-slide-key="${k}"`) >= 0);

        const bodyViolations = [];     // {size, sel}
        const chromeViolations = [];

        // 扫所有 <style> 块(含框架),按规则文本判定(对应 _iter_style_blocks(html) 默认 include_framework=True)。
        for (const { css } of iterStyleBlocks(true)) {
          for (const { selector: rawSel, body } of iterCssRules(css)) {
            const selector = rawSel.trim();
            if (!passesContentGate(selector)) continue;
            // opt-out marker(body 仍含注释)。
            if (body.indexOf('allow:typescale') >= 0) continue;   // 整豁免
            const allowBodyFloor = body.indexOf('allow:body-floor') >= 0;
            const isChrome = CHROME_CLASS_RE.test(selector);
            const isBody = BODY_CLASS_RE.test(selector) && !isChrome;
            const block = stripCssComments(body);
            for (const size of collectFontSizes(block)) {
              if (isBody && !allowBodyFloor) {
                if (size < FLOOR_BODY_PX) bodyViolations.push({ size, sel: selector });
              } else if (size < FLOOR_CHROME_PX) {
                chromeViolations.push({ size, sel: selector });
              }
            }
          }
        }

        const findings = [];
        const levNote = (sel) => selectorIsLifted(sel)
          ? { sev: 'warn', note: ' — LIFTED slide (verbatim from another deck); '
              + 'downgraded to WARNING, you choose whether to bump the font' }
          : { sev: 'error', note: '' };

        for (const { size, sel } of chromeViolations.slice(0, 10)) {
          const { sev, note } = levNote(sel);
          findings.push({
            rule: 'R06', severity: sev, slide_idx, container_sel: sel,
            message: `font-size ${size}px on \`${sel}\` below `
              + `${FLOOR_CHROME_PX}px chrome floor${note}`,
          });
        }
        for (const { size, sel } of bodyViolations.slice(0, 10)) {
          const { sev, note } = levNote(sel);
          findings.push({
            rule: 'R06', severity: sev, slide_idx, container_sel: sel,
            message: `font-size ${size}px on \`${sel}\` below `
              + `${FLOOR_BODY_PX}px BODY floor — selector looks like body content `
              + '(card body / description / caption / list / cell / arch-* / etc.) '
              + 'and projector readability requires ≥ 22 px. Bump to 22, OR if '
              + 'this is genuinely chrome, rename to a chrome class '
              + '(.eyebrow / .footnote / .source / .pill / .tag / etc.), OR '
              + `add /* allow:body-floor */ in the rule for a documented exception.${note}`,
          });
        }

        // inline style 的 font-size(仅 chrome floor)。原版扫 <body> markup 里
        // `style="...font-size:Npx"`(剥 comment / script)。渲染后等价 = 遍历元素 style 属性。
        for (const sl of allSlides) {
          for (const el of [sl, ...sl.querySelectorAll('*')]) {
            const tag = el.tagName;
            if (tag === 'STYLE' || tag === 'SCRIPT') continue;
            const styleAttr = el.getAttribute && el.getAttribute('style');
            if (!styleAttr) continue;
            const mm = /font-size:\s*(\d+)px/.exec(styleAttr);
            if (!mm) continue;
            const size = parseInt(mm[1], 10);
            if (size >= FLOOR_CHROME_PX) continue;
            // inline 无 selector 上下文 → 原版 _lev('') 永不命中 lifted-key → 恒 err。
            findings.push({
              rule: 'R06', severity: 'error', slide_idx, container_sel: shortSel(el),
              message: `inline font-size ${size}px below ${FLOOR_CHROME_PX}px floor`,
            });
          }
        }
        return findings;
      },
    },

    {
      // R20 · 每个 per-page 字号必须落在 4-tier 台阶(16/24/28/48)。(步骤 3 第三批迁自
      // _validate_audits.py audit_type_ladder)。原版只审 selector 含 `[data-page="NN"]` 或
      // `[data-slide-key="..."]` 的规则(框架 master-spec 豁免);off-ladder 即报,给最近台阶;
      // `/* allow:typescale */` 整豁免(hero 例外 + mockup-internal 10-13);lifted 页 err→warn。
      //
      // 移植方式(同 R06 ── 对渲染后 <style> textContent 做与 Python 同套规则文本扫描):
      //   · 只取 selector 含 [data-page= / [data-slide-key= 的规则(框架 master-spec 用 class
      //     选择器,自然被 gate 排除);跳 selector 含 @ 者。
      //   · 字号读规则声明值(font-size + font 缩写);allow:typescale 注释 marker 直读 body。
      //   · (size, selector[:80]) 去重;nearest tier 取最近(等距时按 ladder 集合迭代序,
      //     与 Python `min(set, key=abs)` 同 —— 见下 nearestTier)。lifted 页 err→warn。
      // 沿用原版"规则声明即报(不要求元素真用到)"的语义。冰山(var 失败实渲 16px)由 R-CSSVAR 抓。
      // deck 级,整 deck 算一次挂第一帧。
      id: 'R20',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__R20_DONE__) return [];
        if (!ctx.isFirstInScope) return [];
        if (typeof window !== 'undefined') window.__R20_DONE__ = true;

        const liftedKeys = new Set();
        const allSlides = (typeof document !== 'undefined' && document.querySelectorAll('.slide')) || [];
        for (const sl of allSlides) {
          if (slideIsLifted(sl)) {
            const k = sl.getAttribute('data-slide-key');
            if (k) liftedKeys.add(k);
          }
        }
        const selectorIsLifted = (selector) =>
          [...liftedKeys].some((k) => selector.indexOf(`data-slide-key="${k}"`) >= 0);

        // nearest tier:与 Python `min(TYPE_LADDER_PX, key=lambda r: abs(r-size))` 完全一致 ——
        // 含等距 tie-break。Python set 迭代序对 {48,28,24,16}(由 _FS_TOKENS.values() 插入序经
        // CPython set-hash 得到)实测为 [48, 24, 28, 16];min 保留首个达到最小 key 者。等距时这给出:
        // 20→24 / 26→24 / 38→48(并非升序的 16/24/28)。须照搬该迭代序才能逐字对齐。
        // 若框架 CSS 改了台阶值(集合不再是这四个),退回升序遍历(此时 4-tier 已变,对齐基准也变)。
        // F-358: off-ladder font on a mockup-internal selector is simulated UI, not page text.
        const selectorAllInMockup = (selector) => {
          if (typeof document === 'undefined') return false;
          let els;
          try { els = document.querySelectorAll(selector); } catch (e) { return false; }
          if (!els.length) return false;
          for (const el of els) { if (!inMockupRoot(el, null)) return false; }
          return true;
        };

        const PY_LADDER_ORDER = [48, 24, 28, 16];
        const ladderIter = PY_LADDER_ORDER.every((v) => TYPE_LADDER_PX.has(v))
          && TYPE_LADDER_PX.size === PY_LADDER_ORDER.length
          ? PY_LADDER_ORDER
          : [...TYPE_LADDER_PX].sort((a, b) => a - b);
        const nearestTier = (size) => {
          let best = Infinity, nearest = null;
          for (const t of ladderIter) {
            const d = Math.abs(t - size);
            if (d < best) { best = d; nearest = t; }   // 严格 < → 等距保留首个(与 Python min 一致)
          }
          return nearest;
        };

        const findings = [];
        const seen = new Set();
        for (const { css } of iterStyleBlocks(true)) {
          for (const { selector: rawSel, body } of iterCssRules(css)) {
            const selector = rawSel.trim();
            if (selector.indexOf('[data-page=') < 0 && selector.indexOf('[data-slide-key=') < 0) continue;
            if (selector.indexOf('@') >= 0) continue;
            if (body.indexOf('allow:typescale') >= 0) continue;
            if (selectorAllInMockup(selector)) continue;   // F-358 mockup 沙箱
            const block = stripCssComments(body);
            for (const size of collectFontSizes(block)) {
              if (TYPE_LADDER_PX.has(size)) continue;
              const sel80 = selector.slice(0, 80);
              const dedup = `${size}|${sel80}`;
              if (seen.has(dedup)) continue;
              seen.add(dedup);
              const nearest = nearestTier(size);
              const lifted = selectorIsLifted(selector);
              const sev = lifted ? 'warn' : 'error';
              const note = lifted
                ? ' — LIFTED slide (verbatim from another deck); '
                  + 'downgraded to WARNING, you choose whether to snap '
                  + 'to the type ladder'
                : '';
              findings.push({
                rule: 'R20', severity: sev, slide_idx, container_sel: sel80,
                message: `font-size ${size}px on \`${sel80}\` is off-tier; `
                  + `snap it to the nearest tier = ${nearest}px `
                  + '(allowed: 16 Foot / 24 Body / 28 Sub / 48 Title — '
                  + '4-tier strict per the canonical PPT→Web mapping). '
                  + '`/* allow:typescale */` is a NARROW escape hatch for a '
                  + 'genuine HERO numeral only (cover 100, section 88/160, '
                  + 'big-stat 132+, quote 88+, or mockup-internal 10-13) — '
                  + 'it is not a way to silence this check. If this size is body / '
                  + `label / heading text, pull it onto the ladder instead.${note}`,
              });
            }
          }
        }
        return findings;
      },
    },

    {
      // R-HIERARCHY · card/panel 内 meta 类字号不得超过 body 地板。(步骤 3 第三批迁自
      // _validate_audits.py audit_hierarchy)。原版只审【作者 CSS】里 selector 命中 META_CLASS_RE
      // (owner/attrib/source/who/byline/timestamp/date/status/kicker/eyebrow…)、非 column-label、
      // 无 `/* allow:meta-larger */`、font-size > body floor(24)的规则 → warn。
      // 移植方式(同 R06/R20 ── 对渲染后【作者】<style> textContent 做规则文本扫描):
      //   · 仅作者 CSS(iterStyleBlocks(false),框架表 data-source=framework 排除)。
      //   · selector 先剥注释再判 META_CLASS_RE / COLUMN_LABEL_RE;body 含 allow:meta-larger 整跳。
      //   · 声明字号 > FLOOR_BODY_PX 即报,一规则一报(对应原版 break);无跨规则去重(同原版)。
      // deck 级,整 deck 算一次挂第一帧。
      id: 'R-HIERARCHY',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__RHIER_DONE__) return [];
        if (!ctx.isFirstInScope) return [];
        if (typeof window !== 'undefined') window.__RHIER_DONE__ = true;

        const findings = [];
        for (const { css } of iterStyleBlocks(false)) {   // 仅作者 CSS
          for (const { selector: rawSel, body } of iterCssRules(css)) {
            const selector = stripCssComments(rawSel).trim();
            if (!selector) continue;
            if (body.indexOf('allow:meta-larger') >= 0) continue;
            if (!META_CLASS_RE.test(selector)) continue;
            if (COLUMN_LABEL_RE.test(selector)) continue;
            const block = stripCssComments(body);
            const sizes = collectFontSizes(block);
            for (const size of sizes) {
              if (size > FLOOR_BODY_PX) {
                const sel80 = selector.slice(0, 80);
                findings.push({
                  rule: 'R-HIERARCHY', severity: 'warn', slide_idx, container_sel: sel80,
                  message: `meta-class selector \`${sel80}\` at `
                    + `${size}px (> body floor ${FLOOR_BODY_PX}px). Meta `
                    + '(owner / attrib / source / timestamp / kicker / '
                    + 'eyebrow) must NOT exceed body — otherwise visual '
                    + 'hierarchy reads inverted: the reader\'s eye '
                    + 'lands on "who" before "what". Drop to ≤ 24, OR '
                    + 'add `/* allow:meta-larger */` if this is a '
                    + 'deliberate hero exception (very rare). If this '
                    + 'is actually a column-LABEL (e.g. column-pill, '
                    + 'side-pill), rename the class — column labels '
                    + 'belong to a different name bucket.',
                });
                break;   // 一规则一报(对应原版 break)
              }
            }
          }
        }
        return findings;
      },
    },

    {
      // R05 · slide 文本里禁 emoji / '!' / '…' / '???'。(步骤 3 第三批迁自
      // _validate_audits.py audit_copy_rules)。原版扫 <body> 文本(剥 script/style/svg/标签),
      // 命中即报;IMPORTED deck(全 lifted / origin=imported)降 warn_soft(忠实搬运的外来内容,
      // 人来决定是否清洗),否则 err。每类标点一条 finding。
      // 移植:渲染后扫【整个 <body> 的可见文本】(textContent,剥 script/style/svg 子树),按同四类
      // 判定 —— 与原版"扫 <body> 文本(剥 script/style/svg/标签)"对齐(含 deck chrome,不止 .slide)。
      // 原版按整 body 一次扫(无法归帧)→ 这里挂第一帧、对整 deck 文本判定(deck 级,等价)。
      id: 'R05',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__R05_DONE__) return [];
        if (!ctx.isFirstInScope) return [];
        if (typeof window !== 'undefined') window.__R05_DONE__ = true;

        let text = '';
        if (typeof document !== 'undefined' && document.body) {
          const clone = document.body.cloneNode(true);
          clone.querySelectorAll('style, script, svg').forEach((n) => n.remove());
          text = clone.textContent || '';
        }

        const imported = deckAllImported();
        const note = imported
          ? ' — IMPORTED deck (verbatim-carried content); downgraded to '
            + 'WARNING, you choose whether to clean up the source text'
          : '';
        const sev = imported ? 'warn_soft' : 'error';
        const findings = [];
        const emit = (msg) => findings.push({
          rule: 'R05', severity: sev, slide_idx, message: msg + note,
        });

        // emoji(与原版三段 surrogate 区段同义,JS 用 Unicode 属性 escapes / 显式区段)。
        const EMOJI_RE = /[\u{1F300}-\u{1FAFF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}]/u;
        if (EMOJI_RE.test(text)) emit('emoji detected in slide text');
        if (text.indexOf('!') >= 0 || text.indexOf('！') >= 0) {
          emit("exclamation '!' / '！' detected in slide text");
        }
        if (text.indexOf('…') >= 0 || text.indexOf('...') >= 0) {
          emit("ellipsis '…' / '...' detected in slide text");
        }
        if (text.indexOf('???') >= 0 || text.indexOf('？？？') >= 0) {
          emit("'???' detected in slide text");
        }
        return findings;
      },
    },

    {
      // R56 · 内容页 .header 只许放单个标题,不许 .eyebrow。(步骤 3 第三批迁自
      // _validate_audits.py audit_header_minimal)。原版遍历非 hero-title 版式的 slide,
      // 用 _walk_text_leaves 找"叶自身或祖先链含 eyebrow、且祖先链含 header"的文本叶 → warn,
      // 一帧一条。移植:渲染后等价 = slide 内 .header 后代里有 .eyebrow 元素。
      id: 'R56',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, layout } = ctx;
        if (HERO_TITLE_LAYOUTS.has(layout)) return [];
        // querySelectorAll 直接命中 .header 内的 .eyebrow(等价于"叶/祖先含 eyebrow 且祖先含 header")。
        const hit = slide.querySelector('.header .eyebrow');
        if (!hit) return [];
        return [{
          rule: 'R56', severity: 'warn', slide_idx,
          message: `slide ${slide_idx} (${layout || '?'}): .header still contains an .eyebrow. `
            + 'CSS hides it visually but the markup should be removed too '
            + '— the content-page header is title-only.',
        }];
      },
    },

    {
      // R-VIS-SUBTITLE-CANON · 标题副标 canonical 统一(F-294)。框架早有 canonical:
      //   `.header` 里 H2 之后一个 `<p class="page-sub">`(css `.slide .header .page-sub`:
      //   标题下 36px、--fs-sub=28px、#fff、统一定位)。各页即兴写副标(`.lede` / `.subtitle` /
      //   裸 <div> / inline-styled <p>)→ class/tag/位置/字号全不统一,用户实测「副标位置都不一样」。
      //   这条 name-free 地守一致:**只看 `.header` 内**、`.title-zh`(或 H2)**之后**出现的、
      //   带自有可见文字的副标元素(任意 tag),class 不是 `page-sub` → warn。
      //   关键边界:**只扫 `.header` 内** —— 正文区(`.stage` 里)的 `.lede` 是正文引导段、
      //   不是标题副标,这条一条不报(选择器钉死 .header)。R56 已管 `.header .eyebrow`(eyebrow
      //   是标题上方的 kicker、本就该删),为避免与 R56 双报,带 eyebrow class 的元素这里跳过。
      id: 'R-VIS-SUBTITLE-CANON',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, layout } = ctx;
        if (HERO_TITLE_LAYOUTS.has(layout)) return [];   // hero 版式自管标题/副标
        const findings = [];
        const headers = slide.querySelectorAll('.header');
        for (const hdr of headers) {
          // 定位标题元素(canonical = .title-zh;兜底取首个 h1-h6)。
          let title = hdr.querySelector('.title-zh');
          if (!title) title = hdr.querySelector('h1,h2,h3,h4,h5,h6');
          if (!title) continue;   // 无标题的 header 不在本规则范围
          // 遍历 .header 的【直接元素子节点】,只看排在标题之后的那些(= 副标位)。
          let afterTitle = false;
          for (const el of hdr.children) {
            if (el === title || (title.contains(el))) { afterTitle = true; continue; }
            if (!afterTitle) continue;                    // 标题之前(eyebrow 位)→ 归 R56,不管
            const cls = (el.getAttribute('class') || '').trim();
            const clsLc = cls.toLowerCase();
            // canonical 写法 → 放行。
            if (/(^|\s)page-sub(\s|$)/.test(clsLc)) continue;
            // eyebrow(R56 管)/ 框架抑制的 pageno → 跳过,避免双报。
            if (/(^|\s)(eyebrow|pageno|deck-pageno)(\s|$)/.test(clsLc)) continue;
            // 只逮「带自有可见文字」的副标元素 —— 空的 wordmark / logo div(无文字)放行。
            const txt = (el.textContent || '').replace(/\s+/g, ' ').trim();
            if (!txt) continue;
            const tag = el.tagName.toLowerCase();
            findings.push({
              rule: 'R-VIS-SUBTITLE-CANON', severity: 'warn', slide_idx,
              message: `slide ${slide_idx} (${layout || '?'}): .header 内标题副标用了 `
                + `<${tag} class="${cls || '(none)'}">("${txt.slice(0, 28)}…"),非 canonical。`
                + '标题副标请用 `.header` 里 H2 后的 `<p class="page-sub">`(框架统一定位:'
                + '标题下 36px、28px、#fff)—— 各页即兴写 .lede/.subtitle/裸 div/inline 会让副标'
                + '位置/字号不一致。注:正文引导段用 `.lede` 放 `.stage`(不放 `.header`),这条只查 `.header` 内。',
            });
          }
        }
        return findings;
      },
    },

    {
      // R-ECHO · 某叶文本回声了同帧 3+ 个其它叶的前缀(冗余 summary)。(步骤 3 第三批迁自
      // _validate_audits.py audit_list_echo)。逐帧:用 walkTextLeaves 收叶;target 叶须 ≥12 字、
      // 非 h1-h6、parent 链非 agenda/toc/.../story-arc、CJK≥4、且"像 summary"(tag=p 或 class/parent
      // 命中 _TARGET_INTENT);对每个其它叶取 4/3/2 字 CJK 前缀(非 stopword)在 target 里出现 →
      // 命中;distinct 命中 ≥3 → warn。agenda/section/cover/end 版式整帧跳过。
      id: 'R-ECHO',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        // 跳过 echo-by-design 版式。原版 `_SKIP_LAYOUT_RE.search(fr)` 在【整帧 HTML 文本】
        // 上做子串匹配 —— 不仅本帧自身 data-layout,连嵌入 <style> 里的
        // `:not([data-layout="cover"])` / `.slide[data-layout="agenda"]` 等 CSS 选择器也会命中
        // 而整帧跳过(原版的副作用,严格保真须照搬,否则会多报)。等价:对 slide.outerHTML 同正则。
        const SKIP_LAYOUT_RE = /data-layout="(agenda|section|cover|end)"/;
        if (SKIP_LAYOUT_RE.test(slide.outerHTML || '')) return [];
        const leaves = walkTextLeaves(slide);
        if (leaves.length < 4) return [];

        const SKIP_PARENT_CLS = ['agenda', 'toc', 'outline', 'chapter-list',
          'section-list', 'pills', 'tabs', 'story-arc'];
        const MIN_TARGET_LEN = 12;
        const PREFIX_LENS = [4, 3, 2];
        const STOPWORDS = new Set(['的', '是', '在', '了', '和', '或', '与', '及',
          '我们', '你们', '他们', '这是', '那是',
          '一个', '一些', '一种', '本次', '本周', '本月']);
        const TARGET_INTENT = ['legend', 'note', 'footnote', 'caption', 'summary',
          'footer', 'disclaimer', 'callout', 'lede', 'subline',
          'subtitle', 'recap', 'echo', 'desc-foot', 'page-sub',
          'tagline', 'kicker'];
        const HEADINGS = new Set(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']);
        const isCjk = (c) => c >= '一' && c <= '鿿';

        const findings = [];
        for (let ti = 0; ti < leaves.length; ti++) {
          const target = leaves[ti];
          if (HEADINGS.has(target.tag)) continue;
          const text = target.text;
          if (text.length < MIN_TARGET_LEN) continue;
          // parent 链含结构性列表/导航容器(agenda/toc/outline/section-list/…)→
          // 整块本就是 enumerate 骨架,逐项 echo 是其本性,跳过(子串匹配,与原版同)。
          if (target.parents.some((p) => SKIP_PARENT_CLS.some((s) => (p || '').indexOf(s) >= 0))) continue;
          let cjkChars = 0;
          for (const c of text) if (isCjk(c)) cjkChars++;
          if (cjkChars < 4) continue;
          const tgtCls = (target.cls || '').toLowerCase();
          const parentCls = target.parents.join(' ').toLowerCase();
          // echo-intentional opt-out: an author marks a leaf — or any ancestor —
          // with class `echo-intentional` to declare a DELIBERATE closing / recap
          // line that names earlier items on PURPOSE (rhetoric / call-to-action,
          // not lazy redundancy).
          // NOTE (corrected): this opt-out is NEW — it was ADDED during the
          // Python→audits.js migration. It did NOT exist in the old engine
          // (_validate_audits.py audit_redundant_echo had NO echo-intentional
          // escape hatch; SKIP_PARENT_CLS only ever held structural list
          // containers). Documented in references/validator-rules.md (R-ECHO row).
          if (tgtCls.indexOf('echo-intentional') >= 0
              || parentCls.indexOf('echo-intentional') >= 0) continue;
          const looksLikeSummary = target.tag === 'p'
            || TARGET_INTENT.some((kw) => tgtCls.indexOf(kw) >= 0)
            || TARGET_INTENT.some((kw) => parentCls.indexOf(kw) >= 0);
          if (!looksLikeSummary) continue;

          const matches = new Set();
          for (let oi = 0; oi < leaves.length; oi++) {
            if (oi === ti) continue;
            const otext = leaves[oi].text;
            if (!otext || otext === text) continue;
            for (const nlen of PREFIX_LENS) {
              if (otext.length < nlen) continue;
              const prefix = otext.slice(0, nlen);
              if (STOPWORDS.has(prefix)) continue;
              let hasCjk = false;
              for (const c of prefix) if (isCjk(c)) { hasCjk = true; break; }
              if (!hasCjk) continue;
              if (text.indexOf(prefix) >= 0) { matches.add(prefix); break; }
            }
          }
          if (matches.size >= 3) {
            const preview = text.length <= 60 ? text : text.slice(0, 57) + '…';
            const hit = [...matches].sort().join(' / ');
            findings.push({
              rule: 'R-ECHO', severity: 'warn', slide_idx,
              message: `slide ${slide_idx}: leaf text \`${preview}\` echoes `
                + `${matches.size} other-leaf prefixes on the same slide `
                + `(${hit}). Likely redundant summary — consider dropping `
                + 'the echoed list and keeping only the new information '
                + '(numbers / verbs / next-step). If the echo is '
                + 'intentional (e.g. closing recap of an earlier list), '
                + 'this warn is editorial — leave as-is.',
            });
          }
        }
        return findings;
      },
    },

    {
      // R36 · present-mode 居中用 absolute + 负 margin(不用 grid place-items)。(步骤 3
      // 第四批迁自 _validate_audits.py audit_centering_pattern)。原版扫整份 HTML 文本:
      //   ① 缺 `margin:-540px 0 0 -960px`(空白容忍)→ err
      //   ② present-mode .slide-frame 仍 `display:grid` → err
      // 移植:对整 deck 全部 CSS 源文本(含框架,runner 注入)做同套正则。这两条都是
      // 框架 chrome 约定(feishu-deck.css 提供 absolute+负 margin 居中),deck 级、整 deck
      // 算一次挂第一帧。无 opt-out / lifted 降级(原版无)。
      id: 'R36',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__R36_DONE__) return [];
        if (!ctx.isFirstInScope) return [];
        if (typeof window !== 'undefined') window.__R36_DONE__ = true;

        const css = allStyleText();
        const findings = [];
        // 原版:re.compile(r'margin:\s*-540px\s+0\s+0\s+-960px')(空白容忍)。
        const MARGIN_RE = /margin:\s*-540px\s+0\s+0\s+-960px/;
        if (!MARGIN_RE.test(css)) {
          findings.push({
            rule: 'R36', severity: 'error', slide_idx,
            message: 'present-mode slide centering is not the absolute + '
              + 'negative-margin pattern (margin: -540px 0 0 -960px) — grid '
              + 'place-items can cause transform clipping',
          });
        }
        // 原版:r'data-mode="present"\]\s+\.slide-frame\s*\{[^}]*display:\s*grid'(DOTALL)。
        const GRID_RE = /data-mode="present"\]\s+\.slide-frame\s*\{[^}]*display:\s*grid/;
        if (GRID_RE.test(css)) {
          findings.push({
            rule: 'R36', severity: 'error', slide_idx,
            message: 'present-mode .slide-frame still uses display:grid — switch '
              + 'to absolute positioning for the slide so transform/overflow '
              + 'clipping is deterministic',
          });
        }
        return findings;
      },
    },

    {
      // R48 · 每个 fixed-shape 容器版式默认垂直居中。(步骤 3 第四批迁自
      // _validate_audits.py audit_default_centering + check_default_centering)。
      // 原版聚合【所有 <style> 块】(剥注释 + _strip_nested_at_rules)成整份 CSS 后,对
      // centerable 版式(content-3up/content-2col/agenda/stats/big-stat/quote)检查其容器
      // (stage/grid/toc/flow/nodes/stack 任一)是否含某条 *-center 居中声明;缺 → err。
      // 移植:对整 deck CSS 源文本(含框架,runner 注入)逐块剥注释 + stripNestedAtRules 后
      // 聚合,跑 checkDefaultCentering(逐字镜像)。deck 级,整 deck 算一次挂第一帧。无 opt-out。
      id: 'R48',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__R48_DONE__) return [];
        if (!ctx.isFirstInScope) return [];
        if (typeof window !== 'undefined') window.__R48_DONE__ = true;

        // 聚合:逐块剥注释 + 解 active @media(对应原版 per-block 处理后 join)。
        const parts = [];
        for (const { css } of iterStyleBlocks(true)) {
          parts.push(stripNestedAtRules(stripCssComments(css)));
        }
        const fullCss = parts.join('\n');
        const findings = [];
        for (const missing of checkDefaultCentering(fullCss)) {
          findings.push({
            rule: 'R48', severity: 'error', slide_idx,
            message: `data-layout="${missing}" container has no vertical-centering `
              + 'rule (justify-content / align-content / align-items: center) '
              + 'anywhere in the deck\'s CSS. Fixed-shape layouts must '
              + 'default-center so short content doesn\'t strand at the top '
              + 'with empty bottom. pipeline / timeline / process are explicit '
              + 'exceptions that fill.',
          });
        }
        return findings;
      },
    },

    {
      // L1/L2/L4 · layout-integrity（LKK exchange-deck 失败模式之三，ingest-gate
      // MANDATORY · business-rules.yaml）。迁自 _validate_audits.py
      // audit_layout_integrity（→ check_logo_default / check_balance /
      // check_attrs_density）。三 code 在 Python 里由单个 audit emit，全是 iss.err
      // （error 严重度），无 lifted 降级 / 无 opt-out（须逐字保留）。
      //   L1：.slide .wordmark 默认 background 必须引用 var(--fs-asset-logo)（彩色）；
      //       缺该规则 / 默认指向 mono → 报。
      //   L2：易短内容版式（content-2col/process/content-3up/pipeline，timeline 故意排除）
      //       的 body 容器须 align/justify-content:center 或 flex:1；版式未用到 → 跳过。
      //   L4：process .output .attrs 须 grid-template-columns:1fr（窄面板单列）；无该规则 → N/A。
      // 移植：对 deckOuterHTML()（runner 已注入框架 <style>，等价 Python inline_linked 后的
      // html —— 含全部框架 CSS 源文本 + 渲染后 markup）做与 Python 逐字相同的正则文本扫描。
      // 三者判定全在源文本里（CSS 规则声明 + `data-layout="L"` presence），与渲染计算无关，
      // 故文本扫描即与原版完全对齐。deck 级，整 deck 算一次挂第一帧。
      id: 'L1/L2/L4',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__L124_DONE__) return [];
        if (!ctx.isFirstInScope) return [];
        if (typeof window !== 'undefined') window.__L124_DONE__ = true;

        const html = deckOuterHTML();
        const findings = [];

        // L1 — logo-default。
        if (!checkLogoDefault(html)) {
          findings.push({
            rule: 'L1', severity: 'error', slide_idx,
            message:
              '.slide .wordmark default does NOT reference var(--fs-asset-logo). '
              + 'Mono-white must be opt-in via .is-mono — color is the规范 default.',
          });
        }

        // L2 — balance。
        const [ok, brokenLayout] = checkBalance(html);
        if (!ok) {
          findings.push({
            rule: 'L2', severity: 'error', slide_idx,
            message:
              `data-layout="${brokenLayout}" body-content container missing `
              + 'vertical-centering rule (align-content: center) AND not declared '
              + 'flex: 1. Short content will stack at top with empty bottom — '
              + 'the most-reported "looks unfinished" bug.',
          });
        }

        // L4 — attrs-density。
        if (!checkAttrsDensity(html)) {
          findings.push({
            rule: 'L4', severity: 'error', slide_idx,
            message:
              '.slide[data-layout="process"] .output .attrs is NOT '
              + 'grid-template-columns: 1fr. The output panel is ~400 px wide; '
              + 'a 2-col grid truncates 22 px body text. Use a single column.',
          });
        }

        return findings;
      },
    },

    {
      // R-EMPTY-HEADER-ZONE · 隐藏框架 .header 时 .stage 不得在页顶留空黑带。(步骤 3
      // 第四批迁自 _validate_audits.py audit_empty_header_zone)。原版逐个 <style> 块:
      // 找该块首个 `.slide[data-slide-key="K"]` 作用域 → 若该 key 的 .header 被 display:none
      // (.header 须是同元素最后一个 simple selector,排除 `.header .x` / `.header + .x`)→
      // 再找该 key 的 .stage top 值;top>32 且 top!=61 → warn(留空黑带)。
      // 移植:对每个【渲染后 <style> 节点 textContent】(剥注释)做与原版逐字相同的正则扫描
      // ——本规则的判定全在 per-page CSS 源文本里(scoped slide-key + display:none + top:Npx),
      // 与渲染计算无关,扫源文本即与原版完全对齐(注释在 textContent 里原样保留)。deck 级
      // (扫所有 <style>),整 deck 算一次挂第一帧。
      id: 'R-EMPTY-HEADER-ZONE',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__REHZ_DONE__) return [];
        if (!ctx.isFirstInScope) return [];
        if (typeof window !== 'undefined') window.__REHZ_DONE__ = true;

        const findings = [];
        const styles = (typeof document !== 'undefined' && document.querySelectorAll('style')) || [];
        const reEscape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        for (const styleEl of styles) {
          const css = stripCssComments(styleEl.textContent || '');
          // 该块首个 scoped slide-key(per-page 样式以 .slide[data-slide-key="K"] 前缀;首个为准)。
          const keyM = /\.slide\[data-slide-key="([^"]+)"\]/.exec(css);
          if (!keyM) continue;
          const key = keyM[1];
          const k = reEscape(key);
          // .header 被隐藏?(.header 须为同元素最后一个 simple selector:允许 :pseudo/.class/[attr]
          // 后缀但不许 combinator,否则隐藏的 CHILD/SIBLING 会被误读成整 .header 隐藏。)
          const hideRe = new RegExp(
            '\\.slide\\[data-slide-key="' + k + '"\\]'
            + '[^{]*\\.header(?![\\w-])[^{\\s>+~]*\\s*\\{[^}]*display\\s*:\\s*none[^}]*\\}');
          if (!hideRe.test(css)) continue;
          // 该 key 的 .stage top 值。
          const stageRe = new RegExp(
            '\\.slide\\[data-slide-key="' + k + '"\\]'
            + '[^{]*\\.stage(?![\\w-])[^{]*\\{([^}]*)\\}');
          const sm2 = stageRe.exec(css);
          if (!sm2) continue;
          const topM = /(?<![\w-])top\s*:\s*(\d+)\s*px/.exec(sm2[1]);
          if (!topM) continue;
          const topVal = parseInt(topM[1], 10);
          if (topVal <= 32 || topVal === 61) continue;   // 允许区:≤32 贴顶 / ==61 框架锚点
          findings.push({
            rule: 'R-EMPTY-HEADER-ZONE', severity: 'warn', slide_idx,
            message: `slide-key="${key}": hides framework .header but .stage starts `
              + `at top:${topVal}px — leaves empty dark zone at slide y=0..${topVal}, `
              + 'reads as "missing bg / black band" on dark theme (especially '
              + 'with diagonal-glow decor that doesn\'t tint top corners). '
              + 'Pick one: (a) restore .header (drop the `display:none` rule), '
              + '(b) snap top ≤32 (content at slide edge), (c) align top:61 '
              + '(matches framework anchor — visually consistent with sibling '
              + 'slides), or (d) add a visible top decoration as .stage\'s '
              + 'first child.',
          });
        }
        return findings;
      },
    },

    {
      // R47 · variant 覆盖纪律。(步骤 3 第四批迁自 _validate_audits.py
      // audit_variant_discipline)。原版只查【作者 CSS】(include_framework=False)里 selector
      // 含 [data-variant 的规则:若声明触碰结构(display:布局值 / flex-* / grid-template-* /
      // grid-auto-*),必须同时重声明 align(align-items|place-items)+ justify(justify-content|
      // place-content),缺则 warn。::before/::after/::placeholder/::marker 伪元素 selector 豁免;
      // display:none/contents 不算结构变更。
      // 移植:对【作者】<style> textContent(剥注释 + stripNestedAtRules)做与原版逐字相同的
      // 规则文本扫描(selector + 声明 substring 判定全在源文本里,与渲染无关)。deck 级,整 deck
      // 算一次挂第一帧。无 opt-out / lifted 降级(原版无)。
      id: 'R47',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__R47_DONE__) return [];
        if (!ctx.isFirstInScope) return [];
        if (typeof window !== 'undefined') window.__R47_DONE__ = true;

        const findings = [];
        for (const { css } of iterStyleBlocks(false)) {   // 仅作者 CSS
          const cleaned = stripNestedAtRules(stripCssComments(css));
          // 原版:re.finditer(r'([^{}]+)\{([^}]+)\}', css)。
          const ruleRe = /([^{}]+)\{([^}]+)\}/g;
          let rm;
          while ((rm = ruleRe.exec(cleaned))) {
            const selector = rm[1].trim();
            const block = rm[2];
            if (selector.indexOf('[data-variant') < 0) continue;
            if (selector.indexOf('::before') >= 0 || selector.indexOf('::after') >= 0
              || selector.indexOf('::placeholder') >= 0 || selector.indexOf('::marker') >= 0) continue;
            let touchesStructure = R47_STRUCTURAL_TRIGGERS.some((t) => block.indexOf(t) >= 0);
            if (!touchesStructure) {
              const dRe = /display:\s*([a-z-]+)/g;
              let dm;
              while ((dm = dRe.exec(block))) {
                if (R47_LAYOUT_DISPLAY.has(dm[1])) { touchesStructure = true; break; }
              }
            }
            if (!touchesStructure) continue;   // cosmetic-only variant — exempt
            const hasAlign = R47_ALIGN_PROPS.some((p) => block.indexOf(p) >= 0);
            const hasJustify = R47_JUSTIFY_PROPS.some((p) => block.indexOf(p) >= 0);
            if (hasAlign && hasJustify) continue;
            const missing = [];
            if (!hasAlign) missing.push('align-items / place-items');
            if (!hasJustify) missing.push('justify-content / place-content');
            findings.push({
              rule: 'R47', severity: 'warn', slide_idx, container_sel: selector,
              message: `variant \`${selector}\` changes structure (display/flex/grid) `
                + `but does not redeclare ${missing.join(', ')}. `
                + 'Variants that change layout direction must redeclare every '
                + 'directional property explicitly — cascade does not auto-reset them.',
            });
          }
        }
        return findings;
      },
    },

    {
      // R29-32 · present-mode runtime chrome 已发货。(步骤 3 第四批迁自
      // _validate_audits.py audit_runtime_chrome)。原版在 inline_linked 把外链 JS 注入成
      // <script data-source=framework> 后,在 `html + script_blocks` 全文里查 DOM needle、
      // 在 script_blocks 里查 JS needle;缺则 R29-32 err。还检查 <script src> 是否未被 inline
      // (文件缺失 / inline 失败)→ 报具体失因并 return(短路 needle 检查,免下游噪声)。
      //
      // 移植(渲染基底 + 源可读双轨,见 run-audits.py _inline_framework_js):
      //   · 外链脚本在 page.goto 时已执行 → DOM needle(.deck-progress/.deck-controls/
      //     .ctl prev|next|fs)作为真 DOM 元素/class 存在 → 渲染基底更准。
      //   · runner 又把外链 JS 源以 <script data-source=framework type=text/plain> 注入(不二次
      //     执行)→ JS needle(requestFullscreen/fullscreenchange)与 innerHTML 串可在 script
      //     textContent 里读到,与 Python script_blocks 等价。
      //   · `--fs-grad-keyline` 在框架 CSS,runner 已注入 <style data-source=framework> → CSS
      //     textContent 可读。`is-idle`(2.5s idle 后才挂)在 JS 源里有该串 → 由 JS needle 兜底。
      //   · <script src> 缺失/未注入:runner 注入失败 = 磁盘无文件 → 这里复刻"文件找不到"失因
      //     并短路(对应原版 js_link_failures → return)。
      // 全文搜索 = DOM outerHTML + 所有 script textContent + 所有 style textContent(含框架)。
      // deck 级,整 deck 算一次挂第一帧。
      id: 'R29-32',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__R2932_DONE__) return [];
        if (!ctx.isFirstInScope) return [];
        if (typeof window !== 'undefined') window.__R2932_DONE__ = true;

        const findings = [];
        // 所有 script 源文本(runner 已把外链 JS 注入成 <script data-source=framework
        // type=text/plain>;含页内 inline <script>)。对应 Python script_blocks。
        let scriptBlocks = '';
        const scripts = (typeof document !== 'undefined' && document.querySelectorAll('script')) || [];
        for (const s of scripts) scriptBlocks += ' ' + (s.textContent || '');

        // <script src> 未被 runner 注入框架副本 = 本地文件读不到(对应原版 js_link_failures)。
        // 判定:存在本地 <script src>,但 DOM 里没有任何对应的 <script data-source=framework>。
        const hasFwScript = !!document.querySelector('script[data-source="framework"]');
        const localSrcScripts = [];
        for (const s of scripts) {
          const src = s.getAttribute && s.getAttribute('src');
          if (!src) continue;
          if (/^(?:http:|https:|\/\/|data:)/.test(src)) continue;
          localSrcScripts.push(src);
        }
        if (localSrcScripts.length && !hasFwScript) {
          for (const src of localSrcScripts) {
            findings.push({
              rule: 'R29-32', severity: 'error', slide_idx,
              message: `JS file not found / not readable: ${src}. `
                + 'Did the deck folder move without `copy-assets.py`? '
                + 'Subsequent R29-R32 needle errors are downstream of this.',
            });
          }
          return findings;   // 短路:linked JS 断了,needle 检查会全是下游噪声(对应原版 return)
        }

        // 全文搜索基底:DOM 标记 + script 源 + style 源(含框架 CSS,--fs-grad-keyline 在这)。
        let styleText = '';
        for (const { css } of iterStyleBlocks(true)) styleText += ' ' + css;
        const domText = (typeof document !== 'undefined' && document.documentElement
          && document.documentElement.outerHTML) || '';
        const fullText = domText + ' ' + scriptBlocks + ' ' + styleText;

        const domNeedles = [
          ['deck-progress', 'top progress bar element / class',
            'feishu-deck.js builds this — make sure <script src="assets/feishu-deck.js"> is loading.'],
          ['deck-controls', 'bottom control pill element / class',
            'feishu-deck.js builds this — verify the JS is loading from a reachable path.'],
          ['class="ctl prev"', 'prev button', 'should appear in feishu-deck.js innerHTML.'],
          ['class="ctl next"', 'next button', 'should appear in feishu-deck.js innerHTML.'],
          ['class="ctl fs"', 'fullscreen button', 'should appear in feishu-deck.js innerHTML.'],
          ['--fs-grad-keyline', 'progress bar uses brand gradient',
            'this token must be defined in feishu-deck.css and used by .deck-progress.'],
          ['is-idle', 'auto-idle fade',
            'feishu-deck.js toggles this class after 2.5s of no input.'],
        ];
        const jsNeedles = [
          ['requestFullscreen', 'fullscreen API call',
            'feishu-deck.js calls element.requestFullscreen() on the deck root.'],
          ['fullscreenchange', 'fullscreenchange listener',
            'feishu-deck.js listens to detect Esc-to-exit-fullscreen.'],
        ];
        for (const [needle, desc, hint] of domNeedles) {
          if (fullText.indexOf(needle) < 0) {
            findings.push({
              rule: 'R29-32', severity: 'error', slide_idx,
              message: `present-mode chrome missing: ${desc} ('${needle}'). ${hint}`,
            });
          }
        }
        for (const [needle, desc, hint] of jsNeedles) {
          if (scriptBlocks.indexOf(needle) < 0) {
            findings.push({
              rule: 'R29-32', severity: 'error', slide_idx,
              message: `present-mode chrome missing in JS: ${desc} ('${needle}'). ${hint}`,
            });
          }
        }
        return findings;
      },
    },

    {
      // R-VIS-NO-IMAGERY · 整 deck 视觉发平(多数内容页零图像)。(步骤 3 第四批迁自
      // _validate_audits.py audit_visual_richness)。warn_soft·ADVISORY,永不 err。
      // 原版:遍历 slides,排除 sparse-by-design 版式(hero-title ∪ {agenda,table,replica,
      // iframe-embed,raw}),其余记为 content;某 content 帧无 <svg>/<img>/background-image →
      // flat;content≥3 且 flat/content≥0.6 → warn_soft,列前 8 个 flat 帧。
      // 移植:逐帧判 layout 是否 sparse-by-design;非 sparse 帧用渲染后 DOM 查图像信号
      //   (querySelector svg/img/canvas/video + 任一元素 computed backgroundImage!=none) ——
      //   比原版"扫帧 HTML 子串 background-image"更准(命中真渲染出的背景图,含 CSS 类带来的)。
      // deck 级(跨帧统计比例),整 deck 算一次挂第一帧。
      id: 'R-VIS-NO-IMAGERY',
      severity: 'warn_soft',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__RVNI_DONE__) return [];
        if (!ctx.isFirstInScope) return [];
        if (typeof window !== 'undefined') window.__RVNI_DONE__ = true;

        const slides = (typeof document !== 'undefined' && document.querySelectorAll('.slide')) || [];
        const content = [];
        const flat = [];
        slides.forEach((sl, idx) => {
          const i = idx + 1;
          const layout = (sl.getAttribute('data-layout') || '').trim();
          if (SPARSE_BY_DESIGN.has(layout)) return;
          content.push(i);
          // 图像信号:有 svg/img/canvas/video,或任一后代有非 none 的 background-image。
          let hasImg = !!sl.querySelector('svg, img, canvas, video');
          if (!hasImg) {
            for (const el of [sl, ...sl.querySelectorAll('*')]) {
              const bg = getComputedStyle(el).backgroundImage;
              if (bg && bg !== 'none') { hasImg = true; break; }
            }
          }
          if (!hasImg) flat.push([i, layout]);
        });
        if (content.length >= 3 && (flat.length / content.length) >= 0.6) {
          const where = flat.slice(0, 8).map(([i, l]) => `#${i}(${l})`).join(', ');
          return [{
            rule: 'R-VIS-NO-IMAGERY', severity: 'warn_soft', slide_idx,
            message: `${flat.length}/${content.length} content slides have zero imagery `
              + '(no icon/svg/image/background) — deck reads visually flat & samey. '
              + 'Where it fits, consider an icon (ICON_LIB names) / photo / '
              + `illustration / bespoke layout:raw page. Flat: ${where}. `
              + '[advisory · richness is a design-phase call · never blocks]',
          }];
        }
        return [];
      },
    },

    {
      // R02/R07 · 每帧必有 data-layout / data-screen-label / .wordmark。(步骤 3 第五批
      // 迁自 _validate_audits.py audit_structure 里可逐帧移植的部分)。原版逐帧:
      //   缺 layout → R02 err;缺 screen-label → R02 err;缺 .wordmark → R07 err。
      // 渲染后等价 = 读 slide 的 data-layout / data-screen-label 属性、querySelector('.wordmark')
      // (class 顺序无关、继承/渲染解析后更准)。.footer chrome 2026-05 已退役,原版无此检查。
      //
      // ⚠️ 未迁(留最终结构批):audit_structure 之外的 R-DOM(audit_dom_integrity:
      // slide-frame 嵌套/平衡)/ R-DOC-INTEGRITY(整文档 .deck 闭合/截断)—— 那些要对
      // 整文档源做 HTML 解析(不是逐帧/isFirstInScope 模型),归"最终结构批"。
      id: 'R02-R07-STRUCTURE',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx, layout } = ctx;
        const findings = [];
        const label = slide.getAttribute('data-screen-label');
        if (!layout) {
          findings.push({
            rule: 'R02', severity: 'error', slide_idx,
            message: `slide ${slide_idx}: missing data-layout`,
          });
        }
        if (!label) {
          findings.push({
            rule: 'R02', severity: 'error', slide_idx,
            message: `slide ${slide_idx}: missing data-screen-label`,
          });
        }
        // R07 (missing .wordmark) EXEMPTION for canvas slides + imported decks.
        // 941f781 removed the canvas template's .wordmark (canvas is now the ONLY
        // fragment shipped without one), so without this carve-out every
        // PPTX-imported / canvas deck fails R07 on EVERY slide at the
        // --visual / ingest / publish gate. Reuse the SAME isCanvas / isImported
        // detection the UI1 rule uses (layout === 'canvas' / deckOriginImported()).
        // The data-layout / data-screen-label R02 checks above stay unconditional.
        const r07IsCanvas = (layout === 'canvas');
        const r07Imported = deckOriginImported();
        if (!r07IsCanvas && !r07Imported && !slideHasWordmark(slide)) {
          // 文案与 Python 逐字对齐:layout 为空 → 原版 f-string 渲染 `None`(slide_attr 返回 None)。
          const layoutRepr = layout ? layout : 'None';
          findings.push({
            rule: 'R07', severity: 'error', slide_idx,
            message: `slide ${slide_idx} (${layoutRepr}): missing .wordmark`,
          });
        }
        return findings;
      },
    },

    {
      // UI1(R-UI1)· 系统 UI / 截图必须 HTML 重建,不许贴栅格。(步骤 3 第五批迁自
      // _validate_audits.py audit_ui_mocks_are_html)。原版扫每帧源:
      //   (a) 内容 <img src> 非 data:/非 brand → 命中;
      //   (b) raster background-image 且 url 同时命中 _UI1_RASTER & _UI1_UI_HINTS → 命中;
      //   (c) 非 iframe-embed 版式里出现 <iframe> → 命中(warn 性质)。
      // 降级(err→warn):replica(page-replica / data-layout="replica")、imported(deck 级
      //   <meta fs-deck-origin=imported>)、is_canvas(data-layout="canvas")。
      // opt-out:vouched = slide 含 data-ui-screenshot 或 style 里 allow:ui-screenshot →
      //   warn_soft(永不阻断,--strict 也不升级),消息尾加〔作者已声明保留〕。
      // data:URI / brand(_UI1_BRAND)资产豁免。data-decor="photo-bg" 仅在消息里建议(原版
      //   亦非代码级 opt-out:真照片走 data: / brand 即豁免)—— 逐字保留。
      //
      // 移植(渲染基底):内容 <img> 用 querySelectorAll('img')(原版正则只取带 src 的);
      //   background-image 改读 computed backgroundImage 取 url();<iframe> 用 querySelector。
      //   slide / style 源用渲染后序列化判 replica/canvas/vouched 字符串(与原版子串等价)。
      id: 'UI1',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx, layout } = ctx;
        const fr = slideOuterHTML(slide);
        const replica = (fr.indexOf('page-replica') >= 0 || layout === 'replica');
        const isIframeLayout = (layout === 'iframe-embed');
        const isCanvas = (layout === 'canvas');
        const imported = deckOriginImported();   // deck 级 <meta fs-deck-origin=imported>
        // vouched: data-ui-screenshot 属性(slide 或后代) OR style 里 allow:ui-screenshot。
        const vouched = (fr.indexOf('data-ui-screenshot') >= 0
          || fr.indexOf('allow:ui-screenshot') >= 0);
        const findings = [];
        // _lev:严重度选择 —— 逐字对应原版的三态。
        const push = (msg) => {
          let severity;
          let suffix = '';
          if (vouched) {
            severity = 'warn_soft';
            suffix = ' 〔作者已 data-ui-screenshot 声明保留〕';
          } else if (replica || imported || isCanvas) {
            severity = 'warn';
          } else {
            severity = 'error';
          }
          findings.push({ rule: 'UI1', severity, slide_idx, message: msg + suffix });
        };
        // (a) 内容 <img> 栅格截图(原版扫 `<img ... src="...">`)。
        slide.querySelectorAll('img').forEach((img) => {
          const src = img.getAttribute('src');
          if (!src) return;
          if (src.startsWith('data:') || ui1Brand(src)) return;
          push(`slide ${slide_idx}: <img src="${src}"> 当正文 — 系统 UI / 截图请用 .ui-* `
            + '原语重建成 HTML(window/sidebar/toolbar/list/cell…),别贴栅格:'
            + '图里的字号检查够不到、投影会糊。纯照片用 data-decor="photo-bg" 声明,'
            + '刻意保留截图用 data-ui-screenshot 声明。');
        });
        // (b) raster background-image 带 UI smell(原版扫源里 url(...) 子串;这里读
        //     computed backgroundImage —— 渲染基底,继承/覆盖后真正生效的背景图)。
        const bgSeen = new Set();
        for (const el of [slide, ...slide.querySelectorAll('*')]) {
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') continue;
          const bg = getComputedStyle(el).backgroundImage;
          if (!bg || bg === 'none') continue;
          let mm;
          const re = /url\(\s*(?:'|")?([^'")]+)/gi;
          while ((mm = re.exec(bg))) {
            const url = mm[1];
            if (url.startsWith('data:') || ui1Brand(url)) continue;
            if (UI1_RASTER.test(url) && UI1_UI_HINTS.test(url)) {
              if (bgSeen.has(url)) continue;
              bgSeen.add(url);
              push(`slide ${slide_idx}: background-image url(${url}) 像 UI 截图当正文 — `
                + '用 HTML 重建,别用栅格背景塞 UI。');
            }
          }
        }
        // (c) 内容 <iframe>(豁免 iframe-embed 版式)→ warn 性质(走 _lev 同三态)。
        if (!isIframeLayout && slide.querySelector('iframe')) {
          push(`slide ${slide_idx}: <iframe> 正文嵌入 — 内嵌文字字号检查够不到、不可控。`
            + '把要呈现的内容用 HTML/.ui-* 重建,或只作示意缩略图(非 iframe-embed 版式)。');
        }
        return findings;
      },
    },

    {
      // R-VIS-LIFT-STYLE-LOST · lifted raw 帧丢了框架 CSS。(步骤 3 第五批迁自
      // _validate_audits.py audit_lift_style_lost)。原版:对每个同时带 data-lifted +
      // data-layout="raw" 的 .slide,累加其 inline <style> 字节;<300 字节 且内容含某重版式
      // 签名(quote/cover/section/big-stat/end)→ err。lift 把原 schema 版式改成 raw 后,
      // 框架 `.slide[data-layout=...]` 规则不再匹配 → 退回浏览器默认(quote 92px→16px)。
      // 本规则不吃 data-lifted 降级(这不是源自身的尺寸选择,是 lift 引入的 STYLE-LOSS bug)。
      //
      // 移植(渲染基底 + 源可读):lifted 用 slideIsLifted(data-lifted 属性);layout 读
      //   data-layout;inline <style> 字节 = slide 子树内 <style>(排除 runner 注入的框架块)
      //   textContent 长度和;重版式签名在 slide 源 HTML 子串上判(与原版字面 class 子串等价)。
      //   key/label 读 data-slide-key / data-screen-label 属性。
      id: 'R-VIS-LIFT-STYLE-LOST',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (!slideIsLifted(slide)) return [];
        if ((slide.getAttribute('data-layout') || '') !== 'raw') return [];
        // inline <style> 字节(排除 runner 注入的 data-source=framework 块 —— 那是 deck 级
        // 框架 CSS,不是本帧自带的 inline 样式;原版扫的是 slide inner 里的 <style>)。
        let styleTotal = 0;
        slide.querySelectorAll('style').forEach((s) => {
          if (s.getAttribute && s.getAttribute('data-source') === 'framework') return;
          styleTotal += (s.textContent || '').length;
        });
        if (styleTotal >= 300) return [];   // 有实质 inline CSS → 假定 OK
        const fr = slideOuterHTML(slide);
        for (const origLayout of Object.keys(LIFT_HEAVY_SIGNATURES)) {
          const sigs = LIFT_HEAVY_SIGNATURES[origLayout];
          if (sigs.every((sig) => fr.indexOf(sig) >= 0)) {
            const key = slide.getAttribute('data-slide-key') || '?';
            const label = slide.getAttribute('data-screen-label') || '?';
            const sigsRepr = '[' + sigs.map((s) => `'${s}'`).join(', ') + ']';
            // Python f-string `{key!r}` → repr(): single-quoted (e.g. 'quote-lost').
            const keyRepr = `'${key}'`;
            return [{
              rule: 'R-VIS-LIFT-STYLE-LOST',
              severity: 'error',
              slide_idx,
              message:
                `slide \`${label}\` (data-slide-key=${keyRepr}) is lifted `
                + `(data-lifted) + data-layout="raw" + inline \`<style>\` `
                + `${styleTotal} bytes (<300) + content uses `
                + `\`${origLayout}\` layout signatures (${sigsRepr}). The source `
                + `slide's visual depended on framework \`.slide[data-layout="`
                + `${origLayout}"]\` rules, which no longer match after lifting `
                + `to "raw" → slide renders at browser defaults (e.g. quote `
                + `blockquote falls 92px → 16px). Fix: (1) re-lift with `
                + `\`assets/lift-slides.py\` (auto-inlines framework CSS for `
                + `quote/cover/section/big-stat/end since 2026-05-29), OR `
                + `(2) switch the slide's layout field to \`"${origLayout}"\` `
                + `(schema layout, not raw), OR (3) manually inline the `
                + `framework rules scoped to this slide-key. `
                + `Per \`data-lifted\` lift-aware downgrade does NOT apply `
                + `to this rule — this isn't the source's own size choices, `
                + `it's a STYLE-LOSS bug introduced by the lift itself.`,
            }];
          }
        }
        return [];
      },
    },

    {
      // R-AUTOBALANCE-PRESENT · deck 必须带当前 feishu-deck.js 的 auto-balance runtime。
      // (步骤 3 第五批迁自 _validate_audits.py audit_autobalance_present)。原版在
      // inline_linked 之后查整 HTML 是否含指纹 `function balanceSlide(slide)`;缺 → err。
      // 豁免:非 deck(无 .deck 容器);.deck 标 data-no-autobalance。deck 级,整 deck 算一次。
      //
      // 移植(渲染基底 + 源可读):runner 的 _inline_framework_js 已把链接的 feishu-deck.js
      //   源以 <script data-source=framework type=text/plain> 注入 → 指纹可在 script
      //   textContent 里读到(与 Python inline_linked 后扫整 HTML 等价;linked / inlined 两模式
      //   都命中)。.deck / data-no-autobalance 用渲染后 DOM 判。
      id: 'R-AUTOBALANCE-PRESENT',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__RAB_DONE__) return [];
        if (!ctx.isFirstInScope) return [];   // deck 级:整 deck 算一次,挂本次 scope 首帧
        if (typeof window !== 'undefined') window.__RAB_DONE__ = true;

        const deck = (typeof document !== 'undefined') && document.querySelector('.deck');
        if (!deck) return [];   // 非 deck(replica/片段)→ 豁免
        if (deck.hasAttribute('data-no-autobalance')) return [];   // 作者显式关
        // 指纹:script 源(含框架注入)+ 整文档源 —— 与原版扫 inline_linked 后整 HTML 等价。
        const haystack = allScriptText() + ' ' + deckOuterHTML();
        if (haystack.indexOf(AUTOBALANCE_SIG) >= 0) return [];
        return [{
          rule: 'R-AUTOBALANCE-PRESENT',
          severity: 'error',
          slide_idx,
          message:
            'deck 未内联当前 feishu-deck.js 的 auto-balance runtime'
            + `(找不到指纹 \`${AUTOBALANCE_SIG}\`)。raw/legacy deck 没 re-bundle → `
            + '运行时 auto-balance 0 行没跑,"文字贴底"等 box-crowd 加载时不会被自动修。'
            + '正道:`python3 assets/rebundle-import.py <deck.html> --inplace` 重新内联'
            + '当前框架 runtime(字号/chrome/内容零改动)。若该 deck 刻意不要 auto-balance,'
            + '在 .deck 上加 data-no-autobalance 显式声明即可豁免本闸。',
        }];
      },
    },

    {
      // R-LAYOUT-DEPRECATED · F-305 «raw unless ceremonial» 版式收编。SOURCE-OF-TRUTH =
      // deck.json 的【真 authored layout】(渲染后 data-layout 不可信:raw 页常借 schema
      // CSS)。该页 authored layout ∈ DEPRECATED_BODY_LAYOUTS(content/stats/flow/chart/
      // table/arch-stack/image-text/logo-wall,含全部 variant)→ warn_soft 提醒:正文 schema
      // 版式已冻结,新页应走 layout:"raw"(模型自由排版,更丰富、各页更不同)。仪式页
      // (cover/section/agenda/quote/end)与机制页(raw/canvas/iframe-embed/replica)不在
      // 冻结清单,永不报。
      //   · ADVISORY · warn_soft —— 绝不阻塞(连 --strict 也不升级):存量 deck 的编辑/重渲不被卡。
      //   · 仅 scope 内的页报(driver 对 scope 外页跳 evaluate)—— --scope N 编辑/新增时只点正在动的页。
      //   · IMPORTED deck(全 lifted / origin=imported)整体豁免:外来 deck 版式不该被本立场评判。
      //   · 无 deck.json 真源注入(foreign / Path B)→ 安静跳过(layoutByKeyFromDeckJson 返回 null)。
      //   退役了反向规则 R-RAW-LOOKS-SCHEMA(2026-06-12,F-305):它劝 raw 卡片页回退 content
      //   schema,与本条 raw-first 立场直接冲突;彻底 raw-first 下,扁平卡片页也由模型 raw 自排。
      id: 'R-LAYOUT-DEPRECATED',
      severity: 'warn_soft',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (deckAllImported()) return [];          // 外来 deck 整体豁免
        const byKey = layoutByKeyFromDeckJson();
        if (byKey === null) return [];             // 无 deck.json 真源 → 跳过(advisory 永不误报)
        const key = slide.getAttribute('data-slide-key') || '';
        const authored = byKey.get(key);
        if (!authored || !DEPRECATED_BODY_LAYOUTS.has(authored)) return [];
        return [{
          rule: 'R-LAYOUT-DEPRECATED',
          severity: 'warn_soft',
          slide_idx,
          message:
            `slide "${key}" uses the FROZEN body layout "${authored}" (F-305 «raw `
            + `unless ceremonial»). Schema layouts are kept only for CEREMONIAL pages `
            + `(cover/section/agenda/quote/end) + MECHANISM pages (raw/canvas/`
            + `iframe-embed/replica); body content (content/stats/flow/chart/table/`
            + `arch-stack/image-text/logo-wall) is frozen — author NEW pages as `
            + `layout:"raw" (the model lays them out freely — richer & more distinct). `
            + `[advisory · existing pages keep rendering · never blocks, even under --strict]`,
        }];
      },
    },

    {
      // R-OVERFLOW · 单帧真实内容溢出 1920×1080 画布(被画布裁掉 = 用户看不到)。
      // (VISUAL-AUDIT-SETTLED-STATE-SPEC §2(A):不再用 slide.scrollWidth>1920 —— 那会把
      //  position:absolute 的 glow/drift 装饰(本就该 bleed 出框、被 .slide overflow:hidden
      //  视觉裁掉)算成溢出 → 误报(实测一个 left:1650/width:700 的 glow 撑出 +503px,误报
      //  ERROR)。改为「可见并集」:跳隐藏 / 跳 absolute|fixed 装饰 / 与每个 overflow≠visible
      //  祖先(两轴,不含 .slide 自身——画布边界就是 .slide,要查的正是越出它的真内容)求交后,
      //  仍越出画框 [0,0,1920,1080] 的才算。复用 R-VIS-CANVAS-CENTER 同款 skip+clip 模式。)
      // 严重度分级(逐字保留 validate.py):_ov = max(Δh, Δw);>60 → error(内容被切),
      //   ≥24 → warn(约 1-2 行),else → warn_soft(半行内,空间够,不阻断)。
      id: 'R-OVERFLOW',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx, label, scale } = ctx;
        const TOL = 2;  // design px,抗亚像素抖动
        const _sr = slide.getBoundingClientRect();
        const _st = _sr.top, _sl = _sr.left;
        let overR = 0, overB = 0, overL = 0, overT = 0;
        slide.querySelectorAll('*').forEach((el) => {
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return;
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return;
          // L4 / coverage-boundary note (deliberate): position:absolute|fixed elements
          // are EXCLUDED here per VISUAL-AUDIT-SETTLED-STATE-SPEC §2A — they are decorative
          // (glow / drift) layers meant to bleed past the canvas and be clipped by
          // `.slide { overflow:hidden }`, so counting them produced false ERRORs. The
          // tradeoff (coverage boundary): genuine ABSOLUTELY-POSITIONED *content* that
          // overflows the canvas is NOT caught by R-OVERFLOW. That is intentional; if it
          // ever needs catching it belongs to a dedicated abspos-content rule
          // (cf. R-VIS-BAND-COLLIDE for absolute content bands), not a relaxation here.
          if (cs.position === 'absolute' || cs.position === 'fixed') return;  // 装饰/glow,bleed by design
          const tag = el.tagName;
          const isMedia = tag === 'IMG' || tag === 'SVG' || tag === 'svg'
            || tag === 'CANVAS' || tag === 'VIDEO';
          const isLeaf = el.children.length === 0;
          if (!hasOwnText(el) && !isMedia && !isLeaf) return;
          const r = el.getBoundingClientRect();
          if (r.width < 6 || r.height < 6) return;
          // 与每个 overflow≠visible 祖先(两轴)求交;完全被裁则丢弃;不含 .slide 自身。
          let vl = r.left, vr = r.right, vt = r.top, vb = r.bottom;
          for (let p = el.parentElement; p && p !== slide; p = p.parentElement) {
            const pcs = getComputedStyle(p);
            const pr = p.getBoundingClientRect();
            if (pcs.overflowX !== 'visible') { if (pr.left > vl) vl = pr.left; if (pr.right < vr) vr = pr.right; }
            if (pcs.overflowY !== 'visible') { if (pr.top > vt) vt = pr.top; if (pr.bottom < vb) vb = pr.bottom; }
          }
          if (vr - vl < 6 || vb - vt < 6) return;
          const left = (vl - _sl) / scale, right = (vr - _sl) / scale;
          const top = (vt - _st) / scale, bot = (vb - _st) / scale;
          if (right - 1920 > overR) overR = right - 1920;
          if (bot - 1080 > overB) overB = bot - 1080;
          if (-left > overL) overL = -left;
          if (-top > overT) overT = -top;
        });
        const deltaW = Math.round(Math.max(overR, overL));
        const deltaH = Math.round(Math.max(overB, overT));
        if (deltaW <= TOL && deltaH <= TOL) return [];
        const bits = [];
        if (deltaH > 0) bits.push(`height +${deltaH} px`);
        if (deltaW > 0) bits.push(`width +${deltaW} px`);
        const ov = Math.max(deltaH, deltaW);
        const severity = ov > 60 ? 'error' : ov >= 24 ? 'warn' : 'warn_soft';
        const sev = ov > 60 ? '严重 · 内容被切，必修'
          : ov >= 24 ? '临界 · 约 1-2 行'
            : '可忽略 · 半行内，空间够，不阻断';
        return [{
          rule: 'R-OVERFLOW', severity, slide_idx,
          idx: slide_idx, label, deltaH, deltaW,
          message:
            `slide ${slide_idx} (${label}): real content overflows canvas — `
            + `${bits.join(', ')}（${sev}）. 对症修：标题溢出→换行/加宽容器，`
            + '正文→压字数，条目过多→删条目/减列。(position:absolute 装饰 bleed 已豁免)',
        }];
      },
    },

    {
      // R-VIS-CARD-OVERFLOW · 卡片/容器内容溢出(画布内、R-OVERFLOW 漏过)。(步骤 3 第六批
      // 迁自 visual-audit.js 的 card_overflow producer + validate.py 的 card_overflow 消费段)。
      // 四种 direction(逐字搬 producer):
      //   (a) vertical       — overflow:hidden|clip + scrollHeight-clientHeight>4(裁切),
      //                        带 recoverable(祖先有 user 滚动视口)。
      //   (a') vertical-visible — overflow 非 hidden + 某 CHILD 底边超出父 border-box>8。
      //   (a'') leaf-text-spill — 纯文本叶(无子元素)的 line-box 超出最近 framed 祖先内框>4。
      //   (b) horizontal     — flex/grid + nowrap + scrollWidth-clientWidth>4。
      // 严重度(逐字搬 validate.py):_px = overflow_px;
      //   vertical(裁切):非 recoverable → lifted?warn:err(恒 err 无视 px);recoverable →
      //     _px>16?err:warn。 其余 direction(visible/leaf/horizontal)→ _px>16?err:warn。
      // 文案/字段逐字保留(各 direction 不同 message)。
      id: 'R-VIS-CARD-OVERFLOW',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx, layout, scale } = ctx;
        const _scale = scale;
        const findings = [];
        // overflow 候选集(逐字搬 producer):有 .stage 用 '.stage *';无 .stage 的 raw 用 '*';
        // 无 .stage 的 schema 仍用 '.stage *'(空集 → 不查,避免装饰数字行盒误报)。
        const overflowCandidates = slide.querySelector('.stage')
          ? slide.querySelectorAll('.stage *')
          : (layout === 'raw' ? slide.querySelectorAll('*') : slide.querySelectorAll('.stage *'));
        // lifted-downgrade (F-325): a slide carrying `data-lifted` reproduces a
        // source deck the human deliberately lifted; its geometry is the SOURCE
        // author's design (phone mockups that clip, full-bleed shells, viewBox
        // SVGs, tight nowrap rows), not a fresh defect. So CARD-OVERFLOW findings
        // on a lifted slide demote err→warn (post-process before `return` below)
        // — same family as R-VIS-TIER / R-VIS-BODY-FLOOR, surfaced for the human
        // to judge rather than hard-blocking the render. (This re-animates a
        // branch once kept dead for validate.py parity; validate.py is now only a
        // CLI adapter, so the engine owns severity.) `data-allow-clip` on the
        // element/ancestor still suppresses the finding entirely.
        const lifted = slideIsLifted(slide);
        const liftNote = lifted
          ? ' — LIFTED slide (verbatim from another deck); downgraded to '
            + 'WARNING, you choose whether to fix.'
          : '';
        const pushEntry = (entry) => {
          const direction = entry.direction || 'vertical';
          const px = entry.overflow_px || 0;
          if (direction === 'horizontal') {
            const severity = px > 16 ? 'error' : 'warn';
            findings.push({
              rule: 'R-VIS-CARD-OVERFLOW', severity, slide_idx, ...entry,
              message:
                `slide ${slide_idx} · \`${entry.selector}\` is a flex/grid `
                + 'container with nowrap children — total children width '
                + `(${entry.content_h} px) exceeds container width `
                + `(${entry.card_h} px) by ${entry.overflow_px} px. `
                + 'Children are bleeding past the right edge (visible overflow) '
                + 'or being silently clipped. Fix: shorten child text, move one '
                + 'child to a separate line (display:block sibling), set '
                + '`flex-wrap: wrap`, or widen the container.',
            });
          } else if (direction === 'vertical-visible') {
            // 仅 vertical-visible 命中此分支。⚠️ leaf-text-spill 不在这里:validate.py 的消费段
            // 是 `if horizontal / elif vertical-visible / else`,direction='leaf-text-spill' 落到
            // 末尾 else(overflow:hidden 文案 + recoverable 检查)。leaf-text-spill entry 无
            // recoverable 字段 → !!undefined=false → non-recoverable → lifted?warn:err。这是
            // 逐字对齐 validate.py 现行行为(即便它把 leaf-spill 套了 overflow:hidden 文案)。
            const severity = px > 16 ? 'error' : 'warn';
            findings.push({
              rule: 'R-VIS-CARD-OVERFLOW', severity, slide_idx, ...entry,
              message:
                `slide ${slide_idx} · \`${entry.selector}\` content `
                + `(${entry.content_h} px) is ${entry.overflow_px} px taller `
                + `than its box (${entry.card_h} px) and overflow is NOT hidden `
                + `— content is spilling visibly out the box ${entry.edge || '下沿'} past `
                + 'the border / background. The slide still fits the 1920×1080 canvas, so '
                + 'R-OVERFLOW misses it; the clip-only check missed it too because '
                + 'overflow is visible. Fix: shorten body copy, drop a row / item, '
                + 'tighten padding / gap, or give the box more height. '
                + '(Geometry — a visible spill is a real defect.)',
            });
          } else {
            // direction === 'vertical'(overflow:hidden|clip 裁切)或 'leaf-text-spill'
            // (validate.py else 分支 = 二者共用,见上 elif 注释)。recoverable 缺省 false。
            const recoverable = !!entry.recoverable;
            if (!recoverable) {
              // PRESERVE-EXACTLY:producer 不带 lifted → validate.py 此分支恒 err(死的 lift 降级)。
              const severity = 'error';
              findings.push({
                rule: 'R-VIS-CARD-OVERFLOW', severity, slide_idx, ...entry,
                message:
                  `slide ${slide_idx} · \`${entry.selector}\` has `
                  + `\`overflow:hidden\` but content (${entry.content_h} px) is `
                  + `${entry.overflow_px} px taller than the container `
                  + `(${entry.card_h} px), AND there is NO user-scrollable `
                  + 'viewport (该盒 overflow-y 是 hidden/clip,user 不可滚;祖先也没有 '
                  + 'overflow-y:auto|scroll 的真实滚动视口)→ 被裁内容永久不可见 '
                  + '(non-recoverable clip),客户永远看不到这部分,内容彻底丢。'
                  + 'Fix: shorten body copy, drop a row/item, shrink padding/gap, '
                  + 'increase card height (more stage space), OR drop overflow:hidden '
                  + 'so the issue is at least visible. (内容丢失是硬伤 — 即便溢出很小'
                  + '也顶格 ERROR;lifted 页降 warn 由你定夺。)',
              });
            } else {
              const severity = px > 16 ? 'error' : 'warn';
              findings.push({
                rule: 'R-VIS-CARD-OVERFLOW', severity, slide_idx, ...entry,
                message:
                  `slide ${slide_idx} · \`${entry.selector}\` has `
                  + `\`overflow:hidden\` but content (${entry.content_h} px) is `
                  + `${entry.overflow_px} px taller than the container `
                  + `(${entry.card_h} px) — text is being clipped, but the box `
                  + 'HAS a usable scroll mechanism (内容能滚出来,危害低)。'
                  + 'Fix: shorten body copy, drop a row/item, shrink padding/gap, '
                  + 'increase card height (more stage space), OR drop overflow:hidden '
                  + 'so the clipped content is visible without scrolling.',
              });
            }
          }
        };

        // §2A guard: scrollHeight/scrollWidth count position:absolute descendants
        // (glow / rail / tail decorations that bleed past the box by design) → false
        // clip/overflow. Returns true only if some IN-FLOW (non-absolute, visible)
        // descendant — or el's own direct text — actually extends past el's box on
        // `axis` ('y'|'x'). When el has NO absolute|fixed descendant the scroll metric
        // is already trustworthy → returns true (preserves existing behavior).
        // L4 / coverage-boundary note (deliberate): this carve-out trusts that
        // absolute|fixed descendants are decorations. The tradeoff is that genuine
        // ABSOLUTELY-POSITIONED *content* overflowing its card is NOT flagged as a
        // card overflow — same intentional abspos-decoration exclusion as R-OVERFLOW
        // above. Catching abspos content collisions is R-VIS-BAND-COLLIDE / R-OVERLAP's
        // job, not this rule's, so we do not relax the guard here.
        const _cardRealOverflow = (el, axis) => {
          const all = [...el.querySelectorAll('*')];
          const hasAbs = all.some((d) => {
            const p = getComputedStyle(d).position; return p === 'absolute' || p === 'fixed';
          });
          if (!hasAbs) return true;
          const er = el.getBoundingClientRect();
          const bound = axis === 'x' ? er.right : er.bottom;
          for (const desc of all) {
            const dcs = getComputedStyle(desc);
            if (dcs.position === 'absolute' || dcs.position === 'fixed') continue;
            if (dcs.display === 'none' || dcs.visibility === 'hidden' || +dcs.opacity === 0) continue;
            const r = desc.getBoundingClientRect();
            if ((axis === 'x' ? r.right : r.bottom) > bound + 4) return true;
          }
          for (const n of el.childNodes) {
            if (n.nodeType !== 3 || !n.textContent.trim()) continue;
            const rng = document.createRange(); rng.selectNode(n);
            for (const lr of rng.getClientRects()) {
              if (lr.width < 1 || lr.height < 1) continue;
              if ((axis === 'x' ? lr.right : lr.bottom) > bound + 4) return true;
            }
          }
          return false;  // 全部溢出来自 absolute 装饰 → 非真实裁切
        };
        overflowCandidates.forEach((el) => {
          if (el.tagName === 'SCRIPT' || el.tagName === 'STYLE') return;
          const cs = getComputedStyle(el);
          // 跳隐藏(VISUAL-AUDIT-SETTLED-STATE-SPEC §2A:card_overflow「同样跳 opacity:0」)。
          // 不可见元素(display:none / visibility:hidden / opacity:0)的内部裁切用户根本看不到,
          // 不是缺陷;与 R-OVERFLOW / R-VIS-CANVAS-CENTER 的跳隐藏一致。只移除不可见元素的
          // 误报,绝不漏掉可见内容(可见 → opacity>0)。
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return;
          // F-322: 有意截断 opt-out —— 元素自身或祖先标了 `data-allow-clip`(如文档预览框
          // kb-shell:故意只露文档顶部、下半截断,是设计而非内容丢失;真·可滚动 doc 预览也
          // 归此类)→ 跳过 overflow 审计。与 data-allow-imbalance/-overlap/-flex-slack 同族。
          if (el.closest && el.closest('[data-allow-clip]')) return;
          const overflowY = cs.overflowY;
          const overflow = cs.overflow;
          // F-322: 自身是滚动视口(overflow:auto|scroll)→ 溢出内容由滚动条容纳、用户可
          // 滚出来,既非永久裁切也非可见外溢,不是 card-overflow 缺陷(框架 fs-doc-scroll
          // 文档预览、长列表滚动框等都靠它)。跳过该元素本身;其内部真·裁切的子元素仍由
          // (a) 分支各自评估,且 (a) 的 recoverable 检查会因这个 auto/scroll 祖先把它们降为
          // warn。此前 `clips` 只认 hidden|clip,把 auto/scroll 漏给了 (a') 可见外溢分支 →
          // 把有意的滚动框误判成「撑出 N px 外溢」(知识安全页 fs-doc-scroll 1180>732 误报)。
          if (overflowY === 'auto' || overflowY === 'scroll'
              || overflow === 'auto' || overflow === 'scroll') return;
          const clips = (overflowY === 'hidden' || overflowY === 'clip'
            || overflow === 'hidden' || overflow === 'clip');
          if (clips) {
            const dh = el.scrollHeight - el.clientHeight;
            if (dh > 4 && _cardRealOverflow(el, 'y')) {   // 排除纯 absolute 装饰撑高
              let recoverable = false;
              for (let n = el.parentElement; n && n !== slide; n = n.parentElement) {
                const ncs = getComputedStyle(n);
                const oy = ncs.overflowY;
                if ((oy === 'auto' || oy === 'scroll') && (n.scrollHeight - n.clientHeight) > 4) {
                  recoverable = true; break;
                }
              }
              pushEntry({
                selector: shortSel(el),
                content_h: el.scrollHeight,
                card_h: el.clientHeight,
                overflow_px: dh,
                direction: 'vertical',
                recoverable,
              });
            }
          } else {
            // (a') visible vertical spill — IN-FLOW children cross the parent
            // border-box. ⚠️ F-317: measure BOTH edges in design px (/_scale),
            // NOT scrollHeight. `scrollHeight` ignores content pushed out the TOP
            // of a flex box (justify-content:center|flex-end → dh≈0 even while rows
            // visibly poke above *and* below the border); the old check both gated
            // on `dh = scrollHeight-clientHeight > 8` and measured only the bottom
            // edge in raw screen px, so it (1) missed centered-card overflow
            // (#meeting-qc 标题行顶出面板上沿) and (2) at present-mode scale<1
            // under-reported the bottom spill by never dividing by _scale like the
            // rest of the engine (line 56 等). Now: both edges, design px, summed.
            if (el.clientHeight > 0 && el.children.length > 0) {
              const er = el.getBoundingClientRect();
              let topSpill = 0, botSpill = 0;
              for (const ch of el.children) {
                if (ch.tagName === 'SCRIPT' || ch.tagName === 'STYLE') continue;
                const ccs = getComputedStyle(ch);
                // 装饰/隐藏子元素不算「自身内容」溢出(spec §2A)。
                if (ccs.position === 'absolute' || ccs.position === 'fixed'
                    || ccs.display === 'none' || ccs.visibility === 'hidden' || +ccs.opacity === 0) continue;
                const cr = ch.getBoundingClientRect();
                botSpill = Math.max(botSpill, (cr.bottom - er.bottom) / _scale);
                topSpill = Math.max(topSpill, (er.top - cr.top) / _scale);
              }
              const overshoot = Math.max(0, topSpill) + Math.max(0, botSpill);
              if (overshoot > 8) {
                const edge = (topSpill > 4 && botSpill > 4) ? '上下两沿'
                  : (topSpill > 4) ? '上沿' : '下沿';
                pushEntry({
                  selector: shortSel(el),
                  content_h: Math.round(el.clientHeight / _scale + overshoot),
                  card_h: Math.round(el.clientHeight / _scale),
                  overflow_px: Math.round(overshoot),
                  direction: 'vertical-visible',
                  edge,
                });
              }
            } else if (el.clientHeight > 0 && el.children.length === 0
                       && hasOwnText(el) && !visIsMediaBox(el)) {
              // (a'') leaf-text-spill — leaf line-box vs nearest framed ancestor inner box.
              let frame = null;
              for (let n = el; n && n !== slide; n = n.parentElement) {
                if (visIsFramedBox(n) && !visIsMediaBox(n)) { frame = n; break; }
              }
              if (frame) {
                const fr = frame.getBoundingClientRect();
                const fcs = getComputedStyle(frame);
                const innerBottom = fr.bottom - (parseFloat(fcs.borderBottomWidth) || 0);
                const innerRight = fr.right - (parseFloat(fcs.borderRightWidth) || 0);
                const rng = document.createRange(); rng.selectNodeContents(el);
                let lineBottom = -Infinity, lineRight = -Infinity, anyLine = false;
                for (const lr of rng.getClientRects()) {
                  if (lr.width < 1 || lr.height < 1) continue;
                  anyLine = true;
                  lineBottom = Math.max(lineBottom, lr.bottom);
                  lineRight = Math.max(lineRight, lr.right);
                }
                if (anyLine) {
                  const spill = Math.max((lineBottom - innerBottom) / _scale,
                    (lineRight - innerRight) / _scale);
                  if (spill > 4) {
                    pushEntry({
                      selector: shortSel(el),
                      content_h: Math.round(lineBottom - fr.top),
                      card_h: Math.round(innerBottom - fr.top),
                      overflow_px: Math.round(spill),
                      direction: 'leaf-text-spill',
                      frame_sel: shortSel(frame),
                    });
                  }
                }
              }
            }
          }
          // (b) horizontal overflow on flex/grid nowrap container.
          const isFlexGrid = ['flex', 'inline-flex', 'grid', 'inline-grid'].includes(cs.display);
          const noWrap = cs.flexWrap === 'nowrap' || cs.display === 'grid' || cs.display === 'inline-grid';
          if (isFlexGrid && noWrap) {
            const dw = el.scrollWidth - el.clientWidth;
            if (dw > 4 && _cardRealOverflow(el, 'x')) {   // 排除纯 absolute 装饰撑宽
              pushEntry({
                selector: shortSel(el),
                content_h: el.scrollWidth,
                card_h: el.clientWidth,
                overflow_px: dw,
                direction: 'horizontal',
              });
            }
          }
        });
        // F-325 lifted-downgrade: demote every CARD-OVERFLOW err→warn on a lifted
        // slide (all entries here are this rule) and tag the human-decides note.
        if (lifted) {
          for (const f of findings) {
            if (f.severity === 'error') f.severity = 'warn';
            f.message += liftNote;
          }
        }
        return findings;
      },
    },

    {
      // R-VIS-TIER · 每个文字元素的 computed fontSize 须在 4-tier 台阶 {16,24,28,48} 或
      // 文档化的 hero 例外上。(步骤 3 第六批迁自 visual-audit.js 的 tier producer +
      // validate.py 的 tier 消费段)。几何逐字搬 producer:
      //   skip 无直接文本 / SVG 文本 / px<8;TIER 命中 OK;HERO_SIZES 命中且(isHeroLayout
      //   或 hero-class 祖先)OK;mock-internal(TIER_MOCK 祖先)skip;[data-allow-typescale]
      //   opt-out;同 (sel,px) 一页一报。
      // 严重度(逐字搬 validate.py):lifted → warn(+降级备注),else → err。文案逐字保留。
      id: 'R-VIS-TIER',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx, isHeroLayout } = ctx;
        const findings = [];
        const textEls = slide.querySelectorAll('*');
        const seenTierViolations = new Set();
        textEls.forEach((el) => {
          if (!hasOwnText(el)) return;
          if (el.ownerSVGElement || el.tagName === 'TEXT' || el.tagName === 'tspan') return;
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return;  // 跳隐藏(spec §2A)
          const px = Math.round(parseFloat(cs.fontSize));
          if (!px || px < 8) return;
          if (VIS_TIER.has(px)) return;
          if (VIS_HERO_SIZES.has(px)) {
            if (isHeroLayout) return;
            let heroAncestor = false;
            for (let n = el; n && n !== slide; n = n.parentElement) {
              if (visHasAnyClass(n, VIS_HERO_CLASSES)) { heroAncestor = true; break; }
            }
            if (heroAncestor) return;
          }
          let inMock = false;
          for (let n = el; n && n !== slide; n = n.parentElement) {
            if (visHasAnyClass(n, VIS_TIER_MOCK)) { inMock = true; break; }
          }
          if (inMock) return;
          let allowOut = false;
          for (let n = el; n; n = n.parentElement) {
            if (n.dataset && n.dataset.allowTypescale != null) { allowOut = true; break; }
          }
          if (allowOut) return;
          const sel = shortSel(el);
          const key = `${sel}::${px}`;
          if (seenTierViolations.has(key)) return;
          seenTierViolations.add(key);
          const lifted = !!(el.closest && el.closest('[data-lifted]'));
          const severity = lifted ? 'warn' : 'error';
          const note = lifted
            ? ' — LIFTED slide (verbatim from another deck); downgraded '
              + 'to WARNING, you choose whether to fix.'
            : '';
          findings.push({
            rule: 'R-VIS-TIER', severity, slide_idx,
            selector: sel, computed_px: px, lifted,
            message:
              `slide ${slide_idx} · \`${sel}\` renders at ${px}px (off the `
              + '4-tier ladder {16, 24, 28, 48} + hero whitelist). Snap it to '
              + 'the nearest tier. `/* allow:typescale */` is a narrow escape '
              + 'hatch reserved for a genuine hero numeral (cover hero / section '
              + 'chapter-num / big-stat / quote) — not a way to silence this '
              + `check; only reach for it when the value really is hero scale.${note}`,
          });
        });
        return findings;
      },
    },

    {
      // R-VIS-HIER · 每个 card/panel 内 meta-class 字号 ≤ body-class 字号。(步骤 3 第六批
      // 迁自 visual-audit.js 的 hier producer + validate.py 的 hier 消费段)。几何逐字搬:
      //   card = CARD_KEYS 命中 OR -card/-tile/-cell/-panel/-box 后缀;每 card 一次(WeakSet);
      //   metaEls = 后代里 META_KEYS 命中且有直接文本;bodyEls 同理 BODY_KEYS;两者皆非空时,
      //   bodyPx = min(bodyEls 字号),每个 meta.px > bodyPx → push。always err(逐字搬)。
      id: 'R-VIS-HIER',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const findings = [];
        const cards = slide.querySelectorAll('*');
        const seenCards = new WeakSet();
        cards.forEach((card) => {
          if (!visHasAnyClass(card, VIS_CARD_KEYS) && !visHasCardSuffix(card)) return;
          if (seenCards.has(card)) return;
          seenCards.add(card);
          const allTextEls = [...card.querySelectorAll('*')].filter((e) => {
            if (!hasOwnText(e)) return false;
            const cs = getComputedStyle(e);  // 跳隐藏(spec §2A):隐藏文本不参与卡内层级/字号下限
            return cs.display !== 'none' && cs.visibility !== 'hidden' && +cs.opacity !== 0;
          });
          const metaEls = allTextEls.filter((e) => visHasAnyClass(e, VIS_META_KEYS));
          const bodyEls = allTextEls.filter((e) => visHasAnyClass(e, VIS_BODY_KEYS));
          if (metaEls.length && bodyEls.length) {
            const bodyPx = Math.min(...bodyEls.map(
              (b) => Math.round(parseFloat(getComputedStyle(b).fontSize))));
            metaEls.forEach((m) => {
              const mpx = Math.round(parseFloat(getComputedStyle(m).fontSize));
              if (mpx > bodyPx) {
                findings.push({
                  rule: 'R-VIS-HIER', severity: 'error', slide_idx,
                  card_sel: shortSel(card),
                  meta_sel: shortSel(m),
                  meta_px: mpx,
                  body_sel: shortSel(bodyEls[0]),
                  body_px: bodyPx,
                  message:
                    `slide ${slide_idx} · meta \`${shortSel(m)}\` at ${mpx}px `
                    + `is BIGGER than body \`${shortSel(bodyEls[0])}\` at `
                    + `${bodyPx}px in the same card (\`${shortSel(card)}\`). `
                    + 'Visual hierarchy reads inverted — shrink meta to ≤ body, '
                    + 'or rename to a column-pill class if this element is '
                    + 'actually a column title (not meta).',
                });
              }
            });
          }
        });
        return findings;
      },
    },

    {
      // R-VIS-BODY-FLOOR · ≥8 字直接文本在 <24px 且不在 mock / chrome 类内。(步骤 3 第六批
      // 迁自 visual-audit.js 的 body_floor producer + validate.py 的 body_floor 消费段)。
      // 几何逐字搬:skip SVG 文本 / <style> / <script> / px>=24;直接文本<8 字 skip;
      //   CONTENT_CHROME_CLASSES 命中 skip;MOCK_CONTAINERS(=TIER_MOCK)祖先 skip;
      //   [data-allow-body-floor] 链 opt-out;isHeroLayout skip;同 (sel,px) 一页一报。
      //   附带 _growBox verdict(grow_needed_px/room_px/can_grow/in_box)。
      // 严重度(逐字搬 validate.py):lifted → warn(+降级备注),else → err;_fix 由 can_grow 选。
      id: 'R-VIS-BODY-FLOOR',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx, isHeroLayout, scale } = ctx;
        if (isHeroLayout) return [];   // hero 版式整体豁免(producer 在循环内 skip,等价)
        const _scale = scale;
        const findings = [];
        const textEls = slide.querySelectorAll('*');
        const seenBodyFloor = new Set();
        textEls.forEach((el) => {
          if (el.ownerSVGElement || el.tagName === 'TEXT' || el.tagName === 'tspan') return;
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return;
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return;  // 跳隐藏(spec §2A)
          const px = Math.round(parseFloat(cs.fontSize));
          if (!px || px >= 24) return;
          let directTextStr = '';
          for (const n of el.childNodes) {
            if (n.nodeType === 3) directTextStr += n.textContent;
          }
          directTextStr = directTextStr.trim();
          if (directTextStr.length < 8) return;
          if (visHasAnyClass(el, VIS_CONTENT_CHROME_CLASSES)) return;
          if (visIsStaticChrome(el)) return;   // 静态词表对齐(kicker/legend/meta/… 见 VIS_STATIC_CHROME_TOKENS)
          let inMock = false;
          for (let n = el; n && n !== slide; n = n.parentElement) {
            if (visHasAnyClass(n, VIS_TIER_MOCK) || visIsUiMock(n)) { inMock = true; break; }
          }
          if (inMock) return;
          let allowOut = false;
          for (let n = el; n; n = n.parentElement) {
            if (n.dataset && n.dataset.allowBodyFloor != null) { allowOut = true; break; }
          }
          if (allowOut) return;
          const sel = shortSel(el);
          const key = `${slide_idx}::${sel}::${px}`;
          if (seenBodyFloor.has(key)) return;
          seenBodyFloor.add(key);
          const lifted = !!(el.closest && el.closest('[data-lifted]'));
          const grow = visGrowBox(el, slide, _scale) || {};
          const preview = directTextStr.length > 40
            ? directTextStr.slice(0, 40) + '…' : directTextStr;
          const charCount = directTextStr.length;
          const severity = lifted ? 'warn' : 'error';
          const cg = grow.can_grow;
          let fix;
          if (cg === true) {
            fix = ` 修法→ 提到 24 + 框自动长高(改大自动拉高):需约 `
              + `${grow.grow_needed_px != null ? grow.grow_needed_px : '?'}px,框/画布余 `
              + `${grow.room_px != null ? grow.room_px : '?'}px,装得下。永不缩字号。`;
          } else if (cg === false) {
            fix = ` 修法→ 提到 24 后空间不够(需 `
              + `${grow.grow_needed_px != null ? grow.grow_needed_px : '?'}px,`
              + `仅余 ${grow.room_px != null ? grow.room_px : '?'}px):压字数/删条目,而非缩字号。`;
          } else {
            fix = ' 修法→ 提到 24(优先),内容超框则拉高框 / 压字数,永不缩字号。';
          }
          findings.push({
            rule: 'R-VIS-BODY-FLOOR', severity, slide_idx,
            selector: sel, rendered_px: px, char_count: charCount,
            preview, lifted, ...grow,
            message:
              (lifted ? 'LIFTED slide (verbatim from another deck) — downgraded to '
                + 'WARNING, you choose whether to bump. ' : '')
              + `slide ${slide_idx} · \`${sel}\` renders at ${px}px but its `
              + `direct text is ${charCount} chars ("${preview}"). `
              + 'Body content (≥ 8 chars of sentence-like text outside mockup '
              + 'containers and chrome classes) must be ≥ 24 px on projector.'
              + fix
              + ' (Or rename to a chrome class .eyebrow/.footnote/.source/.pill/'
              + '.tag/.chip/.badge/.pageno/.demo-tag — or put it inside a .ui-* '
              + 'mockup primitive — if it really is chrome, OR set '
              + '`data-allow-body-floor` for a documented exception.)',
          });
        });
        return findings;
      },
    },

    {
      // R-VIS-DIM-TEXT · 正文文字对比度过低(在深色画布上发灰看不清)。新增 2026-06-05。
      //   与 R-WHITE-TEXT 互补:R-WHITE-TEXT 扫【作者 CSS 源】的字面 rgba(255,255,255,<1),
      //   看不穿框架 token —— `color:var(--fs-text-40)` 解析后是软白却被它漏掉(本规则诞生的
      //   导火索:一份 deck 用 --fs-text-40 写正文,投影全灰,R-WHITE-TEXT 一条没报)。本条走
      //   【computed DOM】,token/继承都已解析,正补这个盲区。
      //   feishu-deck 基础 ink 是纯 #fff,`--fs-text-40`(白@0.40)是 chrome 专用档;把它
      //   (或更暗的纯灰)用在句子型正文上 → 投影发灰。几何 name-free:遍历叶元素,有直接
      //   文本(≥8 字、非 chrome 类、非 mock、非隐藏),解析 computed color 的有效亮度
      //   eff = alpha × 相对亮度;eff < 0.5(≈ 白@0.5 以下 / 深纯灰)→ warn。chrome
      //   (.footnote/.source/.eyebrow/.pageno…)本就该暗,经 chrome-class 豁免;确属设计
      //   意图的暗注记 → 元素加 `data-allow-dim-text`。warn(对比度是启发式 + 不破坏存量交付)。
      //   阈值 0.5 放过框架 sanctioned 的 body 0.72 / sub 0.65,只逮把 0.40 档误用到正文。
      id: 'R-VIS-DIM-TEXT',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, isHeroLayout } = ctx;
        if (isHeroLayout) return [];
        const findings = [];
        const seen = new Set();
        slide.querySelectorAll('*').forEach((el) => {
          if (el.ownerSVGElement || el.tagName === 'TEXT' || el.tagName === 'tspan') return;
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return;
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return;
          let txt = '';
          for (const n of el.childNodes) if (n.nodeType === 3) txt += n.textContent;
          txt = txt.trim();
          if (txt.length < 8) return;                                   // sentence-like body only
          // ALL-CAPS Latin = eyebrow / footer / tag convention (e.g. "MESSENGER · DOCS"):
          // chrome-by-convention even without a chrome class, and meant to read dim. Skip.
          if (/[A-Z]/.test(txt) && !/[a-z\u4e00-\u9fff]/.test(txt)) return;
          // Bilingual EN sub-track (.title-en / .subtitle-en / .label-en …): an
          // intentionally de-emphasised secondary translation line (R-LANG owns it),
          // not body — skip so DIM-TEXT doesn't flag every bilingual deck's EN row.
          {
            const _cls = (el.className && el.className.baseVal !== undefined
              ? el.className.baseVal : (el.className || '')).toString();
            if (/(?:^|\s)[\w-]*-en(?:\s|$)/.test(_cls)) return;
          }
          if (visHasAnyClass(el, VIS_CONTENT_CHROME_CLASSES)) return;   // chrome may legitimately be dim
          let inMock = false;
          for (let n = el; n && n !== slide; n = n.parentElement) {
            if (visHasAnyClass(n, VIS_TIER_MOCK)) { inMock = true; break; }
          }
          if (inMock) return;
          let allowOut = false;
          for (let n = el; n; n = n.parentElement) {
            if (n.dataset && n.dataset.allowDimText != null) { allowOut = true; break; }
          }
          if (allowOut) return;
          const m = (cs.color || '').match(/rgba?\(([^)]+)\)/);
          if (!m) return;
          const p = m[1].split(',').map((s) => parseFloat(s));
          if (p.length < 3) return;
          const maxc = Math.max(p[0], p[1], p[2]);
          const minc = Math.min(p[0], p[1], p[2]);
          if (maxc - minc > 40) return;                                 // saturated brand-accent text (blue/orange/violet) — intentional color, NOT washed-out grey
          const a = p.length >= 4 ? p[3] : 1;
          const lum = (0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]) / 255;
          const eff = a * lum;                                          // effective brightness on dark canvas
          if (eff >= 0.5) return;                                       // framework body 0.72 / sub 0.65 pass
          const sel = shortSel(el);
          const key = `${slide_idx}::${sel}`;
          if (seen.has(key)) return;
          seen.add(key);
          const preview = txt.length > 40 ? txt.slice(0, 40) + '…' : txt;
          findings.push({
            rule: 'R-VIS-DIM-TEXT', severity: 'warn', slide_idx,
            selector: sel, effective_brightness: Math.round(eff * 100) / 100,
            message:
              `slide ${slide_idx} · \`${sel}\` 正文 ("${preview}") 有效亮度仅 `
              + `${Math.round(eff * 100)}% —— 深色画布上发灰看不清(基础 ink 是纯 #fff,`
              + `--fs-text-40 / 0.40 是 chrome 专用档,别用在句子型正文上)。`
              + `Fix: 正文用 var(--fs-text) 或 ≥ 0.84 亮度,次要说明 ≥ 0.72;`
              + `真要暗的注记 → 用 .footnote / .source 等 chrome 类,或元素加 data-allow-dim-text。`,
          });
        });
        return findings;
      },
    },

    {
      // R-VIS-CONTRAST-WCAG · 正文与【有效背景】对比度低于 WCAG AA (F-351, 2026-06-20).
      //   与 R-VIS-DIM-TEXT 互补、零重叠:DIM-TEXT 假设画布是纯黑、用启发式 eff 亮度
      //   (alpha×相对亮度 < 0.5)逮"深色画布上发灰的字",看不见【浅色 / 彩色实色背景】上的
      //   低对比(浅卡上的浅灰字、浅黄 callout 上的白字 —— 投影/打印读不清,是 AI slop 高频坑)。
      //   本条只在【能解析出的不透明实色 + 偏亮(relLum≥0.35)背景】上算真·WCAG 对比度
      //   (gamma-correct 相对亮度 + (L1+.05)/(L2+.05) 比值),正文 <4.5:1 / 大字·粗体 <3:1 → warn。
      //   保守至上(地板规则宁漏勿误报):背景是渐变 / 图片 / 半透明 / 解析不到不透明底 / 偏暗
      //   (那是 DIM-TEXT 的地盘)→ 一律豁免,绝不二次报。豁免链与 DIM-TEXT 同款(hero / chrome /
      //   ALL-CAPS eyebrow / 双语 -en / mock 内 / data-allow-contrast|data-allow-dim-text)。
      //   warn(对比度是 AA 下限的启发执行,绝不 error 阻断存量交付)。
      id: 'R-VIS-CONTRAST-WCAG',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, isHeroLayout } = ctx;
        if (isHeroLayout) return [];
        // gamma-correct WCAG 相对亮度 + 对比度比值(self-contained,无现成 helper)。
        const _lin = (c) => { const s = c / 255; return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4); };
        const _relLum = (r, g, b) => 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b);
        const _ratio = (l1, l2) => (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
        const _rgb = (s) => {
          const m = (s || '').match(/rgba?\(([^)]+)\)/);
          if (!m) return null;
          const p = m[1].split(',').map((x) => parseFloat(x));
          if (p.length < 3) return null;
          return { r: p[0], g: p[1], b: p[2], a: p.length >= 4 ? p[3] : 1 };
        };
        // 解析【有效背景】:从元素自身向上走,首个不透明实色 background-color 即文字落底;
        // 中途遇到 background-image(渐变/图片)/ 半透明底 → 解析不可靠,返回 null = 豁免。
        const _bg = (el) => {
          for (let n = el; n && n !== slide.parentElement; n = n.parentElement) {
            const cs = getComputedStyle(n);
            if (cs.backgroundImage && cs.backgroundImage !== 'none') return null;
            const c = _rgb(cs.backgroundColor);
            if (c) {
              if (c.a >= 0.999) return c;     // 不透明实色 = 命中
              if (c.a > 0) return null;        // 半透明底 → 无法干净合成 → 豁免
            }
            if (n === slide) break;
          }
          return null;                          // 没解析到不透明底(暗画布 = DIM-TEXT 地盘)→ 豁免
        };
        const findings = [];
        const seen = new Set();
        slide.querySelectorAll('*').forEach((el) => {
          if (el.ownerSVGElement || el.tagName === 'TEXT' || el.tagName === 'tspan') return;
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return;
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return;
          let txt = '';
          for (const nn of el.childNodes) if (nn.nodeType === 3) txt += nn.textContent;
          txt = txt.trim();
          if (txt.length < 8) return;                                   // sentence-like body only
          if (/[A-Z]/.test(txt) && !/[a-z一-鿿]/.test(txt)) return;   // ALL-CAPS eyebrow/footer
          {
            const _cls = (el.className && el.className.baseVal !== undefined
              ? el.className.baseVal : (el.className || '')).toString();
            if (/(?:^|\s)[\w-]*-en(?:\s|$)/.test(_cls)) return;          // bilingual EN sub-track
          }
          if (visHasAnyClass(el, VIS_CONTENT_CHROME_CLASSES) || visIsStaticChrome(el)) return;
          let inMock = false;
          for (let n = el; n && n !== slide; n = n.parentElement) {
            if (visHasAnyClass(n, VIS_TIER_MOCK)) { inMock = true; break; }
          }
          if (inMock) return;
          let allowOut = false;
          for (let n = el; n; n = n.parentElement) {
            if (n.dataset && (n.dataset.allowContrast != null || n.dataset.allowDimText != null)) { allowOut = true; break; }
          }
          if (allowOut) return;
          const fg = _rgb(cs.color);
          if (!fg) return;
          // 饱和品牌强调色文字(蓝/绿/橙/紫…)是刻意着色,非"洗白的灰",豁免(与 DIM-TEXT 的
          // maxc-minc>40 同口径;否则飞书品牌蓝 #3370ff、品牌绿 #16a34a 等浅卡上的彩字会误报)。
          if (Math.max(fg.r, fg.g, fg.b) - Math.min(fg.r, fg.g, fg.b) > 40) return;
          const bg = _bg(el);
          if (!bg) return;                                              // 有效背景不可解析 → 豁免
          const bgLum = _relLum(bg.r, bg.g, bg.b);
          if (bgLum < 0.35) return;                                     // 偏暗背景 = DIM-TEXT 地盘,零重叠
          // 文字半透明 → 先合成到实色背景上再算(WCAG 要求按实际渲染色)。
          const a = fg.a;
          const fr = a * fg.r + (1 - a) * bg.r;
          const fgc = a * fg.g + (1 - a) * bg.g;
          const fb = a * fg.b + (1 - a) * bg.b;
          // 浅色文字 + 浅背景 = 多半是"浅字盖在更暗的层 / scrim 上"被祖先 walk 误解析成浅底
          // (caption-over-scrim 这类可读模式;对抗验证实测此为主要 FP),保守跳过(宁漏勿误报);
          // 本规则聚焦【深/中灰文字落在浅实色卡】这一最可靠、DIM-TEXT 看不见的低对比情形。
          if (_relLum(fr, fgc, fb) > 0.55) return;
          const cr = _ratio(_relLum(fr, fgc, fb), bgLum);
          const px = parseFloat(cs.fontSize) || 0;
          const wt = parseInt(cs.fontWeight, 10) || 400;
          const isLarge = px >= 24 || (px >= 18.66 && wt >= 700);       // WCAG 大字档
          const need = isLarge ? 3.0 : 4.5;
          if (cr >= need) return;
          const sel = shortSel(el);
          const key = `${slide_idx}::${sel}`;
          if (seen.has(key)) return;
          seen.add(key);
          const preview = txt.length > 40 ? txt.slice(0, 40) + '…' : txt;
          findings.push({
            rule: 'R-VIS-CONTRAST-WCAG', severity: 'warn', slide_idx,
            selector: sel, contrast_ratio: Math.round(cr * 100) / 100, required: need,
            message:
              `slide ${slide_idx} · \`${sel}\` 正文 ("${preview}") 与其背景对比度仅 `
              + `${cr.toFixed(2)}:1,低于 WCAG AA 下限 ${need}:1(${isLarge ? '大字/粗体' : '正文'})`
              + ` —— 浅色/彩色实色底上的低对比文字,投影或打印时读起来吃力(DIM-TEXT 只看深色`
              + `画布、看不到这种浅底低对比,本条专补)。Fix: 加大文字与背景的明度差(正文 ≥4.5:1、`
              + `大字/粗体 ≥3:1),或换更深/更浅的文字色;确属设计意图 → 元素加 `
              + `\`data-allow-contrast\`。(advisory · never blocks)`,
          });
        });
        return findings;
      },
    },

    {
      // R-VIS-ORPHAN · CJK 孤字 / 上长下短 失衡换行。(步骤 3 第六批迁自 visual-audit.js 的
      // orphan producer + validate.py 的 orphan 消费段)。几何逐字搬:每个 CJK 叶元素(无块级
      // 子元素、非 SVG 文本、CJK≥4、非 mock-internal、非 nowrap/pre),按 line-box 量行宽;
      //   ≥2 行且 (a) 末行 ≤ fs*1.45(orphan)或 (b) 行数≤3 且末行 < 最宽*0.38 且 CJK≤cap
      //   (heroFont fs≥72 → cap 25,else 14)(imbalanced)→ push;同 sel 一页一报。
      // always warn(逐字搬)。文案逐字保留(kind / balance 备注)。
      id: 'R-VIS-ORPHAN',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const findings = [];
        const seenOrphan = new Set();
        slide.querySelectorAll('*').forEach((el) => {
          if (!hasOwnText(el)) return;
          if (el.ownerSVGElement || el.tagName === 'TEXT' || el.tagName === 'tspan') return;
          const hasBlockChild = [...el.children].some((c) => {
            const d = getComputedStyle(c).display;
            return d === 'block' || d === 'flex' || d === 'grid' || d === 'list-item' || d === 'table';
          });
          if (hasBlockChild) return;
          const cjk = ((el.textContent || '').match(/[一-鿿]/g) || []).length;
          if (cjk < 4) return;
          let inMock = false;
          for (let n = el; n && n !== slide; n = n.parentElement) {
            if (visHasAnyClass(n, VIS_TIER_MOCK)) { inMock = true; break; }
          }
          if (inMock) return;
          const cs = getComputedStyle(el);
          if (cs.whiteSpace === 'nowrap' || cs.whiteSpace === 'pre') return;
          const fs = parseFloat(cs.fontSize) || 16;
          const rng = document.createRange(); rng.selectNodeContents(el);
          const byTop = new Map();
          [...rng.getClientRects()].forEach((r) => {
            if (r.width < 1 || r.height < 1) return;
            let key = Math.round(r.top);
            for (const k of byTop.keys()) { if (Math.abs(k - key) < 4) { key = k; break; } }
            byTop.set(key, Math.max(byTop.get(key) || 0, r.width));
          });
          const widths = [...byTop.entries()].sort((a, b) => a[0] - b[0]).map((e) => e[1]);
          if (widths.length < 2) return;
          const last = widths[widths.length - 1];
          const maxw = Math.max(...widths);
          const isOrphan = last <= fs * 1.45;
          const heroFont = fs >= 72;
          const cjkCap = heroFont ? 25 : 14;
          const isImbalanced = widths.length <= 3 && last < maxw * 0.38 && cjk <= cjkCap;
          if (!isOrphan && !isImbalanced) return;
          const sel = shortSel(el);
          if (seenOrphan.has(sel)) return;
          seenOrphan.add(sel);
          const kind = isOrphan ? 'orphan' : 'imbalanced';
          const balance = cs.textWrap || '';
          const linePx = widths.map((w) => Math.round(w));
          const lastPx = Math.round(last);
          const maxPx = Math.round(maxw);
          const fontPx = Math.round(fs);
          const preview = (el.textContent || '').trim().slice(0, 16);
          const kindLabel = kind === 'orphan' ? '末行孤字 orphan' : '上长下短 imbalanced';
          const noBal = balance === 'balance' ? '' : ' (该元素当前没有 text-wrap:balance)';
          findings.push({
            rule: 'R-VIS-ORPHAN', severity: 'warn', slide_idx,
            selector: sel, lines: widths.length, line_px: linePx,
            last_px: lastPx, max_px: maxPx, font_px: fontPx,
            kind, balance, preview,
            message:
              `slide ${slide_idx} · \`${sel}\` CJK 换行不平衡 — ${kindLabel}: `
              + `${widths.length} 行 ${linePx}px,末行仅 ${lastPx}px (最宽行 `
              + `${maxPx}px / 字号 ${fontPx}px) ("${preview}"). 文字换行后末行只剩一两个字 `
              + '或上面长下面短,投影上很碎。Fix 优先级: (1) 给元素加 '
              + '`text-wrap: balance`(框架对常见标题/卡名类已默认开 — 若这里没生效,'
              + '多半被更具体的选择器/另一条 !important 压住了,提级覆盖即可);'
              + '(2) 容器固定宽 / 被 flex 夹窄,balance 也救不了 → 加宽容器,或 4 字以内'
              + '主标签用 `white-space: nowrap` 逼单行,或把尾词(「企划」「部」等)用 '
              + `\`display:block\` 拆成副标行;(3) 改文案让上下两行字数接近。${noBal}`,
          });
        });
        return findings;
      },
    },

    {
      // R-VIS-TITLE-POSITION · 内容版式的 .header 绝对 top 漂移。(步骤 3 第七批迁自
      // visual-audit.js 的 title_position producer + validate.py 的 title_position 消费段)。
      // 几何逐字搬 producer:
      //   TITLE_SKIP_LAYOUTS(cover/section/end/quote/big-stat/replica/image-text)跳过;
      //   header = :scope>.header;titleEl = header 内 .title-zh / h1.title-zh / h2.title-zh;
      //   ⚠️ display:none / hidden header 跳过 —— getClientRects().length===0 是"未渲染"
      //   的规范判定(display:none 报全 0 bbox → top:0 会误判),框架在某些版式(如无
      //   with-header 的 agenda:`.header{display:none}`)故意隐藏 header,无可见标题可校
      //   位置,必须跳过(此即任务要求 PRESERVE 的"skips display:none/hidden headers"规则);
      //   scale = slide bbox 高 / 1080(本规则自算 scale,不用 ctx.scale,逐字搬 producer);
      //   headerTop = (header.top - slide.top)/scale 取整;|headerTop-61| > 8 → push。
      // 严重度(逐字搬 validate.py):always err。文案逐字保留。截断 [:20]。
      id: 'R-VIS-TITLE-POSITION',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx, layout } = ctx;
        // TITLE_SKIP_LAYOUTS 逐字搬 producer(注意与 HERO_LAYOUTS 不同:含 replica、不含 image-text? —
        // 实为 cover/section/end/quote/big-stat/replica/image-text,逐字对齐 producer 第 564 行)。
        const TITLE_SKIP_LAYOUTS = new Set(['cover', 'section', 'end', 'quote',
          'big-stat', 'replica', 'image-text']);
        if (TITLE_SKIP_LAYOUTS.has(layout)) return [];
        const header = slide.querySelector(':scope > .header');
        const titleEl = slide.querySelector(
          ':scope > .header > .title-zh, :scope > .header > h1.title-zh, '
          + ':scope > .header > h2.title-zh, :scope > .header h2.title-zh, '
          + ':scope > .header h1.title-zh');
        // display:none / detached header 不渲染 → getClientRects().length===0 跳过(见注释)。
        const headerRendered = !!header && header.getClientRects().length > 0;
        if (!(header && titleEl && headerRendered)) return [];
        // 本规则自算 scale = slide bbox 高 / 1080(逐字搬 producer 第 580 行,非 ctx.scale)。
        const scale = (slide.getBoundingClientRect().height / 1080) || 1;
        const headerTop = Math.round(
          (header.getBoundingClientRect().top - slide.getBoundingClientRect().top) / scale);
        const expectedTop = 61;
        const tolerance = 8;
        if (Math.abs(headerTop - expectedTop) <= tolerance) return [];
        // F-325 lifted-downgrade: a lifted slide keeps its source deck's header
        // baseline (the source author's choice); demote err→warn so it surfaces
        // for review without hard-blocking — same family as R-VIS-TIER.
        const lifted = slideIsLifted(slide);
        return [{
          rule: 'R-VIS-TITLE-POSITION', severity: lifted ? 'warn' : 'error', slide_idx,
          layout, actual_top: headerTop, expected_top: expectedTop,
          message:
            `slide ${slide_idx} (layout \`${layout}\`) · `
            + `\`.header\` rendered at top:${headerTop}px, expected `
            + `~${expectedTop}px (master spec). Likely cause: the `
            + 'layout is missing from the framework header-positioning '
            + 'whitelist in `feishu-deck.css` / `extra-layouts.css`. Add '
            + `\`.slide[data-layout="${layout}"] .header\` to the `
            + 'unified positioning rule (`position:absolute; top:61px; '
            + 'left:73px; right:320px`) so title aligns with the master '
            + 'spec across all layouts.'
            + (lifted ? ' — LIFTED slide (verbatim from another deck); '
              + 'downgraded to WARNING, you choose whether to fix.' : ''),
        }];
      },
    },

    {
      // R-VIS-RAW-TITLE-POS · raw 内容页的 de-facto 标题不在标准基线 (2026-06-04).
      // R-VIS-TITLE-POSITION 只量框架 `.header` 里的 `.title-zh` 的 top(期望 61);raw 页
      // 没有 .header、标题手写在 .raw-stage 里 → 那条规则没东西可量、静默放行,正是
      // "标题偏下/缺失/顶部留空带"一类问题的盲区(世界坚果协会 deck 第一版踩的就是这个:
      // 全 deck `.header` 出现 0 次)。
      // 这条补盲,纯几何 name-free:找 de-facto 标题(slide 内最高的 own-text、非 absolute、
      // font-size>=32 的醒目块,正文一般 <=28 不会被选),量它距 slide 顶的 top;>101px(明显
      // 低于 61 基线 / 上方留了空带)→ warn。只查 layout=raw;hero / data-allow-imbalance 豁免。
      // 双盲区扩盲 (F-271, 2026-06-10):原本"slide 有任一渲染 .header 就归 TITLE-POSITION"
      // 太宽 —— raw 页带了 `.header` 但标题用自定义类(.r-title / .r-head,非 .title-zh)时,
      // TITLE-POSITION 的 titleEl 取到 null → 静默放行,而本条又因 .header 在场提前 return,
      // 两条规则同时漏(实证 nut-assoc 9 页 top 出现 44/48/61 全漏)。改为:只有 .header 里
      // 确有 TITLE-POSITION 能量的框架标题(.title-zh / h1.title-zh / h2.title-zh)时才让位;
      // .header 在场但无框架标题 → 落回下面的 name-free de-facto 扫描(其内含的静态自定义
      // 标题节点会被选中,top 反映绝对定位 .header 的真实渲染位置)。warn(启发式;绝不 error
      // —— F-256 已把 error 级 R-VIS 提为阻断,raw 标题位做 error 会让大量现存 raw deck 全被
      // block,本就标题漂移)。
      id: 'R-VIS-RAW-TITLE-POS',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, layout, isHeroLayout } = ctx;
        if (layout !== 'raw') return [];
        if (isHeroLayout || slide.hasAttribute('data-allow-imbalance')) return [];
        const hdr = slide.querySelector(':scope > .header');
        // 只有 .header 里确有 TITLE-POSITION 能量的框架标题时才让位(选择器与那条逐字对齐);
        // 否则(.header 在场但用自定义标题类 / 无标题)落回下面 name-free 扫描,补双盲区。
        const fwTitle = hdr && hdr.getClientRects().length > 0 && hdr.querySelector(
          ':scope > .title-zh, :scope > h1.title-zh, :scope > h2.title-zh, '
          + ':scope h2.title-zh, :scope h1.title-zh');
        if (fwTitle) {
          // F-307 (2026-06-13) · 关闭 raw×框架标题的标题位盲区。
          // 旧逻辑在此 `return []` 让位给 R-VIS-TITLE-POSITION,但那条是 schema-only、
          // raw 页根本不跑 → 二者夹缝里"谁都没量"。lift 外来 raw 页会把源 deck 的自定义
          // header 定位(top≠61)一起 recover 进来,标题与右上 logo 错位(实证:tongdianjuli
          // lift 进来 top:48,比基线高 13px,顶部参差 + 与 logo 不齐),全程零告警。
          // 这里自量框架 .header 的 top,双向都查(偏高=与 logo 错位 / 偏低=上方空带),
          // tol=8 与 TITLE-POSITION 对齐。severity 仍 warn(F-256:error 级 R-VIS 阻断,
          // raw 标题位做 error 会 block 大量现存漂移 raw deck);warn 进 advisory,作者可见即修。
          const sr0 = slide.getBoundingClientRect();
          const scale0 = (sr0.height / 1080) || 1;
          const fwHeaderTop = Math.round((hdr.getBoundingClientRect().top - sr0.top) / scale0);
          const expFw = 61, tolFw = 8;
          if (Math.abs(fwHeaderTop - expFw) <= tolFw) return [];
          const dir = fwHeaderTop < expFw
            ? '偏高,与右上 logo 不在同一基线(顶部参差)'
            : '偏低,标题上方留了一条空带';
          return [{
            rule: 'R-VIS-RAW-TITLE-POS', severity: 'warn', slide_idx, layout,
            actual_top: fwHeaderTop, expected_top: expFw, title_sel: shortSel(fwTitle),
            message:
              `slide ${slide_idx} (layout \`raw\`) · 框架 \`.header\` 渲染在 top:${fwHeaderTop}px,`
              + `标准基线 ~${expFw}px,${dir} —— 标题与右上角 logo 未对齐。`
              + '常见于 lift 外来页时把源 deck 的自定义 header 定位(top≠61)一起带了进来。'
              + 'Fix: 把该页 `.header` 的 top 改回 61px(写在 custom_css / 该页 <style>),'
              + '与 master 基线和 logo 对齐;确属居中大字 / 无标题设计,用 `data-allow-imbalance` opt-out。',
          }];
        }
        const sr = slide.getBoundingClientRect();
        const scale = (sr.height / 1080) || 1;
        let tEl = null, tTop = Infinity;
        for (const el of slide.querySelectorAll('*')) {
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') continue;
          if (!hasOwnText(el)) continue;
          const cs = getComputedStyle(el);
          if (cs.position === 'absolute' || cs.position === 'fixed') continue;
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
          if ((parseFloat(cs.fontSize) || 0) < 32) continue;        // 标题档,排除正文
          const r = el.getBoundingClientRect();
          if (r.width <= 40 || r.height <= 16) continue;
          if (r.top < tTop) { tTop = r.top; tEl = el; }
        }
        if (!tEl) return [];   // 全页没有醒目标题块 → 留给 R-VIS-FILL / 人工
        const titleTop = Math.round((tEl.getBoundingClientRect().top - sr.top) / scale);
        const expectedTop = 61;
        if (titleTop <= expectedTop + 40) return [];                 // <=101 视作在基线带内
        return [{
          rule: 'R-VIS-RAW-TITLE-POS', severity: 'warn', slide_idx, layout,
          actual_top: titleTop, expected_top: expectedTop, title_sel: shortSel(tEl),
          message:
            `slide ${slide_idx} (layout \`raw\`) · de-facto 标题 \`${shortSel(tEl)}\` `
            + `渲染在 top:${titleTop}px,远低于标准基线 ~${expectedTop}px —— 标题被下压 / `
            + '上方留了一条空带(raw 页手写标题绕过了 R-VIS-TITLE-POSITION 的位置校验)。'
            + 'Fix: 让标题顶到基线 —— stage `justify-content:flex-start` + stage top≈56px、'
            + '标题作首个子节点,正文在其下用 flex 居中;确属无标题 / 居中大字的设计意图,'
            + '用 `data-allow-imbalance` opt-out。',
        }];
      },
    },

    {
      // R-VIS-RAW-TITLE-STACK · raw 内容页"双层标题"(标题里折进/上叠了更小的 eyebrow/kicker)。
      //   飞书 content 页是单行纯标题;R56 在框架 `.header .eyebrow` 上强制,但选择器钉死 .header
      //   → 手写 raw 标题把 kicker 折成标题元素的小字首行(或叠在标题上方)时 R56 一条不报 ——
      //   正是本仓库自己踩过的盲区(变化 0N 小字叠大标题)。本条 name-free 补盲:layout=raw 且
      //   无框架 .header 时,取 de-facto 标题(最高 ≥36px own-text 非 absolute 可见块),若其子树里
      //   有 own-text 叶 fontSize ≤24 且 ≤0.55×标题字号(= 折进去的 eyebrow,而非同号的 .hl/.q
      //   强调)→ warn。hero / data-allow-imbalance / data-allow-title-stack 豁免。warn(启发式)。
      //   复用 R-VIS-RAW-TITLE-POS 的 de-facto 标题几何;与之互补(那条查位置,这条查双层结构)。
      id: 'R-VIS-RAW-TITLE-STACK',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, layout, isHeroLayout } = ctx;
        if (layout !== 'raw') return [];
        if (isHeroLayout || slide.hasAttribute('data-allow-imbalance')
            || slide.hasAttribute('data-allow-title-stack')) return [];
        const hdr = slide.querySelector(':scope > .header');
        if (hdr && hdr.getClientRects().length > 0) return [];   // 框架 header → R56 管
        let tEl = null, tTop = Infinity;
        for (const el of slide.querySelectorAll('*')) {
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') continue;
          if (!hasOwnText(el)) continue;
          const cs = getComputedStyle(el);
          if (cs.position === 'absolute' || cs.position === 'fixed') continue;
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
          if ((parseFloat(cs.fontSize) || 0) < 36) continue;       // 标题档
          const r = el.getBoundingClientRect();
          if (r.width <= 40 || r.height <= 16) continue;
          if (r.top < tTop) { tTop = r.top; tEl = el; }
        }
        if (!tEl) return [];
        const titlePx = parseFloat(getComputedStyle(tEl).fontSize) || 0;
        if (titlePx < 36) return [];
        let kicker = null;
        for (const d of tEl.querySelectorAll('*')) {
          let own = '';
          for (const n of d.childNodes) if (n.nodeType === 3) own += n.textContent;
          own = own.trim();
          if (own.length < 2) continue;                            // 实质小字,非空 span
          const ds = getComputedStyle(d);
          if (ds.display === 'none' || ds.visibility === 'hidden' || +ds.opacity === 0) continue;
          const px = parseFloat(ds.fontSize) || 0;
          if (px > 0 && px <= 24 && px <= titlePx * 0.55) { kicker = { el: d, px, text: own }; break; }
        }
        if (!kicker) return [];
        const kt = kicker.text.length > 24 ? kicker.text.slice(0, 24) + '…' : kicker.text;
        return [{
          rule: 'R-VIS-RAW-TITLE-STACK', severity: 'warn', slide_idx, layout,
          title_sel: shortSel(tEl), kicker_sel: shortSel(kicker.el),
          kicker_px: Math.round(kicker.px), title_px: Math.round(titlePx),
          message:
            `slide ${slide_idx} (layout \`raw\`) · 双层标题 —— de-facto 标题 \`${shortSel(tEl)}\` `
            + `(${Math.round(titlePx)}px) 里折进了更小的 eyebrow/kicker \`${shortSel(kicker.el)}\` `
            + `(${Math.round(kicker.px)}px:"${kt}")。飞书 content 页是单行纯标题,R56 只在框架 `
            + '`.header .eyebrow` 上强制、对手写 raw 标题静默放行 —— 这正是 raw 页绕过 R56 的盲区。'
            + 'Fix: 把编号/eyebrow 并进同一行标题(同字号),或用框架 '
            + '`<div class="header"><h2 class="title-zh">…</h2></div>` 让 R56 等守卫生效;'
            + '确属设计意图的小字前缀 → 加 `data-allow-title-stack`。',
        }];
      },
    },

    {
      // R-VIS-TITLE-GAP · 正文顶到/重叠标题。(步骤 3 第七批迁自 visual-audit.js 的
      // title_gap producer + validate.py 的 title_gap 消费段)。几何逐字搬 producer:
      //   同 TITLE_SKIP_LAYOUTS 跳过(producer 把 title_gap 嵌在同一 !TITLE_SKIP 块内);
      //   命名通道:headerRendered && :scope>.stage → title=header bbox,contentTop = stage
      //     后代里 w>40&&h>16 的最小 top;name-free 兜底(无 header):slide 内顶部 40% 区
      //     内 ≥24px own-text 非 absolute 的最高块当 title,其下方块当 content;
      //   contentTop 须 ≥ title.top-2(否则是 full-bleed bg);gap=(contentTop-title.bottom)/scale,
      //     scale = ctx.scale(--fs-scale,逐字搬 producer 用的 _scale);gap<24 → push。
      // 严重度(逐字搬 validate.py):gap_px<12 → err,else warn(_lev)。文案逐字保留。截断 [:20]。
      id: 'R-VIS-TITLE-GAP',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, layout, scale } = ctx;
        const _scale = scale;
        const TITLE_SKIP_LAYOUTS = new Set(['cover', 'section', 'end', 'quote',
          'big-stat', 'replica', 'image-text']);
        if (TITLE_SKIP_LAYOUTS.has(layout)) return [];
        // Per-slide opt-out (framework-consistent with data-allow-imbalance et al.):
        // a bespoke header-less raw slide authors its own title + subtitle and may
        // trip the name-free fallback below even when the spacing is correct. This
        // explicit escape hatch lets the author affirm intentional title spacing.
        // See validator-rules.md. (Precision is also improved by subtitle-folding
        // in the name-free branch, so this opt-out is the last resort, not routine.)
        if (slide.hasAttribute('data-allow-title-gap')) return [];
        // F-301:header 用 findSlideHeader 找(直接子优先,兼容 .land>.header 嵌一层
        // 的 bespoke 满幅页 —— 旧 `:scope > .header` 在那类页上摸空,整条规则静默)。
        const header = findSlideHeader(slide);
        const headerRendered = !!header && header.getClientRects().length > 0;
        let tgTitleRect = null, tgTitleSel = null, tgContentTop = Infinity;
        let tgBandBottom = null;   // bottom of the title band (title, or title+subtitle)
        const tgStage = slide.querySelector(':scope > .stage');
        if (headerRendered && tgStage) {
          tgTitleRect = header.getBoundingClientRect();
          tgTitleSel = shortSel(header);
          // Header channel: the .header bbox already encloses any subtitle inside it,
          // so the band bottom is simply the header bottom (no folding needed).
          tgBandBottom = tgTitleRect.bottom;
          for (const el of tgStage.querySelectorAll('*')) {
            if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') continue;
            const cs = getComputedStyle(el);
            // 跳隐藏(spec §2A,同 card_overflow/R-OVERFLOW):opacity:0/隐藏元素紧贴标题底
            // 不该被当成最顶内容驱动 gap —— 用户根本看不到它。
            if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
            const r = el.getBoundingClientRect();
            if (r.width > 40 && r.height > 16) tgContentTop = Math.min(tgContentTop, r.top);
          }
        } else if (headerRendered) {
          // F-301 third channel: the header EXISTS and renders, but there is NO
          // `:scope > .stage` — bespoke full-bleed raw pages put content in a
          // custom wrapper (.land/.canvas/…), usually fully absolute-positioned.
          // Before this channel, such a page hit NEITHER branch (header channel
          // requires .stage, name-free requires !header) and 0–24px crowding
          // under the subtitle shipped silently (fwd-founder #8: 14px). The
          // header bbox still defines the title band (it encloses any .page-sub),
          // so measure the gap from header.bottom to the topmost visible content
          // block BELOW the band: own-text leaves, media, or FRAMED boxes — a
          // bordered/filled card frame crowds a subtitle just as much as text
          // does (on #8 the crowding object is the 2×2 grid's .cell border, 24px
          // above its first text). Excluded: the header's own ancestors (the
          // full-bleed wrapper contains the header), unframed empty wrappers,
          // near-canvas-size background panels, and anything overlapping the
          // band itself (that is R-OVERLAP's job — same below-band semantics as
          // the name-free channel).
          tgTitleRect = header.getBoundingClientRect();
          tgTitleSel = shortSel(header);
          tgBandBottom = tgTitleRect.bottom;
          const sr3 = slide.getBoundingClientRect();
          for (const el of slide.querySelectorAll('*')) {
            if (el === header || header.contains(el) || el.contains(header)) continue;
            if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') continue;
            if (el.namespaceURI === 'http://www.w3.org/2000/svg' && el.tagName.toLowerCase() !== 'svg') continue; // 形状由所属 <svg> 的墨迹并集代表
            const cs = getComputedStyle(el);
            if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
            const r = el.getBoundingClientRect();
            if (r.width <= 40 || r.height <= 16) continue;
            const isMedia3 = el.tagName === 'IMG' || el.tagName === 'CANVAS'
              || el.tagName === 'VIDEO' || el.tagName.toLowerCase() === 'svg';
            let effTop = r.top;
            if (el.tagName.toLowerCase() === 'svg') {
              // SVG 外框 bbox 含透明画布区(viewBox 边距)—— 一张「空气感」图表的
              // 外框可以贴着 header 底而墨迹离它很远(本 deck #7:外框 top=带底 0px,
              // 真实节点低 ~50px)。改用墨迹并集顶(可见子图形 bbox 的最小 top),
              // 空 svg 当装饰跳过。
              let ink = Infinity;
              el.querySelectorAll('path,rect,circle,ellipse,line,polyline,polygon,text,image,use,foreignObject')
                .forEach((sh) => {
                  const b2 = sh.getBoundingClientRect();
                  if (b2.width > 2 && b2.height > 2 && b2.top < ink) ink = b2.top;
                });
              if (ink === Infinity) continue;
              effTop = ink;
            }
            if (effTop < tgBandBottom - 2) continue;            // band overlap → R-OVERLAP's job
            if (r.width > sr3.width * 0.9 && r.height > sr3.height * 0.65) continue; // bg panel
            if (!hasOwnText(el) && !isMedia3 && !visIsFramedBox(el)) continue;
            tgContentTop = Math.min(tgContentTop, effTop);
          }
        } else if (!header) {
          const sr = slide.getBoundingClientRect();
          // Collect ALL qualifying title candidates (top 40% of slide, ≥24px own-text)
          // sorted top→bottom — NOT just the single topmost. The same-row-peer guard
          // below then skips ONLY a candidate that is a column-row anchor (it shares
          // its row with a similar-size peer) and falls through to the next candidate,
          // instead of bailing the WHOLE slide. That way a genuine page title sitting
          // ABOVE a row of column anchors is still checked for crowding (N2 fix: the
          // old `return []` silenced every other crowded title on the slide).
          const titleCandidates = [];
          for (const el of slide.querySelectorAll('*')) {
            if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') continue;
            if (!hasOwnText(el)) continue;
            const cs = getComputedStyle(el);
            if (cs.position === 'absolute' || cs.position === 'fixed') continue;
            if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
            if (Math.round(parseFloat(cs.fontSize)) < 24) continue;
            const r = el.getBoundingClientRect();
            if (r.width <= 40 || r.height <= 16) continue;
            if ((r.top - sr.top) > sr.height * 0.4) continue;
            titleCandidates.push(el);
          }
          titleCandidates.sort((a, b) =>
            a.getBoundingClientRect().top - b.getBoundingClientRect().top);
          // Pick the topmost candidate that is NOT a column-row anchor. A column anchor
          // shares its row with another similar-size text block (e.g. `GPT之前 /
          // GPT时代 / Agent时代`, product-pane headers): treating a column's own content
          // as "crowding a column heading" is a false positive, so skip THAT candidate
          // and try the next (a real page title is alone on its top row).
          let tEl = null;
          for (const cand of titleCandidates) {
            const candRect = cand.getBoundingClientRect();
            const candFs = parseFloat(getComputedStyle(cand).fontSize) || 0;
            let candHasPeer = false;
            for (const el of slide.querySelectorAll('*')) {
              if (el === cand || cand.contains(el) || el.contains(cand)) continue;
              if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') continue;
              if (!hasOwnText(el)) continue;
              const cs = getComputedStyle(el);
              if (cs.position === 'absolute' || cs.position === 'fixed') continue;
              if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
              const fs = parseFloat(cs.fontSize) || 0;
              if (!(candFs > 0 && fs >= candFs * 0.75 && fs <= candFs * 1.25)) continue;
              const r = el.getBoundingClientRect();
              if (r.width <= 40 || r.height <= 16) continue;
              if (Math.abs(r.top - candRect.top) < candRect.height * 0.6) { candHasPeer = true; break; }
            }
            if (!candHasPeer) { tEl = cand; break; }   // first non-column-anchor title → protect this one
          }
          if (tEl) {
            tgTitleRect = tEl.getBoundingClientRect();
            tgTitleSel = shortSel(tEl);
            tgBandBottom = tgTitleRect.bottom;
            // Subtitle-folding: a bespoke title is frequently followed immediately by
            // its OWN subtitle (smaller font, ~single line, a few px below). That
            // subtitle is part of the title group, NOT content crowding the title —
            // measuring the gap to it produced false positives on the header-less raw
            // slides that are this branch's only callers. Geometrically (name-free)
            // fold an immediate subtitle into the band: own-text, font strictly
            // smaller than the title, ~single line tall, hugging the title (<24px
            // below). Then the gap is measured from the band bottom and the subtitle
            // is excluded from the content scan. A tall/large block right under the
            // title is NOT a subtitle and still fires (real crowding).
            const titleFs = parseFloat(getComputedStyle(tEl).fontSize) || 0;
            // (Column-row-anchor guard is now done during candidate selection above —
            //  `tEl` is already the topmost title that does NOT share its row with a
            //  similar-size peer, so the old slide-wide `return []` bail is gone: N2.)
            // Subtitle-folding: a bespoke title is frequently followed immediately by
            // its OWN subtitle (smaller font, ~single line, a few px below). That
            // subtitle is part of the title group, NOT content crowding the title.
            // Fold it into the band (geometry/name-free): own-text, font strictly
            // smaller than the title, ~single line tall, hugging the title (<24px).
            let subEl = null, subTop = Infinity;
            for (const el of slide.querySelectorAll('*')) {
              if (el === tEl || tEl.contains(el) || el.contains(tEl)) continue;
              if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') continue;
              if (!hasOwnText(el)) continue;
              const cs = getComputedStyle(el);
              if (cs.position === 'absolute' || cs.position === 'fixed') continue;
              if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
              const r = el.getBoundingClientRect();
              if (r.width <= 40 || r.height <= 16) continue;
              if (r.top < tgTitleRect.bottom - 2) continue;            // must sit below title
              const fs = parseFloat(cs.fontSize) || 0;
              const isSubtitle = fs > 0 && fs < titleFs
                && r.height <= fs * 3.2 * _scale                       // ≤2 行(行高 1.45 × 2 行 = 2.9×fs;F-301:旧 2.0 只放单行,2 行 page-sub(81px = 2.9×28)折不进带,被当成「假内容」量出 36px 假 gap 放行真拥挤)— rect height is SCALED (getBoundingClientRect), fs is UNSCALED computed px, so multiply the fs budget by _scale to compare like-for-like (same fix the sibling-distance test already applies below)
                && (r.top - tgTitleRect.bottom) < 44 * _scale;         // hugging the title(F-301:canonical .page-sub 间距 36px,旧 24 把按规范排的副标全排除在折叠外 → 36 + 8 容差)
              if (isSubtitle && r.top < subTop) { subTop = r.top; subEl = el; }
            }
            if (subEl) { tgBandBottom = subEl.getBoundingClientRect().bottom; }  // fold subtitle into the band; body floor still measured from this band bottom (M2)
            for (const el of slide.querySelectorAll('*')) {
              if (el === tEl || tEl.contains(el) || el.contains(tEl)) continue;
              if (subEl && (el === subEl || subEl.contains(el) || el.contains(subEl))) continue;
              if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') continue;
              // Name-free "crowding content" must be TEXT overflowing UP toward the
              // title (the rule's stated intent: "body grew / overflowed up"). A
              // decorative sibling GRAPHIC (e.g. the evo-arrow `<svg>` 8px under its
              // own `.evo-label`, a divider rule, a glow) is NOT body crowding a title
              // — and when the guessed "title" is itself a decorative label, its
              // adjacent graphic produced a phantom 8px gap (slide-4 false positive).
              // Geometric graphic overlaps are R-OVERLAP / R-VISUAL's job, not this.
              if (!hasOwnText(el)) continue;
              const cs = getComputedStyle(el);
              if (cs.position === 'absolute' || cs.position === 'fixed') continue;
              if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) continue;
              const r = el.getBoundingClientRect();
              if (r.width > 40 && r.height > 16 && r.top >= tgBandBottom - 2) {
                tgContentTop = Math.min(tgContentTop, r.top);
              }
            }
          }
        }
        if (!(tgTitleRect && tgBandBottom != null && tgContentTop !== Infinity && tgContentTop >= tgTitleRect.top - 2)) {
          return [];
        }
        const gap = (tgContentTop - tgBandBottom) / _scale;
        // Floor: 24px breathing room below the title band. When a subtitle is folded
        // into the band, `tgBandBottom` is the SUBTITLE bottom (the title is already
        // protected by the subtitle beneath it), so the gap is measured from the
        // subtitle band — but the BODY still must keep ~24px below that band, not 0.
        // M2 fix: the old `floor = 0` for folded subtitles silenced real 0–24px body
        // crowding under the subtitle (the title was protected, but the body could
        // jam right up against the subtitle and never fire). Keeping floor=24 measured
        // from the subtitle band bottom protects BOTH the title (via the band) and the
        // subtitle band's own breathing room.
        const floor = 24;
        if (gap >= floor) return [];
        const gapPx = Math.round(gap);
        // validate.py: _lev = err if gap_px<12 else warn(逐字搬)。
        const severity = gapPx < 12 ? 'error' : 'warn';
        return [{
          rule: 'R-VIS-TITLE-GAP', severity, slide_idx,
          layout, gap_px: gapPx, title_sel: tgTitleSel,
          message:
            `slide ${slide_idx} (layout \`${layout}\`) · content `
            + `sits only ${gapPx}px below the title (< 24px / overlapping). `
            + 'The body grew or overflowed UP toward `.header` — it is crowding / '
            + 'colliding with the title. Fix: shorten or shrink the content so it '
            + 'fits, OR move the content block DOWN (adjust the stage top / vertical '
            + 'centering). 死规矩:标题/副标题位置不动,压内容或下移正文,绝不动标题。',
        }];
      },
    },

    {
      // R-VIS-CROWD · 框内文字挤到底边。(步骤 3 第七批迁自 visual-audit.js 的 crowd
      // producer + validate.py 的 crowd 消费段)。几何逐字搬 producer:
      //   isHeroLayout / data-allow-imbalance 跳过;_framed = 后代里 _isFramedBox && !_isMediaBox
      //   && bbox 高 > 80*scale;_boxes = _framed 里非被其它 framed 包含的(最外层);
      //   每 box:cu=_contentUnion(box);distTop=(cu.top-r.top)/scale,distBottom=(r.bottom-
      //   cu.bottom)/scale;distBottom<10 && distTop>distBottom+16 → push。scale = ctx.scale。
      // 严重度(逐字搬 validate.py):always warn。文案逐字保留。截断 [:20]。
      id: 'R-VIS-CROWD',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, isHeroLayout, scale } = ctx;
        if (isHeroLayout || slide.hasAttribute('data-allow-imbalance')) return [];
        const _scale = scale;
        const findings = [];
        const _framed = [...slide.querySelectorAll('*')].filter((el) =>
          visIsFramedBox(el) && !visIsMediaBox(el)
          && el.getBoundingClientRect().height > 80 * _scale);
        const _boxes = _framed.filter((el) => !_framed.some((o) => o !== el && o.contains(el)));
        for (const box of _boxes) {
          // 框级/祖先 opt-out(2026-06-11):此前只认 .slide 级,作者按直觉把
          // data-allow-imbalance 加在框上会静默无效 → 两级都认。
          if (box.closest('[data-allow-imbalance]')) continue;
          // flowOnly(2026-06-11):绝对定位角标(mock 缩略图的 ".pptx" 等)是刻意
          // 摆放,不算"被挤到底"的流式内容;唯一文本=角标的 decor 盒整体跳过。
          const cu = visContentUnion(box, { flowOnly: true }); if (!cu) continue;
          const r = box.getBoundingClientRect();
          const distTop = (cu.top - r.top) / _scale;
          const distBottom = (r.bottom - cu.bottom) / _scale;
          if (distBottom < 10 && distTop > distBottom + 16) {
            const sel = shortSel(box);
            const topPx = Math.round(distTop);
            const bottomPx = Math.round(distBottom);
            findings.push({
              rule: 'R-VIS-CROWD', severity: 'warn', slide_idx,
              idx: slide_idx, label: ctx.label, sel,
              top_px: topPx, bottom_px: bottomPx,
              message:
                `slide ${slide_idx} · \`${sel}\` 框内文字贴底 —— 内容离框可见底边`
                + `只剩 ${bottomPx}px,顶部却留 ${topPx}px,文字被挤到框底。`
                + 'Fix: 让卡片按内容尺寸 + 垂直居中(参考 content-3up `align-self: center; '
                + 'justify-content: center`),或给框一个最小下内距 / 减少该框内容;'
                + '若等高框内文字贴底是刻意设计 → 在该框(或 `.slide`)加 `data-allow-imbalance`。',
            });
          }
        }
        return findings;
      },
    },

    {
      // R-VIS-PANEL-TOP · 框内单内容贴顶、下方大片空(crowd 的反向孪生)。(步骤 3 第七批
      // 迁自 visual-audit.js 的 panel_top producer + validate.py 的 panel_top 消费段)。
      // ⚠️ producer 里 panel_top 嵌在 crowd 同一个 _boxes 循环内,与 crowd 共用 _framed/_boxes/
      //   cu/r/distTop/distBottom;这里独立复算同一套 box 选择(纯几何,确定性,产出逐一对齐)。
      // 几何逐字搬 producer:cuH=(cu.bottom-cu.top)/scale;boxH=r.height/scale;
      //   boxH>160 && cuH>0 && cuH<boxH*0.62 && distTop<24 && distBottom>distTop+60 → push。
      // 严重度(逐字搬 validate.py):always warn。文案逐字保留。截断 [:20]。
      id: 'R-VIS-PANEL-TOP',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, isHeroLayout, scale } = ctx;
        if (isHeroLayout || slide.hasAttribute('data-allow-imbalance')) return [];
        const _scale = scale;
        const findings = [];
        const _framed = [...slide.querySelectorAll('*')].filter((el) =>
          visIsFramedBox(el) && !visIsMediaBox(el)
          && el.getBoundingClientRect().height > 80 * _scale);
        const _boxes = _framed.filter((el) => !_framed.some((o) => o !== el && o.contains(el)));
        for (const box of _boxes) {
          // 同 R-VIS-CROWD(2026-06-11):框级 opt-out + flowOnly 内容范围。
          if (box.closest('[data-allow-imbalance]')) continue;
          const cu = visContentUnion(box, { flowOnly: true }); if (!cu) continue;
          const r = box.getBoundingClientRect();
          const distTop = (cu.top - r.top) / _scale;
          const distBottom = (r.bottom - cu.bottom) / _scale;
          const cuH = (cu.bottom - cu.top) / _scale;
          const boxH = r.height / _scale;
          if (boxH > 160 && cuH > 0 && cuH < boxH * 0.62
              && distTop < 24 && distBottom > distTop + 60) {
            const sel = shortSel(box);
            const topPx = Math.round(distTop);
            const bottomPx = Math.round(distBottom);
            const contentH = Math.round(cuH);
            const boxHpx = Math.round(boxH);
            findings.push({
              rule: 'R-VIS-PANEL-TOP', severity: 'warn', slide_idx,
              idx: slide_idx, label: ctx.label, sel,
              top_px: topPx, bottom_px: bottomPx,
              content_h: contentH, box_h: boxHpx,
              message:
                `slide ${slide_idx} · \`${sel}\` 面板内单内容贴顶 —— 内容高 `
                + `${contentH}px 只占框 ${boxHpx}px 的一部分,顶距 `
                + `${topPx}px、底部却空了 ${bottomPx}px,内容卡在框顶。`
                + 'Fix: 给该面板容器(panel/pane/col-visual 类)加 `display:flex; '
                + 'flex-direction:column; justify-content:center`,让单内容在框内垂直居中'
                + '(框架已对 content-2col `.col-visual` 单子默认居中;lifted/raw 页的自定义 '
                + 'panel 需在该页 `custom_css` 补这条);若刻意顶对齐 → 在该框(或 `.slide`)加 '
                + '`data-allow-imbalance`。',
            });
          }
        }
        return findings;
      },
    },

    {
      // R-VIS-BALANCE · 视觉重心 / 留白均衡。(步骤 3 第七批迁自 visual-audit.js 的 balance
      // producer + validate.py 的 balance 消费段)。几何逐字搬 producer(全部用 raw px,不除
      // scale —— 阈值 120/140/150/0.22 皆 raw,与 producer 一致):
      //   isHeroLayout / data-allow-imbalance 跳过;bodyContainer = :scope>.stage / .grid / .flow
      //     / .nodes / .toc / .table-wrap / .stack / slide(兜底);单子且子 class 含 grid/flow/
      //     nodes/toc/table-wrap/stack → 钻进去;height>=200 && width>=200;
      //   blocks = 顶层可见 children(非 STYLE/SCRIPT/none/hidden/absolute/fixed,w>8&&h>8)按 top;
      //   slack = topGap+bottomGap;slack>150 时:bottomGap>topGap+120 → top-heavy,
      //     topGap>bottomGap+120 → bottom-heavy;相邻块 gap>140 → dead-band;
      //   side-empty:contentEls(text|media 叶,可见,w>=8&&h>=8)左右 slack,
      //     leftSlack+rightSlack>0.22*bw && |L-R|>0.22*bw && |L-R|>200 → push。
      // 严重度(逐字搬 validate.py):always warn(四 sub-kind 皆 warn)。文案逐字保留。截断 [:25]。
      id: 'R-VIS-BALANCE',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, isHeroLayout } = ctx;
        if (isHeroLayout || slide.hasAttribute('data-allow-imbalance')) return [];
        const findings = [];
        let bodyContainer = slide.querySelector(':scope > .stage')
          || slide.querySelector(':scope > .grid')
          || slide.querySelector(':scope > .flow')
          || slide.querySelector(':scope > .nodes')
          || slide.querySelector(':scope > .toc')
          || slide.querySelector(':scope > .table-wrap')
          || slide.querySelector(':scope > .stack')
          || slide;
        while (bodyContainer && bodyContainer.children.length === 1) {
          const only = bodyContainer.children[0];
          const rawc = only.className;
          const clsc = (rawc && rawc.baseVal !== undefined ? rawc.baseVal
            : (rawc || '')).toString().toLowerCase();
          if (/\b(grid|flow|nodes|toc|table-wrap|stack)\b/.test(clsc)) {
            bodyContainer = only;
          } else { break; }
        }
        if (!bodyContainer) return [];
        const bodyRect = bodyContainer.getBoundingClientRect();
        if (!(bodyRect.height >= 200 && bodyRect.width >= 200)) return [];
        const blocks = [...bodyContainer.children].filter((c) => {
          if (c.tagName === 'STYLE' || c.tagName === 'SCRIPT') return false;
          const cs = getComputedStyle(c);
          if (cs.display === 'none' || cs.visibility === 'hidden') return false;
          if (cs.position === 'absolute' || cs.position === 'fixed') return false;
          const r = c.getBoundingClientRect();
          return r.width > 8 && r.height > 8;
        }).map((c) => ({ el: c, rect: c.getBoundingClientRect() }))
          .sort((a, b) => a.rect.top - b.rect.top);
        if (blocks.length === 0) return [];
        const containerSel = shortSel(bodyContainer);
        const contentTop = blocks[0].rect.top;
        const contentBottom = blocks[blocks.length - 1].rect.bottom;
        const topGap = contentTop - bodyRect.top;
        const bottomGap = bodyRect.bottom - contentBottom;
        const slack = topGap + bottomGap;
        if (slack > 150) {
          if (bottomGap > topGap + 120) {
            findings.push({
              rule: 'R-VIS-BALANCE', severity: 'warn', slide_idx,
              container_sel: containerSel, kind: 'top-heavy',
              top_gap: Math.round(topGap), bottom_gap: Math.round(bottomGap),
              body_height: Math.round(bodyRect.height),
              message:
                `slide ${slide_idx} · \`${containerSel}\` `
                + `上重下空(top-heavy): 顶部留白 ${Math.round(topGap)}px,`
                + `底部留白 ${Math.round(bottomGap)}px (容器高 ${Math.round(bodyRect.height)}px) `
                + '— 内容堆在顶部,下半页大块空白。Fix: (1) 容器加 '
                + '`justify-content: center`(框架对 fixed-shape layout 已默认开 R48,'
                + '但 raw / flex column 默认 flex-start,需手动加);(2) 删 `flex: 1` 让'
                + '内容随高度伸展的情况,改成 content-sized + center;(3) 内容确实太少 → '
                + '加 supporting 元素(KPI / pullquote / case ref)填重心。Per-slide '
                + 'opt-out: 在 .slide 加 `data-allow-imbalance` 标记为故意。',
            });
          } else if (topGap > bottomGap + 120) {
            findings.push({
              rule: 'R-VIS-BALANCE', severity: 'warn', slide_idx,
              container_sel: containerSel, kind: 'bottom-heavy',
              top_gap: Math.round(topGap), bottom_gap: Math.round(bottomGap),
              body_height: Math.round(bodyRect.height),
              message:
                `slide ${slide_idx} · \`${containerSel}\` `
                + `下重上空(bottom-heavy): 顶部留白 ${Math.round(topGap)}px,`
                + `底部留白 ${Math.round(bottomGap)}px (容器高 ${Math.round(bodyRect.height)}px) `
                + '— 内容沉底,上半页大块空白。Fix: 容器 `justify-content: center` '
                + '或 `align-content: center`;或检查是否有 `margin-top: auto` 把'
                + '内容硬推到底部(BF9 反模式)。',
            });
          }
        }
        for (let i = 1; i < blocks.length; i++) {
          const prev = blocks[i - 1].rect;
          const curr = blocks[i].rect;
          const gap = curr.top - prev.bottom;
          if (gap > 140) {
            findings.push({
              rule: 'R-VIS-BALANCE', severity: 'warn', slide_idx,
              container_sel: containerSel, kind: 'dead-band',
              gap_px: Math.round(gap),
              between_a: shortSel(blocks[i - 1].el),
              between_b: shortSel(blocks[i].el),
              message:
                `slide ${slide_idx} · \`${containerSel}\` `
                + `中间留白 ${Math.round(gap)}px(dead-band)— \`${shortSel(blocks[i - 1].el)}\` `
                + `和 \`${shortSel(blocks[i].el)}\` 之间有一条 >140px 的空带,`
                + '页面被切成两半。Fix: (1) 容器去掉 `flex: 1` / `justify-content: '
                + 'space-between`(BF9 反模式经常制造这种空白);(2) 缩小 gap;(3) '
                + '在中间加一行 supporting 元素(pullquote / KPI / divider);(4) '
                + '确实是设计意图(留白让 hero 呼吸)→ 加 `data-allow-imbalance`。',
            });
          }
        }
        const contentEls = [...bodyContainer.querySelectorAll('*')].filter((el) => {
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return false;
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return false;
          const r = el.getBoundingClientRect();
          if (r.width < 8 || r.height < 8) return false;
          const hasText = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
          const isMedia = el.matches('img,video,canvas,iframe,picture,svg')
            || (cs.backgroundImage && cs.backgroundImage !== 'none'
                && !/gradient/i.test(cs.backgroundImage));
          return hasText || isMedia;
        });
        if (contentEls.length) {
          let cl = Infinity, cr = -Infinity;
          for (const el of contentEls) {
            const r = el.getBoundingClientRect(); cl = Math.min(cl, r.left); cr = Math.max(cr, r.right);
          }
          const leftSlack = cl - bodyRect.left;
          const rightSlack = bodyRect.right - cr;
          const bw = bodyRect.width;
          if (leftSlack + rightSlack > 0.22 * bw
              && Math.abs(leftSlack - rightSlack) > 0.22 * bw
              && Math.abs(leftSlack - rightSlack) > 200) {
            const _side = rightSlack > leftSlack ? '右侧' : '左侧';
            findings.push({
              rule: 'R-VIS-BALANCE', severity: 'warn', slide_idx,
              container_sel: containerSel, kind: 'side-empty',
              left_slack: Math.round(leftSlack), right_slack: Math.round(rightSlack),
              body_width: Math.round(bw),
              message:
                `slide ${slide_idx} · \`${containerSel}\` `
                + `横向失衡 / 单侧空壳(side-empty): 左空 ${Math.round(leftSlack)}px / `
                + `右空 ${Math.round(rightSlack)}px(容器宽 ${Math.round(bw)}px)— `
                + `真实内容(文字/图)挤向一边,${_side}一大块空(空框不算内容)。`
                + '常见 #36「右半是个空壳面板」/ 内容偏左。Fix: (1) 给空的一侧填真内容 '
                + '(图示 / 截图重建 / 要点);(2) 缩窄空面板、让内容两栏铺满;(3) 单列'
                + '窄条飘着 → 加宽或配伴随块。真有图但被判空说明图是 media→已计入不会误报;'
                + '故意留白 → `data-allow-imbalance`。',
            });
          }
        }
        return findings;
      },
    },

    {
      // R-VIS-GUTTER · 同组相邻框间距不等 / 框内 padding 不一致。(步骤 3 第七批迁自
      // visual-audit.js 的 gutter producer + validate.py 的 gutter 消费段)。几何逐字搬 producer:
      //   isHeroLayout / data-allow-imbalance 跳过;遍历 flex/grid 容器,kids = 直接子里
      //   可见 && _isFramedBox && !_isMediaBox && bbox 高/宽 > 40*scale;kids<3 跳;
      //   按主轴(x 跨度 >= y 跨度 = 横向)排序;相邻同轴对(中心错位 <半高/半宽)算 gutter
      //   (/scale);≥2 gutter 且 gmax>max(gmin,1)*1.8 && (gmax-gmin)>10 → gutter finding;
      //   再按 tag 分组(≥3),每框 padding = min(cu.top-r.top, r.bottom-cu.bottom)/scale
      //   (任一 cu 缺或 pd<-2 整组作废);≥3 且 pmax>max(pmin,1)*1.8 && (pmax-pmin)>10 →
      //   padding finding;_gutterSeen 去重(g::sel / p::sel::tag)。scale = ctx.scale。
      // ⚠️ lifted-downgrade PRESERVE-EXACTLY:gutter producer 【从不】在 entry 上写 `lifted`
      //   字段(g:: / p:: 两分支都没有);validate.py 消费段 `entry.get('lifted')` 因此恒
      //   falsy → warn_soft / "LIFTED" 前缀分支【永远】是死的 —— 本规则同样不带 lifted,
      //   severity 恒 warn、无 lifted 前缀,与 validate.py 现行行为零漂移(对照 batch7 的
      //   card_overflow 死 lift 降级)。
      // 严重度(逐字搬 validate.py):恒 warn(lifted 分支死)。文案逐字保留。截断 [:20]。
      id: 'R-VIS-GUTTER',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, isHeroLayout, scale } = ctx;
        if (isHeroLayout || slide.hasAttribute('data-allow-imbalance')) return [];
        const _scale = scale;
        const findings = [];
        const _vis = (el) => {
          const cs = getComputedStyle(el);
          return cs.display !== 'none' && cs.visibility !== 'hidden'
            && cs.position !== 'absolute' && cs.position !== 'fixed';
        };
        const _gutterSeen = new Set();
        slide.querySelectorAll('*').forEach((container) => {
          const ccs = getComputedStyle(container);
          if (!['flex', 'inline-flex', 'grid', 'inline-grid'].includes(ccs.display)) return;
          const kids = [...container.children].filter((el) => {
            if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return false;
            if (!_vis(el) || !visIsFramedBox(el) || visIsMediaBox(el)) return false;
            const r = el.getBoundingClientRect();
            return r.height > 40 * _scale && r.width > 40 * _scale;
          });
          if (kids.length < 3) return;
          const rects = kids.map((el) => ({ el, r: el.getBoundingClientRect() }));
          const xs = rects.map((o) => o.r.left + o.r.width / 2);
          const ys = rects.map((o) => o.r.top + o.r.height / 2);
          const horizontal = (Math.max(...xs) - Math.min(...xs)) >= (Math.max(...ys) - Math.min(...ys));
          rects.sort((a, b) => (horizontal ? (a.r.left - b.r.left) : (a.r.top - b.r.top)));
          const gutters = [];
          for (let i = 1; i < rects.length; i++) {
            const a = rects[i - 1].r, b = rects[i].r;
            if (horizontal) {
              if (Math.abs((a.top + a.height / 2) - (b.top + b.height / 2)) > a.height / 2) continue;
              gutters.push(Math.max(0, (b.left - a.right) / _scale));
            } else {
              if (Math.abs((a.left + a.width / 2) - (b.left + b.width / 2)) > a.width / 2) continue;
              gutters.push(Math.max(0, (b.top - a.bottom) / _scale));
            }
          }
          if (gutters.length >= 2) {
            const gmin = Math.min(...gutters), gmax = Math.max(...gutters);
            if (gmax > (gmin < 1 ? 1 : gmin) * 1.8 && (gmax - gmin) > 10) {
              const key = 'g::' + shortSel(container);
              if (!_gutterSeen.has(key)) {
                _gutterSeen.add(key);
                const containerSel = shortSel(container);
                const axis = horizontal ? 'row' : 'column';
                const guttersR = gutters.map((g) => Math.round(g));
                const minPx = Math.round(gmin), maxPx = Math.round(gmax);
                // validate.py: _lev = warn_soft if entry.lifted else warn — producer 不带
                // lifted → 恒 warn(死降级,见 rule 头注释)。
                findings.push({
                  rule: 'R-VIS-GUTTER', severity: 'warn', slide_idx,
                  label: ctx.label, kind: 'gutter', container_sel: containerSel,
                  axis, gutters: guttersR, min_px: minPx, max_px: maxPx,
                  count: kids.length,
                  message:
                    `slide ${slide_idx} · \`${containerSel}\` 同组相邻框`
                    + `(${axis})间距不等:${guttersR}px(min ${minPx} / `
                    + `max ${maxPx})。同组框 gutter 应相等才齐整(P7 #3:卡片左右 `
                    + '28px 但到下面只 8px)。Fix:把 gap 统一;故意不均 → .slide 加 '
                    + '`data-allow-imbalance`。',
                });
              }
            }
          }
          const byTag = {};
          for (const { el } of rects) (byTag[el.tagName] = byTag[el.tagName] || []).push(el);
          for (const tag of Object.keys(byTag)) {
            const group = byTag[tag];
            if (group.length < 3) continue;
            const pads = [];
            let abort = false;
            for (const el of group) {
              const cu = visContentUnion(el); if (!cu) { abort = true; break; }
              const r = el.getBoundingClientRect();
              const pd = Math.min((cu.top - r.top), (r.bottom - cu.bottom)) / _scale;
              if (pd < -2) { abort = true; break; }
              pads.push(Math.max(0, pd));
            }
            if (abort || pads.length < 3) continue;
            const pmin = Math.min(...pads), pmax = Math.max(...pads);
            if (pmax > (pmin < 1 ? 1 : pmin) * 1.8 && (pmax - pmin) > 10) {
              const key = 'p::' + shortSel(container) + '::' + tag;
              if (!_gutterSeen.has(key)) {
                _gutterSeen.add(key);
                const containerSel = shortSel(container);
                const cellTag = tag.toLowerCase();
                const padsR = pads.map((p) => Math.round(p));
                const minPx = Math.round(pmin), maxPx = Math.round(pmax);
                findings.push({
                  rule: 'R-VIS-GUTTER', severity: 'warn', slide_idx,
                  label: ctx.label, kind: 'padding', container_sel: containerSel,
                  cell_tag: cellTag, pads: padsR, min_px: minPx, max_px: maxPx,
                  count: group.length,
                  message:
                    `slide ${slide_idx} · \`${containerSel}\` 同 tag `
                    + `\`${cellTag}\` 组框的内 padding 不一致:${padsR}px`
                    + `(min ${minPx} / max ${maxPx})。同类 cell 内容到`
                    + '边框的距离应一致才好看(P7 #4)。Fix:统一 padding / 让内容等距居中。',
                });
              }
            }
          }
        });
        return findings;
      },
    },

    {
      // R-OVERLAP · body 容器内 sibling bbox 物理交叠。(步骤 3 第九批迁自 visual-audit.js
      // 的 overlap producer + validate.py 的 overlap 消费段)。几何逐字搬 producer:
      //   containers = slide 内 .stage/.grid/.flow/.nodes/.toc/.stack/.table-wrap;
      //   kids = 直接子里可见(非 none/hidden/absolute/fixed,offsetW/H≠0);两两 i<j 对,
      //   overlapX=min(right)-max(left),overlapY=min(bottom)-max(top);>2 && >2 → push;
      //   seenPairs(slide::aSel::bSel)去重。无 scale(纯像素交叠)。
      // 严重度(逐字搬 validate.py):always err。文案逐字保留。截断 [:20]。
      id: 'R-OVERLAP',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const findings = [];
        const containers = slide.querySelectorAll(
          '.stage, .grid, .flow, .nodes, .toc, .stack, .table-wrap');
        const seenPairs = new Set();
        containers.forEach((container) => {
          const kids = Array.from(container.children).filter((c) => {
            const cs = getComputedStyle(c);
            if (cs.display === 'none' || cs.visibility === 'hidden') return false;
            if (cs.position === 'absolute' || cs.position === 'fixed') return false;
            if (c.offsetWidth === 0 || c.offsetHeight === 0) return false;
            return true;
          });
          for (let i = 0; i < kids.length; i++) {
            for (let j = i + 1; j < kids.length; j++) {
              const a = kids[i].getBoundingClientRect();
              const b = kids[j].getBoundingClientRect();
              const overlapX = Math.min(a.right, b.right) - Math.max(a.left, b.left);
              const overlapY = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
              // 2 px tolerance — 亚像素 rounding 会产生 0.5-1px 名义交叠。
              if (overlapX > 2 && overlapY > 2) {
                const aSel = shortSel(kids[i]);
                const bSel = shortSel(kids[j]);
                const key = `${slide_idx}::${aSel}::${bSel}`;
                if (seenPairs.has(key)) continue;
                seenPairs.add(key);
                const containerSel = shortSel(container);
                const ox = Math.round(overlapX);
                const oy = Math.round(overlapY);
                findings.push({
                  rule: 'R-OVERLAP', severity: 'error', slide_idx,
                  container_sel: containerSel, a_sel: aSel, b_sel: bSel,
                  overlap_x: ox, overlap_y: oy,
                  message:
                    `slide ${slide_idx} · siblings inside \`${containerSel}\` `
                    + `physically overlap: \`${aSel}\` and \`${bSel}\` `
                    + `intersect by ${ox}×${oy} px. `
                    + 'One sibling overflowed its allocated row/column and crashed '
                    + 'into another. Fix: tighten content (smaller padding/gap, fewer '
                    + 'items), expand the container (use `.stage.stage--tall` for 750 px '
                    + 'vs default 680 px height), or add `min-height: 0; overflow: hidden` '
                    + 'on the overflowing element so excess content is clipped instead of '
                    + 'bleeding into siblings.',
                });
              }
            }
          }
        });
        return findings;
      },
    },

    {
      // R-VIS-ABS-OVERLAP · F-313 (2026-06-13) · 两个各自 position:absolute 的内容块
      // 在画面上相互重叠(包围盒相交)。补 R-OVERLAP / R-VIS-BAND-COLLIDE 的盲区:
      //   · R-OVERLAP 只查 framework 容器(.stage/.grid/.flow/...)内的「流式同级块」,
      //     且 4788 行显式 `position:absolute|fixed → return false` 把绝对定位全跳过;
      //   · R-VIS-BAND-COLLIDE 只查 absolute「带」压到 .stage/.grid 等 host 内的流式正文;
      //   两者都漏「raw/自定义页里两个各自 absolute 的块直接叠在一起」(本 session 实证:
      //   voice-hub 中枢卡片被内容撑高、压进底部 SEEN/ROUTED 支柱区,8 处文字叠文字,
      //   render 全绿、capture-frames 也过——因为没有任何规则比对独立绝对块之间的几何)。
      // 方法(name-free,纯几何):收最外层 absolute/fixed、可见、自带文字(textContent≥4)、
      //   非全屏脚手架(面积<画布62%)、非 SVG/装饰(pointer-events≠none)的内容块;两两求交,
      //   ix>8 && iy>8 视为真二维交叠;再确认「一方的文字叶子压进另一方的盒子」(text-in-box)
      //   才报——纯 padding/margin 交叠不算,降误报。warn(启发式,不阻断;`data-allow-overlap`
      //   显式豁免有意叠放的浮层)。截断 6 条/页。
      id: 'R-VIS-ABS-OVERLAP',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const sr = slide.getBoundingClientRect();
        const slideArea = (sr.width * sr.height) || 1;
        const scale = (sr.height / 1080) || 1;
        const interOf = (a, b) => ({
          ix: Math.min(a.right, b.right) - Math.max(a.left, b.left),
          iy: Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top),
        });
        // 升 error(阻断)仅限「静态」块:带 transform 的(slide-in 浮层 / 动效收起态)
        // 易被审计在非 present 上下文量出幻影交叠(实证:renwu mock 的 .rw-detail-layer
        // translateX 收起态在 present 下与 tabbar 有 14px 间隙、审计却报 45px)—— 故只 warn 不阻断。
        const _identityTf = (el) => {
          const t = getComputedStyle(el).transform;
          return t === 'none' || t === 'matrix(1, 0, 0, 1, 0, 0)';
        };
        // 1) 收候选:最外层 absolute/fixed 文本内容块
        const raw = [];
        for (const el of slide.querySelectorAll('*')) {
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') continue;
          if (el.tagName === 'svg' || el.tagName === 'SVG' || el.closest('svg')) continue;
          const cs = getComputedStyle(el);
          if (cs.position !== 'absolute' && cs.position !== 'fixed') continue;
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity < 0.1) continue;
          // ⚠ 不按 pointer-events 过滤:present 模式下非当前帧整体 `pointer-events:none`,
          //   会被所有后代继承 —— 审计逐页量时当前帧只有 1 个,其余帧的候选会被全部误杀
          //   (F-313 调试实证:整页 blocks=[])。装饰层(svg 流线/光晕/动效点)已由上面的
          //   svg 排除 + 下面的「无真实文字」排除覆盖,无需 pointer-events 这条。
          if ((el.textContent || '').trim().length < 4) continue;     // 必须自带真实文字
          const r = el.getBoundingClientRect();
          if (r.width < 24 || r.height < 16) continue;
          if (r.width * r.height > slideArea * 0.62) continue;        // 跳过全屏脚手架容器
          raw.push({ el, r });
        }
        // 只留最外层(若某候选的祖先也是候选 → 丢弃,比对顶层块而非其嵌套文字)
        const blocks = raw.filter((c) =>
          !raw.some((o) => o.el !== c.el && o.el.contains(c.el)));
        // own-text 叶子 rect(含自身,若自带文字)
        const leafRects = (el) => {
          const out = [];
          if (hasOwnText(el)) out.push(el.getBoundingClientRect());
          for (const n of el.querySelectorAll('*')) {
            if (!hasOwnText(n)) continue;
            const cs = getComputedStyle(n);
            if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity < 0.1) continue;
            const r = n.getBoundingClientRect();
            if (r.width > 2 && r.height > 2) out.push(r);
          }
          return out;
        };
        // 该块是否「画了东西」(有不透明底色 / 背景图 / 边框)——只有会 paint 的块压住
        // 另一方文字才算真遮挡。透明大容器(.lcol/.rcol 跨全高但内容只占一段)套住别人
        // 文字不算缺陷,靠这条排除(否则 header 落在透明 .lcol 空白区会误报)。
        const paints = (el) => {
          const cs = getComputedStyle(el);
          const bg = (cs.backgroundColor || '').replace(/\s/g, '');
          const bgVisible = bg && bg !== 'transparent' && !/,0\)$/.test(bg);   // rgba(...,0) = 透明
          const bgImg = cs.backgroundImage && cs.backgroundImage !== 'none';
          const bd = (parseFloat(cs.borderTopWidth) || 0) + (parseFloat(cs.borderBottomWidth) || 0)
            + (parseFloat(cs.borderLeftWidth) || 0) + (parseFloat(cs.borderRightWidth) || 0);
          return !!(bgVisible || bgImg || bd > 0);
        };
        const findings = [];
        const seen = new Set();
        for (let i = 0; i < blocks.length; i++) {
          for (let j = i + 1; j < blocks.length; j++) {
            const A = blocks[i], B = blocks[j];
            if (A.el.closest('[data-allow-overlap]') || B.el.closest('[data-allow-overlap]')) continue;
            const o = interOf(A.r, B.r);
            if (o.ix <= 8 || o.iy <= 8) continue;                    // 需真二维交叠
            // 确认真遮挡:一方「会 paint」的盒子压住了另一方的文字叶子
            const aCoversB = paints(A.el) && leafRects(B.el).some((l) => { const t = interOf(l, A.r); return t.ix > 4 && t.iy > 4; });
            const bCoversA = paints(B.el) && leafRects(A.el).some((l) => { const t = interOf(l, B.r); return t.ix > 4 && t.iy > 4; });
            if (!aCoversB && !bCoversA) continue;                    // 没有「不透明盒压文字」→ 跳过
            const aSel = shortSel(A.el), bSel = shortSel(B.el);
            const key = `${slide_idx}::${aSel}::${bSel}`;
            if (seen.has(key)) continue;
            seen.add(key);
            findings.push({
              rule: 'R-VIS-ABS-OVERLAP',
              // 大面积二维压字(≥40 design px 双轴)= 肉眼明确缺陷 → 升 error 阻断(别再静默 PASS);
              // 小面积边缘擦碰仍 warn(防误报)。沿用 R-VIS-TITLE-GAP 的 warn→err 阈值升级先例。
              severity: (o.ix / scale >= 40 && o.iy / scale >= 40
                && _identityTf(A.el) && _identityTf(B.el)) ? 'error' : 'warn',
              slide_idx,
              a_sel: aSel, b_sel: bSel,
              overlap_x: Math.round(o.ix / scale), overlap_y: Math.round(o.iy / scale),
              message:
                `slide ${slide_idx} · 两个独立绝对定位内容块在画面上相互重叠:\`${aSel}\` 与 \`${bSel}\` `
                + `交叠 ${Math.round(o.ix / scale)}×${Math.round(o.iy / scale)}px,且一方文字压进了另一方的盒子(文字叠文字 / 文字压框)。`
                + 'R-OVERLAP 只查 framework 容器内的流式同级块(跳过 absolute)、R-VIS-BAND-COLLIDE 只查 .stage/.grid 等 host 内带压正文 —— '
                + '都漏了 raw/自定义页里两个各自 `position:absolute` 的块直接叠这一类(本规则补盲)。'
                + 'Fix: 改其一的 top / 缩高 / 换位,或收紧内容别撑高越界,让两块包围盒不再相交;'
                + '确属有意叠放(浮层)→ 给其一加 `data-allow-overlap`。',
            });
            if (findings.length >= 6) return findings;
          }
        }
        // === 媒体框压文字块(F-313 补盲二期)===========================================
        // 上面只两两配「带文字」的 absolute 块;图片/插画栏(.art 等)自身无文字 →
        // 被 textContent<4 过滤掉,图文左右分栏时图栏吃进文字栏这一类完全盲掉
        // (实测:.rail[left96 w700,右沿796] 与 .art[图片,left720] 交叠 76px,渲染门禁全绿放行)。
        // 这里把「无文字的 absolute 媒体框」当遮挡方,与已收的文字块 `blocks` 求包围盒交叠。
        if (!['cover', 'image-text', 'end', 'section'].includes(ctx.layout || '')) {
          const mraw = [];
          for (const el of slide.querySelectorAll('*')) {
            if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') continue;
            const cs = getComputedStyle(el);
            if (cs.position !== 'absolute' && cs.position !== 'fixed') continue;
            if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity < 0.1) continue;
            if (!visIsMediaBox(el)) continue;                          // 必须是图片/媒体框
            if ((el.textContent || '').trim().length >= 4) continue;   // 带文字的(mock UI 等)归上面 text 分支
            if (visHasAnyClass(el, ['wordmark', 'grid-bg', 'aurora', 'decor'])) continue;
            const r = el.getBoundingClientRect();
            if (r.width < 60 || r.height < 60) continue;               // 跳过小图标 / 头像
            if (r.width * r.height > slideArea * 0.62) continue;       // 跳过近满幅背景图
            mraw.push({ el, r });
          }
          const media = mraw.filter((c) => !mraw.some((o) => o.el !== c.el && o.el.contains(c.el)));
          for (const M of media) {
            if (M.el.closest('[data-allow-overlap]')) continue;
            for (const T of blocks) {                                  // blocks = 最外层 absolute 文本块
              if (T.el.contains(M.el) || M.el.contains(T.el)) continue;
              if (T.el.closest('[data-allow-overlap]')) continue;
              const o = interOf(M.r, T.r);
              if (o.ix / scale <= 16 || o.iy / scale <= 16) continue;  // 真二维交叠(≥16 design px,躲阴影/亚像素)
              const aSel = shortSel(M.el), bSel = shortSel(T.el);
              const key = `${slide_idx}::${aSel}::${bSel}`;
              if (seen.has(key)) continue;
              seen.add(key);
              findings.push({
                rule: 'R-VIS-ABS-OVERLAP',
                severity: (o.ix / scale >= 40 && o.iy / scale >= 40
                  && _identityTf(M.el) && _identityTf(T.el)) ? 'error' : 'warn',
                slide_idx,
                a_sel: aSel, b_sel: bSel,
                overlap_x: Math.round(o.ix / scale), overlap_y: Math.round(o.iy / scale),
                message:
                  `slide ${slide_idx} · 绝对定位的图片/媒体块 \`${aSel}\` 与文字块 \`${bSel}\` 包围盒相交 `
                  + `${Math.round(o.ix / scale)}×${Math.round(o.iy / scale)}px —— 图文左右分栏时图片栏吃进文字栏(或文字栏被图盖)。`
                  + '原 R-VIS-ABS-OVERLAP 只配「带文字」的两块,媒体框无文字 → 这类图压文字盲掉(本次补)。'
                  + 'Fix: 调整图片或文字栏的 left/right/width 留出 gutter 让两栏不再相交;'
                  + '确属有意叠放(图上压字)→ 给其一加 `data-allow-overlap` 或改用 image-text 版式。',
              });
              if (findings.length >= 6) return findings;
            }
          }
        }
        return findings;
      },
    },

    {
      // R-VIS-BAND-COLLIDE · 绝对定位内容带压住流式正文。(步骤 3 第九批迁自 visual-audit.js
      // 的 band_collide producer + validate.py 的 band_collide 消费段)。几何逐字搬 producer:
      //   layout ∉ {cover,image-text,end,section};bands = .slide 直接子里 absolute/fixed、
      //   可见、offsetW/H≠0、非 CHROME_WHITELIST、非 wordmark/pageno/deck-progress/deck-controls/
      //   grid-bg/aurora/decor、_isFramedBox && !_isMediaBox、textContent.trim≥4;
      //   hosts = :scope>.stage/.grid/.flow/.nodes/.toc/.stack/.table-wrap;每 band 对每 host 的
      //   own-text 可见 leaf(w,h≥2)求交,ox>2 && oy>4 → 命中(first hit 即停)。无 scale。
      // 严重度(逐字搬 validate.py):always err。文案逐字保留。截断 [:20]。
      id: 'R-VIS-BAND-COLLIDE',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx, layout } = ctx;
        if (['cover', 'image-text', 'end', 'section'].includes(layout)) return [];
        const findings = [];
        const bands = Array.from(slide.children).filter((el) => {
          const cs = getComputedStyle(el);
          if (cs.position !== 'absolute' && cs.position !== 'fixed') return false;
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return false;
          if (el.offsetWidth === 0 || el.offsetHeight === 0) return false;
          if (visHasAnyClass(el, VIS_CHROME_WHITELIST)) return false;
          if (visHasAnyClass(el, ['wordmark', 'pageno', 'deck-progress', 'deck-controls',
            'grid-bg', 'aurora', 'decor'])) return false;
          if (!visIsFramedBox(el) || visIsMediaBox(el)) return false;   // 纯装饰 / 媒体 → 非内容带
          if (el.textContent.trim().length < 4) return false;          // 必须带真文案
          return true;
        });
        if (!bands.length) return [];
        const hosts = Array.from(slide.querySelectorAll(
          ':scope > .stage, :scope > .grid, :scope > .flow, :scope > .nodes, '
          + ':scope > .toc, :scope > .stack, :scope > .table-wrap'));
        bands.forEach((band) => {
          const bb = band.getBoundingClientRect();
          let hit = null;
          for (const host of hosts) {
            if (host === band || host.contains(band) || band.contains(host)) continue;
            for (const leaf of host.querySelectorAll('*')) {
              if (!hasOwnText(leaf)) continue;
              const cs = getComputedStyle(leaf);
              if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) continue;
              const lr = leaf.getBoundingClientRect();
              if (lr.width < 2 || lr.height < 2) continue;
              const ox = Math.min(bb.right, lr.right) - Math.max(bb.left, lr.left);
              const oy = Math.min(bb.bottom, lr.bottom) - Math.max(bb.top, lr.top);
              if (ox > 2 && oy > 4) { hit = { host, leaf, ox, oy }; break; }   // 真竖向侵入正文
            }
            if (hit) break;
          }
          if (hit) {
            const bandSel = shortSel(band);
            const hostSel = shortSel(hit.host);
            const contentSel = shortSel(hit.leaf);
            const ox = Math.round(hit.ox);
            const oy = Math.round(hit.oy);
            findings.push({
              rule: 'R-VIS-BAND-COLLIDE', severity: 'error', slide_idx,
              band_sel: bandSel, host_sel: hostSel, content_sel: contentSel,
              overlap_x: ox, overlap_y: oy,
              message:
                `slide ${slide_idx} · 绝对定位内容带 \`${bandSel}\` 压住正文 `
                + `\`${contentSel}\`(交叠 ${ox}×${oy}px)。`
                + '底部/顶部内容带(takeaway / cta / principle-band 等有文字有底色的"带")若用 '
                + 'position:absolute 挂在 .slide 上,运行时画布居中(centerSlideInCanvas)会把 '
                + 'absolute 元素排除在内容并集外 → 把正文居中进带子下面、视觉重叠(旧 R-OVERLAP '
                + '只查同容器兄弟,查不出这种)。Fix:把内容带作为 `.stage`(flex column)最后一个 '
                + '流式子元素 + `margin-top` 间隔,让正文+带子作为整体被居中;或把 .stage 调高 / 内容下沉。'
                + '绝不靠缩字号或让内容贴边。',
            });
          }
        });
        return findings;
      },
    },

    {
      // R-VIS-ABSPOS-DUAL-ANCHOR · absolute 元素 top+bottom 双锚拉伸高度(级联陷阱)。(步骤 3
      // 第九批迁自 visual-audit.js 的 abspos_dual_anchor producer + validate.py 同名消费段)。
      // 几何逐字搬 producer —— MUTATION TEST:
      //   candidates = slide 内 position:absolute、无 data-allow-dual-anchor、非 LAYOUT_CONTAINER;
      //   每 cand:h1=bbox 高(<4 跳);临时 style.bottom='auto' 再量 h2、还原;
      //   delta=h1-h2;delta<30 跳;h1<h2*2 跳;命中 → push(cs.top/bottom 是 used px 值)。
      //   ⚠️ getComputedStyle 对定位元素返回 USED(px)值,无法静态预筛 top/bottom==='auto' →
      //   必须对每个非 layout candidate 做 mutation 测试(producer 注释)。
      // 严重度(逐字搬 validate.py):always err。文案逐字保留。截断 [:20]。
      id: 'R-VIS-ABSPOS-DUAL-ANCHOR',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const findings = [];
        // F-325 lifted-downgrade: a lifted slide's full-bleed shells / axes /
        // watermarks (top+bottom both anchored to fill the parent) are the source
        // author's design, not a fresh cascade footgun; demote err→warn after
        // collecting — surfaced for review, not blocking. `data-allow-dual-anchor`
        // still skips entirely (handled in the candidate filter above).
        const lifted = slideIsLifted(slide);
        // LAYOUT_CONTAINER_CLASSES 逐字搬 producer:框架布局壳(.stage/.stack/.panel 等)合法
        // 用 top+bottom 双锚撑满父容器供子布局,by design 非 bug;bug 模式在 chrome 元素上。
        const LAYOUT_CONTAINER_CLASSES = [
          'stage', 'stack', 'toc', 'flow', 'nodes', 'grid', 'table-wrap',
          'header', 'footer', 'col-text', 'col-visual',
          'iframe-wrap', 'desktop-frame', 'phone-frame', 'phone-screen',
          'arch-stack', 'arch-hands', 'arch-hand',
          'slide-frame', 'deck', 'panel',
          'two-hand-arch', 'pipeline', 'steps',
        ];
        const isLayoutContainer = (el) => {
          const raw = el.className;
          const cls = (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || ''))
            .toString().split(/\s+/);
          return cls.some((c) => LAYOUT_CONTAINER_CLASSES.includes(c));
        };
        const candidates = [];
        slide.querySelectorAll('*').forEach((el) => {
          if (el.hasAttribute('data-allow-dual-anchor')) return;
          if (isLayoutContainer(el)) return;
          const cs = getComputedStyle(el);
          if (cs.position !== 'absolute') return;
          candidates.push(el);
        });
        candidates.forEach((el) => {
          const h1 = el.getBoundingClientRect().height;
          if (h1 < 4) return;                                  // 0×0(display:none 祖先等)跳过
          // Mutation test:用 inline style(最高优先级)中和 bottom 锚;若 CSS 声明过 bottom:<px>,
          // 去掉它会塌掉锚驱动高度;若本就 bottom:auto,mutation 是 no-op。
          const orig = el.style.bottom;
          el.style.bottom = 'auto';
          const h2 = el.getBoundingClientRect().height;
          if (orig) el.style.bottom = orig;                    // 还原
          else el.style.removeProperty('bottom');
          // Bug 签名:中和 bottom 后高度显著缩水。≥30px 缩水(滤微抖)且 h1≥2×h2(滤内容近乎
          // 填满锚高的 content-driven 容器)。
          const delta = h1 - h2;
          if (delta < 30) return;
          if (h1 < h2 * 2) return;
          const cs = getComputedStyle(el);
          const parent = el.offsetParent;
          const parentH = parent ? parent.getBoundingClientRect().height : 1080;
          const selector = shortSel(el);
          const top = cs.top;
          const bottom = cs.bottom;
          const actualH = Math.round(h1);
          const contentH = Math.round(h2);
          findings.push({
            rule: 'R-VIS-ABSPOS-DUAL-ANCHOR', severity: 'error', slide_idx,
            selector, top, bottom, actual_h: actualH, content_h: contentH,
            parent_h: Math.round(parentH),
            message:
              `slide ${slide_idx} · \`${selector}\` is `
              + `\`position: absolute\` with BOTH \`top: ${top}\` AND `
              + `\`bottom: ${bottom}\` declared — height stretched to `
              + `${actualH} px; content-sized would be ${contentH} px. `
              + 'Classic cascade footgun: an override added `top:` without '
              + 'declaring `bottom: auto`, so an inherited `bottom:` from a '
              + 'less-specific rule is still active and the element fills the '
              + 'parent vertically. Fix: in the override block, add '
              + '`bottom: auto` (or `top: auto`) to neutralize the inherited '
              + 'anchor; OR use `inset:` shorthand to redeclare all four; OR '
              + 'set `data-allow-dual-anchor` on the element if it is a real '
              + 'fill-parent overlay (rare for slide content).',
          });
        });
        if (lifted) {
          for (const f of findings) {
            if (f.severity === 'error') f.severity = 'warn';
            f.message += ' — LIFTED slide (verbatim from another deck); '
              + 'downgraded to WARNING, you choose whether to fix.';
          }
        }
        return findings;
      },
    },

    {
      // R-VIS-SLACK-FLEX · flex:1 子容器内部撑出大块空白。(步骤 3 第九批迁自 visual-audit.js
      // 的 slack_flex producer + validate.py 同名消费段)。几何逐字搬 producer:
      //   isHeroLayout 跳过;遍历 display:flex/inline-flex && flex-direction:column 容器,
      //   无 data-allow-flex-slack,bbox 高≥200;每直接 child(非 STYLE/SCRIPT、无 opt-out、
      //   可见、flex-grow≥1、bbox 高≥200);可见 grandchild(h>4)按 top 排序;
      //   contentTop=chRect.top+padTop,contentBottom=chRect.bottom-padBottom;
      //   topSlack=gc[0].top-contentTop,bottomSlack=contentBottom-gc[last].bottom;
      //   任一 ≥80 → push。无 scale(raw px 阈值 80)。
      // 严重度(逐字搬 validate.py):always warn(kind 文案按 ts/bs ≥80 三分)。文案逐字保留。截断 [:20]。
      id: 'R-VIS-SLACK-FLEX',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, isHeroLayout } = ctx;
        if (isHeroLayout) return [];
        const findings = [];
        slide.querySelectorAll('*').forEach((container) => {
          const cs = getComputedStyle(container);
          if (cs.display !== 'flex' && cs.display !== 'inline-flex') return;
          if (!cs.flexDirection.startsWith('column')) return;
          if (container.hasAttribute('data-allow-flex-slack')) return;
          const cRect = container.getBoundingClientRect();
          if (cRect.height < 200) return;
          [...container.children].forEach((child) => {
            if (child.tagName === 'STYLE' || child.tagName === 'SCRIPT') return;
            if (child.hasAttribute('data-allow-flex-slack')) return;
            const ccs = getComputedStyle(child);
            if (ccs.display === 'none' || ccs.visibility === 'hidden') return;
            const grow = parseFloat(ccs.flexGrow || '0');
            if (!(grow >= 1)) return;
            const chRect = child.getBoundingClientRect();
            if (chRect.height < 200) return;
            const gcs = [...child.children].filter((gc) => {
              if (gc.tagName === 'STYLE' || gc.tagName === 'SCRIPT') return false;
              const gccs = getComputedStyle(gc);
              if (gccs.display === 'none' || gccs.visibility === 'hidden') return false;
              const r = gc.getBoundingClientRect();
              return r.height > 4;
            });
            if (gcs.length === 0) return;
            const rects = gcs.map((gc) => gc.getBoundingClientRect())
              .sort((a, b) => a.top - b.top);
            const padTop = parseFloat(ccs.paddingTop) || 0;
            const padBottom = parseFloat(ccs.paddingBottom) || 0;
            const contentTop = chRect.top + padTop;
            const contentBottom = chRect.bottom - padBottom;
            const topSlack = rects[0].top - contentTop;
            const bottomSlack = contentBottom - rects[rects.length - 1].bottom;
            const THRESHOLD = 80;
            if (topSlack < THRESHOLD && bottomSlack < THRESHOLD) return;
            const containerSel = shortSel(container);
            const childSel = shortSel(child);
            const childHeight = Math.round(chRect.height);
            const contentHeight = Math.round(rects[rects.length - 1].bottom - rects[0].top);
            const ts = Math.round(topSlack);
            const bs = Math.round(bottomSlack);
            const justify = ccs.justifyContent;
            // validate.py kind 三分(逐字搬):ts≥80 && bs≥80 / ts≥80 / else。
            let kind;
            if (ts >= 80 && bs >= 80) kind = `容器内部居中撑空(top ${ts}px / bottom ${bs}px)`;
            else if (ts >= 80) kind = `容器内部上方撑空 ${ts}px`;
            else kind = `容器内部下方撑空 ${bs}px(最后一个子元素到容器底距离过大)`;
            findings.push({
              rule: 'R-VIS-SLACK-FLEX', severity: 'warn', slide_idx,
              container_sel: containerSel, child_sel: childSel, flex_grow: grow,
              child_height: childHeight, content_height: contentHeight,
              top_slack: ts, bottom_slack: bs, justify,
              message:
                `slide ${slide_idx} · \`${childSel}\` `
                + `(flex-grow ${grow}, 高 ${childHeight}px, `
                + `内容 ${contentHeight}px, justify-content: `
                + `${justify}) — ${kind}。父 \`${containerSel}\`。`
                + '原因:`flex:1` 把剩余空间给了该子容器,但内部内容比拿到的空间小,'
                + '`justify-content` 把空白分到容器内部,视觉上跟相邻 sibling 间距'
                + '异常大。Fix 选一个: (1) 去掉子容器的 `flex: 1`(改成 content-sized '
                + '+ 父容器 `justify-content: center` 居中整组内容,这是最常见的修法);'
                + '(2) 把子容器 `justify-content` 改成 `flex-start` / `flex-end` 让'
                + '内容靠一端;(3) 内容确实太少 → 加 supporting 元素填重心;(4) '
                + '确实是设计意图(故意让 hero 元素被推到某一端)→ 在子容器或父容器加 '
                + '`data-allow-flex-slack` 跳过审计。',
            });
          });
        });
        return findings;
      },
    },

    {
      // R-FOCAL-CHECK · 视觉焦点是否清晰。(步骤 3 第九批迁自 visual-audit.js 的 focal producer
      // + validate.py 的 focal 消费段)。几何逐字搬 producer:
      //   isHeroLayout / FOCAL_PARALLEL_LAYOUTS(agenda/logo-wall/arch-stack/table/timeline/
      //   process/stats/iframe-embed/replica) / data-allow-no-focal 跳过;
      //   focalCands = own-text、非 STYLE/SCRIPT/SVG-text、非 FOCAL_CHROME_CLASSES、非 mock 内、
      //   computed fontSize ≥20px;≥3 候选时取 maxPx、atMax=同 maxPx;atMax≥3 时:若 atMax 全部
      //   共享某 PARALLEL_PATTERN_CONTAINERS 祖先 → 平行模式放行;否则若有任一 declared
      //   (.is-hero/.focal/.hero-anchor/data-focal)→ 放行;else push。
      // 严重度(逐字搬 validate.py):always warn。文案逐字保留。截断 [:20]。
      id: 'R-FOCAL-CHECK',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, layout, isHeroLayout } = ctx;
        const FOCAL_PARALLEL_LAYOUTS = new Set([
          'agenda', 'logo-wall', 'arch-stack', 'table', 'timeline', 'process',
          'stats', 'iframe-embed', 'replica',
        ]);
        if (isHeroLayout || FOCAL_PARALLEL_LAYOUTS.has(layout)
            || slide.hasAttribute('data-allow-no-focal')) return [];
        const FOCAL_CHROME_CLASSES = ['wordmark', 'pageno', 'source-footer',
          'footnote', 'source', 'attrib', 'copyright', 'demo-tag',
          'deck-progress', 'deck-controls', 'eyebrow', 'caption',
          'iframe-hint'];
        const focalCands = [];
        slide.querySelectorAll('*').forEach((el) => {
          if (!hasOwnText(el)) return;
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return;
          if (el.ownerSVGElement || el.tagName === 'TEXT' || el.tagName === 'tspan') return;
          if (visHasAnyClass(el, FOCAL_CHROME_CLASSES)) return;
          let inMock = false;
          for (let n = el; n && n !== slide; n = n.parentElement) {
            if (visHasAnyClass(n, VIS_TIER_MOCK)) { inMock = true; break; }
          }
          if (inMock) return;
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return;  // 跳隐藏(spec §2A)
          const px = Math.round(parseFloat(cs.fontSize));
          if (!px || px < 20) return;                          // <20px 一般是 chrome / 注释
          focalCands.push({ el, px });
        });
        if (focalCands.length < 3) return [];
        const maxPx = Math.max(...focalCands.map((c) => c.px));
        const atMax = focalCands.filter((c) => c.px === maxPx);
        if (atMax.length < 3) return [];                       // 1 独享 = 清晰 / 2 共享 = title+body hero 允许
        const PARALLEL_PATTERN_CONTAINERS = new Set([
          'overview-grid', 'north-star-map', 'scene-grid', 'logo-wall',
          'verdict-grid', 'principle-band', 'kpi-strip', 'arch-stack',
          'arch-hands', 'pipeline', 'steps', 'pills', 'toc',
          'agenda-stack', 'iron-corners', 'two-hand-arch',
        ]);
        const ancestorClassSets = atMax.map((c) => {
          const set = new Set();
          for (let n = c.el.parentElement; n && n !== slide; n = n.parentElement) {
            const raw = n.className;
            const cls = (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || ''))
              .toString().toLowerCase().split(/\s+/);
            cls.forEach((x) => { if (x) set.add(x); });
          }
          return set;
        });
        const commonAncestors = [...ancestorClassSets[0]].filter(
          (c) => ancestorClassSets.every((s) => s.has(c)));
        const inParallelPattern = commonAncestors.some(
          (c) => PARALLEL_PATTERN_CONTAINERS.has(c));
        if (inParallelPattern) return [];                      // 显式平行模式,平等大小是设计
        const declared = atMax.filter((c) =>
          visHasAnyClass(c.el, ['is-hero', 'focal', 'hero-anchor'])
          || (c.el.dataset && c.el.dataset.focal != null));
        if (declared.length > 0) return [];                    // 作者已声明 hero,放行
        const topSizePx = maxPx;
        const tiedCount = atMax.length;
        const examples = atMax.slice(0, 4).map((c) => shortSel(c.el));
        const ex3 = examples.slice(0, 3).map((s) => '`' + s + '`').join(', ');
        return [{
          rule: 'R-FOCAL-CHECK', severity: 'warn', slide_idx,
          layout, top_size_px: topSizePx, tied_count: tiedCount, examples,
          message:
            `slide ${slide_idx} (layout \`${layout}\`) · `
            + `${tiedCount} 个元素共享最大字号 ${topSizePx}px `
            + `(e.g. ${ex3}…)`
            + `${tiedCount > 3 ? '…' : ''},视觉焦点模糊 — `
            + '观众第一眼不知道该看哪个。Fix 选一个: (1) 把 N-1 个降一级'
            + '(48→28 或 28→24,按 Card density 规则:≤4 卡 = 48,5-6 卡 = 28,'
            + '≥7 卡 = 28);(2) 给真正的 hero 元素加 `class="is-hero"` 或 '
            + '`data-focal`(明示该元素是焦点,审计放行);(3) 用 brand color / '
            + 'border / 不同 padding 把 hero 元素从平行结构里抽出来;(4) 这页确实'
            + '是 overview / 平权矩阵(N 项等大就是设计本身)→ 在 .slide 加 '
            + '`data-allow-no-focal` 跳过审计。',
        }];
      },
    },

    {
      // R-VIS-PEER-SIZE · 同角色并列 sibling 字号不一致。(步骤 3 第九批迁自 visual-audit.js
      // 的 peer_size producer + validate.py 同名消费段)。几何逐字搬 producer:
      //   isHeroLayout 跳过;ROLE_KEYS = BODY_KEYS ++ META_KEYS;roleOf(el):先命中已知语义
      //   keyword,否则用 EXACT class 签名(排序后 class tokens),否则 null(无 class);
      //   parallelAnchor(el):先找 PEER_PARALLEL/GRID_KEYS/CARD_KEYS/CARD_SUFFIX 祖先,否则最近
      //   flex/grid 容器,否则 null;own-text、非 SVG-text/STYLE/SCRIPT、有 role、非 mock、无
      //   data-allow-peer-size、有 anchor、可见、fontSize≥8px → 按 (anchorId+role) 分组;
      //   每组 ≥2 且 maxPx-minPx>1:majority=出现最多(并列取大)的 px,offenders=|px-majority|>1。
      // ⚠️ lifted PRESERVE-EXACTLY:peer_size producer 确实写 `lifted`(offenders.some closest
      //   [data-lifted]),但 validate.py 消费段【从不读 entry['lifted']】(恒 iss.warn,无 lifted
      //   分支)→ 实际 severity 恒 warn。本规则同保留 lifted payload(逐字)、severity 恒 warn。
      // 严重度(逐字搬 validate.py):always warn。文案逐字保留。截断 [:20]。
      id: 'R-VIS-PEER-SIZE',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, isHeroLayout } = ctx;
        if (isHeroLayout) return [];
        const findings = [];
        const PEER_PARALLEL = new Set([
          'overview-grid', 'north-star-map', 'scene-grid', 'logo-wall',
          'verdict-grid', 'principle-band', 'kpi-strip', 'arch-stack',
          'arch-hands', 'pipeline', 'steps', 'pills', 'toc',
          'agenda-stack', 'todo-grid', 'dir-grid',
        ]);
        const ROLE_KEYS = [...VIS_BODY_KEYS, ...VIS_META_KEYS];
        const _cls = (el) => {
          const raw = el.className;
          return (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || ''))
            .toString().toLowerCase();
        };
        const roleOf = (el) => {
          const c = _cls(el);
          for (const k of ROLE_KEYS) if (c.includes(k)) return k;
          const sig = c.trim().split(/\s+/).filter(Boolean).sort().join('.');
          return sig || null;
        };
        const parallelAnchor = (el) => {
          for (let n = el.parentElement; n && n !== slide; n = n.parentElement) {
            const toks = _cls(n).split(/\s+/).filter(Boolean);
            if (toks.some((t) => PEER_PARALLEL.has(t) || VIS_GRID_KEYS.includes(t)
              || VIS_CARD_KEYS.includes(t))) return n;
            if (VIS_CARD_SUFFIXES.some((suf) => toks.some((t) => t.endsWith(suf)))) return n;
          }
          for (let n = el.parentElement; n && n !== slide; n = n.parentElement) {
            const d = getComputedStyle(n).display;
            if (d === 'flex' || d === 'inline-flex' || d === 'grid' || d === 'inline-grid') return n;
          }
          return null;
        };
        const peerOptOut = (el) => {
          for (let n = el; n && n !== slide; n = n.parentElement)
            if (n.hasAttribute && n.hasAttribute('data-allow-peer-size')) return true;
          return false;
        };
        const groups = new Map();
        const anchorIds = new WeakMap();
        let aSeq = 0;
        slide.querySelectorAll('*').forEach((el) => {
          if (!hasOwnText(el)) return;
          if (el.ownerSVGElement || el.tagName === 'TEXT' || el.tagName === 'tspan') return;
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return;
          const role = roleOf(el); if (!role) return;
          let inMock = false;
          for (let n = el; n && n !== slide; n = n.parentElement) {
            if (visHasAnyClass(n, VIS_TIER_MOCK)) { inMock = true; break; }
          }
          if (inMock || peerOptOut(el)) return;
          const anchor = parallelAnchor(el); if (!anchor) return;
          const cs = getComputedStyle(el);
          if (cs.visibility === 'hidden' || cs.display === 'none') return;
          const px = Math.round(parseFloat(cs.fontSize)); if (!px || px < 8) return;
          if (!anchorIds.has(anchor)) anchorIds.set(anchor, ++aSeq);
          const key = anchorIds.get(anchor) + ' ' + role;
          if (!groups.has(key)) groups.set(key, { anchor, role, items: [] });
          groups.get(key).items.push({ el, px });
        });
        for (const { anchor, role, items } of groups.values()) {
          if (items.length < 2) continue;
          const sizes = items.map((i) => i.px);
          const minPx = Math.min(...sizes), maxPx = Math.max(...sizes);
          if (maxPx - minPx <= 1) continue;
          const tally = {};
          sizes.forEach((s) => { tally[s] = (tally[s] || 0) + 1; });
          const majorityPx = +Object.keys(tally).sort(
            (a, b) => tally[b] - tally[a] || (+b) - (+a))[0];
          const offenders = items.filter((i) => Math.abs(i.px - majorityPx) > 1);
          if (!offenders.length) continue;
          const containerSel = shortSel(anchor);
          const sizesSorted = [...new Set(sizes)].sort((a, b) => a - b);
          const offendersOut = offenders.slice(0, 4).map(
            (o) => ({ sel: shortSel(o.el), px: o.px }));
          const lifted = offenders.some((o) => !!o.el.closest('[data-lifted]'));
          const offStr = offendersOut.slice(0, 3).map(
            (o) => '`' + o.sel + '`=' + o.px + 'px').join(', ');
          findings.push({
            rule: 'R-VIS-PEER-SIZE', severity: 'warn', slide_idx,
            container_sel: containerSel, role, majority_px: majorityPx,
            sizes: sizesSorted, count: items.length, offenders: offendersOut, lifted,
            message:
              `slide ${slide_idx} · \`${containerSel}\` 内同角色 `
              + `\`${role}\` 字号不一致:多数 ${majorityPx}px,`
              + `但 ${offStr} 偏离(本组出现 ${JSON.stringify(sizesSorted)} 多种尺寸)。`
              + '同一并列容器里同角色的 sibling 应等大 —— "有大有小"靠这条抓。'
              + 'Fix:把偏离者统一到多数派字号(按角色给一档);若确为有意不同 → '
              + '元素或祖先加 `data-allow-peer-size`。',
          });
        }
        return findings;
      },
    },

    // R-VIS-ALIGN: removed 2026-06-10 — was an unimplemented stub; alignment audit deferred.
    //   (F-282a) The migrated rule's evaluate() always returned [] (no consumer in the old
    //   validate.py), so it was a registered code that audited nothing — a "rule list ≠ real
    //   coverage" gap. Per the audit's name-free-coverage contract we delete the stub rather
    //   than carry a permanently-silent entry. A real alignment audit is intentionally NOT
    //   shipped here: same-container left-edge clustering is highly subjective and false-positive
    //   prone (intentional staggered layouts read as misaligned), and this skill's stance is
    //   "rather under-report than false-positive". The verbatim grid-equal-height geometry the
    //   old stub preserved lives in git history (commit 8a54484 and earlier) if a future,
    //   calibrated R-VIS-ALIGN is ever built.

    {
      // R-LIFT-CSS-BUDGET · 单张 lifted 页携带的 CSS 字节膨胀护栏 (F-281a)。lift 一张外来
      // raw 页时,它的 custom_css(渲染成 .slide 首子 `<style data-fs-custom-css>`)+ 原始
      // markup 里内嵌的 <style> 会把【源 deck 整页/整站】的 CSS 整团搬进来 —— 多数是死规则
      // (本页用不到的选择器、@keyframes、reset)。攒多了拖慢渲染、污染 round-trip、把 deck.json
      // 撑大。这条只对带 data-lifted 的 slide 统计其【后代全部 <style>】的 UTF-8 字节(custom_css
      // 注入块 + 页内嵌样式都在 .slide 子树内),> 24KB → warn,> 64KB → error。
      // name-free(锚 data-lifted 来源标记,非类名);非 lifted 页(干净/作者 deck,custom_css
      // 通常为 0)天然零触发 —— 故 examples 全静默(实测 lifted=0 / custom_css=0)。
      // 文案指向 clean-lifted-css.py(剔死 CSS)/手动裁剪用不到的规则。
      id: 'R-LIFT-CSS-BUDGET',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (!slideIsLifted(slide)) return [];   // 仅 lifted 页;authored deck 天然豁免
        const WARN_BYTES = 24 * 1024;
        const ERR_BYTES = 64 * 1024;
        // 这张 lifted slide 子树里的全部 <style>(= 注入的 custom_css 块 + 原始 markup 内嵌样式)。
        const styleEls = slide.querySelectorAll('style');
        if (!styleEls.length) return [];
        let bytes = 0;
        // UTF-8 字节(CSS 注释/content 里可能有 CJK,按字符数会低估)。无 TextEncoder 时退回
        // 按 code unit 计数的保守上界(不影响阈值判定方向)。
        const enc = (typeof TextEncoder !== 'undefined') ? new TextEncoder() : null;
        for (const s of styleEls) {
          const txt = s.textContent || '';
          bytes += enc ? enc.encode(txt).length : txt.length;
        }
        if (bytes <= WARN_BYTES) return [];
        const kb = (bytes / 1024).toFixed(1);
        const severity = bytes > ERR_BYTES ? 'error' : 'warn';
        const sel = shortSel(slide);
        const cap = severity === 'error' ? '64KB' : '24KB';
        return [{
          rule: 'R-LIFT-CSS-BUDGET', severity, slide_idx,
          slide_sel: sel, css_bytes: bytes,
          message:
            `slide ${slide_idx} · LIFTED slide \`${sel}\` carries ${kb}KB of CSS `
            + `(custom_css + embedded <style>), over the ${cap} budget. Lifting a `
            + 'raw page usually drags in the SOURCE deck\'s whole stylesheet — most '
            + 'of those rules / @keyframes are dead on this page. Run '
            + '`clean-lifted-css.py` to strip the unused CSS (or manually trim the '
            + 'rules this slide never matches) so the lifted page only keeps the CSS '
            + 'it actually uses — smaller deck.json, faster render, cleaner '
            + (severity === 'error' ? 'round-trip.' : 'round-trip. (advisory)'),
        }];
      },
    },

    {
      // R-CSS-INLINE-BUDGET · 页 CSS 落位收敛 (F-272)。一张 raw 页的 per-page CSS 有两个家:
      //   ① slide.custom_css(正道 · 渲染成 `<style data-fs-custom-css>` 注入 .slide,随
      //      deck.json round-trip)— 这是单一真源;
      //   ② raw `data.html` 顶层内嵌的 `<style>`(实测 68% 走这条)— 不随 deck.json round-trip
      //      的字段走、膨胀无预算(huatai 1.5MB)、且可含跨页 selector 泄漏。
      // 这条只统计 raw 页【内嵌 <style>】(= 渲染后 .slide 子树里 NOT data-fs-custom-css 的
      // <style>)的 UTF-8 字节,> 8KB → warn,提示跑 migrate-head-css-to-custom-css.py 把内嵌
      // 块迁进 custom_css(钉死单一家)。
      // name-free:锚 `<style>` 标签 + data-fs-custom-css 标记(渲染器注入的标记,非 deck 内容
      // 类名),不依赖任何业务类名。注入的 custom_css 块本就在正道里 → 不计;干净/作者 deck 的
      // raw 页 custom_css 通常已是唯一家、无独立内嵌 <style> → 天然零触发(examples 实测 raw=0
      // / 内嵌 <style>=0 → 全静默)。advisory · 永不 block。
      id: 'R-CSS-INLINE-BUDGET',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const WARN_BYTES = 8 * 1024;
        // 内嵌 <style> = slide 子树里 NOT data-fs-custom-css 的 <style>(custom_css 注入块
        // 带该标记,已在正道里,不算泄漏家;只有 raw data.html 自带的内嵌块才计)。
        const embedded = [...slide.querySelectorAll('style')]
          .filter((s) => !s.hasAttribute('data-fs-custom-css'));
        if (!embedded.length) return [];
        const enc = (typeof TextEncoder !== 'undefined') ? new TextEncoder() : null;
        let bytes = 0;
        for (const s of embedded) {
          const txt = s.textContent || '';
          bytes += enc ? enc.encode(txt).length : txt.length;
        }
        if (bytes <= WARN_BYTES) return [];
        const kb = (bytes / 1024).toFixed(1);
        const sel = shortSel(slide);
        return [{
          rule: 'R-CSS-INLINE-BUDGET', severity: 'warn', slide_idx,
          slide_sel: sel, css_bytes: bytes,
          message:
            `slide ${slide_idx} · \`${sel}\` keeps ${kb}KB of CSS in an INLINE `
            + '<style> inside its raw `data.html`, over the 8KB budget. Per-page CSS '
            + 'has two homes — `slide.custom_css` (round-trips with deck.json, the '
            + 'single source of truth) vs an embedded <style> in data.html (does NOT '
            + 'round-trip the field, has no budget, and can leak cross-page '
            + 'selectors). Converge on ONE home: run '
            + '`migrate-head-css-to-custom-css.py <out>/index.html <out>/deck.json` '
            + '(it now also sweeps raw-page inline <style> into the slide\'s '
            + 'custom_css, scoped to its key), then re-render. (advisory · never blocks)',
        }];
      },
    },

    {
      // R-CSS-CROSS-PAGE · 跨页 selector 泄漏 (F-272)。一张页的 <style>(内嵌 OR 注入的
      // custom_css 块)里出现【非本页 slide-key】的 selector(`[data-slide-key="OTHER"]` /
      // `.slide[data-slide-key="OTHER"]`)→ 这条规则其实在样式【别的页】。后果:删本页 / lift
      // 本页会把那条针对别页的规则一起带走 → 静默破坏别页(huatai 内嵌规则引用别页 slide-key
      // 即此类)。per-page CSS 必须只 scope 到本页 key。
      // name-free:锚 data-slide-key 属性(框架 round-trip 锚点,非业务类名)+ <style> 标签;
      // 不依赖任何 deck 内容类名。本页 key 之外的 data-slide-key 引用即报,本页自己的引用不报。
      // 干净 deck 的 custom_css 经渲染器 scope_selectors 一律 scope 到本页 key、内嵌 <style>=0
      // → 天然零触发(examples 实测无跨页泄漏 → 全静默)。advisory · 永不 block。
      id: 'R-CSS-CROSS-PAGE',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const ownKey = slide.getAttribute('data-slide-key') || '';
        const styleEls = slide.querySelectorAll('style');
        if (!styleEls.length) return [];
        const REF_RE = /\[data-slide-key=(?:"([^"]*)"|'([^']*)'|([\w-]+))\]/g;
        const foreign = new Set();
        for (const s of styleEls) {
          // data-source="framework" 框架样式表理论上不会出现在 .slide 子树里(框架 CSS
          // 在 head),但保险起见跳过任何带该标记的块。
          if (s.getAttribute('data-source') === 'framework') continue;
          const txt = s.textContent || '';
          let m;
          REF_RE.lastIndex = 0;
          while ((m = REF_RE.exec(txt)) !== null) {
            const k = m[1] || m[2] || m[3] || '';
            if (k && k !== ownKey) foreign.add(k);
          }
        }
        if (!foreign.size) return [];
        const sel = shortSel(slide);
        const keys = [...foreign].slice(0, 6);
        return [{
          rule: 'R-CSS-CROSS-PAGE', severity: 'warn', slide_idx,
          slide_sel: sel, slide_key: ownKey, foreign_keys: keys,
          message:
            `slide ${slide_idx} · \`${sel}\` (data-slide-key="${ownKey}") has a `
            + `<style> rule scoped to ANOTHER page: data-slide-key ${JSON.stringify(keys)}`
            + `${foreign.size > keys.length ? ` (+${foreign.size - keys.length} more)` : ''}. `
            + 'Per-page CSS that lives on this page but styles a DIFFERENT slide is a '
            + 'cross-page leak: deleting or lifting THIS page silently drops that '
            + 'rule, breaking the OTHER page. Move each foreign-keyed rule into the '
            + 'slide it actually styles (its own `custom_css`), so every page\'s CSS '
            + 'is scoped to its OWN key and travels with it. (advisory · never blocks)',
        }];
      },
    },

    {
      // R-VIS-LABEL-FLOOR · content-tier(≥28px)卡内 <24px 非 chrome 标签。(步骤 3 第十批
      // 迁自 visual-audit.js 的 label_floor producer + validate.py 的 label_floor 消费段)。
      // 几何逐字搬 producer(嵌在 card 循环里,与 R-VIS-HIER 同遍历):
      //   cards = slide 内命中 VIS_CARD_KEYS 或 -card/-tile/-cell/-panel/-box 后缀的元素;
      //   seenCards WeakSet 去重;allTextEls = card 后代里 hasOwnText 者;
      //   sizes = allTextEls computed px;hasContentAnchor = 任一 ≥28;
      //   PAGE_CHROME_ANCESTORS = [header,footer,source-footer,pageno,wordmark,deck-progress,
      //     deck-controls];hasContentAnchor 时:每个 allTextEl px≥24 跳;CHROME_WHITELIST 命中
      //     且祖先(到 card 为止)含 PAGE_CHROME_ANCESTORS → 豁免;否则 push;(sel,px) 一页一报。
      // 严重度(逐字搬 validate.py):lifted → warn(+前缀),else → err。文案逐字保留。截断 [:20]。
      id: 'R-VIS-LABEL-FLOOR',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const findings = [];
        const cards = slide.querySelectorAll('*');
        const seenCards = new WeakSet();
        const seenLabelFloor = new Set();
        const PAGE_CHROME_ANCESTORS = ['header', 'footer', 'source-footer',
          'pageno', 'wordmark', 'deck-progress', 'deck-controls'];
        cards.forEach((card) => {
          if (!visHasAnyClass(card, VIS_CARD_KEYS) && !visHasCardSuffix(card)) return;
          if (seenCards.has(card)) return;
          seenCards.add(card);
          const allTextEls = [...card.querySelectorAll('*')].filter((e) => {
            if (!hasOwnText(e)) return false;
            const cs = getComputedStyle(e);  // 跳隐藏(spec §2A):隐藏文本不参与卡内层级/字号下限
            return cs.display !== 'none' && cs.visibility !== 'hidden' && +cs.opacity !== 0;
          });
          const sizes = allTextEls.map(
            (e) => Math.round(parseFloat(getComputedStyle(e).fontSize)));
          const hasContentAnchor = sizes.some((s) => s >= 28);
          if (!hasContentAnchor) return;
          allTextEls.forEach((el) => {
            const px = Math.round(parseFloat(getComputedStyle(el).fontSize));
            if (px >= 24) return;   // Body tier or above is OK
            if (visHasAnyClass(el, VIS_CHROME_WHITELIST)) {
              let pageChromeAncestor = false;
              for (let n = el.parentElement; n && n !== card; n = n.parentElement) {
                if (visHasAnyClass(n, PAGE_CHROME_ANCESTORS)) {
                  pageChromeAncestor = true; break;
                }
              }
              if (pageChromeAncestor) return;
            }
            const sel = shortSel(el);
            const key = `${slide_idx}::${sel}::${px}`;
            if (seenLabelFloor.has(key)) return;
            seenLabelFloor.add(key);
            const cardSel = shortSel(card);
            const lifted = !!(el.closest && el.closest('[data-lifted]'));
            const severity = lifted ? 'warn' : 'error';
            findings.push({
              rule: 'R-VIS-LABEL-FLOOR', severity, slide_idx,
              card_sel: cardSel, label_sel: sel, label_px: px, lifted,
              message:
                (lifted ? 'LIFTED slide (verbatim) — downgraded to WARNING, '
                  + 'you choose whether to bump. ' : '')
                + `slide ${slide_idx} · card \`${cardSel}\` `
                + 'contains content-tier text (≥28px) but label '
                + `\`${sel}\` is ${px}px — `
                + 'content-card labels MUST be ≥ 24 (Body tier). 16/18 chrome '
                + 'is reserved for true page metadata (.source / .pageno / '
                + '.footnote / .attrib / etc., reached via .header / .footer '
                + 'ancestor). See SKILL.md "Hero-context label floor". '
                + 'Promote to 24 + differentiate via font-weight or brand '
                + 'color, not by shrinking the size.',
            });
          });
        });
        return findings;
      },
    },

    {
      // R-VIS-OPT-OUT-ABUSE · 单帧 ≥6 同类 opt-out = silence 反模式。(步骤 3 第十批迁自
      // visual-audit.js 的 opt_out_abuse producer + validate.py 的 opt_out_abuse 消费段)。
      // 几何/源逐字搬 producer:OPT_OUT_THRESHOLD=5;
      //   (a) [data-allow-body-floor] DOM 计数 >5 → push(type='data-allow-body-floor',
      //       examples = 前 3 个 shortSel);
      //   (b) per-slide <style> 块里 CSS comment opt-out 计数:/* allow:typescale */ /
      //       /* allow:white-opacity */ / /* allow:body-floor */ 各 >5 → push(examples=[])。
      // 严重度(逐字搬 validate.py):always warn(iss.warn)。文案逐字保留。截断 [:20]。
      id: 'R-VIS-OPT-OUT-ABUSE',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const findings = [];
        const OPT_OUT_THRESHOLD = 5;
        const emit = (type, count, examples) => {
          const exStr = examples && examples.length
            ? ` (e.g. ${examples.join(', ')})` : '';
          findings.push({
            rule: 'R-VIS-OPT-OUT-ABUSE', severity: 'warn', slide_idx,
            type, count, threshold: OPT_OUT_THRESHOLD, examples: examples || [],
            message:
              `slide ${slide_idx} has ${count} occurrences of `
              + `\`${type}\` (threshold: ${OPT_OUT_THRESHOLD})${exStr}. `
              + 'opt-out attribute / comment is documented exception, NOT '
              + 'silence button. Batch-muting validator warnings hides real '
              + 'issues (text too small / chrome class abuse / palette drift). '
              + 'Fix: revisit each opt-out — if it is true by-design chrome / '
              + 'axis label / decorative element, KEEP it AND write a one-line '
              + 'justification comment; if it is regular body content, REMOVE '
              + 'the opt-out and bump to 24 (or use brand color, etc). '
              + 'Documented exception is 1-3 per slide, not 6+.',
          });
        };
        // (a) data-allow-body-floor attributes (DOM)
        const dafEls = slide.querySelectorAll('[data-allow-body-floor]');
        if (dafEls.length > OPT_OUT_THRESHOLD) {
          emit('data-allow-body-floor', dafEls.length,
            [...dafEls].slice(0, 3).map((e) => shortSel(e)));
        }
        // (b) CSS comment opt-outs in per-slide <style> blocks
        const styleEls = slide.querySelectorAll('style');
        let typescaleCount = 0, whiteOpacityCount = 0, bodyFloorCount = 0;
        styleEls.forEach((s) => {
          const txt = s.textContent;
          typescaleCount += (txt.match(/\/\*\s*allow:typescale[^*]*\*\//g) || []).length;
          whiteOpacityCount += (txt.match(/\/\*\s*allow:white-opacity[^*]*\*\//g) || []).length;
          bodyFloorCount += (txt.match(/\/\*\s*allow:body-floor[^*]*\*\//g) || []).length;
        });
        if (typescaleCount > OPT_OUT_THRESHOLD) emit('/* allow:typescale */', typescaleCount, []);
        if (whiteOpacityCount > OPT_OUT_THRESHOLD) emit('/* allow:white-opacity */', whiteOpacityCount, []);
        if (bodyFloorCount > OPT_OUT_THRESHOLD) emit('/* allow:body-floor */', bodyFloorCount, []);
        return findings;
      },
    },

    {
      // R-VIS-CARD-MIN-HEIGHT-SPARSE · min-height 撑空 + 没 space-between。(步骤 3 第十批
      // 迁自 visual-audit.js 的 card_min_height_sparse producer + validate.py 同名消费段)。
      // 几何逐字搬 producer:isHeroLayout 整体跳;遍历元素:.fs-card-fill 跳;
      //   [data-allow-min-height-sparse] 跳;display 非 flex/inline-flex 跳;flexDirection 非
      //   column* 跳;minH = minHeight px,<50 跳;justifyContent ∈ {space-between/evenly/around}
      //   跳;kids = 可见直接子(非 STYLE/SCRIPT、非 none/hidden、bbox 高>4),<2 跳;
      //   contentExtent = lastBottom-firstTop(bbox,含 margin/gap);usableH = elH - padTop -
      //   padBottom;slack = usableH - contentExtent,<60 跳;否则 push(各值 round)。
      // 严重度(逐字搬 validate.py):always warn(iss.warn)。文案逐字保留。截断 [:15]。
      id: 'R-VIS-CARD-MIN-HEIGHT-SPARSE',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, isHeroLayout } = ctx;
        if (isHeroLayout) return [];
        const findings = [];
        slide.querySelectorAll('*').forEach((el) => {
          if (el.classList.contains('fs-card-fill')) return;
          if (el.hasAttribute('data-allow-min-height-sparse')) return;
          const cs = getComputedStyle(el);
          if (cs.display !== 'flex' && cs.display !== 'inline-flex') return;
          if (!cs.flexDirection.startsWith('column')) return;
          const minH = parseFloat(cs.minHeight) || 0;
          if (minH < 50) return;
          const jc = cs.justifyContent;
          if (jc === 'space-between' || jc === 'space-evenly' || jc === 'space-around') return;
          const kids = [...el.children].filter((c) => {
            if (c.tagName === 'STYLE' || c.tagName === 'SCRIPT') return false;
            const ccs = getComputedStyle(c);
            if (ccs.display === 'none' || ccs.visibility === 'hidden') return false;
            return c.getBoundingClientRect().height > 4;
          });
          if (kids.length < 2) return;
          const elRect = el.getBoundingClientRect();
          const firstTop = kids[0].getBoundingClientRect().top - elRect.top;
          const lastBottom = kids[kids.length - 1].getBoundingClientRect().bottom - elRect.top;
          const contentExtent = lastBottom - firstTop;
          const padTop = parseFloat(cs.paddingTop) || 0;
          const padBottom = parseFloat(cs.paddingBottom) || 0;
          const usableH = elRect.height - padTop - padBottom;
          const slack = usableH - contentExtent;
          if (slack < 60) return;
          const sel = shortSel(el);
          const clientH = Math.round(elRect.height);
          const contentExtentR = Math.round(contentExtent);
          const usableHR = Math.round(usableH);
          const slackR = Math.round(slack);
          const kidCount = kids.length;
          const minHR = Math.round(minH);
          findings.push({
            rule: 'R-VIS-CARD-MIN-HEIGHT-SPARSE', severity: 'warn', slide_idx,
            selector: sel, client_h: clientH, content_extent: contentExtentR,
            usable_h: usableHR, slack: slackR, kid_count: kidCount,
            justify: jc, min_height: minHR,
            message:
              `slide ${slide_idx} · \`${sel}\` `
              + `(min-height ${minHR}px, 实际 ${clientH}px, `
              + `内容延展 ${contentExtentR}px (first→last bbox), `
              + `可用 ${usableHR}px (减 padding), 真 slack ${slackR}px, `
              + `${kidCount} children, justify-content: ${jc}) `
              + '— 作者设了 min-height 撑卡片体量,但内容堆顶,卡底大量空白。'
              + 'Fix: (1) 给该元素加 `class="fs-card-fill"`(框架 utility · 内部 '
              + '`justify-content: space-between !important` · {N children 跨高度均布}'
              + ');(2) 或缩小 min-height 到自然内容高度附近(slack < 30px · 让 '
              + 'flex-start 看不出来);(3) 确实是设计意图(顶部 hero + 底部留白)→ '
              + '给元素加 `data-allow-min-height-sparse` 跳过审计。'
              + '完整 pattern 见 `feishu-deck.css` 的 `.fs-card-fill` 注释。',
          });
        });
        return findings;
      },
    },

    {
      // R-VIS-HERO-FLOOR · hero 主元素字号下限。(步骤 3 第十批迁自 visual-audit.js 的
      // hero_floor producer + validate.py 的 hero_floor 消费段)。方向 = 尺寸下限(不是白名单)。
      // 几何逐字搬 producer:HERO_FLOORS / KPI_FLOOR / _heroFloorCheck 均为本规则局部(producer
      //   同样局部声明);_heroFloorCheck(specs):每 spec 取 sel 命中的可见(非 none/hidden/
      //   opacity0、bbox≥2、非 TIER_MOCK 祖先、非 [data-allow-typescale] 链)元素,取 px 最大的
      //   best,best 且 0<bestPx<floor → push(layout/role/spec/floor/rendered_px)。
      //   若 layout ∈ HERO_FLOORS:跑该 layout 的 specs;再做 raw fallback —— 若【无】任一 spec
      //   选择器命中可见元素(_classHit=false),用 slide 内最大可见 own-text 字号 vs 该 layout 的
      //   最小 floor(role='hero 主元素 (name-free)')比;最后无条件跑 KPI_FLOOR。
      // 严重度(逐字搬 validate.py):lifted → warn_soft,else → warn(_lev)。文案逐字保留。截断 [:20]。
      id: 'R-VIS-HERO-FLOOR',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, label, layout } = ctx;
        const findings = [];
        const HERO_FLOORS = {
          cover: [{ sel: 'h1.title, .title-zh, .cover-title, .cover-h1', floor: 88, role: '封面主标题', spec: 100 }],
          section: [{ sel: 'h2.title, .title-zh', floor: 72, role: '章节标题', spec: 88 },
            { sel: '.chapter-num', floor: 112, role: '章节序号', spec: 160 }],
          'big-stat': [{ sel: '.num', floor: 168, role: '大数字', spec: 240 }],
          stats: [{ sel: '.col .num', floor: 92, role: '指标数字', spec: 132 }],
          quote: [{ sel: 'blockquote, .quote-body, .bq', floor: 56, role: '引言主体', spec: 88 }],
        };
        const KPI_FLOOR = { sel: '.kpi-val, .kpi .v, .metric-value', floor: 40, role: 'KPI 值', spec: 56 };
        const emit = (role, sel, renderedPx, floorPx, specPx, lifted) => {
          const severity = lifted ? 'warn_soft' : 'warn';
          findings.push({
            rule: 'R-VIS-HERO-FLOOR', severity, slide_idx, label, layout,
            role, selector: sel, rendered_px: renderedPx,
            floor_px: floorPx, spec_px: specPx, lifted,
            message:
              `slide ${slide_idx} (layout \`${layout}\`) · `
              + `${role} \`${sel}\` 渲染 ${renderedPx}px,`
              + `低于该版式 hero 下限 ${floorPx}px(master 规格约 `
              + `${specPx}px)→ 偏小、不够大气(P11 封面 82<100)。方向是`
              + '"够不够大"不是"在不在白名单":hero 主元素该走 layout 规定尺寸。'
              + 'Fix:放大到 master 规格;若刻意做小变体 → 加 `data-allow-typescale`。',
          });
        };
        const _heroFloorCheck = (specs) => {
          for (const { sel, floor, role, spec } of specs) {
            const cands = [...slide.querySelectorAll(sel)].filter((el) => {
              const cs = getComputedStyle(el);
              if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return false;
              const r = el.getBoundingClientRect();
              if (r.width < 2 || r.height < 2) return false;
              for (let n = el; n && n !== slide; n = n.parentElement) if (visHasAnyClass(n, VIS_TIER_MOCK)) return false;
              for (let n = el; n; n = n.parentElement) if (n.dataset && n.dataset.allowTypescale != null) return false;
              return true;
            });
            if (!cands.length) continue;
            let best = null, bestPx = -1;
            for (const el of cands) {
              const px = Math.round(parseFloat(getComputedStyle(el).fontSize));
              if (px > bestPx) { bestPx = px; best = el; }
            }
            if (best && bestPx > 0 && bestPx < floor) {
              emit(role, shortSel(best), bestPx, floor, spec,
                !!best.closest('[data-lifted]'));
            }
          }
        };
        if (HERO_FLOORS[layout]) {
          _heroFloorCheck(HERO_FLOORS[layout]);
          const _specs = HERO_FLOORS[layout];
          const _classHit = _specs.some((s) => [...slide.querySelectorAll(s.sel)].some((el) => {
            const cs = getComputedStyle(el);
            if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return false;
            const r = el.getBoundingClientRect();
            return r.width >= 2 && r.height >= 2;
          }));
          if (!_classHit) {
            const _minFloor = Math.min(..._specs.map((s) => s.floor));
            let _best = null, _bestPx = -1;
            slide.querySelectorAll('*').forEach((el) => {
              if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return;
              if (!hasOwnText(el)) return;
              for (let n = el; n && n !== slide; n = n.parentElement) if (visHasAnyClass(n, VIS_TIER_MOCK)) return;
              for (let n = el; n; n = n.parentElement) if (n.dataset && n.dataset.allowTypescale != null) return;
              const cs = getComputedStyle(el);
              if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return;
              const r = el.getBoundingClientRect();
              if (r.width < 2 || r.height < 2) return;
              const px = Math.round(parseFloat(cs.fontSize));
              if (px > _bestPx) { _bestPx = px; _best = el; }
            });
            if (_best && _bestPx > 0 && _bestPx < _minFloor) {
              emit('hero 主元素 (name-free)', shortSel(_best), _bestPx, _minFloor, _minFloor,
                !!_best.closest('[data-lifted]'));
            }
          }
        }
        _heroFloorCheck([KPI_FLOOR]);
        return findings;
      },
    },

    {
      // R-VIS-SHORT-LABEL-FLOOR · 1–7 字短标签 / SVG 轴标 <18px。(步骤 3 第十批迁自
      // visual-audit.js 的 short_label_floor producer + validate.py 同名消费段)。补 BODY-FLOOR
      // 的「≥8 字」门槛漏掉的短轴标/分类标签,并专门下钻 SVG <text>/<tspan>。
      // 几何逐字搬 producer:isHeroLayout 整体跳;SHORT_FLOOR=18;_SL_CHROME / _SL_MOCK / _slClass
      //   均为本规则局部(producer 自带,避免依赖块内常量);遍历 '*, text, tspan':STYLE/SCRIPT
      //   跳;非 hasOwnText 跳;px≥18 跳;directText(直接文本)为空跳;len = max(CJK,latin)||长度;
      //   len<1 || >7 跳(8+ 归 BODY-FLOOR);自身 class 命中 _SL_CHROME 跳;祖先(非自身)命中
      //   _SL_MOCK 或 _isMediaBox、或链上 [data-allow-body-floor] → skip;否则 push;(sel,px) 一页
      //   一报。is_svg = SVG 文本判定。
      // 严重度(逐字搬 validate.py):lifted → warn_soft,else → warn(_lev);is_svg → '(SVG 轴标)'
      //   后缀。文案逐字保留。截断 [:20]。
      id: 'R-VIS-SHORT-LABEL-FLOOR',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, isHeroLayout } = ctx;
        if (isHeroLayout) return [];
        const findings = [];
        const SHORT_FLOOR = 18;
        const _SL_CHROME = /(^|[\s-])(eyebrow|kicker|pill|tag|chip|badge|source|pageno|footnote|attrib|copyright|wordmark|unit|legend)([\s-]|$)/i;
        const _SL_MOCK = /(mock|phone|screen|device|chat|im-|app-ui|pd-card|doc-frame)/i;
        const _slClass = (el) => { const r = el.className; return (r && r.baseVal !== undefined ? r.baseVal : (r || '')).toString(); };
        const seenShortLabel = new Set();
        slide.querySelectorAll('*, text, tspan').forEach((el) => {
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return;
          if (!hasOwnText(el)) return;
          const isSvgText = !!el.ownerSVGElement || el.tagName === 'text' || el.tagName === 'TEXT' || el.tagName === 'tspan';
          const _slCs = getComputedStyle(el);
          if (_slCs.display === 'none' || _slCs.visibility === 'hidden' || +_slCs.opacity === 0) return;  // 跳隐藏(spec §2A)
          const px = Math.round(parseFloat(_slCs.fontSize) || 0);
          if (!px || px >= SHORT_FLOOR) return;
          let directText = '';
          for (const n of el.childNodes) if (n.nodeType === 3) directText += n.textContent;
          directText = directText.trim();
          if (!directText) return;
          const cjk = (directText.match(/[一-鿿]/g) || []).length;
          const latin = (directText.match(/[A-Za-z0-9%]/g) || []).length;
          const len = Math.max(cjk, latin) || directText.length;
          if (len < 1 || len > 7) return;                 // 8+ 归 R-VIS-BODY-FLOOR
          if (_SL_CHROME.test(_slClass(el))) return;
          if (visIsStaticChrome(el) || visIsUiMock(el)) return;   // 静态词表对齐 + .ui-* 自身即 mockup primitive
          let skip = false;
          for (let n = el; n && n !== slide; n = n.parentElement) {
            if (n !== el && (_SL_MOCK.test(_slClass(n)) || visIsMediaBox(n) || visIsUiMock(n))) { skip = true; break; }
            if (n.dataset && n.dataset.allowBodyFloor != null) { skip = true; break; }
          }
          if (skip) return;
          const sel = shortSel(el);
          const key = slide_idx + '::' + sel + '::' + px;
          if (seenShortLabel.has(key)) return;
          seenShortLabel.add(key);
          const text = directText.length > 16 ? directText.slice(0, 16) + '…' : directText;
          const lifted = !!(el.closest && el.closest('[data-lifted]'));
          const severity = lifted ? 'warn_soft' : 'warn';
          const svgNote = isSvgText ? ' (SVG 轴标)' : '';
          findings.push({
            rule: 'R-VIS-SHORT-LABEL-FLOOR', severity, slide_idx,
            selector: sel, rendered_px: px, char_count: len, is_svg: isSvgText,
            text, lifted,
            message:
              `slide ${slide_idx} · \`${sel}\`${svgNote} 短标签 `
              + `"${text}"(${len} 字)渲染 ${px}px `
              + '< 18px,投影看不清。R-VIS-BODY-FLOOR 的「≥8 字」门槛放过了这种短轴标/'
              + '分类标签,这条专补(含 SVG 轴标)。Fix:放大到 ≥18(图表轴标)/24(正文);'
              + '若确为单位/装饰 → 元素加 `data-allow-body-floor`。',
          });
        });
        return findings;
      },
    },

    {
      // R-VIS-SVG-TEXT-FLOOR · SVG <text>/<tspan> 的 8+ 字实词在【实效渲染】<18px → warn。
      // 缝隙修补(2026-06-12,FWD essence-one-page 现场漏检复盘):R-VIS-BODY-FLOOR 显式
      // skip SVG 文本,R-VIS-SHORT-LABEL-FLOOR 只收 1-7 字 —— 8+ 字的 SVG 文字(以 SVG 为
      // 主内容的架构图/流程图页)恰好掉在两条规则之间:字号闸门全绿,投影上却只有 13-15px。
      // 实效像素 = computed font-size(SVG user units)× viewBox→屏幕缩放(getScreenCTM)
      //   ÷ 页面缩放(ctx.scale)—— 观众看到的是缩放后的字,不是 font-size 属性本身。
      // 豁免与既有地板同口径:chrome 词表 / 静态 chrome / [data-allow-body-floor] 链 /
      //   hero 版式;≤7 字短轴标仍归 R-VIS-SHORT-LABEL-FLOOR。warn 级:SVG 图内排版自由度
      //   大,不阻断交付,但必须被看见。
      id: 'R-VIS-SVG-TEXT-FLOOR',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, isHeroLayout, scale } = ctx;
        if (isHeroLayout) return [];
        const findings = [];
        const SVG_FLOOR = 18;
        const _CHROME = /(^|[\s-])(eyebrow|kicker|pill|tag|chip|badge|source|pageno|footnote|attrib|copyright|wordmark|unit|legend|axis|tick)([\s-]|$)/i;
        const _cls = (el) => { const r = el.className; return (r && r.baseVal !== undefined ? r.baseVal : (r || '')).toString(); };
        const seen = new Set();
        slide.querySelectorAll('text, tspan').forEach((el) => {
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return;
          let directText = '';
          for (const n of el.childNodes) if (n.nodeType === 3) directText += n.textContent;
          directText = directText.trim();
          if (!directText) return;
          const cjk = (directText.match(/[一-鿿]/g) || []).length;
          const latin = (directText.match(/[A-Za-z0-9%]/g) || []).length;
          const len = Math.max(cjk, latin) || directText.length;
          if (len < 8) return;                            // 1-7 字归 R-VIS-SHORT-LABEL-FLOOR
          const attrPx = parseFloat(cs.fontSize) || 0;
          if (!attrPx) return;
          let ctmScale = 1;
          try {
            const m = el.getScreenCTM && el.getScreenCTM();
            if (m) ctmScale = Math.hypot(m.a, m.b);
          } catch (e) { /* detached — fall back to attr px */ }
          const effPx = Math.round(attrPx * (ctmScale || 1) / (scale || 1));
          if (!effPx || effPx >= SVG_FLOOR) return;
          if (_CHROME.test(_cls(el))) return;
          if (visIsStaticChrome(el)) return;
          let allowOut = false;
          for (let n = el; n && n !== slide; n = n.parentElement) {
            if (n.dataset && n.dataset.allowBodyFloor != null) { allowOut = true; break; }
          }
          if (allowOut) return;
          const sel = shortSel(el);
          const key = slide_idx + '::' + sel + '::' + effPx;
          if (seen.has(key)) return;
          seen.add(key);
          const text = directText.length > 24 ? directText.slice(0, 24) + '…' : directText;
          const lifted = !!(el.closest && el.closest('[data-lifted]'));
          findings.push({
            rule: 'R-VIS-SVG-TEXT-FLOOR', severity: lifted ? 'warn_soft' : 'warn', slide_idx,
            selector: sel, rendered_px: effPx, attr_px: Math.round(attrPx),
            char_count: len, text, lifted,
            message:
              `slide ${slide_idx} · SVG \`${sel}\` "${text}"(${len} 字)实效渲染 `
              + `${effPx}px(font-size 属性 ${Math.round(attrPx)} × viewBox 缩放)< 18px,`
              + '投影看不清。SVG 文本不吃 HTML 字号阶梯/正文地板闸,以 SVG 为主内容的'
              + '架构图/流程图页全靠这条看见。Fix:加大 <text> 的 font-size 属性,让实效 '
              + '≥18(图内标注)/ ≥24(页面主内容);确为装饰 → 元素或祖先加 '
              + '`data-allow-body-floor`。',
          });
        });
        return findings;
      },
    },

    {
      // R-VIS-DEAD-ANIM · 该页 CSS 声明了 animation 但选择器运行时零匹配 (F-57)。
      // (步骤 3 最终视觉批迁自 visual-audit.js 的 dead_anim producer + validate.py 的
      //  dead_anim 消费段)。堵 F-51 整类:lift / 前缀注入用正则啃选择器,把合法的
      //  `.slide-frame.is-current` 啃成非法的 `-frame.is-current`(`-frame` 是合法 CSS
      //  ident 故能解析,但没有 `<-frame>` 元素 → 永不匹配)→ 动画永不触发,被驱动元素
      //  停在初态(常 opacity:0)→ 内容永久隐身。静态 CSS 分析看不出(每条单独读都合法),
      //  只有运行时 querySelectorAll 才暴露。
      //
      // ⚠️ 隔离(逐字搬 producer 的"主循环末尾 per-slide force-toggle"):`.is-current` 是
      //  present 模式运行时挂在当前帧的类,审计时只有一帧带它 —— 其余帧的健康 scoped 选择器
      //  会"假性零匹配"。所以临时给【所有】.slide-frame 强加 is-current 让 scoped 选择器
      //  解析,扫完本页样式,finally 还原 —— toggle 包在本 evaluate 内,绝不泄漏到别的规则
      //  (它们在本帧迭代的前/后跑,但永不在 toggle 生效期间被调用)。真死的 `-frame.is-current`
      //  即便强加也仍零匹配(没有 `<-frame>` 元素),force 不会掩盖真断裂。
      //  只查本 slide 自己的 <style>(co-located custom_css + raw inline <style>),
      //  绝不碰 head 框架样式表(其 `.slide-frame.is-current .slide>*` reveal 是健康的)。
      //  与 R-VIS-DEAD-RULE 各有独立 producer:这里【只发 dead_anim,绝不碰 dead_rule】。
      //
      // 严重度(逐字搬 validate.py):always err(内容隐身是硬伤,lifted 页同样报 err)。
      // 文案逐字保留。截断 [:20]。
      id: 'R-VIS-DEAD-ANIM',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const dead = [];
        const seenDead = new Set();
        // Force .is-current on every frame so runtime-scoped selectors resolve;
        // record which ones we touched so we can restore exactly.
        const _forcedFrames = [];
        slide.ownerDocument.querySelectorAll('.slide-frame').forEach((f) => {
          if (!f.classList.contains('is-current')) { f.classList.add('is-current'); _forcedFrames.push(f); }
        });
        try {
          const _declaresAnim = (styleDecl) => {
            try {
              const name = (styleDecl.animationName || '').trim();
              if (name && name !== 'none') return true;
              const sh = (styleDecl.animation || '').trim();
              // shorthand `animation: none` / empty → not a real animation
              if (sh && !/^none(\s|$)/i.test(sh)) return true;
            } catch (e) { /* exotic decl access — ignore */ }
            return false;
          };
          // Depth/string-aware comma split — commas inside :is()/:not()/:has()/
          // [attr="a,b"] must NOT shatter a valid selector (the shards would throw
          // in querySelectorAll → false 'parse-error' on a HEALTHY animation,
          // failing the gate). Mirrors the DEAD-RULE pass's _splitSelectorList.
          const _splitSelList = (sel) => {
            const parts = []; let depth = 0, inStr = 0, buf = '';
            for (let i = 0; i < sel.length; i++) {
              const ch = sel[i];
              if (inStr) { buf += ch; if (ch === inStr && sel[i - 1] !== '\\') inStr = 0; continue; }
              if (ch === '"' || ch === "'") { inStr = ch; buf += ch; continue; }
              if (ch === '(' || ch === '[') depth++;
              else if (ch === ')' || ch === ']') depth = Math.max(0, depth - 1);
              if (ch === ',' && depth === 0) { parts.push(buf.trim()); buf = ''; continue; }
              buf += ch;
            }
            if (buf.trim()) parts.push(buf.trim());
            return parts;
          };
          const _checkSel = (selectorText) => {
            // A rule's selectorText may be a comma list; test each part — any dead
            // part is reported (one dead branch = that target never animates).
            const parts = _splitSelList(selectorText || '').filter(Boolean);
            for (const sel of parts) {
              const key = slide_idx + '::' + sel;
              if (seenDead.has(key)) continue;
              let reason = null;
              try {
                if (slide.ownerDocument.querySelectorAll(sel).length === 0) {
                  // sel matched 0 — but a ::pseudo / :state tail never matches
                  // querySelectorAll. Confirm against the structural host; only
                  // truly dead if the host element is also absent.
                  const host = hostSelForDeadCheck(sel);
                  let hostDead = false;
                  if (host) {
                    try { hostDead = slide.ownerDocument.querySelectorAll(host).length === 0; }
                    catch (e2) { hostDead = false; }
                  }
                  if (hostDead) reason = 'no-match';
                }
              } catch (e) {
                reason = 'parse-error';
              }
              if (reason) {
                seenDead.add(key);
                dead.push({ slide_idx, selector: sel, reason });
              }
            }
          };
          const _walkRules = (rules) => {
            for (const rule of rules) {
              // CSSStyleRule = 1; group rules (@media/@supports/@container) expose .cssRules.
              if (rule.type === 1 && rule.selectorText && rule.style && _declaresAnim(rule.style)) {
                _checkSel(rule.selectorText);
              } else if (rule.cssRules && rule.constructor && /Keyframes|FontFace/i.test(rule.constructor.name) === false) {
                // @media / @supports / @container etc. — recurse. @keyframes/@font-face
                // expose cssRules too but their inner rules are keyframe steps, not
                // DOM selectors, so skip them by constructor name.
                try { _walkRules(rule.cssRules); } catch (e) { /* opaque group rule */ }
              }
            }
          };
          slide.querySelectorAll('style').forEach((styleEl) => {
            let sheet = null;
            try { sheet = styleEl.sheet; } catch (e) { sheet = null; }
            if (!sheet) return;
            let rules = null;
            try { rules = sheet.cssRules; } catch (e) { rules = null; }  // cross-origin / not-yet-parsed
            if (rules) _walkRules(rules);
          });
        } finally {
          // Restore: remove only the .is-current we added.
          _forcedFrames.forEach((f) => f.classList.remove('is-current'));
        }

        const findings = [];
        for (const entry of dead.slice(0, 20)) {
          const _why = (entry.reason === 'parse-error')
            ? '选择器解析失败(伪类 :is()/:has() 等写法非法)'
            : '选择器运行时零匹配:选择器非法,或(更常见)渲染器 per-slide scoper 把合法的 '
              + '`.slide-frame.is-current` 祖先前缀错加成非法的 `-frame.is-current` —— '
              + '若你的 is-current 锚定选择器本身合法,这是渲染 scoping 的 bug,按渲染问题报,别改你的 CSS';
          findings.push({
            rule: 'R-VIS-DEAD-ANIM', severity: 'error', slide_idx,
            selector: entry.selector, reason: entry.reason,
            message:
              `slide ${slide_idx} · 该页 CSS 里 \`${entry.selector}\` 声明了 `
              + `animation,但${_why} —— 这条动画永不触发,被它驱动的元素停在动画初态`
              + '(通常是 opacity:0 / transform 偏移),内容在投影上永久隐身或永不进场/上滚。'
              + 'Fix: 把选择器修正到合法、运行时真能命中的形态(常见即把 `-frame.is-current` '
              + '还原成 `.slide-frame.is-current`,或把损坏的伪类写对);若该规则本就该删,'
              + '连 animation 声明一起删,别留死规则。(几何/DOM 判定,lift 页同样报 err —— '
              + '动画静默失效就是真缺陷。)',
          });
        }
        return findings;
      },
    },

    {
      // R-VIS-DEAD-RULE · 该页 CSS 声明了重要视觉属性但选择器运行时零匹配 (F-68 · F-57 超集)。
      // (步骤 3 最终视觉批迁自 visual-audit.js 的 dead_rule producer + validate.py 的
      //  dead_rule 消费段)。F-57(dead_anim)只覆盖 animation;同一类"规则声明在源里、运行
      //  时选择器死掉、元素静默退回浏览器默认值"的盲区还有非动画属性:冰山 `.hero-pct` 从
      //  100px 死成 16px(16 是合规档、字号闸全绿不报)、`.loop-row` 从 grid 死成 block
      //  (排版塌掉、无报警)。这条把 dead-selector 判定扩到 position:absolute|fixed /
      //  display:grid|flex / font-size≥48px / width|height≥120px 这些一旦失效就视觉塌陷的
      //  重要属性。判定逻辑同 dead_anim:运行时 querySelectorAll 零匹配或解析抛错才算死,绝不
      //  靠"选择器里有没有注释"(`.a /*c*/ .b{}` ≡ 合法的 `.a .b{}`,注释=空白后代组合子)。
      //
      // ⚠️ 隔离(逐字搬 producer 顶部那个自成一体的 bracketed pass):同 R-VIS-DEAD-ANIM,
      //  临时给所有 .slide-frame 强加 is-current 让 scoped 选择器解析,finally 还原,toggle
      //  绝不泄漏到别的规则。dead-rule 只看 querySelectorAll 命中数(与布局/可见性无关),放
      //  隔离 pass 既拿正确 scoped 解析、又不污染后续测量。只查本 slide 自己的 <style>,
      //  绝不碰 head 框架样式表。与 R-VIS-DEAD-ANIM 各有独立 producer:这里【只发 dead_rule,
      //  绝不碰 dead_anim】(否则双报死动画)。
      //
      // 严重度(逐字搬 validate.py):always err(规则静默失效是硬伤,lifted 页同样报 err)。
      // 文案逐字保留。截断 [:20]。
      id: 'R-VIS-DEAD-RULE',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const dead = [];
        const _DEAD_BIG_PX = 48;     // hero/font threshold (master sub-hero & up)
        const _DEAD_SIZE_PX = 120;   // width/height threshold — a real layout block, not a chip
        // Parse the selector list of a CSS rule, splitting on top-level commas only
        // (commas inside :is()/:not()/:has()/[attr="a,b"] must NOT split the list).
        const _splitSelectorList = (sel) => {
          const parts = []; let depth = 0, inStr = 0, buf = '';
          for (let i = 0; i < sel.length; i++) {
            const ch = sel[i];
            if (inStr) { buf += ch; if (ch === inStr && sel[i - 1] !== '\\') inStr = 0; continue; }
            if (ch === '"' || ch === "'") { inStr = ch; buf += ch; continue; }
            if (ch === '(' || ch === '[') depth++;
            else if (ch === ')' || ch === ']') depth = Math.max(0, depth - 1);
            if (ch === ',' && depth === 0) { parts.push(buf.trim()); buf = ''; continue; }
            buf += ch;
          }
          if (buf.trim()) parts.push(buf.trim());
          return parts;
        };
        // Decide which IMPORTANT visual property a CSSStyleRule declares (for F-68).
        // Returns {prop, detail} of the first hit, or null. animation handled by F-57.
        const _importantVisualProp = (style) => {
          const pos = style.getPropertyValue('position');
          if (pos === 'absolute' || pos === 'fixed') return { prop: 'position', detail: pos };
          const disp = style.getPropertyValue('display');
          if (disp === 'grid' || disp === 'inline-grid') return { prop: 'display', detail: disp };
          if (disp === 'flex' || disp === 'inline-flex') return { prop: 'display', detail: disp };
          // font-size (direct or via `font:` shorthand) ≥ _DEAD_BIG_PX (px only — em/% unresolved at parse time)
          let fs = style.getPropertyValue('font-size');
          if (!fs) { const f = style.getPropertyValue('font'); if (f) { const m = f.match(/(\d+(?:\.\d+)?)px/); if (m) fs = m[0]; } }
          if (fs) { const m = fs.match(/^(\d+(?:\.\d+)?)px$/); if (m && parseFloat(m[1]) >= _DEAD_BIG_PX) return { prop: 'font-size', detail: fs }; }
          for (const dim of ['width', 'height']) {
            const v = style.getPropertyValue(dim);
            const m = v && v.match(/^(\d+(?:\.\d+)?)px$/);
            if (m && parseFloat(m[1]) >= _DEAD_SIZE_PX) return { prop: dim, detail: v };
          }
          return null;
        };
        // Recursively walk a CSSRuleList, collecting style rules (descends into @media
        // and other grouping at-rules so nested per-slide grid/position rules count).
        const _collectStyleRules = (ruleList, acc) => {
          for (const rule of ruleList) {
            if (rule.type === 1 /* STYLE_RULE */) acc.push(rule);
            else if (rule.cssRules) _collectStyleRules(rule.cssRules, acc);  // @media / @supports / @layer
          }
        };
        // For one slide: read its OWN inline <style> elements, parse each rule, and for
        // every rule that declares an IMPORTANT non-animation visual property, test
        // whether ANY selector in the list matches at runtime. Zero match → dead_rule.
        const _auditDeadRulesOnly = (sl, sIdx) => {
          const styleEls = sl.querySelectorAll('style');
          const seen = new Set();
          styleEls.forEach((styleEl) => {
            let sheet = null;
            try { sheet = styleEl.sheet; } catch (e) { return; }
            if (!sheet) return;
            let rules; try { rules = sheet.cssRules; } catch (e) { return; }  // cross-origin guard
            const styleRules = [];
            try { _collectStyleRules(rules, styleRules); } catch (e) { return; }
            for (const rule of styleRules) {
              const selText = rule.selectorText;
              if (!selText) continue;
              const impProp = _importantVisualProp(rule.style);
              if (!impProp) continue;  // animation-only rules are F-57's job, NOT dead_rule
              // Does the selector list match anything? Treat a parse error on ANY
              // member as "dead" (an illegal selector silently kills the whole rule).
              let matchCount = 0, parseError = false;
              for (const member of _splitSelectorList(selText)) {
                if (!member) continue;
                try {
                  let n = document.querySelectorAll(member).length;
                  if (n === 0) {
                    // ::pseudo / :state member never matches querySelectorAll —
                    // count its structural host instead so a healthy pseudo-element
                    // decoration (glow/ring ::after) isn't reported dead.
                    const host = hostSelForDeadCheck(member);
                    if (host) { try { n = document.querySelectorAll(host).length; } catch (e2) { /* keep 0 */ } }
                  }
                  matchCount += n;
                }
                catch (e) { parseError = true; }
              }
              if (matchCount > 0 && !parseError) continue;  // healthy — at least one element styled
              const reason = parseError ? 'parse-error' : 'no-match';
              const key = selText + '::' + impProp.prop;
              if (seen.has(key)) continue;
              seen.add(key);
              const lifted = !!(sl.closest && sl.closest('[data-lifted]'))
                           || !!(sl.querySelector && sl.querySelector('[data-lifted]'));
              dead.push({ slide_idx: sIdx, selector: selText, reason, lifted,
                          prop: impProp.prop, value: impProp.detail });
            }
          });
        };
        // Force is-current on every frame so runtime-scoped selectors resolve; restore
        // in finally so it NEVER leaks into the other rules' measurement.
        const _forcedFrames = [];
        document.querySelectorAll('.slide-frame').forEach((f) => {
          if (!f.classList.contains('is-current')) { f.classList.add('is-current'); _forcedFrames.push(f); }
        });
        try {
          _auditDeadRulesOnly(slide, slide_idx);
        } finally {
          _forcedFrames.forEach((f) => f.classList.remove('is-current'));
        }

        const _DEAD_RULE_PROP_NOTE = {
          position: ['退回 static → 定位元素跑位 / 叠层错乱', 'position:absolute|fixed'],
          display: ['退回 block → grid/flex 排版整体塌掉(行/列变竖排)', 'display:grid|flex'],
          'font-size': ['退回浏览器默认 ~16px → hero/大字号文字缩成小字,且 16 是合规档、'
            + '字号闸(R20 / R-VIS-TIER)全绿不会报', '大字号'],
          width: ['退回 auto → 尺寸塌缩 / 布局错位', '具体宽度'],
          height: ['退回 auto → 尺寸塌缩 / 布局错位', '具体高度'],
        };
        const findings = [];
        for (const entry of dead.slice(0, 20)) {
          const _why = (entry.reason === 'parse-error')
            ? '选择器解析失败(伪类 :is()/:has() 等写法非法)'
            : '选择器运行时零匹配:选择器非法,或(更常见)渲染器 per-slide scoper 把合法的 '
              + '`.slide-frame.is-current` 祖先前缀错加成非法的 `-frame.is-current` —— '
              + '若你的 is-current 锚定选择器本身合法,这是渲染 scoping 的 bug,按渲染问题报,别改你的 CSS';
          const note = _DEAD_RULE_PROP_NOTE[entry.prop] || ['元素退回浏览器默认值', entry.prop || '?'];
          const _effect = note[0];
          const _label = note[1];
          // F-353 lifted-downgrade: a "dead" rule on a LIFTED slide (data-lifted)
          // is faithfully-recovered source CSS — often a redundant duplicate, or a
          // rule for an element the lift didn't carry over. The page's correctness
          // is verified by render + visual review, not by every recovered selector
          // matching, so firing this as a blocking err is a false alarm (it ate ~7
          // render-debug minutes on a page that rendered perfectly). Downgrade
          // error→warn on data-lifted slides (same family as the F-325 geometry
          // lifted-downgrade); AUTHORED decks keep err — a dead rule there is a
          // genuine silent defect.
          const _liftTail = entry.lifted
            ? '(几何/DOM 判定 · LIFTED slide —— 从源 deck 忠实搬运的恢复 CSS,'
              + '常是冗余副本或指向未随 lift 带入的元素;页面正确性以渲染+视觉为准,'
              + '故降 warn、不阻断。同 F-325 lifted-downgrade 族。)'
            : '(几何/DOM 判定 —— 规则静默失效就是真缺陷。)';
          findings.push({
            rule: 'R-VIS-DEAD-RULE', severity: entry.lifted ? 'warn' : 'error', slide_idx,
            selector: entry.selector, reason: entry.reason, prop: entry.prop,
            value: entry.value, lifted: entry.lifted,
            message:
              `slide ${slide_idx} · 该页 CSS 里 \`${entry.selector}\` 声明了 `
              + `\`${entry.prop}: ${entry.value || ''}\`(${_label}),但${_why} —— `
              + `这条规则永不生效,被它本该驱动的元素静默${_effect}。源里逐条读都合法、`
              + '字号/排版闸全绿,只有运行时 querySelectorAll 才暴露。'
              + 'Fix: 把选择器修正到合法、运行时真能命中的形态(常见即把 `-frame.is-current` '
              + '还原成 `.slide-frame.is-current`,或把损坏的伪类写对);若该规则本就该删,'
              + '连声明一起删,别留死规则。' + _liftTail,
          });
        }
        return findings;
      },
    },

    {
      // R-DOM · 整文档 .deck 结构不变量。(步骤 3 最终结构批迁自 _validate_audits.py
      // audit_dom_integrity)。原版用 stdlib html.parser 扫 <body> 源,逐 <div> 维护栈,
      // 查三条不变量:
      //   ① 每个 .slide-frame 必须是 .deck 的【直接子】(没被嵌进另一 frame);
      //   ② 每个 .slide-frame 内须恰好一个 .slide 直接子;
      //   ③ <body> 内 <div> 开/闭计数须平衡(剥 comment/script/style 后)。
      // opt-out:<body> 内含 `allow:dom-integrity`。
      //
      // 移植抉择(渲染基底 = 唯一基底,见 UNIFY-VALIDATE-ARCH §0/§1):①② 是结构关系,
      //   渲染后 DOM 直接、且更准地暴露(parentElement / :scope>.slide,不受 class 顺序/
      //   属性影响)→ document-level audits.js 规则,逐字保留 err 文案。
      //   ⚠️ ③(<div> 开/闭平衡)是【源字节截断】信号:浏览器会自动补全/闭合标签,渲染后
      //   DOM 的 div 永远平衡,DOM 里【做不到】忠实判定截断 —— 这条按规范归 RUNNER 层的
      //   R-DOC-INTEGRITY(run-audits.py 读 index.html 原始字节,对整文档 div 计数 + </body>
      //   /</html> 截断检查)。故本规则不含原版 invariant ③;截断仍被 R-DOC-INTEGRITY 抓到
      //   (归一条规则而非两条 —— 这是规范要求的、有意的归属差异,见迁移报告)。
      //
      // document-level:整 deck 算一次,挂本次 scope 首帧(__RDOM_DONE__ 防重复);scope 把
      //   首帧排除也照常报(isFirstInScope 取 scope 内首帧)。
      id: 'R-DOM',
      severity: 'error',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__RDOM_DONE__) return [];
        if (!ctx.isFirstInScope) return [];
        if (typeof window !== 'undefined') window.__RDOM_DONE__ = true;

        if (typeof document === 'undefined' || !document.body) return [];
        // opt-out:<body> 源含 allow:dom-integrity(与原版 `'allow:dom-integrity' in body` 等价)。
        if ((document.body.outerHTML || '').indexOf('allow:dom-integrity') >= 0) return [];

        const findings = [];
        const frames = [...document.querySelectorAll('.slide-frame')];
        const framesSeen = frames.length;
        // Invariant 1a: 每个 slide-frame 的【直接父】须是 .deck(对应原版 div_stack[-1]==deck)。
        let framesUnderDeck = 0;
        // Invariant 1b: 任一祖先也是 slide-frame → 嵌套(对应原版 frames_nested_in_frame,
        //   记录该 frame 的 1-based 出现序号,文档序与原版栈遍历序一致)。
        const framesNestedInFrame = [];
        frames.forEach((fr, i) => {
          if (elHasClass(fr.parentElement, 'deck')) framesUnderDeck += 1;
          if (ancestorHasClass(fr, 'slide-frame')) framesNestedInFrame.push(i + 1);
        });
        // Invariant 2: 每个 frame 恰好一个 .slide 直接子(对应原版 frame_inner_slide_count;
        //   原版只数"栈顶是 slide-frame 时压入的 .slide"= 直接子,这里用 :scope>.slide 等价)。
        const frameInnerSlideCount = frames.map(
          (fr) => fr.querySelectorAll(':scope > .slide').length);

        // Invariant 1: 每个 slide-frame 是 .deck 直接子。
        const orphanFrames = framesSeen - framesUnderDeck;
        if (orphanFrames) {
          findings.push({
            rule: 'R-DOM', severity: 'error', slide_idx,
            message:
              `${orphanFrames} of ${framesSeen} <div class="slide-frame"> `
              + 'are NOT a direct child of <div class="deck">. The most likely '
              + 'cause is a missing </div> earlier in the document (regex-based '
              + 'insertion / deletion ate a closing tag), nesting later frames '
              + 'inside an unclosed frame. Present mode will hide every nested '
              + 'frame because it never becomes the current slide. '
              + 'Re-inspect recent edits; do not use regex to splice slide-frames.',
          });
        }
        if (framesNestedInFrame.length) {
          const idxs = framesNestedInFrame.slice(0, 5).join(', ');
          const more = framesNestedInFrame.length <= 5 ? ''
            : ` (+${framesNestedInFrame.length - 5} more)`;
          findings.push({
            rule: 'R-DOM', severity: 'error', slide_idx,
            message:
              `slide-frame nesting: frames at positions ${idxs}${more} `
              + 'are inside ANOTHER slide-frame. This breaks present mode — '
              + 'only the outer frame becomes the current slide; the inner '
              + 'frames are perma-hidden. Fix the unclosed div above.',
          });
        }
        // Invariant 2: 每个 frame 恰好一个 .slide 直接子。
        frameInnerSlideCount.forEach((n, i0) => {
          if (n !== 1) {
            findings.push({
              rule: 'R-DOM', severity: 'error', slide_idx,
              message:
                `slide-frame #${i0 + 1} contains ${n} direct .slide children `
                + '(expected exactly 1). Either the markup template is broken '
                + 'or two slides got concatenated into one frame.',
            });
          }
        });
        return findings;
      },
    },

    {
      // R-FOREIGN-SCRIPT · 注入面最低防线 (F-287)。parser 读外部 HTML/pptx/飞书文档,
      // 素材里的指令文本原样进模型上下文(prompt 注入),而执行模型手握 render/publish/入库
      // 写权限;raw 页允许任意 markup,lift 从外来 deck 拎页会带任意 <script> 经 slide-library
      // 跨 deck 传染;发布到带飞书登录的 CF worker = XSS 进内网受众浏览器。这条不做完整安全
      // 工程,只做最低防线:检出【非框架来源】的可执行内容 —— ① 内联 / 外链 <script>(src 非
      // 框架脚本),② on* 内联事件属性(onclick/onload/onerror…)。
      //
      // 框架脚本 vs 外来脚本(豁免规则,examples 零误报的关键):
      //   · 只扫【.slide 子树】(slide.querySelectorAll) —— 框架自注入的脚本(feishu-deck.js
      //     /edit-mode/present-mode/fs-deck-notes 数据岛)永远挂在 <body> 直下、不在任何 .slide
      //     里,天然在扫描范围之外。raw 页 / 外来 deck 的 <script> 才住在 slide 的 data.html 里。
      //   · belt-and-suspenders(即便框架将来把脚本塞进 slide 附近):
      //       - data-source="framework"(渲染器 --inline / runner _inline_framework_js 给框架
      //         脚本打的标记,与 R-CSS-CROSS-PAGE / sheetIsFramework 同一约定)豁免;
      //       - 非可执行 type(application/json 数据岛 / text/plain runner 注入的源副本)豁免;
      //       - src 指向框架脚本(…/feishu-deck.js / …/deck-edit-mode.js / …/deck-present.js)豁免。
      //   · 就近祖先链带 data-allow-foreign-script → 整豁免(确属故意写脚本的 bespoke raw 页的
      //     最后逃生口,与 data-allow-* 一族一致)。
      //
      // 严重度按【来源】分级(最危险的外来脚本入库传染判 error):
      //   · lifted 页(data-lifted) / imported deck(<meta fs-deck-origin=imported>)= error
      //     —— 外来脚本经 slide-library 入库会跨 deck 传染,且 lift 从不可信外部带来;
      //   · 普通生成页 = warn —— 作者自己 raw 页写脚本是显式选择,降级提示(可 opt-out)。
      // name-free:锚 <script> 标签 / on* 属性名 / data-source / type / src 模式,不依赖任何
      // 业务类名。examples(干净 schema deck,框架脚本全在 body 级)实测零触发。
      id: 'R-FOREIGN-SCRIPT',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        // 就近祖先链 opt-out(bespoke raw 页故意写脚本)。
        for (let p = slide; p && p !== document.body && p.parentElement; p = p.parentElement) {
          if (p.hasAttribute && p.hasAttribute('data-allow-foreign-script')) return [];
        }
        // 来源分级:lifted 帧(data-lifted)或 imported deck(<meta fs-deck-origin=imported>)
        // = error(外来脚本入库会跨 deck 传染);普通生成页 = warn(作者显式选择,降级)。
        const untrusted = slideIsLifted(slide) || deckOriginImported();
        const sev = untrusted ? 'error' : 'warn';
        const origin = slideIsLifted(slide) ? 'LIFTED'
          : (deckOriginImported() ? 'IMPORTED' : 'authored');

        // 框架脚本 src 模式(渲染器 _shell.html 注入的、与 R-DOC-INTEGRITY 的 feishu-deck.js
        // needle 同源;edit/present 子脚本同目录)。命中即框架自注入,豁免。
        const FRAMEWORK_SRC_RE = /(?:^|\/)(?:feishu-deck\.js|deck-edit-mode\.js|deck-present-mode\.js|deck-present\.js)(?:[?#]|$)/i;
        const isFrameworkScript = (s) => {
          if (s.getAttribute && s.getAttribute('data-source') === 'framework') return true;
          const type = (s.getAttribute && (s.getAttribute('type') || '')).trim().toLowerCase();
          // 非可执行块不是脚本:application/json 数据岛(fs-deck-notes)、text/plain(runner
          // 注入的框架源副本)。可执行 = 空 / text|application/javascript|…/ module / mjs。
          if (type && type !== 'module'
              && !/(?:^|\/)(?:javascript|ecmascript|babel|jsx|js|mjs)$/.test(type)
              && type !== 'text/jsx' && type !== 'application/ecmascript') {
            return true;
          }
          const src = (s.getAttribute && (s.getAttribute('src') || '')).trim();
          if (src && FRAMEWORK_SRC_RE.test(src)) return true;
          return false;
        };

        const findings = [];
        const seen = new Set();   // 同一指纹一页只报一次,降噪

        // ① 非框架 <script>(.slide 子树内)。
        slide.querySelectorAll('script').forEach((s) => {
          if (isFrameworkScript(s)) return;
          const src = (s.getAttribute && (s.getAttribute('src') || '')).trim();
          const what = src
            ? `<script src="${src.slice(0, 80)}">`
            : `inline <script> (${(s.textContent || '').trim().slice(0, 40)}…)`;
          if (seen.has('s:' + what)) return;
          seen.add('s:' + what);
          findings.push({
            rule: 'R-FOREIGN-SCRIPT', severity: sev, slide_idx, origin,
            sample: what,
            message:
              `slide ${slide_idx} (${origin}): non-framework executable ${what} `
              + 'lives inside the slide. Foreign material (parsed HTML/PPTX/Lark docs, '
              + 'a lifted page from another deck) is DATA, not code — a stray '
              + '<script> here runs in every viewer (and, once ingested to '
              + 'slide-library, spreads cross-deck; once published to the '
              + 'Feishu-login CF viewer, becomes XSS inside an internal audience\'s '
              + 'browser). '
              + (untrusted
                  ? 'This page is lifted/imported from an untrusted source → ERROR: '
                    + 'strip the <script> before ingest/publish (rebuild the page as a '
                    + 'schema layout, or hand-author the markup without the script).'
                  : 'Remove it (a deck should not need page-level <script>; framework '
                    + 'JS is injected by render-deck.py). If this raw page genuinely '
                    + 'needs a script, opt out with data-allow-foreign-script — but '
                    + 'never ship a script that came from parsed/lifted material.'),
          });
        });

        // ② on* 内联事件属性(onclick / onload / onerror / onmouseover …)。整 slide 子树
        //    + slide 自身;扫属性名,name-free。框架渲染器不产出 on* 内联事件 → 干净 deck 零触发。
        const ON_ATTR_RE = /^on[a-z]+$/;
        const scan = [slide, ...slide.querySelectorAll('*')];
        for (const el of scan) {
          if (!el.attributes) continue;
          if (el.tagName === 'SCRIPT' || el.tagName === 'STYLE') continue;
          for (const attr of el.attributes) {
            const name = (attr.name || '').toLowerCase();
            if (!ON_ATTR_RE.test(name)) continue;
            const tag = (el.tagName || '').toLowerCase();
            const fp = 'on:' + tag + ':' + name;
            if (seen.has(fp)) continue;
            seen.add(fp);
            findings.push({
              rule: 'R-FOREIGN-SCRIPT', severity: sev, slide_idx, origin,
              sample: `<${tag} ${name}=…>`,
              message:
                `slide ${slide_idx} (${origin}): inline event handler `
                + `\`${name}\` on <${tag}> — an on* attribute is executable code `
                + 'in the page. Same injection surface as a <script>: foreign '
                + 'material is data, not code. '
                + (untrusted
                    ? 'Lifted/imported from an untrusted source → ERROR: remove the '
                      + 'handler before ingest/publish.'
                    : 'Remove the handler (wire behavior in framework JS instead); '
                      + 'opt out with data-allow-foreign-script only for an '
                      + 'intentionally-scripted bespoke raw page.'),
            });
          }
        }
        return findings;
      },
    },

    {
      // R-IFRAME-REMOTE · 远程 iframe = 离线/headless 哑弹 (2026-06-11)。
      // <iframe src="http(s)://…"> 指向外网:① 离线/headless 下页面 load 事件
      // 永远挂起(截图/审计工具逐张烧满超时 —— larkoffice docx 内嵌页实测 3×30s),
      // ② 现场无网/未登录时 live demo 静默变白块,讲到这页才发现。
      //
      // 判定读【原始属性】getAttribute('src'),不读 resolved 的 el.src ——
      // file:// 下相对路径会被浏览器 resolve 成 file://…,用 .src 判会把本地
      // 资源的协议前缀搅进来;原始字节才是作者写了什么的真相。只认 ^https?://
      // (协议相对 // 与 data:/相对路径都不是这条要抓的"指望现场有外网"形态)。
      //
      // 豁免:iframe 自身或就近祖先链(至 slide)带 data-allow-remote-iframe ——
      // 显式接受"现场必有网络+已登录"的前提(与 data-allow-* 一族同约定)。
      // name-free,raw + schema 同覆盖;warn(是否能接受联网依赖是人的判断)。
      id: 'R-IFRAME-REMOTE',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const findings = [];
        slide.querySelectorAll('iframe').forEach((fr) => {
          const rawSrc = (fr.getAttribute('src') || '').trim();
          if (!/^https?:\/\//i.test(rawSrc)) return;     // 本地/相对/data: 不抓
          // 显式接受:iframe 自身或祖先(至 slide 边界)带 data-allow-remote-iframe。
          for (let p = fr; p; p = p.parentElement) {
            if (p.hasAttribute && p.hasAttribute('data-allow-remote-iframe')) return;
            if (p === slide) break;
          }
          findings.push({
            rule: 'R-IFRAME-REMOTE', severity: 'warn', slide_idx,
            src: rawSrc.slice(0, 120),
            message:
              `slide ${slide_idx}: <iframe src="${rawSrc.slice(0, 80)}"> 指向远程地址 — `
              + '远程 iframe 会让页面 load 事件在离线/headless 下永远挂起'
              + '(截图/审计工具逐张烧满超时),现场无网或未登录时这块内容静默变白,'
              + 'live demo 当场失效。把内容本地化(截图静态化 / 抓取后用本地 HTML 重建),'
              + '或确认现场必有网络+已登录后,用 data-allow-remote-iframe 显式接受。',
          });
        });
        return findings;
      },
    },

    {
      // R-EMBED-OPAQUE-BG · 内嵌看板 iframe 的不透明深色内底 = 边缘黑边 (2026-06-21)
      // 一个 raw 页用 <iframe src="data:text/html;…"> 整版内嵌看板时,iframe 元素 + 外层
      // .slide 可透明、letterbox 也吃 deck content-bg —— 但 iframe 内部那份 HTML 自己的
      // html / body / .stage-host / .slide 若画了【不透明深色】底(#04070E / var(--ink) /
      // linear-gradient(#0A0F1A…)),就盖住了 deck 的近黑藏青底,在 slide / letterbox 边缘
      // 露出一圈比 deck 更黑的生硬黑边。齐鲁指挥中心 #27/#28/#29 反复踩、要人盯三次才修干净,
      // 根因正是这一层:外层修了透明、内层没修,而内层在 base64 data: URI 里,过去【没有任何
      // 校验能看见它】(其余规则一律 strip data: 以免误命中 #hex)。已验证修法 = 把内层那几个
      // 满幅包裹设 background:transparent,让 deck 底透上来。
      //
      // 判定:解码 data:text/html 的 base64 / percent 载荷,在内部 CSS 里找上述满幅选择器的
      // background,解析(含一层 var() 解引用)首个颜色 —— 不透明(alpha≥.5)且暗(相对亮度
      // <.18)才报。低 alpha 的辉光渐变 / transparent / 浅色满版(白底看板)都不报。name-free
      // (认 data: 载荷不认类名,故 embed-frame 类只 3/8 页带也不漏);warn(自带底是设计判断)。
      // 确属故意满版自带深色主题 → iframe 或祖先 .slide 加 data-allow-embed-bg 显式接受。
      id: 'R-EMBED-OPAQUE-BG',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        const findings = [];
        const COVER = ['html', 'body', '.stage-host', '.slide'];
        const isCover = (s) => {
          const t = s.trim(); const last = t.split(/\s+/).pop();
          return COVER.indexOf(t) >= 0 || COVER.indexOf(last) >= 0;
        };
        // first color token of a bg value → {lum 0..1, alpha 0..1} or null (unknown)
        const colorOf = (val) => {
          let m = val.match(/rgba?\(\s*([\d.]+)[\s,]+([\d.]+)[\s,]+([\d.]+)(?:[\s,/]+([\d.]+))?/i);
          if (m) return { lum: (0.2126 * +m[1] + 0.7152 * +m[2] + 0.0722 * +m[3]) / 255,
                          alpha: m[4] === undefined ? 1 : +m[4] };
          m = val.match(/#([0-9a-f]{6})\b/i);
          if (m) { const n = parseInt(m[1], 16);
            return { lum: (0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)) / 255, alpha: 1 }; }
          m = val.match(/#([0-9a-f]{3})\b/i);
          if (m) { const h = m[1], r = parseInt(h[0] + h[0], 16), g = parseInt(h[1] + h[1], 16), b = parseInt(h[2] + h[2], 16);
            return { lum: (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255, alpha: 1 }; }
          if (/(^|[\s,(])black([\s,)]|$)/i.test(val)) return { lum: 0, alpha: 1 };
          return null;                       // transparent / unknown / named-light → skip
        };
        slide.querySelectorAll('iframe').forEach((fr) => {
          const src = (fr.getAttribute('src') || '').trim();
          const head = src.match(/^data:text\/html([^,]*),/i);
          if (!head) return;                 // only inline-HTML data: iframes
          // opt-out: iframe or ancestor (up to slide) carries data-allow-embed-bg
          for (let p = fr; p; p = p.parentElement) {
            if (p.hasAttribute && p.hasAttribute('data-allow-embed-bg')) return;
            if (p === slide) break;
          }
          let inner;
          try {
            const payload = src.slice(head[0].length);
            inner = /;base64/i.test(head[1]) ? atob(payload) : decodeURIComponent(payload);
          } catch (e) { return; }
          // CSS lives in <style> blocks; scanning the raw inner HTML would let the
          // markup BEFORE the first rule bleed into that rule's selector (…<style>body
          // → "body" buried in a long token). Gather <style> text first, then scan.
          let css = '', sm; const sre = /<style[^>]*>([\s\S]*?)<\/style>/gi;
          while ((sm = sre.exec(inner))) css += sm[1] + '\n';
          if (!css) css = inner;             // no <style> (rare) — fall back to raw
          // one-level var() map, then scan flat CSS rule blocks for cover-selector bg
          const vars = {}; let vm; const vre = /(--[\w-]+)\s*:\s*([^;]+);/g;
          while ((vm = vre.exec(css))) vars[vm[1]] = vm[2].trim();
          const resolve = (v) => v.replace(/var\(\s*(--[\w-]+)\s*\)/g, (_, n) => vars[n] || '');
          const offenders = []; let bm; const bre = /([^{}]+)\{([^{}]*)\}/g;
          while ((bm = bre.exec(css))) {
            const sels = bm[1].split(',');
            if (!sels.some(isCover)) continue;
            let dm, bg = null; const dre = /background(?:-color)?\s*:\s*([^;}]+)/gi;
            while ((dm = dre.exec(bm[2]))) bg = dm[1].trim();   // last bg decl wins
            if (!bg) continue;
            const col = colorOf(resolve(bg));
            if (col && col.alpha >= 0.5 && col.lum < 0.18) {
              const sel = (sels.find(isCover) || sels[0]).trim();
              if (offenders.indexOf(sel) < 0) offenders.push(sel);
            }
          }
          if (offenders.length) {
            findings.push({
              rule: 'R-EMBED-OPAQUE-BG', severity: 'warn', slide_idx,
              selectors: offenders.join(' / '),
              message:
                `slide ${slide_idx}: 内嵌看板 iframe 内部的 ${offenders.join(' / ')} 画了不透明深色底 — `
                + '盖住 deck 背景,在 slide / letterbox 边缘露出比 deck 更黑的硬黑边(齐鲁指挥中心系列的根因)。'
                + '把内部 html / body / .stage-host / .slide 的 background 设为 transparent,让 deck 底透上来;'
                + '若确属故意满版自带深色主题,在 iframe(或祖先 .slide)加 data-allow-embed-bg 显式接受。',
            });
          }
        });
        return findings;
      },
    },

    // ========================================================================
    //  跨页一致性 (DECK-LEVEL consistency · F-257 cross-page half) —— 至此全部
    //  63 条规则都是【单页】判定,页与页之间零比较,所以"风格逐页漂移"完全隐形:
    //  标题基线一页一个位置、强调色每页一个近重复色号(肉眼目测调色)、
    //  allow:typescale 豁免全 deck 越攒越多(northregion 实测 161 条)。下面三条
    //  做 deck 级求值(只在 ctx.isFirstInScope 锚帧报一次,内部自己扫整 deck),
    //  全部 WARN(一致性是建议不是阻断)、name-free(几何/颜色而非类名白名单)、
    //  带 opt-out。立场:设计自由归模型,skill 只保证「结果合规」——这三条是顾问,
    //  不是设计专政,故宁可漏报不可误报(误报会训练人忽略它)。
    // ========================================================================

    {
      // R-DECK-TITLE-DRIFT · 内容页标题基线 / 字号跨页一致性。R-VIS-TITLE-POSITION
      // 逐页量「.header 距理想 61px」,但它对每一页独立判定 —— 若整 deck 的标题统一
      // 偏到 80px,每页与 61 的偏差一致、可能都在容差内或都被同样处理,却没人发现
      // 「这一页比其余页低了 35px」这种【页间】漂移。这条按 deck 自己的 MODE(众数)
      // 当基准:收集所有【非 hero】slide 的框架标题(.header .title-zh,退 .header h2)
      // computed top 与 font-size(都按 slide scale 归一化到 design px),求各自众数;
      // 某页 top 偏离众数 >8px(对齐 R-VIS-TITLE-POSITION 容差)或 font-size ≠ 众数 → 报。
      // 跳过 hero / display:none 隐藏 header / 渲染失败的页;deck 或某页带
      // data-allow-title-drift(或 CSS 注释 /* allow:title-drift */)整豁免。
      // 需 ≥2 个可量标题才有「众数」可言(单页无所谓一致性)。warn。
      id: 'R-DECK-TITLE-DRIFT',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__RDECK_TITLEDRIFT_DONE__) return [];
        if (!ctx.isFirstInScope) return [];   // deck 级:整 deck 算一次,挂本次 scope 首帧
        if (typeof window !== 'undefined') window.__RDECK_TITLEDRIFT_DONE__ = true;
        if (typeof document === 'undefined') return [];
        // opt-out:整 deck 关。任一 [data-allow-title-drift] 属性,或任一 <style>/源里
        // 的 /* allow:title-drift */ 注释(后者可写在 custom_css 里随页 round-trip)。
        if (document.querySelector('[data-allow-title-drift]')) return [];
        if (allStyleText().indexOf('allow:title-drift') >= 0) return [];

        const slides = document.querySelectorAll('.slide');
        // 与 R-VIS-TITLE-POSITION 同套 TITLE_SKIP_LAYOUTS(hero + replica)逐字一致 ——
        // 这些版式没有内容页式的标准标题基线,纳入比较会污染众数。
        const TITLE_SKIP_LAYOUTS = new Set(['cover', 'section', 'end', 'quote',
          'big-stat', 'replica', 'image-text']);
        const samples = [];   // { idx, top, fs }
        slides.forEach((sl, i) => {
          const layout = sl.getAttribute('data-layout') || '';
          if (TITLE_SKIP_LAYOUTS.has(layout)) return;
          if (HERO_LAYOUTS.has(layout)) return;
          if (sl.hasAttribute('data-allow-title-drift')) return;
          const header = sl.querySelector(':scope > .header');
          const titleEl = sl.querySelector(
            ':scope > .header > .title-zh, :scope > .header > h1.title-zh, '
            + ':scope > .header > h2.title-zh, :scope > .header h2.title-zh, '
            + ':scope > .header h1.title-zh, :scope > .header > h2');
          // display:none / 未渲染 header 跳过(getClientRects().length===0 是规范判定,
          // 与 R-VIS-TITLE-POSITION 一致 —— agenda 等隐藏 header 版式无标题可量)。
          if (!(header && titleEl && header.getClientRects().length > 0)) return;
          const sr = sl.getBoundingClientRect();
          const scale = (sr.height / 1080) || 1;
          const top = Math.round((titleEl.getBoundingClientRect().top - sr.top) / scale);
          const fs = Math.round(parseFloat(getComputedStyle(titleEl).fontSize) / scale);
          samples.push({ idx: i + 1, top, fs });
        });
        // 众数需要样本:少于 2 个可量标题 → 无「页间一致性」概念,静默。
        if (samples.length < 2) return [];

        const modeOf = (vals) => {
          const c = new Map();
          for (const v of vals) c.set(v, (c.get(v) || 0) + 1);
          let best = null, bestN = -1;
          // 平票时取「数值更小」者当基准(标准基线偏低,61 一族;稳定可复现)。
          for (const [v, n] of [...c.entries()].sort((a, b) => a[0] - b[0])) {
            if (n > bestN) { best = v; bestN = n; }
          }
          return best;
        };
        const topMode = modeOf(samples.map((s) => s.top));
        const fsMode = modeOf(samples.map((s) => s.fs));
        const TOL = 8;   // 对齐 R-VIS-TITLE-POSITION 的 8px 容差

        const findings = [];
        for (const s of samples) {
          const topOff = Math.abs(s.top - topMode) > TOL;
          const fsOff = s.fs !== fsMode;
          if (!topOff && !fsOff) continue;
          const bits = [];
          if (topOff) bits.push(`top:${s.top}px vs deck mode ${topMode}px (Δ${s.top - topMode > 0 ? '+' : ''}${s.top - topMode})`);
          if (fsOff) bits.push(`font-size:${s.fs}px vs deck mode ${fsMode}px`);
          findings.push({
            rule: 'R-DECK-TITLE-DRIFT', severity: 'warn', slide_idx: s.idx,
            message:
              `slide ${s.idx}: content-page title drifts from the deck baseline — `
              + bits.join('; ') + '. '
              + 'Page-to-page title position/size should be consistent across content '
              + 'pages; align this one to the deck mode (the value most pages share) '
              + 'so the title doesn\'t jump as the audience pages through. '
              + 'Deliberate? add `data-allow-title-drift` to the slide (or the deck), '
              + 'or `/* allow:title-drift */` in its custom_css. (advisory · never blocks)',
          });
        }
        return findings;
      },
    },

    {
      // R-DECK-PALETTE-DRIFT · 跨页近重复强调色("每页重新目测调色"指纹)。R10 故意
      // strip 掉 <style>(只看 inline / markup),看不见 custom_css / 内联 <style> 里
      // 写死的近重复色号(如 #5cf0dc 与 #5befdc —— 同一个青,手调出三个版本)。这条
      // 用 iterStyleBlocks(true)(含框架 + per-page <style>,正是 R10 的盲区)+ inline
      // style 全量扫 hex / rgb,归一到 rgb,排除近黑/近白/近灰(低 chroma 或暗背景 ——
      // 背景与文字天然就多,不算 accent),把剩下的「真·强调色」聚类:两色同簇 ⇔ 三
      // 通道差都 ≤8。只有当某簇含 ≥3 个【不同】hex(即 ≥3 个近重复)才报 —— 校准实测:
      // 干净 deck 最坏只有 1 个 2-成员簇(brand #3c7fff 与某 mock 蓝 #3a86ff 恰好相近,
      // 合法),要 3 个近重复才是「手调漂移」。framework 自带 6 个品牌强调色彼此分得很
      // 开(无近重复)→ 静默。deck 带 data-allow-palette(或 /* allow:palette */)整豁免。
      // warn。
      id: 'R-DECK-PALETTE-DRIFT',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__RDECK_PALETTE_DONE__) return [];
        if (!ctx.isFirstInScope) return [];   // deck 级:整 deck 算一次
        if (typeof window !== 'undefined') window.__RDECK_PALETTE_DONE__ = true;
        if (typeof document === 'undefined') return [];
        if (document.querySelector('[data-allow-palette]')) return [];
        if (allStyleText().indexOf('allow:palette') >= 0) return [];

        // 颜色源 = 全部 CSS(含框架 + per-page <style>,iterStyleBlocks(true))+ inline
        // style 属性。data: URI 段剥掉(base64 里的假 #hex)。
        let txt = '';
        for (const { css } of iterStyleBlocks(true)) txt += '\n' + css;
        const inlineEls = document.querySelectorAll('[style]');
        for (const el of inlineEls) txt += '\n' + (el.getAttribute('style') || '');
        txt = txt.replace(/data:[^"'\s)]+/g, '');

        const colors = new Set();   // 'r,g,b'
        const addRgb = (r, g, b) => { colors.add(`${r},${g},${b}`); };
        const hexToRgb = (h) => {
          let s = h.toLowerCase();
          if (s.length === 3) s = s[0] + s[0] + s[1] + s[1] + s[2] + s[2];
          return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
        };
        let m;
        const HEX = /#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b/g;
        while ((m = HEX.exec(txt))) { const [r, g, b] = hexToRgb(m[1]); addRgb(r, g, b); }
        const RGB = /rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/g;
        while ((m = RGB.exec(txt))) { addRgb(+m[1], +m[2], +m[3]); }

        // 「真·强调色」过滤:必须够鲜艳(chroma = max-min 通道 ≥60)且够亮(max 通道
        // ≥140)。这排掉:近灰(低 chroma 的文字/边框)、近黑/暗背景(navy #0a1230 一族
        // chroma 虽 ~30 但 max 很低)、近白。校准:must-fire 青 #5cf0dc chroma148 max240
        // 通过;暗背景全被挡。
        const parse = (s) => s.split(',').map(Number);
        const isAccent = (c) => {
          const mx = Math.max(c[0], c[1], c[2]);
          const mn = Math.min(c[0], c[1], c[2]);
          return (mx - mn) >= 60 && mx >= 140;
        };
        const accents = [...colors].map(parse).filter(isAccent);

        // 聚类:同簇 ⇔ 三通道差都 ≤8(near-duplicate 容差)。单链聚合够用。
        const near = (a, b) => Math.abs(a[0] - b[0]) <= 8 && Math.abs(a[1] - b[1]) <= 8 && Math.abs(a[2] - b[2]) <= 8;
        const clusters = [];
        for (const c of accents) {
          let placed = false;
          for (const cl of clusters) {
            if (cl.some((x) => near(x, c))) { cl.push(c); placed = true; break; }
          }
          if (!placed) clusters.push([c]);
        }
        // 只报 ≥3 个不同 hex 的近重复簇(校准:干净 deck 最多 2-成员簇 → 不报;
        // ≥3 = 手调漂移)。
        const toHex = (c) => '#' + c.map((v) => v.toString(16).padStart(2, '0')).join('');
        const dupClusters = clusters.filter((cl) => cl.length >= 3);
        if (!dupClusters.length) return [];

        const groups = dupClusters
          .map((cl) => cl.map(toHex).sort().join(' ≈ '))
          .join(' | ');
        return [{
          rule: 'R-DECK-PALETTE-DRIFT', severity: 'warn', slide_idx,
          message:
            `deck palette has near-duplicate accent colors (the "re-eyeballed the `
            + `accent on every page" fingerprint): ${groups}. `
            + 'These read as the SAME color but are hand-tuned variants — unify each '
            + 'cluster to ONE accent (ideally a `--fs-*` token) so the brand color is '
            + 'identical deck-wide. (R10 can\'t see these because it strips `<style>`.) '
            + 'Intentional? add `data-allow-palette` to the deck (or `/* allow:palette */`). '
            + '(advisory · never blocks)',
        }];
      },
    },

    {
      // R-DECK-TYPESCALE-BUDGET · 全 deck allow:typescale 滥用(豁免变成了常态:
      // northregion 实测 161 条)。/* allow:typescale */ 本是给罕见 hero 数字(封面 100、
      // big-stat 132+ 等)的逃生口,被逐页攒成 deck 级常态后,R20 的 4-tier 台阶约束
      // 实际被架空。这条数【作者 / per-page CSS】里 allow:typescale 出现次数(R20 honor
      // 的那个 marker)与【非 hero 内容页】数;次数 > 1.0×内容页数 → 报(给出总数、均值)。
      // ⚠️ 只数作者 CSS(iterStyleBlocks(false),data-source=framework 排除)—— 框架表
      //    自带 3 条 hero-numeral 豁免(cover/section/image-text 等)是【每个 deck 都有】
      //    的基线噪声,不是作者滥用;实测干净 deck 作者 marker = 0(无论几页都静默),
      //    northregion 那 161 条全在 per-page CSS。must-fire 实测 8/2=4×/页 远超。deck 带
      //    data-allow-typescale-budget(或注释 /* allow:typescale-budget */)整豁免。warn。
      id: 'R-DECK-TYPESCALE-BUDGET',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__RDECK_TSBUDGET_DONE__) return [];
        if (!ctx.isFirstInScope) return [];   // deck 级:整 deck 算一次
        if (typeof window !== 'undefined') window.__RDECK_TSBUDGET_DONE__ = true;
        if (typeof document === 'undefined') return [];
        if (document.querySelector('[data-allow-typescale-budget]')) return [];
        // opt-out 注释在【任意】CSS 都认(作者写在 custom_css 也行)。
        if (allStyleText().indexOf('allow:typescale-budget') >= 0) return [];

        // allow:typescale 出现次数 —— 只数作者 / per-page CSS(排除框架的 hero 基线豁免;
        // 与 R20 读同一个 marker,但 R20 是逐条按 [data-page=/[data-slide-key= 选择器 gate
        // 出作者规则,这里直接用 iterStyleBlocks(false) 把 data-source=framework 整块排除)。
        let authorCss = '';
        for (const { css: c } of iterStyleBlocks(false)) authorCss += '\n' + c;
        const occ = (authorCss.match(/allow:typescale/g) || []).length;
        // 内容页 = 非 hero(与标题漂移同口径:豁免名集合 = HERO_LAYOUTS)。
        const slides = document.querySelectorAll('.slide');
        let content = 0;
        slides.forEach((sl) => {
          const layout = sl.getAttribute('data-layout') || '';
          if (!HERO_LAYOUTS.has(layout)) content += 1;
        });
        if (content < 1) return [];
        // 阈值:严格大于 1.0 × 内容页数(phase-1a 恰好 =1.00 须放行 → 用 >,非 >=)。
        if (occ <= content) return [];

        const avg = (occ / content).toFixed(1);
        return [{
          rule: 'R-DECK-TYPESCALE-BUDGET', severity: 'warn', slide_idx,
          message:
            `deck uses \`allow:typescale\` ${occ}× across ${content} content pages `
            + `(~${avg} per page). The exemption is meant for RARE hero numbers `
            + '(cover 100, section 88/160, big-stat 132+, quote 88+), not a deck-wide '
            + 'escape from the 4-tier ladder {16,24,28,48}. When most pages opt out, '
            + 'R20\'s type-scale discipline is effectively gone — pull the recurring '
            + 'off-tier sizes back onto the ladder (or into shared `--fs-*` tokens) '
            + 'and keep `allow:typescale` for the genuine hero exceptions. '
            + 'Deliberate? add `data-allow-typescale-budget` to the deck. '
            + '(advisory · never blocks)',
        }];
      },
    },

    {
      // R-DECK-EYEBROW-BUDGET · 跨页 eyebrow 密度预算 (F-349, 2026-06-20).
      //   AI slop 高频指纹:每页标题上方都扣一个 uppercase tracking 小标签(eyebrow/kicker)。
      //   飞书 content 页本是单行纯标题(deck 既有约定:content/story 页无 eyebrow);R56 只在
      //   框架 `.header .eyebrow` 上强制【结构】,从不数【密度】。本条按 taste-skill「最多 1
      //   eyebrow / 3 sections」立 deck 级预算:数【内容页(非 hero)中带 eyebrow 的页数】,
      //   超过 ⌈内容页数 / 3⌉ → warn。eyebrow 判定 = class token ∈ {eyebrow,kicker,overline}
      //   (含框架 `.header .eyebrow`,token-exact·零误报)。【刻意不猜 un-classed 小标签】:
      //   对抗验证实测,基于文字样式的 de-facto 启发(uppercase/tracked/small)会把 KPI 指标标
      //   (GMV/ARR)、双语 EN gloss(revenue)、状态徽标(LIVE)这类【非 eyebrow】的复现小标签全
      //   误报。地板规则 FP 是大忌:宁可漏(raw 页手搓未加类的 eyebrow)也绝不误报;作者要纳入时
      //   加 `.eyebrow`/`.kicker` 类即可(框架本就这么渲)。
      //   hero 版式(cover/section/quote…)的 eyebrow 是合法的,不计入(只数内容页)。deck 带
      //   data-allow-eyebrow-budget(或 /* allow:eyebrow-budget */)整豁免。warn。
      id: 'R-DECK-EYEBROW-BUDGET',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__RDECK_EYEBROW_DONE__) return [];
        if (!ctx.isFirstInScope) return [];   // deck 级:整 deck 算一次
        if (typeof window !== 'undefined') window.__RDECK_EYEBROW_DONE__ = true;
        if (typeof document === 'undefined') return [];
        if (document.querySelector('[data-allow-eyebrow-budget]')) return [];
        if (allStyleText().indexOf('allow:eyebrow-budget') >= 0) return [];

        const slides = document.querySelectorAll('.slide');
        let content = 0, withEye = 0;
        slides.forEach((sl) => {
          const layout = sl.getAttribute('data-layout') || '';
          if (HERO_LAYOUTS.has(layout)) return;     // 只数内容页(hero 的 eyebrow 合法)
          content += 1;
          // class-marked eyebrow/kicker/overline(含框架 `.header .eyebrow`)。CSS 类选择器
          // `.eyebrow` 是 token-exact(`.eyebrow-x` 不匹配)。可见性过滤一道。
          const eyeEl = sl.querySelector('.eyebrow, .kicker, .overline');
          if (eyeEl) {
            const cs = getComputedStyle(eyeEl);
            if (cs.display !== 'none' && cs.visibility !== 'hidden' && +cs.opacity !== 0) withEye += 1;
          }
        });
        if (content < 1) return [];
        const budget = Math.ceil(content / 3);
        if (withEye <= budget) return [];

        return [{
          rule: 'R-DECK-EYEBROW-BUDGET', severity: 'warn', slide_idx,
          eyebrow_pages: withEye, content_pages: content, budget,
          message:
            `deck 在 ${content} 个内容页里有 ${withEye} 页带 eyebrow/kicker 小标签(预算 `
            + `⌈${content}/3⌉=${budget})—— "每页标题上方都扣一个 uppercase 小标签"的 AI 指纹。`
            + '飞书 content 页本是单行纯标题,eyebrow 该留给 section/分隔等仪式时刻。'
            + 'Fix: 删掉内容页上重复的 eyebrow,只在少数承上启下页保留;'
            + '确属设计意图? deck 加 `data-allow-eyebrow-budget`(或 `/* allow:eyebrow-budget */`)。'
            + '(advisory · never blocks)',
        }];
      },
    },

    {
      // R-DECK-RADIUS-DRIFT · 跨页圆角【近重复漂移】 (F-350, 2026-06-20).
      //   与 R-DECK-PALETTE-DRIFT 同构(那条逮近重复强调色,这条逮近重复圆角)。走 CSS 源扫
      //   (只扫【作者 / per-page CSS】iterStyleBlocks(false)+inline style —— 框架统一基线排除)。
      //   抓 border-radius / border-*-radius(含四角 longhand)的 px 值,排 0(直角)、排胶囊/整圆
      //   (≥100px 或 % token,刻意的 pill/dot 不是盒子圆角)。**不罚刻意的分级圆角体系**
      //   (chip/card/sheet=8/16/24,间距大、各自单独 → 合法设计,是 CEILING 模型的事不是地板该管),
      //   只罚【近重复漂移】:3px 容差单链聚类后,某一簇里挤了 ≥3 个肉眼几乎一样的圆角
      //   (11/12/13:本想同一个"~12"手敲出三个),或密集圆角梯(8/10/12/14/16 每级仅差 2px 糊成
      //   一坨)→ warn。对抗验证定校准:tiered 8/16/24 与 rem 8/12/16 静默、near-dup 11/12/13 与密集
      //   梯触发。deck 带 data-allow-radius(或 /* allow:radius */)整豁免。warn。
      id: 'R-DECK-RADIUS-DRIFT',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx } = ctx;
        if (typeof window !== 'undefined' && window.__RDECK_RADIUS_DONE__) return [];
        if (!ctx.isFirstInScope) return [];   // deck 级:整 deck 算一次
        if (typeof window !== 'undefined') window.__RDECK_RADIUS_DONE__ = true;
        if (typeof document === 'undefined') return [];
        if (document.querySelector('[data-allow-radius]')) return [];
        if (allStyleText().indexOf('allow:radius') >= 0) return [];

        // 只扫作者 / per-page CSS(排框架统一基线)+ inline style 属性。data: URI 剥掉。
        let txt = '';
        for (const { css } of iterStyleBlocks(false)) txt += '\n' + css;
        const inlineEls = document.querySelectorAll('[style]');
        for (const el of inlineEls) txt += '\n' + (el.getAttribute('style') || '');
        txt = txt.replace(/data:[^"'\s)]+/g, '');

        // border-radius / border-*-radius(含四角 longhand,故 `(?:-[a-z]+)*` 允许多段)的
        // px 盒子圆角集合。% token 跳过(pill/dot 角),不丢整条声明 → longhand 里混 % 的 px 角仍收。
        const radii = new Set();
        let m;
        const DECL = /border(?:-[a-z]+)*-radius\s*:\s*([^;}{]+)/gi;
        while ((m = DECL.exec(txt))) {
          let pm;
          const NUM = /(\d+(?:\.\d+)?)\s*(px|rem|em|%)?/g;
          while ((pm = NUM.exec(m[1]))) {
            const unit = pm[2] || 'px';
            if (unit === '%') continue;               // 百分比角 = pill/dot,跳过该 token
            let n = parseFloat(pm[1]);
            if (unit === 'rem' || unit === 'em') n *= 16;  // 近似换算
            n = Math.round(n);
            if (n <= 0) continue;                     // 0 = 直角
            if (n >= 100) continue;                   // 胶囊 / 整圆,不是盒子圆角
            radii.add(n);
          }
        }
        const vals = [...radii].sort((a, b) => a - b);
        if (vals.length < 3) return [];               // <3 个盒子圆角:不可能有 ≥3 近重复簇

        // 3px 容差单链聚类(同 PALETTE-DRIFT 的近重复思路);某簇含 ≥3 个【不同】值才报
        // (= ≥3 个近重复,手调漂移)。刻意分级体系(8/16/24,间距 >3px)各成单值簇 → 不报。
        const clusters = [];
        let cur = [vals[0]];
        for (let i = 1; i < vals.length; i++) {
          if (vals[i] - vals[i - 1] <= 3) cur.push(vals[i]);
          else { clusters.push(cur); cur = [vals[i]]; }
        }
        clusters.push(cur);
        const dup = clusters.filter((cl) => cl.length >= 3);
        if (!dup.length) return [];

        const sysList = dup.map((cl) => cl.map((v) => v + 'px').join(' ≈ ')).join(' | ');
        return [{
          rule: 'R-DECK-RADIUS-DRIFT', severity: 'warn', slide_idx,
          radius_clusters: dup.length, values: vals,
          message:
            `deck 作者 CSS 有近重复的盒子圆角(${sysList})—— "每个盒子重新目测圆角"的指纹:`
            + '一簇里挤了 ≥3 个肉眼几乎一样的圆角(本想同一个值却手敲出好几个),或密集圆角梯。'
            + '把每簇近重复圆角统一成一个值(最好抽成共享 `--fs-*` token);刻意的分级体系'
            + '(如 8/16/24 三档)不在此列,pill/dot 用 999px 也不算。'
            + '确属设计意图? deck 加 `data-allow-radius`(或 `/* allow:radius */`)。'
            + '(advisory · never blocks)',
        }];
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
    // Engine self-check (was dead code): every rule in RULES must be declared in
    // RULE_META and every narrowed entry must justify itself — the same contract
    // deck-json/tests/test_rule_contract.py text-parses. Run it at engine load so
    // a drifted RULE_META is also caught at runtime, not ONLY by the test. Surfaced
    // via console.warn (not a `rule:` finding) so it stays out of the emitted-code
    // registry / coverage gate — this is an engine-config diagnostic, not a deck rule.
    if (!run._contractChecked) {
      run._contractChecked = true;
      for (const v of assertRuleContract(RULES.map((r) => r.id), RULE_META)) {
        try { console.warn('[audits.js RULE_META contract] ' + v); } catch (_e) { /* no console */ }
      }
    }
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
          // Coverage hook (UNIFY-VALIDATE-ARCH): a schema-keyed rule may carry a
          // name-free geometric twin `rawFallback(slide, ctx)` for raw pages whose
          // bespoke markup its main selector can't see. It self-guards (bails if the
          // framework hook IS present) so no double-report. Dormant until defined.
          if (layout === 'raw' && typeof rule.rawFallback === 'function') {
            const rf = rule.rawFallback(slide, ctx) || [];
            for (const f of rf) findings.push(f);
          }
        } catch (e) {
          findings.push({
            rule: rule.id, severity: 'error', slide_idx,
            message: `audit '${rule.id}' threw on slide ${slide_idx}: ${e && e.message}`,
          });
        }
      }
    });
    // 宽松安全阀:每条规则 deck-wide 最多 40 条 finding —— 只挡病态洪泛(单规则数十上百条,
    // 通常是同一缺陷全 deck 复发),正常 deck 远低于阈值、完全不受影响。封顶【非静默】:被截的
    // 规则补一条 *-CAPPED 提示告知剩余条数,绝不悄悄藏结果(避免旧引擎那种静默 [:N] 截断)。
    const PER_RULE_CAP = 40;
    let outFindings = findings;
    const ruleCounts = new Map();
    for (const f of findings) ruleCounts.set(f.rule, (ruleCounts.get(f.rule) || 0) + 1);
    if ([...ruleCounts.values()].some((n) => n > PER_RULE_CAP)) {
      const kept = new Map();
      const dropped = new Map();
      // Track the HIGHEST severity among the dropped findings per rule so the
      // collapse marker inherits it — emitting it as a flat 'warn' would silently
      // DOWNGRADE the overflow of an error-class rule, so a strict / gate run that
      // promotes warns→errors would still under-represent a real error tail.
      const droppedSev = new Map();
      const SEV_RANK = { warn_soft: 0, warn: 1, error: 2 };
      outFindings = [];
      for (const f of findings) {
        const n = (kept.get(f.rule) || 0) + 1;
        kept.set(f.rule, n);
        if (n <= PER_RULE_CAP) {
          outFindings.push(f);
        } else {
          dropped.set(f.rule, (dropped.get(f.rule) || 0) + 1);
          const prev = droppedSev.get(f.rule);
          const cur = f.severity || 'warn';
          if (prev === undefined || (SEV_RANK[cur] || 0) > (SEV_RANK[prev] || 0)) {
            droppedSev.set(f.rule, cur);
          }
        }
      }
      for (const [rid, extra] of dropped) {
        outFindings.push({
          rule: rid, severity: droppedSev.get(rid) || 'warn', slide_idx: 0,
          message: `${rid}: 另有 +${extra} 处(deck-wide 超过 ${PER_RULE_CAP} 条已折叠)—— `
            + '同一缺陷在全 deck 反复出现,修根因即可批量消除。',
        });
      }
    }
    return {
      engine: 'audits.js',
      version: 1,
      rules: RULES.map((r) => r.id),
      scope: scopeSet ? [...scopeSet] : null,
      slides_total: slides.length,
      findings: outFindings,
    };
  }

  return run((typeof window !== 'undefined' && window.__AUDIT_SCOPE__) || null);
})();
