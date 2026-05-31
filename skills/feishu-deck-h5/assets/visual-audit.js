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
//     title_position: [...], abspos_dual_anchor: [...], orphan: [...],
//     balance: [...], focal: [...], slack_flex: [...] }
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
  // F-13 · NOT the same as Python validate.py HERO_TITLE_LAYOUTS (do not sync):
  // this is the hero-ZONE set (hero sizes anywhere) and INCLUDES big-stat; the
  // Python set is the hero-TITLE set (flexible header) and excludes big-stat
  // because it has no title. Different questions, intentionally different members.
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

  // ---- box-distribution helpers (R-VIS-CROWD · 2026-05-30) ----
  // Union bbox of visible TEXT-bearing leaves under root (decoration excluded).
  const _contentUnion = (root) => {
    let t = Infinity, b = -Infinity, any = false;
    for (const el of root.querySelectorAll('*')) {
      if (el.tagName === 'SVG' || el.tagName === 'svg' ||
          el.tagName === 'SCRIPT' || el.tagName === 'STYLE') continue;
      if (!hasOwnText(el)) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) continue;
      any = true; t = Math.min(t, r.top); b = Math.max(b, r.bottom);
    }
    return any ? { top: t, bottom: b } : null;
  };
  // A visibly "framed" box (border / bg color / bg image) — text sits INSIDE a frame.
  const _isFramedBox = (el) => {
    const cs = getComputedStyle(el);
    const hb = ['Top', 'Right', 'Bottom', 'Left'].some(s =>
      parseFloat(cs['border' + s + 'Width'] || 0) > 0 &&
      !/transparent|rgba\(0, 0, 0, 0\)/.test(cs['border' + s + 'Color']));
    const bg = cs.backgroundColor, hbg = bg && !/transparent|rgba\(0, 0, 0, 0\)/.test(bg);
    const hbi = cs.backgroundImage && cs.backgroundImage !== 'none';
    return hb || hbg || hbi;
  };
  // Media tiles carry an intentionally edge-placed caption — excluded from crowd.
  const _isMediaBox = (el) => {
    const cs = getComputedStyle(el);
    if (cs.backgroundImage && cs.backgroundImage !== 'none' && !/gradient/i.test(cs.backgroundImage)) return true;
    if (el.querySelector('img,iframe,canvas,video,picture')) return true;
    const raw = el.className;
    const c = (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || '')).toString();
    return /\b(photo|image|img|visual|mock|thumb|avatar|portrait|media|phone|screen)\b/i.test(c);
  };
  // grow-box verdict (改大自动拉高) for a sub-floor body element: if its font is
  // bumped to FLOOR (24), how much taller does it get, and is there room — the
  // box's own bottom slack PLUS canvas space below the box — to GROW THE BOX
  // instead of shrinking the font? Pure measurement, no mutation. Lets the
  // R-VIS-BODY-FLOOR finding say "提到 24 → 框可长高装得下" vs "无空间,需压内容".
  const _growBox = (el, slide, scale) => {
    const FLOOR = 24;
    const px = parseFloat(getComputedStyle(el).fontSize) || FLOOR;
    if (px >= FLOOR) return null;
    const elH = el.getBoundingClientRect().height / scale;
    const growNeeded = Math.round(elH * (FLOOR / px - 1)); // ∝ line-height bump
    let node = el.parentElement, framed = null;
    while (node && node !== slide) {
      if (_isFramedBox(node) && !_isMediaBox(node)) { framed = node; break; }
      node = node.parentElement;
    }
    const target = framed || slide;
    const br = target.getBoundingClientRect();
    const cu = _contentUnion(target);
    const innerSlack = cu ? Math.max(0, (br.bottom - cu.bottom) / scale) : 0;
    const sr = slide.getBoundingClientRect();
    const canvasBelow = framed ? Math.max(0, (sr.bottom - br.bottom) / scale) : 0;
    const room = Math.round(innerSlack + canvasBelow);
    return { grow_needed_px: growNeeded, room_px: room,
             can_grow: growNeeded <= room, in_box: !!framed };
  };

  const out = { overflow: [], tier: [], hier: [], align: [], label_floor: [], overlap: [], body_floor: [], card_overflow: [], opt_out_abuse: [], title_position: [], abspos_dual_anchor: [], orphan: [], balance: [], focal: [], slack_flex: [], card_min_height_sparse: [], crowd: [], title_gap: [], peer_size: [], gutter: [], hero_floor: [], short_label_floor: [] };
  const slides = document.querySelectorAll('.slide');
  slides.forEach((slide, idx) => {
    const slide_idx = idx + 1;
    const label = slide.getAttribute('data-screen-label') || `slide-${slide_idx}`;
    const layout = slide.getAttribute('data-layout') || '';
    const isHeroLayout = HERO_LAYOUTS.has(layout);
    const _scale = parseFloat(getComputedStyle(slide).getPropertyValue('--fs-scale')) || 1;

    // ---- R-VIS-CROWD · 框内文字挤到底边 (2026-05-30) ----
    // name-free 几何:framed 非媒体框,其文字内容离框"可见底边"很近(< 10px)
    // 且明显比顶部更挤(下偏 ≥ 16px)= 文字被挤到框底(qingdao 3up 等高卡的
    // "文字离下面太近"实测离底 3px / 顶部 38px)。与"松"(下方大留白,如 KPI 列
    // 顶基线对齐,实测离底 16px+/262px)区分开 —— 松不触发,所以 stats 类天然
    // 豁免,无需按版式名白名单。阈值 10px 给两侧各 ~6px 余量(校准:挤底 3/6px
    // 触发、stats 16px 放行)。Hero 版式 / data-allow-imbalance 跳过。
    if (!isHeroLayout && !slide.hasAttribute('data-allow-imbalance')) {
      const _framed = [...slide.querySelectorAll('*')].filter(el =>
        _isFramedBox(el) && !_isMediaBox(el) && el.getBoundingClientRect().height > 80 * _scale);
      const _boxes = _framed.filter(el => !_framed.some(o => o !== el && o.contains(el)));
      for (const box of _boxes) {
        const cu = _contentUnion(box); if (!cu) continue;
        const r = box.getBoundingClientRect();
        const distTop = (cu.top - r.top) / _scale;       // text → box visible top edge
        const distBottom = (r.bottom - cu.bottom) / _scale; // text → box visible bottom edge
        if (distBottom < 10 && distTop > distBottom + 16) {
          out.crowd.push({
            idx: slide_idx, label, sel: shortSel(box),
            top_px: Math.round(distTop), bottom_px: Math.round(distBottom),
          });
        }
      }
    }

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
    // 2026-05-31 · raw coverage: a layout:"raw" slide has no .stage wrapper, so the
    // .stage-scoped query would miss every clipped / spilling leaf. Fall back to all
    // descendants ONLY for raw. Schema slides keep '.stage *' verbatim — including
    // schema layouts that legitimately have NO .stage (section/cover/etc.), where a
    // blanket '*' would surface decorative-numeral line-box clips as false positives
    // (e.g. .chapter-num). So: zero schema regression, full raw coverage.
    const overflowCandidates = slide.querySelector('.stage')
      ? slide.querySelectorAll('.stage *')
      : (layout === 'raw' ? slide.querySelectorAll('*') : slide.querySelectorAll('.stage *'));
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
        // (a'') Visible TEXT-LEAF spill (R-VIS-CARD-OVERFLOW upgrade · 2026-05-31)
        // (a') above only catches CONTAINERS (children>0; it compares child
        // border-box bottoms). A pure TEXT LEAF — text but NO element children —
        // has no child rect, so text that wraps an extra line and pokes past its
        // cell slipped through unflagged (P2/P8 · #4 "自然语言搭建业务应用").
        // Measure the leaf's own rendered line boxes via Range.getClientRects()
        // vs the nearest framed ancestor's inner (border) box. Line boxes are the
        // actual rendered rows, so a large-font leaf produces no false positive
        // (the reason branch a' avoided scrollHeight in the first place).
        else if (el.clientHeight > 0 && el.children.length === 0
                 && hasOwnText(el) && !_isMediaBox(el)) {
          // Nearest framed, non-media box that is the leaf ITSELF (a framed card
          // whose own text overflows it) OR an ancestor (text spilling out of a
          // separate framed cell, as in #4). Start at `el` so both cases catch.
          let frame = null;
          for (let n = el; n && n !== slide; n = n.parentElement) {
            if (_isFramedBox(n) && !_isMediaBox(n)) { frame = n; break; }
          }
          if (frame) {
            const fr = frame.getBoundingClientRect();
            const fcs = getComputedStyle(frame);
            const innerBottom = fr.bottom - (parseFloat(fcs.borderBottomWidth) || 0);
            const innerRight  = fr.right  - (parseFloat(fcs.borderRightWidth)  || 0);
            const rng = document.createRange(); rng.selectNodeContents(el);
            let lineBottom = -Infinity, lineRight = -Infinity, anyLine = false;
            for (const lr of rng.getClientRects()) {
              if (lr.width < 1 || lr.height < 1) continue;
              anyLine = true;
              lineBottom = Math.max(lineBottom, lr.bottom);
              lineRight  = Math.max(lineRight,  lr.right);
            }
            if (anyLine) {
              const spill = Math.max((lineBottom - innerBottom) / _scale,
                                     (lineRight  - innerRight)  / _scale);
              if (spill > 4) {
                out.card_overflow.push({
                  slide_idx,
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
      // ---- R-VIS-TITLE-GAP · 正文顶到/重叠标题 (2026-05-31) ----
      // R-VIS-TITLE-POSITION only checks the .header's ABSOLUTE top (≈61); it
      // can't see content that grew/overflowed UP toward the title. Here measure
      // the RELATIVE gap: header bottom → topmost real content block inside .stage.
      // Content is in .stage, the title in .header (cross-container — R-OVERLAP,
      // same-container only, never compares them). < 24px (design px) or negative
      // (overlap) → flag (#5 sections grew into the title).
      // Prefer framework chrome (:scope > .header + :scope > .stage). When absent
      // (raw / hand-built / imported markup), fall back to NAME-FREE bands: title =
      // topmost own-text element in a title tier (≥24px) within the top 40% of the
      // slide; content = the topmost real block below it. Schema decks always have
      // .header + .stage → the named path runs and the fallback never fires, so
      // zero schema regression.
      let tgTitleRect = null, tgTitleSel = null, tgContentTop = Infinity;
      const tgStage = slide.querySelector(':scope > .stage');
      if (header && tgStage) {
        tgTitleRect = header.getBoundingClientRect();
        tgTitleSel = shortSel(header);
        for (const el of tgStage.querySelectorAll('*')) {
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') continue;
          const r = el.getBoundingClientRect();
          if (r.width > 40 && r.height > 16) tgContentTop = Math.min(tgContentTop, r.top);
        }
      } else if (!header) {
        const sr = slide.getBoundingClientRect();
        let tEl = null, tTop = Infinity;
        for (const el of slide.querySelectorAll('*')) {
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') continue;
          if (!hasOwnText(el)) continue;
          const cs = getComputedStyle(el);
          if (cs.position === 'absolute' || cs.position === 'fixed') continue;   // skip chrome / decor
          if (Math.round(parseFloat(cs.fontSize)) < 24) continue;                // title tier only
          const r = el.getBoundingClientRect();
          if (r.width <= 40 || r.height <= 16) continue;
          if ((r.top - sr.top) > sr.height * 0.4) continue;                      // must sit near the top
          if (r.top < tTop) { tTop = r.top; tEl = el; }
        }
        if (tEl) {
          tgTitleRect = tEl.getBoundingClientRect();
          tgTitleSel = shortSel(tEl);
          for (const el of slide.querySelectorAll('*')) {
            if (el === tEl || tEl.contains(el) || el.contains(tEl)) continue;
            if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') continue;
            const cs = getComputedStyle(el);
            if (cs.position === 'absolute' || cs.position === 'fixed') continue;
            const r = el.getBoundingClientRect();
            if (r.width > 40 && r.height > 16 && r.top >= tgTitleRect.bottom - 2) tgContentTop = Math.min(tgContentTop, r.top);
          }
        }
      }
      // contentTop must sit BELOW the title's own top (else it's a full-bleed bg /
      // absolute decor spanning the slide — not "content below title").
      if (tgTitleRect && tgContentTop !== Infinity && tgContentTop >= tgTitleRect.top - 2) {
        const gap = (tgContentTop - tgTitleRect.bottom) / _scale;
        if (gap < 24) {
          out.title_gap.push({
            slide_idx, layout, gap_px: Math.round(gap), title_sel: tgTitleSel,
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
    // F-13: single source — the body-floor mock set IS the tier mock set (the
    // TIER_MOCK comment says "Shared with R-VIS-BODY-FLOOR below"). They had
    // silently drifted: `pd-card` was added to TIER_MOCK (2026-05-19) but not
    // here, so .pd-card's ≤13px nodes were exempt from TIER/ORPHAN/FOCAL yet
    // wrongly policed by BODY-FLOOR. Alias keeps them in lockstep forever.
    const MOCK_CONTAINERS = TIER_MOCK;
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
        // grow-box verdict: can we 改大自动拉高 (enlarge font + grow box) here?
        ...(_growBox(el, slide, _scale) || {}),
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
      // imbalance 针对短标签/标题:长正文 2 行末行天然短,不是缺陷。
      // CJK 上限按 hero 上下文放宽 — hero 标题字号 ≥ 72px(section 88 /
      // cover 100 / quote 88+ 都在这一档),一行能放 13-15 CJK 就到 max-width,
      // 16+ CJK 在 hero 里仍是"短标题"。Body 用 14 字 cap 防长正文误报。
      // (2026-05-29 · P08 章节标题 16 CJK 漏报触发)
      const heroFont = fs >= 72;
      const cjkCap = heroFont ? 25 : 14;
      const isImbalanced = widths.length <= 3 && last < maxw * 0.38 && cjk <= cjkCap;
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
        || slide.querySelector(':scope > .stack')
        // 2026-05-31 · raw coverage: no framework container (raw / hand-built /
        // imported markup) → measure balance against the slide itself. Chrome
        // (wordmark / pageno) is position:absolute and is filtered out of both
        // `blocks` and `contentEls` below, so the geometry still reflects real
        // content. Schema decks always resolve a named container first → the
        // fallback never fires for them, so zero schema regression.
        || slide;
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
            // 横向失衡 / 单侧空壳 (2026-05-31 · P10):真实内容(text+media 叶子,
            // 空框不计)挤向一侧,另一侧 ≥22% 横向空。右侧若有图(media 计入)则
            // 不报 → 只揪真空(#36「右半空壳面板」/ 内容偏左右侧空)。raw px,
            // 与上面纵向阈值一致。横向 3-up 内容铺满 → 两侧 slack 都小,不报。
            const contentEls = [...bodyContainer.querySelectorAll('*')].filter(el => {
              if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return false;
              const cs = getComputedStyle(el);
              if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return false;
              const r = el.getBoundingClientRect();
              if (r.width < 8 || r.height < 8) return false;
              const hasText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
              const isMedia = el.matches('img,video,canvas,iframe,picture,svg')
                || (cs.backgroundImage && cs.backgroundImage !== 'none' && !/gradient/i.test(cs.backgroundImage));
              return hasText || isMedia;
            });
            if (contentEls.length) {
              let cl = Infinity, cr = -Infinity;
              for (const el of contentEls) { const r = el.getBoundingClientRect(); cl = Math.min(cl, r.left); cr = Math.max(cr, r.right); }
              const leftSlack = cl - bodyRect.left, rightSlack = bodyRect.right - cr, bw = bodyRect.width;
              if (leftSlack + rightSlack > 0.22 * bw
                  && Math.abs(leftSlack - rightSlack) > 0.22 * bw
                  && Math.abs(leftSlack - rightSlack) > 200) {
                out.balance.push({
                  slide_idx, container_sel: shortSel(bodyContainer), kind: 'side-empty',
                  left_slack: Math.round(leftSlack), right_slack: Math.round(rightSlack),
                  body_width: Math.round(bw),
                });
              }
            }
          }
        }
      }
    }

    // ---- R-VIS-SLACK-FLEX · flex:1 子容器撑出内部空白 (2026-05-28) ----
    // R-VIS-BALANCE 看的是 body container 顶级 children 之间的 sibling gap;
    // 但视觉"远"还有另一类来源 —— `flex:1`(或 flex-grow ≥ 1)子容器
    // 抢光剩余空间后,**内部内容比拿到的空间小**,内部 justify-content
    // (center / flex-end / space-between)把空白分到容器内部上/下/中间。
    // 这种内部 slack 在 R-VIS-BALANCE 的 sibling gap 检测里看不到(sibling
    // 之间只有 stage 的 gap,几 px),但视觉上 user 看到的是 flex 子项内部
    // 末元素到下一 sibling 之间的"大距离"。典型踩坑:`flex:1` arch3 内部
    // justify-content:center,arch3 拿到 800px,内容 600px,200 px slack 分
    // 给 arch3 顶/底各 100 px → arch3 最后一行到 sibling closing 的视觉间距
    // ≈ 100 + stage.gap。Eye 读到"closing 离 arch3 太远"。
    //
    // 检测:为每个 flex column 容器的 child,若 child computed flex-grow ≥ 1
    // 且 child 内部 visible grandchild 存在,measure:
    //   topSlack    = grandchildFirst.top    - child.contentBox.top
    //   bottomSlack = child.contentBox.bottom - grandchildLast.bottom
    // 任一 > 80 px → WARN(80 ≈ slide 8%,肉眼能感觉到)。
    //
    // Skip: HERO_LAYOUTS(cover/section/big-stat/end/quote/image-text 构图
    // 通常不是 flex column)、容器自身 height < 200(不可能有显著 slack)、
    // grandchild count == 0(空 flex 容器)。
    // Opt-out: `data-allow-flex-slack` 在 flex container OR flex-grow child
    // 上(罕见:故意把内容推到某一端,e.g. push-footer-to-bottom layout)。
    if (!isHeroLayout) {
      slide.querySelectorAll('*').forEach(container => {
        const cs = window.getComputedStyle(container);
        if (cs.display !== 'flex' && cs.display !== 'inline-flex') return;
        if (!cs.flexDirection.startsWith('column')) return;
        if (container.hasAttribute('data-allow-flex-slack')) return;
        const cRect = container.getBoundingClientRect();
        if (cRect.height < 200) return;
        // iterate direct children
        [...container.children].forEach(child => {
          if (child.tagName === 'STYLE' || child.tagName === 'SCRIPT') return;
          if (child.hasAttribute('data-allow-flex-slack')) return;
          const ccs = window.getComputedStyle(child);
          if (ccs.display === 'none' || ccs.visibility === 'hidden') return;
          const grow = parseFloat(ccs.flexGrow || '0');
          if (!(grow >= 1)) return;
          const chRect = child.getBoundingClientRect();
          if (chRect.height < 200) return;
          // visible grandchildren — filter style/script and 0-size
          const gcs = [...child.children].filter(gc => {
            if (gc.tagName === 'STYLE' || gc.tagName === 'SCRIPT') return false;
            const gccs = window.getComputedStyle(gc);
            if (gccs.display === 'none' || gccs.visibility === 'hidden') return false;
            const r = gc.getBoundingClientRect();
            return r.height > 4;
          });
          if (gcs.length === 0) return;
          const rects = gcs.map(gc => gc.getBoundingClientRect())
                            .sort((a, b) => a.top - b.top);
          // child content box: bbox minus padding (simplified — pad-aware)
          const padTop    = parseFloat(ccs.paddingTop)    || 0;
          const padBottom = parseFloat(ccs.paddingBottom) || 0;
          const contentTop    = chRect.top    + padTop;
          const contentBottom = chRect.bottom - padBottom;
          const topSlack    = rects[0].top    - contentTop;
          const bottomSlack = contentBottom - rects[rects.length - 1].bottom;
          // threshold 80 px (≈ 7.4% of canvas height)
          const THRESHOLD = 80;
          if (topSlack < THRESHOLD && bottomSlack < THRESHOLD) return;
          out.slack_flex.push({
            slide_idx,
            container_sel: shortSel(container),
            child_sel: shortSel(child),
            flex_grow: grow,
            child_height: Math.round(chRect.height),
            content_height: Math.round(rects[rects.length - 1].bottom - rects[0].top),
            top_slack: Math.round(topSlack),
            bottom_slack: Math.round(bottomSlack),
            justify: ccs.justifyContent,
          });
        });
      });
    }

    // ---- R-VIS-CARD-MIN-HEIGHT-SPARSE · min-height 撑空 + 没 space-between (2026-05-29) ----
    // 作者用 `min-height` 撑 card 视觉体量(常见于"5 卡一行"等 grid),但 card
    // 内是 default `justify-content: flex-start` → 内容堆顶,卡底大量空白。
    // 正解:加 `class="fs-card-fill"` (= space-between),让 N 个 child 均布。
    //
    // 触发 2026-05-29 P15 调试:min-height 540/640 默认 flex-start,卡底
    // 看着空。space-between 是答案,但 framework 没默认提醒 → 作者不知道。
    //
    // 检测(bbox 量法,2026-05-29 修):
    //   1) flex column 元素
    //   2) min-height > 50px (作者刻意撑了)
    //   3) usable_height (clientH - padTop - padBottom) 减去
    //      content_extent (last_child.bottom - first_child.top)
    //      > 60px (这是"真"slack — gap/margin 都自动含进 extent)
    //   4) justify-content 不在 {space-between, space-evenly, space-around}
    // → WARN(留白判断主观,故 warn 不 error)
    //
    // 早期版用 sum(kid heights) + gap 计算 content,但忽略了 `margin` 间距,
    // 在用 margin-bottom 撑子元素的卡上(P04 bytedance hero)误报 95px slack
    // (实际只有 10px)。bbox 量法对 gap / margin 一视同仁,不再误报。
    //
    // Skip: HERO_LAYOUTS;有 `.fs-card-fill` 类的元素(已 opt-in);
    // 单 child 元素(没意义);data-allow-min-height-sparse opt-out。
    if (!isHeroLayout) {
      slide.querySelectorAll('*').forEach(el => {
        if (el.classList.contains('fs-card-fill')) return;
        if (el.hasAttribute('data-allow-min-height-sparse')) return;
        const cs = window.getComputedStyle(el);
        if (cs.display !== 'flex' && cs.display !== 'inline-flex') return;
        if (!cs.flexDirection.startsWith('column')) return;
        const minH = parseFloat(cs.minHeight) || 0;
        if (minH < 50) return;
        const jc = cs.justifyContent;
        if (jc === 'space-between' || jc === 'space-evenly' || jc === 'space-around') return;
        // Count visible direct children
        const kids = [...el.children].filter(c => {
          if (c.tagName === 'STYLE' || c.tagName === 'SCRIPT') return false;
          const ccs = window.getComputedStyle(c);
          if (ccs.display === 'none' || ccs.visibility === 'hidden') return false;
          return c.getBoundingClientRect().height > 4;
        });
        if (kids.length < 2) return;
        // bbox-based content extent — auto-includes any margin/gap spacing
        const elRect = el.getBoundingClientRect();
        const firstTop = kids[0].getBoundingClientRect().top - elRect.top;
        const lastBottom = kids[kids.length - 1].getBoundingClientRect().bottom - elRect.top;
        const contentExtent = lastBottom - firstTop;
        const padTop = parseFloat(cs.paddingTop) || 0;
        const padBottom = parseFloat(cs.paddingBottom) || 0;
        const usableH = elRect.height - padTop - padBottom;
        const slack = usableH - contentExtent;
        if (slack < 60) return;
        out.card_min_height_sparse.push({
          slide_idx,
          selector: shortSel(el),
          client_h: Math.round(elRect.height),
          content_extent: Math.round(contentExtent),
          usable_h: Math.round(usableH),
          slack: Math.round(slack),
          kid_count: kids.length,
          justify: jc,
          min_height: Math.round(minH),
        });
      });
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

    // ---- R-VIS-PEER-SIZE · 同角色并列 sibling 字号不一致 (2026-05-31) ----
    // P5:#4 「18 与 22 混」—— 同一并列容器内、语义角色相同(body/desc/feat-body…)
    // 的 sibling，computed font-size 应相等(容差 1px)。角色 token 必须字面相等
    // 才互比 —— 标题/eyebrow/不同角色本就该不同,零跨角色误报。豁免:hero/SVG/
    // mock/chrome/单元素组/data-allow-peer-size。
    if (!isHeroLayout) {
      const PEER_PARALLEL = new Set([
        'overview-grid', 'north-star-map', 'scene-grid', 'logo-wall',
        'verdict-grid', 'principle-band', 'kpi-strip', 'arch-stack',
        'arch-hands', 'pipeline', 'steps', 'pills', 'toc',
        'agenda-stack', 'todo-grid', 'dir-grid',
      ]);
      const ROLE_KEYS = [...BODY_KEYS, ...META_KEYS];
      const _cls = (el) => {
        const raw = el.className;
        return (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || '')).toString().toLowerCase();
      };
      // roleOf — three tiers, fine→coarse, picking "same role" without ever conflating
      // distinct roles:
      //   1. a KNOWN semantic keyword (body / desc / num / …) — schema behaviour, UNCHANGED.
      //   2. else the element's EXACT class signature (sorted class tokens). Two siblings
      //      that share the SAME class (even an arbitrary raw one like `zztext`) are the
      //      same role; a title vs its EN-subtitle vs a number — DIFFERENT classes — are
      //      NOT compared. This is the distinction the earlier `tag:div` fallback lost
      //      (it merged all <div> into one role → 8 false findings); exact class keeps
      //      them apart. Raw decks that label their peers with ANY consistent class are
      //      now covered; cross-class hierarchy is never flagged.
      //   3. else (no class at all) null — too ambiguous to assign a role geometrically.
      const roleOf = (el) => {
        const c = _cls(el);
        for (const k of ROLE_KEYS) if (c.includes(k)) return k;
        const sig = c.trim().split(/\s+/).filter(Boolean).sort().join('.');
        return sig || null;
      };
      // parallelAnchor: a known parallel / grid / card class first (schema, unchanged);
      // else the nearest flex / grid container (same geometry GUTTER uses) so raw peers in
      // an unnamed flex/grid row still anchor. Null only when no such container exists.
      const parallelAnchor = (el) => {
        for (let n = el.parentElement; n && n !== slide; n = n.parentElement) {
          const toks = _cls(n).split(/\s+/).filter(Boolean);
          if (toks.some(t => PEER_PARALLEL.has(t) || GRID_KEYS.includes(t) || CARD_KEYS.includes(t))) return n;
          if (CARD_SUFFIXES.some(suf => toks.some(t => t.endsWith(suf)))) return n;
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
      const anchorIds = new WeakMap(); let aSeq = 0;
      slide.querySelectorAll('*').forEach(el => {
        if (!hasOwnText(el)) return;
        if (el.ownerSVGElement || el.tagName === 'TEXT' || el.tagName === 'tspan') return;
        if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return;
        const role = roleOf(el); if (!role) return;
        let inMock = false;
        for (let n = el; n && n !== slide; n = n.parentElement) { if (hasAnyClass(n, TIER_MOCK)) { inMock = true; break; } }
        if (inMock || peerOptOut(el)) return;
        const anchor = parallelAnchor(el); if (!anchor) return;
        const cs = window.getComputedStyle(el);
        if (cs.visibility === 'hidden' || cs.display === 'none') return;
        const px = Math.round(parseFloat(cs.fontSize)); if (!px || px < 8) return;
        if (!anchorIds.has(anchor)) anchorIds.set(anchor, ++aSeq);
        const key = anchorIds.get(anchor) + ' ' + role;
        if (!groups.has(key)) groups.set(key, { anchor, role, items: [] });
        groups.get(key).items.push({ el, px });
      });
      for (const { anchor, role, items } of groups.values()) {
        if (items.length < 2) continue;
        const sizes = items.map(i => i.px);
        const minPx = Math.min(...sizes), maxPx = Math.max(...sizes);
        if (maxPx - minPx <= 1) continue;
        const tally = {}; sizes.forEach(s => { tally[s] = (tally[s] || 0) + 1; });
        const majorityPx = +Object.keys(tally).sort((a, b) => tally[b] - tally[a] || (+b) - (+a))[0];
        const offenders = items.filter(i => Math.abs(i.px - majorityPx) > 1);
        if (!offenders.length) continue;
        out.peer_size.push({
          slide_idx, container_sel: shortSel(anchor), role, majority_px: majorityPx,
          sizes: [...new Set(sizes)].sort((a, b) => a - b), count: items.length,
          offenders: offenders.slice(0, 4).map(o => ({ sel: shortSel(o.el), px: o.px })),
          lifted: offenders.some(o => !!o.el.closest('[data-lifted]')),
        });
      }
    }

    // ---- R-VIS-GUTTER · 同组相邻框间距不等 / 框内 padding 不一致 (2026-05-31) ----
    // P7:#3 卡片左右 28px 但到下面 strap 仅 8px;#4 同组 cell padding 不一致。
    // name-free 几何,双闸(max>min*1.8 且差>10px)滤掉均匀网格合法差与亚像素。
    // 豁免:hero / data-allow-imbalance / 媒体框 / <40px chrome / <3 同组框。
    if (!isHeroLayout && !slide.hasAttribute('data-allow-imbalance')) {
      const _vis = (el) => {
        const cs = getComputedStyle(el);
        return cs.display !== 'none' && cs.visibility !== 'hidden'
            && cs.position !== 'absolute' && cs.position !== 'fixed';
      };
      const _gutterSeen = new Set();
      slide.querySelectorAll('*').forEach(container => {
        const ccs = getComputedStyle(container);
        if (!['flex', 'inline-flex', 'grid', 'inline-grid'].includes(ccs.display)) return;
        const kids = [...container.children].filter(el => {
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return false;
          if (!_vis(el) || !_isFramedBox(el) || _isMediaBox(el)) return false;
          const r = el.getBoundingClientRect();
          return r.height > 40 * _scale && r.width > 40 * _scale;
        });
        if (kids.length < 3) return;
        const rects = kids.map(el => ({ el, r: el.getBoundingClientRect() }));
        const xs = rects.map(o => o.r.left + o.r.width / 2);
        const ys = rects.map(o => o.r.top + o.r.height / 2);
        const horizontal = (Math.max(...xs) - Math.min(...xs)) >= (Math.max(...ys) - Math.min(...ys));
        rects.sort((a, b) => horizontal ? (a.r.left - b.r.left) : (a.r.top - b.r.top));
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
              out.gutter.push({
                slide_idx, label, kind: 'gutter', container_sel: shortSel(container),
                axis: horizontal ? 'row' : 'column', gutters: gutters.map(g => Math.round(g)),
                min_px: Math.round(gmin), max_px: Math.round(gmax), count: kids.length,
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
          for (const el of group) {
            const cu = _contentUnion(el); if (!cu) { pads.length = 0; break; }
            const r = el.getBoundingClientRect();
            const pd = Math.min((cu.top - r.top), (r.bottom - cu.bottom)) / _scale;
            if (pd < -2) { pads.length = 0; break; }
            pads.push(Math.max(0, pd));
          }
          if (pads.length < 3) continue;
          const pmin = Math.min(...pads), pmax = Math.max(...pads);
          if (pmax > (pmin < 1 ? 1 : pmin) * 1.8 && (pmax - pmin) > 10) {
            const key = 'p::' + shortSel(container) + '::' + tag;
            if (!_gutterSeen.has(key)) {
              _gutterSeen.add(key);
              out.gutter.push({
                slide_idx, label, kind: 'padding', container_sel: shortSel(container),
                cell_tag: tag.toLowerCase(), pads: pads.map(p => Math.round(p)),
                min_px: Math.round(pmin), max_px: Math.round(pmax), count: group.length,
              });
            }
          }
        }
      });
    }

    // ---- R-VIS-HERO-FLOOR · hero 主元素字号下限 (2026-05-31) ----
    // 方向 = 尺寸下限,不是白名单(对比 R-VIS-TIER 只判 px 在不在 HERO_SIZES)。
    // P11:封面 82px < 100 master → "偏小、不够大气"。下限取 master-spec 的保守
    // 分数,只有真偏小才触发。font-size 不受 --fs-scale 影响,直接读 px。
    const HERO_FLOORS = {
      'cover':    [{ sel: 'h1.title, .title-zh, .cover-title, .cover-h1', floor: 88, role: '封面主标题', spec: 100 }],
      'section':  [{ sel: 'h2.title, .title-zh', floor: 72, role: '章节标题', spec: 88 },
                   { sel: '.chapter-num', floor: 112, role: '章节序号', spec: 160 }],
      'big-stat': [{ sel: '.num', floor: 168, role: '大数字', spec: 240 }],
      'stats':    [{ sel: '.col .num', floor: 92, role: '指标数字', spec: 132 }],
      'quote':    [{ sel: 'blockquote, .quote-body, .bq', floor: 56, role: '引言主体', spec: 88 }],
    };
    const KPI_FLOOR = { sel: '.kpi-val, .kpi .v, .metric-value', floor: 40, role: 'KPI 值', spec: 56 };
    const _heroFloorCheck = (specs) => {
      for (const { sel, floor, role, spec } of specs) {
        const cands = [...slide.querySelectorAll(sel)].filter(el => {
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return false;
          const r = el.getBoundingClientRect();
          if (r.width < 2 || r.height < 2) return false;
          for (let n = el; n && n !== slide; n = n.parentElement) if (hasAnyClass(n, TIER_MOCK)) return false;
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
          out.hero_floor.push({
            slide_idx, label, layout, role, selector: shortSel(best),
            rendered_px: bestPx, floor_px: floor, spec_px: spec,
            lifted: !!best.closest('[data-lifted]'),
          });
        }
      }
    };
    if (HERO_FLOORS[layout]) {
      _heroFloorCheck(HERO_FLOORS[layout]);
      // 2026-05-31 · raw coverage: an arbitrary-class hero (e.g. a raw slide that
      // declares a hero role via _orig_layout → data-layout=cover/section/...) is
      // missed by the class selectors above. If NONE of the layout's spec selectors
      // matched a visible element, fall back to the slide's LARGEST visible own-text
      // font vs the layout's SMALLEST floor — name-free element pick, still gated by
      // the hero layout token. (Undeclared data-layout="raw" has no HERO_FLOORS entry
      // → still skipped: a raw slide with no declared role is not a known hero, so
      // its largest font must not be judged against a hero floor.)
      const _specs = HERO_FLOORS[layout];
      const _classHit = _specs.some(s => [...slide.querySelectorAll(s.sel)].some(el => {
        const cs = getComputedStyle(el);
        if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return false;
        const r = el.getBoundingClientRect();
        return r.width >= 2 && r.height >= 2;
      }));
      if (!_classHit) {
        const _minFloor = Math.min(..._specs.map(s => s.floor));
        let _best = null, _bestPx = -1;
        slide.querySelectorAll('*').forEach(el => {
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return;
          if (!hasOwnText(el)) return;
          for (let n = el; n && n !== slide; n = n.parentElement) if (hasAnyClass(n, TIER_MOCK)) return;
          for (let n = el; n; n = n.parentElement) if (n.dataset && n.dataset.allowTypescale != null) return;
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return;
          const r = el.getBoundingClientRect();
          if (r.width < 2 || r.height < 2) return;
          const px = Math.round(parseFloat(cs.fontSize));
          if (px > _bestPx) { _bestPx = px; _best = el; }
        });
        if (_best && _bestPx > 0 && _bestPx < _minFloor) {
          out.hero_floor.push({
            slide_idx, label, layout, role: 'hero 主元素 (name-free)', selector: shortSel(_best),
            rendered_px: _bestPx, floor_px: _minFloor, spec_px: _minFloor,
            lifted: !!_best.closest('[data-lifted]'),
          });
        }
      }
    }
    _heroFloorCheck([KPI_FLOOR]);

    // ---- R-VIS-SHORT-LABEL-FLOOR · 1–7 字短标签 / SVG 轴标 < 18px (2026-05-31) ----
    // R-VIS-BODY-FLOOR 有 directText.length<8 → return 门槛(豁免图标/单位/短数字),
    // 不能删;但它放过了图表轴标 / 短分类标签(1–7 字,投影看不清)。这条补缝,
    // 并专门下钻 SVG <text>/<tspan>(其他所有渲染检查都跳过 SVG 轴标)。
    // computed < 18px → WARN。自带 chrome/mock 正则(避免依赖块内常量)。
    const SHORT_FLOOR = 18;
    const _SL_CHROME = /(^|[\s-])(eyebrow|kicker|pill|tag|chip|badge|source|pageno|footnote|attrib|copyright|wordmark|unit|legend)([\s-]|$)/i;
    const _SL_MOCK = /(mock|phone|screen|device|chat|im-|app-ui|pd-card|doc-frame)/i;
    const _slClass = (el) => { const r = el.className; return (r && r.baseVal !== undefined ? r.baseVal : (r || '')).toString(); };
    const seenShortLabel = new Set();
    if (!isHeroLayout) {
      slide.querySelectorAll('*, text, tspan').forEach(el => {
        if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return;
        if (!hasOwnText(el)) return;
        const isSvgText = !!el.ownerSVGElement || el.tagName === 'text' || el.tagName === 'TEXT' || el.tagName === 'tspan';
        const px = Math.round(parseFloat(getComputedStyle(el).fontSize) || 0);
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
        let skip = false;
        for (let n = el; n && n !== slide; n = n.parentElement) {
          if (n !== el && (_SL_MOCK.test(_slClass(n)) || _isMediaBox(n))) { skip = true; break; }
          if (n.dataset && n.dataset.allowBodyFloor != null) { skip = true; break; }
        }
        if (skip) return;
        const sel = shortSel(el);
        const key = slide_idx + '::' + sel + '::' + px;
        if (seenShortLabel.has(key)) return;
        seenShortLabel.add(key);
        out.short_label_floor.push({
          slide_idx, selector: sel, rendered_px: px, char_count: len, is_svg: isSvgText,
          text: directText.length > 16 ? directText.slice(0, 16) + '…' : directText,
          lifted: !!(el.closest && el.closest('[data-lifted]')),
        });
      });
    }
  });

  return out;
}
