# 工单编号登记处 (TICKETS)

> **下一可用号 = F-332**
>
> ⚠️ **F-322 由一个并发 session 占用**(card-overflow 滚动 opt-out,其 WIP 未提交;
> 本分支 off HEAD 看不到)。本分支(`fix/code-review-0614`)从 **F-323** 起,跳过 F-322
> 不复用,合并时与对方的 F-322 行各占一行即可。F-323..F-331 = 2026-06-14 全量 code review
> 修复批次,明细见 `docs/CODE-REVIEW-2026-06-14.md`(每条 finding id 可追溯)。

这是 `feishu-deck-h5` skill **唯一**的工单编号登记处。F-255..F-307 已分配
(F-295~F-299 为跳号空洞,作废勿用,见「登记流水」)。
F-292 = F-256 视觉闸门调优(本轮用掉)。F-001..F-254 散落在历史审计文档里
(`docs/archive/` 下各 `AUDIT-*.md` / `*-GAP-*.md`),早期没有集中登记,因此存在
**撞号**(同一个号在不同文档里指两件不同的事)。下表把已知撞号一次性钉死。

## 一句话规矩

- **新工单一律来这里领号**:取「下一可用号」,在本文件登记一行(号 + 一句话 + 归属文件),
  然后把「下一可用号」+1。不要再凭印象在审计文档里直接起号。
- **历史审计文档**顶部各加一行指针:`> 工单号以本文档为准已不可靠,新号见 docs/TICKETS.md`,
  把读者引回这里。已撞号的旧文档不改正文(改不动也没必要),只在本表标注两义。

## 撞号对照表(历史遗留,勿复用这些号)

同一编号在不同历史文档里有两个(及以上)互不相干的含义。引用旧工单号时**必须连文件名一起说**
(例如「F-40(AUDIT-LIFT-IMPORT)」而非裸「F-40」),否则会指错。

| 号段 | 含义 A | 含义 B | 其它含义 |
| --- | --- | --- | --- |
| **F-36 ~ F-39** | 产品级路线图工单(`docs/archive/REPRODUCIBILITY-GAP-2026-05-30.md` 引 `AUDIT-2026-05-29.md` **detail 段**):F-36=HTML→PPTX 桥 / F-37=硬挂载门 / F-38=WYSIWYG 太浅 / F-39=协作评审。**注**:AUDIT-2026-05-29 自己的摘要表(93–94 行)与 detail 段编号就不一致,**一律以 detail 段为准**。 | — | — |
| **F-40 ~ F-46** | `lift-slides.py` / 导入路径工单(`docs/archive/AUDIT-LIFT-IMPORT-2026-06-01.md`):F-40=`--shake` 漏 `[data-page=N]` 组件 CSS / F-41=少一个 `</div>` / F-42=reconcile 成套工具 / F-43=lift 保设计换文字路由 / F-44=安全 text-swap / F-45=lift 资产带不全 / F-46=workflow args 字符串到达。 | 与上一行 F-36~F-39 不重叠(两个号段相邻但各自连续);**真正撞号的是下面 F-80~F-85**。 | — |
| **F-80 ~ F-85** | `lift-slides.py --to-html` / `--preview` 一族(`docs/archive/AUDIT-LIFT-IMPORT-2026-06-01.md`):F-80=`--to-html` lift 进无-deck.json 老 deck / F-81=`--preview` 一条命令出判断 / F-82=raw 页 data.html 契约固化 / F-83=探测命令默认 `--json` 治截断 / F-84=`--to-html` 内建闭环 / F-85=`import-html-slide.py` Mode B 被取代(并入 F-80)。 | edit-mode 安全/正确性 bug(`docs/archive/AUDIT-2026-06-01-skill-review.md`):F-80=getTextLeaves 误使容器可编辑 / F-81=富 HTML 粘贴存储型 XSS / F-82=undoStack 与 save 序列化不一致 / F-83=FS 写失败静默降级 / F-84=process step 双 ::after 箭头 / F-85=`centerSlideInCanvas` 跳过 `position:absolute`(R-VIS-BAND-COLLIDE 根因)。 | **F-85 第三义**:R-DOC-INTEGRITY 整文档完整性闸门(`deck-json/tests/test_doc_integrity.py` 模块 docstring 把该规则标作 F-85,2026-06-03)。 |

> 归属规律:`AUDIT-LIFT-IMPORT-2026-06-01.md` 自己声明「续号 F-50 起 / F-40~F-49 撞号请并入」,
> 是撞号的主源头;`AUDIT-2026-06-01-skill-review.md` 的 F-80~F-85 与它**同日各起一套**导致正面冲突。
> 这正是设此登记处的原因。

## 登记流水(F-293 起)

> 2026-06-12 对账:F-293~F-304 是各 session 在登记处之外自行取的号
> (PLAN-ITERATION-LOOP-2026-06-11 跳号到 F-300+,F-303/304 又被新工具领走),
> 本次回填钉死;F-295~F-299 **从未被分配,作废勿用**(防空号与流水撞车)。
> 此后回到「先领号再开工」的规矩。

| 号 | 一句话 | 归属 |
| --- | --- | --- |
| F-293 | `--scope-frames`:把 render scope 喂进统一审计引擎(单页 scope 渲染规则同源) | `deck-json/render-deck.py` / `tests/test_scoped_audit.py` |
| F-294 | R-VIS-SUBTITLE-CANON:标题副标 canonical 统一(`.header` 内只认 `.page-sub`) | `assets/audits.js` / `tests/test_subtitle_canon.py` |
| F-295~299 | —(跳号空洞,作废勿用) | — |
| F-300 | family-drift 探测 + conformer(同族页漂移检测/归位) | `deck-json/conform-to-deck.py` / `docs/PLAN-ITERATION-LOOP-2026-06-11.md` |
| F-301 | 标题带锚点=副标底 + `findSlideHeader` 三通道(canvas-center/crowd 口径统一) | `assets/audits.js` / `docs/PLAN-ITERATION-LOOP-2026-06-11.md` |
| F-302 | baseline-aware 视觉闸:new-vs-pre-existing findings diff(--scope 豁免存量红) | `deck-json/render-deck.py` / `tests/test_baseline_gate.py` |
| F-303 | fast-text.py:亚秒级纯文案双写编辑(no render, no validation) | `deck-json/fast-text.py` |
| F-304 | shoot-page.py:确定性单页截图(外链 iframe route-ABORT) | `assets/shoot-page.py` |
| **F-305** | **「raw unless ceremonial」:冻结全部正文 schema 版式只留仪式五件套+机制页;新增 validator `R-LAYOUT-DEPRECATED`(advisory)+ 退役反向规则 `R-RAW-LOOKS-SCHEMA`;文档/schema 口径收窄;deck.json 保留裁决在案。**DONE 2026-06-13**(零回归,新测 10/10)** | **`docs/F-305-RAW-UNLESS-CEREMONIAL-2026-06-12.md`** |
| F-306 | 补全 `a06f171`(R-VIS-SVG-TEXT-FLOOR 规则)漏登记的 FAMILIES / business-rules.yaml / validator-rules.md / examples 视觉基线——本是 main 上既存红闸(覆盖闸 + F-03 + 视觉基线三处),随 F-305 验证一并发现并修。DONE 2026-06-13 | `assets/check-only.py` / `assets/business-rules.yaml` / `references/validator-rules.md` / `deck-json/tests/baselines/example_decks_visual.txt` |
| F-307 | ① raw/iframe-embed 的 `.slide` 默认补画 content-bg(frame 白名单本有、slide 列表却漏 raw/iframe 只列了 canvas)→ 透明 raw 页露出 frame 非-16:9 `cover` 裁剪、图暗顶边溢出成「标题上方黑条」(复发老问题);custom_css 仍可覆盖。② 关闭 raw×框架标题的标题位盲区:`R-VIS-RAW-TITLE-POS` 见 raw 页内框架 `.header>.title-zh` 不再 `return []` 让位(让位对象 `R-VIS-TITLE-POSITION` 是 schema-only、raw 不跑),改自量 header top 双向查(偏高=与 logo 错位 / 偏低=空带),tol 8,warn。lift 外来页带进 top≠61 的自定义 header 现可被抓。DONE 2026-06-13(零回归,全 deck PASS) | `assets/feishu-deck.css` / `assets/audits.js` |
| F-308 | import-html-slide 导入时自动**拷贝+改写**一页的本地资产(`img`/`iframe`/`video`/`url()`,iframe body 再下探一层)进 `assets/imported/<src>/` 并 rewrite ref——治外来页落地即 404;复用 `_ASSET_REF_PATTERNS`(同 F-76 扫描器)。DONE 2026-06-13(端到端验证:3 资产+iframe 拷入、ref 全改、render PASS) | `deck-json/import-html-slide.py` |
| F-309 | import-html-slide `--key` / `--index`:从多页 montage 里只导**一张** slide-frame(不再全量导入,治「拎一页」要手抽临时文件)。DONE 2026-06-13 | `deck-json/import-html-slide.py` |
| F-310 | import-html-slide 导入页默认 `lifted:true`(外来 verbatim → validator 把该 deck 的离阶字号降 warn 不顶闸),`--no-lifted` 退出;另加 `--no-copy-assets`。DONE 2026-06-13 | `deck-json/import-html-slide.py` |
| F-311 | run-audits geometry 测量前加 bounded `img.decode()` settle:未解码 `<img height:100%>` 按自然高瞬时撑高,在 clipped media-box 里误报 `R-VIS-CARD-OVERFLOW`;`img.complete` 短路已加载页→零基线漂移(`test_visual_audit_parity`/`test_vis_card_overflow_leaf` 全过)。DONE 2026-06-13 | `assets/run-audits.py` |
| F-312 | `deck-map.py`(新工具):name-free 页面地图(`idx·key·layout·screen-label·title`,读 `<div class="slide-frame">`/`slides[]`,`--json`/`--key`/`--index`)——解决「montage `grep data-slide-key` 误数页」(本 session lift 三次数错的根因)。DONE 2026-06-13 | `deck-json/deck-map.py` |
| F-313 | 新 validator `R-VIS-ABS-OVERLAP`(warn):补「两个各自 `position:absolute` 的内容块在画面上相互重叠」盲区——R-OVERLAP 显式跳过 absolute、R-VIS-BAND-COLLIDE 只认 .stage/.grid host,二者都漏 raw 自定义页里两个 absolute 块直接叠(本 session 实证:voice-hub 中枢卡片被内容撑高压进底部支柱、8 处文字叠文字,render 全绿)。name-free 几何:收最外层 absolute 文本块→两两求交→确认「有底色/边框的块压住另一方文字」才报(避透明容器误报);`data-allow-overlap` 豁免。**调试关键坑**:规则曾整页静默——present 模式**非当前帧整体继承 `pointer-events:none`**,审计逐页量时除当前帧外全被 `pointerEvents==='none'` 过滤误杀;去掉该过滤(装饰层靠 svg+无文字排除)即修。DONE 2026-06-13(真引擎非当前态测:窄 hub 报 2 条 / 修复版 0 / 全 11 页 0 误报;三方覆盖 85 条对齐) | `assets/audits.js` / `assets/business-rules.yaml` / `assets/check-only.py` |
| F-314 | iframe-embed 新增 `data.fit_width` 便捷旋钮:外来固定设计宽原型(`max-width:1320` 类)被 iframe 硬拉到 ~1800px 嵌入体 → 字小+两侧留白;填 `fit_width=设计宽`,渲染器自动算 `zoom=1800/fit_width`,按设计宽渲染再放大铺满(走 iframe 内联 style,天然盖过框架规则)。**配套**:schema 加 `fit_width` 字段(原 `zoom` 描述指向它)、prototype-embed.md Mode B 加「别手搓 custom_css `!important`」红框警示(本 session 真实踩坑:hand-roll 的 `.slide[...] iframe` 被框架规则更高优先级覆盖 → 缩放到错基准 2452px 被裁/偏移)。DONE 2026-06-13(`fit_width:1320`→iframe 视觉 1801×881≈shell,clean fill) | `deck-json/render-deck.py` / `deck-json/deck-schema.json` / `references/prototype-embed.md` |
| **F-315** | **浏览器 edit-mode(`e`+⌘S)编辑被静默覆盖的数据丢失 bug**:同事在浏览器里改了 deck 并保存(只写 index.html,**从不进 deck.json**),之后 AI 改其他页 → render 从未变的 deck.json 全量重建 index.html → 同事改动被还原/抹掉,且 render 成功后自删 `index.html.bak-pre-render`(无痕)。根因=三处缺护栏 + 早有的方向守卫 `_wrong_direction` 没接进 render/deck-cli。**修法(布局无关的自完整性签名,不用 canvas 有损反映射)**:新增共享模块 `_index_sig.py`——render 在产物里埋 `<meta fs-render-sig>`(规范化后内容哈希,归一 deck_id/资产路径);任何外部编辑(edit-mode ⌘S 重序列化 / 手改)使其失配。**策略 = Option A「无损自动 / 有损拦截」**(用户拍板):`resolve_clobber` 先跑廉价 sig+mtime 守卫,有未 sync 编辑时再用 `sync --check-drift` 分类——**raw/custom_css/order/hidden/notes 全无损 → 自动反向 sync 折回 deck.json 再继续(命令/render 叠在其上,两边都活)**;**canvas(反映射不幂等)/ baked DOM / chrome 或 schema 页(sync 折不动)→ 拒绝**(deck-cli exit 6 / render exit 8 / import-html-slide SystemExit),`--force` 丢弃。**三道闸**(均在改 deck.json/index.html 前):deck-cli 写命令唯一收口、render 加载 deck 前(autosync 要在读 deck.json 前发生)、import-html-slide 插页前。render 成功后 `os.utime` 对齐 index.html↔deck.json mtime(常规 set-page→render 循环不误触);`sync --check-drift` 退出码 `0/10/11`。edit-mode 保存 toast 提示。DONE 2026-06-13(新测 **19/19**:含 raw 自动 sync、canvas/schema 拦截、canonical loop 不误触;真实 50 页 canvas deck 实测 check-drift=11→refuse;golden/atomic/sync_direction/render_gate/edit_roundtrip 38/38 零回归)。**已知边界(pre-existing,非本工单)**:canvas/schema 页反向 sync 有损,故对它们**拦截而非自动**——守卫阻止静默丢失,canvas/schema 编辑建议直接在 deck.json 重做。立项 `docs/F-315-EDIT-MODE-CLOBBER-2026-06-13.md` | `deck-json/_index_sig.py` / `deck-json/render-deck.py` / `deck-json/deck-cli.py` / `deck-json/sync-index-to-deck.py` / `assets/edit-mode/deck-edit-mode.js` |
| F-316 | deck 级开关 `deck.hide_progress: true`:持久隐藏 present 模式顶部那条 3px 阅读进度条(`.deck-progress` 品牌渐变 keyline),**无需** per-URL 的 `#clean`/`#kiosk` hash(那个会连底部控件+翻页提示一起藏);只藏进度条、控件保留。渲染器在 `.deck` 上吐 `data-hide-progress`,CSS `.deck[data-hide-progress] ~ .deck-ui .deck-progress{display:none!important}` 盖过 feishu-deck.js 的内联 display。**起因**:本 session 鸣鸣很忙 deck 那条顶部渐变线被用户当成「黑边/上面有条边」反复反馈——查实是进度条(z:60、pointer-events:none、每页都有、宽度随翻页变,所以逐页颜色不同),非页面 bug。正式客户/汇报 deck 常不想要它。DONE 2026-06-13(本 deck 开 hide_progress→普通视图顶部从亮蓝 (63,122,255)→深色 (11,17,45),控件仍在,render PASS) | `deck-json/render-deck.py` / `assets/feishu-deck.css` / `deck-json/deck-schema.json` |
| F-317 | `R-VIS-CARD-OVERFLOW` 双边可见溢出:(a') 可见溢出支路原只量子元素**底边**、且按 `scrollHeight-clientHeight>8` 预闸——`justify-content:center\|flex-end` 卡片内容超框时**顶边**也溢出(标题行顶出面板上沿),而 `scrollHeight` 看不见框上方内容(dh≈0)整卡被跳过;present `scale<1` 时底溢又因未 ÷`_scale`(全引擎唯一漏除处)被低估 → 26px 实溢蒙混过关(#meeting-qc,validator 全绿)。改为量**两边** × **设计 px(÷_scale)** 累加 overshoot,消息标边沿(上沿/下沿/上下两沿)。回归锁 `test_vis_card_overflow_both_edges.py`。**既有规则改检测、不动 rule-id/coverage**(check-rule-coverage 闸不涉及)。DONE 2026-06-13(broken 端到端被拦 rc=4 / good PASS / 18 单测+4 新回归全过 / baseline churn=0) | `assets/audits.js` / `references/validator-rules.md` / `subskills/renderer/SKILL.md` / `deck-json/tests/test_vis_card_overflow_both_edges.py` |
| F-318 | 根治反复出现的「顶部有条边 / 颜色和背景不一样」(非 16:9 全屏 letterbox 接缝):present 模式下 **frame 与 slide 都画 content-bg 但裁剪不同**(frame=视口比例 cover、slide=固定 16:9 cover)→ 出现 letterbox 时两裁剪在边界对不上 = 一条颜色突变横线,屏越大越明显。F-307 只把 frame 从渐变改成 content-bg、没消双层裁剪差。**正解=塌成单层**:新增 `.deck[data-mode="present"] .slide-frame > .slide{ background:transparent !important }` —— present 只由 frame 画一张 cover 铺满(letterbox 也是同一层延续),slide 透明穿透 → 全版式/全视口永不接缝;scroll 模式不动(slide 仍有卡片底)。**边界**:slide 上的 `::before` 满屏氛围叠加(只盖 slide 不盖 letterbox)会留小残缝——lift 页(如 renwu-native)按页 `::before{display:none}` 收掉即可;bespoke 全幅底应画在 `.slide-frame` 上。DONE 2026-06-13(页 1/7/11 跨边界 row-jump 2~10=无缝、页 13 收 ::before 后 0;test_examples_visual_baseline + parity + golden 5 项全过、零基线漂移) | `assets/feishu-deck.css` |
| F-319 | **(A·迭代环加速)** `render-deck.py --scope N,M --visual` 此前只 scope **渲染**,**视觉审计 findings 与 PASS/FAIL 闸仍全 deck** → 别页(他 session 的 WIP / validator 漂移)一个视觉错就 FAIL 并**回滚 in-scope 编辑的 index.html**(本次给 deck 加 19/20 两页,被 p3/4/7/8/13/16 反复挡,只能 grep 捞自己页 + 补渲复原,占了收尾来回 ~80% 时间)。正解=scoped runs/ 的 `--visual` 主闸改走 `--no-visual`(静态)+ 把 `--scope-frames`+in-scope 过滤+F-302 baseline 的视觉块对 `--visual+scope` 也生效(`_vis_block`/`_geom_block` 只判 in-scope NEW 视觉/几何错);deck 级/域外错降级 advisory。DONE 2026-06-13(并发 session 落地:`render-deck.py:3061` `if not args.visual or (scope_pages and _is_runs)` + `:3177` 视觉块 guard 扩成 `not args.visual or scope_pages`;实测 `--scope 19,20 --visual`→PASS rc=0 / `GATE-COVERAGE visual=ran(scope=19,20) geometry=ran(scope=19,20)` / 不回滚;早先两页带 `var(--h)`/`gs-dist` 溢出时正确 BLOCK→修净后 PASS,双向都对)。**⚠ 号冲突待清理**:此 scope-gate 在 `render-deck.py` 注释里长期挂 `F-307`,但本登记处 F-307 是「raw/iframe content-bg 黑条修复」(另一特性)——同号双用,建议把代码注释正名为 F-319。 | `deck-json/render-deck.py` |
| F-320 | **(B·并发编辑解锁)** `deck-cli set/insert/set-page` 的预写 lint 是**全 deck**:别的 session 一个坏页(本次 p16 `R-FAMILY-DRIFT`)就**回滚我对别页的编辑**——`set hide_progress` 被打回(`restored from backup`),被迫 `--skip-lint` + 手写原子追加(丢了乐观锁/校验安全网)。修法=预写 lint 只判被改 slide(+deck 级不变量),域外页既存错降级 advisory、不挡本次写;镜像 F-319/F-307 的 scope-降级口径。DONE 2026-06-13:① `validate-deck.py` 加 `--json`(发 `{ok,errors,warnings,soft_warnings}`,每项带 `{path,msg,slide,key}` —— slide 从实例路径 `slides[N]` 解析、key 为该页 key,给 scope 归属用;`--strict` 下 warnings 已 promote 进 errors 即 blocking 集);② `deck-cli.py` 加 `_edit_scope_keys(args,updated)`(单页/deck 级命令 opt-in 返回 scope:set-page/accent/decor/notes/variant/insert→`{key}`、`set` 路径 `slides.N.x`→`{该页 key}`/非 slides 顶层→`set()` deck 级/不可归属→`None` 全 deck;其余命令一律 `None` 不弱化)+ `_scope_demote()`(校验失败时按 `--json` 归属:in-scope 页/deck 级/schema 错→回滚、纯域外既存错→**降级保留写入**;解析失败 fallback 回滚)+ `write_deck_with_validation(...,scope_keys=)` 接线。**坑**:`set` 用**点**语法 `slides.N`(非方括号)索引数组,helper regex 一度只认方括号会误降级真 slide 错——已修两者都认。实测 4 场景全对(正常成功/deck级 demote/dot-path in-scope 回滚/unscoped reorder 仍全 deck 回滚)+ **112 回归测试全过、零回归**(deck-cli smoke + validate examples/static/gate/slide-filter + edit-roundtrip + atomic-render) | `deck-json/validate-deck.py` / `deck-json/deck-cli.py` |
| F-321 | **(C·截图工具)** 截指定页的 present 模式图**没有一等 CLI**:每轮手搓 Playwright(踩 `networkidle` 超时——iframe 页永不 idle、`ArrowRight`×N 翻页、letterbox 视口),本次重复 ~5 次。`deck-log` 有 snapshot 但绑 making-of。修法=`shoot --pages 19,20 --present [--aspect 16:10] [--out DIR]` 一行出 PNG:复用 `?mode=present` 入口、按 frame-index 翻页、`domcontentloaded`(非 networkidle)、可选 letterbox 视口验接缝。复用 log-tool present helpers。DONE 2026-06-13(`deck-json/shoot.py`:`?mode=present` 入口 + **框架自身键盘导航**(ArrowRight 走到目标帧——最初想用 is-current toggle 跳帧,实测和框架内部 currentIdx 抢控制、非确定性,改回 proven 键盘导航 + 650ms settle 等 fs-reveal)+ `domcontentloaded` + 4s `load` 上限 + 字体 ready;`--pages` 收 idx 或 slide-key、`--aspect` 16:9 design-clip / 其它比例全视口验 letterbox 接缝、缺页 rc=3。实测:design 19/20 + letterbox 13 内容/pager 全对、F-318 无缝可见) | `deck-json/shoot.py` |

## 2026-06-14 全量 code review 修复批次(F-323..F-331)

> 多 agent 全仓 code review(68 agents/13 子系统,每条 HIGH 经对抗式复核)产出 86 条
> 已验证 finding(0 critical / 6 high / 31 medium / 49 low)。按主题收成 9 个批次工单,
> 明细(file:line + evidence + fix + 复核结论)见 `docs/CODE-REVIEW-2026-06-14.md`。
> 分支 `fix/code-review-0614`(独立 worktree,off `6244ed7`)。

| 号 | 一句话 | 归属 / 覆盖 finding |
| --- | --- | --- |
| F-323 | **安全写收口**:4 个非 deck-cli 的 deck.json 写者统一走新 `deck-json/_safe_write.py`(原子写 + `validate-deck.py` 校验 + .bak 回滚),补齐它们各自缺的原子性/校验/回滚/锁——治「import 失败留下半截无效 deck.json」一类数据完整性洞 | `deck-json/_safe_write.py`(新)/ `import-html-slide.py` / `apply-text-pairs.py` / `reconcile-reflow.py` / `merge-canvas-lines.py` · mutation-1/5/6, misc-4, sync-5, reskin-11, lift-5 |
| F-324 | **资产拷贝路径穿越收口**:所有 copy 循环(paste/import/parser/package)用 `_safe_write.contained_dest()` 守住目标目录,`../`/绝对路径/symlink 逃逸一律跳过——治「crafted 源 deck 把文件写到 deck 目录外」 | `deck-json/deck-cli.py` / `import-html-slide.py` / `subskills/parser/parse.py` / `assets/package-deliverable.sh` / `assets/lift-slides.py` · subskill-3, mutation-2/3, delivery-4, lift-3 |
| F-325 | **validator 规则漂移闸补强**:把 `validate-deck.py` 纳入 rule-id 扫描面(R-CANVAS/R-FAMILY-DRIFT/R-DEMO-IFRAME 此前完全绕过漂移闸)、修契约测试正则(吃不下 `L1/L2/L4` 含 `/` 的 id)、补 validator-rules.md 反向闸、修指错文件的消息 | `assets/check-only.py` / `assets/audits.js` / `deck-json/validate-deck.py` / `assets/check-rule-coverage.py` / `references/validator-rules.md` / 契约测试 · contract-1/2/3, audits-js-1/3/5 |
| F-326 | **反向 sync / renumber / canvas 静默丢数据**:canvas 反映射保 size/font/grad/src/svg、整数几何不转 float;`--renumber` 不删 5G/3D 类前导 token;flow/swim 同季里程碑碰撞不丢;reskin 容器/run 不漏;edit-mode 存档剥 runtime !important;译文对不齐/重复替换防护 | `deck-json/sync-index-to-deck.py` / `render-deck.py` / `assets/reskin.py` / `merge-canvas-lines.py` / `edit-mode/deck-edit-mode.js` / `apply-text-pairs.py` / `extract-text-pairs.py` · sync-1/2/3/4, renderer-2/3, reskin-1/2, frontend-2, misc-2/6 |
| F-327 | **publisher/importer 闸门加固(外发面)**:无 deck.json 也必须过 validator、校验实际发布字节(非复用旧 audit)、self-check 不空过、网络子进程加超时、importer 不串 audit、报告模板键修 | `subskills/publisher/publish.py` / `self_check.py` / `subskills/importer/ingest.py` · subskill-1/2/4/5/6/8/9 |
| F-328 | **交付可移植性**:远程交付 zip 不再打包整个共享池(漏其他客户 logo)、`--inline` 认真 src 不认 data-src、inline-assets 不串属性、manifest 与实物一致、magic-page href 不当资源、下载限大小、shoot 浏览器不泄漏 | `assets/package-deliverable.sh` / `finalize.sh` / `inline-assets.py` / `copy-assets.py` / `magic-page-assets.py` / `shoot.py` / `shoot-page.py` / `render-deck.py` / `references/delivery.md` · delivery-1/2/3/5/6/7/8, renderer-1, prose-1 |
| F-329 | **HTML/CSS 正则脆弱解析**:scope @supports 等花括号 at-rule、scale_canvas 不跳含 font-size 整行、drop-shadow 偏移解析、div 深度计数避开注释/script、标题文本转义、band 行均值、迁移幂等 | `assets/reskin.py` / `deck-json/merge-canvas-lines.py` / `migrate-head-css-to-custom-css.py` / `reconcile-lifted.py` / `lift-slides.py` / `render-deck.py` / `deck-map.py` · reskin-3/4/5/6/7/8/9/10, lift-1/4, renderer-4, misc-7 |
| F-330 | **F-319 scope 闸加固 + 回归测试**:消息无「slide N」锚点的 in-scope 错(R05 emoji/!/…)不再被静默降级、no-browser 路径 scope 一致、parse_scope 拒非法区间、补 F-319 回归测试 | `deck-json/render-deck.py` / `assets/run-audits.py` / `audits.js` / 新回归测试 · diff-1/2/3/4, audits-js-2/4, renderer-6 |
| F-331 | **杂项健壮性 + 死代码 + 文档**:iframe scheme 白名单、_lint custom-property 误报、parse_value 类型强转脚枪、dead code 清理、frontend nav/overlay/reveal、PDF 八进制转义、deck-map disabled、translation-qa script 内 CJK、deck-log 版本号、文档契约修正 | 多文件(见 CODE-REVIEW 文档)· renderer-5/7, mutation-4/7/8, sync-6, lift-2/6, frontend-1/3/4/5, subskill-7, misc-1/3/5/8/9, prose-2/3/5/6 |

## 已裁决(WONTFIX / DONE)

| 号 | 含义 | 裁决 |
| --- | --- | --- |
| **F-36 / R-01** HTML→PPTX 导出 | 把 HTML deck 导出成 `.pptx` 文件 | **WONTFIX** · 2026-06-10 用户明确:北极星 = HTML deck,**不再需要 PPT,pptx 导出以后也不立项**;别再提此方向。 |
| **F-37 / R-02** 托管创作面 / 硬挂载门 | 非工程师托管创作入口 | **WONTFIX** · 同上,「PPT 替代」产品方向整体关闭。 |
| **F-292** F-256 视觉闸门调优 | 死代码降 advisory + 存量/imported 豁免 | DONE · commit `8a54484` |
| **F-290** render 提速(6b/6c Playwright 会话合并) | 真提速需重构 F-256/292/272 闸门数据源,风险>收益(性能间接 + F-255 的 --scope 已稀释慢只剩不常跑的全量) | **DEFERRED** · 2026-06-10 用户裁决跳过 |

## 2026-06-10 审计批量补强总账(commit `c4facb6` → `177d932`,6 个 commit)

把 `AUDIT-2026-06-10-ARCH-REVIEW.md` 里「可批量确定性做」的工单全部处理完。状态:

- **DONE**:F-255/256/257/260(`c4facb6`)· F-292(`8a54484`)· F-264/267/268/280/281/282a/291(`43cbf2c`)· F-259/262/272/279(`b4022c2`)· F-283 第一步/285/287(`92fc60b`)· F-266(`177d932`)
- **WONTFIX**:F-36/F-37(pptx 导出 / 托管创作面,见上表)
- **DEFERRED**:F-290(见上行)· F-283 完整字体子集化(B 版,需用户先拍「换开源字体」授权决策)
- **被证伪/已修正**:见报告 §4(16px 非全盲 / balanceSlide R-11 已重写 / 73vs96 混排不存在 等)
