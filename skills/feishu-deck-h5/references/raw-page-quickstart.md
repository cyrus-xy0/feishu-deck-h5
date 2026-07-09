# raw-page-quickstart — feishu-deck-h5 reference

> 何时读:手写一张 bespoke `layout:"raw"` 页(自定义版式 / SVG / 动效),或往现有
> deck **插一页**。目的:把每次都要重新考古的**固定契约**一次性钉死——这些常量
> 永不变,别再 grep CSS / 派 Explore / 逐个 `--help` 重新发现。recon 应从 ~9min → ~3min
> (2026-06-20 齐鲁「那一跃」页复盘:一张 bespoke 页烧了 35min,其中 ~6min 是重新
> 考古这些固定事实,~6min 是焦点元素试探性返工——两者都该被本文消灭)。
> (2026-06-21 齐鲁 CAPA demo 页 21min 复盘再补两条:**deck.json slide 对象形状**钉进
> 「固定常量」省掉手猜字段名的空跑、**隔离 / worktree session 写 runs/ 产物**的 tmp+cp 配方
> 省掉 worktree 摩擦——见下对应小节。)

## 固定常量(背下来,别再查)

- **画布 1920×1080** 绝对定位(`.slide-frame .slide{ width:1920px; height:1080px }`;
  JS 用 `--fs-scale` 整体缩放,内部坐标恒为 1920 canvas px)。
- **字阶只准 {16, 24, 28, 48}**。正文 floor **24**;chrome(eyebrow / tag / pill /
  页码 / 轴标 / 短标签 ≤7 字)floor **16**;hero 数字要越界,在该 CSS 规则里写
  `/* allow:typescale */`,或元素加 `data-allow-typescale`。
- 字体:`var(--fs-font-cjk)`(方正兰亭黑)/ `var(--fs-font-latin)`(Inter)。
  其它可用:`--fs-blue:#3C7FFF`、`--fs-accent`、`--fs-ease-out:cubic-bezier(.16,1,.3,1)`、
  `--fs-dur-enter:.6s`、`--fs-stagger:90ms`。
- content 页深色底约定:`#050a17 url("assets/lark-content-bg.jpg") center/cover no-repeat`。
- **deck.json slide 对象形状(读一页前先背,别手写 extractor)**:`slides[]` 每项 =
  `{key, layout, screen_label, data:{html, title?}, custom_css, accent?, decor?, lifted?, allow?}`。
  **html 在 `data.html`、bespoke CSS 在 `custom_css`、可见标题在 html 的 `.title-zh` 里**
  (`data.title` 只是元数据、raw 页常空)。要看某页真内容 →
  `deck-cli.py <deck.json> get-page <key|#N> [--html|--css|--title]`(按 key 或 1-based 页码寻址;
  `--html` 吐**原始未转义**片段、可 `> frag.html`;无 flag 给摘要+全文)。**别再 `json.load` 手猜
  字段名**——那是「别用临时脚本碰 deck.json」反模式的读侧孪生(`show` 吐的是 JSON-escaped 整对象,
  读 html 用 `get-page --html`)。
- **起一个新 deck 别手搓骨架**:`deck-cli.py <新>/deck.json new-deck --title T --author A --date D
  [--cover-title "一行<br>二行"]` → 吐合法 deck.json(meta + cover)。**别读 1200 行 schema、别拼骨架 + cp**;
  封面标题里字面 `<br>` 会自动转成换行(封面是转义字段,字面 `<br>` 触发 R-ESC-HTML)。仪式页 data 字段速查见下文同名段。
- **raw 页 `.header` 有隐藏契约(别撞)**:框架给它 master 定位(`top:61 left:73`),并把**首个 `<div>` 子节点**
  设成 `flex-direction:column-reverse`(eyebrow-wrapper)、自带 `.eyebrow` 类。**要 kicker / eyebrow 在标题上方:
  别自创类当首子节点**(会继承 column-reverse → 内容被水平居中,真踩过)——用框架结构
  `<div><span class="eyebrow">…</span><h2 class="title-zh">…</h2></div>`,或显式覆盖
  `.slide[data-slide-key=K] .header>div:first-child{flex-direction:row}`。
- **新手写 raw 主容器别叫 `.stage`**:`.slide[data-layout="raw"] > .stage` 继承框架 body-zone
  定位(`top:band+56; left/right:96; bottom:56; flex-column center`)。只有想要这套定位时才用
  `.stage` 并加 `data-allow-reserved-class`;否则用带语义前缀的类名,如 `.ai-leaps-stage` /
  `.risk-map-canvas`。`deck-cli set-page` 会对 `.stage` 等 body-zone 保留类名报
  `L-RAW-RESERVED-CLASS`(lifted 页降级为 warn)。

## raw 页 6 条铁律

1. **raw 页标题:用框架 `.header` 即得 master 定位,但首子节点有隐藏契约——别撞它。**
   `<div class="header">` 自动拿到 master 坐标(`top:61 left:73 right:320`);其内 `.title-zh`/`h2`
   自动 `48px #fff 600`、`.page-sub` 自动 `28px #fff`(都不必自己写)。**坑:框架把 `.header` 的
   **首个 `<div>` 子节点**设成 `flex-direction:column-reverse`(eyebrow-wrapper:DOM 里 eyebrow 在前、
   视觉落到标题下),且有现成 `.eyebrow` 类(`--fs-accent` 橙、letter-spacing)。** 想要 kicker/eyebrow
   在标题**上方**:**别自创类当首子节点**(会继承 column-reverse → 内容被水平居中,这是真踩过的坑)——
   要么用框架结构 `<div><span class="eyebrow">…</span><h2 class="title-zh">…</h2></div>`(eyebrow 落标题下),
   要么显式覆盖 `.slide[data-slide-key=K] .header>div:first-child{flex-direction:row}` 再自定 kicker 类。
   自绘标题后 R-VIS-TITLE-POSITION(只看 `.header` bbox)自动跳过。
2. **一切 CSS scope 到 `.slide[data-slide-key="K"] …`**,别裸选择器(keyframe 是全局的,
   选择器不是——裸选择器会跨页泄漏)。
3. **自定义 raw 容器用语义前缀,别借框架 body-zone 类名当 hook**。坏:`<div class="stage">` +
   `.stage{top:258px}`(会撞 raw body-zone 定位 / 审计语义);好:`<div class="ai-leaps-stage">` +
   `.slide[data-slide-key="K"] .ai-leaps-stage{…}`。若你确实要框架 `.stage` 语义,在片段里加
   `data-allow-reserved-class` 留痕。
4. **焦点闸 R-FOCAL**:≥3 个元素并列共享**全页最大字号**才告警。把 48px 只给该给的
   (如左右双标题 = 2 个,安全),其余 ≤28。真要 3+,该页 slide JSON 加
   `"allow":["no-focal"]`——**真实字段,deck 里实证可用**;无配图同理 `"allow":["no-imagery"]`。
5. **SVG `<text>` 也有字号 floor = 18px**(8+ 字 R-VIS-SVG-TEXT-FLOOR / 1–7 字短标签
   R-VIS-SHORT-LABEL-FLOOR,都按【实效渲染】px 量、都是 **18**)→ 节点/标签宁可用 HTML
   `<span>` 绝对定位**覆在** SVG 上,字号好控、渲染更清晰。
6. **动效只写 `slide.custom_css`**。deck.json 无 JS 槽,re-render 会抹掉任何
   `<script>` / head `<style>`;GSAP 等只在 deck 级 `motion_engine:"gsap"` opt-in 时才有
   (见 `motion-system.md` §8),per-page 一律 CSS-only。

## 动效一行模板(bespoke 入场)

```css
@media (prefers-reduced-motion: no-preference){
  .slide-frame.is-current .slide[data-slide-key="K"] <hook>{
    animation: qK-rise .6s cubic-bezier(.16,1,.3,1) both; animation-delay: calc(.5s + var(--i,0)*90ms);
  }
}
@keyframes qK-rise{ from{opacity:0; transform:translateY(14px)} to{opacity:1; transform:none} }
```

- 触发恒为 `.slide-frame.is-current`;keyframe 全局 → 名字加唯一前缀 `q<slug>-`。
- **静止态必须可见**:resting CSS(无 is-current 时)= 最终可见状态;动画只用 `both` 的
  backwards-fill 在 is-current 期间补起始帧。**绝不**把 resting 设 `opacity:0`——动效没跑
  就丢内容。
- SVG 连线 draw-in:`<path pathLength="1">` + resting `stroke-dashoffset:0`,keyframe
  `from{stroke-dashoffset:1}`。实心形状(箭头/节点)用 scale+opacity pop,**不用** dash
  (dash 只作用于 stroke,对 fill 无效);scale 要先 `transform-box:fill-box; transform-origin:center`。
- **进入自动重播,别手写**:翻进某页时框架自动重启该页的有限 CSS 动画(排除框架 `fs-*` 与 infinite 循环)、
  `<video>` 与内嵌 `<iframe>`(整体重载)——is-current 包裹仍推荐(隐藏页不空跑),但"重播"不依赖它。
  首屏落地页不重播。可交互 / 重型 embed 用 `data-no-restart` 关掉。详见 `motion-system.md` §2b。

## 起一个新 deck(别读 schema、别手搓骨架)

```bash
python3 deck-json/deck-cli.py <new-dir>/deck.json new-deck \
  --title "标题" --author "杰森" --date "2026.06.23" \
  [--cover-title "第一行<br>第二行"] [--customer-slug slug] [--presentation-date 2026-06-23]
```

吐一个**合法 deck.json**(deck meta + 一张 cover)。**别再读 1200 行 schema、别手搓骨架 + cp。**
封面标题里写 `<br>` 会被自动转成换行(封面是转义字段,字面 `<br>` 会触发 R-ESC-HTML)。
之后用 `insert <pos> raw <key>` + `set-page` 加正文页。

### schema 布局 data 字段速查(免读 schema)

**raw-unless-ceremonial(F-305):正文页一律 `layout:"raw"`,只有仪式页用 schema 布局。** 仪式页字段:

| layout | data 必备字段 |
|---|---|
| `cover` | `title` · `author` · `date`(`title` 多行用换行,别字面 `<br>`) |
| `section` | `chapter_num`(如 `"02."` 带句点) · `title`(+ `lede?` / `pills?` / `parent_label?`) |
| `agenda` | `items[]`(每项 `title_zh`;+ `title?` / `active?`) |
| `quote` | `quote{lead,accent,tail}` · `attribution`(+ `title?`) |
| `end` | 无必备(`data` 可省) |
| `raw` | `html`(≥10 字符;bespoke CSS 放 `custom_css`,**不在** `data` 里) |

要更细的字段去 `deck-json/deck-schema.json` 的 `data_<layout>` 段——**grep 取单段,别整读**
(`grep -n '"data_cover"' deck-schema.json` 再定向读那 ~12 行)。

## 手写 raw 页前 · 5 行设计压缩

动手写 HTML 前先在脑内或回复里钉 5 行,别边 render 边找主线:

- Q0 角色:这页是结论页 / 结构总览 / 证据页 / 转场页?
- Q1 记忆点:观众只记住哪一句?
- Q2 信息块:最多 3-4 块;每块一句短文案。
- Q3 视觉骨架:轴 / 阶梯 / 矩阵 / 对比 / 路径,选一个。
- Q4 第一版焦点:最大的字、最亮的线、最实的形第一版就做足。

### 密集业务页默认骨架

- **默认固定几何,少动画**:账单、对比、组织流程、三栏观点这类高密度业务页,第一版优先用
  `position:absolute` 的固定区域 / 固定列宽 / 固定字号,不要一上来写复杂 grid + 延迟动效。
  动效只在页面静态成立后再加;用户没明确要高级动效时,宁可无 bespoke animation。
- **一页一个焦点**:金额页焦点=合计数字;对比页焦点=中轴 / 箭头 / 天平;章节页焦点=章节号 +
  标题。第一版把焦点做足,其余信息压成短句。
- **preview 看静态终态**:若写了 CSS animation,resting state 必须可见;密集页的验证截图应能在
  无动画 / 动画未跑完时也读完正文。

## 插一页 / 改一页 · 预览优先配方

```bash
# 0) 插章节页时用原子快路径:一次写完 chapter/title/label,别 insert section 后再 set 三轮
python3 deck-json/deck-cli.py --yes <deck.json> add-section <N> <KEY> --chapter 01 --title "AI 的能力如何了？" --label 03

# 1) 插脚手架。insert 自己 range-check 位置 + 拒撞名 key → 不必另跑 deck-map "确认插入点"
python3 deck-json/deck-cli.py --yes <deck.json> insert <N> raw <KEY>      # 新页成第 N 页;raw 不需 variant
# 2) 灌 html/css/title。W4 pre-write lint 会提醒某 16px 选择器上是否压了 ≥8 字正文
python3 deck-json/deck-cli.py --yes <deck.json> set-page <KEY> --html f.html --css f.css --title "…"
# 3) 视觉内循环:单页 1:1 快照 + 静态 gate,先用它修布局 / 换行 / 间距
python3 deck-json/preview-slide.py <deck.json> --key <KEY>
# 4) scoped 真闸:只校验 + making-of 只刷这一页(改一页别全 deck 渲)
python3 deck-json/render-deck.py <deck.json> <out-dir> --scope <N>
# 5) 自己审稿截图(present 模式 1920×1080 design clip)
python3 deck-json/shoot.py <index.html> --pages <N> --out <dir>
```

- 上面 = **html 与 css 分开写**时的路径。若你把整页写成**一个含 `<style>` 的 `.html`
  片段**,改用一步式 `python3 deck-json/import-html-slide.py <deck.json> f.html --index <N>`
  (wrap 成 raw + 校验 + 插入 + 拷资产 + 折 CSS 进 custom_css + re-render;见 editor subskill)。
  二者等价,别两套都跑。
- `--yes` / `--force` 是**全局 flag,放在 `<deck.json>` 之前**(`deck-cli.py --yes deck.json insert …`)。
- `#N`(URL hash)= frame index = `slides[N-1]`。用户指 `#10` 之后加一页 → `insert 11`。
  **别为"确认插入点"反复跑 deck-map**;热 deck 防并发位移最多查 1 次。
- set-page / render 自带乐观锁 + `.bak-pre-*` 备份;并发 session 改了同一 deck.json 它会拒写,
  按提示重读即可,不要 `--force` 绕过。`deck-cli` 写命令还会先拿 `.deck.json.lock`,
  覆盖 read→mutate→write 全事务;别用临时脚本绕过这个单写者通道。
- **要照着某页改 / 学它约定**:先 `get-page <key|#N>` 看它的 html+css(别开 ad-hoc extractor),
  再 set-page 写回。
- **对话 / agent demo 页别手搓聊天 UI**:`cp deck-json/templates/prototypes/feishu-chat-demo.html`
  到 `runs/<deck>/prototypes/<名>/index.html` 填内容,再按 iframe + screen-frame 嵌进 raw 页
  (多段对话 = 一个 iframe 内 N 列 `.thread`;契约见脚手架头注 + `prototype-embed.md`)。
- **隔离 / worktree session 里编辑 `runs/` 产物**:`runs/` 是 gitignore 的用户产物、只活在主
  checkout——被隔离进 worktree 时,**Write/Edit 工具会拒写共享 checkout 路径**。对策:**原型 /
  资产 / 片段文件**写到 job tmp(`$CLAUDE_JOB_DIR/tmp` 或 `$TMPDIR`)再 `cp` 进 `runs/.../`;
  **deck.json 改动**走 deck-cli(set-page / insert / render)——它们经 Bash 子进程落盘,不受隔离
  影响。别去研究 worktree、别 ExitWorktree(编辑 deck 产物本就不是「代码改动」,无需隔离)。

## 纯结构改动(move-key / reorder / hide / unhide / delete)= 一次 `--quick` 渲染,别套 `--scope … --shoot`

移动 / 隐藏 / 删一页 = **帧序变,没有任何一页的版式变** → 别套上面「改一页」的 scoped 配方
(2026-06-25 移一页复盘:纯 reorder 却跑了全量渲染、又多补一轮 scoped 截图,白慢一倍)。

```bash
# 1) 改结构:move-key 自带 .bak + range-check(reorder <旧位> <新位> 同理)
python3 deck-json/deck-cli.py --yes <deck.json> move-key <KEY> <目标位>
# 2) 验落点:读 deck.json,不渲(别为"确认顺序"反复渲)
python3 deck-json/deck-map.py <deck.json>
# 3) 一次过:帧序变→必须重渲 index.html,但用 --quick(~15s,别全量 ~2-3min)
python3 deck-json/render-deck.py <deck.json> . --renumber --quick
```

- **`--quick`** = 跳过 deck-log 整 deck 截图快照 + content-fit 拒绝,**保留** JSON schema + HTML 静态闸。
  纯结构改动无版式变化、快照无新信息 → 跳;把 ~2-3min 砍到 ~15s。
- **`--renumber`** = 把每页 `screen_label` 前导数字重写成真实帧序(reorder 后标签必漂;纯语义标签的 deck 才省)。
- **别 `--scope N --shoot`**:reorder 后 N 之后的帧全漂,`--scope`(一次只动一帧的语义)不成立;且内容没变,
  截图纯属多跑一轮。结构改动的正确验证 = `deck-map` 读落点 +(想看图就)瞄移动页那 1 张,**不单开渲染轮**。

## 跨 deck 拎一页(LIFT+SWAP — 默认乐观:paste 先做,render 验,坏了再诊断)

- **工具路径钉死**:repo 根只有 `runs/` + `skills/`;所有 deck-json 工具在
  **`skills/feishu-deck-h5/deck-json/`**(`.claude/skills/feishu-deck-h5` 是指向它的
  symlink)。在 repo 根 / runs 下操作时前缀这个路径,**别 find / ls 重新找**。
- **默认配方 = ~5 步封顶(别 12 步;2026-06-23 lift+改标题复盘:多花的全是预先考古 + 改标题四步)**:
  1. `deck-map.py <源deck.json> --index N` 拿源页 key + 顺手确认目标插入位。
  2. `deck-cli.py <目标deck.json> --yes paste --from <源deck.json> --key <K> [位置]`
     —— **加在末页之后 = 省略位置(默认 append),别为「插哪」跑 `paste --help`**;`--new-key` 改名。
     paste **自己**会 rekey 内嵌 scoped CSS + 拷 `url()`/`<img>` 资产 + 盖 `lifted`,并**打印回执**
     (`input/ copied: [...]`、`stripped N data-text-id`)——信回执,**别预先 archaeology**。
  3. 改标题 / 文案 = **一条 `bash -c`,别 get→Read→Edit→set 四步**:`get-page <K> --html > f`
     → 就地改 `f`(只替换 unique 串才安全;`f` 是抽出来的临时片段、**不是** deck.json)→
     `set slides.<N-1>.data.html --from-file f`,**顺手 `set slides.<N-1>.screen_label <新> --str` 一起设**
     (别为 screen_label 单开一轮 render)。
  4. `render-deck.py <目标deck.json> . --scope <新页码> --shoot` → 读 `last-render.log` 首行。
  5. 瞄那张 `.shoot-pN.png`(交付前看图是硬底线,**这步不省**)。
  起一个**全新** deck 复用某页 → `lift-to-new-deck.py <源> <页> <新dir>`(已内置漂移守卫)。
- **换掉某页 body 但保留它标题(「把源#X lift 到目标#Y,保持 Y 标题换内容」)= 一条命令,别手搓
  paste→get-page→换标题→set 六步(F-378)**:
  `lift-slides.py <源 index.html> --key <K> <目标deck.json> <目标out> --shake --replace <Y> --keep-title`
  —— **就地覆盖目标第 Y 页**(1-based = 页码 #Y)的 body,**保留该页 key + screen_label + 可见标题**;
  自动把源页 CSS rescope 到目标页 key、拷资产(含 `[data-page=N]` 形态的背景图,F-376)、剥 data-text-id、
  剪掉 `--shake` 多带的死框架规则(F-377)，并把 lifted raw 页里的作者 `<style>` 自动搬进
  `custom_css`、剥 `<script>`/`on*=`，避免源页宽选择器污染目标 deck。源是**已发布的 rendered index.html**(feishusolution 包等)时
  也走这条——`lift-slides` 专治 head-CSS 漂移。只能 lift **一页**(--replace 覆盖一个槽);
  完了 `render-deck.py <目标deck.json> <out> --scope Y --shoot` 看图即可。
  源帧号(#Y)= `lift-slides.py <源> --index` 列表里的 1-based 行号。
- **⚠️ 漂移源陷阱 = 失败诊断,不是先验 gate(别因为怕它就预先三连考古)**:老 deck 某页
  `custom_css` 为空、CSS 全留在 **rendered index.html 的 `<head>`**(老锚点 `.slide[data-page="NN"]`)、
  `data-accent`/`data-decor` 只在渲染出的 `<div class="slide">` 上时,paste/lift 只搬空 custom_css →
  无样式 + 缺图 + 丢 accent/decor 的坏页。**但这在第 4 步截图里一眼看穿**(本该有样式的页变白板 /
  图没了 / accent 没了)。历史页可能把 CSS 内嵌在 `data.html` 里；当前 lift/paste 会把这些作者
  `<style>` 先收敛到 `custom_css` 再写入目标 deck。paste 报了拷资产、render 没坏 = 好,**别预先
  `get-page --css` + `grep [data-page=]`**。
  **只有第 4 步真出坏页才诊断**:`get-page <K> --css` 空 + `grep '\[data-page=' <源>/index.html` 命中 =
  漂移 → 修源 `python3 deck-json/repair-lifted.py <源output目录> --apply`(把 head CSS 迁回各页
  custom_css + 重渲)→ 重 paste。手动恢复细节(少用):从 head 抓 `.slide[data-page="NN"] …` 塞进
  custom_css(`scope_selectors` 自动把 `[data-page=NN]` 重锚到当前 key)+ `set-accent`/`set-decor` 补回 +
  拷 `url()` 资产(含 `assets/shared/...` 共享池,新 deck 常缺、必拷)。
- **拎来的页要翻译成目标 deck 的语言**(英文母版拎进中文 deck):别再手搓 paste→get-page→翻→set,
  用两段式驱动 `lift-translate-page.py`——`emit-pairs <目标deck.json> <源> <页> [位置]` 落页 + 吐出
  只含该页的翻译骨架 → 填每个 `replace`(套术语表、压缩 EN 别撑爆 CJK 宽)→ `apply <pairs>`(闸 +
  结构安全 text-swap + scoped render)。模型只填 {find,replace},机械链不必每 session 重发现;整本译后
  QA(residual-CJK / 溢出)仍是交付步(`translation-qa.py`)。

## 速度纪律(别再犯——全是 35min/页 复盘里挤出来的)

- **焦点 / hero 元素第一版就做足**:粗、亮、实心、明确。别从胆怯版试探着加码。
  (反例:题眼箭头"细弧线 → 加粗 → 实心亮青"白烧 3 轮 render+截图 ≈ 6min;实心粗箭头本就
  显然比细线清楚,第一版就该上。)
- **默认不读兄弟页学配色**:直接用上面框架 token + 深色底约定,一定合规、底色也对。
  只有 deck 明显自定义了**非框架默认的主题色**时,才读 1 张同类页取色。
- **recon 一把并行抓完**:上面常量已钉死,无需 grep CSS / 派 Explore / 逐个 `--help`。
- **审稿只看整图**(1920×1080 那张),非歧义不逐块放大裁切。
- **raw 视觉微调先 preview,后真闸**:`preview-slide.py --key K` 用来发现换行 / 间距 /
  焦点 / off-ladder 等单页问题;只有页面视觉基本成立后才跑 `render-deck.py --scope N --shoot`
  或 `--iter`。别为每次 20px 位移都付正式 render 成本。
- **render-review 单轮封顶**:`--scope N --shoot` 后**读 `last-render.log` 第一行就决策**,
  别为「确保」投机重渲。`✔ PASS`(或只剩 F-302 baseline 既存项)→瞄一眼整图即完;
  `❌ BLOCKING` 几何(R-VIS-CARD-OVERFLOW/R-OVERLAP/R-OVERFLOW/band-collide——已替你量好、
  点名元素)→只修那个元素,**只准 1 次** fix-render,还红就交人,别盲目迭代。
  deck-wide rollup(R20 字阶/配色/圆角漂移)是别页既存噪声,绝不重渲去「诊断」它。
- **distribution advisory 有三分法**:`PASS` 但有非阻塞布局提示时,若明显可修(左右中线 /
  卡片下内距)就修 1 轮;若是有意构图,在 slide `allow:["imbalance"]` 或交付说明中留痕;
  不要无声忽略,也不要绿灯后无限追 advisory。
- **收尾小改并进主步**:screen_label 之类在 insert/set-page 时一起设,别单开一轮 render。

## 改单值 / 换个色 / 调 embed 尺寸（EDIT 既有页 — 最高频，比插页更轻）

> 改既有页的「一个字段」时别走 generation 级 recon：别 `json.load` 手猜形状（读用
> `get-page <key|#N> --html/--css`）、别逐个 `--help`、别整页 `set-page`。下面是外科配方。
> （2026-06-22 齐鲁 字号/颜色/demo 三连复盘补：三次都是改既有页单字段，却重新发现了一遍
> CLI ——这些是固定常量，钉这里。）

- **改一个标量值**（`fit_width` / 某颜色变量 / `accent` / 任一值）:
  `deck-cli.py <deck.json> --yes set slides.<N-1>.<点路径> <值>`
  —— 路径 **0-based**（页70 = `slides.69`）；值默认 JSON 化（`1500`→int）；强制字符串加 `--str`。
- **只换某页整段 `custom_css` / `data.html`，且原样保住 `lifted` 溯源串 / `title` 等其它字段**:
  `deck-cli.py <deck.json> --yes set slides.<N-1>.custom_css --from-file f.css`
  —— `--from-file` = verbatim 读文件、不 JSON 化，专为大段 css/html，**只动这一个字段**。
  `set-page` 是「整页 payload」入口（重写 html+css+title、按 `--lifted` 设 lifted 标记）——
  单字段编辑别用它，会顺手动到你没想改的字段。
- **iframe-embed demo「字太小 / 两侧留白」= 不要碰 `custom_css`，调 `data.fit_width`**:
  `deck-cli.py <deck.json> --yes set slides.<N-1>.data.fit_width <原型设计宽>`
  → 渲染器自动 `zoom = 1800 / fit_width`（fit_width 越小越放大、白边消失）。详见
  `prototype-embed.md` F-314。设计宽 = 原型 `max-width`/容器宽（grep 一下）；别设到 < 其
  `min-width` 否则塌版。
- **删掉绝对定位页里的一整块**（撤一个底部条 / 一列 / 一段）：剩余内容的视觉重心会随之上移或下移，
  `R-VIS-CANVAS-CENTER` 会报「偏上 / 偏下」。**删完同一遍就把保留内容补回画布中心**——按删掉区域的
  几何平移（≈ 删掉块高度的一半），或一次读 canvas band 中线 px 补到位；别等渲一轮看报告再补、白渲一遍。
- **改完一遍过验收**：raw 视觉微调用 `preview-slide.py --key K` 先收敛;收口再跑
  `render-deck.py <deck.json> <out-dir> --scope <N> --shoot`
  （渲 + 只校验第 N 页 + 截 `.shoot-pN.png`；既有 deck-wide 基线问题在 scoped 下自动降级、
  不阻塞本页；别为一页改动跑 `--final` / 全 deck 渲）。
- **嵌入的本地原型改完**：它是 iframe `src` 直接按相对路径加载的——改原型 `.html` 文件即生效，
  **deck.json 没动就不必 re-render**；直接 shoot deck 页或刷新浏览器即可验。
