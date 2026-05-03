from __future__ import annotations

import re
from typing import Any

from draw_calendar import parse_draw_date_intent
from utils import CONFIG_DIR, load_json


RULES = load_json(CONFIG_DIR / "lottery_rules.json", {})


def parse_command(text: str) -> dict[str, Any]:
    message = str(text or "").strip()
    if not message:
        return {"ok": False, "error": "空命令"}
    notification_intent = parse_notification_intent(message)
    if notification_intent:
        return notification_intent
    lottery_type = detect_lottery(message)
    count = detect_count(message)
    budget = detect_budget(message)
    multiple = detect_multiple(message)
    play_type = detect_play_type(message)
    issue = detect_issue(message)
    draw_date = parse_draw_date_intent(message)
    prize_level = detect_prize_level(message)
    is_additional = detect_additional(message)
    is_preview = detect_preview(message)
    plan_items = detect_plan_items(message, lottery_type)

    cron_intent = parse_cron_intent(message)
    if cron_intent:
        return cron_intent
    if is_manual_draw_check(message):
        return {"ok": True, "action": "draw_check_prize", "params": clean({"lottery_type": lottery_type or "all", "issue": issue})}
    automation_intent = parse_automation_command(message, lottery_type, count, budget, play_type, multiple, is_additional, draw_date)
    if automation_intent:
        return automation_intent
    clarification = parse_clarification_needed(message)
    if clarification:
        return clarification

    if is_replace(message):
        params = {
            "lottery_type": lottery_type,
            "count": count,
            "budget": budget,
            "play_type": play_type,
            "multiple": multiple,
            "draw_date": draw_date,
            "is_additional": is_additional,
            "is_purchased": not is_preview,
            "text": message,
        }
        if plan_items:
            params["items"] = plan_items
        return {"ok": True, "action": "replace_last_batch", "params": clean(params)}

    if is_manual_record(message):
        if has_ticket_numbers(message):
            return action("record_ticket", lottery_type, message, issue, draw_date, play_type, multiple, is_additional)
        return {"ok": True, "action": "confirm_purchase", "params": {"limit": count or 20}}
    if any(word in message for word in ["刚才的号码我买了", "刚才生成的号码我买了", "算已购买", "确认购买"]):
        return {"ok": True, "action": "confirm_purchase", "params": {"limit": count or 20}}
    if any(word in message for word in ["取消", "不要算成本", "不算成本"]):
        return {"ok": True, "action": "cancel_tickets", "params": {"limit": count or 20, "notes": message}}
    if any(word in message for word in ["最近号码", "最近记录", "选号记录"]):
        return {"ok": True, "action": "recent_tickets", "params": {"limit": count or 10}}
    if any(word in message for word in ["兑奖", "中奖", "兑一下", "有没有中"]):
        return {"ok": True, "action": "check_prize", "params": clean({"lottery_type": lottery_type, "issue": issue})}
    if is_draw_detail_query(message):
        return {
            "ok": True,
            "action": "query_draw_detail",
            "params": clean({"lottery_type": lottery_type or "dlt", "issue": issue, "prize_level": prize_level}),
        }
    if any(word in message for word in ["盈亏", "报告", "花了多少钱", "投入", "回报"]):
        return {"ok": True, "action": "report", "params": {"report_type": detect_report_type(message)}}
    if any(word in message for word in ["开奖", "奖池", "最新"]) and not any(word in message for word in ["给我", "生成", "选号", "注"]):
        return {"ok": True, "action": "fetch_draw", "params": clean({"lottery_type": lottery_type or "all", "issue": issue})}
    if any(word in message for word in ["以后", "默认", "推送时间", "每天"]):
        return parse_config_command(message, lottery_type, count, play_type, is_additional)

    if plan_items and lottery_type:
        return {
            "ok": True,
            "action": "generate_plan",
            "params": {"lottery_type": lottery_type, "items": plan_items, "draw_date": draw_date, "is_purchased": not is_preview, "text": message},
        }
    if is_generate_intent(message) or (lottery_type and (count or budget or multiple or play_type)):
        return {
            "ok": True,
            "action": "generate",
            "params": clean(
                {
                    "lottery_type": lottery_type or "dlt",
                    "count": count,
                    "budget": budget,
                    "play_type": play_type,
                    "draw_date": draw_date,
                    "multiple": multiple,
                    "is_additional": is_additional,
                    "is_purchased": not is_preview,
                    "text": message,
                }
            ),
        }
    return {"ok": False, "error": "未识别命令", "text": message}


def action(name: str, lottery_type: str | None, text: str, issue: str | None, draw_date: str | None, play_type: str | None, multiple: int | None, is_additional: bool | None) -> dict[str, Any]:
    return {
        "ok": True,
        "action": name,
        "params": clean({"lottery_type": lottery_type or "dlt", "text": text, "issue": issue, "draw_date": draw_date, "play_type": play_type, "multiple": multiple, "is_additional": is_additional}),
    }


def detect_lottery(text: str) -> str | None:
    lower = text.lower()
    for key, config in RULES.get("lotteries", {}).items():
        for alias in config.get("aliases", []):
            if str(alias).lower() in lower:
                return key
    return None


def detect_plan_items(text: str, lottery_type: str | None) -> list[dict[str, Any]]:
    if lottery_type not in {"fc3d", "pl3", "kl8"}:
        return []
    items: list[dict[str, Any]] = []
    segments = re.split(r"[，,；;。]\s*", text)
    for segment in segments:
        play_type = detect_play_type(segment)
        count = detect_count(segment)
        if not play_type or not count:
            continue
        item = {"play_type": play_type, "count": count}
        multiple = detect_multiple(segment)
        if multiple:
            item["multiple"] = multiple
        items.append(item)
    if len(items) <= 1:
        return []
    return items


def detect_count(text: str) -> int | None:
    match = re.search(r"(\d+)\s*注", text)
    return int(match.group(1)) if match else None


def detect_budget(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*元", text)
    if match and "奖金" not in text and "奖池" not in text:
        return float(match.group(1))
    return None


def detect_multiple(text: str) -> int | None:
    if "双倍" in text or "两倍" in text:
        return 2
    match = re.search(r"(\d+)\s*倍", text)
    return int(match.group(1)) if match else None


def detect_issue(text: str) -> str | None:
    match = re.search(r"第?\s*(\d{3,})\s*期", text)
    return match.group(1) if match else None


def detect_prize_level(text: str) -> str | None:
    patterns = [
        (r"特等奖", "特等奖"),
        (r"一等奖|一等", "一等奖"),
        (r"二等奖|二等", "二等奖"),
        (r"三等奖|三等", "三等奖"),
        (r"四等奖|四等", "四等奖"),
        (r"五等奖|五等", "五等奖"),
        (r"六等奖|六等", "六等奖"),
        (r"七等奖|七等", "七等奖"),
        (r"八等奖|八等", "八等奖"),
        (r"九等奖|九等", "九等奖"),
    ]
    for pattern, value in patterns:
        if re.search(pattern, text):
            return value
    return None


def detect_play_type(text: str) -> str | None:
    if "组三" in text:
        return "group3"
    if "组六" in text:
        return "group6"
    if "单选" in text or "直选" in text:
        return "single"
    match = re.search(r"选\s*(十|[一二三四五六七八九]|\d{1,2})", text)
    if match:
        value = match.group(1)
        cn = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
        return str(cn.get(value, int(value) if value.isdigit() else value))
    return None


def detect_additional(text: str) -> bool | None:
    if "不追加" in text or "不要追加" in text:
        return False
    if "追加" in text:
        return True
    return None


def detect_preview(text: str) -> bool:
    return any(word in text for word in ["先看看", "参考", "只是看看", "先别记录", "不算成本", "不要算成本", "试一下", "随便看看"])


def detect_report_type(text: str) -> str:
    if "月" in text or "本月" in text:
        return "monthly"
    if "周" in text or "本周" in text:
        return "weekly"
    return "daily"


def parse_cron_intent(text: str) -> dict[str, Any] | None:
    if any(word in text for word in ["确认开启自动化", "确认安装自动化", "确认启用自动化"]):
        return {"ok": True, "action": "install_cron", "params": {"confirm": True}}
    if any(word in text for word in ["开启自动化", "启用自动化", "安装自动化", "安装定时唤醒", "开启定时唤醒"]):
        return {"ok": True, "action": "install_cron", "params": {"confirm": False}}
    if any(word in text for word in ["确认停止自动化", "确认关闭自动化"]):
        return {"ok": True, "action": "uninstall_cron", "params": {"confirm": True}}
    if any(word in text for word in ["停止自动化", "关闭自动化", "停用自动化唤醒"]):
        return {"ok": True, "action": "uninstall_cron", "params": {"confirm": False}}
    if any(word in text for word in ["自动化状态", "定时唤醒状态", "cron状态"]):
        return {"ok": True, "action": "cron_status", "params": {}}
    return None


def parse_notification_intent(text: str) -> dict[str, Any] | None:
    if any(word in text for word in ["通知目标列表", "查看通知目标", "推送目标列表", "查看推送目标"]):
        return {"ok": True, "action": "list_notification_targets", "params": {}}
    if any(word in text for word in ["确认绑定当前通知目标", "确认绑定通知目标", "确认绑定当前窗口", "确认把消息发到这里"]):
        return {"ok": True, "action": "bind_notification_target", "params": {"confirm": True}}
    if any(word in text for word in ["绑定当前通知目标", "绑定通知目标", "绑定当前窗口", "把消息发到这里", "以后发到这里"]):
        return {"ok": True, "action": "bind_notification_target", "params": {"confirm": False}}
    if any(word in text for word in ["确认开启消息推送", "确认启用消息推送", "确认开启通知", "确认启用通知"]):
        return {"ok": True, "action": "enable_notification", "params": {"confirm": True}}
    if any(word in text for word in ["开启消息推送", "启用消息推送", "开启通知", "启用通知"]):
        return {"ok": True, "action": "enable_notification", "params": {"confirm": False}}
    if any(word in text for word in ["消息推送状态", "通知状态", "推送配置"]):
        return {"ok": True, "action": "notification_status", "params": {}}
    if "openclaw" in text.lower() and any(word in text for word in ["推送", "通知"]):
        return {"ok": True, "action": "configure_notification", "params": {"provider": "openclaw_cli"}}
    return None


def parse_automation_command(
    text: str,
    lottery_type: str | None,
    count: int | None,
    budget: float | None,
    play_type: str | None,
    multiple: int | None,
    is_additional: bool | None,
    draw_date: str | None,
) -> dict[str, Any] | None:
    if any(word in text for word in ["查看自动任务", "自动任务列表", "有哪些自动任务"]):
        return {"ok": True, "action": "list_automation", "params": {}}
    if any(word in text for word in ["取消自动任务", "停用自动任务", "停止每天", "取消每天"]):
        params: dict[str, Any] = {}
        task_id = detect_task_id(text)
        if task_id:
            params["task_id"] = task_id
        if "兑奖" in text:
            params["task_action"] = "check_prize"
        return {"ok": True, "action": "disable_automation", "params": params}

    trigger_type = detect_trigger_type(text)
    draw_day_offset = detect_draw_day_offset(text)
    recurring = any(word in text for word in ["每天", "每日", "每晚", "每早", "每周", "每期开奖后", "以后每天", "定时", "自动"]) or bool(trigger_type and any(word in text for word in ["以后", "每次", "每回"]))
    once = draw_date is not None and any(word in text for word in ["明天", "后天", "今晚", "今天", "明晚"])
    if trigger_type and draw_day_offset < 0 and any(word in text for word in ["给我", "生成", "号码", "选号", "注"]):
        recurring = True
    if "默认" in text and not any(word in text for word in ["每天", "每周", "自动", "定时"]):
        return None
    if not (recurring or once):
        return None
    if not any(word in text for word in ["给我", "生成", "号码", "选号", "兑奖", "开奖", "中奖", "报告", "盈亏"]):
        return None

    task_action = detect_task_action(text)
    if task_action == "generate" and not (lottery_type or count or play_type or any(word in text for word in ["号码", "选号", "给我"])):
        return None
    schedule_type = "once" if once and not recurring else "recurring"
    frequency = "weekly" if "每周" in text else "daily"
    if trigger_type:
        frequency = "draw_day"
    weekdays = detect_weekdays(text) if frequency == "weekly" else []
    time_start, time_end, run_time_mode = detect_time_window(text, task_action)
    payload_lottery = lottery_type
    if not payload_lottery and task_action == "generate":
        payload_lottery = "dlt"
    if not payload_lottery and task_action in {"fetch_draw", "draw_check_prize"}:
        payload_lottery = "all"
    payload = clean(
        {
            "lottery_type": payload_lottery,
            "count": count or (1 if task_action == "generate" else None),
            "budget": budget,
            "play_type": play_type,
            "multiple": multiple or (1 if task_action == "generate" else None),
            "is_additional": is_additional,
            "report_type": detect_report_type(text) if task_action == "report" else None,
        }
    )
    return {
        "ok": True,
        "action": "create_automation",
        "params": clean(
            {
                "task_action": task_action,
                "lottery_type": lottery_type,
                "play_type": play_type,
                "schedule_type": schedule_type,
                "frequency": frequency,
                "trigger_type": trigger_type,
                "draw_day_offset": draw_day_offset if trigger_type else None,
                "run_date": draw_date if schedule_type == "once" else None,
                "weekdays": weekdays,
                "time_start": time_start,
                "time_end": time_end,
                "run_time_mode": run_time_mode,
                "payload": payload,
                "raw_text": text,
            }
        ),
    }


def detect_task_action(text: str) -> str:
    if "开奖后" in text and any(word in text for word in ["兑奖", "中奖", "查中奖"]):
        return "draw_check_prize"
    if any(word in text for word in ["兑奖", "中奖", "有没有中"]):
        if any(word in text for word in ["开奖后", "数据出来", "查到开奖", "一开奖"]):
            return "draw_check_prize"
        return "check_prize"
    if any(word in text for word in ["报告", "盈亏"]):
        return "report"
    if "开奖" in text and not any(word in text for word in ["号码", "选号", "生成", "给我", "注"]):
        return "fetch_draw"
    return "generate"


def detect_trigger_type(text: str) -> str | None:
    if any(word in text for word in ["开奖那天", "开奖当天", "开奖日", "每次开奖当天", "开奖前一天", "开奖日前一天"]):
        return "draw_day"
    return None


def detect_draw_day_offset(text: str) -> int:
    if "开奖前一天" in text or "开奖日前一天" in text:
        return -1
    return 0


def detect_task_id(text: str) -> int | None:
    match = re.search(r"#?\s*(\d+)\s*号?任务", text)
    return int(match.group(1)) if match else None


def detect_weekdays(text: str) -> list[int]:
    match = re.search(r"每周([一二三四五六日天,，、和及]+)", text)
    if not match:
        return []
    mapping = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}
    return sorted({mapping[ch] for ch in match.group(1) if ch in mapping})


def detect_time_window(text: str, task_action: str) -> tuple[str, str, str]:
    range_match = re.search(r"(\d{1,2})(?:点|:|：)(\d{1,2})?\s*(?:到|至|-)\s*(\d{1,2})(?:点|:|：)(\d{1,2})?", text)
    if range_match:
        start = normalize_hour(int(range_match.group(1)), text)
        start_minute = int(range_match.group(2) or 0)
        end = normalize_hour(int(range_match.group(3)), text)
        end_minute = int(range_match.group(4) or 0)
        return f"{start:02d}:{start_minute:02d}", f"{end:02d}:{end_minute:02d}", "random_once_in_window"
    time_match = re.search(r"(\d{1,2})\s*(?:点|:|：)\s*(\d{1,2})?", text)
    if time_match:
        hour = normalize_hour(int(time_match.group(1)), text)
        minute = int(time_match.group(2) or 0)
        value = f"{hour:02d}:{minute:02d}"
        return value, value, "fixed"
    if any(word in text for word in ["早上", "早晨", "明早", "上午"]):
        return "07:00", "12:00", "random_once_in_window"
    if "下午" in text:
        return "12:00", "18:00", "random_once_in_window"
    if "晚上" in text or "今晚" in text or "每晚" in text:
        return "18:00", "23:30", "random_once_in_window"
    if task_action in {"check_prize", "draw_check_prize"}:
        return "21:35", "23:55", "fixed"
    return "09:00", "09:00", "fixed"


def normalize_hour(hour: int, text: str) -> int:
    if any(word in text for word in ["下午", "晚上", "今晚", "每晚"]) and hour < 12:
        return hour + 12
    if "中午" in text and hour < 11:
        return hour + 12
    return hour


def parse_clarification_needed(text: str) -> dict[str, Any] | None:
    fuzzy_time = ["有空的时候", "看情况", "你觉得合适", "差不多的时候", "晚点", "最近帮我安排"]
    if any(word in text for word in fuzzy_time) and any(word in text for word in ["生成", "选号", "给我", "提醒", "兑奖"]):
        return {
            "ok": False,
            "needs_clarification": True,
            "error": "时间不够明确",
            "message_text": "这个时间有点模糊。你想固定几点，还是放在上午、下午或晚上？",
            "followup_contexts": [
                {
                    "event": "clarify_time",
                    "facts": {"reason": "时间表达无法落成确定自动任务"},
                    "freedom": "medium",
                    "fallback_text": "你给我一个明确时间或时间段，我就能排上任务。",
                    "guardrails": ["不要自行猜测时间", "不要创建任务", "只问一个简短确认问题"],
                }
            ],
            "followup_messages": ["你给我一个明确时间或时间段，我就能排上任务。"],
        }
    return None


def has_ticket_numbers(text: str) -> bool:
    return len(re.findall(r"\d+", text)) >= 3


def is_replace(text: str) -> bool:
    return any(word in text for word in ["不喜欢", "重新", "换一组", "重来", "这组不要"])


def is_manual_record(text: str) -> bool:
    return any(word in text for word in ["我买了", "已买", "记录我买", "帮我记录", "这几注我买"])


def is_generate_intent(text: str) -> bool:
    return any(word in text for word in ["生成", "来", "给我", "方案", "选号", "再来", "追加生成"])


def is_draw_detail_query(text: str) -> bool:
    detail_words = ["中了几个人", "中几个人", "中奖人数", "中了几注", "中几注", "单注奖金", "中奖金额", "奖金是多少", "奖项明细", "一等奖", "二等奖"]
    context_words = ["上一期", "上期", "最近一期", "最新", "开奖", "奖池", "奖金"]
    return any(word in text for word in detail_words) and any(word in text for word in context_words)


def is_manual_draw_check(text: str) -> bool:
    patterns = [
        "开奖状态",
        "为什么今天还没开奖",
        "今天还没开奖",
        "今天开了吗",
        "今天开奖了吗",
        "今天中了没有",
        "今天中了没",
        "我今天中了没有",
        "我今天中了没",
        "帮我查一下今天中了没有",
    ]
    return any(pattern in text for pattern in patterns)


def parse_config_command(text: str, lottery_type: str | None, count: int | None, play_type: str | None, is_additional: bool | None) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if lottery_type:
        updates["default_lottery"] = lottery_type
    if count:
        updates["default_count"] = count
    if lottery_type and play_type:
        updates.setdefault("default_play_type", {})[lottery_type] = play_type
    if lottery_type and is_additional is not None:
        updates.setdefault("default_additional", {})[lottery_type] = is_additional
    time_match = re.search(r"(\d{1,2})\s*[点:：]\s*(\d{1,2})?", text)
    if time_match and ("推送" in text or "提醒" in text):
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        updates.setdefault("subscriptions", {})["daily_push_time"] = f"{hour:02d}:{minute:02d}"
    return {"ok": True, "action": "update_config", "params": {"config_name": "preferences", "updates": updates}}


def clean(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}
