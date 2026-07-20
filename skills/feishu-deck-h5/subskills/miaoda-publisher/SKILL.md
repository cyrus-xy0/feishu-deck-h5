---
name: miaoda-publisher
description: |
  Publish a confirmed Feishu Deck H5 artifact to its own Miaoda HTML app and
  refresh a separate Miaoda navigation app. Each deck keeps an independent
  app_id and access scope; the catalog is discovery only, never an ACL boundary.
---

# Miaoda publisher

目标：每个 Deck 发布为独立妙搭 HTML 应用，并把其发布态 URL 登记到另一个
妙搭导航应用。不要把多个 Deck 放进同一个应用；应用级权限必须保持独立。

## 前置条件

- 用户已经确认待发布的 HTML。
- 真实创建、发布或修改可见范围前，必须确认目标 Deck、导航应用和权限范围。
- 先运行 `bash assets/preflight.sh --profile miaoda-publish`。
- 妙搭应用属于用户资产，所有命令使用 `--as user`；仅在 CLI 明确报告未登录或
  missing scope 时才执行 `lark-cli auth login --domain apps`。

## 本地目录

默认持久化在仓库忽略的 `runs/miaoda-publisher/`，可用
`FEISHU_DECK_H5_MIAODA_ROOT` 或 `--catalog-root` 覆盖：

```text
catalog/
  site/index.html
  site/assets/lark-cover-bg.jpg
  site/assets/lark-logo.png
  site/covers/<slug>.jpg
  catalog.json
  app.json
decks/<slug>/
  site/index.html
  site/assets/...
  app.json
  publish-manifest.json
  MIAODA_PUBLISH.md
```

`app.json` 只记录 app_id、发布 URL、内容哈希和权限摘要；不得记录 token、
cookie、credential 或 specific scope 的目标 ID。导航发布目录只有
`catalog/site/`，因此本地 registry 不会被上传。

## 发布合同

1. 将确认的 Deck 复制到干净 staging，使用 `copy-assets.py --shared=copy`
   自包含资源，并仅在发布副本注入 `fs-deck-edit-policy=readonly`。妙搭版按
   `E` 只提示回到本地源 Deck 修改后重发，不进入编辑模式；不要上传
   `deck.json`，本地源 Deck 的编辑能力保持不变。发布副本还要给 cover frame
   注入不依赖 CSS `:has()` 的显式花背景和 Logo；两项封面资源以内联 data URI
   写入发布副本，避免妙搭把 JPG 作为附件响应而导致 CSS 背景无法解码。本地源
   Deck 不改。最后用 `verify-portable.py` 拦截缺失、逃逸和 symlink。
2. 在任何外部写入前检查妙搭三条硬限制：单个 HTML ≤10 MB、未压缩总量
   ≤200 MB、tar.gz ≤20 MB。任一超限立即停止。
3. 首次创建 `app_type=html` 的 Deck 应用；后续从 `decks/<slug>/app.json`
   复用 app_id。显式 `--deck-app-id` 与已保存值冲突时必须失败。
4. 发布整个 `decks/<slug>/site/` 目录，不得只传 `index.html`。
5. 仅当用户明确给出 `--scope` 时修改该 Deck 的访问范围；`keep` 不改权限。
6. Deck 发布成功后更新 catalog，再发布独立导航应用。导航 Hero 使用受控的
   飞书花背景与 Logo；每张卡片用 `shoot-page.py` 确定性截取第 1 页为
   960×540 JPEG 封面，并按 Deck 内容哈希复用未变化的截图；若当前机器缺少
   截图运行时，则明确告警并退化为同一飞书花背景。导航卡片使用带尾斜杠的
   完整发布 URL，并追加 `#1` 确保从封面打开；目标 Deck 仍由自己的 ACL
   拦截。敏感标题用 `--unlisted`。
7. 导航失败不得抹掉已经成功的 Deck app_id/URL；重跑应复用状态并补发导航。

## 命令

```bash
python3 subskills/miaoda-publisher/publish.py \
  --html /path/to/index.html \
  --slug marriott-ai \
  --title "万豪 × 飞书 · 打造 AI 原生组织" \
  --category "客户交流"
```

发布给企业内成员：

```bash
python3 subskills/miaoda-publisher/publish.py \
  --task-id <run-id> \
  --slug <slug> \
  --scope tenant \
  --catalog-scope tenant
```

指定范围必须传已确认的 ID JSON：

```bash
python3 subskills/miaoda-publisher/publish.py \
  --html /path/to/index.html \
  --slug <slug> \
  --scope specific \
  --targets-json '[{"type":"user","id":"ou_xxx"}]'
```

只做本地 staging、大小检查和 CLI request dry-run：

```bash
python3 subskills/miaoda-publisher/publish.py \
  --html /path/to/index.html \
  --slug <slug> \
  --dry-run
```

dry-run 写入 `<catalog-root>/.dry-run/<slug>/`，不改正式 registry，也不创建或
发布应用。必须检查 `data.path_error` 不存在、`file_count > 0` 且文件清单包含
根 `index.html`；不能只看退出码 0。

## 权限边界

- `--scope keep`：不修改现有范围；新应用保留平台默认的仅创建者可见。
- `tenant`：企业内可见。
- `public`：必须显式给 `--require-login` 或 `--no-require-login`。
- `specific`：必须给 `--targets-json`；目标 ID 不写进 registry 或导航页。
- 导航应用使用独立的 `--catalog-scope` 系列参数。
- 导航是静态索引，无法按访问者动态隐藏卡片。只有 `listed=true` 的 Deck
  展示；标题本身敏感时必须 `--unlisted`。

## 硬规则

- 妙笔 / Magic Page 仍由 `subskills/publisher` 负责；不得向旧 Publisher 增加
  Miaoda fallback 或通用 `--publish-target`。
- 导航 app_id 绝不能与任何 Deck app_id 相同。
- CLI 成功以退出码 0 且 `ok == true` 为准；真实 create 只读取
  `data.app.app_id`，绝不能把 `data.context.app_id` 的 `cli_...` 写入状态。
- HTML 发布读取 `data.url`；若返回 `data.release_id`，轮询
  `apps +release-get` 到 `finished` 后才可交付 `online_url`。
- 不自动追加 `--allow-sensitive`，不输出或落盘认证信息。
