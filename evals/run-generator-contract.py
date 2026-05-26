#!/usr/bin/env python3
"""Smoke-test the P0 generator wrapper contract.

This check verifies that the productized wrapper, not just the local renderer,
can create a task and emit every fixed handoff artifact:

  deck.json, index.html, texts.md, FEEDBACK.md, assets-manifest.yaml, editable zip
"""

from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
GENERATOR = REPO / "server/generator.py"
REQUEST = REPO / "server/examples/brief-request.json"
REQUIRED = ["deck.json", "index.html", "texts.md", "FEEDBACK.md", "assets-manifest.yaml"]
ZIP_REQUIRED = ["index.html", "texts.md", "assets-manifest.yaml", "FEEDBACK.md", "deck.json"]


def main() -> int:
    proc = subprocess.run(
        ["python3", str(GENERATOR), "create", "--request", str(REQUEST)],
        cwd=REPO,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        return proc.returncode

    task = json.loads(proc.stdout)
    if task.get("status") != "succeeded":
        print(json.dumps(task, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    output_dir = Path(task["output_dir"])
    missing = [name for name in REQUIRED if not (output_dir / name).exists()]
    zip_paths = sorted(output_dir.glob("*.zip"))
    if not zip_paths:
        missing.append("editable zip")
    if missing:
        print(f"missing generator artifacts: {', '.join(missing)}", file=sys.stderr)
        return 1

    zip_path = zip_paths[0]
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        missing_in_zip = [name for name in ZIP_REQUIRED if name not in names]
        has_assets = any(name.startswith("assets/") and not name.endswith("/") for name in names)
    if missing_in_zip or not has_assets:
        print(f"bad editable zip: {zip_path}", file=sys.stderr)
        if missing_in_zip:
            print(f"  missing: {', '.join(missing_in_zip)}", file=sys.stderr)
        if not has_assets:
            print("  missing asset files under assets/", file=sys.stderr)
        return 1

    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
