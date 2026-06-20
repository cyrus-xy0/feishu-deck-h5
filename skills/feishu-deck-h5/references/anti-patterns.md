# anti-patterns — feishu-deck-h5 reference (single-source index)

> **What this is**: the ONE place that names every recurring anti-pattern in this
> skill, what machine channel (if any) enforces it, the borrowed-time excuse that
> reaches for it, and the sentence that closes that excuse off. **It is an INDEX,
> not a rewrite**: the full reasoning, the failure post-mortems, and the recipes
> stay in each canonical file (last column). Do not copy the prose here — fix or
> read the canonical home. The covered-test `deck-json/tests/test_anti_patterns_index.py`
> asserts every `R-*` named in the «执行通道» column really exists in the validate
> engine, so this table cannot drift away from the rules it claims back it.
>
> **执行通道 values**: a concrete `R-*` rule name (machine gate, fires in
> `validate.py` / `audits.js`) · a `deck-cli` exit code / write-path guard · the
> W4 `_lint_fragment` pre-write lint · or **人工** (no rule covers it — judgment +
> a Hard Gate / squint pass is the only floor).

| 反模式简名 | 一句祈使禁令 | 执行通道 | 常见绕过借口 → 封死语 | 详述位置(文件) |
|---|---|---|---|---|
| 手搓/旁路 index.html | 生成产物必须过 `render-deck.py`,绝不手写或 patch 最终 `index.html`。 | `R-PROVENANCE` | 「就改一个字 / 直接出更快」→ 任何没经 render 的 `index.html` 都缺 provenance 戳,gate 当场拦;要改字走 `fast-text.py`(双写)或 `deck-cli` set。 | SKILL.md → Controller Hard Gates 1;`references/deck-generation-policy.md` |
| ad-hoc heredoc 写 deck.json | slide 级写入一律走 `deck-cli set-page` / `set --from-file`,不要 python/heredoc 直接 dump deck.json。 | deck-cli 写路径(乐观锁 / auto-backup / schema 回滚 / W4 lint) | 「小改 / 赶时间不值得用 CLI」→ 乐观锁 + rollback 正为并发小改而生;heredoc 绕过它就是用别人的丢稿换你的几秒。 | `subskills/editor/SKILL.md` → canonical loop「Anti-pattern」;SKILL.md → Shared Contracts |
| opt-out 滥用(mass-mute floor) | opt-out 是 1-3 处 documented intent,不是批量哑掉 floor 警告的开关。 | `R-VIS-OPT-OUT-ABUSE` | 「warn 太多,整卡挂上 `data-allow-body-floor` 清净」→ 单 slide 同种 opt-out ≥5 次几乎一定是 silence 反模式;字太小就 bump,不是静默承认。 | `references/design-first.md` → opt-out 合法 vs 滥用 |
| 跨页 series/family 漂移 | 加入既有系列(eyebrow/编号卡/字阶/页 bg)时逐字照抄邻页,别凭记忆重画。 | `R-FAMILY-DRIFT` | 「看着差不多就行 / raw 页 validator 反正不抓」→ raw 页审美一致性 validator 抓不全,几何/字阶漂移已被 `R-FAMILY-DRIFT` 软报,其余靠 `conform-to-deck.py` + 人工逐字抄。 | `references/editing-discipline.md` E7;`subskills/editor/SKILL.md` → RESKIN/conform |
| holed-out / 空壳页 | 删/改/继承一页后做 squint pass 补回视觉平衡,不许留空洞就交。 | 人工(squint pass) | 「删成功了 · PASS · ship」→ R-rule 全绿 ≠ done;空洞是审美判断没规则管,看一眼那页再说完成。 | `references/editing-discipline.md` E5 / E6 |
| Gate 跳过(用「直接出」当借口) | 「直接出 / 别问了」只跳确认停顿,绝不跳 validate。 | 人工纪律 + Controller Hard Gate 4 | 「用户说直接出 = 不用校验」→ 速度不豁免 gate;锁定的 HTML 必须过它对应的 gate 再交,never patch around it。 | SKILL.md → Controller Hard Gates 4;`references/design-first.md` → When to skip |
| regex/sed 改 slide DOM | 永不用 regex/sed/纯文本替换增删/重排/改 slide-frame 结构。 | `R-DOM` | 「快速 splice 一下就行」→ regex 吃 DOM 会把 frame 嵌套进去、吞掉 `</div>`;结构改动读文件手工定位整块写回,R-DOM 是安全网。 | `references/editing-discipline.md` E2;`subskills/editor/SKILL.md` → Hard Rules |
| whole-deck 审计单页编辑 | 单页小改只跑 scoped `--iter`/`--scope`,别对整 deck 跑全量校验/截图。 | 人工纪律 + Controller Hard Gate 4 | 「顺手全 deck 体检更稳」→ 全量 gate 是 delivery 关,改一页跑它是「改一页却渲染/校验/截图很多页」头号根因;scoped gate 已让未改页保留上次判定。 | SKILL.md → Scope Discipline;`references/operational-notes.md` → 单页小改 |
| screen_label 当页号 | 页面身份是 `page N = frame_index N`,绝不拿 `screen_label` 数字前缀当真页号。 | 人工(`deck-map.py` / `locate-slide.py` 定位) | 「label 上写着 03 就是第 3 页」→ label 在 lift/insert/reorder 后会漂;用 `deck-map.py` 读真页序,需要对齐用 `render --renumber`。 | SKILL.md → Shared Contracts;`subskills/editor/SKILL.md` → Hard Rules |
| 把复杂原型 inline 进 raw slide | 自带壳/缩放/CSS 的独立原型用 iframe(或默认静态图),别拆进 raw `data.html` 逐条 scope。 | 人工(Mode A/B/静态图 决策) | 「verbatim 搬进来 inline 最干净」→ 一旦在 scope `:root` / 改 scale JS / 给每条规则挂 `allow:typescale`,就是 doom loop;停手切 Mode A 或静态图。 | `references/prototype-embed.md` → Anti-pattern doom loop |
| 把纯并列卡片页回退 content schema | F-305 后正文页(含纯 N 卡并列)一律 `layout:"raw"`,别回退已冻结的 body schema。 | `R-LAYOUT-DEPRECATED`(advisory) | 「标准卡片用 content schema 更省更稳」→ 该理由已让位给 raw 自排更丰富;新页用冻结 body 版式会被 `R-LAYOUT-DEPRECATED` 提醒,用框架卡片 token 自排。 | `references/deck-generation-policy.md` → Layout Choice;`references/design-first.md` → Decision rule |
| 为撑满屏幕把页脚顶到底 | 内容不足别拉伸卡片/页脚顶边;filling the screen is not a goal,居中成组才是。 | `R-VIS-SLACK-FLEX` | 「flex:1 撑满更饱满」→ 有兄弟块时 `flex:1` 吞掉所有 slack 造成空带;`R-VIS-SLACK-FLEX` 报过来时答案几乎总是「group + centre」或换会自然填 16:9 的形状,不是 stretch。 | `references/layout-recipes.md` → grid SHOULD/NOT grow |
| 局部 nudge 改整 container 对齐 | 移近某元素只改它自身 margin,绝不翻整 `.stage` 的 justify/align(会连标题一起挪)。 | 人工(raw 页 `R-VIS-TITLE-POSITION` 跳隐藏 header) | 「改 stage center 一步到位」→ 标题不动是死规矩,raw 页 validator 看不见被挪的标题;改完用 Playwright 量 `titleTop` 确认没变。 | `references/editing-discipline.md` E6;`references/operational-notes.md` GEO-EDIT-01 |
| 头 `<style>`/`<script>`/JS 库塞动效 | bespoke 动效只进 `slide.custom_css`(纯 CSS);deck.json 无 JS 槽,head script 会被重渲抹掉。 | 人工(round-trip:custom_css travels,script 不 travel) | 「加个 GSAP/anime.js 更高级」→ 框架级 JS 只有 `magic_move` / `motion_engine:"gsap"` 两个 deck 级 opt-in;per-slide `<script>` 仍禁,bespoke GSAP 走 iframe 逃生口。 | SKILL.md → Shared Contracts(motion);`references/motion-system.md` |
| 裸 `find` 找渲染器/工具 | 工具路径写死(用 skill-base header),绝不裸 `find` 找 `render-deck.py`。 | 人工(render 后验证真渲染了) | 「find 一下省事」→ symlink 下 `find` 不加 `-L` 返空 → `python3 ""` 静默不渲 → 你拿旧产物当「改完了」;render 后看 stdout `OK`+`errors:0` 或比 mtime。 | `references/operational-notes.md` → 绝不用裸 find |

> Pointer-only by design: when a row's machine channel is a `R-*` rule, that rule —
> not this table — is the source of truth for what it catches; this index only
> records *that* it is the channel. To change an enforcement, change the rule (and
> its canonical file), then this row follows. Adding a row that names a new `R-*`
> requires that rule already exist in the engine, or the coverage test fails.
