#!/usr/bin/env python3
"""F-285 · Publisher post-publish self-check (last-mile delivery verification).

The publisher's last mile ends when a deck is live behind a final URL (Magic
Page / a Cloudflare viewer / feishusolution). Nothing today re-opens that URL
as the *audience* would and confirms the bytes actually survived the trip:
broken links, 404'd assets, a font that quietly fell back, or a page that
renders visibly differently from the local render all slip through (see F-76:
icons 404'd only after publish).

This module is a standalone, independently-callable check. Inputs:

    local   — the local rendered product (a dir holding index.html, or an .html
              file). This is the ground truth the audience is supposed to see.
    remote  — the final published URL (https://..., or — for local testing —
              a file:// URL or a http://127.0.0.1 server serving a copy).

It opens BOTH with one Playwright/Chromium process and two isolated contexts,
captures local and remote concurrently, and on the REMOTE side additionally:

  1. collects failed network requests (404 / blocked / DNS) — a "broken link"
     red card. This is the dimension that has no validator: validate.py checks
     the local bytes, never what the receiving server actually serves.
  2. reads the *effective* font-family of each slide's primary text and flags a
     fallback to a generic/serif/sans face where the local render used a real
     loaded face — the "font silently fell back" red card.

It then pairs the two captures by slide key and computes a per-slide visual
difference; a page that drifts past the threshold is a red card.

VISUAL DIFF ALGORITHM (deliberately the same family as
``log-tool/deck-log.py``'s ``diff`` subcommand so behaviour is consistent and
already battle-tested):

  * Pillow present  → perceptual hash (aHash 8×8 + dHash 8×8, pure-Pillow
    grayscale resize — no third-party hash lib, no numpy) for robustness to
    tiny render jitter, PLUS a down-sampled pixel-diff ratio (both images to
    32×32 grayscale, count cells whose grayscale delta exceeds DELTA). The
    combined ratio is ``max(phash, pixel)`` — either channel calling it changed
    counts as changed.
  * Pillow absent   → pure-stdlib byte compare (same bytes → 0, different → 1),
    flagged ``byte``. Never crashes.

A non-zero exit (and ``ok: False`` in the JSON / report) is the RED CARD.

Why no end-to-end real-publish test here: a true post-publish run needs a live
authenticated session against Magic Page / the Cloudflare viewer, which this
environment cannot reach. So the publish step itself stays documented in
publisher SKILL.md, while this module's *logic* (broken-link detection, font
fallback, visual diff, thresholding) is fully local-testable by pointing
``--remote`` at a file:// / local-http copy of the local product (optionally a
copy with one page altered, or one asset removed) and asserting the right red
cards fire.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

DESIGN_W, DESIGN_H = 1920, 1080

# Visual-diff knobs — kept identical to log-tool/deck-log.py so a page that
# deck-log's `diff` would call changed is the same page this self-check flags.
DIFF_PIXEL_GRID = 32        # down-sample to GRID×GRID grayscale before per-cell compare
DIFF_PIXEL_DELTA = 24       # per-cell grayscale delta (0..255) to count a cell as changed
DEFAULT_DIFF_THRESHOLD = 0.06   # >=6% combined per-slide diff → red card (publish drift)
DEFAULT_PAGES = 3           # how many leading slides to verify (cheap, catches the worst)
IFRAME_SETTLE_MS = 1200     # give visible iframe demos time to leave about:blank before screenshot
REMOTE_REPROBE_TIMEOUT = 8  # seconds; used only to de-noise transient script/document aborts

# Generic CSS font families: if the remote's *effective* font resolves to one of
# these while the local render used a real named face, the web font / @font-face
# did not load on the server — a silent fallback the audience sees as wrong type.
_GENERIC_FAMILIES = {
    "serif", "sans-serif", "monospace", "cursive", "fantasy",
    "system-ui", "ui-serif", "ui-sans-serif", "ui-monospace", "ui-rounded",
    "-apple-system", "blinkmacsystemfont",
}
# Common last-resort fallbacks a browser substitutes when the intended face is
# missing. Seeing one of these on the remote where the local used a deck face is
# a fallback signal even when it is technically a named family.
_FALLBACK_FACE_HINTS = {
    "times", "times new roman", "georgia",          # serif last-resorts
    "arial", "helvetica", "helvetica neue",         # sans last-resorts
    "courier", "courier new",                       # mono last-resorts
    "pingfang sc", "heiti sc", "stheiti", "songti sc",  # macOS CJK system faces
    "microsoft yahei", "simsun", "simhei",          # windows CJK system faces
    "noto sans cjk sc", "wenquanyi micro hei",      # linux CJK system faces
}


# --------------------------------------------------------------------------- io
def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def resolve_local_html(local: Path) -> Path:
    """A dir → its index.html; a file → itself. Raises if not a usable .html."""
    local = local.expanduser().resolve()
    if local.is_dir():
        cand = local / "index.html"
        if not cand.is_file():
            raise SystemExit(f"self-check: no index.html under local dir {local}")
        return cand
    if not local.is_file():
        raise SystemExit(f"self-check: local artifact not found: {local}")
    if local.suffix.lower() not in {".html", ".htm"}:
        raise SystemExit(f"self-check: expected .html/.htm local artifact, got {local}")
    return local


def normalize_remote(remote: str) -> str:
    """Accept a real URL as-is; accept a bare local path as a file:// URL so the
    same code path tests against a local copy without a server."""
    raw = (remote or "").strip()
    if not raw:
        raise SystemExit("self-check: --remote URL is required")
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https", "file"}:
        return raw
    p = Path(raw).expanduser()
    if p.is_dir():
        p = p / "index.html"
    if not p.exists():
        raise SystemExit(f"self-check: --remote is not a URL and no such local path: {raw}")
    return p.resolve().as_uri()


# ---------------------------------------------------------------- perceptual hash
# (algorithm mirrors log-tool/deck-log.py; duplicated rather than imported so this
#  check has no dependency on a hyphen-named CLI module / its argv surface.)
def have_pillow() -> bool:
    try:
        import PIL  # noqa: F401
        return True
    except Exception:
        return False


def _gray_px(img, w: int, h: int) -> list[int]:
    return list(img.convert("L").resize((w, h)).tobytes())


def _ahash_bits(img) -> int:
    px = _gray_px(img, 8, 8)
    avg = sum(px) / len(px)
    bits = 0
    for i, v in enumerate(px):
        if v > avg:
            bits |= (1 << i)
    return bits


def _dhash_bits(img) -> int:
    px = _gray_px(img, 9, 8)
    bits = 0
    k = 0
    for row in range(8):
        base = row * 9
        for col in range(8):
            if px[base + col] < px[base + col + 1]:
                bits |= (1 << k)
            k += 1
    return bits


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _phash_diff_ratio(img_a, img_b) -> float:
    d = _hamming(_ahash_bits(img_a), _ahash_bits(img_b)) + \
        _hamming(_dhash_bits(img_a), _dhash_bits(img_b))
    return d / 128.0


def _pixel_diff_ratio(img_a, img_b) -> float:
    n = DIFF_PIXEL_GRID
    ga = _gray_px(img_a, n, n)
    gb = _gray_px(img_b, n, n)
    changed = sum(1 for x, y in zip(ga, gb) if abs(x - y) > DIFF_PIXEL_DELTA)
    return changed / float(n * n)


def _byte_diff(path_a: Path, path_b: Path) -> tuple[float, str]:
    same = path_a.stat().st_size == path_b.stat().st_size and \
        path_a.read_bytes() == path_b.read_bytes()
    return (0.0 if same else 1.0), "byte"


def image_diff(path_a: Path, path_b: Path) -> tuple[float, str]:
    """Combined per-image diff ratio (0..1) + method tag. Pillow → max(phash,
    pixel); else (or on decode failure) → byte compare. Never crashes."""
    if have_pillow():
        try:
            from PIL import Image
            with Image.open(path_a) as ia, Image.open(path_b) as ib:
                ia.load(); ib.load()
                ph = _phash_diff_ratio(ia, ib)
                pix = _pixel_diff_ratio(ia, ib)
            return max(ph, pix), "phash+pixel"
        except Exception:
            return _byte_diff(path_a, path_b)
    return _byte_diff(path_a, path_b)


# ------------------------------------------------------------------- font logic
def _primary_face(font_family: str) -> str:
    """The first concrete family token from a computed font-family string."""
    for part in (font_family or "").split(","):
        tok = part.strip().strip("'\"").lower()
        if tok:
            return tok
    return ""


def font_fell_back(local_family: str, remote_family: str) -> bool:
    """True when the remote's effective primary face looks like a fallback the
    browser substituted because the intended (local) face did not load.

    Conservative: only fires when the local side used a REAL named face (not a
    generic) AND the remote's primary face is generic, a known last-resort
    substitute, or simply differs from the local primary face. If local itself
    already resolved to a generic, there is nothing to fall back FROM."""
    lf = _primary_face(local_family)
    rf = _primary_face(remote_family)
    if not lf or not rf:
        return False
    if lf in _GENERIC_FAMILIES:
        return False                       # local had no real face to lose
    if rf in _GENERIC_FAMILIES:
        return True                        # remote collapsed to a generic
    if rf in _FALLBACK_FACE_HINTS and lf not in _FALLBACK_FACE_HINTS:
        return True                        # remote substituted a last-resort face
    return rf != lf                        # remote rendered a different concrete face


# --------------------------------------------------------------- browser capture
# Slide enumeration / show-one-slide scripts mirror log-tool/deck-log.py so this
# check sees the same per-slide framing the snapshot/diff tooling does.
_SLIDE_META_JS = r"""
() => {
  const frames = [...document.querySelectorAll('.slide-frame')];
  return frames.map((f, i) => {
    const s = f.querySelector('.slide');
    let face = '';
    if (s) {
      const probe = s.querySelector('h1,h2,.title-zh,.lede,p,li') || s;
      face = getComputedStyle(probe).fontFamily || '';
    }
    return {
      idx: i + 1,
      key: (s && (s.getAttribute('data-slide-key') || s.id)) || ('slide-' + (i + 1)),
      layout: (s && s.getAttribute('data-layout')) || '',
      face: face,
    };
  });
}
"""

_SHOW_SLIDE_JS = r"""
(i) => {
  const frames = [...document.querySelectorAll('.slide-frame')];
  frames.forEach((f, j) => f.classList.toggle('is-current', j === i));
  const s = frames[i] && frames[i].querySelector('.slide');
  if (s) s.style.setProperty('--fs-scale', '1');
  const deck = document.querySelector('.deck');
  if (deck) deck.setAttribute('data-nav-armed', '');
}
"""


async def _deck_scope(page):
    """Return the Page/Frame that actually contains the deck.

    Magic Page may wrap the published HTML in an internal frame. The audience
    still sees the deck, but querying only the top document yields zero slides.
    """
    try:
        if await page.query_selector(".slide-frame"):
            return page
    except Exception:
        pass
    for frame in page.frames:
        try:
            if await frame.query_selector(".slide-frame"):
                return frame
        except Exception:
            continue
    return page


async def _slide_iframe_count(scope, slide_idx: int) -> int:
    try:
        return int(await scope.evaluate(
            """(i) => {
              const frames = [...document.querySelectorAll('.slide-frame')];
              const s = frames[i] && frames[i].querySelector('.slide');
              return s ? s.querySelectorAll('iframe').length : 0;
            }""",
            slide_idx,
        ) or 0)
    except Exception:
        return 0


async def _wait_for_current_slide_iframes(page, scope, slide_idx: int) -> None:
    """Let iframe-heavy slides settle before screenshotting.

    Magic Page can wrap iframes through its own router and Playwright may switch
    slides faster than the child document paints. A short wait only on iframe
    slides avoids false black-frame diffs without slowing simple decks.
    """
    if await _slide_iframe_count(scope, slide_idx) <= 0:
        return
    try:
        await page.wait_for_timeout(IFRAME_SETTLE_MS)
    except Exception:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=2_500)
    except Exception:
        pass


async def _capture_side_with_browser(
    browser,
    uri: str,
    out_dir: Path,
    *,
    pages: int,
    collect_requests: bool,
) -> dict[str, Any]:
    """Capture one side inside its own isolated browser context.

    The caller owns the browser so local and remote can share one Chromium
    process while keeping cookies, storage, service workers and failures fully
    isolated. This coroutine is safe to run under asyncio.gather().
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    failed: list[dict[str, Any]] = []
    slides: list[dict[str, Any]] = []
    ctx = None
    try:
        ctx = await browser.new_context(
            viewport={"width": DESIGN_W, "height": DESIGN_H},
            device_scale_factor=1,
        )
        page = await ctx.new_page()
        if collect_requests:
            page.on("requestfailed", lambda req: failed.append({
                "url": req.url,
                "method": req.method,
                "resource_type": req.resource_type,
                "failure": (req.failure or "request failed"),
            }))

            def _on_response(resp):
                try:
                    if resp.status >= 400:
                        failed.append({
                            "url": resp.url,
                            "method": resp.request.method,
                            "resource_type": resp.request.resource_type,
                            "failure": f"HTTP {resp.status}",
                            "status": resp.status,
                        })
                except Exception:
                    pass

            page.on("response", _on_response)
        await page.goto(uri, wait_until="domcontentloaded", timeout=60_000)
        for awaitable in (
            page.wait_for_load_state("load", timeout=4_000),
            page.evaluate("() => Promise.race([(document.fonts && document.fonts.ready) || Promise.resolve(), new Promise(r => setTimeout(r, 2000))])"),
            page.wait_for_function("() => document.querySelector('.deck[data-js-ready]')", timeout=5_000),
        ):
            try:
                await awaitable
            except Exception:
                pass
        scope = page
        for _ in range(20):
            scope = await _deck_scope(page)
            try:
                if await scope.query_selector(".slide-frame"):
                    break
            except Exception:
                pass
            await page.wait_for_timeout(250)
        try:
            await scope.evaluate("() => { const d=document.querySelector('.deck'); if(d) d.setAttribute('data-mode','present'); }")
        except Exception:
            pass
        await page.wait_for_timeout(300)
        meta = await scope.evaluate(_SLIDE_META_JS)
        meta = meta[: max(0, pages)] if pages is not None else meta
        for m in meta:
            try:
                await scope.evaluate(_SHOW_SLIDE_JS, m["idx"] - 1)
                await page.wait_for_timeout(350)
                await _wait_for_current_slide_iframes(page, scope, m["idx"] - 1)
                fn = out_dir / f"s{m['idx']:02d}.png"
                await page.screenshot(
                    path=str(fn),
                    clip={"x": 0, "y": 0, "width": DESIGN_W, "height": DESIGN_H},
                )
                m["png"] = str(fn)
            except Exception as exc:
                m["png"] = ""
                m["capture_error"] = str(exc)
            slides.append(m)
        return {"ok": True, "slides": slides, "failed_requests": failed}
    except Exception as exc:  # browser/navigation faults degrade to a reported skip
        return {
            "ok": False,
            "reason": str(exc),
            "slides": slides,
            "failed_requests": failed,
        }
    finally:
        if ctx is not None:
            try:
                await ctx.close()
            except Exception:
                pass


def _capture_many(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Capture one or more decks with one Chromium and one context per deck."""
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return [
            {"ok": False, "reason": "playwright not installed", "slides": [], "failed_requests": []}
            for _ in requests
        ]

    async def _run() -> list[dict[str, Any]]:
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=True)
                try:
                    # asyncio.gather overlaps local/remote navigation, font
                    # settling and screenshots. Context isolation prevents the
                    # local file from sharing storage/session state with Magic.
                    return list(await asyncio.gather(*[
                        _capture_side_with_browser(browser, **request)
                        for request in requests
                    ]))
                finally:
                    await browser.close()
        except Exception as exc:
            return [
                {"ok": False, "reason": str(exc), "slides": [], "failed_requests": []}
                for _ in requests
            ]

    return asyncio.run(_run())


def capture_side(uri: str, out_dir: Path, *, pages: int, collect_requests: bool) -> dict[str, Any]:
    """Backward-compatible single-side capture using the shared-browser core."""
    return _capture_many([{
        "uri": uri,
        "out_dir": out_dir,
        "pages": pages,
        "collect_requests": collect_requests,
    }])[0]


def capture_pair(
    local_uri: str,
    local_out: Path,
    remote_uri: str,
    remote_out: Path,
    *,
    pages: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Capture local and remote concurrently in two isolated contexts."""
    captures = _capture_many([
        {
            "uri": local_uri,
            "out_dir": local_out,
            "pages": pages,
            "collect_requests": False,
        },
        {
            "uri": remote_uri,
            "out_dir": remote_out,
            "pages": pages,
            "collect_requests": True,
        },
    ])
    return captures[0], captures[1]


# ------------------------------------------------------------------ comparison
def _is_magic_probe_noise(req: dict[str, Any]) -> bool:
    """Magic shell probes that do not affect what the audience sees."""
    parsed = urlparse(req.get("url") or "")
    if parsed.netloc != "magic.solutionsuite.cn":
        return False
    if parsed.path == "/api/me":
        return True
    if parsed.path.endswith("/.image-slots.state.json"):
        return True
    return False


def _reprobe_url_ok(url: str) -> bool:
    """Best-effort reachability check for transient browser failures.

    Only used to de-noise requestfailed events such as iframe navigation aborts
    or one-off script ERR_FAILED records. It never turns an HTTP>=400 response
    green; those have an explicit status and remain red-card evidence.
    """
    parsed = urlparse(url or "")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    headers = {"User-Agent": "feishu-deck-h5-publisher-self-check/1.0"}
    for method in ("HEAD", "GET"):
        try:
            req = Request(url, method=method, headers=headers)
            with urlopen(req, timeout=REMOTE_REPROBE_TIMEOUT) as resp:  # nosec - publisher verifies user-provided URLs
                if 200 <= int(resp.status) < 400:
                    return True
        except Exception:
            continue
    return False


def _is_transient_reprobe_candidate(req: dict[str, Any]) -> bool:
    if "status" in req:
        return False
    rt = (req.get("resource_type") or "").lower()
    failure = (req.get("failure") or "").upper()
    if "ERR_ABORTED" in failure and rt == "document":
        return True
    if "ERR_FAILED" in failure and rt == "script":
        return True
    return False


def _is_asset_failure(req: dict[str, Any]) -> bool:
    """A failed request that actually breaks the page for the audience. Ignore
    aborted analytics/beacon noise; flag anything that is or 404s a real asset."""
    rt = (req.get("resource_type") or "").lower()
    if _is_magic_probe_noise(req):
        return False
    if rt in {"image", "stylesheet", "script", "font", "media", "fetch", "xhr", "document"}:
        return True
    # status-based failures (HTTP>=400) are real regardless of type
    return "status" in req


def _classify_failed_requests(
    failed_requests: list[dict[str, Any]],
    *,
    reprobe_transient: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (broken, ignored) request rows after Magic/iframe de-noising."""
    broken_unique: list[dict[str, Any]] = []
    ignored: list[dict[str, Any]] = []
    seen: set[str] = set()
    reprobe_cache: dict[str, bool] = {}
    for r in failed_requests:
        if _is_magic_probe_noise(r):
            row = dict(r)
            row["ignored_reason"] = "magic-shell-probe"
            ignored.append(row)
            continue
        if not _is_asset_failure(r):
            continue
        url = r.get("url") or ""
        if reprobe_transient and _is_transient_reprobe_candidate(r):
            if url not in reprobe_cache:
                reprobe_cache[url] = _reprobe_url_ok(url)
            ok = reprobe_cache[url]
            if ok:
                row = dict(r)
                row["ignored_reason"] = "transient-browser-failure-reprobe-ok"
                ignored.append(row)
                continue
        if url not in seen:
            seen.add(url)
            broken_unique.append(r)
    return broken_unique, ignored


def compare_captures(
    local: dict[str, Any],
    remote: dict[str, Any],
    *,
    threshold: float,
    diff_dir: Path | None,
) -> dict[str, Any]:
    """Pair local vs remote slides by key, run the visual diff, and assemble the
    red-card verdict (broken links + font fallback + visual drift). Pure logic —
    no browser — so it is unit-testable on hand-built capture dicts."""
    local_by_key = {s.get("key"): s for s in local.get("slides", []) if s.get("key")}
    remote_by_key = {s.get("key"): s for s in remote.get("slides", []) if s.get("key")}

    # 1. broken links / 404'd assets on the remote (the no-validator dimension)
    broken_unique, ignored_requests = _classify_failed_requests(remote.get("failed_requests", []))

    # 2. font fallback per slide
    font_fallbacks: list[dict[str, Any]] = []
    for key, ls in local_by_key.items():
        rs = remote_by_key.get(key)
        if not rs:
            continue
        if font_fell_back(ls.get("face", ""), rs.get("face", "")):
            font_fallbacks.append({
                "key": key, "idx": rs.get("idx"),
                "local_face": _primary_face(ls.get("face", "")),
                "remote_face": _primary_face(rs.get("face", "")),
            })

    # 3. per-slide visual diff
    changed: list[dict[str, Any]] = []
    unchanged = 0
    missing: list[dict[str, Any]] = []
    method = None
    for key in dict.fromkeys(list(local_by_key) + list(remote_by_key)):
        ls, rs = local_by_key.get(key), remote_by_key.get(key)
        if not ls or not rs:
            missing.append({"key": key, "why": "仅本地有" if ls else "仅远程有"})
            continue
        pa = Path(ls.get("png")) if ls.get("png") else None
        pb = Path(rs.get("png")) if rs.get("png") else None
        if not pa or not pa.exists() or not pb or not pb.exists():
            miss = []
            if not pa or not pa.exists():
                miss.append("本地截图缺失")
            if not pb or not pb.exists():
                miss.append("远程截图缺失")
            missing.append({"key": key, "why": "缺图: " + " / ".join(miss)})
            continue
        ratio, m = image_diff(pa, pb)
        method = m
        row = {"key": key, "idx": rs.get("idx") or ls.get("idx"),
               "ratio": ratio, "pct": round(ratio * 100, 1)}
        if ratio >= threshold:
            changed.append(row)
        else:
            unchanged += 1
        if diff_dir is not None:
            diff_dir.mkdir(parents=True, exist_ok=True)
    changed.sort(key=lambda r: r["ratio"], reverse=True)

    # A real visual comparison happened only for paired slides that produced two
    # screenshots (counted in `changed` + `unchanged`). If NOTHING compared (all
    # slides went to `missing` — unpaired keys or capture failures) and there is
    # no broken-link evidence either, the self-check verified nothing on the
    # visual/font dimensions and must NOT report green. (subskill-4)
    compared = len(changed) + unchanged
    no_comparison = (compared == 0) and not broken_unique

    ok = (not broken_unique and not font_fallbacks and not changed) and not no_comparison
    reasons: list[str] = []
    if broken_unique:
        reasons.append(f"{len(broken_unique)} 个资源在发布物上断链/404")
    if font_fallbacks:
        reasons.append(f"{len(font_fallbacks)} 页字体在发布物上回落")
    if changed:
        reasons.append(f"{len(changed)} 页与本地渲染视觉差异超阈值({threshold*100:.0f}%)")
    if no_comparison:
        reasons.append("自检未产生任何可比对的页面(本地/远程页 key 不匹配或截图全部失败)")

    return {
        "ok": ok,
        "method": method or ("byte" if not have_pillow() else "phash+pixel"),
        "threshold": threshold,
        "broken_requests": broken_unique,
        "ignored_requests": ignored_requests,
        "font_fallbacks": font_fallbacks,
        "visual_changed": changed,
        "visual_unchanged": unchanged,
        "missing": missing,
        "reasons": reasons,
    }


def write_report(out_dir: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    json_path = out_dir / "publish-self-check.json"
    md_path = out_dir / "PUBLISH_SELF_CHECK.md"
    _write_json(json_path, payload)
    verdict = payload.get("verdict") or {}
    lines = [
        "# Publish Self-Check (F-285)",
        "",
        f"- ok: {payload.get('ok')}",
        f"- local: `{payload.get('local')}`",
        f"- remote: {payload.get('remote')}",
        f"- pages_checked: {payload.get('pages')}",
        f"- method: {verdict.get('method')}",
        f"- threshold: {verdict.get('threshold')}",
        "",
    ]
    broken = verdict.get("broken_requests") or []
    if broken:
        lines.append(f"## 🔴 断链 / 404 ({len(broken)})")
        for r in broken[:20]:
            lines.append(f"- `{r.get('failure')}` · {r.get('resource_type')} · {r.get('url')}")
        lines.append("")
    ignored = verdict.get("ignored_requests") or []
    if ignored:
        lines.append(f"## 降噪请求 ({len(ignored)})")
        for r in ignored[:20]:
            lines.append(f"- `{r.get('ignored_reason')}` · `{r.get('failure')}` · {r.get('resource_type')} · {r.get('url')}")
        lines.append("")
    fonts = verdict.get("font_fallbacks") or []
    if fonts:
        lines.append(f"## 🔴 字体回落 ({len(fonts)})")
        for f in fonts:
            lines.append(f"- 第{f.get('idx')}页 `{f.get('key')}`: 本地 {f.get('local_face')} → 远程 {f.get('remote_face')}")
        lines.append("")
    changed = verdict.get("visual_changed") or []
    if changed:
        lines.append(f"## 🔴 视觉差异超阈值 ({len(changed)})")
        for r in changed:
            lines.append(f"- {r['pct']:.1f}%  第{r.get('idx')}页  `{r['key']}`")
        lines.append("")
    if verdict.get("missing"):
        lines.append("## 配对缺失")
        for r in verdict["missing"]:
            lines.append(f"- `{r.get('key')}` · {r.get('why')}")
        lines.append("")
    if payload.get("ok"):
        lines.append("✓ 发布物与本地渲染一致,无断链 / 字体回落 / 视觉漂移。")
    else:
        lines.append("✗ 红牌:" + "; ".join(verdict.get("reasons") or []))
    lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return json_path, md_path


def run_self_check(
    *,
    local: Path,
    remote: str,
    out_dir: Path,
    pages: int = DEFAULT_PAGES,
    threshold: float = DEFAULT_DIFF_THRESHOLD,
) -> dict[str, Any]:
    """End-to-end self-check. Returns the payload (also written to out_dir)."""
    local_html = resolve_local_html(local)
    remote_uri = normalize_remote(remote)
    out_dir = out_dir.expanduser().resolve()

    local_cap, remote_cap = capture_pair(
        local_html.as_uri(),
        out_dir / "self-check" / "local",
        remote_uri,
        out_dir / "self-check" / "remote",
        pages=pages,
    )

    if not local_cap.get("ok") or not remote_cap.get("ok"):
        reason = local_cap.get("reason") or remote_cap.get("reason") or "capture failed"
        payload = {
            "ok": False,
            "skipped": True,
            "local": str(local_html),
            "remote": remote_uri,
            "pages": pages,
            "reason": f"self-check could not run a browser ({reason}); "
                      "install playwright + chromium to enable post-publish verification",
            "verdict": {"method": "n/a", "threshold": threshold,
                        "broken_requests": [], "ignored_requests": [], "font_fallbacks": [],
                        "visual_changed": [], "visual_unchanged": 0, "missing": [], "reasons": []},
        }
        write_report(out_dir, payload)
        return payload

    verdict = compare_captures(local_cap, remote_cap, threshold=threshold, diff_dir=None)
    payload = {
        "ok": bool(verdict["ok"]),
        "skipped": False,
        "local": str(local_html),
        "remote": remote_uri,
        "pages": pages,
        "verdict": verdict,
    }
    write_report(out_dir, payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local", required=True, type=Path,
                    help="local rendered product: a dir holding index.html, or an .html file")
    ap.add_argument("--remote", required=True,
                    help="final published URL (https://...); a file:// URL or local path also works for testing")
    ap.add_argument("--out", type=Path, default=Path.cwd(),
                    help="directory to write publish-self-check.json / PUBLISH_SELF_CHECK.md and screenshots")
    ap.add_argument("--pages", type=int, default=DEFAULT_PAGES,
                    help=f"how many leading slides to verify (default {DEFAULT_PAGES})")
    ap.add_argument("--threshold", type=float, default=DEFAULT_DIFF_THRESHOLD,
                    help=f"per-slide combined diff ratio that red-cards a page (default {DEFAULT_DIFF_THRESHOLD})")
    ap.add_argument("--allow-skip", action="store_true",
                    help="exit 0 even if a browser is unavailable (self-check could not run); "
                         "default treats an un-runnable check as a non-zero soft red card")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = run_self_check(
        local=args.local,
        remote=args.remote,
        out_dir=args.out,
        pages=args.pages,
        threshold=args.threshold,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    if payload.get("skipped"):
        return 0 if args.allow_skip else 3
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
