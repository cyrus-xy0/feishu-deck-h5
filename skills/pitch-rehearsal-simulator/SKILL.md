---
name: pitch-rehearsal-simulator
description: |
  Use this skill after a Feishu/Lark HTML deck has been planned or generated and
  the user wants to simulate what will happen if they pitch it to a customer,
  investor, leader, buying committee, or internal stakeholder. Common triggers:
  "模拟讲这套片子", "用户听完会怎样", "pitch rehearsal", "audience simulator",
  "客户会怎么反应", "拿这份 deck 去讲会有什么结果", "帮我预演这场提案".
---

# pitch-rehearsal-simulator

目标:把已经生成或已规划的 HTML pitch deck 放进一个**客户会议预演**里,模拟
不同听众角色逐页听到什么、哪里被打动、哪里会质疑,最后反推出 deck 和讲法
应该怎么改。

这不是“神谕式预测”。输出必须明确是基于当前 deck、受众画像和会议目标的
**scenario forecast / rehearsal result**,用于提高提案质量,不能伪装成真实用户
调研或真实成交概率。

## 触发时机

在以下链路后使用:

```text
brief
  -> deck-outline-planner
  -> feishu-deck-h5 / DeckJSON / HTML
  -> pitch-rehearsal-simulator
  -> deck revision queue / talk track
```

典型用户请求:

- "用这份片子去给客户讲,模拟一下会发生什么"
- "帮我看这套 pitch deck 对 COO / CFO / IT 各自有什么阻力"
- "生成完 HTML deck 后,给我一份客户反应预演"
- "这套 deck 拿去融资 pitch,投资人最可能问什么"

## 输入

优先读取这些 artifact,越靠前越可信:

1. `deck.json` — 稳定 slide key、title、layout 和结构化内容。
2. `outline.json` — 受众、目标、业务场景、痛点、证据缺口。
3. `index.html` — 当没有 deck.json 时,提取 `.slide` 的 `data-slide-key`、
   `data-layout`、标题和正文。
4. 用户补充的会议背景 — 客户名称、行业、参会人、会议目标、已知阻力。

如果只有 HTML 或只有 outline,仍然可以模拟,但要在输出的
`source.assumptions` 里说明限制。

## 输出

默认产出两份文件:

```text
pitch-rehearsal.json   # 结构化结果,符合 schema/pitch-rehearsal.schema.json
PITCH_REHEARSAL.md     # 给 GTM / 讲述者看的可读报告
```

落文件后用 stdlib 校验器检查:

```bash
python3 skills/pitch-rehearsal-simulator/validate-rehearsal.py \
  path/to/pitch-rehearsal.json
```

如果已经有 outline,可以先用内置 heuristic 生成第一版预演骨架:

```bash
python3 skills/pitch-rehearsal-simulator/simulate-pitch.py \
  --outline path/to/outline.json \
  --deck-json path/to/deck.json \
  --out-json path/to/pitch-rehearsal.json \
  --out-md path/to/PITCH_REHEARSAL.md
```

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

## Handoff

预演完成后,把 `revision_queue` 交回:

- `deck-outline-planner`: 当问题是叙事结构、受众选择、页序或主张。
- `feishu-deck-h5`: 当问题是具体页面、文案、layout、可读性或证据页。
- 飞书 Base 素材库/知识库: 当问题是缺客户案例、行业数据、demo、logo 或产品截图。
