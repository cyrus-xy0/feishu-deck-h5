"""W4 (iteration-loop) · pre-write static lint for authored slide fragments.

Catches, BEFORE the fragment is written into deck.json, the classes of
first-render gate failures that are textually detectable (measured in the
FWD-deck session: ~10 first-render blocks, ≥7 of them in these categories):

  L-TYPESCALE   font-size px off the 4-tier ladder ∪ hero whitelist
  L-DUAL-ANCHOR position:absolute with BOTH top: and bottom: (or inset shorthand)
  L-P50-INLINE  base64 images inside <style>/custom_css approaching the 250KB cap
  L-CHROME-16   16px body text on a non-chrome class
  L-BIG-URL     local url() raster reference that should go through add-asset

This is a SUBSET of the render gate, not a replacement — geometry still needs
the browser. Constants are PARSED from assets/audits.js (single source); the
embedded fallbacks below are only used if that parse fails.
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDITS_JS = HERE.parent / "assets" / "audits.js"

LADDER = {16, 24, 28, 48}
# Fallbacks — overwritten by _load_from_audits() when audits.js is readable.
_FALLBACK_HERO_SIZES = {30, 36, 38, 40, 44, 52, 56, 64, 72, 88, 92, 96, 100,
                        132, 160, 240, 312}
_FALLBACK_CHROME = ["pageno", "footnote", "source", "attrib", "copyright",
                    "wordmark", "contact", "eyebrow", "pill", "tag", "chip",
                    "badge", "demo-tag", "demo-label", "caption-meta", "cite"]

P50_CAP = 250 * 1024          # hard cap (validate.py P50)
P50_WARN = 100 * 1024
BIG_URL = 500 * 1024


def _load_from_audits():
    """Parse VIS_HERO_SIZES + VIS_CONTENT_CHROME_CLASSES out of audits.js so the
    lint never drifts from the gate. Returns (hero_sizes, chrome_classes)."""
    try:
        js = AUDITS_JS.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"VIS_HERO_SIZES\s*=\s*new Set\(\[([^\]]+)\]", js)
        hero = {int(x) for x in re.findall(r"\d+", m.group(1))} if m else None
        m = re.search(r"VIS_CONTENT_CHROME_CLASSES\s*=\s*\[([^\]]+)\]", js)
        chrome = re.findall(r"'([^']+)'", m.group(1)) if m else None
        if hero and chrome:
            return hero, chrome
    except Exception:
        pass
    return set(_FALLBACK_HERO_SIZES), list(_FALLBACK_CHROME)


HERO_SIZES, CHROME_CLASSES = _load_from_audits()


def _iter_rules(css: str):
    """Yield (selector, body) for each top-level rule. Tolerant of @media
    nesting (recurses one level) and comments."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    depth, buf, sel, out = 0, [], "", []
    i = 0
    while i < len(css):
        c = css[i]
        if c == "{":
            if depth == 0:
                sel = "".join(buf).strip(); buf = []
            else:
                buf.append(c)
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                body = "".join(buf); buf = []
                if sel.startswith("@") and "{" in body:   # @media block → recurse
                    out.extend(_iter_rules(body))
                else:
                    out.append((sel, body))
            else:
                buf.append(c)
        else:
            buf.append(c)
        i += 1
    return out


def _style_blocks(html: str):
    """(selector-less) style="..." attrs as pseudo-rules + embedded <style> css."""
    inline = [(f"<inline style #{i+1}>", m.group(1))
              for i, m in enumerate(re.finditer(r'style="([^"]*)"', html))]
    embedded = "\n".join(m.group(1) for m in
                         re.finditer(r"<style[^>]*>(.*?)</style>", html, re.S))
    return inline, embedded


def lint_fragment(html: str = "", css: str = "") -> list[dict]:
    """Return findings: [{sev:'err'|'warn', code, msg}]."""
    findings = []
    inline, embedded = _style_blocks(html or "")
    all_rules = (_iter_rules(css or "") + _iter_rules(embedded) + inline)
    frag_all = (html or "") + "\n" + (css or "")
    has_ts_optout = "data-allow-typescale" in frag_all
    has_da_optout = "data-allow-dual-anchor" in frag_all

    for sel, body in all_rules:
        # L-TYPESCALE ---------------------------------------------------------
        for m in re.finditer(r"font(?:-size)?\s*:\s*[^;]*?(\d+(?:\.\d+)?)px", body):
            px = round(float(m.group(1)))
            if px >= 8 and px not in LADDER and px not in HERO_SIZES:
                if not has_ts_optout:
                    findings.append(dict(
                        sev="err", code="L-TYPESCALE",
                        msg=f"{sel}: font-size {px}px is off the ladder "
                            f"{sorted(LADDER)} ∪ hero whitelist — snap it, or put "
                            f"data-allow-typescale on a hero ancestor."))
        # L-DUAL-ANCHOR -------------------------------------------------------
        if re.search(r"position\s*:\s*absolute", body) and not has_da_optout:
            top = re.search(r"(?<![a-z-])top\s*:\s*(?!auto)", body)
            bot = re.search(r"(?<![a-z-])bottom\s*:\s*(?!auto)", body)
            inset = re.search(r"(?<![a-z-])inset\s*:", body)
            if (top and bot) or inset:
                findings.append(dict(
                    sev="err", code="L-DUAL-ANCHOR",
                    msg=f"{sel}: position:absolute with both top+bottom (or "
                        f"inset shorthand) — height stretches to the parent "
                        f"(R-VIS-ABSPOS-DUAL-ANCHOR). Anchor ONE edge + size, "
                        f"or data-allow-dual-anchor for a true overlay."))
        # L-CHROME-16 ---------------------------------------------------------
        for m in re.finditer(r"font(?:-size)?\s*:\s*[^;]*?(?<![\d.])16px", body):
            sl = sel.lower()
            if not any(c in sl for c in CHROME_CLASSES):
                findings.append(dict(
                    sev="warn", code="L-CHROME-16",
                    msg=f"{sel}: 16px is the chrome tier — fine for "
                        f"eyebrow/tag/pill etc.; body copy ≥8 chars on this "
                        f"selector will trip R-VIS-BODY-FLOOR."))
            break  # one note per rule is enough

    # L-P50-INLINE ------------------------------------------------------------
    style_css = (css or "") + "\n" + embedded
    b64 = sum(len(m.group(0)) for m in
              re.finditer(r"data:image/[a-z+]+;base64,[A-Za-z0-9+/=]+", style_css))
    approx = int(b64 * 0.75)
    if approx >= P50_CAP:
        findings.append(dict(
            sev="err", code="L-P50-INLINE",
            msg=f"~{approx//1024}KB of base64 image data inside <style>/custom_css "
                f"≥ the 250KB P50 hard cap — move images to <img src> in the "
                f"body, or better: deck-cli add-asset → reference by path."))
    elif approx >= P50_WARN:
        findings.append(dict(
            sev="warn", code="L-P50-INLINE",
            msg=f"~{approx//1024}KB of base64 in styles — approaching the 250KB "
                f"P50 cap; prefer add-asset + url path."))

    # L-BIG-URL ---------------------------------------------------------------
    for m in re.finditer(r"""url\(\s*['"]?(?!data:|https?:)([^'")]+)""", frag_all):
        p = Path(m.group(1))
        try:
            if p.is_file() and p.stat().st_size > BIG_URL:
                findings.append(dict(
                    sev="warn", code="L-BIG-URL",
                    msg=f"url({p.name}) is {p.stat().st_size//1024}KB — run "
                        f"deck-cli add-asset to compress + place it."))
        except OSError:
            pass
    return findings


def format_findings(findings: list[dict]) -> str:
    icon = {"err": "✗", "warn": "⚠"}
    return "\n".join(f"  {icon[f['sev']]} [{f['code']}] {f['msg']}" for f in findings)


if __name__ == "__main__":
    import argparse, sys
    ap = argparse.ArgumentParser(description="static pre-write lint for slide fragments")
    ap.add_argument("--html", type=Path)
    ap.add_argument("--css", type=Path)
    a = ap.parse_args()
    fs = lint_fragment(a.html.read_text(encoding="utf-8") if a.html else "",
                       a.css.read_text(encoding="utf-8") if a.css else "")
    if fs:
        print(format_findings(fs))
    errs = [f for f in fs if f["sev"] == "err"]
    print(f"lint-fragment: {len(errs)} error(s), {len(fs)-len(errs)} warning(s)")
    sys.exit(1 if errs else 0)
