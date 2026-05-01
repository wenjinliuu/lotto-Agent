from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import database
from utils import CONFIG_DIR, load_json


CALENDAR = load_json(CONFIG_DIR / "draw_calendar.json", {})
CN_TZ = timezone(timedelta(hours=8))


@dataclass(frozen=True)
class TrackingInfo:
    issue: str | None
    draw_date: str | None
    status: str
    note: str = ""
    buy_end_time: str | None = None
    source: str = ""


def cn_now() -> datetime:
    return datetime.now(CN_TZ)


def parse_cn_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=CN_TZ)
            return parsed
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=CN_TZ)
        return parsed
    except ValueError:
        return None


def parse_draw_date_intent(text: str, now: datetime | None = None) -> str | None:
    message = str(text or "")
    base = (now or cn_now()).date()
    if "今天" in message or "今晚" in message:
        return base.isoformat()
    if "明天" in message or "明晚" in message:
        return (base + timedelta(days=1)).isoformat()
    if "后天" in message:
        return (base + timedelta(days=2)).isoformat()

    match = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?", message)
    if match:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()

    match = re.search(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日?", message)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        year = base.year
        candidate = date(year, month, day)
        if candidate < base - timedelta(days=180):
            candidate = date(year + 1, month, day)
        return candidate.isoformat()

    match = re.search(r"(?<!\d)(\d{1,2})[-/](\d{1,2})(?!\d)", message)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        year = base.year
        candidate = date(year, month, day)
        if candidate < base - timedelta(days=180):
            candidate = date(year + 1, month, day)
        return candidate.isoformat()
    return None


def resolve_tracking_info(lottery_type: str, issue: str | None = None, requested_draw_date: str | None = None) -> TrackingInfo:
    if issue and requested_draw_date:
        return TrackingInfo(issue=issue, draw_date=requested_draw_date, status="manual", source="manual")

    latest = latest_next_info(lottery_type)
    if issue:
        return TrackingInfo(issue=issue, draw_date=requested_draw_date or latest.get("next_draw_date") or None, status="manual_issue", source="manual")

    if requested_draw_date:
        return resolve_requested_date(lottery_type, requested_draw_date, latest)

    if latest.get("next_issue") or latest.get("next_draw_date"):
        buy_end = latest.get("next_buy_end_time") or ""
        buy_end_dt = parse_cn_datetime(buy_end)
        if buy_end_dt and cn_now() > buy_end_dt:
            fallback = next_fallback_draw(lottery_type, start=cn_now().date())
            note = f"最新日历中的 {latest.get('next_issue') or ''} 期已过销售截止时间，已按下一次开奖日生成。"
            return TrackingInfo(None, fallback.get("draw_date"), "sales_closed_fallback", note, fallback.get("buy_end_time"), "weekly_fallback")
        return TrackingInfo(
            latest.get("next_issue") or None,
            latest.get("next_draw_date") or date_part(latest.get("next_open_time")) or None,
            "api_next_issue",
            "",
            buy_end or None,
            "api_next",
        )

    fallback = next_fallback_draw(lottery_type, start=cn_now().date())
    return TrackingInfo(None, fallback.get("draw_date"), "weekly_fallback", "", fallback.get("buy_end_time"), "weekly_fallback")


def resolve_requested_date(lottery_type: str, requested_draw_date: str, latest: dict[str, str]) -> TrackingInfo:
    target = parse_date(requested_draw_date)
    if target is None:
        return resolve_tracking_info(lottery_type)

    local = local_calendar_entry(lottery_type, requested_draw_date)
    if local:
        if bool(local.get("is_draw", True)):
            return TrackingInfo(
                str(local.get("issue") or local.get("next_issue") or "") or None,
                str(local.get("draw_date") or requested_draw_date),
                "local_calendar",
                str(local.get("note") or ""),
                str(local.get("next_buy_end_time") or local.get("buy_end_time") or "") or None,
                "local_calendar",
            )
        adjusted = str(local.get("next_draw_date") or local.get("adjust_to") or "")
        if adjusted:
            return TrackingInfo(
                str(local.get("next_issue") or "") or None,
                adjusted,
                "date_adjusted",
                str(local.get("note") or f"你说的是 {requested_draw_date}，但该彩种这天不开奖，已按下一次开奖 {adjusted} 生成。"),
                str(local.get("next_buy_end_time") or "") or None,
                "local_calendar",
            )

    latest_date = latest.get("next_draw_date") or date_part(latest.get("next_open_time"))
    if latest_date:
        latest_target = parse_date(latest_date)
        if latest_target and latest_target >= target:
            if latest_target == target:
                return TrackingInfo(latest.get("next_issue") or None, latest_date, "api_next_issue", "", latest.get("next_buy_end_time") or None, "api_next")
            return TrackingInfo(
                latest.get("next_issue") or None,
                latest_date,
                "date_adjusted",
                f"你说的是 {requested_draw_date}，但该彩种这天不开奖，已按下一次开奖 {latest_date} 生成。",
                latest.get("next_buy_end_time") or None,
                "api_next",
            )

    fallback = next_fallback_draw(lottery_type, start=target)
    if not fallback.get("draw_date"):
        return TrackingInfo(None, requested_draw_date, "missing_calendar", "未找到该彩种的开奖日历。", None, "missing")
    if fallback["draw_date"] == requested_draw_date:
        return TrackingInfo(None, requested_draw_date, "weekly_fallback", "", fallback.get("buy_end_time"), "weekly_fallback")
    return TrackingInfo(
        None,
        fallback["draw_date"],
        "date_adjusted",
        f"你说的是 {requested_draw_date}，但该彩种这天不开奖，已按下一次开奖 {fallback['draw_date']} 生成。",
        fallback.get("buy_end_time"),
        "weekly_fallback",
    )


def latest_next_info(lottery_type: str) -> dict[str, str]:
    try:
        with database.connect() as conn:
            row = conn.execute(
                """
                SELECT next_issue, next_draw_date, next_open_time, next_buy_end_time, raw_json
                FROM draws
                WHERE lottery_type = ?
                ORDER BY COALESCE(draw_date, '') DESC, issue DESC
                LIMIT 1
                """,
                (lottery_type,),
            ).fetchone()
    except Exception:
        return {}
    if not row:
        return {}

    raw = parse_raw(row["raw_json"])
    return {
        "next_issue": row_value(row, "next_issue") or raw_value(raw, "next_issue") or raw_value(raw, "nextissueno"),
        "next_draw_date": row_value(row, "next_draw_date") or raw_value(raw, "next_draw_date") or date_part(raw_value(raw, "nextopentime")),
        "next_open_time": row_value(row, "next_open_time") or raw_value(raw, "next_open_time") or raw_value(raw, "nextopentime"),
        "next_buy_end_time": row_value(row, "next_buy_end_time") or raw_value(raw, "next_buy_end_time") or raw_value(raw, "nextbuyendtime"),
    }


def next_fallback_draw(lottery_type: str, start: date | None = None) -> dict[str, str]:
    config = CALENDAR.get("default_weekly_schedule", {}).get(lottery_type, {})
    weekdays = {int(day) for day in config.get("draw_weekdays", [])}
    if not weekdays:
        return {}
    start_date = start or cn_now().date()
    draw_time = str(config.get("draw_time") or "21:00")
    buy_end = str(config.get("buy_end_time") or "20:00")
    now = cn_now()
    for offset in range(0, 15):
        candidate = start_date + timedelta(days=offset)
        local = local_calendar_entry(lottery_type, candidate.isoformat())
        if local and bool(local.get("is_draw", True)):
            draw_time_value = str(local.get("draw_time") or draw_time)
            buy_end_value = str(local.get("buy_end_time") or local.get("next_buy_end_time") or buy_end)
            return {
                "draw_date": str(local.get("draw_date") or candidate.isoformat()),
                "next_open_time": str(local.get("next_open_time") or format_datetime(candidate, draw_time_value)),
                "buy_end_time": str(local.get("next_buy_end_time") or format_datetime(candidate, buy_end_value)),
            }
        if local and not bool(local.get("is_draw", True)):
            continue
        if candidate.isoweekday() not in weekdays:
            continue
        buy_end_dt = combine_date_time(candidate, buy_end)
        if candidate == now.date() and buy_end_dt and now > buy_end_dt:
            continue
        return {
            "draw_date": candidate.isoformat(),
            "next_open_time": f"{candidate.isoformat()} {draw_time}:00" if len(draw_time) == 5 else f"{candidate.isoformat()} {draw_time}",
            "buy_end_time": f"{candidate.isoformat()} {buy_end}:00" if len(buy_end) == 5 else f"{candidate.isoformat()} {buy_end}",
        }
    return {}


def local_calendar_entry(lottery_type: str, day: str) -> dict[str, Any] | None:
    for item in CALENDAR.get("holiday_overrides", []):
        if not isinstance(item, dict):
            continue
        item_lottery = str(item.get("lottery_type") or "all")
        if item_lottery not in {"all", lottery_type}:
            continue
        if str(item.get("date") or item.get("draw_date") or "")[:10] == str(day)[:10]:
            return item
    return None


def format_datetime(day: date, value: str) -> str:
    text = str(value or "")
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return text
    return f"{day.isoformat()} {text}:00" if len(text) == 5 else f"{day.isoformat()} {text}"


def is_default_draw_day(lottery_type: str, value: str) -> bool:
    target = parse_date(value)
    if target is None:
        return False
    config = CALENDAR.get("default_weekly_schedule", {}).get(lottery_type, {})
    return target.isoweekday() in {int(day) for day in config.get("draw_weekdays", [])}


def combine_date_time(day: date, value: str) -> datetime | None:
    try:
        parts = [int(part) for part in str(value or "20:00").split(":")]
        while len(parts) < 3:
            parts.append(0)
        return datetime.combine(day, time(parts[0], parts[1], parts[2]), tzinfo=CN_TZ)
    except (TypeError, ValueError):
        return None


def parse_date(value: str) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def date_part(value: str) -> str:
    return str(value or "")[:10]


def row_value(row: Any, key: str) -> str:
    try:
        return str(row[key] or "")
    except (KeyError, IndexError):
        return ""


def parse_raw(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def raw_value(raw: dict[str, Any], key: str) -> str:
    if key in raw:
        return str(raw.get(key) or "")
    for container_key in ("class_info", "raw_public_json", "query"):
        nested = raw.get(container_key)
        if isinstance(nested, dict):
            if key in nested:
                return str(nested.get(key) or "")
            value = raw_value(nested, key)
            if value:
                return value
    return ""
