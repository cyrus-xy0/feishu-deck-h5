# F-333 · copy-assets prune 误删 HTML 实体引号(`&quot;`)的内联 `url()` 背景资产

> 状态:**开放 / TODO**（2026-06-16 立项，登记于 `docs/TICKETS.md`）
> 号以 `docs/TICKETS.md` 为准。

## 症状

手写或导入的 raw 页，如果背景图写成 `style=""` 属性里 HTML-转义的双引号：

```html
<div class="end-bg"
     style="background-image: url(&quot;input/ai-peirun-bg.png&quot;);"></div>
```

下次 `render-deck.py`（默认 copy-assets / 自包含模式）后，**`input/ai-peirun-bg.png`
文件被从磁盘删掉**，页面背景静默变空。validator 全绿、render PASS，所以发现不了。

真实案例：`runs/20260605-112833-northregion-ai-lecture` 第 47 页收尾页
（`claim-digital-employee-end`）背景反复消失 —— 即用户报的「这页的图怎么不见了」。

## 根因

两段代码合谋：

1. **prune 会删文件** —— `assets/copy-assets.py` L569–581 的自包含同步：
   遍历 `input/`，凡 **不在 `referenced` 集** 的文件一律 `f.unlink()`。
   （副作用：放进 `input/` 的任何 `.bak` 等临时文件也会被一并删掉。）

2. **引用扫描漏认 `&quot;`** —— 收集 `referenced` 的正则
   `RX_INPUT`（L57）/ `RX_LOCAL_INPUT`（L74）：

   ```python
   RX_INPUT = re.compile(r'((?:\.\./)*)input/([^\'")\s?#]+)')
   ```

   字符类 `[^\'")\s?#]+` 排除了 `'` `"` `)` 空白 `?` `#`，**但没排除 `&`**。
   于是 `url(&quot;input/ai-peirun-bg.png&quot;)` 里 `&quot;` 不被当成引号，
   被当普通路径字符吃进去 → 捕获成 `input/ai-peirun-bg.png&quot;`
   （带 `&quot;` 尾巴、磁盘上不存在的假路径）。

   结果：`referenced` 里是假路径，真文件 `input/ai-peirun-bg.png`
   **不在** `referenced` → 被 prune 删掉。

3. `deck-json/render-deck.py` 的 `_ASSET_REF_RE`（L2008）
   `(?:input|prototypes)/[^\s\"'<>()\\?#]+` 同样没排除 `&` ——
   影响 `slide-index.json` 清单与 lift 拷贝（`_scan_slide_assets`）。

## 为什么只有 `&quot;` 形态中招

- 框架自身 renderer 发的内联背景是**单引号** `url('...')`（见 render-deck.py
  L603/634/651/665/964/1100/1174/1371），`'` 在排除集里 → 扫得对。
- 裸 `url(input/x.png)` → 在 `)` 处截断，对。
- `<style>` 块里**字面双引号** `url("input/x.png")`（非属性、不转义）→ 在 `"`
  处截断，对。
- 唯独：在 `style="..."` 属性里手写双引号，HTML 序列化成 `&quot;` → 崩。

p47 的就地修复正是把 bg url 从内联属性挪进 `<style>` 块、用字面双引号
`url("input/ai-peirun-bg.png")` —— 扫描器立刻能认（lint 随即报出 L-BIG-URL，
证明引用已进入扫描面），文件不再被删。这验证了根因。

## 修法（建议）

最小外科：给三处字符类补 `&`（建议连 `;` 一起），让正则在 `&quot;` 的 `&` 处截断：

- `assets/copy-assets.py` `RX_INPUT`（L57）、`RX_LOCAL_INPUT`（L74）
- `deck-json/render-deck.py` `_ASSET_REF_RE`（L2008）

更稳：扫描前对 html 做一次 `html.unescape(...)`（一次性治本，且覆盖
`&#34;` / `&apos;` 等其它实体形态）。两者择一或并用。

附带核查：`RX_SKILL`（copy-assets.py L53）、`rx_css_url`（L461）等其它引用
正则是否共享同一盲点；以及 prune 在删文件前是否该对「捕获到的假路径明显异常
（含 `&`/不存在）」给一条 warning，避免下次再静默删。

## 回归测试

新增一例：构造一个 raw 页，背景用 `style="...url(&quot;input/x.png&quot;)..."`，
放一张真 `input/x.png`，跑一轮 copy-assets（自包含 prune）后断言
`input/x.png` **仍在**、且被正确改写/计入 referenced。

## 影响面 / 风险

- 文件名里含字面 `&` 的资产极罕见且本就不推荐；把 `&` 从「资产路径合法字符」
  里剔除是安全的。
- 共享文件、并发 session 多（render-deck.py / copy-assets.py 常有 WIP）；
  落地建议走隔离 worktree off origin/main，只动这两文件 + 测试，避免踩别人 WIP。
