#!/usr/bin/env python3
"""bak-and-log.py — backup a file before a destructive edit AND log the
change to CHANGES.md in the same directory. Keeps only the 3 most recent
backups per (file, tag) pair so output dirs don't accumulate 50+ stale
.bak files.

Real-world motivation (2026-05-24): ai-consumer-growth deck had 53 .bak
files (~12 MB) accumulated over multi-day iteration. None had context;
filenames embedded a tag but not WHY. This script consolidates the bak
+ the log into one call, and caps retention.

Usage:
  python3 bak-and-log.py <file> <short-tag> "<description>"
  bash bak-and-log.sh <file> <short-tag> "<description>"  (same thing)

Example:
  bash bak-and-log.sh runs/<ts>/output/index.html iframe-fix \\
      "Remove obsolete iframe-embed override; fixes #6 title position"

Effects:
  1. Copies <file> → <file>.bak-pre-<short-tag>-<YYYYMMDD-HHMMSS>[.<N>]
     (suffix `.N` added if same-second collision)
  2. Prepends an entry to <file's dir>/CHANGES.md (newest at top, below
     the file's header block). Creates CHANGES.md if absent.
  3. Prunes .bak-pre-<short-tag>-* for <file>, keeping 3 most recent.
     Other tags' backups are untouched (tags scope the retention slot).

Conventions:
  - <short-tag> kebab-case, ≤ 24 chars (e.g. "iframe-fix", "p20-rewrite")
  - <description> one line, no markdown formatting expected
  - CHANGES.md is markdown — agents reading it for context get a clean
    timeline without grepping 50 filenames

Exit codes:
  0 — success
  1 — bad args (missing, wrong tag shape, etc.)
  2 — source file does not exist
  3 — copy / write failed
"""

import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

TAG_RE = re.compile(r'^[a-z][a-z0-9-]{0,23}$')


def fail(msg, code=1):
    print(f'ERROR: {msg}', file=sys.stderr)
    sys.exit(code)


def make_unique_bak_path(file: Path, tag: str, ts: str) -> Path:
    """Return a backup path that doesn't already exist. If the second-
    precision timestamp collides, append `.1`, `.2`, ... until free.
    """
    base = file.parent / f'{file.name}.bak-pre-{tag}-{ts}'
    if not base.exists():
        return base
    for n in range(1, 100):
        candidate = file.parent / f'{file.name}.bak-pre-{tag}-{ts}.{n}'
        if not candidate.exists():
            return candidate
    fail(f'too many collisions on {base.name}', 3)


def prepend_changes_md(changes: Path, entry_md: str, dir_label: str):
    """Insert entry_md after the file's header block (after first `---`
    separator). Creates the file with a standard header if absent.
    """
    header = (
        f'# CHANGES · {dir_label}\n\n'
        'Edit history for this output directory. Each entry is written\n'
        'by `bak-and-log.sh` (or `bak-and-log.py`) whenever a backup is\n'
        'taken before a destructive edit. Newest entries at the top.\n\n'
        '---\n\n'
    )
    if not changes.exists():
        body = header
    else:
        body = changes.read_text()
        if '---' not in body:
            # Existing CHANGES.md without our header layout — prepend our
            # header above the existing content.
            body = header + body

    # Insert entry_md immediately after the FIRST `---\n\n` line group.
    # If not found, insert right after the first `---`.
    sep = '---\n\n'
    if sep in body:
        idx = body.index(sep) + len(sep)
        new_body = body[:idx] + entry_md + body[idx:]
    else:
        new_body = body + '\n' + entry_md
    changes.write_text(new_body)


def prune_old_baks(file: Path, tag: str, keep: int = 3) -> int:
    """Delete .bak-pre-<tag>-* for `file`, keeping the `keep` newest by mtime."""
    pattern = f'{file.name}.bak-pre-{tag}-'
    candidates = [p for p in file.parent.iterdir() if p.name.startswith(pattern)]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    to_delete = candidates[keep:]
    for p in to_delete:
        p.unlink()
    return len(to_delete)


def main():
    if len(sys.argv) < 4:
        print(__doc__.split('Usage:')[1].split('\n\n')[0].strip(), file=sys.stderr)
        sys.exit(1)
    file_path = Path(sys.argv[1])
    tag = sys.argv[2]
    desc = sys.argv[3]

    if not file_path.is_file():
        fail(f'file not found: {file_path}', 2)
    if not TAG_RE.match(tag):
        fail(f'tag must be kebab-case ≤ 24 chars (got: {tag!r})', 1)
    if not desc.strip():
        fail('description cannot be empty', 1)

    now = datetime.now()
    ts = now.strftime('%Y%m%d-%H%M%S')
    human_ts = now.strftime('%Y-%m-%d %H:%M:%S')

    # 1. backup
    bak = make_unique_bak_path(file_path, tag, ts)
    try:
        shutil.copy2(file_path, bak)
    except Exception as e:
        fail(f'failed to copy {file_path} → {bak}: {e}', 3)

    # 2. log
    changes = file_path.parent / 'CHANGES.md'
    entry_md = (
        f'## {human_ts} · {tag}\n\n'
        f'{desc}\n\n'
        f'Backup: `{bak.name}`\n\n'
        f'---\n\n'
    )
    dir_label = os.path.relpath(file_path.parent)
    try:
        prepend_changes_md(changes, entry_md, dir_label)
    except Exception as e:
        fail(f'failed to write {changes}: {e}', 3)

    # 3. prune
    pruned = prune_old_baks(file_path, tag, keep=3)

    print(f'✓ backup: {bak.name}')
    print(f'✓ logged: {changes.name}')
    if pruned:
        print(f'✓ pruned: {pruned} older .bak-pre-{tag}-* (kept 3 most recent)')


if __name__ == '__main__':
    main()
