#!/usr/bin/env python3
"""Read and validate the machine-owned workflow/conversion/gate contracts.

The ``*.yaml`` files intentionally contain JSON, a YAML 1.2 subset, so this
tool has no PyYAML dependency and behaves identically in lean installations.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
REFS = ROOT / "references"
CONTRACTS = {
    "workflow": REFS / "workflow.yaml",
    "conversion": REFS / "conversion-policy.yaml",
    "gate": REFS / "gate-policy.yaml",
    "dependency": REFS / "dependency-policy.yaml",
}


class ContractError(ValueError):
    pass


def load_contract(name: str) -> dict:
    path = CONTRACTS[name]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"{path}: {exc}") from exc
    if data.get("schema_version") != 1:
        raise ContractError(f"{path}: unsupported schema_version")
    return data


def validate() -> dict:
    workflow = load_contract("workflow")
    conversion = load_contract("conversion")
    gates = load_contract("gate")
    dependencies = load_contract("dependency")
    modes = workflow.get("modes")
    gate_map = gates.get("gates")
    if not isinstance(modes, dict) or not modes:
        raise ContractError("workflow.yaml: modes must be a non-empty object")
    if not isinstance(gate_map, dict) or not gate_map:
        raise ContractError("gate-policy.yaml: gates must be a non-empty object")
    for mode, spec in modes.items():
        if mode != mode.upper():
            raise ContractError(f"workflow.yaml: mode must be uppercase: {mode}")
        for field in ("family", "owner", "trigger", "gate"):
            if not spec.get(field):
                raise ContractError(f"workflow.yaml: {mode}.{field} is required")
        if spec["gate"] not in gate_map:
            raise ContractError(f"workflow.yaml: {mode} references unknown gate {spec['gate']}")
        references = spec.get("references")
        if not isinstance(references, list):
            raise ContractError(f"workflow.yaml: {mode}.references must be a list")
        for rel in references:
            if not (ROOT / rel).is_file():
                raise ContractError(f"workflow.yaml: {mode} references missing file {rel}")
    execution = gates.get("execution_policy")
    if not isinstance(execution, dict):
        raise ContractError("gate-policy.yaml: execution_policy must be an object")
    authoring = execution.get("authoring")
    delivery = execution.get("delivery")
    if not isinstance(authoring, dict) or not isinstance(delivery, dict):
        raise ContractError(
            "gate-policy.yaml: execution_policy.authoring and .delivery are required"
        )
    if authoring.get("pass_closes_authoring") is not True:
        raise ContractError(
            "gate-policy.yaml: authoring.pass_closes_authoring must be true"
        )
    fix_renders = authoring.get("formal_fix_renders_max")
    if not isinstance(fix_renders, int) or isinstance(fix_renders, bool) or fix_renders < 0:
        raise ContractError(
            "gate-policy.yaml: authoring.formal_fix_renders_max must be a non-negative integer"
        )
    reopen_on = authoring.get("reopen_on")
    do_not_reopen_on = authoring.get("do_not_reopen_on")
    if not isinstance(reopen_on, list) or not reopen_on:
        raise ContractError("gate-policy.yaml: authoring.reopen_on must be a non-empty list")
    if not isinstance(do_not_reopen_on, list) or not do_not_reopen_on:
        raise ContractError(
            "gate-policy.yaml: authoring.do_not_reopen_on must be a non-empty list"
        )
    overlap = set(reopen_on) & set(do_not_reopen_on)
    if overlap:
        raise ContractError(
            f"gate-policy.yaml: authoring reopen policies overlap: {sorted(overlap)}"
        )
    for flag in (
        "one_shape_per_request",
        "verify_only_selected_shape",
        "preserve_last_good_authoring_artifact",
    ):
        if delivery.get(flag) is not True:
            raise ContractError(f"gate-policy.yaml: delivery.{flag} must be true")
    repros = delivery.get("package_repro_attempts_max")
    if not isinstance(repros, int) or isinstance(repros, bool) or repros < 0:
        raise ContractError(
            "gate-policy.yaml: delivery.package_repro_attempts_max must be a non-negative integer"
        )
    failure_mode = delivery.get("package_failure_mode")
    if failure_mode not in modes:
        raise ContractError(
            f"gate-policy.yaml: delivery.package_failure_mode references unknown mode {failure_mode}"
        )
    publish_failure_mode = delivery.get("publish_failure_mode")
    if publish_failure_mode not in modes:
        raise ContractError(
            "gate-policy.yaml: delivery.publish_failure_mode must reference a known mode"
        )
    if publish_failure_mode != "PUBLISH_RECOVERY":
        raise ContractError(
            "gate-policy.yaml: delivery.publish_failure_mode must be PUBLISH_RECOVERY; "
            "Magic delivery failures must not enter the repository-wide MAINTENANCE gate"
        )
    recovery_mode = modes.get(publish_failure_mode) or {}
    if recovery_mode.get("family") != "DELIVERY_RECOVERY":
        raise ContractError("workflow.yaml: PUBLISH_RECOVERY must use DELIVERY_RECOVERY family")
    recovery_gate = gate_map.get(recovery_mode.get("gate")) or {}
    if recovery_gate.get("requires_repository_release_gate") is not False:
        raise ContractError(
            "gate-policy.yaml: PUBLISH_RECOVERY.requires_repository_release_gate must be false"
        )
    recovery_command = str(recovery_gate.get("command") or "")
    if "tests/test_publish_self_check.py" not in recovery_command or "deck-json/tests" in recovery_command:
        raise ContractError(
            "gate-policy.yaml: PUBLISH_RECOVERY must use focused publisher tests, not the full repository suite"
        )
    budget = recovery_gate.get("delivery_time_budget_seconds")
    if not isinstance(budget, int) or isinstance(budget, bool) or not 30 <= budget <= 600:
        raise ContractError(
            "gate-policy.yaml: PUBLISH_RECOVERY.delivery_time_budget_seconds must be 30..600"
        )
    formats = conversion.get("formats")
    if not isinstance(formats, dict) or not formats:
        raise ContractError("conversion-policy.yaml: formats must be a non-empty object")
    for suffix, intents in formats.items():
        if not suffix.startswith(".") or not isinstance(intents, dict):
            raise ContractError(f"conversion-policy.yaml: invalid format {suffix}")
        for intent, spec in intents.items():
            route = spec.get("route")
            if not isinstance(route, list) or not route:
                raise ContractError(f"conversion-policy.yaml: {suffix}.{intent}.route is required")
            unknown = [mode for mode in route if mode not in modes]
            if unknown:
                raise ContractError(
                    f"conversion-policy.yaml: {suffix}.{intent} references unknown modes {unknown}"
                )
    profiles = dependencies.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ContractError("dependency-policy.yaml: profiles must be a non-empty object")
    for name, spec in profiles.items():
        parent = spec.get("extends")
        if parent and parent not in profiles:
            raise ContractError(f"dependency-policy.yaml: {name} extends unknown profile {parent}")
    return {
        "ok": True,
        "modes": len(modes),
        "formats": len(formats),
        "gates": len(gate_map),
        "profiles": len(profiles),
    }


def route_packet(mode: str) -> dict:
    workflow = load_contract("workflow")
    gates = load_contract("gate")
    key = mode.upper()
    try:
        spec = workflow["modes"][key]
    except KeyError as exc:
        raise ContractError(f"unknown mode: {mode}") from exc
    return {
        "mode": key,
        **spec,
        "gate_contract": gates["gates"][spec["gate"]],
        "execution_policy": gates["execution_policy"],
    }


def render_workflow_table() -> str:
    modes = load_contract("workflow")["modes"]
    lines = [
        "| Mode | Trigger | Owner | Gate |",
        "| --- | --- | --- | --- |",
    ]
    for mode, spec in modes.items():
        lines.append(
            f"| `{mode}` | {spec['trigger']} | `{spec['owner']}` | `{spec['gate']}` |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("render-workflow-table")
    route = sub.add_parser("route")
    route.add_argument("mode")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            payload = validate()
        elif args.command == "render-workflow-table":
            print(render_workflow_table())
            return 0
        else:
            payload = route_packet(args.mode)
    except ContractError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
