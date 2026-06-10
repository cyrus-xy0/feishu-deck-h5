#!/usr/bin/env python3
"""
feishu-deck-h5 · Claude Code PostToolUse guard  (handed into the repo for F-266)

WHAT THIS IS
  A Claude-Code hook that fires AFTER the Write/Edit tool writes a file. If the
  model hand-wrote a feishu-deck index.html (Path B — bypassing render-deck.py),
  it runs validate.py on it; if the deck is non-compliant it BLOCKS and feeds the
  report back to the model so it must fix it to a clean exit.

WHY IT EXACTLY CATCHES ONLY PATH B
  render-deck.py writes index.html via Python open() — that does NOT go through
  the Write tool, so this PostToolUse(Write) hook NEVER fires on a normal render
  output. It only fires when a model DIRECTLY Writes an index.html — which is
  precisely the Path-B route that skips validate.

DESIGN RULE: the hook must NEVER break the session. Any exception / parse failure
/ missing file → silently pass through (exit 0).

  -----------------------------------------------------------------------------
  ⚠️ THIS HOOK IS CLAUDE-CODE-ONLY. Codex / cloud agents have no PostToolUse
  hook mechanism, so this file is NOT the model-agnostic enforcement. The
  repo-level, model-agnostic half of Gate 1 is R-PROVENANCE in
  assets/run-audits.py — it stamps + verifies every render-deck.py output and
  runs in BOTH validate paths regardless of which model/harness drove the
  render. See INSTALL-CLOUD.md §8 and references/validator-rules.md (R-PROVENANCE).
  -----------------------------------------------------------------------------

INSTALL (Claude Code only)
  1. Copy this file somewhere stable, e.g. ~/.claude/hooks/validate-deck-write.py
     and `chmod +x` it.
  2. EDIT the SKILL constant below to point at YOUR installed skill path (this
     copy hardcodes the original author's home — it is portable code but the
     path must match your machine; the script no-ops harmlessly if the path is
     wrong, but then it can't validate).
  3. Register it as a PostToolUse hook in ~/.claude/settings.json, e.g.:

       {
         "hooks": {
           "PostToolUse": [
             {
               "matcher": "Write|Edit",
               "hooks": [
                 {"type": "command",
                  "command": "python3 ~/.claude/hooks/validate-deck-write.py"}
               ]
             }
           ]
         }
       }

  Then any hand-written runs/<…>/output/index.html that fails validate.py is
  blocked before the model can call it "done".
"""
import sys, json, subprocess, os

# 飞书技能安装位置 — EDIT THIS to your installed skill path. The original author's
# machine used the path below; a different machine must point it at its own
# skill root (symlink is fine; python follows symlinks). A wrong path → the
# `os.path.exists(VALIDATE)` check fails → the hook passes through (no crash).
SKILL = "/Users/bytedance/.claude/skills/feishu-deck-h5"
VALIDATE = os.path.join(SKILL, "assets", "validate.py")
RUN_AUDITS = os.path.join(SKILL, "assets", "run-audits.py")  # 统一校验引擎 runner


def passthrough():
    """放行:静默 exit 0,不干预。"""
    sys.exit(0)


def surface(msg):
    """非阻断地把信息塞给模型:additionalContext,exit 0,不 block。
    用于 warn 级视觉发现 / 缺依赖提示 —— 让规则结果"被看见"(绝不静默放行),
    但不卡交付(canvas-center 是 warn,且可 data-allow-imbalance opt-out)。"""
    sys.stdout.write(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": msg,
        },
    }, ensure_ascii=False))
    sys.exit(0)


def visual_canvas_center_note(fp):
    """跑统一引擎(audits.js via run-audits.py)的视觉几何档,返回要展示的文字('' = 无)。
    - playwright 缺(rc=2)→ 返回硬提示(可见,绝不静默放行)。
    - 有 R-VIS-CANVAS-CENTER finding → 返回该清单(warn)。
    - 引擎自身异常 → 返回 ''(保持 hook 安全原则,不卡会话)。
    注:写入 hook 只在 Path-B 手搓 index.html 上触发(通常小 deck),整页跑得起。"""
    if not os.path.exists(RUN_AUDITS):
        return ""
    try:
        r = subprocess.run(
            [sys.executable, RUN_AUDITS, fp, "--json"],
            capture_output=True, text=True, timeout=120,
        )
    except Exception:
        return ""  # 引擎异常绝不卡会话
    if r.returncode == 2:
        return (
            "\n\n⚠️ 视觉几何档未执行:统一校验引擎需要 playwright/chromium 才能判定 "
            "R-VIS-CANVAS-CENTER 等「渲染后」规则(静态档做不到)。装好前,本页的居中/"
            "几何类问题不会被自动拦。安装:`pip install playwright && "
            "python -m playwright install chromium`。"
        )
    try:
        data = json.loads(r.stdout or "{}")
    except Exception:
        return ""
    cc = [f for f in data.get("findings", []) if f.get("rule") == "R-VIS-CANVAS-CENTER"]
    if not cc:
        return ""
    lines = "\n".join("  • " + (f.get("message") or "") for f in cc)
    return (
        "\n\n📐 视觉几何档(audits.js · 单规则源)发现内容未在画布垂直居中"
        "(warn;确属设计意图可在该 .slide 加 `data-allow-imbalance` opt-out):\n" + lines
    )


def block(msg):
    """打回:exit 0 + stdout JSON,decision=block 把 msg 反馈给模型。"""
    sys.stdout.write(json.dumps({
        "decision": "block",
        "reason": msg,
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": msg,
        },
    }, ensure_ascii=False))
    sys.exit(0)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        passthrough()

    if data.get("tool_name") not in ("Write", "Edit"):
        passthrough()

    fp = (data.get("tool_input") or {}).get("file_path") or ""
    if not fp.endswith(".html"):
        passthrough()

    # 只管飞书 deck 产物:new-run.sh 产出 runs/<ts>-<slug>/output/index.html,
    # Mira 只读挂载 bootstrap 落在 .feishu-deck-h5-workspace/ 下。纯路径信号。
    low = fp.replace("\\", "/")
    is_deck = low.endswith("/output/index.html") and (
        "/runs/" in low
        or "feishu-deck" in low
        or ".feishu-deck-h5-workspace" in low
    )
    if not is_deck:
        passthrough()

    if not os.path.exists(VALIDATE) or not os.path.exists(fp):
        passthrough()

    # 只跑静态闸(--no-visual):快、无 Playwright/node 依赖。
    # 正好覆盖 case-b 那批硬错:R-CSSVAR / R-LANG / R-KEY / R-WHITE-TEXT / R06 / R20 …
    try:
        r = subprocess.run(
            [sys.executable, VALIDATE, fp, "--no-visual"],
            capture_output=True, text=True, timeout=90,
        )
    except Exception:
        passthrough()  # hook 出错绝不卡会话

    # 统一引擎视觉几何档(audits.js):静态档查不出的渲染后规则(R-VIS-CANVAS-CENTER)。
    # 这一步把"规则的存在"与"规则真跑"焊在一起(UNIFY-VALIDATE-ARCH 步骤 2 闭环)。
    vnote = visual_canvas_center_note(fp)

    if r.returncode == 0:
        # 静态过:有视觉发现 / 缺依赖提示就可见地 surface(绝不静默放行),否则放行。
        if vnote:
            surface(vnote.lstrip("\n"))
        passthrough()

    report = ((r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")).strip()
    if not report:
        report = f"validate.py exited {r.returncode}"

    # 同目录没有 deck.json → 几乎肯定是 Path B 手搓,补一句 Path A 提醒
    nudge = ""
    sib = os.path.join(os.path.dirname(fp), "deck.json")
    if not os.path.exists(sib):
        nudge = (
            "\n\n⚠️ 这个 output/ 目录下没有 deck.json —— 看起来是 Path B 手搓 index.html。"
            "feishu-deck-h5 默认走 Path A:写 deck.json → render-deck.py 渲染"
            "(渲染器自带 validate + 官方 assets + 四档字号 + 品牌色板)。"
            "除非确有理由走 Path B,否则请改用 Path A 重出这一份。"
        )

    # 静态档已挂 → block;视觉几何发现 / 缺依赖提示一并附上。
    block(
        "🚫 feishu-deck-h5 validate.py 未通过 —— 这份手写的 index.html 不合规,"
        "不能当作完成 / 交付。按下面报告改到 exit 0:\n\n" + report + nudge + vnote
    )


if __name__ == "__main__":
    main()
