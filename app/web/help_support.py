from fastapi import APIRouter, Request

from app.services.admin_settings import get_admin_settings
from app.services.dashboard import get_user_notifications
from app.web.templates import templates

router = APIRouter()


@router.get("/help-support")
async def help_support_page(request: Request):
    session_user = request.session.get("user")
    admin_settings = await get_admin_settings()
    app_cfg = admin_settings.get("application", {})
    notifications = []
    if session_user and session_user.get("user_id"):
        try:
            notifications = await get_user_notifications(session_user["user_id"])
        except Exception:
            notifications = []
    return templates.TemplateResponse(
        "help_support.html",
        {
            "request": request,
            "user": session_user,
            "support_email": app_cfg.get("support_email"),
            "support_phone": app_cfg.get("support_phone"),
            "notifications": notifications,
            "active_page": "help_support",
        },
    )
