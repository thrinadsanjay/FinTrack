from fastapi import APIRouter, Request

from app.core.csrf import verify_csrf_token
from app.core.guards import login_required
from app.services.dashboard import get_user_notifications
from app.services.security_center import get_security_overview
from app.services.sessions import revoke_other_sessions
from app.services.audit import audit_log
from app.web.templates import templates

router = APIRouter()


@router.get("/security")
@login_required
async def security_center_page(request: Request):
    user = request.session.get("user")
    overview = await get_security_overview(request, user["user_id"])
    notifications = await get_user_notifications(user["user_id"])
    return templates.TemplateResponse(
        request=request,
        name="pages/security/center.html",
        context={
            "request": request,
            "user": user,
            "active_page": "security",
            "overview": overview,
            "notifications": notifications,
        },
    )


@router.post("/security/sessions/revoke-others")
@login_required
async def security_revoke_others(request: Request):
    form = await request.form()
    verify_csrf_token(request, form.get("csrf_token"))
    user = request.session.get("user")
    count = await revoke_other_sessions(request, user["user_id"])
    await audit_log(
        action="SESSIONS_REVOKED",
        request=request,
        user={"user_id": user["user_id"]},
        meta={"revoked": count},
    )
    from fastapi.responses import RedirectResponse

    return RedirectResponse("/security?revoked=1", status_code=303)
