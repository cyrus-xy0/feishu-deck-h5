#!/usr/bin/env python3
"""Generate a first-pass pitch rehearsal from deck outline / DeckJSON.

The script is intentionally heuristic and offline. It creates a structured
starting point that an agent can refine with richer reasoning, not a substitute
for real customer research.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

MEETING_TYPES = {
    "first-meeting",
    "solution-pitch",
    "poc-kickoff",
    "renewal",
    "investor-pitch",
    "internal-alignment",
    "review",
    "unknown",
}

MEETING_TYPE_ALIASES = {
    "首访": "first-meeting",
    "首次沟通": "first-meeting",
    "方案介绍": "solution-pitch",
    "解决方案提案": "solution-pitch",
    "POC 启动提案": "poc-kickoff",
    "POC启动提案": "poc-kickoff",
    "poc 启动": "poc-kickoff",
    "试点启动": "poc-kickoff",
    "续约": "renewal",
    "融资": "investor-pitch",
    "投资人路演": "investor-pitch",
    "内部对齐": "internal-alignment",
    "复盘": "review",
    "未知": "unknown",
}


def load_json(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_meeting_type(value: str | None) -> str:
    raw = (value or "solution-pitch").strip()
    if raw in MEETING_TYPES:
        return raw
    return MEETING_TYPE_ALIASES.get(raw, "unknown")


def clamp(value: int) -> int:
    return max(0, min(100, value))


def text_join(values: list[str] | None) -> str:
    return "；".join(v for v in (values or []) if v)


def ensure_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return text_join([ensure_text(item) for item in value])
    if isinstance(value, dict):
        return text_join([f"{key}: {ensure_text(item)}" for key, item in value.items() if ensure_text(item)])
    return str(value).strip()


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [ensure_text(item) for item in value if ensure_text(item)]
    text = ensure_text(value)
    return [text] if text else []


def extract_scenario(raw: dict[str, Any]) -> dict[str, Any]:
    if not raw:
        return {}
    scenario = raw.get("scenario") if isinstance(raw.get("scenario"), dict) else raw
    if not isinstance(scenario, dict):
        return {}
    return scenario


def load_scenario(args: argparse.Namespace, outline: dict[str, Any]) -> tuple[dict[str, Any], Path | None]:
    if args.scenario:
        return extract_scenario(load_json(args.scenario)), args.scenario
    if args.outline:
        for name in ("scenario.json", "Scenario.json"):
            candidate = args.outline.parent / name
            if candidate.exists():
                return extract_scenario(load_json(candidate)), candidate
    return extract_scenario(outline.get("scenario", {})), None


def scenario_context(scenario: dict[str, Any]) -> str:
    parts = [
        ("场景", scenario.get("setting")),
        ("决策", scenario.get("decision")),
        ("语言", scenario.get("language")),
        ("风险级别", scenario.get("risk_level") or scenario.get("risk")),
        ("证明要求", scenario.get("proof_requirements") or scenario.get("proof")),
        ("来源摘要", scenario.get("source_summary")),
    ]
    return "；".join(f"{label}: {ensure_text(value)}" for label, value in parts if ensure_text(value))


def infer_meeting_type(args_value: str | None, scenario: dict[str, Any]) -> str:
    if args_value:
        return normalize_meeting_type(args_value)
    text = ensure_text(
        [
            scenario.get("goal"),
            scenario.get("decision"),
            scenario.get("setting"),
            scenario.get("audience"),
        ]
    )
    if not text:
        return "solution-pitch"
    if "poc" in text.lower() or "试点" in text:
        return "poc-kickoff"
    for alias, meeting_type in MEETING_TYPE_ALIASES.items():
        if alias.lower() in text.lower():
            return meeting_type
    if "续约" in text:
        return "renewal"
    if "融资" in text or "投资人" in text:
        return "investor-pitch"
    if "复盘" in text:
        return "review"
    if "内部" in text or "对齐" in text:
        return "internal-alignment"
    if "首次" in text or "首访" in text:
        return "first-meeting"
    return "solution-pitch"


def outline_slides(outline: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(outline.get("slides"), list):
        return list(outline.get("slides") or [])
    return list(outline.get("outline", {}).get("slides", []) or [])


def deck_slide_index(deck: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for i, slide in enumerate(deck.get("slides", []) or [], 1):
        key = slide.get("key") or slide.get("slide_key") or f"slide-{i:02d}"
        index[key] = slide
    return index


def normalize_slides(outline: dict[str, Any], deck: dict[str, Any]) -> list[dict[str, Any]]:
    slides = outline_slides(outline)
    deck_index = deck_slide_index(deck)
    if slides:
        normalized = []
        for i, slide in enumerate(slides, 1):
            key = slide.get("key") or f"slide-{i:02d}"
            deck_slide = deck_index.get(key, {})
            normalized.append(
                {
                    "key": key,
                    "title": slide.get("title") or deck_slide.get("title") or key,
                    "role": slide.get("role") or slide.get("layout_intent") or deck_slide.get("layout") or "content",
                    "message": slide.get("message")
                    or slide.get("single_focus")
                    or ensure_text(slide.get("content"))
                    or text_join(slide.get("content_beats"))
                    or "",
                    "content_beats": slide.get("content_beats") or as_list(slide.get("content")),
                    "evidence": as_list(slide.get("evidence")),
                    "risk_flags": as_list(slide.get("risk_flags") or slide.get("risks")),
                    "assets": slide.get("assets") or slide.get("assets_needed") or [],
                }
            )
        return normalized

    normalized = []
    for i, slide in enumerate(deck.get("slides", []) or [], 1):
        key = slide.get("key") or slide.get("slide_key") or f"slide-{i:02d}"
        title = slide.get("title") or slide.get("headline") or key
        normalized.append(
            {
                "key": key,
                "title": title,
                "role": slide.get("layout") or "content",
                "message": slide.get("subtitle") or slide.get("message") or "",
                "content_beats": [],
                "evidence": [],
                "risk_flags": [],
                "assets": [],
            }
        )
    return normalized


def default_panel(audience: str) -> list[dict[str, Any]]:
    audience_label = audience or "目标客户团队"
    return [
        {
            "id": "decision-owner",
            "role": f"{audience_label}中的业务决策者",
            "agenda": "判断这件事是否值得推进,以及下一步是否需要投入团队时间。",
            "success_criteria": ["业务问题被说清楚", "下一步范围和风险可控", "能看到可验证的价值路径"],
            "likely_objections": ["这是否是现有工具的包装", "为什么现在必须做", "试点投入是否可控"],
        },
        {
            "id": "internal-champion",
            "role": "内部推动者",
            "agenda": "寻找能带回组织内部继续推动的清晰话术、证据和试点抓手。",
            "success_criteria": ["有一句话主张", "有可复述的场景", "有明确试点清单"],
            "likely_objections": ["哪些材料可以发给内部", "能否快速做一个小范围试点"],
        },
        {
            "id": "frontline-owner",
            "role": "实际使用 / 运营负责人",
            "agenda": "确认方案是否真的减轻一线负担,而不是增加新系统和新流程。",
            "success_criteria": ["入口简单", "动作闭环清楚", "异常处理和责任边界清楚"],
            "likely_objections": ["一线会不会不用", "日常操作是否更复杂", "谁来维护知识和流程"],
        },
        {
            "id": "technical-evaluator",
            "role": "技术 / 实施评估者",
            "agenda": "判断集成、权限、数据安全和上线节奏是否可控。",
            "success_criteria": ["系统边界清楚", "数据来源清楚", "试点不依赖大规模改造"],
            "likely_objections": ["要接哪些系统", "权限如何控制", "上线周期是否被低估"],
        },
        {
            "id": "finance-procurement",
            "role": "财务 / 采购把关者",
            "agenda": "确认 ROI 口径、预算合理性和采购风险。",
            "success_criteria": ["指标口径明确", "预算前置风险低", "成功后扩展路径清楚"],
            "likely_objections": ["价值如何量化", "试点后怎么决定买不买", "是否已有替代方案"],
        },
    ]


def slide_questions(slide: dict[str, Any], scenario: dict[str, Any]) -> list[str]:
    role = slide["role"]
    evidence = slide["evidence"]
    risks = slide["risk_flags"]
    questions = []
    decision = ensure_text(scenario.get("decision"))
    proof_requirements = as_list(scenario.get("proof_requirements") or scenario.get("proof"))
    if role in {"pain", "context", "insight"}:
        questions.append("这个痛点在我们这里有多严重,有没有当前数据或样例?")
    if role in {"solution", "demo"}:
        questions.append("这套方案和我们现有系统怎么衔接,第一步要接什么?")
    if role in {"roadmap", "decision", "closing"}:
        questions.append("下一步需要我们投入谁、多少时间、准备哪些材料?")
    if decision:
        questions.append(f"这一页如何帮助我们做出“{decision}”这个决定?")
    if proof_requirements:
        questions.append(f"这页能不能满足证明要求: {proof_requirements[0]}?")
    if evidence or risks:
        questions.append("哪些判断是已经验证的,哪些还只是推断?")
    if not questions:
        questions.append("这一页和我们的业务目标有什么直接关系?")
    return questions[:3]


def slide_reaction(slide: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    title = slide["title"]
    role = slide["role"]
    message = slide["message"]
    evidence = slide["evidence"]
    risks = slide["risk_flags"]

    if role == "cover":
        reaction = "听众会快速判断这是不是为自己准备的场景,封面能建立主题但还不能形成信任。"
        positive = "如果客户名、行业场景和会议目标明确,内部推动者会更容易复述。"
        friction = "封面若只像通用方案,决策者会把后续内容当成标准宣讲。"
    elif role in {"pain", "context", "insight"}:
        reaction = "这一页决定听众是否认同问题定义。讲得准会提升紧迫感,讲得泛会被认为是供应商话术。"
        positive = "业务决策者和一线负责人会关注它是否命中当前卡点。"
        friction = "缺少客户自己的例子或公开证据时,容易被追问'这是不是你们假设的'。"
    elif role in {"solution", "demo"}:
        reaction = "这一页会把兴趣转成可行性判断。听众会从'听起来不错'转向问边界、集成和落地。"
        positive = "内部推动者能拿它解释方案全貌,技术评估者能看到系统边界。"
        friction = "如果 demo 多于业务闭环,财务和技术角色会怀疑这是展示而不是落地方案。"
    elif role in {"evidence", "case"}:
        reaction = "这一页承担信任建立任务,会直接影响是否愿意推进下一步。"
        positive = "有来源和适用边界的证据会显著降低决策者疑虑。"
        friction = "案例或数据若不可追溯,反而会损伤可信度。"
    elif role in {"roadmap", "decision", "closing"}:
        reaction = "这一页会把讨论从认知转向行动,关键是下一步是否低风险、可执行。"
        positive = "清晰的试点清单会让会议更容易收束到负责人和时间窗口。"
        friction = "如果 ask 太大或指标不清,客户可能会选择内部再看看。"
    else:
        reaction = "听众会根据这一页是否承接上一页来判断叙事是否连贯。"
        positive = "信息集中、角色关切明确时,能帮助继续推进。"
        friction = "如果信息只是罗列,会削弱会议节奏。"

    if risks:
        friction += f" 当前风险: {text_join(risks)}。"
    if evidence and any("需要" in item or "确认" in item for item in evidence):
        friction += " 这一页带有待补证据,讲述时要主动说明。"
    if scenario.get("risk_level") or scenario.get("risk"):
        friction += f" 本场 pitch 的风险级别是{ensure_text(scenario.get('risk_level') or scenario.get('risk'))},讲述时需要更早暴露假设边界。"
    if scenario.get("proof_requirements") or scenario.get("proof"):
        positive += f" 如果能对齐证明要求: {ensure_text(scenario.get('proof_requirements') or scenario.get('proof'))},更容易推进决策。"

    quote = f"模拟听众: '这页我听懂了,但我需要知道{slide_questions(slide, scenario)[0].rstrip('？?')}。'"
    revision = "保留核心信息,补一个客户可验证证据或把缺口改成会议问题。"
    if message and len(message) < 18:
        revision = "把 message 扩成可复述的一句话,说明这页为什么推动下一步。"

    return {
        "slide_key": slide["key"],
        "title": title,
        "reaction": reaction,
        "positive_signal": positive,
        "friction": friction,
        "likely_questions": slide_questions(slide, scenario),
        "simulated_quote": quote,
        "revision_hint": revision,
    }


def design_plan_of(outline: dict[str, Any]) -> dict[str, Any]:
    plan = outline.get("design_plan")
    return plan if isinstance(plan, dict) else {}


_NEEDS_CONFIRM_MARKERS = ("需要", "待确认", "待补", "确认", "未提供", "若用户", "可替换", "假设")


def pain_signals(outline: dict[str, Any], scenario: dict[str, Any], slides: list[dict[str, Any]]) -> list[str]:
    """Urgency driver. Designer contract has no `thesis.pain_points`; the
    closest real signals are the narrative tensions in `design_plan.risks`,
    any scenario-level pain fields, and slides whose role frames a problem."""
    plan = design_plan_of(outline)
    signals = as_list(plan.get("risks"))
    signals += as_list(scenario.get("pain_points") or scenario.get("pains"))
    signals += [
        ensure_text(slide.get("message")) or slide.get("title", "")
        for slide in slides
        if slide.get("role") in {"pain", "context", "insight"}
    ]
    return [s for s in signals if s]


def unsupported_claims(outline: dict[str, Any], slides: list[dict[str, Any]]) -> list[str]:
    """Trust drag. Contract has no `claim_discipline.unsupported_claims`; the
    real surface is per-slide evidence items flagged as needing confirmation
    plus the design_plan's open_questions."""
    flagged = [
        item
        for slide in slides
        for item in slide.get("evidence", [])
        if any(marker in item for marker in _NEEDS_CONFIRM_MARKERS)
    ]
    flagged += [
        q
        for q in as_list(design_plan_of(outline).get("open_questions"))
        if any(marker in q for marker in _NEEDS_CONFIRM_MARKERS)
    ]
    return flagged


def needs_confirmation(outline: dict[str, Any]) -> list[str]:
    """Next-step drag. Contract has no `claim_discipline.needs_user_confirmation`;
    open_questions in the design_plan are the real unresolved items that hold
    back a confident next-step ask."""
    return as_list(design_plan_of(outline).get("open_questions"))


def score_deck(outline: dict[str, Any], slides: list[dict[str, Any]], scenario: dict[str, Any]) -> dict[str, int]:
    pain_points = pain_signals(outline, scenario, slides)
    unsupported = unsupported_claims(outline, slides)
    confirmations = needs_confirmation(outline)
    evidence_items = [item for slide in slides for item in slide.get("evidence", [])]
    risk_items = [item for slide in slides for item in slide.get("risk_flags", [])]
    proof_requirements = as_list(scenario.get("proof_requirements") or scenario.get("proof"))
    decision = ensure_text(scenario.get("decision"))
    risk_level = ensure_text(scenario.get("risk_level") or scenario.get("risk"))

    clarity = 58 + min(len(slides), 8) * 4
    urgency = 50 + min(len(pain_points), 3) * 10
    trust = 62 + min(len(evidence_items), 5) * 3 - len(unsupported) * 4 - len(risk_items) * 2
    feasibility = 56 + sum(1 for slide in slides if slide["role"] in {"solution", "demo", "roadmap"}) * 7
    next_step = 50 + sum(1 for slide in slides if slide["role"] in {"roadmap", "decision", "closing"}) * 10
    if decision:
        next_step += 5
        clarity += 4
    if proof_requirements and not evidence_items:
        trust -= 8
    if risk_level in {"high", "高", "高风险"}:
        trust -= 5
        feasibility -= 4
    if confirmations:
        next_step -= min(len(confirmations) * 3, 12)
    return {
        "clarity": clamp(clarity),
        "urgency": clamp(urgency),
        "trust": clamp(trust),
        "feasibility": clamp(feasibility),
        "next_step_readiness": clamp(next_step),
    }


def outcome(scores: dict[str, int]) -> tuple[str, str, str]:
    average = sum(scores.values()) / len(scores)
    if scores["next_step_readiness"] >= 72 and scores["trust"] >= 65:
        return "advance-next-meeting", "medium", "这套 deck 已经能解释问题、方案和低风险下一步,最可能推进到下一次方案/试点讨论。"
    if scores["trust"] < 58:
        return "request-more-material", "medium", "听众可能认可方向,但会要求补证据、客户样例或 ROI 口径后再内部讨论。"
    if scores["feasibility"] < 58:
        return "internal-review", "low", "方案价值有吸引力,但实施边界不够清楚,客户大概率先拉技术/业务内部评估。"
    if average >= 68:
        return "internal-review", "medium", "整体叙事可推进,但还需要内部推动者把材料带回组织继续消化。"
    return "defer", "medium", "当前 deck 更像方向介绍,还不足以让客户承诺下一步资源。"


def build_rehearsal(args: argparse.Namespace) -> dict[str, Any]:
    outline = load_json(args.outline)
    deck = load_json(args.deck_json)
    scenario, scenario_path = load_scenario(args, outline)
    slides = normalize_slides(outline, deck)
    # `design_plan` is the real designer contract surface; `brief` is only a
    # legacy/back-compat fallback (the contract has no top-level `brief`).
    design_plan = design_plan_of(outline)
    brief = outline.get("brief") if isinstance(outline.get("brief"), dict) else {}
    scores = score_deck(outline, slides, scenario)
    primary_outcome, confidence, why = outcome(scores)
    artifacts = []
    if args.outline:
        artifacts.append(str(args.outline))
    if scenario_path:
        artifacts.append(str(scenario_path))
    if args.deck_json:
        artifacts.append(str(args.deck_json))
    if args.html:
        artifacts.append(str(args.html))
    if not artifacts:
        artifacts.append("manual-context")

    audience = args.audience or scenario.get("audience") or brief.get("audience") or "目标客户团队"
    objective = args.objective or scenario.get("goal") or brief.get("objective") or "推动客户确认下一步讨论"
    success_next_step = args.success_next_step or scenario.get("decision") or brief.get("success_metric") or "确认下一次会议、材料清单和负责人"
    title = args.title or brief.get("title") or design_plan.get("title") or deck.get("deck", {}).get("title") or "Pitch rehearsal"
    reactions = [slide_reaction(slide, scenario) for slide in slides]
    weakest = max(reactions, key=lambda item: len(item["friction"])) if reactions else {"slide_key": "deck-level", "title": "deck-level"}
    non_cover_reactions = [
        item
        for item in reactions
        if next((slide["role"] for slide in slides if slide["key"] == item["slide_key"]), "") != "cover"
    ]
    strongest_pool = non_cover_reactions or reactions
    strongest = max(strongest_pool, key=lambda item: len(item["positive_signal"])) if strongest_pool else {"slide_key": "deck-level", "title": "deck-level"}

    first_non_cover = next((slide["key"] for slide in slides if slide["role"] != "cover"), slides[0]["key"] if slides else "deck-level")
    closing_slide = slides[-1]["key"] if slides else "deck-level"
    personas = default_panel(audience)
    unsupported = unsupported_claims(outline, slides)
    confirmations = needs_confirmation(outline)

    return {
        "version": "1.0",
        "source": {
            "artifacts": artifacts,
            "assumptions": [
                "这是基于 deck 结构和受众角色的预演,不是客户真实反馈。",
                "未提供具体参会人时,使用通用购买委员会角色建模。",
                "已消费 designer scenario 来约束会议目标、受众、决策语境和证明要求。" if scenario else "未提供 designer scenario,使用 outline/brief 和通用 pitch 语境推断。",
            ],
            "limitations": [
                "没有真实客户访谈或会议录音输入。",
                "评分用于改稿排序,不代表真实成交概率。",
            ],
        },
        "meeting": {
            "title": title,
            "audience": audience,
            "objective": objective,
            "success_next_step": success_next_step,
            "meeting_type": infer_meeting_type(args.meeting_type, scenario),
            "known_context": text_join([args.context or brief.get("requester_context", ""), scenario_context(scenario)]),
        },
        "audience_panel": personas,
        "deck_arc": {
            "summary": outline.get("outline", {}).get("arc")
            or design_plan.get("narrative_arc")
            or "当前 deck 需要完成从问题定义到方案可信度再到下一步行动的转化。",
            "strongest_moment": f"{strongest['slide_key']} · {strongest['title']}",
            "weakest_moment": f"{weakest['slide_key']} · {weakest['title']}",
            "narrative_risk": f"如果证据和下一步 ask 不能支撑“{success_next_step}”,客户会把会议结果降级为内部再评估。",
            "scores": scores,
        },
        "slide_reactions": reactions,
        "objection_map": [
            {
                "persona_id": "decision-owner",
                "objection": "这件事是否真的足够重要,值得现在推进?",
                "trigger_slide_keys": [first_non_cover],
                "best_response": "用客户自己的业务时刻和一个可验证指标回答,不要只讲通用趋势。",
            },
            {
                "persona_id": "technical-evaluator",
                "objection": "集成、权限和数据边界是否被低估?",
                "trigger_slide_keys": [slide["key"] for slide in slides if slide["role"] in {"solution", "demo"}][:2] or [first_non_cover],
                "best_response": "把首期试点限定在最小系统边界,列出需要接入和暂不接入的系统。",
            },
            {
                "persona_id": "finance-procurement",
                "objection": "如何判断试点值得继续投入?",
                "trigger_slide_keys": [closing_slide],
                "best_response": "提前给出试点成功指标、复盘口径和扩展条件。",
            },
        ],
        "outcome_forecast": {
            "primary_outcome": primary_outcome,
            "confidence": confidence,
            "why": why,
            "conditions_to_improve": [
                "补一页客户当前流程或样例,让痛点从假设变成共同事实。",
                "把 closing ask 改成低风险试点清单:场景、负责人、素材、时间窗口。",
                "为技术/财务角色补充系统边界和指标口径。",
            ],
        },
        "revision_queue": [
            {
                "priority": "P0",
                "target": first_non_cover,
                "issue": "问题定义若缺少客户样例,会被认为是通用供应商话术。",
                "change": "补一个用户提供的流程、截图、SOP 或公开证据;没有证据时改成会议确认问题。",
                "owner": "evidence",
            },
            {
                "priority": "P0",
                "target": closing_slide,
                "issue": "下一步 ask 需要更具体,否则会议容易停在内部评估。",
                "change": "写清试点场景、材料清单、负责人和时间窗口。",
                "owner": "deck",
            },
            {
                "priority": "P1",
                "target": "deck-level",
                "issue": "不同角色的关切没有被显式回应。",
                "change": "讲述时分别回应业务价值、实施边界、一线使用和 ROI 口径。",
                "owner": "talk-track",
            },
        ],
        "talk_track": {
            "opening": "先声明本次不是完整方案宣讲,而是把一个业务闭环缩小到可试点、可验证的下一步。",
            "transition_notes": [
                "从痛点页转方案页时,用'所以我们不从工具开始,从动作闭环开始'承接。",
                "进入 demo 或架构页前,先说明首期边界,降低技术评估者的风险感。",
                "收束时不要泛泛说期待合作,直接落到试点材料和负责人。",
            ],
            "closing_ask": success_next_step,
            "do_not_say": [
                "不要承诺未验证的提升百分比。",
                "不要把模拟反馈说成客户真实反馈。",
                "不要用'全面赋能'替代具体试点动作。",
            ],
        },
        "claim_discipline": {
            "simulated_not_observed": True,
            "needs_confirmation": confirmations or ["实际参会角色、试点范围和成功指标需要用户确认。"],
            "unsafe_claims_to_remove": unsupported or ["任何未提供来源的客户效果数字都应删除或改为待验证假设。"],
        },
    }


def write_markdown(path: Path, data: dict[str, Any]) -> None:
    lines = [
        "# Pitch Rehearsal",
        "",
        f"**Verdict:** {data['outcome_forecast']['primary_outcome']} ({data['outcome_forecast']['confidence']})",
        "",
        f"**Why:** {data['outcome_forecast']['why']}",
        "",
        "## Scores",
        "",
    ]
    for key, value in data["deck_arc"]["scores"].items():
        lines.append(f"- {key}: {value}/100")
    lines.extend(["", "## Audience Panel", ""])
    for persona in data["audience_panel"]:
        lines.append(f"- **{persona['role']}**: {persona['agenda']}")
    lines.extend(["", "## Slide Reactions", ""])
    for reaction in data["slide_reactions"]:
        lines.extend(
            [
                f"### {reaction['slide_key']} · {reaction['title']}",
                "",
                f"- Reaction: {reaction['reaction']}",
                f"- Positive signal: {reaction['positive_signal']}",
                f"- Friction: {reaction['friction']}",
                f"- Simulated quote: {reaction['simulated_quote']}",
                f"- Revision: {reaction['revision_hint']}",
                "",
            ]
        )
    lines.extend(["## Revision Queue", ""])
    for item in data["revision_queue"]:
        lines.append(f"- **{item['priority']} · {item['target']}** [{item['owner']}] {item['change']}")
    lines.extend(["", "## Claim Discipline", "", "- This is a simulated rehearsal, not observed customer feedback."])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outline", type=Path, help="Path to deck-designer outline JSON")
    parser.add_argument("--deck-json", type=Path, help="Path to DeckJSON source")
    parser.add_argument("--html", type=Path, help="Path to rendered HTML deck, recorded as source context")
    parser.add_argument("--scenario", type=Path, help="Path to designer Scenario JSON, if written separately from outline.json")
    parser.add_argument("--out-json", type=Path, required=True, help="Where to write pitch-rehearsal.json")
    parser.add_argument("--out-md", type=Path, help="Where to write PITCH_REHEARSAL.md")
    parser.add_argument("--title")
    parser.add_argument("--audience")
    parser.add_argument("--objective")
    parser.add_argument("--success-next-step")
    parser.add_argument(
        "--meeting-type",
        choices=sorted(MEETING_TYPES | set(MEETING_TYPE_ALIASES)),
    )
    parser.add_argument("--context", default="")
    args = parser.parse_args(argv)

    data = build_rehearsal(args)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.out_md:
        write_markdown(args.out_md, data)
    print(f"Wrote {args.out_json}")
    if args.out_md:
        print(f"Wrote {args.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
