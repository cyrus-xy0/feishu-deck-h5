# F-374 · 投屏放映窗里有 demo 动画(iframe)时,演示者模式「操作不了」

> 状态:**DONE 2026-06-29** · 归属:`assets/feishu-deck.js` / `assets/feishu-deck.css`
> 报告:同事——「投屏的时候选择演讲者模式,投屏放映窗口,如果窗口页面里面有 demo
> 动画,演讲者模式那部分是不能操作的。」

## 现象

演讲者按 `P` 进演示者模式,点 📺 打开**放映窗(`#proj` 跟随窗,拖到投影屏给观众
看)**。某页内嵌一个**交互式 demo**(iframe-embed / phone-frame 原型 / 在线 H5)。
演讲者一旦**点进 demo** 驱动它,之后想翻页 / 操作就「不动了」——按 ←/→/Space/`P`
全都没反应。

## 根因(两条,同一个根)

1. **焦点被 demo `<iframe>` 吃掉 → 键盘全死。** deck 的全部键盘控制(翻页 ←/→/
   Space/Enter、`F` 全屏、`P` 演示者、`Esc`)只挂在**父文档 `document`** 的一个
   `keydown` 监听上。点进 demo iframe 后,焦点进入 iframe,**iframe 内的 keydown 不会
   冒泡到父 `document`**(浏览器同源/跨源都如此)→ 所有快捷键失效。
2. **放映窗没有屏上翻页控件。** `#proj` 跟随窗是 kiosk(`.is-kiosk` 把 deck 自带底部
   控制条藏了),原来**只有一个「✕ 关闭放映窗」按钮**。于是键盘一被 demo 吞,放映窗
   就**没有任何**可点的翻页入口 = 彻底卡死,正是「演示者那部分不能操作」。

## 修法(收敛到「屏上控件 + 双向同步」,**不**碰 demo 的键盘)

> 设计取舍见下「为什么不做键盘转发」——这是对抗式审查驱动的关键决策。

### 1. 放映窗(`#proj`)补全屏上控制条 —— prev / next / close(主修)
跟随窗的 on-body 控件从「只有关闭」升级为**控制条**(`‹上一页 / 下一页› / ✕关闭`)。
鼠标永远能翻页,**与 demo 是否抢焦点无关**——这对**同源和跨源 demo 都管用**,是唯一
普适的出路。控件挂在 `body`(不在 `.deck-ui` 内)所以 `.is-kiosk` 不藏它;
`z-index 2147483646` 所以 demo 盖不住;平时 `opacity .18`,**hover 或键盘聚焦**(`focusin`)
才显——它是 kiosk 窗里唯一的导航,Tab 用户必须能看见(a11y)。翻页用 `goTo(...,false)`
**保住 `#proj` hash**(改成 `#N` 会在 reload 时丢 kiosk 模式)。

### 2. BroadcastChannel 升级为**双向同步**
原来「放映窗只跟随、永不主导」。现在放映窗用控制条翻页时,经 `__fsOnNav` →
`broadcast` 同步回讲者视图,两边不脱节。三道防护保证收敛 + 不误伤:
- **`inSession()`(=`isFollower || projAlive()`)同时闸发/收** → 只有放映窗或「开了
  放映窗的 leader」参与同步;同一 deck 开两个**普通**标签页**互不同步**。
- **`onRemoteGoto` 的 `idx===currentIdx()` 守卫** → 已在该页就不动。
- **`applyingRemote` 抑制回声** → 因为别人通知我而执行的 goto **不再回播**;否则两窗
  同一瞬间被驱动到不同页会**无限 ping-pong**(对抗审查 F4 实测复现了这个 livelock)。

### 3. CSS 保险
`.fs-presenter`(讲者视图浮层)`z-index` 2147483000 → 2147483646,杜绝主窗里设了超高
z-index 的 demo 盖住演示者控件。

## 为什么**不**做「同源 demo 键盘转发」(关键决策)

初版曾对**同源** demo iframe 的 `contentDocument` 再挂一份键盘处理器,让点进同源 demo
后 ←/→/`P` 仍能翻页。**对抗式多视角审查(24 个 agent / 4 视角 / 逐条对抗验证)判定这
是真回归并实测复现**:转发会对 demo 内按下的 ←/→/Space/Enter/Backspace 调
`preventDefault()` 并翻页 → **一个交互式 demo(键盘游戏 / 聚焦的 `<button>` 用空格触发 /
方向键画布)会丢掉这些键**(实测:聚焦 demo 按钮按空格,按钮不触发、幻灯片却前进)。
还附带 `load` 监听器累加、未绑 `signal`、嵌套 iframe 不覆盖等问题。

权衡后**整段移除键盘转发**:键盘留给焦点所在处(demo 要键盘就给 demo,这是浏览器标准
行为),「操作不了」由**屏上控制条**解决(鼠标普适,§1);点回 deck 区域键盘即恢复。
这样收敛后改动更小、零回归、对同源/跨源 demo 一致——对维护者也更好 review。

## 验证

- **Playwright 端到端**(headless,http 源以启用 BroadcastChannel/真 `window.open`)忠实
  复现同事场景,**13/13**:① 聚焦 demo 时 deck **不**抢键盘(无劫持回归)、焦点离开 demo
  键盘即恢复;② 两个普通标签页互不同步;③ 放映窗以 follower 开、**有 prev/next/close
  控制条**、落在 leader 当前页;④ leader↔放映窗双向同步;⑤ 放映窗翻页后**保住 `#proj`
  hash**;⑥ **demo 抢了键盘焦点时,放映窗屏上「下一页」仍能翻页**(核心修复)。
- **对抗式代码审查**(workflow `f334-adversarial-review`,24 agent / 17 条 confirmed):
  驱动了「移除键盘转发」(F2 medium 回归)+ 修 `#proj` hash 污染(F1/F3 cross-window/
  regression)+ 控制条 a11y 聚焦可见(F4/F5)+ `applyingRemote` 防振荡(F4)。
- **反向对照**:根因实验在**未修改 main** 上证实——聚焦 demo iframe 内按 →,deck 不翻页
  (键盘被 iframe 吞)。
- 真实 `examples/sample-deck.html` 冒烟:翻页+演示者+Esc,**0 控制台/页面错误**;
  `examples/sample-deck-inline.html` 已 `build.sh --inline` 重生成,内联 JS 与最新一致。

## 已知边界(LOW,未在本工单处理,记录在案)

- **键盘留在 demo**:点进任何 demo iframe 后,键盘归 demo;翻页用屏上控件或点回 deck。
  这是刻意的(见「为什么不做键盘转发」),非缺陷。
- **跨源 demo**:父页读不到其键(浏览器安全),只能靠屏上控件——Web 平台限制。
- **同一 deck 两个独立演示者会话**:BroadcastChannel 名是全局 `fs-deck-present`,若在同
  浏览器**同时**开两套 leader+放映窗(极罕见),会互相串导航。可后续用会话 token 限定
  配对;当前不值当增复杂度。
- 纯 CSS/JS 的 demo「动画」(非 iframe)本就不抢键盘,不受此 bug 影响,本修复对其无副作用。
