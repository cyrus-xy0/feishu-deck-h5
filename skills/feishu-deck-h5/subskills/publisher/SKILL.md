---
name: publisher
description: |
  Publish a user-confirmed feishu-deck-h5 HTML deck to Feishu/Miaobi Magic Page.
  Use after explicit user confirmation. Runs only publish artifact integrity checks
  (asset availability/hosting, residual local/data refs, post-publish delivery
  self-check), not deck-validator visual/design gates. Do not fix, render,
  rehearse, or ingest decks into feishu-slide-library.
---

# publisher

目标:把用户已经确认的 HTML deck 发布到飞书妙笔 / Magic Page,生成可访问链接。
publisher 只负责“发布”,不负责入库。将成品 HTML 推到
`FuQiang/feishu-slide-library` 的动作属于 `subskills/importer/SKILL.md`。

Inline freshness rule: when this subskill is not running as a separate
multi-agent worker, reread the current upstream files before publishing. Do not
rely on cached chat summaries or earlier reads of the confirmed HTML artifact or
publish metadata.

## 职责边界

- **发布**:默认将确认后的 `.html` / `.htm` 发布到 Feishu/Miaobi Magic Page,
  访问 URL 必须是 `https://magic.solutionsuite.cn/html-box/<id>` 形态,输出
  `magic-page-publish.json`、`cloud-publish.json`、`MAGIC_PAGE_PUBLISH.md` 和
  `publish-manifest.json`。
- **妙笔资产准备**:发布前(调上传 API 之前)先跑**资源体积体检**
  `assets/magic-page-preflight.py`(delivery-8):一次性扫描所有本地 / `data:` /
  远程资源,把**超过妙笔单资源上限(64 MB)的资源一次全部报出来**,不再像过去那样
  在上传 API 处一个一个反应式踩限制(本地视频拦一次→压一次→重校验→重发→远程视频又拦…
  把一次发布拖成 ~40 分钟的串行循环)。默认对**超限视频自动压成可发布画质**
  (降到 1920×1080 以内、30fps、去音轨、H.264;小窗口播放视觉无损);压不下去的、
  非视频的超限资源、或本机没有 ffmpeg 时,**发布直接失败并给出 `MAGIC_PAGE_PREFLIGHT.md`
  报告 + 精确修复命令**,一轮修齐。`--no-compress-oversized` 关掉自动压缩(改为只体检+给命令),
  `--magic-max-resource-bytes` 调上限。
  体检后再把 CSS/JS 内联为临时 HTML,把本地 / `data:` / 远程资源传妙笔 TOS 改托管 URL,
  最后调发布 API。**框架运行时 + 每页 CSS 默认保持内联**(delivery-9 / `--keep-inline-code`,
  publisher 默认开):外置成哈希命名的托管 JS 会让发布字节的「运行时存在」检查认不出
  (误判 runtime 缺失,过去每次发布都要手动绕一轮);代码 <0.5 MB,留内联不会触碰请求体上限,
  只有重资源被外置。**但发布前必须本地检查 Magic Page HTML 正文字数上限**
  (默认 900000 字符,可用 `--magic-max-html-chars` 调整):若默认内联版超限,
  publisher 在调用 Magic Page API 前自动重跑一次外置代码打包,写出
  `PUBLISH_SIZE_REPORT.md`,再发布瘦身后的 `magic-page-ready.html`;不得先撞远端
  413 再手动重发。需要主动外置代码时仍可用 `--externalize-inline-code`。
  **未托管依赖扫描跳过 `<script>` 块与注释**:JS / 注释里出现的 `url()` / `URL()` /
  `location.href` / `createObjectURL` 不再被误判为「未托管资源」(过去也是每次发布手动改写绕过)。
  最终发布物不得依赖本地路径、第三方外链或 `data:` payload;只靠发布链接即可完整使用。
- **iframe / 原型发布策略**:不要默认把 iframe 替换成截图。按三档处理并在最终回复说明采用了哪档:
  1. **保留 iframe**:若 `src` 是可嵌入 HTTPS 页面,且无 `X-Frame-Options` / CSP frame 限制,
     直接保留;发布前用 `curl -I -L` 快速看 `Content-Disposition`、`X-Frame-Options`、CSP。
  2. **本地子页面走 FaaS HTML 代理**:若 iframe 指向本地 prototype / 子 HTML,不要直接把
     HTML 上传到 TOS 后作为 iframe src,也不要默认把子页发布成另一个 Magic HTML Box 再嵌套。
     publisher 会先处理子 HTML 内部资源(图片/视频/字体/`data:` 等上传 TOS),再把处理后的
     子 HTML 上传 TOS,最后发布/更新一个 Magic FaaS 代理用 `text/html; charset=utf-8`
     返回它,主 deck iframe 改成
     `https://magic.solutionsuite.cn/api/faas/<record_id>?p=<slug>`。这样避免 TOS
     `Content-Disposition: attachment` 导致 iframe 空白/下载,也避免 Magic HTML Box 套
     Magic HTML Box 的二次 sandbox 触发 `localStorage` 等交互报错。
     单文件 bundler 超过 Magic 字符上限时,把大 vendor 上传 TOS、业务脚本展开/内联,避免
     `Blob` / `createObjectURL` / `data:image` / 上传组件残留。
  3. **静态 srcdoc / 截图兜底**:只有当 Magic 页面套 Magic 页面黑屏、iframe 内脚本在 Magic
     srcdoc 环境不执行、或目标禁止嵌入时才降级。优先导出无脚本静态 DOM 放入 `srcdoc`
     (仍是 iframe 内容);最后才用截图。降级必须说明原因,不要说成“完整保留交互”。
     用 `subskills/publisher/freeze_srcdoc.py --html <prototype.html> --out <static.html>
     --viewport 480x1000 --screenshot <png>` 生成无脚本兜底 HTML,确认 `banned_found`、
     `failed_requests`、`bad_responses` 为空后再嵌入。
- **发布完整性检查**:publisher 不跑 `deck-validator` / `check-only` 的视觉、设计、
  字号、复用质量门禁。发布门禁只检查即将发布的字节是否完整可访问:资源体积不超限、资源能被
  inline / 上传 / 托管、最终 HTML 不残留本地相对路径或 `data:` payload。这个口径对齐
  `feishu-slide-library` 当前入库准入:硬拦只拦资源可用性,样式 / 结构 / 视觉问题不阻断发布。
  资源重写只把 CSS 语义中的小写 `url(...)` 当资源引用处理,不得误改 JS 里的 `URL(...)`
  构造器。
- **单一发布目标**:publisher 只发布到 Feishu/Miaobi Magic Page;不得提供
  `--publish-target`、Miaoda fallback 或 slide-library 入库分支。
- **不入库**:不得调用 `feishu-slide-library` 的
  `bootstrap-library.py` / `ingest-package.py` / `confirm-ingest.py`,不得生成或确认
  slide-library PR,不得把“已发布”说成“已入库”。

## 前置条件

- 必须有用户明确确认“这就是最终发布物”。
- 不要求 `deck-validator` 通过结论。若用户显式要求“发布前质检/全量检查”,另走
  validator/check-only;不要把它混进默认发布链路。
- 默认发布前必须跑资源体积体检、Magic Page 资产准备、最终 HTML 引用完整性检查。
  `--allow-unaudited` 是历史兼容参数,不再绕过或启用任何发布质量门禁。
- 妙笔真实发布默认读取 `MAGIC_TOKEN` 或 `~/.magic-token`;域名默认
  `https://magic.solutionsuite.cn`,可用 `MAGIC_BASE_URL` / `--magic-base-url` 指定。
  如果本地没有 token,必须先要求用户提供 token,不得等到发布 API 阶段才失败。
  `--dry-run` 不需要 token,但仍必须执行资源体检、Magic Page 资产准备、大小门禁和
  引用完整性检查;它只把资产上传 / FaaS / 最终发布 API 替换成本地 dry-run URL。
- Magic Page 资源上传默认使用仓库内
  `skills/feishu-deck-h5/assets/magic-upload.js`,也可通过
  `FEISHU_DECK_H5_MAGIC_ASSET_UPLOADER` 或 `--magic-asset-uploader` 指定。
  默认 uploader 使用 `magic-upload-batch/v1` NDJSON 协议，在一个长驻 Node
  进程内有界并发上传资源与重写后的 CSS/JS，并校验每个资源的
  key、SHA-256 和返回 URL。不支持该协议的旧自定义 uploader 不会自动
  降级；只能在用户确认兼容需求后显式传 `--legacy-magic-asset-uploader`。

## 速度、幂等与恢复契约

- **普通发布不进入全仓门禁**:`PUBLISH` 只运行资源完整性、Magic API 与发布后自检。
  发布器/runtime 故障在同一未改包上最多复现一次,随后转 `PUBLISH_RECOVERY`:
  只跑 publisher 定向测试 + 当前 artifact replay,先交付 URL。1200+ 全仓测试只属于后续
  `MAINTENANCE` repository release,不得阻塞当前 Deck 交付。
- **冻结输入**:asset preparation 后、任何真实上传前,写
  `publish-snapshot.json` 和 `publish-snapshots/<content-id>/`;HTML、页面哈希和本地资源闭包
  进入内容寻址快照。发布中途 live run 发生变化也不得改变本次上传字节。
- **稳定发布工作区**:`--html` 默认使用 `publisher/<slug>-<source-path-hash>`,不再每次创建
  时间戳目录;同一来源会复用上次 manifest、FaaS record 和 Magic app 更新状态。
- **增量上传/断点续传**:默认使用 `runs/publisher/.magic-asset-cache-v1.json`,按
  `Magic base URL + MIME + SHA-256` 复用已上传 URL。批次部分失败时先 checkpoint 成功行;
  重跑只补 misses。自定义 uploader 默认禁用共享缓存,避免测试/第三方 URL 污染正式缓存。
- **FaaS 分片复用**:`magic-asset-faas.py` 按代码 SHA-256 复用未变分片;需要更新的分片最多
  4 路并发。FaaS 仍是 TOS attachment 的兼容兜底;上传服务若能直接返回
  `Content-Disposition:inline`,应优先跳过这一层。
- **增量自检**:首次发布检查前 N 页;已有成功 manifest 时自动检查封面、末页、变化页和相邻页
  (默认最多 5 页)。页面等待内层 deck `data-js-ready`、fonts loaded、images complete,不用固定
  sleep 猜加载完成。`--self-check-page N` 可显式覆盖。
- **SLO**:默认总预算 600 秒(`--publish-time-budget`);普通重复发布目标 ≤3 分钟,首次发布目标
  ≤5 分钟。每个子阶段写入 `publish-timing.json` / `PUBLISH_TIMING.md`;预算耗尽不再启动新上传
  子进程,而是报告慢阶段并路由 `PUBLISH_RECOVERY`。

## 标准命令

对一个 run 的确认产物发布:

```bash
python3 skills/feishu-deck-h5/subskills/publisher/publish.py \
  --task-id <runs-dir-name> \
  --title "<deck title>"
```

直接发布某个 HTML 文件:

```bash
python3 skills/feishu-deck-h5/subskills/publisher/publish.py \
  --html path/to/index.html \
  --title "<deck title>"
```

全链路 dry run,不真实发布、不写 TOS / FaaS / Magic Page:

```bash
python3 skills/feishu-deck-h5/subskills/publisher/publish.py \
  --html path/to/index.html \
  --title "<deck title>" \
  --dry-run
```

`--dry-run` 会写出 `MAGIC_PAGE_PREFLIGHT.md`、`PUBLISH_SIZE_REPORT.md`、
`PUBLISH_INTEGRITY_REPORT.md` 和 `magic-page-ready.html`;若最终发布字节仍残留
本地路径、`data:` payload 或超限资源,命令必须非零退出。

## 发布后自检 (F-285 · 最后一公里)

发布的最后一公里到拿到最终 URL 就结束了,但**没人以受众身份打开那个 URL** 确认字节真的活着:
断链 / 图 404 / 字体回落 / 关键页视觉走样,本地校验全看不见(validate.py 查的是本地字节,
不是接收服务器实际吐出来的东西 —— F-76 的图标 404 就是发布后才暴露)。所以发布成功、拿到
**最终 app_url** 后,`publish.py` 会自动再跑一步自检(`subskills/publisher/self_check.py`):

- 用 playwright 打开**最终发布 URL**,截前 N 页(默认 3);同时打开**本地渲染产物**截同样的页。
- 三类红牌:
  1. **资源断链 / 404** —— 监听发布页的 failed requests + HTTP≥400 响应,任一真资源
     (图 / 字体 / CSS / JS / 媒体)挂了即红牌。这是唯一没有 validator 的维度。
  2. **字体回落** —— 对比同页主文字的 effective font;本地用了真字体而远程回落成
     generic / 系统兜底字体(PingFang / YaHei / Arial 等)即红牌。
  3. **关键页视觉差异** —— 逐页按感知哈希(aHash+dHash)+ 下采样像素差(取大)算差异比例,
     某页超阈值(默认 6%)即红牌。算法与 `log-tool/deck-log.py diff` 同源。
- iframe-heavy deck 的自检会先让当前页 iframe settle 再截图,并对 Magic shell 探针、
  iframe `document net::ERR_ABORTED`、script `net::ERR_FAILED` 做可达性复测;复测 2xx/3xx
  的项进入 `verdict.ignored_requests`,不算断链。真实 4xx/5xx、DNS 失败、字体回落和视觉走样
  仍是红牌。
- 任一红牌 → `publish-manifest.json` 的 `self_check.ok=false`,**整个发布判非零**(不把断掉的
  交付说成"已发布")。处理:照红牌列出的断链 / 回落页 / 走样页修源,**重新 render → 重新发布 →
  自检复跑**;别手改发布物。确属设计差异可 `--self-check-soft` 把红牌降级为告警,或
  `--skip-self-check` 整步跳过(只在你已人工确认远程 OK 时用)。

### 真实远程 URL 自检需要登录态

端到端"真发布 + 打开真 URL 自检"需要对 Magic Page / Cloudflare viewer 的**已登录会话**,
本工具链(无登录态的环境)跑不了真实远程那一段。因此:

- `publish.py` 在**真实发布成功**时自动对 `app_url` 跑自检 —— 有登录态、URL 可达时这一步会真跑。
- **自检逻辑本身本地可验**:`self_check.py` 可独立调用,`--remote` 既接 `https://` 真 URL,
  也接 `file://` / 本地路径 / 本地 http 副本。本地用「本地产物 vs 本地副本」即可验证断链检测
  (造一个引用缺失资源的副本)、视觉对比、差异阈值,无需真发布:

```bash
# 独立自检:本地产物 vs 最终 URL(真发布后,需登录态可达)
python3 skills/feishu-deck-h5/subskills/publisher/self_check.py \
  --local runs/<task-id>/output \
  --remote https://magic.solutionsuite.cn/html-box/<id> \
  --out runs/<task-id>/output --pages 3

# 本地验证自检逻辑:把 --remote 指向本地副本(改一页 / 删一个资源就能看红牌)
python3 skills/feishu-deck-h5/subskills/publisher/self_check.py \
  --local runs/<task-id>/output --remote /path/to/remote-copy/index.html
```

浏览器(playwright/chromium)缺失时自检报「skipped」而不阻断真发布(`--allow-skip` 控制退出码)。

## 输出

默认写到 `runs/<task-id>/output/`:

```text
magic-page-publish.json
cloud-publish.json
MAGIC_PAGE_PUBLISH.md
publish-manifest.json
magic-iframe-faas.json        # 本地 iframe HTML -> TOS HTML -> FaaS 代理映射
publish-self-check.json      # F-285 发布后自检机读结果 (self_check.ok / verdict)
PUBLISH_SELF_CHECK.md        # F-285 发布后自检红牌报告
self-check/local|remote/*.png  # 本地 vs 远程逐页截图
PUBLISH_SIZE_REPORT.md      # Magic Page 正文字数门禁与自动外置代码记录
publish-snapshot.json       # 本次不可变发布输入、资源闭包、页面哈希
publish-snapshots/<id>/     # 内容寻址发布快照
publish-timing.json         # 分阶段耗时与 600s SLO
PUBLISH_TIMING.md           # 人读耗时报告
publisher-*.log
```

## 硬规则

- 不把 `deck-validator` / `check-only` 作为 Magic Page 默认发布门禁;发布只拦资源完整性。
- 默认发布到 `magic.solutionsuite.cn/html-box/...`;不要把最终交付链接发布成妙搭链接。
- 发布前必须执行 Magic Page 资产准备和依赖审计;除 Magic/TOS 托管 URL 外,不得残留
  `data:`、`file:`、绝对/相对本地资源路径或第三方运行时依赖。
- 不手工替代 `feishu-slide-library` 的任何入库逻辑。
- 不在聊天或日志里泄露 GitHub / 飞书 / Magic token。
- 发布成功后必须跑发布后自检(F-285):有登录态时对**最终 URL** 验断链 / 字体 / 视觉;自检红牌
  不算发布完成,要修源重发。`--skip-self-check` 只在已人工确认远程无误时用。
- PUBLISH / PUBLISH_RECOVERY 不得同步运行 `REPOSITORY_CHANGE` 全仓门禁;正式提交/发布技能代码时
  再进入独立 MAINTENANCE 生命周期完成它。
- 发布完成后的准确话术是“已发布到 Magic Page”。如用户还要求入库,交给 importer。
