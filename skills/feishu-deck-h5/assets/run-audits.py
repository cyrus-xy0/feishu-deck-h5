#!/usr/bin/env python3
"""run-audits.py — 统一校验引擎的瘦 runner (UNIFY-VALIDATE-ARCH-2026-06-03, 步骤 2).

只管"跑":起 1 个 headless 浏览器 → load 整份渲染好的 deck → 注入 audits.js →
按 scope(改动帧 / 全 deck)求值 → 收 findings → 出报告。本文件**不含任何规则逻辑**;
规则全在 assets/audits.js(单规则源)。

硬依赖 playwright/chromium:几何类规则(R-VIS-*)要渲染后 DOM 才能忠实判定,静态解析
做不到(见 UNIFY-VALIDATE-ARCH 文档)。playwright 缺 → 硬提示 + 非零退出,**绝不静默放行**。

用法:
    python3 run-audits.py <deck/index.html> [--slide 49|3,5|10-12] [--by-rule] [--json]

退出码:0 = 无 error 级(warn 照常打印);1 = 有 error 级(规则抛错等);2 = 环境缺依赖。
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDITS_JS = HERE / "audits.js"


def parse_scope(spec):
    """'49' / '3,5' / '10-12' / '3,10-12' -> [1-based ints]; None -> None(全 deck)."""
    if not spec:
        return None
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return sorted(set(out)) or None


def _inline_framework_css(page, base_dir):
    """把页面里 <link rel=stylesheet> 指向的【本地框架 CSS】读盘并注入成
    <style data-source="framework"> 块,让 R-CSSVAR 能用 textContent 读到框架的
    `--fs-*` 变量定义(避免把合法 var(--fs-font-latin) 误报为未定义)。

    只处理本地相对/绝对路径(跳过 http(s)/protocol-relative/data:);file:// 下
    href 形如 `../assets/feishu-deck.css`,相对 HTML 文件目录解析。读不到的安静跳过
    (该样式表本就不可用,审计自然按缺失处理,不该让 runner 崩)。镜像 validate.py 的
    inline_linked,但发生在 runner 的 load 层(纯让源可读,不含规则逻辑)。"""
    try:
        hrefs = page.evaluate(
            "() => [...document.querySelectorAll('link[rel=stylesheet]')]"
            ".map(l => l.getAttribute('href')).filter(Boolean)"
        )
    except Exception:  # noqa: BLE001
        return
    for href in hrefs:
        if href.startswith(("http:", "https:", "//", "data:")):
            continue
        # 去掉 query/fragment 再解析磁盘路径。
        clean = href.split("?", 1)[0].split("#", 1)[0]
        css_path = (base_dir / clean).resolve()
        if not css_path.is_file():
            continue
        try:
            text = css_path.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        page.evaluate(
            "(css) => { const s = document.createElement('style');"
            " s.setAttribute('data-source','framework'); s.textContent = css;"
            " document.head.appendChild(s); }",
            text,
        )


def _inline_framework_js(page, base_dir):
    """把页面里 <script src> 指向的【本地框架 JS】读盘并注入成
    <script data-source="framework" type="text/plain"> 块,让 R29-32(runtime
    chrome)能用 script textContent 读到框架 JS 源(requestFullscreen /
    fullscreenchange 等 JS-API needle、innerHTML 里的 .deck-controls 串)。

    镜像 validate.py 的 inline_linked repl_script,但发生在 runner 的 load 层:
    外链脚本在 page.goto 时已被浏览器加载执行(R29-32 的 DOM needle —— .deck-progress
    /.deck-controls/.ctl 按钮 —— 因此作为真 DOM 元素存在,渲染基底更准);这里再把源
    文本以 **type=text/plain**(不二次执行)注入,只为让源字节可被 textContent 读到,
    与 Python `script_blocks` 读源等价。只处理本地相对/绝对路径(跳过 http(s)/
    protocol-relative/data:),读不到的安静跳过。"""
    try:
        srcs = page.evaluate(
            "() => [...document.querySelectorAll('script[src]')]"
            ".map(s => s.getAttribute('src')).filter(Boolean)"
        )
    except Exception:  # noqa: BLE001
        return
    for src in srcs:
        if src.startswith(("http:", "https:", "//", "data:")):
            continue
        clean = src.split("?", 1)[0].split("#", 1)[0]
        js_path = (base_dir / clean).resolve()
        if not js_path.is_file():
            continue
        try:
            text = js_path.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            continue
        page.evaluate(
            "(js) => { const s = document.createElement('script');"
            " s.setAttribute('data-source','framework');"
            " s.setAttribute('type','text/plain'); s.textContent = js;"
            " document.body.appendChild(s); }",
            text,
        )


def _load_deck_json(base_dir):
    """Read the sibling deck.json next to index.html (SOURCE-OF-TRUTH for
    R-RAW-LOOKS-SCHEMA's raw-layout keys). Mirrors validate.py's
    audit_raw_looks_schema, which reads `Path(path).parent / 'deck.json'`:
    a raw slide commonly masks itself with a schema-ish data-layout in its
    rendered DOM, so the rendered data-layout can't distinguish raw from real
    schema — the deck.json is authoritative. Returns the parsed dict (injected
    to window.__DECK_JSON__) or None (no sidecar → rule falls back / skips,
    advisory never false-positives). Pure file read, no rule logic."""
    dj = (base_dir / "deck.json").resolve()
    if not dj.is_file():
        return None
    try:
        return json.loads(dj.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — unreadable sidecar → treat as absent
        return None


# ===========================================================================
#  RUNNER-LEVEL SOURCE-BYTE / FILE-SYSTEM CHECKS
#  ---------------------------------------------------------------------------
#  UNIFY-VALIDATE-ARCH §0/§1:绝大多数规则收敛到渲染后 DOM(audits.js)。但极少数
#  "真正只关源字节、与渲染无关"的检查 —— 浏览器会改写/补全的东西,DOM 反而做不到忠实
#  判定 —— 留在 runner 层,读 index.html 原始字节。这不是"第二套规则注册表",而是几个
#  字节/文件系统检查;它们 emit 进【同一个】 findings 列表(同 schema:rule/severity/
#  slide_idx/message),输出与 audits.js 规则完全统一。
#
#  本批三条(步骤 3 最终结构批,逐字移植自 _validate_audits.py):
#    · R-DOC-INTEGRITY(audit_doc_integrity, F-85):整文档源字节完整性 —— .deck 闭合 /
#      运行时存在 / </body></html> 截断。【必须】读原始字节:浏览器自动闭合标签,DOM
#      看不到截断(spec 明确)。
#    · R-SELF-CONTAINED(audit_self_contained):head/deck 级 <style> 命中 per-slide 选择器
#      的泄漏。原版是纯源文本 + slide-frame 字符跨度匹配(_slide_frame_spans);留 runner
#      读源 = 与 Python 零漂移(避开 runner 注入的 framework <style> 污染 DOM <style> 集)。
#    · perf(audit_perf, P50–P55):字节/体积预算(inline base64 体积、blur 半径、RO/listener
#      计数、contain/will-change 提示)—— 全是源字节/源文本检查,与渲染无关 → runner。
# ===========================================================================

# perf 阈值(逐字对应 _validate_audits.py PERF_BASE64_WARN_KB / ERROR_KB / BLUR_MAX_PX)。
PERF_BASE64_WARN_KB = 100
PERF_BASE64_ERROR_KB = 250
PERF_BLUR_MAX_PX = 10

# R-DOC-INTEGRITY / R-AUTOBALANCE 共用的 auto-balance runtime 指纹(逐字对应 _AUTOBALANCE_SIG)。
_AUTOBALANCE_SIG = "function balanceSlide(slide)"

# perf 用:迭代 <style> 块,标出 framework 注入块(逐字对应 _validate_common._iter_style_blocks)。
_STYLE_BLOCK_RE = re.compile(r"<style(?P<attrs>[^>]*)>(?P<body>.*?)</style>", re.S)


def _iter_style_blocks(html, *, include_framework=True):
    """Yield (css_text, is_framework) for each <style> block.

    镜像 _validate_common._iter_style_blocks:`<style data-source="framework">` 块
    is_framework=True(inline_linked / build.sh 内联的框架 CSS)。本 runner 读的是【原始
    index.html 字节】(框架仍是 <link>),所以正常不会出现 framework <style> 块 —— 但
    保留同一过滤逻辑与 Python 逐字一致(perf 只用 include_framework=True,与原版同)。"""
    for m in _STYLE_BLOCK_RE.finditer(html):
        attrs = m.group("attrs") or ""
        is_framework = 'data-source="framework"' in attrs
        if is_framework and not include_framework:
            continue
        yield m.group("body"), is_framework


# R-SELF-CONTAINED 源文本工具(逐字对应 _validate_audits.py / _validate_common 的私有符号)。
_SLIDE_FRAME_OPEN_RE = re.compile(
    r'<div\s+(?=[^>]*\bclass="(?:[^"]*\s)?slide-frame(?:\s[^"]*)?")[^>]*>', re.S)
_DIV_TOKEN_RE = re.compile(r"<div\b[^>]*>|</div>")
_PERSLIDE_SEL_RE = re.compile(
    r'\[data-slide-key="([^"]+)"\]|\[data-page=["\']?([\w-]+)["\']?\]')


def _slide_frame_spans(html):
    """(start, end) char-range of each <div class="slide-frame">…</div>, by
    depth-matching divs(逐字对应 _validate_audits._slide_frame_spans)。让 R-SELF-CONTAINED
    分辨 IN-slide <style>(好:co-located custom_css)vs head/deck 级 <style>(page-anim 泄漏)。"""
    spans = []
    for fm in _SLIDE_FRAME_OPEN_RE.finditer(html):
        depth, end = 1, len(html)
        for dm in _DIV_TOKEN_RE.finditer(html, fm.end()):
            depth += 1 if dm.group(0)[1] != "/" else -1
            if depth == 0:
                end = dm.start()
                break
        spans.append((fm.start(), end))
    return spans


def audit_doc_integrity_bytes(html):
    """R-DOC-INTEGRITY(err · F-85)— 整文档源字节完整性。逐字移植 _validate_audits.py
    audit_doc_integrity。读【原始 index.html 字节】(浏览器自动闭合标签,DOM 看不到截断,
    spec 明确这条【必须】在 runner 层)。返回 findings 列表(emit 进统一 findings)。

    三条 err 不变量(仅真 deck —— 无 .deck 容器的片段/replica 跳过):
      1. .deck 已开且已闭(整文档 <div> 平衡;+N 开剩余 = mid-deck 截断,.deck 未闭)。
      2. present-mode runtime 存在(linked <script src=…feishu-deck.js> OR inlined 指纹
         balanceSlide OR <script> 体内 is-current)。
      3. 文档以 </body></html> 结尾(末尾未截断)。
    opt-out:html 含 `allow:doc-integrity`。"""
    findings = []
    DOC = "R-DOC-INTEGRITY"

    def err(msg):
        findings.append({"rule": DOC, "severity": "error", "slide_idx": 0,
                         "message": msg})

    # 仅查真 deck —— 无 .deck 容器的片段/replica 非交付 deck(镜像 R-AUTOBALANCE-PRESENT 闸)。
    if not re.search(r'class="(?:[^"]*\s)?deck(?:\s[^"]*)?"', html):
        return findings
    if "allow:doc-integrity" in html:
        return findings

    # ---- Invariant 1: .deck present AND closed(整文档 <div> 开/闭平衡,剥 comment/script/style)。
    scan = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    scan = re.sub(r"<script[^>]*>.*?</script>", "", scan, flags=re.S | re.I)
    scan = re.sub(r"<style[^>]*>.*?</style>", "", scan, flags=re.S | re.I)
    div_opens = len(re.findall(r"<div\b", scan, re.I))
    div_closes = len(re.findall(r"</div\s*>", scan, re.I))
    if div_opens > div_closes:
        delta = div_opens - div_closes
        err(
            f"document has {div_opens} <div> opens vs {div_closes} </div> "
            f"closes (+{delta}) — the .deck container is opened but never "
            "closed (truncated mid-deck). The closing `</div><!-- /.deck -->` "
            "was lost (a regex/sed/manual edit ate it). In the browser the "
            "present-mode runtime cannot lay out the deck → \"显示不全 / 显示"
            "什么都没有\". Re-render via render-deck.py (never splice the deck "
            "shell by hand); inspect the most recent edit for a dropped </div>.")

    # ---- Invariant 2: present-mode runtime present(linked OR inlined)。
    linked = bool(re.search(r'<script[^>]*\bsrc="[^"]*feishu-deck\.js"', html, re.I))
    inlined = (_AUTOBALANCE_SIG in html) or any(
        "is-current" in body
        for body in re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I))
    if not (linked or inlined):
        err(
            "present-mode runtime is ABSENT — no `<script src=\"…feishu-deck.js\">` "
            "tag and no inlined runtime (auto-balance fingerprint "
            f"`{_AUTOBALANCE_SIG}` not found). Without the runtime, present mode "
            "never initializes — `is-current` is never set on any .slide-frame, "
            "so the deck renders blank / \"显示不全\". A linked deck needs "
            "`<script src=\"…/assets/feishu-deck.js\"></script>` before </body>; a "
            "single-file deck (build.sh --inline) inlines the JS. Re-render via "
            "render-deck.py rather than hand-editing the deck shell.")

    # ---- Invariant 3: document ends well-formed(</body> </html> 存在)。
    missing = [t for t in ("</body>", "</html>") if t.lower() not in html.lower()]
    if missing:
        err(
            f"document is truncated at the end — missing {' and '.join(missing)}. "
            "A complete deck ends with `</div><!-- /.deck --><script …></script>"
            "</body></html>`. Truncation means closing tags / the runtime script "
            "were lost (regex/manual edit), and the browser will not finish "
            "parsing/initializing the deck → \"显示不全\". Re-render via "
            "render-deck.py.")
    return findings


def audit_self_contained_bytes(html):
    """R-SELF-CONTAINED(warn_soft · ADVISORY)— per-slide CSS 必须住在它所样式的 slide 内。
    逐字移植 _validate_audits.py audit_self_contained。读源字节:head/deck 级 <style> 命中
    per-slide 选择器([data-slide-key=…] / [data-page=…])= page-anim 泄漏(re-render/lift
    会静默丢失)。framework 块(data-source="framework")与 co-located 进 .slide 的块豁免。
    返回 findings(warn_soft)。"""
    findings = []
    frame_spans = _slide_frame_spans(html)

    def inside_a_slide(pos):
        return any(a <= pos < b for a, b in frame_spans)

    for m in _STYLE_BLOCK_RE.finditer(html):
        if 'data-source="framework"' in (m.group("attrs") or ""):
            continue                       # inlined framework CSS — generic, not per-slide
        if inside_a_slide(m.start()):
            continue                       # co-located inside a slide → the GOOD pattern
        refs = _PERSLIDE_SEL_RE.findall(m.group("body") or "")
        if not refs:
            continue
        keys = sorted({(r[0] or ("data-page=" + r[1])) for r in refs})
        findings.append({
            "rule": "R-SELF-CONTAINED", "severity": "warn_soft", "slide_idx": 0,
            "message":
                f"head/deck-level <style> targets per-slide selector(s) {keys[:6]} "
                "but sits OUTSIDE the slide. Move those rules into the slide's "
                "`custom_css` (deck.json) — the renderer scopes + co-locates them "
                "inside .slide so they travel on lift/clone and survive republish "
                "(a head/page <style> silently vanishes on re-render and is left "
                "behind on lift). See SKILL.md \"LIFTING A SLIDE FROM ANOTHER DECK\" / "
                "LIFT-ARCHITECTURE-2026-05-30.md. [advisory · non-blocking until L7]",
        })
    return findings


def audit_perf_bytes(html):
    """perf(P50–P55)— 性能预算字节/源文本检查。逐字移植 _validate_audits.py audit_perf。
    P50 = inline base64 体积(linked 模式才查;<meta fs-deck-mode=inline> 豁免);P51 = blur
    半径上限;P52 = ResizeObserver 计数;P53 = addEventListener 无 AbortController;P54 =
    .slide-frame 缺 contain;P55 = .slide 缺 will-change。返回 findings(P50 可 err,余 warn)。"""
    findings = []

    def warn(code, msg):
        findings.append({"rule": code, "severity": "warn", "slide_idx": 0,
                         "message": msg})

    # Detect intentional inline-delivery mode
    inline_mode = bool(re.search(
        r'<meta[^>]*name="fs-deck-mode"[^>]*content="inline"', html))

    # Extract style + script text once (used by P50 / P51 / P54 / P55)
    style_text = " ".join(body for body, _is_fw in _iter_style_blocks(html))
    script_text = " ".join(re.findall(r"<script[^>]*>(.*?)</script>", html, re.S))

    # --- P50: base64 payload inside <style> (linked mode only) ---
    if not inline_mode:
        base64_bytes = sum(len(m.group(0)) for m in
                           re.finditer(r"data:image/[^\"'\s)]+", style_text))
        base64_kb = base64_bytes // 1024
        if base64_kb >= PERF_BASE64_ERROR_KB:
            findings.append({"rule": "P50", "severity": "error", "slide_idx": 0,
                "message":
                    f"inline base64 in <style>: {base64_kb} KB ≥ {PERF_BASE64_ERROR_KB} KB hard cap. "
                    "Use linked assets (<link rel=\"stylesheet\"> + external --fs-asset-* "
                    "image files) for the default delivery; inline only for single-file "
                    "email/IM mode (build.sh --inline). If this IS intentional inline mode, "
                    "add `<meta name=\"fs-deck-mode\" content=\"inline\">` in <head>."})
        elif base64_kb >= PERF_BASE64_WARN_KB:
            warn("P50",
                 f"inline base64 in <style>: {base64_kb} KB ≥ {PERF_BASE64_WARN_KB} KB "
                 "soft budget. Use linked CSS for default delivery, or add "
                 "`<meta name=\"fs-deck-mode\" content=\"inline\">` to mark this as "
                 "intentional single-file mode.")

    # --- P51: backdrop-filter blur radius cap ---
    for m in re.finditer(r"backdrop-filter:\s*blur\((\d+)px\)", html):
        radius = int(m.group(1))
        if radius > PERF_BLUR_MAX_PX:
            warn("P51",
                 f"backdrop-filter: blur({radius}px) exceeds {PERF_BLUR_MAX_PX}px "
                 "cap — GPU cost scales with blur radius. Use opaque rgba "
                 "background instead, or ≤ 8px blur.")

    # --- P52: ResizeObserver count (one per frame is bad — should be 1 total) ---
    ro_count = len(re.findall(r"new\s+ResizeObserver\(", script_text))
    if ro_count > 1:
        warn("P52",
             f"JS instantiates {ro_count} ResizeObservers — one per frame causes "
             f"{ro_count}× layout reads on every viewport change. Use one "
             "document-level RO with rAF batching that iterates frames.forEach.")

    # --- P53: addEventListener without AbortController / removeEventListener ---
    add_count = script_text.count("addEventListener")
    has_abort_controller = "AbortController" in script_text or "controller.abort" in script_text
    rm_count = script_text.count("removeEventListener")
    if add_count >= 8 and not has_abort_controller and rm_count == 0:
        warn("P53",
             f"JS binds {add_count} addEventListener calls with no AbortController "
             "and no removeEventListener. Embedding the deck in an SPA host "
             "leaks listeners on every re-mount. Wrap init() in a single "
             "AbortController and pass {{ signal }} to every addEventListener.")

    # --- P54: missing CSS containment hint on .slide-frame ---
    if ".slide-frame" in style_text and "contain:" not in style_text:
        warn("P54",
             ".slide-frame has no `contain:` hint. Adding `contain: layout paint "
             "size` lets the browser scope reflows to the frame, turning slide "
             "changes from full-document repaints into local ones.")

    # --- P55: missing will-change on the scaled .slide ---
    slide_rule = re.search(r"\.slide-frame\s+\.slide\s*\{([^}]*)\}", style_text, re.S)
    if slide_rule and "will-change" not in slide_rule.group(1):
        warn("P55",
             ".slide-frame .slide has no `will-change: transform` hint. Without "
             "it, the scale transform may not get a GPU layer, causing CPU "
             "rasterization on every transition.")
    return findings


def _inline_linked_text(html_text, base_dir):
    """把 <link rel=stylesheet> / <script src> 的【本地框架文件】读盘内联进 HTML 文本
    (<style data-source="framework"> / <script data-source="framework">)。逐字镜像
    validate.py 的 inline_linked(F-14):外部 http(s)/data: 与缺失文件原样保留。

    为什么 perf 检查要在【内联后】文本上跑:validate.py 在 run_static_audits 前先跑
    inline_linked,所以 audit_perf 看到的 style_text/script_text【含框架 CSS/JS】。P50
    (base64 体积)、P54(.slide-frame contain)、P55(.slide will-change)都依赖框架 CSS
    是否提供这些声明 —— 若 runner 只读 raw(框架仍是 <link>),会与 Python 漂移(框架
    的 contain:/will-change: 看不到 → P54/P55 误报)。在内联后文本上跑 = 与 Python 同源、
    零漂移。(R-DOC-INTEGRITY / R-SELF-CONTAINED 不在此跑:前者【必须】读 raw 抓截断,
    后者框架在 raw 里是 <link> 天然被排除,与 Python 跳过 data-source=framework 等价。)"""
    def repl_link(m):
        tag = m.group(0)
        if 'rel="stylesheet"' not in tag:
            return tag
        hm = re.search(r'href="([^"]+)"', tag)
        if not hm:
            return tag
        href = hm.group(1)
        if href.startswith(("http:", "https:", "data:")):
            return tag
        target = (base_dir / href).resolve()
        if not target.is_file():
            return tag
        try:
            return ('<style data-source="framework">'
                    + target.read_text(encoding="utf-8") + "</style>")
        except Exception:  # noqa: BLE001 — 读不到就原样保留(与 audit 缺失处理一致)
            return tag
    html_text = re.sub(r"<link\b[^>]*>", repl_link, html_text)

    def repl_script(m):
        src = m.group(1)
        if src.startswith(("http:", "https:", "data:")):
            return m.group(0)
        target = (base_dir / src).resolve()
        if not target.is_file():
            return m.group(0)
        try:
            return ('<script data-source="framework">'
                    + target.read_text(encoding="utf-8") + "</script>")
        except Exception:  # noqa: BLE001
            return m.group(0)
    html_text = re.sub(
        r'<script[^>]*src="([^"]+)"[^>]*>\s*</script>', repl_script, html_text)
    return html_text


def runner_source_byte_findings(html, base_dir):
    """跑全部 runner 层源字节/文件系统检查,合并成统一 findings(同 schema)。
    与 audits.js 规则同列表、同字段 → 报告层无需区分来源。顺序:R-DOC-INTEGRITY →
    R-SELF-CONTAINED → perf(与 STATIC_AUDITS 注册顺序对齐,纯 cosmetic)。

    `html` = 原始 index.html 字节(R-DOC-INTEGRITY 必须读 raw 抓截断;R-SELF-CONTAINED
    在 raw 上框架是 <link> 天然排除 = 与 Python 等价)。perf 在【内联框架后】文本上跑,
    与 validate.py(run_static_audits 前已 inline_linked)同源,零漂移。"""
    out = []
    out.extend(audit_doc_integrity_bytes(html))
    out.extend(audit_self_contained_bytes(html))
    out.extend(audit_perf_bytes(_inline_linked_text(html, base_dir)))
    return out


def main():
    ap = argparse.ArgumentParser(description="统一校验引擎 runner(单规则源 audits.js)")
    ap.add_argument("html", type=Path, help="渲染好的 deck index.html")
    ap.add_argument("--slide", help="scope:1-based 帧号,如 49 / 3,5 / 10-12(默认全 deck)")
    ap.add_argument("--by-rule", action="store_true", help="按规则分组输出(而非业务/逐页)")
    ap.add_argument("--json", action="store_true", help="原始 JSON 输出")
    ap.add_argument("--settle-ms", type=int, default=350, help="load 后等布局稳定的毫秒")
    args = ap.parse_args()

    if not args.html.is_file():
        print(f"ERROR: 找不到文件 {args.html}", file=sys.stderr)
        sys.exit(2)
    if not AUDITS_JS.is_file():
        print(f"ERROR: 规则源缺失 {AUDITS_JS}", file=sys.stderr)
        sys.exit(2)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "ERROR: 统一校验引擎需要 playwright/chromium —— 这是硬依赖,绝不静默放行。\n"
            "  几何类规则(R-VIS-CANVAS-CENTER 等)必须在渲染后 DOM 上判定,静态解析做不到。\n"
            "  安装:pip install playwright && python -m playwright install chromium\n"
            "  (若确需仅静态档,显式跑 `validate.py --no-visual`,但 R-VIS-* 几何规则不会被执行。)",
            file=sys.stderr,
        )
        sys.exit(2)

    scope = parse_scope(args.slide)
    audits_src = AUDITS_JS.read_text(encoding="utf-8")
    url = args.html.resolve().as_uri()
    # ── runner 层源字节检查读【原始 index.html 字节】(浏览器自动闭合标签会抹掉截断信号,
    #    DOM 看不到 —— R-DOC-INTEGRITY 等【必须】读字节,见上方函数注释 / UNIFY-VALIDATE §0)。
    raw_html = args.html.read_text(encoding="utf-8", errors="replace")

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = context.new_page()
            page.goto(url, wait_until="load", timeout=30_000)
            page.wait_for_timeout(args.settle_ms)  # 让 scale-to-fit / 布局稳定
            # ── 把链接的【框架 CSS】源文本注入成 <style data-source="framework"> ──
            # R-CSSVAR 要读"所有 CSS 源文本"判定 var(--x) 定义/引用,而 file:// 下外链
            # 样式表的 cssRules 被 CORS 挡、且浏览器会丢掉含未定义 var() 的整条声明(正是
            # 本规则要抓的东西)→ CSSOM 读不到。validate.py 的 audit_undefined_css_vars 同样
            # 依赖 inline_linked 先把框架 CSS 拉进 <style data-source=framework>。这里在
            # runner(load 层)做同一件事:读盘 → 注入文本,纯"让源可读",不含规则逻辑。
            _inline_framework_css(page, args.html.parent)
            # ── 把链接的【框架 JS】源文本注入成 <script data-source="framework"
            #    type="text/plain"> ── R29-32 要读 JS 源判 requestFullscreen 等
            #    needle;外链脚本已执行(DOM needle 是真元素),这里只补源可读(不二次执行)。
            _inline_framework_js(page, args.html.parent)
            # ── 把旁边的 deck.json(若存在)注入 window.__DECK_JSON__ ──
            # R-RAW-LOOKS-SCHEMA 的 SOURCE-OF-TRUTH 是 deck.json 的 layout:"raw" key
            # (渲染后 data-layout 会伪装借框架 CSS,不可信);与 validate.py
            # audit_raw_looks_schema 读 index.html 旁 deck.json 等价。纯文件读,不含规则逻辑。
            deck_json = _load_deck_json(args.html.parent)
            page.evaluate("(dj) => { window.__DECK_JSON__ = dj; }", deck_json)
            page.evaluate("(s) => { window.__AUDIT_SCOPE__ = s; }", scope)
            result = page.evaluate(audits_src)
            browser.close()
    except Exception as e:  # noqa: BLE001 — runner 层兜底,报清楚比吞掉好
        print(f"ERROR: 渲染/求值失败:{e}", file=sys.stderr)
        sys.exit(2)

    findings = result.get("findings", [])
    # ── 合并 runner 层源字节/文件系统检查(R-DOC-INTEGRITY / R-SELF-CONTAINED / perf)。
    #    这些是整文档级(slide_idx=0),与 scope 无关、始终对整份源跑(与 Python 静态档always-run
    #    等价);emit 进【同一】 findings 列表、同 schema,报告层不区分来源。runner 检查的规则名
    #    也并入 result['rules'](去重、保序)让头部 "规则 …" 列表完整。
    runner_findings = runner_source_byte_findings(raw_html, args.html.parent)
    findings = findings + runner_findings
    result["findings"] = findings
    rules = list(result.get("rules", []))
    for f in runner_findings:
        if f["rule"] not in rules:
            rules.append(f["rule"])
    result["rules"] = rules

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        scope_desc = f"scope={scope}" if scope else f"全 deck({result.get('slides_total')} 帧)"
        print(f"统一校验引擎 audits.js v{result.get('version')} · {scope_desc} · "
              f"规则 {','.join(result.get('rules', []))}")
        if not findings:
            print("  ✅ 无 finding")
        elif args.by_rule:
            by = {}
            for f in findings:
                by.setdefault(f["rule"], []).append(f)
            for rule, fs in sorted(by.items()):
                print(f"  ── {rule} ({len(fs)}) ──")
                for f in fs:
                    print(f"    [{f['severity']}] {f['message']}")
        else:
            for f in sorted(findings, key=lambda x: (x.get("slide_idx", 0), x["rule"])):
                print(f"  [{f['severity']}] {f['message']}")

    sys.exit(1 if any(f.get("severity") == "error" for f in findings) else 0)


if __name__ == "__main__":
    main()
