# QA-audit: screenshotting a finished deck

`scripts/qa_audit.js` is the **last gate** before you hand a deck off. The deck
itself is correct by construction (view mode = the original render, so view-mode
fidelity is never in question), but the things that *do* break — 重影, 折行,
丢图, 字号不一致, 金句被压暗 — are **visual**, and the only way to catch them is
to look at the rendered pixels of every page. This script renders any set of
pages to PNG so you can eyeball them, or feed them back into the model.

## The headless multi-page screenshot method

No puppeteer. The script spawns a headless Chrome, talks to it over **CDP via a
raw global WebSocket** (Node 18+, same approach as `faas_store.js`'s
self-contained style), and drives the deck's *own* navigation to walk pages:

```
spawn headless Chrome (dedicated --user-data-dir)
   │  GET http://127.0.0.1:<port>/json   → discover the page target's webSocketDebuggerUrl
   ▼
WebSocket(ws://…)  ─ Page.navigate(url) ─ wait for load + DECODE_MS settle
   │  for each requested page n:
   │     Runtime.evaluate:  #pageinp.value = n; dispatch 'change'   (the deck's page-jump)
   │     wait --wait ms to settle
   │     Page.captureScreenshot  → write <out>/p{n}.png
   ▼
chrome.kill()  (only THAT spawned child pid — see caveat b)
```

Page-jump reuses the deck's built-in path: set `#pageinp.value = n` then fire a
`change` event — no scrolling, no guessing slide offsets. `--xl` clicks `#xlbtn`
once before the loop so you capture the **🌐 翻译模式 / `body.xl`** state (visible
rebuilt text instead of the original image) — that's where 折行 and 字号 problems
actually surface, since view mode is always the pristine image.

### CLI

```bash
node scripts/qa_audit.js --url <file:// or http(s) URL of index.html>   # REQUIRED
  --pages 1,6,11        # 1-based; comma list AND/OR N-M ranges, e.g. 1-12 or 1-3,9 (default 1)
  --out ./qa            # output dir, writes p{n}.png (default ./qa)
  --port 9334           # CDP remote-debugging port (default 9334)
  --chrome '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
  --xl                  # bare flag: click #xlbtn to capture 翻译态 / body.xl
  --wait 1600           # settle ms per page before capture (default 1600)
```

`--url` is mandatory (exits with a usage hint if missing). `parsePages`
dedupes + sorts, so `--pages 1-12` and `--pages 3,1,3,2` both behave. Typical
runs:

```bash
# audit the whole deck from a local mirror
node scripts/qa_audit.js --url file:///abs/path/to/deck/index.html --pages 1-18 --out ./qa
# audit just the 翻译态 of the金句 pages, give heavy bg pages more settle time
node scripts/qa_audit.js --url file://…/index.html --pages 2,7,14 --xl --wait 6000 --out ./qa-xl
```

## WHAT to look for

Walk every `p{n}.png` and check, per page:

- **重影 (ghosting)** — old baked text showing *through* an edited box. The whole
  dual-background architecture exists to prevent this (each `.tb`'s background is
  the no-text crop of that region — see `architecture.md`), so any ghost means a
  box's `--nt` mask is mis-sized/mis-positioned, or a `.tb-title` that shows
  rebuilt text in both states isn't covering the original cleanly. Look hardest
  at titles and any edited/`.dirty` box.
- **overflow / 折行 (overflow / unwanted line-wrap)** — rebuilt text in edit/翻译
  态 spilling its box or wrapping to an extra line. Most common on titles:
  `.tb-title` is **excluded from `--fit` autofit**, and PingFang (the rebuild
  font) is wider than the original, so a one-line PPT title can wrap. Fix is
  manual (smaller `size` or wider `width` on that frame), not automatic.
- **丢图 (missing image)** — a page that's blank/black where a `bg` should be.
  **But first rule out the decode race** (caveat a) — a black `p1.png` is almost
  always "hadn't decoded yet," not a 404.
- **字号不一致 (inconsistent font size)** — sibling frames that should match (e.g.
  two body columns, a row of stat numbers) rendering at visibly different sizes.
  Often a per-frame `--fit` floor (0.65) kicked in on one box but not its twin;
  reconcile by widening the cramped box or hand-setting `size`.
- **金句压暗 (hero/pull-quote dimmed)** — the big 金句 / hero line rendering darker
  or lower-contrast than intended, usually a scrim or overlay sitting on top, or
  the wrong (dark) image variant showing. Compare against the source slide.

## Caveats (read before trusting a screenshot)

**(a) Big background images need ≥5s to DECODE, or they screenshot BLACK.** That
is *not* a missing asset. The script pre-waits `DECODE_MS` (≈5.5s) after first
load; for heavy pages raise `--wait`. To confirm an asset is actually served,
`curl -sI <bg-url>` and check `Content-Length` — a real byte count means it's
fine, it just hadn't painted. **Black ≈ decode-not-404.**

**(b) NEVER `pkill`/`killall` Chrome** — it nukes the user's own browser windows.
The script spawns Chrome with a dedicated `--user-data-dir`
(`os.tmpdir()/qa-audit-profile-<port>`) and only ever `chrome.kill()`s **that
spawned child pid**. Keep it that way; never broaden the kill.

**(c) Prefer a `file://` mirror over a remote URL.** Some sandboxes block headless
Chrome's **network egress** even while `curl` still works, so a remote `http(s)`
deck can hang or black out on background-image fetches. A local `file://` mirror
of the deck (the built `index.html` + assets on disk) is the reliable input for
QA — and avoids the decode-race being confused with a network failure.

## Screenshot findings MUST be re-verified

A static screenshot scan **over-reports 折行 / overflow**. The capture is a single
settled frame at one viewport; autofit (`--fit`), container-query scaling, lazy
bg loading, and font swap can all still be in flight, so a line that *looks*
wrapped or a box that *looks* overflowing in `p{n}.png` may render fine in the
actual deck. **Treat every screenshot finding as a candidate, not a verdict:**

- Re-open that page in a real browser (the deck, not the PNG) and confirm.
- For suspected 丢图, run the curl/`Content-Length` check (caveat a) before
  calling an asset missing.
- For suspected 折行/字号, toggle 翻译态 and resize — if it only wraps at the
  captured size, it's a viewport artifact, not a deck bug.

Only after a finding survives re-verification do you patch it (per
`architecture.md` / SKILL.md 网页翻译版要点) and re-shoot to confirm the fix.
