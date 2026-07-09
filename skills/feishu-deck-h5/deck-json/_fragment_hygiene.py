"""Sanitize lifted raw-slide fragments before they enter deck.json.

The renderer scopes `slide.custom_css` to the slide key, but a `<style>` left in
raw `data.html` is ordinary global CSS. Cross-deck lift/paste must therefore
converge embedded author CSS into `custom_css` and remove executable markup from
foreign fragments before the page is rendered inside a target deck.
"""
from __future__ import annotations

import re

_STYLE_RE = re.compile(r'<style(?P<attrs>[^>]*)>(?P<body>.*?)</style\s*>',
                       re.S | re.I)
_SCRIPT_RE = re.compile(r'<script(?P<attrs>[^>]*)>(?P<body>.*?)</script\s*>',
                        re.S | re.I)
_TAG_RE = re.compile(r'<[^<>]+>')
_ON_ATTR_RE = re.compile(
    r'\s+on[a-zA-Z]+\s*=\s*(?:"[^"]*"|\'[^\']*\'|[^\s>]+)',
    re.S,
)
_FRAMEWORK_SRC_RE = re.compile(
    r'(?:^|/)(?:feishu-deck\.js|deck-edit-mode\.js|deck-present-mode\.js|'
    r'deck-present\.js)(?:[?#]|$)',
    re.I,
)


def _attr(attrs: str, name: str) -> str:
    m = re.search(
        rf'\b{name}\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'>]+))',
        attrs or "",
        re.I,
    )
    return (m.group(1) or m.group(2) or m.group(3) or "") if m else ""


def _is_framework_style(attrs: str) -> bool:
    return _attr(attrs, "data-source").lower() == "framework"


def _is_executable_script(attrs: str) -> bool:
    if _attr(attrs, "data-source").lower() == "framework":
        return False
    src = _attr(attrs, "src").strip()
    if src and _FRAMEWORK_SRC_RE.search(src):
        return False
    typ = _attr(attrs, "type").strip().lower()
    if not typ:
        return True
    if typ == "module":
        return True
    if typ in {"text/jsx", "application/ecmascript"}:
        return True
    if re.search(r'(?:^|/)(?:javascript|ecmascript|babel|jsx|js|mjs)$', typ):
        return True
    return False


def consolidate_author_styles(html: str) -> tuple[str, str, int]:
    """Move non-framework `<style>` bodies out of `html`.

    Returns `(stripped_html, css, count)`. A framework-marked style block is left
    in place because it is not authored page CSS.
    """
    if not isinstance(html, str) or "<style" not in html.lower():
        return html or "", "", 0
    bodies: list[str] = []
    count = 0

    def take(match: re.Match) -> str:
        nonlocal count
        attrs = match.group("attrs") or ""
        if _is_framework_style(attrs):
            return match.group(0)
        count += 1
        body = (match.group("body") or "").strip()
        if body:
            bodies.append(body)
        return ""

    stripped = _STYLE_RE.sub(take, html)
    stripped = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", stripped)
    return stripped, "\n".join(bodies), count


def strip_executable_markup(html: str) -> tuple[str, int, int]:
    """Remove executable script blocks and inline `on*=` handlers.

    Non-executable `<script type="application/json">` / `text/plain` islands and
    framework-marked scripts are preserved. Returns
    `(clean_html, script_count, handler_count)`.
    """
    if not isinstance(html, str) or not html:
        return "", 0, 0
    script_count = 0

    def strip_script(match: re.Match) -> str:
        nonlocal script_count
        attrs = match.group("attrs") or ""
        if not _is_executable_script(attrs):
            return match.group(0)
        script_count += 1
        return ""

    out = _SCRIPT_RE.sub(strip_script, html)
    handler_count = 0

    def strip_handlers(match: re.Match) -> str:
        nonlocal handler_count
        tag = match.group(0)
        if tag.lower().startswith(("<script", "<style")):
            return tag
        new_tag, n = _ON_ATTR_RE.subn("", tag)
        handler_count += n
        return new_tag

    out = _TAG_RE.sub(strip_handlers, out)
    return out, script_count, handler_count


def hygienize_lifted_raw_html(html: str) -> tuple[str, str, dict]:
    """Return `(clean_html, css_to_custom_css, report)` for a lifted raw slide."""
    clean, css, style_count = consolidate_author_styles(html)
    clean, scripts, handlers = strip_executable_markup(clean)
    report = {
        "styles_consolidated": style_count,
        "scripts_stripped": scripts,
        "handlers_stripped": handlers,
    }
    return clean, css, report
