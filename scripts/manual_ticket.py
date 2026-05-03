from __future__ import annotations

import re
from typing import Any

import database
from draw_calendar import resolve_tracking_info
from followup import add as add_followup, add_note
from generate_numbers import format_numbers, ticket_cost
from utils import CONFIG_DIR, load_json, normalize_lottery_type, now_iso


RULES = load_json(CONFIG_DIR / "lottery_rules.json", {})


def record_manual_tickets(
    lottery_type: str,
    text: str | None = None,
    numbers: list[dict[str, Any]] | None = None,
    play_type: str | None = None,
    issue: str | None = None,
    draw_date: str | None = None,
    multiple: int = 1,
    is_additional: bool = False,
    user_platform_id: str = "self",
    notes: str = "",
) -> dict[str, Any]:
    database.init_db()
    key = normalize_lottery_type(lottery_type, RULES)
    config = RULES["lotteries"][key]
    play_type = play_type or config.get("default_play_type", "standard")
    parsed = numbers or parse_manual_numbers(key, text or "", play_type)
    if not parsed:
        return {"ok": False, "error": "没有识别到有效号码"}

    tracking = resolve_tracking_info(key, issue, draw_date)
    issue = tracking.issue
    draw_date = tracking.draw_date
    user_id = database.ensure_user(user_platform_id)
    batch_id = database.create_ticket_batch(
        {
            "user_id": user_id,
            "lottery_type": key,
            "play_type": play_type,
            "issue": issue,
            "draw_date": draw_date,
            "count": len(parsed),
            "total_cost": ticket_cost(key, len(parsed), multiple, is_additional),
            "multiple": multiple,
            "is_additional": is_additional,
            "batch_status": "purchased",
            "source": "manual",
            "user_command": text,
            "created_at": now_iso(),
        }
    )

    tickets = []
    for item in parsed:
        validate_numbers(key, item, item.get("play_type", play_type))
        ticket = {
            "batch_id": batch_id,
            "user_id": user_id,
            "lottery_type": key,
            "play_type": item.get("play_type", play_type),
            "issue": issue,
            "draw_date": draw_date,
            "numbers": item,
            "cost": ticket_cost(key, 1, multiple, is_additional),
            "multiple": multiple,
            "is_additional": is_additional,
            "is_purchased": True,
            "ticket_status": "purchased",
            "purchase_confirmed_at": now_iso(),
            "source": "manual",
            "created_at": now_iso(),
            "tracking_status": tracking.status,
            "notes": notes,
        }
        ticket["id"] = database.insert_ticket(ticket)
        ticket["formatted"] = format_numbers(key, item)
        tickets.append(ticket)

    lines = [f"已记录 {config['name']} {len(tickets)} 注", f"投入：{sum(t['cost'] for t in tickets):g} 元"]
    if issue:
        lines.append(f"开奖期号：{issue}")
    elif draw_date:
        lines.append(f"开奖日期：{draw_date}")
    for index, ticket in enumerate(tickets, 1):
        lines.append(f"{index}. {ticket['formatted']}")
    result = {"ok": True, "batch_id": batch_id, "tickets": tickets, "notice_text": tracking.note, "message_text": "\n".join(lines)}
    add_followup(result, "manual_ticket", batch_id)
    add_note(result, tracking.note, seed=batch_id)
    return result


def parse_manual_numbers(lottery_type: str, text: str, play_type: str) -> list[dict[str, Any]]:
    cleaned = strip_non_ticket_numbers(str(text))
    lines = split_ticket_lines(cleaned)
    tickets: list[dict[str, Any]] = []
    for line in lines:
        nums = extract_nums(line)
        if not nums:
            continue
        tickets.extend(build_tickets_from_numbers(lottery_type, nums, play_type))
    if not tickets:
        nums = extract_nums(cleaned)
        tickets.extend(build_tickets_from_numbers(lottery_type, nums, play_type))
    return tickets


def strip_non_ticket_numbers(text: str) -> str:
    patterns = [
        r"第\s*\d{3,}\s*期",
        r"\b\d{3,}\s*期",
        r"\d+\s*倍",
        r"\d+(?:\.\d+)?\s*元",
        r"\d+\s*注",
    ]
    result = text
    for pattern in patterns:
        result = re.sub(pattern, " ", result, flags=re.IGNORECASE)
    return result


def split_ticket_lines(text: str) -> list[str]:
    normalized = (
        text.replace("；", "\n")
        .replace(";", "\n")
        .replace("。", "\n")
        .replace("|", "\n")
    )
    return [line.strip() for line in normalized.splitlines() if line.strip()]


def extract_nums(text: str) -> list[int]:
    return [int(item) for item in re.findall(r"\d+", text)]


def build_tickets_from_numbers(lottery_type: str, nums: list[int], play_type: str) -> list[dict[str, Any]]:
    if lottery_type in {"ssq", "dlt"}:
        size = 7
        chunks = chunk(nums, size)
        if lottery_type == "ssq":
            return [{"red": item[:6], "blue": item[6:7]} for item in chunks if len(item) == size]
        return [{"front": item[:5], "back": item[5:7]} for item in chunks if len(item) == size]
    if lottery_type == "qlc":
        return [{"basic": item} for item in chunk(nums, 7) if len(item) == 7]
    if lottery_type == "kl8":
        if 1 <= len(nums) <= 10:
            return [{"nums": nums, "play_count": len(nums), "play_type": str(len(nums))}]
        return [{"nums": item, "play_count": len(item), "play_type": str(len(item))} for item in chunk(nums, 10) if 1 <= len(item) <= 10]
    if lottery_type in {"qxc", "pl5", "fc3d", "pl3"}:
        expected = {"qxc": 7, "pl5": 5, "fc3d": 3, "pl3": 3}[lottery_type]
        digits = expand_digits(nums)
        items = []
        for item in chunk(digits, expected):
            if len(item) == expected:
                ticket: dict[str, Any] = {"digits": item}
                if lottery_type in {"fc3d", "pl3"}:
                    ticket["play_type"] = play_type
                items.append(ticket)
        return items
    return []


def expand_digits(nums: list[int]) -> list[int]:
    if all(0 <= n <= 9 for n in nums):
        return nums
    digits: list[int] = []
    for item in nums:
        digits.extend(int(ch) for ch in str(item))
    return digits


def chunk(values: list[int], size: int) -> list[list[int]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def validate_numbers(lottery_type: str, numbers: dict[str, Any], play_type: str) -> None:
    if lottery_type == "ssq":
        validate_unique_range(numbers["red"], 1, 33, 6)
        validate_unique_range(numbers["blue"], 1, 16, 1)
    elif lottery_type == "dlt":
        validate_unique_range(numbers["front"], 1, 35, 5)
        validate_unique_range(numbers["back"], 1, 12, 2)
    elif lottery_type == "qlc":
        validate_unique_range(numbers["basic"], 1, 30, 7)
    elif lottery_type == "kl8":
        count = int(numbers.get("play_count") or len(numbers["nums"]))
        if count < 1 or count > 10:
            raise ValueError("快乐8只支持选一至选十")
        validate_unique_range(numbers["nums"], 1, 80, count)
    elif lottery_type in {"qxc", "pl5", "fc3d", "pl3"}:
        expected = {"qxc": 7, "pl5": 5, "fc3d": 3, "pl3": 3}[lottery_type]
        values = numbers["digits"]
        if len(values) != expected or any(n < 0 or n > 9 for n in values):
            raise ValueError("位数型彩票号码必须是 0-9 的固定长度数字")
        if lottery_type in {"fc3d", "pl3"} and play_type == "group6" and len(set(values)) != 3:
            raise ValueError("组六要求三个不同数字")
        if lottery_type in {"fc3d", "pl3"} and play_type == "group3" and len(set(values)) != 2:
            raise ValueError("组三要求两个不同数字且其中一个重复")


def validate_unique_range(values: list[int], min_value: int, max_value: int, count: int) -> None:
    if len(values) != count:
        raise ValueError(f"号码数量应为 {count}")
    if len(set(values)) != len(values):
        raise ValueError("号码不能重复")
    if any(n < min_value or n > max_value for n in values):
        raise ValueError(f"号码范围应为 {min_value}-{max_value}")
