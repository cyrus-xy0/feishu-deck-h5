# F-315 · 浏览器 edit-mode 编辑被静默覆盖的数据丢失 bug

> 立项 / 修复记录 · 2026-06-13 · 状态 DONE(零回归)

## 现象(用户报告)

> 同事用 `e`(浏览器 edit-mode)改了对应的 deck,保存了,打开都没问题。但再用 AI 去改其他页时,**之前用 e 改的那些页内容全被还原回去了。**

## 根因 — deck.json↔index.html 的「脑裂」

`deck.json` 是唯一真源;`index.html` 是它的派生件,每次 render **整页从 deck.json 重建**。两路编辑写的是**不同文件**:

1. 同事 `e` 进编辑模式改内容 → ⌘S 保存:`deck-edit-mode.js` 的 `buildSavedHTML()` 序列化当前 DOM,用 File System Access API **只写回 index.html**(`deck-edit-mode.js:745-809`),**从不碰 deck.json、不跑 sync、不报警**。→ 改动只活在 index.html。
2. 重新打开看着没问题 —— 打开的就是那个被改过的 index.html,没发生 round-trip,drift 隐形。
3. AI 改其他页:`deck-cli set-page` 读**磁盘上的 deck.json**(里面同事那几页仍是原始内容),改完写回 deck.json。
4. AI 重渲染:`render-deck.py` 从 deck.json 全量重建 index.html 并**盲覆盖**(`render-deck.py` atomic_write)→ 同事写在 index.html 里的改动被原始内容盖掉。
5. 最毒的一刀:render 开始时把旧 index.html 备份成 `index.html.bak-pre-render`,但 **render 成功后 `unlink()` 删掉它**(`render-deck.py:3454-3458`)→ 成功覆盖后磁盘**无痕**,git 也不跟踪 runs/ 的 index.html → 基本无法事后恢复。

防这个的逻辑其实**早就写好了** —— `sync-index-to-deck.py:_wrong_direction()` 的方向守卫 —— 但它**只在人手动跑 sync 时生效,从没接进 render / deck-cli**。`round-trip-integrity.md` 也只是文档口头叮嘱「author owns this check」,**零自动强制**。

## 为何不能用「内容比对 / sync 漂移」当守卫信号

第一版尝试复用 `sync-index-to-deck.py` 的 per-slide 漂移检测(`--check-drift`)。实测:**对一份 50 页全 canvas 的干净 render,它报 50 页全 drift(假阳性)** —— canvas 的反向映射(几何 `cqw/cqh→px`、多 run 文字扁平化)**本就不幂等**。canvas(PPTX 导入)很常见,假阳性会拦死每个操作。→ 内容比对不可用作守卫。

## 修法 — 布局无关的「自完整性签名」

新增共享模块 **`deck-json/_index_sig.py`**:

- **签名**:render 在产物里埋 `<meta name="fs-render-sig" content="…">` = **规范化内容的 sha256**。规范化(`_canonicalize`)归一掉两次忠实 render 之间合法会变的位:per-render 随机 `data-deck-id`、我们自己的 provenance/sig meta、资产路径前缀(copy-assets 把 skill 相对路径改写成 `./assets/`)。其余**全部 authored 内容逐字保留** → 任何可见编辑都改变签名。纯 HTML 字节哈希,**canvas/raw/schema 一视同仁,零假阳性**。
- **校验** `verify(index)` → `ok`(自上次 render 未被改)/ `edited`(内容在 sig stamp 后变过 = 未 sync 的外部编辑)/ `unstamped`(无 sig,旧/外来件)。比的是文件 **vs 自身内嵌 sig**,不读 deck.json、不看 mtime、不做 canvas 反映射。
- **守卫 `guard_should_refuse(deck, index)`**(廉价底座):`verify(index)=="edited"` 且 deck.json **不比** index.html 新(>2s 容差)时认定"有未 sync 编辑"。mtime 那一侧让「sync 回写 deck.json → 重渲染」的**合法恢复流**放行:sync 写完 deck.json 后它变新,重渲染就被允许。

## 策略 — Option A「无损自动 / 有损拦截」(用户拍板)

不是一律拒绝。`resolve_clobber(deck, index)` 先跑上面的廉价守卫;**只有真有未 sync 编辑时**才花一次 `sync --check-drift` 子进程分类(常规循环零开销):

| `--check-drift` 退出码 | 含义 | `resolve_clobber` 动作 |
| --- | --- | --- |
| 0 | 无 slide 级漂移(sig 却说 edited → 编辑在 chrome/`<head>` 或 schema 页,sync 折不动) | **refuse** |
| 10 | 有漂移,**全无损**(raw `data.html` / custom_css / order / hidden / notes) | **autosync** |
| 11 | 有漂移,**含有损**(canvas 页 / baked DOM) | **refuse** |

- **autosync**:自动跑 `sync --index-is-newer` 把编辑折回 deck.json,**再继续**原操作(命令的改 / render 叠在其上,两边都活)。用户无感。
- **refuse**:停下报错(见下三道闸),`--force` 放行并**丢弃**。

**三道闸**(都在改 deck.json / index.html *之前*,此刻 deck.json 仍等于上次 render 的源,判定无歧义;autosync 必须发生在读 deck.json 前,否则渲染拿不到折回的内容):

| 位置 | 行为 |
| --- | --- |
| **deck-cli 写命令唯一收口**(`main()` dispatch 前) | resolve → ok 直过 / autosync 折回后**重载 deck + deck_mtime** / refuse → **exit 6** |
| **render-deck 加载 deck.json 前** | resolve → ok / autosync(deck.json 更新,下方 `json.loads` 自然读到)/ refuse → **exit 8** |
| **import-html-slide 插页前**(`insert_into_json` 读 deck.json 前) | resolve → ok / autosync / refuse → SystemExit;新 `--force` |
| `--force` | 三处皆放行并**丢弃**未 sync 编辑 |
| render 成功收尾 | `os.utime` 把 index.html mtime 对齐 deck.json → 新鲜未编辑产物**不被**当成"比源新",常规 `set-page→render` 循环不误触 |
| `deck-edit-mode.js` 保存 toast | 提示"改动只在 index.html;AI 改前先 sync 回 deck.json"(autosync 是主路,toast 是引导/兜底) |

关键:edit-mode 保存**保留**那个已过期的 `fs-render-sig` meta(stripRuntimeArtifacts 只清 runtime 痕迹,不动 fs-* meta)—— 正是 stale sig 让 `verify()` 判出 "edited"。若 edit-mode 删了 sig,守卫会判 "unstamped" 而跳过,前功尽弃。

## 验证

- 新测 `tests/test_index_sig_guard.py`:**19/19** —— verify ok/edited/unstamped、guard 三态、`resolve_clobber` 分类(raw→autosync / schema→refuse)、**raw 自动 sync**(render 与 deck-cli 各一:无手动 sync,编辑自动折回 deck.json 且重渲染后留存)、schema/chrome edit → refuse(deck-cli exit 6 / render exit 8 + 确认 refuse 时 index.html 未被覆盖)、canonical loop 不误触、--force 放行、edit→sync→render 恢复。
- 真实 **50 页 canvas deck** 实测:干净 render → `verify=ok`(零假阳性);编辑后 `check-drift=11` → `resolve=refuse` → deck-cli rc=6 / render rc=8(canvas 真源**不被自动改坏**)。
- 既有套件零回归:`test_render_deck_golden`(给 `_normalize` 加 strip `fs-render-sig`,快照无需重生)、`test_atomic_render`、`test_sync_direction`、`test_render_gate`、`test_edit_roundtrip_sanitize` —— 共 **38/38**(连新测合计 57/57)。

## 已知边界(pre-existing,不在本工单范围)

`sync-index-to-deck.py` 的反向回写**对 raw 页干净**,但:
- **schema 版式页**:`sync` 默认 skip,需 `--force` 把该页**有损转 raw**(丢结构化 schema 字段);且某些 variant(如 `3up`)转 raw 后会触发 `effective_layout` 缺字段的 render 报错 —— 是 sync `--force` 的旧问题。
- **canvas 页**:几何/多 run 文字反向映射不幂等。

正因 canvas/schema 反向有损,Option A 对它们**拦截而非自动**(只对 raw 自动 sync)。守卫对所有布局都照常**阻止静默丢失**;canvas/schema deck 的「sync 恢复保真度」是独立课题。实务建议:这类 deck 优先**在 deck.json 里重做该编辑**,而不是指望一次完美反向 sync。

## 迁移说明

存量 index.html 没有 `fs-render-sig`(`verify`→`unstamped`→守卫跳过),首次重渲染即补上签名,此后受保护。部署后的首个操作若直接 render 一份从未重渲过的旧 deck,守卫无法判定 → 放行(不比旧行为差)。
