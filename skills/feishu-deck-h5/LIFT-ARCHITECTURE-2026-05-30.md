# feishu-deck-h5 · Lift 架构重设计与路线图

> **生成日期**: 2026-05-30
> **方法**: 多 agent workflow —— 5 个并行 reader 测绘现状(CSS 注入路径 / scoping 模型 / lift 工具链 / raw slide 自包含度 / slide-library locator)→ 4 个独立架构师按不同切入角出方案 → 1 个对抗式综合。10 agent、~686K tokens、255 工具调用。关键根因(`custom_css` 死字段)由人工直接复核实锤。
> **北极星**: 把"从别的 deck 拎一页到新 deck"从"读两个大文件 + 人肉拆 CSS"变成"复制一个 JSON 对象",代价 ~零 agent token,且不产生破 CSS/资源。

> **📌 本次会话已实现并验证(分支 `lift-architecture`,off main,**未提交,待 review**)**:
> **L1–L6 六步全部落地 + 测试绿**。详见下「落地状态」。仅 L7(存量 codemod + 提 err)deferred(设计已固化在本文档,按 ID 执行)。

---

## 一、根因 —— 每页的 CSS 依赖从未被"记录"

每次 lift 慢、费 token,不是 lift 工具不行,而是**架构上每页没有"自己的 CSS 该放哪"的家**。两个实锤缺陷:

1. **有家但没通水管(死字段)** —— `deck-schema.json:108` 早就声明了 `custom_css`(每页 CSS 容器),注释写着 "ESCAPE HATCH. Per-slide raw CSS scoped under `[data-page=NN]`",但 `render-deck.py` **零次消费它**(全仓库唯一引用就是 schema 那一行)。作者无处可放 → 只能把每页定制 CSS 塞进 `<head>` / page-level `<style>` 块 → 那些块**不在 slide 的 DOM 里**,reorder/republish 时静默蒸发(`fs-deck-page-anim` 丢失 bug,memory 记过两次)。
2. **没有语义目录** —— deck.json 查不到"第几页是什么",所以 lift 一页必须:① 读完整源 `index.html`(24KB~1.2MB)数 frame 号 → ② 读 3491 行 `feishu-deck.css` 判断哪些规则作用于这页。98% 读进来的 CSS 与这页无关,但不读全就不敢断言"齐了"。

> framework 那张共享大表(`feishu-deck.css`)本身没问题、**永远共享、永不参与 lift**。问题 100% 在「未被记录的每页偏差 CSS」+「缺发现目录」。

---

## 二、双轨架构(不是二选一)

| 轨 | 对象 | 机制 |
|---|---|---|
| **生成期自包含** | **新 deck** | 每页 CSS 进 `custom_css` → 渲染器 scope 到 slide-key 并 co-locate 进 slide → lift 退化成 JSON 对象复制。一次投入,永久零成本。 |
| **抽取期 tree-shake** | **老/外来 deck** | 工具在 Python 进程内做 CSS 拆分,agent 一个大文件都不读。 |

两轨**共用一个 CSS parser(`_css_utils.py`)+ 一条 validator 契约**,不会漂移。

### 六个部件

- **A · 接通死水管**:`render-deck.py` 消费 `custom_css`,渲染成 `<style data-slide-key=K data-fs-custom-css>` 作为 `.slide` 第一个子节点;作者写无前缀选择器,渲染器自动 scope;`[data-page=NN]`→`[data-slide-key=K]` 重写。**结构性消灭 page-anim 蒸发 bug**(head 里再无每页 CSS 可放)。【L2 ✅】
- **B · 共享 parser `_css_utils.py`**:`iter_css_rules`(从 lift-slides 移出)+ `scope_selectors(css,key)`,处理 @media/@supports 递归、@keyframes/@font-face verbatim、逗号分组、已 scope 幂等、`.slide` 根合并、`&` 语法。render-deck + lift-slides 同源。【L1 ✅】
- **C · 发现目录 `slide-index.json`**:渲染顺手吐 `{key→frame_index,layout,label,assets,bytes}`;lift 工具加 `--index`(外来 deck 流式出表)+ `--key` 选页。agent 从 ~300 token 表挑页,不读 HTML 正文。【L4 ⏸】
- **D · tree-shaker 通用化**:`lift-slides.py` 从硬编码 5 个 `HEAVY_FRAMEWORK_LAYOUTS` 扩到全 15 layout + DOM-class 扫描 + `@keyframes`/`var()` 闭包,偏向过包含(宁多几百字节不破图),`--shake` 门控,只给外来/老 deck。【L6 ⏸】
- **E · deck.json 原生 lift**:`deck-cli.py paste --from SRC --key K`,复制自包含 slide 对象 + 拷 input/prototypes 资源,key 冲突自动改名。新 deck 默认路径,零 HTML 解析。【L3 ✅】
- **F · validator `R-SELF-CONTAINED`**:复用 `_iter_style_blocks`,① head/page `<style>` 引用 slide-key → ERROR(page-anim 反模式);② raw slide 用了无 scope 规则也无 framework 规则的 class → WARN;③ 带 `lifted` 的页断言子树 class 全覆盖。先 WARNING,扫完存量再提 ERROR。【L5 ⏸】

---

## 三、落地状态(L1–L7)

| ID | 内容 | 量级 | 状态 |
|---|---|---|---|
| **L1** | `_css_utils.py`(`iter_css_rules` + `scope_selectors`)+ 17 单测;`lift-slides.py` 改用同源 parser | M | ✅ **本次完成** |
| **L2** | 接通 `custom_css`:scoped 注入 `.slide` 首子;`[data-page]`→`[data-slide-key]` 重写;`sync-index-to-deck.py` 跳过该块保 round-trip;schema 描述更新 | M | ✅ **本次完成** |
| **L3** | `deck-cli.py paste --from … --key … [--new-key] [POS]`:对象复制 + 资源拷贝 + key 去重 + `data-text-id` 剥离 + `lifted` 溯源 + 自动备份/复校 | S | ✅ **本次完成** |
| **L4** | 渲染吐 `slide-index.json`(key→frame_index/layout/label/bytes/assets);`lift-slides.py --index` 出外来 deck 清单 + `--key` 按 slide-key 选页(legacy 位置参数仍兼容) | S | ✅ **本次完成** |
| **L5** | `R-SELF-CONTAINED` validator(`warn_soft` 非阻塞):head/deck 级 `<style>` 引用 `[data-slide-key]`/`[data-page]` 且在 slide 外 → 报告 page-anim 泄漏;framework + in-slide 块豁免;`--strict` 也不升级(到 L7 codemod 后再提 `err`) | M | ✅ **本次完成** |
| **L6** | tree-shaker 通用化(`lift-slides.py --shake`):`[data-layout=X]` 抽取从硬编码 5-heavy 扩到**该 slide 真实 layout(任意 ~15,含 extra-layouts/patterns 三表)** + **source-head `@keyframes` 闭包**(按 slide 引用拉回会蒸发的 page-anim keyframes)。**故意不做全局 class 扫描**(经实测 `.ns-card`/`.north-star-map` 等是全局 `.slide .foo` 规则,任何 link feishu-deck.css 的目标 deck 都在,无需内联,避免特异性/retheme 风险)。无 `--shake` 时对非 heavy layout 打印 hint;legacy 行为不变 | M | ✅ **本次完成** |
| **L7** | `migrate-head-css-to-custom-css.py` codemod + head-leak 提 ERROR + SKILL.md/editing-discipline.md 更新(退役 data-page 指引) | L | ⏸ deferred(需决策 1 拍板 + `.bak`) |

**本次改动文件**(分支 `lift-architecture`,未提交):
- 新增 `deck-json/_css_utils.py`、`deck-json/tests/test_css_utils.py`
- 改 `deck-json/render-deck.py`(+`_inject_custom_css` + `slide-index.json` 吐出)、`deck-json/deck-cli.py`(+`paste`)、`deck-json/sync-index-to-deck.py`(round-trip 跳过 custom-css 块)、`deck-json/deck-schema.json`(`custom_css` 描述)、`assets/lift-slides.py`(改用同源 parser + `--index`/`--key`)

---

## 四、改造后的 lift 流程 + token 对比

**原生 deck(新规矩,常态):**
```bash
deck-cli.py SRC/deck.json show <key>                                  # 看一个 ~2-4KB slide 对象(可选)
deck-cli.py DST/deck.json paste --from SRC/deck.json --key <key> [POS]  # 复制对象 + 拷资源 + 去重 key
render-deck.py DST/deck.json DST/out                                  # 自动输出 <style data-slide-key=…>;framework 本就 linked
```
**外来/老 deck(无 custom_css,需 L4+L6):**
```bash
lift-slides.py --index SRC/index.html                                 # ~300 token 目录表,挑 key
lift-slides.py --shake --key <key> SRC/index.html DST/deck.json       # tree-shake 在进程内跑,agent 只读 ~1KB 报告
```

| | 现在 | 改造后 |
|---|---|---|
| 找页 | 读完整 `index.html`(~6K~300K token) | 读目录表(~300 token,与 deck 大小无关) |
| 取 CSS | 读 3491 行 `feishu-deck.css`(~2.4K token)再人肉筛 | **0** —— 原生自带 / tree-shaker 在 Python 里做 |
| 进 agent 上下文的大文件 | `feishu-deck.css` + 整个源 `index.html` | **都不进** |
| 净收益 | — | 小 deck ~10×,1.2MB 大 deck ~99.8%,成本变 O(1) |

---

## 五、5 个决策(已按建议拍板)

1. **`data-page→data-slide-key` 迁移按渲染顺序映射** —— L7 codemod 时确认渲染顺序唯一、无手工错号 deck;跑前强制 `.bak`。本次 L2 的重写支持「作者写 `[data-page=NN]` 也能用」做后向兼容,**但不动存量已渲染 deck**(那是 L7)。
2. **head-leak 检查何时提 ERROR** —— L5 先发 WARNING,L7 codemod 扫完存量再提 ERROR(早提会误伤未迁移老 deck)。
3. **deck head 共享的 `@keyframes`/`@media`** —— 原生路径:作者把引用的 @-规则写进该页 `custom_css`(`scope_selectors` 已对 @keyframes verbatim、@media 递归);外来路径由 L6 闭包处理。**约定:跨页共享动画不放 head,放各自 custom_css**(单页自带,牺牲一点重复换自包含)。
4. **资源路径坐标系** —— `paste` 把 `input/`、`prototypes/` 拷到目标 deck 同名目录,路径保持 **deck 相对**(`input/<file>`),天然 target-relative;skill-relative `../../../skills/…` 在两 deck 同深度等价,无需改写;feishusolution 部署的 `assets/<file>` 改写仍由 copy-assets/finalize 负责(不变)。
5. **P2 的从零 CSS 选择器引擎** —— **不做默认**(450 行手写引擎,误匹配即破图,风险最高)。L6 用「过包含的 layout+class 抽取」达同等 token 收益、风险小得多;手写引擎仅留作未来 `--minimal` 模式,等「内联 CSS 膨胀」成可测量问题再说。

---

## 六、验证证据(本次 L1–L6)

- `pytest deck-json/tests/test_css_utils.py` → **17 passed**(逗号组 / @media 递归 / @keyframes verbatim / 已 scope 幂等 / `[data-page]` 重写 / `.slide` 根合并 / `:is()`·`[attr]` 逗号陷阱)。
- `pytest deck-json/tests/` 全套 → **155 passed**(无回归)。
- custom_css 端到端:含 custom_css 的 templated(content/3up)+ raw 两类 slide 渲染 → validator **0 err / 0 warn**;`.card`→`.slide[data-slide-key="K"] .card`、`.slide` 根正确合并(非 `.slide .slide`)、`@keyframes` 未被 scope;style 为 `.slide` 首子;`sync-index-to-deck --dry-run` 报 **no drift**(round-trip 干净)。validator 还正确抓到测试里的 bad token `var(--fs-h1)`(R-CSSVAR)—— 证明注入块被正常校验。
- `paste` 端到端:跨 deck travel(3 个 custom_css 块进目标渲染)、key 冲突自动 `→ -2`、`data-text-id` 剥离(避 T03)、目标 deck **render exit 0**;schema 自动复校 + `.bak` 备份。
- 既有 `examples/sample-deck.json` 渲染 exit 0(render-deck.py 无回归);`lift-slides.py` 改用同源 parser 后 `--help` + `iter_css_rules` 仍工作。
- **L4**:渲染吐出的 `slide-index.json` 含 key/frame_index/layout/variant/label/bytes/assets;`lift-slides.py --index` 打印外来 deck 清单;`--key three-pillars` 正确解析到 frame 2 并 lift;**legacy 位置参数 `SRC 1 DST` 仍兼容**(连 cover 的 framework CSS 自动内联也照旧);missing-key 报错 + 显示清单 + exit 1;加 sidecar 后 **155 测试仍全绿**(copy-assets / package-deliverable 不受影响)。
- **L5**:`R-SELF-CONTAINED` 5 个 must-fire/must-not-fire 单测全过(head `[data-slide-key]` 泄漏触发 / `[data-page]` 触发 / co-located `data-fs-custom-css` 不触发 / framework 块不触发 / 无 per-slide 选择器不触发);co-located custom_css 的 deck A 校验 0 触发;注入 head 泄漏后触发 `warn_soft` 但 **exit 0(`--strict` 也 0,不阻塞)**;补 FAMILIES + `validator-rules.md` 文档后 **F-03 治理测试通过**,合计 **160 测试全绿**;扫 runs/ 下 9 份 deck **0 误报**(只针对真正的 head 泄漏,对已自包含的 deck 静默)。
- **L6**:构造外来源 deck(CSS 在 head,无 custom_css)实测:① 非 heavy 的 `content-3up` 不带 `--shake` → 打印 shake hint、不内联;② 带 `--shake` → 该 layout CSS 内联并 rescope 到 slide-key(753→5319 bytes);③ 带 `--shake` lift 引用 `myfade` 动画的 slide → 从 head 拉回 `@keyframes myfade`;把两页 `--shake` lift 进真 deck 后 **render exit 0 / 0 err 0 warn**,rescoped CSS + pulled keyframe 都在产物里;**back-compat:legacy `SRC 1 DST`(cover heavy)无 `--shake` 仍自动内联**;**160 测试全绿**。

---

## 七、下一步

- **合并 L1–L6**:本分支 `lift-architecture` 待 review;确认后 squash/合 main。
- **仅剩 L7(L · 需你拍板)**:`migrate-head-css-to-custom-css.py` codemod —— 把存量 deck 的 head/page `<style>` per-slide 规则按渲染顺序搬进对应 slide 的 `custom_css`(决策 1:确认渲染顺序唯一、无手工错号;跑前 `.bak`)。完成后把 `R-SELF-CONTAINED` 的 head-leak 检查从 `warn_soft` 提成 `err`(决策 2)。这是唯一需要你点头的破坏性步骤,故 deferred。
- **SKILL.md 同步已完成**(本会话):新 lift 正道已写进 SKILL.md「LIFTING」+ `references/round-trip-integrity.md` + `references/prototype-embed.md` + `DECK-CLI-README.md` + `references/validator-rules.md`。
