# operational-notes — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:拷 shell / 嵌入 / 相对路径 edge

## Operational notes (gotchas)

- **纯净投屏模式 — URL hash `#proj` / `#bare` / `#clean` / `#kiosk`.**
  Appending any of these keywords to the deck URL force-hides ALL present
  chrome (page bar + prev/next/fs controls + nav hint) and keeps it hidden —
  unlike the 2.5s idle-fade, hover / mousemove does NOT wake it back. For
  projecting, embedding the deck in an iframe (e.g. 妙搭 / Miaoda), and signage.
  Pure present-layer: works for any deck regardless of source (canvas / raw /
  schema). Toggled live on `hashchange`, so `#proj` ↔ `#3` switches cleanly.
  Lives in `feishu-deck.js` (`applyKioskChrome`) + `.deck-ui.is-kiosk` CSS.
- **演示者模式(Presenter / 放映窗)— 按 `P` 调出。** PowerPoint/Keynote 式
  演示者视图:当前页 + 下一页**实时预览**(克隆 `.slide` 缩放,无截图)、**口播稿**、
  **计时器**、翻页。口播稿来自 deck.json 每页的 `notes` 字段——渲染时输出成隐藏的
  `<script type="application/json" id="fs-deck-notes">` JSON 岛(`notes` 本身不渲进
  页面,只演示者视图读)。视图里点 **📺 放映窗** → `window.open(...#proj)` 开一个
  纯净(kiosk)观众窗,经 **BroadcastChannel**(同源,无后端;localStorage 兜底)
  **自动跟随**主窗翻页;观众窗是 follower(`window.name='fs-projector'`),自身翻页
  不回弹主窗。`Esc`/再按 `P` 退出。实现在 `feishu-deck.js` `setupPresenter()`。
  注:跨窗跟随需同源——`file://` 下浏览器可能不桥接 BroadcastChannel,**发布到
  http(s) 后稳定生效**。
- **`templates/_shell.html` uses `../assets/feishu-deck.css`.** It assumes the
  shell stays one directory deep relative to `assets/`. If you `cp` it to a
  new working directory, fix the relative paths to point at the actual
  `assets/` location, or run `bash build.sh` from the skill root which
  handles the rewrite automatically.
- **`data-decor="flower-bg"` and `"photo-bg"` use `!important` to override
  layout backgrounds.** They REPLACE the layout's default background image —
  intentional, so you can carry the cover atmosphere onto a content page.
  The auto-darkening protection gradient is added on non-cover/non-end
  layouts only (cover and end have their own contrast strategies).
- **CSS rule `.deck[data-mode="scroll"] ~ .deck-ui` relies on `.deck-ui`
  being a later sibling of `.deck`.** `feishu-deck.js` always appends the
  UI to `document.body` so this holds, but if you wrap `.deck` in a parent
  container or insert nodes between `.deck` and `.deck-ui`, the sibling
  selector breaks. The JS belt-and-suspenders `display: none` keeps it
  working in practice — but if you embed the deck inside a custom shell,
  prefer toggling `body.is-scroll` instead.

## 单页小改 = 秒级动作,别搞重(mandatory)

用户说「改这一页的字 / 这页字号不对 / 把 X 改成 Y」时,这是**单页编辑**,
不是全 deck 体检。13 分钟改几个字是 bug,不是正常。铁律:

- **只跑 3 步:① Edit deck.json 的那一页 → ② render → ③ 最多一张该页截图确认。**
  收工。**不要**对整 deck 跑 `check-only.sh --visual` / Playwright 全审计
  (那是「审整份 deck」才用的,19 页全量审计十几秒起,单页改字完全不需要)。
- **不要重复劳动**:同一个量字号 / 截图脚本只跑一次。需要复测就改完再跑一次,
  不要边改边反复跑。
- **回答「这页字是不是小了」**:量**那一页**的字号(一次 Playwright eval 或
  直接读该 slide 的 scoped CSS + 框架默认档)即可,2~3 秒,**不要**为一个
  字号问题启动全 deck 视觉审计。
- **已知步骤的单页操作不要甩给 subagent**:换 demo 文件、改 `src`、改 `title`、
  套 `custom_css`、单页字号这类步骤已知且约 10 步以内的工作,主对话线性完成。
- **依赖链不要塞进并行 block**:`copy → render → inspect → edit → render` 这类
  顺序工作必须一步一确认。并行只用于互不依赖的读/查。
- **单页编辑的校验报告只看这一页**:渲染器可能全 deck render/validate,但判断
  本次改动是否干净只看锁定 slide key。其他页存量 finding 不主动报告、不顺手扩
  scope。
- **多 session 同改一份 deck 时写前重读**:`deck.json` 是单文件 SSOT,last-writer
  wins。写入前重读并确认关键字段仍是预期;遇到 mtime/git 状态变化或工具报
  concurrent modification,先 rebase 自己的改动到最新版。
- **`GEO-EDIT-01` 几何位移小改 = 先算边界,禁止负定位试错(2026-06-04 立)**:
  「把上面那块上移一点 / 下面那块下移 / 卡片靠近些 / 雷达·罗盘·中心图形挪一挪 /
  上下左右框对齐」这类**单页几何微调**,不许靠 `top:-N` / 反复改值边改边截图试错——
  那是把秒级动作拖成十几分钟的根因。铁律:**先花 30 秒做纸面几何**(读出该元素及其
  容器的当前 `top/left/width/height` 与目标位置,算出唯一应改的偏移量),**再一次性
  改 CSS,然后才 render+量一次确认**。负定位(负 margin / 负 top)几乎总是试错的信号,
  禁用;改不动先回去算边界,不要再猜一个值。**只改该元素自身的定位,绝不为「顺手对齐」
  动整个 stage / 容器**(那会连标题一起挪走,见同类约定)。

After preflight and before generating new HTML, create a per-run workspace under
repo-root `runs/`, not under `skills/<skill-name>/`:

```text
<repo-root>/runs/YYYYMMDD-HHMMSS-<slug>/
  input/
  output/
```

Use `assets/new-run.sh <slug>`. The slug is derived from the topic/customer,
ASCII/kebab-case, about 25 chars or shorter. Never use Chinese characters in the
slug and do not use a bare timestamp unless no topic exists. Announce the absolute
run path, tell the user where `input/` and `output/` are, and write all generated
deck artifacts under that run's `output/`.

Do not create a new run when the user explicitly asks to edit an existing
`runs/.../output/` deck.

## ❌ 绝不用裸 `find` 找渲染器 / 工具(空指针根因 · mandatory)

skill 常以 **symlink** 挂在 `~/.claude/skills/feishu-deck-h5 → <repo>/skills/feishu-deck-h5`。
`find ~/.claude/skills/... -name render-deck.py` **不加 `-L` 会返回空**(find 默认
不进 symlink 目录)→ `$RD` 为空 → `python3 ""` **静默不渲染**,然后你会拿到
**上一次的旧产物**当成「改完了」,完全错判。已踩。铁律:

- **渲染器路径写死,不要 `find`**。技能调用时 header 会告知
  `Base directory for this skill: <DIR>`,直接用:
  ```bash
  python3 "<skill-base>/deck-json/render-deck.py" deck.json .
  ```
  (python3 走 symlink 没问题,坏的只有 `find`。)若必须搜,用 `find -L`。
- **render 后必须验证「真的渲染了」再下结论**:看渲染器 stdout 有没有
  `OK  →  …index.html` + `errors: 0`;或 render 前后比 `index.html` 的 mtime /
  目标字符串是否真变了。**绝不靠「我跑了命令」或一张可能是旧的截图就宣布修好**
  ——命令可能因空路径 / 报错而根本没跑。截图前先确认 HTML 真的重渲了。

## ❌ 别发探针 / 轮询去「催」工具输出(mandatory)

工具结果偶尔批量延迟到达,这是正常的 harness 行为,**不是卡住**。**绝不**连发
`echo PROBE` / `echo FLUSH` / sleep 轮询去「确认通道还活着」——纯浪费往返、反而
更慢、把对话刷满噪音。耐心等结果回来;真要等外部状态用 Monitor/until-loop,不要
手撸 echo 刷屏。

---

