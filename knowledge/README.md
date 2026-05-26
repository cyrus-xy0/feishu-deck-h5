# 知识库

这个目录沉淀 deck 规划阶段需要的业务知识。它不是文案素材堆,而是帮助
outline skill 判断行业痛点、业务场景、产品主张和证据缺口的知识层。

## 目录约定

```
knowledge/
├── README.md
├── industries/        # 行业 pain map、场景、常见证据、推荐页型
├── products/          # 飞书产品能力、边界、适用场景
├── stories/           # 已授权客户故事和可引用素材
├── objections/        # 常见反对意见与回应框架
└── evals/             # 输入 brief、outline、人评结果
```

## 来源纪律

每条知识都要能落到一个来源等级:

| 等级 | 含义 | 可怎么用 |
|---|---|---|
| `user-provided` | 用户在本轮或关联资料中明确提供 | 可直接进入 deck |
| `approved-story` | 已授权客户故事或内部确认材料 | 可进入 deck,保留 story/source |
| `public-pattern` | 公开行业常识、通用经营规律 | 可作为痛点判断,不要写成具体客户事实 |
| `hypothesis` | agent 基于场景推断 | 只能作为待确认假设或 open question |

禁止把 `public-pattern` 或 `hypothesis` 写成某个客户的具体数字、访谈结论、
具名引用或内部来源。

## outline skill 使用方式

`deck-outline-planner` 在生成 outline 前应读取:

1. 用户 brief 中明确出现的行业 / 场景对应的 `industries/*`。
2. 用户提到的飞书产品对应的 `products/*`。
3. 若用户给了客户名,只使用 `stories/*` 中已授权且匹配的内容。
4. 若没有匹配知识,在 outline 的 `open_questions` 或 `evidence_needed` 中暴露缺口。

## 建设原则

- 新知识优先写成结构化 pain map,而不是一段泛泛描述。
- 每个行业至少覆盖:业务时刻、关键角色、核心痛点、常见证据、推荐页型、素材提示。
- 每次真实 deck 生成后的 FEEDBACK.md,若出现 3 次以上同类判断,应沉淀进这里。
