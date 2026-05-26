---
name: deck-outline-planner
description: |
  Use this skill when the user asks for a deck plan, outline, proposal structure,
  sales narrative, 客户提案大纲, 汇报材料规划, or gives a raw business brief that
  should become a Feishu/Lark-style H5 deck. The skill turns scene goals into a
  structured outline with industry pain points, evidence gaps, asset needs, and
  DeckJSON layout candidates before feishu-deck-h5 renders HTML. It is especially
  important when the user says the product must not be just a demo.
---

# deck-outline-planner

目标:把用户的业务场景转成可执行的 deck 规划,再交给 `feishu-deck-h5`
生成 H5。这个 skill 不直接写 HTML,也不急着套模板;它先判断“为什么要做这份
deck、要打中谁、每页承担什么说服任务”。

## 输入

可接受任意组合:

- 一段业务 brief / 客户需求 / 销售场景
- 目标受众、行业、客户名、产品范围
- 用户提供的素材、文档、飞书链接、图片、视频或 demo 链接
- 已有 outline,需要升级为更专业的 deck 规划

## 输出

默认输出一份符合 `schema/deck-outline.schema.json` 的 outline JSON,并附
一段面向用户的简短说明。若用户只是在 brainstorm,可以先输出人读版大纲,
但最终进入 H5 生成前必须有同等字段。落文件后用 stdlib 校验器检查:

```bash
python3 skills/deck-outline-planner/validate-outline.py \
  skills/deck-outline-planner/examples/retail-agent-outline.json
```

核心字段:

- `brief`:主题、受众、目标、使用入口(local-agent / feishu-bot)。
- `scene`:行业、角色、业务时刻、核心冲突、信心等级。
- `thesis`:一句话主张、痛点、解法角度、差异化。
- `outline.slides[]`:每页 key、角色、核心信息、候选 DeckJSON layout、素材需求。
- `asset_plan`:图片、视频、icon、logo、demo 等素材请求和兜底。
- `claim_discipline`:哪些判断是用户给的,哪些只是推断,哪些必须确认。

## 工作流

1. **识别使用入口**
   - 本地 agent:可以产出 repo 内文件,强调 deck.json/texts.md/FEEDBACK.md。
   - 飞书 bot:默认考虑远程 zip、在线预览、飞书消息里的多轮反馈。
   - 不确定时写 `delivery_mode: "unknown"`,并把它列为 open question。

2. **抽取场景目标**
   - 目标受众是谁?
   - 这份 deck 要让对方做什么决定?
   - 成功指标是什么:约会、立项、预算、内部 alignment、产品试用、复盘通过?

3. **读取知识库**
   - Source of truth 是飞书 Base `知识库` 表,不是本地 `knowledge/` 目录。
   - 本地 agent 和飞书 bot 都必须通过仓库根目录的 `python3 scripts/base_library.py search-knowledge "<关键词>" --limit 10` 检索；bot 运行时用 `LARK_LIBRARY_AS=bot` 或全局 `--as bot`。
   - 本地 `knowledge/` 和 `.base-cache/knowledge/` 只作为缓存/副本；只有在用户明确允许离线模式时才可引用,并要说明使用的是 cache。
   - 根据行业、飞书产品、客户名分别搜索 Base；客户故事只使用 Base 中已授权/已沉淀记录。
   - 没有知识就暴露缺口,不要编。

4. **形成行业痛点判断**
   - 每个痛点必须包含:为什么现在重要、业务后果、建议证据、证据等级。
   - 不要把通用行业规律写成某客户已经发生的事实。

5. **设计 deck arc**
   - 第一段:为什么这个问题现在必须解决。
   - 第二段:飞书 / agent / bot 如何改变工作方式。
   - 第三段:落地路径、证据、下一步。
   - demo 只能作为论据或体验入口,不能成为整份 deck 的唯一主体。

6. **映射到 DeckJSON**
   - 优先选择 `feishu-deck-h5/deck-json/deck-schema.json` 已有 layout。
   - 每页都给 `layout_candidate`,但只作为建议;H5 skill 可在渲染时调整。
   - 若需要真实交互或在线体验,标记 `iframe-embed` / `phone-iframe` 或 `demo` asset。

7. **生成素材计划**
   - logo/icon/demo 先查飞书 Base `素材库` 表: `python3 scripts/base_library.py search-assets "<关键词>" --limit 20`。
   - `assets/shared/asset-index.generated.json` 只是由 Base 导出的本地缓存索引,不能作为源头手工维护。
   - 现场图片、客户截图、真实 demo 优先用户提供。
   - 找不到素材时明确 fallback,不要让模型临时画商标或伪造客户现场。

## 硬规则

- 不编客户数据、STORY id、访谈来源、具名引语。
- 不用“行业领先、全面赋能、智能升级”填满页面;每页要有可 defend 的判断。
- 信息不足时,提出少量高价值 open questions;已可合理规划时先给带假设的 outline。
- 每页必须有稳定的 `key`,后续会成为 `data-slide-key`。
- 输出要让 `feishu-deck-h5` 能继续工作,而不是只给一段漂亮文字。

## H5 handoff

用户确认 outline 后:

1. 把 outline JSON 放进本次 run 的 `input/` 或 `output/`。
2. 调用 `feishu-deck-h5` 的 DeckJSON-first 流程。
3. 根据 `outline.slides[].layout_candidate` 写 `deck.json`。
4. 根据 `asset_plan` 解析素材;缺素材时用 open question 或安全兜底。
5. 生成后在 FEEDBACK.md 记录:哪些 outline 判断被保留、修改或无法落地。

## Pitch rehearsal handoff

HTML deck 生成后,如果用户想知道“这套片子讲给客户会怎样”,把 outline 和
deck.json 交给 `pitch-rehearsal-simulator`:

```bash
python3 skills/pitch-rehearsal-simulator/simulate-pitch.py \
  --outline runs/<ts>/input/outline.json \
  --deck-json runs/<ts>/output/deck.json \
  --out-json runs/<ts>/output/pitch-rehearsal.json \
  --out-md runs/<ts>/output/PITCH_REHEARSAL.md
```

预演结果里的 `revision_queue` 可回写到 outline:叙事结构问题回到本 skill,
页面/文案问题交给 `feishu-deck-h5`,证据或素材缺口写入知识库/素材 backlog。
