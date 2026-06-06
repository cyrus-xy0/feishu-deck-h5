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
(0 model token,纯文件读)。init 记下当前 transcript 路径+起点;render 不止读这一个,
而是**自动发现同 project 下 start_ts 之后改动、且文件内提到本 deck(run-slug 或标题)的
所有 transcript**,把各自回合合并、按时间重排——这样换了会话(新 sid.jsonl)也不丢今天的
记录。再和版本/问题/修复并成一条时间线。

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
    """deck-dir 是含 output/(本技能)或 out/(旧约定)的那个 run 目录;log/ 是它的兄弟。"""
    deck_dir = deck_dir.resolve()
    # 容错:用户可能直接把 output/ / out/ / log/ 传进来
    if deck_dir.name in ("out", "output", "log"):
        deck_dir = deck_dir.parent
    return deck_dir / "log"


def _deck_html(deck_dir: Path) -> Path:
    """解析 deck 成品 index.html 的位置。本技能 feishu-deck-h5 用 `output/`,旧约定/别处
    可能用 `out/` 或直接放 run 根。依次找 output/ → out/ → run 根,返回第一个存在的;
    都不存在则返回 output/ 候选(本技能约定,供 not-found 报错显示)。
    (历史 bug:原 cmd_snapshot 只认 out/,导致本技能所有 output/ deck 截不了图。)"""
    deck_dir = deck_dir.resolve()
    if deck_dir.name in ("out", "output", "log"):   # 传进来的是 output//out//log/ 时回到 run 根
        deck_dir = deck_dir.parent
    for sub in ("output", "out"):
        cand = deck_dir / sub / "index.html"
        if cand.exists():
            return cand
    if (deck_dir / "index.html").exists():
        return deck_dir / "index.html"
    return deck_dir / "output" / "index.html"


def _journal(log_dir: Path) -> Path:
    return log_dir / "journal.jsonl"


def _first_session_event(log_dir: Path) -> dict | None:
    """已 init 过的标志:journal 里第一条 session 事件(含原始 start_ts)。
    用于 init 幂等 —— new-run.sh 自动 init 之后若又手动 init,不该重戳 start_ts
    (会把起点推后,render 按新 start_ts 过滤就丢掉最早几轮)。"""
    jp = _journal(log_dir)
    if not jp.exists():
        return None
    try:
        for line in jp.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("t") == "session":
                return ev
    except OSError:
        return None
    return None


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


def _prev_slide_fingerprints(log_dir: Path) -> dict:
    """上一个 version 事件逐页的 {key: {'h':指纹, 'png':相对路径}},给增量截图比对用。
    返回空 dict = 没有上一版,或旧版本没存指纹 → snapshot 退化成全量重截。"""
    versions = [e for e in read_events(log_dir) if e.get("t") == "version"]
    if not versions:
        return {}
    out = {}
    for s in versions[-1].get("slides", []):
        if s.get("key"):
            out[s["key"]] = {"h": s.get("h"), "png": s.get("png")}
    return out


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


def _project_dir_for(sess: dict) -> Path | None:
    """会话 transcript 所在的 project 目录(同一 cwd 起的所有会话都落同一个 ~/.claude/projects/<slug>/)。"""
    tp = sess.get("transcript")
    if tp:
        pp = Path(tp).parent
        if pp.exists():
            return pp
    # 退路:用 cwd 推导 slug —— ~/.claude/projects/<cwd 把 / 换成 ->/
    cwd = sess.get("cwd")
    if cwd and _PROJECTS.exists():
        cand = _PROJECTS / str(Path(cwd).resolve()).replace("/", "-")
        if cand.exists():
            return cand
    return None


def _deck_tokens(log_dir: Path, sess: dict) -> list[str]:
    """判定某 transcript 是否在聊"这份 deck"的特征串:
    run 目录名(最强——它的路径在工具调用里一定出现过)+ deck 标题。"""
    toks = [log_dir.parent.name]            # 20260528-192338-zhongan-ai-org
    if sess.get("title"):
        toks.append(sess["title"])
    return [t for t in toks if t]


def _relevant_transcripts(log_dir: Path, sess: dict) -> list[Path]:
    """init 记的那条 + 同 project 下 start_ts 之后改动、且文件内提到本 deck 的所有 transcript。

    解决"换了会话(新 sid.jsonl)→ 今天的回合全丢":render 时按内容自动发现并跨 session 合并。
    file-level 相关性(整文件出现 run-slug 或标题)挡掉用户并行在做别的 deck 的会话。
    注:file-level 只挡掉整段没提本 deck 的会话;同会话里"既做本 deck 又 commit+push /
    做别的 deck"的混合情况,由 extract_turns 的 turn 级 tokens 过滤再筛一道。"""
    found: list[Path] = []
    seen: set[Path] = set()

    recorded = sess.get("transcript")
    if recorded and Path(recorded).exists():               # 记下的主会话:无条件收
        rp = Path(recorded).resolve()
        found.append(rp); seen.add(rp)

    proj = _project_dir_for(sess)
    if proj:
        start = _ts_epoch(sess.get("start_ts"))
        tokens = _deck_tokens(log_dir, sess)
        for jf in sorted(proj.glob("*.jsonl")):
            rp = jf.resolve()
            if rp in seen:
                continue
            try:                                            # 只看 start_ts(留 1h 余量)之后还动过的,别扫历史全集
                if start != float("-inf") and jf.stat().st_mtime < start - 3600:
                    continue
                text = jf.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if tokens and not any(tok in text for tok in tokens):
                continue                                    # 没提到本 deck → 多半是别的 deck 的会话,跳过
            found.append(rp); seen.add(rp)

    if not found:                                           # 连记录都没有时退回"当前 transcript"
        cur = _find_current_transcript()
        if cur:
            # 有 deck token 时, fallback transcript 也要真提到它才采用 —— 否则
            # token-less 的全局最近 fallback 会把别的 session 的 transcript 误挂到本 deck.
            if not tokens:
                found.append(Path(cur))
            else:
                try:
                    ctext = Path(cur).read_text(encoding='utf-8', errors='ignore')
                    if any(tok in ctext for tok in tokens):
                        found.append(Path(cur))
                except OSError:
                    pass
    return found


def _deck_hits(tp: Path, tokens: list[str]) -> int:
    """transcript 文件里 deck token(目录名/标题)出现总次数 —— 这份会话对本 deck 的
    相关强度。真做这 deck 的会话命中数远高于"顺带提了一两次"的无关会话。"""
    if not tokens:
        return 0
    try:
        text = tp.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    return sum(text.count(tok) for tok in tokens)


def _dominant_transcript(transcripts: list[Path], tokens: list[str]) -> Path | None:
    """本 deck 主导的那个 transcript = deck token 命中最多的 —— 它就是真做这份 deck
    的会话(deck 目录/标题在它的工具调用里反复出现)。render 对它保留活跃期内的*全部*
    真回合(含"边做边讨论但没逐字提 deck 名"的回合);对其余次要 transcript 才逐回合
    token 过滤。解决:做 deck 时穿插的纯讨论回合(校验逻辑、规范问题…)本属制作过程,
    却因没触及 deck 文件被 turn 级过滤误删,使 making-of 的输入/回复不全。"""
    if not transcripts:
        return None
    return max(transcripts, key=lambda tp: _deck_hits(tp, tokens))


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


def _evidence_from_content(content) -> str:
    """抽 tool_use 的 input + tool_result 的内容(命令 / 文件路径 / 输出),
    只用来判断"这个回合是否在操作本 deck",不进 making-of 展示。"""
    if not isinstance(content, list):
        return ""
    parts = []
    for b in content:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "tool_use":
            parts.append(json.dumps(b.get("input", ""), ensure_ascii=False))
        elif t == "tool_result":
            c = b.get("content")
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, list):
                parts.append(" ".join(x.get("text", "") for x in c
                                      if isinstance(x, dict)))
    return " ".join(parts)


def extract_turns(transcript: str, since_ts: str | None,
                  tokens: list[str] | None = None) -> list[dict]:
    """从 transcript 抽成 turn 列表:把每条真·人类输入配上紧随其后的 assistant 文本。

    since_ts:只取这个时间(init 的起点)之后的记录,把日志 scope 到"做这个 deck"那段。
    tokens:本 deck 的特征串(run 目录名 / 标题)。给了就做 *turn 级* 相关性过滤——
            只保留"输入 / 回复 / 该回合工具调用的命令·路径"提到本 deck 的回合,
            滤掉同会话里 commit+push、做别的 deck 等无关回合(file-level 过滤的补充)。
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
            ev = _evidence_from_content(content)        # tool_result(命令输出 / 路径)
            if ev:
                rows.append(("ev", ts, ev))
        elif typ == "assistant":
            txt = _text_from_content(content)
            if txt:
                rows.append(("out", ts, txt))
            ev = _evidence_from_content(content)        # tool_use(bash 命令 / 文件路径)
            if ev:
                rows.append(("ev", ts, ev))

    # 配对:一条 in 收集它之后、下一条 in 之前的所有 out 文本 + 工具证据(_ev)
    turns, cur, n = [], None, 0
    for kind, ts, text in rows:
        if kind == "in":
            if cur:
                turns.append(cur)
            n += 1
            cur = {"t": "turn", "n": n, "ts": ts, "input": text,
                   "output_raw": "", "_ev": ""}
        elif kind == "out" and cur is not None:
            cur["output_raw"] = (cur["output_raw"] + "\n\n" + text).strip() if cur["output_raw"] else text
        elif kind == "ev" and cur is not None:
            cur["_ev"] += " " + text
    if cur:
        turns.append(cur)

    # turn 级相关性过滤:只留"操作了本 deck"的回合(滤掉同会话的 commit+push / 别的 deck)。
    # 信号 = 用户指令(input)+ 工具实际触及的命令·路径(_ev);故意不看 assistant 散文
    # (output_raw)—— 回复里为解释而"提到" slug ≠ 真的操作了这个 deck(本次修 bug 即是例)。
    if tokens:
        turns = [t for t in turns
                 if any(tok in (t["input"] + " " + t["_ev"]) for tok in tokens)]
    for t in turns:                                     # _ev 仅用于过滤,不外泄
        t.pop("_ev", None)
    return turns


# ----------------------------------------------------------------------------- init
def cmd_init(args) -> int:
    log_dir = _log_dir(Path(args.deck_dir))
    for sub in ("inputs", "screenshots", "audits"):
        (log_dir / sub).mkdir(parents=True, exist_ok=True)
    # 记下"当前活跃 deck"(供 status 查看;render 用 session 事件里的 transcript)
    ACTIVE_PTR.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_PTR.write_text(str(log_dir.resolve()), encoding="utf-8")

    # 幂等守卫:已 init 过就保留原 start_ts、不再追加 session 事件,只把活跃指针指回本 deck。
    # 否则二次 init(new-run.sh 已自动 init,agent 又照旧手动 init)会把起点推后 → 丢最早几轮。
    # 仅当显式 --transcript 重指时才允许刷新(罕见:自动探测找错了 transcript)。
    existing = _first_session_event(log_dir)
    if existing and not args.transcript:
        print(f"✓ deck-log 已初始化,保留原 start_ts={existing.get('start_ts')}(跳过重复 init)。")
        print(f"  活跃指针 → {ACTIVE_PTR}")
        return 0

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
  // 内容指纹:djb2 over .slide innerHTML —— 用于增量截图判定"这页变没变"。
  // 取 innerHTML(内容)而非 outerHTML:截图时往 .slide 上写的 --fs-scale 内联样式
  // 不进 innerHTML,指纹对截图副作用稳定。
  // 再剥掉子元素上的内联 style="..." 属性:框架运行时(balanceSlide 垂直居中、
  // auto-fit 等)会按测量结果往子元素写 top/bottom/transform 等内联值,且在截图
  // 时刻(~300ms)动画/测量尚未 settle,每次落点差几 px → 指纹漂移 → 同一页每版
  // 都被误判"变了"而空截。每页真正的 CSS 在 <style> 块里(不是 style 属性,不受影响),
  // 所以剥掉内联 style 只滤掉运行时噪声,真实内容/结构改动照样进指纹。
  const norm = (html) => html.replace(/ style=("[^"]*"|'[^']*')/g, '');
  const fp = (str) => { let h = 5381; for (let i = 0; i < str.length; i++) { h = ((h << 5) + h + str.charCodeAt(i)) | 0; } return (h >>> 0).toString(36); };
  const frames = [...document.querySelectorAll('.slide-frame')];
  return frames.map((f, i) => {
    const s = f.querySelector('.slide');
    return {
      idx: i + 1,
      key: (s && (s.getAttribute('data-slide-key') || s.id)) || ('slide-' + (i + 1)),
      layout: (s && s.getAttribute('data-layout')) || '',
      h: s ? fp(norm(s.innerHTML)) : '',
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


def _shoot(html_path: Path, out_png_dir: Path, only_slide: int | None = None,
           prev_by_key: dict | None = None):
    """用 Playwright 把页截成 1920×1080 的 png,**默认增量**。返回 ALL 页的 meta 列表
    (idx/key/layout/h),失败返回 None。每项二选一:
      · 新截的 → 带 'png'(out_png_dir 下的文件名,如 s03.png);
      · 与上一版同 key 且内容哈希未变 → 带 'reuse'(指向上一版那张 png 的相对路径,不重截)。

    prev_by_key:{key: {'h':指纹, 'png':'screenshots/vNN/sMM.png'}} —— 上一版逐页的指纹+png 路径;
                None/页无指纹 → 退化成全量重截(首次启用增量、或外来旧版本)。
    only_slide:兼容老的 --slide N(只截这一页、不做增量判断,给"做完一页刷一页"用)。"""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("  ⚠️ 未装 playwright,跳过截图。`pip install playwright && python -m playwright install chromium`",
              file=sys.stderr)
        return None
    out_png_dir.mkdir(parents=True, exist_ok=True)
    url = html_path.resolve().as_uri()
    prev_by_key = prev_by_key or {}
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
            prev = prev_by_key.get(m.get("key"))
            # 增量:同 key、上一版有指纹且与本次一致、且那张 png 还在 → 复用,不重截
            if (only_slide is None and prev and prev.get("h")
                    and prev.get("h") == m.get("h") and prev.get("png")):
                m["reuse"] = prev["png"]
                shots.append(m)
                continue
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
    html_path = Path(args.html) if args.html else _deck_html(deck_dir)
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

    # 截图(默认增量):只截相对上一版内容变了的页,未变页复用上一版 png
    prev_fp = _prev_slide_fingerprints(log_dir)
    shots = _shoot(html_path, log_dir / "screenshots" / v, prev_by_key=prev_fp)

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
                    sev = f[1] if len(f) > 1 else ""
                    msg = f[-1] if f else ""
                elif isinstance(f, dict):
                    code, sev, msg = f.get("code", ""), f.get("sev", ""), f.get("msg", "")
                else:
                    code, sev, msg = "", "", str(f)
                findings.append({"slide": s.get("idx"), "code": code, "sev": sev, "msg": msg})

    # 落 version + audit 事件(不存 deck html;只存截图路径 + 逐页内容指纹供下一版增量比对)。
    # 复用页的 png 指向它真正所在的旧版目录(reuse),磁盘上本版只多出真正改动的页。
    append_event(log_dir, {
        "t": "version", "v": v, "label": args.label or "",
        "html": str(html_path),
        "slides": [{"idx": s["idx"], "key": s.get("key"), "layout": s.get("layout"),
                    "h": s.get("h"),
                    "png": s.get("reuse") or f"screenshots/{v}/{s['png']}"} for s in (shots or [])],
        "n_slides": len(shots or []),
    })
    if findings:
        append_event(log_dir, {"t": "audit", "v": v, "findings": findings})

    n = len(shots) if shots else 0
    n_reuse = sum(1 for s in (shots or []) if s.get("reuse"))
    n_new = n - n_reuse
    detail = f"   {n} 页(新截 {n_new} · 复用上一版 {n_reuse})" if n else "   0 页"
    print(detail + (" · ⚠️ 无截图(playwright?)" if not shots else "")
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
        start = sess.get("start_ts")
        tokens = _deck_tokens(log_dir, sess)
        rels = _relevant_transcripts(log_dir, sess)
        primary = _dominant_transcript(rels, tokens)
        prim_hits = _deck_hits(primary, tokens) if primary else 0
        # 主会话活跃期上界 = 最后一个 version(render)事件 + 30min 宽限:避免把同一会话里
        # 这份 deck 收尾之后、转去做别的 deck 的回合也收进来。没 version 时不设上界。
        vts = [_ts_epoch(e.get("ts")) for e in events if e.get("t") == "version"]
        until = (max(vts) + 1800) if vts else float("inf")
        for tp in rels:
            if tp == primary:
                # 主会话:保留 start_ts 之后、活跃期内的全部真回合(含纯讨论回合)——
                # turn 级 token 过滤只对次要会话用,挡别 deck / 无关会话。
                turns.extend(t for t in extract_turns(str(tp), start, None)
                             if _ts_epoch(t.get("ts")) <= until)
            else:
                # 次要会话:只在它对本 deck 有实质相关(命中 ≥ 主会话 10% 且 ≥2)时才采,
                # 挡掉"只是顺带提过一两次本 deck 路径"的无关会话(如别 session 并发查看);
                # 采时仍逐回合 token 过滤。
                if _deck_hits(tp, tokens) < max(2, 0.1 * prim_hits):
                    continue
                turns.extend(extract_turns(str(tp), start, tokens))
        # 跨多个 transcript 合并后按时间重排 + 全局重新编号(各文件内部从 1 起,合并后会撞号)
        turns.sort(key=lambda e: _ts_epoch(e.get("ts")))
        for i, t in enumerate(turns, 1):
            t["n"] = i
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
    sess = next((e for e in merged if e.get("t") == "session"), {})
    n_tx = len(_relevant_transcripts(log_dir, sess)) if not OFF_SWITCH.exists() else 0
    print(f"✓ 纪录片已生成:{out}")
    print(f"  跨 {n_tx} 个会话 transcript 捞到 {n_turns} 个对话回合 · 双击打开即可;发给别人用 `--inline` 出单文件。")
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
        tps = _relevant_transcripts(log_dir, sess) if on else []
        print(f"  记录的主 transcript:{sess.get('transcript') or '(未记录)'}")
        if on:
            tk = _deck_tokens(log_dir, sess)
            n = sum(len(extract_turns(str(tp), sess.get('start_ts'), tk)) for tp in tps)
            print(f"  跨 {len(tps)} 个会话 transcript 现可捞回合数:{n}")
    else:
        print("当前无活跃 deck(还没 `deck-log init`)。")
    return 0


def cmd_turns(args) -> int:
    """预览从 transcript 捞到的回合(校验/调试用)。"""
    log_dir = _log_dir(Path(args.deck_dir))
    sess = next((e for e in read_events(log_dir) if e.get("t") == "session"), {})
    since = None if args.all else sess.get("start_ts")
    # --all 看原始全集(不过滤);默认与 render 一致做 turn 级 deck 相关性过滤
    tk = None if args.all else _deck_tokens(log_dir, sess)
    # --transcript 显式指定 → 只看那一个;否则走和 render 一致的跨 session 自动发现
    tps = [Path(args.transcript)] if args.transcript else _relevant_transcripts(log_dir, sess)
    if not tps:
        print("✗ 找不到 transcript", file=sys.stderr); return 2
    turns = []
    for tp in tps:
        turns.extend(extract_turns(str(tp), since, tk))
    turns.sort(key=lambda e: _ts_epoch(e.get("ts")))
    for i, t in enumerate(turns, 1):
        t["n"] = i
        print(f"#{i:>2} [{t.get('ts','')}]  👤 {t['input'][:70]!r}")
        print(f"        🤖 {t['output_raw'][:70]!r}  ({len(t['output_raw'])} 字)")
    print(f"\n共 {len(turns)} 回合 · 跨 {len(tps)} 个 transcript")
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
