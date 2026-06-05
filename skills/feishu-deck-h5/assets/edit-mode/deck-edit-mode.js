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
  const DOWNLOAD_REQUESTED = { download: true };

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
      // Only a TRUE leaf — every child node is text or <br> — may become
      // contenteditable. A MIXED container (text + child elements, e.g.
      // `<h2>标题<span class="tag">NEW</span></h2>`) would let an edit or paste
      // delete/merge its child elements → structural corruption persisted on
      // save. Skip those (their inner text leaves are still walked separately).
      if ([...parent.childNodes].every((c) => c.nodeType === 3 || c.nodeName === 'BR')) {
        leaves.add(parent);
      }
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

    // Force PLAIN-TEXT paste into editables (#81): rich HTML pasted into a
    // contenteditable would be serialized verbatim into the saved index.html —
    // stored XSS / structural corruption in the delivered deck. One delegated,
    // once-attached handler strips formatting to text.
    if (!deck.dataset.editPasteGuard) {
      deck.dataset.editPasteGuard = '1';
      deck.addEventListener('paste', (e) => {
        const ed = e.target && e.target.closest && e.target.closest('[contenteditable="true"]');
        if (!ed) return;
        e.preventDefault();
        const cd = e.clipboardData || window.clipboardData;
        const text = cd ? cd.getData('text/plain') : '';
        const sel = window.getSelection();
        if (sel && sel.rangeCount) {
          const r = sel.getRangeAt(0);
          r.deleteContents();
          r.insertNode(document.createTextNode(text));
          r.collapse(false);
          sel.removeAllRanges();
          sel.addRange(r);
        }
      });
    }

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
            if (perm === 'granted') {
              fileHandle = h;
              cached = true;
            }
          }
        } catch {}
        if (cached) {
          showToast('Edit mode · ⌘S 静默保存（已授权） · Esc 退出', 2500);
          console.log('[deck-edit-mode] save mode: FS Access API (handle cached, silent)');
        } else {
          showToast('Edit mode · 第一次保存需授权当前 HTML 文件 · Esc 退出', 4000);
          console.log('[deck-edit-mode] save mode: FS Access API (picker once)');
        }
        updateSaveButton();
      } else {
        showToast('Edit mode · ⚠ 浏览器不支持原地保存 · ⌘S 会 download · Esc 退出', 4000);
        console.log('[deck-edit-mode] save mode: download fallback');
        updateSaveButton();
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
    // data-slide-key lives on the inner .slide, NOT the dragged .slide-frame —
    // reading dragSrc.dataset.slideKey always gave '' (empty drag payload).
    e.dataTransfer.setData('text/plain', dragSrc.querySelector('.slide')?.dataset.slideKey || '');
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
    // (#246) sync the sidebar order + numbering to the new frame order (and
    // re-bind the IntersectionObserver to the live frames). A canvas drag used
    // to leave the sidebar stale relative to the canvas.
    rebuildSidebar();
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
      // innerHTML restore wiped the inline --fs-scale refitFrames set + left the
      // sidebar's IntersectionObserver bound to detached frames; restore both so
      // undo leaves a fully-working editor, not unscaled slides + a stale
      // sidebar. (#82 — the real glitch; the deeper innerHTML-vs-documentElement
      // scope question is moot here since all editable state lives in .deck.)
      refitFrames();
      rebuildSidebar();
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
    clone.querySelectorAll('.edit-bar, .edit-toast, .edit-sidebar, .fs-presenter').forEach((el) => el.remove());
    // `clone` is the <html> element; the deck-edit-mode class lives on <body>.
    // Strip it from BOTH so a deck saved while in edit mode never bakes the
    // class in — otherwise the blue dashed slide-frame outline + hidden present
    // chrome persist when the saved file is reopened.
    clone.classList.remove('deck-edit-mode');
    const cloneBody = clone.querySelector('body');
    if (cloneBody) cloneBody.classList.remove('deck-edit-mode');
    // Restore deck mode attribute to its pre-edit value
    const deckEl = clone.querySelector('.deck');
    // Default to 'present' when prevDeckMode is null (save() invoked outside edit
    // mode) so the saved file never bakes in the edit-mode 'scroll' state. (#305)
    if (deckEl) deckEl.setAttribute('data-mode', prevDeckMode || 'present');
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

  // First save: explain the browser permission model before opening the native
  // file picker. The native macOS picker labels the action "Open" even though
  // the browser is asking for write permission; showing this dialog first keeps
  // the instructions readable instead of hiding them behind the system window.
  async function pickFileForOverwrite() {
    if (!window.showOpenFilePicker) return null;
    const absPath = decodeURIComponent(location.pathname);
    const currentName = absPath.split('/').pop() || 'index.html';

    const action = await showFirstSaveDialog(absPath, currentName);
    if (action === 'download') return DOWNLOAD_REQUESTED;
    if (action !== 'choose') return null;

    try {
      const [h] = await window.showOpenFilePicker({
        multiple: false,
        types: [{ description: 'HTML deck', accept: { 'text/html': ['.html', '.htm'] } }],
        startIn: 'documents',
      });
      if (h.name !== currentName) {
        const ok = await confirmDifferentFile(h.name, currentName);
        if (!ok) return null;
      }
      if ((await h.queryPermission({ mode: 'readwrite' })) !== 'granted') {
        if ((await h.requestPermission({ mode: 'readwrite' })) !== 'granted') return null;
      }
      return h;
    } catch (err) {
      if (err.name !== 'AbortError') console.warn(err);
      return null;
    }
  }

  function showFirstSaveDialog(absPath, currentName) {
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.className = 'edit-save-dialog';
      overlay.setAttribute('role', 'dialog');
      overlay.setAttribute('aria-modal', 'true');
      overlay.innerHTML = `
        <div class="esd-card">
          <div class="esd-eyebrow">第一次保存需要浏览器授权</div>
          <h2 class="esd-title">选择当前 HTML 文件来授权覆盖保存</h2>
          <p class="esd-copy">
            Chrome 不能直接改写你用 file:// 打开的文件。下一步系统窗口会显示“打开”,
            但这里的含义是把写入权限授予当前 deck；选中同一个 HTML 一次后,
            后续 ${isMac ? '⌘' : 'Ctrl'}S 会静默保存。
          </p>
          <ol class="esd-steps">
            <li>点下面的“选择当前 HTML 文件”。</li>
            <li>在系统窗口里选中 <strong>${escapeHtml(currentName)}</strong>。</li>
            <li>系统按钮即使写着“打开”,也代表授权这个文件。</li>
          </ol>
          <div class="esd-path-wrap">
            <div class="esd-path-label">当前文件路径</div>
            <code class="esd-path">${escapeHtml(absPath)}</code>
          </div>
          <div class="esd-status" aria-live="polite"></div>
          <div class="esd-actions">
            <button class="esd-btn esd-btn-secondary" type="button" data-action="copy">复制路径</button>
            <button class="esd-btn esd-btn-secondary" type="button" data-action="download">下载副本</button>
            <button class="esd-btn esd-btn-secondary" type="button" data-action="cancel">取消</button>
            <button class="esd-btn esd-btn-primary" type="button" data-action="choose">选择当前 HTML 文件</button>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);

      const status = overlay.querySelector('.esd-status');
      const cleanup = (result) => {
        overlay.remove();
        resolve(result);
      };

      overlay.querySelector('[data-action="choose"]').addEventListener('click', () => cleanup('choose'));
      overlay.querySelector('[data-action="download"]').addEventListener('click', () => cleanup('download'));
      overlay.querySelector('[data-action="cancel"]').addEventListener('click', () => cleanup('cancel'));
      overlay.querySelector('[data-action="copy"]').addEventListener('click', async () => {
        try {
          await navigator.clipboard.writeText(absPath);
          status.textContent = '路径已复制。系统窗口里可用 ⌘⇧G 后粘贴跳转。';
        } catch {
          status.textContent = '浏览器未允许复制,请手动选中上方路径复制。';
        }
      });
    });
  }

  function confirmDifferentFile(pickedName, currentName) {
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.className = 'edit-save-dialog';
      overlay.setAttribute('role', 'dialog');
      overlay.setAttribute('aria-modal', 'true');
      overlay.innerHTML = `
        <div class="esd-card esd-card-small">
          <div class="esd-eyebrow">确认保存目标</div>
          <h2 class="esd-title">你选中的不是当前 HTML 文件</h2>
          <p class="esd-copy">
            当前文件是 <strong>${escapeHtml(currentName)}</strong>,你选中了
            <strong>${escapeHtml(pickedName)}</strong>。继续会把修改写入选中的文件。
          </p>
          <div class="esd-actions">
            <button class="esd-btn esd-btn-secondary" type="button" data-action="cancel">取消</button>
            <button class="esd-btn esd-btn-primary" type="button" data-action="confirm">继续保存</button>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);
      const cleanup = (result) => {
        overlay.remove();
        resolve(result);
      };
      overlay.querySelector('[data-action="cancel"]').addEventListener('click', () => cleanup(false));
      overlay.querySelector('[data-action="confirm"]').addEventListener('click', () => cleanup(true));
    });
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
          if (fileHandle === DOWNLOAD_REQUESTED) {
            downloadHtml(html, 'download-copy');
            return;
          }
          if (!fileHandle) return;
          await idbPut(HANDLE_KEY(), fileHandle);
          updateSaveButton();
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
        updateSaveButton();
        return;
      } catch (err) {
        if (err.name === 'AbortError') return;
        // A post-pick write FAILURE (disk full, file moved/locked, permission
        // revoked mid-write) — NOT "unsupported". Surface it honestly and
        // download a copy so the edits aren't silently lost. (#83)
        console.warn('FS Access API write failed:', err);
        fileHandle = null;
        try { await idbDel(HANDLE_KEY()); } catch {}
        downloadHtml(html, 'save-failed');
        return;
      }
    }

    // Fallback: download — browser genuinely lacks the FS Access API
    // (Safari / Firefox / non-secure context)
    downloadHtml(html, 'fallback');
  }

  function downloadHtml(html, reason) {
    const blob = new Blob([html], { type: 'text/html' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = decodeURIComponent(location.pathname.split('/').pop() || 'index.html');
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
    const suffix = reason === 'download-copy' ? ' (未覆盖原文件)'
                 : reason === 'save-failed'   ? ' (原地保存失败, 已下载副本)'
                 : ' (浏览器不支持原地保存)';
    showToast('↓ Downloaded ' + a.download + suffix, 2200);
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
    updateSaveButton();
  }
  function hideEditBar() {
    if (bar) bar.remove();
    bar = null;
  }
  function updateSaveButton() {
    if (!bar) return;
    const btn = bar.querySelector('.edit-bar-save');
    if (!btn) return;
    if (!window.showOpenFilePicker) {
      btn.textContent = '↓ Download';
      btn.title = '浏览器不支持原地覆盖保存,将下载 HTML 副本';
    } else if (fileHandle) {
      btn.textContent = '💾 Save';
      btn.title = `${isMac ? '⌘' : 'Ctrl'}S · 已授权,直接覆盖当前 HTML`;
    } else {
      btn.textContent = '🔐 Authorize Save';
      btn.title = '第一次保存需选择当前 HTML 文件授权覆盖保存';
    }
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
      const slide = sf.querySelector('.slide');
      const key = slide?.dataset.slideKey || '';
      const label = slide?.dataset.screenLabel || `Slide ${i + 1}`;
      // screen_label is "NN name" (baked leading number) — strip it so it isn't
      // shown twice next to the live .es-num (which also drifts after reorder).
      const name = label.replace(/^\s*\d[\w-]*\s+/, '') || label;
      const hidden = !!slide?.hasAttribute('data-hidden');
      return `
        <li class="es-item${hidden ? ' es-hidden' : ''}" data-key="${escapeAttr(key)}" draggable="true">
          <div class="es-row">
            <span class="es-num">${String(i + 1).padStart(2, '0')}</span>
            <span class="es-label" title="${escapeAttr(label)}">${escapeHtml(name)}</span>
            <button class="es-eye" type="button" tabindex="-1"
                    title="放映时隐藏/显示这一页(隐藏页仍可用直链访问)" aria-label="toggle hidden">
              <svg class="i-eye" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z"/><circle cx="12" cy="12" r="3"/></svg>
              <svg class="i-eye-off" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
            </button>
          </div>
          <div class="es-thumb" aria-hidden="true"></div>
        </li>`;
    }).join('');
    sidebar.querySelector('.es-count').textContent = `${frames.length}`;

    // wire click-to-scroll + drag + build the live thumbnail preview
    list.querySelectorAll('.es-item').forEach((li, i) => {
      buildThumb(li.querySelector('.es-thumb'), frames[i] && frames[i].querySelector('.slide'));
      li.addEventListener('click', () => {
        const key = li.dataset.key;
        const target = document.querySelector(`.slide-frame .slide[data-slide-key="${cssEscape(key)}"]`);
        if (target) target.closest('.slide-frame').scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
      const eye = li.querySelector('.es-eye');
      if (eye) eye.addEventListener('click', (e) => {
        e.stopPropagation();           // don't trigger click-to-scroll
        toggleSlideHidden(li.dataset.key, li);
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

  // Toggle 隐藏页 from the sidebar eye button. Flips `data-hidden` on the
  // slide (feishu-deck.js reads it to skip the slide in present-mode 翻页). The
  // attribute lives in the .slide DOM, so the existing ⌘S save serializes it
  // into the HTML — durable, no extra plumbing. Undoable via the snapshot stack.
  function toggleSlideHidden(key, li) {
    const slide = document.querySelector(
      `.slide-frame .slide[data-slide-key="${cssEscape(key)}"]`);
    if (!slide) return;
    snapshot('toggle-hidden');
    const nowHidden = !slide.hasAttribute('data-hidden');
    if (nowHidden) slide.setAttribute('data-hidden', '');
    else           slide.removeAttribute('data-hidden');
    li.classList.toggle('es-hidden', nowHidden);   // CSS swaps eye ↔ eye-off icon
    showToast(nowHidden
      ? `已隐藏「${key}」· 放映翻页跳过(${isMac ? '⌘' : 'Ctrl'}S 保存)`
      : `已取消隐藏「${key}」`, 2200);
  }

  // Build a live thumbnail preview (PPT/Keynote slide navigator). Clone the real
  // 1920×1080 `.slide` and scale it into the 16:9 thumb box — its own CSS renders
  // a faithful mini-preview, fully offline, no rasterization. The clone lives
  // OUTSIDE any `.slide-frame`, so the `.slide-frame.is-current` reveal rule never
  // hides its children. We must restore the sizing that `.slide-frame .slide`
  // normally provides (1920×1080 + scale), and neutralize heavy embeds.
  function buildThumb(thumbEl, slide) {
    if (!thumbEl || !slide) return;
    thumbEl.textContent = '';
    const clone = slide.cloneNode(true);
    clone.removeAttribute('id');
    clone.querySelectorAll('[id]').forEach((e) => e.removeAttribute('id'));
    clone.querySelectorAll('[contenteditable]').forEach((e) => e.removeAttribute('contenteditable'));
    // iframes/videos: don't reload heavy embeds N× in the list — swap for a tile
    clone.querySelectorAll('iframe, video').forEach((el) => {
      const ph = document.createElement('div');
      ph.className = 'es-thumb-embed';
      el.replaceWith(ph);
    });
    clone.style.cssText =
      'position:absolute;top:0;left:0;margin:0;width:1920px;height:1080px;' +
      'transform-origin:top left;pointer-events:none;';
    thumbEl.appendChild(clone);
    // thumbEl is in the DOM → clientWidth is live; scale 1920 down to fit.
    const w = thumbEl.clientWidth || 224;
    clone.style.transform = 'scale(' + (w / 1920) + ')';
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

    // Ignore keystrokes mid-IME-composition (CJK candidate window): a raw
    // Escape/Enter here belongs to the IME, not our shortcuts. (#724)
    if (e.isComposing || e.keyCode === 229) return;

    const saveDialog = document.querySelector('.edit-save-dialog');
    if (saveDialog && e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      saveDialog.querySelector('[data-action="cancel"]')?.click();
      return;
    }

    // E to enter edit mode (only when NOT typing)
    if (!editMode && !inField && e.key.toLowerCase() === 'e' &&
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
    if (editMode && (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 's') {
      e.preventDefault();
      e.stopPropagation();
      save();
      return;
    }
    // ⌘Z / Ctrl+Z to undo last reorder (text undo is browser-native)
    if (editMode && !inField && (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) {
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

  // ── boot: never start in edit-mode visual state ───────────────────────
  // Real edit mode is only ever entered via enterEditMode() (which sets the
  // editMode flag). A `deck-edit-mode` class on <body> at load time is stale —
  // baked in by an older authoring template or by a deck saved before the
  // buildSavedHTML fix. Left alone it keeps the blue dashed slide-frame outline
  // and hides the present-mode chrome with no way to dismiss it (Esc is a no-op
  // while editMode is false). Strip it on load so the deck opens clean; the
  // user still enters edit mode normally with E. This also self-heals decks
  // that were already delivered with the class baked in.
  if (document.body && document.body.classList.contains('deck-edit-mode')) {
    document.body.classList.remove('deck-edit-mode');
  }

  // ── expose a tiny API to the page (useful for debugging / bookmarklets) ──
  window.deckEdit = {
    enter: enterEditMode,
    exit:  exitEditMode,
    save:  save,
    undo:  undo,
  };
})();
