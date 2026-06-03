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
  //  (UI1 / R-VIS-LIFT-STYLE-LOST / R-AUTOBALANCE-PRESENT / R-RAW-LOOKS-SCHEMA /
  //   audit_structure: R02/R07)
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

  // ── R-RAW-LOOKS-SCHEMA:icon 方形 viewBox 判定(逐字对应 _is_icon_vb)。
  const isIconViewBox = (vb) => {
    const p = (vb || '').trim().split(/\s+/);
    if (p.length !== 4) return false;
    const w = parseFloat(p[2]);
    const h = parseFloat(p[3]);
    if (!isFinite(w) || !isFinite(h)) return false;
    return w === h && w > 0 && w <= 64;
  };
  // 结构级 flow/relationship 信号(逐字对应 _FLOW_SIGNALS)—— markup 级连接器,
  // 不含正文里的箭头字形(那种"投入 → 产出"的扁平卡片仍算扁平)。在 slide 源 HTML 上判。
  const RLS_FLOW_SIGNALS = ['connector', 'data-arrow', 'class="arrow'];

  // ── R-RAW-LOOKS-SCHEMA 的 raw_keys 来源:Python 读 index.html 旁的 deck.json。
  //    渲染后没有磁盘 deck.json,改从【渲染后 DOM 的真 data-layout】判 raw —— 但原版
  //    特意说明 raw 页常伪装成 schema-ish data-layout 借框架 CSS,所以 data-layout 不可靠,
  //    SOURCE-OF-TRUTH = deck.json。运行期 deck.json 由 runner 通过 window.__DECK_JSON__
  //    注入(若存在);缺则 fall back 到 data-layout="raw"。两者皆缺 → 该帧不参与(安静跳过,
  //    与原版"无 deck.json 则 skip"同向:advisory 永不误报)。返回 raw slide-key 集合 or null。
  const rawKeysFromDeckJson = () => {
    if (typeof window !== 'undefined' && window.__RLS_RAW_KEYS__ !== undefined) {
      return window.__RLS_RAW_KEYS__;
    }
    let out = null;
    const dj = (typeof window !== 'undefined' && window.__DECK_JSON__) || null;
    if (dj && Array.isArray(dj.slides)) {
      out = new Set();
      for (const s of dj.slides) {
        if (((s.layout || '').trim() === 'raw') && s.key) out.add(s.key);
      }
    }
    if (typeof window !== 'undefined') window.__RLS_RAW_KEYS__ = out;
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
                  + `nearest tier = ${nearest}px `
                  + '(allowed: 16 Foot / 24 Body / 28 Sub / 48 Title — '
                  + '4-tier strict per the canonical PPT→Web mapping). '
                  + 'Add /* allow:typescale */ in the rule to override '
                  + '(only for hero exceptions: cover 100, section 88/160, '
                  + `big-stat 132+, quote 88+, or mockup-internal 10-13).${note}`,
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
          // parent 链含 echo-intentional class → 跳过(子串匹配,与原版同)。
          if (target.parents.some((p) => SKIP_PARENT_CLS.some((s) => (p || '').indexOf(s) >= 0))) continue;
          let cjkChars = 0;
          for (const c of text) if (isCjk(c)) cjkChars++;
          if (cjkChars < 4) continue;
          const tgtCls = (target.cls || '').toLowerCase();
          const parentCls = target.parents.join(' ').toLowerCase();
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
        if (!slideHasWordmark(slide)) {
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
      // R-RAW-LOOKS-SCHEMA · raw-first 反向闸:过度处理的扁平 N 卡片并列。(步骤 3 第五批
      // 迁自 _validate_audits.py audit_raw_looks_schema)。SOURCE-OF-TRUTH = deck.json 的
      // layout:"raw" key(渲染后 data-layout 会伪装,不可信);无 deck.json → 安静跳过(advisory
      // 永不误报)。命中条件:该 key 是 raw、无 @keyframes、无 非 icon diagram svg、无
      // arrow/connector flow 信号、card token 数 ∈ [3,6] → warn_soft(ADVISORY,--strict 也不升级)。
      //
      // 移植:raw_keys 由 runner 经 window.__DECK_JSON__ 注入(无则 fall back data-layout="raw");
      //   @keyframes / svg viewBox / flow 信号 / card token 计数全在 slide 源 HTML 上判(与原版
      //   逐字正则等价,保留高精度)。key 用 data-slide-key 属性。
      id: 'R-RAW-LOOKS-SCHEMA',
      severity: 'warn_soft',
      evaluate(slide, ctx) {
        const { slide_idx, layout } = ctx;
        const rawKeys = rawKeysFromDeckJson();
        const key = slide.getAttribute('data-slide-key') || '';
        // SOURCE-OF-TRUTH: deck.json 注入了 → 严格按其 raw key 集判(缺 key 不算 raw)。
        // 没注入 deck.json → fall back 渲染后 data-layout="raw"(尽力而为;原版无 deck.json
        // 时直接 skip,这里 fall back 是更宽的"尽量也查",仍只对 raw 帧、advisory)。
        let isRaw;
        if (rawKeys === null) {
          isRaw = (layout === 'raw');
        } else {
          isRaw = rawKeys.has(key);
        }
        if (!isRaw) return [];
        const fr = slideOuterHTML(slide);
        if (fr.indexOf('@keyframes') >= 0) return [];   // animated → 真 bespoke
        // svg 计数:全部 svg vs icon svg(方形小 viewBox);有非 icon diagram svg → bespoke。
        const allSvg = slide.querySelectorAll('svg').length;
        let iconSvg = 0;
        slide.querySelectorAll('svg').forEach((svg) => {
          const vb = svg.getAttribute('viewBox');
          if (vb && isIconViewBox(vb)) iconSvg += 1;
        });
        if (allSvg > iconSvg) return [];                // 非 icon diagram svg → bespoke
        if (RLS_FLOW_SIGNALS.some((sig) => fr.indexOf(sig) >= 0)) return [];  // flow/relationship
        // card 元素数:`card` 作为独立 class TOKEN(不是含 "card" 的每个 class)。
        const cardRe = /class="(?:[^"]*\s)?card(?:\s[^"]*)?"/g;
        const cards = (fr.match(cardRe) || []).length;
        if (cards >= 3 && cards <= 6) {
          return [{
            rule: 'R-RAW-LOOKS-SCHEMA',
            severity: 'warn_soft',
            slide_idx,
            message:
              `raw slide "${key}" looks like a plain ${cards}-card parallel `
              + `list (icon+title+body · no diagram-svg · no animation · no `
              + `arrow/connector) — that is a standard shape. Consider falling `
              + `back to content/3up or content/blocks (less bug surface, `
              + `faster, consistent). [advisory · if the page has bespoke / `
              + `relational / narrative substance, keep raw & ignore · never blocks]`,
          }];
        }
        return [];
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
