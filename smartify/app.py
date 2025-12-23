import os
import sqlite3
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

DB_PATH = "/home/adinpinjo/smartify/smartify.db"

DIST_DIR = Path("/home/adinpinjo/smartify-ui/dist")
INDEX_HTML = DIST_DIR / "index.html"
ASSETS_DIR = DIST_DIR / "assets"

APP_SECRET = os.environ.get("SMARTIFY_SECRET", "change-this-secret")
ADMIN_USER = os.environ.get("SMARTIFY_USER", "adinpinjo")
ADMIN_PASS = os.environ.get("SMARTIFY_PASS", "set-in-env")

# Sensor API (local, self-signed)
SENSOR_API = os.environ.get("SMARTIFY_SENSOR_API", "https://localhost:8443/api/temperature")

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=APP_SECRET)

# Serve built assets
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")


def db():
    return sqlite3.connect(DB_PATH)


def authed(request: Request) -> bool:
    return bool(request.session.get("user"))


# -----------------------------
# AUTH
# -----------------------------
@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USER and password == ADMIN_PASS:
        request.session["user"] = username
        return RedirectResponse("/dashboard", status_code=302)
    return RedirectResponse("/login", status_code=302)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


@app.get("/login")
def spa_login():
    if INDEX_HTML.exists():
        return FileResponse(str(INDEX_HTML))
    return JSONResponse({"error": "frontend_not_built"}, status_code=500)


# -----------------------------
# TEMPERATURE (current)
# -----------------------------
@app.get("/api/pi/temperature")
async def pi_temperature(request: Request):
    if not authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        async with httpx.AsyncClient(verify=False, timeout=5.0) as client:
            r = await client.get(SENSOR_API)
            r.raise_for_status()
            return r.json()
    except httpx.RequestError:
        return JSONResponse({"error": "sensor_unreachable"}, status_code=502)
    except Exception as e:
        return JSONResponse({"error": "sensor_error", "detail": str(e)}, status_code=502)


# -----------------------------
# TEMPERATURE HISTORY (chart)
# -----------------------------
@app.get("/api/temperature/history")
def temperature_history(
    request: Request,
    range: Literal["day", "week", "month", "year"] = "day",
):
    if not authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    bucket_s = {
        "day": 300,        # 5 min
        "week": 1800,      # 30 min
        "month": 7200,     # 2 h
        "year": 86400,     # 1 day
    }[range]

    lookback_s = {
        "day": 86400,
        "week": 86400 * 7,
        "month": 86400 * 30,
        "year": 86400 * 365,
    }[range]

    now = datetime.now(timezone.utc)
    since = now - timedelta(seconds=lookback_s)

    con = db()
    cur = con.cursor()
    cur.execute(
        """
        SELECT ts, sensor, temp_c
        FROM temp_readings
        WHERE ts >= ?
          AND sensor IN ('kombi','garaza')
        ORDER BY ts ASC
        """,
        (since.isoformat(),),
    )
    rows = cur.fetchall()
    con.close()

    buckets: dict[int, dict[str, list[float]]] = {}

    for ts, sensor, temp_c in rows:
        if temp_c is None:
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc)
        except Exception:
            continue

        epoch = int(dt.timestamp())
        b = epoch - (epoch % bucket_s)

        if b not in buckets:
            buckets[b] = {"kombi": [], "garaza": []}

        if sensor in ("kombi", "garaza"):
            buckets[b][sensor].append(float(temp_c))

    def avg(xs: list[float]):
        return sum(xs) / len(xs) if xs else None

    series = [{"ts": b, "kombi": avg(v["kombi"]), "garaza": avg(v["garaza"])} for b, v in sorted(buckets.items())]

    return {"range": range, "bucket_s": bucket_s, "count": len(series), "series": series}


# -----------------------------
# GPS (current + track)
# -----------------------------
@app.get("/api/gps/current")
def gps_current(request: Request):
    if not authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    con = db()
    cur = con.cursor()
    cur.execute(
        """
        SELECT ts, lat, lon
        FROM track_points
        WHERE lat IS NOT NULL AND lon IS NOT NULL
        ORDER BY id DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    con.close()

    if not row:
        return {"ts": None, "lat": None, "lon": None, "connected": False}

    return {"ts": row[0], "lat": row[1], "lon": row[2], "connected": True}


@app.get("/api/gps/track")
def gps_track(
    request: Request,
    hours: int = 24,
    limit: int = 2000,
):
    if not authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    hours = max(1, min(hours, 24 * 14))
    limit = max(10, min(limit, 20000))

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    since_iso = since.isoformat()

    con = db()
    cur = con.cursor()
    cur.execute(
        """
        SELECT ts, lat, lon
        FROM track_points
        WHERE lat IS NOT NULL AND lon IS NOT NULL
          AND ts >= ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (since_iso, limit),
    )
    rows = cur.fetchall()
    con.close()

    rows.reverse()
    return {"hours": hours, "count": len(rows), "points": [{"ts": r[0], "lat": r[1], "lon": r[2]} for r in rows]}


# -----------------------------
# NETWORK (nmcli)
# -----------------------------
def run_nmcli(args: list[str]) -> str:
    cmd = ["sudo", "-n", "nmcli"] + args
    out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
    return out


@app.get("/api/network/status")
def network_status(request: Request):
    if not authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    active_ssid = None
    ip4 = None

    try:
        out = run_nmcli(["-t", "-f", "ACTIVE,SSID,DEVICE", "dev", "wifi"])
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[0] == "yes":
                active_ssid = parts[1] or None
                break
    except Exception:
        pass

    try:
        out = run_nmcli(["-t", "-f", "IP4.ADDRESS", "dev", "show"])
        for line in out.splitlines():
            if line.startswith("IP4.ADDRESS:"):
                ip4 = line.split(":", 1)[1].split("/")[0].strip()
                if ip4:
                    break
    except Exception:
        pass

    return {"ssid": active_ssid, "ip": ip4}


@app.get("/api/network/scan")
def network_scan(request: Request):
    if not authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        out = run_nmcli(["-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"])
    except subprocess.CalledProcessError as e:
        return JSONResponse({"error": "nmcli_failed", "detail": e.output[-400:]}, status_code=400)

    networks = []
    for line in out.splitlines():
        parts = line.split(":")
        if len(parts) < 3:
            continue
        ssid, signal, security = parts[0], parts[1], ":".join(parts[2:])
        ssid = (ssid or "").strip()
        if not ssid:
            continue
        networks.append(
            {
                "ssid": ssid,
                "signal": int(signal) if signal.isdigit() else None,
                "security": security.strip(),
            }
        )

    networks.sort(key=lambda x: (x["signal"] is not None, x["signal"]), reverse=True)
    return {"networks": networks}


@app.post("/api/network/connect")
async def network_connect(request: Request):
    if not authed(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    body = await request.json()
    ssid = (body.get("ssid") or "").strip()
    password = body.get("password")

    if not ssid:
        return JSONResponse({"error": "missing_ssid"}, status_code=400)

    try:
        if password:
            run_nmcli(["dev", "wifi", "connect", ssid, "password", password])
        else:
            run_nmcli(["dev", "wifi", "connect", ssid])

        return {"ok": True}
    except subprocess.CalledProcessError as e:
        return JSONResponse({"error": "nmcli_failed", "detail": e.output[-400:]}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": "connect_failed", "detail": str(e)}, status_code=400)


# -----------------------------
# SPA fallback
# -----------------------------
@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if full_path.startswith("api/") or full_path.startswith("assets/"):
        return JSONResponse({"error": "not_found"}, status_code=404)

    if INDEX_HTML.exists():
        return FileResponse(str(INDEX_HTML))
    return JSONResponse({"error": "frontend_not_built"}, status_code=500)

# -----------------------------
# Temperature: latest reading (for Overview)
# -----------------------------
