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
  //  · content-visibility hides non-current slides in present mode, so each
  //    slide is balanced the first time it is actually laid out (initial pass
  //    for current/scroll slides, the is-current observer for the rest).
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
    let severity = 0, spill = 0; const crowded = [];
    for (const box of boxes) {
      const r = box.getBoundingClientRect();
      spill = Math.max(spill, (r.bottom - sb) / scale);
      const cu = _abTextUnion(box); if (!cu) continue;
      const distTop = (cu.top - r.top) / scale, distBottom = (r.bottom - cu.bottom) / scale;
      if (distBottom < 10 && distTop > distBottom + 16) { crowded.push(box); severity += (16 - distBottom); }
    }
    return { severity, spill, crowded };
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
    if (before.severity === 0) return;                 // already balanced → no-op (schema decks)
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
    });
    const after = _abMeasure(slide);
    const titleMoved = titleSnap.some(([el, t, l]) => {
      const r = el.getBoundingClientRect();
      return Math.abs(r.top - t) > 1 || Math.abs(r.left - l) > 1;
    });
    const improved = after.severity < before.severity - 0.5 &&
                     after.spill <= Math.max(before.spill, 2) && !titleMoved;
    if (improved) {
      slide.setAttribute('data-fs-autobalanced', '');
    } else {
      for (const [el, prop, val] of touched) el.style[prop] = val || '';  // incl. title-moved revert
    }
  }
  function maybeBalance(slide) {
    if (!slide || slide.hasAttribute('data-fs-balanced')) return;
    const deck = slide.closest('.deck');
    if (deck && deck.hasAttribute('data-no-autobalance')) return;
    // content-visibility:auto skips off-screen slides → their content has 0
    // size. Only tag+balance once a content container is actually laid out;
    // otherwise leave untagged so the is-current observer retries when visible.
    const probe = slide.querySelector('.stage, .grid, .flow, .nodes, .toc, .stack, .header, [class*="card"]');
    if (!probe || probe.getBoundingClientRect().height < 30) return;
    slide.setAttribute('data-fs-balanced', '');
    try { balanceSlide(slide); } catch (e) { /* never break the deck over layout */ }
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

    // ---- Keyboard nav (present mode) + F = fullscreen (any mode) ----
    document.addEventListener('keydown', (e) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (isTypingTarget(e.target)) return;
      if (e.key === 'f' || e.key === 'F') {
        e.preventDefault(); toggleFullscreen(); nudgeIdle(); return;
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
          e.preventDefault(); goTo(deck, frames, Math.min(cur + 1, frames.length - 1)); break;
        case 'ArrowLeft': case 'ArrowUp': case 'PageUp':
        case 'Backspace':
          e.preventDefault(); goTo(deck, frames, Math.max(cur - 1, 0)); break;
        case 'Home':
          e.preventDefault(); goTo(deck, frames, 0); break;
        case 'End':
          e.preventDefault(); goTo(deck, frames, frames.length - 1); break;
        case 'Escape':
          if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
          break;
      }
      nudgeIdle();
    }, { signal });

    // ---- Fullscreen change handler (debounced single refit, was 3 refits) ----
    let fsRefitTimer;
    function onFsChange() {
      clearTimeout(fsRefitTimer);
      fsRefitTimer = setTimeout(() => {
        frames.forEach(scaleFrame);
        updateUI(deck, frames);
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
      const next = e.deltaY > 0
        ? Math.min(cur + 1, frames.length - 1)
        : Math.max(cur - 1, 0);
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
      const next = dy < 0
        ? Math.min(cur + 1, frames.length - 1)
        : Math.max(cur - 1, 0);
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
        goTo(deck, frames, idx, false);
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
    if (!readHash()) goTo(deck, frames, 0, false);
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
    // Initial auto-balance pass: balances the current slide (present mode) and
    // every laid-out slide (scroll mode). Non-current present-mode slides are
    // content-visibility-hidden here and get balanced on first enter (below).
    requestAnimationFrame(() => frames.forEach((f) => maybeBalance(f.querySelector('.slide'))));
    const mediaObserver = new MutationObserver((muts) => {
      for (const m of muts) {
        const i = frames.indexOf(m.target);
        if (i < 0) continue;
        const now = m.target.classList.contains('is-current');
        if (now === mediaState[i]) continue;   // class changed but is-current didn't
        mediaState[i] = now;
        syncFrameMedia(m.target, now);
        // Balance a present-mode slide the first time it becomes visible
        // (content-visibility makes it measurable only now).
        if (now) requestAnimationFrame(() => maybeBalance(m.target.querySelector('.slide')));
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
      goTo(deck, frames, Math.max(0, currentIdx(frames) - 1));
    }, { signal });
    ui.querySelector('.ctl.next').addEventListener('click', () => {
      goTo(deck, frames, Math.min(frames.length - 1, currentIdx(frames) + 1));
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
    // After the first navigation, arm the reveal animation for subsequent
    // slide changes. The CSS suppresses the staggered reveal on the very
    // first slide load so initial paint isn't ~700 ms of stagger animation.
    if (deck.hasAttribute('data-nav-armed')) {
      // Already armed — normal flow, animations will run on slide change.
    } else if (idx !== 0 || frames[idx].classList.contains('is-current')) {
      // First non-zero nav OR re-asserting current: arm.
      deck.setAttribute('data-nav-armed', '');
    }
    for (let i = 0; i < frames.length; i++) {
      frames[i].classList.toggle('is-current', i === idx);
    }
    if (deck.dataset.mode === 'present') {
      scaleFrame(frames[idx]);
    } else {
      frames[idx].scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    if (updateHash !== false) {
      const newHash = '#' + (idx + 1);
      if (location.hash !== newHash) history.replaceState(null, '', newHash);
    }
    updateUI(deck, frames);
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
      '<div class="nav-hint">← →   翻页  ·  F 全屏</div>';
    return ui;
  }

  function updateUI(deck, frames) {
    const ui = document.querySelector('.deck-ui');
    if (!ui) return;
    const cur = currentIdx(frames);
    const total = frames.length;
    const isPresent = deck.dataset.mode === 'present';
    const isFullscreen = !!(document.fullscreenElement || document.webkitFullscreenElement);

    ui.querySelector('.cur').textContent   = pad(cur + 1);
    ui.querySelector('.total').textContent = pad(total);
    const pct = total > 0 ? ((cur + 1) / total) * 100 : 0;
    ui.querySelector('.deck-progress .bar').style.width = pct + '%';
    ui.querySelector('.ctl.fs .i-enter').style.display = isFullscreen ? 'none'  : 'block';
    ui.querySelector('.ctl.fs .i-exit').style.display  = isFullscreen ? 'block' : 'none';
    ui.querySelector('.deck-progress').style.display = isPresent ? 'block' : 'none';
    ui.querySelector('.deck-controls').style.display = isPresent ? 'flex'  : 'none';
    ui.querySelector('.nav-hint').style.display      = isPresent ? 'block' : 'none';
    ui.querySelector('.ctl.prev').disabled = cur <= 0;
    ui.querySelector('.ctl.next').disabled = cur >= total - 1;
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
