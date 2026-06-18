# 生成流水线 · 性能优化设计方案（2026-06-16）

> 范围：deck 生成的**机械流水线**（render → schema 校验 → 视觉门量像素 → 截图 → 交付），
> 不含 LLM 创作阶段、也不含成品 deck 的运行时性能（P50–P55，另一回事）。
> 原则：**绝不为提速放松校验严格度**；每项改动都要有 before/after 数字。

---

## 0. 基线与认知纠正（先把现状摸准）

单次渲染 + 校验的真实成本分布：

| 环节 | 成本 | 实现 |
|---|---|---|
| 出底稿 → 派生 HTML | 秒级以下 | 模板拼装 |
| Schema 校验（validate-deck.py） | 毫秒 | 纯 Python |
| **视觉门**（run-audits.py 量像素） | ~1–5s | **一次 launch Chromium、整份 load 一次、量完所有页**；含 bounded settle（load 4s / 字体 2s / js-ready 5s / 图解码 / 350+200ms） |
| **截图**（deck-log snapshot `_shoot`） | 取决于改动页数 | **又一次 launch Chromium**、逐页 goto+截；**默认增量复用** |

**已经优化好的（不要重做）：**

- **`--iter` / `--scope`**：把审计 + 截图锁到改动页，~2m12s → ~12s（靠 render-deck 的 `.slide-hashes.json` 侧车）。
- **视觉门一次浏览器整份量完**（不是逐页重开）。
- **截图已是增量**：`_shoot` 默认对每页算 djb2(归一化 innerHTML) 指纹，与上一版一致就 `reuse` 旧 png、不重截（剥掉运行时内联 style 噪声，指纹稳定）。
- **bounded settle + 提前短路**（图片 `complete` 即跳过）。
- **fast-text 纯改字亚秒级双写**。

**认知纠正（影响方案）：**

1. 原 **#2「--final 跳过未变页截图」≈ 已实现**（见上"截图已是增量"）→ 降级为**验证项**，不是开发项。
2. 真正没省的是：一次 `--final` 会**起两个子进程、各 launch 一次 Chromium、各 load+settle 一次**（视觉门一趟 + 截图一趟，两段 bounded-settle 代码几乎重复）→ **合并这两趟是当前最大的真实空间**。
3. `--final` 的**几何审计是故意全量**（定稿门），不在"跳过未变页"的优化范围内；只有截图可增量、审计不削。

---

## 目标 / 非目标

- **目标 A**：缩短单次 `--final` 墙钟（主要靠合并两趟浏览器 load）。
- **目标 B**：缩短高频 `--iter` 编辑循环的**累计**墙钟（靠少冷启动 + 少跑整轮 `--final`）。
- **非目标**：① 改 `--final` 全量几何审计语义；② 放松任何 gate；③ 动成品运行时性能（P50–P55）。

---

## P0（前置必做）· 基准测量工具

没有 before/after 就不叫优化，也违背本技能"量真实、不靠感觉"的信条。

- **做什么**：一个 bench 脚本（建议 `assets/bench-render.py`），对一份固定 N 页样例 deck，分段计时：render / schema / 视觉门 / 截图（全新 vs 全增量两种）/ `--final` 全程 / `--iter` 单页；每段跑 ≥3 次取中位；输出 JSON。
- **验收基准**：后续每个 P-项都用它出 before/after 中位数。
- **工作量**：S。**必须最先做。**

---

## 方案清单（按性价比排序）

### P1（最高收益）· 合并"量像素"与"截图"为一次浏览器 load
- **问题**：`render --final` 跑两个子进程，各自 `pw.chromium.launch` + `goto` + 同一套 bounded-settle → 一次 `--final` 付**两次冷启动 + 两次 settle**。
- **设计**：一次 Playwright 会话内 **load + settle 一次**，先 `evaluate(audits.js)` 拿几何发现，再逐页 `screenshot`（沿用现有增量 reuse 逻辑）。两个独立工具（validate.py / deck-log snapshot）仍保留可单独调用；只让 **render-deck 的 gate 走合并路径**。
- **落点**：`assets/run-audits.py`（浏览器段）+ `log-tool/deck-log.py` 的 `_shoot`（截图段）抽出共用的"一次会话内 audit+shoot"；render-deck 调它替代两次子进程。
- **收益**：每次 `--final` 省一整趟 load+settle（~1–5s）+ 一次进程/浏览器冷启动。
- **风险**：① 审计会 mutate DOM（强制所有帧 `is-current`、`getAnimations().finish()/cancel()`），截图需要的是**逐页** `is-current` + `--fs-scale=1` 的干净终态 → 两段状态会互相污染。**缓解：先截图、后审计**（或截图前重置帧状态/重载）；② 两工具耦合。**回归锁**：`test_examples_visual_baseline` + 截图指纹一致性 + 审计发现数不变。
- **工作量**：M–L。

### P2 · 浏览器 / 进程复用（守护进程 or persistent context）
- **问题**：每次 render 起子进程 + 冷启动 Chromium；高频 `--iter` 反复付冷启动。
- **设计**：可选的常驻渲染/校验守护（一个 long-lived headless Chromium，render 通过它跑合并后的 audit+shoot），或 Playwright browser-server / persistent context。**默认关、显式开**。
- **落点**：`assets/` 新增 daemon + render-deck 探测复用。
- **收益**：每轮省冷启动（~0.3–1s+），对高频 `--iter` 累计可观。
- **风险**：状态泄漏（上一份 deck 残留）、daemon 生命周期 / 崩溃恢复。**缓解：每次 `new_context` 干净隔离 + 健康检查 + 失败回落到一次性 launch。**
- **工作量**：L。**优先级取决于 P0 数据**：若 P1 已把 `--final` 降到可接受、且 `--iter` 冷启动占比不高，P2 可缓。

### P3 · 减少"渲染→改→再渲染"循环次数（免费 + 轻护栏）
- **问题**：靠人/agent 自觉用 `--iter`、定稿才 `--final`；易误用（本会话就连跑了多次 `--final`，每次都做全量几何审计 + 起截图浏览器）。
- **设计**：
  - (a) **约定**：中间修复一律 `--iter`；`--final` 只在交付/发布前。
  - (b) **轻护栏**：render-deck 检测"短时间内重复 `--final`"或"`--final` 但侧车显示零改动页"时打**一条提示**（不阻断）。
  - (c) **少踩坑**：强化 renderer 子技能已有的"提前算行高/溢出一遍过"，减少 fix-loop 轮数。
- **收益**：直接砍掉整轮 `--final` 成本，零运行时代价。
- **风险**：极低（护栏只提示）。
- **工作量**：S。

### P4 · 截图并行（降级 / 可选）
- **问题**：`_shoot` 单浏览器顺序逐页。但**增量复用已让"只改几页"只截那几页**，常态收益小。
- **设计**：仅"首版 / 大量新页"全量截图时，用多 context 并行。
- **结论**：**默认不做**；等 P0 证明"首版全量截图"确实是瓶颈再上。
- **工作量**：M。

### P5（验证项，非开发项）· `--final` 跳过未变页截图
- **结论**：**已实现**（`_shoot` 默认增量）。
- **行动**：① 加回归 test 锁住"未变页被 `reuse`、不重截、指纹一致"；② P0 bench 里确认全增量场景确实快；③ 本方案 §0 已写明，避免重复造轮子。
- **工作量**：S（只补测试 + 文档）。

---

## 执行顺序

**P0（bench）→ P5（确认现状 + 锁测试）→ P3（免费护栏）→ P1（合并 load，最高收益）→ 用 P0 复测 → 视数据决定 P2 / P4。**

## 统一验收口径

- 每项用 P0 bench 出 **before/after 中位墙钟**；
- 每项改动后跑**全量测试套件**（`deck-json/tests` + 视觉 baseline），**任何 gate 行为变化 = 不通过**；
- 性能改动**绝不改变校验结论**（同一 deck，优化前后的发现集必须一致）。
