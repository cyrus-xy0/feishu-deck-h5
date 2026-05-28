// visual-audit.js — runs inside headless Chromium via page.evaluate()
// from validate.py.
//
// Loaded as: _VISUAL_AUDIT_JS = (HERE / 'visual-audit.js').read_text()
// Then: report = page.evaluate(_VISUAL_AUDIT_JS)
//
// The whole file is ONE arrow function expression. Returns:
//   { overflow: [...], tier: [...], hier: [...], align: [...],
//     label_floor: [...], overlap: [...], body_floor: [...],
//     card_overflow: [...], opt_out_abuse: [...],
//     title_position: [...], abspos_dual_anchor: [...], orphan: [...] }
//
// Why on disk (not embedded in validate.py): JS in a Python r"""..."""
// string is invisible to syntax highlight, gets no `node --check`,
// and stack traces report Python line numbers instead of JS source.
// Extracted 2026-05-24. preflight.sh runs `node --check` on every
// preflight pass so syntax errors are caught before Playwright launches.
//
// Class-list constants near the top (TIER, HERO_CLASSES, META_KEYS,
// BODY_KEYS, CARD_KEYS, CARD_SUFFIXES, CHROME_WHITELIST) are the
// audit's "hardcoded vocabulary". When adding new layouts to the
// framework, these may need an entry — search SKILL.md for the rule
// (e.g. "Hero exceptions", "Hero-context label floor") to see what's
// already in the vocab.

() => {
  const TIER = new Set([16, 24, 28, 48]);
  // Hero exceptions — allowed when selector or ancestor matches one of these classes
  const HERO_CLASSES = [
    'hero-num', 'ov-num', 'chapter-num', 'bigstat-num',
    'cover-title', 'cover-h1', 'big-num', 'num', 'unit',
    'slogan',
    // 2026-05-17: north-star-map / verdict-card / pipeline use `idx`
    // as the visual anchor numeral (88 hero per the hero-context rule).
    'idx',
    // 2026-05-19: generic "hero-*" prefix — anything with hero/anchor/-pct/-val
    // in the class name is conventionally the focal numeral / metric.
    'hero', 'kpi-val', 'metric-value', 'kpi-strip',
    // closing-strip uses span for the 52 px hero callout
    'closing-strip',
  ];
  const HERO_SIZES = new Set([
    30,                                      // cover .author (master spec)
    36, 38, 40, 44,                          // master sub-hero values (lede / section-h2 sub / ctitle)
    52, 56, 64, 72, 88, 92, 96, 100, 132, 160,
    240, 312,                                // big-stat extreme
  ]);
  // Hero layouts — any text element on these slides can use HERO_SIZES.
  // The whole layout is a "hero zone" by design (cover, section divider,
  // big-stat, end-slogan, quote with big blockquote, image-text cinematic).
  // 2026-05-20 · added 'image-text' — title is master-spec 88 px (hero),
  // sits over a full-bleed image. Documented in SKILL.md "Hero exception".
  const HERO_LAYOUTS = new Set([
    'cover', 'section', 'big-stat', 'end', 'quote', 'image-text'
  ]);

  // Meta class hints (lowercase, matched against className.toLowerCase())
  const META_KEYS = [
    'owner', 'attrib', 'source', 'who', 'byline', 'author-meta',
    'timestamp', 'date', 'status', 'kicker', 'eyebrow',
    'td-owner', 'quote-attrib', 'voice-who', 'case-attrib',
  ];
  // Body class hints
  const BODY_KEYS = [
    'body', 'desc', 'paragraph', 'para', 'caption',
    'cc-body', 'card-body', 'td-body', 'nc-body', 'ov-desc',
    'dir-desc', 'mode-body', 'rule-text', 'arch-base', 'feat-body',
  ];
  // Card / panel container hints — for grouping meta vs body.
  // 2026-05-23 · added story-case + pain-card + script-card + ind-row +
  // generic *-card suffix matching (via classified-or-suffix check below)
  // after PROMPTS.md corpus surfaced 字小 complaints in story-case
  // industry-tag, logo-wall ind-name, content-3up pain-card eyebrow,
  // 5-script card-num — all card-like containers not previously in this
  // list. Pattern check (any class ending in -card or containing -tile/
  // -panel) lives in `hasAnyCard()` below.
  const CARD_KEYS = [
    'canonical-card', 'todo-card', 'news-card', 'overview-card',
    'mode-card', 'dir-card', 'scene-card', 'ns-card', 'verdict-card',
    'voice-card', 'cta-box', 'data-panel', 'arch-hand',
    'story-case', 'pain-card', 'script-card', 'card-num',
    'ind-row', 'logo-cell',
  ];
  // Suffix patterns that also indicate a card-like container — broader
  // catch than the explicit CARD_KEYS list.
  const CARD_SUFFIXES = ['-card', '-tile', '-cell', '-panel', '-box'];
  // Grid containers whose children should be equal-height
  const GRID_KEYS = [
    'overview-grid', 'todo-grid', 'scene-grid', 'north-star-map',
    'dir-grid',
  ];
  // True page-level chrome classes — these MAY use 16 (Foot) tier even
  // inside hero cards because they are genuine page-level metadata
  // (page numbers, source attribution, footnotes, copyright). Anything
  // else at 16 inside a hero card is a "字小了" violation.
  const CHROME_WHITELIST = [
    'source', 'pageno', 'footnote', 'attrib', 'copyright',
    'wordmark', 'contact', 'cfoot', 'demo-tag',
    // Hero-numeral units (.unit inside hero numerals like "30 万人") are
    // visually part of the hero anchor itself; they can be sub-tier.
    'unit',
  ];

  const hasAnyClass = (el, keys) => {
    // SVG elements have className as SVGAnimatedString, not string —
    // coerce via baseVal / toString before .toLowerCase().
    const raw = el.className;
    const cls = (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || '')).toString().toLowerCase();
    return keys.some(k => cls.includes(k));
  };
  const firstAncestor = (el, keys) => {
    let n = el.parentElement;
    while (n) {
      if (hasAnyClass(n, keys)) return n;
      n = n.parentElement;
    }
    return null;
  };
  const shortSel = el => {
    const tag = el.tagName.toLowerCase();
    const raw = el.className;
    const clsStr = (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || '')).toString();
    const cls = clsStr.split(/\s+/).filter(Boolean);
    return cls.length ? `${tag}.${cls.join('.')}` : tag;
  };
  // Decide whether an element has direct text content (not just child elements)
  const hasOwnText = el => {
    for (const n of el.childNodes) {
      if (n.nodeType === 3 && n.textContent.trim()) return true;
    }
    return false;
  };

  const out = { overflow: [], tier: [], hier: [], align: [], label_floor: [], overlap: [], body_floor: [], card_overflow: [], opt_out_abuse: [], title_position: [], abspos_dual_anchor: [], orphan: [], balance: [], focal: [] };
  const slides = document.querySelectorAll('.slide');
  slides.forEach((slide, idx) => {
    const slide_idx = idx + 1;
    const label = slide.getAttribute('data-screen-label') || `slide-${slide_idx}`;
    const layout = slide.getAttribute('data-layout') || '';
    const isHeroLayout = HERO_LAYOUTS.has(layout);

    // ---- Overflow ----
    if (slide.scrollHeight > 1080 || slide.scrollWidth > 1920) {
      out.overflow.push({
        idx: slide_idx, label,
        h: slide.scrollHeight, w: slide.scrollWidth,
      });
    }

    // ---- Card-content overflow (added 2026-05-22) ----
    // Inner element has `overflow: hidden` + content taller than container =
    // content clipped invisibly. Slide-level R-OVERFLOW doesn't catch it
    // because the card itself fits in canvas. Common in dense 3-up narrative
    // cards. Skip .slide / .slide-frame themselves (intentional canvas clip).
    const overflowCandidates = slide.querySelectorAll('.stage *');
    overflowCandidates.forEach(el => {
      if (el.tagName === 'SCRIPT' || el.tagName === 'STYLE') return;
      const cs = window.getComputedStyle(el);
      const overflowY = cs.overflowY;
      const overflow = cs.overflow;
      const clips = (overflowY === 'hidden' || overflowY === 'clip' ||
                     overflow === 'hidden' || overflow === 'clip');
      // (a) Vertical clip: overflow:hidden + content taller than container
      if (clips) {
        const dh = el.scrollHeight - el.clientHeight;
        if (dh > 4) {
          out.card_overflow.push({
            slide_idx,
            selector: shortSel(el),
            content_h: el.scrollHeight,
            card_h: el.clientHeight,
            overflow_px: dh,
            direction: 'vertical',
          });
        }
      } else {
        // (a') Visible vertical spill (added 2026-05-27) — overflow NOT hidden,
        // but a CHILD element extends below the box's border-box bottom, i.e.
        // content is bleeding out past border/background (visible, not clipped).
        // Slide-level R-OVERFLOW misses it (spill stays within the 1920×1080
        // canvas) and the clip-only branch (a) ignored overflow:visible — the
        // gap that let a lifted content-3up hero card spill 61px unflagged.
        //
        // We require an actual CHILD-element bottom past the parent box, NOT
        // just scrollHeight > clientHeight: a large-font leaf (e.g. big-stat
        // `.num` at 132px) has a line-box taller than its glyph, so
        // scrollHeight - clientHeight > 0 without any VISIBLE spill. Comparing
        // child rects to the parent's border-box bottom avoids that false
        // positive. GEOMETRY → stays error even on lifted slides.
        const dh = el.scrollHeight - el.clientHeight;
        if (dh > 8 && el.clientHeight > 0 && el.children.length > 0) {
          const elBottom = el.getBoundingClientRect().bottom;
          let spill = 0;
          for (const ch of el.children) {
            if (ch.tagName === 'SCRIPT' || ch.tagName === 'STYLE') continue;
            spill = Math.max(spill, ch.getBoundingClientRect().bottom - elBottom);
          }
          if (spill > 8) {
            out.card_overflow.push({
              slide_idx,
              selector: shortSel(el),
              content_h: el.scrollHeight,
              card_h: el.clientHeight,
              overflow_px: Math.round(spill),
              direction: 'vertical-visible',
            });
          }
        }
      }
      // (b) Horizontal overflow on flex/grid container with nowrap children
      // (added 2026-05-22) — catches "flex row children too wide for parent,
      // bleeding past right edge into adjacent column". scrollWidth >
      // clientWidth means children exceed parent's box. Fires regardless of
      // overflow:hidden (visible bleed AND silent clip both bad).
      const isFlexGrid = ['flex','inline-flex','grid','inline-grid'].includes(cs.display);
      const noWrap = cs.flexWrap === 'nowrap' || cs.display === 'grid' || cs.display === 'inline-grid';
      if (isFlexGrid && noWrap) {
        const dw = el.scrollWidth - el.clientWidth;
        if (dw > 4) {
          out.card_overflow.push({
            slide_idx,
            selector: shortSel(el),
            content_h: el.scrollWidth,
            card_h: el.clientWidth,
            overflow_px: dw,
            direction: 'horizontal',
          });
        }
      }
    });

    // ---- Title position drift (added 2026-05-22) ----
    // Master spec: content-style layouts have .header at top:61 / left:73.
    // New layouts (Phase 1.c extras, iframe-embed, etc.) sometimes inherit
    // different positioning if author forgot to add them to the master
    // header positioning whitelist. Catches the "1 slide's title is way
    // lower than all the others" inconsistency that's hard to eyeball
    // until you flip through the deck.
    //
    // Skip cover / section / end / quote layouts where title is intentionally
    // centered / repositioned (not top-aligned). Master master title for
    // content-style layouts must be at top:61 ± 8px tolerance.
    const TITLE_SKIP_LAYOUTS = new Set(['cover', 'section', 'end', 'quote',
      'big-stat', 'replica', 'image-text']);
    if (!TITLE_SKIP_LAYOUTS.has(layout)) {
      const header = slide.querySelector(':scope > .header');
      const titleEl = slide.querySelector(':scope > .header > .title-zh, :scope > .header > h1.title-zh, :scope > .header > h2.title-zh, :scope > .header h2.title-zh, :scope > .header h1.title-zh');
      if (header && titleEl) {
        const headerTop = Math.round(header.getBoundingClientRect().top - slide.getBoundingClientRect().top);
        const expectedTop = 61;
        const tolerance = 8;
        if (Math.abs(headerTop - expectedTop) > tolerance) {
          out.title_position.push({
            slide_idx, layout, actual_top: headerTop, expected_top: expectedTop,
          });
        }
      }
    }

    // ---- Opt-out abuse: count silence-button reflexes (added 2026-05-22) ----
    // opt-out attributes/comments are documented exception, not mass-mute.
    // ≥ 6 of the same kind on a single slide = silence anti-pattern.
    // See SKILL.md "Validator 报告响应纪律 · opt-out attribute 不是 silence button"
    const OPT_OUT_THRESHOLD = 5;
    // (a) data-allow-body-floor attributes (DOM)
    const dafEls = slide.querySelectorAll('[data-allow-body-floor]');
    if (dafEls.length > OPT_OUT_THRESHOLD) {
      out.opt_out_abuse.push({
        slide_idx, type: 'data-allow-body-floor',
        count: dafEls.length, threshold: OPT_OUT_THRESHOLD,
        examples: [...dafEls].slice(0, 3).map(e => shortSel(e)),
      });
    }
    // (b) CSS comment opt-outs in per-slide <style> blocks
    const styleEls = slide.querySelectorAll('style');
    let typescaleCount = 0, whiteOpacityCount = 0, bodyFloorCount = 0;
    styleEls.forEach(s => {
      const txt = s.textContent;
      typescaleCount += (txt.match(/\/\*\s*allow:typescale[^*]*\*\//g) || []).length;
      whiteOpacityCount += (txt.match(/\/\*\s*allow:white-opacity[^*]*\*\//g) || []).length;
      bodyFloorCount += (txt.match(/\/\*\s*allow:body-floor[^*]*\*\//g) || []).length;
    });
    if (typescaleCount > OPT_OUT_THRESHOLD) {
      out.opt_out_abuse.push({
        slide_idx, type: '/* allow:typescale */',
        count: typescaleCount, threshold: OPT_OUT_THRESHOLD, examples: [],
      });
    }
    if (whiteOpacityCount > OPT_OUT_THRESHOLD) {
      out.opt_out_abuse.push({
        slide_idx, type: '/* allow:white-opacity */',
        count: whiteOpacityCount, threshold: OPT_OUT_THRESHOLD, examples: [],
      });
    }
    if (bodyFloorCount > OPT_OUT_THRESHOLD) {
      out.opt_out_abuse.push({
        slide_idx, type: '/* allow:body-floor */',
        count: bodyFloorCount, threshold: OPT_OUT_THRESHOLD, examples: [],
      });
    }

    // ---- Tier: every text-bearing element ----
    // Mock container classes whose internals are exempt from R-VIS-TIER
    // (mock-internal typography is freely <14 px to look realistic).
    // Shared with R-VIS-BODY-FLOOR below.
    const TIER_MOCK = [
      'ui-window', 'ui-screen', 'ui-chat', 'ui-body', 'ui-toolbar',
      'ui-sidebar', 'ui-grid', 'ui-cell', 'ui-list-item', 'ui-msg',
      'phone', 'phone-screen', 'p22-ph', 'p17-phone', 'fs-phone',
      'chat-body', 'chat-header', 'p22-chat', 'p22-noti', 'p22-know',
      'p22-task', 'ph-bar', 'ph-status', 'ph-chat', 'msg-ai', 'msg-user',
      'dash', 'mini-ui', 'browser-mock', 'p17-xhs', 'p17-dy', 'p17-flow-card',
      'page-replica', 'report-toc', 'report-mock', 'doc-mock',
      'doc-preview', 'wiki-mock', 'feishu-doc', 'lark-doc-mock',
      // 2026-05-19 · topology mockup (.pd-card uses ≤13 px nodes by design)
      'pd-card',
      // 2026-05-19 · doc-grid mockup (thumbnail card grid emulating Lark Doc list)
      'doc-grid', 'doc-stage', 'doc-card',
    ];
    const textEls = slide.querySelectorAll('*');
    const seenTierViolations = new Set();
    textEls.forEach(el => {
      if (!hasOwnText(el)) return;
      // 2026-05-19 · skip SVG text — SVG <text>/<tspan> sizes are visual
      // labels inside diagrams (hero numerals, axis labels) and don't follow
      // the slide-content typography ladder.
      if (el.ownerSVGElement || el.tagName === 'TEXT' || el.tagName === 'tspan') return;
      const cs = window.getComputedStyle(el);
      const px = Math.round(parseFloat(cs.fontSize));
      if (!px || px < 8) return;
      if (TIER.has(px)) return;
      // Hero size allowed if: (a) element or any ancestor matches a hero
      // class, OR (b) the whole slide is a hero layout (cover/section/etc.)
      if (HERO_SIZES.has(px)) {
        if (isHeroLayout) return;
        // walk up to find a hero-class ancestor
        let heroAncestor = false;
        for (let n = el; n && n !== slide; n = n.parentElement) {
          if (hasAnyClass(n, HERO_CLASSES)) { heroAncestor = true; break; }
        }
        if (heroAncestor) return;
      }
      // 2026-05-19 · skip mock-internal: text inside phone / Lark Doc /
      // diagram mockup containers is allowed at any size by design.
      let inMock = false;
      for (let n = el; n && n !== slide; n = n.parentElement) {
        if (hasAnyClass(n, TIER_MOCK)) { inMock = true; break; }
      }
      if (inMock) return;
      // Explicit opt-out: walk up looking for [data-allow-typescale]
      let allowOut = false;
      for (let n = el; n; n = n.parentElement) {
        if (n.dataset && n.dataset.allowTypescale != null) {
          allowOut = true; break;
        }
      }
      if (allowOut) return;
      const sel = shortSel(el);
      const key = `${sel}::${px}`;
      if (seenTierViolations.has(key)) return;
      seenTierViolations.add(key);
      out.tier.push({ slide_idx, selector: sel, computed_px: px, lifted: !!el.closest('[data-lifted]') });
    });

    // ---- Hierarchy: within each card, meta should be ≤ body ----
    // ---- Label floor: hero-context cards forbid 16px non-chrome labels ----
    const cards = slide.querySelectorAll('*');
    const seenCards = new WeakSet();
    const seenLabelFloor = new Set();
    const hasCardSuffix = (el) => {
      const raw = el.className;
      const cls = (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || '')).toString().toLowerCase();
      return CARD_SUFFIXES.some(suf => cls.split(/\s+/).some(c => c.endsWith(suf)));
    };
    cards.forEach(card => {
      if (!hasAnyClass(card, CARD_KEYS) && !hasCardSuffix(card)) return;
      if (seenCards.has(card)) return;
      seenCards.add(card);
      const allTextEls = [...card.querySelectorAll('*')].filter(hasOwnText);
      const metaEls = allTextEls.filter(e => hasAnyClass(e, META_KEYS));
      const bodyEls = allTextEls.filter(e => hasAnyClass(e, BODY_KEYS));

      // --- HIER: meta vs body ---
      if (metaEls.length && bodyEls.length) {
        const bodyPx = Math.min(...bodyEls.map(
          b => Math.round(parseFloat(window.getComputedStyle(b).fontSize))));
        metaEls.forEach(m => {
          const mpx = Math.round(parseFloat(window.getComputedStyle(m).fontSize));
          if (mpx > bodyPx) {
            out.hier.push({
              slide_idx,
              card_sel: shortSel(card),
              meta_sel: shortSel(m),
              meta_px: mpx,
              body_sel: shortSel(bodyEls[0]),
              body_px: bodyPx,
            });
          }
        });
      }

      // --- LABEL FLOOR: content card + < 24px label = error ---
      // R-VIS-LABEL-FLOOR codifies the 2026-05-17 hero-context-label-floor
      // rule in SKILL.md. When a card has content-tier text, every content
      // label inside it must be >= 24; 16/18 is reserved for true page chrome.
      //
      // 2026-05-22 · fix: previously chrome-class elements (.eyebrow, .pill,
      // .tag, .chip, .badge) bypassed this audit unconditionally. That let
      // hero-context cards use 16px .eyebrow chrome at the top, defeating the
      // rule. Now we only bypass when the chrome class is ALSO inside a
      // page-level chrome ancestor (.header / .footer / .source-footer /
      // .pageno) — chrome usage inside a content card is treated as a
      // misnamed content label and gets flagged.
      //
      // 2026-05-23 · broaden: hero-anchor (≥48) requirement misses ~50% of
      // user complaints — empirically, users say "字小" about chrome labels
      // in cards WITHOUT a 48 hero, just a 28-44 Sub-tier anchor (e.g.
      // story-case industry-tag, logo-wall ind-name, scripts card eyebrow).
      // PROMPTS.md corpus shows 85 字小 hits / 8 decks; only ~20% had a
      // hero anchor present. Lower the anchor threshold to ≥ 28 (Sub tier)
      // — any card with content-tier text should bring chrome to ≥ 24.
      const sizes = allTextEls.map(
        e => Math.round(parseFloat(window.getComputedStyle(e).fontSize)));
      const hasContentAnchor = sizes.some(s => s >= 28);
      const PAGE_CHROME_ANCESTORS = ['header', 'footer', 'source-footer',
        'pageno', 'wordmark', 'deck-progress', 'deck-controls'];
      if (hasContentAnchor) {
        allTextEls.forEach(el => {
          const px = Math.round(parseFloat(window.getComputedStyle(el).fontSize));
          if (px >= 24) return;  // Body tier or above is OK
          // Only exempt if element's chrome class is INSIDE a page-chrome
          // ancestor (slide header, footer, etc.) — chrome inside a content
          // card means class is misnamed; flag it.
          if (hasAnyClass(el, CHROME_WHITELIST)) {
            let pageChromeAncestor = false;
            for (let n = el.parentElement; n && n !== card; n = n.parentElement) {
              if (hasAnyClass(n, PAGE_CHROME_ANCESTORS)) {
                pageChromeAncestor = true; break;
              }
            }
            if (pageChromeAncestor) return;
          }
          const sel = shortSel(el);
          const key = `${slide_idx}::${sel}::${px}`;
          if (seenLabelFloor.has(key)) return;
          seenLabelFloor.add(key);
          out.label_floor.push({
            slide_idx,
            card_sel: shortSel(card),
            label_sel: sel,
            label_px: px,
            lifted: !!el.closest('[data-lifted]'),
          });
        });
      }
    });

    // ---- R-VIS-BODY-FLOOR: text content >= 8 chars at < 24px outside chrome ----
    // 2026-05-19 · catches the gap where ambiguous short class names
    // (.rt / .d / .ind-tag) pass both R20 (16 is on the 4-tier ladder)
    // and R06 (class-name heuristic). This renderer-aware check looks at
    // the element's actual rendered fontSize AND its direct text content
    // length: if it has ≥ 8 chars of sentence-like text at < 24 px while
    // NOT inside a mockup container or chrome class, flag it. Author
    // can opt out per-element with [data-allow-body-floor].
    const CONTENT_CHROME_CLASSES = [
      'pageno', 'footnote', 'source', 'attrib', 'copyright', 'wordmark',
      'contact', 'eyebrow', 'pill', 'tag', 'chip', 'badge', 'demo-tag',
      'demo-label', 'caption-meta', 'cite',
    ];
    const MOCK_CONTAINERS = [
      'ui-window', 'ui-screen', 'ui-chat', 'ui-body', 'ui-toolbar',
      'ui-sidebar', 'ui-grid', 'ui-cell', 'ui-list-item', 'ui-msg',
      'phone', 'phone-screen', 'p22-ph', 'p17-phone', 'fs-phone',
      'chat-body', 'chat-header', 'p22-chat', 'p22-noti', 'p22-know',
      'p22-task', 'ph-bar', 'ph-status', 'ph-chat', 'msg-ai', 'msg-user',
      'dash', 'mini-ui', 'browser-mock', 'p17-xhs', 'p17-dy', 'p17-flow-card',
      'page-replica',  // replica mode = full PDF image, no text leaves
      // 2026-05-19 · doc / report mockups (Lark Doc / Wiki preview at small px)
      'report-toc', 'report-mock', 'doc-mock', 'doc-preview', 'wiki-mock',
      'feishu-doc', 'lark-doc-mock',
      'doc-grid', 'doc-stage', 'doc-card',
    ];
    const seenBodyFloor = new Set();
    textEls.forEach(el => {
      // Skip SVG (different size semantics)
      if (el.ownerSVGElement || el.tagName === 'TEXT' || el.tagName === 'tspan') return;
      // Skip non-rendered text holders — a <style>/<script> in body (common in
      // raw-layout slides per SKILL.md Mode A) carries its CSS/JS source as
      // textContent at the default 16px and would false-positive. R-VIS-TIER
      // already skips these (line ~157); body-floor must match.
      if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return;
      const cs = window.getComputedStyle(el);
      const px = Math.round(parseFloat(cs.fontSize));
      if (!px || px >= 24) return;
      // Direct-text only (don't double-count nested child text)
      let directText = '';
      for (const n of el.childNodes) {
        if (n.nodeType === 3) directText += n.textContent;
      }
      directText = directText.trim();
      if (directText.length < 8) return;
      // Element class hints chrome → skip
      if (hasAnyClass(el, CONTENT_CHROME_CLASSES)) return;
      // Inside mockup → skip
      let inMock = false;
      for (let n = el; n && n !== slide; n = n.parentElement) {
        if (hasAnyClass(n, MOCK_CONTAINERS)) { inMock = true; break; }
      }
      if (inMock) return;
      // [data-allow-body-floor] anywhere up the chain → opt out
      let allowOut = false;
      for (let n = el; n; n = n.parentElement) {
        if (n.dataset && n.dataset.allowBodyFloor != null) { allowOut = true; break; }
      }
      if (allowOut) return;
      // Skip hero layouts (cover/section/big-stat/end/quote) — stylized text OK
      if (isHeroLayout) return;
      const sel = shortSel(el);
      const key = `${slide_idx}::${sel}::${px}`;
      if (seenBodyFloor.has(key)) return;
      seenBodyFloor.add(key);
      out.body_floor.push({
        slide_idx, selector: sel, rendered_px: px,
        char_count: directText.length,
        preview: directText.length > 40 ? directText.slice(0, 40) + '…' : directText,
        lifted: !!el.closest('[data-lifted]'),
      });
    });

    // ---- Alignment: grid children equal-height ----
    const grids = slide.querySelectorAll('*');
    grids.forEach(grid => {
      if (!hasAnyClass(grid, GRID_KEYS)) return;
      const kids = [...grid.children];
      if (kids.length < 2) return;
      const heights = kids.map(k => Math.round(k.getBoundingClientRect().height));
      const minH = Math.min(...heights);
      const maxH = Math.max(...heights);
      if (maxH - minH > 4) {
        out.align.push({
          slide_idx,
          grid_sel: shortSel(grid),
          count: kids.length,
          heights: heights.slice(0, 8),
          delta: maxH - minH,
        });
      }
    });

    // ---- Overlap: sibling bbox intersection inside body containers ----
    // 2026-05-18 · catches the P05 case where a flex column-grid child
    // overflowed past its allocated row and visually crashed into the
    // legend strip below it. R-OVERFLOW only catches slide-level
    // (content > 1080); element-overlap-within-canvas needs its own check.
    //
    // Scope: direct children of .stage / .grid / each flex/grid container
    // that's meant to vertical-stack siblings. Skip absolute/fixed-positioned
    // siblings (those are intentional overlays — wordmark, decor, etc.).
    const containers = slide.querySelectorAll('.stage, .grid, .flow, .nodes, .toc, .stack, .table-wrap');
    const seenPairs = new Set();
    containers.forEach(container => {
      const kids = Array.from(container.children).filter(c => {
        const cs = window.getComputedStyle(c);
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
          // 2 px tolerance — sub-pixel rounding can produce 0.5-1 px nominal overlap
          if (overlapX > 2 && overlapY > 2) {
            const key = `${slide_idx}::${shortSel(kids[i])}::${shortSel(kids[j])}`;
            if (seenPairs.has(key)) continue;
            seenPairs.add(key);
            out.overlap.push({
              slide_idx,
              container_sel: shortSel(container),
              a_sel: shortSel(kids[i]),
              b_sel: shortSel(kids[j]),
              overlap_x: Math.round(overlapX),
              overlap_y: Math.round(overlapY),
            });
          }
        }
      }
    });

    // ---- R-VIS-ABSPOS-DUAL-ANCHOR ----
    // An override that adds `top:` to a pill/badge WITHOUT resetting an
    // inherited `bottom:` (or vice versa) leaves both anchors active. With
    // both top + bottom set on `position: absolute` AND no explicit
    // `height`, the element's height becomes (parent.height - top - bottom)
    // regardless of content — a pill / badge / icon stretches to most of
    // the parent. Classic silent-visual bug; static CSS analysis would miss
    // it (each rule reads fine in isolation; the bug is in the cascade
    // between override + framework).
    //
    // Detection — MUTATION TEST (the only reliable way):
    //   getComputedStyle().bottom returns the USED value (always px when
    //   position:absolute), not the DECLARED value, so we can't tell from
    //   computed style alone whether `bottom` was set by CSS. Approach:
    //   for every position:absolute element, temporarily set
    //   `style.bottom = 'auto'` (highest specificity), re-measure height.
    //   If height shrinks significantly → CSS DID declare `bottom` → the
    //   dual-anchor was real → bug.
    //
    //   `display: inline-flex` on absolutely-positioned elements gets
    //   blockified to `flex` per CSS spec — so we can't filter by display.
    //   Instead skip elements where the dual-anchor is clearly intentional:
    //     - left AND right both set (full-bleed overlay) → skip
    //     - opt-out attribute `data-allow-dual-anchor` → skip
    //
    // Performance: only ~10–50 abs-positioned elements per slide;
    // mutation/restore is cheap.
    // Candidate set: position: absolute, no opt-out attribute, NOT a
    // layout-container class. Framework layout shells (.stage, .stack,
    // .iframe-wrap, etc.) legitimately use top+bottom dual-anchor to fill
    // the parent for child layout — that's by design, not a bug. The
    // bug pattern is on CHROME elements (pills, badges, hints, chips,
    // icons) where the override forgot to neutralize an inherited bottom.
    //
    // CANNOT pre-filter by cs.top/bottom/left/right === 'auto' because
    // getComputedStyle returns the USED (px) value for ALL positioned
    // elements — `left` reads as e.g. '1547.52px' even when CSS only
    // declared `right`. So we mutation-test every non-layout candidate.
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
      const cls = (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || '')).toString().split(/\s+/);
      return cls.some(c => LAYOUT_CONTAINER_CLASSES.includes(c));
    };
    const candidates = [];
    slide.querySelectorAll('*').forEach(el => {
      if (el.hasAttribute('data-allow-dual-anchor')) return;
      if (isLayoutContainer(el)) return;
      const cs = window.getComputedStyle(el);
      if (cs.position !== 'absolute') return;
      candidates.push(el);
    });
    candidates.forEach(el => {
      const h1 = el.getBoundingClientRect().height;
      // Skip elements that are 0×0 (display:none ancestors, etc.)
      if (h1 < 4) return;
      // Mutation test: neutralize the bottom anchor via inline style
      // (max specificity, beats any CSS). If CSS had `bottom: <px>`
      // declared, removing it collapses anchor-driven height. If CSS
      // had `bottom: auto` already, the mutation is a no-op.
      const orig = el.style.bottom;
      el.style.bottom = 'auto';
      const h2 = el.getBoundingClientRect().height;
      // Restore
      if (orig) el.style.bottom = orig;
      else el.style.removeProperty('bottom');
      // Bug signature: height shrank materially when bottom was neutralized.
      //   ≥ 30 px shrink (filters out micro-fluctuations)
      //   AND h1 ≥ 2× h2 (filters out cases where content nearly
      //   filled the anchor-driven height — likely a content-driven
      //   container, not a stretched pill).
      const delta = h1 - h2;
      if (delta < 30) return;
      if (h1 < h2 * 2) return;
      const cs = window.getComputedStyle(el);
      const parent = el.offsetParent;
      const parentH = parent ? parent.getBoundingClientRect().height : 1080;
      out.abspos_dual_anchor.push({
        slide_idx,
        selector: shortSel(el),
        top: cs.top,
        bottom: cs.bottom,
        actual_h: Math.round(h1),
        content_h: Math.round(h2),
        parent_h: Math.round(parentH),
      });
    });

    // ---- R-VIS-ORPHAN · CJK 孤字 / 上长下短 失衡换行 (2026-05-25) ----
    // For each leaf CJK text element, measure its line boxes. Flag when it
    // wraps to >=2 lines AND either (a) the last line is a lonely ~1-char
    // orphan, or (b) it is a short 2-3 line label whose last line is < 38%
    // of the widest line (the "上面长下面短" imbalance). `text-wrap: balance`
    // in the framework CSS prevents most of these; this catches the residue
    // (fixed-width / flex-clamped containers where balance can't help — fix
    // with a wider container, `white-space: nowrap`, or a smaller font, or
    // by splitting a trailing word into a `display:block` sub-label).
    // Skip: elements with block-level children (intentional sub-label
    // breaks like .role), SVG text, mockup-internal text, nowrap elements.
    const seenOrphan = new Set();
    slide.querySelectorAll('*').forEach(el => {
      if (!hasOwnText(el)) return;
      if (el.ownerSVGElement || el.tagName === 'TEXT' || el.tagName === 'tspan') return;
      const hasBlockChild = [...el.children].some(c => {
        const d = window.getComputedStyle(c).display;
        return d === 'block' || d === 'flex' || d === 'grid' || d === 'list-item' || d === 'table';
      });
      if (hasBlockChild) return;
      const cjk = ((el.textContent || '').match(/[一-鿿]/g) || []).length;
      if (cjk < 4) return;
      let inMock = false;
      for (let n = el; n && n !== slide; n = n.parentElement) {
        if (hasAnyClass(n, TIER_MOCK)) { inMock = true; break; }
      }
      if (inMock) return;
      const cs = window.getComputedStyle(el);
      if (cs.whiteSpace === 'nowrap' || cs.whiteSpace === 'pre') return;
      const fs = parseFloat(cs.fontSize) || 16;
      const rng = document.createRange(); rng.selectNodeContents(el);
      const byTop = new Map();
      [...rng.getClientRects()].forEach(r => {
        if (r.width < 1 || r.height < 1) return;
        let key = Math.round(r.top);
        for (const k of byTop.keys()) { if (Math.abs(k - key) < 4) { key = k; break; } }
        byTop.set(key, Math.max(byTop.get(key) || 0, r.width));
      });
      const widths = [...byTop.entries()].sort((a, b) => a[0] - b[0]).map(e => e[1]);
      if (widths.length < 2) return;
      const last = widths[widths.length - 1];
      const maxw = Math.max(...widths);
      const isOrphan = last <= fs * 1.45;
      // imbalance 只针对短标签/标题(CJK<=14):长正文 2 行末行天然短,不是缺陷
      const isImbalanced = widths.length <= 3 && last < maxw * 0.38 && cjk <= 14;
      if (!isOrphan && !isImbalanced) return;
      const sel = shortSel(el);
      if (seenOrphan.has(sel)) return;
      seenOrphan.add(sel);
      out.orphan.push({
        slide_idx, selector: sel, lines: widths.length,
        line_px: widths.map(w => Math.round(w)),
        last_px: Math.round(last), max_px: Math.round(maxw), font_px: Math.round(fs),
        kind: isOrphan ? 'orphan' : 'imbalanced',
        balance: cs.textWrap || '',
        preview: (el.textContent || '').trim().slice(0, 16),
      });
    });

    // ---- R-VIS-BALANCE · 视觉重心 / 留白均衡 (2026-05-28) ----
    // 在非 hero 页上,正文容器内的内容应大致居中,不应顶到顶部留下半屏空白,
    // 也不应"中空"——两块内容之间有一条大于 140 px 的死带。Floor 防得很死
    // 但天花板要靠这条规则推:大量 "上空 / 下空 / 中空" 的反馈被 R-OVERFLOW
    // 漏过,因为 validator 只看溢出不看留白。
    //
    // Skip: HERO_LAYOUTS (cover/section/big-stat/end/quote/image-text — 构图
    // 本就非居中)。Per-slide opt-out: `data-allow-imbalance`(罕见,例如
    // 故意"顶天立地"的封面变体)。
    if (!isHeroLayout && !slide.hasAttribute('data-allow-imbalance')) {
      // 找正文容器 —— 直接子元素优先 .stage,fallback 到框架已知正文容器
      let bodyContainer = slide.querySelector(':scope > .stage')
        || slide.querySelector(':scope > .grid')
        || slide.querySelector(':scope > .flow')
        || slide.querySelector(':scope > .nodes')
        || slide.querySelector(':scope > .toc')
        || slide.querySelector(':scope > .table-wrap')
        || slide.querySelector(':scope > .stack');
      // 若 .stage 只包了一层 .grid / .flow / 等,钻进去——gap 要量在真正的
      // 内容容器上,不要把 stage→grid 的 padding 误算成内容空隙。
      while (bodyContainer && bodyContainer.children.length === 1) {
        const only = bodyContainer.children[0];
        const rawc = only.className;
        const clsc = (rawc && rawc.baseVal !== undefined ? rawc.baseVal : (rawc || '')).toString().toLowerCase();
        if (/\b(grid|flow|nodes|toc|table-wrap|stack)\b/.test(clsc)) {
          bodyContainer = only;
        } else { break; }
      }
      if (bodyContainer) {
        const bodyRect = bodyContainer.getBoundingClientRect();
        // 容器至少要有 200 px 才有"重心"概念
        if (bodyRect.height >= 200 && bodyRect.width >= 200) {
          const blocks = [...bodyContainer.children].filter(c => {
            if (c.tagName === 'STYLE' || c.tagName === 'SCRIPT') return false;
            const cs = window.getComputedStyle(c);
            if (cs.display === 'none' || cs.visibility === 'hidden') return false;
            if (cs.position === 'absolute' || cs.position === 'fixed') return false;
            const r = c.getBoundingClientRect();
            return r.width > 8 && r.height > 8;
          }).map(c => ({ el: c, rect: c.getBoundingClientRect() }))
            .sort((a, b) => a.rect.top - b.rect.top);
          if (blocks.length > 0) {
            const contentTop = blocks[0].rect.top;
            const contentBottom = blocks[blocks.length - 1].rect.bottom;
            const topGap = contentTop - bodyRect.top;
            const bottomGap = bodyRect.bottom - contentBottom;
            const slack = topGap + bottomGap;
            // 只有当容器有明显富余 (slack ≥ 150 px) 时,失衡才有意义。
            // 内容塞满了的页,topGap == bottomGap == 0,自然不报。
            if (slack > 150) {
              if (bottomGap > topGap + 120) {
                out.balance.push({
                  slide_idx,
                  container_sel: shortSel(bodyContainer),
                  kind: 'top-heavy',
                  top_gap: Math.round(topGap),
                  bottom_gap: Math.round(bottomGap),
                  body_height: Math.round(bodyRect.height),
                });
              } else if (topGap > bottomGap + 120) {
                out.balance.push({
                  slide_idx,
                  container_sel: shortSel(bodyContainer),
                  kind: 'bottom-heavy',
                  top_gap: Math.round(topGap),
                  bottom_gap: Math.round(bottomGap),
                  body_height: Math.round(bodyRect.height),
                });
              }
            }
            // 死带:相邻内容块之间的垂直空隙 > 140 px。水平 grid (3-up)
            // 子元素的 top/bottom 差几乎为 0,自然不会误报;仅对纵向 stack
            // 有意义。140 px ≈ 13% slide 高,是肉眼能感觉到"中间空一块"
            // 的阈值。
            for (let i = 1; i < blocks.length; i++) {
              const prev = blocks[i - 1].rect;
              const curr = blocks[i].rect;
              const gap = curr.top - prev.bottom;
              if (gap > 140) {
                out.balance.push({
                  slide_idx,
                  container_sel: shortSel(bodyContainer),
                  kind: 'dead-band',
                  gap_px: Math.round(gap),
                  between_a: shortSel(blocks[i - 1].el),
                  between_b: shortSel(blocks[i].el),
                });
              }
            }
          }
        }
      }
    }

    // ---- R-FOCAL-CHECK · 视觉焦点是否清晰 (2026-05-28) ----
    // 一张内容页应该有"唯一的视觉重点":第一眼能落下来的元素。最简单
    // 的客观信号是 — 全页只有一个文本元素占据最大字号。如果 ≥3 个元素
    // 共享最大字号,且无任何元素声明 `.is-hero` / `data-focal`,焦点就
    // 模糊了(eye 不知道从哪看起)。
    //
    // Skip:hero layouts(焦点 == 整张 slide)+ 故意平行结构的 layout
    // (agenda / logo-wall / arch-stack / table / timeline / process /
    // stats / iframe-embed / replica)。这些 layout 的 N 元素等大本身
    // 是设计,不该报。Per-slide opt-out: `data-allow-no-focal`(例如
    // overview 页有意 N 路平权)。
    const FOCAL_PARALLEL_LAYOUTS = new Set([
      'agenda', 'logo-wall', 'arch-stack', 'table', 'timeline', 'process',
      'stats', 'iframe-embed', 'replica',
    ]);
    if (!isHeroLayout
        && !FOCAL_PARALLEL_LAYOUTS.has(layout)
        && !slide.hasAttribute('data-allow-no-focal')) {
      const FOCAL_CHROME_CLASSES = ['wordmark', 'pageno', 'source-footer',
        'footnote', 'source', 'attrib', 'copyright', 'demo-tag',
        'deck-progress', 'deck-controls', 'eyebrow', 'caption',
        'iframe-hint'];
      const focalCands = [];
      slide.querySelectorAll('*').forEach(el => {
        if (!hasOwnText(el)) return;
        if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return;
        if (el.ownerSVGElement || el.tagName === 'TEXT' || el.tagName === 'tspan') return;
        if (hasAnyClass(el, FOCAL_CHROME_CLASSES)) return;
        // Skip mockup-internal
        let inMock = false;
        for (let n = el; n && n !== slide; n = n.parentElement) {
          if (hasAnyClass(n, TIER_MOCK)) { inMock = true; break; }
        }
        if (inMock) return;
        const cs = window.getComputedStyle(el);
        const px = Math.round(parseFloat(cs.fontSize));
        // 小于 20 px 的元素一般是 chrome / 注释,不参与焦点计算
        if (!px || px < 20) return;
        focalCands.push({ el, px });
      });
      if (focalCands.length >= 3) {
        const maxPx = Math.max(...focalCands.map(c => c.px));
        const atMax = focalCands.filter(c => c.px === maxPx);
        // 1 个独享最大字号 → 焦点清晰
        // 2 个共享 → 通常是 title + 一个 body hero,允许
        // ≥3 个共享 → 焦点模糊,报告
        if (atMax.length >= 3) {
          // 平行模式容器 —— 若 atMax 元素全部共享一个"显式 N 路平权"的祖先
          // (overview-grid / north-star-map / scene-grid / logo-wall / 等),
          // 平等大小就是设计本身,不算焦点模糊。
          const PARALLEL_PATTERN_CONTAINERS = new Set([
            'overview-grid', 'north-star-map', 'scene-grid', 'logo-wall',
            'verdict-grid', 'principle-band', 'kpi-strip', 'arch-stack',
            'arch-hands', 'pipeline', 'steps', 'pills', 'toc',
            'agenda-stack', 'iron-corners', 'two-hand-arch',
          ]);
          const ancestorClassSets = atMax.map(c => {
            const set = new Set();
            for (let n = c.el.parentElement; n && n !== slide; n = n.parentElement) {
              const raw = n.className;
              const cls = (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || '')).toString().toLowerCase().split(/\s+/);
              cls.forEach(x => { if (x) set.add(x); });
            }
            return set;
          });
          const commonAncestors = [...ancestorClassSets[0]].filter(
            c => ancestorClassSets.every(s => s.has(c)));
          const inParallelPattern = commonAncestors.some(
            c => PARALLEL_PATTERN_CONTAINERS.has(c));
          if (inParallelPattern) {
            // 走人,这页是显式平行模式
          } else {
            const declared = atMax.filter(c =>
              hasAnyClass(c.el, ['is-hero', 'focal', 'hero-anchor'])
              || (c.el.dataset && c.el.dataset.focal != null));
            // 声明了至少一个 .is-hero / data-focal → 通过(作者已表态)
            if (declared.length === 0) {
              out.focal.push({
                slide_idx,
                layout,
                top_size_px: maxPx,
                tied_count: atMax.length,
                examples: atMax.slice(0, 4).map(c => shortSel(c.el)),
              });
            }
          }
        }
      }
    }
  });

  return out;
}
