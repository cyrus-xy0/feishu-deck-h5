#!/usr/bin/env python3
"""把 journal.jsonl 的事件流确定性渲染成 making-of.html。

呈现:深色飞书 DNA 的纵向时间线。每个回合一张卡片(👤输入 / 🤖回复,长回复折叠);
每个版本一张卡片(整套截图缩略图条,点击灯箱放大 + 校验徽章);problem/fix 用醒目
的因果块。截图默认相对引用(making-of.html 与 screenshots/ 同在 log/ 下);--inline
时 base64 内联成真·单文件,便于直接发给同学。
"""
from __future__ import annotations
import base64
import html
import json
import mimetypes
from pathlib import Path

_ESC = lambda s: html.escape("" if s is None else str(s))


def _img_src(log_dir: Path, rel: str, inline: bool) -> str:
    if not inline:
        return _ESC(rel)
    p = (log_dir / rel)
    if not p.exists():
        return _ESC(rel)
    mime = mimetypes.guess_type(str(p))[0] or "image/png"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _turn_card(e: dict) -> str:
    n = e.get("n", "")
    inp = _ESC(e.get("input", "")).replace("\n", "<br>")
    atts = e.get("attachments") or []
    att_html = ""
    if atts:
        att_html = '<div class="atts">' + "".join(f'<span class="att">📎 {_ESC(a)}</span>' for a in atts) + "</div>"
    summary = e.get("summary") or ""
    raw = e.get("output_raw") or ""
    out_html = ""
    if summary:
        out_html += f'<div class="summary">{_ESC(summary).replace(chr(10), "<br>")}</div>'
    if raw:
        out_html += (f'<details class="raw"><summary>展开 Claude 原始回复 '
                     f'({len(raw)} 字)</summary><pre>{_ESC(raw)}</pre></details>')
    if not out_html:
        out_html = '<div class="muted">（无文本回复 / 仅工具操作）</div>'
    return f"""
    <div class="card turn">
      <div class="turn-no">回合 {_ESC(n)}</div>
      <div class="row"><div class="who user">👤 输入</div><div class="bubble">{inp}{att_html}</div></div>
      <div class="row"><div class="who claude">🤖 Claude</div><div class="bubble">{out_html}</div></div>
    </div>"""


def _version_card(log_dir: Path, e: dict, audit_by_v: dict, inline: bool) -> str:
    v = e.get("v", "")
    label = _ESC(e.get("label") or "")
    slides = e.get("slides") or []
    thumbs = ""
    for s in slides:
        png = s.get("png")
        if not png:
            continue
        src = _img_src(log_dir, png, inline)
        cap = f"{s.get('idx')} · {_ESC(s.get('key') or '')}"
        thumbs += (f'<figure class="thumb" onclick="lb(this)"><img loading="lazy" src="{src}" '
                   f'alt="{cap}"><figcaption>{cap}</figcaption></figure>')
    if not thumbs:
        thumbs = '<div class="muted">（这一版没有截图 —— 可能没装 playwright）</div>'

    findings = (audit_by_v.get(v) or {}).get("findings") or []
    if findings:
        items = "".join(f'<li>#{_ESC(f.get("slide"))} {_ESC(f.get("msg"))}</li>' for f in findings)
        badge = f'<span class="badge warn">⚠️ {len(findings)} 条校验发现</span>'
        audit_block = f'<details class="audit"><summary>{badge}</summary><ul>{items}</ul></details>'
    else:
        audit_block = '<span class="badge ok">✅ 校验通过 / 未跑</span>'

    snap = e.get("snapshot")
    snap_link = f'<a class="snaplink" href="{_ESC(snap)}">↗ 打开这一版的冻结副本</a>' if snap else ""
    return f"""
    <div class="card version" id="{_ESC(v)}">
      <div class="vhead"><span class="vtag">🆕 {_ESC(v)}</span>
        <span class="vlabel">{label}</span>{audit_block}{snap_link}</div>
      <div class="strip">{thumbs}</div>
    </div>"""


def _problem_card(e: dict) -> str:
    slide = e.get("slide")
    where = f'第 {slide} 页' if slide is not None else ''
    said = e.get("i_said")
    said_html = f'<div class="said">🗣 “{_ESC(said)}”</div>' if said else ""
    return f"""
    <div class="card problem">
      <div class="ptag">🐞 问题{(' · ' + where) if where else ''}</div>
      <div class="pmsg">{_ESC(e.get("msg") or "")}</div>{said_html}
    </div>"""


def _fix_card(e: dict) -> str:
    res = e.get("resolves")
    res_html = f'<span class="fres">↳ 修复:{_ESC(res)}</span>' if res else ""
    return f"""
    <div class="card fix">
      <div class="ftag">🔧 修复 {res_html}</div>
      <div class="fmsg">{_ESC(e.get("msg") or "")}</div>
    </div>"""


_CSS = """
:root{--bg:#04081B;--bg2:#0A1126;--ink:#E8ECF8;--mut:#7E8AB0;--line:#1C2744;
--accent:#3E7BFA;--user:#2BB3A3;--warn:#F5A623;--bad:#FF6B6B;--ok:#3DD68C;}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(120% 90% at 50% 0%,#0A1126,#04081B 60%,#000);
color:var(--ink);font:15px/1.6 -apple-system,"PingFang SC","Microsoft YaHei",sans-serif;}
.wrap{max-width:920px;margin:0 auto;padding:48px 24px 120px}
header{padding:28px 0 8px;border-bottom:1px solid #1b2744}
.title{font-size:30px;font-weight:700;letter-spacing:.5px}
.sub{color:var(--mut);margin-top:8px;font-size:14px}
.stats{display:flex;gap:18px;margin-top:18px;flex-wrap:wrap}
.stat{background:#0d1530;border:1px solid #1b2744;border-radius:10px;padding:10px 16px}
.stat b{font-size:22px;display:block}.stat span{color:var(--mut);font-size:12px}
.timeline{margin-top:30px;position:relative;padding-left:26px}
.timeline:before{content:"";position:absolute;left:7px;top:6px;bottom:0;width:2px;
background:linear-gradient(#23365f,#0c1430)}
.card{position:relative;margin:0 0 22px;background:#0b1430;border:1px solid #1b2744;
border-radius:14px;padding:18px 20px}
.card:before{content:"";position:absolute;left:-23px;top:22px;width:12px;height:12px;
border-radius:50%;background:var(--accent);box-shadow:0 0 0 4px #04081b}
.turn:before{background:var(--accent)}.version:before{background:var(--ok)}
.problem:before{background:var(--bad)}.fix:before{background:var(--warn)}
.turn-no{font-size:12px;color:var(--mut);font-weight:600;letter-spacing:1px;margin-bottom:10px}
.row{display:flex;gap:12px;margin:10px 0}
.who{flex:0 0 64px;font-size:13px;font-weight:600;padding-top:2px}
.who.user{color:var(--user)}.who.claude{color:#9db4ff}
.bubble{flex:1;background:#070d22;border:1px solid #18223e;border-radius:10px;padding:10px 13px}
.summary{}.muted{color:var(--mut);font-style:italic}
.atts{margin-top:8px}.att{display:inline-block;background:#13203f;border-radius:6px;
padding:2px 8px;font-size:12px;color:#a9b8e0;margin-right:6px}
details.raw{margin-top:10px}details.raw summary{cursor:pointer;color:var(--mut);font-size:13px}
details.raw pre{white-space:pre-wrap;word-break:break-word;background:#05091c;border:1px solid #16203c;
border-radius:8px;padding:12px;margin-top:8px;font:12px/1.55 ui-monospace,Menlo,monospace;
max-height:420px;overflow:auto;color:#c4cdec}
.vhead{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:14px}
.vtag{font-size:16px;font-weight:700;color:var(--ok)}
.vlabel{color:#cdd6f0}
.badge{font-size:12px;padding:3px 10px;border-radius:20px;cursor:default}
.badge.ok{background:#0f2e22;color:var(--ok)}.badge.warn{background:#3a2b0d;color:var(--warn);cursor:pointer}
details.audit{display:inline}details.audit summary{list-style:none;display:inline}
details.audit ul{margin:10px 0 0;padding-left:18px;color:#e8c98a;font-size:13px;width:100%}
.snaplink{margin-left:auto;color:#6f8fd8;font-size:12px;text-decoration:none}
.strip{display:flex;gap:10px;overflow-x:auto;padding-bottom:6px}
.thumb{margin:0;flex:0 0 220px;cursor:zoom-in}
.thumb img{width:220px;height:124px;object-fit:cover;border-radius:8px;border:1px solid #22305a;
background:#000;display:block;transition:transform .12s,border-color .12s}
.thumb:hover img{transform:translateY(-2px);border-color:var(--accent)}
.thumb figcaption{font-size:11px;color:var(--mut);margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.problem{border-color:#5a2230;background:#1a0c12}.ptag{color:var(--bad);font-weight:700;font-size:14px}
.pmsg{margin-top:6px}.said{margin-top:8px;color:#ffb3b3;font-style:italic}
.fix{border-color:#5a460f;background:#171206}.ftag{color:var(--warn);font-weight:700;font-size:14px}
.fres{font-weight:400;color:#d7c08a;font-size:13px;margin-left:6px}.fmsg{margin-top:6px}
#lbx{position:fixed;inset:0;background:rgba(0,0,0,.92);display:none;align-items:center;
justify-content:center;z-index:99;cursor:zoom-out;padding:30px}
#lbx img{max-width:100%;max-height:100%;border-radius:8px;box-shadow:0 20px 80px rgba(0,0,0,.6)}
#lbx .cap{position:absolute;bottom:18px;left:0;right:0;text-align:center;color:#aab6dd;font-size:13px}
footer{margin-top:50px;color:var(--mut);font-size:12px;text-align:center}
"""

_JS = """
function lb(fig){var img=fig.querySelector('img');var b=document.getElementById('lbx');
b.querySelector('img').src=img.src;b.querySelector('.cap').textContent=fig.querySelector('figcaption').textContent;
b.style.display='flex';}
document.getElementById('lbx').addEventListener('click',function(){this.style.display='none';});
document.addEventListener('keydown',function(e){if(e.key==='Escape')document.getElementById('lbx').style.display='none';});
"""


def render_html(log_dir: Path, events: list[dict], out_path: Path, inline: bool = False) -> None:
    title = next((e.get("title") for e in events if e.get("t") == "session"), log_dir.parent.name)
    audit_by_v = {e.get("v"): e for e in events if e.get("t") == "audit"}
    # 把可选的一行摘要(`summary` 事件,带 n)折进对应回合,实现"原文+精炼摘要"
    summary_by_n = {e.get("n"): e.get("msg") for e in events if e.get("t") == "summary" and e.get("n") is not None}
    for e in events:
        if e.get("t") == "turn" and not e.get("summary") and e.get("n") in summary_by_n:
            e["summary"] = summary_by_n[e["n"]]
    n_turns = sum(1 for e in events if e.get("t") == "turn")
    versions = [e for e in events if e.get("t") == "version"]
    n_problems = sum(1 for e in events if e.get("t") == "problem")
    first_ts = next((e.get("ts") for e in events if e.get("ts")), "")

    cards = []
    for e in events:
        t = e.get("t")
        if t == "turn":
            cards.append(_turn_card(e))
        elif t == "version":
            cards.append(_version_card(log_dir, e, audit_by_v, inline))
        elif t == "problem":
            cards.append(_problem_card(e))
        elif t == "fix":
            cards.append(_fix_card(e))
        # session / audit 不单独出卡(audit 并进 version)

    body = "\n".join(cards)
    doc = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>制作纪录片 · {_ESC(title)}</title><style>{_CSS}</style></head>
<body><div class="wrap">
<header>
  <div class="title">🎬 {_ESC(title)} · 制作全过程</div>
  <div class="sub">这份文档完整记录了这个 deck 是怎么一步步做出来的:每一次输入、Claude 的返回、每个版本的截图与校验。{(' 始于 ' + _ESC(first_ts)) if first_ts else ''}</div>
  <div class="stats">
    <div class="stat"><b>{n_turns}</b><span>对话回合</span></div>
    <div class="stat"><b>{len(versions)}</b><span>版本快照</span></div>
    <div class="stat"><b>{sum(v.get('n_slides',0) for v in versions)}</b><span>截图总数</span></div>
    <div class="stat"><b>{n_problems}</b><span>记录的问题</span></div>
  </div>
</header>
<div class="timeline">
{body}
</div>
<footer>由 deck-log 从 journal.jsonl 确定性生成 · 重渲不丢内容 · 改了 journal 重跑 <code>deck-log render</code> 即可</footer>
</div>
<div id="lbx"><img alt=""><div class="cap"></div></div>
<script>{_JS}</script>
</body></html>"""
    out_path.write_text(doc, encoding="utf-8")
