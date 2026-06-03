"""Contract tests for upload-parser handoff artifacts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
PARSER = REPO / "subskills" / "parser" / "parse.py"
VALIDATOR = REPO / "schema" / "validate-contract.py"
SCHEMA = REPO / "schema" / "source-dossier.schema.json"
SAMPLE_HTML = REPO / "examples" / "sample-deck.html"


class UploadParserContractTest(unittest.TestCase):
    def test_html_dossier_validates_and_preserves_dependencies(self) -> None:
        with tempfile.TemporaryDirectory(prefix="upload-parser-html-") as td:
            out = Path(td)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(PARSER),
                    str(SAMPLE_HTML),
                    "--brief",
                    "基于旧 HTML deck 生成新提案",
                    "--output-dir",
                    str(out),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            dossier_path = out / "source-dossier.json"
            self.assertFalse((out / "SOURCE_DOSSIER.md").exists())
            proc = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--schema",
                    str(SCHEMA),
                    "--instance",
                    str(dossier_path),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(dossier["knowledge_layer"]), 1)
            self.assertGreaterEqual(len(dossier["slide_layer"]), 1)
            html_assets = dossier["source_inventory"][0]["html_assets"]
            self.assertIn("../assets/feishu-deck.js", html_assets["scripts"])
            materialized = dossier["source_inventory"][0]["html_assets_materialized"]
            self.assertTrue(Path(materialized["scripts"][0]).is_file())
            self.assertTrue(Path(materialized["stylesheets"][0]).is_file())
            material_paths = {item["path"] for item in dossier["material_layer"]}
            self.assertTrue(any(path.endswith("feishu-deck.js") and Path(path).is_file() for path in material_paths))
            self.assertTrue(any(path.endswith("feishu-deck.css") and Path(path).is_file() for path in material_paths))

    def test_target_html_is_marked_for_editor_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory(prefix="upload-parser-target-html-") as td:
            out = Path(td)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(PARSER),
                    str(SAMPLE_HTML),
                    "--brief",
                    "请在这个 HTML 基础上修改第 2 页文案",
                    "--html-role",
                    "target-html",
                    "--output-dir",
                    str(out),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            dossier_path = out / "source-dossier.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--schema",
                    str(SCHEMA),
                    "--instance",
                    str(dossier_path),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
            source = dossier["source_inventory"][0]
            self.assertEqual(source["source_role"], "target-html")
            self.assertEqual(source["html_import_mode"], "imported_existing_state")
            self.assertIn("editor_bootstrap", source)
            self.assertIn("deck_editor", dossier["handoff"])
            self.assertTrue(dossier["handoff"]["deck_editor"]["ready"])
            self.assertFalse(dossier["handoff"]["deck_designer"]["ready"])

    def test_audio_source_is_registered_as_material(self) -> None:
        with tempfile.TemporaryDirectory(prefix="upload-parser-audio-") as td:
            root = Path(td)
            source = root / "customer-interview.m4a"
            source.write_bytes(b"fake-audio")
            out = root / "out"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(PARSER),
                    str(source),
                    "--brief",
                    "基于客户访谈录音生成提案",
                    "--output-dir",
                    str(out),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            dossier_path = out / "source-dossier.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--schema",
                    str(SCHEMA),
                    "--instance",
                    str(dossier_path),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
            self.assertEqual(dossier["source_inventory"][0]["material_kind"], "audio")
            audio_material = next(item for item in dossier["material_layer"] if item["type"] == "audio")
            self.assertIn("customer-interview", audio_material["path"])
            self.assertTrue(audio_material["path"].endswith(".m4a"))

    def test_markdown_explicit_single_image_page_is_preserved_as_image_page(self) -> None:
        with tempfile.TemporaryDirectory(prefix="upload-parser-image-policy-") as td:
            root = Path(td)
            source = root / "source.md"
            source.write_text(
                """# 联华 AI 应用规划

第5页 无需标题，直接插入图片

> 单独放一页

![AI 场景成熟度分层](ppt-page.png)
""",
                encoding="utf-8",
            )
            out = root / "out"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(PARSER),
                    str(source),
                    "--brief",
                    "基于飞书文档生成联华 AI 应用规划",
                    "--output-dir",
                    str(out),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            dossier_path = out / "source-dossier.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--schema",
                    str(SCHEMA),
                    "--instance",
                    str(dossier_path),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
            material = next(item for item in dossier["material_layer"] if item["path"] == "ppt-page.png")
            self.assertEqual(material["render_decision"]["render_mode"], "direct_image_page")
            self.assertFalse(any(item["slide_key"].startswith("image-page-") for item in dossier["slide_layer"]))
            image_page = next(item for item in dossier["slide_layer"] if item.get("page") == 5)
            self.assertEqual(image_page["layout_hint"], "direct-image-page")
            self.assertEqual(image_page["reconstruction_hint"]["source_image"], "ppt-page.png")
            self.assertEqual(image_page["reconstruction_hint"]["detail_preservation"], "preserve-image-page")
            self.assertEqual(image_page["reconstruction_hint"]["image_page_behavior"], "standalone-no-title")
            self.assertFalse(
                any("ppt-page.png" in item for item in dossier["confidence"]["needs_confirmation"]),
                dossier["confidence"]["needs_confirmation"],
            )

    def test_lark_file_media_uses_media_preview_without_download(self) -> None:
        with tempfile.TemporaryDirectory(prefix="upload-parser-media-preview-") as td:
            root = Path(td)
            source = root / "source.md"
            token = "AbCdEf123456"
            source.write_text(
                f"""# 联华 AI 应用规划

#### 第3页 业务域需求

> 直接插入图片

![业务域需求](https://feishu.cn/file/{token})
""",
                encoding="utf-8",
            )
            calls = root / "calls.txt"
            bin_dir = root / "bin"
            bin_dir.mkdir()
            fake_lark_cli = bin_dir / "lark-cli"
            fake_lark_cli.write_text(
                f"""#!/usr/bin/env python3
from pathlib import Path
import sys

calls = Path({json.dumps(str(calls))})
calls.write_text(calls.read_text() + " ".join(sys.argv[1:]) + "\\n" if calls.exists() else " ".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if args[:2] == ["docs", "+media-preview"]:
    out = Path(args[args.index("--output") + 1])
    out.write_bytes(bytes.fromhex("89504e470d0a1a0a0000000d494844520000000100000001"))
    sys.exit(0)
if args[:2] == ["docs", "+media-download"]:
    sys.exit(88)
sys.exit(64)
""",
                encoding="utf-8",
            )
            fake_lark_cli.chmod(0o755)
            out = root / "out"
            env = {
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
                "LARK_DOC_AS": "bot",
                "LARK_MEDIA_AS": "bot",
            }
            proc = subprocess.run(
                [
                    sys.executable,
                    str(PARSER),
                    str(source),
                    "--brief",
                    "基于飞书文档生成联华 AI 应用规划",
                    "--output-dir",
                    str(out),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            call_log = calls.read_text(encoding="utf-8")
            self.assertIn("docs +media-preview", call_log)
            self.assertIn("--as user", call_log)
            self.assertNotIn("--as bot", call_log)
            self.assertNotIn("+media-download", call_log)
            dossier = json.loads((out / "source-dossier.json").read_text(encoding="utf-8"))
            material = dossier["material_layer"][0]
            self.assertTrue(material["path"].endswith(f"assets/source-media/feishu-file-{token[:12]}.png"))
            self.assertEqual(material["render_decision"]["source_url"], f"https://feishu.cn/file/{token}")
            self.assertEqual(material["render_decision"]["media_preview"]["method"], "media-preview")
            self.assertEqual(material["render_decision"]["media_preview"]["identity"], "user")
            image_page = next(item for item in dossier["slide_layer"] if item.get("layout_hint") == "direct-image-page")
            self.assertEqual(image_page["reconstruction_hint"]["source_image"], material["path"])
            self.assertEqual(image_page["reconstruction_hint"]["source_image_url"], f"https://feishu.cn/file/{token}")

    def test_markdown_complex_page_image_without_direct_insert_is_marked_for_html_reconstruction(self) -> None:
        with tempfile.TemporaryDirectory(prefix="upload-parser-reconstruct-image-") as td:
            root = Path(td)
            source = root / "source.md"
            source.write_text(
                """# 联华 AI 应用规划

第5页 AI 场景成熟度分层

![AI 场景成熟度分层](ppt-page.png)
""",
                encoding="utf-8",
            )
            out = root / "out"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(PARSER),
                    str(source),
                    "--brief",
                    "基于飞书文档生成联华 AI 应用规划",
                    "--output-dir",
                    str(out),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            dossier_path = out / "source-dossier.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--schema",
                    str(SCHEMA),
                    "--instance",
                    str(dossier_path),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
            material = next(item for item in dossier["material_layer"] if item["path"] == "ppt-page.png")
            self.assertEqual(material["render_decision"]["render_mode"], "reconstruct_html")
            self.assertTrue(any(item.get("layout_hint") == "reconstruct-html" for item in dossier["slide_layer"]))
            self.assertTrue(
                any("ppt-page.png" in item for item in dossier["confidence"]["needs_confirmation"]),
                dossier["confidence"]["needs_confirmation"],
            )

    def test_markdown_page_table_details_are_preserved_for_planning(self) -> None:
        with tempfile.TemporaryDirectory(prefix="upload-parser-page-table-") as td:
            root = Path(td)
            source = root / "lianhua.md"
            source.write_text(
                """# 联华超市2026年AI应用规划

#### 第1页｜零售行业 AI 正从“工具提效”走向“经营闭环”

| 核心经营环节 | 线下化 | 数字化 | 智能化 |
|-|-|-|-|
| 商品经营 | 经验选品、人工定价 | 销售库存毛利线上化 | AI 辅助选品、定价、促销与汰换 |
| 生鲜经营 | 经验订货、损耗事后统计 | 订收存损流程可追踪 | AI 预测销量、动态订货与出清 |
| 供应商管理 | 资质合同线下流转 | 资料合同履约线上沉淀 | AI 审核、风险识别、进出评估 |
| 门店运营 | 人工巡检、整改靠追踪 | 巡检整改任务在线闭环 | AI 识别异常、生成整改建议 |
| 员工赋能 | 师傅带教、制度靠人问 | 制度流程培训在线查询 | AI 助手实时问答、岗位指引 |
| 顾客与会员经营 | 人工策划活动、触达粗放 | 会员活动客诉数据线上沉淀 | AI 分群、活动推荐、服务优化 |
| 经营复盘 | 人工拉数、事后复盘 | 驾驶舱报表多维分析 | AI 异常识别、归因分析、行动建议 |

#### 第2页｜从行业对标看联华 AI 数智化转型方向

**基础：数字化底座已基本构建**
""",
                encoding="utf-8",
            )
            out = root / "out"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(PARSER),
                    str(source),
                    "--brief",
                    "基于飞书文档生成联华 AI 应用规划",
                    "--output-dir",
                    str(out),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            dossier_path = out / "source-dossier.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--schema",
                    str(SCHEMA),
                    "--instance",
                    str(dossier_path),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
            inventory_slides = dossier["source_inventory"][0]["slides"]
            self.assertEqual(len(inventory_slides), 2)
            self.assertEqual(inventory_slides[0]["layout"], "markdown-table-detail")
            self.assertEqual(inventory_slides[0]["detail_fidelity"], "preserve-table")
            self.assertGreaterEqual(inventory_slides[0]["table_count"], 1)
            first_planning_slide = dossier["slide_layer"][0]
            self.assertEqual(first_planning_slide["layout_hint"], "markdown-table-detail")
            self.assertEqual(first_planning_slide["reconstruction_hint"]["detail_preservation"], "preserve-table")
            first_knowledge = next(item for item in dossier["knowledge_layer"] if "第1页" in item["title"])
            self.assertIn("AI 异常识别、归因分析、行动建议", first_knowledge["content"])

    def test_markdown_page_visual_instructions_are_preserved_for_planning(self) -> None:
        with tempfile.TemporaryDirectory(prefix="upload-parser-visual-directive-") as td:
            root = Path(td)
            source = root / "lianhua.md"
            source.write_text(
                """# 联华超市2026年AI应用规划

#### 第4页 联华AI场景分层，从需求清单到建设路径

【左侧页面】

先按 L1-L4 分层，形成“先打底座、再沉淀流程、再引入 AI、最后闭环经营”的建设路径。

> 视觉建议：用倒漏斗或阶梯形式呈现。L1 是最底层基础，L4 是最上层经营结果；每一层旁边只放一句管理含义，避免堆文字。

| 层级 | 分层定位 |
|-|-|
| L1 基础底座完善 | 让 AI 有入口、有知识、有运营组织 |
| L2 流程线上升级 | 把线下执行动作搬到线上，形成任务和留痕 |

【右侧页面】

| 层级 | 业务需求本质 | 建设重点 | 代表场景 |
|-|-|-|-|
| L1 基础底座 | 员工需要统一入口，AI 需要知识来源，组织需要推广载体 | 建知识、建入口、建运营机制 | 知识库、AI 训练营、门店圈、工作台统一入口、数据服务 |
| L2 流程线上 | 门店管理事项多、频次高、依赖纸质和人工督办 | 建任务清单、表单、标准、整改闭环、看板 | 门店巡检、资产报修、客诉处理、营销执行检查 |
""",
                encoding="utf-8",
            )
            out = root / "out"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(PARSER),
                    str(source),
                    "--brief",
                    "基于飞书文档生成联华 AI 应用规划",
                    "--output-dir",
                    str(out),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            dossier_path = out / "source-dossier.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--schema",
                    str(SCHEMA),
                    "--instance",
                    str(dossier_path),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
            inventory_slide = dossier["source_inventory"][0]["slides"][0]
            self.assertEqual(inventory_slide["layout"], "source-directed-layout")
            self.assertEqual(inventory_slide["detail_fidelity"], "preserve-layout")
            self.assertIn("左侧页面", inventory_slide["section_markers"])
            first_planning_slide = dossier["slide_layer"][0]
            self.assertEqual(first_planning_slide["layout_hint"], "source-directed-layout")
            hint = first_planning_slide["reconstruction_hint"]
            self.assertEqual(hint["detail_preservation"], "preserve-layout")
            self.assertEqual(hint["table_detail_preservation"], "preserve-table")
            self.assertTrue(any("视觉建议" in item for item in hint["design_directives"]))

    def test_markdown_batch_left_table_right_image_directive_applies_to_target_pages(self) -> None:
        with tempfile.TemporaryDirectory(prefix="upload-parser-batch-layout-") as td:
            root = Path(td)
            source = root / "lianhua.md"
            source.write_text(
                """# 联华超市2026年AI应用规划

#### 第7页 L1｜夯实 AI 基础能力，让组织具备持续用 AI 的土壤

- AI先锋｜通过 AI 训练营提升员工 AI 使用能力

<callout emoji="🟢">
P8-P11 都按照左边表格，右边配图的模式
</callout>

#### 第8页 L2/L3｜推进门店运营标准化

| 模块 | 内容 |
|-|-|
| 项目目标 | 通过巡检标准化、执行在线化和整改闭环化。 |

![门店巡检 AI 执行与整改闭环](page08.png)

#### 第9页 L3｜建设门店智能助手

| 模块 | 内容 |
|-|-|
| 项目目标 | 将总部制度、流程、SOP 和经验知识转化为可即时调用的一线能力。 |

![门店智能问答助手](page09.png)
""",
                encoding="utf-8",
            )
            out = root / "out"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(PARSER),
                    str(source),
                    "--brief",
                    "基于飞书文档生成联华 AI 应用规划",
                    "--output-dir",
                    str(out),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            dossier_path = out / "source-dossier.json"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(VALIDATOR),
                    "--schema",
                    str(SCHEMA),
                    "--instance",
                    str(dossier_path),
                ],
                cwd=REPO,
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
            dossier = json.loads(dossier_path.read_text(encoding="utf-8"))
            by_page = {item["page"]: item for item in dossier["slide_layer"]}
            self.assertEqual(by_page[8]["layout_hint"], "source-directed-layout")
            self.assertEqual(by_page[9]["layout_hint"], "source-directed-layout")
            self.assertEqual(by_page[8]["reconstruction_hint"]["preferred_layout"], "left-table-right-image")
            self.assertEqual(
                by_page[9]["reconstruction_hint"]["batch_layout_directive"]["end_page"],
                11,
            )


if __name__ == "__main__":
    unittest.main()
