# 翻译：让这份 deck 看懂多语言

## 一句话总览

这份 deck 默认是「高保真」——浏览态显示**含文字的原始渲染图**，结构化文字层
透明但可选中。但客户/海外读者要看其它语言时，有三条路，分别对应三种宿主环境。
**先看清你的发布环境，再选路**。

| 路 | 谁来译 | 需要 Chrome？ | 在沙箱 iframe 里能用？ | 怎么开 |
|---|---|---|---|---|
| 1 浏览器「翻译此页」 | 浏览器/豆包整页翻译 | 需要 | **不能**（妙笔 html-box） | `--native-text` 构建，或运行时点「🌐 翻译模式」 |
| 2 内置语言切换 | 构建时已烤好译文 | 不需要 | **能**（任何 iframe） | `--i18n i18n.json` 构建 |
| 3 不做任何特殊构建 | 用户自己复制去翻译 | 不需要 | 能 | 默认即可（透明真文字可选中） |

---

## 路 1：浏览器内置「翻译此页」

浏览器（Chrome / Edge / 豆包浏览器）的整页翻译只认**可见的真文字 DOM 节点**。
默认高保真态正文是「原图 + 透明真文字」，Chrome 看到文字透明会**灰掉翻译按钮**
（见下文硬约束），所以必须先把真文字变可见，浏览器才肯翻。

变可见的开关 = `body.xl` 这个 class（即 deck 里的「🌐 翻译模式」）：
- 构建时加 `--xl-default`，加载即进入 xl（适合直接发出去让人翻）；
- 或运行时点底栏的「🌐 翻译模式（可翻译）」按钮切到 xl。

xl 态下：`bg`（含文字图）隐藏、`bg-notext`（无文字底图）显示，文字层不再透明，
浏览器即可整页翻成任意语言。deck 还内置一个 MutationObserver 监听
`<html class="translated-ltr/rtl">` 或注入的 `<font>`，**自动识别到浏览器正在翻译**
就给 body 打上 `.translated`（用于配合 autofit 防溢出，见末节）。

**适用宿主**：顶层渲染、不沙箱 iframe 的环境——妙搭（Miaoda）、aiforce。
**不适用**：妙笔（Magic）html-box——它把 deck 关进沙箱 iframe，浏览器整页翻译
对沙箱 iframe 内部不生效。发到妙笔请走路 2。

---

## 路 2：内置语言切换（烤进 deck，到处都能用）

构建时用 `--i18n i18n.json` 把译文**烤进 deck**：build.py 为每行匹配到译文的
文字打 `data-i="<序号>"`，并把按渲染序累积的译文数组烤成 `window.__I18N`。
deck 内置「原版 / 繁體 / English / 日本語」切换，纯前端按 `data-i` 取译文替换，
**不依赖浏览器、不依赖网络、在沙箱 iframe 里照样切**——这是发妙笔 html-box 的唯一稳路。

`i18n.json` 形如 `{ 源文本: {h, e, j} }`（h=繁體 zh-Hant，e=English，j=日本語），
由 `make_i18n.py` 生成（见下文）。

---

## 路 3：不做特殊构建（默认态，复制去外部翻译）

什么都不加。默认高保真态正文是原图，但同位置盖着一层**透明却可选中**的真文字
（CSS 把 `.tb` 文字设 `color:transparent`，DOM 文字仍在）。用户可以：
框选 → 复制 → 粘到 Google / DeepL / 豆包 自己翻。零构建成本、到处可用，
代价是要手动一段段复制。

---

## build.py 的三个翻译相关 flag

- `--native-text`：默认就进**原生文字态**——显示无文字底图 + 真 HTML 文字层
  （而非含文字图），让浏览器「右键 → 翻译」能整页翻。代价是放弃像素级原始渲染。
  （body class = `native`。）
- `--xl-default`：加载即进入 `xl`「翻译模式」（文字可见），这样 Chrome 一开页就
  提供「翻译此页」。与默认高保真的区别只在初始 class，运行时仍可来回切。
- `--i18n i18n.json`：传入 `{源文本:{h,e,j}}` 译文表 → deck 多出「原版/繁體/English/
  日本語」内置语言切换；在 iframe 内也可用，不需要浏览器翻译。

> `--xl-default` 与 `--native-text` 都只是设初始 body class（`xl` 优先于 `native`），
> 不互斥于 `--i18n`——可以同时给一份 deck 烤进内置译文，又让它默认进可翻译态。

---

## 运行时与生成脚本

### scripts/faas_translate.js（运行时翻译 FaaS）

部署在妙笔（Magic）FaaS 运行时，给 `make_i18n.py` 批量翻文用。调用约定：
`POST /api/faas/<id>`，body `{texts:[...], source:"zh-CN", target:"en"}`
→ `{ok:true, translations:[...]}`（与入参等长同序）；任何失败都
**不抛异常**，返回 `{ok:false, translations:[...原文不变...]}`，让流水线优雅降级。

凭据（安全要点）：handler 从环境变量读 `LARK_APP_ID` / `LARK_APP_SECRET`
（不再硬编码任何真实凭据进仓库），并要求给该飞书应用授予 `translation:text` 权限。
缺任一变量时不抛异常，返回 `{ok:false, error:"missing_credentials", translations:texts}`。
语言码映射：`zh-CN→zh`、`zh-TW/zh-HK→zh-Hant`、`pt-BR→pt`、`zh-Hant→zh-Hant`（幂等直通）。
部署走 `publish-magic-faas` skill（或直接 `POST /api/faas`），记得在 FaaS 环境里
设置 `LARK_APP_ID` / `LARK_APP_SECRET` 两个环境变量。

### scripts/make_i18n.py（生成 i18n.json）

```
python3 make_i18n.py SOURCE [--out i18n.json] [--faas-url URL] \
        [--langs h,e,j] [--merge existing.json]
```

- `SOURCE` 位置参数，自动识别：既吃 `manifest.json`（顶层 `slides`），也吃
  `texts.json`（extract.py 的输出 `{页号:[frames]}`）。
- 按 build.py 同样的方式遍历 slides→texts→paras，收集每段非空文字、按原文去重，
  输出 `{ 源文本: {h, e, j} }`。
- **h（繁體）**：用 OpenCC `s2tw` 本地转（依赖 `opencc-python-reimplemented`，
  可选；缺了就警告并留空 h）。
- **e / j（英 / 日）**：POST 到 `--faas-url`（即上面部署的 faas_translate.js），
  每批 40 条；某批出错则该批留空 `''`（与 FaaS 的优雅降级一致）。不给 `--faas-url`
  时 e/j 全留空待人工填。
- `--merge existing.json`：先载入已有表，**只回填空字段**，保留已填 / 手工校正过的
  值——译完先人工修空格、再 `--merge` 重跑不会覆盖你的修改。
- `--langs` 只填子集（如 `h,e`）。结束打印各语言覆盖率。

---

## 「译文比中文长」怎么办

英 / 日译文常比中文长，可能溢出文本框。两层兜底：

- **autofit（grouped 收缩，下限 0.65）**：`window.__deckFit()` 对当前页每个文本框
  量算溢出，必要时按比例缩字（`--fit` 变量），同级同字号的框**同比缩**保持视觉一致，
  最多缩到 0.65 就不再缩（标题 `tb-title` 与手动改过的框不参与）。监听 resize 与
  浏览器翻译切换自动重跑。
- **全局 A- / A+（`--gfit`）**：底栏「页面字号」A-/A+ 一键整体缩放全 deck 文字
  （写入 `--gfit`，0.92/1.08 步进），并随状态持久化。

---

## 硬约束（为什么要有模式开关）

**像素级高保真的「透明真文字」态** 与 **浏览器整页翻译** 天生互斥：
Chrome 检测到文字是 `color:transparent` 就**灰掉「翻译」选项**，不肯翻透明文字。
所以无法「既保持原图像素级保真、又让浏览器直接翻」——只能二选一。这正是
「🌐 翻译模式（xl） ⇄ 🖼 高保真」模式开关存在的根本原因：平时高保真看原图，
要浏览器翻译时切到 xl 露出可见真文字。要彻底绕开这条约束，用路 2 的内置 `--i18n`
（构建期烤译文，不依赖浏览器翻译，也就不受透明文字限制）。

---

## 选路速查

- 发**妙笔 html-box**（沙箱 iframe）→ 路 2 `--i18n`（唯一稳）。
- 发**妙搭 / aiforce**（顶层、不沙箱）→ 路 1（`--native-text` 或运行时切 xl）即可，
  想离线/锁定语种也可叠路 2。
- 只是偶尔要看某段外语 → 路 3，选中复制去外部翻译，零构建。

## 端到端流程

1.（可选）部署 `scripts/faas_translate.js`（publish-magic-faas），设
   `LARK_APP_ID` / `LARK_APP_SECRET` 环境变量并授予 `translation:text` 权限
   → 得到 `${MAGIC}/api/faas/<id>`。
2. `python3 scripts/make_i18n.py manifest.json --out i18n.json --faas-url <上面的URL>`
   （h 走 OpenCC，e/j 走 FaaS；人工补/校空字段后，`--merge i18n.json` 重跑保留修改）。
3. `python3 scripts/build.py manifest.json ... --i18n i18n.json`
   → 带「原版 / 繁體 / English / 日本語」内置切换、在沙箱 iframe 内也可用的 deck。

---

## 内置 vs 浏览器翻译：对比与优先级（团队约定）

内部分享主走**妙笔**（可追踪传播链路；GitHub Pages 追踪不了，故不推荐）。**妙笔是沙箱
iframe，浏览器翻译在里面完全失效**——所以**妙笔场景只有内置翻译能用**。据此团队约定
**优先级 = 内置为主、浏览器为辅**。

| 维度 | 内置翻译（`--i18n` 烤进） | 浏览器翻译 |
|---|---|---|
| 离线 / 妙笔沙箱 iframe | ✅ 都能用 | ❌ 妙笔里无效；仅顶层环境（妙搭/本地/Pages） |
| 谁看到 | 作者预制，**人人、任意端同一份** | 每个观众各看各的，临时、刷新即没、不保存 |
| 质量可控 | 可校正到人工质量；繁體 OpenCC 逐字精确 | 取决于观众浏览器/插件，不可控、人各不同 |
| 语言覆盖 | 有限（烤死的几种，加语言要重构建） | 任意语言（长尾小语种全覆盖） |
| 原文 | 保留，多语言并存（一份文件切） | 不动原文（纯客户端覆盖层） |

**优先级在运行时的体现**：选择内置语言（≠原版）时，build 给 `#deck` 设
`translate="no"`，浏览器不会再去二次翻译已切换的文字（防"乱套"/双重翻译）；把语言
切回**原版**后移除该属性，顶层环境下浏览器翻译恢复可用，用于**长尾小语种**兜底。

**易混点**：① 浏览器翻译纯客户端、不写回 deck（非破坏性），但它也**不持久、不可分享**。
② **编辑模式 ≠ 修浏览器翻译**——编辑模式改的是「正文本身」，持久化并同步给所有人、
覆盖该框文字（原始图/源文件不受影响、可还原）；它与浏览器翻译是两条独立的东西。
③ 译文更新走「改 i18n → 重新构建 → 重新部署（覆盖同一妙笔链接）」，不是 deck 内实时改。
