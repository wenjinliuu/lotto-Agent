from __future__ import annotations

import json
from typing import Any

import database
from cron_manager import cron_status
from push_message import notification_status
from utils import CONFIG_DIR, load_json, now_iso


def add_purchase_onboarding(result: dict[str, Any], user_platform_id: str = "self") -> dict[str, Any]:
    if not result.get("ok"):
        return result
    if not has_purchased_ticket_result(result):
        return result
    gaps = automation_gaps(user_platform_id)
    if not gaps:
        return result
    key = f"purchase_onboarding_shown:{user_platform_id}"
    if setting_enabled(key):
        return result
    message = render_purchase_onboarding(gaps)
    messages = list(result.get("followup_messages") or [])
    if message not in messages:
        messages.append(message)
    result["followup_messages"] = messages
    result.setdefault("followup_text", message)
    contexts = list(result.get("followup_contexts") or [])
    contexts.append(
        {
            "event": "purchase_onboarding",
            "event_description": "首次已购买号码后的自动兑奖与消息推送引导",
            "facts": gaps,
            "fallback_text": message,
            "freedom": "medium",
            "style": {
                "tone": "直接、简短、像聊天里顺手提醒",
                "length": "1-2 short Chinese sentences",
                "avoid_template_feel": True,
            },
            "guardrails": [
                "不要承诺中奖，不要暗示提高中奖率。",
                "不要改动号码、期号、开奖日期、金额或购买状态。",
                "只引导用户确认配置，不要声称已经替用户开启。",
            ],
            "strict_facts": sorted(gaps),
            "seed": key,
        }
    )
    result["followup_contexts"] = contexts
    set_setting(key, {"shown_at": now_iso(), "gaps": gaps})
    return result


def has_purchased_ticket_result(result: dict[str, Any]) -> bool:
    tickets = result.get("tickets")
    if isinstance(tickets, list) and any(ticket.get("is_purchased") for ticket in tickets):
        return True
    if result.get("purchased_confirmed"):
        return int(result.get("updated_count") or 0) > 0
    return int(result.get("updated_count") or 0) > 0 and "已购买" in str(result.get("message_text") or "")


def automation_gaps(user_platform_id: str) -> dict[str, Any]:
    gaps: dict[str, Any] = {}
    if not has_prize_automation(user_platform_id):
        gaps["missing_prize_automation"] = True
    cron = cron_status()
    if not cron.get("installed"):
        gaps["missing_cron"] = True
    notify = notification_status()
    if not notify.get("enabled"):
        gaps["missing_notification"] = True
        gaps["notification_provider"] = notify.get("provider")
        gaps["notification_configured"] = bool(notify.get("configured"))
    return gaps


def has_prize_automation(user_platform_id: str) -> bool:
    schedule = load_json(CONFIG_DIR / "schedule.json", {})
    for job in schedule.get("jobs", []):
        if job.get("enabled") and job.get("action") in {"check_prize", "draw_check_prize"}:
            return True
    database.init_db()
    rows = database.fetch_all(
        """
        SELECT t.id
        FROM scheduled_tasks t LEFT JOIN users u ON u.id = t.user_id
        WHERE t.enabled = 1
          AND t.action IN ('check_prize', 'draw_check_prize')
          AND (u.platform_user_id = ? OR ? = '')
        LIMIT 1
        """,
        (user_platform_id, user_platform_id),
    )
    return bool(rows)


def render_purchase_onboarding(gaps: dict[str, Any]) -> str:
    parts = []
    if gaps.get("missing_prize_automation"):
        parts.append("还可以开启“每期开奖后自动兑奖并告诉我”。")
    if gaps.get("missing_cron"):
        parts.append("要让它按时运行，回复“确认开启自动化”。")
    if gaps.get("missing_notification"):
        parts.append("要主动收到结果，还需要配置消息推送并回复“确认开启消息推送”。")
    return " ".join(parts)


def setting_enabled(key: str) -> bool:
    database.init_db()
    rows = database.fetch_all("SELECT value_json FROM settings WHERE key = ? LIMIT 1", (key,))
    return bool(rows)


def set_setting(key: str, value: dict[str, Any]) -> None:
    database.init_db()
    with database.connect() as conn:
        conn.execute(
            """
            INSERT INTO settings(key, value_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
            """,
            (key, json.dumps(value, ensure_ascii=False), now_iso()),
        )
        conn.commit()
