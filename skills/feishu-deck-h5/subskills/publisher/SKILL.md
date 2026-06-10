---
name: publisher
description: |
  Publish a user-confirmed feishu-deck-h5 HTML deck to Feishu/Miaobi Magic Page.
  Use only after validator pass and explicit user confirmation. Do not validate,
  fix, render, rehearse, or ingest decks into feishu-slide-library.
---

# publisher

目标:把用户已经确认的 HTML deck 发布到飞书妙笔 / Magic Page,生成可访问链接。
publisher 只负责“发布”,不负责入库。将成品 HTML 推到
`FuQiang/feishu-slide-library` 的动作属于 `subskills/importer/SKILL.md`。

Inline freshness rule: when this subskill is not running as a separate
multi-agent worker, reread the current upstream files before publishing. Do not
rely on cached chat summaries or earlier reads of the confirmed HTML artifact,
validator pass evidence, or publish metadata.

## 职责边界

- **发布**:默认将确认后的 `.html` / `.htm` 发布到 Feishu/Miaobi Magic Page,
  访问 URL 必须是 `https://magic.solutionsuite.cn/html-box/<id>` 形态,输出
  `magic-page-publish.json`、`cloud-publish.json`、`MAGIC_PAGE_PUBLISH.md` 和
  `publish-manifest.json`。
- **妙笔资产准备**:默认先把 CSS/JS 内联为一个临时 HTML,但保留资源引用为 URL;
  然后把所有本地资源、`data:...` 资源、第三方远程资源上传到妙笔 TOS 并重写为
  托管 URL,最后调用 Magic Page 发布 API。最终发布物不得依赖本地路径、第三方
  外链或 base64 payload;发布到 Magic Page 后必须只靠发布链接就能完整使用。
- **单一发布目标**:publisher 只发布到 Feishu/Miaobi Magic Page;不得提供
  `--publish-target`、Miaoda fallback 或 slide-library 入库分支。
- **不入库**:不得调用 `feishu-slide-library` 的
  `bootstrap-library.py` / `ingest-package.py` / `confirm-ingest.py`,不得生成或确认
  slide-library PR,不得把“已发布”说成“已入库”。

## 前置条件

- 必须有用户明确确认“这就是最终发布物”。
- 必须有 `deck-validator` 通过结论。只有本地调试/夹具可用 `--allow-unaudited`。
- 校验必须跑在**即将发布的那一份 HTML 字节**上,不能复用旧的“渲染时已过”结论。重点拦
  `R-BAKED-DOM`:若发布物含 `data-idx=` / 烤进 body 的 `class="deck-ui"` /
  `.deck` 带 `data-js-ready`,说明它是“运行后被另存的活 DOM”(非 `render-deck.py` 产物),
  发布后会二次 init 导致页码定格在 1 / UI 重复 —— 必须从 `deck.json` 重渲出干净版再发,
  别发烤死版。
- 妙笔发布默认读取 `MAGIC_TOKEN` 或 `~/.magic-token`;域名默认
  `https://magic.solutionsuite.cn`,可用 `MAGIC_BASE_URL` / `--magic-base-url` 指定。
  如果本地没有 token,必须先要求用户提供 token,不得等到发布 API 阶段才失败。
- Magic Page 资源上传默认使用仓库内
  `skills/feishu-deck-h5/assets/magic-upload.js`,也可通过
  `FEISHU_DECK_H5_MAGIC_ASSET_UPLOADER` 或 `--magic-asset-uploader` 指定。

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

全链路 dry run,不真实发布:

```bash
python3 skills/feishu-deck-h5/subskills/publisher/publish.py \
  --html path/to/index.html \
  --title "<deck title>" \
  --dry-run
```

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
publish-self-check.json      # F-285 发布后自检机读结果 (self_check.ok / verdict)
PUBLISH_SELF_CHECK.md        # F-285 发布后自检红牌报告
self-check/local|remote/*.png  # 本地 vs 远程逐页截图
publisher-*.log
```

## 硬规则

- 不绕过 validator 发布失败 HTML。
- 默认发布到 `magic.solutionsuite.cn/html-box/...`;不要把最终交付链接发布成妙搭链接。
- 发布前必须执行 Magic Page 资产准备和依赖审计;除 Magic/TOS 托管 URL 外,不得残留
  `data:`、`file:`、绝对/相对本地资源路径或第三方运行时依赖。
- 不手工替代 `feishu-slide-library` 的任何入库逻辑。
- 不在聊天或日志里泄露 GitHub / 飞书 / Magic token。
- 发布成功后必须跑发布后自检(F-285):有登录态时对**最终 URL** 验断链 / 字体 / 视觉;自检红牌
  不算发布完成,要修源重发。`--skip-self-check` 只在已人工确认远程无误时用。
- 发布完成后的准确话术是“已发布到 Magic Page”。如用户还要求入库,交给 importer。
