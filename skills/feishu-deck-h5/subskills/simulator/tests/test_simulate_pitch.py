"""Smoke tests for pitch-simulator CLI normalization and schema output."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
SIMULATOR = REPO / "subskills" / "simulator" / "simulate-pitch.py"
VALIDATOR = REPO / "subskills" / "simulator" / "validate-rehearsal.py"


class PitchSimulatorCliTest(unittest.TestCase):
    def test_chinese_meeting_type_alias_validates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pitch-sim-test-") as td:
            outline = Path(td) / "outline.json"
            out_json = Path(td) / "pitch-rehearsal.json"
            out_md = Path(td) / "PITCH_REHEARSAL.md"
            outline.write_text(
                json.dumps(
                    {
                        "brief": {
                            "title": "零售 AI Agent 试点提案",
                            "audience": "零售客户经营团队",
                            "objective": "推动 POC 启动",
                            "success_metric": "确认试点范围和负责人",
                        },
                        "outline": {
                            "arc": "从经营痛点进入,展示 AI Agent 方案,最后收束到 POC。",
                            "slides": [
                                {
                                    "key": "cover",
                                    "title": "零售 AI Agent 试点",
                                    "role": "cover",
                                    "message": "面向经营团队的试点提案",
                                },
                                {
                                    "key": "pain",
                                    "title": "一线经营响应慢",
                                    "role": "pain",
                                    "message": "门店问题从发现到处理缺少闭环",
                                    "evidence": ["需要客户确认当前响应时长"],
                                },
                                {
                                    "key": "solution",
                                    "title": "AI Agent 闭环方案",
                                    "role": "solution",
                                    "message": "用智能体串联发现、分派、跟进和复盘",
                                },
                                {
                                    "key": "next-step",
                                    "title": "POC 下一步",
                                    "role": "closing",
                                    "message": "两周确认试点门店、指标和接口清单",
                                },
                            ],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SIMULATOR),
                    "--outline",
                    str(outline),
                    "--out-json",
                    str(out_json),
                    "--out-md",
                    str(out_md),
                    "--meeting-type",
                    "POC 启动提案",
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            data = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(data["meeting"]["meeting_type"], "poc-kickoff")

            proc = subprocess.run(
                [sys.executable, str(VALIDATOR), str(out_json)],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_designer_scenario_shapes_rehearsal_context(self) -> None:
        with tempfile.TemporaryDirectory(prefix="pitch-sim-scenario-test-") as td:
            outline = Path(td) / "outline.json"
            scenario = Path(td) / "scenario.json"
            out_json = Path(td) / "pitch-rehearsal.json"
            outline.write_text(
                json.dumps(
                    {
                        "scenario": {
                            "goal": "推动客户确认 POC 启动",
                            "audience": "制造业客户 CFO、IT 和运营负责人",
                            "setting": "二次方案会,客户已看过初版 demo",
                            "decision": "是否同意两周 POC 范围和负责人",
                            "language": "zh-only",
                            "risk_level": "high",
                            "proof_requirements": ["ROI 口径", "系统集成边界"],
                        },
                        "design_plan": {
                            "title": "制造业智能运营 POC 提案",
                            "narrative_arc": "从运营损耗进入,展示最小闭环,收束到两周 POC。",
                        },
                        "slides": [
                            {
                                "key": "cover",
                                "title": "智能运营 POC",
                                "role": "cover",
                                "single_focus": "面向制造业运营团队的 POC 提案",
                            },
                            {
                                "key": "pain",
                                "title": "异常处理缺少闭环",
                                "role": "pain",
                                "single_focus": "一线异常从发现到复盘缺少责任闭环",
                            },
                            {
                                "key": "pilot-plan",
                                "title": "两周 POC 计划",
                                "role": "closing",
                                "single_focus": "确认场景、负责人、接口清单和复盘口径",
                            },
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            scenario.write_text(
                json.dumps(
                    {
                        "scenario": {
                            "goal": "推动客户确认续约前 POC",
                            "audience": "制造业客户 CFO 和 IT 负责人",
                            "setting": "续约前风险复盘会",
                            "decision": "是否同意续约前完成 POC 验证",
                            "risk_level": "high",
                            "proof_requirements": ["续约风险证据"],
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SIMULATOR),
                    "--outline",
                    str(outline),
                    "--out-json",
                    str(out_json),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            data = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(data["meeting"]["audience"], "制造业客户 CFO 和 IT 负责人")
            self.assertEqual(data["meeting"]["meeting_type"], "poc-kickoff")
            self.assertIn("续约前风险复盘会", data["meeting"]["known_context"])
            self.assertIn(str(scenario), data["source"]["artifacts"])
            self.assertTrue(
                any(
                    "是否同意续约前完成 POC 验证" in question
                    for reaction in data["slide_reactions"]
                    for question in reaction["likely_questions"]
                )
            )

            proc = subprocess.run(
                [sys.executable, str(VALIDATOR), str(out_json)],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)


if __name__ == "__main__":
    unittest.main()
