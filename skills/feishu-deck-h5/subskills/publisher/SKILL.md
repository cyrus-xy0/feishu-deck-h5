---
name: publisher
description: |
  Publish a user-confirmed feishu-deck-h5 HTML deck to Feishu/Miaobi Magic Page
  and ingest the same artifact into FuQiang/feishu-slide-library. Use only after
  validator pass and explicit user confirmation. Do not validate, fix, render,
  or rehearse decks.
---

# publisher

目标:把用户已经确认的 HTML deck 直接发布到飞书妙笔,并按
`FuQiang/feishu-slide-library` 的标准流程完成入库。这个 skill 是最后一公里的
编排器:它不重新验收、不修稿、不渲染,只消费已通过 `deck-validator` 的 HTML 产物,
然后完成“发布可访问链接 + slide library 入库”。

Inline freshness rule: when this subskill is not running as a separate
multi-agent worker, reread the current upstream files before publishing. Do not
rely on cached chat summaries or earlier reads of the confirmed HTML artifact,
validator pass evidence, publish metadata, ingest manifests, or library checkout
state.

## 职责边界

- **发布**:默认将确认后的 `.html` / `.htm` 发布到 Feishu/Miaobi Magic Page,
  访问 URL 必须是 `https://magic.solutionsuite.cn/html-box/<id>` 形态,输出
  `magic-page-publish.json`、`cloud-publish.json` 和 `MAGIC_PAGE_PUBLISH.md`。
  妙搭/Miaoda 只作为显式 `--publish-target miaoda` 的兼容选项,不得作为默认路径。
- **妙笔资产准备**:默认先把 CSS/JS/本地素材内联为一个临时 HTML,再把图片资源上传到
  妙笔 TOS 并重写为公网 URL,最后调用 Magic Page 发布 API。这样最终发布物不依赖本地
  相对路径,也不会把超大的 base64 图片直接交给妙笔。
- **入库**:调用 `feishu-slide-library` 的权威脚本:
  `bootstrap-library.py -> ingest-package.py -> confirm-ingest.py`。不要手写
  fingerprint、判重、候选包、PR 或 viewer index 逻辑。
- **报告**:输出 `ingestion-manifest.json` 和 `INGESTION_REPORT.md`,记录发布 URL、
  ingest_result、review_candidates、PR 计划/结果和失败原因。

## 前置条件

- 必须有用户明确确认“这就是最终发布物”。
- 必须有 `deck-validator` 通过结论。只有本地调试/夹具可用 `--allow-unaudited`。
- 入库目标必须是完整的 `https://github.com/FuQiang/feishu-slide-library`
  checkout,默认读取 `FEISHU_SLIDE_LIBRARY_ROOT`,否则尝试
  `tmp/feishu-slide-library`。
- 在 Codex Desktop/本机 Agent 环境里,优先使用工作区 bundled Python 执行 publisher,
  因为 slide-library ingest 依赖 `lxml` 等包,系统 `python3` 可能缺依赖:

```bash
/Users/bytedance/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  skills/feishu-deck-h5/subskills/publisher/ingest.py \
  --html runs/<run>/output/lark-<deck-id>.html \
  --title "<deck title>" \
  --deck-id <deck-id> \
  --slide-library-root /Users/bytedance/Documents/lark-deck-cyrus/tmp/feishu-slide-library
```

  若该路径不可用,先调用 workspace dependency discovery,或用当前环境里包含
  `lxml` 的 Python。不要在第一次失败后继续用缺依赖的系统 Python 重试。
- 本机已知可用的 slide-library checkout:
  `/Users/bytedance/Documents/lark-deck-cyrus/tmp/feishu-slide-library`。如果不显式传
  `--slide-library-root`,publisher 会尝试
  `skills/feishu-deck-h5/tmp/feishu-slide-library`;该目录可能不存在或缺少
  `bootstrap-library.py` / `ingest-package.py` / `confirm-ingest.py`,导致发布成功但入库失败。
- 如果私有仓库权限缺失,不要让用户在聊天里贴 token;应由宿主环境注入
  `FEISHU_SLIDE_LIBRARY_GITHUB_TOKEN` / `GITHUB_TOKEN` / `GH_TOKEN`。
- 妙笔发布默认读取 `MAGIC_TOKEN` 或 `~/.magic-token`;域名默认
  `https://magic.solutionsuite.cn`,可用 `MAGIC_BASE_URL` / `--magic-base-url` 指定。
- Magic Page 资源上传默认使用仓库内
  `skills/feishu-deck-h5/assets/magic-upload.js`,也可通过
  `FEISHU_DECK_H5_MAGIC_ASSET_UPLOADER` 或 `--magic-asset-uploader` 指定。

## 标准命令

对一个 run 的确认产物发布并入库:

```bash
python3 skills/feishu-deck-h5/subskills/publisher/ingest.py \
  --task-id <runs-dir-name> \
  --title "<deck title>" \
  --deck-id <feishu-slide-library-deck-id>
```

直接处理某个 HTML 文件:

```bash
python3 skills/feishu-deck-h5/subskills/publisher/ingest.py \
  --html path/to/index.html \
  --title "<deck title>" \
  --deck-id <feishu-slide-library-deck-id>
```

只把用户最终确认的 HTML 发布到飞书妙笔,不执行 slide-library 入库:

```bash
python3 skills/feishu-deck-h5/subskills/publisher/ingest.py \
  --html path/to/index.html \
  --title "<deck title>" \
  --publish-only
```

全链路 dry run,不真实发布、不调用 slide-library 外部写入:

```bash
python3 skills/feishu-deck-h5/subskills/publisher/ingest.py \
  --html path/to/index.html \
  --title "<deck title>" \
  --deck-id <deck-id> \
  --dry-run
```

如果只想跑 `ingest-package.py` 生成候选包,暂不执行 `confirm-ingest.py`:

```bash
python3 skills/feishu-deck-h5/subskills/publisher/ingest.py \
  --html path/to/index.html \
  --title "<deck title>" \
  --deck-id <deck-id> \
  --no-confirm-ingest
```

## Codex Desktop 成功路径与失败复盘

2026-06-02 实测“发布到妙笔并入库”时,成功路径如下:

```bash
/Users/bytedance/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
  skills/feishu-deck-h5/subskills/publisher/ingest.py \
  --html runs/20260602-140230-ai-process-remodel/output/lark-ai-process-remodel-2026-06-02.html \
  --title "AI 如何重塑流程" \
  --deck-id lark-ai-process-remodel-2026-06-02 \
  --slide-library-root /Users/bytedance/Documents/lark-deck-cyrus/tmp/feishu-slide-library
```

成功结果:

- 妙笔 URL: `https://magic.solutionsuite.cn/html-box/vlmQ5B8pVw1`
- 入库: `confirm-ingest.py` 成功,`library_ingest.confirmed=true`
- PR: `https://github.com/FuQiang/feishu-slide-library/pull/51`

这次耗时长的原因不是 deck 处理慢,而是连续遇到环境问题:

1. `magic-page-assets failed ... Error: fetch failed`
   - 原因:沙箱网络限制阻断 Magic Page 资产上传。
   - 处理:用批准后的网络权限重跑同一 publisher 命令。
2. `missing feishu-slide-library scripts`
   - 原因:默认 `skills/feishu-deck-h5/tmp/feishu-slide-library` 不是完整 checkout。
   - 处理:显式传入已有完整 checkout:
     `/Users/bytedance/Documents/lark-deck-cyrus/tmp/feishu-slide-library`。
3. `ModuleNotFoundError: No module named 'lxml'`
   - 原因:系统 `python3` 缺 slide-library ingest 所需依赖。
   - 处理:改用 Codex bundled Python:
     `/Users/bytedance/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3`。

后续同类任务应直接使用“bundled Python + 显式 slide-library root + 网络权限”的组合,
不要先用系统 `python3` 或默认库路径试错。若命令没有网络权限且出现 `fetch failed`,
应立即按权限流程重试,不要改 deck 或改发布目标。

## feishu-slide-library 入库方式

publisher 必须复用 `FuQiang/feishu-slide-library` 的脚本和判断:

1. `bootstrap-library.py --library-root <root> --repo-url https://github.com/FuQiang/feishu-slide-library.git --branch main`
2. `ingest-package.py <confirmed.html> --deck-id <deck_id> --job-id <job_id> --library-root <root> --staging-root <staging> --submitted-by <user> --overwrite`
3. 若 `ready_for_confirm=true` 且用户确认已经发生,调用
   `confirm-ingest.py <staging>/ingest_result.json --library-root <root>`。
4. 如果需要真实合并或等待素材网同步,显式传 `--auto-merge` / `--wait-viewer`。

`ingest-package.py` 产出的 `ingest_result.json`、`ingest_report.md`、
`assessment.json`、`review_candidates.md`、`git_pr_plan.json` 等是权威事实源。
publisher 只读取和转写这些路径到 manifest,不得伪造成功结果。

## 输出

默认写到 `runs/<task-id>/output/`:

```text
magic-page-publish.json
cloud-publish.json
MAGIC_PAGE_PUBLISH.md
ingestion-manifest.json
INGESTION_REPORT.md
publisher-*.log
```

`ingestion-manifest.json` 必须符合:

```text
skills/feishu-deck-h5/schema/ingestion-manifest.schema.json
```

关键字段:

- `publication`: 妙笔发布状态、URL、app id、失败原因。
- `library_ingest`: feishu-slide-library deck_id、staging、ingest_result、
  review_candidates、PR/confirm 结果。
- `slide_records`: 兼容字段,用于记录已知 slide key;真正入库判断以
  feishu-slide-library 的 `ingest_result.json` 为准。
- `skipped`: 未执行或失败的步骤,必须写明原因。

## 硬规则

- 不绕过 validator 发布失败 HTML。
- 默认发布到 `magic.solutionsuite.cn/html-box/...`;不要把最终交付链接发布成妙搭链接。
- 不把 simulator 预测、模拟 quote 或成交判断当成真实客户事实入库。
- 不手工替代 `feishu-slide-library` 的 `ingest-package.py` / `confirm-ingest.py`。
- 不在聊天或日志里泄露 GitHub / 飞书 token。
- 不把“已生成候选包”说成“已入库”;只有 `confirm-ingest.py` 成功后才能说入库动作完成。
- 若 PR 已合并但素材网未同步,必须说“已入库,素材网暂未同步”,并给出 PR / check 线索。

## PPT 自选登记

保留旧的本地候选登记入口,用于用户只是想把 PPT/PPTX 作为后续可选来源:

```bash
python3 skills/feishu-deck-h5/subskills/publisher/ingest.py \
  --ppt-library path/to/team-slides.pptx \
  --title "团队自选 PPT" \
  --ppt-page 3 \
  --ppt-page 8
```

该模式不发布妙笔,也不写入 `feishu-slide-library`;要等选中页被转成确认后的 HTML
后,再走标准 publisher 流程。
