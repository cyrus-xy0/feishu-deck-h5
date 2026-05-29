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

FLOOR_BODY_PX        = 24   # body text on content pages (was 22 pre-2026-05-16 · 4-tier spec rung 3)
FLOOR_CHROME_PX      = 16   # corner metadata / footnote / pill / tag (was 14 pre-2026-05-16 · 4-tier rung 4)
# FLOOR_HEADER_PX / FLOOR_TABLE_TH_PX / FLOOR_STATS_TREND_PX were defined but
# never read (R20 enforces the 4-tier ladder directly). Removed 2026-05-18.

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
HERO_TITLE_LAYOUTS = {'cover', 'image-text', 'end', 'section', 'quote'}
# `section` ships hero `.chapter-num` (160) + `<h2 class="title">` (88) where
# 2-line chapter titles are common ("绿氢革命<br>2026"). `quote` ships
# `<blockquote>` at 88px where rhetorical line-breaks read better. Both were
# missing pre-2026-05-18; R13 false-positive on multi-line section/quote
# titles. `audit_header_minimal` already lists the same 5-layout set
# verbatim, so this fix lets us drop the duplicate enumeration there.

# TITLE_ONLY_LAYOUTS was defined here but never read. Eyebrow suppression
# happens via the framework CSS rule `.slide .header .eyebrow { display:none }`
# (feishu-deck.css) + R56 in `audit_header_minimal`. Removed 2026-05-18.


# ---------------------------------------------------------------------------
#  Issue collection
# ---------------------------------------------------------------------------

class Issues:
    """Aggregates findings during validation.

    Three severity buckets:
      - errors:   hard-fail (return code 1)
      - warnings: soft (return code 0 unless --strict promotes them)
      - soft_warnings: editorial advisories that NEVER promote to errors
                       under --strict (e.g. R-FEEDBACK "consider adding a
                       sidecar", R-VIS-ALIGN "4 px tolerance is fuzzy").
                       Rendered indistinguishably from warnings, but
                       protected from --strict promotion.
    """
    def __init__(self):
        self.errors: list[tuple[str, str]] = []
        self.warnings: list[tuple[str, str]] = []
        self.soft_warnings: list[tuple[str, str]] = []

    def err(self, code, msg):       self.errors.append((code, msg))
    def warn(self, code, msg):      self.warnings.append((code, msg))
    def warn_soft(self, code, msg): self.soft_warnings.append((code, msg))


# ---------------------------------------------------------------------------
#  Slide extraction
# ---------------------------------------------------------------------------

_SLIDE_FRAME_OPEN_RE = re.compile(
    r'<div\s+(?=[^>]*\bclass="(?:[^"]*\s)?slide-frame(?:\s[^"]*)?")[^>]*>',
    re.S,
)


def extract_slides(html: str) -> list[str]:
    """Return list of per-slide HTML strings (one per `<div class="slide-frame">`).

    Splits on the slide-frame opening tag via regex (NOT literal string) so
    that frames with attributes — `data-page="NN"`, additional classes, etc.
    — are still recognized. Previously this used
    `body.split('<div class="slide-frame">')` which only matched the bare
    no-attribute form; any deck that put `data-page` on the frame returned
    zero slides.
    """
    body_m = re.search(r'<body[^>]*>(.*)</body>', html, re.S)
    if not body_m:
        return []
    body = body_m.group(1)
    # Strip HTML comments FIRST so any literal '<script>' inside comments
    # doesn't confuse the script-tag stripper below.
    body = re.sub(r'<!--.*?-->', '', body, flags=re.S)
    body = re.sub(r'<script[^>]*>.*?</script>', '', body, flags=re.S)
    parts = _SLIDE_FRAME_OPEN_RE.split(body)
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


def audit_brand_chrome(slides: list[str], iss: Issues):
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


# Body content classes — selectors matching these get the 22 px BODY floor.
# Names taken from SKILL.md "Typography floor" table + framework + observed
# author conventions. These are class names that semantically carry SLIDE
# COPY (paragraphs, descriptions, list items, table cells, captions).
# R12: box-shadow that starts with "0 0 0 …" is a glow-ring (NOT a drop
# shadow with offset). Hoisted to module scope so re.compile happens once
# per process, not once per CSS rule scanned (2026-05-18 cleanup).
_BOX_SHADOW_GLOW_RING_RE = re.compile(r'^\s*0\s+0\s+0(?:\s+\d+\w+)?\s')
_BOX_SHADOW_INSET_RE = re.compile(r'\binset\b')

_BODY_CLASS_RE = re.compile(
    r'\.(?:'
    r'cbody|body|desc|sub|lede|paragraph|para|caption|cap|note|'
    r'feat-body|brand-desc|dir-desc|dir-sub|sc-obj|sc-lever|'
    r'arch-item|arch-base|arch-hand-title|story-hook|story-arc|'
    r'principle|voice-card|voice-q|cta-box|the-who|content-body|'
    r'who|name|preview-text|hook|takeaway|callout-body|'
    r'sec ?ul|sec ?ol|item-body|row-body|cell-body|col-body|col-text|'
    r'page-sub|subtitle(?!-en)|lead|timeline-desc'
    r')\b'
    r'|\b(?:ts-tasks|ts-time)\b'
)

# Chrome / decorative classes — selectors matching these get only the
# 14 px chrome floor (keep current R06 behaviour). These are small-by-design:
# pills, tags, footnotes, page numbers, eyebrows, source citations, mockup-
# internal text.
_CHROME_CLASS_RE = re.compile(
    r'\.(?:'
    r'eyebrow|footnote|pageno|deck-pageno|attrib|source(?:-footer)?|'
    r'pill|chip|tag(?:-chip)?|badge|label-small|chrome|kicker|overline|'
    r'meta|trend|axis(?:-cap)?|hint|tip|legend|nav-hint|mode-toggle|'
    r'phase-pill|status|status-dot|fmt|fix|disclaim|fineprint|'
    r'sc-cap|cfoot|stnum|chapter-num|stat-unit|kpi-unit|unit|'
    r'iframe-hint|count|'
    # `.n` is the canonical numeric-badge class throughout the skill
    # (`.arch-item .n`, `.toc .item .n`, `.scene-card .n`, etc.) — small
    # circular glyph showing "1" / "2" / "3", not body text. Chrome.
    r'n'
    r')\b|'
    # all .ui-* mock primitives (window/list/cell/btn/etc.) are mockup-
    # internal per SKILL.md rung 8 — exempt from body floor by class.
    r'\.ui-[a-z][\w-]*'
)


def _lifted_slide_keys(html: str) -> set:
    """Slide-keys of slides carrying data-lifted (Native slide lift). Their
    CONTENT-STYLE violations (R06 / R-WHITE-TEXT) get downgraded err→warn —
    the slide is verbatim from another deck, so the human CHOOSES whether to
    bump fonts; it's surfaced, not blocking. Geometry/overflow stays error."""
    keys = set()
    for m in re.finditer(r'<div class="slide"[^>]*>', html):
        tag = m.group(0)
        if 'data-lifted' in tag:
            km = re.search(r'data-slide-key="([^"]+)"', tag)
            if km:
                keys.add(km.group(1))
    return keys


def audit_font_sizes(html: str, iss: Issues):
    """R06: font-size minimums on slide content.

    Two floors apply, distinguished by selector class semantics:

    1. **Chrome floor (14 px)** — applies to chrome / mockup classes
       (eyebrow, footnote, pageno, pill, tag, .ui-* mockup primitives,
       etc.). Sizes < 14 are errors; 14 px is the absolute minimum.

    2. **Body floor (22 px)** — applies to selectors that look like body
       content (cbody, desc, lede, caption, list items, cell content,
       arch-*, principle, voice-card, cta-box, etc.). Sizes < 22 are
       errors. This is the floor that prevents the "字还是小 on
       projector" complaint — 18-20 px reads as fine print at 5+ m.

    3. **Ambiguous classes** (selectors matching neither pattern, e.g.
       a custom `.foo`) get the chrome floor by default. Authors should
       either use a body-class name for body content (will then be
       caught) or add `/* allow:body-floor */` to opt out (rare).

    Both floors honor `/* allow:typescale */` (rung-8 mockup-internal
    10-13 px) and the new `/* allow:body-floor */` for genuine
    exceptions where a body-class selector legitimately uses < 22 px.
    """
    body_violations: list[tuple[int, str]] = []
    chrome_violations: list[tuple[int, str]] = []

    for raw, _is_fw in _iter_style_blocks(html):
        css = _strip_nested_at_rules(raw)
        for rule_m in re.finditer(r'([^{}]+)\{([^}]+)\}', css):
            selector = rule_m.group(1).strip()
            block    = rule_m.group(2)
            # Skip auxiliary deck chrome (overlay outside slide canvas)
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
            # Per-rule opt-outs (preserve marker check on raw block before
            # comments are stripped — but our `block` is the post-strip body,
            # so the markers must live in the raw CSS comment that survived
            # _strip_nested_at_rules. Simpler: check the raw style-block CSS
            # for proximity to this selector via substring on the body itself.)
            if 'allow:typescale' in block:
                continue   # rung-8 mockup-internal, fully exempt
            allow_body_floor = 'allow:body-floor' in block

            # Determine which floor applies. CHROME wins over BODY when both
            # match (e.g. `.cta-box .source` is a chrome citation inside a
            # body container — the leaf class wins).
            is_chrome  = bool(_CHROME_CLASS_RE.search(selector))
            is_body    = bool(_BODY_CLASS_RE.search(selector)) and not is_chrome

            sizes = []
            for m in re.finditer(r'font-size:\s*(\d+)px', block):
                sizes.append(int(m.group(1)))
            for m in re.finditer(r'\bfont:\s*[^;{}]*?(\d+)px', block):
                sizes.append(int(m.group(1)))

            for size in sizes:
                if is_body and not allow_body_floor:
                    if size < FLOOR_BODY_PX:
                        body_violations.append((size, selector))
                elif size < FLOOR_CHROME_PX:
                    chrome_violations.append((size, selector))

    lifted_keys = _lifted_slide_keys(html)
    def _lev(sel):
        """Pick severity for an R06 violation: lifted-slide selectors warn
        (human chooses to bump), everything else errors. Returns (fn, note)."""
        if any(f'data-slide-key="{k}"' in sel for k in lifted_keys):
            return iss.warn, (' — LIFTED slide (verbatim from another deck); '
                'downgraded to WARNING, you choose whether to bump the font')
        return iss.err, ''

    for size, sel in chrome_violations[:10]:
        lev, note = _lev(sel)
        lev('R06',
            f'font-size {size}px on `{sel.strip()}` below '
            f'{FLOOR_CHROME_PX}px chrome floor{note}')

    for size, sel in body_violations[:10]:
        lev, note = _lev(sel)
        lev('R06',
            f'font-size {size}px on `{sel.strip()}` below '
            f'{FLOOR_BODY_PX}px BODY floor — selector looks like body content '
            '(card body / description / caption / list / cell / arch-* / etc.) '
            'and projector readability requires ≥ 22 px. Bump to 22, OR if '
            'this is genuinely chrome, rename to a chrome class '
            '(.eyebrow / .footnote / .source / .pill / .tag / etc.), OR '
            f'add /* allow:body-floor */ in the rule for a documented exception.{note}')

    # Inline styles on slide markup — apply chrome floor only (body classes
    # rarely show up as inline `style=""`; we don't try to parse the element's
    # class attribute here).
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
    # 4-tier strict (2026-05-16) — CONTENT pages use ONLY these four:
    16,                    # Foot — footnote, eyebrow, pill, tag, attrib, source
    24,                    # Body — paragraphs, list items, table cells, captions
    28,                    # Sub  — subtitle, column-title, lede (optional tier)
    48,                    # Title — Action Title on content pages
    # Mockup-internal text (Lark Doc / dashboard simulations) opts out via
    # /* allow:typescale */ — no longer in the default ladder.
    # Hero exceptions (cover 100, section 88/160, big-stat 132+, quote 88+)
    # also live OUTSIDE this ladder. They must be tagged with
    # /* allow:typescale */ when they appear in per-page <style> blocks.
    # Framework CSS itself is exempt from R20 (R20 only audits per-page
    # rules scoped to [data-page=...]).
}


def audit_type_ladder(html: str, iss: Issues):
    """R20: every per-page font-size MUST be on the 4-tier type-scale.

    Scope: only rules whose selector contains `[data-page="NN"]`. The global
    framework stylesheet (feishu-deck.css) is the authoritative master spec
    for cover / section / big-stat / end / quote hero values and is exempt
    from R20 by design — R20 targets the per-page `<style>` blocks where
    agents improvise content-page typography.

    Allowed sizes (2026-05-16, 4-tier strict per the canonical PPT→Web
    1pt≈2px mapping; see SKILL.md "Typography floor"):
        16  Foot   — footnote / eyebrow / pill / tag / attrib / source
        24  Body   — paragraphs, list items, table cells, captions
        28  Sub    — subtitle / column-title / lede (optional tier)
        48  Title  — Action Title on content pages

    Hero exceptions (only for cover/section/big-stat/end/quote content
    that genuinely needs a hero-scale value — 88, 100, 132, 160 etc.)
    opt out by adding `/* allow:typescale */` in the rule block. Same
    opt-out applies to mockup-internal text (10-13 px Lark Doc / dashboard
    simulations inside .ui-window).
    """
    seen = set()
    comment_re = re.compile(r'/\*.*?\*/', re.S)
    for style_m in re.finditer(r'<style[^>]*>(.*?)</style>', html, re.S):
        # Single-pass scan: walk raw CSS with comment-tolerant rule regex
        # so the `/* allow:typescale */` marker is visible in the body.
        # Previously we stripped comments BEFORE scanning, which dropped
        # the marker and forced every hero exception to look off-ladder.
        css = _strip_nested_at_rules(style_m.group(1))
        for rule_m in _RULE_WITH_COMMENTS_RE.finditer(css):
            selector = rule_m.group(1).strip()
            body_with_comments = rule_m.group(2)
            # Only audit per-page rules (where agents author improvised CSS)
            if '[data-page=' not in selector:
                continue
            if '@' in selector:
                continue
            if 'allow:typescale' in body_with_comments:
                continue
            # Strip comments for the size scan so a commented-out font-size
            # doesn't trip the audit.
            block = comment_re.sub('', body_with_comments)
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
                    f'font-size {size}px on `{selector[:80]}` is off-tier; '
                    f'nearest tier = {nearest}px '
                    f'(allowed: 16 Foot / 24 Body / 28 Sub / 48 Title — '
                    f'4-tier strict per the canonical PPT→Web mapping). '
                    f'Add /* allow:typescale */ in the rule to override '
                    f'(only for hero exceptions: cover 100, section 88/160, '
                    f'big-stat 132+, quote 88+, or mockup-internal 10-13).')


def audit_undefined_css_vars(html: str, iss: Issues):
    """R-CSSVAR: detect `var(--undefined-name)` references.

    When a CSS `var(--name)` references an undefined custom property AND
    has no fallback, the browser silently fails the surrounding declaration.
    The most damaging instance is `font:` shorthand — if any token in the
    shorthand is invalid (including unresolvable `var()`), the WHOLE
    shorthand is dropped and font-size falls back to the browser default
    of 16px. Authors then size a hero numeral at 88px and see it render
    at 16px, with no diagnostic anywhere.

    Real failure caught 2026-05-18 in Tongrentang P03: author wrote
        font: 700 88px/0.9 var(--fs-font-en);
    where the canonical name is `--fs-font-latin`. The `--fs-font-en` var
    didn't exist, the shorthand silently failed, font-size dropped to
    16px. Same typo was repeated 6 times across the deck, all silently
    rendering at 16px regardless of declared size.

    Both definitions and references come from the combined HTML+inlined-CSS
    sources (main()'s inline_linked has already pulled the framework CSS
    into a `<style data-source="framework">` block). Variables with an
    explicit fallback `var(--x, fallback)` are exempt — fallback IS the
    safety net.
    """
    # Collect every CSS source (author + inlined framework). R-CSSVAR
    # needs to know about ALL `--name:` definitions, including those in
    # feishu-deck.css, before flagging any `var()` reference as undefined.
    combined = '\n'.join(body for body, _is_fw in _iter_style_blocks(html))
    if not combined:
        return

    # Strip CSS comments to avoid matching commented-out var() / --name:
    combined_clean = re.sub(r'/\*.*?\*/', '', combined, flags=re.S)

    # Definitions: `--name: ...;` (or `--name: ...` at rule end without `;`).
    defined = set(re.findall(r'--([a-zA-Z][\w-]*)\s*:', combined_clean))

    # References. The fallback group greedily captures everything up to the
    # matching close paren; balanced inner parens are handled by allowing
    # nested `\([^()]*\)` once (sufficient for our usage, no triple-nested).
    ref_re = re.compile(
        r'var\(\s*--([a-zA-Z][\w-]*)\s*'
        r'(?:,((?:[^()]|\([^()]*\))*))?\)')
    undefined = {}
    for m in ref_re.finditer(combined_clean):
        name = m.group(1)
        fallback = (m.group(2) or '').strip()
        if name in defined:
            continue
        if fallback:
            continue  # browser uses the fallback
        undefined[name] = undefined.get(name, 0) + 1

    if not undefined:
        return

    # Try to suggest a corrected name from defined set (case-insensitive
    # match first, then loose prefix match).
    def _suggest(name: str) -> str:
        lo = name.lower()
        for d in defined:
            if d.lower() == lo:
                return f' Did you mean `--{d}`?'
        # cheap edit-distance: same prefix length ≥ 4, length diff ≤ 5
        for d in defined:
            common = 0
            for a, b in zip(name, d):
                if a == b:
                    common += 1
                else:
                    break
            if common >= 4 and abs(len(d) - len(name)) <= 5:
                return f' Did you mean `--{d}`?'
        return ''

    for name in sorted(undefined):
        count = undefined[name]
        hint = _suggest(name)
        iss.err('R-CSSVAR',
            f'`var(--{name})` referenced {count}× but never defined in any '
            'CSS source linked from this deck. Browser silently fails the '
            'surrounding declaration — common consequence: `font:` shorthand '
            'parse fails → font-size falls back to browser default 16px.' +
            hint)


def audit_bullet_dash(html: str, iss: Issues):
    """R-BULLET-DASH: catch ad-hoc dash-shaped li::before bullets (added 2026-05-22).

    Framework supplies `.feature-list` with branded colored-dot bullets.
    Ad-hoc dash bullets (`width: 8px; height: 1.5px`) are dim, off-brand,
    and bypass the framework component library.

    Detects rules matching `li::before { width: Npx; height: Mpx }` where
    width > 4 × height (dash aspect ratio). Suggests `.feature-list` class.
    """
    for raw_css, _is_fw in _iter_style_blocks(html, include_framework=False):
        css = _strip_nested_at_rules(raw_css)
        for m in re.finditer(r'([^{}]*li(?:::?before|:before)[^{}]*)\{([^}]+)\}', css):
            selector = m.group(1).strip()
            block = m.group(2)
            w_m = re.search(r'width:\s*([\d.]+)px', block)
            h_m = re.search(r'height:\s*([\d.]+)px', block)
            if not (w_m and h_m): continue
            w, h = float(w_m.group(1)), float(h_m.group(1))
            if w >= 4 and h <= 3 and w >= 3 * h:
                iss.warn('R-BULLET-DASH',
                    f'ad-hoc dash bullet on `{selector}` ({w}×{h}px). '
                    'Framework supplies `.feature-list` with branded colored '
                    'dot bullets (8×8 round + halo). Use `<ul class="feature-list">` '
                    'instead — see SKILL.md "Component utility classes" section. '
                    'For multi-color cards, override `.is-<color> li::before { '
                    'background: var(--fs-<color>) }` per accent.')


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
    for raw_css, _is_fw in _iter_style_blocks(html):
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
                if _BOX_SHADOW_INSET_RE.search(value):
                    continue           # inset shadows OK
                if _BOX_SHADOW_GLOW_RING_RE.match(value):
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


def audit_hex_palette(html: str, iss: Issues):
    """R10: all hex values inside slide markup come from --fs-* tokens.

    Strips script/style/svg AND data: URIs first — base64 strings can
    contain '#xxx' false matches.

    Always emits as warning; `main()` promotes all warnings → errors in
    --strict mode globally (see end of main()).
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


def audit_perf(html: str, iss: Issues):
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
    style_text  = ' '.join(body for body, _is_fw in _iter_style_blocks(html))
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
            iss.warn('P50', msg)  # main() promotes warn→err globally in --strict

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
    # 2026-05-18 round 2: walk DOM via `_walk_text_leaves` so the audit
    # works on `<div class="header is-tall">` AND on header markup that
    # nests a wrapper-div (`<div class="header"><div class="wrap"><h2>…</h2>`
    # `</div><div class="eyebrow">…</div></div>`). The previous regex
    # `<div\s[^>]*class="(?:[^"]*\s)?header(?:\s[^"]*)?"[^>]*>(.*?)</div>`
    # closed at the first `</div>` and missed siblings of the wrapper.
    # The walker yields every leaf with its full parent-class chain, so
    # we can ask: "is any `.eyebrow` leaf an ancestor-descendant of a
    # `.header` block on a non-hero layout?"
    for i, fr in enumerate(slides, 1):
        layout = slide_attr(fr, 'layout') or '?'
        if layout in HERO_TITLE_LAYOUTS:
            continue
        # Quick reject: if the slide markup never mentions `eyebrow`, no
        # need to walk. (eyebrow as a string match elsewhere — e.g. in a
        # comment or inside text content — is excluded by the leaf check.)
        if 'eyebrow' not in fr:
            continue
        for leaf in _walk_text_leaves(fr):
            # Is THIS leaf an `.eyebrow` element AND inside a `.header`?
            leaf_classes = (leaf['class'] or '').split()
            if 'eyebrow' not in leaf_classes:
                # Also flag eyebrow on parent of the leaf (eyebrow may
                # contain its own leaf text). Check parent chain.
                if not any('eyebrow' in (p or '').split()
                            for p in leaf['parents']):
                    continue
            # Is any ancestor a `.header`? (whole-word in class list)
            if any('header' in (p or '').split() for p in leaf['parents']):
                iss.warn('R56',
                    f'slide {i} ({layout}): .header still contains an .eyebrow. '
                    'CSS hides it visually but the markup should be removed too '
                    '— the content-page header is title-only.')
                break  # one warning per slide is enough


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


def audit_language_policy(html: str, slides: list[str], iss: Issues):
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
    # HTML attribute order is irrelevant; match `<meta>` and then look up
    # name= / content= individually. The previous regex required name= to
    # appear before content= and silently fell through to zh-only on
    # `<meta content="zh-en" name="fs-language">` — false-positives on a
    # deliberately bilingual deck (B2 fix 2026-05-18).
    mode = 'zh-only'
    for meta_tag in re.findall(r'<meta\s[^>]*>', html):
        name_m = re.search(r'\bname\s*=\s*"([^"]+)"', meta_tag)
        if not name_m or name_m.group(1).strip().lower() != 'fs-language':
            continue
        content_m = re.search(r'\bcontent\s*=\s*"([^"]+)"', meta_tag)
        if content_m:
            mode = content_m.group(1).strip().lower()
        break

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
            iss.warn('R-LANG', msg)  # main() promotes warn→err in --strict
            break  # one report per slide is enough

    # 2026-05-16 · Additional check: Latin-uppercase chrome tags inside
    # short text leaves (span / p / div with eyebrow / kicker / pill / tag
    # / -tag / -eyebrow class names). The deck shouldn't carry "MODE 01" /
    # "DEADLINE" / "SKILL" / "PREDIT" as chrome labels when the page-level
    # language is zh-only — they look like rolling EN translation tracks.
    # Brand names / product codes / acronyms are exempt via whitelist.
    LATIN_BRAND_WHITELIST = {
        'AI', 'API', 'HTML', 'CSS', 'JS', 'CLI', 'SDK', 'UI', 'UX',
        'PDF', 'PNG', 'JPG', 'SVG', 'CTA', 'KPI', 'OKR', 'ROI', 'SOP',
        'CXO', 'CEO', 'CTO', 'CFO', 'COO', 'CMO', 'CIO', 'VP', 'BD', 'KA',
        'PR', 'HR', 'IT', 'BG', 'BU',
        'SaaS', 'PaaS', 'IaaS', 'B2B', 'B2C', 'O2O', 'MVP',
        'LBP', 'IDC', 'AWS', 'GCP', 'OEM', 'ODM', 'NPS', 'GMV',
        'Q1', 'Q2', 'Q3', 'Q4', 'H1', 'H2',
        'Lark', 'Feishu', 'Codex', 'Mira', 'Flow', 'Base', 'Wiki',
        'OpenAI', 'Anthropic', 'Claude', 'GPT', 'LLM',
        # Industry-standard business system acronyms
        'ERP', 'CRM', 'WMS', 'PMS', 'MES', 'SCM', 'BI', 'OA', 'POS',
    }
    # Pattern: technical reference codes (BF10, R20, P32, M1 etc.) — short
    # uppercase prefix + digits. Used to cross-reference SKILL.md sections /
    # validator rules / postmortems. Common in meta-content decks like
    # examples/showcase.html. Auto-allow via regex (not enumerable).
    TECHNICAL_CODE_RE = re.compile(r'^[A-Z]{1,4}\d{1,4}[A-Z]?$')
    # Scan small text leaves whose markup smells like chrome labels.
    # 2026-05-18: added `-en`, `-eng`, `-english`, `-num`, `-index`, `-ord`
    # suffixes — these names strongly signal "this leaf holds an EN translation
    # / ordinal marker" and were the bypass route in the Tongrentang run
    # (custom classes `ap-num` containing "01 · AGGREGATE", `p5-col-en`
    # containing "PRODUCTION" slipped past the chrome scan).
    chrome_class_text_re = re.compile(
        r'<(?:span|p|div|h[1-6])\s[^>]*?'
        r'class="[^"]*\b(?:eyebrow|kicker|pill|tag|chip|badge|'
        r'\w+-tag|\w+-pill|\w+-eyebrow|\w+-chip|\w+-badge|'
        r'\w+-en|\w+-eng|\w+-english|\w+-num|\w+-index|\w+-ord|'
        r'nc-tag|db-tag|dl-eyebrow|mode-tag|side-pill|focus-pill|td-owner)\b'
        r'[^"]*"[^>]*>([^<]+)</(?:span|p|div|h[1-6])>',
        re.S)
    # Match a chunk that is purely Latin uppercase + digits + spaces + punctuation
    # (2-40 chars). `&` added 2026-05-18 so "R & D" registers. Pure-Latin gate
    # keeps CJK label content out.
    latin_uc_re = re.compile(r'^[A-Z0-9 ·\-/_&]{2,40}$')

    def _is_offending_latin(text: str) -> bool:
        text = text.strip()
        if not latin_uc_re.match(text):
            return False
        tokens = [t for t in re.split(r'[\s·\-/_&]+', text)
                  if t and not t.isdigit()]
        if not tokens:
            return False
        return not all(t in LATIN_BRAND_WHITELIST or TECHNICAL_CODE_RE.match(t)
                       for t in tokens)

    for i, fr in enumerate(slides, 1):
        for m in chrome_class_text_re.finditer(fr):
            text = m.group(1).strip()
            if not _is_offending_latin(text):
                continue
            iss.warn('R-LANG',
                f'slide {i}: chrome label `{text}` looks like a Latin label '
                'in a zh-only deck. If it\'s genuinely a brand / product / '
                'acronym, add it to LATIN_BRAND_WHITELIST in validate.py; '
                'otherwise translate to CJK (e.g. "MODE 01" → "方式 01", '
                '"DEADLINE" → "截止时间", "PREDIT"-style typos → fix).')

    # 2026-05-18 · Sibling-pair detection. The chrome-class scan above is
    # narrow (only fires on class names containing chrome-flavored tokens).
    # If an author uses an arbitrary class name to host EN translation copy
    # (real failure mode caught in Tongrentang run: `ap-num` containing
    # "01 · AGGREGATE" paired with sibling `ap-title` "审批聚合"), the chrome
    # scan misses it but the leaf is still a translation track.
    #
    # The structural signature is: a parent element with ≥ 2 text-leaf
    # children where one leaf is pure-Latin and another sibling leaf
    # contains CJK. That pair IS the translation track.
    #
    # We use html.parser (stdlib, no extra deps) to walk the DOM and find
    # such pairs. Brand-whitelist / technical-code allowlist still apply.
    audit_translation_track_pairs(html, slides, iss, _is_offending_latin)


# ---------------------------------------------------------------------------
#  R-LANG enhancement (2026-05-18): sibling-pair translation-track detector
# ---------------------------------------------------------------------------

_CJK_RE = re.compile(r'[一-鿿㐀-䶿豈-﫿]')
_HTML_LEAF_TAGS = {
    'span', 'p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'li', 'a', 'b', 'em', 'strong', 'i', 'u', 'small', 'mark',
    'blockquote', 'dt', 'dd', 'figcaption', 'caption', 'th', 'td',
}
_HTML_VOID_TAGS = {
    'br', 'hr', 'img', 'input', 'meta', 'link', 'source', 'area',
    'base', 'col', 'embed', 'param', 'track', 'wbr',
}
_HTML_SKIP_CONTAINERS = {'script', 'style', 'svg'}


def _walk_text_leaves(fragment: str) -> list[dict]:
    """Walk `fragment` via stdlib html.parser; return text-bearing leaves.

    Each leaf dict carries:
      tag          element name ('span', 'p', etc.)
      class        class attribute value (string, possibly multi-class)
      text         direct text content, stripped
      parents      list of parent class strings, closest-last
      parent_class parents[-1] if parents else ''
      parent_id    unique monotonic int for the immediate parent — group
                   by this to reconstruct sibling sets after the walk

    Void tags (`<br>` / `<img>` / etc.) are ignored; `<script>` /
    `<style>` / `<svg>` are skipped wholesale. Malformed HTML errors
    are swallowed — R-DOM is the place that reports structural
    breakage.
    """
    from html.parser import HTMLParser

    leaves: list[dict] = []

    class W(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.stack: list[dict] = []
            self.skip = 0
            self._next_id = 0

        def handle_starttag(self, tag, attrs):
            if tag in _HTML_VOID_TAGS:
                return
            if tag in _HTML_SKIP_CONTAINERS:
                self.skip += 1
                self.stack.append({'tag': tag, 'class': '', 'text': '',
                                    'has_children': False, 'id': -1})
                return
            cls = next((v or '' for k, v in attrs if k == 'class'), '')
            nid = self._next_id; self._next_id += 1
            self.stack.append({'tag': tag, 'class': cls, 'text': '',
                                'has_children': False, 'id': nid})

        def handle_endtag(self, tag):
            if tag in _HTML_VOID_TAGS:
                return
            if not self.stack:
                return
            f = self.stack.pop()
            if f['tag'] in _HTML_SKIP_CONTAINERS:
                self.skip -= 1
                return
            text = f['text'].strip()
            if self.stack:
                self.stack[-1]['has_children'] = True
            if text and not f['has_children'] and f['tag'] in _HTML_LEAF_TAGS:
                parents = [s.get('class', '') for s in self.stack]
                parent_frame = self.stack[-1] if self.stack else None
                leaves.append({
                    'tag': f['tag'],
                    'class': f['class'],
                    'text': text,
                    'parents': parents,
                    'parent_class': parents[-1] if parents else '',
                    'parent_id': parent_frame['id'] if parent_frame else -1,
                    'parent_tag': parent_frame['tag'] if parent_frame else '',
                })

        def handle_data(self, data):
            if self.skip > 0:
                return
            if self.stack:
                self.stack[-1]['text'] += data

    try:
        W().feed(fragment)
    except Exception:
        pass
    return leaves


# F-12: chart/diagram scaffolding naturally sits beside CJK and is NOT a
# translation track. A matrix axis pole (HIGH/LOW inside .y-axis), a legend
# key, a scale cap, or a data sublabel ("2025 Q4 BASELINE") paired with a CJK
# sibling is expected design — the sibling-pair detector must skip these.
#
# Matched as whole space-delimited class TOKENS, not \b-substrings: '-' is a
# regex word boundary, so \bscale\b would wrongly hit content classes like
# 'scale-section' / 'large-scale' / 'legend-item' / 'axis-title' and even the
# framework's own 'fs-scale' wrapper — silently swallowing genuine EN
# translation tracks living in those classes (caught in adversarial review).
# (We deliberately do NOT also skip by text pattern: a standalone year/number
# is already non-offending via is_offending_latin's all-digit-token exclusion,
# and a substring year/Qn match would wrongly mute real headers like
# "ANNUAL REVIEW 2025" / "VISION 2030".)
_CHART_SCAFFOLD_CLASSES = {
    'x-axis', 'y-axis', 'axis', 'sublabel', 'legend', 'scale', 'tick', 'gridline',
}


def _is_chart_scaffold_class(cls) -> bool:
    return bool(cls) and any(t in _CHART_SCAFFOLD_CLASSES for t in cls.split())


def audit_translation_track_pairs(html: str, slides: list[str], iss,
                                   is_offending_latin) -> None:
    """For each slide: collect leaves via `_walk_text_leaves`, group by
    parent_id, flag parents whose direct children include BOTH a CJK
    leaf AND a Latin-only leaf. That pair IS the canonical
    translation-track signature.

    Layout-only parents (`tr / table / thead / tbody / ul / ol / dl /
    figure`) are EXCLUDED — they routinely host bilingual columns by
    design (e.g. CJK row label + EN data cell in a reference table).
    The translation-track signature only applies to siblings inside a
    SEMANTIC container (`.head / .card / .col-text / .stage / etc.`).
    Round 2 review caught this as a refactor regression: pre-bbc8db6,
    the per-parent pair-check was gated on the parent's tag being a
    leaf-tag, which incidentally excluded these layout-only parents.
    """
    for i, fr in enumerate(slides, 1):
        leaves = _walk_text_leaves(fr)
        if not leaves:
            continue
        by_parent: dict[int, list[dict]] = {}
        for leaf in leaves:
            by_parent.setdefault(leaf['parent_id'], []).append(leaf)

        seen = set()
        for sibs in by_parent.values():
            if len(sibs) < 2:
                continue
            parent_tag = sibs[0]['parent_tag']
            # Skip layout-only parents — bilingual columns inside tables /
            # lists / figures are expected design, not translation tracks.
            if parent_tag in _LAYOUT_ONLY_PARENT_TAGS:
                continue
            cjk_lvs = [l for l in sibs if _CJK_RE.search(l['text'])]
            lat_lvs = [l for l in sibs if is_offending_latin(l['text'])]
            parent_class = sibs[0]['parent_class']
            # F-12: skip chart/diagram scaffolding (axis poles, legend keys,
            # scale caps, data sublabels) — beside-CJK by design, not
            # translation tracks. Group-skip on a scaffold parent; otherwise
            # drop individual scaffold-class Latin leaves.
            if _is_chart_scaffold_class(parent_class):
                continue
            lat_lvs = [l for l in lat_lvs
                       if not _is_chart_scaffold_class(l['class'])]
            if not (cjk_lvs and lat_lvs):
                continue
            # Empty parent class → reference parent by tag for clarity
            parent_ref = (f'class="{parent_class[:60]}"' if parent_class
                          else f'<{parent_tag}>')
            for l in lat_lvs:
                key = (l['class'], l['text'])
                if key in seen:
                    continue
                seen.add(key)
                iss.warn('R-LANG',
                    f'slide {i}: `<{l["tag"]} class="{l["class"][:60]}">'
                    f'{l["text"][:60]}` — Latin-only leaf paired with CJK '
                    f'sibling inside `<… {parent_ref}>` looks like an EN '
                    'translation track. Drop the Latin leaf, translate to '
                    'CJK, opt into bilingual via `<meta name="fs-language" '
                    'content="zh-en">`, or add the term to '
                    'LATIN_BRAND_WHITELIST in validate.py if it is '
                    'genuinely a brand / acronym.')


# Tags that are STRUCTURAL containers (rows / list-bodies / table-bodies)
# rather than semantic content blocks. Their direct children are EXPECTED
# to be sibling cells / items, not translation pairs.
_LAYOUT_ONLY_PARENT_TAGS = {
    'tr', 'table', 'thead', 'tbody', 'tfoot',
    'ul', 'ol', 'dl', 'figure', 'select', 'fieldset',
}


def audit_list_echo(slides: list[str], iss: 'Issues'):
    """R-ECHO: detect a leaf whose text echoes 3+ sibling-leaf prefixes.

    Real failure pattern (Tongrentang P05): the deck has a 5-column scene
    matrix with column titles `研发提效 / 生产保质 / 营销升级 / 供应链强化 /
    高效工作`. A footer leaf reads:
        `已落地 42+ 场景模板,覆盖研发、生产、营销、供应链、行政关键域`
    The footer mentions 4 of those column titles in abbreviated form
    (研发 / 生产 / 营销 / 供应链). Pure redundancy — the columns ARE
    those domains, the footer re-lists them, wasting a sentence.

    Signature:
      • target leaf contains 3+ DISTINCT short substrings
      • each substring is the first 2-4 chars of ANOTHER leaf's text
        on the same slide

    Skip when:
      • target leaf is an H1-H6 (titles can summarize legitimately)
      • slide is an agenda / TOC / outline layout (echoing IS the point)
      • slide is a section divider (chapter pills echo agenda by design)

    Warn-level: editorial judgment may legitimately require an echo
    (e.g., a closing summary that restates an agenda). Author decides
    whether to act. Promoted to error only in --strict mode.
    """
    # Leaf collection delegated to the shared walker; this audit just
    # post-processes the flat list.

    # Slide-level layout context for skip detection
    _SKIP_LAYOUT_RE = re.compile(
        r'data-layout="(agenda|section|cover|end)"')
    # Class names on parent chain that signal "echo is intentional"
    # story-arc: a one-pager case's 痛点/冲突/解法/价值 beats are sequential
    # narrative about ONE customer/scene, so cross-beat entity echo
    # (新店 / 瑞幸 / …) is cohesion by design, not a summary restatement.
    _SKIP_PARENT_CLS = ('agenda', 'toc', 'outline', 'chapter-list',
                        'section-list', 'pills', 'tabs', 'story-arc')
    # Minimum target leaf length to consider as a "summary" candidate.
    # Below this, a leaf is too short to be summarizing anything.
    _MIN_TARGET_LEN = 12
    # Minimum prefix length to consider as a "name match". 1-char matches
    # are too noisy (every Chinese deck has single chars in common); 2-4
    # chars is the typical short-name range.
    _PREFIX_LENS = (4, 3, 2)
    # Minimum prefix that's actually a meaningful word (not a stop word).
    _STOPWORDS = {'的', '是', '在', '了', '和', '或', '与', '及',
                  '我们', '你们', '他们', '这是', '那是',
                  '一个', '一些', '一种', '本次', '本周', '本月'}
    # 2026-05-18 · TARGET-CLASS WHITELIST.
    # The R-ECHO signature (1 leaf containing N other-leaf prefixes) ALSO
    # fires legitimately inside UI mockups, chat windows, data tables where
    # the same customer name / field name appears across rows by design.
    # To avoid those false positives we only consider a leaf as a target
    # if its class (or one of its ancestor classes) carries a "summary
    # intent" marker, OR if the leaf is a `<p>` tag (paragraphs are the
    # canonical summary host).
    _TARGET_INTENT = (
        'legend', 'note', 'footnote', 'caption', 'summary',
        'footer', 'disclaimer', 'callout', 'lede', 'subline',
        'subtitle', 'recap', 'echo', 'desc-foot', 'page-sub',
        'tagline', 'kicker',
    )

    for i, fr in enumerate(slides, 1):
        # Skip layouts where echo is by design
        if _SKIP_LAYOUT_RE.search(fr):
            continue
        leaves = _walk_text_leaves(fr)
        if len(leaves) < 4:  # too few to have meaningful echo
            continue

        for ti, target in enumerate(leaves):
            # Heuristic skips for target
            if target['tag'] in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
                continue
            text = target['text']
            if len(text) < _MIN_TARGET_LEN:
                continue
            # Skip targets whose parent chain says echo is intentional
            if any(any(s in p for s in _SKIP_PARENT_CLS)
                   for p in target['parents']):
                continue
            # Skip targets that are CJK-poor (likely Latin chrome)
            cjk_chars = sum(1 for c in text if '一' <= c <= '鿿')
            if cjk_chars < 4:
                continue
            # Target-intent gate: only consider leaves that LOOK like
            # they're hosting a summary/legend/footnote/caption. Plain
            # `<p>` tags also qualify (paragraph is the canonical
            # summary host).
            tgt_cls = (target['class'] or '').lower()
            parent_cls = ' '.join(target['parents']).lower()
            looks_like_summary = (
                target['tag'] == 'p' or
                any(kw in tgt_cls for kw in _TARGET_INTENT) or
                any(kw in parent_cls for kw in _TARGET_INTENT)
            )
            if not looks_like_summary:
                continue

            matches = set()  # distinct prefix tokens that hit
            matched_other_idx = set()
            for oi, other in enumerate(leaves):
                if oi == ti:
                    continue
                otext = other['text']
                if not otext or otext == text:
                    continue
                # Probe progressively shorter prefixes
                for n in _PREFIX_LENS:
                    if len(otext) < n:
                        continue
                    prefix = otext[:n]
                    if prefix in _STOPWORDS:
                        continue
                    # require CJK in the prefix to avoid Latin noise
                    if not any('一' <= c <= '鿿' for c in prefix):
                        continue
                    if prefix in text:
                        matches.add(prefix)
                        matched_other_idx.add(oi)
                        break  # don't double-count the same other-leaf
            if len(matches) >= 3:
                preview = text if len(text) <= 60 else text[:57] + '…'
                hit = ' / '.join(sorted(matches))
                iss.warn('R-ECHO',
                    f'slide {i}: leaf text `{preview}` echoes '
                    f'{len(matches)} other-leaf prefixes on the same slide '
                    f'({hit}). Likely redundant summary — consider dropping '
                    'the echoed list and keeping only the new information '
                    '(numbers / verbs / next-step). If the echo is '
                    'intentional (e.g. closing recap of an earlier list), '
                    'this warn is editorial — leave as-is.')


def audit_hierarchy(html: str, iss: Issues):
    """R-HIERARCHY: visual size hierarchy must respect semantic hierarchy.

    Within a card / panel / list-item, meta-info (owner / attribution /
    source / timestamp / status / kicker) is structurally LESS important
    than the body content it describes. If the meta element is BIGGER
    than the body it labels, the reader's eye gets pulled to the meta
    first — visual hierarchy contradicts semantic hierarchy.

    Concrete rule: any selector matching META_CLASS_RE that authors a
    font-size > 24 (Body floor) in per-page CSS triggers a warning. The
    24 ceiling is because body classes are at 24 (Body tier); meta on the
    SAME card should be ≤ 24, never above.

    Exempt:
      • Column-label classes that ARE the column's title (e.g. .side-pill
        for `困境` / `解法`, .focus-pill for `重点客群`). These are NOT
        meta — they're content labels. They live in a separate name
        bucket: .column-pill / .side-pill / .focus-pill / .section-tag.
      • Rules with `/* allow:meta-larger */` opt-out (rare, e.g. when the
        owner literally IS the slide's hero — unusual but possible).
    """
    # Use negative lookahead `(?![-_\w])` instead of `\b` so compound class
    # names like `.kicker-bar` / `.byline-link` / `.timestamp-label` don't
    # match — `\b` treats `-` as a word boundary in regex, but we want the
    # class name to END after the meta term.
    META_CLASS_RE = re.compile(
        r'\.(?:'
        r'owner|attrib|source(?:-footer)?|who|byline|author-meta|'
        r'timestamp|date|status|kicker|'
        r'td-owner|nc-author|case-attrib|quote-attrib|voice-who|'
        r'eyebrow'    # eyebrow is meta-tier by tradition
        r')(?![-_\w])'
    )
    # Selectors that LOOK like meta but are actually column labels — exempt.
    # Only list classes that ARE shipped in feishu-deck.css or referenced in
    # SKILL.md recipes; dead exemptions hide bugs.
    COLUMN_LABEL_RE = re.compile(
        r'\.(?:column-pill|side-pill|focus-pill|'
        r'agenda-label|story-label|case-label)(?![-_\w])'
    )

    for raw, _is_fw in _iter_style_blocks(html, include_framework=False):
        css = _strip_nested_at_rules(raw)
        for rule_m in _RULE_WITH_COMMENTS_RE.finditer(css):
            # Strip any leading/trailing comments from the captured selector
            # (the regex eats them as part of [^{}]+? if they appear between
            # rules). Without this, a trailing `/* meta ... */` after a rule
            # gets picked up as the NEXT rule's selector.
            selector = re.sub(r'/\*.*?\*/', '', rule_m.group(1), flags=re.S).strip()
            if not selector:
                continue
            body_with_comments = rule_m.group(2)
            if 'allow:meta-larger' in body_with_comments:
                continue
            if not META_CLASS_RE.search(selector):
                continue
            if COLUMN_LABEL_RE.search(selector):
                continue
            # Strip comments to get pure rule block
            block = re.sub(r'/\*.*?\*/', '', body_with_comments, flags=re.S)
            sizes = []
            for fm in re.finditer(r'font-size:\s*(\d+)px', block):
                sizes.append(int(fm.group(1)))
            for fm in re.finditer(r'\bfont:\s*[^;{}]*?(\d+)px', block):
                sizes.append(int(fm.group(1)))
            for size in sizes:
                if size > FLOOR_BODY_PX:
                    iss.warn('R-HIERARCHY',
                        f'meta-class selector `{selector[:80]}` at '
                        f'{size}px (> body floor {FLOOR_BODY_PX}px). Meta '
                        '(owner / attrib / source / timestamp / kicker / '
                        'eyebrow) must NOT exceed body — otherwise visual '
                        'hierarchy reads inverted: the reader\'s eye '
                        'lands on "who" before "what". Drop to ≤ 24, OR '
                        'add `/* allow:meta-larger */` if this is a '
                        'deliberate hero exception (very rare). If this '
                        'is actually a column-LABEL (e.g. column-pill, '
                        'side-pill), rename the class — column labels '
                        'belong to a different name bucket.')
                    break  # one warn per rule is enough


def audit_default_centering(html: str, iss: Issues):
    """R48: every fixed-shape container layout vertically centers by default.

    Aggregate across ALL `<style>` blocks before checking — a deck's inline
    `<style>` can override framework rules with custom grid-template-columns
    WITHOUT replicating the centering decl, because the framework rule still
    applies (the override's specificity doesn't strip the inherited
    `align-content: center` cascading from the broader `.slide[data-layout]`
    rule). So R48 is satisfied if ANY rule across the document defines
    centering for the layout — checking per-block over-flags every override.
    """
    css_combined = []
    for raw, _is_fw in _iter_style_blocks(html):
        cleaned = re.sub(r'/\*.*?\*/', '', raw, flags=re.S)
        cleaned = _strip_nested_at_rules(cleaned)
        css_combined.append(cleaned)
    full_css = '\n'.join(css_combined)
    for missing in check_default_centering(full_css):
        iss.err('R48',
            f'data-layout="{missing}" container has no vertical-centering '
            'rule (justify-content / align-content / align-items: center) '
            'anywhere in the deck\'s CSS. Fixed-shape layouts must '
            'default-center so short content doesn\'t strand at the top '
            'with empty bottom. pipeline / timeline / process are explicit '
            'exceptions that fill.')


def audit_empty_header_zone(html: str, iss: Issues):
    """R-EMPTY-HEADER-ZONE: when a slide hides framework .header in per-page
    CSS, .stage must not leave an empty dark zone at slide top.

    Framework convention: the unified `.slide[data-layout=...] .header` rule
    positions the title at slide y=61, providing a visual anchor consistent
    across all content slides. When a slide hides it via `display: none`
    (usually to gain vertical space), the slide MUST compensate by either:
      (a) restoring .header (drop the `display:none` rule),
      (b) snapping .stage top to ≤32 (content sits at slide top edge),
      (c) aligning .stage top to 61 (matches framework anchor — visual
          consistency with sibling slides), or
      (d) adding a visible top decoration inside .stage's first child.

    Otherwise the gap between slide y=0 and the first content reads as
    "missing background / black band at top" — especially on dark themes
    with diagonal-glow decor (mix-glow) that don't tint the top corners.

    Postmortem 2026-05-24: slide management-clone-flywheel had
    `.header { display: none }` + `.stage { top: 50px }`. User reported
    「上面有一条黑色,背景没有全」. Took 3 round-trips to localize and
    fix; this rule formalizes the lesson so future hidden-header slides
    catch it automatically.
    """
    for sm in re.finditer(r'<style[^>]*>(.*?)</style>', html, re.S):
        css = re.sub(r'/\*.*?\*/', '', sm.group(1), flags=re.S)
        # Find scoped slide-key (per-page styles are scoped via
        # .slide[data-slide-key="K"] prefix; first occurrence wins)
        key_m = re.search(r'\.slide\[data-slide-key="([^"]+)"\]', css)
        if not key_m:
            continue
        key = key_m.group(1)

        # Is .header hidden for this slide?
        hide_pat = (
            rf'\.slide\[data-slide-key="{re.escape(key)}"\]'
            r'[^{]*\.header(?![\w-])[^{]*\{[^}]*display\s*:\s*none[^}]*\}'
        )
        if not re.search(hide_pat, css):
            continue

        # Find .stage top value
        stage_pat = (
            rf'\.slide\[data-slide-key="{re.escape(key)}"\]'
            r'[^{]*\.stage(?![\w-])[^{]*\{([^}]*)\}'
        )
        sm2 = re.search(stage_pat, css)
        if not sm2:
            continue
        top_m = re.search(r'(?<![\w-])top\s*:\s*(\d+)\s*px', sm2.group(1))
        if not top_m:
            continue
        top_val = int(top_m.group(1))

        # Allowed zones: ≤32 (snap-to-top) or ==61 (framework anchor)
        if top_val <= 32 or top_val == 61:
            continue

        iss.warn(
            'R-EMPTY-HEADER-ZONE',
            f'slide-key="{key}": hides framework .header but .stage starts '
            f'at top:{top_val}px — leaves empty dark zone at slide y=0..{top_val}, '
            f'reads as "missing bg / black band" on dark theme (especially '
            f'with diagonal-glow decor that doesn\'t tint top corners). '
            f'Pick one: (a) restore .header (drop the `display:none` rule), '
            f'(b) snap top ≤32 (content at slide edge), (c) align top:61 '
            f'(matches framework anchor — visually consistent with sibling '
            f'slides), or (d) add a visible top decoration as .stage\'s '
            f'first child.'
        )


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


def audit_lift_style_lost(html: str, iss: Issues):
    """R-VIS-LIFT-STYLE-LOST: lifted slide with `data-layout="raw"` and near-
    empty inline `<style>` likely lost framework styling.

    Triggered by 2026-05-29 P14 incident: source #14 was `data-layout="quote"`
    with NO inline <style> — entire visual (92px blockquote / 30px attrib /
    stack flex centering) came from framework's `.slide[data-layout="quote"]`
    rules. Lift to `data-layout="raw"` made those rules stop matching →
    blockquote rendered at browser default 16px. R-VIS-BODY-FLOOR caught the
    16px but was downgraded to WARN due to `data-lifted` tag — drowned in the
    "source's original size choices" warnings. The TRUE bug ("lift broke
    styling") had no dedicated audit.

    Detection: For each .slide with both `data-lifted` and `data-layout="raw"`,
    sum the byte size of inline `<style>` blocks. If under 300 bytes AND the
    slide content uses class names typically styled by a specific framework
    layout (.stack/.attrib/blockquote for quote; .chapter-num/.pills for
    section; .author for cover; .num+.copy for big-stat), emit ERROR.

    Recommended fix: re-lift with `assets/lift-slides.py` (which auto-inlines
    framework CSS for quote/cover/section/big-stat/end since 2026-05-29), OR
    switch the slide's `layout` field to the schema layout directly.
    """
    # Find each .slide block manually via `frames = re.findall(...)` below.
    HEAVY_SIGNATURES = {
        'quote':    ['<blockquote', '<div class="attrib"', '<div class="stack"'],
        'cover':    ['<div class="author"'],
        'section':  ['<div class="chapter-num"', '<div class="pills"'],
        'big-stat': ['<div class="num"', '<div class="copy"'],
        'end':      ['<div class="slogan"'],
    }

    body_m = re.search(r'<body[^>]*>(.*)</body>', html, re.S)
    if not body_m:
        return
    body = body_m.group(1)

    # Split body by slide-frame to look at each slide
    frames = re.findall(r'<div class="slide-frame"[^>]*>(.*?)</div>\s*(?=<div class="slide-frame"|<div class="deck-ui"|$)',
                        body, re.DOTALL)
    for frame in frames:
        m = re.search(r'<div class="slide"([^>]+)>(.*)', frame, re.DOTALL)
        if not m: continue
        attrs, inner = m.group(1), m.group(2)
        if 'data-lifted' not in attrs: continue
        if 'data-layout="raw"' not in attrs: continue
        # Sum inline <style> blocks
        style_total = sum(len(s) for s in re.findall(r'<style[^>]*>(.*?)</style>', inner, re.DOTALL))
        if style_total >= 300: continue  # has substantial inline CSS, presumably OK
        # Check for heavy-layout signatures
        for orig_layout, sigs in HEAVY_SIGNATURES.items():
            if all(sig in inner for sig in sigs):
                key_m = re.search(r'data-slide-key="([^"]+)"', attrs)
                lab_m = re.search(r'data-screen-label="([^"]+)"', attrs)
                key = key_m.group(1) if key_m else '?'
                label = lab_m.group(1) if lab_m else '?'
                iss.err('R-VIS-LIFT-STYLE-LOST',
                    f'slide `{label}` (data-slide-key={key!r}) is lifted '
                    f'(data-lifted) + data-layout="raw" + inline `<style>` '
                    f'{style_total} bytes (<300) + content uses '
                    f'`{orig_layout}` layout signatures ({sigs}). The source '
                    f'slide\'s visual depended on framework `.slide[data-layout="'
                    f'{orig_layout}"]` rules, which no longer match after lifting '
                    f'to "raw" → slide renders at browser defaults (e.g. quote '
                    f'blockquote falls 92px → 16px). Fix: (1) re-lift with '
                    f'`assets/lift-slides.py` (auto-inlines framework CSS for '
                    f'quote/cover/section/big-stat/end since 2026-05-29), OR '
                    f'(2) switch the slide\'s layout field to `"{orig_layout}"` '
                    f'(schema layout, not raw), OR (3) manually inline the '
                    f'framework rules scoped to this slide-key. '
                    f'Per `data-lifted` lift-aware downgrade does NOT apply '
                    f'to this rule — this isn\'t the source\'s own size choices, '
                    f'it\'s a STYLE-LOSS bug introduced by the lift itself.')
                break


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


def audit_white_text(html: str, iss: Issues):
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
        iss.warn('R-WHITE-TEXT', msg)  # main() promotes warn→err in --strict


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
        iss.warn_soft('R-FEEDBACK',
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
        iss.warn_soft('R-FEEDBACK',
            f'{feedback.name} exists but is an unfilled auto-stub from '
            '`finalize.sh`. The agent must replace the placeholder '
            'sections with real decisions from this run BEFORE hand-off. '
            'Look for `## 关键决策(本 run 实际发生的判断)` — every entry '
            'should describe one concrete choice the agent made (layout '
            'pick, sizing tweak, validator workaround, copy shortening) '
            'with `**为什么**:` + checkbox. Drop the auto-stub HTML '
            'comment once you\'ve filled it in to silence this warning.')


def run_visual_audits(html_path: Path, iss: Issues, *,
                       want_screenshots: bool = False):
    """Single Playwright session that runs all `--visual` audits.

    Replaces standalone audit_visual_overflow. One Chromium launch covers:

      R-OVERFLOW       · per-slide scrollHeight > 1080 or scrollWidth > 1920
      R-VIS-TIER       · every text element's computed fontSize is on the
                         4-tier ladder {16, 24, 28, 48} or a documented hero
                         exception (88, 100, 132, 160) on hero-class selectors
      R-VIS-HIER       · within each card / panel, meta-class fontSize ≤
                         body-class fontSize (renderer-confirmed, not just
                         static CSS — catches inheritance / overrides)
      R-VIS-ALIGN      · grid containers (.overview-grid / .todo-grid / etc.)
                         have all direct children at roughly the same
                         bounding-box height (within 4 px tolerance)
      R-VIS-BODY-FLOOR · 2026-05-19 · text elements with ≥ 8 chars of direct
                         text rendered at < 24 px while NOT inside a mockup
                         container or chrome class. Catches the gap where
                         ambiguous short class names (.rt / .d / .ind-tag)
                         pass both R20 (16 is on ladder) and R06 (class-
                         heuristic). Renderer-aware: looks at actual
                         content length + container. Opt out per element
                         with `data-allow-body-floor`.
      R-VIS-ORPHAN     · 2026-05-25 · CJK leaf text that wraps to ≥2 lines
                         with a lonely ~1-char last line (orphan) OR a short
                         2-3 line label whose last line is < 38% of the
                         widest (上长下短 imbalance). `text-wrap: balance` in
                         feishu-deck.css prevents most; this WARNs on the
                         residue (fixed-width / flex-clamped containers where
                         balance can't help). Skips block-child sub-labels
                         (.role), SVG text, mockup-internal, nowrap. Note:
                         only audits deck slides — text inside prototype
                         <iframe>s is a separate document and not reached.

    Optionally archives PNG screenshots when want_screenshots=True.

    Speed: ~5 seconds for a 30-slide deck (vs ~40 s for per-slide
    screenshot). One Chromium launch, all assertions evaluate inside
    page.evaluate() so the round-trip cost stays minimal.

    Setup once:
        pip install playwright && python -m playwright install chromium
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        # Visual audits are default-on but gracefully degrade. Print a single
        # stderr hint (not a warning so it doesn't pollute the issue list /
        # break CI parsing) and continue with static-only output. Re-enable
        # by `pip install playwright && python -m playwright install chromium`,
        # or suppress this notice via `--no-visual`.
        print('  (visual audits skipped — playwright not installed; '
              'install with `pip install playwright && python -m playwright '
              'install chromium` to enable R-OVERFLOW / R-VIS-* checks)',
              file=sys.stderr)
        return

    url = html_path.resolve().as_uri()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080})
            page = context.new_page()
            # 2026-05-24 · was `wait_until='networkidle' timeout=10_000`.
            # Large decks (50+ slides with images/iframes) blew past 10s
            # because `networkidle` waits for ALL pending requests to settle.
            # The visual audit JS runs purely against the DOM and computed
            # styles — it doesn't need network-quiet, just DOM-ready. Switch
            # to `load` event (faster, fires when initial resources load),
            # bump timeout to 60s as belt-and-braces for big-deck image
            # decoding. Validated on ctg (53 slides) which previously
            # silently failed → 0 R-VIS-* hits.
            page.goto(url, wait_until='load', timeout=60_000)
            # Switch into present mode so each slide gets the full
            # 1920×1080 canvas (scroll mode would false-positive).
            page.evaluate("""
                () => {
                    const deck = document.querySelector('.deck');
                    if (deck) deck.setAttribute('data-mode', 'present');
                }
            """)
            page.wait_for_timeout(200)  # let layout settle

            # ----- One JS evaluation gathers EVERYTHING -----
            # Returns a structured report; Python then formats findings.
            report = page.evaluate(_visual_audit_js())

            # ----- Optional: archive screenshots -----
            shots_dir = None
            if want_screenshots:
                shots_dir = html_path.parent / (html_path.stem + '-previews')
                shots_dir.mkdir(parents=True, exist_ok=True)
                # Wait for deck JS to wire the .is-current class onto the
                # active slide-frame. After init, framework adds
                # `[data-js-ready]` to the deck and the CSS `:first-child`
                # fallback automatically de-activates (BF13), so we no
                # longer need to inject an override stylesheet here.
                try:
                    page.wait_for_function(
                        "() => document.querySelector('.deck[data-js-ready] .slide-frame.is-current') !== null",
                        timeout=3000)
                except Exception:
                    pass  # fall through; bleed may occur if JS never runs
                # Re-iterate slides, hashchange-navigate, screenshot each.
                slide_count = page.evaluate(
                    "() => document.querySelectorAll('.slide').length")
                for i in range(1, slide_count + 1):
                    page.evaluate(f"window.location.hash = '#{i}'")
                    # Wait for is-current to land on the expected frame
                    # (deck JS uses 1-based hash matching data-page).
                    try:
                        page.wait_for_function(
                            f"() => document.querySelector('.slide-frame[data-page=\"{i}\"]')?.classList.contains('is-current')",
                            timeout=1500)
                    except Exception:
                        pass
                    page.wait_for_timeout(350)  # CSS opacity transition is .25s; allow fade to finish
                    fname = f's{i:02d}.png'
                    page.screenshot(path=str(shots_dir / fname),
                                    full_page=False)

            browser.close()
    except Exception as e:
        iss.warn('R-VISUAL',
            f'visual checks could not run ({type(e).__name__}: {e}). '
            'Try `python -m playwright install chromium` if you have not '
            'yet, or open the deck in a browser manually to verify.')
        return

    # ----- Format findings from the JS report -----
    for entry in report.get('overflow', [])[:20]:
        bits = []
        delta_h = entry['h'] - 1080
        delta_w = entry['w'] - 1920
        if delta_h > 0: bits.append(f'height +{delta_h} px')
        if delta_w > 0: bits.append(f'width +{delta_w} px')
        iss.err('R-OVERFLOW',
            f'slide {entry["idx"]} ({entry["label"]}): content overflows '
            f'canvas — {", ".join(bits)}. Reduce content density, drop '
            'cards/rows, increase column count, or shorten body copy.')

    for entry in report.get('tier', [])[:20]:
        _lev = iss.warn if entry.get('lifted') else iss.err
        _note = (' — LIFTED slide (verbatim from another deck); downgraded '
                 'to WARNING, you choose whether to fix.' if entry.get('lifted') else '')
        _lev('R-VIS-TIER',
            f'slide {entry["slide_idx"]} · `{entry["selector"]}` renders '
            f'at {entry["computed_px"]}px (off the 4-tier ladder '
            '{16, 24, 28, 48} + hero whitelist). Snap to nearest tier, OR '
            'add `/* allow:typescale */` if this is a documented hero '
            f'exception (cover hero / section chapter-num / big-stat / etc.).{_note}')

    for entry in report.get('hier', [])[:20]:
        iss.err('R-VIS-HIER',
            f'slide {entry["slide_idx"]} · meta `{entry["meta_sel"]}` at '
            f'{entry["meta_px"]}px is BIGGER than body `{entry["body_sel"]}` '
            f'at {entry["body_px"]}px in the same card '
            f'(`{entry["card_sel"]}`). Visual hierarchy reads inverted — '
            'shrink meta to ≤ body, or rename to a column-pill class if '
            'this element is actually a column title (not meta).')

    for entry in report.get('align', [])[:20]:
        # Soft: 4 px tolerance is genuinely fuzzy (sub-pixel rounding on
        # Chromium fractional scale can produce 5 px deltas on perfectly
        # aligned grids). Editorial — flagged but never promoted to error.
        iss.warn_soft('R-VIS-ALIGN',
            f'slide {entry["slide_idx"]} · grid `{entry["grid_sel"]}` has '
            f'{entry["count"]} direct children with heights '
            f'{entry["heights"]} — max diff {entry["delta"]} px '
            f'(> 4 px tolerance). For canonical-card / overview-card '
            'grids the cards should be equal-height; check `flex: 1` is '
            'applied or `align-items: stretch` is set on the container.')

    for entry in report.get('title_position', [])[:20]:
        iss.err('R-VIS-TITLE-POSITION',
            f'slide {entry["slide_idx"]} (layout `{entry["layout"]}`) · '
            f'`.header` rendered at top:{entry["actual_top"]}px, expected '
            f'~{entry["expected_top"]}px (master spec). Likely cause: the '
            f'layout is missing from the framework header-positioning '
            'whitelist in `feishu-deck.css` / `extra-layouts.css`. Add '
            f'`.slide[data-layout="{entry["layout"]}"] .header` to the '
            'unified positioning rule (`position:absolute; top:61px; '
            'left:73px; right:320px`) so title aligns with the master '
            'spec across all layouts.')

    for entry in report.get('opt_out_abuse', [])[:20]:
        ex_str = (f' (e.g. {", ".join(entry["examples"])})'
                  if entry.get('examples') else '')
        iss.warn('R-VIS-OPT-OUT-ABUSE',
            f'slide {entry["slide_idx"]} has {entry["count"]} occurrences of '
            f'`{entry["type"]}` (threshold: {entry["threshold"]}){ex_str}. '
            'opt-out attribute / comment is documented exception, NOT '
            'silence button. Batch-muting validator warnings hides real '
            'issues (text too small / chrome class abuse / palette drift). '
            'Fix: revisit each opt-out — if it is true by-design chrome / '
            'axis label / decorative element, KEEP it AND write a one-line '
            'justification comment; if it is regular body content, REMOVE '
            'the opt-out and bump to 24 (or use brand color, etc). '
            'Documented exception is 1-3 per slide, not 6+.')

    for entry in report.get('card_overflow', [])[:20]:
        direction = entry.get('direction', 'vertical')
        if direction == 'horizontal':
            iss.err('R-VIS-CARD-OVERFLOW',
                f'slide {entry["slide_idx"]} · `{entry["selector"]}` is a '
                f'flex/grid container with nowrap children — total children '
                f'width ({entry["content_h"]} px) exceeds container width '
                f'({entry["card_h"]} px) by {entry["overflow_px"]} px. '
                'Children are bleeding past the right edge (visible overflow) '
                'or being silently clipped. Fix: shorten child text, move one '
                'child to a separate line (display:block sibling), set '
                '`flex-wrap: wrap`, or widen the container.')
        elif direction == 'vertical-visible':
            iss.err('R-VIS-CARD-OVERFLOW',
                f'slide {entry["slide_idx"]} · `{entry["selector"]}` content '
                f'({entry["content_h"]} px) is {entry["overflow_px"]} px taller '
                f'than its box ({entry["card_h"]} px) and overflow is NOT hidden '
                '— text is spilling visibly out the bottom past the border / '
                'background. The slide still fits the 1920×1080 canvas, so '
                'R-OVERFLOW misses it; the clip-only check missed it too because '
                'overflow is visible. Fix: shorten body copy, drop a row / item, '
                'tighten padding / gap, or give the box more height. (Geometry — '
                'stays ERROR even on lifted slides; a visible spill is a real defect.)')
        else:
            iss.err('R-VIS-CARD-OVERFLOW',
                f'slide {entry["slide_idx"]} · `{entry["selector"]}` has '
                f'`overflow:hidden` but content ({entry["content_h"]} px) is '
                f'{entry["overflow_px"]} px taller than the container '
                f'({entry["card_h"]} px) — text is being clipped silently. '
                'Fix: shorten body copy, drop a row/item, shrink padding/gap, '
                'increase card height (more stage space), OR drop overflow:hidden '
                'so the issue is at least visible.')

    for entry in report.get('overlap', [])[:20]:
        iss.err('R-OVERLAP',
            f'slide {entry["slide_idx"]} · siblings inside `{entry["container_sel"]}` '
            f'physically overlap: `{entry["a_sel"]}` and `{entry["b_sel"]}` '
            f'intersect by {entry["overlap_x"]}×{entry["overlap_y"]} px. '
            'One sibling overflowed its allocated row/column and crashed '
            'into another. Fix: tighten content (smaller padding/gap, fewer '
            'items), expand the container (use `.stage.stage--tall` for 750 px '
            'vs default 680 px height), or add `min-height: 0; overflow: hidden` '
            'on the overflowing element so excess content is clipped instead of '
            'bleeding into siblings.')

    for entry in report.get('label_floor', [])[:20]:
        _lev = iss.warn if entry.get('lifted') else iss.err
        _lev('R-VIS-LABEL-FLOOR',
            (('LIFTED slide (verbatim) — downgraded to WARNING, you choose whether to bump. ')
             if entry.get('lifted') else '') +
            f'slide {entry["slide_idx"]} · card `{entry["card_sel"]}` '
            f'contains content-tier text (≥28px) but label '
            f'`{entry["label_sel"]}` is {entry["label_px"]}px — '
            'content-card labels MUST be ≥ 24 (Body tier). 16/18 chrome '
            'is reserved for true page metadata (.source / .pageno / '
            '.footnote / .attrib / etc., reached via .header / .footer '
            'ancestor). See SKILL.md "Hero-context label floor". '
            'Promote to 24 + differentiate via font-weight or brand '
            'color, not by shrinking the size.')

    for entry in report.get('body_floor', [])[:20]:
        _lev = iss.warn if entry.get('lifted') else iss.err
        _lev('R-VIS-BODY-FLOOR',
            (('LIFTED slide (verbatim from another deck) — downgraded to '
              'WARNING, you choose whether to bump. ') if entry.get('lifted') else '') +
            f'slide {entry["slide_idx"]} · `{entry["selector"]}` renders at '
            f'{entry["rendered_px"]}px but its direct text is '
            f'{entry["char_count"]} chars ("{entry["preview"]}"). '
            'Body content (≥ 8 chars of sentence-like text outside mockup '
            'containers and chrome classes) must be ≥ 24 px on projector. '
            'Bump to 24 (preferred), OR rename to a chrome class '
            '(.eyebrow / .footnote / .source / .pill / .tag / .chip / '
            '.badge / .pageno / .demo-tag) if it really is chrome, OR set '
            '`data-allow-body-floor` on the element for a documented '
            'exception (e.g. legend annotation by design).')

    for entry in report.get('abspos_dual_anchor', [])[:20]:
        iss.err('R-VIS-ABSPOS-DUAL-ANCHOR',
            f'slide {entry["slide_idx"]} · `{entry["selector"]}` is '
            f'`position: absolute` with BOTH `top: {entry["top"]}` AND '
            f'`bottom: {entry["bottom"]}` declared — height stretched to '
            f'{entry["actual_h"]} px; content-sized would be {entry["content_h"]} px. '
            'Classic cascade footgun: an override added `top:` without '
            'declaring `bottom: auto`, so an inherited `bottom:` from a '
            'less-specific rule is still active and the element fills the '
            'parent vertically. Fix: in the override block, add '
            '`bottom: auto` (or `top: auto`) to neutralize the inherited '
            'anchor; OR use `inset:` shorthand to redeclare all four; OR '
            'set `data-allow-dual-anchor` on the element if it is a real '
            'fill-parent overlay (rare for slide content).')

    for entry in report.get('orphan', [])[:25]:
        kind = '末行孤字 orphan' if entry['kind'] == 'orphan' else '上长下短 imbalanced'
        no_bal = '' if entry.get('balance') == 'balance' else \
            ' (该元素当前没有 text-wrap:balance)'
        iss.warn('R-VIS-ORPHAN',
            f'slide {entry["slide_idx"]} · `{entry["selector"]}` CJK 换行不平衡 '
            f'— {kind}: {entry["lines"]} 行 {entry["line_px"]}px,末行仅 '
            f'{entry["last_px"]}px (最宽行 {entry["max_px"]}px / 字号 '
            f'{entry["font_px"]}px) ("{entry["preview"]}"). 文字换行后末行只剩一两个字 '
            '或上面长下面短,投影上很碎。Fix 优先级: (1) 给元素加 '
            '`text-wrap: balance`(框架对常见标题/卡名类已默认开 — 若这里没生效,'
            '多半被更具体的选择器/另一条 !important 压住了,提级覆盖即可);'
            '(2) 容器固定宽 / 被 flex 夹窄,balance 也救不了 → 加宽容器,或 4 字以内'
            '主标签用 `white-space: nowrap` 逼单行,或把尾词(「企划」「部」等)用 '
            '`display:block` 拆成副标行;(3) 改文案让上下两行字数接近。' + no_bal)

    # ---- R-VIS-BALANCE · 视觉重心 / 留白均衡 ----
    # 三种 sub-kind: top-heavy / bottom-heavy / dead-band。Warn 级别
    # (不是 err) — 留白判断有主观成分,作者可能故意留;但默认要让作者
    # 知道这页"上空 / 下空 / 中空",大量"看着空"的反馈都在这里。
    for entry in report.get('balance', [])[:25]:
        kind = entry['kind']
        if kind == 'top-heavy':
            iss.warn('R-VIS-BALANCE',
                f'slide {entry["slide_idx"]} · `{entry["container_sel"]}` '
                f'上重下空(top-heavy): 顶部留白 {entry["top_gap"]}px,'
                f'底部留白 {entry["bottom_gap"]}px (容器高 {entry["body_height"]}px) '
                '— 内容堆在顶部,下半页大块空白。Fix: (1) 容器加 '
                '`justify-content: center`(框架对 fixed-shape layout 已默认开 R48,'
                '但 raw / flex column 默认 flex-start,需手动加);(2) 删 `flex: 1` 让'
                '内容随高度伸展的情况,改成 content-sized + center;(3) 内容确实太少 → '
                '加 supporting 元素(KPI / pullquote / case ref)填重心。Per-slide '
                'opt-out: 在 .slide 加 `data-allow-imbalance` 标记为故意。')
        elif kind == 'bottom-heavy':
            iss.warn('R-VIS-BALANCE',
                f'slide {entry["slide_idx"]} · `{entry["container_sel"]}` '
                f'下重上空(bottom-heavy): 顶部留白 {entry["top_gap"]}px,'
                f'底部留白 {entry["bottom_gap"]}px (容器高 {entry["body_height"]}px) '
                '— 内容沉底,上半页大块空白。Fix: 容器 `justify-content: center` '
                '或 `align-content: center`;或检查是否有 `margin-top: auto` 把'
                '内容硬推到底部(BF9 反模式)。')
        else:  # dead-band
            iss.warn('R-VIS-BALANCE',
                f'slide {entry["slide_idx"]} · `{entry["container_sel"]}` '
                f'中间留白 {entry["gap_px"]}px(dead-band)— `{entry["between_a"]}` '
                f'和 `{entry["between_b"]}` 之间有一条 >140px 的空带,'
                '页面被切成两半。Fix: (1) 容器去掉 `flex: 1` / `justify-content: '
                'space-between`(BF9 反模式经常制造这种空白);(2) 缩小 gap;(3) '
                '在中间加一行 supporting 元素(pullquote / KPI / divider);(4) '
                '确实是设计意图(留白让 hero 呼吸)→ 加 `data-allow-imbalance`。')

    # ---- R-VIS-SLACK-FLEX · flex:1 子容器撑出内部空白 ----
    # R-VIS-BALANCE 看的是 body container 顶级 children 之间的 sibling gap;
    # 这条补的是另一类:`flex:1` 子容器抢光剩余空间后,内部 justify-content
    # 把空白分到子容器顶/底,导致最后一个 grandchild 离子容器边距远 →
    # sibling 看上去"远"。典型踩坑:`.arch3 { flex:1; justify-content: center }`
    # 内部撑出 200px slack。Warn 级(留白判断主观,作者可能有意)。
    for entry in report.get('slack_flex', [])[:20]:
        ts, bs = entry['top_slack'], entry['bottom_slack']
        if ts >= 80 and bs >= 80:
            kind = f'容器内部居中撑空(top {ts}px / bottom {bs}px)'
        elif ts >= 80:
            kind = f'容器内部上方撑空 {ts}px'
        else:
            kind = f'容器内部下方撑空 {bs}px(最后一个子元素到容器底距离过大)'
        iss.warn('R-VIS-SLACK-FLEX',
            f'slide {entry["slide_idx"]} · `{entry["child_sel"]}` '
            f'(flex-grow {entry["flex_grow"]}, 高 {entry["child_height"]}px, '
            f'内容 {entry["content_height"]}px, justify-content: '
            f'{entry["justify"]}) — {kind}。父 `{entry["container_sel"]}`。'
            '原因:`flex:1` 把剩余空间给了该子容器,但内部内容比拿到的空间小,'
            '`justify-content` 把空白分到容器内部,视觉上跟相邻 sibling 间距'
            '异常大。Fix 选一个: (1) 去掉子容器的 `flex: 1`(改成 content-sized '
            '+ 父容器 `justify-content: center` 居中整组内容,这是最常见的修法);'
            '(2) 把子容器 `justify-content` 改成 `flex-start` / `flex-end` 让'
            '内容靠一端;(3) 内容确实太少 → 加 supporting 元素填重心;(4) '
            '确实是设计意图(故意让 hero 元素被推到某一端)→ 在子容器或父容器加 '
            '`data-allow-flex-slack` 跳过审计。')

    # ---- R-VIS-CARD-MIN-HEIGHT-SPARSE · min-height 撑空 + 没 space-between ----
    # 作者用 `min-height` 撑 card 视觉体量,但 default `justify-content: flex-start`
    # 让内容堆顶,卡底大量空白 — 视觉上"卡片看着空"。正解:加 `class="fs-card-fill"`
    # (= space-between),N child 均布。Warn 级(留白判断主观,作者可能故意)。
    # 触发 2026-05-29 P15 调试:这 pattern 应该是 default 提醒,不靠作者记得。
    for entry in report.get('card_min_height_sparse', [])[:15]:
        iss.warn('R-VIS-CARD-MIN-HEIGHT-SPARSE',
            f'slide {entry["slide_idx"]} · `{entry["selector"]}` '
            f'(min-height {entry["min_height"]}px, 实际 {entry["client_h"]}px, '
            f'内容延展 {entry["content_extent"]}px (first→last bbox), '
            f'可用 {entry["usable_h"]}px (减 padding), 真 slack {entry["slack"]}px, '
            f'{entry["kid_count"]} children, justify-content: {entry["justify"]}) '
            f'— 作者设了 min-height 撑卡片体量,但内容堆顶,卡底大量空白。'
            'Fix: (1) 给该元素加 `class="fs-card-fill"`(框架 utility · 内部 '
            '`justify-content: space-between !important` · {N children 跨高度均布}'
            ');(2) 或缩小 min-height 到自然内容高度附近(slack < 30px · 让 '
            'flex-start 看不出来);(3) 确实是设计意图(顶部 hero + 底部留白)→ '
            '给元素加 `data-allow-min-height-sparse` 跳过审计。'
            '完整 pattern 见 `feishu-deck.css` 的 `.fs-card-fill` 注释。')

    # ---- R-FOCAL-CHECK · 视觉焦点是否清晰 ----
    # 唯一被诊断的失败模式:≥3 个元素共享最大字号 AND 无任何元素声明 hero。
    # 通常说明作者把 title + N 个 card title 全做到 48,眼睛没有第一落点。
    for entry in report.get('focal', [])[:20]:
        iss.warn('R-FOCAL-CHECK',
            f'slide {entry["slide_idx"]} (layout `{entry["layout"]}`) · '
            f'{entry["tied_count"]} 个元素共享最大字号 {entry["top_size_px"]}px '
            f'(e.g. {", ".join("`"+s+"`" for s in entry["examples"][:3])}…)'
            f'{"…" if entry["tied_count"] > 3 else ""},视觉焦点模糊 — '
            '观众第一眼不知道该看哪个。Fix 选一个: (1) 把 N-1 个降一级'
            '(48→28 或 28→24,按 Card density 规则:≤4 卡 = 48,5-6 卡 = 28,'
            '≥7 卡 = 28);(2) 给真正的 hero 元素加 `class="is-hero"` 或 '
            '`data-focal`(明示该元素是焦点,审计放行);(3) 用 brand color / '
            'border / 不同 padding 把 hero 元素从平行结构里抽出来;(4) 这页确实'
            '是 overview / 平权矩阵(N 项等大就是设计本身)→ 在 .slide 加 '
            '`data-allow-no-focal` 跳过审计。')

    # (screenshot archival happens inside the Playwright block above; no
    # post-step needed. The previous `if 'shots_dir' in dir(): pass` was
    # dead: `dir()` inside a function returns local names, not what one
    # might assume, and the branch had `pass` anyway. Removed 2026-05-18.)


# ---- JS payload that runs INSIDE the headless browser ----
# Returns: {overflow: [...], tier: [...], hier: [...], align: [...]}
# Loaded from disk so we get JS syntax highlight, `node --check`
# in preflight.sh, and line-mapped stack traces. Extracted
# 2026-05-24 (was a 626-line r"""...""" string embedded here).
#
# Loaded LAZILY (on first visual-audit run), not at import time, so that
# importing this module for static-only checks never touches the file.
# check-only.py does `import validate` and must keep working even if
# visual-audit.js is absent; a read failure here degrades to the existing
# R-VISUAL warning inside run_visual_audits() rather than crashing import.
_VISUAL_AUDIT_JS_CACHE = None


def _visual_audit_js():
    global _VISUAL_AUDIT_JS_CACHE
    if _VISUAL_AUDIT_JS_CACHE is None:
        _VISUAL_AUDIT_JS_CACHE = (
            Path(__file__).resolve().parent / 'visual-audit.js'
        ).read_text()
    return _VISUAL_AUDIT_JS_CACHE



# ---------------------------------------------------------------------------
#  Design-quality nudge (2026-05-29) — advisory, never blocks
# ---------------------------------------------------------------------------

# Layouts that are sparse / imagery-by-nature by design — excluded from the
# visual-richness nudge so it never false-fires on intentionally-minimal pages.
_SPARSE_BY_DESIGN = HERO_TITLE_LAYOUTS | {
    'agenda', 'table', 'replica', 'iframe-embed', 'raw',
}


def audit_visual_richness(slides: list[str], iss: Issues):
    """R-VIS-NO-IMAGERY (warn_soft · ADVISORY): nudge when a deck reads
    visually FLAT — most CONTENT slides carry zero imagery (no icon / inline
    <svg> / <img> / background-image). This is the #1 quality-benchmark gap
    ('全是彩边文字卡 · 零图标/图像 → richness 卡在 ~3.5/5').

    ADVISORY ONLY — never an error, even under --strict (warn_soft). Richness
    is a DESIGN-PHASE judgment: the author/LLM decides per slide whether an
    icon / photo / illustration / bespoke layout:raw page fits. This rule does
    NOT hardcode a requirement; it just reminds when a whole deck is bare text.
    Sparse-by-design layouts (cover/section/end/quote/image-text/agenda/table/
    replica/iframe/raw) are skipped so the nudge targets real flatness only."""
    content, flat = [], []
    for i, fr in enumerate(slides, 1):
        layout = (slide_attr(fr, 'layout') or '').strip()
        if layout in _SPARSE_BY_DESIGN:
            continue
        content.append(i)
        if not ('<svg' in fr or '<img' in fr or 'background-image' in fr):
            flat.append((i, layout))
    if len(content) >= 3 and len(flat) / len(content) >= 0.6:
        where = ', '.join(f'#{i}({l})' for i, l in flat[:8])
        iss.warn_soft(
            'R-VIS-NO-IMAGERY',
            f'{len(flat)}/{len(content)} content slides have zero imagery '
            f'(no icon/svg/image/background) — deck reads visually flat & samey. '
            f'Where it fits, consider an icon (ICON_LIB names) / photo / '
            f'illustration / bespoke layout:raw page. Flat: {where}. '
            f'[advisory · richness is a design-phase call · never blocks]')


def inline_linked(html_text, base_dir):
    """Inline <link rel=stylesheet> / <script src> into the HTML so audits can
    see framework CSS/JS content. External (http/https/data:) refs and missing
    files are left untouched. Shared by main() here and check-only.py — was
    copy-pasted in both, unified per F-14."""
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


def main():
    p = argparse.ArgumentParser(description='feishu-deck-h5 self-check')
    p.add_argument('html', help='Path to the assembled deck HTML file')
    p.add_argument('--strict', action='store_true',
                   help='Promote warnings to errors')
    p.add_argument('--visual', action=argparse.BooleanOptionalAction,
                   default=True,
                   help='Run the Playwright-based renderer-side audits: '
                        'R-OVERFLOW (canvas overflow — catches the P05-style '
                        '"column bleeds into legend" bug that static CSS '
                        'analysis cannot), R-VIS-TIER (computed fontSize on '
                        '4-tier ladder), R-VIS-HIER (meta ≤ body in each '
                        'card), R-VIS-ALIGN (grid children equal height). '
                        'DEFAULT: on (~1-5s extra per deck). Use --no-visual '
                        'to skip (e.g. CI without Chromium). Gracefully '
                        'skips when playwright is not installed.')
    p.add_argument('--screenshots', action='store_true',
                   help='In addition to --visual checks, archive PNG '
                        'screenshots of each slide to '
                        '<deck-stem>-previews/sNN.png. Useful for visual '
                        'baseline / human review; not needed for CI.')
    p.add_argument('--json', action='store_true',
                   help='Emit a stable JSON blob to stdout instead of the '
                        'human-readable report. Format: '
                        '{"deck": <path>, "slides": <N>, "errors": [...], '
                        '"warnings": [...]} where each issue is '
                        '{"code", "msg", "slide" (parsed if present), '
                        '"severity"}. Use this when downstream tools '
                        '(run-regression.py, analyze-prompts.py) consume '
                        'validator output — parsing the human report via '
                        'regex is brittle to format tweaks.')
    args = p.parse_args()
    if args.screenshots and not args.visual:
        args.visual = True   # --screenshots implies --visual

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
    html = inline_linked(html, path.parent)  # module-level helper (F-14)

    slides = extract_slides(html)

    iss = Issues()
    audit_dom_integrity(html, iss)
    audit_lift_style_lost(html, iss)
    # All audits emit warn/err at their inherent severity. The global
    # `--strict` flag promotes ALL warnings to errors after the audits
    # complete (see end of main()) — per-audit `strict` branches were
    # redundant and removed 2026-05-18.
    audit_structure(slides, iss)
    audit_titles_one_line(slides, iss)
    audit_brand_chrome(slides, iss)
    audit_copy_rules(html, iss)
    audit_font_sizes(html, iss)
    audit_type_ladder(html, iss)
    audit_undefined_css_vars(html, iss)
    audit_white_text(html, iss)
    audit_no_drop_shadows(html, iss)
    audit_data_decor(slides, iss)
    audit_hex_palette(html, iss)
    audit_bullet_dash(html, iss)
    audit_runtime_chrome(html, iss, path)
    audit_centering_pattern(html, iss)
    audit_layout_integrity(html, iss)
    audit_default_centering(html, iss)
    audit_empty_header_zone(html, iss)
    audit_hierarchy(html, iss)
    audit_variant_discipline(html, iss)
    audit_ui_mocks_are_html(slides, iss)
    audit_no_cyan_accent(slides, iss)
    audit_header_minimal(slides, iss)
    audit_slide_keys(slides, iss)
    audit_language_policy(html, slides, iss)
    audit_list_echo(slides, iss)
    audit_visual_richness(slides, iss)
    audit_perf(html, iss)
    audit_text_ids(html, path, iss)
    audit_feedback_md(path, iss)

    if args.visual:
        run_visual_audits(path, iss, want_screenshots=args.screenshots)

    if args.strict:
        # Promote regular warnings to errors. SOFT warnings (R-FEEDBACK,
        # R-VIS-ALIGN, etc.) stay as warnings — they are editorial
        # advisories that should never fail CI.
        iss.errors.extend(iss.warnings)
        iss.warnings = []

    # Soft warnings render alongside regular warnings, no separate header.
    all_warnings = iss.warnings + iss.soft_warnings

    if args.json:
        # Stable machine-readable output. Downstream tools (run-regression,
        # analyze-prompts) read this instead of regex-parsing the human
        # narrative. Slide ordinal parsed from msg when present ("slide N ·")
        # — same convention every audit emit follows. selector_hint is best-
        # effort: backtick-quoted token inside the msg (most audits include).
        _SLIDE_IN_MSG = re.compile(r'slide\s+(\d+)\b')
        _BACKTICK_IN_MSG = re.compile(r'`([^`]+)`')
        def _entry(code, msg, severity):
            s = _SLIDE_IN_MSG.search(msg)
            sel = _BACKTICK_IN_MSG.search(msg)
            return {
                'code': code,
                'severity': severity,
                'msg': msg,
                'slide': int(s.group(1)) if s else None,
                'selector_hint': sel.group(1) if sel else None,
            }
        payload = {
            'deck': str(path),
            'slides': len(slides),
            'errors': [_entry(c, m, 'error') for c, m in iss.errors],
            'warnings': (
                [_entry(c, m, 'warning') for c, m in iss.warnings]
                + [_entry(c, m, 'warning_soft') for c, m in iss.soft_warnings]
            ),
            'pass': not iss.errors,
        }
        import json as _json
        print(_json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if not iss.errors else 1

    print(f'feishu-deck-h5 validator  ·  {path.name}')
    print(f'  slides: {len(slides)}')
    print(f'  errors:   {len(iss.errors)}')
    print(f'  warnings: {len(all_warnings)}')

    if iss.errors:
        print('\nERRORS')
        for code, msg in iss.errors:
            print(f'  ✗ [{code}] {msg}')
    if all_warnings:
        print('\nWARNINGS')
        for code, msg in all_warnings:
            print(f'  ! [{code}] {msg}')

    if iss.errors:
        print('\nFAIL — fix the errors above before delivering.')
        return 1
    print('\nPASS — all programmatic checks satisfied.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
