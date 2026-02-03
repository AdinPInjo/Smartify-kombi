"""
Auth API endpoints.
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import JSONResponse

from smartify.config import SMARTIFY_USERNAME, SMARTIFY_PASSWORD


router = APIRouter(tags=["auth"])


@router.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == SMARTIFY_USERNAME and password == SMARTIFY_PASSWORD:
        request.session["logged_in"] = True
        request.session["user"] = username
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False, "error": "invalid_credentials"}, status_code=401)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return JSONResponse({"ok": True})
