#!/usr/bin/env python3
"""canvas_finish.py — 渲染层收尾件,与重建管线解耦,纯 stdlib(无 LibreOffice / fitz / PIL)。

`layout:"canvas"` 的 deck(无论由 build_pptx.py 代码重建,还是翻译/编辑改过)单跑
`render-deck.py` 产不全交付级 index.html,还需两步收尾:

  · make_portable : 框架 CSS/JS(及其内部 url() 引的 lark logo 等)拷进 deck 本地
                    assets/ 并改写成相对引用 → 产物整夹拷走 / 打包 / 发送都不断;
  · post_process  : 注入 letterbox 背景 CSS(若有 bg/ 像素背景)+ fitText 超框自适配
                    脚本 —— **真正单行框溢出时 nowrap + scaleX/scale 贴合,不裁切**。
                    这就是 PPT autofit「溢出缩字」在浏览器侧的确定性等价物(量真实
                    bbox,不估算),纯管线接上它即可治多页换行裁切。

历史:这三个函数原住在 build_pptx_hybrid.py(混合管线),但函数体本身零 fitz/PIL
依赖。混合管线退役后剥到此处共用,build_pptx.py(纯管线)与 rerender-deck.py 都 import
本模块。依赖方向:本模块在 pptx-to-deck,用 feishu-deck-h5 当渲染后端,不让 base 反耦合。
"""
from __future__ import annotations
import os
import re
import shutil
from pathlib import Path


def _default_renderer() -> Path:
    """feishu-deck-h5 渲染后端定位:pptx-to-deck 是顶层 skill,feishu-deck-h5 通常
    是兄弟 skill 目录。优先兄弟 <skills>/feishu-deck-h5/,兼容旧的内嵌祖父布局,
    最后回退已注册的 ~/.claude/skills/feishu-deck-h5(symlink)。"""
    skills_dir = Path(__file__).resolve().parent.parent.parent  # <skills>/
    for cand in (skills_dir / "feishu-deck-h5",                 # 兄弟(新布局)
                 skills_dir,                                     # 旧内嵌
                 Path.home() / ".claude/skills/feishu-deck-h5"):  # 注册 symlink
        if (cand / "deck-json/render-deck.py").is_file():
            return cand
    return Path.home() / ".claude/skills/feishu-deck-h5"


# ── letterbox bg + single-line fit + hide progress ──────────────────────────
def post_process(out_dir: Path, deck: dict) -> None:
    rules = []
    for s in deck["slides"]:
        bg = next((e for e in s["data"]["elements"]
                   if e.get("type") == "image" and e["src"].startswith("bg/")), None)
        if bg:
            rules.append('.deck[data-mode="present"] .slide-frame:has(> '
                         '.slide[data-slide-key="%s"]){background:#000 url("%s") '
                         'center/cover no-repeat}' % (s["key"], bg["src"]))
    # NOTE C4: no blanket `.tb-inner{white-space:nowrap}` rule. Forcing nowrap on
    # EVERY box collapsed legitimately multi-line / <br> / wrapping boxes into one
    # line, which scaleX then crushed. We only nowrap+fit GENUINELY single-line
    # boxes at runtime (see fitText); multi-line boxes keep render-deck.py's
    # normal wrapping / <br> paragraph breaks.
    inject = (
        '<style>.deck-ui .deck-progress{display:none!important}\n'
        + "\n".join(rules) + '</style>\n'
        '<script>\n'
        'function fitText(){var c=document.querySelector(".slide-frame.is-current");'
        'if(!c)return;c.querySelectorAll(".el.tb .tb-inner").forEach(function(i){'
        'if(i.dataset.fit)return;i.dataset.fit="1";'
        # C4: a box is genuinely single-line only if it has no <br>/<p> paragraph
        # break AND its content doesn't wrap onto extra lines at its natural
        # (wrapping) width. Probe by measuring the rendered line count BEFORE we
        # touch white-space: if scrollHeight exceeds ~1.5 line-heights, it's
        # multi-line — leave normal wrapping, don't nowrap, don't crush.
        'if(i.querySelector("br,p")){return;}'
        'var lh=parseFloat(getComputedStyle(i).lineHeight)||0;'
        'if(lh&&i.scrollHeight>lh*1.5){return;}'   # naturally wraps → multi-line
        # single-line box → nowrap, then fit horizontally if it overflows.
        'i.style.whiteSpace="nowrap";'
        # measure NATURAL content width (scrollWidth) vs the box (clientWidth):
        # getBoundingClientRect is clipped to the box, so it never sees overflow.
        'var n=i.scrollWidth,b=i.clientWidth;if(n<=b+1||b<1)return;'
        'var r=b/n;i.style.transformOrigin="left center";'
        # mild overflow -> condense width (scaleX); strong -> shrink proportionally
        # (scale) so letterforms stay legible instead of getting crushed.
        'i.style.transform=(r<0.72?"scale("+r.toFixed(4)+")":"scaleX("+r.toFixed(4)+")");});}\n'
        'addEventListener("load",function(){setTimeout(fitText,300)});'
        'addEventListener("hashchange",function(){setTimeout(fitText,300)});\n'
        '</script>')
    p = out_dir / "index.html"
    h = p.read_text(encoding="utf-8")
    # idempotent: re-running post_process on an already-enhanced index.html (without
    # a fresh render in between) must not stack a second <style>/<script> block.
    if "function fitText(" not in h:
        h = h.replace("</head>", inject + "</head>", 1)
        p.write_text(h, encoding="utf-8")


# ── 资源自包含打包（产物可移动/打包/发送，不依赖技能目录） ──────────────────────
_REF_RX = re.compile(r'(?:href|src)=["\'](?P<a>[^"\']+)["\']|url\((?P<u>[^)]+)\)')
_CSS_URL_RX = re.compile(r'url\((?P<u>[^)]+)\)')
_EXT_PREFIX = ("data:", "http://", "https://", "//", "#", "mailto:")


def make_portable(out: Path, renderer: Path) -> None:
    """使产物自包含：把 index.html 里所有「解析后落在技能目录内」的框架引用
    （CSS / JS / 字体 / 图）拷进 out/assets/ 并改写为 deck 本地相对引用，再跟随每个
    已拷 CSS 内部的 url()（feishu-deck.css 里的 lark logo 等）一并拷齐。结果：整个
    out/ 夹拷走 / 打包 / 发给别人都不断（否则 ../../../../…/skills/… 路径一离开仓库
    就 404）。

    判据 = 「引用解析后是否落在 renderer 技能目录内」：是→框架资源，拷进来；否→
    deck 本地（bg/、input/）或外链，原样不动。**路径无关**——不依赖 copy-assets.py
    的 runs/<ts>/output 规范布局与 (\\.\\./)+skills/feishu-deck-h5/ 正则（那套只在
    repo 根 runs/ 下才匹配），无论输出到哪都能打包成自包含。"""
    renderer = Path(os.path.realpath(renderer))
    out_real = Path(os.path.realpath(out))
    assets = out / "assets"
    html_path = out / "index.html"
    html = html_path.read_text(encoding="utf-8")
    copied: dict[str, Path] = {}   # origin-realpath → 本地 target

    def _resolve(base_dir: Path, ref: str):
        """ref 相对 base_dir 解析；返回「应被打包进来的框架文件」Path，否则 None。
        判据 = 解析后是真实文件、**在技能 renderer 内、但不在 out 内**。
        · 在 out 内（bg/、input/、或二次运行时已打包的 assets/）→ 本就 deck 本地，不动；
          ⚠ 关键：产物常输出到 skills/feishu-deck-h5/runs/<name>，bg/input 也在 renderer
          之下，单看 renderer 会误判，必须再排除 out 内。
        · 技能外（外链 / data: / 系统字体等）→ 不碰。"""
        r = ref.strip().strip("\"'")
        if not r or r.startswith(_EXT_PREFIX):
            return None
        origin = Path(os.path.realpath(base_dir / r.split("?")[0].split("#")[0]))
        if not origin.is_file():
            return None
        if origin.is_relative_to(out_real):     # 已在 deck 内 → 本地，不动
            return None
        if not origin.is_relative_to(renderer):  # 技能外 → 不碰
            return None
        return origin                            # 技能内 + out 外 = 框架资源

    def _local_target(origin: Path) -> Path:
        """技能内文件 → out/assets/ 下的落点。assets/ 子树去掉首段（不要双层
        assets/assets/）；其它子树（deck-json/templates 等）保留相对路径。"""
        rel = origin.relative_to(renderer)
        parts = rel.parts
        if parts and parts[0] == "assets":
            rel = Path(*parts[1:])
        return assets / rel

    def _copy_in(origin: Path) -> Path:
        target = _local_target(origin)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.stat().st_size != origin.stat().st_size:
            shutil.copy2(origin, target)
        copied[str(origin)] = target
        return target

    def repl_html(m):
        ref = m.group("a") or m.group("u")
        origin = _resolve(out, ref)
        if origin is None:
            return m.group(0)
        new = os.path.relpath(_copy_in(origin), out).replace(os.sep, "/")
        return m.group(0).replace(ref, new, 1)

    new_html = _REF_RX.sub(repl_html, html)
    if new_html != html:
        html_path.write_text(new_html, encoding="utf-8")

    # pass 2：已拷 CSS 内部 url() — 相对其 ORIGIN 解析，拷进同位并按 TARGET 改写
    for origin_str, target in list(copied.items()):
        if target.suffix.lower() != ".css":
            continue
        origin = Path(origin_str)
        css = target.read_text(encoding="utf-8")

        def repl_css(m):
            o = _resolve(origin.parent, m.group("u"))
            if o is None:
                return m.group(0)
            t = _copy_in(o)
            return 'url("%s")' % os.path.relpath(t, target.parent).replace(os.sep, "/")

        new_css = _CSS_URL_RX.sub(repl_css, css)
        if new_css != css:
            target.write_text(new_css, encoding="utf-8")
    print(f"    便携打包完成：{len(copied)} 个框架资源已拷入 assets/（产物自包含可移动）")
