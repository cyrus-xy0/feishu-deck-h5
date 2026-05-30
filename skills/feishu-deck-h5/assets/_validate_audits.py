#!/usr/bin/env python3
"""
feishu-deck-h5  ·  validator AUDIT FUNCTIONS (_validate_audits)

The 32 static `audit_*` functions plus their audit-private helpers
(check_* layout-integrity probes, _lifted_slide_keys, _parse_texts_md_ids,
the PERF / TEXT_ID constants). Middle layer of the DAG: imports the shared
kernel, imports nothing from validate.py.
"""

from __future__ import annotations
import functools, re, sys, argparse
from collections import Counter
from pathlib import Path

from _validate_common import *
# Star-import skips underscore-prefixed names — re-import the kernel's private
# symbols (constants / compiled regexes / helpers) the audits reference here.
from _validate_common import (
    _FS_TOKEN_FALLBACK, _load_fs_tokens, _FS_TOKENS,
    _SLIDE_FRAME_OPEN_RE,
    _STYLE_BLOCK_RE, _iter_style_blocks,
    _RULE_WITH_COMMENTS_RE,
    _DECK_VW, _DECK_VH, _MQ_FEATURE_RE, _media_query_matches,
    _strip_nested_at_rules,
    _BOX_SHADOW_GLOW_RING_RE, _BOX_SHADOW_INSET_RE,
    _BODY_CLASS_RE, _CHROME_CLASS_RE,
    _CJK_RE, _HTML_LEAF_TAGS, _HTML_VOID_TAGS, _HTML_SKIP_CONTAINERS,
    _walk_text_leaves,
    _CHART_SCAFFOLD_CLASSES, _is_chart_scaffold_class,
    _LAYOUT_ONLY_PARENT_TAGS,
)


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

