# lark-deck-cyrus · 产品迭代方向

本项目的目标不是做一份能看的 demo,而是形成一个围绕客户场景持续进化的
deck 生产系统:用户可以通过本地 agent + skills,或通过飞书 bot,把业务场景
转成高质量 deck 规划,再稳定渲染成可交付、可编辑、可入库复用的 H5 deck。

## 产品原则

1. **场景先于页面**:先判断用户是谁、要说服谁、业务卡点是什么,再决定页型。
2. **规划先于渲染**:文本 brief 必须先生成 outline,再进入 DeckJSON / H5。
3. **素材可检索**:图片、视频、icon、logo、demo 都要有统一索引和来源纪律。
4. **知识可累积**:行业痛点、产品卖点、客户案例、反对意见沉淀到知识库。
5. **交付可闭环**:每次输出保留 deck.json、texts.md、FEEDBACK.md 和素材 manifest。

## 核心用户旅程

### 1. 本地 agent + skills

用户在本地挂载仓库,给出场景 brief、文档、案例行或已有材料。

流程:

1. `deck-outline-planner` 读取 brief + 知识库,产出结构化 outline。
2. 用户确认关键判断:目标受众、行业痛点、主张、证据缺口、素材计划。
3. `feishu-deck-h5` 消费 outline,优先走 DeckJSON-first 渲染。
4. `server/generator.py` 或本地 skill runner 输出 H5、texts.md、FEEDBACK.md、asset manifest 和可编辑 zip。
5. `pitch-rehearsal-simulator` 模拟目标客户听这套片子的反应,输出异议地图、
   结果预测和改稿队列。
6. 高质量页面进入 slide library,低质量反馈进入知识库或模板 backlog。

### 2. 飞书 bot

用户在飞书里把需求、文档链接、客户名称、图片或视频丢给 bot。

流程:

1. bot 解析上下文,生成同一份 outline schema。
2. 若信息不足,bot 用 2-3 个高价值问题补齐,不是直接生成空泛 deck。
3. bot 调用 H5 生成链路,默认返回 remote zip 或在线预览链接。
4. bot 可追加讲前预演:按参会角色模拟反应、追问、阻力和下一步概率。
5. 用户在飞书里反馈页级修改,bot 回写 deck.json/texts.md,再生成新版。
6. bot 将最终 deck、素材引用、预演摘要和反馈摘要写回知识库和素材库。

## 系统分层

| 层 | 责任 | 当前落点 |
|---|---|---|
| 入口层 | 本地 agent、飞书 bot、未来 API | `skills/`, `server/generator.py`, bot orchestration backlog |
| 规划层 | 场景识别、痛点判断、deck outline | `skills/deck-outline-planner/` |
| 知识层 | 行业、产品、案例、异议、证据纪律 | 飞书 Base `知识库`; 本地仅 cache |
| 素材层 | 图片、视频、icon、demo、logo 索引 | 飞书 Base `素材库`; `assets/shared/` 仅 cache |
| 渲染层 | DeckJSON、模板、CSS/JS、校验 | `skills/feishu-deck-h5/`, `server/generator.py` |
| 预演层 | pitch 听众模拟、异议地图、改稿队列 | `skills/pitch-rehearsal-simulator/` |
| 复用层 | slide library ingest、locator、反馈闭环 | `FEEDBACK.md`, `assets-manifest.yaml`, backlog |

## 里程碑

### P0 · 产品骨架

- 建立 outline skill 和 schema,让场景规划成为一等产物。
- 建立知识库目录和行业 pain map seed。
- 建立素材库索引脚本,支持图片、视频、icon、demo 等类型。
- 在 H5 skill 中声明 outline -> DeckJSON 的消费协议。

### P1 · 可用闭环

- bot 和本地 agent 复用同一份 outline schema。
- H5 渲染器按 outline 的素材计划解析 asset catalog。
- H5 生成后产出 pitch rehearsal artifact,把“客户会怎么反应”转成可执行改稿。
- 建立 10-20 个真实场景 eval:输入 brief -> outline -> deck -> 人评。
- slide-library ingest 使用 `data-slide-key` + asset manifest 做复用追踪。

### P2 · 持续优化

- 行业知识库覆盖高频行业:消费零售、餐饮、制造、金融、互联网、教育。
- CSS/JS 升级从真实失败样本驱动,每次加规则必须有回归样例。
- 用 FEEDBACK.md 聚类模板缺口,沉淀新 layout/block,减少 raw HTML。
- bot 支持多轮页级修改、素材补传、版本 diff、入库建议。

## 完成定义

一次生成任务只有满足以下条件才算产品可用,不算 demo:

- 有明确业务场景、目标受众、成功指标。
- 有 outline 文件或等价结构化规划,能解释每页为什么存在。
- 每个事实主张都有来源等级或证据缺口标注。
- 使用统一素材索引,不把临时图片/logo 散落在输出目录。
- H5 产物通过 validator,并可通过 texts.md 或 deck.json 继续迭代。
- FEEDBACK.md 记录本次判断和下一次应该改进的系统能力。
