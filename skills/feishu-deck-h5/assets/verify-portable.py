#!/usr/bin/env python3
"""feishu-deck-h5 · verify a run output/ or delivery ZIP is portable.

A run output/ is "portable" when, after `copy-assets.py`, every asset an HTML
file references resolves to a real file *inside* output/, with no link back into
the skill folder and no symlink members (which break the slide-library ingest and
several IM/zip transports).

This is the correct, reusable version of an ad-hoc check agents kept re-deriving
in shell — where BSD `sed`/`tr` quote handling silently mangled paths. Do it once,
in Python, with a test.

Checks (over every *.html under output/):
  1. skill-relative refs   — `…/skills/feishu-deck-h5/…` leaked through.
  2. parent-escaping refs   — a relative ref that normalizes outside output/.
  3. missing local refs     — a local ref pointing at a file that isn't there.
  4. symlink members        — any symlink anywhere under output/ (asset trees).

JS-escaped-string noise (`src=\\"uuid\\"` inside inline scripts) and
non-file-shaped refs are ignored: only refs with a known asset extension count.

ZIP verification is archive-native: it does not extract or render the deck. It
checks archive integrity and member safety, requires root ``index.html``, checks
that local HTML/CSS references resolve to members, and can prove that the ZIP's
``index.html`` is byte-identical to the source selected by the packager.

Usage:
    python3 assets/verify-portable.py runs/<ts>/output [--quiet]
    python3 assets/verify-portable.py deck-editable.zip --source-html index.html

Exit codes: 0 portable / 2 bad args / 3 not portable (problems printed)
"""
from __future__ import annotations

import argparse
import hashlib
import os
import posixpath
import re
import stat
import sys
import zipfile

_HREF_SRC = re.compile(r'(?:href|src)=(["\'])(.*?)\1', re.I)
_CSS_URL = re.compile(r'url\(\s*(["\']?)(.*?)\1\s*\)', re.I)
_REMOTE = re.compile(r'^(?:https?:|data:|#|mailto:|javascript:|//|tel:)', re.I)
_ASSET_EXT = re.compile(
    r'\.(?:html?|css|js|png|jpe?g|mp4|webm|mov|svg|webp|gif|ico|woff2?|ttf|otf|json)$',
    re.I)
_SKILL_REL = "skills/feishu-deck-h5"
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[/\\]")


def _iter_refs(html_text: str):
    for m in _HREF_SRC.finditer(html_text):
        yield m.group(2)
    for m in _CSS_URL.finditer(html_text):
        yield m.group(2)


def _iter_css_refs(css_text: str):
    for m in _CSS_URL.finditer(css_text):
        yield m.group(2)


def _is_absolute_archive_path(path: str) -> bool:
    return path.startswith(("/", "\\")) or bool(_WINDOWS_ABSOLUTE.match(path))


def scan_zip(zip_path: str, source_html: str | None = None) -> list[dict]:
    """Return delivery-ZIP problems without extracting the archive."""
    problems: list[dict] = []
    try:
        with zipfile.ZipFile(zip_path) as archive:
            bad_member = archive.testzip()
            if bad_member:
                problems.append({
                    "kind": "zip-corrupt",
                    "file": bad_member,
                    "ref": "CRC check failed",
                })

            infos = archive.infolist()
            members = {info.filename for info in infos if not info.is_dir()}
            for info in infos:
                name = info.filename
                portable_name = name.replace("\\", "/")
                if _is_absolute_archive_path(name):
                    problems.append({"kind": "zip-absolute", "file": name, "ref": name})
                if ".." in portable_name.split("/"):
                    problems.append({"kind": "zip-traversal", "file": name, "ref": name})
                mode = (info.external_attr >> 16) & 0o170000
                if mode == stat.S_IFLNK:
                    problems.append({"kind": "zip-symlink", "file": name, "ref": name})

            if "index.html" not in members:
                problems.append({
                    "kind": "zip-missing-index",
                    "file": "index.html",
                    "ref": "required root member is absent",
                })

            for info in infos:
                name = info.filename
                if info.is_dir() or not name.lower().endswith((".html", ".htm", ".css")):
                    continue
                try:
                    text = archive.read(info).decode("utf-8", errors="ignore")
                except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                    problems.append({"kind": "zip-unreadable", "file": name, "ref": str(exc)})
                    continue
                refs = _iter_css_refs(text) if name.lower().endswith(".css") else _iter_refs(text)
                seen: set[str] = set()
                for raw in refs:
                    if not raw or raw in seen:
                        continue
                    seen.add(raw)
                    if _REMOTE.match(raw):
                        continue
                    if _is_absolute_archive_path(raw):
                        problems.append({"kind": "zip-absolute-ref", "file": name, "ref": raw})
                        continue
                    if "\\" in raw or '"' in raw:
                        continue
                    ref = raw.split("#")[0].split("?")[0]
                    if not ref or not _ASSET_EXT.search(ref):
                        continue
                    if _SKILL_REL in ref:
                        problems.append({"kind": "skill-relative", "file": name, "ref": raw})
                        continue
                    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), ref))
                    if resolved == ".." or resolved.startswith("../"):
                        problems.append({"kind": "escapes", "file": name, "ref": raw})
                    elif resolved not in members:
                        problems.append({"kind": "zip-missing", "file": name, "ref": raw})

            if source_html is not None and "index.html" in members:
                try:
                    source_bytes = open(source_html, "rb").read()
                    archived_bytes = archive.read("index.html")
                except (OSError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
                    problems.append({
                        "kind": "index-unreadable",
                        "file": "index.html",
                        "ref": str(exc),
                    })
                else:
                    source_sha = hashlib.sha256(source_bytes).hexdigest()
                    archived_sha = hashlib.sha256(archived_bytes).hexdigest()
                    if source_sha != archived_sha:
                        problems.append({
                            "kind": "index-mismatch",
                            "file": "index.html",
                            "ref": f"source={source_sha} archive={archived_sha}",
                        })
    except (OSError, zipfile.BadZipFile) as exc:
        problems.append({
            "kind": "zip-unreadable",
            "file": os.path.basename(zip_path),
            "ref": str(exc),
        })
    return problems


def scan(output_dir: str) -> list[dict]:
    """Return a list of problem dicts. Empty list == portable."""
    output_dir = os.path.abspath(output_dir)
    problems: list[dict] = []

    # 4 · symlink members anywhere under output/
    for root, dirs, files in os.walk(output_dir):
        for name in list(dirs) + files:
            p = os.path.join(root, name)
            if os.path.islink(p):
                problems.append({
                    "kind": "symlink",
                    "file": os.path.relpath(p, output_dir),
                    "ref": os.readlink(p),
                })

    # 1–3 · per-HTML reference checks
    for root, _dirs, files in os.walk(output_dir):
        for name in files:
            if not name.lower().endswith(".html"):
                continue
            html_path = os.path.join(root, name)
            rel_html = os.path.relpath(html_path, output_dir)
            base = os.path.dirname(html_path)
            try:
                txt = open(html_path, encoding="utf-8", errors="ignore").read()
            except OSError as e:                       # pragma: no cover
                problems.append({"kind": "unreadable", "file": rel_html, "ref": str(e)})
                continue
            seen: set[str] = set()
            for raw in _iter_refs(txt):
                if not raw or raw in seen:
                    continue
                seen.add(raw)
                if _REMOTE.match(raw):
                    continue
                # JS escaped-string noise inside inline <script> / attributes
                if "\\" in raw or '"' in raw:
                    continue
                ref = raw.split("#")[0].split("?")[0]
                if not ref or not _ASSET_EXT.search(ref):
                    continue
                if _SKILL_REL in ref:
                    problems.append({"kind": "skill-relative", "file": rel_html, "ref": raw})
                    continue
                full = os.path.normpath(os.path.join(base, ref))
                if not (full + os.sep).startswith(output_dir + os.sep) and full != output_dir:
                    problems.append({"kind": "escapes", "file": rel_html, "ref": raw})
                elif not os.path.exists(full):
                    problems.append({"kind": "missing", "file": rel_html, "ref": raw})
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="output directory or delivery ZIP")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--source-html", help="expected source for ZIP index.html")
    args = parser.parse_args(argv)

    if os.path.isdir(args.target):
        if args.source_html:
            print("✗ --source-html is only valid for a ZIP target", file=sys.stderr)
            return 2
        problems = scan(args.target)
        target_kind = "directory"
    elif os.path.isfile(args.target) and zipfile.is_zipfile(args.target):
        if args.source_html and not os.path.isfile(args.source_html):
            print(f"✗ source HTML not found: {args.source_html}", file=sys.stderr)
            return 2
        problems = scan_zip(args.target, args.source_html)
        target_kind = "archive"
    else:
        print(f"✗ not an output directory or ZIP: {args.target}", file=sys.stderr)
        return 2

    if not problems:
        if not args.quiet:
            print(f"✓ portable {target_kind} — {args.target}")
        return 0

    by_kind: dict[str, list[dict]] = {}
    for p in problems:
        by_kind.setdefault(p["kind"], []).append(p)
    print(f"✗ NOT portable — {len(problems)} problem(s) in {args.target}:", file=sys.stderr)
    labels = {
        "symlink": "symlink member (breaks zip/ingest)",
        "skill-relative": "ref into skills/feishu-deck-h5/ (breaks off-machine)",
        "escapes": "ref escapes output/ (breaks once moved)",
        "missing": "ref points at a missing file",
        "unreadable": "unreadable HTML",
        "zip-corrupt": "ZIP member failed CRC",
        "zip-absolute": "absolute archive member",
        "zip-traversal": "archive member contains '..'",
        "zip-symlink": "symlink archive member",
        "zip-missing-index": "required root index.html is missing",
        "zip-unreadable": "unreadable ZIP member/archive",
        "zip-absolute-ref": "absolute local reference in archive HTML/CSS",
        "zip-missing": "local reference is missing from archive",
        "index-unreadable": "could not compare source and archived index.html",
        "index-mismatch": "archived index.html differs from source HTML",
    }
    for kind, items in by_kind.items():
        print(f"  · {labels.get(kind, kind)} × {len(items)}", file=sys.stderr)
        for it in items[:12]:
            print(f"      {it['file']}: {it['ref']}", file=sys.stderr)
        if len(items) > 12:
            print(f"      … and {len(items) - 12} more", file=sys.stderr)
    print("", file=sys.stderr)
    if target_kind == "directory":
        print("  fix: run copy-assets to self-contain, then re-package —", file=sys.stderr)
        print("    python3 assets/copy-assets.py <output-dir> --shared=copy", file=sys.stderr)
        print("  or just use the orchestrated path: assets/finalize.sh <output-dir> remote",
              file=sys.stderr)
    else:
        print("  fix the delivery/package layer and rebuild the ZIP; do not edit deck content.",
              file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
