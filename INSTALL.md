# Install — agent-readable spec

> This file is the canonical install procedure for `feishu-deck-h5`.
> If you are a Claude (or any AI agent) and the user asked you to install
> this skill from a git URL, follow these steps in order.
> If you are a human, [README.md](./README.md) is friendlier.
>
> **云端 agent 平台 / 只读挂载 / Linux 容器（Mira、Codex 等)**：本文讲的是从 git URL
> 装到 Claude Code。那类场景（无 git/SSH、RO 挂载、用 lean tarball 分发）请改看
> [`skills/feishu-deck-h5/INSTALL-CLOUD.md`](./skills/feishu-deck-h5/INSTALL-CLOUD.md)
> ——含经核实的依赖矩阵、`package-skill.sh` 精简打包、PREFLIGHT 退出码排障、
> CJK 字体 / UTF-8 locale / Chromium 系统库等容器专属注意事项。

## TL;DR for the user

Tell your Claude agent:

> "帮我安装 feishu-deck-h5 这个 skill：`git@github.com:FuQiang/feishu-deck-h5.git`"

The agent will detect your harness, pick the right install path, and verify.

---

## Decision tree (for the agent)

Run these checks **in order**, stop at the first match:

### 1. Plugin marketplace path (Claude Code with `/plugin` support)

**Detect:** the user is running Claude Code CLI / Claude Desktop and `/plugin marketplace add` is a known slash command.

**Action — instruct the user to run:**

```
/plugin marketplace add git@github.com:FuQiang/feishu-deck-h5.git
/plugin install feishu-deck-h5@feishu-deck-h5
```

Then restart the session. (Slash commands cannot be invoked by an agent — the user has to type them.)

**Verify:** after restart, confirm both active skills are registered, bootstrap
the PPTX runtime, and run the PPTX profile:

```bash
bash ~/.claude/skills/pptx-to-deck/assets/bootstrap.sh
bash ~/.claude/skills/feishu-deck-h5/assets/preflight.sh --profile pptx
```

### 2. install.sh path (any harness with `~/.claude/skills/` convention)

**Detect:** plugin marketplace not available, but `~/.claude/skills/` (or `$CLAUDE_DIR/skills/`) is the skill registration directory.

**Action — run as the user:**

```bash
git clone git@github.com:FuQiang/feishu-deck-h5.git /tmp/feishu-deck-h5-installer
bash /tmp/feishu-deck-h5-installer/install.sh
rm -rf /tmp/feishu-deck-h5-installer
```

For Codex or other harnesses, set `CLAUDE_DIR` to that harness's skill root:

```bash
CLAUDE_DIR=~/.codex bash install.sh
CLAUDE_DIR=~/.openclaw bash install.sh
```

**Verify:** the script links both `feishu-deck-h5` and `pptx-to-deck`, bootstraps
the PPTX runtime for the default `pptx` profile, then runs preflight. Look for
`PPTX RUNTIME OK` and `PREFLIGHT OK`.

The installer never deletes an existing skill path. A correct symlink is left
unchanged; a different symlink or real directory is refused so local work is
preserved. To intentionally replace it, use `--force --backup`; the old path is
moved to a timestamped backup before the new link is created.

### 3. Manual path (fallback when nothing else fits)

```bash
git clone git@github.com:FuQiang/feishu-deck-h5.git ~/Projects/feishu-deck-h5
mkdir -p ~/.claude/skills
ln -s ~/Projects/feishu-deck-h5/skills/feishu-deck-h5 ~/.claude/skills/feishu-deck-h5
ln -s ~/Projects/feishu-deck-h5/skills/pptx-to-deck ~/.claude/skills/pptx-to-deck
bash ~/.claude/skills/pptx-to-deck/assets/bootstrap.sh
bash ~/.claude/skills/feishu-deck-h5/assets/preflight.sh --profile pptx
```

---

## Prerequisites (verify before installing)

- SSH key registered with GitHub: `ssh -T git@github.com` returns `Hi <user>!`
- Collaborator access on `FuQiang/feishu-deck-h5` (repo is private — ask FuQiang)
- `python3`, `bash`, `node` on PATH (used by build/validate)

If `ssh -T git@github.com` fails, stop and ask the user to set up their SSH key first — every install path depends on it.

### Don't have collaborator access yet?

If `git ls-remote git@github.com:FuQiang/feishu-deck-h5.git HEAD` fails with
"Repository not found" or "Permission denied" but `ssh -T git@github.com`
works, the user has SSH set up but is not yet a collaborator on this private
repo.

`install.sh` detects this and exits with **code 2**, printing a copy-pasteable
Lark/Feishu message template (with the user's GitHub username pre-filled) for
them to send to FuQiang. The agent should:

1. Show the printed template to the user verbatim
2. Tell them to paste it into Lark to FuQiang
3. Wait for them to confirm the GitHub invitation email arrived + was accepted
4. Re-run `install.sh`

Do **not** try to add them as a collaborator via `gh api` — only the repo owner can do that.

---

## Repo structure (so agents know what they cloned)

```
.claude-plugin/marketplace.json   ← present means: plugin path supported
.claude-plugin/plugin.json
skills/feishu-deck-h5/SKILL.md    ← controller skill
skills/pptx-to-deck/SKILL.md      ← active PPTX conversion sibling
install.sh                        ← present means: install.sh path supported
INSTALL.md                        ← this file
README.md                         ← human-facing docs
```

Any of the three indicators present → that install path is supported.
