# feishu-deck-h5 · 技术架构

> 飞书 / Lark 风格单文件 16:9 网页演示（HTML deck）生成技能的整体技术架构。
> 一句话概括：**控制器（Controller）做路由与调度，8 个子技能（Subskills）做实现，
> 所有内容收敛到唯一中间层 `deck.json`（DeckJSON），由确定性渲染器产出 `index.html`，
> 校验通过后本地交付或发布到飞书。**

渲染版示意图见 [`ARCHITECTURE.svg`](./ARCHITECTURE.svg)。

## 架构图

```mermaid
flowchart TB
  U(["用户请求<br/>飞书风格 deck · 解析 / 设计 / 渲染 / 校验 / 编辑 / 翻译 / 发布"])

  %% ===================== 控制器 =====================
  subgraph CTRL["控制器 Controller · skills/feishu-deck-h5/SKILL.md"]
    direction TB
    R1["Router 路由锁定<br/>Mode · Scope · Target"]
    R2["Hard Gates 硬性门禁<br/>① 必走 DeckJSON / render-deck.py<br/>② 先 Designer 后 Renderer<br/>③ 默认 raw-first<br/>④ 交付/发布前必校验"]
    R3["Multi-Agent Dispatch<br/>可用时每步派发 worker 子代理<br/>依赖链保持串行"]
    R1 --> R2 --> R3
  end

  U --> CTRL
  CTRL -.路由/派发.-> PIPE

  %% ===================== 子技能流水线 =====================
  subgraph PIPE["子技能流水线 Subskills · subskills/*/SKILL.md"]
    direction LR
    PARSE["Parser 解析<br/>素材 → source-dossier.json<br/>资产归一化"]
    DESIGN["Designer 设计<br/>→ outline.json<br/>+ DESIGN-PLAN.md"]
    RENDER["Renderer 渲染<br/>outline → deck.json<br/>→ index.html"]
    VALID["Validator 校验<br/>文本/视觉/结构/语言/交付"]
    SIM["Simulator 排练<br/>pitch-rehearsal"]
    PUB["Publisher 发布"]

    PARSE --> DESIGN --> RENDER --> VALID
    VALID -->|通过| SIM
    VALID -->|通过| PUB

    EDIT["Editor 编辑<br/>改稿 / reskin / lift-swap / 导入"]
    TRANS["Translator 翻译<br/>backfill → text-pairs → apply"]
    EDIT --> RENDER
    TRANS --> RENDER
  end

  %% ===================== 核心数据模型 + 工具链 =====================
  subgraph CORE["核心数据模型 + 工具链 · deck-json/"]
    direction TB
    DJ[("deck.json · DeckJSON<br/>唯一事实来源 (SSOT)")]
    SCHEMA["deck-schema.json<br/>10 基础布局 + 2 特殊 + raw"]
    RD["render-deck.py<br/>纯函数渲染器 (确定性)"]
    VD["validate-deck.py / validate.py<br/>+ run-audits / audits.js"]
    CLI["deck-cli.py · locate-slide<br/>lift-slides · apply-text-pairs<br/>sync-index-to-deck · heal/reconcile"]
    SCHEMA --> DJ
    DJ --> RD
    RD --> VD
    CLI --> DJ
  end

  %% ===================== 渲染框架资产 =====================
  subgraph FW["渲染框架资产 · assets/ + deck-json/templates"]
    direction TB
    CSS["feishu-deck.css<br/>feishu-deck-patterns.css"]
    JS["feishu-deck.js<br/>edit-mode · grow-box-fit"]
    TPL["布局/组件模板 templates/"]
    SHARED["shared/ 客户 logo · 字节产品<br/>lark-*-bg / logo / slogan"]
    DELIV["copy-assets · inline-assets<br/>package-deliverable / finalize"]
  end

  %% ===================== Run 工作区 =====================
  subgraph RUNS["Run 工作区 · runs/&lt;时间戳-slug&gt;/"]
    direction TB
    IN["input/ · runtime-library/<br/>source-dossier.json · assets"]
    OUT["output/ · outline.json<br/>DESIGN-PLAN.md · deck.json · index.html"]
    LOG["log/ · PROMPTS.md<br/>pitch-rehearsal.json"]
  end

  %% ===================== 兄弟技能 =====================
  subgraph SIB["兄弟技能 Sibling Skills"]
    direction TB
    P2D["pptx-to-deck<br/>build_pptx / build_pptx_hybrid<br/>(.pptx → canvas deck.json)"]
    K2H["keynote-to-html"]
  end

  %% ===================== 飞书云 =====================
  subgraph CLOUD["飞书云 Feishu Cloud"]
    direction TB
    BASE[("Feishu Base<br/>共享知识 / 资产库")]
    HOST["飞书托管 magic-page<br/>magic-upload / magic-page-publish"]
    LARK["lark-base skill · lark-cli"]
  end

  %% ===================== 跨层关系 =====================
  RENDER -->|生产| DJ
  DJ -->|被各子技能读写| EDIT
  DJ -->|被各子技能读写| TRANS
  RD --> OUT
  RD -.使用.-> CSS
  RD -.使用.-> TPL
  VALID -.调用.-> VD
  DESIGN --> OUT
  PARSE --> IN
  DELIV --> OUT
  P2D -.以本技能为渲染后端.-> RENDER
  PARSE -.委派 .pptx.-> P2D
  DESIGN -.云上下文/资产.-> BASE
  PUB -->|确认后| HOST
  PUB -->|写回记录| BASE
  CLOUD -.lark-cli --as user.-> LARK

  classDef ctrl fill:#1f3a5f,stroke:#4a90d9,color:#fff;
  classDef core fill:#3d2c5f,stroke:#a06bd9,color:#fff;
  classDef cloud fill:#1f5f3a,stroke:#4ad98f,color:#fff;
  classDef data fill:#5f4a1f,stroke:#d9a64a,color:#fff;
  class R1,R2,R3 ctrl;
  class DJ,SCHEMA,RD,VD,CLI core;
  class BASE,HOST,LARK cloud;
  class DJ data;
```

## 分层说明

**控制器（Controller）** 是 `skills/feishu-deck-h5/SKILL.md`。它本身不产出幻灯片，
只负责三件事：路由锁定（Mode / Scope / Target）、硬性门禁、以及多代理派发。四条硬性门禁
分别是：生成必须走 DeckJSON 与 `render-deck.py`、生成必须先设计后渲染、默认 raw-first、
以及交付或发布前必须通过校验。当运行环境支持子代理时，控制器把每个流水线步骤派发给
独立 worker，但依赖链（解析 → 设计 → 渲染 → 校验 → 排练 / 发布）保持串行。

**子技能流水线（Subskills）** 共 8 个，位于 `subskills/*/`。新建 deck 的主链路是
Parser → Designer → Renderer → Validator，随后可选 Simulator（排练）与 Publisher（发布）。
对已有 deck，则由 Editor（改稿、reskin、lift/swap、导入）或 Translator（翻译本地化）发起改动，
再回到 Renderer 重新渲染并经 Validator 把关。

**核心数据模型与工具链（`deck-json/`）** 是整个系统的中枢。`deck.json` 是唯一事实来源，
受 `deck-schema.json` 约束；`render-deck.py` 是一个纯函数渲染器，相同 JSON 永远产出相同 HTML，
保证确定性；`validate-deck.py` / `validate.py` 与 `run-audits` 提供校验门禁；`deck-cli.py`
及 lift-slides、apply-text-pairs、sync-index-to-deck、locate-slide 等脚本支持脚本化批量操作。
`index.html` 始终是从 `deck.json` 派生的产物。

**渲染框架资产（`assets/` 与 `templates/`）** 提供视觉系统：`feishu-deck.css` 与 patterns 样式、
`feishu-deck.js` 与编辑态脚本、布局/组件模板，以及 `shared/` 下的客户 logo、字节产品图、
Lark 背景与品牌素材。交付脚本（copy-assets、inline-assets、package-deliverable、finalize）
负责把资产打包成可移植或真正自包含的成品，而非交付单个外链 HTML。

**Run 工作区（`runs/<时间戳-slug>/`）** 是每次任务的隔离目录：`input/`（含 runtime-library
的 source-dossier.json 与归一化资产）、`output/`（outline.json、DESIGN-PLAN.md、deck.json、
index.html）、以及 `log/` 与 PROMPTS.md。

**兄弟技能** 包括 `pptx-to-deck`（`build_pptx` / `build_pptx_hybrid` 把 .pptx 重建为可编辑的
canvas deck.json，以本技能为渲染后端，Parser 会委派给它）和 `keynote-to-html`。

**飞书云** 层：Feishu Base 作为共享知识与资产库供设计/渲染/解析/发布按需查询；Publisher 在用户
确认后通过 magic-page 系列脚本发布到飞书托管，并把发布记录写回 Base；云操作经 `lark-base` 技能的
`lark-cli --as user` 完成。
