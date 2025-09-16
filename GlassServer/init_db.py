# GlassServer/init_db.py
import os, psycopg2

def run():
    dsn = os.environ["DATABASE_URL"]
    sql_path = os.path.join(os.path.dirname(__file__), "models.sql")
    with open(sql_path, "r", encoding="utf-8") as f:
        ddl = f.read()

    conn = psycopg2.connect(dsn)
    with conn, conn.cursor() as cur:
        cur.execute(ddl)
    conn.close()
    print("DB init OK")

if __name__ == "__main__":
    run()
