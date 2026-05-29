# design-phase — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:GENERATION 设计阶段细节(Step5 密度闸门/DESIGN-PLAN 规格/增量vs批量)

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

**Step 2 · 页级 spec(Q0–Q4 + A 档六维 + density budget)**
- **hero 页:必填** Q0–Q4 + 六维 spec(见 `DESIGN-FIRST POLICY` 设计前预检)。
  且**先翻设计词汇库再落 layout** —— `narrative patterns A–N` + `component
  utility classes`(见文末两节),挑一个 striking pattern,而不是反射性套 3 卡。
- **支撑页:轻量** —— 角色判断 + `Decision rule` 选个 schema layout 就够,
  不必写满六维。
- **每页必走 density budget** —— Q2 的 A/B/C/D 档分完之后,写一行 page-level
  量盘子:**核心信息块 X 个 + 支撑信息 Y 个(含下沉策略)≤ layout 自然容量 Z**。
  装不下不要回头压字号,回 Q1 砍内容(细则见 `DESIGN-FIRST POLICY` Q2)。
  作用是把"过密"挡在 markup 之前 —— 真正的"挤"问题一半根因都是这一步没量。

**Step 3 · 输出设计方案**
- chat 里出 Design pass 表(格式见 `DESIGN-FIRST POLICY` → Design pass output),
  每行带:角色 / 唯一重点 / path / 是否 hero。
- hero 页各附一句话 design intent statement。

**Step 4 · 闸门 + 落盘**
- 有 beyond-default 页 → 等用户确认;全 schema → 宣告即走。
- 确认/宣告后:PREFLIGHT → new-run → **把锁定的方案写一份
  `runs/<ts>/output/DESIGN-PLAN.md`**(与 FEEDBACK.md / PROMPTS.md / texts.md
  同级),生成严格照它走;中途想偏离先回来改 plan,不静默漂移。

**Step 5 · 密度闸门(每次 render 后过一遍,直到通过再交付)**

Q2 的 density budget 是"内容能装下"的预算,但 markup / deck.json 写完
render 出来后,**实际字数、留白、装饰堆积**还会涨一轮 —— 必须再过一遍密度。
这一步**只查密度,不再质疑焦点**(focal 由 Q1 唯一主旨 + `R-FOCAL-CHECK` 接管;
双 hero / 双圆 / 双方块 / 痛 vs 解 等"多 hero"layout 不在本闸门质疑范围)。

**过密信号(命中 ≥1 即过密 · 不分 layout)**:
- **块内过满**:单个非点题正文 > 30 字 · 或单块塞 ≥ 5 个内联元素(图标 / 标签 / 描述 / 注释 / 边框)
- **块间憋气**:相邻块间距 < 块自身高度 1/4 · 或核心块距画框 < 60 px
- **冗余表达**:主副标题同事 · 战略判断 + 正文 + 金句三层重复 · 同概念 ≥ 2 处说
- **支撑铺开**:底座 / 清单 / 注脚每项 > 1 行 · 或带强装饰(框 / 阴影 / 渐变)
- **长句铺垫**:顶部 / 中部完整长句占大色块

**降密 4 个方向(都做,不是选一个)**:
1. **块内压实** —— 长句 → 名词短语,装饰减半,内联元素 ≤ 3
2. **块间松气** —— 增 gap,核心块四周 ≥ 80 px,禁贴边
3. **冗余清理** —— 副标题 / 重复结论 / 多余 caption,删
4. **支撑下沉** —— 细节藏到底部窄带 / cfoot 注脚 / 下一页,每条"名称 + 一行 + 色点"

**症状 → framework 工具(动词级)**:

| 症状 | 用什么 |
|---|---|
| 长句铺垫 / 战略判断 | 顶部 `<p class="lede">` · 或 `<div class="data-panel is-blue">`(左 4 px 蓝条 + 灰底) |
| 散排并列 ≥ 4 无方向 | `flow`(variant: process / timeline)· `arch-stack` · `pipeline` |
| 中间连接带 3 行字 | 压成单行短标签(箭头 / 连接线上) |
| 底座 / 清单 / 支撑 | `kpi-strip` 底部窄带 · 每项"名称 + 一行 + 色点" |
| 金句 / slogan | `quote` layout 整页 · 或 inline `<span class="hl">` 高亮关键词 |
| 全幅照 + 短句 | `image-text` |
| 客户案例 4 拍 | `content/story-case`(别手搓 4 拍) |
| N×M logo | `logo-wall` · N>12 必须按行业 / 阶段分组 |

**量化护栏(纯密度,不含 focal)**:
- 单个非点题正文 ≤ **30 字** · 点题句(hook / quote / lede / arc / slogan)≤ **50 字**
- 全页完整句(非点题正文)≤ **2 句** · 单块内联元素 ≤ **3** · 核心块四周呼吸 ≥ **80 px**
- 底座 / 清单类每项说明 ≤ **1 行** · 同信息重复 = **0 处**

> **documented density exception**:数据表 / 架构图 / 全 case 矩阵 / 4-6 节点
> 时间轴本来就密。命中:走对应 layout(`table` / `arch-stack` / `scene-grid` /
> `flow timeline`),允许超阈值,但 4-tier ladder 不能省。

**输出前自检(纯密度,逐条问)**:

- [ ] **眯眼测试**:缩到 1/3 倍率,主结论可识别 AND 装饰糊成一片 → 通过
- [ ] 块内还有长句 / 整段可压成名词短语?(只看非点题正文)
- [ ] 块间憋气?能否增 gap?四周能否多留 60-80 px?
- [ ] 还有副标题 / 重复结论 / 多余 caption 可删?
- [ ] 底座 / 清单 / 支撑项每条是否压到 1 行 + 1 色点?
- [ ] 装饰(框线 / 阴影 / 渐变)是否过多,有的可不可以去掉?

> **跟 validator 的分工**:`R-VIS-BALANCE` 自动审"块间憋气"的几何信号,
> `R-VIS-BODY-FLOOR` 审密集小字,但**字数 / 冗余 / 装饰堆积**这些内容向密度
> validator 不查(R-COPY-ABSTRACT 已撤,理由 = 用例太杂)。本 Step 5 就是
> 这块**人工兜底**,作者跑一遍,validator 跑另一半。两半合起来 = 完整密度防线。

### DESIGN-PLAN.md 落盘(mandatory)

new-run 之后立即写 `runs/<ts>/output/DESIGN-PLAN.md`,内容:

1. **方案表** —— Step 3 那张表(逐页:角色 / 唯一重点 / layout 或 path / 是否 hero / 为什么)。
2. **hero 页 spec** —— 每张 hero 页的 Q0–Q4 + A 档六维 + 选定的 pattern。
3. **补全计划** —— 哪几页补了内容 / 文案,补的方向,并标注来源性质(公开行业知识 / 产品能力 / 类似客户故事),确认没有 attributed facts。

作用:(1) 生成步有据可依,防 LLM 自己跑偏离开方案(冰红茶 slide 9 那类);
(2) 用户 / 维护者事后能复盘"这份 deck 当初是怎么设计的";(3) 二次迭代时是 diff 基线。
随 run 一起走(`package-deliverable.sh` 已含 `*.md`)。

### 批量 vs 增量:一页一页喂时,设计一页就执行一页(别拖延)

DESIGN PHASE 有两种节奏,**按用户怎么喂内容自动选**:

- **批量模式**(用户一次性给齐主题 / outline / 全部素材):四步走完整 —— 全 deck
  方案表在 chat 出 → 确认 → 一次 new-run + 落 `DESIGN-PLAN.md` + 生成全 deck。
- **增量模式**(用户一页一页喂:"第一页…""第二页…""下一页" / 逐页发路径):
  **设计一页就立刻执行一页,不要攒**。
  1. **第一页就 new-run**:别等方案攒齐。第一页一来就 PREFLIGHT → new-run 建好
     `runs/<ts>-<slug>/`,初始化 `deck.json` + `DESIGN-PLAN.md`。这样 deck 从第一页
     起就在磁盘上、随时能打开。
  2. **每页:设计 → 立即 render / append → 下一页**。该页是 hero / beyond-default
     就先过确认门;是 schema / lift 就直接落。`deck.json` 和 `DESIGN-PLAN.md` 逐页增长。
  3. **不要把已设计好的页只留在 chat 里等"全部齐了再生成"** —— 那是拖延,用户会问
     "怎么没在本地目录"。**设计完一页 = 落盘一页。**

判据:看用户喂法。逐页喂 → 增量(边设计边落盘);一次性给全 → 批量。拿不准就增量
(对用户更可见、可中途调整)。增量模式下确认门不变:schema / lift 页直接落,
hero / beyond-default 页仍先停下确认那一页再落。

---

