# deck-cli · Phase 3 CLI editor for DeckJSON

Operate on a `deck.json` by command — for Claude / programmers / future
visual-editor backends to mutate decks without hand-editing JSON.

```bash
python3 deck-json/deck-cli.py <deck.json> COMMAND [args...] [--yes] [--no-backup]
```

Every **write** command:
1. Mutates the deck in memory
2. Backs up to `<deck>.json.bak-pre-<command>-<YYYYMMDD-HHMMSS>`
3. Writes back to disk
4. Re-validates against schema in `--strict` mode
5. Rolls back from backup if validation fails

Every **destructive** command (`delete`) requires interactive confirmation OR `--yes`.

---

## Commands

### Read (no backup, no side effect)

| Command | Purpose |
|---|---|
| `list` | numbered table of slides (idx / key / layout / variant / screen_label) |
| `get PATH` | print value at dotted path (e.g. `slides.3.data.title`) |
| `show KEY` | pretty-print one slide's JSON |
| `lint` | validate against schema (wraps `validate-deck.py`) |

### Set (per-field write)

| Command | Purpose |
|---|---|
| `set PATH VALUE` | generic dotted-path set. VALUE auto-typed via JSON (int/bool/list/null/string) |
| `set-accent KEY COLOR` | `slide.accent = COLOR` (blue/teal/violet/purple/orange — not cyan per R49) |
| `set-decor KEY TOKENS` | `slide.decor = TOKENS` comma-separated (e.g. `blue-glow,grain`) |
| `set-variant KEY VARIANT` | for `content`/`stats`/`flow` — switches variant AND **drops data fields incompatible with the new variant** (interactive confirm; `--yes` to skip) |
| `hide KEY [KEY…]` | **隐藏页** (PPT-style): set `slide.hidden = true` — still rendered + reachable by `#hash`/scroll, but the runtime skips it in present-mode 翻页 and drops it from the page count. Re-render to apply. Accepts multiple keys |
| `unhide KEY [KEY…]` | clear `slide.hidden` (clean-removes the field) so it rejoins the linear show. Re-render to apply |

### Structural (reorder / insert / delete / clone)

| Command | Purpose |
|---|---|
| `reorder FROM TO` | move slide at position FROM (1-indexed) to position TO |
| `move-key KEY POSITION` | safer than `reorder` for programmatic use — survives prior renumbering |
| `insert POSITION LAYOUT [VARIANT] KEY` | insert a scaffold slide (with `〔TODO〕` placeholders) at POSITION |
| `delete KEY` | remove slide. **Confirm + backup MANDATORY** (per SKILL.md SLIDE DELETION POLICY) |
| `clone KEY NEW_KEY [POSITION]` | duplicate slide within this deck. Default position: right after source slide |
| `paste --from SRC --key K [--new-key NK] [POSITION]` | **deck.json-native lift** — copy a slide from ANOTHER deck.json into this one. Deep-copies the slide object (incl. `custom_css`), copies its `input/`/`prototypes/` assets to target-relative paths, auto-suffixes key collisions, strips source-bound `data-text-id`, stamps `lifted` provenance. Default position: end |

### Render (pipeline alias)

| Command | Purpose |
|---|---|
| `render OUTPUT_DIR [--inline] [--skip-copy-assets] [--skip-texts]` | wrap `render-deck.py` |

---

## Flags

| Flag | Purpose |
|---|---|
| `--yes` | skip interactive confirms (Claude / CI / batch use) |
| `--no-backup` | skip `.bak-pre-*` creation (NOT recommended) |

---

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | invalid args / unknown command / path not found |
| 2 | deck.json read/parse error |
| 3 | post-op schema validation failed (auto-rolled-back from backup) |
| 4 | user declined confirm prompt |
| 5 | render subprocess failed |

---

## Workflow examples

### Quick rename

```bash
python3 deck-cli.py my-deck.json set 'slides.0.data.title' '新标题'
```

### Reorder by key (Claude-friendly — survives index shifts)

```bash
python3 deck-cli.py my-deck.json move-key luckin-case 3
```

### Insert new content slide → fill required fields → render

```bash
# 1. Insert scaffold
python3 deck-cli.py my-deck.json --yes insert 5 content 3up customer-story

# 2. Fill the placeholders (3 cards × title+body)
python3 deck-cli.py my-deck.json set 'slides.4.data.title' '客户故事'
python3 deck-cli.py my-deck.json set 'slides.4.data.cards.0.title_zh' '场景一'
python3 deck-cli.py my-deck.json set 'slides.4.data.cards.0.body' '...'
# ... etc

# 3. Render
python3 deck-cli.py my-deck.json render runs/<ts>/output/
```

### Delete with confirmation (interactive)

```bash
python3 deck-cli.py my-deck.json delete obsolete-slide
# →  deck-cli: about to delete:
# →      slides[7]  key=obsolete-slide
# →      layout: content/3up
# →      screen_label: 08 旧版本
# →  DELETE this slide? (backup auto-created) [y/N] y
# →    deleted slides[7] (key=obsolete-slide)
# →  deck-cli: backup at my-deck.json.bak-pre-delete-20260520-220838
```

### Delete non-interactively (Claude / batch)

```bash
python3 deck-cli.py my-deck.json --yes delete obsolete-slide
```

### Switch variant (e.g. content/3up → content/2col)

```bash
python3 deck-cli.py my-deck.json --yes set-variant three-pillars 2col
# →  deck-cli: drops fields {cards} (not used by content/2col)
# →  ⚠️ NOTE: required fields for content/2col may now be missing (text, visual) — 
# →     fill via set commands before render.
python3 deck-cli.py my-deck.json set 'slides.3.data.text.lede' '...'
python3 deck-cli.py my-deck.json set 'slides.3.data.visual.type' 'placeholder'
```

### Clone a slide for A/B-style iteration

```bash
python3 deck-cli.py my-deck.json --yes clone cover cover-variant-b
python3 deck-cli.py my-deck.json set 'slides.1.data.title' '版本 B 标题'
# Now compare slide 0 (original cover) vs slide 1 (variant B)
```

### Lift a slide from another deck (deck.json-native — no reading index.html)

```bash
# (optional) see what's in the source deck without reading its HTML:
cat old-pitch/slide-index.json        # render-deck.py emits this manifest
python3 deck-cli.py old-pitch/deck.json show five-judgments   # inspect one slide object

# copy it into the current deck (assets + key de-collision handled):
python3 deck-cli.py my-deck.json paste --from old-pitch/deck.json --key five-judgments
python3 deck-cli.py my-deck.json render runs/<ts>/output/
# custom_css travels with the slide → renders scoped, no CSS hunting.
# Foreign deck with no custom_css? Use assets/lift-slides.py --index / --key instead.
```

---

## Safety guarantees

1. **Every write op creates a backup** (`*.bak-pre-<command>-<ts>`) unless `--no-backup`.
2. **Every write op re-validates against schema** in strict mode.
3. **On schema failure, auto-rollback** from backup. Your deck never lands in an invalid state.
4. **Destructive ops (delete)** require interactive y/N confirm OR explicit `--yes` flag. Refuses non-interactive use without `--yes`.
5. **Key uniqueness checked** on insert / clone / set (via the schema's R-KEY business rule).

---

## Composition with Claude

A typical Claude flow editing a deck:

```python
# Pseudo — Claude tool-use sequence
list_result = run("deck-cli deck.json list")
# Claude reads the table, decides what to edit
run("deck-cli deck.json --yes set 'slides.3.data.title' '更精确的标题'")
run("deck-cli deck.json --yes set-accent kpi-4up teal")
run("deck-cli deck.json --yes move-key luckin-case 5")
run("deck-cli deck.json render runs/<ts>/output/")
```

Each call is atomic + validates + backs up. Claude can chain ops without re-reading the whole JSON.

---

## Limitations (Phase 3.a)

- Cross-deck `paste` exists (single-slide lift); full multi-deck `merge` / `split` is still Phase 3.b
- No "rename key" (workaround: clone with new key, delete old, may need to update inter-slide references)
- `set` accepts JSON literals via auto-typing — for very complex nested values, edit the JSON file directly
- No diff / preview before write (the operation prints old → new, but no full slide preview)
- `insert` scaffolds have `〔TODO〕` placeholders that the schema's fit-check will reject on `render` — must fill required fields first (especially for `content/story-case` 4-beat arc)
