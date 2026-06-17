#!/usr/bin/env python3
"""feishu-deck-h5 · verify a run output/ is PORTABLE before it is zipped/sent.

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

Usage:
    python3 assets/verify-portable.py runs/<ts>/output [--quiet]

Exit codes: 0 portable / 2 bad args / 3 not portable (problems printed)
"""
from __future__ import annotations

import os
import re
import sys

_HREF_SRC = re.compile(r'(?:href|src)=(["\'])(.*?)\1', re.I)
_CSS_URL = re.compile(r'url\(\s*(["\']?)(.*?)\1\s*\)', re.I)
_REMOTE = re.compile(r'^(?:https?:|data:|#|mailto:|javascript:|//|tel:)', re.I)
_ASSET_EXT = re.compile(
    r'\.(?:css|js|png|jpe?g|mp4|webm|mov|svg|webp|gif|ico|woff2?|ttf|otf|json)$',
    re.I)
_SKILL_REL = "skills/feishu-deck-h5"


def _iter_refs(html_text: str):
    for m in _HREF_SRC.finditer(html_text):
        yield m.group(2)
    for m in _CSS_URL.finditer(html_text):
        yield m.group(2)


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
    args = [a for a in argv if not a.startswith("-")]
    quiet = "--quiet" in argv
    if len(args) != 1:
        print("usage: verify-portable.py <output-dir> [--quiet]", file=sys.stderr)
        return 2
    output_dir = args[0]
    if not os.path.isdir(output_dir):
        print(f"✗ not a directory: {output_dir}", file=sys.stderr)
        return 2

    problems = scan(output_dir)
    if not problems:
        if not quiet:
            print(f"✓ portable — {output_dir} is self-contained "
                  "(no skill-relative / escaping / missing refs, no symlinks)")
        return 0

    by_kind: dict[str, list[dict]] = {}
    for p in problems:
        by_kind.setdefault(p["kind"], []).append(p)
    print(f"✗ NOT portable — {len(problems)} problem(s) in {output_dir}:", file=sys.stderr)
    labels = {
        "symlink": "symlink member (breaks zip/ingest)",
        "skill-relative": "ref into skills/feishu-deck-h5/ (breaks off-machine)",
        "escapes": "ref escapes output/ (breaks once moved)",
        "missing": "ref points at a missing file",
        "unreadable": "unreadable HTML",
    }
    for kind, items in by_kind.items():
        print(f"  · {labels.get(kind, kind)} × {len(items)}", file=sys.stderr)
        for it in items[:12]:
            print(f"      {it['file']}: {it['ref']}", file=sys.stderr)
        if len(items) > 12:
            print(f"      … and {len(items) - 12} more", file=sys.stderr)
    print("", file=sys.stderr)
    print("  fix: run copy-assets to self-contain, then re-package —", file=sys.stderr)
    print("    python3 assets/copy-assets.py <output-dir> --shared=copy", file=sys.stderr)
    print("  or just use the orchestrated path: assets/finalize.sh <output-dir> remote",
          file=sys.stderr)
    return 3


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
