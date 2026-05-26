#!/usr/bin/env python3
"""Feishu bot MVP for the deck generator.

The bot consumes `im.message.receive_v1` events with lark-cli, asks for missing
high-value brief fields, then calls the local generator wrapper and replies
with status / preview / edit / download links.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import request

import generator


REPO = Path(__file__).resolve().parents[1]
STATE_PATH = Path(os.environ.get("FEISHU_DECK_BOT_STATE", REPO / "runs/feishu-bot-state.json"))
DEFAULT_BASE_URL = os.environ.get("GENERATOR_PUBLIC_BASE_URL", "http://127.0.0.1:8765")
EVENT_KEY = "im.message.receive_v1"


BRIEF_FIELDS: list[tuple[str, str, str]] = [
    ("customer_name", "客户名", "客户是谁,是否需要使用客户 logo 或已有案例?"),
    ("industry", "行业", "客户所属行业和最关键的业务时刻是什么?"),
    ("audience", "目标受众", "这份 deck 讲给谁,他们要做什么决策?"),
    ("objective", "目标", "讲完后希望客户确认的下一步是什么?"),
    ("product_scope", "产品范围", "本次要重点讲哪些飞书产品或能力边界?"),
    ("attachments", "附件链接", "是否有可引用的附件、截图、客户材料或公开来源? 没有可写“无”。"),
]
OPTIONAL_BRIEF_KEYS = {"attachments"}

LABEL_ALIASES: dict[str, str] = {
    "标题": "title",
    "主题": "title",
    "brief": "title",
    "客户": "customer_name",
    "客户名": "customer_name",
    "公司": "customer_name",
    "行业": "industry",
    "受众": "audience",
    "听众": "audience",
    "对象": "audience",
    "目标受众": "audience",
    "目标": "objective",
    "目的": "objective",
    "成功指标": "success_metric",
    "成功标准": "success_metric",
    "业务时刻": "business_moment",
    "业务场景": "business_moment",
    "场景": "business_moment",
    "痛点": "core_tension",
    "问题": "core_tension",
    "核心矛盾": "core_tension",
    "产品": "product_scope",
    "产品范围": "product_scope",
    "能力": "product_scope",
    "附件": "attachments",
    "附件链接": "attachments",
    "链接": "attachments",
    "材料": "attachments",
}


@dataclass
class BotResult:
    reply: str
    task: dict[str, Any] | None = None
    asked_questions: list[str] | None = None


def load_state(path: Path = STATE_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"pending": {}, "processed": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(state: dict[str, Any], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def find_first(obj: Any, keys: set[str]) -> Any:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in keys and value not in (None, ""):
                return value
        for value in obj.values():
            found = find_first(value, keys)
            if found not in (None, ""):
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_first(item, keys)
            if found not in (None, ""):
                return found
    return None


def event_text(event: dict[str, Any]) -> str:
    value = find_first(event, {"content", "text", "message_content"})
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{"):
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                return stripped
            if isinstance(payload, dict):
                return str(payload.get("text") or payload.get("content") or stripped).strip()
        return stripped
    return ""


def event_message_id(event: dict[str, Any]) -> str:
    return str(find_first(event, {"message_id", "messageId"}) or "")


def event_conversation_key(event: dict[str, Any]) -> str:
    chat_id = find_first(event, {"chat_id", "chatId"}) or "unknown-chat"
    sender = find_first(event, {"sender_id", "senderId", "open_id", "openId"}) or "unknown-sender"
    return f"{chat_id}:{sender}"


def normalize_value(key: str, value: Any) -> Any:
    if value is None:
        return value
    if key == "product_scope":
        return generator.normalize_list(value)
    if key == "attachments":
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        urls = re.findall(r"https?://\S+", str(value))
        return urls or str(value).strip()
    return str(value).strip()


def parse_json_brief(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    brief = payload.get("brief") if isinstance(payload.get("brief"), dict) else payload
    return {key: normalize_value(key, value) for key, value in brief.items() if value not in (None, "")}


def parse_labeled_lines(text: str) -> dict[str, Any]:
    brief: dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip(" -\t")
        if not line:
            continue
        match = re.match(r"^([\w\u4e00-\u9fff ]{1,12})[:：]\s*(.+)$", line)
        if not match:
            continue
        label = match.group(1).strip().lower()
        value = match.group(2).strip()
        key = LABEL_ALIASES.get(label)
        if key:
            brief[key] = normalize_value(key, value)
    return brief


def infer_customer_name(text: str) -> str:
    patterns = [
        r"(?:给|为)(?P<name>[^，。,\n]{2,32}?)(?:做|生成|出|准备|制作)",
        r"(?:做|生成|出|准备|制作)一份(?P<name>[^，。,\n]{2,32}?)(?:的|关于)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        name = match.group("name").strip(" 的关于")
        if name:
            return name[:40]
    return ""


def parse_brief_text(text: str, existing: dict[str, Any] | None = None, pending_keys: list[str] | None = None) -> dict[str, Any]:
    brief = dict(existing or {})
    parsed = parse_json_brief(text) or {}
    parsed.update(parse_labeled_lines(text))

    urls = re.findall(r"https?://\S+", text)
    if urls and "attachments" not in parsed:
        parsed["attachments"] = urls

    if pending_keys and not parsed:
        lines = [line.strip(" -\t") for line in text.splitlines() if line.strip(" -\t")]
        for key, value in zip(pending_keys, lines):
            parsed[key] = normalize_value(key, value)

    if "title" not in brief and "title" not in parsed:
        first = next((line.strip() for line in text.splitlines() if line.strip()), "")
        if first:
            parsed["title"] = first[:80]

    if "customer_name" not in brief and "customer_name" not in parsed:
        inferred_customer = infer_customer_name(text)
        if inferred_customer:
            parsed["customer_name"] = inferred_customer

    for key, value in parsed.items():
        if value not in (None, "", []):
            brief[key] = value
    brief.setdefault("delivery_mode", "feishu-bot")
    return brief


def missing_fields(brief: dict[str, Any]) -> list[tuple[str, str, str]]:
    missing = []
    for key, label, question in BRIEF_FIELDS:
        if key in OPTIONAL_BRIEF_KEYS:
            continue
        value = brief.get(key)
        if value in (None, "", []):
            missing.append((key, label, question))
    return missing[:5]


def format_questions(missing: list[tuple[str, str, str]]) -> str:
    lines = ["我先补齐几个关键信息，再生成 deck："]
    for i, (_, label, question) in enumerate(missing, start=1):
        lines.append(f"{i}. {label}: {question}")
    lines.append("")
    lines.append("你可以直接按顺序逐行回答，也可以用“客户: xxx”这种格式。")
    return "\n".join(lines)


def format_task_reply(task: dict[str, Any]) -> str:
    artifacts = task.get("artifacts") or {}
    status_url = f"{artifacts.get('preview_url', '').rsplit('/files/', 1)[0]}/status" if artifacts.get("preview_url") else ""
    if task.get("status") != "succeeded":
        return "\n".join(
            [
                "生成失败了，我把原因记录在任务里了。",
                f"任务 ID: {task.get('id')}",
                f"失败原因: {task.get('error')}",
                f"状态页: {status_url}" if status_url else "",
            ]
        ).strip()

    return "\n".join(
        [
            "已生成飞书 H5 Deck 初稿。",
            f"任务 ID: {task['id']}",
            f"状态页: {status_url}",
            f"预览链接: {artifacts.get('preview_url', '')}",
            f"轻量编辑: {artifacts.get('preview_url', '').rsplit('/files/', 1)[0] + '/edit' if artifacts.get('preview_url') else ''}",
            f"下载包: {artifacts.get('download_url', '')}",
            "",
            "需要改标题、正文、客户名或页序时，打开轻量编辑链接保存，会生成新版本 URL。",
        ]
    )


def handle_message_text(
    text: str,
    state: dict[str, Any],
    *,
    conversation_key: str = "local",
    base_url: str = DEFAULT_BASE_URL,
) -> BotResult:
    pending = state.setdefault("pending", {})
    pending_item = pending.get(conversation_key) or {}
    brief = parse_brief_text(text, pending_item.get("brief"), pending_item.get("missing_keys"))
    missing = missing_fields(brief)
    if missing:
        pending[conversation_key] = {
            "brief": brief,
            "missing_keys": [key for key, _, _ in missing],
            "updated_at": time.time(),
        }
        questions = [question for _, _, question in missing]
        return BotResult(reply=format_questions(missing), asked_questions=questions)

    pending.pop(conversation_key, None)
    brief.setdefault("attachments", "无")
    task = generator.create_or_run_task({"brief": brief}, base_url=base_url)
    return BotResult(reply=format_task_reply(task), task=task)


def reply_to_message(message_id: str, text: str, *, dry_run: bool = False) -> None:
    if dry_run:
        print(f"DRY-RUN reply to {message_id}:\n{text}", file=sys.stderr)
        return
    argv = [
        "lark-cli",
        "im",
        "+messages-reply",
        "--message-id",
        message_id,
        "--text",
        text,
        "--as",
        "bot",
        "--idempotency-key",
        f"deckbot-{message_id}",
    ]
    proc = subprocess.run(argv, cwd=REPO, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)


def process_event(event: dict[str, Any], state: dict[str, Any], *, base_url: str, dry_run: bool) -> None:
    message_id = event_message_id(event)
    if not message_id:
        return
    processed = state.setdefault("processed", [])
    if message_id in processed:
        return
    text = event_text(event)
    if not text:
        return

    result = handle_message_text(text, state, conversation_key=event_conversation_key(event), base_url=base_url)
    reply_to_message(message_id, result.reply, dry_run=dry_run)
    processed.append(message_id)
    del processed[:-200]
    save_state(state)


def stream_stderr(pipe: Any) -> None:
    for line in pipe:
        sys.stderr.write(line)


def consume_events(args: argparse.Namespace) -> int:
    argv = ["lark-cli", "event", "consume", EVENT_KEY, "--as", "bot"]
    if args.max_events:
        argv.extend(["--max-events", str(args.max_events)])
    if args.timeout:
        argv.extend(["--timeout", args.timeout])
    proc = subprocess.Popen(
        argv,
        cwd=REPO,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    assert proc.stdout is not None
    assert proc.stderr is not None
    threading.Thread(target=stream_stderr, args=(proc.stderr,), daemon=True).start()
    state = load_state()
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                sys.stderr.write(f"[bot] skipped non-json event: {line[:120]}\n")
                continue
            try:
                process_event(event, state, base_url=args.base_url, dry_run=args.dry_run)
            except Exception as exc:  # noqa: BLE001 - keep the long-running bot alive.
                sys.stderr.write(f"[bot] event failed: {exc}\n")
                save_state(state)
    finally:
        save_state(state)
        if proc.stdin:
            proc.stdin.close()
    return proc.wait()


def doctor_payload(base_url: str, *, require_generator: bool = False, require_public_url: bool = False) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    lark_cli = shutil.which("lark-cli")
    checks.append({"name": "lark-cli", "ok": bool(lark_cli), "value": lark_cli or ""})

    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        probe = STATE_PATH.parent / ".feishu-bot-state.probe"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
        state_ok = True
        state_error = ""
    except Exception as exc:  # noqa: BLE001
        state_ok = False
        state_error = str(exc)
    checks.append({"name": "state-writable", "ok": state_ok, "path": str(STATE_PATH), "error": state_error})

    public_like = not re.search(r"//(?:127\.0\.0\.1|localhost)(?::\d+)?", base_url)
    checks.append(
        {
            "name": "public-base-url",
            "ok": public_like or not require_public_url,
            "ready": public_like,
            "value": base_url,
            "warning": "" if public_like else "飞书里返回 localhost 链接时,其他人无法打开。",
        }
    )

    generator_ok = False
    generator_error = ""
    try:
        with request.urlopen(base_url.rstrip("/") + "/health", timeout=3) as resp:
            generator_ok = 200 <= resp.status < 300
    except Exception as exc:  # noqa: BLE001
        generator_error = str(exc)
        curl = shutil.which("curl")
        if curl:
            proc = subprocess.run(
                [curl, "-fsS", base_url.rstrip("/") + "/health"],
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=5,
            )
            generator_ok = proc.returncode == 0
            if generator_ok:
                generator_error = ""
            elif proc.stderr:
                generator_error = proc.stderr.strip()
    checks.append({"name": "generator-health", "ok": generator_ok or not require_generator, "reachable": generator_ok, "error": generator_error})

    return {"ok": all(item["ok"] for item in checks), "checks": checks}


def cmd_handle_text(args: argparse.Namespace) -> int:
    state = load_state(args.state)
    result = handle_message_text(args.text, state, conversation_key=args.conversation_key, base_url=args.base_url)
    save_state(state, args.state)
    print(result.reply)
    return 0 if not result.task or result.task.get("status") == "succeeded" else 1


def cmd_doctor(args: argparse.Namespace) -> int:
    payload = doctor_payload(
        args.base_url,
        require_generator=args.require_generator,
        require_public_url=args.require_public_url,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="consume Feishu IM receive events and reply as bot")
    serve.add_argument("--base-url", default=DEFAULT_BASE_URL, help="public generator base URL used in replies")
    serve.add_argument("--max-events", type=int, default=0)
    serve.add_argument("--timeout", default="")
    serve.add_argument("--dry-run", action="store_true", help="print replies instead of sending them")
    serve.set_defaults(func=consume_events)

    handle = sub.add_parser("handle-text", help="local harness for one text message")
    handle.add_argument("text")
    handle.add_argument("--conversation-key", default="local")
    handle.add_argument("--base-url", default=DEFAULT_BASE_URL)
    handle.add_argument("--state", type=Path, default=STATE_PATH)
    handle.set_defaults(func=cmd_handle_text)

    doctor = sub.add_parser("doctor", help="check Feishu bot runtime prerequisites")
    doctor.add_argument("--base-url", default=DEFAULT_BASE_URL)
    doctor.add_argument("--require-generator", action="store_true", help="fail if generator /health is unreachable")
    doctor.add_argument("--require-public-url", action="store_true", help="fail if base URL is localhost")
    doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
