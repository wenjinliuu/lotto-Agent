from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from automation import parse_payload, parse_weekdays
from check_prize import check_prize
import crypto_random
import database
from draw_calendar import is_default_draw_day, next_fallback_draw, parse_date
from fetch_draw import fetch_draw
from followup import add as add_followup
from generate_numbers import generate
from push_message import push_message
from report import build_report
from utils import CONFIG_DIR, load_json, now_iso


def run_due(job_name: str | None = None, push: bool = False) -> dict[str, Any]:
    database.init_db()
    schedule = load_json(CONFIG_DIR / "schedule.json", {})
    results = []
    for job in schedule.get("jobs", []):
        if not job.get("enabled", False):
            continue
        if job_name and job.get("name") != job_name:
            continue
        if not job_name and not legacy_job_due(job):
            continue
        results.append(run_job(job, push=push))
    if not job_name or job_name == "automation":
        results.extend(run_due_automation(push=push))
    return {"ok": all(item.get("ok") for item in results), "results": results}


def run_job(job: dict[str, Any], push: bool = False) -> dict[str, Any]:
    action = job.get("action")
    try:
        if action == "generate":
            if job.get("use_user_preferences"):
                result = generate_from_preferences()
            else:
                result = generate(job.get("lottery_type", "dlt"), count=int(job.get("count", 1)), source="scheduler", is_purchased=True)
        elif action == "fetch_draw":
            result = fetch_draw(job.get("lottery_type", "all"))
        elif action == "check_prize":
            result = check_prize()
        elif action == "draw_check_prize":
            result = run_draw_check_prize(job.get("lottery_type", "all"), quiet_empty=True)
        elif action == "report":
            result = build_report(job.get("report_type", "weekly"))
        else:
            result = {"ok": False, "error": f"未知任务: {action}"}
        if push and should_push_result(action, result, {}):
            result["push"] = push_message(result["wechat_text"])
        database.log_scheduler(job.get("name", ""), str(action), "ok" if result.get("ok") else "error", result.get("error", ""), result)
        return result
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
        database.log_scheduler(job.get("name", ""), str(action), "error", str(exc), result)
        return result


def generate_from_preferences() -> dict[str, Any]:
    preferences = load_json(CONFIG_DIR / "preferences.json", {})
    results = []
    for lottery_type, item in preferences.get("subscriptions", {}).get("lotteries", {}).items():
        if not item.get("enabled", False):
            continue
        results.append(
            generate(
                lottery_type,
                count=int(item.get("count", preferences.get("default_count", 1))),
                play_type=item.get("play_type"),
                multiple=int(item.get("multiple", 1)),
                is_additional=item.get("is_additional"),
                source="scheduler",
                is_purchased=True,
            )
        )
    text_parts = [item.get("wechat_text", "") for item in results if item.get("wechat_text")]
    return {"ok": all(item.get("ok") for item in results), "results": results, "wechat_text": "\n\n".join(text_parts)}


def run_due_automation(push: bool = False) -> list[dict[str, Any]]:
    now = cn_now()
    tasks = database.fetch_all("SELECT * FROM scheduled_tasks WHERE enabled = 1 ORDER BY id ASC")
    results = []
    for task in tasks:
        if not task_due(task, now):
            continue
        result = run_scheduled_task(task, push=push, now=now)
        results.append(result)
    return results


def run_scheduled_task(task: dict[str, Any], push: bool = False, now: datetime | None = None) -> dict[str, Any]:
    now = now or cn_now()
    payload = parse_payload(task.get("payload_json"))
    action = task.get("action")
    try:
        if action == "generate":
            result = generate(
                payload.get("lottery_type") or task.get("lottery_type") or "dlt",
                count=int(payload.get("count", 1)),
                budget=payload.get("budget"),
                play_type=payload.get("play_type") or task.get("play_type"),
                user_platform_id=payload.get("user_platform_id", "wechat_self"),
                multiple=int(payload.get("multiple", 1)),
                is_additional=payload.get("is_additional"),
                source="automation",
                is_purchased=True,
                user_command=task.get("raw_text"),
            )
        elif action == "fetch_draw":
            result = fetch_draw(payload.get("lottery_type", task.get("lottery_type") or "all"))
        elif action == "check_prize":
            result = check_prize(payload.get("lottery_type") or task.get("lottery_type"), payload.get("issue"), payload.get("user_platform_id"))
        elif action == "draw_check_prize":
            result = run_draw_check_prize(payload.get("lottery_type", task.get("lottery_type") or "all"), payload.get("issue"), payload.get("user_platform_id"), quiet_empty=True)
        elif action == "report":
            result = build_report(payload.get("report_type", "weekly"), payload.get("user_platform_id"))
        else:
            result = {"ok": False, "error": f"未知自动任务: {action}"}
        if push and should_push_result(action, result, payload):
            result["push"] = push_message(result["wechat_text"], payload.get("user_platform_id", "wechat_self"))
        mark_task_ran(int(task["id"]), run_key(task, now), result)
        if task.get("schedule_type") == "once":
            disable_task(int(task["id"]))
        database.log_scheduler(f"task:{task['id']}", str(action), "ok" if result.get("ok") else "error", result.get("error", ""), result)
        return {"ok": result.get("ok", False), "task_id": task["id"], "result": result}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
        mark_task_ran(int(task["id"]), run_key(task, now), result)
        database.log_scheduler(f"task:{task['id']}", str(action), "error", str(exc), result)
        return {"ok": False, "task_id": task["id"], "result": result}


def task_due(task: dict[str, Any], now: datetime) -> bool:
    key = run_key(task, now)
    if task.get("last_run_key") == key:
        return False
    schedule_type = task.get("schedule_type") or "recurring"
    today = now.date().isoformat()
    if schedule_type == "once" and task.get("run_date") != today:
        return False
    if schedule_type != "once":
        frequency = task.get("frequency") or "daily"
        if task.get("trigger_type") == "draw_day":
            if not draw_day_task_due(task, now):
                return False
        if frequency == "weekly":
            weekdays = parse_weekdays(task.get("weekdays_json"))
            if weekdays and now.isoweekday() not in weekdays:
                return False
    if task.get("run_time_mode") == "random_once_in_window":
        return random_window_due(task, now, key)
    return in_time_window(now, task.get("time_start") or "09:00", task.get("time_end") or task.get("time_start") or "09:00")


def draw_day_task_due(task: dict[str, Any], now: datetime) -> bool:
    lottery_type = task.get("lottery_type") or parse_payload(task.get("payload_json")).get("lottery_type")
    if not lottery_type or lottery_type == "all":
        return False
    offset = int(task.get("draw_day_offset") or 0)
    target_date = (now.date() - timedelta(days=offset)).isoformat()
    fallback = next_fallback_draw(lottery_type, start=parse_date(target_date) or now.date())
    fallback_date = fallback.get("draw_date")
    if fallback_date:
        return fallback_date == target_date
    return is_default_draw_day(lottery_type, target_date)


def render_draw_check_text(fetch_result: dict[str, Any], prize_result: dict[str, Any]) -> str:
    if int(prize_result.get("checked_count") or 0) <= 0:
        return ""
    return "\n\n".join(part for part in [fetch_result.get("wechat_text"), prize_result.get("wechat_text")] if part)


def run_draw_check_prize(
    lottery_type: str | None = "all",
    issue: str | None = None,
    user_platform_id: str | None = None,
    quiet_empty: bool = False,
) -> dict[str, Any]:
    target = lottery_type or "all"
    fetch_result = fetch_draw(target)
    check_lottery = None if target == "all" else target
    prize_result = check_prize(check_lottery, issue, user_platform_id)
    checked_count = int(prize_result.get("checked_count") or 0)
    result = {
        "ok": bool(fetch_result.get("ok")) and bool(prize_result.get("ok")),
        "fetch_result": fetch_result,
        "prize_result": prize_result,
        "checked_count": checked_count,
        "winning_count": int(prize_result.get("winning_count") or 0),
        "total_amount": float(prize_result.get("total_amount") or 0),
        "wechat_text": render_manual_draw_check_text(fetch_result, prize_result, quiet_empty),
    }
    if checked_count <= 0:
        add_followup(result, "prize_empty", f"{lottery_type}:{issue}:{user_platform_id}")
    elif result["winning_count"] > 0:
        add_followup(result, "prize_win", f"{lottery_type}:{issue}:{result['total_amount']}")
    else:
        add_followup(result, "prize_no_win", f"{lottery_type}:{issue}:{checked_count}")
    return result


def render_manual_draw_check_text(fetch_result: dict[str, Any], prize_result: dict[str, Any], quiet_empty: bool) -> str:
    checked_count = int(prize_result.get("checked_count") or 0)
    if checked_count > 0:
        return "\n\n".join(part for part in [fetch_result.get("wechat_text"), prize_result.get("wechat_text")] if part)
    if quiet_empty:
        return ""
    fetch_text = fetch_result.get("wechat_text") or ("开奖数据同步成功" if fetch_result.get("ok") else f"开奖数据同步失败：{fetch_result.get('error') or '-'}")
    return f"{fetch_text}\n\n暂时没有匹配到可兑奖的已购买号码。"


def should_push_result(action: str | None, result: dict[str, Any], payload: dict[str, Any]) -> bool:
    if not result.get("wechat_text"):
        return False
    preferences = load_json(CONFIG_DIR / "preferences.json", {})
    push_content = preferences.get("subscriptions", {}).get("push_content", {})
    if action in {"check_prize", "draw_check_prize"}:
        prize_result = result.get("prize_result") if action == "draw_check_prize" else result
        checked_count = int((prize_result or {}).get("checked_count") or 0)
        winning_count = int((prize_result or {}).get("winning_count") or 0)
        if checked_count <= 0 and not push_content.get("empty_prize_result", False):
            return False
        if winning_count <= 0 and payload.get("only_push_winning", False):
            return False
    return True


def legacy_job_due(job: dict[str, Any]) -> bool:
    now = cn_now()
    if not in_time_window(now, job.get("time", "00:00"), job.get("time_end", job.get("time", "00:00"))):
        return False
    if job.get("weekday") and weekday_code(now) != str(job["weekday"]).upper():
        return False
    if job.get("day") and now.day != int(job["day"]):
        return False
    key = legacy_run_key(job, now)
    if scheduler_key_exists(key):
        return False
    database.log_scheduler(str(job.get("name", "")), str(job.get("action", "")), "due", key, {"run_key": key})
    return True


def legacy_run_key(job: dict[str, Any], now: datetime) -> str:
    if job.get("action") == "draw_check_prize":
        retry_minutes = max(5, int(job.get("retry_minutes") or 10))
        slot = (now.hour * 60 + now.minute) // retry_minutes
        return f"legacy:{job.get('name')}:{now.date().isoformat()}:{slot}"
    return f"legacy:{job.get('name')}:{now.date().isoformat()}"


def in_time_window(now: datetime, start: str, end: str) -> bool:
    start_minutes = minutes(start)
    end_minutes = minutes(end)
    current = now.hour * 60 + now.minute
    if start_minutes is None:
        return False
    if end_minutes is None or end_minutes == start_minutes:
        end_minutes = start_minutes + 9
    if end_minutes < start_minutes:
        return current >= start_minutes or current <= end_minutes
    return start_minutes <= current <= end_minutes


def random_window_due(task: dict[str, Any], now: datetime, key: str) -> bool:
    start = task.get("time_start") or "09:00"
    end = task.get("time_end") or start
    if not in_time_window(now, start, end):
        return False
    planned = planned_run_minutes(task, key, start, end)
    current = now.hour * 60 + now.minute
    return planned is not None and current >= planned


def planned_run_minutes(task: dict[str, Any], key: str, start: str, end: str) -> int | None:
    start_minutes = minutes(start)
    end_minutes = minutes(end)
    if start_minutes is None:
        return None
    if end_minutes is None or end_minutes < start_minutes:
        end_minutes = start_minutes
    if task.get("planned_run_key") == key and task.get("planned_run_time"):
        return minutes(str(task["planned_run_time"]))
    planned = crypto_random.rand_int(start_minutes, end_minutes)
    planned_time = f"{planned // 60:02d}:{planned % 60:02d}"
    with database.connect() as conn:
        conn.execute(
            "UPDATE scheduled_tasks SET planned_run_key = ?, planned_run_time = ?, updated_at = ? WHERE id = ?",
            (key, planned_time, now_iso(), task["id"]),
        )
        conn.commit()
    return planned


def minutes(value: str | None) -> int | None:
    try:
        hour, minute = [int(part) for part in str(value or "").split(":")[:2]]
        return hour * 60 + minute
    except (TypeError, ValueError):
        return None


def run_key(task: dict[str, Any], now: datetime) -> str:
    if task.get("schedule_type") == "once":
        return f"once:{task['id']}:{task.get('run_date')}"
    if task.get("action") == "draw_check_prize":
        return f"{task['id']}:{now.date().isoformat()}:{now.hour:02d}:{now.minute // 10}"
    return f"{task['id']}:{now.date().isoformat()}"


def mark_task_ran(task_id: int, key: str, result: dict[str, Any]) -> None:
    with database.connect() as conn:
        conn.execute(
            "UPDATE scheduled_tasks SET last_run_key = ?, last_run_at = ?, updated_at = ? WHERE id = ?",
            (key, now_iso(), now_iso(), task_id),
        )
        conn.commit()


def disable_task(task_id: int) -> None:
    with database.connect() as conn:
        conn.execute("UPDATE scheduled_tasks SET enabled = 0, updated_at = ? WHERE id = ?", (now_iso(), task_id))
        conn.commit()


def scheduler_key_exists(key: str) -> bool:
    rows = database.fetch_all("SELECT id FROM scheduler_logs WHERE message = ? LIMIT 1", (key,))
    return bool(rows)


def cn_now() -> datetime:
    return datetime.now(timezone(timedelta(hours=8)))


def weekday_code(now: datetime) -> str:
    return {1: "MON", 2: "TUE", 3: "WED", 4: "THU", 5: "FRI", 6: "SAT", 7: "SUN"}[now.isoweekday()]
