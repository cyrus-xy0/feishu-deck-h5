# deck-log · deck 制作全过程日志

把"一份 deck 是怎么一步步做出来的"完整记录下来,**平行存放在 `log/`,绝不进 `out/`**。
目的:① 同学看完能完全还原制作过程 ② 我能据此诊断"哪些 bug 是 skill 本身该修的"。

## 它长在哪
```
runs/<deck>/
  out/                       成品(本工具不碰)
  log/                       ← deck-log 的地盘
    journal.jsonl            唯一真相源 · append-only · 每行一个事件
    inputs/                  你给的原始附件(brief / 参考图 / .thmx)
    screenshots/vNNN/sNN.png      每版整套:每页一张 1920×1080
    audits/vNNN.json         该版本 check-distribution 的机读结果
    making-of.html           ← 渲染出的"制作纪录片",双击即看,可分享
```
> 只留**截图**,不再冻结"deck 当时的 html"(旧的 `versions/vNNN/snapshot.html` 已移除——
> 那份绝对 `<base>` 副本换机/分享就打不开,价值低)。要回看某版长啥样直接看 `screenshots/`。

## journal.jsonl 事件 schema
每行一个 JSON 对象,`t` 是类型,所有事件都带 `ts`。

**「我的输入 + Claude 原始回复」不写进 journal** —— 它们本就完整躺在会话 transcript
里(`~/.claude/projects/<slug>/<sid>.jsonl`)。`render` 时直接从 transcript 现捞这一段
(纯文件读,0 model token,且永不重复、保 journal append-only 纯净)。`init` 记下当时的
transcript 路径与起点 `start_ts`,render 取其后的回合。

journal.jsonl 里只放**精挑的 curated 事件**:

| `t` | 谁写 | 关键字段 | 含义 |
|-----|------|---------|------|
| `session` | `init` | `title`,`transcript`,`start_ts` | 这次制作的开始 + 绑定的会话 transcript |
| `summary` | 我(可选) | `n`,`msg` | 给第 n 回合补一行精炼摘要(渲染时折进该回合) |
| `version` | `snapshot` | `v`,`label`,`slides[]` | 一个版本:整套截图(每页 png) |
| `audit` | `snapshot` | `v`,`findings[]` | 该版本的几何/校验发现 |
| `problem` | 我 | `slide`,`msg`,`i_said` | 观察到的问题(`i_said`=我当时的原话吐槽) |
| `fix` | 我 | `resolves`,`msg` | 修复了某个 problem |

render 时把 transcript 捞出的 `turn`(`n`/`input`/`output_raw`)和上面这些事件按 `ts`
并成一条时间线。`problem` / `fix` 是 **bug 诊断的因果链金矿**:输入→决策→改动→截图→
校验发现→我吐槽→修复。

## 用法
```bash
DL="python3 ~/.claude/skills/feishu-deck-h5/log-tool/deck-log.py"

$DL init     <deck-dir> --title "客户案例"      # 开工时:搭骨架 + 记下当前 transcript + 设为活跃 deck
$DL snapshot <deck-dir> --label "首版骨架"      # 每出一版:截全套图 + 跑校验 + 自动刷新 making-of
$DL snapshot <deck-dir> --slide 4              # 只改了第4页?秒级只重截那一页(覆盖最新版),自动刷新流水
$DL event    <deck-dir> --type problem --slide 4 --msg "数据页太挤" --said "第4页太挤了"
$DL event    <deck-dir> --type fix --resolves "数据页太挤" --msg "改 2×2"
$DL event    <deck-dir> --type summary --json '{"n":2,"msg":"封面副标题放大;数据页改 2×2"}'
$DL turns    <deck-dir>                          # 调试:预览从 transcript 捞到的回合
$DL render   <deck-dir>                          # 收尾:journal + transcript 回合 → making-of.html(--inline 单文件)
$DL diagnose <deck-dir>                          # 把 problem/audit digest 给大模型,问哪些是 skill bug

$DL on | off | status                            # 全局开关(默认开;off 写 ~/.claude/deck-log.off)
```
`<deck-dir>` = 含 `out/` 的那个 run 目录;传 `out/` 或 `log/` 也能容错识别。

## 无 hook · 怎么拿到输入/回复
**不挂任何常驻 hook。** `init` 时自动定位当前会话的 transcript(`~/.claude/projects/*/`
下最近改动的 `.jsonl`),把路径与 `start_ts` 记进 `session` 事件;`render` 时读它、取
`start_ts` 之后的记录,过滤掉斜杠命令 / `<task-notification>` / `<system-reminder>` 等
非人类输入,把每条真输入配上紧随的 assistant 文本成 `turn`。
- 自动找错了或跨了会话(compaction/resume 换了 transcript 文件):`init --transcript <path>`
  显式指定,或 `render` 前手动改 journal 里 session 事件的 `transcript`。
- `deck-log off`(写 `~/.claude/deck-log.off`,凌驾一切)→ render 不再捞 transcript,
  只渲染版本/问题/修复。`~/.claude/deck-log.active` 仅供 `status` 查看当前活跃 deck。

## Token 成本
输入/回复在 render 时从 transcript 文件读取(**0 model token**);截图落磁盘**不进上下文**;
snapshot/render 只回一行状态。整份日志 ≈ 一次 deck 制作的 0.3–1%。
`diagnose` 会读 journal + transcript 回合(含原始回复),**按需手动触发**,建议丢给 subagent 跑。
