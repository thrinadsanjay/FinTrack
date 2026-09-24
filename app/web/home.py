"""
Dashboard UI controller.
"""
import asyncio
from calendar import monthrange
from datetime import date, datetime
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from app.web.templates import templates
from app.services.dashboard import (
    get_cashflow_window,
    get_dashboard_summary,
    get_recent_transactions,
)
from app.services.planning import get_planning_overlay
from app.services.ai_finance import recommendations_for_user
from app.helpers.dashboard_notifications import get_bills_due_today
from app.core.guards import login_required
from app.core.time import get_user_timezone
from bson import ObjectId
router = APIRouter()


@router.get("/dashboard/cashflow")
@login_required
async def dashboard_cashflow(request: Request):
    user = request.session.get("user")
    range_key = request.query_params.get("range", "month")
    try:
        offset = int(request.query_params.get("offset", "0"))
    except (TypeError, ValueError):
        offset = 0
    payload = await get_cashflow_window(user["user_id"], range_key, offset)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


async def _safe_recommendations(user_id: str) -> list:
    try:
        return await recommendations_for_user(user_id)
    except Exception:
        return []


def _month_weeks(year: int, month: int) -> list[list[date | None]]:
    first_weekday, days = monthrange(year, month)
    start_pad = first_weekday % 7
    cells: list[date | None] = [None] * start_pad
    for day in range(1, days + 1):
        cells.append(date(year, month, day))
    while len(cells) % 7:
        cells.append(None)
    return [cells[i : i + 7] for i in range(0, len(cells), 7)]


def _is_mobile_device(request: Request) -> bool:
    """Detect if request is from a mobile device based on User-Agent"""
    user_agent = request.headers.get("user-agent", "").lower()
    mobile_keywords = ["mobile", "android", "iphone", "ipad", "windows phone", "blackberry", "opera mini"]
    return any(keyword in user_agent for keyword in mobile_keywords)


@router.get("/")
@login_required
async def dashboard(request: Request):
    user = request.session.get("user")

    if request.session.get("force_pwd_reset"):
        return RedirectResponse("/reset-password", status_code=303)

    summary, transactions, planning, bills_due_today, recommendations = await asyncio.gather(
        get_dashboard_summary(user["user_id"]),
        get_recent_transactions(user["user_id"], 5),
        get_planning_overlay(user["user_id"]),
        get_bills_due_today(ObjectId(user["user_id"])),
        _safe_recommendations(user["user_id"]),
    )

    now = datetime.now(get_user_timezone(request))
    cal = (planning or {}).get("calendar") or {}
    cal_year = int(cal.get("year") or now.year)
    cal_month = int(cal.get("month") or now.month)

    return templates.TemplateResponse(
        request=request,
        name="pages/dashboard/dashboard.html",
        context={
            "request": request,
            "user": user,
            "summary": summary,
            "planning": planning,
            "transactions": transactions,
            "notifications": summary.get("notifications", []),
            "bills_due_today": bills_due_today,
            "bills_due_today_count": len(bills_due_today),
            "recommendations": recommendations,
            "active_page": "dashboard",
            "now": now,
            "calendar_weeks": _month_weeks(cal_year, cal_month),
            "calendar_days": cal.get("days") or {},
            "calendar_year": cal_year,
            "calendar_month": cal_month,
        },
    )
