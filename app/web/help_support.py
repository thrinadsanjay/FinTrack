from fastapi import APIRouter, Request

from app.services.admin_settings import get_admin_settings
from app.services.dashboard import get_user_notifications
from app.web.templates import templates

router = APIRouter()


@router.get("/help-support")
async def help_support_page(request: Request):
    session_user = request.session.get("user")
    account_state = str(request.query_params.get("account") or "").strip().lower()
    account_notice = ""
    account_reactivation_context = ""
    if account_state == "disabled":
        account_notice = "Your account is disabled. Reach admin for reactivation."
        account_reactivation_context = "Reactivation request: My account is currently disabled. Please review and re-enable access."
    elif account_state == "deleted":
        account_notice = "Your account has been soft-deleted. Reach admin to review restoration options."
        account_reactivation_context = "Reactivation request: My account was soft-deleted. Please review restoration options and re-enable access if possible."
    admin_settings = await get_admin_settings()
    app_cfg = admin_settings.get("application", {})
    notifications = []
    if session_user and session_user.get("user_id"):
        try:
            notifications = await get_user_notifications(session_user["user_id"])
        except Exception:
            notifications = []
    return templates.TemplateResponse(
        request=request,
        name="help_support.html",
        context={
            "request": request,
            "user": session_user,
            "support_email": app_cfg.get("support_email"),
            "support_phone": app_cfg.get("support_phone"),
            "notifications": notifications,
            "active_page": "help_support",
            "account_notice": account_notice,
            "account_reactivation_context": account_reactivation_context,
        },
    )
