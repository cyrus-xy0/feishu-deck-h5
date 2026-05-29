# content-density — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:判断输入是否过薄 / STOP-and-ask 模板

## CONTENT-DENSITY POLICY (mandatory) — augment thin input by default · no-fabrication guardrail

A 飞书 deck slide is **information-dense by design**. Empty space + 3 lines
of body copy reads as half-finished — the audience reaction is "为什么这页
这么空,你是不是没准备好"。The skill's defaults aim for slides that look
*deliberately curated*, not *padded out*。

**默认动作翻转(2026-05-26)**:旧策略是"输入太薄 → 先停下来问要不要补",
结果 LLM 习惯性出干瘪 3 行 body,被同学反馈"空 / 不好看"。**专业补全是
设计工作本身,不是需要审批的增补**。所以默认改成:

1. **默认就专业补全** —— 把用户输入当 SEED,按真正咨询/战略 deck 的信息密度
   设计这一页(见下 "What augmentation is allowed")。这是默认动作,不需要先问。
2. **唯一硬护栏:不编 attributed facts** —— 具体公司数字 / 具名引语 / 来源出处
   绝不编(见下 + ONE-PAGER no-fabrication 规则)。补的是公开行业知识 / 产品能力
   / 类似客户故事,且标注来源性质。
3. **沙化版式兜底** —— 真没东西可补时,换 sparser-by-design layout
   (`quote` / `big-stat` / `cover` / `end` / `image-text`),2 行也成立。

### The rule (mandatory) — 默认补,只在两种情况停下来问

检测到薄输入(layouts that **need density**:`content-2col` / `content-3up` /
`stats` / `table` / `timeline` / `process`)时:

- **默认**:直接专业补全 + 生成,**不停**(补全计划在 DESIGN PHASE Step 1 已
  写进 DESIGN-PLAN.md,supporting 页随 deck 一起出;hero 页本就会过确认门)。
- **只在以下两种情况才 STOP-and-ask**:
  1. **(a) 薄到任何 layout 都撑不住** —— 连补也撑不起一页(用户给的就一个词,
     既没角色也没具体内容)。
  2. **(b) 意图本身有歧义** —— 这页的角色 / 唯一重点不明(Q0/Q1 填不出),
     补什么方向取决于用户想强调什么。这是问**意图**,不是问"能不能补"。

停下来问时,用下面的 Asking-prompt template。注意区分:**问意图 = 该问;
问"要不要让我补文案" = 不要问,直接补**。

### What counts as "thin" — heuristic

| Layout | Expects | Thin signal |
|---|---|---|
| `content-3up` | 3 distinct points, each with title + 2-3 body lines | < 3 points provided, OR each point is 1 sentence |
| `content-2col` | One narrative + a stack of supporting points OR a visual | text column < ~80 chars, no visual material in scope |
| `stats` | 4 KPI numbers + labels + brief sources | < 3 numbers, OR all from same domain |
| `table` | ≥ 4 rows × 3 cols of meaningful comparison | < 3 rows, OR the columns aren't really distinct |
| `timeline` | 4-6 chronological milestones | < 3 milestones, OR all in same week |
| `process` | 3-6 sequential steps | < 3 steps, OR steps are vague |
| `one-pager case` (story-case) | 4 beats: 痛点 / 冲突 / 解法 / 价值 | any beat < 10 chars (already enforced by render-deck.py schema-fit refusal — exit 4) |

For `quote` / `big-stat` / `cover` / `agenda` / `section` / `end` /
`image-text`, terse input is **fine** — these are sparse-by-design.
The agent doesn't need to ask for these.

### What augmentation is allowed (after user confirms)

The framing the agent uses during augmentation:

> **"结合输入的信息,如果画一页专业的 PPT,请帮我设计对应的内容,
> 要专业风格的。"**

That is — treat the user's input as a SEED, then design the slide with
the information density and structural rigor of a real consulting /
strategy deck. Not as a creative-writing exercise, not as a marketing
brochure: as a **content-rich page a senior decision-maker would actually
read**. Concrete numbers, concrete capabilities, concrete examples,
named adjacent customers — the kind of detail that earns the slide's
real estate.

ALLOWED:
- Industry context the agent knows (e.g. "便利店行业的库存周转一般 12-15 次/年")
- Common pain points associated with the user's named scenario
- Product capability descriptions (飞书 / 多维表格 / 飞书会议 etc.)
- Adjacent customer stories from the agent's knowledge (e.g. "类似海底捞这种连锁门店常用 ……")
- Typical KPI values for the industry (always tagged as "行业基准 · 公开数据")

NOT ALLOWED, even after user confirms:
- Specific numbers attributed to a specific company (the user didn't give)
- Quotes attributed to a named person (the user didn't provide)
- Source citations like "客户访谈" / "内部口径" (covered by the existing
  "NEVER fabricate STORY ids" rule)
- Future product roadmap claims

The line: **augmentation is general industry / product knowledge tagged
as such**; it's NEVER specific facts attributed to specific entities.

### Asking-prompt template

When the agent stops to ask, use roughly this shape:

> "你给的信息支撑不满 `<layout>` 这个版式 —— 它通常需要 `<X>`,
> 你给的是 `<Y>`,直接出图会显得空。
>
> 我可以从以下几个方向**补**(都是公开行业知识 / 产品能力 / 类似客户故事,
> 不会编你没说的具体数据):
>
> 1. `<选项 1 · 一句话>`
> 2. `<选项 2 · 一句话>`
> 3. `<选项 3 · 一句话>`
>
> 或者:换成 `<sparser layout 建议>` / 你再补一段背景给我 / 直接出空版自己改。
>
> 你选哪个?"

### Connection to the no-fabrication rule

This policy and the **NEVER fabricate STORY ids / source attributions**
rule (next section) are siblings:

| Rule | What can never happen | What CAN happen |
|---|---|---|
| No fabrication (next section) | Specific facts (story id, source citation, quote attribution) made up | (nothing — facts are either real or absent) |
| Content-density (this section) | Fabricating **attributed** facts while augmenting (company-specific numbers / named quotes / sources the user didn't give) | **Professional augmentation by default** — public industry knowledge / product capability / adjacent stories, tagged as such; **no confirmation needed** |

Both come from the same north star: **the deck must not silently invent
material that the user couldn't defend in front of the audience** —— 但"补到
信息密度够"和"编造具名事实"是两回事:前者默认做,后者绝不做。

---

