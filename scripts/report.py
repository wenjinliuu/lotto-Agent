from __future__ import annotations

from datetime import date, timedelta

import database
from followup import add as add_followup


def date_range(report_type: str) -> tuple[str, str]:
    today = date.today()
    if report_type == "weekly":
        start = today - timedelta(days=today.weekday())
    elif report_type == "monthly":
        start = today.replace(day=1)
    else:
        start = today
    return start.isoformat(), today.isoformat()


def build_report(report_type: str = "daily", user_platform_id: str | None = None) -> dict:
    database.init_db()
    start, end = date_range(report_type)
    user_filter = ""
    ticket_params: list = [start, end]
    result_params: list = [start, end]
    if user_platform_id:
        user_filter = " AND u.platform_user_id = ?"
        ticket_params.append(user_platform_id)
        result_params.append(user_platform_id)

    tickets = database.fetch_all(
        f"""
        SELECT t.lottery_type, t.cost, t.ticket_status, t.is_purchased
        FROM tickets t LEFT JOIN users u ON u.id = t.user_id
        WHERE substr(t.created_at, 1, 10) BETWEEN ? AND ? {user_filter}
        """,
        ticket_params,
    )
    purchased = [item for item in tickets if item["is_purchased"] and item["ticket_status"] not in {"cancelled", "replaced"}]
    generated_only = [item for item in tickets if not item["is_purchased"] and item["ticket_status"] == "generated"]
    cancelled = [item for item in tickets if item["ticket_status"] == "cancelled"]
    replaced = [item for item in tickets if item["ticket_status"] == "replaced"]

    results = database.fetch_all(
        f"""
        SELECT pr.*, t.lottery_type
        FROM prize_results pr
        JOIN tickets t ON t.id = pr.ticket_id
        LEFT JOIN users u ON u.id = t.user_id
        WHERE substr(pr.checked_at, 1, 10) BETWEEN ? AND ?
          AND t.is_purchased = 1
          AND COALESCE(t.ticket_status, 'generated') != 'cancelled'
          {user_filter}
        ORDER BY pr.checked_at DESC LIMIT 20
        """,
        result_params,
    )

    cost = sum(float(item["cost"] or 0) for item in purchased)
    prize = sum(float(item["prize_amount"] or 0) for item in results)
    pending = sum(1 for item in results if item.get("is_pending_amount"))
    winning_count = sum(1 for item in results if item["is_winning"])
    by_lottery: dict[str, int] = {}
    for item in purchased:
        by_lottery[item["lottery_type"]] = by_lottery.get(item["lottery_type"], 0) + 1
    by_level: dict[str, int] = {}
    for item in results:
        if item["is_winning"]:
            name = item["prize_name"] or item["prize_level"] or "中奖"
            by_level[name] = by_level.get(name, 0) + 1

    lines = [
        f"{label(report_type)} {start} 至 {end}",
        f"已购买：{len(purchased)} 注",
        f"仅生成未购买：{len(generated_only)} 注",
        f"已替换：{len(replaced)} 注",
        f"已取消：{len(cancelled)} 注",
        f"投入：{cost:g} 元",
        f"回报：{prize:g} 元",
        f"盈亏：{prize - cost:g} 元",
        f"中奖次数：{winning_count}",
        f"浮动奖金待确认：{pending}",
        "彩种占比：" + (", ".join(f"{k}:{v}" for k, v in by_lottery.items()) or "-"),
        "奖级命中：" + (", ".join(f"{k}:{v}" for k, v in by_level.items()) or "-"),
    ]
    content = "\n".join(lines)
    with database.connect() as conn:
        user_id = None
        if user_platform_id:
            row = conn.execute("SELECT id FROM users WHERE platform_user_id = ?", (user_platform_id,)).fetchone()
            user_id = row["id"] if row else None
        conn.execute(
            "INSERT INTO reports(user_id, report_type, start_date, end_date, content, created_at) VALUES (?, ?, ?, ?, ?, datetime('now'))",
            (user_id, report_type, start, end, content),
        )
        conn.commit()
    result = {"ok": True, "report_type": report_type, "content": content, "wechat_text": content}
    add_followup(result, "report", f"{report_type}:{start}:{end}")
    return result


def label(report_type: str) -> str:
    return {"daily": "日报", "weekly": "周报", "monthly": "月报"}.get(report_type, "报告")
