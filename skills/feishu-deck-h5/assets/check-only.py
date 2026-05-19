#!/usr/bin/env python3
"""feishu-deck-h5 · 纯检查模式 (check-only)

用法场景: 别人给你一份做好的 HTML deck, 你只想知道哪些地方不合规 ——
跳过 PREFLIGHT / new-run / asset-copy / sidecar 生成的整套生成流程,
直接对单文件跑全套 validate.py 审计, 产出 markdown 报告.

两个模式:

  默认模式 — `bash check-only.sh deck.html`
    按 family (结构/排版/品牌/...) 分组列违规, 标注 context-dependent 规则.
    适合 review-style 看一份外部 deck 的整体卫生.

  入库门禁 — `bash check-only.sh deck.html --gate ingest`
    只看 21 条必修规则 (业务关切 A/B/C 三类), 全部 warn 升 error.
    用 business-rules.yaml 把每条违规渲染成业务语言: 业务症状 / 不修后果 /
    具体修改步骤 + 技术代码做小字附注.
    适合 ingest-package.py 调来做 slide-library 准入扫描.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate as V


# ---------------------------------------------------------------------------
#  默认模式: family 分组 + context-dependent 标注
# ---------------------------------------------------------------------------

FAMILIES = [
    ('结构 / DOM',           ['R02', 'R07', 'R-DOM']),
    ('排版 / 文案',          ['R05', 'R06', 'R13', 'R20', 'R56',
                              'R-WHITE-TEXT', 'R-HIERARCHY']),
    ('品牌 / 调色板',        ['L1', 'R10', 'R12', 'R38', 'R49', 'R-LANG']),
    ('布局完整性',           ['L2', 'L4', 'R36', 'R47', 'R48']),
    ('UI 仿真 / slide-key',  ['UI1', 'R-KEY']),
    ('演示模式 / 运行时',    ['R29-32']),
    ('texts.md 联动',        ['T00', 'T01', 'T02', 'T03']),
    ('性能预算',             ['P50', 'P51', 'P52', 'P53', 'P54', 'P55']),
    ('视觉 (Playwright)',    ['R-OVERFLOW', 'R-OVERLAP', 'R-VIS-TIER', 'R-VIS-HIER',
                              'R-VIS-LABEL-FLOOR', 'R-VIS-BODY-FLOOR',
                              'R-VIS-ALIGN', 'R-VISUAL']),
    ('交付物附件',           ['R-FEEDBACK']),
]

CONTEXT_NOTES = {
    'R-FEEDBACK': '别人交给你的 deck 通常没有 FEEDBACK.md (那是 new-run '
                  '工作流的产物), 这条 warn 可忽略.',
    'T00':        '如果是 Replica-mode (每页 PDF 截图) 或外部来源 deck, '
                  '没有 data-text-id 是正常的.',
    'T03':        '只有同时附 texts.md 才会校验 sync; 纯 HTML 检查不必关注.',
    'P50':        '只在你打算用 inline 单文件交付时才相关; linked 模式的 '
                  'deck 这条只是参考.',
    'UI1':        '如果 deck 是 Replica-mode (PDF 截图 + .page-replica), '
                  '所有 <img> 都会触发, 但这是设计如此.',
    'R29-32':     '如果 deck 是 Replica-mode 或纯阅读型 HTML (不需要 '
                  'present-mode), 可不必满足.',
}


# ---------------------------------------------------------------------------
#  Gate ingest 模式: 业务规则字典
# ---------------------------------------------------------------------------

CONCERN_ORDER = [
    'A · 客户看不见',
    'B · 库找不回这张 slide',
    'C · 复用时会打架',
]


def load_business_rules() -> dict:
    """从 business-rules.yaml 加载 21 条必修规则的业务文案."""
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
        lines.append(f'- **结果**: ✅ **通过** —— 21 条必修规则全部满足, 可入库')
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

    by_concern: dict[str, list] = {c: [] for c in CONCERN_ORDER}
    unknown_codes = []
    for code, msg in violations:
        rule = business_rules.get(code)
        if not rule:
            unknown_codes.append((code, msg))
            continue
        concern = rule.get('concern', '?')
        # tolerant matching: yaml 里可能没完全用 CONCERN_ORDER 字面值
        matched_bucket = next(
            (b for b in CONCERN_ORDER if b == concern), None)
        if matched_bucket is None:
            unknown_codes.append((code, msg))
            continue
        by_concern[matched_bucket].append((code, msg, rule))

    for concern in CONCERN_ORDER:
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
    lines.append('exit 0 → 准入通过, 可移交库的 ingest-package.py 走入库流程.')
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
#  通用: 资产 inline + 跑所有 audits
# ---------------------------------------------------------------------------

def _inline_linked(html_text: str, base_dir: Path) -> str:
    """把 <link rel=stylesheet> / <script src> 内联进 html, 让审计能看到
    framework CSS/JS 内容 (跟 validate.py main() 同逻辑)."""
    def repl_link(m):
        href = m.group(1)
        if href.startswith(('http:', 'https:', 'data:')):
            return m.group(0)
        target = (base_dir / href).resolve()
        if not target.is_file():
            return m.group(0)
        return ('<style data-source="framework">'
                + target.read_text(encoding='utf-8') + '</style>')
    html_text = re.sub(
        r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>',
        repl_link, html_text)

    def repl_script(m):
        src = m.group(1)
        if src.startswith(('http:', 'https:', 'data:')):
            return m.group(0)
        target = (base_dir / src).resolve()
        if not target.is_file():
            return m.group(0)
        return ('<script data-source="framework">'
                + target.read_text(encoding='utf-8') + '</script>')
    return re.sub(
        r'<script[^>]*src="([^"]+)"[^>]*>\s*</script>',
        repl_script, html_text)


def _run_all_audits(html: str, slides: list, path: Path,
                     iss: V.Issues, strict: bool, visual: bool) -> None:
    """触发全部 audits. strict 影响哪些规则报 err vs warn,
    visual 控制是否调 Playwright."""
    V.audit_dom_integrity(html, iss)
    V.audit_structure(slides, iss)
    V.audit_titles_one_line(slides, iss)
    V.audit_brand_chrome(slides, iss)
    V.audit_copy_rules(html, iss)
    V.audit_font_sizes(html, iss)
    V.audit_type_ladder(html, iss)
    V.audit_white_text(html, iss)
    V.audit_no_drop_shadows(html, iss)
    V.audit_data_decor(slides, iss)
    V.audit_hex_palette(html, iss)
    V.audit_runtime_chrome(html, iss, path)
    V.audit_centering_pattern(html, iss)
    V.audit_layout_integrity(html, iss)
    V.audit_default_centering(html, iss)
    V.audit_hierarchy(html, iss)
    V.audit_variant_discipline(html, iss)
    V.audit_ui_mocks_are_html(slides, iss)
    V.audit_no_cyan_accent(slides, iss)
    V.audit_header_minimal(slides, iss)
    V.audit_slide_keys(slides, iss)
    V.audit_language_policy(html, slides, iss)
    V.audit_perf(html, iss)
    V.audit_text_ids(html, path, iss)
    V.audit_feedback_md(path, iss)
    if visual:
        V.run_visual_audits(path, iss, want_screenshots=False)


# ---------------------------------------------------------------------------
#  main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description='feishu-deck-h5 · 纯检查模式 (无 PREFLIGHT / new-run / asset-copy)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
例子:
  # 默认模式: 按 family 分组 review-style 报告
  python3 check-only.py ../examples/sample-deck.html

  # 入库门禁模式: 21 条必修规则, 业务语言报告, 任一违规即 exit 1
  python3 check-only.py /path/to/deck.html --gate ingest

  # 写报告到文件 (默认或 gate 模式都可)
  python3 check-only.py /path/to/deck.html --gate ingest --report report.md
""")
    p.add_argument('html', help='待检查的 HTML 文件路径')
    p.add_argument('--strict', action='store_true',
                   help='把 warn 升级为 error (与 --gate 互斥)')
    p.add_argument('--visual', action='store_true',
                   help='加跑 Playwright 视觉审计; --gate ingest 自动开启')
    p.add_argument('--gate', choices=['ingest'],
                   help='入库门禁模式. ingest = 21 条必修规则, '
                        '业务语言报告, 库 ingest-package.py 用')
    p.add_argument('--report', metavar='PATH',
                   help='把 markdown 报告写到指定路径; 不带则打到 stdout')
    args = p.parse_args()

    path = Path(args.html).resolve()
    if not path.is_file():
        print(f'ERROR: 找不到文件 {path}', file=sys.stderr)
        return 2

    html = path.read_text(encoding='utf-8')
    html = _inline_linked(html, path.parent)
    slides = V.extract_slides(html)
    iss = V.Issues()

    # gate ingest: 自动开 visual + strict
    is_gate = args.gate == 'ingest'
    strict = args.strict or is_gate
    visual = args.visual or is_gate

    _run_all_audits(html, slides, path, iss, strict, visual)

    # strict 模式 (含 gate): warn 升 error
    if strict:
        iss.errors.extend(iss.warnings)
        iss.warnings = []

    # 渲染报告
    if is_gate:
        rules = load_business_rules()
        # 只保留 yaml 里覆盖的规则 (21 条必修)
        kept = [(c, m) for c, m in iss.errors if c in rules]
        report = build_gate_report(path, len(slides), kept, rules)
        # exit code 反映 gate 通过与否
        rc = 1 if kept else 0
    else:
        mode_hints = detect_mode_hints(html, len(slides))
        report = build_default_report(path, len(slides), iss, strict, mode_hints)
        rc = 1 if iss.errors else 0

    if args.report:
        out = Path(args.report).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report + '\n', encoding='utf-8')
        print(f'✓ 报告已写到 {out}', file=sys.stderr)
    else:
        print(report)

    return rc


if __name__ == '__main__':
    sys.exit(main())
