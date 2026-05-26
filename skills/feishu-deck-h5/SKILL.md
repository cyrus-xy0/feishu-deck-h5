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

## MODE SELECTION (read this first — pick CHECK-ONLY vs GENERATION)

Before reading anything else in this file, decide which mode the user is in:

| Mode | Trigger phrases / signals | What to do |
|---|---|---|
| **CHECK-ONLY** | "帮我检查这份 HTML/deck" · "看看这个 deck 合不合规" · "审一下这个 HTML" · "validate this" · "check the deck" · "扫一遍合规问题" · "这个 HTML 哪里不对" · user hands over a path to an existing `.html` and asks for review WITHOUT asking to generate / modify content | **Jump to "CHECK-ONLY MODE" section below.** SKIP PREFLIGHT, SKIP `new-run.sh`, SKIP `copy-assets`, SKIP everything else in this file. |
| **GENERATION** *(default)* | "做一份飞书 deck" · "把这个 PDF 转成 HTML" · "客户提案" · "周会汇报材料" · "改一下第 N 页" · anything where output is a new or edited HTML deck | **Run the DESIGN PHASE first (default-on, chat-only)** — 标 hero 页、逐页定 path、定补全计划、给 hero 页写 Q0–Q4 + 六维 spec。任何一页走默认 layout 之外的设计就停下确认;全 schema 宣告即走。然后 PREFLIGHT → new-run(落 `DESIGN-PLAN.md`)→ 按 path 生成(Path A schema 见 `DECK GENERATION POLICY`;hero 的 `layout: raw` / bespoke 见同节 + `DESIGN-FIRST POLICY` 词汇库)。 |

If a request is genuinely ambiguous ("can you look at this HTML and improve it?"
— check or rewrite?), ask the user once to clarify before branching.

---

## DESIGN PHASE (mandatory · default-on) — 设计先行,生成前的第一步

GENERATION mode 的**第一步,默认执行**。它只在 chat 里发生(不创建任何文件,
所以不和 PREFLIGHT "blocks all work" 冲突)。运行顺序:

> **DESIGN PHASE(chat)→ [按风险确认] → PREFLIGHT → new-run(落 DESIGN-PLAN.md)→ 按 path 生成**

这一节是**编排器**:把下面三条既有 policy(`DECK GENERATION POLICY` /
`DESIGN-FIRST POLICY` / `CONTENT-DENSITY POLICY`)串成一个阶段,并把默认值
钉在"**用好 LLM 做设计**"这一侧 —— 因为下限有 validator 兜底,上限只能靠
LLM 多做创造性工作(补文案、补内容、为高光页写 bespoke layout)。细节仍在
各自 section,本节只给编排 + 默认值 + 指针。(CHECK-ONLY readers skip this section.)

### 默认执行 = 设计思考 always 跑;确认门按风险触发

- **设计思考永远跑** —— 标 hero、定每页 path、定补全计划、给 hero 页写页级
  spec。这些 every run 都做,**不因为"用户说直接出"就跳过 thinking**。
- **确认门是条件触发的**:
  - 全 deck 都落在默认 Path A schema layouts(15 个之内)→ **宣告方案即可往下走**,
    不强制停下等批准。
  - **任何一页走"默认 layout 之外"的设计**(`layout: raw` / bespoke hero /
    超出用户给定材料的重度内容补全)→ **必须停下,把那几页的设计 spec 逐项
    摆出来等用户确认**,改了回 Step 1/2,再生成。
  - 用户明说"直接出 / 别问" → 跳过的是**确认那一下**,不是设计思考。
- **退化场景**(设计阶段坍缩成一句话,见 `Converting existing material`):
  Replica PDF 1:1 贴图 / 单页精修(只动这页,标题 verbatim)/ 用户已明确给定 layout。

### 四步

**Step 1 · Deck 级**
- 叙事弧 + 页数(转换已有材料默认 1:1,见 `Converting existing material` Step 0)。
- 标 **hero 页**(通常 2–3 张高光:封面 / 那一个大论点 / 关键案例 / 收尾)。
  这是"放开 LLM"的**作用域开关** —— hero 页才全开 bespoke,其余页求稳,
  避免把 floor 在全 deck 搞松。
- 逐页定 **path**:hero → `layout: raw` + 词汇库 pattern(见 Step 2);
  其余 → Path A schema(见 `DECK GENERATION POLICY`)。
- **内容/文案补全计划**:默认就**专业补全**(见 `CONTENT-DENSITY POLICY` —
  默认动作是"补",不是"先问")。只标"哪几页补、补什么方向"。唯一硬护栏:
  **不编 attributed facts**(具体公司数字 / 具名引语 / 来源出处 —— 见 ONE-PAGER
  的 no-fabrication 规则)。

**Step 2 · 页级 spec(Q0–Q4 + A 档六维)**
- **hero 页:必填** Q0–Q4 + 六维 spec(见 `DESIGN-FIRST POLICY` 设计前预检)。
  且**先翻设计词汇库再落 layout** —— `narrative patterns A–N` + `component
  utility classes`(见文末两节),挑一个 striking pattern,而不是反射性套 3 卡。
- **支撑页:轻量** —— 角色判断 + `Decision rule` 选个 schema layout 就够,
  不必写满六维。

**Step 3 · 输出设计方案**
- chat 里出 Design pass 表(格式见 `DESIGN-FIRST POLICY` → Design pass output),
  每行带:角色 / 唯一重点 / path / 是否 hero。
- hero 页各附一句话 design intent statement。

**Step 4 · 闸门 + 落盘**
- 有 beyond-default 页 → 等用户确认;全 schema → 宣告即走。
- 确认/宣告后:PREFLIGHT → new-run → **把锁定的方案写一份
  `runs/<ts>/output/DESIGN-PLAN.md`**(与 FEEDBACK.md / PROMPTS.md / texts.md
  同级),生成严格照它走;中途想偏离先回来改 plan,不静默漂移。

### DESIGN-PLAN.md 落盘(mandatory)

new-run 之后立即写 `runs/<ts>/output/DESIGN-PLAN.md`,内容:

1. **方案表** —— Step 3 那张表(逐页:角色 / 唯一重点 / layout 或 path / 是否 hero / 为什么)。
2. **hero 页 spec** —— 每张 hero 页的 Q0–Q4 + A 档六维 + 选定的 pattern。
3. **补全计划** —— 哪几页补了内容 / 文案,补的方向,并标注来源性质(公开行业知识 / 产品能力 / 类似客户故事),确认没有 attributed facts。

作用:(1) 生成步有据可依,防 LLM 自己跑偏离开方案(冰红茶 slide 9 那类);
(2) 用户 / 维护者事后能复盘"这份 deck 当初是怎么设计的";(3) 二次迭代时是 diff 基线。
随 run 一起走(`package-deliverable.sh` 已含 `*.md`)。

---

## CHECK-ONLY MODE

The user gave you an HTML file (own deck, foreign deck, downloaded sample,
PR for review) and just wants to know what's non-compliant. The skill ships
a dedicated entry point for this:

```bash
bash skills/feishu-deck-h5/assets/check-only.sh <html-path> [--strict] [--visual] [--report PATH]
```

What it does:

1. Runs the full `validate.py` rule set (R02 / R05 / R06 / R10 / R12 / R13 /
   R20 / R29-32 / R36 / R38 / R47 / R48 / R49 / R56 / L1-L4 / UI1 / R-LANG /
   R-KEY / R-DOM / R-WHITE-TEXT / R-HIERARCHY / T00-T03 / P50-P55 / R-FEEDBACK).
2. Auto-resolves linked `<link rel="stylesheet">` / `<script src="">` so a
   non-inlined deck validates correctly (same logic as `validate.py`).
3. Groups issues by **family** (结构/DOM · 排版/文案 · 品牌/调色板 · 布局完整性
   · UI 仿真/slide-key · 演示模式/运行时 · texts.md 联动 · 性能预算 · 视觉 ·
   交付物附件) and produces a markdown report.
4. Auto-detects deck mode via heuristics (Replica `.page-replica` /
   inline `fs-deck-mode=inline` / bilingual `fs-language=zh-en`) and prints
   a hints block at the top of the report.
5. Flags **context-dependent rules** (T00 / T03 / UI1 / P50 / R29-32 /
   R-FEEDBACK) — these often false-positive when a deck is a Replica, an
   external HTML, or a non-`new-run`-flow artifact. The report shows them
   but explains when they're safe to ignore.

### When to use what flags

- **default** — `bash check-only.sh deck.html` — warn ≠ blocker. Use for
  first-pass review of someone else's deck. Exit 0 if no errors.
- **`--strict`** — `bash check-only.sh deck.html --strict` — warns promoted
  to errors. Use when the deck is going to a customer and you want zero
  warnings.
- **`--visual`** — adds Playwright-based renderer audits (R-OVERFLOW /
  R-VIS-TIER / R-VIS-HIER / R-VIS-LABEL-FLOOR / R-VIS-ALIGN). ~5s per 30-slide
  deck. Requires `pip install playwright && python -m playwright install
  chromium` once.
- **`--report PATH`** — write the markdown report to a file (stderr prints
  "✓ 报告已写到 …"). Default: stdout. When writing to a file, you can
  forward it on Lark / email as a review note.
- **`--gate ingest`** — 入库门禁模式 (业务语言, A/B/C 业务关切分组).
  See "Gate ingest mode" below.

### Gate ingest mode (入库门禁)

The `--gate ingest` flag turns check-only into a **slide-library 准入扫描**:

```bash
bash skills/feishu-deck-h5/assets/check-only.sh deck.html --gate ingest
```

Differences from default mode:

| Aspect | Default | `--gate ingest` |
|---|---|---|
| Rules checked | 全部 (~40 条) | 21 条必修 (业务关切 A/B/C) |
| Warns | 不阻塞 | 全部升级为 error |
| Visual audits | `--visual` 开启才跑 | **自动开启** |
| Report 分组 | 按 family (技术视角) | 按业务关切 A/B/C (业务视角) |
| Report 语言 | 技术语言 (规则名 + 技术描述) | **业务语言** (症状 + 不修后果 + 修改步骤 + 技术代码小字附注) |
| 数据来源 | 硬编码在 .py | 读 `business-rules.yaml`, 可由非工程师维护 |
| 出口码 | exit 1 if any error | exit 1 if any 必修违规 |
| 用途 | review-style 看 deck 卫生 | **库的 ingest-package.py 自动调** |

#### 21 条必修规则 (按业务关切分组)

> 全部规则的业务文案 (症状 / 不修后果 / 修改步骤) 在
> `assets/business-rules.yaml`. 非工程师可直接 PR 改文案.

**A · 客户看不见 (5 条)** —— 投影上的硬伤
- `R-OVERFLOW` 内容超出 1920×1080 画框
- `R06` 正文字号 < 24px
- `R-WHITE-TEXT` 文字色融背景
- `L2` 内容堆顶留空
- `L4` 多列被挤窄字截断

**B · 库找不回这张 slide (5 条)** —— locator 失锚
- `R-KEY` 缺 slide-key
- `R-DOM` DOM 嵌套坏
- `R02` 缺 layout / 屏幕标签
- `T01` text-id 格式错
- `T02` text-id 重复

**C · 复用时会打架 (11 条)** —— slide 复用品质
- `R05` emoji / `!` / `...` 等违禁标点
- `R10` 调色板飘移
- `R12` 真 drop-shadow
- `R13` 标题 `<br>` 强换行
- `R20` 字号 off-tier
- `R47` variant 改结构没重声明对齐
- `R48` 多卡片版式没默认居中
- `R49` cyan 当主色调
- `R56` 内容页 header 有 eyebrow
- `R-HIERARCHY` 次要字段比主要醒目
- `L1` logo 配色错

#### 与入库无关 (10 条, gate 模式直接屏蔽)

`T00` · `T03` · `R-FEEDBACK` · `UI1` · `P50` · `P51-P55` · `R29-32` · `R36` · `R-LANG` (单条 title-en warn)

这 10 条要么是生成流程产物 (texts.md / FEEDBACK.md), 要么是交付格式选择
(inline vs linked / Replica vs Rewrite), 要么是浏览器性能预算 —— 都跟
slide-library 入库后能否被检索 / 复用 / 追溯无关.

#### 修改业务文案

改 `business-rules.yaml` 即可. 加新规则时同步加 entry:

```yaml
R-NEW-RULE:
  concern:     "A · 客户看不见"     # 三选一: A / B / C
  symptom:     "一句话业务症状"
  consequence: "不修后果, 客户/库视角"
  fix:
    - "动作动词开头的修改步骤"
    - "具体到 px / 颜色 / 措辞"
```

不用动 .py 代码; check-only 启动时动态加载. 加完之后跑下
`python3 -c "import yaml; yaml.safe_load(open('business-rules.yaml'))"`
验证语法.

### Deliverable to the user (check-only)

In check-only mode the only thing you produce is the markdown report.
Either dump it in the chat (default) or write to a file the user names.

**Do NOT**:
- create `runs/<ts>/` work folders
- run `new-run.sh` / `preflight.sh`
- call `copy-assets.py` / `extract-texts.py` / `package-deliverable.sh`
- modify the input HTML in any way
- offer to "fix" issues automatically — leave that as a follow-up the user
  can ask for separately (and which routes them into GENERATION mode on
  the same deck)

**Do**:
- name the report shape ("✗ N errors / ! M warns, FAIL/PASS") in the
  first sentence so the user sees the verdict before scrolling
- if errors are concentrated in one family (e.g. 6 of 8 errors are R20
  type-ladder violations), call that out explicitly so the user knows
  where to focus the fix
- when the heuristic flags Replica-mode / external-deck context, mention
  it so the user knows to ignore the corresponding context-dependent rules

### Rule families summary (for explaining the report)

| Family | Codes | What it audits |
|---|---|---|
| 结构 / DOM | R02 / R07 / R-DOM | every `.slide` has `data-layout` + `data-screen-label` + `.wordmark`; balanced `<div>` tree |
| 排版 / 文案 | R05 / R06 / R13 / R20 / R56 / R-WHITE-TEXT / R-HIERARCHY | banned punctuation; 24/16 floor; no `<br>` in titles; 4-tier ladder; header-minimal; #fff body text |
| 品牌 / 调色板 | L1 / R10 / R12 / R38 / R49 / R-LANG | color logo default; brand hex only; no real drop shadows; valid `data-decor` tokens; no cyan as accent; zh-only meta enforcement |
| 布局完整性 | L2 / L4 / R36 / R47 / R48 | balanced stage / single-col attrs / present-mode centering / variant alignment redeclare / default centering |
| UI 仿真 / slide-key | UI1 / R-KEY | system UI rebuilt as `.ui-*` HTML primitives (not `<img>`); every `.slide` has semantic `data-slide-key` |
| 演示模式 / 运行时 | R29-32 | `.deck-progress`, `.deck-controls`, prev/next/fs buttons, `requestFullscreen`, `fullscreenchange`, idle fade |
| texts.md 联动 | T00 / T01 / T02 / T03 | data-text-id present; valid `slide-NN.field` shape; unique; paired `texts.md` synced |
| 性能预算 | P50-P55 | base64 budget; blur radius; single ResizeObserver; AbortController; GPU layers |
| 视觉 (Playwright, default-on since 2026-05-18) | R-OVERFLOW / R-OVERLAP / R-VIS-TIER / R-VIS-HIER / R-VIS-LABEL-FLOOR / R-VIS-BODY-FLOOR / R-VIS-ALIGN / **R-VIS-ABSPOS-DUAL-ANCHOR** / **R-VIS-ORPHAN** | canvas overflow; **sibling bbox overlap** (catches "column bleeds into legend" — internal overlap within canvas); computed `fontSize` on ladder; meta ≤ body; **renderer-aware body-content < 24 px detection** (R-VIS-BODY-FLOOR · 2026-05-19 · catches ambiguous short class names like `.rt` / `.d` / `.ind-tag` that pass static R20/R06 because 16 is on the ladder and short class names match neither chrome nor body heuristic — checks actual rendered fontSize + ≥ 8 chars of direct text + not inside mockup containers; opt out per element with `data-allow-body-floor`); grid-children equal height; **dual-anchor pill stretch** (R-VIS-ABSPOS-DUAL-ANCHOR · 2026-05-23 · catches the cascade footgun where an override declares `top:` on a `position: absolute` chrome element without resetting an inherited `bottom:`, so the pill / badge / hint stretches to most of the parent height — see BF14 below; mutation-tests every absolutely-positioned non-layout-container element by temporarily setting `style.bottom = 'auto'` and checking if height collapses; layout shells like `.stage / .stack / .iframe-wrap / .panel` are excluded by class denylist; opt-out per element with `data-allow-dual-anchor`); **CJK orphan / 上长下短 wrap** (R-VIS-ORPHAN · 2026-05-25 · WARN · CJK leaf text wrapping to a lonely ~1-char last line, or a short ≤14-CJK label whose last line < 38% of the widest — the residue `text-wrap: balance` can't fix in fixed-width / `<br>`-broken containers; skips block-child sub-labels / SVG / mockup / nowrap; deck slides only, not iframe prototypes — see "CJK 换行平衡 / 末行孤字防治"). ~2 s overhead. Use `--no-visual` to skip (CI without Chromium); gracefully skips if playwright is not installed |
| 交付物附件 | R-FEEDBACK | `FEEDBACK.md` sidecar present (relevant ONLY for new-run flow) |

When the user asks "what does [Rxx] mean", look up the rule in `validate.py`
(grep for the code) — every audit function has a docstring + the error message
explains the fix.

---

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
# 14 subcommands total — see deck-json/DECK-CLI-README.md

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
| `deck-json/deck-cli.py` | 14 atomic ops on deck.json (set / set-accent / set-decor / set-variant / reorder / move-key / insert / delete / clone / render / list / get / show / lint) — auto-backup + revalidate + rollback | `deck-json/DECK-CLI-README.md` |
| `deck-json/validate-deck.py` | Standalone schema lint of deck.json (called by render-deck.py + deck-cli.py automatically) | inline help |
| `deck-json/sync-index-to-deck.py` | **Detect + recover post-render drift** — port edits made directly to index.html back into deck.json so re-render is byte-identical. Run before any fork / library ingest / delivery. | see ROUND-TRIP INTEGRITY section |
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

> **本节是 `DESIGN PHASE` Step 2 的细节**(per-page 设计预检 + Q0–Q4 + 六维 +
> Decision rule)。编排、默认值、确认门规则在 `DESIGN PHASE` 那一节;这里讲
> "每页具体怎么想"。确认门**按风险触发**(全 schema 宣告即走;有 `layout: raw`
> / bespoke / 重度补全的页才停下确认),不再是无条件"必须等确认"。

When the user hands you **a text brief** (一串提示词 / 文案 / Q&A 大纲 /
sections 描述 / 主题列表),**do NOT immediately create files**. First
produce a per-page design plan in chat (DESIGN PHASE Step 1–3), THEN —
若有 beyond-default 页则等确认、否则宣告即走 — generate.

### 设计前预检 · 5 个问题(MANDATORY · 每张新 slide / per-page polish)

**触发条件**:任何即将生成 HTML 的新单页 + 任何用户给文案让你重做的页。

**强制规则**:**必须在 chat 里 EXPLICIT 写出 Q0-Q4 答案 + A 档 6 维 spec
+ design intent statement,再调用任何 Write / Edit 工具**。「在脑子里
跑过了」不算。用户看不见你脑子里的思考。

**当 prompt 信息不足以填完 Q0-Q4 时,你 MUST STOP**:用问句形式
把空缺字段返还给用户,等用户回答再开工。**不要自己脑补答案**,因为
脑补的会跟用户真实意图错位(slide 9 冰红茶就这么发生的)。

#### 反模式 — 看到立刻拍醒

| 用户 prompt | ❌ 错误响应 | ✓ 正确响应 |
|---|---|---|
| 「做一页 AI 重写消费品增长」(8 字标题) | 立刻 `Write` deck.json 加 slide | 先在 chat 输出: "这页的**角色**是?(现象/方法论/结论/对比/证据) **唯一要记住的具体一句话**是?**A 档元素**应该是什么?气质上是冷调科技还是暖调编辑?" 等用户回答再 generate |
| 「加一页关于客户案例」(8 字) | 直接套 `content/story-case` schema | 先问: "案例是单客户(用 story-case)还是多客户矩阵(用 logo-wall + 案例)?痛冲解价值结构齐吗?有客户原话还是只有数据?" |
| 「再做一页」(纯指令) | 沿着上一页 layout 复制 | 先问: "这页角色?跟前一页(方法论)什么关系?接续 / 转折 / 收束?" |

#### 触发判定

**判定 "prompt 信息足够"** —— 满足以下**至少 3 个**:

- ✓ 用户写明了**页面角色**关键词(现象/方法论/结论/对比/证据 之一,
  或同义词如"展示/讲解/收束/对比/数据支撑")
- ✓ 用户写明了**这页要记住的具体内容**(slogan/数字/案例名/产品名等
  具体的东西,不是抽象概念)
- ✓ 用户列出了**至少 2-3 个具体元素**(列表项 / 卡片 / 数字 / 图标 等)
- ✓ 用户暗示了**视觉气质**(科技/编辑/怀旧/工业/极简 等关键词)
- ✓ 用户给了**参考样式**(URL / 截图 / 类比 "做成 BCG 报告风")

**只满足 ≤ 2 项 = 信息不足 = 必须问问题再动手**。

漏跑这 5 题的真实代价(2026-05-22 复盘 · slide 9 冰红茶 5 剧本墙):
prompt 明写「现象呈现页 · 不下结论 · 话术是视觉焦点字号最大 · 引号视觉化」
—— 我跳过预检,直接套了"通用 3 卡 + 锚定 banner"(=方法论页骨架),
slogan 做成 28(Sub tier) 跟场景名同档不是"最大",引号 48 不是"视觉化"。
prompt 字面 4 条要求,**1 条都没真做到**。根因:没跑 Q0-Q4 就动手。

**这个反模式的根因不是用户 prompt 太短,是我自己跳过预检**。即使
prompt 给得很详细(slide 9 那个 prompt 信息绝对足够),不在 chat 里
explicit 跑 Q0-Q4,我还是会用熟悉的模板套上去。**强制 explicit chat
输出是唯一防线**。

#### Q0. 这页是什么角色?

5 选 1:

| 角色 | 视觉处理 | 反模式 |
|---|---|---|
| **现象呈现页** — 信号墙 / 剧本墙 / 案例矩阵 | 等权并列,不下结论 | 加锚定 banner / 加收束金句 / 强行 3up |
| **方法论页** — 步骤 / 框架 / 原则 | 顺序+依赖,流程感 | 等权并列没顺序 / 没收束 |
| **结论页** — 一句话收束 | 单 hero 句,记忆锚点 | 信息密度高,稀释结论 |
| **对比页** — 痛 vs 解 / 旧 vs 新 | 2 列 + 中线 + 视觉重量差 | 3 列均权 / 没视觉对位 |
| **证据页** — 数据 / 案例 / 引文 | 数字为主 + attribution | 抽象论述 / 无具体数据源 |

**错读角色 = layout 全错**。现象页做成方法论页 = 锚定 banner 抢了剧本墙
的戏 = 整页变 PPT 三段论。

#### Q1. 这页最该被记住的唯一一件事是什么?

**只准选 1 个**,不准选 2 个并列。写出来必须是 1 句具体话:

> "我希望观众离开这页时记住 [X]"

X 必须是**具体内容**(slogan / 数字 / 案例名),**不是抽象概念**:
- ✓ "撸串没冰红茶等于火锅没毛肚" — 具体话术
- ✓ "2 小时完成 335 人调研" — 具体数字
- ✗ "3 个痛点" — 抽象,记不住
- ✗ "AI 重构消费品逻辑" — 抽象口号

错读 Q1 = "每个东西都同等重要" = 全均匀 = 没重点 = 灰泥。

#### Q2. 把所有元素分 A/B/C/D 四档 + 强制 6 维 specification

| 档 | 角色 | 数量 |
|---|---|---|
| **A** | 必赢 · 视觉最大 | **唯一** |
| **B** | 辅助焦点 | 2-3 个 |
| **C** | 解释信息 | 视情况 |
| **D** | 注脚 | 视情况 |

**A 一定就是 Q1 答案的载体**。

**仅写「A 档 = slogan」是不够的** —— 这是断点。Q2 之前我写到这里就停,
然后让 4-tier ladder 自动决定字号 → slogan 跟其他元素同档 → A 档没赢。

**Q2 必须为每档输出 6 维 specification,不允许跳过任何一维**:

```
A 档 [元素名]
├─ 字号 ____  (具体 px;允许 off-ladder + /* allow:typescale */)
├─ 容器层级 ____  (1 级页 / 2 级卡 / 3 级浅 zone / 独立 box)
├─ 装饰 ____  (装饰字符 / 大圆角 / 阴影 / 边框 / 渐变 / 无)
├─ 对齐 ____  (左 / 中 / 右)
├─ 字距 ____  (具体 em 值,默认 normal;tight tracking ≤ -0.04em)
└─ 字重 ____  (400 / 500 / 600 / 700 / 800 / 900)

B 档 [...] (同上 6 维)
C 档 [...] (同上 6 维)
D 档 [...] (同上 6 维)
```

**为什么 6 维强制**:

vocab 库(知道哪些 move 可用)需要 5-10 个不同主题的设计积累,**1 个
样本写不出来**(写出来就是 lock 死在那一种气质)。但**思考维度可以
现在固定**:任何 element 处理,**至少这 6 件事都要想过**。

不规定值,**强制必须填**。第一次跑可能填得很烂(没经验),但 explicit
写出来,用户能 review,迭代后能积累成真 vocab。

**反模式 — Q2 断点的具体形态**:

- ❌ "A 档 = slogan" + 5 维全空 → ladder 自动填 28 → 没赢
- ❌ "A 档 = slogan,字号 44" + 容器/装饰/对齐/字距/字重 全空 → 字大了但视觉无重量
- ❌ "B 档 = 场景名,字号 28" + 其余全空 → 跟 A 档 28 同档,A 档没赢
- ❌ 6 维填了但**没跟 Q4 内容气质对齐** → 上了冷调装饰跟主题不搭

**正例 — slide 9 重做版应该这样写**:

```
A 档 = slogon (5 句话术)
├─ 字号:44 (off-ladder · prompt 要求字号最大 · documented intent)
├─ 容器:3 级浅 zone (页 → 卡 → 浅 zone) · 圆角 18
├─ 装饰:80 serif 双引号(左上+右下绝对定位 · 品牌色 0.45 透)
├─ 对齐:中央
├─ 字距:-0.015em (tight tracking 增 editorial 感)
└─ 字重:900

B 档 = 场景名 + 头像 + 图标
├─ 场景名 28 · 2 级卡内 · 顶部 tiny-caps eyebrow "剧本 01" · 左对齐 · -0.01em · 700
├─ 头像 64 · 圆角 14 · 位置:卡顶右 · 品牌色 0.45 透 border · normal · -
└─ 图标 40 · 圆角 14 · 位置:卡顶左 · 1px 白透 border · - · -

C 档 = 人群标签 / 产品规格
├─ 字号 16 · 容器 spec 用圆角 pill 边框, demo 文本无容器
├─ tiny-caps eyebrow 上方("人群标签" / "产品规格")· 0.20em tracking
├─ 字重 500 · normal tracking · 左对齐

D 档 = 内容载体
├─ 字号 16 · 卡底 · 上方虚线 hairline 分隔
├─ 颜色 #fff 透 55% · italic · 左对齐 · normal · 500
```

每行 explicit · 总共 5-6 行 spec · 看完就知道每个元素长什么样。

#### Q3. 我现在准备做黑白框架,还是直接上风格?

**正确顺序**:
1. 黑白框架 — 只看大小 / 位置 / 比例 / 是否成立(无色 / 无品牌色 / 无渐变)
2. 风格 — 上色 / 字体 / 边框 / 阴影 / 渐变

**直接上风格的后果**:`feishu skill 默认 = 深色 + 品牌冷调 + 4-tier ladder`
变成隐形 KPI,prompt 意图被压在底层。我会先做风格再硬塞内容进去 ——
反向工程。

**眯眼测试(必跑)**:把黑白框架缩小到 1/3,眯眼看:
- 重点还成立吗?
- 5 列是不是均权(而不是某列突然轻 / 重)?
- 标题 / 卡片 / A 档元素之间形成节奏了吗?

眯眼看不出层次 = 框架没成立 = 上色也救不了。

#### Q4. 内容自己长出来的气质,跟 feishu skill 默认冲突吗?

| 内容气质 | 自然长出的 palette | feishu skill 默认 | 冲突? |
|---|---|---|---|
| 高科技 / AI 协同 / 数据指标 | 深蓝 / 青色 / 几何 | 深蓝 + 品牌冷调 | ✓ 一致 |
| 客户故事 / 案例 / 编辑感 | 米白 / 纸感 / 编辑灰 | 深蓝 | ✗ 冲突 |
| 食饮 / 怀旧 / 烟火气 | 茶色 / 琥珀 / 砖红 / 纸张 | 深蓝 + brand color | ✗ 强冲突 |
| 节庆 / 文化 / 传统 | 中国红 / 墨黑 / 金 | 深蓝 | ✗ 冲突 |

**冲突时怎么办**:
- feishu skill 标准是**约束底线**(不准 cyan / 不准 drop shadow /
  R10 brand hex / R12 / R13 / R56 等)
- skill 默认的**配色 / 字体 / 渐变模式**是"出厂建议",不是强制起点
- 内容气质优先 —— 即使 break ladder 或做 documented palette
  exception,也比出图跟内容气质不搭好
- 设计方案 chat 里 explicit 标:"⚠️ 这页内容气质要 [X],
  跟 skill 默认 [Y] 冲突;打算 [打破 ladder / 用自定义 palette /
  接受 R-VIS-TIER 报告 / 加 documented exception]"

#### 通过 5 问的标志:写出 1 句 design intent statement

跑完这 5 题应该能写出:

> "这页是 [现象呈现页],唯一重点是 [5 句话术,让观众自己得出结论],
>  A 档元素是 [slogan,44 hero + 80 装饰引号],
>  气质上要 [editorial 杂志感],
>  跟 skill 默认 [深蓝 + cool palette + 4-tier ladder 上限 48] 冲突,
>  处理:[slogan 字号 off-ladder 到 44,引号 off-ladder 到 80,
>  接受 R-VIS-TIER 报告作 documented intent;但保 skill 必守的
>  R10 / R12 / R13 等约束底线]"

**写不出这句话 = Q0-Q4 没答清 = 不要动手。**

#### 实操:把 5 问写进 design pass table

老版 design pass table 只列 layout 选型,加 1 列 "design intent" 写出 Q0-Q4
关键判断:

| # | 页 | 角色(Q0) | 唯一重点(Q1) | A 档元素(Q2) | 气质冲突?(Q4) | Layout |
|---|---|---|---|---|---|---|
| P0 | 冰红茶 5 剧本墙 | 现象页 | 5 句 slogan | slogan 44 + 引号 80 | ✗ 冲突 → 接受 R-VIS-TIER 作 documented intent | raw + content-3up base |

用户看到 "现象页 + 5 句 slogan 是 A 档"就立刻明白方案对不对,比看 layout
名更准。

### Validator 报告响应纪律 · opt-out attribute 不是 silence button

跑 `--visual` 之后 validator 会喊 R-VIS-BODY-FLOOR / R-VIS-TIER /
R-WHITE-TEXT 等。**每条警告都给 3 个选项**,典型形态:

> ✗ R-VIS-BODY-FLOOR · 16px 字太小
> · **Bump to 24 (preferred)**
> · OR rename to chrome class (.eyebrow / .footnote / .source / ...)
> · OR set `data-allow-body-floor` for documented exception

**默认必须选 Bump**。opt-out 是少数路径,仅在元素**真是 by-design 小字**
(axis-label / legend / status-chip / chrome metadata) 时用,**不是**
"warn 太多了批量哑掉"的方便键。

#### 三大 opt-out 的合法 vs 滥用场景

| Opt-out | 合法场景 | 滥用反模式 |
|---|---|---|
| `data-allow-body-floor` | Axis tick label / sparkline 数值 / status pill (在线/离线) / unit suffix | 整张卡片所有 li / desc 批量挂 → 静默承认字太小 |
| `/* allow:typescale */` | Cover hero title / section chapter-num / big-stat 数字 / 一次性装饰字符(80+ serif quote) | 每个 28-44 px 标题都挂 → 让 ladder 失效 |
| `/* allow:white-opacity */` | Subtle backdrop / decorative dim text / 真 chrome metadata | 整页 body 内容都用半透白 → 整页"褪色"感 |

#### 反模式识别:统计学触发器

**单张 slide 同一种 opt-out 出现 ≥ 5 次 = 几乎一定是 silence 反模式**,
不是 documented intent。Documented exception 应该是 1-3 处,精确定位
到真正的 by-design 元素。批量挂 = 在用 opt-out 做 mass-mute。

2026-05-22 复盘实例(slide 10 content-pipeline):

- validator 喊 10+ 条 16px R-VIS-BODY-FLOOR(li / track-body / proc-sub /
  proc-output / r-name / hi-desc 等)
- **我选了批量加 `data-allow-body-floor="diagram"`**,silence 12 个元素
- 用户视觉看:"方框里字普遍偏小,显得方框很空"
- **validator 全做对了 — 是我用 opt-out 哑了正确的警告**
- 修法:撤掉错加的 opt-out,真 body 内容 bump 16 → 24,只保留真 chrome
  (流 01 / 4R Strategy eyebrow / R1-R4 tag / 轨道 A/B badge / infra tag)

#### 实操规则

在 chat 里加 opt-out 之前,必须能回答:

> "这个元素 [name] 我打算挂 [opt-out 名]。它是 documented [chrome /
> by-design small / legend / axis / 装饰字符],因为 [具体设计理由,
> 不是'字号方便']。"

写不出 "因为"，就 bump 字号 / 选其他 fix,不要挂 opt-out。

#### 长期 framework 改进(TODO)

`R-VIS-OPT-OUT-ABUSE` 新审计 — 当单张 slide 上同种 opt-out attribute
出现次数 > 阈值(建议 5)时报 warn,强迫作者写 design justification
或减少 opt-out 数量。这是把"opt-out 必须是 documented intent"从
软约定升级为硬检查的下一步。

### Component utility classes (mandatory · framework 自带,不要自己复刻)

写 raw layout / 自定义 slide 时,**写一行 CSS 之前先查 framework 有没有
现成 component class**。Ad-hoc 重写不仅是冗余代码,而是**反 framework
化** —— skill 的标准化收益被消耗掉,validator 也会漏掉 lint。

| Pattern | 用 framework class | 不要 ad-hoc 写 |
|---|---|---|
| 列表项前面带 bullet | `<ul class="feature-list">` + `<li>...</li>` | ❌ `li::before { content:""; width:8px; height:1.5px; background:rgba(...) }` 自画横线 |
| icon + 大字标 + 小字描述 横排 tile | `<div class="fs-claim-row is-teal"><span class="fs-claim-row__icon">✓</span><div class="fs-claim-row__text"><span class="fs-claim-row__label">...</span><span class="fs-claim-row__desc">...</span></div></div>` | ❌ `<div class="hi"><span class="icon">...</span><span class="text"><span class="label">...</span><span class="desc">...</span></span></div>` 自起类名 |
| 强调短语 inline | `<span class="hl">关键词</span>`(框架 var --fs-cyan + 文本-黄/teal) | ❌ `<span style="color:#xxx">...</span>` |
| 数字 hero | `big-stat` schema layout · 或 `<div class="hero-num">42</div>` | ❌ 写自己的 `font-size:120px` raw |
| KPI 行 4 列 | `stats/row` schema layout | ❌ 4-col flex 自己写 |
| 客户 logo wall | `logo-wall` schema layout | ❌ 自己 grid logos |
| 引用文 + 引号装饰 | `quote` schema layout | ❌ 自己写 `<span class="quote-glyph">"</span>` |

每个 utility class 都已包含:
- 4-tier ladder 字号(`.fs-claim-row__label` 24 / `__desc` 20 already on ladder)
- R10 brand palette tokens (`--fs-blue/teal/violet/purple/orange`)
- R-WHITE-TEXT-safe color choices (solid hex 不靠 opacity 调灰)
- R-VIS-LABEL-FLOOR-safe sizing
- Master 行高 / letter-spacing / 字重

**当你发现 framework 没有现成 component**(罕见):
1. 不要 inline 写 ad-hoc — 写到 framework `feishu-deck.css` 里作为新
   utility class
2. 命名 `.fs-<pattern>` 表明它是 framework 提供
3. 加注释 + 用法 example 写在 utility 定义上方
4. 更新这张表 + 改 SKILL.md 这一节
5. 触发条件:同样 pattern 在 2 个以上 deck 出现 → 该上 framework

**反模式信号**:看到自己写的 CSS 里有
- `.highlight` / `.callout` / `.kpi-tile` / `.hi` / `.fact-row` 等 ad-hoc
  类名 → 几乎一定是该用 framework component 没用
- `<ul>` 没 `class="feature-list"` → 几乎一定该加
- `<span style="color:#XXX">` 真品牌色 inline → 该用 `.hl` 类

### Why design-first

`feishu-deck-h5` 有 14 个 schema layouts + raw 逃生口。layout 选错的代价高:

- 强行套标准 layout → 主问题被塞进 `.header .title-zh` 被 `white-space: nowrap`
  单行截断 / 内容溢出 1080 / 留白尴尬
- 默认全自定义 → 失去 schema 的 R20 / R06 / R-WHITE-TEXT 等防护,Path B 易踩坑
- 用户 review 时 layout 选错要改一整页 = 改 CSS + DOM,比设计阶段 3 分钟
  对齐贵 10 倍

围炉夜话 Q&A 是个正面例子:design pass 阶段就识别"主问题需多行 + 原声列表"
不在 schema 内,直接走自定义 `.qa-page`,避开 `.header h2.title-zh` 单行陷阱。
反例是博裕&星巴克的第一次跑:silent 把 54 页压成 17 页,因为没设计阶段对齐
"页数保持 1:1"。

### When this applies (默认 ON)

- 用户给 text brief / 主题列表 / Q&A 文案 / outline 描述
- 用户说"做一份 deck about X" / "把这些做成 deck" / "围绕 X 主题做一个分享材料"
- 用户描述了内容但没说视觉结构

### When to skip (直接走生成流程)

- 用户明说 "直接出 / 不用问设计 / 别问了就生成"
- 用户给 PDF / PPT 让 Replica / Rewrite / per-page polish — 那些路径有自己的
  conversion rules,设计在那里发生
- One-pager case (4-beat 痛/冲/解/价值 是固定结构)
- 用户在前文已经明确给出了 layout 选择
- 用户在迭代已有 deck 的某一页(per-page polish 模式)

### Design pass output — markdown table in chat

| # | 页 / 主题 | 角色 | Layout / path | hero? | 为什么 |
|---|---|---|---|---|---|
| P0 | 封面 | 结论 | `cover`(Path A) | — | 主标题 + 发起人 + 日期,master 封面 |
| P1 | 客户三个核心痛点 | 现象 | `content/3up`(Path A) | — | 3 个并列点,schema 正合适 |
| P2 | 客户原话 | 证据 | `quote`(Path A) | — | 单句引语 |
| P3 | 那一个大论点 | 结论 | `layout: raw` · 双手架构 pattern | ★ | 全 deck 高光,schema 表达不了;翻词汇库选了 two-hand-arch |
| P4 | Q&A 大问题 + 原声列表 | 现象 | `layout: raw` · `.qa-page` | — | 主问题需多行,schema 无匹配 |

每行必须给:
- **角色**: Q0 五选一(现象 / 方法论 / 结论 / 对比 / 证据)
- **Layout / path**: Path A 写具体 schema 名;hero/bespoke 写 `layout: raw` +
  **从词汇库选定的 pattern 名**(scan `narrative patterns A–N` +
  `component utility classes`,优先复用现成 pattern,别从零硬写)
- **hero?**: 标 ★ 的页才全开 bespoke + 必填 Q0–Q4 六维;通常 2–3 张
- **为什么**: 1 句话依据(为什么这个 layout fit / 为什么必须 bespoke)

> hero 页(★)在表下方各补一句话 design intent statement(见"通过 5 问的标志"),
> 并把 Q0–Q4 + 六维写进 DESIGN-PLAN.md。

### Decision rule — "标准 layout 优先" 判断逻辑

按下表逐页判定。**第一个匹配的就是该页 layout**,不要往下找。

| 内容形态 | 用 | 标准 fit 的理由 |
|---|---|---|
| 单标题 + 发起人 + 日期 | `cover` | Master 封面 |
| 3-8 章节项的目录 | `agenda` | Pill stack |
| 大章节号 + 章节标题 | `section` | Chapter divider |
| **3 个并列要点**(title + 2-3 行 body) | `content/3up` | 最常见 content shape |
| 1 个 narrative + 1 个 visual | `content/2col` | 文 + 图 |
| 4 拍叙事(痛/冲突/解/价值)单客户 | `content/story-case` | One-pager 标准 |
| 4 个 KPI 数字横排 | `stats/row` | KPI dashboard |
| 1 个 hero 数字 + 解释 | `stats/hero` 或 `big-stat` | 大数字 |
| 1 句客户原话 + attribution | `quote` | 单句证言 |
| 全幅照片 + 角落文字 | `image-text` | Cinematic |
| 2-6 行 × 2-5 列对比矩阵 | `table` | Comparison |
| 时间轴 4-6 节点 | `flow/timeline` | Chronological |
| 3-6 顺序流程步骤 | `flow/process` | Sequential |
| 客户 logo 矩阵 | `logo-wall` | N × M 网格 |
| 2-5 层架构(应用 / 平台 / AI / 数据) | `arch-stack` | Tech stack |
| 结尾 slogan / 联系方式 | `end` | Master 封底 |
| Designer-polished PDF 页保真 | `replica` | 整页贴图 |
| **以上都不匹配** | 想想 → 还是不匹配 → **自定义** | 见下 |

### 什么时候自定义 IS the right call

自定义(Path B / `layout: raw`)**仅限**以下场景,设计 pass 中必须 explicit 标出:

1. **schema-shape 结构性不匹配** — e.g. Q&A 页(大问题多行 + 原声列表);标准
   `content-2col` 强制主问题进 `.header .title-zh` 被单行截断
2. **schema 里没有但又是 recurring narrative-pattern** — two-hand-arch /
   Iron 4-corners / 6-step pipeline — schema 没原生 DSL,但 CSS 已经有,
   走 `raw` 块复用 CSS
3. **用户明确给了 schema 无法表达的结构** — "6-beat case" / 竖版手机端 /
   "case 没有冲突,只有 3 个发现"

### Anti-patterns — DO NOT 自定义 for these

- ❌ "想标题 18 px 不要 24" — R20 drift,不是 schema 不够;snap 回 ladder
- ❌ "schema 有 3up 但我想 4 个 card" — `content/blocks` 自由 grid 也是标准
- ❌ "看着 schema 我没把握选哪个" — 看 deck-json/MIGRATION-REPORT.md
   Phase 0.2 的 4-proposal 评估流程,不要直接 raw
- ❌ "想给每页换不同 accent 颜色" — `data-accent` 属性,不是 layout 改

### Design pass 收尾 — 确认门按风险触发

设计方案 table 输出后,看方案里有没有 **beyond-default 页**(`layout: raw` /
bespoke hero / 超出用户给定材料的重度补全):

- **有 → 停下等确认**。把那几页的 spec(Q0–Q4 + 六维 + 选定 pattern)逐项摆出,
  end with:
  > 这几张高光页(P_x / P_y)我按上面的设计来,确认?其余 schema 页我直接出。
- **没有(全 schema)→ 宣告即走**,不强制停:
  > 方案如上(全用标准 layout),我开工了;有要改的随时说。

无论哪种,**真正开始写文件前不要 pre-emptively 跑 PREFLIGHT**;按
`DESIGN PHASE` 的顺序:确认/宣告 → PREFLIGHT → new-run → **落 `DESIGN-PLAN.md`**
→ 生成。

方案一旦 lock,生成时直接照走,**不需要再问一遍**。生成后发现某页 layout
设计错了,先跟用户对齐切换(走 SLIDE DELETION POLICY 的双确认 + 备份规则),
不要静悄悄改设计;偏离 DESIGN-PLAN.md 也先回来改 plan。

---

## WORKSPACE LAYOUT (mandatory) — per-run `runs/<timestamp>/` folder

After PREFLIGHT passes, but **before generating any HTML**, the agent
MUST create a fresh per-run workspace and announce it to the user.
This is a non-negotiable convention so that:

- multiple deck attempts in the same project don't overwrite each other
- the user's source materials and the agent's outputs stay separated
- every run is timestamped and easy to find / archive / git-commit later

### Required structure

`runs/` lives at the **repo root**, NOT inside `skills/<skill-name>/`.
This avoids the common-case path bloat for a single-skill marketplace
repo: users see `<repo>/runs/<ts>/output/index.html`, not the deeper
`<repo>/skills/feishu-deck-h5/runs/<ts>/output/index.html`. `new-run.sh`
resolves "repo root" via `git rev-parse --show-toplevel` and falls back
to skill root only when the skill isn't inside a git tree.

```
<repo-root>/
├── README.md, INSTALL.md, install.sh, …   ← repo-level docs
├── runs/                                   ← ★ user artifacts live here
│   └── YYYYMMDD-HHMMSS/                    ← one folder per skill invocation
│       ├── input/                          ← USER drops source files here
│       └── output/                         ← AGENT writes the deck + validate reports here
└── skills/feishu-deck-h5/                  ← skill source (don't write outputs here)
    ├── SKILL.md, assets/, templates/, examples/, …
    └── (no runs/ subfolder — runs are at repo root)
```

The deck's CSS / JS link in `runs/<ts>/output/index.html` points at the
skill's assets via a relative path:

```html
<link rel="stylesheet" href="../../../skills/feishu-deck-h5/assets/feishu-deck.css">
<script src="../../../skills/feishu-deck-h5/assets/feishu-deck.js"></script>
```

(Three `../` to climb from `output/` to repo root, then down into the
skill folder.)

### Required steps (run IN ORDER, after PREFLIGHT)

**Step W-1.** Ask the user for the **topic / customer name** before creating
the run folder. The slug will be embedded in the folder name so the user
can find this run a week later by `ls runs/ | grep luckin` instead of
guessing the timestamp. Pass it as the second argument to `new-run.sh`:

```bash
bash assets/new-run.sh <slug>
# produces: runs/<YYYYMMDD-HHMMSS>-<slug>/
```

**Slug derivation rules** (the agent derives this from the user's natural
answer — don't make them type kebab-case themselves):

- **Customer / portfolio company** → pinyin or English short name in
  kebab-case: `luckin` / `boyu-starbucks` / `mixue` / `meiyijia`
- **Internal theme / weekly review / keynote** → short English/pinyin tag:
  `q2-okr-review` / `digital-employee-guide` / `sales-enablement`
- **Multiple customers in one deck** → chain longest-first by recognition:
  `boyu-starbucks` not `starbucks-boyu`
- **Length cap** ~25 chars; truncate if longer
- **NEVER use Chinese characters** in the slug (URLs, scp, IM previews,
  some `git log` viewers all break on CJK in paths)
- **NEVER skip the slug** — if the user genuinely refuses to name the
  deck (rare), fall back to a content-shape slug (`one-pager`,
  `quarterly-review`, `customer-pitch`) rather than the bare timestamp

The script prints the absolute path of the new run folder and exits 0.
Capture the printed path; it is the working folder for everything below.

**Slug-only re-invocation** is fine — if the user comes back tomorrow and
says "继续做瑞幸那个 deck", grep `ls runs/ | grep luckin` to find it
rather than creating a new one (see "When NOT to create a new run folder"
below).

**Step W-2.** Announce the path to the user **in the same response**.
Use roughly this phrasing (translate to the user's language):

> "已为本次任务创建工作目录：
> `runs/<timestamp>-<slug>/`
> · 请把素材（图片、PDF、参考稿、文案等）放到 `input/`
> · 我会把生成的 HTML deck 和验证报告写到 `output/`
> 准备好后告诉我即可继续。"

**Step W-3.** Wait for the user to drop files into `input/` (or to
confirm there are no source files — text-only briefs are fine, the
folder still exists for the deck to land in `output/`).

**Step W-4.** All subsequent file writes for this invocation MUST go
under `runs/<timestamp>-<slug>/output/`. Never write the deck to
`examples/`, the repo root, or any other location. `examples/` is
reserved for the maintainers' reference sample.

### When NOT to create a new run folder

- The user explicitly says "edit the existing deck at `runs/.../output/X.html`"
  — in that case, reuse that run folder, don't create a new one.
- You are running `build.sh` to regenerate `examples/sample-deck.html`
  as a maintainer of this skill (not as an end-user delivery). `build.sh`
  is intentionally hardcoded to `examples/` and is out of scope for this
  rule.

---

## SLIDE DELETION POLICY (mandatory) — double-confirm + backup before any net delete

Deleting a slide is **irreversible** without a backup. The deck is the user's
real work product — a 30-slide pitch reduced to 27 slides has lost 3 slides
of editorial decisions, content density, and visual rhythm that can't be
silently regenerated. Mistakes here are high-cost; the confirmation cost is
one IM line. The math always favors confirm-then-act.

### The rule

Before ANY operation that **net-removes** a slide from a deck:

1. **STOP.** Don't run the deletion yet.
2. **List what's being removed.** Show:
   - count of slides going away
   - each slide's `data-screen-label` (e.g. "07 工作台") + `data-slide-key`
     (e.g. `workbench-portal`) so the user can identify it without opening
     the file
   - 1-line "why" the agent is removing each one
3. **Ask for explicit confirmation.** Wait for the user to type back "yes
   delete" / "ok" / "go ahead" / equivalent. **Implicit consent does NOT
   count** — if the user said "trim the deck" earlier, that's not approval
   to delete a specific slide; surface the list and ask again.
4. **Once confirmed, offer a backup.** Default is to copy the deck file
   (and `texts.md` if present) to a `.bak-pre-delete-<YYYYMMDD-HHMMSS>`
   sibling beside the original. The user can decline ("no backup, just go")
   or pick a different option (git commit, separate folder, etc.). The
   agent's default phrasing:

   > "我备份到 `index.html.bak-pre-delete-20260518-160000`(就在 output/ 里)。
   > 同意?如果你想换地方或不要备份,告诉我。"

5. **Only THEN proceed.** Apply the deletion.

### What counts as a "net-removing operation"

| Operation | Triggers? | Notes |
|---|---|---|
| Removing a `.slide-frame` block from `index.html` via Edit | **Yes** | Even if "just one slide" |
| `rm` of the entire `output/` folder | **Yes** | Wholesale wipe |
| Re-rendering a `deck.json` with FEWER `content/story-case` (or any) slides than the current `index.html` has | **Yes** | Net delete via regen |
| Replacing N slides with M < N slides in one operation | **Yes** | Net-removed = N − M |
| Editing texts.md to drop a `## slide-NN` section, then running `apply-texts.py` | **Yes** | `apply-texts.py` itself only patches text leaves, but if the user's intent was "drop this slide", confirm + back up the HTML before applying |
| Inserting slides (M > N) | No | Pure addition is reversible by deleting back |
| Reordering slides (same N, same content) | No | But announce the new order before applying — separate "non-destructive change confirmation" |
| Editing a slide's content (title / cards / CSS / text-id values) | No | The slide still exists; content edits are routine |
| Replacing one slide with one different slide (1:1 swap) | **Yes** | The previous slide's content IS deleted; back it up |

When in doubt, treat the operation as a delete and ask. One IM ping is
cheap; rebuilding a slide from scratch is not.

### When the user has pre-authorized

If the user says EXACTLY "delete slide 7, no need to confirm" or "drop
slides 7-9 and back up to /tmp/foo, don't ask me again", the rule is
satisfied — they gave a specific instruction with both branches resolved.
Default-decline confirmations still require a list-then-act flow; the
"don't ask me again" only applies to THIS operation, not future
deletions in the same session.

### Why this rule is mandatory (and where it came from)

User feedback 2026-05-18: "如果需要删页的,一定要和我 2 次确认,然后给我
删除前备份选项". The agent was getting too comfortable executing slide-
removal operations without surfacing exactly what was being lost. Slide-
level deletion is in the same risk tier as `git push --force` or
`rm -rf` — destructive on shared, slow-to-reproduce work.

### Backup helper: `bak-and-log.sh` (recommended)

Use the shipped helper instead of hand-rolling `cp` + filename — it
backs up, logs the change to `CHANGES.md`, AND prunes old backups so
the output dir doesn't accumulate 50+ stale `.bak` files:

```bash
bash skills/feishu-deck-h5/assets/bak-and-log.sh \
    <file> <short-tag> "<one-line description>"
```

Example:

```bash
bash skills/feishu-deck-h5/assets/bak-and-log.sh \
    runs/<ts>/output/index.html delete-slide-7 \
    "Drop slide 7 (taste-shifts-3pains, redundant with slide 8)"
```

Effects:
- Creates `<file>.bak-pre-<tag>-<YYYYMMDD-HHMMSS>` (`.N` suffix if
  same-second collision)
- Prepends an entry to `<dir>/CHANGES.md` (creates if absent)
- Prunes `.bak-pre-<tag>-*` keeping only the **3 most recent** per
  (file, tag) pair — different tags get separate retention slots

Tags scope retention. Use one tag per edit class (`delete-slide-7`,
`iframe-fix`, `p20-rewrite`) so unrelated edits don't compete for the
3-slot quota.

For paired files (`index.html` + `texts.md`), run the helper TWICE
with the SAME tag and similar descriptions — both files get backed
up under the same retention slot, and both edits get one CHANGES.md
entry per call (consider consolidating description in the second
call: "(paired with index.html backup above)").

### Backup naming convention (legacy, prefer the helper above)

If you must hand-roll without the helper, follow the format the
helper produces so retention logic still recognises the files:

```
<file>.bak-pre-<short-tag>-<YYYYMMDD-HHMMSS>
```

Examples:
- `runs/.../output/index.html.bak-pre-delete-slide-7-20260518-160000`
- `runs/.../output/texts.md.bak-pre-delete-slide-7-20260518-160000`

Without the helper you don't get the CHANGES.md entry or pruning —
which is how the historical 53-bak pile-up happened. Use the helper.

---

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

## DELIVERY MODES — pick by harness

The skill produces files in `runs/<timestamp>/output/`. How those files
reach the human depends on which harness invoked the skill. Pick the
right delivery mode and call it out explicitly when handing off.

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

### 🔒 Delivery contract — NEVER hand back a single linked HTML file

This is a **hard rule, no exceptions**. Before any artifact crosses
the agent → user boundary (chat reply attachment, remote-codex
transport-back, harness "download to user" hook, manual file-pick),
verify the artifact form. Pick exactly **one** of three valid shapes:

| Shape | When | What goes back |
|---|---|---|
| **A · inline single-file HTML** *(default for "show me / 给客户看 / IM 转发 / 链接预览")* | The user just wants to OPEN and SEE the deck. 90% of cases. | `bash build.sh --inline` → ship `examples/sample-deck-inline.html` (or its renamed copy under `runs/<ts>/output/`). Single self-contained file, base64-inlined CSS/JS/images, ~360 KB. Double-click anywhere, works offline. |
| **B · zipped output folder** *(when the user needs to edit text)* | The user (or their downstream customer / sales / 大客户经理) needs to change copy without Claude in the loop. | `bash assets/package-deliverable.sh runs/<ts>/output/` → ship the resulting `deck-editable.zip`. Includes `index.html` + assets + `texts.md` + optional `deck.json` + `assets-manifest.yaml` + `apply-texts.py` + `apply.command`/`apply.bat` launchers. Recipient unzips, edits `texts.md`, double-clicks the launcher to regenerate. |
| **C · hosted URL** *(when the user already deploys to Pages / a CDN)* | Deck lives at a stable web URL. | Ship the URL string. No file attachment. |

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
to one of A/B/C. The author of the skill knows the convention; the
agent doing the hand-back must enforce it.

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
say "客户要改文字" / "我要自己改" / mention apply-texts.

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

# Library-ingest mode — skip shared/* (manifest still lists them)
python3 skills/feishu-deck-h5/assets/copy-assets.py runs/<ts>/output/ --shared=skip
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
  duplicated into `output/assets/shared/`. Use only when the destination tool
  doesn't follow symlinks (rsync without `-L`, archival snapshots, etc.) or
  when you explicitly need an on-disk copy independent of the skill.
- `--shared=skip` — leave `assets/shared/*` references skill-relative;
  don't copy or link those files. Saves ~50–500 KB per deck. Output runs only
  while next to the skill folder OR when a downstream tool (like the
  slide library ingest) rewrites the shared/* paths against its own
  pool. Use this when piping the run straight into the library.

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
- The HTML you drop into the slide-library inbox
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
delivering — the working `index.html` stays in place for further
edits, and the named copy goes out to the recipient.

### Mode 1 · Claude Code on the user's local machine

Default. The user has filesystem access to `runs/<timestamp>/output/`
already. Just tell them the path:

> 已生成：
> · `runs/<ts>/output/index.html` — 浏览器双击打开
> · `runs/<ts>/output/texts.md` — 改文字时编辑这个，然后跑
>   `python3 assets/apply-texts.py runs/<ts>/output/index.html runs/<ts>/output/texts.md`
> · `runs/<ts>/output/lark-<customer>-<YYYY-MM-DD>.html` — 命名规范副本，
>   投递 / 入库 / 同步公网就用这个名字（`finalize.sh --name lark-<...>` 自动产出）

No packaging step needed.

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
├── index.html        ← the deck (single inlined file, viewable offline)
├── texts.md          ← editable copy of every visible string
├── apply-texts.py    ← engine, stdlib-only Python 3
├── apply.command     ← macOS one-click launcher (double-click)
├── apply.bat         ← Windows one-click launcher
└── README.txt        ← user-facing instructions, including macOS Gatekeeper
                       and Windows Python install notes
```

Hand the zip to the harness for delivery. Typical bot flows:

- **Feishu bot**: send as file attachment via `im/v1/messages` with a
  one-line caption ("飞书风格 deck — 解压后双击 index.html 看，改文字看 README.txt").
  ~15-30 KB for the launchers/scripts plus whatever the deck weighs
  (typically 50-300 KB inlined).
- **OpenClaw remote**: return the zip path; OpenClaw's transport layer
  handles uploading or attaching it to the response.
- **Slack / email / etc.**: same — attach the zip.

The user does not need Claude Code, OpenClaw, or pip. Only stock
`python3` (default on macOS, one-time install on Windows).

### Mode 3 · View-only delivery (when editability isn't needed)

If the recipient is "客户/老板看一眼就行" and editing is not in scope,
ship just the inlined `index.html` (no zip, no texts.md, no scripts).
Use `build.sh --inline` to produce a fully self-contained single file.

This loses the texts.md edit loop — only choose it when you're certain
the recipient is consuming, not authoring.

### Choosing between Mode 2 and Mode 3

Default to **Mode 2 (zip with edit kit)** unless the user explicitly
says "this is the final version, no more edits" or "send to the
customer, just the visual." Most internal handoffs eventually need
copy tweaks; shipping the edit kit pre-empts a round-trip back to you.

---

## LANGUAGE POLICY — declared by `<meta>`, enforced by validator R-LANG

**Default = ZH-only.** Decks emit a single language line per visible
text leaf; no EN translation track underneath CN copy. The mode is
declared in `<head>` and enforced by `validate.py`:

```html
<meta name="fs-language" content="zh-only">   <!-- default -->
<meta name="fs-language" content="zh-en">     <!-- bilingual opt-in -->
```

`templates/_shell.html` already includes the zh-only meta. **Switch to
`zh-en` only when the user explicitly asks** (e.g. "面向英文客户",
"give me a bilingual deck"). When you switch, the CSS recipes for
agenda `.title-en`, content-3up bilingual card titles, two-hand-arch
EN mottos, etc. all light up — no token changes needed.

In zh-only mode the validator's R-LANG audit warns on three signals:
- `class="title-en"` / `subtitle-en` / `label-en` rendered in slide
  markup (these classes exist for bilingual mode only).
- Chrome-label classes (`eyebrow` / `kicker` / `pill` / `tag` / `chip` /
  `badge`, plus any class ending in `-en` / `-eng` / `-english` / `-num`
  / `-index` / `-ord` and the framework `*-tag` / `*-pill` / `*-eyebrow` /
  `*-chip` / `*-badge` derivatives) whose text content is pure
  Latin-uppercase + digits + punctuation (e.g. `AGGREGATE` / `MODE 01` /
  `PRODUCTION` / `DEADLINE`) and isn't in `LATIN_BRAND_WHITELIST`.
- **Sibling-pair signature** (2026-05-18): any parent element with ≥ 2
  text-leaf children where one leaf is CJK and another sibling leaf is
  pure-Latin. This is the structural "EN translation track" pattern —
  catches the case where the author uses an arbitrary class name (e.g.
  `ap-num` containing "01 · AGGREGATE" alongside `ap-title` "审批聚合")
  that the class-name scan would miss.

It does NOT touch tokenized vocabulary that's English by convention:
brand names (Lark, Base, Wiki, Meetings), product codes (Salesforce,
C360), units (px, pt, %), abbreviations (KPI, ROI, OKR, KOL). The
ban is on **translation tracks**, not on every Latin-script word.
Mixed-case Latin (e.g. `Context and challenges`) is also exempt — the
pair check only fires on PURE uppercase + digits + punctuation, which
is the dominant signature of intentional "label" content.

---

## CONTENT-DENSITY POLICY (mandatory) — augment thin input by default · no-fabrication guardrail

A 飞书 deck slide is **information-dense by design**. Empty space + 3 lines
of body copy reads as half-finished — the audience reaction is "为什么这页
这么空,你是不是没准备好"。The skill's defaults aim for slides that look
*deliberately curated*, not *padded out*。

**默认动作翻转(2026-05-26)**:旧策略是"输入太薄 → 先停下来问要不要补",
结果 LLM 习惯性出干瘪 3 行 body,被同学反馈"空 / 不好看"。**专业补全是
设计工作本身,不是需要审批的增补**。所以默认改成:

1. **默认就专业补全** —— 把用户输入当 SEED,按真正咨询/战略 deck 的信息密度
   设计这一页(见下 "What augmentation is allowed")。这是默认动作,不需要先问。
2. **唯一硬护栏:不编 attributed facts** —— 具体公司数字 / 具名引语 / 来源出处
   绝不编(见下 + ONE-PAGER no-fabrication 规则)。补的是公开行业知识 / 产品能力
   / 类似客户故事,且标注来源性质。
3. **沙化版式兜底** —— 真没东西可补时,换 sparser-by-design layout
   (`quote` / `big-stat` / `cover` / `end` / `image-text`),2 行也成立。

### The rule (mandatory) — 默认补,只在两种情况停下来问

检测到薄输入(layouts that **need density**:`content-2col` / `content-3up` /
`stats` / `table` / `timeline` / `process`)时:

- **默认**:直接专业补全 + 生成,**不停**(补全计划在 DESIGN PHASE Step 1 已
  写进 DESIGN-PLAN.md,supporting 页随 deck 一起出;hero 页本就会过确认门)。
- **只在以下两种情况才 STOP-and-ask**:
  1. **(a) 薄到任何 layout 都撑不住** —— 连补也撑不起一页(用户给的就一个词,
     既没角色也没具体内容)。
  2. **(b) 意图本身有歧义** —— 这页的角色 / 唯一重点不明(Q0/Q1 填不出),
     补什么方向取决于用户想强调什么。这是问**意图**,不是问"能不能补"。

停下来问时,用下面的 Asking-prompt template。注意区分:**问意图 = 该问;
问"要不要让我补文案" = 不要问,直接补**。

### What counts as "thin" — heuristic

| Layout | Expects | Thin signal |
|---|---|---|
| `content-3up` | 3 distinct points, each with title + 2-3 body lines | < 3 points provided, OR each point is 1 sentence |
| `content-2col` | One narrative + a stack of supporting points OR a visual | text column < ~80 chars, no visual material in scope |
| `stats` | 4 KPI numbers + labels + brief sources | < 3 numbers, OR all from same domain |
| `table` | ≥ 4 rows × 3 cols of meaningful comparison | < 3 rows, OR the columns aren't really distinct |
| `timeline` | 4-6 chronological milestones | < 3 milestones, OR all in same week |
| `process` | 3-6 sequential steps | < 3 steps, OR steps are vague |
| `one-pager case` (story-case) | 4 beats: 痛点 / 冲突 / 解法 / 价值 | any beat < 10 chars (already enforced by render-deck.py schema-fit refusal — exit 4) |

For `quote` / `big-stat` / `cover` / `agenda` / `section` / `end` /
`image-text`, terse input is **fine** — these are sparse-by-design.
The agent doesn't need to ask for these.

### What augmentation is allowed (after user confirms)

The framing the agent uses during augmentation:

> **"结合输入的信息,如果画一页专业的 PPT,请帮我设计对应的内容,
> 要专业风格的。"**

That is — treat the user's input as a SEED, then design the slide with
the information density and structural rigor of a real consulting /
strategy deck. Not as a creative-writing exercise, not as a marketing
brochure: as a **content-rich page a senior decision-maker would actually
read**. Concrete numbers, concrete capabilities, concrete examples,
named adjacent customers — the kind of detail that earns the slide's
real estate.

ALLOWED:
- Industry context the agent knows (e.g. "便利店行业的库存周转一般 12-15 次/年")
- Common pain points associated with the user's named scenario
- Product capability descriptions (飞书 / 多维表格 / 飞书会议 etc.)
- Adjacent customer stories from the agent's knowledge (e.g. "类似海底捞这种连锁门店常用 ……")
- Typical KPI values for the industry (always tagged as "行业基准 · 公开数据")

NOT ALLOWED, even after user confirms:
- Specific numbers attributed to a specific company (the user didn't give)
- Quotes attributed to a named person (the user didn't provide)
- Source citations like "客户访谈" / "内部口径" (covered by the existing
  "NEVER fabricate STORY ids" rule)
- Future product roadmap claims

The line: **augmentation is general industry / product knowledge tagged
as such**; it's NEVER specific facts attributed to specific entities.

### Asking-prompt template

When the agent stops to ask, use roughly this shape:

> "你给的信息支撑不满 `<layout>` 这个版式 —— 它通常需要 `<X>`,
> 你给的是 `<Y>`,直接出图会显得空。
>
> 我可以从以下几个方向**补**(都是公开行业知识 / 产品能力 / 类似客户故事,
> 不会编你没说的具体数据):
>
> 1. `<选项 1 · 一句话>`
> 2. `<选项 2 · 一句话>`
> 3. `<选项 3 · 一句话>`
>
> 或者:换成 `<sparser layout 建议>` / 你再补一段背景给我 / 直接出空版自己改。
>
> 你选哪个?"

### Connection to the no-fabrication rule

This policy and the **NEVER fabricate STORY ids / source attributions**
rule (next section) are siblings:

| Rule | What can never happen | What CAN happen |
|---|---|---|
| No fabrication (next section) | Specific facts (story id, source citation, quote attribution) made up | (nothing — facts are either real or absent) |
| Content-density (this section) | Fabricating **attributed** facts while augmenting (company-specific numbers / named quotes / sources the user didn't give) | **Professional augmentation by default** — public industry knowledge / product capability / adjacent stories, tagged as such; **no confirmation needed** |

Both come from the same north star: **the deck must not silently invent
material that the user couldn't defend in front of the audience** —— 但"补到
信息密度够"和"编造具名事实"是两回事:前者默认做,后者绝不做。

---

## ONE-PAGER CASE POLICY (mandatory) — 一页纸案例 layout

This is the **canonical layout for a single customer case rendered on
one slide** (一页纸案例 / one-pager case study). When the trigger
applies, use the `.story-case` recipe documented below — don't
improvise a different layout, don't add a cover, don't expand it into
multiple slides unless the user explicitly asks for that.

### NEVER fabricate STORY ids, source attributions, or interview citations

Case slides have a strong gravitational pull toward "looking like a
finished case-library entry" — a STORY 0NN suffix, a "数据来源 · XX
客户访谈" caption, a "本院实践访谈" footer. When the user hands you
raw material that doesn't carry these, the agent fills them in by
default, because the schema and recipe markup show them as fields.

**Don't.** Rule:

- If the user did NOT give you a story id, the brand line is
  `"飞书企业 AI · 客户案例"` — period. Do NOT append `STORY 015` /
  `STORY 0NN` / a fabricated number. The 0NN in template comments is
  a placeholder showing where the user-provided id WOULD go, not an
  instruction to make one up.
- If the user did NOT give you a source citation, OMIT the source
  line entirely (drop `.case-caption` / `.source-footer` from the
  markup; omit the `source` field from the slide's `data`). Do NOT write
  "客户访谈" / "内部口径" / "实践访谈" / "调研口径" as a placeholder
   — these read as factual claims and break trust if the customer
  reads the deck.
- The same rule applies to attribution lines under quotes
  (`<div class="attrib">`) and any `Source · ...` line under stats.
  Either the user gave you a real source, or the line doesn't ship.

When in doubt, ask: "do you have a story id / source citation for
this, or should I leave those off?" — one ping is cheaper than the
trust hit of a fake STORY 015 reaching a customer.

This rule overrides the example schemas. Treat schema fields like
`brand` and `source` that show specimen STORY/source values as
**form**, not **content**: the field exists; you fill it ONLY with
what the user actually provided.

### How to render — `content` layout + `variant: story-case` (Path A DeckJSON)

The one-pager case is a **DeckJSON layout**, not a separate engine. Author
it as a `content` slide with `variant: "story-case"` in `deck.json`, then
`render-deck.py` produces `index.html` + `texts.md` (see DECK GENERATION
POLICY for the Path A flow). The 4-beat 痛点/冲突/解法/价值 + hook + scene
shape maps 1:1 to the `data_content_story_case` schema (field reference
below). render-deck.py runs the schema-fit refusal + accent review
automatically (see "Safety nets" below).

> Historical note: pre-2026-05-26 this layout had its own TOML engine
> (`render.py one-pager`). That engine + its `examples/one-pager-luckin/`
> TOML were retired; the layout, the policy in this section, and the two
> safety nets all live in the DeckJSON path now. Old `.toml` cases convert
> 1:1 to a `content/story-case` slide.

#### When story-case doesn't fit — use a different layout (not a different engine)

The 4-beat arc is intentionally narrow. When the case's natural shape
isn't 4-beat, pick the layout that fits instead of forcing it:

1. **User asks for something story-case can't express** — "加一段客户原话",
   "做成 timeline", "用大数字突出 ROI", "把 4 个 beat 改成 6 个观察",
   "case 没有冲突,只有 3 个发现". Switch layout rather than mutilate content.
2. **The story's natural shape** is a one-sentence testimonial → `quote`;
   a hero metric + prose → `stats` variant `hero`; a chronological roadmap
   → `flow` variant `timeline`; 3 parallel observations → `content` variant
   `3up`.
3. **A genuinely one-off visual shape** that no layout + variant covers →
   `layout: "raw"` for that single slide (keep the rest of the deck on
   schema layouts). If the shape recurs across ≥ 2 decks, propose a schema
   extension (deck-json/MIGRATION-REPORT.md Phase 0.2), not a pile of raw
   slides.

Don't switch layout just for per-case flair (different fonts, off-palette
colors, custom logo) — that's drift, not fit. The brand floor below applies
to every layout you land on.

#### Brand floor (mandatory, applies to every layout)

Whatever layout the case lands on, you can vary the *shape* but NOT these
brand basics. The validator enforces most of them:

- Dark cinematic background — `lark-content-bg.jpg` via the master
  decor system, OR a brand-aligned `data-decor` token (no white /
  cream / "Apple style" backgrounds).
- Color palette from `--fs-*` tokens only — no off-palette hex (R10),
  no cyan as slide accent (R49).
- 飞书 wordmark present per L1 (color logo top-right on content,
  mono opt-in only on chapter dividers).
- 16:9 design canvas (1920×1080) — `data-screen-label` on every slide.
- ZH-only by default (no EN translation tracks under every CN line).
- All other validator rules (L1-L4, R02-R56, P50-P55, UI1, T01-T03)
  must still PASS strict. Deviation is a layout choice, not a license
  to skip integrity checks.

If a genuinely new case shape recurs across ≥ 2 decks, propose a schema
extension (a new `content` variant or a new layout) per
deck-json/MIGRATION-REPORT.md Phase 0.2 — that's how the layout catalog
grows, without one-off raw slides accumulating.

#### When the user rejects a story-case output

If the problem is *visual or structural* and it'd recur on the next case,
fix the **template** (`deck-json/templates/content-story-case.fragment.html`)
or its CSS in `assets/feishu-deck-patterns.css`, then re-render — don't
hand-patch the single output's `index.html` (the next render overwrites it,
and the next case hits the same bug).

If the problem is *copy / wording / strategic emphasis*, edit the slide's
`data` in `deck.json` (or `texts.md`) and re-render. The template is fine;
the content was wrong.

If the problem is *"this case shouldn't have been story-case at all"*,
switch the slide's layout/variant (see "When story-case doesn't fit"
above) and proactively expand the trigger-detection rules so similar cases
route correctly next time.

### Safety nets — schema-fit refusal + accent review (in render-deck.py)

`render-deck.py` runs two automatic checks for every `content/story-case`
slide (ported 2026-05-26 from the retired render.py). They catch the
predictable failure modes: thin/placeholder beats, and a mis-framed accent.

**1 · Schema-fit refusal (exit 4).** After schema-validate, before render,
every story-case beat is scanned for:

- Placeholder content: `TBD / TODO / TBC / XXX / N/A / 待补 / 占位 /
  稍后补充 / 未填 / None`, ellipsis-only, question-mark-only strings.
- Length floor: meaty beats (`arc.pain / arc.conflict / arc.solution`)
  ≥ 10 chars; `*.accent` ≥ 2 chars; `*.lead / *.tail` ≥ 1 char (connective).
- Duplicate content across beats (laziness signal).

If any beat fails, render REFUSES (exit 4) and lists the offenders. Correct
response:

- Fill the beat in `deck.json` with real content.
- **Switch layout** — the failure often means "this story doesn't have a
  clean 4-beat arc"; use quote / stats-hero / content-3up instead.
- `--skip-fit-check` to bypass, ONLY for a specific reason (intentionally
  terse copy the user confirmed). Not a way to silence the warning.

**2 · Accent review (post-render print).** After a successful render,
render-deck.py prints each accent-bearing field with the highlight marked
(ANSI teal in a TTY, `[brackets]` otherwise):

```
ACCENT 复核 (1 秒目测,被高亮的词是该突出的吗?)
  luckin-case ·  hook  ·  新店垃圾桶距出餐窄 1 米,按 SOP 必须 [砸墙返工] —— …
  luckin-case · value  ·  飞书把这种隐形经验萃取到 [企业 AI 知识库],…
```

Eyeball it. If the bracketed word isn't the emotional pivot (e.g. `1 米`
instead of `砸墙返工`), fix `arc.value.accent` / `hook.accent` in `deck.json`
and re-render.

### Field reference — `data_content_story_case` (deck.json)

Full schema: `deck-json/deck-schema.json` → `$defs/data_content_story_case`
(`required: title, industry, hook, arc, scene`). The `data` block of a
story-case slide:

```jsonc
{ "key": "case-<slug>", "layout": "content", "variant": "story-case",
  "accent": "blue", "decor": "blue-glow",
  "screen_label": "01 客户案例 — 标题",
  "data": {
    "title":    "客户/项目 · 案例标题",           // single line, no <br> (R13)
    "industry": "行业 · 场景 · 客户案例",          // short pill tag
    // OPTIONAL story-id / source — ONLY if the user gave one. NEVER fabricate.
    "hook":  { "lead": "…before…", "accent": "强调动词", "tail": "…after…" },
    "arc": {
      "pain":     "…",                              // blue   · ≥10 chars
      "conflict": "…",                              // orange · ≥10 chars
      "solution": "…",                              // teal   · ≥10 chars
      "value":  { "lead": "…", "accent": "…", "tail": "…" }   // violet
    },
    "scene": { "image": "input/scene.png",          // path relative to deck.json
               "caption": "现场 · 一句话场景说明",
               "alt": "无障碍描述,完整场景内容" }
  } }
```

Render with the standard Path A flow:
`python3 deck-json/render-deck.py runs/<ts>/output/deck.json runs/<ts>/output/`.
Outputs `index.html` + `texts.md`; the scene image is copied in. A non-zero
exit on a story-case slide is usually the schema-fit refusal (exit 4) — read
the offenders, not a template bug.

### Trigger detection — when to use this layout

Apply the one-pager case layout when ANY of the following is true:

- The user explicitly says **"一页纸案例" / "one-pager case" / "做成一页"
  / "single-page case study" / "压成一页" / "one-page version"**.
- The user hands you ONE row of a customer-story table / story library
  / 案例库 and asks to "make a deck" / "试试效果" / "把这一行做出来" /
  "这个案例做一下".
- The user provides a single customer case with these typical fields:
  题目 / 行业痛点 / 钩子 / 故事背景 / 核心情节 / 核心价值. That field
  shape IS the one-pager case shape.
- The user asks you to "render this case" / "show this customer story"
  / "做这个客户案例" without specifying length.

When in doubt between one-pager vs multi-slide expansion, **default to
one-pager** and offer to expand if the user wants more depth. One-pager
is faster to consume, easier to forward, and works as the IM preview.

The CSS class `.story-case` (added on the `.slide` element) is the
canonical marker for this layout. Any slide with `class="story-case"`
on `.slide` MUST follow the rules in this section.

### Skip the cover page

When the trigger above applies, **SKIP the `cover` layout entirely**
and open the deck with the one-pager content slide.

### Why this is mandatory

- A single-case deck has no deck-level title that needs a hero cover.
  The case IS the content — a separate cover page wastes a slide and
  forces the reader through a click of pure ceremony before they reach
  the value.
- The case illustration belongs **inside** the content slide as the
  visual (right column / hero image), not isolated on a cover. Putting
  it on a cover divorces the image from the narrative.
- Internal sharers / WeCom forwards / IM previews show only the first
  slide. If that slide is a generic cover, the recipient sees nothing
  about the actual story. If it's the content slide, they see the hook,
  the title, and the visual all at once.

### The one-pager structure (mandatory shape)

`data-layout="content-2col"` with `class="story-case"` on the `.slide`,
arranged as:

- **Header**: the case title (one line, no `<br>`, no eyebrow per R56).
- **Left column** (`.col-text`):
  - `.industry-tag` — small accent chip naming the industry / scenario
  - `.story-hook` — the one-line hook (use a `.accent` span on the
    pivot keyword to highlight in teal)
  - `.story-arc` — 4-row labeled narrative beats:
    `痛点` (blue) → `冲突` (orange) → `解法` (teal) → `价值` (violet)
- **Right column** (`.col-visual`): the case illustration as a hero
  frame (see "Image is the visual hero" below for sizing rules — image
  goes in via `background-image`, NEVER an `<img>` tag, to satisfy UI1).
- ~~**`.source-footer`** (data citation line below the body)~~ **Retired 2026-05** alongside `.footer`. Data citations now live inline in the slide body (as a `.caption`, in a corner `.eyebrow`, or just trailing text). Hide-only CSS keeps any leftover DOM invisible.
- ~~**Chrome footer**: brand line + page number.~~ **Retired 2026-05.** The fullscreen present-mode pager (bottom-center prev/next/page-no bar) now shows the page number; the corner `.wordmark` carries the brand. The renderer no longer emits `<div class="footer">` / `<span class="pageno">`. Validator R07 no longer requires it. Don't add it to new slides.

The 4-beat 痛点/冲突/解法/价值 arc IS the rhetorical structure of a
one-pager case. Don't replace it with generic bullets; the labeled
beats are what carry the narrative through one slide.

### When the case doesn't fit the 4-beat shape

Substitute layouts ONLY when the case content forces it:
- `content-3up` — case naturally splits into 3 parallel beats (e.g.
  "三个发现" without a clear conflict→solution narrative)
- `quote` — case IS a one-sentence customer testimonial (no narrative
  arc, just the voice)
- `image-text` — case is more about the scene than the analysis (e.g.
  "看这家门店一周的状态变化")

NEVER use `cover` / `agenda` / `section` / `end` for a one-pager case.
And NEVER expand a one-pager into multiple slides without the user
explicitly asking — the whole point is that it fits on ONE page.

### Multi-case bundles are different

A deck that bundles **3+ cases** (a "客户案例集" / "story library" /
"quarterly customer review") DOES get the standard treatment:
- `cover` slide with the deck title
- `agenda` listing the cases
- `section` divider per case (optional)
- One or more content slides per case

The "skip the cover" rule is specifically for single-case / one-row decks.
If unsure, ask: "is this one case or a bundle?" — the answer determines
whether the cover stays.

### When the user explicitly wants a cover

Override the default if the user says one of:
- "我要一个封面页" / "give it a cover" / "加一张封面"
- "做成正式提案" (formal proposal explicitly needs a hero cover)
- The single case is going to a board / external customer (formal
  context, cover earns its keep)

In all other single-case scenarios, default = no cover, content slide
opens the deck.

### Image sizing — magazine-spread top-aligned (v2, frozen 2026-05-03)

The case illustration is the slide's emotional anchor on the right.
History of the rule (relevant context for future maintainers):

- **v0 (broken)**: `aspect-ratio: 16/9` thumbnail → ~460 px tall image
  with 300 px of empty space below. User feedback: "图太小了".
- **v1 (overshot)**: `min-height: 680 px` hero filling ~88 % of the
  770 px stage zone → image taller than text content, awkward visual
  imbalance. User feedback: "右边的图还是有点大,能不能和左边文字
  的标题对齐".
- **v2 (current)**: image height = LEFT text column's natural height,
  both columns top-aligned, row vertically centered in stage. Reads
  like a magazine spread; image is still ~57 % of the grid width
  (clearly hero by area), but its proportions match the text it
  illustrates.

**Mandatory sizing rules (v2)**:

1. **Column ratio still favors the image.** `1fr 1.3fr` (text 43 %,
   image 57 %). Image is hero by *area*, not by *being taller*.

2. **Top-align both columns; image height equals text height.**
   `grid-template-rows: auto` on `.grid` makes the row natural-sized;
   `align-items: stretch` makes the visual column match the text
   column's height. **Do NOT** set `min-height: 680 px` (the v1 bug)
   or `justify-content: center` on `.col-text` (also v1).

3. **Image is cropped via `background-size: cover`** to fit the
   text-determined height. The 16:9 illustration sitting in a
   ~440 × 950 frame loses ~50 px from top and bottom — fine as long
   as the illustration's main subject is centered (most are).
   Side crop is also fine for the same reason.

4. **Use `background-image`, NOT `<img>`** (UI1 validator treats
   `<img>` in slide content as a possible UI screenshot). Mark the
   frame `role="img" aria-label="..."` for a11y. Per-instance image
   URL goes in inline `style="background-image: url(...)"`, NOT in
   the shared CSS — bundles need per-case `scene-NN.png` filenames.

5. **Caption goes INSIDE the frame as an overlay** (bottom-left
   absolute pill, rgba dark + backdrop blur). Reads like a
   documentary still. Don't stack `frame + caption-below` — it
   shrinks the frame.

6. **`min-height: 360 px` floor** on the frame catches degenerate
   cases where the left text column is unusually short (e.g. a
   one-pager with 2-line beats). Below that, the image stops
   shrinking and the row gets a touch of extra height. Tune this if
   real cases hit it; default is fine for the typical 4-beat shape.

### Reference markup — copy this for a single-case content slide

```html
<div class="slide story-case" data-layout="content-2col" data-accent="blue"
     data-decor="blue-glow" data-screen-label="01 客户案例 — 标题">
  <div class="wordmark"></div>
  <div class="header">
    <h2 class="title-zh" data-text-id="slide-01.title">客户/项目 · 案例标题(单行)</h2>
  </div>
  <div class="stage">
    <div class="grid">
      <div class="col-text">
        <span class="industry-tag">行业 · 场景 · 客户案例</span>
        <p class="story-hook">钩子(一句话定调,核心动词用 .accent 标 teal)。</p>
        <div class="story-arc">
          <div class="row"><span class="lbl">痛点</span><p>…</p></div>
          <div class="row"><span class="lbl is-orange">冲突</span><p>…</p></div>
          <div class="row"><span class="lbl is-teal">解法</span><p>…</p></div>
          <div class="row"><span class="lbl is-violet">价值</span><p>…</p></div>
        </div>
      </div>
      <div class="col-visual">
        <div class="scene-frame" role="img" aria-label="…现场描述…">
          <span class="scene-cap">现场 · 一句话场景说明</span>
        </div>
      </div>
    </div>
  </div>
</div>
```

The story-case v2 CSS lives in `assets/feishu-deck-patterns.css` —
render-deck.py's `content-story-case.fragment.html` links it, so a
v2 → v3 refactor only touches one file. **DON'T inline these rules** in a
`<style>` block on a normal story-case slide.

If you hand-author a one-off story-case as a `layout: "raw"` slide (the
rare case where you need bespoke markup), copy this block verbatim into
that slide's `<style>`:

```css
.slide.story-case[data-layout="content-2col"] .grid {
  display: grid;
  grid-template-columns: 1fr 1.3fr;
  grid-template-rows: auto;             /* row sizes to content (v2) */
  column-gap: 56px;
  align-content: center;                /* center the row in the 770px stage */
  align-items: stretch;                 /* both cols share row height */
}
.slide.story-case .col-text {
  display: flex; flex-direction: column;
  gap: 28px; min-width: 0;
  /* no justify-content: center — content top-aligns inside col (v2) */
}
.slide.story-case .col-visual {
  display: flex; align-items: stretch; min-width: 0; min-height: 0;
}
.slide.story-case .scene-frame {
  position: relative;
  flex: 1; width: 100%;
  min-height: 360px;                    /* floor for degenerate cases (v2) */
  border-radius: 20px;
  border: 1px solid rgba(255,255,255,0.12);
  background-color: rgba(8,12,24,0.45);
  background-repeat: no-repeat;
  /* per-instance: inline style="background-image: url('./scene.png');
                                background-position: center;
                                background-size: cover;" */
  box-shadow: 0 24px 64px -24px rgba(0,0,0,0.65),
              0 0 0 1px rgba(60,127,255,0.16);
}
.slide.story-case .scene-frame .scene-cap {
  position: absolute; left: 18px; bottom: 18px;
  padding: 8px 14px;
  background: rgba(8,12,24,0.72);
  backdrop-filter: blur(8px);
  border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.10);
  font: 500 16px/1.3 var(--fs-font-cjk);
  color: rgba(255,255,255,0.85);
  letter-spacing: 0.04em;
}
```

### Quick check before delivering

Open the slide and ask: *do the left column's first text element
(industry tag) and the right column's image top-edge sit on the same
horizontal line?* If yes, v2 is rendering correctly. If the image
extends above OR below the text content, the row is using `1fr`
instead of `auto` (regression to v1 behavior — fix it).

---

## Layer-1 patterns (RETIRED 2026-05-26) — quote / big-stat / multi-case-bundle

These were a separate TOML-driven engine (`assets/render.py`). **Retired** —
they were fully redundant with DeckJSON Path A layouts. The engine, its
templates, and its `examples/*-luckin/` TOML samples were removed; the
story-case schema-fit refusal + accent review were ported into
`render-deck.py` (see the ONE-PAGER section's "Safety nets").

Author what used to be a Layer-1 pattern as a normal deck.json layout:

| Old Layer-1 pattern | Now author as (deck.json) |
|---|---|
| `quote`             | `layout: "quote"` |
| `big-stat`          | `layout: "stats"`, `variant: "hero"` |
| `one-pager`         | `layout: "content"`, `variant: "story-case"` (see ONE-PAGER CASE POLICY above) |
| `multi-case-bundle` | a normal multi-slide deck: `cover` + `agenda` + one `content/story-case` per case + `end` |

Old `.toml` case files convert 1:1 to the shapes above. If you ever need to
render a legacy `.toml`, `render.py` is recoverable from git history.


## RUN-FEEDBACK CAPTURE (mandatory) — auto-generated `FEEDBACK.md` per run

Every successful run MUST produce a `FEEDBACK.md` file in
`runs/<ts>/output/` alongside `index.html` and `texts.md`. This is the
manual feedback loop that drives skill maintenance: the agent
auto-records the **judgment calls and workarounds it actually made
during this run**, the user spot-checks them, and when they accumulate
≥3 things worth raising, sends the file to the skill maintainer for
integration into the next skill version.

### Why "auto-generated, not template"

A blank "tell us what's broken" form gets blank answers. What works is
showing the user **the specific decisions the agent made on their
content** — layout choices, sizing tweaks, validator workarounds, copy
shortenings, master deviations — and asking them to confirm or push
back per-decision. The user reads through the list, sees one item that
feels wrong, makes a note, moves on. No reconstruction effort needed.

### What goes into `FEEDBACK.md` (REQUIRED sections)

The agent fills the file based on **what actually happened in this
run** — not from a fixed template. Every run is different; the file
content reflects this run's specific decisions. Required sections:

1. **Header** — run timestamp + one-line description of what was built
   (layout, slide count, source material).

2. **关键决策 (auto-detected from this run)** — every non-trivial choice
   the agent made on the user's content. Each item gets:
   - what was decided (1-2 sentences)
   - why (the constraint or content shape that drove it)
   - a `你的看法:` line with checkboxes covering the realistic
     pushback shapes for that decision (`[ ] 对 / [ ] 应改成 X / [ ] 备注`)

   Examples of decisions that belong here:
   - layout pick (e.g. "用了 `.story-case` 因为 …")
   - column ratios / sizing tweaks (e.g. "图片列从 1fr 1fr 改到 1fr 1.3fr")
   - copy shortenings (e.g. "标题从 22 字压到 17 字以单行容纳")
   - validator workarounds (e.g. "把 '#001' 改成 'STORY 001' 因为 R10 误判 hex")
   - master deviations (e.g. "封面加了 subtitle 偏离 master,因为 …")
   - asset choices (e.g. "用 background-image 而非 `<img>` 满足 UI1")

3. **本次没解决的小毛病** (if any) — warnings the agent noticed but
   didn't fix (e.g. "validator 对 `.scene-cap` 做 backdrop-filter 警告
   但在阈值内,没改").

4. **你的额外建议** — empty bullets for the user to add anything not
   already auto-detected.

5. **末尾提示** — exactly:
   > 累计 ≥3 条值得反馈的(打钩 / 备注 / 自填),把这个文件发给 skill 维护者整合到下一版.

### What does NOT go into `FEEDBACK.md`

- Generic / boilerplate self-checklist questions ("layout 对吗? 字号对吗?")
  — useless without context. Only ask about decisions that were
  actually made.
- The validator's PASS report (already shipped in delivery message).
- The slide count or token usage (irrelevant to maintainer).
- Praise of the skill ("looks great!"). The file is for upgrade
  signal only.

### Don't hardcode contact info

`FEEDBACK.md` says "send to skill maintainer" — NOT a specific email,
handle, or IM address. Different installs of this skill have different
maintainers; the recipient identity is implicit per repo convention
(GitHub `CONTRIBUTING.md`, `git log`, the install team's group chat).
Hardcoding a personal address would couple the skill to one person.

### How the agent surfaces it at end of run

After validator passes and files are written, the agent's delivery
message (Mode 1 — Claude Code on local) MUST include:

> · `runs/<ts>/output/FEEDBACK.md` — 这次 build 的关键决策清单,
>   见到不对的地方打钩或备注;累 ≥3 条发给维护者整合到下版.

For Mode 2 (zip / remote / Feishu bot), `FEEDBACK.md` ships INSIDE
`deck-editable.zip` so the recipient can fill it offline. The
`package-deliverable.sh` script already includes `*.md` files in the
zip; no extra work needed.

### Maintainer-side workflow (informational, not enforced)

When the maintainer receives a batch of `FEEDBACK.md` files (e.g. 5+
forwarded over a few weeks), the integration ritual is:
1. Read all files; cluster comments by decision class (sizing,
   validator, layout choice, …).
2. Promote any cluster ≥3 reports into a SKILL.md rule update,
   citing the sample FEEDBACK files in the commit message.
3. One-off comments without cluster support → log in
   `LESSONS.md` (or the equivalent), revisit at next batch.

This step is the maintainer's call, not the agent's — the agent's job
ends at producing high-quality `FEEDBACK.md` files. Keeping the
integration manual is the user's explicit control point over skill
evolution.

---

## RUN-PROMPTS LOG (Phase 1) — `PROMPTS.md` per run

Goal: mine user prompts across many decks to surface **skill-gap
signals** (audit rules / defaults / protocols the skill SHOULD have
caught but didn't) and **workflow patterns** the user can improve on.
Each `runs/<ts>/output/` ships a `PROMPTS.md` capturing every user
prompt that touched the deck, verbatim + lightly tagged.

Full format spec: **`assets/PROMPTS-format.md`** (canonical, all writers
must conform).

### Two writing paths

| Path | When | Who runs it |
|---|---|---|
| **Realtime append** | The agent (any agent supporting it) appends to PROMPTS.md after each user message, before generating any artifact | Agent itself, per the contract in `PROMPTS-format.md` "Realtime-append contract" |
| **Post-hoc extraction** | Backfill historical decks OR rebuild PROMPTS.md from an agent that didn't realtime-append | User runs `extract-from-<agent>.py` against the agent's transcript files |

Both paths produce **the same canonical format**, so downstream analysis
doesn't care which path was used. The two paths can coexist on one
deck (e.g., realtime entries plus a backfill from before realtime
support was added).

### Shipped adapters (Phase 1)

- **`assets/extract-from-claude-code.py`** — for Claude Code's
  per-session JSONL transcripts at `~/.claude/projects/<encoded-cwd>/
  <session-id>.jsonl`. Single-flag deck filter (`--filter-deck SLUG`),
  session-level scoping (any prompt in a transcript mentioning the
  slug → include all prompts from that transcript).
- (other agent adapters: TBD — Codex / Mira / Cursor / Aider need
  sample transcripts before adapters can be written; do NOT speculate-write
  blind adapters)

Use:
```bash
# one transcript
python3 skills/feishu-deck-h5/assets/extract-from-claude-code.py \
    ~/.claude/projects/-Users-bytedance/<session-id>.jsonl \
    --out runs/<ts>/output/PROMPTS.md

# many transcripts → one deck
python3 skills/feishu-deck-h5/assets/extract-from-claude-code.py \
    ~/.claude/projects/-Users-bytedance/*.jsonl \
    --filter-deck <slug> \
    --out runs/<ts>/output/PROMPTS.md \
    --title "<deck display name>"
```

### Realtime-append contract (when agent supports it)

When supported, the agent MUST after every user message:

1. Compute the run's PROMPTS.md path:
   `runs/<ts>/output/PROMPTS.md` (same directory as the deck artifact)
2. If file doesn't exist, create with title + standard header
3. Append a new entry with the timestamp + type guess + slide refs +
   `(agent: <id>)` tag + verbatim user text
4. DO NOT proceed to generate the artifact until the append is done

**Verbatim or nothing**: do NOT summarize, translate, "improve", or
LLM-remix the user's wording. The log's value is its truthiness. If
the user wrote "字小了，没啥没检查出来" that is exactly what goes in.

If the agent runtime cannot file-write (sandboxed harness), print
`PROMPT-LOG: <ts> | <type> | <verbatim text>` to stdout so the user
can hand-append to PROMPTS.md. Don't silently drop.

### Why this exists (the actual goal)

Most "bugs" in a finished deck started as a user complaint like "字小了"
or "标题位置不对" or "中间太空" — the user was the audit. PROMPTS.md
turns that audit into a queryable signal:

| Signal type | What you mine PROMPTS.md for | Yields |
|---|---|---|
| **Skill-gap** | Repeated `bug-report` complaints across decks (e.g. "字小" appears 47 times across 23 decks) | New audit / rule / default — promote into validator |
| **Protocol miss** | `bug-report` AND the prior agent response shows skipped pre-check (no Q0-Q4 design pass, no backup before delete, etc.) | Tighten existing rule into hard gate |
| **Workflow inefficiency** | ≥ 5 edits on the same slide-key within 24h | Per-user coaching note: batch edits, use deck.json bulk ops, etc. |

The `bug-report` class is by far the highest-value mine. Real
production rate (in maintainer's testing on a 43-slide deck): 50
bug-report prompts → at least 2 new audit rules + 1 hard-gate
elevation. That's a 1:25 ratio of skill upgrades to user complaints,
which is what makes the log worth keeping.

### What NOT to log

- Assistant responses (out of scope; log is the USER's voice)
- Tool outputs (out of scope)
- System-injected messages (`<command-name>`, `<system-reminder>`,
  `<local-command-caveat>` — adapters MUST strip these)
- Anything synthesized by an LLM in passing (e.g. an agent's
  "I think the user meant ..." paraphrase)

### Privacy boundary

- PROMPTS.md is per-run, lives next to the deck in `runs/<ts>/output/`
- Same lifecycle as the deck — `package-deliverable.sh` already
  includes `*.md` files, so PROMPTS.md ships with the deck unless
  excluded
- **No automatic cross-user aggregation**. If you want a multi-user
  analysis dataset, collect PROMPTS.md files MANUALLY into a separate
  repo / dir — the user explicitly chooses what they share

If a PROMPTS.md contains sensitive content (real customer names,
internal metrics), `package-deliverable.sh --exclude PROMPTS.md` (TBD)
or just `rm` before zipping. There's no automated PII scrubbing yet.

---

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

If the user explicitly asks for `.pptx`, route to the **pptx** skill instead.

If the user asks for a generic non-Feishu deck (e.g. white background, Apple style),
this skill is the wrong choice — its design tokens are brand-locked.

---

## Files in this skill

```
feishu-deck-h5/
├── SKILL.md                    ← you are here
├── DESIGN.md                   ← 9-section design system spec (awesome-design-md format)
├── assets/                     ← TWO layers: framework (top) + shared content pool (shared/)
│   ├── feishu-deck.css         ← all design tokens + 13 slide layouts (single source of truth)
│   ├── feishu-deck.js          ← scale-to-fit + present/scroll modes + keyboard nav
│   ├── edit-mode/              ← client-side WYSIWYG editor (auto-injected by shell templates, default-on since 2026-05-21)
│   │   ├── deck-edit-mode.css  ← edit-mode chrome (toolbar, drag affordances)
│   │   └── deck-edit-mode.js   ← contenteditable text leaves + drag-reorder + Cmd/Ctrl+S save
│   ├── validate.py             ← programmatic self-check (HARD GATE before delivery)
│   ├── apply-texts.py          ← patch HTML from edited texts.md (text-edit sidecar)
│   ├── extract-texts.py        ← bootstrap texts.md from a deck (annotate or dump)
│   ├── copy-assets.py          ← per-run portability + emits assets-manifest.yaml
│   ├── new-run.sh              ← create runs/<timestamp>/{input,output}/ workspace
│   ├── preflight.sh            ← mandatory local-mount check
│   ├── lark-logo.png           ← color logo (petals + 飞书) for cover/end. From master image3.png
│   ├── lark-logo-mono-white.png← mono-white variant for content/section pages
│   ├── lark-cover-bg.jpg       ← flower-on-dark master background. From master image2.jpg
│   ├── lark-section-bg.jpg     ← cool blue glow on right (chapter pages). From master image4.jpg
│   ├── lark-content-bg.jpg     ← subtle dark gradient (content pages). From master image1.jpg
│   ├── lark-slogan.png         ← "先进团队 先用飞书" slogan PNG. From master image6.png
│   └── shared/                 ← library-grade reusable pool (cross-deck, dedupe-able)
│       ├── clientlogo/         ← 客户/投资机构 brand PNGs (251+ files, growing)
│       ├── digital_employee_avatars_50/ ← 50-portrait generic AI agent library
│       ├── mydigitalemployee/  ← user's named personas (睿睿/参参/探探/呆呆/图图/…)
│       ├── third-party-logos/  ← zoom/slack/salesforce/钉钉/… (sales-ops tools, NOT bytedance)
│       ├── feishu-products/    ← 飞书标识_* (AI/aily/aPaaS/多维表格/… brand kit)
│       └── bytedance-products/ ← 字节系产品 logo (doubao/trae/…) — 飞书之外的字节家产品
├── templates/
│   ├── _shell.html             ← the empty single-file deck skeleton (head + 1 sample slide)
│   └── slide-recipes.html      ← every layout shown in one reference deck (copy the markup you need)
├── examples/
│   └── sample-deck.html        ← a polished 12-slide demo deck (for reference + visual check)
└── preview-dark.html           ← token swatches + type scale + component gallery
```

### Assets layout — two layers (framework + shared pool)

`assets/` has two layers, separated by purpose:

- **Framework** (top-level of `assets/`): `feishu-deck.css`, `feishu-deck.js`,
  and the lark master brand kit (`lark-logo*`, `lark-*-bg.*`, `lark-slogan.png`).
  Every deck depends on these — they ship with every deliverable, never deduped.
- **Shared content pool** (`assets/shared/`): cross-deck reusable PNGs —
  client logos, digital-employee portraits, third-party tool logos, feishu
  sub-product brand kit. Many decks share the same files; downstream tools
  (the slide library) dedupe these against their own `assets/shared/` copy.

**`copy-assets.py` emits `output/assets-manifest.yaml`** at hand-off time,
classifying every referenced file as `shared` / `framework` / `deck-local`.
The slide library reads this manifest on ingest:

- `shared` → don't copy into the deck folder; rewrite the path to the library's
  shared pool (saves ~50–500 KB per deck).
- `framework` → leave alone; deck stays self-contained.
- `deck-local` → copy into `decks/<id>/assets/` (deck-unique covers, photos).

**Back-compat**: pre-reorg references like `assets/clientlogo/foo.png` (no
`shared/` prefix) still work — `copy-assets.py` auto-redirects to
`assets/shared/clientlogo/foo.png`. New authoring should use the canonical
`shared/` paths everywhere.

### Brand assets — must travel with every deck

Every deck depends on these six image files, which were lifted directly from the
official **飞书 母版 2025（深色通用）** PowerPoint master. They live in `assets/` and are
referenced via CSS variables (`--fs-asset-logo` etc.). For single-file delivery, base64-
inline them into a `:root { --fs-asset-… }` override block — see how
`examples/sample-deck.html` does it.

| Variable                | Default file                  | Source (from .thmx)         | Used by             |
|-------------------------|-------------------------------|-----------------------------|---------------------|
| `--fs-asset-logo`       | `lark-logo.png`               | `theme/media/image3.png`    | cover, end (top-left, color) |
| `--fs-asset-logo-mono`  | `lark-logo-mono-white.png`    | recolored from image3.png   | section + every content page (top-right, mono) |
| `--fs-asset-cover-bg`   | `lark-cover-bg.jpg`           | `theme/media/image2.jpg`    | cover, end backgrounds |
| `--fs-asset-section-bg` | `lark-section-bg.jpg`         | `theme/media/image4.jpg`    | section divider |
| `--fs-asset-content-bg` | `lark-content-bg.jpg`         | `theme/media/image1.jpg`    | content / agenda / stats / table / etc |
| `--fs-asset-slogan`     | `lark-slogan.png`             | `theme/media/image6.png`    | end / 封底带 slogan |

### 飞书 product-line icons (2026-05-06) — `assets/shared/feishu-products/飞书标识_*.png`

Beyond the master 6 brand assets above, the skill also ships the
**飞书产品线 official 标识** PNGs covering all product modules. Use these
when a slide references a specific 飞书 product (aily / 多维表格 / 妙搭 /
…) — DON'T draw a stylized clone, DON'T hand-write SVG approximations,
DON'T fetch from the web. The licensed PNGs are right here.

**Naming convention**: `飞书标识_{产品}_{变体}.png`

| 产品 (中文) | Reference path (Color variant by default) | Use for |
|---|---|---|
| AI (飞书 AI 通用) | `assets/shared/feishu-products/飞书标识_AI_Color.png`             | 飞书 AI 入口 / AI 主题页(P04 中卡 hero) |
| aily          | `assets/shared/feishu-products/飞书标识_aily_Color.png`            | aily 智能体相关 |
| aPaaS         | `assets/shared/feishu-products/飞书标识_aPaaS_Color.png`           | 业务搭建 / 低代码相关 |
| 妙搭          | `assets/shared/feishu-products/飞书标识_妙搭_Color.png`            | 妙搭轻量系统 |
| 知识问答      | `assets/shared/feishu-products/飞书标识_知识问答_Color.png`        | 飞书知识问答 / Wiki AI |
| 飞书会议      | `assets/shared/feishu-products/飞书标识_飞书会议_Color.png`        | AI 会议 / 视频会议页 |
| 飞书多维表格  | `assets/shared/feishu-products/飞书标识_飞书多维表格_Color.png`    | Base / 业务一张表 |
| 飞书人事      | `assets/shared/feishu-products/飞书标识_飞书人事_Color.png`        | HR 模块 |
| 飞书招聘      | `assets/shared/feishu-products/飞书标识_飞书招聘_Color.png`        | 招聘模块 |
| 飞书绩效      | `assets/shared/feishu-products/飞书标识_飞书绩效_Color.png`        | 绩效模块 |
| 飞书项目      | `assets/shared/feishu-products/飞书标识_飞书项目_Color.png`        | 项目管理模块 |
| 飞书People    | `assets/shared/feishu-products/飞书标识_飞书People_Color.png`      | HR 套件总称 |
| 集成平台      | `assets/shared/feishu-products/飞书标识_集成平台_Color.png`        | 集成 / 中台 |

**3 variants per product** — pick by background tone:

- `_Color.png` (default) · 全彩,深色背景上用(我们 deck 默认就是深色,所以
  绝大部分场景用这个)
- `_White.png` · 单色白,在已有强色块/品牌色背景上用,避免色彩打架
- `_Black.png` · 单色黑,白色背景 deck 用(本 skill 默认深色 deck,基本用不到)

**How to embed (UI1-friendly)**:

```html
<!-- Use background-image on a div (NOT <img>) so UI1 validator stays
     quiet and the PNG can be controlled via CSS sizing -->
<div class="card-logo" role="img" aria-label="飞书 aily"
     style="background-image: url('../../../skills/feishu-deck-h5/assets/shared/feishu-products/飞书标识_aily_Color.png')"></div>
```

```css
.card-logo {
  width: 56px; height: 56px;             /* 方形 icon 默认尺寸 */
  background-position: center;
  background-size: contain;
  background-repeat: no-repeat;
}
/* Hero card: 用 lark-logo.png (含 wordmark) 而不是产品 icon */
.card.is-hero .card-logo {
  width: 180px; height: 57px;            /* lark-logo 是宽比例 (582:183 ≈ 3.18:1) */
  background-image: url('../../../skills/feishu-deck-h5/assets/lark-logo.png');
}
```

**Authoring discipline**:

1. 任何 slide 提到具体 飞书 产品 → **优先从 `assets/shared/feishu-products/` 找现成 PNG**,不要自己画 SVG / 用 emoji / 用文字代替
2. 找不到对应产品的 icon → 用 `lark-logo.png` (飞书品牌总标志,含 wordmark) 兜底,**不要自己设计**
3. 多个产品并列出现 (如 P04 三入口卡) → 中卡用 `lark-logo.png` (品牌总标志) 突出,边卡用产品 icon 区分
4. 编辑器路径相对值跟你的文件位置变 — 一般 `runs/<ts>/output/` 下用 `../../../skills/feishu-deck-h5/assets/...`,`single-pages/` 子目录加多一层

**Why this is mandatory**: 飞书的 brand guidelines 要求产品标识必须用 official
PNG,不允许重绘。手写 SVG 模仿就是商标违规;用 emoji 替代失专业感;
fetch 远程图既慢又怕版权链接失效。`assets/shared/feishu-products/` 里 45 张就是定稿版本,直接拿来用。

### Client / portfolio brand logos (mandatory) — `assets/shared/clientlogo/`

When a slide shows a **client brand**, **portfolio company**, **PE/VC firm**,
or any "we serve / 这些客户都在用" matrix, the logo PNG MUST come from
`assets/shared/clientlogo/<filename>.{png|jpg|jpeg}`. **Do NOT** put per-client
logos in `assets/` root — that folder is reserved for framework
(feishu-deck CSS/JS) + lark master brand (logo / cover bg / slogan) only.

**Filename matching rule**:

1. **First** look for the client's Chinese name as filename: `霸王茶姬.png`,
   `茶百道.png`, `益禾堂.png`, `源码资本.png`, `中金公司.png`.
2. **Fall back** to canonical English short name / abbreviation: `IDG资本.png`,
   `KKR.png`, `PAG.png`, `CPE源峰.png`, `Mistine_1.png`, `moodytiger.png`.
3. Multiple variants for the same brand → suffix `_N` (`太平鸟_1.png`,
   `新希望_2.png`) or `_paired` for the smaller variant used in 2-up
   paired cells (`CPE源峰_paired.png`).

**Lookup workflow** (every time you author a slide that references client logos):

```bash
ls /Users/<user>/.claude/skills/feishu-deck-h5/assets/shared/clientlogo/ | grep -i "<name>"
```

If the brand exists → use that file. If it doesn't → ask the user to drop
it into `assets/shared/clientlogo/` first; do NOT save it to the run's
`input/` folder, do NOT save it to `assets/` root, do NOT generate a
text fallback PNG without telling the user.

**HTML embed pattern**:

```html
<!-- Bg-image on div for UI1-friendliness -->
<div class="logo-card" role="img" aria-label="霸王茶姬">
  <div class="logo" style="background-image: url('../../../../skills/feishu-deck-h5/assets/shared/clientlogo/霸王茶姬.png')"></div>
</div>

<!-- Or <img> when explicit dimensions / max-width matter -->
<img src="../../../../skills/feishu-deck-h5/assets/shared/clientlogo/中金公司.png" alt="中金公司">
```

(Path depth: `runs/<ts>/output/single-pages/p<NN>.html` → 4 levels up to
repo root, then `skills/feishu-deck-h5/assets/shared/clientlogo/`.)

**Why this is mandatory**: the user maintains `assets/shared/clientlogo/` as a
versioned, growing library shared across all decks. Old per-deck `input/`
copies go stale; `assets/` root pollution makes the brand asset surface
unmaintainable. Single source of truth = `assets/shared/clientlogo/`.

### Digital employee portraits (mandatory) — TWO source folders

**Decision rule (apply in order):**

1. **Named, specific persona** (睿睿 / 参参 / 探探 / 呆呆 / 图图 the 5 内部
   AI 助手, or any task-specific persona like 门店 FFDI 营运助手 / 销售知识
   助手) → portrait MUST come from `assets/shared/mydigitalemployee/<name>.png`.

2. **Anonymous / generic AI agent slot** (e.g. P33 row "门店巡检" of
   品牌X — the row needs a digital-employee face but no specific named
   persona is assigned) → portrait MUST come from
   `assets/shared/digital_employee_avatars_50/NN_<traits>.png` (50-portrait
   generic library, diverse demographics, named by index +
   ethnic/style traits like `01_east_asian_woman_white_shirt.png`).
   Use them in numerical order or pick by visual fit; do not duplicate
   on the same slide.

**Where portraits do NOT belong**:

- ❌ `assets/shared/clientlogo/` — that's customer brand logos, not agents.
- ❌ `assets/` root — reserved for framework (feishu-deck CSS/JS) +
  lark master brand (logo / cover bg / slogan) only.
- ❌ `runs/<ts>/input/` — input is per-run, ephemeral; portraits are
  cross-deck shared assets.
- ❌ Generated CSS gradient placeholder (gray circle) when the slide
  REALLY needs a face — pick a generic from `digital_employee_avatars_50/`
  instead.

**Folder structure**:

```
assets/shared/
├── mydigitalemployee/              — user's OWN named personas
│   ├── 睿睿.png                     — AI 汇报复盘助手
│   ├── 参参.png                     — AI 故事线参谋
│   ├── 探探.png                     — AI 客户调研助手
│   ├── 呆呆.png                     — AI Demo 素材助手
│   ├── 图图.png                     — AI PPT 插画助手
│   ├── 门店FFDI营运助手.png
│   ├── 采购选品小助手.png
│   ├── 销售知识助手.png
│   └── … (extend as new named personas appear)
└── digital_employee_avatars_50/    — 50-portrait generic library
    ├── 01_east_asian_woman_white_shirt.png
    ├── 03_southeast_asian_man_hoodie.png
    ├── 05_african_man_beard_polo.png
    └── … (45+ diverse portraits, gaps in numbering OK)
```

Native circular crop (transparent PNG, 160–230 px square typical), so a
plain `background-image` + `border-radius: 50%` renders cleanly.

**HTML embed pattern**:

```html
<!-- Named persona (睿睿/参参/etc.) — use mydigitalemployee/ -->
<div class="avatar"
     style="background-image: url('../assets/shared/mydigitalemployee/睿睿.png');
            background-position: center; background-size: cover; border-radius: 50%;"
     role="img" aria-label="睿睿"></div>

<!-- Anonymous slot — use digital_employee_avatars_50/ -->
<div class="avatar"
     style="background-image: url('../assets/shared/digital_employee_avatars_50/01_east_asian_woman_white_shirt.png');
            background-position: center; background-size: cover; border-radius: 50%;"
     role="img" aria-label=""></div>
```

**Lookup workflow** (every time a slide references a persona):

```bash
# Step 1: try named persona first
ls ~/.claude/skills/feishu-deck-h5/assets/shared/mydigitalemployee/ | grep -i "<name>"

# Step 2: if no named match, fall back to generic library
ls ~/.claude/skills/feishu-deck-h5/assets/shared/digital_employee_avatars_50/ | head
```

If named persona exists → use `mydigitalemployee/`. If the slide just
needs a generic AI-agent face (no specific name) → use
`digital_employee_avatars_50/`. **Do NOT** generate a gradient
placeholder, **do NOT** crop from input/, **do NOT** save to
`assets/` root.

**Why this is mandatory**: the user maintains both folders as
versioned, growing libraries shared across decks (P25 / P26 / P27 /
P29 / P33 / P41 reference these portraits). The historical mistake of
saving the same avatar in three places (input/, assets/ root,
clientlogo/) led to drift and broken refs. **Single source of truth**:
named → `mydigitalemployee/`, generic → `digital_employee_avatars_50/`.

### Interactive demo / phone mockup spec (mandatory) — when a slide animates a chat / app

Some slides need a **live H5 demo** in place of a screenshot or GIF
(e.g. P20 海底捞大明白 chat,product-launch reels,onboarding flows).
Native CSS animations beat GIFs for these reasons: fully crisp at any
projector size,can be paused / toggled,inherit deck typography, and
the deck file stays self-contained without large binary blobs.

**Anatomy of a phone-mockup demo:**

```
.phone (the device shell)
├── ::before (notch / dynamic island — solid #11141c rounded rect, top center)
├── .ph-status (battery / signal / clock — flex 0 0 50px)
├── .ph-bar (app nav: back ‹ + badge + title + more — flex 0 0 52px)
├── .ph-tabs (in-app tab strip if applicable)
├── .ph-divider (e.g. 新话题 thin separator)
├── .ph-chat (flex: 1 — scrollable / animated content area)
│   └── .ph-chat-inner (the actual messages; can `transform: translateY()` to scroll)
├── .ph-foot-ribbon (e.g. 新话题 button)
├── .ph-input (the text field row)
└── .ph-tools (the emoji / @ / mic / image / Aa / + tool row)
```

**Phone shell — bezel via ring shadows, NEVER `box-shadow` with offset:**

R12 forbids real drop shadows. Build the bezel as concentric rings
(`box-shadow: 0 0 0 Npx <color>`),which the validator allows:

```css
.phone {
  width: 380px; height: 780px;
  background: #f6f6f6;
  border-radius: 46px;
  box-shadow: 0 0 0 10px #11141c,         /* 内圈黑 bezel */
              0 0 0 11px #2c3142,         /* 外圈一圈 1px 高光 */
              inset 0 0 0 1px rgba(0,0,0,0.04);  /* 屏内 hairline */
  overflow: hidden;
  display: flex; flex-direction: column;
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC",
               var(--fs-font-cjk);
}
```

NEVER use `box-shadow: 0 20px 56px ...` for "depth" — it's a real drop
shadow and R12 fails it. Outer rings only.

**Match the platform — iOS-flavor or 飞书-flavor or 企微-flavor:**

If the user gives you a reference screenshot (e.g. they drop a
`参考飞书交互样式.png` in `input/`), **read it pixel-by-pixel** and
match:

- Status bar font weight / color
- Notch/island shape and dimensions
- Nav bar back arrow style (chevron `‹` not arrow `←`)
- Tab strip underline color/width (e.g. 飞书 = blue `#3370FF`,3px,
  centered under active label)
- Bubble corner radii (asymmetric: `4px 14px 14px 14px` for "from
  this side")
- Bubble fill (bot = `#fff` border `rgba(0,0,0,0.04)`,user-side
  飞书 = `#DCEDFF`)
- Avatar gradient direction (135deg)
- Robot tag color (`#FFE7B0` bg + `#B87600` text in 飞书)
- Tool bar icon stroke width (1.8 in 飞书)

When in doubt, pick the user's reference over your imagination.

**Animation timing — looping demo, 12–14s typical:**

```
0.3s  · welcome / opening message
1.4s  · user msg 1
2.6s  · user msg 2
3.8s  · typing dots in
5.0s  · typing dots out + bot reply 1 in
6.0s  · input field starts typing user q3
8.4s  · field clears, user q3 message appears in chat
9.4s  · typing dots 2 in
10.8s · typing dots 2 out + bot reply 2 in
12.0s · pause / hold final state
14.0s · loop (animation re-fires)
```

`.ph-chat-inner` should `transform: translateY()` upward in the second
half of the loop so the early messages naturally scroll out of view —
matches how a real chat behaves when 5+ messages exceed the visible
area.

**Animation patterns to keep:**

```css
@keyframes msg-in  { from { opacity: 0; transform: translateY(8px);} to { opacity: 1; transform: translateY(0);} }
@keyframes msg-out { to { opacity: 0; height: 0; padding: 0; margin: 0;} }      /* for typing dots退场 */
@keyframes dot-pulse { 0%,60%,100% { opacity:.3; transform: translateY(0);} 30% { opacity:1; transform: translateY(-3px);} }
@keyframes type-in   { to { max-width: 86%; } }                   /* steps(N, end) for terminal-style */
@keyframes caret-blink { to { opacity: 0; } }                     /* steps(2) for hard blink */
```

Stagger via individual `animation-delay` on each `.msg.mN` selector
rather than `nth-child` — gives you absolute control and survives
DOM reordering.

**Typography floors apply identically inside the phone:**

- Bubble body text: ≥ 14 px (chrome floor — phone screens are visually
  smaller, so 14 px in mockup ≈ 22 px on the slide it lives in)
- Bubble lead / title (e.g. "你好,我是 \<bot name\>"): ≥ 16 px
- Status bar / tabs / nav bar: ≥ 14 px
- DON'T fall below 14 px even though the mockup looks like a real
  phone — the validator counts these as slide content,not chrome,
  so R06 still applies.

**No emoji, no real shadows, all icons via SVG:**

```html
<!-- Status bar wifi/battery: SVG, never 📶 🔋 (R05 fail) -->
<svg viewBox="0 0 16 12" width="16" height="12" fill="currentColor">...</svg>

<!-- Tool icons (emoji 😀 / @ / mic / image / Aa / +): SVG -->
<span class="tool"><svg viewBox="0 0 24 24">...</svg></span>
```

**Pause-on-hover (optional but recommended):**

```css
.phone:hover .ph-chat-inner,
.phone:hover .msg { animation-play-state: paused; }
```

Lets a presenter hover on the demo to freeze the animation mid-flow
during Q&A.

**When to use a phone demo vs a static screenshot:**

| Use phone demo | Use static screenshot |
|---|---|
| Showing a flow / conversation / progressive UI | Showing a single screen state |
| Highlighting an interaction beat (typing, sending, switching skill) | Listing app features statically |
| Replacing a low-res GIF | Showing exact production pixel art |
| Reference image is high-fidelity & faithful copy is feasible | Reference is too dense to recreate (full dashboards / tables) |

If the source is a 3-second video or a 10-frame GIF, a CSS demo
almost always wins. If the source is a 2000×1200 dashboard packed
with data, just use the screenshot — `<img>` it with `max-width: native`.

---

## Phase 1.c extras — parity contract + regression smoke test (mandatory)

There are TWO tiers of layouts in this skill:

- **Original 10–13 layouts** — `cover / agenda / section / content-3up /
  content-2col / quote / stats(row,hero) / big-stat / image-text / table /
  flow(timeline,process) / end`. CSS in `assets/feishu-deck.css`. Fully
  parity'd with master spec (header position, content-bg, R48 centering,
  etc.). Battle-tested via sample-deck.json + phase-1a/1b demos.

- **Phase 1.c extras** (added after the original set) — `content-before-after /
  content-blocks / content-matrix / content-story-case / flow-tree /
  flow-swim / stats-waterfall / arch-stack / logo-wall / replica`. CSS in
  `deck-json/templates/extra-layouts.css`. Most use brand-new `data-layout`
  values (`matrix-2x2`, `issue-tree`, `flow-swim`, `waterfall`, `arch-stack`,
  `logo-wall`, `content-before-after`); a few reuse original `data-layout`
  values (`content-blocks → content-2col`, `content-story-case → content-2col`,
  `replica → image-text`).

### Why this section exists

Audit 2026-05-21 found that ALL 7 new-`data-layout` extras shipped without:

- `.header` positioning (titles dropped into flow → stuck top-left of slide)
- Slide background image (looked unbranded vs originals' dark ambient bg)
- Default centering (no R48 equivalent)
- Multiple hero-context label floor violations (16 px chrome on axis names /
  industry tags / row headers that are actually content — should be ≥ 24)

The gap existed for ~3 weeks unnoticed because **zero examples used any of
the 7 new layouts**. sample-deck + phase-1a/1b demos all stopped at the
original 13. Without an example exercising the extras, validator-pass said
nothing about visual correctness.

### The contract (mandatory when adding a new layout)

**Three steps. Skip any one and the layout WILL ship with bugs:**

1. **CSS rules in `extra-layouts.css`**. Add `.slide[data-layout="X"]`
   selectors to the unified `.header`, present-mode bg, and scroll-mode
   bg lists at the **top of file** (the "Framework parity" block).
   Then write the layout-specific rules.

2. **Add a slide to `deck-json/examples/phase-1c-extras.json`** exercising
   the new layout with realistic content (≥ minimum schema fields,
   meaningful labels not just "lorem ipsum"). This is the regression deck.

3. **Render the regression deck + eyeball every slide**:
   ```bash
   python3 skills/feishu-deck-h5/deck-json/render-deck.py \
     skills/feishu-deck-h5/deck-json/examples/phase-1c-extras.json \
     skills/feishu-deck-h5/deck-json/examples/phase-1c-extras-out/
   ```
   Open `phase-1c-extras-out/index.html` and visually verify:
   - Title sits at master coords (top:61, left:73), not at slide top
   - Background is dark ambient gradient, not flat black
   - Content fills stage, no large empty regions stranded at top/bottom
   - Labels next to hero-anchor content are ≥ 24 px (Body tier), not 16 px
   - Horizontal/vertical alignment looks deliberate (no off-by-N misalignment)

### Other gotchas surfaced 2026-05-21

- **CSS var URL resolution across files**: `var(--fs-asset-content-bg)`
  is defined in feishu-deck.css with `url("lark-content-bg.jpg")`. When
  used inside a `background:` declaration in extra-layouts.css (different
  file), the URL may NOT resolve correctly in some browser engines (spec
  says relative to declaration site, but practice varies). Workaround:
  use direct relative URLs in extra-layouts.css —
  `background: #000 url("../../assets/lark-content-bg.jpg") center/cover no-repeat;`
  — instead of `var(--fs-asset-content-bg)`.

- **Waterfall label area must be padding-reserved, not flex-stacked**:
  if `.label` and `.sublabel` sit in `.bar`'s flex flow, bars with vs
  without sublabel get DIFFERENT label-area heights, so col bottoms
  misalign across bars ("柱子不在一个平面"). Pattern that works:
  - `.bar { padding-bottom: 96px; justify-content: end; }` — reserves
    fixed area at bottom for label, pushes col flush against it
  - `.label / .sublabel { position: absolute; bottom: <fixed>; }` —
    anchor labels to bar bottom inside the padding zone, decoupled
    from flex flow
  - X-axis line `.chart::after { bottom: 96px; }` — same offset as
    `.bar { padding-bottom }`, so axis aligns to col bottoms
  - `.chart` MUST NOT also set its own `padding-bottom` — the bar's
    padding-bottom is the only reservation; chart adding more
    double-counts and the axis floats below col bottoms.

- **Issue-tree connector lines**: the renderer NEVER injects the SVG
  the schema description promises. CSS pseudo-elements draw lines
  instead: `.connector::before` (vertical trunk, `top:25% bottom:25%`),
  `.connector::after` (root→trunk horizontal stub), `.branch::before`
  (trunk→b1 stub), plus matching trio on `.b1-conn` and `.leaf::before`
  for branch→leaves fork. Works for 2-branch / 2-leaf shapes; 3+ needs
  either renderer-side measurement OR a smarter CSS calc.

- **Replica mode is intentionally chrome-less**: no title, no stage
  content, no wordmark — just a full-bleed page image. If the example
  page_image is a small logo PNG instead of a real PDF page, the slide
  looks "empty" (small image floating). Use a placeholder that
  self-documents — see `replica-placeholder.svg` in examples/.

### 2026-05-21 fix batch (history)

If you see one of these patterns on a Phase 1.c layout, it's likely
fixed already — search extra-layouts.css comments for `2026-05-21`:

| Layout | What was wrong | Where it lived |
|---|---|---|
| All 7 extras | `.header` no positioning | feishu-deck.css unified rule hardcoded 8 names |
| All 7 extras | Background unset in present-mode | Same — slide-frame `:has()` list hardcoded |
| matrix-2x2 | axis names / labels / quadrant titles at 16 chrome | Should be 24-28 (Body / Sub tiers) |
| story-case | industry-tag at 16 chrome | Content categorization, → 24 Body |
| story-case | `.story-arc .lbl` (痛点/冲突/etc.) at 16 | Content row header, → 24 Body (widen column 88→120) |
| logo-wall | ind-name at 16 chrome | Industry label is content, → 24 (widen column 200→280) |
| waterfall | col bottoms misaligned across bars | Mixed-sublabel-presence; absolute-position label/sublabel |
| waterfall | X-axis floated above/below col bottom | Chart had double `padding-bottom` |
| waterfall | footnote rendered at slide top | No `.slide[data-layout="waterfall"] .footnote` positioning rule |
| issue-tree | Connector lines absent | Schema said renderer injects SVG; renderer didn't. CSS pseudo-element workaround |
| flow-swim | Lane names had thin colored border + dark bg | User asked for full-color tinted fill (gradient brand→0.75) |
| replica | "完全看不见内容" smoke test | Placeholder was tiny logo PNG; replaced with self-documenting SVG mock |

### 2026-05-22 fix batch — raw-layout stage geometry + silent text clip

Three related framework gaps surfaced together while building a dense 3-up
narrative slide (`taste-shifts-3pains`). Codify them so the next author
doesn't re-discover.

**Gap 1 — `.stage` default is 680 tall, NOT slide-full (1080)**:

Framework's `.slide .stage` for content layouts is sized to leave room for
header + footer chrome. Internal measurement: stage clientHeight = 680.
This means any `.stage > .grid { position: absolute; top:X; bottom:Y }`
positioning is **relative to a 680 px stage**, not the 1080 px slide.

For raw layouts (`layout: "raw"` + `_orig_layout: "content-*"`) that want
near-full-slide layouts (header overlay + big content + bottom band),
you MUST explicitly override stage to fill the slide:

```css
.slide[data-slide-key='X'] .stage {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  padding: 0;
}
```

Otherwise your grid coordinates measure off the wrong reference, and
"top:140 bottom:170" gives a 370 px grid instead of the expected 770 px.
You won't see this from static CSS — render and measure `clientHeight`.

**Gap 2 — `R-VIS-CARD-OVERFLOW` audit (added 2026-05-22)**:

Cards with `overflow: hidden` that have `scrollHeight > clientHeight` are
**silently clipping content**. Static validator sees nothing wrong (the
card itself fits in canvas; R-OVERFLOW is slide-level only). User sees
text mysteriously cut off.

Added `R-VIS-CARD-OVERFLOW` to `validate.py` visual audit JS — walks every
`.stage *` element, checks `getComputedStyle().overflow{,Y} === 'hidden'`
+ `scrollHeight > clientHeight + 4 px tolerance`. Reports selector +
overflow delta. Fires on the deck rendered with Playwright.

Run via `python3 render-deck.py deck.json out/ --visual` (the flag is new
too — see Gap 3) or `bash check-only.sh out/index.html --visual`.

Fix when triggered: shorten body copy, drop a row, shrink padding/gap,
or **drop `overflow: hidden`** so the issue is at least VISIBLE rather
than silently swallowed.

**Gap 3 — `render-deck.py --visual` flag (added 2026-05-22)**:

Previously `render-deck.py` always ran static validator with `--no-visual`
hardcoded. To get visual audits you had to manually chain
`check-only.sh --visual` after each render — easy to forget, and the
silent-clip bugs accumulated.

Now `render-deck.py deck.json out/ --visual` runs static + visual in
one shot (~2 s overhead for typical 5-10 slide decks). For dense decks
authored with raw layouts especially, **always render with `--visual`
on the last iteration** before delivery.

**Authoring pattern — flex column with `justify-content: center` is the default**:

The cleanest raw-layout pattern for "header + content + bottom band"
when content is shorter than available stage height:

```css
.stage {
  position: absolute; top: 130px; left: 48px; right: 48px; bottom: 32px;
  display: flex; flex-direction: column;
  gap: 28px;                    /* spacing between flow blocks */
  justify-content: center;      /* DEFAULT — center the group vertically */
}
.stage > .grid { position: static; display: grid; ... }
.stage > .anchor-band { position: static; ... }
```

Children flow naturally. Cards size to content. Anchor sits right
below grid with `gap: 28` spacing. **`justify-content: center` is the
right default** — the whole content group (grid + anchor) centers
vertically in the stage, with equal breathing room above and below.

**Why `flex-start` is wrong as default**: with `flex-start`, content
hugs top of stage and leaves a big empty band at slide bottom —
visually "stranded" / "top-heavy". The same R48 default-centering
problem that hit fixed-shape layouts (content-3up / content-2col /
agenda / stats / big-stat / quote) applies to flex columns too.

Use `flex-start` ONLY when you have a TALL stage container holding
a sparse top-anchored layout (e.g. one big hero + small footer
intentionally hugging top). For 99% of "header + body + anchor"
cases, `center` is correct.

No absolute-positioning math, no "why is there a 136 px gap"
mystery. flex column with center auto-handles spacing AND placement.

---

## Converting existing material (PDF / HTML / PPT export / docs) into a compliant deck

When the user hands you ANY existing material — a PDF report, an old HTML
deck, an exported PPT screenshot set, a markdown brief, a Google Slides
share — and asks for a "feishu-deck-h5 version", **follow this workflow
exactly**. Skipping any step produces the failure modes the user has
specifically called out before:

- mono-white logo on every page (should be color)
- content slides made with `data-layout="cover"` (wrong; cover has flower bg)
- end page with title + CTA + 4-col contact grid (master spec is slogan only)
- multi-layer header on content pages with eyebrow + title + subtitle
- `<br>` inside content-page titles
- pre-existing watermarks / page numbers carried over
- **silently compressing N source pages into ~M pages** (the "I'll distill 54 → 17 because it's tighter" failure)

### Step 0 · Preserve the page count — DO NOT compress by default

When the user hands you a source deck (PDF / PPT / HTML) and asks for a
"feishu-deck-h5 version" (or any phrasing that means "convert this"),
the **default contract is 1:1 page mapping**:

- N source pages → N HTML slides
- Original section dividers, agenda recap pages, "thank you" closings
  ALL stay as their own slides
- Per-slide content can be UPGRADED (raster UI → `.ui-window` HTML mock,
  flat list → `.scene-grid` / `.north-star-map` / `.kpi-strip`,
  cropped chart → typographic data viz), but information items don't
  drop off
- The deck's narrative pacing (a 3-part agenda revealed gradually,
  the same idea spread over 3 build-up slides) is the user's prior
  editorial choice — preserve it

**Why this is non-negotiable** (rule elevated 2026-05-05 after a 54-page
博裕&星巴克 deck was silently compressed to 17 slides on first attempt;
user reaction: "不要压缩,这种让你基于PDF生成html,要保持页数不变,等于
就是每页仿制和体验升级"):

- The user already did editorial selection on the source. A page
  exists because they decided it earned its slot.
- Section dividers and agenda-recap slides ARE pacing — pulling
  them strips presentation rhythm.
- A single-case page that gets its own slide says "this case
  matters"; lumping 6 cases into one matrix says "these are
  interchangeable." Different message.
- Internal sales decks routinely get presented page-by-page; if
  the agent "distills" the deck, the speaker has lost their map.

**When compression IS appropriate** (opt-in only):
- User explicitly says "精简" / "提炼" / "压成 N 页" / "做执行摘要" /
  "summarize this in N slides".
- User specifies a target page count different from the source.
- User asks for a "one-pager" / "single-page summary" of a multi-page
  source.

In all other cases — convert page-for-page. If the source has 54
pages, the output has 54 slides.

**How to apply (mechanical)**:
1. Inventory source: count pages (`mdls -name kMDItemNumberOfPages`,
   `pdfinfo`, manual scroll). Write down the count.
2. Use `data-screen-label` numbering that matches the source page
   numbers ("01 Cover" through "54 End" for a 54-page source) so
   any reviewer can cross-reference the validator output to the
   original PDF.
3. Per-page upgrade is the goal — not per-deck redesign. Match the
   source's information items, then re-render in feishu-deck-h5
   style.
4. If a source page is genuinely empty (just a logo/transition),
   render it as a transition slide rather than dropping it.

### Step 0.5 · Pick the conversion mode — Replica vs Rewrite

Before deciding HOW to render each page, decide WHICH MODE the
overall conversion uses. There are two:

#### Replica mode (page-as-image · DEFAULT for designed source decks)

Each PDF page is rendered as a high-res JPG and placed in the slide
as a full-bleed `background-image`. feishu-deck-h5 only contributes
the wrapping shell — fullscreen present mode, mobile vertical
browse, keyboard nav, page indicator, URL hash sync. The source's
typography, screenshots, illustrations, color choices are preserved
**byte-for-byte**.

```bash
# Render all pages to JPG (1920px wide, q85 ~= 200-450 KB each)
mkdir -p runs/<ts>/output/pages
pdftoppm -png -scale-to-x 1920 -scale-to-y -1 input.pdf runs/<ts>/output/pages/p
for f in runs/<ts>/output/pages/p-*.png; do
  sips -s format jpeg -s formatOptions 85 "$f" --out "${f%.png}.jpg" >/dev/null
done
rm runs/<ts>/output/pages/p-*.png
```

Slide markup template:

```html
<div class="slide-frame">
  <div class="slide page-replica" data-layout="image-text"
       data-screen-label="01 Cover"
       style="background-image: url('./pages/p-01.jpg')">
    <div class="wordmark"></div>      <!-- DOM present (R07), hidden via CSS -->
  </div>
</div>
```

Required CSS (one block, applies to every slide):

```css
.slide.page-replica {
  background-color: #000 !important;
  background-position: center center !important;
  background-size: contain !important;
  background-repeat: no-repeat !important;
}
/* Source page already carries 飞书 logo — hide our shell wordmark
   so the brand mark doesn't double up. R07 is satisfied because the
   .wordmark DOM element is still present. */
.slide.page-replica .wordmark { display: none; }
```

Validator behaviour:
- **No `data-text-id` annotations** are added (image is the content).
- Validator emits exactly **one T00 warning** ("no data-text-id
  attributes found"). This is **expected for Replica mode** — do
  NOT silence it by adding fake text-ids to images.
- All other rules (R02 / R07 / R48 / etc.) pass on stub conditions.
- `texts.md` is NOT generated for Replica decks (there's no editable
  text leaf to edit — if the user wants copy changes, they re-export
  the source PDF).

#### Rewrite mode (LLM re-authors each page · OPT-IN)

Each page is hand-authored in feishu-deck-h5 native HTML — every
`.ui-window` mock is rebuilt from `.ui-*` primitives, every logo
matrix becomes a `.logo-cell` text grid, every brand palette item
maps to `--fs-*` tokens. Full `data-text-id` + `texts.md` flow is
in scope.

This is the mode the rest of SKILL.md (Steps 1–5, layout recipes,
narrative patterns) describes. It's the right call when:

- The user explicitly says "用飞书原生组件重画 / native HTML /
  redesign / 改造排版 / 不要截图".
- The source is text / markdown / docs / docs export — there are no
  meaningful screenshots to preserve.
- The source is low-resolution / poorly designed / off-brand and
  needs a real redesign.
- The source is a customer-story table row / case-library row — that
  routes to one-pager / Path A / Path B per the existing rules.

#### Default = Replica when source is a designed PDF/PPT

If the user gives you a presentable PDF or PPT (designer-touched
master, brand-aligned, has actual screenshots and product mocks)
and says "convert to feishu-deck-h5 HTML" — DEFAULT TO REPLICA.

Why:
- The user already paid for the design. Rewriting it loses that
  investment AND tends to lose UI screenshots, atmospheric photos,
  and bespoke visualizations that the LLM can't faithfully recreate
  in a single pass.
- "样式变化很大 · 截图都没了" is the most common reaction to a
  Rewrite output when Replica was the right answer.
- Replica is fast (~30 seconds for `pdftoppm` + `sips` + 60 lines
  of HTML), zero token cost, 100% information fidelity.
- The "experience upgrade" the user actually wanted is the SHELL —
  fullscreen present mode, ←/→ nav, mobile reflow, URL hash sync.
  Replica delivers all of that without touching content.

Lesson elevated 2026-05-05 from the 54-page 博裕&星巴克 deck:
first attempt was Rewrite (compressed to 17 slides) — rejected.
Second attempt was Rewrite (1:1 page count) — rejected with "整体
不太行,这种如何尽量模仿之前的内容,很多截图都没有了,样式变化
很大". Third attempt was Replica — accepted.

#### How to decide in 5 seconds

| Source signal | Mode |
|---|---|
| Designer-polished PDF/PPT, has UI screenshots, brand-aligned | **Replica** (default) |
| Markdown / docs / Google Doc / text export | Rewrite |
| Low-res screenshots / off-brand source / "redesign this" | Rewrite |
| Customer story table row, "做这个客户案例" | one-pager (Path A/B) |
| User says "用 native 组件 / 重画 / 升级排版" | Rewrite |
| User says "保持原样 / 模仿原版 / 别动样式" | Replica |

If ambiguous, **ask the user once** before deciding — the rebuild
cost between modes is high, but the question cost is one IM line.

#### Per-page polish mode (4th mode · iterative)

Distinct from Replica / Rewrite / one-pager: this is the iterative
mode where the user reviews each slide individually and gives
focused feedback ("第 N 页改成 X / 字小一点 / 列宽窄一点"), and the
agent ships a **single-slide HTML** per round under
`runs/<ts>/output/single-pages/p-NN.html`. Trigger phrases:

- "一页一页来" / "每页精修" / "一张张做"
- User reviews a slide in isolation and gives detailed visual feedback
- User drops per-page assets ("这一页的 logo / 截图我放在 input/")

In this mode, **the source PDF/PPT title is verbatim** — every
character, every punctuation mark, every parenthetical note must
reach the HTML unchanged. The agent's licence is to redo BUILD
(layout / typography / decoration), not COPY.

##### Title verbatim — strict rule

In per-page polish mode the slide's `<h2 class="title-zh">` (or
`<h1 class="title">` for hero layouts) MUST mirror the source
title byte-for-byte:

- **Don't drop characters** — "飞书对博裕资本及星巴克价值" can't
  be compressed to "飞书对博裕及星巴克价值". The 资本 stays.
- **Don't add characters** — "AI原生组织" (no space between AI
  and CJK) stays exactly that. Don't insert " AI " spaces by
  reflex.
- **Don't swap punctuation** — full-width "：" (chinese colon)
  / "；" (semicolon) / "（）" (parens) stay full-width. Don't
  replace with "·" or ":" by reflex.
- **Keep parenthetical notes** — "字节跳动的全方位AI布局：飞书
  （企业豆包）定位企业级AI入口" — the "（企业豆包）" annotation
  carries a positioning claim ("飞书 = 企业版豆包"); dropping
  it loses information.
- **Subtitles / agenda items / chapter ledes / pill labels are
  also verbatim**. The "title preservation" rule extends to all
  short headings — anything user might re-read aloud.

The ONLY editable text in per-page polish mode is the body copy:
story-hook, feature descriptions, paragraph bodies. Those the agent
may re-organize / compress / expand to fit the new layout. Headings
are off-limits.

##### When the rule is suspended

Only when the user explicitly says one of:
- "标题改成 X" / "把标题压缩"
- "这个标题太长,帮我精简" / "起一个新标题"
- The user is co-authoring the title in dialogue ("我觉得标题改
  「飞书 × 博裕」更直接")

If the source has an obvious typo (e.g. duplicated character),
**flag it to the user** and ask whether to fix; don't fix silently.

##### Self-check before shipping each polish round

Before declaring a single-page p-NN.html done, verify:

```
(1) <h2> innerText === source-page-N title (visual byte-compare)
(2) Punctuation classes match (full-width vs ASCII)
(3) Parenthetical notes / 数字注释 preserved
(4) Subtitles / pill labels / agenda items also verbatim
```

This rule was elevated 2026-05-06 from the 博裕&星巴克 polish
session: P01 "AI原生组织" got "AI 原生组织" (added space), P02
"飞书对博裕资本及星巴克价值" lost 资本, P04 dropped 「（企业豆
包）」. User feedback: "之前PDF的标题默认是不变的,一个字都
不要改". Verbatim-title is the per-page polish mode contract.

### Step 1 · Inventory the source

For every source page, write down:

| Source page | Role identifier | Likely target layout |
|---|---|---|
| Cover / 主标题 / title slide / first big-image page | hero, lots of negative space | `cover` |
| Table of contents / 目录 / agenda / outline | numbered list of sections | `agenda` |
| Section divider / chapter intro / 章节页 / 大序号 | giant numeral + chapter title | `section` |
| 3 parallel concepts / 三大能力 / capabilities triplet | 3 cards in a row | `content-3up` |
| Body text + chart / one narrative + supporting visual | left text, right image/mock | `content-2col` |
| Customer quote / 金句 / executive thesis | single sentence centered | `quote` |
| 4 KPIs in a row / metrics dashboard | numbers + units + labels | `stats` |
| Single hero number with paragraph | one big number, side prose | `big-stat` |
| Full-bleed photo + text | photograph + bottom-left caption | `image-text` |
| Comparison matrix / feature table | rows × columns of text | `table` |
| Roadmap / chronological milestones | linear timeline with stages | `timeline` |
| 3-6 sequential workflow steps | process flow with arrows | `process` |
| Closing / 谢谢 / 封底 / "thank you" | final visual signature | `end` |

If a source page doesn't fit any of these 13, it's almost always a
content page in disguise — most likely `content-3up` or `content-2col`.
Do NOT invent a 14th layout.

### Step 2 · Cover page (`data-layout="cover"`) — MUST follow master spec

The cover is intentionally minimal: **title + initiator name + date,
nothing else**. NO English subtitle, NO team/company line, NO meeting
type label. The cover earns its weight through composition, not text
volume — the right-half flower image carries the atmosphere.

| Element | Spec |
|---|---|
| Background | `lark-cover-bg.jpg` (the master flower image — NOT a solid color, NOT a gradient invented on the fly) |
| Logo | top-LEFT at (120, 113), size 235×74, **COLORED** tri-petal `--fs-asset-logo` |
| Title | left-half only (max-width 884px), 100/700, can be 1-2 lines (hero allowed `<br>`) |
| Subtitle | **NONE** (no EN translation, no marketing tagline — drop it; if you really need a sentence, put it on slide 02) |
| Author block | left-side at top:720 (2026-05-06 · was 803, moved up to sit ~215px below a 2-line title so name+date read as part of the title block, not a separate stack). Two stacked spans separated by `<br>`: line 1 = the **initiator's personal name** (the meeting host / deck owner / report author — NOT a team / department / role title); line 2 = the date (`YYYY.MM.DD`). |
| Footer chrome | NONE (retired 2026-05; pager UI shows page number) |
| Eyebrow | NONE |

```html
<div class="slide" data-layout="cover" data-screen-label="01 Cover">
  <div class="wordmark">飞书</div>
  <div class="stage">
    <h1 class="title title-zh" data-text-id="slide-01.title">〔主标题 — can wrap with &lt;br&gt;〕</h1>
  </div>
  <div class="author">
    <span data-text-id="slide-01.author">〔发起人名字〕</span><br>
    <span data-text-id="slide-01.date">〔YYYY.MM.DD〕</span>
  </div>
</div>
```

**Why the minimalism is non-negotiable** (this rule was elevated from
user feedback after a 2026-Q2 deck):

- An EN subtitle on every cover reads like marketing copy — clients
  who only need an internal summary find it noisy.
- A team line ("飞书企业服务团队") is generic; an actual person's name
  ("杰森" / "FuQiang") tells the reader who to push back to.
- The cover is a hero composition; the less text it carries, the more
  the title and the flower image can breathe.

If the user explicitly asks for an English subtitle on a particular
deck (e.g. for a bilingual external pitch), allow it — but the
default authoring behavior is "no subtitle" unless asked.

### Step 3 · Every content page — title-only header + colored top-right logo

```html
<div class="slide" data-layout="content-3up" data-screen-label="04 Content">
  <div class="wordmark">飞书</div>           ← top-RIGHT, COLORED, 160×50 (auto from CSS)
  <div class="header">
    <h2 class="title-zh">〔Source title — single line, no &lt;br&gt;〕</h2>
  </div>
  <!-- body content (.grid / .flow / .nodes / .table-wrap / etc.) -->
</div>
```

What you MUST drop from the source:
- Eyebrow / kicker text above the title (R56)
- Subtitle / lead text below the title
- Inline page numbers anywhere — page numbers are entirely retired from per-slide DOM (the present-mode pager handles them)
- Source page numbers in any other position
- Decorative breadcrumbs / "you are here" indicators
- Watermarks
- Explicit `<br>` inside content-page title (R13). If the source title is long, drop the `<br>` and let it wrap naturally — DO NOT shorten or truncate; the title is content, preserve verbatim
- Emoji, `!`, `…`, `???` — strip without asking (R05)

What you MUST preserve:
- Atmospheric backgrounds via `data-decor` (e.g. violet-glow on Digital
  Workforce / AI pages — see "Preserve atmospheric / decorative
  backgrounds when re-rendering")
- System UI / app screenshots → recreate as HTML using `.ui-*` primitives,
  NOT as raster images (UI1)
- Photographic backgrounds → use `data-decor="photo-bg"` with `style="--photo: url(...)"`

#### Typography — 4-tier strict for content pages (mandatory, 2026-05-16)

**The math**: PPT 16:9 canvas is 13.33" × 7.5". 1pt = 1/72". Web canvas
1920×1080 ⇒ 1920 ÷ 13.33 ≈ 144 dpi ⇒ **1pt ≈ 2px**. Standard
consulting-deck PPT sizes map cleanly:

| Tier | PPT (pt) | Web (px) | Role |
|---|---|---|---|
| Title | 18–24 | **48** | Action Title — the headline conclusion on a content slide |
| Sub | 14 | **28** | Subtitle / column-title / lede (optional tier) |
| Body | 10–12 | **24** | Paragraphs, list items, table cells, captions |
| Foot | 8 | **16** | Footnote, eyebrow, pill, tag, attrib, source, page metadata |

**Hard rule**: every CONTENT slide uses **only these four sizes**. The
hierarchy ratio (48 / 24 = 2.0×, 24 / 16 = 1.5×) is what makes the
deck read crisply from 5 m back.

##### What's a "content page" vs a "hero exception"

| Type | Tier system | Examples |
|---|---|---|
| **Content** (80% of slides) | 4-tier strict | content-3up · content-2col · stats · table · timeline · process · agenda body · scene-grid · north-star-map · the body of EVERY content slide |
| **Hero exception** (≤20%) | Master-spec values, OUT of 4-tier | cover hero title (100) · section chapter-num (160) · section H2 (88) · big-stat number (132+) · quote blockquote (88) · end slogan PNG |

Hero exceptions appear ONLY in their respective layouts and ONLY for
the explicit hero element. Everything ELSE on those slides (cover
author, section lede, big-stat caption, etc.) still uses the 4-tier.

##### CSS variables for 4-tier (framework provides them)

```css
:root {
  --fs-title: 48px;   /* Action Title */
  --fs-sub:   28px;   /* Subtitle (optional) */
  --fs-body:  24px;   /* Body copy */
  --fs-foot:  16px;   /* Footnote / chrome */
}
```

Author CSS in per-page `<style>` blocks should prefer the variables
over hardcoded px:

```css
[data-page="03"] .slide .card-title { font: 700 var(--fs-title) / 1.2 var(--fs-font-cjk); }
[data-page="03"] .slide .card-body  { font: 500 var(--fs-body)  / 1.5 var(--fs-font-cjk); }
```

Plain `font-size: 48px` is fine too — the validator accepts both forms.

##### Enforced by validator R06 + R20

- **R06 chrome floor**: any content-page selector that doesn't match a
  body class (chrome / pill / tag / foot / eyebrow / attrib / source /
  pageno / `.ui-*` mockup / etc.) must be ≥ 16 px. Below 16 → error.
- **R06 body floor**: any selector matching body classes (`.cbody` /
  `.body` / `.desc` / `.sub` / `.lede` / `.paragraph` / `.caption` /
  `.feat-body` / `.dir-desc` / `.sc-obj` / `.sc-lever` / `.arch-item` /
  `.arch-base` / `.principle` / `.voice-card` / `.cta-box` / `.who` /
  `.col-text` / `.page-sub` / `.subtitle` / `.ts-tasks` / etc.) must be
  ≥ 24 px. Below 24 → error.
- **R20 type-tier ladder**: every `font-size` in a `[data-page="NN"]`
  scoped CSS rule must be exactly one of `{16, 24, 28, 48}`. Anything
  else fails as `R20 off-tier`. Framework CSS (feishu-deck.css) is
  exempt — its hero rules (88/100/132/160) come from master spec.

##### Opt-outs (sparingly, document why)

- `/* allow:typescale */` — full exemption from R06 + R20. Use for:
  1. Hero exceptions in per-page CSS (cover 100, section 88/160,
     big-stat 132+, quote 88+ when authored per-page).
  2. Mockup-internal text inside `.ui-window` / `.ui-doc` simulations
     (10–13 px to look "small inside a real-size app").
- `/* allow:body-floor */` — exempt this specific rule from R06's
  body floor only. Extremely rare.
- `/* allow:white-opacity */` — exempt from R-WHITE-TEXT (unrelated
  but lives in the same opt-out family).

##### Common drift to recognize and fix

The 4-tier is so simple that drift is obvious. If you find yourself
typing any of these px values in per-page CSS, you're off-tier:

```
DRIFT          → SNAP TO
  14, 18, 20   → 16 (chrome / pill / tag) or 24 (body)
  22           → 24 (body floor, was OLD value, bumped 2026-05-16)
  26, 30, 32   → 28 (sub)
  36, 38, 40   → 48 (title)
  44, 52, 56   → 48 (title)
```

**Why this strict regime**:
- Hierarchy reads instantly when there are 4 size values, not 8 or 12.
  48 / 24 / 28 / 16 gives 2× / 1.16× / 1.5× ratios — the eye picks
  up "this is a title, that is a body" pre-attentively. Sub-tier
  drift (5 sizes between 28 and 18) blurs the boundaries.
- Pre-2026-05-16 the skill ran an 8-rung ladder (10/14/18/22/28/38/44/
  52/56/64/88/100/132/160). Every deck had 8–12 distinct sizes. Users
  consistently flagged "层次不够突出" and "字还是小". The 4-tier collapses
  that range into the 4 spec values.

##### Postmortems (kept for context — pre-2026-05-16 sizing)

- **P32**: 5+ iterations because elements were sized 16 / 22 / 24
  ad-hoc. The eye read 22 / 24 / 28 as "three slightly different
  sub-titles" rather than one consistent rhythm. Under 4-tier
  this can't happen — only 24 exists in the body range.
- **20260505 P03/P06**: timeline events at 17 / 18 / 15 (below body
  floor AND off-ladder); market-card text at 24 / 16 / 16. The 4-tier
  ladder makes the "snap" choice trivial: 24 for body content, 16
  for chrome.

#### Goldilocks zones — decorative elements have only TWO safe sizes (2026-05-16)

Decorative elements (large numerals, display markers, eyebrow indices
like "01 / 05") that AREN'T semantic content must sit in one of two
safe size zones, NEVER in the middle.

For a slide with Title at 48 px:

| Element size | Zone | Outcome |
|---|---|---|
| ≥ 86 px (1.8× Title) | **Hero zone** | "I'm decoration, not text" — reads as visual marker |
| 24–48 px (0.5–1.0×) | **Muddled middle** ⚠️ | Eye can't tell — looks like a wannabe-title that's too small |
| ≤ 19 px (0.4× Title) | **Chrome zone** | "I'm an index / aux info" — reads as eyebrow / footnote |

**Don't sit in 50–80% of the title size.** A decorative numeral at
24, 28, 32, 38, 40 next to a 48 title looks "stuck" — neither
clearly Hero nor clearly Chrome.

**Concrete rule for decorative numerals**:
- Big-numeral-overview cards (like Pattern N, 5-up overview): use
  ≥ 88 px (Hero exception, requires `/* allow:typescale */`).
- Eyebrow-style "N of 5" markers: use **16 (Foot)** as the framework
  `.content-tag` or the new `.column-pill` would in their default.

**Postmortem (20260516 南区周会 slide 1)**: hero numerals iterated
88 → 64 → 16 → 28 → 24 → 88 over 6 rounds. Every middle value
"looked stuck"; user kept saying either "too small" (24) or "too
big" (88) depending on which way they were leaving from. The
Goldilocks rule formalizes this: don't even TRY the middle.

#### Content-context label floor — labels in content cards NEVER get 16 chrome (2026-05-17, broadened 2026-05-23)

When a card / panel contains **any content-tier text (≥ 28 px Sub
tier or above)**, every **content label** in the same card must be
**≥ 24 (Body tier)**. The 16 (Foot / chrome) tier is reserved for
page-level metadata ONLY (reached via `.header` / `.footer` /
`.source-footer` / `.pageno` / `.wordmark` ancestor).

**Broadened 2026-05-23**: originally the rule required a 48 px hero
anchor inside the card. Empirically (PROMPTS.md corpus: 85 "字小"
complaints across 8 decks), users complained equally about chrome
labels in cards that had only a 28-44 Sub-tier anchor (e.g.
`story-case .industry-tag`, `logo-wall .ind-name`,
`script-card .card-num`). Lowered anchor threshold from 48 → 28
(any content-tier text in the card triggers the floor).

| Element role | Tier | Examples |
|---|---|---|
| Hero anchor | 48+ | Hero numeral, big-stat number, display title |
| Sub anchor | 28-44 | Story-hook, card title, scene name, action title |
| Content label (introduces a value) | **24 Body MIN** | "北极星" / "核心售卖" / "交付" / "触达" / "已读" / "个性化对象" / "痛点 / 冲突 / 解法" / "时间维度" / "剧本 01" |
| Page-level chrome | 16 Foot | `.pageno` / `.source` / `.footnote` / `.copyright` / `.attrib` (REQUIRES `.header` / `.footer` ancestor — chrome class inside content card still flags) |

**Why this rule exists** (showcase eval 2026-05-17):

When a card looks like `[88 hero][48 title][24 body][16 label]`,
the 16 label DISAPPEARS — the reader's eye locks onto 88+48+24 as
the content rhythm and treats 16 as noise (or skips it entirely).
On 1920×1080 projectors at 4-5m viewing distance, 16 px CJK is
~3 mm tall — below the threshold for casual scanning.

The fix is NOT to bump 16 → 18 / 20 (still off-tier AND still too
small). The fix is to **promote the label to 24 Body** so it joins
the readable rhythm. If the visual hierarchy worry is "now the
label is the same size as the value below it", use **font-weight
700** or **brand color** to differentiate — those are free hierarchy
levers that don't require shrinking the font.

**Concrete examples from showcase iteration**:

- ❌ `.ns-card .star-label` at 16 (gray) next to `.star` at 24 (white):
  the field name "北极星" reads as throwaway; reader doesn't know
  what "门店坪效" IS. FIX → `.star-label` 24 brand-bold, `.star` 24
  white-regular. Same size, hierarchy via weight + color.
- ❌ `.stats .trend` at 16 chrome ("触达") above the 88 hero number:
  the eyebrow vanishes; viewers see "3 秒" but can't tell it's
  about reach time vs ROI vs decision time. FIX → `.trend` 24
  brand-bold.
- ❌ `.scene-card .sc-label` at 16 chrome ("个性化对象") above the
  24 body value: same disappearing-label problem. FIX → 24.
- ❌ `.evolution-chip .stage-tag` at 16 ("现阶段" / "未来"): readers
  can't anchor the two-row evolution. FIX → 24 brand-bold.

**Decision tree before sizing any label**:
1. Is this label IN a card that has a hero anchor (≥48 element)?
   → YES: minimum 24 (Body). Use weight + color for differentiation.
   → NO: 16 (Foot) is OK if it's true page chrome.
2. Is this label INTRODUCING content the reader needs to understand?
   → YES: 24 minimum. Without the label, the value is orphan.
   → NO (purely decorative numbering, page footer, source line): 16.

**Postmortem (20260517 showcase eval)**: 7 of the user's 10
complaints in slides 6/9/14/16/17/22/24 reduced to this single
rule. Until codified, every per-page CSS that used 16 for a
content-label produced "字小了" feedback even though the slide
passed the 4-tier ladder and body-floor checks.

#### Card density — title-size depends on cards-per-page (2026-05-16)

When you author N parallel cards on a slide, the per-card title size
must scale DOWN as N grows. A 48px Title on 4 cards reads decisively;
the same 48px on 8 cards crowds the canvas and the cards lose visual
breathing room.

| Cards per slide | Card title tier | Why |
|---|---|---|
| ≤ 4 cards | **48 (Title)** | Plenty of horizontal room per card; 48 is decisive |
| 5–6 cards | 28–48 (author judges) | Depends on card aspect ratio. Wide cards still fit 48; narrow drops to 28 |
| ≥ 7 cards | **28 (Sub)** | 48 titles make the page feel "full"; 28 is the right rhythm for dense grids |

When in doubt with 5–6 cards: shrink to 28, OR shrink the card count
by consolidating related items. Don't keep 48 and add cards.

**Postmortem (20260516 南区周会 slide 8)**: 8 todos rendered with 48
titles in a 4×2 grid → cards visually fought each other, user flagged
"太满 / 拥挤". Dropping titles to 28 (Sub) fixed it without losing
content.

#### Nested grids must replicate the parent's column ratio (mandatory)

When a region (e.g. `bottom-cta`, a strip of CTA pills) sits *underneath*
a 2-column main grid and is supposed to align with those columns, its
internal `grid-template-columns` MUST replicate the parent's ratio AND
gap, not default to `1fr 1fr; gap: 24px`.

```css
/* parent stage */
.stage {
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.05fr);
  column-gap: 36px;
}

/* ✅ CORRECT — child grid copies parent's ratio + gap */
.bottom-cta {
  grid-column: 1 / -1;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1.05fr);
  column-gap: 36px;
}

/* ❌ WRONG — child re-invents 1fr 1fr; split line ≠ parent's */
.bottom-cta {
  grid-column: 1 / -1;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}
```

Why: the user's design rule is "right-side elements (lede, report-mock,
right-CTA) all share the same left edge — the 96 px-derived right
column line". With unequal column ratios (1fr vs 1.05fr) the split line
is at ~52 % of stage width, not 50 %. A nested 1fr/1fr CTA strip places
its split at 50 %, leaving the right pill ~14 px misaligned vs the
report-mock's left edge.

The same rule applies to ANY nested grid that visually overlaps the
parent's columns: footer toolbars, KPI strips spanning two columns,
gallery rows under a 2-col content area. If the child doesn't need to
align (e.g. bottom-cta is intentionally a 3-equal-pill strip), this
rule doesn't apply — but say so explicitly with a comment.

**Postmortem**: P32 right CTA pill kept misaligning by ~14 px under
the report-mock. Root cause: parent stage was 1fr/1.05fr but
bottom-cta was 1fr/1fr. Fixed by replicating the ratio.

#### Color contrast floor — body text on dark slides MUST be white (mandatory)

The brand background is dark (~ #080C18). Pure white `#fff` reads
crisp; gray text vanishes when projected. **All semantic body text
(card titles, sub-headings, descriptions, large numerals, captions,
list items) on dark slides MUST be `#fff` or `rgba(255,255,255,0.95)+`
— not the lower-opacity gray tokens.** Specifically, **stop using
these for body text:**

- ❌ `var(--fs-text-72)` / `rgba(255,255,255,0.72)`
- ❌ `var(--fs-text-78)` / `rgba(255,255,255,0.78)`
- ❌ `var(--fs-text-65)` / `rgba(255,255,255,0.65)`
- ❌ `rgba(255,255,255,0.55)` (large numerals shouldn't fade either)

Use them ONLY for:
- True chrome / metadata (page no., footnote disclaimer, axis labels — not body)
- Decorative atmosphere (subtle outlines, dim background hints)
- Disabled/inactive states (mute pills, secondary tabs)

**Rule of thumb:** if the text is *information the audience must
read* — title, sub-head, description, big number, caption under
a screenshot, key data label — it goes to `#fff`. If it's *decoration
or chrome* — fade is OK, but never apply fade to anything carrying
meaning.

This applies regardless of font size and is independent of the
typography floor above. (A 22 px gray description is still
unreadable on a projector. The fix is white, not bigger.)

#### No nested frames — max ONE visible card boundary per content unit (mandatory)

When authoring per-page CSS, **do not stack three layers of bordered
boxes inside each other**. A "frame" is any element with both
`border` (or `box-shadow` ring) AND a fill color/`background`.
Triple-nesting reads as "boxes in boxes" and is the #1 reason
single-page polish slides feel cluttered.

**Counted as 1 frame each:**

- An outer `canvas` / `panel` wrapper card (border + fill).
- A `step-card` / `feat-card` / `dir-card` (border + fill).
- A `mini-ui` mock or a `chart-frame` (border + fill).
- A `factor-chip` / `tag` (border + fill counts as a frame too,
  but small chips are usually OK if their parent is a flat row,
  not another card).

**The cap is 2 visible frame layers max** for any vertical pixel of
the slide. Three or more is forbidden:

```
✗ stage → canvas-frame → step-card → mini-ui     (3 frames — fail)
✗ outer-card → inner-item → icon-bg-tile          (3 frames — fail)
```

**How to fix when you find yourself nesting:**

- **Drop the outer wrapper.** If `canvas-frame` only exists to draw a
  border around step-cards, delete it and put the step-cards directly
  on the slide background.
- **Replace the inner with a hairline.** If you need to subdivide a
  card, use a 1px section divider or a section colored bar (e.g.
  `border-top: 2px solid var(--fs-violet)`) instead of a fully
  bordered sub-card.
- **Section-color the parent, kill the child border.** E.g. the parent
  card's left edge is a 4px violet bar, and the inner content sits
  flat with just text + spacing — no inner card.
- **Use background tone, not borders.** A slightly-lighter rectangular
  block inside a card (no border) signals grouping without adding a
  frame.

Chips, pills, and tag rows that themselves have borders are allowed
inside a card (1 card + N chips = still counted as 2 frame layers
total, since the chips don't nest into a third level).

#### Sibling frames — merge into one card when they're a single content unit (mandatory)

The "no nested frames" rule above covers VERTICAL nesting. This rule
covers a different failure mode: **two stacked sibling frames that
together represent one content unit**. Common case:

```
┌─────────────────────────┐   ← floating pill (frame 1)
│  传统模式: 业务提需求     │
└─────────────────────────┘
┌─────────────────────────┐   ← bullet card (frame 2)
│  · IT 团队: ...          │
│  · 业务团队: ...         │
└─────────────────────────┘
```

Even though they're not nested, the "mode card" is conceptually ONE
unit (header label + supporting body), and rendering it as **two
independent bordered boxes stacked vertically** reads as visually
fragmented. Default to merging into a single frame:

```
┌─────────────────────────┐   ← single frame
│ 传统模式: 业务提需求       │   ← header section (color-block top)
├─────────────────────────┤
│ · IT 团队: ...           │   ← body section
│ · 业务团队: ...          │
└─────────────────────────┘
```

**Decision rule** — before splitting into 2 sibling frames, ask:

> "Does this header label make sense WITHOUT its supporting body?"

If the answer is "no" (e.g., "传统模式" is meaningless without the
bullets explaining what it means), merge them. Use a `1px solid` divider
or a `border-bottom` on the header section instead of two separate
borders. The header gets a stronger fill (gradient / accent) to
visually differentiate it within the merged card.

**Common merge patterns:**

```css
/* parent: single frame */
.mode-card {
  border: 1.5px solid <accent>;
  border-radius: 18px;
  overflow: hidden;     /* clip header gradient at radius */
  background: <body-bg>;
}
/* header section: differentiated bg, NO independent border */
.mode-card .head {
  padding: 16px 26px;
  background: <accent-fill>;
  border-bottom: 1px solid <hairline>;
  text-align: center;
}
/* body section: shares parent border, just padding */
.mode-card .body {
  padding: 22px 28px;
}
```

**When 2 sibling frames ARE OK** — when the two are independent
content units (e.g., a "metric card" and a "trend card" stacked, where
each can stand alone), they SHOULD have their own frames. The rule is
about merging frames for ONE conceptual unit, not about banning
vertical card stacks in general.

**Postmortem**: P35 v2 had a floating mode-head pill + a separately
bordered mode-list card per side. Header pill made no sense without
the bullets it labeled — they were one unit. Merging into a single
mode-card with header-section + body-section eliminated 2 of the
4 visible frames on the page (one per side) and the page felt
visibly more substantial / less cluttered, with no information loss.

#### Reserved class names — do NOT redefine in per-page `<style>` (mandatory)

`feishu-deck.css` ships several **global utility classes** scoped at
`.slide .<name>`. Authoring a per-page `<style>` block that defines a
selector with the same class name causes hard-to-debug visual
collisions — the global rule wins on specificity for properties you
didn't override, so your custom container gets force-shrunk /
force-positioned in ways that look broken without an obvious cause.

**Reserved class names (search `feishu-deck.css` before reusing any
short common name; this list grows over time):**

| Class | Built-in behaviour |
|---|---|
| `.tile` | **64×64 icon tile** with `display: grid; place-items: center` (background tinted by `--fs-accent`). If you author `.tile { display: grid; grid-template-columns: 160px 1fr; padding: 12px 18px; ... }`, the 64×64 width/height wins, your padding is clipped, and inner CJK text wraps to one char per line. |
| `.pill` | Generic pill chrome with padding + border-radius. |
| `.eyebrow` | Uppercase Latin tracked label. |
| `.keyline` | 96×3 keyline accent bar. |
| `.title-zh` / `.title-en` / `.title` | Bilingual title typography. |
| `.wordmark` | Top-right 飞书 logo container. |
| `.stage` / `.header` / `.footer` | Slide structural shells. |
| `.deck` / `.slide` / `.slide-frame` | Top-level deck shell. |
| `.deck-progress` / `.deck-controls` | Present-mode chrome. |

**Convention for custom containers**: prefix per-page classes with a
2–4 char scope tag matching the slide topic, e.g. `.kpi-tile` (not
`.tile`), `.case-card` (not `.card`), `.qa-pill` (not `.pill`),
`.report-toc` (already scoped under `.report-mock`).

**Symptom catalog** to recognize collisions early:
- Custom container collapses to 64×64 → you used `.tile`.
- Padding ignored / borders missing → check `.pill` / `.eyebrow`
  collision.
- Text wraps to one CJK character per line inside what should be a
  wide row → almost always `.tile` collision (the 64px width forces
  the column to be 1-CJK-glyph wide).

**Postmortem**: P29 量化成效 KPI strip broke this rule three iterations
in a row — the local `.tile { display:grid; grid-template-columns:160px 1fr; }`
got overruled by the global `.slide .tile { width:64px; height:64px; }`,
producing 3 empty 64×64 boxes with vertically-stacked CJK labels
spilling out to the right. Renaming to `.kpi-tile` fixed it
immediately. If you see a layout that "looks like the rule didn't
apply", grep `feishu-deck.css` for your class name FIRST.

#### Bar chart · X-axis alignment & in-chart brand logos (mandatory)

When a slide has a bar chart with brand logos under each bar (e.g. P07
万店时代 timeline, P29 quality-check store list), three rules apply:

**1. X-axis baseline must touch bar bottoms · zero gap**

The chart's X-axis line (`::after` pseudo) and the bar `<div class="fill">`
bottom must sit at the *same Y pixel*. The standard pattern:

```css
.store-chart {
  position: relative;
  display: flex; flex-direction: column;          /* MANDATORY · see note below */
  padding: 24px 60px <LABEL_AREA_HEIGHT>px 80px;  /* leave bottom space for logo+brand+date */
  min-height: 540px;
}
/* X-axis line — sits exactly at the top of the label area = bar bottoms */
.store-chart::after {
  content: ''; position: absolute;
  left: 60px; right: 32px;
  bottom: <LABEL_AREA_HEIGHT>px;       /* MUST equal padding-bottom */
  height: 1px;
  background: linear-gradient(90deg, rgba(60,127,255,0.55), rgba(60,127,255,0.10));
}
.store-bars {
  display: grid; grid-template-columns: repeat(N, 1fr);
  align-items: end;                     /* bars sit on container bottom */
  padding: 0 24px 0 16px;               /* padding-bottom: 0 — bars touch baseline */
  flex: 1;                              /* MANDATORY · fills chart content area top-to-bottom */
  min-height: 0;                        /* allow flex to override default content sizing */
}
.store-bar .fill {
  /* heights via .h-XXXX classes; no margin-bottom — flush to bars-container bottom */
}
```

**The `flex: column` + `flex: 1` pair is mandatory, not decorative.**
Without it, `.store-bars`'s natural height = max bar height (e.g. 260 px).
The chart `min-height: 540px` minus `padding-top + padding-bottom`
(174 px) leaves **366 px content area** — but `.store-bars` only fills
260 px of that, so it floats 106 px above the chart's content-area
bottom. Meanwhile `::after { bottom: <LABEL_AREA> }` is anchored to
the chart's content-area bottom. Result: **X-axis line sits 100+ px
below the bars** and the chart looks broken. Forcing `.store-bars`
to `flex: 1` makes it span the full chart content area so its
`align-items: end` baseline lines up exactly with `::after`.

**Forbidden**: any `padding-bottom > 0` on `.store-bars`, or any
`bottom != LABEL_AREA_HEIGHT` on `.store-chart::after`, or omitting
the chart `flex: column` / bars `flex: 1` pair. All of these produce
a visible gap between the X-axis line and the bars and instantly look
amateur.

**2. Brand logo placement: BELOW the X-axis line, not on top of bars**

Logos go in `.label-wrap` absolutely positioned `top: calc(100% + 14px)`
relative to `.store-bar`. Since `.store-bar`'s bottom = bars-container
bottom = X-axis line, this puts the logo card 14 px below the X-axis.

The label area should contain (in vertical order): **logo · brand name
· optional `hq-tag` · date**. Bar count `<span class="count">` goes
ABOVE the bar (not in the label-wrap).

**3. Brand logos MUST preserve aspect ratio · NO circular frames for
non-square logos**

The frequent failure mode: developers default to a 56×56 round avatar
frame with `background-size: 80% 80%` or `cover`, which **stretches**
horizontal logos (`美宜佳`, `沪上阿姨`) into a vertical box. Don't.

**Standard pattern**:

```css
.store-bar .logo {
  width: 96px; height: 44px;            /* rectangular card, ~2.2:1 ratio */
  border-radius: 6px;
  background-color: #fff;
  background-position: center;
  background-size: contain;             /* mandatory — preserves aspect ratio */
  background-repeat: no-repeat;
  padding: 4px;
  border: 1px solid rgba(255,255,255,0.20);
}
.store-bar.is-hero .logo { border: 2px solid var(--fs-blue); }
```

`background-size: contain` is **mandatory** for any logo container with
mixed-aspect-ratio logos (any chart with both wide and square brands).
Use circles ONLY when every logo in the set is verifiably square (logo
files in `clientlogo/` cropped 1:1) — otherwise rectangles.

**Hero callout**: don't use a glow `box-shadow: 0 0 16px ...` on hero
logo — that's a R12 real drop shadow. Use a colored `border` or a
`0 0 0 2px ring` shadow.

### Step 4 · End page (`data-layout="end"`) — MUST follow master spec

The 飞书 master closing is intentionally minimal: flower background +
colored logo top-left + slogan PNG. **No title. No CTA. No contact
grid.** Optional contact line allowed.

| Element | Spec |
|---|---|
| Background | `lark-cover-bg.jpg` (same as cover) |
| Logo | top-LEFT at (120, 121), COLORED, 235×74 |
| Slogan | `lark-slogan.png` ("先进团队 先用飞书") at (102, 348), 561×345 |
| Contact line | optional, bottom-left at top:80 |
| Title / CTA / contact grid | NONE (off-master, do not add) |
| Footer | NONE |

```html
<div class="slide" data-layout="end" data-screen-label="13 End">
  <div class="wordmark">飞书</div>
  <div class="slogan" role="img" aria-label="先进团队 先用飞书"></div>
  <!-- optional, off-master -->
  <div class="contact">contact@feishu.cn  ·  feishu.cn</div>
</div>
```

If the source has CTA pills / contact grids and you really need to keep
them, break with the master and document the deviation in the deck's
opening comment. Default = stay with the master.

### Step 5 · Run the validator BEFORE responding

```bash
bash build.sh --inline
python3 assets/validate.py examples/sample-deck.html --strict
python3 assets/validate.py examples/sample-deck-inline.html --strict
```

All four must exit 0. If any check fails (R49 cyan-as-accent, L1 mono
logo, R13 br-in-title, R56 eyebrow-in-header, P50 base64 budget),
**fix the markup, don't suppress the check**.

### Common conversion mistakes (forbidden)

| Mistake | Why it's wrong | What to do instead |
|---|---|---|
| Use `data-layout="cover"` for an internal "agenda" or "section" page | Cover layout has the flower background and left-half text positioning that doesn't suit an agenda | Use `agenda` or `section` |
| Use mono-white logo on content pages | Mono is opt-in for over-imagery edge cases only (L1) | Use the default colored logo |
| Explicit `<br>` inside content-page `<h2>` | Forbidden by R13 | Drop the `<br>`. If the title is long, let it wrap naturally to 2 lines via CSS word-break — DO NOT shorten, truncate, or add ellipsis. The title is content; preserve it verbatim. Browser handles CJK word-break automatically. |
| Add eyebrow above content page title | Forbidden by R56 | Drop the eyebrow; if context is essential, work it into the title or move it to the slide body |
| Re-use source page numbers verbatim in the title area | Footer/pageno retired 2026-05 — page numbers come from the pager UI in present mode | Drop the inline page no.; if you need an editorial label like "07 / 12", do it as a hand-placed `.eyebrow` or `.callout` once per deck, not standardized chrome |
| Inline raster screenshots of 飞书 UI as `<img>` | Forbidden by UI1 | Recreate using `.ui-window / .ui-grid / .ui-list / .ui-msg` etc. |
| Use cyan as a slide accent | Forbidden by R49 (cyan = inline highlight only) | Pick blue / teal / purple / violet / orange instead |
| Free-style `font-size` like 16 / 17 / 19 / 20 / 24 / 26 / 30 / 32 / 36 / 40 / 48 / 72 / 96 in per-page CSS | Forbidden by R20 modular type-scale | Pick from {14, 18, 22, 28, 38, 44, 52, 56, 64, 88, 100, 132, 160}. Body content ≥ 22. If master truly says exactly 96 px, add `/* allow:typescale */` in the rule and document why |

---

## EDITING DISCIPLINE (mandatory) — high-cost bugs to avoid

These four failure modes recurred in the 2026-05-14 CTG run and burned
30+ minutes of debug time each. Read this section BEFORE doing any
delete-slide / insert-slide / reorder-slide / custom-layout work.

### E1. Identifier sync on delete/insert — what's mandatory vs conditional

A slide can carry up to three numeric identifiers, at different DOM levels:

| Identifier | Lives on | Status | Used for |
|---|---|---|---|
| `data-screen-label="NN Title"` | `.slide` element | **mandatory** | present-mode pager UI label; validator R02 requires it |
| `data-text-id="slide-NN.field"` | every text leaf | **mandatory if texts.md sidecar exists** | links HTML → texts.md (T01–T03) |
| `data-page="NN"` | `.slide-frame` wrapper | **conditional — only when the slide has per-page scoped CSS** | per-page `[data-page="07"] .card { ... }` overrides authored in the deck's inline `<style>` |

The first two are always required (validator enforces). `data-page`
is **purely a CSS-scoping handle** the author opts into when they need
per-page overrides — most Path A (template-rendered) slides don't have
it at all (Opple deck: 0/51 frames carry `data-page`; CTG deck: 36/53
have it because that deck has heavy per-page custom CSS).

**Renumber ritual on delete / insert / reorder** — only update the
identifiers that EXIST on the affected slides:

1. Decide the new ordinal map (e.g. inserting at position 7 → all
   positions ≥ 7 shift +1).
2. **Always** — update `data-screen-label="NN Title"` on every affected
   `.slide`.
3. **Always (if texts.md exists)** — update `data-text-id="slide-NN.field"`
   on every affected text leaf, and the matching `## slide-NN` headers
   in `texts.md`. Use Edit's `replace_all` carefully — scope to the
   affected slide's markup, not the whole file.
4. **Only if `data-page="NN"` is on the affected `.slide-frame`** —
   renumber it too, AND grep for `[data-page="OLDNN"]` selectors in the
   deck's `<style>` blocks and renumber those to match. Skipping this
   leaves per-page CSS attached to the wrong frame (this is the bug
   that gave "第三页样式不对" in the 2026-05-14 CTG run; the slide had
   `data-page="03"` plus a `[data-page="03"] .card { … }` rule, and the
   renumber missed the frame attribute, so the rule fired on the wrong
   page after the delete).
5. Run `python3 assets/validate.py runs/<ts>/output/index.html` —
   R-DOM catches missing `</div>`, T03 catches texts.md drift, R20
   catches per-page CSS that's off the type-scale ladder.

**The deck on disk is your source of truth** for which identifiers
each slide carries — there is no "every slide MUST have data-page"
rule; it's purely conditional on whether per-page CSS exists.

If you find this ritual error-prone, prefer rewriting the slide list
end-to-end (regenerate with fresh ordinals 01..NN) rather than splicing
in place. The validator's R-DOM rule catches the most catastrophic case
(slide-frame nesting from regex-eaten `</div>`); the identifier sync
is editorial — only you can do it right.

### E2. Don't use sed / regex / text substitution to edit slide-frames

Three separate bugs in the CTG run came from using Python regex to splice
HTML for slide insertion / deletion / column-content rotation:

- `(<div class="slide-frame"...)` matched mid-frame instead of frame-start
  because the regex didn't anchor to the `<div ` token boundary. Result:
  insertion landed inside an existing slide-frame, nesting 7 subsequent
  frames inside it. Present mode hid them all (they never became "current").
- `</[a-zA-Z]+>` was the close-tag pattern used in a column-content
  rotation. It correctly closes `</span>` and `</p>` but does NOT match
  `</h3>` (HTML allows digits in tag names; `[a-zA-Z]+` excludes them).
  Result: regex consumed past the h3 and ate the entire next column's
  markup until it found a `</span>` further down.
- Plain text replacement of "第一段" → "新内容" stripped a closing `</div>`
  that lived inside the matched span.

**Rule**: do not use regex / sed / plain text replacement to manipulate
slide DOM structure. For editorial text changes use `apply-texts.py`
(parses by `data-text-id`, position-safe). For structural changes
(insert / delete / move slide), do it by reading the file, identifying
the slide blocks manually, and writing back the full sequence.

**Safety net**: after every structural change, run validator R-DOM
(`audit_dom_integrity` in `validate.py`). It catches the catastrophic
nesting case automatically — every `.slide-frame` must be a direct
child of `.deck`, every frame must hold exactly one `.slide`, and
`<div>` opens must balance closes inside `<body>`. A structural API
helper (`assets/dom-ops.py`) may be added later if the rule proves
insufficient on its own; until then, R-DOM IS the structural defense.

### E3. Custom-layout selectors have lower specificity than framework defaults

Every framework `.slide[data-layout="..."] .grid { ... }` rule has
specificity `(0,2,0)` — one class + one attribute = 2 classes equivalent.
A naively-written custom layout `.slide-vs-wecom .grid { ... }` has
specificity `(0,2,0)` too — same level — but loses the cascade to the
framework because the framework rule was DECLARED LATER.

**Failure mode**: author writes `<div class="slide slide-vs-wecom"
data-layout="content-3up">` and defines `.slide-vs-wecom .grid {
display: flex; gap: 64px }`. Framework rule
`.slide[data-layout="content-3up"] .grid { display: grid;
grid-template-columns: 1fr 1fr 1fr; ... }` wins. The flex layout
silently doesn't apply. Content overflows 1080.

**Three ways to authoring around it**, in order of preference:

1. **Bump specificity by combining classes**: write
   `.slide.slide-vs-wecom .grid { ... }` (specificity `(0,3,0)`) — wins
   over the framework's `(0,2,0)` cleanly.
2. **Use `!important` on the directional / structural properties** —
   `display: flex !important; flex-direction: row !important;` — works
   but pollutes; reserve for layout direction, NOT for cosmetic values.
3. **Use absolute positioning** for the children of your custom layout
   instead of flex/grid. Specificity matters less when each child has
   its own `position: absolute; top: ...; left: ...`.

Watch out for the related trap: don't name your custom class with a
reserved framework class name (`.tile`, `.pill`, `.card`, `.eyebrow`,
`.keyline`, `.title-zh`, `.wordmark`, `.stage`, `.header`, `.footer`,
`.deck`, `.slide`, `.slide-frame`). See "Reserved class names" section
for the full list — collisions cause force-shrink and other surprise
behavior beyond just specificity.

### E4. Pre-delivery R06 / R20 enforcement is NOT optional

The validator already enforces:
- **R06** — body text ≥ 22 px on slide content; chrome ≥ 14 px.
- **R20** — every `font-size` in per-page `<style>` blocks must come from
  the modular type-scale ladder `{10, 11, 12, 13, 14, 18, 22, 28, 38,
  44, 52, 56, 64, 88, 100, 132, 160}`.
- **R-WHITE-TEXT** — content text on dark slides must be `#fff`, never
  `rgba(255,255,255,X<1)`. Low-opacity white reads as gray when
  projected.

These rules existed before the CTG run, but they were violated **at
least 4 times** in that run because the agent wrote inline `<style>` and
shipped without re-validating. Users had to flag the under-floor fonts
every single time.

**Workflow rule for the agent**:

After every Edit that touches CSS inside a `<style>` block of the deck —
especially per-page `<style data-page="NN">` blocks — IMMEDIATELY run:

```bash
python3 assets/validate.py runs/<ts>/output/index.html
```

Don't wait until "final delivery". Don't trust visual eyeballing for
font-size rules — what looks fine on a desktop preview vanishes on a
projector. R06 / R20 / R-WHITE-TEXT exist exactly because human
judgment fails on these consistently.

Treat each violation as a delivery blocker. If you write 16 px because
you think it fits, the rule still rejects — fix to 14 (chrome) or 18
(pill) or 22 (body), not 16.

### E5. Delete an element → rebalance the rest in the same pass (mandatory)

When the user says "删 X" / "去掉 Y" / "Z 不要了",**the task is two
operations, not one**: (1) remove the element, AND (2) rebalance the
surrounding layout so the deleted slot doesn't leave a visible hole.
Validator PASS ≠ visually balanced. Shipping a "successfully deleted"
deck with a giant blank in the middle is failure, even if every R-rule
passes.

**Why this is mandatory** (user feedback 2026-05-22 · slide 15 after
deleting the closing block + the flow-row + the subtitle):

> "这么改完中间太空了,这个你不觉得难看么?为什么要这样设计,之后别这样了"

The agent had treated "delete the closing 3-line block" as a textual
removal and shipped without checking that the remaining `.ttl-block +
.preface + .dept-grid` now top-aligned with a half-screen blank below.
The `dept-grid { flex: 1 }` did fill the space, but each card's interior
content (5 short children + `margin-top: auto` on `.card-stuck`) only
filled ~60% of the now-taller card → ugly empty middles in every card.

Three deletion symptoms that ALWAYS need rebalancing:

| Symptom of recent deletion | Rebalance action |
|---|---|
| `.stage` flex-column lost a child → top-aligned remainder with bottom blank | Add `justify-content: center` (or `space-between`) on `.stage` so the remaining group sits visually centered, not stuck-top. Reference: R48 default centering. |
| Grid row was occupied by deleted element → leftover row stretch grew the rest | Either shrink `grid-template-rows` to match the new row count, OR drop `flex: 1` on the grid so it sizes to content + center it in `.stage`. Reference: BF3 stretch overshoot. |
| Card had N fields with `margin-top: auto` on one (pushing it to bottom); now N-1 fields | Drop `margin-top: auto`, change card to `justify-content: space-between`. The auto-margin trick assumes a specific child count; deleting breaks the assumption. Reference: BF9. |
| Subtitle deleted, title now alone at top | Either bump title font (36→48), or increase `margin-top` on the title so it sits in the visual upper-third instead of pinned to the top edge. |
| Removed 1-2 cards from a `repeat(N, 1fr)` grid | Drop N by 1 (`repeat(N-1, 1fr)`), don't leave the grid with one stretched orphan cell. |

**Mechanical checklist** (run mentally after every Edit that removes
DOM content):

1. Squint at the slide at 1/3 zoom — is there a visible blank band
   (top, middle, or bottom)?
2. If yes, identify which container houses the blank (stage / grid /
   card).
3. Apply the matching fix from the table above.
4. Re-render. Re-squint. If still blank, repeat.

**Anti-pattern**: delete → render → "完成了 · PASS" → ship. This is the
exact failure mode the user called out. Even if the validator is green,
**you owe a visual rebalance pass**.

**Trigger scope (mandatory — broader than "after delete")**: the squint
check + rebalance flow above must run whenever you touch a slide for
ANY of these reasons:

- You **deleted** DOM content (the original trigger).
- You **edited / fixed / restyled** a slide the user pointed at
  ("这页有问题", "改一下 #NN", "看看 slide NN").
- You **inherited** a slide from another flow / earlier in the session
  / another deck and the user is now asking you to look at it.
- You're about to **deliver / hand off** the deck or any specific page.

Common failure pattern (2026-05-22 · slide 17 NPD-4-stage): a slide
ships with `.acts { flex: 1 }` containing only 3 short act rows →
container stretches, content top-aligns, bottom half empty. The slide
was authored by another flow, not by my edit, so E5's "after delete"
trigger never fired. The user catches "中间还是空着好多内容,刚加的
规则怎么没实现" — they're right. The rule is about **the visual end
state**, not just about who edited last. **If you're looking at a
slide for any reason, you own the squint check**.

The 30-second squint pass is cheap. Shipping a holed-out slide and
being told "你不觉得难看么" is expensive.

**Watch for the inverse trap too**: if the user ADDS content, check
whether the now-fuller layout has the OPPOSITE problem (overflow,
R-VIS-CARD-OVERFLOW, cards too tall to fit). Add and delete are symmetric
— both shift the layout, both need a rebalance check.

---

## ROUND-TRIP INTEGRITY (mandatory) — `deck.json` is the source of truth, never post-render-edit `index.html`

`deck.json` is the canonical spec for a deck's visual state. `index.html` is
a derived artifact — `render-deck.py` regenerates it whenever needed. Any
state that only lives in `index.html` (not in `deck.json`) is **silent drift**
and WILL be destroyed by the next render, fork, or downstream tool that
reads `deck.json`.

### The two halves of the rule

**Half A — Authoring side**: do not post-render-edit `index.html`. All visual
state (CSS, HTML structure, animations, scripts, dev-tools tweaks) MUST go
into `deck.json` — `data.html` for `layout: raw`, or the appropriate
template field for schema layouts. If you iterate quickly in the browser
or paste from dev-tools as an experiment, that is fine — but **port the
change back into `deck.json` before delivery, fork, or library ingest**.

**Half B — Fork / clone / download side**: when you derive a new deck from
an existing one (cp the run folder, clone a slide, install from the
slide-library), **copy BOTH `deck.json` AND `index.html`**, OR run a
parity check first and reconcile drift. If you copy only `deck.json`
because it looks like "the spec", you silently lose every post-render
edit the original author made.

### Why this matters for slide-library ingest

The `feishu-slide-library` skill stores the FULL rendered `source.html`
per deck (intentionally — its CSS, fonts, decoration are shared across
slides). So library ingest itself is safe: animations travel with the
slide because the library ingests `index.html`, not `deck.json`.

The risk is at the AUTHORING boundary BEFORE ingest: if your `index.html`
carries post-render edits that aren't in `deck.json`, and your ingest
pipeline does `finalize.sh` (which re-renders) before submitting, the
freshly rendered HTML will have lost the edits before the library ever
sees them. The library's `--gate ingest` runs `check-only.sh` against
the delivered HTML — it doesn't know about `deck.json`, so it can't
catch this drift on its own. **The deck author owns this check, before
delivery.**

### Detection + recovery

The skill ships `deck-json/sync-index-to-deck.py` for both detection
(dry-run) and recovery (actual sync).

```bash
# Detection — exit 0 with drift report; doesn't mutate
python3 skills/feishu-deck-h5/deck-json/sync-index-to-deck.py \
  <output>/index.html  <output>/deck.json  --dry-run

# Recovery — for each raw slide with drift, extract inner HTML from
# index.html and write back to deck.json data.html. Backs up first.
python3 skills/feishu-deck-h5/deck-json/sync-index-to-deck.py \
  <output>/index.html  <output>/deck.json

# Single slide
python3 ... --slide-key content-pipeline

# Convert template-layout slides (cover/quote/section/iframe-embed/etc) to
# raw to capture post-render edits — LOSSY (drops structured fields). Use
# only when you intentionally need raw to preserve edits.
python3 ... --force
```

**The tool normalizes**:
- Trailing/leading whitespace (some old builder scripts left it in deck.json)
- Asset-path rewrites from `copy-assets.py` (`../input/x` → `input/x`,
  `../../../skills/feishu-deck-h5/assets/x` → `assets/x`) — these are
  expected post-finalize, not drift

**The tool will NOT silently overwrite** non-raw slides (template-rendered:
`cover`, `quote`, `section`, `iframe-embed`, `agenda`, etc.) without
`--force`, because converting them to `raw` loses the structured `data`
fields. Use `--slide-key K --force` to convert one specific slide
when you really do mean to bake post-render edits in.

### Fork checklist (mandatory when deriving a new deck from an existing one)

1. **Copy both files**: `cp -r runs/<src>/output runs/<new>/output` (this
   takes BOTH `deck.json` and `index.html`)
2. **Verify parity**: `python3 .../sync-index-to-deck.py <new>/output/index.html <new>/output/deck.json --dry-run`
3. **If drift detected**: run without `--dry-run` to reconcile. Re-render
   to verify: `python3 .../render-deck.py <new>/output/deck.json <new>/output/`
4. Only THEN start editing the new deck.

If you copied only `deck.json` (skipping step 1's `index.html`), step 2
will report 0 drift but you've already lost the post-render edits from
the source. **You must fork by copying the WHOLE output folder, not
deck.json alone.**

### Postmortem (2026-05-24)

The `kangshifu-ai-lecture` deck was forked from `ai-consumer-growth` by
copying only `deck.json`. Source's `index.html` was ~40 KB larger than
what its own `deck.json` would re-render — those 40 KB were post-render-
edited animations:

- slide 9 `ice-tea-5scripts`: 5 keyframes (`it5-card-in`, `it5-icon-pop`,
  `it5-bar-grow`, `it5-fade-in`, `it5-fade-down`) — 10 animation hits
- slide 10 `content-pipeline`: 10 keyframes (`cp-pipe-flow`,
  `cp-fade-up/down/left/right`, `cp-proc-breathe`, `cp-dot-pulse`,
  `cp-reveal-ltr`, `cp-proc-in`, `cp-r-pop`) — 21 animation hits

The fork inherited animation-less `deck.json`; user noticed in
browser:「这页的动画怎么没有了」. Manual recovery: extract each `.slide`'s
inner HTML from source `index.html`, port back into `deck.json` `data.html`.
~150 lines of one-shot Python. `sync-index-to-deck.py` exists so this is
one CLI invocation next time.

---

## Operational notes (gotchas)

- **`templates/_shell.html` uses `../assets/feishu-deck.css`.** It assumes the
  shell stays one directory deep relative to `assets/`. If you `cp` it to a
  new working directory, fix the relative paths to point at the actual
  `assets/` location, or run `bash build.sh` from the skill root which
  handles the rewrite automatically.
- **`data-decor="flower-bg"` and `"photo-bg"` use `!important` to override
  layout backgrounds.** They REPLACE the layout's default background image —
  intentional, so you can carry the cover atmosphere onto a content page.
  The auto-darkening protection gradient is added on non-cover/non-end
  layouts only (cover and end have their own contrast strategies).
- **CSS rule `.deck[data-mode="scroll"] ~ .deck-ui` relies on `.deck-ui`
  being a later sibling of `.deck`.** `feishu-deck.js` always appends the
  UI to `document.body` so this holds, but if you wrap `.deck` in a parent
  container or insert nodes between `.deck` and `.deck-ui`, the sibling
  selector breaks. The JS belt-and-suspenders `display: none` keeps it
  working in practice — but if you embed the deck inside a custom shell,
  prefer toggling `body.is-scroll` instead.

---

## Quick start (recommended workflow)

1. **Read DESIGN.md** end-to-end. Token names matter — the LLM that generates the deck
   must reference `--fs-*` variables, not hex values.
2. **Open `examples/sample-deck.html` in a browser** to confirm the rendering pipeline
   works on the user's machine. This is the visual ground truth.
3. **Open `templates/_shell.html`**. Copy it to the user's working directory, rename
   to whatever the project is (e.g. `2026-Q1-customer-deck.html`).
4. **Author the slide order**. Sketch the deck arc first, then for each slide:
   - pick a layout from the table below
   - copy the corresponding markup block from `templates/slide-recipes.html`
   - drop it into the shell, fill the placeholders, set `data-screen-label`,
     and increment the footer page number.
5. **Annotate every text leaf with `data-text-id`** as you author markup, and
   emit a paired `texts.md` next to `index.html`. See "TEXT-EDIT SIDECAR"
   above for the ID scheme and format. The user edits `texts.md` to fix
   copy without touching layout.
6. **Run the self-check** (final section of this file). The validator
   enforces the text-id scheme and `texts.md` sync.
7. **Deliver as one HTML file**. Inline the CSS + JS for portability if the user
   wants a single attachment (see "Single-file inlined output" below).
   Tell the user the workflow: edit `texts.md` → run
   `python3 assets/apply-texts.py output/index.html output/texts.md`.

---

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

`templates/_shell.html` provides the canonical structure. Inline gist:

```html
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>〔Deck title〕 · Lark Suite</title>
  <!-- For per-run decks at <repo>/runs/<ts>/output/index.html, the CSS / JS
       path needs to climb three levels then dive into the skill folder: -->
  <link rel="stylesheet" href="../../../skills/feishu-deck-h5/assets/feishu-deck.css">
  <!-- Or inline the css for single-file delivery: see "Single-file inlined output" -->
</head>
<body>
  <div class="deck">
    <div class="slide-frame">
      <div class="slide" data-layout="cover" data-screen-label="01 Cover">
        ... cover markup ...
      </div>
    </div>
    <!-- more <div class="slide-frame"> entries -->
  </div>
  <script src="../../../skills/feishu-deck-h5/assets/feishu-deck.js"></script>
</body>
</html>
```

Do not change the DOM order: `.deck > .slide-frame > .slide`. The runtime relies on it.

---

## Layout recipes (canonical copy-paste markup)

Each recipe below is the exact markup the agent should drop into a `.slide-frame`.
The markup uses only tokens defined in `assets/feishu-deck.css`.

### 1. Cover (`data-layout="cover"`) — matches 飞书 母版 slideLayout1

The cover uses the master flower background (`lark-cover-bg.jpg`) with content positioned on the **left half** (the dark negative space). The color logo sits **top-left** at master coordinates. Title is **100 px / 700** (smaller than you'd expect — that's the master's spec). No eyebrow, no subtitle, no keyline bar, no footer chrome.

The cover is intentionally minimal: **title + initiator's personal name + date, nothing else.** No English subtitle. No team / company / department label. The flower image and the title carry the entire composition. (See "Step 2 · Cover page" above for the full rationale.)

```html
<div class="slide" data-layout="cover" data-screen-label="01 Cover">
  <div class="wordmark">飞书</div>
  <div class="stage">
    <h1 class="title title-zh" data-text-id="slide-01.title">先进团队的<br>工作方式</h1>
  </div>
  <div class="author">
    <span data-text-id="slide-01.author">杰森</span><br>
    <span data-text-id="slide-01.date">2026.04.30</span>
  </div>
</div>
```

Note: cover (and `image-text`, `end`) are HERO_TITLE_LAYOUTS — `<br>` is allowed
inside their titles. The validator (R13) skips `<br>` checking on these three.

Master pixel grid (1920×1080 design canvas):
- Logo top-left: `120, 113` size `235×74` (color logo with petals + 飞书 wordmark — `lark-logo.png`)
- Title: `124, 285`, max-width `884`, font 100/700
- Author block: `124, 720` (2026-05-06 · was 803), font 30/600 — two stacked spans, name on top, date below. Do NOT use `.role` muted prefix on the cover (the date alone is enough chrome).
- Right half: reserved for the flower image — DO NOT place text there.

### 2. Agenda (`data-layout="agenda"`) — vertical pill stack (v2, 2026-05-06)

The agenda layout was rebuilt 2026-05-06 from the v1 TOC-grid into a
**vertical pill stack** matching the 飞书 master 议程页 spec. Three
(or up to ~6) pills stack centered on the canvas. NO header by default —
the pills ARE the content. Each pill carries an italic blue numeral
(01/02/03 …) + a single white title line.

```html
<div class="slide" data-layout="agenda" data-accent="blue" data-screen-label="02 Agenda">
  <div class="wordmark"></div>
  <div class="toc">
    <div class="item"><div class="n">01</div><div class="title-zh" data-text-id="slide-02.item-01">飞书的定位和商业化进展</div></div>
    <div class="item"><div class="n">02</div><div class="title-zh" data-text-id="slide-02.item-02">飞书对博裕及星巴克价值</div></div>
    <div class="item"><div class="n">03</div><div class="title-zh" data-text-id="slide-02.item-03">飞书差异化优势</div></div>
  </div>
</div>
```

#### Recap variant — highlight one item (entering chapter)

When the deck has multiple chapters and you re-show the agenda before
each chapter (a recap page), dim the inactive items and highlight the
active one with `class="is-active"`. The active pill border becomes
teal and the numeral picks up the teal accent.

```html
<div class="item is-dim"><div class="n">01</div><div class="title-zh">飞书的定位和商业化进展</div></div>
<div class="item is-active"><div class="n">02</div><div class="title-zh">飞书对博裕及星巴克价值</div></div>
<div class="item is-dim"><div class="n">03</div><div class="title-zh">飞书差异化优势</div></div>
```

#### Header variant — opt-in `data-variant="with-header"`

If the deck genuinely needs a top header (rare — the pills usually
speak for themselves), opt in with `data-variant="with-header"` on
the `.slide` element. The header reappears at top:96 and the pill
stack shifts down to make room. Default = header hidden.

```html
<div class="slide" data-layout="agenda" data-variant="with-header" data-screen-label="02 Agenda">
  <div class="wordmark"></div>
  <div class="header"><h2 class="title-zh">本次汇报共三个部分</h2></div>
  <div class="toc"><!-- pills --></div>
</div>
```

#### Bilingual opt-in

For ZH+EN bilingual decks, add `<div class="title-en">` next to the
ZH line per item — the CSS renders it as a small EN sub-line below
each pill title. ZH-only is the default per LANGUAGE POLICY.

#### Why the rebuild

The v1 TOC-grid (2-column rows with hairline borders) read as a list,
not a focal divider. The 飞书 master 议程页 uses a single-frame pill
stack centered on a section gradient — visually closer to "here's what
this deck covers, in 3 acts" than "here's a long content list." User
feedback 2026-05-06 ("目录这个布局不好看,改成竖排,参考 PDF 第二页布局")
confirmed the pill style as the new default.

### 3. Section (`data-layout="section"`) — matches 飞书 母版 slideLayout3 一级章节页

Chapter divider. Big numeral with a period (`02.` not `02`), section title below, optional lede + product pills. Master positioning is **160 px** for the numeral (NOT 280) — anything larger gets clipped at the line-box top by `-webkit-background-clip:text`.

```html
<div class="slide" data-layout="section" data-screen-label="03 Section">
  <div class="wordmark">飞书</div>
  <div class="chapter-num">02.</div>
  <h2 class="title title-zh">先进团队的工作方式</h2>
  <p class="lede">即时同步 · 共识对齐 · 闭环交付</p>
  <div class="pills">
    <span class="pill">飞书消息</span>
    <span class="pill">飞书文档</span>
    <span class="pill">飞书多维表格</span>
    <span class="pill">飞书知识库</span>
    <span class="pill">飞书视频会议</span>
  </div>
</div>
```

Master pixel grid (1920×1080):
- Logo: top-right at `1677, 61` (mono-white)
- `.chapter-num`: `126, 271`, font **160/700** (master is 80 pt = 160 px on 1920 canvas)
- `.title`: `126, 447`, font **88/700**
- `.lede`: `126, 597`, font 36/500
- `.pills`: `126, bottom 96` row of ghost pills
- Background: `lark-section-bg.jpg` (cool blue glow on the right edge)

### 4. Content 3-up (`data-layout="content-3up"`)

```html
<div class="slide" data-layout="content-3up" data-accent="blue" data-screen-label="04 Content">
  <div class="wordmark">Lark</div>
  <div class="header">
    <div>
      <div class="eyebrow">CAPABILITIES · 三大能力</div>
      <h2 class="title-zh" style="margin-top:14px">先进团队的<br>三大工作方式</h2>
    </div>
  </div>
  <div class="grid">
    <div class="card">
      <div class="head">
        <div class="tile"><svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></div>
        <div class="num">01</div>
      </div>
      <h3 class="ctitle">即时同步<br>Instant sync</h3>
      <p class="cbody">30 万人组织,一封消息触达全员,3 秒内全部已读。</p>
      <div class="cfoot"><span>MESSENGER · DOCS</span><svg width="20" height="20" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg></div>
    </div>
    <div class="card">
      <div class="head">
        <div class="tile"><svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></div>
        <div class="num">02</div>
      </div>
      <h3 class="ctitle">共识对齐<br>Aligned consensus</h3>
      <p class="cbody">所有讨论沉淀进 Wiki,决策可追溯,新成员第一天就能看到全貌。</p>
      <div class="cfoot"><span>WIKI · BASE</span><svg width="20" height="20" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg></div>
    </div>
    <div class="card">
      <div class="head">
        <div class="tile"><svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg></div>
        <div class="num">03</div>
      </div>
      <h3 class="ctitle">闭环交付<br>Closed-loop delivery</h3>
      <p class="cbody">从需求到上线,流程在 Base 中自动流转,每一步都有责任人和时间戳。</p>
      <div class="cfoot"><span>BASE · MEETINGS</span><svg width="20" height="20" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg></div>
    </div>
  </div>
</div>
```

### 5. Content 2-col (`data-layout="content-2col"`)

```html
<div class="slide" data-layout="content-2col" data-accent="blue" data-screen-label="05 Content">
  <div class="wordmark">Lark</div>
  <div class="header">
    <div>
      <div class="eyebrow">PRODUCT · LARK BASE</div>
      <h2 class="title-zh" style="margin-top:14px">让流程在表格里运转</h2>
    </div>
  </div>
  <div class="grid">
    <div class="col-text">
      <p class="lede">Lark Base 把任务、工单、合同、人员、审批,统一到一个可视化的多维表格。</p>
      <ul class="feature-list">
        <li>看板、甘特、日历、卡片视图,一份数据多种视角。</li>
        <li>关联字段把分散的表打成网,数据不再孤立。</li>
        <li>触发器 + 自动化,把人手 工 操作变成系统行为。</li>
        <li>开放 API,与 ERP、CRM、自研系统双向同步。</li>
      </ul>
    </div>
    <div class="col-visual">
      <!-- 〔TODO drop in product UI screenshot or SVG mock here〕 -->
    </div>
  </div>
</div>
```

### 6. Quote (`data-layout="quote"`)

```html
<div class="slide" data-layout="quote" data-accent="blue" data-screen-label="06 Quote">
  <div class="wordmark">Lark</div>
  <div class="stack">
    <hr class="keyline">
    <blockquote>飞书让 30 万人 <span class="accent-text">像一个团队</span> 一样工作。</blockquote>
    <div class="attrib">某头部互联网公司 · CIO · 2024</div>
  </div>
</div>
```

### 7. Stats (`data-layout="stats"`, accent teal)

```html
<div class="slide" data-layout="stats" data-screen-label="07 Stats">
  <div class="wordmark">Lark</div>
  <div class="header">
    <div>
      <div class="eyebrow">BUSINESS IMPACT · 实测数据</div>
      <h2 class="title-zh" style="margin-top:14px">飞书带来的可量化结果</h2>
    </div>
  </div>
  <div class="grid">
    <div class="col">
      <div class="tile sm"><svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg></div>
      <span class="trend">↑ 触达</span>
      <div class="num">3<span class="unit">秒</span></div>
      <div class="label">30 万人组织全员消息送达时延</div>
      <div class="source">Source · 内部传输实测 2024 Q4</div>
    </div>
    <div class="col">
      <div class="tile sm"><svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg></div>
      <span class="trend">↑ 已读</span>
      <div class="num">98<span class="unit">%</span></div>
      <div class="label">关键通知 30 分钟内已读率</div>
      <div class="source">Source · 12 家头部企业平均</div>
    </div>
    <div class="col">
      <div class="tile sm"><svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg></div>
      <span class="trend">↑ ROI</span>
      <div class="num">3.2<span class="unit">×</span></div>
      <div class="label">部署 12 个月后协同 ROI 中位数</div>
      <div class="source">Source · IDC 2024 商务白皮书</div>
    </div>
    <div class="col">
      <div class="tile sm"><svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg></div>
      <span class="trend">↓ 决策</span>
      <div class="num">&lt;60<span class="unit">秒</span></div>
      <div class="label">关键决策从发起到对齐时长</div>
      <div class="source">Source · 客户访谈 N=24</div>
    </div>
  </div>
  <p class="footnote">数据样本: 12 家中国头部企业,2024 Q3-Q4 实测,口径见附录 A.</p>
</div>
```

### 8. Big stat (`data-layout="big-stat"`)

```html
<div class="slide" data-layout="big-stat" data-accent="blue" data-screen-label="08 Big Stat">
  <div class="wordmark">Lark</div>
  <div class="stage">
    <div class="num">30<span class="unit">万人</span></div>
    <div class="copy">
      <div class="eyebrow">SCALE · 极限规模</div>
      <h2 style="margin-top:14px">单一组织,统一协同</h2>
      <p>飞书的消息、文档、视频会议在 30 万人量级下保持秒级响应,且不依赖私有部署。</p>
    </div>
  </div>
</div>
```

### 9. Image-text (`data-layout="image-text"`)

```html
<div class="slide" data-layout="image-text" data-accent="blue" data-screen-label="09 Image"
     style="background-image:url('〔your-photo.jpg〕');">
  <div class="wordmark">Lark</div>
  <div class="stage">
    <div class="eyebrow">CUSTOMER · 一线场景</div>
    <h2 class="title">现场决策,<br>从未离线</h2>
    <p class="lede">门店、产线、出差、远程,飞书让每一处节点都能即时被看到、被对齐。</p>
  </div>
</div>
```

### 10. Table (`data-layout="table"`)

```html
<div class="slide" data-layout="table" data-accent="blue" data-screen-label="10 Table">
  <div class="wordmark">Lark</div>
  <div class="header">
    <div>
      <div class="eyebrow">COMPARISON · 平台对比</div>
      <h2 class="title-zh" style="margin-top:14px">飞书与传统办公套件</h2>
    </div>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr><th>能力</th><th>飞书 Lark</th><th>传统套件 A</th><th>传统套件 B</th></tr>
      </thead>
      <tbody>
        <tr><td>消息 + 文档 + 表格 + 会议 一体化</td><td>原生集成</td><td>多产品拼接</td><td>多产品拼接</td></tr>
        <tr><td>多维表格 (Base) 自动化</td><td>核心能力</td><td>第三方插件</td><td>不支持</td></tr>
        <tr><td>30 万人级消息触达</td><td>3 秒内全员</td><td>未公开</td><td>未公开</td></tr>
        <tr><td>跨域中英双语支持</td><td>原生</td><td>需配置</td><td>需配置</td></tr>
        <tr><td>开放 API + Webhook</td><td>全量开放</td><td>受限</td><td>受限</td></tr>
      </tbody>
    </table>
  </div>
</div>
```

### 11. Timeline (`data-layout="timeline"`)

```html
<div class="slide" data-layout="timeline" data-accent="blue" data-screen-label="11 Timeline" style="--cols:4">
  <div class="wordmark">Lark</div>
  <div class="header">
    <div>
      <div class="eyebrow">ROADMAP · 部署节奏</div>
      <h2 class="title-zh" style="margin-top:14px">12 周落地路径</h2>
    </div>
  </div>
  <div class="nodes">
    <div class="node"><div class="when">W1-2</div><div class="what">需求蓝图</div><div class="desc">访谈 6 部门, 输出协同地图与目标 KPI。</div></div>
    <div class="node"><div class="when">W3-5</div><div class="what">关键流程上线</div><div class="desc">销售、HR、财务三条核心流在 Base 中先跑通。</div></div>
    <div class="node"><div class="when">W6-8</div><div class="what">全员推广</div><div class="desc">分层培训, 关键岗位 100% 接入, 数据搬迁完成。</div></div>
    <div class="node"><div class="when">W9-12</div><div class="what">数据复盘</div><div class="desc">复盘 KPI, 调整流程, 形成长期治理机制。</div></div>
  </div>
  <div class="axis"></div>
</div>
```

### 12. Process (`data-layout="process"`)

```html
<div class="slide" data-layout="process" data-accent="blue" data-screen-label="12 Process" style="--cols:4">
  <div class="wordmark">Lark</div>
  <div class="header">
    <div>
      <div class="eyebrow">SERVICE · 协同闭环</div>
      <h2 class="title-zh" style="margin-top:14px">需求到交付,四步成型</h2>
    </div>
  </div>
  <div class="flow">
    <div class="step"><div class="stnum">01</div><h3>提出</h3><p>任意一线员工在 Messenger 发起,自动落入 Base 队列。</p></div>
    <div class="step"><div class="stnum">02</div><h3>对齐</h3><p>相关方在 Docs 留痕讨论,关键决策沉淀到 Wiki。</p></div>
    <div class="step"><div class="stnum">03</div><h3>交付</h3><p>负责人在 Base 中流转, 责任人 + 时间戳每一步可追溯。</p></div>
    <div class="step"><div class="stnum">04</div><h3>复盘</h3><p>会后 Meetings 自动生成纪要, 关键指标进入下个周期。</p></div>
  </div>
</div>
```

### 13. End / closing (`data-layout="end"`) — matches 飞书 母版 slideLayout8 封底带 slogan

The master closing is intentionally minimal: same flower background as the cover, the color logo top-left, and the brand slogan **"先进团队 先用飞书"** as a PNG (`lark-slogan.png`). NO title, NO CTA pills, NO contact grid. The slogan IS the message.

```html
<div class="slide" data-layout="end" data-screen-label="13 End">
  <div class="wordmark">飞书</div>
  <div class="slogan" role="img" aria-label="先进团队 先用飞书"></div>
  <!-- optional small contact line — not in the master, but allowed -->
  <div class="contact">contact@feishu.cn  ·  feishu.cn</div>
</div>
```

Master pixel grid:
- Logo top-left: `120, 121` size `235×74` (color)
- Slogan PNG: `102, 348` size `561×345` (loaded from `--fs-asset-slogan`)
- Optional `.contact` line: `124, bottom 80` (off-master but allowed)

If you genuinely need a CTA on the closing (e.g. for an internal pitch where someone asked for it), break with the master and use a pill row — but flag the deviation. Default = stay with the master.

---

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

Most decks have at least one slide where the content is genuinely shorter
than the canvas (e.g. a 3-card recommendation summary, a 3-stat KPI row, a
quote). The default layout should never leave content stranded at the top
of an empty canvas; it should center vertically and let the content take
its natural height.

This applies to **every container layout** that holds a fixed number of
content blocks: `content-3up`, `content-2col`, `agenda`, `process`,
`stats`, `big-stat`, `quote`.

> Note on container naming: the spec uses `.stage` as the canonical inner
> container. This skill's CSS uses historical aliases per layout —
> `.grid` (content-3up / content-2col / stats), `.toc` (agenda),
> `.flow` (process), `.nodes` (timeline), `.stack` (quote), `.stage`
> (big-stat). The validator (`check_default_centering`) accepts ALL of
> these as valid containers when checking for default centering.

Mechanical recipe:

```css
/* WRONG — grid grows to fill canvas, cards top-stack */
.slide[data-layout="content-3up"] .stage {
  display: flex; flex-direction: column;
}
.slide[data-layout="content-3up"] .grid {
  flex: 1;          /* claims all available height; cards stretch tall */
  align-items: stretch;
}

/* RIGHT — stage centers, grid sizes to content */
.slide[data-layout="content-3up"] .stage {
  display: flex; flex-direction: column;
  justify-content: center;  /* center group vertically */
  gap: 28px;                 /* spacing between grid and strap/footer */
}
.slide[data-layout="content-3up"] .grid {
  /* no flex: 1 — content-sized grid */
  align-items: stretch;      /* still equalizes cards to tallest one's content */
}
```

When the content IS dense enough to fill 80%+ of the canvas (e.g. content-3up
with strap + 3 features per card), `justify-content: center` resolves to a
top-aligned visual anyway because the content nearly fills available space.
So this default is **safe both for sparse and dense slides**.

### Counter-rule: when grid SHOULD grow

`pipeline` (Pattern I) explicitly wants the 6-step row to fill vertically so
the rail/dots/cards span the canvas — that layout uses `flex: 1` on `.steps`
deliberately. Don't strip that. The rule is: **only layouts with a fixed
content shape (3-up, 2-col, etc.) center; layouts with a stretched flow
(pipeline, timeline, process) fill.**

### Mechanical audit (extends Rule L2)

```python
def check_default_centering(css):
    """Container-layouts that aren't pipeline/timeline/process should center
    vertically by default."""
    centerable = ('content-3up', 'content-2col', 'agenda', 'stats', 'big-stat', 'quote')
    for layout in centerable:
        m = re.search(rf'\.slide\[data-layout="{layout}"\] \.stage\s*\{{([^}}]*)\}}', css, re.DOTALL)
        if not m: continue
        stage = m.group(1)
        if 'justify-content' not in stage and 'align-content' not in stage:
            yield layout  # missing default centering
```

Block delivery if any layout in `centerable` lacks centering.

The shipped `assets/validate.py` implements this as `audit_default_centering`
(rule **R48**), with the practical extension that it accepts any of
`.stage / .grid / .toc / .flow / .nodes / .stack` as a valid container for
the layout (the spec-canonical name is `.stage`; the historical names are
the per-layout aliases this skill already uses). It also accepts
`align-items: center` and `place-content: center` as equivalent centering
declarations. Functionally identical to the spec, just looser about which
selector name carries the rule.

### Failure mode this catches

User adds a recommendations slide with 3 short cards. Cards stretch to
fill canvas, content stuck at top of each card, big empty bottom across
the slide. User asks "why is there so much empty space?" — agent has to
add centering after the fact. **The default layout should already center.**

---

## Variant override discipline

When a `data-variant` re-skins an existing `data-layout`, the variant CSS does
NOT automatically reset properties from the base layout. CSS cascade only
overrides properties that the variant *explicitly declares*. So if the base
sets `flex-direction: column` and your variant only sets `display: flex`, the
column direction sticks.

**Rule:** when a variant changes the visual structure (row ↔ column,
grid ↔ flex, horizontal ↔ vertical), it MUST explicitly redeclare every
directional / structural property of the layout container — NOT rely on
shorthand or default behavior.

### Concrete recipe — variant flips a column container to row

```css
/* ---- Base layout: vertical stack ---- */
.slide[data-layout="content-2col"] .grid {
  display: flex;
  flex-direction: column;     /* base: vertical */
  align-items: stretch;
  justify-content: flex-start;
  flex-wrap: nowrap;
  gap: 24px;
}

/* ---- Variant: flip to horizontal row — WRONG ---- */
.slide[data-layout="content-2col"][data-variant="horizontal"] .grid {
  display: flex;              /* technically already flex; doesn't help */
  /* flex-direction missing → STILL column from base — bug */
  gap: 36px;
}

/* ---- Variant: flip to horizontal row — CORRECT ---- */
.slide[data-layout="content-2col"][data-variant="horizontal"] .grid {
  display: flex;              /* explicit, even if identical */
  flex-direction: row;        /* MUST redeclare — does not auto-reset */
  align-items: stretch;       /* MUST redeclare — even if value is identical */
  justify-content: flex-start;/* MUST redeclare */
  flex-wrap: nowrap;          /* MUST redeclare */
  gap: 36px;
}
```

### Concrete recipe — variant flips a grid to flex (or vice versa)

When changing layout *engine* (grid → flex, flex → grid), every property
specific to the OLD engine becomes a no-op but doesn't disappear. You must
explicitly null them with `unset` or replace them with the new engine's
equivalents.

```css
/* Base: 3-column grid */
.slide[data-layout="content-3up"] .grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  grid-template-rows: auto;
  align-items: stretch;
  align-content: center;
  gap: 36px;
}

/* Variant: become a horizontal flex row instead — CORRECT */
.slide[data-layout="content-3up"][data-variant="flex-row"] .grid {
  display: flex;                                     /* swap engine */
  grid-template-columns: unset;                      /* null grid-only props */
  grid-template-rows: unset;
  flex-direction: row;                               /* declare flex equivalents */
  align-items: stretch;
  justify-content: center;
  flex-wrap: nowrap;
  gap: 36px;
}
```

### Why "redeclare even if identical"

The cascade is property-level, not declaration-level. If the base has
`align-items: stretch` and the variant doesn't mention `align-items` at all,
the base value sticks — which is usually what you want. But the moment you
later refactor the BASE to `align-items: center`, every variant inherits
that change silently. The bug shows up months later when "just a small base
tweak" cascades into 12 broken variants. Redeclaring all structural props
in the variant makes each variant self-contained and audit-friendly.

### Properties considered "structural / directional"

Any of these properties on a layout container constitutes structure. If
the variant changes ANY of them, it must explicitly redeclare ALL of them:

- `display`
- `flex-direction`, `flex-wrap`, `flex-flow`
- `grid-template-columns`, `grid-template-rows`, `grid-template-areas`,
  `grid-auto-flow`, `grid-auto-columns`, `grid-auto-rows`
- `align-items`, `align-content`, `align-self`, `place-items`, `place-content`
- `justify-items`, `justify-content`, `justify-self`
- `gap`, `row-gap`, `column-gap`

Properties like `padding`, `background`, `color`, `border-radius` are
*cosmetic* — a variant changing only those doesn't need to redeclare
structural props.

### Validator behavior

`assets/validate.py` includes `audit_variant_discipline` (rule **R47**).
For every CSS rule whose selector contains `[data-variant=...]`, the
validator checks: if the block declares `display:` or `flex-direction:`
or any `grid-template-*`, it must ALSO declare `align-items` and
`justify-content` (or their `place-*` shorthands). Otherwise it warns
that this variant is touching structure without redeclaring all
directional props — exactly the scenario that produces "I flipped
direction but it didn't change" bugs.

Cosmetic-only variants (e.g. `data-variant="dense"` that only changes
`gap` and `padding`) pass the audit untouched — the rule only triggers
when structural change is detected.

### Going-forward expectation

When writing or editing a `data-variant` rule:

1. Decide: is this variant **cosmetic** (color, spacing, font) or
   **structural** (layout direction, engine, alignment)?
2. If structural → redeclare every directional property listed above.
3. Run `python3 assets/validate.py deck.html` — R47 will catch any
   structural variant that forgot to redeclare alignment.
4. If a variant is intentionally only changing one structural prop and
   keeping the others, redeclare them ANYWAY with the inherited value.
   Self-contained variants are easier to refactor later.

---

## Re-render UI mocks as HTML, not screenshots

When adapting source content into HTML — especially when "translating" or
"re-rendering" an existing deck, slide, or marketing screenshot — **system
UI, app screens, chat threads, dashboards, spreadsheets, browser windows,
and modal dialogs MUST be recreated in HTML/CSS, not embedded as raster
images.**

### Why

| Aspect | Raster screenshot | HTML mock |
|---|---|---|
| Fullscreen scaling | Pixelates above 1× | Crisp at any res |
| Typography | Whatever the screenshot has | Brand font (`var(--fs-font-cjk)`) |
| Color harmony | Off-brand by definition | Uses `--fs-blue` etc. |
| File size | 200–800 KB JPG/PNG | 1–4 KB inline HTML |
| Inspectable | Black box | DOM, accessible |
| Licensing | Real product UI = NDA risk | Stylized recreation, safe |
| "Looks more real" | Looks pasted-in | Looks native to the deck |

### What still belongs as a raster image

- Real photographs (customer scenes, hardware shots, factory floors) →
  use `data-decor="photo-bg"` with `style="--photo: url(...)"`.
- Brand assets (the 飞书 tri-petal logo, the slogan PNG) — already inlined.
- Illustrative artwork that's genuinely artistic (the master flower image).

If it's a UI element — re-render. If it's a photograph or art — inline.

### `.data-panel` vs `.ui-window` — pick the right container

Two ways to frame structured data on a slide. They look superficially
similar, but the visual associations are very different and the rule
for picking is strict:

| Container | When to use | Visual signal |
|---|---|---|
| **`.data-panel`** (default) | You're showing structured data — status rows, KPI summaries, value-translation tables, agent step lists, "下一步" callouts. The data isn't part of any app's UI; you just need a brand-aligned framing. | Side accent bar (4 px blue / teal / violet) + clean header + gradient keyline. NO traffic lights. NO window chrome. |
| **`.ui-window` + `.ui-traffic-lights`** | You're actually mocking a macOS desktop app (real screenshot replacement). The traffic lights tell the viewer "this is a software window." | Three colored dots (red/yellow/green) + titlebar + window-style framing. |

**Default to `.data-panel`.** Reach for `.ui-window` only when the
content WOULD HAVE BEEN a screenshot of a real app — chat thread,
browser dashboard, spreadsheet panel, modal dialog. If the same
content could legitimately appear as a "report module" without app
chrome, it's a `.data-panel`.

`.data-panel` markup pattern:

```html
<div class="data-panel">                  <!-- or .data-panel.is-teal / .is-violet -->
  <h4>客户类型 · 共创进入条件</h4>
  <hr>
  <div class="row">
    <span class="lbl">先进型 · 流程已成熟</span>
    <span class="val">学过来 → 教别人</span>     <!-- default: teal -->
  </div>
  <div class="row">
    <span class="lbl">中间型 · R&amp;D VP 接洽</span>
    <span class="val warn">权限不够 → 暂缓</span>  <!-- .warn = orange -->
  </div>
  <div class="ui-alert">                   <!-- .ui-alert reuses fine inside .data-panel -->
    <div class="t">下一步</div>
    <h5>古茗 / 瑞幸先进流程调研</h5>
    <p>凯轩节后跟进。</p>
  </div>
</div>
```

Tonal variants (`.is-teal` / `.is-violet`) recolor the side accent bar
and the row arrows for differentiation when multiple panels coexist on
a slide (e.g. content-2col with two side-by-side panels).

### UI primitives shipped in the CSS

The `feishu-deck.css` ships a set of `.ui-*` primitive classes that compose
into any 飞书-style app mock. All are dark-themed, brand-aware, and built
from the existing tokens. None of them require additional assets.

| Primitive             | Renders                                          |
|-----------------------|--------------------------------------------------|
| **`.data-panel`**     | **Default** brand-aligned container for structured data — side accent + keyline, no window chrome. Tonal variants `.is-teal` / `.is-violet`. **Use this for non-app data;** `.ui-window` only for actual macOS app UI mocks. |
| `.ui-window`          | Generic dark app panel + 16 px radius + soft shadow — for app UI mocks |
| `.ui-titlebar`        | Top bar inside `.ui-window`                       |
| `.ui-traffic-lights`  | macOS-style red/yellow/green dots — only inside real app mocks |
| `.ui-browser`         | `.ui-window` variant w/ a URL pill in titlebar   |
| `.ui-urlbar`          | Pill-shaped URL display                          |
| `.ui-body`            | Flex container holding `.ui-sidebar` + `.ui-main`|
| `.ui-sidebar`         | 260 px left vertical navigation                   |
| `.ui-main`            | Right-side content column                         |
| `.ui-toolbar`         | Horizontal toolbar with tabs / buttons            |
| `.ui-tab-bar` / `.ui-tab` | Tabs (`.is-active` for selected)              |
| `.ui-list` / `.ui-list-item` | Chat list / contact list / file list rows  |
| `.ui-list-item .ui-line .name / .preview` | Two-line list row text       |
| `.ui-list-item .ui-meta` | Right-side timestamp / count                  |
| `.ui-avatar`          | Round avatar with initial (`data-tone="teal\|purple\|orange"`) |
| `.ui-msg`             | Chat bubble (`.is-self` blue right / `.is-other` ghost left) |
| `.ui-msg-stack`       | Vertical stack of `.ui-msg`                       |
| `.ui-input`           | Form text input                                   |
| `.ui-btn`             | Button (`.is-primary` / `.is-secondary` / `.is-ghost`) |
| `.ui-grid` / `.ui-cell` | Spreadsheet / 多维表格 cells (`.is-header` for thead) |
| `.ui-cell .ui-pill`   | Inline tag inside a cell (`data-tone=...`)        |
| `.ui-status-dot`      | 8 px status dot (`.is-online / .is-busy / .is-offline`) |
| `.ui-badge`           | Numeric notification badge (`.is-mute` for grey)  |
| `.ui-progress`        | 4 px progress bar; set `style="--ui-progress: 76%"`|

### Example: recreating a 飞书 messenger window

```html
<div class="col-visual">
  <div class="ui-window">
    <div class="ui-titlebar">
      <span class="ui-traffic-lights"><i></i></span>
      <span>飞书 · 销售战区</span>
    </div>
    <div class="ui-body">
      <aside class="ui-sidebar">
        <div class="ui-section">置顶会话</div>
        <div class="ui-list">
          <div class="ui-list-item is-selected">
            <span class="ui-avatar" data-tone="teal">A</span>
            <span class="ui-line">
              <span class="name">A 公司 · 战区群</span>
              <span class="preview">王总：方案已确认,周一开评审会</span>
            </span>
            <span class="ui-meta">2 分钟前</span>
          </div>
          <div class="ui-list-item">
            <span class="ui-avatar" data-tone="purple">B</span>
            <span class="ui-line">
              <span class="name">B 银行 · 商务对接</span>
              <span class="preview">合同条款已发您查收</span>
            </span>
            <span class="ui-meta">12:48</span>
          </div>
        </div>
      </aside>
      <main class="ui-main">
        <div class="ui-toolbar">
          <div class="ui-tab-bar">
            <span class="ui-tab is-active">消息</span>
            <span class="ui-tab">文件</span>
            <span class="ui-tab">日程</span>
          </div>
        </div>
        <div class="ui-msg-stack">
          <div class="ui-msg is-other">王总,本季度推进的方案版本已经在 Wiki。</div>
          <div class="ui-msg is-self">收到。我看完后下午给你反馈。</div>
          <div class="ui-msg is-other">好的,有问题随时@我。</div>
        </div>
      </main>
    </div>
  </div>
</div>
```

### Example: recreating a Lark Base 多维表格

```html
<div class="ui-window">
  <div class="ui-titlebar">
    <span class="ui-traffic-lights"><i></i></span>
    <span>销售跟单 · 飞书多维表格</span>
  </div>
  <div class="ui-grid" style="grid-template-columns: 200px 120px 100px 140px">
    <div class="ui-cell is-header">客户</div>
    <div class="ui-cell is-header">阶段</div>
    <div class="ui-cell is-header">金额</div>
    <div class="ui-cell is-header">负责人</div>

    <div class="ui-cell">A 公司</div>
    <div class="ui-cell"><span class="ui-pill" data-tone="teal">已签约</span></div>
    <div class="ui-cell">¥ 3.2M</div>
    <div class="ui-cell">王雪</div>

    <div class="ui-cell">B 银行</div>
    <div class="ui-cell"><span class="ui-pill" data-tone="blue">谈判中</span></div>
    <div class="ui-cell">¥ 4.6M</div>
    <div class="ui-cell">张伟</div>

    <div class="ui-cell">C 集团</div>
    <div class="ui-cell"><span class="ui-pill" data-tone="purple">商机</span></div>
    <div class="ui-cell">¥ 2.4M</div>
    <div class="ui-cell">李娜</div>
  </div>
</div>
```

### Example: recreating a browser-based dashboard

```html
<div class="ui-window ui-browser">
  <div class="ui-titlebar">
    <span class="ui-traffic-lights"><i></i></span>
    <span class="ui-urlbar">larksuite.com / dashboard / 战区周报</span>
  </div>
  <div class="ui-main" style="padding: 32px">
    <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap: 18px">
      <div class="card"><h3 class="ctitle">已读率</h3><div class="num">98%</div></div>
      <div class="card"><h3 class="ctitle">触达时延</h3><div class="num">3 秒</div></div>
      <div class="card"><h3 class="ctitle">ROI</h3><div class="num">3.2×</div></div>
    </div>
  </div>
</div>
```

### Validator behavior

`assets/validate.py` includes `audit_ui_mocks_are_html` (rule **UI1**).
It scans every slide for `<img src="…">` tags. The validator allows:
- `data:` URIs (inlined assets)
- The known brand asset filenames (`lark-logo`, `lark-slogan`,
  `lark-cover-bg`, etc.)

Anything else triggers a **warning** suggesting the `<img>` is a UI
screenshot that should be re-rendered using the `.ui-*` primitives.
In `--strict` mode this becomes an **error**. Pure photographs go through
`data-decor="photo-bg"` with `style="--photo: url(…)"`, not via raw `<img>`.

### Going-forward expectation for the agent

When asked to "translate this slide / deck / page into HTML":
1. Identify which visual elements are SYSTEM UI vs. real photographs.
2. For each UI element, pick the closest `.ui-*` primitive composition.
3. Recreate the UI in HTML/CSS using brand tokens — fonts, colors, radii.
4. Only reach for raster `<img>` when the source is a genuine photograph
   or a piece of artwork.
5. If unsure ("is this a UI screenshot or a marketing illustration?"),
   ask. The default answer is "treat it as UI and re-render".

A deck where every UI element is HTML feels native. A deck with pasted
screenshots feels like a draft.

---

## Layout integrity rules — execute, don't assume

These are the failure modes that hit the LKK exchange deck on first try.
Adding them as **mandatory** layout audits, not "best practice" suggestions.

### Rule L1 — Logo defaults to COLOR on every slide

`.slide .wordmark` background MUST default to `var(--fs-asset-logo)` (the
tri-petal color logo). Mono is **opt-in** via `class="is-mono"`. The mono
variant is only correct on chapter dividers / section pages where the
glow background dominates and a colored logo would clash.

```css
/* default — color */
.slide .wordmark { background: var(--fs-asset-logo) right center/contain no-repeat; }
/* opt-in mono */
.slide .wordmark.is-mono { background-image: var(--fs-asset-logo-mono); }
```

The pre-Sept-2025 spec had this backwards (mono default, color opt-in via
`is-color`). That's deprecated. **If you generate a deck where every content
slide uses the mono logo, you've broken Rule L1.**

### Rule L2 — No content stranded at the top of a slide

If a slide's content uses less than 60% of the canvas height, you MUST
either (a) center the content vertically, or (b) make it expand to fill.
**Never** leave content packed at the top with empty bottom — this is the
single most-reported visual bug from internal sales.

Mechanical fix recipe per layout type:

| Layout         | When to apply                          | CSS to add                                   |
|----------------|----------------------------------------|----------------------------------------------|
| `content-2col` | Cards shorter than canvas              | `align-content: center` on `.stage`/`.grid`  |
| `process`      | Step row natural height < canvas       | `align-content: center` on `.stage`/`.flow`  |
| `content-3up`  | Card row natural height < canvas       | `align-content: center` on `.stage`/`.grid`  |
| `pipeline`     | Steps + highlights + infra leave space | `flex: 1` on `.steps`, let it grow           |
| `timeline`     | Nodes row shorter than container       | `align-content: center` on `.nodes`          |

> The CSS in this skill uses `.grid` / `.flow` / `.nodes` as the historical
> per-layout container names. `.stage` is the canonical generic name from
> the abstract规范. Both are valid; the audit accepts any of them.

If the content is already dense enough to genuinely fill 80%+ of the canvas,
neither center-mode nor grow-mode is needed. Otherwise pick one — DO NOT
ship a top-stacked slide.

### Rule L3 — `margin-top: auto` on a stretched card creates the empty-middle bug

If a card is `display: flex; flex-direction: column` and an inner element
has `margin-top: auto` (e.g. a pills row pushed to bottom), and the parent
grid stretches the card to fill the whole stage height, the visible result
is a card with content stuck at top, pills stuck at bottom, and **a giant
empty middle**.

Fix: combine Rule L2 (center the row vertically with `align-content: center`
on the grid container) with content-sized rows (`grid-template-rows: auto`)
so cards become exactly content-tall instead of canvas-tall. Pills'
`margin-top: auto` then becomes a no-op when content already fills the card.

The shipped CSS now defaults to this safer behavior:

```css
.slide .grid > .card,
.slide .flow > .step {
  align-self: stretch;   /* equal-height within row, cosmetic */
  margin: 0;              /* override the auto-margin default — grid handles vertical placement */
}
```

### Rule L4 — Output panel attribute lists: single column when narrow

The `process` layout's output panel is ~400 px wide. If you put a 4-item
attribute list in `grid-template-columns: 1fr 1fr` (2×2), each cell becomes
~180 px which truncates body-floor (22 px) text like "Communication style".
Use `grid-template-columns: 1fr` (single vertical stack) when the panel
is < 480 px wide. The output panel is naturally tall — vertical stacking
fits its proportion and lets body type stay at the 22 px floor.

The shipped CSS enforces this:

```css
.slide[data-layout="process"] .output .attrs {
  grid-template-columns: 1fr;   /* never 1fr 1fr */
}
```

### Mechanical audit (extends self-check items #6, #7, #19)

The `assets/validate.py` validator now includes these checks (the function
signatures match the规范 verbatim):

```python
def check_logo_default(html):
    """Rule L1: wordmark default must reference --fs-asset-logo (color)."""
    m = re.search(r'\.slide \.wordmark \{[^}]*background:\s*([^;]+);', html, re.DOTALL)
    return m and 'asset-logo)' in m.group(1) and 'asset-logo-mono' not in m.group(1)

def check_balance(html):
    """Rule L2: every layout's stage uses center or flex-grow when content is short."""
    layouts_with_short_content = ('content-2col', 'process', 'content-3up')
    for layout in layouts_with_short_content:
        m = re.search(rf'\.slide\[data-layout="{layout}"\] \.stage \{{[^}}]*\}}', html, re.DOTALL)
        if m and not ('center' in m.group(0) or 'flex: 1' in html):
            return False, layout
    return True, None

def check_attrs_density(html):
    """Rule L4: process output attrs should be 1-col when output panel is narrow."""
    m = re.search(r'\.slide\[data-layout="process"\] \.output \.attrs \{[^}]*\}', html, re.DOTALL)
    return m and 'grid-template-columns: 1fr;' in m.group(0)
```

Block delivery if any returns False.

### Going-forward expectation for the agent

When the agent finishes writing a deck, BEFORE sending the file to the user:

1. Run the font-size audit (existing — Rule #6).
2. Run `check_logo_default` (Rule L1).
3. Run `check_balance` for every layout used (Rule L2).
4. For every `content-3up`, `content-2col`, `process` slide, eyeball whether
   `.stage` either centers or fills. If neither, fix.
5. For every `process` slide with output attrs, confirm single-column.

**The user should never have to point out a top-stacked layout, an empty
middle, or a mono logo on content slides.** If they do, it's because the
agent skipped Rules L1–L4. Re-run before you reply.

---

## Self-check must be EXECUTED, not just listed

The validator audits at the bottom of this file are a hard gate, not a
checklist for your reading pleasure. Before declaring a deck "done":

1. **Run a font-size audit programmatically.** Don't trust visual feel.

   ```bash
   python3 assets/validate.py path/to/your-deck.html
   # exit 0 = pass · exit 1 = fail · exit 2 = file not found
   ```

   The shipped `assets/validate.py` script statically audits the assembled
   HTML against every check that doesn't require a real browser:

   - **Structure** (R02 / R07): every `.slide` has `data-layout`,
     `data-screen-label`, and `.wordmark`. (`.footer` was retired 2026-05;
     the present-mode pager handles page numbers — no per-slide chrome
     is required anymore.)
   - **One-line titles** (R13): no `<br>` inside `.header h2` /
     `.header h2.title-zh` / `.header h2.title` on layouts other than
     `cover` / `image-text` / `end`.
   - **Brand chrome** (R07): warns when `.wordmark.is-mono` is used —
     mono-white logo must be an explicit edge case, not the default.
   - **Banned punctuation** (R05): scans rendered text for emoji, `!`/`！`,
     ellipsis `…`/`...`, `???`/`？？？`.
   - **Font-size floor** (R06): every `font-size` declaration on a selector
     that targets slide content (NOT `.deck-ui`) must be ≥ 14 px. The script
     lists each violation with the offending selector and size.
   - **Modular type-scale ladder** (R20): every `font-size` in per-page
     `<style>` (selector contains `[data-page="NN"]`) must be in the allowed
     set `{10, 11, 12, 13, 14, 18, 22, 28, 38, 44, 52, 56, 64, 88, 100, 132, 160}`.
     Off-ladder values (16/17/19/20/24/26/30/32/36/40/48/72/96 …) ERROR with
     a "nearest rung" hint. Genuine master-spec exceptions opt out via
     `/* allow:typescale */` inside the rule. The framework stylesheet is
     exempt; this rule fires only on per-page improvisation, which is exactly
     where ad-hoc 24/32/96 sizing slips in.
   - **No drop shadows** (R12): scans `.slide` selectors for `box-shadow`
     declarations. Recognises glow rings (`0 0 0 Npx ...`) and `inset`
     shadows as allowed; flags any real drop shadow with non-zero offset.
   - **`data-decor` token validity** (R38): every token inside a slide's
     `data-decor` must come from the ship list (`violet-glow / blue-glow /
     mix-glow / teal-glow / orange-spark / aurora / grain / topo /
     flower-bg / section-bg / photo-bg`). Misspellings produce hard fail.
   - **Hex palette** (R10): warns when slide markup contains hex values
     outside the brand palette. (SVG decoration is excluded from this scan.)
   - **Runtime chrome** (R29-R32): verifies `.deck-progress`, `.deck-controls`,
     prev/next/fs buttons, `requestFullscreen`, `fullscreenchange`, the
     keyline-gradient progress bar, and `.is-idle` auto-fade are all wired.
   - **Centering pattern** (R36): asserts present-mode uses
     `margin: -540px 0 0 -960px` (absolute centering) and NOT `display: grid`
     on `.slide-frame`.
   - **Layout integrity** (L1 / L2 / L4): logo defaults to color, every
     short-content stage has `align-content: center` (or grow), `process`
     output panel attrs are single column.
   - **Default centering** (R48): every fixed-shape layout has centering on
     its inner container.
   - **Variant discipline** (R47): variants that change structural
     properties also redeclare `align-items` + `justify-content`.
   - **UI mocks as HTML** (UI1): warns on any `<img>` in slide content that
     isn't a known brand asset or `data:` URI.
   - **Cyan as slide-accent** (R49): rejects `data-accent="cyan"` on
     `.slide` — cyan is inline-word-highlight only.

   Pass `--strict` to promote warnings (mono logos, off-palette hex) into
   errors. Default mode lets warnings pass for an in-progress deck; strict
   mode is the pre-delivery gate.

2. **Treat exit-1 as a delivery blocker.** If the script reports any error,
   fix it. Don't paper over it by editing the validator. The check is
   conservative — every flag is a real规范 violation, not noise.

3. **Run the script after EVERY rebuild.** Each time you regenerate
   `examples/sample-deck.html` (or any deck), pipe through the validator
   in the same shell command:

   ```bash
   bash build.sh && python3 assets/validate.py examples/sample-deck.html || exit 1
   ```

   This makes regression detection automatic — a CSS edit that introduces
   a 12 px font in a `.slide *` selector will be caught immediately, not
   when a customer flags it on a printed handout.

4. **Items 14, 15, 20, 21 still require a human eye.** Visual alignment of
   the title baseline with the logo center, ZH > EN balance, atmospheric
   "feel", and density of glow vs content density — the validator can't
   judge these. Open the deck at 1920×1080, 1280×720, and 380×680 and
   look. Then ship.

The current `examples/sample-deck.html` passes `validate.py` with exit 0
in both default and `--strict` mode — that's the bar.

---

## Preserve atmospheric / decorative backgrounds when re-rendering

When re-rendering an existing slide into a standard layout, **never silently drop
the slide's distinctive background imagery, decorative gradients, or atmospheric
overlays**. Those visuals carry tone information that the layout structure alone
cannot express — stripping them makes the redesign feel sterile and the user
notices immediately.

### What counts as "atmospheric"
- Radial decorative glows (e.g. the violet magnolia glow lower-right on
  Digital Workforce slides)
- Full-bleed photographic backgrounds beyond the cover (e.g. customer scene
  photos on `image-text` layouts)
- Brand gradients other than the default `--fs-grad-hero`
- Aurora / particle / film-grain overlays
- Hand-drawn illustrative motifs

### How to preserve them — `data-decor` attribute

Decoration is **orthogonal to layout**. A slide can carry any combination of
layout + variant + decor. Mark the decoration with a `data-decor` attribute
on the `.slide` element:

```html
<!-- Preserve the violet magnolia glow when re-rendering Digital Workforce
     into the standard 3-up content layout — layout is unchanged, atmosphere stays -->
<div class="slide"
     data-layout="content-3up"
     data-decor="violet-glow"
     data-screen-label="07 数字员工">
  ...
</div>

<!-- Stack multiple decors with space separation: cinematic mix + grain -->
<div class="slide"
     data-layout="quote"
     data-decor="mix-glow grain"
     data-screen-label="06 Quote">
  ...
</div>

<!-- Custom photographic background for an image-text style customer page -->
<div class="slide"
     data-layout="image-text"
     data-decor="photo-bg"
     style="--photo: url('./photos/store-floor.jpg')"
     data-screen-label="09 Customer">
  ...
</div>
```

### Available decor tokens (CSS already ships these)

| Token          | Renders                                      | Use for |
|----------------|----------------------------------------------|---|
| `violet-glow`  | Lower-right violet bloom (#9F6FF1 + #5C3FFB) | Digital Workforce / 数字员工 / AI signature |
| `blue-glow`    | Centered blue radial (#3C7FFF)               | Quote / hero / single-focus emphasis |
| `mix-glow`     | Purple top-right + blue bottom-left          | Closing / cinematic transitions |
| `teal-glow`    | Bottom-left teal bloom (#33D6C0)             | Data / KPI / impact pages |
| `orange-spark` | Top-right warm flare (#FE7F00)               | Alert / 例外 / risk callout |
| `aurora`       | Three-color ambient (blue + violet + teal)   | Generic ambient atmosphere |
| `grain`        | Subtle film grain (CSS noise, no asset)      | Cinematic finish — pairs with any glow |
| `topo`         | Faint topographic line motif                 | Process / engineering / pipeline pages |
| `flower-bg`    | Full-bleed master flower (`--fs-asset-cover-bg`) | Carries the cover atmosphere into a content page |
| `section-bg`   | Master section gradient (`--fs-asset-section-bg`) | Color-rich chapter pages outside `section` layout |
| `photo-bg`     | Custom URL via `style="--photo: url(...)"`   | Any photographic full-bleed beyond the master assets |

### Architecture rules
1. **Decor is a `::before` (and grain a `::after`) pseudo-element.** It sits
   under all slide content (`z-index: 0`) with `pointer-events: none`. It
   never disturbs layout or hit-testing.
2. **Decor is always opt-in.** Default slides have no `data-decor` and render
   exactly as they used to. Adding decor never changes the layout.
3. **Decor stacks via space-separated tokens.** `data-decor="violet-glow grain"`
   composes the violet bloom and the grain overlay.
4. **`flower-bg` and `photo-bg` automatically add a darkening protection
   gradient** when applied to a non-cover layout, so text remains legible
   over imagery. Cover and end layouts already carry their own contrast
   strategy and skip the auto-overlay.
5. **When re-rendering an existing deck**, audit each source slide for
   atmospheric content and translate it to the matching token. If no token
   matches the source decor exactly, use the closest one and note the
   approximation — never silently drop it.

---

## CSS layout pitfalls (defenses already in feishu-deck.css)

The `.slide` canvas is fixed 1080 × 1920 (or 720 × 1280 native — same ratio).
Four classic flex/grid mistakes blow that canvas out. The CSS includes defenses
for all of them, but be aware:

1. **flex-column + `flex:1` child + min-content content → overflow.** Every flex
   item must also have `min-height: 0` so it can actually shrink. The CSS
   applies this to `.stage`, `.grid`, `.flow`, `.col-text` by default.
2. **CSS Grid rows take max-content height.** Use `grid-template-rows: minmax(0, 1fr)`
   and apply `min-height: 0` to grid cells. The CSS already applies `min-width: 0;
   min-height: 0` to all direct grid children.
3. **`flex-wrap: wrap` on a `min-width: 0` parent = disaster.** Mixed-width
   children blow up scrollHeight. The CSS defaults `.pills` and `.cta-row` to
   `nowrap` with `overflow-x: hidden`. If you genuinely need wrapping pills,
   declare it explicitly.
4. **Card density: stretch vs auto-margin.** Default = `.card { margin: auto 0 }`,
   so cards take their content's natural height and center vertically in the
   grid cell. Only add `class="is-stretch"` when content density actually
   requires the card to fill — otherwise you get an ugly "card filled, content
   only at top" gap. The CSS already encodes this; trust the default.

If you write a custom layout, follow these patterns. If a slide overflows in
practice, run through this list before tweaking pixel values.

---

## Production deck layout fixes (BF1-BF4 — v1.4, 2026-05-02)

These four bugs surfaced in the 数字员工指南 deck and now have permanent
defenses in `feishu-deck.css`. Each captures a specific user-visible failure;
the defense is automatic, but the AUTHORING rule still matters — knowing
why the defense exists keeps you from working around it.

### BF1 — short-numeral big-stat hugs the left edge

**Symptom**: Big-stat slide with a single-character `.num` value (e.g. `5`,
`3`) — the digit visually clings to the slide's left padding (96px from the
edge), looking orphaned. Multi-character values like `30万人` filled the
left grid cell and hid the issue.

**Defense (CSS)** — *v2, 2026-05-03, replaced v1's right-anchor approach*:
`.slide[data-layout="big-stat"] .num { justify-self: center; text-align:
center; }` — sits the numeral in the visual center of its left half-canvas
cell, so the digit reads as a balanced focal element regardless of value
length.

**v1 → v2 history**: v1 used `justify-self: end / text-align: right` to
anchor the number against the slide centerline next to the .copy block.
That hugged the number too close to the .copy text, creating a
visually-jammed-up feeling on the centerline. v2 centers in the cell
instead, with breathing room on both sides.

**Authoring rule**: prefer multi-character values that show the FULL
story — e.g. `30 → 5` instead of bare `5`. The transformation reads in
one glance AND the cell fills naturally. Single-character values are
allowed; the v2 centering keeps them looking deliberate. Don't
hand-tune position.

### BF2 — `.col-visual` double-frames a self-decorated child

**Symptom**: Putting a `.data-panel`, `.ui-window`, `.kpi-strip`,
`.scene-grid`, `.north-star-map`, `.calc`, or `.ui-kpi` directly inside
`.col-visual` produces a visible "browser-chrome" border WRAPPED AROUND the
inner panel — the `.col-visual` default frame (1px hairline + 16px radius +
faint top-down gradient) was meant for raw image / placeholder mocks only.

**Defense (CSS)**: `.col-visual:has(> .data-panel) { border: none;
background: none; padding: 0; border-radius: 0; }` — and the same for
each self-decorated component class. The wrapper frame disappears
automatically; the inner panel's own decoration takes over.

**Authoring rule**: prefer putting structured data containers
(`.data-panel`, etc.) directly inside `.col-visual` — the CSS will
silently strip the wrapper frame. Only keep `.col-visual`'s own frame
when the column carries a raw image, an inline SVG mock, a screenshot,
or a custom hand-built block that has no border of its own.

### BF3 — helpers compressed in stage middle, surrounded by empty space

**Symptom**: `.scene-grid` (especially 2×2 / 4-card layouts) or
`.north-star-map` placed inside a layout's `.stage` shows up as a small
block in the canvas vertical centre, with conspicuous empty space above
AND below. Default `align-self: center` + content-natural height collapse
the helper to ~70% of the available vertical room.

**Defense (CSS)** — *v2, 2026-05-02 PM, replaced v1's vertical-stretch approach*:
- All `.stage > .scene-grid` and `.stage > .north-star-map` get
  `align-self: stretch; width: 100%` so they span the stage horizontally.
- When the helper is the dominant body block (alone, or paired only with a
  trailing pullquote / lede — detected via
  `:only-child` and `:first-child:nth-last-child(-n+2)`), the CSS bumps
  per-card padding (scene-card 32×28, ns-card 28×22) AND grid gap
  (scene-grid 24px, north-star-map 18px). Cards stay content-sized; the
  visual mass spreads across the canvas via richer padding + gaps, not
  via stretching empty card interiors.

**v1 → v2 history**: the first version added `flex: 1; align-content:
stretch` on the grid to force cards to fill the stage vertically. That
overshot — ns-cards at --cols:5 stretched to ~750px tall while content
was only ~400px, leaving giant empty borders, and `.tags`
(`margin-top: auto`) ended up jammed against the bottom border, looking
like the border was "blocking" the text. Lesson: stretch FILLS space but
doesn't distribute content — bigger padding + bigger gaps achieve the
same "feels filled" without the empty-card-interior failure mode.

**Authoring rule**: when you want a 2×2 or 1×N helper to occupy the
canvas, just place it as the major body block of `.stage`. The defense
triggers automatically and bumps padding/gap. If you DON'T want the
extra padding (e.g. 3 short rows of dense cards where tight spacing is
the look), add a non-trivial sibling AFTER the helper (a `.kpi-strip`,
a `.cta-box`, etc.) so the :nth-last-child detector skips the bump.
The auto-bump only fires when there's no significant content following
the helper.

### BF4 — pullquote left-bar shifts text 32px right of grid

**Symptom**: A `.pullquote` placed below a body grid (`.grid`,
`.scene-grid`, `.north-star-map`) reads as "indented" — its text starts
32px to the right of the cards' left edge because the bar uses
`border-left: 4px` + `padding-left: 28px`. The visual misalignment
nags the reader even when they can't articulate why.

**Defense (CSS)**: `.stage > .pullquote { margin-left: -32px; }` pulls
the bar OUTSIDE the text column, so the text-left aligns with the grid's
left edge while the bar still reads as decoration to the left of the
content area.

**Authoring rule**: don't reach for inline `style="margin-left: ..."` to
fix pullquote alignment. The defense handles content-2col / content-3up /
agenda / process / stats / timeline / table stages uniformly. If a
pullquote sits OUTSIDE `.stage` (legacy decks pre-1.3.2 with no stage
wrapper), the rule doesn't fire — but you should be migrating those
decks to the stage pattern anyway.

### BF5 — macOS traffic-lights forbidden by default

**Symptom**: A `.ui-window` mock with `<span class="ui-traffic-lights">`
renders three colored dots (red / yellow / green) at the top-left of
the titlebar, mimicking a macOS app window. In a 飞书 enterprise pitch
the dots feel **too consumer / casual** — the slide stops reading as a
brand-aligned data panel and starts reading as "someone's screenshot."
Reported by users on multiple decks.

**Defense (CSS)**:
`.slide .ui-window:not([data-show-chrome]) .ui-traffic-lights { display:
none; }` — the dots disappear automatically. The `.ui-titlebar` without
dots still reads as a window-style header, which is sufficient chrome
when mocking a Lark Base spreadsheet, a chat panel, or a browser dashboard.

**Opt-in for genuine macOS-screenshot context**: add `data-show-chrome`
on the parent `.ui-window`. This is the documented escape hatch when
a slide genuinely needs the macOS aesthetic (e.g. an "app review" deck
that's literally about macOS apps). Default is HIDDEN.

**Authoring rule**: do NOT include `<span class="ui-traffic-lights">`
in new decks unless you've explicitly decided the slide needs the macOS
window aesthetic. Even if the recipe at the top of `templates/slide-recipes.html`
shows the dots, the brand expectation for 飞书 / 汇报 / 客户提案 contexts
is no traffic lights. The CSS will hide them anyway, but cleaner markup
makes it obvious this isn't a macOS screenshot.

### BF6 — `.ui-grid` clusters at one side of `.ui-window`

**Symptom**: A `.ui-grid` (Lark Base / spreadsheet mock) inside a
`.ui-window` inside `.col-visual` clusters at the LEFT edge of its
parent, leaving large empty space on the right. Reported as
"内容都在一头" (content all stuck on one side) on a sales-table slide
where columns were `style="grid-template-columns: 130px 90px 80px 70px"`
(370px total width) inside an 864px col-visual.

**Defense (CSS)**: `.slide .ui-grid { width: 100%; align-self: stretch; }`
— the grid container always fills its parent's available row width.
Authors using fixed-px columns will see the grid expand and the leftover
space distributed proportionally if their `grid-template-columns`
includes `fr` units.

**Authoring rule**: prefer `fr`-based proportions for `.ui-grid` — e.g.
`style="grid-template-columns: 1.5fr 1fr 1fr 0.8fr"` keeps the relative
column widths AND fills the parent uniformly. If you genuinely need a
narrow content-sized table (e.g. a left-aligned key-value box), override
inline with `style="width: max-content"` on the .ui-grid.

### BF7 — `content-2col` hero image: align top AND bottom (defended in framework CSS)

When `.col-visual` carries an inline `min-height` (e.g. a 16:9 reference
scene anchored to 600px) and `.col-text` holds a stack of 3-5 short
sections, the text column packs at the top with empty space below.

**The framework now auto-applies `justify-content: space-between`** on
`.col-text` whenever `.col-visual` has an inline `min-height` style
(see feishu-deck.css). First text child aligns with image top, last
aligns with image bottom. Just set the image's `min-height` inline —
no other CSS needed.

When NOT to use this — use the story-case v2 pattern instead (see
ONE-PAGER CASE POLICY image-sizing rules) when the layout is
`.story-case`, OR when the text column has dense paragraphs that
naturally exceed image height. For those cases, image shrinks to text,
not the reverse.

### BF8 — flex-stage shrinks chart, grid bars don't follow (defended in framework CSS)

When a chart with positioned X-axis line (`::after { bottom: <pad> }`)
sits in a flex-column `.stage` alongside other body blocks, flex shrinks
the chart but the inner Grid `.bars` stays content-sized → bars
overflow downward, dropping below the X-axis line.

**The framework already defends `.arr-chart` / `.store-chart` /
`.bar-chart` with `flex-shrink: 0`** (see feishu-deck.css). When you
invent a new chart class, follow the same pattern — either name it one
of those, or add `flex-shrink: 0` in your per-page `<style>`.

Mirror failure (bars too SHORT, floating ABOVE X-axis): see "Bar chart
· X-axis alignment & in-chart brand logos" earlier in this file. Same
symptom, opposite cause; both rules apply together.

### BF9 — grid-stretched cell + `margin-top: auto` child = dead-middle empty space

**Symptom**: A vertical-comparison layout puts ONE column inside a grid
row that's stretched to the row's height (default `align-items: stretch`).
An inner element uses `margin-top: auto` to anchor itself to the column
bottom (e.g. "业务后果" label pushed below the comparison). Result: the
column has its title at top, the auto-margined element at bottom, and a
**giant empty middle** — the column is 600 px tall but content is 200 px
top-aligned plus 80 px bottom-anchored.

This is the structural sibling of BF3 (north-star-map's "stretch
overshoot"): any grid-stretched container with one `margin-top: auto`
child gets the same failure pattern.

**Failure recipe (don't write this)**:

```css
/* Bug: column stretches to row height; auto-margin yanks pills to bottom
   even though there's no content between, leaving a huge gap. */
.vs-comparison {
  display: grid; grid-template-columns: 1fr 1fr 1fr;
  align-items: stretch;     /* ← column = row height */
}
.vs-comparison .col {
  display: flex; flex-direction: column;
}
.vs-comparison .col .consequence {
  margin-top: auto;          /* ← yanks to bottom; empty middle */
}
```

**Three valid fixes**:

1. **Replace `margin-top: auto` with `justify-content: space-between`
   on the parent column.** This explicitly distributes children with
   equal gaps; nothing "yanks" to the bottom, so the middle naturally
   reads as deliberate negative space, not as an empty gap.
   ```css
   .vs-comparison .col {
     display: flex; flex-direction: column;
     justify-content: space-between;
   }
   ```
   Best for 3-section columns (title / comparison body / outcome
   footer) — the visual rhythm is clean.

2. **Drop `align-items: stretch` on the grid; let columns size to
   content.** Use `align-items: start` (or default `normal`) so columns
   are content-tall. The `margin-top: auto` then becomes a no-op (no
   space to push into). Use this when columns are intentionally
   different heights and you don't want forced equalization.

3. **Add a visible spacer or divider between the title and the
   auto-margined element.** A `<hr class="vs-divider">` with margin
   `auto 0` or a flex spacer with explicit `flex: 1` and visible
   gradient turns the empty space into deliberate decoration.

**Rule of thumb**: `margin-top: auto` should be paired with content
that fills MOST of the column. If your column has 30% content and 70%
empty (visible to the eye), the design is wrong — pick fix 1 or 2.

This is now flagged in SKILL.md but NOT enforced by the validator —
detecting "visible empty middle" requires layout-aware metrics
(line counts × line-heights). The R-DOM / R20 / R-WHITE-TEXT rules
catch DOM and typography drift; this one is editorial.

### R57 — quote / 金句 pages: no trailing periods

**Symptom**: A `<blockquote>` ending with `。` (or `.`) reads as a
formal full-stop sentence in the headline frame — too declarative,
breaks the rhetorical "this hangs in the air" feel of a 金句 / 客户证言
page. Reported repeatedly across multiple decks.

**Authoring rule**: on `data-layout="quote"` slides:
- Drop the trailing `。` / `.` from the final span of the blockquote
  text (the `.tail` leaf in the mixed-content split).
- Mid-sentence `,` `、` `—` are fine — they structure the sentence;
  it's only the TRAILING terminator that should disappear.
- The `.attrib` line below the quote MAY keep a trailing period if it's
  a complete attribution sentence, but most look better without.
- This applies to inline `<span class="accent-text">` emphasis splits
  too — make sure the LAST span doesn't terminate with a period.

**Why no programmatic enforcement**: a deck may have a quote spanning
multiple sentences with internal `。` (legitimate). Detecting "trailing
period only" reliably requires a parsing pass we haven't bothered to
write. The authoring rule + manual check on every quote slide is enough.

---

## Prototype / standalone-page embed modes (mandatory) — pick BEFORE you write any code

When the user gives you existing HTML(**通常是本地路径**)and asks to "把它加进来 /
搬过来 / 拼进来 / 做成一页",**先按「源是什么」分流** —— 这一步分错就是 30 分钟
doom-loop("乱了""字小了""重叠了")。这是历史重灾区:旧版把"搬过来/原封不动"
默认导去 iframe,而用户要的常常是**原生拼接**。

| 源是什么 | 用哪种 | 为什么 |
|---|---|---|
| **一份 feishu-deck-h5 写的 slide**(或 slide 形态静态 HTML),要它**原样当一张 slide** | **Native slide lift**(原生拼接 · **非 iframe**) | 源与新 deck 共享 `feishu-deck.css`,直接 splice 就对齐,iframe 反而多此一举 |
| **外来的、自带 layout/缩放/chrome 的独立 demo / 原型 / H5**,要它当**"活的"嵌进来** | **iframe · Mode A / B** | 它有自己的世界,iframe 边界才能避免 CSS/JS 互相打架 |
| 一段简单内容(文档/截图/卡片列表),想用框架原语**重画** | **Mode C · re-author** | 想要 texts.md / brand token / 4-tier 接管 |

> **判不准就一句话问**:"这页你要它当**原生 slide 原样拼进来**,还是当**活的 demo 嵌进来(iframe)**?" —— **别默认 iframe**(历史上这里一直默认错)。

下面先讲 **Native slide lift**,再讲 iframe 的 Mode A / B / C:

| # | iframe Mode | When(源都是**外来独立页**) | Layout in deck.json | Deck chrome |
|---|---|---|---|---|
| **A** | **Full-bleed** · 外来 demo 占满整页 | 独立 H5/原型,自带 title+logo+layout,要当"活的" | `raw` (with `_orig_layout: "image-text"`) | **HIDDEN** |
| **B** | **Framed** · deck 给标题栏+wordmark,demo 填下方 | "嵌入到当前页面" / "做一页 demo,标题是 X" | `iframe-embed` (schema-native) | **VISIBLE** |
| **C** | **Native re-author** · 用框架原语重画(非 verbatim) | 简单内容,想要 texts.md/brand token/4-tier | `raw` / schema `content/2col` 等 | VISIBLE per layout |

### Native slide lift (原生拼接 · 非 iframe · 从本地路径搬现成 feishu slide)

**触发**:用户给一个**本地路径**(一份 feishu-deck-h5 deck 的 `index.html`,或 slide
形态的 HTML)+ "把第 N 页 / 这几页 / 这个 slide **搬过来 / 原样拼进来 / 加进来**"。
这是用户的常用工作流——**他发路径,你就基于路径把对应 slide 原样加进当前 deck,
不反问"拿来干嘛"**。典型场景:"我以前写了 50 页,这次从里面挑 3 页讲,拼起来,
一点都不能动。"

**为什么不用 iframe**:源 slide 本来就是 feishu-deck-h5 写的,和新 deck 共享同一套
`feishu-deck.css` + present-mode JS。直接把它的 `.slide-frame` splice 进来就**逐像素
对齐**——不需要 iframe 隔离、不需要 scope CSS、不需要重画。iframe 在这里是**错的工具**
(那是给"外来自带壳的 demo"的,见 Mode A)。这是它和 Mode A 的根本区别。

**手工流程**(没有也不需要一键工具,手工拼):

1. 打开源路径 `index.html`,按 `data-slide-key` / `data-screen-label` / 第几个
   `.slide-frame` 定位目标 slide。
2. 整块剪出 `<div class="slide-frame"> … </div>`(到配对的 `</div>`)**verbatim**。
   **别用正则吃 DOM** —— 手工读 + 整块复制(见 EDITING DISCIPLINE E2 / R-DOM)。
3. **带上它依赖的 per-page 样式**:源 `<head>` 里 scope 到这张的
   `<style>[data-page="NN"] …</style>` / `[data-slide-key="KEY"] …` 块,一起搬。
4. **拷它引用的资源**:`background-image:url(...)` / `<img src>` / iframe `src` 指向的
   `input/*`、`assets/shared/*`、`prototypes/*`,复制进新 deck 并保持相对路径解析。
5. splice 进新 deck 的 `.deck` 容器,顺序随你排。
6. **de-collision(只动管线,不动设计)**:
   - `data-page` 撞车(两张都用 `03` 但 scoped CSS 不同)→ 把搬进来这张的 `data-page`
     连同它的 `[data-page="03"]` 选择器一起改成唯一值。
   - `data-slide-key` 撞 → 改唯一 key;`data-text-id` 撞 → 改(或拼接型直接不管,
     present-mode 页码看 DOM 顺序不看它)。
   - 资源重名(都叫 `input/scene.png` 但不同图)→ 改文件名 + 同步引用。
   - **以上全是编号 / 文件名层面,不改你看到的任何内容 / 设计。**
7. 内容**逐字不动**;**校验可跳**(verbatim 现成 slide,validate 没意义 ——
   纯拼接时手工 `index.html` 根本不走 render;走 deck.json 时 `--skip-validate-html`)。

**两种装配方式**:
- **纯拼接**(只搬现成页、不混新页)→ **直接手工组装 `index.html`**(标准 shell +
  搬来的 slide-frames),最"一点不动",不走 deck.json / render。
- **混装**(搬来的页 + 新设计的页同处一 deck)→ 每张搬来的 slide 作为
  `layout: "raw"` 放进 deck.json(`.slide` 的 inner 塞进 `data.html`),新页走 schema,
  一起 render。

**和 DESIGN PHASE 的关系**:lift 进来的页在设计方案表里标「**源自 `<path>` 第 N 页 ·
原样未改**」,DESIGN PHASE 对它们**不做角色判断 / 不补内容 / 不写六维** —— 它们已是
成品。设计只作用于新加的框架页(封面/章节/结尾)和整体顺序。

### Mode A · Full-bleed slide (verbatim port · iframe)

This is for a **foreign, self-contained** prototype / H5 / demo: it has its own
`<title>`, internal logo, internal scale-to-fit JS, its own background. Deck framework
chrome would **collide** with it, so give it the entire `1920×1080` canvas via an
**iframe** and tell the deck to add nothing. **A feishu-deck slide from another deck
does NOT belong here** —— 那走上面的 **Native slide lift**(原样 splice,不套 iframe)。

```json
{
  "key": "<prototype-slug>",
  "layout": "raw",
  "_orig_layout": "image-text",
  "screen_label": "NN <topic>",
  "data": {
    "html": "<style>.slide[data-slide-key='<prototype-slug>'] { position: absolute; inset: 0; background: #080C18; overflow: hidden; }\n.slide[data-slide-key='<prototype-slug>'] iframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; display: block; transform: scale(1.018); transform-origin: center center; }\n.slide[data-slide-key='<prototype-slug>'] .wordmark { display: none; }\n.slide[data-slide-key='<prototype-slug>'] .header { display: none; }</style><div class=\"wordmark\"></div><iframe src=\"prototypes/<prototype-slug>/index.html\" title=\"<demo title>\" loading=\"lazy\"></iframe>"
  }
}
```

Then `cp -r <source-deck>/prototypes/<slug> runs/<ts>/output/prototypes/` and you're done.

**`transform: scale(1.018)` is intentional** — standalone prototypes commonly compute
`min(window.innerWidth/W, window.innerHeight/H)` and cap at one axis, leaving 15px black
gutters. The 1.018 scale-up nudges the prototype past the gutters to fill 1920 cleanly.
Adjust per-prototype if needed.

### Mode B · Framed embed (iframe-embed schema)

This is the "**give me a demo slide titled X**" case. Deck contributes the chapter
title + 飞书 logo, prototype lives in the body area:

```json
{
  "key": "<demo-slug>",
  "layout": "iframe-embed",
  "screen_label": "NN <topic>",
  "data": {
    "title": "<deck-level chapter title>",
    "src": "prototypes/<demo-slug>/index.html",
    "iframe_title": "<a11y label>",
    "hint": "<optional bottom-right caption>"
  }
}
```

### Mode C · Native HTML re-author

Reserved for when the source is simple enough to redraw using framework primitives
(`.card`, `.kpi-strip`, `.data-panel`, `.ui-*`, etc.) AND you want `texts.md` editing,
brand tokens, 4-tier typography to apply. See "Re-render UI mocks as HTML, not
screenshots" earlier in this file. **Do NOT use this mode for a complex
standalone prototype** — its internal CSS (`:root` vars, absolute positioning,
custom scale JS) will fight the framework's stage / header / wordmark. See
anti-pattern below.

### Anti-pattern (this is the doom loop) · don't try to inline a complex prototype

Symptom: you start by copy-pasting prototype `<style>` + `<body>` into a raw slide's
`data.html`, then spend an hour:

- scoping every `:root { --x }` to `.slide[data-slide-key="..."] { --x }`
- prefixing every selector to avoid leaking
- rewriting the prototype's `window.innerWidth/W` scale logic to use slide dims
- adding `/* allow:typescale */` to every minified rule body to silence R06
- realizing the prototype's `position: absolute` children fight `.stage` / `.header`
- being told it "全乱了" and asked "有这么麻烦么"

**Yes, it's that hard, and it's the wrong tool.** When you catch yourself doing any
of the above on a standalone prototype HTML, stop and switch to **Mode A** (or B if
the deck needs a title overlay). The iframe boundary is what makes "verbatim port"
actually verbatim — without it, you're rebuilding the prototype inside the slide's
DOM tree and fighting every collision by hand.

### Decision recipe (90% of cases)

| 用户给的 + 说的 | 用哪种 |
|---|---|
| **本地路径 + feishu slide** · "把(第N页/这几页/这个 slide)搬过来 / 复制这页 / 原样拼进来 / 加进来 / 一点不动" | **Native lift**(splice · 非 iframe) |
| **外来独立 demo/原型** · "原封不动嵌这个 demo / 直接插入这个原型 / 把这个交互页放进来" | **A**(iframe 全幅) |
| "做一页 demo · 标题是 X" / "嵌入到当前页面" / "加个 demo,deck 给标题" | **B**(iframe framed) |
| "把这个文档/PDF/截图 重新用 native 组件画" / "用 .card / .kpi-strip 重做" | **C**(re-author) |
| 只给 URL/HTML 没说要干嘛 | **问**:"当**原生 slide 拼**(Native lift)还是当**活 demo 嵌**(iframe)?" — 别猜、**别默认 iframe** |

> 区分关键不在"搬/插入/原封不动"这些词(两类都这么说),而在**源是什么**:
> 一份 **feishu slide** → Native lift;一个**自带壳的独立 demo/原型** → iframe。

---

## Embedding prototypes (iframe rules)

Decks regularly embed live UI prototypes. There's a checklist for this — every
item below has bitten us before:

1. **Always copy the prototype HTML to the deck's outputs/ folder before
   embedding.** Never use `file:///Users/.../Downloads/...` or any user-local
   absolute path. When the deck is shared, the recipient won't have that file.
   Copy → reference with a relative path (`./prototypes/foo.html`).

2. **Strip "原型 / Demo" labels at the source, not via CSS.** `grep` and
   `replace` the `<div class="…demo-label…">…</div>` out of the prototype's
   HTML. CSS hiding leaves layout artifacts and screen-reader noise. Source
   stripping is 100× cleaner.

3. **Mobile prototype → wrap in `.phone-frame`** (CSS class shipped with the
   skill):
   ```html
   <div class="phone-frame">
     <div class="phone-screen">
       <iframe src="./prototypes/mobile.html" loading="lazy"></iframe>
     </div>
   </div>
   ```
   The notch (`::before`) and home indicator (`::after`) are decorative and
   already have `pointer-events: none` — without that the user reports "buttons
   don't respond".

4. **Desktop prototype → `.desktop-frame`** (no phone shell):
   ```html
   <div class="desktop-frame">
     <iframe src="./prototypes/desktop.html" loading="lazy"></iframe>
     <div class="iframe-hint">原型可点击 · Click anywhere</div>
   </div>
   ```
   The hint pill fades out after 7 s (already in CSS) and has `pointer-events:
   none` so it doesn't block clicks.

5. **iframe content too big? Scale it.**
   ```css
   .my-iframe { zoom: 0.88; }
   /* OR with width/height compensation */
   .my-iframe {
     transform: scale(0.88);
     width: calc(100% / 0.88); height: calc(100% / 0.88);
   }
   ```

6. **iframe tabs wrapping** is usually a font-size issue. Edit the
   prototype's source: `font-size: 11px`, `white-space: nowrap`,
   `flex-shrink: 0` on tab labels. If the prototype is bundled as base64 +
   gzip, decode → edit → re-gzip → re-encode (the `python -c` one-liner with
   `base64 + gzip + JSON` is the standard move).

7. **EVERY decorative overlay above an iframe needs `pointer-events: none`.**
   That includes hint pills, phone notches, home indicators, brand watermarks,
   timestamp chrome. Without it the prototype receives clicks but nothing
   happens — and the user thinks the prototype is broken.

8. **JSX / React prototypes MUST be pre-compiled — never Babel-runtime on
   `file://`.** A prototype whose `index.html` uses
   `<script type="text/babel" src="app.jsx">` + a CDN `@babel/standalone`
   renders **completely BLANK when the deck is opened via `file://`** (the
   normal way the user views a deck). Two reasons, either fatal:
   - Babel-standalone fetches each `.jsx` via XHR; on `file://` the browser
     blocks that as a cross-origin request (origin is `null`) → the JSX
     never transpiles → empty `#root`.
   - The CDN `<script src="https://unpkg.com/...">` needs live internet; an
     offline presentation gets nothing.

   **Symptom**: the slide shows the title + the iframe's bordered frame, but
   the frame is empty/black. The screenshot looks like a hollow box. Check
   the prototype's `index.html` for `type="text/babel"` and `unpkg.com`/CDN
   `src`s — that combination is the tell.

   **Fix (make it self-contained + file://-safe + offline)**:
   1. Pre-transpile every `.jsx` → plain `.js`. Babel-standalone runs fine in
      Node: `global.Babel = require('./babel.min.js');
      Babel.transform(src, { presets: ['react'] }).code`. Also transpile any
      inline `<script type="text/babel">` boot block.
   2. Vendor `react` + `react-dom` locally (`vendor/*.production.min.js`,
      ~140 KB total) instead of unpkg.
   3. Rewrite `index.html` so every script is a plain local
      `<script src="vendor/react.min.js">` / `<script src="compiled/app.js">`
      — no `type="text/babel"`, no CDN, no runtime Babel (drop the ~3 MB
      `babel.min.js` from the runtime entirely).
   4. Keep the `.jsx` as source; regenerate `compiled/*.js` whenever you edit
      one (and remember the rendered text now comes from `compiled/*.js`, so
      a copy change means: edit `.jsx` → recompile → the `.js` updates).

   Regular `<script src="x.js">` (and `data.js`, plain CSS `<link>`) load fine
   on `file://` — only Babel's XHR fetch of `.jsx` is blocked. So the cure is
   to remove JSX-at-runtime, not to inline cleverly. (Surfaced 2026-05-25 on
   the kangshifu `dealer-five-maps` five-maps demo — it shipped Babel-runtime
   and was blank on `file://`.)

---

## Narrative patterns (DESIGN.md §9 — A through K)

Beyond the 13 base layouts, the design system carries 11 named *narrative
patterns* for specific rhetorical moves common in 飞书 internal pitches.
The CSS ships classes for the high-frequency ones. Markup recipes:

### A. 3 + 1 hero pattern — "三类需求 → 统一过滤器"
Three parallel cards on top, one full-width "hero" card below. SVG dotted
arrows from each top-card foot converge to the hero. Use this when "decision
converges from multiple inputs" (clearer than 4-up).

### B. Verdict pill matrix — `data-verdict="go|conditional|nogo"`
For "接 / 部分接 / 不接" judgments. The card border color, top 5 px head bar,
and right-corner badge all derive from `data-verdict`:
```html
<div class="verdict-card" data-verdict="go">
  <span class="badge">GO · 接</span>
  <h3 class="ctitle">立即接入</h3>
  <p class="cbody">理由 …</p>
</div>
```
Color rules: `go=teal`, `conditional=purple`, `nogo=orange`.

### C. North-Star chip — every focus-area page must carry one
Sits directly under the page header. Dashed teal border, ★ icon prefix:
```html
<span class="north-star">北极星指标 · 关键决策时长 &lt; 60 秒</span>
```

### D. Boundary band — `不做` / `做` contrast
Two cards side-by-side. Left = orange dashed, body has line-through. Right =
teal solid, body uses `<span class="hl">关键词</span>` for accent4 emphasis:
```html
<div class="boundary-band">
  <div class="boundary-no">
    <span class="pill">不做</span>
    <p class="body">为单点客户定制非通用功能</p>
  </div>
  <div class="boundary-yes">
    <span class="pill">做</span>
    <p class="body">投入到 <span class="hl">5+ 客户共有的</span> 通用能力</p>
  </div>
</div>
```

### E. Fork visualization — 1 input → N branches
Don't use a 1/2/3 sequence diagram. Structure: input card → engine badge with
ACCENT4 pulse → Y-fork SVG → N branch cards in a row. Hand-write the SVG
for now; a helper is on the roadmap.

### F. Evolution chip — `现阶段 → 未来`
Compact two-row block, `white-space: nowrap` per row, dashed border:
```html
<div class="evolution-chip">
  <span class="stage-tag">CURRENT</span><span class="stage-body">中心化协同 + 部门工作流</span>
  <span class="stage-tag">FUTURE</span><span class="stage-body is-future">联邦化协同 + 跨域 AI 工作流</span>
</div>
```

### G. Two-track structure — one role, parallel tracks
Two stacked sub-blocks per role. Each sub-block: 3 px left color bar + short
label pill + body. Use for "PM 既负责 X 也负责 Y" duality.

### H. Iron 4-corners (铁四角) — 2×2 grid + center node
Four cards in a 2×2, an absolutely-positioned circle in the middle, four SVG
guide lines from center to each card's inner edge. Each card carries: pill +
serial numeral top-right + lead + body + key-deliverable chips + hand-off
indicator. Use for "四个不可分割的协同角色".

### H+. Two-hand architecture (心脏图) — `two-hand-arch`
Use when the value proposition is "we do exactly TWO things, on a shared
base, for a single decision-maker". 4-tier vertical structure: top
decision-maker crown → SVG curved-dashed lines (blue + teal) → two hands
(left blue tinted, right teal tinted) each with 3 numbered items → bottom
base (the underlying tech stack). Brand palette only — NEVER imitate
v2-style blue+orange split; use blue+teal which matches the feishu master.

```html
<div class="two-hand-arch">
  <div class="arch-top">
    <svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>
    品牌总部 · CEO / 销售 VP / 渠道总监
  </div>
  <div class="arch-lines">
    <svg viewBox="0 0 800 60" preserveAspectRatio="none">
      <defs>
        <linearGradient id="archL" x1="0%" x2="100%"><stop offset="0" stop-color="#3C7FFF"/><stop offset="1" stop-color="#3C7FFF" stop-opacity=".3"/></linearGradient>
        <linearGradient id="archR" x1="0%" x2="100%"><stop offset="0" stop-color="#33D6C0" stop-opacity=".3"/><stop offset="1" stop-color="#33D6C0"/></linearGradient>
      </defs>
      <path d="M400,0 Q400,30 200,60" stroke="url(#archL)" stroke-width="2" fill="none" stroke-dasharray="6 6"/>
      <path d="M400,0 Q400,30 600,60" stroke="url(#archR)" stroke-width="2" fill="none" stroke-dasharray="6 6"/>
    </svg>
  </div>
  <div class="arch-hands">
    <div class="arch-hand left">
      <div class="arch-hand-title"><h3>左手 · X</h3><span class="em">EN MOTTO</span></div>
      <div class="sub">一句解释左手做什么</div>
      <div class="arch-items">
        <div class="arch-item"><span class="n">1</span>第一项 — 一句话效果</div>
        <div class="arch-item"><span class="n">2</span>第二项</div>
        <div class="arch-item"><span class="n">3</span>第三项</div>
      </div>
    </div>
    <div class="arch-hand right">
      <div class="arch-hand-title"><h3>右手 · Y</h3><span class="em">EN MOTTO</span></div>
      <div class="sub">一句解释右手做什么</div>
      <div class="arch-items">
        <div class="arch-item"><span class="n">4</span>第一项</div>
        <div class="arch-item"><span class="n">5</span>第二项</div>
        <div class="arch-item"><span class="n">6</span>第三项</div>
      </div>
    </div>
  </div>
  <div class="arch-base">底座 · 飞书 IM · 文档 · 多维表格 · 审批 · 知识库 — <b>天然一体</b></div>
</div>
```

### I. 6-step pipeline timeline
Top horizontal rail (gradient line + 6 dots, last dot teal). Below: 6 columns
with step number, EN, ZH, 3 bullets each. Final column gets accent4 stroke +
shadow. Use for end-to-end multi-stage flows that need labels.

### J. Three-color principle band — `principle-band`
```html
<div class="principle-band">
  <span class="principle" data-color="teal">专项优先</span>
  <span class="principle" data-color="blue">相邻扩展</span>
  <span class="principle" data-color="purple">战略例外</span>
</div>
```
Each principle prefixed by a glowing dot in its own color.

### K. 1+1 vs 1+1+N boundary tags — tenant/mode choice
Two side-by-side tags. Current mode highlighted; alternative mode rendered
with `text-decoration: line-through`. Use for "我们当前做 1+1; 不做 1+1+N".

### L. North-Star Map — `north-star-map`
N-up survey of parallel projects / initiatives in a single slide. Each card
distills one project to its essentials: **idx → 项目名 → 北极星指标 →
核心售卖 → 3 个 sub-capability tag chip**. Use this on the "deck-level
overview" slide right after the agenda / section divider — it gives the
viewer a single-frame mental model before each project gets its own deep-dive.

Markup:
```html
<div class="north-star-map" style="--cols:5">
  <div class="ns-card is-blue is-hero">     <!-- .is-hero highlights the lead card -->
    <span class="idx">01</span>
    <h4>门店管理</h4>
    <span class="star-label">北极星指标</span>
    <span class="star">门店坪效</span>
    <span class="core-label">核心售卖</span>
    <span class="core">千店千面个性化</span>
    <div class="tags">
      <span class="tag-chip">人 · 排班</span>
      <span class="tag-chip">货 · 菜单</span>
      <span class="tag-chip">场 · 陈列</span>
    </div>
  </div>
  <div class="ns-card is-violet">
    <span class="idx">02</span>
    <h4>内容营销</h4>
    <span class="star-label">北极星指标</span>
    <span class="star">广告投放 ROI</span>
    <span class="core-label">核心售卖</span>
    <span class="core">素材全生命周期</span>
    <div class="tags">
      <span class="tag-chip">内容洞察</span>
      <span class="tag-chip">内容生成</span>
      <span class="tag-chip">IP 探针</span>
    </div>
  </div>
  <!-- repeat for ns-card.is-teal / .is-purple / .is-orange -->
</div>
```

Tonal variants (`.is-blue / .is-violet / .is-teal / .is-purple / .is-orange`)
recolor the idx numeral and tag chip text. Keep them in deck order so the eye
can scan left-to-right by accent. Set `--cols` (default 5) to adjust grid
density: 4-up for shorter narrative arcs, 6-up only when content stays terse.
**Why this beats a comparison table**: a table forces the eye to read across;
the map lets each card breathe and treats every project as a peer. For "5
专项" or "4 战场" content this is the strongest single-slide overview shape.

### M. Adjacency-scenes grid — `scene-grid`
3×2 = 6 cards (or `--cols` adjusted) showing how a single principle / product
applies across **N adjacent industry domains**, with a quantified **economic
lever** per scene. Each card carries:
- a top accent bar (3 px, per-card color)
- an icon tile + scene name (one row)
- a divider
- 个性化对象 / 适用对象 label
- a one-line description of WHAT is personalized
- a `.sc-lever` callout with a **bold `<em>` for the impact number**
  (e.g. `经济杠杆 · <em>报损率 ↓1pp = 头部一年增利 1-2 亿</em>`)

Markup:
```html
<div class="scene-grid" style="--cols:3">
  <div class="scene-card is-blue">
    <div class="sc-top">
      <span class="sc-icon"><svg viewBox="0 0 24 24" stroke="currentColor"
        stroke-width="1.6" fill="none" stroke-linecap="round"
        stroke-linejoin="round"><path d="M3 7h18l-2 12H5L3 7Z"/>
        <path d="M8 7V5a4 4 0 0 1 8 0v2"/></svg></span>
      <span class="sc-name">生鲜超市</span>
    </div>
    <hr>
    <span class="sc-label">个性化对象</span>
    <span class="sc-obj">千店千策订货 · 加工 · 临期 · 调价</span>
    <span class="sc-lever">经济杠杆 · <em>报损率 ↓1pp = 头部一年增利 1-2 亿</em></span>
  </div>
  <div class="scene-card is-violet">
    <div class="sc-top">
      <span class="sc-icon"><svg viewBox="0 0 24 24" stroke="currentColor"
        stroke-width="1.6" fill="none" stroke-linecap="round"
        stroke-linejoin="round"><rect x="3" y="6" width="18" height="14" rx="2"/>
        <path d="M7 6V4h10v2"/><path d="M3 11h18"/></svg></span>
      <span class="sc-name">便利店选品</span>
    </div>
    <hr>
    <span class="sc-label">个性化对象</span>
    <span class="sc-obj">千店千策的 SKU 组合</span>
    <span class="sc-lever">经济杠杆 · <em>单店日销提升 5%+</em></span>
  </div>
  <!-- 4 more scene-cards … -->
</div>
```

The lever is the rhetorical hook — without a real, quantified impact number
this layout collapses into a generic "list of use cases". If you can't fill
in a credible `<em>` value for a scene, drop it from the grid; six soft
scenes are weaker than three hard ones. Per-card tonal variants
(`.is-blue / .is-violet / .is-teal / .is-purple / .is-orange`) recolor the
accent bar, icon, and label; keep adjacent cards in different tones so the
viewer can pre-attentively count the panels.

### N. 5-up Overview with Hero Numerals — `overview-grid` (2026-05-16)

Use this for **"this month / quarter / week, 5 things to push forward"**
overview pages. Each card carries a large decorative numeral (88 px Hero
exception) + a bold Title-tier topic name + one-line description body.
The hero numeral signals "5 parallel directions" pre-attentively; the
topic name takes the focal weight.

This pattern was evolved during the 2026-05-16 南区周会 session through
~10 iterations of size / weight / treatment tuning. The final values:

| Element | Size | Weight | Color | Notes |
|---|---|---|---|---|
| Page title (top, page-wide) | 48 Title | 700 | #fff | Standard |
| Card numeral 01–05 | **88 Hero** | 500 medium | 55% semi-transparent brand color | `/* allow:typescale */` |
| Card topic name | **48 Title** | 700 | #fff | Bold dominates within card |
| Card description | 24 Body | 500 medium | #fff @ 92% | Margin-top auto pushes to bottom |

5 cards in a horizontal `grid-template-columns: repeat(5, 1fr)`, gap 24px,
each card `min-height: 320px` to give numeral + title + body proper
breathing room.

Markup:
```html
<div class="slide" data-layout="content-3up" data-screen-label="01 五个推进方向"
     data-slide-key="weekly-overview">
  <div class="wordmark"></div>
  <div class="header">
    <h2 class="title-zh">本周南区周会 · 五个推进方向</h2>
  </div>
  <div class="stage">
    <div class="grid overview-grid">
      <div class="card overview-card is-c1">
        <span class="ov-num">01</span>
        <span class="ov-name">商机管理</span>
        <span class="ov-desc">Q2/Q3 大扫除 · 周末截止</span>
      </div>
      <!-- 4 more cards: is-c2 / is-c3 / is-c4 / is-c5 -->
    </div>
  </div>
</div>
```

Per-card tonal variants `.is-c1` (blue) / `.is-c2` (violet) / `.is-c3`
(teal) / `.is-c4` (orange) / `.is-c5` (neutral white) recolor the
border + numeral. Keep the SAME color → SAME topic across the deck (if
slide 1 says 商机管理 = blue, then slide 2 which is a deep-dive on 商机
should also lead with blue).

**Why this pattern needed naming**: a 5-up overview is structurally
different from a 3-up content layout (Pattern A) or a generic list. The
hero numeral makes each card READ as a "chapter" rather than a "cell".
Without the hero treatment, "5 things" devolves into "5 small cards",
and the page reads as "a list" not "an overview".

**Don't use this for**:
- 3 or 4 cards (too few — the hero numeral overpowers; use Pattern A
  content-3up or content-2col instead)
- 6+ cards (too many — hero numerals visually fight; collapse to
  smaller scale or split across two slides)
- Cards with > 2 lines of body (cards become tall and the hero numeral
  loses dominance; use Pattern A with regular sizes instead)

---

## BF10–12 — Alignment defenses (2026-05-16)

Framework CSS now ships three alignment defaults that catch common
"why doesn't it line up" footguns. All three apply automatically; the
notes here are for context when authors hand-write similar layouts.

### BF10 — Mixed-size row uses `align-items: center`, not baseline

When a row has elements at very different font sizes (ratio > 1.5×,
e.g. a 48 px numeral followed by 24 px body), `align-items: baseline`
LOOKS misaligned — the baselines do align but the visual centers don't.
Center alignment puts the smaller element at the visual middle of the
bigger element's line-box.

Apply via `.mixed-row` utility class:
```html
<div class="mixed-row">
  <span class="num">01</span>
  <p class="text">不留意向沟通阶段的商机...</p>
</div>
```

Default: `display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 22px`.

### BF11 — Hero zone content centered, not flex-start

For big-stat (and similar 2-col-hero) layouts, the LEFT column's
content (hero number + caption + secondary stat) should be visually
centered within its half — not hugging the slide's left edge.

Framework default: `.slide[data-layout="big-stat"] .hero { align-items: center; text-align: center; }`. Don't override unless you intentionally
want left-flush (rare; for that, use `.slide[data-layout="content-2col"] .col-text` which is left-flush by design).

### BF12 — Multi-card column equal-height

When `.col-text` / `.col-visual` contain multiple stacked cards (2–3
typical), the cards should fill the column height equally — otherwise
left / right columns of a 2-col grid mis-align across the page.

Framework default: `.canonical-card / .news-card / .data-panel` get
`flex: 1` when they're direct children of `.col-text` / `.col-visual`.
Heights balance automatically; no per-deck override needed.

### BF13 — Present-mode first-frame fallback must gate on `[data-js-ready]` (2026-05-17)

**Symptom**: navigating between content pages in present mode, the cover
(slide 1) **flashes underneath** for a frame or two — most noticeable
on slower transitions or when screenshotting via headless Chromium.
The cover bleeds through as a faint background even on slide 13 / 22 /
whichever the user just navigated to.

**Root cause**: framework CSS provides a "pre-JS first-frame visible"
fallback so users don't see a black screen during the gap between
CSS-applied (all frames opacity:0) and JS-loaded (active frame gets
`.is-current`). The original rule was:

```css
/* WRONG — fallback stays alive forever */
.deck[data-mode="present"] .slide-frame:first-child {
  opacity: 1; pointer-events: auto;
}
```

The `:first-child` selector has equal specificity to `.is-current`, but
this rule was DECLARED LATER in the stylesheet, so it kept winning even
after JS marked another frame as `.is-current`. The first frame
remained `opacity: 1` underneath every subsequent slide.

**Defense (CSS + JS, mandatory pair)**:

```css
/* feishu-deck.css — gate the fallback so it deactivates after JS init */
.deck[data-mode="present"]:not([data-js-ready]) .slide-frame:first-child {
  opacity: 1; pointer-events: auto;
}
```

```js
/* feishu-deck.js — set [data-js-ready] AFTER initial goTo() */
if (!readHash()) goTo(deck, frames, 0, false);
deck.setAttribute('data-js-ready', '');
```

**How it works**:
- Before JS runs: deck has no `[data-js-ready]` → fallback active →
  first frame visible → no black screen during the ~50 ms init window.
- After JS runs: deck gains `[data-js-ready]` → fallback DEselects →
  only `.is-current` frame is opacity:1 → no bleed-through.

**Don't break this pair**:
- If you simplify CSS to "always show first frame", flash returns.
- If you simplify CSS to "never show first frame", initial black screen returns.
- If JS sets `[data-js-ready]` too early (before first `goTo`), brief black flash.
- If JS forgets to set `[data-js-ready]`, fallback never deactivates.

**Postmortem (2026-05-17)**: showcase eval surfaced the flash during
screenshot capture. Initial fix was a `page.add_style_tag` injection
inside `validate.py`'s screenshot loop — only fixed screenshots, not
the real browser experience. Root fix moved to framework: gate the
CSS fallback behind `:not([data-js-ready])`. Validator workaround
removed (commit after BF13 lands).

### BF14 — abs-positioned chrome override must reset the OTHER anchor (2026-05-23)

**Symptom**: a deck adds a local `<style>` override for a `position:
absolute` chrome element (hint pill, badge, chip, icon) and sets ONLY
ONE vertical anchor (`top: Xpx;` *or* `bottom: Ypx;`) without resetting
the other. A less-specific framework rule already declared the OTHER
anchor — both are now active. Browser computes height as
`parent.height - top - bottom`, regardless of content. The chrome
element silently stretches to ~80–95 % of the parent height.

**Postmortem (2026-05-23)**: AI-consumer-growth deck slide 6 (and 8,
30 — three iframe-embed slides). The deck's `<head> <style>` block
had an obsolete override (predating the framework's 2026-05-22
iframe-embed support):

```css
/* override (wrong — only declares top) */
.slide[data-layout="iframe-embed"] .iframe-wrap > .iframe-hint {
  position: absolute; top: 16px; right: 16px;
  display: inline-flex; padding: 8px 14px;
  /* no `bottom:` declared → inherited `bottom: 18px` still active */
}
```

Framework rule still applied for `bottom`:

```css
/* framework (extra-layouts.css) */
.slide[data-layout="iframe-embed"] .iframe-hint {
  position: absolute;
  bottom: 18px; right: 18px;
  display: inline-flex; padding: 10px 18px;
}
```

Result: hint pill rendered at **764 px tall** instead of ~32 px.
User-visible: "进入页面，报告可滚动查阅这个的高有问题，非常大".

**Two valid fixes**:

1. **Delete the obsolete override entirely** — if the framework
   already has the layout's rules covered (which is what we did
   here, since the override predated framework iframe-embed support).
2. **In the override, redeclare BOTH anchors** —
   `top: 16px; bottom: auto;` (or use `inset:` shorthand to set all
   four). This makes the override self-contained and immune to
   future framework rule changes.

```css
/* fixed pattern (if you must override) */
.slide[data-layout="iframe-embed"] .iframe-wrap > .iframe-hint {
  position: absolute;
  top: 16px;       bottom: auto;          /* MUST redeclare bottom */
  right: 16px;     left: auto;            /* and left, for symmetry */
  display: inline-flex; padding: 8px 14px;
}
```

**Defense (validator)**: `R-VIS-ABSPOS-DUAL-ANCHOR` in `validate.py`
visual audit catches this automatically. For every
`position: absolute` non-layout element in the deck, the audit:
1. measures rendered height (`h1`)
2. temporarily sets `style.bottom = 'auto'` and re-measures (`h2`)
3. restores the original `style.bottom`
4. flags if `h1 - h2 >= 30 px` AND `h1 >= 2 × h2` (height collapsed
   by ≥ 30 px AND ≥ 2× ratio when bottom was neutralized → CSS DID
   declare `bottom` AND it was driving the height)

Why mutation test: `getComputedStyle().bottom` returns the USED
value (always px) for any positioned element, NOT the declared
value. There is no static way to tell from JS whether `bottom`
was declared in CSS or computed by the layout engine. Mutating
inline `style.bottom = 'auto'` (max specificity) flips the resolver
into the "bottom unset" path and exposes whether CSS had it set.

**Excluded from the audit** (legitimate full-bleed by design):
- Class denylist: `.stage / .stack / .toc / .flow / .nodes / .grid /
  .table-wrap / .header / .footer / .col-text / .col-visual /
  .iframe-wrap / .desktop-frame / .phone-frame / .phone-screen /
  .arch-stack / .panel / .slide-frame / .deck / .two-hand-arch /
  .pipeline / .steps` — these are layout shells; vertical span is
  intentional.
- Element opt-out: `data-allow-dual-anchor` attribute — set this
  on a custom-class element that genuinely needs both top + bottom
  active (e.g. a true full-height side-rail or a fill-parent overlay
  drawing the entire canvas).

**Authoring rule**: when you write a `<style>` override for an
absolutely-positioned chrome element AND the same element is targeted
by framework CSS (any `.slide[data-layout=...] .chrome-class` rule),
either:
- Drop the override (let the framework take over), OR
- Redeclare all four anchors in the override (top + bottom + left +
  right, using explicit `auto` for the ones you don't want active),
  OR use `inset:` shorthand.

Half-redeclared overrides on positioned elements are the same class
of bug as R47 (variants that change `display` / `flex-direction`
without redeclaring `align-items` + `justify-content`). The fix
discipline is the same: **self-contained overrides, no partial
property declarations on positioning / layout properties**.

### BF15 — hiding framework `.header` requires content rebalance (2026-05-24)

**Symptom**: a slide hides `.header { display: none }` in per-page CSS to gain
vertical space, AND sets `.stage` with a custom `top` value in the "danger
zone" (typically `top: 40-60px`, neither close enough to slide edge to look
like a deliberate "snap to top" nor matching the framework anchor at
`top: 61px`). Result: an empty dark area at slide y=0..N appears as
「上面一条黑色 · 背景没有全」 — especially with diagonal-glow decor
(mix-glow's bright zones are at opposite corners, leaving the top edge
darker).

**Why this happens**: the framework's unified
`.slide[data-layout=...] .header` rule positions title at slide y=61 — a
deliberate visual anchor shared by every content slide. When you hide
`.header`, the slide loses that anchor; if your content doesn't replace
its visual function, the gap is perceived as missing background, not as
intentional whitespace.

**The rule**: when hiding framework `.header`, the slide MUST do ONE of:

| Choice | When to use | Effect |
|---|---|---|
| (a) Restore `.header` (drop `display:none`) | Default safe path — you usually can keep `.header` AND tighten the rest | Title sits at framework anchor y=61; visually consistent with sibling slides |
| (b) Snap `.stage { top: ≤32 }` | Hero / full-bleed feel — content extends near slide edge | Content sits at slide top edge; no perceived gap |
| (c) Align `.stage { top: 61px }` | Most common — sibling consistency | First child of stage sits at the same y as other slides' titles |
| (d) Add a visible top decoration as `.stage`'s first child (eyebrow / brand bar / decorative line) | Slide needs unique top treatment | Decoration occupies the would-be-gap |

**Anti-pattern**: `.header { display: none }` + `.stage { top: 40-60 }`
without a top decoration. Visual gap of 40-60 px reads as "missing bg".

**Validator enforcement**: `audit_empty_header_zone` (rule
**R-EMPTY-HEADER-ZONE**) fires `warn` when a per-page CSS block hides
`.header` AND sets `.stage top` to a value > 32 AND ≠ 61 — i.e. NOT
snapped-to-top AND NOT framework-anchored. The rule scans every `<style>`
block scoped to a `data-slide-key`.

**Postmortem (2026-05-24)**: slide `management-clone-flywheel` had
`.header { display: none }` + `.stage { top: 50px }` + `mix-glow` decor
(whose bright zones are at opposite corners, leaving the top edge dark).
User reported 「上面有一条黑色,背景没有全」. Took 3 round-trips:
50→16 "snap to top" overshot past framework anchor; 16→61 finally matched
sibling slides. After codifying as R-EMPTY-HEADER-ZONE, validator surfaces
the pattern up front so authors hit it once at lint time.

Validator finding 2026-05-24: 8 other slides in the kangshifu deck (and
~same in source) use the same pattern (mostly `top:50` + hidden header,
including `flow-grows-itself` which uses mix-glow same as 22). They may
have the same "black zone" perception that just hadn't been spotted yet.
Run validator → review → fix proactively before next demo.

### BF15.1 — diagonal-glow decor + letterbox = visible edge at slide top (2026-05-24)

**Symptom (follow-up to BF15)**: even after pulling `.stage` top to 61 to
match framework anchor, slide 22 in fullscreen on a non-16:9 monitor
**STILL** showed "上面有黑色的边" — a visible horizontal seam at the slide
top boundary.

**Why**: the decor `::before` pseudo-element (mix-glow / orange-spark / any
decor with a glow source near the top) is bounded by `.slide` dimensions.
The slide-frame's bg image (`lark-content-bg.jpg`) extends into the
letterbox area on non-16:9 viewports, but the decor tinting does NOT.
Result: a sharp luma jump where decor tinting begins at the slide top edge.

Pixel proof at 1920×1200 viewport, col 1700 (right side, mix-glow purple
zone):

```
y=58 (letterbox): RGB(47, 35, 74)  luma=43
y=60 (slide top): RGB(69, 50,106)  luma=62   ← 19 luma jump
```

The 19-luma jump is the visible edge.

**Fix pattern** (slide-specific, applied via per-page CSS using `:has()`):

```css
/* Move the decor from .slide ::before onto .slide-frame ::after so it
   covers the letterbox + slide uniformly. */
.slide-frame:has(> .slide[data-slide-key="K"])::after {
  content: '';
  position: absolute; inset: 0;
  background-image: /* same radial-gradient as the original decor */;
  pointer-events: none; z-index: 0;
}
/* Suppress the slide's own ::before — otherwise it stacks ON TOP of the
   frame::after inside the slide, doubling the tint and re-creating the
   edge at the slide boundary. */
.slide[data-slide-key="K"][data-decor~="mix-glow"]::before {
  background-image: none;
}
```

After applying: luma is uniform 40-44 across the y=60 boundary (no jump).
The decor reads as a single continuous gradient from viewport edge to
viewport edge.

**When this matters**: only on viewports where letterbox is visible
(non-16:9 monitor in fullscreen). On 16:9 monitor (slide fills viewport),
the slide top edge IS the viewport top edge → no letterbox → no edge.

**Affected decor list**: any decor whose `radial-gradient` has its bright
zone near the slide top edge (`y <= ~20%`):
- `mix-glow` (`at 92% 8%`) — explicitly seen on slide 22, 43
- `orange-spark` (`at 88% 18%`) — likely affected, untested

Not affected (glow at bottom or center): `violet-glow`, `teal-glow`,
`blue-glow`.

**Framework-level fix (deferred)**: the right long-term fix is to make
`data-decor` apply to `.slide-frame::after` directly (via the same `:has()`
selector pattern) rather than only `.slide::before`. That would make the
decor uniformly cover the viewport for every slide automatically. Out of
scope for this fix; tracked as a framework TODO. Until then, slides with
top-bright decors need the per-slide `:has()` override above.

---

## Slide media auto-restart + auto-sound on enter (framework behavior, 2026-05-24 · sound 2026-05-25)

**Problem**: present mode keeps EVERY `.slide-frame` in the DOM at once
(only `.is-current` toggles visibility). So a `<video autoplay loop>` on a
non-first slide **starts playing on page load while its slide is still
hidden**, and by the time the presenter navigates to it the clip is at
some arbitrary point mid-loop — never from the start. Same class of bug
hits CSS `@keyframes` animations (they run once on load and are finished
before you arrive). Reported on slide 11 of the kangshifu deck
(`<video ... autoplay muted loop>`); the same `<video autoplay>` pattern
exists in ≥ 5 decks and `@keyframes`/`animation:` in ≥ 10.

**Fix (in `feishu-deck.js`, automatic — no per-deck markup)**: a single
`MutationObserver` watches every frame's `class` attribute. It catches
EVERY navigation path (present-mode `goTo`, hash nav, prev/next buttons,
and the separate mobile-patch IIFE's direct `.is-current` toggles).

- **Enter** a frame → each `<video>` is reset to `currentTime = 0`, and
  if it carries the `autoplay` attribute it is `.play()`ed — **with sound
  unless it was authored `muted`** (`muted = false` only for un-muted
  videos). See the sound paragraph below.
- **Leave** a frame → its `<video>`s are `.pause()`d (stops hidden
  background looping AND any sound).
- On both transitions a `CustomEvent` is dispatched on the `.slide`:
  **`fs-slide-enter`** / **`fs-slide-leave`** (bubbling). CSS-keyframe
  decks that need to re-trigger an animation on revisit can listen for
  `fs-slide-enter` and toggle a class, OR — simpler, no JS — scope the
  animation to `.slide-frame.is-current .x { animation: … }` so re-adding
  `.is-current` re-applies (and thus restarts) the animation.

**Sound (2026-05-25 · conservative default)**: an autoplay video plays
**with sound** when its slide is entered **only if it was authored WITHOUT
a `muted` attribute**. The framework sets `muted = false` before `.play()`
for those. An authored `muted` attribute is **respected as "keep silent"**
(same as `data-keep-muted`) — so already-shipped decks written per the old
"`autoplay muted` to enable autoplay" guidance keep playing silently and
do NOT suddenly blare audio when they pick up the updated `feishu-deck.js`.

Browsers block unmuted autoplay until a user gesture — but in present mode
**slide navigation is itself a gesture**, so unmuting succeeds on every
navigated-to slide. The one pre-gesture case (deck opens directly on a
video slide, before the viewer clicks/keys anything) gracefully falls back
to muted; a one-shot `pointerdown`/`keydown`/`touchstart` listener
(`upgradeMediaSound`) then turns sound on at the first input **without
resetting the playhead** (so the enabling click doesn't restart the clip).
Leaving a slide pauses its videos, so no two slides' audio overlap.

**Opt out**:
- `data-no-restart` — don't reset/pause this video on slide enter/leave
  (keeps its position across visits — rare).
- `data-keep-muted` — keep this video **silent** even though it has no
  `muted` attribute. Mostly redundant now that authored `muted` is also
  honored, but useful as an explicit-intent marker on a clip you author
  without `muted` but still want silent.

**Authoring guidance**:
- Want a video that plays from the top WITH SOUND each time the slide is
  shown → give it `autoplay` **without `muted`** (add `loop` to repeat
  while on screen). The framework resets the playhead and unmutes it.
- Want a silent / decorative / ambient background loop → keep the `muted`
  attribute: `autoplay loop muted`. The framework leaves it alone.
- Want a CSS animation to replay on revisit → scope it to
  `.slide-frame.is-current` (preferred) or hook `fs-slide-enter`.

**Caveat — existing decks**: this fix lives in the skill's
`feishu-deck.js`. Decks that link to the skill copy get it on next load.
Decks that shipped their OWN `output/assets/feishu-deck.js` (copy-assets
snapshot) or are already published (e.g. `feishusolution/<deck>/assets/`)
keep their old copy until re-run through `copy-assets.py` / re-deployed.

---

## CJK 换行平衡 / 末行孤字防治 (2026-05-25)

**Problem**: CJK 文本换行后,末行只剩一两个字("市场传媒"→市场/传媒、
"渠道适配感知"→渠道适配感/知),或两行上长下短(第一行很长、第二行很短)。
投影上很碎、不像一个整体。用户明确不接受这种孤字/失衡。

**两层防护:预防(CSS) + 检测(validator),不是二选一。**

### 1 · 预防 — `text-wrap: balance`(框架已默认开一批)

`feishu-deck.css` 有一条 **skill-level baseline**(`/* text-wrap baseline */`),
给常见标题/卡名类(`.ctitle / .card-name / .role-name / .ns-card h4 /
.scene-card .sc-name / .feat-label / .bot-name / .arch-label / .dir-name`)
开了 `text-wrap: balance`。balance 让换行后各行字数尽量相等,把 5+1 重排成
3+3,孤字自然消失,**纯 CSS、零 JS、零成本**。

- 如果某页用的是 **deck 专有类**(渲染器/手写产生的 `.meta-value / .slogan /
  `.ctx / .ts-time` 之类),baseline 没覆盖到 → 在该 deck 的 `<style>` 里补一条
  `.deck .slide-frame .slide :is(.类A,.类B) { text-wrap: balance; }` 即可。
- **balance 的硬限制(必须知道)**:
  - 元素里有 `<br>` 强制换行 → **balance 整体失效**(Chromium 行为)。别在会
    换行的标签里用 `<br>` 拼副标题;要副标题就用 `display:block` 子元素。
  - 容器是**固定宽 / 被 flex 夹窄**且文本本身就超出可用宽 → balance 也救不了
    (它只能重排、不能变出空间)。

### 2 · 检测 — `R-VIS-ORPHAN`(`--visual`,WARN)

`visual-audit.js` + `validate.py` 新增 `R-VIS-ORPHAN`:present 模式下用 Range
量每个 CJK 叶子文本元素的行盒,命中两类:

- **orphan**:换 ≥2 行且末行 ≤ ~1.45 字宽(末行单字)。
- **imbalanced**:短标签/标题(CJK ≤ 14 字)换 2-3 行,且末行 < 最宽行的 38%。

**跳过**(避免误报):有 block 级子元素的(`.role` 这类故意拆行的副标)、SVG
`<text>`、mockup 容器内文字、`white-space: nowrap` 的。**只审 deck slide
本身——`<iframe>` 里的原型是独立文档,审计够不着**(原型要手改,见下)。
长正文 2 行末行天然短,不算缺陷,已被 CJK≤14 闸挡掉。

### 3 · 被 R-VIS-ORPHAN 点名后的修复阶梯

1. **该类没 balance** → 加 `text-wrap: balance`(报告里 `bal != 'balance'` 即此情形;
   若加了仍不生效,多半被更具体的选择器/另一条 `!important` 压住,提级覆盖)。
2. **已 balance 仍孤字 = 容器约束**(报告里 `bal == 'balance'`):
   - 首选**加宽容器**。例:`senior-tour-leader-day` 时间轴首列固定 `200px`,
     最长活动名 "下午拜访 · 收单回办公室" 18px 要 206px、内容区只有 178px →
     必溢出。把 `grid-template-columns: 200px 1fr 1fr` 改成 `236px 1fr 1fr`
     就全单行了。**别靠缩字号**:缩字号只是把溢出在各行间搬家(whack-a-mole,
     这行修好那行又冒),且常踩 R20/R-VIS-TIER 的 off-tier。
   - ≤4 字主标签放不下 → `white-space: nowrap` 逼单行 + 把尾词用 `display:block`
     拆成副标行(见原型例子)。
   - 实在无解再考虑改文案让上下两行字数接近(内容是甲方的,慎改)。

### 4 · 原型 `<iframe>` 里的标签(检测够不着,手动按同款规则)

原型是独立 HTML,R-VIS-ORPHAN 审不到,得手写时就避坑。典型:`sps-coord-pain`
原型的 `.hub-node`(固定 148px,内含 avatar + `.hub-label`)里 "市场传媒" 4 字
被 avatar 挤到换行。修法 = 同款阶梯:**缩小 avatar 腾宽 + 主标签 `white-space:
nowrap` 逼单行**(`.role`"企划"本就 `display:block` 落副标行),量出可用宽再定
字号(量 → 定 → 验,别拍脑袋)。

---

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

Where the design system has a reusable HTML+CSS combo, treat it as a "helper".
The CSS already ships the styles; the markup is what you copy. These are the
named helpers; expand each to the recipe block above when generating a deck:

| Helper                           | Use for                              | CSS class              |
|----------------------------------|--------------------------------------|------------------------|
| `north_star_chip(metric)`        | Pin every focus area to its KPI      | `.north-star`          |
| `verdict_card(go/cond/nogo, …)`  | Decision-judgment cards              | `.verdict-card[data-verdict=…]` |
| `boundary_band(no_text, yes_text)`| 不做 / 做 contrast                   | `.boundary-band`       |
| `evolution_chip(now, future)`    | 现阶段 → 未来                        | `.evolution-chip`      |
| `principle_band(items)`          | Three-color strategy principles      | `.principle-band`      |
| `phone_frame_iframe(src)`        | Mobile prototype embed               | `.phone-frame`         |
| `desktop_iframe(src)`            | Desktop prototype embed + hint       | `.desktop-frame`       |
| `aurora_background()`            | Add `data-decor="aurora"` on `.slide`| `[data-decor~="aurora"]` |
| `fullscreen_button()`            | Already shipped in `.deck-ui`        | `.deck-controls .ctl.fs` (auto) |
| `north_star_map(N, cards)`       | Pattern L · N-up project survey, idx + title + 北极星 + 核心售卖 + 3 chips | `.north-star-map / .ns-card` |
| `scene_grid(cards)`              | Pattern M · 3×2 industry-adjacency grid with quantified economic lever per scene | `.scene-grid / .scene-card` |

Roadmap helpers (no CSS yet — write the markup by hand and follow the spec):
fork visualization, iron-4-corners, 6-step pipeline timeline, two-track
structure, 1+1 vs 1+1+N boundary tags.

---

## Richness primitives (v1.3) — promoted from the deck_v3 reference

The skill ships a second tier of helpers that exist specifically to STOP the
agent from delivering an austere "skeleton" deck. They were promoted from the
hand-built `deck_v3_feishu` reference build — the highest-fidelity feishu
deck the team had shipped at the time. **Use them by default**, not "if you
have time". A slide that cites a number without `.kpi-strip`, a closing without
`.cta-box`, or a transform without `.ui-wave + .report-item` is a slide that
under-delivers on what the skill is capable of.

### MANDATORY: wrap body + helpers in `<div class="stage">`

`.grid` / `.flow` / `.nodes` / `.toc` / `.table-wrap` are **absolutely
positioned** by their layout rules. So if you place a `.pullquote` /
`.cta-box` / `.kpi-strip` / `.lede` as a *direct sibling* of the body
container under `.slide`, the helper falls into normal flow at the TOP
of the slide canvas — overlapping the header. Visually broken.

The fix is to wrap the body container AND its helpers in `<div class="stage">`:

```html
<div class="slide" data-layout="content-2col" data-decor="blue-glow">
  <div class="wordmark">飞书</div>
  <div class="header"><h2 class="title-zh">…</h2></div>
  <div class="stage">                       <!-- ← MANDATORY when using helpers -->
    <p class="lede">…</p>                   <!-- optional intro -->
    <div class="grid">…body cards…</div>    <!-- body, now flows naturally -->
    <p class="pullquote">…</p>              <!-- helper, flows below body -->
    <div class="cta-box">…</div>            <!-- helper, flows below pullquote -->
  </div>
</div>
```

`.stage` becomes the absolutely-positioned body zone (top:220, bottom:110,
left/right:96), and inner `.grid` / `.flow` / `.nodes` / `.toc` /
`.table-wrap` override their default absolute positioning to flow inside
the stage's flex column. Helpers stack naturally below the body.

Layouts that support `.stage` wrapper: `content-2col`, `content-3up`,
`process`, `timeline`, `table`, `agenda`, `stats`. (Cover / end / image-text /
big-stat have their own `.stage` semantics — see their layout recipes.)

For `timeline`: when wrapped in `.stage`, the `.axis` line stays as a direct
child of `.slide` (outside `.stage`) and auto-aligns to slide center.

If a slide has NO helpers (just body), you can omit `.stage`
without harm. Pre-1.3.2 decks (no `.stage` wrapper anywhere) still render
correctly via the legacy absolute positioning.

### When converting an external HTML deck (the failure mode this prevents)

Every primitive below maps to a v3-pattern the agent CAN'T just drop. If the
source deck has:

| Source has | You MUST use |
|---|---|
| Italic blockquote sealing the argument | `.pullquote` (default teal · `.is-orange / .is-blue / .is-violet`) |
| Customer testimonial cards with quotation glyphs | `.voice-card` (with `::before "「"`) |
| "Next step" CTA strip with a button | `.cta-box` + `.cta-btn` (`.is-teal` for promise framing) |
| Row of small KPI/metric mini-cards | `.kpi-strip` (set `--strip-cols`; tone via `.is-teal/.is-blue/.is-orange`) |
| ROI calculator / interactive sliders | `.calc` + `.calc-row` + `.calc-result` |
| Dashboard ROI rows / system list | `.ui-row` (`.val.up/.dn` for trend tone) |
| Alert banner with title + body | `.ui-alert` (orange-tone, fixed) |
| KPI tile with label + big number + delta | `.ui-kpi` (`.is-teal` for highlight variant) |
| Audio waveform (recording / call) | `.ui-wave` with 10 `<i>` bars (animated) |
| Tagged finding/insight rows (做得好 / 漏关键 / 建议) | `.report-item` (`.is-warn` orange · `.is-info` blue) |

> **Do NOT add `<div class="grid-bg"></div>` by default.** The class still
> ships for legacy decks, but the 飞书 master content layouts already use
> `lark-content-bg.jpg` (a subtle dark ambient gradient) as their background
> via `--fs-asset-content-bg`. Adding a dot-grid on top creates double-noise
> texture that makes the page feel busy and OFF-master. Only opt in to
> `.grid-bg` if a slide explicitly needs an additional engineered/technical
> backdrop (rare; e.g. a custom whitepaper layout). Default = clean.

**Drop a primitive → you've stripped meaning the source author put there.**
This is the lesson from v1 of the v3 conversion: validator-passing ≠ visually
faithful. Compliance and richness are both required.

### Card hover & tile gradient — already on by default

Every `.card` now:
- On hover: brighter background + 1 px blue glow ring (via `box-shadow:
  0 0 0 1px`) + accent border. **No `transform: translateY(...)`** — the
  transformed hit-area moves away from the cursor and creates a hover-flicker
  loop. Color + ring affords interactivity without moving the box.
- Has a **gradient blue→violet** `.tile` instead of a flat tinted square.
- Shows `.num` at 36 px / 700 (was inheriting smaller defaults).
- Shows `.cfoot` with dashed top border + accent arrow on the right.

If you write `<div class="card"><div class="head"><div class="tile">…</div>
<div class="num">01</div></div>…</div>`, you GET the v3 visual treatment for
free. There is no `.is-rich` modifier — richness is the default.

### Process step chevron — already on by default

Every `.step` inside a `[data-layout="process"] .flow` auto-renders a blue
chevron between cards. Last step and `data-variant="vertical"` auto-hide
the chevron. No markup change.

### Markup recipes (canonical)

```html
<!-- pullquote — caps a body grid with a thesis statement -->
<p class="pullquote">不是让你再投一个大系统,而是先请几个不要工位的同事。</p>
<p class="pullquote is-orange">不安抚,直接给解法。</p>

<!-- voice-card — testimonial inside a content-3up grid -->
<div class="voice-card">
  <p class="q">以前每天 8 点打开微信群看 200 条问题,现在群里是空的。精英销售终于能把时间放在打单。</p>
  <p class="who">某饮料品牌 · 华东大区销售经理</p>
</div>

<!-- cta-box — strong call-to-action tail strip -->
<div class="cta-box">
  <div class="l">
    <h3>下一步 · 免费 90 分钟诊断工作坊</h3>
    <p>解决方案架构师上门或线上,共同识别值得优先做的 1 个场景。</p>
  </div>
  <button class="cta-btn">启动诊断 →</button>
</div>

<!-- kpi-strip — 3-up metric row beneath body -->
<div class="kpi-strip">
  <div class="kpi"><div class="v is-teal">T+2 天</div><div class="l">费效比出数周期</div></div>
  <div class="kpi"><div class="v is-teal">全量</div><div class="l">异常自动筛(原抽查 5%)</div></div>
  <div class="kpi"><div class="v is-teal">3–5%</div><div class="l">预估可收回营销浪费</div></div>
</div>

<!-- calc — interactive ROI widget. needs ~12 lines of inline JS to wire up -->
<div class="calc">
  <div class="calc-row">
    <label>业务员人数</label>
    <input type="range" id="r1" min="100" max="5000" step="100" value="1000">
    <span class="v" id="v1">1,000 人</span>
  </div>
  <!-- ...more rows... -->
  <div class="calc-result">
    <div class="lbl">预计年化释放销售时间价值</div>
    <div class="amount" id="roi">6,300 万</div>
  </div>
  <p class="calc-hint">* 承诺的不是这个数字本身,而是每个变量的真实测量。</p>
</div>

<!-- ui-row + ui-alert + ui-kpi inside a ui-window -->
<div class="ui-window">
  <div class="ui-titlebar"><span class="ui-traffic-lights"><i></i></span><span>活动费效比 · 04-28</span></div>
  <div class="ui-body">
    <div class="ui-row"><span class="lbl">华东 · 大润发周末堆头</span><span class="val up">ROI 3.2x</span></div>
    <div class="ui-row"><span class="lbl">华北 · 餐饮渠道返点</span><span class="val dn">ROI 0.6x</span></div>
    <div class="ui-alert">
      <div class="t">异常自动标红</div>
      <h5>华北 · 12 家门店</h5>
      <p>照片疑似同时段同角度,销量环比未提升。已抄送大区经理。</p>
    </div>
    <div class="ui-kpi is-teal">
      <div class="t">本周自动核销</div>
      <div class="v">1,284</div>
      <div class="d">↑ 47% vs 人工 · 省 40 h/月</div>
    </div>
  </div>
</div>

<!-- ui-wave + report-item — audio→insights transform widget -->
<div class="ui-window">
  <div class="ui-titlebar"><span>INPUT · 一线拜访录音</span></div>
  <div class="ui-body">
    <div class="ui-wave"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
    <div>业务员小李 · 04-28 · 14:32 · 23 分钟</div>
  </div>
</div>
<div class="ui-window">
  <div class="ui-titlebar"><span>OUTPUT · 销冠视角复盘 · 5 分钟</span></div>
  <div class="ui-body">
    <div class="report-item"><span class="tag">做得好</span><div><b>主动倾听</b>,捕获备货过多的真实困境。</div></div>
    <div class="report-item is-warn"><span class="tag">漏关键</span><div>未识别<b>"再看看"</b>背后的退货风险信号。</div></div>
    <div class="report-item is-info"><span class="tag">销冠建议</span><div>立即提<b>调换新品 + 返点补贴</b>组合方案。</div></div>
  </div>
</div>

<!-- grid-bg — DO NOT add by default. The 飞书 master content background
     (lark-content-bg.jpg via --fs-asset-content-bg) already provides the
     ambient gradient. .grid-bg on top creates double-noise. Only opt in
     for engineered/technical layouts that need an explicit grid backdrop. -->
```

---

## Performance budget (hard rules — enforced by `audit_perf`)

A 13-slide deck should be lean. The skill ships with a perf budget enforced
by `validate.py audit_perf`. Each rule has a CSS or JS fix; none of them
require an external dependency.

| ID  | Budget | Hard cap | Fix |
|-----|--------|----------|-----|
| P50 | base64 in `<style>` ≤ 100 KB (default delivery) | 250 KB error | Use `bash build.sh` (linked); single-file mode requires `<meta name="fs-deck-mode" content="inline">` |
| P51 | `backdrop-filter: blur(N)` ≤ 10 px | warn always | Drop blur radius or replace with opaque rgba |
| P52 | `new ResizeObserver()` count ≤ 1 | warn at 2+ | One document-level RO with rAF batching, iterate frames in callback |
| P53 | `addEventListener` count ≥ 8 must use `AbortController` | warn always | Wrap init in `new AbortController()` + pass `{ signal }` to every listener; expose `destroy()` |
| P54 | `.slide-frame` declares `contain: ...` | warn if missing | `.slide-frame { contain: layout paint size }` — local repaints |
| P55 | `.slide-frame .slide` declares `will-change: transform` | warn if missing | `.slide-frame .slide { will-change: transform }` + `transform: ... translateZ(0)` |

### Two delivery modes

| Mode | When | Output | base64 | Validator |
|---|---|---|---|---|
| **Linked (default)** | Internal use, hosted, repo deck | `examples/sample-deck.html` ≈ 24 KB + external `assets/*` | 0 KB | passes P50 |
| **Inlined (opt-in)**  | Email attachment, IM, "send-me-the-html" | `examples/sample-deck-inline.html` ≈ 360 KB | 250 KB | skips P50 (signaled by `<meta name="fs-deck-mode" content="inline">`) |

`bash build.sh` produces the linked version; `bash build.sh --inline` produces both.
The inlined HTML must include the `fs-deck-mode=inline` meta tag — `build.sh` adds it
automatically. Hand-built single-file decks must add it manually or get flagged P50.

---

## Content-page header — title only, no eyebrow, no sub-line

Per the 2026-04 reference deck (see attached screenshot in commit history),
the content-page header is intentionally minimal:

```html
<div class="header">
  <h2 class="title-zh">懂我的AI,可以代我做方案评审</h2>
</div>
```

That's it. **No eyebrow above. No subtitle below. No inner wrapper div.
No inline page number** — page numbers come from the present-mode pager UI; per-slide chrome was retired 2026-05.

The reasoning: a content slide already carries a card grid / table /
process flow / etc. as its main body. Stacking an eyebrow + title +
sub-line at the top creates visual hierarchy noise that competes with
the actual content for attention. The screenshot demonstrates exactly
this: a single white sans-serif title at top-left, the colored 飞书
logo at top-right on the same baseline, and the content below.

The CSS enforces this defensively:

```css
.slide .header .eyebrow { display: none; }
```

Even if someone copies the old eyebrow-included markup, the eyebrow
won't render. The `.eyebrow` class is still usable elsewhere (inside
cards, section dividers, stats columns, etc.) — it's only suppressed
when it sits inside a content-page `.header`.

The Hero layouts (`cover` / `image-text` / `end`) use their own `.stage`
container, not `.header`, so they're unaffected and keep their existing
title patterns.

---

## Self-check — the validator IS the self-check

Run before every delivery:

```bash
bash assets/finalize.sh runs/<ts>/output local            # in-progress
bash assets/finalize.sh runs/<ts>/output local --strict   # final delivery
```

`finalize.sh` orchestrates `copy-assets` → `extract-texts` → `validate.py`
in order. Every validator error prints **what's wrong + how to fix** —
read it, fix it. Don't suppress.

The validator covers programmable rules (last refreshed 2026-05-18):

| Family | Rules | What it enforces |
|---|---|---|
| Structure | R02 / R07 / R-DOM | every `.slide` has `data-layout`, `data-screen-label`, `.wordmark`; balanced `<div>` open/close (`.slide-frame` direct under `.deck`, exactly one `.slide` per frame, no nested frames) |
| Copy | R05 / R13 | no emoji / `!` / `…`; no `<br>` in content-page titles (allowed on hero layouts: cover / image-text / end / section / quote) |
| Hex palette | R10 | hex values come from `--fs-*` tokens; SVG decor and inlined framework CSS are exempt |
| Drop shadows | R12 | no real `box-shadow` offsets (rings + insets only) |
| Typography | R06 / R20 | body ≥ 24 px; chrome ≥ 16 px; per-page `font-size` on the 4-tier ladder `{16, 24, 28, 48}` — hero exceptions (cover 100, section 88/160, big-stat 132+, quote 88+) require `/* allow:typescale */` in the rule |
| White-text | R-WHITE-TEXT | semantic body text on dark slides is `#fff` not low-opacity gray (which vanishes on projector); chrome opt-out via `/* allow:white-opacity */` |
| Hierarchy | R-HIERARCHY | inside a card, meta-info (owner / source / attribution) is structurally less important than body — its rendered fontSize must be ≤ body |
| CSS vars | R-CSSVAR | `var(--name)` references must resolve to a defined custom property (or have a fallback). Browser silently drops the surrounding declaration when a var is undefined — the worst case is `font:` shorthand where `font-size` falls back to 16 px regardless of the size you wrote |
| Redundant echo | R-ECHO | a summary leaf (class contains `legend / note / footnote / caption / summary / footer / lede / disclaimer / callout / subtitle / kicker / page-sub / tagline / recap`, or a plain `<p>`) shouldn't echo ≥ 3 sibling-leaf prefixes — that's a list restatement; drop the echo and keep only the new information |
| Logo | L1 | `.wordmark` defaults to color; mono is `class="is-mono"` opt-in |
| Layout integrity | L1 / L2 / L4 | logo default, balanced stage with content centering, single-col `.process .attrs` (L3 is not currently shipped) |
| Variants | R47 | structural-changing variants redeclare alignment |
| Centering | R48 | fixed-shape layouts default-center vertically |
| Empty header zone | R-EMPTY-HEADER-ZONE | hiding framework `.header` requires `.stage top ≤32` (snap to edge) OR `top:61` (framework anchor) OR a visible top decoration; otherwise the gap reads as "missing bg" — see BF15 |
| Cyan | R49 | cyan is inline-highlight only, not slide accent |
| Header | R56 | content-page `.header` has only `<h2>` (no eyebrow); matching is class-list aware (`class="header is-tall"` works) |
| Decor | R38 | `data-decor` tokens are from ship list |
| Runtime chrome | R29-R32 | present-mode bar/buttons + `requestFullscreen` wired |
| Centering pattern | R36 | `margin: -540px 0 0 -960px`, NOT grid `place-items` |
| UI mocks | UI1 | system UI is HTML primitives, not raster `<img>` |
| Language | R-LANG | `.title-en` / `.subtitle-en` / `.label-en` classes + chrome-class scan (any class ending in `-en / -eng / -english / -num / -index / -ord` AND eyebrow / kicker / pill / tag / chip / badge family) + sibling-pair detection (CJK leaf paired with Latin-only leaf inside the same parent) — only when `<meta name="fs-language" content="zh-only">` (or absent); meta-attribute order is irrelevant |
| Slide keys | R-KEY | every `.slide` has unique semantic `data-slide-key` (kebab-case); positional slugs warned |
| Text-id sidecar | T00 / T01 / T02 / T03 | data-text-id present (T00); valid `slide-NN.field` shape (T01); unique (T02); paired `texts.md` in sync (T03) |
| Performance | P50-P55 | base64 budget, blur cap, single ResizeObserver, AbortController, GPU layers |
| Visual (Playwright, default-on) | R-OVERFLOW / R-OVERLAP / R-VIS-TIER / R-VIS-HIER / R-VIS-ALIGN / R-VIS-LABEL-FLOOR / **R-VIS-CARD-OVERFLOW** | slide-level overflow > 1920×1080; sibling bbox intersection inside `.stage / .grid / .flow / .nodes / .toc / .stack / .table-wrap` (catches "column bleeds into legend"); computed `font-size` on 4-tier ladder; meta ≤ body in rendered DOM; grid-children equal height; hero-context cards forbid 16 px non-chrome labels; **inner element with `overflow:hidden` + `scrollHeight > clientHeight` (catches the SILENT TEXT CLIP bug where dense 3-up cards swallow content past their flex-1 boundary — added 2026-05-22)**. ~2 s overhead. `--no-visual` skips; gracefully skips when playwright not installed |
| Run-feedback | R-FEEDBACK | every run produces a `FEEDBACK.md` capturing decisions made for maintainer follow-up |
| Preflight | PREFLIGHT | local mount writable; not ephemeral |

**Severity model**: every audit emits `warn`, `err`, or `warn_soft` at its inherent severity. `--strict` globally promotes all regular `warn`s to errors at the end of `main()`. **Soft warnings** (`warn_soft`) — currently `R-FEEDBACK` and `R-VIS-ALIGN` — are editorial advisories that NEVER escalate to errors under `--strict`. They render alongside regular warnings (under the same `WARNINGS` heading) but don't fail CI.

What the validator can't catch — needs human eyes before delivery:

- **Visual alignment** — title baseline ↔ logo center, agenda numerals ↔ titles
- **Atmospheric feel** — gloom/glow density vs content density (open at 1920×1080 and squint)
- **ZH-EN sizing balance** on bilingual decks (ZH must read bigger / sit above)
- **Narrative landing** — does each slide deliver its one point in 3 seconds?

Open at 1920×1080 (PC), 1280×720 (laptop), 380×680 (phone). If any breaks
visually, fix the slide; the validator only catches programmable rules.

---

## Failure modes & fixes

| Symptom                                | Likely cause                                         | Fix |
|----------------------------------------|------------------------------------------------------|---|
| Slide displays at top-left, tiny       | Forgot to wrap `.slide` in `.slide-frame`            | Add the wrapper. |
| Indicator + toggle don't appear        | Missing `<script src="assets/feishu-deck.js">`       | Add it (or inline). |
| Mobile shows huge whitespace           | Viewport meta tag missing                            | Add `<meta name="viewport" ...>`. |
| Title overflows past edge              | Content too long for 1920 px canvas                  | Cut content. Don't shrink type below 24 px. |
| Card heights misaligned                | Card content imbalanced                              | Add a 1-line `<br>` to short titles. Cards are min-height:400. |
| Stats column rule on first column      | Default CSS leaks                                    | First column has `border-left:0` already — check overrides. |
| Two accents on one slide               | Forgot to set `data-accent` on slide level           | Set `data-accent="teal"` on the `.slide` element only. |
| Quote glow too strong                  | Custom background overrides `--fs-grad-glow-blue`    | Don't override `.slide[data-layout="quote"]` background. |

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

## Examples

- `examples/sample-deck.html` — 12-slide demo using all 13 layouts (single file, inlined).
- `preview-dark.html` — token swatches and component gallery for visual self-test.
- `templates/slide-recipes.html` — every layout in one reference deck (open and copy).
