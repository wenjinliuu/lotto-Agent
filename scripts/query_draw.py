from __future__ import annotations

import json
from typing import Any

import database
from fetch_draw import fetch_draw, format_draw_numbers
from utils import CONFIG_DIR, load_json, normalize_lottery_type


RULES = load_json(CONFIG_DIR / "lottery_rules.json", {})


def query_draw_detail(
    lottery_type: str | None = None,
    issue: str | None = None,
    prize_level: str | None = None,
    latest: bool = True,
    auto_fetch: bool = True,
    source: str | None = None,
) -> dict[str, Any]:
    database.init_db()
    key = normalize_lottery_type(lottery_type or "dlt", RULES)
    draw = find_draw(key, issue, latest)
    sync_result = None
    if auto_fetch and should_sync_draw(draw):
        sync_result = fetch_draw(key, issue=issue, source=source)
        draw = find_draw(key, issue, latest)

    if not draw:
        target = f"第{issue}期" if issue else "最近一期"
        sync_error = sync_result.get("error") if isinstance(sync_result, dict) else ""
        message = f"数据库里没有找到{RULES['lotteries'][key]['name']}{target}开奖数据"
        if sync_error:
            message += f"，已尝试从公共开奖源同步但失败：{sync_error}"
        return {"ok": False, "error": message, "sync_result": sync_result}

    if auto_fetch and not find_prize_details(int(draw["id"])) and sync_result is None:
        sync_result = fetch_draw(key, issue=draw.get("issue") or issue, source=source)
        draw = find_draw(key, issue or draw.get("issue"), latest)
        if not draw:
            return {"ok": False, "error": "开奖数据同步后仍未找到本期开奖数据", "sync_result": sync_result}

    details = find_prize_details(int(draw["id"]), prize_level)
    text = render_draw_detail(draw, details, prize_level)
    return {"ok": True, "draw": draw, "prize_details": details, "sync_result": sync_result, "message_text": text}


def should_sync_draw(draw: dict[str, Any] | None) -> bool:
    if not draw:
        return True
    return False


def find_draw(lottery_type: str, issue: str | None, latest: bool) -> dict[str, Any] | None:
    if issue:
        rows = database.fetch_all(
            """
            SELECT *
            FROM draws
            WHERE lottery_type = ? AND issue = ?
            LIMIT 1
            """,
            (lottery_type, issue),
        )
    else:
        rows = database.fetch_all(
            """
            SELECT *
            FROM draws
            WHERE lottery_type = ?
            ORDER BY COALESCE(draw_date, '') DESC, issue DESC
            LIMIT 1
            """,
            (lottery_type,),
        )
    return rows[0] if rows else None


def find_prize_details(draw_id: int, prize_level: str | None = None) -> list[dict[str, Any]]:
    rows = database.fetch_all(
        """
        SELECT *
        FROM draw_prize_details
        WHERE draw_id = ?
        ORDER BY id ASC
        """,
        (draw_id,),
    )
    if not prize_level:
        return rows
    needle = normalize_prize_level(prize_level)
    return [row for row in rows if prize_matches(row, needle)]


def render_draw_detail(draw: dict[str, Any], details: list[dict[str, Any]], prize_level: str | None) -> str:
    lottery_name = RULES["lotteries"][draw["lottery_type"]]["name"]
    numbers = parse_numbers(draw.get("numbers_json"))
    lines = [
        f"{lottery_name} 第{draw['issue']}期开奖",
        format_draw_numbers(draw["lottery_type"], numbers),
        f"开奖：{draw.get('draw_date') or '-'}",
    ]
    if draw.get("sales_amount"):
        lines.append(f"销量：{draw['sales_amount']}")
    if draw.get("prize_pool"):
        lines.append(f"奖池：{draw['prize_pool']}")
    if draw.get("deadline"):
        lines.append(f"兑奖截止：{draw['deadline']}")
    lines.append("")

    if not details:
        label = prize_level or "奖项明细"
        lines.append(f"未找到{label}数据")
        return "\n".join(lines)

    for detail in details:
        lines.append(format_prize_detail(detail))
    return "\n".join(lines)


def format_prize_detail(detail: dict[str, Any]) -> str:
    name = detail.get("prize_name") or detail.get("prize_level") or "奖项"
    count = format_count(detail.get("winning_count"))
    amount = detail.get("prize_amount") or "-"
    parts = [f"{name}：{count}注", f"单注{amount}"]
    additional_count = detail.get("additional_count")
    additional_amount = detail.get("additional_amount")
    if additional_count not in (None, "", 0) or additional_amount:
        parts.append(f"追加{format_count(additional_count)}注")
        parts.append(f"追加单注{additional_amount or '-'}")
    return "，".join(parts)


def parse_numbers(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def normalize_prize_level(value: str | None) -> str:
    text = str(value or "").strip()
    replacements = {
        "一等": "一等奖",
        "二等": "二等奖",
        "三等": "三等奖",
        "四等": "四等奖",
        "五等": "五等奖",
        "六等": "六等奖",
        "七等": "七等奖",
        "八等": "八等奖",
        "九等": "九等奖",
        "特等": "特等奖",
    }
    return replacements.get(text, text)


def prize_matches(row: dict[str, Any], needle: str) -> bool:
    haystack = f"{row.get('prize_level') or ''} {row.get('prize_name') or ''}"
    return needle in haystack or haystack in needle


def format_count(value: Any) -> str:
    if value in (None, ""):
        return "-"
    return str(value)
