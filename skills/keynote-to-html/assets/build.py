#!/usr/bin/env python3
"""
keynote-to-html · build.py

读取 extract.applescript 输出的 TSV，按 .key bundle 的 Data/ 目录解析图片
引用，为每一页拼出绝对定位的 HTML，写出 DeckJSON 格式的 deck.json，再调用
渲染器的 render-deck.py 产出自包含的 HTML deck。

主要能力：
  · 逐元素绝对定位（x, y, w, h, 旋转, 透明度）。
  · 图片 / 视频 / 形状 / 线条 / 文本 / 群组渲染。
  · 母版与 base-layout 元素渲染在该页元素之**下**（与 Keynote 绘制顺序一致）。
  · 多 run 文本（同一文本框内逐字符的字体 / 字号 / 颜色变化）输出为内联 `<span>`。
  · 资源解析：兼容老的目录形式 .key bundle 与 Keynote 14.5+ 的单文件 zip
    格式（含 UTF-8 文件名 quirks）。
  · 视频自动取首帧 jpg poster。
  · Lazy-video 标记（`preload="none"` + `class="lazy-video"` + `data-src=...`），
    多视频 deck 也不会撑爆浏览器的解码器槽位。
  · 基于 IWA 的确定性资产解析（需安装 keynote-parser）—— 恢复 AppleScript
    拿不到的真实 bbox / 资产 stem / 段落对齐。
  · 光栅兜底：对无法结构化重建的元素（图表、表格、矢量线、渐变填充形状）
    从每页 PNG / PDF 页面裁出对应区域。

用法：
  python3 build.py <extract.tsv> <key-bundle-path> <output-dir> \
      [--limit N] [--renderer PATH] [--rasters-dir DIR] [--pdf PATH]

如果 --rasters-dir / --pdf 都未提供，则不做光栅兜底（未处理元素会以可见的
占位符形式渲染出来）。
"""
from __future__ import annotations

import argparse
import base64
import html as html_lib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("ERROR: PyMuPDF not installed. Run: pip3 install PyMuPDF")

try:
    from PIL import Image
except ImportError:
    sys.exit("ERROR: Pillow not installed. Run: pip3 install Pillow")

# Local module: IWA-based deterministic asset resolution (see iwa_resolver.py).
# Optional — if keynote-parser isn't installed, we fall back to the heuristic
# AssetResolver alone.
try:
    from iwa_resolver import IWAAssetMap
    _IWA_AVAILABLE = True
except Exception:
    IWAAssetMap = None  # type: ignore
    _IWA_AVAILABLE = False


# ----------------------------------------------------------------------------
# Data model
# ----------------------------------------------------------------------------

@dataclass
class Element:
    type: str          # image / text / movie / shape / table / chart / group / other:*
    x: float
    y: float
    w: float
    h: float
    rotation: float = 0
    file_name: str = ""
    font: str = ""
    font_size: float = 0
    r: int = 0
    g: int = 0
    b: int = 0
    fill_r: int = 0
    fill_g: int = 0
    fill_b: int = 0
    corner_radius: float = 0
    opacity: float = 100  # 0–100 (Keynote convention)
    is_master: bool = False  # True if extracted from the slide's base layout (master)
    text: str = ""
    # Per-run styling (only populated when extract emitted RUN records — i.e.
    # text has non-uniform fonts/sizes/colors). Each run is a dict:
    # {"text": str, "font": str, "size": float, "r": int, "g": int, "b": int}
    runs: list = field(default_factory=list)

    @property
    def text_color_hex(self) -> str:
        return _kn_rgb_to_hex(self.r, self.g, self.b)

    @property
    def fill_color_hex(self) -> str:
        # Treat sentinel (-1) as no fill — emit transparent for safety
        if self.fill_r < 0:
            return "transparent"
        return _kn_rgb_to_hex(self.fill_r, self.fill_g, self.fill_b)

    @property
    def fill_color_rgba(self) -> str:
        """Returns rgba() with alpha from gamma-corrected opacity. transparent if no fill."""
        if self.fill_r < 0:
            return "transparent"
        a = self.css_opacity
        return f"rgba({int(self.fill_r * 255 / 65535)},{int(self.fill_g * 255 / 65535)},{int(self.fill_b * 255 / 65535)},{a:.3f})"

    @property
    def has_fill(self) -> bool:
        return self.fill_r >= 0

    @property
    def is_translucent(self) -> bool:
        return self.opacity < 99.5

    @property
    def css_opacity(self) -> float:
        """Opacity for CSS. Identity mapping (authored opacity / 100) once
        feishu's stagger-reveal animation is disabled (see compose_slide_html
        for the override). Pixel-measured against Keynote PDF export and the
        identity is a close match — no gamma correction needed."""
        if self.opacity >= 99.5:
            return 1.0
        return max(0.0, min(1.0, self.opacity / 100.0))


def _kn_rgb_to_hex(r: int, g: int, b: int) -> str:
    """Keynote color (0–65535 per channel) → #RRGGBB."""
    return "#{:02X}{:02X}{:02X}".format(
        max(0, min(255, int(r * 255 / 65535))) if r else 0,
        max(0, min(255, int(g * 255 / 65535))) if g else 0,
        max(0, min(255, int(b * 255 / 65535))) if b else 0,
    )


@dataclass
class Slide:
    keynote_no: int
    skipped: bool
    bg_r: int = 0
    bg_g: int = 0
    bg_b: int = 0
    elements: list[Element] = field(default_factory=list)

    @property
    def bg_hex(self) -> str:
        return _kn_rgb_to_hex(self.bg_r, self.bg_g, self.bg_b)

    @property
    def has_bg_color(self) -> bool:
        return (self.bg_r + self.bg_g + self.bg_b) > 0


# ----------------------------------------------------------------------------
# TSV parsing
# ----------------------------------------------------------------------------

def parse_tsv(tsv_path: Path) -> tuple[int, list[Slide]]:
    total = 0
    slides: list[Slide] = []
    current: Optional[Slide] = None

    for line in tsv_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        head = parts[0]

        if head == "#TOTAL":
            total = int(parts[1])
        elif head == "#SLIDE":
            current = Slide(keynote_no=int(parts[1]), skipped=(parts[2] == "true"))
            slides.append(current)
        elif head == "#SLIDE-META" and current is not None:
            try:
                current.bg_r = int(float(parts[1] or 0))
                current.bg_g = int(float(parts[2] or 0))
                current.bg_b = int(float(parts[3] or 0))
            except (IndexError, ValueError):
                pass
        elif head == "#END-SLIDE" and current is not None:
            # Dedupe pass. Keynote 15 surfaces some elements multiple times:
            #   (a) master items appear in both `base layout` and the slide's
            #       own `iWork items` (→ MASTER + ITEM records)
            #   (b) the same master item appears twice in `base layout` (→
            #       MASTER + MASTER records, identical bbox + filename)
            # Collapse by (type, file_name, rounded bbox). Keep the FIRST
            # occurrence; prefer MASTER over ITEM when both exist so master-
            # suppression logic still gets a chance to evaluate it.
            seen: set[tuple[str, str, int, int, int, int]] = set()
            # First pass: collect master keys so we can drop ITEM duplicates
            # of them.
            master_keys = {
                (el.type, el.file_name, int(el.x), int(el.y),
                 int(el.w), int(el.h))
                for el in current.elements
                if el.is_master and el.file_name
            }
            deduped = []
            for el in current.elements:
                key = (el.type, el.file_name,
                       int(el.x), int(el.y), int(el.w), int(el.h))
                # Skip an ITEM that duplicates a MASTER record (or vice versa)
                if (not el.is_master) and el.file_name and key in master_keys:
                    continue
                # Skip exact duplicates (same is_master, same key)
                tag = (("M" if el.is_master else "I"),) + key
                if tag in seen:
                    continue
                seen.add(tag)
                deduped.append(el)
            current.elements = deduped
            current = None
        elif head == "#DONE":
            break
        elif head in ("ITEM", "MASTER") and current is not None:
            # ITEM \t type \t x \t y \t w \t h \t rotation \t file_name \t font \t
            # font_size \t r \t g \t b \t fill_r \t fill_g \t fill_b \t corner \t opacity \t text_b64
            try:
                el = Element(
                    type=parts[1],
                    x=float(parts[2]),
                    y=float(parts[3]),
                    w=float(parts[4]),
                    h=float(parts[5]),
                    rotation=float(parts[6] or 0),
                    file_name=parts[7],
                    font=parts[8],
                    font_size=float(parts[9] or 0),
                    r=int(float(parts[10] or 0)),
                    g=int(float(parts[11] or 0)),
                    b=int(float(parts[12] or 0)),
                    fill_r=int(float(parts[13] or 0)),
                    fill_g=int(float(parts[14] or 0)),
                    fill_b=int(float(parts[15] or 0)),
                    corner_radius=float(parts[16] or 0),
                    opacity=float(parts[17] or 100),
                    is_master=(head == "MASTER"),
                    text=base64.b64decode(parts[18]).decode("utf-8") if len(parts) > 18 and parts[18] else "",
                )
                # Skip "group" container records — their children were already flattened.
                if el.type == "group":
                    continue
                current.elements.append(el)
            except (IndexError, ValueError) as e:
                print(f"  warning: bad ITEM line: {e!r} — {line[:120]}", file=sys.stderr)

        elif head == "RUN" and current is not None and current.elements:
            # RUN \t font \t size \t r \t g \t b \t text_b64
            # Attaches to the most recently appended element.
            try:
                last = current.elements[-1]
                run_text = base64.b64decode(parts[6]).decode("utf-8") if len(parts) > 6 and parts[6] else ""
                last.runs.append({
                    "text": run_text,
                    "font": parts[1],
                    "size": float(parts[2] or 0),
                    "r":    int(float(parts[3] or 0)),
                    "g":    int(float(parts[4] or 0)),
                    "b":    int(float(parts[5] or 0)),
                })
            except (IndexError, ValueError) as e:
                print(f"  warning: bad RUN line: {e!r} — {line[:120]}", file=sys.stderr)

    return total, slides


# ----------------------------------------------------------------------------
# Image matching against .key/Data/
# ----------------------------------------------------------------------------

class AssetResolver:
    """Resolves Element.file_name → actual file under .key/Data/.

    Strategy (v0.2):
      1. Strip "-NNNN" / "-small-NNNN" suffix from Data/ filenames, compare to
         AppleScript-reported stem (which lacks the suffix).
      2. If exactly one non-"small" candidate matches the stem, use it.
      3. Multiple candidates → filter to those whose intrinsic size is at
         least 0.5× the displayed size (rejects tiny thumbnails). Among the
         remaining, score by aspect-ratio match (size as tiebreaker).
    """

    def __init__(self, data_dir: Path, out_assets_dir: Path,
                 iwa_map: "Optional[IWAAssetMap]" = None):
        self.data_dir = data_dir
        self.out_assets_dir = out_assets_dir
        self.cache: dict[tuple[str, int, int], Optional[Path]] = {}
        self.png_cache: dict[Path, Path] = {}
        self._all_files: list[Path] = sorted(p for p in data_dir.iterdir() if p.is_file())
        self._by_name: dict[str, Path] = {p.name: p for p in self._all_files}
        self._dimensions: dict[Path, tuple[float, float]] = {}
        # IWA-derived ground truth: (slide_no, bbox) → exact Data/ filename.
        # When present, we consult this BEFORE the name-stem heuristic — it's
        # deterministic where the heuristic has to guess between collisions.
        self.iwa_map = iwa_map

    def text_align_for_element(self, slide_no: int, x: float, y: float,
                               w: float, h: float) -> Optional[str]:
        """IWA-sourced text alignment ("left"/"center"/"right"/"justify").
        Returns None when no match — caller falls back to bbox heuristic."""
        if self.iwa_map is None:
            return None
        return self.iwa_map.text_alignment(slide_no, x, y, w, h)

    def resolve_with_bbox(self, slide_no: int, x: float, y: float,
                          w: float, h: float, file_name: str,
                          kind: Optional[str] = None):
        """Like resolve_for_element, but also returns the IWA's TRUE bbox
        AND a `has_mask` flag.

        Returns (Path, (x, y, w, h), has_mask) or (Path, None, False) if
        IWA didn't supply a bbox (legacy heuristic path), or None if
        nothing resolved at all.
        """
        if self.iwa_map is not None:
            hit = self.iwa_map.lookup_with_bbox(slide_no, x, y, w, h,
                                                file_name=file_name, kind=kind)
            if hit:
                fname, bbox, has_mask = hit
                p = self._by_name.get(fname)
                if p is not None:
                    return (p, bbox, has_mask)
        if file_name:
            p = self.resolve(file_name, w, h)
            if p is not None:
                return (p, None, False)
        return None

    def resolve_for_element(self, slide_no: int, x: float, y: float,
                            w: float, h: float, file_name: str,
                            kind: Optional[str] = None) -> Optional[Path]:
        """Resolve an image/movie element to its Data/ file.

        Strategy: IWA bbox lookup first (deterministic), then fall back to the
        old name-stem heuristic. The IWA path works even when AppleScript
        reports `file_name=""` (some inserted movies don't expose a name).
        """
        if self.iwa_map is not None:
            fname = self.iwa_map.lookup(slide_no, x, y, w, h,
                                       file_name=file_name, kind=kind)
            if fname:
                hit = self._by_name.get(fname)
                if hit is not None:
                    return hit
        # Fallback: legacy stem + dimension heuristic. Keeps things working
        # if (a) keynote-parser isn't installed, or (b) the bbox match fails
        # for some edge case (rotated groups, etc.).
        if file_name:
            return self.resolve(file_name, w, h)
        return None

    def _intrinsic_size(self, p: Path) -> Optional[tuple[float, float]]:
        if p in self._dimensions:
            return self._dimensions[p]
        try:
            if p.suffix.lower() == ".pdf":
                doc = fitz.open(p)
                rect = doc[0].rect
                doc.close()
                size = (rect.width, rect.height)
            elif p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".tiff", ".bmp"):
                img = Image.open(p)
                size = img.size
                img.close()
            elif p.suffix.lower() == ".svg":
                # Parse viewBox or width/height from the SVG header.
                import xml.etree.ElementTree as ET
                try:
                    root = ET.parse(p).getroot()
                    vb = root.get("viewBox")
                    if vb:
                        nums = vb.split()
                        if len(nums) == 4:
                            size = (float(nums[2]), float(nums[3]))
                        else:
                            return None
                    else:
                        w = root.get("width", "").rstrip("px")
                        h = root.get("height", "").rstrip("px")
                        size = (float(w), float(h))
                except Exception:
                    return None
            else:
                return None
            self._dimensions[p] = size
            return size
        except Exception:
            return None

    @staticmethod
    def _strip_id_suffix(fname: str) -> str:
        if "." in fname:
            stem, _ = fname.rsplit(".", 1)
        else:
            stem = fname
        return re.sub(r"-small-\d+$|-\d+$", "", stem)

    def resolve(self, file_name: str, want_w: float, want_h: float) -> Optional[Path]:
        if not file_name:
            return None
        key = (file_name, int(want_w), int(want_h))
        if key in self.cache:
            return self.cache[key]

        reported_stem = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
        reported_ext = file_name.rsplit(".", 1)[1].lower() if "." in file_name else ""

        candidates: list[Path] = []
        for p in self._all_files:
            if "small" in p.stem:
                continue
            if self._strip_id_suffix(p.name) == reported_stem:
                candidates.append(p)

        if not candidates:
            self.cache[key] = None
            return None

        if len(candidates) == 1:
            self.cache[key] = candidates[0]
            return candidates[0]

        # FILTER BY EXTENSION FIRST: when AppleScript reports a specific file
        # extension (e.g. `.tiff`), prefer candidates with the same extension
        # before falling back to dimension matching. This fixes the bug where
        # slide 37's `已粘贴的图像.tiff` was matched to a .png (robot image)
        # instead of the .tiff (pink-gradient bg) because aspect-ratio-only
        # matching favored the .png whose bbox aspect happened to match.
        if reported_ext:
            same_ext = [c for c in candidates if c.suffix.lower().lstrip(".") == reported_ext]
            if same_ext:
                candidates = same_ext

        # Multi-candidate: filter by minimum size (source >= 0.5 × displayed area)
        target_area = max(1.0, want_w * want_h)
        big_enough: list[Path] = []
        for c in candidates:
            sz = self._intrinsic_size(c)
            if sz is None:
                continue
            if sz[0] * sz[1] >= 0.5 * target_area:
                big_enough.append(c)

        pool = big_enough if big_enough else candidates

        # Score by aspect ratio match; size as gentle tiebreaker
        target_ratio = want_w / want_h if want_h else 1
        scored: list[tuple[float, Path]] = []
        for c in pool:
            sz = self._intrinsic_size(c)
            if sz is None:
                continue
            cw, ch = sz
            cratio = cw / ch if ch else 1
            ratio_diff = abs(cratio - target_ratio) / max(cratio, target_ratio)
            # log-ish size proximity, capped
            size_ratio = min(cw * ch, target_area) / max(cw * ch, target_area)
            size_diff = 1 - size_ratio
            score = ratio_diff + size_diff * 0.05  # ratio dominates but penalize huge mismatches
            scored.append((score, c))
        scored.sort()
        best = scored[0][1] if scored else None
        self.cache[key] = best
        return best

    def to_png(self, src: Path, slide_assets_dir: Path) -> Path:
        slide_assets_dir.mkdir(parents=True, exist_ok=True)
        if src in self.png_cache:
            cached = self.png_cache[src]
            dst = slide_assets_dir / cached.name
            if not dst.exists():
                shutil.copy(cached, dst)
            return dst

        suffix = src.suffix.lower()
        if suffix == ".pdf":
            doc = fitz.open(src)
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(3, 3), alpha=True)
            dst = slide_assets_dir / (src.stem + ".png")
            pix.save(dst)
            doc.close()
        elif suffix in (".tiff", ".tif", ".bmp"):
            # Browsers don't reliably render TIFF/BMP — convert via Pillow.
            img = Image.open(src)
            dst = slide_assets_dir / (src.stem + ".png")
            img.convert("RGBA").save(dst)
            img.close()
        else:
            # .png / .jpg / .jpeg / .gif / .svg — browsers can render directly.
            dst = slide_assets_dir / src.name
            shutil.copy(src, dst)

        self.png_cache[src] = dst
        return dst


# ----------------------------------------------------------------------------
# Raster fallback — crop unhandled element regions from page PNG
# ----------------------------------------------------------------------------

class RasterFallback:
    """Crop bbox regions from rasterized page PNGs as fallback for elements we
    can't reconstruct structurally (lines, charts, tables, shapes with no
    extractable fill, etc.)."""

    def __init__(self, rasters_dir: Optional[Path], pdf_path: Optional[Path],
                 slides_with_kn_no: list[int]):
        """slides_with_kn_no: ordered Keynote slide numbers of non-skipped slides;
        index in this list is the PDF page number - 1."""
        self.rasters_dir = rasters_dir
        self.pdf_path = pdf_path
        # Map keynote_slide_no → PDF page number (1-based)
        self.kn_to_pdf_page: dict[int, int] = {
            kn: idx + 1 for idx, kn in enumerate(slides_with_kn_no)
        }
        self._page_cache: dict[int, Image.Image] = {}
        self._raster_pdf_doc: Optional[fitz.Document] = None
        if not self.rasters_dir and self.pdf_path:
            try:
                self._raster_pdf_doc = fitz.open(self.pdf_path)
            except Exception as e:
                print(f"  warning: could not open --pdf for fallback: {e}", file=sys.stderr)

    def available(self) -> bool:
        return self.rasters_dir is not None or self._raster_pdf_doc is not None

    def _page_image(self, keynote_no: int) -> Optional[Image.Image]:
        pdf_page = self.kn_to_pdf_page.get(keynote_no)
        if pdf_page is None:
            return None
        if pdf_page in self._page_cache:
            return self._page_cache[pdf_page]

        img: Optional[Image.Image] = None
        if self.rasters_dir:
            # try common naming patterns
            for pattern in (f"slide-{pdf_page:02d}.png", f"slide-{pdf_page:03d}.png",
                            f"p-{pdf_page:03d}.jpg", f"page-{pdf_page:03d}.png"):
                cand = self.rasters_dir / pattern
                if cand.is_file():
                    img = Image.open(cand).convert("RGBA")
                    break
        if img is None and self._raster_pdf_doc is not None:
            try:
                page = self._raster_pdf_doc[pdf_page - 1]
                pix = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("RGBA")
            except Exception as e:
                print(f"  warning: PDF page {pdf_page} render failed: {e}", file=sys.stderr)
                img = None

        if img is not None:
            self._page_cache[pdf_page] = img
        return img

    def crop(self, keynote_no: int, x: float, y: float, w: float, h: float,
             out_path: Path) -> Optional[Path]:
        page_img = self._page_image(keynote_no)
        if page_img is None:
            return None
        # clamp
        pw, ph = page_img.size
        # The PDF/raster page is 1920x1080. Element coords are in same canvas units.
        # If raster is different size, scale.
        sx = pw / 1920.0
        sy = ph / 1080.0
        left   = max(0, int(x * sx))
        top    = max(0, int(y * sy))
        right  = min(pw, int((x + w) * sx))
        bottom = min(ph, int((y + h) * sy))
        if right <= left or bottom <= top:
            return None
        crop = page_img.crop((left, top, right, bottom))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        crop.save(out_path)
        return out_path


# ----------------------------------------------------------------------------
# HTML composition per slide
# ----------------------------------------------------------------------------

_FONT_WEIGHT_KEYWORDS = [
    # Order matters: longer / more specific keywords first
    ("extralight", 200), ("ultralight", 200),
    ("extrabold", 800), ("ultrabold", 800),
    ("semibold", 600), ("demibold", 600),
    ("heavy", 900), ("black", 900),
    ("bold", 700),
    ("medium", 500),
    ("light", 300),
    ("thin", 100),
    ("regular", 400), ("normal", 400), ("book", 400),
]


def _render_text_runs(el, default_color: str, default_font: str, default_size: float) -> str:
    """Render the text content of a text/shape element.

    When `el.runs` contains 2+ entries, emit `<span>` per run with per-run
    font/size/color/weight applied as inline styles. When empty (or 1 run),
    fall back to the container's default styling (just escape + br).

    Newlines become <br> regardless.
    """
    text_fallback = html_lib.escape(el.text).replace("\n", "<br>")
    if len(el.runs) < 2:
        return text_fallback
    out_parts: list[str] = []
    for run in el.runs:
        rt = run.get("text", "")
        if not rt:
            continue
        rfont = run.get("font") or default_font
        rsize = run.get("size") or default_size
        rcolor = _kn_rgb_to_hex(run.get("r", 0), run.get("g", 0), run.get("b", 0)) or default_color
        rweight, rstyle = parse_font_weight_style(rfont)
        rstack = text_font_stack(rfont)
        rt_html = html_lib.escape(rt).replace("\n", "<br>")
        out_parts.append(
            f'<span style="font-family:{rstack};font-size:{rsize:.1f}px;'
            f'font-weight:{rweight};font-style:{rstyle};color:{rcolor};">'
            f'{rt_html}</span>'
        )
    return "".join(out_parts) if out_parts else text_fallback


def parse_font_weight_style(font_name: str) -> tuple[int, str]:
    """Parse a Keynote font name like 'Helvetica-Bold' or
    'HarmonyOS_Sans_SC_Black' into (font-weight, font-style).

    Returns (400, 'normal') for plain / unparseable names.
    """
    if not font_name:
        return 400, "normal"
    fn = font_name.lower()
    # font-style
    style = "italic" if "italic" in fn or "oblique" in fn else "normal"
    # font-weight — first matching keyword wins (sorted by specificity)
    weight = 400
    for kw, w in _FONT_WEIGHT_KEYWORDS:
        if kw in fn:
            weight = w
            break
    return weight, style


def fit_font_to_box(text: str, container_w: float, container_h: float,
                    original_size: float, line_height: float = 1.35,
                    min_size: float = 12.0) -> float:
    """Identity passthrough (v0.13).

    Previous versions tried to approximate Keynote's "shrink text to fit"
    behavior via char-width heuristics, but the estimation was inherently
    inexact (web fallback fonts vary in width vs the authored
    AlibabaPuHuiTi / HarmonyOS_Sans / FZLTTHK fonts) and produced
    spurious shrinks (slide 21 had 3 same-sized quote lines shrunk to
    3 different sizes). Per user direction (2026-05): always honor the
    AUTHORED font size. If the user wants text resized, they can edit the
    Keynote source or the rendered HTML directly. Browser will wrap text
    natively when it overflows the container width.
    """
    return original_size


def text_font_stack(font_name: str) -> str:
    """Returns a CSS font-family stack using SINGLE quotes for multi-word names —
    so it can be embedded inside an HTML `style="..."` attribute without
    breaking the attribute delimiter. (Critical bug fix v0.5: previously used
    double quotes inside double-quoted style attributes, causing browsers to
    discard everything past `font-family:`.)
    """
    fn = (font_name or "").lower()
    cjk = "'PingFang SC','Microsoft YaHei','Source Han Sans SC','Noto Sans SC',sans-serif"
    latin = "'Helvetica Neue','Helvetica','Arial',sans-serif"
    if "harmony" in fn or "alibaba" in fn or "puhui" in fn or "fangzheng" in fn or "lanting" in fn:
        return cjk
    if "helvetica" in fn or "arial" in fn:
        return f"'{font_name}',{latin}"
    if "songti" in fn or "宋" in fn:
        return f"'{font_name}',{cjk}"
    return f"'{font_name}',{cjk}" if font_name else cjk


def _transform(rotation: float) -> str:
    """CSS transform with !important so it survives feishu's per-slide override
    (`.slide > * { transform: none !important }` from our anti-flash CSS)."""
    if abs(rotation) < 0.01:
        return ""
    return f" transform: rotate({rotation}deg) !important;"


def _text_align(el_x: float, el_w: float, slide_w: float = 1920) -> str:
    """Infer CSS text-align from bbox position.

    AppleScript doesn't reliably expose Keynote's text alignment property
    (`alignment of paragraph 1` throws on certain text items). Use a bbox
    heuristic: when the bbox horizontal center is within ±80 px of the slide
    center, treat the text as center-aligned. Bboxes near the left/right
    margins are treated as left/right-aligned.
    """
    bbox_center = el_x + el_w / 2
    slide_center = slide_w / 2  # 960
    if abs(bbox_center - slide_center) <= 80:
        return "center"
    # bbox sits near right edge → right-align
    if el_x + el_w > slide_w - 40 and el_x > slide_w * 0.5:
        return "right"
    return "left"


# Patterns for Keynote master/layout placeholder text that should NOT render
# on the actual slide. AppleScript returns the placeholder text (visible only
# in editor) as if it were content. Filter known placeholder patterns.
_PLACEHOLDER_PATTERNS = [
    re.compile(r"^\s*$"),                                  # empty / whitespace
    re.compile(r"^\s*正文级别\s*\d+\s*$", re.MULTILINE),    # 正文级别 1 / 2 / 3
    re.compile(r"^(\s*正文级别\s*\d+\s*\n?)+$"),            # multi-line stack
    re.compile(r"^\s*幻灯片标题\s*$"),                      # Slide Title (zh)
    re.compile(r"^\s*副标题\s*$"),                          # Subtitle (zh)
    re.compile(r"^\s*Slide\s+(title|headline)\s*$", re.IGNORECASE),
    re.compile(r"^\s*Subtitle\s*$", re.IGNORECASE),
    re.compile(r"^\s*Presentation\s+Title\s*$", re.IGNORECASE),  # Apple template
    re.compile(r"^\s*Click\s+or\s+tap\s+to", re.IGNORECASE),
    re.compile(r"^\s*(Click|Tap)\s+to\s+(add|edit)", re.IGNORECASE),
    re.compile(r"^\s*[单点]击此处"),                        # 单击此处编辑标题 / 主标题 / 全标题 (zh "click to edit"); also catches doubled stutters
    re.compile(r"^\s*Body\s+(text|level)(\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten))?\s*$", re.IGNORECASE),  # "Body Level 1" AND spelled-out "Body Level One".."Five"
    re.compile(r"^(\s*Body\s+(text|level)(\s+(\d+|one|two|three|four|five|six|seven|eight|nine|ten))?\s*\n?)+$", re.IGNORECASE),  # multi-line stack "Body Level One\nBody Level Two\n..." in one text box
    re.compile(r"^\s*Lorem\s+ipsum", re.IGNORECASE),
    re.compile(r"^\s*金句页底图\s*$"),                       # decor placeholder
    re.compile(r"^\s*Section\s+Title\s*$", re.IGNORECASE),
    re.compile(r"^\s*Chapter\s+Title\s*$", re.IGNORECASE),
]


def is_placeholder_text(text: str) -> bool:
    """True if text looks like a Keynote master/layout placeholder, not real content."""
    if not text:
        return True
    return any(p.match(text) for p in _PLACEHOLDER_PATTERNS)


def _bbox_close(a: Element, b: Element, tol: float = 8.0) -> bool:
    """True if two elements occupy substantially the same bbox (≤ tol px on each side)."""
    return (abs(a.x - b.x) <= tol and abs(a.y - b.y) <= tol
            and abs(a.w - b.w) <= tol and abs(a.h - b.h) <= tol)


def _localize_renderer_refs(html_path: Path, renderer_local: Path,
                            renderer_skill_root: Path) -> None:
    """Copy renderer CSS/JS files into <output>/_renderer/ and rewrite
    index.html refs to use that local path.

    Scans for any `href="..."` or `src="..."` URL pointing into the
    renderer skill directory (matched by the renderer's directory name).
    For each match:
      1. Resolves the path relative to renderer_skill_root.
      2. Copies the file into renderer_local/, preserving subfolders.
      3. Rewrites the HTML ref to the local path.

    Idempotent: safe to re-run.
    """
    if not html_path.is_file():
        return
    html = html_path.read_text(encoding="utf-8")

    # Match any `../../skills/<renderer-name>/<rest>` URL. Renderer dir
    # name is taken from renderer_skill_root.name so this works whether
    # the renderer is `feishu-deck-h5`, a fork, or any compatible skill.
    renderer_dir = re.escape(renderer_skill_root.name)
    pat = re.compile(
        r'((?:\.\./)+)(?:[\w./-]*?)skills/' + renderer_dir + r'/([^\'")\s?#]+)'
    )
    renderer_local.mkdir(parents=True, exist_ok=True)
    copied = 0
    seen: set[str] = set()

    def _sub(m):
        nonlocal copied
        rest = m.group(2)  # e.g. "assets/feishu-deck.css"
        src = renderer_skill_root / rest
        if not src.is_file():
            # Unknown ref — leave it alone so the broken state is visible
            # rather than silently mangled.
            return m.group(0)
        dst = renderer_local / rest
        if rest not in seen:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
                shutil.copy2(src, dst)
                copied += 1
            seen.add(rest)
        return f"_renderer/{rest}"

    new_html = pat.sub(_sub, html)
    if new_html != html:
        html_path.write_text(new_html, encoding="utf-8")
    print(f"    localized renderer: {len(seen)} refs · {copied} files copied to _renderer/")


def _object_fit_for(natural_w: float, natural_h: float,
                    render_w: float, render_h: float) -> str:
    """Pick `object-fit: cover` vs `contain` based on aspect comparison.

    The default in HTML for our renderer is `cover` (fill the box, crop
    overflow). That's fine when the image's natural aspect roughly matches
    the render box — OR when the image is TALLER than the box (e.g. phone
    screenshots in a portrait slot, where cover crops top/bottom which is
    the intentional Keynote display).

    But when the image is significantly WIDER than the box (e.g. 邮政储蓄
    银行 logo natural 624×53 in a 206×42 slot, or FOTILE natural 517×232
    in a 193×31 slot), cover crops the LEFT/RIGHT and we lose the start /
    end of the logo. Authors expect the full logo to remain readable; use
    `contain` instead — image fits fully, with vertical letterbox.

    Threshold: 25% aspect drift. Below that, natural≈container and cover
    is fine. Above that, only switch to contain when natural is the WIDER
    one (we don't want to letterbox tall phone shots).
    """
    if natural_w <= 0 or natural_h <= 0 or render_w <= 0 or render_h <= 0:
        return "cover"
    nat_ratio = natural_w / natural_h
    ren_ratio = render_w / render_h
    drift = abs(nat_ratio - ren_ratio) / max(ren_ratio, nat_ratio)
    if drift < 0.25:
        return "cover"
    # Natural wider than container → cover would crop sides → use contain.
    if nat_ratio > ren_ratio:
        return "contain"
    # Natural taller than container → cover crops top/bottom, usually the
    # intentional Keynote display for portrait images (phones, hero shots).
    return "cover"


def _emit_iwa_fill_div(sf, in_place: bool) -> str:
    """Render an IWA `_ShapeFill` as a positioned `<div>`.

    in_place=True  → emitted at source position (no z-index; document order
                     is the source of truth — shape comes before video
                     gets stacked under it).
    in_place=False → emitted at end (z-index:5; sits above images/videos
                     but below text at z-index:10).
    """
    if sf.gradient_css:
        bg = f"background:{sf.gradient_css};"
        op_part = f"opacity:{sf.alpha:.3f};" if sf.alpha < 0.999 else ""
    else:
        bg = f"background:rgba({sf.r},{sf.g},{sf.b},{sf.alpha:.3f});"
        op_part = ""
    z = "" if in_place else "z-index:5;"
    return (
        f'<div class="el iwa-fill" style="left:{sf.x:.0f}px;top:{sf.y:.0f}px;'
        f'width:{sf.w:.0f}px;height:{sf.h:.0f}px;'
        f'{bg}{op_part}{z}pointer-events:none;"></div>'
    )


def compose_slide_html(slide: Slide, resolver: AssetResolver,
                       raster: RasterFallback,
                       slide_assets_subdir: str,
                       slide_assets_dir: Path) -> tuple[str, list[str]]:
    parts: list[str] = []
    warnings: list[str] = []
    key = f"slide-{slide.keynote_no:03d}"

    # Background heuristic: AppleScript's #SLIDE-META gives us the master's fill
    # color only when it's a plain color fill — many Keynote masters use image/
    # gradient fills that don't expose. Fall back to inferring from master name
    # via the layout name (we don't currently pass that through; instead, when
    # bg_r/g/b are all zero AND we're in a "white master" context, the user
    # can override). For now: keep extracted bg; if (0,0,0) and the slide has
    # ANY element with text color #000, assume the master is white.
    bg = slide.bg_hex if slide.has_bg_color else None
    if bg is None:
        # Heuristic: if any SLIDE-LEVEL (not master, not placeholder) text
        # element uses near-black color, the slide background is probably
        # white. Master text uses theme-default black even on dark slides —
        # and slide-level shapes with placeholder content (e.g. "金句页底图"
        # which is a decor placeholder named with black theme text) would
        # also pollute the check. Filter both out.
        has_dark_text = any(
            (not el.is_master)
            and el.type in ("text", "shape") and el.text.strip()
            and not is_placeholder_text(el.text)
            and (el.r + el.g + el.b) < 20000
            for el in slide.elements
        )
        bg = "#FFFFFF" if has_dark_text else "#000"

    parts.append(f"<style>")
    parts.append(f".slide[data-slide-key='{key}'] {{ background: {bg}; overflow: hidden; }}")
    parts.append(f".slide[data-slide-key='{key}'] .el {{ position: absolute; transform-origin: center center; }}")
    parts.append(f".slide[data-slide-key='{key}'] .shape {{ box-sizing: border-box; }}")
    # CRITICAL: feishu-deck-h5's "stagger reveal" rule sets
    #   .slide-frame.is-current .slide > * { opacity: 0; transform: ...; animation: fs-reveal ... }
    # The animation transitions opacity 0 → 1 over 0.28s. We disable the
    # animation so authored opacity (e.g. 22% for a translucent bg) is honored
    # — but the base rule's `opacity: 0` would then make elements WITHOUT
    # inline opacity permanently invisible (black slide on navigate). So we
    # also set `opacity: 1` as the default; inline opacity (smaller values)
    # naturally wins via higher specificity.
    parts.append(
        f".slide[data-slide-key='{key}'].slide > * {{ "
        f"animation: none !important; "
        f"transform: none !important; "
        f"opacity: 1; "
        f"}}"
    )
    # z-index discipline so IWA-sourced shape backdrops (translucent black
    # masks, card-fill overlays) layer correctly:
    #   img / video : 0   (slide backgrounds)
    #   .iwa-fill   : 5   (the backdrops we synthesize from style chain)
    #   text/shape  : 10  (all <div class="el ..."> except .iwa-fill)
    parts.append(
        f".slide[data-slide-key='{key}'] > img.el,"
        f".slide[data-slide-key='{key}'] > video.el {{ z-index: 0; }}"
    )
    parts.append(
        f".slide[data-slide-key='{key}'] > div.el:not(.iwa-fill) {{ z-index: 10; }}"
    )
    parts.append(f"</style>")

    SLIDE_W, SLIDE_H = 1920, 1080
    # Master-element suppression: ONLY for template placeholder text/shape
    # ("幻灯片标题", "正文级别 1", etc.) — Keynote literally doesn't render
    # those strings, they're authoring hints in the editor. Everything else
    # from the master (background image, footer chrome, page-number marker)
    # is preserved; z-order + opacity handle whether it actually shows.
    suppressed_master: set[int] = set()
    for i, el in enumerate(slide.elements):
        if not el.is_master:
            continue
        if el.type in ("text", "shape") and is_placeholder_text(el.text):
            suppressed_master.add(i)

    # Match IWA shape-fills to AppleScript shape elements by bbox. When the
    # AppleScript shape has no fill / no text (the typical "empty shape used
    # as a colored rectangle" case), we replace its emission with the IWA
    # backdrop — placed at the SAME position in the parts list so source
    # draw-order is preserved (e.g. slide 18 has the shape BEFORE the video,
    # so its black backdrop must render UNDER the video, not over it).
    iwa_fills = (resolver.iwa_map.shape_fills_for_slide(slide.keynote_no)
                 if resolver.iwa_map is not None else [])
    iwa_fill_for_idx: dict[int, object] = {}  # AppleScript elem idx → _ShapeFill
    iwa_consumed: set[int] = set()  # indices into iwa_fills that paired off
    for fi, sf in enumerate(iwa_fills):
        # Find AppleScript element with best bbox overlap (must be a shape,
        # and the bboxes must be close — we don't want to attach an opaque
        # full-canvas backdrop to a tiny placeholder by accident).
        best_idx, best_score = None, 0.0
        for j, ej in enumerate(slide.elements):
            if ej.type != "shape":
                continue
            # IoU-ish score, rough
            ix0, iy0 = max(sf.x, ej.x), max(sf.y, ej.y)
            ix1, iy1 = min(sf.x + sf.w, ej.x + ej.w), min(sf.y + sf.h, ej.y + ej.h)
            if ix1 <= ix0 or iy1 <= iy0:
                continue
            inter = (ix1 - ix0) * (iy1 - iy0)
            union = sf.w * sf.h + ej.w * ej.h - inter
            score = inter / union if union > 0 else 0
            if score > best_score:
                best_score, best_idx = score, j
        if best_idx is not None and best_score >= 0.5:
            iwa_fill_for_idx[best_idx] = sf
            iwa_consumed.add(fi)

    # Pre-pass: detect shape+image pairs occupying the same bbox.
    # In Keynote these are "stylized image placeholders" — a shape with a fill
    # (often gradient/theme) acting as a frame, with an image inside it.
    # AppleScript can't extract the shape's fill in many cases, so we render
    # the entire pair as a single raster crop. Mark both elements as skipped.
    skip_idx: set[int] = set()
    used_via_raster_pair: set[int] = set()
    bbox_pair_crops: dict[int, str] = {}  # element idx → cropped png rel path

    if raster.available():
        for i, ei in enumerate(slide.elements):
            if ei.type != "shape" or ei.text.strip() or ei.has_fill:
                continue  # only consider EMPTY shapes
            for j, ej in enumerate(slide.elements):
                if j == i or j in skip_idx:
                    continue
                if ej.type != "image":
                    continue
                if _bbox_close(ei, ej):
                    fb = raster.crop(
                        slide.keynote_no, ei.x, ei.y, ei.w, ei.h,
                        slide_assets_dir / f"_pair-{i}.png",
                    )
                    if fb:
                        bbox_pair_crops[j] = f"{slide_assets_subdir}/{fb.name}"
                        skip_idx.add(i)
                        used_via_raster_pair.add(j)
                    break

    # Detect empty shapes for skip decision:
    #   · If the shape CONTAINS multiple other elements inside its bbox →
    #     it's a CONTAINER (banner/card background). Keep it for the
    #     shape-rendering branch's container heuristic to handle.
    #   · If the shape OVERLAPS with content but does NOT contain it (e.g.
    #     a tiny placeholder rectangle dropped on top of text) → skip; it's
    #     an invisible authoring placeholder.
    #   · If the shape has NO overlap with anything → also skip.
    def bbox_contains(a, b, min_overlap_ratio=0.70):
        """True iff at least `min_overlap_ratio` (default 70%) of b's bbox
        area falls inside a's bbox. Strict bbox-containment is too brittle:
        Keynote authors often have body text extending a few px past a
        banner shape's bottom; pure containment misses that case.
        """
        b_area = b.w * b.h
        if b_area <= 0:
            return False
        # intersection
        ix0, iy0 = max(a.x, b.x), max(a.y, b.y)
        ix1, iy1 = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
        if ix1 <= ix0 or iy1 <= iy0:
            return False
        inter_area = (ix1 - ix0) * (iy1 - iy0)
        return (inter_area / b_area) >= min_overlap_ratio

    def overlaps_without_containing(idx: int) -> bool:
        a = slide.elements[idx]
        contained = 0
        overlapping = 0
        for k, b in enumerate(slide.elements):
            if k == idx or b.type == "group":
                continue
            # check center-distance overlap
            if (abs((a.x + a.w/2) - (b.x + b.w/2)) < (a.w + b.w) / 2 - 4 and
                abs((a.y + a.h/2) - (b.y + b.h/2)) < (a.h + b.h) / 2 - 4):
                overlapping += 1
                if bbox_contains(a, b):
                    contained += 1
        # Overlaps with content but doesn't contain any of it → placeholder
        return overlapping > 0 and contained == 0

    for i, ei in enumerate(slide.elements):
        if i in skip_idx:
            continue
        if ei.type == "shape" and not ei.text.strip() and not ei.has_fill:
            if overlaps_without_containing(i):
                skip_idx.add(i)

    for idx, el in enumerate(slide.elements):
        if idx in skip_idx or idx in suppressed_master:
            continue
        rot = _transform(el.rotation)
        op_css = f"opacity:{el.css_opacity:.3f} !important;" if el.is_translucent else ""

        # Shape+image pair already cropped from raster — emit that crop
        if idx in used_via_raster_pair:
            rel = bbox_pair_crops[idx]
            parts.append(
                f'<img class="el" src="{html_lib.escape(rel)}" '
                f'style="left:{el.x}px;top:{el.y}px;width:{el.w}px;height:{el.h}px;'
                f'object-fit:cover;{op_css}{rot}">'
            )
            continue

        if el.type == "image":
            # IWA-deterministic resolution, returning both file AND the
            # IWA's true bbox (when available). For non-master images,
            # AppleScript sometimes reports a CLIPPED bbox (the visible
            # region) which mis-renders the image via object-fit:cover —
            # e.g. slide 12's 邮政储蓄银行 logo (AppleScript 206×42,
            # natural image 624×53, IWA truth 380×32 fits perfectly).
            # If IWA gives us a wider/taller bbox, prefer it.
            iwa_bbox = None
            iwa_has_mask = False
            rb = resolver.resolve_with_bbox(
                slide.keynote_no, el.x, el.y, el.w, el.h, el.file_name, kind="image"
            )
            if rb is None:
                src = None
            else:
                src, iwa_bbox, iwa_has_mask = rb
            if src is None and not el.file_name:
                warnings.append(f"slide {slide.keynote_no} item {idx}: image with no file_name")
                continue
            if src is None:
                warnings.append(
                    f"slide {slide.keynote_no} item {idx}: could not resolve '{el.file_name}' "
                    f"({int(el.w)}×{int(el.h)})"
                )
                # try raster fallback
                if raster.available():
                    fb_path = raster.crop(
                        slide.keynote_no, el.x, el.y, el.w, el.h,
                        slide_assets_dir / f"_fallback-img-{idx}.png",
                    )
                    if fb_path:
                        rel = f"{slide_assets_subdir}/{fb_path.name}"
                        parts.append(
                            f'<img class="el" src="{html_lib.escape(rel)}" '
                            f'style="left:{el.x}px;top:{el.y}px;width:{el.w}px;'
                            f'height:{el.h}px;object-fit:cover;{rot}">'
                        )
                        continue
                parts.append(
                    f'<div class="el" style="left:{el.x}px;top:{el.y}px;width:{el.w}px;'
                    f'height:{el.h}px;outline:1px dashed #f08;color:#f08;font:14px monospace;'
                    f'padding:4px;background:rgba(255,0,128,.08);{rot}">'
                    f'missing image: {html_lib.escape(el.file_name)}</div>'
                )
                continue
            png_path = resolver.to_png(src, slide_assets_dir)
            rel = f"{slide_assets_subdir}/{png_path.name}"
            # Choose render bbox. AppleScript reports the actual display
            # bbox after any mask/crop Keynote has applied — for images
            # entirely within the canvas, that IS the correct bbox.
            # The only case AppleScript LIES is when the image overflows
            # the canvas: Keynote's PDF-export pipeline clips the bbox at
            # the canvas edge before reporting, and now `object-fit:cover`
            # at that smaller-than-real bbox shows the wrong pixel slice
            # (e.g. slide 5 master `up@2x.png` is a 2048×6456 tall texture
            # placed at y=-1081 in the template; AppleScript clips to
            # (-19,-53) 1958×2076 → object-fit shows the middle band of
            # the image, not the top band Keynote actually displays).
            # Detection: AppleScript bbox extends well beyond canvas. In
            # that case use IWA's true placement. .slide overflow:hidden
            # clips it correctly.
            # Bbox decision — kept simple to avoid the rabbit hole:
            #
            #   · Slide-level images: ALWAYS use AppleScript bbox. The IWA
            #     archive carries a `mask` field on virtually every image
            #     drawable (Keynote authors images with implicit unity
            #     masks, so mask presence doesn't reliably signal "the
            #     image is meaningfully cropped"). Trying to override
            #     based on aspect-mismatch with the natural file flips
            #     phone screenshots wrong-way-around. Leaving these on
            #     AppleScript matches what users see in Keynote present
            #     mode at the cost of minor side-cropping on a few wide
            #     logos (e.g. 邮政储蓄银行: object-fit:cover may shave a
            #     few px off each end — acceptable cosmetic drift).
            #
            #   · MASTER images: use IWA bbox ONLY when AppleScript bbox
            #     extends substantially off-canvas. That's the canonical
            #     "Keynote clipped its reported bbox at the canvas edge"
            #     signal — and the only case where IWA's true placement
            #     is observably necessary (e.g. slide 5 up@2x.png 2048×6456
            #     reported as 1958×2076 by AppleScript).
            SLIDE_W, SLIDE_H = 1920, 1080
            CANVAS_OVERFLOW_EPS = 8
            x_use, y_use, w_use, h_use = el.x, el.y, el.w, el.h
            if el.is_master and resolver.iwa_map is not None:
                overflows = (
                    el.x < -CANVAS_OVERFLOW_EPS or el.y < -CANVAS_OVERFLOW_EPS
                    or (el.x + el.w) > SLIDE_W + CANVAS_OVERFLOW_EPS
                    or (el.y + el.h) > SLIDE_H + CANVAS_OVERFLOW_EPS
                )
                if overflows:
                    tbb = resolver.iwa_map.master_bbox(slide.keynote_no, el.file_name)
                    if tbb is not None:
                        x_use, y_use, w_use, h_use = tbb
            # Pick object-fit based on natural-vs-render aspect comparison
            # (see _object_fit_for). cover for typical / portrait-cropped
            # images; contain when natural is much wider than container so
            # we don't side-crop wide logos.
            natural = resolver._intrinsic_size(src)
            if natural is not None:
                fit = _object_fit_for(natural[0], natural[1], w_use, h_use)
            else:
                fit = "cover"
            parts.append(
                f'<img class="el" src="{html_lib.escape(rel)}" '
                f'style="left:{x_use}px;top:{y_use}px;width:{w_use}px;height:{h_use}px;'
                f'object-fit:{fit};{op_css}{rot}">'
            )

        elif el.type == "movie":
            # IWA-first resolution — critical for movies, which AppleScript
            # sometimes reports with empty file_name (the legacy resolver
            # had no chance there).
            src = resolver.resolve_for_element(
                slide.keynote_no, el.x, el.y, el.w, el.h, el.file_name, kind="movie"
            )
            if src is None:
                # Movie has no resolvable file (AppleScript sometimes returns
                # empty `file name` for inserted movies). Fall back to raster
                # crop of the slide region so user at least sees the visual.
                if raster.available():
                    fb = raster.crop(
                        slide.keynote_no, el.x, el.y, el.w, el.h,
                        slide_assets_dir / f"_fallback-movie-{idx}.png",
                    )
                    if fb:
                        rel = f"{slide_assets_subdir}/{fb.name}"
                        warnings.append(
                            f"slide {slide.keynote_no} item {idx}: movie '{el.file_name}' "
                            f"unresolved, using raster crop"
                        )
                        parts.append(
                            f'<img class="el" src="{html_lib.escape(rel)}" '
                            f'style="left:{el.x}px;top:{el.y}px;width:{el.w}px;'
                            f'height:{el.h}px;object-fit:cover;{op_css}{rot}">'
                        )
                        continue
                warnings.append(
                    f"slide {slide.keynote_no} item {idx}: movie '{el.file_name}' unresolved"
                )
                continue
            slide_assets_dir.mkdir(parents=True, exist_ok=True)
            dst = slide_assets_dir / src.name
            if not dst.exists():
                shutil.copy(src, dst)
            rel = f"{slide_assets_subdir}/{src.name}"

            # Auto-generate a poster frame (first video frame) so the video
            # has something to show before autoplay starts — or when autoplay
            # is blocked (file:// URLs, some browser policies).
            poster_attr = ""
            try:
                import av  # PyAV — optional, but recommended for videos
                poster_path = slide_assets_dir / (src.stem + ".poster.jpg")
                if not poster_path.exists():
                    container = av.open(str(src))
                    for frame in container.decode(video=0):
                        frame.to_image().save(str(poster_path), quality=80)
                        break
                    container.close()
                poster_attr = f' poster="{html_lib.escape(slide_assets_subdir)}/{poster_path.name}"'
            except ImportError:
                pass  # av not installed — silently omit poster
            except Exception as e:
                warnings.append(
                    f"slide {slide.keynote_no} item {idx}: poster gen failed for {src.name}: {e}"
                )

            # IMPORTANT: do NOT set the `src` attribute up-front, and use
            # `preload="none"` — otherwise the browser greedily downloads /
            # decodes every <video> element across all 62 slides on page load,
            # which murders performance and makes navigation laggy. We use
            # `data-src` and rely on feishu-deck.js (see the inline patch
            # below) to swap in `src` only when the slide becomes current,
            # and pause + nuke `src` when it leaves view.
            parts.append(
                f'<video class="el lazy-video" data-src="{html_lib.escape(rel)}"{poster_attr} '
                f'style="left:{el.x}px;top:{el.y}px;width:{el.w}px;height:{el.h}px;'
                f'object-fit:cover;{op_css}{rot}" muted loop playsinline preload="none"></video>'
            )

        elif el.type == "shape":
            # A shape may have text, fill, both, or neither.
            has_text = bool(el.text.strip())
            has_fill_color = el.has_fill
            # text_inner gets either escaped text OR per-run <span>s when
            # the element has multi-run styling (see _render_text_runs).
            # default_color/size/font filled in below once we know them.
            text_inner = ""

            if has_fill_color or has_text:
                # rgba background bakes opacity into the color when translucent.
                # For opaque elements we still emit rgba (with alpha=1.0); same result.
                bg_rgba = el.fill_color_rgba if has_fill_color else "transparent"

                # Corner radius heuristic — only for shapes that look like a "card"
                # or "pill" (opaque-ish, small). Skip for translucent overlays
                # (those are usually full-bleed masks, not rounded boxes).
                radius_css = ""
                if has_fill_color and not el.is_translucent:
                    ratio = el.w / el.h if el.h else 1
                    if 1.5 < ratio < 6 and el.h < 200:
                        radius_css = f"border-radius:{int(el.h/2)}px"
                    elif 0.7 < ratio < 1.4 and el.h < 200:
                        radius_css = "border-radius:24px"
                    else:
                        radius_css = "border-radius:16px"

                style_parts = [
                    f"left:{el.x}px", f"top:{el.y}px",
                    f"width:{el.w}px", f"min-height:{el.h}px",
                    f"background:{bg_rgba}",
                    radius_css if radius_css else None,
                ]
                if has_text:
                    weight, fstyle = parse_font_weight_style(el.font)
                    text_color = el.text_color_hex
                    fs_authored = el.font_size or 24
                    is_multirun = len(el.runs) >= 2
                    # Multi-run text uses authored per-run sizes; don't try to
                    # shrink-to-fit using the first run's size (would miscalculate
                    # for mixed-size content).
                    fs = fs_authored if is_multirun else fit_font_to_box(
                        el.text, el.w, el.h, fs_authored)
                    font_stack = text_font_stack(el.font)
                    text_inner = _render_text_runs(el, default_color=text_color,
                                                    default_font=el.font, default_size=fs)
                    # Alignment: source-of-truth is the IWA paragraph style
                    # (TSWP.ParagraphStyleArchive.paraProperties.alignment).
                    # Fall back to bbox-center heuristic if the lookup misses
                    # (rare — typically when the text shape is purely on the
                    # master/template, which we don't index).
                    ta = (resolver.text_align_for_element(
                              slide.keynote_no, el.x, el.y, el.w, el.h)
                          or _text_align(el.x, el.w))
                    base_style = [
                        f"color:{text_color}",
                        f"font-family:{font_stack}",
                        f"font-size:{fs:.1f}px",
                        f"font-weight:{weight}",
                        f"font-style:{fstyle}",
                        "line-height:1.35",
                        "padding:8px 16px",
                        f"text-align:{ta}",
                    ]
                    if is_multirun:
                        # Block layout — let <span>s flow as inline text so
                        # \n→<br> creates lines and multi-style segments stay
                        # on the same line. Vertical centering via padding
                        # rather than flex (flex breaks <span> inline flow).
                        style_parts += base_style + [
                            "display:block",
                            # Approximate vertical centering by adjusting top
                            # padding when shape box is taller than text.
                            # (Flex would re-flow spans as items.)
                        ]
                    else:
                        # Single-run text — flex is fine and gives clean
                        # vertical centering of a single line.
                        align_items_v = "center"
                        justify = {"left":"flex-start", "center":"center",
                                   "right":"flex-end"}[ta]
                        style_parts += base_style + [
                            "display:flex",
                            f"align-items:{align_items_v}",
                            f"justify-content:{justify}",
                        ]
                # Element-level opacity is only needed when the shape has TEXT and is
                # translucent (because rgba bg already handles fill alpha; but text
                # color would stay opaque). For fill-only translucent overlays, rgba
                # alone is sufficient and we leave `opacity:1` so text inside other
                # overlapping divs isn't affected.
                if el.is_translucent and has_text:
                    style_parts.append(f"opacity:{el.css_opacity:.3f} !important")

                style = ";".join(p for p in style_parts if p) + ";" + rot.strip()
                parts.append(
                    f'<div class="el shape" style="{style}">{text_inner}</div>'
                )
            else:
                # No fill, no text from AppleScript. If IWA reports a fill
                # for this shape's bbox, emit it RIGHT HERE so source draw
                # order is preserved (the shape may sit BELOW a video — see
                # slide 18 where the black backdrop sits under a 42%-opaque
                # video). Otherwise it's a truly invisible authoring node.
                sf = iwa_fill_for_idx.get(idx)
                if sf is not None:
                    parts.append(_emit_iwa_fill_div(sf, in_place=True))
                else:
                    warnings.append(f"slide {slide.keynote_no} item {idx}: shape no fill/text — skipped")

        elif el.type == "text":
            if not el.text.strip():
                continue
            ta = (resolver.text_align_for_element(
                      slide.keynote_no, el.x, el.y, el.w, el.h)
                  or _text_align(el.x, el.w))
            # Container styling uses the FIRST run's font/size as the default.
            # When el.runs has multiple entries, individual <span>s override.
            font_stack = text_font_stack(el.font)
            text_color = el.text_color_hex
            size_authored = el.font_size or 24
            size = fit_font_to_box(el.text, el.w, el.h, size_authored, line_height=1.4)
            weight, fstyle = parse_font_weight_style(el.font)
            inner = _render_text_runs(el, default_color=text_color,
                                       default_font=el.font, default_size=size)
            parts.append(
                f'<div class="el" style="left:{el.x}px;top:{el.y}px;width:{el.w}px;'
                f'min-height:{el.h}px;color:{text_color};'
                f'font-family:{font_stack};font-size:{size:.1f}px;'
                f'font-weight:{weight};font-style:{fstyle};line-height:1.4;'
                f'text-align:{ta};{op_css}{rot}">'
                f'{inner}</div>'
            )

        else:
            # Horizontal / vertical LINES (other:line) — Keynote authors them as
            # zero-height (h=0) or zero-width separators. They can't be raster-
            # cropped (invalid crop region) but they're visually a 1-2px hairline.
            # Render as a thin div with a semi-transparent border. Catches the
            # divider lines used under card titles on slide 24, the section
            # underlines on slide 12 / 30 / 42, etc.
            if el.type == "other:line" and (el.h < 2 or el.w < 2):
                # horizontal hairline (h=0) or vertical hairline (w=0)
                line_color = "rgba(255,255,255,0.35)"
                if el.h < 2:
                    parts.append(
                        f'<div class="el" style="left:{el.x}px;top:{el.y - 1}px;'
                        f'width:{el.w}px;height:2px;background:{line_color};{rot}"></div>'
                    )
                else:
                    parts.append(
                        f'<div class="el" style="left:{el.x - 1}px;top:{el.y}px;'
                        f'width:2px;height:{el.h}px;background:{line_color};{rot}"></div>'
                    )
                continue

            # Other unsupported types (chart / table / other:*): raster fallback
            if raster.available():
                fb_path = raster.crop(
                    slide.keynote_no, el.x, el.y, el.w, el.h,
                    slide_assets_dir / f"_fallback-{el.type.replace(':','-')}-{idx}.png",
                )
                if fb_path:
                    rel = f"{slide_assets_subdir}/{fb_path.name}"
                    parts.append(
                        f'<img class="el" src="{html_lib.escape(rel)}" '
                        f'style="left:{el.x}px;top:{el.y}px;width:{el.w}px;'
                        f'height:{el.h}px;object-fit:cover;{rot}">'
                    )
                    continue
            warnings.append(
                f"slide {slide.keynote_no} item {idx}: unsupported type '{el.type}' "
                f"({int(el.w)}×{int(el.h)})"
            )

    # IWA-sourced shape backdrops. AppleScript reports `fill=none` for shapes
    # whose color comes from a parent ShapeStyle (translucent black masks,
    # card backdrops, banner pills — all driven by style inheritance). We
    # pull these from the IWA archive and render them here. z-index: 5 puts
    # them ABOVE images/videos (default z-auto) but BELOW text/text-shapes
    # (which we bump to z-index: 10 below).
    # End-of-slide pass: any IWA fills that DIDN'T match an AppleScript
    # shape (typically slides where AppleScript reported the body shape as
    # a tiny placeholder text stub — slides 20-23's 60% black mask is the
    # canonical case). Render with z-index:5 so they layer above raw
    # images/videos but below text. Matched fills were already emitted
    # in source-order position.
    for fi, sf in enumerate(iwa_fills):
        if fi in iwa_consumed:
            continue
        parts.append(_emit_iwa_fill_div(sf, in_place=False))

    return "\n".join(parts), warnings


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tsv", type=Path)
    ap.add_argument("key_bundle", type=Path,
                    help="Path to the .key bundle (directory containing Data/, Index.zip)")
    ap.add_argument("output_dir", type=Path)
    ap.add_argument("--limit", type=int, default=0)
    # Renderer skill — defaults to sibling `feishu-deck-h5`; any compatible
    # renderer skill works. Kept as a flag so this skill stays decoupled
    # from any specific renderer implementation.
    ap.add_argument("--renderer", type=Path,
                    default=Path(__file__).resolve().parents[2] / "feishu-deck-h5",
                    help="Path to renderer skill root (default: ../feishu-deck-h5/). "
                         "Decoupled so this skill can render against any compatible renderer.")
    ap.add_argument("--redesigns", type=Path, default=None,
                    help="Directory with per-slide HTML overrides "
                         "(slide-NN.html where NN is 1-based PDF page number). "
                         "When present, the file's HTML replaces auto-extracted "
                         "elements for that slide. Use for layouts that don't "
                         "map cleanly from Keynote (heavy tables, custom grids).")
    ap.add_argument("--rasters-dir", type=Path, default=None,
                    help="Directory with per-page PNGs (slide-NN.png) for fallback crops")
    ap.add_argument("--pdf", type=Path, default=None,
                    help="Source PDF for fallback rasterization (alternative to --rasters-dir)")
    args = ap.parse_args()

    if not args.tsv.is_file():
        print(f"ERROR: TSV not found: {args.tsv}", file=sys.stderr)
        return 1

    # Keynote 14.5+ can save `.key` as either a directory bundle (older default)
    # OR as a single zip file (newer default). Handle both. For zip form, extract
    # Data/ entries to <output>/.cache/Data/ once and reuse on subsequent runs.
    data_dir = args.key_bundle / "Data"
    if not data_dir.is_dir():
        import zipfile, shutil as _shutil
        if args.key_bundle.is_file() and zipfile.is_zipfile(args.key_bundle):
            cache_data = args.output_dir / ".cache" / "Data"
            if not cache_data.is_dir() or not any(cache_data.iterdir()):
                cache_data.mkdir(parents=True, exist_ok=True)
                print(f"==> extracting Data/ from zipped .key to {cache_data}/...")
                with zipfile.ZipFile(args.key_bundle) as zf:
                    for info in zf.infolist():
                        # FIX: Keynote stores UTF-8 filenames without setting the
                        # UTF-8 flag bit (0x800), so zipfile defaults to CP437
                        # decode → mojibake for Chinese names. Recode if needed.
                        raw_name = info.filename
                        if not (info.flag_bits & 0x800):
                            try:
                                raw_name = raw_name.encode("cp437").decode("utf-8")
                            except (UnicodeDecodeError, UnicodeEncodeError):
                                pass  # not recodable; keep as-is
                        if info.is_dir() or not raw_name.startswith("Data/"):
                            continue
                        name = Path(raw_name).name
                        if not name or name.startswith("."):
                            continue
                        target = cache_data / name
                        with zf.open(info) as src, open(target, "wb") as dst:
                            _shutil.copyfileobj(src, dst)
                print(f"    extracted {len(list(cache_data.iterdir()))} files")
            data_dir = cache_data
        else:
            print(f"ERROR: not a .key bundle (no Data/) and not a .key zip: {args.key_bundle}", file=sys.stderr)
            return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"==> parsing TSV: {args.tsv}")
    total, slides = parse_tsv(args.tsv)
    non_skipped = [s for s in slides if not s.skipped]
    print(f"    total slides: {total}  ·  non-skipped: {len(non_skipped)}")

    if args.limit:
        non_skipped = non_skipped[: args.limit]
        print(f"    limit: building first {len(non_skipped)} slides")

    # Build IWA-derived per-slide asset map from the .key bundle. This is
    # the deterministic ground truth for image/movie resolution — used by
    # resolver.resolve_for_element. Heuristic fallback still kicks in if a
    # bbox match misses or keynote-parser isn't installed.
    iwa_map = None
    if _IWA_AVAILABLE:
        try:
            iwa_map = IWAAssetMap.from_key(args.key_bundle)
            n_assets = sum(len(iwa_map.assets_for_slide(s)) for s in range(1, 200))
            print(f"    IWA asset map: {n_assets} image/movie refs across slides")
        except Exception as e:
            print(f"    IWA asset map: build failed ({e}); falling back to heuristic only")
    else:
        print(f"    IWA asset map: keynote-parser not installed; heuristic-only resolution")

    resolver = AssetResolver(data_dir, args.output_dir / "assets", iwa_map=iwa_map)
    raster = RasterFallback(
        rasters_dir=args.rasters_dir,
        pdf_path=args.pdf,
        slides_with_kn_no=[s.keynote_no for s in non_skipped],
    )
    if raster.available():
        src_kind = "rasters-dir" if args.rasters_dir else "pdf"
        print(f"    raster fallback: {src_kind} available")
    else:
        print(f"    raster fallback: none (unhandled elements will show placeholders)")

    deck_slides = []
    all_warnings: list[str] = []

    # Optional per-slide HTML overrides — for layouts that don't map cleanly
    # from Keynote (heavy tables, custom grids, side-by-side phones). Each file
    # in --redesigns is `slide-NN.html` (NN = 1-based PDF page number); its
    # contents replace the auto-extracted slide body entirely.
    redesigns_dir = args.redesigns
    if redesigns_dir and redesigns_dir.is_dir():
        n_redesigns = sum(1 for f in redesigns_dir.glob("slide-*.html"))
        print(f"    redesigns: {n_redesigns} override(s) available in {redesigns_dir}")
    elif redesigns_dir:
        print(f"    redesigns: dir not found, ignoring: {redesigns_dir}")

    for i, slide in enumerate(non_skipped, start=1):
        sub = f"assets/slide-{slide.keynote_no:03d}"
        slide_assets_dir = args.output_dir / sub

        # Redesign override? Two filename conventions are accepted:
        #   · `slide-NN.html`  (2-digit) — matches by PDF page index (1..62)
        #   · `slide-NNN.html` (3-digit, zero-padded) — matches by the
        #     underlying Keynote slide number (slide.keynote_no, includes
        #     skipped slides; matches the deck.json `key`). Useful when
        #     re-ordering / hiding slides shouldn't break a redesign.
        # PDF-index form wins if both exist (more specific to current render).
        override_html = None
        override_label = ""
        if redesigns_dir:
            for cand_name in (f"slide-{i:02d}.html",
                              f"slide-{slide.keynote_no:03d}.html"):
                cand = redesigns_dir / cand_name
                if cand.is_file():
                    override_html = cand.read_text(encoding="utf-8")
                    override_label = cand_name
                    break

        if override_html is not None:
            html_body = override_html
            warns_count = 0
            label = f"REDESIGN {override_label}"
        else:
            html_body, warns = compose_slide_html(slide, resolver, raster, sub, slide_assets_dir)
            all_warnings.extend(warns)
            warns_count = len(warns)
            label = f"keynote-slide {slide.keynote_no:2d}  ·  {len(slide.elements)} elements"

        deck_slides.append({
            "key": f"slide-{slide.keynote_no:03d}",
            "layout": "raw",
            "screen_label": f"{i:02d}",
            "data": {"html": html_body},
        })
        print(f"  · pdf-page {i:2d}  ←  {label}"
              + (f"  ⚠ {warns_count}" if warns_count else ""))

    deck = {
        "version": "1.0",
        "deck": {
            "title": args.output_dir.parent.name,
            "language": "zh-only",
            "mode": "rewrite",
        },
        "slides": deck_slides,
    }
    deck_path = args.output_dir / "deck.json"
    deck_path.write_text(json.dumps(deck, ensure_ascii=False, indent=2))
    print(f"\n==> wrote deck.json with {len(deck_slides)} slides")

    if all_warnings:
        warnings_path = args.output_dir / "warnings.txt"
        warnings_path.write_text("\n".join(all_warnings))
        print(f"    ⚠ {len(all_warnings)} warnings → {warnings_path.name}")

    render_script = args.renderer / "deck-json/render-deck.py"
    if not render_script.is_file():
        print(f"ERROR: render-deck.py not at {render_script}", file=sys.stderr)
        return 1

    print(f"\n==> rendering via feishu-deck-h5/render-deck.py")
    cmd = [
        sys.executable, str(render_script),
        str(deck_path), str(args.output_dir),
        "--skip-validate-html", "--skip-texts", "--skip-copy-assets",
        # We re-localize the HTML's renderer refs ourselves below — the
        # renderer's bundled copy-assets.py expects a `runs/<ts>/output/`
        # layout which doesn't apply when this skill is the orchestrator.
        # Our localizer is smaller and works for any output directory.
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("RENDER FAILED:", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1

    for line in (result.stdout.strip().splitlines() or [""])[-5:]:
        print(f"    {line}")

    # Localize the renderer's CSS/JS refs. After render-deck.py finishes,
    # index.html contains <link>/<script> URLs like
    #   ../../../skills/feishu-deck-h5/assets/feishu-deck.css
    # which only resolve when serving from above the skill root — they break
    # the moment you serve from the output dir (paths escape the server
    # root → 404 → all slides stack unstyled, JS doesn't run, no nav).
    # Copy each referenced renderer file into <output>/_renderer/ and
    # rewrite the HTML to use that local path. Result: output dir is
    # self-contained and `bash serve.sh` Just Works.
    _localize_renderer_refs(args.output_dir / "index.html",
                             args.output_dir / "_renderer",
                             args.renderer)

    # Drop a one-line `serve.sh` next to index.html. Browsers (esp. Chrome)
    # impose extra restrictions on file:// — CORS, certain SVG references,
    # cache aggressiveness — that don't show under http://. The serve script
    # gives a deterministic "double-click to view" path.
    serve_path = args.output_dir / "serve.sh"
    serve_path.write_text(
        '#!/usr/bin/env bash\n'
        '# Serve this deck on localhost:8765 so the browser uses http:// not file://.\n'
        '# (file:// has CORS/SVG/cache quirks that don\'t show under http://.)\n'
        'set -e\n'
        'cd "$(dirname "$0")"\n'
        'PORT="${1:-8765}"\n'
        'echo "==> serving on http://localhost:$PORT/index.html"\n'
        'python3 -m http.server "$PORT"\n'
    )
    serve_path.chmod(0o755)

    print(f"\n==> DONE  →  {args.output_dir / 'index.html'}")
    print(f"          or  bash {serve_path}  (recommended — avoids file:// quirks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
