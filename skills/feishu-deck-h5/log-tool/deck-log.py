#!/usr/bin/env python3
"""deck-log — 记录一份 feishu-deck-h5 deck 的完整制作过程。

把"我给的输入 / Claude 的返回 / 每个版本的截图 / 校验发现 / 我观察到的问题"
落成一条 append-only 的事件流(journal.jsonl,唯一真相源),再确定性渲染成一份
自包含的单页 making-of.html(给同学看的"制作纪录片"),并能把过程里反复出现的
问题digest 出来,辅助判断"哪些 bug 是 skill 本身该修的"。

它和 deck 成品平行存放,绝不进 out/:

    runs/<deck>/
      out/                     成品(不动)
      log/                     ← 本工具的地盘
        journal.jsonl          唯一真相源:每行一个事件
        inputs/                你给的原始附件(brief / 参考图 / .thmx …)
        screenshots/vNNN/sNN.png   每版整套(每页一张 1920×1080)
        audits/vNNN.json       该版本的几何/校验机读结果
        making-of.html         渲染出的纪录片(可分享)

输入/我的回复不靠 hook 实时记 —— 它们本就完整躺在会话 transcript 里,render 时直接捞
(0 model token,纯文件读)。init 记下当前 transcript 路径+起点,render 取其后的回合,
按时间线和版本/问题/修复并在一起。

子命令
    init      <deck-dir> [--transcript]  搭 log/ 骨架,记下会话 transcript+起点,设为活跃 deck
    snapshot  <deck-dir> [--label …] [--slide N]  Playwright 截图 + 跑校验 → version 事件 + 自动刷新 making-of;--slide N 只刷某页
    event     <deck-dir> --type T ...    追加一条任意事件(problem / fix / note / summary …)
    turns     <deck-dir> [--all]         预览从 transcript 捞到的回合(调试)
    render    <deck-dir> [--inline]      journal + transcript 回合 → making-of.html
    diagnose  <deck-dir>                 输出供大模型分析"哪些是 skill bug"的 digest + 提示词
    on | off | status                    全局开关(默认开;off=写 ~/.claude/deck-log.off → render 不捞 transcript)

设计取舍见同目录 README.md 与 SKILL.md 的「制作日志」一节。
"""
from __future__ import annotations
import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
ACTIVE_PTR = HOME / ".claude" / "deck-log.active"   # 内容 = 当前活跃 deck 的 log/ 绝对路径
OFF_SWITCH = HOME / ".claude" / "deck-log.off"      # 存在即全局停录(凌驾一切,仿 lark-broadcast.off)

DESIGN_W, DESIGN_H = 1920, 1080


# ----------------------------------------------------------------------------- helpers
def _now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _ts_epoch(s) -> float:
    """ISO 时间戳 → epoch 秒,用于*跨时区*正确比较/排序。

    坑:journal 的 start_ts/ts 是本地格式(`...+08:00`),transcript 的 timestamp 是
    UTC(`...Z`)。直接按字符串比大小会把 `16:xxZ`(=北京 00:xx,实际在 start 之后)
    误判成"开工前"丢弃 —— 这是 making-of 流水为空的根因。统一解析成绝对时间点再比。
    解析失败返回 -inf(排最前、不参与过滤)。"""
    if not s:
        return float("-inf")
    try:
        return _dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OSError, OverflowError):
        return float("-inf")


def _log_dir(deck_dir: Path) -> Path:
    """deck-dir 是含 out/ 的那个 run 目录;log/ 是它的兄弟。"""
    deck_dir = deck_dir.resolve()
    # 容错:用户可能直接把 out/ 或 log/ 传进来
    if deck_dir.name in ("out", "log"):
        deck_dir = deck_dir.parent
    return deck_dir / "log"


def _journal(log_dir: Path) -> Path:
    return log_dir / "journal.jsonl"


def append_event(log_dir: Path, obj: dict) -> dict:
    """往 journal.jsonl 追加一条事件(append-only,永不重写)。"""
    log_dir.mkdir(parents=True, exist_ok=True)
    obj.setdefault("ts", _now_iso())
    with _journal(log_dir).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
    return obj


def read_events(log_dir: Path) -> list[dict]:
    jp = _journal(log_dir)
    if not jp.exists():
        return []
    out = []
    for line in jp.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass  # 容错:坏行跳过,不让一行毁掉整份日志
    return out


def _version_nums(log_dir: Path) -> list[int]:
    """已有的版本号列表(从 screenshots/vNNN 推导;不再依赖已废弃的 versions/ 冻结目录)。"""
    shots = log_dir / "screenshots"
    nums = []
    if shots.exists():
        for d in shots.iterdir():
            m = re.fullmatch(r"v(\d{3})", d.name)
            if m:
                nums.append(int(m.group(1)))
    return sorted(nums)


def _next_version(log_dir: Path) -> str:
    nums = _version_nums(log_dir)
    return f"v{(nums[-1] + 1) if nums else 1:03d}"


def _latest_version(log_dir: Path) -> str | None:
    nums = _version_nums(log_dir)
    return f"v{nums[-1]:03d}" if nums else None


# ------------------------------------------------------ transcript ingest (无 hook 方案)
# 输入和我的原始回复本来就完整躺在会话 transcript 里(~/.claude/projects/<slug>/<sid>.jsonl)。
# 不用常驻 hook 实时镜像 —— render 时直接从 transcript 捞这一段(0 model token,纯文件读)。
_PROJECTS = HOME / ".claude" / "projects"
# 斜杠命令 / 命令机器产物 / harness 注入的伪用户消息,不是真·人类输入,过滤掉
_CMD_PREFIXES = ("<command-name>", "<command-message>", "<command-args>",
                 "<local-command-stdout>", "<local-command-stderr>", "<user-memory-input>",
                 "<task-notification>", "<system-reminder>")


def _find_current_transcript() -> str | None:
    """当前会话的 transcript = ~/.claude/projects/*/ 下最近改动的 .jsonl(本会话正在写它)。"""
    if not _PROJECTS.exists():
        return None
    cands = list(_PROJECTS.glob("*/*.jsonl"))
    if not cands:
        return None
    return str(max(cands, key=lambda p: p.stat().st_mtime).resolve())


def _is_real_prompt(text: str) -> bool:
    t = text.lstrip()
    return bool(t) and not t.startswith(_CMD_PREFIXES)


def _text_from_content(content) -> str:
    """transcript 的 message.content 可能是 str,也可能是 block 列表。
    新版会话格式里真·用户输入多为 [{"type":"text","text":...}],旧版才是裸 str。
    只抽 text block,忽略 tool_result / image / thinking 等。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        ).strip()
    return ""


def extract_turns(transcript: str, since_ts: str | None) -> list[dict]:
    """从 transcript 抽成 turn 列表:把每条真·人类输入配上紧随其后的 assistant 文本。

    since_ts:只取这个时间(init 的起点)之后的记录,把日志 scope 到"做这个 deck"那段。
    """
    p = Path(transcript)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = o.get("timestamp")
        if since_ts and ts:
            te, se = _ts_epoch(ts), _ts_epoch(since_ts)
            # 只在两边都能解析时才过滤,且按绝对时间点(跨时区安全)比较
            if te != float("-inf") and se != float("-inf") and te < se:
                continue
        typ = o.get("type")
        msg = o.get("message") or {}
        content = msg.get("content")
        if typ == "user" and not o.get("isMeta"):
            txt = _text_from_content(content)
            if txt and _is_real_prompt(txt):
                rows.append(("in", ts, txt))
        elif typ == "assistant":
            txt = _text_from_content(content)
            if txt:
                rows.append(("out", ts, txt))

    # 配对:一条 in 收集它之后、下一条 in 之前的所有 out 文本
    turns, cur, n = [], None, 0
    for kind, ts, text in rows:
        if kind == "in":
            if cur:
                turns.append(cur)
            n += 1
            cur = {"t": "turn", "n": n, "ts": ts, "input": text, "output_raw": ""}
        elif kind == "out" and cur is not None:
            cur["output_raw"] = (cur["output_raw"] + "\n\n" + text).strip() if cur["output_raw"] else text
    if cur:
        turns.append(cur)
    return turns


# ----------------------------------------------------------------------------- init
def cmd_init(args) -> int:
    log_dir = _log_dir(Path(args.deck_dir))
    for sub in ("inputs", "screenshots", "audits"):
        (log_dir / sub).mkdir(parents=True, exist_ok=True)
    # 记下"当前活跃 deck"(供 status 查看;render 用 session 事件里的 transcript)
    ACTIVE_PTR.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_PTR.write_text(str(log_dir.resolve()), encoding="utf-8")
    title = args.title or log_dir.parent.name
    transcript = args.transcript or _find_current_transcript()
    start_ts = _now_iso()
    append_event(log_dir, {"t": "session", "title": title, "cwd": str(Path.cwd()),
                           "transcript": transcript, "start_ts": start_ts})
    print(f"✓ deck-log 已就绪:{log_dir}")
    print(f"  活跃指针 → {ACTIVE_PTR}")
    if transcript:
        print(f"  会话 transcript → {transcript}")
        print("  (render 时会从它捞这一刻起的 输入+回复;无需 hook)")
    else:
        print("  ⚠️ 没自动找到 transcript;render 前用 `--transcript <path>` 指一下,否则只记版本/问题。")
    if OFF_SWITCH.exists():
        print("  ⚠️ 全局开关当前为 OFF(~/.claude/deck-log.off 存在);render 不会捞 transcript。`deck-log on` 打开。")
    return 0


# ----------------------------------------------------------------------------- snapshot
_SLIDE_META_JS = r"""
() => {
  const frames = [...document.querySelectorAll('.slide-frame')];
  return frames.map((f, i) => {
    const s = f.querySelector('.slide');
    return {
      idx: i + 1,
      key: (s && (s.getAttribute('data-slide-key') || s.id)) || ('slide-' + (i + 1)),
      layout: (s && s.getAttribute('data-layout')) || '',
    };
  });
}
"""

_SHOW_SLIDE_JS = r"""
(i) => {
  const frames = [...document.querySelectorAll('.slide-frame')];
  frames.forEach((f, j) => f.classList.toggle('is-current', j === i));
  const s = frames[i] && frames[i].querySelector('.slide');
  if (s) s.style.setProperty('--fs-scale', '1');   // viewport 1920×1080 → 1:1
  // 关掉进场 stagger,截到稳定终态
  const deck = document.querySelector('.deck');
  if (deck) deck.setAttribute('data-nav-armed', '');
}
"""


def _shoot(html_path: Path, out_png_dir: Path, only_slide: int | None = None):
    """用 Playwright 把每页截成 1920×1080 的 png。返回本次截到的页 meta 列表,失败返回 None。

    only_slide:仅截第 N 页(1-based)。用于"每页做完只刷那一页"的增量截图,避免
    每次都全量重开浏览器逐页跑(deck 越大越慢)。其余页沿用上一版已有的 png。"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("  ⚠️ 未装 playwright,跳过截图。`pip install playwright && python -m playwright install chromium`",
              file=sys.stderr)
        return None
    out_png_dir.mkdir(parents=True, exist_ok=True)
    url = html_path.resolve().as_uri()
    shots = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": DESIGN_W, "height": DESIGN_H},
                                  device_scale_factor=1)
        page = ctx.new_page()
        page.goto(url, wait_until="load", timeout=60_000)
        page.evaluate("() => { const d=document.querySelector('.deck'); if(d) d.setAttribute('data-mode','present'); }")
        page.wait_for_timeout(300)
        meta = page.evaluate(_SLIDE_META_JS)
        if only_slide is not None:
            meta = [m for m in meta if m["idx"] == only_slide]
            if not meta:
                print(f"  ⚠️ 第 {only_slide} 页不存在,未截图。", file=sys.stderr)
        for m in meta:
            page.evaluate(_SHOW_SLIDE_JS, m["idx"] - 1)
            page.wait_for_timeout(350)
            fn = out_png_dir / f"s{m['idx']:02d}.png"
            page.screenshot(path=str(fn), clip={"x": 0, "y": 0, "width": DESIGN_W, "height": DESIGN_H})
            m["png"] = fn.name
            shots.append(m)
        browser.close()
    return shots


def _run_distribution_audit(html_path: Path) -> dict | None:
    """复用 skill 现成的 check-distribution.py --json 拿机读几何发现。"""
    import subprocess
    script = Path(__file__).resolve().parent.parent / "assets" / "check-distribution.py"
    if not script.exists():
        return None
    try:
        rc = subprocess.run([sys.executable, str(script), str(html_path), "--json"],
                            capture_output=True, text=True, timeout=180)
        if rc.stdout.strip():
            return json.loads(rc.stdout)
    except Exception as e:
        print(f"  ⚠️ 分布校验跳过:{e}", file=sys.stderr)
    return None


def cmd_snapshot(args) -> int:
    deck_dir = Path(args.deck_dir).resolve()
    log_dir = _log_dir(deck_dir)
    html_path = Path(args.html) if args.html else (
        deck_dir / "out" / "index.html" if (deck_dir / "out").exists()
        else deck_dir / "index.html")
    if not html_path.exists():
        print(f"✗ 找不到 deck html:{html_path}", file=sys.stderr)
        return 2

    only = getattr(args, "slide", None)

    # ---- 增量模式:只刷某一页 ----
    # 覆盖最新版本里那一页的 png(秒级、只开一次浏览器截一张),不新建版本、不动 journal。
    # making-of 的 version 事件仍指向同一 png 路径,改了字节下次 render 自动反映。
    if only is not None:
        latest = _latest_version(log_dir)
        if latest:
            shots = _shoot(html_path, log_dir / "screenshots" / latest, only_slide=only)
            n = len(shots) if shots else 0
            print(f"📸 {latest} · 仅刷新第 {only} 页:{n} 张"
                  + (" · ⚠️ 无截图(playwright?)" if shots is None else ""))
            _auto_render(log_dir, deck_dir)
            return 0
        print("  (还没有基线版本,先做一次完整 snapshot 再用 --slide 增量)", file=sys.stderr)
        # 落空 → 继续走全量,建立基线

    v = _next_version(log_dir)
    print(f"📸 {v}  ←  {html_path}")

    # 截图(全套)
    shots = _shoot(html_path, log_dir / "screenshots" / v)

    # 几何校验
    audit = _run_distribution_audit(html_path)
    findings = []
    if audit:
        (log_dir / "audits").mkdir(parents=True, exist_ok=True)
        (log_dir / "audits" / f"{v}.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        # check-distribution --json:顶层是 slide 列表,每 slide 的 signals 是
        # [code, sev, msg] 三元组列表。抽成扁平摘要。
        rows = audit if isinstance(audit, list) else audit.get("slides", [])
        for s in rows or []:
            for f in (s.get("signals") or s.get("findings") or []):
                if isinstance(f, (list, tuple)):
                    code = f[0] if len(f) > 0 else ""
                    sev = f[1] if len(f) > 2 else ""
                    msg = f[-1] if f else ""
                elif isinstance(f, dict):
                    code, sev, msg = f.get("code", ""), f.get("sev", ""), f.get("msg", "")
                else:
                    code, sev, msg = "", "", str(f)
                findings.append({"slide": s.get("idx"), "code": code, "sev": sev, "msg": msg})

    # 落 version + audit 事件(不再保存 deck 当时的 html,只留截图)
    append_event(log_dir, {
        "t": "version", "v": v, "label": args.label or "",
        "html": str(html_path),
        "slides": [{"idx": s["idx"], "key": s.get("key"), "layout": s.get("layout"),
                    "png": f"screenshots/{v}/{s['png']}"} for s in (shots or [])],
        "n_slides": len(shots or []),
    })
    if findings:
        append_event(log_dir, {"t": "audit", "v": v, "findings": findings})

    n = len(shots) if shots else 0
    print(f"   {n} 页截图" + (" · ⚠️ 无截图(playwright?)" if not shots else "")
          + (f" · {len(findings)} 条校验发现" if findings else " · 校验通过/未跑"))
    _auto_render(log_dir, deck_dir)
    return 0


def _auto_render(log_dir: Path, deck_dir: Path) -> None:
    """snapshot 后顺手刷新 making-of.html(快、0 token),省得手动再跑 render。"""
    try:
        from _render_makingof import render_html
        merged = _merge_events_and_turns(log_dir)
        if merged:
            render_html(log_dir, merged, log_dir / "making-of.html", inline=False)
            print(f"   ↻ 已刷新流水:{log_dir / 'making-of.html'}")
    except Exception as e:
        print(f"   ⚠️ 流水刷新跳过(可手动 `deck-log render {deck_dir}`):{e}", file=sys.stderr)


# ----------------------------------------------------------------------------- event
def cmd_event(args) -> int:
    log_dir = _log_dir(Path(args.deck_dir))
    obj = {"t": args.type}
    if args.version:
        obj["v"] = args.version
    if args.slide is not None:
        obj["slide"] = args.slide
    if args.msg:
        obj["msg"] = args.msg
    if args.said:
        obj["i_said"] = args.said
    if args.resolves:
        obj["resolves"] = args.resolves
    if args.json:
        try:
            obj.update(json.loads(args.json))
        except json.JSONDecodeError as e:
            print(f"✗ --json 解析失败:{e}", file=sys.stderr)
            return 2
    append_event(log_dir, obj)
    print(f"✓ +{args.type}" + (f" (slide {args.slide})" if args.slide is not None else ""))
    return 0


# ----------------------------------------------------------------------------- render
def _rel(log_dir: Path, p: str) -> str:
    """journal 里存的是相对 log/ 的路径;making-of.html 也在 log/,直接用。"""
    return p


def _merge_events_and_turns(log_dir: Path, allow_transcript: bool = True) -> list[dict]:
    """合并:journal 的 curated 事件(session/version/audit/problem/fix/summary)
    + 从 transcript 现捞的 turn(输入+回复),按 ts 排成一条时间线。

    turn 不写进 journal —— 每次 render 现读,既不重复、又保 append-only 纯净。"""
    events = read_events(log_dir)
    sess = next((e for e in events if e.get("t") == "session"), {})
    turns = []
    if allow_transcript and not OFF_SWITCH.exists():
        tp = sess.get("transcript") or _find_current_transcript()
        if tp:
            turns = extract_turns(tp, sess.get("start_ts"))
    merged = events + turns
    # 按绝对时间点排序(journal 本地 +08:00 与 transcript UTC Z 混排也不会错位)
    merged.sort(key=lambda e: _ts_epoch(e.get("ts") or e.get("start_ts")))
    return merged


def cmd_render(args) -> int:
    from _render_makingof import render_html  # 同目录模块
    log_dir = _log_dir(Path(args.deck_dir))
    merged = _merge_events_and_turns(log_dir)
    if not merged:
        print(f"✗ 没有任何事件:{_journal(log_dir)}(先 `deck-log init`)", file=sys.stderr)
        return 2
    out = log_dir / "making-of.html"
    render_html(log_dir, merged, out, inline=args.inline)
    n_turns = sum(1 for e in merged if e.get("t") == "turn")
    print(f"✓ 纪录片已生成:{out}")
    print(f"  从 transcript 捞到 {n_turns} 个对话回合 · 双击打开即可;发给别人用 `--inline` 出单文件。")
    return 0


# ----------------------------------------------------------------------------- diagnose
def cmd_diagnose(args) -> int:
    log_dir = _log_dir(Path(args.deck_dir))
    events = _merge_events_and_turns(log_dir)
    problems = [e for e in events if e.get("t") == "problem"]
    fixes = [e for e in events if e.get("t") == "fix"]
    audits = [e for e in events if e.get("t") == "audit"]
    title = next((e.get("title") for e in events if e.get("t") == "session"), log_dir.parent.name)

    digest = {
        "deck": title,
        "n_turns": sum(1 for e in events if e.get("t") == "turn"),
        "n_versions": sum(1 for e in events if e.get("t") == "version"),
        "problems": [{"slide": p.get("slide"), "observed": p.get("msg"), "i_said": p.get("i_said")} for p in problems],
        "fixes": [{"resolves": f.get("resolves"), "msg": f.get("msg")} for f in fixes],
        "audit_findings": [{"v": a.get("v"), "findings": a.get("findings")} for a in audits],
    }
    print(json.dumps(digest, ensure_ascii=False, indent=2))
    print("\n" + "=" * 72)
    print("把以上 digest 交给大模型,问:")
    print("""\
  「这些是我做这份 deck 时反复手动纠正的问题 + 校验自动发现的问题。
   逐条判断:哪些是 feishu-deck-h5 *框架本身* 该自动解决的 bug(候选 F-NN 工单),
   哪些只是这份 deck 的一次性内容问题。框架类的,按 AUDIT-*.md 的 F-NN 工单格式给出
   (问题 / 复现 / 根因猜测 / 建议修法 / 优先级),并提示是否该 grep 同类问题一次批量修。」""")
    return 0


# ----------------------------------------------------------------------------- on/off/status
def cmd_off(args) -> int:
    OFF_SWITCH.parent.mkdir(parents=True, exist_ok=True)
    OFF_SWITCH.write_text(f"off since {_now_iso()}\n", encoding="utf-8")
    print("⏸  deck-log 全局已关(render 不再从 transcript 捞输入/回复)。`deck-log on` 重新打开。")
    return 0


def cmd_on(args) -> int:
    if OFF_SWITCH.exists():
        OFF_SWITCH.unlink()
    print("▶️  deck-log 全局已开(默认态)。")
    return 0


def cmd_status(args) -> int:
    on = not OFF_SWITCH.exists()
    print(f"全局开关:{'ON ▶️' if on else 'OFF ⏸ (~/.claude/deck-log.off 存在)'}")
    if ACTIVE_PTR.exists():
        active = ACTIVE_PTR.read_text(encoding="utf-8").strip()
        log_dir = Path(active)
        ev = read_events(log_dir) if log_dir.exists() else []
        sess = next((e for e in ev if e.get("t") == "session"), {})
        print(f"当前活跃 deck:{active}")
        print(f"  版本数:{sum(1 for e in ev if e.get('t')=='version')} · "
              f"问题:{sum(1 for e in ev if e.get('t')=='problem')}")
        tp = sess.get("transcript")
        print(f"  transcript:{tp or '(未记录)'}")
        if tp and on:
            print(f"  从 transcript 现可捞回合数:{len(extract_turns(tp, sess.get('start_ts')))}")
    else:
        print("当前无活跃 deck(还没 `deck-log init`)。")
    return 0


def cmd_turns(args) -> int:
    """预览从 transcript 捞到的回合(校验/调试用)。"""
    log_dir = _log_dir(Path(args.deck_dir))
    sess = next((e for e in read_events(log_dir) if e.get("t") == "session"), {})
    tp = args.transcript or sess.get("transcript") or _find_current_transcript()
    if not tp:
        print("✗ 找不到 transcript", file=sys.stderr); return 2
    turns = extract_turns(tp, None if args.all else sess.get("start_ts"))
    for t in turns:
        print(f"#{t['n']:>2} [{t.get('ts','')}]  👤 {t['input'][:70]!r}")
        print(f"        🤖 {t['output_raw'][:70]!r}  ({len(t['output_raw'])} 字)")
    print(f"\n共 {len(turns)} 回合(transcript={tp})")
    return 0


# ----------------------------------------------------------------------------- cli
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="deck-log", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="搭 log/ 骨架并设为活跃 deck")
    p.add_argument("deck_dir"); p.add_argument("--title", default=None)
    p.add_argument("--transcript", default=None, help="显式指定会话 transcript(默认自动找最近的)")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("snapshot", help="截图+校验,落一个 version 事件;--slide N 只刷某页")
    p.add_argument("deck_dir"); p.add_argument("--html", default=None)
    p.add_argument("--label", default=None, help="这一版的简短说明")
    p.add_argument("--slide", type=int, default=None,
                   help="只重截第 N 页(1-based,覆盖最新版本那一页,秒级);省略=全量截一版")
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("event", help="追加一条任意事件")
    p.add_argument("deck_dir"); p.add_argument("--type", required=True,
                                               help="problem | fix | note | milestone | …")
    p.add_argument("--version", default=None)
    p.add_argument("--slide", type=int, default=None)
    p.add_argument("--msg", default=None, help="一句话描述")
    p.add_argument("--said", default=None, help="(problem) 你当时的原话吐槽")
    p.add_argument("--resolves", default=None, help="(fix) 指向它修的那个 problem")
    p.add_argument("--json", default=None, help="额外字段,JSON 对象字符串")
    p.set_defaults(func=cmd_event)

    p = sub.add_parser("render", help="journal → making-of.html")
    p.add_argument("deck_dir"); p.add_argument("--inline", action="store_true",
                                               help="base64 内联所有图,出真·单文件")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("diagnose", help="输出供大模型分析 skill bug 的 digest")
    p.add_argument("deck_dir")
    p.set_defaults(func=cmd_diagnose)

    p = sub.add_parser("turns", help="预览从 transcript 捞到的回合(调试)")
    p.add_argument("deck_dir"); p.add_argument("--transcript", default=None)
    p.add_argument("--all", action="store_true", help="忽略 start_ts,捞整份 transcript")
    p.set_defaults(func=cmd_turns)

    sub.add_parser("off", help="全局停录").set_defaults(func=cmd_off)
    sub.add_parser("on", help="全局开录(默认)").set_defaults(func=cmd_on)
    sub.add_parser("status", help="看开关与活跃 deck").set_defaults(func=cmd_status)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
