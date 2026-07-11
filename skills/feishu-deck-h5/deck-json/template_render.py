#!/usr/bin/env python3
"""Renderer adapter for PPT-derived Template Packs.

The Template Pack runtime in :mod:`template-pack.py` owns validation, coverage
resolution and asset containment.  This module owns the small HTML/CSS adapter
needed by ``render-deck.py``:

* load the pack referenced by ``deck.template_ref``;
* bind the existing DeckJSON layouts to the six semantic template roles;
* inject locked VI/fixed elements without adding a new business layout; and
* map extracted slots onto the existing layout DOM.

All paths written into the HTML are relative to the render output directory so
the normal ``copy-assets.py`` pass can materialise a run-local Template Pack
from ``runs/<id>/input/`` into the portable output bundle.
"""

from __future__ import annotations

import colorsys
import hashlib
import html
import importlib.util
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from _css_utils import scope_selectors


HERE = Path(__file__).resolve().parent
PACK_RUNTIME = HERE / "template-pack.py"


def _load_pack_runtime():
    spec = importlib.util.spec_from_file_location("_fs_template_pack_runtime", PACK_RUNTIME)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Template Pack runtime: {PACK_RUNTIME}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tp = _load_pack_runtime()


class TemplateRenderError(ValueError):
    """The deck cannot safely bind or render its selected Template Pack."""


_URI_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_ACTIVE_MARKUP_RE = re.compile(
    r"<\s*(?:script|style|iframe|object|embed|link|meta|base|foreignObject)\b|"
    r"\bon[a-z]+\s*=|javascript\s*:",
    re.I,
)
_ACTIVE_CSS_RE = re.compile(
    r"</?\s*(?:style|script)\b|@import\b|expression\s*\(|javascript\s*:",
    re.I,
)
_SLIDE_OPEN_RE = re.compile(r'(<div class="slide(?:\s[^"]*)?"[^>]*>)')
_FRAME_OPEN_RE = re.compile(r'(<div class="slide-frame"[^>]*>)')


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_template_pack_path(deck_path: Path, ref: str) -> Path:
    """Resolve a deck-relative pack path without allowing workspace escape.

    Canonical runs keep ``deck.json`` in ``output/`` and the pack snapshot in
    sibling ``input/runtime-library/template-pack/``.  Therefore one parent hop
    is intentionally legal, while absolute paths, URI schemes and escaping a
    run/deck root are not.
    """

    if not isinstance(ref, str) or not ref.strip():
        raise TemplateRenderError("deck.template_ref.path must be a non-empty string")
    value = ref.strip()
    if Path(value).is_absolute() or value.startswith(("~", "//")) or _URI_SCHEME_RE.match(value):
        raise TemplateRenderError(
            "deck.template_ref.path must be a local path relative to deck.json"
        )
    deck_dir = deck_path.resolve().parent
    candidate = (deck_dir / value).resolve(strict=False)
    # A canonical output directory may read its sibling input directory.  For a
    # standalone deck, keep the pack inside the deck directory itself.
    allowed_root = deck_dir.parent if deck_dir.name.startswith("output") else deck_dir
    if not _is_within(candidate, allowed_root.resolve()):
        raise TemplateRenderError(
            f"deck.template_ref.path escapes the run/deck root: {value!r}"
        )
    if not candidate.is_file():
        raise TemplateRenderError(f"Template Pack does not exist: {candidate}")
    return candidate


def _pack_canvas(pack: Any) -> tuple[int, int] | None:
    canvas = pack.raw.get("canvas", {}) if isinstance(pack.raw, Mapping) else {}
    if not isinstance(canvas, Mapping):
        return None
    recommended = canvas.get("recommended_design_canvas")
    if isinstance(recommended, Mapping):
        canvas = recommended
    try:
        width = int(canvas.get("width"))
        height = int(canvas.get("height"))
    except (TypeError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def _deck_canvas(deck: Mapping[str, Any]) -> tuple[int, int] | None:
    canvas = (deck.get("deck") or {}).get("canvas") or {}
    if not isinstance(canvas, Mapping):
        return None
    try:
        width = int(canvas.get("width"))
        height = int(canvas.get("height"))
    except (TypeError, ValueError):
        return None
    return (width, height) if width > 0 and height > 0 else None


def _pack_fingerprint(pack_path: Path, pack: Any) -> str:
    """Hash the pack JSON plus all declared runtime assets.

    ``render-deck`` folds this into its visual auto-scope fingerprint so editing
    an approved pack cannot be mistaken for a no-op deck re-render.
    """

    digest = hashlib.sha1()
    digest.update(pack_path.read_bytes())
    refs: set[str] = set()
    for slide_role in tp.SEMANTIC_ROLES:
        try:
            layout = tp.get_layout_override(pack, slide_role, strict=False)
        except Exception:
            layout = None
        if not isinstance(layout, Mapping):
            continue
        try:
            packet = tp._fixed_layer_packet(pack, layout)  # runtime-owned normalisation
        except Exception:
            continue
        refs.update(packet.get("asset_refs", []))
    for ref in sorted(refs):
        digest.update(ref.encode("utf-8"))
        try:
            digest.update(tp.resolve_pack_asset(pack, ref, must_exist=True).read_bytes())
        except OSError:
            digest.update(b"<missing>")
    return digest.hexdigest()


def load_template_context(
    deck: Mapping[str, Any],
    *,
    deck_path: Path,
    output_dir: Path,
    final: bool = False,
) -> dict[str, Any] | None:
    """Load and bind the optional ``deck.template_ref``.

    Missing roles are legal in a pack, but never silently substituted for a
    role this deck actually uses.  Preview can explicitly use ``mode:flexible``
    to inspect an incomplete pack; final renders always bind strictly.
    """

    ref = (deck.get("deck") or {}).get("template_ref")
    if ref is None:
        return None
    if not isinstance(ref, Mapping):
        raise TemplateRenderError("deck.template_ref must be an object")
    pack_path = resolve_template_pack_path(deck_path, ref.get("path", ""))
    # Draft packs are preview-only.  A deck field must not be able to turn a
    # delivery render into an implicit approval operation.
    allow_draft = bool(ref.get("allow_draft", False)) and not final
    mode = str(ref.get("mode", "strict")).lower()
    if mode not in {"strict", "flexible"}:
        raise TemplateRenderError("deck.template_ref.mode must be 'strict' or 'flexible'")
    if final and mode != "strict":
        raise TemplateRenderError("final render requires deck.template_ref.mode='strict'")
    try:
        pack = tp.load_template_pack(
            pack_path,
            final=final,
            allow_draft=allow_draft,
            verify_assets=True,
        )
        if not final and pack.status == "draft" and not allow_draft:
            raise TemplateRenderError(
                "draft Template Pack binding is review-only; set "
                "deck.template_ref.allow_draft=true explicitly for this preview"
            )
        if pack.status == "retired":
            raise TemplateRenderError(
                "retired Template Packs are historical inspection artifacts and "
                "cannot be selected for a new render"
            )
        expected_id = str(ref.get("id", ""))
        expected_version = str(ref.get("version", ""))
        if expected_id and pack.template_id != expected_id:
            raise TemplateRenderError(
                f"template_ref.id={expected_id!r} does not match pack "
                f"template_id={pack.template_id!r}"
            )
        if expected_version and pack.version != expected_version:
            raise TemplateRenderError(
                f"template_ref.version={expected_version!r} does not match pack "
                f"version={pack.version!r}"
            )
        strict = final or mode == "strict"
        authored_slides = [
            slide for slide in deck.get("slides", []) if not slide.get("_disabled")
        ]
        bindings = tp.build_deck_bindings(
            pack,
            authored_slides,
            final=final,
            allow_draft=allow_draft,
            strict=strict,
        )
    except tp.TemplatePackError as exc:
        raise TemplateRenderError(str(exc)) from exc

    pack_canvas = _pack_canvas(pack)
    deck_canvas = _deck_canvas(deck)
    if pack_canvas and not deck_canvas:
        raise TemplateRenderError(
            "a deck using template_ref must declare deck.canvas with the Template "
            f"Pack size {pack_canvas[0]}x{pack_canvas[1]}"
        )
    if pack_canvas and deck_canvas and pack_canvas != deck_canvas:
        raise TemplateRenderError(
            "deck.canvas does not match Template Pack canvas: "
            f"deck={deck_canvas[0]}x{deck_canvas[1]}, "
            f"pack={pack_canvas[0]}x{pack_canvas[1]}"
        )
    if strict:
        _validate_strict_fixed_planes(bindings)
        _validate_strict_authored_slots(authored_slides, bindings)

    web_prefix = Path(os.path.relpath(pack.base_dir, output_dir.resolve())).as_posix()
    by_key = {binding.get("slide_key"): binding for binding in bindings}
    inactive = [
        binding for binding in bindings
        if binding.get("role") is not None and not binding.get("active")
    ]
    return {
        "pack": pack,
        "pack_path": pack_path,
        "bindings": by_key,
        "inactive": inactive,
        "strict": strict,
        "web_prefix": web_prefix,
        "fingerprint": _pack_fingerprint(pack_path, pack),
    }


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _px(value: Any) -> str | None:
    number = _number(value)
    if number is None:
        return None
    return f"{number:g}px"


def _geometry(value: Mapping[str, Any]) -> dict[str, Any]:
    nested = value.get("geometry", value.get("bbox", {}))
    result: dict[str, Any] = dict(nested) if isinstance(nested, Mapping) else {}
    for key in ("x", "y", "w", "h", "width", "height"):
        if key in value:
            result[key] = value[key]
    if "w" not in result and "width" in result:
        result["w"] = result["width"]
    if "h" not in result and "height" in result:
        result["h"] = result["height"]
    return result


def _geometry_css(value: Mapping[str, Any]) -> list[str]:
    box = _geometry(value)
    declarations: list[str] = []
    for source, target in (("x", "left"), ("y", "top"), ("w", "width"), ("h", "height")):
        unit = _px(box.get(source))
        if unit is not None:
            declarations.append(f"{target}:{unit}")
    if declarations:
        declarations.insert(0, "position:absolute")
    return declarations


def _style_object(value: Mapping[str, Any]) -> dict[str, Any]:
    style: dict[str, Any] = {}
    for key in ("style", "typography", "text_style"):
        child = value.get(key)
        if isinstance(child, Mapping):
            style.update(child)
            if isinstance(child.get("text"), Mapping):
                style.update(child["text"])
    for key in (
        "font_family", "font_size", "font_size_pt", "font_weight", "font_style", "color",
        "color_source",
        "alignment", "text_align", "line_height", "letter_spacing", "opacity",
        "fill", "background", "border_radius",
    ):
        if key in value:
            style[key] = value[key]
    return style


def _safe_css_scalar(value: str, label: str) -> str:
    text = str(value).strip()
    if not text or re.search(r"[;{}<>]|/\*|\*/|url\s*\(|expression\s*\(", text, re.I):
        raise TemplateRenderError(f"unsafe {label} in Template Pack: {value!r}")
    return text


def _safe_css_color(value: str, label: str = "color") -> str:
    text = _safe_css_scalar(value, label)
    if not re.fullmatch(
        r"#[0-9A-Fa-f]{3,8}|(?:rgba?|hsla?)\([0-9.,%\s+\-/]+\)|"
        r"[A-Za-z][A-Za-z0-9-]*",
        text,
    ):
        raise TemplateRenderError(f"unsupported {label} in Template Pack: {value!r}")
    return text


def _text_style_css(value: Mapping[str, Any], pack: Any | None = None) -> list[str]:
    style = _style_object(value)
    out: list[str] = []
    family = style.get("font_family")
    if isinstance(family, str) and family.strip():
        out.append(f"font-family:{_safe_css_scalar(family, 'font family')} !important")
    size = _px(style.get("font_size"))
    if size:
        # Exact template typography is authoritative; the framework ladder must
        # not rewrite it.  The allow marker is understood by the static gate.
        out.append(f"font-size:{size} !important /* allow:typescale */")
    weight = style.get("font_weight")
    if isinstance(weight, (int, float)) and not isinstance(weight, bool):
        out.append(f"font-weight:{weight:g} !important")
    elif isinstance(weight, str) and re.fullmatch(r"(?:[1-9]00|normal|bold|bolder|lighter)", weight.strip()):
        out.append(f"font-weight:{weight.strip()} !important")
    if style.get("font_style") in {"normal", "italic", "oblique"}:
        out.append(f"font-style:{style['font_style']} !important")
    authored_color = style.get("color_source", style.get("color"))
    gradient = (
        _fill_value(pack, authored_color)
        if pack is not None and isinstance(authored_color, Mapping)
        and authored_color.get("type") == "gradient"
        else None
    )
    color = _color_value(pack, authored_color) if pack is not None else style.get("color")
    if gradient:
        out.extend([
            f"background-image:{gradient} !important",
            "background-clip:text !important",
            "-webkit-background-clip:text !important",
            "-webkit-text-fill-color:transparent !important",
        ])
        color = None
    if pack is not None and authored_color not in (None, "") and color is None:
        if not gradient:
            raise TemplateRenderError(
                f"cannot resolve Template Pack text color: {authored_color!r}"
            )
    if isinstance(color, str) and color.strip():
        out.append(f"color:{_safe_css_color(color)} !important")
    align = style.get("text_align", style.get("alignment"))
    if align in {"left", "center", "right", "justify", "start", "end"}:
        out.append(f"text-align:{align} !important")
    line_height = style.get("line_height")
    if isinstance(line_height, (int, float)):
        # Values <=4 are line-height ratios; larger values are extracted px.
        suffix = "" if float(line_height) <= 4 else "px"
        out.append(f"line-height:{float(line_height):g}{suffix} !important")
    elif isinstance(line_height, str) and line_height.strip():
        safe_line = line_height.strip()
        if not re.fullmatch(r"(?:normal|[0-9]+(?:\.[0-9]+)?(?:px|pt|%|em|rem)?)", safe_line):
            raise TemplateRenderError(f"unsafe line height in Template Pack: {line_height!r}")
        out.append(f"line-height:{safe_line} !important")
    elif isinstance(line_height, Mapping):
        unit = line_height.get("unit")
        value = _number(line_height.get("value"))
        if value is not None and unit == "percent":
            out.append(f"line-height:{value / 100:g} !important")
        elif value is not None and unit == "pt":
            source_pt = _number(style.get("font_size_pt"))
            design_px = _number(style.get("font_size"))
            scale = design_px / source_pt if source_pt and design_px else 4 / 3
            out.append(f"line-height:{value * scale:g}px !important")
    letter = style.get("letter_spacing")
    if isinstance(letter, (int, float)):
        out.append(f"letter-spacing:{float(letter):g}px !important")
    elif isinstance(letter, str) and letter.strip():
        safe_letter = letter.strip()
        if not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?(?:px|pt|em|rem|%)", safe_letter):
            raise TemplateRenderError(f"unsafe letter spacing in Template Pack: {letter!r}")
        out.append(f"letter-spacing:{safe_letter} !important")
    return out


# geometry target, typography target.  These selectors are renderer-owned and
# intentionally allowlisted; a PPT file cannot inject arbitrary selectors.
_SLOT_TARGETS: dict[str, dict[str, tuple[str, str]]] = {
    "cover": {
        "title": (".stage .title-zh", ".stage .title-zh"),
        "subtitle": (".stage .subtitle", ".stage .subtitle"),
        "author": (".author", ".author"),
        "date": (".author", ".author"),
        "body": (".stage", ".stage"),
        "content": (".stage", ".stage"),
    },
    "raw": {
        "title": (".header", ".header .title-zh"),
        "subtitle": (".header .page-sub", ".header .page-sub"),
        "body": (".stage", ".stage"),
        "content": (".stage", ".stage"),
    },
    "section": {
        "chapter": (".chapter-num", ".chapter-num"),
        "chapter_num": (".chapter-num", ".chapter-num"),
        "parent_label": (".parent-label", ".parent-label"),
        "title": (".title-zh", ".title-zh"),
        "subtitle": (".lede", ".lede"),
        "lede": (".lede", ".lede"),
        "body": (".lede", ".lede"),
        "content": (".lede", ".lede"),
        "pills": (".pills", ".pills"),
    },
    "quote": {
        "quote": (".stack", ".stack blockquote"),
        "body": (".stack", ".stack blockquote"),
        "content": (".stack", ".stack blockquote"),
        "attribution": (".attrib", ".attrib"),
    },
    "agenda": {
        "title": (".header", ".header .title-zh"),
        "subtitle": (".header .page-sub", ".header .page-sub"),
        "body": (".toc", ".toc"),
        "content": (".toc", ".toc"),
        "items": (".toc", ".toc"),
    },
    "end": {
        # An explicit end -> cover alias reuses the cover's fixed shell, but
        # the authored page is still an END page.  Bind the source layout's
        # title/subtitle-style slots onto end's native slogan/contact DOM rather
        # than emitting dead cover selectors.  This keeps aliasing visual-only:
        # it never changes the target page's business/content semantics.
        "title": ("> .slogan", "> .slogan"),
        "slogan": ("> .slogan", "> .slogan"),
        "subtitle": ("> .contact", "> .contact"),
        "author": ("> .contact", "> .contact"),
        "date": ("> .contact", "> .contact"),
        "body": (".contact", ".contact"),
        "content": (".contact", ".contact"),
        "contact": (".contact", ".contact"),
    },
}


def _slot_semantic_name(slot: Mapping[str, Any]) -> str:
    """Return the renderer-owned semantic name used by slots and guards."""
    return str(
        slot.get(
            "semantic_name",
            slot.get("slot_kind", slot.get("name", slot.get("slot", slot.get("role", "")))),
        )
    ).strip().lower().replace("-", "_")


_AUTHORED_SLOT_COMPAT: dict[str, dict[str, frozenset[str]]] = {
    "cover": {
        "title": frozenset({"title"}),
        "subtitle": frozenset({"subtitle"}),
        # The framework renders author + date in one block, so either extracted
        # placeholder supplies the geometry/typography for that combined block.
        "author": frozenset({"author", "date"}),
        "date": frozenset({"author", "date"}),
    },
    "section": {
        "chapter_num": frozenset({"chapter", "chapter_num"}),
        "parent_label": frozenset({"parent_label"}),
        "title": frozenset({"title"}),
        "lede": frozenset({"subtitle", "lede", "body", "content"}),
        "pills": frozenset({"pills"}),
    },
    "quote": {
        "quote": frozenset({"quote", "body", "content"}),
        "attribution": frozenset({"attribution"}),
    },
    "agenda": {
        "title": frozenset({"title"}),
        "items": frozenset({"items", "body", "content"}),
    },
    "end": {
        # The accepted names are SOURCE-slot names. This is deliberately keyed
        # by the requested page role, not the resolved alias role: end→cover may
        # reuse cover title/subtitle slots while still targeting end slogan and
        # contact DOM (see _SLOT_TARGETS['end']).
        "slogan": frozenset({"slogan", "title"}),
        "contact": frozenset({"contact", "subtitle", "author", "date", "body", "content"}),
    },
}


def _has_authored_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (Sequence, Mapping)) and not isinstance(value, (str, bytes)):
        return bool(value)
    return True


def _authored_slot_requirements(
    slide: Mapping[str, Any], role: str,
) -> list[tuple[str, frozenset[str]]]:
    data = slide.get("data") or {}
    if not isinstance(data, Mapping):
        return []
    requirements: list[tuple[str, frozenset[str]]] = []
    if role == "raw":
        if str(slide.get("layout", "")) == "raw":
            if _has_authored_value(data.get("html")):
                requirements.append(("html", frozenset({"body", "content"})))
            return requirements
        # Legacy body layouts still have requested role=raw. Their title is a
        # distinct header; every other authored business field composes inside
        # the shared body/stage slot.
        for field, value in data.items():
            if not _has_authored_value(value):
                continue
            accepted = frozenset({"title"}) if field == "title" else frozenset({"body", "content"})
            requirements.append((str(field), accepted))
        return requirements
    for field, accepted in _AUTHORED_SLOT_COMPAT.get(role, {}).items():
        if _has_authored_value(data.get(field)):
            requirements.append((field, accepted))
    return requirements


def _validate_strict_authored_slots(
    slides: Sequence[Mapping[str, Any]], bindings: Sequence[Mapping[str, Any]],
) -> None:
    """Block strict renders before any authored field can leak to default VI."""
    missing: list[str] = []
    for slide, binding in zip(slides, bindings):
        if not binding.get("active"):
            continue
        # ``role`` is the requested role. Never substitute ``resolved_role``
        # here: aliases reuse a shell, not the source page's content semantics.
        role = str(binding.get("role") or "")
        slots = binding.get("slots") or []
        available = {
            _slot_semantic_name(slot)
            for slot in slots
            if isinstance(slot, Mapping) and not slot.get("system_field")
        }
        available.discard("")
        for field, accepted in _authored_slot_requirements(slide, role):
            if available & accepted:
                continue
            names = ", ".join(sorted(available)) or "none"
            missing.append(
                f"slide {str(slide.get('key', ''))!r} data.{field} "
                f"(requested role {role!r}, layout {str(binding.get('layout_id', ''))!r}; "
                f"available slots: {names})"
            )
    if missing:
        raise TemplateRenderError(
            "strict Template Pack has no corresponding slot for authored field(s): "
            + "; ".join(missing)
        )


def _safe_area_rule(binding: Mapping[str, Any], scope: str) -> str:
    safe = binding.get("safe_area")
    if not isinstance(safe, Mapping):
        return ""
    role = str(binding.get("role") or "raw")
    target = {
        "cover": ".stage",
        "raw": ".stage",
        "section": ".lede",
        "quote": ".stack",
        "agenda": ".toc",
        "end": ".contact",
    }.get(role)
    if not target:
        return ""
    declarations = _geometry_css(safe)
    return f"{scope} {target}{{{';'.join(declarations)};}}" if declarations else ""


def _markup_classes(markup: str) -> set[str]:
    classes: set[str] = set()
    for match in re.finditer(r'class=["\']([^"\']*)["\']', markup, re.I):
        classes.update(match.group(1).split())
    return classes


def _slot_rules(
    binding: Mapping[str, Any], scope: str, pack: Any, slide_html: str,
) -> list[str]:
    role = str(binding.get("role") or "raw")
    targets = _SLOT_TARGETS.get(role, _SLOT_TARGETS["raw"])
    rules: list[str] = []
    slots = binding.get("slots") or []
    if not isinstance(slots, Sequence) or isinstance(slots, (str, bytes)):
        return rules
    explicit_body = False
    has_geometry = False
    semantic_names: set[str] = set()
    markup_classes = _markup_classes(slide_html)
    if role == "cover":
        # Extracted placeholder coordinates are slide-absolute. Neutralise the
        # framework's 16:9 stage box so cover title/subtitle slots can use those
        # coordinates verbatim on arbitrary aspect ratios.
        rules.append(
            f"{scope} .stage{{position:absolute !important;inset:0 !important;"
            "width:100% !important;height:100% !important;}"
        )
    for slot in slots:
        if not isinstance(slot, Mapping):
            continue
        if slot.get("system_field"):
            # PowerPoint date/footer/page-number placeholders are master chrome,
            # not replaceable business-content slots. They must not hijack the
            # cover's combined author/date block.
            continue
        name = _slot_semantic_name(slot)
        semantic_names.add(name)
        if name in {"body", "content", "items"}:
            explicit_body = True
        pair = targets.get(name)
        if pair is None:
            continue
        geom_target, text_target = pair
        required_classes = re.findall(r"\.([A-Za-z_][A-Za-z0-9_-]*)", text_target)
        if required_classes and required_classes[-1] not in markup_classes:
            # Optional source placeholders (subtitle/lede/etc.) may be absent in
            # this authored slide. Do not emit a dead selector that the visual
            # DEAD-RULE gate would correctly reject.
            continue
        geom_css = _geometry_css(slot)
        if geom_css:
            has_geometry = True
            rules.append(f"{scope} {geom_target}{{{';'.join(geom_css)} !important;}}")
        text_css = _text_style_css(slot, pack)
        if text_css:
            rules.append(f"{scope} {text_target}{{{';'.join(text_css)};}}")
    if not explicit_body and not has_geometry:
        safe_rule = _safe_area_rule(binding, scope)
        if safe_rule:
            rules.insert(0, safe_rule)
    # Remove Feishu-specific optional chrome that is not represented by a
    # confirmed template slot. Fixed enterprise VI is supplied by fixed_elements.
    if role == "cover" and not ({"author", "date"} & semantic_names):
        rules.append(f"{scope} > .author{{display:none !important;}}")
    if role == "section":
        if not ({"chapter", "chapter_num"} & semantic_names):
            rules.append(f"{scope} > .chapter-num{{display:none !important;}}")
        if not ({"subtitle", "lede", "body", "content"} & semantic_names):
            rules.append(f"{scope} > .lede{{display:none !important;}}")
    if role == "quote":
        rules.append(f"{scope} .keyline{{display:none !important;}}")
        if "attribution" not in semantic_names:
            rules.append(f"{scope} .attrib{{display:none !important;}}")
    if role == "agenda" and "title" not in semantic_names:
        rules.append(f"{scope} > .header{{display:none !important;}}")
    return rules


def _web_ref(prefix: str, ref: str) -> str:
    normal = tp.normalize_asset_ref(ref)
    return f"{prefix.rstrip('/')}/{normal}" if prefix not in {"", "."} else f"./{normal}"


def _rewrite_pack_refs(value: str, refs: Sequence[str], prefix: str) -> str:
    result = value
    for ref in sorted(set(refs), key=len, reverse=True):
        result = result.replace(ref, _web_ref(prefix, ref))
    return result


def _theme_color(pack: Any, token: str, seen: set[str] | None = None) -> str | None:
    seen = set(seen or ())
    if token in seen:
        return None
    seen.add(token)
    tokens = pack.raw.get("tokens", {}) if isinstance(pack.raw, Mapping) else {}
    colors = tokens.get("colors", []) if isinstance(tokens, Mapping) else []
    if isinstance(colors, Sequence) and not isinstance(colors, (str, bytes)):
        for item in colors:
            if not isinstance(item, Mapping) or str(item.get("token")) != token:
                continue
            value = item.get("value")
            if isinstance(value, Mapping):
                return _color_value(pack, value, seen)
            if isinstance(value, str):
                return value
    return None


def _apply_color_transforms(base: str | None, transforms: Any) -> str | None:
    """Resolve common DrawingML color transforms into a concrete CSS color."""

    if not base or not isinstance(base, str) or not base.startswith("#"):
        return base
    token = base[1:]
    if len(token) == 3:
        token = "".join(ch * 2 for ch in token)
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", token):
        return base
    r, g, b = (int(token[i:i + 2], 16) / 255 for i in (0, 2, 4))
    alpha = 1.0
    if not isinstance(transforms, Sequence) or isinstance(transforms, (str, bytes)):
        transforms = []
    for item in transforms:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name", ""))
        raw = _number(item.get("value"))
        if raw is None:
            continue
        amount = max(0.0, min(1.0, raw / 100000.0))
        if name == "tint":
            r, g, b = (r + (1 - r) * amount, g + (1 - g) * amount, b + (1 - b) * amount)
        elif name == "shade":
            r, g, b = (r * amount, g * amount, b * amount)
        elif name in {"lumMod", "lumOff", "satMod", "satOff"}:
            h, light, saturation = colorsys.rgb_to_hls(r, g, b)
            if name == "lumMod":
                light *= amount
            elif name == "lumOff":
                light += amount
            elif name == "satMod":
                saturation *= amount
            else:
                saturation += amount
            r, g, b = colorsys.hls_to_rgb(
                h, max(0.0, min(1.0, light)), max(0.0, min(1.0, saturation)),
            )
        elif name == "alpha":
            alpha = amount
        elif name == "alphaMod":
            alpha *= amount
        elif name == "alphaOff":
            alpha = min(1.0, alpha + amount)
    rgb = tuple(max(0, min(255, round(channel * 255))) for channel in (r, g, b))
    if alpha < 0.999:
        return f"rgba({rgb[0]},{rgb[1]},{rgb[2]},{alpha:.4f})"
    return "#" + "".join(f"{channel:02X}" for channel in rgb)


def _color_value(pack: Any, value: Any, seen: set[str] | None = None) -> str | None:
    if isinstance(value, str):
        if value.startswith("theme:"):
            return _theme_color(pack, value.split(":", 1)[1], seen)
        return value
    if not isinstance(value, Mapping):
        return None
    if value.get("type") == "solid":
        return _color_value(pack, value.get("color"), seen)
    kind = value.get("kind")
    token = value.get("value")
    result = None
    if kind in {"rgb", "system"} and isinstance(token, str) and token:
        result = f"#{token.lstrip('#')}"
    elif kind == "theme" and isinstance(token, str):
        result = _theme_color(pack, token, seen)
    elif kind == "preset" and isinstance(token, str):
        result = token
    return _apply_color_transforms(result, value.get("transforms"))


def _fill_value(pack: Any, value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return _safe_css_scalar(value, "fill")
    if not isinstance(value, Mapping):
        return None
    kind = value.get("type")
    if kind == "none":
        return None
    if kind == "solid" or value.get("kind"):
        resolved = _color_value(pack, value)
        return _safe_css_color(resolved, "fill") if resolved else None
    if kind == "gradient":
        stops = []
        for stop in value.get("stops") or []:
            if not isinstance(stop, Mapping):
                continue
            color = _color_value(pack, stop.get("color"))
            position = _number(stop.get("position"))
            if color is None or position is None:
                raise TemplateRenderError(f"cannot resolve Template Pack gradient stop: {stop!r}")
            stops.append(
                f"{_safe_css_color(color, 'gradient color')} "
                f"{max(0, min(100, position / 1000)):g}%"
            )
        if not stops:
            raise TemplateRenderError("Template Pack gradient has no resolvable stops")
        raw_angle = _number(value.get("angle"))
        angle = ((raw_angle or 0) / 60000.0 + 90) % 360
        return f"linear-gradient({angle:g}deg, {', '.join(stops)})"
    if kind in {"picture", "pattern"}:
        raise TemplateRenderError(
            f"Template Pack {kind} fill requires an extracted local image asset"
        )
    return None


def _fixed_element_html(
    element: Mapping[str, Any], prefix: str, index: int, pack: Any,
    *, include_children: bool = True,
) -> str:
    if element.get("visible") is False:
        return ""
    kind = str(
        element.get("type", element.get("kind", element.get("shape_type", "")))
    ).lower()
    eid = html.escape(str(element.get("id", f"fixed-{index + 1}")), quote=True)
    declarations = _geometry_css(element)
    style = _style_object(element)
    z = element.get("z_index", element.get("z", 0))
    if isinstance(z, (int, float)):
        declarations.append(f"z-index:{int(z)}")
    if isinstance(style.get("opacity"), (int, float)):
        declarations.append(f"opacity:{float(style['opacity']):g}")
    fill_source = style.get("fill", style.get("background"))
    if fill_source is None and isinstance(style.get("theme_reference"), Mapping):
        fill_source = style["theme_reference"].get("color")
    fill = None if element.get("src") else _fill_value(pack, fill_source)
    if isinstance(fill, str) and fill.strip():
        declarations.append(f"background:{fill.strip()}")
    line = style.get("line")
    if isinstance(line, Mapping):
        line_fill = _fill_value(pack, line.get("fill"))
        width_emu = _number(line.get("width_emu"))
        if line_fill and width_emu:
            declarations.append(f"border:{max(1, width_emu / 9525):g}px solid {line_fill}")
    radius = _px(style.get("border_radius"))
    if radius:
        declarations.append(f"border-radius:{radius}")
    rotate = _number(
        element.get("rotation_degrees", element.get("rotation", element.get("rotate")))
    )
    if rotate:
        declarations.append(f"transform:rotate({rotate:g}deg)")
    declarations.append("pointer-events:none")
    css = html.escape(";".join(declarations), quote=True)
    classes = "fs-template-fixed is-locked" if element.get("locked", True) else "fs-template-fixed"

    if element.get("src") or kind in {"image", "picture", "logo"}:
        src = element.get("src", element.get("asset_ref", element.get("path")))
        if not isinstance(src, str) or not src:
            return ""
        source = html.escape(_web_ref(prefix, src), quote=True)
        fit = element.get("fit", element.get("object_fit", "contain"))
        if fit not in {"contain", "cover", "fill", "none", "scale-down"}:
            fit = "contain"
        return (
            f'<img class="{classes}" data-template-fixed-id="{eid}" '
            f'src="{source}" alt="" aria-hidden="true" '
            f'style="{css};object-fit:{fit}">'
        )
    if element.get("text") is not None or kind in {"text", "label", "text_box"}:
        text = html.escape(str(element.get("text", "")))
        text_css = ";".join(_text_style_css(element, pack))
        return (
            f'<div class="{classes}" data-template-fixed-id="{eid}" '
            f'data-allow-body-floor data-allow-typescale aria-hidden="true" '
            f'style="{css};{html.escape(text_css, quote=True)}">'
            f'{text}</div>'
        )
    if kind in {"shape", "rect", "rectangle", "line", "auto_shape", "freeform", "background"}:
        own = (
            f'<div class="{classes}" data-template-fixed-id="{eid}" '
            f'aria-hidden="true" style="{css}"></div>'
        )
    else:
        own = ""
    children = (element.get("children") or []) if include_children else []
    nested = "".join(
        _fixed_element_html(child, prefix, index * 100 + child_index + 1, pack)
        for child_index, child in enumerate(children)
        if isinstance(child, Mapping)
    )
    return own + nested


def _explicit_fixed_plane(element: Mapping[str, Any]) -> str | None:
    for key in ("content_plane", "stack_plane", "fixed_plane", "plane", "layer"):
        value = str(element.get(key, "")).strip().lower()
        if value in {"background", "foreground"}:
            return value
    return None


def _source_fixed_plane(element: Mapping[str, Any]) -> str | None:
    value = str(element.get("source_stack_plane", "")).strip().lower()
    return value if value in {"background", "foreground", "interleaved"} else None


def _declared_fixed_plane(element: Mapping[str, Any], pack: Any) -> str | None:
    """Return an explicit/protected content plane; never infer one from z alone.

    PowerPoint ``z_index`` is absolute within one shape tree. A decorative
    shape may therefore have a positive/high index while still sitting below a
    later content placeholder. The extractor does not yet persist that
    placeholder-relative plane may be absent in older packs, so runtime defaults
    uncertain elements to background and only promotes declared/protected brand
    elements. Newer packs supply ``source_stack_plane`` as the second priority.
    """
    explicit = _explicit_fixed_plane(element)
    if explicit:
        return explicit
    source_plane = _source_fixed_plane(element)
    if source_plane:
        return source_plane
    if element.get("background") is True:
        return "background"
    if element.get("foreground") is True or element.get("is_foreground") is True:
        return "foreground"
    if element.get("protected") is True or element.get("is_protected") is True:
        return "foreground"

    kind = str(
        element.get("type", element.get("kind", element.get("shape_type", "")))
    ).strip().lower()
    if kind in {"logo", "wordmark", "brandmark"}:
        return "foreground"
    identity = " ".join(
        str(element.get(key, "")) for key in ("id", "name", "semantic_role")
    ).lower()
    if re.search(r"(?:^|[\s_-])(?:logo|wordmark|brandmark)(?:$|[\s_-])", identity):
        return "foreground"

    brand = pack.raw.get("brand", {}) if isinstance(pack.raw, Mapping) else {}
    asset_ids = brand.get("asset_ids", []) if isinstance(brand, Mapping) else []
    if element.get("asset_id") and element.get("asset_id") in asset_ids:
        return "foreground"
    return None


def _walk_fixed_elements(elements: Sequence[Any]):
    for element in elements:
        if not isinstance(element, Mapping):
            continue
        yield element
        yield from _walk_fixed_elements(element.get("children") or [])


def _validate_strict_fixed_planes(bindings: Sequence[Mapping[str, Any]]) -> None:
    unresolved: list[str] = []
    for binding in bindings:
        if not binding.get("active"):
            continue
        for element in _walk_fixed_elements(binding.get("fixed_elements") or []):
            if _explicit_fixed_plane(element):
                continue
            if _source_fixed_plane(element) != "interleaved":
                continue
            unresolved.append(
                f"slide {str(binding.get('slide_key', ''))!r} layout "
                f"{str(binding.get('layout_id', ''))!r} fixed element "
                f"{str(element.get('id', element.get('name', 'unknown')))!r}"
            )
    if unresolved:
        raise TemplateRenderError(
            "strict Template Pack cannot render source_stack_plane='interleaved' "
            "without reviewed content_plane/stack_plane=background|foreground: "
            + "; ".join(unresolved)
        )


def _fixed_element_layers(
    elements: Sequence[Any], prefix: str, pack: Any,
) -> tuple[str, str, bool]:
    """Render structured fixed VI into independent stacking-context planes.

    Child elements are already flattened by the prior renderer, so walking the
    tree preserves that behaviour. ``z_index`` remains intact for ordering
    inside a plane; it never guesses whether an element sits above content.
    """
    background: list[str] = []
    foreground: list[str] = []
    has_interleaved = False

    def visit(
        element: Mapping[str, Any], index: int, inherited_plane: str = "background",
    ) -> None:
        nonlocal has_interleaved
        if element.get("visible") is False:
            return
        declared = _declared_fixed_plane(element, pack)
        if declared == "interleaved":
            # Flexible/draft preview only: keep uncertain VI behind content and
            # expose a machine-readable review marker. Strict mode is rejected
            # earlier by _validate_strict_fixed_planes.
            has_interleaved = True
            plane = "background"
        else:
            plane = declared or inherited_plane
        fragment = _fixed_element_html(
            element, prefix, index, pack, include_children=False,
        )
        (foreground if plane == "foreground" else background).append(fragment)
        children = element.get("children") or []
        for child_index, child in enumerate(children):
            if isinstance(child, Mapping):
                visit(child, index * 100 + child_index + 1, plane)

    for index, element in enumerate(elements):
        if isinstance(element, Mapping):
            visit(element, index)
    return "".join(background), "".join(foreground), has_interleaved


def _background_value(pack: Any, binding: Mapping[str, Any], prefix: str) -> str:
    layout = pack.layouts.get(str(binding.get("layout_id", "")), {})
    background = layout.get("background") if isinstance(layout, Mapping) else None
    if isinstance(background, Mapping):
        color = background.get("color")
        image = background.get("src", background.get("image"))
        if isinstance(image, str) and image:
            color_part = f"{color} " if isinstance(color, str) and color else ""
            return f'{color_part}url("{_web_ref(prefix, image)}") center/cover no-repeat'
        if isinstance(color, str) and color:
            return color
    if isinstance(background, str) and background:
        return background
    tokens = pack.raw.get("tokens", {})
    if isinstance(tokens, Mapping):
        colors = tokens.get("colors", tokens.get("color", {}))
        if isinstance(colors, Mapping):
            for key in ("background", "canvas", "page", "surface"):
                if isinstance(colors.get(key), str) and colors[key]:
                    return str(colors[key])
    # Neutral fallback only; extracted fixed elements/backgrounds render above
    # it.  This prevents the default Feishu flower/content master leaking behind
    # a corporate template whose source background was plain white.
    return "#ffffff"


def apply_template_binding(
    slide_html: str,
    binding: Mapping[str, Any] | None,
    *,
    pack: Any,
    web_prefix: str,
) -> str:
    """Inject one renderer binding into an already-rendered existing layout."""

    if not binding or binding.get("role") is None:
        return slide_html
    if not binding.get("active"):
        reason = html.escape(str(binding.get("reason", "unavailable")), quote=True)
        return _SLIDE_OPEN_RE.sub(
            lambda match: match.group(0)[:-1] + f' data-template-status="{reason}">',
            slide_html,
            count=1,
        )

    fixed_html = str(binding.get("fixed_html") or "")
    if _ACTIVE_MARKUP_RE.search(fixed_html):
        raise TemplateRenderError(
            f"Template Pack fixed layer contains active markup on slide {binding.get('slide_key')!r}"
        )
    refs = [str(ref) for ref in binding.get("asset_refs", []) if isinstance(ref, str)]
    fixed_html = _rewrite_pack_refs(fixed_html, refs, web_prefix)
    fixed_css = _rewrite_pack_refs(str(binding.get("fixed_css") or ""), refs, web_prefix)
    if _ACTIVE_CSS_RE.search(fixed_css):
        raise TemplateRenderError(
            f"Template Pack fixed CSS contains active/escaping content on slide "
            f"{binding.get('slide_key')!r}"
        )
    if fixed_css.strip():
        fixed_css = scope_selectors(fixed_css, str(binding.get("slide_key", "")))

    attrs = binding.get("data_attrs", {})
    attr_text = "".join(
        f' {html.escape(str(key), quote=True)}="{html.escape(str(value), quote=True)}"'
        for key, value in attrs.items()
        if isinstance(key, str) and key.startswith("data-template-")
    )
    rendered = _SLIDE_OPEN_RE.sub(
        lambda match: match.group(0)[:-1] + attr_text + ">",
        slide_html,
        count=1,
    )
    frame_attrs = (
        f' data-template-id="{html.escape(str(binding.get("template_id", "")), quote=True)}"'
        f' data-template-role="{html.escape(str(binding.get("role", "")), quote=True)}"'
        f' data-template-layout-id="{html.escape(str(binding.get("layout_id", "")), quote=True)}"'
        f' data-template-slide-key="{html.escape(str(binding.get("slide_key", "")), quote=True)}"'
    )
    rendered = _FRAME_OPEN_RE.sub(
        lambda match: match.group(0)[:-1] + frame_attrs + ">",
        rendered,
        count=1,
    )

    scope = (
        f'.slide[data-slide-key="{binding.get("slide_key", "")}"]'
        f'[data-template-id="{binding.get("template_id", "")}"]'
    )
    frame_scope = (
        f'.slide-frame[data-template-id="{binding.get("template_id", "")}"]'
        f'[data-template-slide-key="{binding.get("slide_key", "")}"]'
    )
    rules = [
        f"{frame_scope}{{background:{_background_value(pack, binding, web_prefix)} !important;}}",
        f"{scope}{{background:transparent !important;isolation:isolate;}}",
        f"{scope} > .wordmark{{display:none !important;}}",
        f"{scope} > .slogan-default{{display:none !important;}}",
        f"{scope} > .fs-template-fixed-layer{{position:absolute;inset:0;pointer-events:none;overflow:hidden;}}",
        f'{scope} > .fs-template-fixed-layer[data-template-fixed-layer="background"]'
        "{z-index:-1 !important;}",
        f'{scope} > .fs-template-fixed-layer[data-template-fixed-layer="foreground"]'
        "{z-index:1000 !important;}",
    ]
    rules.extend(_slot_rules(binding, scope, pack, rendered))
    if fixed_css.strip():
        # Extracted CSS is generated by our converter, but still scope the common
        # root token to avoid cross-slide leakage.
        fixed_css = fixed_css.replace(":root", scope)
        rules.append(fixed_css)

    structured_background, structured_foreground, has_interleaved = _fixed_element_layers(
        binding.get("fixed_elements") or [], web_prefix, pack,
    )
    stack_status = ' data-template-stack-status="interleaved"' if has_interleaved else ""
    layers = (
        '<div class="fs-template-fixed-layer" data-allow-dual-anchor '
        'data-template-fixed-layer="background"'
        + stack_status
        + ' aria-hidden="true">'
        + structured_background
        + fixed_html
        + "</div>"
        '<div class="fs-template-fixed-layer" data-allow-dual-anchor '
        'data-template-fixed-layer="foreground" aria-hidden="true">'
        + structured_foreground
        + "</div>"
    )
    style_block = (
        f'<style data-fs-template-css data-template-layout-id="'
        f'{html.escape(str(binding.get("layout_id", "")), quote=True)}">\n'
        + "\n".join(rule for rule in rules if rule)
        + "\n</style>"
    )
    injection = "\n        " + style_block + "\n        " + layers
    rendered, count = _SLIDE_OPEN_RE.subn(
        lambda match: match.group(0) + injection,
        rendered,
        count=1,
    )
    if count != 1:
        raise TemplateRenderError(
            f"cannot find .slide root for template binding {binding.get('slide_key')!r}"
        )
    return rendered


__all__ = [
    "TemplateRenderError",
    "resolve_template_pack_path",
    "load_template_context",
    "apply_template_binding",
]
