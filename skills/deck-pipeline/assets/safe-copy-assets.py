#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("usage: python3 safe-copy-assets.py <output-dir>", file=sys.stderr)
        return 1

    script_dir = Path(__file__).resolve().parent
    guard = script_dir / "historical-run-guard.py"
    upstream = script_dir.parent.parent / "feishu-deck-h5" / "assets" / "copy-assets.py"
    guard_proc = subprocess.run(["python3", str(guard), args[0]])
    if guard_proc.returncode != 0:
        return guard_proc.returncode
    cmd = ["python3", str(upstream), *args, "--shared=copy"]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
