#!/usr/bin/env python3
"""render-deck.py — Phase 1 DeckJSON renderer.

Reads a deck.json (validated against deck-schema.json) and emits a
complete HTML deck composed of per-(layout, variant) fragment templates.
Then runs the skill's HTML validator (assets/validate.py) as a HARD GATE
before declaring success.

Pipeline:
  1. Validate deck.json against schema     → fail-fast on bad data
  2. Load deck                              → JSON parse
  3. Render each slide via dispatcher       → fragment per (layout, variant)
  4. Render embeddable blocks in body_blocks → partial per block.type
  5. Compose into deck shell                → _shell.html template
  6. Run HTML validator on output           → fail if validator errors
  7. Write index.html + report success

stdlib-only Python 3.11+. No external deps. Mirrors render.py conventions
(same {{ field }} / {{{ field }}} substitution syntax).

Phase 1.a coverage (this version):
  layouts:  cover, agenda, content/3up, content/2col, quote, end
  blocks:   pullquote, kpi-strip, cta-box, data-panel
  Slides using uncovered (layout, variant) combos error with a clear msg.

Phase 1.b/c/d (later versions) add the rest of the 12 layouts + 3 blocks.

Usage:
  python3 render-deck.py <deck.json> <output-dir>/ [--skip-validate-json] [--skip-validate-html]
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Story-case fit primitives are single-sourced in _story_case_fit.py (F-15) so
# render-deck.py and validate-deck.py can't drift apart.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _story_case_fit import (  # noqa: E402
    get_path,
    PLACEHOLDER_PATTERNS as _PLACEHOLDER_PATTERNS,
    STORY_CASE_FIT_CHECK,
    _min_len_for,
)
# scope_selectors co-locates per-slide custom_css scoped to its slide-key
# (LIFT-ARCHITECTURE step 2) so the CSS travels with the slide on lift/clone.
from _css_utils import scope_selectors  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

HERE          = Path(__file__).resolve().parent       # deck-json/
SKILL_ROOT    = HERE.parent                            # skills/feishu-deck-h5/
ASSETS_DIR    = SKILL_ROOT / "assets"
TEMPLATES_DIR = HERE / "templates"
BLOCKS_DIR    = TEMPLATES_DIR / "blocks"
SCHEMA_FILE   = HERE / "deck-schema.json"
VALIDATE_DECK = HERE / "validate-deck.py"
VALIDATE_HTML = ASSETS_DIR / "validate.py"
COPY_ASSETS   = ASSETS_DIR / "copy-assets.py"

# Phase 4 / post-review-medium-6: there's now ONE pathway for \n→<br>.
# Every {{ field }} substitution goes through _esc_br (see render_template
# sub_safe). Templates use {{ title }} not {{{ title }}}, so user text gets
# both HTML-escaped AND newline-converted in one safe pass — no separate
# BR_FIELDS pre-walk needed. Use {{{ raw }}} only when the renderer/enricher
# itself built trusted HTML (e.g. enricher-composed `cards_html`).


def _optional_text_node(value, slide_no_padded: str, text_id_suffix: str,
                        tag: str = "p", classes: str = "", indent: str = "          ") -> str:
    """Render an optional text node (returns "" if value is falsy).

    Used by ~10 enrichers for fields like subtitle/lede/footnote/source/
    attribution — the boilerplate "if X: ctx[X_html] = '<tag class=... data-
    text-id=slide-NN.X>{escaped}</tag>' else ''" pattern.

    Args:
      value:            the source string (None / "" → returns "")
      slide_no_padded:  ctx['slide_no_padded'] for the data-text-id prefix
      text_id_suffix:   tail of data-text-id (e.g. "lede", "footnote")
      tag:              wrapping element ("p", "h2", "span", "div", ...)
      classes:          CSS classes for the wrapper
      indent:           leading whitespace for output (templates expect it)

    Returns the HTML string ready to interpolate into a `{{{ X_html }}}` slot.
    """
    if not value:
        return ""
    cls_attr = f' class="{classes}"' if classes else ""
    return (f'{indent}<{tag}{cls_attr} data-text-id="slide-{slide_no_padded}.{text_id_suffix}">'
            f'{_esc_br(value)}</{tag}>')


def _esc_br(s):
    """HTML-escape AND convert \\n → <br>. The single path for converting
    user-typed text into HTML-safe markup with line breaks preserved.

    Used by:
      - render_template sub_safe (all {{ field }} substitutions, including
        title/heading/lede/body/attribution/etc.)
      - enrichers that compose HTML fragments inline (cards_html, cols_html...)

    Escape FIRST, then \\n→<br>, so the <br> tags survive html.escape.
    None → empty string. Non-string → str() then escaped."""
    if s is None:
        return ""
    return html.escape(str(s), quote=True).replace("\n", "<br>")


# ---------------------------------------------------------------------------
# Helpers (mirror render.py — kept inline for self-contained script)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# content/story-case schema-fit refusal + accent review
# Ported 2026-05-26 from the retired assets/render.py one-pager pipeline.
# story-case carries the SAME field shape (hook.{lead,accent,tail},
# arc.{pain,conflict,solution}, arc.value.{lead,accent,tail}), so the checks
# apply verbatim. The JSON schema enforces field PRESENCE; this catches
# placeholder / too-short / duplicate beats it can't see, and prints the
# accent word for a 1-second eyeball. Opt out with --skip-fit-check.
# ---------------------------------------------------------------------------

STORY_CASE_ACCENT_PATHS = (
    ("hook",  "hook"),
    ("value", "arc.value"),
)


def check_story_case_fit(data: dict) -> list:
    """Return fit issues for one content/story-case slide's data dict.
    Empty list = OK. Mirrors the retired render.py one-pager schema-fit gate."""
    issues = []
    seen = {}
    for path in STORY_CASE_FIT_CHECK:
        try:
            text = get_path(data, path)
        except KeyError:
            continue
        text = text.strip() if isinstance(text, str) else ""
        for pat in _PLACEHOLDER_PATTERNS:
            if re.search(pat, text, flags=re.IGNORECASE):
                issues.append(f"{path}: 占位词 ({text!r}) — 这一拍承不起,改内容或换 layout")
                break
        else:
            min_len = _min_len_for(path)
            if len(text) < min_len:
                issues.append(f"{path}: 只有 {len(text)} 字 ({text!r}) — 太短,该 beat 可能不存在")
            elif text in seen and not path.endswith((".lead", ".tail", ".accent")):
                issues.append(f"{path}: 与 {seen[text]} 完全相同 ({text!r}) — 这一拍可能不存在")
            else:
                seen[text] = path
    return issues


def show_story_case_accents(data: dict, slide_key: str) -> None:
    """Print accent-bearing fields with the highlight marked (ANSI teal in a
    TTY, brackets otherwise) for a 1-second 'is the right word emphasized?'."""
    use_color = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    hl_o = "\033[1;36m" if use_color else "["
    hl_c = "\033[0m" if use_color else "]"
    for label, base in STORY_CASE_ACCENT_PATHS:
        try:
            lead   = get_path(data, f"{base}.lead")
            accent = get_path(data, f"{base}.accent")
            tail   = get_path(data, f"{base}.tail")
        except KeyError:
            continue
        print(f"  {slide_key} · {label:>5}  ·  {lead}{hl_o}{accent}{hl_c}{tail}")


def relpath_from_to(src_dir: Path, dst_dir: Path) -> str:
    return os.path.relpath(dst_dir, start=src_dir).replace(os.sep, "/")


def render_template(template: str, data: dict) -> str:
    """Substitute placeholders in `template`.

    Syntax:
      {{{ field }}}  raw   — value substituted as-is (use for known HTML)
      {{ field }}    safe  — value HTML-escaped (default)

    Raw substitutions are resolved FIRST and parked behind NUL sentinels so the
    subsequent safe `{{ }}` pass never re-scans raw-injected author HTML — a raw
    slide's data.html or an enricher-built `*_html` slot may legitimately contain
    a literal `{{ word }}` (e.g. a templating-syntax demo or copy with double
    braces), which must NOT be re-interpreted as a missing-field placeholder
    (that would SystemExit the whole render). Supports dotted paths: {{ a.b }}.
    """
    raw_chunks: list[str] = []

    def sub_raw(m):
        path = m.group(1).strip()
        try:
            raw_chunks.append(str(get_path(data, path)))
        except KeyError:
            raise SystemExit(f"render-deck: template references missing field {{{{{{ {path} }}}}}}")
        return f"\x00RAW{len(raw_chunks) - 1}\x00"
    template = re.sub(r"\{\{\{\s*([\w.]+)\s*\}\}\}", sub_raw, template)

    def sub_safe(m):
        path = m.group(1).strip()
        try:
            value = get_path(data, path)
        except KeyError:
            raise SystemExit(f"render-deck: template references missing field {{{{ {path} }}}}")
        return _esc_br(str(value))
    template = re.sub(r"\{\{\s*([\w.]+)\s*\}\}", sub_safe, template)

    # Restore parked raw chunks AFTER the safe pass, verbatim (never re-scanned).
    return re.sub(r"\x00RAW(\d+)\x00", lambda m: raw_chunks[int(m.group(1))], template)


# ---------------------------------------------------------------------------
# Slide rendering
# ---------------------------------------------------------------------------

def _derive_screen_label(slide: dict) -> str:
    title = slide.get("data", {}).get("title", "")
    if not title:
        return slide.get("key", "untitled")[:20]
    cleaned = re.sub(r"\s+", " ", re.sub(r"[·:：—\-]+", " ", title))
    cleaned = cleaned.replace("\n", " ").replace("<br>", " ")
    return cleaned.strip()[:20]


def _renumber_label(slide: dict, frame_index: int) -> str:
    """Canonical screen_label = '<frame_index:02d> <name>'. Strips any existing
    leading number token ('50 飞书生态' / '04-A 标题' → name), then re-prefixes
    with the slide's TRUE frame_index, so the library label number stops drifting
    from the on-screen page number / URL hash after lift / insert / reorder.
    Used by render --renumber."""
    base = slide.get("screen_label") or _derive_screen_label(slide)
    name = re.sub(r"^\s*\d[\w\-]*\s+", "", base).strip() or _derive_screen_label(slide)
    return f"{frame_index:02d} {name}"


def _build_data_attrs(slide: dict) -> str:
    """Compose data-accent + data-decor + per-slide title-style / logo-position
    overrides for the .slide element.
    Variant is NOT emitted on .slide (production decks use class modifiers,
    per Phase 0.1 survey); it's only used JSON-side for template dispatch.
    title_style + logo_position are deck-level defaults (on .deck) — only
    emitted on .slide when overridden per-slide."""
    parts = []
    if slide.get("accent"):
        parts.append(f'data-accent="{_esc_br(slide["accent"])}"')
    decor = slide.get("decor", [])
    if decor:
        parts.append(f'data-decor="{_esc_br(" ".join(decor))}"')
    if slide.get("title_style"):
        parts.append(f'data-title-style="{_esc_br(slide["title_style"])}"')
    if slide.get("logo_position"):
        parts.append(f'data-logo-position="{_esc_br(slide["logo_position"])}"')
    if slide.get("lifted"):
        # Native slide lift: mark the slide so validate.py / visual-audit.js
        # downgrade its CONTENT-STYLE violations (R06 / R-WHITE-TEXT /
        # R-VIS-BODY-FLOOR / R-VIS-TIER) from error → warning. Geometry /
        # overflow rules stay full severity. Value = source ref string.
        val = slide["lifted"] if isinstance(slide["lifted"], str) else "1"
        parts.append(f'data-lifted="{_esc_br(val)}"')
    return " ".join(parts)


def _tone_modifier(tone: str | None) -> str:
    """tone='orange' → ' is-orange'; tone='default' / None → ''."""
    if not tone or tone == "default":
        return ""
    return f" is-{tone}"


def _enrich_pullquote(block):
    block["tone_modifier"] = _tone_modifier(block.get("tone"))

def _enrich_cta_box(block):
    block["tone_modifier"] = _tone_modifier(block.get("tone"))
    body = block.get("body")
    block["body_html"] = (
        f'              <p>{_esc_br(body)}</p>'
        if body else ""
    )
    btn = block.get("button_label")
    block["button_html"] = (
        f'            <button class="cta-btn">{_esc_br(btn)} →</button>'
        if btn else ""
    )

def _enrich_kpi_strip(block):
    kpis = block.get("kpis", [])
    block["strip_cols"] = len(kpis)
    rows = []
    for j, k in enumerate(kpis):
        v = _esc_br(k.get("value", ""))
        l = _esc_br(k.get("label", ""))
        tone_cls = _tone_modifier(k.get("tone", "teal"))

        rows.append(
            f'            <div class="kpi">'
            f'<div class="v{tone_cls}">{v}</div>'
            f'<div class="l">{l}</div></div>'
        )
    block["kpis_html"] = "\n".join(rows)

def _enrich_data_panel(block):
    block["tone_modifier"] = _tone_modifier(block.get("tone"))
    rows = block.get("rows", [])
    out = []
    for j, r in enumerate(rows):
        lbl = _esc_br(r.get("lbl", ""))
        val = _esc_br(r.get("val", ""))
        tone_cls = " warn" if r.get("tone") == "warn" else ""

        out.append(
            f'            <div class="row">'
            f'<span class="lbl">{lbl}</span>'
            f'<span class="val{tone_cls}">{val}</span></div>'
        )
    block["rows_html"] = "\n".join(out)


def _enrich_verdict_grid(block):
    cards = block.get("cards", [])
    block["card_count"] = len(cards)
    parts = []
    for i, c in enumerate(cards):
        verdict = c.get("verdict", "go")
        badge = _esc_br(c.get("badge", ""))
        title = _esc_br(c.get("title", ""))
        # body may contain inline <span class="accent-text">...</span> — trust raw
        body = c.get("body", "")
        kpis = c.get("kpis", [])

        kpis_html = ""
        if kpis:
            kpi_rows = "\n".join(
                f'              <div class="kpi">'
                f'<div class="v{_tone_modifier(k.get("tone","teal"))}">'
                f'{_esc_br(k.get("value",""))}</div>'
                f'<div class="l">'
                f'{_esc_br(k.get("label",""))}</div></div>'
                for j, k in enumerate(kpis)
            )
            kpis_html = (
                f'\n              <div class="kpi-strip" style="--strip-cols:{len(kpis)};margin-top:auto">\n'
                f'{kpi_rows}\n'
                f'              </div>'
            )
        parts.append(
            f'            <div class="verdict-card" data-verdict="{verdict}">\n'
            f'              <span class="badge">{badge}</span>\n'
            f'              <h3 class="ctitle">{title}</h3>\n'
            f'              <p class="cbody">{body}</p>'
            f'{kpis_html}\n'
            f'            </div>'
        )
    block["cards_html"] = "\n".join(parts)


def _enrich_phone_iframe(block):
    hint = block.get("hint")
    block["hint_html"] = (
        f'            <div class="iframe-hint">{_esc_br(hint)}</div>'
        if hint else ""
    )
    if not block.get("title"):
        block["title"] = "Phone prototype"


def _enrich_principle_band(block):
    principles = block.get("principles", [])
    parts = []
    for i, p in enumerate(principles):
        text = _esc_br(p.get("text", ""))
        color = p.get("color", "teal")

        parts.append(
            f'            <span class="principle" data-color="{color}">{text}</span>'
        )
    block["principles_html"] = "\n".join(parts)


def _enrich_mockup_card(block):
    """mockup-card — UI mockup card · 4 kinds (past/now/callout/compare).
    Kind gets a CSS class modifier; optional fields (image, label,
    compare_pair) gate their respective HTML chunks."""
    kind = block.get("kind", "now")
    block["kind_modifier"] = f" is-{kind}"
    block["label_html"] = (
        f'              <div class="eyebrow">{_esc_br(block.get("label", ""))}</div>'
        if block.get("label") else ""
    )
    body = block.get("body")
    block["body_html"] = (
        f'              <p class="body">{_esc_br(body)}</p>' if body else ""
    )
    img = block.get("image")
    block["image_html"] = (
        f'              <div class="ui-shot" '
        f'style="background-image:url(\'{_esc_br(img)}\')"></div>'
        if img else ""
    )
    cp = block.get("compare_pair") or {}
    if kind == "compare" and cp:
        block["compare_html"] = (
            f'              <div class="compare-pair">'
            f'<span class="left">{_esc_br(cp.get("left", ""))}</span>'
            f'<span class="vs">vs</span>'
            f'<span class="right">{_esc_br(cp.get("right", ""))}</span>'
            f'</div>'
        )
    else:
        block["compare_html"] = ""


def _enrich_persona_card(block):
    """persona-card — name + role + generation + summary + optional portrait."""
    gen = block.get("generation")
    block["generation_html"] = (
        f'              <span class="generation">{_esc_br(gen)}</span>'
        if gen else ""
    )
    summary = block.get("summary")
    block["summary_html"] = (
        f'              <p class="summary">{_esc_br(summary)}</p>'
        if summary else ""
    )
    portrait = block.get("portrait")
    block["portrait_html"] = (
        f'              <div class="portrait" '
        f'style="background-image:url(\'{_esc_br(portrait)}\')"></div>'
        if portrait else ""
    )


def _enrich_testimonial_card(block):
    """testimonial-card — customer testimonial with name/title/quote + optional
    portrait + company_logo. block.get("_block_path") is used by render_slide
    to build data-text-id prefix; we just precompute the snake-case fields.

    company_logo resolution:
      - if it contains '/' or '.' (looks like a path), use as-is
      - else treat as logical key → resolve to <asset_path>/shared/clientlogo/<key>.png
    portrait: always treated as a path (relative to deck.json dir).
    """
    portrait = block.get("portrait")
    block["portrait_html"] = (
        f'              <div class="portrait" style="background-image:url(\'{_esc_br(portrait)}\')"></div>'
        if portrait else ""
    )
    logo = block.get("company_logo")
    if logo:
        if "/" in logo or "." in logo:
            src = logo
        else:
            # Logical key — enricher resolves via asset_path. Sanitize.
            safe = re.sub(r"[/\\.]+", "_", str(logo)).lstrip("_") or "missing"
            # Note: we don't have direct access to asset_path here (block enricher);
            # use a sentinel that gets substituted at slide render time via {{ asset_path }}.
            src = f"{{ASSET_PATH}}/shared/clientlogo/{safe}.png"
        block["company_logo_html"] = (
            f'              <div class="company-logo" style="background-image:url(\'{_esc_br(src)}\')"></div>'
        )
    else:
        block["company_logo_html"] = ""


BLOCK_ENRICHERS = {
    "pullquote":        _enrich_pullquote,
    "cta-box":          _enrich_cta_box,
    "kpi-strip":        _enrich_kpi_strip,
    "data-panel":       _enrich_data_panel,
    "verdict-grid":     _enrich_verdict_grid,
    "phone-iframe":     _enrich_phone_iframe,
    "testimonial-card": _enrich_testimonial_card,
    "mockup-card":      _enrich_mockup_card,
    "persona-card":     _enrich_persona_card,
    "principle-band": _enrich_principle_band,
}


def render_block(block: dict, asset_path: str = "..") -> str:
    """Render an embeddable block by its type field.

    asset_path: passed through so blocks that resolve framework-shared assets
    (e.g. testimonial-card's company_logo logical key) can compute correct
    relative paths. Block enrichers leave a `{ASSET_PATH}` sentinel and we
    substitute here after rendering.
    """
    block_type = block.get("type")
    if not block_type:
        raise SystemExit(f"render-deck: block missing 'type' field: {block!r}")
    tpl_path = BLOCKS_DIR / f"{block_type}.fragment.html"
    if not tpl_path.exists():
        raise SystemExit(
            f"render-deck: no template for block type='{block_type}' (expected {tpl_path}). "
            f"Known types: pullquote, kpi-strip, cta-box, data-panel, "
            f"verdict-grid, phone-iframe, principle-band, testimonial-card."
        )
    enricher = BLOCK_ENRICHERS.get(block_type)
    block_ctx = dict(block)
    if enricher:
        enricher(block_ctx)
    rendered = render_template(tpl_path.read_text(encoding="utf-8"), block_ctx)
    # Substitute asset_path sentinel left by block enrichers (e.g. for
    # company_logo logical-key resolution in testimonial-card)
    return rendered.replace("{ASSET_PATH}", asset_path)


def _resolve_template_path(layout: str, variant: str | None) -> Path:
    """Pick the fragment template file for a (layout, variant) combo."""
    if variant:
        candidates = [
            TEMPLATES_DIR / f"{layout}-{variant}.fragment.html",
            TEMPLATES_DIR / f"{layout}.fragment.html",  # fallback
        ]
    else:
        candidates = [TEMPLATES_DIR / f"{layout}.fragment.html"]

    for p in candidates:
        if p.exists():
            return p

    raise SystemExit(
        f"render-deck: no template for layout='{layout}' variant='{variant}' "
        f"(looked for {[str(p.relative_to(HERE)) for p in candidates]}). "
        f"Phase 1.a covers: cover, agenda, content/3up, content/2col, quote, end."
    )


def _render_feature_list(items: list | None) -> str:
    if not items:
        return ""
    lis = "\n".join(f'        <li>{_esc_br(str(item))}</li>' for item in items)
    return f'      <ul class="feature-list">\n{lis}\n      </ul>'


# ---------------------------------------------------------------------------
# Agenda helper (items list → HTML)
# ---------------------------------------------------------------------------

def render_agenda_items(items: list, slide_no_padded: str) -> str:
    """Compose .toc rows for the agenda layout. Items array shape per schema."""
    rows = []
    for i, item in enumerate(items, start=1):
        n = f"{i:02d}"
        idx = i - 1
        zh = _esc_br(item.get("title_zh", ""))
        en = item.get("title_en")
        en_html = (
            f'<div class="title-en" data-allow-body-floor>'
            f'{_esc_br(en)}</div>'
            if en else ""
        )
        # active/dim modifiers per recap variant
        classes = ["item"]
        if item.get("active"): classes.append("is-active")
        if item.get("dim"):    classes.append("is-dim")
        cls = " ".join(classes)
        rows.append(
            f'        <div class="{cls}"><div class="n">{n}</div>'
            f'<div><div class="title-zh" data-text-id="slide-{slide_no_padded}.item-{n}">{zh}</div>{en_html}</div></div>'
        )
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# Card helpers (content/3up)
# ---------------------------------------------------------------------------

ICON_LIB = {
    "message-circle":   '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    "users":            '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "check-circle":     '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
    "check":            '<polyline points="20 6 9 17 4 12"/>',
    "zap":              '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    "trending-up":      '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>',
    "clock":            '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "layout-dashboard": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/>',
    # — expanded 2026-05-29 (quality benchmark: models reach for these Lucide names) —
    "activity":         '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>',
    "trending-down":    '<polyline points="23 18 13.5 8.5 8.5 13.5 1 6"/><polyline points="17 18 23 18 23 12"/>',
    "target":           '<circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/>',
    "bar-chart":        '<line x1="12" y1="20" x2="12" y2="10"/><line x1="18" y1="20" x2="18" y2="4"/><line x1="6" y1="20" x2="6" y2="16"/>',
    "bar-chart-2":      '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
    "pie-chart":        '<path d="M21.21 15.89A10 10 0 1 1 8 2.83"/><path d="M22 12A10 10 0 0 0 12 2v10z"/>',
    "arrow-right":      '<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>',
    "arrow-up-right":   '<line x1="7" y1="17" x2="17" y2="7"/><polyline points="7 7 17 7 17 17"/>',
    "arrow-up":         '<line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>',
    "arrow-down":       '<line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/>',
    "star":             '<polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>',
    "award":            '<circle cx="12" cy="8" r="7"/><polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"/>',
    "alert-triangle":   '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    "shield":           '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "lightbulb":        '<path d="M9 18h6"/><path d="M10 22h4"/><path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5A4.61 4.61 0 0 1 8.91 14"/>',
    "rocket":           '<path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>',
    "layers":           '<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>',
    "database":         '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>',
    "calendar":         '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
    "mail":             '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 6-10 7L2 6"/>',
    "search":           '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "eye":              '<path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/>',
    "globe":            '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    "git-branch":       '<line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
    "map-pin":          '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>',
    "dollar-sign":      '<line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/>',
    "briefcase":        '<rect x="2" y="7" width="20" height="14" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
    "file-text":        '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><line x1="10" y1="9" x2="8" y2="9"/>',
    "flag":             '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/>',
    "heart":            '<path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>',
    "x-circle":         '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>',
    "plus-circle":      '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="16"/><line x1="8" y1="12" x2="16" y2="12"/>',
    "refresh-cw":       '<polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
    "filter":           '<polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/>',
    "package":          '<line x1="16.5" y1="9.4" x2="7.5" y2="4.21"/><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>',
}


def _render_icon(icon, default_svg=None):
    """Icon ref → inline SVG string. Accepts named (from ICON_LIB) or {svg: ...}."""
    if isinstance(icon, dict) and "svg" in icon:
        return icon["svg"]
    if isinstance(icon, str) and icon in ICON_LIB:
        paths = ICON_LIB[icon]
        return (f'<svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" '
                f'fill="none" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')
    if isinstance(icon, str) and icon:
        # Don't let a mistyped/unknown icon name silently vanish (quality-benchmark finding).
        print(f'  ⚠ icon "{icon}" not in ICON_LIB — dropped. Known ({len(ICON_LIB)}): '
              f'{", ".join(sorted(ICON_LIB))}. Or pass an inline {{"svg": "<svg…>"}}.',
              file=sys.stderr)
    return default_svg or ""


def render_3up_cards(cards: list, slide_no_padded: str) -> str:
    """Render .card row for content/3up."""
    out = []
    for i, card in enumerate(cards, start=1):
        n_padded = f"{i:02d}"
        idx = i - 1
        num = card.get("num", n_padded)
        icon_svg = _render_icon(card.get("icon"))
        title_zh = _esc_br(card.get("title_zh", ""))
        title_en = card.get("title_en")
        title_html = title_zh
        if title_en:
            title_html += f'<br>{_esc_br(title_en)}'
        body = _esc_br(card.get("body", ""))
        footer = card.get("footer_label")
        kpi = card.get("kpi")

        head_block = f'        <div class="head">\n'
        if icon_svg:
            head_block += f'          <div class="tile">{icon_svg}</div>\n'
        head_block += (f'          <div class="num">'
                       f'{_esc_br(num)}</div>\n')
        head_block += f'        </div>'

        kpi_block = ""
        if kpi:
            kpi_v = _esc_br(kpi.get("value", ""))
            kpi_l = _esc_br(kpi.get("label", ""))
            kpi_block = (f'\n        <div class="kpi" style="margin-top:auto;display:flex;'
                         f'align-items:baseline;gap:8px">'
                         f'<span class="v" '
                         f'style="font:700 48px/1 var(--fs-font-latin);color:var(--fs-teal)">{kpi_v}</span>'
                         f'<span class="l" '
                         f'style="font:500 16px/1 var(--fs-font-cjk);color:rgba(255,255,255,0.92)">{kpi_l}</span></div>')

        foot_block = ""
        if footer:
            foot_block = (f'\n        <div class="cfoot">'
                          f'<span data-allow-body-floor>'
                          f'{_esc_br(footer)}</span>'
                          f'<svg width="20" height="20" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round">'
                          f'<path d="M5 12h14M13 6l6 6-6 6"/></svg></div>')

        out.append(
            f'      <div class="card">\n'
            f'{head_block}\n'
            f'        <h3 class="ctitle" data-text-id="slide-{slide_no_padded}.card-{n_padded}.title">{title_html}</h3>\n'
            f'        <p class="cbody" data-text-id="slide-{slide_no_padded}.card-{n_padded}.body">{body}</p>'
            f'{kpi_block}'
            f'{foot_block}\n'
            f'      </div>'
        )
    return "\n".join(out)


# Custom slide renderer dispatch ------------------------------------------------
# Some layouts need helper-composed HTML before template substitution.
# These map (layout, variant) → ctx mutator.

def _enrich_cover(ctx, slide):
    snp = ctx["slide_no_padded"]
    ctx["subtitle_html"] = _optional_text_node(
        ctx.get("subtitle"), snp, "subtitle", classes="subtitle")


def _enrich_agenda(ctx, slide):
    snp = ctx["slide_no_padded"]
    items = ctx.get("items", [])
    ctx["agenda_items_html"] = render_agenda_items(items, snp)
    # header is optional (v2 default hides header — pills speak for themselves)
    title = ctx.get("title")
    if title:
        title_node = _optional_text_node(title, snp, "title",
                                         tag="h2", classes="title-zh",
                                         indent="          ")
        ctx["header_html"] = f'        <div class="header">\n{title_node}\n        </div>'
    else:
        ctx["header_html"] = ""


def _enrich_content_3up(ctx, slide):
    snp = ctx["slide_no_padded"]
    ctx["cards_html"] = render_3up_cards(ctx.get("cards", []), snp)
    ctx["lede_html"] = _optional_text_node(
        ctx.get("lede"), snp, "lede", classes="lede")


def _enrich_content_2col(ctx, slide):
    snp = ctx["slide_no_padded"]
    text = ctx.get("text", {}) or {}
    ctx["text_lede_html"] = _optional_text_node(
        text.get("lede"), snp, "text.lede", classes="lede",
        indent="              ")

    ctx["text_feature_list_html"] = _render_feature_list_v2(
        text.get("feature_list"), ctx["slide_no_padded"]
    )

    # text_body_blocks_html is computed by render_slide() (not here).

    visual = ctx.get("visual", {}) or {}
    ctx["visual_html"] = _render_visual(visual, ctx["slide_no_padded"])


def _render_feature_list_v2(items, slide_no_padded):
    if not items:
        return ""
    lis = "\n".join(
        f'                <li data-text-id="slide-{slide_no_padded}.text.feature-{i+1:02d}">'
        f'{_esc_br(str(item))}</li>'
        for i, item in enumerate(items)
    )
    return (f'              <ul class="feature-list">\n'
            f'{lis}\n              </ul>')


def _render_visual(visual, slide_no_padded):
    v_type = visual.get("type")
    if v_type == "image":
        img = visual.get("image", {})
        src = _esc_br(img.get("src", ""))
        alt = _esc_br(img.get("alt", ""))
        fit = visual.get("min_height")
        style = f'min-height:{_esc_br(fit)}px;' if fit else ""
        return (
            f'              <div role="img" aria-label="{alt}" '
            f'style="background-image:url(\'{src}\');background-size:cover;'
            f'background-position:center;{style}width:100%;height:100%;'
            f'min-height:400px;border-radius:16px"></div>'
        )
    if v_type == "data-panel":
        panel = visual.get("panel", {})
        return render_block(panel)
    if v_type == "raw-svg":
        return visual.get("svg", "")
    if v_type == "placeholder":
        label = _esc_br(visual.get("label", "〔visual TODO〕"))
        return (
            f'              <div style="display:flex;align-items:center;justify-content:center;'
            f'width:100%;height:100%;min-height:400px;border:1px dashed rgba(255,255,255,0.20);'
            f'border-radius:16px;color:rgba(255,255,255,0.55);'
            f'font:500 24px/1 var(--fs-font-cjk)">{label}</div>'
        )
    return ""


def _enrich_end(ctx, slide):
    snp = ctx["slide_no_padded"]
    ctx["contact_html"] = _optional_text_node(
        ctx.get("contact"), snp, "contact",
        tag="div", classes="contact", indent="        ")
    # Optional slogan — mirrors PPT '封底(带 slogan)' layout master.
    ctx["slogan_html"] = _optional_text_node(
        ctx.get("slogan"), snp, "slogan",
        tag="div", classes="slogan", indent="        ")


def _enrich_section(ctx, slide):
    snp = ctx["slide_no_padded"]
    # Optional parent_label — when present, marks this as a subsection
    # (PPT layout 3 '二级章节页'). Renders above the title.
    ctx["parent_label_html"] = _optional_text_node(
        ctx.get("parent_label"), snp, "parent_label",
        tag="div", classes="parent-label", indent="        ")
    ctx["lede_html"] = _optional_text_node(
        ctx.get("lede"), snp, "lede", classes="lede", indent="        ")

    pills = ctx.get("pills") or []
    if pills:
        items = "\n".join(
            f'          <span class="pill" data-text-id="slide-{snp}.pill-{i+1:02d}">'
            f'{_esc_br(p)}</span>'
            for i, p in enumerate(pills)
        )
        ctx["pills_html"] = f'        <div class="pills">\n{items}\n        </div>'
    else:
        ctx["pills_html"] = ""


def _enrich_stats_row(ctx, slide):
    cols = ctx.get("cols") or []
    snp = ctx["slide_no_padded"]
    rendered = []
    for i, col in enumerate(cols, start=1):
        cn = f"{i:02d}"
        idx = i - 1
        icon_svg = _render_icon(col.get("icon"))
        tile = (
            f'            <div class="tile sm">{icon_svg}</div>\n'
            if icon_svg else ""
        )
        trend = col.get("trend")
        trend_html = (
            f'            <span class="trend" data-text-id="slide-{snp}.col-{cn}.trend">'
            f'{_esc_br(trend)}</span>\n'
            if trend else ""
        )
        num = _esc_br(col.get("num", ""))
        unit = col.get("unit")
        # unit nests inside .num; do NOT give it its own data-text-id (would
        # violate SKILL.md mixed-text-and-inline rule). User edits "3秒" as one
        # leaf via slide-NN.col-XX.num.
        unit_html = (
            f'<span class="unit">{_esc_br(unit)}</span>'
            if unit else ""
        )
        label = _esc_br(col.get("label", ""))
        source = col.get("source")
        source_html = (
            f'\n            <div class="source" data-text-id="slide-{snp}.col-{cn}.source">'
            f'{_esc_br(source)}</div>'
            if source else ""
        )
        rendered.append(
            f'          <div class="col">\n'
            f'{tile}'
            f'{trend_html}'
            f'            <div class="num" data-text-id="slide-{snp}.col-{cn}.num">{num}{unit_html}</div>\n'
            f'            <div class="label" data-text-id="slide-{snp}.col-{cn}.label">{label}</div>'
            f'{source_html}\n'
            f'          </div>'
        )
    ctx["cols_html"] = "\n".join(rendered)
    ctx["footnote_html"] = _optional_text_node(
        ctx.get("footnote"), snp, "footnote", classes="footnote", indent="        ")


def _enrich_stats_hero(ctx, slide):
    snp = ctx["slide_no_padded"]
    stat = ctx.get("stat", {})
    unit = stat.get("unit")
    # unit nests inside .num — no data-text-id (mixed-text-and-inline rule).
    # User edits "30万人" as one leaf via slide-NN.stat.number.
    ctx["unit_html"] = (
        f'<span class="unit">{_esc_br(unit)}</span>'
        if unit else ""
    )
    eyebrow = ctx.get("eyebrow")
    ctx["eyebrow_html"] = (
        f'            <div class="eyebrow" data-text-id="slide-{snp}.eyebrow">'
        f'{_esc_br(eyebrow)}</div>'
        if eyebrow else ""
    )


def _enrich_image_text(ctx, slide):
    snp = ctx["slide_no_padded"]
    image = ctx.get("image", {}) or {}
    src = image.get("src", "")
    position = image.get("position", "center")
    fit = image.get("fit", "cover")

    # Detect file-missing case and fall back to a brand-aligned dark gradient.
    # Resolve src relative to the deck.json file (set by main()).
    deck_dir = ctx.get("_deck_dir")
    file_exists = True
    if src and not src.startswith(("http://", "https://", "data:")):
        candidate = Path(src) if Path(src).is_absolute() else (deck_dir / src if deck_dir else Path(src))
        file_exists = candidate.is_file()

    if file_exists and src:
        ctx["bg_style"] = (
            f"background-image:url('{_esc_br(src)}');"
            f"background-size:{_esc_br(fit)};"
            f"background-position:{_esc_br(position)};"
        )
    else:
        # Fallback: dark radial gradient — placeholder that won't look broken on a projector.
        # Mimics image-text master atmosphere without needing a real photo.
        if src:
            print(f"render-deck: WARN slide[{ctx['slide_no'] - 1}] image.src '{src}' not found at "
                  f"{deck_dir / src if deck_dir else src}; falling back to gradient placeholder.",
                  file=sys.stderr)
        ctx["bg_style"] = (
            "background:"
            "radial-gradient(circle at 78% 22%, rgba(60,127,255,0.85), rgba(15,26,74,0.95) 45%, #000 100%),"
            "linear-gradient(180deg, rgba(0,0,0,0), rgba(0,0,0,0.65));"
            "background-color:#000;"
        )

    ctx["lede_html"] = _optional_text_node(
        ctx.get("lede"), snp, "lede", classes="lede")


def _enrich_table(ctx, slide):
    snp = ctx["slide_no_padded"]
    headers = ctx.get("headers") or []
    ctx["headers_html"] = "".join(
        f'<th data-text-id="slide-{snp}.head-{i+1:02d}">{_esc_br(h)}</th>'
        for i, h in enumerate(headers)
    )
    rows = ctx.get("rows") or []
    row_html = []
    for r, row in enumerate(rows, start=1):
        rn = f"{r:02d}"
        ridx = r - 1
        cells = "".join(
            f'<td data-text-id="slide-{snp}.row-{rn}.cell-{c+1:02d}">{_esc_br(cell)}</td>'
            for c, cell in enumerate(row)
        )
        row_html.append(f'              <tr>{cells}</tr>')
    ctx["rows_html"] = "\n".join(row_html)
    ctx["footnote_html"] = _optional_text_node(
        ctx.get("footnote"), snp, "footnote", classes="footnote", indent="        ")


def _enrich_logo_wall(ctx, slide):
    """logo-wall — N industries × M client logos. Logo entries are logical
    keys (e.g. '瑞幸咖啡'); enricher resolves to skill-shared assets path.

    Path resolution: uses ctx['asset_path'] (computed by main as the
    output→skill assets relative path) + '/shared/clientlogo/<key>.png'.
    Missing logo files render as empty boxes — designer responsibility to
    populate assets/shared/clientlogo/ ahead of time. We do NOT warn at
    render time (would spam stderr); a future R-LOGO-MISSING rule could.
    """
    snp = ctx["slide_no_padded"]
    asset_path = ctx.get("asset_path", "..")
    ctx["lede_html"] = _optional_text_node(
        ctx.get("lede"), snp, "lede", classes="lede", indent="          ")

    industries = ctx.get("industries") or []
    industry_blocks = []
    for ii, ind in enumerate(industries, start=1):
        i_padded = f"{ii:02d}"
        name = _esc_br(ind.get("name", ""))
        logos = ind.get("logos") or []
        logo_divs = []
        for li, key in enumerate(logos, start=1):
            # Sanitize: key is user-supplied. Forbid `/` `..` here so
            # `data.logos = ["../../etc/passwd"]` can't escape clientlogo/.
            safe_key = re.sub(r"[/\\.]+", "_", str(key)).lstrip("_") or "missing"
            src = f"{asset_path}/shared/clientlogo/{safe_key}.png"
            logo_divs.append(
                f'              <div class="logo" '
                f'data-text-id="slide-{snp}.industry-{i_padded}.logo-{li:02d}" '
                f'style="background-image:url(\'{_esc_br(src)}\')"></div>'
            )
        logos_html = "\n".join(logo_divs)
        industry_blocks.append(
            f'            <div class="industry">\n'
            f'              <span class="ind-name" '
            f'data-text-id="slide-{snp}.industry-{i_padded}.name">{name}</span>\n'
            f'              <div class="logos">\n{logos_html}\n              </div>\n'
            f'            </div>'
        )
    ctx["industries_html"] = "\n".join(industry_blocks)


def _enrich_arch_stack(ctx, slide):
    """arch-stack — N horizontal layers, each layer has a name (title+sub) and
    a row of module pills. Layer color coding cycles l1/l2/l3/l4 by index.
    Schema enforces 2-5 layers + 3-8 modules per layer."""
    snp = ctx["slide_no_padded"]
    layers = ctx.get("layers") or []
    blocks = []
    for li, layer in enumerate(layers, start=1):
        ln = f"{li:02d}"
        name = layer.get("name") or {}
        title = _esc_br(name.get("title", ""))
        sub = name.get("sub")
        # data-allow-body-floor: layer subtitle is a by-design Latin eyebrow
        # under the 28px .title (chrome, not body) — honors the CSS
        # /* allow:body-floor */ at the runtime R-VIS-BODY-FLOOR audit too.
        sub_html = (f'              <div class="sub" data-allow-body-floor data-text-id="slide-{snp}.layer-{ln}.name.sub">{_esc_br(sub)}</div>'
                    if sub else "")
        modules = layer.get("modules") or []
        modules_html = "\n".join(
            f'              <span class="m" data-text-id="slide-{snp}.layer-{ln}.module-{mi:02d}">'
            f'{_esc_br(m)}</span>'
            for mi, m in enumerate(modules, start=1)
        )
        blocks.append(
            f'          <div class="layer is-l{li}">\n'
            f'            <div class="name">\n'
            f'              <div class="title" data-text-id="slide-{snp}.layer-{ln}.name.title">{title}</div>\n'
            f'{sub_html}\n'
            f'            </div>\n'
            f'            <div class="modules">\n{modules_html}\n            </div>\n'
            f'          </div>'
        )
    ctx["layers_html"] = "\n".join(blocks)


def _enrich_flow_timeline(ctx, slide):
    snp = ctx["slide_no_padded"]
    nodes = ctx.get("nodes") or []
    if not ctx.get("cols"):
        ctx["cols"] = len(nodes)
    out = []
    for i, node in enumerate(nodes, start=1):
        nn = f"{i:02d}"
        idx = i - 1
        when = _esc_br(node.get("when", ""))
        what = _esc_br(node.get("what", ""))
        desc = node.get("desc")
        desc_html = (
            f'<div class="desc" data-text-id="slide-{snp}.node-{nn}.desc">'
            f'{_esc_br(desc)}</div>'
            if desc else ""
        )
        out.append(
            f'          <div class="node">'
            f'<div class="when" data-text-id="slide-{snp}.node-{nn}.when">{when}</div>'
            f'<div class="what" data-text-id="slide-{snp}.node-{nn}.what">{what}</div>'
            f'{desc_html}'
            f'</div>'
        )
    ctx["nodes_html"] = "\n".join(out)


def _enrich_flow_process(ctx, slide):
    snp = ctx["slide_no_padded"]
    steps = ctx.get("steps") or []
    if not ctx.get("cols"):
        ctx["cols"] = len(steps)
    out = []
    for i, step in enumerate(steps, start=1):
        sn = f"{i:02d}"
        idx = i - 1
        num = _esc_br(step.get("num", sn))
        title = _esc_br(step.get("title", ""))
        body = _esc_br(step.get("body", ""))
        out.append(
            f'          <div class="step">'
            f'<div class="stnum" data-text-id="slide-{snp}.step-{sn}.num">{num}</div>'
            f'<h3 data-text-id="slide-{snp}.step-{sn}.title">{title}</h3>'
            f'<p data-text-id="slide-{snp}.step-{sn}.body">{body}</p>'
            f'</div>'
        )
    ctx["steps_html"] = "\n".join(out)


def _enrich_content_blocks(ctx, slide):
    snp = ctx["slide_no_padded"]
    lede = ctx.get("lede")
    ctx["lede_html"] = _optional_text_node(lede, snp, "lede", classes="lede")
    # source-footer keeps a special inline style block (designer intent)
    # because the schema's "caption" class doesn't carry the right typography
    # for the muted footer treatment. Migrate to a real class in a future pass.
    footer = ctx.get("source_footer")
    ctx["source_footer_html"] = (
        f'          <p class="caption" style="margin-top:16px;font:500 16px/1.4 var(--fs-font-cjk);'
        f'color:var(--fs-text-40);letter-spacing:0.04em" '
        f'data-text-id="slide-{snp}.source-footer">'
        f'{_esc_br(footer)}</p>'
        if footer else ""
    )


def _enrich_content_matrix(ctx, slide):
    snp = ctx["slide_no_padded"]
    axes = ctx.get("axes", {}) or {}
    for ax_key in ("y", "x"):
        ax = axes.setdefault(ax_key, {})
        ax.setdefault("high_label", "HIGH")
        ax.setdefault("low_label", "LOW")
        ax.setdefault("name", "")
    ctx["axes"] = axes

    quads = ctx.get("quadrants", {}) or {}
    parts = []
    for pos in ("tl", "tr", "bl", "br"):
        q = quads.get(pos, {})
        ord_str = _esc_br(q.get("ord", ""))
        title = _esc_br(q.get("title", ""))
        items = q.get("items", [])
        items_html = "\n".join(
            f'              <li data-text-id="slide-{snp}.{pos}.item-{i+1:02d}">'
            f'{_esc_br(item)}</li>'
            for i, item in enumerate(items)
        )
        ord_html = (
            f'<span class="ord">{ord_str}</span>'
            if ord_str else ""
        )
        parts.append(
            f'          <div class="quad q-{pos}">\n'
            f'            <h3>{ord_html}<span data-text-id="slide-{snp}.{pos}.title">{title}</span></h3>\n'
            f'            <ul>\n'
            f'{items_html}\n'
            f'            </ul>\n'
            f'          </div>'
        )
    ctx["quadrants_html"] = "\n".join(parts)


def _enrich_content_before_after(ctx, slide):
    """before-after variant — 痛点 vs 飞书后,中间一个 pivot 箭头。
    Schema 保证 before.items.length === after.items.length (or close);
    if not, we still render both sides and let visual review catch it."""
    snp = ctx["slide_no_padded"]

    def _items_html(items, side: str) -> str:
        lines = []
        for i, txt in enumerate(items or [], start=1):
            ii = f"{i:02d}"
            icon = "✕" if side == "before" else "✓"
            lines.append(
                f'              <li data-text-id="slide-{snp}.{side}.item-{ii}">'
                f'<span class="icon">{icon}</span>{_esc_br(str(txt))}</li>'
            )
        return "\n".join(lines)

    before = ctx.get("before", {}) or {}
    after  = ctx.get("after",  {}) or {}
    ctx["before_items_html"] = _items_html(before.get("items"), "before")
    ctx["after_items_html"]  = _items_html(after.get("items"),  "after")

    pivot = ctx.get("pivot", {}) or {}
    ctx["pivot_caption_html"] = _optional_text_node(
        pivot.get("caption"), snp, "pivot.caption",
        tag="div", classes="caption", indent="            ")


def _enrich_content_story_case(ctx, slide):
    snp = ctx["slide_no_padded"]
    scene = ctx.get("scene", {}) or {}
    deck_dir = ctx.get("_deck_dir")
    src = scene.get("image", "")
    alt = scene.get("alt", "")
    caption = scene.get("caption", "")
    fit = scene.get("fit", "cover")
    position = scene.get("position", "center")

    # Detect missing scene image and fall back to gradient (same as image-text)
    file_exists = True
    if src and not src.startswith(("http://", "https://", "data:")):
        candidate = Path(src) if Path(src).is_absolute() else (deck_dir / src if deck_dir else Path(src))
        file_exists = candidate.is_file()

    if file_exists and src:
        bg_style = (
            f"background-image:url('{_esc_br(src)}');"
            f"background-size:{_esc_br(fit)};"
            f"background-position:{_esc_br(position)};"
        )
    else:
        if src:
            print(f"render-deck: WARN slide[{ctx['slide_no'] - 1}] scene.image '{src}' not found; "
                  f"falling back to gradient placeholder.", file=sys.stderr)
        bg_style = (
            "background:radial-gradient(circle at 50% 50%, "
            "rgba(60,127,255,0.25), rgba(15,26,74,0.85) 60%, #000 100%);"
            "background-color:#000;"
        )

    ctx["scene_html"] = (
        f'              <div class="scene-frame" role="img" '
        f'aria-label="{_esc_br(alt)}" style="{bg_style}">\n'
        f'                <span class="scene-cap" data-text-id="slide-{snp}.scene.caption">'
        f'{_esc_br(caption)}</span>\n'
        f'              </div>'
    )


def _enrich_stats_waterfall(ctx, slide):
    snp = ctx["slide_no_padded"]
    bars = ctx.get("bars", []) or []
    if not ctx.get("cols"):
        ctx["cols"] = len(bars)

    def parse_val(v):
        m = re.search(r'-?\d+(?:\.\d+)?', v or "")
        return abs(float(m.group())) if m else 0

    values = [parse_val(b.get("value", "")) for b in bars]
    max_val = max(values) if values and max(values)> 0 else 1

    parts = []
    for i, bar in enumerate(bars, start=1):
        bn = f"{i:02d}"
        idx = i - 1
        kind = bar.get("kind", "pos")
        value = _esc_br(bar.get("value", ""))
        delta = bar.get("delta")
        delta_html = (
            f'              <div class="delta" data-text-id="slide-{snp}.bar-{bn}.delta">'
            f'{_esc_br(delta)}</div>\n'
            if delta else ""
        )
        label = _esc_br(bar.get("label", ""))
        sublabel = bar.get("sublabel")
        # data-allow-body-floor: sublabel is a by-design secondary annotation
        # under the 24px .label — keep 16 to preserve the label/sublabel
        # hierarchy (bumping to 24 would flatten it). Honors the audit per-element.
        sublabel_html = (
            f'              <div class="sublabel" data-allow-body-floor data-text-id="slide-{snp}.bar-{bn}.sublabel">'
            f'{_esc_br(sublabel)}</div>\n'
            if sublabel else ""
        )
        # Bar visual heights (proportional MVP — true waterfall stacking is Phase 1.d)
        if kind == "base":
            h = 320
        elif kind == "end":
            h = 480
        else:
            h = max(40, int(values[i-1] / max_val * 380))
        parts.append(
            f'            <div class="bar is-{kind}">\n'
            f'              <div class="value" data-text-id="slide-{snp}.bar-{bn}.value">{value}</div>\n'
            f'{delta_html}'
            f'              <div class="col" style="height:{h}px"></div>\n'
            f'              <div class="label" data-text-id="slide-{snp}.bar-{bn}.label">{label}</div>\n'
            f'{sublabel_html}'
            f'            </div>'
        )
    ctx["bars_html"] = "\n".join(parts)
    ctx["footnote_html"] = _optional_text_node(
        ctx.get("footnote"), snp, "footnote", classes="footnote", indent="        ")


_CHART_TOKENS = ["var(--fs-blue)", "var(--fs-teal)", "var(--fs-violet)", "var(--fs-orange)"]
_CHART_NAMED = {"blue": "var(--fs-blue)", "teal": "var(--fs-teal)",
                "violet": "var(--fs-violet)", "orange": "var(--fs-orange)",
                "grey": "rgba(255,255,255,0.45)"}


def _chart_color(idx, override=None):
    """Series/segment color → brand token. Auto-rotates blue/teal/violet/orange
    by index; optional closed-enum override. Never free hex (stays inside R10)."""
    if override and override in _CHART_NAMED:
        return _CHART_NAMED[override]
    return _CHART_TOKENS[idx % len(_CHART_TOKENS)]


def _enrich_chart(ctx, slide):
    """layout:chart — deterministic data-viz (bar / line / donut) from numeric
    values. ALL geometry computed here at build time → inline CSS/SVG using
    brand tokens, no JS, crisp at any scale-to-fit. Author supplies values only;
    generalizes the stats/waterfall pattern into a chart family."""
    snp = ctx["slide_no_padded"]
    variant = slide.get("variant") or "bar"
    series = ctx.get("series") or []
    unit = _esc_br(ctx.get("unit", "") or "")

    def vlabel(p):
        vl = p.get("value_label")
        if vl:
            return _esc_br(str(vl))
        v = p.get("value", 0)
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        return f"{v}{unit}"

    def legend_chips(items):
        chips = "".join(
            f'<span class="cl-chip"><i style="background:{c}"></i>{_esc_br(n)}</span>'
            for c, n in items if n
        )
        return f'        <div class="chart-legend">{chips}</div>\n' if chips else ""

    chart_html = ""

    if variant == "bar":
        pts = (series[0].get("points") if series else []) or []
        color = _chart_color(0, series[0].get("color") if series else None)
        vals = [abs(float(p.get("value", 0) or 0)) for p in pts]
        mx = max(vals) if vals and max(vals) > 0 else 1
        cols = []
        for i, p in enumerate(pts):
            h = max(24, round(vals[i] / mx * 360))
            cols.append(
                f'          <div class="cbar">'
                f'<div class="cval" data-text-id="slide-{snp}.pt-{i+1:02d}.value">{vlabel(p)}</div>'
                f'<div class="ccol" style="height:{h}px;'
                f'background:linear-gradient(180deg,{color},color-mix(in srgb,{color} 30%,transparent))"></div>'
                f'<div class="clabel" data-text-id="slide-{snp}.pt-{i+1:02d}.label">{_esc_br(p.get("label",""))}</div>'
                f'</div>'
            )
        chart_html = (f'        <div class="chart chart-bar" style="--cn:{len(pts) or 1}">\n'
                      + "\n".join(cols) + "\n        </div>\n")

    elif variant == "line":
        W, H, PAD = 1000.0, 380.0, 14.0
        npts = max((len(s.get("points") or []) for s in series), default=0)
        allvals = [abs(float(p.get("value", 0) or 0)) for s in series for p in (s.get("points") or [])]
        mx = max(allvals) if allvals and max(allvals) > 0 else 1
        polylines, leg = [], []
        for si, s in enumerate(series):
            pts = s.get("points") or []
            color = _chart_color(si, s.get("color"))
            coords = []
            for i, p in enumerate(pts):
                x = PAD + (i / (npts - 1) * (W - 2 * PAD) if npts > 1 else 0)
                y = H - PAD - abs(float(p.get("value", 0) or 0)) / mx * (H - 2 * PAD)
                coords.append(f"{x:.1f},{y:.1f}")
            polylines.append(
                f'<polyline points="{" ".join(coords)}" fill="none" stroke="{color}" '
                f'stroke-width="3" vector-effect="non-scaling-stroke" '
                f'stroke-linejoin="round" stroke-linecap="round"/>')
            leg.append((color, s.get("name")))
        first = (series[0].get("points") if series else []) or []
        xlabels = "".join(
            f'<span data-text-id="slide-{snp}.x-{i+1:02d}">{_esc_br(p.get("label",""))}</span>'
            for i, p in enumerate(first))
        chart_html = (
            f'        <div class="chart chart-line">\n'
            f'          <svg class="cline-svg" viewBox="0 0 1000 380" preserveAspectRatio="none">'
            + "".join(polylines) + "</svg>\n"
            f'          <div class="cline-x">{xlabels}</div>\n'
            f'        </div>\n' + legend_chips(leg))

    elif variant == "donut":
        pts = (series[0].get("points") if series else []) or []
        vals = [abs(float(p.get("value", 0) or 0)) for p in pts]
        total = sum(vals) or 1
        R, C, SW, CIRC = 84.0, 120.0, 34.0, 2 * 3.141592653589793 * 84.0
        segs, leg, cum = [], [], 0.0
        for i, p in enumerate(pts):
            color = _chart_color(i, p.get("color"))
            seg = vals[i] / total * CIRC
            segs.append(
                f'<circle cx="{C}" cy="{C}" r="{R:.2f}" fill="none" stroke="{color}" '
                f'stroke-width="{SW}" stroke-dasharray="{seg:.2f} {CIRC - seg:.2f}" '
                f'stroke-dashoffset="{-cum:.2f}"/>')
            cum += seg
            leg.append((color, f'{_esc_br(p.get("label",""))} {round(vals[i] / total * 100)}%'))
        center = f'{round(total)}{unit}' if unit else str(round(total))
        chart_html = (
            f'        <div class="chart chart-donut">\n'
            f'          <svg class="cdonut-svg" viewBox="0 0 240 240">'
            f'<g transform="rotate(-90 120 120)">' + "".join(segs) + '</g></svg>\n'
            f'          <div class="cdonut-center">{center}</div>\n'
            f'        </div>\n' + legend_chips(leg))

    ctx["chart_html"] = chart_html
    ctx["footnote_html"] = _optional_text_node(
        ctx.get("footnote"), snp, "footnote", classes="footnote", indent="        ")


def _enrich_flow_tree(ctx, slide):
    snp = ctx["slide_no_padded"]
    root = ctx.get("root", {}) or {}
    why = root.get("why")
    # root.why may contain inline <em>...</em> — trust raw
    ctx["root_why_html"] = (
        f'            <div class="why" data-text-id="slide-{snp}.root.why">{why}</div>'
        if why else ""
    )

    branches = ctx.get("branches", []) or []
    parts = []
    for i, b in enumerate(branches, start=1):
        bn = f"{i:02d}"
        idx = i - 1
        ord_str = _esc_br(b.get("ord", ""))
        title = _esc_br(b.get("title", ""))
        leaves = b.get("leaves", [])
        leaves_html = "\n".join(
            f'              <div class="leaf" data-text-id="slide-{snp}.branch-{bn}.leaf-{j+1:02d}">'
            f'{_esc_br(leaf)}</div>'
            for j, leaf in enumerate(leaves)
        )
        ord_html = (
            f'<span class="ord">{ord_str}</span>'
            if ord_str else ""
        )
        parts.append(
            f'            <div class="branch">\n'
            f'              <div class="b1">{ord_html}<span class="t" '
            f'data-text-id="slide-{snp}.branch-{bn}.title">{title}</span></div>\n'
            f'              <div class="b1-conn"></div>\n'
            f'              <div class="leaves">\n'
            f'{leaves_html}\n'
            f'              </div>\n'
            f'            </div>'
        )
    ctx["branches_html"] = "\n".join(parts)


def _enrich_flow_swim(ctx, slide):
    """flow/swim — multi-lane roadmap. CSS grid:
       row 1 (60px) = empty | time1 | time2 | ... timeN
       rows 2..N+1 (1fr each) = lane-name | <milestones placed by quarter>
       milestones with no quarter slot → empty cell.
    The template's `.stage` declares grid-template-rows/cols dynamically via
    inline style; this enricher populates each cell.
    """
    snp = ctx["slide_no_padded"]
    time_axis = ctx.get("time_axis") or []
    lanes = ctx.get("lanes") or []
    ctx["time_axis_count"] = len(time_axis)
    ctx["lanes_count"]     = len(lanes)

    cells = []
    # Row 1: empty corner + time headers
    cells.append(f'          <div class="time-cell empty"></div>')
    for ti, tlabel in enumerate(time_axis, start=1):
        cells.append(
            f'          <div class="time-cell" '
            f'data-text-id="slide-{snp}.time-{ti:02d}">{_esc_br(tlabel)}</div>'
        )
    # Each lane: lane-name + N cells (one per quarter; empty if no milestone)
    for li, lane in enumerate(lanes, start=1):
        ln = f"{li:02d}"
        accent = lane.get("accent", "blue")
        sub = lane.get("sub")
        sub_html = (f'<span class="sub" data-text-id="slide-{snp}.lane-{ln}.sub">{_esc_br(sub)}</span>'
                    if sub else "")
        cells.append(
            f'          <div class="lane-name is-{accent}" '
            f'data-text-id="slide-{snp}.lane-{ln}.name">'
            f'{_esc_br(lane.get("name", ""))}{sub_html}'
            f'</div>'
        )
        # Build column cells, placing milestones by quarter index
        milestones_by_q = {}
        for mi, ms in enumerate(lane.get("milestones") or [], start=1):
            q = ms.get("quarter")
            if isinstance(q, int) and 1 <= q <= len(time_axis):
                milestones_by_q[q] = (mi, ms)
        for qi in range(1, len(time_axis) + 1):
            entry = milestones_by_q.get(qi)
            if entry:
                mi, ms = entry
                mn = f"{mi:02d}"
                desc = ms.get("desc")
                desc_html = (f'<div class="d" data-text-id="slide-{snp}.lane-{ln}.ms-{mn}.desc">'
                             f'{_esc_br(desc)}</div>' if desc else "")
                cells.append(
                    f'          <div><div class="ms is-{accent}">'
                    f'<div class="t" data-text-id="slide-{snp}.lane-{ln}.ms-{mn}.title">{_esc_br(ms.get("title", ""))}</div>'
                    f'{desc_html}</div></div>'
                )
            else:
                cells.append(f'          <div></div>')
    ctx["grid_html"] = "\n".join(cells)


def _enrich_replica(ctx, slide):
    # Just pass page_image as-is + escape alt
    if "alt" not in ctx or not ctx.get("alt"):
        ctx["alt"] = ""


def _enrich_iframe_embed(ctx, slide):
    # iframe_title defaults to data.title for a11y
    if not ctx.get("iframe_title"):
        ctx["iframe_title"] = ctx.get("title", "")
    # hint pill is optional — omit / empty → no pill
    hint = (ctx.get("hint") or "").strip()
    if hint:
        ctx["hint_html"] = (
            '            <div class="iframe-hint">'
            '<span class="dot"></span>'
            f'<span>{_esc_br(hint)}</span>'
            '</div>'
        )
    else:
        ctx["hint_html"] = ""
    # Optional zoom: scale iframe content while keeping it filling the container.
    # transform-origin: top-left + inverse width/height keeps the iframe flush
    # to the wrap's edges so the hint pill stays correctly positioned.
    # `+ 2px` overcompensation hides sub-pixel rounding seams on right/bottom
    # edges (otherwise the wrap's bg shows through a thin gap); the wrap's
    # overflow: hidden clips the overshoot.
    zoom = ctx.get("zoom")
    if zoom and zoom != 1.0:
        inv = 100.0 / float(zoom)
        ctx["iframe_inline_style"] = (
            f' style="transform: scale({zoom}); transform-origin: top left; '
            f'width: calc({inv:.4f}% + 2px); height: calc({inv:.4f}% + 2px);"'
        )
    else:
        ctx["iframe_inline_style"] = ""


def _enrich_raw(ctx, slide):
    # Verbatim html — template uses {{{ html }}}, no processing.
    # `_orig_layout` lets a raw slide claim a layout name so the framework
    # CSS rules (e.g. `.slide[data-layout="content-2col"] .stage`) still
    # engage. The template uses {{ effective_layout }} for the data-layout
    # attribute; we default to "raw" if no override.
    ctx["effective_layout"] = slide.get("_orig_layout") or "raw"


ENRICHERS = {
    ("cover",   None):           _enrich_cover,
    ("agenda",  None):           _enrich_agenda,
    ("section", None):           _enrich_section,
    ("content", "3up"):          _enrich_content_3up,
    ("content", "2col"):         _enrich_content_2col,
    ("content", "blocks"):       _enrich_content_blocks,
    ("content", "matrix"):       _enrich_content_matrix,
    ("content", "before-after"): _enrich_content_before_after,
    ("content", "story-case"):   _enrich_content_story_case,
    ("stats",   "row"):          _enrich_stats_row,
    ("stats",   "hero"):         _enrich_stats_hero,
    ("stats",   "waterfall"):    _enrich_stats_waterfall,
    ("chart",   "bar"):          _enrich_chart,
    ("chart",   "line"):         _enrich_chart,
    ("chart",   "donut"):        _enrich_chart,
    ("image-text", None):        _enrich_image_text,
    ("table",   None):           _enrich_table,
    ("logo-wall", None):         _enrich_logo_wall,
    ("arch-stack", None):        _enrich_arch_stack,
    ("flow",    "timeline"):     _enrich_flow_timeline,
    ("flow",    "process"):      _enrich_flow_process,
    ("flow",    "tree"):         _enrich_flow_tree,
    ("flow",    "swim"):         _enrich_flow_swim,
    ("end",     None):           _enrich_end,
    ("replica", None):           _enrich_replica,
    ("raw",     None):           _enrich_raw,
    ("iframe-embed", None):      _enrich_iframe_embed,
}


_ASSET_REF_RE = re.compile(r"(?:input|prototypes)/[^\s\"'<>()\\?#]+")


def _scan_slide_assets(slide_html: str) -> list:
    """Deck-local asset refs (input/<file>, prototypes/<slug>/...) a slide
    carries — the ones a lift must copy. Shared/framework refs resolve in any
    deck so they're not listed. Used for the slide-index.json manifest."""
    return sorted(set(_ASSET_REF_RE.findall(slide_html)))


def render_slide(slide: dict, slide_index: int, total: int, asset_path: str, deck_dir: Path | None = None) -> str:
    layout  = slide["layout"]
    variant = slide.get("variant")
    tpl_path = _resolve_template_path(layout, variant)

    data = slide.get("data", {})
    # Post-medium-6: no pre-normalization. \n → <br> happens inside _esc_br
    # at substitute time (and inside enrichers that call _esc_br directly).

    ctx = {
        **data,
        "slide_no":         slide_index + 1,
        "slide_no_padded":  f"{slide_index + 1:02d}",
        "slide_key":        slide["key"],
        "screen_label":     slide.get("screen_label") or _derive_screen_label(slide),
        "accent":           slide.get("accent", "blue"),
        "data_attrs":       _build_data_attrs(slide),
        "asset_path":       asset_path,
        "_deck_dir":        deck_dir,
    }

    # Render top-level embeddable blocks
    blocks = ctx.get("body_blocks") or []
    ctx["body_blocks_html"] = (
        "\n".join(render_block(b, asset_path) for b in blocks) if blocks else ""
    )

    # content/2col: text.body_blocks rendering
    text = ctx.get("text") or {}
    if isinstance(text, dict):
        text_blocks = text.get("body_blocks") or []
        ctx["text_body_blocks_html"] = (
            "\n".join(render_block(b, asset_path) for b in text_blocks) if text_blocks else ""
        )
        ctx["text_feature_list_html"] = _render_feature_list(text.get("feature_list"))
        ctx["text_lede"] = text.get("lede", "")

    # Apply layout-specific enricher (composes helper HTML)
    enricher = ENRICHERS.get((layout, variant))
    if enricher:
        enricher(ctx, slide)

    rendered = render_template(tpl_path.read_text(encoding="utf-8"), ctx)

    # Co-locate per-slide custom_css as a <style> scoped to the slide-key, as the
    # FIRST child of .slide (LIFT-ARCHITECTURE step 2). This gives every slide a
    # round-tripping home for its deviation CSS — no head/page-level <style> that
    # vanishes on republish — and makes the slide self-contained so a deck.json
    # paste/clone carries its styling with no CSS hunting.
    custom_css = slide.get("custom_css")
    if isinstance(custom_css, str) and custom_css.strip():
        rendered = _inject_custom_css(rendered, slide["key"], custom_css)

    return rendered


def _inject_custom_css(slide_html: str, slide_key: str, custom_css: str) -> str:
    """Insert a `<style data-slide-key=K data-fs-custom-css>` block (selectors
    scoped to the slide-key) as the first child of `.slide`. A `<style>` is
    display:none in the UA sheet so it adds no layout, and no framework rule
    targets a direct child of `.slide` positionally, so first-child is safe.
    The `data-fs-custom-css` marker lets sync-index-to-deck.py skip it on
    round-trip (it lives in the deck.json `custom_css` field, not data.html)."""
    scoped = scope_selectors(custom_css, slide_key)
    if not scoped.strip():
        return slide_html
    block = (f'<style data-slide-key="{slide_key}" data-fs-custom-css>\n'
             f'{scoped}\n'
             f'        </style>')
    # Match the `.slide` open div ALLOWING extra classes (`slide story-case`,
    # `slide page-replica`, …). `(?:\s[^"]*)?` keeps `class="slide-frame"` OUT
    # (after `slide` must come `"` or whitespace, never `-`), so the first match
    # is still the real `.slide` open. Anchoring on exact `class="slide"` used to
    # silently drop custom_css on story-case / replica slides (n=0 → no-op).
    new_html, n = re.subn(
        r'(<div class="slide(?:\s[^"]*)?"[^>]*>)',
        lambda m: m.group(0) + "\n        " + block,
        slide_html, count=1,
    )
    return new_html if n else slide_html


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="render-deck.py",
        description="Render a DeckJSON file into a complete HTML deck.",
    )
    ap.add_argument("deck",       type=Path, help="path to deck.json")
    ap.add_argument("output_dir", type=Path, help="output directory")
    ap.add_argument("--skip-validate-json", action="store_true",
                    help="skip DeckJSON schema validation (NOT recommended)")
    ap.add_argument("--skip-validate-html", action="store_true",
                    help="skip post-render HTML validator (NOT recommended)")
    ap.add_argument("--skip-fit-check", action="store_true",
                    help="skip the content/story-case schema-fit refusal "
                         "(placeholder / too-short / duplicate beat detection)")
    ap.add_argument("--skip-copy-assets", action="store_true",
                    help="skip copy-assets step — output will reference skill-relative paths "
                         "(works only while output sits in <repo>/runs/<ts>/output/)")
    ap.add_argument("--shared", choices=["link", "copy", "skip"], default="link",
                    help="copy-assets mode for shared/* files (default link, see SKILL.md)")
    ap.add_argument("--inline", action="store_true",
                    help="single-file delivery mode — base64-inline all CSS/JS/images. "
                         "Mutually exclusive with copy-assets (auto-skips it).")
    ap.add_argument("--visual", action="store_true",
                    help="run Playwright visual audits after render (R-OVERFLOW / "
                         "R-OVERLAP / R-VIS-TIER / R-VIS-LABEL-FLOOR). Adds ~5-10s. "
                         "Requires `pip install playwright && python -m playwright install chromium`.")
    ap.add_argument("--renumber", action="store_true",
                    help="rewrite each slide's screen_label leading number to its TRUE "
                         "frame_index (post-_disabled-skip), persisted back to deck.json "
                         "(auto-backup .bak-pre-renumber-<ts>). Fixes stale labels after "
                         "lift/insert/reorder so the library label number matches the "
                         "on-screen page number / URL hash (#N).")
    args = ap.parse_args(argv)

    if args.inline and not args.skip_copy_assets:
        # --inline supersedes copy-assets
        args.skip_copy_assets = True

    # 1. Validate deck.json against schema
    if not args.skip_validate_json:
        rc = subprocess.run(
            [sys.executable, str(VALIDATE_DECK), str(args.deck), "--strict"],
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            print("render-deck: deck.json failed schema validation:", file=sys.stderr)
            print(rc.stdout, file=sys.stderr)
            if rc.stderr.strip():
                print(rc.stderr, file=sys.stderr)
            return 2

    # 2. Load deck
    try:
        deck = json.loads(args.deck.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"render-deck: deck file not found: {args.deck}", file=sys.stderr); return 2
    except json.JSONDecodeError as e:
        print(f"render-deck: invalid JSON: {e}", file=sys.stderr); return 2

    # 2.5 content/story-case schema-fit refusal (ported from retired render.py).
    # Schema enforces field presence; this catches placeholder / too-short /
    # duplicate beats. Opt out with --skip-fit-check.
    if not args.skip_fit_check:
        fit_issues = []
        for i, s in enumerate(deck.get("slides", [])):
            if (s.get("layout") == "content" and s.get("variant") == "story-case"
                    and not s.get("_disabled")):
                for msg in check_story_case_fit(s.get("data", {})):
                    fit_issues.append(f"  slide[{i}] key='{s.get('key')}' · {msg}")
        if fit_issues:
            print("render-deck: content/story-case 内容撑不起 schema (schema-fit refusal):",
                  file=sys.stderr)
            print("\n".join(fit_issues), file=sys.stderr)
            print("  → 改 deck.json 把这些 beat 写实,或换 layout(别硬塞)。"
                  "确认有意为之就加 --skip-fit-check。", file=sys.stderr)
            return 4

    # 3. Setup output dir
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    asset_path = relpath_from_to(args.output_dir, ASSETS_DIR)

    # 4. Render each slide
    # Skip slides with `_disabled: true` (escape hatch for "this slide errors,
    # let the rest of the deck render so I can keep working"). SKILL.md
    # promises this; the renderer must honor it. Skipped slides don't count
    # toward `total` (page numbers stay sane).
    active_slides = [(i, s) for i, s in enumerate(deck["slides"])
                     if not s.get("_disabled")]
    n_skipped = len(deck["slides"]) - len(active_slides)
    if n_skipped > 0:
        print(f"  ⚠ skipped {n_skipped} slide(s) marked _disabled: true",
              file=sys.stderr)
    slides_html = []
    total = len(active_slides)
    deck_dir = args.deck.resolve().parent

    # --renumber: canonicalize every active slide's screen_label leading number
    # to its true frame_index, BEFORE render (so the emitted data-screen-label +
    # slide-index.json both follow), and persist back to deck.json with a backup.
    if getattr(args, "renumber", False):
        import time
        changes = []
        for new_idx, (orig_idx, slide) in enumerate(active_slides):
            old = slide.get("screen_label") or _derive_screen_label(slide)
            new = _renumber_label(slide, new_idx + 1)
            slide["screen_label"] = new          # mutates deck["slides"][orig_idx]
            if new != old:
                changes.append((new_idx + 1, old, new))
        if changes:
            ts = time.strftime("%Y%m%d-%H%M%S")
            bak = args.deck.with_name(args.deck.name + f".bak-pre-renumber-{ts}")
            bak.write_text(args.deck.read_text(encoding="utf-8"), encoding="utf-8")
            args.deck.write_text(
                json.dumps(deck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"  ↻ renumbered {len(changes)} screen_label(s) → frame_index "
                  f"(backup: {bak.name})", file=sys.stderr)
            for fi, old, new in changes[:8]:
                print(f"      #{fi}: '{old}' → '{new}'", file=sys.stderr)
            if len(changes) > 8:
                print(f"      … +{len(changes) - 8} more", file=sys.stderr)
        else:
            print("  ↻ --renumber: all screen_labels already match frame_index",
                  file=sys.stderr)

    for new_idx, (orig_idx, slide) in enumerate(active_slides):
        try:
            # Pass NEW index (post-skip) for page-number continuity, but include
            # original index in error context for debugging.
            slide_html = render_slide(slide, new_idx, total, asset_path, deck_dir=deck_dir)
        except SystemExit as e:
            raise SystemExit(
                f"slide[{orig_idx}] key='{slide.get('key')}' "
                f"layout='{slide.get('layout')}': {e}"
            )
        slides_html.append(slide_html)

    # 5. Compose into shell
    shell_tpl = TEMPLATES_DIR / "_shell.html"
    if not shell_tpl.exists():
        print(f"render-deck: shell template missing: {shell_tpl}", file=sys.stderr); return 2

    # Path to deck-json/templates/ (for extra-layouts.css link)
    templates_path = relpath_from_to(args.output_dir, TEMPLATES_DIR)

    # Conditionally link feishu-deck-patterns.css only when any slide needs it
    # (content/story-case is the only Phase 1.c layout that depends on it).
    needs_patterns = any(
        s.get("layout") == "content" and s.get("variant") == "story-case"
        for s in deck["slides"]
    )
    patterns_css_link = (
        f'  <link rel="stylesheet" href="{asset_path}/feishu-deck-patterns.css">'
        if needs_patterns else ""
    )

    # Compose data-* attrs for the <div class="deck"> element. title_style /
    # logo_position are deck-wide defaults; CSS scopes engage via
    # .deck[data-title-style="X"] / .deck[data-logo-position="Y"]. Per-slide
    # overrides emit on the .slide element instead (handled in render_slide).
    deck_data_attrs_parts = []
    if deck["deck"].get("title_style"):
        deck_data_attrs_parts.append(f' data-title-style="{deck["deck"]["title_style"]}"')
    if deck["deck"].get("logo_position"):
        deck_data_attrs_parts.append(f' data-logo-position="{deck["deck"]["logo_position"]}"')
    deck_data_attrs = "".join(deck_data_attrs_parts)

    final = render_template(shell_tpl.read_text(encoding="utf-8"), {
        "title":                      deck["deck"]["title"],
        "asset_path":                 asset_path,
        "deck_json_templates_path":   templates_path,
        "patterns_css_link":          patterns_css_link,
        "language":                   deck["deck"].get("language", "zh-only"),
        "slides_html":                "\n".join(slides_html),
        "deck_data_attrs":            deck_data_attrs,
    })

    out_html = args.output_dir / "index.html"
    out_html.write_text(final, encoding="utf-8")

    # 5.4 — Emit slide-index.json: a compact {key→frame_index,layout,label,bytes,
    #       assets} manifest so a downstream "lift" can pick a slide by semantic
    #       key from a ~300-token table instead of reading the whole index.html
    #       to find a frame number (LIFT-ARCHITECTURE L4).
    slide_index = {
        "version": "1.0",
        "deck": deck["deck"].get("title", ""),
        "slides": [
            {
                "key":         slide.get("key"),
                "frame_index": new_idx + 1,
                "layout":      slide.get("layout"),
                "variant":     slide.get("variant"),
                "label":       slide.get("screen_label") or _derive_screen_label(slide),
                "bytes":       len(slides_html[new_idx]),
                "assets":      _scan_slide_assets(slides_html[new_idx]),
            }
            for new_idx, (orig_idx, slide) in enumerate(active_slides)
        ],
    }
    (args.output_dir / "slide-index.json").write_text(
        json.dumps(slide_index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # 6. HTML validator gate
    if not args.skip_validate_html:
        # If --visual, run validate.py WITHOUT --no-visual so Playwright audits
        # (R-OVERFLOW / R-OVERLAP / R-VIS-TIER / R-VIS-LABEL-FLOOR) fire.
        # Otherwise default behaviour: static checks only.
        validate_cmd = [sys.executable, str(VALIDATE_HTML), str(out_html)]
        if not args.visual:
            validate_cmd.append("--no-visual")
        rc = subprocess.run(validate_cmd, capture_output=True, text=True)
        # Always show validator output (digest is helpful)
        print(rc.stdout)
        if rc.returncode != 0:
            print(file=sys.stderr)
            print("render-deck: rendered HTML failed validate.py — fix the TEMPLATE that produced the bad slide, not the output.", file=sys.stderr)
            if rc.stderr.strip():
                print(rc.stderr, file=sys.stderr)
            return 4

    # 7. Post-render asset handling — choose one of:
    #    (a) --inline: base64-inline CSS/JS/images into the HTML (single-file)
    #    (b) copy-assets: rewrite skill-relative paths to local ./assets/ and
    #        copy referenced files (default — makes output self-contained for
    #        zip/move/share)
    #    (c) --skip-copy-assets: leave skill-relative paths (works only inside
    #        the repo's runs/<ts>/output/ structure)
    if args.inline:
        inline_html(out_html, deck)
        print(f"\nOK  →  {out_html}  (inline single-file mode)")
    elif not args.skip_copy_assets:
        # copy-assets.py requires output under <repo>/runs/<ts>/output/
        # (SKILL.md WORKSPACE LAYOUT). For other paths (smoke tests in /tmp/),
        # skip with warning rather than fatal-fail.
        if "/runs/" not in str(args.output_dir.resolve()):
            # FOOTGUN WARNING — output paths reference the skill via relative
            # paths that only resolve inside the repo. Moving / emailing this
            # HTML will break all CSS / JS / images. Use --inline for portable
            # output, OR ALWAYS create output under <repo>/runs/<ts>/output/
            # per the WORKSPACE LAYOUT convention.
            print(file=sys.stderr)
            print(f"  ⚠⚠⚠  WARNING — copy-assets skipped  ⚠⚠⚠", file=sys.stderr)
            print(f"  Output dir is not under <repo>/runs/<ts>/output/:", file=sys.stderr)
            print(f"    {args.output_dir.resolve()}", file=sys.stderr)
            print(f"  The HTML's CSS/JS/image refs use skill-RELATIVE paths.", file=sys.stderr)
            print(f"  They resolve ONLY while served from inside the repo tree.", file=sys.stderr)
            print(f"  Moving / emailing this HTML will produce a broken deck.", file=sys.stderr)
            print(f"  Fix options:", file=sys.stderr)
            print(f"    · Re-run with --inline for a single-file portable deck, OR", file=sys.stderr)
            print(f"    · Output under <repo>/runs/<ts>/output/ so assets get copied", file=sys.stderr)
            print(file=sys.stderr)
            print(f"\nOK  →  {out_html}  (linked mode, skill-relative paths · NOT PORTABLE)")
        else:
            rc = subprocess.run(
                [sys.executable, str(COPY_ASSETS), str(args.output_dir),
                 f"--shared={args.shared}"],
                capture_output=True, text=True,
            )
            if rc.returncode != 0:
                print("render-deck: copy-assets.py failed:", file=sys.stderr)
                print(rc.stdout, file=sys.stderr)
                print(rc.stderr, file=sys.stderr)
                return 5
            print(f"\nOK  →  {out_html}  (linked mode + local assets/)")
    else:
        print(f"\nOK  →  {out_html}  (linked mode, skill-relative paths)")

    print(f"       deck:   {deck['deck']['title']}")
    print(f"       slides: {total}")

    # Accent review — for any content/story-case slide, print the highlighted
    # word so the author can eyeball that the right pivot is emphasized.
    sc_slides = [s for s in deck.get("slides", [])
                 if s.get("layout") == "content" and s.get("variant") == "story-case"
                 and not s.get("_disabled")]
    if sc_slides:
        print("\nACCENT 复核 (1 秒目测,被高亮的词是该突出的吗?)")
        for s in sc_slides:
            show_story_case_accents(s.get("data", {}), s.get("key", "?"))
    return 0


def inline_html(out_html: Path, deck: dict) -> None:
    """Phase 1.d --inline implementation. Replaces external <link>/<script>
    references with inlined <style>/<script> blocks. Also base64-encodes
    referenced images. Adds <meta name=\"fs-deck-mode\" content=\"inline\">
    so the HTML validator skips the P50 base64 budget warn."""
    import base64, mimetypes

    html_text = out_html.read_text(encoding="utf-8")

    def _inline_stylesheet(m):
        href = m.group(1)
        css_path = (out_html.parent / href).resolve()
        if not css_path.is_file():
            return m.group(0)  # leave as-is if not findable
        css = css_path.read_text(encoding='utf-8')
        # Inline the CSS's OWN url() refs (e.g. `--fs-asset-cover-bg:
        # url("lark-cover-bg.jpg")`) resolved against the STYLESHEET's dir —
        # they are relative to the CSS file, NOT to out_html, so the later
        # out_html-relative background-image pass never finds them and the
        # "portable single-file" deck would lose its cover/section/content
        # backgrounds + Lark logo the moment it's moved. `_resolve_bg` keeps
        # http/data/missing refs untouched.
        css = re.sub(
            r"""url\(\s*['"]?([^'")]+)['"]?\s*\)""",
            lambda u: f"url({_resolve_bg(css_path, u.group(1))})",
            css,
        )
        return f"<style>{css}</style>"

    def _inline_script(m):
        src = m.group(1)
        js_path = (out_html.parent / src).resolve()
        if not js_path.is_file():
            return m.group(0)
        return f"<script>{js_path.read_text(encoding='utf-8')}</script>"

    # Order matters: stylesheet first (cheap), then script, then bg images
    html_text = re.sub(
        r'<link\s+rel="stylesheet"\s+href="([^"]+)"\s*/?>',
        _inline_stylesheet, html_text,
    )
    html_text = re.sub(
        r'<script\b[^>]*?\bsrc="([^"]+)"[^>]*></script>',
        _inline_script, html_text,
    )
    # bg images: handle url('...') and url("...")
    html_text = re.sub(
        r"(background-image\s*:\s*url\()'([^']+)'(\))",
        lambda m: f"{m.group(1)}{_resolve_bg(out_html, m.group(2))}{m.group(3)}",
        html_text,
    )
    html_text = re.sub(
        r'(background-image\s*:\s*url\()"([^"]+)"(\))',
        lambda m: f"{m.group(1)}{_resolve_bg(out_html, m.group(2))}{m.group(3)}",
        html_text,
    )

    # Add fs-deck-mode=inline meta (skips P50 base64 budget). Check for the
    # exact meta tag, not the bare string — feishu-deck.js inlines a
    # `const MODE_KEY = 'fs-deck-mode'` constant that matches a naive search.
    if '<meta name="fs-deck-mode"' not in html_text:
        html_text = html_text.replace(
            '<meta name="fs-language"',
            '<meta name="fs-deck-mode" content="inline">\n  <meta name="fs-language"',
            1,
        )

    out_html.write_text(html_text, encoding="utf-8")


def _resolve_bg(out_html: Path, url: str) -> str:
    """Resolve a background-image url() to data: URI if local file exists."""
    import base64, mimetypes
    if url.startswith(("http://", "https://", "data:")):
        return f"'{url}'"
    img_path = (out_html.parent / url).resolve()
    if not img_path.is_file():
        return f"'{url}'"
    mime, _ = mimetypes.guess_type(str(img_path))
    if not mime:
        mime = "image/png"
    b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")
    return f"'data:{mime};base64,{b64}'"


if __name__ == "__main__":
    sys.exit(main())
