"""
Frontend routes (SPA).
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse, FileResponse

from smartify.config import STATIC_DIR


router = APIRouter(tags=["frontend"])


def frontend_ready() -> bool:
    return (STATIC_DIR / "index.html").exists()


@router.get("/")
def root():
    if not frontend_ready():
        return JSONResponse({"error": "frontend_not_built"}, status_code=500)
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@router.get("/dashboard")
def dashboard():
    if not frontend_ready():
        return JSONResponse({"error": "frontend_not_built"}, status_code=500)
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@router.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if not frontend_ready():
        return JSONResponse({"error": "frontend_not_built"}, status_code=500)
    target = STATIC_DIR / full_path
    if target.exists() and target.is_file():
        return FileResponse(target)
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})
