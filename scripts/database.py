from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from utils import DATA_DIR, now_iso


DB_PATH = DATA_DIR / "lottery.db"


SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      platform_user_id TEXT UNIQUE NOT NULL,
      display_name TEXT,
      is_allowed INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ticket_batches (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER,
      lottery_type TEXT NOT NULL,
      play_type TEXT,
      issue TEXT,
      draw_date TEXT,
      count INTEGER NOT NULL DEFAULT 0,
      budget REAL,
      total_cost REAL NOT NULL DEFAULT 0,
      multiple INTEGER NOT NULL DEFAULT 1,
      is_additional INTEGER NOT NULL DEFAULT 0,
      batch_status TEXT NOT NULL DEFAULT 'purchased',
      source TEXT,
      user_command TEXT,
      replaced_by_batch_id INTEGER,
      created_at TEXT NOT NULL,
      updated_at TEXT,
      FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tickets (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      batch_id INTEGER,
      user_id INTEGER,
      lottery_type TEXT NOT NULL,
      play_type TEXT,
      issue TEXT,
      draw_date TEXT,
      numbers_json TEXT NOT NULL,
      cost REAL NOT NULL DEFAULT 0,
      multiple INTEGER NOT NULL DEFAULT 1,
      is_additional INTEGER NOT NULL DEFAULT 0,
      is_purchased INTEGER NOT NULL DEFAULT 0,
      ticket_status TEXT NOT NULL DEFAULT 'generated',
      replaced_by_batch_id INTEGER,
      purchase_confirmed_at TEXT,
      cancelled_at TEXT,
      notes TEXT,
      tracking_status TEXT,
      source TEXT,
      created_at TEXT NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id),
      FOREIGN KEY(batch_id) REFERENCES ticket_batches(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS draws (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      lottery_type TEXT NOT NULL,
      issue TEXT NOT NULL,
      draw_date TEXT,
      draw_time TEXT,
      numbers_json TEXT NOT NULL,
      prize_pool TEXT,
      sales_amount TEXT,
      deadline TEXT,
      next_issue TEXT,
      next_draw_date TEXT,
      next_open_time TEXT,
      next_buy_end_time TEXT,
      source_url TEXT,
      raw_json TEXT NOT NULL,
      fetched_at TEXT NOT NULL,
      UNIQUE(lottery_type, issue)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS draw_prize_details (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      draw_id INTEGER NOT NULL,
      prize_level TEXT,
      prize_name TEXT,
      winning_count INTEGER,
      prize_amount TEXT,
      additional_count INTEGER,
      additional_amount TEXT,
      raw_json TEXT,
      FOREIGN KEY(draw_id) REFERENCES draws(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS prize_results (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ticket_id INTEGER NOT NULL,
      draw_id INTEGER NOT NULL,
      hit_summary TEXT,
      prize_level TEXT,
      prize_name TEXT,
      prize_amount REAL NOT NULL DEFAULT 0,
      is_pending_amount INTEGER NOT NULL DEFAULT 0,
      prize_source TEXT,
      is_winning INTEGER NOT NULL DEFAULT 0,
      checked_at TEXT NOT NULL,
      UNIQUE(ticket_id, draw_id),
      FOREIGN KEY(ticket_id) REFERENCES tickets(id),
      FOREIGN KEY(draw_id) REFERENCES draws(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reports (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER,
      report_type TEXT,
      start_date TEXT,
      end_date TEXT,
      content TEXT,
      created_at TEXT NOT NULL,
      FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
      key TEXT PRIMARY KEY,
      value_json TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS api_logs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      lottery_type TEXT,
      api_url TEXT,
      status TEXT NOT NULL,
      message TEXT,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scheduler_logs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_name TEXT,
      action TEXT,
      status TEXT NOT NULL,
      message TEXT,
      result_json TEXT,
      created_at TEXT NOT NULL
    )
    """
    ,
    """
    CREATE TABLE IF NOT EXISTS scheduled_tasks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER,
      task_name TEXT,
      action TEXT NOT NULL,
      lottery_type TEXT,
      play_type TEXT,
      payload_json TEXT NOT NULL DEFAULT '{}',
      schedule_type TEXT NOT NULL DEFAULT 'recurring',
      frequency TEXT,
      trigger_type TEXT,
      draw_day_offset INTEGER NOT NULL DEFAULT 0,
      run_date TEXT,
      weekdays_json TEXT,
      time_start TEXT,
      time_end TEXT,
      run_time_mode TEXT NOT NULL DEFAULT 'fixed',
      planned_run_key TEXT,
      planned_run_time TEXT,
      enabled INTEGER NOT NULL DEFAULT 1,
      last_run_key TEXT,
      last_run_at TEXT,
      source TEXT,
      raw_text TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT,
      FOREIGN KEY(user_id) REFERENCES users(id)
    )
    """
]


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    target = Path(db_path or DB_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    with connect(db_path) as conn:
        for statement in SCHEMA:
            conn.execute(statement)
        migrate_db(conn)
        conn.commit()


def migrate_db(conn: sqlite3.Connection) -> None:
    ensure_columns(
        conn,
        "tickets",
        {
            "batch_id": "INTEGER",
            "ticket_status": "TEXT NOT NULL DEFAULT 'generated'",
            "replaced_by_batch_id": "INTEGER",
            "purchase_confirmed_at": "TEXT",
            "cancelled_at": "TEXT",
            "notes": "TEXT",
            "tracking_status": "TEXT",
        },
    )
    ensure_columns(
        conn,
        "draws",
        {
            "deadline": "TEXT",
            "next_open_time": "TEXT",
            "next_buy_end_time": "TEXT",
        },
    )
    ensure_columns(
        conn,
        "prize_results",
        {
            "is_pending_amount": "INTEGER NOT NULL DEFAULT 0",
            "prize_source": "TEXT",
        },
    )
    ensure_columns(
        conn,
        "scheduled_tasks",
        {
            "trigger_type": "TEXT",
            "draw_day_offset": "INTEGER NOT NULL DEFAULT 0",
            "run_time_mode": "TEXT NOT NULL DEFAULT 'fixed'",
            "planned_run_key": "TEXT",
            "planned_run_time": "TEXT",
        },
    )


def create_ticket_batch(batch: dict[str, Any], conn: sqlite3.Connection | None = None) -> int:
    own_conn = conn is None
    conn = conn or connect()
    try:
        cursor = conn.execute(
            """
            INSERT INTO ticket_batches(user_id, lottery_type, play_type, issue, draw_date, count, budget, total_cost, multiple, is_additional, batch_status, source, user_command, replaced_by_batch_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch.get("user_id"),
                batch["lottery_type"],
                batch.get("play_type"),
                batch.get("issue"),
                batch.get("draw_date"),
                batch.get("count", 0),
                batch.get("budget"),
                batch.get("total_cost", 0),
                batch.get("multiple", 1),
                int(bool(batch.get("is_additional", False))),
                batch.get("batch_status", "purchased"),
                batch.get("source", "agent"),
                batch.get("user_command"),
                batch.get("replaced_by_batch_id"),
                batch.get("created_at", now_iso()),
                batch.get("updated_at"),
            ),
        )
        if own_conn:
            conn.commit()
        return int(cursor.lastrowid)
    finally:
        if own_conn:
            conn.close()


def update_ticket_batch(batch_id: int, updates: dict[str, Any], conn: sqlite3.Connection | None = None) -> None:
    if not updates:
        return
    own_conn = conn is None
    conn = conn or connect()
    try:
        updates = {**updates, "updated_at": updates.get("updated_at", now_iso())}
        assignments = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(f"UPDATE ticket_batches SET {assignments} WHERE id = ?", (*updates.values(), batch_id))
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()


def ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def ensure_user(platform_user_id: str, display_name: str = "", is_allowed: bool = True, conn: sqlite3.Connection | None = None) -> int:
    own_conn = conn is None
    conn = conn or connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO users(platform_user_id, display_name, is_allowed, created_at) VALUES (?, ?, ?, ?)",
            (platform_user_id, display_name or platform_user_id, int(is_allowed), now_iso()),
        )
        row = conn.execute("SELECT id FROM users WHERE platform_user_id = ?", (platform_user_id,)).fetchone()
        if own_conn:
            conn.commit()
        return int(row["id"])
    finally:
        if own_conn:
            conn.close()


def insert_ticket(ticket: dict[str, Any], conn: sqlite3.Connection | None = None) -> int:
    own_conn = conn is None
    conn = conn or connect()
    try:
        cursor = conn.execute(
            """
            INSERT INTO tickets(batch_id, user_id, lottery_type, play_type, issue, draw_date, numbers_json, cost, multiple, is_additional, is_purchased, ticket_status, replaced_by_batch_id, purchase_confirmed_at, cancelled_at, notes, tracking_status, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticket.get("batch_id"),
                ticket.get("user_id"),
                ticket["lottery_type"],
                ticket.get("play_type"),
                ticket.get("issue"),
                ticket.get("draw_date"),
                json.dumps(ticket["numbers"], ensure_ascii=False),
                ticket.get("cost", 0),
                ticket.get("multiple", 1),
                int(bool(ticket.get("is_additional", False))),
                int(bool(ticket.get("is_purchased", False))),
                ticket.get("ticket_status") or ("purchased" if ticket.get("is_purchased") else "generated"),
                ticket.get("replaced_by_batch_id"),
                ticket.get("purchase_confirmed_at"),
                ticket.get("cancelled_at"),
                ticket.get("notes"),
                ticket.get("tracking_status"),
                ticket.get("source", "agent"),
                ticket.get("created_at", now_iso()),
            ),
        )
        if own_conn:
            conn.commit()
        return int(cursor.lastrowid)
    finally:
        if own_conn:
            conn.close()


def upsert_draw(draw: dict[str, Any], conn: sqlite3.Connection | None = None) -> int:
    own_conn = conn is None
    conn = conn or connect()
    try:
        conn.execute(
            """
            INSERT INTO draws(lottery_type, issue, draw_date, draw_time, numbers_json, prize_pool, sales_amount, deadline, next_issue, next_draw_date, next_open_time, next_buy_end_time, source_url, raw_json, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(lottery_type, issue) DO UPDATE SET
              draw_date=excluded.draw_date,
              draw_time=excluded.draw_time,
              numbers_json=excluded.numbers_json,
              prize_pool=excluded.prize_pool,
              sales_amount=excluded.sales_amount,
              deadline=excluded.deadline,
              next_issue=excluded.next_issue,
              next_draw_date=excluded.next_draw_date,
              next_open_time=excluded.next_open_time,
              next_buy_end_time=excluded.next_buy_end_time,
              source_url=excluded.source_url,
              raw_json=excluded.raw_json,
              fetched_at=excluded.fetched_at
            """,
            (
                draw["lottery_type"],
                draw["issue"],
                draw.get("draw_date"),
                draw.get("draw_time"),
                json.dumps(draw.get("numbers", {}), ensure_ascii=False),
                draw.get("prize_pool"),
                draw.get("sales_amount"),
                draw.get("deadline"),
                draw.get("next_issue"),
                draw.get("next_draw_date"),
                draw.get("next_open_time"),
                draw.get("next_buy_end_time"),
                draw.get("source_url"),
                json.dumps(draw.get("raw", {}), ensure_ascii=False),
                draw.get("fetched_at", now_iso()),
            ),
        )
        row = conn.execute(
            "SELECT id FROM draws WHERE lottery_type = ? AND issue = ?",
            (draw["lottery_type"], draw["issue"]),
        ).fetchone()
        draw_id = int(row["id"])
        conn.execute("DELETE FROM draw_prize_details WHERE draw_id = ?", (draw_id,))
        for detail in draw.get("prize_details", []):
            conn.execute(
                """
                INSERT INTO draw_prize_details(draw_id, prize_level, prize_name, winning_count, prize_amount, additional_count, additional_amount, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draw_id,
                    detail.get("prize_level"),
                    detail.get("prize_name"),
                    detail.get("winning_count"),
                    detail.get("prize_amount"),
                    detail.get("additional_count"),
                    detail.get("additional_amount"),
                    json.dumps(detail.get("raw", detail), ensure_ascii=False),
                ),
            )
        if own_conn:
            conn.commit()
        return draw_id
    finally:
        if own_conn:
            conn.close()


def insert_prize_result(result: dict[str, Any], conn: sqlite3.Connection | None = None) -> int:
    own_conn = conn is None
    conn = conn or connect()
    try:
        cursor = conn.execute(
            """
            INSERT INTO prize_results(ticket_id, draw_id, hit_summary, prize_level, prize_name, prize_amount, is_pending_amount, prize_source, is_winning, checked_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticket_id, draw_id) DO UPDATE SET
              hit_summary=excluded.hit_summary,
              prize_level=excluded.prize_level,
              prize_name=excluded.prize_name,
              prize_amount=excluded.prize_amount,
              is_pending_amount=excluded.is_pending_amount,
              prize_source=excluded.prize_source,
              is_winning=excluded.is_winning,
              checked_at=excluded.checked_at
            """,
            (
                result["ticket_id"],
                result["draw_id"],
                json.dumps(result.get("hit_summary", {}), ensure_ascii=False),
                result.get("prize_level"),
                result.get("prize_name"),
                result.get("prize_amount", 0),
                int(bool(result.get("is_pending_amount", False))),
                result.get("prize_source"),
                int(bool(result.get("is_winning", False))),
                result.get("checked_at", now_iso()),
            ),
        )
        if own_conn:
            conn.commit()
        return int(cursor.lastrowid)
    finally:
        if own_conn:
            conn.close()


def log_api(lottery_type: str, api_url: str, status: str, message: str, conn: sqlite3.Connection | None = None) -> None:
    own_conn = conn is None
    conn = conn or connect()
    try:
        conn.execute(
            "INSERT INTO api_logs(lottery_type, api_url, status, message, created_at) VALUES (?, ?, ?, ?, ?)",
            (lottery_type, api_url, status, message, now_iso()),
        )
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()


def log_scheduler(job_name: str, action: str, status: str, message: str = "", result: dict[str, Any] | None = None, conn: sqlite3.Connection | None = None) -> None:
    own_conn = conn is None
    conn = conn or connect()
    try:
        conn.execute(
            "INSERT INTO scheduler_logs(job_name, action, status, message, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (job_name, action, status, message, json.dumps(result or {}, ensure_ascii=False, default=str), now_iso()),
        )
        if own_conn:
            conn.commit()
    finally:
        if own_conn:
            conn.close()


def fetch_all(query: str, params: Iterable[Any] = (), conn: sqlite3.Connection | None = None) -> list[dict[str, Any]]:
    own_conn = conn is None
    conn = conn or connect()
    try:
        return [dict(row) for row in conn.execute(query, tuple(params)).fetchall()]
    finally:
        if own_conn:
            conn.close()
