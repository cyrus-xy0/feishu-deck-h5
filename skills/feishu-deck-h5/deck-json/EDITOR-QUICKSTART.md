# deck-editor 快速上手

可视化编辑 feishu-deck-h5 deck 的本地工具。**零依赖** —— 只用 macOS / Linux 自带的 Python 3.11+。

---

## 第一次使用 · 3 条路径(挑你最熟悉的)

### 路径 A · 最简单 · macOS 双击 (推荐给非技术同事)

**适合**:从来没碰过命令行,只想看到一个能点的图标。

**步骤**:

1. **从同事那拿一份本仓库的 clone**
   - 如果你装了 [GitHub Desktop](https://desktop.github.com/) (推荐),它有图形界面 clone
   - 或者让同事 zip 整个 `feishu-deck-h5/` 目录发你,解压
   - 最终你的 Mac 上要有一个像 `~/Documents/GitHub/feishu-deck-h5/` 的目录

2. **找到双击启动器**
   - Finder 打开 `~/Documents/GitHub/feishu-deck-h5/skills/feishu-deck-h5/deck-json/`
   - 找到一个叫 `deck-editor.command` 的文件 (有个齿轮图标)
   - **双击它**

3. **第一次双击会弹安全提示**(macOS 默认不允许下载的脚本自动运行)
   - 弹"无法打开,因为来自身份不明的开发者" → 关掉
   - 在 Finder 里 **按住 Ctrl + 单击** 该文件 → 选"打开"
   - 再弹一次 → 点 "打开"
   - 之后每次双击就直接跑了

4. **浏览器自动打开** http://127.0.0.1:XXXX/?token=XXX
   - **左**:slide 列表(拖动可重排)
   - **中**:preview(双击文字直接改)
   - **右**:inspector(各种字段编辑)

5. **退出**:关闭弹出的 Terminal 窗口 (顶上有 ⏚ 标题的小窗口)

**把 `deck-editor.command` 拖到 Dock 右侧 Stack 区** → 以后 Dock 点一下就开。

#### 用别的 deck.json 怎么办?

- **双击启动器** = 打开"最近修改过的" deck.json
- **把任意 deck.json 文件 拖到 Dock 里的启动器图标** = 打开那个 deck
- 也可以在编辑器右上的"📂 切换 deck" 按钮里换

---

### 路径 B · Shell 命令 · 一次配置长期省事

**适合**:命令行用得顺,想任何目录敲 `edit-deck` 就开干。

**一次配置**:

```bash
# 把这一行加到你的 ~/.zshrc (macOS 默认 shell 配置文件)
echo "alias edit-deck='python3 ~/Documents/GitHub/feishu-deck-h5/skills/feishu-deck-h5/deck-json/deck-editor.py'" >> ~/.zshrc
# 重新加载
source ~/.zshrc
```

**用**:

```bash
edit-deck                              # 自动找最近的 deck.json
edit-deck path/to/another/deck.json    # 指定路径
edit-deck --port 7421                  # 想用固定端口
edit-deck --no-browser                 # 不让自动开浏览器
```

#### 路径检查

`echo` 那行假设你 repo 装在 `~/Documents/GitHub/feishu-deck-h5/`。如果你 clone 到别处,改路径。看你 repo 在哪:

```bash
ls -d ~/Documents/GitHub/feishu-deck-h5
# 或
find ~ -type d -name 'feishu-deck-h5' 2>/dev/null | head -3
```

---

### 路径 C · 系统级 symlink

**适合**:你的 PATH 里有 `/usr/local/bin/` 或 `/opt/homebrew/bin/`,想 `edit-deck` 是个系统命令。

```bash
# macOS Intel / Linux
sudo ln -s ~/Documents/GitHub/feishu-deck-h5/skills/feishu-deck-h5/deck-json/deck-editor.py /usr/local/bin/edit-deck

# Apple Silicon (M1/M2/M3) — 用 /opt/homebrew/bin/ 通常不用 sudo
ln -s ~/Documents/GitHub/feishu-deck-h5/skills/feishu-deck-h5/deck-json/deck-editor.py /opt/homebrew/bin/edit-deck
```

之后任何目录直接 `edit-deck`。

---

## 编辑器布局

```
┌───────────────────────────────────────────────────────────────────────┐
│ deck-editor · <标题> · N slides         📂 切换 ↻Render ⟳Reload [就绪] │
├─────────────┬─────────────────────────────────┬───────────────────────┤
│  Slides     │  Preview (16:9 等比缩放)        │  Slide Inspector      │
│  01 cover   │  ┌───────────────────────────┐  │  Key · Layout         │
│  02 agenda  │  │                           │  │  Variant 下拉切换     │
│  03 ... ▶  │  │   双击文字直接改          │  │  Screen label         │
│             │  │                           │  │  Title (自动保存)     │
│  拖动 = 排序│  │   blur → 自动保存         │  │  按 layout 扩展字段   │
│             │  │                           │  │  Accent · Decor       │
│             │  └───────────────────────────┘  │  ─── Arrays ───       │
│             │                                 │  ▶ Cards (3 / 3)      │
│             │                                 │  ▶ Body blocks (2/4)  │
└─────────────┴─────────────────────────────────┴───────────────────────┘
```

---

## 常用编辑速查

| 想做 | 怎么做 |
|---|---|
| 改文字 | 双击 preview 里的文字 → 改 → 鼠标点别处 = 保存 |
| 改完按 Enter(单行标题等) | 直接保存 · 想换行用 `Shift+Enter` |
| 改完按 Enter(段落 body 等) | 换行 · 想直接保存用 `Cmd+Enter` |
| 取消改动 | 编辑中按 `Esc` → 恢复原值 |
| 重排 slide | 左侧列表拖动 → 看到的"缝隙横线"就是落点 |
| 加 / 删 slide | Inspector 底部 "复制此页" / "删除" |
| 换 layout 变体 (3up→2col 等) | Inspector "Variant" 下拉(content/stats/flow 有多 variant) |
| 改 accent 颜色 | Inspector "Accent" 下拉(blue/teal/violet/purple/orange) |
| 加 card / col / node 等数组项 | Inspector 底部数组区 "+ 添加" |
| 改某张 card 字段 | Inspector 底部展开 card #N → 改 → blur 自动保存 |
| 导入别的 deck 的 slide | 顶栏"导入幻灯片" → 选 deck.json → 勾选要导入的 |
| 一键导入整份 PDF (每页变 replica slide) | 顶栏 "📄 导入 PDF" → 选 PDF。**注:** 需 `brew install poppler` (macOS) 或 `apt install poppler-utils` (Linux) |
| 全屏 preview | 顶栏 "⛶ 全屏" · `Esc` 退出 |
| 跑完整 render | 顶栏 "↻ Render" 或 `Cmd+S` |
| 上一张 / 下一张 slide | `↑` / `↓` |
| 显示键盘速查 | 按 `?` |

---

## 输出文件

每次改后,编辑器自动备份 deck.json:

```
runs/<ts>/output/
├── deck.json                    ← 你正在编辑的
├── deck.json.bak-pre-set-...    ← 自动备份(改坏可以恢复)
├── _preview/                    ← 编辑器内部用,不要交付
│   └── index.html
└── (其他)
```

**最终交付要单独跑 render**(不是用 _preview/):

```bash
# 完整渲染 + 自包含 output/ (含 assets/ + texts.md)
python3 .../render-deck.py runs/<ts>/output/deck.json runs/<ts>/output/

# 单文件 inline 模式 (适合邮件附件 / Slack 发文件 / 离线打开)
python3 .../render-deck.py runs/<ts>/output/deck.json runs/<ts>/output/ --inline
```

---

## 故障排查

### 浏览器没自动打开

终端窗口会打印类似:
```
deck-editor · http://127.0.0.1:7421/?token=Wq8x...
```

复制这一整行 URL 到浏览器地址栏即可。**token 不能少**,否则编辑器看似能打开但所有改都 403。

### `no deck path given and none auto-detected`

要么:
- 显式给路径: `edit-deck /full/path/to/deck.json`
- 或 cd 到含 `runs/<ts>/output/deck.json` 的目录再跑

### 端口被占

```bash
edit-deck deck.json --port 7421     # 用别的端口
```

或 kill 之前没退出的 server:

```bash
pkill -f deck-editor.py
```

### 远程 / SSH 场景

```bash
edit-deck deck.json --no-browser
# 拿到 URL 后,本地终端 SSH 端口转发:
ssh -L 7421:127.0.0.1:7421 your-server
# 本地浏览器打开 http://127.0.0.1:7421/?token=...
```

### 编辑器双击启动器不响应

macOS 阻止下载脚本运行。**Finder 里 按 Ctrl+点击 `deck-editor.command` → 选"打开"**。第一次需要确认信任,之后双击直接跑。

### 改完文字看不到 preview 更新

编辑器为流畅故意不每次都重渲。点顶栏 **"↻ Render"** 或做结构操作(加 / 删 / 重排)就会触发。in-place 文字编辑已经显示了你输入,实际数据已保存。

### 导入 PDF 报 "pdftoppm not found"

PDF 切页要 poppler 工具,Mac 一句话装:

```bash
brew install poppler
```

Linux:

```bash
sudo apt install poppler-utils   # Debian / Ubuntu
sudo yum install poppler-utils   # RHEL / CentOS
```

### 编辑器想做的事 schema 装不下

罕见。两条路:

1. 用 `layout: "raw"` slide,把 HTML 手写在 `data.html`,可选 `_orig_layout` 让框架 CSS 仍生效
2. 跳出编辑器,直接 `$EDITOR runs/<ts>/output/deck.json`,改完点编辑器 `⟳ Reload`

---

## 用法层次(供心理建模)

- **80% 场景**:浏览器双击编辑 + Inspector 改字段 + 数组 add/del
- **15% 场景**:直接编辑 deck.json (大规模结构改 / 字段 schema 没暴露)
- **5% 场景**:`raw` HTML 单页(真装不下的 layout)

---

## 更多文档

| 想了解 | 看 |
|---|---|
| schema 字段定义 | [`deck-schema.json`](./deck-schema.json) |
| CLI 14 命令 reference | [`DECK-CLI-README.md`](./DECK-CLI-README.md) |
| 设计取舍 / 历史 / 怎样扩 schema | [`MIGRATION-REPORT.md`](./MIGRATION-REPORT.md) |
| Claude 用 SKILL 生成 deck | [`../SKILL.md`](../SKILL.md) § DECK GENERATION POLICY |
