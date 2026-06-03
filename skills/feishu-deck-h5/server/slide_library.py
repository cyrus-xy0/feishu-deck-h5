"""Small local compatibility layer for subskill PPT registration.

The full cloud slide-library ingest is owned by FuQiang/feishu-slide-library.
This module only supports parser/publisher local PPT inventory modes so those
subskills can run in this repository without importing external code at startup.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "tmp" / "slide-library" / "ppt-uploads.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _pptx_slide_count(path: Path) -> int:
    try:
        with zipfile.ZipFile(path) as zf:
            return len([name for name in zf.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", name)])
    except Exception:
        return 0


def _slide_count(path: Path) -> int:
    if path.suffix.lower() == ".pptx":
        count = _pptx_slide_count(path)
        if count:
            return count
    return 1


def _read_registry() -> list[dict[str, Any]]:
    if not REGISTRY.exists():
        return []
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _write_registry(records: list[dict[str, Any]]) -> None:
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY.write_text(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def register_ppt_upload(path: str | Path, metadata: dict[str, Any], pages: list[int] | None = None) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    if not source.exists():
        return {
            "ok": False,
            "source": str(source),
            "slide_count": 0,
            "registered": [],
            "skipped": [{"reason": "source file not found", "path": str(source)}],
        }

    slide_count = _slide_count(source)
    selected_pages = pages or list(range(1, slide_count + 1))
    digest = _sha256(source)[:16]
    registered: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for page in selected_pages:
        if page < 1 or page > slide_count:
            skipped.append({"page": page, "reason": f"page outside 1..{slide_count}"})
            continue
        slide_key = f"ppt-{digest}-p{page:03d}"
        registered.append({
            "slide_key": slide_key,
            "page": page,
            "source": str(source),
            "metadata": metadata,
            "registered_at": _now_iso(),
        })

    if registered:
        records = _read_registry()
        records.extend(registered)
        _write_registry(records)

    return {
        "ok": bool(registered),
        "source": str(source),
        "slide_count": slide_count,
        "registered": registered,
        "skipped": skipped,
    }
