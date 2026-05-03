#!/usr/bin/env python3
"""
feishu-deck-h5  ·  programmatic self-check

Runs the SKILL.md self-check items that can be enforced by static analysis.
This is a HARD GATE: a deck is not "done" until this script exits 0.

Usage:
    python3 assets/validate.py path/to/deck.html [--strict]

    --strict  also fails on warnings (mono-logo usage, large unknown hex
              values inside slide markup, etc.)

Exit codes:
    0   all checks pass
    1   one or more violations
    2   internal error (cannot parse file)
"""

from __future__ import annotations
import re, sys, argparse
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
#  规范 thresholds (hard floors)
# ---------------------------------------------------------------------------

FLOOR_BODY_PX        = 22   # body text never smaller than this on canvas
FLOOR_CHROME_PX      = 14   # corner metadata floor
FLOOR_HEADER_PX      = 52   # page-header H2 minimum (master is 26pt × 2 = 52)
FLOOR_TABLE_TH_PX    = 24   # table thead 规范
FLOOR_STATS_TREND_PX = 20   # stats trend tag 规范

# Brand palette — all hex values inside slide markup must be from this set.
ALLOWED_HEX = {
    'fff', 'ffffff', '000', '000000',
    '3c7fff', '24c3ff', '33d6c0', '5c3ffb', '9f6ff1', 'fe7f00',
    '0f1a4a', '060b22', '1a2256', '050817', '04060f', '0a1230', '1b1f3a',
}

# Allowed data-decor tokens
ALLOWED_DECOR = {
    'violet-glow', 'blue-glow', 'mix-glow', 'teal-glow', 'orange-spark',
    'aurora', 'grain', 'topo', 'flower-bg', 'section-bg', 'photo-bg',
}

# Layouts where 2-line hero titles are explicitly allowed
HERO_TITLE_LAYOUTS = {'cover', 'image-text', 'end'}

# Layouts that suppress the eyebrow (规范: title-only pages)
TITLE_ONLY_LAYOUTS = {'cover', 'agenda', 'big-stat'}


# ---------------------------------------------------------------------------
#  Issue collection
# ---------------------------------------------------------------------------

class Issues:
    def __init__(self):
        self.errors: list[tuple[str, str]] = []
        self.warnings: list[tuple[str, str]] = []

    def err(self, code, msg):     self.errors.append((code, msg))
    def warn(self, code, msg):    self.warnings.append((code, msg))


# ---------------------------------------------------------------------------
#  Slide extraction
# ---------------------------------------------------------------------------

def extract_slides(html: str) -> list[str]:
    """Return list of per-slide HTML strings (between each <div class='slide-frame'>)."""
    body_m = re.search(r'<body[^>]*>(.*)</body>', html, re.S)
    if not body_m:
        return []
    body = body_m.group(1)
    # Strip HTML comments FIRST so that any literal '<script>' / '</script>' text
    # inside comments doesn't confuse the script-tag stripper below.
    body = re.sub(r'<!--.*?-->', '', body, flags=re.S)
    # Now strip real script tags
    body = re.sub(r'<script[^>]*>.*?</script>', '', body, flags=re.S)
    parts = body.split('<div class="slide-frame">')
    return parts[1:]   # discard preamble before first slide-frame


def slide_attr(fr: str, name: str) -> str | None:
    m = re.search(rf'data-{name}="([^"]+)"', fr)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
#  Per-rule audits
# ---------------------------------------------------------------------------

def audit_structure(slides: list[str], iss: Issues):
    """R01-R02: every slide has data-layout, data-screen-label, .wordmark."""
    for i, fr in enumerate(slides, 1):
        layout = slide_attr(fr, 'layout')
        label  = slide_attr(fr, 'screen-label')
        if not layout:
            iss.err('R02', f'slide {i}: missing data-layout')
        if not label:
            iss.err('R02', f'slide {i}: missing data-screen-label')
        if 'class="wordmark' not in fr:
            iss.err('R07', f'slide {i} ({layout}): missing .wordmark')
        # .footer chrome was retired 2026-05 — fullscreen pager handles
        # page numbers, so no per-slide footer is required anymore.


def audit_titles_one_line(slides: list[str], iss: Issues):
    """R13: page-header titles are single-line (no <br>).

    Catches both `class="title-zh"` AND bare `class="title"` — the section
    recipe used to ship `<h2 class="title">` which previously slipped through.
    """
    for i, fr in enumerate(slides, 1):
        layout = slide_attr(fr, 'layout') or '?'
        if layout in HERO_TITLE_LAYOUTS:
            continue   # cover / image-text / end are allowed multi-line
        # Match h2 / h1 with class containing "title" or "title-zh"
        title_re = re.compile(
            r'<h[12][^>]*class="[^"]*\btitle(?:-zh)?\b[^"]*"[^>]*>(.*?)</h[12]>',
            re.S)
        for h in title_re.findall(fr):
            if '<br' in h:
                iss.err('R13',
                    f'slide {i} ({layout}): <br> inside header title — '
                    'titles must be one line on non-hero layouts')


def audit_brand_chrome(slides: list[str], iss: Issues, strict: bool):
    """R07: logo always colored unless explicit is-mono opt-in."""
    for i, fr in enumerate(slides, 1):
        if 'class="wordmark is-mono"' in fr or 'class="is-mono wordmark"' in fr:
            iss.warn('R07',
                f'slide {i}: mono-white logo used — verify this is an over-imagery edge case')


def audit_copy_rules(html: str, iss: Issues):
    """R05: no emoji / '!' / '…' / '???' anywhere in slide content."""
    body_m = re.search(r'<body[^>]*>(.*)</body>', html, re.S)
    if not body_m: return
    body = re.sub(r'<script.*?</script>', '', body_m.group(1), flags=re.S)
    body = re.sub(r'<style.*?</style>', '', body, flags=re.S)
    text = re.sub(r'<[^>]+>', ' ', body)

    # Emoji
    emoji_re = re.compile(r'[\U0001F300-\U0001FAFF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF]')
    if emoji_re.search(text):
        iss.err('R05', 'emoji detected in slide text')

    # Banned punctuation
    if '!' in text or '！' in text:
        iss.err('R05', "exclamation '!' / '！' detected in slide text")
    if '…' in text or '...' in text:
        iss.err('R05', "ellipsis '…' / '...' detected in slide text")
    if '???' in text or '???' in text or '？？？' in text:
        iss.err('R05', "'???' detected in slide text")


def audit_font_sizes(html: str, iss: Issues):
    """R06 / R17 / R18 / R19: font-size minimums on SLIDE CONTENT only.

    We walk every CSS rule and only flag font-size below floor when the
    rule's selector targets slide content (`.slide`). Selectors targeting
    `.deck-ui` (the auxiliary navigation overlay outside the slide) are
    exempt from the规范 floor — they're not slide content.
    """
    violations = []
    for style_m in re.finditer(r'<style[^>]*>(.*?)</style>', html, re.S):
        css = style_m.group(1)
        for rule_m in re.finditer(r'([^{}]+)\{([^}]+)\}', css):
            selector = rule_m.group(1).strip()
            block    = rule_m.group(2)
            # Skip auxiliary chrome (deck-UI overlay, deck-controls, deck-progress)
            if '.deck-ui' in selector or '.deck-controls' in selector \
               or '.deck-progress' in selector or '.mode-toggle' in selector \
               or '.nav-hint' in selector or '@' in selector:
                continue
            # Only check rules that target slide content
            if '.slide' not in selector and '.card' not in selector \
               and '.col' not in selector and '.toc' not in selector \
               and '.cell' not in selector and 'thead' not in selector \
               and 'tbody' not in selector:
                continue
            for m in re.finditer(r'font-size:\s*(\d+)px', block):
                size = int(m.group(1))
                if size < FLOOR_CHROME_PX:
                    violations.append((size, selector))
            for m in re.finditer(r'\bfont:\s*[^;{}]*?(\d+)px', block):
                size = int(m.group(1))
                if size < FLOOR_CHROME_PX:
                    violations.append((size, selector))
    if violations:
        for size, sel in violations[:10]:
            iss.err('R06',
                f'font-size {size}px on `{sel.strip()}` below {FLOOR_CHROME_PX}px slide-content floor')

    # Inline styles on slide markup
    body_m = re.search(r'<body[^>]*>(.*)</body>', html, re.S)
    if body_m:
        body = re.sub(r'<!--.*?-->', '', body_m.group(1), flags=re.S)
        body = re.sub(r'<script[^>]*>.*?</script>', '', body, flags=re.S)
        for m in re.finditer(r'style="[^"]*font-size:\s*(\d+)px', body):
            size = int(m.group(1))
            if size < FLOOR_CHROME_PX:
                iss.err('R06',
                    f'inline font-size {size}px below {FLOOR_CHROME_PX}px floor')


def audit_no_drop_shadows(html: str, iss: Issues):
    """R12: no DROP SHADOWS on slide content.

    A drop shadow has non-zero offset or non-zero blur:
        box-shadow: 0 8px 24px rgba(...)         ← shadow
        box-shadow: 4px 4px 12px #000             ← shadow
    A glow ring uses zero offset and blur, just spread:
        box-shadow: 0 0 0 6px rgba(...)           ← glow ring (allowed)
    Inset shadows are also allowed (decorative inner highlight).
    """
    glow_ring_re = re.compile(r'^\s*0\s+0\s+0(?:\s+\d+\w+)?\s')   # "0 0 0 [Npx ...]"
    inset_re     = re.compile(r'\binset\b')

    style_m = re.findall(r'<style[^>]*>(.*?)</style>', html, re.S)
    for css in style_m:
        for m in re.finditer(r'(\.slide[^{,]*)\s*\{([^}]*)\}', css):
            selector = m.group(1)
            block = m.group(2)
            # Skip allowed wrappers (UI mock window chrome is the documented
            # exception per "no drop shadows" rule — they're product UI mocks,
            # not slide content cards)
            if any(s in selector for s in ('frame', 'phone-frame',
                                            'desktop-frame', 'controls',
                                            'ui-window', 'ui-browser')):
                continue
            for sm in re.finditer(r'box-shadow:\s*([^;}]+)', block):
                value = sm.group(1).strip()
                if inset_re.search(value):
                    continue           # inset shadows OK
                if glow_ring_re.match(value):
                    continue           # 0 0 0 ... is a glow ring, not a shadow
                # Anything else with non-zero offset → real drop shadow
                iss.warn('R12',
                    f'real drop shadow on `{selector.strip()}` — `box-shadow: {value}` '
                    '(use hairline + contrast instead)')


def audit_data_decor(slides: list[str], iss: Issues):
    """R38: data-decor tokens come from the ship list."""
    for i, fr in enumerate(slides, 1):
        decor = slide_attr(fr, 'decor')
        if not decor:
            continue
        for token in decor.split():
            if token not in ALLOWED_DECOR:
                iss.err('R38',
                    f'slide {i}: unknown data-decor token {token!r} — '
                    f'must be one of {sorted(ALLOWED_DECOR)}')


def audit_hex_palette(html: str, iss: Issues, strict: bool):
    """R10: all hex values inside slide markup come from --fs-* tokens.

    Strips script/style/svg AND data: URIs first — base64 strings can
    contain '#xxx' false matches.
    """
    body_m = re.search(r'<body[^>]*>(.*)</body>', html, re.S)
    if not body_m: return
    body = re.sub(r'<script.*?</script>', '', body_m.group(1), flags=re.S)
    body = re.sub(r'<style.*?</style>', '', body, flags=re.S)
    body = re.sub(r'<svg.*?</svg>', '', body, flags=re.S)   # SVG decor may use raw hex
    body = re.sub(r'data:[^"\'\s)]+', '', body)             # strip data: URIs (base64 false matches)
    hexes = Counter(h.lower() for h in re.findall(r'#([0-9A-Fa-f]{3,6})\b', body))
    extras = {h: c for h, c in hexes.items() if h not in ALLOWED_HEX}
    if extras:
        msg = ', '.join(f'#{h}×{c}' for h, c in sorted(extras.items()))
        if strict:
            iss.err('R10', f'hex values outside palette in slide markup: {msg}')
        else:
            iss.warn('R10', f'hex values outside palette in slide markup: {msg}')


def audit_runtime_chrome(html: str, iss: Issues):
    """R29-R32: present-mode chrome is shipped.

    DOM needles can live either in static markup OR be injected by JS at
    runtime (the runtime builds .deck-controls via innerHTML). So we check
    the full document for those. JS-API needles (requestFullscreen /
    fullscreenchange) must appear inside a <script> block.
    """
    script_blocks = ' '.join(re.findall(r'<script[^>]*>(.*?)</script>', html, re.S))

    # DOM/CSS — JS-injected innerHTML strings count
    dom_needles = [
        ('deck-progress',     'top progress bar element / class'),
        ('deck-controls',     'bottom control pill element / class'),
        ('class="ctl prev"',  'prev button'),
        ('class="ctl next"',  'next button'),
        ('class="ctl fs"',    'fullscreen button'),
        ('--fs-grad-keyline', 'progress bar uses brand gradient'),
        ('is-idle',           'auto-idle fade'),
    ]
    # API needles — must be invoked from script
    js_needles = [
        ('requestFullscreen', 'fullscreen API call'),
        ('fullscreenchange',  'fullscreenchange listener'),
    ]
    for needle, desc in dom_needles:
        if needle not in html:
            iss.err('R29-32', f'present-mode chrome missing: {desc} ({needle!r})')
    for needle, desc in js_needles:
        if needle not in script_blocks:
            iss.err('R29-32', f'present-mode chrome missing in JS: {desc} ({needle!r})')


def audit_centering_pattern(html: str, iss: Issues):
    """R36: present-mode uses absolute + negative margin (not grid place-items).

    Whitespace-tolerant: accepts `margin:-540px 0 0 -960px` /
    `margin: -540px 0 0 -960px` / etc.
    """
    margin_re = re.compile(r'margin:\s*-540px\s+0\s+0\s+-960px')
    if not margin_re.search(html):
        iss.err('R36',
            'present-mode slide centering is not the absolute + negative-margin '
            'pattern (margin: -540px 0 0 -960px) — grid place-items can cause '
            'transform clipping')
    grid_re = re.compile(
        r'data-mode="present"\]\s+\.slide-frame\s*\{[^}]*display:\s*grid', re.S)
    if grid_re.search(html):
        iss.err('R36',
            'present-mode .slide-frame still uses display:grid — switch to absolute '
            'positioning for the slide so transform/overflow clipping is deterministic')


# ---------------------------------------------------------------------------
#  Performance budget — P1-P5 (the perf review findings)
# ---------------------------------------------------------------------------

PERF_BASE64_WARN_KB    = 100   # base64 payload in <style> warns above this
PERF_BASE64_ERROR_KB   = 250   # …becomes error above this in --strict
PERF_BLUR_MAX_PX       = 10    # backdrop-filter blur radius cap


def audit_perf(html: str, iss: Issues, strict: bool):
    """P50–P55: performance budget checks.

    Catches the regressions that gave us a 365 KB deck and per-pixel
    mousemove handlers. Each check has a concrete fix in SKILL.md.

    Inlined-mode opt-in: a deck explicitly marked `<meta name="fs-deck-mode"
    content="inline">` (e.g. by build.sh --inline) skips P50 since base64
    inlining is the whole point of that mode.
    """
    # Detect intentional inline-delivery mode
    inline_mode = bool(re.search(
        r'<meta[^>]*name="fs-deck-mode"[^>]*content="inline"', html))

    # Extract style + script text once (used by P50 / P51 / P54 / P55)
    style_text  = ' '.join(re.findall(r'<style[^>]*>(.*?)</style>',  html, re.S))
    script_text = ' '.join(re.findall(r'<script[^>]*>(.*?)</script>', html, re.S))

    # --- P50: base64 payload inside <style> (linked mode only) ---
    if not inline_mode:
        base64_bytes = sum(len(m.group(0)) for m in
                           re.finditer(r'data:image/[^"\'\s)]+', style_text))
        base64_kb = base64_bytes // 1024
        if base64_kb >= PERF_BASE64_ERROR_KB:
            iss.err('P50',
                f'inline base64 in <style>: {base64_kb} KB ≥ {PERF_BASE64_ERROR_KB} KB hard cap. '
                'Use linked assets (<link rel="stylesheet"> + external --fs-asset-* '
                'image files) for the default delivery; inline only for single-file '
                'email/IM mode (build.sh --inline). If this IS intentional inline mode, '
                'add `<meta name="fs-deck-mode" content="inline">` in <head>.')
        elif base64_kb >= PERF_BASE64_WARN_KB:
            msg = (f'inline base64 in <style>: {base64_kb} KB ≥ {PERF_BASE64_WARN_KB} KB '
                   'soft budget. Use linked CSS for default delivery, or add '
                   '`<meta name="fs-deck-mode" content="inline">` to mark this as '
                   'intentional single-file mode.')
            if strict: iss.err('P50', msg)
            else:      iss.warn('P50', msg)

    # --- P51: backdrop-filter blur radius cap ---
    for m in re.finditer(r'backdrop-filter:\s*blur\((\d+)px\)', html):
        radius = int(m.group(1))
        if radius > PERF_BLUR_MAX_PX:
            iss.warn('P51',
                f'backdrop-filter: blur({radius}px) exceeds {PERF_BLUR_MAX_PX}px '
                'cap — GPU cost scales with blur radius. Use opaque rgba '
                'background instead, or ≤ 8px blur.')

    # --- P52: ResizeObserver count (one per frame is bad — should be 1 total) ---
    ro_count = len(re.findall(r'new\s+ResizeObserver\(', script_text))
    if ro_count > 1:
        iss.warn('P52',
            f'JS instantiates {ro_count} ResizeObservers — one per frame causes '
            f'{ro_count}× layout reads on every viewport change. Use one '
            'document-level RO with rAF batching that iterates frames.forEach.')

    # --- P53: addEventListener without AbortController / removeEventListener ---
    add_count = script_text.count('addEventListener')
    has_abort_controller = 'AbortController' in script_text or 'controller.abort' in script_text
    rm_count = script_text.count('removeEventListener')
    if add_count >= 8 and not has_abort_controller and rm_count == 0:
        iss.warn('P53',
            f'JS binds {add_count} addEventListener calls with no AbortController '
            'and no removeEventListener. Embedding the deck in an SPA host '
            'leaks listeners on every re-mount. Wrap init() in a single '
            'AbortController and pass {{ signal }} to every addEventListener.')

    # --- P54: missing CSS containment hint on .slide-frame ---
    if '.slide-frame' in style_text and 'contain:' not in style_text:
        iss.warn('P54',
            '.slide-frame has no `contain:` hint. Adding `contain: layout paint '
            'size` lets the browser scope reflows to the frame, turning slide '
            'changes from full-document repaints into local ones.')

    # --- P55: missing will-change on the scaled .slide ---
    slide_rule = re.search(r'\.slide-frame\s+\.slide\s*\{([^}]*)\}', style_text, re.S)
    if slide_rule and 'will-change' not in slide_rule.group(1):
        iss.warn('P55',
            '.slide-frame .slide has no `will-change: transform` hint. Without '
            'it, the scale transform may not get a GPU layer, causing CPU '
            'rasterization on every transition.')


# ---------------------------------------------------------------------------
#  Layout integrity rules L1–L4 (the LKK exchange deck failure modes)
# ---------------------------------------------------------------------------

def check_logo_default(html: str) -> bool:
    """Rule L1: wordmark default must reference --fs-asset-logo (color)."""
    m = re.search(r'\.slide \.wordmark\s*\{[^}]*background:\s*([^;]+);', html, re.DOTALL)
    if not m:
        return False
    decl = m.group(1)
    return 'asset-logo)' in decl and 'asset-logo-mono' not in decl


def check_balance(html: str) -> tuple[bool, str | None]:
    """Rule L2: every body-content stage of layouts that often run short
    must vertically center the row OR explicitly grow to fill.

    We accept either `align-content: center` on the container OR `flex: 1`
    declared somewhere in the layout block as evidence that the author
    consciously handled vertical balance. We also accept .stage / .grid /
    .flow / .nodes as canonical container names.
    """
    # NOTE: 'timeline' is intentionally excluded. Its .axis line is absolutely
    # positioned at a fixed slide y, and its .node dots are at a fixed y inside
    # each .node — vertical-centering the .nodes row shifts the dots down by
    # (zone_h - row_h)/2 and unaligns them from the axis line. Timeline accepts
    # an empty-bottom tradeoff to keep axis-dot alignment.
    layouts_with_short_content = (
        'content-2col', 'process', 'content-3up', 'pipeline')
    aliases = ('stage', 'grid', 'flow', 'nodes')
    for layout in layouts_with_short_content:
        ok = False
        for alias in aliases:
            pattern = rf'\.slide\[data-layout="{layout}"\]\s+\.{alias}\s*\{{([^}}]*)\}}'
            for m in re.finditer(pattern, html, re.DOTALL):
                block = m.group(1)
                if 'align-content: center' in block \
                   or 'justify-content: center' in block \
                   or 'flex: 1' in block:
                    ok = True; break
            if ok: break
        # If the layout isn't even used in this deck, skip
        if f'data-layout="{layout}"' not in html:
            continue
        if not ok:
            return False, layout
    return True, None


def check_attrs_density(html: str) -> bool:
    """Rule L4: process output attrs should be 1-col when output panel is narrow."""
    m = re.search(
        r'\.slide\[data-layout="process"\]\s+\.output\s+\.attrs\s*\{[^}]*\}',
        html, re.DOTALL)
    if not m:
        return True   # no output panel in deck → rule N/A
    return 'grid-template-columns: 1fr;' in m.group(0)


def check_default_centering(css: str):
    """Container layouts that aren't pipeline/timeline/process should center
    vertically by default. Yields the layout name for each violation.

    Spec uses `.stage` as the canonical container name. We also accept the
    historical aliases `.grid / .toc / .flow / .nodes / .stack` because
    individual layouts in this skill use those names.
    """
    centerable = ('content-3up', 'content-2col', 'agenda',
                  'stats', 'big-stat', 'quote')
    container_aliases = ('stage', 'grid', 'toc', 'flow', 'nodes', 'stack')
    for layout in centerable:
        ok = False
        for alias in container_aliases:
            pattern = rf'\.slide\[data-layout="{layout}"\]\s+\.{alias}\s*\{{([^}}]*)\}}'
            for m in re.finditer(pattern, css, re.DOTALL):
                block = m.group(1)
                if 'justify-content: center' in block \
                   or 'align-content: center' in block \
                   or 'place-content: center' in block \
                   or 'align-items: center' in block:
                    ok = True; break
            if ok: break
        if not ok:
            yield layout


def audit_header_minimal(slides: list[str], iss: Issues):
    """R56: content-page .header contains only a single <h2> title.

    The CSS already hides .header .eyebrow visually. This audit also flags
    the markup so it stays clean. Permitted: <h2>...</h2>. Forbidden inside
    .header: .eyebrow, .pageno, inline subtitles. The agenda layout's `.en`
    sub-line is a documented exception (it's the bilingual EN translation
    of the agenda title, kept alongside the title).
    """
    for i, fr in enumerate(slides, 1):
        layout = slide_attr(fr, 'layout') or '?'
        # Hero layouts use .stage not .header — skip
        if layout in HERO_TITLE_LAYOUTS or layout in ('cover','section','quote','end'):
            continue
        # Find .header blocks
        for hdr in re.findall(r'<div class="header">(.*?)</div>\s*(?=<div)', fr, re.S):
            if '<div class="eyebrow"' in hdr or 'class="eyebrow"' in hdr:
                iss.warn('R56',
                    f'slide {i} ({layout}): .header still contains an .eyebrow. '
                    'CSS hides it visually but the markup should be removed too '
                    '— the content-page header is title-only.')
            # .pageno was retired 2026-05 — no warning needed; rule
            # only flags the historical "eyebrow inside header" footgun.


def audit_no_cyan_accent(slides: list[str], iss: Issues):
    """R49: cyan (#24C3FF) is INLINE-WORD-HIGHLIGHT only — never a slide accent.

    Scans slide markup for `data-accent="cyan"` on `.slide` or its children.
    Cyan inline highlight via `.accent-text` / `.hl` / `.ui-pill[data-tone="cyan"]`
    is allowed (handled at the inline level, not the slide level).
    """
    for i, fr in enumerate(slides, 1):
        if re.search(r'data-accent="cyan"', fr):
            iss.err('R49',
                f'slide {i}: data-accent="cyan" — cyan #24C3FF is reserved for '
                'inline word highlight (.accent-text / .hl), never as the slide '
                'accent. Use blue / teal / purple / violet / orange instead.')


def audit_default_centering(html: str, iss: Issues):
    """R48: every fixed-shape container layout vertically centers by default."""
    for style_m in re.finditer(r'<style[^>]*>(.*?)</style>', html, re.S):
        css = re.sub(r'/\*.*?\*/', '', style_m.group(1), flags=re.S)
        for missing in check_default_centering(css):
            iss.err('R48',
                f'data-layout="{missing}" container has no vertical-centering '
                'rule (justify-content / align-content / align-items: center). '
                'Fixed-shape layouts must default-center so short content '
                'doesn\'t strand at the top with empty bottom. pipeline / '
                'timeline / process are explicit exceptions that fill.')


def audit_variant_discipline(html: str, iss: Issues):
    """R47: variant override discipline.

    For every CSS rule whose selector contains [data-variant=...], if the
    block declares a STRUCTURAL property — meaning it actually changes layout
    engine or direction — it MUST ALSO redeclare both align-items (or place-
    items) AND justify-content (or place-content).

    What counts as structural:
      - display: flex/grid/block/inline-*/table  (NOT none/contents — those
        are hide-or-flatten, not layout changes)
      - flex-direction, flex-wrap, flex-flow
      - grid-template-* / grid-auto-*

    Cosmetic-only variants (color, padding, gap, font, just `display: none`
    on a pseudo-element to hide an arrow) are exempt.

    Selectors that target a pseudo-element (::before / ::after / ::placeholder)
    are also exempt — they're decorative bits, not layout containers.
    """
    layout_display_values = ('flex', 'grid', 'block', 'inline-block',
                             'inline-flex', 'inline-grid', 'inline', 'table',
                             'table-row', 'table-cell')
    structural_triggers = (
        'flex-direction:', 'flex-wrap:', 'flex-flow:',
        'grid-template-columns:', 'grid-template-rows:', 'grid-template-areas:',
        'grid-auto-flow:', 'grid-auto-columns:', 'grid-auto-rows:',
    )
    align_props = ('align-items:', 'place-items:')
    justify_props = ('justify-content:', 'place-content:')

    for style_m in re.finditer(r'<style[^>]*>(.*?)</style>', html, re.S):
        css = style_m.group(1)
        # Strip CSS comments so they don't contaminate selector reports
        css = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
        for rule_m in re.finditer(r'([^{}]+)\{([^}]+)\}', css):
            selector = rule_m.group(1).strip()
            block    = rule_m.group(2)
            if '[data-variant' not in selector:
                continue
            # Skip pseudo-element-targeting variants (decorative)
            if '::before' in selector or '::after' in selector \
               or '::placeholder' in selector or '::marker' in selector:
                continue
            # Does the variant touch real layout structure?
            touches_structure = any(t in block for t in structural_triggers)
            # Check display: but ignore none/contents (hides, not layout changes)
            for d_m in re.finditer(r'display:\s*([a-z-]+)', block):
                if d_m.group(1) in layout_display_values:
                    touches_structure = True; break
            if not touches_structure:
                continue   # cosmetic-only variant — exempt
            # If structural, must redeclare alignment + justification
            has_align   = any(p in block for p in align_props)
            has_justify = any(p in block for p in justify_props)
            if not (has_align and has_justify):
                missing = []
                if not has_align:   missing.append('align-items / place-items')
                if not has_justify: missing.append('justify-content / place-content')
                iss.warn('R47',
                    f'variant `{selector.strip()}` changes structure (display/flex/grid) '
                    f'but does not redeclare {", ".join(missing)}. '
                    'Variants that change layout direction must redeclare every '
                    'directional property explicitly — cascade does not auto-reset them.')


def audit_ui_mocks_are_html(slides: list[str], iss: Issues):
    """Rule UI1: System UI / screenshots must be re-rendered as HTML, not raster.

    We scan slide markup for <img> tags whose src looks like a UI screenshot
    (jpg/png file referenced from a non-photo path). Photographic content
    via data-decor="photo-bg" or .col-visual / image-text full-bleed bg
    is fine — that's a real photograph, not a UI mock.
    Any inline <img> inside slide content is a yellow flag — usually it's
    a developer who pasted a screenshot instead of building HTML. WARN.
    """
    for i, fr in enumerate(slides, 1):
        for m in re.finditer(r'<img\s[^>]*src="([^"]+)"', fr):
            src = m.group(1)
            # Allow data: URIs (likely intentional inline asset)
            if src.startswith('data:'): continue
            # Allow the brand asset dir (logo, slogan)
            if 'lark-logo' in src or 'lark-slogan' in src or 'lark-cover' in src \
               or 'lark-section' in src or 'lark-content' in src:
                continue
            # Otherwise: probably a UI screenshot — recreate as HTML instead
            iss.warn('UI1',
                f'slide {i}: <img src="{src}"> in slide content — if this is a '
                'system UI / app screenshot, recreate it as HTML using the .ui-* '
                'primitives (window/sidebar/toolbar/list/cell/etc.) instead of '
                'raster. HTML mocks scale crisply, harmonize with brand fonts, '
                'and avoid pixelation in fullscreen. Pure photographs are fine.')


TEXT_ID_RE = re.compile(r'data-text-id="([^"]+)"')
TEXT_ID_VALID_RE = re.compile(r'^slide-\d+\.[\w.\-]+$')


def audit_text_ids(html: str, html_path: Path, iss: Issues):
    """T01-T03: data-text-id correctness + sync with paired texts.md.

    - T01: every data-text-id matches the canonical pattern.
    - T02: data-text-id values are unique within the deck.
    - T03: if a paired texts.md sits next to the HTML, its id set matches.

    A deck with NO data-text-id at all gets a single warning (texts.md
    sidecar missing), not 200 individual errors — legacy / external decks
    still pass through.
    """
    body_m = re.search(r'<body[^>]*>(.*)</body>', html, re.S)
    body = body_m.group(1) if body_m else html
    # Strip HTML comments FIRST so '<script>' / '</script>' literals inside
    # comments don't confuse the script-tag stripper (same defense used by
    # extract_slides above).
    body = re.sub(r'<!--.*?-->',         '', body, flags=re.S)
    body = re.sub(r'<script.*?</script>', '', body, flags=re.S)
    body = re.sub(r'<style.*?</style>',   '', body, flags=re.S)
    ids = TEXT_ID_RE.findall(body)

    if not ids:
        iss.warn('T00',
            'no data-text-id attributes found — text-edit sidecar (texts.md) '
            'is missing. New decks generated by this skill MUST annotate every '
            'text leaf and ship a paired texts.md. See SKILL.md "TEXT-EDIT '
            'SIDECAR" section, or run `assets/extract-texts.py` to retrofit.')
        return

    # T01 — id format
    bad = [tid for tid in ids if not TEXT_ID_VALID_RE.match(tid)]
    for tid in bad[:10]:
        iss.err('T01',
            f'data-text-id={tid!r} does not match `slide-NN.field` pattern.')

    # T02 — uniqueness
    counts = Counter(ids)
    dups = [(tid, n) for tid, n in counts.items() if n > 1]
    for tid, n in dups[:10]:
        iss.err('T02', f'duplicate data-text-id {tid!r} appears {n}× in deck.')

    # T03 — sync with paired texts.md (best-effort, soft errors)
    # Resolution order: more-specific `<basename>.texts.md` first, then
    # generic `texts.md` in the same directory. This way a per-run folder
    # `runs/<ts>/output/{index.html, texts.md}` works, and an example
    # `examples/{sample-deck.html, sample-deck.texts.md}` also works,
    # without ambiguity if both happen to exist.
    specific = html_path.with_suffix('.texts.md')
    generic  = html_path.parent / 'texts.md'
    if specific.is_file():
        sidecar = specific
    elif generic.is_file():
        sidecar = generic
    else:
        iss.warn('T03',
            f'paired sidecar not found at {specific.name} or '
            f'{generic.name} — user cannot edit texts.md and reapply. '
            'Generate it with `assets/extract-texts.py`.')
        return

    md_ids = _parse_texts_md_ids(sidecar.read_text(encoding='utf-8'))
    html_ids = set(ids)
    missing_md = sorted(html_ids - md_ids)
    extra_md   = sorted(md_ids - html_ids)
    if missing_md:
        iss.err('T03',
            f'{len(missing_md)} ids in HTML are missing from {sidecar.name} '
            f'(e.g. {", ".join(missing_md[:3])}). Re-run extract-texts.py '
            'to regenerate the sidecar.')
    if extra_md:
        iss.err('T03',
            f'{len(extra_md)} ids in {sidecar.name} are not present in HTML '
            f'(e.g. {", ".join(extra_md[:3])}). Either the HTML drifted or '
            'the sidecar is stale.')


def _parse_texts_md_ids(md: str) -> set[str]:
    """Extract the set of full ids declared in a texts.md file."""
    ids: set[str] = set()
    current_slide: str | None = None
    slide_hdr = re.compile(r'^##\s+(slide-\d+)\b')
    kv = re.compile(r'^([A-Za-z0-9_.\-]+)\s*:')
    for line in md.splitlines():
        line = line.rstrip()
        if not line or line.startswith('>'):
            continue
        m = slide_hdr.match(line)
        if m:
            current_slide = m.group(1); continue
        if line.startswith('#'):
            continue
        m = kv.match(line)
        if m and current_slide:
            ids.add(f'{current_slide}.{m.group(1)}')
    return ids


def audit_layout_integrity(html: str, iss: Issues):
    """Run all four LKK-exchange-deck integrity checks (L1-L4)."""
    if not check_logo_default(html):
        iss.err('L1',
            '.slide .wordmark default does NOT reference var(--fs-asset-logo). '
            'Mono-white must be opt-in via .is-mono — color is the规范 default.')

    ok, broken_layout = check_balance(html)
    if not ok:
        iss.err('L2',
            f'data-layout="{broken_layout}" body-content container missing '
            'vertical-centering rule (align-content: center) AND not declared '
            'flex: 1. Short content will stack at top with empty bottom — '
            'the most-reported "looks unfinished" bug.')

    if not check_attrs_density(html):
        iss.err('L4',
            '.slide[data-layout="process"] .output .attrs is NOT '
            'grid-template-columns: 1fr. The output panel is ~400 px wide; '
            'a 2-col grid truncates 22 px body text. Use a single column.')


# ---------------------------------------------------------------------------
#  Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description='feishu-deck-h5 self-check')
    p.add_argument('html', help='Path to the assembled deck HTML file')
    p.add_argument('--strict', action='store_true',
                   help='Promote warnings to errors')
    args = p.parse_args()

    path = Path(args.html)
    if not path.is_file():
        print(f'ERROR: file not found: {path}', file=sys.stderr)
        return 2

    html = path.read_text(encoding='utf-8')

    # Resolve linked stylesheets and scripts so audits can see their content
    # (the linked-mode deck doesn't inline CSS/JS — without this, runtime-chrome
    # and centering-pattern audits would false-fail).
    def inline_linked(html_text, base_dir):
        # <link rel="stylesheet" href="...css">
        def repl_link(m):
            href = m.group(1)
            if href.startswith(('http:', 'https:', 'data:')): return m.group(0)
            target = (base_dir / href).resolve()
            if not target.is_file(): return m.group(0)
            return '<style>' + target.read_text(encoding='utf-8') + '</style>'
        html_text = re.sub(
            r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>',
            repl_link, html_text)
        # <script src="...js"></script>
        def repl_script(m):
            src = m.group(1)
            if src.startswith(('http:', 'https:', 'data:')): return m.group(0)
            target = (base_dir / src).resolve()
            if not target.is_file(): return m.group(0)
            return '<script>' + target.read_text(encoding='utf-8') + '</script>'
        html_text = re.sub(
            r'<script[^>]*src="([^"]+)"[^>]*>\s*</script>',
            repl_script, html_text)
        return html_text
    html = inline_linked(html, path.parent)

    slides = extract_slides(html)

    iss = Issues()
    audit_structure(slides, iss)
    audit_titles_one_line(slides, iss)
    audit_brand_chrome(slides, iss, args.strict)
    audit_copy_rules(html, iss)
    audit_font_sizes(html, iss)
    audit_no_drop_shadows(html, iss)
    audit_data_decor(slides, iss)
    audit_hex_palette(html, iss, args.strict)
    audit_runtime_chrome(html, iss)
    audit_centering_pattern(html, iss)
    audit_layout_integrity(html, iss)
    audit_default_centering(html, iss)
    audit_variant_discipline(html, iss)
    audit_ui_mocks_are_html(slides, iss)
    audit_no_cyan_accent(slides, iss)
    audit_header_minimal(slides, iss)
    audit_perf(html, iss, args.strict)
    audit_text_ids(html, path, iss)

    if args.strict:
        iss.errors.extend(iss.warnings)
        iss.warnings = []

    print(f'feishu-deck-h5 validator  ·  {path.name}')
    print(f'  slides: {len(slides)}')
    print(f'  errors:   {len(iss.errors)}')
    print(f'  warnings: {len(iss.warnings)}')

    if iss.errors:
        print('\nERRORS')
        for code, msg in iss.errors:
            print(f'  ✗ [{code}] {msg}')
    if iss.warnings:
        print('\nWARNINGS')
        for code, msg in iss.warnings:
            print(f'  ! [{code}] {msg}')

    if iss.errors:
        print('\nFAIL — fix the errors above before delivering.')
        return 1
    print('\nPASS — all programmatic checks satisfied.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
