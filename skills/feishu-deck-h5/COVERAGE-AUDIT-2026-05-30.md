# 检查覆盖盲区审计 · 2026-05-30

> 缘起:在青岛啤酒(外来手搓 raw deck)的逐页修复中,用户一条条人工指出布局/字号问题。
> 提问:**把技能现有的全部检查叠加在一起,能不能自动抓住这些?抓不到的,技能要补什么?**
> 方法:6 个 agent 并行盘点了 `validate.py` / `_validate_audits.py` / `visual-audit.js` /
> `feishu-deck.js`(auto-balance)/ `references/validator-rules.md` / `SKILL.md` 的每一处检查,
> 再把它们叠加,对照本会话踩到的 11 个真问题逐条判定(源码逐条核对)。

## 总结论(扎心版)

**叠加后也搞不定。** 可靠兜住 **0** 条,部分(partial)**6** 条,完全漏(gap)**5** 条。

最致命的一条是**流程缺口而非规则缺口**:**auto-balance 是运行时 JS,青啤 raw deck 实测 0 行
`data-fs-autobalanced`、根本没跑** —— 等高卡不长高 / 不居中的自动修复,在这份 deck 上从一开始就是死的。
(raw deck 没经 `rebundle-import.py` 重新内联当前框架 JS,auto-balance 就不存在。)

## 覆盖矩阵(P1–P11 = 本会话真问题)

| 问题 | 判定 | 为什么(源码事实) |
|---|---|---|
| P1 正文/轴标字号 <24 | partial | 长句兜得住(R06 body-floor + R-VIS-BODY-FLOOR);**短标签/轴标被 `visual-audit.js:588 if(directText.length<8)return` 放过**;SVG `<text>` 内字号所有渲染检查跳过 |
| P2 写死高度/等高网格框不长高→卡溢出 | partial | R-VIS-CARD-OVERFLOW 抓**有子元素**的可见溢出(分支 a' 要求 `el.children.length>0`);**纯文本叶子溢出是明文盲区**;auto-balance 本可 un-stretch 但**没跑** |
| **P3 内容顶到/重叠标题** | **gap** | **没有任何检查量「标题↔正文纵向间距」**;R-VIS-TITLE-POSITION 只比 .header top 是否 61±8;R-OVERLAP 只比同容器兄弟,标题在 .header、正文在 .stage **跨容器比不到** |
| P4 没整体居中/底部死留白 | partial | R-VIS-BALANCE 是 **warn 不阻断**,阈值 >150px slack + >120px 不对称才触发,中度偏移漏;check-distribution.py L1 非硬闸、手动 |
| **P5 同角色字号不一致(18 与 22 混)** | **gap** | **完全没有 peer-consistency 检查**;R-VIS-TIER 明文:两 sibling 一个 24 一个 28 各自合法、mismatch 不可见;两值都 ≥24 则彻底放行 |
| P6 单字孤行 | partial | R-VIS-ORPHAN 在,但 **warn 级 + 仅 CJK≥4 字 + SVG/iframe/mock 内不查**;hero 版式主标题 CJK cap 放宽 |
| **P7 同组框间距不相等(28↔8px)** | **gap(近似)** | 只有手动工具 check-distribution.py L2 沾边,**不在硬闸 + 阈值 >120px**,28/8px 小量级漏;R-VIS-ALIGN 只查等高不查 gutter |
| P8 overflow:visible 溢出顶进下一行 | partial | 同 P2,card-overflow a' 要求子元素;纯文本叶子无碰撞对象时漏;R-OVERLAP 限白名单容器 |
| **P9 整页截图当正文,图里字 8-10px** | **gap** | 字号检查全基于 computed DOM font-size,**够不到栅格图像/iframe 内像素文字**(青啤 79 `<img>` / 213 bg-image / 5 iframe);UI1 只 warn「别贴截图」从不量可读性 |
| P10 构图失衡/空壳面板 | partial | R-VIS-BALANCE dead-band **仅纵向**,横向 3-up 天然豁免(#36 右半空壳漏);warn 级 + hero 整页豁免 |
| **P11 hero/封面字号偏小** | **gap** | **检查方向反了**:R-VIS-TIER 只判「在不在 HERO_SIZES 白名单」,不判「该 100 却 82 偏小」;hero 版式上 body/label-floor 直接 `isHeroLayout return` |

## 五个结构性根因(为什么怎么叠都漏)

1. **auto-balance 是运行时 JS,raw deck 没 re-bundle 就 0 行没跑**(P2/P4 自动修复失效)。
2. **R-VIS-BODY-FLOOR 的「≥8 字」硬门槛**系统性放过所有短标签/轴标(P1/P5 短文本)。
3. **card-overflow 可见溢出分支要求有子元素**,纯文本叶子溢出明文盲区(P2/P8)。
4. **静态规则看不到几何/重叠/渲染字号**;跨容器(标题↔正文)重叠与间距无人认领(P3)。
5. **多个能沾边的几何检查(check-distribution L1/L2/L3)不在硬闸、是手动工具**;BALANCE/CROWD/SLACK 全 warn 级,非 `--strict` 不阻断。

## 修复 backlog(按性价比;触发 = 青啤修完一起改)

### 先做(small,堵流程根因)
- [ ] **R-AUTOBALANCE-PRESENT**(`validate.py` 硬闸):deck 缺 `balanceSlide` 指纹 → err,逼 raw/legacy deck 必须 `rebundle-import.py` 重新内联后才放行。**否则 auto-balance 永远是死的。**
- [ ] **UI1 warn→err**(或 `--strict` 必升):内容版式上非品牌 `<img>` / 含 UI 特征 bg-image 强制改 HTML 重建,从源头堵 P9。

### 再做(medium,补检查盲区)
- [ ] **R-VIS-TITLE-GAP**(P3,`visual-audit.js`):量 `:scope>.header` bottom → `.stage` 首内容块 top 间距,<24 或负(重叠)→ err;并让 R-OVERLAP 跨 header/stage 做一次 bbox 相交。
- [ ] **R-VIS-PEER-SIZE**(P5,`visual-audit.js`):同平权祖先(复用 R-FOCAL 的 PARALLEL_PATTERN_CONTAINERS)或同卡内同语义类(desc/cbody…)的 sibling,computed font-size 不一致(容差 1px)→ warn。
- [ ] **短标签 floor + 下钻 SVG `<text>`**(P1/P5):**不删 8 字门槛**(删了图标/单位数字误报),补一条 1–7 字非 chrome 短标签下限(<18 → warn);并让渲染检查能读 SVG `<text>` 的 computed 字号。
- [ ] **card-overflow 改 `Range.getClientRects()`**(P2/P8,`visual-audit.js:284`):去掉 `el.children.length>0` 依赖,用文本叶子自身行盒 union bottom vs 父 border-box bottom(沿用 orphan 已有 Range 量法),纯文本叶子溢出也能测,且避开大字号 line-box 假阳。
- [ ] **gutter 相等性**(P7):把 check-distribution.py 的 L2-DEADBAND/L2-CROSSAXIS/L3-BOXROW 提进 `validate.py` 硬闸,阈值改相对(max gap >2×min gap)抓 28↔8px 量级;R-VIS-ALIGN 增「等 gutter」维度。
- [ ] **R-VIS-HERO-FLOOR**(P11):cover/section/big-stat 的 hero 主元素 computed < 该 layout 规定 hero 尺寸(读 layout token,如封面 ≥100)→ warn;方向从「白名单」改「尺寸下限」。
- [ ] **R-VIS-BALANCE 横向 dead-band / 单侧空壳**(P10):当前仅纵向;或把 L1-UNDERFILL-H 提进硬闸。

### 大工程(large,可选但是治本)
- [ ] 给 `feishu-deck.js` 的 **balanceSlide 加 grow-box 能力**(复用 `grow-box-fit.py` 逻辑):auto-balance 真能把写死高度的框「长高」容纳大字,而不只 `align-self:center`。这是 P2 的运行时治本。

## 配套:本会话验证的方法(青啤逐页修用的,也该进 doctrine)

逐页「**量真因 → 改对杠杆 → 复测全清单**」:
- 卡溢出 ≠ 整页溢出;框不长高常是被兄弟卡/写死行高卡死(→ `grid-auto-rows:max-content` / 拉高行)。
- 居中算可用区(标题下方),`(可用−内容)/2`;**transform 被进场动画占用**,移动内容用 `top/bottom`,别用 transform。
- 等间距:同组框 gutter 应相等(卡片左右 gap == 到下面框的 gap)。
- 死规矩:标题/副标题不动。
- **复测要查「可见溢出 + 重叠 + 孤字」,不只 `overflow:hidden` 裁切**(本会话漏过)。
