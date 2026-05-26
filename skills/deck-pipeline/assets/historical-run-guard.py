#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

DEFAULT_BASELINE = Path(
    "/Users/bytedance/Desktop/tttt/deck-design/_shared/checks/deck-pipeline-safe-upgrade-baseline.json"
)
DECK_PIPELINE_ROOT = Path("/Users/bytedance/Desktop/tttt/deck-design/deck-pipeline")


def load_baseline() -> set[str]:
    if not DEFAULT_BASELINE.is_file():
        return set()
    data = json.loads(DEFAULT_BASELINE.read_text(encoding="utf-8"))
    return set(data.keys())


def dir_relative_to_deck_pipeline_root(output_dir: Path) -> str | None:
    try:
        return str(output_dir.resolve().relative_to(DECK_PIPELINE_ROOT))
    except ValueError:
        return None


def is_historical_output_dir(output_dir: Path, baseline_paths: set[str]) -> bool:
    rel_dir = dir_relative_to_deck_pipeline_root(output_dir)
    if not rel_dir:
        return False
    prefix = rel_dir.rstrip("/") + "/"
    return any(path.startswith(prefix) for path in baseline_paths)


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "usage: python3 historical-run-guard.py <output-dir>",
            file=sys.stderr,
        )
        return 1

    output_dir = Path(sys.argv[1]).resolve()
    baseline_paths = load_baseline()
    if not baseline_paths:
        print("IMMUTABILITY_GUARD baseline-missing allow")
        return 0

    if is_historical_output_dir(output_dir, baseline_paths):
        print(
            "IMMUTABILITY_GUARD historical-run-blocked",
            file=sys.stderr,
        )
        print(
            f"  blocked output dir: {output_dir}",
            file=sys.stderr,
        )
        print(
            "  reason: this directory belongs to the pre-upgrade historical run set.",
            file=sys.stderr,
        )
        print(
            "  action: copy this run to a new isolated run directory before mutate/finalize/inline.",
            file=sys.stderr,
        )
        return 2

    print("IMMUTABILITY_GUARD ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
