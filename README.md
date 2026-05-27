# feishu-deck-h5

> **飞书风格的客户提案 deck —— 但产物是一份 `.html`,不是 `.pptx`。**
> 浏览器全屏即放映、单文件发 IM、文本编辑器改字、视觉与飞书官方母版逐像素对齐。
> 而且:**版面质量不是"靠人盯",是一层无头浏览器逐页渲染、程序化卡死的硬门禁。**

🔗 看样品 → [`examples/sample-deck.html`](examples/sample-deck.html)
（双击在浏览器打开,左右键翻页）

---

## 一句话定位

让 AI 生成一份"看起来像设计师手搓、又能被程序证明没翻车"的飞书风格演示。
不是套模板,不是导出 PPT —— 是一条 **数据驱动 + 自动校验 + 设计先行** 的生产流水线。

---

## 三个让我们和"AI 随手生成 PPT"拉开差距的地方

### 1️⃣ 你写数据,不写 CSS —— DeckJSON 流水线干掉 ~95% 的版面 bug

绝大多数"让大模型直接吐 HTML/PPT"的方案,bug 都出在 CSS:字号飘了、卡片溢出了、
`var(--x)` 没定义导致整条 `font:` 声明被浏览器静默丢弃……

我们把这层全部收口。默认走 **DeckJSON-first**:你（或 Claude）只写一份结构化
`deck.json`,渲染器 `render-deck.py` 自动产出 `index.html + texts.md + assets/`。

```bash
python3 deck-json/render-deck.py runs/<ts>/output/deck.json runs/<ts>/output/ --inline
```

- **稳**:字号、留白、阴影、CSS 变量、配色全由渲染器和框架 CSS 兜底,你碰不到出错的地方。
- **可改**:自动生成 `texts.md` 文本侧文件,销售 / 客户用记事本改文案,不碰一行标记。
- **可版本化**:`deck.json` 在 git 里 diff 干净 —— 比对两版提案是 JSON diff,不是 1500 行 HTML diff。
- **可编排**:增删、重排页面 = 改 JSON 数组,不会再出现正则吃掉 `</div>` 那种事故。

覆盖约 **95%** 的真实 deck;实在不规则的 hero 页用 `layout:"raw"` 单页 bespoke,仍在管线内、仍过校验。

### 2️⃣ 校验器会"真的把你的 deck 在无头浏览器里跑一遍"

别家是生成完**祈祷**它没歪。我们是:每次交付前 `validate.py` 作为 **硬门禁(HARD GATE)**,
任何一条 error 就拒绝交付。校验分两层:

**静态规则层**(结构 / 排版 / 配色 / 层级 / CSS 变量 / 语言 …）—— 例如:

| 族 | 它卡什么 |
|---|---|
| 排版 R06 / R20 | 正文 ≥ 24px、chrome ≥ 16px,字号必须落在 `{16,24,28,48}` 四档阶梯上 |
| 白字 R-WHITE-TEXT | 深色页正文必须 `#fff`,挡掉投影仪上"灰字直接消失" |
| 层级 R-HIERARCHY | 卡片里的归属 / 来源信息字号必须 ≤ 正文,挡掉"附注比正文还大" |
| CSS 变量 R-CSSVAR | `var(--x)` 必须解析得到,挡掉静默丢声明的连环坑 |
| 语言 R-LANG | 中文模式下扫出夹带的英文副标 / 角标 |

**视觉渲染层（Playwright,默认开启）** —— 这才是杀手锏:它**真的把每一页渲染出来量像素**:

- `R-OVERFLOW` 整页溢出 1920×1080
- `R-OVERLAP` 同级盒子边界相交(抓"某列糊到图例上")
- `R-VIS-CARD-OVERFLOW` 卡片内 `overflow:hidden` + 内容被裁 —— 抓那种**肉眼一眼看不出、文字被悄悄切掉**的密集三栏卡片
- `R-VIS-TIER / HIER / ALIGN` 计算字号、层级、等高对齐

> 一句话:**版面质量是被程序证明的,不是被人"觉得还行"放过的。**

### 3️⃣ 设计先行,而且是增量出活,不是"一把梭"

强制 **DESIGN PHASE**:拿到文案先出设计方案(版面、叙事结构、配色),
你确认后才动手;而且是**一页一页设计→执行**,不批量延迟堆到最后才发现整体翻车。
配套 11 套**叙事模式**(3+1 hero、verdict 判定矩阵、做/不做 boundary、北极星地图……),
直接把"飞书内部那套结构化论证"变成可复用的版面骨架。

---

## 为什么不直接用 PowerPoint

| | PowerPoint `.pptx` | feishu-deck-h5 `.html` |
|---|---|---|
| 文件大小 | 几十 MB 起步 | 24–360 KB |
| 需要 Office license | 是 | 否(任何浏览器都能开） |
| 飞书 / IM 转发 | 经常变形 | 单文件,对方双击即看 |
| AI 直接生成 | 很难做出像样的 | 天然适合(HTML 是 LLM 母语) |
| 视觉一致性 | 靠人盯 | **程序化硬门禁 + 无头浏览器逐页渲染校验** |
| 版本管理 / 协作 | git 看不了 diff | `deck.json` / HTML 标准 git diff,PR review 友好 |
| 产品截图 | 贴 PNG,缩放糊 | **HTML 重建,任意缩放都清晰、字体跟 deck 一致** |

不是替代 PPT 的所有场景 —— 客户硬要 `.pptx` 还是给 `.pptx`。但售前 / 内训 / 产品提案
这类 **多人迭代 + 多渠道分发** 的场景,HTML 几乎完胜。

---

## 它还顺手解决了这些

- **手机能看** —— 自动切换纵向滚动浏览,发链接给客户立刻能预览。
- **视觉跟飞书品牌逐像素对齐** —— 13 种 layout 全部从官方 `.thmx` 母版抽出,色值 / 字号 / 留白都是母版坐标。
- **31 个 `ui-*` 原语** —— `.ui-window` / `.ui-msg` / `.ui-kpi` / `.ui-tabs` …… 用 HTML 重建产品截图,而不是贴 PNG。
- **32 个 richness 原语** —— `.kpi-strip` / `.cta-box` / `.pullquote` / `.ui-wave` …… 专门防止 AI 交付"骨架感"的寡淡 deck。
- **飞书产品官方 logo** —— aily / 多维表格 / 妙搭 / 飞书会议 / 飞书人事 / 集成平台 全套,无需自己画 SVG。
- **Native slide lift** —— 把一张现成 slide 原样搬进来,自动归一化进体系。
- **媒体进页自动播放 / 重启 + 自动声音**、**中文换行平衡 / 末行孤字防治**、**性能预算硬约束**(`audit_perf`)。
- **每次 run 自动产出 `FEEDBACK.md` / `PROMPTS.md`** —— skill 自身可被持续打磨。

---

## 支持哪些 layout

**13 种基础 layout + 3 种特殊**(`raw` / `replica` / `iframe-embed`)= schema 内 15 种,覆盖一份典型客户提案从封面到封底的所有页型:

| Layout | 适合什么内容 |
|---|---|
| **cover** | 封面 —— 飞书母版花朵背景,标题在左、配图在右 |
| **agenda** | 议程 —— 4–8 项编号,双列堆叠 |
| **section** | 章节分隔 —— 巨型序号 + 章节标题 + 产品 pill |
| **content-3up** | 三大能力 / 三个支柱 —— 三卡并列 |
| **content-2col** | 一段叙事 + 配图 / UI 截图 —— 左文右图 |
| **quote** | 客户证言 / 金句 —— 居中大字 + 来源 |
| **stats** | 4-up KPI —— 四个并列数字 + 单位 + 来源 |
| **big-stat** | 单个英雄数字 —— 例如 "30 万人" + 旁边一段说明 |
| **image-text** | 全屏照片 + 左下角文字 —— 客户现场 / 门店 / 工厂 |
| **table** | 对比表 —— 飞书 vs 传统套件这种比较矩阵 |
| **timeline** | 横向时间轴 —— 4–6 个里程碑 |
| **process** | 流程步骤 —— 3–6 步带右指箭头 |
| **end** | 封底 —— 飞书品牌花朵背景 + CTA + 联系方式 |
| `raw` / `replica` / `iframe-embed` | hero 高光页 / 母版复刻 / 嵌入原型,仍在管线内、仍过校验 |

完整规格 + 11 叙事模式 + UI 原语清单见 [SKILL.md](skills/feishu-deck-h5/SKILL.md)。

---

## 看更多例子

- [`examples/sample-deck.html`](examples/sample-deck.html) —— 12 张 slide 涵盖全部基础 layout
- [`preview-dark.html`](preview-dark.html) —— 设计令牌(颜色 / 字号 / 渐变)+ 组件 gallery
- [`templates/slide-recipes.html`](templates/slide-recipes.html) —— 每种 layout 的 reference 实现

---

## 怎么开始用

**让 Claude 帮你装 + 帮你做**,一句话:

> "帮我安装 feishu-deck-h5 skill:https://github.com/FuQiang/feishu-deck-h5,
> 装完帮我做一份关于〔你的主题〕的 deck"

Claude 会读 [INSTALL.md](INSTALL.md) 走标准安装流程(plugin marketplace 或 install.sh),
然后按 [SKILL.md](skills/feishu-deck-h5/SKILL.md) 的规范、走 DeckJSON 流水线生成 deck。

---

## 想看怎么搭出来的

| 内容 | 文档 |
|---|---|
| 安装路径(marketplace / install.sh / 手动 clone） | [INSTALL.md](INSTALL.md) |
| DeckJSON 流水线 + 13+3 layouts + 11 叙事模式 + UI/richness 原语 + 校验规则 | [SKILL.md](skills/feishu-deck-h5/SKILL.md) |
| 9-section 完整设计系统 | [DESIGN.md](DESIGN.md) |
| 业务规则 | [BUSINESS_RULES.md](BUSINESS_RULES.md) |

---

## License

MIT —— 见 [LICENSE](LICENSE)。

`assets/lark-*.png/jpg` 是 ByteDance / 飞书的官方品牌资产,版权归飞书设计团队,
不在本仓库 MIT 许可范围内,第三方使用前请遵守飞书品牌规范。
