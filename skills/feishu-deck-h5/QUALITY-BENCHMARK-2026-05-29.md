# Deck 生成质量基准 · 2026-05-29

> 方法:5 个薄 brief(q2-review / retail-proposal / product-launch / monthly-data / customer-case)× {Opus, Sonnet} = 10 份真实生成(走完整 Path A 管线),每份由独立 agent **盲评**打分(1-5 × 5 轴)。20 agent。
> 用途:本文件是后续"质量引擎"四块工作的**基线 + 回归指标**。每次改完重跑此基准,看分数涨没涨。
> 生成产物在 `/tmp/qbench/<slug>-<model>/`(临时;注意写在 /tmp 导致部分品牌图/图标资源路径未解析,见 §4 注意)。

## 1 · 总分(5 deck 均分,满分 25)

| 轴 | Opus | Sonnet | Δ(O−S) |
|---|---|---|---|
| 一致性 consistency | 4.6 | 4.4 | +0.2 |
| **丰富 richness** | **3.6** | **3.8** | **−0.2** |
| **质量 quality** | **3.6** | **3.4** | +0.2 |
| 变化 variety | 4.6 | 4.0 | +0.6 |
| 契合预期 expectation_fit | 4.6 | 4.2 | +0.4 |
| **总分** | **21.0** | **19.8** | **+1.2** |

每 brief 总分(O / S):q2-review 23/19 · retail 23/21 · product 18/18 · **monthly-data 18/22(Sonnet 反超)** · customer-case 23/19。

## 2 · 三个反直觉结论

**① Sonnet 已经≈Opus(差 1.2/25,~5%)——"Sonnet 也能跑"基本已经成立。**
系统(schema/模板/validator)已经把大部分质量扛住了。丰富度上 Sonnet 甚至略高;monthly-data 上 Sonnet 反超 4 分。模型差距只集中在 **variety(+0.6)/ expectation_fit(+0.4)**——即 Opus 的版式选择略更"刻意"。
→ **结论:别再为"追平 Sonnet"投入。那点差距靠"系统替模型做版式选择"(库+调度)就能抹平,不需要强模型。**

**② "千篇一律"被误诊了——单 deck 内版式重复=0。**
10 份 deck **每份 maxrepeat=1**(没有任何一份重复用同一 layout),distinct=slide_count。两个模型都没掉进"cover+4×3卡+end"。所以"雷同"不是 layout 重复问题。

**③ 真正的天花板 = 视觉丰富度,卡在 ~3.5/5。**
richness(3.6/3.8)和 quality(3.4/3.6)是**最低的两轴**(一致/变化/契合都 4+)。系统已经"版式多样且一致",但"看起来都差不多、不够有质感"。这才是"效果≠预期"的真相 —— 不是结构,是**视觉质感**。

## 3 · 差距地图(102 条评审信号聚类,按出现频次)

| 频次 | 主题 | 含义 |
|---|---|---|
| **27** | **零图像/图标/插画** | 每份 deck 都是"深色上的彩边圆角卡片",全程无图标、无配图、无插画。**这是丰富度天花板的头号原因。**(且有信号指出 deck.json 声明了 KPI 图标却没渲染出来——见 §4) |
| **20** | **封面/目录最欠设计** | cover 常只是 h1 里塞个 `<br>` 第二行,没 eyebrow/keyline;agenda 就是一摞裸编号 pill。开场页是全 deck 最平的。 |
| 7 | 焦点/层次弱 | 含品牌图(logo/cover-bg/slogan)在产物里未渲染、把"目标值"当"实测值"放 hero 等 |
| 6 | 语义色不自洽 | 颜色编码跟 legend 不是 1:1(同一 verdict 两个颜色);框架 CSS 给部分层级定义了色、部分没有 |
| 6 | 留白/密度不均 | cover/agenda 稀,issue-tree/verdict 挤,同 deck 内疏密失衡 |
| 6 | 平铺清单/欠设计页 | before-after、2col 都靠 4-5 条 bullet,措辞节奏雷同 |
| 2 | 同一张卡的质感单一 | 中段多页都是"圆角彩边卡"同一视觉家族,快翻有家族脸 |

**一句话**:不是版式不够多,是**视觉语汇太单一**——全靠"文字+彩边卡",没有图标/图像/插画/多样质感,开场页尤其平。

## 4 · ⚠️ 一个要先核实的:资源未渲染

多条信号说"deck.json 声明了图标/品牌图(KPI 图标、lark-logo、lark-cover-bg、lark-slogan)但在 `out/` 产物里没显示"。**部分是测试假象**:本次生成写在 `/tmp/qbench/`(仓库外),skill-relative 资源路径(`../../../skills/...`)在 /tmp 不解析。但"stats 的 icon 字段声明了却不渲染"可能是**真的渲染器没接 icon 字段** —— 值得 5 分钟核实(在仓库 `runs/` 内渲一份看图标/品牌图是否出)。若属实,这是一条便宜的高价值修复。

## 5 · 据此重排"质量引擎"四块

| 原计划 | 据数据调整 |
|---|---|
| ③ 模型基准 | **已完成诊断**(差距小)。保留为**回归 harness**:基线 = Opus 21.0 / Sonnet 19.8 / richness ~3.7 / quality ~3.5。**降级"追平 Sonnet"。** |
| ① 库扩容 | **重心转移**:variety 已够好,不缺 layout。缺的是**视觉原语**——图标体系、图像/插画支持、突破"彩边卡"的多样质感、给封面/目录的 striking 开场 pattern。**这是 #1 杠杆(27 信号)。** |
| ② 质量评分器 | **现在可校准建**(见 §6)。要检测的不是"layout 重复"(没发生),而是 §3 的真问题。 |
| ④ 预览环 | 仍有用——§4 的资源未渲染问题,有真预览就当场抓到。 |

## 6 · ② 设计质量评分器 — 校准后的规则集(下一步建)

按差距地图,新规则(扩 R-VIS-* 那条线,deck 级 + 静态结构分析,大多不需 Chromium):

- [ ] **`R-VIS-NO-IMAGERY`**(头号):整 deck N+ 页零图标/图像/插画 → "视觉语汇单一,建议加图标/配图/插画" warn。校准:当前 deck 普遍命中(richness~3.5)。
- [ ] **`R-VIS-FLAT-OPENER`**:cover/agenda 欠设计(cover 只有 h1 无 eyebrow/keyline;agenda 纯裸 pill)→ warn。
- [ ] **`R-VIS-TEXTURE-MONO`**:大多数内容页共用单一视觉 idiom(全是彩边圆角卡)→ "质感单一" warn。
- [ ] **`R-VIS-COLOR-SEMANTIC`**:声明了 legend/语义色却不自洽(同义项不同色)→ warn。
- [ ] 复用现成:`R-FOCAL-CHECK`(焦点)、`R-VIS-BALANCE`(空/失衡)纳入复合分。
- [ ] **richness 复合分**:每页+全 deck 一个"设计丰富度分"(图标/图像用量、视觉 idiom 多样性、密度均衡、焦点清晰)。
- 工程纪律:新规则**必须带 must-fire + must-not-fire 测试**(F-09:validator 35 条只有 ~3 条有测试,别再扩脆弱面);测试 fixture 直接用本次 10 份 benchmark deck(已知该高/该低)。

## 7 · 回归用法
改完 ①/② 后,重跑 `deck-quality-benchmark` 工作流(同 5 brief × 2 模型),对比本基线:richness/quality 应从 ~3.5 往上走,且 Opus−Sonnet 差应缩小。
