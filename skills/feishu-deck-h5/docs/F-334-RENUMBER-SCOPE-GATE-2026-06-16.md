# F-334 · `--renumber` / 结构性插入 参与 auto-scope(单页改动不再被全量门禁绑架)

> 立项工单 · 2026-06-16 · `deck-json/render-deck.py`
> 同族:F-310(auto-scope 侧车)、F-319(scope-aware 视觉/静态门禁)、F-302(baseline 降级)、F-320(deck-cli scoped 预写 lint)

## 复盘背景

给一份 48 页 deck **插一页案例 + `render-deck.py --renumber`**,结果跑了**全 deck 视觉门禁**,在**别的页早已存在的 15 个 error**(第 2/5/10/35/38 页)上 BLOCKED **并回滚了 index.html** —— 新插的、本身 0 error 的页被无关页面的旧 bug 扣作人质、白白作废重来,还让用户以为「页面没了」。

「单页改动从第一次渲染就该 scoped」本是 F-310/F-319 已建好的能力;这次没接住,是因为 `--renumber` 把安全网显式关掉了。

## 根因(三触发器,缺一不可全修)

1. **结构性插入 → 全量**:`_auto_scope_pages` 用顺序敏感的 `pk != ck` 守卫,任何 insert / delete / reorder / `_disabled` 切换都短路成 "slides added/removed/reordered — full"。**插一页(哪怕不 renumber)就触发**。
2. **`--renumber` 关掉 auto-scope**:`_iter_auto` / `_default_auto` 条件里都带 `not args.renumber` → `scope_pages` 为空 → F-319 的 scoped 降级(键于 `scope_pages` 真值)整段不进。
3. **`screen_label` 进了内容哈希**:`_slide_hash` 哈希整个 slide dict(含 `screen_label`)→ renumber 改了 label 就把每个移位页标成 dirty。

> `screen_label` 仅作为 `data-screen-label` 属性输出;唯一读它的门禁 R02 只查**存在性**、从不看内容,也从不可见/参与样式/被测量(已对 audits.js / validate-deck.py / 模板 全量核实)。所以它**不是受门禁约束的内容**,排除安全。

## 修法(全部在 `deck-json/render-deck.py`,零渲染路径改动)

| # | 改动 | 作用 |
| --- | --- | --- |
| A | `_SIDECAR_SCHEMA` 2 → 3 | 旧侧车经 framework-hash 失配做一次性全量升级(F-310 既有机制),干净失效 |
| B | `_slide_hash` 排除 `screen_label` | label 变动永不标 dirty;diff 只追**受门禁约束**的内容变化 |
| C | `_sidecar_state` 注释更新 | 反映结构性改动改走 by-key diff |
| D | `_auto_scope_pages` 删 `pk != ck` 守卫 | insert/delete/reorder 改 **by-key** diff:只有新增/改动页 dirty;移位但同内容的页字节级一致、不重门禁;`deck_meta`/framework 改动仍全量;无内容变化 → 无 dirty → 便宜全量 |
| E | 决策块去掉 `not args.renumber` | `--renumber`(决策在 renumber 改写**之前**跑)参与 auto-scope;`--final` 仍强制全量 |
| F | 决策块「always win」注释去掉 `--renumber` | 文档对齐 |

**为何天然组合 F-319**:F-319 的静态/视觉降级、`_in_scope()`、F-302 baseline 全部键于 `scope_pages` 真值。本修只让 `scope_pages` 在 insert/renumber 时被设成「真正变化的页」,F-319 的整套降级**自动生效**,无需改门禁代码。

## 验证

- **单元**(`tests/test_auto_scope.py`,新增 6 例 + 改 1):insert 只标新页 dirty / `screen_label`-only 不 dirty / insert+renumber 只标新页 / reorder 同内容不 dirty / disable-off 无内容变化=便宜全量 / 重新启用一页 scope 到它。
- **集成**(`tests/test_renumber_scope_gate.py`,新增,Playwright-gated):runs/ deck 带预存视觉 error + 插一干净页 + `--renumber` → **rc 0、`GATE-COVERAGE scope=auto:2`、renumber 执行、新页在 index.html(未回滚)**;并锁 `--final` 仍全量 BLOCK(rc 4)。
- **迭代环**(`tests/test_iteration_loop.py`,改):结构性 insert 现 scope 到新页(原断言 "added/removed/reordered → full" 已更新)。
- **回归**:auto_scope + iteration + render_gate + baseline_gate + gate_tuning + scoped_audit + hidden_page + renumber_scope_gate + atomic_render + golden + log_digest + readability + deck_cli_smoke = **94 测全过**;golden/digest 证渲染输出与摘要格式字节级不变(本修不碰渲染路径)。

## 已知边界(非本次修复范围)

- **纯 renumber-only-无内容变化的重渲染**:diff 为空 → "no slide changed — full (cheap anyway)" → 仍走全量门禁。属退化场景(没有实质变化),非用户报告的 insert+renumber 路径;`--final` 才是定稿全量门禁,不动。

## 并发说明

- 隔离 worktree `fix/renumber-scope-gate`(off 本地 `4d6450c`,带 F-319);**只改 `render-deck.py` + 3 个测试 + 本工单 + TICKETS 一行**。
- **未碰** 并发 session 正在改的 `audits.js` / `feishu-deck.css`。
- **未 push / 未合**,待用户确认合入时机。
