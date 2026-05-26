#!/usr/bin/env python3
from __future__ import annotations

import re
from pathlib import Path

BOOTSTRAP_WORKSPACE_RE = re.compile(r"workspace \(RW\)\s*:\s*(.+)")
OK_SKILL_ROOT_RE = re.compile(r"skill root:\s*(.+)")


def parse_preflight_output(text: str) -> dict:
    text = text.strip()
    if text.startswith("PREFLIGHT BOOTSTRAPPED"):
        match = BOOTSTRAP_WORKSPACE_RE.search(text)
        if not match:
            raise ValueError("Missing bootstrapped workspace path in preflight output")
        workspace_root = match.group(1).strip()
        return {
            "mode": "bootstrapped",
            "workspace_root": workspace_root,
            "skill_root": workspace_root,
        }
    if text.startswith("PREFLIGHT OK"):
        match = OK_SKILL_ROOT_RE.search(text)
        if not match:
            raise ValueError("Missing skill root path in preflight output")
        skill_root = match.group(1).strip()
        return {
            "mode": "ok",
            "workspace_root": skill_root,
            "skill_root": skill_root,
        }
    raise ValueError("Unsupported preflight result")


def validate_args(strict: bool = False, visual: bool = False) -> list[str]:
    args: list[str] = []
    if strict:
        args.append("--strict")
    if not visual:
        args.append("--no-visual")
    return args


def finalize_copy_assets_args(output_dir: str | Path) -> list[str]:
    return [str(output_dir), "--shared=copy"]


def historical_run_is_immutable() -> bool:
    return True
