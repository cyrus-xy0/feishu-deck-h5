#!/usr/bin/env python3
"""Validate deck-outline-planner output with stdlib-only checks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


KEY_RE = re.compile(r"^[a-z][a-z0-9-]*$")
LAYOUTS = {
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
    "replica",
    "raw",
    "end",
}
VARIANT_REQUIRED = {"content", "stats", "flow"}
DELIVERY_MODES = {"local-agent", "feishu-bot", "unknown"}
EVIDENCE_LEVELS = {"user-provided", "approved-story", "public-pattern", "hypothesis"}


class Validator:
    def __init__(self, path: Path):
        self.path = path
        self.errors: list[str] = []
        self.root = self.find_repo_root(path.resolve())

    @staticmethod
    def find_repo_root(path: Path) -> Path:
        for parent in [path.parent, *path.parents]:
            if (parent / "knowledge").is_dir() and (parent / "skills").is_dir():
                return parent
        return Path.cwd()

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def require(self, obj: object, where: str, keys: list[str]) -> bool:
        if not isinstance(obj, dict):
            self.error(where, "expected object")
            return False
        ok = True
        for key in keys:
            if key not in obj:
                self.error(where, f"missing required field `{key}`")
                ok = False
        return ok

    def validate(self) -> bool:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - CLI validator should surface parse errors.
            self.error(str(self.path), f"invalid JSON: {exc}")
            return False

        self.require(data, "$", ["version", "brief", "scene", "thesis", "outline", "asset_plan", "claim_discipline", "handoff"])
        if data.get("version") != "1.0":
            self.error("$.version", "must be 1.0")

        self.validate_brief(data.get("brief"))
        self.validate_scene(data.get("scene"))
        self.validate_thesis(data.get("thesis"))
        self.validate_knowledge_refs(data.get("knowledge_refs", []))
        asset_ids = self.validate_assets(data.get("asset_plan"))
        self.validate_outline(data.get("outline"), asset_ids)
        self.validate_handoff(data.get("handoff"))
        return not self.errors

    def validate_brief(self, brief: object) -> None:
        if not self.require(brief, "$.brief", ["title", "audience", "objective", "delivery_mode"]):
            return
        mode = brief.get("delivery_mode")
        if mode not in DELIVERY_MODES:
            self.error("$.brief.delivery_mode", f"must be one of {sorted(DELIVERY_MODES)}")

    def validate_scene(self, scene: object) -> None:
        self.require(scene, "$.scene", ["industry", "business_moment", "core_tension", "confidence"])

    def validate_thesis(self, thesis: object) -> None:
        if not self.require(thesis, "$.thesis", ["one_sentence", "pain_points", "solution_angle"]):
            return
        pain_points = thesis.get("pain_points")
        if not isinstance(pain_points, list) or not pain_points:
            self.error("$.thesis.pain_points", "must contain at least one pain point")
            return
        for i, point in enumerate(pain_points):
            where = f"$.thesis.pain_points[{i}]"
            if not self.require(point, where, ["name", "why_now", "impact", "evidence_level"]):
                continue
            if point.get("evidence_level") not in EVIDENCE_LEVELS:
                self.error(f"{where}.evidence_level", f"must be one of {sorted(EVIDENCE_LEVELS)}")

    def validate_knowledge_refs(self, refs: object) -> None:
        if not isinstance(refs, list):
            self.error("$.knowledge_refs", "must be an array when present")
            return
        for i, ref in enumerate(refs):
            where = f"$.knowledge_refs[{i}]"
            if not self.require(ref, where, ["source", "used_for"]):
                continue
            if ref.get("source") != "feishu-base":
                self.error(f"{where}.source", "must be feishu-base")
            if not any(ref.get(key) for key in ["record_id", "doc_id", "query", "title"]):
                self.error(where, "must include at least one Base locator: record_id, doc_id, query, or title")

    def validate_assets(self, assets: object) -> set[str]:
        if not isinstance(assets, list):
            self.error("$.asset_plan", "must be an array")
            return set()
        seen: set[str] = set()
        for i, asset in enumerate(assets):
            where = f"$.asset_plan[{i}]"
            if not self.require(asset, where, ["id", "type", "need", "preferred_source"]):
                continue
            asset_id = asset.get("id")
            if not isinstance(asset_id, str) or not KEY_RE.match(asset_id):
                self.error(f"{where}.id", "must be kebab-case")
                continue
            if asset_id in seen:
                self.error(f"{where}.id", f"duplicate asset id `{asset_id}`")
            seen.add(asset_id)
        return seen

    def validate_outline(self, outline: object, asset_ids: set[str]) -> None:
        if not self.require(outline, "$.outline", ["arc", "slides"]):
            return
        slides = outline.get("slides")
        if not isinstance(slides, list) or len(slides) < 3:
            self.error("$.outline.slides", "must contain at least 3 slides")
            return
        seen: set[str] = set()
        for i, slide in enumerate(slides):
            where = f"$.outline.slides[{i}]"
            if not self.require(slide, where, ["key", "title", "role", "message", "layout_candidate"]):
                continue
            key = slide.get("key")
            if not isinstance(key, str) or not KEY_RE.match(key):
                self.error(f"{where}.key", "must be kebab-case")
            elif key in seen:
                self.error(f"{where}.key", f"duplicate slide key `{key}`")
            seen.add(key)

            candidate = slide.get("layout_candidate")
            if not self.require(candidate, f"{where}.layout_candidate", ["layout"]):
                continue
            layout = candidate.get("layout")
            if layout not in LAYOUTS:
                self.error(f"{where}.layout_candidate.layout", f"unknown layout `{layout}`")
            if layout in VARIANT_REQUIRED and not candidate.get("variant"):
                self.error(f"{where}.layout_candidate.variant", f"`{layout}` needs a variant")

            for asset_id in slide.get("assets", []) or []:
                if asset_id not in asset_ids:
                    self.error(f"{where}.assets", f"references missing asset_plan id `{asset_id}`")

    def validate_handoff(self, handoff: object) -> None:
        if not self.require(handoff, "$.handoff", ["target_skill", "deckjson_strategy"]):
            return
        if handoff.get("target_skill") != "feishu-deck-h5":
            self.error("$.handoff.target_skill", "must be feishu-deck-h5")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)

    ok = True
    for path in args.paths:
        validator = Validator(path)
        if validator.validate():
            print(f"PASS {path}")
            continue
        ok = False
        print(f"FAIL {path}", file=sys.stderr)
        for error in validator.errors:
            print(f"  - {error}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
