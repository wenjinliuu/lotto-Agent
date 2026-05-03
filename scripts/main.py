from __future__ import annotations

import argparse
import ast
import json
import os
from typing import Any

import database
from automation import create_task, disable_tasks, list_tasks
from check_prize import check_prize
from cron_manager import cron_status, install_cron, uninstall_cron
from fetch_draw import fetch_draw, manual_draw_input
from generate_numbers import generate, generate_plan
from manual_ticket import record_manual_tickets
from natural_language import parse_command
from push_message import bind_notification_target, configure_notification, enable_notification, list_notification_targets, notification_status
from query_draw import query_draw_detail
from report import build_report
from scheduler import run_draw_check_prize, run_due
from ticket_manager import cancel_recent, confirm_recent, parse_ticket_ids, recent_tickets, replace_last_batch
from update_config import update_config
from utils import parse_json_arg


def dispatch(action: str, **kwargs: Any) -> dict[str, Any]:
    if action == "generate":
        return generate(
            kwargs.get("lottery_type", kwargs.get("lottery", "dlt")),
            count=int(kwargs.get("count") or 1),
            budget=kwargs.get("budget"),
            play_type=kwargs.get("play_type"),
            user_platform_id=kwargs.get("user_platform_id", "self"),
            issue=kwargs.get("issue"),
            draw_date=kwargs.get("draw_date"),
            multiple=int(kwargs.get("multiple") or 1),
            is_additional=kwargs.get("is_additional"),
            is_purchased=bool(kwargs.get("is_purchased", True)),
            user_command=kwargs.get("user_command") or kwargs.get("text"),
        )
    if action == "generate_plan":
        items = parse_items_arg(kwargs.get("items"))
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            return {"ok": False, "error": "generate_plan 的 items 必须是玩法对象列表"}
        if not items:
            return {"ok": False, "error": "generate_plan 缺少玩法 items"}
        return generate_plan(
            kwargs.get("lottery_type", "dlt"),
            items=items,
            user_platform_id=kwargs.get("user_platform_id", "self"),
            issue=kwargs.get("issue"),
            draw_date=kwargs.get("draw_date"),
            is_purchased=bool(kwargs.get("is_purchased", True)),
            user_command=kwargs.get("user_command") or kwargs.get("text"),
        )
    if action == "parse_command":
        return parse_command(kwargs.get("text") or kwargs.get("payload") or "")
    if action == "create_automation":
        automation_payload = build_automation_payload(kwargs)
        return create_task(
            action=kwargs.get("task_action") or kwargs.get("scheduled_action") or "generate",
            user_platform_id=kwargs.get("user_platform_id", "self"),
            lottery_type=kwargs.get("lottery_type"),
            play_type=kwargs.get("play_type"),
            schedule_type=kwargs.get("schedule_type", "recurring"),
            frequency=kwargs.get("frequency", "daily"),
            trigger_type=kwargs.get("trigger_type"),
            draw_day_offset=int(kwargs.get("draw_day_offset") or 0),
            run_date=kwargs.get("run_date"),
            weekdays=parse_json_arg(kwargs.get("weekdays")) or [],
            time_start=kwargs.get("time_start"),
            time_end=kwargs.get("time_end"),
            run_time_mode=kwargs.get("run_time_mode", "fixed"),
            notification_recipient=kwargs.get("notification_recipient") or kwargs.get("recipient"),
            delivery=build_delivery(kwargs),
            payload=automation_payload,
            raw_text=kwargs.get("raw_text") or kwargs.get("text") or "",
        )
    if action == "list_automation":
        return list_tasks(kwargs.get("user_platform_id", "self"), include_disabled=bool(kwargs.get("include_disabled", False)))
    if action == "disable_automation":
        return disable_tasks(kwargs.get("user_platform_id", "self"), kwargs.get("task_id"), kwargs.get("task_action"))
    if action == "install_cron":
        return install_cron(confirm=bool(kwargs.get("confirm", False)))
    if action == "uninstall_cron":
        return uninstall_cron(confirm=bool(kwargs.get("confirm", False)))
    if action == "cron_status":
        return cron_status()
    if action == "notification_status":
        return notification_status()
    if action == "list_notification_targets":
        return list_notification_targets()
    if action == "bind_notification_target":
        return bind_notification_target(
            provider=kwargs.get("provider") or "openclaw_cli",
            recipient=kwargs.get("recipient") or kwargs.get("user_platform_id", "self"),
            target=kwargs.get("target"),
            chat_id=kwargs.get("chat_id"),
            account_id=kwargs.get("account_id"),
            channel=kwargs.get("channel"),
            display_name=kwargs.get("display_name"),
            confirm=bool(kwargs.get("confirm", False)),
        )
    if action == "configure_notification":
        return configure_notification(
            provider=kwargs.get("provider") or "dry_run",
            recipient=kwargs.get("recipient") or kwargs.get("user_platform_id", "self"),
            target=kwargs.get("target"),
            chat_id=kwargs.get("chat_id"),
            account_id=kwargs.get("account_id"),
            channel=kwargs.get("channel"),
            confirm=bool(kwargs.get("confirm", False)),
        )
    if action == "enable_notification":
        return enable_notification(confirm=bool(kwargs.get("confirm", False)))
    if action == "fetch_draw":
        return fetch_draw(kwargs.get("lottery_type", "all"), issue=kwargs.get("issue"), source=kwargs.get("source"))
    if action == "draw_check_prize":
        return run_draw_check_prize(kwargs.get("lottery_type", "all"), kwargs.get("issue"), kwargs.get("user_platform_id"), quiet_empty=False)
    if action == "query_draw_detail":
        return query_draw_detail(
            kwargs.get("lottery_type"),
            kwargs.get("issue"),
            kwargs.get("prize_level"),
            latest=True,
            auto_fetch=bool(kwargs.get("auto_fetch", True)),
            source=kwargs.get("source"),
        )
    if action == "check_prize":
        return check_prize(kwargs.get("lottery_type"), kwargs.get("issue"), kwargs.get("user_platform_id"))
    if action == "report":
        return build_report(kwargs.get("report_type", "daily"), kwargs.get("user_platform_id"))
    if action == "confirm_purchase":
        return confirm_recent(kwargs.get("user_platform_id", "self"), int(kwargs.get("limit") or 20), parse_ticket_ids(kwargs.get("ticket_ids")))
    if action == "cancel_tickets":
        return cancel_recent(kwargs.get("user_platform_id", "self"), int(kwargs.get("limit") or 20), parse_ticket_ids(kwargs.get("ticket_ids")), kwargs.get("notes") or "")
    if action == "replace_last_batch":
        return replace_last_batch(
            kwargs.get("user_platform_id", "self"),
            {
                "lottery_type": kwargs.get("lottery_type"),
                "count": kwargs.get("count"),
                "budget": kwargs.get("budget"),
                "play_type": kwargs.get("play_type"),
                "issue": kwargs.get("issue"),
                "draw_date": kwargs.get("draw_date"),
                "multiple": kwargs.get("multiple"),
                "is_additional": kwargs.get("is_additional"),
                "is_purchased": kwargs.get("is_purchased"),
                "user_command": kwargs.get("text") or kwargs.get("payload"),
            },
        )
    if action == "recent_tickets":
        return recent_tickets(kwargs.get("user_platform_id", "self"), int(kwargs.get("limit") or 10))
    if action == "record_ticket":
        return record_manual_tickets(
            kwargs.get("lottery_type", "dlt"),
            text=kwargs.get("text") or kwargs.get("payload"),
            play_type=kwargs.get("play_type"),
            issue=kwargs.get("issue"),
            draw_date=kwargs.get("draw_date"),
            multiple=int(kwargs.get("multiple") or 1),
            is_additional=bool(kwargs.get("is_additional", False)),
            user_platform_id=kwargs.get("user_platform_id", "self"),
            notes=kwargs.get("notes") or "",
        )
    if action == "update_config":
        return update_config(kwargs.get("config_name", "preferences"), parse_json_arg(kwargs.get("updates")) or {})
    if action == "status":
        try:
            database.init_db()
        except OSError as exc:
            guidance = database_permission_guidance(str(database.DB_PATH.parent))
            return {
                "ok": False,
                "error": str(exc),
                "data_dir": str(database.DB_PATH.parent),
                "db_path": str(database.DB_PATH),
                "message_text": guidance,
            }
        return {"ok": True, "data_dir": str(database.DB_PATH.parent), "db_path": str(database.DB_PATH), "message_text": f"lotto-agent 正常，数据库已就绪：{database.DB_PATH}"}
    if action == "manual_draw_input":
        return manual_draw_input(kwargs["lottery_type"], parse_json_arg(kwargs.get("payload")) or {})
    if action == "schedule":
        return run_due(kwargs.get("job_name"), push=bool(kwargs.get("push", False)))
    return {"ok": False, "error": f"未知 action: {action}"}


def parse_items_arg(value: Any) -> Any:
    parsed = parse_json_arg(value)
    if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], str):
        parsed = parse_json_arg(parsed[0])
    if isinstance(parsed, str):
        try:
            parsed = ast.literal_eval(parsed)
        except (SyntaxError, ValueError):
            parsed = parse_json_arg(parsed)
    return parsed


def build_delivery(kwargs: dict[str, Any]) -> dict[str, str]:
    delivery_payload = parse_json_arg(kwargs.get("delivery"))
    if isinstance(delivery_payload, dict):
        return {
            key: value
            for key, value in {
                "channel": delivery_payload.get("channel") or delivery_payload.get("source"),
                "chat_id": delivery_payload.get("chat_id") or delivery_payload.get("to") or delivery_payload.get("target") or delivery_payload.get("delivery_to"),
                "account_id": delivery_payload.get("account_id") or delivery_payload.get("accountId") or delivery_payload.get("account"),
            }.items()
            if value
        }
    return {
        key: value
        for key, value in {
            "channel": kwargs.get("delivery_channel") or kwargs.get("channel"),
            "chat_id": kwargs.get("delivery_chat_id") or kwargs.get("delivery_to") or kwargs.get("chat_id") or kwargs.get("target"),
            "account_id": kwargs.get("delivery_account_id") or kwargs.get("account_id"),
        }.items()
        if value
    }


def build_automation_payload(kwargs: dict[str, Any]) -> dict[str, Any]:
    payload = parse_json_arg(kwargs.get("payload")) or {}
    if not isinstance(payload, dict):
        payload = {}
    action = kwargs.get("task_action") or kwargs.get("scheduled_action") or "generate"
    merge_if_present(payload, "lottery_type", kwargs.get("lottery_type"))
    merge_if_present(payload, "issue", kwargs.get("issue"))
    if action == "generate":
        merge_if_present(payload, "count", kwargs.get("count"))
        merge_if_present(payload, "budget", kwargs.get("budget"))
        merge_if_present(payload, "play_type", kwargs.get("play_type"))
        merge_if_present(payload, "draw_date", kwargs.get("draw_date"))
        merge_if_present(payload, "multiple", kwargs.get("multiple"))
        merge_if_present(payload, "is_additional", kwargs.get("is_additional"))
    if action == "report":
        merge_if_present(payload, "report_type", kwargs.get("report_type"))
    return payload


def merge_if_present(payload: dict[str, Any], key: str, value: Any) -> None:
    if key not in payload and value is not None:
        payload[key] = value


def database_permission_guidance(data_dir: str) -> str:
    if os.name == "nt":
        return (
            f"数据库目录不可写：{data_dir}\n"
            "默认目录应位于当前用户的 OpenClaw workspace 下：$HOME\\.openclaw\\workspace\\lotto-agent-data\n"
            "请确认运行 OpenClaw/计划任务的用户有权限创建并写入该目录，例如：\n"
            "New-Item -ItemType Directory -Force \"$HOME\\.openclaw\\workspace\\lotto-agent-data\"\n\n"
            "也可以把 LOTTO_AGENT_DATA_DIR 设置到另一个明确可写的位置：\n"
            "$env:LOTTO_AGENT_DATA_DIR=\"$HOME\\.openclaw\\workspace\\lotto-agent-data\"\n\n"
            "然后重新运行：python scripts/main.py status\n"
            "如果作为计划任务运行，也要在计划任务里设置同一个 LOTTO_AGENT_DATA_DIR。"
        )
    escaped = data_dir.replace("'", "'\"'\"'")
    export_line = 'export LOTTO_AGENT_DATA_DIR="$HOME/.openclaw/workspace/lotto-agent-data"'
    return (
        f"数据库目录不可写：{data_dir}\n"
        "默认目录应位于当前用户的 OpenClaw workspace 下：~/.openclaw/workspace/lotto-agent-data\n"
        "请确认运行 lotto-agent/OpenClaw/cron 的用户有权限创建并写入该目录。也可以显式设置：\n"
        f"{export_line}\n\n"
        "如果目录不能自动创建，请先创建并授权给运行 lotto-agent/OpenClaw 的系统用户：\n"
        f"sudo mkdir -p '{escaped}'\n"
        f"sudo chown -R $(whoami):$(whoami) '{escaped}'\n"
        f"sudo chmod 700 '{escaped}'\n\n"
        "然后重新运行：python scripts/main.py status"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="lotto-agent skill entry")
    parser.add_argument("action")
    parser.add_argument("--lottery-type", "--lottery", dest="lottery_type")
    parser.add_argument("--count", type=int)
    parser.add_argument("--budget", type=float)
    parser.add_argument("--play-type")
    parser.add_argument("--multiple", type=int, default=1)
    additional_group = parser.add_mutually_exclusive_group()
    additional_group.add_argument("--additional", dest="is_additional", action="store_true")
    additional_group.add_argument("--no-additional", dest="is_additional", action="store_false")
    parser.set_defaults(is_additional=None)
    parser.add_argument("--issue")
    parser.add_argument("--source")
    parser.add_argument("--prize-level")
    parser.add_argument("--no-auto-fetch", dest="auto_fetch", action="store_false")
    parser.set_defaults(auto_fetch=True)
    parser.add_argument("--preview", dest="is_purchased", action="store_false")
    parser.add_argument("--purchased", dest="is_purchased", action="store_true")
    parser.set_defaults(is_purchased=True)
    parser.add_argument("--draw-date")
    parser.add_argument("--report-type", default="daily")
    parser.add_argument("--user-platform-id", default="self")
    parser.add_argument("--provider")
    parser.add_argument("--recipient")
    parser.add_argument("--notification-recipient")
    parser.add_argument("--display-name")
    parser.add_argument("--target")
    parser.add_argument("--chat-id")
    parser.add_argument("--account-id")
    parser.add_argument("--channel")
    parser.add_argument("--config-name", default="preferences")
    parser.add_argument("--updates")
    parser.add_argument("--payload")
    parser.add_argument("--delivery")
    parser.add_argument("--delivery-channel")
    parser.add_argument("--delivery-chat-id")
    parser.add_argument("--delivery-to", dest="delivery_to")
    parser.add_argument("--delivery-account-id")
    parser.add_argument("--items")
    parser.add_argument("--task-action")
    parser.add_argument("--scheduled-action")
    parser.add_argument("--schedule-type", default="recurring")
    parser.add_argument("--frequency", default="daily")
    parser.add_argument("--trigger-type")
    parser.add_argument("--draw-day-offset", type=int, default=0)
    parser.add_argument("--run-date")
    parser.add_argument("--weekdays")
    parser.add_argument("--time-start")
    parser.add_argument("--time-end")
    parser.add_argument("--run-time-mode", default="fixed")
    parser.add_argument("--raw-text")
    parser.add_argument("--task-id", type=int)
    parser.add_argument("--include-disabled", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--text")
    parser.add_argument("--ticket-ids")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--notes")
    parser.add_argument("--job-name")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--message-text", action="store_true")
    args = parser.parse_args()
    kwargs = vars(args)
    action = kwargs.pop("action")
    result = dispatch(action, **kwargs)
    if args.message_text and result.get("message_text"):
        print(result["message_text"])
        for message in result.get("followup_messages") or []:
            print("\n---\n" + message)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
