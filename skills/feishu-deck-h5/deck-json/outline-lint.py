#!/usr/bin/env python3
"""outline-lint.py — self-check for a designer outline.json (stdlib only).

This is a SELF-CHECK tool, not a render-time gate. It is meant to be run by the
designer right after writing output/outline.json:

  python3 deck-json/outline-lint.py output/outline.json

It does NOT make render require an outline.json — render-deck.py never calls it,
and a deck with no outline.json is still perfectly valid. The point is to catch a
half-filled outline (raw slide missing part of its six-dimension design spec, or
an empty density budget) before that thin spec leaks into authoring.

Two layers of checks:

  1. Shape: outline.json conforms to schema/outline.schema.json — top-level
     scenario / design_plan / slides, plus each slide's required keys
     (key / role / layout_intent / single_focus / density_budget / design_spec).
  2. raw-slide design contract: for every slide whose `layout_intent` starts with
     `raw:`, its design_spec must cover all six design dimensions
     (字号 / 容器 / 装饰 / 对齐 / 字距 / 字重 — see references/design-first.md) and
     its density_budget must be non-empty. The six dims may be written as discrete
     keys OR as prose (six_dim_A / Q2_tiers / …), so coverage is checked over the
     flattened design_spec text, mirroring how real outlines are authored.

Errors are reported with the slide key and a 1-based locator (key='…', 第N项),
matching the deck-cli / validator coordinate convention (F-280).

Exit codes:
  0 = clean
  1 = lint violations
  2 = file / schema load error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
DEFAULT_SCHEMA = HERE.parent / "schema" / "outline.schema.json"


def _kw(*words: str) -> Callable[[str], bool]:
    lowered = tuple(w.lower() for w in words)
    return lambda blob: any(w in blob for w in lowered)


def _re(pattern: str) -> Callable[[str], bool]:
    rx = re.compile(pattern, re.IGNORECASE)
    return lambda blob: bool(rx.search(blob))


def _any(*preds: Callable[[str], bool]) -> Callable[[str], bool]:
    return lambda blob: any(p(blob) for p in preds)


# Six design dimensions from references/design-first.md (Q2 六维). The spec is
# checked over the FLATTENED design_spec text. Authors write these two ways and
# both are legitimate, so each dimension accepts the explicit label AND the
# compact shorthand seen in real outlines
# ("关口名40/700/左/-0.01em" == 字号40 · 字重700 · 对齐左 · 字距-0.01em):
#   字号 — label, or a px / bare size number, or "绘制/SVG" sized art
#   容器 — label, or 卡/page/zone/box/panel container vocabulary
#   装饰 — label, or glow/border/圆角/阴影/渐变/序号/图标/引号 decoration vocabulary
#   对齐 — label, or 左/中/右/居中/center/left/right
#   字距 — label, or an em tracking value / normal / tight
#   字重 — label, or a 400–900 weight number
# Compact slash-tuple shorthand: "40/700/左" or "32/700/居中/-0.01em" packs
# 字号/字重/对齐(/字距) into one token. Detect any size/weight slash pair so the
# dims it implies aren't reported as missing.
_SLASH_TUPLE = _re(r"\b\d{2,3}\s*/\s*(400|500|600|700|800|900)\b")

SIX_DIMENSIONS: list[tuple[str, Callable[[str], bool]]] = [
    ("字号", _any(_kw("字号", "font-size", "font_size", "fontsize"),
                  _re(r"\d{2,3}\s*(px|pt)\b"), _re(r"(?<![.\d])\d{2,3}(?![\d%])"),
                  _kw("绘制", "svg"))),
    ("容器", _any(_kw("容器", "container", "panel"),
                  _kw("卡", "页面", "page", "zone", "box", "胶囊", "pill", "band", "轨"))),
    ("装饰", _any(_kw("装饰", "decoration", "decor"),
                  _kw("glow", "border", "圆角", "阴影", "渐变", "序号", "图标", "引号",
                      "icon", "dashed", "hairline", "chevron", "箭头"))),
    ("对齐", _any(_kw("对齐", "align"),
                  _re(r"(?<![a-z])(左|中|右|居中|center|left|right)(?![a-z])"))),
    # 字距 defaults to normal and is routinely omitted when the rest of the
    # tuple is explicit; a size/weight slash-tuple counts as covering it.
    ("字距", _any(_kw("字距", "tracking", "letter-spacing", "letter_spacing", "letterspacing"),
                  _re(r"-?\d?\.?\d+\s*em\b"), _kw("normal", "tight"), _SLASH_TUPLE)),
    ("字重", _any(_kw("字重", "font-weight", "font_weight", "fontweight"),
                  _re(r"(?<![.\d])(400|500|600|700|800|900)(?![\d])"), _SLASH_TUPLE)),
]


# ---------------------------------------------------------------------------
# Result accumulator
# ---------------------------------------------------------------------------

class Result:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


# ---------------------------------------------------------------------------
# Layer 1 — shape check against the JSON Schema
# ---------------------------------------------------------------------------

_TYPE_PY = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
}


def _check_shape(schema: dict[str, Any], instance: Any, path: str, res: Result) -> None:
    """Lightweight Draft-2020-12 subset: type / required / properties / items.

    Enough to enforce outline.schema.json (which only uses those keywords plus
    pattern/minItems, treated as soft). Unknown keywords are ignored.
    """
    expected = schema.get("type")
    if expected:
        py = _TYPE_PY.get(expected)
        # bool is a subclass of int but we only map declared types, so this is safe.
        if py is not None and not isinstance(instance, py):
            res.err(f"{path}: expected {expected}")
            return  # type is wrong; deeper checks would be noise

    if expected == "object" or isinstance(instance, dict):
        if isinstance(instance, dict):
            for key in schema.get("required", []):
                if key not in instance:
                    res.err(f"{path}: missing required key '{key}'")
            for key, sub in schema.get("properties", {}).items():
                if key in instance and isinstance(sub, dict) and sub:
                    _check_shape(sub, instance[key], f"{path}.{key}", res)

    if expected == "array" and isinstance(instance, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict) and item_schema:
            for i, item in enumerate(instance):
                _check_shape(item_schema, item, f"{path}[{i}]", res)


# ---------------------------------------------------------------------------
# Layer 2 — raw-slide design contract
# ---------------------------------------------------------------------------

def _flatten_text(value: Any) -> str:
    """Collapse a design_spec (dict / list / str / nested) into one searchable
    blob including its keys, so prose specs like six_dim_A are covered."""
    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                parts.append(str(k))
                walk(v)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
        elif node is not None:
            parts.append(str(node))

    walk(value)
    return "\n".join(parts)


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def _locator(key: str, index_1based: int) -> str:
    return f"slides[{index_1based - 1}] (key='{key}', 第{index_1based}项)"


def _check_raw_slide(slide: dict[str, Any], index_1based: int, res: Result) -> None:
    key = slide.get("key") or f"slide-{index_1based:02d}"
    loc = _locator(key, index_1based)

    density = slide.get("density_budget")
    if _is_empty(density):
        res.err(f"{loc}: raw slide has empty density_budget")

    spec = slide.get("design_spec")
    if _is_empty(spec):
        res.err(f"{loc}: raw slide has empty design_spec (need 六维: 字号/容器/装饰/对齐/字距/字重)")
        return

    blob = _flatten_text(spec).lower()
    missing = []
    for label, covered in SIX_DIMENSIONS:
        if not covered(blob):
            missing.append(label)
    if missing:
        res.err(
            f"{loc}: raw slide design_spec missing 六维 dimension(s): "
            + "、".join(missing)
        )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def lint(outline: Any, schema: dict[str, Any]) -> Result:
    res = Result()
    _check_shape(schema, outline, "$", res)

    # Even if the shape check flagged problems, try the per-slide design check
    # for whatever slides do look like dicts — more findings in one pass.
    slides = outline.get("slides") if isinstance(outline, dict) else None
    if isinstance(slides, list):
        for i, slide in enumerate(slides, 1):
            if not isinstance(slide, dict):
                res.err(f"slides[{i - 1}] (第{i}项): expected object")
                continue
            intent = slide.get("layout_intent")
            if isinstance(intent, str) and intent.strip().lower().startswith("raw:"):
                _check_raw_slide(slide, i, res)
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("outline", type=Path, help="Path to outline.json")
    ap.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA, help="Path to outline.schema.json")
    args = ap.parse_args(argv)

    try:
        schema = json.loads(args.schema.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"outline-lint: cannot load schema {args.schema}: {exc}", file=sys.stderr)
        return 2
    try:
        outline = json.loads(args.outline.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"outline-lint: cannot load outline {args.outline}: {exc}", file=sys.stderr)
        return 2

    res = lint(outline, schema)
    if res.ok:
        n = len(outline.get("slides", [])) if isinstance(outline, dict) else 0
        print(f"outline-lint: OK — {args.outline} ({n} slides)")
        return 0

    print(f"outline-lint: {len(res.errors)} issue(s) in {args.outline}", file=sys.stderr)
    for msg in res.errors:
        print(f"  - {msg}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
