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

## raw 页 5 条铁律

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
3. **焦点闸 R-FOCAL**:≥3 个元素并列共享**全页最大字号**才告警。把 48px 只给该给的
   (如左右双标题 = 2 个,安全),其余 ≤28。真要 3+,该页 slide JSON 加
   `"allow":["no-focal"]`——**真实字段,deck 里实证可用**;无配图同理 `"allow":["no-imagery"]`。
4. **SVG `<text>` 也有字号 floor**(R-VIS-SVG-TEXT-FLOOR)→ 节点/标签宁可用 HTML
   `<span>` 绝对定位**覆在** SVG 上,字号好控、渲染更清晰。
5. **动效只写 `slide.custom_css`**。deck.json 无 JS 槽,re-render 会抹掉任何
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

## 插一页 / 改一页 · 三命令配方

```bash
# 1) 插脚手架。insert 自己 range-check 位置 + 拒撞名 key → 不必另跑 deck-map "确认插入点"
python3 deck-json/deck-cli.py --yes <deck.json> insert <N> raw <KEY>      # 新页成第 N 页;raw 不需 variant
# 2) 灌 html/css/title。W4 pre-write lint 会提醒某 16px 选择器上是否压了 ≥8 字正文
python3 deck-json/deck-cli.py --yes <deck.json> set-page <KEY> --html f.html --css f.css --title "…"
# 3) scoped 渲染:只校验 + making-of 只刷这一页(改一页别全 deck 渲)
python3 deck-json/render-deck.py <deck.json> <out-dir> --scope <N>
# 4) 自己审稿截图(present 模式 1920×1080 design clip)
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
  按提示重读即可,不要 `--force` 绕过。
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

## 速度纪律(别再犯——全是 35min/页 复盘里挤出来的)

- **焦点 / hero 元素第一版就做足**:粗、亮、实心、明确。别从胆怯版试探着加码。
  (反例:题眼箭头"细弧线 → 加粗 → 实心亮青"白烧 3 轮 render+截图 ≈ 6min;实心粗箭头本就
  显然比细线清楚,第一版就该上。)
- **默认不读兄弟页学配色**:直接用上面框架 token + 深色底约定,一定合规、底色也对。
  只有 deck 明显自定义了**非框架默认的主题色**时,才读 1 张同类页取色。
- **recon 一把并行抓完**:上面常量已钉死,无需 grep CSS / 派 Explore / 逐个 `--help`。
- **审稿只看整图**(1920×1080 那张),非歧义不逐块放大裁切。
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
- **改完一遍过验收**：`render-deck.py <deck.json> <out-dir> --scope <N> --shoot`
  （渲 + 只校验第 N 页 + 截 `.shoot-pN.png`；既有 deck-wide 基线问题在 scoped 下自动降级、
  不阻塞本页；别为一页改动跑 `--final` / 全 deck 渲）。
- **嵌入的本地原型改完**：它是 iframe `src` 直接按相对路径加载的——改原型 `.html` 文件即生效，
  **deck.json 没动就不必 re-render**；直接 shoot deck 页或刷新浏览器即可验。
