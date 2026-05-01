from __future__ import annotations

import argparse
import ast
import json
from typing import Any

import database
from automation import create_task, disable_tasks, list_tasks
from check_prize import check_prize
from cron_manager import cron_status, install_cron, uninstall_cron
from fetch_draw import fetch_draw, manual_draw_input
from generate_numbers import generate, generate_plan
from manual_ticket import record_manual_tickets
from natural_language import parse_command
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
            user_platform_id=kwargs.get("user_platform_id", "wechat_self"),
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
            user_platform_id=kwargs.get("user_platform_id", "wechat_self"),
            issue=kwargs.get("issue"),
            draw_date=kwargs.get("draw_date"),
            is_purchased=bool(kwargs.get("is_purchased", True)),
            user_command=kwargs.get("user_command") or kwargs.get("text"),
        )
    if action == "parse_command":
        return parse_command(kwargs.get("text") or kwargs.get("payload") or "")
    if action == "create_automation":
        return create_task(
            action=kwargs.get("task_action") or kwargs.get("scheduled_action") or "generate",
            user_platform_id=kwargs.get("user_platform_id", "wechat_self"),
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
            payload=parse_json_arg(kwargs.get("payload")) or {},
            raw_text=kwargs.get("raw_text") or kwargs.get("text") or "",
        )
    if action == "list_automation":
        return list_tasks(kwargs.get("user_platform_id", "wechat_self"), include_disabled=bool(kwargs.get("include_disabled", False)))
    if action == "disable_automation":
        return disable_tasks(kwargs.get("user_platform_id", "wechat_self"), kwargs.get("task_id"), kwargs.get("task_action"))
    if action == "install_cron":
        return install_cron(confirm=bool(kwargs.get("confirm", False)))
    if action == "uninstall_cron":
        return uninstall_cron(confirm=bool(kwargs.get("confirm", False)))
    if action == "cron_status":
        return cron_status()
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
        return confirm_recent(kwargs.get("user_platform_id", "wechat_self"), int(kwargs.get("limit") or 20), parse_ticket_ids(kwargs.get("ticket_ids")))
    if action == "cancel_tickets":
        return cancel_recent(kwargs.get("user_platform_id", "wechat_self"), int(kwargs.get("limit") or 20), parse_ticket_ids(kwargs.get("ticket_ids")), kwargs.get("notes") or "")
    if action == "replace_last_batch":
        return replace_last_batch(
            kwargs.get("user_platform_id", "wechat_self"),
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
        return recent_tickets(kwargs.get("user_platform_id", "wechat_self"), int(kwargs.get("limit") or 10))
    if action == "record_ticket":
        return record_manual_tickets(
            kwargs.get("lottery_type", "dlt"),
            text=kwargs.get("text") or kwargs.get("payload"),
            play_type=kwargs.get("play_type"),
            issue=kwargs.get("issue"),
            draw_date=kwargs.get("draw_date"),
            multiple=int(kwargs.get("multiple") or 1),
            is_additional=bool(kwargs.get("is_additional", False)),
            user_platform_id=kwargs.get("user_platform_id", "wechat_self"),
            notes=kwargs.get("notes") or "",
        )
    if action == "update_config":
        return update_config(kwargs.get("config_name", "preferences"), parse_json_arg(kwargs.get("updates")) or {})
    if action == "status":
        database.init_db()
        return {"ok": True, "wechat_text": "lotto-Agent 正常，数据库已就绪。"}
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


def main() -> None:
    parser = argparse.ArgumentParser(description="lotto-Agent OpenClaw skill entry")
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
    parser.add_argument("--user-platform-id", default="wechat_self")
    parser.add_argument("--config-name", default="preferences")
    parser.add_argument("--updates")
    parser.add_argument("--payload")
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
    parser.add_argument("--wechat-text", action="store_true")
    args = parser.parse_args()
    kwargs = vars(args)
    action = kwargs.pop("action")
    result = dispatch(action, **kwargs)
    if args.wechat_text and result.get("wechat_text"):
        print(result["wechat_text"])
        for message in result.get("followup_messages") or []:
            print("\n---\n" + message)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
