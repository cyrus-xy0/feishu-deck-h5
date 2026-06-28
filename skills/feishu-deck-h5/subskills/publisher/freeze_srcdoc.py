#!/usr/bin/env python3
"""Freeze a rendered prototype into script-free HTML for iframe srcdoc fallback.

Use only after live iframe options fail. The output is still HTML inside an
iframe, but it no longer depends on scripts running inside Magic Page's iframe
environment.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

BANNED_DEFAULT = (
    "<script",
    "</script",
    "data:image",
    "blob:",
    "new Blob",
    "createObjectURL",
    "image-slot",
    "__bundler/",
)


def normalize_target(raw: str) -> str:
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https", "file"}:
        return raw
    p = Path(raw).expanduser().resolve()
    if not p.exists():
        raise SystemExit(f"freeze-srcdoc: input not found: {raw}")
    return p.as_uri()


def freeze(
    *,
    target: str,
    out: Path,
    width: int,
    height: int,
    wait_ms: int,
    screenshot: Path | None,
    allow_banned: bool,
) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise SystemExit(f"freeze-srcdoc: playwright unavailable: {exc}") from exc

    uri = normalize_target(target)
    out = out.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if screenshot:
        screenshot = screenshot.expanduser().resolve()
        screenshot.parent.mkdir(parents=True, exist_ok=True)

    failed: list[dict] = []
    bad: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
        page.on("requestfailed", lambda req: failed.append({
            "url": req.url,
            "resource_type": req.resource_type,
            "failure": req.failure or "request failed",
        }))
        page.on("response", lambda resp: bad.append({
            "url": resp.url,
            "status": resp.status,
            "resource_type": resp.request.resource_type,
        }) if resp.status >= 400 else None)
        page.goto(uri, wait_until="domcontentloaded", timeout=60_000)
        if wait_ms > 0:
            page.wait_for_timeout(wait_ms)
        if screenshot:
            page.screenshot(path=str(screenshot), full_page=True)
        html = page.evaluate(
            """() => {
              document.querySelectorAll('script').forEach((s) => s.remove());
              document.querySelectorAll('[data-reactroot]').forEach((n) => n.removeAttribute('data-reactroot'));
              return '<!DOCTYPE html>\\n' + document.documentElement.outerHTML;
            }"""
        )
        browser.close()

    out.write_text(html, encoding="utf-8")
    found = [needle for needle in BANNED_DEFAULT if needle.lower() in html.lower()]
    ok = not bad and not failed and (allow_banned or not found)
    return {
        "ok": ok,
        "input": target,
        "output": str(out),
        "screenshot": str(screenshot) if screenshot else "",
        "bytes": out.stat().st_size,
        "banned_found": found,
        "failed_requests": failed,
        "bad_responses": bad,
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--html", required=True, help="local HTML path, file:// URL, or https:// URL to freeze")
    ap.add_argument("--out", required=True, type=Path, help="script-free HTML output path")
    ap.add_argument("--viewport", default="480x1000", help="browser viewport, WIDTHxHEIGHT (default 480x1000)")
    ap.add_argument("--wait-ms", type=int, default=7000, help="time to wait after DOMContentLoaded (default 7000)")
    ap.add_argument("--screenshot", type=Path, help="optional screenshot of the rendered source before freezing")
    ap.add_argument("--allow-banned", action="store_true", help="do not fail if publish-risk strings remain")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        width_s, height_s = args.viewport.lower().split("x", 1)
        width, height = int(width_s), int(height_s)
    except Exception as exc:
        raise SystemExit("freeze-srcdoc: --viewport must look like 480x1000") from exc
    result = freeze(
        target=args.html,
        out=args.out,
        width=width,
        height=height,
        wait_ms=args.wait_ms,
        screenshot=args.screenshot,
        allow_banned=args.allow_banned,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
