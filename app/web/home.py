from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from app.web.templates import templates
from app.services.dashboard import get_dashboard_summary, get_recent_transactions

router = APIRouter()

def require_login(request: Request):
    if "user" not in request.session:
        return RedirectResponse("/login")

@router.get("/")
async def dashboard(request: Request):
    user = request.session.get("user")
    if not user:
        return RedirectResponse("/login", status_code=303)

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
            "active_page": "dashboard",
        },
    )
