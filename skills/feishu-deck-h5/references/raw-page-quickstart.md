# raw-page-quickstart — feishu-deck-h5 reference

> 何时读:手写一张 bespoke `layout:"raw"` 页(自定义版式 / SVG / 动效),或往现有
> deck **插一页**。目的:把每次都要重新考古的**固定契约**一次性钉死——这些常量
> 永不变,别再 grep CSS / 派 Explore / 逐个 `--help` 重新发现。recon 应从 ~9min → ~3min
> (2026-06-20 齐鲁「那一跃」页复盘:一张 bespoke 页烧了 35min,其中 ~6min 是重新
> 考古这些固定事实,~6min 是焦点元素试探性返工——两者都该被本文消灭)。

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

## raw 页 5 条铁律

1. **框架不给 raw 页渲 `.header`** → 自己写标题元素(约定起点:绝对定位 `top:61 left:73`,
   `#fff`,`600 48px/1.1 var(--fs-font-cjk)`)。自绘标题后 R-VIS-TITLE-POSITION(只看
   `.header` 的 bbox)自动跳过,不必隐藏什么。
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

## 速度纪律(别再犯——全是 35min/页 复盘里挤出来的)

- **焦点 / hero 元素第一版就做足**:粗、亮、实心、明确。别从胆怯版试探着加码。
  (反例:题眼箭头"细弧线 → 加粗 → 实心亮青"白烧 3 轮 render+截图 ≈ 6min;实心粗箭头本就
  显然比细线清楚,第一版就该上。)
- **默认不读兄弟页学配色**:直接用上面框架 token + 深色底约定,一定合规、底色也对。
  只有 deck 明显自定义了**非框架默认的主题色**时,才读 1 张同类页取色。
- **recon 一把并行抓完**:上面常量已钉死,无需 grep CSS / 派 Explore / 逐个 `--help`。
- **审稿只看整图**(1920×1080 那张),非歧义不逐块放大裁切。
- **收尾小改并进主步**:screen_label 之类在 insert/set-page 时一起设,别单开一轮 render。
