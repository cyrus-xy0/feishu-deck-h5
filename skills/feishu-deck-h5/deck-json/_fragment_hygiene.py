"""Sanitize lifted raw-slide fragments before they enter deck.json.

The renderer scopes `slide.custom_css` to the slide key, but a `<style>` left in
raw `data.html` is ordinary global CSS. Cross-deck lift/paste must therefore
converge embedded author CSS into `custom_css` and remove executable markup from
foreign fragments before the page is rendered inside a target deck.
"""
from __future__ import annotations

import html as html_lib
import re

_STYLE_RE = re.compile(
    r'<style(?P<attrs>(?:[^>"\']+|"[^"]*"|\'[^\']*\')*)>'
    r'(?P<body>.*?)</style\s*>',
                       re.S | re.I)
_SCRIPT_RE = re.compile(
    r'<script(?P<attrs>(?:[^>"\']+|"[^"]*"|\'[^\']*\')*)>'
    r'(?P<body>.*?)</script\s*>',
                        re.S | re.I)
_SCRIPT_OPEN_RE = re.compile(
    r'<script(?P<attrs>(?:[^>"\']+|"[^"]*"|\'[^\']*\')*)>', re.S | re.I,
)
_TAG_RE = re.compile(r'<(?:[^<>"\']+|"[^"]*"|\'[^\']*\')*>', re.S)
_ATTR_TOKEN_RE = re.compile(
    r'(?P<leading>\s+)(?P<name>[^\s=/>]+)'
    r'(?:\s*=\s*(?P<value>"[^"]*"|\'[^\']*\'|[^\s>]+))?', re.S,
)
_URL_ATTRS = {"href", "src", "srcset", "xlink:href", "action", "formaction", "poster", "background"}


def _attr(attrs: str, name: str) -> str:
    m = re.search(
        rf'\b{name}\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s"\'>]+))',
        attrs or "",
        re.I,
    )
    return (m.group(1) or m.group(2) or m.group(3) or "") if m else ""


def _is_executable_script(attrs: str) -> bool:
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


def _token_value(match: re.Match) -> str:
    value = match.group("value") or ""
    if len(value) >= 2 and value[0] in {'"', "'"} and value[-1] == value[0]:
        return value[1:-1]
    return value


def consolidate_author_styles(html: str) -> tuple[str, str, int]:
    """Move every fragment `<style>` body out of `html`.

    Framework styles are renderer-owned and live outside ``.slide``. Therefore a
    marker found inside an imported fragment is author-controlled and cannot be
    trusted as provenance.
    """
    if not isinstance(html, str) or "<style" not in html.lower():
        return html or "", "", 0
    bodies: list[str] = []
    count = 0

    def take(match: re.Match) -> str:
        nonlocal count
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

    Non-executable `<script type="application/json">` / `text/plain` islands are
    preserved. Fragment-owned ``data-source=framework`` and framework-looking
    basenames are not provenance and receive no exemption. Returns
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

    # A malformed/unclosed external script can still load as soon as the browser
    # parses its opening tag. Remove any executable opener left after complete
    # blocks were handled; its trailing text becomes inert fragment text.
    out = _SCRIPT_OPEN_RE.sub(strip_script, out)
    handler_count = 0

    def strip_handlers(match: re.Match) -> str:
        nonlocal handler_count
        tag = match.group(0)
        if tag.lower().startswith(("<script", "<style")):
            return tag
        def clean_attr(attr_match: re.Match) -> str:
            nonlocal handler_count
            if not (attr_match.group("name") or "").lower().startswith("on"):
                return attr_match.group(0)
            handler_count += 1
            return ""

        return _ATTR_TOKEN_RE.sub(clean_attr, tag)

    out = _TAG_RE.sub(strip_handlers, out)
    return out, script_count, handler_count


def _normalized_url(value: str) -> str:
    decoded = html_lib.unescape(value or "")
    return re.sub(r"[\x00-\x20\x7f]+", "", decoded).lower()


def _active_url(value: str) -> bool:
    normalized = _normalized_url(value)
    candidates = [normalized]
    # srcset is a comma-separated list whose first token in every item is a URL.
    candidates.extend(item.split()[0] for item in normalized.split(",") if item.split())
    for candidate in candidates:
        if candidate.startswith(("javascript:", "vbscript:")):
            return True
        if candidate.startswith("data:"):
            mime = candidate[5:].split(";", 1)[0].split(",", 1)[0]
            if mime in {
                "text/html", "application/xhtml+xml", "image/svg+xml",
                "text/javascript", "application/javascript",
                "text/ecmascript", "application/ecmascript",
                "text/xml", "application/xml",
            }:
                return True
    return False


def strip_active_attributes(html: str) -> tuple[str, int]:
    """Remove srcdoc and executable URL/style attributes from a fragment."""
    if not isinstance(html, str) or not html:
        return "", 0
    stripped = 0

    def clean_tag(match: re.Match) -> str:
        nonlocal stripped
        tag = match.group(0)
        if tag.lower().startswith(("<script", "<style")):
            return tag

        def clean_attr(attr_match: re.Match) -> str:
            nonlocal stripped
            name = (attr_match.group("name") or "").lower()
            value = _token_value(attr_match)
            unsafe = name == "srcdoc" or (name in _URL_ATTRS and _active_url(value))
            if name == "style":
                decoded = html_lib.unescape(value)
                urls = re.findall(r"url\(\s*(['\"]?)(.*?)\1\s*\)", decoded, re.I | re.S)
                unsafe = unsafe or any(_active_url(url) for _quote, url in urls)
                unsafe = unsafe or bool(
                    re.search(r"(?:expression\s*\(|-moz-binding\s*:)", decoded, re.I))
            if unsafe:
                stripped += 1
                return ""
            return attr_match.group(0)

        return _ATTR_TOKEN_RE.sub(clean_attr, tag)

    return _TAG_RE.sub(clean_tag, html), stripped


def hygienize_lifted_raw_html(html: str) -> tuple[str, str, dict]:
    """Return `(clean_html, css_to_custom_css, report)` for a lifted raw slide."""
    clean, css, style_count = consolidate_author_styles(html)
    clean, active_attrs = strip_active_attributes(clean)
    clean, scripts, handlers = strip_executable_markup(clean)
    report = {
        "styles_consolidated": style_count,
        "scripts_stripped": scripts,
        "handlers_stripped": handlers,
        "active_attributes_stripped": active_attrs,
    }
    return clean, css, report
