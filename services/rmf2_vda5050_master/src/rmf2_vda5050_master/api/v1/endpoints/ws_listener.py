from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from rmf2_vda5050_master.config import _MODE

router = APIRouter()

_HTML = (Path(__file__).parent / "ws_listener.html").read_text()


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def ws_listener(request: Request) -> HTMLResponse:
    if _MODE == "prod":
        raise HTTPException(status_code=404)
    root = request.scope.get("root_path", "")
    return HTMLResponse(_HTML.replace("{root_path}", root))
