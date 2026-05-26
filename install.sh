#!/usr/bin/env bash
# feishu-deck-h5 · install script
#
# Installs this skill into Claude Code (or any compatible harness that follows
# the ~/.claude/skills/ convention) by:
#   1. Cloning to $INSTALL_DIR (default: ~/Projects/feishu-deck-h5)
#   2. Symlinking product skills into $CLAUDE_DIR/skills/
#   3. Running preflight to verify
#
# Usage:
#   bash install.sh                              # from inside an existing clone
#   git clone <url> tmp && bash tmp/install.sh   # one-shot from anywhere
#
# Environment variables:
#   INSTALL_DIR   where to keep the working clone (default: ~/Projects/feishu-deck-h5)
#   CLAUDE_DIR    skill registration root (default: ~/.claude — use ~/.openclaw etc. for other harnesses)
#   REPO_URL      override the git remote (default: git@github.com:FuQiang/feishu-deck-h5.git)

set -e

REPO_URL="${REPO_URL:-git@github.com:FuQiang/feishu-deck-h5.git}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/Projects/feishu-deck-h5}"
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
SKILLS_DIR="$CLAUDE_DIR/skills"
SKILL_NAMES=("deck-outline-planner" "feishu-deck-h5" "pitch-rehearsal-simulator")
PRIMARY_LINK_PATH="$SKILLS_DIR/feishu-deck-h5"

echo "==> feishu-deck-h5 install"
echo "    repo:    $REPO_URL"
echo "    target:  $INSTALL_DIR"
echo "    skills:  ${SKILL_NAMES[*]}"
echo "    into:    $SKILLS_DIR"
echo

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

# 1. clone (or update if exists)
if [ -d "$INSTALL_DIR/.git" ]; then
  echo "==> existing clone found at $INSTALL_DIR, pulling latest..."
  git -C "$INSTALL_DIR" pull --ff-only
else
  echo "==> cloning..."
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

# 2. symlink product skills into $CLAUDE_DIR/skills/
mkdir -p "$SKILLS_DIR"
for SKILL_NAME in "${SKILL_NAMES[@]}"; do
  SRC_PATH="$INSTALL_DIR/skills/$SKILL_NAME"
  LINK_PATH="$SKILLS_DIR/$SKILL_NAME"
  if [ ! -d "$SRC_PATH" ]; then
    echo "ERROR — missing skill directory: $SRC_PATH"
    exit 1
  fi
  if [ -L "$LINK_PATH" ] || [ -e "$LINK_PATH" ]; then
    echo "==> removing existing $LINK_PATH..."
    rm -rf "$LINK_PATH"
  fi
  ln -s "$SRC_PATH" "$LINK_PATH"
  echo "==> symlinked: $LINK_PATH -> $SRC_PATH"
done

# 3. verify
echo
echo "==> running preflight..."
if bash "$PRIMARY_LINK_PATH/assets/preflight.sh"; then
  echo
  echo "==> DONE. Restart your Claude Code / harness session to pick up the new skill."
else
  echo
  echo "WARN — preflight failed. The skill is installed but the current directory"
  echo "may not be a writable mount. cd into a real project before generating decks."
  echo "(See SKILL.md PREFLIGHT for details.)"
  exit 1
fi
