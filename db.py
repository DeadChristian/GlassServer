# db.py — Postgres in prod, SQLite in dev; converts :name -> %(name)s
import os, re
from typing import Optional, Dict, Any, List

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    # ---------- Postgres (psycopg3) ----------
    import psycopg  # pip install psycopg[binary]
    _PARAM_RE = re.compile(r":([a-zA-Z_][a-zA-Z0-9_]*)")

    def _pg_sql(sql: str) -> str:
        # Convert ":name" params to psycopg "%(name)s"
        return _PARAM_RE.sub(r"%(\1)s", sql)

    def _conn():
        return psycopg.connect(DATABASE_URL, autocommit=True)

    def execute(sql: str, params: Optional[Dict[str, Any]] = None) -> None:
        with _conn() as c:
            with c.cursor() as cur:
                cur.execute(_pg_sql(sql), params or {})

    def query_one(sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        with _conn() as c:
            with c.cursor() as cur:
                cur.execute(_pg_sql(sql), params or {})
                row = cur.fetchone()
                if not row:
                    return None
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, row))

    def query_all(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        with _conn() as c:
            with c.cursor() as cur:
                cur.execute(_pg_sql(sql), params or {})
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]

else:
    # ---------- SQLite (dev/local) ----------
    import sqlite3
    DB_PATH = os.getenv("DB_PATH", "/tmp/glass.db")
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    _sqlite = sqlite3.connect(DB_PATH, check_same_thread=False)
    _sqlite.row_factory = sqlite3.Row

    def execute(sql: str, params: Optional[Dict[str, Any]] = None) -> None:
        with _sqlite:
            _sqlite.execute(sql, params or {})

    def query_one(sql: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        cur = _sqlite.execute(sql, params or {})
        row = cur.fetchone()
        return dict(row) if row else None

    def query_all(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        cur = _sqlite.execute(sql, params or {})
        rows = cur.fetchall()
        return [dict(r) for r in rows]
