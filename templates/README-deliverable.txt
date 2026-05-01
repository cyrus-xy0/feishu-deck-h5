================================================================
  飞书风格 HTML Deck  ·  使用说明
================================================================

这个 zip 包里有什么
─────────────────────
  index.html        ← 要看的 deck 本体（双击在浏览器打开）
  texts.md          ← 所有文字，集中在一个 .md 文件里方便编辑
  apply-texts.py    ← 把 texts.md 的改动写回 index.html 的小脚本
  apply.command     ← (macOS) 双击运行 apply-texts.py
  apply.bat         ← (Windows) 双击运行 apply-texts.py
  README.txt        ← 你正在看的这份说明


第一次使用：浏览 deck
─────────────────────
  1. 双击 index.html
  2. 在浏览器里：
       ←/→ 或空格    ── 翻页
       Esc           ── 退出全屏
       ⌘/Ctrl + F    ── 全屏


改文字（不动布局）
─────────────────────
  1. 用任何文本编辑器打开 texts.md（VS Code / Sublime / 自带的记事本都行）
  2. 找到要改的那一行，比如：
       title: 先进团队的\n工作方式
     改成：
       title: 我们的核心理念\n2026 路线图
     （`\n` 表示换行，会渲染成 HTML 里的 <br>）
  3. 保存 texts.md
  4. 双击：
       macOS    →  apply.command
       Windows  →  apply.bat
     窗口里会显示改了几条，比如:
       ~ slide-01.title
           - '先进团队的\n工作方式'
           + '我们的核心理念\n2026 路线图'
       wrote: index.html  (1 change(s))
  5. 浏览器里 Cmd/Ctrl + R 刷新 index.html → 看到新文字


首次运行 apply.command 被 macOS 拦截怎么办
─────────────────────
  macOS 第一次会弹 "无法打开 apply.command，因为它来自身份不明的开发者"。
  这是 Gatekeeper 的默认保护行为。

  放行办法：
    Finder 里 → 右键点 apply.command → 选 "打开"
    弹窗里再点一次 "打开"

  之后所有双击都不会再被拦。


Windows 第一次提示 Python 未安装
─────────────────────
  apply.bat 会告诉你去 https://python.org/downloads/ 装 Python 3。
  装的时候记得勾选 "Add Python to PATH"。装完再双击 apply.bat 即可。


改样式 / 颜色 / 排版
─────────────────────
  这一类不能在 texts.md 里改，因为 texts.md 只管文字。
  样式调整需要联系最初生成这份 deck 的人，让他改 CSS / overrides.css
  之后重新出包。


改结构 / 加新页 / 改 layout
─────────────────────
  同上，回到生成这份 deck 的会话里说："给 slide 5 之后加一页 stats，
  内容是…"，让 Claude / OpenClaw 重新生成即可。texts.md 里的 ID 在
  没结构变更的 slide 上会保持稳定，所以你之前改过的文字不会丢。


技术细节（FYI）
─────────────────────
  - apply-texts.py 是 stdlib-only Python 3，无需 pip install 任何东西。
  - 改动会通过 data-text-id="slide-NN.field" 属性精确定位到 DOM 节点，
    只替换 textContent，绝不动 layout / CSS / SVG / 装饰元素。
  - 每次运行会先存一份 index.html.bak，改坏了直接拿这份覆盖就回滚了。


================================================================
有问题就把这个 zip 发给最初生成 deck 的同事。
================================================================
