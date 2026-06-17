# F-338..F-341 · 成品 deck 运行时加载性能 quick-wins(2026-06-17)

> 范围:**已渲染的成品 deck 在浏览器里打开的加载性能**(运行时,P50–P55 家族),
> 特别是移动端。不含生成流水线性能(那是 `PERF-OPT-PLAN-2026-06-16.md`),也不含
> LLM 创作阶段。
> 原则:框架级修复(不动单个 deck)、零校验回退、每项有 before/after 数字。
> 分支:`perf-runtime-quickwins-imgopt`(独立 worktree,off origin/main)。

## 0. 起因

用户:「飞书 deck H5 现在本地打开还是有点慢,特别是移动端,这个加载能优化么?」

## 1. 诊断(多-agent 审计:5 维并行 finder → 逐条对抗式验证,18/22 确认)

实测画像(样例 `runs/digital-employee-guide-428`,50 页导入 deck):

- **背景图 4K 超采**:`bg/` 共 16MB,每张 3840×2160 JPEG,而画布只有 1920×1080 ——
  超采 4 倍。管线里无任何降分辨率步骤。
- **内容图 60MB PNG**:168 张共 ~60MB,最大单张 7.53MB;照片却存成无损 PNG。
- **scroll 模式(移动默认)100 个常驻合成层**:`feishu-deck.css` 的 base `.slide-frame .slide`
  对每页永久 `will-change:transform` + `translateZ(0)` → 100 个 1920×1080 GPU 层,
  ~1.7GB 级显存压力,层驱逐抖动。
- **render-blocking**:`feishu-deck.js`(73KB)同步、3 个外链样式表、edit-mode 默认随发布。
- 字体是系统字体(0 web font)——不是问题。

### 认知纠正(验证阶段打回的直觉误区)

1. **不是「16MB 一次性下载卡网络」**:背景图同时也是 `<img loading=lazy>`,网络层惰性 +
   URL 去重。真正的杀手是**解码**——移动端默认 scroll 模式所有页 layout → 所有 4K 背景
   解码,弱手机 CPU 上逐帧解码即卡顿。→ 降分辨率(降解码量)比降下载量更对症。
2. **本地打开多为 `file://` / 裸 `python3 -m http.server`,无 gzip**:gzip 类收益在该
   场景不生效;**原始字节(图片瘦身 + minify)**才是真杠杆。→ 本批不押注 gzip。
3. **framework 已有部分虚拟化**:`content-visibility:auto`(css:181)+ present 非当前页
   `content-visibility:hidden`(css:262)。所以「全 DOM 渲染」的 paint 成本已部分缓解;
   DOM 虚拟化类发现被降级。

### 被驳回的发现(对抗验证 is_real=false,记录以免重提)

- `content-visibility-not-defer-bg-fetch`:bg 同时是 `<img lazy>`,网络已惰性去重,「全量
  预取」前提不成立。
- `no-presplit-mode-pre-js-all-frames-layout`:前提对但收益可忽略。
- `present-frame-intrinsic-size-letterbox`:观察准确但收益可忽略且改法不安全。
- `local-serve-no-compression`:gzip 数字对,但本地打开多为 file://,框架站错(见认知纠正 2)。

## 2. 本批落地(两档)

### 一行级 · 零风险 · 移动端立竿见影

- **F-338**(`assets/feishu-deck.css`)scroll 模式合成层解除。新增:
  ```css
  .deck[data-mode="scroll"] .slide-frame .slide {
    transform: scale(var(--fs-scale, 1));  /* 去 translateZ(0):不提层 */
    will-change: auto;
  }
  ```
  关键交互:光加 `will-change:auto` 不够——base 规则 `transform` 里的 `translateZ(0)`
  会**独立强制提层**,所以覆盖规则必须同时去掉它。**只覆盖 scroll**,被反复调优的
  present 翻页闪烁路径(css:277,确实需要提层做缩放动画)完全不动。
- **F-339**(`_shell.html` + `render-deck.py`)`feishu-deck.js` 加 `defer`。它本就自门控
  `readyState`/DOMContentLoaded → defer 后 init 时序不变、首屏可并行 settle。
  `motion_scripts`(opt-in GSAP)一并 defer 以保源序(defer 按文档顺序执行,
  runtime→gsap→motion 次序不变)。
- **F-340**(`render-deck.py`:1983/1993)两处 `<img>` 加 `decoding="async"`,JPEG 解码移出
  主线程。纯渲染 hint,无版式/校验影响;导入 deck 的全幅背景 `<img>` 也覆盖。

### 图片瘦身

- **F-341** 新工具 `assets/optimize-images.py` + 接进 `finalize.sh`。
  - 降分辨率:长边 >1920 降到画布尺寸(保比例,LANCZOS)。
  - 转码:**完全不透明** PNG ≥150KB → JPEG(照片 10–15× 小),同步重写
    index.html/deck.json/slide-index.json 引用(含 URL 编码中文名,含百分号编码变体)。
  - **真有透明**的 PNG 只降分辨率、保 PNG 无损(实测样例 147 张 PNG 中 81 张真透明但仅
    2.4MB,66 张不透明吃掉 54.4MB —— alpha 守卫是对的且必须)。
  - **按维度天然幂等**:已≤上限即跳过;转码后源 png 删除,重跑无事可做。
  - 依赖轻:Pillow 优先(转码必需,做 alpha 检测);无 Pillow 退 `sips` 仅降分辨率;
    都没有则打印提示 no-op,**绝不让构建失败**。
  - **架构决策**:`finalize.sh` 里只接**降分辨率**(`--no-transcode`)——转码改文件名会
    与 copy-assets 刚写的 manifest/origin 追踪冲突;降分辨率不改名、manifest 保持准确。
    完整转码留给独立工具直接跑在就地 deck(导入 deck 正是此例,无 manifest 管线)。
  - 接入点:copy-assets 之后、validate 之前(validate 看到的就是交付字节)。默认开,
    `finalize.sh --no-optimize-images` 关(给刻意要 hi-res / 可缩放细节的 deck)。

## 3. 实测(真实导入 deck digital-employee-guide-428,完整 50 页,含 assets/)

| 指标 | before | after |
| --- | --- | --- |
| deck 总量 | 76MB | **20MB**(74% 小) |
| 背景 `bg/` | 16MB(50×4K) | 4MB(50×1080p) |
| 栅格总量 | 73.8MB | 17.6MB(76% 小) |
| optimize 明细 | — | 57 降分辨率 · 40 转码 · 127 已最优 · 3 引用文件更新 |
| validator | PASS(0 err) | **PASS(0 err)** |
| 断链 | — | **0**(input/ 168 refs + bg/ 50 refs 全命中) |
| 幂等 | — | 二次运行 0 改动 |

新测 `deck-json/tests/test_optimize_images.py` 8/8:降分辨率+幂等 / 不透明转码+引用重写 /
透明不转码 / 小图跳过 / dry-run 零改动 / URL 编码中文名重写 / shared 池跳过。

注:比初判 ~10MB 大些,因为安全起见保留了 107 个透明/小 PNG 无损。头号 4K→1080p
**解码**收益(用户「移动端慢」的真症)已完全实现。

## 4. 后续待办(本批未做,已确认有效,按 ROI 排序)

- **edit-mode 默认随发布(66KB 死重)**:加 `--present`/`--publish` 渲染模式剥掉 edit-mode
  CSS+JS;发布路径默认剥。
- **`extra-layouts.css`(41KB)按需引入**:只有 7 个冷门布局用到,镜像 `patterns_css_link`
  的条件逻辑。
- **cover 背景 preload + fetchpriority=high**:首屏 LCP 提前。
- **CSS/JS minification**:`file://` 场景直接省原始字节(esbuild 类工具,非手搓正则)。
- **resize 只重算当前帧**:现在每次 URL bar 伸缩重算 100 帧(feishu-deck.js:766/478)。
- **背景图双重引用去重**:全幅背景同时是 CSS `:has()` 背景 + `<img>`,冗余解码。
- **optimize-images 升级**:`finalize.sh` 也走转码(需先打通 manifest/copy-assets 的
  rename 协同);WebP 选项(比 JPEG 再小 ~25%)。

## 5. 风险与边界

- 所有改动框架级,不动单个 deck。
- 视觉基线截图走 present 模式,F-338 只动 scroll 模式 → 零基线漂移。
- F-339/F-340 改渲染输出(`defer` / `decoding=async`),golden/signature 测试若断为**预期**
  (输出有意变化),同步更新 golden。
- optimize-images 在**输出副本**上降分辨率;run-root `input/` 原图保留,可再编辑。
