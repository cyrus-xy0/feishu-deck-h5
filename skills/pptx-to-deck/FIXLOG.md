# pptx-to-deck · 问题→修复日志

目标：每次真实 PPT 暴露的缺陷都在这里记录 + 在 `build_pptx.py` 里**通用化修复**（不写死某份 deck），
让下一份 PPT 一次做对。测试基准稿：`营销人的 AI 副驾-从创意到落地的新工作方式.pptx`（60 页）。

## 已修复

### F1 · 表格 `_NoFill` 单元格崩溃
- **现象**：`render_table` 调 `cell.fill.fore_color` 在非 SOLID 填充（`_NoFill`）上抛 `TypeError`，整个转换中断。
- **根因**：`fill.type is not None` 对 `_NoFill` 也成立，但它没有前景色。
- **修复**：新增 `fill_hex(fill)` 安全函数——仅当 `fill.type == MSO_FILL.SOLID` 才取 `fore_color`，其余一律 None。表格/形状/背景统一走它。
- **通用性**：✅ 任何含无填充表格单元格的 PPT 都不再崩。

### F2 · 主题色（theme color）文字回退成猜测色
- **现象**：用主题色（tx1/lt1/accent…）的文字 `color` 解析不到，回退默认。
- **根因**：python-pptx 对 schemeClr 不返回 `.rgb`；且 theme part 是通用 `Part`，无 `._element`，要解析 `.blob`。
- **修复**：`build_theme_map(prs)` 从首个母版关联的 theme part 解析 `<a:clrScheme>`，映射 `dk1/lt1/dk2/lt2/accent1-6/hlink/folHlink`（含 tx/bg 别名）→ RGB；`rgb_hex` 对 schemeClr 查表。
- **通用性**：✅ 16 个主题色全解析。注意：未读 master `clrMap`（用默认 tx1→dk1 映射），少数自定义 clrMap 的稿可能偏；未处理 lumMod/lumOff 明暗微调。

### F3 · 嵌套双引号截断内联 style（**最严重**）
- **现象**：深色卡片上本该白色的标题/正文全渲染成深色（≈隐身）。computed color = 继承的 #111，而非 HTML 里写的 #FFFFFF。
- **根因**：`style="…font-family:"FZLanTing…","PingFang SC"…;color:#FFFFFF"` —— 字体名用了**双引号**，嵌在双引号 `style=""` 属性里，HTML 解析器在第一个内部 `"` 处截断属性，**font-family 之后的所有声明（color/font-weight…）被丢弃**。font-size 在 font-family 之前所以幸存 → 表现为"字号对、颜色丢"。
- **修复**：内联 style 里字体名一律用**单引号**（`DEFAULT_FONT_STACK` 与 run font-family 同步改）。
- **通用性**：✅ 这是全局根因，一改全 60 页文字颜色 / 粗细恢复正常。**教训：任何拼进 `style=""` 的值都不能含裸双引号。**

### F4 · 段内软换行 `<a:br/>` 丢失 → 多行标题挤成一行
- **现象**：封面标题「营销人的AI副驾」+「创意到人效的新工作方式」本应两行，被并到一行内联混排。
- **根因**：`paragraph.runs` 不含 `<a:br/>`，只迭代 runs 就丢了换行点。
- **修复**：`render_text_frame` 改为按文档顺序遍历 `p._p` 子元素：`a:r`→span、`a:br`→`<br>`、`a:fld`→字段缓存文本。
- **通用性**：✅ 任何含段内换行 / 字段（页码/日期）的文本都正确。

### F5 · 渐变填充 → CSS linear-gradient
- **现象**：渐变填充的形状（装饰卡片/背景）被当作不可复现 → 跳过或留空。
- **修复**：`gradient_css(shape)` 解析 `<a:gradFill>` 的 `<a:gsLst>` 渐变停靠点（srgbClr/schemeClr/sysClr）+ `<a:lin ang>` 角度（1/60000 度，East 起算 → CSS `(ppt+90)mod360`），生成 `linear-gradient()`。`shape_box_css` 渐变分支接入，标 is_solid=True 不再栅格。
- **通用性**：✅ 本稿 161 处渐变全部 CSS 还原。未处理径向渐变 `<a:path>` 和停靠点的 lumMod/alpha 微调。

### F6 · 线条/连接符 LINE 缺失
- **现象**：34 条 LINE（分割线等）被跳过。
- **修复**：`render_line` 用 SVG `<line>` 渲染，按 xfrm `flipH/flipV` 定起止点（支持对角线），stroke=线色、stroke-width=线宽×scale。`svg.el` 纳入 z-index:10 保持层序。
- **通用性**：✅ 任意方向线条通用。

### F7 · 媒体/视频 MEDIA 空白
- **现象**：8 个视频元素不渲染，留空。
- **修复**：MEDIA 分支优先取首帧海报图（`shape.image`），取不到则渲染带 ▶ 的深色占位。
- **通用性**：✅ 不再空白。注：视频不可播放（静态 deck），仅展示首帧/占位。

### F8 · layout/master 背景层缺失（**背景没了**）
- **现象**：封面（及多页）背景、装饰图、logo 全没，渲染在空白底上。
- **根因**：`slide.shapes` 只含本页自身形状；deck 的**设计背景图片填充 + 装饰图 + logo 都在 layout/master 层**（`<p:bg>` 的 `<a:blip>` 图片填充、layout/master 的 PICTURE 形状）。整层被漏。
- **修复**：`_emit_bg_picture()` 解析 slide/layout/master 的 `<p:bg>` 图片填充（`a:blip@r:embed` → `container.part.related_part()` → 全屏 `<img>`）；`emit_template_shapes()` 渲染 layout/master 的非占位符形状，**垫在本页内容下方**（master→layout→slide 顺序），用 `_PROMPT_RE` 滤掉"单击此处/XXXX/公司职称"等模板提示文字。
- **通用性**：✅ 所有页的模板背景/装饰/logo 都回来了。注：未解析 master `clrMap`、layout 占位符的几何继承。

### F9 · ⚠️ 截图清理误杀用户浏览器（严重事故）
- **现象**：批量截图时为清理我自己堆积的 headless helper 进程，用了 `pkill -9 -f "Google Chrome"` —— **把用户正在用的 Chrome 也杀了**（用户当时在改另一个 deck）。
- **根因**：广义 pkill 按进程名匹配，分不清「我的 headless」和「用户的浏览器」。
- **修复**：**永不** `pkill "Google Chrome"`。只杀本次截图的进程树：`kill $cpid` + `pkill -P $cpid`（子进程）+ `pkill -f -- "$udd"`（按唯一临时 user-data-dir 匹配）。每张用唯一 `mktemp -d` 做 profile，既隔离又能精准定位。
- **教训**：任何 `pkill`/`killall` 按名字杀进程前，先想「这名字会不会命中用户自己的进程」。宁可留几个 idle helper，也绝不广杀。

### F10 · ⚠️ QA sweep 把重图页误报成黑屏（**假阳性，差点冤枉重建器**）
- **现象**：57 页 sweep 后有 7 页（s17/24/28/37/38/43/54）截图全黑（13–22KB），看上去像 `build_pptx` 整页重建失败、内容全丢。
- **真因**：**不是重建坏了，是 QA 截图计时太短。** 这些页的 `deck.json` 元素其实都在（5–116 个，几何/颜色/白字全对），但每页压着 PPTX 原图的多 MB 嵌入 blob（实测 slide 28 = 两张 3.1MB 全幅 JPG + 1MB 内容 PNG ≈ 7MB）。`sweep.sh` 用 `--virtual-time-budget=2500`，Chrome 在 blob 解码完成**之前**就截了图 → 抓到黑帧。把 budget 提到 12000ms，7 页全部恢复（13–22KB → 0.6–1.4MB），内容完整。
- **修复**：`sweep.sh` `--virtual-time-budget` 2500 → **12000**，kill 轮询上限 70 → 120（60s），加注释说明 VTB 是上限非固定等待（轻页仍快，只有重图页多等解码）。
- **通用性**：✅ 任何含重嵌入图的重建 deck 的 QA 截图都不再假黑。**教训：截图工具的"页面坏了"要先排除"截早了"，别急着改重建器——本例诊断一度误判为 build_pptx 静默吞错（`_slide_is_hard` / `except: continue`），实测 `is_hard=False`、`data.elements` 非空才翻案。**

### F11 · `<a:ln><a:noFill/>` 误变成灰色幻影边框（**每个文本框都套灰框**）
- **现象**：导入后每段文字前面多出一个同位置、`border:#888888 1px` 的 `shape`，整页文本框被灰色细框包住——既不是浏览器选中框也不是编辑态辅助框，是 `build_pptx` 真实生成的边框。
- **根因**：源 PPTX 的文本框线条是 `<a:ln w="12700"><a:noFill/></a:ln>`——「线宽存在，但线填充为无」= PowerPoint 视为无线条。但 `_border_obj()` 只判断 `ln.width > 0`，拿不到颜色就 fallback 成 `#888888`，于是把"无线条"错误变成灰描边。python-pptx 不暴露 `<a:noFill/>`，只看 `ln.width`（仍 >0），不读原始 OOXML 就识别不了。
- **修复**：新增 `_line_is_nofill(shape)`——直接读 `<p:spPr><a:ln>` 下是否有 `<a:noFill/>`，有就判定无线条。`_border_obj()`（文本框/AUTO_SHAPE 边框）和 freeform `custGeom` 描边路径都先过这道闸：noFill → 不出边框/描边。真实有颜色的边框照常保留。
- **通用性**：✅ 任何 `noFill` 线条的形状都不再产生幻影灰框；回归测试 `test_border_obj_nofill_returns_none` / `test_border_obj_real_border_preserved` 锁住两个方向。**教训：python-pptx 的 `ln.width>0` ≠ 有线条，必须读 OOXML 的 `a:ln/a:noFill`。**

### F12 · 干掉混合(2 层)管线 → 单一纯代码重建 + 收尾件共用
- **背景**：曾有两条管线——`build_pptx.py`(纯代码四层可编辑) + `build_pptx_hybrid.py`(LibreOffice/PyMuPDF 像素保真两层)，且 SKILL.md 把 hybrid 标「推荐默认」，导致导入时被默认带向"像素保真不可编辑",而真实诉求是「全可编辑」。
- **处理**：① `build_pptx_hybrid.py` `git mv` 归档到 `skills/_deprecated/`。② 它体内三个**零 fitz/PIL 依赖**的收尾函数 `post_process`(letterbox + fitText 超框自适配) / `make_portable`(自包含打包) / `_default_renderer` 剥进新模块 `assets/canvas_finish.py`(纯 stdlib)。③ `rerender-deck.py` 与 `build_pptx.py` 都改 import `canvas_finish`——**build 与 rerender 从此共用同一套渲染层收尾**。④ `build_pptx.py` 渲染后接 `make_portable + post_process`(原来纯管线漏了这步,故无 fitText 也非路径无关自包含)。
- **通用性**：✅ 单管线,无 LibreOffice/PyMuPDF。60 页基准稿重建 0 unreconstructed、产物自包含(0 悬空 skill 引用)、fitText 已注入;`rerender-deck.py` 端到端经 canvas_finish 重渲通过;7 测试过。**教训：删一条管线前先查它有没有被复用的"中性收尾件"——本例 fitText/打包就被 rerender 与翻译 canvas 分支依赖,无脑 rm 会连带炸掉。**

## 待办 / 已知有损（按优先级）

- **T1 · autofit 文本收缩(部分解决)**：`post_process` 的 fitText 现已接入纯管线,**真正单行**超框文本框在浏览器侧 nowrap+scaleX 贴合(量真实 bbox,非估算)。**仍未解**:多行 / 含 `<br>` 的框 fitText 故意不动(C4:避免把合法换行段挤成一行再压扁),其横向溢出仍 spill(overflow visible,不裁切但越界)——60 页基准稿实测残留 13 页此类横向溢出,**全是 overflow:visible 无纵向裁切**。下一步候选:对"在自然换行宽度下 scrollWidth 仍 > clientWidth"的框(即真·不可换行/源 nowrap)也施加 scaleX(合法换行框 scrollWidth≈clientWidth 不会被误缩,绕开 C4 陷阱)。
- **T4 · 图片裁剪 `a:srcRect`**：未提取，整图贴入 bbox（可能比原稿多出被裁掉的部分）。
- **T5 · 占位符字号继承链**：run 无显式字号且为占位符时，未沿 layout/master 继承，回退默认。
- **T6 · 自由形状 FREEFORM**：有填充的按 bbox 矩形近似（丢自定义几何）；无填充的跳过。复杂图标可能走样。
- **T7 · 径向渐变 / 渐变微调**：仅线性渐变；radial、lumMod/shade/tint/alpha 未处理。
