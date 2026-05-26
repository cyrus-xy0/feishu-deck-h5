#!/usr/bin/env python3
"""Build a deterministic index for assets/shared.

The index lets outline planning, H5 rendering, and bot delivery use the same
asset vocabulary instead of guessing paths from filenames.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
from pathlib import Path


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}
VIDEO_EXTS = {".mp4", ".mov", ".webm", ".m4v"}
DEMO_EXTS = {".html", ".htm"}
DATA_EXTS = {".json", ".csv", ".tsv", ".txt", ".md"}
SKIP_NAMES = {"README.md", "asset-index.schema.json", "asset-index.generated.json"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"[^a-z0-9._\-\u4e00-\u9fff]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    if re.search(r"[\u4e00-\u9fff]", value):
        return value
    return value or "asset"


def detect_kind(rel: Path) -> str:
    ext = rel.suffix.lower()
    parts = {p.lower() for p in rel.parts}
    rel_text = "/".join(rel.parts).lower()

    if "clientlogo" in parts or "logos" in parts or "logo" in rel_text:
        return "logo"
    if "feishu-products" in parts or "third-party-logos" in parts or "bytedance-products" in parts:
        return "icon"
    if "avatar" in rel_text or "mydigitalemployee" in parts or "digital_employee_avatars_50" in parts:
        return "avatar"
    if ext in VIDEO_EXTS:
        return "video"
    if ext in DEMO_EXTS or "demos" in parts:
        return "demo"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in DATA_EXTS:
        return "data"
    return "other"


def tags_for(rel: Path, kind: str) -> list[str]:
    tags = {kind}
    parts = list(rel.parts)
    collection = parts[0] if parts else "root"
    tags.add(collection)

    stem = rel.stem
    for token in re.split(r"[_\-\s]+", stem):
        token = token.strip()
        if token:
            tags.add(token)

    lower_stem = stem.lower()
    if "white" in lower_stem or "white" in stem:
        tags.add("white")
    if "black" in lower_stem or "black" in stem:
        tags.add("black")
    if "color" in lower_stem or "color" in stem:
        tags.add("color")

    return sorted(tags)


def build_index(root: Path) -> dict:
    if not root.exists():
        raise SystemExit(f"asset root not found: {root}")

    items = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith(".") or path.name in SKIP_NAMES:
            continue

        rel = path.relative_to(root)
        collection = rel.parts[0] if len(rel.parts) > 1 else "root"
        kind = detect_kind(rel)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        path_posix = rel.as_posix()
        item_id = slugify(path_posix.rsplit(".", 1)[0])

        items.append(
            {
                "id": item_id,
                "path": f"assets/shared/{path_posix}",
                "collection": collection,
                "kind": kind,
                "display_name": rel.stem,
                "mime": mime,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "tags": tags_for(rel, kind),
            }
        )

    return {"version": "1.0", "root": "assets/shared", "source": "local", "items": items}


def write_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(__file__).resolve().parent / "shared"
    parser.add_argument("--root", type=Path, default=default_root, help="asset root to scan")
    parser.add_argument("--output", type=Path, help="output JSON path")
    parser.add_argument("--check", action="store_true", help="exit non-zero if output is stale")
    parser.add_argument("--source", choices=["base", "local"], default="base",
                        help="source of truth for the index (default: base)")
    parser.add_argument("--as", dest="identity", choices=["user", "bot"],
                        default=os.environ.get("LARK_LIBRARY_AS", "user"),
                        help="identity used when --source=base")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    output = args.output or (root / "asset-index.generated.json")

    if args.source == "base":
        repo = Path(__file__).resolve().parents[3]
        provider = repo / "scripts" / "base_library.py"
        cmd = [
            sys.executable,
            str(provider),
            "--as",
            args.identity,
            "export-asset-index",
            "--output",
            str(output),
            *(["--check"] if args.check else []),
        ]
        return subprocess.run(cmd, cwd=repo).returncode

    rendered = write_json(build_index(root))

    if args.check:
        if not output.exists():
            print(f"asset index missing: {output}", file=sys.stderr)
            return 1
        current = output.read_text(encoding="utf-8")
        if current != rendered:
            print(f"asset index is stale: {output}", file=sys.stderr)
            print("run: python3 skills/feishu-deck-h5/assets/catalog-assets.py", file=sys.stderr)
            return 1
        print(f"asset index OK: {output}")
        return 0

    output.write_text(rendered, encoding="utf-8")
    print(f"wrote {output} ({len(json.loads(rendered)['items'])} assets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
