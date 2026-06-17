# delivery — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30)· 何时读:交付/hand-off 时(Mode 1/2/3 走查、copy-assets --shared 模式、package-deliverable 内部、命名规范、交付话术)。
> ⚠️ 硬闸门(禁裸 linked HTML / A·B·C 形态 / 发前 copy-assets / 重命名 / 每轮 surface 路径)留在 SKILL.md CORE,不在这里。

## DELIVERY MODES — pick by harness

The skill produces files in `runs/<timestamp>/output/`. How those files
reach the human depends on which harness invoked the skill. Pick the
right delivery mode and call it out explicitly when handing off.

### 打包 / package — fast path (one command)

When the user just says **打包 / package / bundle / 交付 / 发我** for an
existing run, do NOT broad-`find` the run folder or hand-roll a
self-containment check. The whole job is one orchestrated command:

```bash
# a slug is enough — resolve-run.sh maps it to runs/*<slug>*/output (newest)
bash assets/finalize.sh <slug-or-output-path> <shape>
```

`finalize.sh` already runs copy-assets (self-contain) → validate → package,
so you never invoke those by hand. Pick the shape from what the user will do
with the deck:

| User intent | shape | command | artifact |
|---|---|---|---|
| 自己/客户改文字 · 便携可编辑 (**默认 for a bare "打包"**) | **B** | `finalize.sh <slug> remote [--name lark-<cust>-<YYYY-MM-DD>]` | `deck-editable.zip` (or `<name>.zip`) |
| 看一眼 / IM 转发 / 单文件 | **A** | `bash build.sh --inline` → ship the inline `.html` | one self-contained `.html` |
| 入库素材库 / slide-library ingest | **D** | `finalize.sh <slug> library --deck-id lark-<cust>-<date>` | `deck.zip` |
| 已部署到 Pages / CDN | **C** | ship the URL string | — |

Default a bare **"打包这个 deck"** to **B (`finalize.sh <slug> remote`)** —
portable, editable, survives transport. `--name` is optional and, if given,
must follow `lark-<customer>-<YYYY-MM-DD>`; omit it for a quick
`deck-editable.zip`. Reach for the lower-level `package-deliverable.sh` /
`copy-assets.py` only with a reason — `package-deliverable.sh` now runs a
`verify-portable.py` preflight and **refuses** a non-self-contained output
(self-contain with `finalize.sh` or `copy-assets --shared=copy` first;
`--skip-portable-check` overrides).

> Why this section exists (F-343): a bare "打包" once took ~8 min — a broad
> filesystem `find` to locate the run, an agent re-deriving the portability
> check in shell (BSD `sed`/`tr` quote bugs forced repeated re-runs), and
> verification heavier than a package needs. The command above is seconds:
> `resolve-run.sh` kills the locate step, `verify-portable.py` kills the
> hand-rolled check, and the scope rule below caps the verification.

### Hand-back rule (read this first)

**Decide whether to surface the file in the reply by the run mode, NOT
by file path.**

- **Interactive / chat / dialog** (the user sent a message and is
  waiting for your reply — Claude Code, Lark bot, web chat, any
  agent platform with a conversation UI): **MUST** end the reply by
  pointing at — or attaching — the new artifact under
  `runs/<ts>/output/`. Every iteration. "已修复" alone is a bug; the
  user has nothing to open. This applies on **every** edit pass, not
  just the first generation: a fix to an existing deck is a new
  artifact too — surface its path again.
- **Non-interactive / CLI / cron / batch / unattended**: writing the
  file under `runs/<ts>/output/` is the entire deliverable. Don't
  echo paths into stdout for show.

**The output directory is always the skill's own
`runs/<ts>/output/`** — never `~/Downloads/`, `/tmp/`, the user's
desktop, or any other ad-hoc location, unless the user explicitly
asks ("放到下载目录"). If the harness sandbox can't reach
`runs/<ts>/output/`, that's Mode 2 — package and attach, don't relocate.

### 🔒 Pre-handoff visual self-review — validator green ≠ done

Before any deck crosses the agent → user boundary, the gate is
**render → look at every page with a designer's eye → fix → THEN
deliver.** It is NOT `render → validate (rules) → ship`.

**Why** (user feedback · 世界坚果协会 deck): the first cut passed the
validator clean (0 error) yet shipped with the title sitting low /
missing and visibly hollow pages. The user asked three times "为什么
不能一次做对". Root cause: the agent equated "validator 0 error" with
"done" and never looked. Worse, the failures **compound** — centering
the title hides the hollowness in the middle; only when the title is
restored to its baseline does the empty space surface.

**What the validator cannot judge** (no rule covers these — they are
aesthetic, and `raw` / bespoke pages skip the position rules outright
because there is nothing to measure):

- **Title position** — is it at the standard baseline, or drifted /
  missing? (raw pages bypass `R-VIS-TITLE-POSITION`, see E6 in
  `editing-discipline`)
- **Fullness** — is the page hollow (top / middle / bottom blank band)?
- **Consistency** — does it match its sibling pages' style?
- **Focus** — is there a clear first-read, or is everything flat?

**How to apply — scope the look to the work (F-335):** for an
INTERMEDIATE scoped edit, render `--iter` and eyeball ONLY the changed
page(s) (auto-scope already re-shot just those — don't re-walk all N
pages). For a DELIVERY checkpoint (the deck crosses the agent → user
boundary, or before publish), **look at EVERY page's screenshot** and
walk it through 「标题位 / 饱满度 / 一致性 / 焦点」 before you trust the
green light. If it fails, fix and re-render. In multi-agent runs, make
"post-render visual self-review (changed page(s) intermediate, whole deck
at delivery)" a **default stage**, not an afterthought. This complements the precise-measurement gate (computed
`font-size` px, see `check-only` / `validator-rules`): font sizes you
**measure**, but composition / title position / hollowness you **look at**.

### 🔒 Delivery contract — NEVER hand back a single linked HTML file

This is a **hard rule, no exceptions**. Before any artifact crosses
the agent → user boundary (chat reply attachment, remote-codex
transport-back, harness "download to user" hook, manual file-pick),
verify the artifact form. Pick exactly **one** valid shape for the destination:

| Shape | When | What goes back |
|---|---|---|
| **A · inline single-file HTML** *(default for "show me / 给客户看 / IM 转发 / 链接预览")* | The user just wants to OPEN and SEE the deck. Use for customer preview, IM forwarding, and single-file viewing. | `python3 assets/inline-assets.py runs/<ts>/output/index.html --out runs/<ts>/output/lark-<customer>-<date>.html` (or `python3 deck-json/render-deck.py runs/<ts>/output --inline`) → ship that per-run inline file. Single self-contained file, base64-inlined CSS/JS/images, ~360 KB. Double-click anywhere, works offline. **Do NOT use `build.sh --inline` here — that rebuilds the skill's bundled SAMPLE deck, not the user's run.** Not a slide-library ingest format. |
| **B · zipped output folder** *(when the user needs to edit text)* | The user (or their downstream customer / sales / 大客户经理) needs to change copy without Claude in the loop. | `bash assets/package-deliverable.sh runs/<ts>/output/` → ship the resulting `deck-editable.zip`. Includes `index.html` + assets + optional `deck.json` + `assets-manifest.yaml` + `README.txt`. Recipient unzips, opens `index.html`, presses **E** for the built-in visual editor, edits text in-browser, saves with ⌘/Ctrl+S. |
| **C · hosted URL** *(when the user already deploys to Pages / a CDN)* | Deck lives at a stable web URL. | Ship the URL string. No file attachment. |
| **D · `deck.zip` for slide-library ingest** *(required for "入库素材库 / 上传素材网站 / 网页入库 / slide library ingest")* | The destination is the material library web ingest pipeline. | `bash assets/finalize.sh runs/<ts>/output library --deck-id <deck-id>` → upload `runs/<ts>/output/deck.zip`. This is the only standard upload format for the material library. |

**Banned form · single linked HTML**: never hand back just one
`*.html` file that points to sibling `assets/` / `input/` /
`prototypes/` directories. It works locally inside the skill folder
and **breaks the moment** it crosses any transport boundary — remote
codex auto-downloads to `~/Downloads/` strip the siblings, IM
attachments take only the file the agent named, `airdrop` /
`scp` of one file leaves the directory behind. The user will see a
naked unstyled DOM and call it "乱码".

**Why this rule exists**: the skill's linked-output mode is meant
for **in-skill iteration** (fast browser cache, small HTML diffs),
not for delivery. The delivery boundary is where linked must convert
to the destination-appropriate shape. The author of the skill knows the convention; the
agent doing the hand-back must enforce it.

**Material-library ingest rule**: linked `index.html` is local iteration
only and must not be uploaded to the material library by itself. Inline
HTML remains supported for customer preview, IM forwarding, and
single-file review, but it is not a material-library ingest format. When
the user says "入库素材库" / "上传素材网站" / "网页入库" / "slide library
ingest", produce `runs/<ts>/output/deck.zip` with:

```bash
bash assets/finalize.sh runs/<ts>/output library --deck-id <deck-id>
```

Do not manually compress `runs/<ts>/output/`. Do not upload
`runs/<ts>/output/index.html`. Do not use inline HTML for material-library
ingest.

**Specific failure mode this rule prevents** (remote codex / web
sandbox): an agent runs the skill in a remote container, finishes
the build, and the harness's "return artifact" hook picks **the most
recently modified file** matching `*.html` (which is the linked
`output/<deck>.html`). The HTML lands in the user's `~/Downloads/`
without its sibling `assets/` directory. Every `<link>`,
`background-image`, `<script src>` is a dead path. Always produce a
single-file artifact (inline HTML or zip) so the hand-back hook has
something correct to grab.

**How to apply in chat replies**: when surfacing the deck path,
**name the shape**, not just the path:

> ✅ `runs/<ts>/output/lark-opple-2026-05-13-inline.html` (inline, 任意位置可开)
> ❌ `runs/<ts>/output/index.html` (linked — 只在 skill 目录内可开)

If the user typed "把 deck 发我" / "给客户看" / "传到飞书" without
specifying form, default to **A (inline)**. Only switch to B if they
say "客户要改文字" / "我要自己改" (the zip's index.html carries the
in-browser visual editor — press E).

### Self-contained output (mandatory · runs before every hand-back)

The HTML files in `runs/<ts>/output/` reference assets via relative
paths back into the skill folder:
`../../../../skills/feishu-deck-h5/assets/<file>`. That works **only**
while the run folder lives next to the skill folder. The moment the
user moves, zips, or shares `runs/<ts>/output/`, every image / logo /
CSS / video link breaks.

**Rule**: before handing the artifact back to the user, run

```bash
# Default — link mode: shared/ is a symlink, framework files are real copies.
# zip / Finder-compress / IM-upload follow the symlink → recipient gets real files.
python3 skills/feishu-deck-h5/assets/copy-assets.py runs/<ts>/output/

# Full self-contained copy — use for archival or non-symlink-following destinations
python3 skills/feishu-deck-h5/assets/copy-assets.py runs/<ts>/output/ --shared=copy

# Library-ingest mode — full copy, no symlinks, ready for deck.zip
python3 skills/feishu-deck-h5/assets/copy-assets.py runs/<ts>/output/ --shared=copy
```

The script:

- Scans every `*.html` under `output/` for asset references matching
  `((\.\./)+)skills/feishu-deck-h5/(assets|examples|templates)/<file>`
  and `((\.\./)+)input/<file>`.
- Copies **only the referenced files** into `output/assets/` and
  `output/input/` (never the entire `shared/clientlogo/` or
  `shared/digital_employee_avatars_50/` directory if only a subset is
  used — typical run drops 3–5 logos out of 250+).
- Rewrites the HTML paths from skill-relative to local-relative
  (`../assets/<file>` and `../input/<file>`).
- Auto-redirects pre-reorg paths (`assets/clientlogo/foo.png`,
  `assets/zoom.png`, `assets/飞书标识_AI_Color.png`) to the canonical
  `assets/shared/...` location so old decks keep working. Applies to
  BOTH skill-relative refs AND already-local refs in pre-reorg outputs
  — re-running this script on a legacy `output/` folder migrates files
  in place (mv to `output/assets/shared/...`) and rewrites HTML.
- Emits `output/assets-manifest.yaml` classifying every referenced file
  as `shared` / `framework` / `deck-local` (downstream tools like the
  slide library use this for dedupe).
- Idempotent — running twice is safe; only changed/new files re-copy.

**`--shared` mode (when to use which)**:

- `--shared=link` *(default)* — replace `output/assets/shared/` with a single
  symlink (absolute path) to the skill's canonical `assets/shared/`. HTML refs
  are rewritten to local-looking `assets/shared/foo.png` and resolve through
  the symlink. `zip -r`, Finder "Compress", and IM-upload tools all follow the
  symlink and embed the real files into the zip — so "send the folder" workflows
  still produce a self-contained deliverable for the recipient. Saves ~5–30 MB
  per run vs. copy mode. Auto-migrates a real `shared/` directory from a prior
  copy-mode run into a symlink on first re-run.
- `--shared=copy` — full self-contained copy: every referenced shared file is
  duplicated into `output/assets/shared/`. Required for library mode
  (`finalize.sh ... library --deck-id ...`) and useful when the destination tool
  doesn't follow symlinks (rsync without `-L`, archival snapshots, etc.) or
  when you explicitly need an on-disk copy independent of the skill.
- `--shared=skip` — leave `assets/shared/*` references skill-relative;
  don't copy or link those files. Saves ~50–500 KB per deck. Output runs only
  while next to the skill folder OR when a downstream tool (like the
  slide library ingest) rewrites the shared/* paths against its own
  pool. Do not use this for new material-library uploads; library mode now
  requires `--shared=copy` and packages `deck.zip`.

After running with link or copy mode, `runs/<ts>/output/` is **send-friendly**:
cut/copy the folder anywhere on disk (link mode keeps symlinks intact on the
same machine) or zip and send (both modes produce a self-contained zip).

**Migrating existing runs to link mode**:

```bash
# Convert every runs/*/output/assets/shared/ from a real dir into a symlink
bash skills/feishu-deck-h5/assets/migrate-shared-to-symlink.sh

# Dry-run first if unsure
bash skills/feishu-deck-h5/assets/migrate-shared-to-symlink.sh --dry-run
```

When NOT to run it:
- Mid-iteration, when you know the user will keep editing in-place.
  (Just delays inevitable work but doesn't break anything.)
- When the user explicitly asks to keep skill-relative paths to
  share `assets/` updates across runs.

In every other case (delivery, hand-off, demo, attachment, "请给我看看"),
**run it**. The user's "把所有引用 assets 的文件复制到 output 下" instruction
is a baseline, not a special request.

### File-naming convention (mandatory) — `lark-<customer>-<presentation-date>.html`

While generating, the deck lives at `runs/<ts>/output/index.html` —
the `index.html` filename is canonical for working / preview / HTTP
serving. **But every artifact that leaves that working folder MUST be
renamed** to:

```
lark-<customer-slug>-<YYYY-MM-DD>.html
```

The date is the **presentation date** (when the deck will be
presented / shared / posted), NOT the generation timestamp. Apply
this convention to:

- The HTML you copy into a public site (e.g. `feishusolution/<...>`)
- The inline HTML you send for customer preview / IM forwarding
- The `deck.zip` produced for slide-library ingest (`--deck-id` should follow
  the same `lark-<customer>-<date>` identity)
- The zip name from `package-deliverable.sh` (`--name lark-<customer>-<date>`)
- Any "send this to the customer" copy

**Customer slug rules**:
- Lowercase, kebab-case
- Pinyin or English short name, NOT Chinese characters
  (CJK in filenames breaks URLs, IM previews, some scp/rsync chains)
- Multiple customers: chain with `-`, longest-first by recognition
- Examples: `boyu-starbucks` (博裕 + 星巴克 联合提案), `luckin`,
  `mixue-franchise`, `hetnet-ai-keynote`

**Date format**: `YYYY-MM-DD` — full ISO. Quarters (`2026q2`) and
year-month (`2026-05`) are NOT precise enough to disambiguate
re-presentations.

**Examples**:
| Use case | Filename |
|---|---|
| 博裕 + 星巴克 5/8 提案 | `lark-boyu-starbucks-2026-05-08.html` |
| 瑞幸内部周会 4/30 | `lark-luckin-2026-04-30.html` |
| 茶饮行业 keynote 5/15 | `lark-tea-beverage-keynote-2026-05-15.html` |

**Why this convention**: search-friendly when you have 100 decks in
a folder; `git log` shows the customer + date at a glance; matches
the slide-library's `deck_id` pattern (`lark-<customer>-<date>`)
so 1 deck → 1 deck_id without rename surgery.

`finalize.sh` accepts `--name <slug>` to emit the named copy
alongside `index.html` automatically. Pass it whenever you're
delivering HTML preview/public-site artifacts — the working `index.html`
stays in place for further edits, and the named copy goes out to the
recipient. For slide-library ingest, keep the generated file name
`runs/<ts>/output/deck.zip` and carry the same identity through
`--deck-id <deck-id>`.

### Mode 1 · Claude Code on the user's local machine

Default. The user has filesystem access to `runs/<timestamp>/output/`
already. Just tell them the path:

> 已生成：
> · `runs/<ts>/output/index.html` — 本地迭代 / HTTP 预览用（按 E 可在浏览器里直接改文字，不可单独上传素材库）
> · `runs/<ts>/output/deck.json` — 改文案的正道：`deck-cli set slides.N.data.<field> "…"` 再 re-render
> · `runs/<ts>/output/lark-<customer>-<YYYY-MM-DD>.html` — 命名规范副本，
>   客户预览 / IM 转发 / 单文件查看用（inline HTML，不作为素材库入库格式）
> · `runs/<ts>/output/deck.zip` — 素材库网页上传唯一标准格式：
>   `bash assets/finalize.sh runs/<ts>/output library --deck-id <deck-id>`

No packaging step needed for local preview. If the destination is the material
library, run the library finalize command and upload `deck.zip`.

### Mode 2 · OpenClaw / OpenCode / remote agent / Feishu bot

The skill ran in a sandbox the user can't reach. Filesystem paths are
useless. **Generate `deck-editable.zip` and ship that as the deliverable**:

```bash
bash assets/package-deliverable.sh runs/<ts>/output/
# produces: runs/<ts>/output/deck-editable.zip
```

The zip contains:

```
deck-editable.zip
├── index.html        ← the deck (viewable offline; press E for the built-in editor)
├── assets/           ← fonts / images / logos (if present)
├── deck.json         ← deck source (if present) — for structural re-gen by the author
└── README.txt        ← user-facing instructions (browse + in-browser text editing)
```

Hand the zip to the harness for delivery. Typical bot flows:

- **Feishu bot**: send as file attachment via `im/v1/messages` with a
  one-line caption ("飞书风格 deck — 解压后双击 index.html 看，按 E 改文字看 README.txt").
  Size is whatever the deck + assets weigh (typically 50-300 KB).
- **OpenClaw remote**: return the zip path; OpenClaw's transport layer
  handles uploading or attaching it to the response.
- **Slack / email / etc.**: same — attach the zip.

The recipient needs nothing installed — the deck opens and edits in any
browser (in-browser editor is zero-dep client-side JS).

### Mode 3 · View-only delivery (when editability isn't needed)

If the recipient is "客户/老板看一眼就行" and editing is not in scope,
ship just the inlined `index.html` (no zip). Run
`python3 assets/inline-assets.py runs/<ts>/output/index.html --out runs/<ts>/output/lark-<customer>-<date>.html`
(or `python3 deck-json/render-deck.py runs/<ts>/output --inline`) to produce a
fully self-contained single file from **the user's run**. Do NOT use
`build.sh --inline` — that rebuilds the skill's bundled SAMPLE deck.

(The inline single file still carries the in-browser editor unless you
strip the edit-mode lines; for a strictly read-only handout, remove them.)

### Choosing between Mode 2 and Mode 3

Default to **Mode 2 (zip with edit kit)** unless the user explicitly
says "this is the final version, no more edits" or "send to the
customer, just the visual." Most internal handoffs eventually need
copy tweaks; shipping the edit kit pre-empts a round-trip back to you.

---


## Caveats to relay to the user when delivering

> "This is an HTML approximation of the 飞书 母版 2025 (深色通用) PowerPoint master.
>
> 1. **Fonts** — Production uses 方正兰亭黑Pro (licensed). Web stack falls back to
>    Noto Sans SC / PingFang SC. To match the master pixel-for-pixel, install the
>    licensed face on the rendering machine.
> 2. **Logo** — The wordmark in this output is typographic ('Lark · 飞书'). For the
>    real tri-petal mark, drop in `lark-logo-mono-white.png` and `lark-logo-color.png`
>    via the `<div class=\"wordmark\">` slot.
> 3. **Icons** — Hand-drawn Lucide-style. For brand parity, swap to ByteDance IconPark.
> 4. **Customer logos / photos** — All product UI mocks and customer faces are
>    flagged with 〔TODO〕 and must be replaced before external use."

---
