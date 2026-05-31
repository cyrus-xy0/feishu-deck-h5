# check-only — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:CHECK-ONLY 模式:用户给成品 HTML 要审/校验

## CHECK-ONLY MODE

The user gave you an HTML file (own deck, foreign deck, downloaded sample,
PR for review) and just wants to know what's non-compliant. The skill ships
a dedicated entry point for this:

```bash
bash skills/feishu-deck-h5/assets/check-only.sh <html-path> [--strict] [--no-visual] [--report PATH]
```

What it does:

1. Runs the full `validate.py` rule set (R02 / R05 / R06 / R10 / R12 / R13 /
   R20 / R29-32 / R36 / R38 / R47 / R48 / R49 / R56 / L1-L4 / UI1 / R-LANG /
   R-KEY / R-DOM / R-WHITE-TEXT / R-HIERARCHY / T00-T03 / P50-P55).
2. Auto-resolves linked `<link rel="stylesheet">` / `<script src="">` so a
   non-inlined deck validates correctly (same logic as `validate.py`).
3. Groups issues by **family** (结构/DOM · 排版/文案 · 品牌/调色板 · 布局完整性
   · UI 仿真/slide-key · 演示模式/运行时 · texts.md 联动 · 性能预算 · 视觉 ·
   交付物附件) and produces a markdown report.
4. Auto-detects deck mode via heuristics (Replica `.page-replica` /
   inline `fs-deck-mode=inline` / bilingual `fs-language=zh-en`) and prints
   a hints block at the top of the report.
5. Flags **context-dependent rules** (T00 / T03 / UI1 / P50 / R29-32) —
   these often false-positive when a deck is a Replica, an
   external HTML, or a non-`new-run`-flow artifact. The report shows them
   but explains when they're safe to ignore.

### When to use what flags

- **default** — `bash check-only.sh deck.html` — warn ≠ blocker, **视觉审计默认开**
  (与 `validate.py` 对齐, 2026-05-31 起)。Use for first-pass review of someone
  else's deck. Exit 0 if no errors.
- **`--strict`** — `bash check-only.sh deck.html --strict` — warns promoted
  to errors. Use when the deck is going to a customer and you want zero
  warnings.
- **`--no-visual`** — **关闭** Playwright 视觉审计 (R-OVERFLOW / R-VIS-TIER /
  R-VIS-HIER / R-VIS-LABEL-FLOOR / R-VIS-BALANCE / R-FOCAL-CHECK …)。视觉审计
  **默认开启**, ~2-5s per 30-slide deck, 需要 `pip install playwright &&
  python -m playwright install chromium` 一次; 未装时自动跳过 (打 notice, 不硬
  失败)。仅在 CI 无 chromium 或想跑得更快时用 `--no-visual` 关掉。
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

#### 与入库无关 (gate 模式直接屏蔽)

`T00` · `T03` · `UI1` · `P50` · `P51-P55` · `R29-32` · `R36` · `R-LANG` (单条 title-en warn)

这几条要么是生成流程产物 (texts.md), 要么是交付格式选择
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
| 视觉 (Playwright, default-on since 2026-05-18) | R-OVERFLOW / R-OVERLAP / R-VIS-TIER / R-VIS-HIER / R-VIS-LABEL-FLOOR / R-VIS-BODY-FLOOR / **R-VIS-ABSPOS-DUAL-ANCHOR** / **R-VIS-ORPHAN** / **R-VIS-BALANCE** / **R-FOCAL-CHECK** | canvas overflow; **sibling bbox overlap** (catches "column bleeds into legend" — internal overlap within canvas); computed `fontSize` on ladder; meta ≤ body; **renderer-aware body-content < 24 px detection** (R-VIS-BODY-FLOOR · 2026-05-19 · catches ambiguous short class names like `.rt` / `.d` / `.ind-tag` that pass static R20/R06 because 16 is on the ladder and short class names match neither chrome nor body heuristic — checks actual rendered fontSize + ≥ 8 chars of direct text + not inside mockup containers; opt out per element with `data-allow-body-floor`); grid-children equal height; **dual-anchor pill stretch** (R-VIS-ABSPOS-DUAL-ANCHOR · 2026-05-23 · catches the cascade footgun where an override declares `top:` on a `position: absolute` chrome element without resetting an inherited `bottom:`, so the pill / badge / hint stretches to most of the parent height — see BF14 below; mutation-tests every absolutely-positioned non-layout-container element by temporarily setting `style.bottom = 'auto'` and checking if height collapses; layout shells like `.stage / .stack / .iframe-wrap / .panel` are excluded by class denylist; opt-out per element with `data-allow-dual-anchor`); **CJK orphan / 上长下短 wrap** (R-VIS-ORPHAN · 2026-05-25 · WARN · CJK leaf text wrapping to a lonely ~1-char last line, or a short ≤14-CJK label whose last line < 38% of the widest — the residue `text-wrap: balance` can't fix in fixed-width / `<br>`-broken containers; skips block-child sub-labels / SVG / mockup / nowrap; deck slides only, not iframe prototypes — see "CJK 换行平衡 / 末行孤字防治"); **视觉重心 / 留白均衡**(R-VIS-BALANCE · 2026-05-28 · WARN · 量正文容器的内容 bbox,三种 sub-kind:top-heavy(顶部留白 0、底部 256+px)、bottom-heavy(反向)、dead-band(相邻内容块之间 >140 px 死带)。捕捉"上空 / 下空 / 中空"反馈——这些页 validator floor 全 PASS 但视觉上"摆不平"。Skip hero layouts;per-slide opt-out `data-allow-imbalance`);**视觉焦点**(R-FOCAL-CHECK · 2026-05-28 · WARN · 非 hero / 非平行模式页上,≥3 个文本元素共享全页最大字号 → 焦点模糊报告。捕捉用户最常反馈的"信息平铺无重点"——典型 = 页 title 48 + 3 张 card title 48,眼睛不知道第一眼看哪。Skip:hero layouts、parallel-pattern containers(overview-grid / north-star-map / scene-grid / logo-wall / kpi-strip / arch-stack / pipeline / 等"显式 N 路平权"祖先)、声明 `.is-hero` / `data-focal` 的元素、`data-allow-no-focal` slide。Fix: 降级 N-1 个元素;或一个 `.is-hero`;或 brand color / border 差异化;或 `data-allow-no-focal` 显式平权). ~2 s overhead. Use `--no-visual` to skip (CI without Chromium); gracefully skips if playwright is not installed |

When the user asks "what does [Rxx] mean", look up the rule in `validate.py`
(grep for the code) — every audit function has a docstring + the error message
explains the fix.

---

