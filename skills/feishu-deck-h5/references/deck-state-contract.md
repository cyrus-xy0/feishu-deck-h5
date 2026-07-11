# deck-state-contract — feishu-deck-h5 reference
> The single authoritative contract for `deck.json` / `deck-cli` STATE + ERRORS.
> 何时读:任何要写 `deck.json`、读退码、判 clobber 方向、或想手搓 heredoc 写 deck 的时刻。
> This subsumes the orphan `deck-json/DECK-CLI-README.md` (a stale command listing
> SKILL.md never linked — its exit-code table stopped at 5 and missed exit 6).
> Five sections: API · Key Design · Data Scope · Error Handling · Limitations.
> Single-source discipline: this file is the CONTRACT (write-guarantees + exit
> codes + drift direction). It does NOT re-document command flags — see
> `DECK-CLI-README.md` for the full command/flag catalog and worked examples.

---

## 1. API — every write tool, one line, with its write guarantee

The deck's on-disk state is mutated by exactly these tools. Each line names what
the tool writes and the guarantee it carries. **Anything not in this list MUST NOT
write `deck.json`** (see §2: no ad-hoc heredoc).

| Tool | Writes | Write guarantee |
|---|---|---|
| `deck-json/deck-cli.py` (`set-page` / `set --from-file` / `paste` / `insert` / `add-section` / `delete` / `move-key` / `reorder` / `clone` / `hide`/`unhide` / `set-*`) | `deck.json` only | **The sanctioned write path.** POSIX file lock around read→mutate→write + optimistic mtime_ns guard (concurrent-session clobber) + `*.bak-pre-<cmd>-<ts>` auto-backup + post-op strict schema re-validate **with rollback** + W4 pre-write lint (`set-page`/`set --from-file`). Destructive `delete` needs `--yes`/interactive confirm. |
| `deck-json/fast-text.py` | `deck.json` AND `index.html` (dual-write) | Pure-copy swap only. `count==1` asserted on **both** sides, JSON-escape handled, refuses `<`/`>`. **No render, no validation** — the sanctioned exception to "rerender after edits" (round-trip holds because the same literal string changed in both representations). JSON corruption is refused-and-restored. |
| `deck-json/import-html-slide.py` | `deck.json` (Mode A) | Wraps an authored html+css fragment as a `raw` slide, validates each candidate, inserts at index / `end` / after-key, auto re-renders. The sanctioned path for "add one new page". |
| `deck-json/render-deck.py` | `index.html`, `slide-index.json`, `.slide-hashes.json`, `validate-findings.json`, scoped screenshots, plus snapshots/copied assets | Re-derives output from `deck.json`, stamps `fs-render-sig`, and runs static + visual + geometry gates. Gate refusal restores the gate-controlled HTML/index/sidecar/screenshot bundle, including prior absence; no old HTML/new sidecar split is allowed. Never writes `deck.json` except an **auto-sync** fold of lossless browser edits (F-315). |
| `assets/materialize-remote-images.py` | downloaded `assets/remote/*`, matching URL strings in `deck.json` and nested HTML/CSS, optional `assets-manifest.yaml` | Hardened public-only downloads are staged first. Each HTML/CSS reference is relative to its own file; DeckJSON keeps output-root-relative references so rerender preserves localization. Text/assets commit with rollback on caught failure; assets land before references so interruption cannot create references to absent files. |
| `deck-json/lift-insert.py` | the complete destination deck directory bundle | Copies the destination to a same-filesystem stage, performs paste, asset/iframe localization, full render, visual gate and optional screenshots there, then verifies DeckJSON/HTML order, render signature/provenance, notes and all sidecars. The official directory is replaced only after every check passes; caught swap failures restore the original directory, and concurrent destination changes abort the commit. It never splices rendered frame strings into old HTML. |
| `deck-json/sync-index-to-deck.py` | `deck.json` (reverse-feed) | Recovers post-render `index.html` edits back into `deck.json` (raw inner HTML · canvas elements by-id · order · `custom_css` · `hidden` · `notes`). Backs up first. **Refuses to write when `deck.json` is newer** (downgrades to dry-run) — direction guard. |
| `deck-json/repair-lifted.py` | `deck.json` (orchestrates the repair tools) | Thin orchestrator for a garbled lifted/imported deck (backfill → migrate-head-css → heal → clean → reconcile → render+validate). **Defaults to `--dry-run`**; `--apply` runs for real. Each delegated step keeps its own backup + re-validate-with-rollback. |

Read-only helpers (no write, no backup): `deck-cli list`/`get`/`show`/`lint`,
`locate-slide.py`, `sync-index-to-deck.py --dry-run` / `--check-drift`,
`conform-to-deck.py` (default drift table), `repair-lifted.py` (default dry-run).

---

## 2. Key Design — invariants that make the state coherent

- **`deck.json` is the single source of truth; `index.html` is derived.** Any
  visual state that lives only in `index.html` is silent drift and WILL be
  destroyed by the next render/fork/downstream read. (Full rationale +
  postmortems: `round-trip-integrity.md`.)
- **Every write goes through `deck-cli`** (or the dual-write `fast-text` /
  insert-`import-html-slide`). That path is what carries the single-writer file
  lock, optimistic lock, auto-backup, schema-fail rollback, and W4 pre-write lint.
  **Ad-hoc
  python/heredoc that opens and rewrites `deck.json` directly is an anti-pattern**
  — it bypasses every one of those guards, and every guard exists because a real
  session paid for its absence (concurrent-session clobbering, an invalid deck
  landing on disk, an off-ladder font reaching the gate).
- **`data-slide-key` namespace discipline.** Each slide carries a stable semantic
  key. Lifted / hand-authored slides MUST retain a stable `data-slide-key` before
  delivery or library ingest. **Bare generic keys (`cover`, `intro`, …) collide
  across decks** — two decks both keyed `cover` overwrite each other's library
  thumbnail; namespace them `<deck_id>-<key>`. Within one deck the schema's
  **R-KEY** business rule enforces key uniqueness on insert/clone/set.
- **Opaque tokens travel verbatim.** A path, slide key, run timestamp, or asset
  ref is opaque — pass it through exactly as produced, never reconstruct it from
  memory. (Always pass ABSOLUTE paths to `lift-slides.py` / `render-deck.py`; the
  skill root is usually a symlink and a relative `runs/…` resolves wrong.)

---

## 3. Data Scope — what each layer owns, and the canonical loop

- **`deck.json`** owns the canonical spec: per-slide `data` (schema fields or raw
  `data.html`), `custom_css`, slide order, `hidden`, speaker `notes`, deck-level
  flags. `data.html` for a raw slide is the **inner** content of `.slide` — it does
  NOT include the `.slide` / `.slide-frame` wrappers.
- **`index.html`** is derived output only; `render-deck.py` regenerates it on
  demand. Treat it as disposable except as the carrier of un-synced browser edits
  (which the clobber guard / `sync-index-to-deck.py` reclaim into `deck.json`).
- **One editing model across all three slide kinds** (canvas / raw / schema):
  **render → edit `deck.json` → sync back if browser-edited → re-render.** Prefer
  editing `deck.json` over the browser, especially for canvas (PPTX-import) decks.
- **Page identity is one number.** `page N` (1-based) == URL `#N` == frame index N
  == `slides[N-1]` among ACTIVE (non-hidden, non-`_disabled`) slides. Never use a
  stale `screen_label` numeric prefix as a source page number.

---

## 4. Error Handling — exit codes are PER-TOOL and NOT interchangeable

> **⚠️ Exit-code semantics are per-tool. The same number means different things in
> different tools — do not write a wrapper that branches on a bare exit code
> without knowing which tool produced it.** The headline trap is **`exit 3`**:
> in **`deck-cli`** it means "schema validation failed → already auto-rolled-back
> from `.bak`, the disk deck is UNCHANGED"; in **`fast-text`** it means "the
> `deck.json` write SUCCEEDED but `index.html` was refused → you must re-render to
> sync". One is a no-op rollback, the other is a partial write needing follow-up —
> opposite required actions, same number. (A second collision: **`exit 6`** is
> deck-cli's clobber-refusal but render's `--inline-strict` un-inlined-refs
> failure; **`exit 8`** is render's clobber-refusal.)

### `deck-cli.py`

| Exit | Meaning | What to do |
|---|---|---|
| 0 | success | — |
| 1 | invalid args / unknown command / path not found | fix the invocation |
| 2 | `deck.json` read/parse error | the deck file is missing or malformed JSON |
| 3 | post-op schema validation failed → **auto-rolled-back from `.bak`** (disk deck UNCHANGED) | fix the payload so it validates, then retry; do not re-run blindly |
| 4 | user declined the confirm prompt | re-run with intent (or `--yes`) |
| 5 | `render` subprocess failed | see render's own exit table below |
| 6 | clobber-guard refused (browser carries un-synced LOSSY edits) **or** auto-sync failed | reconcile via `sync-index-to-deck.py` / re-apply in `deck.json`, or `--force` to DISCARD |

> Note: `DECK-CLI-README.md`'s table stops at 5 and omits **6**. That orphan is
> stale; **6 is real** (clobber-guard refusal, see §4 clobber). This contract is
> the authoritative exit table.

### `fast-text.py`

| Exit | Meaning | What to do |
|---|---|---|
| 0 | both `deck.json` AND `index.html` updated | done |
| 2 | refused: `OLD==NEW` / contains `<` or `>` / `count!=1` in deck.json / JSON corruption (restored) | lengthen the anchor string so it is unique, or use the canonical fragment loop |
| 3 | `deck.json` updated, but `index.html` refused (0 or >1 matches, or renderer entity-escaped the text) | **`render --quick`** to sync the html to the already-written deck.json |

### `render-deck.py`

| Exit | Meaning | What to do |
|---|---|---|
| 0 | success | — |
| 2 | deck not found / invalid JSON / pre-render schema fail / unresolvable `--scope` | fix the deck.json or the `--scope` token |
| 4 | a gate REFUSED the render (story-case schema-fit · static `validate.py` · visual-block · geometry-block · distribution-block) → `index.html` rolled back | fix the flagged template/element; the stderr names the gate + escape env var |
| 5 | `copy-assets.py` subprocess failed | see stderr; output must live under `<repo>/runs/<ts>/output/` |
| 6 | `--inline-strict` and ≥1 LOCAL ref could not be inlined (would 404 when moved) | fix the missing local file before shipping the single-file deck |
| 8 | clobber-guard REFUSED to overwrite `index.html` (un-synced lossy browser edit) **or** auto-sync of lossless edits failed | inspect with `sync-index-to-deck.py --dry-run`, re-apply in `deck.json`, or `--force` to DISCARD |

### `repair-lifted.py`

| Exit | Meaning | What to do |
|---|---|---|
| 0 | pipeline completed (or dry-run plan printed) | add `--apply` to actually run, if this was a dry-run |
| 2 | precondition failed (neither `deck.json` nor `index.html` present) | point it at a real deck dir / `index.html` / `deck.json` |
| (other) | a delegated step's exit code, **passed through verbatim** | look up that step's tool in its own table above |

### `sync-index-to-deck.py --check-drift` (read-only triage)

| Exit | Meaning |
|---|---|
| 0 | in sync (no un-synced edit) |
| 2 | error |
| 10 | un-synced edits, **all lossless** (raw/order/hidden/notes/custom_css) → would auto-sync |
| 11 | un-synced edits, **some lossy** (canvas / baked / schema / chrome) → would refuse |

### The clobber guard — two paths (F-315, Option A)

When `index.html` carries browser/hand edits not yet in `deck.json` (fails its
`fs-render-sig`) AND `deck.json` is not newer, the shared resolver acts
**auto-sync-if-lossless, else refuse**:

- **raw-slide edits (lossless)** → silently **auto-synced** into `deck.json`
  first, then the command/render proceeds. No action needed; both edits survive.
- **canvas / schema / baked / chrome edits (lossy or unfoldable)** → **REFUSE**:
  `deck-cli` exits **6**, `render` exits **8**. Reconcile manually
  (`sync-index-to-deck.py`, or re-apply the edit in `deck.json`), or `--force` to
  DISCARD the un-synced edits. (Full mechanics: `round-trip-integrity.md` §
  "Automatic clobber guard".)

---

## 5. Limitations / pre-flight — read before you write

Severity-tagged. Each line is a known footgun plus its fix; treat this section as
the pre-write checklist.

- **〔有损〕 canvas/schema sync is non-idempotent.** A reverse-feed of a canvas
  (PPTX-import) slide re-maps geometry/multi-run text; a schema slide only
  converts with `--force` (lossy schema→raw). The clobber guard refuses these for
  this reason. *Fix:* edit canvas/schema content in `deck.json`, not the browser.
- **〔有损〕 `fast-text` exit 3 leaves a partial write.** `deck.json` changed but
  `index.html` did not. *Fix:* `render --quick` to resynchronize.
- **〔不可逆〕 `--force` DISCARDS un-synced browser edits.** On both `deck-cli` and
  `render`, `--force` skips the clobber guard and throws away whatever was edited
  only in `index.html`. *Fix:* run `sync-index-to-deck.py --dry-run` first and
  reconcile before you ever reach for `--force`.
- **〔不可逆 / 反直觉〕 syncing the WRONG direction overwrites fresh `deck.json`
  edits with stale HTML.** Drift can mean either genuine post-render `index.html`
  edits (sync them) OR un-rendered `deck.json` edits (re-render instead — do NOT
  sync). *Fix:* always `--dry-run` FIRST, confirm the DRIFT DIRECTION; the tool
  guards it (refuses to write when `deck.json` is newer, override only with
  `--index-is-newer` when you truly hand-edited `index.html`).
- **〔反直觉〕 a green sync report from an old run is not a clean bill.** Older runs
  only checked raw HTML; `custom_css` / `hidden` / `notes` were missed. *Fix:*
  re-run the full sync — it now covers all six fields.
- **〔天花板〕 `deck-cli` has no `rename-key`.** *Fix:* `clone` with the new key,
  `delete` the old, and update any inter-slide references by hand.
- **〔天花板〕 `insert` scaffolds carry `〔TODO〕` placeholders the schema's
  fit-check REJECTS on render** (exit 4, especially `content/story-case`'s 4-beat
  arc). *Fix:* fill the required fields with `set` before you render.
- **〔反直觉〕 ad-hoc heredoc that writes `deck.json` bypasses every guard.** No
  file lock, no optimistic guard, no backup, no rollback, no lint. *Fix:* always go through `deck-cli`
  `set-page` / `set --from-file`.
- **〔天花板〕 `repair-lifted` does NOT grow too-small text** — it only snaps
  OFF-LADDER font sizes onto the tier. *Fix:* use `assets/grow-box-fit.py` after
  rebundling for genuinely-tiny readable text.

---
