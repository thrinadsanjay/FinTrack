"""
Dashboard UI controller.
"""

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from app.web.templates import templates
from app.services.dashboard import (
    get_dashboard_summary,
    get_recent_transactions,
)
from app.core.guards import login_required
router = APIRouter()


@router.get("/")
@login_required
async def dashboard(request: Request):
    user = request.session.get("user")

    if request.session.get("force_pwd_reset"):
        return RedirectResponse("/reset-password", status_code=303)

    summary = await get_dashboard_summary(user["user_id"])
    transactions = await get_recent_transactions(user["user_id"])

    return templates.TemplateResponse(
        "home.html",
        {
            "request": request,
            "user": user,
            "summary": summary,
            "transactions": transactions,
            "notifications": summary.get("notifications", []),
            "active_page": "dashboard",
        },
    )
