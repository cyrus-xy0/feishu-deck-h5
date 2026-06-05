# 统一校验架构 — 单引擎 / 单规则源 (UNIFY-VALIDATE-ARCH-2026-06-03)

> 状态:**步骤 2 已实现**(2026-06-03,整合分支 integrate-pr16-pipeline-restructure)。
> 落地:`assets/audits.js`(单规则源引擎)+ `assets/run-audits.py`(瘦 runner,playwright 硬依赖)
> + 写入 hook 接入 canvas-center。R-VIS-CANVAS-CENTER 已从 visual-audit.js 几何逐字移植,
> finding 与旧引擎**逐一对齐**(everbright:s17 偏上47 / s22 偏下61 完全相同),且**更正确**——
> 旧 `validate.py:605 [:20]` 截断在 60 帧 deck 上静默漏掉的 s54(偏上54)被新引擎补回。
> 缘起:2026-06-03 everbright deck 会话,#49「内容偏下」事故暴露"规则在、自动闸没跑"的结构缺口。

---

## 0. 缘起(为什么要做)

会话中 slide #49(`judgment-training-complaints`)内容垂直不居中(整页内容并集中心比画布参考中线低 70px)。

- 规则**早已存在**:`R-VIS-CANVAS-CENTER`(2026-05-31,`references/validator-rules.md`)。
- 但**从没在编辑时跑过**:写入 hook(`~/.claude/hooks/validate-deck-write.py`)第 71 行写死 `validate.py --no-visual`,只跑静态档;`R-VIS-CANVAS-CENTER` 属 `run_visual_audits` / `visual-audit.js`(视觉档,要 playwright)→ 两档不重叠,这条规则在自动路径上**一次没触发**。
- 结果:bug 没被自动拦,靠人肉截图 + 直觉修对,中途还差点判反方向(只量了单块 merge-box,误判"偏上")。最后按规则公式(整页内容并集中心 vs `(主标题底+1080)/2`)量出 +70 → 修后 −3px 才确认。

**核心病根:规则的"存在"与"执行"脱节;且今天已是两套注册表、两种语言(维护两处)。**

---

## 1. 关键技术结论(决定架构走向)

几何类规则(① 刨标题、整块内容区居中;② 左右列高不一致时如何居中)**不能在静态解析里忠实实现**。

原因是原理性的:这两条都要知道元素**渲染后落在哪个像素**,而那取决于文字换行(尤其 CJK 断行)占几行、图片/SVG 实际渲染尺寸、flex/grid 空间分配、`gap/padding/flex:1`……这些是浏览器布局引擎算出的不动点。静态解析 CSS 文本算不出"这段话换几行 / 这一列最终多高"——想算准 = 自己重写一个 Blink。

→ **统一方向不是"全塞进静态解析器"(几何做不到),而是反过来:所有规则收敛到"浏览器渲染后的 DOM"这一个基底。**

### 超集论证(为什么往浏览器收敛不丢能力)

静态档现在查的,渲染 DOM 全能查、且更准:

| 静态查 | 渲染 DOM 查 | 谁更准 |
|---|---|---|
| R20/R06 字号(读 CSS 文本) | `getComputedStyle(el).fontSize`(层叠/继承/覆盖后真正生效值) | 渲染(冰山 `.hero-pct` 死规则 100px→16px,静态看不出) |
| R07 缺 wordmark | `querySelector('.wordmark')` | 等价 |
| R10 调色板 hex | `getComputedStyle` color/background | 渲染 |
| R-DOM 结构 | `querySelectorAll('.slide-frame > .slide')` | 等价 |
| R-LANG 语言轨 | 渲染 DOM 文本节点 | 等价 |

**静态集是渲染集的子集**;搬进渲染档不丢能力、反而更准。真正"只关源字节、与渲染无关"的极少数(P50 base64 体积、`fs-deck-mode` meta、磁盘资产存在性)归 runner 的几个字节/文件系统检查,不构成第二套规则注册表。

---

## 2. 现状(要消灭的)

- 静态档:`STATIC_AUDITS` 注册表(`validate.py:844`)+ 审计函数 `_validate_audits.py`(Python,解析 HTML/CSS 文本)。
- 视觉档:`run_visual_audits`(`validate.py:106`)+ `visual-audit.js`(2044 行 JS,浏览器内)。
- **两套注册表、两种语言。** 改一条规则可能两边都要动;一条规则可能两边各实现一半。裂口今天已存在。

---

## 3. 目标架构:单基底 / 单注册表 / 用"范围"调速

```
┌─────────────────────────────────────────────────────┐
│  runner (瘦 harness · 只管"跑")                        │
│   1. 起 1 个 headless 浏览器、load 整份 deck(1 session) │
│   2. 注入 audits.js                                    │
│   3. 按 scope 跑(changed 帧 / 全 deck)                 │
│   4. 收 findings → 统一报告(业务 / --by-rule 两视图)    │
│   ─ 另:少数纯字节/文件系统检查(P50/资产存在性)在此层   │
└─────────────────────────────────────────────────────┘
                      │ 注入
                      ▼
┌─────────────────────────────────────────────────────┐
│  audits.js  ◀── 唯一规则源,以后只改这一个文件           │
│   每条规则 = (ctx) => findings                          │
│   ctx: perFrame bbox / getComputedStyle /              │
│        querySelector / textContent / 源 HTML            │
│   R-VIS-CANVAS-CENTER, R20, R07, R-DOM, R-BALANCE …全在此│
└─────────────────────────────────────────────────────┘
```

三要点:

1. **单基底 = 渲染后的 DOM**。一个 headless 浏览器、一个 session、整份 deck 一次 load。所有规则都是"对渲染 DOM 求值的函数"。
2. **单注册表 = 一个 `audits.js`**。无 static/visual 之分,只有一个规则列表。改规则只动这一个文件。Python/Node 退化成纯 runner(起浏览器、收结果、出报告),不含规则逻辑。
3. **"静态 vs 动态" → "范围(scope)"**,这才是调速旋钮:
   - 编辑时(hook):只对**改动的几帧**求值 → 1 次 load + 几帧 eval ≈ **1–2 秒**。
   - 交付前 / 手动:对**全 deck** 求值。
   - 可选:按帧 hash 缓存,跳过没变的帧。
   - 慢的从来不是"视觉"属性,是"算了 60 帧";只算 1 帧就不慢。

**hook 接法**:调这一个引擎、scope=改动帧;playwright 不在 → **硬提示装它,绝不静默放行**。无第二条静态路径。

### 你那两条规则的归属
- ① 刨标题、整块内容区居中 → 几何,必须渲染 → `audits.js`(即现 `R-VIS-CANVAS-CENTER`,逻辑照搬:内容并集排 `.header`,垂直中心 vs `(主标题底+1080)/2`,偏移 >40px 判失衡)。
- ② 左右列高不一致时如何居中 → 要两列渲染高度 → 必须渲染 → `audits.js`(新增或并进 R-VIS-BALANCE)。
- 两条在静态档都做不到 → "统一到渲染档"是唯一能容纳它们的选择。

---

## 4. 价值分析(多维度,含代价)

**本质:把"规则写没写"和"规则有没有真跑"焊成一件事。**

1. **维护**:一处真源,告别两注册表/两语言的漂移;补上今天已存在的裂口。
2. **正确性**:消灭最危险的"假绿"(静态档看 CSS 文本说合规、实际渲染坏了——#49、冰山死规则均是)。
3. **强制执行(最大价值)**:规则从"纸面"变"真闸"——闸口跑的就是带规则的同一引擎,规则真触发;写规则的时间不白费。
4. **信任 / 去模型依赖**:几何判断从"靠 LLM 肉眼"变"机器每次都算",可复现、与模型无关(呼应"降低大模型依赖")。
5. **体验 / 速度**:scope 调速,编辑时 1–2s 且只关改动页;告别今天 309 行全 deck 存量噪声。
6. **规则资产复利**:加新规则 = 写一个对渲染 DOM 求值的函数,无"放哪个文件/哪种语言"的纠结 → 愿意把更多设计品味固化成规则 → 生成即对比例升高。
7. **三入口一致**:生成 / 校验 / check-only 给同一裁决,不再"生成时说好、审查又报"。
8. **可读性 / 接手**:读一个文件知道全部规则。

### 诚实的代价与风险
- **硬依赖 playwright/chromium**:今天静态档零依赖;统一后凡跑闸的环境(hook/CI/他人机器)都要有浏览器。缺了须硬提示、不可静默放行。
- **迁移有 finding 漂移风险**:每条静态规则搬成 JS 须回归对齐。
- **极小延迟地板**:即便算 1 帧也有浏览器启动几百 ms;单字符改从"瞬间"变 1–2s。缓解:常驻浏览器 / 只在保存时跑。
- **非字面 100% 一处**:P50 体积、资产存在性等纯字节检查仍在 runner(与渲染无关)。约 95% 统一,仍远胜两套规则。
- **规则语言变 JS**:几何规则本就是 JS,净效果是向"唯一能做全部的语言"收敛。

**净判断**:核心收益是"规则存在 ↔ 规则执行"重新对齐 + 消灭假绿 + 砍重复维护;最大真实代价是全环境带浏览器 + 一次性迁移。投入直击 #49 痛点,值得做,但**小步迁**(先 canvas-center 一条验证闭环),摊薄漂移风险。

---

## 5. 迁移路径(增量、低风险)

1. **冻结**:不再往 `_validate_audits.py` 加新规则(止血)。
2. **逐条搬**:`STATIC_AUDITS` 每条搬进 `audits.js`、改为对渲染 DOM 求值;搬一条删一条 Python 原版,跑回归对齐 finding。
3. **收尾**:`_validate_audits.py` 清空后删除;P50 等字节级检查留 runner,明确标注"源字节检查"。
4. **终态**:一个 `audits.js`(规则)+ 一个瘦 runner + hook 调它(scope=changed)。改规则永远只动 `audits.js`。

---

## 6. 执行顺序(2026-06-03 用户定)

> **先做"合并",再做本统一改造。** —— 用户明确:动这个统一架构之前,先把代码/分支合并到一个干净、合并后的基线上,避免在分叉状态上重构(否则统一本身又落进"两处"的坑)。

- [x] **前置:合并** —— 已用整合分支 `integrate-pr16-pipeline-restructure`(off main,main-as-base)作基线;`待澄清(a)` 的"双 clone"实测是 symlink(`~/.claude/skills/feishu-deck-h5` → `Documents/GitHub/.../skills/feishu-deck-h5`),单一真源,非两份。
- [ ] 步骤 1:冻结静态档新增(建议:给 `_validate_audits.py` 顶部加"FROZEN,新规则进 audits.js"横幅;本次未做,留作下步)。
- [x] 步骤 2:搭 `audits.js` 骨架 + 迁 `R-VIS-CANVAS-CENTER` 验证闭环(finding 对齐 ✅)+ 写入 hook 接入(canvas-center,playwright 缺硬提示)。
- [ ] 步骤 3:逐条迁剩余 ~39 条静态规则,各自回归对齐。
- [ ] 步骤 4:删 `_validate_audits.py`;Path-A 渲染流也接统一引擎(写入 hook 只逮 Path-B,#49 是 Path-A —— 真正堵 #49 还需把统一引擎接进 render/交付的自动校验)。

### 待澄清(动手前)
- "合并"具体指哪一个?候选:
  - (a) **两个 repo clone** 的合并/统一(本机存在 `~/.claude/skills/...` symlink 指向的 clone 与 `Documents/Github/feishu-deck-h5` 的 runs;preflight 曾警告双 clone)。
  - (b) **git 分支合并**(把当前未合并的分支/改动并回主干,作为重构基线)。
  - (c) 其它(如先把本会话 everbright deck 的改动提交/合并)。
