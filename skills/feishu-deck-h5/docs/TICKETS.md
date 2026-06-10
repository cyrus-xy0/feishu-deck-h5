# 工单编号登记处 (TICKETS)

> **下一可用号 = F-293**

这是 `feishu-deck-h5` skill **唯一**的工单编号登记处。F-255..F-292 已分配。
F-292 = F-256 视觉闸门调优(本轮用掉)。F-001..F-254 散落在历史审计文档里
(`docs/archive/` 下各 `AUDIT-*.md` / `*-GAP-*.md`),早期没有集中登记,因此存在
**撞号**(同一个号在不同文档里指两件不同的事)。下表把已知撞号一次性钉死。

## 一句话规矩

- **新工单一律来这里领号**:取「下一可用号」,在本文件登记一行(号 + 一句话 + 归属文件),
  然后把「下一可用号」+1。不要再凭印象在审计文档里直接起号。
- **历史审计文档**顶部各加一行指针:`> 工单号以本文档为准已不可靠,新号见 docs/TICKETS.md`,
  把读者引回这里。已撞号的旧文档不改正文(改不动也没必要),只在本表标注两义。

## 撞号对照表(历史遗留,勿复用这些号)

同一编号在不同历史文档里有两个(及以上)互不相干的含义。引用旧工单号时**必须连文件名一起说**
(例如「F-40(AUDIT-LIFT-IMPORT)」而非裸「F-40」),否则会指错。

| 号段 | 含义 A | 含义 B | 其它含义 |
| --- | --- | --- | --- |
| **F-36 ~ F-39** | 产品级路线图工单(`docs/archive/REPRODUCIBILITY-GAP-2026-05-30.md` 引 `AUDIT-2026-05-29.md` **detail 段**):F-36=HTML→PPTX 桥 / F-37=硬挂载门 / F-38=WYSIWYG 太浅 / F-39=协作评审。**注**:AUDIT-2026-05-29 自己的摘要表(93–94 行)与 detail 段编号就不一致,**一律以 detail 段为准**。 | — | — |
| **F-40 ~ F-46** | `lift-slides.py` / 导入路径工单(`docs/archive/AUDIT-LIFT-IMPORT-2026-06-01.md`):F-40=`--shake` 漏 `[data-page=N]` 组件 CSS / F-41=少一个 `</div>` / F-42=reconcile 成套工具 / F-43=lift 保设计换文字路由 / F-44=安全 text-swap / F-45=lift 资产带不全 / F-46=workflow args 字符串到达。 | 与上一行 F-36~F-39 不重叠(两个号段相邻但各自连续);**真正撞号的是下面 F-80~F-85**。 | — |
| **F-80 ~ F-85** | `lift-slides.py --to-html` / `--preview` 一族(`docs/archive/AUDIT-LIFT-IMPORT-2026-06-01.md`):F-80=`--to-html` lift 进无-deck.json 老 deck / F-81=`--preview` 一条命令出判断 / F-82=raw 页 data.html 契约固化 / F-83=探测命令默认 `--json` 治截断 / F-84=`--to-html` 内建闭环 / F-85=`import-html-slide.py` Mode B 被取代(并入 F-80)。 | edit-mode 安全/正确性 bug(`docs/archive/AUDIT-2026-06-01-skill-review.md`):F-80=getTextLeaves 误使容器可编辑 / F-81=富 HTML 粘贴存储型 XSS / F-82=undoStack 与 save 序列化不一致 / F-83=FS 写失败静默降级 / F-84=process step 双 ::after 箭头 / F-85=`centerSlideInCanvas` 跳过 `position:absolute`(R-VIS-BAND-COLLIDE 根因)。 | **F-85 第三义**:R-DOC-INTEGRITY 整文档完整性闸门(`deck-json/tests/test_doc_integrity.py` 模块 docstring 把该规则标作 F-85,2026-06-03)。 |

> 归属规律:`AUDIT-LIFT-IMPORT-2026-06-01.md` 自己声明「续号 F-50 起 / F-40~F-49 撞号请并入」,
> 是撞号的主源头;`AUDIT-2026-06-01-skill-review.md` 的 F-80~F-85 与它**同日各起一套**导致正面冲突。
> 这正是设此登记处的原因。

## 已裁决(WONTFIX / DONE)

| 号 | 含义 | 裁决 |
| --- | --- | --- |
| **F-36 / R-01** HTML→PPTX 导出 | 把 HTML deck 导出成 `.pptx` 文件 | **WONTFIX** · 2026-06-10 用户明确:北极星 = HTML deck,**不再需要 PPT,pptx 导出以后也不立项**;别再提此方向。 |
| **F-37 / R-02** 托管创作面 / 硬挂载门 | 非工程师托管创作入口 | **WONTFIX** · 同上,「PPT 替代」产品方向整体关闭。 |
| **F-292** F-256 视觉闸门调优 | 死代码降 advisory + 存量/imported 豁免 | DONE · commit `8a54484` |
