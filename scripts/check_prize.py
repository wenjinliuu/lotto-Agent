from __future__ import annotations

import json
from collections import Counter
from typing import Any

import database
from followup import add as add_followup
from utils import CONFIG_DIR, load_json, normalize_lottery_type, now_iso


RULES = load_json(CONFIG_DIR / "lottery_rules.json", {})


def count_matches(ticket: list[int], draw: list[int]) -> int:
    counts = Counter(draw or [])
    hits = 0
    for number in ticket or []:
        if counts[number] > 0:
            counts[number] -= 1
            hits += 1
    return hits


def evaluate(
    lottery_type: str,
    ticket_numbers: dict[str, Any],
    draw_numbers: dict[str, Any],
    play_type: str = "standard",
    is_additional: bool = False,
    multiple: int = 1,
    draw_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    key = normalize_lottery_type(lottery_type, RULES)
    if key == "ssq":
        return match_rule(key, {"red": count_matches(ticket_numbers["red"], draw_numbers["red"]), "blue": int(ticket_numbers["blue"][0] == draw_numbers["blue"][0])}, multiple, draw_context=draw_context)
    if key == "dlt":
        return match_rule(key, {"front": count_matches(ticket_numbers["front"], draw_numbers["front"]), "back": count_matches(ticket_numbers["back"], draw_numbers["back"])}, multiple, is_additional, draw_context)
    if key == "qlc":
        special_hit = int(draw_numbers.get("special") in ticket_numbers.get("basic", []))
        return match_rule(key, {"basic": count_matches(ticket_numbers["basic"], draw_numbers["basic"]), "special": special_hit}, multiple, draw_context=draw_context)
    if key == "qxc":
        main = sum(1 for a, b in zip(ticket_numbers["digits"][:6], draw_numbers["digits"][:6]) if a == b)
        tail = int(ticket_numbers["digits"][6] == draw_numbers["digits"][6])
        return match_rule(key, {"main": main, "tail": tail}, multiple, draw_context=draw_context)
    if key in {"fc3d", "pl3"}:
        return evaluate_digit3(ticket_numbers["digits"], draw_numbers["digits"], play_type, multiple)
    if key == "pl5":
        hit = ticket_numbers["digits"] == draw_numbers["digits"]
        return fixed("一等奖", 100000 * multiple, {"all": int(hit)}) if hit else lose({"all": 0})
    if key == "kl8":
        hits = count_matches(ticket_numbers["nums"], draw_numbers["nums"])
        table = RULES["prize_rules"]["kl8"].get(str(ticket_numbers.get("play_count") or play_type), {})
        amount = float(table.get(str(hits), 0)) * multiple
        return fixed(f"中{hits}", amount, {"matches": hits}) if amount else lose({"matches": hits})
    return lose({})


def match_rule(key: str, facts: dict[str, int], multiple: int = 1, is_additional: bool = False, draw_context: dict[str, Any] | None = None) -> dict[str, Any]:
    for rule in RULES["prize_rules"][key]:
        candidates = rule.get("any") or [rule.get("when", {})]
        if any(all(facts.get(k) == v for k, v in candidate.items()) for candidate in candidates):
            amount_from_api = api_prize_amount(rule["level"], draw_context, is_additional)
            if rule.get("float"):
                return {
                    "is_winning": True,
                    "prize_level": rule["level"],
                    "prize_name": rule["level"],
                    "prize_amount": amount_from_api * multiple if amount_from_api is not None else 0,
                    "is_float": amount_from_api is None,
                    "is_pending_amount": amount_from_api is None,
                    "prize_source": "api_prize_detail" if amount_from_api is not None else "pending_api_amount",
                    "hit_summary": facts,
                }
            amount = dlt_pool_amount(rule["level"], draw_context)
            if amount is None:
                amount = amount_from_api if amount_from_api is not None else float(rule.get("amount", 0))
            if is_additional:
                amount += api_additional_amount(rule["level"], draw_context) or float(rule.get("additional_amount", 0))
            source = "dlt_pool_rule" if key == "dlt" and draw_context else "rule"
            if amount_from_api is not None and key != "dlt":
                source = "api_prize_detail"
            return fixed(rule["level"], amount * multiple, facts, prize_source=source)
    return lose(facts)


def dlt_pool_amount(level: str, draw_context: dict[str, Any] | None) -> float | None:
    if not draw_context or draw_context.get("lottery_type") != "dlt":
        return None
    amounts = RULES["prize_rules"].get("dlt_pool_amounts", {})
    under = amounts.get("under", {})
    over = amounts.get("at_or_over", {})
    if level not in under and level not in over:
        return None
    prize_pool = parse_money(draw_context.get("prize_pool"))
    threshold = float(RULES["prize_rules"].get("dlt_pool_threshold", 800000000))
    table = over if prize_pool >= threshold else under
    return float(table.get(level, under.get(level, 0)))


def api_prize_amount(level: str, draw_context: dict[str, Any] | None, include_additional: bool = False) -> float | None:
    if not draw_context:
        return None
    for detail in draw_context.get("prize_details", []):
        if level and (level == detail.get("prize_level") or level == detail.get("prize_name")):
            amount = parse_money(detail.get("prize_amount"))
            if include_additional:
                amount += parse_money(detail.get("additional_amount"))
            return amount if amount > 0 else None
    return None


def api_additional_amount(level: str, draw_context: dict[str, Any] | None) -> float | None:
    if not draw_context:
        return None
    for detail in draw_context.get("prize_details", []):
        if level and (level == detail.get("prize_level") or level == detail.get("prize_name")):
            amount = parse_money(detail.get("additional_amount"))
            return amount if amount > 0 else None
    return None


def parse_money(value: Any) -> float:
    text = str(value or "").strip().replace(",", "").replace("，", "").replace("元", "")
    if not text:
        return 0
    multiplier = 1
    if "亿" in text:
        multiplier = 100000000
        text = text.replace("亿", "")
    elif "万" in text:
        multiplier = 10000
        text = text.replace("万", "")
    try:
        return float(text) * multiplier
    except ValueError:
        digits = "".join(ch for ch in text if ch.isdigit() or ch == ".")
        return float(digits) * multiplier if digits else 0


def evaluate_digit3(ticket: list[int], draw: list[int], play_type: str, multiple: int) -> dict[str, Any]:
    rules = RULES["prize_rules"]["digit3"]
    if play_type == "single":
        return fixed(rules["single"]["level"], rules["single"]["amount"] * multiple, {"position": 3}) if ticket == draw else lose({"position": sum(a == b for a, b in zip(ticket, draw))})
    if play_type == "group3":
        ok = len(set(draw)) == 2 and Counter(ticket) == Counter(draw)
        return fixed(rules["group3"]["level"], rules["group3"]["amount"] * multiple, {"group": int(ok)}) if ok else lose({"group": 0})
    ok = len(set(draw)) == 3 and Counter(ticket) == Counter(draw)
    return fixed(rules["group6"]["level"], rules["group6"]["amount"] * multiple, {"group": int(ok)}) if ok else lose({"group": 0})


def fixed(level: str, amount: float, hit_summary: dict[str, Any], prize_source: str = "rule") -> dict[str, Any]:
    return {"is_winning": True, "prize_level": level, "prize_name": level, "prize_amount": amount, "is_float": False, "is_pending_amount": False, "prize_source": prize_source, "hit_summary": hit_summary}


def lose(hit_summary: dict[str, Any]) -> dict[str, Any]:
    return {"is_winning": False, "prize_level": "", "prize_name": "未中奖", "prize_amount": 0, "is_float": False, "is_pending_amount": False, "prize_source": "rule", "hit_summary": hit_summary}


def check_prize(lottery_type: str | None = None, issue: str | None = None, user_platform_id: str | None = None) -> dict[str, Any]:
    database.init_db()
    params: list[Any] = []
    where = ["1=1"]
    if lottery_type:
        where.append("t.lottery_type = ?")
        params.append(normalize_lottery_type(lottery_type, RULES))
    if issue:
        where.append("COALESCE(t.issue, d.issue) = ?")
        params.append(issue)
    if user_platform_id:
        where.append("u.platform_user_id = ?")
        params.append(user_platform_id)
    query = f"""
      SELECT t.*, d.id AS draw_id, d.numbers_json AS draw_numbers_json, d.issue AS draw_issue, d.prize_pool AS draw_prize_pool
      FROM tickets t
      JOIN draws d ON d.lottery_type = t.lottery_type
        AND (
          (t.issue IS NOT NULL AND t.issue = d.issue)
          OR (t.issue IS NULL AND t.draw_date IS NOT NULL AND t.draw_date = d.draw_date)
        )
      LEFT JOIN users u ON u.id = t.user_id
      WHERE {' AND '.join(where)}
        AND t.is_purchased = 1
        AND COALESCE(t.ticket_status, 'generated') NOT IN ('cancelled', 'replaced')
      ORDER BY t.id DESC
    """
    checked = []
    with database.connect() as conn:
        for row in conn.execute(query, params).fetchall():
            ticket = dict(row)
            prize_details = [
                dict(detail)
                for detail in conn.execute(
                    "SELECT prize_level, prize_name, prize_amount, additional_amount, winning_count, additional_count FROM draw_prize_details WHERE draw_id = ?",
                    (ticket["draw_id"],),
                ).fetchall()
            ]
            result = evaluate(
                ticket["lottery_type"],
                json.loads(ticket["numbers_json"]),
                json.loads(ticket["draw_numbers_json"]),
                ticket.get("play_type") or "standard",
                bool(ticket.get("is_additional")),
                int(ticket.get("multiple") or 1),
                {
                    "lottery_type": ticket["lottery_type"],
                    "issue": ticket["draw_issue"],
                    "prize_pool": ticket["draw_prize_pool"],
                    "prize_details": prize_details,
                },
            )
            result.update({"ticket_id": ticket["id"], "draw_id": ticket["draw_id"], "checked_at": now_iso()})
            database.insert_prize_result(result, conn)
            conn.execute(
                """
                UPDATE tickets
                SET ticket_status = ?
                WHERE id = ?
                  AND COALESCE(ticket_status, 'generated') NOT IN ('cancelled', 'replaced')
                """,
                ("won" if result["is_winning"] else "lost", ticket["id"]),
            )
            checked.append(result)
        conn.commit()
    win_count = len([item for item in checked if item["is_winning"]])
    amount = sum(float(item["prize_amount"]) for item in checked)
    result = {"ok": True, "checked_count": len(checked), "winning_count": win_count, "total_amount": amount, "results": checked, "wechat_text": f"兑奖完成：{len(checked)} 注，中奖 {win_count} 注，金额 {amount:g} 元"}
    if len(checked) <= 0:
        add_followup(result, "prize_empty", f"{lottery_type}:{issue}:{user_platform_id}")
    elif win_count > 0:
        add_followup(result, "prize_win", f"{lottery_type}:{issue}:{amount}")
    else:
        add_followup(result, "prize_no_win", f"{lottery_type}:{issue}:{len(checked)}")
    return result
