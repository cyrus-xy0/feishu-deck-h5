---
name: pptx-to-editable-html
description: |
  把 .pptx（或 Keynote 导出的 PPTX）转成「浏览 100% 保真 + 文字可编辑」的单文件
  HTML deck。核心是**双背景架构**：浏览模式显示含文字的原始渲染图（字体/排版
  与 PPT 完全一致），按 E 进入编辑模式才切到无文字底图 + 结构化可编辑文字框；
  改过的文字框用「无文字底图的同位置裁片」做背景，精确遮住原图文字（无重影）。
  自带演示导航、目录（缩略图点击跳转 / 多选拖拽排序 / 单页隐藏）、页码直跳、
  本地保存与导出 HTML、视频(点播)与 GIF(自动循环) overlay、CJK 字体子集内嵌。
  可选挂 FaaS 存储后端（--faas）实现「共享同一份、跨设备、改了即存」——专治妙笔
  html-box 沙箱 iframe 禁用 localStorage 导致存不住的问题。
  【网页翻译版】内置「可见真文字 + 浏览器翻译此页」模式（🌐 翻译模式 / body.xl）：正文
  平时是原图、一点翻译就显示可被浏览器/豆包整页翻译的真文字；配 --fit/--gfit autofit
  防溢出、bg 懒加载防首屏黑屏。专为发布到飞书妙搭（顶层渲染、可浏览器翻译）而做。

  触发词：「PPT 转可编辑 HTML」、「PPTX → 可编辑网页」、「PPT 转 HTML 但文字
  要能改」、「双背景可编辑 deck」、「把这个 PPT 做成能在线改文字的网页」。

  与 keynote-to-html 的区别：keynote-to-html 走 .key→iWA 纯结构化重建（文字直接
  渲染，字体/排版会失真）；本 skill 走 .pptx + 双背景，浏览是原图所以零失真，
  结构化文字只在编辑态出现。两者可独立使用。

  失真与边界（不要因此阻断）：
    · 浏览模式 = 原始渲染图，零失真。
    · 编辑模式文字用 CJK web 字体（子集化原字体最佳；否则回退 PingFang），
      字形可能与原图有细微差异——这是编辑态，可接受。
    · 自定义 Freeform 形状、复杂阴影/渐变、入场动画：浏览靠原图保真，无需重建。
    · 媒体音轨探测决定 GIF(无声→自动循环) 还是视频(有声→点播)。
---

> # ⚠️ DEPRECATED / 已退役 — 图片(双背景)路线
>
> **本技能（pptx-to-editable-html，含 manifest / 双背景图 / 截图 / 整页渲染图路线）已退役。**
> 按用户「完全不要图」的决定,PPTX 现在统一走:
>
> **parser → build_pptx → 结构化 `canvas` deck.json(代码重建、无截图)。**
>
> 啃不动的页(原生图表 / SmartArt / OLE)产纯文字占位 + 汇总报告页号,由用户自己重做那几页。
> 见 `skills/feishu-deck-h5/subskills/parser/SKILL.md` 与
> `skills/pptx-to-deck/assets/build_pptx.py`(continuator;旧的 `pptx-to-html` 嵌套路径已提升为顶层 `pptx-to-deck`)。
>
> 代码仍保留(未删除)仅作存档参考;**请勿用于新任务**。build_pptx 已是 python-pptx 原生
> OOXML 抽取,无需从本技能搬运任何抽取能力。
>
> ---
> **2026-06-04 归档**:本目录已 `git mv` 到 `skills/_deprecated/`,从 `skills/` 顶层撤出,
> 不再作为可加载 skill。`.pptx` 的活路径 = `pptx-to-deck`;`.key` = `keynote-to-html`。
>
> **保留它的唯一理由 = 4 项 `pptx-to-deck` 至今没有、且绑死在双背景架构上的「蓝图能力」**,
> 将来要做「飞书妙搭可翻译 deck」时直接抄这里、不要重新发明:
> 1. **CJK 字体子集化** — `scripts/subset_font.py`(fonttools+brotli,12MB→~200KB woff2,仅用到的字形)
> 2. **离线多语言切换** — `scripts/make_i18n.py` + OpenCC s2tw 繁体 + Lark `translation:text` API
>    批处理(3 并发 + 指数退避),可在妙笔 iframe 沙箱内切换(浏览器翻译被禁时仍可用)
> 3. **FaaS 跨设备共享持久化** — `scripts/faas_store.js`(browser↔TOS,绕过 html-box 沙箱禁 localStorage)
> 4. **浏览器「网页翻译」模式** — `body.xl` 可见真文字层 + `--fit/--gfit` 防溢出,专为妙搭顶层渲染
>
> 这 4 项不可直接移植进 deck.json 模型(需重写),所以归档保留作蓝图,而非搬进 build_pptx。

# pptx-to-editable-html — PPT 转 HTML 技能（网页翻译版）

> **网页翻译版**：在「双背景可编辑」基础上加了一套**可见真文字层 + 浏览器翻译**模式，
> 专为发布到**飞书妙搭**（顶层渲染、能用浏览器/豆包「翻译此页」）而做。详见文末
> 「部署到妙搭」与「网页翻译版要点」。

## 这个 skill 做什么

给一个 `.pptx`，产出一个自包含 HTML：**看起来和 PPT 一模一样（浏览模式是原始
渲染图），但按 `E` 就能逐框编辑文字**。编辑改动可保存到浏览器、导出成新 HTML。

为什么这样设计：纯结构化重建（把每个文字框用 HTML 重画）永远会在字体、对齐、
自动缩放、自定义形状上失真。双背景架构把"保真"和"可编辑"解耦——浏览永远是
真渲染图，结构化文字层只在编辑时出现，改过的框用无文字底图裁片遮住原文字。

## 依赖

- **python-pptx**（`pip install python-pptx`）— 解析 pptx 文字结构
- **Keynote**（macOS）— 把 pptx 渲染成 PDF（正确渲染中文字体；PowerPoint 沙盒
  写不了 /tmp，LibreOffice 缺商业字体会回退难看）。也可用 PowerPoint 手动导 PDF。
- **swift**（macOS 自带）— PDF→高清 PNG（`render_pdf.swift`）
- **fonttools + brotli**（`pip install fonttools brotli`）— 字体子集化（可选但强烈推荐）
- **ffmpeg/ffprobe**（可选，仅当有视频/GIF）— 媒体提取/转码/音轨探测
- **Pillow**（`pip install Pillow`，可选）— 文字色恢复 / 无文字底图修复（`recover_colors.py` / `repair_notext_bg.py`）
- **opencc-python-reimplemented**（`pip install opencc-python-reimplemented`，可选）— 生成繁體译文（`make_i18n.py`）
- 一个能放静态资源的图床/对象存储（图片和字体走外链；或改成本地相对路径自部署）

## 完整流程

设 `D=deck.pptx`，工作目录 `W=./work`，图床 `HOST=https://your-host/deck`。

### 1. 提取文字 + 生成无文字 PPTX
```bash
python3 scripts/extract.py "$D" --out "$W"
# → W/texts.json（每页文字框：位置/段落字号/颜色/对齐/内边距/垂直锚点）
# → W/text-stripped.pptx（清空所有文字、保留全部装饰）
```
占位符标题字号常继承自母版（python-pptx 读不到），若有上一版/keynote 抽的
字号数据可 `--fill-sizes prior.json` 按文字匹配补全。

### 2. 渲染两套背景图（含文字 + 无文字）
```bash
# 含文字原图（浏览模式用）
osascript scripts/keynote_export.applescript "$PWD/$D" /tmp/withtext.pdf
swift scripts/render_pdf.swift /tmp/withtext.pdf "$W/bg" 1920
# 无文字底图（编辑模式用）
osascript scripts/keynote_export.applescript "$PWD/$W/text-stripped.pptx" /tmp/notext.pdf
swift scripts/render_pdf.swift /tmp/notext.pdf "$W/notext" 1920
# 体积优化：PNG→JPEG（照片页效果好、加载快）
for f in "$W"/bg/*.png; do sips -s format jpeg -s formatOptions 88 "$f" --out "${f%.png}.jpg" >/dev/null; done
for f in "$W"/notext/*.png; do sips -s format jpeg -s formatOptions 88 "$f" --out "${f%.png}.jpg" >/dev/null; done
```

### 3.（可选）字体子集化
```bash
python3 scripts/subset_font.py /path/to/Font-Regular.otf "$W/texts.json" "$W/font/reg.woff2"
python3 scripts/subset_font.py /path/to/Font-Bold.otf    "$W/texts.json" "$W/font/bold.woff2"
```

### 4.（可选）提取视频/GIF
```bash
python3 scripts/extract_media.py "$D" --out "$W/media"
# → W/media/files/*, W/media/media-raw.json（含音轨判定的 gif 标记）
# 上传 files/ 后把每条的 "file" 改成 "url"，存成 media.json
```

### 5. 上传图片/字体/媒体到图床
把 `W/bg`、`W/notext`、`W/font`、`W/media/files` 传到 `HOST` 对应路径。
（`scripts/upload_to_url.sh` 是 TOS 预签名 PUT 的示例，按你的图床改。）

### 6. 组装 manifest + 生成 HTML
```bash
python3 scripts/make_manifest.py "$W/texts.json" --out "$W/manifest.json" \
  --img-base "$HOST" \
  --bg-pattern 'bg/page-{n:03d}.jpg' --notext-pattern 'notext/page-{n:03d}.jpg' \
  --title '我的演示' \
  --font-base "$HOST/font" --font-reg reg.woff2 --font-bold bold.woff2 \
  --media "$W/media.json"   # 可选；--skip 58,60 可删页
python3 scripts/build.py "$W/manifest.json" --out "$W/index.html"
```
`index.html` 即成品：本地双击即可用，或部署到任意静态托管 / 妙笔 html-box。

### 6.5 增强脚本（可选，发布前常用）
都在 `scripts/`，各自的「为什么 / 怎么用」详见对应 reference：
- **照片发虚 → 高清重渲**：把 step 2 的 `1920` 改成 `2880`/`3840` 重渲 bg 与 notext（**两张必须同 width**），再 JPEG q88、manifest 指向高清图。见 `references/image-quality.md`。
- **文字变白/不可见 → 颜色恢复**：`python3 scripts/recover_colors.py "$W/manifest.json" --out "$W/manifest-colored.json"`（python-pptx 抽不到主题色 → null → 白；从 bg/notext 差分反推真实色。在 make_manifest 之后、build 之前跑）。
- **无文字底图丢图形 → 修复**：`python3 scripts/repair_notext_bg.py "$W/manifest.json"`（diff 标记受损页并重建；首选其实是从只剥文字的源重渲，见 image-quality.md）。
- **多语言 → 内置语言切换**：`python3 scripts/make_i18n.py "$W/manifest.json" --out "$W/i18n.json" [--faas-url <faas_translate.js 部署后的 URL>]` 生成 `{源文:{h,e,j}}`，再 `build.py … --i18n "$W/i18n.json"`。三条翻译路径与 `--native-text`/`--xl-default` 见 `references/translation.md`。
- **金句压暗页**：`make_manifest.py --dim '58:0'`（第 58 页第 0 个文本框为高亮金句，整页其余文字压暗）。
- **发布前体检**：`node scripts/qa_audit.js --url "file://$PWD/$W/index.html" --pages 1-99 --out "$W/qa"`（CDP 多页截图，截图结论需再核验）。见 `references/qa-audit.md`。

### 7.（可选）共享后端持久化 —— 改动跨设备、可分享
默认改动存浏览器 localStorage（仅本机本浏览器；**且妙笔 html-box 的沙箱 iframe
禁用 localStorage，发布后存不住**）。要让「改了即存、关了再开还在、发链接给别人
对方看到最新版、还能继续改同一份」，挂一个 FaaS 存储后端（中转 TOS）：
```bash
# 1) 部署存储函数（用 publish-magic-faas skill，或直接 POST /api/faas）
node <publish-magic-faas>/publish.mjs --token "$MAGIC_TOKEN" \
  --file scripts/faas_store.js --name deck_store
#   → 拿到 record id，调用地址 = https://magic.solutionsuite.cn/api/faas/<id>
# 2) 生成 HTML 时带上 --faas（也可在 make_manifest 时 --faas 烤进 manifest）
python3 scripts/build.py "$W/manifest.json" --out "$W/index.html" \
  --faas "https://magic.solutionsuite.cn/api/faas/<id>"
```
带了 `--faas`：浏览器加载时从 FaaS 拉取共享状态，编辑自动保存（防丢）、💾 保存即
写回服务端。不带 `--faas`：退回 localStorage + 导出 HTML 的本机模式（原行为不变）。
原理与 CORS 细节见 `references/backend-persistence.md`。

## 交互（成品 HTML）

- 翻页：← → / 空格 / PageUp·Down / Home·End；底部页码框可**直接输入页号跳转**；`F` 全屏
- **纯净投屏模式**：URL 加 `#proj`（或 `#bare`/`#clean`/`#kiosk`）→ **隐藏底部工具栏（含页码栏）**，投屏/`--app` 放映时只剩正文（翻页用方向键）。配 Chrome `--app="<url>#proj" --start-fullscreen` 即得无浏览器外壳 + 无工具栏的纯幻灯片
- **🌐 翻译模式**：底栏按钮在「高保真（原图）」↔「翻译模式（无字底图 + 可见真文字）」间切换。**进入翻译模式后，翻译走「内置为主、浏览器为辅」**：
  - ① **内置翻译（主）**——底栏**「语言」下拉**（原版 / 繁體 / English / 日本語），用 `--i18n` 烤进的译文**离线、即时、沙箱 iframe（妙笔）里也能切**，人人看到同一份。**选了内置语言会给 deck 打 `translate="no"`**，挡掉浏览器二次翻译。仅在 `--i18n` 构建时出现。
  - ② **浏览器翻译（辅）**——把「语言」切回**原版**后，可在**顶层环境**（妙搭/本地/Pages）用浏览器/豆包「翻译此页」翻**任意长尾小语种**；**妙笔沙箱 iframe 里浏览器翻译无效**（那里只有内置可用）。
  翻译态还有全局 **A-/A+** 整体字号（防译文变长溢出）。
- **E**：切换编辑模式（也可点底部 ✎ 按钮），**原始字号**所见即所得
- 编辑态**改框**：点左上 **✥** 选框（可连点多选）、拖 ✥ 移动、右下 **◢** 改大小、工具条 **左/中/右**对齐与 **A-/A+** 字号，均对所选生效
- **▦ 目录**：缩略图点击跳转；**⌘/Ctrl 或 Shift 点击多选**后**整组拖动排序**；
  每图右上**眼睛**隐藏/显示该页（隐藏页播放时自动跳过）
- **保存**：**退出编辑即自动保存**——挂 `--faas` 时写回服务端（所有人可见最新版、跨设备防丢），否则存本浏览器 localStorage（本版无独立保存/导出按钮）

## 部署到妙搭（飞书 Miaoda / aiforce，可浏览器翻译）

妙搭是**顶层渲染**（不像妙笔 html-box 那样再套 sandbox iframe），所以**浏览器「翻译此页」
/ 豆包划词能直接翻整页**——这是「网页翻译版」的关键落点。用 `lark-apps` skill 的 `lark-cli` 发布：

```bash
# 入口文件必须叫 index.html；--path 必须是 cwd 内相对路径
# 首次需飞书授权一次：lark-cli auth login --domain apps（scope 含 spark:app:publish/write）
lark-cli apps +create --name "我的演示" --app-type HTML              # 首次：建应用拿 app_xxx
cd <部署目录的父目录> \
  && lark-cli apps +html-publish --app-id app_xxx --path ./<部署目录> --as user
# 返回 {"ok":true,"data":{"url":"https://bytedance.aiforce.cloud/app/app_xxx"}}
```

- 同一 `--app-id` 重发 = **原地更新同一链接**，URL 不变（发前先备份 index.html，发错可回滚重发）。
- aiforce 链接对浏览器是 **OAuth 登录墙**（匿名 curl 会 302 到 `accounts.feishu.cn`），但
  `lark-cli` 用授权过的 user token 发布**不受墙影响**——Agent 能发；发完只能靠人在浏览器硬刷新眼检。

## 网页翻译版要点 / 维护经验

- **翻译优先级 = 内置为主、浏览器为辅（团队约定）**：① **内置翻译**（底栏「语言」下拉，`--i18n` 烤进的译文，**离线/即时/沙箱 iframe 也能切**，原版/繁體/English/日本語，人人看到同一份）是主路径——**发妙笔（沙箱 iframe）时浏览器翻译失效，内置是唯一选择**；选了内置语言会给 deck 打 `translate="no"` 防浏览器二次翻译。② **浏览器翻译**仅作辅助：切回「原版」后，在**顶层环境（妙搭/本地/Pages）**可翻**长尾小语种**，质量取决于观众浏览器、不保存、各看各的。内置译文由 `make_i18n.py` 生成（OpenCC 繁體 + `faas_translate.js` 飞书翻译批译），详见 `references/translation.md`。
- **可见真文字层（xl / 翻译态）**：底栏 🌐「翻译模式」按钮切 `body.xl`；平时显原图(`.bg`)，
  xl 态切到无字底图(`.bg-notext`) + 重建真文字供整页翻译。浏览态靠
  `body:not(.edit):not(.xl) .tb:not(.dirty):not(.tb-title) .ln{color:transparent}` 把重建
  文字藏起（只露原图）；`.tb-title` 例外（标题两态都显重建文字、靠 `.tb` 的 `--nt` 裁片背景盖原图，无重影）。
- **autofit 兜底**：`.ln` 字号 = `calc(cqw(size) * var(--fit,1) * var(--gfit,1))`；`__deckFit`
  对非 `.tb-title` 框测溢出降 `--fit`(floor 0.65)；`--gfit` 是底栏 A+/A- 全局字号。**标题
  (`.tb-title`) 被排除**——长标题在重建字体(PingFang 比原字宽)下会换行，需手工调小该框 size 或加宽 width。
- **懒加载**：`bg`/`bg-notext` 用 `data-src`，`loadSlideImgs(当前±相邻)` 才真加载，防首屏一次性拉全图黑屏。
- **段内高亮（per-run color）**：manifest 每段 `paras` 只有单一 color/size，**装不下段内
  混排强调**。要给「122+」这类局部上色/加大，**直接往成品 HTML 的 `.ln` 注
  `<span style="color:#XX;font-weight:700;font-size:1.3em">…</span>`**——innerHTML 模型支持、
  浏览态被 `.ln *{transparent}` 一并藏起、只在 xl/编辑态显、无重影；build.py 走 `H.escape`
  不支持，故此法是**部署 HTML 级补丁**（改完重新 `+html-publish`）。
- **本版已移除演示者模式**（按妙搭场景精简；HEAD 之前的 presenter 视图/放映窗在「网页翻译版」不带）。

## 架构细节与专题
- `references/architecture.md` — 双背景、三态（高保真/翻译/编辑）、box 编辑、autofit、懒加载、持久化
- `references/manifest-schema.md` — manifest 字段（含 `dimothers`/`over`、i18n 说明）
- `references/translation.md` — 三条翻译路径、`--i18n`/`--native-text`/`--xl-default`、FaaS 与 `make_i18n.py`
- `references/image-quality.md` — 高清重渲（锐化）、`recover_colors.py`、`repair_notext_bg.py`
- `references/qa-audit.md` — `qa_audit.js` 发布前多页截图体检
- `references/backend-persistence.md` — `--faas` 共享后端原理与 CORS
