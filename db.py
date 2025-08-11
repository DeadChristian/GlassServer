# db.py — Postgres in prod, SQLite in dev
import os
from typing import Optional, Dict, Any

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    import psycopg  # psycopg3

    def _conn():
        return psycopg.connect(DATABASE_URL, autocommit=True)

    def execute(sql: str, params: Optional[Dict[str, Any]] = None):
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or {})

    def query_one(sql: str, params: Optional[Dict[str, Any]] = None):
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or {})
                row = cur.fetchone()
                if not row:
                    return None
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, row))
else:
    import sqlite3
    DB_PATH = os.getenv("DB_PATH", "/tmp/glass.db")
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    _sqlite = sqlite3.connect(DB_PATH, check_same_thread=False)
    _sqlite.row_factory = sqlite3.Row

    def execute(sql: str, params: Optional[Dict[str, Any]] = None):
        with _sqlite:
            _sqlite.execute(sql, params or {})

    def query_one(sql: str, params: Optional[Dict[str, Any]] = None):
        cur = _sqlite.execute(sql, params or {})
        row = cur.fetchone()
        return dict(row) if row else None
