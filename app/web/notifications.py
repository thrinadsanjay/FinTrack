from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.csrf import verify_csrf_token
from app.core.guards import login_required
from app.services.audit import audit_log
from app.services.notifications import mark_all_read, mark_read_by_ids
from app.services.web_push import (
    get_push_public_config,
    save_fcm_token,
    deactivate_fcm_token,
)

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


@router.get("/push/config")
@login_required
async def push_config(request: Request):
    cfg = await get_push_public_config()
    return JSONResponse({"status": "ok", "push": cfg})


@router.post("/push/subscribe")
@login_required
async def push_subscribe(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    return JSONResponse({"detail": "WebPush subscription is disabled. Use Firebase FCM token registration."}, status_code=400)


@router.post("/push/fcm/register")
@login_required
async def push_fcm_register(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    user = request.session.get("user") or {}
    payload = await request.json()
    token = str((payload or {}).get("token") or "").strip()
    if not token:
        return JSONResponse({"detail": "FCM token is required."}, status_code=400)

    ok = await save_fcm_token(
        user_id=user.get("user_id"),
        token=token,
        user_agent=request.headers.get("user-agent", ""),
    )
    if not ok:
        return JSONResponse({"detail": "Invalid FCM token payload."}, status_code=400)

    await audit_log(
        action="PUSH_FCM_TOKEN_SAVED",
        request=request,
        user={
            "user_id": str(user.get("user_id") or ""),
            "username": user.get("username"),
            "auth_provider": user.get("auth_provider"),
        },
        meta={"has_token": True},
    )
    return JSONResponse({"status": "ok"})


@router.post("/push/unsubscribe")
@login_required
async def push_unsubscribe(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    return JSONResponse({"detail": "WebPush unsubscribe is disabled. Use Firebase FCM unregister."}, status_code=400)


@router.post("/push/fcm/unregister")
@login_required
async def push_fcm_unregister(request: Request):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    user = request.session.get("user") or {}
    payload = await request.json()
    token = str((payload or {}).get("token") or "").strip()
    if not token:
        return JSONResponse({"detail": "FCM token is required."}, status_code=400)

    await deactivate_fcm_token(user_id=user.get("user_id"), token=token)
    await audit_log(
        action="PUSH_FCM_TOKEN_REMOVED",
        request=request,
        user={
            "user_id": str(user.get("user_id") or ""),
            "username": user.get("username"),
            "auth_provider": user.get("auth_provider"),
        },
        meta={"token_prefix": token[:16]},
    )
    return JSONResponse({"status": "ok"})
