---
name: importer
description: |
  Quality-gate and ingest a user-finished feishu-deck-h5 HTML deck into
  FuQiang/feishu-slide-library, then sync the Cloudflare-hosted library
  viewer through the slide-library PR flow. Use only after the user already has
  an HTML deck and explicitly says 入库, 提交, 上传, import, submit, archive, add to
  slide library, or push into the reusable slide library. Do not use for generic
  HTML editing, validation-only review, Magic Page-only publishing, fixing,
  rendering, or rehearsal.
---

# importer

目标:把用户做好的、已确认的 HTML deck 先质检,再按
`https://github.com/FuQiang/feishu-slide-library` 的标准逻辑通过 PR 入库,随后同步
Cloudflare 托管的素材库站点。这里的同步是 slide-library viewer / Cloudflare 站点同步,
不是 Magic Page 链接发布；仅发布 Magic Page 链接仍属于 `subskills/publisher/SKILL.md`。

Inline freshness rule: when this subskill is not running as a separate
multi-agent worker, reread the current upstream files before ingestion. Do not
rely on cached chat summaries or earlier reads of the confirmed HTML artifact,
validator pass evidence, viewer sync metadata, ingest manifests, or library checkout
state.

## 触发条件

只有同时满足以下条件才使用 importer:

1. 用户已有一个 htmldeck / `index.html` / run output 中的成品 HTML。
2. 用户明确说出“入库”“提交”“上传”“import”“submit”“archive”“add to slide library”等意图。
3. 目标是进入 `FuQiang/feishu-slide-library` 及其 Cloudflare 托管 viewer,而不是只要本地交付或 Magic Page。

如果用户只是说“检查/质检/看看能不能入库”,先走 validator/check-only;不要直接 importer。

## 职责边界

- **质检 (入库前门禁)**:先复用已有 validator PASS 证据;没有 PASS 证据时对确认 HTML 运行
  `check-only.py --gate ingest` 并写 `IMPORT_QUALITY_REPORT.md`。质检不过不得入库。
  入库门会把 warn 升 error,且**覆盖跨页一致性规则**
  `R-DECK-TITLE-DRIFT` / `R-DECK-PALETTE-DRIFT` / `R-DECK-TYPESCALE-BUDGET`(F-257/F-285):
  标题跨页漂移、近重复强调色、`allow:typescale` 滥用都会拦在库门外 —— 不一致的 deck 入库后
  最坑复用(抽到别处拼接接不上)。注意门禁只 block `business-rules.yaml` 里有条目的规则码,
  这三条已补进字典;新增跨页规则务必同步补 yaml,否则会被门禁静默丢掉(F-18 漂移)。
- **PR 入库**:调用 `feishu-slide-library` 的权威脚本:
  `bootstrap-library.py -> ingest-package.py -> confirm-ingest.py`。不要手写
  fingerprint、判重、候选包、PR、merge 或 viewer index 逻辑。
- **Viewer 同步**:真实入库请求默认应让 `confirm-ingest.py` 走 PR/merge/viewer 同步链路,
  并等待 Cloudflare 托管站点同步完成。用 `--auto-merge --wait-viewer` 明确表达这个意图。
- **上下文记录**:把 PR、Cloudflare viewer 同步结果和 viewer URL/线索记录进
  `ingestion-manifest.json`;不得读取或沿用 `magic-page-publish.json` /
  `cloud-publish.json` 作为入库或 viewer 同步结果。
- **报告**:输出 `ingestion-manifest.json` 和 `INGESTION_REPORT.md`,记录
  quality_gate、ingest_result、review_candidates、PR / merge / viewer 同步结果和失败原因。

## 前置条件

- 必须有用户明确确认“这就是最终入库物”。
- 必须有 validator PASS 证据,或 importer 自己运行 `check-only.py --gate ingest` 并通过。
  只有本地调试/夹具可用 `--allow-unaudited`。
- 入库目标必须是完整的 `https://github.com/FuQiang/feishu-slide-library`
  checkout,默认读取 `FEISHU_SLIDE_LIBRARY_ROOT`,否则尝试
  `../../tmp/feishu-slide-library` 和旧位置 `tmp/feishu-slide-library`。
- 在 Codex Desktop/本机 Agent 环境里,优先使用工作区 bundled Python 执行 importer,
  因为 slide-library ingest 依赖 `lxml` 等包,系统 `python3` 可能缺依赖。
- 本机已知可用的 slide-library checkout:
  `/Users/bytedance/Documents/import/feishu-deck-h5/tmp/feishu-slide-library`。
  importer 会自动预检 `bootstrap-library.py` / `ingest-package.py` /
  `ingest-assets.py` / `confirm-ingest.py`,缺失时在写入前停止。
- 如果私有仓库权限缺失,不要让用户在聊天里贴 token;应由宿主环境注入
  `FEISHU_SLIDE_LIBRARY_GITHUB_TOKEN` / `GITHUB_TOKEN` / `GH_TOKEN`。

## 标准命令

对一个 run 的确认产物入库:

```bash
python3 skills/feishu-deck-h5/subskills/importer/ingest.py \
  --task-id <runs-dir-name> \
  --title "<deck title>" \
  --deck-id <feishu-slide-library-deck-id> \
  --auto-merge \
  --wait-viewer
```

直接处理某个 HTML 文件:

```bash
python3 skills/feishu-deck-h5/subskills/importer/ingest.py \
  --html path/to/index.html \
  --title "<deck title>" \
  --deck-id <feishu-slide-library-deck-id> \
  --auto-merge \
  --wait-viewer
```

只跑 `ingest-package.py` 生成候选包,暂不执行 `confirm-ingest.py`:

```bash
python3 skills/feishu-deck-h5/subskills/importer/ingest.py \
  --html path/to/index.html \
  --title "<deck title>" \
  --deck-id <deck-id> \
  --no-confirm-ingest
```

全链路 dry run,不调用 slide-library 外部写入:

```bash
python3 skills/feishu-deck-h5/subskills/importer/ingest.py \
  --html path/to/index.html \
  --title "<deck title>" \
  --deck-id <deck-id> \
  --dry-run
```

## feishu-slide-library 入库方式

importer 必须复用 `FuQiang/feishu-slide-library` 的脚本和判断:

0. 若没有可复用的 validator PASS 证据,先跑
   `check-only.py <confirmed.html> --gate ingest --report IMPORT_QUALITY_REPORT.md`。
1. `bootstrap-library.py --library-root <root> --repo-url https://github.com/FuQiang/feishu-slide-library.git --branch main`
2. `ingest-package.py <confirmed.html> --deck-id <deck_id> --job-id <job_id> --library-root <root> --staging-root <staging> --submitted-by <user> --overwrite`
3. 若 deck-h5 output 有 `assets-manifest.yaml`,必须先调用
   `ingest-assets.py <deck-h5-output-dir> <deck_id>`;若 source.html 仍残留
   `assets/feishu-deck.css` / `assets/feishu-deck.js` 等本地框架引用,必须停止。
4. 若 `ready_for_confirm=true` 且用户确认已经发生,调用
   `confirm-ingest.py <staging>/ingest_result.json --library-root <root>`。
5. 真实“入库/提交/上传”默认显式传 `--auto-merge --wait-viewer`,让 PR 合并后等待
   Cloudflare 托管的素材网/viewer 同步。若权限或 CI 阻塞,报告 PR/check 线索。

`ingest-package.py` 产出的 `ingest_result.json`、`ingest_report.md`、
`assessment.json`、`review_candidates.md`、`git_pr_plan.json` 等是权威事实源。
importer 只读取和转写这些路径到 manifest,不得伪造成功结果。

## 输出

默认写到 `runs/<task-id>/output/`:

```text
ingestion-manifest.json
INGESTION_REPORT.md
IMPORT_QUALITY_REPORT.md
importer-slide-library-*.log
```

`ingestion-manifest.json` 必须符合:

```text
skills/feishu-deck-h5/schema/ingestion-manifest.schema.json
```

关键字段:

- `quality_gate`: validator/check-only 入库门禁结果。
- `library_ingest`: feishu-slide-library deck_id、staging、ingest_result、
  review_candidates、PR/confirm/merge 结果。
- `viewer_sync`: slide-library Cloudflare viewer 同步结果和 URL/线索。
- `slide_records`: 兼容字段,用于记录已知 slide key;真正入库判断以
  feishu-slide-library 的 `ingest_result.json` 为准。
- `skipped`: 未执行或失败的步骤,必须写明原因。

## 硬规则

- 不绕过 validator 入库失败 HTML。
- 不把 Magic Page 或妙搭链接当成 slide-library/Cloudflare 入库或 viewer 同步结果。
- 不把 simulator 预测、模拟 quote 或成交判断当成真实客户事实入库。
- 不手工替代 `feishu-slide-library` 的 `ingest-package.py` / `confirm-ingest.py`。
- 不在聊天或日志里泄露 GitHub / 飞书 token。
- 不把“已生成候选包”说成“已入库”;只有 `confirm-ingest.py` 成功后才能说入库动作完成。
- 若 PR 已合并但 Cloudflare viewer / 素材网未同步,必须说“已入库,素材网暂未同步”,
  并给出 PR / check 线索。
