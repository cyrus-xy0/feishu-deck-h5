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
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDITS_JS = HERE / "audits.js"


def parse_scope(spec):
    """'49' / '3,5' / '10-12' / '3,10-12' -> [1-based ints]; None -> None(全 deck).

    Slide ordinals are 1-based, so 0 / negative / reversed (a>b) ranges are
    INVALID — silently accepting them yields a scope set that matches NO frame
    (`scopeSet.has(slide_idx)` is always false), turning a scoped run into a
    no-op false PASS that skips every rule. Reject them loudly with ValueError so
    the caller can surface the bad input instead of green-lighting nothing."""
    if not spec:
        return None
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part.lstrip("-"):  # a range (ignore a leading '-' sign on `a`)
            a_str, b_str = part.rsplit("-", 1)
            a, b = int(a_str), int(b_str)
            if a < 1 or b < 1:
                raise ValueError(
                    f"invalid scope range {part!r}: slide ordinals are 1-based "
                    "(0 / negative not allowed)")
            if a > b:
                raise ValueError(
                    f"invalid scope range {part!r}: start {a} > end {b} "
                    "(reversed range matches no frame)")
            out.extend(range(a, b + 1))
        else:
            n = int(part)
            if n < 1:
                raise ValueError(
                    f"invalid scope frame {n!r}: slide ordinals are 1-based "
                    "(0 / negative not allowed)")
            out.append(n)
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
    """Read the sibling deck.json next to index.html (SOURCE-OF-TRUTH for the
    true authored `layout` of each slide — R-LAYOUT-DEPRECATED's key→layout map).
    A raw slide commonly masks itself with a schema-ish data-layout in its
    rendered DOM, so the rendered data-layout can't distinguish raw from real
    schema — the deck.json is authoritative. Returns the parsed dict (injected
    to window.__DECK_JSON__) or None (no sidecar → rule skips, advisory never
    false-positives). Pure file read, no rule logic.
    (Until 2026-06-12 this also fed the retired R-RAW-LOOKS-SCHEMA.)"""
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
#  这里分两组:
#
#  (A) 两条路径都跑(runner_source_byte_findings;dom_rules True/False 皆执行 —— 浏览器
#      看不到忠实结果,audits.js 不发或方向不同,不会双报):
#    · R-DOC-INTEGRITY(audit_doc_integrity, F-85):整文档源字节完整性 —— .deck 闭合 /
#      运行时存在 / </body></html> 截断。【必须】读原始字节:浏览器自动闭合标签,DOM
#      看不到截断(spec 明确)。invariant-1 抓【under-close】(opens>closes)。
#    · R-DOM(audit_dom_balance_bytes):invariant-3 = <body> <div> 开/闭【over-close】
#      平衡(多余 </div>)。旧 audit_dom_integrity 三条不变量迁移只保留 1&2 到 audits.js
#      (slide-frame 嵌套 / 每帧恰一 .slide),丢了 invariant-3 —— 浏览器自动补全后渲染
#      DOM 永远平衡,DOM 看不到 → 必须读源字节、且两路径都跑。只报 over-close(R-DOC-
#      INTEGRITY 已抓 under-close,方向互补不重复)。
#    · R-SELF-CONTAINED(audit_self_contained):head/deck 级 <style> 命中 per-slide 选择器
#      的泄漏。原版是纯源文本 + slide-frame 字符跨度匹配(_slide_frame_spans);留 runner
#      读源 = 与 Python 零漂移(避开 runner 注入的 framework <style> 污染 DOM <style> 集)。
#    · perf(audit_perf, P50–P55):字节/体积预算(inline base64 体积、blur 半径、RO/listener
#      计数、contain/will-change 提示)—— 全是源字节/源文本检查,与渲染无关 → runner。
#
#  (B) 只在 NO-BROWSER 路径跑(runner_no_browser_text_findings;仅 dom_rules=False —— 这些
#      rule code audits.js 已在渲染后 DOM 上覆盖,--visual 路径跑这套会双报,故此路径专用):
#    · R-KEY(audit_slide_keys_bytes)/ R-ESC-HTML(audit_escaped_html_bytes)/
#      R02 + R07(audit_structure_bytes,R07 对 canvas/imported 豁免,parity with audits.js)/
#      R05(audit_copy_bytes,IMPORTED deck 降 warn_soft)。
#    H1 恢复:迁移后默认 --no-visual 闸(render-deck 默认门 + write-hook)曾只剩 R-DOC-INTEGRITY
#    /R-SELF-CONTAINED/perf,丢了 ~34 条源文本审计 —— 把"真正只关源字节"的几条搬回字节路径,
#    让无 Chromium 的默认门重获真实静态强制。
# ===========================================================================

# perf 阈值(逐字对应 _validate_audits.py PERF_BASE64_WARN_KB / ERROR_KB / BLUR_MAX_PX)。
PERF_BASE64_WARN_KB = 100
PERF_BASE64_ERROR_KB = 250
PERF_BLUR_MAX_PX = 10

# BYTE_RULE_META — coverage contract for the runner-level source-byte rules
# (UNIFY-VALIDATE-ARCH §coverage, PR3). This is the BYTE half of the unified rule
# surface; the DOM half is RULE_META in audits.js. Together they make EVERY rule —
# whether it runs as a computed-DOM check in the headless browser or a source-byte
# check here in the runner — carry an explicit coverage declaration, so "covers
# raw + schema by default" is machine-enforced across BOTH physical engines, not
# just the DOM one. These are all name-free source/byte scans (they key on bytes,
# never on framework class names) → coverage 'universal' (fire on raw and schema
# alike). Enforced by deck-json/tests/test_byte_rule_contract.py: every rule code
# the byte functions emit must be declared here with signal 'bytes'.
BYTE_RULE_META = {
    "R-DOC-INTEGRITY":  {"coverage": "universal", "signal": "bytes"},
    "R-BAKED-DOM":      {"coverage": "universal", "signal": "bytes"},   # serialized post-JS DOM (data-idx / baked .deck-ui / data-js-ready) — must re-render from deck.json
    "R-PROVENANCE":     {"coverage": "conditional", "signal": "bytes"},  # runs/ + sibling deck.json only — render-deck stamp present + deck.json hash matches (F-266)
    "R-DOM":            {"coverage": "universal", "signal": "bytes"},   # over-close byte half (under-close/struct DOM half in audits.js)
    "R-SELF-CONTAINED": {"coverage": "universal", "signal": "bytes"},
    "R-KEY":            {"coverage": "universal", "signal": "bytes"},   # no-browser path (DOM half in audits.js)
    "R-ESC-HTML":       {"coverage": "universal", "signal": "bytes"},
    "R02":              {"coverage": "universal", "signal": "bytes"},
    "R05":              {"coverage": "universal", "signal": "bytes"},
    "R07":              {"coverage": "universal", "signal": "bytes"},
    "P50": {"coverage": "universal", "signal": "bytes"},
    "P51": {"coverage": "universal", "signal": "bytes"},
    "P52": {"coverage": "universal", "signal": "bytes"},
    "P53": {"coverage": "universal", "signal": "bytes"},
    "P54": {"coverage": "universal", "signal": "bytes"},
    "P55": {"coverage": "universal", "signal": "bytes"},
}

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


# ===========================================================================
#  NO-BROWSER SOURCE-TEXT RULES (run ONLY when dom_rules=False)
#  ---------------------------------------------------------------------------
#  H1 restore (UNIFY-VALIDATE-ARCH follow-up): the unified engine's DEFAULT
#  --no-visual gate (validate.py's run_unified_audits(dom_rules=False), used by
#  render-deck.py's default gate + the write-hook) used to run ONLY R-DOC-
#  INTEGRITY / R-SELF-CONTAINED / perf — it had LOST the ~34 source-text audits
#  that ran unconditionally pre-migration. The genuinely source-text-only rules
#  below are restored into the no-browser BYTE path so that gate regains real
#  enforcement WITHOUT Chromium.
#
#  CRITICAL — NO DOUBLE-EMIT: these run ONLY when dom_rules=False. When
#  dom_rules=True (the --visual path), audits.js already evaluates the SAME rule
#  codes (R-KEY / R-ESC-HTML / R02 / R07 / R05) against the rendered DOM, so the
#  byte path must stay silent there or every finding would appear twice. They are
#  wired into runner_no_browser_text_findings(), which run_unified_engine only
#  calls on the dom_rules=False branch.
#
#  Rules (逐字移植自 _validate_audits.py @ git 076dc44):
#    · R-KEY      ← audit_slide_keys      (duplicate / missing / invalid / positional key)
#    · R-ESC-HTML ← audit_escaped_html    (literal escaped markup &lt;span …&gt; in text)
#    · R02 / R07  ← audit_structure       (per-frame data-layout + data-screen-label + .wordmark)
#                   — R07 (missing .wordmark) EXEMPT for canvas slides
#                     (data-layout="canvas") + imported decks (<meta fs-deck-origin
#                     =imported>), MIRRORING the audits.js R07 exemption (canvas
#                     dropped its .wordmark in commit 941f781, so without the
#                     exemption every PPTX-import/canvas deck would fail R07 on
#                     every slide at the --visual/ingest/publish gate).
#    · R05        ← audit_copy_rules      (emoji / '!' / '…' / '???' in slide copy;
#                     IMPORTED deck downgrades err→warn_soft)
#  (R-DOM div-balance — the over-close direction R-DOC-INTEGRITY misses — runs in
#   BOTH paths; see audit_dom_balance_bytes below.)
# ===========================================================================

# R-KEY 源工具(逐字对应 _validate_audits.py audit_slide_keys 内的局部正则)。
_SLIDE_OPEN_RE = re.compile(r'<div\s+(?=[^>]*\bclass="(?:[^"]*\s)?slide(?:\s[^"]*)?")[^>]*>', re.S)
_KEY_SLUG_RE = re.compile(r'data-slide-key="([^"]*)"')
_KEY_VALID_SLUG_RE = re.compile(r'^[a-z][a-z0-9-]*$')   # MUST match deck-schema.json key pattern
_KEY_POSITIONAL_RE = re.compile(r'^(slide|page|section|frame)-?\d+$')

# R-ESC-HTML 源工具(逐字对应 _validate_audits.py _ESC_TAGS / _ESCAPED_TAG_RE)。
_ESC_TAGS = (r'span|b|i|em|strong|div|p|br|h[1-6]|ul|ol|li|a|svg|img|'
             r'small|sup|sub|mark|code')
_ESCAPED_TAG_RE = re.compile(
    r'&lt;/?(?:' + _ESC_TAGS + r')\s*/?&gt;'               # (A) <br> </span> <b> <br/>
    r'|&lt;(?:' + _ESC_TAGS + r')\s+[a-zA-Z][\w-]*\s*=',   # (B) <span class= / <a href=
    re.I)

# R02/R07 + R05 provenance 工具(逐字对应 _validate_audits.py _slide_is_lifted /
# _deck_imported / _deck_all_imported)。canvas/imported 检测与 audits.js 的 UI1/R07
# 豁免同源(isCanvas = data-layout="canvas";imported = deck 级 fs-deck-origin=imported)。
_DECK_IMPORTED_META_RE = re.compile(
    r'<meta\s+name=["\']fs-deck-origin["\']\s+content=["\']imported["\']')
_LIFTED_SLIDE_RE = re.compile(r'<div class="slide(?:\s[^"]*)?"[^>]*>')


def _extract_slide_frames(html):
    """Per-slide HTML strings, one per <div class="slide-frame">…(end-of-frame).
    逐字镜像 _validate_common.extract_slides:body 内剥 comment/script,再按 slide-frame
    开标签 split。R-KEY / R02 / R07 逐帧扫源字节用它(与渲染后 querySelectorAll('.slide') 等价)。"""
    body_m = re.search(r"<body[^>]*>(.*)</body>", html, re.S)
    if not body_m:
        return []
    body = body_m.group(1)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    body = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.S)
    parts = _SLIDE_FRAME_OPEN_RE.split(body)
    return parts[1:]   # discard preamble before first slide-frame


def _frame_attr(fr, name):
    """data-<name> value in a slide-frame chunk(逐字对应 _validate_common.slide_attr)。"""
    m = re.search(rf'data-{name}="([^"]+)"', fr)
    return m.group(1) if m else None


def _slide_is_lifted_bytes(fr):
    """True if a slide-frame chunk carries data-lifted(逐字对应 _slide_is_lifted)。"""
    return "data-lifted" in fr


def _deck_imported_bytes(html):
    """True if deck stamps <meta name="fs-deck-origin" content="imported">
    (逐字对应 _deck_imported)。R07 豁免 + R05 降级共用;与 audits.js deckOriginImported 同源。"""
    return bool(_DECK_IMPORTED_META_RE.search(html))


def _deck_all_imported_bytes(html, frames=None):
    """True if EVERY .slide is imported/lifted, OR deck stamps origin=imported
    (逐字对应 _deck_all_imported)。R05 deck-wide 降级 scope 用(与 audits.js deckAllImported 同源)。"""
    if _deck_imported_bytes(html):
        return True
    frames = _extract_slide_frames(html) if frames is None else frames
    if not frames:
        return False
    return all(_slide_is_lifted_bytes(fr) for fr in frames)


def audit_slide_keys_bytes(html):
    """R-KEY(err/warn)— 每个 .slide 必带唯一、kebab-case、语义的 data-slide-key。
    逐字移植 _validate_audits.py audit_slide_keys(在源字节上跑;NO-BROWSER 路径专用,
    audits.js 的 R-KEY 已覆盖 --visual 路径)。空/非法 slug、重复 = err;positional = warn
    (lifted 页降 warn_soft);缺 key = err。返回统一 findings(slide_idx=0,与原版逐帧 'slide N'
    文案对齐)。"""
    findings = []

    def err(msg):
        findings.append({"rule": "R-KEY", "severity": "error", "slide_idx": 0,
                         "message": msg})

    def warn(msg):
        findings.append({"rule": "R-KEY", "severity": "warn", "slide_idx": 0,
                         "message": msg})

    def warn_soft(msg):
        findings.append({"rule": "R-KEY", "severity": "warn_soft", "slide_idx": 0,
                         "message": msg})

    frames = _extract_slide_frames(html)
    seen = {}        # slug -> first slide index it appeared in
    missing = []
    for i, fr in enumerate(frames, 1):
        m = _KEY_SLUG_RE.search(fr)
        if not m:
            missing.append(i)
            continue
        slug = m.group(1)
        if not slug:
            err(f'slide {i}: data-slide-key is empty. '
                'Set a semantic kebab-case slug (e.g. "arr-history", "cover", '
                '"case-meiyijia"). Required by feishu-slide-library locator.')
            continue
        if not _KEY_VALID_SLUG_RE.match(slug):
            err(f'slide {i}: data-slide-key="{slug}" is not valid kebab-case. '
                'Use lowercase letters, digits, and `-` only; must start with '
                'an alphanumeric. Example: "arr-history" not "ARR_History".')
            continue
        if _KEY_POSITIONAL_RE.match(slug):
            if _slide_is_lifted_bytes(fr):
                warn_soft(
                    f'slide {i}: data-slide-key="{slug}" is positional — '
                    'IMPORTED/lifted slide (key carried from source ordering); '
                    'soft advisory, rename to a semantic slug if you keep it.')
            else:
                warn(
                    f'slide {i}: data-slide-key="{slug}" is positional — it '
                    'breaks when slides reorder. Use a semantic slug naming '
                    'what the slide is ABOUT (e.g. "arr-history" instead of '
                    '"slide-06").')
        if slug in seen:
            err(f'slide {i}: data-slide-key="{slug}" already used by '
                f'slide {seen[slug]}. Slugs must be deck-internal unique. '
                'Pick a different semantic slug or add a suffix '
                f'(e.g. "{slug}-v2").')
        else:
            seen[slug] = i
    if missing:
        err(f'{len(missing)} slide(s) missing data-slide-key '
            f'(slide indices: {", ".join(map(str, missing[:5]))}'
            f'{", …" if len(missing) > 5 else ""}). '
            'Every .slide must carry a semantic kebab-case slug so the '
            'feishu-slide-library skill can index it. Add '
            '`data-slide-key="<slug>"` next to data-screen-label.')
    return findings


def audit_escaped_html_bytes(html, scope=None):
    """R-ESC-HTML(err)— 文本里出现被转义的 HTML 标签(如 `&lt;span class=…`)。
    逐字移植 _validate_audits.py audit_escaped_html(源字节;NO-BROWSER 专用,audits.js 已覆盖
    --visual)。逐帧剥 style/script 后扫 _ESCAPED_TAG_RE;命中即 err。返回统一 findings。

    per-slide rule → honors `scope`(1-based 帧号集合)和 audits.js driver 一致:scope 外
    的帧不评(否则 `--scope-frames N` 在 no-visual 路径会漏报 off-scope 帧的旧问题,与 --visual
    路径结果分叉)。scope=None → 全 deck。"""
    findings = []
    for i, fr in enumerate(_extract_slide_frames(html), 1):
        if scope is not None and i not in scope:
            continue
        scan = re.sub(r"<style\b[^>]*>.*?</style>", "", fr, flags=re.S | re.I)
        scan = re.sub(r"<script\b[^>]*>.*?</script>", "", scan, flags=re.S | re.I)
        hits = _ESCAPED_TAG_RE.findall(scan)
        if not hits:
            continue
        sample = hits[0].replace("&lt;", "<").replace("&gt;", ">")
        findings.append({
            "rule": "R-ESC-HTML", "severity": "error", "slide_idx": 0,
            "message":
                f'slide {i}: 文本里出现被转义的 HTML 标签(如 `{sample}…`)。'
                '裸 HTML 进了 schema 的转义文本字段(content/3up 等的 lede / body / '
                'title 走 `{{ field }}`,会被 _esc_br 转义),所以原样显示成"乱码"。'
                '修法:把这页改成 `layout: raw` 自己控 markup(行内高亮 / svg 都放这),'
                '或去掉标签改用该字段支持的强调方式;换行用 \\n(渲染器会转 <br>),'
                '不要写字面 <br>。raw 页 / `{{{ raw }}}` 字段输出的是真标签、不会变 '
                '&lt;,因此不会被本规则误报。',
        })
    return findings


def audit_structure_bytes(html, scope=None):
    """R02 / R07(err)— 每帧必有 data-layout + data-screen-label + .wordmark。
    逐字移植 _validate_audits.py audit_structure 的可逐帧部分(R13 单行标题留在 audits.js)。
    NO-BROWSER 专用,audits.js 的 R02-R07-STRUCTURE 已覆盖 --visual 路径。

    per-slide rule → honors `scope`(1-based 帧号集合,与 audits.js driver 一致);scope 外
    的帧不评。scope=None → 全 deck。

    ⚠️ R07 豁免 parity:缺 .wordmark 对 canvas 帧(data-layout="canvas")与 imported deck
    (deck 级 <meta fs-deck-origin=imported>)豁免 —— 与 audits.js R07 / UI1 用的同一
    isCanvas / imported 检测同源。941f781 删掉了 canvas 模板的 .wordmark(canvas 成了唯一
    无 wordmark 的片段),不豁免的话每份 PPTX 导入 / canvas deck 会在 --visual/ingest/publish
    闸上每帧 R07 误报。返回统一 findings。"""
    findings = []
    imported = _deck_imported_bytes(html)   # deck 级 fs-deck-origin=imported(同 audits.js deckOriginImported)
    for i, fr in enumerate(_extract_slide_frames(html), 1):
        if scope is not None and i not in scope:
            continue
        layout = _frame_attr(fr, "layout")
        label = _frame_attr(fr, "screen-label")
        if not layout:
            findings.append({"rule": "R02", "severity": "error", "slide_idx": 0,
                             "message": f"slide {i}: missing data-layout"})
        if not label:
            findings.append({"rule": "R02", "severity": "error", "slide_idx": 0,
                             "message": f"slide {i}: missing data-screen-label"})
        if 'class="wordmark' not in fr:
            is_canvas = (layout == "canvas")   # 同 audits.js R07/UI1 的 isCanvas
            if is_canvas or imported:
                continue                       # R07 豁免:canvas / imported(parity with audits.js)
            # 文案与 Python 逐字对齐:layout 为空 → slide_attr 返回 None → f-string 渲染 `None`。
            layout_repr = layout if layout else "None"
            findings.append({"rule": "R07", "severity": "error", "slide_idx": 0,
                             "message":
                                 f"slide {i} ({layout_repr}): missing .wordmark"})
    return findings


def audit_copy_bytes(html):
    """R05(err / IMPORTED→warn_soft)— slide 文本里禁 emoji / '!' / '…' / '???'。
    逐字移植 _validate_audits.py audit_copy_rules(源字节;NO-BROWSER 专用,audits.js 已覆盖
    --visual)。剥 script/style/svg + 标签后扫文本;IMPORTED deck(全 lifted / origin=imported)
    降 warn_soft。返回统一 findings。"""
    findings = []
    body_m = re.search(r"<body[^>]*>(.*)</body>", html, re.S)
    if not body_m:
        return findings
    body = re.sub(r"<script.*?</script>", "", body_m.group(1), flags=re.S)
    body = re.sub(r"<style.*?</style>", "", body, flags=re.S)
    body = re.sub(r"<svg.*?</svg>", "", body, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", body)

    imported = _deck_all_imported_bytes(html)
    note = (" — IMPORTED deck (verbatim-carried content); downgraded to "
            "WARNING, you choose whether to clean up the source text"
            if imported else "")
    sev = "warn_soft" if imported else "error"

    def lev(msg):
        findings.append({"rule": "R05", "severity": sev, "slide_idx": 0,
                         "message": msg + note})

    emoji_re = re.compile(
        r"[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF]")
    if emoji_re.search(text):
        lev("emoji detected in slide text")
    if "!" in text or "！" in text:
        lev("exclamation '!' / '！' detected in slide text")
    if "…" in text or "..." in text:
        lev("ellipsis '…' / '...' detected in slide text")
    if "???" in text or "？？？" in text:
        lev("'???' detected in slide text")
    return findings


def audit_dom_balance_bytes(html):
    """R-DOM(err)— <body> 内 <div> 开/闭【over-close】平衡(extra </div>)。
    R-DOM invariant-3 的【源字节】实现(C1a parity 补漏):旧 audit_dom_integrity 有三条不变量,
    迁移只保留 1&2(slide-frame 嵌套 / 每帧恰一 .slide,都在 audits.js 渲染后 DOM 上跑);
    invariant-3 = 整 <body> <div> 开/闭平衡 —— 浏览器会自动补全标签,渲染后 DOM 永远平衡,DOM
    看不到 → 必须读源字节,且在 BOTH dom_rules 路径都跑(audits.js 那条 R-DOM 永远查不到)。

    与既有检查清晰分工、不重复:
      · R-DOC-INTEGRITY invariant-1 已抓【under-close】(div_opens > div_closes,即 .deck
        开了没闭 / mid-deck 截断),且仅对【有 .deck 的真 deck】;
      · 本规则只在【net over-close】(div_closes > div_opens,即多一个 </div>)时 emit R-DOM
        —— 这是 R-DOC-INTEGRITY 永不触发的方向(它只查 opens>closes),所以无双报;且对
        【有无 .deck 均查】(片段也能有杂散 </div>)。
    opt-out:body 含 `allow:dom-integrity`(与旧 audit_dom_integrity 同 opt-out 串)。"""
    findings = []
    body_m = re.search(r"<body[^>]*>(.*)</body>", html, re.S)
    if not body_m:
        return findings
    body = body_m.group(1)
    if "allow:dom-integrity" in body:
        return findings
    # 剥 comment/script/style(它们里的伪标签会污染计数;与旧 audit_dom_integrity 同序)。
    scan = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    scan = re.sub(r"<script[^>]*>.*?</script>", "", scan, flags=re.S | re.I)
    scan = re.sub(r"<style[^>]*>.*?</style>", "", scan, flags=re.S | re.I)
    div_opens = len(re.findall(r"<div\b", scan, re.I))
    div_closes = len(re.findall(r"</div\s*>", scan, re.I))
    # 只报 over-close(多 </div>);under-close 归 R-DOC-INTEGRITY,避免双报(见 docstring)。
    if div_closes > div_opens:
        delta = div_closes - div_opens
        findings.append({
            "rule": "R-DOM", "severity": "error", "slide_idx": 0,
            "message":
                f'div balance in <body>: {div_opens} opens vs {div_closes} '
                f'closes (−{delta}) — {delta} extra </div>. A stray closing tag '
                'closes the DOM tree prematurely / leaks across boundaries, so '
                'later content escapes its intended container in the browser. '
                'Locate the extra </div> — every regex/sed/manual edit is a '
                'prime suspect. Re-render via render-deck.py rather than '
                'hand-splicing the deck shell.',
        })
    return findings


def runner_no_browser_text_findings(html, scope=None):
    """NO-BROWSER source-text rules — run ONLY on the dom_rules=False path.
    These rule codes (R-KEY / R-ESC-HTML / R02 / R07 / R05) are ALSO emitted by
    audits.js on the rendered DOM (the --visual path), so they MUST NOT run when
    dom_rules=True or every finding would double-emit. run_unified_engine calls
    this ONLY on the no-Chromium branch (H1 restore). Order mirrors the old
    STATIC_AUDITS registration (cosmetic). R-DOM div-balance is NOT here — it runs
    in BOTH paths via runner_source_byte_findings (the DOM rule can't cover it).

    `scope`(1-based 帧号集合 / None=全 deck)只作用于【逐帧 per-slide】规则
    (R02 / R07 / R-ESC-HTML) —— 与 audits.js driver(`scopeSet.has(slide_idx)`)对齐,
    使 `--no-visual --scope-frames N` 与 `--visual --scope-frames N` 给出一致 findings
    (否则 no-Chromium 路径会漏报 off-scope 帧的旧问题、阻断 scoped 编辑)。R05 / R-KEY 是
    【deck 级】规则(整 deck 求值,等同它们 audits.js 里 isFirstInScope 的 deck-level 孪生),
    故 scope-independent、不传 scope —— 与 R05/R-KEY 的 audits.js 行为一致。"""
    out = []
    out.extend(audit_structure_bytes(html, scope))    # R02 / R07 (per-slide → scoped)
    out.extend(audit_copy_bytes(html))                # R05 (deck-level → unscoped)
    out.extend(audit_slide_keys_bytes(html))          # R-KEY (deck-level → unscoped)
    out.extend(audit_escaped_html_bytes(html, scope)) # R-ESC-HTML (per-slide → scoped)
    return out


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


def audit_baked_runtime_dom_bytes(html):
    """R-BAKED-DOM(err)— 检出"运行后被二次保存的活 DOM"(serialized post-JS DOM)。

    render-deck.py 的干净产物里这些痕迹**永远不出现**:它们全是 feishu-deck.js 在浏览器
    运行时才写进 DOM 的。一旦出现,说明这份 HTML 是页面跑起来后被「另存 / 烤死」的快照
    (e.g. 浏览器另存、edit-mode 保存态),而不是渲染器的输出。把它当成 index.html 发布会
    导致加载时 JS 二次 init:buildUI 再造一个默认 `01 / 01` 的 `.deck-ui` 叠上去 → 页码定格在
    1、UI 重复、reveal 动画错乱。翻页还能用(handler 绑在真实 .slide-frame 上)所以容易漏判。

    指纹(任一命中即 err):
      · `data-idx="…"`            —— JS 给每个 .slide-frame 写的运行时序号(render 产物无)
      · `class="deck-ui"`         —— buildUI() 运行时 createElement+append 的覆盖层(render 产物无)
      · `.deck` 上 data-js-ready / data-nav-armed / data-edit-paste-guard —— 运行时标志

    修法:从 deck.json 重新 `render-deck.py` 出干净 index.html 再发布,别发这份烤死版。
    （与 Mira case-b 手搓 index.html 同源:任何绕过渲染器的 HTML 都该被这道闸拦住。）"""
    findings = []
    hits = []
    if re.search(r'<[^>]*\bdata-idx="', html):
        hits.append("data-idx=（运行时 .slide-frame 序号）")
    if re.search(r'class="[^"]*\bdeck-ui\b', html):
        hits.append('class="deck-ui"（运行时 buildUI 覆盖层）')
    deck_open = re.search(r'<div[^>]*\bclass="[^"]*\bdeck\b[^"]*"[^>]*>', html)
    if deck_open and re.search(r'data-(js-ready|nav-armed|edit-paste-guard)',
                               deck_open.group(0)):
        hits.append(".deck 带运行时标志(data-js-ready/nav-armed/edit-paste-guard)")
    if hits:
        findings.append({
            "rule": "R-BAKED-DOM", "severity": "error", "slide_idx": 0,
            "message":
                "serialized post-JS DOM detected — this index.html is a saved/"
                "“baked” live DOM, not a render-deck.py output. "
                "Signals: " + "；".join(hits) + "。"
                "Publishing it double-inits the deck JS (duplicate .deck-ui, page "
                "counter frozen at 1). Re-render from deck.json with render-deck.py "
                "and publish that clean file instead.",
        })
    return findings


# R-PROVENANCE 工具(F-266)。逐字对应 render-deck.py 的盖章常量,跨进程对齐。
_PROVENANCE_HASH_LEN = 12
_PROV_GENERATOR_RE = re.compile(
    r'<meta\s+name=["\']fs-deck-generator["\']\s+content=["\']([^"\']*)["\']', re.I)
_PROV_HASH_RE = re.compile(
    r'<meta\s+name=["\']fs-deck-hash["\']\s+content=["\']([^"\']*)["\']', re.I)


def _index_under_runs(path):
    """True iff `path` (the index.html being audited) lives under a runs/ tree.

    Name-free path signal: ANY ancestor directory named `runs`. This scopes
    R-PROVENANCE to real delivery renders — /tmp smoke tests, tests/ temp
    renders and standalone HTML outside runs/ are exempt (never reported). Mirror
    of the spirit of render-deck's `_is_runs_output`, kept liberal here (any runs/
    ancestor) because R-PROVENANCE's other gate — a SIBLING deck.json must exist —
    is the real precondition; together they exempt everything that isn't a
    deck.json-backed deck under runs/."""
    parts = {p.name for p in [path, *path.parents]}
    return "runs" in parts


def _deck_json_hash_for(base_dir):
    """sha256 of the sibling deck.json FILE CONTENT (first _PROVENANCE_HASH_LEN
    hex chars), or None if no readable deck.json next to index.html. Byte-for-byte
    the same computation render-deck.py stamps with (deck_json_hash), so a clean
    re-render always matches."""
    dj = (base_dir / "deck.json")
    try:
        data = dj.read_bytes()
    except Exception:  # noqa: BLE001 — missing/unreadable → caller treats as absent
        return None
    return hashlib.sha256(data).hexdigest()[:_PROVENANCE_HASH_LEN]


def audit_provenance_bytes(html, base_dir):
    """R-PROVENANCE(warn / error · F-266)— Gate 1「必走 render-deck.py」的模型无关强制。

    render-deck.py 给每份产物的 <head> 盖两枚章:
      · <meta name="fs-deck-generator" content="render-deck">  —— 出身证明
      · <meta name="fs-deck-hash" content="<H>">               —— H = sha256(deck.json 文件内容)[:12]
    H 基于【deck.json 文件内容】而非 index.html —— 这是规避误报的核心:渲染后改写
    (inline-assets / copy-assets / explode-assets 只动 index.html、不动 deck.json)
    不会让 H 失配(deck.json 没变 → H 没变)。只有「改了 deck.json 没重渲」或「手改
    index.html(deck.json 仍是旧的)」才会失配 —— 那才是真漂移,该挡。

    仅在【index.html 在 runs/ 路径下 且 同目录有 deck.json】时才查;/tmp 测试、无
    deck.json 的独立 HTML、imported 片段等一律豁免(不报)。这是模型无关的仓库层强制:
    Codex/云环境装不了 CC hook,这条 byte 规则在两条校验路径(--visual / --no-visual)
    都跑,补上 hook 缺位的那一半。

    三档(与 SKILL.md 三道硬闸 / --strict 提升机制对齐):
      · 无 fs-deck-generator 章 → warn:存量旧 deck(改造前渲染的)本就没章,无辜,
        重渲一次即盖章 —— 不硬挡。warn 在 --strict / 入库门(--gate ingest)会被统一
        提升为 error(validate.py / check-only 末尾把 iss.warnings 升 iss.errors),
        满足「入库门无章升 error」而日常 render 只 warn。
      · 有章但 fs-deck-hash ≠ 当前同目录 deck.json 的 sha256[:12] → error:真漂移,挡。
    返回统一 findings。"""
    findings = []
    # 仅查 runs/ 下、且有 sibling deck.json 的真交付 deck;其余全豁免(测试 / 独立 HTML / imported)。
    if not _index_under_runs(base_dir):
        return findings
    cur_hash = _deck_json_hash_for(base_dir)
    if cur_hash is None:
        return findings   # 无 sibling deck.json → 豁免(独立 HTML / imported,非 deck.json-backed)

    gen_m = _PROV_GENERATOR_RE.search(html)
    if not gen_m:
        findings.append({
            "rule": "R-PROVENANCE", "severity": "warn", "slide_idx": 0,
            "message":
                "无 provenance 章(疑似手搓 index.html 或改造前的旧 deck);重渲一次即盖章。"
                "这份 index.html 的 <head> 缺 `<meta name=\"fs-deck-generator\" "
                "content=\"render-deck\">` —— 它要么是绕过渲染器手搓/手补的(Path B 偷渡:"
                "deck.json↔index.html 会漂移,后续 lift/翻译/再渲染会炸),要么是 F-266 "
                "改造前渲染的旧 deck(无辜)。修法:从同目录 deck.json 跑 "
                "`render-deck.py <deck.json> <dir>/` 重渲一次,渲染器会盖章。"
                "[warn · --strict / 入库门(--gate ingest)会升为 error]",
        })
        return findings

    hash_m = _PROV_HASH_RE.search(html)
    stamped_hash = hash_m.group(1) if hash_m else ""
    if stamped_hash != cur_hash:
        findings.append({
            "rule": "R-PROVENANCE", "severity": "error", "slide_idx": 0,
            "message":
                f"provenance 章失配 —— index.html 的 fs-deck-hash=\"{stamped_hash or '(缺)'}\" "
                f"≠ 当前同目录 deck.json 的 sha256[:12]=\"{cur_hash}\"。这是真漂移:要么改了 "
                "deck.json 却没重渲(index.html 还是旧内容),要么手改了 index.html(deck.json "
                "仍是旧的)。任一种,交付的 index.html 都与它的 deck.json 不一致 —— 后续 lift/"
                "翻译/再渲染会以 deck.json 为准、产出与现在所见不同的结果。修法:从 deck.json 跑 "
                "`render-deck.py <deck.json> <dir>/` 重渲,让 index.html 与 deck.json 重新对齐;"
                "若 index.html 的手改是有意保留的,把那次改动写回 deck.json(custom_css / raw "
                "data.html)再重渲。",
        })
    return findings


def runner_source_byte_findings(html, base_dir):
    """跑【两条路径都要】的 runner 层源字节/文件系统检查,合并成统一 findings(同 schema)。
    与 audits.js 规则同列表、同字段 → 报告层无需区分来源。顺序:R-DOC-INTEGRITY →
    R-BAKED-DOM → R-DOM(div over-close balance)→ R-SELF-CONTAINED → R-PROVENANCE →
    perf(纯 cosmetic)。R-PROVENANCE(F-266)是【条件】byte 规则:只在 index.html 在
    runs/ 下且同目录有 deck.json 时才查(其余豁免),验 render-deck 盖的出身章 + deck.json
    哈希;它在两条路径都跑,补 CC hook 在非 CC 环境的缺位(模型无关的 Gate-1 强制)。

    这些规则在 dom_rules True/False 两条路径都跑:它们读的是浏览器看不到忠实结果的源字节
    (截断 / 多余 </div> / head <style> 泄漏 / 体积预算),与渲染后 DOM 无关、不会与 audits.js
    双报(audits.js 不发这些 code,或发的是不同方向:R-DOM 那条在 audits.js 是 slide-frame
    嵌套/每帧恰一 .slide 的 DOM 结构,与本处 over-close div 平衡分工互补)。

    `html` = 原始 index.html 字节(R-DOC-INTEGRITY 必须读 raw 抓截断;R-SELF-CONTAINED
    在 raw 上框架是 <link> 天然排除 = 与 Python 等价)。perf 在【内联框架后】文本上跑,
    与 validate.py(run_static_audits 前已 inline_linked)同源,零漂移。

    注:NO-BROWSER 源文本规则(R-KEY / R-ESC-HTML / R02 / R07 / R05)不在此 —— 它们与
    audits.js 重叠,只在 dom_rules=False 路径单独跑(见 runner_no_browser_text_findings)。"""
    out = []
    out.extend(audit_doc_integrity_bytes(html))
    out.extend(audit_baked_runtime_dom_bytes(html))   # R-BAKED-DOM:烤死的活 DOM(两路径都跑)
    out.extend(audit_dom_balance_bytes(html))   # R-DOM invariant-3:over-close(两路径都跑)
    out.extend(audit_self_contained_bytes(html))
    out.extend(audit_provenance_bytes(html, base_dir))  # R-PROVENANCE:Gate-1 盖章(F-266,两路径都跑;runs/+sibling deck.json 才查)
    out.extend(audit_perf_bytes(_inline_linked_text(html, base_dir)))
    return out


class EngineUnavailable(Exception):
    """Raised when the unified engine cannot run (playwright missing or render
    failed). Carries an exit-2 'environment' meaning, distinct from a deck
    defect. validate.py catches this to degrade / hard-prompt as appropriate."""


def run_unified_engine(html_path, scope=None, *, settle_ms=350,
                       dom_rules=True):
    """Run the unified engine against ONE rendered deck and return the merged
    result dict {engine, version, rules:[...], scope, slides_total, findings:[...]}.

    This is the SINGLE shared entry both run-audits.py's CLI and validate.py
    call — so the unified engine is sourced from exactly one place (no second
    rule path). Findings carry the canonical schema
    {rule, severity, slide_idx, message, ...payload}.

    Composition:
      · DOM/geometry rules (audits.js) — need a headless browser. Run when
        `dom_rules=True` (the default / `--visual` path).
      · runner-level SOURCE-BYTE / file-system checks ALWAYS run on BOTH paths
        (read raw index.html bytes, NO browser): R-DOC-INTEGRITY (truncation),
        R-DOM div over-close balance, R-SELF-CONTAINED (head/deck <style> leak),
        perf P50-P55. These are things the browser auto-repairs so the rendered
        DOM can't see faithfully — see runner_source_byte_findings.
      · NO-BROWSER source-text rules (R-KEY / R-ESC-HTML / R02 / R07 / R05) run
        ONLY on the dom_rules=False path (H1 restore). On dom_rules=True the SAME
        rule codes are evaluated by audits.js against the rendered DOM, so the
        byte versions stay silent there to avoid double-emit — see
        runner_no_browser_text_findings.

    `dom_rules=False` is the `--no-visual` / no-Chromium path: skip the browser
    entirely, return the runner byte/source findings PLUS the no-browser
    source-text rules (R-KEY / R-ESC-HTML / R02 / R07 / R05) so the default gate +
    write-hook regain real static enforcement without Chromium. Geometry / pure
    DOM-text rules (R-VIS-*, R06/R20/R10/R-OVERFLOW/… and the audits.js R-DOM
    nesting invariants) are NOT evaluated in that mode — they require a rendered
    DOM (see UNIFY-VALIDATE-ARCH §1). Callers must surface this so it is never a
    silent half-check.

    Raises EngineUnavailable when dom_rules=True but playwright is missing or
    the render/eval fails — the caller decides whether that is fatal (run-audits
    CLI: hard exit 2) or a degrade-to-byte-only advisory (validate.py)."""
    html_path = Path(html_path)
    if not AUDITS_JS.is_file():
        raise EngineUnavailable(f"规则源缺失 {AUDITS_JS}")

    # ── runner 层源字节检查读【原始 index.html 字节】(浏览器自动闭合标签会抹掉截断信号,
    #    DOM 看不到 —— R-DOC-INTEGRITY 等【必须】读字节,见上方函数注释 / UNIFY-VALIDATE §0)。
    raw_html = html_path.read_text(encoding="utf-8", errors="replace")
    runner_findings = runner_source_byte_findings(raw_html, html_path.parent)
    runner_rules = []
    for f in runner_findings:
        if f["rule"] not in runner_rules:
            runner_rules.append(f["rule"])

    if not dom_rules:
        # NO-CHROMIUM path: byte/source rules + the no-browser source-text rules
        # (R-KEY / R-ESC-HTML / R02 / R07 / R05). The latter run ONLY here (H1
        # restore) — on the --visual path audits.js owns the same codes against
        # the rendered DOM, so running them here too would double-emit. Stable
        # result shape so the caller maps it uniformly with the full-engine path.
        # Thread `scope` so the PER-SLIDE byte rules (R02/R07/R-ESC-HTML) skip
        # off-scope frames exactly like the audits.js driver does on the --visual
        # path — keeping `--no-visual --scope-frames N` consistent with --visual.
        scope_set = set(scope) if scope else None
        text_findings = runner_no_browser_text_findings(raw_html, scope_set)
        all_findings = runner_findings + text_findings
        rules = list(runner_rules)
        for f in text_findings:
            if f["rule"] not in rules:
                rules.append(f["rule"])
        return {
            "engine": "audits.js",
            "version": None,
            "rules": rules,
            "scope": list(scope) if scope else None,
            "slides_total": None,
            "findings": all_findings,
            "dom_rules": False,
        }

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise EngineUnavailable(
            "统一校验引擎需要 playwright/chromium —— 这是硬依赖,绝不静默放行。\n"
            "  几何类规则(R-VIS-CANVAS-CENTER 等)必须在渲染后 DOM 上判定,静态解析做不到。\n"
            "  安装:pip install playwright && python -m playwright install chromium"
        ) from e

    audits_src = AUDITS_JS.read_text(encoding="utf-8")
    url = html_path.resolve().as_uri()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            # Bounded settle (B/2026-06-06): an embedded live demo can keep the
            # 'load' event pending ~30s, taxing every audit run. Prefer full load
            # for fidelity but cap it, then await fonts. This deck: ~31s → ~1-5s.
            try:
                page.wait_for_load_state("load", timeout=4_000)
            except Exception:
                pass
            try:
                page.evaluate("() => Promise.race([(document.fonts && document.fonts.ready) || Promise.resolve(), new Promise(r => setTimeout(r, 2000))])")
            except Exception:
                pass
            # Wait for framework init (feishu-deck.js sets data-js-ready on .deck).
            # domcontentloaded can return before layout JS runs → un-laid-out DOM.
            try:
                page.wait_for_function("() => document.querySelector('.deck[data-js-ready]')", timeout=5_000)
            except Exception:
                pass
            # Await <img> decode (bounded). A still-loading <img> contributes its
            # intrinsic (natural) height to layout, so a `height:100%` image inside
            # an overflow:hidden media box can transiently measure FAR taller than
            # its container → false R-VIS-CARD-OVERFLOW (content-clip). Decoding makes
            # every image layout-definite before geometry is measured. `img.complete`
            # short-circuits the already-loaded common case to a no-op (zero baseline
            # drift); the 2s race caps a slow/broken asset so it can't hang the gate.
            try:
                page.evaluate(
                    "() => Promise.race(["
                    "Promise.all([...document.images].map(i => "
                    "(i.complete && i.naturalWidth) ? Promise.resolve() "
                    ": (i.decode ? i.decode().catch(() => {}) : Promise.resolve()))),"
                    "new Promise(r => setTimeout(r, 2000))])"
                )
            except Exception:
                pass
            page.wait_for_timeout(settle_ms)  # 让 scale-to-fit / 布局稳定
            # ── 把链接的【框架 CSS】源文本注入成 <style data-source="framework"> ──
            # R-CSSVAR 要读"所有 CSS 源文本"判定 var(--x) 定义/引用,而 file:// 下外链
            # 样式表的 cssRules 被 CORS 挡、且浏览器会丢掉含未定义 var() 的整条声明(正是
            # 本规则要抓的东西)→ CSSOM 读不到。runner(load 层)做这件事:读盘 → 注入文本,
            # 纯"让源可读",不含规则逻辑。
            _inline_framework_css(page, html_path.parent)
            # ── 把链接的【框架 JS】源文本注入成 <script data-source="framework"
            #    type="text/plain"> ── R29-32 要读 JS 源判 requestFullscreen 等
            #    needle;外链脚本已执行(DOM needle 是真元素),这里只补源可读(不二次执行)。
            _inline_framework_js(page, html_path.parent)
            # ── 把页面切到 present 模式 ── 每帧拿整块 1920×1080 画布,几何规则(R-OVERFLOW
            #    /canvas-center 等)才量得准(scroll 模式会误报)。镜像旧 run_visual_audits。
            page.evaluate("""
                () => {
                    const deck = document.querySelector('.deck');
                    if (deck) deck.setAttribute('data-mode', 'present');
                }
            """)
            page.wait_for_timeout(200)  # 让 present 布局再稳定一次
            # ── 把旁边的 deck.json(若存在)注入 window.__DECK_JSON__ ──
            # R-LAYOUT-DEPRECATED 的 SOURCE-OF-TRUTH 是 deck.json 的真 authored layout
            # (渲染后 data-layout 会伪装借框架 CSS,不可信)。纯文件读,不含规则逻辑。
            deck_json = _load_deck_json(html_path.parent)
            page.evaluate("(dj) => { window.__DECK_JSON__ = dj; }", deck_json)
            page.evaluate("(s) => { window.__AUDIT_SCOPE__ = s; }", scope)
            result = page.evaluate(audits_src)
            browser.close()
    except EngineUnavailable:
        raise
    except Exception as e:  # noqa: BLE001 — render/eval 失败 = 环境故障,非 deck 缺陷
        raise EngineUnavailable(f"渲染/求值失败:{e}") from e

    # ── 合并 runner 层源字节/文件系统检查(R-DOC-INTEGRITY / R-SELF-CONTAINED / perf)。
    #    这些是整文档级(slide_idx=0),与 scope 无关、始终对整份源跑;emit 进【同一】 findings
    #    列表、同 schema,报告层不区分来源。runner 检查的规则名也并入 result['rules'](去重、保序)。
    findings = list(result.get("findings", [])) + runner_findings
    result["findings"] = findings
    rules = list(result.get("rules", []))
    for r in runner_rules:
        if r not in rules:
            rules.append(r)
    result["rules"] = rules
    result["dom_rules"] = True
    return result


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

    try:
        scope = parse_scope(args.slide)
    except ValueError as e:
        print(f"ERROR: --slide {args.slide!r}: {e}", file=sys.stderr)
        sys.exit(2)
    try:
        result = run_unified_engine(args.html, scope, settle_ms=args.settle_ms)
    except EngineUnavailable as e:
        print(
            f"ERROR: {e}\n"
            "  (若确需仅静态档,显式跑 `validate.py --no-visual`,但 R-VIS-* 几何规则不会被执行。)",
            file=sys.stderr,
        )
        sys.exit(2)

    findings = result.get("findings", [])

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
