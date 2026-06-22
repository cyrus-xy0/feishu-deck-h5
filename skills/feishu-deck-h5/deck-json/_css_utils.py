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

def _match_brace(css: str, open_idx: int) -> int:
    """Index just AFTER the `}` matching the `{` at `open_idx`, ignoring braces
    inside string literals (`content: "}"`) and `/* comments */` — a naive
    brace counter mis-balanced on either and split a rule mid-body."""
    n = len(css)
    depth, k, instr = 1, open_idx + 1, ''
    while k < n and depth > 0:
        c = css[k]
        if instr:
            if c == instr and css[k - 1] != '\\':
                instr = ''
            k += 1
            continue
        if c in '"\'':
            instr = c
        elif css[k:k + 2] == '/*':
            end = css.find('*/', k + 2)
            k = end + 2 if end != -1 else n
            continue
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        k += 1
    return k


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
            # @-rule with body — scan balanced braces (string/comment aware)
            i = _match_brace(css, brace)
            continue
        # Regular rule: selector { body }
        brace = css.find('{', i)
        if brace == -1:
            break
        selector = css[i:brace].strip()
        k = _match_brace(css, brace)
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
            # block @-rule — find matching close brace (string/comment aware)
            k = _match_brace(css, brace)
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
        k = _match_brace(css, brace)
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


# ---------------------------------------------------------------------------
# F-364 · slide-root background -> frame promotion (letterbox 黑边 root cure)
# ---------------------------------------------------------------------------
#
# THE BUG. A full-bleed layout (raw / iframe-embed / canvas) whose custom_css
# paints a background on the SLIDE ROOT -- `.slide { background: <gradient> }`
# -- silently regrows the letterbox seam F-318 was built to remove.
# render-deck scopes that selector to `.slide[data-slide-key="K"]...`
# (specificity 0,4,0), which TIES F-318's `.slide-frame > .slide` zeroing rule
# (also 0,4,0); the co-located <style> is emitted AFTER the framework sheet, so
# source-order breaks the tie in the author's favour -> F-318 is defeated. The
# slide then paints its bg at the 16:9 crop while the frame paints content-bg at
# the VIEWPORT crop, and the two disagree at the slide<->letterbox boundary
# ("标题上方有黑条"). markBleedPanels (the runtime seam-fix) can't catch it
# either -- it scans slide DESCENDANTS (querySelectorAll('*')), never the root.
#
# THE CURE. Do at RENDER time exactly what feishu-deck.css's own guidance
# (~L238: "a bespoke full-bleed background sets it on `.slide-frame` via
# custom_css") says: hoist the slide-root background onto the FRAME for present
# mode (one layer fills letterbox + slide -> no seam) and keep it on the slide
# for scroll mode (no letterbox there; present forces the slide transparent via
# F-318). The author keeps writing the obvious `.slide { background: ... }`; the
# renderer makes it correct. Both emitted selectors carry `[data-slide-key=]`
# so the later scope_selectors() pass leaves them verbatim, and neither targets
# the slide root, so the transform is idempotent (safe to re-run every render).

_BG_PROP_RE = re.compile(r'^background(-[a-z-]+)?$')
_BG_RESET_VALUES = {"none", "transparent", "initial", "inherit", "unset",
                    "revert", ""}


def _targets_slide_root(part: str) -> bool:
    """True iff this single selector's SUBJECT (rightmost compound) is the slide
    root -- `.slide`, `.slide[...]`, `.slide:has(...)`, `&[...]` -- i.e. a
    background here paints the whole slide. False for `.slide-frame`,
    `.slide .card` (descendant subject), `.slideshow`, bare descendants."""
    p = part.strip()
    if not p:
        return False
    if p.startswith("&"):
        rest = p[1:]
    elif re.match(r'\.slide(?![\w-])', p):
        rest = p[len(".slide"):]
    else:
        return False
    # rest may carry attribute/pseudo qualifiers on the SAME compound; a
    # top-level combinator (space / > / + / ~) means the subject is a
    # descendant, not the root. Parens (:has(...)/:is(...)) are transparent.
    depth = 0
    for ch in rest:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif depth == 0 and ch in " \t\r\n>+~":
            return False
    return True


def _split_decls(body: str) -> list[str]:
    """Split a declaration block on top-level `;` (paren- and comment-aware)."""
    decls, depth, buf = [], 0, []
    i, n = 0, len(body)
    while i < n:
        if body[i:i + 2] == "/*":
            end = body.find("*/", i + 2)
            end = (end + 2) if end != -1 else n
            buf.append(body[i:end])
            i = end
            continue
        c = body[i]
        if c in "([":
            depth += 1
        elif c in ")]":
            depth = max(0, depth - 1)
        if c == ";" and depth == 0:
            decls.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    tail = "".join(buf)
    if tail.strip():
        decls.append(tail)
    return decls


def _decl_prop(decl: str) -> str:
    d = re.sub(r'/\*[\s\S]*?\*/', "", decl).strip()
    if ":" not in d:
        return ""
    return d.split(":", 1)[0].strip().lower()


def _is_bg_decl(decl: str) -> bool:
    return bool(_BG_PROP_RE.match(_decl_prop(decl)))


def _bg_all_reset(bg_decls: list[str]) -> bool:
    """True if every background declaration is a no-op reset (none/transparent/
    ...) -- nothing worth hoisting to the frame."""
    for d in bg_decls:
        d2 = re.sub(r'/\*[\s\S]*?\*/', "", d)
        val = d2.split(":", 1)[1] if ":" in d2 else ""
        val = val.replace("!important", "").strip().rstrip(";").strip().lower()
        if val not in _BG_RESET_VALUES:
            return False
    return True


def _join_decls(decls: list[str]) -> str:
    out = []
    for d in decls:
        t = d.strip()
        if t:
            out.append(t if t.endswith((";", "*/")) else t + ";")
    return ("\n  " + "\n  ".join(out) + "\n") if out else ""


def promote_root_bg_to_frame(css: str, slide_key: str) -> str:
    """Hoist any slide-root `background*` declaration onto the .slide-frame for
    present mode (+ keep it on the slide for scroll). See the block comment
    above. Call BEFORE scope_selectors(), and ONLY for full-bleed layouts
    (raw / iframe-embed / canvas) -- other layouts have no letterbox seam.
    Top-level rules only; @media/@keyframes bodies pass through verbatim."""
    if not css or not css.strip():
        return css
    frame_sel = (f'.deck[data-mode="present"] .slide-frame'
                 f':has(> .slide[data-slide-key="{slide_key}"])')
    scroll_sel = f'.deck[data-mode="scroll"] .slide[data-slide-key="{slide_key}"]'
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
        # comment -> verbatim
        if css[i:i + 2] == "/*":
            k = css.find("*/", i + 2)
            k = (k + 2) if k != -1 else n
            out.append(css[i:k])
            i = k
            continue
        # @-rule (statement or block) -> verbatim
        if css[i] == "@":
            brace = css.find("{", i)
            semi = css.find(";", i)
            if brace == -1 or (semi != -1 and semi < brace):
                end = (semi + 1) if semi != -1 else n
                out.append(css[i:end])
                i = end
                continue
            k = _match_brace(css, brace)
            out.append(css[i:k])
            i = k
            continue
        # regular rule: selector { body }
        brace = css.find("{", i)
        if brace == -1:
            out.append(css[i:])
            break
        rule_start = i
        selector = css[i:brace]
        k = _match_brace(css, brace)
        body = css[brace + 1:k - 1]
        i = k
        parts = _split_top_level_commas(selector)
        root_parts = [p for p in parts if _targets_slide_root(p)]
        if not root_parts:
            out.append(css[rule_start:k])          # byte-identical passthrough
            continue
        decls = _split_decls(body)
        bg_decls = [d for d in decls if _is_bg_decl(d)]
        if not bg_decls or _bg_all_reset(bg_decls):
            out.append(css[rule_start:k])
            continue
        other_parts = [p for p in parts if not _targets_slide_root(p)]
        other_decls = [d for d in decls if not _is_bg_decl(d)]
        bg_body = _join_decls(bg_decls)
        repl: list[str] = []
        if other_parts:
            # descendant subjects paint a child, never the letterbox -> full rule kept
            repl.append(f"{', '.join(other_parts)} {{{body}}}")
        if other_decls:
            repl.append(f"{', '.join(p.strip() for p in root_parts)} "
                        f"{{{_join_decls(other_decls)}}}")
        repl.append(f"{frame_sel} {{{bg_body}}}")
        repl.append(f"{scroll_sel} {{{bg_body}}}")
        out.append("\n".join(repl))
    return "".join(out)
