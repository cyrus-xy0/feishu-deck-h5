#!/usr/bin/env python3
"""Validate a JSON artifact against the lightweight local contract schema."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def validate(schema: dict[str, Any], instance: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for key in schema.get("required", []):
        if key not in instance:
            errors.append(f"missing required key: {key}")
    properties = schema.get("properties", {})
    for key, rules in properties.items():
        if key not in instance:
            continue
        expected = rules.get("type")
        if expected == "array" and not isinstance(instance[key], list):
            errors.append(f"{key}: expected array")
        elif expected == "object" and not isinstance(instance[key], dict):
            errors.append(f"{key}: expected object")
        elif expected == "string" and not isinstance(instance[key], str):
            errors.append(f"{key}: expected string")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--schema", required=True, type=Path)
    ap.add_argument("--instance", required=True, type=Path)
    args = ap.parse_args(argv)

    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    instance = json.loads(args.instance.read_text(encoding="utf-8"))
    errors = validate(schema, instance)
    if errors:
        print(json.dumps({"ok": False, "errors": errors}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "schema": str(args.schema), "instance": str(args.instance)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
