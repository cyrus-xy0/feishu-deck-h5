# F-30 · SKILL.md 瘦身/拆分 实施计划

> 生成: 2026-05-29 · 配套审查报告 `AUDIT-2026-05-29.md` 的 P0 工单 **F-30**。
> 产出方式: 9-agent workflow(7 并行分类 → 合成 → 对抗性 verify)。**verify 结论:方向正确,但合成稿"不可照原样执行",已折入 6 项必修更正(下方标 ⚠️FIX)。**
> 目标: 把每次激活 eager 载入的 `SKILL.md` 从 **420,079 B ≈ 105K tokens** 砍到 **≈ 55–65 KB ≈ 14–16K tokens(约 85% 降幅)**,不丢任何路由能力与硬闸门。

## 0 · 关键事实 / 安全前提
- **唯一文件**:`~/.claude/skills/feishu-deck-h5` 是仓库 `skills/feishu-deck-h5/` 的**符号链接**(同 inode)。编辑仓库路径 = 改 harness 实际加载的那份。`~/Downloads/feishu-deck-h5/SKILL.md`(83KB,4-30,只读)是旧拷贝,**不动**。
- **回滚**:这是 git 仓库 → 在分支 `f30-skillmd-slim` 上做,逐步提交;另存 `SKILL.md.bak-pre-slim-<ts>`(用户铁律:破坏性操作留备份)。
- **机制**:Claude Code skill 把 SKILL.md **eager 全量**载入;reference 文件**懒加载**(agent 被指引时才 Read)。所以"移出"只有在 **lean SKILL.md 留下明确 trigger+指针**时才安全。

## 1 · 处置总览(已折入 verify 更正)

### CORE — 保持 eager(逐字保留)
front-matter/STOP banner · **MODE SELECTION(路由,神圣,逐字)** · **PREFLIGHT(硬闸门,逐字)** · **DECK GENERATION POLICY(整段保留 15.6KB —— Path A/B 决策交织,拆了会丢 raw-vs-PathB 判断)** · deck-purpose 散文(L3022-3036) · When-to-use · Available layouts(13 版式决策表) · Iconography(禁 emoji/远程图) · Single-file inlined · **Copy/numbering 规范(整段——含单页单 teal 强调等非 validator 强制的编辑规则)** · 新增 **REFERENCES INDEX**(所有 references/*.md + CHANGES.md 锚点的一行指针)

### COMPRESS — 留 eager 内核 + 指向 reference(共 ~19 段)
| 段 | 内核保留(eager) | 详情移到 |
|---|---|---|
| DESIGN PHASE | 4 步骨架 + confirm-gate + DESIGN-PLAN.md 落盘 + Step5 闸门存在 · **⚠️FIX 保留一行**「转换已有材料(PDF/PPT)→ 默认 1:1 页数,先看 references/converting…再开工」+ 退化场景 | references/design-phase.md |
| **DELIVERY MODES** ⚠️FIX(原合成稿错移成纯 MOVE,**最严重**) | 🔒 禁"单 linked HTML"裸文件 + A/B/C 一行表 + 发前跑 copy-assets/finalize + 重命名 `lark-<客户>-<YYYY-MM-DD>.html` + 每轮 surface 产物路径 | references/delivery.md(Mode1-3 走查/package 内部/caveats) |
| **Files in this skill(品牌资产纪律)** ⚠️FIX(silent 商标违规路径,不可纯移) | 6 条硬规则:logo 只从 clientlogo/、飞书 icon 只从 feishu-products/ **禁手绘/SVG/emoji**、persona 两目录、`background-image` div 非 `<img>`、R12 ring-shadow、禁写 per-asset 到 assets 根/runs input | references/assets-and-files.md(文件树/查找流程/phone mockup) |
| **EDITING DISCIPLINE** ⚠️FIX(删页同时触发 E1/E2,非仅 E5) | 一行 breadcrumb:删/插/重排时 **E1** 重编 data-page+同步 scoped CSS · **E2** 禁 sed/regex 改 DOM · **E5** 任何动过的页都欠一次 squint/再平衡;从 SLIDE DELETION 交叉链接 | references/editing-discipline.md(E1-E4 细节) |
| **Quick start** ⚠️FIX(原教旧手写流,与 DeckJSON-first 矛盾) | **改写**成 DeckJSON-first 7 步骨架(deck.json→render-deck.py→finalize.sh→交付 A/B/C);删 copy `_shell.html`/手标 data-text-id 那套 | — |
| WORKSPACE LAYOUT | new-run.sh + slug + announce + writes-under-output | references/(slug 规则 inline-terse,无需单文件) |
| SLIDE DELETION POLICY | 5 步双确认 + bak-and-log.sh + "隐性同意不算" + **交叉链接 EDITING E1/E2/E5** | references/slide-deletion.md |
| TEXT-EDIT SIDECAR | 交付物 + data-text-id 方案 + **data-slide-key 硬前提** + apply-texts.py | references/text-edit-sidecar.md |
| LANGUAGE POLICY | 默认 ZH-only + 两个 `<meta>` 值 + zh-en 仅显式请求 | (validator R-LANG 打印细节) |
| CONTENT-DENSITY | 默认补全 + **no-fabrication 护栏** + 两个 STOP-and-ask | references/content-density.md |
| ROUND-TRIP INTEGRITY | A/B 两半契约(deck.json 唯一真相;fork 拷整目录) | references/round-trip-integrity.md |
| The shell | DOM 顺序 `.deck>.slide-frame>.slide` + 路径 | (templates/_shell.html) |
| Layout default centering | 哪些 center 哪些 fill(R48) | references/layout-recipes.md |
| Layout integrity L1-L4 | 四条一行规则 | references/layout-recipes.md |
| Self-check×2 | finalize.sh/validate.py 闸门命令 + exit1 阻塞 + 人眼项 | references/validator-rules.md |
| Richness primitives | **强制 `.stage` 包裹** + richness-是默认 + 禁 grid-bg + helper 名单 | references/richness-primitives.md |
| Helper-snippet | helper 名一行索引 | references/narrative-patterns.md |
| Performance budget | P50-P55 一行 + `fs-deck-mode=inline` | — |
| Content-page header | header 仅 title-zh 无 eyebrow + hero 例外 | — |
| Examples | 一行指针 | — |

### MOVE → 新建 references/*.md(纯移,mode/feature 触发才读)
`design-first.md`(24.1K · Q0-Q4/六维/squint/组件类表)· `check-only.md`(10.9K)· `reskin.md`(33.5K · 含 Re-render-UI-mocks + Preserve-atmospheric;**CORE 指针必带 1920×1080 硬前提 + META-RULE**)· `converting-existing-material.md`(46.7K · **CORE 指针必带 1:1 页数 + Replica/Rewrite 路由**)· `one-pager-case.md`(21K · **指针带 skip-cover + 禁造 STORY id/来源**)· `run-artifacts.md`(FEEDBACK+PROMPTS)· `extra-layouts-and-raw.md`(11K · 指针带 .stage=680 坑 + flex center 默认 + --visual)· `layout-recipes.md`(33.5K · 13 版式 markup + R47 variant + CSS pitfalls)· `narrative-patterns.md`(16.6K · A-N)· `prototype-embed.md`(28.1K · **指针带"别默认 iframe":feishu slide→native lift / 外来 demo→iframe / 简单→re-author**)· `validator-rules.md`(7K)· `operational-notes.md` · `troubleshooting.md`(症状→修)

### CHANGES.md — 历史搬出(留 ≤1 行 breadcrumb,执行内容已在 CSS/validator)
`#layer-1-retired` · `#BF1-BF9`(原 BF1-4 段,实含 BF1-9+R57)· `#BF10-BF15`(原 BF10-12 段)· `#media-autorestart` · `#cjk-orphan`。⚠️ R57(quote 无尾句号)、media 的 autoplay-without-muted 等"非 validator 强制"的编辑规则,**其一行规则保留在 breadcrumb**,不随散文埋进 CHANGES。

## 2 · 字节预算(折入更正后)
- 合成稿原估 core ≈ 54KB(87%↓)。verify 的 4 处晋升(DELIVERY +~1.5K、品牌 +~1K、EDITING +~0.8K、DESIGN 保 1:1 行)使 core ≈ **55–65 KB ≈ 14–16K tokens**,**≈ 84–87% 降幅**。最终值执行后实测。
- references/ 总量 ≈ 300KB+(懒加载,单次只命中 1–2 个)。CHANGES.md ≈ 35KB(几乎不被加载)。

## 3 · 必须留在 CORE 的硬闸门(verify 的验收清单)
PREFLIGHT · SLIDE-DELETION 5 步确认 · LANGUAGE 默认 ZH · CONTENT-DENSITY 禁造 attributed facts · TEXT-EDIT data-slide-key · validator 闸门 · **DELIVERY 禁裸 linked HTML** · **prototype 别默认 iframe** · **RESKIN 1920×1080 前提** · **Converting 1:1 页数** · EDITING E1/E2/E5。任何一条只活在 reference 里 = 不合格。

## 4 · 迁移步骤(有序 · 安全 · create-refs-first)
1. **分支 + 备份**:`git checkout -b f30-skillmd-slim`;`cp SKILL.md SKILL.md.bak-pre-slim-<ts>`。确认基线 `wc -c = 420079`。
2. **先建 references/**:把每个 MOVE 段的正文**逐字**搬进目标 `references/<file>.md`(按 §1 分组),每文件加 H1 + 一行 `(从 SKILL.md 拆出 · 何时读: <trigger>)` 头。
3. **建 CHANGES.md**:5 个锚点段逐字搬入(纯历史,不影响运行)。
4. **校验 reference 完整**:grep 每个被移段的关键命令/标识(check-only.sh / reskin.sh / story-case / `.stage 680` / data-decor …)在 references 中恰好出现一次。**确认正文已在 reference 后,才删 core 里的正文**。
5. **COMPRESS 19 段**:逐段 exact-string Edit 压到"内核 + 指针",绝不碰相邻 CORE 段。⚠️ 逐段自检"这条真被 validator 强制吗?"——不是则保留其一行规则。
6. **删 MOVE 正文**:各替换为单行 pointer(≈120B)。**保持段落顺序**,文档仍自上而下连贯。deck-purpose 散文(L3022-3036)原地不动。
7. **插 REFERENCES INDEX**(MODE SELECTION 之后或 When-to-use 之前):列全部 references/*.md + CHANGES 锚点 + 一行 trigger。
8. **修悬挂交叉引用**:PREFLIGHT 里 `(see DELIVERY MODES below)` 等指向被移段的 "below" → 指到 COMPRESS 后的 core stub 或 INDEX。
9. **路由自测**:只读 slim SKILL.md,逐一走 6 条入口(CHECK-ONLY / GEN-from-brief / GEN-default / RESKIN / convert-existing / prototype-embed)+ §3 每条硬闸门是否 eager 可见。
10. **实测 + 收尾**:`wc -c` 实测降幅;若有 skill 结构 CI 则跑;否则用 GEN-default 只读 slim core 跑一份 trivial deck 验证渐进披露;通过前保留 `.bak`。提交、推送(等你确认)、把 AUDIT 里 F-30 标 done。

## 5 · 待你定的开关
1. **激进度**:维持 ~85% 极简(推荐 —— 大块都是真·mode-gated,且 verify 的 4 处晋升已把 silent-failure 堵住)vs 更保守(DESIGN-FIRST/Converting/Files 在 core 留更胖,降幅 ~50-60%)。
2. **CHANGES.md 单向门**:确认接受"BF1-15/Layer-1/media/CJK 的散文搬走,以 CSS/validator 为真相源"(verify 共识:可以,但叙事是单向门)。
3. **执行方式**:建议起一个**执行 workflow**(并行写 ~14 个 reference 文件——各是独立新文件、不冲突;再串行压 core;再路由自测),或我顺序手工执行。
