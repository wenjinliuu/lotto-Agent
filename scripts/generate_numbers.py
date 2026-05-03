from __future__ import annotations

from typing import Any
from collections import defaultdict

import crypto_random
import database
from draw_calendar import resolve_tracking_info as resolve_calendar_tracking
from followup import add as add_followup, add_note
from onboarding import add_purchase_onboarding
from utils import CONFIG_DIR, load_json, normalize_lottery_type, now_iso, pad_number


RULES = load_json(CONFIG_DIR / "lottery_rules.json", {})
FORMAT = load_json(CONFIG_DIR / "output_format.json", {})
PREFERENCES = load_json(CONFIG_DIR / "preferences.json", {})


def generate_one(lottery_type: str, play_type: str | None = None) -> dict[str, Any]:
    key = normalize_lottery_type(lottery_type, RULES)
    config = RULES["lotteries"][key]
    play_type = str(play_type or config.get("default_play_type", "standard"))

    if key in {"fc3d", "pl3"}:
        return {"digits": generate_digit3(play_type), "play_type": play_type}
    if key == "kl8":
        count = int(play_type)
        section = config["sections"][0]
        return {"nums": crypto_random.pick_unique(section["min"], section["max"], count, True), "play_count": count, "play_type": play_type}

    numbers: dict[str, Any] = {}
    for section in config["sections"]:
        if section["unique"]:
            values = crypto_random.pick_unique(section["min"], section["max"], section["count"], section.get("sort", True))
        else:
            values = crypto_random.pick_digits(section["count"], section["min"], section["max"])
        numbers[section["key"]] = values
    return numbers


def generate_digit3(play_type: str) -> list[int]:
    if play_type == "group6":
        return crypto_random.pick_unique(0, 9, 3, False)
    if play_type == "group3":
        pair = crypto_random.pick_unique(0, 9, 2, False)
        repeated = crypto_random.choice(pair)
        values = pair + [repeated]
        # 组三要求不排序，洗牌由逐位 crypto 选择完成。
        result: list[int] = []
        pool = values[:]
        while pool:
            result.append(pool.pop(crypto_random.rand_int(0, len(pool) - 1)))
        return result
    return crypto_random.pick_digits(3)


def ticket_cost(lottery_type: str, count: int, multiple: int = 1, is_additional: bool = False) -> float:
    config = RULES["lotteries"][lottery_type]
    price = float(config.get("price", 2))
    if is_additional:
        price += float(config.get("additional_price", 0))
    return price * count * multiple


def default_multiple(lottery_type: str) -> int:
    return max(1, int(PREFERENCES.get("default_multiple", {}).get(lottery_type, 1)))


def default_additional(lottery_type: str, config: dict[str, Any]) -> bool:
    if lottery_type in PREFERENCES.get("default_additional", {}):
        return bool(PREFERENCES["default_additional"][lottery_type])
    return bool(config.get("default_additional", False))


def default_play_type(lottery_type: str, config: dict[str, Any]) -> str:
    return str(PREFERENCES.get("default_play_type", {}).get(lottery_type, config.get("default_play_type", "standard")))


def format_numbers(lottery_type: str, numbers: dict[str, Any]) -> str:
    sep = FORMAT.get("separator", "  ")
    plus = FORMAT.get("plus_separator", " + ")
    key = normalize_lottery_type(lottery_type, RULES)
    if key == "ssq":
        return sep.join(pad_number(n) for n in numbers["red"]) + plus + sep.join(pad_number(n) for n in numbers["blue"])
    if key == "dlt":
        return sep.join(pad_number(n) for n in numbers["front"]) + plus + sep.join(pad_number(n) for n in numbers["back"])
    if key == "qlc":
        return sep.join(pad_number(n) for n in numbers["basic"])
    if key == "kl8":
        return sep.join(pad_number(n) for n in numbers["nums"])
    return sep.join(str(n) for n in numbers["digits"])


def generate(
    lottery_type: str,
    count: int = 1,
    budget: float | None = None,
    play_type: str | None = None,
    user_platform_id: str = "self",
    issue: str | None = None,
    draw_date: str | None = None,
    multiple: int = 1,
    is_additional: bool | None = None,
    is_purchased: bool = True,
    source: str = "message",
    user_command: str | None = None,
    batch_status: str | None = None,
    replaced_by_batch_id: int | None = None,
    save: bool = True,
) -> dict[str, Any]:
    database.init_db()
    key = normalize_lottery_type(lottery_type, RULES)
    config = RULES["lotteries"][key]
    if is_additional is None:
        is_additional = default_additional(key, config)
    multiple = max(1, int(multiple or default_multiple(key)))
    if budget is not None:
        unit = ticket_cost(key, 1, multiple, bool(is_additional))
        count = max(1, int(float(budget) // unit))
    count = max(1, int(count))
    play_type = play_type or default_play_type(key, config)
    is_additional = bool(is_additional)
    tracking = resolve_calendar_tracking(key, issue, draw_date)
    issue = tracking.issue
    draw_date = tracking.draw_date
    user_id = database.ensure_user(user_platform_id)
    status = batch_status or ("purchased" if is_purchased else "generated")
    batch_id = None
    if save:
        batch_id = database.create_ticket_batch(
            {
                "user_id": user_id,
                "lottery_type": key,
                "play_type": play_type,
                "issue": issue,
                "draw_date": draw_date,
                "count": count,
                "budget": budget,
                "total_cost": ticket_cost(key, count, multiple, is_additional),
                "multiple": multiple,
                "is_additional": is_additional,
                "batch_status": status,
                "source": source,
                "user_command": user_command,
                "replaced_by_batch_id": replaced_by_batch_id,
                "created_at": now_iso(),
            }
        )

    tickets = []
    for _ in range(count):
        numbers = generate_one(key, play_type)
        cost = ticket_cost(key, 1, multiple, is_additional)
        ticket = {
            "batch_id": batch_id,
            "user_id": user_id,
            "lottery_type": key,
            "lottery_name": config["name"],
            "play_type": numbers.get("play_type", play_type),
            "issue": issue,
            "draw_date": draw_date,
            "numbers": numbers,
            "formatted": format_numbers(key, numbers),
            "cost": cost,
            "multiple": multiple,
            "is_additional": is_additional,
            "is_purchased": is_purchased,
            "ticket_status": status,
            "replaced_by_batch_id": replaced_by_batch_id,
            "purchase_confirmed_at": now_iso() if is_purchased else None,
            "source": source,
            "created_at": now_iso(),
            "tracking_status": tracking.status,
        }
        if save:
            ticket["id"] = database.insert_ticket(ticket)
        tickets.append(ticket)

    total_cost = sum(float(ticket["cost"]) for ticket in tickets)
    if save and batch_id:
        database.update_ticket_batch(batch_id, {"total_cost": total_cost, "count": len(tickets)})
    text = render_message(key, tickets, total_cost)
    result = {
        "ok": True,
        "lottery_type": key,
        "batch_id": batch_id,
        "tickets": tickets,
        "total_cost": total_cost,
        "tracking": tracking.__dict__,
        "notice_text": tracking.note,
        "message_text": text,
    }
    add_followup(result, "generate_purchased" if is_purchased else "generate_preview", batch_id or text)
    add_note(result, tracking.note, seed=batch_id or text)
    if is_purchased:
        add_purchase_onboarding(result, user_platform_id)
    return result


def generate_plan(
    lottery_type: str,
    items: list[dict[str, Any]],
    user_platform_id: str = "self",
    issue: str | None = None,
    draw_date: str | None = None,
    is_purchased: bool = True,
    source: str = "message",
    user_command: str | None = None,
    save: bool = True,
) -> dict[str, Any]:
    database.init_db()
    key = normalize_lottery_type(lottery_type, RULES)
    config = RULES["lotteries"][key]
    tracking = resolve_calendar_tracking(key, issue, draw_date)
    issue = tracking.issue
    draw_date = tracking.draw_date
    user_id = database.ensure_user(user_platform_id)
    normalized_items = [normalize_plan_item(key, config, item) for item in items]
    total_count = sum(item["count"] for item in normalized_items)
    total_cost = sum(ticket_cost(key, item["count"], item["multiple"], item["is_additional"]) for item in normalized_items)
    status = "purchased" if is_purchased else "generated"
    batch_id = None
    if save:
        batch_id = database.create_ticket_batch(
            {
                "user_id": user_id,
                "lottery_type": key,
                "play_type": "mixed" if len({item["play_type"] for item in normalized_items}) > 1 else normalized_items[0]["play_type"],
                "issue": issue,
                "draw_date": draw_date,
                "count": total_count,
                "total_cost": total_cost,
                "multiple": 1,
                "is_additional": any(item["is_additional"] for item in normalized_items),
                "batch_status": status,
                "source": source,
                "user_command": user_command,
                "created_at": now_iso(),
            }
        )
    tickets: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    for item in normalized_items:
        group_tickets = []
        for _ in range(item["count"]):
            numbers = generate_one(key, item["play_type"])
            cost = ticket_cost(key, 1, item["multiple"], item["is_additional"])
            ticket = {
                "batch_id": batch_id,
                "user_id": user_id,
                "lottery_type": key,
                "lottery_name": config["name"],
                "play_type": numbers.get("play_type", item["play_type"]),
                "issue": issue,
                "draw_date": draw_date,
                "numbers": numbers,
                "formatted": format_numbers(key, numbers),
                "cost": cost,
                "multiple": item["multiple"],
                "is_additional": item["is_additional"],
                "is_purchased": is_purchased,
                "ticket_status": status,
                "purchase_confirmed_at": now_iso() if is_purchased else None,
                "source": source,
                "created_at": now_iso(),
                "tracking_status": tracking.status,
            }
            if save:
                ticket["id"] = database.insert_ticket(ticket)
            tickets.append(ticket)
            group_tickets.append(ticket)
        groups.append({"item": item, "tickets": group_tickets})
    if save and batch_id:
        database.update_ticket_batch(batch_id, {"total_cost": total_cost, "count": len(tickets)})
    text = render_plan_message(key, groups, total_cost, is_purchased, issue, draw_date, tracking.status)
    result = {
        "ok": True,
        "lottery_type": key,
        "batch_id": batch_id,
        "tickets": tickets,
        "groups": groups,
        "total_cost": total_cost,
        "tracking": tracking.__dict__,
        "notice_text": tracking.note,
        "message_text": text,
    }
    add_followup(result, "generate_purchased" if is_purchased else "generate_preview", batch_id or text)
    add_note(result, tracking.note, seed=batch_id or text)
    if is_purchased:
        add_purchase_onboarding(result, user_platform_id)
    return result


def normalize_plan_item(lottery_type: str, config: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    play_type = str(item.get("play_type") or default_play_type(lottery_type, config))
    multiple = max(1, int(item.get("multiple") or 1))
    count = max(1, int(item.get("count") or 1))
    if lottery_type == "kl8" and play_type not in config.get("play_types", []):
        play_type = str(max(1, min(10, int(play_type))))
    return {
        "play_type": play_type,
        "count": count,
        "multiple": multiple,
        "is_additional": bool(item.get("is_additional", default_additional(lottery_type, config))),
    }


def render_message(lottery_type: str, tickets: list[dict[str, Any]], total_cost: float) -> str:
    name = RULES["lotteries"][lottery_type]["name"]
    header_parts = [name]
    if lottery_type in {"fc3d", "pl3"}:
        header_parts.append(play_label(tickets[0].get("play_type")))
    if lottery_type == "kl8":
        header_parts.append(kl8_label(tickets[0].get("play_type") or tickets[0].get("numbers", {}).get("play_type")))
    header_parts.append(f"{len(tickets)}注")
    if tickets and tickets[0].get("multiple", 1) > 1:
        header_parts.append(f"{tickets[0]['multiple']}倍")
    if lottery_type == "dlt" and tickets and tickets[0].get("is_additional"):
        header_parts.append("追加")
    if tickets and not tickets[0].get("is_purchased"):
        header_parts.append("仅生成")
    lines = ["｜".join(part for part in header_parts if part and part != "标准")]
    if tickets and tickets[0].get("issue"):
        if FORMAT.get("message", {}).get("show_issue_on_generate", False):
            lines.append(f"期号：{tickets[0]['issue']}")
    elif tickets and tickets[0].get("draw_date"):
        if FORMAT.get("message", {}).get("show_draw_date_on_generate", True):
            lines.append(f"开奖：{tickets[0]['draw_date']}")
    elif tickets and tickets[0].get("tracking_status"):
        lines.append(f"开奖：待确认")
    lines.append(("参考金额" if tickets and not tickets[0].get("is_purchased") else "投入") + f"：{total_cost:g}元")
    lines.append("")
    for ticket in tickets:
        lines.append(ticket["formatted"])
    return "\n".join(lines)


def render_plan_message(lottery_type: str, groups: list[dict[str, Any]], total_cost: float, is_purchased: bool, issue: str | None, draw_date: str | None, tracking_status: str) -> str:
    name = RULES["lotteries"][lottery_type]["name"]
    total_count = sum(len(group["tickets"]) for group in groups)
    single_group = len(groups) == 1
    if single_group:
        return render_message(lottery_type, groups[0]["tickets"], total_cost)
    header = [name]
    if not is_purchased:
        header.append("仅生成")
    lines = ["｜".join(header)]
    if issue and FORMAT.get("message", {}).get("show_issue_on_generate", False):
        lines.append(f"期号：{issue}")
    elif draw_date and FORMAT.get("message", {}).get("show_draw_date_on_generate", True):
        lines.append(f"开奖：{draw_date}")
    elif tracking_status:
        lines.append("开奖：待确认")
    lines.append(("参考金额" if not is_purchased else "投入") + f"：{total_cost:g}元")
    lines.append("")
    for group in groups:
        item = group["item"]
        title = plan_group_title(lottery_type, item, len(group["tickets"]))
        lines.append(title)
        for ticket in group["tickets"]:
            lines.append(ticket["formatted"])
        lines.append("")
    return "\n".join(lines).rstrip()


def plan_group_title(lottery_type: str, item: dict[str, Any], count: int) -> str:
    parts = []
    if lottery_type in {"fc3d", "pl3"}:
        parts.append(play_label(item["play_type"]))
    elif lottery_type == "kl8":
        parts.append(kl8_label(item["play_type"]))
    parts.append(f"{count}注")
    if item.get("multiple", 1) > 1:
        parts.append(f"{item['multiple']}倍")
    if lottery_type == "dlt" and item.get("is_additional"):
        parts.append("追加")
    return "｜".join(part for part in parts if part and part != "标准")


def play_label(play_type: Any) -> str:
    return FORMAT.get("labels", {}).get(str(play_type), str(play_type or ""))


def kl8_label(play_type: Any) -> str:
    return FORMAT.get("kl8_labels", {}).get(str(play_type), f"选{play_type}")


def format_tracking_status(status: str) -> str:
    if status == "missing_next_issue":
        return "未找到下一期信息，请先更新开奖数据"
    if status == "fallback":
        return "未自动绑定期号"
    return status
