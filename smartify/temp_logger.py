import time
import sqlite3
from datetime import datetime, timezone
import httpx

DB_PATH = "/home/adinpinjo/smartify/smartify.db"
URL = "https://localhost:8443/api/temperature"  # sensor API (self-signed)
INTERVAL_S = 30

def db():
    return sqlite3.connect(DB_PATH)

def now_iso():
    return datetime.now(timezone.utc).isoformat()

def insert(sensor: str, t, h):
    con = db()
    cur = con.cursor()
    cur.execute(
        "INSERT INTO temp_readings (ts, sensor, temp_c, hum_pct) VALUES (?, ?, ?, ?)",
        (now_iso(), sensor, t, h),
    )
    con.commit()
    con.close()

def main():
    while True:
        try:
            with httpx.Client(verify=False, timeout=5.0) as client:
                r = client.get(URL)
                r.raise_for_status()
                data = r.json()

            # expected:
            # { ts: ..., kombi:{temp_c,hum_pct}, garaza:{temp_c,hum_pct} }
            k = data.get("kombi", {})
            g = data.get("garaza", {})

            insert("kombi", k.get("temp_c"), k.get("hum_pct"))
            insert("garaza", g.get("temp_c"), g.get("hum_pct"))

        except Exception as e:
            # keep running; you can inspect later via journalctl once systemd service is added
            pass

        time.sleep(INTERVAL_S)

if __name__ == "__main__":
    main()
