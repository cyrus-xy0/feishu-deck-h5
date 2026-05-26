#!/usr/bin/env python3
"""Minimal server-side generator wrapper for lark-deck-cyrus.

This is the productized P0 path around the existing local skills:

  Brief -> Outline -> DeckJSON -> renderer -> validator -> editable zip

It intentionally uses only the Python standard library so it can run anywhere
the current repo already runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


REPO = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO / "runs"
OUTLINE_VALIDATOR = REPO / "skills/deck-outline-planner/validate-outline.py"
RENDERER = REPO / "skills/feishu-deck-h5/deck-json/render-deck.py"
CHECK_ONLY = REPO / "skills/feishu-deck-h5/assets/check-only.sh"
PACKAGE = REPO / "skills/feishu-deck-h5/assets/package-deliverable.sh"
BASE_LIBRARY = REPO / "scripts/base_library.py"

REQUIRED_OUTPUTS = [
    "deck.json",
    "index.html",
    "texts.md",
    "FEEDBACK.md",
    "assets-manifest.yaml",
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def compact_date() -> str:
    return datetime.now().strftime("%Y.%m.%d")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def slugify(value: str, fallback: str = "deck") -> str:
    raw = (value or "").strip().lower()
    raw = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    if not raw or not raw[0].isalpha():
        digest = hashlib.sha1((value or fallback).encode("utf-8")).hexdigest()[:8]
        raw = f"{fallback}-{digest}"
    return raw[:48].strip("-")


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        parts = re.split(r"[,;，；\n]+", value)
        return [p.strip() for p in parts if p.strip()]
    return [str(value).strip()]


def brief_value(brief: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = brief.get(key)
        if value:
            return str(value).strip()
    return default


def base_identity() -> str:
    return os.environ.get("LARK_LIBRARY_AS", "user")


def query_base_library(command: str, keyword: str, limit: int = 5) -> list[dict[str, Any]]:
    proc = subprocess.run(
        [
            sys.executable,
            str(BASE_LIBRARY),
            "--as",
            base_identity(),
            command,
            keyword,
            "--limit",
            str(limit),
            "--format",
            "json",
        ],
        cwd=REPO,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"Base library query failed: {command} {keyword}\n{proc.stderr or proc.stdout}")
    return json.loads(proc.stdout)


def base_knowledge_refs(industry: str, business_moment: str, product_scope: list[str]) -> list[dict[str, Any]]:
    keyword_candidates = [
        " ".join([industry, business_moment, *product_scope]).strip(),
        industry,
        business_moment,
        *product_scope[:2],
        "行业包",
    ]
    rows: list[dict[str, Any]] = []
    seen_records: set[str] = set()
    for keyword in [k for k in keyword_candidates if k]:
        for row in query_base_library("search-knowledge", keyword, limit=3):
            record_id = str(row.get("_record_id") or row.get("文档ID") or row.get("标题") or "")
            if record_id in seen_records:
                continue
            seen_records.add(record_id)
            rows.append(row)
            if len(rows) >= 3:
                break
        if len(rows) >= 3:
            break
    refs = []
    for row in rows:
        refs.append(
            {
                "source": "feishu-base",
                "table": "知识库",
                "record_id": row.get("_record_id", ""),
                "doc_id": row.get("文档ID", ""),
                "title": row.get("标题", ""),
                "cache_path": row.get("本地路径", ""),
                "summary": row.get("摘要", ""),
                "used_for": "作为场景痛点、证据纪律和素材计划参考；不得把通用知识写成客户事实。",
            }
        )
    return refs


def high_value_questions(brief: dict[str, Any]) -> list[str]:
    checks = [
        ("customer_name", "客户是谁,是否需要使用客户 logo 或已有案例?"),
        ("industry", "客户所属行业和最关键的业务时刻是什么?"),
        ("audience", "这份 deck 讲给谁,他们要做什么决策?"),
        ("objective", "讲完后希望客户确认的下一步是什么?"),
        ("product_scope", "本次要重点讲哪些飞书产品或能力边界?"),
        ("attachments", "是否有可引用的附件、截图、客户材料或公开来源?"),
    ]
    questions = [q for key, q in checks if not brief.get(key)]
    return questions[:5]


def brief_to_outline(brief: dict[str, Any]) -> dict[str, Any]:
    title = brief_value(brief, "title", "brief", default="客户 pitch deck")
    customer = brief_value(brief, "customer_name", "customer", default="目标客户")
    industry = brief_value(brief, "industry", default="未知行业")
    audience = brief_value(brief, "audience", "target_audience", default="客户业务负责人和项目推动者")
    objective = brief_value(brief, "objective", default="推动客户确认下一步试点")
    success_metric = brief_value(brief, "success_metric", default="确认试点场景、负责人和时间表")
    product_scope = normalize_list(brief.get("product_scope")) or ["飞书 AI", "多维表格", "知识库", "任务闭环"]
    business_moment = brief_value(brief, "business_moment", default="方案共创和试点决策")
    core_tension = brief_value(
        brief,
        "core_tension",
        default="业务目标明确,但流程、知识、数据和复盘尚未形成可追踪闭环",
    )
    solution_angle = brief_value(
        brief,
        "solution_angle",
        default="用飞书把入口、任务、知识和数据连成可试点、可复盘的工作流",
    )

    pain_points = [
        {
            "name": "流程断点",
            "why_now": "业务节奏加快后,靠人工同步很难持续追踪动作。",
            "impact": "团队容易停留在沟通完成,但责任、异常和复盘没有闭环。",
            "evidence_level": "hypothesis",
            "evidence_needed": "需要用户补充真实流程、截图、表格或会议材料。",
        },
        {
            "name": "知识和数据不回流",
            "why_now": "问题、经验和指标散在不同系统或群聊里。",
            "impact": "同类问题反复出现,优秀做法难以复用。",
            "evidence_level": "hypothesis",
            "evidence_needed": "需要确认可引用的数据源和客户版本边界。",
        },
    ]

    slides = [
        {
            "key": "cover",
            "title": title,
            "role": "cover",
            "message": f"面向{customer}的{industry}方案。",
            "layout_candidate": {"layout": "cover"},
            "assets": ["customer-logo"],
        },
        {
            "key": "business-gap",
            "title": "业务断点",
            "role": "pain",
            "message": core_tension,
            "content_beats": [p["name"] for p in pain_points],
            "layout_candidate": {"layout": "content", "variant": "before-after"},
            "assets": [],
            "risk_flags": ["缺少客户提供证据时,不得写成已验证事实。"],
        },
        {
            "key": "solution-loop",
            "title": "飞书工作流闭环",
            "role": "solution",
            "message": solution_angle,
            "content_beats": product_scope,
            "layout_candidate": {"layout": "arch-stack"},
            "assets": ["product-icons"],
        },
        {
            "key": "pilot-metrics",
            "title": "试点指标",
            "role": "evidence",
            "message": "先定义验证口径,不提前承诺结果。",
            "layout_candidate": {"layout": "stats", "variant": "row"},
            "assets": ["pilot-data"],
        },
        {
            "key": "pilot-path",
            "title": "试点路径",
            "role": "roadmap",
            "message": "从一个具体场景开始,跑完闭环后再扩展。",
            "layout_candidate": {"layout": "flow", "variant": "timeline"},
            "assets": [],
        },
        {
            "key": "next-step",
            "title": "下一步",
            "role": "closing",
            "message": success_metric,
            "layout_candidate": {"layout": "end"},
            "assets": [],
        },
    ]

    return {
        "version": "1.0",
        "brief": {
            "title": title,
            "audience": audience,
            "requester_context": brief_value(brief, "requester_context", default="generator wrapper"),
            "objective": objective,
            "success_metric": success_metric,
            "delivery_mode": brief_value(brief, "delivery_mode", default="feishu-bot"),
            "constraints": ["默认中文", "不能编造客户数据", "缺证据时写成待确认问题"],
        },
        "scene": {
            "industry": industry,
            "segment": brief_value(brief, "segment", default=""),
            "user_role": audience,
            "business_moment": business_moment,
            "core_tension": core_tension,
            "confidence": "low" if high_value_questions(brief) else "medium",
        },
        "thesis": {
            "one_sentence": f"{customer}可以先围绕一个{business_moment}场景,验证{solution_angle}。",
            "pain_points": pain_points,
            "solution_angle": solution_angle,
            "differentiation": "从单页功能展示升级为可验证、可复盘、可扩展的业务闭环。",
        },
        "knowledge_refs": base_knowledge_refs(industry, business_moment, product_scope),
        "outline": {
            "arc": "客户场景 -> 业务断点 -> 飞书闭环 -> 试点指标 -> 试点路径 -> 下一步",
            "slides": slides,
        },
        "asset_plan": [
            {
                "id": "customer-logo",
                "type": "logo",
                "need": "客户官方 logo",
                "query": customer,
                "preferred_source": "feishu-base",
                "fallback": "缺失时不伪造商标,只使用文字客户名。",
                "required": False,
            },
            {
                "id": "product-icons",
                "type": "icon",
                "need": "飞书产品标识或能力 icon",
                "query": "、".join(product_scope),
                "preferred_source": "feishu-base",
                "fallback": "使用文字 pill,不手绘商标。",
                "required": False,
            },
            {
                "id": "pilot-data",
                "type": "data",
                "need": "试点指标口径和基线数据",
                "preferred_source": "user-provided",
                "fallback": "只写指标定义和待确认项。",
                "required": False,
            },
        ],
        "open_questions": high_value_questions(brief),
        "claim_discipline": {
            "unsupported_claims": ["不能声明客户已经实现的百分比提升或具名访谈结论。"],
            "needs_user_confirmation": high_value_questions(brief)
            or ["试点范围、指标口径和客户版本边界。"],
        },
        "handoff": {
            "target_skill": "feishu-deck-h5",
            "deckjson_strategy": "direct",
            "notes": "generator wrapper 生成确定性初稿;真实客户交付前应补齐 open questions。",
        },
    }


def outline_to_deck(outline: dict[str, Any]) -> dict[str, Any]:
    brief = outline["brief"]
    scene = outline["scene"]
    thesis = outline["thesis"]
    customer = "目标客户"
    title = brief["title"]
    slug = slugify(title)
    product_scope = outline["outline"]["slides"][2].get("content_beats") or ["飞书 AI", "多维表格", "知识库", "任务"]
    product_scope = product_scope[:4]

    before_items = [p["impact"] for p in thesis.get("pain_points", [])][:3]
    while len(before_items) < 3:
        before_items.append("关键动作和复盘信息分散,推进依赖人工提醒。")
    after_items = [
        "入口统一到飞书消息 / bot / 表单。",
        "动作进入任务、表格或知识库,责任和状态可追踪。",
        "复盘沉淀为下一次可复用的知识和页面。",
    ]

    deck = {
        "version": "1.0",
        "deck": {
            "title": title,
            "author": "lark-deck-cyrus generator",
            "date": compact_date(),
            "presentation_date": today(),
            "customer_slug": slug,
            "language": "zh-only",
            "mode": "rewrite",
        },
        "slides": [
            {
                "key": "cover",
                "layout": "cover",
                "data": {
                    "title": title,
                    "author": "方案初稿",
                    "date": f"{scene['industry']} · {compact_date()}",
                },
            },
            {
                "key": "business-gap",
                "layout": "content",
                "variant": "before-after",
                "accent": "orange",
                "data": {
                    "title": "这份方案先解决一个问题:业务动作能否闭环",
                    "before": {"tag": "现状 · 分散推进", "items": before_items},
                    "pivot": {"caption": "飞书工作流"},
                    "after": {"tag": "目标 · 可追踪闭环", "items": after_items},
                },
            },
            {
                "key": "solution-loop",
                "layout": "arch-stack",
                "accent": "blue",
                "data": {
                    "title": "用飞书把入口、能力、对象和治理连成一条链",
                    "layers": [
                        {"name": {"title": "业务入口", "sub": "GTM / 客户"}, "modules": ["飞书 bot", "表单", "群聊", "移动端"]},
                        {"name": {"title": "产品能力", "sub": "重点范围"}, "modules": product_scope},
                        {"name": {"title": "业务对象", "sub": "可追踪"}, "modules": ["任务", "知识", "数据", "复盘"]},
                        {"name": {"title": "治理底座", "sub": "可交付"}, "modules": ["权限", "来源", "版本", "看板"]},
                    ],
                },
            },
            {
                "key": "pilot-metrics",
                "layout": "stats",
                "variant": "row",
                "accent": "teal",
                "data": {
                    "title": "试点先看口径,不提前承诺效果",
                    "cols": [
                        {"icon": "target", "num": "1", "unit": "个", "label": "先选一个具体业务场景"},
                        {"icon": "users", "num": "N", "unit": "人", "label": "试点角色和范围由客户确认"},
                        {"icon": "clipboard-check", "num": "3", "unit": "类", "label": "跟踪动作、异常、复盘沉淀"},
                    ],
                    "footnote": "所有结果数字需试点后由客户数据确认。",
                },
            },
            {
                "key": "pilot-path",
                "layout": "flow",
                "variant": "timeline",
                "accent": "blue",
                "data": {
                    "title": "四步把初稿推进到可验证试点",
                    "cols": 4,
                    "nodes": [
                        {"when": "D1", "what": "确认场景", "desc": "补齐客户、受众、目标和材料边界。"},
                        {"when": "D2-3", "what": "接入素材", "desc": "整理 logo、流程截图、知识和指标口径。"},
                        {"when": "D4-7", "what": "试跑闭环", "desc": "用一个真实流程验证入口、任务和反馈。"},
                        {"when": "D8+", "what": "复盘扩展", "desc": "根据证据决定扩展、改版或入库复用。"},
                    ],
                },
            },
            {
                "key": "next-step",
                "layout": "end",
                "data": {"title": "下一步", "slogan": brief.get("success_metric") or "确认试点场景、素材和负责人"},
            },
        ],
    }
    if customer != "目标客户":
        deck["notes"] = f"Customer: {customer}"
    return deck


def run_command(cmd: list[str], log_path: Path, cwd: Path = REPO) -> subprocess.CompletedProcess[str]:
    started = time.time()
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    elapsed = time.time() - started
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "$ " + " ".join(cmd) + "\n"
        + f"# exit={proc.returncode} elapsed={elapsed:.2f}s\n\n"
        + "## stdout\n"
        + proc.stdout
        + "\n## stderr\n"
        + proc.stderr,
        encoding="utf-8",
    )
    return proc


def delivery_name(deck: dict[str, Any]) -> str:
    meta = deck.get("deck", {})
    slug = meta.get("customer_slug") or slugify(meta.get("title", "deck"))
    date = meta.get("presentation_date") or today()
    return f"lark-{slug}-{date}"


def write_feedback(output_dir: Path, outline: dict[str, Any], deck: dict[str, Any], source: str) -> None:
    meta = deck.get("deck", {})
    questions = outline.get("open_questions") or []
    question_lines = "\n".join(f"- [ ] {q}" for q in questions) if questions else "- 无;本次输入已足够生成初稿。"
    content = f"""# Run feedback · {meta.get('title', 'deck')}

生成时间: {now_iso()}
来源: {source}
产物: DeckJSON-first HTML deck, {len(deck.get('slides', []))} slides

## 关键决策(本 run 实际发生的判断)

### 1. 使用 DeckJSON-first 生成
- **决策**: 先生成 `outline.json` 和 `deck.json`,再由 renderer 生成 `index.html`。
- **为什么**: 服务端链路需要稳定校验、可重渲染和可版本化,不能把 HTML 当源文件。
- **你的看法**:
  - [ ] 对
  - [ ] 应改成其他生成路径
  - [ ] 备注:

### 2. 缺证据的内容降级为待确认
- **决策**: 未提供客户数据或附件时,只写试点指标口径和待确认项。
- **为什么**: 产品规则禁止编造客户数据、具名引语或已实现效果。
- **你的看法**:
  - [ ] 对
  - [ ] 应补充真实证据后增强页面
  - [ ] 备注:

### 3. 固定产物已按服务端任务输出
- **决策**: 本次任务输出 `deck.json`、`index.html`、`texts.md`、`FEEDBACK.md`、`assets-manifest.yaml` 和可编辑 zip。
- **为什么**: GTM / Bot / Web 都需要同一套交付契约,方便预览、编辑、下载和追踪失败原因。
- **你的看法**:
  - [ ] 对
  - [ ] 需要增加其他产物
  - [ ] 备注:

## 本次没解决的小毛病

{question_lines}

## 你的额外建议

-

---

累计 >=3 条值得反馈的(打钩 / 备注 / 自填),把这个文件发给 skill 维护者整合到下一版。
"""
    (output_dir / "FEEDBACK.md").write_text(content, encoding="utf-8")


def output_artifacts(task_id: str, output_dir: Path, base_url: str | None = None) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for path in sorted(output_dir.iterdir()):
        if path.is_file():
            artifacts[path.name] = str(path)
    zip_files = sorted(output_dir.glob("*.zip"))
    preview = output_dir / "index.html"
    editable = zip_files[0] if zip_files else output_dir / "deck-editable.zip"
    if base_url:
        root = base_url.rstrip("/")
        artifacts["preview_url"] = f"{root}/decks/{task_id}/files/index.html"
        artifacts["edit_url"] = f"{root}/decks/{task_id}/files/{editable.name}"
        artifacts["download_url"] = artifacts["edit_url"]
    else:
        artifacts["preview_url"] = preview.resolve().as_uri() if preview.exists() else ""
        artifacts["edit_url"] = editable.resolve().as_uri() if editable.exists() else ""
        artifacts["download_url"] = artifacts["edit_url"]
    return artifacts


def assert_required_outputs(output_dir: Path) -> list[str]:
    missing = [name for name in REQUIRED_OUTPUTS if not (output_dir / name).exists()]
    if not list(output_dir.glob("*.zip")):
        missing.append("editable zip")
    return missing


def task_paths(task_id: str) -> tuple[Path, Path, Path, Path]:
    task_dir = RUNS_DIR / task_id
    input_dir = task_dir / "input"
    output_dir = task_dir / "output"
    log_dir = task_dir / "logs"
    return task_dir, input_dir, output_dir, log_dir


def save_task(task_dir: Path, task: dict[str, Any]) -> None:
    task["updated_at"] = now_iso()
    write_json(task_dir / "task.json", task)


def load_task(task_id: str) -> dict[str, Any]:
    task_path = RUNS_DIR / task_id / "task.json"
    if not task_path.exists():
        raise FileNotFoundError(task_id)
    return read_json(task_path)


def create_or_run_task(
    request: dict[str, Any],
    *,
    task_id: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    brief = request.get("brief") or {}
    if not isinstance(brief, dict):
        raise ValueError("request.brief must be an object when provided")

    source = "deck_json" if request.get("deck_json") else "outline" if request.get("outline") else "brief"
    title_source = (
        (request.get("deck_json") or {}).get("deck", {}).get("title")
        if isinstance(request.get("deck_json"), dict)
        else brief_value(brief, "customer_name", "title", "brief", default="deck")
    )
    task_id = task_id or f"generator-{datetime.now():%Y%m%d-%H%M%S}-{slugify(str(title_source))}"
    task_dir, input_dir, output_dir, log_dir = task_paths(task_id)
    if task_dir.exists():
        shutil.rmtree(task_dir)
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)

    task = {
        "id": task_id,
        "status": "running",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "source": source,
        "input_dir": str(input_dir),
        "output_dir": str(output_dir),
        "logs": {},
        "artifacts": {},
        "error": None,
    }
    save_task(task_dir, task)
    write_json(input_dir / "request.json", request)

    try:
        if request.get("outline"):
            outline = request["outline"]
        else:
            outline = brief_to_outline(brief)
        write_json(input_dir / "outline.json", outline)

        if request.get("deck_json"):
            deck = request["deck_json"]
        else:
            deck = outline_to_deck(outline)
        write_json(output_dir / "deck.json", deck)

        outline_log = log_dir / "outline-validator.txt"
        proc = run_command(["python3", str(OUTLINE_VALIDATOR), str(input_dir / "outline.json")], outline_log)
        task["logs"]["outline_validator"] = str(outline_log)
        if proc.returncode != 0:
            raise RuntimeError("outline validation failed")

        render_log = log_dir / "render.txt"
        proc = run_command(
            [
                "python3",
                str(RENDERER),
                str(output_dir / "deck.json"),
                str(output_dir),
                "--shared=copy",
            ],
            render_log,
        )
        task["logs"]["render"] = str(render_log)
        if proc.returncode != 0:
            raise RuntimeError("render failed")

        write_feedback(output_dir, outline, deck, source)

        validator_report = output_dir / "validator-report.md"
        check_log = log_dir / "check-only.txt"
        proc = run_command(
            ["bash", str(CHECK_ONLY), str(output_dir / "index.html"), "--strict", "--report", str(validator_report)],
            check_log,
        )
        task["logs"]["check_only"] = str(check_log)
        task["artifacts"]["validator-report.md"] = str(validator_report)
        if proc.returncode != 0:
            raise RuntimeError("validator failed under --strict")

        zip_name = delivery_name(deck)
        package_log = log_dir / "package.txt"
        proc = run_command(["bash", str(PACKAGE), str(output_dir), "--name", zip_name], package_log)
        task["logs"]["package"] = str(package_log)
        if proc.returncode != 0:
            raise RuntimeError("editable zip packaging failed")

        missing = assert_required_outputs(output_dir)
        if missing:
            raise RuntimeError("missing required outputs: " + ", ".join(missing))

        task["status"] = "succeeded"
        task["artifacts"].update(output_artifacts(task_id, output_dir, base_url=base_url))
    except Exception as exc:  # noqa: BLE001 - task wrapper should persist any failure.
        task["status"] = "failed"
        task["error"] = str(exc)
        task["artifacts"].update(output_artifacts(task_id, output_dir, base_url=base_url))
    save_task(task_dir, task)
    return task


def load_request_file(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if "deck" in data and "slides" in data:
        return {"deck_json": data}
    return data


class GeneratorHandler(BaseHTTPRequestHandler):
    server_version = "lark-deck-generator/0.1"

    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        host_s = "127.0.0.1" if host in ("", "0.0.0.0") else host
        return f"http://{host_s}:{port}"

    def send_json(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def read_body_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API.
        parsed = urlparse(self.path)
        parts = [unquote(p) for p in parsed.path.strip("/").split("/") if p]
        if parsed.path == "/health":
            self.send_json(200, {"ok": True})
            return
        if len(parts) == 2 and parts[0] == "decks":
            try:
                self.send_json(200, load_task(parts[1]))
            except FileNotFoundError:
                self.send_json(404, {"error": "task not found", "id": parts[1]})
            return
        if len(parts) >= 4 and parts[0] == "decks" and parts[2] == "files":
            task_id = parts[1]
            rel = Path(*parts[3:])
            output_dir = RUNS_DIR / task_id / "output"
            target = (output_dir / rel).resolve()
            if not target.is_file() or not target.is_relative_to(output_dir.resolve()):
                self.send_json(404, {"error": "file not found"})
                return
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            raw = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API.
        parsed = urlparse(self.path)
        parts = [unquote(p) for p in parsed.path.strip("/").split("/") if p]
        try:
            if parts == ["decks"]:
                task = create_or_run_task(self.read_body_json(), base_url=self.base_url())
                self.send_json(201 if task["status"] == "succeeded" else 500, task)
                return
            if len(parts) == 3 and parts[0] == "decks" and parts[2] == "regenerate":
                task_id = parts[1]
                request_path = RUNS_DIR / task_id / "input" / "request.json"
                if not request_path.exists():
                    self.send_json(404, {"error": "task not found", "id": task_id})
                    return
                task = create_or_run_task(read_json(request_path), task_id=task_id, base_url=self.base_url())
                self.send_json(200 if task["status"] == "succeeded" else 500, task)
                return
        except Exception as exc:  # noqa: BLE001
            self.send_json(400, {"error": str(exc)})
            return
        self.send_json(404, {"error": "not found"})

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[generator] " + (fmt % args) + "\n")


def cmd_create(args: argparse.Namespace) -> int:
    if args.request:
        request = load_request_file(args.request)
    elif args.deck_json:
        request = {"deck_json": read_json(args.deck_json)}
        if args.brief:
            request["brief"] = read_json(args.brief)
    elif args.brief:
        request = {"brief": read_json(args.brief)}
    else:
        raise SystemExit("create requires --request, --deck-json, or --brief")
    task = create_or_run_task(request, base_url=args.base_url)
    print(json.dumps(task, ensure_ascii=False, indent=2))
    return 0 if task["status"] == "succeeded" else 1


def cmd_status(args: argparse.Namespace) -> int:
    print(json.dumps(load_task(args.task_id), ensure_ascii=False, indent=2))
    return 0


def cmd_regenerate(args: argparse.Namespace) -> int:
    request_path = RUNS_DIR / args.task_id / "input" / "request.json"
    if not request_path.exists():
        raise SystemExit(f"task not found: {args.task_id}")
    task = create_or_run_task(read_json(request_path), task_id=args.task_id, base_url=args.base_url)
    print(json.dumps(task, ensure_ascii=False, indent=2))
    return 0 if task["status"] == "succeeded" else 1


def cmd_serve(args: argparse.Namespace) -> int:
    httpd = ThreadingHTTPServer((args.host, args.port), GeneratorHandler)
    host, port = httpd.server_address[:2]
    print(f"generator listening on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="create and run a deck generation task")
    create.add_argument("--request", type=Path, help="JSON request with brief, outline, and/or deck_json")
    create.add_argument("--brief", type=Path, help="brief JSON; used when no request is supplied")
    create.add_argument("--deck-json", type=Path, help="DeckJSON source; skips deterministic brief planner")
    create.add_argument("--base-url", help="external base URL used to populate preview/edit links")
    create.set_defaults(func=cmd_create)

    status = sub.add_parser("status", help="print task status JSON")
    status.add_argument("task_id")
    status.set_defaults(func=cmd_status)

    regen = sub.add_parser("regenerate", help="rerun an existing task from input/request.json")
    regen.add_argument("task_id")
    regen.add_argument("--base-url", help="external base URL used to populate preview/edit links")
    regen.set_defaults(func=cmd_regenerate)

    serve = sub.add_parser("serve", help="run the HTTP wrapper")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
