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
   R-KEY / R-DOM / R-WHITE-TEXT / R-HIERARCHY / P50-P55).
2. Auto-resolves linked `<link rel="stylesheet">` / `<script src="">` so a
   non-inlined deck validates correctly (same logic as `validate.py`).
3. Produces the **STANDARD per-page business report** (默认输出,见下节
   「标准报告格式」). 这是所有人调 check-only / 校验时得到的统一格式。

## 标准报告格式(默认 · mandatory)— 逐页 · 业务语言 · 区分错误/提醒

**这是 check-only / 任何校验的唯一标准输出,所有人体验一致。** 不再默认按
技术规则家族(R06 / R-VIS-TIER…)聚合 —— 那是给工程师的,业务/客户看不懂。

默认报告(`assets/check-only.py` 的 `build_per_page_report()` 生成,**不要手动
改写格式 / 重新归类**)长这样:

- **表头**:文件 · 共 N 页 · 结论(`🔴 X 处错误 · 🟡 Y 处提醒`,或 `✅ 全部通过`)
- **图例**:🔴 错误 = 投影上客户能直接看到的硬伤,交付前建议修;🟡 提醒 = 可优化细节,不挡交付
- **逐页**:从第 1 页到第 N 页**全部列出**,干净页标 `✅ 没问题`;有问题的页 🔴 在前
  🟡 在后,**同一页同类问题合并成一行**(带 `(本页 N 处)` 计数,不刷屏)
- **整份文件**:不针对某一页的问题(性能 / 放映功能 / 文案外挂)单列一段
- **小结**:哪些页干净(不用管)+ 🎯 最该先看哪几页

业务文案来自 `assets/business-rules.yaml`(每条规则一段 `症状/后果/修法`),
**已 100% 覆盖所有会触发的规则**。非工程师可直接改那里的措辞,不用动 `.py`。

回答用户「检查这份 deck / 这页有什么问题」时,**直接把这份报告给他**,不要
自己再用规则代码 / 家族重新组织一遍。

### 规则只有一套源 · 三路取用 · 防漂闸门(架构 mandatory)

**规则逻辑只定义在一处** —— 单一引擎:`assets/audits.js`(DOM 规则引擎)+
`assets/run-audits.py`(字节 / 文件系统域)。`assets/validate.py` 只是编排器,
通过 `run_unified_audits` 把两者的发现合到一起;三条路径全部经它取同一套审计,
**没有第二套规则**(旧的 `_validate_audits.py` / `STATIC_AUDITS` 静态注册表已退役)。
schema 形状校验另在 `deck-json/validate-deck.py`:

| 路径 | 入口 | 怎么取规则 |
|---|---|---|
| ① 生成即对 / 渲染后自查 | `deck-json/render-deck.py` | 渲染后硬闸调 `validate.py` |
| ② 直接校验 | `assets/validate.py` | 编排器 → `run_unified_audits`(audits.js + run-audits.py) |
| ③ 已成品检查 (check-only) | `assets/check-only.py` | `import validate` → 同一套 `run_unified_audits` |

引擎之外只有**两份「附属清单」**(不是第二套规则,只是给规则码挂分组/文案):
`check-only.py` 的 `FAMILIES`(`--by-rule` 工程师分组)+ `business-rules.yaml`
(业务文案)。它们必须 100% 跟引擎对齐,否则漂移 → 落「未分类」/ 退兜底句 /
死文案永不触发。

**防漂三道闸**(改了引擎规则码后必须保持绿):
1. **提交前硬闸** —— `python3 assets/check-rule-coverage.py`:三方比对(引擎 ↔
   FAMILIES ↔ yaml),有缺口 / 死码 `exit 1` 并逐条列出该补哪个文件。改完规则
   跑一下就知道同步没。
2. **运行时横幅** —— check-only 出报告时若发现引擎有码但 yaml 没文案,报告顶部
   自动打 `⚠️ 业务文案未覆盖 N 条…`,不再默默退兜底。
3. **ingest 门禁自检** —— `warn_on_gate_rule_drift()` 对 ingest 门禁同样比对。

**加 / 改一条规则的标准流程**:① 在引擎里写逻辑 —— DOM 规则进 `assets/audits.js`,
字节 / 文件系统规则进 `assets/run-audits.py`(并在 audits.js 的规则 surface 表登记)
→ ② `business-rules.yaml` 加一段同名 code 的文案 → ③ `FAMILIES` 把该 code 归到对应
家族 → ④ 跑 `check-rule-coverage.py` 确认三方对齐(绿)。逻辑一处、文案一处、分组
一处,各司其职,闸门保证不漂。

### 报告附加项

- Auto-detects deck mode via heuristics (Replica `.page-replica` /
  inline `fs-deck-mode=inline` / bilingual `fs-language=zh-en`).
- **`--by-rule`**(工程师视图):按技术规则家族聚合的旧报告,排查框架 bug 时用。
- **`--gate ingest`**(库准入):按业务关切 A/B/C 分组,slide-library 的
  `ingest-package.py` 自动调,exit code 语义不同(见下「Gate ingest mode」)。

### When to use what flags

- **default** — `bash check-only.sh deck.html` — 出**逐页业务报告**(标准格式,
  见上节)。warn ≠ blocker, **视觉审计默认开**(与 `validate.py` 对齐, 2026-05-31
  起)。Use for first-pass review of someone else's deck. Exit 0 if no errors.
- **`--by-rule`** — `bash check-only.sh deck.html --by-rule` — 工程师视图,按
  技术规则家族聚合(旧默认格式)。排查框架 bug / 改 validator 时用。
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

**B · 库找不回这张 slide (3 条)** —— locator 失锚
- `R-KEY` 缺 slide-key
- `R-DOM` DOM 嵌套坏
- `R02` 缺 layout / 屏幕标签

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

`UI1` · `P50` · `P51-P55` · `R29-32` · `R36` · `R-LANG` (单条 title-en warn)

这几条要么是交付格式选择 (inline vs linked / Replica vs Rewrite), 要么是
浏览器性能预算 —— 都跟 slide-library 入库后能否被检索 / 复用 / 追溯无关.

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
- call `copy-assets.py` / `package-deliverable.sh`
- modify the input HTML in any way
- offer to "fix" issues automatically — leave that as a follow-up the user
  can ask for separately (and which routes them into GENERATION mode on
  the same deck)

**Do**:
- **直接把 `validate.py` 生成的逐页业务报告给用户** —— 它已经是「逐页 + 业务
  语言 + 🔴错误/🟡提醒 + 小结」的标准格式。**不要**自己再按规则代码 / 家族
  重新组织,**不要**把术语(R06 / R-VIS-TIER…)抖给业务用户看。
- 开头一句先报结论(`🔴 X 错误 · 🟡 Y 提醒` 或 `✅ 全部通过`),用户先看到判定
  再往下翻;报告末尾的「最该先看」小结直接引用即可。
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
| 性能预算 | P50-P55 | base64 budget; blur radius; single ResizeObserver; AbortController; GPU layers |
| 视觉 (Playwright, default-on since 2026-05-18) | R-OVERFLOW / R-OVERLAP / R-VIS-TIER / R-VIS-HIER / R-VIS-LABEL-FLOOR / R-VIS-BODY-FLOOR / **R-VIS-ABSPOS-DUAL-ANCHOR** / **R-VIS-ORPHAN** / **R-VIS-BALANCE** / **R-FOCAL-CHECK** | canvas overflow; **sibling bbox overlap** (catches "column bleeds into legend" — internal overlap within canvas); computed `fontSize` on ladder; meta ≤ body; **renderer-aware body-content < 24 px detection** (R-VIS-BODY-FLOOR · 2026-05-19 · catches ambiguous short class names like `.rt` / `.d` / `.ind-tag` that pass static R20/R06 because 16 is on the ladder and short class names match neither chrome nor body heuristic — checks actual rendered fontSize + ≥ 8 chars of direct text + not inside mockup containers; opt out per element with `data-allow-body-floor`); grid-children equal height; **dual-anchor pill stretch** (R-VIS-ABSPOS-DUAL-ANCHOR · 2026-05-23 · catches the cascade footgun where an override declares `top:` on a `position: absolute` chrome element without resetting an inherited `bottom:`, so the pill / badge / hint stretches to most of the parent height — see BF14 below; mutation-tests every absolutely-positioned non-layout-container element by temporarily setting `style.bottom = 'auto'` and checking if height collapses; layout shells like `.stage / .stack / .iframe-wrap / .panel` are excluded by class denylist; opt-out per element with `data-allow-dual-anchor`); **CJK orphan / 上长下短 wrap** (R-VIS-ORPHAN · 2026-05-25 · WARN · CJK leaf text wrapping to a lonely ~1-char last line, or a short ≤14-CJK label whose last line < 38% of the widest — the residue `text-wrap: balance` can't fix in fixed-width / `<br>`-broken containers; skips block-child sub-labels / SVG / mockup / nowrap; deck slides only, not iframe prototypes — see "CJK 换行平衡 / 末行孤字防治"); **视觉重心 / 留白均衡**(R-VIS-BALANCE · 2026-05-28 · WARN · 量正文容器的内容 bbox,三种 sub-kind:top-heavy(顶部留白 0、底部 256+px)、bottom-heavy(反向)、dead-band(相邻内容块之间 >140 px 死带)。捕捉"上空 / 下空 / 中空"反馈——这些页 validator floor 全 PASS 但视觉上"摆不平"。Skip hero layouts;per-slide opt-out `data-allow-imbalance`);**视觉焦点**(R-FOCAL-CHECK · 2026-05-28 · WARN · 非 hero / 非平行模式页上,≥3 个文本元素共享全页最大字号 → 焦点模糊报告。捕捉用户最常反馈的"信息平铺无重点"——典型 = 页 title 48 + 3 张 card title 48,眼睛不知道第一眼看哪。Skip:hero layouts、parallel-pattern containers(overview-grid / north-star-map / scene-grid / logo-wall / kpi-strip / arch-stack / pipeline / 等"显式 N 路平权"祖先)、声明 `.is-hero` / `data-focal` 的元素、`data-allow-no-focal` slide。Fix: 降级 N-1 个元素;或一个 `.is-hero`;或 brand color / border 差异化;或 `data-allow-no-focal` 显式平权). ~2 s overhead. Use `--no-visual` to skip (CI without Chromium); gracefully skips if playwright is not installed |

When the user asks "what does [Rxx] mean", look up the rule in `validate.py`
(grep for the code) — every audit function has a docstring + the error message
explains the fix.

---

