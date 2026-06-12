# 方案 · feishu-deck-h5 迭代循环提速(iteration-loop)

> 2026-06-11 · 基于 FWD deck(runs/20260610-185242-fwd-founder-ai-layer)53 轮渲染的实测复盘。
> 工单编号已对账回填 `docs/TICKETS.md`(2026-06-12:F-300~F-302 属本计划;F-303/304 已被 fast-text/shoot-page 领走)。新号一律去 TICKETS.md 领,勿再从此处推算。

## 0. 背景与实测

**管线不是瓶颈,循环才是。** 20 页 deck 实测:

| 路径 | 耗时 |
|---|---|
| 全量渲染 + 全审计(static+visual+geometry+distribution) | **6.1s** |
| 同上 + deck-log autosnapshot | **9.6s** |
| `--scope 1` 单页 | **3.9s** |

而该 session 53 轮成功渲染、净工作 ~351min → **平均 6.6min/轮,渲染计算只占 ~3%**。
其余开销全在 agent 循环侧,按浪费排序:

1. **每个小改动现写一次性 heredoc python 注入脚本** → ~25 个脚本、3–4 次 bash 引号/反引号炸弹、每次失败 = 一个完整回合。
2. **渲染输出不落盘** → 被 GATE BLOCK 时 grep 丢失 ❌ 段,**整轮重渲只为看报错**(8–10 次)。
3. **新页首渲门禁必挂**(~10 次):非阶梯字号 18/20/21/22px、abs-pos 双锚、base64 进 `<style>` 触 P50、非 chrome 类 16px 文本——全是写入前可静态查出的已知规则。
4. **过度读图**:每轮 Read 整张 1920×1080 截图验证(token+延迟大户),纯文案改动也读图。
5. **`--scope`/`--quick` 存在但从未被用**;`DECK_LOG_NO_AUTOSNAP` 同。"记得用"靠不住。
6. **cd 漂移**:相对路径渲染失败 6 次。
7. **绕开 deck-cli 直接 python 改 deck.json** → 自动放弃了 deck-cli 已有的乐观锁,撞上并发 session 冲掉 data-lifted 等,3–4 轮返工。

## 1. 设计原则

- **把"agent 纪律"固化为"工具默认行为"**。靠 agent 记得用 flag 的优化等于没有(本场 --scope 就是证据)。代码 > 文档 > 记忆。
- **正道唯一**:编辑 deck.json 只走 deck-cli(它已有锁、备份、确认);本方案补齐它缺的口,然后把绕行列为反模式。
- **左移**:能在写入前静态查出的错误,不允许活到渲染门禁。
- **验证按成本分级**:文本回显 < 缩略图 < 全图;按改动类型选最便宜的够用档。

## 2. 目标态:Canonical Edit Loop(一图流)

```
写/改 fragment 文件 (input/<key>.body.html / <key>.css)
        │
        ▼
deck-cli <deck.json> set <key> --html f.html --css f.css     ← W1 补口
        ├─ 自动静态预检 lint-fragment(字号阶梯/双锚/P50…)    ← W4,FAIL 拒写
        ├─ 乐观锁(已有)防并发覆盖
        ▼
自动 scope 渲染(只审变更页,~4s)                              ← W3
        ├─ stdout:≤12 行 digest(PASS/FAIL + 每错一行)        ← W2
        ├─ 完整日志:output/last-render.log(覆盖式)           ← W2
        ├─ 变更页可见文本回显(纯文案改动到此为止,零图)        ← W5
        ▼
需要看版式 → 读 sNN.thumb.png(~640px 缩略图)                 ← W5
        ▼
交付前:render --final(全量审计 + autosnapshot + 严格 GATE)   ← W6
```

## 3. 工作项

### W1 · deck-cli 编辑通道补口:`--from-file` / `--html` / `--css`
- **问题**:`set` 走 argv 传值,塞不进 100KB 的 data.html → agent 被迫裸写 python。
- **改动**:`deck-json/deck-cli.py`
  - `set <key> <dotted-path> --from-file PATH`(通用);
  - 快捷:`set-page <key> [--html F] [--css F] [--lifted] [--title S]`(一次设 data.html / custom_css / lifted / data.title);
  - 全部走既有 optimistic-lock 与 .bak 备份。
- **验收**:`deck-cli deck.json set-page the-shift --html body.html --css page.css` 单命令完成注入;并发被改时拒写并提示重读。
- **工时**:0.5d。

### W2 · 渲染输出落盘 + 紧凑 digest(杀"重跑看报错")
- **问题**:无日志文件;BLOCK 详情埋在长输出里被 grep 吃掉 → 重渲只为看错。
- **改动**:`deck-json/render-deck.py`
  - 每次渲染完整输出写 `output/last-render.log`(覆盖式,含 GATE-COVERAGE 与全部 findings);
  - stdout 默认只打 digest:`PASS/FAIL · N errors · N warnings`,每条 **error** 一行(`slide N · RULE · selector · 一句修法`),BLOCK 时 error 段置顶;末行打 log 路径;`--verbose` 恢复现行为。
- **验收**:BLOCK 场景不需要第二次渲染即可定位全部 error。
- **工时**:0.5d。

### W3 · auto-scope:把 `--scope` 从"记得用"变"默认"
- **问题**:--scope 全程没被用;且需要 agent 自己算页码。
- **改动**:`render-deck.py`
  - 维护 sidecar `output/.slide-hashes.json`(每页 `hash(data+custom_css+layout+allow+lifted)`);
  - 默认 diff 上次 → 隐式 `--scope <变更页>`;新增/删除/重排页、deck 级字段变更、sidecar 缺失 → 自动回退全量;
  - `--full` 强制全量(交付);GATE-COVERAGE 行如实标 `scope=auto(3,7)`;
  - deck 级一致性规则(distribution / R-DECK-*)在 scope 模式下降级为一行提示:"M 页未复审,交付前 `--final`"。
- **风险**:跨页一致性规则依赖全量视野 → 用上面的降级提示兜底,不做静默跳过;`--strict-baseline` 语义保持。
- **验收**:单页小改零参数 ~4s;改 deck.title 等全局字段自动回退全量。
- **工时**:1–1.5d(含 sidecar 失效矩阵的测试)。

### W4 · 写入前静态预检 `lint-fragment`(左移 80% 首渲失败)
- **问题**:首渲门禁失败 ~10 次,全是文本可查的已知规则。
- **改动**:新增 `deck-json/lint-fragment.py`(纯文本,无浏览器,<1s),并作为 W1 `set-page` 的 pre-write 钩子(FAIL 拒写,`--force` 绕过):
  - `font-size` ∉ 阶梯 {16,24,28,48} ∪ hero 白名单尺寸,且无 `data-allow-typescale` 祖先提示;
  - abs-pos 同设 top+bottom(或 `inset:0`)且非 `data-allow-dual-anchor`;
  - `<style>`/custom_css 内 base64 累计 >250KB(P50 预警在写入时就报);
  - 16px 文本挂在非 chrome 白名单类上(对照 audits.js 的 `VIS_CONTENT_CHROME_CLASSES` 单一来源,**勿复制清单,import/读取同一份**);
  - `url()` 引用本地大图(>500KB)提示走资产链接(见 W8)。
- **口径**:预检是**子集**,不替代门禁;规则表与 audits.js 共享常量,禁止两处维护。
- **验收**:对本场 10 个历史失败用例回放,≥7 个在写入前被拦截。
- **工时**:1d。

### W5 · 廉价验证物:文本回显 + 缩略图
- **问题**:agent 每轮读全尺寸截图,token/延迟大户;纯文案改动也读图。
- **改动**:
  - render digest(W2)末尾附**变更页可见文本回显**(渲染后 DOM 的该页 innerText,≤15 行)→ 文案改动零图闭环;
  - `log-tool/deck-log.py` snapshot 每页同时产 `sNN.thumb.png`(宽 640);digest 打印 thumb 路径,引导优先读小图。
- **验收**:文案类改动整轮无 image Read;读图轮 token 降 ~60%。
- **工时**:0.5d。

### W6 · 迭代/交付双档 profile
- **改动**:
  - `render-deck.py --iter`:= auto-scope(W3)+ `DECK_LOG_NO_AUTOSNAP` + digest 输出;
  - `render-deck.py --final`:= `--full` + autosnapshot + 完整审计 + 严格 GATE(等价现默认);
  - 缺省行为 = `--iter`?**不**——缺省保持现状(安全),W1 的 `set-page` 内部调 `--iter`,交付路径(delivery/publish 文档)写死 `--final`。
- **验收**:迭代轮端到端 ≤5s;`--final` 与现行为 bit 级一致。
- **工时**:0.5d。

### W7 · SKILL.md「Canonical edit loop」+ 反模式声明
- **改动**:
  - renderer / editor 子技能各加一节:上面的一图流、绝对路径要求、"绕开 deck-cli 直接脚本改 deck.json = 反模式(丢失锁/备份/预检)";
  - controller SKILL.md 的 Shared Contracts 加一行:slide 级编辑唯一写通道 = deck-cli;
  - 可选加固:仿 validate-deck-write 思路,PostToolUse hook 对"直接 Write/Edit deck.json"提 warning(不 block,因为批量迁移脚本仍属合法)。
- **工时**:0.5d(hook 另 +0.5d,可选)。

### W8(可选)· `deck-cli add-asset`:资产入位一条龙
- **问题**:agent 手工 sips 压缩 + base64 内联(P50 风险 + deck.json 膨胀到 2.5MB)。
- **改动**:`add-asset <file> [--max-width N] [--quality Q]` → 压缩落 `output/input/`,打印相对引用路径;配合 W4 的大图提示形成闭环。
- **工时**:0.5d。

## 4. 不做(non-goals)

- 不改审计规则本身、不动 P50 阈值、不放松门禁;
- 不做渲染并行化/缓存浏览器常驻(6s 已够快,复杂度不值);
- 存量 deck 的 base64 → 链接资产迁移不进本方案(独立 hygiene 工单);
- 不做"自动攒批改动"(那是 agent 行为,工具侧由 W1 单命令 + W3 auto-scope 把攒批的收益变小,降低必要性)。

## 5. 落地顺序与依赖

```
W2(独立,最小) → W1 + W4(同一 PR:编辑通道+预检) → W3(核心) → W5 → W6 → W7(文档收口) → W8(可选)
```

总工时粗估 4.5–5.5d。W2/W1/W4 先行即可吃掉本场 ~60% 的浪费形态(失败回合 + 重跑看错 + 首渲挂)。

## 6. 预期收益(按本场数据折算)

| 浪费形态 | 现状(53 轮 session) | 方案后 |
|---|---|---|
| 失败 Bash 回合(cd/引号/heredoc) | ~15 回合 | ≈0(单命令 + 绝对路径文档) |
| 重渲看报错 | 8–10 次 | 0(last-render.log) |
| 首渲门禁挂 | ~10 次 | ≤3(预检左移) |
| 读图 token | 每轮全图 | 文案轮 0 图;版式轮 thumb(-60%) |
| 单轮端到端(agent 侧) | ~3–4 min | **~1–1.5 min** |

## 7. 验收回放集

用本 session 的真实失败做回归:
1. `the-shift` 77px/50px typescale + `.kicker` 16px + `inset:0` 双锚 → W4 应全拦;
2. `craft-iceberg` base64 进 `<style>` 545KB(P50)→ W4 写入时报;
3. `four-engines` os-strip top+bottom 双锚 → W4 拦;
4. `bytedance-blueprint` data-lifted 被并发冲掉 → W1 锁 + `lifted:true` 字段路径,复现应拒写并提示重读;
5. 任意单页文案改 → W3+W5:~4s digest + 文本回显,全程零图、零全量审计。
