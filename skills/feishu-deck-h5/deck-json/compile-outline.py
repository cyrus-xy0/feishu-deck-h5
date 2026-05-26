#!/usr/bin/env python3
"""Compile a deck-outline-planner outline into DeckJSON.

This is the deterministic bridge in the product loop:

  outline.json -> deck.json -> render-deck.py -> index.html

The compiler intentionally keeps business intent in notes/report, while
producing schema-valid DeckJSON that the renderer can consume directly.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
VALIDATE_DECK = HERE / "validate-deck.py"

KEY_RE = re.compile(r"^[a-z][a-z0-9-]*$")
VALID_LAYOUTS = {
    "cover",
    "agenda",
    "section",
    "content",
    "stats",
    "quote",
    "image-text",
    "table",
    "flow",
    "logo-wall",
    "arch-stack",
    "iframe-embed",
    "end",
    "replica",
    "raw",
}
VALID_VARIANTS = {
    "content": {"3up", "2col", "story-case", "blocks", "matrix", "before-after"},
    "stats": {"row", "hero", "waterfall"},
    "flow": {"timeline", "process", "tree", "swim"},
}
DEFAULT_VARIANT = {
    "content": "3up",
    "stats": "row",
    "flow": "process",
}
ICONS = ["message-circle", "check-circle", "users", "sparkles", "database", "flag"]


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - CLI should surface file/parse errors.
        raise SystemExit(f"compile-outline: failed to read {path}: {exc}") from exc


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def as_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def first_text(*values: Any, fallback: str) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


def normalize_key(value: Any, fallback: str) -> str:
    raw = str(value or "").strip().lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    if not raw or not re.match(r"^[a-z]", raw):
        raw = fallback
    if not KEY_RE.match(raw):
        raw = re.sub(r"-+", "-", raw)
        raw = re.sub(r"[^a-z0-9-]", "", raw)
    return raw if KEY_RE.match(raw) else fallback


def clamp_items(items: list[str], minimum: int, maximum: int, seed: list[str]) -> list[str]:
    out = [item for item in items if item][:maximum]
    for item in seed:
        if len(out) >= minimum:
            break
        if item and item not in out:
            out.append(item)
    while len(out) < minimum:
        out.append(f"要点 {len(out) + 1}")
    return out[:maximum]


def make_accent_phrase(text: str) -> dict[str, str]:
    normalized = text.strip() or "核心主张需要被看见"
    if len(normalized) < 6:
        normalized = f"{normalized}形成清晰共识"
    if len(normalized) <= 10:
        return {"lead": normalized[:1], "accent": normalized[1:3], "tail": normalized[3:] or "。"}
    start = max(1, len(normalized) // 3)
    end = min(len(normalized) - 1, start + max(2, len(normalized) // 5))
    return {
        "lead": normalized[:start],
        "accent": normalized[start:end],
        "tail": normalized[end:] or "。",
    }


def long_text(*parts: str) -> str:
    text = "。".join(part.strip("。") for part in parts if part and part.strip())
    if len(text) >= 10:
        return text
    return f"{text}，用于支撑本页主张的上下文。" if text else "用于支撑本页主张的上下文。"


class OutlineCompiler:
    def __init__(self, outline: dict[str, Any], args: argparse.Namespace):
        self.outline = outline
        self.args = args
        self.brief = outline.get("brief", {}) if isinstance(outline.get("brief"), dict) else {}
        self.scene = outline.get("scene", {}) if isinstance(outline.get("scene"), dict) else {}
        self.thesis = outline.get("thesis", {}) if isinstance(outline.get("thesis"), dict) else {}
        self.plan = outline.get("outline", {}) if isinstance(outline.get("outline"), dict) else {}
        self.asset_plan = outline.get("asset_plan", []) if isinstance(outline.get("asset_plan"), list) else []
        self.claims = outline.get("claim_discipline", {}) if isinstance(outline.get("claim_discipline"), dict) else {}
        self.report: dict[str, Any] = {
            "version": "1.0",
            "summary": {
                "input_title": self.brief.get("title"),
                "slides": 0,
                "warnings": 0,
            },
            "slide_mappings": [],
            "warnings": [],
            "claim_discipline": self.claims,
        }

    def warn(self, message: str, slide_key: str | None = None) -> None:
        item = {"message": message}
        if slide_key:
            item["slide_key"] = slide_key
        self.report["warnings"].append(item)

    def compile(self) -> dict[str, Any]:
        raw_slides = self.plan.get("slides", [])
        if not isinstance(raw_slides, list) or not raw_slides:
            raise SystemExit("compile-outline: outline.outline.slides must be a non-empty array")

        slides = [self.compile_slide(slide, i + 1, raw_slides) for i, slide in enumerate(raw_slides)]
        self.report["summary"]["slides"] = len(slides)
        self.report["summary"]["warnings"] = len(self.report["warnings"])

        notes = self.deck_notes()
        deck: dict[str, Any] = {
            "version": "1.0",
            "deck": self.deck_meta(),
            "slides": slides,
            "notes": notes,
        }
        assets = self.assets_manifest()
        if assets:
            deck["assets"] = assets
        return deck

    def deck_meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "title": first_text(self.brief.get("title"), fallback="未命名 Deck"),
            "author": self.args.author,
            "date": self.args.cover_date,
            "language": self.args.language,
            "mode": "rewrite",
        }
        if self.args.presentation_date:
            meta["presentation_date"] = self.args.presentation_date
        if self.args.customer_slug:
            meta["customer_slug"] = normalize_key(self.args.customer_slug, "compiled-deck")
        return meta

    def deck_notes(self) -> str:
        lines = [
            "Compiled from deck-outline-planner outline.",
            f"Arc: {self.plan.get('arc', '')}",
        ]
        unsupported = as_list(self.claims.get("unsupported_claims"))
        confirmations = as_list(self.claims.get("needs_user_confirmation"))
        if unsupported:
            lines.append("Unsupported claims: " + " / ".join(unsupported))
        if confirmations:
            lines.append("Needs confirmation: " + " / ".join(confirmations))
        return "\n".join(line for line in lines if line.strip())

    def assets_manifest(self) -> dict[str, Any] | None:
        scenes: dict[str, str] = {}
        logos: dict[str, str] = {}
        for item in self.asset_plan:
            if not isinstance(item, dict):
                continue
            asset_id = item.get("id")
            if not isinstance(asset_id, str) or not KEY_RE.match(asset_id):
                continue
            if item.get("type") == "logo":
                logos[asset_id] = f"asset:{asset_id}"
            elif item.get("type") in {"image", "video", "demo"}:
                scenes[asset_id] = f"asset:{asset_id}"
        if not scenes and not logos:
            return None
        return {"scenes": scenes, "logos": logos}

    def compile_slide(self, slide: Any, index: int, all_slides: list[Any]) -> dict[str, Any]:
        if not isinstance(slide, dict):
            raise SystemExit(f"compile-outline: slide {index} must be an object")
        source_key = str(slide.get("key") or "")
        key = normalize_key(source_key, f"slide-{index:02d}")
        mapping: dict[str, Any] = {
            "source_key": source_key,
            "key": key,
            "warnings": [],
        }
        if key != source_key:
            mapping["warnings"].append(f"key normalized from {source_key!r} to {key!r}")

        layout, variant = self.resolve_layout(slide, key, mapping)
        data = self.data_for(layout, variant, slide, index, all_slides)
        out: dict[str, Any] = {
            "key": key,
            "layout": layout,
            "screen_label": f"{index:02d} {first_text(slide.get('title'), fallback=key)}",
            "data": data,
        }
        if variant:
            out["variant"] = variant
        if layout not in {"cover", "end", "replica", "raw"}:
            out["accent"] = "blue"

        notes = self.slide_notes(slide)
        if notes:
            out["notes"] = notes

        mapping["layout"] = layout
        mapping["variant"] = variant
        mapping["role"] = slide.get("role")
        mapping["message"] = slide.get("message")
        self.report["slide_mappings"].append(mapping)
        for warning in mapping["warnings"]:
            self.warn(warning, key)
        return out

    def resolve_layout(self, slide: dict[str, Any], key: str, mapping: dict[str, Any]) -> tuple[str, str | None]:
        candidate = slide.get("layout_candidate")
        if not isinstance(candidate, dict):
            candidate = {}
        role = slide.get("role")
        requested = candidate.get("layout")
        layout = requested if requested in VALID_LAYOUTS else None
        if not layout:
            layout = "cover" if role == "cover" else "end" if role == "closing" else "content"
            mapping["warnings"].append(f"layout_candidate invalid or missing; used {layout!r}")

        requested_variant = candidate.get("variant")
        variant: str | None = None
        if layout in VALID_VARIANTS:
            if requested_variant in VALID_VARIANTS[layout]:
                variant = requested_variant
            else:
                variant = DEFAULT_VARIANT[layout]
                if requested_variant:
                    mapping["warnings"].append(
                        f"variant {requested_variant!r} is not valid for {layout!r}; used {variant!r}"
                    )
                else:
                    mapping["warnings"].append(f"variant missing for {layout!r}; used {variant!r}")
        elif requested_variant:
            mapping["warnings"].append(f"variant {requested_variant!r} dropped for single-layout {layout!r}")
        mapping["layout_candidate"] = candidate
        return layout, variant

    def slide_notes(self, slide: dict[str, Any]) -> str:
        lines = []
        for label, key in [
            ("role", "role"),
            ("message", "message"),
            ("visual_intent", "visual_intent"),
        ]:
            value = slide.get(key)
            if isinstance(value, str) and value.strip():
                lines.append(f"{label}: {value.strip()}")
        for label, key in [("evidence", "evidence"), ("risk_flags", "risk_flags")]:
            items = as_list(slide.get(key))
            if items:
                lines.append(f"{label}: " + " / ".join(items))
        return "\n".join(lines)

    def data_for(
        self,
        layout: str,
        variant: str | None,
        slide: dict[str, Any],
        index: int,
        all_slides: list[Any],
    ) -> dict[str, Any]:
        if layout == "cover":
            return self.data_cover(slide)
        if layout == "agenda":
            return self.data_agenda(slide, all_slides)
        if layout == "section":
            return self.data_section(slide, index)
        if layout == "content":
            return self.data_content(variant or "3up", slide)
        if layout == "stats":
            return self.data_stats(variant or "row", slide)
        if layout == "flow":
            return self.data_flow(variant or "process", slide)
        if layout == "quote":
            return self.data_quote(slide)
        if layout == "image-text":
            return self.data_image_text(slide)
        if layout == "table":
            return self.data_table(slide)
        if layout == "logo-wall":
            return self.data_logo_wall(slide)
        if layout == "arch-stack":
            return self.data_arch_stack(slide)
        if layout == "iframe-embed":
            return self.data_iframe(slide)
        if layout == "replica":
            return self.data_replica(slide)
        if layout == "raw":
            return self.data_raw(slide)
        if layout == "end":
            return self.data_end(slide)
        raise SystemExit(f"compile-outline: unsupported layout {layout!r}")

    def title(self, slide: dict[str, Any]) -> str:
        return first_text(slide.get("title"), slide.get("message"), fallback="未命名页面")

    def message(self, slide: dict[str, Any]) -> str:
        return first_text(slide.get("message"), self.thesis.get("one_sentence"), fallback=self.title(slide))

    def beats(self, slide: dict[str, Any], minimum: int = 3, maximum: int = 6) -> list[str]:
        return clamp_items(
            as_list(slide.get("content_beats")),
            minimum,
            maximum,
            [
                self.message(slide),
                self.scene.get("core_tension", ""),
                self.thesis.get("solution_angle", ""),
                "下一步行动",
            ],
        )

    def data_cover(self, slide: dict[str, Any]) -> dict[str, Any]:
        data = {
            "title": self.title(slide),
            "author": self.args.author,
            "date": self.args.cover_date,
        }
        msg = self.message(slide)
        if msg and msg != data["title"]:
            data["subtitle"] = msg
        return data

    def data_agenda(self, slide: dict[str, Any], all_slides: list[Any]) -> dict[str, Any]:
        beats = as_list(slide.get("content_beats"))
        if not beats:
            beats = [
                first_text(item.get("title"), fallback=str(item.get("key", "")))
                for item in all_slides
                if isinstance(item, dict) and item.get("role") not in {"cover", "closing"}
            ]
        return {"items": [{"title_zh": item} for item in clamp_items(beats, 1, 8, ["核心内容"])]}

    def data_section(self, slide: dict[str, Any], index: int) -> dict[str, Any]:
        data: dict[str, Any] = {
            "chapter_num": f"{index:02d}.",
            "title": self.title(slide),
            "lede": self.message(slide),
        }
        pills = as_list(slide.get("content_beats"))[:8]
        if pills:
            data["pills"] = pills
        return data

    def data_content(self, variant: str, slide: dict[str, Any]) -> dict[str, Any]:
        if variant == "2col":
            return self.content_2col(slide)
        if variant == "blocks":
            return self.content_blocks(slide)
        if variant == "matrix":
            return self.content_matrix(slide)
        if variant == "before-after":
            return self.content_before_after(slide)
        if variant == "story-case":
            return self.content_story_case(slide)
        return self.content_3up(slide)

    def content_3up(self, slide: dict[str, Any]) -> dict[str, Any]:
        beats = self.beats(slide, 3, 3)
        cards = []
        for i, beat in enumerate(beats, start=1):
            cards.append({
                "num": f"{i:02d}",
                "icon": ICONS[(i - 1) % len(ICONS)],
                "title_zh": beat,
                "body": long_text(self.message(slide), f"{beat}需要被组织成可执行动作"),
            })
        return {"title": self.title(slide), "lede": self.message(slide), "cards": cards}

    def content_2col(self, slide: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": self.title(slide),
            "text": {
                "lede": self.message(slide),
                "feature_list": self.beats(slide, 3, 6),
            },
            "visual": {"type": "placeholder", "label": first_text(slide.get("visual_intent"), fallback="示意视觉")},
        }

    def content_blocks(self, slide: dict[str, Any]) -> dict[str, Any]:
        beats = self.beats(slide, 2, 4)
        return {
            "title": self.title(slide),
            "lede": self.message(slide),
            "body_blocks": [{
                "type": "principle-band",
                "principles": [
                    {"text": beat, "color": ["teal", "blue", "purple", "teal"][i % 4]}
                    for i, beat in enumerate(beats)
                ],
            }],
        }

    def content_matrix(self, slide: dict[str, Any]) -> dict[str, Any]:
        beats = self.beats(slide, 4, 4)
        labels = ["立即验证", "重点建设", "暂缓观察", "控制风险"]
        quadrants = {}
        for key, label, beat, ord_ in zip(["tl", "tr", "bl", "br"], labels, beats, ["A", "B", "C", "D"]):
            quadrants[key] = {"ord": ord_, "title": label, "items": [beat]}
        return {
            "title": self.title(slide),
            "axes": {
                "y": {"name": "业务影响", "high_label": "高", "low_label": "低"},
                "x": {"name": "实施复杂度", "high_label": "高", "low_label": "低"},
            },
            "quadrants": quadrants,
        }

    def content_before_after(self, slide: dict[str, Any]) -> dict[str, Any]:
        beats = self.beats(slide, 3, 6)
        return {
            "title": self.title(slide),
            "before": {
                "tag": "现状 · 断点",
                "items": [f"{beat}依赖人工追踪" for beat in beats],
            },
            "pivot": {"caption": "飞书 bot + agent"},
            "after": {
                "tag": "升级后 · 闭环",
                "items": [f"{beat}进入任务、知识、数据闭环" for beat in beats],
            },
        }

    def content_story_case(self, slide: dict[str, Any]) -> dict[str, Any]:
        title = self.title(slide)
        message = self.message(slide)
        beats = self.beats(slide, 3, 4)
        asset = self.first_asset(slide) or "asset:story-scene"
        if asset == "asset:story-scene":
            self.warn("story-case has no scene asset; renderer will use the generated asset reference", slide.get("key"))
        return {
            "title": title,
            "industry": first_text(self.scene.get("industry"), fallback="业务场景"),
            "hook": make_accent_phrase(message),
            "arc": {
                "pain": long_text(beats[0], self.scene.get("core_tension", "")),
                "conflict": long_text(beats[1], "当前工作方式难以形成可追踪闭环"),
                "solution": long_text(beats[2], self.thesis.get("solution_angle", "")),
                "value": make_accent_phrase(self.thesis.get("one_sentence") or message),
            },
            "scene": {
                "image": asset,
                "caption": first_text(slide.get("visual_intent"), fallback="业务场景示意"),
                "alt": title,
                "fit": "cover",
            },
        }

    def data_stats(self, variant: str, slide: dict[str, Any]) -> dict[str, Any]:
        self.warn("stats layout compiled with ordinal placeholders; replace with verified metrics before delivery", slide.get("key"))
        if variant == "hero":
            return {
                "title": self.title(slide),
                "eyebrow": "关键判断",
                "stat": {"number": "1", "unit": "个闭环"},
                "heading": self.title(slide),
                "body": long_text(self.message(slide), "请在获得真实数据后替换为可引用指标"),
            }
        if variant == "waterfall":
            beats = self.beats(slide, 3, 6)
            bars = [{"kind": "base", "value": "1", "label": beats[0], "delta": "起点"}]
            for beat in beats[1:-1]:
                bars.append({"kind": "pos", "value": "+1", "label": beat})
            bars.append({"kind": "end", "value": str(len(beats)), "label": beats[-1], "delta": "目标态"})
            return {"title": self.title(slide), "bars": bars, "footnote": "指标需用客户确认数据替换。"}
        beats = self.beats(slide, 3, 4)
        return {
            "title": self.title(slide),
            "cols": [
                {"icon": ICONS[i % len(ICONS)], "num": f"{i + 1:02d}", "label": beat}
                for i, beat in enumerate(beats)
            ],
            "footnote": "序号用于占位,交付前替换为真实指标。",
        }

    def data_quote(self, slide: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": self.title(slide),
            "quote": make_accent_phrase(self.message(slide)),
            "attribution": "Outline thesis",
        }

    def data_image_text(self, slide: dict[str, Any]) -> dict[str, Any]:
        src = self.first_asset(slide) or "asset:outline-visual"
        if src == "asset:outline-visual":
            self.warn("image-text has no asset; renderer will reference asset:outline-visual", slide.get("key"))
        return {
            "image": {"src": src, "alt": self.title(slide), "fit": "cover"},
            "title": self.title(slide),
            "lede": self.message(slide),
        }

    def data_table(self, slide: dict[str, Any]) -> dict[str, Any]:
        rows = [[beat, "当前做法待梳理", "建议动作进入闭环"] for beat in self.beats(slide, 1, 6)]
        return {
            "title": self.title(slide),
            "headers": ["维度", "当前方式", "建议动作"],
            "rows": rows,
        }

    def data_flow(self, variant: str, slide: dict[str, Any]) -> dict[str, Any]:
        if variant == "timeline":
            beats = self.beats(slide, 3, 6)
            return {
                "title": self.title(slide),
                "cols": len(beats),
                "nodes": [
                    {"when": f"阶段 {i}", "what": beat, "desc": self.message(slide)}
                    for i, beat in enumerate(beats, start=1)
                ],
            }
        if variant == "tree":
            beats = self.beats(slide, 2, 4)
            return {
                "title": self.title(slide),
                "root": {"question": self.title(slide), "why": self.message(slide)},
                "branches": [
                    {"ord": chr(65 + i), "title": beat, "leaves": [long_text(beat, self.message(slide))]}
                    for i, beat in enumerate(beats)
                ],
            }
        if variant == "swim":
            beats = self.beats(slide, 2, 5)
            time_axis = ["启动", "试跑", "复盘"]
            return {
                "title": self.title(slide),
                "time_axis": time_axis,
                "lanes": [
                    {
                        "name": beat,
                        "accent": ["blue", "teal", "violet", "orange"][i % 4],
                        "milestones": [
                            {"quarter": 1, "title": "接入", "desc": "明确输入和负责人"},
                            {"quarter": 2, "title": "运行", "desc": "按场景试跑"},
                            {"quarter": 3, "title": "复盘", "desc": "沉淀下一步动作"},
                        ],
                    }
                    for i, beat in enumerate(beats)
                ],
            }
        beats = self.beats(slide, 3, 6)
        return {
            "title": self.title(slide),
            "cols": len(beats),
            "steps": [
                {"num": f"{i:02d}", "title": beat, "body": self.message(slide)}
                for i, beat in enumerate(beats, start=1)
            ],
        }

    def data_logo_wall(self, slide: dict[str, Any]) -> dict[str, Any]:
        logo_assets = [
            item.get("query") or item.get("id")
            for item in self.asset_plan
            if isinstance(item, dict) and item.get("type") == "logo"
        ]
        logos = clamp_items([str(item) for item in logo_assets if item], 3, 12, ["客户 logo", "飞书", "业务系统"])
        self.warn("logo-wall uses logical logo keys; confirm assets/shared/clientlogo contains these files", slide.get("key"))
        return {
            "title": self.title(slide),
            "lede": self.message(slide),
            "industries": [{
                "name": first_text(self.scene.get("industry"), fallback="目标行业"),
                "logos": logos,
            }],
        }

    def data_arch_stack(self, slide: dict[str, Any]) -> dict[str, Any]:
        beats = self.beats(slide, 3, 6)
        layer_titles = ["用户入口", "Agent 能力", "业务协同", "知识数据"]
        layers = []
        for i, name in enumerate(layer_titles):
            modules = clamp_items(beats[i:] + beats[:i], 3, 8, ["任务", "知识", "数据"])
            layers.append({
                "name": {"title": name, "sub": ["ENTRY", "AGENT", "WORKFLOW", "DATA"][i]},
                "modules": modules,
            })
        return {"title": self.title(slide), "layers": layers}

    def data_iframe(self, slide: dict[str, Any]) -> dict[str, Any]:
        src = self.first_asset(slide) or "about:blank"
        if src == "about:blank":
            self.warn("iframe-embed has no HTML/demo asset; using about:blank", slide.get("key"))
        return {
            "title": self.title(slide),
            "src": src,
            "iframe_title": self.title(slide),
            "hint": self.message(slide),
        }

    def data_replica(self, slide: dict[str, Any]) -> dict[str, Any]:
        src = self.first_asset(slide) or "replica-placeholder.svg"
        if src == "replica-placeholder.svg":
            self.warn("replica has no page image; using replica-placeholder.svg", slide.get("key"))
        return {"page_image": src, "alt": self.title(slide), "source_page": 1}

    def data_raw(self, slide: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": self.title(slide),
            "html": (
                '<div class="raw-outline-slide">'
                f"<h2>{html.escape(self.title(slide))}</h2>"
                f"<p>{html.escape(self.message(slide))}</p>"
                "</div>"
            ),
        }

    def data_end(self, slide: dict[str, Any]) -> dict[str, Any]:
        return {
            "title": self.title(slide),
            "slogan": self.message(slide),
        }

    def first_asset(self, slide: dict[str, Any]) -> str | None:
        assets = as_list(slide.get("assets"))
        if not assets:
            return None
        return f"asset:{assets[0]}"


def write_feedback(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Outline Compile Feedback",
        "",
        f"- slides: {report.get('summary', {}).get('slides', 0)}",
        f"- warnings: {report.get('summary', {}).get('warnings', 0)}",
        "",
        "## Slide mappings",
        "",
    ]
    for item in report.get("slide_mappings", []):
        variant = f" / {item['variant']}" if item.get("variant") else ""
        lines.append(f"- `{item['key']}` -> `{item['layout']}{variant}`")
        for warning in item.get("warnings", []):
            lines.append(f"  - warning: {warning}")
    warnings = report.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        for warning in warnings:
            prefix = f"`{warning.get('slide_key')}`: " if warning.get("slide_key") else ""
            lines.append(f"- {prefix}{warning.get('message')}")
    claims = report.get("claim_discipline", {})
    if claims:
        lines.extend(["", "## Claim discipline", ""])
        for label in ["unsupported_claims", "needs_user_confirmation"]:
            items = as_list(claims.get(label))
            if items:
                lines.append(f"- {label}: " + " / ".join(items))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_validate(path: Path) -> int:
    proc = subprocess.run(
        [sys.executable, str(VALIDATE_DECK), str(path)],
        capture_output=True,
        text=True,
    )
    if proc.stdout:
        print(proc.stdout, file=sys.stderr, end="")
    if proc.stderr:
        print(proc.stderr, file=sys.stderr, end="")
    return proc.returncode


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("outline", type=Path, help="Path to deck-outline-planner outline JSON")
    parser.add_argument("out", nargs="?", type=Path, help="Path to write DeckJSON. Omit to print to stdout")
    parser.add_argument("--report", type=Path, help="Optional compile-report.json path")
    parser.add_argument("--feedback", type=Path, help="Optional FEEDBACK.md path")
    parser.add_argument("--author", default="飞书企业 AI", help="Cover/deck author")
    parser.add_argument("--cover-date", default="Deck 草案", help="Cover/deck display date")
    parser.add_argument("--presentation-date", help="Optional ISO YYYY-MM-DD for DeckJSON deck.presentation_date")
    parser.add_argument("--customer-slug", help="Optional kebab-case customer slug for delivery filename")
    parser.add_argument("--language", choices=["zh-only", "zh-en"], default="zh-only")
    parser.add_argument("--no-validate", action="store_true", help="Skip validate-deck.py after writing")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    outline = load_json(args.outline)
    compiler = OutlineCompiler(outline, args)
    deck = compiler.compile()

    if args.out:
        write_json(args.out, deck)
        compiler.report["output"] = str(args.out)
    else:
        print(json.dumps(deck, ensure_ascii=False, indent=2))

    compiler.report["input"] = str(args.outline)
    compiler.report["summary"]["warnings"] = len(compiler.report["warnings"])
    if args.report:
        write_json(args.report, compiler.report)
    if args.feedback:
        write_feedback(args.feedback, compiler.report)

    if args.out and not args.no_validate:
        return run_validate(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
