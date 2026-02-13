from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.core.csrf import verify_csrf_token
from app.core.guards import login_required
from app.services.notifications import mark_all_read, mark_read_by_ids

router = APIRouter()


@router.post("/read")
@login_required
async def mark_notifications_read(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    user = request.session.get("user")
    payload = await request.json()
    ids = payload.get("ids")
    mark_all = payload.get("all", False)

    if mark_all:
        await mark_all_read(user_id=user["user_id"])
        return JSONResponse({"status": "ok", "read": "all"})

    if ids:
        await mark_read_by_ids(user_id=user["user_id"], ids=ids)
        return JSONResponse({"status": "ok", "read": ids})

    return JSONResponse({"status": "noop"})
