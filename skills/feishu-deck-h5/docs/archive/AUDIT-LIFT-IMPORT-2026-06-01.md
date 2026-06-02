# AUDIT · LIFT + 忠实导入 (2026-06-01)

来源:把星巴克源 deck 的 19 页"保设计 + 只换文字"导入众安 deck 这一轮的实战复盘。
全程踩坑均指向 `lift-slides.py` / 导入路径 / 路由的可补点。编号 F-40..F-46(接最新 roadmap,撞号请并入)。

> 一句话:**`lift-slides.py` 能把简单排版页 1:1 搬过来,但带 bespoke 组件(手机 mockup/对话 UI/KPI 条)的页会塌;且忠实 lift 与四档字号闸天生冲突,目前没有 turnkey 工具调和,只能手搓。**

---

## F-40 · `lift-slides.py --shake` 漏掉 `[data-page=N]` 下的组件 CSS 【P0,最高价值】
- **现象**:lift 复杂页(店长陈列=手机对话 UI、罗莱=KPI条+5手机、知识冰山等)后,组件全塌成左侧一列纯文字。简单排版页(两种模式/认知/激励)正常。
- **根因**:源 deck 把组件样式 scope 在 `[data-page=N]` wrapper 下(如 `[data-page="18"] .slide .msg .bubble`)。`--shake` 只回收了 `.slide[data-slide-key=K]`-scoped 规则 + 基础 layout CSS,**没回收 `[data-page=N]`**;而 lift 又把内容里的 `data-page` 属性剥了 → 这页的组件 CSS 既没被带、也没了挂载点 = 整丢。
- **修法(已验证可行,应进工具)**:① 读源 `.slide-frame`(非 `.slide`)的 `data-page`;② tree-shake 时把**本页** `[data-page=N]` 规则纳入,选择器里的 `[data-page="N"]`(及其后跟的 `.slide`)rescope 成 `.slide[data-slide-key=K]`;③ 排除别页 `[data-page=M≠N]` / 别 key / 别 layout / `.deck`(否则类名跨页复用会拉进一堆规则,实测 → 1931 条 R20 误报)。
- **锚点**:本轮 `ch34-staging/faithful_css.py`(`keep_part`/`scope_selector`/`shake` + `key_datapage.json` 映射)就是这套逻辑的原型,可直接吸收进 `lift-slides.py --shake`。
- **影响**:修了这条,复杂页 lift 一把过,不用手搓 CSS。

## F-41 · `lift-slides.py` 系统性少一个 `</div>` 【P0,易修】
- **现象**:19 页**每页**都 +1 div 不平衡(15 开/14 闭),触发 R-DOM,渲染失败。
- **根因**:源 fragment 本身平衡(19/19,含 frame+slide wrapper)。抽取剥 wrapper 时多吃了一个闭合 `</div>`。注:DESIGN-PLAN(2026-05-29)记过一个"末尾多带 `</div>`"的**反向** bug 已修(`closes_seen==2`);这次是**少带**,边界判定需再校。
- **临时修法**:抽完后 `delta = html.count('<div')-html.count('</div>')`,`delta>0` 末尾补 `</div>×delta`(本轮 `lift_all.py` 用的)。但治本应在 extractor 抽对。

## F-42 · "lift 进既有 deck"缺忠实导入的成套调和工具 【P1】
- **现象**:忠实 lift 一份手搓源 deck → 1900+ 条 R20(源合理用了 11/18/22/38px 等非四档字号)。还连带 R05(emoji 当图标)、UI1(persona `<img>` 当正文)、R-VIS-ABSPOS、R13(标题 `<br>`)、R-OVERFLOW 等一串源设计自带的违规。
- **缺口**:`grow-box-fit.py`/`rebundle-import.py` 是给"独立导入整份外来 deck"的;**"从外来 deck 拎几页进我的 deck"没有对应工具**;`fs-deck-origin=imported` 又已被剥夺降级权(IMPORT-RAW-DECK-LESSONS L1 撤回)→ 问题全留给人手。
- **修法**:出一个 **`reconcile-lifted.py`**(mockup-aware):
  - 字号 snap 到 16/24/28/48,但 **mockup 内小字(<16,在 `.phone`/`.ui-*`/已声明 mockup 容器内)不动**(否则撑破手机框,实测 R-VIS-CARD-OVERFLOW);hero 区(≥80)不动。
  - 自动声明常见 import 违规:persona `<img>` 补 `data-ui-screenshot`、dual-anchor 补 `data-allow-dual-anchor`、标题去 `<br>`、emoji 字形→SVG/中性符。
- **锚点**:本轮 `ch34-staging/postfix.py` + `faithful_css.py:snap_fonts` 是原型。

## F-43 · MODE 路由缺"lift 保设计 + 换文字"独立入口 【P1,省整轮白做】
- **现象**:"把这些页换成众安,需要重新设计"在 RESKIN(只换皮)和 GENERATION(重画)之间是**真歧义**。第一版判成"重画"、做了 19 页 schema 重设计,用户"理解错了"才返工。
- **根因**:`converting-existing-material.md` 的 Replica vs Rewrite 只在"转 PDF/PPT"触发;"把另一份 deck 的页导进来"没命中该分支。
- **修法**:REQUEST ROUTER / MODE SELECTION 加一条:**转换/导入既有 deck 的页时,先确认「保留原版式(lift) vs 重做版式(schema 重设计)」,默认偏保留**(与 RESKIN 默认一致)。把"lift+换文字"作为与 RESKIN/GENERATION 并列的第四条路明确写出来。

## F-44 · 缺"只换字、不动结构"的安全 text-swap 模式 【P2】
- **现象**:lift 后要把文字换成新客户,但让 LLM 重写整段 HTML 会改坏结构/CSS。
- **本轮做法(值得固化)**:agent 只产出 `[{find, replace}]` 精确替换对,主对话**程序化套用**(`html.replace`),结构 100% 不动。19 页 253 对、247 命中。
- **修法**:把"find/replace-pairs text-swap"写成 skill 标准做法 + 一个 `apply-text-pairs.py`(报告未命中项,常见未命中=源/产物间 `<br>`/emoji 归一化差异)。

## F-45 · lift 资产带不全且不报告 【P2】
- **现象**:base64 内嵌图、iframe 引用的正文(jay 页正文在 `assets/custom/.../*.html`,该文件不存在 → 整页正文空)、clientlogo(罗莱 logo)带得不一致。
- **修法**:lift 应**报告引用了哪些资产 + 标出品牌特定的**(clientlogo/`input/` 截图/iframe src)让人决定替换或移除,而不是静默丢/留。

## F-46 · workflow `args` 以字符串到达 【P3,偏 harness 但写进模板省踩】
- **现象**:首次发 dynamic workflow,`const briefs = args` → `args` 是字符串(非数组)→ `briefs.map` 抛 "undefined is not a function",整个 workflow 秒挂。
- **修法**:skill 里所有 workflow 示例/模板加护栏 `const x = (typeof args==='string') ? JSON.parse(args) : (args||[])`。

---

# 第二批 · "换 demo / 单页编辑为什么这么慢"复盘 (2026-06-01 下午)

> **状态(2026-06-01 已处理)**:F-47/F-48/F-49 全部落地。F-48 乐观锁已实现进 `deck-cli.py`
> (`write_deck_with_validation` 加 `expected_mtime`/`force` 参数 + main 读 deck 时抓 mtime + 新增 `--force` flag;
> 实测 并发改动→拒写、--force→放行、6 个 smoke 测试仍过)。F-47/F-49 护栏写进 SKILL.md
> `SMALL-EDIT DISCIPLINE` 第 4/5/6 条。下面工单原文保留供追溯。

来源:pg22 嵌入 demo 换成"疑难件一句话调度"这一轮,一个本该 5-6 步的线性小任务**实际花了 ~50 分钟**。复盘后大头是**执行纪律失误**(F-47/F-49,不是 skill 缺陷,但值得固化成护栏防复发)+ 一个**真·环境缺口**(F-48 并发写)。诚实记账:F-47/F-49 主要是 agent 操作问题,skill 侧只能给"提示/默认"层面的护栏。

## F-47 · 轻量线性任务被误甩给 subagent → 42 分钟 / 291 次工具调用 【P1,纪律+护栏】
- **现象**:"换个自包含 demo 文件 + 接进 pg22 + 适配 16:9"= 5-6 步直线操作(cp → file:// 渲染测 → 改 deck.json src/title → render → 截图核验)。主对话自己做约 6 次工具调用即可。**却委托给 general-purpose subagent**,它在隔离环境从零摸索、反复 Playwright 核验、跑了 **42 分钟 / 291 次工具调用**,还被并发写覆盖过一次要重做。
- **根因**:对任务复杂度误判 + 违反既有 memory `feedback_deck_background_worker`(默认内联,只对**重型 hero/raw 慢页**才甩后台 subagent)。换 demo 不是重型页,不该甩。
- **修法(护栏,非硬规则)**:在 SKILL.md 的"单点小改/SMALL-EDIT DISCIPLINE"节补一句**反例**:"换 demo 文件 / 改 src / 改 title / 套 custom_css 这类已知步骤的单页操作 = 主对话线性自做,**不甩 subagent**;subagent 只留给真正需要并行 fan-out 或大范围摸索(多文件审计/全 deck 搜索)的活。判据:**步骤已知且 ≤~10 步 → 自做**;步骤未知需探索/可并行 → 才考虑委托。"
- **影响**:这一条是本轮最大时间黑洞,修了(养成判据)单页编辑回到秒级。

## F-48 · 同一 deck 被多 session 并发写,无锁 / 无检测 / 无提示 【P1,真缺口】
- **现象**:本轮全程另一个 session 在持续重写同一份 `deck.json`(24 页 → 44 页),把测量结果冲掉、把改动覆盖过一次(subagent 在 08:45 版上重做才稳住)。每次 read-modify-write 都得先确认"是不是又变了",拖慢且有静默互相覆盖风险。
- **根因**:deck.json 是单文件 source-of-truth,但**无任何并发保护**——没有锁文件、没有"自上次读后是否被改"的检测、render/deck-cli 也不告警。两个 agent 同时 in-place 编辑就是 last-writer-wins。
- **本轮缓解(值得固化)**:① 写前一刻重读 deck.json + 断言页数/关键页 key 不变(本轮 `add_value_page.py` 的 assert 正确拦下了两次并发改动,没盲写);② 挂后台 watch 等 deck.json"连续 150s 不变"再批量改。
- **修法**:(a) `deck-cli.py` / render-deck.py 写入前做**乐观锁**——记录读取时的 mtime/hash,写回前比对,变了就拒绝 + 提示"deck 已被其他进程改动,请重读";(b) SKILL.md 并发节明确"多 session 同改一 deck 时,Edit/写入前重读 + 断言关键不变"(已有 memory `feedback_refresh_before_edit_concurrency`,把它具体到 deck.json 工作流)。
- **影响**:消除静默覆盖,多 agent 协作同一 deck 才安全。

## F-49 · 单页改动的 Playwright 核验冷启 + babel demo 编译,累加成本高 【P2】
- **现象**:每次核验都冷启一个 chromium + 等 React/Babel demo 内编译(单次 4-5s),一轮里截了很多次 → 累加可观。叠加 F-47 的 291 次调用里大量是这种核验。
- **根因**:无常驻预览;每次 `python3 shot.py` 都新 launch。且对单页小改做了过多"截图—看—再截"循环。
- **修法**:① SMALL-EDIT DISCIPLINE 已有"小改最多对那一页截 1 张图确认、别全量"——本轮违反了,强调执行;② 可选:提供一个**常驻 headless 预览服务**(launch 一次、按 slide key 截图的小工具),把冷启摊销掉。但 ① 是主要矛盾,② 是锦上添花。

---

## 优先级
- **先做 F-40 + F-41**(把 lift 工具修对 → 复杂页不用手搓 CSS + 不再 div 不平衡)。
- **再做 F-43**(路由确认 → 省掉"理解错→整轮白做")。
- F-42/F-44 把本轮手搓的 `faithful_css.py`/`postfix.py`/`apply_swap.py` 收编成正式工具。
- **F-48(并发乐观锁)单独拎出**:它是唯一的"真·环境缺口",且影响所有多 session 协作,价值高、相对独立。
- **F-47/F-49 是纪律护栏**:不需写代码,补进 SKILL.md SMALL-EDIT DISCIPLINE 的反例清单即可(便宜、防复发,本轮就栽在这)。
- 本轮全部脚本 + 中间产物留档在 `runs/20260528-192338-zhongan-ai-org/ch34-staging/`(可作各修法的参考实现)。

# 第三批 · 众安 deck 并发 lift(24→46 页 / 18✗185!)四维综合审查 (2026-06-01)

来源:把星巴克源 deck 的 19+ 页 lift 进众安、并发堆到 46 页,产出 18✗185! 的实战。
4 个维度(lift-bloat / fontsize-gate / mock-overflow / process-discipline)独立分析后去重、
按投入产出排序。编号 **F-50 起**;与已有 F-40~F-49 重叠处**并入注明**,不另起新号。

> **一句话总结**:这 18✗185! 不是 18 个孤立 bug,而是**两个系统性框架缺陷 + 一组流程缺口**的复利产物,可归为 **4 大类**:
> (1) **lift 搬运的 CSS 全坏了**——源 slide 内联了整份框架 CSS,lift 原样搬入,且前缀注入用正则把选择器啃成非法形态(`-frame.is-current` 129 处死动画、`[data-slide-key] /*注释` 1301 条死规则);
> (2) **静态字号闸是哑的**——R20 只认死约定 `[data-page=`(实测 index.html 中 `data-slide-key:data-page = 10553:4`),现代页一律漏审;
> (3) **lift 写路径绕过 F-48 乐观锁 + 无"进一页校一页"闭环**——违规以批量、滞后方式一次性爆发;
> (4) **纪律/文档盲区**——SKILL.md 对 raw/lift 页有失真承诺、无批次纪律、无 LIFT-DONE 定义。
>
> **最该先修**:**F-50(lift 剥离框架 CSS 副本)** 与 **F-51(选择器合法性 / `-frame` 还原)** 是同一次 CSS-parser 重写就能一起解决的**最高杠杆项**——它们一把消掉体积 71%(~1.5MB)+ 1301 条死规则 + 129 处死动画(后者又是 mock 裁切和一批 R-VIS-ORPHAN/FOCAL "!" 的隐藏成因)。其次是 **F-52(R20 gate 一行改)**,让 36 张现代页的字号梯子在静态层重新被守住。

---

## 高杠杆(改框架/工具,一次性消一大批 findings)

### F-50 · lift 把源 slide 内联的"整份框架 CSS dump"原样搬入(每页背 ~88KB 框架副本)【P0,最高杠杆】
- **现象**:16 个星巴克-lift 页各含 30–88KB 的 `<style>` 块,全是 framework `feishu-deck.css` 逐条加 `[data-slide-key=K]` 前缀的副本(back-starbucks-store-day 88KB / 354 条规则,0 other-key、3 global,几乎全冗余)。16 页 CSS 合计 **1.73MB(占其 html 71%)**,其中 1.49MB 是框架 dump;index.html 已实测 2.62MB。
- **根因**:源 deck 在 lift 之前已用 `migrate-head-css-to-custom-css` / `custom_css` 同页化(R-SELF-CONTAINED)把整份框架 CSS 逐条前缀内联进了每个 `.slide` DOM。`lift-slides.py:extract_one()`(L249-293)逐字切 slide 内层(`inner = "".join(src_lines[slide_open:slide_close-1])`),框架 dump 随之进来;`--shake` 的"不内联 global `.slide .foo`"承诺只管它**自己生成**的 CSS,管不到**已躺在源 DOM 里**的那一份。
- **修法**:在 `transform()` 增"框架副本剥离"步——把搬来的 `<style>` 块逐规则用 CSS parser 比对 framework(`feishu-deck.css`/`extra-layouts.css`/`feishu-deck-patterns.css`),去前缀后规则体与同选择器逐字一致即删除(目标 deck 已 link 框架,`[data-layout="raw"]` 默认生效兜底);只保留 bespoke override。源头同修 `migrate-head-css-to-custom-css`:只同页化真正 per-slide 自定义规则,**不要**把框架全量前缀内联。
- **影响**:16 页 ×(30–88KB)≈ 1.49MB 冗余清零,index.html 预计 2.62MB→~1.2MB;编辑/round-trip/validator 全文正则扫描全面减负。需逐页 `--visual` 回归确认框架兜底无视觉回退(L79 已强制此步)。
- **优先级**:**P0**(体积主因,且阻塞 fontsize/mock 维度的可维护性与可推理性)。

### F-51 · lift/前缀注入把选择器啃成非法形态:129 处死动画 + 1301 条死规则【P0,与 F-50 共修法 / 部分并入 F-40】
- **现象(两种损坏,同一类根因)**:
  - (a) **死动画**:所有 lift 页的进场/滚动动画 scope 被啃成非法的 `.slide[data-slide-key="K"] -frame.is-current ...`(`-frame` 不是合法 type/class,永不匹配)。**实测 index.html 共 129 处** `-frame.is-current`,分布 18 个 lift 页(pg26-46),对照仅 27 处合法 `.slide-frame.is-current`。后果:消息默认态 `opacity:0`,进场动画永不触发 → pg40/pg41 手机 3/4 条消息**永久隐身**;`.ph-chat-inner` 自动上滚永不播 → 被裁的 244–300px **永远滚不出来**。**疑为 R-VIS-ORPHAN!9 / R-FOCAL-CHECK!10 等一批 "!" 的隐藏成因**(内容停在动画初态)。
  - (b) **死规则**:大量 `.slide[data-slide-key="K"] /* comment */ .header {…}`——前缀贴到注释左边,非法,整条丢弃。**实测 1301 处**。
- **根因**:前缀注入(在 `migrate-head-css-to-custom-css` / 源同页化 / lift 的 class-prefix 重写)用纯字符串/正则在选择器头插前缀,**没用 CSS parser**——把内联注释当选择器一部分,把 leading combinator/class token(`.slide-frame`)啃掉。lift 把损坏结果原样搬入。
- **修法**:F-50 的剥离若改用真 CSS parser(`_css_utils.iter_css_rules` 的 brace-match 解析)即顺带修正/丢弃损坏规则;`lift-slides.py --shake` 的选择器重写禁止啃掉 leading combinator/class token,并在重写后断言选择器合法性(任何以裸 `-` 开头的简单选择器即报错)。**本 deck 止血**:129 处 `-frame.is-current`→`.slide-frame.is-current` 精确串替换(运行时宿主类确认为 `.slide-frame`,见 `feishu-deck.js`)。
- **影响**:消除 1301 条静默死规则 + 18 页全部死动画,自愈 pg40/pg41 mock 裁切(动画一活,457px 窗口分时复用,300px 内容滚得出来),并可能一并清掉多条 R-VIS-ORPHAN/FOCAL "!"。
- **优先级**:**P0**。与 F-50 同一次 parser 化即可解决。**(a) 死动画与 F-40「shake CSS 处理」同源,但是独立缺陷,单列;(b) 死规则纯靠 F-50 剥离顺带。**

### F-52 · R20 静态字号梯子闸对 `data-slide-key` 页失效(哑闸 + 失真承诺)【P0,一行修,高杠杆】
- **现象**:`assets/_validate_audits.py:298` `audit_type_ladder()` 仅审 selector 含 `[data-page=` 的规则;现代管线全用 `[data-slide-key=`(**实测 index.html 10553:4**)。R20 在每张 raw/lift/custom_css 页都是 no-op。pg21 `system-integration-thesis` 的 30/25/28/20、pg24 `sfdc-daily-ai-summary` 的 23/21/20 全 off-ladder 却静态全绿,只有 `--visual` 的 R-VIS-TIER 兜得到。SKILL.md:418 还对 raw 页明写"4-tier ladder 全在",作者据此放心写 30/28 = **信任陷阱**。
- **根因**:`data-page`→`data-slide-key` 的 scope 约定迁移时,R20 的 gate 没跟着改;且 `deck-json/tests/test_validate_static_rules.py:21,135-138` 把"无 `data-page`→不报 R20"断言成**预期行为**,反向保护了这个盲区。R06(字号下限,L185)gate 认 `.slide/.card/.col`,raw 页有这些类故会触发(pg24 的 <24 被 R06 抓到),但 R06 不管 >24 的 off-ladder → 28/30 全靠死掉的 R20。
- **修法**:line 298 gate 改为 `if '[data-page=' not in selector and '[data-slide-key=' not in selector: continue`(与 R06 对齐;`allow:typescale` opt-out 已就位,hero 例外不受影响)。同步改测试为"`data-slide-key` 页 off-ladder → 报 R20"。SKILL.md:418 在 F-52 落地前加注"静态梯子当前仅 Playwright 兜",落地后承诺即真。**改 gate 时一并给 R20 接上 lifted→warn 降级**(`_lifted_slide_keys`,L218/226,与 R06 同款),否则 36 页一次性炸出几百条 err 淹没真问题。
- **影响**:一行改让全 deck 36 张 raw/lift 页的字号梯子在静态层重新被守住,不依赖 Playwright。
- **优先级**:**P0**。

### F-53 · `lift-slides.py` 完全绕过 F-48 乐观锁 → lift 写路径仍可静默覆盖并发改动【P0,F-48 真闭环】
- **现象**:F-48 的乐观锁只活在 `deck-json/deck-cli.py:write_deck_with_validation`(L134,`expected_mtime` 比对 + `--force`),仅 `paste`/`set` 等命令到达。但本轮 22 页是用 `assets/lift-slides.py` 搬的——L503 直接 `dst_deck_json.write_text(...)`,`grep -c expected_mtime lift-slides.py == 0`,无读时记 mtime / 写前比对 / `--force`。本轮最频繁的写路径上,**F-48 等于没修**(另一 session 全程 24→46、覆盖过改动)。
- **根因**:F-48 把锁修进了 deck-cli,但没把它提成所有写路径共用的 helper;lift / `import-html-slide.py` 是裸写嫌疑路径。
- **修法**:把 `write_deck_with_validation`(含 `expected_mtime`/`force`)提成共享 helper,`lift-slides.py` 与 `import-html-slide.py` 改用之:load 时记 `dst.stat().st_mtime`,写回前比对,被改则拒写 + 提示重读,加 `--force` flag。
- **影响**:F-48 的真正闭环——不修这条,"乐观锁已修"是假象,最高频写路径仍 last-writer-wins。
- **优先级**:**P0**。(并入/接续 **F-48**:F-48 实现了锁,F-53 把锁接进 lift。)

### F-54 · 缺"批量 lift → 每批 reconcile 字号 + validate"的成套闭环(turnkey)【P0,本轮顺序坑根因 / 依赖 F-42】
- **现象**:22 页一次性 lift,全程无一步强制"进来后立刻 reconcile 四档 + 跑 validator",18✗185! 一次性砸到用户脸上。pg21/pg24(off-ladder)、pg40/41/42(溢出裁切)全是**进来时就该被拦**的。
- **根因**:① `lift-slides.py --key KEY,KEY` 支持多 key,但做完只 write_text,不 validate、不 reconcile;② F-42 的 `reconcile-lifted.py`(字号 snap + mockup-aware)**仍未实现**;③ SKILL.md L982 的 validator 硬闸是"declaring deck done 前"语境,**未绑定到 lift 动作**。三者叠加 = 流程上完全允许"只 lift 不 reconcile 不 validate"。
- **修法**:出一条批量 lift 闭环命令(或在 `lift-slides.py` 批量模式末尾内建),每批强制原子三步:① 跑 F-42 `reconcile-lifted.py`(snap 四档,mockup<16/hero≥80 不动)② 跑 `validate.py` ③ 回报 ✗ 列表,**✗ 未清零/未登记不算"lift 完成"**。报告里**附带每页 lift 后字节数 + scope 前缀计数**,>100KB / >N 次前缀显式 flag(让"lift 22 页=2.3MB"在动作发生时就可见,接 F-50)。
- **影响**:直接消灭"先大量 lift 再统一修"这个顺序坑。
- **优先级**:**P0**(依赖 F-42 `reconcile-lifted.py` 落地)。

### F-55 · `--shake` head-CSS 恢复"整条多目标规则保留",把无关 slide-key 拖入本页【P1】
- **现象**:lift 页 style[2](AUTO-RECOVERED,6.6KB)里出现 8 个不同 slide-key,7 个与本页无关。每个 lift 页都把源那条"一条 animation 列几十个 key"的多目标规则整条搬来。
- **根因**:`extract_head_slide_rules()`(L216-236)注释自承"Over-inclusive:多目标规则只要含本页 key 就整条保留"。
- **修法**:恢复时把多目标 selector 按逗号 split,**只裁出含本页 key 的那一支**(保留其引用的 @keyframes),丢弃其余。
- **影响**:消除"页 A 的 CSS 提到页 B/C/D 的 key"的跨页耦合噪声(也利于并发安全),head-recovered 块体积下降。
- **优先级**:**P1**(shake 自身可控的逻辑缺陷,修起来干净)。

### F-56 · pg42 lift-merge 把多条冲突 `.stage` 规则层叠进同一 slide-key,整页溢出 +419px【P1,并入 F-42 reconcile 职责】
- **现象**:pg42 `back-closed-loop-store-decision` 无 `.phone`,但同一 `[data-slide-key]` 下有 **5 条互相冲突的 `.stage` 规则**(absolute/padding/justify 打架),末位 `justify-content:center` 把 1331px 内容列在 856px 框里居中→上下溢出→slide 撑到 1499px(画布 1080,+419)。R-OVERFLOW 抓到了(✗1)但只报"画布溢出",没指向"stage 规则层叠"这个 lift 病根。
- **根因**:`deck-cli paste` / lift-merge 合并多源页 CSS 时对 `.stage`(及其它同名结构规则)未去重,原样堆叠、最后写者生效。
- **修法**:本 deck——去重 stage 规则留 1 条,step-node 列改 `justify-content:flex-start` 或 `.stage--tall`,压进 856px。框架——lift-merge 对同名结构规则去重 / 最后写者告警,并入 **F-42 `reconcile-lifted.py`** 职责。
- **优先级**:**P1**。

### F-57 · validate 增"动画落地"校验 R-VIS-DEAD-ANIM(声明了 animation 的元素其选择器必须运行时真能匹配)【P1,堵 F-51 整类】
- **现象**:F-51 的 129 处死选择器 validate 一条不报——它不查选择器合法性,也不查动画是否真播了,靠人肉 grep 才发现。
- **修法**:visual-audit.js 加一项:凡 CSS 出现 `animation:` 的规则,其选择器在 present 模式下 `document.querySelectorAll(sel).length===0`(或解析抛错)即报 **R-VIS-DEAD-ANIM**(err)。一次性堵住"选择器被啃→动画静默失效"整类。
- **优先级**:**P1**(把 F-51 修复固化成回归护栏)。

### F-58 · R-VIS-CARD-OVERFLOW 升级:区分"可滚出 vs 永久不可见",并把 mock 裁切预检前移到 lift 当下【P1】
- **现象**:检查器对本例 2 处 clip(pg40/pg41 `.ph-chat`,=✗2)**没有漏报**;gap 在 (a) 文案不区分"被裁但能滚出来" vs "被裁且动画死了永远滚不出来"(本例属后者最坏);(b) 裁切只有跑全量 `--visual` 才暴露,lift 当下(`lift-slides.py`/`deck-cli paste`)不报。
- **修法**:(a) clip 分支(visual-audit.js L289-300)对被裁元素加探测:overflow:hidden 且内部无可用滚动(`scrollTop` 恒 0 / 滚动 transform 恒 identity / 被裁子元素 opacity:0)→ 升级文案"内容永久不可见(non-recoverable clip)"并顶格 err;(b) lift 工具落地后对含 `overflow:hidden` 的容器跑轻量 scrollHeight 预检,超框即在 lift 报告里列"该 mock lift 后裁掉 N px"。
- **优先级**:**P1**(覆盖率不缺,缺严重度刻画 + 预警时机)。

### F-59 · raw 页四档字号脚手架:CSS 变量 + 写前查表(把 correct-by-construction 搬回 raw 路径)【P1】
- **现象**:schema 页字号 100% 来自手调过的框架模板,作者无处写 px → 物理上不可能 off-ladder;raw 授权区(SKILL.md:412-428)从不把 `{16,24,28,48}` 摆到作者眼前,作者凭记忆写裸 `font: ... 30px` = construction 保证断点。
- **修法(二选一或并用)**:(a) 框架 CSS 暴露四档语义变量 `--fs-tier-title:48px / --fs-tier-sub:28px / --fs-tier-body:24px / --fs-tier-foot:16px`,raw 授权区改为"字号一律 `font-size: var(--fs-tier-*)` 引用,不写裸 px";(b) SKILL.md raw 段加一行硬要求 + 四档速查表,模板/例子只用变量。
- **优先级**:**P1**(与 F-52 配合闭环:F-52 是兜底闸,F-59 是写时正道)。

---

## 低杠杆(纪律/文档护栏,便宜、防复发)

### F-60 · validator 增 R-LIFT-CSS-BUDGET:单 lift 页内联 CSS 体积上限【P1,F-50 落地后启用】
- **现象**:缺任何对 lift 页 CSS 体积的硬约束,导致 88KB/页 裸奔到 18 页。
- **根因**:R-SELF-CONTAINED 只查"head 是否泄漏 per-slide CSS",不查"slide 内联了多少",方向相反,反而鼓励把 CSS 全塞进 slide。
- **修法**:`layout:"raw"` 且带 `lifted` 的页,`<style>` 合计 >15KB 报 `!`、>40KB 报 ✗。**必须在 F-50 落地后启用**,否则全红。
- **优先级**:**P1**(把 F-50/F-51 修复固化成护栏)。

### F-61 · raw 页 CSS 未走 `custom_css`,内联进 `data.html` 的 `<style>`(弃用写法)【P1,并入既有 LIFT-ARCHITECTURE L2】
- **现象**:pg21/pg24 `custom_css` 为空串,per-page CSS 以 `<style>` 块塞在 `data.html` 里——LIFT-ARCHITECTURE L2 / memory `feedback_pageanim_not_in_deckjson_schema` 已判定弃用(republish/round-trip 易静默丢失),正道是放 `slide.custom_css` 由 render 自动 scope+co-locate。
- **修法**:把这两页(及同 session 同写法 raw 页)`<style>` 迁到 `custom_css`,迁移时顺手把裸 px 改成 F-59 的四档变量。可复用 `deck-json/migrate-head-css-to-custom-css.py`(但需先修 F-50/F-51 的前缀注入,否则迁移会抄进损坏选择器)。
- **优先级**:**P1**。

### F-62 · 工作流缺"分批 + 增量校验"纪律(BATCH LIFT DISCIPLINE)【P0→纪律,便宜防复发】
- **现象**:24→46(+22)是一次爆发式 lift;用户"踩了不少坑"的体感来源就是问题以**批量、滞后、一次性**方式暴露。SKILL.md LIFTING 节(L803-825)只讲"怎么 lift 一页",没讲"lift 很多页时的批次纪律";SMALL-EDIT DISCIPLINE 管单页小改,管不到"22 页大迁移"这个量级——中间量级是纪律盲区。
- **修法**:LIFTING 节加 "BATCH LIFT DISCIPLINE" 子节铁律:① 绝不"先全部 lift 再统一修",每 3–5 页一批,每批走 F-54 闭环;② 边 lift 边修>先 lift 后修,复杂页(mockup/对话/KPI 条,F-40 已知会塌)lift 一页立刻渲染截图核验;③ 字号 reconcile 是每批准入闸,不让 off-ladder 页"先进来欠着"。
- **优先级**:纪律护栏,**便宜、本轮就栽在没写明**。

### F-63 · "LIFT DONE = 4 项全绿"正式 Definition-of-Done checklist【P1,文档闸】
- **现象**:本轮"lift 完了"=页面进了 deck.json,无任何标准说"欠 reconcile / 欠 validate / 欠 per-page 截图核验 = 没完成",于是 18✗185! 的 deck 被当"lift 好了"交付。SKILL.md L982 是整 deck 交付前的硬闸,没有 lift 动作自己的 DoD。
- **修法**:LIFTING 节加每批 checklist:[ ] DOM 平衡(R-DOM,接 F-41)[ ] 复杂组件页逐页截图未塌(接 F-40)[ ] 字号已 reconcile 四档、`validate.py` 无 off-ladder ✗(接 F-52/F-59)[ ] 无静默裁切,R-VIS-CARD-OVERFLOW/R-OVERFLOW 无 ✗(接 F-56/F-58)。任一不绿 = lift 未完成,不得宣称交付。
- **优先级**:**P1**。

### F-64 · 多 session 并发协作协议:把"靠 agent 机灵"沉淀成默认动作【P1,纪律+文档】
- **现象**:F-48/F-53 是被动拦截(锁),但 agent 不知道何时该意识到自己处在并发场景。本轮两 session 全程同改一份 deck,靠 subagent 在 08:45 版上重做、靠 `add_value_page.py` assert 手搓拦截——纪律靠临场发挥,没沉淀。
- **修法**:SKILL.md 并发节扩成一张协议小表:**检测信号**(deck.json mtime 比上次读新 / `git status` 显 ` M` / harness 提示 "file modified externally" / lift·deck-cli 拒写报 "concurrent modification")→ **退避动作**(重读最新→把自己改动 rebase 到新版→重试;连续撞→后台 watch "连续 ~150s 不变"再批量改)→ **`--force` 唯一合法场景**(仅确认自己是唯一写者时;并发用 `--force` = 故意覆盖,等同 force-push 红线)。配合 F-53 让 lift 也抛 "concurrent modification",信号才在所有写路径一致可见。
- **优先级**:**P1**。

### F-65 · R20 进 render-deck 默认静态闸 + 加 `data-slide-key` 回归 fixture【P2】
- **现象**:本类问题拖到全量校验才暴露,因为只有 `--visual` 才跑 R-VIS-TIER,新手 render 默认不带。
- **修法**:确认 render-deck.py 默认静态 validate 含 `audit_type_ladder`;`tests/` 增一条 `[data-slide-key=]` + off-ladder 的 fixture,固化 F-52 不被回退。
- **优先级**:**P2**。

### F-66 · 全 deck `data-slide-key` 页静态字号一次性清账【P2,体检】
- **现象**:36 张 raw 页此前全在 R20 静态盲区;F-52 修好后需一次性回扫,把 ">24 floor 但 off-ladder" 存量(lift 进来的星巴克页大概率一片)全曝出来。
- **修法**:F-52 落地→render→收集全部新增 R20→与已知 18✗/185! 对账,区分"lift 页(warn,可留)" vs "新手写 raw(err,必修)";按 IMPORT-RAW-DECK-LESSONS 的修法(grow-box-fit / 重生成,绝不盲 snap)逐页处理。
- **优先级**:**P2**。

---

## 投入产出总览

| 杠杆 | 工单 | 一次性消掉 |
|---|---|---|
| **极高** | F-50 + F-51 | ~1.5MB 体积(71%)+ 1301 条死规则 + 129 处死动画(连带自愈 mock 裁切 + 一批 R-VIS-ORPHAN/FOCAL "!") |
| **高** | F-52 | 36 张现代页的静态字号梯子重新被守(一行改 gate) |
| **高** | F-53 | F-48 乐观锁接进最高频写路径(lift),消静默覆盖 |
| **高** | F-54 | 消灭"先堆 22 页后修"顺序坑(依赖 F-42) |
| 中 | F-55/F-56/F-57/F-58/F-59 | shake 多目标裁剪 / stage 去重 / 死动画护栏 / clip 严重度 / raw 四档变量 |
| 低(纪律) | F-60~F-66 | 体积闸 / custom_css 迁移 / 批次纪律 / DoD / 并发协议 / R20 默认闸 / 清账 |

**编号说明**:F-50~F-66 接续本文件 F-40~F-49,无内部撞号。并入既有工单的:F-51(死动画与 **F-40** 同源,独立缺陷单列)、F-53(接续 **F-48** 闭环)、F-54/F-56(依赖/并入 **F-42** `reconcile-lifted.py`)、F-61(并入 LIFT-ARCHITECTURE L2 弃用判定)。

---

## 本轮可立即落地的(便宜护栏) vs 需排期的(改框架/工具)

### A. 本轮可立即落地(便宜护栏,今天就能补)
- **F-52** 一行改 gate(`_validate_audits.py:298` 加认 `[data-slide-key=`)+ 同步改 `test_validate_static_rules.py:21,135-138` —— 纯一行 + 测试,最高 ROI。
- **F-51 本 deck 止血**:129 处 `-frame.is-current` → `.slide-frame.is-current` 精确串替换(框架重写另排期)。
- **F-55** 文档侧:SKILL.md:418 在 F-52 落地前加注"静态梯子当前仅 Playwright 兜"(已被 F-52 吸收为同步项)。
- **F-62 / F-63 / F-64** 纯文档:SKILL.md LIFTING 节加 BATCH LIFT DISCIPLINE + LIFT-DONE checklist + 并发协作协议表。
- **F-61** 本 deck:pg21/pg24 `<style>`→`custom_css`(需 F-50/F-51 前缀注入修好后再批量迁,否则抄进损坏选择器)。

### B. 需排期(改框架/工具,需测试 + `--visual` 回归)
- **F-50 + F-51(框架侧)**:`lift-slides.py` `transform()` 加 CSS-parser 化的"框架副本剥离 + 选择器合法性断言";源头修 `migrate-head-css-to-custom-css` 不再全量前缀内联。**最大工程量、最大收益,优先排。**
- **F-53**:`write_deck_with_validation` 提共享 helper,`lift-slides.py` / `import-html-slide.py` 接乐观锁。
- **F-54 + F-42**:实现 `reconcile-lifted.py`(mockup-aware snap)+ 批量 lift 闭环命令(lift→reconcile→validate 原子三步)。
- **F-55(shake 多目标裁剪)/ F-56(lift-merge stage 去重)/ F-57(R-VIS-DEAD-ANIM)/ F-58(clip 严重度 + lift 预检)/ F-59(四档 CSS 变量)/ F-60(R-LIFT-CSS-BUDGET,F-50 后启用)/ F-65(R20 入默认闸 + fixture)**。
- **F-66**:F-52 落地后跑一次全 deck 静态字号清账,对账 18✗/185!。

---

# 第四批 · "存量 deck 修页"复盘 (2026-06-01 晚)

来源:用户回头点修 #39 冰山(20%/80% 大字没了)、#40/41 demo 塌、#42 闭环散架等单页,
逐页手工诊断+止血一整轮。**核心教训:F-40/50/51/52 的修复全是 forward-only(修工具),
但本 deck 是旧工具 lift 的、损坏已固化在产物里,没有任何"回头治存量"的路径 → 每一页都得
人肉重走一遍 parser 当年没做的事**。验证:`iter_css_rules` 现已剥注释(F-51 工具侧已落地)、
R20 gate 已认 `[data-slide-key=`(F-52 已落地,本轮正是它把 pg21/pg24 off-ladder 抓出来的)、
lift-slides 已有 `expected_mtime`(F-53)、已有 data-page→key 映射(F-40)——**工具修好了,
deck 还烂着**。编号 **F-67 起**。

## F-67 · 缺"治存量" turnkey:`heal-lifted.py`(把 F-51「本 deck 止血」工具化)【P0,本轮最大时间黑洞的根因】
- **现象**:forward 修复对已 lift 坏掉的页零作用。本轮手工补了:① 冰山 `.hero-pct` 死规则
  (`[data-page="17"] /*注释*/ .slide .hero-pct{font:800 100px}` 被旧 scoper 啃成 `.slide[k] .slide .hero-pct`
  双层后代,谁都不匹配 → 100px 退 16px)② `.above/.below` 镜像定位死规则 ③ pg40/41 `.pic-cell/.demo-cell/.ph-input`
  display 死规则 ④ pg42 `.loop-row{display:grid}` 死规则(同样夹注释,且前面连 `.slide` 都没有,首轮扫漏)。
  每条都是"剥注释→正确 scope→追加盖过坏版"——**正是修好的 `iter_css_rules` 该一次性做的事,却靠人逐条搓**。
- **实测残留**:本 deck 现仍有 **129 处 `-frame.is-current` 死动画选择器**(F-51(a),pg26-46),
  "止血串替换"从未对本 deck 跑过 → 18 个 lift 页进场动画仍死(pg40/41 手机后几条消息可能仍隐身)。
  - **【2026-06-01 校正 · 对抗复核】**:上述「129 处 `-frame.is-current` 死动画选择器」实测**不准确**——复核 live index.html:`(?<![\w-])-frame\.is-current` 啃坏形态 = **0 处**,合法 `.slide-frame.is-current` = **129 处**。即 F-51(a) 的「啃坏死动画」**已清零**(上一轮串替换已把 `] -frame` 修成合法形态);heal 在本 deck 跑出 **0 个 `-frame` fix** 也印证此点。 真正的残留是 **1305 处夹注释规则**(`] /*…*/ selector`)。
  - **【2026-06-01 落地 + 推翻核心安全前提】**:`heal-lifted.py` 已实现(`deck-json/heal-lifted.py`,13380B,主区/skill 逐字节一致,幂等已验)、已对本受害 deck 试跑并**已回滚**。但对抗复核**证伪了工具的核心前提**「夹注释死规则 = 非法 / 浏览器丢弃 / 零像素」:CSS 注释在选择器间被当作**空白(后代组合子)**,`.slide[k] /*c*/ .stage{}` ≡ 合法的 `.slide[k] .stage{}`,浏览器**照样应用**(已用 Playwright 实测 `color/width/height` 全生效)。因此 1305 处里**混有生效的框架副本规则**;heal 全量丢弃后,本 deck slide43 `back-four-extraction-measures` 的 `.knife-card` 行高/`.grid` 布局塌陷——实测两行卡片由「18px 间隙」变「重叠 62px」、grid 底由 952px 溢到 1012px;headless `check-only.py --visual` 上 R-OVERLAP 0→4、R-VIS-CARD-OVERFLOW 3→5(slide43/44/46 新增)。(注:本审计 F-67 现象段自己记录的「冰山 `.hero-pct` 100px→16px」「pg42 `.loop-row` grid→block」正是夹注释规则**生效后被啃坏才失效**的反例,与「零像素」前提自相矛盾。其中 `.slide[k] /*c*/ .slide .x` 这类**双 `.slide` 后代**才是真死;`.slide[k] /*c*/ .stage` 这类是**真活**——工具不区分二者是 bug 根因。)
  - **结论**:工具可保留为骨架,但**严禁按现状批量治存量**;落地前必须补 **F-68 式写回闸门**(写回前 headless render+geometry-validate,✗ 不得增加,否则自动放弃并保留原文件),或改为只删「双 `.slide`/双层后代」等**实测零匹配**的规则、对其余 keep-on-doubt。在补这道闸门前,F-67 标记为**已实现但未通过对抗验收(blocked)**。
- **修法**:`heal-lifted.py <deck.json>`:对 `layout:raw` 且 lifted 的页,用 `_css_utils.iter_css_rules`
  重解析内联 `<style>`,① 丢弃/修正注释啃坏的死规则 ② `-frame.is-current`→`.slide-frame.is-current` 串替换
  ③ 剥框架副本(接 F-50)④ 选择器合法性断言。**幂等**,可对任何旧 lift deck 重跑。这是把本轮 ~50% 诊断时间
  压成一条命令的关键。
- **优先级**:**P0**。F-50/51/52 是"不再产新坏页",F-67 是"修好已坏页",二者缺一不可。

## F-68 · 静态/视觉闸抓不到"规则死了 → 元素退默认值"(扩 F-57 到非动画)【P1】
- **现象**:冰山 `.hero-pct` 从 100px 死成 16px——但 **16 是合规档,R20 全绿**;`.loop-row` 从 grid 死成 block——
  **无任何闸报警**。两处都是"声明在源里、运行时规则死掉、元素静默退默认",肉眼/用户才发现。F-57(R-VIS-DEAD-ANIM)
  只覆盖 `animation:`。
- **修法**:扩成 **R-VIS-DEAD-RULE**:凡内联 CSS 里声明了 `position:absolute|fixed` / `display:grid|flex` /
  `font:`含≥48px 的规则,其选择器在运行时 `querySelectorAll(sel).length===0`(或解析非法)即报。
  几何兜底可选:hero 区文本(源标 ≥48/≥80)实测渲染 ≤24px → 报"hero 文字疑似退默认"。
- **优先级**:**P1**(把本轮两类肉眼 bug 固化成回归护栏)。

## F-69 · heal/re-extract 的"变暗陷阱" + 外科式纪律【P1,写进 F-67 工具纪律】
- **现象**:修 pg42 时先试"整页全量重抽源 CSS",结果把源的暗背景/叠层通用 `.slide` 规则一起 scope 进来 →
  整页发黑、文字不可见(与早先 clean-regen 变暗同源)。回退改成**只补 dp-specific bespoke 规则**(loop-row/step-node/mock-*),
  颜色才保住。
- **修法**:`heal-lifted.py` 默认**只重建 `[data-page=N]`/key-scoped 的 bespoke 规则**,
  **绝不**把通用 `.slide`/背景/叠层规则重新 scope 进单页(那些靠目标 deck 框架兜底)。补充用**追加+同特异性**
  盖过坏版,不用 prepend(prepend 会被坏的 lift 规则后置覆盖)。
- **优先级**:**P1**(F-67 不带这条纪律就会制造 pg42 那种变黑)。

## F-70 · lift 不记 provenance,heal/re-lift 无法确定性回源【P1】
- **现象**:修 pg42 要找它的真源页,但内嵌 CSS 标 `[data-page="21"]` 而源 deck 视觉序≠data-page序,
  首次按 hash 截图截到的是另一张(3层架构页);最后靠 class 签名(loop-row/store-card/is-airport)
  才反查到真源("店长排班·食材损耗"闭环)。
- **修法**:lift 时给每页写 `fs-lift-origin: {src_deck, data_page, src_key}`(deck.json 字段或 slide 注释),
  heal/re-lift/对账时直接回源,不靠反向猜。
- **优先级**:**P1**。

## F-71 · `snap_fonts` 只认 `font-size:`,漏 `font:` 简写【P2,并入 F-42 reconcile】
- **现象**:case-luolai `.kpi-strip-feihe .v{font:800 52px/1 …}` 的 52px **没被 snap**(本轮原型 `snap_fonts`
  正则只匹配 `font-size:(\d+)px`),触发 R20,手加 `/* allow:typescale */` 才过。
- **修法**:F-42 `reconcile-lifted.py` 的 snap 必须同时解析 `font:` 简写里的 px(取 `font:` 值中第一个 `\d+px`),
  与 `font-size:` 一并 snap;hero≥80 / mockup<16 例外照旧。
- **优先级**:**P2**(F-42 落地时一并)。

## F-72 · 没有 heal 工具 → 只能手补 → CSS 越补越肿(反证 F-67)【记账】
- **现象**:本轮手工补丁后,back-* 页内联 `<style>` 从原 ~88KB 涨到 **112–176KB/页**(pg42 闭环 176KB)。
  每次"追加一块止血 style"都在原框架副本上再叠。**手补是 bloat 放大器**,与 F-50(剥副本)反向。
- **结论**:这不是独立工单,是 F-67 必要性的量化证据——存量修复必须工具化+幂等(每次重跑产出收敛),
  而非人肉追加 style(每次只增不减)。
- **优先级**:并入 **F-67**。

---

## 第四批一句话
**audit 把"不再产新坏页"的工具修复(F-40/50/51/52/53)做对了且大部分已落地;但"修好已坏的存量 deck"
是完整缺失的一环(F-67),本轮整轮手工止血就是这个洞的代价。次要新洞:死规则无闸(F-68)、heal 变暗纪律(F-69)、
缺回源 provenance(F-70)、snap 漏简写(F-71)。**


---

# 第五批 · F-50 半自动去重实战 + 关键方法论修正 (2026-06-01 晚)

来源:执行 F-50(减 lift 页框架副本冗余),workflow 半自动 + 每步 headless 几何门禁 + 对抗复核。

## F-50-c2 · clean-lifted-css.py 清损坏 keyframe 【已落地·可保留】
- **现象**:11 个 lift 页的 @keyframes 被旧 scoper 注入 slide-key → `.slide[K] to {…}` 非法帧选择器(keyframe 帧只能 from/to/N%),浏览器静默丢帧。`iter_css_rules`/heal-lifted 都够不着(它们把 @keyframes 当 opaque @-rule 整块跳过)。
- **修法**:新工具 `deck-json/clean-lifted-css.py` —— comment-aware 扫 @keyframes 块内部,剥掉注入的 slide-key 前缀复原裸帧。repair 非 drop(kf 定义 11 次、引用 0 次,render-neutral)。F-53 锁/.bak/幂等齐。
- **验证**:对抗复核独立复现全过——几何零新增、**真实导航截图 0.000% 像素差**、幂等 no-op、锁 exit 3。**可合入。** 减 396B(本身小,价值=为 hoist 扫障)。

## F-50-(a)/(c1) · tree-shake 去重 【打回·不可按现状用】
- **(a) deck 级 hoist 落点不通**(诊断正确,合理超范围):render-deck 只读 deck_meta 4 字段、deck-schema additionalProperties:false、sync-index 只 round-trip .slide 内层 → 无 deck 级共享 CSS 落点。真 (a) 是跨 schema+shell+sync 的 render-deck 能力缺口。
- **(c1) 按页 tree-shake 减重达标但产物会塌**:treeshake-faithful-css.py 减 1.13MB(−61%),但**对抗复核用真实键盘导航截图证伪了"视觉零改变"**——11/11 lift 页字号静默缩成 16px(slide-42 实测 .body-note 22→16、.hero-name 38→16、6.9% 像素塌陷)。
- **根因(微妙)**:删"无害死规则"时,删掉了夹在**未清的 mangled 注释残渣选择器**(deck 现存 869 条 `.slide[K] /*`)之间的间隔规则 → 改变浏览器 CSS **错误恢复边界** → 把本应保留的有效正文/标题规则一并吞掉。根因不在 treeshake 删除决策,在前置 heal 没把 869 条非法注释残渣清干净。
- **续做条件**:① 前置必须先彻底清 mangled 注释残渣(扩 heal-lifted);② treeshake 增「浏览器解析后置校验」——比对"工具保留数 vs 浏览器实际解析数",有 gap=触发 parser-swallow→拒写。工具存档 `_parked-tools/treeshake-faithful-css.py.PARKED`,修好前不进生产路径。

## ⚠️ 方法论修正(写给所有"改 CSS 后验视觉零回归"的工单)
**冻结动画截图法(强制 is-current 但不真绘制目标页)会产生假 0** —— 两份 deck 得到相同错误帧、假装零差异(本轮 build agent 即栽此,报告 0.000% 实为假阴性)。**正解:真实键盘导航到目标页 + 动画 settle 后截图,再 diff**;且几何门禁必须覆盖 BODY-FLOOR(字号塌陷),只看 CARD-OVERFLOW/OVERLAP/OVERFLOW 会漏掉"规则死→字号退默认"那类。

## F-50 整体进度
c2 清污染 ✅可信可合;tree-shake 减重达标但渲染回归→**打回**;deck 级 hoist 未启动(render-deck 能力缺口)。**真正减 1.13MB 的能力存在,但需先补齐 heal 残渣清理 + parser-swallow 校验才安全。**

---

# 第六批 · "lift 一页进无-deck.json 老 deck"为何慢 + 加速 (2026-06-02)

来源:用户把 kangshifu #16 lift 进 everbright(老式无 deck.json 老 deck)末尾,主对话手搓 ~15 次工具调用 + 1 次假设错误重跑才完成;用户问"除 bug 外哪里能加速"。后台分析 agent 读 lift-slides/deck-cli/import-html-slide/locate-slide/validate/render-deck 后定根因。

**根因占比**:工具缺口 ~50%(没有一条命令把源 index.html #N → lift 进**无 deck.json** 的 legacy index.html;现成两条路 `deck-cli paste`/`lift-slides`→deck.json **都假设目标有 deck.json**;splice 能力其实埋在 `import-html-slide.py` Mode B 没接上)+ 过度探测 ~30%(自包含/CSS位置/资产/冲突全靠人肉 grep,工具内部函数早会算)+ 假设错误重跑 ~15%(raw data.html=内层这条契约只在代码注释、SKILL.md 没写)+ 输出截断 ~5%(**非 locale**,是超长单行/整页倒 stdout 触发 harness 截断)。

## F-80 · `lift-slides.py --to-html DST/index.html`:lift 进无-deck.json 老 deck 【已落地·parity 测过】
- **现状痛点**:目标是老式 index.html 即源 deck 时,无任何 turnkey 命令,只能手搓「抽 frame→shake→拷资产→包 frame→续号→div 平衡 splice→备份→validate」8 步。
- **修法**:`lift-slides.py` 加 `--to-html`:DST 以 `.html` 结尾即走此路(`.json` 仍走 deck.json 路径)。复用 `extract_one`(抽)+ `transform`(剥 data-text-id/拷资产/改写 shared 路径,与 deck.json 路径同一套)+ 新 `_wrap_frame`(内层→完整 `.slide-frame>.slide`,data-layout=源 layout,**承 F-82**)+ 新 `_deck_close_offset`/`_splice_into_html`(div 平衡定位 `.deck` 闭合前,本会话手工验证过的逻辑固化)+ 自动 `.bak` + `_validate_after_lift`(只判本页:R-DOM 干净 + 无 finding 提到新 key,承 F-63/F-68)。续号 screen_label 用目标真实帧号。
- **复用率**:6 环节 5 个现成函数,新代码仅 wrap/splice/路由。
- **验证**:用手工 lift 前的 51 帧备份建 scratch,`--to-html` 一条命令 → 52 帧、R-DOM 干净、0 新 finding、截图与手工 8 步**渲染完全一致**(avatar skill-relative 路径改写正常加载)。**8 步 → 1 步。**

## F-81 · `lift-slides.py --preview SRC #N|--key K [--against DST]`:一条命令出全部 lift 判断 【已落地】
- **现状痛点**:探测 5-6 次人肉 grep(自包含/CSS在哪/@keyframes闭包/资产存不存在/撞key),还是截断重灾区。
- **修法**:只读 `--preview`,出紧凑 JSON:`{self_contained, css_location(inline/head/both), head_scoped_rules_for_this_key, inline_keyframes, referenced_anim_names, keyframes_only_in_head_need_shake, asset_refs[{url,kind,exists}], recommend_shake, against:{key_collision,target_frames,assets_present}}`。复用 build_manifest/extract_one/scan_asset_refs/_source_author_css/extract_head_slide_rules/_extract_keyframes/_referenced_anim_names。
- **关键修正**:`_source_author_css()` 返回**所有**非框架 `<style>`(含 frame 内联块),直接喂会把页**自己的内联 CSS** 误判成 head CSS → 假报 not-self-contained。修:扫"外部 head CSS"时**排除本 frame 自身的行**(`non_frame = 前半 + 后半`)。修后 kangshifu#16 正确报 `self_contained:true / recommend_shake:false`。
- **5 步探测 → 1 步**(且全是截断高风险的 grep)。

## F-82 · 契约固化:raw 页 `data.html` = 内层,`.slide` 包裹由 render 加 【已落地】
- **现状痛点**:这条只在 `sync-index-to-deck.py`/`render-deck.py`/`import-html-slide` 代码注释里,SKILL.md 主体没写 → 本轮"以为能从 data.html 重建 frame"作废重来一轮。
- **修法**:SKILL.md LIFTING 节加 🔒 铁律(要完整可渲染 frame 必须从渲染后 index.html 抽,绝不从 data.html 拼);`--to-html` 已按此实现(从 index.html 抽 + `_wrap_frame` 重包)。

## F-83 · 探测/lift 命令不倒正文、默认 `--json` 治截断 【部分·候选】
- **实测**:截断**与 locale 无关**(LANG/PYTHONUTF8 正常、CJK print 正常);是**超长单行 / 整页 HTML 倒 stdout** 触发 harness 字节上限。本会话多次"只打第一行就截断、命令执行也被打断、scratch 没建成"即此。
- **已做**:`--preview` 出紧凑 JSON;`--to-html` 输出按页一行、不倒正文。
- **待做**:SKILL.md 纪律「lift 探测走专用子命令出结论,看正文用 Read 读文件区间,绝不 `cat`/`grep` 整页到 stdout」;lift 大输出建议重定向到文件再 tail。

## F-84 · `--to-html` 内建 lift-DONE 闭环 【部分落地】
- **已做**:`--to-html` 落地后原子跑 `validate.py`(吃 assembled HTML,无需 deck.json)+ 抽 R-DOM/新 key finding 判定(承 F-63/F-68)。
- **待做**:可选 `--shot KEY` 落地后单页截图核验(走 `validate.py --slide`/已修好的 `deck-log snapshot --slide`,绕开原 deck-log out/output bug——该 bug 本会话已修)。

## F-85 · `import-html-slide.py` Mode B 被 `lift-slides --to-html` 取代 【并入 F-80】
- Mode B 的 `insert_into_html`(splice 进无-deck.json index.html)能力是 F-80 的近亲,但只吃预抽 fragment、交互式、不 shake、不拷资产、不 validate。F-80 已用自带 div-平衡 splice 覆盖全链,**不跨模块复用 Mode B**(避免 assets/↔deck-json/ 导入耦合)。建议把 Mode B 标注"legacy,新流程用 `lift-slides --to-html`"。

## 第六批一句话
**"lift 一页进无-deck.json 老 deck"过去没有 turnkey 命令是这次慢的主因;F-80(`--to-html`)+ F-81(`--preview`)+ F-82(契约固化)已落地并 parity 测过,把 ~15 次调用压到 2-3 次。截断与 locale 无关,是整页倒 stdout 触发 harness 截断(F-83 纪律待固化)。**

