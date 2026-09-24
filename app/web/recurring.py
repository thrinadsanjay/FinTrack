from datetime import datetime

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.csrf import verify_csrf_token
from app.core.errors import AppError
from app.core.guards import login_required
from app.core.time import get_user_timezone
from app.helpers.recurring_ui import (
    build_recurring_columns,
    compute_recurring_stats,
    enrich_recurring_rule,
    filter_recurring_rules,
    recurring_query_string,
)
from app.helpers.dashboard_time import app_now
from app.helpers.flash import flash_redirect
from app.services.accounts import get_accounts
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

VALID_STATUS = {"all", "active", "paused", "ended"}
VALID_TYPES = {"", "credit", "debit", "transfer"}


def _normalize_filters(
    *,
    status: str = "all",
    tx_type: str = "",
    account_id: str = "",
    search: str = "",
) -> dict:
    status = (status or "all").strip().lower()
    if status not in VALID_STATUS:
        status = "all"
    tx_type = (tx_type or "").strip().lower()
    if tx_type not in VALID_TYPES:
        tx_type = ""
    return {
        "status": status,
        "tx_type": tx_type,
        "account_id": (account_id or "").strip(),
        "search": (search or "").strip(),
    }


def _list_redirect(request: Request, filters: dict, message: str) -> RedirectResponse:
    query = recurring_query_string(**filters)
    url = f"/recurring?{query}" if query else "/recurring"
    return flash_redirect(request, url, message)


async def _render_recurring_page(
    *,
    request: Request,
    filters: dict,
    edit_id: str | None = None,
    error: str | None = None,
    open_add: bool = False,
    status_code: int = 200,
):
    user = request.session.get("user")
    user_tz = get_user_timezone(request)
    all_rules = await RecurringDepositService.list_user_rules(
        user_id=user["user_id"],
        status="all",
    )
    notifications = await get_user_notifications(user["user_id"])
    accounts = await get_accounts(user["user_id"])

    enriched_all = [enrich_recurring_rule(rule, user_tz=user_tz) for rule in all_rules]
    stats = compute_recurring_stats(enriched_all, user_tz=user_tz)
    visible = filter_recurring_rules(
        enriched_all,
        status=filters["status"],
        tx_type=filters["tx_type"],
        account_id=filters["account_id"],
        search=filters["search"],
    )
    enriched = visible
    columns = build_recurring_columns(enriched, user_tz=user_tz)

    edit_rule = None
    if edit_id:
        edit_rule = await RecurringDepositService.get_user_rule(
            user_id=user["user_id"],
            recurring_id=edit_id,
        )
        if edit_rule:
            edit_rule = enrich_recurring_rule(edit_rule, user_tz=user_tz)

    active_filter_count = sum(
        1
        for key, value in filters.items()
        if value and not (key == "status" and value == "all")
    )

    return templates.TemplateResponse(
        request=request,
        name="pages/transactions/recurring.html",
        context={
            "request": request,
            "user": user,
            "notifications": notifications,
            "active_page": "recurring",
            "rules": enriched,
            "columns": columns,
            "accounts": accounts,
            "filters": filters,
            "status": filters["status"],
            "edit_rule": edit_rule,
            "frequency_options": FREQUENCY_OPTIONS,
            "stats": stats,
            "error": error,
            "open_add": open_add,
            "force_recurring": True,
            "spend_accounts": [acc for acc in accounts if str(acc.get("type") or "") != "loan"],
            "today_iso": app_now().date().isoformat(),
            "active_filter_count": active_filter_count,
            "query_string": recurring_query_string(**filters),
        },
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
@login_required
async def recurring_page(
    request: Request,
    status: str = Query("all"),
    tx_type: str = Query(""),
    account_id: str = Query(""),
    search: str = Query(""),
    edit_id: str | None = Query(None),
    add: str | None = Query(None),
):
    filters = _normalize_filters(
        status=status,
        tx_type=tx_type,
        account_id=account_id,
        search=search,
    )
    return await _render_recurring_page(
        request=request,
        filters=filters,
        edit_id=edit_id,
        open_add=str(add or "") == "1",
    )


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
    tx_type: str = Form(""),
    account_id: str = Form(""),
    search: str = Form(""),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    filters = _normalize_filters(
        status=status,
        tx_type=tx_type,
        account_id=account_id,
        search=search,
    )
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
            filters=filters,
            edit_id=recurring_id,
            error=str(exc),
            status_code=exc.status_code,
        )

    return _list_redirect(request, filters, "Recurring rule updated")


@router.post("/pause")
@login_required
async def pause_recurring_rule(
    request: Request,
    recurring_id: str = Form(...),
    status: str = Form("all"),
    tx_type: str = Form(""),
    account_id: str = Form(""),
    search: str = Form(""),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    filters = _normalize_filters(
        status=status,
        tx_type=tx_type,
        account_id=account_id,
        search=search,
    )
    try:
        await RecurringDepositService.pause_rule(
            user_id=user["user_id"],
            recurring_id=recurring_id,
            request=request,
        )
    except AppError as exc:
        return await _render_recurring_page(
            request=request,
            filters=filters,
            error=str(exc),
            status_code=exc.status_code,
        )
    return _list_redirect(request, filters, "Recurring rule paused")


@router.post("/resume")
@login_required
async def resume_recurring_rule(
    request: Request,
    recurring_id: str = Form(...),
    status: str = Form("all"),
    tx_type: str = Form(""),
    account_id: str = Form(""),
    search: str = Form(""),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    filters = _normalize_filters(
        status=status,
        tx_type=tx_type,
        account_id=account_id,
        search=search,
    )
    try:
        await RecurringDepositService.resume_rule(
            user_id=user["user_id"],
            recurring_id=recurring_id,
            request=request,
        )
    except AppError as exc:
        return await _render_recurring_page(
            request=request,
            filters=filters,
            error=str(exc),
            status_code=exc.status_code,
        )
    return _list_redirect(request, filters, "Recurring rule resumed")


@router.post("/end")
@login_required
async def end_recurring_rule(
    request: Request,
    recurring_id: str = Form(...),
    status: str = Form("all"),
    tx_type: str = Form(""),
    account_id: str = Form(""),
    search: str = Form(""),
    csrf_token: str = Form(...),
):
    verify_csrf_token(request, csrf_token)
    user = request.session.get("user")
    filters = _normalize_filters(
        status=status,
        tx_type=tx_type,
        account_id=account_id,
        search=search,
    )
    try:
        await RecurringDepositService.end_rule(
            user_id=user["user_id"],
            recurring_id=recurring_id,
            request=request,
        )
    except AppError as exc:
        return await _render_recurring_page(
            request=request,
            filters=filters,
            error=str(exc),
            status_code=exc.status_code,
        )
    return _list_redirect(request, filters, "Recurring rule ended")
