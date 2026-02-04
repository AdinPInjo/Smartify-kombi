"""Log access endpoints."""
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse

from smartify.auth import require_auth
from smartify.config import DATA_DIR

router = APIRouter(tags=["logs"])


@router.get("/api/logs/recent")
def api_logs_recent(
    request: Request,
    lines: int = 200,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
):
    err = require_auth(request, x_api_key)
    if err:
        return err

    max_lines = max(1, min(int(lines), 1000))
    log_path = Path(DATA_DIR) / "logs" / "smartify.log"
    if not log_path.exists():
        return JSONResponse({"ok": True, "lines": [], "path": str(log_path)})

    try:
        content = log_path.read_text(encoding="utf-8", errors="ignore")
        raw_lines = content.splitlines()
        tail = raw_lines[-max_lines:]
        return JSONResponse({"ok": True, "lines": tail, "path": str(log_path)})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e), "lines": [], "path": str(log_path)})
