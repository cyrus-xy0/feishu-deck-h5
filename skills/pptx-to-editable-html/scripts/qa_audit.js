#!/usr/bin/env node
// qa_audit.js — multi-page QA screenshotter for a dual-background editable deck.
// Drives a HEADLESS Chrome over the raw DevTools Protocol (CDP) via a WebSocket —
// NO puppeteer dependency, just child_process + the built-in global WebSocket (Node 18+).
// For each requested page it sets #pageinp's value + fires a `change` event (the deck's
// own page-jump path), waits for the slide to settle, then captures a PNG to <out>/p{n}.png.
//
// Usage:
//   node qa_audit.js --url file:///abs/path/to/index.html --pages 1,6,11
//   node qa_audit.js --url http://127.0.0.1:8080/index.html --pages 1-12 --out ./qa --xl
//   node qa_audit.js --url file://$PWD/index.html --pages 1,6,11 --wait 2200 --port 9334 \
//        --chrome '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
//
// Flags (all have sane defaults except --url):
//   --url     file:// or http(s) URL of the deck's index.html            (REQUIRED)
//   --pages   1-based pages to shoot; comma list and/or N-M ranges, e.g. 1,6,11 or 1-12 or 1-3,9
//   --out     output dir, writes p{n}.png                                 (default ./qa)
//   --port    CDP remote-debugging port                                   (default 9334)
//   --chrome  Chrome/Chromium binary path        (default macOS '/Applications/Google Chrome.app/...')
//   --xl      flag: click #xlbtn after load to capture the 🌐 translate mode (body.xl) instead of view mode
//   --wait    settle ms per page after the page-jump, before capture      (default 1600)
//
// HARD-WON CAVEATS (do not relearn these the painful way):
//   (a) BIG BACKGROUND IMAGES SCREENSHOT BLACK if captured before they DECODE. A multi-MB
//       JPEG/PNG bg can take >=5s to decode in headless Chrome; a shot taken too early is
//       all-black. That is NOT a missing asset — verify the bg is actually being served by
//       curl-ing its URL and checking Content-Length (a real byte count = the asset is fine,
//       it just hadn't decoded yet). We pre-wait DECODE_MS (>=5s) after first load, and you
//       can raise --wait per page. Black p1.png almost always means "decode, not 404".
//   (b) NEVER `pkill` / `killall` Chrome — that nukes the USER's own browser windows. We spawn
//       Chrome with a DEDICATED --user-data-dir and only ever kill THAT spawned child pid
//       (chrome.kill). The dedicated profile also avoids colliding with a logged-in session.
//   (c) SOME SANDBOXES BLOCK HEADLESS CHROME NETWORK EGRESS (while curl still works). A remote
//       http(s) --url can hang/black out on bg fetches even though the host is reachable from the
//       shell. A LOCAL file:// MIRROR of the deck (index.html + assets on disk, or assets fetched
//       to local paths) is far more reliable for QA than a remote URL. Prefer file:// when in doubt.

const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

// ---- tiny argv parser (--key value, and bare --flag booleans) ----
function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) continue;
    const key = a.slice(2);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith('--')) { out[key] = true; }      // bare flag, e.g. --xl
    else { out[key] = next; i++; }
  }
  return out;
}

// "1,6,11" and/or "1-12" / "1-3,9" -> sorted unique 1-based ints
function parsePages(spec) {
  const set = new Set();
  for (const part of String(spec).split(',')) {
    const s = part.trim();
    if (!s) continue;
    const m = s.match(/^(\d+)-(\d+)$/);
    if (m) {
      let [, lo, hi] = m; lo = +lo; hi = +hi;
      if (lo > hi) [lo, hi] = [hi, lo];
      for (let n = lo; n <= hi; n++) set.add(n);
    } else if (/^\d+$/.test(s)) {
      set.add(+s);
    }
  }
  return [...set].sort((a, b) => a - b);
}

const args = parseArgs(process.argv.slice(2));

const URL_ = args.url;
if (!URL_ || URL_ === true) {
  console.error('ERROR: --url is required (file:// or http(s) URL of the deck index.html)');
  console.error("  e.g. node qa_audit.js --url file://$PWD/index.html --pages 1,6,11");
  process.exit(2);
}
const PAGES = parsePages(args.pages || '1');
const OUT = path.resolve(args.out && args.out !== true ? args.out : './qa');
const PORT = +(args.port && args.port !== true ? args.port : 9334);
const CHROME = (args.chrome && args.chrome !== true)
  ? args.chrome
  : '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const XL = !!args.xl;                                       // capture 🌐 translate mode (body.xl)
const WAIT = +(args.wait && args.wait !== true ? args.wait : 1600); // settle ms per page

const W = 1600, H = 900;                                    // 16:9-ish capture viewport
const DECODE_MS = 5500;                                     // caveat (a): give big bg images time to decode
// CAVEAT (b): dedicated, throwaway profile dir so we only ever touch OUR Chrome, never the user's.
const PROFILE = path.join(require('os').tmpdir(), `qa-audit-profile-${PORT}`);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function getJSON(p) { const r = await fetch(`http://127.0.0.1:${PORT}${p}`); return r.json(); }

(async () => {
  fs.mkdirSync(OUT, { recursive: true });

  // Spawn headless Chrome on its OWN profile + debugging port. about:blank first; we navigate via CDP.
  const chrome = spawn(CHROME, [
    '--headless', '--no-sandbox', '--disable-gpu', '--hide-scrollbars',
    `--user-data-dir=${PROFILE}`,                          // caveat (b): dedicated profile
    '--no-first-run', '--no-default-browser-check',
    '--disable-background-networking', '--disable-component-update',
    `--remote-debugging-port=${PORT}`,
    `--window-size=${W},${H}`,
    'about:blank',
  ], { stdio: 'ignore' });

  // CAVEAT (b): kill ONLY this spawned child — never pkill/killall Chrome.
  const killChrome = () => { try { chrome.kill('SIGKILL'); } catch (e) {} };

  // Wait for the DevTools endpoint to come up.
  let ready = false;
  for (let i = 0; i < 60; i++) {
    try { await getJSON('/json/version'); ready = true; break; } catch (e) { await sleep(250); }
  }
  if (!ready) { console.error('devtools not ready on port ' + PORT); killChrome(); process.exit(1); }

  // Attach to the first page target over a raw WebSocket (built-in global, Node 18+).
  const targets = await getJSON('/json');
  const page = targets.find((t) => t.type === 'page') || targets[0];
  const ws = new WebSocket(page.webSocketDebuggerUrl);

  let id = 0; const pending = {};
  const send = (method, params = {}) => new Promise((res) => {
    const mid = ++id; pending[mid] = res;
    ws.send(JSON.stringify({ id: mid, method, params }));
  });

  let onload; const loadDone = new Promise((r) => { onload = r; });
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending[m.id]) { pending[m.id](m.result); delete pending[m.id]; }
    if (m.method === 'Page.loadEventFired' && onload) { onload(); onload = null; }
  };

  try {
    await new Promise((r) => { ws.onopen = r; });
    await send('Page.enable');
    await send('Runtime.enable');
    await send('Emulation.setDeviceMetricsOverride', { width: W, height: H, deviceScaleFactor: 1, mobile: false });
    await send('Page.navigate', { url: URL_ });
    await Promise.race([loadDone, sleep(8000)]);            // load fires OR 8s ceiling
    await sleep(DECODE_MS);                                 // caveat (a): let the first big bg decode

    if (XL) {
      // 🌐 translate mode: click #xlbtn so body.xl shows the real (translatable) text layer.
      await send('Runtime.evaluate', {
        expression: "(function(){var b=document.getElementById('xlbtn');if(b)b.click();})()",
      });
      await sleep(800);
    }

    for (const n of PAGES) {
      // Jump via the deck's own page input: set #pageinp.value then dispatch a 'change' event.
      await send('Runtime.evaluate', {
        expression:
          `(function(){var p=document.getElementById('pageinp');` +
          `if(p){p.value='${n}';p.dispatchEvent(new Event('change'));}})()`,
      });
      await sleep(WAIT);                                    // per-page settle (raise for heavy bg)
      const shot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
      const file = path.join(OUT, `p${n}.png`);
      fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
      console.log('WROTE ' + file);
    }

    ws.close();
    killChrome();
    process.exit(0);
  } catch (e) {
    console.error('ERR', (e && e.message) || e);
    try { ws.close(); } catch (_) {}
    killChrome();
    process.exit(1);
  }
})().catch((e) => { console.error('ERR', (e && e.message) || e); process.exit(1); });
