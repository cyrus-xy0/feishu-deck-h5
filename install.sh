#!/usr/bin/env bash
# feishu-deck-h5 · install script
#
# Installs this skill suite into Claude Code (or any compatible harness that
# follows the ~/.claude/skills/ convention) by:
#   1. Cloning to $INSTALL_DIR (default: ~/Projects/feishu-deck-h5)
#   2. Symlinking the active feishu-deck-h5 and pptx-to-deck sibling skills
#   3. Bootstrapping PPTX dependencies when the selected profile needs them
#   4. Running preflight to verify
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
#   PREFLIGHT_PROFILE capability verified after linking (default: pptx)

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
PREFLIGHT_PROFILE="${PREFLIGHT_PROFILE:-pptx}"
SKILL_NAMES=("feishu-deck-h5" "pptx-to-deck")

echo "==> feishu-deck-h5 install"
echo "    repo:    $REPO_URL"
echo "    target:  $INSTALL_DIR"
echo "    skills:  ${SKILL_NAMES[*]}"
echo "    profile: $PREFLIGHT_PROFILE"
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
  for skill_name in "${SKILL_NAMES[@]}"; do
    if [ ! -f "$INSTALL_DIR/skills/$skill_name/SKILL.md" ]; then
      echo "ERROR — --link-only requires skills/$skill_name at $INSTALL_DIR" >&2
      exit 1
    fi
  done
  echo "==> link-only: using existing clone at $INSTALL_DIR"
elif [ -d "$INSTALL_DIR/.git" ]; then
  echo "==> existing clone found at $INSTALL_DIR, pulling latest..."
  git -C "$INSTALL_DIR" pull --ff-only
else
  echo "==> cloning..."
  mkdir -p "$(dirname "$INSTALL_DIR")"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

# 2. symlink active sibling skills into $CLAUDE_DIR/skills/
mkdir -p "$SKILLS_DIR"
link_skill() {
  local skill_name="$1"
  local target_path="$INSTALL_DIR/skills/$skill_name"
  local link_path="$SKILLS_DIR/$skill_name"
  local link_needed=1

  if [ -L "$link_path" ]; then
    local target_physical link_physical
    target_physical="$(cd "$target_path" && pwd -P)"
    link_physical="$(cd "$link_path" 2>/dev/null && pwd -P || true)"
    if [ -n "$link_physical" ] && [ "$link_physical" = "$target_physical" ]; then
      echo "==> $skill_name symlink already correct; leaving it unchanged"
      link_needed=0
    fi
  fi

  if [ "$link_needed" -eq 1 ] && { [ -L "$link_path" ] || [ -e "$link_path" ]; }; then
    if [ "$FORCE" -ne 1 ] || [ "$BACKUP" -ne 1 ]; then
      echo "ERROR — refusing to replace existing skill path: $link_path" >&2
      if [ -L "$link_path" ]; then
        echo "  current symlink -> $(readlink "$link_path")" >&2
      else
        echo "  current path is a real file/directory and may contain local work" >&2
      fi
      echo "  Re-run with --force --backup to preserve it before replacement." >&2
      exit 3
    fi
    local backup_path
    backup_path="$link_path.backup-$(date +%Y%m%d-%H%M%S)"
    mv "$link_path" "$backup_path"
    echo "==> backed up existing path: $backup_path"
  fi

  if [ "$link_needed" -eq 1 ]; then
    ln -s "$target_path" "$link_path"
    echo "==> symlinked: $link_path -> $target_path"
  fi
}

# Fail closed before creating any link so a conflict in the second sibling does
# not leave a partially-installed skill set.
for skill_name in "${SKILL_NAMES[@]}"; do
  target_path="$INSTALL_DIR/skills/$skill_name"
  link_path="$SKILLS_DIR/$skill_name"
  link_matches=0
  if [ -L "$link_path" ]; then
    target_physical="$(cd "$target_path" && pwd -P)"
    link_physical="$(cd "$link_path" 2>/dev/null && pwd -P || true)"
    if [ -n "$link_physical" ] && [ "$link_physical" = "$target_physical" ]; then
      link_matches=1
    fi
  fi
  if [ "$link_matches" -eq 0 ] && { [ -L "$link_path" ] || [ -e "$link_path" ]; }; then
    if [ "$FORCE" -ne 1 ] || [ "$BACKUP" -ne 1 ]; then
      echo "ERROR — refusing to replace existing skill path: $link_path" >&2
      if [ -L "$link_path" ]; then
        echo "  current symlink -> $(readlink "$link_path")" >&2
      else
        echo "  current path is a real file/directory and may contain local work" >&2
      fi
      echo "  No links were changed. Re-run with --force --backup to preserve conflicts." >&2
      exit 3
    fi
  fi
done

for skill_name in "${SKILL_NAMES[@]}"; do
  link_skill "$skill_name"
done

# 3. bootstrap the optional PPTX runtime only when that capability is requested.
case "$PREFLIGHT_PROFILE" in
  pptx|template)
    echo
    echo "==> bootstrapping pptx-to-deck Python runtime..."
    bash "$INSTALL_DIR/skills/pptx-to-deck/assets/bootstrap.sh"
    ;;
esac

# 4. verify
echo
echo "==> running preflight..."
if bash "$SKILLS_DIR/feishu-deck-h5/assets/preflight.sh" --profile "$PREFLIGHT_PROFILE"; then
  echo
  echo "==> DONE. Restart your Claude Code / harness session to pick up the new skill."
else
  echo
  echo "WARN — preflight failed. The skill is installed but the current directory"
  echo "may not be a writable mount. cd into a real project before generating decks."
  echo "(See SKILL.md PREFLIGHT for details.)"
  exit 1
fi
