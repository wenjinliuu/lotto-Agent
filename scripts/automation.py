from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import database
from cron_manager import cron_status
from followup import add as add_followup
from utils import CONFIG_DIR, load_json, normalize_lottery_type, now_iso


RULES = load_json(CONFIG_DIR / "lottery_rules.json", {})
CN_TZ = timezone(timedelta(hours=8))


def create_task(
    action: str,
    user_platform_id: str = "wechat_self",
    lottery_type: str | None = None,
    play_type: str | None = None,
    schedule_type: str = "recurring",
    frequency: str | None = "daily",
    trigger_type: str | None = None,
    draw_day_offset: int = 0,
    run_date: str | None = None,
    weekdays: list[int] | None = None,
    time_start: str | None = None,
    time_end: str | None = None,
    run_time_mode: str = "fixed",
    payload: dict[str, Any] | None = None,
    raw_text: str = "",
    source: str = "wechat",
) -> dict[str, Any]:
    database.init_db()
    key = normalize_lottery_type(lottery_type, RULES) if lottery_type else None
    user_id = database.ensure_user(user_platform_id)
    payload = payload or {}
    if key:
        payload.setdefault("lottery_type", key)
    if play_type:
        payload.setdefault("play_type", play_type)
    time_start = time_start or "09:00"
    time_end = time_end or time_start
    with database.connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO scheduled_tasks(user_id, task_name, action, lottery_type, play_type, payload_json, schedule_type, frequency, trigger_type, draw_day_offset, run_date, weekdays_json, time_start, time_end, run_time_mode, enabled, source, raw_text, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
            """,
            (
                user_id,
                task_name(action, key, payload),
                action,
                key,
                play_type,
                json.dumps(payload, ensure_ascii=False),
                schedule_type,
                frequency,
                trigger_type,
                int(draw_day_offset or 0),
                run_date,
                json.dumps(weekdays or [], ensure_ascii=False),
                time_start,
                time_end,
                normalize_run_time_mode(run_time_mode),
                source,
                raw_text,
                now_iso(),
            ),
        )
        conn.commit()
        task_id = int(cursor.lastrowid)
    text = render_created_task(task_id, action, key, payload, schedule_type, frequency, run_date, weekdays, time_start, time_end, trigger_type, draw_day_offset)
    status = cron_status()
    if not status.get("installed"):
        text += "\n\n自动化唤醒器还没开启。回复“确认开启自动化”后，我会帮你安装每5分钟检查一次的服务器任务。"
    result = {"ok": True, "task_id": task_id, "cron_installed": status.get("installed", False), "wechat_text": text}
    add_followup(result, "automation_created", task_id)
    if not status.get("installed"):
        add_followup(result, "cron_needed", task_id)
    return result


def list_tasks(user_platform_id: str = "wechat_self", include_disabled: bool = False) -> dict[str, Any]:
    database.init_db()
    rows = database.fetch_all(
        """
        SELECT t.*
        FROM scheduled_tasks t LEFT JOIN users u ON u.id = t.user_id
        WHERE (u.platform_user_id = ? OR ? = '')
          AND (? = 1 OR t.enabled = 1)
        ORDER BY t.id DESC
        LIMIT 30
        """,
        (user_platform_id, user_platform_id, int(include_disabled)),
    )
    if not rows:
        return {"ok": True, "tasks": [], "wechat_text": "当前没有自动任务。"}
    lines = ["自动任务"]
    for row in rows:
        lines.append(render_task_line(row))
    status = cron_status()
    if not status.get("installed"):
        lines.append("")
        lines.append("自动化唤醒器未开启，回复“确认开启自动化”即可安装。")
    return {"ok": True, "tasks": rows, "cron_installed": status.get("installed", False), "wechat_text": "\n".join(lines)}


def disable_tasks(user_platform_id: str = "wechat_self", task_id: int | None = None, action: str | None = None) -> dict[str, Any]:
    database.init_db()
    params: list[Any] = [user_platform_id, user_platform_id]
    where = ["(u.platform_user_id = ? OR ? = '')", "t.enabled = 1"]
    if task_id:
        where.append("t.id = ?")
        params.append(task_id)
    if action:
        where.append("t.action = ?")
        params.append(action)
    with database.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT t.id
            FROM scheduled_tasks t LEFT JOIN users u ON u.id = t.user_id
            WHERE {' AND '.join(where)}
            """,
            params,
        ).fetchall()
        ids = [int(row["id"]) for row in rows]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            conn.execute(f"UPDATE scheduled_tasks SET enabled = 0, updated_at = ? WHERE id IN ({placeholders})", [now_iso(), *ids])
        conn.commit()
    result = {"ok": True, "disabled_count": len(ids), "wechat_text": f"已停用 {len(ids)} 个自动任务。"}
    add_followup(result, "cancel", f"automation:{len(ids)}")
    return result


def task_name(action: str, lottery_type: str | None, payload: dict[str, Any]) -> str:
    if action == "generate":
        name = RULES.get("lotteries", {}).get(lottery_type or "", {}).get("name", lottery_type or "默认彩种")
        return f"自动生成{name}{payload.get('count', 1)}注"
    if action == "draw_check_prize":
        return "开奖后自动抓取并兑奖"
    if action == "check_prize":
        return "自动兑奖"
    if action == "fetch_draw":
        return "自动抓开奖"
    if action == "report":
        return f"自动{payload.get('report_type', 'weekly')}报告"
    return action


def render_created_task(task_id: int, action: str, lottery_type: str | None, payload: dict[str, Any], schedule_type: str, frequency: str | None, run_date: str | None, weekdays: list[int] | None, time_start: str, time_end: str, trigger_type: str | None = None, draw_day_offset: int = 0) -> str:
    lines = [f"已创建自动任务 #{task_id}"]
    lines.append(render_schedule(schedule_type, frequency, run_date, weekdays, time_start, time_end, trigger_type, draw_day_offset))
    lines.append(render_action(action, lottery_type, payload))
    return "\n".join(lines)


def render_task_line(row: dict[str, Any]) -> str:
    payload = parse_payload(row.get("payload_json"))
    return f"#{row['id']} {render_schedule(row.get('schedule_type'), row.get('frequency'), row.get('run_date'), parse_weekdays(row.get('weekdays_json')), row.get('time_start'), row.get('time_end'), row.get('trigger_type'), int(row.get('draw_day_offset') or 0))}｜{render_action(row.get('action'), row.get('lottery_type'), payload)}"


def render_schedule(schedule_type: str | None, frequency: str | None, run_date: str | None, weekdays: list[int] | None, time_start: str | None, time_end: str | None, trigger_type: str | None = None, draw_day_offset: int = 0) -> str:
    window = time_start or "09:00"
    if time_end and time_end != time_start:
        window = f"{time_start}-{time_end}"
    if trigger_type == "draw_day":
        prefix = "开奖日当天" if int(draw_day_offset or 0) == 0 else f"开奖日前{abs(int(draw_day_offset))}天"
        return f"{prefix} {window}"
    if schedule_type == "once":
        return f"{run_date or '指定日期'} {window}"
    if frequency == "weekly":
        return f"每周{''.join(weekday_label(day) for day in weekdays or [])} {window}"
    return f"每天 {window}"


def render_action(action: str | None, lottery_type: str | None, payload: dict[str, Any]) -> str:
    if action == "generate":
        name = RULES.get("lotteries", {}).get(lottery_type or payload.get("lottery_type", ""), {}).get("name", lottery_type or "默认彩种")
        parts = [f"{name}{int(payload.get('count', 1))}注"]
        if payload.get("play_type") and payload.get("play_type") != "standard":
            parts.append(f"玩法{payload['play_type']}")
        if int(payload.get("multiple", 1)) > 1:
            parts.append(f"{payload['multiple']}倍")
        if payload.get("is_additional"):
            parts.append("追加")
        return "生成" + "｜".join(parts)
    if action == "draw_check_prize":
        return "抓开奖并自动兑奖"
    if action == "check_prize":
        return "自动兑奖"
    if action == "fetch_draw":
        return "抓取开奖"
    if action == "report":
        return f"生成{payload.get('report_type', 'weekly')}报告"
    return str(action or "")


def parse_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def parse_weekdays(value: Any) -> list[int]:
    if isinstance(value, list):
        return [int(item) for item in value]
    try:
        parsed = json.loads(value or "[]")
        return [int(item) for item in parsed]
    except (TypeError, ValueError, json.JSONDecodeError):
        return []


def weekday_label(day: int) -> str:
    return {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "日"}.get(int(day), str(day))


def cn_now() -> datetime:
    return datetime.now(CN_TZ)


def valid_time(value: str) -> bool:
    return re.fullmatch(r"\d{2}:\d{2}", str(value or "")) is not None


def normalize_run_time_mode(value: str | None) -> str:
    return "random_once_in_window" if value == "random_once_in_window" else "fixed"
