/* deck-edit-mode.js — in-browser edit mode for a rendered feishu-deck HTML.
 *
 * Zero dependencies, no server. Drop the <script src=> tag into the deck HTML
 * and open via file://. Press E to enter edit mode, Esc to exit. Cmd/Ctrl+S
 * to save (File System Access API → in-place; else download).
 *
 * Edits supported in the v1:
 *   • Text leaves are contenteditable
 *   • Slide-frames are drag-reorderable
 *   • Save serializes the current DOM (minus edit-mode chrome) to disk
 */
(function () {
  'use strict';

  // ── state ──────────────────────────────────────────────────────────────
  let editMode = false;
  let bar = null;
  let dragSrc = null;
  let fileHandle = null;       // remembered after first save (FS Access API)
  let prevDeckMode = null;     // restore deck.dataset.mode on exit
  let prevIdleFade = null;     // restore feishu-deck.js idle-fade on exit
  let undoStack = [];          // snapshots for ⌘Z undo (simple, document-wide)
  const UNDO_DEPTH = 30;

  const deck   = document.querySelector('.deck');
  const isMac  = /Mac/i.test(navigator.platform);

  // ── identify text leaves to make contenteditable ──────────────────────
  function getTextLeaves() {
    if (!deck) return [];
    const leaves = new Set();
    const walker = document.createTreeWalker(
      deck,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode: (n) =>
          n.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT,
      }
    );
    let node;
    while ((node = walker.nextNode())) {
      const parent = node.parentElement;
      if (!parent) continue;
      // skip chrome / UI / non-content text
      if (parent.closest('style, script, .deck-ui, .edit-bar, .edit-toast, .wordmark, iframe')) continue;
      // skip elements whose computed display would hide them
      const tag = parent.tagName;
      if (tag === 'TITLE' || tag === 'NOSCRIPT') continue;
      leaves.add(parent);
    }
    return [...leaves];
  }

  // ── enter / exit edit mode ────────────────────────────────────────────
  function enterEditMode() {
    if (editMode) return;
    editMode = true;
    document.body.classList.add('deck-edit-mode');

    // Capture which slide the user was viewing in present mode so we can
    // scroll to it after switching layouts. Sources, in priority order:
    //   1. `.slide-frame.is-current` set by feishu-deck.js
    //   2. URL hash #N (1-indexed)
    //   3. slide 0
    let landIdx = 0;
    const cur = document.querySelector('.slide-frame.is-current');
    if (cur) {
      landIdx = [...document.querySelectorAll('.slide-frame')].indexOf(cur);
    } else {
      const m = location.hash.match(/^#(\d+)/);
      if (m) landIdx = Math.max(0, parseInt(m[1], 10) - 1);
    }

    // Switch deck to scroll mode so all slides are visible for reordering.
    if (deck) {
      prevDeckMode = deck.getAttribute('data-mode') || 'present';
      deck.setAttribute('data-mode', 'scroll');
    }
    // Suppress feishu-deck.js auto-fade of the present-mode chrome — we'll
    // hide it via CSS, but make sure it doesn't fight us.
    const deckUi = document.querySelector('.deck-ui');
    if (deckUi) {
      prevIdleFade = deckUi.style.opacity;
      deckUi.style.opacity = '0';
      deckUi.style.pointerEvents = 'none';
    }

    // contenteditable on every text leaf
    getTextLeaves().forEach((el) => {
      el.setAttribute('contenteditable', 'true');
      el.setAttribute('spellcheck', 'false');
    });

    // draggable on every slide-frame
    document.querySelectorAll('.slide-frame').forEach((sf) => {
      sf.setAttribute('draggable', 'true');
      sf.addEventListener('dragstart', onDragStart);
      sf.addEventListener('dragend',   onDragEnd);
      sf.addEventListener('dragover',  onDragOver);
      sf.addEventListener('drop',      onDrop);
    });

    // Disable iframes so they don't capture clicks while editing
    document.querySelectorAll('iframe').forEach((f) => {
      f.dataset.prevPointerEvents = f.style.pointerEvents || '';
      f.style.pointerEvents = 'none';
    });

    showEditBar();
    showSidebar();
    snapshot('enter');

    // Re-compute --fs-scale on every frame for the new (narrower) layout.
    // The framework's ResizeObserver observes document.documentElement, which
    // doesn't always fire on body-class / data-mode toggles → slide can keep
    // the old (wider) scale and overflow horizontally. Do it manually.
    // Also scroll to the slide the user was viewing in present mode.
    requestAnimationFrame(() => {
      refitFrames();
      const frames = document.querySelectorAll('.slide-frame');
      if (frames[landIdx]) {
        frames[landIdx].scrollIntoView({ block: 'start', behavior: 'auto' });
      }
    });
    // Listen for window resize while in edit mode and re-fit
    window.addEventListener('resize', refitFrames);

    // Diagnose save capability up front.
    //   • FS Access API supported → check IndexedDB for a previously-approved
    //     handle: if found, ⌘S is silent forever. Otherwise FIRST ⌘S shows
    //     the picker ONCE, then silent forever.
    //   • Not supported (Safari/FF) → ⌘S downloads a new file each time.
    (async () => {
      if (window.showOpenFilePicker) {
        let cached = false;
        try {
          const h = await idbGet(HANDLE_KEY());
          if (h) {
            const perm = await h.queryPermission({ mode: 'readwrite' });
            cached = (perm === 'granted');
          }
        } catch {}
        if (cached) {
          showToast('Edit mode · ⌘S 静默保存（已授权） · Esc 退出', 2500);
          console.log('[deck-edit-mode] save mode: FS Access API (handle cached, silent)');
        } else {
          showToast('Edit mode · 第一次 ⌘S 选当前文件授权一次,之后永远静默 · Esc 退出', 4000);
          console.log('[deck-edit-mode] save mode: FS Access API (picker once)');
        }
      } else {
        showToast('Edit mode · ⚠ 浏览器不支持原地保存 · ⌘S 会 download · Esc 退出', 4000);
        console.log('[deck-edit-mode] save mode: download fallback');
      }
    })();
  }

  function exitEditMode() {
    if (!editMode) return;
    editMode = false;
    document.body.classList.remove('deck-edit-mode');

    if (deck && prevDeckMode != null) {
      deck.setAttribute('data-mode', prevDeckMode);
      prevDeckMode = null;
    }
    const deckUi = document.querySelector('.deck-ui');
    if (deckUi) {
      deckUi.style.opacity = prevIdleFade || '';
      deckUi.style.pointerEvents = '';
      prevIdleFade = null;
    }

    document.querySelectorAll('[contenteditable]').forEach((el) => {
      el.removeAttribute('contenteditable');
      el.removeAttribute('spellcheck');
    });
    document.querySelectorAll('.slide-frame').forEach((sf) => {
      sf.removeAttribute('draggable');
      sf.removeEventListener('dragstart', onDragStart);
      sf.removeEventListener('dragend',   onDragEnd);
      sf.removeEventListener('dragover',  onDragOver);
      sf.removeEventListener('drop',      onDrop);
    });
    document.querySelectorAll('iframe').forEach((f) => {
      f.style.pointerEvents = f.dataset.prevPointerEvents || '';
      delete f.dataset.prevPointerEvents;
    });

    hideEditBar();
    hideSidebar();
    window.removeEventListener('resize', refitFrames);
    // Refit one more time so present mode picks up correct scale.
    requestAnimationFrame(refitFrames);
  }

  // Mirror of feishu-deck.js scaleFrame — compute --fs-scale per frame from
  // its current width/height. Safe to call any time; idempotent.
  function refitFrames() {
    document.querySelectorAll('.slide-frame').forEach((frame) => {
      const slide = frame.querySelector('.slide');
      if (!slide) return;
      const w = frame.clientWidth, h = frame.clientHeight;
      if (!w || !h) return;
      const scale = Math.min(w / 1920, h / 1080);
      slide.style.setProperty('--fs-scale', String(scale));
    });
  }

  // ── drag-reorder slide-frames ─────────────────────────────────────────
  // Drop indicator is a horizontal line BETWEEN slides (drop-above /
  // drop-below class on the hovered target), not an outline AROUND the
  // target. That way the user sees exactly which gap the slide will land in.
  function clearDropMarkers() {
    document.querySelectorAll('.drop-above, .drop-below').forEach((el) => {
      el.classList.remove('drop-above', 'drop-below');
    });
  }
  function onDragStart(e) {
    dragSrc = e.currentTarget;
    dragSrc.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', dragSrc.dataset.slideKey || '');
    snapshot('reorder');
  }
  function onDragEnd() {
    if (dragSrc) dragSrc.classList.remove('dragging');
    clearDropMarkers();
    dragSrc = null;
  }
  function onDragOver(e) {
    if (!dragSrc || e.currentTarget === dragSrc) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const target = e.currentTarget;
    const rect = target.getBoundingClientRect();
    const above = e.clientY < rect.top + rect.height / 2;
    clearDropMarkers();
    target.classList.add(above ? 'drop-above' : 'drop-below');
  }
  function onDrop(e) {
    e.preventDefault();
    if (!dragSrc) return;
    const target = e.currentTarget;
    if (target === dragSrc) {
      clearDropMarkers();
      return;
    }
    const rect = target.getBoundingClientRect();
    const before = e.clientY < rect.top + rect.height / 2;
    target.parentNode.insertBefore(dragSrc, before ? target : target.nextSibling);
    clearDropMarkers();
  }

  // ── undo stack ─────────────────────────────────────────────────────────
  function snapshot(reason) {
    undoStack.push(deck.innerHTML);
    if (undoStack.length > UNDO_DEPTH) undoStack.shift();
  }
  function undo() {
    if (undoStack.length < 2) return;        // need at least two to step back
    undoStack.pop();                          // discard current
    deck.innerHTML = undoStack[undoStack.length - 1];
    // re-attach editable + drag handlers on the new DOM
    if (editMode) {
      getTextLeaves().forEach((el) => el.setAttribute('contenteditable', 'true'));
      document.querySelectorAll('.slide-frame').forEach((sf) => {
        sf.setAttribute('draggable', 'true');
        sf.addEventListener('dragstart', onDragStart);
        sf.addEventListener('dragend',   onDragEnd);
        sf.addEventListener('dragover',  onDragOver);
        sf.addEventListener('drop',      onDrop);
      });
    }
    showToast('↶ undone', 700);
  }

  // ── save ──────────────────────────────────────────────────────────────
  function buildSavedHTML() {
    // Clone the documentElement so we don't disturb the live DOM.
    const clone = document.documentElement.cloneNode(true);
    // Strip edit-mode artifacts
    clone.querySelectorAll('[contenteditable]').forEach((el) => el.removeAttribute('contenteditable'));
    clone.querySelectorAll('[spellcheck]').forEach((el) => el.removeAttribute('spellcheck'));
    clone.querySelectorAll('[draggable]').forEach((el) => el.removeAttribute('draggable'));
    clone.querySelectorAll('.dragging, .drop-target, .drop-above, .drop-below').forEach((el) => {
      el.classList.remove('dragging', 'drop-target', 'drop-above', 'drop-below');
    });
    clone.querySelectorAll('.edit-bar, .edit-toast, .edit-sidebar').forEach((el) => el.remove());
    clone.classList.remove('deck-edit-mode');
    // Restore deck mode attribute to its pre-edit value
    const deckEl = clone.querySelector('.deck');
    if (deckEl && prevDeckMode) deckEl.setAttribute('data-mode', prevDeckMode);
    // Restore iframe pointer-events to original (we stored on the live DOM,
    // but the clone reflects the modified value; resetting in clone)
    clone.querySelectorAll('iframe').forEach((f) => {
      const orig = f.dataset && f.dataset.prevPointerEvents;
      if (orig) f.style.pointerEvents = orig;
      else f.style.removeProperty('pointer-events');
      if (f.dataset) delete f.dataset.prevPointerEvents;
    });
    return '<!DOCTYPE html>\n' + clone.outerHTML;
  }

  // First save: open a picker so user authorizes write to the current file.
  // To skip folder-by-folder navigation, we auto-copy the absolute path to
  // the clipboard right before the dialog appears, and show a giant toast
  // telling the user to ⌘⇧G → ⌘V → Enter in the picker. Result: 4 keystrokes
  // and no navigation, even on the very first save. Handle is then cached
  // in IndexedDB so this dance is one-time-ever.
  async function pickFileForOverwrite() {
    if (!window.showOpenFilePicker) return null;
    const absPath = decodeURIComponent(location.pathname);
    const currentName = absPath.split('/').pop() || 'index.html';

    // Copy the path so the user can paste it in the picker's "Go to Folder".
    let clipOk = false;
    try {
      await navigator.clipboard.writeText(absPath);
      clipOk = true;
    } catch (e) { /* clipboard blocked — fall back to manual instruction */ }

    showHelp(absPath, clipOk);

    try {
      const [h] = await window.showOpenFilePicker({
        multiple: false,
        types: [{ description: 'HTML deck', accept: { 'text/html': ['.html', '.htm'] } }],
        startIn: 'documents',
      });
      hideHelp();
      if (h.name !== currentName) {
        if (!confirm(`保存到 "${h.name}" 而不是 "${currentName}"?\n按取消重新选。`)) return null;
      }
      if ((await h.queryPermission({ mode: 'readwrite' })) !== 'granted') {
        if ((await h.requestPermission({ mode: 'readwrite' })) !== 'granted') return null;
      }
      return h;
    } catch (err) {
      hideHelp();
      if (err.name !== 'AbortError') console.warn(err);
      return null;
    }
  }

  // Help overlay that surfaces the ⌘⇧G shortcut + the path the user should
  // paste. Appears WHILE the picker is open so the user can read it through
  // their attention shift to the dialog.
  let helpOverlay = null;
  function showHelp(absPath, clipOk) {
    if (helpOverlay) hideHelp();
    helpOverlay = document.createElement('div');
    helpOverlay.className = 'edit-help-overlay';
    helpOverlay.innerHTML = `
      <div class="eho-card">
        <div class="eho-title">第一次保存 · 4 个按键搞定</div>
        <ol class="eho-steps">
          <li>picker 已弹出 → 按 <kbd>⌘</kbd>+<kbd>⇧</kbd>+<kbd>G</kbd></li>
          <li>路径${clipOk ? '已复制到剪贴板,按 <kbd>⌘</kbd>+<kbd>V</kbd> 粘贴' : '手动粘贴: <code class="eho-path"></code>'}</li>
          <li>按 <kbd>Enter</kbd></li>
          <li>授权后,以后 ⌘S 永远静默,不再弹这个</li>
        </ol>
        <div class="eho-path-wrap">
          <div class="eho-path-label">${clipOk ? '路径已在剪贴板:' : '路径:'}</div>
          <code class="eho-path">${absPath}</code>
        </div>
      </div>
    `;
    document.body.appendChild(helpOverlay);
    // also write the path into any .eho-path placeholders
    helpOverlay.querySelectorAll('.eho-path').forEach((el) => {
      if (!el.textContent) el.textContent = absPath;
    });
  }
  function hideHelp() {
    if (helpOverlay) helpOverlay.remove();
    helpOverlay = null;
  }

  // ── IndexedDB-persisted file handle ──────────────────────────────────
  // Goal: make the picker truly ONE-TIME-EVER (per browser profile, per
  // origin). The FileSystemHandle is stored in IndexedDB; on later visits
  // we retrieve it and call requestPermission — Chrome silently re-grants
  // if the user previously approved.
  const IDB_NAME = 'deck-edit-mode';
  const IDB_STORE = 'handles';
  function idbOpen() {
    return new Promise((resolve, reject) => {
      const r = indexedDB.open(IDB_NAME, 1);
      r.onupgradeneeded = () => r.result.createObjectStore(IDB_STORE);
      r.onsuccess = () => resolve(r.result);
      r.onerror   = () => reject(r.error);
    });
  }
  function idbGet(key) {
    return idbOpen().then((db) => new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, 'readonly');
      const req = tx.objectStore(IDB_STORE).get(key);
      req.onsuccess = () => resolve(req.result);
      req.onerror   = () => reject(req.error);
    }));
  }
  function idbPut(key, value) {
    return idbOpen().then((db) => new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, 'readwrite');
      tx.objectStore(IDB_STORE).put(value, key);
      tx.oncomplete = () => resolve();
      tx.onerror    = () => reject(tx.error);
    }));
  }
  function idbDel(key) {
    return idbOpen().then((db) => new Promise((resolve, reject) => {
      const tx = db.transaction(IDB_STORE, 'readwrite');
      tx.objectStore(IDB_STORE).delete(key);
      tx.oncomplete = () => resolve();
      tx.onerror    = () => reject(tx.error);
    }));
  }
  const HANDLE_KEY = () => 'h:' + location.pathname;   // per-file key

  async function tryRestoreHandle() {
    if (!('indexedDB' in window)) return null;
    try {
      const h = await idbGet(HANDLE_KEY());
      if (!h) return null;
      // re-grant permission silently if already approved; else prompt now
      let perm = await h.queryPermission({ mode: 'readwrite' });
      if (perm === 'granted') return h;
      perm = await h.requestPermission({ mode: 'readwrite' });
      return perm === 'granted' ? h : null;
    } catch (e) {
      console.warn('[deck-edit-mode] handle restore failed:', e);
      return null;
    }
  }

  async function save() {
    const html = buildSavedHTML();

    // Path 1: File System Access API — overwrite the SAME file silently
    // after the first authorization. Handle persists in IndexedDB so the
    // picker is truly one-time-ever per browser profile.
    if (window.showOpenFilePicker) {
      try {
        if (!fileHandle) {
          // Try to restore a previously-approved handle for THIS path
          fileHandle = await tryRestoreHandle();
        }
        if (!fileHandle) {
          // First-ever save — show picker once. After the user grants
          // permission, the handle is cached in IDB and the picker won't
          // come back even after page reload.
          fileHandle = await pickFileForOverwrite();
          if (!fileHandle) return;
          await idbPut(HANDLE_KEY(), fileHandle);
        } else {
          // re-check permission (some browsers expire it on tab inactive)
          const perm = await fileHandle.queryPermission({ mode: 'readwrite' });
          if (perm !== 'granted') {
            if ((await fileHandle.requestPermission({ mode: 'readwrite' })) !== 'granted') {
              fileHandle = null;  // permission revoked — re-pick next time
              await idbDel(HANDLE_KEY());
              return;
            }
          }
        }
        const writable = await fileHandle.createWritable();
        await writable.write(html);
        await writable.close();
        showToast('✓ Saved to ' + fileHandle.name, 1200);
        return;
      } catch (err) {
        if (err.name === 'AbortError') return;
        console.warn('FS Access API failed, falling back to download:', err);
        fileHandle = null;
        try { await idbDel(HANDLE_KEY()); } catch {}
      }
    }

    // Fallback: download (Safari / Firefox / non-secure context)
    const blob = new Blob([html], { type: 'text/html' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = decodeURIComponent(location.pathname.split('/').pop() || 'index.html');
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
    showToast('↓ Downloaded ' + a.download + ' (浏览器不支持原地保存)', 2200);
  }

  // ── UI bar ─────────────────────────────────────────────────────────────
  function showEditBar() {
    if (bar) return;
    bar = document.createElement('div');
    bar.className = 'edit-bar';
    bar.innerHTML = `
      <span class="edit-bar-label">📝 Edit mode</span>
      <span class="edit-bar-hint">click text · drag slides · ${isMac ? '⌘' : 'Ctrl'}S save · Esc exit</span>
      <button class="edit-bar-btn edit-bar-save" title="${isMac ? '⌘' : 'Ctrl'}S">💾 Save</button>
      <button class="edit-bar-btn edit-bar-exit" title="Esc">✕</button>
    `;
    document.body.appendChild(bar);
    bar.querySelector('.edit-bar-save').onclick = save;
    bar.querySelector('.edit-bar-exit').onclick = exitEditMode;
  }
  function hideEditBar() {
    if (bar) bar.remove();
    bar = null;
  }

  // ── left sidebar: slide list (click to scroll + drag to reorder) ───────
  let sidebar = null;
  let intersectionObs = null;

  function showSidebar() {
    if (sidebar) return;
    sidebar = document.createElement('aside');
    sidebar.className = 'edit-sidebar';
    sidebar.innerHTML = `
      <div class="edit-sidebar-header">
        <span class="es-title">Slides</span>
        <span class="es-count"></span>
        <button class="es-refresh" title="Refresh list">↻</button>
      </div>
      <ol class="edit-sidebar-list"></ol>
      <div class="edit-sidebar-foot">拖动条目重排 · 点击跳转</div>
    `;
    document.body.appendChild(sidebar);
    sidebar.querySelector('.es-refresh').onclick = rebuildSidebar;
    rebuildSidebar();
  }
  function hideSidebar() {
    if (intersectionObs) { intersectionObs.disconnect(); intersectionObs = null; }
    if (sidebar) sidebar.remove();
    sidebar = null;
  }

  function rebuildSidebar() {
    if (!sidebar) return;
    const list = sidebar.querySelector('.edit-sidebar-list');
    const frames = [...document.querySelectorAll('.slide-frame')];
    list.innerHTML = frames.map((sf, i) => {
      const key = sf.querySelector('.slide')?.dataset.slideKey || '';
      const label = sf.querySelector('.slide')?.dataset.screenLabel || `Slide ${i + 1}`;
      return `
        <li class="es-item" data-key="${escapeAttr(key)}" draggable="true">
          <span class="es-num">${String(i + 1).padStart(2, '0')}</span>
          <span class="es-label" title="${escapeAttr(label)}">${escapeHtml(label)}</span>
        </li>`;
    }).join('');
    sidebar.querySelector('.es-count').textContent = `${frames.length}`;

    // wire click-to-scroll + drag
    list.querySelectorAll('.es-item').forEach((li) => {
      li.addEventListener('click', () => {
        const key = li.dataset.key;
        const target = document.querySelector(`.slide-frame .slide[data-slide-key="${cssEscape(key)}"]`);
        if (target) target.closest('.slide-frame').scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
      li.addEventListener('dragstart', onSidebarDragStart);
      li.addEventListener('dragend',   onSidebarDragEnd);
      li.addEventListener('dragover',  onSidebarDragOver);
      li.addEventListener('drop',      onSidebarDrop);
    });

    // active-slide highlight via IntersectionObserver
    if (intersectionObs) intersectionObs.disconnect();
    intersectionObs = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const key = entry.target.querySelector('.slide')?.dataset.slideKey;
        if (!key) return;
        sidebar.querySelectorAll('.es-item').forEach((li) => {
          li.classList.toggle('is-active', li.dataset.key === key);
        });
      });
    }, { rootMargin: '-40% 0px -40% 0px', threshold: 0 });
    frames.forEach((f) => intersectionObs.observe(f));
  }

  let sbDragSrc = null;
  function onSidebarDragStart(e) {
    sbDragSrc = e.currentTarget;
    sbDragSrc.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', sbDragSrc.dataset.key);
    snapshot('sidebar-reorder');
  }
  function onSidebarDragEnd() {
    if (sbDragSrc) sbDragSrc.classList.remove('dragging');
    clearDropMarkers();
    sbDragSrc = null;
  }
  function onSidebarDragOver(e) {
    if (!sbDragSrc || e.currentTarget === sbDragSrc) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const target = e.currentTarget;
    const rect = target.getBoundingClientRect();
    const above = e.clientY < rect.top + rect.height / 2;
    clearDropMarkers();
    target.classList.add(above ? 'drop-above' : 'drop-below');
  }
  function onSidebarDrop(e) {
    e.preventDefault();
    if (!sbDragSrc) return;
    const target = e.currentTarget;
    if (target === sbDragSrc) { clearDropMarkers(); return; }
    const rect = target.getBoundingClientRect();
    const before = e.clientY < rect.top + rect.height / 2;
    // Move both: the sidebar <li> AND the corresponding .slide-frame
    target.parentNode.insertBefore(sbDragSrc, before ? target : target.nextSibling);
    const srcFrame = document.querySelector(`.slide-frame .slide[data-slide-key="${cssEscape(sbDragSrc.dataset.key)}"]`)
                       ?.closest('.slide-frame');
    const dstFrame = document.querySelector(`.slide-frame .slide[data-slide-key="${cssEscape(target.dataset.key)}"]`)
                       ?.closest('.slide-frame');
    if (srcFrame && dstFrame && srcFrame !== dstFrame) {
      dstFrame.parentNode.insertBefore(srcFrame, before ? dstFrame : dstFrame.nextSibling);
    }
    // renumber the badge after reorder
    [...sidebar.querySelectorAll('.es-item')].forEach((li, i) => {
      li.querySelector('.es-num').textContent = String(i + 1).padStart(2, '0');
    });
    clearDropMarkers();
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }
  function escapeAttr(s) { return escapeHtml(s); }
  function cssEscape(s) { return (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/"/g, '\\"'); }

  function showToast(msg, ms) {
    const t = document.createElement('div');
    t.className = 'edit-toast';
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), ms || 1200);
  }

  // ── global keyboard handler (capture phase to override feishu-deck.js) ─
  document.addEventListener('keydown', (e) => {
    // Don't intercept when typing in contenteditable / input / textarea
    const inField = e.target && (
      e.target.isContentEditable ||
      e.target.tagName === 'INPUT' ||
      e.target.tagName === 'TEXTAREA'
    );

    // E to enter edit mode (only when NOT typing)
    if (!editMode && !inField && e.key === 'e' &&
        !e.metaKey && !e.ctrlKey && !e.altKey && !e.shiftKey) {
      e.preventDefault();
      enterEditMode();
      return;
    }
    // Esc to exit (even when typing — Esc blurs the editable first by browser,
    // then we catch a second Esc to actually exit. For convenience we just
    // exit on any Esc while in edit mode.)
    if (editMode && e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      // blur active editable, then exit
      if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
      exitEditMode();
      return;
    }
    // ⌘S / Ctrl+S to save (in edit mode)
    if (editMode && (e.metaKey || e.ctrlKey) && e.key === 's') {
      e.preventDefault();
      e.stopPropagation();
      save();
      return;
    }
    // ⌘Z / Ctrl+Z to undo last reorder (text undo is browser-native)
    if (editMode && !inField && (e.metaKey || e.ctrlKey) && e.key === 'z' && !e.shiftKey) {
      e.preventDefault();
      undo();
      return;
    }

    // In edit mode, swallow nav keys so feishu-deck.js doesn't jump slides
    // while user is editing. Allow them only when NOT in a contenteditable.
    if (editMode && !inField &&
        ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', ' ',
         'PageUp', 'PageDown', 'Home', 'End'].includes(e.key)) {
      e.stopPropagation();
    }
  }, true);

  // ── snapshot on every text input (capped, for undo) ───────────────────
  let inputDebounce = null;
  document.addEventListener('input', (e) => {
    if (!editMode) return;
    if (!e.target || !e.target.isContentEditable) return;
    clearTimeout(inputDebounce);
    inputDebounce = setTimeout(() => snapshot('input'), 600);
  });

  // ── expose a tiny API to the page (useful for debugging / bookmarklets) ──
  window.deckEdit = {
    enter: enterEditMode,
    exit:  exitEditMode,
    save:  save,
    undo:  undo,
  };
})();
