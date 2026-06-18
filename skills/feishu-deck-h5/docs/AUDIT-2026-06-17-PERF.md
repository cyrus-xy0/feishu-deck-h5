# AUDIT-2026-06-17 · 生成流水线性能审查(PERF) — 落地状态

> **本分支(`perf-pipeline-audit`, off `origin/main`)已实现并验证 2 项:**
>
> - **PERF-0 标尺** `assets/bench-render.py` —— 分段计时管线(chromium 冷启动 / render_advisory / validate_static / validate_visual_json / validate_visual_nocache / check_distribution / deck_cli_set),≥N 次取中位,出 JSON,带 `--compare baseline.json` 增量对比。后续所有 PERF-* 改动的 before/after 都用它。**实测 50 页 deck**:render_advisory **5480ms / 3 chromium**(印证头条)、validate_visual_json 3834ms、check_distribution 1028ms。
> - **PERF-A CJK 字体探针 per-host 缓存** `assets/validate.py::probe_effective_cjk_font` —— 键 = `sha256(feishu-deck.css 字节) + 本机字体指纹(font 目录文件名/mtime/size 哈希)`。缓存命中**不再起 chromium**。**实测**:`validate --visual --json` 4357ms → 3834ms(**−523ms / −12%**);advisory render ~5.86s → 5.48s;探针结果**逐字一致**(live=cold=warm=`方正兰亭黑Pro_GB18030`);改 CSS 字节或装/卸字体 → key 变 → 自动 re-probe;`test_font_fingerprint.py` 11/11 + `test_imported_deck_fonts` 过。bypass 开关 `DECK_NO_FONT_PROBE_CACHE=1`(parity 测试用)。探针是 metadata 永不作 gate,缓存**不可能翻任何 verdict**。
>
> **⚠ 编号更正(重要)**:正文多处把本审查挂到 **F-327**,那是从主 checkout 一份**未提交的本地 doc**(`PERF-OPT-PLAN-2026-06-16.md`)读来的 —— 在 `origin/main` 上 **F-327 实为「publisher/importer 闸门加固」**(典型撞号漂移)。故本分支**不占用 F-327**;PERF-0 / PERF-A 的正式工单号在**合并时现读** `git show origin/main:skills/feishu-deck-h5/docs/TICKETS.md` 再领(本地已用 F-334、scope 分支已用 F-335,真·next-free 需现读)。PERF-0/PERF-A **不是 validator 规则**,不触 rule-coverage 闸,无需同步 audits.js / FAMILIES / business-rules.yaml / validator-rules.md。
>
> **PERF-B(共享浏览器编排器)= 已 DEFERRED 的 F-290**(用户 2026-06-10 裁决:风险>收益,理由含「F-255 的 --scope 已稀释慢只剩不常跑的全量」)。本分支**未实现**,尊重该裁决。但本次基准给那条理由一个**反证**:实测 `--scope` 只省 ~200ms(goto+settle 仍 load 全 50 页 DOM),且**默认** advisory render 就付 3 次 chromium 冷启动(并非「只剩不常跑的全量」)。是否重启 F-290 由用户裁决;正文 §3🟡 `PERF-B′` 列了落地所需的 settle 一致性护栏 + 差分门。
>
> *以下为审计原始报告全文(由 65-agent workflow 产出:9 段本机基准 + 22 候选 × 双对抗核查)。正文内出现的 “F-327” 字样按上文更正理解。*

---

# AUDIT-2026-06-17 · 生成流水线性能审查(PERF)

> 审查对象:`skills/feishu-deck-h5` deck **生成流水线**(render → schema → 视觉门量像素 → 分布门 → 截图/snapshot)的墙钟。不含 LLM 创作阶段,不含成品 deck 运行时性能(P50–P55,另一回事)。
> 审查方式:9 段本机基准(`chromium 冷启动 / python import / advisory render / --visual render / 独立 validate / 独立 check-distribution / deck-cli 写 / 复合 render vs 部件之和 / auto-snapshot`,每段 2–7 次取中位)+ 22 个优化候选,每个经 **perf-skeptic + correctness-skeptic** 双对抗核查(real_savings / breaks_accuracy / breaks_richness 三轴投票)。夸大的省时与破坏校验/丰富度的候选已在核查环节剔除或降级。
> **铁律(贯穿全文)**:性能优化**绝不削任何一条 check、绝不删任何内容**。同一 deck,优化前后的**发现集(codes/slides/severities)与渲染产物必须逐字一致**。任何会让 gate 静默漏掉缺陷的候选一律进 🔴。
>
> **编号基线**:本报告与既有 **F-327**(`PERF-OPT-PLAN-2026-06-16.md`,重启 DEFERRED 的 F-290「6b/6c 会话合并」)**同主题**。本审查是 F-327 的「P0 量化 + 候选定级」交付物,**不另起总号**;下方逐条工单为 F-327 的子项落点(领正式号时按 `git show origin/main:.../TICKETS.md` 现读 next-free)。

---

## 1. 执行摘要

**墙钟被「在同一份已渲染 `index.html` 上反复付 Chromium 冷启动 + 整份 load+settle」吃掉,而不是审计逻辑本身。** 一份 50 页 runs/ deck 的默认 advisory render ≈ **6.4s 付 3 次 Chromium 冷启动**(6b 引擎 + CJK 字体探针 + 6c 分布),带 auto-snapshot 的**真实生产路径** ≈ **8.7s 稳态付 5 次冷启动**(首版 ~30s)。复合时间≈各部件之和(388+4217+1081ms…),**证明零浏览器共享**。每次冗余的整份 load+settle ≈ **906ms + 370ms 冷启动**。

五个最大的、**不削一条 check 的**净空间:

1. **共享一个浏览器+页面跑 6b 引擎 / 字体探针 / 6c 分布三趟** —— 同一份 DOM 只 load 一次,`audits.js` 与 `MEASURE_JS` 两个 eval 在同一页跑。回收 **~0.7–1.2s/render**(乐观口径 ~2s;perf-skeptic 砍到 0.7–1.2s,字体探针已被 F-293 优化为合成页、不能靠共享消除,只能 memoize)。这是 F-327 P1 的核心,但收益被原方案高估,需以 P0 实测复核。
2. **CJK 字体探针 per-host memoize** —— `validate.py:333` 每次 `--visual --json` 都为一个**与 deck 无关、与机器字体绑定**的合成页起一整个 Chromium(414ms)。结果对本机每个 deck/每次 render 都相同 → 缓存即省,**但缓存键必须含 host 字体安装态**(否则装/卸字体后探针撒谎,正是它要诊断的场景)。
3. **去重 check-distribution** —— 它在「6c 门 + snapshot 内」**每次 logged render 跑两次**同一份 html(~1.08s 一趟)。但 correctness-skeptic 发现:6c 写 sidecar 后、snapshot 读之前 **`index.html` 被 copy-assets 原地改写**,内容哈希必然 miss → 简单 sidecar 复用方案省 0。要省得改成「snapshot 复用 6c 已在内存的结果 / 或哈希落在 copy-assets 之后」。
4. **首版 50 张 baseline 截图** —— 单次最大一次性成本(~23.6s),且无改动的增量 snapshot 仍开 2 个 Chromium。可并行(K 路)到 ~8–11s,但属一次性、非热路径。
5. **`--shake` lift 的灾难性正则回溯** —— 已是**潜在多分钟假死**;但核查确认 **`lift-slides.py:402` 的 bail-guard 已经在源码里(两条子句 + F-332 注释)**,该候选**已落地**,残留只剩「把规则切到 `<style>` 块体」这条加固。

被两位 skeptic 一致打回的(详见 🔴):`deck-cli` 在进程内校验、render 子进程在进程内化、引擎内 R10/spread/css-parse 微优化(全 <1% 且部分破坏 message/几何语义)、batch 模式(scope-union 弱化 gate)、gate-skip-by-hash(key 不覆盖 audits.js → 静默漏新规则)、adaptive-settle(无可靠 layout-settled 信号 → 假阳/假阴)、persistent-browser(无损但收益 ~0.37s 且引入 stale-DOM 陷阱)。

---

## 2. 瓶颈画像(基准实测,按对默认 50 页 render 的影响排序)

| # | 环节 | 墙钟(中位) | Chromium 次数 | 是否冗余 / 备注 | 证据 |
|---|---|---|---|---|---|
| 1 | **advisory render(默认,无 --visual)** | **6358ms** | **3** | 复合≈部件之和(388+4217+1081)→ 零浏览器共享 | `render-deck.py:3201-3215`(6b)/`:3426-3431`(6c) |
| 2 | **render + auto-snapshot(真实生产路径,runs/ 自动建 log/)** | **8669ms 稳态 / 29882ms 首版** | **5** | 5 趟同一 html:6b+字体探针+6c + snapshot 的 _shoot + **第 2 次 check-distribution** | `render-deck.py:2137-2146`(自动建 log/)/`deck-log.py:512,580` |
| 3 | `--visual` render(干净 deck) | 5474ms(被拦 deck 2 次 / 干净 3 次) | 2–3 | 与 advisory 同形(6b 在 --visual 下被跳,改由静态门 `:3079` 带 --visual);非「双跑引擎」 | `render-deck.py:3079-3087, :3511` |
| 4 | 独立 `validate.py --visual --json`(整 deck) | 4009ms | 1(human)/2(--json) | **一个 Chromium 量全 50 帧**(对的);--json 多的 1 个=字体探针 | `run-audits.py:1071-1137` / `validate.py:368-369` |
| 5 | — 其中 engine pass 本体(50 帧 audits.js) | ~3.7s(eval ~0.58s + 固定 bootstrap ~1.3s) | — | **合法重活,已是单浏览器整 deck**,不是 per-page | `run-audits.py:1136` |
| 6 | — 其中 CJK 字体探针 | 414ms | 1(独立) | **deck 无关、host-only、每次 render 一致 → 纯浪费** | `validate.py:350-388`(F-293 合成页) |
| 7 | 独立 check-distribution.py(整 deck) | 1081ms | 1 | 与 run-audits bootstrap 字节级雷同,可共页 | `check-distribution.py:351-390` |
| 8 | auto-snapshot 首版(50 张逐页截图) | 23600ms | 2 | 单次最大一次性成本;增量(0 改动)仍 2300ms / 2 Chromium | `deck-log.py:543-568` |
| 9 | Chromium 冷启动(空 headless 起+关) | 372.7ms | 1 | **每趟都付的单位税**;真实每趟≈906ms(reload+settle)+370ms | benchmark #1 |
| 10 | python import 冷启动(render-deck 模块) | 106ms(裸解释器 33.8) | 0 | 每 render spawn ~5-7 子进程 × ~40-100ms ≈ 0.3-0.7s 进程税 | benchmark #2 |
| 11 | deck-cli set / paste(写操作) | 472 / 460ms | 0 | **便宜**,1 个 schema-validate spawn;迭代成本由后续 render 主导 | `deck-cli.py:291` |
| 12 | `--scope` 引擎 | 仅省 ~200ms(3.5s vs 3.7s) | — | goto 仍 load 全 50 页 DOM、settle 固定;只 eval 缩小 | `run-audits.py` |
| 13 | `--quick` | ~1.0s / 0 Chromium | 0 | **跳过几何+视觉+分布门** → 仅中间文案编辑,**不可当交付门** | `render-deck.py:3466-3491` |

**一句话**:合法重活(50 帧 audits.js,单浏览器)只占一趟;真正的税是 **~1.3s/趟的冷启动+load+settle 被付了 3–5 次**,外加一个 414ms 的 deck-无关字体探针每次重起浏览器。

---

## 3. 推荐优化(分级)

### 🟢 净赚(零风险,立即做)

这些经两位 skeptic **都判 none/none 风险或已自带 fail-safe**、且省的是可证明的浪费。

---

#### [PERF-A] CJK 字体探针 per-host memoize(键含 host 字体态)
- **改什么**:`validate.py:333 probe_effective_cjk_font`,在 `:368` 起 Chromium 前先算 `key = sha256(feishu-deck.css 字节)` **+ host 字体安装指纹**(粗签名,如 `fc-list` 哈希或 canvas 探针缓存),查 `~/.cache/feishu-deck-h5/cjk-font-probe.json`;命中直接返回缓存的 `effective_cjk_font`,**不起浏览器**;miss 跑现有探针并写回。
- **为什么快**:探针加载一个**合成、与 deck 无关**的框架 CSS-only 页(`validate.py:350-367`),结果只取决于框架字体栈 + 本机字体,对本机每个 deck/每次 render 都相同(benchmark #6 实测 414ms、deck-invariant)。`pass` 只看 `iss.errors`(`validate.py:641`),探针是 metadata、**永不是 gate**(docstring `:343-344`)→ 缓存**不可能翻任何 verdict**。
- **预计省**:~0.4s/`--visual --json`(默认 advisory 6b 路径 + 每个 --json 门),首跑后 warm;CI 多 deck 扫一遍后基本全 warm。
- **涉及文件**:`assets/validate.py`
- **验证方法**:2-3 个 deck 跑 --json,断言 `effective_cjk_font` 与无缓存逐字一致、第二次 Chromium launch 数 -1;**改 feishu-deck.css → 必须 re-probe(miss)**;**模拟装/卸 CJK 字体 → 必须 re-probe**(这是 correctness-skeptic 的硬要求:CSS-hash-only 键会在「装字体后仍报旧 fallback face」时撒谎,defeats 诊断本意 → host 字体指纹**不是 optional,是 mandatory**);`test_font_fingerprint.py` 绿;rule-coverage 不变(探针非规则);golden + 视觉基线不变。
- **工作量**:S(因强制加 host 字体指纹,略大于原 S)

---

#### [PERF-B] 把 6b 引擎 / 字体探针 / 6c 分布合并到一次浏览器会话(F-327 P1)
- **改什么**:用进程内 driver 替换 `render-deck.py` 的三处子进程:6b advisory `validate.py --visual --json`(`:3208-3215`)、其内部字体探针、6c `check-distribution.py`(`:3428-3431`)。起**一个** headless Chromium,对 `index.html` `goto+settle` **一次**,然后 `page.evaluate(audits.js)` **且** `page.evaluate(MEASURE_JS)` 在同一已 load 的 DOM 上跑;字体探针走 PERF-A 缓存。保留独立 CLI 不动;只让 render gate 走合并快路径。**完整保留** scope 过滤(`:3251-3257`)、engine-down BLOCK(`:3228-3242`)、F-302 baseline + F-256/F-292 promotion 逻辑。
- **为什么快**:三趟各付自己的 launch(~0.13s)+ goto+settle(~0.90s),对同一 html。共享后:launch 0.131 + goto+settle 0.900 + audits.js eval 0.575 + MEASURE_JS eval 0.018 ≈ **2.0s**,对比当前 6b 3.48 + 6c 1.48 + probe 0.4 ≈ 5.0s。两个 eval 字节不变 → **零规则削弱**。
- **预计省**:**~0.7–1.2s/logged-advisory render**(perf-skeptic 修正口径:原 2.5-3.0s 高估,因字体探针被算重了、且其本体 ~1.0s 的 audits.js eval 无法共享掉)。**这是子任务里 multi-second 量级唯一一个,但必须用 PERF-0 实测复核口径再投产。**
- **涉及文件**:`deck-json/render-deck.py`、`assets/validate.py`、`assets/check-distribution.py`、`assets/run-audits.py`
- **验证方法(强护栏,不可省)**:见 §3 🟡 注 —— 此项被 correctness-skeptic 判 `breaks_accuracy=true`(settle-drift),所以**它真正属于 🟡**,放在 🟢 末尾仅因它是 F-327 既定 P1 的主收益项,但**落地前必须满足 🟡 的 settle 一致性护栏**。先 ship PERF-A(独立 S、零风险),再以护栏方式做 PERF-B。
- **工作量**:L

> 说明:严格按双 skeptic 投票,真正零风险净赚的只有 **PERF-A**(font-probe memoize,加 host 指纹后)与下方两条 lift 收尾。PERF-B 收益最大但带 settle-drift,正确归 🟡。

---

#### [PERF-C] lift `--shake` 规则切到 `<style>` 块体(`lift-descale-scope-styles`)
- **前置事实**:`lift-descale-bail-guard`(`if 'animation' not in css or '{' not in css: return set()`)**已在源码落地**(`assets/lift-slides.py:402`,带 F-332 注释)——**不要再提**;它已把常见页的 O(n²) 回溯短路。
- **改什么**:让 `_root_animation_names`(`lift-slides.py:389`)只在 `<style>...</style>` 块体的拼接上跑那条 `([^{}]+)\{...\}` 走查(复用 `_source_author_css:448` 已有的 `re.finditer(r'<style[^>]*>(.*?)</style>', re.S)`),而不是整段 inner HTML。**只改 `_root_animation_names`**,**绝不动 `_referenced_anim_names`(`:979`)**(它故意要抓 inline `style="animation:..."`,切到 `<style>` 会丢动画 = 丰富度回归)。
- **为什么快**:bail-guard 不覆盖「正文 prose 含 `animation` 字样 + 任意 `<style>`」的对抗页(两条件都过)→ safe-skeptic 实测一个 111KB inner 仍回溯 **67.9s**;切到 `<style>` 体(~93 字节)→ 0.0002s,同样 3 个匹配。硬封顶残留最坏情况。
- **预计省**:典型页 marginal(bail-guard 已盖);对抗页**秒→亚毫秒**。仅 `--shake` lift 时付,非 render 热路径。
- **涉及文件**:`assets/lift-slides.py`
- **验证方法**:corpus grep `<div class="slide"[^>]*style="[^"]*animation`(确认无 inline root 动画被依赖,返回零);golden 字节 diff + F-332 fixture(真根动画仍 descale)+ render --visual;rule-coverage 不变(lift 不碰 audits.js);视觉基线绿。**护栏**:严禁实现者把 `_referenced_anim_names`/`_extract_keyframes` 也切到 `<style>`(线性、非 cliff、零提速理由)。
- **工作量**:S

---

### 🟡 带护栏(需验证后做)

真实省时,但 correctness-skeptic 找到具体的会破坏发现集/产物/可观测性的路径,**护栏达成前不得 ship**。

---

#### [PERF-B′] 共享浏览器编排器 —— settle 一致性护栏(承上 PERF-B)
- **真实省**:~0.7–1.2s/full-advisory runs/ render(perf-skeptic 与 safe-skeptic 一致认可,但口径远小于原 2.5-3s)。**只命中 full/final runs/ render,不命中 --scope/--quick(两门均 `not scope_pages and not args.quick` 守卫)、不命中 --no-visual/非 runs(已 0 Chromium)。**
- **为什么需护栏(correctness-skeptic 实证)**:三个 eval 相同,**但共享页只 settle 一次 → 各 reader 看到的 DOM 状态不同**:
  1. 6b 引擎等 `<img>` decode(`run-audits.py:1100-1109`)以防半载图的 intrinsic height 误报几何;check-distribution **不** decode。共享 post-decode 页上,6c 的 MEASURE_JS 读到它从没见过的 settled 图高 → `L1-UNDERFILL`/`L2-DEADBAND` 在 image-heavy deck 上可能变。
  2. 两套 present-settle 窗口不同(6b:350+200ms;6c:+250ms),对 fs-reveal fill-mode 入场动画在不同帧读几何 → 边界 finding 翻转。
  3. audits.js **需要**被 mutate 的 DOM(注入 `<style data-source=framework>` + `<script type=text/plain>` + `__DECK_JSON__` + present-mode);MEASURE_JS **必须**读 pre-injection DOM。
- **必须满足的护栏**:
  1. **read-only 测量 eval(MEASURE_JS)先跑,任何 mutate eval(audits.js 注入)后跑**;eval 间 re-assert present-mode;统一 settle 取**两套的超集**(img.decode + 最长 settle 窗口),保证没人读到更「未 settle」的 DOM。
  2. **差分门(硬验收)**:编排器发现集(errors/warnings/distribution)vs 当前 3-子进程输出,在 **50p deck + 4 个版式各异 deck** 上必须是**相同 SET**(codes/slides/severities 逐一对齐);**故意破坏 deck 仍 rc=4、干净 deck rc=0**;**engine-down 仍 BLOCK**(F-255 的 `EngineUnavailable→R-VISUAL→BLOCK` 契约必须逐字复刻——这是最高风险路径)。
  3. golden render 字节对比 + 完整视觉基线(`-n auto`)+ rule-coverage 全过 + 若几何测量漂移导致基线 re-bake **= 不通过,回退**。
- **涉及文件**:`deck-json/render-deck.py`、`assets/validate.py`、`assets/check-distribution.py`、`assets/run-audits.py`
- **工作量**:L

---

#### [PERF-D] 去重 check-distribution(6c 结果喂给 snapshot)—— 需修哈希时机
- **真实省**:check-distribution 每 logged render 跑两次(6c 门 `render-deck.py:3428` + snapshot `deck-log.py:580`)同一 html,~1.08s 一趟(benchmark #6,原候选写 1.48s 偏高)。
- **致命前提坑(correctness-skeptic 实证)**:原方案键 `sha256(index.html)` 在 6c 时写、snapshot 时读;**但两点之间 `index.html` 被 `copy-assets.py:450` 原地改写**(skill-relative `<link>/<script>/<img>` → 本地 `assets/` 路径),`--inline` 改得更多。autosnap 恰好只在 runs/ + 有 log/ 时触发 = 正是 copy-assets 跑的地方 → **哈希必 miss、check-distribution 照样重跑、净省≈0**。
- **必须满足的护栏(否则不做)**:**改成 snapshot 直接复用 6c 已在内存/sidecar 的结果**(check-distribution 输出是 rendered-DOM 几何的纯函数、对 asset-path 改写不敏感,所以复用值=新跑值),**或**把 sidecar 哈希落在 **copy-assets 之后**的 `index.html` 字节上。键必须 content-hash 且 miss→live-spawn(fail-safe)。**严禁**未来维护者「放松键」(用 deck.json 哈希 / post-copy 哈希但又不重排 6c 时序)——那才是真 staleness 入口。
- **验证方法**:logged render → snapshot 分布 findings 与 6c 结果、与独立 fresh check-distribution **逐字一致**;check-distribution Chromium launch 2→1(subprocess trace);out-of-band 改 index.html → cache MISS 重跑;making-of `log/audits/vNN.json` 不变;golden + 视觉基线不变。
- **涉及文件**:`deck-json/render-deck.py`、`log-tool/deck-log.py`、`assets/check-distribution.py`
- **工作量**:M

---

#### [PERF-E] 跳过「无变更」snapshot 的指纹浏览器开页
- **真实省**:无内容变更的全量 snapshot 仍开 Chromium 做 goto+settle+meta-evaluate 只为读指纹(`deck-log.py:516-538` 在 `:545-548` 复用判定之前)。render 已知 0 改动时,该开页是浪费。~0.9–1.4s,但**仅命中「无改动全量 render」这个少见 corner case**(真实编辑走 `--slide N` 单页路径,不触此)。
- **护栏(correctness-skeptic,med 信心)**:短路守卫**必须逐字复刻 `deck-log.py:546-548`**——per-page 指纹命中 **且** 对应 PNG 仍存在 **且** 上一版 slides 非空。**绝不能**在「上次 snapshot 子进程失败(slides:[])/ PNG 被外部删」时短路,否则把空/坏 version event 传进 making-of(它本来会 re-shoot 恢复)。**禁用** candidate 提的「从别的 render Chromium pass 收指纹」alternative(那些 pass 的 DOM treatment 不同 → 假 unchanged/changed)。
- **验证方法**:无改动连渲两次 → 第二次 snapshot 0 launch、version event 指向相同 PNG;改一页 → 浏览器开、只重截那页;任何指纹 gap 拒绝短路;making-of 仍含所有页。
- **涉及文件**:`deck-json/render-deck.py`、`log-tool/deck-log.py`
- **工作量**:L

---

#### [PERF-F] 测试合成引擎路径:`data-js-ready` 运行时注入(去掉每次合成 run 的 5s 死等)
- **真实省**:`engine_helpers._wrap`(`:61`)注入的合成 carrier 不带框架 JS → `run-audits.py:1090 wait_for_function('.deck[data-js-ready]', 5000)` 每次合成 run **死等满 5s**(A/B 实测 5.98s→0.87s,~5.1s/run)。33 文件 import engine_helpers、731 个测试函数 → 全套省 ~25-45min,与 xdist 叠乘。**这是测试套件最大单项,非生产路径。**
- **护栏(correctness-skeptic 实证,二选一只有一个安全)**:
  - ❌ **不要把属性 baked 进 `.deck` 字节**——会触发 `R-BAKED-DOM`(`run-audits.py:836-839`,ERROR 级 byte 规则,A/B:22→23 findings)。candidate 的「set the attribute directly」变体**破坏 accuracy**。
  - ✅ **只发一个运行时 inline `<script>` 在 live DOM 里 set 属性**(A/B carrier 27→27、plain-deck 一致,5.98→0.87s)。属性只在 live DOM、不在 raw 字节 → R-BAKED-DOM 不匹配。
  - 注入只 scope 到合成 `.deck` 分支(carrier + plain-deck-wrap + raw 均 safe),**不碰 `verbatim=True`**(`test_doc_integrity.py` 绕过 _wrap)。
- **验证方法**:全套 before/after diff pass/skip 计数相同、每条断言成立;**差分发现 SET 一致且无新增 R-BAKED-DOM**(option 1 会被这条抓住);golden gate / 视觉基线 / rule-coverage 全过。
- **涉及文件**:`deck-json/tests/engine_helpers.py`
- **工作量**:S

---

#### [PERF-G] 测试合成引擎路径:session-scoped 共享浏览器(每 run 新 context)
- **真实省**:`run_unified_engine` 每 call 一次 `launch+close`,测试套件 ~150-400+ 次。摊掉 ~370ms 冷启动 → 全套 ~27s–3min(在 PERF-F 落地后才成为次大固定成本)。串行 unittest 直接累加。
- **护栏(correctness-skeptic,唯一安全变体)**:**每 run 用 `new_context()`(或至少 fresh page)**——audits.js 的 28 个 `window.__*__`(24 个 once-per-run memo flag + `__DECK_JSON__/__AUDIT_SCOPE__` 等)全 window-scoped,fresh page 全 reset;**只共享进程、绝不共享 page/context state**。生产路径(validate.py/reconcile-reflow.py/golden/baseline)positional 调用、不传 page= → 默认 None 仍各自 launch+close、**字节不变**。
- **验证方法**:正序+逆序跑全套,要求 pass/skip + golden/baseline findings **逐一相同**(证无跨测污染);atexit 关浏览器(注意 xdist 下是 per-worker);若任何 run 复用同一 page → 第二个 deck 的 deck-level 规则会静默返回 [] = gate 漏缺陷(这正是要防的 failure mode)。
- **涉及文件**:`assets/run-audits.py`、`deck-json/tests/engine_helpers.py`
- **工作量**:M

---

#### [PERF-H] pytest-xdist `-n auto`(先修固定路径写者)
- **真实省**:48/89 测试文件起独立 Chromium 子进程、无共享 server/端口 → 干净并行,RAM-bound ~3-5x;叠 PERF-F 后 ~5min → ~1.5-2min。
- **护栏(correctness-skeptic 补全 candidate 漏报的碰撞点)**:**先**修所有固定路径/共享资源写者,否则 worker 撞车出假失败:
  - `test_baseline_gate.py:63`(固定 `runs/00000000-000000-baseline-gate-test`)
  - **`test_renumber_scope_gate.py:82`**(同款固定 `runs/...-renumber-scope-gate`,candidate 漏报)
  - **`test_outline_lint.py:91`**(glob 共享 `runs/*/output/outline.json`,与并发写 runs/ 的 gate 测试冲突,candidate 漏报)
  - candidate 提的 `library_root=REPO_ROOT` 测试在本 repo `deck-json/tests` **不存在**(那是别 repo 记忆),勿照搬。
  - 各给 unique tmp dir 或 `@pytest.mark.xdist_group`。需放宽 README 的 stdlib-unittest-discover 强制(允许 pytest+xdist 作为 fast runner)。
- **失败模式 = 假失败/flaky,不会静默 PASS 过真缺陷**(xdist 跑相同断言对相同 committed 参考文件)→ 不破坏 accuracy,但碰撞清单不全会引入 flaky。
- **验证方法**:先串行出 baseline pass/skip + golden/visual/rule-coverage;再 `-n auto` 要求**完全相同**;预审所有 hardcoded `runs/` 路径 + 共享 glob 后再启用。
- **涉及文件**:`deck-json/tests/test_baseline_gate.py`、`test_renumber_scope_gate.py`、`test_outline_lint.py`、`README.md`、`conftest.py`(需新建)
- **工作量**:M

---

#### [PERF-I] 首版 50 张 baseline snapshot K 路并行(一次性首渲成本)
- **真实省**:首版 baseline 串行 ~24-32s,K=3-4 → ~8-11s。**一次性/每 deck**,稳态增量已只截改动页 → 不碰编辑热路径。
- **护栏(correctness-skeptic)**:settle 是**固定 wall-clock timer**(`wait_for_timeout(300/350)`、load 4s/fonts 2s cap),**不是 readiness gate**;K 路 CPU/GPU 争用下 timer 不自动拉长 → 可能截到 mid-settle 帧(CJK fallback、未 reveal stagger),正是 fonts.ready/data-js-ready 当初要灭的 flake;还会让下次 `deck-log diff` 在未变页报假 >1% 变化。`_SHOW_SLIDE_JS` 改全帧 is-current → **每 shard 必须独立 page/context**(共享页交错会污染)。**K 必须 bound**(避免 host thrash)。这些 PNG 只喂 making-of,不喂任何 gate → **accuracy 安全**,风险纯在帧保真度。
- **验证方法**:并行 baseline 与串行**逐张 pixel-compare(<1% 各)**;下次增量复用仍生效(指纹不变);无页缺/多;压测已知慢 deck(embedded-live-demo)确认 cap 守住。
- **涉及文件**:`log-tool/deck-log.py`
- **工作量**:L

---

#### [PERF-J] `deck-cli` 写命令进程内校验(+ 崩溃隔离护栏)
- **真实省**:实测 subprocess `validate-deck --strict` 138.7ms → 进程内(schema 解析一次 + 模块 import 一次)29.3ms,**~109ms/写**,略优于 candidate 估的 80-90ms;`_scope_demote` 第二次 spawn 再省 ~138ms。5-8 编辑 burst ~0.5-1.1s。**但便宜路径**:benchmark 明确「deck-cli 编辑便宜,迭代成本由后续 render 主导」。
- **护栏(safe-skeptic 实证的真回归,candidate 只提了 SystemExit、不够)**:`check_business_rules` 在 deck-cli 可达的畸形 deck 上**抛未捕获 AttributeError/TypeError**(实证:`set slides.0.data.rows.0 123` → 内存 dict 过 scope → 原子写落盘 → subprocess `len(123)` crash rc=1 → `write_deck_with_validation` 看 rc≠0 → **回滚 + rc=3**)。进程内时该异常在 step-4 回滚前逃逸 → **畸形 deck 已落盘且被保留**(当前代码会拒绝+回滚的写,变成静默保留坏盘)。**必须**:catch AttributeError/TypeError(非仅 SystemExit)、stub argv、reset 模块全局态、保留原子写+回滚契约。
- **验证方法**:clean/in-scope-broken/off-scope-broken deck 上,进程内 `Result.errors/warnings/soft_warnings`(paths+msgs)与 subprocess --json **逐字一致**;**畸形 deck(rows=123 类)必须仍回滚 rc=3、盘恢复**;F-320 scope-demote / F-48 乐观锁 / W1 回滚单测全过;rule-coverage + golden + 视觉基线不变。
- **涉及文件**:`deck-json/deck-cli.py`
- **工作量**:M(收益小、属次要,排在 PERF-A/B/D 之后)

---

### 🔴 不做 / 慎做(说明 WHY,防止重复提案)

| 候选 | 裁决 | 为什么(双 skeptic 共识) |
|---|---|---|
| **dedup-check-distribution-snapshot(原版 sidecar 键)** | 🔴 原版 reject | 键 `sha256(index.html)` 在 6c 写、snapshot 读之间,`copy-assets.py:450` 原地改写 index.html → **哈希必 miss、净省 0**。仅在 `--skip-copy-assets AND not --inline` 罕见组合才命中。**正确做法已移到 🟡 PERF-D**(复用内存结果 / 改哈希时机)。 |
| **background-auto-snapshot(fire-and-forget)** | 🔴 reject | option (b)「env/flag gate iteration」**已四套 ship**:`--quick`(跳 snapshot)/`--scope N`(per-page)/`--iter`(`DECK_LOG_NO_AUTOSNAP=1`)/`--final`(强制全量);默认 loop 已 auto-scope 到 ≤4 改动页走单截图。option (a) detach 破坏 W2 契约(autosnap stdout teed 进 last-render.log,`_finish_render_log` 已 teardown)+ 与下次 render Chromium 争 CPU。 |
| **gate-skip-unchanged-hash** | 🔴 reject | (1) index.html 埋 per-render uuid `data-deck-id`(`render-deck.py:2757`)→ 裸 sha256 每次都变、no-op 也 miss。(2) 键**不覆盖 audits.js**(今日还在改)/引用图资产/Chromium 版本 → 改 audits.js 加规则后重渲未变 deck **复用旧 PASS、新规则永不跑** = candidate 自己 forbid 的「静默弱化 gate」。(3) 常见多文件编辑场景已被 F-310/F-334 auto-scope sidecar 覆盖。 |
| **adaptive-settle-waits** | 🔴 reject | candidate 自带 kill-switch「无可靠 layout-settled 信号则保留固定 sleep」——代码确**无**该信号:`data-js-ready` 在 maybeBalance(rAF)/fonts.ready→setBandAnchor **之前** set;`data-fs-balanced` 是「started」非「settled」且失败会 revert;`data-fs-canvascentered/-colbalanced` 仅在该 pass 实际动时才 set → 无法区分「settled 无需动」。裸 rAF 会在 deferred 居中/列平衡/字体重锚 **之前** resolve → **假 R-VIS-* 阳/阴**。settle 在 accuracy-critical 几何测量路径上。 |
| **persistent-browser-iteration** | 🔴 reject(perf)/ investigate(safe) | 设计若严格(总 fresh goto、只共享进程、--final fresh launch)无损,但收益仅 ~0.37s/iter(540ms 的 settle 是固定 timer + data-js-ready 等框架 JS 重跑,warm cache 救不回);candidate 的「~0.9s 保持页 warm」与自己的 accuracy 守卫(总 fresh goto)自相矛盾。引入 stale-DOM/leaked-injected-state 陷阱(28 个 window 态 = 引擎正确性基底,page 复用一旦失误 → 24 条 deck-level 规则静默返回 [] = 零信号全漏)。L effort 换 7% 不值;`validate.py`(真正起浏览器的模块)还漏在 files_touched 外。 |
| **deck-cli-batch-mode** | 🔴 reject(perf)/ ship-with-guard(safe) | 机械真省(N-1 冷启动+spawn),但 (1) **scope-union 弱化 gate**:`_edit_scope_keys` 对 reorder/delete/clone/paste/hide 故意返回 None(全 deck 门),candidate 的 key-union 会把 `{set A}+{reorder}` 算成 `{A}` → demote 其余页真错、提交坏盘;正确语义=任一 op None 则整 batch None。(2) 原子性夸大:paste/add-asset 在校验前 `shutil.copy2` 落资产文件,回滚 deck.json 不撤文件。(3) clobber/乐观锁只 batch 开头跑一次 → 拉宽并发竞态窗。属 L effort 命中便宜路径,且 render 仍跑一次 → 一次性交互编辑省 0。 |
| **render-inprocess-subprocess-calls**(copy-assets + schema in-process) | 🔴 reject(perf) | 实测可回收仅 ~102ms(validate-deck 106ms 里 ~57ms 是真 schema 工作、进程内也跑;copy-assets ~53ms 多为启动税)= 1.2-1.6% of render,<measurement noise。瓶颈在 Chromium(~20x)。无损但不值；排在 orchestrator+font-probe 之后才谈。 |
| **deck-cli-inprocess-validate(独立项)** | 🟡→低优先 | 同 PERF-J,~80ms/写、便宜路径、~1.3% of render cycle;**已并入 PERF-J**(带崩溃隔离护栏),不另立。 |
| **lift-inprocess-validate** | 🔴 reject | 实测可回收 ~72ms(模块 import 仅 2.5ms,无「80-100ms import 冷启动」可摊);lift 是一次性人工 CLI,且其终端就提示「Now run render-deck --visual」(5-6s 强制门)→ 72ms 是下一步的 ~1%。第二 spawn site 是 `validate.py`(不同文件、可能起 Chromium),candidate 的「0-chromium」论据只覆盖 validate-deck。F-281b 回滚契约**无现存回归测试**,改动风险>收益。 |
| **lift-single-pass-source-parse** | 🔴 reject | 实测 build_manifest 50 帧 = **5.9ms**(非 candidate 的 130ms,差 20-45x);part(a) 净省 ~3ms;part(b) write-once 在**无测试**的 multi-frame/`--pos` 路径上改字节(顺序/标号/`.bak`/崩溃安全全变)→ safe-skeptic 判 breaks_accuracy+richness。trivial 收益换真回归面。 |
| **r10-perslide-dedup** | 🔴 reject | 真省仅 ~144ms@50p(常见小 deck 6-37ms,sub-perceptible),~3.9% engine eval / ~2.3% advisory render。且 safe-skeptic 实证「identical-or-superset」**为假**:per-hex ×N 计数双向漂移(非单调超集),改 `run-audits --json` text 输出;golden gate 只 snapshot per-severity counts + slide_idx、**不 pin message** → 验证计划盲区。verdict 不变但 message 行为变,不值改引擎热点。 |
| **engine-ctx-style-cache** | 🔴 reject | ~25-30ms(~0.7% eval)且 Chromium 内置 style cache 已吸收大部分。改 ~18-30 rule body 风险高:`R-VIS-ABSPOS-DUAL-ANCHOR` 实际 mutate layout(`el.style.bottom='auto'` 再测再还原)→ candidate「layout static」前提**错**;memo 只是侥幸不坏。sub-1% 换 ERROR 级视觉门改面。 |
| **engine-abs-overlap-singlewalk** | 🔴 reject | 实测全引擎 eval 仅 ~325ms warm;该改动去掉 ~6-8ms(candidate 估 10-20ms 高)。premise「多数页 <2 abs」**错**(实测 median 6.5、mean 25.2,仅 3/50 页 <2)。part B「同样早返 DUAL-ANCHOR」**破坏 accuracy**:DUAL-ANCHOR 是 per-element 规则,单个 dual-anchored 元素就该 fire(实证 lone-watermark 返 1 error),「<2 无 pair」是 category error → 漏掉旗舰用例。 |
| **engine-spread-hoist** | 🔴 reject | 实测 ~0.4-0.6ms/render(非 5-12ms),sub-noise。candidate「~30 sites」实为 8;5 个 `[slide,...]` 已 once-per-rule 无可 hoist;真正 in-loop 的 spread over **不同** loop 变量、结构上不可 hoist 到 rule-level。自我声明被 engine-ctx-style-cache subsume。强行 hoist in-loop 会破坏 per-slide/per-element scoping(R10/NO-IMG/CARD-OVERFLOW)。 |
| **engine-css-parse-memo** | 🔴 reject(perf)/ ship-with-guard(safe) | 实测全 deck 仅注入 2 个 author `<style>`(7.7KB,非 candidate 假设的「50 per-page」),一次 iterCssRules(combined ~190KB)= 0.26ms warm;memo 去掉 ~0.4ms warm = ~0.01% engine eval。referentially-transparent 安全但为 0.5ms 给 7000 行共享 validator 加 window 全局态,premise 量级错 10x。（注:safe-skeptic 提到 rule-coverage 现为 **85/85** 非文档旧写的 84/84，doc 数字陈旧。） |
| **test-render-dedup** | 🔴 reject | premise 对自己 scope 文件**事实错**:`test_golden_gate.py` 只渲一次(且第二 test 读 committed JSON 不渲)、`test_examples_visual_baseline.py` 渲一次 + 校验一个预渲 html;三件产物互不重叠 → content-keyed cache 永不命中。且 deck.json-only 键对 linked vs default render / copy-assets 差异盲 → 会把两种 render 撞一起、serve 缺资产的 html、静默移动 finding。 |
| **unify-browser-bootstrap-helper** | 🔴 reject | 0s 独立(自认 enabler),且 enabler 定位错:四块 bootstrap **不是同一序列**(shoot.py 加 network-block+`?mode=present`;shoot-page.py 是 file://#n hash-nav、无 fonts.ready/data-js-ready/present;capture-frames 又一套);强行统一要么改 shoot 行为(违「no behaviour change」)要么变成多分支(失去合并意义)。真正 ~2.2s 收益不 gate 在抽这些 copy 上。 |
| **lift-descale-bail-guard** | ✅ 已落地(不要再提) | **已在 `lift-slides.py:402`**(`if 'animation' not in css or '{' not in css: return set()` + F-332 注释)。该候选已是现状,残留加固见 🟢 PERF-C。 |
| **confirmed-already-optimal** | ✅ 已确认最优(信息项) | (1) `capture-frames.py:119-153` 一个 Chromium 跑所有 key。(2) `deck-log._shoot:546-548` djb2 指纹增量复用、`--slide N` 路径才故意 force-shoot 单页。「_shoot 强制全重截」的旧 memory 记法**是错的**。 |

---

## 4. 准确度与丰富度护栏(每个优化都必须保持通过)

任何 PERF-* 改动**只有同时满足以下全部**才算「不削 check / 不切内容」:

- **发现集逐字一致**:同一 deck,优化前后 `run-audits --json` 与 `check-distribution --json` 的 **codes / slides / severities 完全相同**。差分门(orchestrator/dedup/in-process)以「相同 SET」为硬验收,不是「都 PASS」。
- **rule-coverage 全过**:`check-rule-coverage`(audits.js ↔ FAMILIES ↔ business-rules.yaml ↔ validator-rules.md 单源对齐)——注意现行计数 **85/85**(部分旧文档仍写 84/84,以现读为准)。加/退任何规则必同步四处(铁律,见 memory)。
- **golden render 字节对比**:`test_golden_gate.py`(engine-findings-match-golden)+ `test_render_deck_golden`(linked/normalized markup)。
- **完整视觉基线**:`test_examples_visual_baseline.py`(`-n auto`)零基线漂移;若任何几何测量因 settle 合并漂移导致基线 re-bake = **回退**。
- **rc 契约不变**:故意破坏 deck rc=4、干净 deck rc=0、**engine-down 仍 BLOCK**(F-255 `EngineUnavailable→R-VISUAL→BLOCK`)。
- **写路径原子性 + 回滚**:in-process 校验/batch 必须保留 deck-cli 原子写 + 失败回滚(F-269/F-48/F-320 全过),畸形 deck 仍拒绝落盘。
- **R-BAKED-DOM 不新增**:测试合成 js-ready 只走 runtime `<script>`,绝不 bake 进 `.deck` 字节。
- **缓存无 staleness 窗**:font-probe 键含 host 字体态;dedup 键 content-hash 且 miss→live-spawn;`--final`/`--visual` 交付门**永不被任何 hash-skip 跳过**。
- **lift 不丢动画**:descale 切 `<style>` 仅限 `_root_animation_names`,`_referenced_anim_names`(抓 inline 动画引用)保持扫全 inner。

---

## 5. 建议落地顺序

承 F-327 的「P0 先量化 → 先落免费/低风险 → 再啃合并」执行序,按双 skeptic 定级重排:

1. **PERF-0(前置必做)= F-327 P0 `assets/bench-render.py`**:固定 N 页样例,分段计时(render/schema/视觉门/分布/截图全新 vs 增量/--final 全程/--iter 单页),≥3 次取中位,出 JSON。**没有 before/after 不优化**——本报告所有「~Xs」都要它复核(尤其 PERF-B 的 0.7-1.2s vs 原 2.5s 口径分歧)。【S】
2. **PERF-A 字体探针 memoize(键含 host 字体态)**:独立、零风险、~0.4s/--json,先落。【S】
3. **PERF-C lift `<style>`-scope 加固** + 登记 `lift-descale-bail-guard` 已落地:封顶 `--shake` 对抗页假死。【S】
4. **PERF-F 测试 js-ready 运行时注入**(runtime `<script>` only):全套省 25-45min,解锁后续测试迭代。【S】
5. **PERF-H xdist**(先修 `test_baseline_gate.py:63` / `test_renumber_scope_gate.py:82` / `test_outline_lint.py:91` 碰撞)+ **PERF-G 测试共享浏览器(每 run new_context)**:测试墙钟 ~5min→~1.5-2min。【M+M】
6. **PERF-D 去重 check-distribution(复用 6c 内存结果 / 改哈希时机)**:稳态 logged render -~1.08s。【M】
7. **PERF-B′ 共享浏览器编排器(read-only eval 先跑 + 差分门 + engine-down 契约复刻)= F-327 P1 主收益**:用 PERF-0 复测口径再投产;最大单项但最高 settle-drift 风险,放在有 bench + 测试加速兜底之后。【L】
8. **PERF-E 跳无变更 snapshot 开页** + **PERF-I 首版 baseline K 路并行**:corner-case / 一次性,数据证明值得再上。【L+L】
9. **PERF-J deck-cli 进程内校验(带崩溃隔离)**:便宜路径次要项,最后做。【M】

> 凡 PERF-B′/D/E/G/I 落地后,**必须用 PERF-0 出 before/after + 跑 §4 全套不变量**;**任一 gate 行为变化 = 不通过、回退**。性能改动绝不改变校验结论。

---

**相关文件(绝对路径)**:
- 设计/总账:`/Users/bytedance/Documents/Github/feishu-deck-h5/skills/feishu-deck-h5/docs/PERF-OPT-PLAN-2026-06-16.md`(F-327)、`/Users/bytedance/Documents/Github/feishu-deck-h5/skills/feishu-deck-h5/docs/TICKETS.md`(F-290 DEFERRED→F-327 重启;领新号现读 origin)
- 瓶颈代码锚点:`assets/run-audits.py:1071-1137`、`assets/validate.py:333-393,628-645`、`assets/check-distribution.py:351-390`、`deck-json/render-deck.py:3079-3087,3201-3215,3426-3431,2104-2169`、`log-tool/deck-log.py:491-586,543-568`、`assets/lift-slides.py:389-402`(bail-guard 已落地)、`deck-json/tests/engine_helpers.py:61`