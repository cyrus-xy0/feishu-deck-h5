"""iwa_resolver.py — deterministic per-slide asset map from a .key bundle.

Why this exists
---------------
AppleScript reports image/movie elements with only a `file name` basename
(e.g. "已粘贴的图像.png", or sometimes empty). Multiple Data/ files can
match that stem after suffix stripping, and our prior AssetResolver had to
guess between them by aspect/size. That guessing was wrong on slides where
two images shared the same base name but lived at different bbox positions
(e.g. slide PDF-page 45 was picking 10793.png when the right answer was
已粘贴的图像-9115.png).

The .key bundle itself has the ground truth. Each `Index/Slide-<id>.iwa`
lists its drawables; image/movie drawables reference a numeric data-id;
`Index/Metadata.iwa` maps data-id → on-disk filename. We follow this chain
and key the result by (slide_no_1based, bbox) so the resolver in build.py
can look up the exact filename without guessing.

Usage
-----
    m = IWAAssetMap.from_key(Path("foo.key"))
    fname = m.lookup(slide_no=45, x=-7.6, y=6.5, w=1935, h=1097)
    # → "已粘贴的图像-9115.png" or None

slide_no is 1-based and matches AppleScript's iteration order (which
includes skipped slides — same as `current.keynote_no` in build.py).
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


import re

# AppleScript reports an element's VISIBLE mask region; IWA stores the
# image's natural frame. Same image, different bbox — so we can't bbox-match
# directly. Strategy:
#   1. Filter slide's IWA assets by file_name stem (strip trailing -NNNN data
#      id suffix and ".ext"). Usually narrows to one.
#   2. If still multiple, fall back to a fuzzy bbox proximity ranking.
#   3. If file_name is empty (some inserted movies), use kind + bbox.


def _gradient_to_css(gradient: dict) -> str:
    """Convert an IWA gradient dict into a CSS `linear-gradient(...)` string.

    Keynote angle convention: radians, counter-clockwise from +x axis.
    CSS angle convention: degrees, clockwise from up (`0deg` = bottom-to-top).
    Transform: css_deg = (90 - kn_deg) mod 360
    """
    import math
    stops = gradient.get("stops") or []
    if not stops:
        return ""
    # Angle (linear gradient only — radial not yet handled, fall back to vertical)
    angle_rad = (gradient.get("anglegradient") or {}).get("gradientangle", math.pi / 2)
    try:
        angle_rad = float(angle_rad)
    except (TypeError, ValueError):
        angle_rad = math.pi / 2
    angle_deg_kn = math.degrees(angle_rad)
    angle_deg_css = (90.0 - angle_deg_kn) % 360.0
    css_stops = []
    for s in stops:
        c = s.get("color") or {}
        r = int(round(float(c.get("r") or 0) * 255))
        g = int(round(float(c.get("g") or 0) * 255))
        b = int(round(float(c.get("b") or 0) * 255))
        a = float(c.get("a") if c.get("a") is not None else 1.0)
        frac_pct = float(s.get("fraction") or 0) * 100.0
        css_stops.append(f"rgba({r},{g},{b},{a:.3f}) {frac_pct:.1f}%")
    # Multiply style-level opacity in later — we leave that to the caller
    return f"linear-gradient({angle_deg_css:.1f}deg, {', '.join(css_stops)})"


def _strip_data_id_suffix(name: str) -> str:
    """`已粘贴的图像-9115.png` → `已粘贴的图像` ;  `image-2-1.png` → `image-2-1`.

    Only strip a trailing `-NNNN+` that's at least 4 digits (Keynote's data
    id format is always large numbers). A trailing `-1` is part of the real
    name and must NOT be stripped (`image-2-1.png` stem is `image-2-1`).
    """
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return re.sub(r"-\d{4,}$", "", stem)


@dataclass
class _Asset:
    slide_no: int          # 1-based, matches AppleScript order
    kind: str              # "image" or "movie"
    x: float
    y: float
    w: float
    h: float
    filename: str          # actual on-disk name under Data/
    # When True, the underlying TSD.ImageArchive has a `mask` field —
    # Keynote applied a crop/mask to the image. In that case the visible
    # display bbox is SMALLER than this asset's geometry; AppleScript
    # reports the masked visible region (which is what we want to render
    # at). When False, the image renders at its full geometry (no mask)
    # and AppleScript may report a narrower clipped bbox by mistake —
    # use THIS asset's bbox to avoid object-fit:cover side-cropping.
    has_mask: bool = False


@dataclass
class _TextAlign:
    slide_no: int
    x: float
    y: float
    w: float
    h: float
    align: str             # "left" / "center" / "right" / "justify" / "natural"


@dataclass
class _ShapeFill:
    """Translucent / colored / gradient shape backdrop derived from IWA
    style chain.

    AppleScript reports many shape fills as `fill=none` — color comes from
    a parent ShapeStyle, not a direct assignment. We surface here:
      · solid color fills (r,g,b,alpha)
      · linear gradient fills (gradient_css carries the full CSS string)
    `gradient_css`, when non-empty, is the source-of-truth — render via
    `background: <gradient_css>;` and ignore the r/g/b fields.
    """
    slide_no: int
    x: float
    y: float
    w: float
    h: float
    r: int                 # 0-255 (solid fill path)
    g: int
    b: int
    alpha: float           # 0..1 (solid fill path: color-alpha × style opacity)
    has_text: bool
    gradient_css: str = ""  # non-empty → use this instead of rgba(r,g,b,a)


# Map TSWP TextAlignmentType enum (TATvalue0..4) to CSS-friendly strings.
# Keynote / iWork proto convention (verified empirically against centered
# title shapes in test decks):
#   0 = left, 1 = right, 2 = center, 3 = justify, 4 = natural (locale default)
_TAT_TO_ALIGN = {
    "TATvalue0": "left",
    "TATvalue1": "right",
    "TATvalue2": "center",
    "TATvalue3": "justify",
    "TATvalue4": "natural",
}


class IWAAssetMap:
    def __init__(self, assets: list[_Asset], text_aligns: list[_TextAlign] = None,
                 shape_fills: list[_ShapeFill] = None,
                 master_bboxes: dict = None):
        self._assets = assets
        self._by_slide: dict[int, list[_Asset]] = {}
        for a in assets:
            self._by_slide.setdefault(a.slide_no, []).append(a)
        self._aligns_by_slide: dict[int, list[_TextAlign]] = {}
        for ta in (text_aligns or []):
            self._aligns_by_slide.setdefault(ta.slide_no, []).append(ta)
        self._fills_by_slide: dict[int, list[_ShapeFill]] = {}
        for sf in (shape_fills or []):
            self._fills_by_slide.setdefault(sf.slide_no, []).append(sf)
        # (slide_no, filename) → (x, y, w, h) of the image IN THE TEMPLATE.
        # AppleScript reports master images at their CLIPPED bbox (the visible
        # region intersected with the canvas), which mis-positions tall/wide
        # template backgrounds — `up@2x.png` is 2048×6456 but AppleScript said
        # 1958×2076, so object-fit:cover shows the wrong slice. The template
        # IWA has the TRUE placement; we render at that.
        self._master_bbox: dict[tuple[int, str], tuple[float, float, float, float]] = master_bboxes or {}

    def master_bbox(self, slide_no: int, file_name: str) -> Optional[tuple[float, float, float, float]]:
        """Return (x, y, w, h) of a master/template image as positioned IN
        the template, or None if not in our map. Match by file_name stem
        (slide_no is a future hint — for now, templates with the same
        image use the same bbox across slides, so a global filename match
        is fine)."""
        if not file_name:
            return None
        stem = _strip_data_id_suffix(file_name)
        # First try (slide_no, fn) exact stem match
        for (sn, fn), bbox in self._master_bbox.items():
            if sn == slide_no and _strip_data_id_suffix(fn) == stem:
                return bbox
        # Fall back to ANY slide's template that has this filename stem
        for (sn, fn), bbox in self._master_bbox.items():
            if _strip_data_id_suffix(fn) == stem:
                return bbox
        return None

    def shape_fills_for_slide(self, slide_no: int) -> list[_ShapeFill]:
        """All ShapeInfo-archive fills on this slide, in IWA archive order."""
        return list(self._fills_by_slide.get(slide_no, []))

    def lookup_with_bbox(self, slide_no: int, x: float, y: float, w: float, h: float,
                         file_name: Optional[str] = None,
                         kind: Optional[str] = None) -> Optional[tuple]:
        """Like `lookup`, but returns (filename, (x, y, w, h), has_mask)."""
        candidates = self._by_slide.get(slide_no, [])
        if kind:
            candidates = [a for a in candidates if a.kind == kind]
        if not candidates:
            return None
        if file_name:
            ap_stem = _strip_data_id_suffix(file_name)
            stem_hits = [a for a in candidates
                         if _strip_data_id_suffix(a.filename) == ap_stem]
            if not stem_hits:
                return None
            candidates = stem_hits
        if len(candidates) == 1:
            a = candidates[0]
            return (a.filename, (a.x, a.y, a.w, a.h), a.has_mask)
        best = max(candidates, key=lambda a: _bbox_score(a, x, y, w, h))
        return (best.filename, (best.x, best.y, best.w, best.h), best.has_mask)

    def lookup(self, slide_no: int, x: float, y: float, w: float, h: float,
               file_name: Optional[str] = None,
               kind: Optional[str] = None) -> Optional[str]:
        """Return the Data/ filename matching this element, or None.

        Match strategy (in order):
          1. Same kind (image vs movie) — if `kind` is given.
          2. If `file_name` is given, filter by stem match (strip data-id
             suffix and extension). This usually disambiguates uniquely,
             because two elements on the same slide rarely share a stem.
          3. If still > 1 candidate, pick the one whose bbox is closest
             (best size-overlap heuristic — see _bbox_score).
          4. If file_name is empty (some inserted movies have no exposable
             name), fall straight through to bbox-only.
        """
        candidates = self._by_slide.get(slide_no, [])
        if kind:
            candidates = [a for a in candidates if a.kind == kind]
        if not candidates:
            return None

        if file_name:
            ap_stem = _strip_data_id_suffix(file_name)
            stem_hits = [a for a in candidates
                         if _strip_data_id_suffix(a.filename) == ap_stem]
            if not stem_hits:
                # NO stem match. Critical: don't fall back to bbox scoring
                # across unrelated assets — that pairs a master logo to a
                # random phone screenshot just because positions are close.
                # Hand back to the caller so the legacy stem+dim heuristic
                # (which has its own scope) can have a shot.
                return None
            candidates = stem_hits

        if len(candidates) == 1:
            return candidates[0].filename

        # Tiebreaker among stem-matched candidates: bbox proximity. Also
        # covers the empty-file_name case where caller passed kind only
        # (e.g. a movie whose AppleScript file_name is "" — fall through
        # to bbox match within that kind).
        best = max(candidates, key=lambda a: _bbox_score(a, x, y, w, h))
        return best.filename

    def assets_for_slide(self, slide_no: int) -> list[_Asset]:
        return list(self._by_slide.get(slide_no, []))

    def text_alignment(self, slide_no: int, x: float, y: float,
                       w: float, h: float) -> Optional[str]:
        """Return CSS alignment ("left"/"center"/"right"/"justify") for the
        text element at this bbox, or None if not known.

        IWA stores text shapes with the AUTHORED width but often h=0 (text
        auto-fits to content). AppleScript reports the RENDERED bbox with
        a real height. So bbox-area overlap doesn't work — we score by
        horizontal extent overlap + vertical center proximity instead.
        """
        candidates = self._aligns_by_slide.get(slide_no, [])
        if not candidates:
            return None

        def score(ta: _TextAlign) -> float:
            # Horizontal overlap (the dimension alignment cares about)
            ox = max(0.0, min(ta.x + ta.w, x + w) - max(ta.x, x))
            x_score = ox / max(min(ta.w, w), 1.0)  # 1.0 = fully overlapping
            # Vertical center distance (in slide-height units)
            dy = abs((ta.y + ta.h / 2) - (y + h / 2)) / 1080.0
            return x_score - dy  # prefer high x-overlap, low y-distance

        best = max(candidates, key=score)
        if score(best) < 0.5:  # weak match — caller should fall back
            return None
        if best.align == "natural":
            return None
        return best.align

    @classmethod
    def from_key(cls, key_path: Path) -> "IWAAssetMap":
        """Build the map by parsing a .key bundle (single-file zip OR
        directory bundle — both forms have an `Index/` tree of .iwa files).
        """
        try:
            from keynote_parser.codec import IWAFile
        except ImportError as e:
            raise RuntimeError(
                "keynote-parser package required for IWA resolution. "
                "Install with: pip install keynote-parser"
            ) from e

        # Open as either zip or directory bundle. Directory case left for
        # forward compatibility — we exercise the zip path on Keynote 14.5+.
        if key_path.is_file() and zipfile.is_zipfile(key_path):
            opener = _ZipOpener(key_path)
        elif key_path.is_dir():
            opener = _DirOpener(key_path)
        else:
            raise RuntimeError(f"not a .key file or bundle: {key_path}")

        with opener as o:
            # 1. data_id → on-disk filename (from Metadata.iwa's
            # PackageMetadata.datas list)
            meta_d = IWAFile.from_buffer(o.read("Index/Metadata.iwa")).to_dict()
            data_id_to_filename: dict[str, str] = {}
            for chunk in meta_d.get("chunks", []):
                for ar in chunk.get("archives", []):
                    for obj in ar.get("objects", []):
                        if obj.get("_pbtype") == "TSP.PackageMetadata":
                            for d in obj.get("datas", []):
                                # "fileName" is the on-disk name in Data/;
                                # fall back to preferredFileName if missing.
                                fn = d.get("fileName") or d.get("preferredFileName")
                                if fn:
                                    data_id_to_filename[d["identifier"]] = fn

            # 2. Slide order: KN.ShowArchive.slideTree.slides is the ordered
            # list of SlideNodeArchive ids; each node points to a SlideArchive
            # id which matches `Index/Slide-<id>.iwa`. Order INCLUDES skipped
            # slides, matching AppleScript's iteration.
            doc_d = IWAFile.from_buffer(o.read("Index/Document.iwa")).to_dict()
            node_order: list[str] = []
            node_to_slide_arch: dict[str, str] = {}
            for chunk in doc_d.get("chunks", []):
                for ar in chunk.get("archives", []):
                    for obj in ar.get("objects", []):
                        t = obj.get("_pbtype")
                        if t == "KN.ShowArchive":
                            for ref in obj.get("slideTree", {}).get("slides", []):
                                node_order.append(ref["identifier"])
                        elif t == "KN.SlideNodeArchive":
                            nid = ar["header"]["identifier"]
                            node_to_slide_arch[nid] = obj["slide"]["identifier"]
            slide_arch_order = [node_to_slide_arch[n] for n in node_order
                                if n in node_to_slide_arch]

            # 3a. Pre-pass A: index ParagraphStyleArchive entries (source of
            # truth for text alignment). Most styles live in
            # DocumentStylesheet.iwa, but per-slide overrides can live in the
            # slide's own iwa.
            para_align: dict[str, str] = {}  # arch_id → "left"/"center"/etc.
            # Pre-pass B: index ShapeStyleArchive entries (source of truth for
            # shape fill color + opacity). Walk parent chain to resolve.
            shape_style_raw: dict[str, dict] = {}  # arch_id → {fill, opacity, parent}
            for n in (("Index/DocumentStylesheet.iwa",) +
                      tuple(f"Index/Slide-{a}.iwa" for a in slide_arch_order
                            if f"Index/Slide-{a}.iwa" in set(o.namelist()))):
                try:
                    d = IWAFile.from_buffer(o.read(n)).to_dict()
                except Exception:
                    continue
                for chunk in d.get("chunks", []):
                    for ar in chunk.get("archives", []):
                        for obj in ar.get("objects", []):
                            t = obj.get("_pbtype")
                            arid = ar["header"]["identifier"]
                            if t == "TSWP.ParagraphStyleArchive":
                                pp = obj.get("paraProperties") or {}
                                a = pp.get("alignment")
                                if a in _TAT_TO_ALIGN:
                                    para_align[arid] = _TAT_TO_ALIGN[a]
                            elif t == "TSWP.ShapeStyleArchive":
                                # TSWP.ShapeStyleArchive nests:
                                #   super.super.parent.identifier  → parent style
                                #   super.shapeProperties           → overrides (incl. opacity)
                                # And TSP.StylePropertyTable on super.super
                                # carries the bulk properties (fill etc).
                                # We capture raw and resolve later.
                                sup = obj.get("super", {}) or {}
                                ssup = sup.get("super", {}) or {}
                                parent = (ssup.get("parent") or {}).get("identifier")
                                # Properties at this style's level live on
                                # sup.shapeProperties (overrides) AND on
                                # ssup.shapeProperties (the "real" props).
                                own_props = (sup.get("shapeProperties") or {})
                                base_props = (ssup.get("shapeProperties") or {})
                                shape_style_raw[arid] = {
                                    "parent": parent,
                                    "own": own_props,
                                    "base": base_props,
                                }

            # Resolve shape-style chain. Returns dict with keys:
            #   "kind": "color" | "gradient" | None
            #   "color": (r,g,b,a) tuple in 0..1, when kind == "color"
            #   "gradient_css": full CSS linear-gradient(...) string, when kind == "gradient"
            #   "opacity": 0..1, the style-level alpha multiplier
            # A gradient fill in any level wins over a color fill in parents
            # (gradient is a complete fill spec, not an additive override).
            def _resolve_shape_style(sid: str, seen=None) -> dict:
                if seen is None: seen = set()
                if not sid or sid in seen or sid not in shape_style_raw:
                    return {"kind": None, "color": None, "gradient_css": "", "opacity": 1.0}
                seen.add(sid)
                raw = shape_style_raw[sid]
                parent = _resolve_shape_style(raw["parent"], seen)
                kind = parent["kind"]
                color = parent["color"]
                grad = parent["gradient_css"]
                op = parent["opacity"]
                # Walk own → base properties (own overrides base overrides parent)
                for src in (raw["base"], raw["own"]):
                    if not isinstance(src, dict): continue
                    fill = src.get("fill")
                    if isinstance(fill, dict):
                        # Gradient (linear)
                        gradient = fill.get("gradient")
                        if isinstance(gradient, dict) and gradient.get("stops"):
                            css = _gradient_to_css(gradient)
                            if css:
                                kind, color, grad = "gradient", None, css
                        else:
                            c = fill.get("color")
                            if isinstance(c, dict) and "r" in c:
                                color = (float(c.get("r") or 0),
                                         float(c.get("g") or 0),
                                         float(c.get("b") or 0),
                                         float(c.get("a") if c.get("a") is not None else 1.0))
                                kind, grad = "color", ""
                    if "opacity" in src and src["opacity"] is not None:
                        op = float(src["opacity"])
                return {"kind": kind, "color": color, "gradient_css": grad, "opacity": op}

            # 3b. Per-slide pass: collect image/movie drawables AND text-shape
            # alignments. For each slide:
            #   · Find TSD.ImageArchive / TSD.MovieArchive → asset map
            #   · Find TSWP.ShapeInfoArchive / KN.PlaceholderArchive → look up
            #     its ownedStorage → first paragraph style → alignment.
            all_names = set(o.namelist())
            assets: list[_Asset] = []
            text_aligns: list[_TextAlign] = []
            shape_fills: list[_ShapeFill] = []
            # (slide_no, on-disk filename) → (x, y, w, h) from the slide's
            # templateSlide chain. Captures the TRUE placement of master/
            # template images (which AppleScript reports clipped to canvas).
            master_bboxes: dict[tuple[int, str], tuple[float, float, float, float]] = {}

            # Pre-pass: build slide_no → templateSlide arch_id mapping via
            # SlideNodeArchive. Then for each template_id, scan its IWA
            # (either Index/TemplateSlide-<id>.iwa, or Index/TemplateSlide.iwa
            # which holds the global default(s)) for image/movie drawables.
            slide_to_template: dict[int, str] = {}
            for slide_no, arch_id in enumerate(slide_arch_order, 1):
                iwa_name = f"Index/Slide-{arch_id}.iwa"
                if iwa_name not in all_names:
                    continue
                try:
                    sd = IWAFile.from_buffer(o.read(iwa_name)).to_dict()
                except Exception:
                    continue
                for chunk in sd.get("chunks", []):
                    for ar in chunk.get("archives", []):
                        for obj in ar.get("objects", []):
                            if obj.get("_pbtype") == "KN.SlideArchive":
                                tpl = (obj.get("templateSlide") or {}).get("identifier")
                                if tpl:
                                    slide_to_template[slide_no] = tpl

            # Pre-pass: index template_id → list of image_archives. Templates
            # can live in `Index/TemplateSlide-<id>.iwa` (per-template file)
            # OR in `Index/TemplateSlide.iwa` (one file may hold several
            # default templates). Walk both.
            template_images: dict[str, list[tuple[str, float, float, float, float]]] = {}
            # filename = filename ; tuple = (filename, x, y, w, h)

            def _index_template_iwa(name: str):
                try:
                    td = IWAFile.from_buffer(o.read(name)).to_dict()
                except Exception:
                    return
                # In TemplateSlide.iwa multiple slide archives may coexist;
                # group images by which SlideArchive's ownedDrawables they
                # belong to.
                for chunk in td.get("chunks", []):
                    # Build local lookup: drawable_arch_id → SlideArchive_id
                    drawable_to_slide: dict[str, str] = {}
                    slide_archives: dict[str, dict] = {}
                    for ar in chunk.get("archives", []):
                        for obj in ar.get("objects", []):
                            if obj.get("_pbtype") == "KN.SlideArchive":
                                sarid = ar["header"]["identifier"]
                                slide_archives[sarid] = obj
                                for dr in obj.get("ownedDrawables", []):
                                    drawable_to_slide[dr["identifier"]] = sarid
                    for ar in chunk.get("archives", []):
                        for obj in ar.get("objects", []):
                            t = obj.get("_pbtype", "")
                            if t in ("TSD.ImageArchive", "TSD.MovieArchive"):
                                if t == "TSD.ImageArchive":
                                    ref = obj.get("data") or {}
                                else:
                                    ref = obj.get("movieData") or {}
                                data_id = ref.get("identifier")
                                fname = data_id_to_filename.get(data_id) if data_id else None
                                if not fname:
                                    continue
                                geo = obj.get("super", {}).get("geometry", {}) or {}
                                pos = geo.get("position", {}) or {}
                                size = geo.get("size", {}) or {}
                                bbox = (
                                    float(pos.get("x", 0) or 0),
                                    float(pos.get("y", 0) or 0),
                                    float(size.get("width", 0) or 0),
                                    float(size.get("height", 0) or 0),
                                )
                                # Which template SlideArchive owns this drawable?
                                arid = ar["header"]["identifier"]
                                owner = drawable_to_slide.get(arid)
                                if owner:
                                    template_images.setdefault(owner, []).append((fname, *bbox))

            for n in all_names:
                if n.startswith("Index/TemplateSlide") and n.endswith(".iwa"):
                    _index_template_iwa(n)

            # For each slide, register: (a) bboxes from its direct
            # templateSlide; (b) ALL template images globally (keyed by a
            # sentinel slide_no=-1). AppleScript's `base layout` resolves
            # via Keynote's internal master inheritance, which doesn't
            # always match the IWA `templateSlide` ref (slide 5's
            # templateSlide is an empty "blank" but AppleScript reports
            # up@2x.png from a parent master). The global fallback handles
            # that case.
            for slide_no, tpl_id in slide_to_template.items():
                for (fname, x, y, w, h) in template_images.get(tpl_id, []):
                    master_bboxes[(slide_no, fname)] = (x, y, w, h)
            for tpl_id, imgs in template_images.items():
                for (fname, x, y, w, h) in imgs:
                    # Don't overwrite a slide-specific entry
                    key = (-1, fname)
                    master_bboxes.setdefault(key, (x, y, w, h))
            for slide_no, arch_id in enumerate(slide_arch_order, 1):
                iwa_name = f"Index/Slide-{arch_id}.iwa"
                if iwa_name not in all_names:
                    continue
                slide_d = IWAFile.from_buffer(o.read(iwa_name)).to_dict()

                # First pass on this iwa: build a local storage-arch lookup so
                # we can resolve ShapeInfo → Storage → ParaStyle within one
                # slide without rescanning.
                storage_first_para: dict[str, Optional[str]] = {}
                for chunk in slide_d.get("chunks", []):
                    for ar in chunk.get("archives", []):
                        for obj in ar.get("objects", []):
                            if obj.get("_pbtype") == "TSWP.StorageArchive":
                                tps = obj.get("tableParaStyle") or {}
                                entries = tps.get("entries") or []
                                first = None
                                if entries:
                                    first = (entries[0].get("object") or {}).get("identifier")
                                storage_first_para[ar["header"]["identifier"]] = first

                for chunk in slide_d.get("chunks", []):
                    for ar in chunk.get("archives", []):
                        for obj in ar.get("objects", []):
                            t = obj.get("_pbtype", "")
                            # Asset extraction
                            if t in ("TSD.ImageArchive", "TSD.MovieArchive"):
                                if t == "TSD.ImageArchive":
                                    ref = obj.get("data") or {}
                                    kind = "image"
                                else:
                                    ref = obj.get("movieData") or {}
                                    kind = "movie"
                                data_id = ref.get("identifier")
                                fname = data_id_to_filename.get(data_id) if data_id else None
                                if fname:
                                    geo = obj.get("super", {}).get("geometry", {}) or {}
                                    pos = geo.get("position", {}) or {}
                                    size = geo.get("size", {}) or {}
                                    # `mask` field signals Keynote applied
                                    # a crop on this image — AppleScript
                                    # bbox is the visible masked region;
                                    # this asset's geometry is the underlying
                                    # natural placement.
                                    has_mask = bool(obj.get("mask"))
                                    assets.append(_Asset(
                                        slide_no=slide_no, kind=kind,
                                        x=float(pos.get("x", 0) or 0),
                                        y=float(pos.get("y", 0) or 0),
                                        w=float(size.get("width", 0) or 0),
                                        h=float(size.get("height", 0) or 0),
                                        filename=fname,
                                        has_mask=has_mask,
                                    ))
                                continue

                            # Shape archives (text-bearing or pure backdrops).
                            # Used for TWO purposes:
                            #   · text alignment (resolved via paragraph style)
                            #   · shape fill backdrop (resolved via shape style)
                            if t in ("TSWP.ShapeInfoArchive", "KN.PlaceholderArchive"):
                                # Geometry path differs between shape and placeholder.
                                geo = (obj.get("super", {}).get("super", {}).get("geometry")
                                       or obj.get("super", {}).get("geometry") or {})
                                pos = geo.get("position", {}) or {}
                                size = geo.get("size", {}) or {}
                                w = float(size.get("width", 0) or 0)
                                h = float(size.get("height", 0) or 0)
                                # Skip true empty placeholders.
                                if w == 0 and h == 0:
                                    continue
                                px = float(pos.get("x", 0) or 0)
                                py = float(pos.get("y", 0) or 0)

                                storage_ref = (obj.get("ownedStorage")
                                               or obj.get("deprecatedStorage") or {})
                                storage_id = storage_ref.get("identifier")
                                has_text = bool(storage_id)

                                # Alignment
                                if storage_id:
                                    para_id = storage_first_para.get(storage_id)
                                    align = para_align.get(para_id) if para_id else None
                                    if align:
                                        text_aligns.append(_TextAlign(
                                            slide_no=slide_no,
                                            x=px, y=py, w=w, h=h, align=align,
                                        ))

                                # Shape fill — read via TSWP.ShapeStyleArchive
                                # parent chain. AppleScript can't surface these.
                                style_id = (obj.get("super", {}).get("style") or {}).get("identifier")
                                if style_id:
                                    rs = _resolve_shape_style(style_id)
                                    op = rs.get("opacity", 1.0)
                                    if rs.get("kind") == "gradient":
                                        css = rs.get("gradient_css") or ""
                                        if css and op > 0.02:
                                            shape_fills.append(_ShapeFill(
                                                slide_no=slide_no,
                                                x=px, y=py, w=w, h=h,
                                                r=0, g=0, b=0,
                                                alpha=op,
                                                has_text=has_text,
                                                gradient_css=css,
                                            ))
                                    elif rs.get("kind") == "color":
                                        color = rs.get("color")
                                        if color is not None:
                                            r, g, b, a = color
                                            eff_alpha = a * op
                                            if eff_alpha > 0.02:
                                                shape_fills.append(_ShapeFill(
                                                    slide_no=slide_no,
                                                    x=px, y=py, w=w, h=h,
                                                    r=int(round(r * 255)),
                                                    g=int(round(g * 255)),
                                                    b=int(round(b * 255)),
                                                    alpha=eff_alpha,
                                                    has_text=has_text,
                                                ))
        return cls(assets, text_aligns, shape_fills, master_bboxes=master_bboxes)


def _bbox_score_xywh(ax: float, ay: float, aw: float, ah: float,
                     bx: float, by: float, bw: float, bh: float) -> float:
    """IoU-ish bbox overlap; positive on overlap, negative-distance otherwise."""
    inter_w = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    inter_h = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = inter_w * inter_h
    if inter == 0:
        acx, acy = ax + aw / 2, ay + ah / 2
        bcx, bcy = bx + bw / 2, by + bh / 2
        return -(((acx - bcx) ** 2 + (acy - bcy) ** 2) / 1e6)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _bbox_score(a: _Asset, x: float, y: float, w: float, h: float) -> float:
    return _bbox_score_xywh(a.x, a.y, a.w, a.h, x, y, w, h)


# ----------------------------------------------------------------------------
# Opener abstraction so the .key zip and (legacy) directory bundle share a
# single read-by-name interface.
# ----------------------------------------------------------------------------

class _ZipOpener:
    def __init__(self, p: Path):
        self.p = p

    def __enter__(self):
        self._zf = zipfile.ZipFile(self.p)
        self._names = set(self._zf.namelist())
        return self

    def __exit__(self, *exc):
        self._zf.close()

    def read(self, name: str) -> bytes:
        return self._zf.read(name)

    def namelist(self) -> list[str]:
        return list(self._names)


class _DirOpener:
    def __init__(self, p: Path):
        self.p = p

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def read(self, name: str) -> bytes:
        return (self.p / name).read_bytes()

    def namelist(self) -> list[str]:
        return [str(f.relative_to(self.p)) for f in self.p.rglob("*") if f.is_file()]
