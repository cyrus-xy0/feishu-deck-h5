#!/usr/bin/env python3
"""Run 5 product-level H5 deck eval rounds.

Each round uses different business input, validates the outline, renders
DeckJSON to HTML, captures slide screenshots with local Chrome when available,
and writes a compact evaluation report.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
OUTLINE_VALIDATOR = REPO / "skills/deck-outline-planner/validate-outline.py"
RENDERER = REPO / "skills/feishu-deck-h5/deck-json/render-deck.py"
CHECK_ONLY = REPO / "skills/feishu-deck-h5/assets/check-only.sh"
REHEARSAL_SIM = REPO / "skills/pitch-rehearsal-simulator/simulate-pitch.py"
REHEARSAL_VALIDATOR = REPO / "skills/pitch-rehearsal-simulator/validate-rehearsal.py"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def run(cmd: list[str], cwd: Path = REPO, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            cmd,
            124,
            (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            (exc.stderr or "") if isinstance(exc.stderr, str) else f"timeout after {timeout}s",
        )


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def png_size(path: Path) -> tuple[int, int] | None:
    raw = path.read_bytes()
    if len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(raw[16:20], "big"), int.from_bytes(raw[20:24], "big")


def screenshot_indices(slides: int) -> list[int]:
    if slides <= 3:
        return list(range(1, slides + 1))
    return sorted({1, max(1, (slides + 1) // 2), slides})


def capture_screenshots(html: Path, slides: int, out_dir: Path) -> tuple[bool, list[str]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if not CHROME.exists():
        return False, [f"Chrome not found at {CHROME}"]

    issues: list[str] = []
    user_data = out_dir.parent / "chrome-profile"
    user_data.mkdir(parents=True, exist_ok=True)
    html_url = html.resolve().as_uri()
    ok = True
    for idx in screenshot_indices(slides):
        shot = out_dir / f"slide-{idx:02d}.png"
        cmd = [
            str(CHROME),
            "--headless=new",
            "--disable-gpu",
            "--disable-background-networking",
            "--disable-breakpad",
            "--disable-component-update",
            "--disable-crash-reporter",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-sync",
            "--hide-scrollbars",
            "--no-first-run",
            "--allow-file-access-from-files",
            "--run-all-compositor-stages-before-draw",
            "--virtual-time-budget=2500",
            "--window-size=1920,1080",
            f"--user-data-dir={user_data}",
            f"--screenshot={shot}",
            f"{html_url}#{idx}",
        ]
        proc = run(cmd, timeout=5)
        if not shot.exists():
            ok = False
            issues.append(f"slide {idx:02d} screenshot failed: {proc.stderr.strip() or proc.stdout.strip()}")
            continue
        if proc.returncode not in (0, 124):
            ok = False
            issues.append(f"slide {idx:02d} screenshot command exited {proc.returncode}: {proc.stderr.strip() or proc.stdout.strip()}")
        size = png_size(shot)
        if size != (1920, 1080):
            ok = False
            issues.append(f"slide {idx:02d} screenshot size {size}, expected 1920x1080")
    return ok, issues


def content_score(outline: dict, deck: dict) -> tuple[int, list[str]]:
    score = 0
    notes: list[str] = []

    brief = outline.get("brief", {})
    if all(brief.get(k) for k in ["audience", "objective", "success_metric", "delivery_mode"]):
        score += 2
    else:
        notes.append("brief 缺少受众、目标、成功指标或入口模式")

    pain_points = outline.get("thesis", {}).get("pain_points", [])
    levels = {p.get("evidence_level") for p in pain_points}
    if len(pain_points) >= 2 and levels - {"hypothesis"}:
        score += 2
    else:
        notes.append("痛点证据等级偏弱,需要更多用户或公开证据")

    slides = outline.get("outline", {}).get("slides", [])
    if 5 <= len(slides) <= 7 and all(s.get("message") for s in slides):
        score += 2
    else:
        notes.append("页数或每页 message 不够稳定")

    asset_ids = {a.get("id") for a in outline.get("asset_plan", [])}
    dangling = [asset for s in slides for asset in (s.get("assets") or []) if asset not in asset_ids]
    if not dangling:
        score += 1
    else:
        notes.append(f"素材引用未进入 asset_plan: {', '.join(sorted(set(dangling)))}")

    unsupported = outline.get("claim_discipline", {}).get("unsupported_claims", [])
    confirmations = outline.get("claim_discipline", {}).get("needs_user_confirmation", [])
    if unsupported and confirmations:
        score += 1
    else:
        notes.append("claim_discipline 没有暴露 unsupported / confirmation")

    serialized = json.dumps(deck, ensure_ascii=False)
    risky_patterns = [r"客户访谈", r"内部口径", r"STORY\s*\d+", r"提升\s*\d+%", r"节省\s*\d+%"]
    hits = [p for p in risky_patterns if re.search(p, serialized)]
    if not hits:
        score += 2
    else:
        notes.append(f"疑似不可 defend 主张: {', '.join(hits)}")

    return score, notes


def html_score(out_dir: Path, slide_count: int, render_ok: bool, check_ok: bool, screenshots_ok: bool, screenshot_issues: list[str]) -> tuple[int, list[str]]:
    score = 0
    notes: list[str] = []
    html = out_dir / "index.html"
    texts = out_dir / "texts.md"

    if render_ok and html.exists():
        score += 3
    else:
        notes.append("renderer 未成功产出 index.html")

    if check_ok:
        score += 2
    else:
        notes.append("check-only 未通过")

    if texts.exists() and texts.stat().st_size > 200:
        score += 1
    else:
        notes.append("texts.md 缺失或过小")

    if screenshots_ok:
        score += 2
    else:
        notes.extend(screenshot_issues or ["截图检查未通过"])

    if slide_count >= 5:
        score += 1
    else:
        notes.append("slide 数量低于产品级 deck 的最小测试密度")

    manifest = out_dir / "assets-manifest.yaml"
    if manifest.exists():
        score += 1
    else:
        notes.append("assets-manifest.yaml 缺失")

    return score, notes


def outline_case(
    *,
    title: str,
    audience: str,
    objective: str,
    success_metric: str,
    delivery_mode: str,
    industry: str,
    moment: str,
    tension: str,
    thesis: str,
    pain_points: list[dict],
    slides: list[dict],
    asset_plan: list[dict],
    open_questions: list[str],
    unsupported: list[str],
    confirmations: list[str],
) -> dict:
    return {
        "version": "1.0",
        "brief": {
            "title": title,
            "audience": audience,
            "objective": objective,
            "success_metric": success_metric,
            "delivery_mode": delivery_mode,
            "constraints": ["默认中文", "不能编造客户数据", "demo 必须服务业务判断"],
        },
        "scene": {
            "industry": industry,
            "business_moment": moment,
            "core_tension": tension,
            "confidence": "medium",
        },
        "thesis": {
            "one_sentence": thesis,
            "pain_points": pain_points,
            "solution_angle": "用飞书 bot / 本地 agent 把任务、知识、数据和复盘连接为可追踪闭环。",
            "differentiation": "从单点工具演示升级为可试点、可度量、可复盘的工作流方案。",
        },
        "knowledge_refs": [
            {
                "source": "feishu-base",
                "table": "知识库",
                "query": industry,
                "cache_path": ".base-cache/knowledge/knowledge/industries/retail-consumer.md",
                "title": "行业包 · 消费零售 / 连锁餐饮",
                "used_for": "通过 Base 检索后作为 pain map 的结构参考;非零售行业只复用来源纪律和素材计划方式。",
            }
        ],
        "outline": {
            "arc": "场景问题 → 工作流断点 → agent / bot 闭环 → 证据与试点路径 → 下一步决策",
            "slides": slides,
        },
        "asset_plan": asset_plan,
        "open_questions": open_questions,
        "claim_discipline": {
            "unsupported_claims": unsupported,
            "needs_user_confirmation": confirmations,
        },
        "handoff": {
            "target_skill": "feishu-deck-h5",
            "deckjson_strategy": "direct",
            "notes": "本 eval 直接生成 DeckJSON,真实客户交付前仍需用户确认 open questions。",
        },
    }


def common_assets(*ids: str) -> list[dict]:
    base = {
        "customer-logo": {
            "id": "customer-logo",
            "type": "logo",
            "need": "客户官方 logo",
            "query": "客户中文名",
            "preferred_source": "feishu-base",
            "fallback": "缺失时请用户上传,不要自行绘制商标。",
            "required": False,
        },
        "workflow-demo": {
            "id": "workflow-demo",
            "type": "demo",
            "need": "端到端工作流 demo 或 HTML mockup",
            "query": "agent workflow demo",
            "preferred_source": "generated",
            "fallback": "用 DeckJSON flow/process 重建示意。",
            "required": False,
        },
        "product-icons": {
            "id": "product-icons",
            "type": "icon",
            "need": "飞书产品标识或能力 icon",
            "query": "飞书标识",
            "preferred_source": "feishu-base",
            "fallback": "使用文字 pill,不画商标。",
            "required": False,
        },
        "pilot-data": {
            "id": "pilot-data",
            "type": "data",
            "need": "试点前后对比数据",
            "query": "试点指标",
            "preferred_source": "user-provided",
            "fallback": "只写指标口径和待确认项。",
            "required": False,
        },
    }
    return [base[i] for i in ids]


def deck_base(title: str, slug: str) -> dict:
    return {
        "version": "1.0",
        "deck": {
            "title": title,
            "author": "产品化 eval",
            "date": "2026.05.25",
            "presentation_date": "2026-05-25",
            "customer_slug": slug,
            "language": "zh-only",
            "mode": "rewrite",
        },
        "slides": [],
    }


def cases() -> list[dict]:
    retail_outline_slides = [
        {"key": "cover", "title": "门店执行 AI agent 方案", "role": "cover", "message": "新品上市和门店巡检的闭环试点。", "layout_candidate": {"layout": "cover"}, "assets": ["customer-logo"]},
        {"key": "execution-gap", "title": "门店执行断点", "role": "pain", "message": "群聊能提醒,但不能保证动作、反馈和复盘连起来。", "layout_candidate": {"layout": "content", "variant": "before-after"}, "assets": ["workflow-demo"]},
        {"key": "agent-loop", "title": "bot 是入口,agent 是引擎", "role": "solution", "message": "飞书 bot 承接一线入口,agent 调任务、知识和数据。", "layout_candidate": {"layout": "arch-stack"}, "assets": ["product-icons"]},
        {"key": "pilot-metrics", "title": "试点指标只看三件事", "role": "evidence", "message": "先定义可验证指标,避免 demo 变成表演。", "layout_candidate": {"layout": "stats", "variant": "row"}, "assets": ["pilot-data"]},
        {"key": "pilot-path", "title": "两周试点路径", "role": "roadmap", "message": "从一个活动 SOP 和一组门店开始。", "layout_candidate": {"layout": "flow", "variant": "timeline"}, "assets": []},
        {"key": "next-step", "title": "下一步", "role": "closing", "message": "确认试点场景、素材和负责人。", "layout_candidate": {"layout": "end"}, "assets": []},
    ]
    retail_deck = deck_base("连锁门店执行 AI agent 方案", "retail-agent")
    retail_deck["slides"] = [
        {"key": "cover", "layout": "cover", "data": {"title": "门店执行\nAI agent 方案", "author": "产品化 eval", "date": "客户提案 · 2026.05.25"}},
        {"key": "execution-gap", "layout": "content", "variant": "before-after", "accent": "orange", "data": {"title": "门店执行断点不在有没有群,而在动作能否闭环", "before": {"tag": "现状 · 群聊驱动", "items": ["总部发 SOP,区域经理靠群提醒门店", "异常靠人工截图汇总,责任人不稳定", "活动复盘只看到销量,看不到动作差异"]}, "pivot": {"caption": "飞书 bot + agent"}, "after": {"tag": "目标 · 闭环驱动", "items": ["SOP 转为任务清单,门店动作可追踪", "异常自动进入责任队列,处理过程留痕", "复盘同时看到结果、动作和问题沉淀"]}}},
        {"key": "agent-loop", "layout": "arch-stack", "accent": "blue", "data": {"title": "bot 是入口,agent 是把执行跑起来的工作引擎", "layers": [{"name": {"title": "一线入口", "sub": "飞书 bot"}, "modules": ["提问", "接任务", "报异常", "查 SOP"]}, {"name": {"title": "agent 能力", "sub": "流程引擎"}, "modules": ["意图识别", "任务派发", "异常提醒", "复盘摘要"]}, {"name": {"title": "业务对象", "sub": "门店运营"}, "modules": ["活动 SOP", "巡检表", "门店反馈", "经营看板"]}, {"name": {"title": "知识与数据底座", "sub": "治理底座"}, "modules": ["知识库", "多维表格", "审批", "消息记录"]}]}},
        {"key": "pilot-metrics", "layout": "stats", "variant": "row", "accent": "teal", "data": {"title": "试点指标先定义,避免 demo 变成表演", "cols": [{"icon": "check-circle", "num": "1", "unit": "个", "label": "选定一个可复盘的活动 SOP"}, {"icon": "store", "num": "N", "unit": "家", "label": "试点门店数由客户确认"}, {"icon": "clock", "num": "3", "unit": "类", "label": "跟踪任务完成、异常响应、复盘沉淀"}], "footnote": "本页只定义指标口径,不声明客户已实现结果。"}},
        {"key": "pilot-path", "layout": "flow", "variant": "timeline", "accent": "blue", "data": {"title": "两周试点先跑一个闭环,再扩展更多门店动作", "cols": 4, "nodes": [{"when": "D1-2", "what": "确认场景", "desc": "选活动 SOP、门店范围和责任人。"}, {"when": "D3-5", "what": "接入素材", "desc": "整理知识库、任务表和异常口径。"}, {"when": "D6-10", "what": "门店试跑", "desc": "用 bot 完成问答、提醒和上报。"}, {"when": "D11-14", "what": "复盘扩展", "desc": "按指标看是否进入第二阶段。"}]}},
        {"key": "next-step", "layout": "end", "data": {"title": "下一步", "slogan": "确认试点场景、素材和负责人"}},
    ]

    manufacturing_outline_slides = [
        {"key": "cover", "title": "制造质量异常闭环", "role": "cover", "message": "本地 agent 帮质量团队把异常处理沉淀成知识。", "layout_candidate": {"layout": "cover"}, "assets": ["customer-logo"]},
        {"key": "quality-root", "title": "质量异常为什么重复发生", "role": "insight", "message": "问题不是没有记录,而是记录、处置和复用断开。", "layout_candidate": {"layout": "flow", "variant": "tree"}, "assets": []},
        {"key": "local-agent-loop", "title": "本地 agent 工作流", "role": "solution", "message": "不把敏感资料发出去,在本地完成检索、归因和报告草稿。", "layout_candidate": {"layout": "flow", "variant": "process"}, "assets": ["workflow-demo"]},
        {"key": "governance-matrix", "title": "先做高影响低阻力场景", "role": "decision", "message": "用矩阵避免一次性铺太大。", "layout_candidate": {"layout": "content", "variant": "matrix"}, "assets": []},
        {"key": "pilot-path", "title": "四周试点路径", "role": "roadmap", "message": "围绕一种异常类型形成闭环。", "layout_candidate": {"layout": "flow", "variant": "timeline"}, "assets": ["pilot-data"]},
        {"key": "next-step", "title": "下一步", "role": "closing", "message": "确认异常类型、资料边界和参与角色。", "layout_candidate": {"layout": "end"}, "assets": []},
    ]
    manufacturing_deck = deck_base("制造质量异常本地 agent 闭环", "manufacturing-quality")
    manufacturing_deck["slides"] = [
        {"key": "cover", "layout": "cover", "data": {"title": "质量异常\n本地 agent 闭环", "author": "产品化 eval", "date": "方案评审 · 2026.05.25"}},
        {"key": "quality-root", "layout": "flow", "variant": "tree", "accent": "orange", "data": {"title": "质量异常为什么重复发生", "root": {"question": "为什么同类异常处理后还会复发?", "why": "记录存在,但归因、处置、复盘没有形成可复用闭环。"}, "branches": [{"title": "知识散落", "leaves": ["8D 报告、巡检记录、供应商邮件分散", "新人查不到历史相似问题"]}, {"title": "处置不可追踪", "leaves": ["纠正动作没有责任人和截止时间", "跨部门协同靠人工催办"]}, {"title": "复盘不可复用", "leaves": ["经验没有沉淀为标准问答", "再次发生时仍从头排查"]}]}},
        {"key": "local-agent-loop", "layout": "flow", "variant": "process", "accent": "blue", "data": {"title": "本地 agent 在资料边界内完成质量闭环", "cols": 5, "steps": [{"title": "读资料", "body": "读取本地 8D、巡检、来料记录,不外发敏感文件。"}, {"title": "找相似", "body": "按异常现象和物料批次检索历史案例。"}, {"title": "归因建议", "body": "输出可能原因、证据缺口和待确认问题。"}, {"title": "生成任务", "body": "把纠正动作拆成责任人、截止时间和验证方式。"}, {"title": "沉淀知识", "body": "复盘后写入知识库,供下次异常复用。"}]}},
        {"key": "governance-matrix", "layout": "content", "variant": "matrix", "accent": "teal", "data": {"title": "试点优先级:先做高影响、低数据阻力的异常类型", "axes": {"y": {"name": "业务影响", "high_label": "高", "low_label": "低"}, "x": {"name": "数据阻力", "high_label": "高", "low_label": "低"}}, "quadrants": {"tl": {"title": "立即试点", "items": ["重复发生的来料异常", "已有完整 8D 模板"]}, "tr": {"title": "谨慎推进", "items": ["跨供应商争议问题", "需要法务审阅资料"]}, "bl": {"title": "低优先级", "items": ["低频轻微缺陷", "人工处理成本可接受"]}, "br": {"title": "暂缓", "items": ["资料结构混乱", "责任边界尚未定义"]}}}},
        {"key": "pilot-path", "layout": "flow", "variant": "timeline", "accent": "blue", "data": {"title": "四周试点只围绕一种异常类型形成闭环", "cols": 4, "nodes": [{"when": "W1", "what": "资料边界", "desc": "确定可读目录和脱敏规则。"}, {"when": "W2", "what": "相似案例", "desc": "建立异常标签和检索口径。"}, {"when": "W3", "what": "任务闭环", "desc": "把纠正动作接入飞书任务。"}, {"when": "W4", "what": "复盘入库", "desc": "评估误判、漏判和知识沉淀质量。"}]}},
        {"key": "next-step", "layout": "end", "data": {"slogan": "先选一个异常类型,把闭环真正跑完"}},
    ]

    finance_outline_slides = [
        {"key": "cover", "title": "投研材料生产 agent", "role": "cover", "message": "让研究员用本地 agent 生成可追溯材料。", "layout_candidate": {"layout": "cover"}, "assets": []},
        {"key": "research-pain", "title": "投研材料的风险来自不可追溯", "role": "pain", "message": "快不等于可用,证据链才是底线。", "layout_candidate": {"layout": "content", "variant": "3up"}, "assets": []},
        {"key": "source-discipline", "title": "每个主张都要有来源等级", "role": "solution", "message": "把事实、推断、待确认分层。", "layout_candidate": {"layout": "table"}, "assets": []},
        {"key": "agent-process", "title": "从资料包到汇报 deck", "role": "solution", "message": "本地 agent 输出 outline、证据缺口和页面草稿。", "layout_candidate": {"layout": "flow", "variant": "process"}, "assets": ["workflow-demo"]},
        {"key": "review-gate", "title": "交付前的三道门", "role": "decision", "message": "内容、合规、表现都过关才进入客户版本。", "layout_candidate": {"layout": "content", "variant": "blocks"}, "assets": []},
        {"key": "next-step", "title": "下一步", "role": "closing", "message": "拿一个历史材料包做 dry run。", "layout_candidate": {"layout": "end"}, "assets": []},
    ]
    finance_deck = deck_base("投研材料本地 agent 生产闭环", "finance-research")
    finance_deck["slides"] = [
        {"key": "cover", "layout": "cover", "data": {"title": "投研材料\n本地 agent 生产闭环", "author": "产品化 eval", "date": "内部评审 · 2026.05.25"}},
        {"key": "research-pain", "layout": "content", "variant": "3up", "accent": "violet", "data": {"title": "投研材料的风险来自不可追溯,不是来自速度不够快", "cards": [{"num": "01", "icon": "file-search", "title_zh": "材料散", "body": "年报、纪要、模型、新闻和内部笔记各在一处,引用关系难复查。"}, {"num": "02", "icon": "shield-alert", "title_zh": "口径混", "body": "事实、推断、个人判断混在一起,审阅时很难定位风险。"}, {"num": "03", "icon": "repeat", "title_zh": "复用弱", "body": "每次路演都重新整理,历史材料难沉淀为可复用框架。"}]}},
        {"key": "source-discipline", "layout": "table", "accent": "blue", "data": {"title": "每个主张都要有来源等级,才能进入客户版本", "headers": ["来源等级", "可进入 deck 的方式", "禁止动作"], "rows": [["用户提供", "可直接引用,保留文件名或页码", "不要改写成更强结论"], ["公开资料", "可作为事实或行业背景", "不要写成内部确认"], ["agent 推断", "只能放在假设或待确认区", "不要写成研究结论"], ["证据缺口", "进入 open questions 或备忘", "不要用漂亮话补齐"]]}},
        {"key": "agent-process", "layout": "flow", "variant": "process", "accent": "blue", "data": {"title": "从资料包到汇报 deck,每一步都保留证据链", "cols": 5, "steps": [{"title": "读取资料", "body": "本地解析 PDF、表格、纪要和模型说明。"}, {"title": "抽取主张", "body": "分离事实、判断、风险和待确认问题。"}, {"title": "生成 outline", "body": "按受众和决策目标组织页面角色。"}, {"title": "渲染 H5", "body": "DeckJSON 生成可编辑 HTML,保留 text sidecar。"}, {"title": "审阅入库", "body": "通过校验后沉淀为可复用页型和知识。"}]}},
        {"key": "review-gate", "layout": "content", "variant": "blocks", "accent": "teal", "data": {"title": "交付前必须过三道门", "body_blocks": [{"type": "verdict-grid", "cards": [{"verdict": "go", "badge": "内容门", "title": "主张可 defend", "body": "每个关键判断都有来源等级或证据缺口。"}, {"verdict": "conditional", "badge": "合规模", "title": "敏感信息可控", "body": "本地资料边界清楚,客户版本不带内部路径。"}, {"verdict": "go", "badge": "表现门", "title": "HTML 可演示", "body": "通过 validator,可全屏、可发链接、可编辑文本。"}]}]}},
        {"key": "next-step", "layout": "end", "data": {"slogan": "拿一个历史材料包做 dry run,先验证证据链"}},
    ]

    hr_outline_slides = [
        {"key": "cover", "title": "校园招聘 bot 方案", "role": "cover", "message": "把候选人问答、面试协调和复盘放进飞书。", "layout_candidate": {"layout": "cover"}, "assets": ["customer-logo"]},
        {"key": "candidate-pain", "title": "招聘体验断点", "role": "pain", "message": "候选人等待、HR 重复答疑、面试官反馈不闭环。", "layout_candidate": {"layout": "content", "variant": "before-after"}, "assets": []},
        {"key": "bot-demo-plan", "title": "飞书 bot 使用路径", "role": "demo", "message": "demo 展示的是闭环路径,不是功能拼盘。", "layout_candidate": {"layout": "iframe-embed"}, "assets": ["workflow-demo"]},
        {"key": "roles", "title": "三类角色各自得到什么", "role": "solution", "message": "候选人、HR、面试官看到的是同一条流程的不同界面。", "layout_candidate": {"layout": "content", "variant": "3up"}, "assets": ["product-icons"]},
        {"key": "pilot-path", "title": "首轮试点路径", "role": "roadmap", "message": "从一个岗位族开始,跑完 FAQ 到面试复盘。", "layout_candidate": {"layout": "flow", "variant": "timeline"}, "assets": ["pilot-data"]},
        {"key": "next-step", "title": "下一步", "role": "closing", "message": "确认岗位族、FAQ、面试流程和权限边界。", "layout_candidate": {"layout": "end"}, "assets": []},
    ]
    hr_deck = deck_base("校园招聘飞书 bot 闭环", "hr-campus")
    hr_deck["slides"] = [
        {"key": "cover", "layout": "cover", "data": {"title": "校园招聘\n飞书 bot 闭环", "author": "产品化 eval", "date": "方案共创 · 2026.05.25"}},
        {"key": "candidate-pain", "layout": "content", "variant": "before-after", "accent": "purple", "data": {"title": "招聘体验断点来自流程断链,不是单个问答效率", "before": {"tag": "现状 · 多端割裂", "items": ["候选人反复问流程、地点、材料要求", "HR 在群聊和表格之间来回同步", "面试官反馈晚,复盘缺少统一口径"]}, "pivot": {"caption": "飞书 bot"}, "after": {"tag": "目标 · 一条链路", "items": ["候选人通过 bot 获得准确 FAQ 和进度", "HR 在 Base 中看状态、异常和提醒", "面试反馈自动汇总进复盘视图"]}}},
        {"key": "bot-demo-plan", "layout": "content", "variant": "3up", "accent": "blue", "data": {"title": "demo 必须展示闭环路径,不是功能按钮集合", "cards": [{"num": "01", "icon": "message-circle", "title_zh": "候选人入口", "body": "问流程、查材料、收到面试提醒。"}, {"num": "02", "icon": "users", "title_zh": "HR 控台", "body": "查看候选人状态、异常问题和待处理事项。"}, {"num": "03", "icon": "clipboard-check", "title_zh": "复盘沉淀", "body": "面试反馈、问题统计、FAQ 更新进入同一视图。"}], "body_blocks": [{"type": "cta-box", "heading": "真实 demo 前先确认岗位族和权限边界", "body": "没有真实流程口径时,只能展示示意路径,不能承诺已接入客户系统。", "tone": "teal"}]}},
        {"key": "roles", "layout": "content", "variant": "3up", "accent": "teal", "data": {"title": "三类角色看到的是同一条流程的不同视图", "cards": [{"num": "A", "icon": "user", "title_zh": "候选人", "body": "少等待、少重复提交、能知道下一步。"}, {"num": "B", "icon": "briefcase", "title_zh": "HR", "body": "少手工答疑、少催面试官、能看到异常。"}, {"num": "C", "icon": "star", "title_zh": "面试官", "body": "少找信息、少漏反馈、能复用评价模板。"}]}},
        {"key": "pilot-path", "layout": "flow", "variant": "timeline", "accent": "blue", "data": {"title": "首轮试点从一个岗位族开始跑完整闭环", "cols": 4, "nodes": [{"when": "W1", "what": "FAQ 与流程", "desc": "整理候选人高频问题和标准流程。"}, {"when": "W2", "what": "bot 入口", "desc": "上线问答、提醒和状态查询。"}, {"when": "W3", "what": "面试反馈", "desc": "接入评价模板和反馈提醒。"}, {"when": "W4", "what": "复盘优化", "desc": "根据问题统计更新 FAQ 和流程节点。"}]}},
        {"key": "next-step", "layout": "end", "data": {"slogan": "先跑一个岗位族,把候选人体验闭环做实"}},
    ]

    support_outline_slides = [
        {"key": "cover", "title": "SaaS 客服知识 agent", "role": "cover", "message": "让客服问题从回答走向产品反馈闭环。", "layout_candidate": {"layout": "cover"}, "assets": ["customer-logo"]},
        {"key": "support-gap", "title": "客服知识断点", "role": "pain", "message": "回答快,但问题没有回流到产品和知识库。", "layout_candidate": {"layout": "content", "variant": "before-after"}, "assets": []},
        {"key": "knowledge-loop", "title": "知识闭环架构", "role": "solution", "message": "bot、工单、知识库和产品反馈形成闭环。", "layout_candidate": {"layout": "arch-stack"}, "assets": ["product-icons"]},
        {"key": "triage-matrix", "title": "问题分流规则", "role": "decision", "message": "用价值和紧急度决定自动答、人工接、产品回流。", "layout_candidate": {"layout": "content", "variant": "matrix"}, "assets": []},
        {"key": "pilot-metrics", "title": "试点看三类指标", "role": "evidence", "message": "不承诺提升,先定义可验证口径。", "layout_candidate": {"layout": "stats", "variant": "row"}, "assets": ["pilot-data"]},
        {"key": "next-step", "title": "下一步", "role": "closing", "message": "确认知识来源、工单字段和反馈负责人。", "layout_candidate": {"layout": "end"}, "assets": []},
    ]
    support_deck = deck_base("SaaS 客服知识 agent 闭环", "saas-support")
    support_deck["slides"] = [
        {"key": "cover", "layout": "cover", "data": {"title": "客服知识\nagent 闭环", "author": "产品化 eval", "date": "客户成功方案 · 2026.05.25"}},
        {"key": "support-gap", "layout": "content", "variant": "before-after", "accent": "orange", "data": {"title": "客服知识断点:回答快,但问题没有回流", "before": {"tag": "现状 · 单次处理", "items": ["客服在多个知识源之间查答案", "同类问题反复出现,原因不回流", "产品团队只看到聚合后的模糊反馈"]}, "pivot": {"caption": "知识 agent"}, "after": {"tag": "目标 · 闭环改进", "items": ["bot 先答标准问题,人工接复杂场景", "工单自动打标签,沉淀知识缺口", "高频问题进入产品反馈和帮助中心更新"]}}},
        {"key": "knowledge-loop", "layout": "arch-stack", "accent": "blue", "data": {"title": "客服 bot 只是入口,真正价值在知识和反馈闭环", "layers": [{"name": {"title": "服务入口", "sub": "支持入口"}, "modules": ["飞书 bot", "网页客服", "工单入口"]}, {"name": {"title": "agent 能力", "sub": "分流判断"}, "modules": ["意图识别", "答案召回", "置信度判断", "人工分派"]}, {"name": {"title": "业务闭环", "sub": "反馈回流"}, "modules": ["知识库更新", "工单标签", "产品反馈", "复盘看板"]}, {"name": {"title": "治理底座", "sub": "质量控制"}, "modules": ["权限", "审计", "灰度", "质量抽检"]}]}},
        {"key": "triage-matrix", "layout": "content", "variant": "matrix", "accent": "teal", "data": {"title": "问题分流规则:不是所有问题都交给 bot", "axes": {"y": {"name": "客户影响", "high_label": "高", "low_label": "低"}, "x": {"name": "答案确定性", "high_label": "高", "low_label": "低"}}, "quadrants": {"tl": {"title": "人工优先", "items": ["高价值客户投诉", "续约风险相关问题"]}, "tr": {"title": "bot 先答", "items": ["标准操作问题", "已验证帮助文档"]}, "bl": {"title": "异步处理", "items": ["低影响咨询", "不影响使用的建议"]}, "br": {"title": "产品回流", "items": ["知识库缺口", "高频但答案不稳定"]}}}},
        {"key": "pilot-metrics", "layout": "stats", "variant": "row", "accent": "teal", "data": {"title": "试点先看口径,不提前承诺效果", "cols": [{"icon": "message-square", "num": "3", "unit": "类", "label": "标准问答、复杂问题、产品反馈分流"}, {"icon": "database", "num": "1", "unit": "套", "label": "知识库更新和工单标签口径"}, {"icon": "eye", "num": "100", "unit": "%", "label": "高风险回答进入人工抽检"}], "footnote": "所有结果数字需试点后由客户数据确认。"}},
        {"key": "next-step", "layout": "end", "data": {"slogan": "先定义分流规则,再让 agent 接入真实问题"}},
    ]

    outlines = [
        outline_case(title="连锁门店执行 AI agent 方案", audience="连锁餐饮 COO 和运营负责人", objective="推动客户确认两周试点", success_metric="确认试点门店、SOP 和负责人", delivery_mode="feishu-bot", industry="消费零售 / 连锁餐饮", moment="新品上市与门店巡检", tension="总部策略到门店动作不可追踪", thesis="把门店执行从群聊提醒升级为 AI agent 驱动的任务、知识、数据闭环。", pain_points=[{"name": "执行动作衰减", "why_now": "活动节奏更快,区域经理无法逐店盯动作。", "impact": "复盘只能看到销量,看不到动作差异。", "evidence_level": "public-pattern"}, {"name": "一线问题不回流", "why_now": "新人多、班次碎,经验靠人传人。", "impact": "重复问答和重复错误增加管理成本。", "evidence_level": "hypothesis"}], slides=retail_outline_slides, asset_plan=common_assets("customer-logo", "workflow-demo", "product-icons", "pilot-data"), open_questions=["是否有最近一次活动 SOP?", "试点门店范围是多少?"], unsupported=["不能写已提升的百分比。"], confirmations=["试点周期、门店数、指标口径。"]),
        outline_case(title="制造质量异常本地 agent 闭环", audience="质量负责人、IT 和工厂运营负责人", objective="确认一个异常类型进入四周试点", success_metric="确认资料边界、异常类型和参与角色", delivery_mode="local-agent", industry="制造 / 质量管理", moment="重复质量异常复盘", tension="质量资料存在本地,但归因、处置和复盘断开", thesis="用本地 agent 在资料边界内把质量异常处理变成可复用闭环。", pain_points=[{"name": "资料散落", "why_now": "8D、邮件、巡检记录越来越多。", "impact": "相似问题难检索,新人依赖老师傅。", "evidence_level": "public-pattern"}, {"name": "处置不可追踪", "why_now": "纠正动作跨部门,人工催办成本高。", "impact": "同类异常复发时无法快速定位断点。", "evidence_level": "hypothesis"}], slides=manufacturing_outline_slides, asset_plan=common_assets("customer-logo", "workflow-demo", "pilot-data"), open_questions=["哪些资料允许本地 agent 读取?", "优先试点哪类异常?"], unsupported=["不能声明缺陷率下降。"], confirmations=["资料边界、脱敏规则、试点异常类型。"]),
        outline_case(title="投研材料本地 agent 生产闭环", audience="研究负责人、合规审阅和一线研究员", objective="用历史材料包验证证据链生产方式", success_metric="完成一次 dry run 并通过审阅", delivery_mode="local-agent", industry="金融 / 投研", moment="资料包到客户汇报", tension="速度提升不能牺牲来源可追溯", thesis="让本地 agent 生成带来源纪律的 outline 和 H5 deck,把风险前置。", pain_points=[{"name": "来源不可追溯", "why_now": "资料来源多且版本变化快。", "impact": "审阅时无法快速确认主张来源。", "evidence_level": "public-pattern"}, {"name": "复用弱", "why_now": "每次路演都重组材料。", "impact": "经验没有沉淀为稳定页型。", "evidence_level": "hypothesis"}], slides=finance_outline_slides, asset_plan=common_assets("workflow-demo"), open_questions=["历史材料包是否可放入本地目录?", "哪些内容需要合规先审?"], unsupported=["不能写未授权投资结论。"], confirmations=["资料范围、引用规则、客户版本边界。"]),
        outline_case(title="校园招聘飞书 bot 闭环", audience="招聘负责人、HRBP 和校招项目经理", objective="确认一个岗位族进入 bot 试点", success_metric="确认 FAQ、流程节点和权限边界", delivery_mode="feishu-bot", industry="人力资源 / 招聘", moment="校园招聘高峰", tension="候选人体验、HR 协调和面试反馈没有形成同一条链", thesis="用飞书 bot 把候选人问答、面试协调和复盘沉淀串成招聘闭环。", pain_points=[{"name": "重复答疑", "why_now": "校招高峰问题集中且重复。", "impact": "HR 被流程性问题占用。", "evidence_level": "public-pattern"}, {"name": "反馈不闭环", "why_now": "面试官反馈分散且延迟。", "impact": "候选人体验和复盘质量不稳定。", "evidence_level": "hypothesis"}], slides=hr_outline_slides, asset_plan=common_assets("customer-logo", "workflow-demo", "product-icons", "pilot-data"), open_questions=["试点岗位族是什么?", "FAQ 是否已有标准答案?"], unsupported=["不能承诺招聘转化率提升。"], confirmations=["岗位族、流程节点、权限边界。"]),
        outline_case(title="SaaS 客服知识 agent 闭环", audience="客户成功负责人、支持负责人和产品运营", objective="确认知识来源与分流规则试点", success_metric="确认知识库、工单字段和产品反馈负责人", delivery_mode="feishu-bot", industry="SaaS / 客户支持", moment="支持问题规模化", tension="回答问题和改进产品之间断开", thesis="用知识 agent 把客服回答、工单标签和产品反馈连成可复盘闭环。", pain_points=[{"name": "知识缺口反复出现", "why_now": "客户规模扩大后问题重复率上升。", "impact": "支持团队忙于重复处理,产品看不到具体缺口。", "evidence_level": "public-pattern"}, {"name": "风险回答不可控", "why_now": "AI 先答需要置信度和人工抽检。", "impact": "高风险问题若误答会影响客户信任。", "evidence_level": "hypothesis"}], slides=support_outline_slides, asset_plan=common_assets("customer-logo", "product-icons", "pilot-data"), open_questions=["知识库来源有哪些?", "哪些问题必须人工接管?"], unsupported=["不能承诺自动解决率。"], confirmations=["分流规则、工单字段、人工抽检口径。"]),
    ]
    decks = [retail_deck, manufacturing_deck, finance_deck, hr_deck, support_deck]
    slugs = ["retail-agent", "manufacturing-quality", "finance-research", "hr-campus", "saas-support"]
    return [{"slug": slug, "outline": outline, "deck": deck} for slug, outline, deck in zip(slugs, outlines, decks)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=time.strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--skip-screenshots", action="store_true")
    args = parser.parse_args(argv)

    root = REPO / "runs/product-evals" / args.run_id
    root.mkdir(parents=True, exist_ok=True)
    summary: list[dict] = []

    for idx, case in enumerate(cases(), start=1):
        round_dir = root / f"round-{idx:02d}-{case['slug']}"
        input_dir = round_dir / "input"
        output_dir = round_dir / "output"
        screenshot_dir = round_dir / "screenshots"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        outline_path = input_dir / "outline.json"
        deck_path = output_dir / "deck.json"
        write_json(outline_path, case["outline"])
        write_json(deck_path, case["deck"])

        outline_proc = run(["python3", str(OUTLINE_VALIDATOR), str(outline_path)])
        render_proc = run(["python3", str(RENDERER), str(deck_path), str(output_dir), "--shared=link"])
        check_proc = run(["bash", str(CHECK_ONLY), str(output_dir / "index.html"), "--strict"]) if (output_dir / "index.html").exists() else subprocess.CompletedProcess([], 1, "", "index.html missing")
        rehearsal_path = output_dir / "pitch-rehearsal.json"
        rehearsal_md_path = output_dir / "PITCH_REHEARSAL.md"
        rehearsal_proc = run(
            [
                "python3",
                str(REHEARSAL_SIM),
                "--outline",
                str(outline_path),
                "--deck-json",
                str(deck_path),
                "--html",
                str(output_dir / "index.html"),
                "--out-json",
                str(rehearsal_path),
                "--out-md",
                str(rehearsal_md_path),
            ]
        )
        rehearsal_validate_proc = (
            run(["python3", str(REHEARSAL_VALIDATOR), str(rehearsal_path)])
            if rehearsal_path.exists()
            else subprocess.CompletedProcess([], 1, "", "pitch-rehearsal.json missing")
        )
        screenshots_skipped = args.skip_screenshots
        screenshots_ok, screenshot_issues = (True, []) if screenshots_skipped else (False, ["screenshots not run"])
        if not screenshots_skipped and (output_dir / "index.html").exists():
            screenshots_ok, screenshot_issues = capture_screenshots(output_dir / "index.html", len(case["deck"]["slides"]), screenshot_dir)

        c_score, c_notes = content_score(case["outline"], case["deck"])
        h_score, h_notes = html_score(output_dir, len(case["deck"]["slides"]), render_proc.returncode == 0, check_proc.returncode == 0, screenshots_ok, screenshot_issues)

        (round_dir / "logs").mkdir(exist_ok=True)
        (round_dir / "logs/outline-validator.txt").write_text(outline_proc.stdout + outline_proc.stderr, encoding="utf-8")
        (round_dir / "logs/render.txt").write_text(render_proc.stdout + render_proc.stderr, encoding="utf-8")
        (round_dir / "logs/check-only.txt").write_text(check_proc.stdout + check_proc.stderr, encoding="utf-8")
        (round_dir / "logs/pitch-rehearsal.txt").write_text(
            rehearsal_proc.stdout
            + rehearsal_proc.stderr
            + "\n\n--- validate ---\n"
            + rehearsal_validate_proc.stdout
            + rehearsal_validate_proc.stderr,
            encoding="utf-8",
        )

        summary.append(
            {
                "round": idx,
                "slug": case["slug"],
                "outline_ok": outline_proc.returncode == 0,
                "render_ok": render_proc.returncode == 0,
                "check_ok": check_proc.returncode == 0,
                "rehearsal_ok": rehearsal_proc.returncode == 0 and rehearsal_validate_proc.returncode == 0,
                "screenshots_ok": screenshots_ok,
                "screenshots_skipped": screenshots_skipped,
                "content_score": c_score,
                "html_score": h_score,
                "content_notes": c_notes,
                "html_notes": h_notes,
                "html": str((output_dir / "index.html").resolve()),
                "rehearsal": str(rehearsal_path.resolve()),
                "screenshots": str(screenshot_dir.resolve()),
            }
        )

    report = root / "EVAL_REPORT.md"
    lines = ["# Product H5 Eval Report", "", f"Run: `{args.run_id}`", ""]
    for item in summary:
        lines.extend(
            [
                f"## Round {item['round']:02d} · {item['slug']}",
                "",
                f"- outline: {'PASS' if item['outline_ok'] else 'FAIL'}",
                f"- render: {'PASS' if item['render_ok'] else 'FAIL'}",
                f"- check-only strict: {'PASS' if item['check_ok'] else 'FAIL'}",
                f"- pitch rehearsal: {'PASS' if item['rehearsal_ok'] else 'FAIL'}",
                f"- screenshots: {'SKIP' if item['screenshots_skipped'] else ('PASS' if item['screenshots_ok'] else 'FAIL')} (sample: first / middle / last)",
                f"- content score: {item['content_score']}/10",
                f"- html score: {item['html_score']}/10",
                f"- html: `{item['html']}`",
                f"- pitch rehearsal: `{item['rehearsal']}`",
                f"- screenshots: `{item['screenshots']}`",
            ]
        )
        if item["content_notes"]:
            lines.append("- content notes: " + "; ".join(item["content_notes"]))
        if item["html_notes"]:
            lines.append("- html notes: " + "; ".join(item["html_notes"]))
        lines.append("")

    report.write_text("\n".join(lines), encoding="utf-8")
    print(report)

    failed = [
        i
        for i in summary
        if not (i["outline_ok"] and i["render_ok"] and i["check_ok"] and i["rehearsal_ok"] and i["screenshots_ok"])
    ]
    if failed:
        print(f"{len(failed)} round(s) need improvement", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
