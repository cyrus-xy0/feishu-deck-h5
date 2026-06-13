# ⚠️ 冻结版式清单 — F-305 «raw unless ceremonial»(2026-06-12)

> 给维护者的面包屑。**不参与渲染**(fragment loader 只按 `*.fragment.html` 精确名
> 加载,本 `.md` 不会被当版式)。放这里是因为模板引擎(`render-deck.py` 的
> `render_template`)是自定义 regex 渲染器,**没有注释机制** —— `{# #}` / `{{! }}` 会
> 原样泄漏、HTML 注释会渲进客户可见输出,所以不在各 fragment 里逐个塞 DEPRECATED 注释。

## 立场

正文 schema 版式**已冻结**:schema 只为【仪式页】(cover / section / agenda /
quote / end)与【机制页】(raw / canvas / iframe-embed / replica)保留;**正文内容
一律 `layout:"raw"`**(模型自由排版,更丰富、各页更不同)。详见
`docs/F-305-RAW-UNLESS-CEREMONIAL-2026-06-12.md`。

## 冻结的 fragment(仍为存量 deck 渲染,别删;新页别再用)

| layout | fragment 文件 |
|---|---|
| content(全 variant) | `content-3up` · `content-2col` · `content-before-after` · `content-blocks` · `content-matrix` · `content-story-case` |
| stats(全 variant) | `stats-row` · `stats-hero` · `stats-waterfall` |
| flow(全 variant) | `flow-process` · `flow-swim` · `flow-timeline` · `flow-tree` |
| chart | `chart` |
| table | `table` |
| arch-stack | `arch-stack` |
| image-text | `image-text` |
| logo-wall | `logo-wall` |

## 三条铁律

1. **不删、不改渲染逻辑** —— 存量 deck 重渲必须零回归。
2. **新页用 `layout:"raw"`** —— validator `R-LAYOUT-DEPRECATED`(warn_soft · advisory ·
   永不阻塞,连 `--strict` 也不升级)会提醒用了冻结版式的**新页**(scope 内才报)。
3. **保留的(不在此表)**:`cover` / `section` / `agenda` / `quote` / `end`(仪式)+
   `raw` / `canvas` / `iframe-embed` / `replica`(机制)。

> 2026-06-12 同批退役了反向规则 `R-RAW-LOOKS-SCHEMA`(它劝 raw 卡片页回退 content
> schema,与本立场冲突)。
