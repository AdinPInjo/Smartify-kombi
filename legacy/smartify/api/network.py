"""
Network (nmcli) API endpoints.
"""
from typing import Optional

from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse

from smartify.auth import require_auth
from smartify.services.network import run_nmcli


router = APIRouter(tags=["network"])


@router.get("/api/network/status")
def api_network_status(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    err = require_auth(request, x_api_key)
    if err:
        return err

    proc = run_nmcli(["-t", "-f", "ACTIVE,SSID,DEVICE", "dev", "wifi"])
    if proc.returncode != 0:
        return JSONResponse({"error": "nmcli_failed", "stderr": proc.stderr.strip()}, status_code=500)

    lines = [l.strip() for l in proc.stdout.splitlines() if l.strip()]
    return JSONResponse({"rows": lines})


@router.get("/api/network/scan")
def api_network_scan(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    err = require_auth(request, x_api_key)
    if err:
        return err

    proc = run_nmcli(["-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi", "list"])
    if proc.returncode != 0:
        return JSONResponse({"error": "nmcli_failed", "stderr": proc.stderr.strip()}, status_code=500)

    rows = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = line.split(":")
        ssid = parts[0] if len(parts) > 0 else ""
        signal = parts[1] if len(parts) > 1 else ""
        security = parts[2] if len(parts) > 2 else ""
        rows.append({"ssid": ssid, "signal": signal, "security": security})

    return JSONResponse({"networks": rows})
