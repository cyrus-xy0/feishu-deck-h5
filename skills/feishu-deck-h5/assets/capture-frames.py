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
      [--click-selector CSS]   # 落定后点击当前页元素,并抓 *_clicked.png
      [--close-selector CSS]   # 可选:点击关闭元素,并抓 *_closed.png
      [--click-wait-ms N]      # 点击后等待,默认 250
      [--allow-remote]         # 不拦外部 http(s) 请求(默认拦:deck 资产应本地化,
                               # 远程 iframe/字体会把 load/fonts.ready 永久挂死,F-311)

退出码:0 = 全部 key 通过断言;1 = 任一 key 不通过(详情在 stdout JSON);2 = 环境问题。
截图命名:<out-dir>/<key>_mid.png / <key>_settled.png；启用交互时另有
<key>_clicked.png，指定关闭元素时另有 <key>_closed.png。

只读不写 deck;需要 playwright + chromium(与 validate.py --visual 同环境)。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def _canvas_dimensions(html: Path) -> tuple[int, int]:
    """Portable rendered HTML owns the canvas; legacy files default to 16:9."""
    try:
        raw = html.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 1920, 1080
    mw = re.search(r"\bdata-deck-width\s*=\s*['\"]([0-9]+)['\"]", raw, re.I)
    mh = re.search(r"\bdata-deck-height\s*=\s*['\"]([0-9]+)['\"]", raw, re.I)
    if mw and mh:
        width, height = int(mw.group(1)), int(mh.group(1))
        if width > 0 and height > 0:
            return width, height
    return 1920, 1080


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="capture mid+settled frames and assert settle state")
    ap.add_argument("html", help="rendered index.html path")
    ap.add_argument("keys", nargs="+", help="data-slide-key(s) to verify")
    ap.add_argument("--out-dir", default="/tmp")
    ap.add_argument("--settle-ms", type=int, default=4500)
    ap.add_argument("--mid-ms", type=int, default=900)
    ap.add_argument("--assert-class", default="reveal")
    ap.add_argument("--transient-class", default="fly")
    ap.add_argument("--click-selector",
                    help="after settle, click this CSS selector inside the current slide "
                         "and capture <key>_clicked.png")
    ap.add_argument("--close-selector",
                    help="after the clicked frame, click this CSS selector inside the "
                         "current slide and capture <key>_closed.png")
    ap.add_argument("--click-wait-ms", type=int, default=250,
                    help="wait after interaction clicks (default: 250)")
    ap.add_argument("--allow-remote", action="store_true",
                    help="don't abort external http(s) requests (default aborts them: "
                         "remote iframes/fonts hang load+fonts.ready forever offline, F-311)")
    return ap


def main() -> int:
    args = _build_parser().parse_args()

    if args.close_selector and not args.click_selector:
        print("✗ --close-selector requires --click-selector", file=sys.stderr)
        return 2
    if args.click_wait_ms < 0:
        print("✗ --click-wait-ms must be >= 0", file=sys.stderr)
        return 2

    html = Path(args.html).resolve()
    if not html.exists():
        print(f"✗ not found: {html}", file=sys.stderr)
        return 2
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    canvas_w, canvas_h = _canvas_dimensions(html)

    try:
        from playwright.sync_api import sync_playwright
        from playwright.sync_api import TimeoutError as PWTimeoutError
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

    def _shot(page, path: Path) -> None:
        """截图带兜底(F-311):正常走 page.screenshot(等 fonts.ready,最准),
        但若页面里有永不落定的资源(典型:远程 iframe 文档的字体)导致超时,
        降级走 CDP Page.captureScreenshot——不等待、立刻出图,宁可拿到帧也别挂死。"""
        try:
            page.screenshot(path=str(path), timeout=8000)
        except PWTimeoutError:
            print(f"  ! screenshot wait timed out — CDP fallback for {path.name}"
                  f"(页内有永不落定的资源,常见=远程 iframe;截图内容不受影响)",
                  file=sys.stderr)
            import base64
            cdp = page.context.new_cdp_session(page)
            data = cdp.send("Page.captureScreenshot", {"format": "png"})["data"]
            path.write_bytes(base64.b64decode(data))
            cdp.detach()

    failed = False
    report = {}
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            print(f"✗ browser unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        ctx = browser.new_context(viewport={"width": canvas_w, "height": canvas_h})
        if not args.allow_remote:
            # F-311: deck 资产应当本地化(R-SELF-CONTAINED);外部请求只会拖慢/挂死
            # (远程 iframe 让 load 与 fonts.ready 永不触发)。默认全拦,要看远程内容
            # 用 --allow-remote。
            ctx.route("**/*", lambda r: r.abort()
                      if r.request.url.startswith(("http://", "https://")) else r.continue_())
        page = ctx.new_page()
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
            _shot(page, out_dir / f"{key}_mid.png")
            page.wait_for_timeout(max(0, args.settle_ms - args.mid_ms))
            _shot(page, out_dir / f"{key}_settled.png")
            res = page.evaluate(assert_js, [key, args.assert_class, args.transient_class])
            if args.click_selector:
                interaction = {
                    "clickSelector": args.click_selector,
                    "closeSelector": args.close_selector,
                    "clickedScreenshot": None,
                    "closedScreenshot": None,
                    "error": None,
                }
                try:
                    current = page.locator(".slide-frame.is-current .slide")
                    trigger = current.locator(args.click_selector).first
                    if trigger.count() == 0:
                        raise RuntimeError(
                            f"click selector not found in current slide: {args.click_selector}")
                    trigger.click(timeout=5000)
                    page.wait_for_timeout(args.click_wait_ms)
                    clicked_path = out_dir / f"{key}_clicked.png"
                    _shot(page, clicked_path)
                    interaction["clickedScreenshot"] = str(clicked_path)
                    if args.close_selector:
                        closer = current.locator(args.close_selector).first
                        if closer.count() == 0:
                            raise RuntimeError(
                                "close selector not found in current slide: "
                                f"{args.close_selector}")
                        closer.click(timeout=5000)
                        page.wait_for_timeout(args.click_wait_ms)
                        closed_path = out_dir / f"{key}_closed.png"
                        _shot(page, closed_path)
                        interaction["closedScreenshot"] = str(closed_path)
                except Exception as exc:  # interaction failures are page failures, not env failures
                    interaction["error"] = str(exc)
                res["interaction"] = interaction
            report[key] = res
            ok = (not res.get("error") and not res.get("notSettled")
                  and not res.get("transientVisible") and not res.get("overflow")
                  and not (res.get("interaction") or {}).get("error"))
            if not ok:
                failed = True
            paths = [f"{key}_mid.png", f"{key}_settled.png"]
            if args.click_selector:
                paths.append(f"{key}_clicked.png")
            if args.close_selector:
                paths.append(f"{key}_closed.png")
            print(f"{'✓' if ok else '✗'} {key}  →  {out_dir}/" + "  ".join(paths))
        browser.close()

    print(json.dumps(report, ensure_ascii=False, indent=1))
    if failed:
        print("✗ settle assertions failed — 修终值/both/delay,别交付(motion-system §3.5)",
              file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
