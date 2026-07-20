#!/usr/bin/env python3
"""feishu-deck-h5 · 纯检查模式 (check-only)

用法场景: 别人给你一份做好的 HTML deck, 你只想知道哪些地方不合规 ——
跳过 PREFLIGHT / new-run / asset-copy / sidecar 生成的整套生成流程,
直接对单文件跑全套 validate.py 审计, 产出 markdown 报告.

四个模式:

  默认模式 — `bash check-only.sh deck.html`  ← 标准输出, 所有人一致
    逐页业务报告: 从第 1 页到第 N 页全部列出 (干净页标 ✅), 用业务语言
    区分 🔴错误 / 🟡提醒, 同页同类问题合并计数, 末尾给"最该先看哪几页".
    业务文案取自 business-rules.yaml (非工程师可直接改措辞).
    实现 = build_per_page_report().

  工程师视图 — `bash check-only.sh deck.html --by-rule`
    按 family (结构/排版/品牌/...) 分组列违规, 标注 context-dependent 规则.
    排查 framework bug / 改 validator 时用. 实现 = build_default_report().

  入库门禁 — `bash check-only.sh deck.html --gate ingest`
    只看 业务必修规则 (业务关切 A/B/C 三类), 全部 warn 升 error.
    用 business-rules.yaml 把每条违规渲染成业务语言: 业务症状 / 不修后果 /
    具体修改步骤 + 技术代码做小字附注.
    适合用户主动要求的严格业务/视觉评审.

  资源准入 — `bash check-only.sh deck.zip --resource-only`
    只检查入库包结构、入口 HTML、运行时本地引用和
    assets-manifest.yaml 的素材可达性. 不跑视觉、排版或跨页一致性规则.
    这是 slide-library 入库链路的默认门禁; `--gate ingest` 保留给显式的
    严格业务/视觉评审.
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import importlib.util
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate as V


HTML_SUFFIXES = {'.html', '.htm'}
ZIP_HARD_REQUIRED = (
    'index.html',
    'deck.json',
    'assets',
    'assets-manifest.yaml',
    'ingestion-manifest.json',
)
ZIP_SOFT_REQUIRED = (
    'outline.json',
    'DESIGN-PLAN.md',
    'texts.md',
    'README.md',
)
REMOTE_REF_SCHEMES = {'http', 'https', 'data', 'blob', 'mailto', 'tel', 'javascript'}
LOCAL_PATH_SCHEMES = {'file'}
REFERENCE_ATTRS = ('src', 'href', 'poster', 'data-src', 'data-original', 'xlink:href')
ATTR_REF_RE = re.compile(
    r'''(?P<attr>src|href|poster|data-src|data-original|xlink:href)\s*=\s*(?P<q>["'])(?P<value>.*?)(?P=q)''',
    re.I | re.S,
)
CSS_URL_RE = re.compile(r'''url\(\s*(?:"([^"]*)"|'([^']*)'|([^)]*?))\s*\)''', re.I | re.S)
STYLE_BLOCK_RE = re.compile(r'<style\b[^>]*>(.*?)</style>', re.I | re.S)
LINK_TAG_RE = re.compile(r'<link\b[^>]*>', re.I | re.S)
META_REFRESH_RE = re.compile(
    r'''<meta\b[^>]*http-equiv\s*=\s*["']?refresh["']?[^>]*content\s*=\s*["'][^"']*?\burl\s*=\s*([^"';>]+)[^"']*["']''',
    re.I | re.S,
)
JS_LOCATION_RE = re.compile(
    r'''(?:window\.)?location(?:\.href)?\s*=\s*["']([^"']+)["']''',
    re.I,
)


def load_ingest_asset_closure():
    module_path = Path(__file__).resolve().parent / 'ingest-asset-closure.py'
    spec = importlib.util.spec_from_file_location('feishu_deck_ingest_asset_closure', module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load runtime asset closure validator: {module_path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


INGEST_ASSET_CLOSURE = load_ingest_asset_closure()


# ---------------------------------------------------------------------------
#  默认模式: family 分组 + context-dependent 标注
# ---------------------------------------------------------------------------

FAMILIES = [
    ('结构 / DOM',           ['R02', 'R07', 'R-DOM', 'R-DOC-INTEGRITY', 'R-BAKED-DOM',
                              'R-PROVENANCE', 'R-CANVAS']),
    ('安全 / 注入面',        ['R-FOREIGN-SCRIPT']),
    ('排版 / 文案',          ['R05', 'R06', 'R13', 'R20', 'R56',
                              'R-VIS-SUBTITLE-CANON',
                              'R-WHITE-TEXT', 'R-HIERARCHY', 'R-ECHO',
                              'R-BULLET-DASH', 'R-ESC-HTML']),
    ('品牌 / 调色板',        ['L1', 'R10', 'R12', 'R38', 'R49', 'R-LANG']),
    ('布局完整性',           ['L2', 'L4', 'R36', 'R47', 'R48', 'R-CSSVAR',
                              'R-EMPTY-HEADER-ZONE', 'R-VIS-LIFT-STYLE-LOST',
                              'R-LIFT-CSS-BUDGET',
                              'R-CSS-INLINE-BUDGET', 'R-CSS-CROSS-PAGE',
                              'R-SELF-CONTAINED', 'R-LOCAL-ASSET-REF',
                              'R-AUTOBALANCE-PRESENT',
                              'R-LAYOUT-DEPRECATED', 'R-IFRAME-REMOTE',
                              'R-DEMO-IFRAME', 'R-EMBED-OPAQUE-BG']),
    ('UI 仿真 / slide-key',  ['UI1', 'R-KEY']),
    ('演示模式 / 运行时',    ['R29-32']),
    ('性能预算',             ['P50', 'P51', 'P52', 'P53', 'P54', 'P55']),
    ('视觉 (Playwright)',    ['R-OVERFLOW', 'R-OVERLAP', 'R-VIS-ABS-OVERLAP', 'R-VIS-TIER', 'R-VIS-HIER',
                              'R-VIS-LABEL-FLOOR', 'R-VIS-BODY-FLOOR', 'R-VIS-DIM-TEXT',
                              'R-VIS-ABSPOS-DUAL-ANCHOR',
                              'R-VIS-CARD-OVERFLOW', 'R-VIS-OPT-OUT-ABUSE',
                              'R-VIS-TITLE-POSITION', 'R-VIS-ORPHAN', 'R-VISUAL',
                              'R-VIS-NO-IMAGERY', 'R-FOCAL-CHECK', 'R-VIS-BALANCE',
                              'R-VIS-CARD-MIN-HEIGHT-SPARSE', 'R-VIS-SLACK-FLEX',
                              'R-VIS-CROWD', 'R-VIS-PANEL-TOP', 'R-VIS-TITLE-GAP', 'R-VIS-PEER-SIZE',
                              'R-VIS-GUTTER', 'R-VIS-HERO-FLOOR',
                              'R-VIS-SHORT-LABEL-FLOOR', 'R-VIS-SVG-TEXT-FLOOR',
                              'R-VIS-CANVAS-CENTER',
                              'R-VIS-BAND-COLLIDE', 'R-VIS-DEAD-ANIM', 'R-VIS-DEAD-RULE',
                              'R-VIS-FILL', 'R-VIS-RAW-TITLE-POS', 'R-VIS-RAW-TITLE-STACK',
                              'R-VIS-CONTRAST-WCAG']),
    ('跨页一致性',           ['R-DECK-TITLE-DRIFT', 'R-DECK-PALETTE-DRIFT',
                              'R-DECK-TYPESCALE-BUDGET', 'R-FAMILY-DRIFT',
                              'R-DECK-EYEBROW-BUDGET', 'R-DECK-RADIUS-DRIFT']),
]

CONTEXT_NOTES = {
    'P50':        '只在你打算用 inline 单文件交付时才相关; linked 模式的 '
                  'deck 这条只是参考.',
    'UI1':        '如果 deck 是 Replica-mode (PDF 截图 + .page-replica), '
                  '所有 <img> 都会触发, 但这是设计如此.',
    'R29-32':     '如果 deck 是 Replica-mode 或纯阅读型 HTML (不需要 '
                  'present-mode), 可不必满足.',
    'R-SELF-CONTAINED': '老 deck 把每页 CSS 放在 head <style> 里很常见; 这条只是 '
                        '提醒「该页 CSS 没跟着 slide 走, lift/republish 会丢」. '
                        '非阻塞 (warn_soft); 迁到 deck.json 的 custom_css 即可消除.',
    'R-LOCAL-ASSET-REF': '本地 deck 的运行时静态资源必须落在 assets/ 或 input/ 并用相对 '
                         '路径引用. http(s) / file:// / 本机绝对路径会让冷启动等待网络、离线 '
                         '失效且不可移植,因此在 DeckJSON 生成前门禁与最终 HTML 兜底都硬拦.',
    'R-FOREIGN-SCRIPT': '注入面最低防线: 非框架来源的 <script> / on* 内联事件. 严重度按来源 '
                        '分级 —— lifted/imported 页 = error(外来脚本经入库会跨 deck 传染、'
                        '发布到带飞书登录的 CF viewer = XSS), 普通生成页 = warn. 框架自注入脚本 '
                        '(data-source=framework / framework src / 非可执行 type)与 body 级脚本 '
                        '豁免; 确属故意写脚本的 bespoke raw 页用 data-allow-foreign-script opt-out.',
    'R-PROVENANCE': 'Gate-1「必走 render-deck.py」的模型无关强制 (F-266). 只在 runs/ 下 '
                    '且同目录有 deck.json 的真交付 deck 上查 (/tmp 测试 / 独立 HTML / '
                    'imported 豁免). 无 render-deck 出身章 = warn (改造前的旧 deck 无辜, '
                    '重渲一次即盖章; --strict / 入库门会升 error). 有章但 fs-deck-hash 与 '
                    '当前 deck.json 哈希失配 = error (真漂移: 改了 deck.json 没重渲, 或手改了 '
                    'index.html). 修法: 从 deck.json 跑 render-deck.py 重渲.',
    'R-LAYOUT-DEPRECATED': 'F-305 «raw unless ceremonial»: 正文 schema 版式 (content / '
                        'stats / flow / chart / table / arch-stack / image-text / '
                        'logo-wall, 含全部 variant) 已冻结 —— 仍为存量 deck 渲染, 但新页应走 '
                        'layout:"raw" (模型自由排版, 更丰富、各页更不同). 只有仪式页 '
                        '(cover/section/agenda/quote/end) 与机制页 (raw/canvas/iframe-embed/'
                        'replica) 留 schema. 非阻塞 (warn_soft, 连 --strict 也不升级); 真源 = '
                        'deck.json 的 authored layout (非渲染后 data-layout); imported / '
                        '无 deck.json 整体豁免. 2026-06-12 退役了反向的 R-RAW-LOOKS-SCHEMA.',
}


# ---------------------------------------------------------------------------
#  Gate ingest 模式: 业务规则字典
# ---------------------------------------------------------------------------

CONCERN_ORDER = [
    'A · 客户看不见',
    'B · 库找不回这张 slide',
    'C · 复用时会打架',
    'D · 放映功能不全',
    'E · 文件偏大可能卡顿',
]


def load_business_rules() -> dict:
    """从 business-rules.yaml 加载 业务必修规则的业务文案."""
    try:
        import yaml
    except ImportError:
        print('ERROR: --gate 模式需要 PyYAML. 装一下: pip install pyyaml',
              file=sys.stderr)
        sys.exit(2)
    yaml_path = Path(__file__).resolve().parent / 'business-rules.yaml'
    if not yaml_path.is_file():
        print(f'ERROR: 找不到业务规则字典 {yaml_path}', file=sys.stderr)
        sys.exit(2)
    return yaml.safe_load(yaml_path.read_text(encoding='utf-8'))


def enumerate_validate_rules() -> set:
    """Best-effort set of rule codes the validator can emit. Used to detect gate
    drift (F-18) and to drive the FAMILIES / business-rules coverage guards.

    UNIFY-VALIDATE-ARCH (step 4): the rendered-deck rule source is the unified
    engine. Codes come from FOUR places, scanned here:
      · assets/audits.js — the DOM/geometry/structure rules. Each finding carries
        a `rule: '<code>'` literal (NOTE the emitted code can differ from the
        rule's `id:` — e.g. the `R02-R07-STRUCTURE` rule emits `R02` and `R07`;
        the `L1/L2/L4` rule emits `L1`/`L2`/`L4` — so we scan the EMITTED
        `rule:` literals, not the `id:` declarations).
      · assets/run-audits.py — the runner-level source-byte / file-system checks
        (R-DOC-INTEGRITY via `DOC = "…"`, R-SELF-CONTAINED via a `"rule": "…"`
        literal, perf P50–P55 via `warn("P5x", …)` / the PERF_* constants).
      · assets/validate.py — the CLI/adapter layer's own advisory `R-VISUAL`
        (engine-unavailable degrade), emitted via `iss.warn_soft('R-VISUAL', …)`.
      · deck-json/validate-deck.py — the deck.json-side SCHEMA + business
        validator (wired into deck-cli lint, render-deck, conform, repair). It
        emits its codes as a free-text `(CODE)` parenthetical inside the message
        (R-CANVAS / R-FAMILY-DRIFT / R-DEMO-IFRAME are UNIQUE to it; R-KEY /
        R-LANG / R49 overlap the engine), so we scan that convention (contract-1).
        Without this surface those three codes escaped the FAMILIES / yaml /
        validator-rules.md coverage guards entirely.
    The OLD _validate_audits.py / visual-audit.js dual registries were retired;
    they are no longer scanned (and no longer exist).
    """
    here = Path(__file__).resolve().parent
    codes: set[str] = set()

    # 1) audits.js — emitted `rule: '<code>'` literals (single + double quote).
    try:
        js = here.joinpath('audits.js').read_text(encoding='utf-8')
        codes |= set(re.findall(r"\brule:\s*['\"]([A-Za-z0-9][\w-]*)['\"]", js))
    except OSError:
        pass

    # 2) run-audits.py — runner byte/source rules. Catch all the emit idioms:
    #    `"rule": "X"`, the `DOC = "R-DOC-INTEGRITY"` alias, and `warn("P5x", …)`.
    try:
        runner = here.joinpath('run-audits.py').read_text(encoding='utf-8')
        codes |= set(re.findall(r'"rule":\s*"([A-Za-z0-9][\w-]*)"', runner))
        codes |= set(re.findall(r'\bDOC\s*=\s*"([A-Za-z0-9][\w-]*)"', runner))
        codes |= set(re.findall(r'\bwarn\(\s*"([A-Za-z0-9][\w-]*)"', runner))
        codes |= set(re.findall(r'\bfindings\.append\(\{\s*"rule":\s*"([A-Za-z0-9][\w-]*)"', runner))
    except OSError:
        pass

    # 3) validate.py — the adapter layer's own emits (R-VISUAL degrade advisory),
    #    via iss.err/warn/warn_soft or the local lev/_lev aliases.
    try:
        vp = here.joinpath('validate.py').read_text(encoding='utf-8')
        codes |= set(re.findall(
            r"(?:iss\.(?:err|warn|warn_soft)|_?lev)\(\s*['\"]([A-Za-z0-9][\w-]*)['\"]",
            vp))
    except OSError:
        pass

    # 4) deck-json/validate-deck.py — the deck.json-side schema+business validator
    #    (contract-1). It carries the rule code as a free-text `(CODE)` suffix
    #    inside each Result.err/warn/warn_soft message rather than a structured
    #    `rule=` field, so scan that parenthetical convention. Restrict to
    #    R-prefixed codes (R-…, R<num>) so ticket refs like `(F-300)` and stray
    #    `(HERE)` mentions are NOT mistaken for rule codes.
    try:
        vd = here.parent.joinpath('deck-json', 'validate-deck.py').read_text(encoding='utf-8')
        codes |= set(re.findall(r'\((R-[A-Z][A-Z0-9-]*|R\d+)\)', vd))
    except OSError:
        pass

    return codes


def warn_on_gate_rule_drift(yaml_rules, emitted_rules) -> None:
    """F-18: the ingest gate keeps only errors whose code is in
    business-rules.yaml. If a rule code is renamed in validate.py but the yaml
    isn't updated, that rule silently drops out of the gate (and it can exit 0).
    Surface the drift loudly instead of failing silently. Informational only —
    never blocks the gate. Skips quietly if validate.py couldn't be scanned."""
    if not emitted_rules:
        return
    orphaned = sorted(set(yaml_rules) - emitted_rules)
    if orphaned:
        print('⚠️  business-rules.yaml 含 validate.py 已不再发出的规则码: '
              f'{", ".join(orphaned)} —— 这些码永远不会触发入库门. '
              '可能是 validate.py 改名了规则码, 或 yaml 该更新了 (F-18).',
              file=sys.stderr)


def _extract_location(msg: str) -> str:
    """从技术 msg 里抽取定位信息. 返回 '· ' 分隔的简短串."""
    parts = []

    # 聚合型: "N slide(s) missing X" / "(slide indices: 1, 2, 3, ...)"
    m_agg = re.search(r'(\d+)\s+slide\(s\)', msg)
    m_idx = re.search(r'slide indices?:\s*([0-9,\s…]+)', msg)
    if m_agg:
        loc = f'{m_agg.group(1)} 张 slide'
        if m_idx:
            indices = m_idx.group(1).strip().rstrip(',').rstrip()
            loc += f' ({indices})'
        parts.append(loc)
    else:
        # 单 slide: "slide N (label)" 或 "slide N: ..."
        m = re.search(r'slide (\d+)(?:\s*\(([^)]+)\))?', msg)
        if m:
            parts.append(f'slide {m.group(1)}' +
                         (f' ({m.group(2)})' if m.group(2) else ''))

    # font-size Npx
    m = re.search(r'font-size (\d+(?:\.\d+)?)px', msg)
    if m:
        parts.append(f'字号 {m.group(1)}px')

    # CSS selector in backticks —— 但跳过明显是 fix-hint / 引用的反引号
    # (R-KEY 这类规则的报错里反引号包的是建议写法, 不是定位锚点)
    skip_selector = m_agg is not None  # 聚合型违规通常没有单个 selector
    if not skip_selector:
        for m in re.finditer(r'`([^`\n]{1,100})`', msg):
            val = m.group(1)
            # 跳过明显是建议示例的: 含 < > " ' 通常是 markup template
            if any(ch in val for ch in '<>"\''):
                continue
            parts.append(f'`{val}`')
            break

    return ' · '.join(parts) if parts else '(整份 deck)'


# ---------------------------------------------------------------------------
#  默认模式报告
# ---------------------------------------------------------------------------

def detect_mode_hints(html: str, slides_count: int) -> list[str]:
    hints = []
    if re.search(r'class="[^"]*\bpage-replica\b', html):
        hints.append('🎬 检测到 `.page-replica` —— 这是 Replica-mode '
                     '(PDF 截图入框), UI1 / T00 警告通常可忽略.')
    if re.search(r'<meta\s+name="fs-deck-mode"\s+content="inline"', html):
        hints.append('📦 检测到 `<meta name="fs-deck-mode" content="inline">` —— '
                     'P50 base64 预算审核按 inline 模式跑 (允许更大).')
    if re.search(r'<meta\s+name="fs-language"\s+content="zh-en"', html):
        hints.append('🌐 检测到 `<meta name="fs-language" content="zh-en">` —— '
                     '允许 .title-en / .subtitle-en bilingual class, R-LANG '
                     '审计相应放宽.')
    if slides_count == 0:
        hints.append('⚠️ 没有解析出任何 `.slide` —— 可能 DOM 结构不符合 '
                     '`.deck > .slide-frame > .slide` 约定, 或这根本不是 '
                     '一份 feishu-deck-h5 deck.')
    return hints


def _strip_pageno(label: str) -> str:
    """'03 目录' -> '目录' (去掉开头页码, 标题不重复)."""
    return re.sub(r'^\s*\d+\s*', '', str(label or '')).strip()


def _slides_of_msg(msg: str) -> list:
    """这条 finding 指向哪几页 (1-based). 聚合型展开为多页, 单页返回 [N],
    deck 级 (没有 slide 编号) 返回 []."""
    m_idx = re.search(r'slide indices?:\s*([0-9,\s]+)', msg)
    if m_idx:
        return [int(x) for x in re.findall(r'\d+', m_idx.group(1))]
    m = re.search(r'\bslide (\d+)\b', msg)
    return [int(m.group(1))] if m else []


def build_per_page_report(html_path: Path, slides_count: int, iss,
                          strict: bool, business_rules: dict, html: str) -> str:
    """标准报告 (默认输出) — 逐页 · 业务语言 · 区分 🔴错误 / 🟡提醒.

    所有人调 check-only 都得到这个格式, 体验一致. 不按技术规则家族
    (R06 / R-VIS-TIER…) 聚合 —— 那是工程师视图 (--by-rule). 业务文案
    取自 business-rules.yaml 的 symptom 字段; 没文案的 code 退回不含
    术语的兜底句, 绝不把规则代码抖给业务用户.
    """
    EMO = {'err': '🔴', 'warn': '🟡'}

    # 每页业务标签: data-screen-label 按文档顺序 (R02 保证每页都有)
    labels = re.findall(r'data-screen-label="([^"]*)"', html)
    n = slides_count or len(labels)

    findings = ([(c, m, 'err') for c, m in iss.errors]
                + [(c, m, 'warn') for c, m in iss.warnings]
                + [(c, m, 'warn') for c, m in iss.soft_warnings])

    by_slide: dict = {}
    deck_level: dict = {}
    for code, msg, sev in findings:
        idxs = _slides_of_msg(msg)
        buckets = [by_slide.setdefault(i, {}) for i in idxs] or [deck_level]
        for bucket in buckets:
            g = bucket.setdefault(code, {'sev': sev, 'n': 0})
            g['n'] += 1
            if sev == 'err':
                g['sev'] = 'err'

    def biz_line(code: str, g: dict) -> str:
        meta = business_rules.get(code) or {}
        sym = meta.get('symptom')
        cnt = f" (本页 {g['n']} 处)" if g['n'] > 1 else ''
        emo = EMO[g['sev']]
        if sym:
            line = f"- {emo} {sym}{cnt}"
            if g['sev'] == 'err' and meta.get('fix'):
                line += f"\n  → 怎么修: {meta['fix'][0]}"
            return line
        kind = '需要修正' if g['sev'] == 'err' else '可优化'
        return f"- {emo} 这一页有一处{kind}的细节{cnt}"

    def ordered(groups: dict) -> list:
        return sorted(groups.items(),
                      key=lambda kv: (0 if kv[1]['sev'] == 'err' else 1, kv[0]))

    n_err = len(iss.errors)
    n_warn = len(iss.warnings) + len(iss.soft_warnings)

    L = ['# 飞书 Deck 检查报告', '']
    L.append(f'- 文件: `{html_path}`')
    L.append(f'- 共 {n} 页')
    if n_err == 0 and n_warn == 0:
        L.append('- 结论: ✅ 全部通过, 没发现问题')
    else:
        parts = []
        if n_err:
            parts.append(f'🔴 {n_err} 处错误')
        if n_warn:
            parts.append(f'🟡 {n_warn} 处提醒')
        L.append('- 结论: ' + ' · '.join(parts))
    L += ['', '> 🔴 错误 = 投影上客户能看到的硬伤, 交付前建议修  ·  '
          '🟡 提醒 = 可优化的细节, 不挡交付', '']

    # 运行时防漂: 引擎有规则码但 yaml 没文案 → 该码触发时只能退兜底句.
    # 把它显式横幅出来 (而不是默默退化), 维护者一眼看到 yaml 该补.
    # 规则只有一套源 (引擎); 这里只是检查 yaml 文案清单是否跟上, 不复制规则.
    try:
        _missing = sorted(enumerate_validate_rules() - set(business_rules))
    except Exception:
        _missing = []
    if _missing:
        L.append(f'> ⚠️ 业务文案未覆盖 {len(_missing)} 条规则码, 命中时会显示为'
                 f'笼统兜底句 —— 维护者请在 business-rules.yaml 补: '
                 f'{" ".join(_missing)} (跑 `check-rule-coverage.py` 看详情)')
        L.append('')
    L += ['---', '']

    clean = []
    attention = []   # (idx, n_err, n_warn, label)
    for i in range(1, n + 1):
        label = _strip_pageno(labels[i - 1]) if i - 1 < len(labels) else ''
        L.append(f'## 第 {i} 页' + (f' · {label}' if label else ''))
        g = by_slide.get(i)
        if not g:
            L.append('✅ 没问题')
            clean.append(i)
        else:
            od = ordered(g)
            pe = sum(1 for _, x in od if x['sev'] == 'err')
            for code, gg in od:
                L.append(biz_line(code, gg))
            attention.append((i, pe, len(od) - pe, label))
        L.append('')

    if deck_level:
        L.append('## 整份文件 (不针对某一页)')
        for code, gg in ordered(deck_level):
            L.append(biz_line(code, gg))
        L.append('')

    L += ['---', '', '## 小结']
    if clean:
        L.append('- ✅ 干净的页: '
                 + '、'.join(f'第{p}页' for p in clean) + ' —— 不用管')
    attention.sort(key=lambda a: (-a[1], -a[2]))
    top = [a for a in attention if a[1] > 0][:3] or attention[:2]
    if top:
        refs = []
        for i, pe, pw, label in top:
            tag = []
            if pe:
                tag.append(f'{pe}错')
            if pw:
                tag.append(f'{pw}提醒')
            refs.append(f'第{i}页' + (('·' + label) if label else '')
                        + f'({"/".join(tag)})')
        L.append('- 🎯 最该先看: ' + ' 、 '.join(refs))
    return '\n'.join(L)


def build_default_report(html_path: Path, slides_count: int, iss,
                          strict: bool, mode_hints: list[str]) -> str:
    lines = []
    lines.append('# feishu-deck-h5 合规检查报告')
    lines.append('')
    lines.append(f'- **目标**: `{html_path}`')
    lines.append(f'- **Slide 数**: {slides_count}')
    lines.append(f'- **模式**: '
                 f'{"strict (warn 升级为 error)" if strict else "default (warn 不阻塞)"}')
    lines.append(f'- **总计**: ✗ error {len(iss.errors)} 条 ｜ '
                 f'! warn {len(iss.warnings)} 条')
    lines.append('')

    if mode_hints:
        lines.append('## 自动检测到的上下文')
        lines.append('')
        for h in mode_hints:
            lines.append(f'- {h}')
        lines.append('')

    if not iss.errors and not iss.warnings:
        lines.append('## ✅ PASS —— 所有可编程规则通过')
        lines.append('')
        lines.append('> 视觉对齐 / 字体看感 / 故事节奏需要人眼看 deck 才能判断,')
        lines.append('> 不在本报告范围. 跑 `--visual` 可加 Playwright 视觉审计.')
        return '\n'.join(lines)

    err_by_code: dict[str, list[str]] = {}
    warn_by_code: dict[str, list[str]] = {}
    for code, msg in iss.errors:
        err_by_code.setdefault(code, []).append(msg)
    for code, msg in iss.warnings:
        warn_by_code.setdefault(code, []).append(msg)
    seen_codes = set(err_by_code) | set(warn_by_code)

    for fam_name, codes in FAMILIES:
        fam_errs = sum(len(err_by_code.get(c, [])) for c in codes)
        fam_warns = sum(len(warn_by_code.get(c, [])) for c in codes)
        if fam_errs + fam_warns == 0:
            continue
        lines.append(f'## {fam_name}  (✗ {fam_errs} · ! {fam_warns})')
        lines.append('')
        for c in codes:
            errs = err_by_code.get(c, [])
            warns = warn_by_code.get(c, [])
            if not errs and not warns:
                continue
            tag = '  ⚠️ context-dependent' if c in CONTEXT_NOTES else ''
            lines.append(f'### [{c}]  ✗ {len(errs)}  ·  ! {len(warns)}{tag}')
            lines.append('')
            for m in errs:
                lines.append(f'- ✗ {m}')
            for m in warns:
                lines.append(f'- ! {m}')
            lines.append('')

    uncategorized = seen_codes - {c for _, codes in FAMILIES for c in codes}
    if uncategorized:
        lines.append('## 未分类规则')
        lines.append('')
        lines.append('> FAMILIES 表未覆盖. 看到这一段说明 validate.py 新增了规则,'
                     ' check-only.py 该更新 FAMILIES 表了.')
        lines.append('')
        for c in sorted(uncategorized):
            for m in err_by_code.get(c, []):
                lines.append(f'- ✗ [{c}] {m}')
            for m in warn_by_code.get(c, []):
                lines.append(f'- ! [{c}] {m}')
        lines.append('')

    relevant_notes = [c for c in CONTEXT_NOTES if c in seen_codes]
    if relevant_notes:
        lines.append('## 📝 context-dependent 规则说明')
        lines.append('')
        lines.append('下列规则在某些场景下会假阳性, 看 deck 上下文判断是否真要修:')
        lines.append('')
        for c in relevant_notes:
            lines.append(f'- **[{c}]** — {CONTEXT_NOTES[c]}')
        lines.append('')

    if iss.errors:
        lines.append('## ❌ FAIL —— 有 error 等级问题待修')
    else:
        lines.append('## ⚠️ PASS WITH WARNINGS —— 仅 warn 等级, 按需修')

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
#  Gate ingest 模式报告 (业务语言)
# ---------------------------------------------------------------------------

def build_gate_report(html_path: Path, slides_count: int, violations: list,
                       business_rules: dict) -> str:
    """按业务关切 A/B/C 分组渲染. violations = [(code, msg), ...]."""
    lines = []
    lines.append('# 入库准入扫描 · feishu-deck-h5')
    lines.append('')
    lines.append(f'- **目标**: `{html_path}`')
    lines.append(f'- **Slide 数**: {slides_count}')

    if not violations:
        lines.append(f'- **结果**: ✅ **通过** —— 业务必修规则全部满足, 可入库')
        lines.append('')
        lines.append('---')
        lines.append('')
        lines.append('## ✅ 入库准入: 通过')
        lines.append('')
        lines.append('这份 deck 满足 feishu-slide-library 的全部入库前置要求.')
        lines.append('下一步可以走 ingest-package.py 的四象限判定流程.')
        lines.append('')
        lines.append('> 注: 此扫描只校验"可编程的硬规则"; 内容质量 / 故事节奏 /')
        lines.append('> 视觉对齐还需要人眼审稿.')
        return '\n'.join(lines)

    lines.append(f'- **结果**: ❌ **未通过** —— {len(violations)} 处违规需修复')
    lines.append('')
    lines.append('---')
    lines.append('')
    lines.append('## ❌ 入库准入: 未通过')
    lines.append('')
    lines.append(f'共发现 **{len(violations)} 处违规**, 必须全部修复才能入库.')
    lines.append('按下列业务关切分组列出, 优先处理 A (客户看不见) > B (库找不回) > C (复用打架).')
    lines.append('')

    # Effective bucket order: the canonical A–E prefix PLUS any other concern
    # value present in business_rules (so a future concern can't be silently
    # misrouted into the "未覆盖" section — the bug that hit D/E). Sorted so a
    # new "F · …" lands after E.
    extra = sorted({(r.get('concern') or '?') for r in business_rules.values()}
                   - set(CONCERN_ORDER) - {'?'})
    order = CONCERN_ORDER + extra
    by_concern: dict[str, list] = {c: [] for c in order}
    unknown_codes = []
    for code, msg in violations:
        rule = business_rules.get(code)
        if not rule:
            unknown_codes.append((code, msg))
            continue
        concern = rule.get('concern', '?')
        if concern not in by_concern:
            unknown_codes.append((code, msg))  # rule carries no recognizable concern
            continue
        by_concern[concern].append((code, msg, rule))

    for concern in order:
        violations_in_bucket = by_concern[concern]
        if not violations_in_bucket:
            continue
        lines.append(f'## {concern}  ({len(violations_in_bucket)} 处)')
        lines.append('')

        # 同 code 的多条违规聚合在一起 (避免同一规则报 10 次刷屏)
        grouped: dict[str, list] = {}
        for code, msg, rule in violations_in_bucket:
            grouped.setdefault(code, []).append((msg, rule))
        for code, items in grouped.items():
            rule = items[0][1]
            symptom = rule.get('symptom', '(no symptom)')
            consequence = rule.get('consequence', '(no consequence)')
            fix_steps = rule.get('fix', [])

            lines.append(f'### ❌ {symptom}')
            lines.append('')
            lines.append(f'**不修后果**: {consequence}')
            lines.append('')
            lines.append('**定位** (共 {} 处):'.format(len(items)))
            for msg, _ in items[:10]:  # 最多列 10 处, 防止刷屏
                loc = _extract_location(msg)
                lines.append(f'- {loc}')
            if len(items) > 10:
                lines.append(f'- … 还有 {len(items) - 10} 处, 全部修完再回扫')
            lines.append('')
            lines.append('**怎么改**:')
            for i, step in enumerate(fix_steps, 1):
                lines.append(f'{i}. {step}')
            lines.append('')
            # 技术代码做小字附注 (作者跟开发 debug 时能 grep validate.py)
            sample_msg = items[0][0]
            sample_msg = re.sub(r'\s+', ' ', sample_msg).strip()
            if len(sample_msg) > 200:
                sample_msg = sample_msg[:200] + '…'
            lines.append(f'<sub>技术代码 `{code}` · 原始报错: {sample_msg}</sub>')
            lines.append('')

    if unknown_codes:
        lines.append('## ⚠️ business-rules.yaml 未覆盖的规则')
        lines.append('')
        lines.append('> validate.py 报了这些规则, 但业务字典里没对应文案. '
                     '请同步更新 business-rules.yaml.')
        lines.append('')
        for code, msg in unknown_codes:
            lines.append(f'- `[{code}]` {msg[:140]}')
        lines.append('')

    lines.append('---')
    lines.append('')
    lines.append('## 下一步')
    lines.append('')
    lines.append('按上面顺序修, 改完后重跑:')
    lines.append('')
    lines.append('```bash')
    lines.append(f'bash skills/feishu-deck-h5/assets/check-only.sh '
                 f'"{html_path.name}" --gate ingest')
    lines.append('```')
    lines.append('')
    lines.append('exit 0 → 严格业务/视觉评审通过; 如需入库, 另跑 --resource-only 资源门禁.')
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
#  通用: 资产 inline + 跑所有 audits
# ---------------------------------------------------------------------------

# _inline_linked was a byte-for-byte copy of validate.py's helper — unified
# per F-14. Use V.inline_linked (single source).


def _run_all_audits(html: str, slides: list, path: Path,
                     iss: V.Issues, strict: bool, visual: bool) -> None:
    """触发全部 audits via the SINGLE unified engine (UNIFY-VALIDATE-ARCH step 4).

    check-only no longer iterates its own audit registry — it folds the unified
    engine's findings into `iss` exactly the way validate.py main() does (shared
    `V.run_unified_audits`), so the two entry points can NEVER run different rule
    sets (the F-08 drift class is now structurally impossible — one source).

      visual=True  → full engine: render in headless Chromium (audits.js
                     geometry/DOM/structure rules) PLUS runner byte/source rules
                     (R-DOC-INTEGRITY / R-SELF-CONTAINED / perf). Degrades to
                     byte/source-only + a soft advisory if Chromium is missing —
                     never a silent green, never blocks a good deck on a CI hiccup.
      visual=False → `--no-visual`: byte/source rules ONLY (no browser); the
                     DOM/geometry rules do not run (documented partial check).

    `html` / `slides` are still parsed by the caller for the per-page report
    (labels, page count); the engine itself re-reads + renders `path`."""
    V.run_unified_audits(path, iss, dom_rules=visual, want_screenshots=False)


# ---------------------------------------------------------------------------
#  ZIP package mode
# ---------------------------------------------------------------------------

def is_windows_drive_path(value: str) -> bool:
    return bool(re.match(r'^[A-Za-z]:[/\\]', value or ''))


def is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode == 0o120000


def normalize_zip_member_name(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if '\\' in name:
        raise ValueError(f'反斜杠路径不允许: {name}')
    if is_windows_drive_path(name):
        raise ValueError(f'Windows 盘符路径不允许: {name}')
    if not name or name.endswith('/'):
        raise ValueError(f'空路径或目录项不允许作为文件: {name}')
    if name.startswith('/') or Path(name).is_absolute():
        raise ValueError(f'绝对路径不允许: {name}')
    parts = [part for part in name.split('/') if part]
    if not parts or any(part in {'.', '..'} for part in parts):
        raise ValueError(f'不安全 ZIP 路径: {name}')
    if any(part == '__MACOSX' for part in parts) or any(part == '.DS_Store' for part in parts):
        raise ValueError(f'ZIP 不允许包含系统元数据: {name}')
    if any(part.startswith('._') for part in parts):
        raise ValueError(f'ZIP 不允许包含 AppleDouble 元数据: {name}')
    if is_zip_symlink(info):
        raise ValueError(f'ZIP 不允许包含 symlink: {name}')
    return '/'.join(parts)


def safe_manifest_path(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if '\\' in text or text.startswith('/') or is_windows_drive_path(text):
        return None
    parts = [part for part in text.split('/') if part]
    if not parts or any(part in {'.', '..'} for part in parts):
        return None
    return '/'.join(parts)


def runtime_lock_content_id(files: list[dict[str, object]]) -> str:
    identities = [
        {
            'source_path': str(item['source_path']),
            'package_path': str(item['package_path']),
            'sha256': str(item['sha256']),
        }
        for item in sorted(files, key=lambda value: str(value['package_path']))
    ]
    canonical = json.dumps(
        {'schema_version': 1, 'files': identities},
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return 'sha256-' + hashlib.sha256(canonical).hexdigest()


def inspect_runtime_lock(package_root: Path) -> list[str]:
    lock_path = package_root / 'runtime-lock.json'
    if not lock_path.is_file():
        return []
    try:
        payload = json.loads(lock_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        return [f'runtime-lock.json 不是有效 JSON: {exc}']
    if not isinstance(payload, dict) or payload.get('schema_version') != 1:
        return ['runtime-lock.json schema_version 必须为 1']
    if set(payload) != {
        'schema_version',
        'runtime_id',
        'snapshot_id',
        'deck_h5_commit',
        'files',
    }:
        return ['runtime-lock.json 顶层字段不符合 schema v1']

    errors: list[str] = []
    runtime_id = str(payload.get('runtime_id') or '')
    snapshot_id = str(payload.get('snapshot_id') or '')
    deck_h5_commit = str(payload.get('deck_h5_commit') or '')
    if not re.fullmatch(r'sha256-[0-9a-f]{64}', runtime_id):
        errors.append('runtime-lock.json.runtime_id 不是完整 sha256 标识')
    if not re.fullmatch(r'sha256-[0-9a-f]{64}', snapshot_id):
        errors.append('runtime-lock.json.snapshot_id 不是完整 sha256 标识')
    if not re.fullmatch(r'[0-9a-f]{40}', deck_h5_commit):
        errors.append('runtime-lock.json.deck_h5_commit 不是完整 Git commit')

    raw_files = payload.get('files')
    if not isinstance(raw_files, list):
        return errors + ['runtime-lock.json.files 必须为数组']
    files: list[dict[str, object]] = []
    seen_sources: set[str] = set()
    seen_packages: set[str] = set()
    for index, item in enumerate(raw_files):
        if not isinstance(item, dict) or set(item) != {
            'source_path',
            'package_path',
            'sha256',
            'size',
        }:
            errors.append(f'runtime-lock.json.files[{index}] 字段不符合 schema v1')
            continue
        source_path = safe_manifest_path(item.get('source_path'))
        package_path = safe_manifest_path(item.get('package_path'))
        digest = str(item.get('sha256') or '')
        size = item.get('size')
        if not source_path or not package_path:
            errors.append(f'runtime-lock.json.files[{index}] 包含不安全路径')
            continue
        if source_path in seen_sources or package_path in seen_packages:
            errors.append(f'runtime-lock.json.files[{index}] 路径重复')
            continue
        seen_sources.add(source_path)
        seen_packages.add(package_path)
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            errors.append(f'runtime-lock.json.files[{index}].sha256 无效')
            continue
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            errors.append(f'runtime-lock.json.files[{index}].size 无效')
            continue
        target = package_root / package_path
        if not target.is_file():
            errors.append(f'runtime-lock.json 引用文件缺失: {package_path}')
            continue
        actual_size = target.stat().st_size
        if actual_size != size:
            errors.append(
                f'runtime-lock.json 文件大小不匹配: {package_path} '
                f'({actual_size} != {size})'
            )
            continue
        actual_digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual_digest != digest:
            errors.append(f'runtime-lock.json 文件哈希不匹配: {package_path}')
            continue
        files.append(
            {
                'source_path': source_path,
                'package_path': package_path,
                'sha256': digest,
                'size': size,
            }
        )
    if len(files) == len(raw_files) and runtime_lock_content_id(files) != runtime_id:
        errors.append('runtime-lock.json.runtime_id 与 files 内容不一致')
    return errors


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def should_ignore_reference(reference: str) -> bool:
    if not reference or reference.startswith('#') or reference in {'...', '…'}:
        return True
    parsed = urlparse(reference)
    if re.match(r'^[A-Za-z]$', parsed.scheme) and len(reference) >= 2 and reference[1] == ':':
        return False
    return parsed.scheme.lower() in REMOTE_REF_SCHEMES


def extract_html_references(html: str) -> list[str]:
    refs: list[str] = []
    for match in ATTR_REF_RE.finditer(html):
        refs.append(html_lib.unescape(match.group('value')).strip())
    for style_body in STYLE_BLOCK_RE.findall(html):
        refs.extend(extract_css_references(style_body))
    return refs


def extract_css_references(css: str) -> list[str]:
    refs: list[str] = []
    for single, double, bare in CSS_URL_RE.findall(css or ''):
        refs.append(html_lib.unescape(single or double or bare or '').strip().strip('"\''))
    return refs


def linked_stylesheet_refs(html: str) -> list[str]:
    refs: list[str] = []
    for tag in LINK_TAG_RE.findall(html):
        if not re.search(r'\brel\s*=\s*(["\']?)stylesheet\1', tag, re.I):
            continue
        match = re.search(r'\bhref\s*=\s*(["\'])(.*?)\1', tag, re.I | re.S)
        if match:
            refs.append(html_lib.unescape(match.group(2)).strip())
    return refs


def html_redirect_target(html: str) -> str:
    for pattern in (META_REFRESH_RE, JS_LOCATION_RE):
        match = pattern.search(html)
        if match:
            return html_lib.unescape(match.group(1)).strip().strip('"\'')
    return ''


def is_local_html_redirect(reference: str) -> bool:
    ref = (reference or '').strip()
    if not ref or should_ignore_reference(ref) or '\\' in ref or is_windows_drive_path(ref):
        return False
    parsed = urlparse(ref)
    if parsed.scheme or parsed.netloc:
        return False
    path_text = unquote(parsed.path or ref).strip()
    if not path_text or path_text.startswith('/') or Path(path_text).is_absolute():
        return False
    parts = [part for part in path_text.split('/') if part]
    if not parts or any(part in {'.', '..'} for part in parts):
        return False
    return Path(path_text).suffix.lower() in HTML_SUFFIXES


def resolve_package_reference(reference: str, *, source_dir: Path, package_root: Path) -> tuple[Path | None, str | None]:
    ref = (reference or '').strip().strip('"\'')
    if should_ignore_reference(ref):
        return None, None
    if is_windows_drive_path(ref):
        return None, f'HTML 引用包含 Windows 盘符路径: {ref}'
    if '\\' in ref:
        return None, f'HTML 引用包含反斜杠路径: {ref}'

    parsed = urlparse(ref)
    scheme = parsed.scheme.lower()
    if scheme in LOCAL_PATH_SCHEMES:
        return None, f'HTML 引用本机路径: {ref}'
    if scheme and scheme not in REMOTE_REF_SCHEMES:
        return None, f'HTML 引用不支持的本机/自定义 scheme: {ref}'

    path_text = unquote(parsed.path or ref)
    if not path_text:
        return None, None
    if path_text.startswith('/') or Path(path_text).is_absolute():
        return None, f'HTML 引用绝对路径: {ref}'
    parts = [part for part in path_text.split('/') if part]
    if any(part == '..' for part in parts):
        return None, f'HTML 引用包含 ../ 越界路径: {ref}'

    target = (source_dir / path_text).resolve()
    if not is_relative_to(target, package_root):
        return None, f'HTML 引用逃逸 ZIP 根目录: {ref}'
    return target, None


def inspect_asset_references(primary_html: Path, package_root: Path) -> list[str]:
    errors: list[str] = []
    html = primary_html.read_text(encoding='utf-8')
    css_to_scan: list[Path] = []
    for ref in sorted(set(extract_html_references(html))):
        target, error = resolve_package_reference(ref, source_dir=primary_html.parent, package_root=package_root)
        if error:
            errors.append(error)
            continue
        if target and not target.exists():
            errors.append(f'HTML 引用资产缺失: {ref}')
            continue
        if target and Path(unquote(urlparse(ref).path or ref)).suffix.lower() == '.css':
            css_to_scan.append(target)

    for ref in linked_stylesheet_refs(html):
        target, error = resolve_package_reference(ref, source_dir=primary_html.parent, package_root=package_root)
        if error or not target or not target.exists():
            continue
        if target not in css_to_scan:
            css_to_scan.append(target)

    for css_path in sorted(set(css_to_scan)):
        try:
            css = css_path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            css = css_path.read_text(encoding='utf-8', errors='ignore')
        for ref in sorted(set(extract_css_references(css))):
            target, error = resolve_package_reference(ref, source_dir=css_path.parent, package_root=package_root)
            if error:
                errors.append(error)
            elif target and not target.exists():
                errors.append(f'CSS 引用资产缺失: {ref}')
    return errors


def closure_issue_message(issue: object) -> str:
    code = str(getattr(issue, 'code', '') or '')
    required_by = str(getattr(issue, 'required_by', '') or '')
    reference = str(getattr(issue, 'reference', '') or '')
    message = f'{code} {required_by} -> {reference}'
    if code == 'LOCAL_REF_MISSING' and required_by == 'index.html':
        return f'{message} (HTML 引用资产缺失: {reference})'
    if code == 'LOCAL_REF_ESCAPE':
        if is_windows_drive_path(reference):
            return f'{message} (HTML 引用包含 Windows 盘符路径: {reference})'
        if '\\' in reference:
            return f'{message} (HTML 引用包含反斜杠路径: {reference})'
        if urlparse(reference).scheme.lower() == 'file':
            return f'{message} (HTML 引用本机路径: {reference})'
        if '..' in Path(unquote(urlparse(reference).path or reference)).parts:
            return f'{message} (HTML 引用包含 ../ 越界路径: {reference})'
        return f'{message} (HTML 引用逃逸 ZIP 根目录: {reference})'
    return message


def run_resource_check(path: Path) -> tuple[int, str]:
    """Check only the runtime resource closure of a standalone HTML artifact.

    This intentionally does not call validate.py or Playwright.  A library
    ingest must reject a broken package/resource reference, but visual quality
    and cross-page consistency belong to an explicit authoring/review pass.
    """
    manifest_path = path.parent / 'assets-manifest.yaml'
    if manifest_path.is_file():
        closure = INGEST_ASSET_CLOSURE.inspect_package(
            path.parent,
            path,
            manifest_path,
        )
    else:
        # A direct HTML import may not have a sidecar manifest.  Keep the
        # resource-only check useful for that compatibility path while still
        # scanning every runtime-local reference from the HTML.
        with tempfile.TemporaryDirectory(prefix='feishu-resource-manifest.') as td:
            empty_manifest = Path(td) / 'assets-manifest.yaml'
            empty_manifest.write_text('assets: []\n', encoding='utf-8')
            closure = INGEST_ASSET_CLOSURE.inspect_package(
                path.parent,
                path,
                empty_manifest,
            )

    errors = [closure_issue_message(issue) for issue in closure.issues]
    lines = [
        '# feishu-deck-h5 resource-only 入库检查',
        '',
        f'- 文件: `{path}`',
        '- 检查: 运行时本地引用、素材存在性、素材非空、路径安全',
        f'- 可达文件: {len(closure.reachable_files)}',
        f'- manifest 素材: {len(closure.manifest_files)}',
        '',
    ]
    if errors:
        lines.append('## 🔴 资源阻塞问题')
        lines.extend(f'- {item}' for item in errors)
        return 1, '\n'.join(lines)
    lines.append('## ✅ 资源闭包通过')
    lines.append('视觉、排版和跨页一致性未纳入本次入库门禁。')
    return 0, '\n'.join(lines)


def inspect_zip_package(zip_path: Path, extract_dir: Path) -> tuple[Path | None, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    extract_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []

    try:
        with zipfile.ZipFile(zip_path) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            for info in infos:
                try:
                    names.append(normalize_zip_member_name(info))
                except ValueError as exc:
                    errors.append(str(exc))
            if errors:
                return None, errors, warnings
            for info, name in zip(infos, names):
                target = extract_dir / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, target.open('wb') as dst:
                    shutil.copyfileobj(src, dst)
    except zipfile.BadZipFile:
        return None, ['不是有效 ZIP 文件'], warnings

    top_level = {name.split('/', 1)[0] for name in names}
    if top_level == {'output'}:
        errors.append('ZIP 顶层只有 output/；deck.zip 顶层必须直接包含 index.html、deck.json、assets/、assets-manifest.yaml、ingestion-manifest.json')

    for item in ZIP_HARD_REQUIRED:
        target = extract_dir / item
        if item == 'assets':
            if not target.is_dir():
                errors.append('缺硬必需目录: assets/')
        elif not target.is_file():
            errors.append(f'缺硬必需文件: {item}')

    for item in ZIP_SOFT_REQUIRED:
        if not (extract_dir / item).exists():
            warnings.append(f'缺软必需文件: {item}')

    manifest_path = extract_dir / 'ingestion-manifest.json'
    primary_html: Path | None = None
    requires_runtime_lock = False
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            errors.append(f'ingestion-manifest.json 不是有效 JSON: {exc}')
            manifest = {}
        deck_id = str(manifest.get('deck_id') or '').strip() if isinstance(manifest, dict) else ''
        if not deck_id:
            errors.append('ingestion-manifest.json.deck_id 缺失；library 入库无法继承稳定素材 ID')
        elif not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}', deck_id):
            errors.append(f'ingestion-manifest.json.deck_id 不是安全 ID: {deck_id}')
        hard_required = manifest.get('hard_required') if isinstance(manifest, dict) else None
        requires_runtime_lock = (
            isinstance(hard_required, list)
            and 'runtime-lock.json' in hard_required
        )
        primary = safe_manifest_path(manifest.get('primary_html')) if isinstance(manifest, dict) else None
        if not primary:
            errors.append('ingestion-manifest.json.primary_html 缺失或不是安全相对路径')
        else:
            primary_html = extract_dir / primary
            if not primary_html.is_file():
                errors.append(f'primary_html 不存在: {primary}')
            elif primary_html.suffix.lower() not in HTML_SUFFIXES:
                errors.append(f'primary_html 不是 HTML 文件: {primary}')

    runtime_lock_path = extract_dir / 'runtime-lock.json'
    if requires_runtime_lock and not runtime_lock_path.is_file():
        errors.append('缺硬必需文件: runtime-lock.json')
    if runtime_lock_path.is_file():
        errors.extend(inspect_runtime_lock(extract_dir))

    if primary_html and primary_html.is_file():
        try:
            primary_text = primary_html.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            primary_text = primary_html.read_text(encoding='utf-8', errors='ignore')
        redirect = html_redirect_target(primary_text)
        if is_local_html_redirect(redirect):
            errors.append(f'primary_html 是跳转壳，不能作为入库入口: {redirect}；请把真实 deck 内容写入 index.html')
        closure = INGEST_ASSET_CLOSURE.inspect_package(
            extract_dir,
            primary_html,
            extract_dir / 'assets-manifest.yaml',
        )
        errors.extend(closure_issue_message(issue) for issue in closure.issues)
    return primary_html, errors, warnings


def build_zip_package_report(
    path: Path,
    errors: list[str],
    warnings: list[str],
    *,
    resource_only: bool = False,
) -> str:
    lines = [
        '# feishu-deck-h5 deck.zip ' + ('resource-only 资源检查' if resource_only else '入库包检查'),
        '',
        f'- 文件: `{path}`',
    ]
    if resource_only:
        lines.append('- 检查: 包结构、入口 HTML、运行时本地引用和素材闭包')
    lines.append('')
    if errors:
        lines.append('## 🔴 阻塞问题')
        lines.extend(f'- {item}' for item in errors)
    else:
        lines.append('## ✅ 包结构通过')
    if warnings:
        lines.extend(['', '## 🟡 非阻塞提醒'])
        lines.extend(f'- {item}' for item in warnings)
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
#  main
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description='feishu-deck-h5 · 纯检查模式 (无 PREFLIGHT / new-run / asset-copy)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
例子:
  # 默认模式: 按 family 分组 review-style 报告
  python3 check-only.py ../examples/sample-deck.html

  # 入库门禁模式: 业务必修规则, 业务语言报告, 任一违规即 exit 1
  python3 check-only.py /path/to/deck.html --gate ingest
  python3 check-only.py /path/to/deck.zip --gate ingest

  # 资源-only 入库门禁: 只阻塞包结构和运行时资源问题
  python3 check-only.py /path/to/deck.zip --resource-only

  # 写报告到文件 (默认或 gate 模式都可)
  python3 check-only.py /path/to/deck.html --gate ingest --report report.md
""")
    p.add_argument('html', help='待检查的 HTML 或 deck.zip 文件路径')
    p.add_argument('--strict', action='store_true',
                   help='把 warn 升级为 error (与 --gate 互斥)')
    p.add_argument('--visual', action=argparse.BooleanOptionalAction,
                   default=True,
                   help='Playwright 视觉审计 (R-OVERFLOW / R-VIS-* / R-FOCAL …). '
                        'DEFAULT: on, 与 validate.py 对齐; --no-visual 关闭 '
                        '(CI 无 chromium 时); --gate ingest 强制开启. '
                        '未装 playwright/chromium 时自动跳过, 不硬失败')
    p.add_argument('--gate', choices=['ingest'],
                   help='严格业务/视觉评审模式. ingest = 业务必修规则和业务语言报告; '
                        '不是默认的 slide-library 资源入库门')
    p.add_argument('--resource-only', action='store_true',
                   help='资源-only 入库门禁: 只检查包结构/运行时本地引用/素材闭包, '
                        '不跑视觉、排版或跨页一致性规则. 适用于 slide-library 入库')
    p.add_argument('--by-rule', action='store_true',
                   help='工程师视图: 按技术规则家族 (R06 / R-VIS-TIER…) 分组. '
                        '默认是逐页业务报告; 排查 framework bug 时用这个.')
    p.add_argument('--report', metavar='PATH',
                   help='把 markdown 报告写到指定路径; 不带则打到 stdout')
    p.add_argument('--scope', default=None, metavar='N[,N,KEY,...]',
                   help='F-336: 把报告限定到这些页 — 逗号分隔的 1-based 页号 '
                        '(= URL #N / data-screen-label 顺序) 和/或 slide key. '
                        '所有规则照常全 deck 跑 (跨页问题仍能抓到), 但只呈现命中 '
                        '在 scope 页上的 findings + deck 级 findings. 单页 review '
                        '不再被存量 off-scope 噪声淹没.')
    return p


def run_html_check(path: Path, args: argparse.Namespace) -> tuple[int, str]:
    html = path.read_text(encoding='utf-8')
    html = V.inline_linked(html, path.parent)
    slides = V.extract_slides(html)
    iss = V.Issues()

    # gate ingest: 自动开 visual + strict
    is_gate = args.gate == 'ingest'
    strict = args.strict or is_gate
    visual = args.visual or is_gate

    _run_all_audits(html, slides, path, iss, strict, visual)

    # F-336 · --scope: filter the REPORT to the locked page(s). All rules already
    # ran whole-deck (a cross-page problem is still caught); we only surface
    # findings attributed to an in-scope slide (by `slide N` in the msg OR a
    # data-slide-key="<in-scope key>") plus deck-level findings (no page anchor).
    if getattr(args, 'scope', None):
        keys_in_doc = re.findall(r'data-slide-key="([^"]+)"', html)  # 1-based order
        key_to_page = {k: i + 1 for i, k in enumerate(keys_in_doc)}
        scope_pages, scope_keys, bad = set(), set(), []
        for tok in str(args.scope).split(','):
            tok = tok.strip()
            if not tok:
                continue
            if tok.isdigit():
                scope_pages.add(int(tok))
            elif tok in key_to_page:
                scope_pages.add(key_to_page[tok])
            else:
                bad.append(tok)
        if bad or not scope_pages:
            return 2, (f"check-only: --scope '{args.scope}' 解析不出有效页: "
                       f"{', '.join(bad) or '(空)'}. 接受 1-based 页号或 slide key.")
        for p in scope_pages:                       # match findings cited by key too
            if 1 <= p <= len(keys_in_doc):
                scope_keys.add(keys_in_doc[p - 1])

        def _keep(item):
            _c, m = item
            idxs = set(_slides_of_msg(m))
            has_key_ref = 'data-slide-key="' in m
            if not idxs and not has_key_ref:
                return True                          # deck-level — always surface
            if idxs & scope_pages:
                return True
            return any(f'data-slide-key="{k}"' in m for k in scope_keys)
        iss.errors = [it for it in iss.errors if _keep(it)]
        iss.warnings = [it for it in iss.warnings if _keep(it)]
        iss.soft_warnings = [it for it in iss.soft_warnings if _keep(it)]

    # strict 模式 (含 gate): warn 升 error
    if strict:
        iss.errors.extend(iss.warnings)
        iss.warnings = []

    # 渲染报告
    if is_gate:
        rules = load_business_rules()
        # F-18: warn (don't block) if yaml lists a code validate.py no longer
        # emits — otherwise that rule silently drops out of the gate.
        warn_on_gate_rule_drift(set(rules.keys()), enumerate_validate_rules())
        # 只保留 yaml 里覆盖的规则 (业务必修)
        kept = [(c, m) for c, m in iss.errors if c in rules]
        report = build_gate_report(path, len(slides), kept, rules)
        # exit code 反映 gate 通过与否
        rc = 1 if kept else 0
    else:
        # 默认 = 逐页业务报告 (标准格式, 所有人一致). --by-rule = 工程师家族视图.
        # 业务报告需要 business-rules.yaml; 万一缺/PyYAML 没装, 软退回家族视图.
        rules = None
        if not args.by_rule:
            try:
                rules = load_business_rules()
            except SystemExit:
                rules = None
        if rules is not None:
            report = build_per_page_report(path, len(slides), iss, strict,
                                           rules, html)
        else:
            mode_hints = detect_mode_hints(html, len(slides))
            report = build_default_report(path, len(slides), iss, strict,
                                          mode_hints)
        rc = 1 if iss.errors else 0

    return rc, report


def emit_report(report: str, report_path: str | None) -> None:
    if report_path:
        out = Path(report_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report + '\n', encoding='utf-8')
        print(f'✓ 报告已写到 {out}', file=sys.stderr)
    else:
        print(report)


def main() -> int:
    p = build_parser()
    args = p.parse_args()

    path = Path(args.html).resolve()
    if not path.is_file():
        print(f'ERROR: 找不到文件 {path}', file=sys.stderr)
        return 2

    if path.suffix.lower() == '.zip':
        with tempfile.TemporaryDirectory(prefix='feishu-check-only-zip.') as td:
            primary, errors, warnings = inspect_zip_package(path, Path(td) / 'package')
            for warning in warnings:
                print(f'WARNING: {warning}', file=sys.stderr)
            if errors or primary is None:
                emit_report(
                    build_zip_package_report(path, errors, warnings, resource_only=args.resource_only),
                    args.report,
                )
                return 1
            if args.resource_only:
                # inspect_zip_package already performs the package contract
                # and runtime asset-closure scan.  Do not fall through to the
                # full HTML/visual audit in resource-only mode.
                emit_report(build_zip_package_report(path, errors, warnings, resource_only=True), args.report)
                return 0
            rc, report = run_html_check(primary, args)
            emit_report(report, args.report)
            return rc

    if path.suffix.lower() not in HTML_SUFFIXES:
        print(f'ERROR: unsupported check-only input: {path.suffix or "<none>"}', file=sys.stderr)
        return 2

    if args.resource_only:
        rc, report = run_resource_check(path)
    else:
        rc, report = run_html_check(path, args)
    emit_report(report, args.report)
    return rc


if __name__ == '__main__':
    sys.exit(main())
