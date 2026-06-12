# F-305 · 版式收编:「raw unless ceremonial」——冻结正文 schema 版式,只留仪式五件套

> 状态:**REGISTERED**(2026-06-12 用户拍板「记个工单」,只记账不动工)
> 类型:架构决策记录 + 待执行工单 · 优先级 P2(无 bug 压迫,窗口期任选)
> 决策来源:2026-06-12 会话「deck 99% 都是 raw,deck.json / 固定 layout 还有必要么」
> + 用户长期方向「AI 设计能力越来越强,想把更多东西交给 AI 处理」。
> 延续:AUDIT-2026-06-10 决策更新「skill = 合规引擎,设计自由度留给模型」
> (F-263 / F-276 不做设计模板的同一逻辑收尾)。

## 0. 两个决策(本单只执行第二个)

| 问题 | 裁决 | 性质 |
| --- | --- | --- |
| deck.json 这层还要不要? | **保留,不再反复讨论** | 决策记录(无代码改动) |
| 固定 layout 还要不要? | **冻结全部正文版式,schema 只留仪式页 + 机制页** | 待执行工单 |

### 0.1 deck.json 保留的裁决理由(记录在案,防重复辩论)

raw 占比越高,deck.json 越不是「布局引擎」,而是**事务底座**:

- 真源可重渲(index.html 永远是派生物);
- 乐观锁 + auto-backup + schema-fail 回滚的挂点(F-48 一族);
- `custom_css` + `magic_move` 的唯一重渲存活槽;
- lift / translate / pptx-import(canvas)的统一作用面;
- 页身份契约(`data-slide-key`,page N = frame N = slides[N-1]);
- 多 agent 并发的单写者合并点。

诚实的替代方案(每页 fragment 文件 + manifest)在绿地下成立且编辑更顺手,但迁移
= 重开全部已愈合的锁 / 回滚 / round-trip 伤口 + 制造第二套平行系统(deck-translate
切块线的退役教训:别重建)。日常编辑痛点已被 canonical loop 解决(改渲染出的 DOM →
sync back,从不手摸 JSON 字符串)。

**重新审视的阈值条件**(全部满足才值得再谈):100% raw + 永不 pptx 导入 + 永不
翻译 / lift + 永远单写者。当前一条都不满足。

## 1. 数据(2026-06-12 普查:25 deck / 525 页)

| 类别 | layout | 页数 | 占比 |
| --- | --- | --- | --- |
| 自由设计 | raw | 410 | **78.1%** |
| 仪式 / 结构页 | section 39 · cover 15 · agenda 6 · quote 5 · end 4 | 69 | **13.1%** |
| 机制页 | iframe-embed 14 · canvas 1 | 15 | 2.9% |
| **正文模板(本单冻结对象)** | content 14(3up:6 / 2col:5 / before-after:2 / story-case:1)· flow 5 · table 4 · chart 3 · stats 3 · arch-stack 2 | **31** | **5.9%** |

- 正文模板 31 页 ÷ 25 deck ≈ 平均每 deck 1.2 页,且散在 10+ 个版式 / 变体上——事实性死亡。
- `image-text` / `logo-wall` / content 的 `blocks` / `matrix` 变体:**零使用**。
- schema 残余用量高度集中在仪式页;**section(39 次)是 schema 第一大户,比 cover 多一倍**。
  (用户口径「99% raw」实测 78%,但方向成立:正文早已全面 raw 化。)

复跑命令(repo 根,执行前后各跑一次做对照基线):

```bash
python3 -c "import json,glob,collections; cnt=collections.Counter(); [cnt.update(s.get('layout','?') for s in json.load(open(p)).get('slides',[])) for p in glob.glob('runs/*/output/deck.json')]; print(cnt.most_common())"
```

## 2. 切割原则

> **必须一模一样的页面留给代码;应该各不相同的页面交给 AI。**

- 仪式页(封面 / 分章 / 目录 / 金句 / 尾页)是**一致性问题**不是设计问题:同 deck 的
  N 个分章页就该结构全同。确定性模板零 token、零漂移;AI 再强,在这里也没有设计
  余量可赚。raw 永远是逃生门(想做主题化分章页随时走 raw),留 schema 不损失表达力。
- 正文页是**表达力问题**:固定模板 = 设计 ceiling 残留,与「合规引擎」定位冲突,
  且数据证明模型自己都不选它。
- AI 能力增强趋势下的层次区分:该退的是**设计约束层**(模板 = 能力拐杖,随模型变强
  过时);不该退、反而更重要的是**契约治理层**(deck.json + validator + 锁 = 验收
  带宽)。委托给 AI 的规模 × 验收带宽,后者才是天花板。

## 3. Scope(执行清单)

### 3.1 保留(动也不动)

- **仪式五件套** schema:`cover` `section` `agenda` `quote` `end`
- **机制类**:`raw` · `canvas`(pptx 导入底座)· `iframe-embed`(prototype-embed
  机制)· `replica`(backfill / round-trip 机制)

### 3.2 冻结(deprecate,不删)

正文版式全部:`content`(含全部 variant:2col / 3up / before-after / blocks /
matrix / story-case)· `flow`(process / swim / timeline / tree)· `stats`
(hero / row / waterfall)· `chart` · `table` · `arch-stack` · `image-text` ·
`logo-wall`

冻结方式(三条,缺一不可):

1. **renderer 兼容性不变**:继续渲染存量 deck,重渲零回归。不删模板文件、不删
   `_story_case_fit.py` 等配套代码;模板文件头部加
   `<!-- DEPRECATED F-305: frozen for legacy decks; new slides go raw -->`。
2. **validator 新增 deprecation 告警**:**仅对新增页**使用冻结版式时报
   `R-LAYOUT-DEPRECATED`(WARN 级,绝不 error——存量 deck 的编辑 / 重渲不能被卡)。
   「新增页」判定可复用 F-302 baseline 机制(new-vs-pre-existing diff)。
3. **文档口径单源化收窄**:`references/deck-generation-policy.md` 的 schema 回退
   allowlist(F-260 已单源化)收窄为仪式五件套;`design-first.md` / designer /
   renderer 子技能同步;控制器 SKILL.md Hard Gate #3 措辞从 "pure standard shapes"
   改为 "ceremonial pages only (cover / section / agenda / quote / end)"。

### 3.3 投入转移

省下的正文模板维护面(渲染分支 × validator 适配 × 文档 × 测试矩阵)转投 **raw 侧
validator 覆盖**——真窟窿在那边:R-VIS-TITLE-POSITION 的 `.title-zh` 选择器盲区、
raw 页自创 kicker 无规则可拦(memory 在案)。方向挂钩 F-257(跨页一致性)。

## 4. 防误读(重要)

**本单 ≠ AUDIT-2026-06-10 已否决的「F-260 原稿:把 raw 收窄到 4 种页型」。**
那条是收窄 *raw*(强迫自由页回模板,与 raw-first 冲突,已否决);本单是收窄
*schema fallback*(把模板名单砍小,raw 领地更大)——方向相反,与 raw-first 同向,
是「不做设计模板」决策(F-263 / F-276 WONTFIX)的自然收尾。

## 5. 验收标准

- [ ] 存量 25 deck 全部重渲零回归(冻结版式照常渲染)。
- [ ] 新 deck 新增页用冻结版式 → `R-LAYOUT-DEPRECATED` WARN 出现;存量页重渲 /
      编辑 → 不报。
- [ ] 三处文档口径一致且互引:deck-generation-policy.md / design-first.md /
      SKILL.md Hard Gate #3。
- [ ] §1 普查命令复跑,正文模板新增量 = 0(执行后基线)。

## 6. 关联

F-260(allowlist 单源化——本单只改名单内容)· F-257(跨页一致性——投入转移去向)·
F-263 / F-276(WONTFIX 设计模板——同一逻辑)· F-302(baseline 机制——deprecation
告警的「新增页」判定可复用)· AUDIT-2026-06-10 决策更新 ·
memory `feedback_skill_compliance_engine_not_design_system`
