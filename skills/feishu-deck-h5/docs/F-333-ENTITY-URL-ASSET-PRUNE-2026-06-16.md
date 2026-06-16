# F-333 · copy-assets prune 误删 HTML 实体引号(`&quot;`)的内联 `url()` 背景资产

> 状态:**DONE**（2026-06-16 立项 + 当日实现，登记于 `docs/TICKETS.md`）
> 号以 `docs/TICKETS.md` 为准。实现见下「已实现的修法」+「对抗复核」段。

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

## 已实现的修法（DONE 2026-06-16）

> 注意：**不是**简单给字符类补 `&`。对抗式复核证明那样会把文件名里**合法含
> `&` 的资产**（`input/Q&A.png` / `R&D-roadmap.png` / `AT&T-logo.png`）截断 →
> 真文件被 prune 删掉 = 为另一种输入**重新引入本工单要消灭的删除 bug**。见「对抗复核」。

按消费端分三类处理（34 个易碎扫描器中，喂给删除/拷贝/内联/上传的才修；CSS-only
扫描器与 data-URI 扫描器故意不动）：

1. **删除 / 清单 / 拷贝 sink 的「无 `url(` 锚点」扫描器** —— 用**实体专属否定先行**
   收紧字符类，只在 `&` 确实是 quote-entity（`&quot;`/`&apos;`/`&#34;`/`&#39;`）开头时
   才截断，普通 `&`（`Q&A.png`）照常吞:
   - `copy-assets.py` `RX_SKILL`/`RX_INPUT`/`RX_LOCAL_ASSET`/`RX_LOCAL_INPUT` +
     `link_deck_local` 内联 `re.sub`（共用模块级 `_NE = r"(?!&(?:quot|apos|#34|#39);)"`）
   - `render-deck.py` `_ASSET_REF_RE`（slide-index 清单）
   - 为何不用整段 `html.unescape`：copy-assets 会把扫到的 `src` **改写后回写**，
     unescape 整缓冲会把 `style="…&quot;…"` 解成字面引号 → 破坏属性合法性。
2. **「有 `url(` 锚点」的 lift/import url() 模式** —— `&quot;` 夹在 `url(` 和路径**之间**，
   截断字符类只会让它不匹配；改为**容忍实体引号开/闭 + 内层允许非实体 `&`**:
   `url\(\s*(?:&(?:quot|apos|#34|#39);|['"])?((?:[^'")&]|&(?!(?:quot|apos|#34|#39);))+?)(?:…)?\s*\)`，
   捕获干净内层路径（既能分类、又是原文字面子串可供 `inner.replace` 回写）。
   `lift-slides.py` L491 与 `import-html-slide.py` L276 是逐字镜像,同步改。
3. **纯解析消费端（解析后丢弃原 ref）** —— 在解析 choke point 做 `html.unescape` + 剥字面引号,
   **但门控**:仅当 ref 含 quote-entity 标记时才 unescape(否则普通 CSS 文件名的其它命名实体
   会被误解码),且放在**外链/data:/fragment 判断之后**(否则含 `&amp;` 的 data: URI 被破坏):
   - `inline-assets.py` `strip_ref` / `magic-page-assets.py` `strip_ref`（门控）
   - `render-deck.py` `_resolve_bg`（门控 + 移到 `_is_inlinable_local_ref` 之后,保 F-270 fragment）

**故意不动**:`explode-assets.py DATA_URI_RE`、`copy-assets rx_css_url`、
`render-deck _inline_stylesheet`、`magic-page IMPORT_RE` —— 扫的是 `<style>`/CSS 文件里
**字面引号**文本,永远不带 HTML 实体。

## 对抗复核（4 个否定视角,catch 的真缺陷）

`f333-adversarial` workflow 跑出 2 个 high + 4 个 minor,关键两条已驱动上面的最终设计:

- **issue 0 (high·new-bug)**:字符类补 `&;` 会删 `input/Q&A.png` 类字面 `&` 文件名(端到端 repro
  实证被 `unlink`)。→ 改用实体专属否定先行(1 类)。
- **issue 5 (high·regression)**:`_resolve_bg` 无条件 `html.unescape` 破坏含 `&amp;`/`&quot;` 的
  data:/外链 URL。→ 门控 + 移到外链判断后(3 类)。
- issue 2/3/4(minor):lift/import 字面 `&` 丢资产、strip_ref 误解码 CSS 命名实体 → 已一并修。

## 回归测试

- `deck-json/tests/test_copy_assets_deck_json.py`：端到端 —— `url(&quot;input/x.png&quot;)`
  与 `&#34;` 形式过 copy-assets prune 后真文件**存活**、orphan 被剪、manifest 干净;
  **`url(&quot;input/Q&A.png&quot;)` 字面 `&` 文件名存活**(对抗回归守卫)。
- `deck-json/tests/test_entity_asset_refs.py`（新）：每个修好的扫描器符号的单元守卫 ——
  实体/数字/单引号形式产出干净路径、**字面 `&`/`;` 文件名不被截断**、data:/外链含 `&amp;`/`&quot;`
  **不被破坏**、fragment 保 bare(F-270)、CSS 命名实体不解码、lift/import 字面 `&` 捕获 +
  子串可回写。

## 影响面 / 风险

- 最终修法**保留**字面 `&`/`;` 文件名(对抗复核要求),只在真 quote-entity 处截断 ——
  零功能回退,既有 136 测试 + 21 新测全过。
- ReDoS:lift/import 的 `(?:[^'")&]|&(?!…))+?` 含有界先行的非贪婪量词,输入为有界 HTML 片段,无灾难回溯。
- 共享文件、并发 session 多(render-deck.py / copy-assets.py 常有 WIP);走隔离 worktree off
  origin/main,只动 7 源文件 + 2 测试,避免踩别人 WIP。
