"""
身份与归属存储（SQLite，与工单库同机部署）
- users：坐席账号（werkzeug 哈希口令，role: agent / admin）
- thread_owners：thread_id → 访客ID 归属，客户侧会话隔离的唯一事实来源
首次初始化自动创建默认坐席（用户名 agent，口令取 AGENT_DEFAULT_PASSWORD，默认 aegis-demo），
生产部署必须通过环境变量修改或删除该账号。
"""

import os
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from werkzeug.security import check_password_hash, generate_password_hash

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'agent',
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS thread_owners (
    thread_id  TEXT PRIMARY KEY,
    visitor_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_thread_owners_visitor ON thread_owners(visitor_id);
CREATE TABLE IF NOT EXISTS thread_index (
    thread_id  TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);
"""


def _db_path() -> str:
    return os.getenv("AUTH_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "auth.db"
    )


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_default_agent() -> Optional[str]:
    """首次运行创建默认坐席账号；已存在时返回 None。"""
    conn = _connect()
    try:
        exists = conn.execute("SELECT 1 FROM users WHERE username=?", ("agent",)).fetchone()
        if exists:
            return None
        uid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?, ?, ?, 'agent', ?)",
            (uid, "agent", generate_password_hash(os.getenv("AGENT_DEFAULT_PASSWORD", "aegis-demo")), _now()),
        )
        conn.commit()
        return uid
    finally:
        conn.close()


def verify_login(username: str, password: str) -> Optional[Dict[str, Any]]:
    """校验坐席账号；成功返回 {username, role}，失败返回 None。"""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT username, password_hash, role FROM users WHERE username=?", (username,)
        ).fetchone()
    finally:
        conn.close()
    if not row or not check_password_hash(row["password_hash"], password):
        return None
    return {"username": row["username"], "role": row["role"]}


def create_user(username: str, password: str, role: str = "agent") -> str:
    """创建坐席账号（管理功能，供后续扩展）；用户名冲突抛 ValueError。"""
    uid = str(uuid.uuid4())
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO users (id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
            (uid, username, generate_password_hash(password), role, _now()),
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        raise ValueError(f"用户名已存在: {username}") from e
    finally:
        conn.close()
    return uid


def bind_thread_owner(thread_id: str, visitor_id: str) -> None:
    """登记线程归属；已存在时不覆盖（归属不迁移）。"""
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO thread_owners (thread_id, visitor_id, created_at) VALUES (?, ?, ?)",
            (thread_id, visitor_id, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def visitor_owns_thread(thread_id: str, visitor_id: str) -> bool:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM thread_owners WHERE thread_id=? AND visitor_id=?", (thread_id, visitor_id)
        ).fetchone()
    finally:
        conn.close()
    return row is not None


def threads_of_visitor(visitor_id: str, limit: int = 50) -> list:
    """访客自己的线程 ID 列表（新→旧）。"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT thread_id FROM thread_owners WHERE visitor_id=? ORDER BY created_at DESC LIMIT ?",
            (visitor_id, int(limit)),
        ).fetchall()
    finally:
        conn.close()
    return [r["thread_id"] for r in rows]


def new_visitor_id() -> str:
    return str(uuid.uuid4())


def record_thread(thread_id: str) -> None:
    """登记线程索引（全量会话列表用）；已存在不覆盖创建时间。"""
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO thread_index (thread_id, created_at) VALUES (?, ?)",
            (thread_id, _now()),
        )
        conn.commit()
    finally:
        conn.close()


def list_threads(limit: int = 200) -> list:
    """全部线程（新→旧），坐席会话列表用。"""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT thread_id, created_at FROM thread_index ORDER BY created_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    finally:
        conn.close()
    return [{"thread_id": r["thread_id"], "created_at": r["created_at"]} for r in rows]


def delete_thread_record(thread_id: str) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM thread_index WHERE thread_id=?", (thread_id,))
        conn.execute("DELETE FROM thread_owners WHERE thread_id=?", (thread_id,))
        conn.commit()
    finally:
        conn.close()
