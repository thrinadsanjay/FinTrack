from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.core.csrf import verify_csrf_token
from app.routers.deps import get_current_user_valid as get_current_user
from app.services.audit import audit_log
from app.services.sessions import revoke_other_sessions

router = APIRouter()


@router.post("/sessions/revoke-others")
async def revoke_other_sessions_endpoint(request: Request, user=Depends(get_current_user)):
    verify_csrf_token(request, request.headers.get("X-CSRF-Token"))
    user_id = str(user.get("user_id") or "")
    count = await revoke_other_sessions(request, user_id)
    await audit_log(
        action="SESSIONS_REVOKED",
        request=request,
        user={"user_id": user_id},
        meta={"revoked": count},
    )
    return JSONResponse({"ok": True, "revoked": count})
