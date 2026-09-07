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


def list_tickets(status: Optional[str] = None, q: str = "",
                 limit: int = 200, offset: int = 0) -> Dict[str, Any]:
    """工单列表：状态过滤 + 关键词（问题/编号/回复）+ 分页。
    返回 {items, total, limit, offset}；created_at 倒序（同秒按插入序）。"""
    q = (q or "").strip().lower()
    like = f"%{q}%"
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        where, params = [], []
        if status:
            where.append("status=?")
            params.append(status)
        if q:
            where.append("(LOWER(user_query) LIKE ? OR LOWER(id) LIKE ? OR LOWER(draft_reply) LIKE ? OR LOWER(human_reply) LIKE ?)")
            params += [like, like, like, like]
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        total = conn.execute(
            f"SELECT COUNT(*) FROM tickets {where_sql}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM tickets {where_sql} ORDER BY created_at DESC, rowid DESC LIMIT ? OFFSET ?",
            params + [int(limit), int(offset)],
        ).fetchall()
    return {"items": [dict(r) for r in rows], "total": total, "limit": int(limit), "offset": int(offset)}


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
