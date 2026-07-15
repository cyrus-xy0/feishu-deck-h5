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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/materialize-remote-images.py" "$OUT_DIR"

# Fail closed before writing a new package. Removing a previous package first
# prevents a failed rerun from leaving a stale deck.zip that looks successful.
ZIP_PATH="$OUT_DIR/deck.zip"
CLOSURE_REPORT="$OUT_DIR/.asset-closure.json"
rm -f "$ZIP_PATH" "$CLOSURE_REPORT"
trap 'rm -f "$CLOSURE_REPORT"' EXIT
python3 "$SCRIPT_DIR/ingest-asset-closure.py" \
  "$OUT_DIR" \
  --primary-html index.html \
  --manifest assets-manifest.yaml \
  --report "$CLOSURE_REPORT" >/dev/null

python3 - "$OUT_DIR" "$DECK_ID" "$CLOSURE_REPORT" "$SCRIPT_DIR/shared" <<'PY'
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

out_dir = Path(sys.argv[1]).resolve()
deck_id = sys.argv[2].strip()
closure_report_path = Path(sys.argv[3]).resolve()
canonical_shared_root = Path(sys.argv[4]).resolve()

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
HTML_SUFFIXES = {".html", ".htm"}
META_REFRESH_RE = re.compile(
    r"""<meta\b[^>]*http-equiv\s*=\s*["']?refresh["']?[^>]*content\s*=\s*["'][^"']*?\burl\s*=\s*([^"';>]+)[^"']*["']""",
    re.I | re.S,
)
JS_LOCATION_RE = re.compile(
    r"""(?:window\.)?location(?:\.href)?\s*=\s*["']([^"']+)["']""",
    re.I,
)


def rel(path: Path) -> str:
    return path.relative_to(out_dir).as_posix()


def fail(message: str) -> None:
    sys.exit(f"ERROR: {message}")


def is_packaged_metadata(path: Path) -> bool:
    parts = path.relative_to(out_dir).parts
    return any(part.startswith(".") for part in parts)


def find_html_redirect_target(html: str) -> str:
    for pattern in (META_REFRESH_RE, JS_LOCATION_RE):
        match = pattern.search(html)
        if match:
            return match.group(1).strip().strip('"\'')
    return ""


def safe_local_html_redirect_target(raw_target: str) -> Path | None:
    if not raw_target or "\\" in raw_target:
        return None
    parsed = urlparse(raw_target)
    if parsed.scheme or parsed.netloc:
        return None
    path_text = unquote(parsed.path or raw_target).strip()
    if not path_text or path_text.startswith("/") or Path(path_text).is_absolute():
        return None
    parts = [part for part in path_text.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        return None
    target = out_dir.joinpath(*parts).resolve()
    try:
        target.relative_to(out_dir)
    except ValueError:
        return None
    if target.suffix.lower() not in HTML_SUFFIXES or not target.is_file():
        return None
    # Only same-directory promotion is safe without rewriting relative asset refs.
    if target.parent != out_dir:
        return None
    return target


def promoted_primary_html() -> Path | None:
    index = out_dir / "index.html"
    try:
        html = index.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        html = index.read_text(encoding="utf-8", errors="ignore")
    redirect = find_html_redirect_target(html)
    if not redirect:
        return None
    target = safe_local_html_redirect_target(redirect)
    if target is None:
        fail(f"index.html redirects to an unsafe or unsupported target: {redirect}")
    if target.name == "index.html":
        return None
    print(f"WARNING: index.html is a redirect shell; packaging {target.name} as root index.html", file=sys.stderr)
    return target


for path in out_dir.rglob("*"):
    r = rel(path)
    parts = path.relative_to(out_dir).parts
    if path.is_symlink():
        allowed_shared_link = (
            path == out_dir / "assets" / "shared"
            and canonical_shared_root.is_dir()
            and path.resolve() == canonical_shared_root
        )
        if not allowed_shared_link:
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
try:
    closure_report = json.loads(closure_report_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    fail(f"runtime asset closure report is missing or invalid: {exc}")
if closure_report.get("status") != "verified" or closure_report.get("issues"):
    fail("runtime asset closure report is not verified")
manifest["asset_closure"] = {
    "status": "verified",
    "reachable_file_count": int(closure_report.get("reachable_file_count") or 0),
    "manifest_file_count": int(closure_report.get("manifest_file_count") or 0),
    "total_bytes": int(closure_report.get("total_bytes") or 0),
    "digest_sha256": str(closure_report.get("digest_sha256") or ""),
}
manifest["package_scope"] = {
    "policy": "runtime-closure-plus-provenance-metadata-v1",
    "note": "Derived screenshots, logs, staging trees, and other transport archives are excluded.",
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

primary_override = promoted_primary_html()
zip_path = out_dir / "deck.zip"

stage = Path(tempfile.mkdtemp(prefix="feishu-deck-ingest-pkg."))
try:
    # Keep the ingest package deliberately narrow. Historically this loop copied
    # the entire output/ tree, so old delivery ZIPs, screenshots, logs and even
    # prior ingest artifacts were recursively embedded in deck.zip. The closure
    # report is the authoritative runtime set; add only the source/provenance
    # metadata that the library knows how to preserve.
    provenance_metadata = {
        "deck.json",
        "slide-index.json",
        "assets-manifest.yaml",
        "ingestion-manifest.json",
        "outline.json",
        "outline.md",
        "DESIGN-PLAN.md",
        "texts.md",
        "PROMPTS.md",
        "README.md",
    }
    included = set(str(item) for item in closure_report.get("reachable_files", []))
    included.update(name for name in provenance_metadata if (out_dir / name).is_file())

    for relative_text in sorted(included):
        relative = Path(relative_text)
        if (
            relative.is_absolute()
            or not relative.parts
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            fail(f"unsafe closure path: {relative_text}")
        logical_source = out_dir / relative
        source = logical_source.resolve()
        try:
            source.relative_to(out_dir)
        except ValueError:
            shared_link = out_dir / "assets" / "shared"
            allowed_shared_file = False
            try:
                allowed_shared_file = (
                    relative.parts[:2] == ("assets", "shared")
                    and shared_link.is_symlink()
                    and shared_link.resolve(strict=True) == canonical_shared_root
                    and source.relative_to(canonical_shared_root) is not None
                )
            except (OSError, ValueError):
                allowed_shared_file = False
            if not allowed_shared_file:
                fail(f"closure path escapes output: {relative_text}")
        if not source.is_file():
            fail(f"closure file disappeared before packaging: {relative_text}")
        if primary_override is not None and source == primary_override.resolve():
            continue
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    if primary_override is not None:
        shutil.copy2(primary_override, stage / "index.html")

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
            if "\\" in arcname:
                fail(f"internal error: refusing to write backslash path into deck.zip: {arcname}")
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
