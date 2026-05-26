#!/usr/bin/env python3
"""Base-first library provider for deck assets and planning knowledge.

The Feishu Base configured in config/base-library.json is the source of
truth. Local files are cache copies only. This CLI is intentionally usable by
both local agent workflows and Feishu bot workers.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO / "config" / "base-library.json"
SKIP_INDEX_NAMES = {"README.md", "asset-index.schema.json", "asset-index.generated.json"}


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or Path(os.environ.get("LARK_LIBRARY_CONFIG", DEFAULT_CONFIG))
    if not config_path.is_absolute():
        config_path = REPO / config_path
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if os.environ.get("LARK_LIBRARY_BASE_TOKEN"):
        data["base_token"] = os.environ["LARK_LIBRARY_BASE_TOKEN"]
    return data


def repo_rel(path: Path) -> str:
    return path.resolve().relative_to(REPO).as_posix()


def field_value(record: dict[str, Any], name: str, default: Any = None) -> Any:
    return record.get(name, default)


def scalar(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, list):
        if not value:
            return default
        first = value[0]
        if isinstance(first, dict):
            return str(first.get("name") or first.get("text") or first.get("id") or default)
        return str(first)
    return str(value)


def list_value(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out = []
        for item in value:
            if isinstance(item, dict):
                out.append(str(item.get("name") or item.get("text") or item.get("id") or ""))
            else:
                out.append(str(item))
        return [item for item in out if item]
    return [str(value)]


def tags(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = list_value(value)
    else:
        raw = [part.strip() for part in str(value or "").split(",") if part.strip()]
    return list(dict.fromkeys(raw))


def run_lark(config: dict[str, Any], table: str, args: list[str], identity: str) -> dict[str, Any]:
    table_cfg = config["tables"][table]
    cmd = [
        "lark-cli",
        "base",
        *args,
        "--as",
        identity,
        "--base-token",
        config["base_token"],
        "--table-id",
        table_cfg["id"],
    ]
    proc = subprocess.run(cmd, cwd=REPO, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise SystemExit(f"base_library: command failed\n{' '.join(cmd)}\n{proc.stderr or proc.stdout}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"base_library: lark-cli returned non-JSON output:\n{proc.stdout}") from exc


def rows_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data", {})
    fields = data.get("fields", [])
    rows = data.get("data", [])
    record_ids = data.get("record_id_list", [])
    out = []
    for idx, row in enumerate(rows):
        item = {field: value for field, value in zip(fields, row)}
        if idx < len(record_ids):
            item["_record_id"] = record_ids[idx]
        out.append(item)
    return out


def list_records(config: dict[str, Any], table: str, identity: str, fields: list[str] | None = None) -> list[dict[str, Any]]:
    table_cfg = config["tables"][table]
    selected = fields or table_cfg["fields"]
    offset = 0
    all_rows: list[dict[str, Any]] = []
    while True:
        args = ["+record-list", "--format", "json", "--limit", "200", "--offset", str(offset)]
        for field in selected:
            args.extend(["--field-id", field])
        payload = run_lark(config, table, args, identity)
        rows = rows_from_payload(payload)
        all_rows.extend(rows)
        if not payload.get("data", {}).get("has_more"):
            break
        offset += len(rows)
        if not rows:
            break
    return all_rows


def search_records(config: dict[str, Any], table: str, keyword: str, identity: str, limit: int) -> list[dict[str, Any]]:
    if not keyword.strip():
        raise SystemExit("base_library: search keyword cannot be empty")
    table_cfg = config["tables"][table]
    body = {
        "keyword": keyword,
        "search_fields": table_cfg["search_fields"],
        "select_fields": table_cfg["fields"],
        "limit": limit,
        "offset": 0,
    }
    payload = run_lark(config, table, ["+record-search", "--format", "json", "--json", json.dumps(body, ensure_ascii=False)], identity)
    return rows_from_payload(payload)


def attachment_list(record: dict[str, Any]) -> list[dict[str, Any]]:
    value = record.get("附件") or []
    return value if isinstance(value, list) else []


def download_attachment(
    config: dict[str, Any],
    table: str,
    record: dict[str, Any],
    output_path: Path,
    identity: str,
    overwrite: bool,
) -> bool:
    attachments = attachment_list(record)
    if not attachments:
        return False
    token = attachments[0].get("file_token")
    if not token:
        return False
    size = attachments[0].get("size")
    if output_path.exists() and not overwrite and (not size or output_path.stat().st_size == int(size)):
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "+record-download-attachment",
        "--record-id",
        record["_record_id"],
        "--file-token",
        str(token),
        "--output",
        repo_rel(output_path),
        "--overwrite",
    ]
    run_lark(config, table, args, identity)
    return True


def shared_asset_records(config: dict[str, Any], identity: str) -> list[dict[str, Any]]:
    rows = list_records(config, "assets", identity)
    return [
        row
        for row in rows
        if scalar(row.get("本地路径")).startswith("skills/feishu-deck-h5/assets/shared/")
        and Path(scalar(row.get("本地路径"))).name not in SKIP_INDEX_NAMES
    ]


def sync_shared_assets(config: dict[str, Any], identity: str, overwrite: bool, quiet: bool) -> dict[str, int]:
    records = shared_asset_records(config, identity)
    downloaded = 0
    skipped = 0
    for row in records:
        target = REPO / scalar(row.get("本地路径"))
        if download_attachment(config, "assets", row, target, identity, overwrite):
            downloaded += 1
        else:
            skipped += 1
    if not quiet:
        print(json.dumps({"records": len(records), "downloaded": downloaded, "skipped": skipped}, ensure_ascii=False, indent=2))
    return {"records": len(records), "downloaded": downloaded, "skipped": skipped}


def asset_index_from_base(config: dict[str, Any], identity: str) -> dict[str, Any]:
    items = []
    for row in shared_asset_records(config, identity):
        full_path = scalar(row.get("本地路径"))
        rel_path = full_path.removeprefix("skills/feishu-deck-h5/")
        attachments = attachment_list(row)
        size_bytes = int(attachments[0].get("size", 0)) if attachments else int(float(row.get("大小KB") or 0) * 1024)
        items.append(
            {
                "collection": scalar(row.get("集合"), "root"),
                "display_name": scalar(row.get("显示名称")),
                "id": scalar(row.get("素材ID")),
                "kind": scalar(row.get("类型"), "other"),
                "mime": scalar(row.get("MIME"), "application/octet-stream"),
                "path": rel_path,
                "sha256": scalar(row.get("SHA256")),
                "size_bytes": size_bytes,
                "tags": tags(row.get("标签")),
            }
        )
    items.sort(key=lambda item: item["id"])
    return {"version": "1.0", "root": "assets/shared", "source": "feishu-base", "items": items}


def write_asset_index(config: dict[str, Any], identity: str, output: Path | None, check: bool) -> int:
    out = output or (REPO / config["local_cache"]["asset_index"])
    if not out.is_absolute():
        out = REPO / out
    rendered = json.dumps(asset_index_from_base(config, identity), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if check:
        current = out.read_text(encoding="utf-8") if out.exists() else ""
        if current != rendered:
            print(f"asset index is stale against Base: {repo_rel(out)}", file=sys.stderr)
            return 1
        print(f"asset index OK against Base: {repo_rel(out)}")
        return 0
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(rendered, encoding="utf-8")
    print(f"wrote {repo_rel(out)} ({len(json.loads(rendered)['items'])} Base assets)")
    return 0


def print_records(rows: list[dict[str, Any]], table: str, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    for row in rows:
        if table == "assets":
            attachments = attachment_list(row)
            print(
                f"- {scalar(row.get('素材ID'))} | {scalar(row.get('显示名称'))} | "
                f"{scalar(row.get('类型'))}/{scalar(row.get('格式'))} | {scalar(row.get('集合'))} | "
                f"{scalar(row.get('本地路径'))} | attachments={len(attachments)}"
            )
        else:
            print(
                f"- {scalar(row.get('文档ID'))} | {scalar(row.get('标题'))} | "
                f"{scalar(row.get('类型'))} | {scalar(row.get('关联行业'))} | {scalar(row.get('本地路径'))}\n"
                f"  {scalar(row.get('摘要'))}"
            )


def sync_knowledge_cache(config: dict[str, Any], identity: str, overwrite: bool, quiet: bool) -> dict[str, int]:
    records = list_records(config, "knowledge", identity)
    cache_root = REPO / config["local_cache"]["knowledge"]
    downloaded = 0
    skipped = 0
    for row in records:
        local_path = scalar(row.get("本地路径")) or f"{scalar(row.get('文档ID'))}.md"
        target = cache_root / local_path
        if download_attachment(config, "knowledge", row, target, identity, overwrite):
            downloaded += 1
        else:
            skipped += 1
    if not quiet:
        print(json.dumps({"records": len(records), "downloaded": downloaded, "skipped": skipped}, ensure_ascii=False, indent=2))
    return {"records": len(records), "downloaded": downloaded, "skipped": skipped}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="config/base-library.json override")
    parser.add_argument("--as", dest="identity", choices=["user", "bot"], default=os.environ.get("LARK_LIBRARY_AS", "user"))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search-assets", help="search the Base asset table")
    p.add_argument("keyword")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")

    p = sub.add_parser("search-knowledge", help="search the Base knowledge table")
    p.add_argument("keyword")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")

    p = sub.add_parser("sync-shared-assets", help="sync Base shared asset attachments into the local cache copy")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--export-index", action="store_true", help="also regenerate asset-index.generated.json from Base")

    p = sub.add_parser("sync-knowledge-cache", help="sync Base knowledge attachments into .base-cache/knowledge")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--quiet", action="store_true")

    p = sub.add_parser("export-asset-index", help="write asset-index.generated.json from Base records")
    p.add_argument("--output", type=Path)
    p.add_argument("--check", action="store_true")

    args = parser.parse_args(argv)
    config = load_config(args.config)

    if args.command == "search-assets":
        print_records(search_records(config, "assets", args.keyword, args.identity, args.limit), "assets", args.format)
        return 0
    if args.command == "search-knowledge":
        print_records(search_records(config, "knowledge", args.keyword, args.identity, args.limit), "knowledge", args.format)
        return 0
    if args.command == "sync-shared-assets":
        sync_shared_assets(config, args.identity, args.overwrite, args.quiet)
        if args.export_index:
            return write_asset_index(config, args.identity, None, False)
        return 0
    if args.command == "sync-knowledge-cache":
        sync_knowledge_cache(config, args.identity, args.overwrite, args.quiet)
        return 0
    if args.command == "export-asset-index":
        return write_asset_index(config, args.identity, args.output, args.check)
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
