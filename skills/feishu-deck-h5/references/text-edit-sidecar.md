# text-edit-sidecar — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:texts.md sidecar 细节 / mixed-content 陷阱 / T01-T03

## TEXT-EDIT SIDECAR (mandatory) — `data-text-id` + `texts.md`

Decks are 1500+ lines of dense HTML. Users CANNOT comfortably hunt through
markup to fix a typo or rewrite a sentence. Every deck this skill produces
MUST ship with a paired `texts.md` sidecar so the user can edit copy in
one ergonomic file and reapply the changes back into the HTML without
touching layout, CSS, decoration, or SVG mocks.

### Required deliverables (per run)

After PREFLIGHT and WORKSPACE setup, the agent's `runs/<timestamp>/output/`
folder MUST contain BOTH:

```
output/
  index.html          ← deck, every text leaf carries data-text-id="slide-NN.field"
  texts.md            ← sidecar, edit-only file paired with index.html
```

The user edits `texts.md`; running

```bash
python3 assets/apply-texts.py output/index.html output/texts.md
```

patches `index.html` in place (with a `.bak` first), changing only the
`textContent` of every element matching the changed ids. Layout, CSS,
SVG, decoration are byte-for-byte preserved.

### Authoring rule — every text leaf gets a `data-text-id`

When generating slide markup, every element whose inner content is plain
text (optionally containing `<br>`) MUST carry a `data-text-id` attribute
following this scheme:

```
data-text-id="slide-{NN}.{field}"
```

- `NN` is the zero-padded slide ordinal matching `data-screen-label`
  order (`slide-01`, `slide-02`, …). It MUST stay stable across
  regenerations of the same deck.
- `field` is a semantic, dot-namespaced name (`title`, `subtitle`,
  `card-01.body`, `agenda.item-03.zh`, `kpi-02.label`).
  Use ordinals (`-01`, `-02`) on repeating siblings even when there's
  only one today, so that adding a sibling later doesn't silently
  renumber the existing one.

**Examples (correct):**

```html
<h1 class="title" data-text-id="slide-01.title">先进团队的<br>工作方式</h1>
<p class="subtitle" data-text-id="slide-01.subtitle">The way advanced teams work</p>
<div class="agenda-item">
  <div class="n">01</div>
  <div class="title-zh" data-text-id="slide-02.agenda.item-01.zh">背景与挑战</div>
  <div class="title-en" data-text-id="slide-02.agenda.item-01.en">Context and challenges</div>
</div>
```

### Authoring rule — every `.slide` gets a `data-slide-key`

Separate from `data-text-id` (which is positional and serves this skill's
own apply-texts.py tooling), every `<div class="slide">` MUST also carry a
`data-slide-key` attribute that is a **semantic, kebab-case slug**:

```html
<div class="slide"
     data-layout="big-stat"
     data-screen-label="08 ARR Evolution"
     data-slide-key="arr-history">
  ...
</div>
```

Rules:

- Slug is **deck-internal unique** (no two `.slide` in the same file share a key).
- Slug is **semantic** — describes what the slide is about, not its position.
  Good: `cover`, `agenda`, `arr-history`, `case-meiyijia-display`, `closing`.
  Bad: `slide-01`, `section-3`, `page-7` (positional → breaks on reorder).
- Slug **MUST stay stable across reorders**. If you move a slide from page 7 to
  page 3, `data-slide-key` does not change. (This is the whole point — it's
  why we don't use the position-based `slide-NN` for this purpose.)
- Slug **MAY change when a slide's content materially changes** in a future
  deck (e.g., `arr-history` → `arr-history-v3` when the storyline shifts).
  That's how the slide-library detects "this is a new version" without
  losing the link to the old one.

#### Why this matters (consumer: feishu-slide-library)

The companion `feishu-slide-library` skill ingests rendered decks into a
reusable slide asset library. Its locator (`canonical_source.slide_key`)
points back to `[data-slide-key="..."]` in the deck's source.html. **No key
→ no locator → the slide is unindexable**.

If a deck is authored without `data-slide-key` on every `.slide`, the
slide-library ingestion will halt and require the keys to be backfilled.
Don't ship without them.

#### Bundled cover/agenda/end fragments

The `bundle-*.fragment.html` and `_shell.html` templates need `data-slide-key`
added too. Suggested defaults: `cover`, `agenda`, `closing` (or `end`).
For section dividers and content slides authored from `slide-recipes.html`,
pick a slug that names the topic, not the layout.

### Excluded from `data-text-id` (NEVER annotate these)

- `<svg>` and any element inside SVG (decorative, not user copy).
- `.pageno` (retired 2026-05; the present-mode pager UI shows page numbers, no per-slide DOM).
- Anything inside `<script>`, `<style>`, `<noscript>`, HTML comments.
- The `<title>` in `<head>` (page-level metadata; edit the file directly
  if needed).
- Brand-locked text that must never change (e.g., the "飞书" wordmark)
  — these MAY be annotated for completeness, but MUST be flagged in
  `texts.md` with a `(brand-locked)` suffix in the field name comment.

### Mixed-text-and-inline rule (this is the trap)

If an element contains text AND inline tags other than `<br>` — for
instance `<blockquote>飞书让 30 万人 <span class="accent-text">像一个团队</span>
一样工作。</blockquote>` — DO NOT put a single `data-text-id` on the
parent. Instead, split the content into separate leaves:

```html
<blockquote>
  <span data-text-id="slide-06.quote.lead">飞书让 30 万人 </span>
  <span class="accent-text" data-text-id="slide-06.quote.emphasis">像一个团队</span>
  <span data-text-id="slide-06.quote.tail"> 一样工作。</span>
</blockquote>
```

This keeps every editable run a clean text leaf so `apply-texts.py` can
substitute it with no markup-aware logic. The cost is two extra `<span>`
wrappers, which CSS doesn't see (they have no class).

### `texts.md` format

A single flat file, one section per slide. The `extract-texts.py` script
generates it; the agent emits it directly when authoring a fresh deck.

```markdown
# {Deck title} — texts

> Edit text below. After save, run:
>   python3 assets/apply-texts.py <deck.html> <texts.md>
>
> Rules:
>   • Edit ONLY this file. Visual tweaks → overrides.css.
>     Layout / structure / new slides → re-ask Claude.
>   • Use `\n` to insert a line break (renders as <br>).
>   • Do NOT rename the slide-NN.field ids — they pair with HTML.

## slide-01 (cover) — 01 Cover
title: 先进团队的\n工作方式
subtitle: The way advanced teams work
author.role: 客户提案 · 2026.04
author.team: 飞书企业服务团队

## slide-02 (agenda) — 02 Agenda
title: 本次汇报共六个部分
agenda.item-01.zh: 背景与挑战
agenda.item-01.en: Context and challenges
…
```

- Section header: `## slide-NN (layout) — screen-label` exactly.
- Lines: `field-name: value` (single line). Use `\n` literal (two chars,
  backslash + n) to encode a `<br>` inside the value.
- Lines starting with `>` or `#` are comments / headers — ignored on
  apply.

### Edit discipline (relay to the user when delivering)

1. **Text changes → `texts.md`**, then run `apply-texts.py`. Never edit
   text directly in `index.html` (the next regeneration / re-extract
   will conflict).
2. **Visual / spacing / color tweaks → `overrides.css`** linked at the
   end of the deck. Never edit the inline CSS in the deck.
3. **Layout, new slides, structural changes → re-ask Claude.** That
   triggers a regeneration; ids must remain stable for slides that
   already existed.

### Tools shipped with the skill

| Script | Purpose |
|---|---|
| `assets/apply-texts.py [<html> <texts.md>] [--dry-run] [--check]` | Apply edits from texts.md back into HTML. With no args, defaults to `index.html` + `texts.md` in the script's own directory (so it works inside the bundled deliverable zip). `--check` exits 1 on drift. |
| `assets/extract-texts.py <html> [--out texts.md] [--annotate out.html]` | Bootstrap texts.md from a deck. Mode A: deck already annotated — just dump. Mode B: bare deck — auto-add `data-text-id` and emit annotated HTML alongside texts.md. |
| `assets/package-deliverable.sh <output-dir> [--name foo]` | Bundle the per-run output into `deck-editable.zip` containing `index.html`, `assets/`, `texts.md`, optional `deck.json`, `assets-manifest.yaml`, `apply-texts.py`, `apply.command` (macOS), `apply.bat` (Windows), and a user-facing `README.txt`. The recipient unzips, edits texts.md, double-clicks the launcher — no Claude Code or pip required, just stock Python 3. |

**Retrofit limitation**: `extract-texts.py` Mode B captures pure text
leaves only. Mixed-content elements (text + inline tags) are skipped —
the user must restructure them per the "mixed-text-and-inline rule"
above. For NEW decks the agent generates, this never comes up because
the agent splits leaves up front.

### Validator behaviour

`assets/validate.py` runs `audit_text_ids` (rule T01–T03) on every
deck. It enforces:

- T01 — every `data-text-id` value matches `^slide-\d+\.[\w.\-]+$`.
- T02 — `data-text-id` values are unique within the deck.
- T03 — if a paired `texts.md` lives next to the HTML, its id set
  matches the HTML's id set (no drift). For a per-run deck at
  `runs/<ts>/output/index.html`, the validator looks for
  `runs/<ts>/output/texts.md` automatically.

Decks with no `data-text-id` at all are flagged with a single warning
("texts.md sidecar not generated") rather than 200 individual errors,
so legacy / external decks still pass through.

---

