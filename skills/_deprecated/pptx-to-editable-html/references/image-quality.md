# 图像质量：清晰度、文字色、无文字底图

双背景架构的成像质量全靠 `bg`/`bgNotext` 两张图。常见三类毛病，各有一招根治。
全部脚本路径相对 skill 根目录，坐标都在 1920×1080 设计画布上（脚本内部会缩放，
不影响 manifest 坐标）。

## 1. 照片发虚 → 高分辨率重渲

**为什么**：整页是被当成**一张** 1920×1080 位图渲出来的，把内嵌的 4–6K 原始照片
一路降采样到页面分辨率，所以照片糊。

**怎么修**：`bg` 和 `bgNotext` 用**同一批源 PDF**在更高分辨率下重渲，再重新编码。
两张必须用**同一 width**，否则像素不对齐，脏区裁片（dirty-mask crop）会错位。

```bash
swift scripts/render_pdf.swift deck.pdf          ./work/bg     2880   # 或 3840
swift scripts/render_pdf.swift text-stripped.pdf ./work/notext 2880   # 同一 width！
```

重渲后 JPEG q88 编码（高分辨率 PNG 太大），再把 manifest 指向高清图：

```bash
sips -s format jpeg -s formatOptions 88 ./work/bg/page-001.png --out ./work/bg/page-001.jpg
# 或 Pillow: Image.save(out, 'JPEG', quality=88)
```

```bash
python3 scripts/make_manifest.py texts.json --out manifest.json \
    --img-base https://host/deck \
    --bg-pattern 'bg/page-{n:03d}.jpg' --notext-pattern 'notext/page-{n:03d}.jpg' ...
```

矢量 PDF 在 2880/3840 px 下是按原生矢量分辨率绘制的（不走插值），所以 width
就是唯一旋钮，不需要额外的 scale 因子或 `.high` 插值。`render_pdf.swift` 已覆盖
全部页、可调分辨率、输出 `page-{n:03d}.png`，无需另写渲染器。

## 2. 文字变白 / 不可见 → recover_colors.py

**为什么**：python-pptx 解析不出**主题色 / 继承色**（`solidFill` 指向
`schemeClr` 或来自 master/layout 占位符），`extract.py` 只能给 `color:null`。
build 把 null 当默认色，白底上的浅色文字就此隐形。

**怎么修**：拿现成的两张渲染图反推真实文字色——对每个文字框 diff `bg`（含文字）
与 `bgNotext`（无文字），diff 大于阈值的像素就是文字笔画，取含文字裁片里这些
像素的主导色，**只覆盖 color 为 null 或近白**的段落。颜色按 //12 分桶以合并抗锯齿
边缘。`bg`/`bgNotext` 支持 http(s) URL（自动下载缓存，12 线程）或本地路径。

**时机**：`make_manifest.py` **之后**、`build.py` **之前**跑——它读 manifest、写一份
补好颜色的新 manifest：

```bash
python3 scripts/recover_colors.py manifest.json --out manifest-colored.json
# 可选：--workdir ./work/cr  --diff-threshold 45  --canvas 1920x1080
# 输出: recovered colors: N paras across M boxes -> manifest-colored.json
```

然后 `build.py manifest-colored.json`。

## 3. 无文字底图丢图形 → 优先重渲，repair_notext_bg.py 兜底

**为什么**：生成无文字 PDF 时，如果把整层图形（不只是文字）都剥掉了，`bgNotext`
就会连**文字框外**的图形、装饰、形状一起丢——进编辑态背景就缺一块。

**首选修法（更干净）**：从一份**只剥文字、保留图形**的 PPTX/PDF 在高分辨率下重渲
无文字底图，图形天然保留。即第 1 节里的 `text-stripped.pdf` 路线——剥得对，就没这毛病。

**兜底修法**：图形仍然丢了，再用 repair。逐页 diff `bg`/`bgNotext`，把每个文字框
矩形和媒体矩形涂黑，若**框外**仍有变化的面积（diff>40 的像素）超过整页 0.8%，
就判定该页"无文字渲染掉了图形"。对被标记的页，重建 `bgNotext` = 含文字底图，
仅在**每个文字框矩形**位置贴上无文字裁片（框外图形回来、框内文字依旧消失）。

```bash
python3 scripts/repair_notext_bg.py manifest.json
# 可选：--workdir ./work/repair  --out-dir <workdir>/out
#       --area-threshold 0.008  --diff-threshold 40  --canvas 1920x1080
# 输出: 被标记页列表 + page-{n:03d}.png（不上传）
```

**关键——文件按页号编号，不按 slide 索引**：删页/跳页后 slide 索引 ≠ 原始页号，
所以输出文件名取自 `bg` 文件名里正则 `(?:page|slide)-0*(\d+)` 解析出的页号。
修完**上传**这些页，再把 manifest 的 `bgNotext` 指向它们——后续 swap 步骤才对得上号。