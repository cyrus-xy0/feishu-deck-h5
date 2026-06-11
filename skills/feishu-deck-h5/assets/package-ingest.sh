#!/usr/bin/env bash
# feishu-deck-h5 · package a runs/<ts>/output/ folder for slide-library ingest.
#
# Usage:
#   bash assets/package-ingest.sh runs/<ts>/output --deck-id <deck-id>
#
# Produces:
#   runs/<ts>/output/deck.zip
#
# The ZIP root is the output folder contents directly: index.html, deck.json,
# assets/, assets-manifest.yaml, ingestion-manifest.json, ...

set -euo pipefail

OUT_DIR="${1:-}"
shift || true

DECK_ID=""
while [ $# -gt 0 ]; do
  case "$1" in
    --deck-id) DECK_ID="${2:?--deck-id requires a value}"; shift 2 ;;
    --name) echo "ERROR: package-ingest.sh does not accept --name; deck.zip is fixed" >&2; exit 1 ;;
    *) echo "ERROR: unknown arg: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$OUT_DIR" ] || [ ! -d "$OUT_DIR" ]; then
  echo "Usage: bash assets/package-ingest.sh <output-dir> --deck-id <deck-id>" >&2
  echo "       output-dir must exist (typically runs/<ts>/output/)" >&2
  exit 1
fi

if [ -z "$DECK_ID" ]; then
  echo "ERROR: --deck-id is required for slide-library ingest packages" >&2
  exit 1
fi

python3 - "$OUT_DIR" "$DECK_ID" <<'PY'
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

out_dir = Path(sys.argv[1]).resolve()
deck_id = sys.argv[2].strip()

if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", deck_id):
    sys.exit("ERROR: --deck-id must be a stable id using letters, numbers, dot, underscore, or dash")

hard_required = (
    "index.html",
    "deck.json",
    "assets",
    "assets-manifest.yaml",
    "ingestion-manifest.json",
)
soft_required = (
    "outline.json",
    "DESIGN-PLAN.md",
    "texts.md",
    "README.md",
)


def rel(path: Path) -> str:
    return path.relative_to(out_dir).as_posix()


def fail(message: str) -> None:
    sys.exit(f"ERROR: {message}")


def is_packaged_metadata(path: Path) -> bool:
    parts = path.relative_to(out_dir).parts
    return any(part.startswith(".") for part in parts)


for path in out_dir.rglob("*"):
    r = rel(path)
    parts = path.relative_to(out_dir).parts
    if path.is_symlink():
        fail(f"symlink is not allowed: {r}")
    if path.name == ".DS_Store" or "__MACOSX" in parts or path.name.startswith("._"):
        fail(f"system metadata is not allowed: {r}")

missing_hard = []
for item in hard_required:
    if item == "ingestion-manifest.json":
        continue
    target = out_dir / item
    if item == "assets":
        if not target.is_dir():
            missing_hard.append("assets/")
    elif not target.is_file():
        missing_hard.append(item)
if missing_hard:
    fail("missing hard required item(s): " + ", ".join(missing_hard))

soft_missing = [item for item in soft_required if not (out_dir / item).exists()]
for item in soft_missing:
    print(f"WARNING: missing soft required item: {item}", file=sys.stderr)

manifest = {
    "package_type": "feishu-deck-h5-library",
    "deck_id": deck_id,
    "primary_html": "index.html",
    "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    "hard_required": list(hard_required),
    "soft_required": list(soft_required),
    "soft_missing": soft_missing,
}
(out_dir / "ingestion-manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)

readme = f"""# feishu-deck-h5 material-library package

- deck_id: `{deck_id}`
- primary_html: `index.html`
- package: `deck.zip`

This `deck.zip` is the only standard upload format for feishu-slide-library web ingest.

Do not upload linked `index.html` by itself. It is only for local iteration inside `runs/<ts>/output/`.
Do not upload inline HTML for material-library ingest. Inline HTML is for preview, IM forwarding, and single-file viewing.
"""
(out_dir / "README.md").write_text(readme, encoding="utf-8")

missing_hard_after = []
for item in hard_required:
    target = out_dir / item
    if item == "assets":
        if not target.is_dir():
            missing_hard_after.append("assets/")
    elif not target.is_file():
        missing_hard_after.append(item)
if missing_hard_after:
    fail("missing hard required item(s) after manifest generation: " + ", ".join(missing_hard_after))

zip_path = out_dir / "deck.zip"
if zip_path.exists():
    zip_path.unlink()

stage = Path(tempfile.mkdtemp(prefix="feishu-deck-ingest-pkg."))
try:
    for item in sorted(out_dir.iterdir(), key=lambda p: p.name):
        if item.name == "deck.zip":
            continue
        if is_packaged_metadata(item):
            continue
        target = stage / item.name
        if item.is_dir():
            shutil.copytree(
                item,
                target,
                symlinks=False,
                ignore=lambda _dir, names: [name for name in names if name.startswith(".")],
            )
        else:
            shutil.copy2(item, target)

    for path in stage.rglob("*"):
        r = path.relative_to(stage).as_posix()
        parts = path.relative_to(stage).parts
        if path.is_symlink():
            fail(f"staging symlink is not allowed: {r}")
        if path.name == ".DS_Store" or "__MACOSX" in parts or path.name.startswith("._"):
            fail(f"staging metadata is not allowed: {r}")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(stage.rglob("*")):
            if path.is_dir():
                continue
            arcname = path.relative_to(stage).as_posix()
            if arcname.startswith("output/"):
                fail("internal error: refusing to write output/ wrapper into deck.zip")
            info = zipfile.ZipInfo(arcname)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100644 & 0xFFFF) << 16
            archive.writestr(info, path.read_bytes())
finally:
    shutil.rmtree(stage, ignore_errors=True)

size_kb = zip_path.stat().st_size // 1024
print("feishu-deck-h5 · package-ingest")
print(f"  deck_id : {deck_id}")
print(f"  wrote   : {zip_path} ({size_kb} KB)")
print("  format  : deck.zip with index.html at ZIP root")
PY
