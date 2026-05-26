#!/usr/bin/env python3
"""Local P2 slide library provider.

This module is the first productized boundary between the generator/editor and
reusable team assets. Feishu Base remains the long-term source of truth; this
local library gives CI, demos, and offline workers a deterministic gate/search
contract.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
BUSINESS_LIBRARY = REPO / "library/business/slides"
CANDIDATES_DIR = REPO / "library/business/candidates"
DESIGN_KIT = REPO / "library/design-kit/manifest.json"
EXAMPLE_DECKS = REPO / "skills/feishu-deck-h5/deck-json/examples"
RUNS_DIR = REPO / "runs"

ALLOWED_SOURCE_LEVELS = {
    "synthetic",
    "public-pattern",
    "internal-draft",
    "internal-approved",
    "customer-approved",
}
APPROVED_STATUSES = {"approved", "candidate", "rejected"}
REQUIRED_ENTRY_KEYS = [
    "id",
    "title",
    "status",
    "thumbnail",
    "tags",
    "industry",
    "product",
    "customer_stage",
    "deck_type",
    "value_prop",
    "layout",
    "source",
    "slide",
]
SENSITIVE_PATTERNS = [
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("phone", re.compile(r"(?<!\d)(?:1[3-9]\d{9}|\+?\d[\d -]{8,}\d)(?!\d)")),
    ("sensitive-word", re.compile(r"(客户机密|严格保密|未公开|身份证|银行卡|NDA|confidential)", re.I)),
]


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def repo_rel(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO).as_posix()
    except ValueError:
        return str(resolved)


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(normalize_list(item))
        return list(dict.fromkeys(out))
    return [part.strip() for part in re.split(r"[,;，；、\n]+", str(value)) if part.strip()]


def text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(text_values(item))
        return out
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(text_values(item))
        return out
    return []


def slide_title(slide: dict[str, Any]) -> str:
    data = slide.get("data") if isinstance(slide.get("data"), dict) else {}
    for key in ["title", "slogan", "quote", "lede"]:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return str(slide.get("key") or slide.get("layout") or "slide")


def slide_text(slide: dict[str, Any]) -> str:
    return "\n".join(text_values(slide.get("data") or {})).strip()


def load_design_kit() -> dict[str, Any]:
    if not DESIGN_KIT.exists():
        return {"version": "1.0", "items": []}
    return read_json(DESIGN_KIT)


def load_business_entries(include_candidates: bool = False) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for root in [BUSINESS_LIBRARY, CANDIDATES_DIR] if include_candidates else [BUSINESS_LIBRARY]:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.json")):
            entry = read_json(path)
            entry["_path"] = repo_rel(path)
            entries.append(entry)
    return entries


def fallback_example_entries(limit: int = 36) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for source in sorted(EXAMPLE_DECKS.glob("*.json")):
        try:
            deck = read_json(source)
        except Exception:
            continue
        for slide in deck.get("slides", []):
            if not isinstance(slide, dict) or slide.get("layout") in {"cover", "end", "raw", "replica"}:
                continue
            entry = {
                "id": f"example-{source.stem}-{slide.get('key')}",
                "title": slide_title(slide),
                "status": "candidate",
                "thumbnail": "",
                "tags": ["example", str(slide.get("layout", "")), str(slide.get("variant", ""))],
                "industry": ["通用"],
                "product": ["飞书"],
                "customer_stage": ["首访", "POC"],
                "deck_type": ["客户 pitch"],
                "value_prop": normalize_list(slide_title(slide)),
                "layout": slide.get("layout"),
                "variant": slide.get("variant", ""),
                "source": {
                    "level": "synthetic",
                    "deck": repo_rel(source),
                    "slide_key": slide.get("key"),
                    "owner": "lark-deck-cyrus",
                },
                "slide": slide,
            }
            entries.append(entry)
            if len(entries) >= limit:
                return entries
    return entries


def library_entries(include_candidates: bool = False, fallback: bool = True) -> list[dict[str, Any]]:
    entries = load_business_entries(include_candidates=include_candidates)
    if entries or not fallback:
        return entries
    return fallback_example_entries()


def entry_terms(entry: dict[str, Any]) -> str:
    fields = [
        entry.get("id"),
        entry.get("title"),
        entry.get("layout"),
        entry.get("variant"),
        entry.get("thumbnail"),
        entry.get("source", {}).get("deck") if isinstance(entry.get("source"), dict) else "",
        slide_text(entry.get("slide") or {}),
    ]
    for key in ["tags", "industry", "product", "customer_stage", "deck_type", "value_prop"]:
        fields.extend(normalize_list(entry.get(key)))
    return " ".join(str(item) for item in fields if item).lower()


def validate_entry(entry: dict[str, Any], *, seen_ids: set[str], seen_slide_keys: set[str]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for key in REQUIRED_ENTRY_KEYS:
        if entry.get(key) in (None, "", []):
            issues.append({"severity": "error", "code": "LIB-MISSING-FIELD", "message": f"missing {key}"})

    entry_id = str(entry.get("id", ""))
    if entry_id in seen_ids:
        issues.append({"severity": "error", "code": "LIB-DUPLICATE-ID", "message": entry_id})
    seen_ids.add(entry_id)

    status = entry.get("status")
    if status not in APPROVED_STATUSES:
        issues.append({"severity": "error", "code": "LIB-STATUS", "message": f"invalid status: {status}"})

    source = entry.get("source") if isinstance(entry.get("source"), dict) else {}
    level = source.get("level")
    if level not in ALLOWED_SOURCE_LEVELS:
        issues.append({"severity": "error", "code": "LIB-SOURCE-LEVEL", "message": f"invalid source level: {level}"})
    for key in ["deck", "slide_key", "owner"]:
        if not source.get(key):
            issues.append({"severity": "error", "code": "LIB-SOURCE", "message": f"source.{key} is required"})

    slide = entry.get("slide") if isinstance(entry.get("slide"), dict) else {}
    slide_key = str(slide.get("key") or source.get("slide_key") or "")
    if not slide_key:
        issues.append({"severity": "error", "code": "LIB-SLIDE-KEY", "message": "slide key is required"})
    elif slide_key in seen_slide_keys:
        issues.append({"severity": "error", "code": "LIB-DUPLICATE-SLIDE-KEY", "message": slide_key})
    seen_slide_keys.add(slide_key)

    if entry.get("layout") != slide.get("layout"):
        issues.append({"severity": "error", "code": "LIB-LAYOUT-MISMATCH", "message": "entry.layout must match slide.layout"})

    thumbnail = str(entry.get("thumbnail") or "")
    if thumbnail and not (REPO / thumbnail).exists():
        issues.append({"severity": "error", "code": "LIB-THUMBNAIL", "message": f"thumbnail not found: {thumbnail}"})

    if not slide_text(slide):
        issues.append({"severity": "error", "code": "LIB-TEXT", "message": "slide text is empty"})

    haystack = " ".join(
        [
            str(entry.get("title") or ""),
            " ".join(normalize_list(entry.get("tags"))),
            " ".join(normalize_list(entry.get("industry"))),
            " ".join(normalize_list(entry.get("product"))),
            slide_text(slide),
        ]
    ).lower()
    for code, pattern in SENSITIVE_PATTERNS:
        if pattern.search(haystack):
            issues.append({"severity": "error", "code": "LIB-SENSITIVE", "message": f"sensitive pattern matched: {code}"})

    if status == "approved" and level in {"internal-draft"}:
        issues.append({"severity": "error", "code": "LIB-APPROVAL", "message": "approved entries cannot use internal-draft source level"})

    return issues


def validate_library(include_candidates: bool = True) -> dict[str, Any]:
    entries = library_entries(include_candidates=include_candidates, fallback=False)
    seen_ids: set[str] = set()
    seen_slide_keys: set[str] = set()
    results = []
    ok = True
    for entry in entries:
        issues = validate_entry(entry, seen_ids=seen_ids, seen_slide_keys=seen_slide_keys)
        if any(issue["severity"] == "error" for issue in issues):
            ok = False
        results.append({"id": entry.get("id"), "path": entry.get("_path"), "issues": issues})
    return {"ok": ok, "entries": len(entries), "results": results}


def matches_filter(entry: dict[str, Any], key: str, value: str | None) -> bool:
    if not value:
        return True
    if key == "layout":
        return str(entry.get("layout", "")).lower() == value.lower()
    needle = value.lower()
    return any(needle in item.lower() for item in normalize_list(entry.get(key)))


def search_slides(
    *,
    query: str = "",
    industry: str = "",
    product: str = "",
    customer_stage: str = "",
    deck_type: str = "",
    value_prop: str = "",
    layout: str = "",
    include_candidates: bool = False,
    limit: int = 20,
) -> list[dict[str, Any]]:
    query_terms = [term.lower() for term in normalize_list(query)]
    filters = {
        "industry": industry,
        "product": product,
        "customer_stage": customer_stage,
        "deck_type": deck_type,
        "value_prop": value_prop,
        "layout": layout,
    }
    matched: list[dict[str, Any]] = []
    for entry in library_entries(include_candidates=include_candidates):
        if entry.get("status") == "rejected":
            continue
        if any(not matches_filter(entry, key, value) for key, value in filters.items()):
            continue
        terms = entry_terms(entry)
        if query_terms and not all(term in terms for term in query_terms):
            continue
        matched.append(summarize_entry(entry))
        if len(matched) >= limit:
            break
    return matched


def summarize_entry(entry: dict[str, Any]) -> dict[str, Any]:
    slide = entry.get("slide") or {}
    layout = entry.get("layout") or slide.get("layout")
    variant = entry.get("variant") or slide.get("variant", "")
    return {
        "id": entry.get("id"),
        "title": entry.get("title") or slide_title(slide),
        "status": entry.get("status"),
        "thumbnail": entry.get("thumbnail", ""),
        "tags": normalize_list(entry.get("tags")),
        "industry": normalize_list(entry.get("industry")),
        "product": normalize_list(entry.get("product")),
        "customer_stage": normalize_list(entry.get("customer_stage")),
        "deck_type": normalize_list(entry.get("deck_type")),
        "value_prop": normalize_list(entry.get("value_prop")),
        "layout": layout,
        "variant": variant,
        "source": entry.get("source", {}),
        "text": slide_text(slide)[:500],
        "insert_suggestion": f"插入为 {layout}{('/' + variant) if variant else ''},再替换客户事实和指标。",
        "slide": slide,
    }


def mark_reuse_candidate(task_id: str, slide_key: str, metadata: dict[str, Any]) -> dict[str, Any]:
    deck_path = RUNS_DIR / task_id / "output/deck.json"
    if not deck_path.exists():
        raise FileNotFoundError(f"deck.json not found for task: {task_id}")
    deck = read_json(deck_path)
    slide = next((item for item in deck.get("slides", []) if item.get("key") == slide_key), None)
    if not slide:
        raise ValueError(f"slide not found: {slide_key}")

    entry_id = re.sub(r"[^a-z0-9-]+", "-", f"candidate-{task_id}-{slide_key}".lower()).strip("-")[:96]
    entry = {
        "version": "1.0",
        "id": entry_id,
        "title": metadata.get("title") or slide_title(slide),
        "status": "candidate",
        "thumbnail": metadata.get("thumbnail") or "library/business/thumbnails/pending.svg",
        "tags": normalize_list(metadata.get("tags") or metadata.get("tag") or ["needs-review"]),
        "industry": normalize_list(metadata.get("industry") or ["待标注"]),
        "product": normalize_list(metadata.get("product") or ["待标注"]),
        "customer_stage": normalize_list(metadata.get("customer_stage") or ["待标注"]),
        "deck_type": normalize_list(metadata.get("deck_type") or ["待标注"]),
        "value_prop": normalize_list(metadata.get("value_prop") or slide_title(slide)),
        "layout": slide.get("layout"),
        "variant": slide.get("variant", ""),
        "source": {
            "level": metadata.get("source_level") or "internal-draft",
            "deck": f"runs/{task_id}/output/deck.json",
            "slide_key": slide_key,
            "owner": metadata.get("owner") or "gtm",
            "reviewer": metadata.get("reviewer", ""),
        },
        "slide": slide,
    }
    target = CANDIDATES_DIR / f"{entry_id}.json"
    write_json(target, entry)
    check = validate_entry(entry, seen_ids=set(), seen_slide_keys=set())
    return {"path": repo_rel(target), "entry": summarize_entry(entry), "issues": check}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="search reusable business slides")
    search.add_argument("--query", default="")
    search.add_argument("--industry", default="")
    search.add_argument("--product", default="")
    search.add_argument("--customer-stage", default="")
    search.add_argument("--deck-type", default="")
    search.add_argument("--value-prop", default="")
    search.add_argument("--layout", default="")
    search.add_argument("--include-candidates", action="store_true")
    search.add_argument("--limit", type=int, default=20)

    validate = sub.add_parser("validate", help="run slide library gate")
    validate.add_argument("--approved-only", action="store_true")

    mark = sub.add_parser("mark-reuse", help="create a review candidate from a generated task")
    mark.add_argument("--task-id", required=True)
    mark.add_argument("--slide-key", required=True)
    mark.add_argument("--title")
    mark.add_argument("--industry", action="append", default=[])
    mark.add_argument("--product", action="append", default=[])
    mark.add_argument("--customer-stage", action="append", default=[])
    mark.add_argument("--deck-type", action="append", default=[])
    mark.add_argument("--value-prop", action="append", default=[])
    mark.add_argument("--tag", action="append", default=[])
    mark.add_argument("--source-level", default="internal-draft")
    mark.add_argument("--owner", default="gtm")
    mark.add_argument("--reviewer", default="")

    args = parser.parse_args(argv)
    if args.command == "search":
        rows = search_slides(
            query=args.query,
            industry=args.industry,
            product=args.product,
            customer_stage=args.customer_stage,
            deck_type=args.deck_type,
            value_prop=args.value_prop,
            layout=args.layout,
            include_candidates=args.include_candidates,
            limit=args.limit,
        )
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if args.command == "validate":
        result = validate_library(include_candidates=not args.approved_only)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    if args.command == "mark-reuse":
        result = mark_reuse_candidate(
            args.task_id,
            args.slide_key,
            {
                "title": args.title,
                "industry": args.industry,
                "product": args.product,
                "customer_stage": args.customer_stage,
                "deck_type": args.deck_type,
                "value_prop": args.value_prop,
                "tags": args.tag,
                "source_level": args.source_level,
                "owner": args.owner,
                "reviewer": args.reviewer,
            },
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not any(issue["severity"] == "error" for issue in result["issues"]) else 1
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
