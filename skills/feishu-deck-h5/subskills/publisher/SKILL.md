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

## 输出

默认写到 `runs/<task-id>/output/`:

```text
magic-page-publish.json
cloud-publish.json
MAGIC_PAGE_PUBLISH.md
publish-manifest.json
publisher-*.log
```

## 硬规则

- 不绕过 validator 发布失败 HTML。
- 默认发布到 `magic.solutionsuite.cn/html-box/...`;不要把最终交付链接发布成妙搭链接。
- 发布前必须执行 Magic Page 资产准备和依赖审计;除 Magic/TOS 托管 URL 外,不得残留
  `data:`、`file:`、绝对/相对本地资源路径或第三方运行时依赖。
- 不手工替代 `feishu-slide-library` 的任何入库逻辑。
- 不在聊天或日志里泄露 GitHub / 飞书 / Magic token。
- 发布完成后的准确话术是“已发布到 Magic Page”。如用户还要求入库,交给 importer。
