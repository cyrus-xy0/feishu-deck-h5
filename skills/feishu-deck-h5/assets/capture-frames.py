#!/usr/bin/env python3
"""capture-frames.py — 动效页抓帧 + 落定断言(motion-system §3.4 / §3.5 的配套工具)。

给带 bespoke 入场动效的页面做"动起来了 + 落定干净"双验证:
  • 每个 key 抓两帧:mid(动画中段,证明在动)+ settled(等完最长 delay+duration,
    证明落定)。
  • settled 帧上跑 §3.5 硬断言:
      - 所有 .reveal(可换 --assert-class)computed opacity === 1 且无残留 transform
        (卡半透明 / 卡位移 = 该页动效不合格);
      - 瞬态元素(--transient-class,默认 fly)已退场(opacity ≤ 0.05);
      - 无元素 bbox 溢出 .slide 边界(±1.5px 容差)。
  • 多个 key 共用一个浏览器会话(每页省一次 chromium 冷启动)。

用法:
  python3 capture-frames.py <index.html> <key> [<key>...]
      [--out-dir DIR]          # 截图输出目录,默认 /tmp
      [--settle-ms N]          # 落定等待,默认 4500;> 页内最长 delay+duration
      [--mid-ms N]             # 中间帧时刻,默认 900
      [--assert-class NAME]    # 落定断言的入场 hook class,默认 reveal
      [--transient-class NAME] # 必须退场的瞬态 class,默认 fly

退出码:0 = 全部 key 通过断言;1 = 任一 key 不通过(详情在 stdout JSON);2 = 环境问题。
截图命名:<out-dir>/<key>_mid.png / <key>_settled.png。

只读不写 deck;需要 playwright + chromium(与 validate.py --visual 同环境)。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="capture mid+settled frames and assert settle state")
    ap.add_argument("html", help="rendered index.html path")
    ap.add_argument("keys", nargs="+", help="data-slide-key(s) to verify")
    ap.add_argument("--out-dir", default="/tmp")
    ap.add_argument("--settle-ms", type=int, default=4500)
    ap.add_argument("--mid-ms", type=int, default=900)
    ap.add_argument("--assert-class", default="reveal")
    ap.add_argument("--transient-class", default="fly")
    args = ap.parse_args()

    html = Path(args.html).resolve()
    if not html.exists():
        print(f"✗ not found: {html}", file=sys.stderr)
        return 2
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("✗ needs playwright (pip install playwright && playwright install chromium)",
              file=sys.stderr)
        return 2

    assert_js = """([key, hookCls, transientCls]) => {
      const slide = [...document.querySelectorAll('.slide')]
        .find((s) => s.getAttribute('data-slide-key') === key);
      if (!slide) return { error: 'slide not found: ' + key };
      const out = { notSettled: [], transientVisible: 0, overflow: [] };
      slide.querySelectorAll('.' + hookCls).forEach((el) => {
        const cs = getComputedStyle(el);
        const op = parseFloat(cs.opacity);
        const tf = cs.transform;
        const moved = tf && tf !== 'none' && !/matrix\\(1, 0, 0, 1, 0, 0\\)/.test(tf);
        if (op < 0.99 || moved) {
          out.notSettled.push(
            (el.className || el.tagName) + ' op=' + op.toFixed(2)
            + ' tf=' + (moved ? tf : 'none'));
        }
      });
      slide.querySelectorAll('.' + transientCls).forEach((el) => {
        if (parseFloat(getComputedStyle(el).opacity) > 0.05) out.transientVisible++;
      });
      const sb = slide.getBoundingClientRect();
      slide.querySelectorAll('*').forEach((el) => {
        const r = el.getBoundingClientRect();
        if (r.width && (r.right > sb.right + 1.5 || r.left < sb.left - 1.5
            || r.bottom > sb.bottom + 1.5 || r.top < sb.top - 1.5)) {
          const c = (el.className && el.className.baseVal !== undefined)
            ? el.className.baseVal : el.className;
          out.overflow.push((c || el.tagName) + ' '
            + Math.round(r.left - sb.left) + ',' + Math.round(r.top - sb.top)
            + ' ' + Math.round(r.width) + 'x' + Math.round(r.height));
        }
      });
      out.overflow = [...new Set(out.overflow)].slice(0, 8);
      return out;
    }"""

    failed = False
    report = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport={"width": 1920, "height": 1080}).new_page()
        page.goto(html.as_uri() + "#" + args.keys[0],
                  wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(300)
        # 确保 present 模式已就绪(框架当前页标记在 .slide-frame.is-current 上)
        if not page.evaluate("document.querySelectorAll('.slide-frame.is-current').length"):
            for k in ("Enter", " ", "ArrowRight"):
                page.keyboard.press(k)
                page.wait_for_timeout(150)
                if page.evaluate("document.querySelectorAll('.slide-frame.is-current').length"):
                    break
        for key in args.keys:
            # 换页触发动画从头重放(is-current 祖先类切换 = 框架自身的重放机制)
            page.evaluate(f"window.location.hash = '#{key}'")
            page.wait_for_timeout(args.mid_ms)
            page.screenshot(path=str(out_dir / f"{key}_mid.png"))
            page.wait_for_timeout(max(0, args.settle_ms - args.mid_ms))
            page.screenshot(path=str(out_dir / f"{key}_settled.png"))
            res = page.evaluate(assert_js, [key, args.assert_class, args.transient_class])
            report[key] = res
            ok = (not res.get("error") and not res.get("notSettled")
                  and not res.get("transientVisible") and not res.get("overflow"))
            if not ok:
                failed = True
            print(f"{'✓' if ok else '✗'} {key}  →  {out_dir}/{key}_mid.png  {key}_settled.png")
        browser.close()

    print(json.dumps(report, ensure_ascii=False, indent=1))
    if failed:
        print("✗ settle assertions failed — 修终值/both/delay,别交付(motion-system §3.5)",
              file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
