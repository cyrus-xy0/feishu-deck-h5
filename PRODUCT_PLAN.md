# lark-deck-cyrus 产品规划

> 版本: 2026-05-26  
> 范围: 基于本项目文档、近期 eval 产物、Base 迁移记录，以及历史 session 中围绕 GTM 场景、部署方案、素材库和 skill 一致性的讨论整理。

## 1. 产品定位

`lark-deck-cyrus` 要做的不是一个“能生成 HTML PPT 的 demo”，而是一套面向 GTM 团队的 **HTML Pitch Deck 生产与复用系统**。

核心判断:

- HTML deck 替代 PPT,成为 GTM 对客户 pitch、内部 alignment、方案介绍的主要材料形态。
- GTM 同学用低门槛入口拿到高一致性、高质量、可修改的 pitchdeck。
- 每次优秀输出都能沉淀为团队资产,下次可被搜索、复用、改版。

一句话产品定义:

> GTM 在飞书里提出业务需求,系统基于结构化规划、设计系统、素材库和确定性渲染生成可直接讲的 HTML deck;讲完后好页自动进入团队素材库,未来可搜索、插入和再生成。

## 2. 目标用户与使用场景

### 2.1 主要用户

| 用户 | 目标 | 对产品的真实要求 |
|---|---|---|
| GTM / 售前 / 客户成功 | 快速做出客户 pitchdeck | 简单入口、质量稳定、能改、能发链接 |
| GTM Leader / Enablement | 保证团队对外材料一致 | 统一 icon、layout、话术结构、数据来源纪律 |
| 方案专家 / PMM | 复用行业方案和产品叙事 | 能维护 pitch recipe、行业知识、产品模块 |
| 设计系统 / 工程维护者 | 保持视觉和生成链路稳定 | 可测试、可校验、可版本化、可追责 |

### 2.2 优先业务场景

第一阶段只抓四个高频动作:

| 场景 | 用户说法 | 系统输出 |
|---|---|---|
| 新建客户 pitch | “帮我做一份 XX 客户 AI 知识库 pitchdeck” | 一份可讲的 HTML deck,带预览链接和可编辑源 |
| 基于已有材料改版 | “把这份 deck 改成餐饮行业版本” | 复用结构,替换客户、行业痛点、案例、产品重点 |
| 找团队已有好页 | “有没有零售行业 Base 对比 Excel 的页” | 返回 slide 缩略图,可插入到当前 deck |
| 讲完后沉淀资产 | “这份讲得不错,以后复用” | 通过 gate 后入库,带标签、来源、版本和缩略图 |

## 3. 产品原则

1. **业务场景优先**: 先判断客户、受众、决策目标和业务卡点,再生成页面。
2. **规划先于渲染**: brief 必须先进入 outline / recipe / DeckJSON,不能直接自由写 HTML。
3. **一致性靠约束**: 固定 design system、layout、asset vocabulary、validator 和发布 gate。
4. **源文件不是 HTML**: `deck.json` 是可维护源,`index.html` 是渲染产物。
5. **素材可检索可追踪**: logo、icon、案例、demo、优秀 slide 都要有索引、来源和权限边界。
6. **好内容回流系统**: 每次生成后的 `FEEDBACK.md`、素材引用和通过 gate 的 slide 都要服务下一次复用。

## 4. 端到端产品链路

```text
飞书 Bot / Web 表单
  -> 需求澄清
  -> deck-outline-planner 生成结构化 outline
  -> Pitch Recipe / Layout 选择
  -> 素材库解析和缺口标注
  -> DeckJSON
  -> feishu-deck-h5 renderer
  -> validator / screenshot / gate
  -> pitch-rehearsal-simulator 讲前预演
  -> HTML 预览链接 + 可编辑包
  -> Web 轻量编辑
  -> 发布客户链接
  -> Slide Library 入库 / 复用
```

## 5. 产品架构

| 模块 | 产品责任 | 当前基础 | 规划方向 |
|---|---|---|---|
| 入口层 | GTM 从哪里开始 | 目前主要是 Codex / skill | 飞书 Bot 为主,Web 表单为辅,Codex 给维护者 |
| 规划层 | 先把 brief 变成可执行 deck 结构 | `skills/deck-outline-planner/` | 增加 pitch recipe、行业场景和 open questions |
| 知识层 | 行业痛点、产品主张、案例、异议 | 飞书 Base `知识库`; 本地仅副本 | 扩充来源等级和可引用边界 |
| 素材层 | logo、icon、demo、图片、优秀页 | 飞书 Base `素材库`; `assets/shared/` 仅 cache | 做成可搜索、可预览、可插入的素材库 |
| 渲染层 | 结构化 deck 到 HTML | DeckJSON、renderer、validator、`server/generator.py` 薄 wrapper | 生产级队列、持久化、静态托管和任务追踪 |
| 预演层 | 预测这套片子讲给目标受众后的反应 | `skills/pitch-rehearsal-simulator/` | 角色化 audience panel、异议地图、改稿队列、讲法建议 |
| 编辑层 | 生成后如何修改 | `texts.md`、DeckJSON、客户端 edit-mode | Web 轻量编辑 deck.json,重新渲染发布 |
| 发布层 | 成品放在哪里 | 本地 `runs/` | 对象存储 / 静态托管,每份 deck 有 URL 和版本 |
| 复用层 | 好页如何沉淀 | `data-slide-key`、gate 意识 | slide library 入库、搜索、组合、下载 |

## 6. MVP 范围

### 6.1 MVP 要解决的问题

让一个 GTM 不需要懂 repo、脚本和模板,也能在飞书里完成:

1. 提交客户 pitch 需求。
2. 回答 3-5 个必要问题。
3. 拿到一份可预览、可修改、可分享的 HTML deck。
4. 看到“拿这套片子去讲”的客户反应预演、主要阻力和改稿建议。
5. 修改文字、客户名、logo、页序。
6. 一键提交优秀页进入素材库候选。

### 6.2 MVP 不做

- 不做完整 PowerPoint 替代。
- 不做开放公网无权限分享。
- 不让 GTM 直接手改 HTML 作为正式链路。
- 不一开始做复杂工作流审批。
- 不自动编造客户数据、访谈来源、STORY id 或具名引语。

### 6.3 MVP 成功定义

| 指标 | 目标 |
|---|---|
| 生成成功率 | 80% 以上 brief 可生成首版 draft |
| 品牌一致性 | validator strict 通过率 95% 以上 |
| 首版时间 | 5 分钟内拿到预览链接 |
| 可修改性 | 80% 常见修改不需要维护者介入 |
| 复用沉淀 | 每 10 份 deck 至少沉淀 10 张可复用 slide |
| 用户信任 | 不出现不可 defend 的虚构数据或来源 |

## 7. 路线图

### P0: 生成链路产品化

目标: 从“本地 skill 能跑”变成“服务端能稳定生成”。

- 固化 `Brief -> Outline -> DeckJSON -> HTML` 标准链路。
- 产品化 `server/generator.py` wrapper,负责创建任务、运行 renderer、跑 validator、输出链接。
- 输出固定产物:`deck.json`、`index.html`、`texts.md`、`FEEDBACK.md`、`assets-manifest.yaml`、可编辑 zip。
- H5 之后追加 `pitch-rehearsal.json`、`PITCH_REHEARSAL.md`,先做离线 heuristic,再允许 agent 精修。
- 将当前 5 个 eval 场景扩展为回归集:零售、制造、金融、HR、SaaS 支持。
- 修正文档漂移,确保 README / PRODUCT / SKILL / DeckJSON 文档对“layout 数量、inline 模式、编辑方式”的描述一致。

### P1: GTM 入口和轻量编辑

目标: GTM 能从飞书自然发起,拿到可改 deck。

- 飞书 Bot MVP:
  - 接收 brief、客户名、行业、目标受众、产品范围、附件链接。
  - 信息不足时只问 3-5 个高价值问题。
  - 返回预览链接、编辑链接、下载包。
- Web 轻量编辑:
  - 改标题、正文、客户名、logo。
  - 删除/重排页面。
  - 从素材库插入已有 slide。
  - 保存后重新渲染,生成新版本 URL。
- 任务状态页:
  - 展示生成中、成功、失败原因、validator 报告。

### P2: 素材库和复用闭环

目标: 好 deck 变成团队资产,下次能搜到、插入、改版。

- 设计素材和业务素材分库:
  - Design Kit: layout、CSS token、飞书品牌资产、产品 icon。
  - Business Library: 客户案例、行业方案、优秀 slide、demo、已发布 deck。
- 入库 gate:
  - `data-slide-key` 唯一。
  - 来源等级明确。
  - 无敏感客户信息泄露。
  - 缩略图、文本、标签、deck 来源完整。
- 检索能力:
  - 按行业、产品、客户阶段、deck 类型、价值主张、layout 搜索。
  - 返回缩略图和可插入建议。
- 沉淀流程:
  - GTM 标记“值得复用”。
  - 维护者审核。
  - 进入 slide library。

### P3: 知识和 recipe 层

目标: 从“好看的页”升级为“可复制的 pitch 逻辑”。

- 建立 pitch recipe:
  - 首访客户 pitch。
  - POC 方案介绍。
  - 复盘/续约。
  - 行业案例包。
  - 竞品替代方案。
- 建立行业知识包:
  - 消费零售、餐饮、制造、金融、互联网、教育、HR。
  - 每个行业包含业务时刻、关键角色、核心痛点、证据建议、推荐页型。
- 建立产品叙事模块:
  - Base、Aily、知识问答、妙搭、飞书项目、会议、People 等。
- 将 `FEEDBACK.md` 聚类为模板 backlog,驱动新增 layout/block。

### P4: 平台化和治理

目标: 让团队可以长期运营这个系统。

- 权限和分享:
  - 内部 viewer 受飞书登录保护。
  - 客户链接支持有效期和访问范围。
- 版本管理:
  - 每次重新生成保留版本。
  - 支持 deck diff 和回滚。
- 质量看板:
  - 生成量、失败原因、常用 recipe、复用 slide、热门行业。
- 生命周期:
  - 过期素材提醒。
  - 敏感客户素材下架。
  - 品牌资产升级后的批量重渲染。

## 8. 关键产品决策

### 8.1 用户入口

默认入口是 **飞书 Bot**,不是 Codex。

- GTM 的自然工作流在飞书里。
- Codex 保留给维护者、复杂定制和设计系统升级。
- Web 页面用于预览、编辑和素材库浏览。

推荐入口分层:

| 入口 | 面向谁 | 用途 |
|---|---|---|
| 飞书 Bot | GTM | 新建、改版、查素材、拿链接 |
| Web 工作台 | GTM / PMM | 预览、轻量编辑、素材库检索 |
| Codex / repo | 维护者 | 模板、validator、schema、批量迁移 |

### 8.2 渲染位置

生成渲染在服务端,浏览器只负责展示。

```text
brief / deck.json
  -> 服务端 renderer
  -> index.html
  -> 静态托管 URL
```

这样才能统一版本、跑校验、保留源文件、支持重新生成。

### 8.3 素材维护

素材分两类:

| 类型 | 放哪里 | 谁维护 |
|---|---|---|
| 设计素材 | Design Kit / 当前 repo | 设计系统和工程维护者 |
| 业务素材 | Slide Library / Base / 对象存储 | GTM、PMM、维护者共同维护 |

### 8.4 修改方式

正式修改链路是:

```text
编辑 deck.json / 结构化字段
  -> 重新渲染 HTML
  -> 重新校验
  -> 发布新版本
```

`texts.md` 和 HTML edit-mode 可以作为轻量编辑入口,但最终仍要回写结构化源。

## 9. 当前资产与差距

### 9.1 已有基础

- `feishu-deck-h5`: 飞书风格 HTML deck 设计系统、模板、运行时和 validator。
- `pitch-rehearsal-simulator`: H5 后置预演,模拟购买委员会角色、逐页反应、异议地图和改稿队列。
- `deck-json`: 单一数据模型、schema、renderer、CLI、layout/block 模板。
- `deck-outline-planner`: 将业务 brief 变成场景、主张、证据缺口、素材计划和页级规划。
- `assets/shared`: 已形成公共素材索引,当前 Base 迁移记录包含 571 个 asset、52 条 knowledge。
- `evals`: 已有 5 个产品级场景 eval,覆盖 outline、render、strict check、截图和评分。
- `data-slide-key`: 已有 slide library 复用锚点意识。

### 9.2 主要差距

| 差距 | 影响 | 优先级 |
|---|---|---|
| 缺 GTM 自助入口 | 普通用户仍依赖会用 Codex 的人 | P1 |
| 缺生产级生成服务 | 已有薄 wrapper,但缺队列、持久化存储、托管 URL、鉴权和回滚 | P0 |
| 缺业务 recipe | layout 好看但 pitch 逻辑还靠人 | P3 |
| 素材库还偏文件/索引 | 用户不能自然搜索、预览、插入 | P2 |
| 编辑体验未产品化 | GTM 常见修改仍可能找维护者 | P1 |
| 入库流程未闭环 | 好页难持续变成团队资产 | P2 |
| 文档存在漂移 | 新用户信任和维护成本受影响 | P0 |

## 10. 近期实施建议

### 10.1 两周内

- 整理并合并产品文档,明确 `PRODUCT.md`、`PRODUCT_PLAN.md`、`README.md` 分工。
- 为 `deck-outline-planner` 增加 3 个 pitch recipe 示例。
- 把 `pitch-rehearsal-simulator` 接入至少 1 个产品 eval,验证 JSON、报告和回写建议格式。
- 将 product eval 固定进 CI 或本地一键命令。
- 梳理文档漂移:layout 数量、inline/finalize、编辑模式、slide library 关系。

### 10.2 一个月内

- 把最薄的 generator wrapper 扩成可部署 service:
  - `POST /decks`
  - `GET /decks/{id}`
  - `POST /decks/{id}/regenerate`
- 输出静态 URL 和编辑包。
- 做飞书 Bot 原型:接 brief、问问题、返回链接。
- 做 Web 预览页:展示 deck、validator 报告、下载链接。

### 10.3 一个季度内

- 上线轻量编辑器。
- 上线素材库搜索和插入。
- 建立入库审核和 metadata schema。
- 将 Base 中的 asset / knowledge 变成生成时可查询的真实数据源。
- 形成 20 个真实场景 eval 和 50 张可复用 slide。

## 11. 产品风险

| 风险 | 表现 | 应对 |
|---|---|---|
| 生成内容不可 defend | 编造客户数据、访谈、STORY id | claim discipline 强制;缺证据写 open question |
| 视觉一致性下降 | 手改 HTML、临时色值、自由 layout | DeckJSON-first、固定 design kit、validator gate |
| GTM 觉得复杂 | 入口像开发工具 | 飞书 Bot + Web 工作台,隐藏脚本和 repo |
| 素材库变垃圾桶 | 所有 deck 都进库 | 入库审核、标签规范、过期下架 |
| 维护成本膨胀 | 每个客户都要定制模板 | recipe 优先,新增 layout 必须来自重复需求 |

## 12. 北极星指标

建议北极星指标:

> GTM 通过系统生成并实际使用的客户 pitchdeck 数量,以及其中被复用的 slide 数量。

配套指标:

- 生成到首次预览的时间。
- strict validator 通过率。
- 用户自行完成修改的比例。
- 每周新增可复用 slide 数。
- 素材库搜索到插入的转化率。
- 被重新使用的 deck / slide 占比。
