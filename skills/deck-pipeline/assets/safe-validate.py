#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("usage: python3 safe-validate.py <html-path> [--strict] [--visual]", file=sys.stderr)
        return 1

    script_dir = Path(__file__).resolve().parent
    upstream = script_dir.parent.parent / "feishu-deck-h5" / "assets" / "validate.py"

    strict = False
    visual = False
    passthrough: list[str] = []
    for arg in args:
        if arg == "--strict":
            strict = True
        elif arg == "--visual":
            visual = True
        else:
            passthrough.append(arg)

    cmd = ["python3", str(upstream), *passthrough]
    if strict:
        cmd.append("--strict")
    if not visual:
        cmd.append("--no-visual")
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
