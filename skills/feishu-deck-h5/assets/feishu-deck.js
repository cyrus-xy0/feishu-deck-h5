/* ============================================================================
   feishu-deck-h5 · runtime
   - Scale-to-fit each .slide to its frame (1920×1080 design canvas)
   - Auto-detect mobile / narrow viewport → scroll mode (vertical card stack)
   - Desktop default → present mode (one slide per viewport, ←/→/space, wheel)
   - Keyboard: ←/→/PgUp/PgDn/Space/Home/End  ·  URL hash sync (#3)
   - Mode toggle button: 演示 ↔ 浏览  (entering 演示 also requests fullscreen)
   - F-key + bottom button: fullscreen toggle
   - Auto-fade chrome after 2.5s idle (mousemove throttled to 100ms)
   - All listeners bound through a single AbortController → clean destroy()
   - Single document-level ResizeObserver (was 1 per frame)
   ============================================================================ */
(function () {
  'use strict';

  const DESIGN_W = 1920;
  const DESIGN_H = 1080;
  const MOBILE_BREAKPOINT = 900;
  const MODE_KEY  = 'fs-deck-mode';
  const IDLE_MS   = 2500;
  const NUDGE_THROTTLE_MS = 100;
  const FS_REFIT_DEBOUNCE = 80;

  let activeController = null;       // tracks the current init's AbortController

  // ============================================================
  // Runtime auto-balance (2026-05-30): after scale-to-fit, geometrically fix
  // mis-distributed boxes so RAW / legacy decks (which bypass the schema
  // correct-by-construction defaults) come out balanced ON LOAD — not
  // detected-then-fixed. name-free / geometric (no layout-name whitelist).
  //  · measurement-gated: only touches slides that actually measure crowded.
  //  · apply-measure-keep-or-revert: a correction is kept ONLY if it reduces
  //    crowding without introducing new canvas overflow → never makes a slide
  //    worse (genuinely over-full boxes, e.g. content 161px too tall, revert).
  //  · skips hero layouts, [data-allow-imbalance], [data-no-autobalance] decks.
  //  · when slides are laid out (measured 2026-06-10): in present mode ALL
  //    frames are stacked at `position:absolute; inset:0` (only opacity/
  //    content-visibility differ), so the single init pass (below) already
  //    measures + balances EVERY frame whose content `content-visibility:auto`
  //    actually laid out — which, being in-viewport, is most of them, not just
  //    the current one (observed 10/13 on sample-deck at init). The is-current
  //    observer is a RETRY channel, not the primary path: it re-balances only
  //    the few frames whose content content-visibility happened to skip at init
  //    (probe height 0 → maybeBalance bailed, left untagged for the retry).
  //  · NO new ResizeObserver / addEventListener — stays within P52/P53 budget.
  // ============================================================
  const HERO_AB = new Set(['cover', 'section', 'big-stat', 'quote', 'image-text', 'end']);
  const _abHasText = (el) => {
    for (const n of el.childNodes) if (n.nodeType === 3 && n.textContent.trim()) return true;
    return false;
  };
  const _abTextUnion = (root) => {
    let t = Infinity, b = -Infinity, any = false;
    root.querySelectorAll('*').forEach((el) => {
      if (/^(SVG|svg|SCRIPT|STYLE)$/.test(el.tagName) || !_abHasText(el)) return;
      const cs = getComputedStyle(el);
      if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) return;
      const r = el.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return;
      any = true; t = Math.min(t, r.top); b = Math.max(b, r.bottom);
    });
    return any ? { top: t, bottom: b } : null;
  };
  const _abFramed = (el) => {
    const cs = getComputedStyle(el);
    const border = ['Top', 'Right', 'Bottom', 'Left'].some((s) =>
      parseFloat(cs['border' + s + 'Width'] || 0) > 0 &&
      !/transparent|rgba\(0, 0, 0, 0\)/.test(cs['border' + s + 'Color']));
    const bg = cs.backgroundColor && !/transparent|rgba\(0, 0, 0, 0\)/.test(cs.backgroundColor);
    const bgi = cs.backgroundImage && cs.backgroundImage !== 'none';
    return border || bg || bgi;
  };
  const _abMedia = (el) => {
    const cs = getComputedStyle(el);
    if (cs.backgroundImage && cs.backgroundImage !== 'none' && !/gradient/i.test(cs.backgroundImage)) return true;
    if (el.querySelector('img,iframe,canvas,video,picture')) return true;
    const raw = el.className, c = (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || '')).toString();
    return /\b(photo|image|img|visual|mock|thumb|avatar|portrait|media|phone|screen)\b/i.test(c);
  };
  // Per-slide measurement: crowd severity (framed box text jammed against its
  // bottom edge) + spill (how far any framed box bottom passes the slide edge).
  function _abMeasure(slide) {
    const scale = parseFloat(getComputedStyle(slide).getPropertyValue('--fs-scale')) || 1;
    const sb = slide.getBoundingClientRect().bottom;
    const all = [...slide.querySelectorAll('*')].filter((el) =>
      _abFramed(el) && !_abMedia(el) && el.getBoundingClientRect().height > 80 * scale);
    const boxes = all.filter((el) => !all.some((o) => o !== el && o.contains(el)));
    let severity = 0, spill = 0, overflow = 0; const crowded = [], overflowed = [];
    for (const box of boxes) {
      const r = box.getBoundingClientRect();
      spill = Math.max(spill, (r.bottom - sb) / scale);
      const cu = _abTextUnion(box); if (!cu) continue;
      const distTop = (cu.top - r.top) / scale, distBottom = (r.bottom - cu.bottom) / scale;
      // 文字溢出框底(distBottom<0)= grow-box 的对象:框被写死/挤扁,内容掉出去。
      if (distBottom < -1) { overflow += (-distBottom); overflowed.push([box, -distBottom]); }
      if (distBottom < 10 && distTop > distBottom + 16) { crowded.push(box); severity += (16 - distBottom); }
    }
    return { severity, spill, overflow, crowded, overflowed };
  }
  // HARD RULE (death rule): auto-balance must NEVER move a content-page title
  // or subtitle. These positions are snapshotted before any correction and
  // re-checked after — if a correction shifts ANY of them, the whole slide is
  // reverted. Belt: corrections only un-stretch the crowded box's FRAMED peers,
  // never title/non-box siblings.
  const _abTitleEls = (slide) => [...slide.querySelectorAll(
    '.header, .title-zh, .title-en, .subtitle, .eyebrow, .kicker, ' +
    '.header h1, .header h2, .header h3')];

  function balanceSlide(slide) {
    const layout = slide.getAttribute('data-layout') || '';
    if (HERO_AB.has(layout) || slide.hasAttribute('data-allow-imbalance')) return;
    const before = _abMeasure(slide);
    if (before.severity === 0 && before.overflow === 0) return;  // balanced → no-op (schema decks)
    // Snapshot title/subtitle positions — they may not move (hard rule).
    const titleSnap = _abTitleEls(slide).map((el) => {
      const r = el.getBoundingClientRect(); return [el, r.top, r.left];
    });
    // Correction: un-stretch the crowded box's FRAMED peers only (content-sized
    // + shared centerline; never a title/other sibling) + center content
    // vertically inside flex-column boxes — the content-3up fix on raw geometry.
    const touched = [];
    const rows = new Set();
    before.crowded.forEach((box) => { if (box.parentElement) rows.add(box.parentElement); });
    rows.forEach((p) => {
      for (const ch of p.children) {
        if (ch.nodeType !== 1 || !_abFramed(ch) || _abMedia(ch)) continue;  // peers only
        touched.push([ch, 'alignSelf', ch.style.alignSelf]);
        ch.style.alignSelf = 'center';
      }
    });
    before.crowded.forEach((box) => {
      const cs = getComputedStyle(box);
      if (cs.display.indexOf('flex') >= 0 && cs.flexDirection.indexOf('column') === 0) {
        touched.push([box, 'justifyContent', box.style.justifyContent]);
        box.style.justifyContent = 'center';
      }
      // A common imported/raw failure is a fixed-height card with asymmetric
      // padding (e.g. 70px top / 3px bottom) plus flex-end. Merely changing
      // justify-content cannot center the visible text because the content box
      // itself is biased downward. Shift padding budget from top to bottom while
      // keeping total vertical padding constant, then let measure-or-revert prove
      // the crowd got better without moving titles or spilling the canvas.
      const cu = _abTextUnion(box);
      if (cu) {
        const scale = parseFloat(getComputedStyle(slide).getPropertyValue('--fs-scale')) || 1;
        const r = box.getBoundingClientRect();
        const distTop = (cu.top - r.top) / scale;
        const distBottom = (r.bottom - cu.bottom) / scale;
        if (distBottom < 10 && distTop > distBottom + 16) {
          const pt = parseFloat(cs.paddingTop) || 0;
          const pb = parseFloat(cs.paddingBottom) || 0;
          const move = Math.min((distTop - distBottom) / 2, Math.max(0, pt - 12));
          if (move > 1) {
            touched.push([box, 'paddingTop', box.style.paddingTop]);
            touched.push([box, 'paddingBottom', box.style.paddingBottom]);
            box.style.paddingTop = Math.round(pt - move) + 'px';
            box.style.paddingBottom = Math.round(pb + move) + 'px';
          }
        }
      }
    });
    // GROW-BOX (2026-05-31): a box whose text overflows its bottom (written-in /
    // squeezed-flat height) → raise its min-height to contain the content (the
    // runtime version of grow-box-fit's 拉高框). We grow OPTIMISTICALLY here;
    // the measure-or-revert guard below is the safety net — if growing pushes
    // the slide past its edge (no canvas room) or moves the title, the whole
    // thing reverts (incl. these min-heights). Never shrinks; never touches fonts.
    const scaleAB = parseFloat(getComputedStyle(slide).getPropertyValue('--fs-scale')) || 1;
    before.overflowed.forEach(([box, over]) => {
      const r = box.getBoundingClientRect();
      touched.push([box, 'minHeight', box.style.minHeight]);
      box.style.minHeight = Math.ceil(r.height / scaleAB + over + 6) + 'px';
    });
    const after = _abMeasure(slide);
    const titleMoved = titleSnap.some(([el, t, l]) => {
      const r = el.getBoundingClientRect();
      return Math.abs(r.top - t) > 1 || Math.abs(r.left - l) > 1;
    });
    // Keep if EITHER crowd OR overflow got meaningfully better, AND neither got
    // worse, AND no new canvas spill, AND the title didn't move (death rule).
    const crowdBetter = after.severity < before.severity - 0.5;
    const overflowBetter = after.overflow < before.overflow - 2;
    const improved = (crowdBetter || overflowBetter) &&
                     after.severity <= before.severity + 0.5 &&
                     after.overflow <= before.overflow + 2 &&
                     after.spill <= Math.max(before.spill, 2) && !titleMoved;
    if (improved) {
      slide.setAttribute('data-fs-autobalanced', '');
    } else {
      for (const [el, prop, val] of touched) el.style[prop] = val || '';  // incl. title-moved revert
    }
  }
  // ---- R-VIS-CANVAS-CENTER runtime fix (2026-05-31): vertically center the content
  //      UNION inside the visual canvas [main-title bottom → 1080], not inside the .stage
  //      box. .stage is often anchored symmetrically (top:200/bottom:200 → center 540)
  //      while the canvas center is ~597 once the title eats the top → content reads 偏上
  //      by a per-page amount. Mechanism = TRANSLATE the band: top += off, bottom -= off.
  //      Same height, so it is (a) immune to flex:1 children absorbing extra space (the
  //      trap that hollowed out justify-content in the earlier attempt), and (b) sets
  //      top/bottom — not transform — so it COMPOSES with the fs-reveal entrance transform
  //      instead of being overridden by it. Measured AFTER entrance animations settle
  //      (transform → identity), else the union reads mid-animation. Geometry mirrors the
  //      validate.py / visual-audit.js R-VIS-CANVAS-CENTER detector.
  const _ccMeasure = (slide) => {
    const sr = slide.getBoundingClientRect();
    const scale = sr.height / 1080;
    if (scale < 0.01) return null;
    const top0 = sr.top;
    const header = slide.querySelector(':scope > .header');
    const hb = (header && header.getClientRects().length)
      ? (header.getBoundingClientRect().bottom - top0) / scale : 0;
    let t = Infinity, b = -Infinity, any = false;
    slide.querySelectorAll('*').forEach((el) => {
      if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return;
      if (header && (el === header || header.contains(el))) return;
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return;
      if (cs.position === 'absolute' || cs.position === 'fixed') {
        // Skip structural/chrome (.stage / header / wordmark) and decorative
        // absolute layers — but INCLUDE an absolutely-positioned CONTENT BAND
        // (a DIRECT child of .slide, i.e. a sibling of .stage, that bears text),
        // else the runtime centers the in-flow content right UNDER it
        // (R-VIS-BAND-COLLIDE root). Deliberately narrow: ONLY that exact band
        // shape is newly measured — chrome, decorative layers, and deeper
        // absolute labels stay skipped, so normal decks are unaffected.
        const isBand = el.parentElement === slide && _abHasText(el)
          && !el.classList.contains('stage')
          && !el.classList.contains('header')
          && !el.classList.contains('wordmark');
        if (!isBand) return;
      }
      const tag = el.tagName;
      const isMedia = tag === 'IMG' || tag === 'SVG' || tag === 'svg' || tag === 'CANVAS' || tag === 'VIDEO';
      if (!_abHasText(el) && !isMedia && el.children.length) return;            // empty wrappers don't count
      const r = el.getBoundingClientRect();
      if (r.width < 6 || r.height < 6) return;
      // Clamp to clipping ancestors — content clipped away by an overflow:hidden
      // ancestor (phone-mock chat taller than its frame, input bar below the clip)
      // is invisible; counting it skews the union. Intersect with each clipping box.
      let vt = r.top, vb = r.bottom;
      for (let p = el.parentElement; p && p !== slide; p = p.parentElement) {
        if (getComputedStyle(p).overflowY !== 'visible') {
          const pr = p.getBoundingClientRect();
          if (pr.top > vt) vt = pr.top;
          if (pr.bottom < vb) vb = pr.bottom;
        }
      }
      if (vb - vt < 6) return;
      t = Math.min(t, (vt - top0) / scale);
      b = Math.max(b, (vb - top0) / scale);
      any = true;
    });
    if (!any) return null;
    const canvasMid = (hb + 1080) / 2;
    return { offset: canvasMid - (t + b) / 2, hb, ccTop: t, ccBot: b, contentH: b - t, bandH: 1080 - hb };
  };
  function _ccApply(slide) {
    const layout = slide.getAttribute('data-layout') || '';
    // F-301 · re-true the band anchor now that entrance animations have settled
    // (centerSlideInCanvas defers to this point): the maybeBalance-time measure
    // can catch the header mid-reveal (translateY in flight → bbox ~10px low).
    // Idempotent, runs even for hero/opted-out slides — the stage anchor must be
    // right regardless of whether the centering pass below is allowed to act.
    try { setBandAnchor(slide); } catch (e) { /* best-effort */ }
    if (HERO_AB.has(layout) || slide.hasAttribute('data-allow-imbalance')) return;
    if (slide.getBoundingClientRect().height < 30) return;          // not laid out / navigated away
    const m = _ccMeasure(slide);
    if (!m || m.hb < 40) return;                                    // header-bearing content pages only
    if (Math.abs(m.offset) <= 12) return;                           // sub-perceptual → leave it
    if (m.contentH > m.bandH - 8) return;                           // can't fit when centered → genuinely full
    let el = null;
    for (const sel of [':scope > .stage', ':scope > .grid', ':scope > .flow',
                       ':scope > .nodes', ':scope > .toc', ':scope > .table-wrap']) {
      const c = slide.querySelector(sel); if (c) { el = c; break; }
    }
    if (!el) return;
    const cs = getComputedStyle(el);
    if (cs.position !== 'absolute' && cs.position !== 'fixed') return;          // band must be positioned
    const top = parseFloat(cs.top), bot = parseFloat(cs.bottom);
    if (!isFinite(top) || !isFinite(bot)) return;
    const off = Math.round(m.offset);
    // Container-fit gate: only band-translate if the band CONTAINER itself stays on-canvas
    // after the shift (top inset / bottom inset = how far it can move up / down before an
    // edge leaves the canvas). If the shift would push it off, the container is already
    // canvas-filling and the offset is an INTERNAL top-alignment issue (content top-aligned
    // in a tall container — R-VIS-BALANCE / justify-content territory), NOT a container
    // mis-anchor. Translating it would just spill it off the edge (e.g. a top-aligned table
    // in a 770px box). Skip — band-translate is only for mis-anchored containers (the
    // symmetric .stage [200,880] case), where there is slack on both sides.
    if (off > 0 ? off > bot - 4 : -off > top - 4) return;
    // Death rule, scoped for a whole-block translate: protect only titles OUTSIDE the
    // translated band — the page header/title at the top must never move. A subtitle or
    // label that lives INSIDE the band is content: it rides the block down as one unit
    // (relative position preserved), which is exactly what centering should do. (The crowd
    // pass protects in-box subtitles because it un-stretches peers; here nothing is
    // displaced relative to the content — the entire composition shifts together.)
    const titleSnap = _abTitleEls(slide).filter((t) => !el.contains(t))
      .map((t) => { const r = t.getBoundingClientRect(); return [t, r.top, r.left]; });
    const pTop = el.style.top, pBot = el.style.bottom;
    el.style.setProperty('top', Math.round(top + off) + 'px', 'important');
    el.style.setProperty('bottom', Math.round(bot - off) + 'px', 'important');
    const after = _ccMeasure(slide);
    const titleMoved = titleSnap.some(([t, y, x]) => {
      const r = t.getBoundingClientRect(); return Math.abs(r.top - y) > 1 || Math.abs(r.left - x) > 1;
    });
    const ok = after && Math.abs(after.offset) < Math.abs(m.offset) - 2 &&
               after.ccTop > m.hb - 6 && after.ccBot < 1080 - 4 && !titleMoved;
    if (ok) slide.setAttribute('data-fs-canvascentered', '');
    else { el.style.top = pTop; el.style.bottom = pBot; }           // measure-or-revert
  }
  // Defer until entrance animations settle (transform back to identity), then apply once.
  function centerSlideInCanvas(slide) {
    const anims = (slide.getAnimations ? slide.getAnimations({ subtree: true }) : []).filter((a) => {
      try { return a.effect.getComputedTiming().iterations !== Infinity; } catch (e) { return false; }
    });
    if (!anims.length) { try { _ccApply(slide); } catch (e) { /* best-effort */ } return; }
    let done = false;
    const go = () => { if (done) return; done = true; try { _ccApply(slide); } catch (e) { /* best-effort */ } };
    Promise.all(anims.map((a) => a.finished.catch(() => {}))).then(go);
    setTimeout(go, 1200);                                           // hard cap if an animation never resolves
  }
  // ---- Letterboxed-image unit fix (2026-05-31): the "差得多→分别居中" branch for media
  //      columns. A column whose media is a `background-size:contain` image sits
  //      letterboxed in a fixed-height frame (flex:1 / min-height:720), so its label
  //      floats ABOVE the image (detached) and the image reads shorter than a sibling
  //      column. Size the frame to the IMAGE's own aspect ratio → the label rides
  //      directly on the photo as one tight unit → the cell's centering then centers
  //      that unit. Only fires when the image is meaningfully letterboxed vertically
  //      (>18% slack); a small letterbox is left to the whole-block pass ("差不多→整体
  //      对齐"). Flow columns already center via align-items — this is only for the
  //      contain-image case that align-items can't reach. Runs BEFORE canvas-center so
  //      the block pass measures the tightened, internally-balanced columns.
  const _ccImageFrames = (slide) => {
    const out = [];
    slide.querySelectorAll('*').forEach((el) => {
      const cs = getComputedStyle(el);
      if (cs.backgroundSize !== 'contain') return;
      const m = cs.backgroundImage && cs.backgroundImage.match(/url\(["']?(.*?)["']?\)/);
      if (m) out.push({ el, url: m[1] });
    });
    return out;
  };
  function balanceColumns(slide) {
    const layout = slide.getAttribute('data-layout') || '';
    if (HERO_AB.has(layout) || slide.hasAttribute('data-allow-imbalance')) return Promise.resolve();
    const frames = _ccImageFrames(slide);
    if (!frames.length) return Promise.resolve();
    const sc = (slide.getBoundingClientRect().height / 1080) || 1;
    return Promise.all(frames.map(({ el, url }) => new Promise((resolve) => {
      const r = el.getBoundingClientRect();
      const frameW = r.width / sc, frameH = r.height / sc;
      if (frameW < 40 || frameH < 40) return resolve();
      const im = new Image();
      im.onerror = () => resolve();
      im.onload = () => {
        const ar = im.naturalWidth / im.naturalHeight;
        if (!ar || ar <= frameW / frameH) return resolve();          // not wider than frame → no vertical letterbox
        const containedH = frameW / ar;                              // image's rendered height in the frame
        if (containedH >= frameH * 0.82) return resolve();           // <18% slack → 差不多 → leave for block pass
        const cell = el.parentElement;
        const prev = [el.style.flex, el.style.minHeight, el.style.height, el.style.aspectRatio,
                      el.style.width, el.style.backgroundSize, el.style.maxHeight,
                      cell && cell.style.justifyContent];
        el.style.setProperty('flex', '0 0 auto', 'important');
        el.style.setProperty('min-height', '0', 'important');
        el.style.setProperty('height', 'auto', 'important');
        el.style.setProperty('aspect-ratio', im.naturalWidth + '/' + im.naturalHeight);
        el.style.setProperty('width', '100%', 'important');
        el.style.setProperty('background-size', 'cover', 'important');
        el.style.setProperty('max-height', Math.round(frameH) + 'px', 'important');
        if (cell) cell.style.setProperty('justify-content', 'center', 'important');
        if (el.getBoundingClientRect().height / sc > frameH - 6) {   // didn't actually tighten → revert
          el.style.flex = prev[0]; el.style.minHeight = prev[1]; el.style.height = prev[2];
          el.style.aspectRatio = prev[3]; el.style.width = prev[4]; el.style.backgroundSize = prev[5];
          el.style.maxHeight = prev[6]; if (cell) cell.style.justifyContent = prev[7] || '';
        } else {
          slide.setAttribute('data-fs-colbalanced', '');
        }
        resolve();
      };
      im.src = url;
    })));
  }
  // F-301 · subtitle-aware band anchor: measure the rendered `.header` bbox
  // bottom (design px — the bbox encloses any .page-sub subtitle) into the
  // slide's `--fs-band-bottom` custom property. The framework `.stage` rule
  // derives its `top` from this var (top = band bottom + 56, see
  // feishu-deck.css), so the body band starts below the REAL title band
  // (title + subtitle) instead of an assumed main-title-only height. Runs
  // before balanceSlide so every later measure/center pass (balance, columns,
  // canvas-center, audits) sees the final stage geometry; re-applied on
  // fonts.ready because a late font swap can rewrap the title. Idempotent and
  // write-only-on-change, so re-running never invalidates applied fixes.
  function setBandAnchor(slide) {
    if (!slide) return;
    const header = slide.querySelector(':scope > .header');
    if (!header || !header.getClientRects().length) return;
    const sr = slide.getBoundingClientRect();
    if (sr.height < 30) return;                           // not laid out
    const hb = (header.getBoundingClientRect().bottom - sr.top) / (sr.height / 1080);
    if (!(hb > 40 && hb < 420)) return;                   // degenerate/hero header → keep fallback
    const v = Math.round(hb) + 'px';
    if (slide.style.getPropertyValue('--fs-band-bottom') !== v) {
      slide.style.setProperty('--fs-band-bottom', v);
    }
  }
  function maybeBalance(slide) {
    if (!slide || slide.hasAttribute('data-fs-balanced')) return;
    const deck = slide.closest('.deck');
    if (deck && deck.hasAttribute('data-no-autobalance')) return;
    // In present mode frames are stacked at inset:0, but content-visibility:auto
    // can still skip layout for a frame the browser deems not-yet-relevant → its
    // content measures 0. Only tag+balance once a content container is actually
    // laid out (non-zero height); otherwise leave untagged so the is-current
    // observer retries when the frame becomes current (measured 2026-06-10: at
    // init most frames already measure laid-out and get balanced here; only the
    // few content-visibility skipped fall through to that retry).
    const probe = slide.querySelector('.stage, .grid, .flow, .nodes, .toc, .stack, .header, [class*="card"]');
    if (!probe || probe.getBoundingClientRect().height < 30) return;
    slide.setAttribute('data-fs-balanced', '');
    try { setBandAnchor(slide); } catch (e) { /* never break the deck over layout */ }
    try { balanceSlide(slide); } catch (e) { /* never break the deck over layout */ }
    // columns first (tightens letterboxed media → internally-balanced cols), then the
    // whole-block canvas-center on the tightened layout. balanceColumns resolves after
    // any image loads (or immediately when there are none).
    balanceColumns(slide)
      .catch(() => {})
      .then(() => { try { centerSlideInCanvas(slide); } catch (e) { /* best-effort */ } });
  }

  // F-344 · Letterbox seam auto-fix. Lifted/raw pages often carry a full-slide
  // opaque background panel of their own (e.g. .qilu-page / .source-frame-wrap /
  // .ppt-stage / .slide65-redo) that paints EITHER the framework content-bg image
  // (cropped to the 16:9 .slide) OR a flat dark solid, CONFINED to the slide. In
  // present mode the .slide-frame paints that SAME content-bg across the WHOLE
  // frame — incl. the top/bottom letterbox — and .slide is transparent (F-318); but
  // the child panel re-covers the slide area at a DIFFERENT crop / flat tone, so a
  // luma seam shows at the slide↔letterbox boundary on any non-16:9 viewport
  // ("黑边"). We tag such panels so the stylesheet can drop their redundant backdrop
  // (keeping decorative gradient glows) and let the frame's seamless content-bg show
  // through. Coverage is a viewport-independent ratio, so one pass per slide is
  // enough; it rides alongside maybeBalance (init pass + is-current retry) → no new
  // observer, no extra reflow beyond what maybeBalance already forced. The visual
  // effect is gated to present mode in CSS (.fs-bleed-panel), so scroll mode — which
  // has no letterbox and no frame content-bg fill — is untouched.
  function markBleedPanels(slide) {
    if (!slide || slide.hasAttribute('data-fs-bleed-checked')) return;
    const layout = slide.getAttribute('data-layout');
    if (layout !== 'raw' && layout !== 'iframe-embed' && layout !== 'canvas') return;
    const sr = slide.getBoundingClientRect();
    const sArea = sr.width * sr.height;
    if (sArea < 900) return;                   // not laid out yet — observer will retry
    slide.setAttribute('data-fs-bleed-checked', '');
    // The frame's content-bg url is the seamless backdrop panels should defer to.
    let frameUrl = '';
    const frame = slide.closest('.slide-frame');
    if (frame) {
      const fm = getComputedStyle(frame).backgroundImage.match(/url\((["']?)(.*?)\1\)/);
      if (fm) frameUrl = fm[2];
    }
    const splitLayers = (s) => {               // top-level comma split (paren-aware)
      const out = []; let depth = 0, cur = '';
      for (let k = 0; k < s.length; k++) {
        const ch = s[k];
        if (ch === '(') depth++; else if (ch === ')') depth--;
        if (ch === ',' && depth === 0) { out.push(cur.trim()); cur = ''; } else cur += ch;
      }
      if (cur.trim()) out.push(cur.trim());
      return out;
    };
    slide.querySelectorAll('*').forEach((el) => {
      if (el.classList.contains('fs-bleed-panel')) return;
      const r = el.getBoundingClientRect();
      if ((r.width * r.height) / sArea < 0.95) return;     // must blanket the slide
      const cs = getComputedStyle(el);
      const bi = cs.backgroundImage;
      const layers = (bi && bi !== 'none') ? splitLayers(bi) : [];
      const hasFrameBg = !!frameUrl && layers.some((l) => l.indexOf('url(') >= 0 && l.indexOf(frameUrl) >= 0);
      let darkSolid = false;                   // opaque dark solid backdrop?
      const cm = cs.backgroundColor.match(/rgba?\(([^)]+)\)/);
      if (cm) {
        const p = cm[1].split(',').map(parseFloat);
        const a = p.length > 3 ? p[3] : 1;
        if (a >= 0.9 && (p[0] + p[1] + p[2]) / 3 < 70) darkSolid = true;
      }
      if (!hasFrameBg && !darkSolid) return;   // leave hero photos / light panels alone
      // Keep gradient layers + any NON-content-bg url (hero); drop only the redundant
      // frame content-bg url, and flatten the dark solid to transparent.
      const keep = layers.filter((l) => l.indexOf('gradient') >= 0
        || (l.indexOf('url(') >= 0 && (!frameUrl || l.indexOf(frameUrl) < 0)));
      el.style.setProperty('--fs-bleed-grads', keep.length ? keep.join(', ') : 'none');
      el.classList.add('fs-bleed-panel');
    });
  }

  function init() {
    const deck = document.querySelector('.deck');
    if (!deck) return null;

    // If a previous init is still alive, destroy it first (idempotent)
    if (activeController) activeController.abort();
    activeController = new AbortController();
    const signal = activeController.signal;

    // ---- Resolve mode (cache localStorage value at init only — no IO in hot path) ----
    const url = new URL(location.href);
    const queryMode = url.searchParams.get('mode');
    let storedMode = null;
    try { storedMode = localStorage.getItem(MODE_KEY); } catch (e) { /* private/blocked */ }
    const auto = window.matchMedia('(max-width: ' + MOBILE_BREAKPOINT + 'px)').matches
                   ? 'scroll' : 'present';
    setMode(deck, queryMode || storedMode || auto);

    // ---- Build UI overlay ----
    // Aborting the old controller (above) detaches its listeners but does NOT
    // remove the .deck-ui node it appended; a re-run of init() would otherwise
    // leave a duplicate, partly-dead control bar. Remove any prior overlay first.
    document.querySelectorAll('.deck-ui').forEach((el) => {
      if (el.parentNode) el.parentNode.removeChild(el);
    });
    const ui = buildUI();
    document.body.appendChild(ui);

    // ---- Set up frames + reveal-animation child indices ----
    const frames = Array.from(deck.querySelectorAll('.slide-frame'));
    frames.forEach((frame, i) => {
      frame.dataset.idx = String(i);
      const slide = frame.querySelector('.slide');
      if (!slide) return;
      // (Per-slide .footer/.pageno retired 2026-05 — pager UI in present
      //  mode shows the page number; no per-slide DOM read needed.)
      // Reveal animation: assign --child-i 1..N to direct children for staggered delay
      Array.prototype.forEach.call(slide.children, (child, idx) => {
        child.style.setProperty('--child-i', String(Math.min(idx + 1, 7)));
      });
      // Click-to-present in scroll mode
      frame.addEventListener('click', () => {
        if (deck.dataset.mode === 'scroll') goTo(deck, frames, i, true);
      }, { signal });
    });

    // ---- Single document-level ResizeObserver (was 1 per frame = 12) ----
    let pendingRefit = false;
    const ro = new ResizeObserver(() => {
      if (pendingRefit) return;
      pendingRefit = true;
      requestAnimationFrame(() => {
        pendingRefit = false;
        frames.forEach(scaleFrame);
      });
    });
    ro.observe(document.documentElement);
    signal.addEventListener('abort', () => ro.disconnect());
    frames.forEach(scaleFrame);   // initial scale

    // ---- Presenter mode (speaker view + projector-window follow) ----
    setupPresenter(deck, frames, signal);

    // ---- Keyboard nav (present mode) + F = fullscreen (any mode) ----
    document.addEventListener('keydown', (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (isTypingTarget(e.target)) return;
      if (e.key === 'f' || e.key === 'F') {
        e.preventDefault(); toggleFullscreen(); nudgeIdle(); return;
      }
      if (e.key === 'p' || e.key === 'P') {
        e.preventDefault();
        if (typeof window.__fsTogglePresenter === 'function') window.__fsTogglePresenter();
        return;
      }
      if (deck.dataset.mode !== 'present') return;
      const cur = currentIdx(frames);
      switch (e.key) {
        // Next-slide aliases. Covers standard keyboards + most presentation
        // clickers, including Windows-market models that emit ArrowDown/Up
        // (Targus / Kensington Expert / DinoFire / 一拓 / Aibatu) and ones
        // that map "advance" to Enter.
        case 'ArrowRight': case 'ArrowDown': case 'PageDown':
        case ' ': case 'Spacebar': case 'Enter':
          e.preventDefault(); goTo(deck, frames, stepNext(frames, cur)); break;
        case 'ArrowLeft': case 'ArrowUp': case 'PageUp':
        case 'Backspace':
          e.preventDefault(); goTo(deck, frames, stepPrev(frames, cur)); break;
        case 'Home':
          e.preventDefault(); goTo(deck, frames, firstVisible(frames)); break;
        case 'End':
          e.preventDefault(); goTo(deck, frames, lastVisible(frames)); break;
        case 'Escape':
          if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
          else osFsHint(); // F-305: Esc can't reach OS-level fullscreen — guide instead
          break;
      }
      nudgeIdle();
    }, { signal });

    // ---- F-305 · OS-fullscreen escape hint -------------------------------
    // Esc exits HTML5 (page) fullscreen, but a browser page CANNOT exit the
    // macOS window-level fullscreen Space (green button / ⌃⌘F) — security
    // boundary. Presenters who mixed the two get "I pressed Esc but my demo
    // still owns a whole desktop". We can't fix it; we CAN say the magic key.
    // Heuristic for "window occupies an OS fullscreen Space": window fills the
    // physical screen AND sits at y=0 (a normal macOS window can't cover the
    // menu bar; auto-hidden-menubar users may see a rare false hint — 4s,
    // truthful, harmless).
    function osFsLikely() {
      return !document.fullscreenElement
        && window.screenY === 0
        && window.outerWidth >= screen.width
        && window.outerHeight >= screen.height;
    }
    function osFsHint() {
      if (!osFsLikely()) return;
      let t = document.getElementById('fs-os-hint');
      if (!t) {
        t = document.createElement('div');
        t.id = 'fs-os-hint';
        t.style.cssText =
          'position:fixed;top:28px;left:50%;transform:translateX(-50%);' +
          'z-index:99999;padding:10px 22px;border-radius:10px;' +
          'background:rgba(10,14,24,.92);border:1px solid rgba(255,255,255,.18);' +
          'color:#fff;font:600 15px/1.4 -apple-system,sans-serif;' +
          'box-shadow:0 12px 40px rgba(0,0,0,.5);pointer-events:none;' +
          'transition:opacity .3s;';
        document.body.appendChild(t);
      }
      t.textContent = /Mac/i.test(navigator.platform)
        ? '已退出页面全屏 — 窗口仍处于系统全屏,按 ⌃⌘F(或绿色按钮)退出'
        : '已退出页面全屏 — 窗口仍处于系统全屏,按 F11 退出';
      t.style.opacity = '1';
      clearTimeout(osFsHint._t);
      osFsHint._t = setTimeout(() => { t.style.opacity = '0'; }, 4000);
    }

    // ---- Fullscreen change handler (debounced single refit, was 3 refits) ----
    let fsRefitTimer;
    function onFsChange() {
      clearTimeout(fsRefitTimer);
      fsRefitTimer = setTimeout(() => {
        frames.forEach(scaleFrame);
        updateUI(deck, frames);
        // F-305: just exited page fullscreen but the WINDOW still owns a
        // fullscreen Space → tell the presenter the one key that works.
        if (osFsLikely()) osFsHint();
      }, FS_REFIT_DEBOUNCE);
    }
    document.addEventListener('fullscreenchange',       onFsChange, { signal });
    document.addEventListener('webkitfullscreenchange', onFsChange, { signal });

    // ---- Wheel nav (present, debounced 600ms) ----
    let wheelLock = 0;
    deck.addEventListener('wheel', (e) => {
      if (deck.dataset.mode !== 'present') return;
      const now = Date.now();
      if (now - wheelLock < 600) return;
      if (Math.abs(e.deltaY) < 30) return;
      wheelLock = now;
      const cur = currentIdx(frames);
      const next = e.deltaY > 0 ? stepNext(frames, cur) : stepPrev(frames, cur);
      goTo(deck, frames, next);
    }, { signal, passive: true });

    // ---- Touch swipe (present mode) ----
    let touchStartY = null;
    deck.addEventListener('touchstart', (e) => {
      if (deck.dataset.mode !== 'present') return;
      touchStartY = e.touches[0].clientY;
    }, { signal, passive: true });
    deck.addEventListener('touchend', (e) => {
      if (deck.dataset.mode !== 'present' || touchStartY == null) return;
      const dy = e.changedTouches[0].clientY - touchStartY;
      touchStartY = null;
      if (Math.abs(dy) < 50) return;
      const cur = currentIdx(frames);
      const next = dy < 0 ? stepNext(frames, cur) : stepPrev(frames, cur);
      goTo(deck, frames, next);
    }, { signal, passive: true });

    // ---- Hash sync — #3 (1-based slide index) OR #<slide-key>
    // (data-slide-key slug, e.g. #cover / #cup-journey). Slug form is
    // how the slide-library viewer deep-links into a specific slide.
    function readHash() {
      const raw = decodeURIComponent(location.hash.replace(/^#/, ''));
      if (!raw) return false;
      if (/^\d+$/.test(raw)) {
        const idx = Math.max(0, Math.min(frames.length - 1, parseInt(raw, 10) - 1));
        // updateHash=true normalizes an out-of-range / `#0` hash to the clamped
        // slide's canonical #N (was left stale, mismatching the shown slide).
        goTo(deck, frames, idx, true);
        return true;
      }
      // data-slide-key / id live on the inner .slide, not on .slide-frame
      const idx = frames.findIndex(f => {
        const slide = f.querySelector('.slide');
        return slide && (slide.dataset.slideKey === raw || slide.id === raw);
      });
      if (idx >= 0) {
        goTo(deck, frames, idx, false);
        return true;
      }
      return false;
    }
    window.addEventListener('hashchange', readHash, { signal });
    if (!readHash()) goTo(deck, frames, firstVisible(frames), false);

    // ---- Kiosk / projection mode — hash keyword force-hides all chrome ----
    // #proj | #bare | #clean | #kiosk → page bar + controls + hint vanish and
    // stay hidden (idle-fade still wakes on hover; kiosk does not). For
    // projecting, embedding in an iframe (e.g. Miaoda), and signage. Pure
    // present-layer: works for any deck regardless of source model.
    function applyKioskChrome() {
      // Guard with (?![\w-]) instead of \b: \b treats '-' as a word boundary, so
      // a valid slide-key hash like #proj-2026 / #clean-tech would wrongly trip
      // kiosk mode and hide ALL nav chrome (M7). The keyword must be the WHOLE
      // hash token (not followed by another word-char OR a hyphen).
      ui.classList.toggle('is-kiosk', /(^|[#&/])(proj|bare|clean|kiosk)(?![\w-])/i.test(location.hash || ''));
    }
    window.addEventListener('hashchange', applyKioskChrome, { signal });
    applyKioskChrome();
    // Initial target is now visible via .is-current; disable the CSS
    // first-frame fallback so the cover cannot bleed through later fades.
    deck.setAttribute('data-js-ready', '');

    // ---- Restart slide media on enter + fs-slide-enter/leave events ----
    // One observer covers EVERY .is-current toggle path: present-mode goTo,
    // hash nav, prev/next buttons, AND the mobile patch's direct toggles
    // (separate IIFE below). Initial pass pauses hidden autoplay videos and
    // starts the current slide's video.
    const mediaState = frames.map((f) => f.classList.contains('is-current'));
    frames.forEach((f, i) => syncFrameMedia(f, mediaState[i]));
    // Initial auto-balance pass: runs maybeBalance on EVERY frame (both modes).
    // In present mode all frames are stacked at inset:0, so this pass already
    // balances every frame whose content content-visibility:auto laid out —
    // measured 2026-06-10: most non-current frames, not just the current one.
    // The handful content-visibility skipped (probe height 0) stay untagged and
    // are balanced on first enter by the observer below (a retry, not the
    // primary path).
    requestAnimationFrame(() => { if (signal.aborted) return; frames.forEach((f) => { const s = f.querySelector('.slide'); maybeBalance(s); try { markBleedPanels(s); } catch (e) { /* never break the deck over layout */ } }); });
    // F-301 · re-measure the band anchor once webfonts settle: a late font swap
    // can rewrap the title/subtitle and change the header bbox bottom. Cheap,
    // idempotent, and skipped for opted-out decks (same data-no-autobalance
    // contract as maybeBalance). Slides canvas-center already pinned with an
    // inline top keep their pin — the var only feeds the stylesheet fallback.
    if (document.fonts && document.fonts.ready && !deck.hasAttribute('data-no-autobalance')) {
      document.fonts.ready.then(() => {
        if (signal.aborted) return;
        frames.forEach((f) => { try { setBandAnchor(f.querySelector('.slide')); } catch (e) { /* best-effort */ } });
      });
    }
    const mediaObserver = new MutationObserver((muts) => {
      for (const m of muts) {
        const i = frames.indexOf(m.target);
        if (i < 0) continue;
        const now = m.target.classList.contains('is-current');
        if (now === mediaState[i]) continue;   // class changed but is-current didn't
        mediaState[i] = now;
        syncFrameMedia(m.target, now);
        // Retry channel: balance a present-mode slide that the init pass left
        // untagged because content-visibility:auto had skipped its layout then
        // (maybeBalance no-ops if it was already tagged at init, which is the
        // common case — see the init pass above).
        if (now) requestAnimationFrame(() => { if (signal.aborted) return; const s = m.target.querySelector('.slide'); maybeBalance(s); try { markBleedPanels(s); } catch (e) { /* never break the deck over layout */ } });
      }
    });
    frames.forEach((f) => mediaObserver.observe(f, { attributes: true, attributeFilter: ['class'] }));
    signal.addEventListener('abort', () => mediaObserver.disconnect());

    // Browsers block unmuted autoplay until the first user gesture. If the
    // deck opens directly on a video slide, that video falls back to muted on
    // load; upgrade it to sound on the first input — WITHOUT resetting its
    // playhead (so the click that enables sound doesn't restart the clip).
    let mediaGestureDone = false;
    const upgradeMediaSound = () => {
      if (mediaGestureDone) return;
      mediaGestureDone = true;
      const cur = frames.find((f) => f.classList.contains('is-current'));
      if (!cur) return;
      cur.querySelectorAll('video').forEach((v) => {
        if (v.autoplay && !v.hasAttribute('data-keep-muted')
            && !v.hasAttribute('muted') && v.muted) {
          v.muted = false;
          const p = v.play();
          if (p && p.catch) p.catch(() => {});
        }
      });
    };
    ['pointerdown', 'keydown', 'touchstart'].forEach((ev) =>
      document.addEventListener(ev, upgradeMediaSound, { signal }));

    // ---- Auto-idle (chrome fades after 2.5s of no input) ----
    let idleTimer;
    function nudgeIdle() {
      const u = document.querySelector('.deck-ui');
      if (!u) return;
      u.classList.remove('is-idle');
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        if (deck.dataset.mode === 'present') u.classList.add('is-idle');
      }, IDLE_MS);
    }
    // mousemove is throttled — fires up to 100×/sec normally, we only need ~10
    let lastNudge = 0;
    function throttledNudge() {
      const now = performance.now();
      if (now - lastNudge < NUDGE_THROTTLE_MS) return;
      lastNudge = now; nudgeIdle();
    }
    document.addEventListener('mousemove',  throttledNudge, { signal, passive: true });
    document.addEventListener('keydown',    nudgeIdle,      { signal, passive: true });
    document.addEventListener('wheel',      nudgeIdle,      { signal, passive: true });
    document.addEventListener('touchstart', nudgeIdle,      { signal, passive: true });
    document.addEventListener('click',      nudgeIdle,      { signal, passive: true });
    nudgeIdle();   // start the timer

    // ---- UI button wires (prev/next + fullscreen) ----
    // 2026-05-06 · removed top-right .mode-toggle button. Bottom-pill .fs button
    // already handles present-mode entry via fullscreen request, and mobile
    // scroll mode is auto-detected via viewport. Toggle button became redundant
    // and added noise to top-right corner where the brand logo sits.
    ui.querySelector('.ctl.prev').addEventListener('click', () => {
      goTo(deck, frames, stepPrev(frames, currentIdx(frames)));
    }, { signal });
    ui.querySelector('.ctl.next').addEventListener('click', () => {
      goTo(deck, frames, stepNext(frames, currentIdx(frames)));
    }, { signal });
    ui.querySelector('.ctl.fs').addEventListener('click', toggleFullscreen, { signal });

    // ---- Window resize / orientation ----
    let resizeTimer;
    function onResize() {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        // Auto-flip mode on the fly only if user hasn't pinned it
        if (!storedMode && !queryMode) {
          const want = window.matchMedia('(max-width: ' + MOBILE_BREAKPOINT + 'px)').matches
                         ? 'scroll' : 'present';
          if (deck.dataset.mode !== want) setMode(deck, want);
        }
        frames.forEach(scaleFrame);
        updateUI(deck, frames);
        maybePortraitToast();
      }, 100);
    }
    window.addEventListener('resize',            onResize, { signal });
    window.addEventListener('orientationchange', onResize, { signal });

    maybePortraitToast();
    updateUI(deck, frames);

    // ---- Return destroy() so SPA hosts can clean up ----
    return {
      destroy() {
        if (activeController) {
          activeController.abort();
          activeController = null;
        }
        const u = document.querySelector('.deck-ui');
        if (u && u.parentNode) u.parentNode.removeChild(u);
        clearTimeout(fsRefitTimer);
        clearTimeout(resizeTimer);
        clearTimeout(idleTimer);
      },
      goTo: (i) => goTo(deck, frames, i),
      setMode: (m) => setMode(deck, m),
    };
  }

  // ---- Helpers ----
  function pad(n) { return n < 10 ? '0' + n : '' + n; }

  function setMode(deck, mode) {
    deck.dataset.mode = mode === 'scroll' ? 'scroll' : 'present';
  }

  function scaleFrame(frame) {
    const slide = frame.querySelector('.slide');
    if (!slide) return;
    const w = frame.clientWidth, h = frame.clientHeight;
    if (!w || !h) return;
    // 2026-05-06 · always use contain (Math.min) to preserve all slide content.
    // History:
    //   v1 (current) · contain. On 16:10 viewports there are small letterbox
    //                  bars top/bottom, but every pixel of the 1920×1080 slide
    //                  is visible — including wordmark in the top-right corner
    //                  and page-no UI at the bottom-center.
    //   v2 (rejected) · cover (Math.max) on fullscreen. Eliminated bars, but on
    //                   16:10 monitors clipped ~106px from each side, eating
    //                   into the master 96px content padding and clipping
    //                   wordmark / corner content. User reported "显示不全".
    // Conclusion: bars are the correct visual behavior; 16:9-content-on-16:10-
    // viewport can't be both "no bars" AND "no clipping". Keep contain.
    const scale = Math.min(w / DESIGN_W, h / DESIGN_H);
    slide.style.setProperty('--fs-scale', String(scale));
  }

  function currentIdx(frames) {
    for (let i = 0; i < frames.length; i++) {
      if (frames[i].classList.contains('is-current')) return i;
    }
    return 0;
  }

  // ---- Hidden slides (隐藏页, PPT-style "hide slide") -----------------------
  // A slide marked `hidden: true` in deck.json renders `data-hidden` on its
  // `.slide` (durable — re-render keeps it). The slide stays in the DOM and is
  // still reachable by a direct #N / #key hash and in scroll mode, but LINEAR
  // present-mode navigation (→ / ← / space / wheel / swipe / prev-next) skips
  // over it, and the page indicator counts only visible slides.
  function isHidden(f) {
    const s = f.querySelector('.slide');
    return !!(s && s.hasAttribute('data-hidden'));
  }
  function stepNext(frames, cur) {            // next visible after cur (else stay)
    for (let i = cur + 1; i < frames.length; i++) if (!isHidden(frames[i])) return i;
    return cur;
  }
  function stepPrev(frames, cur) {            // prev visible before cur (else stay)
    for (let i = cur - 1; i >= 0; i--) if (!isHidden(frames[i])) return i;
    return cur;
  }
  function firstVisible(frames) {
    for (let i = 0; i < frames.length; i++) if (!isHidden(frames[i])) return i;
    return 0;
  }
  function lastVisible(frames) {
    for (let i = frames.length - 1; i >= 0; i--) if (!isHidden(frames[i])) return i;
    return frames.length - 1;
  }
  function visibleCount(frames) {
    let n = 0; for (const f of frames) if (!isHidden(f)) n++; return n;
  }
  // 1-based position of `idx` among visible frames (visible frames at-or-before
  // idx). A hidden current slide reports the count of visible frames before it,
  // floored at 1, so the indicator never reads 0.
  function visibleOrdinal(frames, idx) {
    let n = 0;
    for (let i = 0; i <= idx && i < frames.length; i++) if (!isHidden(frames[i])) n++;
    return Math.max(1, n);
  }

  // Restart-on-enter for slide media (2026-05-24).
  // Present mode keeps EVERY slide in the DOM at once, so a <video autoplay
  // loop> starts on page load while its slide is still hidden and is mid-loop
  // by the time the presenter navigates to it. Entering a frame resets its
  // <video>s to the start (and plays them if marked autoplay); leaving a
  // frame pauses them. Also fires fs-slide-enter / fs-slide-leave on the
  // .slide so CSS-keyframe decks can re-trigger animations on revisit.
  // Opt out of restart per element with data-no-restart.
  //
  // Sound (2026-05-25): autoplay videos play WITH SOUND by default. Slide nav
  // is itself a user gesture, so unmuting succeeds on every navigated-to
  // slide; on the very first frame (pre-gesture) the unmuted play rejects and
  // we fall back to muted — upgradeMediaSound() (see init) then turns sound on
  // at the first input. Keep a video silent (decorative loop backgrounds,
  // secondary clips that would overlap audio) with data-keep-muted.
  //
  // Driven by a single MutationObserver on frame .class (see init) so it
  // catches every nav path.
  function syncFrameMedia(frame, isCurrent) {
    if (!frame) return;
    const slide = frame.querySelector('.slide');
    const vids = frame.querySelectorAll('video');
    // NOTE: non-current present frames are made content-visibility:hidden by the
    // stylesheet, which already halts their SMIL (<animate>) + CSS animations
    // and releases their compositor layer — so no JS-side svg.pauseAnimations is
    // needed (an earlier version did this; content-visibility:hidden supersedes it).
    if (isCurrent) {
      vids.forEach((v) => {
        if (v.hasAttribute('data-no-restart')) return;
        try { v.currentTime = 0; } catch (e) { /* not seekable yet */ }
        if (v.autoplay) playWithSound(v);
      });
      if (slide) slide.dispatchEvent(new CustomEvent('fs-slide-enter', { bubbles: true }));
    } else {
      vids.forEach((v) => {
        if (v.hasAttribute('data-no-restart')) return;
        try { v.pause(); } catch (e) { /* noop */ }
      });
      if (slide) slide.dispatchEvent(new CustomEvent('fs-slide-leave', { bubbles: true }));
    }
  }

  // Play an autoplay <video>, unmuting it UNLESS the author asked for silence.
  // Conservative (2026-05-25): an authored `muted` attribute is respected as
  // "keep silent" (so already-shipped `autoplay muted loop` decks don't
  // suddenly blare), same as data-keep-muted. Only videos authored WITHOUT
  // muted get sound. Unmuted play falls back to muted if the browser blocks
  // it (no user gesture yet); upgradeMediaSound() retries on first input.
  function playWithSound(v) {
    const keepSilent = v.hasAttribute('data-keep-muted') || v.hasAttribute('muted');
    if (!keepSilent) v.muted = false;
    const p = v.play();
    if (p && p.catch) p.catch(() => {
      if (keepSilent) return;                 // already muted, or couldn't play
      v.muted = true;                         // unmuted autoplay blocked → retry muted
      const p2 = v.play();
      if (p2 && p2.catch) p2.catch(() => {});
    });
  }

  function goTo(deck, frames, idx, updateHash) {
    if (idx < 0 || idx >= frames.length) return;
    // Capture armed state BEFORE the arming block below: Magic Move must NOT
    // fire on the very first paint (same intent as the fs-reveal suppression).
    const wasArmed = deck.hasAttribute('data-nav-armed');
    // After the first navigation, arm the reveal animation for subsequent
    // slide changes. The CSS suppresses the staggered reveal on the very
    // first slide load so initial paint isn't ~700 ms of stagger animation.
    if (deck.hasAttribute('data-nav-armed')) {
      // Already armed — normal flow, animations will run on slide change.
    } else if (frames.some((f) => f.classList.contains('is-current'))) {
      // Not the first paint: some frame is already current, so this goTo is a
      // real navigation (or a re-assert of the current slide) → arm the reveal.
      // We key on "a current frame already exists" rather than `idx !== 0`, which
      // wrongly armed (and animated ~700ms) the FIRST paint when slide 0 is hidden
      // and the initial landing target is a non-zero firstVisible() index.
      deck.setAttribute('data-nav-armed', '');
    }
    // The visual swap: toggle the current frame, then scale (present) or
    // scroll (scroll mode). Factored out so Magic Move can wrap it.
    const applySwap = () => {
      for (let i = 0; i < frames.length; i++) {
        frames[i].classList.toggle('is-current', i === idx);
      }
      if (deck.dataset.mode === 'present') {
        scaleFrame(frames[idx]);
      } else {
        frames[idx].scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    };
    // Keynote-style Magic Move (opt-in via deck.json `magic_move` →
    // data-magic-move): wrap the swap in a View Transition so any element
    // sharing a `view-transition-name` across the two slides morphs between
    // its old and new position/size. Feature-detected (Firefox has no
    // startViewTransition → instant swap), present-mode only, never on first
    // paint, and disabled under prefers-reduced-motion.
    const wantsMagicMove = deck.hasAttribute('data-magic-move')
      && deck.dataset.mode === 'present'
      && wasArmed
      && typeof document.startViewTransition === 'function'
      && !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (wantsMagicMove) {
      document.startViewTransition(applySwap);
    } else {
      applySwap();
    }
    if (updateHash !== false) {
      const newHash = '#' + (idx + 1);
      if (location.hash !== newHash) history.replaceState(null, '', newHash);
    }
    updateUI(deck, frames);
    if (typeof window.__fsOnNav === 'function') window.__fsOnNav(idx);  // presenter hook
  }

  // ============================================================
  // Presenter mode (2026-06): PowerPoint/Keynote-style speaker view + a separate
  // projector/audience window that follows the presenter's navigation.
  //  · Speaker view: current + next-slide live previews (cloned .slide, scaled —
  //    same technique as the editor thumbnails, no rasterization), per-slide
  //    speaker notes (from deck.json `notes`, emitted as a hidden JSON island),
  //    a timer, and prev/next.
  //  · Projector window: window.open(...#proj) → clean kiosk view; follows nav
  //    via BroadcastChannel (same-origin, no backend; localStorage fallback).
  //  · Entry: 'P' toggles speaker view (no-op in the projector follower window).
  // ============================================================
  function setupPresenter(deck, frames, signal) {
    let notes = {};
    try {
      const el = document.getElementById('fs-deck-notes');
      if (el) notes = JSON.parse(el.textContent || '{}');
    } catch (e) { notes = {}; }

    // A projector window is opened by openProjector() with window.name
    // 'fs-projector'. It FOLLOWS the leader's nav and never leads.
    const isFollower = (window.name === 'fs-projector');

    let chan = null;
    try { chan = new BroadcastChannel('fs-deck-present'); } catch (e) { chan = null; }
    const LS_KEY = 'fs-deck-present-goto';
    function broadcast(idx) {
      if (isFollower) return;
      const msg = { type: 'goto', idx: idx, t: Date.now() };
      if (chan) { try { chan.postMessage(msg); } catch (e) {} }
      try { localStorage.setItem(LS_KEY, JSON.stringify(msg)); } catch (e) {}
    }
    function onRemoteGoto(msg) {
      if (!isFollower || !msg || msg.type !== 'goto' || typeof msg.idx !== 'number') return;
      if (frames[msg.idx]) goTo(deck, frames, msg.idx, false);
    }
    if (chan) chan.onmessage = (e) => onRemoteGoto(e.data);
    window.addEventListener('storage', (e) => {
      if (e.key === LS_KEY && e.newValue) { try { onRemoteGoto(JSON.parse(e.newValue)); } catch (x) {} }
    }, { signal });

    let pv = null, pvOpen = false, timerStart = 0, timerId = 0, pvKey = null, projWin = null;

    // nav hook called by goTo: mirror to the projector + refresh speaker view.
    window.__fsOnNav = (idx) => { broadcast(idx); if (pvOpen) renderPV(); };

    const curIdx = () => currentIdx(frames);

    // Persist edited notes into the hidden island so a save (window.deckEdit.save
    // / ⌘S) bakes them into the HTML, and `sync-index-to-deck.py --notes-only`
    // can push them back to the deck.json `notes` field.
    function writeNotesIsland() {
      let isl = document.getElementById('fs-deck-notes');
      if (!isl) {
        isl = document.createElement('script');
        isl.type = 'application/json'; isl.id = 'fs-deck-notes';
        document.body.appendChild(isl);
      }
      isl.textContent = JSON.stringify(notes);
    }

    // Live preview: clone the real .slide and scale it (no <img>, no raster).
    function thumbInto(box, slide) {
      if (!box) return;
      box.textContent = '';
      if (!slide) return;
      const c = slide.cloneNode(true);
      c.removeAttribute('id');
      c.querySelectorAll('[id]').forEach((e) => e.removeAttribute('id'));
      c.querySelectorAll('[contenteditable]').forEach((e) => e.removeAttribute('contenteditable'));
      c.querySelectorAll('iframe, video').forEach((e) => {
        const ph = document.createElement('div'); ph.className = 'pv-embed'; e.replaceWith(ph);
      });
      c.style.cssText = 'position:absolute;top:0;left:0;margin:0;width:1920px;height:1080px;' +
                        'transform-origin:top left;pointer-events:none;';
      box.appendChild(c);
      const w = box.clientWidth || 480;
      c.style.transform = 'scale(' + (w / 1920) + ')';
    }

    function renderPV() {
      if (!pv) return;
      const ci = curIdx();
      const ni = stepNext(frames, ci);
      const curSlide = frames[ci] && frames[ci].querySelector('.slide');
      const hasNext = ni !== ci;
      thumbInto(pv.querySelector('.pv-cur'),  curSlide);
      thumbInto(pv.querySelector('.pv-next'), hasNext ? frames[ni].querySelector('.slide') : null);
      const key = curSlide && curSlide.dataset.slideKey;
      pvKey = key || null;
      const ta = pv.querySelector('.pv-notes');
      ta.value = (key && notes[key]) ? notes[key] : '';
      ta.placeholder = '写这一页的讲稿…（自动存入页面;💾 或 ⌘S 保存到文件)';
      pv.querySelector('.pv-pos').textContent =
        visibleOrdinal(frames, ci) + ' / ' + visibleCount(frames);
      pv.querySelector('.pv-nextlabel').textContent = hasNext ? '下一页' : '（已是最后一页）';
    }

    function fmtTime(ms) {
      const s = Math.max(0, Math.floor(ms / 1000)), m = Math.floor(s / 60), r = s % 60;
      return (m < 10 ? '0' : '') + m + ':' + (r < 10 ? '0' : '') + r;
    }

    function buildPV() {
      pv = document.createElement('div');
      pv.className = 'fs-presenter';
      pv.innerHTML =
        '<div class="pv-grid">' +
          '<div class="pv-col"><div class="pv-lab">当前</div><div class="pv-cur pv-box"></div></div>' +
          '<div class="pv-col"><div class="pv-lab pv-nextlabel">下一页</div><div class="pv-next pv-box"></div>' +
            '<div class="pv-lab pv-notes-lab">备注（可编辑）</div>' +
            '<textarea class="pv-notes" spellcheck="false"></textarea></div>' +
        '</div>' +
        '<div class="pv-bar">' +
          '<button class="pv-btn pv-prev" type="button">‹ 上一页</button>' +
          '<span class="pv-pos">1 / 1</span>' +
          '<button class="pv-btn pv-nextbtn" type="button">下一页 ›</button>' +
          '<span class="pv-timer">00:00</span>' +
          '<button class="pv-btn pv-reset" type="button" title="计时归零">↺</button>' +
          '<button class="pv-btn pv-save" type="button" title="保存讲稿到当前 HTML 文件">💾 保存</button>' +
          '<button class="pv-btn pv-proj" type="button" title="打开放映窗(观众屏,自动跟随)">📺 放映窗</button>' +
          '<button class="pv-btn pv-exit" type="button" title="退出 (Esc / P)">✕ 退出</button>' +
        '</div>';
      document.body.appendChild(pv);
      pv.querySelector('.pv-prev').onclick    = () => goTo(deck, frames, stepPrev(frames, curIdx()));
      pv.querySelector('.pv-nextbtn').onclick = () => goTo(deck, frames, stepNext(frames, curIdx()));
      pv.querySelector('.pv-proj').onclick    = openProjector;
      pv.querySelector('.pv-exit').onclick    = closePresenter;
      pv.querySelector('.pv-reset').onclick   = () => { timerStart = Date.now(); };
      // edit notes → update in-memory map + the hidden island (so any save persists)
      pv.querySelector('.pv-notes').addEventListener('input', function () {
        if (!pvKey) return;
        if (this.value) notes[pvKey] = this.value; else delete notes[pvKey];
        writeNotesIsland();
      });
      // 💾 save → bake island into the HTML via the edit-mode FS-Access save.
      pv.querySelector('.pv-save').onclick = () => {
        writeNotesIsland();
        if (window.deckEdit && typeof window.deckEdit.save === 'function') {
          window.deckEdit.save();
        } else {
          alert('已写入页面。用编辑模式(E)的 ⌘S 保存到文件,'
              + '或运行 sync-index-to-deck.py --notes-only 同步到 deck.json。');
        }
      };
    }

    function openPresenter() {
      if (pvOpen) return;
      if (!pv) buildPV();
      pv.style.display = 'flex';
      pvOpen = true;
      if (!timerStart) timerStart = Date.now();
      timerId = setInterval(() => {
        const t = pv && pv.querySelector('.pv-timer');
        if (t) t.textContent = fmtTime(Date.now() - timerStart);
      }, 1000);
      requestAnimationFrame(renderPV);   // ensure boxes have width before scaling
    }
    function closePresenter() {
      if (!pvOpen) return;
      pvOpen = false;
      if (pv) pv.style.display = 'none';
      clearInterval(timerId);
      closeProjector();   // exiting the presenter dismisses the projector it spawned — no orphan
    }
    window.__fsTogglePresenter = isFollower
      ? function () {}
      : function () { pvOpen ? closePresenter() : openPresenter(); };

    function projAlive() { try { return !!projWin && !projWin.closed; } catch (e) { return false; } }
    function updateProjBtn() {
      const btn = pv && pv.querySelector('.pv-proj');
      if (btn) btn.textContent = projAlive() ? '📺 关闭放映窗' : '📺 放映窗';
    }
    function closeProjector() {
      if (projAlive()) { try { projWin.close(); } catch (e) {} }
      projWin = null;
      updateProjBtn();
    }
    // 📺 toggles the audience/projector window. The handle is KEPT (it used to be
    // discarded) so the deck can actually close it — otherwise the #proj kiosk
    // window orphaned in the background with no way to dismiss it ("关不掉的窗口").
    function openProjector() {
      if (projAlive()) { closeProjector(); return; }      // already open → close (clear dismiss path)
      const url = location.pathname + location.search + '#proj';
      projWin = window.open(url, 'fs-projector', 'width=1280,height=760');
      updateProjBtn();
      setTimeout(() => broadcast(curIdx()), 400);   // land the new window on our slide
    }

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && pvOpen) { e.preventDefault(); closePresenter(); }
    }, { signal });

    signal.addEventListener('abort', () => {
      clearInterval(timerId);
      closeProjector();
      if (chan) { try { chan.close(); } catch (e) {} }
      window.__fsOnNav = null;
      window.__fsTogglePresenter = null;
    });
    // Close the projector if the whole tab/window goes away — never leave an orphan behind.
    window.addEventListener('beforeunload', () => { if (!isFollower) closeProjector(); }, { signal });

    // The projector itself (#proj follower) is a chrome-less kiosk window, so it had
    // no in-page way to close — give it its own dismiss button. Lives ON body (not
    // inside .deck-ui), so the `.is-kiosk` chrome-hide does not touch it; it is the
    // last-resort exit for an orphaned audience window.
    if (isFollower) {
      const x = document.createElement('button');
      x.type = 'button';
      x.textContent = '✕ 关闭放映窗';
      x.setAttribute('aria-label', '关闭放映窗');
      x.style.cssText =
        'position:fixed;top:12px;right:12px;z-index:2147483600;padding:8px 14px;' +
        'border-radius:999px;border:1px solid rgba(255,255,255,.28);background:rgba(8,12,24,.72);' +
        'color:#fff;font:600 14px/1 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;' +
        'cursor:pointer;opacity:.2;transition:opacity .2s;backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);';
      x.addEventListener('mouseenter', () => { x.style.opacity = '1'; });
      x.addEventListener('mouseleave', () => { x.style.opacity = '.2'; });
      x.addEventListener('click', () => { try { window.close(); } catch (e) {} });
      document.body.appendChild(x);
    }
  }

  function buildUI() {
    const ui = document.createElement('div');
    ui.className = 'deck-ui';
    // 2026-05-06 · top-right .mode-toggle button removed (redundant with bottom
    // .ctl.fs and auto mobile scroll detection). Don't re-add — see updateUI().
    ui.innerHTML =
      '<div class="deck-progress" aria-hidden="true"><div class="bar"></div></div>' +
      '<div class="deck-controls" role="group" aria-label="Slide controls">' +
        '<button class="ctl prev" type="button" title="上一页 (←)" aria-label="Previous slide">' +
          '<svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round" width="16" height="16"><path d="M15 18l-6-6 6-6"/></svg>' +
        '</button>' +
        '<span class="indicator"><span class="cur">01</span><span class="sep"> / </span><span class="total">01</span></span>' +
        '<button class="ctl next" type="button" title="下一页 (→ / Space)" aria-label="Next slide">' +
          '<svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round" width="16" height="16"><path d="M9 6l6 6-6 6"/></svg>' +
        '</button>' +
        '<span class="ctl-sep"></span>' +
        '<button class="ctl fs" type="button" title="全屏 (F)" aria-label="Toggle fullscreen">' +
          '<svg class="i-enter" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round" width="16" height="16"><path d="M3 9V5a2 2 0 0 1 2-2h4M21 9V5a2 2 0 0 0-2-2h-4M3 15v4a2 2 0 0 0 2 2h4M21 15v4a2 2 0 0 1-2 2h-4"/></svg>' +
          '<svg class="i-exit"  viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.2" fill="none" stroke-linecap="round" stroke-linejoin="round" width="16" height="16"><path d="M9 3v4a2 2 0 0 1-2 2H3M15 3v4a2 2 0 0 0 2 2h4M9 21v-4a2 2 0 0 0-2-2H3M15 21v-4a2 2 0 0 1 2-2h4"/></svg>' +
        '</button>' +
      '</div>' +
      '<div class="nav-hint">← →&nbsp;翻页&nbsp; ·&nbsp; F&nbsp;全屏&nbsp; ·&nbsp; P&nbsp;演示者&nbsp; ·&nbsp; E&nbsp;编辑</div>';
    return ui;
  }

  function updateUI(deck, frames) {
    const ui = document.querySelector('.deck-ui');
    if (!ui) return;
    const cur = currentIdx(frames);
    // Indicator counts only VISIBLE slides (hidden 隐藏页 are skipped in the
    // show), so "3 / 12" matches what the audience actually pages through.
    const total = visibleCount(frames);
    const pos   = visibleOrdinal(frames, cur);
    const isPresent = deck.dataset.mode === 'present';
    const isFullscreen = !!(document.fullscreenElement || document.webkitFullscreenElement);

    ui.querySelector('.cur').textContent   = pad(pos);
    ui.querySelector('.total').textContent = pad(total);
    const pct = total > 0 ? (pos / total) * 100 : 0;
    ui.querySelector('.deck-progress .bar').style.width = pct + '%';
    ui.querySelector('.ctl.fs .i-enter').style.display = isFullscreen ? 'none'  : 'block';
    ui.querySelector('.ctl.fs .i-exit').style.display  = isFullscreen ? 'block' : 'none';
    ui.querySelector('.deck-progress').style.display = isPresent ? 'block' : 'none';
    ui.querySelector('.deck-controls').style.display = isPresent ? 'flex'  : 'none';
    ui.querySelector('.nav-hint').style.display      = isPresent ? 'block' : 'none';
    // Gate prev/next on the VISIBLE ordinal (same index space as the indicator
    // above) — NOT the raw frame index `cur`, which counts hidden 隐藏页 too and
    // would mis-disable the buttons when hidden slides are not all at the tail.
    ui.querySelector('.ctl.prev').disabled = pos <= 1;
    ui.querySelector('.ctl.next').disabled = pos >= total;
  }

  function requestFullscreen() {
    const root = document.documentElement;
    if (root.requestFullscreen) {
      root.requestFullscreen().catch(() => {});
    } else if (root.webkitRequestFullscreen) {
      root.webkitRequestFullscreen();
    }
  }
  function toggleFullscreen() {
    const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
    if (fsEl) {
      // Guard: if neither exit API exists (Firefox-without-prefix in
      // ancient builds, sandboxed iframes), `.call` would crash on
      // undefined. 2026-05-18 round 2 review fix.
      const exit = document.exitFullscreen || document.webkitExitFullscreen;
      if (exit) exit.call(document);
    } else {
      requestFullscreen();
    }
  }

  function isTypingTarget(target) {
    if (!target || !(target instanceof Element)) return false;
    if (target.isContentEditable) return true;
    const tag = target.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
  }

  function maybePortraitToast() {
    const isPortrait = window.matchMedia('(orientation: portrait) and (max-width: 900px)').matches;
    if (isPortrait) document.body.classList.add('fs-portrait-warn');
    else document.body.classList.remove('fs-portrait-warn');
  }

  // ---- Boot ----
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }

  // Expose programmatic API for SPA hosts
  if (typeof window !== 'undefined') {
    window.feishuDeck = { init };
  }
})();

/* ============================================================================
   Mobile UX patch (≤900px) — tap-to-enlarge + swipe nav (2026-05-21)
   ----------------------------------------------------------------------------
   Issue: on mobile, the framework auto-switches to scroll mode where each
   slide-frame is 100vw × 9/16 (~393×220 on a 393w phone). The 1920×1080
   design canvas scales to ~0.2× → 22px body text becomes ~4.5px → unreadable.
   User reported "手机端打开就是错乱的".

   Fix: keep scroll mode as the overview but make each frame a tap target —
   tap any slide → switch to present mode showing that one slide filling the
   viewport. Left/right swipe paginates. Tap "← 返回列表" returns to scroll.

   Paired with the CSS block at the bottom of feishu-deck.css (same date stamp).
   Runs as a separate IIFE after the main init, so existing init logic stays
   untouched. Mobile-only — does nothing on viewports > 900px.
   ============================================================================ */
(function () {
  if (typeof window === 'undefined') return;
  if (!window.matchMedia('(max-width: 900px)').matches) return;

  function wire() {
    const deck = document.querySelector('.deck');
    if (!deck) return;
    const frames = Array.from(deck.querySelectorAll('.slide-frame'));
    if (!frames.length) return;
    if (document.querySelector('.fs-mobile-back')) return;  // idempotent

    const backBtn = document.createElement('div');
    backBtn.className = 'fs-mobile-back';
    backBtn.textContent = '← 返回列表';
    backBtn.setAttribute('role', 'button');
    backBtn.setAttribute('aria-label', '返回 slide 列表');
    document.body.appendChild(backBtn);

    const pageNo = document.createElement('div');
    pageNo.className = 'fs-mobile-pageno';
    document.body.appendChild(pageNo);

    function curIdx() {
      for (let i = 0; i < frames.length; i++) {
        if (frames[i].classList.contains('is-current')) return i;
      }
      return 0;
    }
    function updatePageNo() {
      pageNo.textContent = (curIdx() + 1) + ' / ' + frames.length;
    }
    // MANUAL scale computation. The framework's ResizeObserver only watches
    // documentElement and does NOT fire on data-mode flips (the viewport
    // doesn't change). So after switching mode, --fs-scale stays at the
    // previous mode's value and the slide visibly fails to scale up.
    // Measure clientWidth/Height ourselves after layout settles.
    function scaleNow(idx) {
      const frame = frames[idx];
      const slide = frame && frame.querySelector('.slide');
      if (!slide) return;
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          const w = frame.clientWidth, h = frame.clientHeight;
          if (!w || !h) return;
          const scale = Math.min(w / 1920, h / 1080);
          slide.style.setProperty('--fs-scale', String(scale));
        });
      });
    }
    function setMode(mode, idx) {
      deck.dataset.mode = mode;
      try { localStorage.setItem('fs-deck-mode', mode); } catch (e) {}
      if (mode === 'present' && typeof idx === 'number') {
        frames.forEach((f, i) => f.classList.toggle('is-current', i === idx));
        scaleNow(idx);
        // Keep the URL hash in sync (#914): the mobile patch toggles is-current
        // directly instead of going through the main goTo(), so without this a
        // reload / shared link restored the wrong slide.
        try { history.replaceState(null, '', '#' + (idx + 1)); } catch (e) {}
      } else if (mode === 'scroll') {
        frames.forEach((_, i) => scaleNow(i));
      }
      updatePageNo();
    }
    function go(delta) {
      const cur = curIdx();
      const next = Math.max(0, Math.min(frames.length - 1, cur + delta));
      if (next !== cur) {
        frames.forEach((f, i) => f.classList.toggle('is-current', i === next));
        scaleNow(next);
        updatePageNo();
        try { history.replaceState(null, '', '#' + (next + 1)); } catch (e) {}
      }
    }

    frames.forEach((frame, i) => {
      frame.addEventListener('click', (e) => {
        if (deck.dataset.mode !== 'scroll') return;
        if (e.target && e.target.closest('a, button, iframe, [role="button"], .probe-tab')) return;
        e.preventDefault();
        e.stopPropagation();
        setMode('present', i);
      }, true);
    });

    backBtn.addEventListener('click', () => {
      const cur = curIdx();
      setMode('scroll');
      if (cur >= 0) setTimeout(() => frames[cur].scrollIntoView({ block: 'center' }), 50);
    });

    let sx = null, sy = null, st = 0;
    document.addEventListener('touchstart', (e) => {
      if (deck.dataset.mode !== 'present') return;
      const t0 = e.touches[0]; sx = t0.clientX; sy = t0.clientY; st = Date.now();
    }, { passive: true });
    document.addEventListener('touchend', (e) => {
      if (deck.dataset.mode !== 'present' || sx === null) return;
      const t1 = e.changedTouches[0];
      const dx = t1.clientX - sx, dy = t1.clientY - sy, dt = Date.now() - st;
      sx = sy = null;
      if (dt > 600) return;
      if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy) * 1.2) {
        if (e.target && e.target.closest('iframe')) return;
        e.preventDefault();
        go(dx < 0 ? +1 : -1);
      }
    }, { passive: false });

    updatePageNo();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire, { once: true });
  } else {
    setTimeout(wire, 100);
  }
})();
