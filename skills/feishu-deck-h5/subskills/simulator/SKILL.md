---
name: feishu-deck-h5-simulator
description: |
  Rehearse how an approved or delivered H5 deck may land with customers,
  investors, leaders, buying committees, or internal stakeholders. Trigger on
  "模拟讲这套片子", "客户会怎么反应", "pitch rehearsal", or "帮我预演". Produces
  scenario forecasts, objections, talk-track notes, and revision queues, not real research.
---

# feishu-deck-h5-simulator

目标:把已经生成或已规划的 pitch deck 放进一个**客户会议预演**里,模拟
不同听众角色逐页听到什么、哪里被打动、哪里会质疑,最后反推出 deck 和讲法
应该怎么改。

这不是“神谕式预测”。输出必须明确是基于当前 deck、受众画像和会议目标的
**scenario forecast / rehearsal result**,用于提高提案质量,不能伪装成真实用户
调研或真实成交概率。

Inline freshness rule: when this subskill is not running as a separate
multi-agent worker, reread the current upstream files before simulating. Do not
rely on cached chat summaries or earlier reads of `audit-report.json`,
`outline.json`, `deck.json`, `index.html`, or the user's latest meeting context.

## 触发时机

feishu-deck-h5 标准链路里,`pitch-simulator` 放在 `deck-validator` 之后、`publisher`
之前,但它是 **validator 后本地 HTML 交付完成之后的异步环节**。不要在
`deck-designer` 刚产出 outline 后先跑 simulator;designer 应该先基于知识库和用户 brief 生成 outline,再由 renderer / validator 形成可看的 deck。

在以下链路后使用:

```text
brief
  -> deck-designer
  -> user confirms outline
  -> deck-renderer
  -> deck-validator
  -> local HTML delivery
  -> async pitch-simulator
  -> user decides revise vs confirm publishable
  -> publish-magic-page if needed
  -> user confirms ingestion
  -> publisher
```

典型用户请求:

- "用这份片子去给客户讲,模拟一下会发生什么"
- "帮我看这套 pitch deck 对 COO / CFO / IT 各自有什么阻力"
- "生成完 HTML deck 后,给我一份客户反应预演"
- "这套 deck 拿去融资 pitch,投资人最可能问什么"

## 输入

优先读取这些 artifact,越靠前越可信:

1. `deck.json` — 稳定 slide key、title、layout 和结构化内容。
2. `scenario.json` / `Scenario.json` 或 `outline.json.scenario` — designer 落盘的
   pitch goal、audience、decision context、setting、language、risk level、proof requirements。
3. `outline.json` — 受众、目标、业务场景、痛点、证据缺口、页级设计意图。
4. `index.html` — 当没有 deck.json 时,提取 `.slide` 的 `data-slide-key`、
   `data-layout`、标题和正文。
5. 用户补充的会议背景 — 客户名称、行业、参会人、会议目标、已知阻力。

如果只有 HTML 或只有 outline,仍然可以模拟,但要在输出的
`source.assumptions` 里说明限制。

在 feishu-deck-h5 标准链路中,不要新增 `rehearsal-request.json`。预演直接消费
designer 已落盘的 Scenario、`outline.json`、`deck.json`、可选 `index.html`,并以 `audit-report.json`
的 `verdict` 作为进入门禁。不要直接消费 validator 的 markdown 摘要。

## Subagent I/O Contract

作为独立异步 subagent 执行时,输入只包含 `context_packet`、`audit-report.json`、
`scenario.json` 或带 `scenario` 字段的 `outline.json`、`deck.json` 和可选 `index.html`。输出必须是
`pitch-rehearsal.json` 和 `PITCH_REHEARSAL.md`;它们补交给用户和总控,不阻塞 validator
后的本地 HTML 交付。simulator 不能直接发布、改稿或入库。

## 输出

默认产出两份文件:

```text
pitch-rehearsal.json   # 结构化结果,符合 schema/pitch-rehearsal.schema.json
PITCH_REHEARSAL.md     # 给 GTM / 讲述者看的可读报告
```

这两份文件必须返回给用户或在状态页可见;不能只作为内部日志。预演完成后不自动发布、不自动入库;必须让用户选择是否按反馈修改:选择修改则回到 `deck-designer` 生成新 outline 并重新生成本地 HTML;选择不用修改后,再进入最终发布物确认。

落文件后用 stdlib 校验器检查:

```bash
python3 skills/feishu-deck-h5/subskills/simulator/validate-rehearsal.py \
  path/to/pitch-rehearsal.json
```

如果已经有 outline,可以先用内置 heuristic 生成第一版预演骨架:

```bash
python3 skills/feishu-deck-h5/subskills/simulator/simulate-pitch.py \
  --scenario path/to/scenario.json \
  --outline path/to/outline.json \
  --deck-json path/to/deck.json \
  --out-json path/to/pitch-rehearsal.json \
  --out-md path/to/PITCH_REHEARSAL.md
```

如果不显式传 `--scenario`,脚本会自动读取 `outline.json` 同目录下的
`scenario.json` / `Scenario.json`;仍没有时再回退到 `outline.json` 顶层
`scenario` 字段。

之后由 agent 补充更细的角色心理、追问和讲稿建议。

## 工作流

1. **识别会议目标**
   - 这场 pitch 要让对方做什么决定?
   - 是首访、方案介绍、POC 启动、续约、融资、内部 alignment,还是复盘?
   - 成功不是“听懂”,而是“推进到哪个下一步”。

2. **建立 audience panel**
   - 默认 4-6 个角色,不要只模拟一个“客户”。
   - 至少包含:决策者、内部推动者、实际使用者、技术/实施评估者、财务/采购或反对者。
   - 每个角色要有 `agenda`、`success_criteria`、`likely_objections`。

3. **拆 deck arc**
   - 从 outline / deck.json 读取每页 key、title、role、message。
   - 判断每页承担的说服任务:建立紧迫性、提出主张、展示方案、证明可行、收束下一步。
   - 标记每页的证据强度和风险:是否缺数据、是否太抽象、是否跳过客户关切。

4. **逐页模拟**
   - 每页输出:主要反应、被打动点、疑问、沉默风险、谁会打断、下一页是否承接。
   - 模拟 quote 必须标注为 `simulated_quote`,不能写成真实客户原话。
   - 不要为了戏剧性编造客户内部信息。

5. **预测会议走向**
   - 输出一个主要结果:推进下一步 / 要求补材料 / 要求内部评估 / 暂缓 / 拒绝。
   - 给出 confidence,并解释是哪些 deck 信号导致这个判断。
   - 评分只作为排序工具,不要写成真实概率。

6. **形成修改队列**
   - 按优先级列出要改的 slide、要补的证据、要删的废话、要调整的讲法。
   - 修改建议必须能回写到 `deck.json` 或 `outline.json`。
   - 对无法 defend 的主张,只允许改成 open question 或证据缺口,不要补编数字。
   - 修改队列必须等待用户确认;确认后才交回 `deck-designer` / `deck-renderer` 迭代。

## JSON 核心字段

- `source`: 输入 artifact、限制和假设。
- `meeting`: 目标客户/场景、会议目标、成功下一步。
- `audience_panel`: 模拟听众角色。
- `deck_arc`: 对整套 deck 说服路径的判断。
- `slide_reactions`: 逐页反应和问题。
- `objection_map`: 角色维度的阻力地图。
- `outcome_forecast`: 会议最可能走向。
- `revision_queue`: 可执行改稿清单。
- `talk_track`: 讲法建议、开场、转场、收束。
- `claim_discipline`: 哪些判断是假设、哪些需要用户/客户确认。

## 硬规则

- 不把模拟结果说成真实调研、真实访谈或真实成交概率。
- 不编客户内部预算、组织政治、已发生事件或具名引语。
- 不输出“整体不错”这种空话;每条建议要能落到 slide key、证据或讲法。
- 不只评价视觉;重点是 deck 是否推动目标受众做下一步决定。
- 不建议用户靠夸张承诺解决异议;证据不足时,建议补材料或降低 claim。
- 不自动触发改稿、发布或入库;预演反馈必须由用户确认“修改”后才进入下一轮规划和渲染,用户确认“不用改”后才进入发布物确认。云端发布也必须等待用户确认当前发布物。

## Handoff

预演完成后,把 `revision_queue` 交回:

- `deck-designer`: 当问题是叙事结构、受众选择、页序、每页重点、关键 idea 或主张。
- `deck-renderer`: 当问题是具体页面、文案、layout、可读性、素材落地或证据页。
- `deck-validator`: 当下一版生成后需要再次验收。
- `publisher`: 当 deck 通过验收且预演没有阻断性修改建议时,把可复用的 slide、素材和知识交给入库流程。
- 飞书 Base 素材库/知识库: 当问题是缺客户案例、行业数据、demo、logo 或产品截图。
