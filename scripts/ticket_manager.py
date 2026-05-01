from __future__ import annotations

import json
from typing import Any

import database
from followup import add as add_followup
from generate_numbers import format_numbers, generate
from utils import CONFIG_DIR, load_json, normalize_lottery_type, now_iso


RULES = load_json(CONFIG_DIR / "lottery_rules.json", {})


def confirm_recent(user_platform_id: str = "wechat_self", limit: int = 20, ticket_ids: list[int] | None = None) -> dict[str, Any]:
    return update_ticket_status(
        user_platform_id=user_platform_id,
        status="purchased",
        limit=limit,
        ticket_ids=ticket_ids,
        updates={"is_purchased": 1, "purchase_confirmed_at": now_iso(), "cancelled_at": None},
    )


def cancel_recent(user_platform_id: str = "wechat_self", limit: int = 20, ticket_ids: list[int] | None = None, notes: str = "") -> dict[str, Any]:
    if ticket_ids is None:
        batch = latest_batch(user_platform_id)
        if batch:
            return cancel_batch(int(batch["id"]), notes)
    return update_ticket_status(
        user_platform_id=user_platform_id,
        status="cancelled",
        limit=limit,
        ticket_ids=ticket_ids,
        updates={"is_purchased": 0, "cancelled_at": now_iso(), "notes": notes},
    )


def update_ticket_status(user_platform_id: str, status: str, limit: int, ticket_ids: list[int] | None, updates: dict[str, Any]) -> dict[str, Any]:
    database.init_db()
    with database.connect() as conn:
        rows = select_target_tickets(conn, user_platform_id, limit, ticket_ids)
        for row in rows:
            conn.execute(
                """
                UPDATE tickets
                SET ticket_status = ?,
                    is_purchased = ?,
                    purchase_confirmed_at = COALESCE(?, purchase_confirmed_at),
                    cancelled_at = COALESCE(?, cancelled_at),
                    notes = COALESCE(?, notes)
                WHERE id = ?
                """,
                (
                    status,
                    int(updates.get("is_purchased", row["is_purchased"])),
                    updates.get("purchase_confirmed_at"),
                    updates.get("cancelled_at"),
                    updates.get("notes"),
                    row["id"],
                ),
            )
        conn.commit()
    action_text = "已确认购买" if status == "purchased" else "已取消统计"
    result = {"ok": True, "updated_count": len(rows), "ticket_ids": [row["id"] for row in rows], "wechat_text": f"{action_text} {len(rows)} 注。"}
    add_followup(result, "confirm" if status == "purchased" else "cancel", ",".join(str(row["id"]) for row in rows))
    return result


def latest_batch(user_platform_id: str = "wechat_self") -> dict[str, Any] | None:
    database.init_db()
    with database.connect() as conn:
        row = conn.execute(
            """
            SELECT b.*
            FROM ticket_batches b LEFT JOIN users u ON u.id = b.user_id
            WHERE (u.platform_user_id = ? OR ? = '')
              AND COALESCE(b.batch_status, 'purchased') NOT IN ('cancelled', 'replaced')
            ORDER BY b.id DESC
            LIMIT 1
            """,
            (user_platform_id, user_platform_id),
        ).fetchone()
    return dict(row) if row else None


def cancel_batch(batch_id: int, notes: str = "") -> dict[str, Any]:
    database.init_db()
    with database.connect() as conn:
        conn.execute(
            """
            UPDATE ticket_batches
            SET batch_status = 'cancelled', updated_at = ?
            WHERE id = ?
            """,
            (now_iso(), batch_id),
        )
        cursor = conn.execute(
            """
            UPDATE tickets
            SET ticket_status = 'cancelled',
                is_purchased = 0,
                cancelled_at = ?,
                notes = COALESCE(NULLIF(?, ''), notes)
            WHERE batch_id = ?
            """,
            (now_iso(), notes, batch_id),
        )
        conn.commit()
    result = {"ok": True, "updated_count": cursor.rowcount, "batch_id": batch_id, "wechat_text": f"已取消上一组 {cursor.rowcount} 注，不计入成本。"}
    add_followup(result, "cancel", batch_id)
    return result


def replace_last_batch(user_platform_id: str = "wechat_self", overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    batch = latest_batch(user_platform_id)
    if not batch:
        return {"ok": False, "error": "没有找到可替换的上一组号码"}
    database.init_db()
    overrides = overrides or {}
    with database.connect() as conn:
        conn.execute(
            "UPDATE ticket_batches SET batch_status = 'replaced', updated_at = ? WHERE id = ?",
            (now_iso(), batch["id"]),
        )
        conn.execute(
            """
            UPDATE tickets
            SET ticket_status = 'replaced', is_purchased = 0, cancelled_at = ?
            WHERE batch_id = ?
            """,
            (now_iso(), batch["id"]),
        )
        conn.commit()
    result = generate(
        overrides.get("lottery_type") or batch["lottery_type"],
        count=int(overrides.get("count") or batch["count"] or 1),
        budget=overrides.get("budget"),
        play_type=overrides.get("play_type") or batch["play_type"],
        user_platform_id=user_platform_id,
        issue=overrides.get("issue") or batch["issue"],
        draw_date=overrides.get("draw_date") or batch["draw_date"],
        multiple=int(overrides.get("multiple") or batch["multiple"] or 1),
        is_additional=bool(overrides.get("is_additional", bool(batch["is_additional"]))),
        is_purchased=bool(overrides.get("is_purchased", True)),
        source="replace",
        user_command=overrides.get("user_command"),
        replaced_by_batch_id=int(batch["id"]),
    )
    result["replaced_batch_id"] = int(batch["id"])
    result["wechat_text"] = f"上一组已取消并重新生成：\n{result['wechat_text']}"
    add_followup(result, "replace", batch["id"])
    return result


def select_target_tickets(conn, user_platform_id: str, limit: int, ticket_ids: list[int] | None) -> list[Any]:
    if ticket_ids:
        placeholders = ",".join("?" for _ in ticket_ids)
        return conn.execute(
            f"""
            SELECT t.*
            FROM tickets t LEFT JOIN users u ON u.id = t.user_id
            WHERE t.id IN ({placeholders}) AND (u.platform_user_id = ? OR ? = '')
            ORDER BY t.id DESC
            """,
            [*ticket_ids, user_platform_id, user_platform_id],
        ).fetchall()
    return conn.execute(
        """
        SELECT t.*
        FROM tickets t LEFT JOIN users u ON u.id = t.user_id
        WHERE (u.platform_user_id = ? OR ? = '')
          AND COALESCE(t.ticket_status, 'generated') = 'generated'
        ORDER BY t.id DESC
        LIMIT ?
        """,
        (user_platform_id, user_platform_id, max(1, int(limit))),
    ).fetchall()


def recent_tickets(user_platform_id: str = "wechat_self", limit: int = 10) -> dict[str, Any]:
    database.init_db()
    rows = database.fetch_all(
        """
        SELECT t.*
        FROM tickets t LEFT JOIN users u ON u.id = t.user_id
        WHERE u.platform_user_id = ? OR ? = ''
        ORDER BY t.id DESC
        LIMIT ?
        """,
        (user_platform_id, user_platform_id, max(1, int(limit))),
    )
    lines = [f"最近 {len(rows)} 注记录"]
    for row in rows:
        numbers = json.loads(row["numbers_json"])
        try:
            formatted = format_numbers(row["lottery_type"], numbers)
        except Exception:
            formatted = row["numbers_json"]
        status = row.get("ticket_status") or ("purchased" if row.get("is_purchased") else "generated")
        batch = f"B{row.get('batch_id')}" if row.get("batch_id") else "-"
        lines.append(f"#{row['id']} {batch} {row['lottery_type']} {formatted} [{status}] {row.get('issue') or row.get('draw_date') or ''}")
    return {"ok": True, "tickets": rows, "wechat_text": "\n".join(lines)}


def parse_ticket_ids(value: Any) -> list[int] | None:
    if value in (None, ""):
        return None
    if isinstance(value, list):
        return [int(item) for item in value]
    return [int(item.strip()) for item in str(value).replace("，", ",").split(",") if item.strip()]
