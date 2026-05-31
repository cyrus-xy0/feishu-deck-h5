#!/usr/bin/env bash
# feishu-deck-h5 · check-only mode (bash launcher)
#
# 用法: bash check-only.sh <html-path> [--strict] [--no-visual] [--report PATH]
#
# 跟 finalize.sh 不一样: 不跑 copy-assets, 不跑 extract-texts, 不要求
# 在 runs/<ts>/output/ 工作目录里; 适合对外部 / 他人交付的 HTML deck
# 做 PR-review 式的合规扫描.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  cat <<'EOF' >&2
Usage: bash check-only.sh <html-path> [--strict] [--no-visual] [--report PATH]

Args:
  <html-path>   待检查的 HTML 文件
  --strict      把 warn 升级为 error
  --no-visual   关闭 Playwright 视觉审计 (默认开启, 与 validate.py 对齐;
                未装 playwright + chromium 时自动跳过, 不硬失败)
  --report PATH 把 markdown 报告写到指定文件; 不带则打到 stdout

Examples:
  bash check-only.sh ~/Downloads/foreign-deck.html
  bash check-only.sh ../examples/sample-deck.html --report ~/Desktop/check.md
  bash check-only.sh /path/to/deck.html --strict --no-visual
EOF
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/check-only.py" "$@"
