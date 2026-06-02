# 让同学也能做出"康师傅级"飞书 deck —— 诊断 + 改进规划(定稿)

> 维护者内部文档 · 2026-05-30 · 基于 6 个调研 agent 交叉验证 + 本地复核 + 对抗式审校
> **审校已折入**:对抗审校的 5 条 must_fix 全部修正,should_improve 全部吸收,missing 6 点补齐。本稿额外修正了**审校自身的两处事实错误**:(1) `deck-json/templates/blocks/` 实际存在(10 个 `.fragment.html`),审校误判为不存在——它在 `deck-json/` 下而非顶层 `templates/`,审校"别拿不存在资产做接力"的精神仍采纳,改为如实标注位置;(2) AUDIT 工单号审校与初稿**都引错了**,以 AUDIT **正文 detail 段(376–409 行)为准**重新对齐:`F-36`=pptx桥、`F-37`=硬挂载门、`F-38`=WYSIWYG浅、`F-39`=协作评审(AUDIT 自己的摘要表 93–94 行与 detail 段编号不一致,这是 AUDIT 的债,执行前一律以 detail 段为准)。
> **已实测确认**(本地复核):36/44 raw、13 个 `_*.py`、18 个 deck.json `.bak`、deck.json 355KB(含 **105 个 `@keyframes`/31 个 `<svg>`/35 个 `<style>`**)、`经销商管理五张地图` = app.jsx + 7 个 `scene-*.jsx`(React iframe 工程真实存在)、SKILL.md 984 行/71KB、`examples/showcase.html` = 28 页 + 28 张 PNG(SKILL.md/references **0 处当 starter 入口引用**)、ICON_LIB(Lucide)、`deck-json/templates/blocks/` 有 10 个 `.fragment.html`、`package-deliverable.sh` **不做 inline**、`build.sh --inline` **只重建 skill 自带样例**(硬编码标题"先进团队的工作方式·飞书2026客户提案")、QUALITY-BENCHMARK §8 重跑后 Opus richness 3.6→**4.2**、quality 卡 **3.6**、Opus−Sonnet 差 1.2→**0.8**。

---

## 1. 一句话诊断

**标杆"康师傅 AI 讲座"= 你本人用 82% 手写 raw HTML(36/44 张,含逐页 bespoke `<style>` + 105 个 `@keyframes` + 31 个内联 SVG)+ 13 个一次性 Python 脚本直改 deck.json + 跨 3 天约 18 个 deck.json 备份多轮回退打磨出来的专家作品**(部分 hero 背后是 `app.jsx + 7 个 scene-*.jsx` 的完整 React 工程)。而 SKILL.md 主推的 happy-path(写 deck.json schema → render → finalize)在标杆里几乎没用上(0 个 base layout,schema 只占 18%),文档反而把 raw 钉成"罕见逃生口/要先过六维门"。

**真正的 gap 有两条,解法完全不同:**
- **(A) 降门槛(floor)**——同学连一份干净 deck 都常产不出来,被 PREFLIGHT 挂载门、DESIGN PHASE 六维门、9 步串行流程、984 行文档绕晕。**纯文档/工具问题,skill 内 100% 能解 —— 但仅对"已在 Claude Code + 已挂载本地盘"的同学有效。**
- **(B) 拉天花板(ceiling)**——标杆 bespoke 质感**根本没被产品化**,锁在"手写 raw 的工艺"里。同学既没这套手艺,也没你的私人 deck 零件库(含无法被片段库覆盖的 React iframe 工程)。这是真护城河,也是 skill 最大可补齐缺口。

**核心矛盾:文档体量按"让维护者不犯错"优化,不是按"让新人 5 分钟出第一张"优化。**

> ⚠️ **诚实边界**:本规划 12 个方案**全在 skill 内部**,都假设用户已在 Claude Code + 已挂载本地盘。对 AUDIT 点名的**中位作者(无终端、无 Claude Code 的 PM/销售/运营)——本轮零覆盖**。速通卡/showcase/edit-mode 他们一个都够不着。这批最大的下限用户**只能等托管面(AUDIT R-02,关 F-37+F-38)**。不能让"降门槛是主战场"的措辞盖过这个事实:本轮降的是**"已进场但被流程绕晕"那批人**的门槛,不是"根本进不了场"那批人的门槛。

---

## 2. 标杆是怎么做出来的 vs 文档教的怎么做

| 维度 | A · 标杆实际做法(专家工作流) | B · 文档教的 happy-path | 差距含义 |
|---|---|---|---|
| **raw 占比** | 36/44 = **82%** 手写 raw HTML(实测) | 主推 schema,raw 列为"escape hatch·极少用" | 同学照文档只能复刻那 18% schema 页 |
| **每页 CSS** | 多数 raw 页自带 `<style>`(35 处),逐页私有 CSS | schema 统一样式,0 私有 CSS | 差异化质感 = "每页一套私有样式表",schema 反对这件事 |
| **动画/SVG** | **105 个 `@keyframes` + 31 个内联 SVG**(飞轮/管道/架构 hub/手机壳) | schema 给不了 | QUALITY-BENCHMARK 说的"头号杠杆=视觉语汇"的物理来源 |
| **改 deck 工具** | **13 个一次性 `_*.py` 脚本**(最大 35KB),0 个用 deck-cli | deck-cli.py 14 个原子操作 | 专家觉得 cli 不够用宁可现写脚本;同学既不会写也没这些脚本 |
| **迭代轮数** | **约 18 个 deck.json 备份,跨 3 天**(备份名含 anim-revert/flywheel-revert) | 文档暗示"一把过" | 这份效果是几十轮试错 |
| **隐藏成本** | 最强的几张 iframe 背后是**完整 React 工程**(`app.jsx + 7 scene-*.jsx`);部分 hero 从隔壁 deck **移植** | 文档无此工作流 | 同学没有私人零件库;**这几张最强 hero 片段库根本覆盖不了** |
| **新人 time-to-first-deck** | 专家 30–60 分钟出像样的 | 新人读懂 PREFLIGHT+DESIGN+Path A 要 1–2 小时,且大概率卡门 | 实测可能"数小时或放弃",产出仍平庸 |

**结论:文档 happy-path 和标杆真实做法是两条不同的路。** 同学走文档,结构上注定做不出标杆质感。

---

## 3. 失败模式分层(谁撞上 / 根因 / 能否靠 skill 解)

| ID | 失败模式 | 谁撞上 | 根因属于 | skill 能解吗 | floor/ceiling |
|---|---|---|---|---|---|
| **F0** | **根本没有终端/不会挂载,产不出任何东西** | **无 Claude Code 的 PM/销售/运营(最大那批中位作者)** | **平台缺失(R-02 托管面)** | ❌ **本轮 skill 内零解**,须等托管面 | **floor(本轮不覆盖)** |
| **F1** | 已在 Claude Code 但产不出干净 deck(挂载/不会写 deck.json/render 报错) | 有终端但偶尔用的同学 | 工具/自动化 | ✅ 可解 | floor |
| **F2** | 产出但"平"(richness 已 4.2,quality 卡 3.6;封面/目录最弱) | 走纯 schema 的大多数同学 | 一半文档 + 一半设计判断 | ⚠️ 半自动可解,封顶靠模型 | ceiling(边际递减) |
| **F3** | 想做 bespoke hero 但不会写 raw / 不懂框架 | **几乎所有同学** | **能力 + 产品化缺失(核心矛盾)** | ✅ 可补:高频 raw hero 升 schema / fork 片段库 | ceiling(最大缺口) |
| **F4** | 被流程/模式绕晕(8 模式 + 多闸门 + 984 行) | 第一次/偶尔用 | **纯文档/认知** | ✅ 纯信息架构 | floor |
| **F5** | 迭代成本高(无快速预览反馈环) | 所有想"调到满意"的人 | 工具/自动化 | ✅ 可解 | floor(兼抬 ceiling) |
| **F6** | 资源不渲染(写在 runs/ 外路径不解析) | 把 deck 生成到 /tmp 的人 | 文档/工具边界 | ✅ 便宜 | floor |
| **F7** | **新人 fork 含 raw 的页后改坏 HTML(未闭合/坏 SVG),validator 只报 schema 不报 raw 内部 DOM 损坏** | 任何从 starter/片段库 fork 了 raw 的同学 | **下放 raw 引入的新失败模式** | ⚠️ 须新建兜底(见 §4 方案 6b) | floor(新增,必须配救援) |

**两条线判断:**
- **floor(降门槛)= F1/F4/F5/F6/F7 + F2 的认知一半** → skill 内可解,零模型依赖,本轮主战场(**但不含 F0**)。
- **ceiling(拉天花板)= F3 + F2 的设计一半** → 把"手写 raw 工艺"产品化成可复用 layout/片段,唯一真护城河;**但 quality 已卡 3.6、richness 已到 4.2,边际递减**(§6)。
- **F0 = 平台级缺口,本轮 skill 内无解,只能 AUDIT R-02 兜。**

---

## 4. 改进方案总表(按"减步骤/缩时间"杠杆从高到低排)

> **"已部分存在(接力)"列已逐条本地核实**,纠正初稿与审校的多处错判。effort 已按真实工程量重估。

| # | 方案 | 砍掉的步骤 | floor/ceiling | effort(已重估) | 已部分存在(接力,已核实) | 风险 |
|---|---|---|---|---|---|---|
| **1** | **30 秒速通卡 + SKILL.md 顶部分流**(新人 3 步 vs 维护者细节) | 砍"做 deck 先读 984 行 + 22 references" | floor/F4 | **trivial** | F-30 已瘦身;只放指针 | 卡与正文漂移会误导 → **必须配 §6 CI 断言** |
| **2** | **SHOWCASE→FORK 起步画廊**(showcase.html 28 页 + 28 PNG 做成 starter,选缩略图即 cp) | 砍 DESIGN PHASE 从零标 hero/定每页 path | both | **small**(入口+清洗,非 trivial) | ✅ `examples/showcase.html`(28 页)+ 28 PNG **从未作为 starter 入口被任何模式/DESIGN PHASE 引用**(仅作内部 eval 案例在 `converting-existing-material.md` 被提及)+ `import-html-slide.py` Mode A | **starter 必须优先用 schema-only/轻 raw**;重 raw hero 走片段库通道;占位全 `〔…〕`,剥净具名事实;**取材前先清洗 run 目录(见风险④)** |
| **3** | **交付话术默认提 EDIT-MODE + 退出 drift 提示** | 砍新人改文案"回 deck.json 改字段→重渲→再看"往返 | both | **trivial**(改一句话术)+ **small**(退出 drift 检测) | ✅ **edit-mode 已默认开**(`SKILL.md` 明写"default on since 2026-05-21",`_shell.html` 默认注入 `deck-edit-mode`,copy-assets 默认拷编辑器) | **真 gap 不是"opt-in",是交付第一句没提它 + 退出无 drift 提示** |
| **4a** | **render 默认接 finalize**(copy-assets+extract-texts+validate 三连) | 砍"记得跑 finalize 残留" | floor | **trivial** | ✅ `finalize.sh` 已三连 | 略慢,留 `--no-finalize` |
| **4b** | **finalize `--inline` 泛化到任意 output** | 给"我要单文件发邮件"一条路 | floor | **⚠️ medium(新代码,非接力)** | ❌ **`build.sh --inline` 只重建 skill 自带样例(标题硬编码),不能对任意 run output 出 inline;`package-deliverable.sh` 不做 inline**。**per-deck inline 路径不存在,要新写** | **别把 4a 与 4b 捆绑**:4a trivial 默认开,4b 是真工程量、**显式 opt-in**,inline 不设默认 |
| **5** | **一键"做份 deck"超级入口**(`deck.sh`:5 问→preflight+new-run+从 starter 生稿+render+finalize) | 折叠 PREFLIGHT + DESIGN Step1-4 + Quick start 成线性问答 | floor | **medium** | ⚠️ 复用现有脚本,别重写;= AUDIT 路线图缺口 | 不绕过硬挂载校验,只包装;内部复用避免平行维护面 |
| **6a** | **deck-doctor:把 validate 报错翻成人话 + 给手改建议(不自动改)** | 砍"读 validator-rules.md 全表人肉定位" | floor | **small** | ✅ validate.py 规则已结构化输出 | 纯翻译,无 DOM 风险 |
| **6b** | **deck-doctor `--fix`(只 patch deck.json 字段再 re-render)** + **raw 损坏诊断/回滚兜底**(解 F7) | 砍机械修 R48/R56/R20/R10/R-VIS-ORPHAN 的手工返工;给"raw 改坏了"一条救援 | floor | **⚠️ small-medium(新代码,非接力)** | ✅ 结构化输出是输入,**自动修是新逻辑+保守白名单+解释文案** | **绝不 regex 改 DOM**(E2 教训);**raw 内部 DOM 损坏只报告+建议从最近 `.bak` 回滚,不自动改 raw**(F7 兜底) |
| **7** | **活预览 render `--shots`**(渲后无头浏览器拍每页 PNG 拼联系单) | 压"render→逐页翻 44 页→记问题" | both | **small** | ✅ pptx-to-html 已带 Chromium | 须先 copy-assets;可选 flag,缺环境跳过 |
| **8** | **PREFLIGHT 草稿放宽 + 8 模式收敛成 3 行决策表** | 把挂载门从"动手前阻塞"→"交付前阻塞";砍反复选模式 | floor | **small** | ⚠️ 改时序/话术,不去闸门;**与 AUDIT F-37(挂载门)同一闸门,应交叉引用** | 草稿强标"未持久化" + 交付前硬落盘 |
| **9** | **top-3 raw hero 升一等 schema layout**(flywheel / scene-grid / striking cover) | 砍 hero 页"raw + 六维 spec + 手写 1-3 万字符 HTML + 过门" | **ceiling** | **large** | ⚠️ arch-stack 有雏形;chart 已有 | 选错 pattern 做无人用 layout;每个带 must-fire/not-fire 测试(F-09);一次只做 2-3 个最高频 |
| **10** | **raw-hero 片段库**(占位化标杆 hero 存 `deck-json/templates/blocks/` 旁,带预览)— 方案 9 过渡态 | 砍"翻词汇库→从零写 raw"中"从零写"那段 | ceiling | **⚠️ medium-large(逐张人工活,非脚本批处理)** | ✅ `narrative-patterns.md` + `templates/slide-recipes.html` + `references/richness-primitives.md`(逐字配方)+ **`deck-json/templates/blocks/` 已有 10 个 `.fragment.html`**;**但占位化 36 张是实打实人工活,基本从零建** | **iframe hero(`app.jsx + 7 scene-*.jsx` 的 React 工程)无法占位化进片段库——最强的几张 hero 不可复用**;占位剥净具名公司/数字 |
| **11** | **render `--enrich`:把已 ship 的 richness 建议变默认动作 + 数字结构自动落 chart** | 砍 DESIGN Step2 逐页判断 icon/图表 + Step5 密度返工 | both | **small-medium** | ✅ **richness 三件套(图标自动建议/R-VIS-NO-IMAGERY warn/chart 优先)已 ship(§8,richness +0.6)**;ICON_LIB(Lucide)+ chart(bar/line/donut)已有。**本轮只做增量:建议→默认 + 自动落 chart** | 关键词→icon 可能错配,宁缺勿错配 + 可关;**绝不自动编造数据** |
| **12** | **deck-cli add-pattern**(从画廊往现有 deck 插高光页)+ **框架级修动画重播**(`_patch_anim_restart.py` 的 MutationObserver 上沉 render-deck.py) | 砍增量模式"某页 bespoke→走 raw→六维→手写";别让每个同学手注动画补丁 | both | **medium** | ✅ deck-cli insert/clone 已有;`_patch_anim_restart.py` 是普适框架 bug | 依赖方案 9/10 先有库;**先做风险⑥的脚本盘点,否则 add-pattern 会被同样绕过** |

**明确否决(避免投错方向):**
- **❌ 现在做独立 WYSIWYG 编辑器作主线(AUDIT F-39=WYSIWYG 太浅,P1;并入 R-02/R-03)**—— large 且已排期。没有画廊和 schema 化 hero 前先做深 WYSIWYG,会让新人在空白 deck 上面对更多决策 = 增步骤。**注意:这与方案 8 要碰的 F-38(硬挂载门,P0)是不同工单,F-38 应交叉引用而非否决。**
- **❌ 接外部 AI 文生图 API**—— 破坏 local-first / 单 HTML / 离线交付核心契约,引 key/配额/版权/风格漂移,与"降低大模型依赖"原则冲突。要视觉语汇走方案 11 本地确定性资产。

---

## 5. 分阶段路线图(回归成本已计入,见 §6)

### 🟢 本周(纯文档/话术 · 几乎零工程,主攻 floor/F4/F1)

只放**真·trivial 且确实是"提到默认入口"**的项,审校点名的伪 trivial 已移走。

1. **方案 1 速通卡 + 顶部分流** → F4。SKILL.md 顶加 ~15 行"新人 3 步" + 明标"下面 900 行是维护者细节"。**配 §6 CI 断言防漂移。**
2. **方案 2 起步:激活 showcase 入口** → F1/F4。SKILL.md 顶部 + DESIGN Step2 加"先看 `examples/showcase.html` / 28 张 PNG 选最接近的 pattern"。零成本最大杠杆(从未被任何模式引为入口)。**先做风险④的 run 目录清洗。**
3. **方案 3 交付话术默认提 edit-mode** → F5/F1。交付第一句改"打开 HTML 按 E 改文案 Cmd+S 存盘"。**edit-mode 已默认开,这是纯话术。**
4. **方案 4a render 默认接 finalize** → F1。末尾默认 `finalize local`,留 `--no-finalize`。**(4b inline 移到两周,不在本批。)**
5. **方案 8 模式收敛 + 草稿放宽** → F4/F1。MODE SELECTION 收成 3 行决策表;PREFLIGHT 加 `--draft` 旁路(草稿不持久 + 交付前硬落盘)。**交叉引用 AUDIT F-38。**
6. **方案 6a deck-doctor 报错翻译(只解释不改)** → F4/F5。`small` 但纯只读,可挤进本周。

### 🟡 两周(medium · 把"工艺"半产品化 + 补真工程量项)

7. **方案 2 完整 starter 画廊** → F1/F3。4-6 套 starter(AI 内部讲座/客户提案/周会复盘/产品发布),**优先 schema-only/轻 raw**,全 `〔…〕` + `new-from-starter.sh`。**重 raw hero 不进 starter,走片段库。**
8. **方案 10 raw-hero 片段库(收敛目标)** → F3。**两周只占位化 4-6 张最高频 hero(flywheel/iceberg/scene-grid/dashboard),带预览**,明确这是**逐张人工工程不是脚本批处理**。36 张全量挪到一个月+。**iframe React hero 不在覆盖范围。**
9. **方案 7 活预览 `--shots`** → F5。复用 Chromium。
10. **方案 11 render `--enrich`(增量)** → F2。**承认基线已 4.2,本轮只把建议变默认 + 自动落 chart;爬坡空间只剩 0.3,边际递减。**
11. **方案 4b finalize `--inline` 泛化** → F1。**新代码,medium,inline 仍 opt-in 不设默认。**
12. **方案 6b deck-doctor `--fix` + F7 raw 损坏兜底** → F4/F5/F7。先覆盖 5 条机械规则,只 patch deck.json;raw 内部损坏只报告 + 建议回滚。
13. **方案 5 超级入口 `deck.sh` 雏形** → F1/F4。串现有脚本。

### 🔵 一个月+(large · 拉天花板 + 补 F0 平台缺口)

14. **方案 9 top-3 raw hero 升 schema layout** → F3/F2。flywheel + scene-grid + striking cover,每个带 parity 契约 + must-fire/not-fire 测试。
15. **方案 10 全量 36 raw 占位化** → F3。逐张人工,排在这里。
16. **方案 12 add-pattern + 框架级修动画重播** → F3/F5。**先做风险⑥脚本盘点再设计 cli。**
17. **richness 下一 frontier**(QUALITY-BENCHMARK §8 未做)→ F2:真图表/figure/插画(quality 卡 3.6 的解药)、`R-VIS-COLOR-SEMANTIC` 语义色、texture-mono 雷同检测。
18. **接力 AUDIT 工单(对齐 detail 段编号)**:
    - **R-01**(关 **F-36**:HTML→PPTX 桥)—— 解"要 .pptx 的干系人",最高杠杆。
    - **R-02**(关 **F-37 硬挂载门 + F-38 WYSIWYG 浅)—— 唯一能解 F0(无终端中位作者)的路径,`deck-editor.py` commit c327192 可复活。**
    - **R-04**(关 **F-39**:协作/评审)。
    - **F-47**(治理文件不随分发,small)。

---

## 6. 北极星与回归指标

**北极星拆成两个不冲突的承诺** —— 不能在同一句里要求新人"不碰 raw"又达"标杆 bespoke",QUALITY-BENCHMARK 已证明纯 schema 路径 quality 卡 3.6:

- **floor 承诺**:非工程师同学(**已在 Claude Code**)10 分钟内、不写一行 deck.json、不碰 raw,产出一份 **4.2 级、能直接发、不出错** 的 deck(benchmark §8 已背书 richness 4.2 可达)。
- **ceiling 承诺**:会用的同学一条命令把**产品化后的** hero layout / 片段 fork 进自己 deck(碰 schema 化 hero,不碰裸 raw)。
- **F0 不在北极星内**:无终端中位作者本轮无解,显式标注"待 R-02 托管面"。

| 指标 | 现状(baseline,已核实) | 目标 | 怎么量 |
|---|---|---|---|
| 新人 time-to-first-good-deck(已在 CC) | 数小时 / 经常放弃 | **≤10 分钟** | 找 3 个没用过的同学实测计时 |
| happy-path 步骤数 | 9 步 + 6+ STOP 门 | **3 步** | 速通卡步数 |
| 必读文档量(动手前) | 984 行 + 22 references | 顶部 ~15 行速通卡 | eager token 不变,"必读"坍缩 |
| **速通卡防漂移** | 无 lint/CI | 卡内每个命令/路径进 **validate 或 CI 断言**(命令仍存在才过) | CI 断言数 = 卡内命令数 |
| validate 失败自救率 | ~0 | deck-doctor 机械修 ≥ 50% 报错 | --fix 闭环规则数 / 总 R-rule |
| benchmark richness(Opus) | **已 4.2**(§8 +0.6) | **≥4.5(只剩 0.3,边际递减)** | deck-quality-benchmark(5 brief×2 模型) |
| benchmark quality(Opus) | **卡 3.6(+0.0)** | **≥4.0**(靠真图表/figure) | 同上 |
| 新人能命中 raw-hero 模板 | 0(片段库不存在/showcase 0 入口引用) | starter + 片段库 ≥ 8 个可 fork hero,每个有预览 | 画廊条目数 |
| Opus−Sonnet 差 | **1.2→0.8**(§8) | 保持 ≤1 | benchmark 总分差 |
| **F0 覆盖率** | **0**(无终端无解) | 本轮**显式不承诺**,待 R-02 | —— |

**回归护栏 + 成本纪律**:每加一套 starter / 一个 schema hero layout,跑一次 benchmark 回归(5 brief×2 模型盲评)。**12 个方案里方案 9/10/11/14/15/17 至少 6 个触发回归,每次都要钱+时间+人判趋势——两周/一个月窗口已把这些串行回归循环算进,实际节奏比"纯编码时间"慢。** LLM 盲评有噪声,看趋势不看单点。

---

## 7. 风险与边界

**(1) 产品化 raw 会不会牺牲灵活度?** 不会,**保留 raw 作永久逃生口**。方案 9 只把出现 ≥3 次的高频 pattern 升 schema(flywheel/scene-grid/cover),长尾仍走 raw。每个新 layout 必须带 parity 契约 + must-fire/not-fire 测试(F-09 教训)。**但有硬上限:`app.jsx + 7 scene-*.jsx` 的 React iframe hero 是整个工程,片段库/schema 都覆盖不了——标杆最强的几张 hero 不可复用,这是产品化的天花板。**

**(2) 自动补全会不会触碰"禁造具名事实"红线?** 严守 CONTENT-DENSITY 硬护栏:
- 方案 11 自动配**图标**(查 ICON_LIB,确定性,不调 LLM,宁缺勿错配)和**图表**(仅当大纲已有明确数值结构才触发)——**绝不自动编造数据/公司名/数字**。
- 方案 2/10 的 starter 与片段库占位文案必须**全 `〔…〕` 空槽**,占位化时**剥净标杆具名公司/数字**(康师傅/真实 KPI 一律抹掉)。

**(3) 减闸门会不会破坏 PREFLIGHT / 交付硬契约?** **不去闸门,只改时序**:
- 方案 8 草稿放宽 = 硬挂载从"动手前阻塞一切"移到"首次写盘前",草稿强标"未持久化/交付前必须落盘",交付硬闸门保留(与"防 ephemeral 丢失"是审慎权衡)。**这正是 AUDIT F-38 同一闸门,交叉引用而非否决。**
- 方案 3 round-trip 分层:**文案编辑**走 edit-mode 直接存(extract-texts 能回收,天然安全);**改结构/动画/新增 raw** 仍回 deck.json;edit-mode 退出检测非文本 DOM 变更就提示 sync,finalize 默认跑 `sync --dry-run` 报 drift。
- 方案 6b deck-doctor:**只 patch deck.json 字段再 re-render,绝不 regex 改 DOM**(E2 的 sed 吃 `</div>` 教训);拿不准只建议不动手。

**(4) raw-heavy starter 与 edit-mode round-trip 天然冲突**:标杆 raw 页 data.html 含逐页私有 `<style>`,fork 后这些会跟着复制,新人用 Cmd+S 改结构极易撞 round-trip drift(改了 DOM 没回灌 deck.json)。**对策**:starter 画廊优先 schema-only/轻 raw(可安全 round-trip);重 raw hero 单独走片段库/add-pattern 通道并强标"改这页要回 deck.json";**新增 F7 兜底**:新人把 raw 改坏(未闭合/坏 SVG)时,validator 只报 schema、deck-doctor 不碰 DOM,所以提供"raw 损坏诊断 + 建议从最近 `.bak` 回滚"作为唯一救援。

**(5) 别让 starter 泄漏专家私人脚手架**:标杆 run 根有 13 个 `_*.py` + 18 个 `.bak` + React 工程。方案 2/10 取材前**必须先清洗 run 目录,只取 `output/deck.json` 的占位化版本**,否则临时脚本和备份会一起进 starter 画廊。

**(6) 专家为何弃用 deck-cli 改写一次性脚本**:方案 12 add-pattern 上线前,**先盘点 13 个 `_*.py` 各做了什么 cli 做不到的事**(疑似缺批量/正则化/跨页操作)。若不查清,新加的 cli 命令会被同样绕过。

**(7) 文档减负本身的债**:速通卡与 900 行正文会漂移。**速通卡里每个命令/路径进 validate 或 CI 断言**(命令不存在则 CI 失败),否则它会和正文漂移——这正是文档本身的债,不能用更多没人维护的文档去补。

**(8) 别把工作量投错方向**:WYSIWYG 编辑器(F-39)和外部 AI 配图 API 已否决。本轮主战场是"把已有零件提到默认入口"+ 补几个真工程量项(4b/6b/10/11),**不是新造系统**。

---

## 附 · 相关文件路径(供执行定位,均已本地核实)

- 标杆 deck:`runs/20260524-112833-kangshifu-ai-lecture/output/deck.json`(355KB,36/44 raw,105 `@keyframes`/31 `<svg>`/35 `<style>`)
- 标杆专家脚手架:同 run 根目录 13 个 `_*.py` / `output/*.bak*`(18 个 deck.json 备份) / `input/经销商管理五张地图/` 与 `output/prototypes/dealer-five-maps/`(`app.jsx + 7 scene-*.jsx`,React 工程)
- Skill 根:`skills/feishu-deck-h5/`
- 待激活孤儿资产:`examples/showcase.html`(28 页)+ `examples/showcase-previews/`(28 张 PNG)——**从未作为 starter 入口被任何模式引用**
- 已有零件(已核实):`assets/edit-mode/`(默认开)、`assets/finalize.sh`(三连)、`assets/package-deliverable.sh`(**不做 inline**)、`build.sh --inline`(**只重建 skill 样例,标题硬编码,不通用**)、`assets/new-run.sh`、`assets/preflight.sh`、`deck-json/render-deck.py`(ICON_LIB / Lucide)、`deck-json/deck-cli.py`(14 ops)、`deck-json/import-html-slide.py`、`deck-json/templates/blocks/`(**10 个 `.fragment.html`,在 `deck-json/` 下非顶层 `templates/`**)、`templates/slide-recipes.html`、`references/narrative-patterns.md`、`references/richness-primitives.md`
- Meta 文档(工单号以 detail 段为准):`AUDIT-2026-05-29.md`(**F-36=pptx桥→R-01;F-37=硬挂载门→R-02;F-38=WYSIWYG浅→R-02/R-03;F-39=协作→R-04;摘要表 93–94 行编号与 detail 段不一致,以 detail 段为准**)、`QUALITY-BENCHMARK-2026-05-29.md`(§8:Opus richness 3.6→**4.2**,quality 卡 **3.6**,Opus−Sonnet 差 1.2→**0.8**;下一 frontier=真图表/figure/插画)

---

*生成方式:6 维并行调研 agent(标杆解剖/上手摩擦/失败根因/已有资产/解法空间/外部对照)→ 合成 → 对抗式审校 → 修订定稿 → 维护者本地复核(9 agent / ~635K tokens)。所有量化事实经 `python3`/`grep`/`find` 实测核对。*
