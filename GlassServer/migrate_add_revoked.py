# migrate_add_revoked.py — add revoked column without get_conn
from db import execute

# Try plain ADD COLUMN (works on SQLite); if it errors because it exists, ignore.
try:
    execute("ALTER TABLE licenses ADD COLUMN revoked INTEGER DEFAULT 0")
    print("Added column 'revoked' (plain).")
except Exception as e:
    # Some DBs support IF NOT EXISTS; try that next.
    try:
        execute("ALTER TABLE licenses ADD COLUMN IF NOT EXISTS revoked INTEGER DEFAULT 0")
        print("Added column 'revoked' (IF NOT EXISTS).")
    except Exception as e2:
        print("Note: couldn't add column (it probably already exists).")
        print("First error:", repr(e))
        print("Second error:", repr(e2))
