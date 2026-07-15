from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def active_docs() -> list[Path]:
    return [ROOT / "SKILL.md", ROOT / "INSTALL-CLOUD.md"] + sorted(
        (ROOT / "references").glob("*.md")
    ) + sorted(ROOT.glob("subskills/*/SKILL.md"))


def test_machine_contracts_validate() -> None:
    contract = load_module("skill_contract", ROOT / "assets" / "skill-contract.py")
    result = contract.validate()
    assert result == {"ok": True, "modes": 15, "formats": 5, "gates": 10, "profiles": 7}
    packet = contract.route_packet("MAINTENANCE")
    assert "python3 -m pytest" in packet["gate_contract"]["command"]
    assert "unittest" not in packet["gate_contract"]["command"]
    recovery = contract.route_packet("PUBLISH_RECOVERY")
    assert recovery["gate_contract"]["requires_repository_release_gate"] is False
    assert "tests/test_publish_self_check.py" in recovery["gate_contract"]["command"]
    assert "deck-json/tests" not in recovery["gate_contract"]["command"]


def test_execution_policy_closes_passed_authoring_and_bounds_delivery() -> None:
    contract = load_module("skill_contract_execution", ROOT / "assets" / "skill-contract.py")
    policy = contract.load_contract("gate")["execution_policy"]
    authoring = policy["authoring"]
    delivery = policy["delivery"]

    assert authoring["pass_closes_authoring"] is True
    assert authoring["formal_fix_renders_max"] == 1
    assert {
        "advisory_only",
        "optional_polish",
        "packaging_runtime_failure",
    } <= set(authoring["do_not_reopen_on"])
    assert delivery["one_shape_per_request"] is True
    assert delivery["verify_only_selected_shape"] is True
    assert delivery["package_repro_attempts_max"] == 1
    assert delivery["package_failure_mode"] == "MAINTENANCE"
    assert delivery["publish_failure_mode"] == "PUBLISH_RECOVERY"
    assert delivery["preserve_last_good_authoring_artifact"] is True

    for mode in contract.load_contract("workflow")["modes"]:
        assert contract.route_packet(mode)["execution_policy"] == policy


def test_stop_policy_is_visible_in_controller_and_delivery_docs() -> None:
    controller = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    renderer = (ROOT / "subskills" / "renderer" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    delivery = (ROOT / "references" / "delivery.md").read_text(encoding="utf-8")
    quickstart = (ROOT / "references" / "raw-page-quickstart.md").read_text(
        encoding="utf-8"
    )

    assert "A formal PASS plus the required visual review closes authoring" in controller
    assert "Single-slide budget: one preview, at most one targeted correction" in controller
    assert "Choose one delivery shape" in controller
    assert "Loop: iterate with preview" not in renderer
    assert "Single-slide budget: run one preview" in renderer
    assert "One shape, one verification path, one stop" in delivery
    assert "`PUBLISH_RECOVERY` task" in delivery
    assert "publisher-focused tests plus one artifact" in delivery
    assert (
        "`python3 deck-json/render-deck.py <output>/deck.json <output> --inline`"
        in delivery
    )
    assert "PASS 关闭作者循环" in quickstart
    assert "交付形态只选一个" in quickstart


def test_finalize_inline_hint_uses_the_required_render_arguments() -> None:
    finalize = (ROOT / "assets" / "finalize.sh").read_text(encoding="utf-8")
    assert "render-deck.py <deck.json> <output-dir> --inline" in finalize
    assert "render-deck.py runs/<ts>/output --inline" not in finalize


def test_finalize_emits_a_terminal_receipt_without_linked_named_copy() -> None:
    finalize = (ROOT / "assets" / "finalize.sh").read_text(encoding="utf-8")
    assert 'cp "$HTML" "$NAMED_HTML"' not in finalize
    assert "local mode does not accept --name" in finalize
    assert "slide-library 入库门禁" not in finalize
    assert "FAIL_DOMAIN=page DO_NOT_EDIT_DECK=0" in finalize
    assert "FAIL_DOMAIN=delivery DO_NOT_EDIT_DECK=1" in finalize
    for shape in ("local", "remote", "library"):
        assert f"FINALIZE_RESULT status=pass shape={shape}" in finalize
    assert finalize.count("stop=true") == 3


def test_router_table_matches_workflow_manifest() -> None:
    workflow = json.loads((ROOT / "references" / "workflow.yaml").read_text(encoding="utf-8"))
    router = (ROOT / "references" / "request-router.md").read_text(encoding="utf-8")
    table_modes = set(re.findall(r"^\| `([^`]+)` \|", router, flags=re.MULTILINE))
    assert table_modes == set(workflow["modes"])
    contract = load_module("skill_contract_table", ROOT / "assets" / "skill-contract.py")
    generated = router.split("<!-- BEGIN GENERATED WORKFLOW TABLE -->", 1)[1].split(
        "<!-- END GENERATED WORKFLOW TABLE -->", 1
    )[0].strip()
    assert generated == contract.render_workflow_table()


def test_dependency_profiles_are_complete_and_checkable() -> None:
    checker = load_module("check_profile", ROOT / "assets" / "check-profile.py")
    policy = checker.load_policy()
    assert set(policy["profiles"]) == {
        "core", "generate", "edit", "pptx", "template", "publish", "import",
    }
    core_files = set(checker.merged_profile("core", policy)["files"])
    assert {"deck-json/render-deck.py", "deck-json/deck-cli.py", "deck-json/deck-schema.json"} <= core_files
    assert {"assets/audits.js", "assets/skill-contract.py"} <= core_files
    assert checker.check("core")["ok"]
    assert checker.check("template")["ok"]


def test_preflight_profiles_emit_machine_status() -> None:
    for profile in ("core", "template"):
        proc = subprocess.run(
            ["bash", str(ROOT / "assets" / "preflight.sh"), "--profile", profile, "--json"],
            cwd=REPO,
            text=True,
            capture_output=True,
        )
        assert proc.returncode == 0, proc.stderr or proc.stdout
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        assert payload == {
            "ok": True,
            "profile": profile,
            "result": "ok",
            "exit_code": 0,
        }


def test_active_docs_do_not_teach_retired_contracts() -> None:
    forbidden = {
        "raw renders no header": "raw header wording",
        "raw renders no `.header`": "raw header wording",
        "Direct JSON Edit": "unguarded DeckJSON writes",
        "$EDITOR runs/<ts>/output/deck.json": "unguarded DeckJSON writes",
        "render-deck.py runs/<ts>/output --inline": "invalid render signature",
        "10,11,12,13,14": "retired type ladder",
        "10, 11, 12, 13, 14": "retired type ladder",
    }
    offenders: list[str] = []
    for path in active_docs():
        text = path.read_text(encoding="utf-8")
        for needle, label in forbidden.items():
            if needle in text:
                offenders.append(f"{path.relative_to(ROOT)}: {label}: {needle}")
    assert not offenders, "\n".join(offenders)


def test_cloud_install_matches_runtime_contract() -> None:
    text = (ROOT / "INSTALL-CLOUD.md").read_text(encoding="utf-8")
    assert "Python 3.10 or newer" in text
    assert "visual-audit.js" not in text
    assert "dependency-policy.yaml" in text
    assert "--profile pptx" in text


def test_common_raw_edit_context_budget() -> None:
    packet = [
        ROOT / "SKILL.md",
        ROOT / "subskills" / "editor" / "SKILL.md",
        ROOT / "references" / "raw-page-quickstart.md",
    ]
    assert len((ROOT / "SKILL.md").read_text(encoding="utf-8").splitlines()) <= 300
    assert sum(path.stat().st_size for path in packet) <= 60_000


def test_render_cli_requires_deck_and_output_dir() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "deck-json" / "render-deck.py"), "--help"],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "deck output_dir" in proc.stdout
    assert "handoff/publish" not in proc.stdout
    assert "Magic Page publish" in proc.stdout


def test_install_script_never_deletes_existing_skill_path() -> None:
    text = (REPO / "install.sh").read_text(encoding="utf-8")
    assert 'rm -rf "$LINK_PATH"' not in text
    assert "--force --backup" in text


def test_preflight_discovers_repository_from_skill_subdirectory() -> None:
    text = (ROOT / "assets" / "preflight.sh").read_text(encoding="utf-8")
    assert 'git -C "$SKILL_ROOT" rev-parse --show-toplevel' in text
    assert '[ -d "$SKILL_ROOT/.git" ]' not in text
