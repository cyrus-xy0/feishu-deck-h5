#!/usr/bin/env python3
"""reskin.py — foreign HTML → feishu-deck h5 one-shot reskin engine.

Takes a standalone HTML slide (any canvas size, any palette, any logo)
and emits a deck.json + per-page CSS that fits the feishu-deck-h5
framework: 1920×1080 canvas, lark master assets, --fs-* palette, 4-tier
type ladder, R12-clean shadows, framework `.header > h2.title-zh` +
auto-injected `.wordmark`.

Triggered by reskin.sh (which chains preflight → new-run → reskin.py →
render-deck.py → validate.py). Can be invoked standalone for debugging.

Hard rule: this script NEVER restructures the foreign layout's
narrative/pattern. It only swaps chrome — title position, font tokens,
palette, background, drop-shadows, canvas scale. The source's actual
content layout (diagrams / cards / flow) survives byte-for-byte (modulo
the CSS rewrites).

stdlib + bs4 + pyyaml. Python 3.11+.

Usage:
    python3 reskin.py <input.html> <output-deckjson.json> [--slug SLUG]
                                                          [--rules PATH]

Exit codes:
    0  OK
    1  bad args / missing file
    2  HTML parse failure
    3  no usable body content
    4  rules file invalid
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("✗ pyyaml required: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

try:
    from bs4 import BeautifulSoup, Tag, NavigableString
except ImportError:
    print("✗ beautifulsoup4 required: pip install beautifulsoup4", file=sys.stderr)
    sys.exit(1)


HERE = Path(__file__).resolve().parent
DEFAULT_RULES = HERE / "reskin-rules.yaml"


# ════════════════════════════════════════════════════════════════════
#  Helpers
# ════════════════════════════════════════════════════════════════════

def _warn(warnings: list[str], msg: str) -> None:
    warnings.append(msg)


def _hex_to_rgb(h: str) -> tuple[int, int, int] | None:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return None


def _rgb_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _slugify(s: str) -> str:
    """Kebab-case ascii slug. Drops CJK; falls back to 'reskin'."""
    out = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return out[:40] or "reskin"


# ════════════════════════════════════════════════════════════════════
#  CSS rewriters (pure-string transforms, no DOM)
# ════════════════════════════════════════════════════════════════════

def rewrite_palette(css: str, rules: dict, warnings: list[str]) -> str:
    """Replace #hex literals with var(--fs-*) when within threshold.

    Also rewrites :root { --custom-name: #hex } definitions — leaves the
    --custom-name in place but points it at the mapped --fs-* token.
    """
    palette = rules["palette"]
    threshold = rules["palette_match_threshold"]
    cyan_redirect = rules.get("cyan_redirect_to", "--fs-blue")

    fs_colors = [(p["var"], tuple(p["rgb"])) for p in palette]
    cyan_rgb = (36, 195, 255)  # for cyan-redirect heuristic

    def _is_grayscale_ish(rgb: tuple[int, int, int]) -> bool:
        """True if RGB channels are close enough to be a gray/muted color.

        Source decks often define muted text colors like #9AA6C2 (R=154,
        G=166, B=194) — these are gray-ish (max channel spread = 40) and
        should NOT be remapped to a brand accent. Brand colors have one
        channel dominant: #3C7FFF (R=60, G=127, B=255 — B dominant by 195),
        #33D6C0 (R=51, G=214, B=192 — G dominant by 163).

        Rule: if max(R,G,B) - min(R,G,B) < 60, treat as grayscale-ish.
        """
        return max(rgb) - min(rgb) < 60

    def map_hex(hex_str: str) -> str | None:
        rgb = _hex_to_rgb(hex_str)
        if rgb is None:
            return None
        # Grayscale-ish colors (muted text, dim borders) stay as source.
        if _is_grayscale_ish(rgb):
            return None
        # Nearest palette color FIRST, then the R49 cyan redirect — so a
        # legitimate brand color that happens to sit within 60 of cyan but is
        # AT LEAST AS CLOSE to a real palette token (e.g. --fs-teal) maps to
        # that token instead of being force-redirected to blue.
        closest_var, closest_rgb = min(
            fs_colors, key=lambda kv: _rgb_distance(rgb, kv[1])
        )
        closest_dist = _rgb_distance(rgb, closest_rgb)
        cyan_dist = _rgb_distance(rgb, cyan_rgb)
        if cyan_dist < 60 and not (closest_dist <= threshold and closest_dist <= cyan_dist):
            return f"var({cyan_redirect})"   # cyan-ish with no closer real match → blue (R49)
        if closest_dist <= threshold:
            return f"var({closest_var})"
        return None  # too far, keep original

    replaced_count = 0

    # Pattern 1: bare #hex in property values
    def hex_repl(m):
        nonlocal replaced_count
        hex_str = m.group(0)
        mapped = map_hex(hex_str)
        if mapped:
            replaced_count += 1
            return mapped
        return hex_str

    css = re.sub(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", hex_repl, css)

    # Pattern 2: rgb()/rgba() with brand-ish colors → map RGB to var()
    # Only when alpha is 1.0 (else keep as transparent variant).
    def rgb_repl(m):
        nonlocal replaced_count
        r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
        alpha = m.group(4)
        if alpha is not None and float(alpha) < 0.99:
            return m.group(0)  # transparent, keep
        mapped = map_hex(f"#{r:02x}{g:02x}{b:02x}")
        if mapped:
            replaced_count += 1
            return mapped
        return m.group(0)

    css = re.sub(
        r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)(?:\s*,\s*([\d.]+))?\s*\)",
        rgb_repl,
        css,
    )

    if replaced_count:
        warnings.append(
            f"palette: {replaced_count} hex/rgb values → var(--fs-*)"
        )
    return css


def rewrite_fonts(css: str, warnings: list[str]) -> str:
    """Replace foreign font-family stacks with var(--fs-font-cjk).

    Catches `font-family: "PingFang SC", ...` and the family token
    inside `font:` shorthand. The framework's :root defines
    --fs-font-cjk, so this works inside reskinned slides.
    """
    n = 0

    def fam_repl(m):
        nonlocal n
        n += 1
        return f"{m.group(1)}: var(--fs-font-cjk)"

    css = re.sub(
        r"\b(font-family)\s*:\s*[^;}]+",
        fam_repl,
        css,
    )

    # `font:` shorthand has the family at the end (after size/line-height).
    # Conservatively only swap the family token list, not the size/weight.
    # Pattern: `font: <weight?> <size>[/<lh>] <family-list>;`
    # Replace the family-list portion (everything after the size/lh).
    def font_short_repl(m):
        nonlocal n
        prefix = m.group(1)  # font: 800 28px/1.4
        # If the matched group is just the prefix (no family suffix),
        # there's nothing to swap.
        n += 1
        return f"{prefix} var(--fs-font-cjk)"

    css = re.sub(
        r"(\bfont\s*:\s*[^;{}]*?\d+(?:\.\d+)?(?:px|pt|em|rem)(?:\s*/\s*[\d.]+)?)\s+[^;{}]+",
        font_short_repl,
        css,
    )

    if n:
        warnings.append(f"font-family: {n} declarations → var(--fs-font-cjk)")
    return css


CHROME_CLASS_HINTS = (
    "eyebrow", "pill", "tag", "chip", "badge",
    "footnote", "source", "caption", "page",
    "pageno", "footer", "small", "subtitle-en", "label-en",
    "attrib", "credit", "copyright", "logo",
    # `.title-en` is chrome (Latin index/eng label) per framework
    "title-en", "kicker",
)

# Classes that mark a "name / heading / closing-line" — content anchor
# inside a card. Source 14-22 → 28 (Sub tier), not 24 (Body), because
# these are NOT body paragraphs but sub-tier section labels.
NAME_CLASS_HINTS = (
    "wname",         # wheel/section name
    "cname",         # card name
    "ctitle",        # card title
    "card-title", "card-name",
    "scene-name", "ind-name", "role-name", "persona-name",
    "tagline",       # closing slogan
    "lede", "lead",  # opening line
    "heading", "section-title", "block-title",
)


def _selector_class_kind(selector: str) -> str:
    """Heuristic: classify selector by what kind of element it targets.

    Returns: 'chrome' | 'name' | 'body'
    - 'chrome' → 16 px floor OK (page-level metadata)
    - 'name'   → 28 px (Sub tier) for source 14-22 (card name / heading)
    - 'body'   → 24 px floor (body paragraphs / list items)

    Match rule: hint matches as a class-name SUFFIX (`.wpill` matches "pill",
    `.card-tag` matches "tag") but NOT as a substring inside a longer word
    (`.spillage` does NOT match "pill"). Pattern `\\.[\\w-]*{hint}\\b`.
    """
    s = selector.lower()
    # name takes priority over chrome (e.g. .card-title beats .title-en)
    for hint in NAME_CLASS_HINTS:
        if re.search(rf"\.[\w-]*{re.escape(hint)}\b", s):
            return "name"
    for hint in CHROME_CLASS_HINTS:
        if re.search(rf"\.[\w-]*{re.escape(hint)}\b", s):
            return "chrome"
    return "body"


# Backward-compat shim (some helpers still call _selector_is_chrome)
def _selector_is_chrome(selector: str) -> bool:
    return _selector_class_kind(selector) == "chrome"


def snap_font_sizes(css: str, rules: dict, warnings: list[str]) -> str:
    """Snap every font-size:Npx to the 4-tier ladder {16, 24, 28, 48}.

    SELECTOR-AWARE: if the selector targets a body-content class (not
    chrome), the floor is 24 (R06 body floor), not 16. So a foreign
    `.subtitle { font-size: 15px }` snaps to 24, not 16.

    Also processes the size token inside `font:` shorthand.
    """
    table = rules["font_size_snap_table"]

    def snap_value(n: float, kind: str) -> int:
        # kind: 'chrome' | 'name' | 'body'
        # Source 14-22 routes to: chrome=16, name=28 (Sub), body=24
        # Source ≥ 23 uses the ladder table as-is.
        if n <= 22:
            if kind == "chrome":
                return 16
            elif kind == "name":
                return 28
            else:  # body
                return 24
        # Source > 22 uses the table
        snapped = table[-1]["snap"]
        for row in table:
            if n <= row["max"]:
                snapped = row["snap"]
                break
        if kind == "body" and snapped == 16:
            return 24
        return snapped

    n_snapped = 0

    def process_rule(m):
        nonlocal n_snapped
        sel = m.group(1)
        body = m.group(2)
        kind = _selector_class_kind(sel)

        # font-size: Npx
        def size_repl(sm):
            nonlocal n_snapped
            n = float(sm.group(1))
            new = snap_value(n, kind)
            if abs(n - new) < 0.5:
                return sm.group(0)
            n_snapped += 1
            return f"font-size: {new}px"

        body = re.sub(
            r"font-size\s*:\s*(\d+(?:\.\d+)?)\s*px",
            size_repl,
            body,
        )

        # `font:` shorthand
        def short_size_repl(sm):
            nonlocal n_snapped
            prefix = sm.group(1)
            n = float(sm.group(2))
            new = snap_value(n, kind)
            suffix = sm.group(3) or ""
            if abs(n - new) < 0.5:
                return sm.group(0)
            n_snapped += 1
            return f"{prefix}{new}px{suffix}"

        body = re.sub(
            r"(\bfont\s*:\s*(?:[^;{}]*?\s)?)(\d+(?:\.\d+)?)px(\s*/\s*[\d.]+\s+[^;{}]*)?",
            short_size_repl,
            body,
        )

        return f"{sel}{{{body}}}"

    css = re.sub(
        r"([^{}]+)\{([^{}]+)\}",
        process_rule,
        css,
        flags=re.DOTALL,
    )

    if n_snapped:
        warnings.append(
            f"font-size: {n_snapped} values snapped to 4-tier ladder "
            f"(selector-aware: chrome → 16, body → 24)"
        )
    return css


def _split_csv_respecting_parens(s: str) -> list[str]:
    """Split comma-separated CSS values, respecting parens.

    `0 4px 14px rgba(51,112,255,.4), inset 0 0 5px #000` →
        ['0 4px 14px rgba(51,112,255,.4)', 'inset 0 0 5px #000']
    """
    out = []
    depth = 0
    cur = ""
    for c in s:
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if c == "," and depth == 0:
            if cur.strip():
                out.append(cur.strip())
            cur = ""
        else:
            cur += c
    if cur.strip():
        out.append(cur.strip())
    return out


def strip_drop_shadows(css: str, warnings: list[str]) -> str:
    """Remove R12 violations — box-shadow values with non-zero offset.

    Keeps: inset shadows, glow rings (0 0 Npx ...), text-shadow.
    Drops: real drop shadows (any non-inset with ox or oy != 0).

    If all values in a declaration are real drop shadows, removes the
    entire declaration. If some are glow rings, keeps those.
    """
    stripped = 0

    def keep_part(part: str) -> bool:
        tokens = part.strip().split()
        if not tokens:
            return False
        if "inset" in tokens:
            return True
        # First two numeric tokens are offsets
        nums = []
        for t in tokens:
            m = re.match(r"^-?(\d+(?:\.\d+)?)(?:px)?$", t)
            if m:
                nums.append(float(m.group(1)))
            if len(nums) == 2:
                break
        if len(nums) >= 2:
            ox, oy = nums[0], nums[1]
            return ox == 0 and oy == 0
        return True  # un-parseable, keep

    def fix(m):
        nonlocal stripped
        val = m.group(1)
        term = m.group(2)            # the `;` or `}` that ended the declaration
        parts = _split_csv_respecting_parens(val)
        kept = [p for p in parts if keep_part(p)]
        dropped = len(parts) - len(kept)
        stripped += dropped
        if not kept:
            # Drop the whole declaration, but KEEP a `}` terminator (it closes
            # the rule). A `;` terminator goes away with the declaration.
            return "}" if term.strip() == "}" else ""
        return f"box-shadow: {', '.join(kept)}{term}"

    css = re.sub(
        # Stop at `;` OR `}` and re-emit the terminator — a box-shadow that is
        # the LAST declaration in its block (no trailing `;`) otherwise lets
        # `[^;]+` run past `}` into the next rule.
        r"box-shadow\s*:\s*([^;}]+)(\s*[;}])",
        fix,
        css,
    )

    if stripped:
        warnings.append(
            f"R12: dropped {stripped} real drop-shadow value(s) "
            f"(non-zero offset, non-inset)"
        )
    return css


def scale_canvas(css: str, from_w: int, to_w: int, warnings: list[str]) -> str:
    """Multiply every Npx in CSS by (to_w / from_w).

    Applied AFTER font-size snap (so font-sizes stay on ladder; only
    structural px scale). Conservative: snap font-size again at the end.
    """
    factor = to_w / from_w
    if abs(factor - 1.0) < 0.02:
        return css  # already at target

    def scale(m):
        n = float(m.group(1))
        scaled = round(n * factor)
        return f"{scaled}px"

    # Skip font-size declarations — they're already on ladder. Scale
    # everything else.
    out_lines = []
    for line in css.split("\n"):
        if "font-size" in line or re.search(r"\bfont\s*:", line):
            out_lines.append(line)
        else:
            out_lines.append(re.sub(r"(\d+(?:\.\d+)?)px", scale, line))
    warnings.append(
        f"canvas: scaled non-font px by {factor:.3f} (from {from_w} to {to_w})"
    )
    return "\n".join(out_lines)


def scope_selectors(css: str, slide_key: str, warnings: list[str]) -> str:
    """Prefix every selector with .slide[data-slide-key="<key>"] so the
    rewritten CSS only applies inside this reskinned slide.

    Skips @keyframes (those don't take a selector prefix), @media (recursed
    over body) — keeps it simple, doesn't handle deeply nested at-rules.
    """
    anchor = f'.slide[data-slide-key="{slide_key}"]'

    out = []
    pos = 0
    n_scoped = 0

    # Walk CSS top-level. State: at top, inside @keyframes, inside @media.
    # Simple bracket-depth scan.
    while pos < len(css):
        # Skip whitespace + comments
        m = re.match(r"\s+|/\*.*?\*/", css[pos:], re.DOTALL)
        if m:
            out.append(m.group(0))
            pos += m.end()
            continue

        # @-rule? (keyframes, media, font-face, ...)
        m = re.match(r"@(\w+)([^{;]*)", css[pos:])
        if m:
            atname = m.group(1)
            atprelude = m.group(0)
            pos += m.end()
            # Find the body { ... } or terminating ;
            if pos < len(css) and css[pos] == "{":
                # Find matching }
                depth = 1
                start = pos
                pos += 1
                while pos < len(css) and depth > 0:
                    if css[pos] == "{":
                        depth += 1
                    elif css[pos] == "}":
                        depth -= 1
                    pos += 1
                body = css[start + 1 : pos - 1]
                if atname in ("keyframes", "-webkit-keyframes", "font-face"):
                    # Don't scope these — they're keyframe names, not selectors.
                    out.append(f"{atprelude}{{{body}}}")
                elif atname == "media":
                    # Recurse — scope the inner content's selectors.
                    scoped_body = scope_selectors(body, slide_key, warnings)
                    out.append(f"{atprelude}{{{scoped_body}}}")
                else:
                    out.append(f"{atprelude}{{{body}}}")
            else:
                # @import / @charset etc. — semicolon-terminated.
                if pos < len(css) and css[pos] == ";":
                    out.append(atprelude + ";")
                    pos += 1
                else:
                    out.append(atprelude)
            continue

        # Regular rule: selector-list { body }
        m = re.match(r"([^{}]+)\{", css[pos:])
        if not m:
            # No more rules
            out.append(css[pos:])
            break
        selector_list = m.group(1).rstrip()
        pos += m.end()
        # Find matching close brace
        depth = 1
        start = pos
        while pos < len(css) and depth > 0:
            if css[pos] == "{":
                depth += 1
            elif css[pos] == "}":
                depth -= 1
            pos += 1
        body = css[start : pos - 1]

        # Prefix each selector in the list
        selectors = [s.strip() for s in selector_list.split(",")]
        scoped = []
        for sel in selectors:
            if not sel:
                continue
            # If selector already starts with our anchor, keep it.
            if sel.startswith(anchor):
                scoped.append(sel)
            # If selector targets html/body, drop it — these are foreign
            # global rules we don't want leaking.
            elif re.match(r"^(html|body)\b", sel):
                warnings.append(
                    f"scope: dropped global rule on {sel.split()[0]} "
                    f"(foreign chrome — incompatible with framework shell)"
                )
                continue
            # If selector is :root, treat specially — keep as :root so
            # custom-property definitions still apply globally. Framework's
            # --fs-* tokens are at :root already; the foreign --my-color
            # values map to feishu tokens at the value level, not the var
            # name, so leaving :root works.
            elif sel.startswith(":root"):
                scoped.append(sel)
            # Drop universal `*` resets — when scoped to .slide[...] *
            # they hit framework chrome (.wordmark / .header) inside the slide.
            elif sel.strip() == "*":
                warnings.append(
                    "scope: dropped global `*` reset (foreign chrome — "
                    "would override framework defaults inside the slide)"
                )
                continue
            # Foreign body-scoped selectors: prefix with anchor.
            # Special case: source's `.slide` IS the canvas root → maps to
            # our anchor directly (NOT `<anchor> .slide` — that selector
            # has no target since framework's .slide doesn't nest another
            # .slide inside it). So:
            #   `.slide`          → `<anchor>`             (canvas root rule)
            #   `.slide .foo`     → `<anchor> .foo`        (descendant of canvas)
            #   `.foo`            → `<anchor> .foo`        (normal)
            #   `.foo .bar`       → `<anchor> .foo .bar`
            else:
                # Match `.slide` (possibly followed by combinator)
                m = re.match(r"^\.slide\b(.*)", sel.strip())
                if m:
                    rest = m.group(1).strip()
                    if not rest:
                        scoped.append(anchor)
                        # When mapping source `.slide` → framework anchor,
                        # strip declarations that meant "slide-card edge in
                        # standalone viewport" but read as "thin line at
                        # top/bottom of slide" inside framework's full-canvas
                        # wrap: `border`, `box-shadow`, `border-radius`.
                        body = re.sub(
                            r"\b(border|border-top|border-bottom|border-left|border-right|border-radius|box-shadow)\s*:[^;}]+;?",
                            "",
                            body,
                        )
                    else:
                        scoped.append(f"{anchor} {rest}")
                    n_scoped += 1
                else:
                    scoped.append(f"{anchor} {sel}")
                    n_scoped += 1
        if scoped:
            out.append(f"{', '.join(scoped)}{{{body}}}")
    if n_scoped:
        warnings.append(
            f"scope: prefixed {n_scoped} selectors with [data-slide-key={slide_key}]"
        )
    return "".join(out)


# ════════════════════════════════════════════════════════════════════
#  DOM operations (BeautifulSoup)
# ════════════════════════════════════════════════════════════════════

def extract_css(soup: BeautifulSoup) -> tuple[str, list[Tag]]:
    """Concat all <style> contents from <head>. Returns (css, style_tags)."""
    style_tags = soup.find_all("style")
    css = "\n\n".join(s.get_text() or "" for s in style_tags)
    return css, style_tags


def detect_source_canvas(css: str) -> tuple[int, int] | None:
    """Try to find the source's intended canvas size.

    Looks for the first selector that sets BOTH width and height with
    px values matching common slide aspect ratios (16:9, 4:3). Skips
    obviously non-slide values (e.g. width:100% etc.).
    """
    # Look for "width:Npx" and "height:Mpx" within ~200 chars of each other
    for m in re.finditer(
        r"width\s*:\s*(\d{3,4})\s*px[^{}]*?height\s*:\s*(\d{3,4})\s*px",
        css,
        re.DOTALL,
    ):
        w, h = int(m.group(1)), int(m.group(2))
        ratio = w / h
        if abs(ratio - 16 / 9) < 0.05 or abs(ratio - 4 / 3) < 0.05:
            return (w, h)
    # Also check height first, width second
    for m in re.finditer(
        r"height\s*:\s*(\d{3,4})\s*px[^{}]*?width\s*:\s*(\d{3,4})\s*px",
        css,
        re.DOTALL,
    ):
        h, w = int(m.group(1)), int(m.group(2))
        ratio = w / h
        if abs(ratio - 16 / 9) < 0.05 or abs(ratio - 4 / 3) < 0.05:
            return (w, h)
    return None


def detect_title(body: Tag, rules: dict) -> tuple[str | None, Tag | None]:
    """Find the foreign page title. Returns (text, element-to-remove)."""
    candidates = rules["foreign_chrome"]["title_candidates"]
    for cand in candidates:
        tag_name = cand["tag"]
        substrings = cand.get("class_substring") or []
        for el in body.find_all(tag_name):
            classes = " ".join(el.get("class", [])).lower()
            if substrings and not any(s in classes for s in substrings):
                continue
            text = el.get_text(" ", strip=True)
            if text and len(text) >= 4:
                return (text, el)
    return (None, None)


def detect_subtitle(body: Tag) -> tuple[str | None, Tag | None]:
    """Find the foreign page subtitle (paraphrasing the title, lives near it).

    Heuristics: any element with class containing 'subtitle' / 'sub-title' /
    'subhead' / 'lede' / 'lead' / 'tagline-top'. Returns (text, element).
    """
    SUBTITLE_HINTS = ("subtitle", "sub-title", "subhead", "lede", "lead-line")
    for el in body.find_all(True):
        if el.attrs is None or el.parent is None:
            continue
        classes = " ".join(el.get("class", [])).lower()
        if any(h in classes for h in SUBTITLE_HINTS):
            text = el.get_text(" ", strip=True)
            if text and len(text) >= 4:
                return (text, el)
    return (None, None)


def prune_empty_wrappers(body: Tag, warnings: list[str]) -> int:
    """Drop UNCLASSED divs/spans whose text content is empty after extractions.

    Walks bottom-up so nested empties cascade-clean. Returns number pruned.

    SKIP classed empties (e.g. `<div class="circle"></div>`) — they're
    CSS-decorated drawings (border-radius circles, dashed-line shapes,
    spinning markers, etc.). Empty + classed = "the element IS the visual".
    Only TRULY orphan empties (no class, no id) are residue from extraction.
    """
    n = 0
    for el in list(body.find_all(True))[::-1]:
        if el.parent is None or el.attrs is None:
            continue
        if el.name not in ("div", "span", "section", "article", "header", "footer"):
            continue
        # If element has any class or id, assume it's styled-decorative.
        # Don't decompose.
        if el.get("class") or el.get("id") or el.get("style"):
            continue
        has_text = bool(el.get_text(strip=True))
        has_media = any(
            el.find(t) is not None
            for t in ("img", "svg", "iframe", "video", "canvas")
        )
        if not has_text and not has_media:
            el.decompose()
            n += 1
    if n:
        warnings.append(
            f"chrome: pruned {n} unclassed empty wrapper div(s) (residue from extracted title/subtitle/logo)"
        )
    return n


def strip_foreign_logo(body: Tag, rules: dict, warnings: list[str]) -> int:
    """Remove logo blocks from body (framework auto-injects .wordmark)."""
    sig = rules["foreign_chrome"]["logo_signals"]
    class_subs = [s.lower() for s in sig["class_substring"]]
    brand_texts = sig["brand_text"]

    n_removed = 0
    for el in list(body.find_all(True)):  # all tags
        # Skip elements that lost their parent during a previous decompose()
        # in this loop (find_all snapshot may include descendants of a
        # later-decomposed ancestor; their attrs become None).
        if el.parent is None or el.attrs is None:
            continue
        classes = " ".join(el.get("class", [])).lower()
        if not any(s in classes for s in class_subs):
            continue
        has_svg = el.find("svg") is not None
        text = el.get_text(strip=True)
        has_brand = any(b in text for b in brand_texts)
        if has_svg or has_brand:
            el.decompose()
            n_removed += 1
    if n_removed:
        warnings.append(
            f"chrome: removed {n_removed} foreign logo block(s) "
            f"(framework .wordmark auto-injects)"
        )
    return n_removed


def strip_scale_script(soup: BeautifulSoup, warnings: list[str]) -> None:
    """Excise the foreign scale-to-fit logic from `<script>` blocks.

    The fit() function is redundant with framework feishu-deck.js (which
    handles scaling). BUT it commonly lives in the SAME <script> block
    as content-bearing code (e.g. buildRing that populates nodes on the
    ring). So we surgically remove only the fit-related pieces:
      - the `function fit() { ... }` declaration
      - the immediate `fit();` call
      - the `window.addEventListener('resize', fit)` listener

    Keeping the rest of the script intact (buildRing, animation init, etc.).

    If after excision a script becomes empty/whitespace-only, drop it.
    """
    FIT_FN_PATTERN = re.compile(
        r"function\s+fit\s*\(\s*\)\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",
        re.DOTALL,
    )
    FIT_CALL = re.compile(r"\bfit\s*\(\s*\)\s*;?")
    RESIZE_LISTENER = re.compile(
        r"window\.addEventListener\(\s*['\"]resize['\"][^)]+\)\s*;?",
    )

    excised = 0
    for s in list(soup.find_all("script")):
        if s.get("src"):
            continue
        txt = s.get_text() or ""
        if not (
            "innerWidth" in txt
            and "innerHeight" in txt
            and ("scale(" in txt or "scale " in txt)
        ):
            continue  # no scale-to-fit logic in this script
        new_txt = FIT_FN_PATTERN.sub("", txt)
        new_txt = FIT_CALL.sub("", new_txt)
        new_txt = RESIZE_LISTENER.sub("", new_txt)
        if new_txt.strip():
            # Script has other content — replace its text, keep the tag.
            s.string = new_txt
            excised += 1
        else:
            # Whole script was just scale-to-fit — remove entirely.
            s.decompose()
            excised += 1

    if excised:
        warnings.append(
            f"chrome: excised foreign scale-to-fit logic from {excised} script(s) "
            f"(framework feishu-deck.js handles scale; other content preserved)"
        )


def find_main_container(body: Tag) -> Tag | None:
    """Find the outermost slide-canvas-like container.

    Heuristic: an element with class containing 'slide' or 'stage', OR
    body's first big div. Returns its inner content node.
    """
    for sel_class in ("slide", "stage", "canvas", "deck"):
        for el in body.find_all("div"):
            classes = " ".join(el.get("class", [])).lower()
            if sel_class in classes:
                return el
    # Fallback: the largest direct child of body
    direct_divs = [c for c in body.children if isinstance(c, Tag) and c.name == "div"]
    if direct_divs:
        return direct_divs[0]
    return None


# ════════════════════════════════════════════════════════════════════
#  Composer
# ════════════════════════════════════════════════════════════════════

def _b64_content_bg() -> str:
    """Base64-inline lark-content-bg.jpg so per-page CSS is self-contained
    (var(--fs-asset-content-bg) doesn't work in inline <style> — Custom
    Property url() is text-substituted, then resolved against the HTML
    document's URL, NOT the framework CSS's URL, so url("lark-content-bg.jpg")
    becomes file://.../output/lark-content-bg.jpg → 404)."""
    import base64
    bg_path = HERE / "lark-content-bg.jpg"
    if not bg_path.exists():
        return ""
    b64 = base64.b64encode(bg_path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def build_header_css(slide_key: str, rules: dict) -> str:
    """Per-page CSS for framework `.header` + `.stage` + background."""
    h = rules["header_chrome"]
    auto = rules["auto_layout"]
    anchor = f'.slide[data-slide-key="{slide_key}"]'

    # Inline lark-content-bg.jpg as base64 (don't use var(--fs-asset-content-bg)
    # — see _b64_content_bg comment for why).
    bg_data_uri = _b64_content_bg()
    bg_decl = (
        f'background: #000 url("{bg_data_uri}") center/cover no-repeat;'
        if bg_data_uri else
        f"background: #080C18;  /* lark-content-bg.jpg not found; fallback to dark */"
    )

    parts = [
        f"/* === Framework chrome (auto-emitted by reskin) === */",
        f"{anchor} {{",
        f"  {bg_decl}",
        f"}}",
        f"",
        f"{anchor} .header {{",
        f"  position: absolute;",
        f"  top: {h['title_top']}px; left: {h['title_left']}px; right: {h['title_right']}px;",
        f"  padding: 0; border: 0;",
        f"}}",
        f"",
        f"{anchor} .stage {{",
        f"  position: absolute;",
        f"  top: {h['stage_top']}px; left: {h['stage_left']}px;",
        f"  right: {h['stage_right']}px; bottom: {h['stage_bottom']}px;",
        f"  padding: 0;",
    ]
    if auto["enable_stage_flex"]:
        parts += [
            f"  display: flex; flex-direction: column;",
            f"  gap: {auto['stage_gap']}px;",
        ]
    parts += [f"}}"]

    if auto["enable_stage_flex"] and auto.get("flex_grow_class_substring"):
        # Generic: if any direct child of .stage has a class matching one
        # of the hints, flex:1. Otherwise all flex-shrink:0.
        hints = auto["flex_grow_class_substring"]
        selector_parts = ", ".join(
            f'{anchor} .stage > [class*="{h}"]' for h in hints
        )
        parts += [
            f"",
            f"/* Auto-layout: largest child fills remaining stage height */",
            f"{anchor} .stage > * {{ flex-shrink: 0; }}",
            f"{selector_parts} {{ flex: 1; min-height: 0; flex-shrink: 1; }}",
        ]

    return "\n".join(parts) + "\n"


def compose_data_html(
    inner_html: str,
    title_text: str,
    slide_key: str,
    rewritten_css: str,
    rules: dict,
    subtitle_text: str | None = None,
    source_canvas: tuple[int, int] | None = None,
    extract_to_header: bool = True,
    source_font_family: str | None = None,
) -> str:
    """Build the `data.html` string for the raw-layout slide.

    Structure:
        <style>...rewritten + chrome CSS...</style>
        <div class="header">
          <h2 class="title-zh">title</h2>
          [<p class="page-sub">subtitle</p>]   ← optional, framework 28px
        </div>
        <div class="stage">
          <div class="rk-canvas">         ← native-sized scale wrapper
            ...foreign body inner content (CSS px untouched, JS coords intact)...
          </div>
        </div>

    The `rk-canvas` wrapper lets us VISUALLY scale the source canvas
    (1280×720 → fills 1920×1080 framework slide) WITHOUT touching CSS px
    or JS coordinates. `transform: scale()` only affects rendering, not
    layout box — so all `position: absolute` math and JS-computed offsets
    survive unchanged.
    """
    # For 1920×1080 native sources, SKIP framework .header + .stage chrome
    # (extract_to_header=False). The source already has its own title +
    # padding designed for the full 1920×1080 canvas; adding framework
    # chrome on top displaces source content downward and causes overflow.
    # Just emit rewritten source CSS + body (no header div, no stage wrap).
    if not extract_to_header:
        bg_data_uri = _b64_content_bg()
        bg_decl = (
            f'background: #000 url("{bg_data_uri}") center/cover no-repeat;'
            if bg_data_uri else
            f"background: #080C18;"
        )
        # Re-assert source's font-family on .slide anchor. Framework's
        # `.slide { font-family: var(--fs-font-cjk) }` would otherwise
        # cascade and change line-heights → ~70px downward drift.
        font_override = (
            f"  font-family: {source_font_family};\n"
            if source_font_family else ""
        )
        chrome_css = (
            f"/* === Framework chrome (native 1920×1080 mode: skip .header/.stage) === */\n"
            f'.slide[data-slide-key="{slide_key}"] {{\n'
            f"  {bg_decl}\n"
            f"{font_override}"
            f"}}\n"
        )
        full_css = chrome_css + "\n/* === Rewritten source CSS === */\n" + rewritten_css
        return (
            f"<style>\n{full_css}\n</style>\n"
            f"<!-- source content kept at native 1920×1080 layout -->\n"
            f"{inner_html}\n"
        )

    chrome_css = build_header_css(slide_key, rules)
    full_css = chrome_css + "\n/* === Rewritten source CSS === */\n" + rewritten_css

    sub_html = (
        f'<p class="page-sub">{subtitle_text}</p>' if subtitle_text else ""
    )

    # Scale wrapper — fit source canvas into framework stage box visually
    # WITHOUT touching CSS px or JS coords. transform: scale() is render-
    # only, layout box stays at source size, so absolute-positioned children
    # + JS-computed offsets (buildRing etc.) stay consistent.
    #
    # CAVEAT: foreign HTML often uses 3-column layouts (1fr center 1fr)
    # designed for a tight aspect; scaling stretches columns proportionally
    # and labels in narrow center columns can wrap into siblings. If the
    # output overlaps, the user disables wrap by setting
    # `auto_layout.scale_wrap: false` in reskin-rules.yaml (default: true).
    enable_wrap = rules.get("auto_layout", {}).get("scale_wrap", True)
    h_cfg = rules["header_chrome"]
    stage_w = 1920 - h_cfg["stage_left"] - h_cfg["stage_right"]
    stage_h = 1080 - h_cfg["stage_top"] - h_cfg["stage_bottom"]
    if enable_wrap and source_canvas and source_canvas[0] != 1920:
        sw, sh = source_canvas
        scale = min(stage_w / sw, stage_h / sh)
        canvas_wrap_css = f"""
.slide[data-slide-key="{slide_key}"] .stage {{
  display: grid; place-items: center; gap: 0;
}}
.slide[data-slide-key="{slide_key}"] .rk-canvas {{
  width: {sw}px; height: {sh}px;
  transform: scale({scale:.4f});
  transform-origin: center center;
  position: relative;
  flex-shrink: 0;
}}
"""
        full_css += "\n/* === Source canvas scale wrap === */\n" + canvas_wrap_css
        stage_inner = f'<div class="rk-canvas">\n{inner_html}\n</div>'
    else:
        stage_inner = inner_html

    return (
        f"<style>\n{full_css}\n</style>\n"
        f'<div class="header">\n'
        f'  <h2 class="title-zh">{title_text}</h2>\n'
        f"  {sub_html}\n"
        f"</div>\n"
        f'<div class="stage">\n{stage_inner}\n</div>\n'
    )


# ════════════════════════════════════════════════════════════════════
#  Label-floor 2nd pass (content-context label floor)
# ════════════════════════════════════════════════════════════════════

def label_floor_bump(css: str, rules: dict, warnings: list[str]) -> str:
    """If any selector with a card-hint class has font-size: 16, AND any
    OTHER selector in the same anchor context has font-size: 28+, bump
    the 16 to 24.

    This is a heuristic — we don't have full DOM context, just CSS rules.
    Approach: scan all rules, find those targeting "card-like" classes
    with 16px, then check if any sibling rule on the same root class has
    28+. Conservative bump.
    """
    cfg = rules["content_label_floor"]
    floor_anchor_min = cfg["floor_anchor_min"]
    bump_target = cfg["bump_target"]
    card_hints = cfg["card_class_hints"]

    # Build a map of root-card-class → font-sizes seen
    rule_pattern = re.compile(r"([^{}]+)\{([^{}]+)\}", re.DOTALL)
    rules_found = list(rule_pattern.finditer(css))

    # Find which root containers have sub-tier content (28+)
    rich_containers: set[str] = set()
    for m in rules_found:
        sel, body = m.group(1), m.group(2)
        size_match = re.search(r"font-size\s*:\s*(\d+(?:\.\d+)?)\s*px", body)
        if not size_match:
            # Also check font: shorthand
            short = re.search(r"\bfont\s*:\s*(?:[^;]*?\s)?(\d+(?:\.\d+)?)px", body)
            if not short:
                continue
            size = float(short.group(1))
        else:
            size = float(size_match.group(1))
        if size >= floor_anchor_min:
            # Extract any card-hint class from the selector
            for hint in card_hints:
                m2 = re.search(rf"\.[\w-]*{hint}[\w-]*", sel)
                if m2:
                    rich_containers.add(m2.group(0))

    # Bump pass: any rule whose selector has a class containing a
    # rich-container hint AND its font-size is 16 → bump to bump_target
    if not rich_containers:
        return css

    n_bumped = 0

    def maybe_bump(m):
        nonlocal n_bumped
        sel, body = m.group(1), m.group(2)
        # Does selector mention any of our rich containers' class?
        is_in_rich = any(rc in sel for rc in rich_containers)
        if not is_in_rich:
            return m.group(0)
        # SKILL.md content-context label floor: bump CONTENT labels (24 body),
        # NOT chrome (16 pills/tags/badges stay 16). Per the rule's wording:
        # "every content label in the same card must be ≥ 24". Chrome elements
        # are excluded from "content label".
        if _selector_class_kind(sel) == "chrome":
            return m.group(0)
        # If font-size is exactly 16, bump to target
        new_body = re.sub(
            r"font-size\s*:\s*16px\b",
            lambda _: f"font-size: {bump_target}px",
            body,
        )
        if new_body != body:
            n_bumped += body.count("font-size: 16px") + body.count("font-size:16px")
            return f"{sel}{{{new_body}}}"
        return m.group(0)

    css = rule_pattern.sub(maybe_bump, css)
    if n_bumped:
        warnings.append(
            f"label-floor: bumped {n_bumped} chrome 16px → {bump_target}px "
            f"(content-context label floor; sibling has {floor_anchor_min}+px)"
        )
    return css


# ════════════════════════════════════════════════════════════════════
#  Drop foreign-chrome CSS rules
# ════════════════════════════════════════════════════════════════════

def drop_foreign_chrome_rules(css: str, rules: dict, warnings: list[str]) -> str:
    """Strip CSS rules that conflict with framework chrome (e.g. foreign
    .slide background, body overflow:hidden)."""
    cfg = rules["foreign_chrome"]
    drop_patterns = cfg.get("drop_rules_re", [])
    bg_neutralize_subs = cfg.get("background_neutralize_selectors_substring", [])

    n_dropped = 0

    # Drop entire rules matching drop_rules_re
    for pat in drop_patterns:
        before = len(css)
        css = re.sub(pat + r"[^}]*\}", "", css, flags=re.DOTALL)
        if len(css) != before:
            n_dropped += 1

    # Match a neutralize-sub as a STANDALONE selector token — a bare substring
    # `s in sel` wrongly neutralized `.card-body` / `.slide-frame` because
    # 'body' / '.slide' are substrings of them.
    def _sel_token_present(sub, sel):
        if sub[:1] in ('.', '#'):           # class / id — only a right boundary
            return re.search(re.escape(sub) + r'(?![\w-])', sel) is not None
        # element selector — standalone token (not a class / word suffix)
        return re.search(r'(?<![\w.#-])' + re.escape(sub) + r'(?![\w-])', sel) is not None

    # Neutralize background on selectors matching the neutralize-subs
    def neutralize(m):
        nonlocal n_dropped
        sel, body = m.group(1), m.group(2)
        if any(_sel_token_present(s, sel) for s in bg_neutralize_subs):
            # Drop background:/background-image:/background-color: from body
            new_body = re.sub(
                r"background(?:-color|-image)?\s*:[^;]+;?",
                "",
                body,
            )
            if new_body != body:
                n_dropped += 1
                return f"{sel}{{{new_body}}}"
        return m.group(0)

    css = re.sub(r"([^{}]+)\{([^{}]+)\}", neutralize, css, flags=re.DOTALL)

    if n_dropped:
        warnings.append(
            f"chrome: dropped/neutralized {n_dropped} foreign CSS rule(s) "
            f"(canvas bg / body overflow / etc.)"
        )
    return css


# ════════════════════════════════════════════════════════════════════
#  Main pipeline
# ════════════════════════════════════════════════════════════════════

class CanvasMismatchError(SystemExit):
    """Raised when source canvas != 1920×1080. Reskin REFUSES to proceed.

    Scaling foreign HTML to 1920×1080 is the part reskin can't do reliably
    (JS-positioned elements don't co-scale with CSS; CSS scale-wrap stretches
    column ratios; the source's content was designed for its native canvas
    and looks wrong at any other size). Better to fail fast at preflight
    than waste a render and screenshot pass discovering it.
    """


def preflight_canvas(soup: BeautifulSoup, css: str) -> tuple[int, int]:
    """Check source canvas. Return (w, h) on match, raise on mismatch.

    Hard requirement: source MUST be 1920×1080 (feishu standard). Any
    other size — letterbox the result (visually small) or content-redesign
    (out of reskin's scope). Both unacceptable for "one-shot reskin".

    Detection precedence:
      1. CSS `width: Npx; height: Mpx` on a slide-like rule (16:9 / 4:3 ratio)
      2. Fail with actionable error message.
    """
    canvas = detect_source_canvas(css)
    if canvas is None:
        # Couldn't detect → also fail rather than assume; user gets clear
        # message instead of silent miss.
        raise CanvasMismatchError(
            "✗ reskin preflight failed: could not detect source canvas size.\n"
            "  Looked for `.slide { width: Npx; height: Npx }` (or similar)\n"
            "  with 16:9 or 4:3 aspect. Reskin requires explicit 1920×1080.\n"
            "  Fix: add  `.slide { width:1920px; height:1080px; }`  to source CSS,\n"
            "  OR resize the source to 1920×1080 native before reskinning."
        )
    w, h = canvas
    if (w, h) != (1920, 1080):
        raise CanvasMismatchError(
            f"✗ reskin preflight failed: source canvas is {w}×{h}, not 1920×1080.\n"
            f"  Reskin is a chrome-rewrite (palette / fonts / logo / bg / header),\n"
            f"  NOT a content-resize. Foreign {w}×{h} content can't fit\n"
            f"  the framework's 1920×1080 slide without one of:\n"
            f"    (a) letterboxing — content looks small in the frame\n"
            f"    (b) CSS scale-wrap — JS coords + 3-col layouts break\n"
            f"    (c) full content redesign — that's GENERATION mode, not reskin\n"
            f"  Fix: resize source to 1920×1080 native FIRST, then re-run reskin.\n"
            f"  (Tip: in claude artifacts you can ask the LLM to 'redo at 1920×1080';\n"
            f"  in hand-coded HTML, change `width/height` + scale interior coords.)"
        )
    return canvas


def reskin(input_html: str, slug: str, rules: dict, keep_source_typography: bool = False) -> dict:
    """Run the full reskin pipeline. Returns dict with deck_json, warnings."""
    warnings: list[str] = []
    soup = BeautifulSoup(input_html, "html.parser")
    body = soup.body
    if body is None:
        raise SystemExit("✗ no <body> in input HTML")

    # 1. Extract CSS
    css, style_tags = extract_css(soup)
    if not css.strip():
        warnings.append(
            "no <style> blocks found in source — output will be unstyled"
        )

    # 2. PREFLIGHT — canvas must be 1920×1080 OR we fail fast (saves the
    #    user a render + screenshot cycle to discover the mismatch).
    canvas = preflight_canvas(soup, css)
    source_w = canvas[0]
    warnings.append(f"canvas: preflight passed — source is 1920×1080")

    # 3. Detect title — but DON'T extract for 1920×1080 native sources.
    # When source canvas matches framework (1920×1080), source was designed
    # with its own title block at native top coords (e.g. padding-top:66 +
    # .head section). Adding a framework `.header` on top would steal ~200px
    # of vertical space and force source content downward → overflow.
    # The "title-zh" framework-styling benefit isn't worth that geometry hit.
    # We DO get a screen_label from the title text for deck-level metadata.
    title_text, title_el = detect_title(body, rules)
    extract_to_header = canvas != (1920, 1080)  # only extract for non-native sizes
    if not title_text:
        title_text = soup.title.get_text(strip=True) if soup.title else "Untitled"
        warnings.append(
            f"title: no inline title detected; using <title> tag → '{title_text}'"
        )
    elif extract_to_header:
        warnings.append(f"title: extracted '{title_text[:40]}...' → .header")
    else:
        warnings.append(
            f"title: kept in source layout (1920×1080 native; "
            f"framework .header skipped to preserve source geometry)"
        )

    # 3.5 Detect subtitle (only used when extracting; otherwise leave in source)
    subtitle_text, subtitle_el = detect_subtitle(body)
    if subtitle_text and extract_to_header:
        warnings.append(f"subtitle: extracted '{subtitle_text[:40]}...' → .page-sub")

    # 4. Strip foreign chrome from body (ONLY when extracting to framework chrome)
    if extract_to_header:
        if title_el:
            title_el.decompose()
        if subtitle_el:
            subtitle_el.decompose()

    strip_foreign_logo(body, rules, warnings)
    strip_scale_script(soup, warnings)

    # 4.5 Prune empty wrappers left over from extractions
    prune_empty_wrappers(body, warnings)

    # 5. Find main container, extract inner HTML
    # Collect inline scripts that survived strip_scale_script — these are
    # usually content-bearing (buildRing, animation triggers, etc.) and
    # often live OUTSIDE the .slide div as siblings at body level. We
    # gather them now (before stripping) so they survive into the output.
    surviving_scripts_html: list[str] = []
    for s in list(soup.find_all("script")):
        if s.get("src"):
            continue
        # bs4 quirk: .get_text() returns '' on <script> tags whose content
        # was set via .string = X (which strip_scale_script does for surgical
        # excision). Use str(s) and inspect the rendered HTML instead — the
        # actual content is preserved there.
        rendered = str(s)
        # Strip the wrapping <script>...</script> to check inner emptiness
        inner = re.sub(r"^\s*<script[^>]*>", "", rendered)
        inner = re.sub(r"</script>\s*$", "", inner)
        if inner.strip():
            surviving_scripts_html.append(rendered)

    main = find_main_container(body)
    if main is None:
        # Fallback: use the body's inner directly
        for s in soup.find_all("style"):
            s.decompose()
        for s in soup.find_all("script"):
            s.decompose()
        inner_html = body.decode_contents()
    else:
        for s in main.find_all("style"):
            s.decompose()
        for s in main.find_all("script"):
            s.decompose()
        inner_html = main.decode_contents()
        # Re-append surviving body-level scripts (e.g. buildRing) so they
        # execute inside the rendered slide.
        if surviving_scripts_html:
            inner_html = (
                inner_html
                + "\n<!-- foreign body-level scripts preserved by reskin -->\n"
                + "\n".join(surviving_scripts_html)
            )
            warnings.append(
                f"chrome: preserved {len(surviving_scripts_html)} foreign inline "
                f"script(s) (e.g. buildRing / animation triggers)"
            )

    if not inner_html.strip():
        raise SystemExit("✗ source HTML has no usable body content")

    # 6. CSS rewrites
    slide_key = f"reskin-{slug}"

    # BEFORE scope drops html/body rules, extract source's font-family
    # stack (usually defined on html/body). We'll re-apply it explicitly
    # to .slide[data-slide-key=X] in native mode so the framework's
    # default font doesn't cascade into source content.
    source_font_family: str | None = None
    m_ff = re.search(
        # Stop the capture at `;` OR `}` — a font-family that is the LAST
        # declaration in its block (no trailing `;`) otherwise let `[^;]+` run
        # past the closing `}` into the next rule until some later `;`, capturing
        # garbage markup as the "font stack".
        r"(?:^|\s)(?:html|body)(?:\s*,\s*(?:html|body))?\s*\{[^}]*?font-family\s*:\s*([^;}]+)\s*[;}]",
        css,
        re.IGNORECASE | re.DOTALL,
    )
    if m_ff:
        source_font_family = m_ff.group(1).strip()
        warnings.append(
            f"font-family: captured source's body stack '{source_font_family[:40]}...' "
            f"to re-apply on .slide (preserves source's vertical metrics)"
        )

    css = drop_foreign_chrome_rules(css, rules, warnings)
    css = strip_drop_shadows(css, warnings)
    css = rewrite_palette(css, rules, warnings)
    # Font-family swap ONLY in non-native mode. For 1920×1080 native,
    # swapping the source's "PingFang SC" stack to var(--fs-font-cjk)
    # (whose primary is "方正兰亭黑") causes ~5-15px height inflation
    # per text element (CJK glyph metrics differ), cumulatively pushing
    # tagline below the 1080 boundary. Keep source's font-family exactly.
    if extract_to_header:
        css = rewrite_fonts(css, warnings)
    else:
        warnings.append(
            "font-family: rewrite SKIPPED (1920×1080 native mode — "
            "source font stack preserved to match source's vertical metrics)"
        )
    # Font-size snap + label-floor bump ONLY in non-native mode.
    # For 1920×1080 native source: source designed its own typography
    # hierarchy (e.g. 16/19/23/32/50 px) for its layout heights. Snapping
    # 19→24 and 17→24 (body floor) inflates element heights → strategy
    # bar wraps to 2 lines → wheel column drops → base + tagline pushed
    # below 1080. Source's own hierarchy is the right choice here.
    # font-size snap + label-floor — default ON per user choice option B
    # (2026-05-28 conversation): projector readability per SKILL.md R06/R20
    # wins over source's pixel-perfect layout. Side effect: source content
    # designed for sub-floor sizes may overflow 1080 boundary. Post-render
    # overflow check (reskin.sh) warns user with specifics.
    #
    # --keep-source-typography flag (option A): skip snap, add allow:* escape
    # comments. Source's hierarchy preserved at the cost of sub-spec text.
    if keep_source_typography:
        n_marked = 0
        def add_allow(m):
            nonlocal n_marked
            sel, body = m.group(1), m.group(2)
            if "font-size" not in body and "font:" not in body.replace("font-family:", ""):
                return m.group(0)
            if "allow:typescale" in body or "allow:body-floor" in body:
                return m.group(0)
            n_marked += 1
            return (
                f"{sel}{{\n  /* allow:typescale allow:body-floor "
                f"(--keep-source-typography flag) */{body}}}"
            )
        css = re.sub(r"([^{}]+)\{([^{}]+)\}", add_allow, css, flags=re.DOTALL)
        warnings.append(
            f"font-size: snap + label-floor SKIPPED (--keep-source-typography flag); "
            f"added allow:* escape on {n_marked} rule(s)"
        )
    else:
        css = snap_font_sizes(css, rules, warnings)
        css = label_floor_bump(css, rules, warnings)
    # Canvas scaling is OPT-IN. By default we DON'T scale: foreign CSS px
    # values stay native, and source content shows at its original canvas
    # size inside the framework's 1920×1080 slide (letterboxed). Why:
    # foreign HTML often has JS-positioned elements with hardcoded coords
    # (e.g. buildRing with cx=160 R=125) that we can't safely rewrite —
    # scaling CSS but not JS gives broken layout. Manual scaling via a
    # wrapping `transform: scale(N)` is the user's call.
    enable_scale = rules.get("auto_layout", {}).get("scale_canvas", False)
    if enable_scale and canvas and canvas[0] != 1920:
        css = scale_canvas(css, source_w, 1920, warnings)
    elif canvas and canvas[0] != 1920:
        warnings.append(
            f"canvas: source {canvas[0]}×{canvas[1]} kept native (not scaled to 1920×1080); "
            f"content will appear letterboxed inside framework slide. To scale, "
            f"add transform: scale({1920/canvas[0]:.2f}) on a wrapping div manually, "
            f"OR set auto_layout.scale_canvas: true in reskin-rules.yaml "
            f"(only safe when source has no JS-positioned elements)."
        )
    # Scope every selector to this slide-key so we don't leak
    css = scope_selectors(css, slide_key, warnings)

    # 7. Compose deck.json
    data_html = compose_data_html(
        inner_html, title_text, slide_key, css, rules,
        subtitle_text=subtitle_text if extract_to_header else None,
        source_canvas=canvas if extract_to_header else None,
        extract_to_header=extract_to_header,
        source_font_family=source_font_family,
    )
    deck = {
        "version": "1.0",
        "deck": {
            "title": title_text,
            "author": "reskin",
        },
        "slides": [
            {
                "key": slide_key,
                "layout": "raw",
                "screen_label": f"01 {title_text[:30]}",
                "data": {
                    "title": title_text,
                    "html": data_html,
                },
            }
        ],
    }
    return {"deck_json": deck, "warnings": warnings}


# ════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="Reskin a foreign HTML slide to feishu-deck-h5 framework."
    )
    ap.add_argument("input", help="Path to foreign HTML")
    ap.add_argument("output", help="Path to write deck.json")
    ap.add_argument(
        "--slug",
        default=None,
        help="Slide key slug (kebab-case). Defaults to filename stem.",
    )
    ap.add_argument(
        "--rules",
        default=str(DEFAULT_RULES),
        help=f"Path to rules YAML (default: {DEFAULT_RULES})",
    )
    ap.add_argument(
        "--keep-source-typography",
        action="store_true",
        help="Skip font-size snap. Source's hierarchy preserved at cost of "
             "sub-spec text. Use when source's design density requires its "
             "own typography (small body text by deliberate choice).",
    )
    args = ap.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"✗ input not found: {input_path}", file=sys.stderr)
        sys.exit(1)
    try:
        rules = yaml.safe_load(Path(args.rules).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"✗ failed to load rules YAML: {e}", file=sys.stderr)
        sys.exit(4)

    slug = args.slug or _slugify(input_path.stem)

    try:
        result = reskin(
            input_path.read_text(encoding="utf-8"), slug, rules,
            keep_source_typography=args.keep_source_typography,
        )
    except SystemExit:
        raise
    except Exception as e:
        print(f"✗ reskin failed: {e}", file=sys.stderr)
        sys.exit(2)

    output_path = Path(args.output)
    output_path.write_text(json.dumps(result["deck_json"], ensure_ascii=False, indent=2), encoding="utf-8")

    # Print warnings to stderr (deck-cli style)
    print(f"✓ wrote {output_path}", file=sys.stderr)
    for w in result["warnings"]:
        print(f"  · {w}", file=sys.stderr)


if __name__ == "__main__":
    main()
