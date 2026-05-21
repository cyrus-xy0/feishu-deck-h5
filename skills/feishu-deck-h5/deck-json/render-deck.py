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
EXTRACT_TEXTS = ASSETS_DIR / "extract-texts.py"
COPY_ASSETS   = ASSETS_DIR / "copy-assets.py"

# Phase 4 / post-review-medium-6: there's now ONE pathway for \n→<br>.
# Every {{ field }} substitution goes through _esc_br (see render_template
# sub_safe). Templates use {{ title }} not {{{ title }}}, so user text gets
# both HTML-escaped AND newline-converted in one safe pass — no separate
# BR_FIELDS pre-walk needed. Use {{{ raw }}} only when the renderer/enricher
# itself built trusted HTML (e.g. enricher-composed `cards_html`).


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

def get_path(d, dotted: str):
    cur = d
    for k in dotted.split("."):
        if not isinstance(cur, dict) or k not in cur:
            raise KeyError(dotted)
        cur = cur[k]
    return cur


def relpath_from_to(src_dir: Path, dst_dir: Path) -> str:
    return os.path.relpath(dst_dir, start=src_dir).replace(os.sep, "/")


def render_template(template: str, data: dict) -> str:
    """Substitute placeholders in `template`.

    Syntax:
      {{{ field }}}  raw   — value substituted as-is (use for known HTML)
      {{ field }}    safe  — value HTML-escaped (default)

    Raw substitutions run first so they're not double-processed.
    Supports dotted paths: {{ scene.caption }}.
    """
    def sub_raw(m):
        path = m.group(1).strip()
        try:
            return str(get_path(data, path))
        except KeyError:
            raise SystemExit(f"render-deck: template references missing field {{{{{{ {path} }}}}}}")
    template = re.sub(r"\{\{\{\s*([\w.]+)\s*\}\}\}", sub_raw, template)

    def sub_safe(m):
        path = m.group(1).strip()
        try:
            value = get_path(data, path)
        except KeyError:
            raise SystemExit(f"render-deck: template references missing field {{{{ {path} }}}}")
        return _esc_br(str(value))
    return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", sub_safe, template)


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


def _build_data_attrs(slide: dict) -> str:
    """Compose data-accent + data-decor + data-variant attribute strings.
    Variant is NOT emitted on .slide (production decks use class modifiers,
    per Phase 0.1 survey); it's only used JSON-side for template dispatch."""
    parts = []
    if slide.get("accent"):
        parts.append(f'data-accent="{_esc_br(slide["accent"])}"')
    decor = slide.get("decor", [])
    if decor:
        parts.append(f'data-decor="{_esc_br(" ".join(decor))}"')
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


BLOCK_ENRICHERS = {
    "pullquote":      _enrich_pullquote,
    "cta-box":        _enrich_cta_box,
    "kpi-strip":      _enrich_kpi_strip,
    "data-panel":     _enrich_data_panel,
    "verdict-grid":   _enrich_verdict_grid,
    "phone-iframe":   _enrich_phone_iframe,
    "principle-band": _enrich_principle_band,
}


def render_block(block: dict) -> str:
    """Render an embeddable block by its type field."""
    block_type = block.get("type")
    if not block_type:
        raise SystemExit(f"render-deck: block missing 'type' field: {block!r}")
    tpl_path = BLOCKS_DIR / f"{block_type}.fragment.html"
    if not tpl_path.exists():
        raise SystemExit(
            f"render-deck: no template for block type='{block_type}' (expected {tpl_path}). "
            f"Phase 1.a covers: pullquote, kpi-strip, cta-box, data-panel."
        )
    # Run enricher to populate _html / _modifier fields
    enricher = BLOCK_ENRICHERS.get(block_type)
    block_ctx = dict(block)  # don't mutate caller's dict
    if enricher:
        enricher(block_ctx)
    return render_template(tpl_path.read_text(encoding="utf-8"), block_ctx)


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
}


def _render_icon(icon, default_svg=None):
    """Icon ref → inline SVG string. Accepts named (from ICON_LIB) or {svg: ...}."""
    if isinstance(icon, dict) and "svg" in icon:
        return icon["svg"]
    if isinstance(icon, str) and icon in ICON_LIB:
        paths = ICON_LIB[icon]
        return (f'<svg viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" '
                f'fill="none" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')
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
    subtitle = ctx.get("subtitle")
    if subtitle:
        ctx["subtitle_html"] = (
            f'          <p class="subtitle" data-text-id="slide-{ctx["slide_no_padded"]}.subtitle">'
            f'{_esc_br(subtitle)}</p>'
        )
    else:
        ctx["subtitle_html"] = ""


def _enrich_agenda(ctx, slide):
    items = ctx.get("items", [])
    ctx["agenda_items_html"] = render_agenda_items(items, ctx["slide_no_padded"])
    # header is optional (v2 default hides header — pills speak for themselves)
    title = ctx.get("title")
    if title:
        ctx["header_html"] = (
            f'        <div class="header">\n'
            f'          <h2 class="title-zh" data-text-id="slide-{ctx["slide_no_padded"]}.title">'
            f'{_esc_br(title)}</h2>\n'
            f'        </div>'
        )
    else:
        ctx["header_html"] = ""


def _enrich_content_3up(ctx, slide):
    cards = ctx.get("cards", [])
    ctx["cards_html"] = render_3up_cards(cards, ctx["slide_no_padded"])
    lede = ctx.get("lede")
    if lede:
        ctx["lede_html"] = (
            f'          <p class="lede" data-text-id="slide-{ctx["slide_no_padded"]}.lede">'
            f'{_esc_br(lede)}</p>'
        )
    else:
        ctx["lede_html"] = ""


def _enrich_content_2col(ctx, slide):
    text = ctx.get("text", {}) or {}
    text_lede = text.get("lede")
    if text_lede:
        ctx["text_lede_html"] = (
            f'              <p class="lede" data-text-id="slide-{ctx["slide_no_padded"]}.text.lede">'
            f'{_esc_br(text_lede)}</p>'
        )
    else:
        ctx["text_lede_html"] = ""

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
        style = f'min-height:{fit}px;' if fit else ""
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
    contact = ctx.get("contact")
    if contact:
        ctx["contact_html"] = (
            f'        <div class="contact" data-text-id="slide-{ctx["slide_no_padded"]}.contact">'
            f'{_esc_br(contact)}</div>'
        )
    else:
        ctx["contact_html"] = ""


def _enrich_section(ctx, slide):
    lede = ctx.get("lede")
    if lede:
        ctx["lede_html"] = (
            f'        <p class="lede" data-text-id="slide-{ctx["slide_no_padded"]}.lede">'
            f'{_esc_br(lede)}</p>'
        )
    else:
        ctx["lede_html"] = ""

    pills = ctx.get("pills") or []
    if pills:
        items = "\n".join(
            f'          <span class="pill" data-text-id="slide-{ctx["slide_no_padded"]}.pill-{i+1:02d}">'
            f'{_esc_br(p)}</span>'
            for i, p in enumerate(pills)
        )
        ctx["pills_html"] = (
            f'        <div class="pills">\n'
            f'{items}\n        </div>'
        )
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

    footnote = ctx.get("footnote")
    ctx["footnote_html"] = (
        f'        <p class="footnote" data-text-id="slide-{snp}.footnote">'
        f'{_esc_br(footnote)}</p>'
        if footnote else ""
    )


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
            f"background-image:url('{src}');"
            f"background-size:{fit};"
            f"background-position:{position};"
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

    lede = ctx.get("lede")
    ctx["lede_html"] = (
        f'          <p class="lede" data-text-id="slide-{snp}.lede">'
        f'{_esc_br(lede)}</p>'
        if lede else ""
    )


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
    footnote = ctx.get("footnote")
    ctx["footnote_html"] = (
        f'        <p class="footnote" data-text-id="slide-{snp}.footnote">'
        f'{_esc_br(footnote)}</p>'
        if footnote else ""
    )


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
    ctx["lede_html"] = (
        f'          <p class="lede" data-text-id="slide-{snp}.lede">'
        f'{_esc_br(lede)}</p>'
        if lede else ""
    )
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
            f"background-image:url('{src}');"
            f"background-size:{fit};"
            f"background-position:{position};"
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
        sublabel_html = (
            f'              <div class="sublabel" data-text-id="slide-{snp}.bar-{bn}.sublabel">'
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

    footnote = ctx.get("footnote")
    ctx["footnote_html"] = (
        f'        <p class="footnote" data-text-id="slide-{snp}.footnote">'
        f'{_esc_br(footnote)}</p>'
        if footnote else ""
    )


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


def _enrich_replica(ctx, slide):
    # Just pass page_image as-is + escape alt
    if "alt" not in ctx or not ctx.get("alt"):
        ctx["alt"] = ""


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
    ("content", "story-case"):   _enrich_content_story_case,
    ("stats",   "row"):          _enrich_stats_row,
    ("stats",   "hero"):         _enrich_stats_hero,
    ("stats",   "waterfall"):    _enrich_stats_waterfall,
    ("image-text", None):        _enrich_image_text,
    ("table",   None):           _enrich_table,
    ("flow",    "timeline"):     _enrich_flow_timeline,
    ("flow",    "process"):      _enrich_flow_process,
    ("flow",    "tree"):         _enrich_flow_tree,
    ("end",     None):           _enrich_end,
    ("replica", None):           _enrich_replica,
    ("raw",     None):           _enrich_raw,
}


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
        "\n".join(render_block(b) for b in blocks) if blocks else ""
    )

    # content/2col: text.body_blocks rendering
    text = ctx.get("text") or {}
    if isinstance(text, dict):
        text_blocks = text.get("body_blocks") or []
        ctx["text_body_blocks_html"] = (
            "\n".join(render_block(b) for b in text_blocks) if text_blocks else ""
        )
        ctx["text_feature_list_html"] = _render_feature_list(text.get("feature_list"))
        ctx["text_lede"] = text.get("lede", "")

    # Apply layout-specific enricher (composes helper HTML)
    enricher = ENRICHERS.get((layout, variant))
    if enricher:
        enricher(ctx, slide)

    return render_template(tpl_path.read_text(encoding="utf-8"), ctx)


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
    ap.add_argument("--skip-texts", action="store_true",
                    help="skip texts.md sidecar generation (NOT recommended)")
    ap.add_argument("--skip-copy-assets", action="store_true",
                    help="skip copy-assets step — output will reference skill-relative paths "
                         "(works only while output sits in <repo>/runs/<ts>/output/)")
    ap.add_argument("--shared", choices=["link", "copy", "skip"], default="link",
                    help="copy-assets mode for shared/* files (default link, see SKILL.md)")
    ap.add_argument("--inline", action="store_true",
                    help="single-file delivery mode — base64-inline all CSS/JS/images. "
                         "Mutually exclusive with copy-assets (auto-skips it).")
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

    final = render_template(shell_tpl.read_text(encoding="utf-8"), {
        "title":                      deck["deck"]["title"],
        "asset_path":                 asset_path,
        "deck_json_templates_path":   templates_path,
        "patterns_css_link":          patterns_css_link,
        "language":                   deck["deck"].get("language", "zh-only"),
        "slides_html":                "\n".join(slides_html),
    })

    out_html = args.output_dir / "index.html"
    out_html.write_text(final, encoding="utf-8")

    # 5.5 — Generate texts.md sidecar (kills T03 warning, lets users edit copy
    #       without touching HTML markup).
    if not args.skip_texts:
        rc = subprocess.run(
            [sys.executable, str(EXTRACT_TEXTS), str(out_html),
             "--out", str(args.output_dir / "texts.md")],
            capture_output=True, text=True,
        )
        if rc.returncode != 0:
            print(f"render-deck: extract-texts.py failed (non-fatal): {rc.stderr.strip()}",
                  file=sys.stderr)

    # 6. HTML validator gate
    if not args.skip_validate_html:
        rc = subprocess.run(
            [sys.executable, str(VALIDATE_HTML), str(out_html), "--no-visual"],
            capture_output=True, text=True,
        )
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
    if not args.skip_texts:
        print(f"       sidecar: texts.md")
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
        return f"<style>{css_path.read_text(encoding='utf-8')}</style>"

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
        r'<script\s+src="([^"]+)"></script>',
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
