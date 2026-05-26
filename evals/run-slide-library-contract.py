#!/usr/bin/env python3
"""Smoke-test the P2 local slide library contract."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "server"))

import generator  # noqa: E402
import slide_library  # noqa: E402


def has_error(issues: list[dict[str, str]]) -> bool:
    return any(issue.get("severity") == "error" for issue in issues)


def main() -> int:
    gate = slide_library.validate_library(include_candidates=False)
    if not gate["ok"] or gate["entries"] < 3:
        print("slide library gate failed or seed library is too small", file=sys.stderr)
        print(gate, file=sys.stderr)
        return 1

    rows = slide_library.search_slides(query="飞书", industry="消费零售", limit=5)
    if not rows:
        print("slide library search returned no rows", file=sys.stderr)
        return 1
    for row in rows:
        for key in ["thumbnail", "insert_suggestion", "slide", "layout", "source"]:
            if not row.get(key):
                print(f"search row missing {key}", file=sys.stderr)
                print(row, file=sys.stderr)
                return 1

    with tempfile.TemporaryDirectory() as td:
        old_candidates = slide_library.CANDIDATES_DIR
        slide_library.CANDIDATES_DIR = Path(td)
        task = generator.create_or_run_task(
            {
                "brief": {
                    "title": "P2 slide library candidate smoke",
                    "customer_name": "示例客户",
                    "industry": "消费零售",
                    "audience": "GTM",
                    "objective": "验证候选入库",
                    "product_scope": ["飞书AI", "多维表格", "知识问答"],
                }
            }
        )
        if task.get("status") != "succeeded":
            print("generator task for candidate failed", file=sys.stderr)
            print(task, file=sys.stderr)
            return 1
        result = slide_library.mark_reuse_candidate(
            task["id"],
            "business-gap",
            {
                "industry": ["消费零售"],
                "product": ["飞书AI"],
                "customer_stage": ["首访"],
                "deck_type": ["客户pitch"],
                "value_prop": ["业务闭环"],
                "tags": ["值得复用", "候选"],
            },
        )
        slide_library.CANDIDATES_DIR = old_candidates
    if has_error(result["issues"]):
        print("candidate gate produced errors", file=sys.stderr)
        print(result, file=sys.stderr)
        return 1

    print(rows[0]["id"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
