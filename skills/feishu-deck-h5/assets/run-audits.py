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

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1920, "height": 1080})
            page = context.new_page()
            page.goto(url, wait_until="load", timeout=30_000)
            page.wait_for_timeout(args.settle_ms)  # 让 scale-to-fit / 布局稳定
            page.evaluate("(s) => { window.__AUDIT_SCOPE__ = s; }", scope)
            result = page.evaluate(audits_src)
            browser.close()
    except Exception as e:  # noqa: BLE001 — runner 层兜底,报清楚比吞掉好
        print(f"ERROR: 渲染/求值失败:{e}", file=sys.stderr)
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
