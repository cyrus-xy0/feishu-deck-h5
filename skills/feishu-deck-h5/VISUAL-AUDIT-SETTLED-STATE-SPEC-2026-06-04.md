# 视觉审计「呈现+结算态」测量规格 (VISUAL-AUDIT-SETTLED-STATE-SPEC-2026-06-04)

> 交给 unify-validate-arch 迁移线(步骤 3:把规则迁进 `audits.js`)。
> 不是另搞一套——是补上「测哪个时刻的渲染 DOM」这条缺失规格,并防止迁移把旧引擎的
> 误报一起搬过来。落点:`run-audits.py`(harness)+ R-OVERFLOW/dead_anim 迁移时的规则写法。

## 0. 缘起(实证)
langzi 客户 demo(`runs/langzi-…-minlite-…/index.html`,54 页 graft 包)用 **旧引擎**
(`validate.py → run_visual_audits → visual-audit.js`)check 出 195→132 错,其中一大批是**假阳**:
- 「死动画 / 元素停在隐身」(dead_anim):Playwright 实测 `yifuli-case-page` 的 `.yf-hero/.yf-metric/.yf-summary/.yf-value` opacity 全 = 1,**根本没隐身**。
- 「内容超出 1920×1080」(R-OVERFLOW):`slide.scrollWidth` 2078→4582,但那是 `yfGlowFloat/yfHeroDrift/yfSweep` 这类**持续漂移装饰**把元素 transform 推出框,而 slide 是 `overflow:hidden` 裁掉的——**视觉上不溢出**。

**根因**:旧 `visual-audit.js` 为让 scoped 选择器解析,会**强加 `is-current`**(L309-322),这触发 `.slide-frame.is-current .slide>*` reveal,把进场元素置于**动画第一帧**(opacity:0 / transform 偏移),然后**没等动画结算就量**。它自己注释了这个污染(**visual-audit.js:220-221**):
> "reveal 会把 .slide 直接子元素初态置 opacity:0 / transform 偏移,**污染 R-VIS-TITLE-POSITION / R-OVERFLOW 等的 bbox**。"

## 1. 新引擎已经做对的部分(别重复造,别回退)
`audits.js` 的 `R-VIS-CANVAS-CENTER`(L191-213)**不 force is-current**,而是:
- L195 跳过 `display:none / visibility:hidden / opacity:0` 的元素;
- L196 跳过 `position:absolute/fixed`(装饰);
- L204-213 对每个 `overflow!=visible` 的祖先**求交裁剪**(被裁内容不算可见)。

→ 这套「跳隐藏 + 裁剪感知」对**几何类**天然免疫动画初态/装饰飘移污染。**迁移时务必沿用这套,不要把旧引擎的 `scrollWidth` 写法搬过来。**

## 2. 要补的两条(精确、收窄)

### (A) 规则写法 — R-OVERFLOW / card_overflow 迁移时
**不要**移植 `visual-audit.js:383` 的 `slide.scrollWidth>1920 || slide.scrollHeight>1080`。
**要**照 `audits.js` R-VIS-CANVAS-CENTER 的可见并集模式判溢出:

```
// 可见溢出 = 「跳隐藏 + 裁剪感知」后,仍有元素的可见盒越出 slide 画框 [0,0,1920,1080]
for el of slide.querySelectorAll('*'):
    skip STYLE/SCRIPT
    cs = getComputedStyle(el)
    skip if display:none / visibility:hidden / +opacity===0          // 同 CANVAS-CENTER L195
    skip if position absolute/fixed                                   // 装饰/glow 不算内容 L196
    r = el.getBoundingClientRect()  → 转 slide 相对 + /scale
    // 与每个 overflow!=visible 祖先求交(被裁的不算可见)            // 同 CANVAS-CENTER L204-213
    clip r against overflow-hidden ancestors
    if clipped width/height < 6: continue
    if vis_left < -TOL or vis_top < -TOL or vis_right > 1920+TOL or vis_bottom > 1080+TOL:
        → R-OVERFLOW finding（带越界方向/像素）
```
- `overflow:hidden` 裁掉的装饰漂移**自然不计**(被祖先求交切掉)。
- card_overflow(内层 `overflow:hidden` + 内容比容器高)单独保留,但同样跳 opacity:0。
- 阈值 `TOL`(如 2px)抗亚像素抖动。

### (B) harness — `run-audits.py` 加「呈现+结算」一步(给 dead_anim / dead_rule 用)
几何类有 (A) 兜底就够了;但 **dead_anim(F-57)/dead_rule(R-VIS-DEAD-RULE,F-68)** 的语义本身就是
「该出现却停在隐身 / 选择器命中不到」——要区分「真坏」vs「只是动画还没播 / scoped 选择器要 is-current 才命中」,
**必须**先把 DOM 推到「present + 动画结算」态。这是 harness 职责(不是单条规则逻辑),放 `run-audits.py`。

**插入点:`run-audits.py` 第 80↔81 行之间**(`page.wait_for_timeout(settle_ms)` 之后、设 `__AUDIT_SCOPE__` / `evaluate(audits_src)` 之前):

```python
        page.wait_for_timeout(args.settle_ms)  # 既有:布局稳定
        # —— 新增:呈现 + 结算态 ——
        # 让 reveal-gated / 持续动画内容以「结算后」态被测量,而非动画第一帧。
        # 见 VISUAL-AUDIT-SETTLED-STATE-SPEC。仅 dead_anim/dead_rule 强依赖此步;
        # 几何类规则已用「跳隐藏+裁剪」自免疫(audits.js R-VIS-CANVAS-CENTER)。
        page.evaluate("""() => {
          // ① 强加 is-current:让 .is-current 作用域的选择器解析、reveal-gated 子元素不被永久压隐
          document.querySelector('.deck') && document.querySelector('.deck').setAttribute('data-mode','present');
          document.querySelectorAll('.slide-frame').forEach(f => f.classList.add('is-current'));
          // ② 结算动画:有限动画 finish()→终态(进场元素到达可见);无限漂移/glow finish() 抛错→cancel()→回基态(无瞬时 transform)
          for (const a of document.getAnimations()) {
            try { a.finish(); } catch (e) { try { a.cancel(); } catch (e2) {} }
          }
        }""")
        page.wait_for_timeout(120)  # 结算后让布局 flush 一次
```

- `getAnimations()` 拿到 CSS + WAAPI 全部动画;`finish()` 把**有限**进场动画推到终态(opacity→1、transform→0),`cancel()` 把**无限**漂移/glow 去效到基态。两类都不再停在第一帧。
- 强加 is-current **全帧**即可(一次 load 量整 deck 的模型);量的是各 slide 自身相对坐标,全帧 current 不影响 per-slide bbox。无需 restore(跑完即关浏览器)。

## 3. 验收
1. **回归对齐**:加 (B) 后重跑 R-VIS-CANVAS-CENTER 回归(everbright s17 偏上47 / s22 偏下61 / s54 偏上54)——finding **必须不变**(结算只让隐藏元素现身,canvas-center 本就跳隐藏,理应零漂移;若变,说明结算引入了副作用,需排查)。
2. **假阳归零**:对 langzi `yifuli-case-page(9)/approval-center(38)/meeting-qc(39)`——加 (A)+(B) 后,dead_anim 应降到 0(或只剩真·永久隐身),R-OVERFLOW 应不再因 glow/drift 误报;真·静态溢出(若有)仍报。
3. **UI1 不在本规格范围**:截图当正文是 imported 策略题(deck 级 `fs-deck-origin=imported` / 逐页 `data-ui-screenshot`),与本测量态修复无关。

## 3b. 实测验证(2026-06-04,langzi minlite 第 9/38/39 页,Playwright 原型)
复现「旧引擎:force is-current 后立刻量(动画 t=0)」vs「spec(B):force is-current + `getAnimations().finish()/cancel()` 结算后量」:

| 页 | dead_anim(opacity:0 元素)BEFORE→AFTER | 旧 scrollW×H overflow BEFORE→AFTER | spec(A) 裁剪感知违例 |
|---|---|---|---|
| 9 · yifuli-case | **1 → 0**(after 无残留) | 2071×1090 flag=T → 2070×1080 flag=**T** | **0** |
| 38 · approval-center | **1 → 0** | 2094×1090 flag=T → 2090×1080 flag=**T** | **0** |
| 39 · meeting-qc | **1 → 0** | 2064×1090 flag=T → 2060×1080 flag=**T** | **0** |

两条独立结论:
1. **(B) 结算 → dead_anim 归零**:BEFORE 的 opacity:0 元素结算后全部现身(after-still-hidden 为空)→ 那些「隐身」是进场动画初帧,**非真损伤**。
2. **(A) 才是 overflow 的解,(B) 不够**:结算后**旧 `scrollWidth` 仍 >1920(2060-2090)照样 flag**(glow/drift 是 `position:absolute` + 被 `overflow:hidden` 裁,但 scrollWidth 仍计入);而 **spec(A) 裁剪感知违例 = 0**,正确判定「无可见溢出」。→ **overflow 必须靠 (A) 重写规则,单靠 (B) 结算修不掉。**

> 注:本原型 BEFORE 计到 1 个 opacity:0(旧引擎报「4/6 处」)——是我复现的 force/测量时序与旧引擎不完全一致所致;方向(→0)与 overflow 的裁剪感知归零是确定的,计数仅示意。

## 4. 与统一架构的一致性
- 方向一致:统一架构命题是「单基底=渲染后 DOM」;本规格补一句「**渲染后 DOM 的 present+结算态**」,(A) 复用你已落地的 R-VIS-CANVAS-CENTER 裁剪/跳隐藏 pattern。
- 落点正确:(A) 在迁移规则时写对即可;(B) 属 harness(`run-audits.py`),不污染单规则源 `audits.js`。
- **别动正在退场的 `visual-audit.js`**(那是要删的);本规格只面向新引擎。
