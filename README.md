# feishu-deck-h5

> **HTML 版飞书风格汇报材料系统** · 不是 .pptx，是用 HTML 完整模仿 PPT 视觉的 deck 生成技能。

把飞书母版 2025（深色通用）.thmx 深度解析成 design system，生成跟 PPT 视觉无差别的 HTML deck，
单文件支持 16:9 PC 全屏 + 移动端浏览，内置 55 项规范的程序化自检 (`validate.py`)，
零外部依赖（除浏览器和 Python 3）。

```
Linked deck (default):    24 KB · 浏览器外部加载 assets · 首屏快
Inlined deck (opt-in):   361 KB · 单文件交付 · 邮件/IM 用
Self-check items:         55  · validate.py exit 0 = 通过
audit/check functions:    20  · CSS / JS / 文档全覆盖
```

---

## Quick start

```bash
# 1. 克隆
git clone git@github.com:FuQiang/feishu-deck-h5.git
cd feishu-deck-h5

# 2. 默认构建（linked, 24 KB）
bash build.sh

# 3. 单文件构建（inlined, 361 KB）
bash build.sh --inline

# 4. 跑自检
python3 assets/validate.py examples/sample-deck.html
python3 assets/validate.py examples/sample-deck-inline.html --strict

# 5. 浏览器打开
open examples/sample-deck.html
```

---

## 仓库结构

```
feishu-deck-h5/
├── SKILL.md                   ← 主文档：13 layouts + 55 自检项 + 所有规范
├── DESIGN.md                  ← 9-section design system（awesome-design-md 格式）
├── build.sh                   ← 构建脚本（默认 linked，--inline 出单文件版）
├── assets/
│   ├── feishu-deck.css        ← 全部 design tokens + layouts + decor + UI primitives
│   ├── feishu-deck.js         ← 运行时（scale-fit, fullscreen, idle-fade, etc.）
│   ├── validate.py            ← 程序化自检（20 个 audit/check 函数）
│   ├── lark-logo.png          ← 飞书品牌资产（从 .thmx 母版抽取）
│   ├── lark-logo-mono-white.png
│   ├── lark-cover-bg.jpg
│   ├── lark-section-bg.jpg
│   ├── lark-content-bg.jpg
│   └── lark-slogan.png
├── templates/
│   ├── _shell.html            ← 空 deck 骨架，复制改名即可
│   └── slide-recipes.html     ← 13 layouts 全部示范
├── examples/
│   ├── sample-deck.html       ← 默认交付样品（linked, 24 KB）
│   └── sample-deck-inline.html← 单文件版（inlined, 361 KB，opt-in）
├── preview-dark.html          ← 设计令牌 + 组件可视化
└── _body.partial.html         ← build.sh 用的 body 片段
```

---

## 13 个 layouts

| Layout              | 用途 |
|---------------------|---|
| `cover`             | 封面（飞书母版花朵背景，左半部文字） |
| `agenda`            | 议程（号码与标题等字号） |
| `section`           | 章节分隔（大序号 + 标题 + 产品 pill） |
| `content-3up`       | 三卡并列 |
| `content-2col`      | 文字 + 视觉双栏 |
| `quote`             | 金句 |
| `stats`             | 4-up KPI |
| `big-stat`          | 单大数字 |
| `image-text`        | 全屏图 + 文字 |
| `table`             | 对比表格 |
| `timeline`          | 横向时间轴 |
| `process`           | 步骤流程 |
| `end`               | 封底带 slogan |

外加 11 个叙事模式（A–K）和 27 个 UI 原语（`.ui-window` / `.ui-grid` / `.ui-msg` 等）— 详见 SKILL.md。

---

## 验证

`assets/validate.py` 会在不需要浏览器的情况下静态校验 HTML：

```bash
python3 assets/validate.py path/to/your-deck.html
# exit 0 = 通过 · exit 1 = 失败 · exit 2 = 文件未找到

python3 assets/validate.py path/to/your-deck.html --strict
# 把 warnings 提升为 errors，作为最终交付前的硬门槛
```

20 个 audit/check 函数覆盖 49 项规范 + 6 项性能预算。完整列表见 `SKILL.md` 自检清单。

---

## CI

`.github/workflows/validate.yml` 会在每次 push 和 PR 时跑一遍 build + validate（默认和 strict 双模式）。
主分支 always-green 不让 perf 退化或规范违反混进来。

---

## 设计原则

完整规范在 [SKILL.md](./SKILL.md) 和 [DESIGN.md](./DESIGN.md)。简单说：

1. **每张 slide 1920×1080 设计画布**，运行时缩放
2. **彩色 logo 永远默认**，mono 是 opt-in 边缘 case
3. **页头标题永远单行**（cover/image-text/end 的 hero 双行除外）
4. **Title-only 页面隐藏 eyebrow**，让标题与 logo 同基线
5. **固定形状 layout 默认垂直居中**，pipeline/timeline/process 是 fill 例外
6. **Layout 与 decor 正交** — `data-decor` 装饰可与任意 layout 组合，不动结构
7. **Variant 必须重声明所有结构属性** — cascade 不会自动重置
8. **UI 截图必须 HTML 重建** — 用 `.ui-*` 原语而不是贴 PNG
9. **演示模式自动全屏**，顶部进度条 + 底部控件 + 闲置淡出
10. **性能预算硬规则** — base64 ≤ 100 KB / blur ≤ 10px / 单 ResizeObserver / AbortController 清理 / contain + will-change

---

## 致谢

- **飞书母版 2025（深色通用）** — 设计参考来自 ByteDance / 飞书设计团队
- **awesome-design-md** ([VoltAgent](https://github.com/VoltAgent/awesome-design-md)) — DESIGN.md 9-section 格式来源
- **Lucide** — 图标风格参考（生产建议替换为 ByteDance IconPark）

---

## License

MIT — see [LICENSE](./LICENSE).

注意：`assets/lark-*.png/jpg` 是 ByteDance / 飞书的品牌资产，不在 MIT 之内。仓库公开化前必须移除或替换。
