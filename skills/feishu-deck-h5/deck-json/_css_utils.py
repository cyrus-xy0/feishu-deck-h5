#!/usr/bin/env python3
"""_css_utils.py — single-source CSS parsing + per-slide scoping for the
feishu-deck-h5 deck pipeline.

Why this module exists (LIFT-ARCHITECTURE step 1)
-------------------------------------------------
"Lift a page from deck A into deck B" was slow + token-expensive because a
slide's CSS dependency set was never *recorded* — it lived in the shared
3491-line feishu-deck.css and in scattered head/page `<style>` blocks, so
extracting one page meant re-deriving the whole cascade.

The fix is two-track and BOTH tracks need the same primitive: take a chunk of
author CSS and *scope every selector to one slide* so the CSS travels with the
slide and never leaks to siblings. That primitive is `scope_selectors()`.

- render-deck.py uses it to emit `slide.custom_css` as a co-located
  `<style data-slide-key=K>` block (self-contained-by-construction track).
- lift-slides.py uses `iter_css_rules()` (moved here verbatim) to tree-shake
  framework rules out of foreign decks (the legacy track).

Keeping ONE parser in ONE place (the established `_story_case_fit.py` pattern)
means the two tracks can't drift.

stdlib only. Python 3.10+.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Top-level rule iterator (moved verbatim from lift-slides.py — single source)
# ---------------------------------------------------------------------------

def iter_css_rules(css: str):
    """Yield (selector, body) for top-level CSS rules. Skips @-rules (media,
    keyframes, etc.) and comments. Doesn't handle nested rules (CSS doesn't
    have them at top level in this codebase)."""
    i, n = 0, len(css)
    while i < n:
        # Skip whitespace
        while i < n and css[i] in ' \t\n\r':
            i += 1
        if i >= n:
            break
        # Skip block comment /* ... */
        if css[i:i + 2] == '/*':
            j = css.find('*/', i + 2)
            if j == -1:
                break
            i = j + 2
            continue
        # Skip @-rule entirely (find matching close brace or ;)
        if css[i] == '@':
            brace = css.find('{', i)
            semi = css.find(';', i)
            if brace == -1 or (semi != -1 and semi < brace):
                i = (semi + 1) if semi != -1 else n
                continue
            # @-rule with body — scan balanced braces
            depth, k = 1, brace + 1
            while k < n and depth > 0:
                c = css[k]
                if c == '{':
                    depth += 1
                elif c == '}':
                    depth -= 1
                k += 1
            i = k
            continue
        # Regular rule: selector { body }
        brace = css.find('{', i)
        if brace == -1:
            break
        selector = css[i:brace].strip()
        depth, k = 1, brace + 1
        while k < n and depth > 0:
            c = css[k]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
            k += 1
        body = css[brace + 1: k - 1].strip()
        yield selector, body
        i = k


# ---------------------------------------------------------------------------
# Per-slide selector scoping
# ---------------------------------------------------------------------------

# Block @-rules whose body is itself a list of rules → recurse + scope inside,
# keep the @-wrapper. (@layer/@scope can also be statement form — handled below.)
_AT_NESTED = {"media", "supports", "container", "layer", "scope"}


def _split_top_level_commas(selector: str) -> list[str]:
    """Split a selector list on commas that are NOT inside () or []. Needed so
    `:is(.a, .b)` and `[data-x="a,b"]` don't get split mid-token."""
    parts, depth, buf = [], 0, []
    for c in selector:
        if c in "([":
            depth += 1
        elif c in ")]":
            depth = max(0, depth - 1)
        if c == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(c)
    if buf:
        parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _scope_one_selector(part: str, scope: str) -> str:
    """Scope a single (comma-free) selector to `scope`.

    Rules, in priority order:
      1. Already `[data-slide-key=...]`-scoped → leave verbatim (idempotent).
      2. Back-compat: `[data-page="NN"]` token → swap it for `scope`.
      3. Targets the slide root (`.slide`, `.slide .x`, `.slide:has(...)`) →
         replace the leading `.slide` with `scope`.
      4. Leading `&` (nesting-style) → `&` means the slide root.
      5. Bare descendant (`.card`, `h4`, `*`) → prefix with `scope `.
    """
    p = part.strip()
    if not p:
        return p
    if "[data-slide-key=" in p:
        return p
    if "[data-page" in p:
        # `[data-page=N]` is usually the FRAME-level ancestor of `.slide` (the
        # page-anim head pattern `[data-page="03"] .slide .card`). A plain token
        # swap yields `scope .slide .card` — a PHANTOM nested `.slide` that
        # matches 0 elements (scope already IS the keyed `.slide`), so a migrated
        # rule silently dies. Mirror lift-slides.extract_head_slide_rules: strip
        # selector-position comments, FUSE `[data-page=N](>) .slide` onto the
        # keyed scope, then re-anchor any remaining bare `[data-page]` token.
        # (Also handles bare `[data-page]` with no `=`.)
        p = re.sub(r'/\*[\s\S]*?\*/', ' ', p)
        p = re.sub(r'\[data-page(?:=[^\]]*)?\]\s*(?:>\s*)?\.slide(?![\w-])',
                   lambda m: scope, p)
        return re.sub(r'\[data-page(?:=[^\]]*)?\]', lambda m: scope, p)
    # `.slide` as the leading token (but NOT `.slide-frame` / `.slideshow`)
    if re.match(r'\.slide(?![\w-])', p):
        return re.sub(r'^\.slide', scope, p, count=1)
    if p.startswith("&"):
        return scope + p[1:]
    return f"{scope} {p}"


def _scope_block(css: str, scope: str) -> str:
    """Walk CSS preserving comments/whitespace; scope every regular rule's
    selector to `scope`; recurse into nested @-rules; pass keyframes/font-face
    through verbatim."""
    out: list[str] = []
    i, n = 0, len(css)
    while i < n:
        # passthrough leading whitespace
        j = i
        while j < n and css[j] in " \t\r\n":
            j += 1
        if j > i:
            out.append(css[i:j])
            i = j
        if i >= n:
            break
        # comment
        if css[i:i + 2] == "/*":
            k = css.find("*/", i + 2)
            k = (k + 2) if k != -1 else n
            out.append(css[i:k])
            i = k
            continue
        # @-rule
        if css[i] == "@":
            m = re.match(r'@([\w-]+)', css[i:])
            name = m.group(1).lower() if m else ""
            brace = css.find("{", i)
            semi = css.find(";", i)
            if brace == -1 or (semi != -1 and semi < brace):
                # statement @-rule (@import, @charset, @layer name;)
                end = (semi + 1) if semi != -1 else n
                out.append(css[i:end])
                i = end
                continue
            # block @-rule — find matching close brace
            depth, k = 1, brace + 1
            while k < n and depth > 0:
                if css[k] == "{":
                    depth += 1
                elif css[k] == "}":
                    depth -= 1
                k += 1
            if name in _AT_NESTED:
                header = css[i:brace]
                body = css[brace + 1:k - 1]
                out.append(header + "{" + _scope_block(body, scope) + "}")
            else:
                # @keyframes / @font-face / @page / @property … — verbatim
                out.append(css[i:k])
            i = k
            continue
        # regular rule: selector { body }
        brace = css.find("{", i)
        if brace == -1:
            out.append(css[i:])
            break
        selector = css[i:brace]
        depth, k = 1, brace + 1
        while k < n and depth > 0:
            if css[k] == "{":
                depth += 1
            elif css[k] == "}":
                depth -= 1
            k += 1
        body = css[brace + 1:k - 1]
        parts = _split_top_level_commas(selector)
        scoped_sel = ", ".join(_scope_one_selector(p, scope) for p in parts)
        out.append(f"{scoped_sel} {{{body}}}")
        i = k
    return "".join(out)


def scope_selectors(css: str, slide_key: str) -> str:
    """Scope every top-level selector in `css` to a single slide identified by
    `slide_key`, so the CSS is self-contained and safe to co-locate inside the
    slide / lift into another deck without leaking onto sibling slides.

    The scope prefix is `.slide[data-slide-key="KEY"]`. Authors write CSS
    WITHOUT the prefix; selectors already scoped (`[data-slide-key=]`) pass
    through unchanged, and legacy `[data-page=NN]`-prefixed selectors are
    rewritten to the slide-key scope (reorder-stable). `@media`/`@supports`/
    `@container`/`@layer{}` bodies are recursed into; `@keyframes`/`@font-face`
    are left verbatim (their names are global by design).
    """
    if not css or not css.strip():
        return ""
    scope = f'.slide[data-slide-key="{slide_key}"]'
    return _scope_block(css, scope)
