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

# ---- Compatibility shim: get_conn() for code that uses raw cursors ----
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///glass.db")
_IS_PG = DATABASE_URL.startswith(("postgres://", "postgresql://"))

if _IS_PG:
    # Postgres: simple passthrough (works with "with get_conn() as conn, conn.cursor() as cur")
    import psycopg

    def get_conn():
        # autocommit False so "with" context can commit/rollback
        return psycopg.connect(DATABASE_URL)
else:
    # SQLite: provide a connection + cursor that behave as context managers
    import sqlite3

    class _SqliteCursorCtx:
        def __init__(self, conn):
            self._conn = conn
            self._cur = None

        def __enter__(self):
            self._cur = self._conn.cursor()
            return self._cur

        def __exit__(self, exc_type, exc, tb):
            try:
                self._cur.close()
            except Exception:
                pass

    class _SqliteConnProxy:
        def __init__(self, path):
            self._conn = sqlite3.connect(path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row

        # allow: "with get_conn() as conn, conn.cursor() as cur:"
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            try:
                if exc_type:
                    self._conn.rollback()
                else:
                    self._conn.commit()
            finally:
                self._conn.close()

        def cursor(self):
            return _SqliteCursorCtx(self._conn)

        # expose commit/rollback for any code that calls them
        def commit(self):
            self._conn.commit()

        def rollback(self):
            self._conn.rollback()

    def get_conn():
        # support sqlite:///path or bare path
        path = DATABASE_URL.replace("sqlite:///", "") if DATABASE_URL.startswith("sqlite:///") else DATABASE_URL
        return _SqliteConnProxy(path)
