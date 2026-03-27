from datetime import datetime, timezone

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.csrf import verify_csrf_token
from app.core.errors import AppError
from app.core.guards import login_required
from app.services.dashboard import get_user_notifications
from app.services.recurring_deposit import RecurringDepositService
from app.web.templates import templates

router = APIRouter()

FREQUENCY_OPTIONS = [
    ("daily", "Daily"),
    ("weekly", "Weekly"),
    ("biweekly", "Biweekly"),
    ("monthly", "Monthly"),
    ("quarterly", "Quarterly"),
    ("halfyearly", "Half-yearly"),
    ("yearly", "Yearly"),
]


async def _render_recurring_page(
    *,
    request: Request,
    status: str,
    edit_id: str | None = None,
    error: str | None = None,
    status_code: int = 200,
):
    user = request.session.get("user")
    rules = await RecurringDepositService.list_user_rules(user_id=user["user_id"], status=status)
    notifications = await get_user_notifications(user["user_id"])

    now = datetime.now(timezone.utc)
    active_count = sum(1 for r in rules if r["status"] == "active")
    paused_count = sum(1 for r in rules if r["status"] == "paused")
    ended_count = sum(1 for r in rules if r["status"] == "ended")

    month_pending_total = 0
    for rule in rules:
        next_run = rule.get("next_run")
        if (
            rule.get("status") == "active"
            and rule.get("type") == "debit"
            and next_run
            and next_run.year == now.year
            and next_run.month == now.month
            and next_run >= now
        ):
            month_pending_total += rule.get("amount", 0)

    edit_rule = None
    if edit_id:
        edit_rule = await RecurringDepositService.get_user_rule(
            user_id=user["user_id"],
            recurring_id=edit_id,
        )

    return templates.TemplateResponse(
        "recurring_list.html",
        {
            "request": request,
            "user": user,
            "notifications": notifications,
            "active_page": "recurring",
            "rules": rules,
            "status": status,
            "edit_rule": edit_rule,
            "frequency_options": FREQUENCY_OPTIONS,
            "stats": {
                "active": active_count,
                "paused": paused_count,
                "ended": ended_count,
                "month_pending": month_pending_total,
            },
            "error": error,
        },
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
@login_required
async def recurring_page(
    request: Request,
    status: str = Query("all"),
    edit_id: str | None = Query(None),
):
    if status not in {"all", "active", "paused", "ended"}:
        status = "all"
    return await _render_recurring_page(request=request, status=status, edit_id=edit_id)


@router.post("/edit")
@login_required
async def edit_recurring_rule(
    request: Request,
    recurring_id: str = Form(...),
    amount: float = Form(...),
    description: str = Form(""),
    frequency: str = Form(...),
    end_date: str | None = Form(None),
    status: str = Form("all"),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        parsed_end_date = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
        await RecurringDepositService.update_rule(
            user_id=user["user_id"],
            recurring_id=recurring_id,
            amount=amount,
            description=description,
            frequency=frequency,
            end_date=parsed_end_date,
            request=request,
        )
    except AppError as exc:
        return await _render_recurring_page(
            request=request,
            status=status,
            edit_id=recurring_id,
            error=str(exc),
            status_code=exc.status_code,
        )

    return RedirectResponse(f"/recurring?status={status}", status_code=303)


@router.post("/pause")
@login_required
async def pause_recurring_rule(
    request: Request,
    recurring_id: str = Form(...),
    status: str = Form("all"),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        await RecurringDepositService.pause_rule(
            user_id=user["user_id"],
            recurring_id=recurring_id,
            request=request,
        )
    except AppError as exc:
        return await _render_recurring_page(
            request=request,
            status=status,
            error=str(exc),
            status_code=exc.status_code,
        )
    return RedirectResponse(f"/recurring?status={status}", status_code=303)


@router.post("/resume")
@login_required
async def resume_recurring_rule(
    request: Request,
    recurring_id: str = Form(...),
    status: str = Form("all"),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        await RecurringDepositService.resume_rule(
            user_id=user["user_id"],
            recurring_id=recurring_id,
            request=request,
        )
    except AppError as exc:
        return await _render_recurring_page(
            request=request,
            status=status,
            error=str(exc),
            status_code=exc.status_code,
        )
    return RedirectResponse(f"/recurring?status={status}", status_code=303)


@router.post("/end")
@login_required
async def end_recurring_rule(
    request: Request,
    recurring_id: str = Form(...),
    status: str = Form("all"),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    try:
        await RecurringDepositService.end_rule(
            user_id=user["user_id"],
            recurring_id=recurring_id,
            request=request,
        )
    except AppError as exc:
        return await _render_recurring_page(
            request=request,
            status=status,
            error=str(exc),
            status_code=exc.status_code,
        )
    return RedirectResponse(f"/recurring?status={status}", status_code=303)
