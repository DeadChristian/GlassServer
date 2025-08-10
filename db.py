import os, sqlite3
from typing import Any, Dict, List, Optional

DB_PATH = os.getenv("DB_PATH", "glass.db")

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def execute(sql: str, params: Optional[Dict[str, Any]] = None) -> None:
    conn = _conn()
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute(sql, params or {})
        conn.commit()
    finally:
        conn.close()

def query_one(sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    conn = _conn()
    try:
        cur = conn.execute(sql, params or {})
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

def query_all(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    conn = _conn()
    try:
        cur = conn.execute(sql, params or {})
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
