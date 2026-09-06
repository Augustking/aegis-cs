"""
人工接管工单队列（SQLite）
图进程（langgraph dev）与 Flask 进程共用同一数据文件；WAL + busy_timeout 保证双进程安全。
数据文件路径默认 <项目根>/tickets.db，环境变量 TICKET_DB_PATH 可覆盖（测试指向临时目录）。
"""

import os
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id             TEXT PRIMARY KEY,
    thread_id      TEXT NOT NULL,
    user_query     TEXT NOT NULL,
    draft_reply    TEXT NOT NULL,
    quality_score  REAL NOT NULL,
    quality_reason TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'open',
    created_at     TEXT NOT NULL,
    resolved_at    TEXT,
    human_reply    TEXT,
    quality_dims   TEXT
);
CREATE INDEX IF NOT EXISTS idx_tickets_thread_status ON tickets(thread_id, status);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """老库补列：quality_dims（T5 质检三维评分）；表不存在时跳过（建表语句已含）。"""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tickets'"
    ).fetchone()
    if not exists:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(tickets)")}
    if "quality_dims" not in cols:
        conn.execute("ALTER TABLE tickets ADD COLUMN quality_dims TEXT")


def _db_path() -> str:
    return os.getenv("TICKET_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "tickets.db"
    )


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    _migrate(conn)
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def create_ticket(
    thread_id: str,
    user_query: str,
    draft_reply: str,
    quality_score: float,
    quality_reason: str,
    quality_dims: Optional[Dict[str, float]] = None,
) -> str:
    """创建 open 状态工单，返回工单 id。quality_dims 为三维评分字典（可选）。"""
    import json as _json

    ticket_id = str(uuid.uuid4())
    dims_json = _json.dumps(quality_dims, ensure_ascii=False) if quality_dims else None
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        conn.execute(
            "INSERT INTO tickets (id, thread_id, user_query, draft_reply,"
            " quality_score, quality_reason, status, created_at, quality_dims)"
            " VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?)",
            (ticket_id, thread_id, user_query, draft_reply,
             float(quality_score), quality_reason, _now(), dims_json),
        )
    return ticket_id


def has_open_ticket(thread_id: str) -> bool:
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        row = conn.execute(
            "SELECT 1 FROM tickets WHERE thread_id=? AND status='open' LIMIT 1",
            (thread_id,),
        ).fetchone()
    return row is not None


def latest_ticket_for_thread(thread_id: str) -> Optional[Dict[str, Any]]:
    """该线程最近一张工单（任意状态，新→旧）；无工单返回 None。"""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        row = conn.execute(
            "SELECT * FROM tickets WHERE thread_id=?"
            " ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
    return dict(row) if row else None


def get_ticket(ticket_id: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        row = conn.execute(
            "SELECT * FROM tickets WHERE id=?", (ticket_id,)
        ).fetchone()
    return dict(row) if row else None


def list_tickets(status: Optional[str] = None) -> List[Dict[str, Any]]:
    # created_at 为秒级精度，同秒创建时用 rowid（插入序）做稳定 tiebreaker
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        if status:
            rows = conn.execute(
                "SELECT * FROM tickets WHERE status=?"
                " ORDER BY created_at DESC, rowid DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tickets ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
    return [dict(r) for r in rows]


def resolve_ticket(ticket_id: str, human_reply: str) -> bool:
    """关闭工单并记录人工回复；仅 open 状态可关闭（幂等保护），返回是否成功。"""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        cur = conn.execute(
            "UPDATE tickets SET status='resolved', resolved_at=?, human_reply=?"
            " WHERE id=? AND status='open'",
            (_now(), human_reply, ticket_id),
        )
    return cur.rowcount > 0
