import os
import sqlite3
import threading
from typing import Optional, Dict, Any

DB_PATH = os.getenv("DB_PATH", "/tmp/glass.db")

_lock = threading.Lock()
_conn_singleton: Optional[sqlite3.Connection] = None

def _get_conn() -> sqlite3.Connection:
    global _conn_singleton
    if _conn_singleton is None:
        _conn_singleton = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn_singleton.row_factory = sqlite3.Row
    return _conn_singleton

def execute(sql: str, params: Optional[Dict[str, Any]] = None) -> int:
    with _lock:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(sql, params or {})
        conn.commit()
        return cur.rowcount

def query_one(sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    cur = _get_conn().cursor()
    cur.execute(sql, params or {})
    row = cur.fetchone()
    return dict(row) if row else None
