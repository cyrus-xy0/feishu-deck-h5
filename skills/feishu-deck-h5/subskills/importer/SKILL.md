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

目标:把用户做好的、已确认的 HTML deck 先做资源准入检查,再按
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

- **资源-only 入库门禁**:对确认 HTML 运行 `check-only.py --resource-only` 并写
  `IMPORT_QUALITY_REPORT.md`。它只阻塞包结构、入口 HTML、运行时本地引用、路径安全和
  `assets-manifest.yaml` 素材闭包问题;不跑视觉、排版或跨页一致性规则。
  资源检查不过不得入库。`--gate ingest` 仍保留为用户主动要求时的严格业务/视觉评审，
  不再是默认入库门。
- **PR 入库**:对 canonical `runs/<task>/output/index.html` 先运行
  `copy-assets.py --shared=link -> package-ingest.sh --deck-id`,生成新鲜、自包含的
  `deck.zip`;再调用 `feishu-slide-library` 的权威脚本:
  `bootstrap-library.py -> ingest-package.py -> confirm-ingest.py`。孤立的外部 HTML
  仍直接交给 `ingest-package.py` 做兼容入库。不要手写
  fingerprint、判重、候选包、PR、merge 或 viewer index 逻辑。
- **candidate 资产门禁**:`ingest-package.py` 必须在 candidate 事务内消费
  `assets-manifest.yaml`,把 shared 改写到 `../../assets/shared/`,并把 framework
  改写到 `../../assets/framework/`。importer 随后只读校验 candidate;不得再调用
  legacy `ingest-assets.py` 修改 live library。
- **Viewer 同步**:真实入库请求默认应让 `confirm-ingest.py` 走 PR/merge/viewer 同步链路,
  并等待 Cloudflare 托管站点同步完成。用 `--auto-merge --wait-viewer` 明确表达这个意图。
- **上下文记录**:把 PR、Cloudflare viewer 同步结果和 viewer URL/线索记录进
  `ingestion-manifest.json`;不得读取或沿用 `magic-page-publish.json` /
  `cloud-publish.json` 作为入库或 viewer 同步结果。
- **报告**:输出 `ingestion-manifest.json` 和 `INGESTION_REPORT.md`,记录
  quality_gate、ingest_result、review_candidates、PR / merge / viewer 同步结果和失败原因。

## 前置条件

- 必须有用户明确确认“这就是最终入库物”。
- importer 必须自己运行 `check-only.py --resource-only` 并通过资源闭包检查。
  `--allow-unaudited` 只允许本地调试时跳过前置资源预检;后续打包和 slide-library
  资源门禁仍然生效。
- 入库目标必须是完整的 `https://github.com/FuQiang/feishu-slide-library`
  checkout,默认读取 `FEISHU_SLIDE_LIBRARY_ROOT`,否则尝试
  `../../tmp/feishu-slide-library` 和旧位置 `tmp/feishu-slide-library`。
- 在 Codex Desktop/本机 Agent 环境里,优先使用工作区 bundled Python 执行 importer,
  因为 slide-library ingest 依赖 `lxml` 等包,系统 `python3` 可能缺依赖。
- 本机已知可用的 slide-library checkout:
  `/Users/bytedance/Documents/import/feishu-deck-h5/tmp/feishu-slide-library`。
  importer 会自动预检 `bootstrap-library.py` / `ingest-package.py` /
  `confirm-ingest.py`,缺失时在写入前停止。`ingest-assets.py` 不再是 wrapper
  依赖;资产归并必须发生在 candidate 生成事务内。
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

全链路 dry run,不调用打包或 slide-library 外部写入,也不改 canonical run:

```bash
python3 skills/feishu-deck-h5/subskills/importer/ingest.py \
  --html path/to/index.html \
  --title "<deck title>" \
  --deck-id <deck-id> \
  --dry-run
```

## feishu-slide-library 入库方式

importer 必须复用 `FuQiang/feishu-slide-library` 的脚本和判断:

0. 先跑
   `check-only.py <confirmed.html> --resource-only --report IMPORT_QUALITY_REPORT.md`。
1. canonical run output 先执行
   `copy-assets.py <output> --shared=link`,让本地 output 收敛到中央 shared pool;
   再执行 `package-ingest.sh <output> --deck-id <deck_id>`,由 ZIP 只物化实际可达的
   shared 字节。禁止把单独 `index.html` 交给库而丢失 manifest/assets。
2. `bootstrap-library.py --library-root <root> --repo-url https://github.com/FuQiang/feishu-slide-library.git --branch main`
3. `ingest-package.py <deck.zip|isolated.html> --deck-id <deck_id> --job-id <job_id> --library-root <root> --staging-root <staging> --submitted-by <user> --overwrite --no-deck-h5-gate --resource-checks-only`
   入库只让资源可用性问题阻塞;用户若需要严格业务/视觉评审，单独运行
   `check-only.py <confirmed.html> --gate ingest`。
4. 从 `ingest_result.json` 解析 `candidate_root`,只读验证:
   `decks/<deck_id>/source.html` 存在、没有 deck-local `assets/shared/`,manifest 中
   shared 引用都已改写为 `../../assets/shared/...`,中央文件存在且与包内文件 hash
   一致,同时不残留旧 framework 路径。验证失败不得 confirm,也不得事后修改 live library。
5. 若 `ready_for_confirm=true`、candidate 资产门禁通过且用户确认已经发生,调用
   `confirm-ingest.py <staging>/ingest_result.json --library-root <root>`。
6. 真实“入库/提交/上传”默认显式传 `--auto-merge --wait-viewer`,让 PR 合并后等待
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

- `quality_gate`: resource-only check-only 入库门禁结果。
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
- 不在 `ingest-package.py` 之后调用 `ingest-assets.py` 修改 live library;shared/framework
  改写必须在 candidate 事务中完成,wrapper 只做 verify-only。
- 不在聊天或日志里泄露 GitHub / 飞书 token。
- 不把“已生成候选包”说成“已入库”;只有 `confirm-ingest.py` 成功后才能说入库动作完成。
- 若 PR 已合并但 Cloudflare viewer / 素材网未同步,必须说“已入库,素材网暂未同步”,
  并给出 PR / check 线索。
