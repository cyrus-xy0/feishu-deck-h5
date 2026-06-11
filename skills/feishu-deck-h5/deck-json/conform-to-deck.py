#!/usr/bin/env python3
"""conform-to-deck.py — F-300: family-drift detector for a page joining an
existing deck (the "adopt a foreign page into a house-styled deck" gap).

The problem this solves (F-300)
-------------------------------
When a foreign / reskinned / freshly-rebuilt page is dropped into a deck that
ALREADY has a settled house style, the new page is faithful to its SOURCE but
divergent from its NEW SIBLINGS. Every divergence then surfaces as a separate
manual feedback round ("change the background", "move the title", "remove the
thing above the title", "fix the body size", "the gray text should be white").

Those are not five arbitrary preferences — they are one rule:

    A page joining a deck must match the conventions of its sibling pages.

And crucially, those conventions are already machine-readable: the sibling pages
ARE the spec. This tool reads the consensus of the sibling raw content pages and
reports, for the page(s) under test, every dimension where it drifts from that
consensus. No template, no whitelist, no design judgement baked in — same
philosophy as `check-distribution.py`: look at what the family agrees on, flag
the outlier. It is the detection half of the conform step; the deterministic
fixes (strip own page-bg / strip pre-title chrome / snap font tiers) are applied
by `--apply` (see "Auto-fix" below); the title-move and the color call stay
report-only because they need DOM rework / a human eye.

The five dimensions (traceable to the five manual rounds that motivated this)
----------------------------------------------------------------------------
  D1  page-background     — does the page set its OWN full-bleed background
                            instead of inheriting the master content-bg the
                            siblings show through?                      [①]
  D2  title-in-header     — is the title in the framework `.header > .title-zh`
                            like the siblings, or in a bespoke title block? [②]
  D3  pre-title chrome    — does the page carry an eyebrow / topbar / page-label
                            ABOVE the title that the siblings don't?      [③]
  D4  font-tier ladder    — are the page's font sizes on the {16,24,28,48}
                            family ladder the siblings sit on?            [④]
  D5  body-text luminance — is the page's body text as bright as the siblings'
                            (vs. source greys that go dim on the master bg)? [⑤]

Consensus, not rules
--------------------
For each dimension we compute the consensus across the sibling raw content pages
(every raw slide EXCEPT cover/section/end and except the page under test). A
dimension only has a verdict when >= 2 siblings agree; with fewer, we report
"insufficient siblings" and skip — a 2-page deck has no family to conform to.

Read-only by default
--------------------
Default run writes nothing: it prints the drift table. `--apply` runs the three
deterministic conforms (D1 page-bg strip, D3 pre-title-chrome strip via a real
HTML parser — never regex DOM surgery, D4 font snap via reconcile-lifted) with a
`.bak-pre-conform-<ts>` backup + optimistic lock; D2/D5 are never auto-applied.

USAGE
-----
    python3 conform-to-deck.py <deck.json>                 # audit every content page
    python3 conform-to-deck.py <deck.json> --page 3        # focus one page (1-based)
    python3 conform-to-deck.py <deck.json> --slide the-shift
    python3 conform-to-deck.py <deck.json> --strict        # exit 1 if any drift
    python3 conform-to-deck.py <deck.json> --apply          # run the D1/D3/D4 conforms

stdlib only (+ _validate_common for the ladder/chrome constants, _css_utils for
the rule iterator, reconcile-lifted for the font-snap single-source-of-truth).
Python 3.10+.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
_ASSETS = HERE.parent / "assets"
for _p in (str(HERE), str(_ASSETS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:
    from _validate_common import _CHROME_CLASS_RE, TYPE_LADDER_PX  # noqa: E402
except Exception:  # pragma: no cover — defensive fallback
    _CHROME_CLASS_RE = re.compile(
        r'\.(?:eyebrow|footnote|pageno|kicker|overline|meta|tag|pill|chip|badge|'
        r'label-small|chrome|source|hint|legend|axis|unit|status)\b|\.ui-[a-z][\w-]*')
    TYPE_LADDER_PX = {16, 24, 28, 48}

from _css_utils import iter_css_rules  # noqa: E402


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_recon = _load("reconcile_lifted", "reconcile-lifted.py")

# ---------------------------------------------------------------------------
# slide helpers
# ---------------------------------------------------------------------------
_NON_CONTENT_RE = re.compile(
    r'\b(cover|section|divider|chapter|agenda|closing|end|thank|title-?slide)\b', re.I)
_STYLE_RE = re.compile(r'<style[^>]*>(.*?)</style>', re.S | re.I)


def slide_html(slide: dict) -> str:
    data = slide.get("data")
    if isinstance(data, dict) and isinstance(data.get("html"), str):
        return data["html"]
    return ""


def is_content_raw(slide: dict) -> bool:
    """A raw slide that participates in the content-page family — excludes the
    cover / section dividers / end which legitimately differ from content pages."""
    if slide.get("layout") != "raw":
        return False
    blob = f"{slide.get('key', '')} {slide.get('screen_label', '')}"
    return not _NON_CONTENT_RE.search(blob)


def _slide_css(slide: dict) -> str:
    """All CSS that styles this slide: custom_css + any inline <style> in html."""
    cc = slide.get("custom_css") or ""
    inline = "\n".join(_STYLE_RE.findall(slide_html(slide)))
    return cc + "\n" + inline


def _nows(s: str) -> str:
    return re.sub(r'\s+', '', s)


# ---------------------------------------------------------------------------
# D1 — page background
# ---------------------------------------------------------------------------
_ROOT_SEL_RE = re.compile(r'\.slide\[data-slide-key="[^"]*"\]\s*$')
_BG_DECL_RE = re.compile(r'\bbackground(?:-color|-image)?\s*:\s*([^;{}]+)', re.I)
_EMPTY_BG = {'transparent', 'none', 'inherit', 'unset', 'initial', 'revert', ''}


def _decl_is_opaque_bg(value: str) -> bool:
    v = value.strip().lower()
    if v in _EMPTY_BG:
        return False
    # `background: none` / a bare color that is transparent → not a real bg.
    if v.startswith('rgba(') and re.search(r',\s*0?\.?0+\s*\)$', v):
        return False
    return True


def _rule_has_opaque_bg(body: str) -> bool:
    return any(_decl_is_opaque_bg(m.group(1)) for m in _BG_DECL_RE.finditer(body))


def _is_fullbleed(body: str) -> bool:
    nb = _nows(body).lower()
    abs_pos = 'position:absolute' in nb or 'position:fixed' in nb
    bleed = ('inset:0' in nb
             or ('top:0' in nb and 'left:0' in nb
                 and 'width:100%' in nb and 'height:100%' in nb))
    return abs_pos and bleed


def sets_own_page_bg(slide: dict) -> tuple[bool, str]:
    """True if the slide paints its own full-bleed background (root `.slide[key]`
    rule, or a full-bleed wrapper element) instead of inheriting the master bg."""
    key = slide.get("key") or ""
    for sel, body in iter_css_rules(_slide_css(slide)):
        for part in sel.split(','):
            part = part.strip()
            is_root = bool(_ROOT_SEL_RE.search(part)) or part == '.slide'
            if (is_root or _is_fullbleed(body)) and _rule_has_opaque_bg(body):
                where = "root .slide rule" if is_root else f"full-bleed `{part[:40]}`"
                return True, where
    return False, ""


# ---------------------------------------------------------------------------
# D2 — title in framework .header
# ---------------------------------------------------------------------------
_HEADER_RE = re.compile(r'class="[^"]*\bheader\b[^"]*"', re.I)


def title_in_header(slide: dict) -> bool:
    html = slide_html(slide)
    return bool(_HEADER_RE.search(html)) and 'title-zh' in html


# ---------------------------------------------------------------------------
# D3 — pre-title chrome (eyebrow / topbar / page-label)
# ---------------------------------------------------------------------------
_PRETITLE_RE = re.compile(
    r'class="[^"]*\b(topbar|eyebrow|kicker|overline|page-?label|slug|page-?meta)\b',
    re.I)


def has_pretitle_chrome(slide: dict) -> tuple[bool, str]:
    m = _PRETITLE_RE.search(slide_html(slide))
    return (True, m.group(1)) if m else (False, "")


# ---------------------------------------------------------------------------
# D4 — font-tier ladder (single source of truth = reconcile-lifted snap policy)
# ---------------------------------------------------------------------------
def offladder_count(slide: dict) -> int:
    """How many font declarations reconcile-lifted WOULD snap to {16,24,28,48}.
    Scans custom_css AND inline <style> (reconcile only scans html <style>, so we
    drive its per-rule snapper directly over every rule that styles this slide)."""
    n = 0
    for sel, body in iter_css_rules(_slide_css(slide)):
        allow_ts = 'allow:typescale' in body
        _, changed = _recon._snap_declarations(body, sel, allow_ts, [])
        n += changed
    return n


# ---------------------------------------------------------------------------
# D5 — body-text luminance
# ---------------------------------------------------------------------------
_COLOR_DECL_RE = re.compile(r'(?<![\w-])color\s*:\s*([^;{}]+)', re.I)
_BG_LUM = 0.04  # approx luminance of the dark master content-bg, for alpha blend


def _parse_color(v: str):
    """Return (r, g, b, alpha) or None. Handles #rgb / #rrggbb / rgb()/rgba()."""
    v = v.strip().lower()
    if v in ('white', '#fff', '#ffffff'):
        return (255, 255, 255, 1.0)
    if v in ('black', '#000', '#000000'):
        return (0, 0, 0, 1.0)
    m = re.fullmatch(r'#([0-9a-f]{3})', v)
    if m:
        h = m.group(1)
        return (int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16), 1.0)
    m = re.fullmatch(r'#([0-9a-f]{6})', v)
    if m:
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
    m = re.match(r'rgba?\(([^)]+)\)', v)
    if m:
        parts = re.split(r'[,/]+', m.group(1).strip())
        try:
            r, g, b = (int(float(parts[i])) for i in range(3))
        except (ValueError, IndexError):
            return None
        a = float(parts[3]) if len(parts) > 3 and parts[3].strip() else 1.0
        return (r, g, b, a)
    return None


def _is_muted_grey(literal: str) -> bool:
    """True if the color is achromatic-ish (a grey, not a brand accent): small
    spread between its max and min RGB channel. Brand blues/teals/oranges have a
    wide spread and are NOT greys, so they're excluded from the muted-grey smell."""
    col = _parse_color(literal)
    if col is None:
        return False
    r, g, b, _ = col
    return (max(r, g, b) - min(r, g, b)) <= 40


def _rel_lum(rgb) -> float:
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(rgb[0]) + 0.7152 * lin(rgb[1]) + 0.0722 * lin(rgb[2])


def _effective_lum(color) -> float:
    """Luminance of the text as it actually reads, blending alpha over the bg."""
    r, g, b, a = color
    return a * _rel_lum((r, g, b)) + (1 - a) * _BG_LUM


def body_text_luminances(slide: dict) -> list[tuple[str, str, float]]:
    """(selector, color-literal, effective-luminance) for every body-ish text
    color this slide declares. Skips chrome selectors, gradient/transparent text,
    var()/currentColor (unresolvable), and obvious SVG fills."""
    out = []
    for sel, body in iter_css_rules(_slide_css(slide)):
        low = sel.lower()
        if _CHROME_CLASS_RE.search(sel) or 'svg' in low or '::' in sel:
            continue
        for m in _COLOR_DECL_RE.finditer(body):
            raw = m.group(1).strip()
            lv = raw.lower()
            if any(t in lv for t in ('transparent', 'inherit', 'currentcolor',
                                     'var(', 'unset', 'initial')):
                continue
            col = _parse_color(raw)
            if col is None:
                continue
            out.append((sel.strip()[:48], raw, _effective_lum(col)))
    return out


# ---------------------------------------------------------------------------
# consensus + verdict
# ---------------------------------------------------------------------------
def _bool_consensus(values: list[bool]):
    """Majority True/False across siblings, or None when tied / < 2 siblings."""
    if len(values) < 2:
        return None
    t = sum(1 for v in values if v)
    f = len(values) - t
    if t == f:
        return None
    return t > f


class Dim:
    def __init__(self, code, label, ask, verdict, page_desc, family_desc, fix):
        self.code, self.label, self.ask = code, label, ask
        self.verdict = verdict          # "match" | "drift" | "n/a"
        self.page_desc, self.family_desc, self.fix = page_desc, family_desc, fix


def assess_page(slide: dict, siblings: list[dict]) -> list[Dim]:
    dims = []

    # D1 page-bg ------------------------------------------------------------
    page_bg, where = sets_own_page_bg(slide)
    sib_bg = [sets_own_page_bg(s)[0] for s in siblings]
    cons = _bool_consensus(sib_bg)
    if cons is None:
        v, fam = "n/a", "insufficient siblings"
    else:
        v = "drift" if page_bg != cons else "match"
        fam = "own bg" if cons else "inherit master bg"
    dims.append(Dim("D1", "page background", "①", v,
                    (f"own bg ({where})" if page_bg else "inherit master bg"),
                    fam, "auto"))

    # D2 title-in-header ----------------------------------------------------
    page_h = title_in_header(slide)
    cons = _bool_consensus([title_in_header(s) for s in siblings])
    if cons is None:
        v, fam = "n/a", "insufficient siblings"
    else:
        v = "drift" if page_h != cons else "match"
        fam = ".header > .title-zh" if cons else "bespoke title block"
    dims.append(Dim("D2", "title placement", "②", v,
                    ".header > .title-zh" if page_h else "bespoke title block",
                    fam, "semi (DOM)"))

    # D3 pre-title chrome ---------------------------------------------------
    page_c, ctype = has_pretitle_chrome(slide)
    cons = _bool_consensus([has_pretitle_chrome(s)[0] for s in siblings])
    if cons is None:
        v, fam = "n/a", "insufficient siblings"
    else:
        v = "drift" if page_c != cons else "match"
        fam = "has eyebrow/topbar" if cons else "no pre-title chrome"
    dims.append(Dim("D3", "pre-title chrome", "③", v,
                    (f"has .{ctype}" if page_c else "none"), fam, "auto"))

    # D4 font ladder --------------------------------------------------------
    page_off = offladder_count(slide)
    sib_off = [offladder_count(s) for s in siblings]
    sib_clean = sum(1 for n in sib_off if n == 0)
    if len(siblings) < 2:
        v, fam = "n/a", "insufficient siblings"
    elif page_off > 0 and sib_clean >= max(2, len(siblings) - sib_clean):
        v, fam = "drift", f"{sib_clean}/{len(siblings)} siblings on ladder"
    else:
        v = "match" if page_off == 0 else "advisory"
        fam = f"{sib_clean}/{len(siblings)} siblings on ladder"
    dims.append(Dim("D4", "font ladder", "④", v,
                    "on ladder" if page_off == 0 else f"{page_off} off-ladder",
                    fam, "auto"))

    # D5 body luminance -----------------------------------------------------
    # ADVISORY ONLY. A color's real readability depends on the LOCAL background
    # (dark text on a light card is fine; the same on the dark master bg is not),
    # which a static deck.json scan cannot resolve. So D5 never hard-fails — it is
    # a high-confidence SMELL: an achromatic mid-grey used as text where the family
    # body is predominantly bright. The authoritative contrast floor lives in the
    # render-time validator (R-VIS-BODY-CONTRAST), which can read the composited bg.
    sib_lums = [lum for s in siblings for _, _, lum in body_text_luminances(s)]
    page_lums = body_text_luminances(slide)
    if len(sib_lums) < 3 or not page_lums:
        v, fam, page_desc = "n/a", "insufficient sibling colors", "—"
    else:
        bright_frac = sum(1 for x in sib_lums if x >= 0.5) / len(sib_lums)
        # muted-grey smell band: achromatic + dim-but-not-near-black. Excludes
        # near-black dark-on-light-card text (L<0.10) and readable light greys.
        smells = [(sel, c, lum) for sel, c, lum in page_lums
                  if _is_muted_grey(c) and 0.10 <= lum <= 0.42]
        if bright_frac >= 0.55 and smells:
            v = "advisory"
            worst = min(smells, key=lambda x: x[2])
            extra = f" +{len(smells) - 1} more" if len(smells) > 1 else ""
            page_desc = f"muted grey {worst[1]} (L={worst[2]:.2f}){extra}"
        else:
            v, page_desc = "match", "no muted-grey body smell"
        fam = f"{bright_frac:.0%} of family body text is bright"
    dims.append(Dim("D5", "body luminance", "⑤", v, page_desc, fam,
                    "judgment (confirm at render)"))

    return dims


# ---------------------------------------------------------------------------
# auto-fix (--apply): the three DETERMINISTIC conforms. D2 (title move) and D5
# (color call) are never auto-applied — they need DOM rework / a human eye.
# ---------------------------------------------------------------------------
_BG_STRIP_RE = re.compile(r'\bbackground(?:-color|-image)?\s*:[^;{}]*;?', re.I)


def _strip_bg_css(css: str) -> tuple[str, int]:
    """Remove background declarations from rules that paint the page itself (root
    `.slide[key]` or a full-bleed opaque wrapper). Preserves every other byte —
    walks via reconcile-lifted's raw-span tokenizer and recurses into @media."""
    out, n = [], 0
    for kind, raw, selector in _recon._tokenize(css):
        if kind == 'rule':
            brace = raw.find('{')
            sel, body = raw[:brace], raw[brace + 1:raw.rfind('}')]
            parts = [p.strip() for p in sel.split(',')]
            is_root = any(p == '.slide' or _ROOT_SEL_RE.search(p) for p in parts)
            if (is_root or _is_fullbleed(body)) and _rule_has_opaque_bg(body):
                new_body = _BG_STRIP_RE.sub('', body)
                if new_body != body:
                    n += 1
                raw = sel + '{' + new_body + '}'
            out.append(raw)
        elif kind == 'at' and selector.lstrip().lower().startswith('@media'):
            brace = raw.find('{')
            inner = raw[brace + 1:raw.rfind('}')]
            new_inner, m = _strip_bg_css(inner)
            n += m
            out.append(raw[:brace + 1] + new_inner + '}')
        else:
            out.append(raw)
    return ''.join(out), n


def _rewrite_inline_styles(html: str, fn) -> tuple[str, int]:
    """Apply `fn(css)->(css,n)` to every inline <style> body, preserving offsets."""
    total = 0

    def _repl(mt):
        nonlocal total
        full, inner = mt.group(0), mt.group(1)
        new_inner, k = fn(inner)
        if not k:
            return full
        total += k
        a, b = mt.start(1) - mt.start(0), mt.end(1) - mt.start(0)
        return full[:a] + new_inner + full[b:]

    return _STYLE_RE.sub(_repl, html), total


def fix_page_bg(slide: dict) -> int:
    """D1 — strip the slide's own page background so the master content-bg shows."""
    n = 0
    cc = slide.get("custom_css") or ""
    new_cc, m = _strip_bg_css(cc)
    if m:
        slide["custom_css"] = new_cc
        n += m
    html = slide_html(slide)
    new_html, k = _rewrite_inline_styles(html, _strip_bg_css)
    if k:
        slide["data"]["html"] = new_html
        n += k
    return n


_PRETITLE_TOKEN_RE = re.compile(
    r'^(topbar|eyebrow|kicker|overline|page-?label|slug|page-?meta)$', re.I)


def fix_pretitle_chrome(slide: dict) -> list[str]:
    """D3 — remove the eyebrow / topbar / page-label that sits above the title.
    Uses a real HTML parser (never regex DOM surgery — editor hard rule). The
    title element itself is never removed."""
    from bs4 import BeautifulSoup
    html = slide_html(slide)
    soup = BeautifulSoup(html, "html.parser")
    removed = []
    for el in list(soup.find_all(True)):
        classes = (getattr(el, "attrs", None) or {}).get("class") or []
        if not any(_PRETITLE_TOKEN_RE.match(c) for c in classes):
            continue
        if "title-zh" in classes or el.find(class_="title-zh"):
            continue  # never remove (or gut) the title block itself
        removed.append("." + ".".join(classes))
        el.decompose()
    if removed:
        slide["data"]["html"] = str(soup)
    return removed


def fix_font_ladder(slide: dict) -> int:
    """D4 — snap off-ladder font sizes onto {16,24,28,48}. Delegates byte-for-byte
    to reconcile-lifted's snapper (single source of truth) over BOTH custom_css
    and inline <style>."""
    n = 0
    cc = slide.get("custom_css") or ""
    new_cc, m = _recon._reconcile_css(cc, [])
    if m:
        slide["custom_css"] = new_cc
        n += m
    html = slide_html(slide)
    new_html, k, _ = _recon.reconcile_html(html)
    if k:
        slide["data"]["html"] = new_html
        n += k
    return n


def apply_conforms(slide: dict, dims: dict) -> list[str]:
    """Run the deterministic conforms for whichever auto dimensions drifted.
    Returns a list of human-readable action strings (empty = nothing changed)."""
    actions = []
    if dims["D1"].verdict == "drift":
        if fix_page_bg(slide):
            actions.append("D1 ① stripped own page-bg → inherits master content-bg")
    if dims["D3"].verdict == "drift":
        gone = fix_pretitle_chrome(slide)
        if gone:
            actions.append(f"D3 ③ removed pre-title chrome {', '.join(gone)}")
    if dims["D4"].verdict in ("drift", "advisory"):
        n = fix_font_ladder(slide)
        if n:
            actions.append(f"D4 ④ snapped {n} font declaration(s) to the ladder")
    return actions


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
_MARK = {"match": "✓", "drift": "✗", "advisory": "!", "n/a": "·"}


def print_page_report(slide: dict, dims: list[Dim], idx: int) -> int:
    drifts = [d for d in dims if d.verdict in ("drift", "advisory")]
    key = slide.get("key") or "?"
    label = slide.get("screen_label") or ""
    head = f"page {idx} · {key}" + (f"  ({label})" if label else "")
    print(f"\n{head}")
    print("  " + "-" * (len(head)))
    for d in dims:
        mk = _MARK[d.verdict]
        line = (f"  {mk} {d.ask} {d.code} {d.label:<17} "
                f"page: {d.page_desc:<28} family: {d.family_desc}")
        print(line)
        if d.verdict in ("drift", "advisory"):
            print(f"      → fix class: {d.fix}")
    if not drifts:
        print("  ✓ conforms to family on all assessable dimensions.")
    return len([d for d in dims if d.verdict == "drift"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("deck_json", type=Path)
    ap.add_argument("--page", type=int, default=None,
                    help="focus one page (1-based frame index)")
    ap.add_argument("--slide", default=None, help="focus one slide by key")
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any page drifts (gate / CI use)")
    ap.add_argument("--apply", action="store_true",
                    help="run the deterministic conforms (D1 page-bg / D3 pre-title "
                         "chrome / D4 font ladder); D2/D5 stay report-only")
    ap.add_argument("--force", action="store_true",
                    help="bypass the optimistic-lock check on --apply write")
    args = ap.parse_args(argv)

    if not args.deck_json.exists():
        print(f"conform-to-deck: {args.deck_json} not found", file=sys.stderr)
        return 2
    expected_mtime = args.deck_json.stat().st_mtime
    try:
        deck = json.loads(args.deck_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"conform-to-deck: {args.deck_json} is not valid JSON: {e}",
              file=sys.stderr)
        return 2

    slides = deck.get("slides", [])
    content = [(i + 1, s) for i, s in enumerate(slides) if is_content_raw(s)]
    print(f"conform-to-deck: {args.deck_json.name} — {len(slides)} slide(s), "
          f"{len(content)} raw content page(s) in the family")

    if len(content) < 3:
        print("  · need >= 3 raw content pages to form a family consensus "
              f"(found {len(content)}). Nothing to conform against.")
        return 0

    # select pages under test
    if args.page is not None:
        targets = [(i, s) for i, s in content if i == args.page]
        if not targets:
            print(f"  ✗ page {args.page} is not a raw content page.",
                  file=sys.stderr)
            return 2
    elif args.slide is not None:
        targets = [(i, s) for i, s in content if s.get("key") == args.slide]
        if not targets:
            print(f"  ✗ no raw content page with key '{args.slide}'.",
                  file=sys.stderr)
            return 2
    else:
        targets = content

    total_drift_pages = 0
    applied = []          # (idx, key, [actions]) when --apply changed a page
    manual = []           # (idx, key, [D2/D5 items]) left for the human
    for idx, slide in targets:
        siblings = [s for i, s in content if i != idx]
        dim_list = assess_page(slide, siblings)
        dims = {d.code: d for d in dim_list}
        n = print_page_report(slide, dim_list, idx)
        if n:
            total_drift_pages += 1
        if args.apply:
            actions = apply_conforms(slide, dims)
            if actions:
                applied.append((idx, slide.get("key"), actions))
            left = [f"{d.code} {d.ask} {d.label} ({d.page_desc})"
                    for d in dim_list if d.verdict in ("drift", "advisory")
                    and d.fix.startswith(("semi", "judgment"))]
            if left:
                manual.append((idx, slide.get("key"), left))

    print(f"\n{'=' * 60}")

    # --- detection-only summary -----------------------------------------------
    if not args.apply:
        if total_drift_pages:
            print(f"✗ {total_drift_pages} page(s) drift from the family. "
                  f"Auto-fixable: D1/D3/D4 → re-run with --apply. Review: D2/D5.")
        else:
            print("✓ all assessed page(s) conform to the family.")
        return 1 if (args.strict and total_drift_pages) else 0

    # --- apply: write the deterministic conforms ------------------------------
    if not applied:
        print("✓ nothing to auto-conform — no D1/D3/D4 drift to fix. "
              "(D2/D5 are never auto-applied.)")
        return 0

    print("APPLIED the deterministic conforms:")
    for idx, key, actions in applied:
        print(f"  page {idx} · {key}")
        for a in actions:
            print(f"      · {a}")

    # F-53 optimistic lock: refuse to clobber a concurrent write.
    if not args.force:
        cur = args.deck_json.stat().st_mtime
        if abs(cur - expected_mtime) > 1e-6:
            print(f"\n✗ REFUSING write — {args.deck_json.name} changed on disk "
                  f"since read (concurrent edit). Re-run, or pass --force.",
                  file=sys.stderr)
            return 3

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = args.deck_json.with_suffix(f".json.bak-pre-conform-{ts}")
    shutil.copy2(args.deck_json, bak)
    args.deck_json.write_text(
        json.dumps(deck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n  ✓ backup: {bak.name}")
    print(f"  ✓ wrote {args.deck_json.name}")

    # write-after-validate + rollback (F-281b discipline): a conform that
    # produced a schema-invalid deck.json must not land on disk.
    import subprocess
    val = subprocess.run(
        [sys.executable, str(HERE / "validate-deck.py"), str(args.deck_json),
         "--strict"], capture_output=True, text=True)
    if val.returncode != 0:
        shutil.copy2(bak, args.deck_json)
        print("\n✗ post-conform validate-deck --strict FAILED — rolled back "
              "byte-for-byte from the backup. No change landed.", file=sys.stderr)
        tail = (val.stdout or val.stderr or "").rstrip().splitlines()[-12:]
        print("\n".join("    " + ln for ln in tail), file=sys.stderr)
        return 4
    print("  ✓ post-conform validate-deck --strict: PASS")

    if manual:
        print("\nStill needs a human (not auto-applied):")
        for idx, key, left in manual:
            print(f"  page {idx} · {key}")
            for item in left:
                print(f"      · {item}")
    print("\nNext: re-render to confirm the conforms didn't shift layout:")
    print(f"  python3 deck-json/render-deck.py {args.deck_json} "
          f"{args.deck_json.parent}/ --scope {','.join(str(i) for i, _, _ in applied)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
