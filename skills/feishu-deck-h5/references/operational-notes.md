# operational-notes — feishu-deck-h5 reference
> 从 SKILL.md 拆出(F-30 瘦身)· 何时读:拷 shell / 嵌入 / 相对路径 edge

## Operational notes (gotchas)

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

