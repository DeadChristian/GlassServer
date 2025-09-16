# init_referrals.py
import os, psycopg2

def run():
    dsn = os.environ["DATABASE_URL"]
    ddl = open("schema_referrals.sql", "r", encoding="utf-8").read()
    conn = psycopg2.connect(dsn)
    with conn, conn.cursor() as cur:
        cur.execute(ddl)
    conn.close()

if __name__ == "__main__":
    run()


