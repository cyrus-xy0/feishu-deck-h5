# pptx-to-html · 问题→修复日志

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

## 待办 / 已知有损（按优先级）

- **T1 · autofit 文本收缩**：PPT「溢出时缩小字号」未模拟，超长文本按写死字号渲染会溢出框。keynote 技能也主动放弃了（估算不准）。暂不处理，溢出靠自然换行。
- **T4 · 图片裁剪 `a:srcRect`**：未提取，整图贴入 bbox（可能比原稿多出被裁掉的部分）。
- **T5 · 占位符字号继承链**：run 无显式字号且为占位符时，未沿 layout/master 继承，回退默认。
- **T6 · 自由形状 FREEFORM**：有填充的按 bbox 矩形近似（丢自定义几何）；无填充的跳过。复杂图标可能走样。
- **T7 · 径向渐变 / 渐变微调**：仅线性渐变；radial、lumMod/shade/tint/alpha 未处理。
