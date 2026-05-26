#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from compat import parse_preflight_output


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    upstream = script_dir.parent.parent / "feishu-deck-h5" / "assets" / "preflight.sh"
    proc = subprocess.run(
        ["bash", str(upstream)],
        capture_output=True,
        text=True,
    )
    output = (proc.stdout or "") + (proc.stderr or "")
    if output:
        print(output, end="" if output.endswith("\n") else "\n")
    if proc.returncode != 0:
        return proc.returncode

    parsed = parse_preflight_output(output)
    print(
        f"COMPAT_PREFLIGHT mode={parsed['mode']} workspace_root={parsed['workspace_root']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
