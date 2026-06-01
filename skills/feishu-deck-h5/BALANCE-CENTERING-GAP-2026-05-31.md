# balanceSlide 居中带偏移 —— 诊断 + 回退记录(R-11)

> 维护者内部文档 · 2026-05-31 · 基于青啤 deck(`20260526 … lark-qingdao-beer`)62 页全量几何扫描 + DOM 级根因定位
> **结论**:运行时 `balanceSlide` 不该硬扛"内容垂直居中";当日改动已 `git restore` 到 HEAD(止损),问题立为 **R-11**,在 stage 定位约定层 / 分布审计报告层解,不在运行时引擎。

## 1. 一句话

bespoke deck 普遍把 `.stage` 写成对称 `position:absolute; top:200; bottom:200`(中线 **540**),
而"内容在 [标题底 → 屏幕底] 带内居中"的理想中线 ≈ **597** —— 二者差一个 **固定 57px**。
这不是单页 top-heavy bug,是 **deck 级 stage 定位约定** 与理想居中带之间的系统性偏移。

## 2. 数据(青啤 62 页;排除右上角 logo/header,只量 `.stage` 内容相对理想中线的偏移)

| 桶 | 页数 | 说明 |
|---|---|---|
| strong(off>80) | **2** | #1 cover(HERO 布局,引擎本就跳过 + 封面留白是设计)、#49 |
| mild(50–80) | **20** | off **高度集中在 ~57**(53–74)= `597 − 540`,即对称 stage 约定 |
| ok(±50) | 30 | 居中 / 填满 |
| low(<−50) | 1 | #30 |
| skip | 9 | section/agenda 等无 stage 或空 |

- **没有真正"内容堆上半、下方大片空白"的 top-heavy 页。**
- mild 的 20 页是**同一个常量偏移**,且**视觉亚感知**(57px 在 1080 高里仅 5%);#3/#6/#33/#53 截图均觉居中/填满。
- 早先用含 logo 的口径测出 off −134/−160 是**高估**:右上角 `.wordmark`/`.client-mark`(slide 直接子)被算进"内容"把重心拉高;按 `.stage` 内容算,#53 实际只偏 ~57px。

## 3. 两条运行时执行通道为何都失败(关键教训)

`balanceSlide` 想在运行时把正文整体下移 ~57px,试过两种机制,**都被 deck 自身架构废掉**:

1. **`justify-content / align-content: center`** → 被 `flex:1` 子容器**架空**。
   bespoke 正文容器(`.grid`/`.flow`)常 `flex:1` 撑满 stage、内容 `align-items:start` 顶在上面,
   父容器的 `center` 无可用 slack。实测 **#44**:标记 `data-fs-autobalanced` 但 `contentMid` 489→489 零变化(空转)。

2. **`transform: translateY`** → 被进场动画 **`fs-reveal` 覆盖**。
   stage 有 `animation: fs-reveal`;animation 运行/fill 期间 transform 由动画接管,优先级高于 inline style。
   实测 **#53**:inline `translateY(51.4px)` 在,但 `getComputedStyle(stage).transform === matrix(1,0,0,1,0,0)`(identity)→ 视觉零位移。

> **结论:运行时 JS 在 bespoke deck 上没有干净通道做这个垂直微调** —— flex 占了布局通道,animation 占了 transform 通道。

## 4. 真根因 + 正解方向(均不在运行时引擎)

根因 = **deck 的 stage 定位约定**:bespoke 把 stage 设成对称 [200,880]。framework 默认 stage 本是**非对称**(top≈220 / bottom≈110,中线≈595≈理想)。正解候选:

- **(a) stage 定位约定层(首选)**:别让 bespoke 把 stage 改成对称;在 lift/迁移或 CSS 约定层守住 framework 非对称 stage,57px 偏移从源头消失。见 [[project-feishu-deck-lift]] 的 R-SELF-CONTAINED / custom_css 通道。
- **(b) `check-distribution.py` 增维**:给几何分布审计加一条"`.stage` 内容相对 [标题底→底] 居中带偏移"指标,**报告**而非运行时强改(报告级,零回归)。
- **(c) 若确需自动修**:只在"无 `fs-reveal` 动画 且 无 `flex:1` 撑满"的页注入 stage 非对称定位 CSS(覆盖 top/bottom),而非 transform/justify;但收益亚感知,优先级低。

**明确不做**:`balanceSlide` 运行时 transform/justify 硬扛(已实证两通道皆废)。

## 5. 回退记录

- **2026-05-31**:当日 `balanceSlide` 的 `_abTopHeavy` / `_abUnfillFlex` / 居中注入(历经两版:① `justify/align-content:center` 注入,② 页级 `translateY` 下移)**全部 `git restore` 到 HEAD**。
- 重构尝试代码(页级 translateY 版)备份在:`~/feishu-deck-balanceslide-reattempt-20260531-143050.js`,供本 R-11 落地时参考 —— 其中 `_abTopHeavy` 的"排除 logo、只量 `.stage` 内容、把居中带锚到标题底"判据是**对的**,只是执行通道选错。
- `preflight.sh` 的 RO-mount fallback python3 改动与本问题无关,**独立保留**。
- 回退前确认:schema deck baseline 零回归 + 0 标题移动(死规则未破)。
