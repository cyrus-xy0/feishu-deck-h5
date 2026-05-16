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
import functools, re, sys, argparse
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

# Layouts where 2-line hero titles (with `<br>`) are explicitly allowed.
# `image-text` is included because the recipe + sample-deck both author
# `<h2>现场决策,<br>从未离线</h2>` over a full-bleed photo, which reads
# as a hero composition (title at bottom-left over the image), not a
# normal content-page header. Master spec may revisit this — if so,
# update both the recipe in templates/slide-recipes.html and SKILL.md
# §"Available layouts" together with this set.
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
            continue   # cover / image-text / end allow multi-line hero titles
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
    # Strip SVG content too — inline SVG can carry <title>foo</title> /
    # <desc> for a11y and those texts are NOT slide copy. Without this,
    # any SVG with a `!` in its accessible title falsely triggers R05.
    # (audit_hex_palette already strips SVG for the same family of reasons.)
    body = re.sub(r'<svg.*?</svg>', '', body, flags=re.S | re.I)
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


_STYLE_BLOCK_RE = re.compile(
    r'<style(?P<attrs>[^>]*)>(?P<body>.*?)</style>', re.S)


def _iter_style_blocks(html: str, *, include_framework: bool = True):
    """Iterate `<style>` block contents in `html`.

    Yields `(css_text, is_framework)` tuples. The is_framework flag is
    True for `<style data-source="framework">` blocks (CSS files inlined
    by inline_linked() in main()).

    Audits that police AUTHOR CSS (R-WHITE-TEXT, R47, …) should call
    with `include_framework=False` — framework master-spec rules have
    their own review process and are exempt from the per-deck audit.

    Audits that need ALL CSS (R29-R32 chrome, R36 centering pattern,
    R20 per-page ladder) call with the default `include_framework=True`.
    """
    for m in _STYLE_BLOCK_RE.finditer(html):
        attrs = m.group('attrs') or ''
        is_framework = 'data-source="framework"' in attrs
        if is_framework and not include_framework:
            continue
        yield m.group('body'), is_framework


# Module-level compiled regexes used by hot-path audits. Hoisted out of
# function bodies so they compile ONCE per process, not per-call. The
# `re` module caches but the explicit pattern at module scope is clearer.

# Rule pattern allowing inline `/* ... */` comments inside the body.
# Selector is non-brace chars (non-greedy); body is a sequence of either
# a CSS comment or non-brace chars. Used by audits that need to see the
# raw comment text (e.g. /* allow:white-opacity */ markers) without
# making a second pass through the source.
_RULE_WITH_COMMENTS_RE = re.compile(
    r'([^{}]+?)\{((?:/\*.*?\*/|[^{}])*)\}',
    re.S,
)


_AT_RULE_RE = re.compile(r'@[a-zA-Z-]+[^{]*\{(?:[^{}]|\{[^{}]*\})*\}', re.S)


@functools.lru_cache(maxsize=64)
def _strip_nested_at_rules(css: str) -> str:
    """Remove `@media`, `@keyframes`, `@supports`, `@font-face` blocks
    (and any other `@thing { ... }`) from CSS before flat-rule scanning.

    The audits use `([^{}]+)\\{([^}]+)\\}` to extract `selector { block }`
    pairs. That regex assumes no nested braces — but real CSS has `@media`
    / `@keyframes` blocks that wrap inner rules with their own braces.
    Without stripping, the regex either:
        a) captures the @media wrapper as a "selector" with the FIRST
           inner brace pair as its "block", missing every other rule
           inside that @block, OR
        b) captures inner rules but with the @-rule still semantically
           wrapping them, so e.g. R20's `[data-page]` scope check
           accidentally matches `@media` query expressions.

    Stripping nested @-rules before the scan gives every audit a clean
    flat CSS to walk. We do this destructively (no preservation) because
    the audits only need to evaluate top-level rule blocks; nested rules
    inside @media etc. are responsive variants that aren't subject to
    the body-floor / type-ladder / drop-shadow rules anyway.

    Cached (perf fix 2026-05-16): 7 audits each call this on the same
    `<style>` block contents per validate run. With LRU caching keyed on
    the raw CSS string, the strip runs once per unique input; subsequent
    calls (~85% on a CTG-sized deck) hit the cache. Cache lifetime is
    process-scoped; one validate run = one process, so no cross-deck
    leak. Cache size 64 covers any realistic deck (a deck has ≤ 20
    distinct `<style>` blocks even after framework inlining).
    """
    # Iterate until no change — pathological inputs would converge slowly,
    # so cap at 10 passes.
    prev = None
    out = css
    for _ in range(10):
        prev = out
        out = _AT_RULE_RE.sub('', out)
        if out == prev:
            break
    return out


def audit_font_sizes(html: str, iss: Issues):
    """R06 / R17 / R18 / R19: font-size minimums on SLIDE CONTENT only.

    We walk every CSS rule and only flag font-size below floor when the
    rule's selector targets slide content (`.slide`). Selectors targeting
    `.deck-ui` (the auxiliary navigation overlay outside the slide) are
    exempt from the规范 floor — they're not slide content.
    """
    violations = []
    for style_m in re.finditer(r'<style[^>]*>(.*?)</style>', html, re.S):
        css = _strip_nested_at_rules(style_m.group(1))
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
            # Same opt-out as R20 — rung 8 mockup-internal text (10–13 px) is
            # legitimate per SKILL.md when the parent is a UI mockup. Authors
            # mark such rules with /* allow:typescale */ so both R06 and R20
            # ignore them.
            if 'allow:typescale' in block:
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


TYPE_LADDER_PX = {
    10, 11, 12, 13,        # rung 8 — mockup-internal text only
    14,                    # rung 7 — chrome (footnote, pageno, eyebrow caps)
    18,                    # rung 6 — pill / sub-meta
    22,                    # rung 5 — body floor
    28,                    # rung 4 — col-title / lede
    38,                    # rung 3 — content sub-heading
    44,                    # rung 2 — slide title (per SKILL ladder)
    52,                    # master-spec — unified `.header .title-zh`
    56,                    # master-spec — content-3up `.num`
    64,                    # master-spec — `.slide .title-zh` global baseline
    88,                    # master-spec — section h2, hero KPI
    100,                   # rung 1 — cover hero
    132,                   # master-spec — `.bigstat-num`
    160,                   # master-spec — chapter-num
}


def audit_type_ladder(html: str, iss: Issues):
    """R20: every per-page font-size MUST be on the modular type-scale.

    Scope: only rules whose selector contains `[data-page="NN"]`. The global
    framework stylesheet (feishu-deck.css) is the authoritative master spec
    for cover / section / big-stat etc. and has its own review process; this
    rule targets the per-page `<style>` blocks where agents improvise card
    typography and go off-ladder (16/17/19/20/24/26/32/36/40/48/64*/72/96 etc.).

    Genuine master-spec exceptions opt out by adding `/* allow:typescale */`
    in the same rule block. Use sparingly and document why.
    """
    seen = set()
    for style_m in re.finditer(r'<style[^>]*>(.*?)</style>', html, re.S):
        css = style_m.group(1)
        # Strip CSS comments first so they can't pollute selector capture
        css_clean = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
        # Strip nested @-blocks (media/keyframes/supports) — the rule
        # regex below can't handle nested braces.
        css_clean = _strip_nested_at_rules(css_clean)
        for rule_m in re.finditer(r'([^{}]+)\{([^}]+)\}', css_clean):
            selector = rule_m.group(1).strip()
            block    = rule_m.group(2)
            # Only audit per-page rules (where agents author improvised CSS)
            if '[data-page=' not in selector:
                continue
            if '@' in selector:
                continue
            if 'allow:typescale' in block:
                continue
            sizes = []
            for m in re.finditer(r'font-size:\s*(\d+)px', block):
                sizes.append(int(m.group(1)))
            for m in re.finditer(r'\bfont:\s*[^;{}]*?(\d+)px', block):
                sizes.append(int(m.group(1)))
            for size in sizes:
                if size in TYPE_LADDER_PX:
                    continue
                key = (size, selector[:80])
                if key in seen:
                    continue
                seen.add(key)
                nearest = min(TYPE_LADDER_PX, key=lambda r: abs(r - size))
                iss.err('R20',
                    f'font-size {size}px on `{selector[:80]}` is off-ladder; '
                    f'nearest rung = {nearest}px '
                    f'(allowed: 14 chrome / 18 pill / 22 body / 28 sub-title / '
                    f'38 / 44 / 52 / 56 / 64 / 88 / 100 / 132 / 160). '
                    f'Add /* allow:typescale */ in the rule to override.')


def audit_no_drop_shadows(html: str, iss: Issues):
    """R12: no DROP SHADOWS on slide content.

    A drop shadow has non-zero offset or non-zero blur:
        box-shadow: 0 8px 24px rgba(...)         ← shadow
        box-shadow: 4px 4px 12px #000             ← shadow
    A glow ring uses zero offset and blur, just spread:
        box-shadow: 0 0 0 6px rgba(...)           ← glow ring (allowed)
    Inset shadows are also allowed (decorative inner highlight).

    Exemption: real drop shadows on UI-mock window chrome (`.ui-window`
    / `.phone-frame` / `.desktop-frame` etc.) are legitimate — those
    primitives recreate macOS app windows where a soft depth shadow is
    part of the simulation. Mark such rules with `/* allow:drop-shadow */`
    in the same block to opt out (same convention as R20's
    /* allow:typescale */ and R-WHITE-TEXT's /* allow:white-opacity */).
    """
    glow_ring_re = re.compile(r'^\s*0\s+0\s+0(?:\s+\d+\w+)?\s')   # "0 0 0 [Npx ...]"
    inset_re     = re.compile(r'\binset\b')

    style_m = re.findall(r'<style[^>]*>(.*?)</style>', html, re.S)
    for raw_css in style_m:
        css = _strip_nested_at_rules(raw_css)
        # Walk rule blocks but preserve raw text per-rule so we can detect
        # the /* allow:drop-shadow */ marker (it survives comment-stripping
        # because we never strip comments in audit_no_drop_shadows).
        for m in re.finditer(r'(\.slide[^{,]*)\s*\{([^}]*)\}', css):
            selector = m.group(1)
            block = m.group(2)
            if 'allow:drop-shadow' in block:
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
                    '(use hairline + contrast instead, OR add '
                    '/* allow:drop-shadow */ in the rule if this is a UI-mock '
                    'window chrome that legitimately needs depth shadow)')


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


def audit_runtime_chrome(html: str, iss: Issues, html_path: 'Path'):
    """R29-R32: present-mode chrome is shipped.

    DOM needles can live either in static markup OR be injected by JS at
    runtime (the runtime builds .deck-controls via innerHTML). JS-API
    needles (requestFullscreen / fullscreenchange) must appear inside a
    <script> block.

    Linked JS via `<script src="…">` is loaded from disk (relative to
    the HTML file) and concatenated into the searchable text — without
    this, decks that link feishu-deck.js externally would always fail
    the audit even though they work fine in browser.
    """
    # main()'s `inline_linked` has already inlined every resolvable
    # `<script src="...">` into a `<script data-source="framework">…</script>`
    # block, so the framework JS body is captured by the findall below
    # WITHOUT a second disk read here.
    #
    # If a `<script src>` survived past inline_linked, that's because
    # the file couldn't be resolved (missing / outside base_dir / etc.) —
    # report it as the specific R29-R32 failure cause, NOT as "7 chrome
    # needles missing" downstream noise.
    script_blocks = ' '.join(re.findall(r'<script[^>]*>(.+?)</script>', html, re.S))

    base_dir = html_path.parent
    js_link_failures: list[str] = []
    for src in re.findall(r'<script[^>]*\bsrc=["\']([^"\']+)["\']\s*[^>]*>\s*</script>', html):
        if src.startswith(('http:', 'https:', '//', 'data:')):
            continue
        js_path = (base_dir / src).resolve()
        if not js_path.is_file():
            js_link_failures.append(
                f'JS file not found: {src} (resolved to {js_path}). '
                'Did the deck folder move without `copy-assets.py`?')
        else:
            # File exists but inline_linked didn't substitute it — likely
            # permission error or the regex didn't match its `<script src>`
            # form (e.g. attributes in a non-standard order).
            js_link_failures.append(
                f'JS file present but not inlined: {src}. '
                'inline_linked in main() failed to replace this script tag; '
                'verify file permissions and the tag has no body content.')

    if js_link_failures:
        for msg in js_link_failures:
            iss.err('R29-32', msg
                + ' Subsequent R29-R32 needle errors are downstream of this.')
        # If linked JS is broken, skip needle checks — they'll all fail
        # with downstream noise that hides the real cause.
        return

    # All searchable text (HTML markup + inline JS + linked JS bodies — the
    # last is already in script_blocks because inline_linked rewrote
    # <script src> into inline <script> with the file's content).
    full_text = html + ' ' + script_blocks

    dom_needles = [
        ('deck-progress',     'top progress bar element / class',
         'feishu-deck.js builds this — make sure <script src="assets/feishu-deck.js"> is loading.'),
        ('deck-controls',     'bottom control pill element / class',
         'feishu-deck.js builds this — verify the JS is loading from a reachable path.'),
        ('class="ctl prev"',  'prev button',  'should appear in feishu-deck.js innerHTML.'),
        ('class="ctl next"',  'next button',  'should appear in feishu-deck.js innerHTML.'),
        ('class="ctl fs"',    'fullscreen button', 'should appear in feishu-deck.js innerHTML.'),
        ('--fs-grad-keyline', 'progress bar uses brand gradient',
         'this token must be defined in feishu-deck.css and used by .deck-progress.'),
        ('is-idle',           'auto-idle fade',
         'feishu-deck.js toggles this class after 2.5s of no input.'),
    ]
    js_needles = [
        ('requestFullscreen', 'fullscreen API call',
         'feishu-deck.js calls element.requestFullscreen() on the deck root.'),
        ('fullscreenchange',  'fullscreenchange listener',
         'feishu-deck.js listens to detect Esc-to-exit-fullscreen.'),
    ]
    for needle, desc, hint in dom_needles:
        if needle not in full_text:
            iss.err('R29-32', f'present-mode chrome missing: {desc} ({needle!r}). {hint}')
    for needle, desc, hint in js_needles:
        if needle not in script_blocks:
            iss.err('R29-32', f'present-mode chrome missing in JS: {desc} ({needle!r}). {hint}')


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


def audit_slide_keys(slides: list[str], iss: Issues):
    """R-KEY: every <div class="slide"> carries a unique semantic data-slide-key.

    Consumed by the companion `feishu-slide-library` skill — its locator
    (canonical_source.slide_key) points back to [data-slide-key="..."] in
    the deck source. Missing or duplicate keys → unindexable slides.

    Rules:
      • Every .slide MUST have data-slide-key set.
      • Slug must match ^[a-z0-9][a-z0-9-]*$ (kebab-case, starts with
        alphanumeric, no underscores or uppercase).
      • Slugs MUST be unique within the deck (no two slides share a key).
      • Positional slugs are allowed but flagged as warning — the rule
        wants semantic slugs that survive reorder (`slide-NN` /
        `page-N` / `section-N` are positional).
    """
    slug_re = re.compile(r'data-slide-key="([^"]*)"')
    valid_slug_re = re.compile(r'^[a-z0-9][a-z0-9-]*$')
    positional_re = re.compile(r'^(slide|page|section|frame)-?\d+$')

    seen: dict[str, int] = {}  # slug -> first slide index it appeared in
    missing: list[int] = []

    for i, fr in enumerate(slides, 1):
        m = slug_re.search(fr)
        if not m:
            missing.append(i)
            continue
        slug = m.group(1)

        if not slug:
            iss.err('R-KEY',
                f'slide {i}: data-slide-key is empty. '
                'Set a semantic kebab-case slug (e.g. "arr-history", "cover", '
                '"case-meiyijia"). Required by feishu-slide-library locator.')
            continue

        if not valid_slug_re.match(slug):
            iss.err('R-KEY',
                f'slide {i}: data-slide-key="{slug}" is not valid kebab-case. '
                'Use lowercase letters, digits, and `-` only; must start with '
                'an alphanumeric. Example: "arr-history" not "ARR_History".')
            continue

        if positional_re.match(slug):
            iss.warn('R-KEY',
                f'slide {i}: data-slide-key="{slug}" is positional — it '
                'breaks when slides reorder. Use a semantic slug naming '
                'what the slide is ABOUT (e.g. "arr-history" instead of '
                '"slide-06").')

        if slug in seen:
            iss.err('R-KEY',
                f'slide {i}: data-slide-key="{slug}" already used by '
                f'slide {seen[slug]}. Slugs must be deck-internal unique. '
                'Pick a different semantic slug or add a suffix '
                f'(e.g. "{slug}-v2").')
        else:
            seen[slug] = i

    if missing:
        iss.err('R-KEY',
            f'{len(missing)} slide(s) missing data-slide-key '
            f'(slide indices: {", ".join(map(str, missing[:5]))}'
            f'{", …" if len(missing) > 5 else ""}). '
            'Every .slide must carry a semantic kebab-case slug so the '
            'feishu-slide-library skill can index it. Add '
            '`data-slide-key="<slug>"` next to data-screen-label.')


def audit_language_policy(html: str, slides: list[str], iss: Issues, strict: bool):
    """R-LANG: enforce the SKILL's ZH-only-by-default language policy.

    The deck declares its language mode in <head>:
        <meta name="fs-language" content="zh-only">   ← default if absent
        <meta name="fs-language" content="zh-en">     ← bilingual opt-in

    In zh-only mode, EN-translation tracks under CN copy are forbidden:
      • `.title-en` / `.subtitle-en` / `.label-en` div siblings
      • paired CJK + Latin lines on agenda items, content-3up cards, mottos

    The most reliable static signal is the `.title-en` / `.subtitle-en` /
    `.label-en` class — these EXIST in feishu-deck.css specifically for
    bilingual mode. If a deck declares zh-only but renders these classes,
    it's drifting back to bilingual without saying so.

    A bilingual deck just sets the meta and the audit is a no-op.
    """
    meta_m = re.search(
        r'<meta[^>]*name="fs-language"[^>]*content="([^"]+)"', html)
    mode = (meta_m.group(1) if meta_m else 'zh-only').strip().lower()

    if mode == 'zh-en':
        return  # bilingual explicitly opted in

    if mode not in ('zh-only', 'zh-en'):
        iss.warn('R-LANG',
            f'<meta name="fs-language" content="{mode}"> — unknown value. '
            'Use "zh-only" (default, monolingual ZH) or "zh-en" (bilingual). '
            'Treating as zh-only.')

    en_class_re = re.compile(r'class="[^"]*\b(title|subtitle|label)-en\b')
    for i, fr in enumerate(slides, 1):
        for m in en_class_re.finditer(fr):
            cls = m.group(0).split('class="')[-1]
            msg = (f'slide {i}: bilingual class `{cls}…` rendered in '
                   'zh-only mode — drop the EN translation track, or '
                   'opt into bilingual via `<meta name="fs-language" '
                   'content="zh-en">` in <head>.')
            if strict: iss.err('R-LANG', msg)
            else:      iss.warn('R-LANG', msg)
            break  # one report per slide is enough


def audit_default_centering(html: str, iss: Issues):
    """R48: every fixed-shape container layout vertically centers by default."""
    for style_m in re.finditer(r'<style[^>]*>(.*?)</style>', html, re.S):
        css = re.sub(r'/\*.*?\*/', '', style_m.group(1), flags=re.S)
        css = _strip_nested_at_rules(css)
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

    # Variants are an author-CSS concern; framework declares its variants
    # under master-spec review and doesn't need this rule.
    for raw, _is_fw in _iter_style_blocks(html, include_framework=False):
        css = re.sub(r'/\*.*?\*/', '', raw, flags=re.S)
        css = _strip_nested_at_rules(css)
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


def audit_dom_integrity(html: str, iss: Issues):
    """R-DOM: structural invariants on the .deck DOM tree.

    Catches the "regex insertion ate a closing div" failure mode that
    nested 7 slide-frames inside another slide-frame in the 2026-05-14
    CTG run — present-mode then hid all 7 because they weren't the
    current slide. 30+ minute debug, no clear symptom.

    Invariants enforced (using stdlib html.parser, no external deps):
      1. Every <div class="slide-frame"> must be a direct child of
         <div class="deck"> (not nested inside another slide-frame).
      2. Every <div class="slide-frame"> must contain exactly one
         <div class="slide"> direct child.
      3. Inside <body>, the <div> open/close tag count must balance
         after stripping comments, scripts, and styles.

    Self-closing tags (img / br / hr / input / link / meta) and the
    void-tag set are NOT counted. Templates that legitimately use HTML
    fragments with unbalanced divs (rare) can suppress this audit by
    embedding `<!-- allow:dom-integrity -->` in the body.
    """
    from html.parser import HTMLParser

    body_m = re.search(r'<body[^>]*>(.*)</body>', html, re.S)
    if not body_m:
        return
    body = body_m.group(1)

    # Author-opt-out (very rarely needed)
    if 'allow:dom-integrity' in body:
        return

    # Strip comments, script, style — these can contain pseudo-tags that
    # confuse the parser without affecting real DOM structure.
    body = re.sub(r'<!--.*?-->',           '', body, flags=re.S)
    body = re.sub(r'<script[^>]*>.*?</script>', '', body, flags=re.S)
    body = re.sub(r'<style[^>]*>.*?</style>',   '', body, flags=re.S)

    class DomChecker(HTMLParser):
        """Track ONLY <div> stack — that's all the invariants need.

        Avoids the void-tag noise: <br> / <img> / <hr> fire handle_starttag
        but never handle_endtag, which would corrupt a generic tag stack.
        Self-closing XHTML (<path d="..."/>) fires handle_startendtag, which
        we also don't care about. Restricting to divs gives a clean signal.
        """
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.div_stack: list[str] = []   # class_str of each open div
            self.frames_seen = 0
            self.frames_under_deck = 0
            self.frames_nested_in_frame: list[int] = []
            self.frame_inner_slide_count: list[int] = []
            self.div_opens = 0
            self.div_closes = 0

        @staticmethod
        def _has_class(class_str: str, name: str) -> bool:
            return bool(class_str) and name in class_str.split()

        def handle_starttag(self, tag, attrs):
            if tag != 'div':
                return
            class_str = next((v or '' for k, v in attrs if k == 'class'), '')
            self.div_opens += 1
            if self._has_class(class_str, 'slide-frame'):
                self.frames_seen += 1
                # parent must be <div class="deck"> (the top of the div stack)
                if self.div_stack and self._has_class(self.div_stack[-1], 'deck'):
                    self.frames_under_deck += 1
                # is any enclosing div also a slide-frame?
                for parent_cls in self.div_stack:
                    if self._has_class(parent_cls, 'slide-frame'):
                        self.frames_nested_in_frame.append(self.frames_seen)
                        break
                self.frame_inner_slide_count.append(0)
            elif self._has_class(class_str, 'slide'):
                # direct child of a frame? top of stack should be slide-frame
                if self.div_stack and self._has_class(self.div_stack[-1], 'slide-frame'):
                    if self.frame_inner_slide_count:
                        self.frame_inner_slide_count[-1] += 1
            self.div_stack.append(class_str)

        def handle_endtag(self, tag):
            if tag != 'div':
                return
            self.div_closes += 1
            if self.div_stack:
                self.div_stack.pop()

    checker = DomChecker()
    try:
        checker.feed(body)
        checker.close()
    except Exception as e:
        iss.warn('R-DOM',
            f'DOM parser failed to scan body ({e}). Structural invariants '
            'could not be checked. Open in a browser to verify rendering.')
        return

    # Invariant 1: every slide-frame is a direct child of .deck
    orphan_frames = checker.frames_seen - checker.frames_under_deck
    if orphan_frames:
        iss.err('R-DOM',
            f'{orphan_frames} of {checker.frames_seen} <div class="slide-frame"> '
            'are NOT a direct child of <div class="deck">. The most likely '
            'cause is a missing </div> earlier in the document (regex-based '
            'insertion / deletion ate a closing tag), nesting later frames '
            'inside an unclosed frame. Present mode will hide every nested '
            'frame because it never becomes the current slide. '
            'Re-inspect recent edits; do not use regex to splice slide-frames.')
    if checker.frames_nested_in_frame:
        # specific frames flagged — list first few for debugging
        idxs = ', '.join(str(n) for n in checker.frames_nested_in_frame[:5])
        more = '' if len(checker.frames_nested_in_frame) <= 5 \
                  else f' (+{len(checker.frames_nested_in_frame)-5} more)'
        iss.err('R-DOM',
            f'slide-frame nesting: frames at positions {idxs}{more} '
            'are inside ANOTHER slide-frame. This breaks present mode — '
            'only the outer frame becomes the current slide; the inner '
            'frames are perma-hidden. Fix the unclosed div above.')

    # Invariant 2: every frame holds exactly one .slide direct child
    for i, n in enumerate(checker.frame_inner_slide_count, 1):
        if n != 1:
            iss.err('R-DOM',
                f'slide-frame #{i} contains {n} direct .slide children '
                '(expected exactly 1). Either the markup template is broken '
                'or two slides got concatenated into one frame.')

    # Invariant 3: div open/close balance
    if checker.div_opens != checker.div_closes:
        delta = checker.div_opens - checker.div_closes
        sign = '+' if delta > 0 else '−'
        iss.err('R-DOM',
            f'div balance in <body>: {checker.div_opens} opens vs '
            f'{checker.div_closes} closes ({sign}{abs(delta)}). The DOM '
            'tree will close prematurely or leak across boundaries. '
            'Locate the missing tag — every regex/sed insertion is a '
            'prime suspect.')


def audit_white_text(html: str, iss: Issues, strict: bool):
    """R-WHITE-TEXT: content text must be pure white on dark slides.

    Why: this skill targets 1920×1080 projector-room presentations. Any
    `color: rgba(255,255,255,X)` with X < 1 reads as gray when projected
    5+ meters away — author-direct readability is OK, audience-side
    readability is not. The brand background ~#080C18 has zero contrast
    with low-opacity whites.

    Scope:
      • CSS rules whose selector targets slide content (.slide and its
        descendants, NOT .deck-ui / .deck-progress / .deck-controls).
      • Inline style="" on slide markup.

    Exemptions (treated as legitimate "soft" usage):
      • Rules that explicitly bind to chrome classes (.eyebrow as a Latin
        caps tracker, .footnote, .pageno, .source / .source-footer that's
        already retired, .caption, .deck-pageno, .nav-hint, .mode-toggle).
      • Rules whose own `font-size` is ≤ 14 px (chrome floor — they're
        meta-text by definition).
      • Rules carrying `/* allow:white-opacity */` in the same block.

    Soft = warning by default, error in --strict.
    """
    chrome_class_re = re.compile(
        r'\.(?:eyebrow|footnote|pageno|caption|source|source-footer|'
        r'deck-pageno|nav-hint|mode-toggle|deck-ui|deck-controls|'
        r'deck-progress|attrib|sc-cap|axis-cap)\b')
    # Match only the `color:` property — NOT border-color / outline-color /
    # text-decoration-color / column-rule-color etc. Negative lookbehind
    # ensures `color` isn't preceded by `-` or a word character.
    soft_white_re = re.compile(
        r'(?<![-\w])color:\s*rgba\(\s*255\s*,\s*255\s*,\s*255\s*,\s*0?\.\d+\s*\)')
    fs_re = re.compile(r'font-size:\s*(\d+)px')
    comment_re = re.compile(r'/\*.*?\*/', re.S)

    flagged: list[tuple[str, str]] = []
    # Skip framework CSS — its master-spec rules carry their own
    # allow:white-opacity tags where appropriate. R-WHITE-TEXT polices
    # author CSS, where the gray-text-on-projector trap actually hurts.
    #
    # Single-pass parse (perf fix 2026-05-16): we used to iterate the
    # comment-stripped CSS, then for EACH .slide rule re-search the raw
    # CSS again via re.escape(selector) to find the /* allow:white-opacity */
    # marker. That was O(rules × raw_size) — 457 ms on the 53-slide CTG
    # deck. Now we iterate raw directly with a comment-tolerant rule
    # regex; each rule's body carries its OWN comments inline so we can
    # check the marker without a second pass.
    for raw, _is_fw in _iter_style_blocks(html, include_framework=False):
        # Strip nested @-rules first (@media / @keyframes / @supports) so
        # the top-level rule regex doesn't trip on nested braces. CSS
        # inside @media is intentionally not audited (responsive variants).
        css = _strip_nested_at_rules(raw)
        # Rule body can contain /* ... */ comments. Allow them in the body
        # via the alternation: `comment | non-brace char`. This preserves
        # the comment text (including the allow:white-opacity marker) in
        # group(2) so a single substring check decides exemption.
        for rule_m in _RULE_WITH_COMMENTS_RE.finditer(css):
            selector = rule_m.group(1).strip()
            body_with_comments = rule_m.group(2)
            if '.slide' not in selector and '.card' not in selector \
               and '.col' not in selector:
                continue
            if chrome_class_re.search(selector):
                continue
            if 'allow:white-opacity' in body_with_comments:
                continue
            # Strip comments from THIS rule's body before checking for the
            # rgba declaration — a comment like `/* hint: rgba(255,...) */`
            # shouldn't trigger. Per-rule strip is O(body_size); since
            # bodies are typically <1 KB and we visit each char once total,
            # the audit is O(css_size), no longer quadratic.
            body = comment_re.sub('', body_with_comments)
            fs_m = fs_re.search(body)
            if fs_m and int(fs_m.group(1)) <= 14:
                continue
            if soft_white_re.search(body):
                flagged.append((selector, body.strip()[:80]))

    # Inline style="" on slide markup
    body_m = re.search(r'<body[^>]*>(.*)</body>', html, re.S)
    if body_m:
        body = re.sub(r'<script.*?</script>', '', body_m.group(1), flags=re.S)
        body = re.sub(r'<style.*?</style>',   '', body, flags=re.S)
        for m in re.finditer(r'style="([^"]*)"', body):
            decl = m.group(1)
            if soft_white_re.search(decl):
                fs_m = fs_re.search(decl)
                if fs_m and int(fs_m.group(1)) <= 14:
                    continue
                flagged.append(('<inline>', decl[:80]))

    for selector, block in flagged[:12]:
        msg = (f'soft-white text on `{selector}` — `{block}…`. '
               'Content text on dark slides must be `#fff` or `rgba(255,255,255,1)`. '
               'Low-opacity white reads as gray when projected. Use other '
               'levers for hierarchy (font-weight, font-size, background '
               'tone, border dim). Add `/* allow:white-opacity */` in the '
               'rule if this is a deliberate chrome exception.')
        if strict: iss.err('R-WHITE-TEXT', msg)
        else:      iss.warn('R-WHITE-TEXT', msg)


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

def audit_feedback_md(html_path: Path, iss: Issues):
    """R-FEEDBACK: every run output should ship a FEEDBACK.md sidecar.

    Path A (render.py) emits FEEDBACK.md inline with each deck. Path B
    (freehand LLM authoring) has no automation and the agent forgets
    more often than not — 8 of 17 runs through 2026-05-15 shipped
    without one. SKILL.md "RUN-FEEDBACK CAPTURE" makes it mandatory;
    this is the soft enforcement that catches the omission.

    Scope: only flags HTML living under a `runs/<ts>/output/` directory
    (the per-run output convention from new-run.sh). Files in
    `examples/`, `templates/`, or arbitrary one-off locations skip
    this audit — they're not per-run outputs.

    Warning, not error: the deck still works without FEEDBACK.md.
    `finalize.sh` auto-stubs the file these days, so this rule is
    mostly a safety net for legacy / one-off runs that bypass finalize.
    """
    # Only enforce inside the runs/<ts>/output/ convention
    parent = html_path.parent
    grandparent = parent.parent
    in_run_output = (parent.name == 'output' and
                     re.match(r'^\d{8}-\d{6}', grandparent.name))
    if not in_run_output:
        return

    feedback = parent / 'FEEDBACK.md'
    if not feedback.is_file():
        iss.warn('R-FEEDBACK',
            f'no FEEDBACK.md in {parent}. Every run should '
            'capture the agent\'s judgment calls + visual workarounds + '
            'validator escapes for the maintainer to fold into the next '
            'skill version. Run `bash assets/finalize.sh <output-dir>` '
            'to auto-stub the file, then fill in agent decisions before '
            'hand-off. (Path A render.py emits this automatically; '
            'freehand decks need it written by hand.)')
        return

    # Detect the finalize.sh auto-stub. If found, the file exists but is
    # empty of agent-authored content — finalize.sh just created a
    # placeholder. Keep warning until the agent fills it in.
    try:
        content = feedback.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return
    if 'FEEDBACK.md.auto-stub' in content:
        iss.warn('R-FEEDBACK',
            f'{feedback.name} exists but is an unfilled auto-stub from '
            '`finalize.sh`. The agent must replace the placeholder '
            'sections with real decisions from this run BEFORE hand-off. '
            'Look for `## 关键决策(本 run 实际发生的判断)` — every entry '
            'should describe one concrete choice the agent made (layout '
            'pick, sizing tweak, validator workaround, copy shortening) '
            'with `**为什么**:` + checkbox. Drop the auto-stub HTML '
            'comment once you\'ve filled it in to silence this warning.')


def audit_visual_overflow(html_path: Path, iss: Issues):
    """R-OVERFLOW: open the deck in a headless browser at 1920×1080 and
    report any .slide whose content extends past the canvas.

    Static validators (R02 / R06 / R20 / R-DOM …) can't see pixel overflow.
    A slide with a 2 200-px-tall stack of cards passes every static rule
    but bleeds past the bottom of the canvas in present mode. The CTG run
    flagged this manually multiple times.

    This audit runs Playwright in headless mode. It is OPT-IN via
    `--visual` because Playwright + Chromium are a ~150 MB install most
    users don't have; we don't want to make the default validator depend
    on them.

    Setup (one-time, on the developer's machine):

        pip install playwright
        python -m playwright install chromium

    Behaviour without Playwright: prints an install hint and returns
    cleanly (no failure). With Playwright: renders the deck file://-URL,
    iterates every `.slide`, captures `scrollHeight` and `scrollWidth`,
    and flags any slide whose content extends past 1080 px tall or
    1920 px wide.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        iss.warn('R-OVERFLOW',
            '--visual requested but `playwright` is not installed. '
            'Install with: `pip install playwright && '
            'python -m playwright install chromium` (~150 MB). '
            'Visual overflow check skipped — static rules still ran.')
        return

    url = html_path.resolve().as_uri()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = context.new_page()
            page.goto(url, wait_until='networkidle', timeout=10_000)
            # Switch the deck into present mode so each .slide gets the
            # 1920×1080 canvas it's designed for (scroll mode uses smaller
            # viewports and would false-positive everywhere).
            page.evaluate("""
                () => {
                    const deck = document.querySelector('.deck');
                    if (deck) deck.setAttribute('data-mode', 'present');
                }
            """)
            page.wait_for_timeout(200)  # allow style recalc
            overflows = page.evaluate("""
                () => {
                    const slides = document.querySelectorAll('.slide');
                    const out = [];
                    slides.forEach((s, i) => {
                        const label = s.getAttribute('data-screen-label') || `slide-${i+1}`;
                        // Use scrollHeight/scrollWidth on the slide element itself
                        const h = s.scrollHeight;
                        const w = s.scrollWidth;
                        if (h > 1080 || w > 1920) {
                            out.push({ idx: i+1, label, h, w });
                        }
                    });
                    return out;
                }
            """)
            browser.close()
    except Exception as e:
        iss.warn('R-OVERFLOW',
            f'visual overflow check could not run ({type(e).__name__}: {e}). '
            'Try `python -m playwright install chromium` if you have not yet, '
            'or open the deck in a browser manually to verify.')
        return

    for entry in overflows[:20]:
        delta_h = entry['h'] - 1080
        delta_w = entry['w'] - 1920
        bits = []
        if delta_h > 0: bits.append(f'height +{delta_h} px')
        if delta_w > 0: bits.append(f'width +{delta_w} px')
        iss.err('R-OVERFLOW',
            f'slide {entry["idx"]} ({entry["label"]}): content overflows '
            f'canvas — {", ".join(bits)}. Reduce content density, drop '
            'cards / rows, increase column count, or shorten body copy. '
            'Body floor R06 is 22 px and is not negotiable; if content '
            'genuinely needs more vertical room, split across two slides.')


def main():
    p = argparse.ArgumentParser(description='feishu-deck-h5 self-check')
    p.add_argument('html', help='Path to the assembled deck HTML file')
    p.add_argument('--strict', action='store_true',
                   help='Promote warnings to errors')
    p.add_argument('--visual', action='store_true',
                   help='Also run the optional Playwright-based overflow '
                        'check (renders each slide at 1920×1080 and flags '
                        'content past canvas). Requires `pip install '
                        'playwright && python -m playwright install chromium`.')
    args = p.parse_args()

    path = Path(args.html)
    if not path.is_file():
        print(f'ERROR: file not found: {path}', file=sys.stderr)
        return 2

    html = path.read_text(encoding='utf-8')

    # Resolve linked stylesheets and scripts so audits can see their content
    # (the linked-mode deck doesn't inline CSS/JS — without this, runtime-chrome
    # and centering-pattern audits would false-fail).
    #
    # Inlined `<style>` and `<script>` blocks carry `data-source="framework"`
    # so author-CSS audits (R-WHITE-TEXT, R47, future rules) can scope
    # themselves to author markup and skip framework rules they shouldn't
    # police. Audits that DO want to see framework (R29-R32 runtime chrome,
    # R36 centering pattern, R10 hex palette) can ignore the attribute.
    def inline_linked(html_text, base_dir):
        # <link rel="stylesheet" href="...css">
        def repl_link(m):
            href = m.group(1)
            if href.startswith(('http:', 'https:', 'data:')): return m.group(0)
            target = (base_dir / href).resolve()
            if not target.is_file(): return m.group(0)
            return ('<style data-source="framework">'
                    + target.read_text(encoding='utf-8')
                    + '</style>')
        html_text = re.sub(
            r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>',
            repl_link, html_text)
        # <script src="...js"></script>
        def repl_script(m):
            src = m.group(1)
            if src.startswith(('http:', 'https:', 'data:')): return m.group(0)
            target = (base_dir / src).resolve()
            if not target.is_file(): return m.group(0)
            return ('<script data-source="framework">'
                    + target.read_text(encoding='utf-8')
                    + '</script>')
        html_text = re.sub(
            r'<script[^>]*src="([^"]+)"[^>]*>\s*</script>',
            repl_script, html_text)
        return html_text
    html = inline_linked(html, path.parent)

    slides = extract_slides(html)

    iss = Issues()
    audit_dom_integrity(html, iss)
    audit_structure(slides, iss)
    audit_titles_one_line(slides, iss)
    audit_brand_chrome(slides, iss, args.strict)
    audit_copy_rules(html, iss)
    audit_font_sizes(html, iss)
    audit_type_ladder(html, iss)
    audit_white_text(html, iss, args.strict)
    audit_no_drop_shadows(html, iss)
    audit_data_decor(slides, iss)
    audit_hex_palette(html, iss, args.strict)
    audit_runtime_chrome(html, iss, path)
    audit_centering_pattern(html, iss)
    audit_layout_integrity(html, iss)
    audit_default_centering(html, iss)
    audit_variant_discipline(html, iss)
    audit_ui_mocks_are_html(slides, iss)
    audit_no_cyan_accent(slides, iss)
    audit_header_minimal(slides, iss)
    audit_slide_keys(slides, iss)
    audit_language_policy(html, slides, iss, args.strict)
    audit_perf(html, iss, args.strict)
    audit_text_ids(html, path, iss)
    audit_feedback_md(path, iss)

    if args.visual:
        audit_visual_overflow(path, iss)

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
