#!/usr/bin/env python3
"""
build_pptx.py · PPTX → feishu-deck-h5 deck.json → HTML

Native PowerPoint (.pptx) importer. Walks every slide with python-pptx and
reconstructs each slide as absolutely-positioned HTML on a 1920×1080 canvas,
emitting a `layout:"raw"` deck.json that the user's *own* feishu-deck-h5
renderer (deck-json/render-deck.py) turns into a present-mode HTML deck.

This is the PowerPoint analogue of rollingai-decks' keynote-to-html skill —
but with no AppleScript and no Keynote: .pptx is open OOXML, so python-pptx
reads exact element geometry (EMU), text runs (font / size / color / b / i),
images, tables and groups directly, cross-platform.

Element handling (v0.1):
  · background      slide background solid fill → .slide background
  · picture         <img> at bbox (object-fit: fill to match PPT stretch)
  · text frame      real <div>/<span> with per-run font/size/color/weight,
                    paragraph alignment + vertical anchor + bullets
  · auto shape      solid-fill → background div (+ border, + corner radius)
  · table           <table> with cell text + fills + borders
  · group           recursively flattened through the group's child transform
  · rotation        CSS transform: rotate()

Lossy / fallback (use --raster to recover the visual for these):
  · charts / SmartArt / gradient- or picture-filled shapes / freeform / WordArt
    → cropped from a LibreOffice-rasterized page PNG and embedded as <img>.
  · --full-raster makes EVERY slide a single full-bleed PNG (pixel-perfect,
    zero editability) — a guaranteed-fidelity baseline.

Usage:
  build_pptx.py <in.pptx> <out-dir>
       [--renderer DIR]   feishu-deck-h5 skill root
                          (default: ~/.claude/skills/feishu-deck-h5)
       [--limit N]        only first N slides
       [--raster]         per-element raster fallback for unhandled elements
       [--full-raster]    every slide = one full-bleed rasterized PNG
       [--inline]         single-file output (base64-inline everything)
       [--title TEXT]     deck title
"""
from __future__ import annotations

import argparse
import base64
import html as html_lib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from pptx import Presentation
from pptx.util import Emu
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.enum.dml import MSO_THEME_COLOR
from pptx.oxml.ns import qn

# ── canvas ──────────────────────────────────────────────────────────────────
SLIDE_W, SLIDE_H = 1920, 1080
EMU_PER_PT = 12700

# NOTE: font names use SINGLE quotes — these strings are emitted inside a
# double-quoted style="" attribute, and nested double quotes would truncate
# the attribute (silently dropping every declaration after font-family,
# e.g. color/font-weight → text falls back to the inherited default).
DEFAULT_FONT_STACK = (
    "'PingFang SC','Microsoft YaHei','Source Han Sans SC',"
    "'Helvetica Neue',Arial,sans-serif"
)


# ── affine transform (EMU→EMU), used to flatten nested groups ────────────────
class Xf:
    """Maps a shape's container-local EMU coords to absolute slide EMU."""

    def __init__(self, ox=0.0, oy=0.0, sx=1.0, sy=1.0):
        self.ox, self.oy, self.sx, self.sy = ox, oy, sx, sy

    def x(self, v):  return self.ox + v * self.sx
    def y(self, v):  return self.oy + v * self.sy
    def w(self, v):  return v * self.sx
    def h(self, v):  return v * self.sy

    def enter_group(self, grp) -> "Xf":
        """Return the child transform for a GroupShape `grp`."""
        # group's own box, mapped to absolute slide EMU through *this* xf
        gx, gy = self.x(grp.left), self.y(grp.top)
        gw, gh = self.w(grp.width), self.h(grp.height)
        # child coordinate space (a:chOff / a:chExt)
        cox = coy = 0.0
        cex = grp.width or 1
        cey = grp.height or 1
        xfrm = grp._element.find(qn("p:grpSpPr"))
        if xfrm is not None:
            xfrm = xfrm.find(qn("a:xfrm"))
        if xfrm is not None:
            ch_off = xfrm.find(qn("a:chOff"))
            ch_ext = xfrm.find(qn("a:chExt"))
            if ch_off is not None:
                cox = float(ch_off.get("x", 0)); coy = float(ch_off.get("y", 0))
            if ch_ext is not None:
                cex = float(ch_ext.get("cx", 1)) or 1
                cey = float(ch_ext.get("cy", 1)) or 1
        sx = gw / cex
        sy = gh / cey
        return Xf(gx - cox * sx, gy - coy * sy, sx, sy)


# ── theme-color resolution ────────────────────────────────────────────────────
# Populated once per presentation in main(): MSO_THEME_COLOR member → "#RRGGBB".
# Without this, scheme-colored text (the deck author's "tx1/lt1/accent1") has no
# .rgb and falls back to a guessed default → light text on dark cards goes dark.
_THEME: dict = {}
# parallel map keyed by the raw schemeClr val string ("accent1","lt1","tx1"…),
# for resolving colors inside gradient stops / XML we read by hand.
_THEME_BY_NAME: dict = {}

# clrScheme child tag → theme-color enum members it backs (incl. the tx/bg
# aliases that the master's clrMap maps to dk/lt by default).
_SCHEME_TAGS = [
    ("dk1", [MSO_THEME_COLOR.DARK_1, MSO_THEME_COLOR.TEXT_1]),
    ("lt1", [MSO_THEME_COLOR.LIGHT_1, MSO_THEME_COLOR.BACKGROUND_1]),
    ("dk2", [MSO_THEME_COLOR.DARK_2, MSO_THEME_COLOR.TEXT_2]),
    ("lt2", [MSO_THEME_COLOR.LIGHT_2, MSO_THEME_COLOR.BACKGROUND_2]),
    ("accent1", [MSO_THEME_COLOR.ACCENT_1]),
    ("accent2", [MSO_THEME_COLOR.ACCENT_2]),
    ("accent3", [MSO_THEME_COLOR.ACCENT_3]),
    ("accent4", [MSO_THEME_COLOR.ACCENT_4]),
    ("accent5", [MSO_THEME_COLOR.ACCENT_5]),
    ("accent6", [MSO_THEME_COLOR.ACCENT_6]),
    ("hlink", [MSO_THEME_COLOR.HYPERLINK]),
    ("folHlink", [MSO_THEME_COLOR.FOLLOWED_HYPERLINK]),
]


def _clr_to_hex(node) -> Optional[str]:
    """Read a hex from a clrScheme child (<a:srgbClr> or <a:sysClr lastClr>)."""
    srgb = node.find(qn("a:srgbClr"))
    if srgb is not None and srgb.get("val"):
        return f"#{srgb.get('val')}"
    sysc = node.find(qn("a:sysClr"))
    if sysc is not None and sysc.get("lastClr"):
        return f"#{sysc.get('lastClr')}"
    return None


def build_theme_map(prs) -> dict:
    """Map theme-color members → hex from the first master's theme clrScheme."""
    from lxml import etree
    out: dict = {}
    try:
        master = prs.slide_masters[0]
        theme_part = None
        for rel in master.part.rels.values():
            if "theme" in rel.reltype:
                theme_part = rel.target_part
                break
        if theme_part is None:
            return out
        # the theme is a generic Part (no ._element) — parse its blob
        root = etree.fromstring(theme_part.blob)
        clr_scheme = root.find(f".//{qn('a:clrScheme')}")
        if clr_scheme is None:
            return out
        for tag, members in _SCHEME_TAGS:
            node = clr_scheme.find(qn(f"a:{tag}"))
            if node is None:
                continue
            hexc = _clr_to_hex(node)
            if hexc:
                for m in members:
                    out[m] = hexc
                _THEME_BY_NAME[tag] = hexc
        # tx/bg aliases default-mapped to dk/lt (master clrMap default)
        for alias, base in (("tx1", "dk1"), ("bg1", "lt1"),
                            ("tx2", "dk2"), ("bg2", "lt2")):
            if base in _THEME_BY_NAME:
                _THEME_BY_NAME[alias] = _THEME_BY_NAME[base]
    except Exception:
        pass
    return out


def _scheme_name_hex(val: str) -> Optional[str]:
    """Resolve a raw schemeClr val ('accent1','lt1','tx1','bg1'…) to hex."""
    return _THEME_BY_NAME.get(val)


def _xml_color_hex(node) -> Optional[str]:
    """Resolve a DrawingML color child (<a:srgbClr>/<a:schemeClr>/<a:sysClr>)."""
    srgb = node.find(qn("a:srgbClr"))
    if srgb is not None and srgb.get("val"):
        return f"#{srgb.get('val')}"
    sysc = node.find(qn("a:sysClr"))
    if sysc is not None and sysc.get("lastClr"):
        return f"#{sysc.get('lastClr')}"
    sch = node.find(qn("a:schemeClr"))
    if sch is not None and sch.get("val"):
        return _scheme_name_hex(sch.get("val"))
    return None


def gradient_css(shape) -> Optional[str]:
    """Parse a shape's <a:gradFill> into a CSS linear-gradient(), or None."""
    try:
        sp_pr = shape._element.find(qn("p:spPr"))
        if sp_pr is None:
            return None
        grad = sp_pr.find(qn("a:gradFill"))
        if grad is None:
            return None
        gs_lst = grad.find(qn("a:gsLst"))
        if gs_lst is None:
            return None
        stops = []
        for gs in gs_lst.findall(qn("a:gs")):
            col = _xml_color_hex(gs)
            if col:
                stops.append((int(gs.get("pos", "0")) / 1000.0, col))
        if len(stops) < 2:
            return None
        # angle: PPT <a:lin ang> is 1/60000 deg clockwise from East (3 o'clock).
        # CSS linear-gradient 0deg = "to top"; convert via (ppt + 90) mod 360.
        ang_css = "to bottom"
        lin = grad.find(qn("a:lin"))
        if lin is not None and lin.get("ang") is not None:
            ang = (int(lin.get("ang")) / 60000.0 + 90) % 360
            ang_css = f"{ang:.0f}deg"
        stop_str = ", ".join(f"{c} {p:.0f}%" for p, c in stops)
        return f"linear-gradient({ang_css}, {stop_str})"
    except Exception:
        return None


# ── color helpers ─────────────────────────────────────────────────────────────
def rgb_hex(color) -> Optional[str]:
    """Best-effort RGB hex from a python-pptx ColorFormat. None if unresolved.
    Resolves scheme/theme colors via the presentation theme map (_THEME)."""
    try:
        if color is None or color.type is None:
            return None
        # explicit RGB → direct (getattr swallows the AttributeError that
        # .rgb raises for non-RGB color types)
        rgb = getattr(color, "rgb", None)
        if rgb is not None:
            return f"#{str(rgb)}"
        # scheme/theme color → look up resolved hex
        tc = getattr(color, "theme_color", None)
        if tc is not None and tc in _THEME:
            return _THEME[tc]
    except Exception:
        return None
    return None


def fill_hex(fill) -> Optional[str]:
    """Safe solid-fill hex. Returns None for no-fill / gradient / picture /
    pattern / unresolved — never raises (python-pptx raises on .fore_color
    for non-solid fills)."""
    try:
        from pptx.enum.dml import MSO_FILL
        if fill is not None and fill.type == MSO_FILL.SOLID:
            return rgb_hex(fill.fore_color)
    except Exception:
        return None
    return None


def emu(v) -> float:
    return float(v) if v is not None else 0.0


# ── geometry → px ─────────────────────────────────────────────────────────────
class Canvas:
    """Uniform scale + center offset from slide EMU into 1920×1080 px."""

    def __init__(self, slide_w_emu: int, slide_h_emu: int):
        self.scale = min(SLIDE_W / slide_w_emu, SLIDE_H / slide_h_emu)
        self.off_x = (SLIDE_W - slide_w_emu * self.scale) / 2
        self.off_y = (SLIDE_H - slide_h_emu * self.scale) / 2

    def px_left(self, emu_x):  return emu_x * self.scale + self.off_x
    def px_top(self, emu_y):   return emu_y * self.scale + self.off_y
    def px_size(self, emu_d):  return emu_d * self.scale
    def pt_to_px(self, pt):    return pt * EMU_PER_PT * self.scale


# ── text rendering ────────────────────────────────────────────────────────────
_ALIGN = {
    PP_ALIGN.LEFT: "left", PP_ALIGN.CENTER: "center",
    PP_ALIGN.RIGHT: "right", PP_ALIGN.JUSTIFY: "justify",
}
_ANCHOR = {
    MSO_ANCHOR.TOP: "flex-start", MSO_ANCHOR.MIDDLE: "center",
    MSO_ANCHOR.BOTTOM: "flex-end",
}


def _para_has_bullet(p) -> Optional[str]:
    """Return a bullet marker string if the paragraph is bulleted, else None."""
    pPr = p._p.find(qn("a:pPr"))
    if pPr is None:
        return None
    if pPr.find(qn("a:buNone")) is not None:
        return None
    if pPr.find(qn("a:buChar")) is not None:
        ch = pPr.find(qn("a:buChar")).get("char", "•")
        return ch
    if pPr.find(qn("a:buAutoNum")) is not None:
        return "•"  # numbered → approximate; v0 doesn't track the counter
    return None


def _run_span(r, cv: Canvas) -> str:
    """Render one _Run as a styled <span>, or '' if empty."""
    txt = html_lib.escape(r.text).replace("\n", "<br>")
    if not txt:
        return ""
    styles = []
    sz = r.font.size
    if sz is not None:
        styles.append(f"font-size:{cv.px_size(int(sz)):.1f}px")
    name = r.font.name
    if name:
        styles.append(f"font-family:'{name}',{DEFAULT_FONT_STACK}")
    col = rgb_hex(r.font.color)
    if col:
        styles.append(f"color:{col}")
    if r.font.bold:
        styles.append("font-weight:700")
    if r.font.italic:
        styles.append("font-style:italic")
    if r.font.underline:
        styles.append("text-decoration:underline")
    return f'<span style="{";".join(styles)}">{txt}</span>'


def render_text_frame(shape, cv: Canvas, default_color: str) -> str:
    from pptx.text.text import _Run
    tf = shape.text_frame
    anchor = _ANCHOR.get(tf.vertical_anchor, "flex-start")
    blocks = []
    for p in tf.paragraphs:
        align = _ALIGN.get(p.alignment, "left")
        bullet = _para_has_bullet(p)
        indent = (p.level or 0) * 1.4  # em
        # paragraph font size = first run that declares one (bullet inherits it)
        para_px = next((cv.px_size(int(r.font.size)) for r in p.runs
                        if r.font.size is not None), None)
        # Walk children in document order so soft line breaks <a:br/> (which
        # are NOT runs and are absent from p.runs) and fields <a:fld> render in
        # place. Iterating p.runs alone collapses multi-line titles onto one line.
        runs_html = []
        for child in p._p:
            tag = child.tag
            if tag == qn("a:r"):
                runs_html.append(_run_span(_Run(child, p), cv))
            elif tag == qn("a:br"):
                runs_html.append("<br>")
            elif tag == qn("a:fld"):  # slide number / date field → its cached text
                t = child.find(qn("a:t"))
                if t is not None and t.text:
                    runs_html.append(f"<span>{html_lib.escape(t.text)}</span>")
        inner = "".join(runs_html)
        if not inner:
            inner = "<br>"
        ls = p.line_spacing
        ls_css = ""
        if isinstance(ls, float):
            ls_css = f"line-height:{ls};"
        prefix = f'<span style="opacity:.85;margin-right:.4em">{html_lib.escape(bullet)}</span>' if bullet else ""
        size_css = f"font-size:{para_px:.1f}px;" if para_px else ""
        blocks.append(
            f'<div style="text-align:{align};{ls_css}{size_css}'
            f'padding-left:{indent:.1f}em;margin:0">{prefix}{inner}</div>'
        )
    body = "".join(blocks)
    # vertical anchoring via flex
    return (
        f'<div style="display:flex;flex-direction:column;'
        f'justify-content:{anchor};width:100%;height:100%;'
        f'color:{default_color};box-sizing:border-box">{body}</div>'
    )


# ── shape fill / border → CSS ─────────────────────────────────────────────────
def shape_box_css(shape) -> tuple[str, bool]:
    """Return (css, is_solid). is_solid False means the fill is something we
    can't reproduce (gradient / picture / pattern) → caller may raster-fall-back."""
    css = []
    is_solid = False
    try:
        fill = shape.fill
        if fill.type is not None:
            from pptx.enum.dml import MSO_FILL
            if fill.type == MSO_FILL.SOLID:
                hexc = rgb_hex(fill.fore_color)
                if hexc:
                    css.append(f"background-color:{hexc}")
                    is_solid = True
            elif fill.type == MSO_FILL.GRADIENT:
                grad = gradient_css(shape)
                if grad:
                    css.append(f"background:{grad}")
                    is_solid = True  # reproduced in CSS → no raster needed
            elif fill.type in (MSO_FILL.PICTURE, MSO_FILL.PATTERNED):
                is_solid = False  # needs raster
    except Exception:
        pass
    # border
    try:
        ln = shape.line
        if ln.width is not None and int(ln.width) > 0:
            lc = rgb_hex(ln.color) or "#888"
            css.append(f"border:{max(1, int(ln.width)/EMU_PER_PT):.0f}px solid {lc}")
    except Exception:
        pass
    # corner radius for rounded rectangles
    try:
        if shape.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE:
            from pptx.enum.shapes import MSO_SHAPE
            if shape.auto_shape_type == MSO_SHAPE.ROUNDED_RECTANGLE:
                css.append("border-radius:14px")
            elif shape.auto_shape_type in (MSO_SHAPE.OVAL,):
                css.append("border-radius:50%")
    except Exception:
        pass
    return ";".join(css), is_solid


def _transform(rotation: float) -> str:
    if rotation and abs(rotation) > 0.01:
        return f"transform:rotate({rotation:.2f}deg) !important;"
    return ""


def pos_style(cv: Canvas, xf: Xf, shape) -> str:
    l = cv.px_left(xf.x(emu(shape.left)))
    t = cv.px_top(xf.y(emu(shape.top)))
    w = cv.px_size(xf.w(emu(shape.width)))
    h = cv.px_size(xf.h(emu(shape.height)))
    return (f"left:{l:.1f}px;top:{t:.1f}px;width:{w:.1f}px;height:{h:.1f}px;"
            f"{_transform(getattr(shape, 'rotation', 0) or 0)}")


# ── table ─────────────────────────────────────────────────────────────────────
def render_table(shape, cv: Canvas, xf: Xf) -> str:
    tbl = shape.table
    rows_html = []
    for row in tbl.rows:
        cells = []
        for cell in row.cells:
            txt = html_lib.escape(cell.text).replace("\n", "<br>")
            fill = fill_hex(cell.fill)
            bg = f"background:{fill};" if fill else ""
            cells.append(
                f'<td style="border:1px solid rgba(255,255,255,.25);'
                f'padding:6px 10px;{bg}">{txt}</td>'
            )
        rows_html.append(f"<tr>{''.join(cells)}</tr>")
    return (
        f'<div class="el" style="{pos_style(cv, xf, shape)}">'
        f'<table style="width:100%;height:100%;border-collapse:collapse;'
        f'font-size:{cv.pt_to_px(14):.0f}px">{"".join(rows_html)}</table></div>'
    )


def render_line(shape, cv: Canvas, xf: Xf) -> str:
    """Render a LINE / connector as an SVG line (handles diagonal + flips)."""
    l = cv.px_left(xf.x(emu(shape.left)))
    t = cv.px_top(xf.y(emu(shape.top)))
    w = max(cv.px_size(xf.w(emu(shape.width))), 1.0)
    h = max(cv.px_size(xf.h(emu(shape.height))), 1.0)
    color, sw = None, 1.0
    try:
        color = rgb_hex(shape.line.color)
        if shape.line.width:
            sw = max(1.0, int(shape.line.width) * cv.scale)
    except Exception:
        pass
    color = color or "#8895AA"
    xfrm = shape._element.find(f".//{qn('a:xfrm')}")
    flip_h = xfrm is not None and xfrm.get("flipH") == "1"
    flip_v = xfrm is not None and xfrm.get("flipV") == "1"
    x1, y1, x2, y2 = (w if flip_h else 0), (h if flip_v else 0), \
                     (0 if flip_h else w), (0 if flip_v else h)
    return (
        f'<svg class="el" style="left:{l:.1f}px;top:{t:.1f}px;'
        f'width:{w:.1f}px;height:{h:.1f}px;overflow:visible" '
        f'viewBox="0 0 {w:.1f} {h:.1f}" preserveAspectRatio="none">'
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="{color}" stroke-width="{sw:.1f}"/></svg>'
    )


# ── per-shape dispatch ────────────────────────────────────────────────────────
def emit_shape(shape, cv: Canvas, xf: Xf, slide_assets: Path, assets_rel: str,
               img_counter: list, default_text_color: str,
               raster_flags: list) -> list[str]:
    """Return list of HTML fragments for one shape (groups → many)."""
    out: list[str] = []
    st = shape.shape_type

    # GROUP → recurse with composed transform
    if st == MSO_SHAPE_TYPE.GROUP:
        child_xf = xf.enter_group(shape)
        for child in shape.shapes:
            out += emit_shape(child, cv, child_xf, slide_assets, assets_rel,
                              img_counter, default_text_color, raster_flags)
        return out

    # PICTURE
    if st == MSO_SHAPE_TYPE.PICTURE:
        try:
            img = shape.image
            img_counter[0] += 1
            ext = img.ext or "png"
            fname = f"img-{img_counter[0]:03d}.{ext}"
            (slide_assets / fname).write_bytes(img.blob)
            rel = f"{assets_rel}/{fname}"
            out.append(
                f'<img class="el" src="{html_lib.escape(rel)}" '
                f'style="{pos_style(cv, xf, shape)}object-fit:fill" '
                f'alt="">'
            )
            return out
        except Exception:
            raster_flags.append((shape, xf, "picture-failed"))
            return out

    # LINE / connector
    if st == MSO_SHAPE_TYPE.LINE:
        out.append(render_line(shape, cv, xf))
        return out

    # MEDIA (video/audio) → poster frame if available, else a play placeholder
    if st == MSO_SHAPE_TYPE.MEDIA:
        try:
            img = shape.image  # the poster/cover frame, when present
            img_counter[0] += 1
            ext = img.ext or "png"
            fname = f"media-{img_counter[0]:03d}.{ext}"
            (slide_assets / fname).write_bytes(img.blob)
            rel = f"{assets_rel}/{fname}"
            out.append(
                f'<img class="el" src="{html_lib.escape(rel)}" '
                f'style="{pos_style(cv, xf, shape)}object-fit:cover" alt="">')
        except Exception:
            out.append(
                f'<div class="el shape" style="{pos_style(cv, xf, shape)}'
                f'background:#0B0F18;display:flex;align-items:center;'
                f'justify-content:center;color:#fff;font-size:48px">▶</div>')
        return out

    # TABLE
    if shape.has_table:
        out.append(render_table(shape, cv, xf))
        return out

    # CHART / SmartArt / OLE → graphic frame we can't structurally render
    if st in (MSO_SHAPE_TYPE.CHART, MSO_SHAPE_TYPE.DIAGRAM,
              MSO_SHAPE_TYPE.EMBEDDED_OLE_OBJECT,
              MSO_SHAPE_TYPE.LINKED_OLE_OBJECT):
        raster_flags.append((shape, xf, "graphic-frame"))
        return out

    # AUTO SHAPE / TEXT BOX / PLACEHOLDER
    box_css, is_solid = shape_box_css(shape)
    has_text = shape.has_text_frame and shape.text_frame.text.strip()

    # shape with an unreproducible fill (gradient/picture) and no text → raster
    if box_css == "" and not is_solid and not has_text \
            and st not in (MSO_SHAPE_TYPE.TEXT_BOX, MSO_SHAPE_TYPE.PLACEHOLDER):
        # could be a decorative gradient/freeform/line — recover via raster
        raster_flags.append((shape, xf, "shape-no-css"))
        return out

    inner = render_text_frame(shape, cv, default_text_color) if has_text else ""
    out.append(
        f'<div class="el shape" style="{pos_style(cv, xf, shape)}'
        f'{box_css}">{inner}</div>'
    )
    return out


# ── raster fallback (LibreOffice → PDF → PyMuPDF crop) ────────────────────────
class Raster:
    def __init__(self, pptx_path: Path, out_dir: Path, enabled: bool):
        self.enabled = enabled
        self.pptx = pptx_path
        self.out_dir = out_dir
        self.doc = None
        self.pdf = None

    def _ensure_pdf(self) -> bool:
        if self.doc is not None:
            return True
        soffice = (shutil.which("soffice")
                   or "/Applications/LibreOffice.app/Contents/MacOS/soffice")
        if not Path(soffice).exists() and shutil.which("soffice") is None:
            print("    ⚠ raster fallback needs LibreOffice (soffice) — skipping",
                  file=sys.stderr)
            return False
        tmp = self.out_dir / "_raster"
        tmp.mkdir(exist_ok=True)
        try:
            subprocess.run([soffice, "--headless", "--convert-to", "pdf",
                            "--outdir", str(tmp), str(self.pptx)],
                           check=True, capture_output=True, timeout=180)
        except Exception as e:
            print(f"    ⚠ LibreOffice convert failed: {e}", file=sys.stderr)
            return False
        pdf = tmp / (self.pptx.stem + ".pdf")
        if not pdf.exists():
            return False
        import fitz
        self.doc = fitz.open(str(pdf))
        return True

    def page_png(self, slide_idx: int, slide_assets: Path, assets_rel: str
                 ) -> Optional[str]:
        """Full-slide PNG (1-based render of slide_idx, 0-based)."""
        if not self._ensure_pdf() or slide_idx >= len(self.doc):
            return None
        import fitz
        page = self.doc[slide_idx]
        zoom_x = SLIDE_W / page.rect.width
        zoom_y = SLIDE_H / page.rect.height
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom_x, zoom_y), alpha=False)
        fname = f"page-{slide_idx + 1:03d}.png"
        pix.save(str(slide_assets / fname))
        return f"{assets_rel}/{fname}"

    def crop(self, slide_idx: int, l, t, w, h, slide_assets: Path,
             assets_rel: str, tag: str) -> Optional[str]:
        """Crop the px bbox (already in 1920×1080 space) from the rasterized page."""
        if not self._ensure_pdf() or slide_idx >= len(self.doc):
            return None
        import fitz
        page = self.doc[slide_idx]
        zoom_x = SLIDE_W / page.rect.width
        zoom_y = SLIDE_H / page.rect.height
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom_x, zoom_y), alpha=True)
        from PIL import Image
        im = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)
        box = (max(0, int(l)), max(0, int(t)),
               min(pix.width, int(l + w)), min(pix.height, int(t + h)))
        if box[2] <= box[0] or box[3] <= box[1]:
            return None
        crop = im.crop(box)
        fname = f"raster-{slide_idx + 1:03d}-{tag}.png"
        crop.save(str(slide_assets / fname))
        return f"{assets_rel}/{fname}"


# ── slide background ──────────────────────────────────────────────────────────
def slide_bg(slide, prs) -> str:
    """Resolve a background color from slide → layout → master. Default #FFF."""
    from pptx.enum.dml import MSO_FILL
    for src in (slide, slide.slide_layout, slide.slide_layout.slide_master):
        try:
            bg = src.background
            if bg.fill.type == MSO_FILL.SOLID:
                hexc = rgb_hex(bg.fill.fore_color)
                if hexc:
                    return hexc
        except Exception:
            continue
    return "#FFFFFF"


def _emit_bg_picture(container, slide_assets: Path, assets_rel: str,
                     tagname: str, img_counter: list) -> Optional[str]:
    """If a slide/layout/master has a `<p:bg>` PICTURE fill, extract the image
    and return a full-bleed <img>. The cover's designed background lives here
    (in the layout/master), NOT in the slide's own shapes — miss it and the
    deck renders on a blank background."""
    try:
        el = container._element
        bg = el.find(f".//{qn('p:bg')}")
        if bg is None:
            return None
        blip = bg.find(f".//{qn('a:blip')}")
        if blip is None:
            return None
        embed = blip.get(qn("r:embed"))
        if not embed:
            return None
        part = container.part.related_part(embed)
        ext = str(part.partname).rsplit(".", 1)[-1] or "png"
        img_counter[0] += 1
        fname = f"bg-{tagname}-{img_counter[0]:03d}.{ext}"
        (slide_assets / fname).write_bytes(part.blob)
        rel = f"{assets_rel}/{fname}"
        return (f'<img class="el" src="{html_lib.escape(rel)}" '
                f'style="left:0;top:0;width:{SLIDE_W}px;height:{SLIDE_H}px;'
                f'object-fit:cover">')
    except Exception:
        return None


# placeholder prompt text on layout/master that must NOT render as content
_PROMPT_RE = re.compile(
    r"单击此处|單擊此處|请输入|請輸入|点击.*编辑|按一下.*編輯|母版|母版文本样式|"
    r"Click to edit|XXXX|公司职称|人名$|^\s*第.*页\s*$"
)


def emit_template_shapes(container, cv: Canvas, slide_assets: Path,
                         assets_rel: str, img_counter: list,
                         default_text_color: str, raster_flags: list) -> list:
    """Emit a layout/master's own shapes (decorative pictures, logos, footers)
    UNDER the slide content. Skip placeholders (template prompts) and any
    leftover prompt text — those are authoring hints, not real content."""
    out: list = []
    xf = Xf()
    for sh in container.shapes:
        try:
            if sh.is_placeholder:
                continue
            if sh.has_text_frame and _PROMPT_RE.search(sh.text_frame.text or ""):
                continue
        except Exception:
            pass
        out += emit_shape(sh, cv, xf, slide_assets, assets_rel,
                          img_counter, default_text_color, raster_flags)
    return out


def compose_slide(slide, idx: int, cv: Canvas, prs, out_dir: Path,
                  raster: Raster, full_raster: bool) -> str:
    key = f"slide-{idx + 1:03d}"
    assets_rel = f"assets/{key}"
    slide_assets = out_dir / assets_rel
    slide_assets.mkdir(parents=True, exist_ok=True)

    bg = slide_bg(slide, prs)
    # heuristic text color: dark bg → light text default
    def _lum(hx):
        hx = hx.lstrip("#")
        if len(hx) != 6:
            return 255
        r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
        return 0.299 * r + 0.587 * g + 0.114 * b
    default_text_color = "#111" if _lum(bg) > 140 else "#F5F5F5"

    parts = [
        "<style>",
        f".slide[data-slide-key='{key}'] {{ background:{bg}; overflow:hidden; }}",
        f".slide[data-slide-key='{key}'] .el {{ position:absolute; transform-origin:center center; }}",
        f".slide[data-slide-key='{key}'] .shape {{ box-sizing:border-box; }}",
        # neutralize feishu-deck-h5's stagger-reveal so our layout shows verbatim
        (f".slide[data-slide-key='{key}'].slide > * {{ "
         f"animation:none !important; transform:none !important; opacity:1; }}"),
        f".slide[data-slide-key='{key}'] > img.el {{ z-index:0; }}",
        f".slide[data-slide-key='{key}'] > div.el,"
        f".slide[data-slide-key='{key}'] > svg.el {{ z-index:10; }}",
        "</style>",
    ]

    if full_raster:
        png = raster.page_png(idx, slide_assets, assets_rel)
        if png:
            parts.append(
                f'<img class="el" src="{html_lib.escape(png)}" '
                f'style="left:0;top:0;width:{SLIDE_W}px;height:{SLIDE_H}px;'
                f'object-fit:fill">')
            return "\n".join(parts)
        # fall through to structural if raster unavailable

    img_counter = [0]
    raster_flags: list = []
    xf = Xf()

    # TEMPLATE LAYER (drawn UNDER slide content): the layout/master carry the
    # deck's designed background image + decorative graphics + logo. python-pptx
    # slide.shapes does NOT include them, so render them here, master→layout
    # order, before the slide's own shapes.
    layout = slide.slide_layout
    master = layout.slide_master
    for cont, tg in ((master, "master"), (layout, "layout")):
        bgimg = _emit_bg_picture(cont, slide_assets, assets_rel, tg, img_counter)
        if bgimg:
            parts.append(bgimg)
        parts += emit_template_shapes(cont, cv, slide_assets, assets_rel,
                                      img_counter, default_text_color, raster_flags)

    for shape in slide.shapes:
        parts += emit_shape(shape, cv, xf, slide_assets, assets_rel,
                            img_counter, default_text_color, raster_flags)

    # recover flagged elements via per-element raster crop
    for shape, sxf, tag in raster_flags:
        l = cv.px_left(sxf.x(emu(shape.left)))
        t = cv.px_top(sxf.y(emu(shape.top)))
        w = cv.px_size(sxf.w(emu(shape.width)))
        h = cv.px_size(sxf.h(emu(shape.height)))
        rel = raster.crop(idx, l, t, w, h, slide_assets, assets_rel,
                          f"{int(l)}x{int(t)}") if raster.enabled else None
        if rel:
            parts.append(
                f'<img class="el" src="{html_lib.escape(rel)}" '
                f'style="left:{l:.1f}px;top:{t:.1f}px;width:{w:.1f}px;'
                f'height:{h:.1f}px;object-fit:fill" data-fallback="{tag}">')
    return "\n".join(parts)


def _default_renderer() -> Path:
    """Locate the feishu-deck-h5 renderer. This is a SUB-skill nested inside
    the feishu-deck-h5 skill (.../feishu-deck-h5/pptx-to-html/assets/), so the
    renderer is the grandparent dir. Fall back to ~/.claude/skills/feishu-deck-h5."""
    parent_skill = Path(__file__).resolve().parent.parent.parent  # → feishu-deck-h5/
    if (parent_skill / "deck-json/render-deck.py").is_file():
        return parent_skill
    return Path.home() / ".claude/skills/feishu-deck-h5"


# ── main ──────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="PPTX → feishu-deck-h5 HTML deck")
    ap.add_argument("pptx", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--renderer", type=Path, default=_default_renderer())
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--raster", action="store_true")
    ap.add_argument("--full-raster", action="store_true")
    ap.add_argument("--inline", action="store_true")
    ap.add_argument("--title", default=None)
    args = ap.parse_args(argv)

    if not args.pptx.is_file():
        print(f"ERROR: pptx not found: {args.pptx}", file=sys.stderr)
        return 1
    render_script = args.renderer / "deck-json/render-deck.py"
    if not render_script.is_file():
        print(f"ERROR: render-deck.py not at {render_script}", file=sys.stderr)
        return 1

    args.out_dir.mkdir(parents=True, exist_ok=True)
    prs = Presentation(str(args.pptx))
    global _THEME
    _THEME = build_theme_map(prs)
    print(f"==> theme colors resolved: {len(_THEME)} members")
    cv = Canvas(prs.slide_width, prs.slide_height)
    raster = Raster(args.pptx, args.out_dir, args.raster or args.full_raster)

    print(f"==> {args.pptx.name}: {len(prs.slides)} slides, "
          f"canvas scale={cv.scale:.4f}")
    deck_slides = []
    for idx, slide in enumerate(prs.slides):
        if args.limit and idx >= args.limit:
            break
        html_body = compose_slide(slide, idx, cv, prs, args.out_dir,
                                  raster, args.full_raster)
        deck_slides.append({
            "key": f"slide-{idx + 1:03d}",
            "layout": "raw",
            "screen_label": f"{idx + 1:02d}",
            "data": {"html": html_body},
        })
        print(f"  · slide {idx + 1:2d}  ←  {len(slide.shapes)} shapes")

    deck = {
        "version": "1.0",
        "deck": {
            "title": args.title or args.pptx.stem,
            "language": "zh-only",
            "mode": "rewrite",
        },
        "slides": deck_slides,
    }
    deck_path = args.out_dir / "deck.json"
    deck_path.write_text(json.dumps(deck, ensure_ascii=False, indent=2))
    print(f"==> wrote {deck_path}  ({len(deck_slides)} slides)")

    cmd = [sys.executable, str(render_script), str(deck_path), str(args.out_dir),
           "--skip-validate-html", "--skip-texts", "--skip-fit-check"]
    if args.inline:
        cmd.append("--inline")
    print(f"==> rendering via {render_script}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("RENDER FAILED:", file=sys.stderr)
        print(res.stdout, file=sys.stderr)
        print(res.stderr, file=sys.stderr)
        return 1
    for line in (res.stdout.strip().splitlines() or [""])[-6:]:
        print(f"    {line}")

    # serve helper
    serve = args.out_dir / "serve.sh"
    serve.write_text(
        '#!/usr/bin/env bash\nset -e\ncd "$(dirname "$0")"\n'
        'PORT="${1:-8765}"\n'
        'echo "==> http://localhost:$PORT/index.html"\n'
        'python3 -m http.server "$PORT"\n')
    serve.chmod(0o755)
    print(f"\n==> DONE → {args.out_dir / 'index.html'}")
    print(f"    preview: bash {serve}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
