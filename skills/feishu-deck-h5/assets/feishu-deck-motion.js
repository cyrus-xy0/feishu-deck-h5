/* ============================================================================
   feishu-deck-motion.js  —  OPT-IN GSAP entrance engine for the feishu-deck
   runtime.  Engaged ONLY when the deck root carries data-motion="gsap"
   (deck.json `motion_engine: "gsap"`); the renderer emits this attr + the GSAP
   <script> tags together, so a deck without the flag never loads this file and
   keeps the zero-dependency fs-reveal CSS baseline.

   WHY IT IS SAFE (the design rules, learned the hard way):
   - It NEVER pre-hides content via a global rule. The resting state is the
     framework default = VISIBLE. For only the specific descendants it animates,
     it kills fs-reveal inline + pins opacity:1 BEFORE tweening, then uses
     .from() so the END state is always the visible value. If GSAP fails to
     load, errors, or a slide is never entered → content is shown, never lost.
   - It does NOT touch the page's layout measurement (no global `.slide>*`
     override), so oversized self-scaling pages keep their correct --fs-scale.
   - Title splitting is WORD-level for body titles (word boxes preserve line
     wrapping → title height unchanged → no mis-scale); CHAR-level only on the
     structurally-simple cover / section / closing pages. Gradient-clip titles
     get the gradient re-applied per unit so split text stays visible.
   - Every per-slide build is wrapped in try/catch with a clearProps fail-safe,
     plus a watchdog that force-reveals any slide left hidden.

   It hooks the runtime's own fs-slide-enter / fs-slide-leave CustomEvents, so it
   composes with navigation, scaling and Magic Move rather than replacing them.
   Caveat: the CSSOM-based validator audits (DEAD-ANIM / DEAD-RULE) cannot see
   JS-driven motion — the visible-resting guarantee above is the safety net.
   ============================================================================ */
(function () {
  var root = document.documentElement;
  var deck = document.querySelector('.deck[data-motion="gsap"]');
  if (!deck) return;                                          // opt-in only
  if (!window.gsap) return;                                   // no lib → fs-reveal stays
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  if (location.search.indexOf('nofx') >= 0) return;          // diagnostic kill-switch (A/B vs baseline)
  var gsap = window.gsap;
  try { gsap.registerPlugin(window.CustomEase, window.SplitText); } catch (e) {}

  var EASE = 'power3.out';
  try { if (window.CustomEase) { CustomEase.create('fwd', 'M0,0 C0.16,1 0.3,1 1,1'); EASE = 'fwd'; } } catch (e) {}

  var tlMap = new WeakMap(), ambientMap = new WeakMap();
  function arr(x) { return Array.prototype.slice.call(x); }
  function skip(el) { return el.classList.contains('wordmark') || el.tagName === 'STYLE' || el.tagName === 'SCRIPT'; }
  function key(s) { return s.getAttribute('data-slide-key') || ''; }

  // Elements to stagger: direct .slide children, but if the slide wraps
  // everything in 1-2 containers, descend into the largest one.
  function blocksOf(slide) {
    var direct = arr(slide.children).filter(function (el) { return !skip(el); });
    var rt = slide;
    if (direct.length > 0 && direct.length <= 2) {
      rt = direct.reduce(function (a, b) {
        var ab = a ? a.offsetWidth * a.offsetHeight : 0;
        return (b.offsetWidth * b.offsetHeight >= ab) ? b : a;
      }, null) || slide;
    }
    var blocks = (rt === slide) ? direct : arr(rt.children).filter(function (el) { return !skip(el); });
    return blocks.length ? blocks : direct;
  }
  function flowOnly(els) {
    return els.filter(function (el) { var p = getComputedStyle(el).position; return p !== 'absolute' && p !== 'fixed'; });
  }
  // safe resting state on elements we animate: kill fs-reveal inline (only
  // these) + pin opacity:1 so a partial/failed tween never hides content.
  function prep(els) { for (var i = 0; i < els.length; i++) { els[i].style.animation = 'none'; els[i].style.opacity = '1'; } }
  function titleOf(slide) { return slide.querySelector('.title-zh, .ep-h1, [class*="headline"], h1, h2'); }

  // split breaks `background-clip:text` gradients (the unit spans have no bg) →
  // re-apply the title's gradient to each unit so it stays visible.
  function fixGradient(title, units) {
    var cs = getComputedStyle(title);
    var transparent = cs.webkitTextFillColor === 'rgba(0, 0, 0, 0)' || cs.color === 'rgba(0, 0, 0, 0)';
    if (!transparent || !cs.backgroundImage || cs.backgroundImage === 'none') return;
    units.forEach(function (u) {
      u.style.backgroundImage = cs.backgroundImage; u.style.webkitBackgroundClip = 'text';
      u.style.backgroundClip = 'text'; u.style.color = 'transparent'; u.style.webkitTextFillColor = 'transparent';
    });
  }

  function revealTitle(tl, title, mode, at) {
    if (!title) return;
    prep([title]);
    // Any element child (even classed <span> segments) → the title is structured;
    // SplitText would mangle it, so stagger the children instead.
    if (title.children.length > 0 || !window.SplitText) {
      var kids = arr(title.children).length ? arr(title.children) : [title];
      prep(kids);
      tl.from(kids, { opacity: 0, yPercent: 40, filter: 'blur(6px)', stagger: 0.07, duration: 0.7, clearProps: 'filter,transform' }, at);
      return;
    }
    try {
      if (title._fwdSplit) { try { title._fwdSplit.revert(); } catch (e) {} title._fwdSplit = null; }
      var sp = new SplitText(title, { type: mode === 'chars' ? 'chars,words' : 'words' });
      title._fwdSplit = sp;
      var units = mode === 'chars' ? sp.chars : sp.words;
      fixGradient(title, units);
      gsap.set(title, { opacity: 1 });
      tl.from(units, {
        opacity: 0, yPercent: mode === 'chars' ? 120 : 60, rotateX: mode === 'chars' ? -65 : -28,
        filter: 'blur(5px)', transformOrigin: '50% 100% -20px',
        stagger: mode === 'chars' ? 0.018 : 0.05, duration: mode === 'chars' ? 0.7 : 0.66, ease: 'power4.out'
      }, at);
    } catch (e) { gsap.set(title, { opacity: 1 }); }
  }

  function drawSVG(tl, slide, at) {
    try {
      var strokes = [];
      arr(slide.querySelectorAll('svg')).forEach(function (svg) {
        arr(svg.querySelectorAll('path, line, polyline')).forEach(function (p) {
          if (strokes.length >= 70) return;
          var cs = getComputedStyle(p);
          if (cs.stroke === 'none' || parseFloat(cs.strokeWidth) === 0) return;
          var len = 0; try { len = p.getTotalLength(); } catch (e) { return; }
          if (len < 8 || len > 6000) return;
          strokes.push(p); gsap.set(p, { strokeDasharray: len, strokeDashoffset: len });
        });
      });
      if (strokes.length) tl.to(strokes, { strokeDashoffset: 0, duration: 0.9, ease: 'power1.inOut', stagger: 0.05, clearProps: 'strokeDasharray,strokeDashoffset' }, at);
    } catch (e) {}
  }

  function ambient(slide) {
    try {
      var els = arr(slide.querySelectorAll('[class*="glow"],[class*="orb"],[class*="halo"],[class*="aura"],[class*="spark"],[class*="float"],[class*="pulse"]'))
        .filter(function (el) { return el.offsetParent !== null; }).slice(0, 6);
      if (els.length) ambientMap.set(slide, gsap.to(els, { y: '+=7', duration: 3.4, ease: 'sine.inOut', yoyo: true, repeat: -1, stagger: 0.4 }));
    } catch (e) {}
  }

  function countUp(tl, slide, at) {
    arr(slide.querySelectorAll('.metric, .num, [class*="kpi"] .metric, [class*="stat-num"]')).forEach(function (el) {
      var raw = (el.textContent || '').trim();
      if (raw.length > 12) return;
      var m = raw.match(/^([^\d]*?)(\d[\d,]*\.?\d*)(.*)$/); if (!m) return;
      var end = parseFloat(m[2].replace(/,/g, '')); if (!isFinite(end) || end === 0) return;
      if (!el.hasAttribute('data-fwd-num')) el.setAttribute('data-fwd-num', raw);
      var pre = m[1], suf = m[3], dec = (m[2].split('.')[1] || '').length, o = { v: 0 };
      tl.to(o, { v: end, duration: 1.1, ease: 'power1.out',
        onUpdate: function () { el.textContent = pre + (dec ? o.v.toFixed(dec) : Math.round(o.v).toLocaleString()) + suf; },
        onComplete: function () { el.textContent = raw; }, onInterrupt: function () { el.textContent = raw; } }, at);
    });
  }

  function isCover(s) { return key(s) === 'cover' || !!s.querySelector('.cover, [class*="cover"]'); }
  function isSection(s) { return /^section[-_]/.test(key(s)) || s.classList.contains('section') || !!s.querySelector('[class*="section-"]'); }
  function isClosing(s) { return /clos|end|film/.test(key(s)); }

  function buildContent(slide) {
    var blocks = flowOnly(blocksOf(slide)); prep(blocks);
    var tl = gsap.timeline({ defaults: { ease: EASE } });
    if (blocks.length) tl.from(blocks, { opacity: 0, y: 42, scale: 0.975, transformOrigin: '50% 70%', duration: 0.82, stagger: 0.085, clearProps: 'transform' }, 0);
    revealTitle(tl, titleOf(slide), 'words', 0.08);
    var items = arr(slide.querySelectorAll('.panel, .eng, .kcol, .card, .item, li, .ktag, .eng-kpi, .kcore'))
      .filter(function (el) { return el.offsetParent !== null && blocks.indexOf(el) < 0; }).slice(0, 44);
    if (items.length > 1) { prep(items); tl.from(items, { opacity: 0, y: 24, filter: 'blur(4px)', duration: 0.55, stagger: 0.045, clearProps: 'filter,transform' }, 0.26); }
    drawSVG(tl, slide, 0.3); countUp(tl, slide, 0.4);
    return tl;
  }
  function buildCover(slide) {
    var blocks = flowOnly(blocksOf(slide)); prep(blocks);
    var tl = gsap.timeline({ defaults: { ease: EASE } });
    tl.from(blocks, { opacity: 0, y: 60, scale: 0.94, filter: 'blur(12px)', transformOrigin: '50% 60%', duration: 1.1, stagger: 0.12, clearProps: 'filter,transform' }, 0);
    revealTitle(tl, titleOf(slide), 'chars', 0.2); drawSVG(tl, slide, 0.5); countUp(tl, slide, 0.6);
    return tl;
  }
  function buildSection(slide) {
    var blocks = flowOnly(blocksOf(slide)); prep(blocks);
    var tl = gsap.timeline({ defaults: { ease: EASE } });
    tl.from(blocks, { opacity: 0, x: 46, filter: 'blur(8px)', duration: 0.9, stagger: 0.1, clearProps: 'filter,transform' }, 0);
    revealTitle(tl, titleOf(slide), 'chars', 0.15); drawSVG(tl, slide, 0.4);
    return tl;
  }

  function reveal(slide) {
    try {
      var amb = ambientMap.get(slide); if (amb) { amb.kill(); ambientMap['delete'](slide); }
      var els = blocksOf(slide).concat(arr(slide.querySelectorAll('.panel,.eng,.kcol,.card,.item,li,.ktag,.eng-kpi,.kcore,.title-zh,.ep-h1,h1,h2')));
      gsap.killTweensOf(els);
      for (var i = 0; i < els.length; i++) { els[i].style.opacity = '1'; els[i].style.animation = 'none'; }
      gsap.set(els, { clearProps: 'transform,filter' });
      var t = titleOf(slide); if (t && t._fwdSplit) { try { t._fwdSplit.revert(); } catch (e) {} t._fwdSplit = null; }
    } catch (e) {}
    arr(slide.querySelectorAll('[data-fwd-num]')).forEach(function (el) { el.textContent = el.getAttribute('data-fwd-num'); });
  }

  // Detect author-supplied bespoke motion: any element carrying a CSS
  // animation-name other than the framework's own fs-reveal. If a slide has its
  // own custom_css @keyframes/animation, the engine STEPS ASIDE ENTIRELY — no
  // prep, no .from, no reveal — so it never fights or clobbers hand-designed
  // per-page motion. Such a page then behaves exactly as it did with the engine
  // OFF: framework fs-reveal baseline + its own custom_css. Cached per slide.
  function bespoke(slide) {
    if (slide._fwdBespoke !== undefined) return slide._fwdBespoke;
    var found = false;
    try {
      var els = slide.querySelectorAll('*');
      for (var i = 0; i < els.length && i < 600; i++) {
        var nm = getComputedStyle(els[i]).animationName;
        if (!nm || nm === 'none') continue;
        var ps = nm.split(',');
        for (var j = 0; j < ps.length; j++) {
          var n = ps[j].trim();
          if (n && n !== 'none' && n !== 'fs-reveal') { found = true; break; }
        }
        if (found) break;
      }
    } catch (e) {}
    slide._fwdBespoke = found;
    return found;
  }

  function animateSlide(slide) {
    if (!slide) return;
    if (bespoke(slide)) return;     // page owns its own motion → engine steps aside
    var prev = tlMap.get(slide); if (prev) prev.kill();
    var amb = ambientMap.get(slide); if (amb) { amb.kill(); ambientMap['delete'](slide); }
    try {
      var tl = (isCover(slide) || isClosing(slide)) ? buildCover(slide) : isSection(slide) ? buildSection(slide) : buildContent(slide);
      tlMap.set(slide, tl);
      tl.eventCallback('onComplete', function () { ambient(slide); });
      return tl;
    } catch (e) { reveal(slide); }
  }

  function slideOf(e) { return e.target && e.target.closest ? e.target.closest('.slide') : e.target; }
  document.addEventListener('fs-slide-enter', function (e) { var s = slideOf(e); if (s) animateSlide(s); }, true);
  document.addEventListener('fs-slide-leave', function (e) {
    var s = slideOf(e); if (!s || bespoke(s)) return;   // never touch a bespoke page
    var tl = tlMap.get(s); if (tl) tl.kill(); reveal(s);
  }, true);

  // The runtime fires the FIRST fs-slide-enter during its own sync init (before
  // this listener attaches), so retries catch the settled current slide.
  function ensureCurrent() {
    var s = document.querySelector('.slide-frame.is-current .slide') || document.querySelector('.slide');
    if (s && tlMap.get(s) === undefined) animateSlide(s);
  }
  function watchdog() {
    var s = document.querySelector('.slide-frame.is-current .slide'); if (!s || bespoke(s)) return;
    var blks = blocksOf(s);
    for (var i = 0; i < blks.length; i++) {
      if (parseFloat(getComputedStyle(blks[i]).opacity) < 0.02) { var tl = tlMap.get(s); if (!tl || !tl.isActive()) { reveal(s); return; } }
    }
  }
  function init() {
    [0, 120, 350, 700, 1200].forEach(function (d) { setTimeout(ensureCurrent, d); });
    [1700, 2800].forEach(function (d) { setTimeout(watchdog, d); });
  }
  if (document.readyState !== 'loading') init();
  else document.addEventListener('DOMContentLoaded', init);
})();
