from __future__ import annotations

from typing import Any

from utils import CONFIG_DIR, load_json, now_iso


RULES = load_json(CONFIG_DIR / "lottery_rules.json", {})


def extract_numbers(value: Any) -> list[int]:
    import re

    return [int(item) for item in re.findall(r"\d+", str(value or ""))]


def build_open_numbers(lottery_type: str, data: dict[str, Any]) -> dict[str, Any]:
    main = extract_numbers(data.get("number"))
    refer = extract_numbers(data.get("refernumber"))
    if lottery_type == "ssq":
        return {"red": main[:6], "blue": (refer[:1] or main[6:7])}
    if lottery_type == "dlt":
        return {"front": main[:5], "back": (refer[:2] or main[5:7])}
    if lottery_type == "qlc":
        return {"basic": main[:7], "special": (refer[:1] or main[7:8] or [None])[0]}
    if lottery_type == "qxc":
        nums = main[:7] if len(main) >= 7 else main[:6] + refer[:1]
        return {"digits": nums[:7]}
    if lottery_type in {"fc3d", "pl3"}:
        digits = list("".join(str(n) for n in main))[:3]
        return {"digits": [int(n) for n in digits]}
    if lottery_type == "pl5":
        digits = list("".join(str(n) for n in main))[:5]
        return {"digits": [int(n) for n in digits]}
    if lottery_type == "kl8":
        return {"nums": main[:20]}
    return {"raw_numbers": main}


def normalize_prize_details(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result = []
    for index, item in enumerate(value, 1):
        if not isinstance(item, dict):
            item = {"value": item}
        result.append(
            {
                "prize_level": str(item.get("prizename") or item.get("prize_level") or item.get("level") or item.get("name") or index),
                "prize_name": str(item.get("prizename") or item.get("prize_name") or item.get("name") or item.get("prize_level") or ""),
                "winning_count": safe_int(item.get("num") or item.get("winning_count")),
                "prize_amount": safe_text(item.get("singlebonus") or item.get("bonus") or item.get("prize") or item.get("prize_amount")),
                "additional_count": safe_int(item.get("addnum") or item.get("additional_count")),
                "additional_amount": safe_text(item.get("addbonus") or item.get("additional_amount")),
                "raw": item,
            }
        )
    return result


def parse_jisuapi(lottery_type: str, payload: dict[str, Any], source_url: str = "") -> dict[str, Any]:
    data = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise ValueError(str(payload.get("msg") if isinstance(payload, dict) else "API 未返回 result"))
    issue = str(data.get("issueno") or data.get("issue") or "")
    if not issue:
        raise ValueError("API 响应缺少期号")
    open_date = str(data.get("opendate") or data.get("officialopendate") or "")
    return {
        "lottery_type": lottery_type,
        "caipiaoid": safe_int(data.get("caipiaoid")),
        "issue": issue,
        "draw_date": open_date[:10],
        "draw_time": open_date[11:19] if len(open_date) >= 19 else "",
        "deadline": safe_text(data.get("deadline")),
        "numbers": build_open_numbers(lottery_type, data),
        "prize_pool": safe_text(data.get("totalmoney") or data.get("poolmoney")),
        "sales_amount": safe_text(data.get("saleamount") or data.get("sales")),
        "next_issue": safe_text(data.get("nextissueno")),
        "next_draw_date": safe_text(data.get("nextopendate"))[:10],
        "next_open_time": safe_text(data.get("nextopentime")),
        "next_buy_end_time": safe_text(data.get("nextbuyendtime")),
        "source_url": source_url,
        "raw": payload,
        "fetched_at": now_iso(),
        "prize_details": normalize_prize_details(data.get("prize")),
    }


def parse_public_draw(lottery_type: str, payload: dict[str, Any], source_url: str = "") -> dict[str, Any]:
    issue = str(payload.get("issue") or "")
    if not issue:
        raise ValueError("公开开奖数据缺少期号")
    return {
        "lottery_type": lottery_type,
        "caipiaoid": safe_int(payload.get("caipiaoid")),
        "issue": issue,
        "draw_date": safe_text(payload.get("draw_date")),
        "draw_time": safe_text(payload.get("draw_time")),
        "deadline": safe_text(payload.get("deadline")),
        "numbers": payload.get("numbers", {}),
        "prize_pool": safe_text(payload.get("prize_pool")),
        "sales_amount": safe_text(payload.get("sales_amount")),
        "next_issue": safe_text(payload.get("next_issue")),
        "next_draw_date": safe_text(payload.get("next_draw_date")),
        "next_open_time": safe_text(payload.get("next_open_time")),
        "next_buy_end_time": safe_text(payload.get("next_buy_end_time")),
        "source_url": source_url or safe_text(payload.get("source_url")),
        "raw": payload,
        "fetched_at": safe_text(payload.get("fetched_at")) or now_iso(),
        "prize_details": normalize_prize_details(payload.get("prize_details", [])),
    }


def parse_manual(lottery_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    if "issue" not in payload:
        raise ValueError("手动录入需要 issue")
    return {
        "lottery_type": lottery_type,
        "issue": str(payload["issue"]),
        "draw_date": safe_text(payload.get("draw_date")),
        "draw_time": safe_text(payload.get("draw_time")),
        "numbers": payload.get("numbers", {}),
        "prize_pool": safe_text(payload.get("prize_pool")),
        "sales_amount": safe_text(payload.get("sales_amount")),
        "next_issue": safe_text(payload.get("next_issue")),
        "next_draw_date": safe_text(payload.get("next_draw_date")),
        "next_open_time": safe_text(payload.get("next_open_time")),
        "next_buy_end_time": safe_text(payload.get("next_buy_end_time")),
        "source_url": "manual",
        "raw": payload,
        "fetched_at": now_iso(),
        "prize_details": normalize_prize_details(payload.get("prize_details", [])),
    }


def safe_text(value: Any) -> str:
    return "" if value is None else str(value)


def safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None
