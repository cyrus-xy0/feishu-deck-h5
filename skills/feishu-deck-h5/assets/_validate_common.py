#!/usr/bin/env python3
"""
feishu-deck-h5  ·  validator SHARED KERNEL (_validate_common)

The shared KERNEL of the validator. Holds the `Issues` collector, slide
extraction, the DOM text-leaf walker, the type-token ladder, and ALL the
module-level constants / compiled regexes / helpers shared across the validator
adapter (validate.py) and the runner byte/source checks (run-audits.py).

UNIFY-VALIDATE-ARCH step 4: the old `_validate_audits` audit module was retired
(its rules moved to the unified engine). This module imports nothing from
validate.py — it stays the bottom of the DAG (_validate_common ← validate.py /
run-audits.py).
"""

from __future__ import annotations
import functools, re, sys, argparse
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
#  规范 thresholds (hard floors)
# ---------------------------------------------------------------------------

# F-02 · single source of truth for the 4-tier font ladder. Derive it from the
# framework CSS :root --fs-* tokens (the values that actually RENDER) instead of
# re-typing 16/24/28/48 here AND in feishu-deck.css AND in SKILL.md. The parity
# test (tests/test_type_tokens_ssot.py) fails if CSS drifts from the fallback
# below; the fallback keeps the validator working if the CSS can't be read.
_FS_TOKEN_FALLBACK = {'--fs-foot': 16, '--fs-body': 24, '--fs-sub': 28, '--fs-title': 48}


def _load_fs_tokens() -> dict:
    """Parse `--fs-{title,sub,body,foot}: Npx` from the framework CSS :root."""
    css = Path(__file__).resolve().parent / 'feishu-deck.css'
    try:
        text = css.read_text(encoding='utf-8')
    except OSError:
        return dict(_FS_TOKEN_FALLBACK)
    found = {f'--fs-{n}': int(px)
             for n, px in re.findall(r'--fs-(title|sub|body|foot)\s*:\s*(\d+)px', text)}
    # require all four; otherwise fall back (defensive against a future rename)
    return found if _FS_TOKEN_FALLBACK.keys() <= found.keys() else dict(_FS_TOKEN_FALLBACK)


_FS_TOKENS = _load_fs_tokens()

FLOOR_BODY_PX   = _FS_TOKENS['--fs-body']   # body text on content pages (4-tier rung 3)
FLOOR_CHROME_PX = _FS_TOKENS['--fs-foot']   # corner metadata / footnote / pill / tag (rung 4)
# FLOOR_HEADER_PX / FLOOR_TABLE_TH_PX / FLOOR_STATS_TREND_PX were defined but
# never read (R20 enforces the 4-tier ladder directly). Removed 2026-05-18.

# Brand palette — all hex values inside slide markup must be from this set.
ALLOWED_HEX = {
    'fff', 'ffffff', '000', '000000',
    '3c7fff', '24c3ff', '33d6c0', '5c3ffb', '9f6ff1', 'fe7f00',
    '080c18', '0f1a4a', '060b22', '1a2256', '050817', '04060f', '0a1230', '1b1f3a',
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
# F-13 · This is NOT the same set as visual-audit.js HERO_LAYOUTS — do not
# "sync" them. HERO_TITLE_LAYOUTS = layouts whose page TITLE/header is
# hero/flexible (multi-line title allowed in R13, header-minimal exempt in
# R56). big-stat is intentionally ABSENT: it has no hero title (only .num /
# .copy). The JS HERO_LAYOUTS answers a different question — "is the WHOLE
# slide a hero zone where hero font sizes are allowed anywhere" — and correctly
# includes big-stat.
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
                       under --strict (e.g. R-VIS-NO-IMAGERY "deck reads
                       flat", R-SELF-CONTAINED "head CSS not co-located").
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


# F-11 · @media handling. The previous approach DELETED every @-rule before
# flat-rule scanning, which hid real violations (sub-floor font / off-palette
# hex / drop shadow) written INSIDE @media. But blindly auditing all @media
# would false-positive on legitimate responsive overrides (e.g. a smaller font
# in `@media (max-width:768px)`) that never render — the deck is a FIXED
# 1920×1080 canvas. So resolve @media against that viewport: an @media that
# WOULD be active is unwrapped (its inner rules join the flat scan and get
# audited); one that wouldn't (responsive mobile / print) is dropped, as before.
# Other at-rules (@keyframes/@font-face/@supports/@page) carry no auditable
# selector rules and are dropped unchanged.
_DECK_VW, _DECK_VH = 1920, 1080
_MQ_FEATURE_RE = re.compile(r'\(\s*(min|max)-(width|height)\s*:\s*(\d+)\s*px\s*\)')


def _media_query_matches(query: str, vw: int = _DECK_VW, vh: int = _DECK_VH) -> bool:
    """Would this @media query be active at the deck's fixed viewport? Unknown /
    unparseable features default to True (audit it — don't hide a violation)."""
    q = (query or '').strip().lower()
    if not q:
        return True
    for branch in q.split(','):                 # comma = OR
        b = branch.strip()
        if not b:
            return True
        active = True
        for part in re.split(r'\band\b', b):    # 'and' = AND
            p = part.strip()
            if not p or p in ('all', 'screen', 'only screen', 'only all'):
                continue
            if p in ('print', 'speech') or p.startswith('only print'):
                active = False; break
            if p.startswith('not '):
                active = ('print' in p or 'speech' in p)  # not-print → screen
                break
            m = _MQ_FEATURE_RE.search(p)
            if m:
                kind, dim, val = m.group(1), m.group(2), int(m.group(3))
                cur = vw if dim == 'width' else vh
                if (kind == 'min' and cur < val) or (kind == 'max' and cur > val):
                    active = False; break
            # unknown feature (orientation / resolution / prefers-*) → keep active
        if active:
            return True
    return False


@functools.lru_cache(maxsize=64)
def _strip_nested_at_rules(css: str) -> str:
    """Resolve nested @-rules before flat `selector { block }` scanning (F-11).
    @media that would be active at the deck's 1920×1080 viewport is UNWRAPPED so
    its inner rules get audited; inactive @media + @keyframes/@font-face/
    @supports/@page are dropped. Balanced-brace aware (recurses into nested
    @media), unlike the old regex which couldn't. Name kept for its 9 callers.
    Cached: the same `<style>` block is scanned by ~9 audits per run; LRU keyed
    on the raw CSS makes the resolve run once per unique input.
    """
    out = []
    n = len(css)
    i = 0
    while True:
        at = css.find('@', i)
        if at == -1:
            out.append(css[i:]); break
        out.append(css[i:at])
        brace = css.find('{', at)
        if brace == -1:                          # malformed @-rule (no body)
            out.append(css[at:]); break
        prelude = css[at:brace]
        depth, j = 0, brace
        while j < n:                             # find the matching close brace
            c = css[j]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = css[brace + 1:j]
        mk = re.match(r'@([a-zA-Z-]+)\s*(.*)', prelude, re.S)
        kind = mk.group(1).lower() if mk else ''
        cond = mk.group(2) if mk else ''
        if kind == 'media' and _media_query_matches(cond):
            out.append(_strip_nested_at_rules(body))   # unwrap (+ recurse nesting)
        # else: drop (inactive @media, @keyframes/@font-face/@supports/@page…)
        i = j + 1
    return ''.join(out)


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


# 4-tier strict (2026-05-16) — CONTENT pages use ONLY these four {16,24,28,48}.
# Derived from the framework CSS --fs-* tokens (single source, F-02), not
# re-typed here. Mockup-internal text opts out via /* allow:typescale */; hero
# exceptions (cover 100, section 88/160, big-stat 132+, quote 88+) live OUTSIDE
# this ladder and must be tagged /* allow:typescale */ in per-page <style>
# blocks. Framework CSS itself is exempt (R20 only audits [data-page=...] rules).
TYPE_LADDER_PX = set(_FS_TOKENS.values())


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


# Tags that are STRUCTURAL containers (rows / list-bodies / table-bodies)
# rather than semantic content blocks. Their direct children are EXPECTED
# to be sibling cells / items, not translation pairs.
_LAYOUT_ONLY_PARENT_TAGS = {
    'tr', 'table', 'thead', 'tbody', 'tfoot',
    'ul', 'ol', 'dl', 'figure', 'select', 'fieldset',
}
