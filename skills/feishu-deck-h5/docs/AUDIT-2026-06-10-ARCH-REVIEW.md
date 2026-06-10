# AUDIT-2026-06-10 · 架构 / 代码 / 功能全面审查

> 审查对象:`skills/feishu-deck-h5`(HEAD `ed25176`,main)。
> 审查方式:10 维度并行深审(控制器/设计阶段/raw-first/validator/Python 核心/运行时/跨模型/编辑 round-trip/历史存量/真实 runs 实证)→ 每条 P0/P1 发现独立对抗性核查(打开证据文件复核引文、对 git log 与 docs/archive 查重)→ 完整性批判。共 63 个 agent,全部发现均带 file:line 级证据,夸大与误读已在核查环节剔除或降级。
> 驱动痛点:① 出品不稳定 ② 设计感/页间一致性差 ③ 同事用 Codex 等其他模型跑效果差。
>
> **编号基线**:历史文档最大工单号 = F-254(AUDIT-2026-06-01-skill-review.md)。本报告从 **F-255** 起。注意 F-NN 已三度撞号(F-36~46、F-80~85 在不同文档各有两义),见 F-291 建议的 TICKETS.md 登记处。

---

## 决策更新 · 2026-06-10(用户拍板,落地中)

技能定位锁定:**skill = 合规引擎,设计自由度留给模型**(memory `feedback_skill_compliance_engine_not_design_system`)。据此对下方工单重新取舍——投资"合规 floor",放弃"设计 ceiling 锚定":

- **做(模型无关的合规保证)**:F-255/256 闸门不变量化、F-257 跨页一致性规则 + 可选 `deck_meta.style_contract`(已加 schema)、F-260 白名单单源化 + raw 正名 first-class(已改 schema/policy/designer/renderer)、R-BAKED-DOM FAMILIES 漏档(已修,本是 main 上 b3f7fd5 引入的 pre-existing red)。
- **不做(设计锚定 / 模板,留给模型)**:~~F-258 `deck-cli scaffold` + 能力分级自动 schema-first~~(会把 deck 拉回 schema,与"纯 raw-first"冲突)· ~~F-263 showcase 接线 / raw 范例库~~(showcase 实测 28 页全 schema-layout、0 raw、仅 1 svg,当 raw 锚点会 flatten richness)· ~~F-276 card primitive / roadmap-helper 模板化~~(同属设计模板)。
- **raw-first 永远是默认**;schema 回退仅限单源 allowlist 命中。跨模型(Codex)= 合规但可能偏平,富度是模型的事(用户接受此 tradeoff)。F-260 只做"单源化 + schema 描述/计数修正",**不做**原稿里"把 raw 收窄到 4 种页型"那条(与 raw-first 冲突)。

---

## 0. TL;DR

三大痛点不是「模型不行」,而是三条机制性根因链,每条都有代码级证据:

1. **不稳定 ←「门禁强度是环境/路径/flag 的函数」**。视觉/几何质量闸的实际生效条件 = `输出路径含 /runs/ 子串 AND 没用 --scope/--quick AND playwright+chromium 装好 AND advisory 子进程 JSON 可解析`。任何一条不满足,硬闸静默消失、render 照样 PASS。同一 deck 在你机器上拦、在别处放行。
2. **一致性差 ←「跨页一致性在三层都没有承载物」**。全部 62 条 validator 规则都是单页局部判定,零跨页比较;DESIGN-PLAN 没有 deck 级视觉常量小节;deck_meta 只有 2 个样式字段。实证:huatai 单 deck 96 个 hex/53 对近邻色、northregion 161 个 `allow:typescale` 洗绿 26 种阶外字号、字阶 token 采用率 0%~86% 全凭当次发挥。每页各自全绿,整 deck 仍像拼贴。
3. **Codex 跑不好 ←「质量押在最吃模型能力的环节,而兜底闸恰好在弱环境全关」**。raw-first 要求每页现写自由 HTML/CSS,确定性 schema 路径被锁在「用户念咒『安全模式』」后面;Codex 机器大概率没装 playwright → 唯一能兜住烂排版的 ~50 条浏览器域规则一条不跑,还报绿。**质量不是模型差,是闸门没开 + 模式没降级。**

最高杠杆三件事(可并行、互不依赖,覆盖本轮 P0/P1 约七成):见 §2。

实证还给出一个重要修正:**方差的主轴不是「模型当天发挥」,而是生成路径**——fresh 生成(shuyi/nut-assoc)相当干净,lift/clone+增量补丁路径(huatai/zhongan)持续累积冲突且相关审计全是软警告。「越改越坏」是机制,不是手感。

---

## 1. 痛点 → 根因映射(合并去重后)

### 1.1 出品不稳定

| 根因 | 证据锚点 | 工单 |
|---|---|---|
| playwright 缺失 → 整个 DOM 引擎降级为一条 warn_soft、exit 0,硬几何阻断闸(17f2dde)随之静默失效;check-mira.sh 全 repo 零接线;preflight 不探测能力 | validate.py:164-185 / render-deck.py:2286 / check-mira.sh:183 | F-255 |
| `--scope/--quick` 整体跳过 6b 硬几何闸+6c 分布闸,被改页带着 overlap/clip 绿灯通过——而编辑场景默认就是 --scope | render-deck.py:2293-2294, 2361-2363 | F-255 |
| 47/62 条 DOM 规则(含 26 条 **error 级**)默认只是 advisory 打印不阻断,「门禁绿≠做好」结构性内建 | render-deck.py:2306, 2325(_HARD_GEOM 仅 4 码) | F-256 |
| `/runs/` 裸子串路径 gate + `except Exception: pass` 吞掉 advisory 子进程崩溃(copy-assets 同款 bug 已修过,这两处没跟) | render-deck.py:2293, 2344-2345 | F-255 |
| 设计阶段 prose-mandatory 零机器闸:适用 run 实测 ~45-50% 跳过 DESIGN-PLAN 落盘(mandate 后仍如此);render 不检查任何设计工件 | grep render-deck.py "DESIGN-PLAN|outline" = 0 命中 | F-262 |
| render 失败不回滚:index.html 先写盘后过闸,exit 4 时上一版好产物已被坏版本覆盖;全链路无原子写(known F-146 未修) | render-deck.py:2228 vs 2261;无 os.replace | F-269 |
| 多 agent 单写者纪律纯 prose:F-48 乐观锁只护 CLI 写路径,文档首推的 Option A 直编 deck.json 无锁 | deck-generation-policy.md:43-46 | F-279 |

### 1.2 设计感 / 一致性差

| 根因 | 证据锚点 | 工单 |
|---|---|---|
| **零跨页一致性规则**:62 条规则全为单页判定(仅 R-CSSVAR/R10/R-KEY 等 7 条整 deck 求值但不做页间比较) | audits.js:5880-5896 driver | F-257 |
| **无 deck 级 style contract 承载物**:DESIGN-PLAN mandatory 清单无视觉常量节;deck_meta 仅 title_style/logo_position | design-phase.md:123-134 / deck-schema.json:63-72 | F-257 |
| `allow:typescale` 整 rule 一票豁免、无值域、无 deck 级预算,R20 报错文案自带绕过教程;northregion 161 个豁免洗绿 14/17/18/22px 正文(warn 无牙,validate 退出码只看 error) | audits.js:2143, 2165, 5174 | F-257 |
| 调色板漂移零覆盖:R10 扫描前剥掉 `<style>` 块(huatai 96 hex 中 87 个在盲区)且仅 warn | audits.js:1631-1634, 1578 | F-257 |
| token 采用率无任何机制拉回:字阶 token 0%~86%、radius token 5 deck 中 4 个 0 引用、裸 radius 单 deck 23 种值 | 实测 5 run | F-257 |
| Q4 授权脱离品牌色板但框架无任何替代色板 token——每个暖调 deck 现挑 hex,与 R10 持续摩擦 | design-first.md:214-222 / feishu-deck.css:15-21 | F-280 |
| golden 范例库(showcase.html+28 截图)建好了但全部 SKILL.md/subskills **零引用**,设计时没有视觉锚点(known: REPRODUCIBILITY-GAP 方案2,至今未落地) | grep "showcase" 仅 postmortem 命中 | F-263 |
| raw-first 两份互相矛盾的回退白名单(policy 8 行 vs design-first 18 行),renderer 只引前者;读到哪份决定同一页型走 raw 还是 schema | deck-generation-policy.md:86-101 / design-first.md:394-424 | F-260 |
| lift/clone 路径补丁堆叠:huatai 12/21 个 key 携带互相矛盾的 .header 规则栈,标题位差 35px 靠级联顺序裸定;跨页 selector 泄漏(known 家族 F-56/F-50/F-60,均未落地) | runs 实证 + data.html 内嵌 127KB×6 style | F-281 |
| layout-recipes 6 个「canonical copy-paste markup」自带 eyebrow+内层 wrapper,违反自家 Content Header Rule/R56——照抄即产出死标记 | layout-recipes.md:149-359 vs policy:152-163 | F-264 |

### 1.3 跨模型(Codex)效果差

| 根因 | 证据锚点 | 工单 |
|---|---|---|
| schema-first「安全模式」被文档自己定位为「非资深 harness 的正确默认」,却只能靠用户念咒触发;无任何能力自检步骤 → Codex 默认拿到最难模式(每页现写 bespoke CSS) | design-phase.md:27-28 / policy:103-104 | F-258 |
| 最小可用路径(outline→schema 骨架→填空→render,零自由 HTML)机械上存在(28 个 layout 模板+纯 stdlib 渲染)但没有 scaffold 命令、没有文档入口 | deck-json/templates/ | F-258 |
| playwright 弱环境兜底全关(见 1.1)→ 模型最弱的环节恰好没有闸 | 同 F-255 | F-255 |
| Hard Gate 1「必走 render-deck.py」唯一硬闸是你个人机器的 CC hook(repo 内零强制、无 provenance 章);Codex 无 PostToolUse 机制 | validate.py:88 注释 / hook 不在 repo | F-266 |
| 一次生成必读 prose 实测 ~117KB≈30K token(连常用 refs ~230KB≈60K);最硬的 mandatory 规则(底色/Q0-Q4)是英文文档里的中文段;References 列表 23 个裸文件名无「何时读」 | wc -c 实测 / renderer SKILL.md:44-53 | F-265 |
| 两套互不映射的 Mode 词表都自称 mandatory(SKILL.md 12 小写 vs request-router 7 大写),且对「substantive edit 走不走 design gate」「pptx 过不过 Designer」给出相反答案 | SKILL.md:31 vs request-router.md:8,168 | F-261 |
| designer 必经步骤硬依赖 lark-base skill+lark-cli 登录态,缺失时无降级条款(parser 有 Codex 条款,designer/renderer 没有)→ 静默走样、logo 缺失 | designer/SKILL.md:37-38 | F-268 |
| 文档腐烂误导字面化模型:validator-rules.md 同文件两套矛盾字号规范(4-tier vs 旧 17 档,把 24/48 列为 ERROR 示例)、editing-discipline E4 同病、3 处指向已删除的 _validate_audits.py、macOS 专属命令残留 | validator-rules.md:28 vs 98-108 | F-264 |
| 字体可移植性:首选「方正兰亭黑 Pro GB18030」是本机授权字体,零 @font-face/零子集化——几何审计量的是「当前机器字体」的 metrics,跨机器 verdict 本身漂移;受众端回落雅黑后 density/留白走样 | feishu-deck.css:45-53 | F-283 |

---

## 2. 最高杠杆三件事

三条正交主线,合计覆盖本轮 P0/P1 发现约七成。**这是唯一不需要「模型变聪明」就能砍掉大部分方差的路径。**

### ② 之前先记住一条总原则:prose → code 固化
本轮反复出现的模式:凡是靠嘱咐的环节(4 条 Hard Gates 里 3 条纯 prose、Q0-Q4 chat 输出、单写者纪律、「翻译后复审布局」、「logo 缺了问用户」)在弱模型/新 session 上全部静默失效;凡是代码强制的环节(schema validate、F-48 锁、R-BAKED-DOM)都真的拦住了事故。每条 MUST 的归宿应该是一个规则 ID 或一个 CLI 检查。

### 主线 A · 把质量闸做成「环境/路径/flag 不变量」(F-255/256)→ 主打不稳定+跨模型
- playwright 缺失:对 runs/ 交付路径从 warn_soft 改为显式红牌(exit≠0 + 安装命令,`DECK_ALLOW_NO_VISUAL=1` 逃生);/tmp 测试路径保留软降级。UNIFY-VALIDATE-ARCH §4 自己写过「缺了须硬提示、不可静默放行」,run-audits.py 守了,validate.py/render 闸没守——把承诺兑现即可。
- `--scope/--quick`:不再整段跳过 6b,对被改页跑 scoped 视觉审计(audits.js 本就支持 `__AUDIT_SCOPE__`,单页 ~1-2s),套用同一 _HARD_GEOM 阻断。
- render 结束固定打印一行闸门覆盖摘要 `gates: static=ran, geometry=ran|SKIPPED(why), distribution=...`——让「没跑」和「跑了没问题」永远可区分。
- 已免费跑出的 error 级 R-VIS advisory 提升为阻断(F-253 当年否的是「全局 --visual 默认 ON」,不是这个;需配存量 deck 豁免迁移)。
- check-mira.sh 接进 SKILL.md Preflight;preflight.sh 首行打印 `CAPABILITY visual-audit: ON/OFF`。

### 主线 B · deck 级 style contract 落盘 + 机器执行(F-257)→ 主打一致性
一个小契约,三层各补一格:
1. **DESIGN-PLAN.md 增加第 4 节「Deck Style Contract」**(accent 章节分配、卡片面规格 radius/border/bg、KPI 数字处理、图标 stroke、动效语言),renderer/editor 写每页前必读;
2. **deck_meta 加 style_contract 字段**使其随 deck round-trip;
3. **audits.js 加 deck 级一致性规则族**(driver 已遍历全部 slides,R10/R-KEY 已有同款两遍扫描架构):
   - R-DECK-TITLE-DRIFT:标题 top/字号偏离众数报离群页;
   - R-CSS-GEOM-CONFLICT:同 (key, selector) 组内几何取值不一致 → err;同 key `<style>` 含其他 slide-key 的 selector → err(跨页泄漏);
   - R10b:CSS 通道(iterStyleBlocks)色板审计 + 近邻聚类(Δchannel≤8 判同簇),deck 级 >5 簇 warn / >15 err;
   - allow:typescale 加值域白名单(仅 ≥56 hero 或 ≤13 mock 生效)+ deck 级预算 error 档;改掉 2165 行「加注释即可 override」的教程式文案;
   - radius/token 采用率 advisory(报错文案给 px→token 映射,让修复动作指向 token)。

### 主线 C · 能力分级生成模式 + 黄金锚点(F-258/263/260)→ 主打跨模型+设计感
- **能力自检 → 自动 stance**:SKILL.md:92-101 的 multi-agent 探测协议已是先例,同款做 stance 判定——无 playwright/check-mira 报 degraded/非 Claude harness → DESIGN-PLAN 自动写 `stance: schema-first`,终结「安全模式靠念咒」。
- **`deck-cli scaffold --from outline.json`**:按 layout_intent 机械展开 schema 骨架,弱模型只做 `deck-cli set` 填文案——打通「全 CLI、零自由 HTML」的最小可用路径,并在 SKILL.md 明文写出这条路径。
- **showcase 接进 designer 必读**(REPRODUCIBILITY-GAP 方案 2 的既定未落地路线):每张 raw 页在 DESIGN-PLAN spec 里写一行「锚定:showcase sNN」;按方案 9/10 占位化 4-6 张高频 hero 入 templates/blocks/。
- **白名单单源化**:以 design-first 18 行表为唯一来源,policy 8 行表改指针;把 81-84 的「有 alignment/hierarchy 就留 raw」(全称词,形同虚设)改写为与 Q0 页面角色挂钩的封闭决策表;同步修 deck-schema.json:1146 把 raw 从「ESCAPE HATCH」改为 first-class(及 :5/:351 的 layout 计数,实为 14+3)。

---

## 3. 工单清单

### P0

- **[F-255] 质量闸环境/路径/flag 不变量化**(主线 A 全部;合并 5 个维度各自报的 playwright 静默降级 + scope/quick 绕闸 + /runs/ 子串 gate + except:pass + check-mira 零接线)。
- **[F-256] error 级 R-VIS advisory → 阻断**(render 已免费跑完 --visual;重审 F-253 范围;配存量豁免)。
- **[F-257] deck 级 style contract + 跨页一致性规则族**(主线 B 全部)。
- **[F-258] 能力分级 stance + scaffold 最小路径**(主线 C 前两条)。
- **[F-259] 编辑链「越改越坏」三件套协同修**:
  - edit-mode `buildSavedHTML()` 只剥 edit 痕迹不剥运行时痕迹,⌘S 保存件必中 R-BAKED-DOM 三指纹(data-idx/.deck-ui/data-js-ready),而文档钦定的恢复路径 sync-index-to-deck 会把 `--child-i`/autobalance 内联样式/canvascenter top|bottom !important 当编辑回灌进 deck.json 真源(一次性源污染,非无界累积;surgical flags 可走无污染路径但正文编辑必污染);
  - 修法:① buildSavedHTML 补剥运行时痕迹(deck-edit-mode.js:328-359);② 运行时突变改写进可整体 remove 的 `<style data-fs-runtime>` 或挂 `slide.__fsTouched` 供保存前回退;③ sync 入口复用 R-BAKED-DOM 指纹检测,命中默认拒绝 + `--sanitize` 自动剥;④ pytest:渲染→headless 跑 JS→save→R-BAKED-DOM 0 命中。

### P1

- **[F-260] raw/schema 白名单单源化 + 判据收紧 + schema 描述对齐**(主线 C;含 deck-schema.json:1146「ESCAPE HATCH」与 :5/:351 计数修正→14+3)。
- **[F-261] Mode 词表收敛为 request-router 7-mode 单一枚举** + mode→subskill 映射表;给「substantive deck edits」一个可判定分界(改既有 run 内 deck=EDIT 系,产新 run 工件=GENERATION);统一「pptx 导入是否过 Designer」口径(纯导入免,导入后再创作必须过)。
- **[F-262] design gate 代码化**:new-run.sh 生成 outline.json/DESIGN-PLAN.md stub;新建 schema/outline.schema.json + outline-lint(校验 raw 页 design_spec 六维齐全 + density_budget);render-deck 对 runs/ 首渲检查设计工件(warn → --strict err,`--allow-no-design` 逃生;canvas/pptx-import/lift/re-render 豁免);同步修 simulate-pitch.py 读不存在字段的问题(thesis/claim_discipline/brief 均不在契约里,urgency 恒 50,design→simulate 反馈回路实际是断的)。
- **[F-263] showcase + hero 片段库落地**(REPRODUCIBILITY-GAP 方案 2/9/10;ceiling 主线至今零落地,而 raw-first 已成默认,缺口被放大)。
- **[F-264] 文档腐烂清理批**(对字面化模型杀伤最大):
  - validator-rules.md:72-165 整段陈旧 self-check(R06≥14px+17 档旧阶梯,把现行唯一合法值 24/48 列为 ERROR 示例)重写为 4-tier,真源标注 feishu-deck.css --fs-* tokens;editing-discipline.md:247-253(E4)同步;
  - 3 处 `_validate_audits.py` 死指针(validator/SKILL.md:91-92、check-only.md:47,70 等)改为 audits.js+run-audits.py;
  - layout-recipes 6 个 recipe 的 header 块改为合规 title-only 形态(同文件 :96 agenda 已是);
  - policy:182-198 与 renderer SKILL.md:88-92 的「raw 守卫缺口」表更新(R-VIS-RAW-TITLE-STACK 已堵上);
  - **防回潮**:tests/ 加 doc-link 检查(扫仓内相对路径引用,不存在即 fail)+ 字号阶梯 doc-sync 断言(模式抄 test_check_only_gate.py 的 F-03 测试)。
- **[F-265] 阅读集治理**:SKILL.md References 23 个文件名每行加「何时读」(各文件第 2 行现成);为新 deck 生成/单页编辑/check-only 三个高频任务定义 ≤5 文件的最小阅读集 manifest;deck-schema.json(67KB)拆 per-layout 摘要;layout-recipes(43KB)按 layout 切片;万字单行(validator-rules.md:47)拆表格;关键 mandatory 中文段补英文镜像句。
- **[F-266] Gate 1 工具链强制**:render-deck 在 index.html 盖 provenance 章(`fs-deck-generator` meta + sha256(deck.json) 前 12 位);新增 R-PROVENANCE(runs/ 下无章或 hash 不符 → err,接 finalize/check-only --gate ingest;需兼容 inline-assets/explode-assets/sync 等合法 post-render 改写);validate-deck-write.py hook 收进 repo(assets/hooks/)+INSTALL.md 安装说明,注明非 CC 环境靠 R-PROVENANCE 兜底。
- **[F-267] lifted 修复管线接线**:heal-lifted/clean-lifted-css/reconcile-lifted 三件套零文档路由(grep SKILL.md+subskills+references 零命中),F-62 还在教「手工对齐字号」而确定性 snap 工具就在旁边。加 repair-lifted.py 薄编排器(backfill→migrate-head-css→heal→clean→reconcile→render+validate,dry-run-first),editor SKILL.md 只路由这一条命令。
- **[F-268] 云依赖降级协议**:designer 第 3 步加「lark-cli 不存在/未登录 → local-only 模式」条款(DESIGN-PLAN 记 cloud_assets: unavailable,资产只用 assets/shared/,缺 logo 列清单问用户,严禁手绘/emoji 兜底)。
- **[F-269] 原子写 + render 失败回滚**(known F-146 重提):共享 `atomic_write_text`(tmp+os.replace)替换全链路裸 write_text;render 闸 return 4 前恢复 .bak-pre-render 的上一版 index.html 并说明「已回滚」。
- **[F-270] --inline 完整化**:`<img src>`/`<video src|poster>`/无引号 url() 不内联、缺失文件零警告(本机预览正常、发出去 404)。补 pass + 「未内联 N 个本地引用」清单 + --inline-strict;与 inline-assets.py(publisher 线,同样静默)收敛为单一实现。
- **[F-271] 运行时/验证器假设统一**:
  - canvas-center 测量提成共享实现(absolute 内容带:运行时算/validator 跳过;阈值 12 vs 40——(12,40] 区间校验放行但放映时被静默平移);
  - 落地 audits.js:938 自注册的 raw twin TODO(PR2)——R-VIS-CANVAS-CENTER 至今 schema-only,而 raw 页正是 R-11 57px 偏移的原产地;
  - 删 feishu-deck.css:738 的 content-3up 96/96 死规则(被 :1497-1513 统一规则级联压住,但仍是文档/模型的误导源);修 R-VIS-TITLE-POSITION 的 `.header > .title-zh` 选择器盲区(nut-assoc 用 .r-title → titleEl null 静默放行,9 页标题 top 三个值);
  - .slide 加 `font-size: var(--fs-body); line-height:1.5;`(漏写字号的默认结果从 16px 变 24px;R-VIS-BODY-FLOOR 能抓 ≥8 字的,<8 字短文本和 advisory 不阻断路径仍漏);
  - 修正 feishu-deck.js:26-40/574-579 与实测相反的注释(present 模式 inset:0 叠放,init 即全量平衡,enter 是重试通道非主通道)。
- **[F-272] 页 CSS 落位收敛**:三套约定(custom_css / head style / raw data.html 内嵌)→ render 时把 data.html 顶层 `<style>` 自动抽进 custom_css(复用 migrate 的 _css_utils 逻辑);落 L7b 把 R-SELF-CONTAINED 升 err;内嵌字节预算(>8KB/页 warn,>32KB err)+ 跨 key selector → err。
- **[F-273] sync-index-to-deck 方向守卫 + 覆盖面黑洞**:deck.json 比 index.html 新时硬警告+默认 dry-run(防「改了又没改」静默回滚);默认全量 sync 内置 hidden/notes reconcile;custom_css 块与字段比对(F-235 重叠);template 页 drift 升显眼 WARNING(--force 转 raw 是 lossy)。
- **[F-274] F-36/F-37 产品层双 P0 正式裁决**:deck→PPTX 桥与托管创作面自 2026-05-29 零进展且降级未登记——「同事跑不出效果」有一部分是入口问题不是模型问题。二选一并登记:标 DEFERRED-BY-PIVOT+恢复条件,或启动 R-01 Phase1(每页 PNG 拍平 .pptx,python-pptx 已 vendored)。

### P2(摘要,按主题归批)

- **[F-275] 多写者结构化**:worker 只产 slide 片段文件,控制器单写者经 deck-cli apply-patch 合并(F-48 锁复用);Option A 文档加多 session 禁直编红线。(原 1.1 表中 F-279 并入此条)
- **[F-276] 设计 token 补全**:间距阶梯(--fs-gap-s/m/l/breath)、卡片 primitive(.cards-3/.card)、5 个无 CSS 的 roadmap helper 落成框架类、raw 页容量 Z 推导规则。
- **[F-277] 替代色板 token**:[data-palette="warm-paper"] 等 2-3 套具名色板覆写 --fs-accent/--fs-bg-*,Q4 表指向枚举名,R10 白名单收编。(对应 1.2 表 F-280)
- **[F-278] 动效契约落盘**:bespoke 动效定稿后写「动效契约」进 DESIGN-PLAN;稳定效果(B 章节仪式/.reveal 错落)升 slide.motion schema token。
- **[F-279] deck-log 闭环接线**:`deck-log diff` 子命令(相邻 snapshot 同 key 截图像素 diff+变化页清单),heal/reconcile/sync 后自动跑;盘存量 making-of 统计「同页渲染≥4 轮」的高返工页型作为真实不稳定热力图。
- **[F-280] 错误信息统一**:validate-deck 报错带 key+1-based 序号;render_slide 异常带页码/key 上下文;R20 等报错文案从「教绕过」改为「指向合法例外清单」。
- **[F-281] lift 线存量护栏**(known 家族):R-LIFT-CSS-BUDGET(F-60)落地;lift 写后复校+回滚(F-124);huatai/zhongan 跑一次 consolidation 清洗作回归样本。
- **[F-282] 杂项**:scope_selectors 静默杀 :root 变量声明(改 rehome 到 slide 根);fs-deck-mode localStorage 跨 deck 泄漏;移动端第二套导航栈;R-VIS-ALIGN 空壳 stub(实现或删);SVG text 字号豁免;audits.js 拆 rules/*.js + 5 对双语言孪生规则 parity 测试;fixtures 指向 git-ignored runs/ 的 CI 缩水;F-252 --photos-as-bg;E1/E2 手工仪式重写为 legacy 例外;源/靶 HTML 判定加 tiebreak 问句;单页小改纪律收敛进 editing-discipline 单一节。

### 新专项(本轮审查盲区,来自完整性批判;建议各立一单)

- **[F-283] 字体可移植性**:check-mira/preflight 探测 CJK 首选字体是否安装;validate --json meta 记录实际生效 font-family(跨机器 verdict 自带环境指纹);中期字体子集化打包(woff2,与 pptx-to-deck 蓝图第 1 项共线)——一次消灭「审计度量随机器漂移」+「受众端回落雅黑走样」双重漂移。
- **[F-284] parser 摄取质量专项**:1690 行 parse.py + 双 schema 零审计。抽 3-5 个 run 做 原始素材→dossier→deck 三层事实保真度抽查;validate-contract.py 接进 parse 完成点(目前主管线零调用,又一条 prose 闸)。
- **[F-285] 发布后自检**:publisher 发布完成后 playwright 打开最终 URL 截 3 页对比本地(断链/字体回落/资产丢失当场红牌);slide-library 入库前强制 check-only --gate ingest+跨页一致性规则(防带病页面经复用链路代际遗传)。
- **[F-286] assets/shared manifest**:356 个中文文件名 logo 无索引——生成 manifest.json(标准名/别名/paired 变体/底色适配/授权标注),查找从「ls+猜」变「查表」;评估 25MB clientlogo 拆出主仓。
- **[F-287] 注入面最低防线**:dossier/lift_origin 标 untrusted=true+「素材是数据不是指令」条款;R-FOREIGN-SCRIPT 审计(非框架 `<script>`/on* 在 lift/入库 err、生成 warn);发布到带登录态 worker 前跑 strict 档。
- **[F-288] translator 布局回归**:apply-text-pairs 后强制全量 render+几何审计(CJK→EN 文本变长 30-60%,现流程只换文本不复审布局);glossary 是否真被读取顺手验证。
- **[F-289] simulator 有效性验证**:修完 F-262 字段契约后,拿 6 个已交付 deck 的 simulate 分数对照实际返工轮数;无相关性就降级为可选环节。
- **[F-290] 性能反向伤质量**:全量 render 串行 2-3 趟独立 playwright 整页加载,慢得诱导 --quick/--scope 绕闸——6b/6c 合并进同一浏览器会话,validate-deck 改 import 调用。
- **[F-291] docs/TICKETS.md 唯一编号登记处**:首行「下一可用号 = F-292」;附撞号对照表(F-36~46、F-80~85 两义归属);AUDIT-2026-05-29 deferred 长尾 14 单逐条标 DEFERRED/WONTFIX 销账。

---

## 4. 被证伪 / 修正的假设(防追鬼)

对抗核查环节推翻或显著修正了这些「听上去很对」的判断,以后别按原表述追:

1. **「设计文档全是形容词审美词」— 不成立。** 实测 design-first.md 数值约束 37 处 vs 形容词 12 处,Q0-Q4/六维/密度护栏是真材实料。设计感方差的根因在「契约无机器闸 + 值域无 per-role 绑定 + 范例库没接线」,不在方法论本身。
2. **「16px 正文 validator 全盲」— 不成立。** R-VIS-BODY-FLOOR(error 级)能抓 ≥8 字 <24px 正文。真实漏洞链是:floor 规则存在 → 默认路径只 advisory 不阻断 → allow:typescale 洗绿 → warn 不计退出码。修的是链不是规则。
3. **「balanceSlide 两通道皆废(R-11)」— 已过时。** 现已重写为 alignSelf/padding 预算/min-height + measure-or-revert,headless 实测 init 通道对全部 slide 真实生效;「on-enter 重试被 opacity:0 致盲」也被实测推翻(opacity 不继承,深层文字元素可测)。残留只是注释与实测相反 + 少量 0 高度元素探针缺口。
4. **「73/61 vs 96/96 同 deck 混排」— 部分推翻。** css:1497-1513 统一 header 规则级联压住了 :738 的 96/96(死规则),实测 huatai/zhongan 全部标题渲染在 61/73。真问题=死规则误导 + R-VIS-TITLE-POSITION 只认 `.title-zh` 的选择器盲区。huatai 的「互相矛盾规则栈」本身仍成立(那是 lift 补丁堆叠问题,F-281)。
5. **「northregion deck.json 不自含、重渲即全损」— 误读。** 63 个 style 全部 co-located 在 slide 内、scope 到本页 key、源于 data.html——deck.json 完全自含。三套 CSS 落位约定并存(F-272)仍成立,但该 deck 不是事故温床。
6. **「295KB 必读指令」— 定性修正。** 那是 worst-case 指针闭包,References 标题明确是 load-as-needed;但「无何时读标注 + 模型抽样阅读 → 每次读到的子集不同」这条机制成立(F-265)。
7. **「playwright 缺失完全静默」— 措辞修正。** 会打 warn_soft+安装提示到 stderr,但 exit 0、verdict PASS、硬几何阻断闸随之失效;--scope/--quick//tmp 路径才是真静默。修法不变(F-255)。
8. **「设计阶段 70% 跳过率」— 修正为 ~45-50%。** 16/23 缺 plan 的 run 里有 mandate 之前的、测试的、translator 管线的(不适用设计阶段);05-27 后合规趋势在改善。问题仍成立但量级要用修正值。

另外两点验证为「真的做对了」,值得保持:unify-validate 迁移真正完成(单一规则源+RULE_META 契约+CI 测试是高水准设计);Python 写事务(deck-cli F-48 锁+备份+写后复校回滚)与渲染确定性(无时间戳/排序稳定)质量都很高。

---

## 5. 各维度一句话结论

| 维度 | 结论 |
|---|---|
| controller | 职责切分与三锁设计是对的;但 4 条 Hard Gates 仅 1 条有部分代码强制,两套 Mode 词表并存,指令负担迫使抽样阅读 |
| design-phase | 方法论真材实料;败在 prose-mandatory 零机器闸(~45-50% 跳过)+ 值域无 per-role 绑定 + showcase 零接线 |
| renderer/raw-first | 文档化深度罕见地好;但 raw-first 的三件配套(单一白名单/style contract/schema 描述对齐)全部缺位,75% 页面(324/432 实测)押在现写 HTML 上 |
| validator | 工程基础显著好于一般技能(单一规则源+契约+CI);但默认门禁只跑字节规则、零跨页规则、raw 覆盖弱一档 |
| python-core | 整体质量高、渲染确定性好;主要问题是闸门可用性随环境漂移 + 写盘纪律不一致(非原子/不回滚) |
| runtime | R-11 已实质修复、57px 偏移已修;残留是与 validator 的三处假设漂移 + CSS 无默认字号防线 |
| cross-model | 根因三层叠加:raw-first 押模型能力 + 弱环境闸全关 + 重判断协议纯 prose;解法=prose→code 固化+能力分级 |
| editor/round-trip | 教义层全技能最好;但 edit-mode 保存件↔R-BAKED-DOM↔sync 三组件互相矛盾,「越改越坏」在这条链上是机制性必然 |
| known-issues | 历史修复率 85-90% 相当扎实;最大的未落地欠账=REPRODUCIBILITY ceiling(showcase/hero 库)与 playwright 静默放行 |
| empirical | 不一致主要在【同 deck 页与页之间】;方差主轴是生成路径(fresh 干净 / lift+增量补丁持续劣化),不是当天发挥 |

---

*报告由 10 维度并行审查 + 逐条对抗核查生成(2026-06-10)。工单按「做 F-NN」惯例可直接执行;动手前建议先建 F-291 的 TICKETS.md 领号,避免第四次撞号。*
