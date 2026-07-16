#!/usr/bin/env python3
"""Validate one install/runtime capability profile from dependency-policy.yaml."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "references" / "dependency-policy.yaml"


def load_policy() -> dict:
    data = json.loads(POLICY.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("profiles"), dict):
        raise ValueError(f"invalid dependency policy: {POLICY}")
    return data


def merged_profile(name: str, policy: dict, seen: set[str] | None = None) -> dict:
    seen = set() if seen is None else seen
    if name in seen:
        raise ValueError(f"dependency profile cycle: {name}")
    seen.add(name)
    try:
        own = dict(policy["profiles"][name])
    except KeyError as exc:
        raise ValueError(f"unknown dependency profile: {name}") from exc
    parent = own.pop("extends", None)
    merged = {"files": [], "commands": [], "python_modules": [], "siblings": [], "chromium_launch": False}
    if parent:
        merged.update(merged_profile(parent, policy, seen))
    for key in ("files", "commands", "python_modules", "siblings"):
        values = list(merged.get(key, [])) + list(own.get(key, []))
        deduped = []
        for value in values:
            marker = json.dumps(value, sort_keys=True) if isinstance(value, dict) else value
            if marker not in [json.dumps(v, sort_keys=True) if isinstance(v, dict) else v for v in deduped]:
                deduped.append(value)
        merged[key] = deduped
    merged["chromium_launch"] = bool(merged.get("chromium_launch") or own.get("chromium_launch"))
    return merged


def sibling_candidates(spec: dict) -> list[Path]:
    name = spec["name"]
    candidates: list[Path] = []
    root_env = str(spec.get("root_env") or "").strip()
    if root_env and os.environ.get(root_env):
        candidates.append(Path(os.environ[root_env]).expanduser())
    if os.environ.get("FS_DECK_SKILLS_DIR"):
        candidates.append(Path(os.environ["FS_DECK_SKILLS_DIR"]).expanduser() / name)
    candidates.append(ROOT.parent / name)
    if os.environ.get("CODEX_HOME"):
        candidates.append(Path(os.environ["CODEX_HOME"]).expanduser() / "skills" / name)
    candidates.extend(
        [
            Path.home() / ".codex" / "skills" / name,
            Path.home() / ".claude" / "skills" / name,
            Path.home() / ".agents" / "skills" / name,
        ]
    )
    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        marker = str(candidate.resolve(strict=False))
        if marker not in seen:
            seen.add(marker)
            deduped.append(candidate)
    return deduped


def sibling_python(root: Path, runtime: dict) -> tuple[Path | None, list[str]]:
    candidates: list[Path] = []
    env_name = str(runtime.get("env") or "").strip()
    if env_name and os.environ.get(env_name):
        candidates.append(Path(os.environ[env_name]).expanduser())
    candidates.extend(root / rel for rel in runtime.get("candidates", []))
    if runtime.get("allow_current"):
        candidates.append(Path(sys.executable))
    for command in runtime.get("commands", []):
        found = shutil.which(command)
        if found:
            candidates.append(Path(found))

    modules = list(runtime.get("modules", []))
    probe = "; ".join(f"import {module}" for module in modules)
    tried: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        marker = str(candidate.resolve(strict=False))
        if marker in seen:
            continue
        seen.add(marker)
        tried.append(str(candidate))
        if not candidate.is_file():
            continue
        try:
            proc = subprocess.run(
                [str(candidate), "-c", probe],
                text=True,
                capture_output=True,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode == 0:
            return candidate, tried
    return None, tried


def check(name: str) -> dict:
    policy = load_policy()
    profile = merged_profile(name, policy)
    errors: list[str] = []
    for rel in profile["files"]:
        if not (ROOT / rel).is_file():
            errors.append(f"missing file: {rel}")
    for command in profile["commands"]:
        if shutil.which(command) is None:
            errors.append(f"missing command: {command}")
    for module in profile["python_modules"]:
        if importlib.util.find_spec(module) is None:
            errors.append(f"missing python module: {module}")
    for sibling in profile["siblings"]:
        required = list(sibling.get("required_files", []))
        roots = sibling_candidates(sibling)
        complete_roots = [
            root for root in roots if all((root / rel).is_file() for rel in required)
        ]
        if not complete_roots:
            for rel in required:
                errors.append(f"missing sibling file: {sibling['name']}/{rel}")
            continue
        runtime = sibling.get("python_runtime")
        if runtime:
            all_tried: list[str] = []
            for sibling_root in complete_roots:
                interpreter, tried = sibling_python(sibling_root, runtime)
                all_tried.extend(tried)
                if interpreter is not None:
                    break
            else:
                modules = ", ".join(runtime.get("modules", []))
                errors.append(
                    f"missing sibling Python runtime: {sibling['name']} needs {modules}; "
                    f"tried {', '.join(dict.fromkeys(all_tried)) or 'no candidates'}"
                )
    if profile["chromium_launch"] and not errors:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                executable = Path(pw.chromium.executable_path)
                if not executable.is_file():
                    errors.append(f"missing Chromium executable: {executable}")
                else:
                    browser = pw.chromium.launch(headless=True)
                    browser.close()
        except Exception as exc:  # includes missing shared libraries and launch errors
            errors.append(f"Chromium launch failed: {exc}")
    return {"ok": not errors, "profile": name, "requirements": profile, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = check(args.profile)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = {"ok": False, "profile": args.profile, "errors": [str(exc)]}
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    elif not result["ok"]:
        for error in result["errors"]:
            print(error)
    return 0 if result["ok"] else 5


if __name__ == "__main__":
    sys.exit(main())
