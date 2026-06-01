# INSTALL-CLOUD.md — feishu-deck-h5 在云端 agent 平台 / 容器上的安装

> 面向**操作者**：在 Mira / Codex / 内部 harness 等云端 agent 平台、Linux 容器，
> 或 macOS 开发机上安装本 skill。本文只描述**经代码核实**（含对抗式核实）的依赖
> 与行为，不臆造额外依赖。
>
> 从 git URL 安装到 Claude Code（plugin / install.sh / 手动 symlink）请看仓库根的
> [`INSTALL.md`](../../INSTALL.md)。本文专讲云端 / 只读挂载 / 容器场景。

---

## 1. TL;DR

最小可用的 deck 渲染只需 **bash + python3（≥ 3.9）**，且必须有一块**可写的持久化
目录**（PREFLIGHT 硬闸门，见 §6）。**核心渲染链对第三方包零硬依赖**，纯 stdlib 即可
端到端渲染 + 静态校验，且 **locale 无关**（见 §7 — 此前的 C-locale 崩溃已在代码层根治）。

要让**视觉审计（visual audits）**与中文截图也正常工作，云端 Linux 容器还需三件套：

```bash
pip install playwright pyyaml beautifulsoup4
python -m playwright install chromium     # 浏览器二进制，独立步骤
playwright install-deps chromium          # Chromium 的系统 .so，又一独立步骤（见 §7）
apt-get install -y fonts-noto-cjk         # CJK 字体，否则中文渲染成 tofu（见 §7）
```

装完用**一条命令验证**：

```bash
bash assets/check-mira.sh
```

纯环境自检，无 LLM、无 token、约 5 秒。**注意**：`check-mira.sh` **不**检测 UTF-8 locale、
CJK 字体、Chromium 系统库，也不真正启动 Chromium——这三项请按 §5 末 / §7 手动核对。

---

## 2. 依赖矩阵（经对抗式核实）

核心渲染链 = `preflight.sh → new-run.sh → render-deck.py → validate.py → finalize.sh`
（外加每个 deck 都带的 `copy-assets.py`）。**该链对第三方包的硬依赖
为零**：纯 stdlib 即可端到端渲染并做静态校验；缺第三方包只让运行期视觉审计静默跳过。

| 依赖 | 需要程度 | 谁在用 | 缺失后果 |
|---|---|---|---|
| **bash** | **required** | 每个 `*.sh`（`#!/usr/bin/env bash`，用到数组 / `[[ ]]` / 进程替换 / `BASH_SOURCE`） | 脚本无法运行；POSIX dash/sh 不兼容。Alpine 需 `apk add bash`。无 sh 回退。 |
| **python3 (≥ 3.9)** | **required** | `render-deck.py`、`validate.py`、`validate-deck.py`、`deck-cli.py`、`copy-assets.py`、`finalize.sh`、`build.sh`（多处**无 `command -v` 守卫**） | 整个 skill 无法渲染。**地板是 3.9**：`argparse.BooleanOptionalAction`（validate.py / check-only.py）在默认校验路径上无 fallback，<3.9 在 parser 构建期崩；另有外围文件用 PEP 585 内建泛型注解在 def 期求值，3.8 会 `TypeError`。3.9 也已满足 RO-mount python 镜像 fallback 用到的 `shutil.copytree(dirs_exist_ok=)`（3.8+）。无 3.10 专属特性。 |
| **playwright + chromium** | optional | `validate.py`（视觉审计）、`render-deck.py --visual`（经 subprocess 间接调 validate.py）、`grow-box-fit.py`、`check-distribution.py` | **核心路径优雅降级**：`validate.py` 的 import 为函数内 `try/except ImportError`，缺失时打印一行 stderr NOTICE 并 `return`，**不产 issue、仍 exit 0**，deck 照常渲染通过；只有运行期视觉审计（R-OVERFLOW / R-OVERLAP / R-VIS-TIER 等）被跳过。`render-deck.py` 默认 `--no-visual`，自身从不 import playwright。**仅外围工具硬失败**：`check-distribution.py` 无守卫 import → ModuleNotFoundError；`grow-box-fit.py` → exit 2。安装见 §1，**外加** Chromium 系统 .so（§7）。 |
| **PyYAML (yaml)** | conditional | `check-only.py`（仅 `--gate`）、`reskin.py` | **核心渲染/校验链完全不 import yaml**，缺它不影响渲染。仅：`check-only --gate` ingest 模式 `sys.exit(2)`；`reskin.py` 模块加载期 `sys.exit(1)`。`check-mira.sh` 缺它仅 WARN（跳过深度 frontmatter 解析），不阻塞。`pip install pyyaml`。 |
| **beautifulsoup4 (bs4)** | optional | **仅** `reskin.py`（外来 HTML 重新配色工具） | 仅 `reskin.py` 模块加载期 `sys.exit(1)`。渲染/校验链全无 bs4 import，不受影响。`pip install beautifulsoup4`。 |
| **git** | conditional | `new-run.sh`、`preflight.sh`、`check-mira.sh` | **核心路径不硬失败**。`new-run.sh` 用 `git rev-parse --show-toplevel` 决定 `runs/` 落点，有 `if` 守卫 + 非 git 回退到 `SKILL_ROOT`，缺它只是 `runs/` 落 skill 根而非 repo 顶。`preflight.sh` 跨 clone 扫描由 `command -v git` 守卫（软警告）。 |
| **node** | optional | `preflight.sh`（`node --check visual-audit.js`，约 50ms 语法预检） | 由 `command -v node` 守卫；缺它该检查静默跳过，preflight 落 `PREFLIGHT OK`。视觉审计真正引擎是 Playwright/Chromium 而非 node CLI，功能不退化。 |
| **rsync** | optional | `preflight.sh`（RO-mount 镜像）、`package-skill.sh`（打包） | 由 `command -v rsync` 守卫，缺它回退到 python3 `shutil.copytree`。**仅当 rsync 与 python3 都缺**时 preflight `exit 2` / package `exit 1`。单缺 rsync 无用户可见影响。 |
| **tar** | conditional | 仅 `package-skill.sh`（slim 分发打包） | `tar -czf` **无守卫**：缺它不产出 tarball。`--dir-only` 模式在调用 tar 前 `exit 0` 可绕过。只影响**打包 skill**，不影响 deck 生成。仅用可移植 `-czf`/`-xzf`。 |
| **find / sed / cp / date** | required | 多个 `*.sh`（slug / 时间戳 / 暂存 / 扫描） | POSIX-baseline。**无 `sed -i`**（规避 BSD/GNU `-i` 陷阱）；`cp -R`（非 `-r`，两边通用）；`date` 仅 `+FORMAT`/`+%s`（不碰 GNU `-d`/BSD `-v`）。 |
| **stat / mktemp / chmod / du / awk / wc·tr·cut·head·tail·grep** | conditional | 各 `*.sh` 尺寸/临时/权限/计数 | 多为外围或诊断路径。`stat` 各调用均 BSD `-f`/GNU `-c` 双 flavor 守卫。 |
| **numfmt / tput / gh** | optional | 仅 `check-mira.sh` | 均守卫：`numfmt`（GNU-only）回退原始字节串；`tput` 回退无色；`gh` `mark_skip`（只 push 流程才需）。纯外观/可选，无功能损失。 |
| **CJK 字体（Noto Sans SC 等）** | Linux 容器上**事实必需**于视觉审计/截图 | `feishu-deck.css`（`--fs-font-cjk`）、Playwright 截图、`visual-audit.js` 几何测量 | `check-mira.sh` **不检测**。精简 Debian/Ubuntu/Alpine 默认无任何 CJK 字体，Chromium 把中文渲染成 tofu：(1) 截图空框；(2) 更隐蔽——tofu 字宽与折行点不同，R-OVERFLOW / R-VIS-ORPHAN 等几何审计产**假阳/假阴**（静默）。`apt-get install fonts-noto-cjk`。 |

> **说明**：没有 `subprocess` 调外部 CLI——每个 `*.py` 的 `subprocess.run(...)` 都用
> `sys.executable` 重入同级 `.py`。git/gh/rsync/tar/node/sed/awk 只在 `.sh` 层。
> Playwright 全程作为 **Python 库** import（处处 `try/except` 守卫），从不作为 CLI。

---

## 3. 环境变量

脚本只读取**两个**环境变量（均在 `preflight.sh`）。

| 变量 | 默认 | 作用 |
|---|---|---|
| **FS_DECK_WORKSPACE** | `$PWD/.feishu-deck-h5-workspace` | RO-mount bootstrap 时可写镜像的落点。**仅在 skill 根不可写的分支被读取**——可写挂载下不生效。其父目录会被探测可写性；父目录不可写则 `exit 2` 并提示设此变量。**故：RO 挂载且 `$PWD` 不可写时，操作者必须把它指向一个可写目录。** |
| **FS_DECK_NOCACHE** | 未设（= 用缓存） | 纯性能旋钮，只影响 Check 5 跨 clone 软警告。空时复用 `.feishu-deck-h5-preflight-cache`（TTL 24h）；非空则跳过缓存重扫。**永不改退出码、永不阻塞**。常规保持不设。 |

> 另：`PYTHONUTF8=1` 不是本 skill 读取的变量，但建议在容器里设它（或 `LANG=C.UTF-8`）
> 作为**双保险**——见 §7。

---

## 4. 安装步骤

**A. 产出 lean 分发包（在一台已装好 skill 的机器上）**

```bash
bash assets/package-skill.sh            # 产物：dist/feishu-deck-h5-<YYYYMMDD>.tar.gz
bash assets/package-skill.sh --verify   # 顺带在精简副本上跑 check-mira.sh 自检
bash assets/package-skill.sh --dir-only # 只做暂存目录、不打 tar
```

打包会排除 `runs/`、`.git/`、`__pycache__`、`*.bak`、**689MB 的 pptx example 语料**等，
仅留渲染所需：843MB → 约 68MB tarball。

**B. 在目标平台解包并就位**

```bash
tar -xzf feishu-deck-h5-<YYYYMMDD>.tar.gz -C <skills-dir>/   # 归档根是干净的 feishu-deck-h5/
```

放置位置要让 `<skills-dir>/feishu-deck-h5/` 下能看到全部 **9 个 REQUIRED 文件**
（否则 preflight `exit 1`）。本文（INSTALL-CLOUD.md）随包同行，解包后就在 skill 根。

**C. 安装运行时依赖（云端 Linux 容器完整版）** — 见 §1 的四行；无 `requirements.txt`，
三个 pip 包各把守不同外围功能，且都在**运行期失败时**才暴露需求，所以没有清单会
一次崩一个地发现。无版本 pin。

**D. RO 挂载（Mira / `/opt` 只读挂载）** — 合法，走 **PREFLIGHT BOOTSTRAPPED**：preflight
探测到根不可写后，把整个 skill 镜像（rsync 或 python3 `shutil.copytree` 回退）到一块
可写工作区，`chmod -R u+w` 后打印工作区路径。要点：

- 保证 `$PWD` 可写（默认落 `$PWD/.feishu-deck-h5-workspace`），**或**设 `FS_DECK_WORKSPACE`；
- 保证 `python3`（首选，本就是硬渲染依赖）**或** `rsync` 至少有一个；
- 看到 `PREFLIGHT BOOTSTRAPPED` 后，agent **必须先 `cd` 进打印出的工作区路径**，再跑
  任何后续命令。镜像不含 `.git/`，`runs/` 会落在工作区内——正是 harness 取回产物之处。

---

## 5. 安装后验证

```bash
bash assets/check-mira.sh
```

纯 sanity check（`set +e`），无 LLM、约 5 秒。共 **7 个 check 组**；只有 `mark_fail`
（强制项）让整体 `exit 1`，`mark_warn` / `mark_skip` 都不阻塞退出码。

1. **SKILL.md frontmatter** — `name == feishu-deck-h5`；`description ≤ 1024`（Codex/Mira 上限）。
2. **Preflight mount** — 跑 `preflight.sh`，须 `PREFLIGHT OK` 或 `PREFLIGHT BOOTSTRAPPED`。
3. **Runtime deps** — `python3`（缺=FAIL）、`git`（缺=FAIL）、`gh`（缺=SKIP）、`pyyaml`（缺=WARN）、`playwright`（缺=SKIP）。
4. **runs/ writable** — 实跑 `new-run.sh`，断言 `input/` + `output/` 可写回读。
5. **Framework assets** — 校验 11 个固定文件存在且非空。
6. **Validator dry-run** — `validate.py examples/sample-deck.html --no-visual`，验证 harness **能跑** validator。
7. **Git** — 非 git 安装 SKIP（正常）；git repo 则 `git status` 须成功。

**阻塞性依赖只有 python3、git、那 11 个框架文件。** 没装 gh/pyyaml/playwright 也能绿过
（代价分别是 push / 深度 frontmatter 解析 / 视觉审计）。

> ⚠️ **绿过 ≠ 容器就绪**：check-mira 不探测 UTF-8 locale、CJK 字体，也不真正 launch
> Chromium。云端容器请额外手动核对：
> ```bash
> locale | grep -i utf            # 应为 *.UTF-8
> fc-list :lang=zh | head         # 应有 CJK 字体输出
> python -m playwright install --dry-run chromium
> ```

---

## 6. 按 PREFLIGHT 退出码排障

`preflight.sh` 是硬闸门，先于一切工作运行。stdout 第一行恒为
`PREFLIGHT OK` / `PREFLIGHT BOOTSTRAPPED` / `PREFLIGHT FAIL · exit N`。

| 退出码 | 含义 | 处置 |
|---|---|---|
| **0 · OK** | skill 根可写，原地运行 | 无需动作，从 `$SKILL_ROOT` 直接跑。 |
| **0 · BOOTSTRAPPED** | 根曾只读，已镜像到可写工作区 | agent **必须先 `cd` 进打印出的 `workspace (RW) : <path>`** 再跑后续命令。 |
| **1** | 未检测到挂载 / 源缺 REQUIRED 文件 | mount 空或不完整：clone repo 进挂载，或复制全量 9 个 REQUIRED 文件。**STOP**。 |
| **2** | 根只读 **且** 无可写区可 bootstrap | (a) 工作区**父目录**不可写 → 设 `FS_DECK_WORKSPACE=<writable-dir>` 或改 RW 挂载；(b) 镜像产不出（rsync 与 python3 都缺）→ 装 python3（首选）或 rsync。**STOP**。 |
| **3** | 只在 `*/mnt/outputs/*` 等临时输出目录运行（会话间擦除） | 让用户挂载真实本地工作目录并从中重跑。「仅 ephemeral 输出」== 「无挂载」，硬拒绝。**STOP**。 |
| **4** | `visual-audit.js` JS 语法错误（**仅装了 node** 且 `node --check` 失败才触发） | 跑 `node --check .../assets/visual-audit.js` 看解析错误并修 JS。**STOP**。 |

> `new-run.sh` 退出码：0 = run 目录已建；1 = 无法创建（权限/无挂载）。

---

## 7. 可移植性 & CJK 注意事项

**locale / UTF-8 — 默认路径已 locale 无关（本次加固）。**
此前 `validate.py` 用裸 `Path('visual-audit.js').read_text()`（无 `encoding=`），而该
文件含数千个 CJK 字节；在 `LANG=C` / `LC_ALL=C` / `POSIX`（精简 Linux 基镜与多数 CI
runner 的默认 locale）下按 ASCII 解码会抛 `UnicodeDecodeError`，**在默认 `--visual` 路径
上硬崩**（且只在装了 playwright 时才走到——正是最完整准备的容器画像）。
**现已修复**：该处与另外 7 处外围文件的全部文本 I/O（`read_text` / `write_text` /
`open`）均显式 `encoding='utf-8'`，端到端校验在 `PYTHONUTF8=0 LC_ALL=C` 下实测通过。

- 因此设不设 UTF-8 locale，**默认 deck 渲染/校验链都不会再因此崩**。
- 仍**建议**设 `export LANG=C.UTF-8`（或 `PYTHONUTF8=1`）作为双保险：保证 Chromium 拿到
  正确字体环境、shell 层中文输出不乱码、未来新增代码不再踩同一坑。

**CJK 字体（Playwright/截图事实必需）** — 见 §2 末行。精简镜像无任何 CJK 字体时
Chromium 把中文渲染成 tofu，既毁截图预览，又让 `visual-audit.js` 的几何测量
（`getBoundingClientRect` / `scrollHeight` 等）基于**错误字体**算出 R-OVERFLOW /
R-VIS-ORPHAN / R-VIS-BODY-FLOOR 等**静默错误的几何裁决**。

```bash
apt-get install -y fonts-noto-cjk        # 或 fonts-wqy-zenhei
fc-list :lang=zh | head                   # 验证：应有输出
```

CSS 字体栈（`--fs-font-cjk`）声明「方正兰亭黑 Pro → Noto Sans SC → PingFang SC →
微软雅黑 → system-ui」；服务器上**连回退字体本身都不存在**，所以这是「能不能正确
渲染中文」的问题，不只是「像素级匹配授权字体」的锦上添花。

**Chromium 系统库** — `pw.chromium.launch(headless=True)` 在 bare-minimal Debian/Ubuntu
上会因缺 `libnss3` / `libatk-1.0` / `libcups` / `libdrm` / `libgbm` / `libxkbcommon` /
`libpango` 等 .so 失败，直到跑 `playwright install-deps chromium`（或 apt 等价物）。这是
区别于「pip install playwright」与「playwright install chromium」的**第三个独立步骤**。
注意 `run_visual_audits` 的 `try/except` 只守 **import**、不守 **launch**：纯 ImportError 优雅
跳过，但 launch 失败属另一类（内层 `except` 降为 R-VISUAL 警告；`--strict` 下提升为
error → `exit 4`）。所以系统库该装齐还得装齐。

**GNU/BSD coreutils** — 可移植性良好：`stat` 处处 BSD `-f` + GNU `-c` 双 flavor 兜底；
`numfmt`（GNU-only）守卫后回退字节串；`du` 只用 `-sh`/`-sk`（含 macOS Seatbelt 绝对路径
报 0B 的 `cd`-相对 workaround）；`date` 只用 `+FORMAT`/`+%s`；**无 `sed -i`**；`tar -czf`、
`cp -R` 用可移植标志。真正硬点是 **bash 必须存在**（脚本非 POSIX-sh 兼容）；Alpine 需
`apk add bash`。

**shared 资产权限（不同 UID 容器）** — `assets/shared/digital_employee_avatars_50` 目录是
`0o700`（仅属主可读）。`copy-assets.py` 默认 `--shared=link` 用 symlink。同 UID 单用户无碍；
但容器里 agent 进程 UID 与解包 UID 不同时（挂载卷/解 tar 常见），该目录不可读，引用
数字员工头像的 deck 会得到坏图。建议：运行 UID 不同则 `chmod -R a+rX assets/shared`；
要把交付物带出容器时优先 `copy-assets.py --shared=copy`（避免 symlink 指回 RO 挂载被
丢失）。
