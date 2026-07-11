#!/usr/bin/env bash
# feishu-deck-h5 · install script
#
# Installs this skill into Claude Code (or any compatible harness that follows
# the ~/.claude/skills/ convention) by:
#   1. Cloning to $INSTALL_DIR (default: ~/Projects/feishu-deck-h5)
#   2. Symlinking skills/feishu-deck-h5 into $CLAUDE_DIR/skills/feishu-deck-h5
#   3. Running preflight to verify
#
# Usage:
#   bash install.sh                              # clone/update + safe link
#   bash install.sh --link-only                  # use INSTALL_DIR, no network
#   bash install.sh --force --backup             # replace after preserving old path
#
# Environment variables:
#   INSTALL_DIR   where to keep the working clone (default: ~/Projects/feishu-deck-h5)
#   CLAUDE_DIR    skill registration root (default: ~/.claude — use ~/.openclaw etc. for other harnesses)
#   REPO_URL      override the git remote (default: git@github.com:FuQiang/feishu-deck-h5.git)
#   PREFLIGHT_PROFILE capability verified after linking (default: generate)

set -e

FORCE=0
BACKUP=0
LINK_ONLY=0
while [ "$#" -gt 0 ]; do
  case "$1" in
    --force) FORCE=1 ;;
    --backup) BACKUP=1 ;;
    --link-only) LINK_ONLY=1 ;;
    -h|--help)
      sed -n '1,24p' "$0"
      exit 0
      ;;
    *) echo "ERROR — unknown option: $1" >&2; exit 64 ;;
  esac
  shift
done
if [ "$FORCE" -eq 1 ] && [ "$BACKUP" -ne 1 ]; then
  echo "ERROR — --force is accepted only together with --backup" >&2
  exit 64
fi

REPO_URL="${REPO_URL:-git@github.com:FuQiang/feishu-deck-h5.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/Projects/feishu-deck-h5}"
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
SKILLS_DIR="$CLAUDE_DIR/skills"
LINK_PATH="$SKILLS_DIR/feishu-deck-h5"
PREFLIGHT_PROFILE="${PREFLIGHT_PROFILE:-generate}"

echo "==> feishu-deck-h5 install"
echo "    repo:    $REPO_URL"
echo "    target:  $INSTALL_DIR"
echo "    symlink: $LINK_PATH"
echo

if [ "$LINK_ONLY" -eq 0 ]; then
  # Prereq 1: SSH access to GitHub
  SSH_OUT="$(ssh -T -o BatchMode=yes -o ConnectTimeout=5 git@github.com 2>&1 || true)"
  if ! echo "$SSH_OUT" | grep -q "successfully authenticated\|Hi "; then
    echo "ERROR — SSH to github.com failed. Make sure your SSH key is registered:"
    echo "  https://github.com/settings/keys"
    echo "  Test with: ssh -T git@github.com"
    exit 1
  fi
  GH_USER="$(echo "$SSH_OUT" | sed -n 's/^Hi \([^!]*\)!.*/\1/p')"

  # Prereq 2: access to this specific repo (collaborator on private repo)
  if ! git ls-remote "$REPO_URL" HEAD >/dev/null 2>&1; then
  cat <<EOF

ERROR — your SSH key works, but you don't have access to FuQiang/feishu-deck-h5
(it's a private repo). Send this message to FuQiang on Lark/Feishu:

  ──────────────────────────────────────────────────────────────
  你好 FuQiang，想用一下 feishu-deck-h5 这个 skill，
  请把我加为仓库 collaborator：

  · GitHub 用户名: ${GH_USER:-<你的 GitHub username, 在 https://github.com 登录后右上角>}
  · 仓库: https://github.com/FuQiang/feishu-deck-h5
  · 添加入口（FuQiang 这边点）:
    https://github.com/FuQiang/feishu-deck-h5/settings/access
  ──────────────────────────────────────────────────────────────

收到 GitHub 邀请邮件后点 "Accept invitation"，然后重新运行本脚本。

EOF
    exit 2
  fi
fi

# 1. clone (or update if exists)
if [ "$LINK_ONLY" -eq 1 ]; then
  if [ ! -f "$INSTALL_DIR/skills/feishu-deck-h5/SKILL.md" ]; then
    echo "ERROR — --link-only requires a complete clone at $INSTALL_DIR" >&2
    exit 1
  fi
  echo "==> link-only: using existing clone at $INSTALL_DIR"
elif [ -d "$INSTALL_DIR/.git" ]; then
  echo "==> existing clone found at $INSTALL_DIR, pulling latest..."
  git -C "$INSTALL_DIR" pull --ff-only
else
  echo "==> cloning..."
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

# 2. symlink into $CLAUDE_DIR/skills/
mkdir -p "$SKILLS_DIR"
TARGET_PATH="$INSTALL_DIR/skills/feishu-deck-h5"
LINK_NEEDED=1
if [ -L "$LINK_PATH" ]; then
  TARGET_PHYSICAL="$(cd "$TARGET_PATH" && pwd -P)"
  LINK_PHYSICAL="$(cd "$LINK_PATH" 2>/dev/null && pwd -P || true)"
  if [ -n "$LINK_PHYSICAL" ] && [ "$LINK_PHYSICAL" = "$TARGET_PHYSICAL" ]; then
    echo "==> symlink already correct; leaving it unchanged"
    LINK_NEEDED=0
  fi
fi

if [ "$LINK_NEEDED" -eq 1 ] && { [ -L "$LINK_PATH" ] || [ -e "$LINK_PATH" ]; }; then
  if [ "$FORCE" -ne 1 ] || [ "$BACKUP" -ne 1 ]; then
    echo "ERROR — refusing to replace existing skill path: $LINK_PATH" >&2
    if [ -L "$LINK_PATH" ]; then
      echo "  current symlink -> $(readlink "$LINK_PATH")" >&2
    else
      echo "  current path is a real file/directory and may contain local work" >&2
    fi
    echo "  Re-run with --force --backup to preserve it before replacement." >&2
    exit 3
  fi
  BACKUP_PATH="$LINK_PATH.backup-$(date +%Y%m%d-%H%M%S)"
  mv "$LINK_PATH" "$BACKUP_PATH"
  echo "==> backed up existing path: $BACKUP_PATH"
fi
if [ "$LINK_NEEDED" -eq 1 ]; then
  ln -s "$TARGET_PATH" "$LINK_PATH"
  echo "==> symlinked: $LINK_PATH -> $TARGET_PATH"
fi

# 3. verify
echo
echo "==> running preflight..."
if bash "$LINK_PATH/assets/preflight.sh" --profile "$PREFLIGHT_PROFILE"; then
  echo
  echo "==> DONE. Restart your Claude Code / harness session to pick up the new skill."
else
  echo
  echo "WARN — preflight failed. The skill is installed but the current directory"
  echo "may not be a writable mount. cd into a real project before generating decks."
  echo "(See SKILL.md PREFLIGHT for details.)"
  exit 1
fi
