# feishu-deck-h5

> **飞书风格的客户提案 deck，但是 HTML 不是 PPT。**
> 浏览器全屏放映、单文件发 IM、文本编辑器改字、视觉与飞书母版完全对齐。

🔗 看样品 → [`examples/sample-deck.html`](examples/sample-deck.html)
（双击在浏览器打开，左右键翻页）

---

## 这是什么

把飞书母版 2025（深色通用）的 PowerPoint 视觉**完整搬到 HTML**，生成的就是一份
`.html` 文件，但它表现得跟 PPT 一样：

- **浏览器全屏 = 16:9 演示模式** — 左右键翻页、底部进度条、闲置自动隐藏控件
- **手机能看** — 自动切换成纵向滚动浏览，发链接给客户立刻能预览
- **单文件可直接转发** — 飞书 / 邮件 / IM 任何途径，对方双击就开，不用装 Office
- **文字用记事本改** — 配套 `texts.md` 文本侧文件，改文字不动布局
- **视觉跟飞书品牌完全对齐** — 13 种 layout 全部从官方 .thmx 母版抽出，色值/字号/留白都是母版坐标

---

## 为什么不直接用 PowerPoint

| | PowerPoint .pptx | feishu-deck-h5 .html |
|---|---|---|
| 文件大小 | 几十 MB 起步 | 24-360 KB |
| 需要 Office license | 是 | 否（任何浏览器都能开） |
| 飞书/IM 转发 | 经常变形 | 单文件，对方双击即看 |
| AI 直接生成 | 很难做出像样的 | 天然适合（HTML 是 LLM 母语） |
| 视觉一致性 | 靠人盯 | 55 项规范程序化自动校验 |
| 版本管理 / 协作 | git 看不了 diff | 标准 git diff，PR review 友好 |

不是替代 PPT 所有场景——客户硬要 .pptx 还是给 .pptx。但售前/内训/产品提案
这些**多人迭代 + 多渠道分发**的场景，HTML 几乎是完胜。

---

## 谁在用 · 4 个高频场景

### 1. 售前给客户做提案 deck
PDF/Word 输入 → Claude 按规范生成 → 浏览器全屏走全程。
客户那边发 IM 链接看预览、要 PPT 就直接 inline 单文件版发过去。

### 2. PMM 做产品发布材料
13 种 layout 已经把"封面 / 议程 / 章节页 / 三卡并列 / 数据 / 客户证言 / 流程 / 时间轴"
全部封好。新内容塞进去就是品牌一致的输出，不用每次重新调字号留白。

### 3. 内训讲师做培训材料
texts.md 文本侧文件给非技术同事用——他们不用碰 HTML，只改一份 markdown
就能更新整份 deck 的文字。

### 4. 想把旧 PDF 升级成 HTML 演示
源 PDF 直接渲染成图片做底，外层套上 feishu-deck-h5 的演示外壳（全屏 / 翻页 /
移动端）。1:1 还原视觉、零信息损失、几十秒出活。

---

## 看更多例子

- [`examples/sample-deck.html`](examples/sample-deck.html) — 12 张 slide 涵盖全部 13 种 layout
- [`preview-dark.html`](preview-dark.html) — 设计令牌（颜色 / 字号 / 渐变）+ 组件 gallery
- [`templates/slide-recipes.html`](templates/slide-recipes.html) — 每种 layout 的 reference 实现

---

## 怎么开始用

**让 Claude 帮你装 + 帮你做**，一句话：

> "帮我安装 feishu-deck-h5 skill：https://github.com/FuQiang/feishu-deck-h5，
> 装完帮我做一份关于〔你的主题〕的 deck"

Claude 会读 [INSTALL.md](INSTALL.md) 走标准安装流程（plugin marketplace 或 install.sh），
然后按 [SKILL.md](skills/feishu-deck-h5/SKILL.md) 的规范生成 deck。

---

## 想看怎么搭出来的

| 内容 | 文档 |
|---|---|
| 安装路径（marketplace / install.sh / 手动 clone） | [INSTALL.md](INSTALL.md) |
| 13 layouts + 11 叙事模式 + 27 UI 原语 + 55 自检项 | [SKILL.md](skills/feishu-deck-h5/SKILL.md) |
| 9-section 完整设计系统 | [DESIGN.md](DESIGN.md) |

---

## License

MIT — 见 [LICENSE](LICENSE)。

`assets/lark-*.png/jpg` 是 ByteDance / 飞书的官方品牌资产，版权归飞书设计团队，
不在本仓库 MIT 许可范围内，第三方使用前请遵守飞书品牌规范。
