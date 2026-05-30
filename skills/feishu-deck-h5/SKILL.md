---
name: feishu-deck-h5
description: |
  Use this skill when the user asks for a Feishu / Lark-style slide deck rendered as a
  single HTML file (NOT a real .pptx). Common triggers: "飞书风格 PPT", "Lark deck",
  "汇报材料", "客户提案", "h5 deck", "16:9 网页演示", "用 html 模仿 ppt", or the user
  attaching the 飞书 .thmx master. Produces a dark, cinematic deck at 1920×1080 with
  auto scale-to-fit + a mobile vertical browse mode in one file. Default language is
  CHINESE-ONLY; bilingual ZH+EN is opt-in (external bilingual pitch). Output looks
  indistinguishable from a hand-built Lark sales deck. Do NOT use for a real PowerPoint
  .pptx — that's the pptx skill. Also runs in CHECK-ONLY mode when the user hands over
  a finished HTML and asks for review / validation (e.g. "帮我检查这份 HTML",
  "validate this", "审一下这个 deck") — see MODE SELECTION in SKILL.md body for the
  full trigger list and what each mode does.
---

# feishu-deck-h5

> **🛑 STOP — read this preflight before doing anything else.**

## MODE SELECTION (read this first — pick CHECK-ONLY vs GENERATION vs RESKIN)

Before reading anything else in this file, decide which mode the user is in:

| Mode | Trigger phrases / signals | What to do |
|---|---|---|
| **CHECK-ONLY** | "帮我检查这份 HTML/deck" · "看看这个 deck 合不合规" · "审一下这个 HTML" · "validate this" · "check the deck" · "扫一遍合规问题" · "这个 HTML 哪里不对" · user hands over a path to an existing `.html` and asks for review WITHOUT asking to generate / modify content | **Jump to "CHECK-ONLY MODE" section below.** SKIP PREFLIGHT, SKIP `new-run.sh`, SKIP `copy-assets`, SKIP everything else in this file. |
| **RESKIN** | user hands you a foreign / non-feishu HTML and asks to "换皮 / feishu 化 / 套个飞书模版 / reskin / 改成飞书风格 / 把颜色字体换成飞书 / 用飞书 deck 重做这个" — they want feishu CHROME (palette / font / 4-tier ladder / real lark logo / lark-content-bg / .header / .stage) applied to the SAME visual design, **without redesigning content** | **Jump to "RESKIN MODE" section below.** Run `bash assets/reskin.sh <input.html>` — mechanical chrome rewrite. SKIP DESIGN PHASE (no design judgment is made), SKIP redesigning to a Pattern H+ / N-up / etc. — that's a different ask. |
| **GENERATION** *(default)* | "做一份飞书 deck" · "把这个 PDF 转成 HTML" · "客户提案" · "周会汇报材料" · "改一下第 N 页" · anything where output is a new or edited HTML deck | **Run the DESIGN PHASE first (default-on, chat-only)** — 标 hero 页、逐页定 path、定补全计划、给 hero 页写 Q0–Q4 + 六维 spec + **density budget**(每页量"装得下吗")。任何一页走默认 layout 之外的设计就停下确认;全 schema 宣告即走。然后 PREFLIGHT → new-run(落 `DESIGN-PLAN.md`)→ 按 path 生成(Path A schema 见 `DECK GENERATION POLICY`;hero 的 `layout: raw` / bespoke 见同节 + `DESIGN-FIRST POLICY` 词汇库)→ **render 后过 Step 5 密度闸门**(纯密度,不查 focal),通不过改回 deck.json 再 render,直到过了再交付。 |

If a request is genuinely ambiguous ("can you look at this HTML and improve it?"
— check or rewrite?), ask the user once to clarify before branching.

**RESKIN vs GENERATION confusion (this took 6 turns to learn)**: "用飞书模版" /
"套飞书皮" / "feishu 化" — these mean **chrome only**, NOT "redesign the content
using Pattern H+ / N-up / arch-stack." If the user gives you an existing HTML and
asks to "use the feishu template", default to RESKIN. Only ask before redesigning
content if they say "重新设计 / 重画 / 改 layout / 套个新的 pattern".

---

## REFERENCES INDEX — 按需加载

下面是按需加载的参考文件;遇到对应模式/特性时用 Read 打开对应文件。

所有路径前缀:`~/.claude/skills/feishu-deck-h5/references/`

- `assets-and-files.md` — 品牌资产/产品icon/persona/phone-mock + 文件树
- `check-only.md` — CHECK-ONLY 模式:用户给成品 HTML 要审/校验
- `content-density.md` — 判断输入是否过薄 / STOP-and-ask 模板
- `converting-existing-material.md` — 把 PDF/PPT/HTML/docs 转成合规 deck(1:1 页数 / Replica vs Rewrite)
- `delivery.md` — 交付/hand-off 时(Mode 1/2/3 走查、copy-assets --shared、package-deliverable 内部、命名规范、交付话术);硬闸门仍在 CORE
- `design-first.md` — 拿到文案要先出设计方案 + 组件类表(Q0-Q4/六维/squint)
- `design-phase.md` — GENERATION 设计阶段细节(Step5 密度闸门/DESIGN-PLAN 规格/增量vs批量)
- `editing-discipline.md` — 删/插/重排/自定义 layout 编辑(E1-E5 细节)
- `extra-layouts-and-raw.md` — 加新 layout 的 parity 契约 / 手写 raw 稠密版式
- `layout-recipes.md` — 手写/换皮 slide markup · variant 纪律 · 居中 · CSS 陷阱
- `narrative-patterns.md` — 按字母取叙事 pattern A-N + helper 配方
- `one-pager-case.md` — 一页纸客户案例 story-case(skip cover / 禁造 STORY id)
- `operational-notes.md` — 拷 shell / 嵌入 / 相对路径 edge
- `prototype-embed.md` — 嵌入已有 HTML/原型/别的 slide(别默认 iframe)
- `reskin.md` — RESKIN 换皮 / 重渲 UI mock / 保留氛围背景
- `richness-primitives.md` — 手写 richness primitive 的逐字配方
- `round-trip-integrity.md` — fork / 回灌 deck.json 的细节 + sync-index-to-deck.py
- `run-artifacts.md` — 写每轮 FEEDBACK.md / PROMPTS.md
- `slide-deletion.md` — net-delete 触发判定细节 + 备份命名
- `text-edit-sidecar.md` — texts.md sidecar 细节 / mixed-content 陷阱 / T01-T03
- `troubleshooting.md` — 渲染坏了但 validator 没指出时:症状→修
- `validator-rules.md` — validator 规则全表 R02..P55 含义 / 严重度

固化修复记录见 `CHANGES.md`(按需 Read,定位锚点):

- `#layer-1-retired` — Layer-1 patterns 已退役(quote / big-stat / multi-case-bundle)
- `#BF1-BF9` — 生产 deck 版式修复 BF1–BF9 + R57(金句无句末标点)
- `#BF10-BF15` — 对齐防御 BF10–BF12、present-mode 首帧 BF13、abs chrome 复位 BF14、隐藏 .header 重平衡 BF15(含 BF15.1 letterbox 边缘)
- `#media-autorestart` — slide media 进场自动重播 + 自动开声(框架行为)
- `#cjk-orphan` — CJK 换行平衡 / 末行孤字防治(预防 text-wrap:balance、检测 R-VIS-ORPHAN、修复阶梯、iframe 内手动处理)

## DESIGN PHASE (mandatory · default-on) — 设计先行,生成前的第一步

GENERATION mode 的**第一步,默认执行**。只在 chat 里发生(不建文件,不与 PREFLIGHT 冲突)。运行顺序:

> **DESIGN PHASE(chat)→ [按风险确认] → PREFLIGHT → new-run(落 DESIGN-PLAN.md)→ 按 path 生成**

把默认值钉在「**用好 LLM 做设计**」一侧:下限有 validator 兜底,上限只能靠 LLM 多做创造(补文案、补内容、为 hero 页写 bespoke layout)。(CHECK-ONLY readers skip this section.)

### 默认执行 + 确认门按风险触发
- **设计思考永远跑** —— 标 hero、定每页 path、定补全计划、给 hero 页写页级 spec。every run 都做,**不因「用户说直接出」就跳过 thinking**。
- **确认门条件触发**:全 deck 落在默认 Path A schema layouts(≤15)→ **宣告方案即往下走**,不强停。**任何一页走默认 layout 之外**(`layout: raw` / bespoke hero / 超出用户材料的重度补全)→ **必须停下,把那几页设计 spec 逐项摆出等用户确认**。用户明说「直接出 / 别问」→ 跳过的是确认那一下,不是设计思考。
- **转换已有材料(PDF/PPT/HTML)→ 默认 1:1 页数**,先看 `references/converting-existing-material.md`(Replica vs Rewrite 路由)再开工。
- **退化场景**(设计阶段坍缩成一句话):Replica PDF 1:1 贴图 / 单页精修(只动这页,标题 verbatim)/ 用户已明确给定 layout。

### 四步骨架
- **Step 1 · Deck 级**:叙事弧 + 页数(转换默认 1:1)· 标 hero 页(通常 2–3 张:封面/大论点/关键案例/收尾,是「放开 LLM」的作用域开关)· 逐页定 path(hero→`layout: raw`+词汇库 pattern;其余→Path A schema)· 内容/文案补全计划(默认就补,见 CONTENT-DENSITY;唯一硬护栏:**不编 attributed facts** —— 具体公司数字/具名引语/来源出处)。
- **Step 2 · 页级 spec**:hero 页必填 Q0–Q4 + 六维 + 先翻设计词汇库再落 layout · 支撑页轻量(角色判断 + Decision rule 选 schema)· **每页必走 density budget**:写一行「核心块 X + 支撑 Y(含下沉) ≤ layout 容量 Z」,装不下回 Q1 砍内容,不回头压字号。
- **每页判断视觉丰富度(别让整 deck 全是「彩边文字卡」)**:逐页想这页要不要视觉元素 —— 纯文字页考虑配**图标**(deck.json 的 `icon` 字段,名字见 render-deck.py `ICON_LIB` ~43 个 Lucide;`content/3up`、`stats/row` 原生支持)/ 配图 / 插画 / 用 `layout: raw` 做更丰富的 hero 页。**有数据要呈现 → 优先 `layout: chart`(`bar` 跨类比较 / `line` 时间趋势,1-3 线 / `donut` 占比构成),给数字 renderer 出确定性真图表,比堆 KPI 文字卡信息密度更高、更图表化**(增减归因仍用 `stats/waterfall` 桥图)。按内容判断、不强制每页都加;光靠默认 schema 文字卡会显得平。validator `R-VIS-NO-IMAGERY` 仅在整 deck 大部分页都零图像时**建议性**提醒(不阻塞,richness 是你的设计判断)。
- **Step 3 · 输出设计方案**:chat 出 Design pass 表(角色/唯一重点/path/是否 hero),hero 页各附一句 design intent。
- **Step 4 · 闸门 + 落盘**:beyond-default 页→等确认;全 schema→宣告即走。确认后:PREFLIGHT → new-run → **把锁定方案写 `runs/<ts>/output/DESIGN-PLAN.md`**(与 FEEDBACK/PROMPTS/texts.md 同级),生成严格照它走;偏离先回来改 plan,不静默漂移。

### Step 5 · 密度闸门(每次 render 后过一遍,通过再交付)
**EXISTS-and-runs:每次 render 出来后必跑**。只查密度,不质疑焦点(focal 由 Q1 + R-FOCAL-CHECK 接管)。过密信号命中 ≥1 即过密:单条非点题正文 >30 字 / 单块 ≥5 内联元素 / 块间距 < 块高 1/4 或核心块距画框 <60px / 主副标题同事或三层重复 / 支撑每项 >1 行带强装饰 / 顶部长句占大色块。降密 4 方向都做:块内压实(长句→名词短语,内联 ≤3)· 块间松气(核心块四周 ≥80px,禁贴边)· 冗余清理 · 支撑下沉(底部窄带/cfoot,每条「名称+一行+色点」)。**眯眼测试**:缩 1/3,主结论可识别 AND 装饰糊成一片 → 通过。与 validator 分工:R-VIS-BALANCE / R-VIS-BODY-FLOOR 查几何信号,字数/冗余/装饰堆积由本 Step 人工兜底。

### 批量 vs 增量
按用户喂法自动选:一次性给全 → 批量(方案表→确认→一次 new-run+落 plan+生成全 deck);逐页喂 → 增量,**设计一页就执行一页,别攒**(第一页就 new-run,逐页 render/append,deck.json 与 DESIGN-PLAN.md 逐页增长)。拿不准就增量。

> 📎 细节见 `references/design-phase.md`

## CHECK-ONLY MODE

> 📎 详见 `references/check-only.md`

## RESKIN MODE — foreign HTML → feishu chrome (mechanical, one-shot)

> 📎 RESKIN 换皮:**先 grep 源 canvas — 必须 1920×1080,否则 reskin 拒跑(exit 3);任何非机械权衡先问用户(META-RULE)**。详见 `references/reskin.md`

## PREFLIGHT (mandatory, blocks all work) — local mount required

This skill is **ONLY valid in local-mount mode**. If the user has not
mounted a writable local folder, the skill MUST refuse to proceed and
must NOT write anything to ephemeral session storage.

### Why this is mandatory

Decks generated in temporary session storage (`/sessions/.../mnt/outputs/`)
are **wiped between conversations**. Without a local mount:

- The user loses the deck the moment the conversation ends.
- Brand assets (`lark-*.png/jpg`) can't be reused across decks.
- Multiple people on the same team can't collaborate or version-control.
- The user can't `git commit` what they generated.
- The generated HTML can't be opened in the user's own browser via
  `file://` because the session is sandboxed.

The skill is designed for persistent, team-shareable, version-controlled
decks. Running without a mount defeats every reason this skill exists.

### Required preflight steps (run IN ORDER)

**Step P-1.** Check `<env>` in your system context for the line
`User selected a folder: yes/no`.
- If `yes` → continue to Step P-2.
- If `no` → go to Step P-3 (request mount).

**Step P-2.** Verify the mount is writable by running:

```bash
bash assets/preflight.sh
```

The script exits 0 on success and prints one of two stdout markers:

- `PREFLIGHT OK` — skill root is writable; proceed normally from
  the current directory.
- `PREFLIGHT BOOTSTRAPPED` — skill root was read-only (e.g. Mira-style
  harness mounting the skill RO). The script auto-mirrored the skill
  into a writable workspace and printed its path. **You MUST `cd` into
  that workspace before any further skill commands.** See Step P-2.4.

Exit codes 1 / 2 / 3 mean: missing files or no mount / read-only AND
no writable bootstrap area / running from ephemeral output. Any
non-zero exit blocks all subsequent work.

**Step P-2.4.** If preflight printed `PREFLIGHT BOOTSTRAPPED`, the
skill is mounted read-only and a writable mirror was just created.
Parse the `workspace (RW) : <path>` line from the output and `cd`
into it before doing anything else:

```bash
cd "<workspace path from preflight stdout>"
```

Once inside the workspace, EVERY subsequent skill command —
`assets/new-run.sh`, `deck-json/render-deck.py`, `assets/validate.py`,
`build.sh`, `assets/package-deliverable.sh` — runs from this
workspace, NOT from the original RO mount. The `runs/<ts>/output/`
artifact will land here; that's the path you hand back to the user
per the Hand-back rule (see DELIVERY MODES below).

If the harness can pre-set `FS_DECK_WORKSPACE` to a known location,
honor it — preflight uses that value when present. Otherwise the
default is `$PWD/.feishu-deck-h5-workspace/`.

Why this exists: harnesses like Mira mount the whole skill RO. We
can't write `runs/<ts>/{input,output}/` next to `assets/` in that
case, so preflight rsyncs the skill into a writable area and chmods
the mirror back to writable. All relative paths inside the skill
keep working because the workspace IS a complete copy.

**Step P-2.5.** If the script's stdout contains the line
`WARNING · another clone of this repo lives on disk:`, the user has
TWO checkouts of `feishu-deck-h5` on the machine (e.g. one in
`~/Documents/Github/feishu-deck-h5/` and one in the Claude Code
session-mount path). Outputs you create here will NOT appear in the
other one — same GitHub remote, different filesystem directories.

**STOP. Do NOT call `new-run.sh` yet.** Surface the conflict to the
user and ask which clone they want this run's deck to land in:

> "我看到你机器上有两份 feishu-deck-h5 的 clone：
> · 我现在挂载的：`<current skill root>`
> · 另一份：`<other clone path>`
>
> 这次生成的 `runs/<ts>/` 只会出现在我挂载的这份里。如果你平时
> 在另一份编辑/commit，我建议切到那份再继续。要切吗？"

If the user says "切到 X" / "use the other one", abort this run and
ask them to re-invoke the skill with Claude Code mounted at the
other path. If the user says "use this one" / explicitly picks the
current root, proceed to Step W-1.

**Step P-3.** Call `mcp__cowork__request_cowork_directory` and ask the
user to select their project folder. Phrase the request like:

> "I need to mount your local working directory before generating a
> deck — outputs need to persist beyond this session and be available
> in your editor / browser. Please select the folder where you want
> the deck files to live (e.g. `~/Projects/2026-customer-deck/`)."

**Step P-4.** If the user declines or the mount call fails or P-2 still
fails after P-3, STOP and reply with this exact message:

> "feishu-deck-h5 requires a local mounted folder so generated decks
> persist beyond this conversation, can be opened in your browser, and
> can be version-controlled. I can't proceed without one. Please select
> a working directory and ask me again, or use a different tool that
> doesn't require local persistence."

**Do NOT** generate any HTML in `/sessions/*/mnt/outputs/`. **Do NOT**
hand-wave with "I'll generate it temporarily". **Do NOT** offer to
inline everything into a single message. The skill is gated; honor the
gate.

### What "local mount" looks like in practice

| State | Filesystem indicator | Action |
|---|---|---|
| User cloned the repo + mounted | `~/Projects/feishu-deck-h5/` mounted; SKILL.md visible | OK, proceed |
| User mounted a parent project folder | `~/Projects/q1-pitch/` mounted; cloned skill in subfolder OR via plugin install | OK, proceed |
| User mounted a fresh empty folder | Mounted but no skill files yet | Copy skill files into the mount first (`git clone` or copy from `~/.claude/skills/`), then proceed |
| Harness mounts skill read-only (Mira / sandbox) | `preflight.sh` prints `PREFLIGHT BOOTSTRAPPED` and exit 0 | `cd` into the workspace path it printed, then run all skill commands from there (Step P-2.4) |
| User has not mounted anything | `User selected a folder: no` in env | Request mount, refuse if declined |
| Working in `/sessions/*/mnt/outputs/` only | `preflight.sh` returns exit 3 | Treat as no-mount, refuse |
| Skill RO AND no writable area for bootstrap | `preflight.sh` returns exit 2 | Tell the user to set `FS_DECK_WORKSPACE` to any writable directory, or mount the skill RW |

The skill treats "ephemeral outputs only" the same as "no mount" — both
are non-persistent and equally broken for this skill's purpose.

---

## DECK GENERATION POLICY (mandatory) — DeckJSON-first by default

**After PREFLIGHT passes, decide HOW you'll author the deck. Two paths:**

| Path | When | What you write | What renders |
|---|---|---|---|
| **A · DeckJSON-first** *(RECOMMENDED, default)* | The deck fits one of the 15 layouts in `deck-json/deck-schema.json` (12 base + 3 specials: `raw` / `replica` / `iframe-embed`) — covers ~95% of real decks | `runs/<ts>/output/deck.json` per schema | `python3 deck-json/render-deck.py deck.json runs/<ts>/output/` → produces `index.html + texts.md + assets/` automatically |
| **B · Raw HTML authoring** *(escape hatch · 整页手写 `index.html`,极少用)* | A pattern genuinely doesn't fit any schema layout AND can't be expressed as a `layout: "raw"` slide | Hand-author `index.html` per the R02 / R06 / R20 / L1-L4 / BF1-BF12 rules below | Skill's existing `validate.py` HARD GATE before delivery |

> **注意区分 `layout: "raw"`(Path A 内)与 Path B(整页手写)**:hero 高光页用
> `layout: "raw"` 单页 bespoke —— 它仍在 deck.json / render-deck.py 管线内、仍过
> validate.py,是**一等设计工具**(见下「`layout: raw` for hero pages」)。Path B
> 是连 `layout:"raw"` 都表达不了时才整页手写的最后手段。

**Why Path A is the default**:
- **Stability**: ~95% of HTML/CSS bugs Path B hits (R20 off-tier font, R06 floors, R12 drop shadows, BF1-BF12 layout traps, R-CSSVAR undefined tokens) are eliminated because you write data, not CSS. Renderer + framework CSS handle them.
- **Editability**: Auto-generated `texts.md` sidecar lets the user (or downstream sales / customer) edit copy without touching markup.
- **Versionability**: deck.json diffs cleanly in git. Compare two pitch versions by JSON diff, not 1500-line HTML diff.
- **Composability**: Reorder / insert / delete slides = JSON array mutation. No more regex-eating-`</div>` (R-DOM defense exists for a reason).
- **Future**: Phase 3 CLI editor + Phase 4 visual editor edit the SAME deck.json. Path A future-proofs the work.

**Quick start**:

```bash
# 1. After PREFLIGHT + WORKSPACE creation, write deck.json (see inline
#    minimal example below — copy it verbatim and edit fields)
$EDITOR runs/<ts>/output/deck.json    # full templates in deck-json/examples/

# 2. Render — produces index.html + texts.md + (optionally) assets/
python3 deck-json/render-deck.py runs/<ts>/output/deck.json runs/<ts>/output/

# 3. (optional) single-file delivery for email attachment / Slack drop
python3 deck-json/render-deck.py runs/<ts>/output/deck.json runs/<ts>/output/ --inline
```

The renderer does triple-gate: DeckJSON schema → HTML render → existing `validate.py` (R02/R06/R20/L1-L4/BF1-12/R-CSSVAR/R-WHITE-TEXT/all). Any error = render fails. **Same bar as Path B's manual gate, but enforced for you**.

**After the initial render, iterating on the deck — 3 options ordered by ergonomics**:

```bash
# Option A · Direct JSON edit (best for batch / structural rewrites)
$EDITOR runs/<ts>/output/deck.json
python3 deck-json/render-deck.py runs/<ts>/output/deck.json runs/<ts>/output/

# Option B · Atomic CLI ops (best for one-shot changes; auto-backup + validate + rollback)
python3 deck-json/deck-cli.py runs/<ts>/output/deck.json set slides.3.data.title "新标题"
python3 deck-json/deck-cli.py runs/<ts>/output/deck.json clone three-pillars three-pillars-v2
python3 deck-json/deck-cli.py runs/<ts>/output/deck.json reorder 5 2
python3 deck-json/deck-cli.py runs/<ts>/output/deck.json set-variant kpi-4up hero
# lift a page FROM another deck (deck.json-native, +assets, auto de-collide key):
python3 deck-json/deck-cli.py DST/deck.json paste --from SRC/deck.json --key five-judgments
# 15 subcommands total — see deck-json/DECK-CLI-README.md

# Option C · WYSIWYG · edit the rendered HTML directly in your browser
# (default-on since 2026-05-21: every rendered deck auto-loads
# assets/edit-mode/deck-edit-mode.{css,js}. Press E to enter edit mode,
# Esc to exit, Cmd/Ctrl+S to save. Zero deps, runs from file:// or
# https://.)
```

**Inline minimal example** (4 slides, every required field). Copy this verbatim, then iterate:

```jsonc
{
  "version": "1.0",
  "deck":  { "title": "Q2 OKR 复盘", "author": "团队 A", "date": "2026-05" },
  "slides": [
    { "key": "cover",  "layout": "cover",   "accent": "blue",
      "data": { "title":  "Q2 OKR 复盘\n5 个关键判断",
                "author": "团队 A",
                "date":   "2026-05" } },
    { "key": "agenda", "layout": "agenda",  "accent": "blue",
      "data": { "items": [
        { "title_zh": "目标回顾" },
        { "title_zh": "完成度评估" },
        { "title_zh": "关键经验" },
        { "title_zh": "Q3 重点" } ] } },
    { "key": "outcomes", "layout": "content", "variant": "3up", "accent": "teal",
      "data": { "title": "三个关键结论",
        "cards": [
          { "num": "01", "title_zh": "结论一", "body": "..." },
          { "num": "02", "title_zh": "结论二", "body": "..." },
          { "num": "03", "title_zh": "结论三", "body": "..." } ] } },
    { "key": "end",    "layout": "end",     "accent": "blue",
      "data": { "title": "下一步", "contact": "team-a@example.com" } }
  ]
}
```

Then `python3 deck-json/render-deck.py runs/<ts>/output/deck.json runs/<ts>/output/`. The renderer fills in everything else — wordmark, page numbers, `data-text-id`, present-mode UI, all typography ladders. You only describe **what**, not **how**.

### When Path A is the right choice

Use DeckJSON whenever the deck consists of slides matching any of:

| Layout | Variants | Use for |
|---|---|---|
| `cover` | — | Title page |
| `agenda` | — | TOC, pill stack |
| `section` | — | Chapter divider with big numeral (optional `parent_label` for subsection) |
| `content` | `3up` / `2col` / `story-case` / `blocks` / `matrix` / `before-after` | 3 cards / 左文右图 / 一页纸案例 / 全宽 body / 2×2 矩阵 / 痛点→解决方案对比 |
| `stats` | `row` / `hero` / `waterfall` | 3-4 KPI row / 1 hero number / 桥图 |
| `chart` | `bar` / `line` / `donut` | 跨类比较柱图 / 时间趋势折线(1-3 线) / 占比构成环图 — 给数字,renderer 算几何出确定性 SVG/CSS(无 JS),比文字 KPI 卡更图表化 |
| `quote` | — | Single customer quote |
| `image-text` | — | Full-bleed photo + overlay text |
| `table` | — | Comparison matrix |
| `flow` | `timeline` / `process` / `tree` / `swim` | Timeline / process steps / MECE tree / multi-lane roadmap |
| `logo-wall` | — | N industries × M client-logo grid |
| `arch-stack` | — | 2-5 layer architecture diagram (apps / platform / AI / data) |
| `end` | — | Closing slide (optional `slogan` for branded sign-off) |
| `replica` | — | PDF page-as-image (for PDF→HTML conversion) |
| `iframe-embed` | — | Embed a live HTML prototype with a deck title bar + 飞书 wordmark (Prototype embed Mode B) |
| `raw` | — | Escape hatch for one-off custom slides |

Plus 10 embeddable blocks (pullquote / cta-box / kpi-strip / data-panel / principle-band / verdict-grid / phone-iframe / testimonial-card / mockup-card / persona-card) that compose inside `content/3up` / `content/2col` / `content/blocks`.

Deck-level theme: `deck.title_style` (4 styles · center-single/center-double/left-double/left) × `deck.logo_position` (front/back) = 8 master-variant combinations. Per-slide override via `slide.title_style` / `slide.logo_position`.

**Full schema + field reference**: `deck-json/deck-schema.json`
**Worked examples**: `deck-json/examples/sample-deck.json` (14 slides — the 10 core layouts: cover/agenda/section/content/stats/flow/quote/image-text/table/end) · `deck-json/examples/phase-1c-extras.json` (the extras: content-blocks/matrix/before-after, flow-tree/swim, stats-waterfall, logo-wall, arch-stack, replica). `iframe-embed` + `raw` have no example deck yet.
**Migration notes**: `deck-json/MIGRATION-REPORT.md`

### `layout: raw` for hero pages — 一等工具,不是兜底

设计阶段标为 **hero 的高光页,主动用 `layout: "raw"` 做 bespoke** —— 这是
"用好 LLM 做设计"的主战场,不是失败兜底。三件事记牢:

- **raw ≠ 失控**:`layout: "raw"` 仍走 `render-deck.py` + `validate.py` 全套
  HARD GATE(R10 brand hex / R12 no-drop-shadow / R13 / 4-tier ladder /
  R-WHITE-TEXT / UI1 … 全在)。floor 由 validator 兜,你只管把 ceiling 做高。
- **门槛 = Q2 六维 spec**:写 raw 前必须先在 chat 出该 hero 页的 Q0–Q4 + A 档
  六维(见 `DESIGN-FIRST POLICY` 设计前预检)。六维写不出来 = 还没想清楚 =
  先别写 raw。
- **先翻词汇库再硬写**:`narrative patterns A–N`(双手架构 / 铁四角 /
  scene-grid / 北极星地图 / 5-up 大号数字 …)+ `component utility classes`
  多半已有现成 pattern,优先复用。

支撑页(非 hero)不要这样 —— 它们走 Path A schema 求稳。把 bespoke 的预算
**集中花在 2–3 张 hero 页**上,不要全 deck 放开。

### When to escape to Path B (整页手写 HTML)

连 `layout: "raw"` 单页都表达不了时,才整页手写。**only** when:

1. **No schema layout fits the structural shape** — e.g. the "two-hand-architecture" with crown/SVG-arches/base requires highly specific 4-tier vertical DOM that doesn't map cleanly to any layout. Use `layout: "raw"` first; only fall back to full Path B if even `raw` won't suffice.
2. **One-off design experiment** — you're prototyping a brand-new visual pattern that may or may not become a recurring layout. Path B lets you iterate freely. **If the pattern recurs ≥ 2 decks, propose a schema extension** (see deck-json/MIGRATION-REPORT.md Phase 0.2 process) instead of building 5 raw slides.
3. **Replica mode (PDF→HTML conversion)** — actually use `layout: "replica"` per-slide (still Path A); only escape to Path B if the page-image approach isn't acceptable to the user.

**Anti-patterns** (do NOT escape to Path B for these):
- "I want this title 18 px instead of 24" → that's R20 drift, not a schema gap. Fix the content or accept the tier.
- "The schema has `content/3up` but I want 4 cards" → ask: is this `content/3up` with denser cards, or `content/blocks` with a custom 4-card grid? Either fits.
- "I'm not sure which layout matches" → read `deck-json/MIGRATION-REPORT.md` Phase 0.2 — the 4-proposal evaluation shows the decision process.

### How Path A turns existing R-rules into "no-ops you don't think about"

Most of the rules later in this file (R02 missing data-layout, R06 font floor, R20 type ladder, R10 hex palette, R12 drop shadows, R-CSSVAR undefined tokens, L1 logo default, L2 stage balance, L4 attrs density, BF1-12 layout defenses, R47 variant discipline, R48 default centering, R49 cyan accent, R56 header minimal, UI1 ui-mocks-as-HTML, T01-T03 texts.md, P50-55 perf budget) **are about correct HTML/CSS output**. The renderer enforces all of them automatically because:

- Templates are hand-tuned (4-tier ladder, brand tokens, correct alignment defaults)
- Enrichers fill optional fields safely (no missing-attr crashes)
- HTML validator runs as a HARD GATE on every render
- `texts.md` is auto-generated (T03 satisfied by default)

**If you're going Path A, you don't read those rules unless you're modifying a template** — the framework already implements them. The rules below are critical for Path B authors and for skill maintainers extending the templates.

### Troubleshooting Path A (when render fails)

The renderer's triple-gate is loud about failures — read the error message before trying to "fix" anything. Common failure modes:

| Symptom | What it means | What to do |
|---|---|---|
| `validate-deck: ...` (Step 1) | DeckJSON schema violation (missing required field, wrong enum value, wrong shape) | Read the path the error reports; fix in `deck.json`; re-run |
| `render-deck: missing field {{{ X }}}` (Step 3) | Template references a data field that's missing or null | Some optional fields' templates expect them when present — check the `optional` annotation in `deck-schema.json`; either fill the field or use a different layout |
| `validate.py: ✗ Rxx ...` (Step 6, HARD GATE) | Generated HTML failed framework rule. **Almost never your fault** if you went Path A — it's a renderer / framework bug | Capture full error; report at `https://github.com/<repo>/issues` with the deck.json and the validate.py output. Workaround: comment out the offending slide with `_disabled: true` (renderer skips), keep going, fix it offline |
| `texts.md: out of sync` | Auto-generated sidecar diverged from deck (you hand-edited HTML after render) | Re-render — the sidecar regenerates from deck.json. Don't hand-edit `index.html`; edit deck.json |
| Render OK but visual looks wrong | Renderer succeeded but the slide design has a problem (overflow, text too small, wrong color) | Run `bash skills/feishu-deck-h5/assets/check-only.sh runs/<ts>/output/index.html --visual` for visual audits (R-OVERFLOW / R-VIS-TIER / etc.) — they catch what static validate.py can't |

**When you must escape mid-deck**:

If 1-2 specific slides won't fit the schema but everything else does:

```json
{ "key": "weird-layout", "layout": "raw", "data": {
    "html": "<div class=\"slide\" data-layout=\"raw\" ...>...</div>" } }
```

`layout: raw` lets you hand-author one slide while keeping all OTHER slides on Path A. The HTML you write is escape-hatched into the deck shell as-is. **Don't** abandon Path A wholesale for one weird slide.

### Editor / CLI quick reference (cross-link)

| Tool | Use case | Doc |
|---|---|---|
| `deck-json/render-deck.py` | Render deck.json → HTML (always runs first) | inline help: `--help` |
| `deck-json/deck-cli.py` | 15 atomic ops on deck.json (set / set-accent / set-decor / set-variant / reorder / move-key / insert / delete / clone / **paste** / render / list / get / show / lint) — auto-backup + revalidate + rollback. **`paste --from SRC --key K` is the deck.json-native lift** (copy a slide from another deck + its assets) | `deck-json/DECK-CLI-README.md` |
| `deck-json/validate-deck.py` | Standalone schema lint of deck.json (called by render-deck.py + deck-cli.py automatically) | inline help |
| `deck-json/sync-index-to-deck.py` | **Detect + recover post-render drift** — port edits made directly to index.html back into deck.json so re-render is byte-identical. Run before any fork / library ingest / delivery. | see ROUND-TRIP INTEGRITY section |
| `assets/lift-slides.py` | Lift a slide from a FOREIGN / legacy deck (no `custom_css`) — `--index` lists slides, `--key K` selects, tree-shakes framework CSS + copies assets into a `layout:raw` entry | see LIFTING section |
| `assets/check-only.sh` | Audit an EXISTING `.html` deck (Path A or B output) against all framework rules | see CHECK-ONLY MODE section above |

> *Visual editing — default on since 2026-05-21*. Every rendered deck
> ships with a zero-dep client-side editor (`assets/edit-mode/deck-edit-
> mode.{css,js}`, ~663 LoC). The shell templates (`_shell.html`,
> `_bundle-shell.html`, `big-stat.html`, `one-pager-case.html`,
> `quote.html`) inject the `<link>` + `<script>` + `<body class="deck-
> edit-mode">` by default, and copy-assets.py automatically copies the
> editor into `output/assets/edit-mode/` because the HTML references
> it. Press **E** to enter edit mode, **Esc** to exit, **Cmd/Ctrl+S**
> to save. On Chromium-based browsers, the first save shows an
> authorization dialog, then the native picker; choose the current HTML
> file once (macOS may label the system button "Open") and later saves
> overwrite silently via the File System Access API. Other browsers use a
> download fallback. Drag a slide-frame to reorder; click any text leaf to edit it directly. Runs from file://
> or https:// — works for `feishusolution`-style GitHub Pages
> deployments. To opt out for a specific deck (e.g. delivery zip
> destined for read-only viewers), strip the two edit-mode lines + the
> body class — the deck still renders normally without them.
>
> The pre-2026-05-21 server-side editor (`deck-editor.py` + Python
> server + browser UI) was retired in favor of this client-side
> approach (no server to run; works on static hosts; one file flip
> to enable/disable).

---

## DESIGN-FIRST POLICY (mandatory) — 给文案就先出设计方案,别直接动手

> 📎 详见 `references/design-first.md`

## WORKSPACE LAYOUT (mandatory) — per-run `runs/<timestamp>/` folder

PREFLIGHT 通过后、**生成任何 HTML 之前**,必须建一个新的 per-run 工作目录并向用户宣告。非协商约定(多次尝试不互相覆盖、素材与产物分离、每 run 带时间戳易归档)。

### 结构
`runs/` 在**仓库根**,NOT 在 `skills/<skill-name>/`(`new-run.sh` 用 `git rev-parse --show-toplevel` 解析根,非 git 树才退回 skill 根)。

```
<repo-root>/
├── runs/
│   └── YYYYMMDD-HHMMSS-<slug>/
│       ├── input/    ← 用户放源文件
│       └── output/   ← agent 写 deck + 报告
└── skills/feishu-deck-h5/   ← skill 源(不在此写产物)
```
CSS/JS 用相对路径 `../../../skills/feishu-deck-h5/assets/feishu-deck.{css,js}`(三个 `../` 从 output/ 爬到根再进 skill)。

### 步骤(PREFLIGHT 后按序)
- **W-1.** 先问用户 **topic / 客户名** 再建目录,作为 `new-run.sh` 第二参:`bash assets/new-run.sh <slug>` → 产 `runs/<YYYYMMDD-HHMMSS>-<slug>/`。Slug 由用户自然回答派生(别让用户敲 kebab-case):客户/portfolio→拼音或英文短名 kebab-case;内部主题→短英文/拼音 tag;多客户→按识别度最长在前;≤~25 字符。**NEVER 用中文字符**(URL/scp/IM/git log 会坏)。**NEVER 跳过 slug** —— 用户拒绝命名则退到内容形状 slug(`one-pager`/`customer-pitch`),不用裸时间戳。捕获脚本打印的绝对路径作为工作目录。
- **W-2.** 同一回复里**向用户宣告路径**(译成用户语言):「已为本次任务创建工作目录 `runs/<ts>-<slug>/`;素材放 `input/`;生成的 HTML + 验证报告写到 `output/`。」
- **W-3.** 等用户把文件放进 `input/`(或确认无源文件 —— 纯文本 brief 也行)。
- **W-4.** 本次调用**所有后续文件写入必须在** `runs/<ts>-<slug>/output/` 下。绝不写到 `examples/`、仓库根或别处。

### 何时 NOT 建新 run 文件夹
用户明说「编辑现有 deck `runs/.../output/X.html`」→ 复用该 run · 维护者跑 `build.sh` 重建 `examples/sample-deck.html`(硬编码 examples/,出本规则范围)。

## SLIDE DELETION POLICY (mandatory) — double-confirm + backup before any net delete

Deleting a slide is **irreversible without a backup** — same risk tier as `git push --force` / `rm -rf`. Confirmation costs one IM line; rebuilding a slide does not. Before ANY operation that **net-removes** a slide:

1. **STOP.** Don't run the deletion yet.
2. **List what's being removed** — count + each slide's `data-screen-label` + `data-slide-key` + a 1-line "why".
3. **Ask for explicit confirmation.** Wait for "yes delete" / "ok" / "go ahead". **Implicit consent does NOT count** — an earlier "trim the deck" is not approval to delete a specific slide; surface the list and ask again.
4. **Once confirmed, offer a backup** — default copy file (+ `texts.md` if present) to a `.bak-pre-delete-<YYYYMMDD-HHMMSS>` sibling; user may decline or pick another option.
5. **Only THEN proceed.**

**What counts as net-removing:** deleting a `.slide-frame`; `rm` of `output/`; re-rendering a `deck.json` with FEWER slides than current; replacing N with M<N; dropping a `## slide-NN` from texts.md then applying; a 1:1 slide swap (previous content IS deleted). **Not** net-removing: pure inserts, reorders (but announce new order first), or content edits.

Use the shipped helper (backs up + logs CHANGES.md + prunes to 3 most-recent per tag):

```bash
bash skills/feishu-deck-h5/assets/bak-and-log.sh <file> <short-tag> "<one-line description>"
```

For paired `index.html` + `texts.md`, run it TWICE with the SAME tag.

> 编辑机制见 EDITING DISCIPLINE kernel(E1 重编 data-page + 同步 scoped CSS · E2 禁 sed/regex 改 DOM · E5 动过的页欠一次 squint/再平衡)。
> 📎 细节见 `references/slide-deletion.md`(net-delete 触发判定表、pre-authorize 边界、备份命名约定)

## TEXT-EDIT SIDECAR (mandatory) — `data-text-id` + `texts.md`

Decks 是 1500+ 行密集 HTML,用户改不动 markup。每份 deck **必须**配一个 `texts.md` sidecar,让用户在一个文件里改文案再回写,不碰 layout/CSS/装饰/SVG。

### 交付物(per run)
PREFLIGHT + WORKSPACE 之后,`runs/<ts>/output/` **必须同时含** `index.html`(每个文本叶子带 `data-text-id`)+ `texts.md`(配对编辑文件)。用户改 `texts.md` 后跑:

```bash
python3 assets/apply-texts.py output/index.html output/texts.md
```

原地 patch `index.html`(先 `.bak`),只改匹配 id 的 `textContent`,layout/CSS/SVG/装饰逐字节保留。

### data-text-id 方案 — 每个文本叶子都打
纯文本(可含 `<br>`)的元素必须带 `data-text-id="slide-{NN}.{field}"`:
- `NN` = 零填充 slide 序号,匹配 `data-screen-label` 顺序,**跨重生成保持稳定**。
- `field` = 语义化点分名(`title` / `card-01.body` / `kpi-02.label`);重复同级即使现在只有一个也用序号(`-01`),防加兄弟时静默重编号。
- **mixed-content 陷阱**:元素含文本 AND 非 `<br>` 内联标签时,**不要**在父上打单个 id;拆成多个 `<span data-text-id=...>` 叶子,让 apply-texts.py 无需 markup 逻辑即可替换。
- **排除**(永不标注):`<svg>` 内部 · `.pageno` · `<script>/<style>/<noscript>`/注释 · head `<title>`。

### data-slide-key 硬前提 — 每个 `.slide` 都打
独立于 `data-text-id`,每个 `<div class="slide">` **必须**带 `data-slide-key`:deck-内唯一、语义 kebab-case slug(`cover` / `arr-history` / `case-meiyijia-display`,**不是** `slide-01`/`page-7` 这类位置名)、**跨 reorder 保持稳定**、内容实质变化时才可改(`arr-history`→`arr-history-v3`)。消费者是 `feishu-slide-library`:其 locator `canonical_source.slide_key` 指向 `[data-slide-key]`,**无 key → 无 locator → 切片不可索引**,入库会 halt。bundle 片段默认 `cover`/`agenda`/`closing`。**不带齐 key 不发货。**

### Validator T01–T03
T01 每个 `data-text-id` 匹配 `^slide-\d+\.[\w.\-]+$` · T02 deck 内唯一 · T03 配对 `texts.md` 的 id 集与 HTML 一致(无漂移)。完全无 `data-text-id` 的 deck 只报一条 warning(legacy/外部 deck 仍通过)。

> 📎 细节见 `references/text-edit-sidecar.md`

## DELIVERY MODES — pick by harness

The skill writes to `runs/<ts>/output/`. In **interactive/chat** mode, every reply (every edit pass, not just first gen) MUST end by surfacing the artifact path under `runs/<ts>/output/` — "已修复" alone is a bug. In **non-interactive/CLI/cron** mode, writing the file is the whole deliverable. Output dir is always the skill's own `runs/<ts>/output/`, never `~/Downloads/` or `/tmp/` unless the user explicitly asks.

### 🔒 Delivery contract — NEVER hand back a single linked HTML file

**Hard rule, no exceptions.** A bare `*.html` that points at sibling `assets/` / `input/` / `prototypes/` dirs works in the skill folder but **breaks the moment it crosses any transport boundary** (remote-codex auto-download, IM attach, scp/airdrop of one file) — user sees a naked unstyled DOM and calls it "乱码". Linked mode is for in-skill iteration ONLY. At the delivery boundary, convert to exactly **one** of three valid shapes:

| Shape | When | What goes back |
|---|---|---|
| **A · inline single-file HTML** *(default)* | user just wants to OPEN and SEE ("发我"/"给客户看"/"传飞书"/链接预览) — 90% | `build.sh --inline` → one self-contained file, double-click anywhere, offline |
| **B · zipped output folder** | user/downstream needs to edit text | `assets/package-deliverable.sh runs/<ts>/output/` → `deck-editable.zip` (index.html + assets + texts.md + apply-texts.py + launchers) |
| **C · hosted URL** | deck already deploys to Pages/CDN | ship the URL string, no attachment |

Default to **A** unless they say "客户要改文字"/"我要自己改" → **B**. When surfacing, **name the shape** not just the path (`…-inline.html (inline, 任意位置可开)`).

### Run copy-assets / finalize before send (mandatory · every hand-back)

Output HTML references assets via skill-relative paths that break once moved/zipped/shared. **Before any hand-back, run:**

```bash
python3 skills/feishu-deck-h5/assets/copy-assets.py runs/<ts>/output/        # default --shared=link
python3 skills/feishu-deck-h5/assets/copy-assets.py runs/<ts>/output/ --shared=copy  # non-symlink dests
```

The user's "把所有引用 assets 的文件复制到 output 下" is a baseline, not a special request — run it for every delivery/hand-off/demo/"请给我看看".

### File-naming convention (mandatory) — `lark-<customer>-<YYYY-MM-DD>.html`

Working file stays `runs/<ts>/output/index.html`. **Every artifact that LEAVES the working folder MUST be renamed** to `lark-<customer-slug>-<YYYY-MM-DD>.html`. Date = presentation date (not gen timestamp). Slug = lowercase kebab pinyin/English, NEVER CJK (breaks URLs/IM previews/scp). `finalize.sh --name <slug>` emits the named copy alongside `index.html` — pass it whenever delivering.

> 📎 细节见 `references/delivery.md`(Mode 1/2/3 走查、`--shared` 模式、package-deliverable 内部、命名示例、caveats 话术)

## LANGUAGE POLICY — declared by `<meta>`, enforced by validator R-LANG

**默认 = ZH-only。** 每个可见文本叶子一条语言,CN 文案下面不带 EN 翻译轨。模式在 `<head>` 声明,由 `validate.py` 强制:

```html
<meta name="fs-language" content="zh-only">   <!-- default -->
<meta name="fs-language" content="zh-en">     <!-- bilingual opt-in -->
```

`templates/_shell.html` 已含 zh-only meta。**只在用户显式要求时切 `zh-en`**(如「面向英文客户」「bilingual deck」);切换后 agenda `.title-en` / content-3up 双语卡标题 / two-hand-arch EN motto 等 CSS recipe 自动点亮,无需改 token。

zh-only 下 R-LANG 审三类信号:slide markup 出现 `title-en`/`subtitle-en`/`label-en`(双语专用类)· chrome-label 类(`eyebrow`/`kicker`/`pill`/`tag`/`chip`/`badge` 及 `-en`/`-num`/`-index` 等后缀)文本是纯 Latin 大写+数字+标点且不在白名单 · sibling-pair signature(同父 ≥2 文本叶子,一 CJK 一纯 Latin = EN 翻译轨结构)。不碰约定为英文的 token:品牌名(Lark/Base/Wiki)、产品码、单位(px/pt/%)、缩写(KPI/ROI/OKR)、混合大小写 Latin(`Context and challenges`)。禁的是**翻译轨**,不是每个 Latin 词。

> 📎 细节见 `references/validator-rules.md`(R-LANG 打印细节)

## CONTENT-DENSITY POLICY (mandatory) — augment thin input by default · no-fabrication guardrail

A 飞书 deck slide is **information-dense by design** — 3 lines of body in empty space reads as half-finished. **Professional augmentation IS the design work, not an增补 needing approval** (默认动作翻转 2026-05-26). So:

1. **默认就专业补全** — treat the user's input as a SEED and design the page at the information density of a real consulting/strategy deck. Default action, **no confirmation needed**. (Augmentation plan is already in DESIGN-PLAN.md from DESIGN PHASE Step 1; hero pages still pass their confirm gate.)
2. **唯一硬护栏:NEVER fabricate attributed facts** — specific company numbers / named-person quotes / source citations ("客户访谈"/"内部口径") / future-roadmap claims are NEVER invented (sibling of the NEVER-fabricate-STORY-ids rule). What you CAN add: public industry knowledge, product-capability descriptions, adjacent customer stories, typical KPIs — always tagged as such (e.g. "行业基准 · 公开数据"). The line: **augmentation is general industry/product knowledge tagged as such; NEVER specific facts attributed to specific entities the user didn't give.**
3. **沙化版式兜底** — when there's genuinely nothing to add, switch to a sparser-by-design layout (`quote` / `big-stat` / `cover` / `end` / `image-text`) where 2 lines hold up.

**Only STOP-and-ask in two cases:**
- **(a)** thin to the point that NO layout holds up even with augmentation (one word, no role, no content).
- **(b)** the intent itself is ambiguous — the page's role / single focus is unclear (Q0/Q1 unanswerable); what to augment depends on what the user wants to emphasize.

Note the distinction: **asking about intent = do ask; asking "要不要让我补文案" = don't ask, just augment.**

North star: **the deck must not silently invent material the user couldn't defend in front of the audience** — but "补到信息密度够" and "编造具名事实" are different things: the former is the default, the latter never.

> 📎 细节见 `references/content-density.md`(thin heuristic 表、ALLOWED/NOT-ALLOWED 清单、Asking-prompt template)

## ONE-PAGER CASE POLICY (mandatory) — 一页纸案例 layout

> 📎 一页纸客户案例:**skip cover · 用 content/story-case · 绝不编造 STORY id/来源**。详见 `references/one-pager-case.md`

## RUN-FEEDBACK CAPTURE (mandatory) — auto-generated `FEEDBACK.md` per run

> 📎 详见 `references/run-artifacts.md`

## RUN-PROMPTS LOG (Phase 1) — `PROMPTS.md` per run

> 📎 详见 `references/run-artifacts.md`

## MAKING-OF LOG (default-on) — `log/` per run · 制作全过程纪录片

记录一份 deck 是怎么一步步做出来的(给同学还原过程 + 给自己诊断 skill bug),
平行存放在 `runs/<deck>/log/`,**绝不进 `out/`**。工具:`log-tool/deck-log.py`
(schema/细节见 `log-tool/README.md`)。**默认开**;`deck-log off` 全局停录。

固定动作(做 GENERATION 类 deck 时按部就班执行,无需用户提醒):

1. **开工**(建好 WORKSPACE 后):`deck-log init <run-dir> --title "<deck 名>"`
   → 搭 `log/` 骨架、记下当前会话 transcript 路径、设为活跃 deck。**每个回合的输入+我的
   原始回复无需手动记**:它们本就在会话 transcript 里,`render` 时自动捞 `start_ts` 之后
   那段(0 token,纯文件读;**不挂任何常驻 hook**)。自动找错了用 `init --transcript <path>`。
2. **每出一版**:`deck-log snapshot <run-dir> --label "<这版做了啥>"`
   → 冻结副本 + Playwright 截全套图(每页 1920×1080)+ 跑 check-distribution 校验。
3. **用户吐槽某页 / 我发现问题**:`deck-log event <run-dir> --type problem --slide N
   --msg "<问题>" --said "<用户原话>"`;修好后 `--type fix --resolves "<那个问题>"`。
   (这条 problem→fix 因果链是后面 `diagnose` 判断"哪些是框架 bug"的关键。)
4. **可选**给关键回合补一行摘要:`deck-log event <run-dir> --type summary
   --json '{"n":<回合号>,"msg":"<一句话>"}'`。
5. **收尾**:`deck-log render <run-dir>` → 生成 `log/making-of.html`(双击即看;
   `--inline` 出可分享单文件)。告诉用户路径。
6. **诊断**(用户问"哪些是 skill 该修的 bug"时):`deck-log diagnose <run-dir>` 出
   digest,**丢给 subagent 分析**,按 `AUDIT-*.md` 的 F-NN 工单格式产出候选工单。

Generate a dark, cinematic Lark / 飞书 brand-aligned **HTML deck** at 1920×1080 in a single
self-contained file that:

- looks identical on PC at 16:9 fullscreen,
- gracefully reflows to a vertical browse on mobile,
- never invents tokens — pulls every color, font size, gradient, radius, and spacing
  from `assets/feishu-deck.css`,
- ships with a built-in present mode (←/→/space, click-to-go), a scroll mode (mobile),
  a mode toggle, page indicator, and URL hash sync.

This skill is the **canonical interpretation** of the 飞书母版 2025 (深色通用) PowerPoint
master, expressed as design tokens and layout recipes.

---

## When to use this skill

Use it when the user wants:
- a slide deck delivered as an HTML file (not a `.pptx`)
- something that *looks like* a Lark / 飞书 / ByteDance enterprise pitch
- a dark, bilingual ZH+EN sales / quarterly / customer-pitch presentation
- both PC fullscreen and mobile-viewable in one artifact

If the user explicitly asks to PRODUCE a real `.pptx` file, route to the **pptx**
skill instead.

If the user hands over an EXISTING `.pptx` and wants it restored/imported as an
HTML deck ("把这份 PPT 还原成 HTML / H5", "import pptx", ".pptx 转 deck"), use the
**`pptx-to-html` sub-skill** in this skill's `pptx-to-html/` folder — it parses
the .pptx with python-pptx and emits a `layout:"raw"` deck.json that this skill's
`deck-json/render-deck.py` renders. Output goes to this skill's own `runs/` like
any other deck. Entry point:
`bash pptx-to-html/assets/run.sh <in.pptx> runs/<deck-name>`. See
`pptx-to-html/SKILL.md` (and `pptx-to-html/example/` for a hardened 60-page sample).

If the user asks for a generic non-Feishu deck (e.g. white background, Apple style),
this skill is the wrong choice — its design tokens are brand-locked.

---

## Files in this skill

`assets/` has two layers: **framework** (top-level: `feishu-deck.css`, `feishu-deck.js`, lark master brand kit `lark-logo*` / `lark-*-bg.*` / `lark-slogan.png` — ship with every deck, never deduped) + **shared content pool** (`assets/shared/`: cross-deck reusable PNGs, dedupe-able). `validate.py` / `apply-texts.py` / `copy-assets.py` / `new-run.sh` / `preflight.sh` / `bak-and-log.sh` also live in `assets/`.

### Brand-asset hard rules (mandatory)

1. **Client / portfolio / PE-VC logos** come ONLY from `assets/shared/clientlogo/<name>.{png|jpg}` (Chinese name first, then English short name; `_N` / `_paired` variants). If missing → ask the user to drop it in; do NOT save to `input/`, do NOT save to `assets/` root, do NOT auto-generate a text-fallback PNG.
2. **飞书 product icons** come ONLY from `assets/shared/feishu-products/飞书标识_{产品}_{变体}.png` (`_Color` default on dark). **NEVER redraw / hand-write SVG approximations / use emoji / fetch from web** — brand guidelines require the official PNG; the licensed files are right here. No matching product icon → fall back to `lark-logo.png`, never self-design.
3. **Digital-employee portraits** come from TWO folders: **named persona** (睿睿/参参/探探/呆呆/图图 + task personas) → `assets/shared/mydigitalemployee/<name>.png`; **anonymous/generic AI slot** → `assets/shared/digital_employee_avatars_50/NN_<traits>.png`. Never a gray-gradient placeholder, never crop from `input/`.
4. **Embed via `background-image` on a `<div>` (NOT `<img>`)** so the UI1 validator stays quiet and CSS controls sizing. (`<img>` only when explicit dimensions / max-width matter.)
5. **Phone-mockup bezel = R12 ring shadows** (`box-shadow: 0 0 0 Npx <color>` concentric rings), NEVER a real offset `box-shadow: 0 20px 56px …` drop shadow (R12 fails it).
6. **Never write per-asset PNGs to `assets/` root or `runs/<ts>/input/`** — `assets/` root is framework + lark master brand only; `input/` is ephemeral per-run. Shared assets are single-source-of-truth in `assets/shared/…`.

> 📎 细节见 `references/assets-and-files.md`(完整文件树、clientlogo/feishu-products/persona 查找流程与 embed pattern、phone-mockup demo 规格与动画时序)

## Phase 1.c extras — parity contract + regression smoke test (mandatory)

> 📎 详见 `references/extra-layouts-and-raw.md`

## Converting existing material (PDF / HTML / PPT export / docs) into a compliant deck

> 📎 转换 PDF/PPT/HTML/docs:**默认 1:1 页数不压缩(博裕&星巴克教训);先判 Replica vs Rewrite**。详见 `references/converting-existing-material.md`

## EDITING DISCIPLINE (mandatory) — high-cost bugs to avoid

BEFORE any delete-slide / insert-slide / reorder-slide / custom-layout edit, run this breadcrumb:

- **删/插/重排任何 slide → E1** 重编 `data-screen-label`(始终)、`data-text-id`(若有 texts.md sidecar)、`data-page`(仅当该 frame 带 per-page scoped CSS)并同步 deck 内 `[data-page="NN"]` 的 scoped CSS 选择器。**只更新该 slide 上确实存在的标识符**(没有「每页都必须有 data-page」这条规则)。改完跑 `python3 assets/validate.py runs/<ts>/output/index.html`(R-DOM / T03 / R20)。
- **E2** 绝不用 `sed` / regex / 纯文本替换改 slide DOM 结构——会吃掉相邻 frame 的 `</div>` → 嵌套塌陷 → R-DOM。结构改动靠「读文件、人工定位 slide 块、整段写回」;文本编辑用 `apply-texts.py`(按 `data-text-id` 解析,位置安全)。安全网:每次结构改动后跑 R-DOM(`audit_dom_integrity`)——每个 `.slide-frame` 必须是 `.deck` 直接子节点、恰好含一个 `.slide`。
- **E5** 动过任何页都欠一次 squint/再平衡:删/改/继承/交付任一原因看一页,都要 1/3 缩放眯眼检查有没有空白带,有就在 stage/grid/card 上补 `justify-content: center` / 降 `repeat(N,1fr)` / 去 `margin-top:auto` 等再平衡。**validator PASS ≠ 视觉平衡**;加内容则反向查溢出。

> 📎 细节见 `references/editing-discipline.md`

## ROUND-TRIP INTEGRITY (mandatory) — `deck.json` is the source of truth, never post-render-edit `index.html`

`deck.json` 是 deck 视觉状态的唯一规范;`index.html` 是 `render-deck.py` 的派生产物。只存在于 `index.html` 而不在 `deck.json` 的状态 = silent drift,下次 render/fork/下游工具读 `deck.json` 时会被毁掉。两半契约:

- **A 半(创作侧)**:不要 post-render-edit `index.html`。所有视觉状态(CSS / HTML 结构 / 动画 / 脚本 / dev-tools 试出来的改动)必须回写进 `deck.json`(`layout: raw` 进 `data.html`,schema layout 进对应字段)。浏览器里快速试验可以,但**交付 / fork / 入库前必须 port 回 `deck.json`**。
- **B 半(fork / clone / download 侧)**:从既有 deck 派生时,**拷整个 output 文件夹**(同时带 `deck.json` 和 `index.html`),不要只拷 `deck.json`(那样会静默丢掉原作者的所有 post-render 编辑)。fork 后先跑 `python3 deck-json/sync-index-to-deck.py <new>/output/index.html <new>/output/deck.json --dry-run` 查 drift,有就去掉 `--dry-run` 回灌,再 re-render 验证,然后才开始编辑。

> 📎 细节见 `references/round-trip-integrity.md`

## LIFTING A SLIDE FROM ANOTHER DECK (mandatory route) — deck.json-native first, never read the monolith

把别的 deck 的一页拎进当前 deck。**默认走 deck.json,绝不为了找/拆一页去读源 `index.html` 或 3491 行 `feishu-deck.css`**(那是被弃用的老路,慢且费 token)。按源 deck 形态二选一:

- **源是本技能产出的 deck.json(常态)→ `deck-cli.py paste`**:
  ```bash
  python3 deck-json/deck-cli.py SRC/deck.json show <key>                          # 可选:先看这一页(~2-4KB 对象)
  python3 deck-json/deck-cli.py DST/deck.json paste --from SRC/deck.json --key <key> [POS]
  python3 deck-json/render-deck.py DST/deck.json DST/                              # custom_css 随对象 travel,自动 scope
  ```
  纯 JSON 对象复制 —— 自动拷 `input/`、`prototypes/` 资源、key 冲突自动改名、剥离源绑定的 `data-text-id`、写 `lifted` 溯源、自动备份 + 复校。要按 key 浏览源 deck 看 `SRC/slide-index.json`(render 自动产出的清单)。
- **源是外来 / 老 deck(没有 `custom_css` 的页)→ `assets/lift-slides.py … --shake`**:
  ```bash
  python3 assets/lift-slides.py SRC/index.html --index                            # 列清单挑 key(不读正文)
  python3 assets/lift-slides.py SRC/index.html --key <key> DST/deck.json --shake   # tree-shake → layout:raw
  ```
  **`--shake` 让任何老 deck 直接切干净、无需预先修**:内联该页真实 layout 的框架 CSS + **把源 head 里属于这页的 per-slide 规则(`[data-slide-key]`/`[data-page]` page-anim 老坑)搬进来并把 `[data-page=N]` 改写成 `[data-slide-key]`** + 拉回引用的 `@keyframes`。全局 `.slide .foo` 规则不内联(任何目标 deck 都有)。

**配套硬规矩 —— 每页的定制 CSS 只放 `slide.custom_css`,绝不放 `<head>` / page-level `<style>`**:渲染器会把 `custom_css` 自动 scope 到 `.slide[data-slide-key=KEY]` 并 co-locate 进该 slide(`<style data-fs-custom-css>`),这样它能随 lift/clone/paste travel 且 round-trip 不丢。写无前缀选择器即可(`.card{…}`),`@keyframes`/`@media` 也放这里。head 里塞每页 CSS = republish 静默蒸发(`fs-deck-page-anim` 旧坑),已被本路径取代。

**切老 deck 不用预先修**(`--shake` 会在切的时候就地恢复 head per-slide CSS)。`migrate-head-css-to-custom-css.py` codemod 是**可选**的、用来**把源 deck 自己修 durable**(让它自己 re-render/republish 不再丢动画,且之后可走 native `paste`):`python3 deck-json/migrate-head-css-to-custom-css.py <out>/index.html <out>/deck.json --dry-run`(先体检,`nothing to migrate`=干净)→ 去掉 `--dry-run` 加 `--render`(自带 `.bak`、幂等;`[data-page=N]` 按渲染 DOM 实际对应映射;不可归属的规则只报告不动)。`R-SELF-CONTAINED`(advisory)标出还在 head 的泄漏。

> 📎 架构/根因/路线图(L1–L7)见 `LIFT-ARCHITECTURE-2026-05-30.md`;round-trip 细节见 `references/round-trip-integrity.md`。

## Operational notes (gotchas)

> 📎 详见 `references/operational-notes.md`

## Quick start (recommended workflow)

**DeckJSON-first 默认流。** 你写数据(deck.json),`render-deck.py` 出 HTML;不要手抄 `_shell.html`、不要从 slide-recipes 复制 markup、不要手标 `data-text-id`(那是已废弃的旧手写流)。

1. **PREFLIGHT** — `bash assets/preflight.sh`(硬闸门,必须 PASS 才动手)。
2. **DESIGN PHASE(chat-only,默认开)** — 标 hero 页、逐页定 layout/path、定补全与密度预算、hero 写 Q0–Q4 + 六维 spec;走默认 layout 之外的设计先停下确认,全 schema 宣告即走。
3. **建工作区** — `bash assets/new-run.sh <slug>` → `runs/<ts>-<slug>/{input,output}/`,落 `DESIGN-PLAN.md`,announce 路径。
4. **写 `deck.json`(Path A · schema-driven)** — 按 `deck-json/deck-schema.json` 的 15 个 layout(12 base + `raw`/`replica`/`iframe-embed`)填数据,写到 `runs/<ts>-<slug>/output/deck.json`。最小例:`deck-json/examples/phase-1a-demo.json`。
5. **渲染** — `python3 deck-json/render-deck.py runs/<ts>-<slug>/output/deck.json runs/<ts>-<slug>/output/`,自动产出 `index.html + texts.md + assets/`(无需手标 text-id)。
6. **闸门** — `bash assets/finalize.sh runs/<ts>-<slug>/output/ local`(跑 copy-assets + extract-texts + validate);validate.py exit≠0 必须改 deck.json 再重跑,通过前不交付。
7. **交付 A/B/C** — 见 DELIVERY MODES;禁裸 "单 linked HTML";重命名 `lark-<客户>-<YYYY-MM-DD>.html`,每轮 surface 产物路径。用户改 `texts.md` 回灌即可改文案。

> Path B(整页手写 `index.html`)是**极少用的逃生口**,仅当某 pattern 既不匹配任何 schema layout、也无法用 `layout: "raw"` 单页表达时才用;见 `DECK GENERATION POLICY`。
> 📎 细节见 `DECK GENERATION POLICY` · `references/delivery.md`

## Available layouts

Pick by content, not by aesthetic. Each layout corresponds to a `data-layout` attribute
on `.slide`. Full markup lives in `templates/slide-recipes.html`.

| Layout            | Use when                                     | Accent default |
|-------------------|----------------------------------------------|---|
| `cover`           | First slide. Title + EN subtitle + brand + date. | blue |
| `agenda`          | TOC. 4–8 numbered items in 2 columns.        | blue |
| `section`         | Chapter divider. Giant `01` numeral + ZH title + EN lede + product pills. | blue |
| `content-3up`     | Three parallel pillars / capabilities / pillars. | blue |
| `content-2col`    | One narrative + supporting visual / mock / list. | blue |
| `quote`           | Single customer / executive quote, centered.  | blue |
| `stats`           | 4-up KPI row with big numbers as evidence.   | **teal** |
| `big-stat`        | One hero number (e.g. `30万`) + paragraph.    | blue |
| `image-text`      | Single full-bleed photo with type bottom-left. | blue |
| `table`           | Comparison or matrix. Up to 6 rows × 5 cols. | blue |
| `timeline`        | Chronological 4–6 milestones along an axis.  | blue |
| `process`         | 3–6 sequential steps with right-pointing arrows. | blue |
| `end`             | Closing — title + CTA pills + contact grid.  | blue |

**Mix rule.** A 12-slide deck typically uses 7–9 distinct layouts. Repeat `content-3up`
for parallel concepts; otherwise alternate to keep rhythm.

---

## The shell (single-file deck skeleton)

`templates/_shell.html` 是 canonical 结构(从那里拷,不要在此处粘整段 HTML)。

**强制 DOM 顺序:`.deck > .slide-frame > .slide`**——runtime 依赖它,嵌套错了会静默隐藏 slide(frame 必须是 `.deck` 直接子节点,每个 frame 恰好含一个 `.slide`)。

资源路径:per-run deck 在 `<repo>/runs/<ts>/output/index.html`,CSS/JS 需爬三级再进 skill 目录 `../../../skills/feishu-deck-h5/assets/feishu-deck.{css,js}`;单文件交付则把 CSS inline(见「Single-file inlined output」)。

> 📎 模板见 `templates/_shell.html`

## Layout recipes (canonical copy-paste markup)

> 📎 详见 `references/layout-recipes.md`

## Iconography

- Use **Lucide-style inline SVG**, 24 px viewBox, `stroke: currentColor`, `stroke-width: 2`,
  `stroke-linecap: round`, `stroke-linejoin: round`, `fill: none`. Inherit color via the
  parent (`.tile` colors children to `--fs-accent` automatically).
- For production, recommend the user swap to **ByteDance IconPark** for licensing parity.
- **Never** use emoji or unicode glyphs (`✓ ✗ → 🚀`) as icons. Always real SVG.

A small library of go-to icons is included in the recipes above. When the LLM needs
a new icon, it should hand-write the SVG path rather than reference a remote URL.

---

## Single-file inlined output (recommended for delivery)

For a portable artifact, the agent should produce ONE `.html` file with CSS + JS inlined:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>...</title>
  <style>/* paste contents of assets/feishu-deck.css */</style>
</head>
<body>
  <div class="deck">
    <!-- slide-frame entries -->
  </div>
  <script>/* paste contents of assets/feishu-deck.js */</script>
</body>
</html>
```

The `examples/sample-deck.html` file is built this way and is the reference output.

---

## Layout default: content sizes itself, the stage centers it

**Default = the inner container centers vertically; content takes its natural height.** Never leave content stranded at the top of an empty canvas.

- **CENTER (fixed-shape layouts):** `content-3up`, `content-2col`, `agenda`, `stats`, `big-stat`, `quote` — their stage gets `justify-content: center` (or `align-content`/`align-items: center`/`place-content: center`). Dense slides (≥80% fill) resolve to top-aligned anyway, so this is safe for both sparse and dense.
- **FILL (stretched-flow layouts):** `pipeline`, `timeline`, `process` — these `flex: 1` their step/node row to span the canvas. Don't strip that.
- Container name is per-layout: `.grid` / `.toc` / `.flow` / `.nodes` / `.stack` / `.stage` all count as valid centering targets.

Enforced by `validate.py` rule **R48** (`audit_default_centering`) — blocks delivery if a fixed-shape layout's container lacks centering.

> 📎 细节见 `references/layout-recipes.md`

## 布局正确性 = 一次做对(correct-by-construction)优先,校验是安全网

**目标:deck 生成出来本身布局就对,而不是每次靠校验抓出来再改。** 优先级:

1. **生成即对(主力)** —— 居中、内容尺寸、卡片分布等布局正确性由**框架 CSS / schema 默认**保证(`.stage` 居中;版式 scoped 默认,如 content-3up / process / matrix / before-after / logo-wall 的"内容尺寸 + 共享中线 + 卡内垂直居中")。schema 路径理想是"零 finding":你描述 *what*,框架负责 *layout*,不手调字号/位置去凑。
2. **校验(R48 / R-VIS-BALANCE / R-VIS-CROWD / L1–L4 …)= 安全网,不是主力** —— 只兜 construction 保证不了的(`layout: raw` 手写页、极端内容、外来 deck)。理想状态它越来越安静;**靠校验反复抓同一类布局问题 = 信号:该把它修进框架默认**。
3. **反复出现的版式缺陷 → 修框架,别只加检测、更别每个 deck 局部 workaround。** 维护者标准打法:对该版式写 **scoped CSS 默认**(覆盖该 `data-layout`,不动全局 legacy 规则)→ 用 `assets/check-distribution.py`(三层 name-free 几何分布审计:画布/组/框;`--css` 注入测、`--fix` gated 修正)在**不均内容**上验证 findings 下降 **且其它版式零回归** → 再合;能升 schema 默认就别留给人手调。豁免要几何/结构判定(如 stats KPI 列顶基线对齐),**不要按版式名开白名单**。

> 📎 细节见 `references/layout-recipes.md`

## 导入外来 raw HTML deck:字号问题照报,修法二选一,绝不盲 snap

拿到 / 导入一份**外来手搓 HTML deck**(不是本技能 schema 生成的)时:

1. **字号问题照报,imported 不豁免**(2026-05-30 修正,曾错把 imported 的字号降 advisory,等于把问题藏了 —— 已撤回)。小正文(<24)投影看不清、hero 尺寸不对,**谁设计的都是问题,validator 照报 R06/R20/R-VIS-TIER/下限**。`<meta name="fs-deck-origin" content="imported">` 现在只是**来源标记**(不改字号严重度)。
2. **错在「修法」,不在「报」。snap = 把字号 px 拍到 4 档却不管框** → 撑爆适配 / 把 hero 压小、丢重点(见 `IMPORT-RAW-DECK-LESSONS-2026-05-30.md`)。正确修法二选一:
   - **(A) 保留原设计 + 把字号修对** —— ① 换当前框架 JS:`python3 assets/rebundle-import.py <deck.html>`(auto-balance 加载修 box-crowd〔文字贴底〕,零字号/chrome 触碰);② **小正文 → 提到下限 24 + 框自动长高(改大自动拉高;画布有空间就拉高框,没空间才压内容/删条目),永不缩字号**;③ **hero/封面 → 走 layout 定义的 hero 尺寸**(该大就大,不是随便一个 82);④ chrome 永远排除。
   - **(B) 重生成走 schema** —— 按 `deck.json`(Path A)重做,字号**按角色**给(重点→hero、正文→24、chrome→框架),内容与字号一起设计、天生适配 = correct-by-construction。
3. **绝不**「snap 字号 px 完事不管框」—— 这是拍平设计、级联溢出的**类别错误**。修小字靠 **enlarge + grow-box**;修 hero 靠 **layout 尺寸**;chrome(翻页器/全屏提示/wordmark/pageno)永远不是内容,任何变换/检查都排除它。

> 📎 复盘见 `IMPORT-RAW-DECK-LESSONS-2026-05-30.md`(L1 已撤回,见文内修正记)

## Variant override discipline

> 📎 详见 `references/layout-recipes.md`

## Re-render UI mocks as HTML, not screenshots

> 📎 详见 `references/reskin.md`

## Layout integrity rules — execute, don't assume

Four mandatory layout audits (run before sending, never "best practice"). The user should never have to point out a top-stacked layout, an empty middle, or a mono logo on content slides — if they do, you skipped these.

- **L1 — Logo defaults to COLOR.** `.slide .wordmark` background MUST be `var(--fs-asset-logo)`; mono is opt-in via `class="is-mono"` (chapter/section pages only). Mono on every content slide = broken L1.
- **L2 — No content stranded at the top.** If a slide's content fills <60% of canvas height, either center vertically (`align-content: center`) or grow to fill (`flex: 1`). Never top-stack with an empty bottom.
- **L3 — `margin-top: auto` on a stretched card = empty-middle bug.** Combine L2 centering with content-sized rows (`grid-template-rows: auto`) so cards are content-tall, not canvas-tall.
- **L4 — Narrow output-panel attribute lists use a single column.** `process` output panel (~400 px) attrs MUST be `grid-template-columns: 1fr`, never `1fr 1fr` (2-col truncates 22 px body text).

Validator ships L1 / L2 / L4 (L3 not currently shipped).

> 📎 细节见 `references/layout-recipes.md`

## Self-check must be EXECUTED, not just listed

The validator is a hard gate, not a checklist for reading pleasure. Before declaring a deck "done":

1. **Run it.** `python3 assets/validate.py path/to/deck.html` — exit 0 = pass · **exit 1 = delivery BLOCKER** · exit 2 = file not found. Fix every error; don't paper over it by editing the validator.
2. **Use `--strict` as the pre-delivery gate** — it promotes warnings (mono logos, off-palette hex) into errors. Default mode lets warnings pass for an in-progress deck.
3. **Re-run after EVERY rebuild** — chain it: `bash build.sh && python3 assets/validate.py examples/sample-deck.html || exit 1`. Makes regression detection automatic.
4. **Human-eye items the validator can't judge:** visual alignment (title baseline ↔ logo center), ZH > EN sizing balance, atmospheric "feel" (glow vs content density), narrative landing. Open at 1920×1080, 1280×720, 380×680 and look — then ship.

`examples/sample-deck.html` passes in both default and `--strict` mode — that's the bar.

> 📎 细节见 `references/validator-rules.md`

## Preserve atmospheric / decorative backgrounds when re-rendering

> 📎 详见 `references/reskin.md`

## CSS layout pitfalls (defenses already in feishu-deck.css)

> 📎 详见 `references/layout-recipes.md`

## Prototype / standalone-page embed modes (mandatory) — pick BEFORE you write any code

> 📎 嵌入已有 HTML/原型/别的 slide:**别默认 iframe — feishu slide→native lift;外来 demo→iframe A/B;简单内容→re-author C**。详见 `references/prototype-embed.md`

## Embedding prototypes (iframe rules)

> 📎 详见 `references/prototype-embed.md`

## Narrative patterns (DESIGN.md §9 — A through K)

> 📎 详见 `references/narrative-patterns.md`

## Copy / numbering 规范

These are content rules — they affect what to *write*, not how to render it.

1. **Cite numbers inline.** When a slide cites a number, put the
   citation right next to the number — as a trailing `<span class="caption">`,
   a small `<p class="caption">` under the heading, or in the body
   sentence itself ("…根据 12 家中国头部企业 2024 Q3-Q4 实测"). This
   keeps the deck reading like a board memo. (`.source-footer` was the
   pre-2026-05 way; retired alongside `.footer` chrome.)
2. **Eyebrow numbering uses `01 / 02 / 03 / 04-A / 04-B / 04-C / …`** to
   express chapter+sub-page hierarchy. When a focus area expands across
   multiple pages, sub-letters are mandatory.
3. **CN ↔ EN separator:** ZH text + space + `·` + space + EN text.
   No em-dashes, no slashes, no parens.
4. **Single ACCENT4 (teal) emphasis per page.** The keyword-jump rule applies
   to *every* page, not just quote/金句. If two phrases compete for emphasis,
   pick one or step back to a neutral color.
5. **Match deck length to actual narrative arc.** A short pitch can stop on
   the last content slide — don't force a quote slide and a closing slogan if
   the story doesn't earn them. Use `end` only when there's a real "end".

---

## Helper-snippet recipes

Reusable HTML+CSS combos — the CSS already ships the styles; copy the markup. Named helpers (expand to the recipe in the reference when generating):

`north_star_chip` · `verdict_card(go/cond/nogo)` · `boundary_band(no,yes)` · `evolution_chip(now,future)` · `principle_band(items)` · `phone_frame_iframe(src)` · `desktop_iframe(src)` · `aurora_background()` · `fullscreen_button()` · `north_star_map(N,cards)` (Pattern L) · `scene_grid(cards)` (Pattern M).

Roadmap helpers (no CSS yet — write markup by hand): fork visualization, iron-4-corners, 6-step pipeline timeline, two-track structure, 1+1 vs 1+1+N boundary tags.

> 📎 细节见 `references/narrative-patterns.md`

## Richness primitives (v1.3) — promoted from the deck_v3 reference

第二层 helper,专为阻止交付「骨架」deck 而存在。**richness 是默认,不是「有空再加」**——引数字却不上 `.kpi-strip`、收尾不上 `.cta-box`、转化不上 `.ui-wave + .report-item`,就是 under-deliver。没有 `.is-rich` 开关,`.card` 默认就带 hover ring + gradient tile,`.step` 默认带 chevron。

**MANDATORY:用 `.grid` / `.flow` / `.nodes` / `.toc` / `.table-wrap` 等绝对定位 body 容器 + 任何 helper 时,必须把 body 容器和 helper 一起包进 `<div class="stage">`**。否则 helper 落入正常流顶端、压住 header → 视觉破损。`.stage` 成为绝对定位 body 区(top:220/bottom:110/left·right:96),内部容器改为在 stage flex 列里流式排布,helper 自然堆在 body 下方。支持 `.stage` 的 layout:`content-2col` / `content-3up` / `process` / `timeline` / `table` / `agenda` / `stats`(cover/end/image-text/big-stat 有自己的 `.stage` 语义)。无 helper 的纯 body 页可省略 `.stage`。

**禁止默认加 `<div class="grid-bg"></div>`**——飞书母版 content layout 已用 `lark-content-bg.jpg`(`--fs-asset-content-bg`)做 ambient 渐变,叠 dot-grid 会双重噪点、脱离母版;仅 engineered/technical 自定义 layout 显式需要时才 opt-in。

Helper 名单:`.pullquote`(收口论点)· `.voice-card`(证言)· `.cta-box`+`.cta-btn`(行动呼吁)· `.kpi-strip`(指标行,设 `--strip-cols`)· `.calc`/`.calc-row`/`.calc-result`(ROI 计算器,需 ~12 行内联 JS)· `.ui-row` / `.ui-alert` / `.ui-kpi` / `.ui-wave` / `.report-item`(ui-window 内的 dashboard / 波形 / 洞察行)。tone 变体多为 `.is-teal/.is-blue/.is-orange`,`.report-item` 用 `.is-warn` / `.is-info`。

> 📎 细节见 `references/richness-primitives.md`

## Performance budget (hard rules — enforced by `audit_perf`)

A 13-slide deck stays lean. `validate.py audit_perf` enforces (each has a CSS/JS fix, no external deps):

- **P50** — base64 in `<style>` ≤ 100 KB default (250 KB hard error). Use `bash build.sh` (linked). Single-file mode requires `<meta name="fs-deck-mode" content="inline">` to skip P50 — `build.sh --inline` adds it; hand-built single-file decks must add it manually or get flagged.
- **P51** — `backdrop-filter: blur(N)` ≤ 10 px.
- **P52** — `new ResizeObserver()` count ≤ 1 (one document-level RO with rAF batching).
- **P53** — ≥8 `addEventListener` must use `AbortController` + `{signal}` + expose `destroy()`.
- **P54** — `.slide-frame { contain: layout paint size }`.
- **P55** — `.slide-frame .slide { will-change: transform }` + `translateZ(0)`.

Linked (default) = ~24 KB + external `assets/*`, 0 base64, passes P50. Inlined (opt-in, email/IM) = ~360 KB, needs the `fs-deck-mode=inline` meta.

## Content-page header — title only, no eyebrow, no sub-line

Content-page header is intentionally minimal — just the title:

```html
<div class="header">
  <h2 class="title-zh">懂我的AI,可以代我做方案评审</h2>
</div>
```

**No eyebrow above, no subtitle below, no inner wrapper div, no inline page number** (page numbers come from the present-mode pager; per-slide chrome retired 2026-05). A content slide already carries its body (cards/table/flow) — stacking eyebrow+title+sub-line creates hierarchy noise. CSS enforces defensively: `.slide .header .eyebrow { display: none; }`. The `.eyebrow` class still works elsewhere (cards, section dividers, stats columns).

**Hero exception:** `cover` / `image-text` / `end` use their own `.stage` container, not `.header`, so they keep their existing title patterns. (Enforced by validator R56.)

## Self-check — the validator IS the self-check

Run before every delivery:

```bash
bash assets/finalize.sh runs/<ts>/output local            # in-progress
bash assets/finalize.sh runs/<ts>/output local --strict   # final delivery
```

`finalize.sh` orchestrates `copy-assets` → `extract-texts` → `validate.py` in order. Every validator error prints **what's wrong + how to fix** — read it, fix it. Don't suppress.

**Severity model:** each audit emits `warn` / `err` / `warn_soft` at its inherent severity. `--strict` promotes all regular `warn`s to errors. **Soft warnings** (`warn_soft` — currently `R-FEEDBACK`, `R-VIS-ALIGN`) are editorial advisories that NEVER escalate under `--strict`.

**What the validator can't catch — needs human eyes before delivery:**

- **Visual alignment** — title baseline ↔ logo center, agenda numerals ↔ titles
- **Atmospheric feel** — gloom/glow density vs content density (open at 1920×1080 and squint)
- **ZH-EN sizing balance** on bilingual decks (ZH must read bigger / sit above)
- **Narrative landing** — does each slide deliver its one point in 3 seconds?

Open at 1920×1080 (PC), 1280×720 (laptop), 380×680 (phone). If any breaks visually, fix the slide.

> 📎 细节见 `references/validator-rules.md`

## Failure modes & fixes

> 📎 详见 `references/troubleshooting.md`

## Caveats to relay to the user when delivering

> 📎 详见 `references/delivery.md`

## Examples

- `examples/sample-deck.html` — 12-slide demo using all 13 layouts (single file, inlined).
- `preview-dark.html` — token swatches + component gallery for visual self-test.
- `templates/slide-recipes.html` — every layout in one reference deck (open and copy).
